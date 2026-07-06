# Weatherization API — Product Requirements Document

## 1. Introduction

Residential weatherization programs sit at the intersection of building science, public subsidy, and household finance. A single home passes through a field energy audit with blower-door and duct-leakage diagnostics, a recommended scope of insulation and air-sealing measures, crew scheduling and installation, utility rebates and the federal 25C tax credit, low-income Weatherization Assistance Program (WAP) eligibility screening, an independent post-test verification, and optional financing of whatever balance the household still owes. Each of these stages is owned by a different actor and governed by its own rules, yet all of them must reconcile against one job's money and energy ledgers in real time.

This document specifies the Weatherization API, the backend that orchestrates that entire lifecycle. It defines how program administrators open and fund jobs, how auditors document a home's leakage and propose measures, how installers record completed work, how utility rebates and tax credits are computed and reconciled against a budget cap, and how independent verification either finalizes a job or unwinds its financial commitments. The system is built on immediate consistency: every rebate approval, every installed measure, and every cancellation is expected to leave the job's derived totals — estimated cost, approved rebates, tax credit, out-of-pocket balance, and both estimated and verified energy savings — in a correct, immediately readable state. The remainder of this document establishes the global contracts that all endpoints share (Section 2), the domain workflows and their scattered business rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that every endpoint honors regardless of the domain workflow it serves.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request that omits `X-User-Role` or presents a value that is not one of the recognized roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles: `ProgramAdmin`, `Auditor`, `Installer`, and `Homeowner`.

- A `ProgramAdmin` is the weatherization program operator. This role owns dwellings, jobs, crews and their scheduling, scope-item decisions, the full rebate lifecycle, and job cancellation.
- An `Auditor` is the field energy auditor. This role opens audits, records blower-door and duct-leakage tests, proposes scope measures, and performs post-test verification.
- An `Installer` is the install crew lead who records completed measures.
- A `Homeowner` is the household applicant, who applies for WAP and responds to financing offers.

All four roles carry an **opaque** identity. When `X-User-Role` is any of `ProgramAdmin`, `Auditor`, `Installer`, or `Homeowner`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared against any resource's `id`. The server may nonetheless record the acting user's `X-User-ID` on the resources it creates: when an `Auditor` opens an audit, their `X-User-ID` is stored as the audit's `auditor_user_id`; when an `Auditor` records a diagnostic test, their `X-User-ID` is stored as the test's `tester_user_id`. The `tester_user_id` recorded on a baseline blower-door test is the sole basis for the segregation-of-duties check enforced at verification time (Section 3.8); it is compared only against the `X-User-ID` of the auditor attempting verification, never against any entity identifier.

Two operations are shared across roles: submitting a WAP application is permitted to both `ProgramAdmin` and `Homeowner`, and offering a financing plan is permitted to both `ProgramAdmin` and `Homeowner`. All read (GET) endpoints are available to every recognized role. Every remaining write operation is exclusive to the single role named in Section 4.

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

