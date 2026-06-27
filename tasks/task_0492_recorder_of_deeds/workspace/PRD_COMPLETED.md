# Recorder Of Deeds API — Product Requirements Document

## 1. Introduction

County recorders of deeds sit at the intersection of public-record integrity and revenue collection. Every conveyance, mortgage, lien, and plat that touches a parcel of land must be examined for statutory form, assessed for recording fees and transfer taxes, paid for, and finally page-stamped into the permanent land-records books with a unique instrument number that can never be reused. This API models the full back-office of such an office: electronic submission of document packages, examination and rejection, fee and transfer-tax assessment, payment from escrow or card, recording with grantor/grantee indexing, and the downstream products that the public consumes — certified copies and name searches.

The system is built around two non-negotiable disciplines. The first is **segregation of duties**: the examiner who finalizes an assessment may not be the officer who records the same package, so that no single person can both price and perfect a recording. The second is **tamper-evident sequencing**: instrument numbers, book numbers, and page numbers advance monotonically and are never reclaimed, even when a same-day recording is voided for correction. Layered on top are forward-looking escrow accounting that distinguishes settled money from money merely held against pending assessments, optimistic concurrency control that prevents a stale client from overwriting a re-examined assessment or paying an outdated total, and a logical clock that drives recording dates, lien lapse, and continuation windows so that time-dependent behavior is fully deterministic and test-drivable.

This document specifies the contract the implementation must satisfy: the global request/response conventions, the cross-cutting accounting and concurrency principles, the business workflows for each lifecycle, the endpoint surface, and the catalogue of error codes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly four roles, spelled precisely as `Submitter`, `Examiner`, `Recorder`, and `Clerk`. If `X-User-Role` is missing or is not one of these four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When a recognized role attempts an operation it is not permitted to perform under the role matrix in Section 4, the request is rejected with `ERR_FORBIDDEN`.

The four roles differ in how `X-User-ID` is interpreted. When `X-User-Role` is `Submitter`, `X-User-ID` is the `id` of the acting `Submitter` entity; ownership checks on any resource that references a `Submitter` compare the resource's `submitter_id` foreign-key field to `X-User-ID`. This binding governs every owner-scoped action — re-recording, withdrawing, paying, continuing a filing, and terminating a filing — and a mismatch surfaces as `ERR_NOT_OWNER`. By contrast, when `X-User-Role` is `Examiner`, `Recorder`, or `Clerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier — for example, it captures the acting `Examiner`'s `X-User-ID` into the package's `examiner_user_id` when an assessment is finalized — but it never compares an `Examiner`, `Recorder`, or `Clerk` identifier to any entity's `id` for ownership purposes. The one place an opaque identifier is compared is the segregation-of-duties check at recording time, where the acting `Recorder`'s `X-User-ID` must differ from the stored `examiner_user_id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp in ascending order. Every list-based response includes the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id` formatted as a UUID, with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation — and `version`, an integer that begins at its initial value of 1 and increments by one on each mutation. In this domain every entity carries the full set of common fields: `RecordingOffice`, `Submitter`, `DocumentPackage`, `PartyEntry`, `FeeAssessment`, `Payment`, `RecordedDocument`, `RejectionNotice`, `PlatSurvey`, `LienUccFiling`, and `CopySearchRequest` all expose `id`, `created_at`, `updated_at`, and `version`.

The `DocumentPackage` `version` field has a second role beyond audit: it is the optimistic-concurrency anchor described in Section 2.9, and it is bumped by one specifically when an assessment is finalized and when a payment is captured.

Time in this system is driven by a **logical clock**, never by wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it holds that default without ever falling back to the host's real time. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; once set, every `RecordingOffice`'s `recording_date` tracks the new clock value. The `recording_date` is the business date used to stamp recordings and to evaluate lien lapse, continuation windows, and the same-day correction window.

### 2.5. Recording-Office Sequence Counters and Page-Stamp Discipline

Each `RecordingOffice` maintains a family of derived counters that must reconcile exactly with the documents it has recorded. The office is created with a `county_name`, a `book_capacity` (the maximum number of `RECORDED` documents a land-records book holds before it rolls over, which must be at least 1), and an optional `instrument_seq_start` (the first instrument number this office ever mints, defaulting to 1000000). At creation the office's `next_instrument_number` is initialized to `instrument_seq_start`, `current_book` is set to 1, `current_page` is set to 1, and `documents_in_current_book` is set to 0.

