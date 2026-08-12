# Manufacturer Patient Assistance Program API — Product Requirements Document

## 1. Introduction

A pharmaceutical manufacturer's patient assistance foundation operates a delicate financial trust: donated drug product and a fixed annual budget must reach uninsured and underinsured patients who qualify, while every dollar of commitment, every shipped unit, and every dispensed dose is auditable. This document specifies the Manufacturer Patient Assistance Program (PAP) API, the system of record for that trust. It governs the full arc of a patient's relationship with a program — eligibility screening with income annualization and Federal Poverty Level comparison, supporting-document review, application adjudication, approval-period enrollment, product shipment to a provider or directly to the patient, dispensing at the point of care, re-enrollment through a renewal cycle, and final budget reconciliation.

The system's design is dominated by three compliance pressures. First, duplication of benefits must be structurally impossible: a patient cannot simultaneously draw on a copay card and a PAP enrollment for the same product family, and cannot hold two overlapping enrollments. Second, fiscal exposure is forward-looking — the moment an application is approved, the full remaining benefit cap is committed against the program budget, and the program's posture tightens automatically as commitments accumulate, independent of whether any product has shipped. Third, segregation of duties is enforced at the identity level: the caseworker who denied an application may never decide the appeal of that denial. All date-sensitive behavior — screening validity, appeal windows, renewal windows, lot expiry, budget-period containment — reads a single logical clock rather than wall-clock time, so that program operations are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `ProgramAdministrator`, `CaseWorker`, `AppealsOfficer`, `Patient`, `Prescriber`, and `PharmacyDispenser`. A request missing either header, or carrying a role string outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient` entity; ownership checks on any resource that references a patient compare the resource's `patient_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403). When `X-User-Role` is `Prescriber`, `X-User-ID` is the `id` of the acting `Prescriber` entity; ownership checks compare the resource's `prescriber_id` field to `X-User-ID`, with violations rejected as `ERR_PRESCRIBER_MISMATCH` (HTTP 403) where a prescriber-specific rule exists and `ERR_OWNERSHIP_VIOLATION` elsewhere. When `X-User-Role` is `ProgramAdministrator`, `CaseWorker`, `AppealsOfficer`, or `PharmacyDispenser`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `reviewer_id` on an `Application`, `decided_by` on an `Appeal`, `reported_by` on a `ChangeOfCircumstance`, `dispenser_id` on a `DispenseEvent`, or `requested_by` on a `Shipment`) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields, with one deliberate exception:

- `id` (string): A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- `updated_at` (string): An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified. This field is refreshed upon any mutation of the resource.
- `version` (integer): A system-managed integer that starts at 1 on creation and increments by 1 with every modification to the resource. It is the pivot of optimistic concurrency control (§2.8).

The exception is the `DispenseEvent`, which is an immutable audit record: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it. Any cascade that touches another entity — for example, a shipment cancellation that releases lot reservations, or an approval that recomputes a program's posture — is itself a mutation of each affected entity and therefore refreshes that entity's `updated_at` and increments its `version`.

### 2.5. The Logical Clock and Date Windows

The system never consults wall-clock time. A single logical UTC clock governs every date-sensitive rule: screening validity, the appeal window, the renewal window, enrollment expiry, lot expiry, and budget-period containment. At server startup, before any adjustment, the logical clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `ProgramAdministrator`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. All date comparisons in this document are evaluated against the logical clock's current UTC date, referred to simply as "today."

All windows are closed intervals on dates. A screening remains usable while today is on or before the verified date plus the program's `screening_validity_days`. An appeal may be filed while today is on or before the application's `decided_at` date plus the program's `appeal_window_days`. A renewal application may be filed while today is on or after the enrollment's `end_date` minus the program's `renewal_window_days` and on or before the `end_date` itself. An enrollment expires when today is strictly after its `end_date`; an inventory lot expires when today is strictly after its `expiry_date`. Budget-period overlap between two periods of the same program is evaluated on closed intervals: two periods conflict unless the first period's end is strictly before the second period's start or the first period's start is strictly after the second period's end — so two periods that merely touch at a single shared calendar day are an overlap, while periods whose boundary dates are exactly one day apart (one ends the day before the other begins) are disjoint and allowed.

### 2.6. Money, Unit Costs, and Rounding Discipline

All monetary amounts are carried as integer cents (`*_cents` fields) to eliminate floating-point drift. Unit costs are the exception: they are exchanged as decimal-dollar strings with exactly four fraction digits (for example, `'100.0000'`), both as the program's reference `unit_cost_per_unit` — which exists only for benefit-cap computation — and as each inventory lot's acquisition `unit_cost_per_unit`, which drives shipment and dispense valuation.

Two rounding disciplines are pinned and must not be varied. First, wherever a division or multiplication yields a fractional cent or percentage, the result is rounded half up; percentages (the `fpl_percent` on a screening and both utilization percentages) are pinned at exactly two decimal places and expressed as decimal strings such as `'191.69'`, and threshold comparisons are always evaluated against the rounded value, never the unrounded one. Second, valuation is rounded per atomic unit and then summed — never summed and then rounded. A shipment's `value_cents` is the sum of its lines' individually rounded values; a shipment's `dispensed_value_cents` is the sum of its dispense events' individually rounded values. The choice is deliberate and observable: for a lot with unit cost `'12.3456'`, two dispense events of 3 units each yield 3704 cents plus 3704 cents, totalling 7408 cents, whereas valuing 6 units at once would round to 7407 cents. The per-event order is the pinned one, and the two values deliberately differ.

### 2.7. Validation Order

When a single request would fail several rules, the failure the client observes is determined by a fixed priority cascade; lower tiers are evaluated first, and HTTP status does not disambiguate within a tier. The tiers, in evaluation order, are:

