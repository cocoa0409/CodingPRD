# USPTO Patent Prosecution API — Product Requirements Document

## 1. Introduction

Filing and prosecuting a patent at the United States Patent and Trademark Office is a long-running, calendar-driven workflow whose every step is mediated by an exact fee, a statutory deadline, and a rigid sequencing rule. An applicant who underpays by a dollar, who misses a six-month maximum response window by an hour, or who attempts to convert a provisional application a day past its first anniversary, is treated by USPTO operations no differently from someone who never filed at all — the application is abandoned, the conversion right is consumed, the patent expires. The cost of this rigidity is borne by applicants who must reason simultaneously about four fee schedules (Large/Small/Micro entity tiers across utility, design, provisional, and PCT national phase filings), a cyclic examiner-applicant exchange, three maintenance windows spanning 11.5 years, and the singular 30-month deadline that controls international filings entering the U.S. national phase.

This document specifies the contract for a back-office service that USPTO operations and authenticated applicants use to perform that workflow under machine discipline. It covers applicant onboarding (including the micro-entity income qualification test), the four application types and their continuation relationships, the docketing → office-action → response cycle, conversion of provisionals to utilities within their twelve-month window, issuance and the three downstream maintenance windows for utility patents, and the PCT national phase entry pathway. Because deadlines drive most state transitions, the service exposes test-driving endpoints under the `/_<name>` prefix so that the deadline sweeper and the logical clock can be advanced deterministically without waiting for wall-clock time. Concurrency is handled optimistically: the two operations that consume a non-renewable application right — paying the issue fee and converting a provisional — require the caller to assert the application version they observed, and a mismatch is rejected rather than retried.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming one of three roles — `Applicant`, `USPTOExaminer`, or `USPTOAdmin`. A request missing either header, carrying an unknown role string, or naming an `X-User-ID` that does not resolve to an existing applicant when the role is `Applicant`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role lacks permission for the endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles map to identity in different ways. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` entity; ownership checks on any resource that references an applicant (notably an `Application` whose `applicant_id` names the caller, plus all downstream office-action responses, fee payments, and PCT phase entries derived from those applications) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `USPTOExaminer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server may record it for audit but does not compare it to any entity's `id`. When `X-User-Role` is `USPTOAdmin`, `X-User-ID` is likewise an opaque operator identifier; an admin is the only role permitted to drive the test clock and the deadline sweeper, but an admin is not a substitute for an applicant on applicant-only mutations (filing, paying the issue fee, converting a provisional, filing an office-action response, posting fee payments, or recording a PCT national phase entry).

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; the `offset` parameter defaults to 0 and must be non-negative. All list responses are sorted by `created_at` in ascending order. The `meta` block of every list response surfaces `limit`, `offset`, `total_count` (the number of records matching the filter before pagination), and `has_more` (true when more records exist beyond the current page).

### 2.4. Resource Identity and Audit Fields

Most resources in this system — `Applicant`, `Application`, `OfficeAction`, `OfficeActionResponse`, `MaintenanceFee`, and `PCTPhaseEntry` — carry four common audit fields: `id` (a server-minted UUID with no type prefix), `created_at` (the ISO 8601 UTC instant the row was inserted, with three fractional digits), `updated_at` (the ISO 8601 UTC instant of the most recent mutation, with three fractional digits), and `version` (an integer that starts at 1 on creation and increments by exactly 1 on every server-driven mutation of the row, including state transitions and computed-field recomputations). The `FeePayment` entity is append-only and so carries only `id` and `created_at`; it has no `updated_at` and no `version` because no operation ever mutates a posted payment.

Whenever a workflow advances an entity's lifecycle — for example, an examiner dockets a filed application, or a maintenance payment posts and recomputes the parent's `total_fees_paid_cents` — `updated_at` is refreshed and `version` is bumped on every row that was actually mutated by that operation. Cascading transitions bump the version of every cascaded entity independently (one bump on the parent, one bump on each touched child).

### 2.5. Nested Path Resolution

Endpoints that template a resource id in the URL (for example, the docket, pay-issue-fee, and convert endpoints under `/applications/{id}`) resolve the path segments left to right. If a path-templated id does not match any existing record of the corresponding entity, the request is rejected with `ERR_APPLICATION_NOT_FOUND` (HTTP 404) before any body parsing or role check on the request body takes place. The same `ERR_APPLICATION_NOT_FOUND` is raised when a request body references a foreign key — `applicant_id`, `application_id`, `office_action_id`, `parent_application_id`, or `maintenance_fee_id` — that does not resolve to an existing row.

