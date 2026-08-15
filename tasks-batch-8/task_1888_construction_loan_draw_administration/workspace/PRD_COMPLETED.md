# Construction Loan Draws API — Product Requirements Document

## 1. Introduction

A construction loan is not disbursed as a lump sum. Proceeds move out of the lender's commitment incrementally, each release gated on evidence that the work it pays for has actually been performed: signed lien waivers, vendor invoices, and an independent inspector's percent-complete finding. Between origination and completion the lender must administer the budget line by line (including contingency), withhold and later release retainage, police advances against materials stored off-site, track an interest reserve that services the note until the building cash-flows, and — when the project stands complete — convert the facility into permanent financing. Each of these steps is a control point where money can leak if the paperwork, the inspection, or the arithmetic is wrong.

This document specifies a REST API that administers that full lifecycle for a construction lender. Work moves through an explicit approval chain: a `Borrower` originates draw requests, documents, release requests, and conversion requests; a `DrawProcessor` runs intake, verifies documents, and manages inspections; an `Inspector` reports field results; a `CreditOfficer` holds approval authority over draws, reallocations, releases, and conversions; a `LoanServicer` moves money and runs interest accruals; and a `LenderAdmin` owns borrower, loan, and budget setup. Financial aggregates — disbursed principal, withheld retainage, percent complete, reserve balances — are never written by clients; the server recomputes them from child events as they land, with immediate consistency, so that every read reflects the full history of the loan.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role outside the declared role set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400).

Six roles exist, spelled exactly as follows:

- `LenderAdmin` — lender operations administrator; owns borrower, loan, and budget setup and drafts reallocations.
- `DrawProcessor` — draw intake and review specialist; verifies documents and manages inspections.
- `CreditOfficer` — credit authority; approves draws, reallocations, retainage releases, and conversions.
- `LoanServicer` — servicing desk; moves money and runs interest accruals.
- `Inspector` — third-party inspector; reports inspection results only.
- `Borrower` — borrower contact; submits draws, documents, release requests, and conversion requests for its own loans.

A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). All roles may use every read endpoint; write capabilities are partitioned per role as detailed in §3 and §4.

Identity semantics differ across roles. When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting Borrower record; ownership checks on any resource that traces back to a loan compare the loan's `borrower_id` against `X-User-ID`, and a mismatch on a borrower-only write is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). When `X-User-Role` is `LenderAdmin`, `DrawProcessor`, `CreditOfficer`, `LoanServicer`, or `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. For action endpoints nested under a resource path (submit, start-review, request-revision, reject, withdraw, approve, fund, mark-installed, review, complete, cancel, apply, pay, convert, terminate), the resource addressed by the path is the one returned — except `POST /loans/{id}/interest-accruals`, which returns the `INTEREST_PAYMENT` ledger entry it created (§3.8).
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

List endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 is treated as 1, a `limit` above 100 is treated as 100, and a negative `offset` is treated as 0; a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Results are always sorted by `created_at` in ascending order, with ties broken by creation order, the earlier-created record first. When several filter parameters are supplied on one list call, they combine conjunctively (logical AND). The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned in the page is less than `total_count`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id`, a server-minted UUID with no type prefix. Alongside it sit `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and a `version` integer that starts at 1 when the resource is created and increments by one on every mutation of that resource.

One resource is the exception. Interest reserve ledger entries are an append-only audit trail: once written they never change, so an entry carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. Money, Percentages, and Rounding Discipline

All monetary values throughout the API are integer amounts of cents, carried in fields suffixed `_cents`; fractional-cent results never persist. Percent values — retainage rates, percent-complete readings, advance caps — are decimal numbers carried to two decimal places; percent inputs are accepted exactly as supplied, and the server neither rounds them to two places nor rejects additional decimal precision. Rates of interest are expressed in basis points, so an annual note rate of 12% is written as 1200.

Rounding follows a single default: round half up. Two computations deliberately depart from that default and instead round down to a whole cent — the inspection-based approval cap and the advance cap on uninstalled stored materials, both described in §3.5. Retainage has its own pinned rounding order: every draw line item is rounded to whole cents first, and only then are the per-line amounts summed into the draw total; summing first and rounding once is not equivalent and is not permitted.

### 2.6. State Integrity, Loan-Open Gating, and Cascades

Every state-bearing resource accepts a transition only from a valid from-state. A transition attempted from any other state — including from an already-terminal state — is rejected with `ERR_INVALID_STATE` (HTTP 409). This lockdown also covers idempotency-shaped mistakes such as marking an already-installed line item installed a second time.

The loan's lifecycle gates nearly all child activity. While a loan is `OPEN`, the full toolkit is available; once it is `CONVERTED` or `TERMINATED`, creating budget lines, draws, draw line items, draw documents, inspections, reallocation requests, retainage releases, or conversion reviews against it — and running interest accruals on it — is rejected with `ERR_LOAN_NOT_OPEN` (HTTP 409).

Mutation is never local. Funding a draw ripples outward into its line items, their budget lines, and the loan's aggregates; conversion and termination cascade into every budget line of the loan. Each recomputation bumps the owning resource's `version` and refreshes its `updated_at`, and each loan-level recomputation increments the loan's `version` by one — a discipline that §2.7's concurrency guard and §3's workflows rely on throughout.

### 2.7. Optimistic Concurrency on Reallocation Drafting

Exactly one write is guarded by optimistic concurrency control: drafting a budget reallocation (the `POST /reallocation-requests` endpoint). The request body must carry `expected_loan_version`, a non-optional field holding the value of the target loan's `version` that the client last observed. If the loan's current `version` no longer matches — because any loan-mutating operation has advanced it since the client's last read — the create is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412), so the client never drafts a reallocation against a budget state it has not observed. No other endpoint in the API accepts a version field.

### 2.8. Validation Evaluation Order