1. **Authentication.** Presence of both headers and membership of the role in the declared set (`ERR_UNAUTHENTICATED`).
2. **Endpoint authorization.** The caller's role is listed for the endpoint (`ERR_FORBIDDEN`).
3. **Request schema.** Required fields present, types match, enum values valid, date ranges sane (`coverage_end` on or after `coverage_start`, `period_end` on or after `period_start`, `actual_on_hand` non-negative), conditional inputs present (the year-to-date fields exactly when the income basis calls for them, `prior_year_income_cents` exactly for the prior-year basis, `insurance_coverage_pct` exactly when the insurance status is underinsured, and the circumstance-specific `new_*` field matching the reported circumstance type), and the `Idempotency-Key` header present on shipment creation (`ERR_INVALID_REQUEST`).
4. **Entity-backed ownership.** `Patient` and `Prescriber` callers acting only on their own resources (`ERR_OWNERSHIP_VIOLATION` / `ERR_PRESCRIBER_MISMATCH`).
5. **Existence.** Every identifier in the path and body resolves to an existing resource — program, budget period, patient, prescriber, screening, document, application, appeal, enrollment, circumstance, copay card, lot, shipment, or reconciliation run (`ERR_NOT_FOUND`).
6. **Optimistic concurrency.** The expected-version field, where required, matches the parent entity's current `version` (`ERR_STALE_VERSION`) — checked immediately after existence and before all business rules.
7. **Source-state legality.** The entity is in the state the transition requires (the family of `ERR_*_NOT_*` state errors).
8. **Duplication and duty segregation.** Benefit-duplication and appeal-decider checks (`ERR_DUPLICATE_BENEFIT_ACTIVE`, `ERR_SEGREGATION_OF_DUTIES`).
9. **Temporal windows.** Screening freshness, renewal and appeal windows, period geometry (`ERR_SCREENING_STALE`, `ERR_OUTSIDE_RENEWAL_WINDOW`, `ERR_APPEAL_WINDOW_EXPIRED`, `ERR_BUDGET_PERIOD_OVERLAP`).
10. **Business constraints.** Uniqueness, completeness, quantity, destination, dispense-membership, and reconciliation coverage rules.
11. **Cross-reference agreement.** Screening-to-application (or screening-to-enrollment) patient and program agreement, and prescriber resolvability for provider-destination shipments (`ERR_SCREENING_MISMATCH`, `ERR_PRESCRIBER_REQUIRED`).
12. **Fiscal gates.** Posture and budget-sufficiency gates, in their own fixed internal order described in §3.3.

This ordering means, for example, that a stale-version conflict surfaces before any business rule is consulted, and that a missing `Idempotency-Key` header surfaces as a schema error before existence is even considered.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry optimistic-concurrency guards; no other endpoint takes a version field. First, updating a program's configuration requires the request to carry `expected_program_version` holding the client's last observed `version` of that program. If the value does not match the program's current `version` — because another accepted update has advanced it since the client last read the record — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the stale writer from applying a configuration delta computed against a superseded baseline. Second, creating a renewal application against an enrollment requires the request to carry `expected_enrollment_version` matching that enrollment's current `version`; renewal creation itself advances the enrollment's `version` by 1 (and supersedes older non-terminal renewal applications), so a writer holding a stale version is acting on an out-of-date view and is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). A successful renewal creation therefore invalidates any previously observed enrollment version.

### 2.9. Idempotent Shipment Creation

Shipment creation is the system's only idempotency-guarded write. Every creation request must supply an `Idempotency-Key` header (the key may alternatively be supplied as the body field `idempotency_key`, and is persisted on the resulting shipment under that name); a request without either is rejected with `ERR_INVALID_REQUEST`. When a key arrives that the server has seen before, the request bodies are compared. An identical body replays the original `201 Created` response verbatim with no side effects — no new shipment, no new reservation. The same key with a different body is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409).

### 2.10. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers — for example, a document uploaded beneath a screening, or a dispense event recorded beneath a shipment — the system validates the existence of each identifier in a sequential, left-to-right order. The request is rejected immediately with an `ERR_NOT_FOUND` (HTTP 404) corresponding to the first identifier in the path that does not resolve, before any deeper resource or business rule is consulted.

### 2.11. Program Posture and the Conserved Budget

Every program behaves as a conserved fiscal ledger. Its `total_allocated_cents` is the sum of `allocated_cents` over all of its budget periods regardless of period status; its `total_disbursed_cents` is the sum of `disbursed_cents` over all of its enrollments regardless of enrollment status; and its `total_committed_cents` is the sum, over enrollments in `ACTIVE` or `SUSPENDED` status only, of each enrollment's remaining commitment (its `benefit_cap_cents` minus its `disbursed_cents`). At all times, the allocated total equals committed plus disbursed plus unallocated available funds — commitment releases (on termination, expiry, or renewal closure) and disbursement confirmations (on delivery) move money between those buckets but never create or destroy it.

From these totals the system derives a utilization pair and a posture. The committed basis percentage is the sum of committed and disbursed cents, multiplied by 100, divided by `total_allocated_cents`, and rounded half up to two decimal places (`utilization_committed_basis_pct`); when no budget has been allocated at all, this percentage reads `'0.00'`. The disbursed basis percentage (`utilization_disbursed_basis_pct`) counts delivered actuals only, computed the same way from `total_disbursed_cents` alone. The two bases deliberately diverge: immediately after an approval with zero shipments, the committed basis jumps while the disbursed basis still reads `'0.00'`. The program's `posture` is derived from the committed basis with inclusive boundaries — a committed basis of exactly `'100.00'` or more yields `EXHAUSTED`; a committed basis of exactly `'90.00'` or more but under 100 yields `RESTRICTED`; anything lower yields `OPEN`. Posture is recomputed after every commitment or disbursement mutation (approval, renewal, termination, expiry, delivery, or appeal overturn) and again on every read of the program's utilization report.

## 3. Business Logic & Workflows

### 3.1. Programs and Budget Periods

Everything begins with a `ProgramAdministrator` standing up an **AssistanceProgram**. A program covers exactly one drug product, named by `product_name`, and is described to applicants by its display `name`. Its configuration fixes the reference `unit_cost_per_unit` (used only for benefit-cap computation), the hard unit caps `max_units_per_enrollment` and `max_units_per_shipment`, the money-axis cap `max_annual_benefit_cents`, the approval-period length `enrollment_duration_days`, the `screening_validity_days`, `appeal_window_days`, and `renewal_window_days` windows, the `lot_expiry_buffer_days` used by inventory allocation, and the `allow_patient_direct_shipment` flag that decides whether patient-home delivery is permitted at all. A newly created program starts with `posture` `OPEN`, all totals at zero, and `version` 1.

Configuration may later be updated by a `ProgramAdministrator` through the OCC-guarded update described in §2.8; each accepted update increments the program's `version` by 1. Updates apply prospectively only: enrollments already approved keep the caps and dates pinned at their approval, and changing `enrollment_duration_days` or `unit_cost_per_unit` never recomputes a live enrollment's `end_date` or `benefit_cap_cents`.

A program's budget is subdivided into **BudgetPeriod** records, each carrying its owning `program_id`, a closed date interval from `period_start` through `period_end` (with `period_end` on or after `period_start`), and an `allocated_cents` amount of zero or more. Creating a period whose closed interval intersects any existing period of the same program is rejected with `ERR_BUDGET_PERIOD_OVERLAP` — recalling from §2.5 that a single shared calendar day counts as overlap while strict one-day adjacency does not. Creating a period recomputes the program's `total_allocated_cents`. A period is born `OPEN` and may be closed exactly once by a `ProgramAdministrator`; closing a period that is not `OPEN` is rejected with `ERR_BUDGET_PERIOD_NOT_OPEN`, and closure is one-way. Each period accumulates its own `committed_cents` (the remaining commitment of enrollments anchored to it) and `disbursed_cents` (the delivered shipment value attributed to it).