### 2.6. Money, Time, and Precision

All monetary amounts in this system are denominated in U.S. dollar cents as non-negative integers; there are no fractional cents and no other currencies. Every calculated fee follows the same procedure: take the base amount in cents from the calculation's constant table, multiply by the applicant's entity-size multiplier (1.00 for `LARGE`, 0.50 for `SMALL`, 0.20 for `MICRO`), round the product to the nearest integer using round-half-up, and compare the result for exact equality against the applicant's submitted `amount_cents`. Greater is rejected just as firmly as less.

All datetimes — `filing_date`, `issue_date`, `priority_date`, `term_expiration_date`, `paid_at`, `response_filed_at`, `pct_international_filing_date`, `national_phase_due_date`, `shortened_due_date`, `maximum_due_date`, `window_open_date`, `window_due_date`, and `window_grace_date` — are recorded as ISO 8601 UTC instants with three fractional digits. The server maintains a single logical clock, `current_utc`, that all deadline comparisons read from. Tests pin this clock by calling the admin-only test-driving capability that takes a `to_iso8601` instant.

### 2.7. Order of Validation

Every endpoint runs its checks in a fixed priority order so that the rejection reason returned to the caller is deterministic. Authentication is evaluated first (in two steps: `X-User-Role` is present and known, then `X-User-ID` is present and resolves), then role authorization, then existence of any path-templated resource, then existence of any body-referenced foreign key. Only after these gates pass does the server evaluate state-machine admissibility (`ERR_INVALID_STATE` if the transition is not defined out of the current state, `ERR_TERMINAL_STATE` if the source state is in the entity's terminal set — namely `ABANDONED`, `EXPIRED`, `CONVERTED` for an application, `RESPONDED`, `EXPIRED`, `WITHDRAWN` for an office action, and `PAID`, `LAPSED` for a maintenance fee, with the single exception that an `ISSUED` application is permitted to transition to `EXPIRED` via maintenance-fee lapse), followed by business rules in the order: continuation-relationship coherence, micro-entity eligibility, PCT 30-month timeliness, provisional-conversion 12-month timeliness, single-shot conversion, maintenance-fee window timeliness, fee-amount exactness, claim-count range, maintenance-window ordering, extension-month range, OCC version match, single-outstanding office action, and singleton PCT phase entry. Within a single endpoint's checks, any earlier rule short-circuits later ones; a request that fails both an existence check and a fee-amount check is reported as not-found, never as fee-mismatch.

### 2.8. Optimistic Concurrency Control

Two endpoints — paying the issue fee and converting a provisional, both addressed at a specific application via `/applications/{id}/pay-issue-fee` and `/applications/{id}/convert-provisional-to-utility` — consume a non-replayable right on the parent `Application`, so both require the caller to assert the application version they last observed. Each request body must include `expected_application_version` as a non-optional integer field, and if that value does not equal the target application's current `version` at the moment the server evaluates the request, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no row is mutated. The pay-issue-fee guard captures the case where another writer has already paid (legitimately advancing the application's version to `ISSUED` and minting `issued_patent_number`), so the current writer's view is stale and a second payment would double-charge. The convert-provisional guard captures the case where another writer has already converted (legitimately consuming the conversion right and flipping `status` to `CONVERTED`), so the second conversion attempt is against a stale view of an already-converted provisional. Endpoints not listed above — application creation, docketing, office-action creation, office-action-response filing, fee payments other than the issue fee, PCT phase entry recording — do not take any version field; they are protected by state-machine and uniqueness rules instead.

### 2.9. Continuation, Conversion, and the Independence of Children

When a new application is filed as a continuation or continuation-in-part of an earlier one, the child is a fully independent `Application` row that names its parent through `parent_application_id` and declares the relationship kind through `continuation_type` (either `CONTINUATION` or `CIP`). Both `parent_application_id` and `continuation_type` are immutable after creation. A conversion of a provisional, by contrast, is a distinct relationship: the new utility row also names the provisional via `parent_application_id`, but `continuation_type` is left null because conversion is not a continuation.

Because children are independent rows, a downstream cascade on the parent — for example, the parent being marked `ABANDONED` for a missed office-action deadline — does not propagate to a continuation child in a non-terminal state. A continuation can outlive its parent. The only relationship the parent imposes on the child is the priority-date inheritance rule covered in §3.

