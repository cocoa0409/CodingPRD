# Multistate Payroll Tax API — Product Requirements Document

## 1. Introduction

Operating payroll across multiple U.S. states is a problem of layered arithmetic and segregated trust. A single biweekly pay cycle must simultaneously evaluate federal income tax withholding from a per-employee W-4 form, state income tax for jurisdictions as different as `STATE:CA` (graduated brackets) and `STATE:TX` (no income tax at all), local income tax for cities like `LOCAL:NYC` and `LOCAL:SF`, Social Security capped at a wage-base, base Medicare on every dollar, an additional Medicare surcharge above a yearly threshold, and any court-ordered wage garnishments — each computed in a fixed sequence so that the dollar of disposable earnings is calculated once and consumed only once. At month end, every withheld bucket is reconciled against a per-jurisdiction `Remittance` row and then transmitted to the corresponding tax authority.

This service exists because the surface area for arithmetic and policy errors is enormous and the cost of getting any one of them wrong is concrete: a misapplied bracket, a missed `SUPERSEDED` W-4, a `CHILD_SUPPORT` order accidentally ranked below a `CREDITOR` order, or an over-remittance to `STATE:CA` all produce real-world money movements that someone — the employee, the IRS, or a court — will later contest. The API encodes both the calculation pipeline and the trust boundary between the staff who *prepare* a payroll run, the staff who *approve* and pay it, and the compliance officer who closes the period and remits the funds. Strict segregation of duties at the approval step is not a configuration choice; it is a precondition.

A secondary goal is operational determinism. Because some computations (the per-paycheck percentage method versus the year-end reconciled bracket method; the provisional running accrual versus the reconciled month-end aggregate) intentionally produce different numbers from identical inputs, every variant switch is exposed as an explicit flag rather than implicit detection. Likewise, ties in the garnishment waterfall are broken by `priority_rank`, then `served_on`, then `created_at` — never by random ordering, and never by `id`. The downstream tester, the auditor, and the engineer reading this document must all arrive at the same cents.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must include two request headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the principal is acting. If either header is missing, or `X-User-Role` does not match a known role, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP status 401. If both headers are present but the named role lacks permission for the requested endpoint, the request is rejected with `ERR_FORBIDDEN` and HTTP status 403.

The system recognizes exactly five roles: `HRClerk`, `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, and `PlatformAdmin`. For all five roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it on resources where a transition writes it (for example, `prepared_by_user_id` and `approved_by_user_id` on `PaycheckRun`), but it never compares `X-User-ID` to any entity's `id`. Ownership in this domain is enforced by segregation-of-duties checks against recorded operator ids, not by entity-backed identity.

`HRClerk` manages employees and W-4 forms but cannot create or approve paycheck runs. `PayrollPreparer` creates paycheck runs and the paychecks attached to them. `PayrollApprover` approves, rejects, pays, and (jointly with `ComplianceOfficer`) voids paycheck runs; segregation of duties forbids the approver from being the same operator who prepared the run. `ComplianceOfficer` owns garnishment orders, closes accrual periods, remits to tax authorities, and may also void paid runs as a compensating action. `PlatformAdmin` seeds tax-rate tables and the test-driving capabilities, and may read everything.

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

List endpoints accept two optional query parameters: `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; out-of-range values are rejected as malformed requests. `offset` defaults to 0 and must be non-negative. The default sort order for every list endpoint is by `created_at` ascending. Each list response includes `limit`, `offset`, `total_count`, and `has_more` in its `meta` block so callers can paginate forward without an off-by-one.

### 2.4. Common Resource Properties