When a package is recorded the office stamps the new instrument with the office's then-current values and then advances its counters. The `next_instrument_number` starts at `instrument_seq_start` and rises by one for each document recorded. The `current_book` is the active land-records book number; it starts at 1 and rises by one each time `documents_in_current_book` reaches `book_capacity`. The `current_page` is the next page within the current book; it starts at 1, advances by the recorded document's page count, and resets to 1 whenever the book rolls over. The `documents_in_current_book` counts the `RECORDED` documents whose book equals `current_book`; it starts at 0 and resets to 0 on a book roll. The full page-stamp and roll mechanics, including the order in which these counters move, are detailed in Section 3.5.

Two ledger-style counters round out the office. The `daily_collected_cents` is a running ledger of `total_due_cents` collected for `RECORDED` documents; it starts at 0 and is reconciled only at those two events — rising by a package's assessment `total_due_cents` when the package records and falling by that same amount when a recording is voided for correction — and it is never recomputed or reset by the passage of the logical clock, so advancing `recording_date` to a new day does not zero it out and it continues to accumulate across days. The `total_indexed_entries` is the count of `PartyEntry` rows in `INDEXED` status across all recorded packages, starting at 0, and likewise rises and falls only as entries are indexed at recording and voided at correction. Both counters always equal that live event-driven accumulation over their underlying rows.

### 2.6. Escrow Accounting: Settled, Held, and Available

Each `Submitter` is registered with a `name` and a `submitter_type`, which is one of `TITLE_COMPANY`, `ATTORNEY`, `SELF`, or `GOVERNMENT`. A submitter's `status` is `ACTIVE` on registration and may become `SUSPENDED`; a `SUSPENDED` submitter may neither submit new packages nor re-record. The submitter carries four monetary counters, all in integer cents, and they must be kept distinct because the system deliberately separates money that has actually moved from money that is merely earmarked.

The `escrow_deposited_total_cents` is the lifetime sum of all escrow deposits ever credited to the submitter; it begins at 0 and rises by each deposit amount. The `escrow_balance_cents` is **settled** escrow — the deposited lifetime total minus the sum of `amount_cents` over this submitter's `CAPTURED` escrow-method payments. Settled balance is reduced only by captured payments and is never reduced by a mere hold. The `escrow_held_cents` is a **forward-looking hold** — the sum of `total_due_cents` for this submitter's packages whose assessment is `FINALIZED` and whose package is still in `ASSESSED` status (that is, finalized but not yet paid, voided, or otherwise consumed). The `escrow_available_cents` is the spendable figure: it is the settled `escrow_balance_cents` minus the `escrow_held_cents`. A hold therefore reduces what is available to spend without reducing the settled balance; only a captured payment reduces the settled balance. The precise recomputation triggers are given in Section 3.4.

### 2.7. Monetary Precision and Rounding

All monetary amounts in this system are integer cents. The recording-fee computation is purely additive over integer terms and requires no rounding. Where a percentage-based charge is computed — the transfer tax and the records-management surcharge — the result is rounded half up to whole cents. Critically, when several such components are summed into a single total, each component is rounded to whole cents independently and only then are the rounded components added together; the system never sums raw fractional values and rounds once at the end. The exact formulas, their constants, and the pinned round-then-sum order appear in Section 3.3.

### 2.8. Hierarchical Consistency, Cascades, and Nested Retrieval

A single business operation frequently mutates more than one resource, and the system commits all such effects together. Recording a package, for example, mints a `RecordedDocument`, advances office sequence counters, may roll a book, flips party entries to `INDEXED`, and updates two office ledgers — all as one atomic transition. Voiding a recording for correction reverses the compensable parts of that cascade. Rejecting a package both voids its finalized assessment and releases the corresponding escrow hold. Each of these cascades is specified in full in Section 3; wherever a mutation occurs, the affected resource's `updated_at` is refreshed and, for resources that carry it, `version` is incremented.