When several checks could reject the same request, they run in a fixed priority order and the earliest failing check determines the error returned. The order is:

1. **Request context.** `X-User-ID` and `X-User-Role` are present and the role is one of the declared roles — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400).
2. **Role authorization.** The role is permitted for the endpoint — otherwise `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. **Borrower ownership.** On borrower-role writes, `X-User-ID` equals the target loan's `borrower_id` — otherwise `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). This covers creating draws, submitting or withdrawing a draw, adding line items or documents, requesting retainage releases, and requesting conversion reviews. Evaluating this check requires the target loan to be resolved first (for line items and documents, through the referenced draw), so an unresolvable identifier in the body surfaces `ERR_NOT_FOUND` before the ownership comparison runs; on retainage-release creation the budget line is resolved before ownership as well.
4. **Existence.** Every identifier in the path and body resolves to an existing resource — otherwise `ERR_NOT_FOUND` (HTTP 404).
5. **Stale-version guard.** On reallocation drafting only, `expected_loan_version` equals the loan's current `version` — otherwise `ERR_STALE_LOAN_VERSION` (HTTP 412).
6. **State validity and loan-open gating.** The resource is in a valid from-state for the requested transition, and child creation happens only under an `OPEN` loan — otherwise `ERR_INVALID_STATE` or `ERR_LOAN_NOT_OPEN` (both HTTP 409). Within this tier, state-transition endpoints check the addressed resource's own from-state before the loan-open gate, while child-creation endpoints under a draw (line items, documents) run the loan-open gate before the parent draw's intake-state check; on decision-bearing review endpoints the `decision` field is validated between the two, ahead of any decision-specific loan-open gate.
7. **Lien-waiver compliance.** The draw-approval waiver gate of §3.5 — otherwise `ERR_LIEN_WAIVER_UNVERIFIED` (HTTP 409).
8. **Temporal rules.** Billing-period validity at draw creation, half-open period overlap at submission, inspection scheduling gaps, and accepted-inspection staleness at approval — surfaced as `ERR_DRAW_PERIOD_INVALID` (HTTP 422), `ERR_DRAW_PERIOD_OVERLAP` (HTTP 409), `ERR_INSPECTION_SCHEDULE_CONFLICT` (HTTP 409), or `ERR_INSPECTION_STALE` (HTTP 409).
9. **Structural rules.** Line-item presence, cost-code uniqueness, stored-materials evidence, reallocation direction, single open conversion review, and mark-installed eligibility — surfaced as `ERR_DRAW_HAS_NO_LINES` (HTTP 422), `ERR_DUPLICATE_COST_CODE` (HTTP 409), `ERR_STORED_MATERIALS_EVIDENCE_MISSING` (HTTP 422), `ERR_INVALID_REQUEST` (HTTP 400), `ERR_REALLOCATION_SAME_LINE` (HTTP 422), `ERR_CONTINGENCY_DIRECTION_VIOLATION` (HTTP 422), `ERR_CONVERSION_IN_PROGRESS` (HTTP 409), or `ERR_LINE_NOT_STORED_MATERIALS` (HTTP 422).
10. **Cross-entity linkage and readiness.** Budget-line-to-loan matching, inspection-to-draw-to-loan matching, accepted-inspection presence at approval, retainage-release eligibility, and conversion readiness — surfaced as `ERR_BUDGET_LINE_LOAN_MISMATCH` (HTTP 422), `ERR_DRAW_LOAN_MISMATCH` (HTTP 422), `ERR_INSPECTION_REQUIRED` (HTTP 409), `ERR_RETAINAGE_NOT_RELEASABLE` (HTTP 409), or `ERR_CONVERSION_PRECONDITIONS_UNMET` (HTTP 409).
11. **Fiscal caps.** Commitment ceiling, invoice coverage, nothing-approvable, release-vs-retained, reallocation floor, and zero-activity termination — surfaced as `ERR_COMMITMENT_EXCEEDED` (HTTP 422), `ERR_INVOICE_COVERAGE_INSUFFICIENT` (HTTP 422), `ERR_NOTHING_APPROVABLE` (HTTP 422), `ERR_RELEASE_EXCEEDS_RETAINED` (HTTP 422), `ERR_REALLOCATION_BELOW_FLOOR` (HTTP 422), or `ERR_LOAN_HAS_ACTIVITY` (HTTP 409).

A missing required field, an empty string where a required string must be non-empty, an invalid enum value, or a non-positive value in an amount field this document declares positive is a structural failure reported as `ERR_INVALID_REQUEST` (HTTP 400). Four numeric fields accept zero and reject only negative values: `interest_rate_annual_bps`, `interest_reserve_initial_cents`, `permanent_interest_rate_annual_bps`, and `stored_materials_observed_cents`.

### 2.9. Identifier Existence and Referential Checks

Every identifier appearing in a URL path or a request body — including `loan_id`, `draw_id`, `budget_line_id`, `from_budget_line_id`, `to_budget_line_id`, and `borrower_id` — must resolve to an existing resource; an unresolvable reference is rejected with `ERR_NOT_FOUND` (HTTP 404). Where a path nests resources, path parameters are validated left to right, so an unknown parent id surfaces before any child-level check runs.

## 3. Business Logic & Workflows

### 3.1. Borrower Onboarding and Loan Origination

Before any money can move, a `LenderAdmin` registers the borrowing entity. Registration captures the borrower's `legal_name`, a primary `contact_email`, and an `entity_type` of `INDIVIDUAL`, `LLC`, `CORPORATION`, or `PARTNERSHIP`. The resulting record's `id` becomes the ownership anchor for everything that follows: any borrower-role write against a loan compares `X-User-ID` to the loan's `borrower_id`. A borrower record can be fetched by id by any role.