Every primary resource — `Employee`, `W4Form`, `PaycheckRun`, `Paycheck`, `GarnishmentOrder`, and `Remittance` — carries an `id`, a `created_at`, an `updated_at`, and a `version`. The `id` is a server-minted UUID and carries no type prefix. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` is a non-negative integer that begins at 0 on creation and increments by exactly 1 on every successful state-changing mutation of the row, including cascade-driven updates to the row from a sibling entity's transition.

Two scaffold entities deliberately carry only `id` and `created_at`: `GarnishmentDeduction` (a child of `Paycheck`, written once when the parent paycheck transitions to `PAID`) and `TaxRateTable` (configuration data that is replaced rather than mutated in place). Neither of these two entity types exposes `updated_at`, and neither exposes `version`.

### 2.5. Path Hierarchy and Nested Resource Lookup

Nested URL paths are validated left-to-right. For example, the listing under a parent paycheck run resolves the run identifier first; if the run id does not exist, the response is `ERR_NOT_FOUND` and the child collection is never consulted. The same left-to-right rule applies to the sub-resource collection that enumerates garnishment deductions under a paycheck.

Foreign keys in request bodies — `employee_id`, `paycheck_run_id`, `garnishment_order_id`, and a non-null `supersedes_w4_id` — must each resolve to an existing entity. A missing FK is rejected with `ERR_FK_NOT_FOUND` (HTTP 404). This is a distinct condition from `ERR_NOT_FOUND`, which is reserved for unresolvable path ids.

### 2.6. Validation Priority Ordering

A single request may trigger several rejections; the response always reflects the **first** failing rule in priority order, so test fixtures can construct exactly one failing condition at a time. The priority sequence is fixed: authentication (`ERR_UNAUTHENTICATED`) comes first, then authorization (`ERR_FORBIDDEN`), then path-id existence (`ERR_NOT_FOUND`), then foreign-key existence (`ERR_FK_NOT_FOUND`), then state-machine guards (`ERR_INVALID_STATE`), then employee-not-active blocking (`ERR_EMPLOYEE_NOT_ACTIVE`), then segregation-of-duties (`ERR_SOD_VIOLATION`), then the single-order CCPA intake cap (`ERR_GARNISHMENT_EXCEEDS_CCPA`), then the no-W-4-on-file referential check (`ERR_NO_W4_ON_FILE`), then supersede-target validity (`ERR_SUPERSEDE_TARGET_INVALID`), then pay-period interval overlap (`ERR_PAY_PERIOD_OVERLAP`), then garnishment aggregate-capacity (`ERR_GARNISHMENT_AGGREGATE_CAP`), then the exact-amount remittance check (`ERR_REMITTANCE_AMOUNT_MISMATCH`), then the open-run-blocks-close period guard (`ERR_OPEN_RUN_BLOCKS_CLOSE`), then OCC stale-version rejection (`ERR_STALE_VERSION`), and finally generic shape validation (`ERR_INVALID_REQUEST`). Implementations must evaluate guards in this order; in particular, the `ERR_OPEN_RUN_BLOCKS_CLOSE` check sits **below** the generic state-machine guard so that a `Remittance` not currently in `ACCRUING` produces `ERR_INVALID_STATE` rather than the open-run message.

### 2.7. Optimistic Concurrency on Remittance

The `Remittance` row is the single point in the system where stale-read protection is enforced via optimistic concurrency. The `POST /remittances/{id}/remit` request body must include `expected_remittance_version`. The server compares that value against the target remittance's current `version`. If they differ, the remit is rejected with `ERR_STALE_VERSION` and HTTP status 412 — even if every other precondition would pass. A mismatch occurs when, after a client reads the remittance row, a late-arriving cascade (for example, a `Paycheck` transitioning to `PAID` or `VOID` during the accrual window, or the act of closing the period itself) advanced `Remittance.version`; the client is then submitting against a view the server has moved past. No other endpoint in this API takes a `version` field on input; concurrent edits elsewhere are serialized purely by entity-state preconditions.

### 2.8. Precision, Rounding, and the Cents Discipline

Money in this system is exclusively integer cents, never decimal. Hour fields are integer hundredths of an hour, named with the `_e2` suffix (so `4000` means 40.00 hours). Every multiplicative step uses **floor division** — integer division that discards the fractional remainder — and the rounding order within each calculation is fixed and pinned (see §3 for the per-calculation order). Rates expressed in **basis points** are integers where one basis point is one one-hundredth of a percent (so the Social Security rate `SS_RATE_BASIS_POINTS = 620` is 6.20%, and the federal supplemental flat rate `2200` is 22.00%). The garnishment waterfall in particular rounds **per-order first** and then sums the rounded amounts; reversing the order to sum-then-round changes cents at boundary inputs and is forbidden.

### 2.9. Cascading Side Effects and Hierarchical Consistency

State transitions in this system cascade across more than one entity at a time. When a `PaycheckRun` is paid, each child `Paycheck` transitions from `PENDING` to `PAID`; each affected `Employee`'s year-to-date accumulators update; each `GarnishmentOrder` debited by a `GarnishmentDeduction` has its `balance_remaining_cents` reduced (and possibly transitions `ACTIVE → SATISFIED`); and the relevant `Remittance` rows have their `accrued_cents` incremented. The reverse cascade fires when a `PaycheckRun` is voided: children flip to `VOID`, year-to-date accumulators reverse, satisfied garnishments revive to `ACTIVE`, and accruals subtract. Every entity touched by a cascade bumps its own `version` and refreshes `updated_at` along with the in-row business changes.

### 2.10. Test-Driving Capabilities

Two endpoints exist solely to make the boundary-precision test plan tractable. A clock-advance capability lets an operator set the server's notion of NOW_UTC for the next transitions; a YTD-seed capability lets an operator directly write an `Employee`'s `ytd_wages_cents`, `ytd_fed_withheld_cents`, `ytd_ss_wages_cents`, and `ytd_medicare_wages_cents` to specific cents values so that a single subsequent paycheck can be driven across (for instance) the additional-Medicare threshold without authoring 26 prior runs. Both endpoints are restricted to `PlatformAdmin`. The YTD-seed capability refreshes the employee's `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Onboarding an Employee and Filing the First W-4

An `HRClerk` registers a new employee by submitting a `full_name`, the two-letter `work_state_code` (one of `CA`, `NY`, `TX`, or `WA`) for the location where work is performed, the two-letter `residence_state_code` (drawn from the same set and used for reciprocity-edge cases on state withholding), and an optional `locality_code` (one of `NONE`, `NYC`, or `SF`; defaults to `NONE` when the work location has no local income tax). The newly created employee enters `ACTIVE` status, and every year-to-date accumulator — `ytd_wages_cents`, `ytd_fed_withheld_cents`, `ytd_ss_wages_cents`, and `ytd_medicare_wages_cents` — is initialized to zero. An employee can subsequently be moved among `ACTIVE`, `ON_LEAVE`, and `TERMINATED` via a status update by either an `HRClerk` or a `PlatformAdmin`, who submits the new `status` as the only input field.