### 2.10. Time-Driven Cascades and the Deadline Sweeper

Three workflows in this system are completed by the passage of time rather than by an applicant action: an office action whose maximum response window has elapsed abandons its parent application; a provisional past its twelfth month expires unless converted; and an issued utility whose maintenance window grace deadline has passed expires. These cascades do not fire on every read — they fire when the deadline sweeper runs. Calling the admin-only sweep capability synchronously evaluates all three populations against the current logical clock and applies the cascades atomically per affected application: the triggering office actions on an abandoned application all flip to `EXPIRED` and `Application.status` flips to `ABANDONED`; a lapsed maintenance fee flips to `LAPSED` and the parent `Application.status` flips from `ISSUED` to `EXPIRED`. Every cascaded row's `version` bumps by 1, and the sweep response surfaces five counters — applications abandoned, applications expired, provisionals expired, maintenance fees lapsed, and office actions expired — describing only that single sweep's effects.

## 3. Business Logic & Workflows

### 3.1. Applicant Onboarding and the Micro-Entity Income Test

Before any application can be filed, the calling principal must exist as an `Applicant` row. Creating an applicant requires the applicant's `legal_name` (a string of 2 to 200 characters) and, optionally, their declared `entity_size` (defaulting to `LARGE` when omitted, otherwise one of `SMALL` or `MICRO`). When the declared size is `MICRO`, the applicant must additionally supply `micro_qualifying_year` (the calendar year used to evaluate the income test, an integer between 2000 and 2100 inclusive) and `gross_income_prior_year_cents` (the applicant's prior calendar-year gross income in U.S. dollar cents, a non-negative integer). The `prior_applications_filed` field — the count of prior non-provisional applications on which the applicant or any of their inventors has been named — is required of every applicant, defaults to 0 when omitted, and must be non-negative.

A micro-entity applicant is accepted only when the micro-entity eligibility predicate holds at applicant-creation time: `gross_income_prior_year_cents` must be present, must not exceed `MICRO_INCOME_CEILING_CENTS` of 24,600,000 cents (the illustrative $246,000 ceiling), `prior_applications_filed` must not exceed `MICRO_PRIOR_APPS_CEILING` of 4, and `micro_qualifying_year` must be present. If any of those four conditions fails, the create is rejected with `ERR_MICRO_INELIGIBLE`. The same predicate is re-evaluated whenever a `MICRO` applicant later attempts to file an application or post a fee payment — the goal is that a `MICRO` discount can never be applied by an applicant who no longer qualifies. Applicants whose declared size is `LARGE` or `SMALL` skip the eligibility predicate entirely; their `micro_qualifying_year` and `gross_income_prior_year_cents` fields are not required and are ignored if supplied.

### 3.2. Filing an Application

An applicant files a patent application by submitting their `applicant_id`, the `application_type` (one of `UTILITY`, `DESIGN`, `PROVISIONAL`, or `PCT_NATIONAL`, immutable after creation), the invention's `title` (3 to 500 characters), and the two claim counts: `claim_count` (the total number of claims, an integer in the range 1 to 500 inclusive) and `independent_claim_count` (the number of independent claims, an integer at least 1 and not exceeding `claim_count`). A violation of either claim-count rule rejects the request with `ERR_CLAIM_COUNTS_INVALID`.

A continuation or continuation-in-part is filed by including `parent_application_id` (the id of an existing application) and `continuation_type` (either `CONTINUATION` or `CIP`). The pair must be coherent: when `parent_application_id` is null, `continuation_type` must also be null, and when `parent_application_id` is set, `continuation_type` must be set to `CONTINUATION` or `CIP`; any other combination is rejected with `ERR_CONTINUATION_TYPE_MISMATCH`. The referenced parent must not be in a terminal lifecycle state — that is, not in `ABANDONED`, `EXPIRED`, or `CONVERTED` — because dead applications can no longer spawn continuations; a parent in `ISSUED` is permitted, since continuations off issued patents are a legitimate prosecution strategy. A parent in any other excluded terminal state rejects the create with `ERR_CONTINUATION_PARENT_TERMINAL`.