### 2.3. Pagination and List Ordering

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must fall between a minimum of 1 and a maximum of 100 inclusive. The `offset` parameter is the number of items to skip; when omitted it defaults to 0, and it must be at least 0. A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 400).

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. Each list response includes `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object, where `total_count` reflects the number of matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Resource Identity, Timestamps, and Versioning

Most resources in the system are mutable and carry a common set of system-managed fields:

- `id` — a server-minted UUID with no type prefix, unique across the system.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 when the resource is created and increments by 1 on each subsequent mutation of that resource. It is the basis for optimistic concurrency control (Section 2.9).

Dwellings, WAP applications, jobs, energy audits, scope items, crews, crew assignments, rebate claims, and financing plans all carry the full set above. **Diagnostic tests are the sole exception:** a diagnostic test is an immutable, append-only measurement event. It carries only `id` and `created_at`; it has no `updated_at` and no `version` field, because it is never modified after creation.

A job's own `version` deserves special attention because it is the parent version consulted by financing-plan optimistic concurrency. The operations that advance a job's `version` are: completing its install dimension, running verification, cancelling it, offering a financing plan against it, and the crew assignment that first moves its install dimension from `PLANNED` to `SCHEDULED`. Each such advance also refreshes the job's `updated_at`.

### 2.5. Request Validation Pipeline and Precedence

When more than one rule could reject a request, the system evaluates checks in a fixed precedence so that the reported `error_id` is deterministic. Lower-numbered checks take priority over higher-numbered ones:

1. **Authentication** — `X-User-Role` must be present and a recognized role, or the request fails with `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Authorization** — the role must be permitted for the operation per Section 2.1 and Section 4, or the request fails with `ERR_FORBIDDEN` (403). Applies to every endpoint.
3. **Body well-formedness** — required fields must be present, enums must hold legal values, numeric fields must be within their declared ranges, and pagination parameters must be in range; otherwise `ERR_VALIDATION` (400). Applies to every endpoint.
4. **Path existence** — every identifier in the URL path must resolve to an existing resource, or `ERR_NOT_FOUND` (404). Applies to every endpoint that addresses a resource by path.
5. **Foreign-key existence** — every foreign key carried in the request body (for example `dwelling_id`, `job_id`, `crew_id`, `audit_id`, `scope_item_id`, `baseline_test_id`, or `post_test_id`) must resolve to an existing resource, or `ERR_NOT_FOUND` (404). Applies to all create endpoints and to verification.
6. **Date-window validity** — a crew assignment's `scheduled_end_date` must be strictly after its `scheduled_start_date`, or `ERR_INVALID_DATE_WINDOW` (422). Applies to crew-assignment creation.
7. **State precondition** — the target resource must be in the state its transition requires, or `ERR_INVALID_STATE` (409). Applies to every state-transition operation.
8. **Cross-entity state precondition** — a referenced sibling resource must be in the required state; the exact code varies by operation: `ERR_AUDIT_NOT_APPROVED`, `ERR_SCOPE_NOT_INSTALLED`, `ERR_NOT_WAP_ELIGIBLE`, or `ERR_BASELINE_TEST_REQUIRED`, each HTTP 409. Applies to scope-item decisions, rebate-claim submission, job creation, and diagnostic-test creation.
9. **Segregation of duties** — at verification, the acting auditor's `X-User-ID` must not equal the baseline blower-door test's `tester_user_id`, or `ERR_SOD_VIOLATION` (409). Applies to verification.
10. **Structural constraints** — the operation's structural preconditions must hold; the code varies: `ERR_SCOPE_INCOMPLETE`, `ERR_CREW_DOUBLE_BOOKED`, `ERR_DWELLING_WINDOW_CONFLICT`, or `ERR_CREW_CAPACITY_EXCEEDED`, each HTTP 409. Applies to verification, install completion, and crew-assignment creation.
11. **Rebate budget** — approving a rebate must not push the job's approved rebate total above its cap, or `ERR_REBATE_BUDGET_EXCEEDED` (409). Applies to rebate-claim approval.
12. **Optimistic concurrency** — `expected_job_version` must equal the job's current `version`, or `ERR_STALE_VERSION` (412). Applies to financing-plan creation.

This ordering means, for example, that a caller lacking permission always sees `ERR_FORBIDDEN` before any state or business check runs, and that a stale-version conflict on a financing offer surfaces only after the body has been validated and the referenced job has been resolved.

### 2.6. Referential Integrity and Path Resolution

Because entities are peers linked by foreign-key fields rather than nested under one another, most paths address a single resource by its own identifier: a dwelling by `dwelling_id`, a WAP application by `wap_application_id`, a job by `job_id`, an audit by `audit_id`, a diagnostic test by `diagnostic_test_id`, a scope item by `scope_item_id`, a crew by `crew_id`, a crew assignment by `crew_assignment_id`, a rebate claim by `rebate_claim_id`, and a financing plan by `financing_plan_id`. When a path carries an identifier that does not resolve, the request fails with `ERR_NOT_FOUND` (404) before any state or business rule is considered; when a path carries more than one identifier, they are validated left to right and the first that fails to resolve determines the 404.

Relationships between resources are expressed through foreign keys carried in request bodies. Those foreign keys are resolved with the same `ERR_NOT_FOUND` (404) semantics as path identifiers: a create request that references a non-existent parent — a scope item citing a missing `job_id` or `audit_id`, a rebate claim citing a missing `scope_item_id`, a crew assignment citing a missing `crew_id`, a diagnostic test citing a missing `baseline_test_id`, and so on — is rejected before its business logic runs.

### 2.7. Monetary Precision, Rounding, and Energy-Savings Units

All monetary amounts are stored and returned as integer cents. Wherever a computation can produce a fractional cent — because a per-square-foot rate is multiplied by a possibly fractional area, or because an amortization divides a principal — the result is rounded half up to a whole number of cents. Energy-savings figures are expressed in kilowatt-hours (kWh) and are rounded half up to one decimal place. Ratios used purely as pass/fail thresholds (the blower-door reduction fraction) are compared at full floating-point precision without intermediate rounding.

Two derived amounts have additional flooring or capping behavior described with their calculations: a job's estimated out-of-pocket balance is floored at zero, and both the per-measure tax credit and the annual tax credit total are subject to a pinned rounding-then-capping order (Section 3.6). Boundary comparisons are inclusive where the underlying rule says so — WAP income eligibility uses an at-or-below comparison, and the verification reduction threshold uses an at-or-above comparison.