### 3.2. Intake, Eligibility Screening, and Supporting Documents

Before anyone can apply, the people must exist. A `CaseWorker` or `ProgramAdministrator` registers a **Patient** with `full_name`, `date_of_birth`, and a two-letter `state_code`; the same roles register a **Prescriber** with `full_name`, `npi_number`, and `state_code`.

A patient then opens an **EligibilityScreening** — patients create screenings for themselves only, with the `patient_id` matching their identity and the `program_id` naming the program screened for. The screening captures `household_size` (at least 1), an `income_basis` of `YTD_ANNUALIZED` or `PRIOR_YEAR`, an `insurance_status` of `UNINSURED`, `UNDERINSURED`, `INSURED_COMMERCIAL`, `MEDICARE`, or `MEDICAID`, and the income evidence matching the basis: `ytd_income_cents` together with `ytd_months_elapsed` (1 through 12) when the basis is `YTD_ANNUALIZED`, or `prior_year_income_cents` when the basis is `PRIOR_YEAR`. A screening declaring `UNDERINSURED` must additionally supply `insurance_coverage_pct`, a decimal string between `'0.00'` and `'0.99'` such as `'0.60'`. Supplying a conditional field for the wrong basis or status, or omitting one that applies, fails schema validation as `ERR_INVALID_REQUEST`.

At creation the system computes and pins the screening's financial figures. The `annualized_income_cents` is derived by one of two variants: under `YTD_ANNUALIZED`, the year-to-date income is divided by the months elapsed, multiplied by 12, and rounded half up to whole cents — a projection that makes a mid-year raise produce a higher annualized figure than the prior-year tax return for the same patient; under `PRIOR_YEAR`, the filed prior-year total is used verbatim with no projection, so identical household data can be eligible under one basis and ineligible under the other. The Federal Poverty Level limit for the household, `fpl_limit_cents`, is 1,565,000 cents (the base figure for a household of one) plus 550,000 cents for each additional household member beyond the first. The `fpl_percent` is the annualized income multiplied by 100, divided by `fpl_limit_cents`, and rounded half up to two decimal places.

The screening's `eligibility_determination` is left undecided until a verification decision, but its rule is fixed at creation time and uses the rounded percentage: an `UNINSURED` patient is `ELIGIBLE` if and only if `fpl_percent` is at most 400.00, inclusive; an `UNDERINSURED` patient is `ELIGIBLE` if and only if `fpl_percent` is at most 500.00, inclusive, and `insurance_coverage_pct` is below `'1.00'`; and a patient with `INSURED_COMMERCIAL`, `MEDICARE`, or `MEDICAID` coverage is always `INELIGIBLE`, since those patients must use copay programs instead.

A screening is born in `DRAFT`. While it is `DRAFT` (and also while `SUBMITTED`), the patient may upload **ScreeningDocument** records beneath it, each with a `doc_type` of `PROOF_OF_INCOME`, `IDENTITY`, `INSURANCE_VERIFICATION`, or `OTHER` and an opaque `file_reference` storage handle; documents begin `PENDING`. Submission by the owning patient — identity enforced as `ERR_OWNERSHIP_VIOLATION` for anyone else — moves the screening `DRAFT → SUBMITTED`, but only when the screening is in fact `DRAFT` (otherwise `ERR_SCREENING_NOT_DRAFT`) and the required documentary evidence is present: at least one uploaded document of type `PROOF_OF_INCOME` and at least one of type `IDENTITY` in every case, plus at least one of type `INSURANCE_VERIFICATION` whenever the insurance status is anything other than `UNINSURED`. A submission lacking any required document type is rejected with `ERR_DOCUMENTS_INCOMPLETE`.

A `CaseWorker` then renders the verification decision. Verifying a screening requires it to be `SUBMITTED` (otherwise `ERR_SCREENING_NOT_SUBMITTED`), requires every uploaded document to be `ACCEPTED` (otherwise `ERR_DOCUMENTS_NOT_ACCEPTED` — documents themselves are reviewed individually from `PENDING` to `ACCEPTED` or `REJECTED` by a `CaseWorker`, with a non-`PENDING` document rejected as `ERR_DOCUMENT_NOT_PENDING` and an optional `review_note` stored when supplied), and requires the computed determination to be `ELIGIBLE` (otherwise `ERR_PATIENT_INELIGIBLE`, HTTP 422). Verification records `verified_at` from the logical clock and persists `eligibility_determination` as `ELIGIBLE`, moving the screening to `VERIFIED`. Rejection instead requires a `rejection_reason` (its absence fails as `ERR_INVALID_REQUEST`), stores that reason, and moves the screening to `REJECTED`.

Rejection is not the end: the owning patient may return a `REJECTED` screening to `DRAFT` through the revision loop — any other source state is rejected with `ERR_SCREENING_NOT_REJECTED`. Revision clears `verified_at` but retains previously uploaded documents with their statuses, letting the patient replace only what failed and resubmit. Finally, a `VERIFIED` screening does not stay fresh forever: the daily sweep (§3.8) turns it `STALE` once today passes the `verified_at` date plus `screening_validity_days`, and `STALE` is terminal.

### 3.3. Applications: From Submission to Approval

With a verified screening in hand, the patient files a fresh **Application** naming `patient_id`, `program_id`, and `screening_id`; renewal applications take a different path described in §3.5 and carry `renewal_of_enrollment_id`, which is null for fresh filings. Cross-references must agree exactly — the screening's own `patient_id` and `program_id` must equal the application's, else `ERR_SCREENING_MISMATCH` (HTTP 422) — and only one non-terminal fresh application may exist per patient and program, a second attempt drawing `ERR_APPLICATION_ALREADY_EXISTS`. The screening must be `VERIFIED` (`ERR_SCREENING_NOT_VERIFIED` otherwise) and still within its validity window (`ERR_SCREENING_STALE` otherwise). When several of these checks would fail at once on a fresh filing, the §2.7 cascade fixes the observed failure: the screening's `VERIFIED` state is evaluated first, then its validity window (`ERR_SCREENING_STALE`), then the per-patient-and-program uniqueness rule (`ERR_APPLICATION_ALREADY_EXISTS`), and the cross-reference agreement check (`ERR_SCREENING_MISMATCH`) last. A fresh application is born `SUBMITTED`.

