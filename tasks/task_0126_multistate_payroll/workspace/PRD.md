# Multistate Payroll API — Product Requirements Document

## 1. Introduction

Payroll for a multistate workforce sits at the intersection of three regulatory regimes — federal income tax with FICA and Additional Medicare withholding, a patchwork of state and locality income tax rules, and court-ordered garnishment satisfied through a strict creditor waterfall — and a single arithmetic mistake in any one of them can either short the IRS, overpay a creditor, or leave an employee with a negative net check. The Multistate Payroll API is the system of record that processes a payroll cycle end to end: it captures the employee's W-4 election (including pre-filling a new year's election from the prior year), drafts a paycheck for each employee in each pay period, runs the per-paycheck tax engine across federal/state/local jurisdictions, allocates garnishments through a CCPA-compliant waterfall, ledgers the result on approval, and finally rolls up monthly remittance totals to the tax authorities.

Because payroll touches the company's cash account, the API enforces segregation of duties: the operator who calculates a paycheck may not approve it, the operator who approves may not disburse it, and the operator who finalizes a remittance may not transmit it. Corrections after disbursement are supported through an issue-correction loop that voids the original paycheck, posts compensating ledger entries, and creates a new draft paycheck — even if the corresponding monthly remittance has already been transmitted, in which case the remittance enters an amendment cycle. The same domain entities are exposed both for day-to-day data entry and for after-the-fact reconciliation; everything is recorded, nothing is mutated in place.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the role the operator is acting under. When either header is missing or carries a value the system does not recognize, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the role does not authorize the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Four role names are recognized by the system, spelled exactly as follows:

- `PayrollSpecialist` — responsible for day-to-day data entry: creating employees, recording W-4 elections (including pre-fill from the prior year), opening pay periods, attaching payroll items, running paycheck calculation, reverting to draft, and issuing corrections on already-approved or paid paychecks.
- `PayrollManager` — responsible for managerial actions: terminating employees, creating and releasing garnishment orders, approving calculated paychecks, finalizing/reopening/amending remittance periods, and seeding tax bracket configuration. May also create employees and create remittance periods (shared with `PayrollSpecialist`).
- `Treasurer` — responsible for disbursement: marking approved paychecks paid, and transmitting finalized or amended remittance to the tax authorities.
- `Any` — read-only access to list and retrieve operations across all resources, granted to any authenticated user holding one of the three preceding roles.

For every one of the four roles, `X-User-ID` is an **opaque operator identifier** that is not tied to any persisted entity. The server may record the supplied identifier on a resource (for example, capturing it as the calculator, approver, finalizer, or amender so that segregation-of-duties comparisons can be made on later transitions), but it never compares `X-User-ID` to any entity's `id`. Ownership is not modeled on a per-employee basis; instead, the role itself confers authority over the relevant operations, with explicit segregation-of-duties checks (see §2.6) reinforcing that the *same human* may not execute two consecutive control steps on the same artifact.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return, defaulting to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by their creation timestamp in ascending order. The `meta` object of any list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary, top-level resources — `Employee`, `W4Profile`, `PayPeriod`, `PayrollItem`, `Paycheck`, `GarnishmentOrder`, and `RemittancePeriod` — carry a system-managed core:

- `id` is a server-minted UUID string with no type prefix.
- `created_at` is an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`).
- `updated_at` is also an ISO 8601 UTC timestamp with three fractional digits and is refreshed on every mutation.
- `version` is an integer that begins at 1 on creation and increments by exactly 1 on every mutation, including mutations driven by side effects (for example, when a paycheck moves through its lifecycle and the side effects of approval revise the parent employee's year-to-date counters, the affected `Employee` resource's `updated_at` is refreshed and its `version` is incremented as well).

Two resources are exceptions because they are append-only or immutable. The `YTDLedgerEntry` records audit history and the `TaxBracketTable` records seeded configuration; both carry only `id` and `created_at`, and **neither** carries `updated_at` or `version`.

### 2.5. Optimistic Concurrency Control

Any mutation endpoint that targets a specific resource by id may optionally accept a `version` field in its request body. When `version` is supplied, the server compares it to the resource's current `version` and, on mismatch, rejects the request with `ERR_STALE_DATA`. When `version` is omitted from the body, no OCC check is performed and the mutation proceeds. This applies uniformly to termination, paycheck transitions (calculate, recalculate, approve, mark-paid, issue-correction), pay-period lock, garnishment release, remittance transitions (finalize, reopen, remit, amend), and payroll item edits.

### 2.6. Segregation of Duties

Three points in the payroll cycle enforce that the *same human* — identified by `X-User-ID` — may not perform two consecutive control steps on the same artifact:

- On a paycheck moving from `CALCULATED` to `APPROVED`, the approver's `X-User-ID` must differ from the `X-User-ID` recorded as the most recent calculator of that paycheck. A match is rejected with `ERR_SEGREGATION_OF_DUTIES`.
- On a paycheck moving from `APPROVED` to `PAID`, the Treasurer's `X-User-ID` must differ from **both** the approver and the most recent calculator of that paycheck. A match against either is rejected with `ERR_SEGREGATION_OF_DUTIES`.
- On a remittance moving from `FINALIZED` (or `AMENDED`) to `REMITTED`, the Treasurer's `X-User-ID` must differ from the finalizer's, and on the post-amendment remit it must differ from both the original finalizer and the amender. A match is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Segregation-of-duties is the highest-priority business-safety check: it is evaluated **before** referential checks such as the active W-4 lookup, because an SOD violation cannot be cured by data fixes.

### 2.7. Validation Ordering

Validations are evaluated in a fixed priority order so that a request never surfaces a downstream error while masking an upstream one. The order is: (1) presence of `X-User-ID` and `X-User-Role`; (2) role permission for the target endpoint; (3) left-to-right existence of every path resource (e.g., for an endpoint such as `/pay-periods/{periodId}/payroll-items`, the period must be located before the request is examined further, and a missing period yields `ERR_PAY_PERIOD_NOT_FOUND`); (4) state preconditions on the owning pay period (`OPEN`); (5) state preconditions on the paycheck (`DRAFT`, `CALCULATED`, `APPROVED`, etc., as relevant); (6) state preconditions on the remittance period (`DRAFT` for finalize, `FINALIZED` for remit or reopen, `REMITTED` for amend); (7) segregation of duties; (8) referential checks such as active W-4 resolution; (9) garnishment cap range; (10) pay period date ordering; (11) remittance (`tax_year`, `tax_month`) uniqueness; (12) hours validity; (13) per-employee-per-period paycheck uniqueness; (14) remittance finalize requires all monthly paychecks in non-pending states; (15) approve requires non-negative net pay; (16) lock requires at least one payroll item with every item already calculated; (17) OCC version match if `version` was supplied. The hours rule is evaluated before the duplicate-paycheck rule because malformed hours short-circuit recomputation.

### 2.8. Nested Resource Retrieval

Several endpoints take more than one path identifier (for example, `/pay-periods/{periodId}/payroll-items`). The system validates path identifiers strictly left to right and rejects the request immediately with the first applicable not-found error. This same left-to-right discipline applies to existence checks for the body's referenced ids: an `employee_id` supplied inside a payroll-item request body is resolved only after the surrounding `{periodId}` has been confirmed to exist.

### 2.9. Cascading Side Effects and Hierarchical State Alignment

Several state transitions in this system mutate more than one entity. When a paycheck transitions from `CALCULATED` to `APPROVED`, the server appends a `YTDLedgerEntry` with `entry_kind` of `ACCRUAL` whose deltas equal the paycheck's wage components, then recomputes `Employee.ytd_gross_wages_cents`, `ytd_social_security_wages_cents`, and `ytd_medicare_wages_cents` by summing all ledger entries for that `(employee_id, tax_year)`, then refreshes each active garnishment order's `amount_collected_cents` by adding the paycheck's per-order allocations — and if any order's collected total now meets or exceeds its `total_owed_cents`, that order automatically transitions to `SATISFIED`. Conversely, when a paycheck is voided through the correction loop, the server appends a `YTDLedgerEntry` with `entry_kind` of `REVERSAL` whose deltas are the negation of the source paycheck's components, recomputes the employee's year-to-date counters from the ledger, subtracts the source paycheck's per-order allocations from each garnishment order's collected total, and if any order had been `SATISFIED` but its collected total has now dropped below `total_owed_cents`, it automatically transitions back to `ACTIVE`.

Pay-period state likewise tracks the operational reality of its children: when a paycheck reaches `PAID` (or `VOIDED`) and every paycheck in the pay period is now in `PAID` or `VOIDED`, and the period itself is in `LOCKED`, the system automatically transitions the period to `CLOSED`. The system never re-opens a closed period; corrections to a paid paycheck that already belonged to a closed period leave that period closed and attach the new draft correction paycheck to a different target pay period supplied by the caller.

Every mutation — whether explicit (a state transition initiated by a client) or implicit (a derived field reconciled by a side effect, such as `Employee.ytd_*` after approval or `PayPeriod.paycheck_count` after a new payroll item) — refreshes the affected resource's `updated_at` and increments its `version`.

### 2.10. Monetary Values and Precision

Every monetary quantity in this system is represented as an integer count of **cents**, including configuration constants (the standard deduction, the federal and state bracket boundaries, the Social Security wage base, the Additional Medicare threshold). Calculations that produce a fractional cent are rounded to the nearest whole cent using **round half up** (i.e., a remainder of exactly half a cent rounds away from zero, toward positive infinity for non-negative values). Rounding is applied per tax type **before** summing into the paycheck's total withholding — that is, federal, state, and local withholdings are each rounded independently to whole cents, then summed into the figures stored on the paycheck. The same round-half-up rule applies to Social Security, base Medicare, Additional Medicare, the garnishment global CCPA cap, and each garnishment per-order cap.

### 2.11. The Year-to-Date Ledger Principle

The system never stores an authoritative wage total *in place* on the employee. Each `YTDLedgerEntry` is append-only and records the `employee_id`, the `paycheck_id` that produced it, the `tax_year` derived from the source paycheck's `PayPeriod.pay_date` year, signed deltas (`gross_wages_delta_cents`, `social_security_wages_delta_cents`, `medicare_wages_delta_cents`) — positive for accruals, negative for reversals — and an `entry_kind` of `ACCRUAL` or `REVERSAL`. The denormalized fields `ytd_gross_wages_cents`, `ytd_social_security_wages_cents`, and `ytd_medicare_wages_cents` on `Employee` are derived: they always equal the sum of ledger entries for the employee in the current `tax_year`, and the server re-derives them whenever a paycheck is approved or voided. This invariant — that summing the ledger reproduces the employee's denormalized year-to-date fields — is the system's reconciliation contract; it is what test scenarios verify.

### 2.12. Remittance Correction Cycle

Once a `RemittancePeriod` reaches `REMITTED`, the books for that calendar month are considered transmitted. The system supports later corrections by allowing a remittance to be amended: when a previously approved or paid paycheck is voided through the correction loop and the new correction paycheck for the same `(tax_year, tax_month)` reaches `APPROVED`, a `PayrollManager` may amend the remittance, which transitions it from `REMITTED` to `AMENDED` and re-runs the monthly aggregation so the totals reflect the correction (no reversal entries are written into the remittance; the recomputed totals overwrite the prior totals). The `AMENDED` remittance is then re-transmitted by a Treasurer back to `REMITTED`, and the cycle may repeat. The `REMITTED` and `AMENDED` states are therefore not terminal; only `DRAFT` and `FINALIZED` (in their reopened forms) can return to one another, while `REMITTED ↔ AMENDED` is the audit cycle.

## 3. Business Logic & Workflows

### 3.1. Establishing the Workforce: Employees and Their W-4 Profiles

An `Employee` is created by either a `PayrollSpecialist` or a `PayrollManager` and represents one person whose pay the system will compute. The creation payload requires a `full_name`, a `hire_date` expressed as an ISO date in `YYYY-MM-DD` form that defines the first pay period the employee is eligible for, a `work_state` chosen from `CA`, `NY`, `TX`, `IL`, or `PA` that controls the state income tax regime applied to the employee's paychecks, an optional `work_locality` chosen from `NYC`, `PHL`, or `NONE` that selects the city-level income tax jurisdiction (defaulting to `NONE` when omitted, in which case no local tax is withheld), and a non-negative integer `hourly_rate_cents`. On creation, the employee's `status` is `ACTIVE`, and the three year-to-date wage counters — `ytd_gross_wages_cents`, `ytd_social_security_wages_cents`, and `ytd_medicare_wages_cents` — are initialized to zero.

Each employee carries an append-mostly history of W-4 elections, modeled as `W4Profile` records under that employee. A profile is created via the explicit W-4 endpoint, where a `PayrollSpecialist` supplies the `filing_status` (`SINGLE`, `MARRIED_JOINT`, or `HEAD_OF_HOUSEHOLD`), an optional `dependents_amount_cents` representing the annual dependent credit from W-4 Step 3 (defaulting to 0), an optional `other_income_cents` representing the annual other-income add-on from Step 4(a) (defaulting to 0), an optional `additional_withholding_cents` representing the per-paycheck extra federal withholding from Step 4(c) (defaulting to 0), an optional `state_allowances` integer for the state-level allowance count (defaulting to 0), and the `effective_pay_period_id` of the pay period at which this profile becomes the employee's active W-4. The `effective_pay_period_id` is immutable after creation. Newly created profiles record `prefilled_from_prior_year` as `false`.

Alternatively, a new year's profile may be pre-filled from the most recent prior-year profile via a pre-fill capability: the specialist supplies only the new `effective_pay_period_id`, and the system locates the employee's W-4 whose `effective_pay_period.pay_date` is the latest within the prior tax year, copies its `filing_status`, `state_allowances`, `dependents_amount_cents`, and `other_income_cents` onto the new profile, sets `additional_withholding_cents` to 0, and marks `prefilled_from_prior_year` true. If no prior-year W-4 exists for the employee, the pre-fill is rejected with `ERR_NO_PRIOR_YEAR_W4`. Pre-fill is one-shot per employee per target tax year: a second pre-fill attempt for the same employee that would land in the same target tax year is rejected with `ERR_W4_PREFILL_ALREADY_DONE`, and concurrent pre-fill attempts serialize so that exactly one succeeds and the loser receives the same code.

The active W-4 for an employee at a given pay period is determined by an ordering rule: take all `W4Profile` records whose `effective_pay_period_id` resolves to a pay period whose `pay_date` is on or before the target pay period's `pay_date`, order them by that `pay_date` ascending, then break ties by the `W4Profile`'s own `created_at` ascending; the profile with the greatest such ordering is the active one. When no such profile exists, calculation of a paycheck for that employee is rejected with `ERR_NO_W4`.

An employee leaves the workforce via the terminate capability, which a `PayrollManager` performs and which advances `status` from `ACTIVE` to `TERMINATED`. Termination requires that no paycheck for this employee is currently in `DRAFT` or `CALCULATED`; if one is, the request is rejected with `ERR_PENDING_PAYCHECKS`. On success, the server stamps `termination_date` to today (its logical clock). After termination, a final-settlement paycheck may still be created for the employee provided the owning pay period's `period_end` is within seven days of the recorded `termination_date`; calculate requests outside that window are rejected with `ERR_TERMINATED_EMPLOYEE`.

### 3.2. The Pay Period Container

A `PayPeriod` is the unit of payroll work and is created by a `PayrollSpecialist` with three ISO dates: `period_start`, `period_end`, and `pay_date`. The system requires that `period_end` is greater than or equal to `period_start`, and that `pay_date` is greater than or equal to `period_end`; either inversion is rejected with `ERR_INVALID_PAY_PERIOD_DATES`. The pay period's tax attribution year is derived from the `pay_date`'s calendar year — not from `period_end` — because payroll reporting follows the date of pay rather than the date of work.

A new pay period begins in `OPEN` status and carries a `paycheck_count` of zero. While `OPEN`, payroll items may be attached and paychecks may be calculated or reverted. A `PayrollSpecialist` then locks the period via the lock capability, which advances the period from `OPEN` to `LOCKED`; at least one `PayrollItem` must exist in the period or the lock is rejected with `ERR_NO_PAYROLL_ITEMS`, and every `PayrollItem` must already have a corresponding paycheck in `CALCULATED` or later (`APPROVED`, `PAID`, or `VOIDED`) or the lock is rejected with `ERR_UNCALCULATED_ITEMS`. After lock, no new payroll items may be attached; the `PayrollItem.locked` flag was already set to true when each item's paycheck reached `CALCULATED`. The period transitions automatically from `LOCKED` to `CLOSED` once every paycheck within it is in `PAID` or `VOIDED`. Once `CLOSED`, the period is terminal and cannot be reopened.

### 3.3. Payroll Items and the Implicit Paycheck

Inside an `OPEN` pay period, a `PayrollSpecialist` attaches a `PayrollItem` per employee, supplying the employee's id and four optional hour fields: `regular_hours`, `overtime_hours` (billed at 1.5 times the hourly rate), `double_hours` (billed at 2.0 times the hourly rate), and a `retro_adjustment_cents` figure representing a lump-sum retroactive pay adjustment which may be positive (retro pay) or negative (a clawback). All four default to zero when omitted, the three hour fields must each be non-negative, and the sum of `regular_hours`, `overtime_hours`, and `double_hours` must not exceed 240 hours per period; violation is rejected with `ERR_INVALID_HOURS`. At most one non-correction `PayrollItem` may exist per `(pay_period_id, employee_id)` pair; an attempt to attach a second is rejected with `ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE`, and two concurrent attaches for the same pair are serialized so that exactly one wins and the loser receives the same code.

Creating the payroll item simultaneously creates an implicit `Paycheck` in `DRAFT` status linked to it via `payroll_item_id`, carries `pay_period_id` and `employee_id` from the request context, and increments the parent `PayPeriod.paycheck_count`. While the linked paycheck is in `DRAFT`, the specialist may edit the hours and the retro adjustment by submitting an update against the payroll item; once the paycheck reaches `CALCULATED`, the item's `locked` flag is true and further edits are rejected. Reverting the paycheck to `DRAFT` clears `locked` back to false.

### 3.4. Calculating a Paycheck

Calculation is the central computation in the system. A `PayrollSpecialist` calculates a paycheck, advancing it from `DRAFT` to `CALCULATED`. The request requires that the employee is `ACTIVE` (or in the seven-day final-settlement window described in §3.1; otherwise `ERR_TERMINATED_EMPLOYEE`), that an active `W4Profile` resolves for this employee at this pay period (otherwise `ERR_NO_W4`), and that the owning pay period is still `OPEN`. The system records the calculator's `X-User-ID` so that the later approval can enforce segregation of duties, snapshots the active W-4 onto the paycheck as `w4_profile_id`, and then computes every cents-denominated field in the paycheck. Two simultaneous calculate calls on the same paycheck serialize so that exactly one wins; the loser sees the resulting `CALCULATED` state and is rejected with `ERR_PAYCHECK_NOT_DRAFT`.

**Gross wages.** The paycheck's `gross_wages_cents` is the sum of four contributions: the regular hours multiplied by the hourly rate, the overtime hours multiplied by one-and-one-half times the hourly rate, the double hours multiplied by two times the hourly rate, and the retro adjustment. Hour-times-rate products are evaluated using the integer hourly rate (in cents) and decimal hours; the final gross is rounded to whole cents using round half up.

**Federal income tax — default annualized method.** When the retro adjustment is zero, the per-paycheck federal withholding uses an annualized projection. The system first multiplies the paycheck's gross by 26 (the number of biweekly pay periods per year) to obtain an annualized wage, then adds the W-4 Step 4(a) annual other-income amount. From this it subtracts the standard deduction corresponding to the filing status — 1,390,000 cents for `SINGLE`, 2,780,000 cents for `MARRIED_JOINT`, and 2,090,000 cents for `HEAD_OF_HOUSEHOLD` — flooring the result at zero. The system then applies the federal piecewise bracket table for the filing status, evaluating each bracket in order: every cent of taxable income that falls into a bracket is multiplied by that bracket's rate in basis points and divided by 10,000, and the contributions across all brackets are summed to produce the annual tax. The dependent credit `dependents_amount_cents` is then subtracted from the annual tax, flooring at zero. The result is divided by 26 to produce the per-paycheck withholding, and the W-4 Step 4(c) `additional_withholding_cents` is added to that quotient. The final amount is rounded half up to whole cents.

The federal bracket table for `SINGLE` is four tiers: 10.00% on income from 0 up to 1,100,000 cents, 12.00% on income from 1,100,000 to 4,475,000 cents, 22.00% on income from 4,475,000 to 9,525,000 cents, and 24.00% on all income beyond 9,525,000 cents. For `MARRIED_JOINT` the breakpoints are 0 / 2,200,000 / 8,950,000 / 19,050,000 cents with the same four rates 10.00% / 12.00% / 22.00% / 24.00%. For `HEAD_OF_HOUSEHOLD` the breakpoints are 0 / 1,575,000 / 6,005,000 / 9,525,000 cents with the same four rates.

**Federal income tax — supplemental flat rate variant for retro.** When the retro adjustment is non-zero, the system splits the paycheck into two pieces. The non-retro portion (regular plus overtime plus double, computed as gross minus the retro adjustment) is run through the same annualized method described above, ignoring the retro contribution. Independently, the retro adjustment itself is multiplied by the IRS supplemental flat rate of 22.00% (no annualization, no bracket evaluation, no standard deduction), and the result is rounded half up to whole cents. The two pieces are then summed to produce the federal withholding. The state retro adjustment, when applicable, follows the same supplemental-rate split using the state-specific supplemental rate where one is configured. This dual-variant trigger is the reason that identical hours can produce different federal withholding from one paycheck to the next: a retro adjustment of zero yields the standard aggregate method, and a non-zero retro adjustment yields the supplemental flat-rate split.

**Federal income tax — year-to-date reconciliation variant.** A third variant applies in one specific recovery scenario. If `Employee.ytd_gross_wages_cents` is currently greater than zero and the most recent prior paycheck for this employee was voided through the correction loop within the same tax year, the system uses cumulative true-up instead of annualization for the first paycheck calculated after that void. In this mode the cumulative taxable income is computed as the sum of the employee's pre-paycheck year-to-date gross plus this paycheck's gross, minus a prorated standard deduction equal to the filing-status standard deduction multiplied by `(periods_elapsed + 1) / 26` where `periods_elapsed` counts pay periods already processed in the year. That cumulative taxable amount is run through the federal bracket table for the filing status to produce the cumulative expected federal tax. From this the system subtracts the federal withholding already accumulated in the ledger from prior approvals in this tax year, and the difference — floored at zero so the withholding mechanism never refunds — is the reconciled federal withholding for this paycheck. After this single reconciliation paycheck, subsequent paychecks revert to the standard annualized method (or the supplemental variant when retro is present).

**State income tax.** The state withholding mirrors the federal annualized algorithm but uses the state's bracket table indexed by `work_state` and filing status, the state standard deduction, and `state_allowances`. Each state allowance subtracts 400,000 cents from the annualized taxable wage (i.e., $4,000 per allowance). `CA` for `SINGLE` is three tiers: 2.00% on income from 0 up to 1,000,000 cents, 4.00% on income from 1,000,000 to 5,000,000 cents, and 6.00% on income above 5,000,000 cents. `NY` for `SINGLE` is three tiers: 4.00% on income from 0 up to 1,200,000 cents, 6.00% on income from 1,200,000 to 8,000,000 cents, and 7.00% on income above 8,000,000 cents. `IL` is a single-bracket flat rate of 4.95% on all income, applied regardless of filing status. `PA` is a single-bracket flat rate of 3.07%, applied regardless of filing status. `TX` is a single-bracket flat rate of 0% — i.e., Texas produces zero state withholding. The result is rounded half up to whole cents.

**Local income tax.** When `work_locality` is `NONE`, the paycheck's `local_withholding_cents` is exactly zero. Otherwise the system applies a flat rate to the gross (no annualization) according to the locality: `NYC` is 3.80% of gross, `PHL` is 3.50% of gross. The product is rounded half up to whole cents.

**Social Security.** The Social Security tax is 6.20% applied to wages up to an annual wage base of 16,830,000 cents (i.e., $168,300). The system first computes the year-to-date Social Security wages **before** this paycheck — `ytd_social_security_wages_cents` as currently stored on the employee — and the remaining room is the wage base minus that figure, floored at zero. The taxable Social Security wages for this paycheck are the minimum of the gross and the remaining room. The withholding is taxable Social Security wages multiplied by 620 basis points and divided by 10,000, rounded half up to whole cents. At the boundary, if the pre-paycheck year-to-date Social Security wages equal the wage base exactly, the taxable amount is zero and the withholding is zero; if they equal the wage base minus one cent, the taxable amount is the minimum of the gross and one cent, and the withholding is still computed against that one cent.

**Base Medicare.** Standard Medicare withholding is 1.45% of the paycheck's gross, with no annual cap. The product is rounded half up to whole cents.

**Additional Medicare.** The employer must withhold an additional 0.90% on the portion of an employee's year-to-date Medicare wages that exceeds 20,000,000 cents (i.e., $200,000), regardless of filing status. The system computes the year-to-date Medicare wages **before** this paycheck (`ytd_medicare_wages_cents` as currently stored) and the same total **after** adding this paycheck's gross. If the post-paycheck year-to-date Medicare wages are at or below 20,000,000 cents, the additional withholding is zero. If the pre-paycheck year-to-date Medicare wages are already at or above 20,000,000 cents, the full gross is subject and the additional withholding is the gross multiplied by 90 basis points divided by 10,000, rounded half up to whole cents. If this paycheck crosses the threshold within itself — pre-paycheck year-to-date below and post-paycheck year-to-date above — the system applies the additional rate only to the post-threshold portion (post-paycheck year-to-date minus 20,000,000), and rounds half up to whole cents. The boundary distinction is sharp: at-or-above means crossing has already happened, at-or-below means crossing has not yet happened, and the mid case computes the post-threshold portion only. The employer does not match Additional Medicare in remittance (see §3.10).

**Net pay.** The paycheck's `net_pay_cents` is `gross_wages_cents` minus federal, state, and local withholdings, minus Social Security, base Medicare, and Additional Medicare, minus `garnishment_total_cents` (see §3.5). Calculation may produce a negative provisional net at this stage; approval will then reject it (see §3.6).

Calculation snapshots `w4_profile_id` and `employee_id` onto the paycheck, sets `PayrollItem.locked` to true, and stamps every computed field. The note that federal withholding at `CALCULATED` is **provisional** is intentional: until the paycheck is approved, the ledger has not absorbed it, and subsequent corrections may force a year-to-date reconciliation variant on the next paycheck.

### 3.5. Garnishment Orders and the Waterfall Allocator

A garnishment order is a court-ordered withholding against an employee's disposable income. A `PayrollManager` creates a `GarnishmentOrder` by supplying `employee_id`, `order_type` (one of `CHILD_SUPPORT`, `FEDERAL_TAX_LEVY`, `STUDENT_LOAN`, or `CREDITOR`), `total_owed_cents` (the cumulative balance the order must collect, immutable after creation), `cap_pct_of_disposable` (a per-pay-period cap expressed as an integer percent of disposable income in the range 1 through 100 inclusive — values outside the range are rejected with `ERR_INVALID_GARNISHMENT_CAP`), and `effective_pay_date` (the order applies only to paychecks whose owning pay period's `pay_date` is on or after this date). On creation, `amount_collected_cents` is zero, `status` is `ACTIVE`, and `priority_rank` is derived from `order_type`: `CHILD_SUPPORT` is rank 1, `FEDERAL_TAX_LEVY` is rank 2, `STUDENT_LOAN` is rank 3, and `CREDITOR` is rank 4. Lower ranks are paid first.

When a paycheck reaches the calculate step, the system runs the garnishment waterfall after computing all the withholdings.

1. The system first computes the employee's **disposable income** as gross minus federal, state, and local withholdings minus Social Security, base Medicare, and Additional Medicare. (Note that disposable income is the basis for the cap; the disposable amount is then further reduced by garnishment allocations to produce net pay.)
2. The system enumerates the employee's `GarnishmentOrder` rows where `status` is `ACTIVE` and `effective_pay_date` is on or before the owning pay period's `pay_date`. It sorts them by `priority_rank` ascending, then by `created_at` ascending, then by `id` ascending — a stable triple-key sort so the same input always produces the same allocations.
3. The system computes a **global CCPA cap** on the total garnishment that may be taken from this paycheck. The default cap is 25% of disposable income; however, if the employee has any `ACTIVE` `CHILD_SUPPORT` order, the cap rises to 50% of disposable income. The cap is computed as disposable multiplied by the applicable percent (25 or 50) divided by 100, rounded half up to whole cents.
4. With the global cap as the initial `remaining_pool`, the system walks the sorted order list and for each order computes a per-order cap as the disposable multiplied by `cap_pct_of_disposable` divided by 100, rounded half up to whole cents. It also computes the remaining owed amount on the order as `total_owed_cents` minus the order's currently stored `amount_collected_cents`. The allocation for the order is then the minimum of the per-order cap, the remaining owed amount, and the remaining pool. The allocation is recorded against the order on this paycheck, the remaining pool is decremented by the allocation, and processing stops as soon as the remaining pool reaches zero.
5. The sum of all per-order allocations on this paycheck is stored as the paycheck's `garnishment_total_cents`.

Two rules govern the waterfall precisely. First, the per-order cap is rounded **before** the waterfall comparisons, not after — the integer per-order cap is what enters the minimum operation. Second, there is no redistribution: if an earlier order is capped low (because its `cap_pct_of_disposable` is small) and the remaining pool would have allowed a later order to receive more than its cap, the later order is still bounded by its own cap; unused headroom from an earlier order is **not** re-allocated to a later order. The stable tie-break ensures reruns produce identical allocations.

On paycheck approval, the system refreshes each affected garnishment order's `amount_collected_cents` by adding this paycheck's per-order allocation. If `amount_collected_cents` reaches or exceeds `total_owed_cents` and the order is currently `ACTIVE`, the order transitions automatically to `SATISFIED`. Conversely, on paycheck void through the correction loop, the per-order allocation is subtracted from `amount_collected_cents`, and if the order had been `SATISFIED` but the new collected total is now below `total_owed_cents`, the order transitions back to `ACTIVE`. The garnishment-amount reconciliation is itself an aggregation: for each order, the system can derive `amount_collected_cents` as the sum of per-order allocations across that employee's `APPROVED` or `PAID` paychecks minus the sum of per-order allocations across that employee's `VOIDED` paychecks; this derivation must match the stored figure at all times.

A `PayrollManager` may also release an `ACTIVE` order via the release capability, advancing it to `RELEASED`; a release request against an order whose `status` is not `ACTIVE` is rejected with `ERR_GARNISHMENT_NOT_ACTIVE`.

### 3.6. Paycheck Approval and Disbursement

After calculation, a `PayrollManager` advances the paycheck from `CALCULATED` to `APPROVED`. The owning pay period must still be `OPEN` (otherwise `ERR_PAY_PERIOD_NOT_OPEN`), the paycheck's `net_pay_cents` must be greater than or equal to zero (otherwise `ERR_NEGATIVE_NET_PAY`, returned with HTTP 402), and the approver's `X-User-ID` must differ from the calculator's. Approval has three cascading side effects, all atomic: it appends a `YTDLedgerEntry` of kind `ACCRUAL` whose `gross_wages_delta_cents`, `social_security_wages_delta_cents`, and `medicare_wages_delta_cents` equal the paycheck's gross (modified for Social Security by the wage-base cap that was applied at calculate), it recomputes the employee's three year-to-date counters by summing all ledger entries for `(employee_id, tax_year)`, and it refreshes each touched garnishment order's `amount_collected_cents`. Two simultaneous approvals on the same paycheck or an approval racing a recalculate are serialized so that exactly one wins; the loser receives `ERR_PAYCHECK_NOT_CALCULATED`. A specialist may also revert a calculated paycheck back to draft, which is only allowed while the owning pay period is `OPEN`, clears every computed field on the paycheck to null, and releases the `PayrollItem.locked` flag.

A `Treasurer` then disburses the paycheck by advancing it from `APPROVED` to `PAID`. The Treasurer's `X-User-ID` must differ from the approver's and from the calculator's; matching either is rejected with `ERR_SEGREGATION_OF_DUTIES`. The disbursement also triggers the period-close check: if every paycheck in the owning pay period is now in `PAID` or `VOIDED` and the period is in `LOCKED`, the system transitions the period to `CLOSED`.

### 3.7. The Correction Loop

The correction loop handles the case where a paycheck must be amended after approval. A `PayrollSpecialist` calls the issue-correction capability supplying a `target_pay_period_id` for the new draft paycheck. The source paycheck must be in `APPROVED` or `PAID`; if it is in any other state, the request is rejected with `ERR_PAYCHECK_NOT_CORRECTABLE`. If the source paycheck is in `PAID`, the owning `RemittancePeriod` for that paycheck must be in `DRAFT` or `FINALIZED` — not `REMITTED`. (When the remittance is already `REMITTED`, issuing a correction is still permitted on the underlying paycheck; the remittance separately enters the amendment cycle described in §3.10.)

The side effects of the correction are: the source paycheck's `status` advances to `VOIDED`, a `YTDLedgerEntry` of kind `REVERSAL` is appended whose deltas are the negation of the source paycheck's, the employee's three year-to-date counters are recomputed from the ledger, each affected garnishment order has the source's per-order allocations subtracted from its `amount_collected_cents` (with any order whose collected total drops below `total_owed_cents` transitioning back from `SATISFIED` to `ACTIVE`), and a new `Paycheck` is created in `DRAFT` cloned from the source's `payroll_item_id` with `is_retro_correction` set to true and `correction_of_paycheck_id` pointing at the source. The new draft attaches to the supplied `target_pay_period_id`; a previously `CLOSED` source period remains `CLOSED` because paycheck count was already finalized there.

When the very next paycheck for the same employee in the same tax year is calculated and a void has just occurred in that tax year, the year-to-date reconciliation variant described in §3.4 is what runs on it, ensuring cumulative under- or over-withholding is corrected at the next pay period.

### 3.8. Concurrency and Uniqueness Guarantees

Several races are explicitly serialized by the system. Two simultaneous calculate calls on the same paycheck serialize so that exactly one wins; the loser observes the resulting `CALCULATED` state and is rejected with `ERR_PAYCHECK_NOT_DRAFT`. Two simultaneous approve calls (or an approve and a recalculate) on the same `CALCULATED` paycheck serialize so that exactly one wins; the loser is rejected with `ERR_PAYCHECK_NOT_CALCULATED`. Two simultaneous attempts to create a payroll item for the same `(pay_period_id, employee_id)` serialize so that at most one non-correction paycheck per pair exists; the loser is rejected with `ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE`. Two simultaneous attempts to create a remittance for the same `(tax_year, tax_month)` serialize so that at most one exists; the loser is rejected with `ERR_DUPLICATE_REMITTANCE`. Two simultaneous pre-fill attempts for the same employee targeting the same effective tax year serialize so that at most one prefilled profile is created; the loser is rejected with `ERR_W4_PREFILL_ALREADY_DONE`. Two simultaneous finalize calls on the same `RemittancePeriod` serialize so that exactly one transitions from `DRAFT` to `FINALIZED`; the loser is rejected with `ERR_REMITTANCE_NOT_DRAFT`.

### 3.9. Tax Bracket Configuration

The federal, state, and local tax tables are seeded into the system as `TaxBracketTable` records by a `PayrollManager`. Each table identifies its `jurisdiction` (one of `FEDERAL`, `CA`, `NY`, `TX`, `IL`, `PA`, `NYC`, or `PHL`), its `filing_status` (one of `SINGLE`, `MARRIED_JOINT`, or `HEAD_OF_HOUSEHOLD`, or the sentinel `ANY` meaning the table applies regardless of filing status, as used by Illinois, Pennsylvania, Texas, and the flat-rate localities), its `tax_year`, and an ordered array of `brackets`, where each bracket is a record of `lower_cents`, `upper_cents_or_null` (a null upper bound denotes the open-ended top bracket), and `rate_bps` expressed in basis points. A calculate operation that needs to resolve a bracket but cannot find a matching table for the lookup keys is rejected with `ERR_TAX_BRACKET_NOT_FOUND`.

For convenience in test orchestration, an admin-only capability advances the server's logical clock to a supplied `to_iso` instant; this affects the value used as "today" when stamping `termination_date` and any other current-date resolution. The capability is restricted to the `PayrollManager` role.

### 3.10. Monthly Remittance

The system aggregates withholdings into a monthly `RemittancePeriod`, created by either a `PayrollSpecialist` or a `PayrollManager` via the create remittance capability with `tax_year` and `tax_month` (1 through 12). On creation, the remittance is in `DRAFT` with every `total_*_cents` field at zero and an empty `state_breakdown`. The `(tax_year, tax_month)` pair is unique across remittances.

A `PayrollManager` finalizes the remittance, advancing it from `DRAFT` to `FINALIZED`. Two preconditions must hold before aggregation runs. First, every `PayPeriod` whose `pay_date` falls inside this `(tax_year, tax_month)` must be in `CLOSED`; if any is still `OPEN` or `LOCKED`, the request is rejected with `ERR_OPEN_PAY_PERIODS_IN_MONTH`. Second, every `Paycheck` whose owning pay period's `pay_date` is in this `(tax_year, tax_month)` must be in `APPROVED`, `PAID`, or `VOIDED`; if any is still in `DRAFT` or `CALCULATED`, the request is rejected with `ERR_UNAPPROVED_PAYCHECKS_IN_MONTH`. The aggregation then sources every paycheck whose owning pay period's `pay_date.year` equals `tax_year` and `pay_date.month` equals `tax_month` and whose status is `APPROVED` or `PAID`; voided paychecks contribute zero. The system sums the per-paycheck cents-already-rounded values to populate:

- `total_federal_withholding_cents` = sum of each paycheck's `federal_withholding_cents`.
- `total_state_withholding_cents` = sum of each paycheck's `state_withholding_cents` (this is the grand total across states).
- `total_local_withholding_cents` = sum of each paycheck's `local_withholding_cents`.
- `total_social_security_cents` = sum of each paycheck's `social_security_cents`, then multiplied by two — because the employer matches Social Security one-for-one.
- `total_medicare_cents` = sum of each paycheck's `medicare_base_cents`, then multiplied by two — because the employer matches base Medicare one-for-one.
- `total_medicare_additional_cents` = sum of each paycheck's `medicare_additional_cents` — the employer does **not** match Additional Medicare; only the employee-withheld portion is remitted.
- `state_breakdown` is an array of records `{ state, amount_cents }`, formed by grouping the source paychecks by the employee's `work_state` and summing each group's `state_withholding_cents`. The grand `total_state_withholding_cents` equals the sum of these breakdown amounts.

These per-paycheck inputs are already rounded; the aggregation itself is pure integer summation (no further rounding). The employer-matching rule on Social Security and base Medicare and the no-match rule on Additional Medicare are pinned by this contract because a naive implementation that doubles everything or doubles nothing will be exposed by the remittance totals.

A `PayrollManager` may reopen a `FINALIZED` remittance back to `DRAFT`, but only if the remittance has never been transmitted — i.e., its status was never `REMITTED`. Reopen clears every `total_*_cents` field and the `state_breakdown` array.

A `Treasurer` transmits a `FINALIZED` remittance, advancing it to `REMITTED`. The Treasurer's `X-User-ID` must differ from the user who finalized this remittance; matching is rejected with `ERR_SEGREGATION_OF_DUTIES`.

After transmission, if a previously approved or paid paycheck in the same `(tax_year, tax_month)` is voided and a new correction paycheck for that month subsequently reaches `APPROVED`, a `PayrollManager` amends the remittance via the amend capability, advancing it from `REMITTED` to `AMENDED`. The precondition is that at least one paycheck in this month is now `VOIDED` with a corresponding correction paycheck in `APPROVED`; otherwise the request is rejected with `ERR_NO_AMENDMENT_BASIS`. The amend side effect re-runs the monthly aggregation including the correction paychecks and stores the new totals (no reversal entries are written; the recomputed totals overwrite the prior totals). The `AMENDED` remittance is then re-transmitted back to `REMITTED` by a Treasurer whose `X-User-ID` differs from both the original finalizer and the amender; matching is rejected with `ERR_SEGREGATION_OF_DUTIES`. The `REMITTED ↔ AMENDED` cycle may repeat as further corrections arrive in the month.

## 4. Endpoint Definitions

Operations that create new top-level resources return `201 Created`; operations that modify or transition existing resources return `200 OK`. Read operations return `200 OK`. Path parameters and request body schemas are derived from the workflow narratives in §3; this table is the canonical method/path map.

| Method | Path                                                          | Description                                                                                  | Authorized Role(s)                  |
| ------ | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------- |
| POST   | `/employees`                                                  | Create employee                                                                              | PayrollSpecialist, PayrollManager   |
| GET    | `/employees`                                                  | List employees (optional `status` filter)                                                    | Any                                 |
| GET    | `/employees/{employeeId}`                                     | Get employee                                                                                 | Any                                 |
| POST   | `/employees/{employeeId}/terminate`                           | Terminate employee                                                                           | PayrollManager                      |
| POST   | `/employees/{employeeId}/w4-profiles`                         | Create a W-4 profile effective at a given pay period                                         | PayrollSpecialist                   |
| POST   | `/employees/{employeeId}/w4-profiles/prefill`                 | Pre-fill a W-4 from the latest prior-year profile                                            | PayrollSpecialist                   |
| GET    | `/employees/{employeeId}/w4-profiles`                         | List the employee's W-4 profiles                                                             | Any                                 |
| POST   | `/garnishment-orders`                                         | Create a court-ordered garnishment                                                           | PayrollManager                      |
| GET    | `/garnishment-orders`                                         | List garnishment orders (filterable by `employee_id`, `status`)                              | Any                                 |
| GET    | `/garnishment-orders/{orderId}`                               | Get garnishment order                                                                        | Any                                 |
| POST   | `/garnishment-orders/{orderId}/release`                       | Release a garnishment order                                                                  | PayrollManager                      |
| POST   | `/pay-periods`                                                | Create a pay period                                                                          | PayrollSpecialist                   |
| GET    | `/pay-periods`                                                | List pay periods (optional `status` filter)                                                  | Any                                 |
| GET    | `/pay-periods/{periodId}`                                     | Get pay period                                                                               | Any                                 |
| POST   | `/pay-periods/{periodId}/lock`                                | Lock pay period (no further items)                                                           | PayrollSpecialist                   |
| POST   | `/pay-periods/{periodId}/payroll-items`                       | Add a payroll item and implicit draft paycheck                                               | PayrollSpecialist                   |
| PUT    | `/payroll-items/{itemId}`                                     | Update payroll item hours/retro while linked paycheck is still in draft                      | PayrollSpecialist                   |
| GET    | `/paychecks`                                                  | List paychecks (filterable by `pay_period_id`, `employee_id`, `status`)                      | Any                                 |
| GET    | `/paychecks/{paycheckId}`                                     | Get paycheck                                                                                 | Any                                 |
| POST   | `/paychecks/{paycheckId}/calculate`                           | Compute withholdings and garnishment allocations                                             | PayrollSpecialist                   |
| POST   | `/paychecks/{paycheckId}/recalculate`                         | Revert calculated paycheck to draft                                                          | PayrollSpecialist                   |
| POST   | `/paychecks/{paycheckId}/approve`                             | Approve paycheck (segregation of duties vs calculator)                                       | PayrollManager                      |
| POST   | `/paychecks/{paycheckId}/mark-paid`                           | Mark paycheck paid (segregation of duties vs approver and calculator)                        | Treasurer                           |
| POST   | `/paychecks/{paycheckId}/issue-correction`                    | Void paycheck and create a new draft correction paycheck                                     | PayrollSpecialist                   |
| POST   | `/remittance-periods`                                         | Create a remittance for `(tax_year, tax_month)`                                              | PayrollSpecialist, PayrollManager   |
| GET    | `/remittance-periods`                                         | List remittance periods (filterable by `tax_year`, `status`)                                 | Any                                 |
| GET    | `/remittance-periods/{remitId}`                               | Get remittance period                                                                        | Any                                 |
| POST   | `/remittance-periods/{remitId}/finalize`                      | Aggregate monthly totals and lock                                                            | PayrollManager                      |
| POST   | `/remittance-periods/{remitId}/reopen`                        | Reopen finalized remittance back to draft                                                    | PayrollManager                      |
| POST   | `/remittance-periods/{remitId}/remit`                         | Transmit remittance to tax authorities (segregation of duties vs finalizer/amender)          | Treasurer                           |
| POST   | `/remittance-periods/{remitId}/amend`                         | Amend a remitted remittance after a correction landed in the same month                     | PayrollManager                      |
| POST   | `/tax-bracket-tables`                                         | Seed a bracket table                                                                         | PayrollManager                      |
| GET    | `/tax-bracket-tables`                                         | List bracket tables (filterable by `jurisdiction`, `tax_year`)                               | Any                                 |
| POST   | `/_clock/advance`                                             | Test-only: advance server logical clock to a supplied ISO instant                            | PayrollManager                      |

## 5. Error Code Catalogue

| Error ID                                          | HTTP Status Code     |
| ------------------------------------------------- | -------------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`      | 400 Bad Request      |
| `ERR_INSUFFICIENT_PERMISSIONS`                    | 403 Forbidden        |
| `ERR_EMPLOYEE_NOT_FOUND`                          | 404 Not Found        |
| `ERR_W4_PROFILE_NOT_FOUND`                        | 404 Not Found        |
| `ERR_PAY_PERIOD_NOT_FOUND`                        | 404 Not Found        |
| `ERR_PAYROLL_ITEM_NOT_FOUND`                      | 404 Not Found        |
| `ERR_PAYCHECK_NOT_FOUND`                          | 404 Not Found        |
| `ERR_GARNISHMENT_ORDER_NOT_FOUND`                 | 404 Not Found        |
| `ERR_REMITTANCE_NOT_FOUND`                        | 404 Not Found        |
| `ERR_TAX_BRACKET_NOT_FOUND`                       | 404 Not Found        |
| `ERR_PAY_PERIOD_NOT_OPEN`                         | 409 Conflict         |
| `ERR_PAY_PERIOD_NOT_LOCKABLE`                     | 409 Conflict         |
| `ERR_PAYCHECK_NOT_DRAFT`                          | 409 Conflict         |
| `ERR_PAYCHECK_NOT_CALCULATED`                     | 409 Conflict         |
| `ERR_PAYCHECK_NOT_APPROVED`                       | 409 Conflict         |
| `ERR_PAYCHECK_NOT_CORRECTABLE`                    | 409 Conflict         |
| `ERR_REMITTANCE_NOT_DRAFT`                        | 409 Conflict         |
| `ERR_REMITTANCE_NOT_FINALIZED`                    | 409 Conflict         |
| `ERR_REMITTANCE_NOT_REMITTED`                     | 409 Conflict         |
| `ERR_GARNISHMENT_NOT_ACTIVE`                      | 409 Conflict         |
| `ERR_SEGREGATION_OF_DUTIES`                       | 403 Forbidden        |
| `ERR_NO_W4`                                       | 409 Conflict         |
| `ERR_NO_PRIOR_YEAR_W4`                            | 409 Conflict         |
| `ERR_TERMINATED_EMPLOYEE`                         | 409 Conflict         |
| `ERR_PENDING_PAYCHECKS`                           | 409 Conflict         |
| `ERR_INVALID_PAY_PERIOD_DATES`                    | 400 Bad Request      |
| `ERR_INVALID_HOURS`                               | 400 Bad Request      |
| `ERR_INVALID_GARNISHMENT_CAP`                     | 400 Bad Request      |
| `ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE`             | 409 Conflict         |
| `ERR_DUPLICATE_REMITTANCE`                        | 409 Conflict         |
| `ERR_W4_PREFILL_ALREADY_DONE`                     | 409 Conflict         |
| `ERR_NO_PAYROLL_ITEMS`                            | 409 Conflict         |
| `ERR_UNCALCULATED_ITEMS`                          | 409 Conflict         |
| `ERR_OPEN_PAY_PERIODS_IN_MONTH`                   | 409 Conflict         |
| `ERR_UNAPPROVED_PAYCHECKS_IN_MONTH`               | 409 Conflict         |
| `ERR_NO_AMENDMENT_BASIS`                          | 409 Conflict         |
| `ERR_NEGATIVE_NET_PAY`                            | 402 Payment Required |
| `ERR_STALE_DATA`                                  | 409 Conflict         |
| `ERR_INVALID_REQUEST`                             | 400 Bad Request      |