Before any paycheck can be cut for an employee, that employee must have a filed W-4. The W-4 creation payload identifies the employee through `employee_id`, names the calendar `tax_year` (which must be `2025` or `2026`), and declares an IRS `filing_status` from the set `SINGLE`, `MARRIED_JOINT`, or `HEAD_OF_HOUSEHOLD`. The optional dollar-valued inputs all default to zero: `dependents_amount_cents` (the Step-3 dependents credit in cents), `other_income_cents` (Step-4(a)), `deductions_cents` (Step-4(b)), and `extra_withholding_cents` (Step-4(c) extra per-paycheck withholding). The form is created in `DRAFT`, with `filed_at` initially null. Either an `HRClerk` or a `PayrollPreparer` may create the draft; the same two roles may file it. Creation is rejected with `ERR_EMPLOYEE_NOT_ACTIVE` when the named employee is in `TERMINATED` status — only `ACTIVE` and `ON_LEAVE` employees may have new W-4 paperwork drafted or filed.

Filing the W-4 advances `W4Form.status` from `DRAFT` to `FILED`, stamps `filed_at` with the current UTC instant, and is allowed only when the form is currently in `DRAFT`, the named employee is in `ACTIVE` or `ON_LEAVE` status, and `filing_status` is set on the form. A violation of the state guard surfaces as `ERR_INVALID_STATE`; an attempt to file for a `TERMINATED` employee surfaces as `ERR_EMPLOYEE_NOT_ACTIVE`. Filing also fires two cascade hops: if the new W-4 carries a `supersedes_w4_id` pointing at a prior form, that prior form is immediately transitioned from `FILED` to `SUPERSEDED`; and any `PENDING` paycheck for this employee under a `PaycheckRun` still in `DRAFT` has its provisional federal withholding recomputed in place. An employee's W-4 history therefore cycles `DRAFT → FILED → SUPERSEDED` across amendments — there is one currently-effective filed W-4 at a time per (employee, tax_year), and `SUPERSEDED` is terminal for any individual form.

A supersede chain has its own integrity rules. When `supersedes_w4_id` is non-null on either creation or filing, the referenced prior form must currently be in `FILED` status, must belong to the same `employee_id`, and must cover the same `tax_year`. Any deviation — wrong status, wrong employee, mismatched year — is rejected with `ERR_SUPERSEDE_TARGET_INVALID`. The first W-4 of a given tax year for an employee leaves `supersedes_w4_id` null.

### 3.2. The Tax-Rate Reference Data

Withholding computations consult a configuration table the `PlatformAdmin` seeds: each row carries a `jurisdiction` string (one of `FEDERAL`, `STATE:CA`, `STATE:NY`, `STATE:TX`, `STATE:WA`, `LOCAL:NYC`, or `LOCAL:SF`), a `tax_year`, a `filing_status` (the federal row stores the filing variant; state and local rows uniformly use `SINGLE`), an ordered `brackets_json` array describing the graduated bracket schedule as `[{lower_cents, upper_cents_or_null, rate_basis_points}]`, and a `supplemental_flat_basis_points` used for supplemental-wage forms. `STATE:TX` and `STATE:WA` are deliberately seeded with an empty brackets list — these states levy no income tax, and state withholding evaluates to zero for any employee whose `work_state_code` is one of them. The list endpoint accepts `jurisdiction`, `tax_year`, and `filing_status` filters.

### 3.3. Composing a Paycheck Run

A `PayrollPreparer` opens a new run by submitting the inclusive `pay_period_start` and `pay_period_end` timestamps and the disbursement `pay_date`. The new run is created in `DRAFT`; the operator's `X-User-ID` is captured as `prepared_by_user_id`, `approved_by_user_id` is left null, and `total_gross_cents` is zero until paychecks are attached. The `pay_date` carries weight beyond record-keeping: its year-month component (the first seven characters, e.g. `2025-04`) is the bucket against which monthly remittances will be grouped, and its calendar year drives which `TaxRateTable` row is consulted for every child paycheck's federal, state, and local computation.

A pay-period collision check protects the system from overlapping runs. If the proposed interval `[pay_period_start, pay_period_end]` (closed on both ends — a point overlap at the boundary counts as a conflict, so `start == prior.end` is a conflict) collides with any non-`VOID` `PaycheckRun` already holding a `Paycheck` for one of the to-be-added employees, the create is rejected with `ERR_PAY_PERIOD_OVERLAP`. The same check applies when a paycheck is later added to the run for an employee whose other runs would now overlap.

Adding a paycheck to a `DRAFT` run is the moment all the withholding arithmetic fires. The preparer submits the parent `paycheck_run_id`, the `employee_id` of the wage recipient, and the `pay_type` (one of `REGULAR`, `OVERTIME`, `DOUBLE`, or `RETRO`). Depending on the form: a `REGULAR` paycheck supplies `regular_hours_e2` and `hourly_rate_cents`; an `OVERTIME` paycheck supplies `overtime_hours_e2` and `hourly_rate_cents`; a `DOUBLE` paycheck supplies `double_hours_e2` and `hourly_rate_cents`; a `RETRO` paycheck supplies `retro_amount_cents` as a flat retroactive amount. At approval time, the run must contain at least one paycheck and every paycheck's `pay_type` must match its hours fields — `REGULAR` requires `regular_hours_e2` greater than zero, `OVERTIME` requires `overtime_hours_e2` greater than zero, `DOUBLE` requires `double_hours_e2` greater than zero, and `RETRO` requires `retro_amount_cents` greater than zero — otherwise approval is rejected with `ERR_INVALID_STATE`.

Two further preconditions guard the paycheck create itself. The employee must currently be in `ACTIVE` or `ON_LEAVE` status (a `TERMINATED` employee yields `ERR_EMPLOYEE_NOT_ACTIVE`), and the employee must have a `FILED` W-4 covering the parent run's `pay_date`-year (no filed W-4 yields `ERR_NO_W4_ON_FILE`). When multiple `FILED` W-4 forms exist for the same employee and tax year because of supersession chains, the "currently effective" form is the one with the most recent `filed_at` timestamp; ties are broken by `created_at` ascending.