For nested retrieval and nested mutation, path identifiers are validated left-to-right. When a path names a parent resource and then a child (for instance, a payment under a package), the parent's existence is confirmed before the child's. The first identifier in the path that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND`, and that check precedes any business-rule evaluation.

### 2.9. Optimistic Concurrency Control on the Document Package

Two write operations against a `DocumentPackage` are guarded by optimistic concurrency control keyed on the package's `version`. Both require the client to send `expected_package_version` as a mandatory field carrying the `version` the client last observed for that package; the field is never optional on these two operations, and no other endpoint accepts a version field.

When an assessment is finalized, the request must carry `expected_package_version` equal to the target package's current `version`. A re-examination legitimately creates a new `FINALIZED` assessment that supersedes the prior one, advancing the package's `version`; if another writer has advanced that `version` since the client last read it, the finalize is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412) so the client cannot silently overwrite a newer assessment it never observed. Likewise, when a payment is captured, the request must carry `expected_package_version` equal to the package's current `version`; because a newer assessment may have superseded the one the client priced against, a stale package version is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412) rather than letting the payment apply to an outdated total. In both cases the rejection is framed purely in terms of the observed-versus-current version, independent of any timing of requests.

### 2.10. Validation Ordering

When a request could fail multiple checks, the system evaluates them in a fixed priority order so that the same input always produces the same error. Authentication is checked first: a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization is second: a recognized role not permitted for the operation yields `ERR_FORBIDDEN`. Third, every path and body resource identifier is resolved left-to-right, and an unresolved id yields `ERR_NOT_FOUND`. Fourth, on any POST or PATCH the request body is validated for required fields, correct types and enum values, non-negative numeric amounts, and the copy/search field-combination rule, with failures yielding `ERR_INVALID_REQUEST`. Fifth, the target resource must be in a valid source state for the requested transition, or the request is rejected with `ERR_INVALID_STATE`. Sixth, for owner-scoped actions (re-record, withdraw, payments, continue, terminate) the acting submitter must own the resource, or the request is rejected with `ERR_NOT_OWNER`.

The remaining priority bands carry the domain rules and are evaluated after the six structural bands above. Seventh come the compliance and safety checks (submitter not suspended, segregation of duties, and the margin and notary defects that block examination approval). Eighth come index-completeness and cross-entity state checks (at least one grantor and one grantee; assessment finalized before payment; document recorded before a certified copy). Ninth come the temporal-overlap and window rules (plat lot-range overlap, tax-lien period overlap with its grace buffer, the continuation window and lapse, and the same-day correction window). Tenth come the fiscal checks (payment amount equals the finalized total; escrow sufficiency for escrow-method payments). Eleventh and last is the optimistic-concurrency check that `expected_package_version` matches the package's current `version`. Where a single subsection below lists several checks for one operation, this global ordering governs which error surfaces first.

## 3. Business Logic & Workflows

### 3.1. Submitters, Offices, and Escrow Funding

The lifecycle begins with front-office setup performed by a `Clerk`. A clerk creates a `RecordingOffice` by supplying a `county_name` and a `book_capacity`, optionally overriding the `instrument_seq_start`; the office comes up with its sequence counters initialized as described in Section 2.5 and its `recording_date` tracking the logical clock. A clerk registers a filing party as a `Submitter` by supplying a `name` and a `submitter_type`; the new submitter is `ACTIVE` with all four escrow counters at zero. A clerk may later suspend a submitter, flipping `status` to `SUSPENDED`; suspended submitters are barred from submitting and re-recording.

Escrow is funded through the office cashier. A clerk deposits escrow on behalf of a submitter by naming the `submitter_id` and an `amount_cents`; the deposit raises that submitter's `escrow_deposited_total_cents` and `escrow_balance_cents` by the deposited amount and triggers a recomputation of `escrow_available_cents`. Deposits are the only inflow to settled escrow.

### 3.2. Submitting and Indexing a Document Package

A `Submitter` initiates a filing by submitting a `DocumentPackage`. The submission names the `submitter_id` and `office_id`, declares the `doc_type` — one of `DEED`, `MORTGAGE`, `LIEN`, `UCC`, `PLAT`, or `OTHER` — and provides a `declared_page_count` (at least 1), the `first_page_top_margin_inches` of the first page, and a `notary_present` boolean indicating whether a complete acknowledgement/notary block is present. The submitter may also declare a `declared_consideration_cents` for the transfer-tax estimate; for non-conveyance documents this is 0, and 0 is its default when omitted. A submission may only be made by a submitter whose `status` is `ACTIVE`. The package is born in `SUBMITTED` status. Its `verified_page_count` and `verified_consideration_cents` remain unset until examination, its `examiner_user_id` is unset until an assessment is finalized, and its `resubmission_count` starts at 0.

At submission time the system can produce an **estimated** transfer tax from the `declared_consideration_cents` — using the same threshold formula as the authoritative computation but against the declared figure. This estimate is informational only and is not persisted onto any `FeeAssessment`; it may differ from the final figure if the examiner verifies a different consideration. The authoritative value is always the final variant computed at examination approval from the verified consideration.

Indexing is built up by adding grantor/grantee entries. A submitter adds a `PartyEntry` to a package by supplying a `party_role` (`GRANTOR` or `GRANTEE`) and a `party_name`. Each entry references its `package_id` and is born `PENDING`; it remains `PENDING` until the package is recorded, becomes `INDEXED` on recording, and becomes `VOIDED` if the package is withdrawn or its recording is later corrected. A package may be withdrawn by its owning submitter while it is in `SUBMITTED` or `REJECTED` status; withdrawal moves the package to `WITHDRAWN` and voids all of its `PartyEntry` rows.

### 3.3. Examination, Rejection, and the Re-Record Loop

When an `Examiner` begins examination of a package, the package advances from `SUBMITTED` to `IN_EXAMINATION`. This transition is gated on two preconditions: the owning submitter must be `ACTIVE`, or the request is rejected with `ERR_SUBMITTER_SUSPENDED`; and the package must already carry at least one `PartyEntry` whose `party_role` is `GRANTOR` and at least one whose `party_role` is `GRANTEE`, or it is rejected with `ERR_INDEX_INCOMPLETE`.

**Approving the examination** is the act of finalizing a `FeeAssessment`, and it is the system's most consequential transition. It is valid when the package is in `IN_EXAMINATION` status — finalizing a fresh assessment — and also when the package is already in `ASSESSED` status, which is the re-examination case that creates a new `FINALIZED` assessment superseding the prior one per Section 2.9; any other source state is rejected with `ERR_INVALID_STATE`. The examiner supplies the `verified_page_count`, the `verified_consideration_cents`, and the `expected_package_version`. Approval is blocked unless the first-page top margin is at least the minimum top margin of 3.0 inches — a margin of exactly 3.0 inches passes — otherwise the request is rejected with `ERR_MARGIN_DEFECT`. Approval is also blocked unless `notary_present` is true, otherwise it is rejected with `ERR_NOTARY_DEFECT`. The request must also supply both verified figures, and the `expected_package_version` must match the package's current `version` per Section 2.9. When all checks pass, the package's `verified_page_count` and `verified_consideration_cents` are set from the request; a new `FeeAssessment` is created in `FINALIZED` status with its component fees computed; any prior `FeeAssessment` for the package is set to `SUPERSEDED`; the package's `examiner_user_id` is set to the acting examiner's `X-User-ID`; the submitter's `escrow_held_cents` is increased by the new `total_due_cents` and `escrow_available_cents` is recomputed; the package advances to `ASSESSED`; and the package's `version` is incremented by one.

The `FeeAssessment` records its `package_id`, the computed `recording_fee_cents`, `transfer_tax_cents`, `records_mgmt_cents`, and `total_due_cents`, and its `status` (`FINALIZED`, `SUPERSEDED`, or `VOIDED`). The three component fees are computed as follows.

The **recording fee** has three additive parts. The page part is a base first-page fee of 2,500 cents plus an additional-page fee of 500 cents for each page beyond the first — that is, 500 cents multiplied by the verified page count minus one, but never below zero pages. The index part is an index surcharge of 200 cents for each non-VOIDED party entry beyond the first four free entries — that is, 200 cents multiplied by the count of non-VOIDED `PartyEntry` rows (grantors and grantees together) minus four, but never below zero entries. The doc-type part is a surcharge that depends on the package's `doc_type`: 1,000 cents for `DEED`, 1,500 cents for `MORTGAGE`, 800 cents for `LIEN`, 500 cents for `UCC`, 3,000 cents for `PLAT`, and 0 cents for `OTHER`. The `recording_fee_cents` is the sum of these three parts; all terms are integer cents and no rounding is applied.

The **transfer tax** is threshold-based. If the verified consideration is at most the exempt threshold of 10,000 cents (that is, one hundred dollars or less is exempt), the `transfer_tax_cents` is 0. Otherwise it is the verified consideration multiplied by the tax rate of 55 basis points, divided by 10,000, rounded half up to whole cents.

The **records-management surcharge** mirrors the transfer-tax threshold. If the verified consideration is at most the same exempt threshold of 10,000 cents, the `records_mgmt_cents` is 0. Otherwise it is the verified consideration multiplied by the records-management rate of 13 basis points, divided by 10,000, rounded half up to whole cents.

The **total due** is assembled with the pinned round-then-sum order: the `transfer_tax_cents` and `records_mgmt_cents` are each rounded half up to whole cents independently as just described, and then `total_due_cents` is the integer sum of `recording_fee_cents`, `transfer_tax_cents`, and `records_mgmt_cents`. The system never sums the raw fractional tax and surcharge before rounding.

**Rejection** is the examiner's alternative outcome. It is valid when the package is in `IN_EXAMINATION` status and also when it is already in `ASSESSED` status — where the cascade additionally voids the `FINALIZED` assessment and releases its hold as described below — while any other source state is rejected with `ERR_INVALID_STATE`. Rejecting a package requires a `reason_code` — one of `MARGIN`, `NOTARY`, `LEGAL_DESCRIPTION`, `INDEX_INCOMPLETE`, or `FEE_DISCREPANCY` — and accepts an optional free-text `detail`. The rejection cascade has three linked effects: a `RejectionNotice` recording the `reason_code` and `detail` is created (its `cured` flag starts false); any `FINALIZED` `FeeAssessment` for the package is set to `VOIDED`; and voiding that assessment releases its hold, so the submitter's `escrow_held_cents` decreases by that assessment's `total_due_cents` and `escrow_available_cents` is recomputed. The package then moves to `REJECTED`.

**Re-recording** closes the loop. The owning submitter corrects and resubmits a rejected package, which requires that the acting submitter own the package and that the submitter's `status` be `ACTIVE`, otherwise the request is rejected with `ERR_SUBMITTER_SUSPENDED`. The re-record applies whichever corrected fields are provided — `declared_page_count`, `declared_consideration_cents`, `first_page_top_margin_inches`, and `notary_present` — marks the latest `RejectionNotice` as `cured` (its `cured` flag becomes true), increments `resubmission_count` by one, and returns the package to `IN_EXAMINATION`. This is the cyclic `REJECTED → IN_EXAMINATION` path, and a package may traverse it repeatedly.

### 3.4. Payment and the Escrow Hold-to-Spend Conversion

Once a package is `ASSESSED`, its owning submitter pays the finalized assessment. The payment supplies an `amount_cents`, a `method` (`ESCROW` or `CARD`), and the `expected_package_version`. Several preconditions guard the capture: there must be a `FINALIZED` `FeeAssessment` for the package, or the request is rejected with `ERR_ASSESSMENT_NOT_FINALIZED`; the `amount_cents` must equal that finalized assessment's `total_due_cents`, or the request is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`; and when the `method` is `ESCROW`, the submitter's settled `escrow_balance_cents` must be at least the `amount_cents`, or the request is rejected with `ERR_ESCROW_INSUFFICIENT`. The `expected_package_version` must also match the package's current `version` per Section 2.9.