Review is claimed, not assigned. A `CaseWorker` claims a `SUBMITTED` application — any other state draws `ERR_APPLICATION_NOT_SUBMITTED` — moving it to `UNDER_REVIEW` and recording their own `X-User-ID` as `reviewer_id`. From that moment the review belongs to that caseworker: only the recorded reviewer may request more information or render a decision, and anyone else is rejected with `ERR_REVIEWER_MISMATCH` (HTTP 403). Requesting information requires the application be `UNDER_REVIEW` (else `ERR_APPLICATION_NOT_UNDER_REVIEW`), stores the supplied `info_request_note`, and moves the application to `MORE_INFO_REQUESTED`. The owning patient answers by resubmitting — anyone else draws `ERR_OWNERSHIP_VIOLATION`, and a non-`MORE_INFO_REQUESTED` state draws `ERR_APPLICATION_NOT_AWAITING_INFO`; an optional `resubmission_note` may accompany the answer — which returns the application to `UNDER_REVIEW` with the same `reviewer_id` retained. This request-and-resubmit cycle may repeat indefinitely.

Approval is the system's fiscal point of no return, and its gates are evaluated in the fixed order given by §2.7: state and reviewer first, then screening status and freshness, then duplication-of-benefit checks (§3.6), then the renewal-source check where applicable, then the fiscal gates — and within the fiscal gates the order is pinned: posture `EXHAUSTED` blocks every approval with `ERR_PROGRAM_BUDGET_EXHAUSTED` (HTTP 402); posture `RESTRICTED` blocks fresh approvals with `ERR_PROGRAM_RESTRICTED` (HTTP 403) but renewals are exempt from this gate; an `OPEN` budget period containing today's date must exist, else `ERR_NO_OPEN_BUDGET_PERIOD`; and finally the sufficiency test — the program's `total_committed_cents` plus `total_disbursed_cents` plus the new enrollment's `benefit_cap_cents` must not exceed `total_allocated_cents`, else `ERR_INSUFFICIENT_PROGRAM_BUDGET` (HTTP 402). For a renewal, the prior enrollment's remaining commitment is released as part of the same approval before the sufficiency test is evaluated: a renewal replaces a commitment rather than adding to it.

The enrollment created by an approval is fully pinned at that moment. Its `patient_id`, `program_id`, and `application_id` come from the application; its `commitment_budget_period_id` is the containing `OPEN` period; its `start_date` is today for a fresh approval, or the day after the prior enrollment's `end_date` for a renewal; its `end_date` is the `start_date` plus `enrollment_duration_days` minus one day; and its `cap_units` is the program's `max_units_per_enrollment` at approval. The `benefit_cap_cents` is computed in a pinned order: the program's reference `unit_cost_per_unit` string is multiplied by 100 and rounded half up to whole unit cents; that unit figure is multiplied by `max_units_per_enrollment` to form the product axis; the base cap is the smaller of `max_annual_benefit_cents` and that product axis; and, when the backing screening's insurance status is `UNDERINSURED`, the base cap is multiplied by one minus the screening's `insurance_coverage_pct` and rounded half up to whole cents — otherwise the base cap stands unchanged. Unit conversion first, product axis second, the minimum with the annual cap third, underinsured scaling last; the order is pinned and must not be rearranged. The new enrollment starts `ACTIVE` with `disbursed_cents` zero and `remaining_units` equal to `cap_units`; the containing period's `committed_cents` increases by the benefit cap, program totals and posture are recomputed per §2.11, the application's `decided_at` is set from the logical clock, its `enrollment_id` is filled in, and — for renewals — the prior enrollment closes as described in §3.5.

Denial requires a `decision_reason` (absent, `ERR_INVALID_REQUEST`), records it, stamps `decided_at`, and lands the application in `DENIED`. Both approval and denial require the `UNDER_REVIEW` state with the matching reviewer; the `approved_via_appeal` flag stays false on a first-pass approval.

### 3.4. Appeals, Segregation of Duties, and Exceptions

A patient who believes a denial was wrong may file one **Appeal** against it, supplying non-empty `grounds`. The application must be `DENIED` — appealing anything else is rejected with `ERR_APPLICATION_NOT_DENIED` — only one `FILED` appeal may exist per application (`ERR_APPEAL_ALREADY_EXISTS`), and the filing must fall inside the appeal window of §2.5, else `ERR_APPEAL_WINDOW_EXPIRED`. An appeal is born `FILED`.

An `AppealsOfficer` decides the appeal, and the system enforces segregation of duties at the identity level: the deciding officer's `X-User-ID` must differ from the application's `reviewer_id`, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Deciding a non-`FILED` appeal is rejected with `ERR_APPEAL_NOT_FILED`. An `UPHELD` decision simply stores `decided_by`, `decided_at`, and the `decision_reason` and ends the matter.

An `OVERTURNED` decision triggers the deepest cascade in the system — appeal to application to enrollment to budget — and it is gated by exactly the approval precondition set of §3.3, re-evaluated fresh at appeal-decision time rather than inherited from the original review: no duplicate benefit (`ERR_DUPLICATE_BENEFIT_ACTIVE`), posture not `EXHAUSTED` (`ERR_PROGRAM_BUDGET_EXHAUSTED`), posture not `RESTRICTED` for a non-renewal (`ERR_PROGRAM_RESTRICTED`), an `OPEN` budget period containing today (`ERR_NO_OPEN_BUDGET_PERIOD`), and budget sufficiency (`ERR_INSUFFICIENT_PROGRAM_BUDGET`). Only when every gate passes does the application move `DENIED → APPROVED` with `approved_via_appeal` set to true, an enrollment created and budget committed exactly as in a first-pass approval, and posture recomputed.

### 3.5. Enrollments: Renewal, Suspension, Termination, and Change of Circumstance

An **Enrollment** is the living benefit: `ACTIVE`, holding a pinned `benefit_cap_cents` and `cap_units`, a `disbursed_cents` running total of delivered shipment value, and `remaining_units` — the `cap_units` minus the units sitting on shipments in `RESERVED`, `DISPATCHED`, `DELIVERED`, or `RETURNED` status (a `CANCELLED` shipment restores its units to the pool). Enrollments are readable by all roles and filterable by `patient_id`, `program_id`, `application_id`, `commitment_budget_period_id`, and `status`.

Renewal is how a benefit period chains into the next. Inside the renewal window of §2.5 — outside it the filing is rejected with `ERR_OUTSIDE_RENEWAL_WINDOW` — the patient files a renewal application against the enrollment, carrying a `screening_id` and the OCC field `expected_enrollment_version` described in §2.8. The referenced screening must belong to the enrollment's own patient and program (`ERR_SCREENING_MISMATCH` otherwise), must be `VERIFIED` (`ERR_SCREENING_NOT_VERIFIED`), and must still be inside its validity window (`ERR_SCREENING_STALE`). Creation stamps the new application's `renewal_of_enrollment_id` with the enrollment's `id`, supersedes every non-terminal renewal application of that same enrollment — any such application, whether `SUBMITTED`, `UNDER_REVIEW`, or `MORE_INFO_REQUESTED`, moves to `SUPERSEDED` by system action — and increments the enrollment's `version` by 1, which is precisely why the OCC guard exists. When a renewal is later approved (§3.3), the prior enrollment moves `ACTIVE → CLOSED_RENEWED`, its remaining commitment — `benefit_cap_cents` minus `disbursed_cents` — is released from both the program totals and its commitment period's `committed_cents`, and the successor enrollment's `start_date` is the prior `end_date` plus one day.

