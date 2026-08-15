# Global Mobility Assignment Tax API — Product Requirements Document

## 1. Introduction

Multinational employers that place employees on foreign assignments carry two stubborn obligations for the life of every placement. The assignee must be kept tax-neutral — neither enriched nor penalized by the gap between home-country and host-country taxation — and the business must maintain a continuously reconciled view of what each assignment costs and which business unit ultimately pays for it. This document specifies the Global Mobility & Assignment Tax Equalization API, the system of record for an expatriate assignment program from letter drafting through repatriation and final ledger closure.

The API spans assignment letter and compensation package construction, home/host payroll splits and shadow payroll, hypothetical tax withholding with year-end tax equalization settlement, tax return preparation vendor coordination, social security totalization certificates of coverage, per-diem and housing allowance policy, assignment extension and repatriation, and forward cost projection with business-unit chargeback. All resources live in a flat set of peer collections mounted under `/mobility`; relationships between them are expressed through identifier fields carried in request bodies rather than through nested URLs.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

Nine role designations are recognized. `MobilityAdmin` is the global mobility program administrator: it owns programs, employees, allowance policies, the assignment lifecycle, extension requests, and the logical clock. `BusinessUnitApprover` performs the first step of assignment dual approval and decides extension requests. `MobilityApprover` performs the second approval step and approves compensation packages. `PayrollSpecialist` operates compensation packages, payroll splits, shadow payroll records, and settlement preparation. `FinanceController` approves and executes settlements, posts and voids chargeback entries, and creates cost projections. `VendorCoordinator` drives tax-vendor engagements and certificates of coverage. `TaxVendor` is the external tax preparation vendor's operator and returns draft returns. `Assignee` is the expatriate employee, acting on their own resources only. `Any` is not a granted credential but the designation used in §4 for read endpoints open to every authenticated role.

A request whose role is not among the roles authorized for the endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Identity semantics differ by role. When `X-User-Role` is `Assignee`, `X-User-ID` is the `id` of the acting Employee; ownership checks on any resource that references an Employee — in practice the settlement dispute path — compare the target assignment's `employee_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_FOR_ROLE`. When `X-User-Role` is `MobilityAdmin`, `BusinessUnitApprover`, `MobilityApprover`, `PayrollSpecialist`, `FinanceController`, `VendorCoordinator`, `TaxVendor`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on the resources it mutates (for example as `submitted_by_user_id`, `bu_approved_by_user_id`, `created_by_user_id`, `approved_by_user_id`, or `decided_by_user_id`), where it feeds the segregation-of-duties checks of §2.8, but it never compares that identifier to any entity's `id`.

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

Requests to undefined paths, and to declared paths with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope.

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order — stable creation order, with ties on the creation timestamp broken by `id` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

Beyond pagination, each list endpoint accepts optional equality filters matching its resource's reference and status fields. Filters compare by exact equality; integer-typed filter fields (such as `tax_year`) coerce the query value to an integer before comparison, and a value that cannot be coerced simply matches nothing. Assignments filter by `program_id`, `employee_id`, `policy_id`, or `status`; allowance policies by `host_country_code`; compensation packages, payroll splits, and certificates of coverage by `assignment_id`; shadow payroll records by `assignment_id`, `tax_year`, or `status`; settlements by `assignment_id`, `tax_year`, `status`, or `vendor_engagement_id`; vendor engagements by `assignment_id`, `tax_year`, or `status`; cost projections and extension requests by `assignment_id` or `status`; chargeback entries by `assignment_id`, `entry_type`, `status`, `source_record_id`, or `source_settlement_id`.

### 2.4. Common Resource Properties

Every resource in the API carries a standard set of system-managed fields:

- **`id` (string):** A server-minted unique identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp refreshed whenever the resource's properties change.
- **`version` (integer):** A system-managed integer that starts at 1 at creation — with `updated_at` equal to `created_at` — and increments by exactly one on every direct write to the resource, anchoring the optimistic concurrency rules of §2.7. Ledger-cascade aggregate refreshes are the one exception: updates to an assignment's year-to-date counters and `cost_posture`, and to a program's `total_posted_chargeback_cents`, refresh `updated_at` only and leave `version` unchanged.

No entity in this API is exempt from these four properties. Where a workflow narrates that a cross-entity cascade "refreshes" an assignment's `updated_at`, the cascade touch is deliberate; where a workflow narrates that the assignment's `version` advances, it advances by exactly one.

### 2.5. The Logical Clock and Calendar Semantics

All date-dependent behavior — the certificate-of-coverage expiry sweep, the `actual_end_date` stamp at repatriation completion — reads a server-maintained logical clock, never the wall clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. A `MobilityAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant — the set is free-standing, so the supplied instant may lie forward or backward — and returns the resulting `current_utc`; advancing the clock past an issued certificate's coverage end triggers the expiry cascade described in §3.5. Audit timestamps — the meta envelope's `api_request_timestamp` and every resource's `created_at` and `updated_at` — are wall-clock values; the logical clock governs business-date behavior only.

Two interval conventions coexist and must not be confused. Assignment windows are closed intervals: `start_date` and `planned_end_date` are both inclusive, so two same-employee assignments whose windows merely touch at a single shared date are in conflict. Allowance policy windows are half-open: `effective_from` is inclusive and `effective_to` exclusive, so two back-to-back policies for the same country — one ending exactly where the next begins — are permitted.

### 2.6. Monetary Precision and Rounding

Every monetary amount in the system is an integer number of cents expressed in the owning program's `functional_currency`; no fractional cents exist anywhere. Rounding, where a rule requires it, is always round half up to integer cents, applied at exactly the pinned step the rule declares — never earlier, never twice. Three pinned orderings recur throughout §3 and are stated here once: when a gross amount is split between home and host payroll, the home share is the rounded one and the host share takes the residual; when a per-diem allowance is computed, the COLA-adjusted daily rate is rounded first and only then multiplied by the number of days; when hypothetical tax is computed, the annual tax figure is rounded first and the monthly division is rounded second.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control on the Assignment aggregate: creating a cost projection (`POST /mobility/cost-projections`), creating an extension request (`POST /mobility/extension-requests`), and initiating repatriation (`POST /mobility/assignments/{id}/initiate-repatriation`). Each of these requests must carry `expected_assignment_version`, a non-optional input holding the `version` of the target Assignment as the client last observed it. If that value does not match the Assignment's current `version` — because any direct write to the assignment (submission, either approval step, either rejection, cancellation, an extension approval, a cost-projection creation, an extension-request creation, repatriation initiation or completion, or closure) has advanced it since the client's last read — the request is rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412), preventing the client from acting on terms it has not observed. The guard exists because each of these operations would otherwise legitimately succeed on the stale view: a cost-projection creation silently supersedes the prior `CURRENT` projection, an extension-request creation silently supersedes the prior `PENDING` request, and repatriation initiation is valid whenever the assignment is still `ACTIVE`. Endpoints not listed here take no version field.

### 2.8. Segregation of Duties

Three controlled steps require two distinct people. The operator who approves a compensation package must differ from the package's `created_by_user_id`. The controller who approves a settlement must differ from the settlement's `created_by_user_id`. And the mobility approver who activates an assignment must differ from the assignment's `bu_approved_by_user_id` — the business-unit approver who performed the first approval step. Any attempt to perform both sides of a controlled step with the same `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