On a successful capture the system creates a `Payment` in `CAPTURED` status recording its `package_id`. If the method is `ESCROW`, the submitter's `escrow_balance_cents` decreases by the `amount_cents`, drawing down settled escrow. In all cases the hold converts to spend: the submitter's `escrow_held_cents` decreases by the assessment's `total_due_cents` and `escrow_available_cents` is recomputed. The package advances to `PAID` and its `version` is incremented by one. A payment that cannot be captured because escrow is insufficient or the amount does not match is not persisted as a successful capture; the `status` enum also admits `FAILED` for a payment that did not capture.

The escrow figures are recomputed on assessment finalize, on assessment void, on payment capture, and on escrow deposit. Settled `escrow_balance_cents` is the lifetime `escrow_deposited_total_cents` minus the sum of `amount_cents` over the submitter's `CAPTURED` escrow-method payments, taken in chronological order, reflecting only money actually drawn and ignoring pending holds. The forward-looking `escrow_held_cents` is the sum of `total_due_cents` over the submitter's packages whose assessment is `FINALIZED` and whose package status is `ASSESSED`. The spendable `escrow_available_cents` is `escrow_balance_cents` minus `escrow_held_cents`; a hold thus lowers available without lowering the settled balance, while a capture lowers the settled balance.

### 3.5. Recording: Page-Stamp, Instrument Mint, and Indexing