### 3.4. The Withholding Pipeline (Per Paycheck)

Creating a paycheck advances `Paycheck.status` to `PENDING` and runs the withholding pipeline in a fixed order: gross wages, then federal, then state, then local, then Social Security, then base Medicare, then additional Medicare, then garnishment waterfall, then net pay. Every output is integer cents.

**Gross wages.** The output `gross_wages_cents` depends on `pay_type`. For a `REGULAR` paycheck, gross is the product of `regular_hours_e2` and `hourly_rate_cents` divided by 100 with the remainder discarded (floor division). For an `OVERTIME` paycheck, the overtime multiplier is one-and-a-half: gross is `overtime_hours_e2` multiplied by `hourly_rate_cents`, multiplied by 3, then floor-divided by 200. For a `DOUBLE` paycheck, the multiplier is two: gross is `double_hours_e2` multiplied by `hourly_rate_cents`, multiplied by 2, then floor-divided by 100. For a `RETRO` paycheck, gross is simply `retro_amount_cents`. No rounding step crosses these branches — each branch performs its own integer-floor division.

**Federal withholding — provisional variant.** Provisional federal withholding (`fed_withheld_cents`) is computed at paycheck creation by the per-paycheck percentage method against the currently-effective `FILED` W-4 for the employee and the paycheck's `pay_date`-year (selected as described in §3.3 — most recent `filed_at`, tie-break `created_at` ascending). The procedure projects the current paycheck's gross to an annual figure by multiplying it by `PAY_PERIODS_PER_YEAR`, which is 26 (biweekly). It then computes an adjusted annual figure as the projected annual wages plus `other_income_cents`, minus `deductions_cents`, minus the standard deduction for the filer's `filing_status` — `1,460,000` cents (\$14,600.00) for `SINGLE`, `2,920,000` cents (\$29,200.00) for `MARRIED_JOINT`, and `2,190,000` cents (\$21,900.00) for `HEAD_OF_HOUSEHOLD`. The federal `brackets_json` for that tax year and filing status is then applied: for each bracket where the adjusted annual figure exceeds the bracket's `lower_cents`, take the smaller of the adjusted annual figure and the bracket's `upper_cents_or_null` (treating null as infinity), subtract the `lower_cents`, multiply by the bracket's `rate_basis_points`, and floor-divide by 10000; the per-bracket results are summed to form the annual tax in cents. The annual tax is floor-divided by `PAY_PERIODS_PER_YEAR` to get the provisional per-paycheck tax. From this per-paycheck tax, the system subtracts `dependents_amount_cents` floor-divided by `PAY_PERIODS_PER_YEAR`, then adds `extra_withholding_cents`, then floors the result at zero. The order of operations is fixed: floor-divide per bracket first, sum, then floor-divide by pay periods, then dependents subtraction, then extra-withholding addition, then floor at zero. For `OVERTIME`, `DOUBLE`, and `RETRO` paychecks the percentage-method branch is skipped: the provisional federal withholding is the gross wages multiplied by the federal row's `supplemental_flat_basis_points` and floor-divided by 10000, plus `extra_withholding_cents`, floored at zero.

**Federal withholding — reconciled variant.** The reconciled variant runs only when the pay request that advances a run from `APPROVED` to `PAID` carries `is_year_end_run` set to true in its request body. It exists because per-paycheck annualization and exact-bracket aggregation can produce different cents for the same employee; the reconciled variant uses the employee's actual year-to-date wages rather than a projection from a single paycheck, and so it is the authoritative number for the final pay period of the year. The reconciliation runs against each child paycheck **before** the year-to-date increments apply, using the pre-payment year-to-date as its baseline. Concretely, `annual_wages_actual` is `Employee.ytd_wages_cents` *before* this paycheck plus this paycheck's `gross_wages_cents`; the adjusted annual figure is `annual_wages_actual` plus `other_income_cents`, minus `deductions_cents`, minus the same standard deduction for `filing_status` as the provisional variant; the bracket-summed annual tax is computed identically to the provisional bracket math; then `dependents_amount_cents` is subtracted; then `extra_withholding_cents` is added after multiplying it by `PAY_PERIODS_PER_YEAR`; finally `fed_withheld_cents` for this paycheck is the larger of zero and that adjusted annual tax minus `Employee.ytd_fed_withheld_cents` *before* this paycheck. The reconciled `fed_withheld_cents` then replaces the provisional value on each child paycheck for the rest of the cascade. When `is_year_end_run` is false or omitted, `fed_withheld_cents` stays at the provisional value set at paycheck creation. There is no implicit year-end detection — the variant switch is a single explicit flag.

**State and local withholding.** The system makes two passes through the rate-table for each paycheck: one for `STATE:<work_state_code>` and one for `LOCAL:<locality_code>`. When `locality_code` is `NONE`, the local pass is skipped and `local_withheld_cents` is zero. For `STATE:TX` and `STATE:WA`, the state rate table's brackets are empty and `state_withheld_cents` is zero. Otherwise: for a `REGULAR` paycheck, the per-pay tax is the bracket-summed tax over `gross_wages_cents` against the state (or local) `brackets_json` for the paycheck's `pay_date`-year (using `SINGLE` as the filing-status key), computed by the same floor-divide-per-bracket-then-sum rule as the federal provisional variant; for an `OVERTIME`, `DOUBLE`, or `RETRO` paycheck, the per-pay tax is `gross_wages_cents` multiplied by the table's `supplemental_flat_basis_points` then floor-divided by 10000. In both cases the result is floored at zero before being written to `state_withheld_cents` or `local_withheld_cents`.