### 2.9. Cascading Ledger Consistency

Several single calls produce multi-hop cascades that cross aggregate boundaries, and the server performs every hop automatically — clients never invoke the downstream resources directly. Posting a shadow payroll record creates a chargeback entry, which updates the assignment's year-to-date aggregates, which re-runs the overrun posture check, whose outcome in turn gates extension approval. Initiating repatriation suspends the active payroll split, and that suspension voids every draft shadow payroll record of the assignment. Certificate expiry flips the split's exemption flag, and that flip recomputes employer social security on every draft record while posted records stay frozen. Because chargeback entries are only ever created as cascade products, the chargeback list endpoint is their sole discovery channel. Program-level and assignment-level totals are maintained as signed running aggregates — voiding compensates them — so the ledger always reflects the live state of its source documents.

### 2.10. Order of Validation

Every request is evaluated against a fixed validation pipeline, and the earliest failing check determines the error returned:

1. **Authentication context.** Both `X-User-ID` and `X-User-Role` must be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Authorization.** The role must be listed for the endpoint, else `ERR_FORBIDDEN_FOR_ROLE` (403).
3. **Existence.** Every path identifier must resolve to an existing resource, validated left to right; body foreign-key fields (`program_id`, `employee_id`, `policy_id`, `assignment_id`) must reference existing rows, else `ERR_NOT_FOUND` (404). For `Assignee`-only operations, ownership is evaluated once the target resource has resolved: the caller must own the target assignment, else `ERR_FORBIDDEN_FOR_ROLE` (403).
4. **Request shape.** The request body must be a JSON object; required fields must be present; enums must lie in their declared sets; integers must satisfy their field constraints (percentages between 0 and 100 inclusive, amounts non-negative, `period_month` between 1 and 12 inclusive); date fields must be valid `YYYY-MM-DD` calendar dates; `effective_to` must be strictly after `effective_from`; `valid_until` strictly after `valid_from`; `planned_end_date` on or after `start_date` — else `ERR_INVALID_REQUEST` (400).
5. **State eligibility.** The target must be in a from-state of the invoked transition, and terminal states accept no further transitions; state-gated creations require their parent state — a shadow payroll record requires an `ACTIVE` assignment, a settlement requires an assignment that is `ACTIVE`, `REPATRIATION_PENDING`, or `REPATRIATED`, and an extension request requires an `ACTIVE` assignment — else `ERR_INVALID_STATE` (409).
6. **Optimistic concurrency.** On the three guarded operations of §2.7, `expected_assignment_version` must equal the assignment's current `version`, else `ERR_STALE_ASSIGNMENT_VERSION` (412).
7. **Segregation of duties**, per §2.8 — `ERR_SEGREGATION_OF_DUTIES` (409).
8. **Cross-entity referential gates.** Mobility approval requires an `APPROVED` package (`ERR_PACKAGE_NOT_APPROVED`), an `ACTIVE` split (`ERR_SPLIT_NOT_ACTIVE`), and — when the assignment is totalization-covered — an `ISSUED` certificate (`ERR_COC_REQUIRED`); settlement creation and recalculation require a filed engagement (`ERR_VENDOR_NOT_FILED`); record creation and posting require an `ACTIVE` split (`ERR_SPLIT_NOT_ACTIVE`); cost-projection creation requires an approved package and an active split. All are 409.
9. **Date-window rules.** Same-employee assignment overlap (`ERR_ASSIGNMENT_OVERLAP`, 409); same-country policy window overlap (`ERR_POLICY_WINDOW_OVERLAP`, 409); record period outside the assignment window (`ERR_PERIOD_OUTSIDE_ASSIGNMENT`, 422); extension date not strictly forward (`ERR_EXTENSION_NOT_FORWARD`, 422); duration beyond the program cap (`ERR_MAX_DURATION_EXCEEDED`, 422). Where several rules of this family apply to one request, evaluation order is pinned: on assignment creation the duration cap is evaluated before the overlap sweep, on record creation the period-window check precedes the remaining record checks, and on extension creation the strictly-forward rule precedes the duration cap.
10. **Uniqueness and quantity constraints**, evaluated in this order: one open compensation package (`ERR_DUPLICATE_PACKAGE`, 409), one open payroll split (`ERR_DUPLICATE_SPLIT`, 409), one non-closed vendor engagement per tax year (`ERR_DUPLICATE_ENGAGEMENT`, 409), one open certificate (`ERR_COC_ALREADY_OPEN`, 409), one open settlement per tax year (`ERR_DUPLICATE_SETTLEMENT`, 409), one draft-or-posted record per period (`ERR_DUPLICATE_PAYROLL_PERIOD`, 409), per-diem days within the month (`ERR_PER_DIEM_DAYS_INVALID`, 422), and split percentages summing to exactly one hundred (`ERR_SPLIT_SUM_INVALID`, 422).
11. **Cumulative per-diem annual cap** across posted records of the tax year — `ERR_PER_DIEM_ANNUAL_CAP_EXCEEDED` (409), evaluated only on posting.
12. **Extension approval coverage gate** — when the assignment is totalization-covered, an issued certificate whose coverage reaches the requested new end date must exist, else `ERR_COC_COVERAGE_GAP` (409).
13. **Cost posture gate** — extension approval is blocked while the assignment's `cost_posture` is `OVERRUN`, else `ERR_COST_OVERRUN_BLOCKED` (409).
14. **Repatriation and closure ledger gates** — completing repatriation requires every vendor engagement to be `FILED` or `CLOSED` (`ERR_ENGAGEMENT_NOT_FINAL`, 409); closing an assignment requires every settlement `SETTLED` and every chargeback entry `POSTED` or `VOIDED` (`ERR_UNSETTLED_LEDGER`, 409).