Loan origination is likewise a `LenderAdmin` capability. Creating a loan takes the `borrower_id` of a registered borrower, the `commitment_amount_cents` establishing the total construction commitment, the `interest_rate_annual_bps` note rate in basis points, the `interest_reserve_initial_cents` funding the interest reserve at origination, and the `maturity_date` as an ISO 8601 calendar date. `commitment_amount_cents` must be a positive integer; `interest_rate_annual_bps` and `interest_reserve_initial_cents` must be non-negative integers, zero included. Four policy knobs are optional and default when omitted: `day_count_convention` selects the interest accrual variant and defaults to `ACTUAL_360` (the alternative being `THIRTY_360`); `retainage_pct`, the standard percent withheld from each approved draw line, defaults to 10.00; `reduced_retainage_pct`, the percent withheld once the completion milestone is reached, defaults to 5.00; `retainage_milestone_pct`, the inspection-verified percent complete at or above which retainage reduces, defaults to 50.00; and `stored_materials_max_pct`, the maximum advance against a stored-materials line's invoice value, defaults to 75.00.

A new loan is born `OPEN`. Origination seeds the interest reserve ledger with an `INITIAL_DEPOSIT` entry: its `entry_index` is 1, its `amount_cents` is the positive `interest_reserve_initial_cents`, and its `reserve_balance_after_cents` equals that same initial amount. The loan's computed surface starts clean: `total_original_budget_cents`, `principal_disbursed_cents`, `retained_cents`, `interest_reserve_swept_cents`, and `interest_capitalized_cents` all begin at 0; `inspection_percent_complete` and `cost_percent_complete` begin at 0.00; `interest_reserve_depleted`, `milestone_reached`, and `retainage_fully_released` begin false; and `permanent_interest_rate_annual_bps` with `permanent_term_months` remain null until conversion. The `interest_reserve_balance_cents` is initialized to `interest_reserve_initial_cents` and thereafter always equals the initial reserve plus the signed sum of every ledger entry's `amount_cents`. Loans can be fetched individually with their computed aggregates, or listed with optional `borrower_id` and `status` filters.

### 3.2. Budget Architecture and the Commitment Cap

With a loan open, a `LenderAdmin` builds out its budget as a flat set of budget lines. Each line carries the owning `loan_id`, a `cost_code`, a free-text `description`, an `original_amount_cents` that must be positive, and an optional `is_contingency` flag that defaults to false. Within one loan a `cost_code` may be used only once; a duplicate is rejected with `ERR_DUPLICATE_COST_CODE` (HTTP 409).

The commitment is a hard ceiling: the sum of `original_amount_cents` across all of a loan's budget lines may never exceed the loan's `commitment_amount_cents`. A line whose addition would break that ceiling is rejected with `ERR_COMMITMENT_EXCEEDED` (HTTP 422).

A budget line is born `ACTIVE`, with `revised_amount_cents` initialized to its `original_amount_cents` and `disbursed_cents`, `retained_cents`, and `approved_unfunded_cents` all starting at 0. Creating a line also refreshes the loan's `total_original_budget_cents`, and that recomputation increments the loan's `version`. Contingency lines play a special role later: a line flagged `is_contingency` may serve as the source of a budget reallocation but never as its target (§3.7). Budget lines can be fetched by id or listed with optional `loan_id`, `is_contingency`, and `status` filters; the `is_contingency` filter parses its query value after trimming surrounding whitespace and lowercasing, with `true`, `1`, or `yes` selecting contingency lines and any other value selecting non-contingency lines.

### 3.3. Draw Intake, Line Items, and Supporting Documents

A draw request begins with the `Borrower`. Creating one names the `loan_id` and the billing period as `period_start_date` and `period_end_date` — both ISO dates, start inclusive and end exclusive — and the end must fall strictly after the start, or the create is rejected with `ERR_DRAW_PERIOD_INVALID` (HTTP 422). The server stamps the draw with a `draw_number`, a per-loan monotone sequence that starts at 1, assigns each new draw the highest existing number on that loan plus one, and is never reused even if a draw is later withdrawn or rejected. A new draw sits in `DRAFT`; its `requested_total_cents`, `approved_total_cents`, `retainage_total_cents`, and `funded_total_cents` all start at 0, `revision_notes` and `rejection_reason` start null, `effective_retainage_pct` starts null, and `milestone_applied` starts false.

While the draw is `DRAFT` — or later, while it sits in `REVISION_REQUESTED` — the borrower builds it up with line items. A line item names its `draw_id`, the `budget_line_id` it charges against, a `line_type` of `WORK_COMPLETED` or `STORED_MATERIALS`, and a positive `requested_cents`. The referenced budget line must belong to the same loan as the draw; a cross-loan reference is rejected with `ERR_BUDGET_LINE_LOAN_MISMATCH` (HTTP 422). Stored-materials lines carry evidentiary baggage: `stored_material_invoice_cents` (the invoice value of the stored materials), `insurance_certificate_ref` (the insurance evidence reference), and `stored_location` (where the materials sit) are all required whenever `line_type` is `STORED_MATERIALS`, and their absence yields `ERR_STORED_MATERIALS_EVIDENCE_MISSING` (HTTP 422). Those same three fields are forbidden on a `WORK_COMPLETED` line — their presence there is `ERR_INVALID_REQUEST` (HTTP 400). An optional `installed_by_date` records the ISO date by which stored materials must be installed. On the computed side, `is_installed` starts false and `installed_date` null, while `approved_cents`, `retainage_cents`, `net_fundable_cents`, and `funded_cents` all start at 0 until approval and funding compute them. Every line-item addition recomputes the draw's `requested_total_cents` as the sum of its items' `requested_cents`.

