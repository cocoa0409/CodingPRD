# Cost-Seg & R&D Tax-Credit Service API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Cost-Segregation & R&D Tax-Credit Service API, a back-office platform that lets an engineering-and-tax firm run two distinct but structurally similar engagements: cost-segregation studies that reclassify a building's acquisition cost into shorter-lived depreciation classes, and research-and-development credit studies that quantify a taxpayer's qualified research expenditure. Both engagement types share a single lifecycle — a study is scoped, staffed with a preparing engineer, built up with detailed line-level work, submitted for an independent review, finalized, and delivered to the client's CPA — but they diverge sharply in the arithmetic that drives their tax benefit.

The platform's central discipline is that the same underlying inputs are evaluated under two competing methods so the firm can advise clients on the outcome of each. A cost-segregation study computes first-year depreciation both with and without bonus depreciation; an R&D study computes the credit under both the regular and the alternative-simplified-credit methods and reports the one the client elected. Downstream of those figures sit a contingent or fixed fee, an outstanding-fee ledger on the client, an audit-support workflow for studies later examined by the IRS, and a look-back amendment path that reopens a delivered study to file a §481(a) catch-up on an amended return.

Because the firm's engineers double as independent reviewers, the system enforces a strict segregation of duties: the person who prepared a study can never be the person who approves or finalizes it. This constraint, together with a real-money fee ledger and a set of statutory windows and rate thresholds keyed to the tax year, makes correctness — not just workflow — the product's defining requirement.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly four roles: `StudyManager`, `Engineer`, `Reviewer`, and `CPA`. A request whose `X-User-Role` header is missing or holds a value outside this set is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_UNAUTHORIZED`.

Two of the roles are backed by a persisted staff record and two are opaque. When `X-User-Role` is `Engineer`, `X-User-ID` is the `id` of the acting `Engineer` entity; ownership and segregation-of-duties checks compare that value against the study's `assigned_engineer_id`. When `X-User-Role` is `Reviewer`, `X-User-ID` is likewise the `id` of an `Engineer` entity (the same staff table backs both the preparer and the reviewer capacities); the finalizing or rejecting reviewer's `X-User-ID` is compared against the study's `assigned_engineer_id` to enforce segregation of duties, and on finalize it is stamped onto the study as `reviewer_engineer_id`. When `X-User-Role` is `StudyManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `CPA`, `X-User-ID` is likewise an opaque identifier for the client's accountant and is not matched against any stored entity.