Upon successful creation, the application is stamped with `filing_date` equal to the server's current UTC instant (which also equals `created_at`, but the two are surfaced separately because business deadlines key off `filing_date` and not `created_at`), the lifecycle `status` is set to `FILED`, the `total_fees_paid_cents` accumulator is initialized to 0, and `priority_date` is computed. For a primary filing (no parent), the priority date is the new application's own `filing_date`. For a `CONTINUATION`, the priority date is inherited from the parent's `filing_date` — preserving the earlier priority for prior-art purposes and (for a utility) anchoring the future term-expiration calculation 20 years from that earlier date. For a `CIP`, the priority date is the new application's own `filing_date`, because a continuation-in-part introduces new matter that must be treated as filed today; this is the deliberate difference between the two continuation kinds, and the same parent-and-dates input yields two different `priority_date` values depending on which kind was chosen. `issued_patent_number`, `issue_date`, and `term_expiration_date` are null at filing and stay null until issuance makes them computable.

### 3.3. Paying the Filing and Excess-Claim Fees

A freshly-filed application sits in `FILED` until its filing fee is posted; an examiner is not permitted to docket it until that happens. Posting a filing fee is done by submitting a fee payment that names the `application_id`, sets `payment_category` to `FILING`, and submits an `amount_cents` exactly equal to the server-computed expected filing fee for the application's type and the applicant's entity size. The base filing fee in cents depends on the application type: 32,000 cents for `UTILITY`, 22,000 cents for `DESIGN`, 30,000 cents for `PROVISIONAL`, and 32,000 cents for `PCT_NATIONAL`. That base is multiplied by the entity multiplier — 1.00, 0.50, or 0.20 for `LARGE`, `SMALL`, and `MICRO` respectively — and the product is rounded to the nearest cent using round-half-up to yield the expected payment. A submitted amount that is greater or less than this expected value is rejected with `ERR_FEE_AMOUNT_MISMATCH`.

A second category, `EXCESS_CLAIMS`, covers the per-claim surcharge that applies whenever an application files more than 20 total claims or more than 3 independent claims. The expected excess fee is computed as follows: count the excess total claims as `claim_count` minus 20 (or zero, whichever is greater), count the excess independent claims as `independent_claim_count` minus 3 (or zero, whichever is greater), multiply the excess-total count by `EXCESS_CLAIM_BASE_CENTS` of 10,000 cents per claim, multiply the excess-independent count by `EXCESS_INDEP_BASE_CENTS` of 48,000 cents per claim, apply the entity-size multiplier to each of those two products individually, add the two scaled products together, and finally round the sum to the nearest cent using round-half-up. The order of operations is fixed: each term is scaled before the sum, and the sum is rounded exactly once after addition. The fee category for this payment is `EXCESS_CLAIMS`, the `amount_cents` must match the server's expected value exactly, and `maintenance_fee_id` is left null. A fee payment whose category is not one of the maintenance categories must also leave `maintenance_fee_id` null; a maintenance payment must populate it, and any other combination is malformed.

On every successful fee payment, a new `FeePayment` row is created with `payment_status` set to `POSTED`, the payment is appended to the application's ledger, and `Application.total_fees_paid_cents` is recomputed as the sum of `amount_cents` across all `POSTED` payments for that application; `Application.version` bumps and `updated_at` is refreshed.

### 3.4. Docketing and the Examiner Cycle

Once an application's accumulated `total_fees_paid_cents` is at least the expected filing fee for its type-and-size, an examiner can docket it, transitioning the application from `FILED` to `AWAITING_EXAMINATION`. Docketing is permitted only for applications whose type is in `UTILITY`, `DESIGN`, or `PCT_NATIONAL`; a `PROVISIONAL` never enters examination — it can only be converted or allowed to expire. The transition is the simple state advance: `Application.status` is set to `AWAITING_EXAMINATION` and `Application.version` bumps.

From `AWAITING_EXAMINATION`, the examiner may issue an office action by creating an `OfficeAction` that references the target `application_id` and declares its `action_type` (one of `NON_FINAL`, `FINAL`, or `NOTICE_OF_ALLOWANCE`, immutable after creation). On creation, the `issue_date` is stamped to the server's current UTC instant, two deadlines are computed — `shortened_due_date` as the issue date plus 3 months and `maximum_due_date` as the issue date plus 6 months — and the office action lands in `OUTSTANDING`. The parent application moves: from `AWAITING_EXAMINATION` to `OFFICE_ACTION_OUTSTANDING` for `NON_FINAL` or `FINAL` actions, or directly to `ALLOWED` for a `NOTICE_OF_ALLOWANCE` (the alternate happy path where the examiner allows without ever rejecting). The application's version bumps on either branch.