Paperwork rides along the same intake window: while a draw is `DRAFT` or `REVISION_REQUESTED`, the borrower attaches documents by `draw_id`, each with a `doc_type` of `LIEN_WAIVER_CONDITIONAL`, `LIEN_WAIVER_UNCONDITIONAL`, `INVOICE`, or `INSURANCE_CERTIFICATE`, a `party_name` identifying the contractor or vendor, a positive `amount_cents`, the document's `doc_date`, and an optional `reference_number` for the external document or invoice number. A document starts `SUBMITTED`. A `DrawProcessor` then reviews each one, passing a `decision` of `VERIFIED` or `REJECTED`; a rejection also takes a `reason`, which is recorded as the document's `rejection_reason`. Only `VERIFIED` documents count toward the approval gates of §3.5. Line items can be listed with optional `draw_id`, `budget_line_id`, and `line_type` filters; documents with optional `draw_id`, `doc_type`, and `status` filters; draws themselves with optional `loan_id` and `status` filters.

Submission closes the intake loop. The borrower — and only the borrower whose id matches the loan's `borrower_id` — submits a `DRAFT` draw, moving it to `SUBMITTED`. Two guards apply, running in the §2.8 order — temporal (8) before structural (9): first, the billing period must not collide with a sibling draw of the same loan that sits in `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `APPROVED`, or `FUNDED`. Periods are half-open intervals: two periods overlap when the new period's `period_start_date` falls before the sibling's `period_end_date` and the sibling's `period_start_date` falls before the new period's `period_end_date`. Adjacency is allowed — a new period whose `period_start_date` equals a sibling's `period_end_date` touches but does not overlap it. A genuine collision is rejected with `ERR_DRAW_PERIOD_OVERLAP` (HTTP 409). Second, the draw must contain at least one line item, or submission fails with `ERR_DRAW_HAS_NO_LINES` (HTTP 422). The borrower may instead abandon the draw: withdrawal moves a `DRAFT`, `SUBMITTED`, or `REVISION_REQUESTED` draw to the terminal `WITHDRAWN` state.

### 3.4. Inspections and Verified Progress

Draw approval leans on independent verification, so a `DrawProcessor` orders inspections. Ordering takes the `loan_id`, a `scheduled_date`, and optionally a `draw_id`: supplying one creates a draw inspection tied to that draw, while omitting it creates a completion inspection not tied to any draw (its `draw_id` stays null). When `draw_id` is supplied, that draw must belong to the named loan, or the order is rejected with `ERR_DRAW_LOAN_MISMATCH` (HTTP 422). Scheduling keeps a minimum three-day gap on a loan: if the new inspection's `scheduled_date` falls within two days, in either direction, of the `scheduled_date` of an existing `ORDERED` inspection on the same loan, the order is rejected with `ERR_INSPECTION_SCHEDULE_CONFLICT` (HTTP 409). A successfully ordered inspection starts `ORDERED`; a `DrawProcessor` may cancel one still `ORDERED`, moving it to `CANCELLED`.

Fieldwork is reported by an `Inspector`. Completing an `ORDERED` inspection records the `percent_complete_reported` — a value from 0.00 to 100.00 inclusive, with anything outside that range rejected as `ERR_INVALID_REQUEST` (HTTP 400) — together with the `completed_date` the inspection was performed, an optional `stored_materials_observed_cents` valuing materials seen on site (a non-negative integer when present), and optional `notes`. The inspection moves to `COMPLETED`.

A `DrawProcessor` then adjudicates the report with a `decision`. `REJECTED` takes a `reason`, recorded as the inspection's `rejection_reason`, and the report is discarded. `ACCEPTED` is consequential: the loan's `inspection_percent_complete` is recomputed as the `percent_complete_reported` of the loan's latest `ACCEPTED` inspection, where "latest" means the greatest `completed_date` with ties broken by the greatest `created_at` and any remaining tie broken in favor of the later-created inspection, and reads 0.00 while no accepted inspection exists. Whenever that recomputed value reaches or exceeds the loan's `retainage_milestone_pct` — an inclusive boundary — the loan's `milestone_reached` latches true and never flips back, even if a later accepted inspection reports a lower percent. The recomputation increments the loan's `version`. Inspections can be fetched by id or listed with optional `loan_id`, `draw_id`, and `status` filters.

Two percent-complete numbers coexist, and they answer different questions. The inspection-based `inspection_percent_complete` just described drives milestone gating, retainage reduction, and conversion readiness; it typically runs ahead of cost early in a project. The cost-based `cost_percent_complete` is a reporting field: the sum, across all of the loan's budget lines in any status, of each line's `disbursed_cents` plus its `retained_cents`, divided by the sum of all lines' `revised_amount_cents`, multiplied by 100, and rounded half-up to two decimal places; while the loan has no budget lines it reads 0.00. Identical inputs produce different percents under the two variants, by design.

### 3.5. Draw Review, Approval Mathematics, and Funding

Once a draw is `SUBMITTED`, a `DrawProcessor` takes it up, moving it from `SUBMITTED` to `UNDER_REVIEW`. Review has three exits. Sending it back for revision moves it to `REVISION_REQUESTED` and records the supplied `revision_notes` on the draw; the borrower then edits line items and documents and resubmits, closing the cycle `UNDER_REVIEW` → `REVISION_REQUESTED` → `SUBMITTED`, with the earlier `revision_notes` retained on the draw for audit. Rejection is terminal: the draw moves to `REJECTED` and the supplied `reason` is recorded as its `rejection_reason`. The third exit is approval.