## 3. Business Logic & Workflows

### 3.1. Setting Up the Program: Programs, Employees, and Allowance Policies

A `MobilityAdmin` begins by creating a mobility program, supplying a `name`, the `home_country_code` that governs hypothetical taxation, and optionally the `functional_currency` in which every cent-denominated amount of the program is expressed — USD when omitted. Three policy knobs complete the program definition, each with a default the administrator may override at creation: `cost_overrun_threshold_pct` defaults to 110 and controls when an assignment's cost posture flips to overrun (§3.6); `max_assignment_duration_days` defaults to 1825 and caps the length of any assignment in the program; `per_diem_annual_day_cap` defaults to 365 and bounds cumulative per-diem days per assignment per tax year. A program is created `ACTIVE` and stays `ACTIVE` — v1 exposes no archival transition. Its `total_posted_chargeback_cents` starts at zero and thereafter tracks the signed sum of `amount_cents` over all chargeback entries in `POSTED` status belonging to assignments of the program.

Employees are registered with an `employee_ref` — an external HR reference carried as an opaque string, with no uniqueness constraint enforced in v1 — plus `full_name` and `home_country_code`. Two attributes drive downstream money math: `family_size`, the tax household size, defaults to 1, must be at least 1, and sets the personal exemption used by the hypothetical tax schedule at 200000 cents per family member; `annual_base_salary_cents`, the home-country gross annual base salary, is required and must be non-negative.

Per-diem and housing entitlements come from allowance policies, one per host country and era. A `MobilityAdmin` creates a policy with a `policy_name`, the `host_country_code` it covers, a half-open effectiveness window from `effective_from` (inclusive) to `effective_to` (exclusive), the base `per_diem_daily_cents` rate, the `housing_monthly_cap_cents` ceiling, and an optional `cola_pct` cost-of-living adjustment percent that defaults to 0; the two amounts and the percentage must each be non-negative. An `effective_to` that is not strictly after `effective_from` is rejected as `ERR_INVALID_REQUEST`. Because every policy is `ACTIVE` in v1, the half-open windows of any two policies for the same `host_country_code` must not intersect: a genuine overlap is rejected with `ERR_POLICY_WINDOW_OVERLAP`, while mere adjacency — one window's `effective_from` equal to another's `effective_to` — is allowed.

### 3.2. Building the Assignment: Letter, Package, Split, and Dual Approval

With program, employee, and policy in place, a `MobilityAdmin` creates the assignment itself in `DRAFT`, referencing the three parents by `program_id`, `employee_id`, and `policy_id` and supplying `host_country_code`, the `host_business_unit` that will absorb chargeback entries, the `assignment_type` (`SHORT_TERM` or `LONG_TERM`), the `totalization_applies` flag that decides whether certificate coverage gates activation and extension, and the closed assignment window `start_date` through `planned_end_date`. A `planned_end_date` before `start_date` fails shape validation as `ERR_INVALID_REQUEST`. Within the date-window family, the duration cap is evaluated before the overlap sweep: a window ending beyond `start_date` plus the program's `max_assignment_duration_days` is rejected with `ERR_MAX_DURATION_EXCEEDED` (HTTP 422), and only then does the server check whether the same employee already holds an assignment in `DRAFT`, `PENDING_BU_APPROVAL`, `PENDING_MOBILITY_APPROVAL`, `ACTIVE`, or `REPATRIATION_PENDING` whose closed interval intersects the new one — touching endpoints count as a conflict — rejecting with `ERR_ASSIGNMENT_OVERLAP`. A freshly created assignment carries `cost_posture` `NORMAL`, all four year-to-date counters at zero, and `actual_end_date` unset.

The assignment letter is represented by a compensation package, created by a `PayrollSpecialist` or `MobilityAdmin` with the `assignment_id`, a `letter_title`, the `home_base_annual_cents` carried on the letter, and optional `goods_services_differential_pct` and `relocation_lump_sum_cents`, both defaulting to 0 and all amounts non-negative. At most one package per assignment may be open — `DRAFT`, `SUBMITTED`, or `APPROVED` all count as open, and a second attempt is rejected with `ERR_DUPLICATE_PACKAGE`. The creator's identity is recorded as `created_by_user_id`, and `revision_number` starts at 0. A `PayrollSpecialist` submits the package, moving it `DRAFT` → `SUBMITTED`; a `MobilityApprover` then approves it `SUBMITTED` → `APPROVED`, subject to the segregation rule against the creator, with the approver recorded as `approved_by_user_id`. Revision is cyclic: a `PayrollSpecialist` may return a `SUBMITTED` package to `DRAFT`, incrementing `revision_number` by one and clearing `approved_by_user_id`; the same revise action works from `APPROVED`, but only while the linked assignment is still in `DRAFT` — revising the package of an assignment that has progressed further is rejected with `ERR_INVALID_STATE`.

Alongside the letter, a `PayrollSpecialist` creates the payroll split for the assignment with `home_payroll_pct` and `host_payroll_pct`, each between 0 and 100 inclusive and together summing to exactly one hundred — any other total is rejected with `ERR_SPLIT_SUM_INVALID` (HTTP 422) — and the optional `shadow_payroll_host` flag, defaulting to true, which records whether a host shadow payroll is run. At most one split per assignment may be open across `DRAFT`, `ACTIVE`, and `SUSPENDED`, else `ERR_DUPLICATE_SPLIT`. The split is created in `DRAFT` with its computed `coc_exempt` flag false. Activation (`DRAFT` → `ACTIVE`) re-verifies the sum-to-one-hundred rule, surfacing `ERR_SPLIT_SUM_INVALID` if it no longer holds. An `ACTIVE` split may be suspended (`ACTIVE` → `SUSPENDED`) and later resumed (`SUSPENDED` → `ACTIVE`), but resuming requires the linked assignment itself to be `ACTIVE` — resuming under a `REPATRIATION_PENDING` or `REPATRIATED` assignment is rejected with `ERR_INVALID_STATE`. Termination (`ACTIVE` → `TERMINATED` or `SUSPENDED` → `TERMINATED`) is terminal and may be invoked directly by a `PayrollSpecialist` or triggered by the repatriation cascades of §3.9.