Validation of every request proceeds in a fixed priority order, and the first failing check determines the error returned. Authentication (the header check above) is evaluated first, then authorization for the operation, then the existence of every resource named in the path and every required foreign-key id in the body (see §2.7), then whether the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`), then segregation of duties, then study-type applicability, then numeric-range checks on the body, then the temporal and overlap checks, then the fiscal checks, and finally the optimistic-concurrency check. Where a single operation is guarded by several of these, the earlier-priority failure is the one surfaced.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. Out-of-range or non-integer values are not rejected: a `limit` below 1 is clamped up to 1, a `limit` above 100 is clamped down to 100, and a `limit` that is not a valid integer falls back to the default of 10. The `offset` parameter skips a number of leading items and defaults to 0; a negative or non-integer `offset` falls back to 0. Unless a specific endpoint says otherwise, list results are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in this system carry a common set of server-managed fields. Every such resource has an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Resources that can change after creation additionally carry an `updated_at` timestamp, refreshed on every mutation, and a `version`, an integer that starts at 1 and increments by one on every mutation. `Client`, `Property`, `Study`, `AssetComponent`, `QreLineItem`, `Report`, `AuditSupportCase`, `AmendedReturn`, and `FeeInvoice` all carry the full set including `updated_at` and `version`.

The `Engineer` entity is the sole exception: it is an immutable staff record that carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because once created it is never modified.

### 2.5. Monetary Values, Rates, and Rounding

All monetary quantities are stored and returned as integer cents. Every rounding step in this document uses the round-half-up convention (a value exactly halfway between two whole cents rounds up to the larger). Rates and percentages supplied by clients — `marginal_tax_rate`, `qualified_percent`, `fixed_base_pct` — are decimals and are not pre-rounded; they enter calculations at full precision, and only the resulting cent amount is rounded.

One rounding rule is deliberately pinned and must not be simplified: when a study's first-year depreciation is summed across its components, each component's first-year figure is rounded to whole cents individually and only then are the rounded per-component figures added together. The system must never sum the raw un-rounded products and round once at the end; per-component rounding precedes summation.

### 2.6. The Logical Clock and Temporal Anchoring

The server keeps a logical clock rather than reading wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it, that default is the current time — the server never falls back to real wall-clock time. An administrative test-driving capability lets a `StudyManager` set the clock to a supplied instant via the `to_iso8601` field. The logical clock supplies the `issued_at` timestamp stamped when a report is issued, the `filed_at` timestamp stamped when an amended return is filed, and the calendar year used by the amended-return statute-of-limitations check described in §3.6.

### 2.7. Hierarchical Consistency, Cascades, and Nested Retrieval

Many operations mutate more than one resource. When an operation causes a secondary or downstream change — a report advancing when its study is finalized, a fee invoice being created, a client's fee ledger moving — each affected resource is independently mutated: its `updated_at` is refreshed and its `version` is incremented. These cascades are described in full in the workflow narratives of §3; the requirement here is that no cascade is silent, and every resource touched by an operation reflects the mutation in its own `updated_at` and `version`.

For requests that address a nested resource through a path containing more than one identifier, the identifiers are validated left to right. The first identifier in the path that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier or business rule is considered. The same left-to-right existence discipline applies to required foreign-key ids carried in a request body.

### 2.8. Segregation of Duties

The firm's engineers act both as preparers and as independent reviewers, so the system forbids anyone from reviewing their own preparation. Whenever a `Reviewer` rejects a study back for revision or finalizes it, the reviewer's own engineer id (their `X-User-ID`) must differ from the study's `assigned_engineer_id`. If they are the same person, the operation is rejected with `ERR_SOD_VIOLATION`. This is the only place two capacities of the same staff member collide, and the check guards exactly the reject and finalize operations.

### 2.9. Optimistic Concurrency Control

Creating an amended return against a look-back study is guarded by optimistic concurrency on the parent study. The create request must carry `expected_study_version`, holding the `version` of the target `Study` that the client last observed. If `expected_study_version` does not equal the study's current `version`, the create is rejected with `ERR_STALE_STUDY_VERSION` at HTTP 412. Because a delivered look-back study may legitimately have more than one amended return created against it over its life, a second create is not blocked by any state precondition; the stale-version check exists precisely because an earlier amended-return create has already advanced the study's `version` — so a writer holding the pre-advance version is working from a stale view and is turned away. A successful amended-return create itself advances the study's `version` by one. No other endpoint takes a version field.

### 2.10. Conserved Ledger Quantities

Two running totals are treated as conserved quantities that the system maintains by applying matched increments and decrements rather than by recomputation on read. A study's `total_allocated_cost_cents` is the sum of `allocated_cost_cents` over that study's asset components currently in status `ALLOCATED`: allocating a component adds its cost, and excluding a component that had been allocated subtracts the same cost as a compensating reversal. A client's `outstanding_fee_cents` is the sum of `amount_cents` over that client's fee invoices in status `ISSUED` (never those `PAID` or `VOID`): finalizing a study adds the new invoice's amount, while paying or voiding an invoice each subtracts that amount. These invariants must hold after every operation that touches them.

## 3. Business Logic & Workflows

### 3.1. Onboarding Clients and Registering Properties

Every engagement begins with a taxpayer. A `StudyManager` creates a `Client` by supplying its `legal_name`, its `entity_type` — one of `C_CORP`, `S_CORP`, `PARTNERSHIP`, or `INDIVIDUAL` — and its `marginal_tax_rate`, a decimal that must be at least 0 and at most 1; a rate outside that band is rejected with `ERR_INVALID_AMOUNT`. The marginal rate is the fraction of a depreciation deduction that converts into cash tax benefit, so it is retained for later benefit calculations. A new client starts in `status` `ONBOARDING` with `outstanding_fee_cents` at 0. A study cannot be opened for a client until a `StudyManager` activates it, moving `status` from `ONBOARDING` to `ACTIVE`; only then is the client eligible to own studies.

For cost-segregation work, a `StudyManager` registers the building as a `Property` owned by a client. A property is created with its owning `client_id`, an `address`, a `building_type` — one of `COMMERCIAL`, `RESIDENTIAL_RENTAL`, or `INDUSTRIAL` — a `purchase_price_cents` that must be strictly positive, a `land_value_cents` that must be at least 0 and strictly less than the purchase price, and a `placed_in_service_date` in ISO 8601 UTC. A purchase price that is not positive, or a land value outside its band, is rejected with `ERR_INVALID_AMOUNT`. On creation the system computes the property's `depreciable_basis_cents` as the purchase price minus the land value; this figure is the non-land cost available to depreciate and is the ceiling on how much component cost a study may reclassify. The calendar year of `placed_in_service_date` later selects the bonus-depreciation percentage. Properties can be listed and optionally filtered by `client_id`.

The firm's technical staff are recorded as `Engineer` entities, each created by a `StudyManager` with a `full_name` and an `email`. A single engineer record can act as a study's preparer under the `Engineer` role and as an independent approver under the `Reviewer` role, which is why segregation of duties (§2.8) must compare identities rather than roles.

### 3.2. Opening and Scoping a Study

A `StudyManager` opens a `Study` for an `ACTIVE` client by supplying the `client_id`, the `study_type` — either `COST_SEGREGATION` or `RD_CREDIT` — the `tax_year` the study applies to, and optionally `is_look_back`, which defaults to false and marks a study as eligible for a later amended-return catch-up. A study opened for a client that is not `ACTIVE` is rejected with `ERR_CLIENT_NOT_ACTIVE`. A new study begins in `status` `DRAFT`.

Scoping moves a study from `DRAFT` to `SCOPING` and records its commercial and methodological terms; only a `StudyManager` may scope. Every scope request sets the `fee_type`, either `FIXED` or `PERCENT`. When the fee is `FIXED`, the request must include `fee_fixed_amount_cents`; when the fee is `PERCENT`, it must include `fee_percent_bps`, a contingent fee expressed in basis points of the realized tax benefit. A scope request whose fee terms are incomplete — a fixed fee without its flat amount, or a percent fee without its basis points — is rejected with `ERR_MISSING_FEE_TERMS`. A percent fee whose `fee_percent_bps` exceeds 3,000 basis points (that is, thirty percent of the realized benefit) is rejected with `ERR_FEE_PERCENT_TOO_HIGH`.

Scoping a cost-segregation study additionally requires `property_id`, which must reference a `Property` owned by the study's client; a `property_id` that resolves to an existing property whose owner is a different client is treated as a missing resource for this study and rejected with `ERR_NOT_FOUND` (this ownership check is part of the existence stage and runs before the state check). It is rejected with `ERR_PROPERTY_STUDY_OVERLAP` if any other non-`CANCELLED` cost-segregation study already exists for that same property with the same `tax_year`. Scoping an R&D study instead requires the `credit_method`, either `REGULAR` or `ASC`, along with the parameters that method needs: the `fixed_base_pct` and `avg_annual_gross_receipts_cents` used by the regular method's base amount (both optional and treated as 0 when omitted), and the prior-year qualified research figures `prior_qre_year1_cents`, `prior_qre_year2_cents`, and `prior_qre_year3_cents` that form the ASC base period (each optional and defaulting to 0). An R&D study is rejected with `ERR_RD_BASE_PERIOD_OVERLAP` if any other non-`CANCELLED` R&D study for the same client has a base period, spanning the three tax years up to but not including its own `tax_year`, that overlaps this study's base period.

Once scoped, a `StudyManager` staffs the study by supplying `assigned_engineer_id`, which must reference an existing engineer; this records the preparer and advances the study from `SCOPING` to `ENGINEERING`. From `DRAFT`, `SCOPING`, `ENGINEERING`, or `IN_REVIEW`, a `StudyManager` may cancel a study, moving it to the terminal `CANCELLED` state.

### 3.3. Engineering the Cost-Segregation Allocation

While a cost-segregation study is in `ENGINEERING`, its assigned `Engineer` builds up the reclassification detail as `AssetComponent` records. Each component belongs to its parent study through a `study_id` and is created with a `component_name`, an `asset_class` — one of `FIVE_YEAR`, `SEVEN_YEAR`, `FIFTEEN_YEAR`, or `THIRTY_NINE_YEAR` — and an `allocated_cost_cents` that must be strictly positive, else `ERR_INVALID_AMOUNT`. Adding a component to a study whose `study_type` is not `COST_SEGREGATION` is rejected with `ERR_STUDY_TYPE_MISMATCH`. On creation the component starts in `status` `PROPOSED`, and its `recovery_period_years` is derived from the asset class: 5 years for `FIVE_YEAR`, 7 for `SEVEN_YEAR`, 15 for `FIFTEEN_YEAR`, and 39 for `THIRTY_NINE_YEAR`.

An engineer commits a proposed component into the study by allocating it, moving its `status` from `PROPOSED` to `ALLOCATED`. Allocation is permitted only while the parent study is in `ENGINEERING`, otherwise `ERR_INVALID_STATE`. Allocation must not push the study's running `total_allocated_cost_cents` above the property's `depreciable_basis_cents`; if the component's cost added to the current allocated total would exceed the basis, the request is rejected with `ERR_ALLOCATION_EXCEEDS_BASIS`. A successful allocation adds the component's `allocated_cost_cents` to the study's `total_allocated_cost_cents`. An engineer may instead exclude a component, moving it to the terminal `EXCLUDED` state; a component excluded from `PROPOSED` has no ledger effect, whereas a component excluded after it was `ALLOCATED` subtracts its `allocated_cost_cents` back out of the study's `total_allocated_cost_cents` as a compensating reversal. Unlike allocation, exclusion is not gated on the parent study's state — a component may be excluded (with its ledger reversal, if it was allocated) regardless of whether the parent study is still in `ENGINEERING`; the only state check is that a component already in the terminal `EXCLUDED` state cannot be excluded again, which is rejected with `ERR_INVALID_STATE`.

The study's depreciation figures are recomputed over its `ALLOCATED` components (components in `PROPOSED` or `EXCLUDED` are ignored) whenever the study is submitted for review and again whenever the study is read. Two variants are produced. Under the **without-bonus** baseline, each allocated component's first-year figure is its `allocated_cost_cents` multiplied by that class's first-year MACRS rate — 20 percent for `FIVE_YEAR`, 14.29 percent for `SEVEN_YEAR`, 5 percent for `FIFTEEN_YEAR`, and 2.564 percent for `THIRTY_NINE_YEAR` — rounded to whole cents; the rounded per-component figures are then summed to yield `first_year_depreciation_no_bonus_cents`.

Under the **with-bonus** variant, the bonus percentage is selected by the calendar year in which the property was placed in service: 100 percent for 2022, 80 percent for 2023, 60 percent for 2024, 40 percent for 2025, and 20 percent for 2026. Bonus depreciation applies only to the bonus-eligible classes — `FIVE_YEAR`, `SEVEN_YEAR`, and `FIFTEEN_YEAR`; `THIRTY_NINE_YEAR` is not bonus-eligible. For each bonus-eligible allocated component, the bonus amount is its `allocated_cost_cents` multiplied by the year's bonus percentage, rounded to whole cents; the remaining cost after subtracting that rounded bonus amount is multiplied by the class's first-year MACRS rate and rounded to whole cents; the component's first-year figure is the sum of those two rounded parts. For a `THIRTY_NINE_YEAR` component, the with-bonus first-year figure is simply its cost times the 2.564 percent MACRS rate, rounded to whole cents. The rounded per-component figures are summed to yield `first_year_depreciation_cents`. Per §2.5, each component is rounded before summation in both variants.

The study's `estimated_tax_benefit_cents` for a cost-segregation study is the with-bonus `first_year_depreciation_cents` multiplied by the client's `marginal_tax_rate`, rounded to whole cents. This realized-benefit figure is what a percent fee is later charged against.

### 3.4. Building the R&D Credit

While an R&D study is in `ENGINEERING`, its assigned `Engineer` records qualified research expenditure as `QreLineItem` records. Each line is created against the study with a `qre_category` — one of `WAGES`, `SUPPLIES`, or `CONTRACT_RESEARCH` — a `gross_amount_cents` that must be strictly positive, and a `qualified_percent`, a decimal strictly greater than 0 and at most 1. A non-positive gross amount or a qualified percent outside its band is rejected with `ERR_INVALID_AMOUNT`. Adding a line to a study whose `study_type` is not `RD_CREDIT` is rejected with `ERR_STUDY_TYPE_MISMATCH`. A new line starts in `status` `DRAFT`.

Qualifying a line moves its `status` from `DRAFT` to `QUALIFIED` and is permitted only while the parent study is in `ENGINEERING`, otherwise `ERR_INVALID_STATE`. Qualifying computes the line's `qualified_amount_cents` as its `gross_amount_cents` multiplied by an effective percentage, rounded to whole cents. The effective percentage equals the line's `qualified_percent` in the ordinary case; for a `CONTRACT_RESEARCH` line, the effective percentage is the smaller of `qualified_percent` and the contract-research cap of 0.65, so no more than sixty-five percent of a contract-research expense can ever count as qualified.

When the study is submitted for review, and again whenever it is read, the credit is recomputed over the study's `QUALIFIED` lines. The current-year qualified research total is the sum of `qualified_amount_cents` across those qualified lines (each already contract-capped at qualify time). Both credit methods are computed. Under the **ASC** method, the three-year average prior qualified research is the exact average of `prior_qre_year1_cents`, `prior_qre_year2_cents`, and `prior_qre_year3_cents` — their sum divided by three, without pre-rounding. When that average is greater than 0, `rd_credit_asc_cents` is 14 percent of the current-year total minus half of the average prior amount, rounded to whole cents, and floored at 0 so it is never negative. When the average prior amount is 0, the study is treated as a startup and `rd_credit_asc_cents` is 6 percent of the current-year total, rounded to whole cents.

Under the **regular** method, the base amount is the greater of two rounded figures: half of the current-year total, and the study's `fixed_base_pct` multiplied by its `avg_annual_gross_receipts_cents` — each rounded to whole cents. Then `rd_credit_regular_cents` is 20 percent of the current-year total minus that base amount, rounded to whole cents, and floored at 0. The study's `estimated_tax_benefit_cents` for an R&D study is `rd_credit_asc_cents` when the study's `credit_method` is `ASC` and `rd_credit_regular_cents` when it is `REGULAR`.

### 3.5. Review, Revision, and Finalization

When the detail work is complete, the assigned `Engineer` submits the study for review, advancing it from `ENGINEERING` to `IN_REVIEW`. Submission is refused unless the study has a non-empty benefit input set: a cost-segregation study needs at least one `ALLOCATED` component, failing which the submission is rejected with `ERR_NO_ALLOCATED_COMPONENTS`, and an R&D study needs at least one `QUALIFIED` line, failing which it is rejected with `ERR_NO_QUALIFIED_QRE`. Submitting recomputes every benefit field — `first_year_depreciation_cents`, `first_year_depreciation_no_bonus_cents`, `rd_credit_regular_cents`, `rd_credit_asc_cents`, and `estimated_tax_benefit_cents` — as described in §3.3 and §3.4.

Submission also drives the deliverable. If the study has no report yet, the system creates a `Report` for it in `status` `DRAFT` with `revision_count` at 0; its `report_type` is `COST_SEG_REPORT` for a cost-segregation study and `RD_CREDIT_REPORT` for an R&D study. If instead a report already exists and sits in `REVISION_REQUESTED`, the submission moves that report from `REVISION_REQUESTED` back to `DRAFT` and increments its `revision_count` by one — this is the revision loop.

A `Reviewer` acts on a study that is `IN_REVIEW`. Both reviewer actions enforce segregation of duties: the reviewer's engineer id must differ from `assigned_engineer_id`, else `ERR_SOD_VIOLATION` (§2.8). Rejecting sends the study back from `IN_REVIEW` to `ENGINEERING` for more work, may carry a free-text `review_note`, and moves the study's report from `DRAFT` to `REVISION_REQUESTED`; the study can then be resubmitted, which returns the report to `DRAFT` and bumps its `revision_count`, closing the `IN_REVIEW ↔ ENGINEERING` loop.

Finalizing advances the study from `IN_REVIEW` to `FINALIZED` and stamps the acting reviewer's engineer id onto the study as `reviewer_engineer_id`. Finalization then triggers a three-link cascade. First, the study's report moves from `DRAFT` to `ISSUED` and its `issued_at` is stamped from the logical clock. Second, the newly issued report triggers creation of a `FeeInvoice` against the study in `status` `ISSUED`, whose `fee_basis` copies the study's `fee_type` and whose `amount_cents` is computed by the study-fee rule: for a `FIXED` fee the amount is the study's `fee_fixed_amount_cents`, and for a `PERCENT` fee it is the study's `fee_percent_bps` divided by 10,000, multiplied by the study's `estimated_tax_benefit_cents`, rounded to whole cents. Third, the issued invoice's `amount_cents` is added to the owning client's `outstanding_fee_cents`.

### 3.6. Delivery, Audit Support, and Look-Back Amendments

Once a study is `FINALIZED`, the client's `CPA` accepts the deliverable, advancing the study from `FINALIZED` to `DELIVERED`. Delivery is the gateway to the two post-engagement workflows.

A `StudyManager` may open an `AuditSupportCase` on a study only after it is `DELIVERED`; opening a case on a study in any other state is rejected with `ERR_INVALID_STATE`. A case is created with an `irs_notice_ref` identifying the IRS notice or examination and starts in `status` `OPEN`. A `StudyManager` later resolves an open case by supplying a `resolution_note`, which is recorded as the case moves from `OPEN` to `RESOLVED`.

The look-back path lets the firm reclaim a benefit a client did not originally take. A `StudyManager` creates an `AmendedReturn` against a study only when that study is both flagged `is_look_back` and in `status` `DELIVERED`; otherwise the create is rejected with `ERR_INVALID_STATE`. The create request supplies the `amended_tax_year` and the `expected_study_version` that guards the operation under optimistic concurrency (§2.9): a mismatch with the study's current `version` yields `ERR_STALE_STUDY_VERSION` at HTTP 412, and a successful create advances the study's `version` by one. The new amended return starts in `status` `DRAFT`.

Filing an amended return moves it from `DRAFT` to `FILED` but is allowed only while the amendment window is open: the current logical-clock year must be at most the `amended_tax_year` plus the three-year amendment statute, and a filing attempted after that year has passed is rejected with `ERR_AMEND_WINDOW_EXPIRED`. Filing computes the §481(a) catch-up adjustment and records it on the return as `section_481a_cents`. That catch-up is the additional first-year deduction the cost-segregation study unlocks versus the as-filed treatment that would have depreciated the whole basis over 39 years: the as-filed first-year figure is the property's `depreciable_basis_cents` multiplied by the 39-year first-year MACRS rate of 2.564 percent, rounded to whole cents, and the catch-up is the study's `first_year_depreciation_cents` minus that as-filed figure. Filing then stamps `filed_at` from the logical clock, copies the computed catch-up onto the parent study's `section_481a_cents`, and supersedes the study's issued report, moving it from `ISSUED` to `SUPERSEDED`.

### 3.7. The Fee Ledger and Invoice Settlement

Each finalized study produces exactly one fee invoice, and the client's `outstanding_fee_cents` tracks the firm's open receivables against that client. A `StudyManager` settles an issued invoice by paying it, moving its `status` from `ISSUED` to `PAID` and subtracting its `amount_cents` from the client's `outstanding_fee_cents`. Alternatively, a `StudyManager` may void an issued invoice — for example when a finalize is later determined to have been in error — moving its `status` from `ISSUED` to `VOID` and likewise subtracting its `amount_cents` from the client's `outstanding_fee_cents` as a compensating reversal of the finalize cascade. Because only `ISSUED` invoices contribute to `outstanding_fee_cents`, both settlement paths leave the ledger consistent with the sum of the client's still-open invoices.

Reports and fee invoices for a study are both retrievable as lists. Studies themselves can be listed and optionally filtered by `client_id`, `property_id`, or `assigned_engineer_id`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that read a resource or drive a state transition on an existing resource return `200 OK`. Every request is subject to the authentication, authorization, existence, and state checks described in §2, and to the business rules scattered through §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Create a taxpayer client | StudyManager |
| GET | `/clients/{id}` | Get a client | StudyManager, Engineer, Reviewer, CPA |
| POST | `/clients/{id}/activate` | Activate an onboarding client | StudyManager |
| POST | `/properties` | Create a property | StudyManager |
| GET | `/properties/{id}` | Get a property | StudyManager, Engineer, Reviewer, CPA |
| GET | `/properties` | List properties, optionally filtered by client | StudyManager, Engineer, Reviewer, CPA |
| POST | `/engineers` | Create an engineer (backs Engineer and Reviewer roles) | StudyManager |
| GET | `/engineers/{id}` | Get an engineer | StudyManager, Engineer, Reviewer, CPA |
| POST | `/studies` | Create a study for an active client | StudyManager |
| GET | `/studies/{id}` | Get a study including computed benefit fields | StudyManager, Engineer, Reviewer, CPA |
| GET | `/studies` | List studies, optionally filtered | StudyManager, Engineer, Reviewer, CPA |
| POST | `/studies/{id}/scope` | Scope fee arrangement, property, or credit method | StudyManager |
| POST | `/studies/{id}/assign-engineer` | Assign the preparer engineer | StudyManager |
| POST | `/studies/{id}/submit-review` | Submit study for review; compute benefit, advance report | Engineer |
| POST | `/studies/{id}/reject` | Send study back for revision | Reviewer |
| POST | `/studies/{id}/finalize` | Finalize study; cascade report issue, fee, ledger | Reviewer |
| POST | `/studies/{id}/deliver` | Accept the deliverable | CPA |
| POST | `/studies/{id}/cancel` | Cancel a non-terminal study | StudyManager |
| POST | `/studies/{id}/asset-components` | Add a proposed cost-seg component | Engineer |
| GET | `/studies/{id}/asset-components` | List a study's asset components | StudyManager, Engineer, Reviewer, CPA |
| POST | `/asset-components/{id}/allocate` | Allocate a component into the study | Engineer |
| POST | `/asset-components/{id}/exclude` | Exclude a component | Engineer |
| POST | `/studies/{id}/qre-line-items` | Add a draft R&D expense line | Engineer |
| GET | `/studies/{id}/qre-line-items` | List a study's QRE line items | StudyManager, Engineer, Reviewer, CPA |
| POST | `/qre-line-items/{id}/qualify` | Qualify a QRE line | Engineer |
| GET | `/studies/{id}/reports` | List a study's reports | StudyManager, Engineer, Reviewer, CPA |
| POST | `/studies/{id}/audit-cases` | Open an audit-support case on a delivered study | StudyManager |
| GET | `/studies/{id}/audit-cases` | List a study's audit-support cases | StudyManager, Engineer, Reviewer, CPA |
| POST | `/audit-cases/{id}/resolve` | Resolve an open audit-support case | StudyManager |
| POST | `/studies/{id}/amended-returns` | Create an amended-return draft (OCC on study version) | StudyManager |
| GET | `/studies/{id}/amended-returns` | List a study's amended returns | StudyManager, Engineer, Reviewer, CPA |
| POST | `/amended-returns/{id}/file` | File the amended return; compute §481(a), supersede report | StudyManager |
| GET | `/studies/{id}/fee-invoices` | List a study's fee invoices | StudyManager, Engineer, Reviewer, CPA |
| POST | `/fee-invoices/{id}/pay` | Mark a fee invoice paid | StudyManager |
| POST | `/fee-invoices/{id}/void` | Void a fee invoice (compensating) | StudyManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StudyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_STUDY_TYPE_MISMATCH` | 409 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_PROPERTY_STUDY_OVERLAP` | 409 |
| `ERR_RD_BASE_PERIOD_OVERLAP` | 409 |
| `ERR_AMEND_WINDOW_EXPIRED` | 409 |
| `ERR_FEE_PERCENT_TOO_HIGH` | 422 |
| `ERR_ALLOCATION_EXCEEDS_BASIS` | 409 |
| `ERR_NO_ALLOCATED_COMPONENTS` | 409 |
| `ERR_NO_QUALIFIED_QRE` | 409 |
| `ERR_MISSING_FEE_TERMS` | 422 |
| `ERR_STALE_STUDY_VERSION` | 412 |