**Social Security withholding.** The Social Security computation is capped at a yearly wage base of `SS_WAGE_BASE_CENTS = 16,860,000` cents (\$168,600.00). The remaining capacity is the larger of zero and that wage base minus `Employee.ytd_ss_wages_cents` at the moment of computation. The taxable portion of this paycheck is the smaller of `gross_wages_cents` and the remaining capacity; `ss_withheld_cents` is that taxable portion multiplied by `SS_RATE_BASIS_POINTS = 620` (6.20%) and floor-divided by 10000. When the employee's year-to-date Social Security wages have already reached the wage base, the remaining capacity is zero and `ss_withheld_cents` is zero.

**Base Medicare.** `medicare_withheld_cents` is `gross_wages_cents` multiplied by `MEDICARE_RATE_BASIS_POINTS = 145` (1.45%) and floor-divided by 10000. Base Medicare is uncapped.

**Additional Medicare.** The additional Medicare surcharge — `addl_medicare_cents` — applies at 0.9% (`ADDL_MEDICARE_RATE_BASIS_POINTS = 90`) on the portion of Medicare wages that exceed `ADDL_MEDICARE_THRESHOLD_CENTS = 20,000,000` cents (\$200,000.00) year-to-date. The computation uses both the prior YTD Medicare wages and the new YTD figure that includes this paycheck. The taxable portion above the threshold is computed as the larger of zero and the new YTD minus the threshold, minus the larger of zero and the prior YTD minus the threshold. `addl_medicare_cents` is then that taxable portion multiplied by the additional-Medicare rate and floor-divided by 10000. The boundary semantics are strict: a paycheck that pushes the year-to-date from \$199,999.99 to exactly \$200,000.00 contributes zero cents (the threshold dollar itself is not yet above), and a paycheck that pushes the year-to-date to \$200,000.01 contributes the 0.9% surcharge on the \$0.01 fraction — which, under floor division, also yields zero cents.

**Net pay.** `net_pay_cents` is `gross_wages_cents` minus the sum of `fed_withheld_cents`, `state_withheld_cents`, `local_withheld_cents`, `ss_withheld_cents`, `medicare_withheld_cents`, `addl_medicare_cents`, and `garnishment_total_cents`, with the result floored at zero — net pay cannot go negative even if the sum of withholdings and garnishments would otherwise exceed gross.

### 3.5. Garnishment Orders and the Waterfall

A `ComplianceOfficer` registers a garnishment order by submitting the affected employee through `employee_id`, the `order_type` (one of `CHILD_SUPPORT`, `IRS_LEVY`, `STUDENT_LOAN`, or `CREDITOR`), the maximum cents deductible per pay week for this order through `weekly_cap_cents`, the total amount the order ultimately requires through `original_balance_cents`, and the `served_on` date the order was served on the employer. The new order is created in `ACTIVE` status; `balance_remaining_cents` starts equal to `original_balance_cents`, and a `priority_rank` is pinned at creation from the order's type: `CHILD_SUPPORT` is rank 1, `IRS_LEVY` is rank 2, `STUDENT_LOAN` is rank 3, and `CREDITOR` is rank 4. `priority_rank` is immutable thereafter; later changes to the order's type are not modeled.

Two intake-time safety checks guard the new order. The first is a single-order CCPA ceiling: a `CHILD_SUPPORT` order whose `weekly_cap_cents` alone would exceed the CCPA 50% cap (`CCPA_MAX_BASIS_POINTS_WITH_CHILD_SUPPORT = 5000` basis points, i.e. 50.00%) of the employee's most recent `PAID` `Paycheck.gross_wages_cents` is rejected at intake with `ERR_GARNISHMENT_EXCEEDS_CCPA`. The second is an aggregate-capacity check: the sum of `weekly_cap_cents` over all currently-`ACTIVE` `GarnishmentOrder` rows for the employee, plus this new order's `weekly_cap_cents`, must not exceed the CCPA-derived aggregate capacity. The two checks have **distinct interval semantics** — the first targets a single new order against an existing-pay reference, the second targets a sum across the employee's active orders — and they surface as different error ids. An aggregate-capacity violation surfaces as `ERR_GARNISHMENT_AGGREGATE_CAP`.

The `ComplianceOfficer` may move an `ACTIVE` order to `SUSPENDED` by suspending it (rejected with `ERR_INVALID_STATE` if the order is not currently `ACTIVE`); and may move a `SUSPENDED` order back to `ACTIVE` by reactivating it (rejected with `ERR_INVALID_STATE` if not currently `SUSPENDED`). A `SUSPENDED` order is skipped by the waterfall on every subsequent paycheck until it is reactivated. The `ComplianceOfficer` may also release an order outright, transitioning to `RELEASED` from any of `ACTIVE`, `SATISFIED`, or `SUSPENDED`; `RELEASED` is the terminal court-ordered release and is distinct from the auto-`SATISFIED` state reached when an order's balance hits zero through normal deductions. An order can also reach `SATISFIED` automatically when a paycheck transition advances a `GarnishmentDeduction` against it that brings `balance_remaining_cents` to zero; and a `SATISFIED` order can revive to `ACTIVE` when a paycheck transition voids that deduction and raises the balance above zero again. These last two transitions are system-driven and have no operator endpoint.