Activation of the assignment itself is a dual approval. A `MobilityAdmin` submits the draft, moving it `DRAFT` → `PENDING_BU_APPROVAL` and recording `submitted_by_user_id`. A `BusinessUnitApprover` then approves — `PENDING_BU_APPROVAL` → `PENDING_MOBILITY_APPROVAL`, recording `bu_approved_by_user_id` — or rejects, reverting the assignment to `DRAFT` and clearing `submitted_by_user_id`; an optional `reason` may accompany the rejection. The second step belongs to a `MobilityApprover`, who must be a different person from the business-unit approver recorded in `bu_approved_by_user_id` (a coincidence is `ERR_SEGREGATION_OF_DUTIES`). Mobility approval additionally enforces three referential gates, all 409s: an `APPROVED` compensation package must exist (`ERR_PACKAGE_NOT_APPROVED`), an `ACTIVE` payroll split must exist (`ERR_SPLIT_NOT_ACTIVE`), and when `totalization_applies` is true an `ISSUED` certificate of coverage must exist (`ERR_COC_REQUIRED`). Passing all gates moves the assignment `PENDING_MOBILITY_APPROVAL` → `ACTIVE`. Mobility rejection reverts the assignment to `DRAFT` and clears both `submitted_by_user_id` and `bu_approved_by_user_id`, again accepting an optional `reason`. Finally, a `MobilityAdmin` may cancel an assignment while it is in `DRAFT`, `PENDING_BU_APPROVAL`, or `PENDING_MOBILITY_APPROVAL`, moving it to the terminal `CANCELLED` state; cancellation frees the employee's date window, because `CANCELLED` rows no longer participate in the `ERR_ASSIGNMENT_OVERLAP` check.

### 3.3. The Monthly Shadow Payroll Cycle

Each month of an active assignment, a `PayrollSpecialist` creates a shadow payroll record supplying `assignment_id`, the calendar `tax_year`, the `period_month` between 1 and 12, `total_gross_cents` for the period before any split, the `per_diem_days` claimed, and `housing_receipts_cents`; both amounts and the day count must be non-negative. Creation is gated in pipeline order: the assignment must be `ACTIVE` (`ERR_INVALID_STATE`); an `ACTIVE` payroll split must exist (`ERR_SPLIT_NOT_ACTIVE`); within the date-window family the period-window check precedes the remaining record checks, so the record's month must intersect the assignment's `start_date`–`planned_end_date` window (`ERR_PERIOD_OUTSIDE_ASSIGNMENT`, HTTP 422) before the uniqueness sweep runs; at most one record per assignment, tax year, and period month may exist in `DRAFT` or `POSTED` status — a `VOIDED` record frees the slot — else `ERR_DUPLICATE_PAYROLL_PERIOD`; and `per_diem_days` must not exceed the number of days in the period month, else `ERR_PER_DIEM_DAYS_INVALID` (HTTP 422). The record is created in `DRAFT` with all computed fields derived immediately from the `ACTIVE` split's percentages and the assignment's policy; thereafter a `DRAFT` record is recomputed only by the certificate-expiry cascade of §3.5 — no other event, certificate issuance included, recomputes an existing draft — and its computed fields freeze at posting.

The split math is pinned. `home_gross_cents` is the record's `total_gross_cents` multiplied by `home_payroll_pct` and divided by one hundred, rounded half up to integer cents; `host_gross_cents` is the residual — total minus home — so the two shares always sum back to the total, with the boundary cases falling out naturally (a zero home percentage gives the host everything; one hundred gives the host zero). The allowance fields follow the policy reached through the assignment's `policy_id`: `per_diem_cents` is the policy's `per_diem_daily_cents` uplifted by `cola_pct` — multiplied by one hundred plus `cola_pct` and divided by one hundred, rounded half up to integer cents at the daily-rate step — then multiplied by `per_diem_days` with no second rounding; computing the monthly product first and rounding once at the end is forbidden, because the two orders diverge by cents whenever the daily rate is non-integral. `housing_cents` is the lesser of the policy's `housing_monthly_cap_cents` and the month's `housing_receipts_cents`.

Hypothetical tax uses a tiered annual schedule with a personal exemption. The exemption is the employee's `family_size` multiplied by 200000 cents. For an annual gross amount, taxable income is the gross minus the exemption, floored at zero; the annual tax is ten percent of the first 5000000 cents of taxable income, plus twenty percent of the portion of taxable income between 5000000 and 10000000 cents, plus thirty percent of any taxable income above 10000000 cents, with the annual figure rounded half up to integer cents. Each shadow payroll record applies the PROVISIONAL variant: the record's `total_gross_cents` is multiplied by twelve to project an annual gross, the annual schedule is applied, and the result is divided by twelve and rounded half up to integer cents to yield `hypothetical_tax_cents` — a forward-looking withholding estimate.

Employer-side taxes follow. `employer_host_tax_cents` is a fixed-point gross-up at a host tax rate of forty percent, circular by definition because the employer-paid tax is itself a taxable benefit: the initial estimate is forty percent of `host_gross_cents` rounded half up; each subsequent estimate is forty percent of the sum of `host_gross_cents` and the current estimate, rounded half up at every round; iteration stops when two consecutive estimates agree, after at most fifty rounds, and the final estimate is stored. The closed-form shortcut is forbidden — per-iteration rounding is observable in the result. `employer_socsec_cents` is zero while the split's `coc_exempt` flag is true, and otherwise seven point six five percent of `host_gross_cents`, rounded half up.

Posting, performed by a `PayrollSpecialist`, moves the record `DRAFT` → `POSTED` and is where the ledger comes alive. The split must be `ACTIVE` (`ERR_SPLIT_NOT_ACTIVE`), and the cumulative per-diem cap is enforced: the sum of `per_diem_days` over `POSTED` records of the assignment for the same `tax_year`, plus this record's days, must not strictly exceed the program's `per_diem_annual_day_cap` — exactly reaching the cap is accepted, one day beyond it is rejected with `ERR_PER_DIEM_ANNUAL_CAP_EXCEEDED`. On a successful post, the computed money fields freeze. The first cascade hop creates a chargeback entry of `entry_type` `PERIOD_COST` in `ACCRUED` status, whose `amount_cents` is the sum of the record's five frozen fields — `host_gross_cents`, `employer_host_tax_cents`, `employer_socsec_cents`, `per_diem_cents`, and `housing_cents` — with `business_unit` copied from the assignment's `host_business_unit` and `source_record_id` pointing back at the record. The second hop adds the entry amount to the assignment's `ytd_chargeback_cents`, adds `total_gross_cents` to `ytd_gross_cents`, `hypothetical_tax_cents` to `ytd_hypo_withheld_cents`, and `per_diem_days` to `ytd_per_diem_days`, refreshing the assignment's `updated_at`. The third hop re-runs the overrun posture check of §3.6, which may flip `cost_posture` from `NORMAL` to `OVERRUN`; while the posture is `OVERRUN`, extension approval is rejected with `ERR_COST_OVERRUN_BLOCKED` (§3.7).

