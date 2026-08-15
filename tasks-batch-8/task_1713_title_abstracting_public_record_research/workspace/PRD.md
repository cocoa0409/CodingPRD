# Title Abstracting API — Product Requirements Document

## 1. Introduction

Title abstracting is a deadline-driven, liability-bearing craft: a client (typically lender or buyer counsel) commissions a search of the public record, an abstracter walks the grantor/grantee indexes and the lien, judgment, and tax rolls across a defined search period, an examiner reviews the work product, and the firm delivers an abstract report whose conclusions it must stand behind. Every step leaves an audit trail, every county copy fee passes through to the client, and every missed deadline has a negotiated consequence.

This document specifies the Title Abstracting & Public Record Research API, which governs that engagement end to end. The platform tracks an order from intake through chain-of-title and lien search, legal-description verification against survey, report drafting and examiner review, curative work, county record retrieval with pass-through fee handling, and final delivery under a turnaround SLA with explicit liability limits. Four cooperating roles — the ordering `Client`, the field `Abstracter`, the reviewing `Examiner`, and the `OperationsManager` who dispatches work, runs intake quality control, administers county fees, and delivers the finished product — interact through a single REST interface mounted under `/api`.

Two design commitments shape everything that follows. First, the search and the money are both auditable: scope windows, chain-of-title linkage, curative severity, segregation of duties on waivers, and a per-order fee ledger are enforced by the system rather than by convention. Second, time in this system is logical, not wall-clock: a test-driving clock governs receipt, due dates, delivery, overdue evaluation, and late-credit computation, so that SLA behavior is deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint — or whose `X-User-ID` fails an attribute-ownership rule — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles, spelled as follows: `Client`, `Abstracter`, `Examiner`, and `OperationsManager`. All four carry an **opaque** identity: `X-User-ID` is an operator identifier not tied to any persisted entity. The server records these identifiers on resources where a workflow books them — for example, `abstracter_ref` on a `SearchAssignment`, `reviewer_examiner_ref` on an `AbstractReport`, or `raised_by_examiner_ref` on a `CurativeRequirement` — and it compares those recorded attributes against `X-User-ID` for ownership checks, but it never resolves `X-User-ID` against any entity's `id`. The ownership rules that bind header to data are three: a `Client` may place an order only when the request's `client_ref` equals `X-User-ID`, and may later read or cancel only orders whose `client_ref` matches; an `Abstracter` may submit, resume, verify, flag, or void work only on assignments whose `abstracter_ref` matches; and an `Examiner` may approve or require revision only on a report whose `reviewer_examiner_ref` matches, and may never waive a requirement they themselves raised.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — `AbstractOrder`, `SearchAssignment`, `RecordDocument`, `LegalDescriptionCheck`, `AbstractReport`, `CurativeRequirement`, and `CountyRetrieval` — carries a standard system-managed property set. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded at creation. `updated_at` follows the same format and refreshes on every mutation. `version` is an integer starting at its initial value on creation and incrementing by one on every mutation of that resource, including mutations driven by system cascades. All seven resources in this domain carry the full set; none omits `updated_at` or `version`.

### 2.5. The Logical Clock and Turnaround SLA