### 2.8. Parallel Job Dimensions, Cascades, and Version Semantics

A job tracks three status fields that evolve on different clocks. `job_status` (`ACTIVE`, `COMPLETED`, or `CANCELLED`) is the overall lifecycle. Independently, `install_status` (`PLANNED`, `SCHEDULED`, or `INSTALLED`) tracks the physical install, and `verification_status` (`PENDING`, `PASSED`, or `FAILED`) tracks post-test outcomes. `install_status` and `verification_status` are **parallel, independent dimensions**: one advances through crew scheduling and install completion, the other through post-test verification, and neither gates the other's transitions except where a workflow explicitly says so. The overall `job_status` auto-completes only when both terminal-favorable conditions are met (Section 3.8).

Because the system holds immediate consistency, an operation on one resource frequently reconciles others. When a job is cancelled or fails verification, the effect cascades down to that job's scope items, rebate claims, and crew assignments; when a scope item is approved, installed, or cancelled, or when a rebate claim is approved or voided, the job's derived money and savings totals are recomputed on the spot. Each reconciliation that mutates a resource refreshes that resource's `updated_at`. The specific fields recomputed on each event, and the exact cascade chains, are described in the relevant Section 3 workflows; the governing principle here is that no client action leaves a job's derived totals stale.

### 2.9. Optimistic Concurrency for Financing Offers

Offering a financing plan is the one write in the system guarded by optimistic concurrency against a parent job. A financing-offer request must carry `expected_job_version`, the `version` of the target job that the client last observed. Before the offer is created, the server compares `expected_job_version` against the job's current `version`; if they differ, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no plan is created.

The reason this guard exists is that a newly offered plan legitimately supersedes any prior offered plan for the same job and, in doing so, advances the job's `version`. If a client reads the job, and another writer then offers a plan that advances the job's `version`, a later offer still carrying the pre-supersede `expected_job_version` is operating on a stale view of the job and is rejected so it cannot overwrite an offer it never observed. The rejection is purely a function of the observed-versus-current `version` comparison: whenever the submitted `expected_job_version` is behind the job's current `version`, the offer is refused with `ERR_STALE_VERSION`. No other endpoint accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Dwellings, Households, and WAP Eligibility

Everything begins with a **dwelling** — the physical home. A `ProgramAdmin` records a dwelling with its `address`, its `year_built`, its `conditioned_area_sqft` (the conditioned floor area in square feet), its `foundation_type`, and its `heating_fuel_type`. The `foundation_type` is one of `SLAB`, `CRAWLSPACE`, or `BASEMENT`; the `heating_fuel_type` is one of `GAS`, `ELECTRIC`, `OIL`, or `PROPANE`. Any other value for either enum is a malformed body (`ERR_VALIDATION`).

A household seeking low-income assistance submits a **WAP application** against a dwelling. Either a `ProgramAdmin` or a `Homeowner` may submit it, providing the `dwelling_id` of the home, the `household_size` (which must be at least 1), and the `annual_gross_income_cents` (which must be at least 0). Eligibility is decided immediately at submission and is never revised afterward. The system first computes the household's income limit, stored as `income_limit_cents`: it is twice the sum of a base amount for a one-person household plus a per-additional-person amount for each person beyond the first. The base amount for a single-person household is 1,500,000 cents ($15,000), the increment for each additional household member is 500,000 cents ($5,000), and the whole figure is doubled because the program screens at 200% of the federal poverty level. Concretely, `income_limit_cents` equals 2 × (1,500,000 + (`household_size` − 1) × 500,000). The application's `status` is then set to `ELIGIBLE` when `annual_gross_income_cents` is less than or equal to `income_limit_cents`, and to `INELIGIBLE` otherwise; the boundary is inclusive, so an income exactly equal to the limit is `ELIGIBLE`. WAP applications may be listed with optional filters on `dwelling_id` and `status`.

### 3.2. Opening, Tracking, and Cancelling a Job

A `ProgramAdmin` opens a **job** for a dwelling by supplying the `dwelling_id`, the `program_track`, and the `rebate_budget_cap_cents`. The `program_track` is one of `WAP`, `UTILITY`, or `MARKET`, and it names the funding track. When the track is `WAP`, the job may be created only if the referenced dwelling already has a WAP application whose `status` is `ELIGIBLE`; if no eligible application exists for that dwelling, creation is rejected with `ERR_NOT_WAP_ELIGIBLE`. The `rebate_budget_cap_cents` (which must be at least 0) is the ceiling on the total approved utility rebate the job may ever accrue.