Voiding reverses the cycle. A `DRAFT` record may be voided freely to `VOIDED`. A `POSTED` record may be voided only while no settlement in `CALCULATED`, `PENDING_REVIEW`, `APPROVED`, or `DISPUTED` exists for the record's assignment and tax year — posted source records under an open settlement are frozen, and the attempt is rejected with `ERR_INVALID_STATE`. Voiding a posted record compensates: its `PERIOD_COST` chargeback entry transitions to `VOIDED` with the entry-void compensation rules of §3.9, the assignment's `ytd_gross_cents`, `ytd_hypo_withheld_cents`, `ytd_per_diem_days`, and `ytd_chargeback_cents` are each decremented by the record's frozen amounts, and the overrun posture check re-runs, so the posture may flip back from `OVERRUN` to `NORMAL`. The repatriation cascade of §3.9 also voids draft records without compensation, since they never entered the ledger.

### 3.4. Coordinating the Tax-Preparation Vendor

Year-end actuals come from an external tax preparation vendor, engaged per assignment and tax year. A `VendorCoordinator` creates the engagement with `assignment_id`, `tax_year`, the filing `scope` (`HOME_ONLY`, `HOST_ONLY`, or `DUAL`), the `vendor_name`, and the agreed `fee_cents`, which must be non-negative. At most one engagement per assignment and tax year may be non-`CLOSED` — a second attempt while any earlier engagement for the year is still open, including one already `FILED`, is rejected with `ERR_DUPLICATE_ENGAGEMENT`. New engagements start in `ENGAGED` with `revision_count` at 0.

The engagement lifecycle is a cyclic review loop bracketed by linear milestones. The coordinator sends the tax data package, moving `ENGAGED` → `DATA_SENT`. The `TaxVendor` returns a draft return, moving the engagement to `DRAFT_RETURNED` from either `DATA_SENT` or — after a revision round — `REVISION_REQUESTED`. The coordinator begins internal review (`DRAFT_RETURNED` → `UNDER_REVIEW`) and then either sends the draft back for revision (`UNDER_REVIEW` → `REVISION_REQUESTED`, incrementing `revision_count` by one — the loop may repeat as many times as needed) or accepts the draft (`UNDER_REVIEW` → `ACCEPTED`). Marking the return filed moves `ACCEPTED` → `FILED` and records two figures from the filed return, `filed_total_gross_cents` and `filed_home_tax_cents`, both required and non-negative; the filing is what unlocks settlement creation for that assignment and tax year (§3.8). A filed engagement is finally closed (`FILED` → `CLOSED`), the terminal state that also frees the one-open-engagement slot for the year.

### 3.5. Social Security Totalization and the Certificate of Coverage

When a totalization agreement applies between home and host countries, a certificate of coverage exempts the assignment from host social security. A `VendorCoordinator` applies with the `assignment_id` and an external `application_ref`; at most one certificate per assignment may be open across `REQUESTED`, `SUBMITTED`, and `ISSUED`, else `ERR_COC_ALREADY_OPEN`. The application moves `REQUESTED` → `SUBMITTED` when the coordinator submits it to the authorities. Rejection (`SUBMITTED` → `REJECTED`) records the authority's decision and frees the one-open-certificate slot, allowing a fresh application. Issuance is recorded with a coverage window — `valid_from` and `valid_until`, the latter inclusive and required to be strictly after the former, else `ERR_INVALID_REQUEST` — and moves the certificate to `ISSUED` from `SUBMITTED` or, as the re-application path after rejection, directly from `REJECTED`. On issuance the payroll split's `coc_exempt` flag becomes true, so records created thereafter compute `employer_socsec_cents` as zero; existing `DRAFT` records keep their previously computed figures (§3.3). If the logical clock's date is already strictly past the supplied `valid_until` at issuance, the certificate expires immediately within the same call — passing through `ISSUED` to `EXPIRED` with the same split-flag and draft-record cascade as a clock sweep.

Coverage lapse is clock-driven. When the logical clock is advanced past an `ISSUED` certificate's `valid_until` — coverage end being inclusive, expiry triggers only once the clock date is strictly after it — the certificate transitions `ISSUED` → `EXPIRED`. The first cascade hop flips the assignment's split `coc_exempt` back to false; the second hop recomputes `employer_socsec_cents` under the non-exempt rule on every `DRAFT` shadow payroll record of the assignment, while `POSTED` records keep their frozen figures. `REJECTED` and `EXPIRED` are the certificate's terminal states.

### 3.6. Cost Projection and the Overrun Posture

A `FinanceController` or `MobilityAdmin` may create a cost projection for an assignment, a create-with-supersede operation guarded by optimistic concurrency: the request carries `assignment_id` and `expected_assignment_version`, and a mismatch with the assignment's current `version` is rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412) before any other business check. Two referential gates then apply — an `APPROVED` compensation package must exist (`ERR_PACKAGE_NOT_APPROVED`) and an `ACTIVE` payroll split must exist (`ERR_SPLIT_NOT_ACTIVE`). On success, any prior `CURRENT` projection for the assignment becomes `SUPERSEDED`, the new projection is stored as `CURRENT`, and the assignment's `version` increments by one.

The projection's computed fields derive from the assignment window and the compensation plan. `projected_months` is the number of calendar months touched by the closed window from `start_date` to `planned_end_date`, counting both the starting and the ending month. `monthly_cost_cents` builds a per-month employer cost: the approved package's `home_base_annual_cents` is multiplied by the active split's `host_payroll_pct` and divided by one hundred, rounded half up to integer cents, giving the annual host share; dividing that by twelve and again rounding half up gives the monthly host share. The monthly cost is then the monthly host share, plus the forty-percent fixed-point gross-up computed on that monthly host share per the pinned iteration of §3.3, plus employer social security on that monthly host share at seven point six five percent rounded half up (zero while `coc_exempt` holds), plus thirty days of the COLA-adjusted daily per-diem rate from the assignment's policy — the daily rate rounded half up first, exactly as in §3.3 — plus the policy's full `housing_monthly_cap_cents`.