Approval belongs to the `CreditOfficer` and is the most heavily gated operation in the product. Its gates run in a fixed order. First, lien-waiver coverage, failing which the draw is rejected with `ERR_LIEN_WAIVER_UNVERIFIED` (HTTP 409): the sum of this draw's `VERIFIED` documents of type `LIEN_WAIVER_UNCONDITIONAL` must be at least the `approved_total_cents` of the most recently funded sibling draw — the one with the highest `draw_number` among the loan's `FUNDED` draws, or zero when no funded sibling exists — and, independently, the sum of this draw's `VERIFIED` documents of type `LIEN_WAIVER_CONDITIONAL` must be at least this draw's own `requested_total_cents`. Documents still `SUBMITTED` or already `REJECTED` count for nothing. Second, inspection staleness: when an `ACCEPTED` inspection linked to this draw exists, the `completed_date` of the latest such inspection — selected exactly as in the approval mathematics below — must lie within the closed interval from the draw's `period_start_date` through its `period_end_date`, or approval is rejected with `ERR_INSPECTION_STALE` (HTTP 409). Third, at least one `ACCEPTED` inspection whose `draw_id` is this draw must exist at all, or approval is rejected with `ERR_INSPECTION_REQUIRED` (HTTP 409). Fourth, invoice coverage, failing which the draw is rejected with `ERR_INVOICE_COVERAGE_INSUFFICIENT` (HTTP 422): the sum of this draw's `VERIFIED` documents of type `INVOICE` must be at least the sum of `requested_cents` across the draw's `WORK_COMPLETED` line items — stored-materials lines carry their own `stored_material_invoice_cents` and are excluded from that requirement. Finally, the computed `approved_total_cents` must be greater than zero, or approval is rejected with `ERR_NOTHING_APPROVABLE` (HTTP 422).

When the gates pass, per-line approval amounts are computed against the draw's inspection — the `ACCEPTED` inspection linked to this draw with the greatest `completed_date`, ties broken by the greatest `created_at` and any remaining tie broken in favor of the later-created inspection, as in §3.4. Each line item's `approved_cents` is the smallest of several ceilings, never below zero. Its cost headroom is the budget line's `revised_amount_cents` minus its `disbursed_cents`, minus its `retained_cents`, minus its `approved_unfunded_cents` — the budget not yet consumed or reserved. Its inspection cap is the budget line's `revised_amount_cents` multiplied by the inspection's `percent_complete_reported` and divided by 100, rounded down to a whole cent, with the line's `disbursed_cents`, `retained_cents`, and `approved_unfunded_cents` then subtracted; a negative result is treated as zero. A `WORK_COMPLETED` line's `approved_cents` is the minimum of its `requested_cents`, its cost headroom, and its inspection cap. A `STORED_MATERIALS` line adds a fourth ceiling, the stored-materials advance cap: if the line's `is_installed` is true the cap equals its full `stored_material_invoice_cents`, and otherwise the cap is that invoice value multiplied by the loan's `stored_materials_max_pct` and divided by 100, rounded down to a whole cent — so an uninstalled line may be advanced at most 75% of invoice value under default policy.

Retainage is computed per line immediately after approval amounts. The effective percent is the loan's `reduced_retainage_pct` when `milestone_reached` is true at that moment and its `retainage_pct` otherwise. Each line's `retainage_cents` is its `approved_cents` multiplied by that effective percent and divided by 100, rounded half up to a whole cent — and the rounding order is pinned: every line is rounded first, and the draw's `retainage_total_cents` is the sum of those rounded per-line amounts, never a rounding of the sum, because the two orders can differ by cents. A line's `net_fundable_cents` is then its `approved_cents` minus its `retainage_cents`.

Approval stamps the draw `APPROVED` and records its `approved_total_cents` as the sum of the per-line `approved_cents`, its `retainage_total_cents` as above, the `effective_retainage_pct` actually applied, and `milestone_applied`, whether `milestone_reached` was true at approve time. Each budget line touched by the draw has its `approved_unfunded_cents` recomputed — that field is the sum of `approved_cents` over the line's items sitting in `APPROVED`, not yet `FUNDED`, draws, reserving headroom against later approvals — and each such recomputation increments the budget line's `version`.

Funding belongs to the `LoanServicer` and requires the loan to still be `OPEN`, failing which it is rejected with `ERR_LOAN_NOT_OPEN` (HTTP 409). Funding cascades through three levels. On each line item, `funded_cents` is set to its `net_fundable_cents`. On each touched budget line, `disbursed_cents` grows by the line's `net_fundable_cents`, `retained_cents` grows by the line's `retainage_cents`, and `approved_unfunded_cents` shrinks by the line's `approved_cents`, with the budget line's `version` incrementing. On the loan, `principal_disbursed_cents`, `retained_cents`, and `cost_percent_complete` are recomputed and the loan's `version` increments by one. The draw's `funded_total_cents` becomes the sum of its items' `funded_cents`, and the draw settles into the terminal `FUNDED` state.

One post-approval line-item update remains. Once a draw is `APPROVED` or `FUNDED`, a `DrawProcessor` may mark a stored-materials line installed, supplying the `installed_date`; the line's `is_installed` becomes true and the date is recorded. The capability exists only for `STORED_MATERIALS` lines — invoking it on a `WORK_COMPLETED` line is rejected with `ERR_LINE_NOT_STORED_MATERIALS` (HTTP 422) — and only while the owning draw is `APPROVED` or `FUNDED`; a draw in any other state, or a repeat marking of an already-installed line, is rejected with `ERR_INVALID_STATE` (HTTP 409). Per §2.8 the state check runs first, so a `WORK_COMPLETED` line whose draw sits outside those states draws `ERR_INVALID_STATE`, not `ERR_LINE_NOT_STORED_MATERIALS`. Installation matters financially: an installed line's stored-materials advance cap rises to its full invoice value on subsequent approvals.

### 3.6. Retainage Release

Withheld retainage is released deliberately, never automatically. A release may be requested only once the loan's `milestone_reached` is true or an `ACCEPTED` inspection reporting exactly 100.00 exists for the loan; before either condition holds, the request is rejected with `ERR_RETAINAGE_NOT_RELEASABLE` (HTTP 409). The `Borrower` requests a release by naming the `loan_id`, the `budget_line_id` whose retained balance is being released — which must belong to that loan, or the request is rejected with `ERR_BUDGET_LINE_LOAN_MISMATCH` (HTTP 422) — a positive `amount_cents`, and a free-text `reason` such as milestone reduction or completion. The requested amount may not exceed the line's currently withheld `retained_cents`, checked at creation with `ERR_RELEASE_EXCEEDS_RETAINED` (HTTP 422). These creation gates run in the order presented here: releasability first, then the line-to-loan match, then the amount cap. A new release sits in `REQUESTED`; releases can be listed with optional `loan_id`, `budget_line_id`, and `status` filters.