Recording perfects a paid package, and it is reserved for a `Recorder` who is not the examiner of record. The segregation-of-duties precondition requires that the acting recorder's `X-User-ID` differ from the package's stored `examiner_user_id`; if they are equal the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. The package must also still satisfy index completeness — at least one `GRANTOR` and at least one `GRANTEE` party entry — or it is rejected with `ERR_INDEX_INCOMPLETE`.

When recording proceeds, a `RecordedDocument` is minted against the office's current counters: its `instrument_number` is taken from the office's `next_instrument_number`, its `book` from the office's `current_book`, its `page` from the office's `current_page`, and its `recorded_on` from the office's `recording_date`. The new document records its `package_id` and is born `RECORDED`. The mint then advances the office: `next_instrument_number` increases by one, `current_page` advances by the package's `verified_page_count`, and `documents_in_current_book` increases by one. If, after that increment, `documents_in_current_book` reaches the office's `book_capacity`, the book rolls: `current_book` increases by one, `documents_in_current_book` resets to 0, and `current_page` resets to 1. Alongside the mint, every `PartyEntry` for the package transitions from `PENDING` to `INDEXED` and the office's `total_indexed_entries` increases by that count, and the office's `daily_collected_cents` increases by the assessment's `total_due_cents`. The package itself advances from `PAID` to `RECORDED`, a terminal state.