Two variants of the total exist, selected by payroll reality and recorded in `variant`. When the assignment has no `POSTED` shadow payroll record, the projection is `PROVISIONAL`: `total_projected_cents` is `projected_months` multiplied by `monthly_cost_cents`, a pure plan-based forward estimate. Once at least one record has posted, the projection is `ACTUALIZED`: posted actuals replace the plan for elapsed months, so the total is the sum of `amount_cents` over the assignment's `PERIOD_COST` chargeback entries in `ACCRUED` or `POSTED` status (`VOIDED` entries excluded), plus `monthly_cost_cents` multiplied by the remaining months — the projected month count minus the number of `POSTED` records. The same assignment data therefore yields two valid totals: `PROVISIONAL` looks forward from the plan, while `ACTUALIZED` reconciles posted actuals chronologically.

After every mutation of an assignment's `ytd_chargeback_cents` — a record post, a record void, a settlement execution, or a chargeback void — the overrun posture check re-evaluates `cost_posture`. Let the reference be the assignment's `CURRENT` cost projection; if none exists, the posture stays `NORMAL`. The number of posted months is the count of the assignment's `POSTED` shadow payroll records; when that count is zero, the posture is `NORMAL`. Otherwise the pro-rata threshold is the projection's `monthly_cost_cents` multiplied by the posted-month count and by the program's `cost_overrun_threshold_pct`, divided by one hundred, compared as an exact rational with no rounding before the comparison. When `ytd_chargeback_cents` strictly exceeds that threshold, `cost_posture` flips to `OVERRUN`; when it equals the threshold exactly, the posture is `NORMAL`. The posture feeds back into the business process at exactly one point: extension approval (§3.7).

### 3.7. Extending the Assignment

A `MobilityAdmin` requests an extension with `assignment_id`, the `requested_new_end_date`, `expected_assignment_version` for the concurrency guard, and an optional free-text `reason`. Creation is OCC-guarded: a stale `expected_assignment_version` is rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412). The assignment must be `ACTIVE` (`ERR_INVALID_STATE`). Within the date-window family, the strictly-forward rule precedes the duration cap: a `requested_new_end_date` that is not strictly after the assignment's current `planned_end_date` is rejected with `ERR_EXTENSION_NOT_FORWARD` (HTTP 422), and one that would push the assignment beyond `start_date` plus the program's `max_assignment_duration_days` is rejected with `ERR_MAX_DURATION_EXCEEDED` (HTTP 422). Creation is create-with-supersede: any prior `PENDING` request for the same assignment becomes `SUPERSEDED`, the new request starts in `PENDING`, and the assignment's `version` increments by one.

The decision belongs to a `BusinessUnitApprover`. Declining requires the request to be `PENDING` and the assignment `ACTIVE`; it moves the request to `DECLINED` and records `decided_by_user_id`. Approval requires the same two state conditions and then evaluates two further gates in a fixed order: first the coverage gate — when `totalization_applies` is true, an `ISSUED` certificate whose `valid_until` falls on or after the `requested_new_end_date` must exist, otherwise the approval is rejected with `ERR_COC_COVERAGE_GAP`; then the posture gate — while the assignment's `cost_posture` is `OVERRUN`, approval is rejected with `ERR_COST_OVERRUN_BLOCKED`. An approved extension moves the request to `APPROVED`, records `decided_by_user_id`, sets the assignment's `planned_end_date` to the `requested_new_end_date`, refreshes the assignment's `updated_at`, and increments the assignment's `version` by one — an advance any holder of the old version will feel the next time they attempt an OCC-guarded operation.

### 3.8. Year-End Tax Equalization Settlement

Once the vendor has filed, a `PayrollSpecialist` creates the tax equalization settlement for a tax year by supplying `assignment_id` and `tax_year`. The assignment must be `ACTIVE`, `REPATRIATION_PENDING`, or `REPATRIATED` (`ERR_INVALID_STATE` otherwise). An eligible filed engagement must exist for the same assignment and year — eligibility means status `FILED` or `CLOSED` with a recorded `filed_total_gross_cents`; when several qualify, the selection is deterministic: a `FILED` engagement ranks ahead of a `CLOSED` one, then the most recently updated, then the most recently created, then the lexicographically largest `id`. An empty eligible set fails with `ERR_VENDOR_NOT_FILED`. At most one settlement per assignment and tax year may be open — `CALCULATED`, `PENDING_REVIEW`, `APPROVED`, and `DISPUTED` all count as open, while `SETTLED` frees the slot — else `ERR_DUPLICATE_SETTLEMENT`. Creation computes immediately into `CALCULATED`, recording `created_by_user_id` and the `vendor_engagement_id` of the selected engagement.

The reconciliation itself compares what was withheld against what the filed return implies. `total_hypo_withheld_cents` is the sum of `hypothetical_tax_cents` over the assignment's `POSTED` shadow payroll records for the settlement's `tax_year`; `DRAFT` and `VOIDED` records never contribute. `final_hypo_tax_cents` is the FINAL variant of the hypothetical tax — the same tiered annual schedule of §3.3, personal exemption included, applied once to the engagement's `filed_total_gross_cents` rather than to any payroll figure — so identical payroll data paired with a filed gross that differs from twelve times the monthly gross yields a different number than the provisional sum. `settlement_amount_cents` is the withheld total minus the final tax: a positive amount means the company owes the employee (`direction` `EMPLOYEE_CREDIT`), a negative amount means the employee owes the company (`EMPLOYEE_DEBIT`), and an exactly zero amount is `ZERO`.