A newly created job starts with `job_status` = `ACTIVE`, `install_status` = `PLANNED`, and `verification_status` = `PENDING`, its `version` at 1, and all of its computed money and savings fields initialized (`total_estimated_cost_cents`, `approved_rebate_total_cents`, `tax_credit_cents`, and `estimated_out_of_pocket_cents` at 0, `estimated_annual_savings_kwh` at 0, and `verified_annual_savings_kwh` left null until verification). Reading a job returns all of these derived fields alongside the inputs; jobs may be listed with optional filters on `dwelling_id` and `job_status`.

Cancellation is a `ProgramAdmin` action available only while the job is `ACTIVE`; attempting it on a job that is not `ACTIVE` fails with `ERR_INVALID_STATE`. Cancelling moves `job_status` from `ACTIVE` to `CANCELLED` and unwinds the job's commitments through a compensating cascade. Every scope item still in `PROPOSED`, `APPROVED`, or `INSTALLED` is moved to `CANCELLED`; for each such scope item that had a rebate claim in `APPROVED` status, that claim is moved to `VOIDED`, which returns its `finalized_amount_cents` to the budget by decrementing the job's `approved_rebate_total_cents`. Separately, every crew assignment for the job still in `SCHEDULED` is moved to `CANCELLED`, releasing its reserved crew-days back to the crew (Section 3.5). After the cascade, the job's financial rollup is recomputed so that `total_estimated_cost_cents` and `estimated_out_of_pocket_cents` reflect the reduced scope. Cancellation advances the job's `version`.

### 3.3. The Energy Audit Cycle and Diagnostic Testing

An `Auditor` opens an **energy audit** for a job by supplying the `job_id`; the audit is created in `DRAFT` status with its `auditor_user_id` set to the auditor's `X-User-ID`. Audits may be read individually or listed with optional filters on `job_id` and `status`.

The audit follows a cycle. Submitting a `DRAFT` audit for review advances it from `DRAFT` to `SUBMITTED`; submitting an audit that is not in `DRAFT` fails with `ERR_INVALID_STATE`. On submission, the audit's `estimated_annual_savings_kwh` is computed as the sum of `estimated_savings_kwh` across every scope item of the audit's job that is not in `REJECTED` status, rounded half up to one decimal place. A `ProgramAdmin` then decides the submitted audit by supplying a `decision`. A `decision` of `APPROVE` moves a `SUBMITTED` audit to `APPROVED`; a `decision` of `REJECT` moves a `SUBMITTED` audit to `REJECTED`. Deciding an audit that is not `SUBMITTED` fails with `ERR_INVALID_STATE`. A `REJECTED` audit is re-submittable: submitting it again advances `REJECTED` back to `SUBMITTED` and recomputes its `estimated_annual_savings_kwh`, closing the `SUBMITTED → REJECTED → SUBMITTED` revision loop. Only `APPROVED` is terminal.

In parallel, the `Auditor` documents the home's leakage with **diagnostic tests**. A diagnostic test records a `job_id`, a `kind` (`BLOWER_DOOR` or `DUCT_LEAKAGE`), a `stage` (`BASELINE` or `POST`), and a `cfm_measured` (the measured airflow — CFM50 for a blower-door test, CFM25 for a duct-leakage test — which must be greater than 0). The test also captures `tester_user_id` from the auditor's `X-User-ID`. When a test's `stage` is `POST`, it must carry a `baseline_test_id` that references a `BASELINE` test of the same job and the same `kind`; a POST-stage test that does not reference such a matching baseline is rejected with `ERR_BASELINE_TEST_REQUIRED`. For a `BASELINE` test, `baseline_test_id` is left null. Diagnostic tests may be listed with optional filters on `job_id`, `baseline_test_id`, `kind`, and `stage`.

### 3.4. Proposing and Approving Scope Measures

An `Auditor` proposes a **scope item** — a single recommended measure — by supplying the `job_id`, the `audit_id` of the audit that recommended it, the `category`, the `area_sqft` (treated area in square feet, greater than 0), the `target_r_value` (the target insulation R-value, at least 0), the `estimated_cost_cents` (at least 0), and the `estimated_savings_kwh` (estimated annual kWh savings, at least 0). The `category` is one of `ATTIC_INSULATION`, `WALL_INSULATION`, `CRAWL_INSULATION`, `AIR_SEALING`, or `DUCT_SEALING`. A scope item is created in `PROPOSED` status; its `achieved_r_value` and `actual_cost_cents` remain null until installation records them. Scope items may be listed with optional filters on `job_id`, `audit_id`, `status`, and `category`.