Circumstances change mid-enrollment, and the system tracks them explicitly. A `ChangeOfCircumstance` may be reported by the patient or a `CaseWorker` against an `ACTIVE` or `SUSPENDED` enrollment (anything else draws `ERR_ENROLLMENT_NOT_ACTIVE` at review time), with a `circumstance_type` of `INCOME_CHANGE`, `INSURANCE_CHANGE`, or `HOUSEHOLD_CHANGE`; the matching conditional field — `new_annual_income_cents`, `new_insurance_status`, or `new_household_size` respectively — must be present, and an optional `note` may accompany the report. The reporter's `X-User-ID` is recorded as `reported_by`, and the circumstance begins `REPORTED`. A `CaseWorker` review then resolves it: a `REPORTED` circumstance (else `ERR_CIRCUMSTANCE_NOT_REPORTED`) may be dismissed — landing in `DISMISSED` with no further effect — or applied, landing in `APPLIED`. An applied review with a suspend outcome cascades the enrollment `ACTIVE → SUSPENDED`; an applied review with a terminate outcome cascades it to `TERMINATED`; the circumstance records the `outcome` as `SUSPENDED` or `TERMINATED` accordingly and stores the caseworker's `review_note`.

Suspension is protective, not punitive. When an `ACTIVE` enrollment is suspended, its `status_reason` takes the circumstance's review note, and every one of its shipments still in `RESERVED` status is cancelled with full compensation — each affected lot's `quantity_reserved` decreases by the line quantity, its `quantity_on_hand` increases by the same amount, and the enrollment's `remaining_units` is restored. Critically, suspension does not release the budget commitment: the benefit stays reserved against the program, which is why suspended enrollments still count in the committed totals of §2.11. A `CaseWorker` may later reinstate a `SUSPENDED` enrollment (only `SUSPENDED`, else `ERR_ENROLLMENT_NOT_SUSPENDED`) by supplying a `screening_id` that references a screening of the enrollment's own patient and program (`ERR_SCREENING_MISMATCH` otherwise), currently `VERIFIED` (`ERR_SCREENING_NOT_VERIFIED`), and still within its validity window (`ERR_SCREENING_STALE`). Reinstatement carries no budget effect, because suspension never released anything.

Termination is final and comes in three flavors. A `CaseWorker` may terminate an `ACTIVE` or `SUSPENDED` enrollment directly, supplying a `termination_reason`; a circumstance review with a terminate outcome does the same by cascade; and the daily sweep expires enrollments (§3.8). Any action against a terminated, expired, or closed enrollment requiring an active one is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. Termination and expiry share their side effects: every `RESERVED` shipment is cancelled with lot-release and `remaining_units` restoration, and the remaining commitment — `benefit_cap_cents` minus `disbursed_cents` — is released from the program's `total_committed_cents` and the commitment period's `committed_cents`, with posture recomputed. From `SUSPENDED`, termination releases the commitment in the same way (there are no `RESERVED` shipments left to cancel, suspension having cleared them).

### 3.6. Copay Cards and Duplication-of-Benefits Prevention

The manufacturer's copay program and its patient assistance program cover the same product family, so the system treats them as mutually exclusive benefits for the same patient. A `CaseWorker` issues a **CopayCard** naming `patient_id` and `program_id` — the latter anchoring the duplication check — with a closed coverage interval from `coverage_start` through `coverage_end`. Two independent guards apply at issuance. First, no enrollment in `ACTIVE` or `SUSPENDED` status may overlap the requested coverage for that patient and program, else `ERR_DUPLICATE_BENEFIT_ACTIVE`. Second, no other copay card for the same patient and program may overlap the requested interval unless that other card is `TERMINATED`, else `ERR_COPAY_CARD_OVERLAP`.

The symmetric guard fires at PAP approval and appeal-overturn time: no copay card in `ACTIVE` status whose coverage interval intersects the new enrollment's `[start_date, end_date]` may exist for the patient and program, and no enrollment in `ACTIVE` or `SUSPENDED` status may exist for the pair other than the one named by `renewal_of_enrollment_id` — either violation is `ERR_DUPLICATE_BENEFIT_ACTIVE` (HTTP 409). A `SUSPENDED` copay card, notably, does not block approval; only `ACTIVE` cards do.

A card's own lifecycle is simple: born `ACTIVE`, a `CaseWorker` may suspend it (any other state drawing `ERR_COPAY_CARD_NOT_ACTIVE`) or terminate it from either `ACTIVE` or `SUSPENDED`, with an optional `reason` stored as `termination_reason` when supplied; any action against a `TERMINATED` card is rejected with `ERR_COPAY_CARD_TERMINATED`.

### 3.7. Inventory, FEFO Allocation, and the Shipment Lifecycle

Physical product enters the system as **InventoryLot** records received by a `ProgramAdministrator`: the owning `program_id`, a `lot_number` unique within its program (a repeat draws `ERR_LOT_NUMBER_DUPLICATE`), a `quantity_received` of at least 1, the acquisition `unit_cost_per_unit` as a four-fraction-digit decimal string, and an `expiry_date`. On receipt, `quantity_on_hand` equals `quantity_received`, and the other quantity counters — `quantity_reserved`, `quantity_shipped`, `quantity_dispensed`, `quantity_quarantined` — start at zero; the on-hand figure is always what remains after subtracting reserved, shipped, dispensed, and quarantined units from what was received. A lot is born `ACTIVE` and can leave that state three ways, all one-way: a `ProgramAdministrator` may quarantine it — moving it to `QUARANTINED` — with a `reason` stored as `status_reason` (only `ACTIVE`, else `ERR_LOT_NOT_ACTIVE`); the sweep expires it to `EXPIRED` once today passes its `expiry_date`; and a reconciliation variance (§3.8) places it `UNDER_INVESTIGATION`. Quarantined and under-investigation lots are excluded from allocation, while their existing `RESERVED` lines are left untouched; an expired lot's entire on-hand quantity moves to `quantity_quarantined` (on-hand drops to zero, product never restocked), and any lines still reserved against it remain reserved — the shipment will fail at dispatch until cancelled.