Review and execution follow. A `PayrollSpecialist` submits the settlement, `CALCULATED` → `PENDING_REVIEW`. Approval belongs to a `FinanceController` who must differ from the settlement's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and its effect splits on the amount: a zero-amount settlement skips `APPROVED` entirely and transitions directly to `SETTLED` with no chargeback entry created, while a nonzero settlement moves to `APPROVED` and records `approved_by_user_id`, waiting for the explicit settle step. While the settlement is `PENDING_REVIEW`, the assignee — and only the assignee, meaning `X-User-ID` must equal the assignment's `employee_id`, else `ERR_FORBIDDEN_FOR_ROLE` — may dispute it with an optional `reason`, moving it to `DISPUTED` with that reason recorded as `dispute_reason`. A `PayrollSpecialist` resolves a dispute by recalculating: the linked engagement must still be `FILED` or `CLOSED` with its `filed_total_gross_cents` recorded (`ERR_VENDOR_NOT_FILED`), all four computed fields are recomputed from the current `POSTED` records and the filed engagement, the settlement returns `DISPUTED` → `CALCULATED`, and `dispute_reason` is cleared — a cyclic revision loop that may repeat. The final settle action, by a `FinanceController`, applies only to nonzero settlements in `APPROVED`; zero amounts are already settled at approval, so attempting it there is `ERR_INVALID_STATE`. Settling moves the settlement to `SETTLED` and fires the cascade: a chargeback entry of `entry_type` `SETTLEMENT` is created in `ACCRUED` with `amount_cents` equal to the signed `settlement_amount_cents` — an `EMPLOYEE_DEBIT` therefore yields a negative entry — with `source_settlement_id` pointing at the settlement and `business_unit` copied from the assignment; the assignment's `ytd_chargeback_cents` increases by the settlement amount; and the overrun posture check re-runs.

### 3.9. Chargeback Posting, Repatriation, and Closure

Chargeback entries are never created directly — they exist only as cascade products of record posting and settlement execution, in `ACCRUED` status, and the list endpoint is the sole discovery channel for them. A `FinanceController` posts an accrued entry (`ACCRUED` → `POSTED`), which adds its `amount_cents` to the program's `total_posted_chargeback_cents`. Voiding compensates symmetrically and is permitted from either non-terminal state: voiding an `ACCRUED` entry — manually, or as the cascade from voiding a posted shadow payroll record — decrements the assignment's `ytd_chargeback_cents` by the entry's amount and re-runs the overrun posture check; voiding a `POSTED` entry additionally decrements the program's `total_posted_chargeback_cents`, again with the assignment decrement and the posture re-run. An entry in any other state rejects the void with `ERR_INVALID_STATE`; `POSTED` and `VOIDED` are the terminal states.

Repatriation unwinds the assignment in two controlled steps. Initiating repatriation is a `MobilityAdmin` action guarded by optimistic concurrency: the request must carry `expected_assignment_version` matching the assignment's current `version`, with a mismatch rejected as `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412) — an extension approval or a projection creation landing since the client's last read is exactly the staleness this guard catches, because the assignment is still `ACTIVE` and the transition would otherwise proceed on outdated terms. On success the assignment moves `ACTIVE` → `REPATRIATION_PENDING`, its `version` increments by one, and the cascade fires in two hops: the `ACTIVE` payroll split transitions to `SUSPENDED`, and that suspension in turn transitions every `DRAFT` shadow payroll record of the assignment to `VOIDED`. Completing repatriation requires every vendor engagement of the assignment to be `FILED` or `CLOSED` — otherwise `ERR_ENGAGEMENT_NOT_FINAL` — and moves the assignment `REPATRIATION_PENDING` → `REPATRIATED`, stamping `actual_end_date` with the current clock date and transitioning the `SUSPENDED` split to `TERMINATED`.