A `ProgramAdmin` decides a proposed scope item by supplying a `decision`. A `decision` of `APPROVE` moves a `PROPOSED` scope item to `APPROVED`, but only if the audit named by its `audit_id` is currently in `APPROVED` status; approving against an audit that is not `APPROVED` is rejected with `ERR_AUDIT_NOT_APPROVED`. A `decision` of `REJECT` moves a `PROPOSED` scope item to `REJECTED`, which is terminal. Deciding a scope item that is not `PROPOSED` fails with `ERR_INVALID_STATE`. Approving a scope item recomputes the job's financial rollup: `total_estimated_cost_cents` becomes the sum of `estimated_cost_cents` across the job's scope items in `APPROVED`, `INSTALLED`, or `VERIFIED` status, and the job's `estimated_out_of_pocket_cents` is recomputed accordingly (Section 3.6 defines the rollup fully). The job's `estimated_annual_savings_kwh` — distinct from the audit's field of the same name — is the audit-model projection: the sum of `estimated_savings_kwh` across the job's scope items in `APPROVED`, `INSTALLED`, or `VERIFIED` status, rounded half up to one decimal place.

### 3.5. Crew Scheduling and Capacity

A `ProgramAdmin` registers an install **crew** with a `name`, a `crew_size` (number of installers, at least 1), a `skills` array (the set of scope-item categories the crew is qualified to install), and a `capacity_days` (the maximum committed crew-days the crew may hold across active assignments, at least 0). A crew exposes two derived fields: `committed_days`, the sum of `duration_days` over that crew's assignments currently in `SCHEDULED` status, and `available_days`, which is `capacity_days` minus `committed_days`. A freshly registered crew has `committed_days` of 0 and `available_days` equal to `capacity_days`.

Scheduling a crew for a job is a `ProgramAdmin` action that creates a **crew assignment** from a `job_id`, a `crew_id`, a `scheduled_start_date`, and a `scheduled_end_date`. Both dates are ISO 8601 UTC date-times, and the window is treated as half-open, covering the start instant up to but not including the end instant. The `scheduled_end_date` must be strictly after the `scheduled_start_date`, or the request fails with `ERR_INVALID_DATE_WINDOW` (422). The assignment's `duration_days` is computed as the whole number of days between start and end. Three further checks then apply: the requested window may not overlap any window of another assignment for the same crew that is currently `SCHEDULED`, or the request fails with `ERR_CREW_DOUBLE_BOOKED`; the requested window may not fall too close to a `SCHEDULED` assignment belonging to a *different* job at the *same* dwelling — specifically, if fewer than 2 whole days separate the two windows, the request fails with `ERR_DWELLING_WINDOW_CONFLICT`; and adding this assignment's `duration_days` to the crew's current `committed_days` may not exceed the crew's `capacity_days`, or the request fails with `ERR_CREW_CAPACITY_EXCEEDED`.

When an assignment is created it starts in `SCHEDULED` status and reserves its crew-days by adding `duration_days` to the crew's `committed_days`. As a side effect, if the target job's `install_status` is still `PLANNED`, this — the first scheduled assignment for the job — moves the job's `install_status` from `PLANNED` to `SCHEDULED` and advances the job's `version`. Cancelling a crew assignment is available to a `ProgramAdmin` while the assignment is `SCHEDULED` (cancelling one that is not `SCHEDULED` fails with `ERR_INVALID_STATE`); it moves the assignment to `CANCELLED` and releases its reservation, subtracting `duration_days` back out of the crew's `committed_days` so the ledger returns to its pre-assignment value. The same release runs when a crew assignment is cancelled as part of a job-cancellation cascade. Crew assignments may be listed with optional filters on `job_id`, `crew_id`, and `status`.

### 3.6. Installation and the Federal 25C Tax Credit

Once the audit is approved and the crew is scheduled, an `Installer` records completed work by marking an approved scope item installed, supplying the measured `achieved_r_value` and the `actual_cost_cents` of the finished measure. This is permitted only when the scope item is in `APPROVED` status and the referenced job's `install_status` is `SCHEDULED`; either precondition failing yields `ERR_INVALID_STATE`. The action moves the scope item from `APPROVED` to `INSTALLED`, stores the supplied `achieved_r_value` and `actual_cost_cents` on it, and recomputes both the job's `tax_credit_cents` and its financial rollup.

The job's `tax_credit_cents` implements the federal 25C credit. The qualifying set is the job's scope items in `INSTALLED` or `VERIFIED` status whose `category` is one of `ATTIC_INSULATION`, `WALL_INSULATION`, `CRAWL_INSULATION`, or `AIR_SEALING`; `DUCT_SEALING` never qualifies and is excluded. For each qualifying measure, the per-measure credit is 30% of that measure's `actual_cost_cents`, rounded to the nearest whole dollar — that is, take 0.30 times `actual_cost_cents`, round that amount half up to a whole number of dollars, and express it back in cents as a multiple of 100. The evaluation order is pinned and must not be reordered: **round each measure's credit to whole dollars first, then sum the rounded per-measure credits, then apply the annual cap.** The job's `tax_credit_cents` is the lesser of that sum and the annual cap of 120,000 cents ($1,200).