A recording may be voided for correction by a `Recorder`, but only on the same recording day: the `RecordedDocument`'s `recorded_on` must equal the office's current `recording_date`, otherwise the request is rejected with `ERR_CORRECTION_WINDOW_CLOSED`. A void-correction sets the document's `status` to `CORRECTED_VOID` and reverses the compensable parts of the recording cascade: the office's `documents_in_current_book` decreases by one, the office's `daily_collected_cents` decreases by that package's `total_due_cents`, and the package's `PartyEntry` rows move from `INDEXED` to `VOIDED` with the office's `total_indexed_entries` decreasing by that count. The instrument number is deliberately not reclaimed and `next_instrument_number` is left unchanged, preserving a tamper-evident sequence.

### 3.6. Plats and Surveys: Lot-Range Reservation

A `Submitter` files a `PlatSurvey` to reserve a contiguous block of lots. The filing names the `submitter_id` and `office_id`, the `subdivision_name`, the `block_number`, and the inclusive lot range as `start_lot` and `end_lot`, where the end lot is at least the start lot. The plat is born `SUBMITTED`. Its `plat_book` and `plat_page` remain unset until it is recorded.

An `Examiner` approves a submitted plat, advancing it from `SUBMITTED` to `APPROVED`. Approval requires that `end_lot` be at least `start_lot`, or the request is rejected with `ERR_INVALID_LOT_RANGE`; and that no already-`RECORDED` plat on the same `office_id`, `subdivision_name`, and `block_number` have a closed inclusive lot range that overlaps this plat's range, or the request is rejected with `ERR_LOT_RANGE_OVERLAP`. Two closed inclusive ranges overlap whenever each one's start is not greater than the other's end. An examiner may instead reject a submitted plat, moving it to `REJECTED` with no preconditions.

A `Recorder` records an approved plat, advancing it from `APPROVED` to `RECORDED`. Because other plats may have recorded in the interim, the overlap check is re-evaluated at record time against the already-`RECORDED` plats on the same subdivision and block, and a fresh overlap is rejected with `ERR_LOT_RANGE_OVERLAP`. On recording, the plat is page-stamped: its `plat_book` is set from the office's `current_book` and its `plat_page` from the office's `current_page`.

### 3.7. Liens and UCC Filings: Lapse, Continuation, and Tax-Lien Exclusivity

A `Submitter` files a `LienUccFiling` against a parcel. The filing names the `submitter_id` and `office_id`, the `lien_type` — one of `UCC1`, `TAX_LIEN`, `JUDGMENT_LIEN`, or `MECHANICS_LIEN` — the `parcel_id` the lien attaches to, the `debtor_name`, and the `effective_date` on which the lien period begins inclusively. On creation the filing's `lapse_date` is set to the effective date plus the lapse term of five years, its `continuation_count` starts at 0, and its `status` is `ACTIVE`.