Review belongs to the `CreditOfficer`, who passes a `decision` of `APPROVED` or `REJECTED`; a rejection takes a `reason`, recorded as the release's `review_reason`. Approving requires the loan to be `OPEN`, or the review is rejected with `ERR_LOAN_NOT_OPEN` (HTTP 409).

Payment belongs to the `LoanServicer` and re-verifies the money at the moment it moves: the loan must still be `OPEN` (`ERR_LOAN_NOT_OPEN`, HTTP 409), and the budget line's `retained_cents` must still be at least the release `amount_cents`, re-checked at payment with `ERR_RELEASE_EXCEEDS_RETAINED` (HTTP 422). Payment moves money within the line: `retained_cents` falls by the amount and `disbursed_cents` grows by the same amount, with the budget line's `version` incrementing. On the loan, `retained_cents` and `principal_disbursed_cents` are recomputed, `retainage_fully_released` is set true when the loan's withheld balance reaches zero after having once been positive, and the loan's `version` increments by one. The release settles `PAID`, terminal alongside `REJECTED`.

### 3.7. Budget Reallocation

Budgets move between lines through an audited request, drafted by a `LenderAdmin`. The request names the `loan_id`, the `from_budget_line_id` it draws from, the `to_budget_line_id` it feeds, a positive `amount_cents`, a free-text `justification`, and — per §2.7 — the `expected_loan_version` the drafter last observed; a stale value is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412). Both budget lines must belong to the named loan, or the request is rejected with `ERR_BUDGET_LINE_LOAN_MISMATCH` (HTTP 422). Source and target must differ — a request whose `from_budget_line_id` equals its `to_budget_line_id` is rejected with `ERR_REALLOCATION_SAME_LINE` (HTTP 422) — and the direction rule for contingency applies: the target line must not be a contingency line, or the request is rejected with `ERR_CONTINGENCY_DIRECTION_VIOLATION` (HTTP 422), since contingency may fund other lines but may never be topped up itself.

A drafted request starts `PENDING`, records the presented version in `created_loan_version` for audit, and — because drafting itself is a loan-mutating operation — increments the loan's `version` by one, which in turn invalidates any other drafter's stale `expected_loan_version`. Review belongs to the `CreditOfficer`, whose `decision` of `APPROVED` or `REJECTED` moves the request accordingly; a rejection takes a `reason`, recorded as the request's `review_reason`. A `LenderAdmin` may also cancel a request still `PENDING` or already `APPROVED`, moving it to `CANCELLED`.

Application belongs to the `LoanServicer`. The loan must be `OPEN`, or the apply is rejected with `ERR_LOAN_NOT_OPEN` (HTTP 409). The from-line has a floor that protects money already spoken for: applying is rejected with `ERR_REALLOCATION_BELOW_FLOOR` (HTTP 422) unless the source line's `revised_amount_cents` minus the reallocation `amount_cents` remains at least the sum of that line's `disbursed_cents`, `retained_cents`, and `approved_unfunded_cents`. A successful apply subtracts `amount_cents` from the source line's `revised_amount_cents` and adds it to the target line's `revised_amount_cents`, incrementing both budget lines' `version`, and increments the loan's `version` by one as the derived budget totals are re-evaluated. The request settles `APPLIED`.

Revised amounts are always derivable from history: a line's `revised_amount_cents` equals its `original_amount_cents` plus the `amount_cents` of every `APPLIED` reallocation targeting it, minus the `amount_cents` of every `APPLIED` reallocation sourced from it. Because a reallocation only moves budget and never creates or destroys it, the sum of `revised_amount_cents` across a loan's lines always equals the sum of `original_amount_cents`, no matter how many reallocations have been applied. Reallocation requests can be listed with optional `loan_id`, `from_budget_line_id`, `to_budget_line_id`, and `status` filters.

### 3.8. Interest Reserve Ledger and Accrual Runs

Every loan carries an append-only interest reserve ledger. Each entry bears a per-loan monotone `entry_index` starting at 1 — the `INITIAL_DEPOSIT` written at origination is index 1 — and an `entry_type` of `INITIAL_DEPOSIT`, `INTEREST_PAYMENT`, `CAPITALIZATION`, or `SWEEP`. The `amount_cents` is a signed reserve delta: positive for `INITIAL_DEPOSIT`, negative for `INTEREST_PAYMENT` (by the amount paid from the reserve), negative for `SWEEP`, and zero for `CAPITALIZATION`. Accrual-period fields are populated selectively: `period_start_date` and `period_end_date` are set only on `INTEREST_PAYMENT` and `CAPITALIZATION` entries and are null otherwise; `days_counted`, `interest_due_cents`, and `paid_from_reserve_cents` are null on `INITIAL_DEPOSIT` and `SWEEP` entries. An entry's `capitalized_cents` equals `interest_due_cents` minus `paid_from_reserve_cents` on an `INTEREST_PAYMENT`, mirrors that same shortfall on its paired `CAPITALIZATION`, and is zero otherwise. Every entry records `reserve_balance_after_cents`, the loan's reserve balance immediately after the entry posts. The ledger of a loan can be listed by any role, ordered by `entry_index` ascending.