At most one office action with `status` of `OUTSTANDING` may exist per application at any time. An attempt to create a second non-allowance office action while another is already `OUTSTANDING` is rejected with `ERR_OFFICE_ACTION_ALREADY_OUTSTANDING`; the only office action that may be issued while another is `OUTSTANDING` is one whose action type is `NOTICE_OF_ALLOWANCE`, because the notice withdraws all other outstanding actions as a side effect.

### 3.5. Responding to an Office Action

When the office action is in `OUTSTANDING` and is not a `NOTICE_OF_ALLOWANCE` (notices are responded to via the issue-fee payment, not via an office-action response), the applicant files a response by submitting `office_action_id`, `extension_months_requested`, and `claim_amendment_count`. The `claim_amendment_count` field — the total number of claims after amendment, also bounded by the [1, 500] range and the independent-claim subset rule — substitutes for `claim_count` in the same range-validation check that filing uses, and a violation is reported as `ERR_CLAIM_COUNTS_INVALID`. The applicant's original `Application.claim_count` is not mutated by an office-action response; the amended count is local to the response row. The `extension_months_requested` parameter must be an integer in the set {0, 1, 2, 3}; anything outside that set is rejected with `ERR_EXTENSION_MONTHS_INVALID` before any extension fee is computed.

The deadline for a timely response is the office action's `shortened_due_date` plus the requested extension in whole months, with the absolute statutory ceiling of `maximum_due_date` (six months after issue) never exceeded. Specifically, the response is timely only when the server's current UTC instant — recorded into the response as `response_filed_at` — is on or before the office action's `shortened_due_date` advanced by `extension_months_requested` months, AND that advanced datetime is itself on or before the office action's `maximum_due_date`. A response that satisfies both conditions is recorded with `response_status` of `ACCEPTED`; the only other possible response status is `REJECTED_LATE`, which corresponds to a response that violates either condition.

When extensions are purchased, the response must be filed in the same transaction as a fee payment whose `payment_category` is `EXTENSION` and whose `amount_cents` equals the expected extension fee for the requested months and the applicant's entity size. When no extension is requested (`extension_months_requested` equals 0), the expected extension fee is 0, and no separate extension payment is required. Otherwise, the expected base in cents is read from a small table indexed by month count — 22,000 cents for a 1-month extension, 64,000 cents cumulative for a 2-month extension, and 148,000 cents cumulative for a 3-month extension — multiplied by the same entity-size multiplier, and rounded to the nearest cent with round-half-up. The result is recorded on the response as `extension_fee_cents`. A standalone fee payment posted via `POST /fee-payments` with `payment_category` set to `EXTENSION` computes its server-expected `amount_cents` by referencing the most recently created `OfficeActionResponse` (ordered by `created_at`) whose parent office action belongs to the named `application_id`, using that response's `extension_months_requested`; if no such response exists on the application at the moment the payment is evaluated, the payment is rejected with `ERR_FEE_AMOUNT_MISMATCH`. The ordering implication is that the office-action response row must already exist before a standalone EXTENSION fee payment can be posted against the same application.

A timely response transitions the parent office action from `OUTSTANDING` to `RESPONDED` (bumping `OfficeAction.version`) and the parent application from `OFFICE_ACTION_OUTSTANDING` to `RESPONSE_FILED` (bumping `Application.version`). The applicant has now returned the prosecution baton to the examiner.

### 3.6. The Cycle Continues — Successive Office Actions, Allowance, or Abandonment

From `RESPONSE_FILED`, the examiner may issue another office action. The same creation endpoint is reused, the same action-type rules apply, and a new `OfficeAction` lands in `OUTSTANDING` while the application cycles back to `OFFICE_ACTION_OUTSTANDING`. This cycle — examiner action, applicant response, repeat — can continue across an arbitrary number of iterations until the examiner issues a `NOTICE_OF_ALLOWANCE` or the application is abandoned.

A notice of allowance issued while the application is in `OFFICE_ACTION_OUTSTANDING` advances the application to `ALLOWED` and additionally sets every other `OUTSTANDING` office action on the same application to `WITHDRAWN` as a side effect, bumping the version of each office action that was withdrawn (excluding the notice itself, which remains the active allowance). The application's version also bumps. A notice of allowance issued directly from `AWAITING_EXAMINATION` simply advances the application to `ALLOWED` without any withdrawals, since by definition no prior outstanding office action exists.