**Tax-lien exclusivity** is enforced at creation for `TAX_LIEN` filings only, using a mandatory grace buffer between consecutive tax-lien periods on a parcel. A new `TAX_LIEN` is rejected with `ERR_TAX_LIEN_OVERLAP` if there exists an `ACTIVE` `TAX_LIEN` on the same `parcel_id` whose buffered period contains the new lien's effective date — that is, when the new lien's `effective_date` is earlier than the existing lien's `lapse_date` plus the tax-lien grace buffer of 30 days, and the new lien's `effective_date` is at the same time on or after the existing lien's `effective_date`. Adjacency therefore requires at least the 30-day grace gap before a successor tax lien may begin.

**Lapse** is derived lazily on read. A filing's `status` becomes `LAPSED` when the office's `recording_date` reaches or passes its `lapse_date` — the boundary is inclusive, so a filing is `LAPSED` exactly at its `lapse_date`. This evaluation happens when the filing is fetched: if the recording date is at or beyond the lapse date and the filing is still `ACTIVE`, it is observed as `LAPSED`. Advancing the logical clock is what makes a lapse observable. Once lapsed, the filing is terminal for enforcement and continuation is no longer accepted.

**Continuation** extends a still-active filing and forms a self-loop on `ACTIVE`. The owning submitter files a continuation, which requires that the acting submitter own the filing; that the office's `recording_date` be strictly before the `lapse_date`, or the request is rejected with `ERR_FILING_ALREADY_LAPSED`; and that the office's `recording_date` be on or after the lapse date minus the continuation window of 180 days — meaning continuation is permitted only within the 180 days immediately before lapse — or the request is rejected with `ERR_CONTINUATION_TOO_EARLY`. A successful continuation pushes the `lapse_date` forward by another five years and increments `continuation_count` by one. The owning submitter may also terminate the filing, moving its `status` to `TERMINATED`.

### 3.8. Certified Copies and Name Searches

A `Submitter` requests a public-records product through a `CopySearchRequest`, naming the `submitter_id` and a `request_type` of either `CERTIFIED_COPY` or `NAME_SEARCH`. The field combination is strict: for a `CERTIFIED_COPY` the request must carry a `recorded_document_id` and must not carry a `search_name`; for a `NAME_SEARCH` it must carry a `search_name` and must not carry a `recorded_document_id`. A violation of this combination is an `ERR_INVALID_REQUEST`. The request is born `REQUESTED`, and its flat `fee_cents` is computed on creation: a `CERTIFIED_COPY` costs 1,500 cents and a `NAME_SEARCH` costs 800 cents.