Accruals are run by a `LoanServicer`, one run per request, over the half-open period from `period_start_date` to `period_end_date`; no billing-period validity rule applies to accruals — the supplied dates are used as given, and no analog of §3.3's `ERR_DRAW_PERIOD_INVALID` is enforced here. The evaluation order is pinned. First the accrual base is fixed as the loan's `principal_disbursed_cents` plus its `interest_capitalized_cents`, taken at the start of the run before anything this run capitalizes. Second, the days in the period are counted per the loan's `day_count_convention`. Third, `interest_due_cents` is the base multiplied by `interest_rate_annual_bps`, divided by ten thousand, multiplied by the day count, and divided by 360, rounded half up to whole cents. Fourth, `paid_from_reserve_cents` is the lesser of `interest_due_cents` and the reserve balance immediately before the run, and the reserve is drawn down by that amount. Fifth, the shortfall — `interest_due_cents` minus `paid_from_reserve_cents` — is added to `interest_capitalized_cents` whenever it is positive, joining the base of the next run. Finally, when a run leaves `interest_reserve_balance_cents` at zero, `interest_reserve_depleted` is set true. Each accrual increments the loan's `version`.

Every run writes exactly one `INTEREST_PAYMENT` entry — even when the computed `interest_due_cents` is zero — and additionally writes one `CAPITALIZATION` entry if and only if the shortfall was positive; the run returns the `INTEREST_PAYMENT` entry it created.

Day counting comes in the two variants selected at origination. Under `ACTUAL_360`, the count is the actual number of calendar days from `period_start_date` to `period_end_date`, the end date excluded, so a period spanning February counts 28 or 29 days for that month. Under `THIRTY_360`, every month counts thirty days: the start day-of-month is capped at 30; the end day-of-month is likewise capped at 30 — explicitly, an end day of 31 paired with a start day of 30 or 31 is counted as 30; and the count is 360 times the difference in years, plus 30 times the difference in months, plus the capped end day minus the capped start day. Identical period dates therefore produce a different `interest_due_cents` under the two conventions.

### 3.9. Conversion to Permanent Financing and Early Termination

When construction completes, the `Borrower` requests conversion to permanent financing by naming the `loan_id`. Only one conversion review may be open per loan: if a review in `REQUESTED` or `APPROVED` already exists, the new request is rejected with `ERR_CONVERSION_IN_PROGRESS` (HTTP 409). A fresh review starts `REQUESTED`, and reviews can be listed with optional `loan_id` and `status` filters.