A **Shipment** is created by a `CaseWorker`, by the patient for their own `ACTIVE` enrollment, or by a `Prescriber`, and it is the idempotency-guarded endpoint of §2.9. The request names the `enrollment_id`, a `destination` of `PROVIDER` or `PATIENT`, and a `quantity_units` of at least 1 (zero or less fails as `ERR_INVALID_QUANTITY`). The destination rules are strict: `PATIENT` destination is rejected with `ERR_INVALID_DESTINATION` when the program's `allow_patient_direct_shipment` is false; `PROVIDER` destination without a `prescriber_id` — or a `prescriber_id` supplied alongside `PATIENT` destination — is rejected with `ERR_PRESCRIBER_REQUIRED`; a `Prescriber` caller may request only `PROVIDER` shipments addressed to themselves, otherwise `ERR_PRESCRIBER_MISMATCH`, and a `Patient` caller may ship only against their own enrollment, otherwise `ERR_OWNERSHIP_VIOLATION`. Shipments against a `SUSPENDED` enrollment are rejected with `ERR_ENROLLMENT_NOT_ACTIVE`. The quantity must satisfy both hard caps: it may not exceed the program's `max_units_per_shipment` nor the enrollment's `remaining_units`, with violations rejected as `ERR_SHIPMENT_QUANTITY_LIMIT_EXCEEDED` (HTTP 422).

Creation is also the moment of allocation. The system selects inventory by first-expiry-first-out: a lot is eligible when it belongs to the enrollment's program, is `ACTIVE`, has `quantity_on_hand` greater than zero, and has an `expiry_date` strictly later than today plus the program's `lot_expiry_buffer_days` — a lot expiring exactly on the buffered date is excluded. When no lot qualifies, creation is rejected with `ERR_NO_ELIGIBLE_INVENTORY`. Eligible lots are ranked by `expiry_date` ascending with ties broken by `created_at` ascending (never by id), and the allocation fills greedily from the earliest-expiry lot, overflowing to the next. If the summed on-hand across all candidates is below `quantity_units`, the entire request is rejected with `ERR_INSUFFICIENT_INVENTORY` — reservations are all-or-nothing, never partial. On success, one **ShipmentLine** is created per lot touched, recording the `shipment_id`, the allocated `lot_id`, the `quantity` drawn from that lot, and a per-line `value_cents` computed as the quantity multiplied by the lot's `unit_cost_per_unit` and by 100, rounded half up to whole cents; the shipment's `value_cents` is the sum of those individually rounded line values (the rounding order of §2.6 is pinned). Each line's lot has its `quantity_on_hand` moved into `quantity_reserved`, the enrollment's `remaining_units` decreases by `quantity_units`, the shipment is born `RESERVED`, and the creator's `X-User-ID` is stored as `requested_by`.

From `RESERVED`, a `CaseWorker` may dispatch the shipment — any other state draws `ERR_SHIPMENT_NOT_RESERVED` — but only while every line's lot is still `ACTIVE`, else `ERR_LOT_NOT_ACTIVE` (this is where an expired lot with lingering reservations blocks the pipeline). Dispatch moves each line's quantity on its lot from `quantity_reserved` to `quantity_shipped` and lands the shipment in `DISPATCHED`. Delivery confirmation moves the shipment `DISPATCHED → DELIVERED` — any other state draws `ERR_SHIPMENT_NOT_DISPATCHED` — and the confirming party depends on destination: a `CaseWorker` may always confirm; a `Prescriber` may confirm only a `PROVIDER`-destination shipment addressed to themselves (`ERR_PRESCRIBER_MISMATCH` otherwise); and a `Patient` may confirm only their own `PATIENT`-destination shipment (`ERR_OWNERSHIP_VIOLATION` otherwise). Delivery is the money movement: the enrollment's `disbursed_cents` increases by the shipment's `value_cents`, the commitment budget period's `disbursed_cents` increases by the same amount, and program totals and posture are recomputed — because committed totals are derived as cap minus disbursed over open enrollments, delivery shifts value from committed to disbursed with no separate release step.

Two exits avoid delivery. Cancelling a `RESERVED` shipment — by a `CaseWorker`, or by the system during an enrollment suspend, terminate, or expire cascade — requires the `RESERVED` state (`ERR_SHIPMENT_NOT_CANCELLABLE` otherwise) and fully compensates the reservation: per line, the lot's `quantity_reserved` returns to `quantity_on_hand`, and the enrollment's `remaining_units` is restored by `quantity_units`. An optional `reason` is stored as `status_reason`. Returning a `DISPATCHED` shipment, by contrast, is lossy: per line, the lot's `quantity_shipped` decreases and its `quantity_quarantined` increases by the line quantity — returned product may never be restocked — the enrollment's `remaining_units` is not restored (the units are consumed), and no money moves because the shipment never delivered. Its `status_reason` likewise stores the optional `reason`.

### 3.8. Dispensing, Reconciliation, and the Daily Sweep