**The waterfall — fixed evaluation order, fixed rounding order.** Each paycheck's garnishment computation runs after gross and all tax withholdings have been computed. First, disposable earnings — `gross_wages_cents` minus the sum of `fed_withheld_cents`, `state_withheld_cents`, `local_withheld_cents`, `ss_withheld_cents`, `medicare_withheld_cents`, and `addl_medicare_cents` — is computed. Second, the paycheck cap is `disposable_earnings` multiplied by the CCPA basis-points limit and floor-divided by 10000. The system selects between two basis-point limits based on whether any `CHILD_SUPPORT` order is currently `ACTIVE` for the employee at compute time: when at least one `ACTIVE` `CHILD_SUPPORT` order exists, the cap is 50.00% (`CCPA_MAX_BASIS_POINTS_WITH_CHILD_SUPPORT = 5000`); otherwise, the cap is 25.00% (`CCPA_MAX_BASIS_POINTS_CREDITOR_ONLY = 2500`). Third, the candidate orders are all `ACTIVE` garnishments for this employee sorted by `priority_rank` ascending, then `served_on` ascending, then `created_at` ascending. The tie-break tail is fixed: `served_on` earlier wins within the same `priority_rank`, and `created_at` earlier wins within the same `served_on`. The `id` is never used as a tie-breaker. Fourth, the system walks the sorted list in order while a `remaining` counter tracks the unconsumed paycheck cap (initialized to the paycheck cap); for each order, the per-order amount is the smallest of `weekly_cap_cents`, the order's current `balance_remaining_cents`, and the `remaining` cap. If the per-order amount is positive, a `GarnishmentDeduction` is recorded against the paycheck with `garnishment_order_id` and `amount_cents` set, and `remaining` is reduced by that amount; if `remaining` reaches zero, the walk stops and any orders later in the sort are skipped on this paycheck. Fifth, `garnishment_total_cents` is the sum of the per-order amounts. **The rounding order is pinned: per-order amounts are computed (and floor-divided) before any summation, then summed.** Reversing the order to sum-then-round produces different cents at boundary inputs and is not permitted.

`GarnishmentDeduction` rows are minimal child records: `paycheck_id`, `garnishment_order_id`, `amount_cents`, and `applied_at`. The deduction is created when the parent paycheck is created and the waterfall fires, but its `applied_at` is stamped only when the parent `Paycheck` transitions from `PENDING` to `PAID`. `GarnishmentDeduction` carries only `id` and `created_at` as common fields — no `updated_at`, no `version` — and it is never edited in place; reversals happen through the void cascade on the parent paycheck.

### 3.6. Approval, Payment, and the Void Compensating Action

A `PayrollPreparer` finalizes the run's contents and the `PayrollApprover` advances it: from `DRAFT` to `APPROVED`, from `APPROVED` back to `DRAFT` for correction (a branching revert), from `APPROVED` to `PAID` for actual disbursement, and (only in a compensating-action posture) from `PAID` to `VOID`. Approval has four preconditions evaluated in order. The run must currently be in `DRAFT`; the approver's `X-User-ID` must differ from the run's `prepared_by_user_id` (segregation of duties); the run must contain at least one child paycheck; and every child paycheck's `pay_type` must match its hours fields per §3.3. A preparer who attempts to approve their own run is rejected with `ERR_SOD_VIOLATION` and HTTP 403. State-guard or content-guard failures surface as `ERR_INVALID_STATE`. The successful approval transitions `PaycheckRun.status` to `APPROVED` and records `approved_by_user_id` as `X-User-ID`. Rejecting an `APPROVED` run reverts `PaycheckRun.status` to `DRAFT` and clears `approved_by_user_id` to null; rejection is rejected with `ERR_INVALID_STATE` when the run is not currently `APPROVED`.

Paying an `APPROVED` run is the cascade-heavy transition. The request optionally carries `is_year_end_run`; when true, the reconciled federal-withholding variant from §3.4 replaces each child paycheck's `fed_withheld_cents` *before* the year-to-date increments apply (the reconciled formula explicitly uses pre-payment YTD as its baseline). When false or omitted, `fed_withheld_cents` is left at the provisional value. Each child `Paycheck` then transitions from `PENDING` to `PAID`. For each child paycheck, the employee's accumulators advance: `ytd_wages_cents` increases by that paycheck's `gross_wages_cents`; `ytd_fed_withheld_cents` increases by the paycheck's post-reconciliation `fed_withheld_cents`; `ytd_ss_wages_cents` increases by the smaller of the paycheck's gross and the remaining Social Security capacity (the wage base minus the prior YTD figure); and `ytd_medicare_wages_cents` increases by the paycheck's gross. For each `GarnishmentDeduction` on each child paycheck, the corresponding `GarnishmentOrder` has its `balance_remaining_cents` reduced by the deduction's `amount_cents`; if that balance reaches zero, the order transitions from `ACTIVE` to `SATISFIED`. For each tax bucket on each child paycheck — federal income, FICA, state income, local income — the relevant `Remittance` row's `accrued_cents` is incremented by that bucket's value for the `(period_month, jurisdiction, tax_type)` tuple, creating the remittance row if it does not yet exist; the row remains in `ACCRUING` through this cascade. Each child paycheck's `applied_at` is set on its `GarnishmentDeduction` children to the current UTC instant. Paying a run that is not currently `APPROVED`, or a run whose child paychecks are not all in `PENDING`, is rejected with `ERR_INVALID_STATE`.