The system measures time against a logical clock, never the wall clock. At server startup, before any administrative adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`. An admin-only, test-driving capability — available to the `OperationsManager` — advances the logical clock to a supplied `to_iso8601` instant; setting the clock re-evaluates the overdue flag on every order that has not yet reached a terminal state. The logical clock stamps `received_at` when an order is placed, stamps `delivered_at` when it is delivered, decides whether an order reads as overdue at read time, and anchors the late-credit computation at delivery. All timestamp comparisons in this domain are made to the second.

Each order commits to a turnaround tier through its `sla_tier`, one of `STANDARD` or `RUSH`. The due instant `due_at` is derived at creation as `received_at` plus seventy-two hours for a `STANDARD` order, or plus twenty-four hours for a `RUSH` order. An order reads as overdue — its computed `is_overdue` flag is true — precisely when the logical clock has advanced past `due_at` while the order's `status` is neither `DELIVERED` nor `CANCELLED`; once the order reaches either terminal state the flag is false regardless of the clock.

### 2.6. Monetary Precision and the Fee Ledger

All money in this domain is integer cents. Every fee, premium, credit, and cap is stored and returned as a whole number of cents; wherever a multiplication yields a fractional cent, the result is rounded half up to the nearest whole cent. Two computations share this rule: the rush premium (twenty-five percent of its base, rounded half up) and the late credit (ten percent of the final fee, rounded half up). The per-document county charge of 2500 cents and the per-page charge of 125 cents are exact whole-cent quantities and need no rounding.

Every order carries a running actual fee, `accrued_fees_cents`, which behaves as a ledger: it is initialized at creation, recomputed in full each time a county fee is posted or reversed, and recomputed again when a posted fee is reversed as part of a cancellation. Posting a fee and later reversing it is a compensating pair — after the pair, `accrued_fees_cents` returns to exactly the value it held before the post. One rounding order is pinned and non-negotiable: the rush premium is computed exactly once, on the whole subtotal formed by the base fee plus the full sum of contributing retrieval fees. Computing the premium per retrieval line and summing is a forbidden variant, because per-line rounding drifts the total — three per-page lines of 375 cents each yield a premium of 10281 cents when computed once on the subtotal of 41125, but 10282 cents when rounded line by line.

### 2.7. Engagement Liability Limits

The firm's exposure on each engagement is capped, and the cap is recomputed whenever the fee basis moves: at order creation, at every recomputation of `accrued_fees_cents`, on any scope amendment that changes the `liability_tier`, and at delivery. The fee basis is `final_fee_cents` once delivery has set it, and `accrued_fees_cents` before that. The cap `liability_cap_cents` is the lesser of two quantities: the tier multiplier applied to the fee basis — three times the basis for the `STANDARD` liability tier, five times for `EXTENDED` — or an absolute ceiling of 200000 cents. An order's `liability_tier` of `STANDARD` or `EXTENDED` therefore directly scales the firm's maximum exposure, bounded above by the absolute ceiling.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both guard on the parent order's `version`. Amending an order's engagement scope requires the request to carry `expected_abstract_order_version`, a non-optional field holding the order `version` the client last observed. Opening the abstract report for an order likewise requires `expected_abstract_order_version`. In both cases, if the order's current `version` on the server has advanced past the supplied value — because another writer patched the scope, a cascade bumped the version, or any other mutation intervened — the request is rejected with `ERR_STALE_VERSION` (HTTP 412); the client must re-read the order and retry against the version it actually observes. No other endpoint accepts a version field: every other write proceeds without an OCC check, because the remaining state machines serialize their own preconditions.

### 2.9. Hierarchical Consistency and Cascading Finalization

The order is the root of every aggregate in this domain, and its state propagates downward without requiring a client request on each child. When an order is cancelled, every assignment still in `IN_PROGRESS`, `SUBMITTED`, or `RETURNED_FOR_CORRECTION` moves to `CANCELLED`; any report in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `REVISION_REQUIRED` moves to `CANCELLED`; and every county retrieval with a posted-but-not-invoiced fee moves from `FEE_POSTED` to `FEE_REVERSED`, with the order's running fee recomputed afterward. Delivery cascades in the opposite direction of finalization: delivering the order moves its `APPROVED` report to `DELIVERED`, which in turn moves every retrieval still in `FEE_POSTED` to `INVOICED`, which in turn triggers the final fee, late-credit, billed-fee, and liability-cap recomputation on the order. Each such cascade that mutates the order increments the order's `version` by one and refreshes `updated_at`.

A complementary guard runs upward: once an order reaches `DELIVERED` or `CANCELLED`, any attempt to mutate a child — a document, curative requirement, retrieval, legal description check, report, or assignment — is refused with `ERR_ORDER_TERMINAL`. Within the retrieval lifecycle, fiscal audit errors take precedence even over that terminal guard: a fee already invoiced always surfaces its invoicing error rather than the terminal-order error, so the books can never be silently touched.

### 2.10. Nested Resource Retrieval and Validation Ordering

Requests that reference resources through path or body identifiers are validated in a strict, left-to-right sequence. The parent order is resolved first — a reference to a nonexistent order yields `ERR_ORDER_NOT_FOUND` before any child identifier is examined — and only then the assignment, document, check, report, curative requirement, or retrieval named by the request, each surfacing its own not-found error (`ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CURATIVE_NOT_FOUND`, `ERR_RETRIEVAL_NOT_FOUND`). A `prior_document_id` supplied in a body that names no existing document likewise surfaces `ERR_DOCUMENT_NOT_FOUND`.

Validation as a whole is priority-ordered, and the ordering is observable. Authentication (401) is evaluated first, then role and ownership authorization (403), then input well-formedness (400), then existence (404), then the fiscal lifecycle guards on fee posting and reversal, then the terminal-order guard, then generic state-transition legality (409), and only then the domain business rules — waiver safety, temporal windows, overlap and buffer conflicts, uniqueness, OCC staleness — each at its declared position. When several rules could reject the same request, the one earliest in this order is the error the client receives; for example, an attempt to post a fee against a retrieval that is already `INVOICED` on an already-delivered order surfaces `ERR_ALREADY_INVOICED`, never `ERR_ORDER_TERMINAL`.

## 3. Business Logic & Workflows

### 3.1. Placing an Order: Intake, Scope, and the Provisional Quote

An engagement begins when a `Client` places an order. The intake payload names the opaque client identifier `client_ref` — which must equal the caller's `X-User-ID`, or the placement is refused with `ERR_FORBIDDEN` — together with the subject property's `property_address`, the `county` of record, a `state_code` of exactly two uppercase letters A through Z, the legal description of record as `legal_description_text`, the search depth `search_period_years` as an integer from 1 to 60 inclusive, and the `effective_date` in ISO `YYYY-MM-DD` form marking the end of the search window. Two engagement tiers may optionally be supplied: `sla_tier` (`STANDARD` or `RUSH`, defaulting to `STANDARD`) and `liability_tier` (`STANDARD` or `EXTENDED`, defaulting to `STANDARD`). A request missing a required field, presenting an enum outside its declared values, or violating a range — a `search_period_years` of 0 or 61, a `state_code` in lowercase — is rejected with `ERR_VALIDATION` (HTTP 400).

Creation stamps `received_at` from the logical clock and leaves the order in `RECEIVED` status. Two read-only fields derive immediately. The scope window opens at `scope_start_date`, computed as `effective_date` minus `search_period_years` calendar years, keeping the same month and day — a thirty-year search effective 2026-03-15 opens on 1996-03-15. The turnaround commitment `due_at` derives per §2.5.

Creation also produces the provisional quote. The provisional fee `provisional_fee_cents` is the sum of a 40000-cent base fee and an estimated retrieval allowance — eight projected county documents at 2500 cents each, i.e. 20000 cents — plus, when the tier is `RUSH`, a premium of twenty-five percent of that subtotal rounded half up; for a `STANDARD` order the premium is zero and the quote is exactly 60000 cents. The running ledger `accrued_fees_cents` initializes differently: it contains the base fee plus, for `RUSH` only, twenty-five percent of the base fee alone rounded half up — the estimated allowance is a projection for quoting, not yet a charge, and it is discarded entirely at finalization, which uses only actually posted, non-reversed retrieval fees. The liability cap `liability_cap_cents` initializes per §2.7 with the just-initialized `accrued_fees_cents` as its fee basis. The order's `final_fee_cents`, `delivered_at`, and `billed_fee_cents` are all null until delivery, `late_credit_cents` starts at 0, `open_curative_count` starts at 0, and the `legal_hold` flag starts false.

### 3.2. Amending the Engagement While the Books Are Open

While an order remains in `RECEIVED` or `SEARCH_IN_PROGRESS`, an `OperationsManager` may amend its engagement scope. The amendable fields are `search_period_years`, `effective_date`, `sla_tier`, `liability_tier`, and `legal_description_text`; the request must also carry `expected_abstract_order_version` per §2.8, and a stale version is refused with `ERR_STALE_VERSION` (HTTP 412). Once the order has advanced beyond `SEARCH_IN_PROGRESS` the scope is locked, and any such amendment is rejected with `ERR_SCOPE_LOCKED` (HTTP 409).

A successful amendment increments the order's `version` by one and re-derives everything the changed terms touch. A change to `search_period_years` or `effective_date` recomputes `scope_start_date` and re-derives the `in_scope` flag of every non-`VOID` recorded document on the order; a change to `sla_tier` recomputes `due_at` and the premium portion of both the provisional quote and the running fee; a change to `liability_tier` recomputes the liability cap. Amendments are audited on the order itself — `updated_at` refreshes with each accepted patch.

### 3.3. Dispatching Search Work: Assignments and Work Windows

An `OperationsManager` dispatches public-record work by creating a search assignment naming the `order_id` it serves, the `abstracter_ref` of the abstracter who will work it, a `search_type` of either `CHAIN_OF_TITLE` or `LIEN_JUDGMENT_TAX`, and a committed work window from `window_start` to `window_end`. The window is a half-open interval: it must be strictly ordered, so a `window_end` that is not later than `window_start` is rejected with `ERR_WINDOW_INVALID` (HTTP 422). An abstracter's committed windows may not collide: the new window must not intersect any non-`CANCELLED` assignment window of the same `abstracter_ref`, under half-open semantics two windows that merely touch — one ending exactly where the other begins — are permitted, and any true intersection is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409).

The first assignment created for an order moves that order from `RECEIVED` to `SEARCH_IN_PROGRESS` as an automatic side effect, incrementing the order's `version` by one. Each assignment tracks three read-only counters: `document_count`, the number of linked documents not in `VOID` status; `verified_count`, the number of linked documents in `VERIFIED` status; and `revision_count`, which starts at 0 and increments by one each time the assignment is returned for correction. The `return_reason` recorded from the most recent return stays null until the first return occurs. The assignment itself begins in `IN_PROGRESS`.

### 3.4. Walking the Indexes: Recording Instruments and the Chain of Title

As the search proceeds, the assigned `Abstracter` records each discovered instrument with a payload naming the `order_id` and the `assignment_id` that surfaced it, an `instrument_type` of `DEED`, `MORTGAGE`, `LIEN`, `JUDGMENT`, `TAX_LIEN`, `EASEMENT`, or `RESTRICTION`, the `grantor_name` and `grantee_name` exactly as indexed, the county's `instrument_number`, and the `recording_date` in ISO `YYYY-MM-DD` form. Within a single order, an `instrument_number` may appear on only one non-`VOID` document; a duplicate is rejected with `ERR_DUPLICATE_INSTRUMENT` (HTTP 409). Two optional inputs complete the record: `prior_document_id`, which links a deed to its chain-of-title predecessor, and `exception_applies` (default false), which marks an instrument — typically an `EASEMENT` or `RESTRICTION` — as one that must surface as a title exception in the report.

Recording derives two read-only flags. The scope flag `in_scope` is true exactly when `recording_date` falls on or after the order's `scope_start_date` and on or before its `effective_date` — both bounds are inclusive, so an instrument recorded exactly on `scope_start_date` is in scope while one recorded the day before is not. The chain flag `chain_break_flag` applies only to a `DEED` whose `prior_document_id` is set: it is true when the new deed's `grantor_name`, after trimming surrounding whitespace, differs — case-sensitively — from the prior document's `grantee_name` trimmed the same way, and false in every other case (non-deed instruments, or no predecessor supplied). The chain link itself is validated: `prior_document_id`, when present, must reference a document of the same order whose `instrument_type` is `DEED` and whose status is not `VOID`, else the recording is rejected with `ERR_CHAIN_LINK_INVALID` (HTTP 422). Each recording recomputes the assignment's `document_count`.

Every recorded document begins in `REPORTED` status. The assigned abstracter then dispositions each one. Verifying a document moves it from `REPORTED` to `VERIFIED` — or from `FLAGGED_FOR_CURATIVE` to `VERIFIED` once its issue is cured — and recomputes the assignment's `verified_count`. Flagging a document moves it from `REPORTED` to `FLAGGED_FOR_CURATIVE` and, as a cascade, raises a `CurativeRequirement` on the order with `record_document_id` pointing at the flagged document, `raised_by_examiner_ref` left null (the system raised it), `description` set to the supplied `reason`, and `severity` of `CRITICAL` when the instrument is a `LIEN`, `JUDGMENT`, or `TAX_LIEN` and `STANDARD` otherwise; the order's `open_curative_count` increments by one. Voiding moves a mistakenly recorded document from `REPORTED` to `VOID`; voiding is available both to the assigned abstracter and to an `OperationsManager`, accepts an optional `reason`, and recomputes the assignment's `document_count` — record-then-void is a compensating pair that leaves `document_count` unchanged. All three dispositions require that the acting abstracter match the assignment's `abstracter_ref` (else `ERR_FORBIDDEN`), that the assignment still be `IN_PROGRESS` (else `ERR_INVALID_STATE`), and that the parent order not be terminal (else `ERR_ORDER_TERMINAL`); the void action additionally permits the `OperationsManager` regardless of the abstracter match.

### 3.5. Closing the Search: Submission, Examination, and the Correction Loop

When every recorded instrument has been dispositioned, the assigned `Abstracter` submits the assignment, moving it from `IN_PROGRESS` to `SUBMITTED`. Submission enforces four checks in order: the caller must be the assignment's own abstracter (else `ERR_FORBIDDEN`); the parent order must not be terminal (else `ERR_ORDER_TERMINAL`); the assignment must link at least one non-`VOID` document (else `ERR_EMPTY_ASSIGNMENT`, HTTP 422); and no linked document may still sit in `REPORTED` (else `ERR_DOCUMENTS_NOT_EXAMINED`, HTTP 409) — the examiner expects everything either verified, flagged, or voided.

Examination then runs a revision loop. An `Examiner` may accept a `SUBMITTED` assignment, moving it to `ACCEPTED`; or return it, moving it from `SUBMITTED` to `RETURNED_FOR_CORRECTION` with a mandatory `reason`, incrementing `revision_count` by one and recording `return_reason` from that reason. The assigned abstracter resumes a returned assignment, moving it from `RETURNED_FOR_CORRECTION` back to `IN_PROGRESS`, and the loop may repeat. Acceptance is the trigger that re-evaluates the order's search-completion guard: the order advances from `SEARCH_IN_PROGRESS` to `SEARCH_COMPLETE` when at least one assignment exists for it outside `CANCELLED`, every non-`CANCELLED` assignment has reached `ACCEPTED`, and no legal hold is in effect — and when the guard passes, the order's `version` increments by one. The same guard is re-evaluated each time a legal hold clears. Accept, return, and resume each refuse to run against a terminal order with `ERR_ORDER_TERMINAL`, and the abstracter-scoped actions refuse a mismatched caller with `ERR_FORBIDDEN`.

### 3.6. Legal Description Verification and the Survey Exception

In parallel with the field search, an `OperationsManager` runs intake quality control by opening a legal description check for the order, supplying a `survey_reference` and the `checked_legal_description` as abstracted from the records. The check begins `PENDING`.

The verdict comes in two shapes, both recorded by an `OperationsManager` with a `verdict` and a `survey_exception_applied` flag. A `verdict` of `VERIFIED` moves the check from `PENDING` to `VERIFIED` and records the supplied flag on `survey_exception_applied` — when true, a standard survey exception must be carried into the report. A `verdict` of `MISMATCH` moves the check from `PENDING` to `MISMATCH`, likewise records the flag, and sets the order's `legal_hold` to true: the order now carries a read-only hold that remains true while any check on it is in `MISMATCH`. An `OperationsManager` resolves a mismatch by supplying the corrected `resolved_description`, moving the check from `MISMATCH` to `RESOLVED`; resolution overwrites the order's `legal_description_text` with the corrected value, clears `legal_hold` when no other `MISMATCH` check remains, increments the order's `version` by one, and re-evaluates the search-completion guard described in §3.5 — so clearing the last hold on a fully accepted order is itself enough to complete the search phase. Verdicts and resolutions against a terminal order are refused with `ERR_ORDER_TERMINAL`.

### 3.7. Compiling the Abstract Report: Drafting, Review Slots, and Approval

Once the order sits in `SEARCH_COMPLETE`, the assigned `Abstracter` opens the abstract report by supplying the `order_id`, a `title`, and `expected_abstract_order_version`. Opening the report is the transition that moves the order from `SEARCH_COMPLETE` to `REPORT_DRAFTING`; the guard enforces three conditions — the order must actually be in `SEARCH_COMPLETE` (else `ERR_INVALID_STATE`), no other report for the order may currently occupy any of `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUIRED`, or `APPROVED` (else `ERR_REPORT_ALREADY_ACTIVE`, HTTP 409), and the supplied version must match the order's current `version` (else `ERR_STALE_VERSION`, HTTP 412, per §2.8). The report is created in `DRAFT`, and the order's `version` increments by one. A fresh report's `revision_number` starts at 0; `revision_reason`, `reviewer_examiner_ref`, `review_slot_start`, and `review_slot_end` all begin null.

The abstracter submits the draft — or a revised draft — moving the report from `DRAFT` (or `REVISION_REQUIRED`) to `SUBMITTED`; submission requires the parent order to be in `REPORT_DRAFTING` (else `ERR_INVALID_STATE`), and it moves the order from `REPORT_DRAFTING` to `REPORT_UNDER_REVIEW`, incrementing the order's `version`. An `Examiner` then takes the report under review by booking a review slot with `review_slot_start` and `review_slot_end`. The slot must be strictly ordered — an end not later than the start yields `ERR_SLOT_INVALID` (HTTP 422) — and it must respect the examiner's buffered calendar: against every other non-`CANCELLED` report slot booked to the same examiner, the gap between the new slot and each existing slot must be at least thirty minutes on both sides, with a gap of exactly thirty minutes permitted; any tighter packing is rejected with `ERR_SLOT_CONFLICT` (HTTP 409). Booking records `reviewer_examiner_ref` as the acting examiner's `X-User-ID` along with both slot endpoints, and moves the report from `SUBMITTED` to `UNDER_REVIEW`.

The reviewing examiner then dispositions the report. Approval — moving the report from `UNDER_REVIEW` to `APPROVED` — requires that the caller be the booked `reviewer_examiner_ref` (else `ERR_FORBIDDEN`) and that no curative requirement on the order remains `OPEN` (else `ERR_OPEN_CURATIVE_REQUIREMENTS`, HTTP 409); approval moves the order from `REPORT_UNDER_REVIEW` to `READY_FOR_DELIVERY` and increments the order's `version`. Requiring revision — moving the report from `UNDER_REVIEW` to `REVISION_REQUIRED` — likewise requires the booked reviewer, takes a mandatory `reason`, increments `revision_number` by one, records `revision_reason` from that reason, returns the order from `REPORT_UNDER_REVIEW` to `REPORT_DRAFTING`, and increments the order's `version`; the abstracter may then re-submit, and the loop repeats.

### 3.8. The Curative List: Raising, Satisfying, and Waiving Requirements

Beyond the system-raised requirements produced by flagging (§3.4), an `Examiner` may raise a curative requirement directly against an order, supplying the `order_id`, a `description` of what must be cured before the report can be approved, optionally a `record_document_id` tying the requirement to a recorded instrument, and optionally a `severity` of `LOW`, `STANDARD` (the default), or `CRITICAL`. A directly raised requirement books `raised_by_examiner_ref` as the raiser's `X-User-ID`; every requirement opens in `OPEN` status with `resolution_note` null, and each opening increments the order's `open_curative_count` by one — a read-only tally of how many requirements remain open.

Requirements close in two directions. The assigned abstracter satisfies a requirement by supplying a `resolution_note`, moving it from `OPEN` to `SATISFIED` and decrementing `open_curative_count`. An examiner waives a requirement, also supplying a `resolution_note`, moving it from `OPEN` to `WAIVED` and decrementing the count — but waiver carries two safety checks, evaluated after the generic guards: a requirement whose `severity` is `CRITICAL` cannot be waived at all (`ERR_CRITICAL_NOT_WAIVABLE`, HTTP 422), and segregation of duties forbids the waiving examiner from being the same examiner who raised it, so a waiver is refused with `ERR_SOD_WAIVER_FORBIDDEN` (HTTP 403) whenever `raised_by_examiner_ref` is non-null and equals the caller's `X-User-ID` — a system-raised requirement, whose raiser is null, may be waived by any examiner. Both closure paths refuse a terminal parent order with `ERR_ORDER_TERMINAL`. Because approval (§3.7) demands a zero open count, every requirement must reach `SATISFIED` or `WAIVED` before the report can be approved.

### 3.9. County Retrievals and the Pass-Through Fee Ledger

When the report needs the county's own copy of an instrument, the assigned `Abstracter` requests a county retrieval naming the `order_id`, the `record_document_id` to pull, and the `county` to pull it from. The county's charging mode is captured in `fee_mode` — `PER_DOCUMENT` (the default) or `PER_PAGE` — with `page_count` accompanying the per-page mode: a `PER_PAGE` request without a `page_count` of at least 1 is rejected with `ERR_PAGE_COUNT_INVALID` (HTTP 422), while for the per-document mode the field is ignored. The retrieval opens in `REQUESTED`, its `fee_cents` null until a fee is posted.

Fee handling belongs to the `OperationsManager`. Posting the fee moves a retrieval from `REQUESTED` to `FEE_POSTED` and computes `fee_cents`: a flat 2500 cents when the mode is `PER_DOCUMENT`, regardless of any page count; or `page_count` times 125 cents when the mode is `PER_PAGE` — a ten-page instrument therefore costs 1250 cents instead of 2500. Posting then recomputes the order's running fee per §2.6: the base fee of 40000 cents plus the sum of `fee_cents` over every retrieval of the order in `FEE_POSTED` or `INVOICED` status — `REQUESTED` retrievals carry no fee and `FEE_REVERSED` retrievals are excluded — plus, for `RUSH` orders only, the twenty-five-percent premium computed once on that whole subtotal and rounded half up; the liability cap is recomputed alongside. Reversing a fee moves a retrieval from `FEE_POSTED` to `FEE_REVERSED`, accepts an optional `reason`, and recomputes the running fee and cap the same way — post-then-reverse is the compensating pair that leaves `accrued_fees_cents` unchanged.

The fiscal guards here run ahead of the generic state checks, per §2.10. Posting against a retrieval already in `FEE_POSTED` or `FEE_REVERSED` is refused with `ERR_FEE_ALREADY_POSTED` (HTTP 409); posting against an `INVOICED` retrieval, or reversing one, is refused with `ERR_ALREADY_INVOICED` (HTTP 409) — an invoiced fee can never be touched. Reversing a retrieval still in `REQUESTED` or already `FEE_REVERSED` falls through to the generic guard and is refused with `ERR_INVALID_STATE` (HTTP 409). Both operations refuse a terminal parent order with `ERR_ORDER_TERMINAL`, subject to the invoicing precedence above.

### 3.10. Cancellation and Delivery: The Two Ways an Engagement Ends

An order may be cancelled from any non-terminal state — `RECEIVED`, `SEARCH_IN_PROGRESS`, `SEARCH_COMPLETE`, `REPORT_DRAFTING`, `REPORT_UNDER_REVIEW`, or `READY_FOR_DELIVERY` — by the `Client` who owns it (the order's `client_ref` must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN`) or by an `OperationsManager`, with an optional `reason`. Cancellation executes the full downward cascade of §2.9: in-flight assignments cancel, a live report cancels, posted-but-uninvoiced retrieval fees reverse, and the running fee is recomputed; the order's `version` increments by one, and the order lands in `CANCELLED`. An order already `DELIVERED` or `CANCELLED` cannot be cancelled again — the transition does not exist from a terminal state, so the attempt surfaces `ERR_INVALID_STATE`.