A `Clerk` fulfills a request. For a `CERTIFIED_COPY`, the referenced `RecordedDocument` must exist and be in `RECORDED` status, or the request is rejected with `ERR_DOCUMENT_NOT_RECORDED`. On fulfillment the request moves to `FULFILLED` and its `result_count` is set: a `CERTIFIED_COPY` yields a copy count of 1, while a `NAME_SEARCH` yields the count of `INDEXED` `PartyEntry` rows whose `party_name` equals the `search_name`. A clerk may instead deny a request, moving it to `DENIED` with no preconditions.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions, suspensions, deposits, and the clock-setting capability — return `200 OK`, except that the assessment, rejection, and payment creations, which mint new child resources, return `201 Created` as noted below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/offices` | Create a recording office | Clerk |
| GET | `/offices/{id}` | Get a recording office | Clerk, Examiner, Recorder, Submitter |
| POST | `/offices/{id}/deposit-escrow` | Credit escrow to a submitter | Clerk |
| POST | `/submitters` | Register a filing party | Clerk |
| GET | `/submitters/{id}` | Get a submitter | Clerk, Examiner, Recorder, Submitter |
| POST | `/submitters/{id}/suspend` | Suspend a submitter | Clerk |
| GET | `/submitters` | List submitters | Clerk, Examiner, Recorder |
| POST | `/packages` | Submit a document package | Submitter |
| GET | `/packages/{id}` | Get a document package | Clerk, Examiner, Recorder, Submitter |
| GET | `/packages` | List/filter document packages | Clerk, Examiner, Recorder, Submitter |
| POST | `/packages/{id}/party-entries` | Add a grantor/grantee index entry | Submitter |
| GET | `/packages/{id}/party-entries` | List a package's index entries | Clerk, Examiner, Recorder, Submitter |
| POST | `/packages/{id}/begin-examination` | Begin examination of a package | Examiner |
| POST | `/packages/{id}/assessments` | Finalize the fee/transfer-tax assessment | Examiner |
| GET | `/packages/{id}/assessments` | List a package's fee assessments | Clerk, Examiner, Recorder, Submitter |
| POST | `/packages/{id}/reject` | Reject a package under examination | Examiner |
| GET | `/packages/{id}/rejections` | List a package's rejection notices | Clerk, Examiner, Recorder, Submitter |
| POST | `/packages/{id}/re-record` | Re-record a rejected package | Submitter |
| POST | `/packages/{id}/payments` | Pay a package's finalized assessment | Submitter |
| GET | `/packages/{id}/payments` | List a package's payments | Clerk, Examiner, Recorder, Submitter |
| POST | `/packages/{id}/record` | Record a paid package | Recorder |
| GET | `/packages/{id}/recorded-document` | Get the recorded instrument(s) for a package — returned as a paginated `array` envelope (the `RecordedDocument` rows for the package, sorted by `created_at` ascending, with the `limit`/`offset`/`total_count`/`has_more` pagination fields), not as a single bare object | Clerk, Examiner, Recorder, Submitter |
| POST | `/packages/{id}/withdraw` | Withdraw a submitted or rejected package | Submitter |
| GET | `/recorded-documents/{id}` | Get a recorded instrument by id | Clerk, Examiner, Recorder, Submitter |
| POST | `/recorded-documents/{id}/void-correction` | Void a recording for correction | Recorder |
| POST | `/plats` | Submit a plat/survey | Submitter |
| GET | `/plats/{id}` | Get a plat/survey | Clerk, Examiner, Recorder, Submitter |
| GET | `/plats` | List/filter plats/surveys | Clerk, Examiner, Recorder, Submitter |
| POST | `/plats/{id}/approve` | Approve a plat | Examiner |
| POST | `/plats/{id}/reject` | Reject a plat | Examiner |
| POST | `/plats/{id}/record` | Record an approved plat | Recorder |
| POST | `/ucc-filings` | File a lien / UCC statement | Submitter |
| GET | `/ucc-filings/{id}` | Get a lien/UCC filing | Clerk, Examiner, Recorder, Submitter |
| GET | `/ucc-filings` | List/filter lien/UCC filings | Clerk, Examiner, Recorder, Submitter |
| POST | `/ucc-filings/{id}/continue` | File a continuation statement | Submitter |
| POST | `/ucc-filings/{id}/terminate` | Terminate a lien/UCC filing | Submitter |
| POST | `/copy-search-requests` | Request a certified copy or name search | Submitter |
| GET | `/copy-search-requests/{id}` | Get a copy/search request | Clerk, Examiner, Recorder, Submitter |
| GET | `/copy-search-requests` | List/filter copy/search requests | Clerk, Examiner, Recorder, Submitter |
| POST | `/copy-search-requests/{id}/fulfill` | Fulfill a copy/search request | Clerk |
| POST | `/copy-search-requests/{id}/deny` | Deny a copy/search request | Clerk |
| POST | `/_clock/set_current_utc` | Set the logical clock | Clerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_SUBMITTER_SUSPENDED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_MARGIN_DEFECT` | 409 |
| `ERR_NOTARY_DEFECT` | 409 |
| `ERR_INDEX_INCOMPLETE` | 409 |
| `ERR_ASSESSMENT_NOT_FINALIZED` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 409 |
| `ERR_ESCROW_INSUFFICIENT` | 409 |
| `ERR_DOCUMENT_NOT_RECORDED` | 409 |
| `ERR_INVALID_LOT_RANGE` | 422 |
| `ERR_LOT_RANGE_OVERLAP` | 409 |
| `ERR_TAX_LIEN_OVERLAP` | 409 |
| `ERR_CONTINUATION_TOO_EARLY` | 409 |
| `ERR_FILING_ALREADY_LAPSED` | 409 |
| `ERR_CORRECTION_WINDOW_CLOSED` | 409 |
| `ERR_STALE_PACKAGE_VERSION` | 412 |