Voiding a `PAID` run is a compensating action that runs every effect from the pay cascade in reverse. Each child `Paycheck` transitions from `PAID` to `VOID`. For each child paycheck, the employee's year-to-date accumulators are reversed by the same amounts they were incremented by. For each `GarnishmentDeduction`, `balance_remaining_cents` on the corresponding order is increased back by `amount_cents`; if the order was previously `SATISFIED` and is now above zero again, it reverts to `ACTIVE`. For each tax bucket, the relevant `Remittance.accrued_cents` is subtracted back by that bucket's value. The void is rejected with `ERR_INVALID_STATE` when the run is not currently `PAID`, **or** when any `Remittance` whose `period_month` matches the run's `pay_date`-month is already in `REMITTED` status for any jurisdiction — once funds have been remitted to the tax authority, the run is no longer reversible inside this system. Voiding is shared between `PayrollApprover` and `ComplianceOfficer`.

### 3.7. Closing the Month and Remitting to the Tax Authority

The remittance lifecycle has three statuses — `ACCRUING`, `RECONCILED`, and `REMITTED` — and tracks per-jurisdiction, per-bucket monthly liability through `period_month` (formatted as `YYYY-MM`), `jurisdiction` (one of `FEDERAL`, `STATE:CA`, `STATE:NY`, `STATE:TX`, `STATE:WA`, `LOCAL:NYC`, or `LOCAL:SF`), and `tax_type` (one of `FED_INCOME`, `FICA_EMPLOYEE`, `STATE_INCOME`, or `LOCAL_INCOME`). The `period_month` of a remittance row is derived from the parent paycheck run's `pay_date` (specifically its year-month prefix), and a remittance row is created on first need during a pay cascade rather than ahead of time. While the row is `ACCRUING`, `accrued_cents` runs as a provisional accumulator — incremented by each `Paycheck`'s relevant bucket when the paycheck transitions to `PAID`, and decremented when a paycheck transitions to `VOID` (the bucket-by-bucket reversal). `reconciled_cents` and `paid_cents` are both zero throughout the accruing phase.

A `ComplianceOfficer` closes the period for a remittance row to advance `Remittance.status` from `ACCRUING` to `RECONCILED`. The close-period transition has three preconditions: the row must currently be in `ACCRUING`; every `PaycheckRun` whose `pay_date`-month equals the remittance's `period_month` must be in `PAID` or `VOID` (no `DRAFT` or `APPROVED` runs may leak into a closed month); and no `Paycheck` in `PENDING` status whose parent run's `pay_date`-month equals this `period_month` may exist. The first two are enforced together: a row not in `ACCRUING` yields `ERR_INVALID_STATE`, and an open paycheck run for the same month yields `ERR_OPEN_RUN_BLOCKS_CLOSE` (HTTP 409). The priority ordering in §2.6 ensures the state guard fires before the open-run guard so that an already-`RECONCILED` or already-`REMITTED` row is reported as a state violation rather than as an open-run problem. The close-period side effect re-runs the remittance aggregation in **reconciled** mode — a full re-scan over every `Paycheck` whose `status` is `PAID` and whose parent run's `pay_date`-month equals this `period_month`, summing the matching bucket field per `(jurisdiction, tax_type)` — and writes the resulting authoritative number to `reconciled_cents`. The provisional `accrued_cents` and the authoritative `reconciled_cents` are equal when no voids occurred during the month; they may differ when a sequence of `PAID`/`VOID`/`PAID` cycles drifted the running accumulator, and the difference between the two fields is the readable audit trail. Closing the period also increments the row's `version`.

The reconciled scan uses a deterministic accumulator order: paychecks are summed in `created_at` ascending order; ties on `created_at` are broken by `created_at` ascending (the `id` is never used as a tie-break). The provisional accumulator likewise updates in the order paycheck transitions arrive.