Delivery is the happy path, performed by an `OperationsManager` against an order in `READY_FOR_DELIVERY` — from any other state the request is refused with `ERR_INVALID_STATE`. Delivery stamps `delivered_at` from the logical clock and then runs the three-link cascade of §2.9: the order's `APPROVED` report moves to `DELIVERED`; that report delivery moves every retrieval of the order still in `FEE_POSTED` to `INVOICED`; and the invoicing triggers the closing computations on the order. The final fee `final_fee_cents` is set to the running `accrued_fees_cents` as it stands at that instant. The late credit is then evaluated against the logical clock: when `delivered_at` is strictly later than `due_at`, `late_credit_cents` is ten percent of `final_fee_cents` rounded half up; a delivery exactly at `due_at` is on time and earns a credit of 0. The billed amount `billed_fee_cents` is the final fee minus the late credit. Finally the liability cap is recomputed with `final_fee_cents` as its fee basis per §2.7, and the order's `version` increments by one. From `DELIVERED`, as from `CANCELLED`, no further child mutation is possible.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state-transition actions, amendments, deliveries, and cancellations — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/abstract-orders` | Place a new abstracting order; stamps receipt from the logical clock and computes the provisional quote, running fee, due instant, and liability cap | Client |
| GET | `/api/abstract-orders/{id}` | Fetch one order with all computed fields; the overdue flag is evaluated against the logical clock at read time | Client, Abstracter, Examiner, OperationsManager |
| GET | `/api/abstract-orders` | List orders with pagination; a `Client` sees only their own orders | Client, Abstracter, Examiner, OperationsManager |
| PATCH | `/api/abstract-orders/{id}` | Amend engagement scope while the order is early; OCC-guarded | OperationsManager |
| POST | `/api/abstract-orders/{id}/cancel` | Cancel a non-terminal order; cascades to assignments and report, reverses posted fees | Client, OperationsManager |
| POST | `/api/abstract-orders/{id}/deliver` | Deliver an approved order; finalizes fees, applies the late credit, invoices retrievals | OperationsManager |
| POST | `/api/search-assignments` | Dispatch a search assignment with a committed work window; the first assignment starts the search phase | OperationsManager |
| GET | `/api/search-assignments/{id}` | Fetch one assignment | Client, Abstracter, Examiner, OperationsManager |
| GET | `/api/search-assignments` | List assignments with pagination and filters | Client, Abstracter, Examiner, OperationsManager |
| POST | `/api/search-assignments/{id}/submit` | Abstracter submits the completed search for examination | Abstracter |
| POST | `/api/search-assignments/{id}/accept` | Examiner accepts a submitted search; may complete the order's search phase | Examiner |
| POST | `/api/search-assignments/{id}/return` | Examiner returns a submitted search for correction | Examiner |
| POST | `/api/search-assignments/{id}/resume` | Abstracter resumes work on a returned assignment | Abstracter |
| POST | `/api/record-documents` | Record a discovered instrument against an assignment | Abstracter |
| GET | `/api/record-documents/{id}` | Fetch one recorded document | Client, Abstracter, Examiner, OperationsManager |
| GET | `/api/record-documents` | List recorded documents with pagination and filters, including chain children via the predecessor filter | Client, Abstracter, Examiner, OperationsManager |
| POST | `/api/record-documents/{id}/verify` | Abstracter verifies a reported or flagged document | Abstracter |
| POST | `/api/record-documents/{id}/flag` | Abstracter flags a reported document for curative action; auto-raises a requirement | Abstracter |
| POST | `/api/record-documents/{id}/void` | Void a mistakenly recorded document (compensating action) | Abstracter, OperationsManager |
| POST | `/api/legal-description-checks` | Open a legal-description verification / survey-exception check | OperationsManager |
| GET | `/api/legal-description-checks/{id}` | Fetch one legal description check | Client, Abstracter, Examiner, OperationsManager |
| GET | `/api/legal-description-checks` | List legal description checks with pagination and filters | Client, Abstracter, Examiner, OperationsManager |
| POST | `/api/legal-description-checks/{id}/submit-verdict` | Record the verification verdict; a mismatch puts the order on legal hold | OperationsManager |
| POST | `/api/legal-description-checks/{id}/resolve` | Resolve a mismatch with the corrected legal description; clears the hold and may complete the search phase | OperationsManager |
| POST | `/api/abstract-reports` | Open the abstract report for a search-complete order; OCC-guarded | Abstracter |
| GET | `/api/abstract-reports/{id}` | Fetch one report | Client, Abstracter, Examiner, OperationsManager |
| GET | `/api/abstract-reports` | List reports with pagination and filters | Client, Abstracter, Examiner, OperationsManager |
| POST | `/api/abstract-reports/{id}/submit` | Submit a draft or revised report for examination | Abstracter |
| POST | `/api/abstract-reports/{id}/start-review` | Examiner books a buffered review slot and takes the report under review | Examiner |
| POST | `/api/abstract-reports/{id}/approve` | Reviewing examiner approves the report; requires zero open curative requirements | Examiner |
| POST | `/api/abstract-reports/{id}/require-revision` | Reviewing examiner sends the report back for revision | Examiner |
| POST | `/api/curative-requirements` | Examiner raises a curative requirement, optionally tied to a recorded document | Examiner |
| GET | `/api/curative-requirements/{id}` | Fetch one curative requirement | Client, Abstracter, Examiner, OperationsManager |
| GET | `/api/curative-requirements` | List curative requirements with pagination and filters | Client, Abstracter, Examiner, OperationsManager |
| POST | `/api/curative-requirements/{id}/satisfy` | Abstracter marks a requirement cured | Abstracter |
| POST | `/api/curative-requirements/{id}/waive` | Examiner waives a non-critical requirement raised by a different examiner | Examiner |
| POST | `/api/county-retrievals` | Abstracter requests county retrieval of a recorded instrument | Abstracter |
| GET | `/api/county-retrievals/{id}` | Fetch one county retrieval | Client, Abstracter, Examiner, OperationsManager |
| GET | `/api/county-retrievals` | List county retrievals with pagination and filters | Client, Abstracter, Examiner, OperationsManager |
| POST | `/api/county-retrievals/{id}/post-fee` | OperationsManager posts the county pass-through fee; recomputes the running fee and liability cap | OperationsManager |
| POST | `/api/county-retrievals/{id}/reverse-fee` | OperationsManager reverses a posted, not-yet-invoiced fee | OperationsManager |
| POST | `/api/_clock/set_current_utc` | Advance the test-driving logical clock; re-evaluates overdue flags on all non-terminal orders | OperationsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_CHECK_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_CURATIVE_NOT_FOUND` | 404 |
| `ERR_RETRIEVAL_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_TERMINAL` | 409 |
| `ERR_CRITICAL_NOT_WAIVABLE` | 422 |
| `ERR_SOD_WAIVER_FORBIDDEN` | 403 |
| `ERR_WINDOW_INVALID` | 422 |
| `ERR_SLOT_INVALID` | 422 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_SLOT_CONFLICT` | 409 |
| `ERR_DUPLICATE_INSTRUMENT` | 409 |
| `ERR_REPORT_ALREADY_ACTIVE` | 409 |
| `ERR_EMPTY_ASSIGNMENT` | 422 |
| `ERR_DOCUMENTS_NOT_EXAMINED` | 409 |
| `ERR_CHAIN_LINK_INVALID` | 422 |
| `ERR_PAGE_COUNT_INVALID` | 422 |
| `ERR_FEE_ALREADY_POSTED` | 409 |
| `ERR_ALREADY_INVOICED` | 409 |
| `ERR_SCOPE_LOCKED` | 409 |
| `ERR_OPEN_CURATIVE_REQUIREMENTS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