Closure is the final accounting gate. A `MobilityAdmin` closes a `REPATRIATED` assignment only when the ledger is fully settled: every settlement of the assignment must be `SETTLED`, and every chargeback entry must be `POSTED` or `VOIDED`; any outstanding item is rejected with `ERR_UNSETTLED_LEDGER`. A successful close moves the assignment to `CLOSED`, its terminal state alongside `CANCELLED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, approvals, posting, voiding — return `200 OK`, as do all reads. The table below is a summary only: request fields, preconditions, side effects, and cascades are specified in §3, cross-cutting rules in §2, and error identifiers in §5. All resources are peer collections under `/mobility`; the logical-clock control is mounted at the root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; sweeps certificate expiry | MobilityAdmin |
| POST | `/mobility/programs` | Create a mobility program | MobilityAdmin |
| GET | `/mobility/programs/{id}` | Get a program | Any |
| POST | `/mobility/employees` | Create an employee | MobilityAdmin |
| GET | `/mobility/employees/{id}` | Get an employee | Any |
| POST | `/mobility/allowance-policies` | Create an allowance policy | MobilityAdmin |
| GET | `/mobility/allowance-policies/{id}` | Get a policy | Any |
| GET | `/mobility/allowance-policies` | List allowance policies | Any |
| POST | `/mobility/assignments` | Create an assignment in DRAFT | MobilityAdmin |
| GET | `/mobility/assignments/{id}` | Get an assignment | Any |
| GET | `/mobility/assignments` | List assignments | Any |
| POST | `/mobility/assignments/{id}/submit` | Submit assignment for dual approval | MobilityAdmin |
| POST | `/mobility/assignments/{id}/approve-bu` | Business-unit approval (step 1) | BusinessUnitApprover |
| POST | `/mobility/assignments/{id}/reject-bu` | Business-unit rejection; reverts to DRAFT | BusinessUnitApprover |
| POST | `/mobility/assignments/{id}/approve-mobility` | Mobility approval (step 2) to ACTIVE | MobilityApprover |
| POST | `/mobility/assignments/{id}/reject-mobility` | Mobility rejection; reverts to DRAFT | MobilityApprover |
| POST | `/mobility/assignments/{id}/initiate-repatriation` | Initiate repatriation (OCC-guarded) | MobilityAdmin |
| POST | `/mobility/assignments/{id}/complete-repatriation` | Complete repatriation | MobilityAdmin |
| POST | `/mobility/assignments/{id}/close` | Close a repatriated assignment | MobilityAdmin |
| POST | `/mobility/assignments/{id}/cancel` | Cancel while DRAFT or in approval | MobilityAdmin |
| POST | `/mobility/compensation-packages` | Create the compensation package / assignment letter | PayrollSpecialist, MobilityAdmin |
| GET | `/mobility/compensation-packages/{id}` | Get a compensation package | Any |
| GET | `/mobility/compensation-packages` | List compensation packages | Any |
| POST | `/mobility/compensation-packages/{id}/submit` | Submit package for approval | PayrollSpecialist |
| POST | `/mobility/compensation-packages/{id}/approve` | Approve package | MobilityApprover |
| POST | `/mobility/compensation-packages/{id}/revise` | Return package to DRAFT for revision | PayrollSpecialist |
| POST | `/mobility/payroll-splits` | Create the host/home payroll split | PayrollSpecialist |
| GET | `/mobility/payroll-splits/{id}` | Get a payroll split | Any |
| GET | `/mobility/payroll-splits` | List payroll splits | Any |
| POST | `/mobility/payroll-splits/{id}/activate` | Activate a split | PayrollSpecialist |
| POST | `/mobility/payroll-splits/{id}/suspend` | Suspend an active split | PayrollSpecialist |
| POST | `/mobility/payroll-splits/{id}/resume` | Resume a suspended split | PayrollSpecialist |
| POST | `/mobility/payroll-splits/{id}/terminate` | Terminate a split | PayrollSpecialist |
| POST | `/mobility/shadow-payroll-records` | Create a DRAFT shadow payroll record | PayrollSpecialist |
| GET | `/mobility/shadow-payroll-records/{id}` | Get a shadow payroll record | Any |
| GET | `/mobility/shadow-payroll-records` | List shadow payroll records | Any |
| POST | `/mobility/shadow-payroll-records/{id}/post` | Post a DRAFT record | PayrollSpecialist |
| POST | `/mobility/shadow-payroll-records/{id}/void` | Void a DRAFT or POSTED record | PayrollSpecialist |
| POST | `/mobility/settlements` | Create a settlement (computes into CALCULATED) | PayrollSpecialist |
| GET | `/mobility/settlements/{id}` | Get a settlement | Any |
| GET | `/mobility/settlements` | List settlements | Any |
| POST | `/mobility/settlements/{id}/submit` | Submit settlement for finance review | PayrollSpecialist |
| POST | `/mobility/settlements/{id}/approve` | Approve settlement | FinanceController |
| POST | `/mobility/settlements/{id}/dispute` | Assignee disputes a pending settlement | Assignee |
| POST | `/mobility/settlements/{id}/recalculate` | Recompute a disputed settlement | PayrollSpecialist |
| POST | `/mobility/settlements/{id}/settle` | Settle an approved nonzero settlement | FinanceController |
| POST | `/mobility/vendor-engagements` | Engage a tax return preparation vendor | VendorCoordinator |
| GET | `/mobility/vendor-engagements/{id}` | Get a vendor engagement | Any |
| GET | `/mobility/vendor-engagements` | List vendor engagements | Any |
| POST | `/mobility/vendor-engagements/{id}/send-data` | Send the tax data package to the vendor | VendorCoordinator |
| POST | `/mobility/vendor-engagements/{id}/return-draft` | Vendor returns a draft return | TaxVendor |
| POST | `/mobility/vendor-engagements/{id}/start-review` | Begin internal review of the draft | VendorCoordinator |
| POST | `/mobility/vendor-engagements/{id}/request-revision` | Send the draft back for revision | VendorCoordinator |
| POST | `/mobility/vendor-engagements/{id}/accept` | Accept the reviewed draft | VendorCoordinator |
| POST | `/mobility/vendor-engagements/{id}/mark-filed` | Record the filed return with filed totals | VendorCoordinator |
| POST | `/mobility/vendor-engagements/{id}/close` | Close a filed engagement | VendorCoordinator |
| POST | `/mobility/certificates-of-coverage` | Apply for a certificate of coverage | VendorCoordinator |
| GET | `/mobility/certificates-of-coverage/{id}` | Get a certificate | Any |
| GET | `/mobility/certificates-of-coverage` | List certificates | Any |
| POST | `/mobility/certificates-of-coverage/{id}/submit` | Submit the totalization application | VendorCoordinator |
| POST | `/mobility/certificates-of-coverage/{id}/mark-issued` | Record issuance with the coverage window | VendorCoordinator |
| POST | `/mobility/certificates-of-coverage/{id}/mark-rejected` | Record rejection of the application | VendorCoordinator |
| POST | `/mobility/cost-projections` | Create a cost projection (OCC-guarded create-with-supersede) | FinanceController, MobilityAdmin |
| GET | `/mobility/cost-projections/{id}` | Get a cost projection | Any |
| GET | `/mobility/cost-projections` | List cost projections | Any |
| POST | `/mobility/extension-requests` | Request an assignment extension (OCC-guarded create-with-supersede) | MobilityAdmin |
| GET | `/mobility/extension-requests/{id}` | Get an extension request | Any |
| GET | `/mobility/extension-requests` | List extension requests | Any |
| POST | `/mobility/extension-requests/{id}/approve` | Approve an extension | BusinessUnitApprover |
| POST | `/mobility/extension-requests/{id}/decline` | Decline an extension request | BusinessUnitApprover |
| GET | `/mobility/chargeback-entries/{id}` | Get a chargeback entry | Any |
| GET | `/mobility/chargeback-entries` | List chargeback entries | Any |
| POST | `/mobility/chargeback-entries/{id}/post` | Post an accrued chargeback entry | FinanceController |
| POST | `/mobility/chargeback-entries/{id}/void` | Void an accrued or posted chargeback entry | FinanceController |

## 5. Error Code Catalogue

Trigger conditions for each error are specified where the rule lives in §2 and §3; this catalogue is the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_ASSIGNMENT_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_PACKAGE_NOT_APPROVED` | 409 Conflict |
| `ERR_SPLIT_NOT_ACTIVE` | 409 Conflict |
| `ERR_COC_REQUIRED` | 409 Conflict |
| `ERR_COC_COVERAGE_GAP` | 409 Conflict |
| `ERR_VENDOR_NOT_FILED` | 409 Conflict |
| `ERR_ASSIGNMENT_OVERLAP` | 409 Conflict |
| `ERR_POLICY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_EXTENSION_NOT_FORWARD` | 422 Unprocessable Entity |
| `ERR_MAX_DURATION_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PERIOD_OUTSIDE_ASSIGNMENT` | 422 Unprocessable Entity |
| `ERR_SPLIT_SUM_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PAYROLL_PERIOD` | 409 Conflict |
| `ERR_PER_DIEM_DAYS_INVALID` | 422 Unprocessable Entity |
| `ERR_PER_DIEM_ANNUAL_CAP_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_PACKAGE` | 409 Conflict |
| `ERR_DUPLICATE_SPLIT` | 409 Conflict |
| `ERR_DUPLICATE_ENGAGEMENT` | 409 Conflict |
| `ERR_COC_ALREADY_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_SETTLEMENT` | 409 Conflict |
| `ERR_COST_OVERRUN_BLOCKED` | 409 Conflict |
| `ERR_ENGAGEMENT_NOT_FINAL` | 409 Conflict |
| `ERR_UNSETTLED_LEDGER` | 409 Conflict |