Adjudication belongs to the `CreditOfficer`, whose `decision` of `DECLINED` takes a `reason`, recorded as the review's `decline_reason`, and closes the review as `DECLINED`. Approval is readiness-gated: the loan must be `OPEN`, or the review is rejected with `ERR_LOAN_NOT_OPEN` (HTTP 409); and three conditions must all hold, or approval is rejected with `ERR_CONVERSION_PRECONDITIONS_UNMET` (HTTP 409) — the loan's `retained_cents` is zero, no draw of the loan sits in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`, and at least one `ACCEPTED` inspection for the loan reports a `percent_complete_reported` of exactly 100.00.

Execution belongs to the `LoanServicer`, who supplies the permanent terms — `permanent_interest_rate_annual_bps` (a non-negative integer) and `permanent_term_months` (a positive integer) — on an `APPROVED` review, with the loan still `OPEN` at execution or the call is rejected with `ERR_LOAN_NOT_OPEN` (HTTP 409). The terms are recorded on the review, which settles `CONVERTED`, and copied onto the loan's own `permanent_interest_rate_annual_bps` and `permanent_term_months`. Executing conversion fires the loan's completion cascade: the loan moves from `OPEN` to `CONVERTED`; every `ACTIVE` budget line of the loan cascades to `CLOSED` with its `version` incrementing; any remaining interest reserve is swept back to the borrower by writing a `SWEEP` entry whose `amount_cents` is the negative of the remaining balance, growing the loan's `interest_reserve_swept_cents` by the swept amount and driving `interest_reserve_balance_cents` to zero — and when no reserve balance remains, no `SWEEP` entry is written and `interest_reserve_swept_cents` is unchanged, nor does a sweep ever set `interest_reserve_depleted`, a flag set only by accrual runs (§3.8); and the loan's `version` increments by one.

The other exit from `OPEN` is early termination, a `LenderAdmin` capability reserved for loans that never drew down. Termination requires zero activity: `principal_disbursed_cents` and `retained_cents` must both be zero; no draw may sit in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, or `APPROVED`; no reallocation request may sit in `PENDING` or `APPROVED`; no retainage release may sit in `REQUESTED` or `APPROVED`; and no conversion review may sit in `REQUESTED` or `APPROVED`. Any violation is rejected with `ERR_LOAN_HAS_ACTIVITY` (HTTP 409). A clean termination moves the loan to `TERMINATED` and fires the same cascade as conversion: budget lines `CLOSED` with version increments, a `SWEEP` entry returning any remaining reserve, and the loan's `version` incrementing by one. `CONVERTED` and `TERMINATED` are both terminal.

## 4. Endpoint Definitions

All paths below are rooted at the service base URL. Endpoints that create a new resource respond with HTTP 201; reads, state transitions, and all other modifications respond with HTTP 200. Request payloads, computed fields, side effects, and gating conditions are specified in §2 and §3 — this table is a navigational index, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /borrowers | Register a Borrower | LenderAdmin |
| GET | /borrowers/{id} | Get a Borrower | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /loans | Create a construction Loan (status OPEN); seeds the interest reserve | LenderAdmin |
| GET | /loans/{id} | Get a Loan with computed aggregates | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| GET | /loans | List Loans with optional filters and pagination | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /loans/{id}/terminate | Terminate an OPEN loan with zero activity | LenderAdmin |
| POST | /loans/{id}/interest-accruals | Run one interest accrual over [period_start_date, period_end_date) | LoanServicer |
| GET | /loans/{id}/interest-ledger | List InterestReserveEntry rows for a loan, ordered by entry_index ASC | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /budget-lines | Add a budget line item to a loan | LenderAdmin |
| GET | /budget-lines/{id} | Get a BudgetLine | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| GET | /budget-lines | List BudgetLines with optional filters | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /draws | Create a draw request in DRAFT | Borrower |
| GET | /draws/{id} | Get a DrawRequest | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| GET | /draws | List DrawRequests with optional filters | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /draws/{id}/submit | Submit a DRAFT draw, or resubmit a REVISION_REQUESTED draw | Borrower |
| POST | /draws/{id}/start-review | Move a SUBMITTED draw into UNDER_REVIEW | DrawProcessor |
| POST | /draws/{id}/request-revision | Send an UNDER_REVIEW draw back to the borrower for revision | DrawProcessor |
| POST | /draws/{id}/reject | Reject an UNDER_REVIEW draw (terminal) | DrawProcessor |
| POST | /draws/{id}/withdraw | Withdraw a DRAFT, SUBMITTED, or REVISION_REQUESTED draw | Borrower |
| POST | /draws/{id}/approve | Approve an UNDER_REVIEW draw; computes per-line approved/retainage/net amounts | CreditOfficer |
| POST | /draws/{id}/fund | Fund an APPROVED draw; cascades to line items, budget lines, and loan aggregates | LoanServicer |
| POST | /draw-line-items | Add a line item to a DRAFT or REVISION_REQUESTED draw | Borrower |
| GET | /draw-line-items/{id} | Get a DrawLineItem | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| GET | /draw-line-items | List DrawLineItems with optional filters | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /draw-line-items/{id}/mark-installed | Mark a STORED_MATERIALS line item installed (draw must be APPROVED or FUNDED) | DrawProcessor |
| POST | /draw-documents | Attach a document (lien waiver, invoice, insurance certificate) to a DRAFT or REVISION_REQUESTED draw | Borrower |
| GET | /draw-documents/{id} | Get a DrawDocument | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| GET | /draw-documents | List DrawDocuments with optional filters | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /draw-documents/{id}/review | Verify or reject a SUBMITTED document | DrawProcessor |
| POST | /inspections | Order an inspection (draw inspection when draw_id given, completion inspection when omitted) | DrawProcessor |
| GET | /inspections/{id} | Get an Inspection | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| GET | /inspections | List Inspections with optional filters | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /inspections/{id}/complete | Inspector reports results for an ORDERED inspection | Inspector |
| POST | /inspections/{id}/review | Accept or reject a COMPLETED inspection; acceptance updates loan progress fields | DrawProcessor |
| POST | /inspections/{id}/cancel | Cancel an ORDERED inspection | DrawProcessor |
| POST | /reallocation-requests | Request a budget reallocation between two lines (OCC-guarded by expected_loan_version) | LenderAdmin |
| GET | /reallocation-requests/{id} | Get a ReallocationRequest | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| GET | /reallocation-requests | List ReallocationRequests with optional filters | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /reallocation-requests/{id}/review | Approve or reject a PENDING reallocation | CreditOfficer |
| POST | /reallocation-requests/{id}/apply | Apply an APPROVED reallocation to the budget lines | LoanServicer |
| POST | /reallocation-requests/{id}/cancel | Cancel a PENDING or APPROVED reallocation | LenderAdmin |
| POST | /retainage-releases | Request release of withheld retainage on a budget line | Borrower |
| GET | /retainage-releases/{id} | Get a RetainageRelease | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| GET | /retainage-releases | List RetainageReleases with optional filters | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /retainage-releases/{id}/review | Approve or reject a REQUESTED retainage release | CreditOfficer |
| POST | /retainage-releases/{id}/pay | Pay an APPROVED release: transfers retained to disbursed on the line | LoanServicer |
| POST | /conversion-reviews | Request conversion of a construction loan to permanent financing | Borrower |
| GET | /conversion-reviews/{id} | Get a ConversionReview | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| GET | /conversion-reviews | List ConversionReviews with optional filters | LenderAdmin, DrawProcessor, CreditOfficer, LoanServicer, Inspector, Borrower |
| POST | /conversion-reviews/{id}/review | Approve (readiness-gated) or decline a REQUESTED conversion review | CreditOfficer |
| POST | /conversion-reviews/{id}/convert | Execute conversion to permanent financing for an APPROVED review | LoanServicer |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue is an index only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_LOAN_NOT_OPEN | 409 |
| ERR_STALE_LOAN_VERSION | 412 |
| ERR_LIEN_WAIVER_UNVERIFIED | 409 |
| ERR_DRAW_PERIOD_INVALID | 422 |
| ERR_DRAW_PERIOD_OVERLAP | 409 |
| ERR_INSPECTION_SCHEDULE_CONFLICT | 409 |
| ERR_INSPECTION_STALE | 409 |
| ERR_DRAW_HAS_NO_LINES | 422 |
| ERR_DUPLICATE_COST_CODE | 409 |
| ERR_STORED_MATERIALS_EVIDENCE_MISSING | 422 |
| ERR_REALLOCATION_SAME_LINE | 422 |
| ERR_CONTINGENCY_DIRECTION_VIOLATION | 422 |
| ERR_CONVERSION_IN_PROGRESS | 409 |
| ERR_LINE_NOT_STORED_MATERIALS | 422 |
| ERR_INSPECTION_REQUIRED | 409 |
| ERR_RETAINAGE_NOT_RELEASABLE | 409 |
| ERR_CONVERSION_PRECONDITIONS_UNMET | 409 |
| ERR_BUDGET_LINE_LOAN_MISMATCH | 422 |
| ERR_DRAW_LOAN_MISMATCH | 422 |
| ERR_COMMITMENT_EXCEEDED | 422 |
| ERR_INVOICE_COVERAGE_INSUFFICIENT | 422 |
| ERR_NOTHING_APPROVABLE | 422 |
| ERR_RELEASE_EXCEEDS_RETAINED | 422 |
| ERR_REALLOCATION_BELOW_FLOOR | 422 |
| ERR_LOAN_HAS_ACTIVITY | 409 |