Abandonment happens when the deadline sweeper observes that an `OUTSTANDING` office action's `maximum_due_date` has passed without an `ACCEPTED` response. When the sweep runs and finds at least one such office action attached to an application still in `OFFICE_ACTION_OUTSTANDING`, the cascade fires: every `OUTSTANDING` office action on that application flips to `EXPIRED` (each bumping its own version), and the application's status flips to `ABANDONED` with a version bump. Any continuation children of the abandoned application that are themselves in a non-terminal lifecycle are unaffected — they continue independently.

### 3.7. Paying the Issue Fee and Issuance

An applicant whose application has reached `ALLOWED` pays the issue fee to transition it to `ISSUED`. The pay-issue-fee request takes two body fields: `amount_cents` and `expected_application_version`. The expected issue fee in cents is derived from the application type — 120,000 cents for `UTILITY`, 74,000 cents for `DESIGN`, and 120,000 cents for `PCT_NATIONAL` (a `PROVISIONAL` cannot reach `ALLOWED` and so has no issue-fee schedule) — multiplied by the entity multiplier and rounded to the nearest cent with round-half-up. The submitted `amount_cents` must equal that expected value exactly. The `expected_application_version` must equal the application's current `version`; otherwise the operation is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated.

When the request succeeds, a `FeePayment` is appended to the ledger with `payment_category` set to `ISSUE` and `payment_status` set to `POSTED`; the application advances from `ALLOWED` to `ISSUED`; `issued_patent_number` is minted as a server-generated string of the form `US{seq}` where `seq` is a monotonically increasing sequence; `issue_date` is stamped to the server's current UTC instant; and `term_expiration_date` is computed by application type. For a `UTILITY` or `PCT_NATIONAL` application, the term expires 20 years after `priority_date`; for a `DESIGN`, the term expires 15 years after `issue_date`; for a `PROVISIONAL` the term expiration is defined as 12 months after `filing_date` and is used to drive the auto-expiry sweep rather than any issuance. Finally, `Application.total_fees_paid_cents` is recomputed to include the new payment, and `Application.version` bumps.

For a `UTILITY` patent only, issuance generates three `MaintenanceFee` rows in `PENDING`, one per maintenance window. Each row carries its `window_number` (1, 2, or 3), its window dates computed from `issue_date` (window 1 opens at issue plus 3.5 years and is due at issue plus 4 years, window 2 opens at issue plus 7.5 years and is due at issue plus 8 years, window 3 opens at issue plus 11.5 years and is due at issue plus 12 years), and `window_grace_date` equal to the window's `window_due_date` plus 6 months. Each row's `base_fee_cents` is computed at the moment of issuance: the base in cents is 200,000 for window 1, 376,000 for window 2, and 772,000 for window 3; that base is multiplied by the entity multiplier at issuance time and rounded with round-half-up. `paid_at` is null until the row transitions to `PAID`.

### 3.8. Maintenance Fees Across the Decade

A maintenance fee is paid by posting a fee payment that names the `application_id`, sets `payment_category` to one of `MAINTENANCE_W1`, `MAINTENANCE_W2`, or `MAINTENANCE_W3` (matching the window being paid), names the target `maintenance_fee_id`, and supplies `amount_cents` exactly equal to the expected payment for that window at the current logical clock. The expected payment is the row's recorded `base_fee_cents` plus, when applicable, a late surcharge: if the server's `current_utc` is on or before `window_due_date`, no surcharge applies and the expected payment is simply the base; if `current_utc` is strictly after `window_due_date` but on or before `window_grace_date`, a surcharge applies, computed by multiplying `LATE_SURCHARGE_BASE_CENTS` of 16,000 cents by the entity multiplier and rounding the result to the nearest cent with round-half-up, then added to the base. The two rounds happen independently — the base is rounded once at issuance, the surcharge is rounded once at payment time, and the two integer cents are summed.

Maintenance payments must satisfy four windows of constraint. First, the parent application must still be in `ISSUED` — a payment against a row whose parent has already been expired is rejected as an invalid state. Second, the `current_utc` must lie within `[window_open_date, window_grace_date]`; a payment before the window opens or after the grace cutoff is rejected with `ERR_MAINTENANCE_WINDOW_CLOSED`. Third, the `amount_cents` must exactly match the expected (base, or base plus surcharge) per the rules above; a mismatch is rejected with `ERR_FEE_AMOUNT_MISMATCH`. Fourth, the windows must be paid in order: a payment for window N is permitted only when every earlier window on the same application is already `PAID`; an attempt to pay window 2 while window 1 is still `PENDING`, or window 3 while window 1 or 2 is still `PENDING`, is rejected with `ERR_MAINTENANCE_OUT_OF_ORDER`.