The **financial rollup** ties the money fields together and is recomputed whenever a scope item is approved, marked installed, or cancelled, whenever a rebate claim is approved or voided, when the install dimension is completed, and during the verification-failure cascade. It sets `total_estimated_cost_cents` to the sum of `estimated_cost_cents` across the job's scope items in `APPROVED`, `INSTALLED`, or `VERIFIED` status; it sets `tax_credit_cents` from the 25C computation above; and it sets `estimated_out_of_pocket_cents` to the greater of 0 and (`total_estimated_cost_cents` − `approved_rebate_total_cents` − `tax_credit_cents`), so the out-of-pocket balance is floored at zero.

Completing the install dimension is a separate `ProgramAdmin` action that moves the job's `install_status` from `SCHEDULED` to `INSTALLED`. It is permitted only while the job is `ACTIVE` and its `install_status` is `SCHEDULED` (otherwise `ERR_INVALID_STATE`), and only if no scope item of the job remains in `APPROVED` status still awaiting installation — if any approved-but-uninstalled measure remains, the request fails with `ERR_SCOPE_INCOMPLETE`. On success it sets `install_status` to `INSTALLED`, recomputes the financial rollup, and advances the job's `version`.

### 3.7. Utility Rebate Claims and the Budget Ledger

A `ProgramAdmin` opens a **rebate claim** against an installed measure by supplying the `job_id` and the `scope_item_id`. The claim is created in `DRAFT` status, and its `provisional_amount_cents` is computed immediately from the tiered rebate schedule using the scope item's `target_r_value`. The rebate schedule first maps an R-value to a tier: an R-value below 30 is tier 1, an R-value from 30 up to but not including 49 is tier 2, and an R-value of 49 or more is tier 3. For the three insulation categories the per-square-foot rate in cents is drawn from that tier — attic insulation pays 50, 90, or 130 cents per square foot for tiers 1, 2, and 3 respectively; wall insulation pays 40, 70, or 100; crawlspace insulation pays 30, 55, or 80. The two sealing categories carry no tier and use a flat rate: air sealing pays 25 cents per square foot and duct sealing pays 20 cents per square foot regardless of R-value. The raw rebate is the applicable rate multiplied by the measure's `area_sqft`, rounded half up to whole cents, and the stored amount is capped at the per-measure ceiling of 200,000 cents ($2,000). Rebate claims may be read individually or listed with optional filters on `job_id`, `scope_item_id`, and `status`.

Submitting a rebate claim moves it from `DRAFT` to `SUBMITTED` and recomputes the rebate as `finalized_amount_cents` using the same schedule and cap but keyed on the measure's `achieved_r_value` rather than its `target_r_value`; the finalized amount therefore diverges from the provisional amount whenever the installed R-value lands in a different tier. Submission is permitted only when the claim is in `DRAFT` (otherwise `ERR_INVALID_STATE`) and only when the referenced scope item is in `INSTALLED` or `VERIFIED` status; a claim whose measure is not yet installed is rejected with `ERR_SCOPE_NOT_INSTALLED`.

A `ProgramAdmin` then decides a submitted claim by supplying a `decision`. A `decision` of `APPROVE` moves a `SUBMITTED` claim to `APPROVED`, but only if doing so keeps the budget in bounds: the job's current `approved_rebate_total_cents` plus this claim's `finalized_amount_cents` must not exceed the job's `rebate_budget_cap_cents`, or the approval is rejected with `ERR_REBATE_BUDGET_EXCEEDED`. On approval the claim's `finalized_amount_cents` is added to the job's `approved_rebate_total_cents` and the job's `estimated_out_of_pocket_cents` is recomputed. A `decision` of `DENY` moves a `SUBMITTED` claim to `DENIED`, which is terminal. Deciding a claim that is not `SUBMITTED` fails with `ERR_INVALID_STATE`. The job's `approved_rebate_total_cents` is always the sum of `finalized_amount_cents` over the job's rebate claims currently in `APPROVED` status, and the remaining budget is the `rebate_budget_cap_cents` minus that total.

Voiding is the compensating action on the rebate ledger. A `ProgramAdmin` may void a claim that is in `APPROVED` status (voiding one that is not `APPROVED` fails with `ERR_INVALID_STATE`); the same void also happens automatically when a job cancellation or a verification failure cascades onto an approved claim. Voiding moves the claim to `VOIDED` (terminal), subtracts its `finalized_amount_cents` back out of the job's `approved_rebate_total_cents` so the total returns to its pre-approval value, and recomputes `estimated_out_of_pocket_cents`.