Remitting transitions `Remittance.status` from `RECONCILED` to `REMITTED`. The `ComplianceOfficer` submits two fields on the request: `paid_cents` (the cents actually transmitted to the jurisdiction) and `expected_remittance_version` (the client's last observed `version` of the remittance row). Four preconditions are evaluated. The row must currently be in `RECONCILED` (otherwise `ERR_INVALID_STATE`); `paid_cents` must be strictly greater than zero; `paid_cents` must equal `reconciled_cents` exactly (a partial or excess remittance is rejected with `ERR_REMITTANCE_AMOUNT_MISMATCH`); and `expected_remittance_version` must equal the remittance row's current `version`. A version mismatch is rejected with `ERR_STALE_VERSION` and HTTP 412 — even when every other precondition would pass. This stale-version condition arises when a cascade has advanced the row's version since the client's last read; for example, when a late-arriving `Paycheck` `PAID`/`VOID` transition during accrual, or the act of closing the period itself, bumped `Remittance.version`. The successful remit transitions `Remittance.status` to `REMITTED`, sets `paid_cents` to the request's value, and increments `Remittance.version` by one.

`Remittance` rows are read with `period_month`, `jurisdiction`, `tax_type`, and `status` filters on the listing endpoint.

### 3.8. Auditing Through Listings

Several listings exist purely to make reverse-reachability queryable without server-side joins. Paychecks can be filtered by `employee_id`, `paycheck_run_id`, `status`, and `pay_type`. The sub-resource listing under a paycheck run returns its child paychecks. Garnishment orders can be filtered by `employee_id`, `status`, and `order_type`. Garnishment deductions can be filtered by `garnishment_order_id` and `paycheck_id`, and the sub-resource listing under a paycheck returns its child garnishment deductions. W-4 forms can be filtered by `employee_id`, `tax_year`, `status`, and `supersedes_w4_id` — the last one specifically to walk the supersession chain forward from any prior form. Employees can be filtered by `status` and `work_state_code`. Paycheck runs can be filtered by `status`, `pay_date_from`, and `pay_date_to`. Every filter listed here is optional; omitting all filters yields the full set, paginated by `limit` and `offset` and ordered by `created_at` ascending.

The clock-advance capability accepts a single `to_iso8601` field and sets the server's NOW_UTC to that instant for all subsequent transitions. The YTD-seed capability accepts any subset of `ytd_wages_cents`, `ytd_fed_withheld_cents`, `ytd_ss_wages_cents`, and `ytd_medicare_wages_cents`, and overwrites the named fields directly on the targeted employee while refreshing `updated_at` and incrementing `version`. Both capabilities are reserved for `PlatformAdmin`.

## 4. Endpoint Definitions

The endpoint surface follows REST conventions. Endpoints that create a new resource respond with HTTP 201 on success; endpoints that modify an existing resource or transition its state respond with HTTP 200. Endpoints that retrieve or list respond with HTTP 200. All endpoints follow the §2.2 success envelope on success and the §2.2 error envelope on failure. Request bodies and the full set of side effects for each endpoint are described in §3; the table below is intentionally minimal.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/employees` | Register a new employee | `HRClerk`, `PlatformAdmin` |
| GET | `/employees/{id}` | Retrieve an employee | `HRClerk`, `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/employees` | List employees with pagination and filters | `HRClerk`, `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| PATCH | `/employees/{id}/status` | Update `Employee.status` (e.g., `ACTIVE` → `TERMINATED`) | `HRClerk`, `PlatformAdmin` |
| POST | `/w4-forms` | Create a W-4 form in `DRAFT` | `HRClerk`, `PayrollPreparer` |
| POST | `/w4-forms/{id}/file` | File the W-4 (`DRAFT` → `FILED`) | `HRClerk`, `PayrollPreparer` |
| GET | `/w4-forms/{id}` | Retrieve a W-4 form | `HRClerk`, `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/w4-forms` | List W-4 forms with filters | `HRClerk`, `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/paycheck-runs` | Create a paycheck run in `DRAFT` | `PayrollPreparer` |
| POST | `/paycheck-runs/{id}/approve` | Approve a `DRAFT` run | `PayrollApprover` |
| POST | `/paycheck-runs/{id}/reject` | Revert `APPROVED` → `DRAFT` | `PayrollApprover` |
| POST | `/paycheck-runs/{id}/pay` | Mark `APPROVED` run as `PAID`; cascade child paychecks, YTD, garnishments, accruals | `PayrollApprover` |
| POST | `/paycheck-runs/{id}/void` | Void a `PAID` run (compensating action) | `PayrollApprover`, `ComplianceOfficer` |
| GET | `/paycheck-runs/{id}` | Retrieve a paycheck run | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/paycheck-runs` | List paycheck runs | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/paychecks` | Create a `Paycheck` under a `DRAFT` run; triggers withholding pipeline | `PayrollPreparer` |
| GET | `/paychecks/{id}` | Retrieve a paycheck | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin`, `HRClerk` |
| GET | `/paycheck-runs/{id}/paychecks` | List paychecks under a paycheck run | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/paychecks` | List paychecks with filters | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin`, `HRClerk` |
| POST | `/garnishment-orders` | Register a garnishment order | `ComplianceOfficer` |
| POST | `/garnishment-orders/{id}/suspend` | Suspend a garnishment order | `ComplianceOfficer` |
| POST | `/garnishment-orders/{id}/reactivate` | Reactivate a `SUSPENDED` garnishment order | `ComplianceOfficer` |
| POST | `/garnishment-orders/{id}/release` | Release a garnishment order (terminal) | `ComplianceOfficer` |
| GET | `/garnishment-orders/{id}` | Retrieve a garnishment order | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin`, `HRClerk` |
| GET | `/garnishment-orders` | List garnishment orders | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin`, `HRClerk` |
| GET | `/garnishment-deductions/{id}` | Retrieve a single garnishment deduction | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin`, `HRClerk` |
| GET | `/paychecks/{id}/garnishment-deductions` | List garnishment deductions under a paycheck | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin`, `HRClerk` |
| GET | `/garnishment-deductions` | List garnishment deductions with filters | `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin`, `HRClerk` |
| GET | `/remittances/{id}` | Retrieve a remittance row (includes `version`) | `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| GET | `/remittances` | List remittances with filters | `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/remittances/{id}/close-period` | Close accrual (`ACCRUING` → `RECONCILED`) | `ComplianceOfficer` |
| POST | `/remittances/{id}/remit` | Remit (`RECONCILED` → `REMITTED`); OCC-guarded | `ComplianceOfficer` |
| POST | `/tax-rate-tables` | Insert or replace a tax-rate-table row | `PlatformAdmin` |
| GET | `/tax-rate-tables` | List tax-rate-table rows | `HRClerk`, `PayrollPreparer`, `PayrollApprover`, `ComplianceOfficer`, `PlatformAdmin` |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's NOW_UTC clock | `PlatformAdmin` |
| POST | `/_employees/{id}/set_ytd` | Test-driving: seed an employee's YTD fields directly | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_GARNISHMENT_EXCEEDS_CCPA` | 422 |
| `ERR_NO_W4_ON_FILE` | 422 |
| `ERR_SUPERSEDE_TARGET_INVALID` | 422 |
| `ERR_PAY_PERIOD_OVERLAP` | 422 |
| `ERR_GARNISHMENT_AGGREGATE_CAP` | 422 |
| `ERR_REMITTANCE_AMOUNT_MISMATCH` | 422 |
| `ERR_OPEN_RUN_BLOCKS_CLOSE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