Once a shipment is `DELIVERED` — dispensing against any other state is rejected with `ERR_SHIPMENT_NOT_DELIVERED` — a `PharmacyDispenser` records **DispenseEvent** records beneath it, one per lot actually dispensed. Each event names the `lot_id` and a `quantity` of at least 1, optionally carries a `dispensed_at` timestamp (defaulting to the logical clock's now), and records the caller's `X-User-ID` as `dispenser_id`. The lot must appear among the shipment's lines, else `ERR_LOT_NOT_IN_SHIPMENT`, and the cumulative dispensed quantity for the shipment-lot pair must never exceed the line's `quantity`, else `ERR_DISPENSE_EXCEEDS_RESERVED`. Each event's `value_cents` is computed as its quantity multiplied by the lot's `unit_cost_per_unit` and by 100, rounded half up to whole cents — per event, pinned, per §2.6 — and the shipment's `dispensed_value_cents` accumulates the sum of those per-event values. On the lot, the dispensed quantity moves from `quantity_shipped` into `quantity_dispensed`, and the line's `dispensed_quantity` grows accordingly. Dispense events are the system's immutable audit atoms: per §2.4 they carry no `updated_at` and no `version`. They are readable per shipment or per lot.

At period end, a `ProgramAdministrator` runs a **ReconciliationRun** against a `program_id` and a `budget_period_id` that must be `CLOSED` — reconciling an open period is rejected with `ERR_BUDGET_PERIOD_NOT_CLOSED`. The submitted `counts` — one entry per lot carrying `actual_on_hand` — must cover every `ACTIVE` lot of the program whose book units (on-hand plus reserved plus shipped) exceed zero, else `ERR_RECONCILIATION_COUNTS_MISSING` (HTTP 422), and every counted lot must belong to the run's program, else `ERR_RECONCILIATION_LOT_MISMATCH` (HTTP 422). For each counted lot the run computes `book_on_hand` from the lot's `quantity_on_hand`, a `variance_units` of actual minus book, and a `variance_value_cents` as the variance multiplied by the lot's `unit_cost_per_unit` and by 100, rounded half up per lot. The run's per-lot results are exposed as its `lines`, each entry bundling `lot_id`, `book_on_hand`, `actual_on_hand`, `variance_units`, and `variance_value_cents`. The run's outcome is computed atomically at creation: `CLEAN` if and only if every line's variance is zero, otherwise `VARIANCE_FLAGGED`, and every lot with a non-zero variance is moved to `UNDER_INVESTIGATION` and thereby excluded from further allocation. A run has no further transitions.

The final piece of machinery is the daily sweep, a `ProgramAdministrator`-only capability that accepts an optional `program_id` scope and applies three expiration passes in a pinned order. First, every `VERIFIED` screening whose validity date has passed — today strictly after the `verified_at` date plus `screening_validity_days` — becomes `STALE`. Second, every `ACTIVE` or `SUSPENDED` enrollment with today strictly after its `end_date` becomes `EXPIRED`, with the full cascade of §3.5: `RESERVED` shipments cancelled with lot release and unit restoration, remaining commitment released, posture recomputed. Third, every `ACTIVE` lot with today strictly after its `expiry_date` becomes `EXPIRED`, its on-hand quantity moving to quarantined. The sweep reports back the identifiers it touched as `staled_screening_ids`, `expired_enrollment_ids`, `expired_lot_ids`, and `cancelled_shipment_ids`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a program, budget period, patient, prescriber, screening, document, application, appeal, circumstance, copay card, lot, shipment, dispense event, or reconciliation run) return a `201 Created` status code. Operations that modify an existing resource — state transitions, decisions, configuration updates — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/pap/programs` | Create an AssistanceProgram (posture `OPEN`, totals 0, version 1) | ProgramAdministrator |
| GET    | `/pap/programs` | List programs | Any |
| GET    | `/pap/programs/{id}` | Get one program (computed posture/totals current as of read) | Any |
| PUT    | `/pap/programs/{id}` | Update program configuration (OCC-guarded; prospective only) | ProgramAdministrator |
| GET    | `/pap/programs/{id}/utilization` | Computed budget and utilization report (`allocated_cents`, `committed_cents`, `disbursed_cents`, `utilization_committed_basis_pct`, `utilization_disbursed_basis_pct`, `posture`, `active_enrollment_count`, `open_application_count`) | Any |
| POST   | `/pap/budget-periods` | Create a budget period (closed-interval overlap rejected) | ProgramAdministrator |
| GET    | `/pap/budget-periods` | List budget periods (filters: `program_id`, `status`) | Any |
| GET    | `/pap/budget-periods/{id}` | Get one budget period | Any |
| POST   | `/pap/budget-periods/{id}/close` | Close an `OPEN` budget period | ProgramAdministrator |
| POST   | `/pap/patients` | Register a patient | CaseWorker, ProgramAdministrator |
| GET    | `/pap/patients/{id}` | Get a patient | Any |
| POST   | `/pap/prescribers` | Register a prescriber | CaseWorker, ProgramAdministrator |
| GET    | `/pap/prescribers/{id}` | Get a prescriber | Any |
| POST   | `/pap/screenings` | Create an eligibility screening in `DRAFT` (income/FPL computed immediately) | Patient |
| GET    | `/pap/screenings` | List screenings (filters: `patient_id`, `program_id`, `status`) | Any |
| GET    | `/pap/screenings/{id}` | Get a screening | Any |
| POST   | `/pap/screenings/{id}/submit` | Submit a `DRAFT` screening (required doc types uploaded) | Patient |
| POST   | `/pap/screenings/{id}/decision` | Caseworker verification decision (`decision`, optional `rejection_reason`) | CaseWorker |
| POST   | `/pap/screenings/{id}/revise` | Return a `REJECTED` screening to `DRAFT` (documents retained) | Patient |
| POST   | `/pap/screenings/{id}/documents` | Upload a supporting document (allowed while `DRAFT` or `SUBMITTED`) | Patient |
| GET    | `/pap/screenings/{id}/documents` | List a screening's documents | Any |
| POST   | `/pap/documents/{id}/review` | Accept or reject a `PENDING` document (`decision`, optional `review_note`) | CaseWorker |
| POST   | `/pap/applications` | Create a fresh (non-renewal) application in `SUBMITTED` | Patient |
| GET    | `/pap/applications` | List applications (filters: `patient_id`, `program_id`, `screening_id`, `enrollment_id`, `renewal_of_enrollment_id`, `status`) | Any |
| GET    | `/pap/applications/{id}` | Get an application | Any |
| POST   | `/pap/applications/{id}/claim` | Caseworker claims a `SUBMITTED` application | CaseWorker |
| POST   | `/pap/applications/{id}/request-info` | Reviewer requests more information (`info_request_note`) | CaseWorker |
| POST   | `/pap/applications/{id}/resubmit` | Patient answers the info request (optional `resubmission_note`; reviewer retained) | Patient |
| POST   | `/pap/applications/{id}/decision` | Reviewer approves or denies (`decision`, optional `decision_reason`); approval creates the enrollment and commits budget | CaseWorker |
| POST   | `/pap/applications/{id}/appeals` | Patient files an appeal of a `DENIED` application within the appeal window (`grounds`) | Patient |
| GET    | `/pap/appeals` | List appeals (filters: `application_id`, `status`) | Any |
| GET    | `/pap/appeals/{id}` | Get an appeal | Any |
| POST   | `/pap/appeals/{id}/decision` | AppealsOfficer upholds or overturns (`decision`, optional `decision_reason`); overturn re-runs approval gates and creates the enrollment | AppealsOfficer |
| GET    | `/pap/enrollments` | List enrollments (filters: `patient_id`, `program_id`, `application_id`, `commitment_budget_period_id`, `status`) | Any |
| GET    | `/pap/enrollments/{id}` | Get an enrollment | Any |
| POST   | `/pap/enrollments/{id}/renewal-applications` | Patient files a renewal application inside the renewal window (`screening_id`, `expected_enrollment_version`); supersedes prior non-terminal renewals; OCC-guarded | Patient |
| POST   | `/pap/enrollments/{id}/terminate` | Terminate an `ACTIVE` or `SUSPENDED` enrollment (`termination_reason`); releases commitment, cancels `RESERVED` shipments | CaseWorker |
| POST   | `/pap/enrollments/{id}/reinstate` | Reinstate a `SUSPENDED` enrollment with a fresh `VERIFIED` screening (`screening_id`) | CaseWorker |
| POST   | `/pap/enrollments/{id}/circumstances` | Report a change of circumstance on an `ACTIVE` or `SUSPENDED` enrollment | Patient, CaseWorker |
| GET    | `/pap/circumstances` | List circumstances (filters: `enrollment_id`, `status`) | Any |
| GET    | `/pap/circumstances/{id}` | Get a circumstance | Any |
| POST   | `/pap/circumstances/{id}/review` | Caseworker applies (suspend/terminate) or dismisses (`decision`, optional `review_note`) | CaseWorker |
| POST   | `/pap/copay-cards` | Issue a copay card (duplication-of-benefits and card-overlap checks) | CaseWorker |
| GET    | `/pap/copay-cards` | List copay cards (filters: `patient_id`, `program_id`, `status`) | Any |
| GET    | `/pap/copay-cards/{id}` | Get a copay card | Any |
| POST   | `/pap/copay-cards/{id}/suspend` | Suspend an `ACTIVE` copay card (a suspended card does not block PAP approval) | CaseWorker |
| POST   | `/pap/copay-cards/{id}/terminate` | Terminate an `ACTIVE` or `SUSPENDED` copay card (optional `reason`) | CaseWorker |
| POST   | `/pap/inventory-lots` | Receive an inventory lot | ProgramAdministrator |
| GET    | `/pap/inventory-lots` | List lots (filters: `program_id`, `status`) | Any |
| GET    | `/pap/inventory-lots/{id}` | Get a lot | Any |
| POST   | `/pap/inventory-lots/{id}/quarantine` | Quarantine an `ACTIVE` lot (`reason`; excluded from FEFO, reservations unaffected) | ProgramAdministrator |
| GET    | `/pap/inventory-lots/{id}/lines` | List shipment lines allocated from this lot | Any |
| GET    | `/pap/inventory-lots/{id}/dispense-events` | List dispense events recorded against this lot | Any |
| POST   | `/pap/shipments` | Request a shipment; reserves inventory via FEFO at creation; `Idempotency-Key` header required | CaseWorker, Patient, Prescriber |
| GET    | `/pap/shipments` | List shipments (filters: `enrollment_id`, `prescriber_id`, `status`) | Any |
| GET    | `/pap/shipments/{id}` | Get a shipment | Any |
| GET    | `/pap/shipments/{id}/lines` | List a shipment's allocation lines | Any |
| POST   | `/pap/shipments/{id}/dispatch` | Dispatch a `RESERVED` shipment (all line lots must be `ACTIVE`) | CaseWorker |
| POST   | `/pap/shipments/{id}/deliver` | Confirm delivery; moves value from committed to disbursed | CaseWorker, Prescriber, Patient |
| POST   | `/pap/shipments/{id}/cancel` | Cancel a `RESERVED` shipment (optional `reason`; compensates the reservation) | CaseWorker |
| POST   | `/pap/shipments/{id}/return` | Return a `DISPATCHED` shipment (optional `reason`; units quarantined, not restocked) | CaseWorker |
| POST   | `/pap/shipments/{id}/dispense-events` | Record dispensing of a `DELIVERED` shipment, per lot (`lot_id`, `quantity`, optional `dispensed_at`) | PharmacyDispenser |
| GET    | `/pap/shipments/{id}/dispense-events` | List dispense events of a shipment | Any |
| POST   | `/pap/reconciliation-runs` | Reconcile physical `counts` against book inventory for a `CLOSED` budget period | ProgramAdministrator |
| GET    | `/pap/reconciliation-runs` | List reconciliation runs (filters: `program_id`, `budget_period_id`, `status`) | Any |
| GET    | `/pap/reconciliation-runs/{id}` | Get a reconciliation run with per-lot lines | Any |
| POST   | `/_clock/set_current_utc` | Set the logical clock (`to_iso8601`); startup default `2026-05-01T00:00:00Z` | ProgramAdministrator |
| POST   | `/_system/run-daily-sweep` | Run the daily sweep in pinned order (screenings, then enrollments, then lots); optional `program_id` scope | ProgramAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
| `ERR_SCREENING_NOT_DRAFT` | 409 Conflict |
| `ERR_SCREENING_NOT_SUBMITTED` | 409 Conflict |
| `ERR_SCREENING_NOT_REJECTED` | 409 Conflict |
| `ERR_SCREENING_NOT_VERIFIED` | 409 Conflict |
| `ERR_SCREENING_STALE` | 409 Conflict |
| `ERR_SCREENING_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DOCUMENTS_INCOMPLETE` | 409 Conflict |
| `ERR_DOCUMENTS_NOT_ACCEPTED` | 409 Conflict |
| `ERR_DOCUMENT_NOT_PENDING` | 409 Conflict |
| `ERR_PATIENT_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_APPLICATION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_APPLICATION_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_APPLICATION_NOT_AWAITING_INFO` | 409 Conflict |
| `ERR_REVIEWER_MISMATCH` | 403 Forbidden |
| `ERR_APPLICATION_NOT_DENIED` | 409 Conflict |
| `ERR_APPEAL_ALREADY_EXISTS` | 409 Conflict |
| `ERR_APPEAL_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_APPEAL_NOT_FILED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DUPLICATE_BENEFIT_ACTIVE` | 409 Conflict |
| `ERR_COPAY_CARD_OVERLAP` | 409 Conflict |
| `ERR_COPAY_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_COPAY_CARD_TERMINATED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_OUTSIDE_RENEWAL_WINDOW` | 409 Conflict |
| `ERR_CIRCUMSTANCE_NOT_REPORTED` | 409 Conflict |
| `ERR_PROGRAM_BUDGET_EXHAUSTED` | 402 Payment Required |
| `ERR_PROGRAM_RESTRICTED` | 403 Forbidden |
| `ERR_INSUFFICIENT_PROGRAM_BUDGET` | 402 Payment Required |
| `ERR_NO_OPEN_BUDGET_PERIOD` | 409 Conflict |
| `ERR_BUDGET_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_BUDGET_PERIOD_NOT_OPEN` | 409 Conflict |
| `ERR_BUDGET_PERIOD_NOT_CLOSED` | 409 Conflict |
| `ERR_INVALID_QUANTITY` | 400 Bad Request |
| `ERR_SHIPMENT_QUANTITY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INVALID_DESTINATION` | 400 Bad Request |
| `ERR_PRESCRIBER_REQUIRED` | 400 Bad Request |
| `ERR_PRESCRIBER_MISMATCH` | 403 Forbidden |
| `ERR_NO_ELIGIBLE_INVENTORY` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_LOT_NUMBER_DUPLICATE` | 409 Conflict |
| `ERR_LOT_NOT_ACTIVE` | 409 Conflict |
| `ERR_LOT_NOT_IN_SHIPMENT` | 409 Conflict |
| `ERR_DISPENSE_EXCEEDS_RESERVED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_RESERVED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_DISPATCHED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_DELIVERED` | 409 Conflict |
| `ERR_RECONCILIATION_COUNTS_MISSING` | 422 Unprocessable Entity |
| `ERR_RECONCILIATION_LOT_MISMATCH` | 422 Unprocessable Entity |