### 3.8. Post-Test Verification and Job Completion

Independent verification is an `Auditor` action that resolves the job's `verification_status`. The auditor supplies a `post_test_id` naming the POST-stage blower-door test to measure against. Verification is permitted only when the job's `install_status` is `INSTALLED` (otherwise `ERR_INVALID_STATE`). Segregation of duties applies: the acting auditor's `X-User-ID` must not equal the `tester_user_id` recorded on the job's baseline blower-door test, or the request is rejected with `ERR_SOD_VIOLATION` — the person who recorded the baseline may not sign off on the outcome. The job must also have at least one scope item in `INSTALLED` status; if none is installed, verification fails with `ERR_SCOPE_INCOMPLETE`. The `post_test_id` must resolve to a POST-stage blower-door test whose `baseline_test_id` in turn resolves to a `BASELINE` blower-door test of this same job, establishing the baseline/post pair used for measurement.

The outcome is driven by the whole-house air-leakage reduction. The reduction fraction is the baseline CFM50 minus the post CFM50, divided by the baseline CFM50, where the baseline and post CFM50 are the `cfm_measured` values of the baseline and post blower-door tests. Verification **passes** when this fraction is at least 0.20 (a 20% reduction) and **fails** when it is below 0.20; the comparison is inclusive at exactly 0.20 and is made at full precision.

On a pass, the job's `verification_status` moves from `PENDING` to `PASSED`. The job's `verified_annual_savings_kwh` is then computed top-down from the measurement: it is the CFM50 reduction (baseline CFM50 minus post CFM50) multiplied by 1.5 kWh per unit of CFM50 reduction, rounded half up to one decimal place; this measurement-based figure typically differs from the audit-model `estimated_annual_savings_kwh`. Every scope item of the job in `INSTALLED` status is advanced to `VERIFIED`. Finally, because the install dimension is already `INSTALLED` and verification has now passed, the overall `job_status` auto-completes from `ACTIVE` to `COMPLETED` — the two parallel dimensions have both terminated favorably. A pass advances the job's `version`.

On a failure, the job's `verification_status` moves from `PENDING` to `FAILED`, and a three-link cascade unwinds the affected work. First (link 1), every scope item of the job in `INSTALLED` status is moved to `FAILED_VERIFICATION`. Second (link 2), for each such scope item that had a rebate claim in `APPROVED` status, that claim is moved to `VOIDED`, caused by its measure failing verification. Third (link 3), each voided claim decrements the job's `approved_rebate_total_cents` by its `finalized_amount_cents` and the job's `estimated_out_of_pocket_cents` is recomputed, caused by the rebate voiding. A failure does not complete the job; it too advances the job's `version`.

### 3.9. Financing the Remaining Balance

A household may finance whatever out-of-pocket balance remains. Either a `ProgramAdmin` or a `Homeowner` offers a **financing plan** for a job by supplying the `job_id`, the `principal_cents` (the financed principal, greater than 0), the `term_months` (the loan term, at least 1), the `apr_bps` (the annual percentage rate in basis points, at least 0, where 600 basis points means 6.00%), and the `expected_job_version` required by the optimistic-concurrency guard of Section 2.9.

The plan is created in `OFFERED` status with its `monthly_payment_cents` computed by standard amortization. The monthly interest rate is `apr_bps` divided by 10,000 to convert basis points to a decimal fraction, then divided by 12. When `apr_bps` is 0 the monthly rate is 0, and `monthly_payment_cents` is simply `principal_cents` divided by `term_months`, rounded half up to whole cents. Otherwise `monthly_payment_cents` is `principal_cents` multiplied by the monthly rate, divided by the quantity one minus (one plus the monthly rate) raised to the power of the negative `term_months`, with the final result rounded half up to whole cents.