A successful maintenance payment transitions the named `MaintenanceFee` from `PENDING` to `PAID` — that is, the row's `fee_status` field flips from `PENDING` to `PAID` — stamps `paid_at` to the server's current UTC instant, bumps `MaintenanceFee.version`, appends the `FeePayment` (whose `payment_status` is `POSTED`), and recomputes `Application.total_fees_paid_cents`, also bumping `Application.version`.

When a maintenance window's `window_grace_date` passes with the row still in `PENDING`, the deadline sweeper flips the triggering `MaintenanceFee.fee_status` to `LAPSED` (bumping its version), and cascades the parent application from `ISSUED` to `EXPIRED` (bumping its version). The patent has expired for failure to maintain.

### 3.9. Provisionals and Their Twelve-Month Window

A `PROVISIONAL` application is a one-year placeholder for priority. It is not eligible for docketing, never enters examination, and has only two possible end states: it can be converted into a utility, or it auto-expires. Conversion is the conversion endpoint addressed at the provisional, taking `title`, `claim_count`, `independent_claim_count`, and `expected_application_version` in the body. Three preconditions guard the conversion: the source application's `application_type` must be `PROVISIONAL`, its `status` must be `FILED`, and the server's `current_utc` must be on or before the source application's `filing_date` plus 12 months. A late conversion attempt — `current_utc` strictly after that 12-month anchor — is rejected with `ERR_PROVISIONAL_CONVERSION_LATE`. A second conversion attempt against a provisional whose status is already `CONVERTED` is rejected with `ERR_PROVISIONAL_ALREADY_CONVERTED`, because conversion is single-shot. And, as in §3.7, an `expected_application_version` mismatch is rejected with `ERR_STALE_VERSION`.

A successful conversion creates a fresh `Application` with `application_type` set to `UTILITY`, `parent_application_id` pointing at the source provisional, and `continuation_type` left null (conversion is a distinct relationship from continuation, even though both record the source application as parent). The new utility's `priority_date` inherits the source provisional's `filing_date`. The source application is itself transitioned from `FILED` to `CONVERTED` — a terminal state — and `Application.version` bumps. If conversion never happens, the source provisional auto-expires when the sweeper observes that its `filing_date` plus 12 months has elapsed; the sweep flips its `status` from `FILED` to `EXPIRED` and bumps its version. Both `CONVERTED` and `EXPIRED` are terminal for a provisional.

### 3.10. PCT National Phase Entry

A `PCT_NATIONAL` application records its entry into the U.S. national phase by creating a `PCTPhaseEntry` that names the target `application_id` and the original `pct_international_filing_date` (the international filing date, which must be strictly earlier than the moment the entry is recorded). The server computes `national_phase_due_date` as the international filing date plus 30 months. A national phase entry created on or before that due date is accepted with `phase_status` set to `ENTERED`; an entry whose `created_at` is strictly after the due date is rejected with `ERR_PCT_NATIONAL_PHASE_LATE`. At most one `PCTPhaseEntry` may exist per application: a second entry against the same application is rejected with `ERR_PCT_PHASE_ENTRY_DUPLICATE`.

### 3.11. The Test Clock and the Sweeper

Because the deadlines that drive abandonment, provisional expiry, and patent expiry would otherwise require waiting weeks or years to exercise, an admin-only test-driving capability lets the administrator pin the server's logical clock to a supplied `to_iso8601` instant. Every deadline comparison in the system subsequently reads from this clock, so a test can advance the clock past a maximum response window, past a provisional's twelfth month, or past a maintenance grace date, and then call the admin-only sweep capability. The sweep runs the same three populations the system would run on its own: outstanding office actions whose `maximum_due_date` has elapsed cascade their parent applications to `ABANDONED`; provisionals in `FILED` past their twelve-month window flip to `EXPIRED`; maintenance fees still `PENDING` past their `window_grace_date` flip to `LAPSED` and cascade their parent applications from `ISSUED` to `EXPIRED`. The sweep response surfaces five integer counters — `applications_abandoned`, `applications_expired`, `provisionals_expired`, `maintenance_fees_lapsed`, and `office_actions_expired` — each counting only the rows that this particular sweep call mutated.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the newly created resource in `data`. Endpoints that modify an existing resource (state transitions, payments crediting an existing application) and endpoints that read return HTTP 200 with the affected or requested resource in `data`. The two test-driving endpoints under `/_<name>` likewise return HTTP 200.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/applicants` | Create an applicant; validates micro-entity eligibility. | `Applicant`, `USPTOAdmin` |
| GET | `/applicants/{id}` | Read a single applicant. | `Applicant`, `USPTOAdmin`, `USPTOExaminer` |
| GET | `/applicants` | List applicants, paginated. | `Applicant`, `USPTOAdmin`, `USPTOExaminer` |
| POST | `/applications` | File a new patent application; sets filing date, status, and priority date. | `Applicant` |
| GET | `/applications/{id}` | Read a single application. | `Applicant`, `USPTOAdmin`, `USPTOExaminer` |
| GET | `/applications` | List applications; filterable by `applicant_id` and `parent_application_id`. | `Applicant`, `USPTOAdmin`, `USPTOExaminer` |
| POST | `/applications/{id}/docket` | Examiner dockets a filed application for examination. | `USPTOExaminer` |
| POST | `/applications/{id}/pay-issue-fee` | Pay the issue fee; transitions ALLOWED to ISSUED. OCC-guarded. | `Applicant` |
| POST | `/applications/{id}/convert-provisional-to-utility` | Convert a PROVISIONAL into a child UTILITY within 12 months. OCC-guarded. | `Applicant` |
| POST | `/office-actions` | Examiner issues an office action or notice of allowance. | `USPTOExaminer` |
| GET | `/office-actions/{id}` | Read a single office action. | `Applicant`, `USPTOAdmin`, `USPTOExaminer` |
| GET | `/office-actions` | List office actions; filterable by `application_id`. | `Applicant`, `USPTOAdmin`, `USPTOExaminer` |
| POST | `/office-action-responses` | Applicant files an office-action response, optionally with extension months. | `Applicant` |
| GET | `/office-action-responses/{id}` | Read a single office-action response. | `Applicant`, `USPTOAdmin`, `USPTOExaminer` |
| GET | `/office-action-responses` | List office-action responses; filterable by `office_action_id`. | `Applicant`, `USPTOAdmin`, `USPTOExaminer` |
| GET | `/maintenance-fees/{id}` | Read a single maintenance fee. | `Applicant`, `USPTOAdmin` |
| GET | `/maintenance-fees` | List maintenance fees; filterable by `application_id`. | `Applicant`, `USPTOAdmin` |
| POST | `/fee-payments` | Post a fee payment for filing, excess claims, extension, issue, or maintenance. | `Applicant` |
| GET | `/fee-payments/{id}` | Read a single fee payment. | `Applicant`, `USPTOAdmin` |
| GET | `/fee-payments` | List fee payments; filterable by `application_id` and `maintenance_fee_id`. | `Applicant`, `USPTOAdmin` |
| POST | `/pct-phase-entries` | Record national phase entry for a PCT application within 30 months. | `Applicant` |
| GET | `/pct-phase-entries/{id}` | Read a single PCT phase entry. | `Applicant`, `USPTOAdmin` |
| GET | `/pct-phase-entries` | List PCT phase entries; filterable by `application_id`. | `Applicant`, `USPTOAdmin` |
| POST | `/_clock/set_current_utc` | Test-driving: pin the server's current UTC clock to a supplied instant. | `USPTOAdmin` |
| POST | `/_jobs/sweep-deadlines` | Test-driving: run the deadline sweeper synchronously and return per-cascade counters. | `USPTOAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TERMINAL_STATE` | 409 |
| `ERR_CONTINUATION_TYPE_MISMATCH` | 422 |
| `ERR_CONTINUATION_PARENT_TERMINAL` | 409 |
| `ERR_MICRO_INELIGIBLE` | 422 |
| `ERR_PCT_NATIONAL_PHASE_LATE` | 422 |
| `ERR_PROVISIONAL_CONVERSION_LATE` | 422 |
| `ERR_PROVISIONAL_ALREADY_CONVERTED` | 409 |
| `ERR_MAINTENANCE_WINDOW_CLOSED` | 409 |
| `ERR_FEE_AMOUNT_MISMATCH` | 422 |
| `ERR_CLAIM_COUNTS_INVALID` | 422 |
| `ERR_MAINTENANCE_OUT_OF_ORDER` | 409 |
| `ERR_EXTENSION_MONTHS_INVALID` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_OFFICE_ACTION_ALREADY_OUTSTANDING` | 409 |
| `ERR_PCT_PHASE_ENTRY_DUPLICATE` | 409 |