Offering a new plan for a job automatically supersedes any existing plan for that job that is still in `OFFERED` status, moving the prior plan from `OFFERED` to `SUPERSEDED`, and advances the job's `version` (which is exactly what causes a later offer still carrying an outdated `expected_job_version` to be rejected under the stale-version guard of Section 2.9). A `Homeowner` responds to an offered plan by supplying a `decision`: a `decision` of `ACCEPT` moves an `OFFERED` plan to `ACCEPTED`, and a `decision` of `DECLINE` moves an `OFFERED` plan to `DECLINED`; responding to a plan that is not `OFFERED` fails with `ERR_INVALID_STATE`. `ACCEPTED`, `DECLINED`, and `SUPERSEDED` are all terminal. Financing plans may be read individually or listed with optional filters on `job_id` and `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource or drive a state transition on an existing resource return `200 OK`. In the Authorized Role(s) column, "Any" means every recognized role (`ProgramAdmin`, `Auditor`, `Installer`, `Homeowner`) may call the endpoint; every other cell lists the exact role(s) permitted.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/weatherization/dwellings` | Create a dwelling record | ProgramAdmin |
| GET | `/weatherization/dwellings/{dwelling_id}` | Read a dwelling | Any |
| POST | `/weatherization/wap-applications` | Submit a WAP household eligibility application | ProgramAdmin, Homeowner |
| GET | `/weatherization/wap-applications/{wap_application_id}` | Read a WAP application | Any |
| GET | `/weatherization/wap-applications` | List WAP applications | Any |
| POST | `/weatherization/jobs` | Create a weatherization job for a dwelling | ProgramAdmin |
| GET | `/weatherization/jobs/{job_id}` | Read a job (includes computed money and savings fields) | Any |
| GET | `/weatherization/jobs` | List jobs | Any |
| POST | `/weatherization/jobs/{job_id}/complete-install` | Mark the install dimension complete | ProgramAdmin |
| POST | `/weatherization/jobs/{job_id}/verify` | Run post-test verification | Auditor |
| POST | `/weatherization/jobs/{job_id}/cancel` | Cancel a job with cascade | ProgramAdmin |
| POST | `/weatherization/audits` | Open an energy audit for a job | Auditor |
| GET | `/weatherization/audits/{audit_id}` | Read an energy audit | Any |
| GET | `/weatherization/audits` | List energy audits | Any |
| POST | `/weatherization/audits/{audit_id}/submit` | Submit an audit for review | Auditor |
| POST | `/weatherization/audits/{audit_id}/decide` | Approve or reject a submitted audit | ProgramAdmin |
| POST | `/weatherization/diagnostic-tests` | Record a blower-door or duct-leakage measurement | Auditor |
| GET | `/weatherization/diagnostic-tests/{diagnostic_test_id}` | Read a diagnostic test | Any |
| GET | `/weatherization/diagnostic-tests` | List diagnostic tests | Any |
| POST | `/weatherization/scope-items` | Add a recommended measure to a job/audit | Auditor |
| GET | `/weatherization/scope-items/{scope_item_id}` | Read a scope item | Any |
| GET | `/weatherization/scope-items` | List scope items | Any |
| POST | `/weatherization/scope-items/{scope_item_id}/decide` | Approve or reject a proposed scope item | ProgramAdmin |
| POST | `/weatherization/scope-items/{scope_item_id}/mark-installed` | Record installation of an approved measure | Installer |
| POST | `/weatherization/crews` | Register an install crew | ProgramAdmin |
| GET | `/weatherization/crews/{crew_id}` | Read a crew (includes committed/available days) | Any |
| POST | `/weatherization/crew-assignments` | Schedule a crew for a job over a date window | ProgramAdmin |
| GET | `/weatherization/crew-assignments/{crew_assignment_id}` | Read a crew assignment | Any |
| GET | `/weatherization/crew-assignments` | List crew assignments | Any |
| POST | `/weatherization/crew-assignments/{crew_assignment_id}/cancel` | Cancel a scheduled crew assignment | ProgramAdmin |
| POST | `/weatherization/rebate-claims` | Open a utility rebate claim for a scope item | ProgramAdmin |
| GET | `/weatherization/rebate-claims/{rebate_claim_id}` | Read a rebate claim | Any |
| GET | `/weatherization/rebate-claims` | List rebate claims | Any |
| POST | `/weatherization/rebate-claims/{rebate_claim_id}/submit` | Submit a rebate claim (computes finalized amount) | ProgramAdmin |
| POST | `/weatherization/rebate-claims/{rebate_claim_id}/decide` | Approve or deny a submitted rebate claim | ProgramAdmin |
| POST | `/weatherization/rebate-claims/{rebate_claim_id}/void` | Void an approved rebate claim | ProgramAdmin |
| POST | `/weatherization/financing-plans` | Offer a financing plan for a job's out-of-pocket balance | ProgramAdmin, Homeowner |
| GET | `/weatherization/financing-plans/{financing_plan_id}` | Read a financing plan | Any |
| GET | `/weatherization/financing-plans` | List financing plans | Any |
| POST | `/weatherization/financing-plans/{financing_plan_id}/respond` | Accept or decline an offered financing plan | Homeowner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_DATE_WINDOW` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AUDIT_NOT_APPROVED` | 409 |
| `ERR_SCOPE_NOT_INSTALLED` | 409 |
| `ERR_NOT_WAP_ELIGIBLE` | 409 |
| `ERR_BASELINE_TEST_REQUIRED` | 409 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_SCOPE_INCOMPLETE` | 409 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_DWELLING_WINDOW_CONFLICT` | 409 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 |
| `ERR_REBATE_BUDGET_EXCEEDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
