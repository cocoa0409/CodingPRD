# PEO HR Outsourcing API — Product Requirements Document

## 1. Introduction

A Professional Employer Organization sells one promise: a growing company hands over the machinery of employment — payroll, tax, benefits, workers' compensation, compliance paperwork — and gets back a single monthly relationship and a single invoice. Delivering on that promise means the PEO becomes a **co-employer of record**. It hires the client's staff onto its own master Federal EIN, reports their wages under that EIN, insures them under one master workers'-comp policy, and pools them into benefit plans large enough to earn carrier rates a twenty-person company could never negotiate alone. Everything the client used to do badly, the PEO now does centrally — and is legally on the hook for.

This document specifies the backend service that runs that business. It spans the full co-employment arc: registering a prospective client and countersigning the service agreement; hiring worksite employees and shepherding their I-9 / W-4 / direct-deposit paperwork through review; enrolling them into pooled medical, dental and vision plans during an open-enrollment window; running semi-monthly payroll with wage-base-capped federal taxes; aggregating every client's payroll into one quarterly master-EIN return; producing ACA and EEO-1 filings from derived headcount; billing the client an administrative fee plus four pass-through cost lines; collecting the money; and working the HR advisory queue when a client needs to know whether they can fire someone.

Two structural themes run through the whole system and should be read as design constraints rather than incidental details. The first is **money that must reconcile**: every cent charged to a client is either an administrative fee the PEO earns or a cost it passes through, and a voided invoice must return the client's ledger to exactly the value it held before the invoice existed. The second is **derived truth**: headcounts, pool occupancy, year-to-date wage accumulators, outstanding balances and quarterly filing membership are never incremented in place and never trusted from a stale copy — they are recomputed from the underlying rows every time something upstream changes.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` carries a value that is not one of the five business roles below, the caller is treated as the **Anonymous** identity. Anonymous is permitted on zero endpoints; every request presenting it is refused with `ERR_UNAUTHENTICATED` (HTTP 401) before any other check runs. Once the caller is authenticated, the endpoint's own role list is consulted; a recognized role that is not listed on the endpoint is refused with `ERR_UNAUTHORIZED` (HTTP 403).

The five business roles are `PeoAdmin`, `PayrollSpecialist`, `HrAdvisor`, `ClientAdmin` and `Employee`. `Anonymous` is the sixth, degenerate identity described above.

- A **`PeoAdmin`** is the PEO's operations administrator. They register and activate clients, review onboarding packets, own the master workers'-comp policy and its class codes, create pooled benefit plans and enrollment windows, approve payroll, record bank funding outcomes, prepare and file tax returns, open and submit compliance filings, void invoices, and drive the logical clock.
- A **`PayrollSpecialist`** is the PEO's payroll operator. They open payroll runs, calculate them and initiate the funding debit. They deliberately cannot approve a run — see the segregation-of-duties rule in §2.8.
- An **`HrAdvisor`** is PEO HR advisory staff working the client ticket queue.
- A **`ClientAdmin`** is the HR administrator at a co-employment client and acts only inside their own company.
- An **`Employee`** is a worksite employee using self-service: reading their own record, pay history and enrollments, enrolling in benefits, and raising HR tickets.

Three of these roles are **opaque identities**. When `X-User-Role` is `PeoAdmin`, `PayrollSpecialist` or `HrAdvisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — a calculating operator's id lands in `calculated_by_user_id`, an approver's in `approved_by_user_id`, an advisor's in `assigned_advisor_user_id` — but it never compares it to any entity's `id`.

The other two roles are **entity-backed**. When `X-User-Role` is `ClientAdmin`, `X-User-ID` is the `id` of the acting `ClientCompany`; every ownership check compares the target resource's owning client (the company itself, or the `client_id` of the employee, packet, payroll run, invoice, enrollment or ticket being addressed) to `X-User-ID`. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `WorksiteEmployee`; ownership checks compare the target's `worksite_employee_id` (or, for the employee record itself, its `id`) to `X-User-ID`. A `ClientAdmin` reaching into another company's data, or an `Employee` reaching into another employee's data, is refused with `ERR_NOT_OWNER` (HTTP 403).

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

Every list endpoint accepts two optional query parameters. `limit` defaults to 10, may be no smaller than 1 and no larger than 100. `offset` defaults to 0 and may be no smaller than 0. A `limit` outside the inclusive range 1 to 100 is a malformed request and is refused with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a subsection below states otherwise, list results are ordered by `created_at` ascending. The `meta` block of a list response carries `limit` (the effective page size), `offset` (the effective starting position), `total_count` (the number of rows matching the filters, before the page window is applied) and `has_more` (true when rows remain beyond the current window).

### 2.4. Resource Identity, Timestamps and Versioning

Every resource is addressed by an `id` that the server mints as a UUID. Identifiers carry no type prefix — an invoice id and a ticket id are indistinguishable in shape, and the path decides what a given id is expected to resolve to.

Most resources additionally carry three common properties. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` is refreshed on every mutation of the resource. `version` is an integer that starts at 1 when the resource is created and increases by exactly 1 on every mutation, including mutations that arrive as a side effect of an operation performed on a different resource. This last point matters: when approving a payroll run issues an invoice and that invoice moves the client's ledger, the client's `version` advances too.

Three record types are deliberately leaner because they are immutable ledger rows rather than mutable resources: `WcClassCode`, `PayrollLine` and `InvoiceLine` carry only `id` and `created_at`. They have no `updated_at` and no `version`, and none is ever exposed.

The server runs on a **logical clock**, never on wall-clock time. Before any call sets it, the clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to real time. A `PeoAdmin` moves it with a test-driving capability that accepts a `to_iso8601` instant and answers with the new `current_utc` and an `activated_enrollment_count`. Anything the specification calls "the current clock date" is the date component of that logical clock: benefit waiting periods, enrollment-window status, termination dates, coverage end dates, `filed_at` and `submitted_at` all read from it.

### 2.5. Pinning a Write to the State the Caller Observed

Two writes in this system are dangerous precisely because repeating them *succeeds*. Opening a fresh onboarding packet legitimately supersedes whatever non-terminal packet the employee already carries, so a duplicate create would quietly void a packet the caller never knew existed. Applying a payment to an invoice legitimately accumulates, so a duplicate apply would double-credit the client. Both are therefore protected by optimistic concurrency control, and in both cases the protection is a mandatory, non-optional input field naming the version the caller last observed.

Creating an onboarding packet for a worksite employee requires `expected_employee_version` to equal that `WorksiteEmployee`'s current `version`. If any writer has advanced the employee's version since the caller read it, the create is refused with `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412).

Applying a payment to a client invoice requires `expected_invoice_version` to equal that `ClientInvoice`'s current `version`. If the invoice has moved on — another payment landed, or the invoice was voided — the payment is refused with `ERR_STALE_INVOICE_VERSION` (HTTP 412).

No other endpoint takes a version field. Everywhere else, the caller supplies the resource id and the server reads the current row.

### 2.6. Money, Counts and the Order of Rounding

All monetary amounts are integers denominated in **cents**. There are no floating-point amounts anywhere in a stored record or a response body. Wherever a rate, factor or fraction produces a non-integer intermediate, the result is rounded **half up** to a whole cent — a value exactly on the half-cent boundary rounds away from zero.

The **order** in which rounding is applied is part of the contract, not an implementation detail, because rounding-then-summing and summing-then-rounding differ by cents:

- Each tax component on a pay line is rounded half up **individually, at the line level**, and only the rounded integers are summed into the run's totals and into the invoice's employer-tax pass-through. The system never re-derives a tax figure from a run's aggregate gross wages.
- Each workers'-comp premium is rounded half up **per line**, and the rounded per-line premiums are summed.
- Each benefit premium is rounded half up **per enrollee**, and only then is the employer/employee split taken.
- Sums of already-rounded integers are never re-rounded.

Counts (headcounts, seat occupancy, revision rounds, reopen counts, aggregated run counts) are integers. The one place a fraction becomes a count — the part-time ACA equivalence in §2.9 — uses a **floor**, not half-up rounding.

### 2.7. The Client Ledger, Credit and Delinquency

A client's `outstanding_balance_cents` is a **derived ledger figure, never an incremented counter**. It is, at all times, the sum over that client's invoices whose `status` is either `ISSUED` or `PARTIALLY_PAID` of the invoice's `total_cents` minus its `amount_paid_cents`. Invoices in `PAID` or `VOID` status contribute nothing. The balance is recomputed from scratch after every invoice mutation: when an invoice is issued by the payroll-approval cascade, when a payment is applied, and when an invoice is voided.

This definition is what makes voiding an invoice the exact compensating action for issuing one. Issuing an invoice of some total raises the balance by exactly that total; voiding it, with no payment applied, lowers the balance by exactly that total, leaving no drift.

Each client carries a `credit_limit_cents`, defaulting to 5,000,000 cents (fifty thousand dollars) and required to be at least 0. It gates payroll approval, and the gate reads the balance **before** the approval's own invoice is issued — so a single approval may legitimately push a client past their limit, and it is the *next* approval that is refused.

Delinquency is tracked separately, as `delinquency_strikes`: the count of payroll debits the client's bank has returned. Strikes drive both a fee surcharge (§3.6) and suspension (§3.7), and they reset to 0 whenever a suspended client is restored to `ACTIVE`.

### 2.8. Segregation of Duties and the Payroll Gates

The operator who calculates a payroll run may not be the operator who approves it. At approval the approving `PeoAdmin`'s `X-User-ID` is compared to the run's `calculated_by_user_id`; if they are equal, the approval is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Because a recalculation overwrites `calculated_by_user_id` with the recalculating operator, an administrator who recalculates a run has just disqualified themselves from approving it.

Payroll also carries a compliance gate. No employee may be paid whose co-employment paperwork the PEO has not reviewed: every employee in a run's payable set must hold an onboarding packet in `APPROVED` status, and a single employee still awaiting review blocks the entire run with `ERR_ONBOARDING_INCOMPLETE` (HTTP 422).

### 2.9. ACA Headcount and Filing Applicability

Two derived headcounts sit on every client and are recomputed whenever any of its worksite employees changes employment status — that is, when a packet approval activates an employee, and when an employee is terminated.

`active_employee_count` is simply the number of that client's worksite employees whose `status` is `ACTIVE`. Employees still in `PENDING_ONBOARDING` and employees already `TERMINATED` do not count.

`fte_count` is the ACA full-time-equivalent figure. Each `ACTIVE` employee whose `employment_type` is `FULL_TIME` contributes exactly one. Part-time worksite staff are not counted individually; instead the client reports their aggregate monthly hours as `part_time_monthly_hours_total`, and that figure is divided by 120 monthly hours per equivalent and rounded **down** to a whole number of equivalents. The two components are added: full-time heads plus part-time equivalents.

`is_ale` — Applicable Large Employer — is true when `fte_count` is at least 50. Fifty exactly is an ALE; the threshold is inclusive. Applicability of the two compliance filing types follows from these figures, and both gates are likewise inclusive: an `ACA_1095C` filing requires `is_ale` to be true, and an `EEO1` filing requires `fte_count` to be at least 15.

### 2.10. Cascades and Derived Counters

Several operations in this system mutate more than one entity. Where they do, the cascade is specified in full in the relevant §3 subsection, and each entity the cascade touches has its `version` advanced and its `updated_at` refreshed. Terminating an employee, for example, reaches through their benefit enrollments into the pooled plans' seat counts and back up into their client's ACA headcount; approving a payroll run reaches into every paid employee's year-to-date accumulators, then issues an invoice, then moves the client's ledger.

Every derived quantity in the system — `outstanding_balance_cents`, `active_employee_count`, `fte_count`, `is_ale`, `enrolled_count`, `pool_status`, the three year-to-date wage accumulators, and a tax filing's member set — is **recomputed from its source rows**, not adjusted by a delta. This is what guarantees that a compensating action (a void, a cancellation, a termination) restores the system to exactly the value it would have held had the compensated action never happened.

### 2.11. Path Resolution and Validation Precedence

When several checks could reject the same request, the order in which they are evaluated is fixed. Implementations must apply them in this sequence, because the first failure determines which `error_id` the caller sees.

1. **Authentication.** Headers present and the role recognized — otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The caller's role appears on the endpoint — otherwise `ERR_UNAUTHORIZED` (403).
3. **Ownership.** For `ClientAdmin` and `Employee` callers, the target resource belongs to them — otherwise `ERR_NOT_OWNER` (403).
4. **Path existence.** Every id embedded in the URL resolves, validated **left to right**: on a nested path, the outer id is resolved before the inner one, so a request naming a nonexistent client and a nonexistent employee reports the client. The dedicated 404 codes are `ERR_CLIENT_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_PACKET_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_PAYROLL_RUN_NOT_FOUND`, `ERR_TAX_FILING_NOT_FOUND`, `ERR_COMPLIANCE_FILING_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and `ERR_TICKET_NOT_FOUND`.
5. **Body foreign keys.** Every foreign key supplied in the request body resolves — a `wc_class_code_id` to a class code (`ERR_CLASS_CODE_NOT_FOUND`), a `benefit_plan_id` to a plan (`ERR_PLAN_NOT_FOUND`), a `worksite_employee_id` to an employee (`ERR_EMPLOYEE_NOT_FOUND`). This applies to hiring a worksite employee, creating a benefit enrollment, and raising an HR ticket.
6. **Body schema.** Required fields present, types correct, enum members recognized, and numeric and date constraints honored — otherwise `ERR_INVALID_REQUEST` (400). The constraints are: `annual_salary_cents` greater than 0; `wc_experience_mod` between 0.5 and 2.0 inclusive; `quarter` one of 1, 2, 3 or 4; a payment's `amount_cents` greater than 0; `period_end` on or after `period_start`; `check_date` on or after `period_end`; `close_date` on or after `open_date`; `ssn_last4` exactly four digits; `birth_year` between 1930 and 2010 inclusive; `credit_limit_cents` at least 0; `part_time_monthly_hours_total` at least 0; `employer_contribution_pct` between 0 and 1 inclusive; `pool_capacity` greater than 0; `participation_minimum_count` at least 1; `composite_rate_cents`, `age_band_base_rate_cents`, `base_rate_per_100_cents` and `payroll_cap_cents` each greater than 0; and `limit` inside the range 1 to 100.
7. **Optimistic concurrency.** `expected_employee_version` and `expected_invoice_version` match, as specified in §2.5 — otherwise the corresponding 412.
8. **Uniqueness.** A client's `fein` is unique across all clients (`ERR_DUPLICATE_FEIN`, 409); a master policy's `master_policy_number` is unique; and the triple of `year`, `quarter` and `basis` is unique across tax filings (`ERR_DUPLICATE_TAX_FILING`, 409).
9. **State legality.** The target resource is in a state from which the requested transition is declared — otherwise `ERR_INVALID_STATE` (409). This covers packet submission and review, payroll calculation, approval, funding and funding events, invoice payment and void, tax filing, compliance submission, enrollment cancellation and client activation. HR tickets are the single exception: an action not declared from a ticket's current status is refused with `ERR_TICKET_ACTION_NOT_ALLOWED` (409) instead.
10. **Client standing.** The owning client is `ACTIVE` — otherwise `ERR_CLIENT_NOT_ACTIVE` (409). This gate guards exactly five operations: hiring a worksite employee, opening an onboarding packet, creating a benefit enrollment, opening a payroll run, and calculating a payroll run. Notably it does **not** guard invoice payment or the re-funding of an already-approved run, which is how a suspended client digs itself out.
11. **Business safety and temporal rules**, then the fiscal gates, in the order presented in §3: onboarding completeness, segregation of duties, packet completeness and revision limits, benefits eligibility, filing applicability, ticket reopen budget, pay-period overlap, enrollment-window rules, coverage overlap, pool capacity, empty payable set, empty aggregation set, unsettled runs, the credit limit, and finally overpayment.

---

## 3. Business Logic & Workflows

### 3.1. Taking a Client Live, and Losing Them Again

A prospective client enters the system as a record carrying its `legal_name`, its own `fein` (the client keeps its Federal EIN even though payroll will be reported under the PEO's master EIN — the two are different numbers and both are stored), and the two-letter `state_code` of its worksite. Three commercial parameters may be supplied at registration and otherwise take their defaults: `credit_limit_cents` (5,000,000 cents), `wc_experience_mod` (1.0 — the workers'-comp experience modification factor that will multiply every class-code rate for this client, and which must lie between 0.5 and 2.0 inclusive), and `part_time_monthly_hours_total` (0). A fourth, `service_agreement_signed`, records whether the co-employment agreement has actually been executed and defaults to false. Registration is a `PeoAdmin` operation and mints the client in `PROSPECT` status with an `outstanding_balance_cents` of 0, `delinquency_strikes` of 0 and `version` 1. A second client presenting a `fein` that another client already holds is refused with `ERR_DUPLICATE_FEIN`.

Nothing happens to a `PROSPECT`. It cannot hire, cannot run payroll, cannot enroll anyone in benefits. Countersigning by a `PeoAdmin` moves the client `PROSPECT → ACTIVE`, but only if the client is in fact still `PROSPECT` and its `service_agreement_signed` flag is true; an attempt against an unsigned agreement, or against a client that has already been taken live, is refused with `ERR_INVALID_STATE`.

Clients can also fall out of good standing. When the client's bank returns a payroll debit for the second time — that is, when `delinquency_strikes` reaches 2 after the increment — an `ACTIVE` client is moved by the system to `SUSPENDED`. A `SUSPENDED` client is frozen for anything new: hiring, opening packets, enrolling in benefits, opening payroll runs and calculating payroll are all refused with `ERR_CLIENT_NOT_ACTIVE`. What a suspended client *can* still do is pay its invoices and re-attempt funding on runs already approved. When the client's recomputed `outstanding_balance_cents` reaches exactly 0 — whether because the last outstanding invoice was paid in full or because it was voided — the system moves the client `SUSPENDED → ACTIVE` and resets `delinquency_strikes` to 0. Reading a client returns all of this: the derived ledger, the strike count, the headcounts and the ACA figures.

### 3.2. Hiring, and the Onboarding Packet Cycle

Hiring is available to both a `PeoAdmin` and the client's own `ClientAdmin`, and only against an `ACTIVE` client. The payload carries the new hire's `first_name`, `last_name`, `ssn_last4` (exactly four digits — the employee will use it to identify themselves in self-service), `birth_year` (between 1930 and 2010, and the basis of the age band used later by age-rated benefit plans), `hire_date` as an ISO calendar date, `annual_salary_cents` (strictly positive), and a `wc_class_code_id` naming the workers'-comp class the employee's duties fall under. `employment_type` may be supplied as `FULL_TIME` or `PART_TIME` and defaults to `FULL_TIME`; only full-time heads are counted individually toward the ACA figure of §2.9, since part-time hours arrive in aggregate on the client record. The employee is created in `PENDING_ONBOARDING` with `version` 1, a null `termination_date`, `benefits_eligible` false and all three year-to-date accumulators at 0. The client's `active_employee_count`, `fte_count` and `is_ale` do **not** move at hire — a new hire is not yet an employee for ACA purposes.

Paperwork is tracked as an **onboarding packet**, opened against the employee by a `PeoAdmin` or `ClientAdmin`. Three booleans record the co-employment documents: `i9_completed` (employment-eligibility verification), `w4_completed` (withholding election) and `direct_deposit_completed` (deposit authorization). Each may be supplied at creation and each otherwise defaults to false. Opening a packet is the OCC-protected write of §2.5 — the caller must pin `expected_employee_version` to the employee's current `version` — precisely because a fresh packet **supersedes** any packet the employee still carries: every existing packet of that employee in `DRAFT`, `SUBMITTED` or `RETURNED` status is moved to `VOIDED`, and the new one is created in `DRAFT` with `revision_rounds` at 0 and a null `reviewer_note`. The employee's own `version` advances as a result, which is exactly why the next caller cannot reuse a version it read before the supersede.

Submission moves the packet `DRAFT → SUBMITTED`, and is also the correction path, moving it `RETURNED → SUBMITTED` for another round of review. Both are open to a `PeoAdmin` or `ClientAdmin`. Two conditions guard it. First, all three of `i9_completed`, `w4_completed` and `direct_deposit_completed` must be true; a submission with any one of them false is refused with `ERR_PACKET_INCOMPLETE`. Second, the packet's `revision_rounds` must be strictly below 3: a packet that has already been returned three times has exhausted its correction budget, and the fourth submission attempt is refused with `ERR_PACKET_REVISION_LIMIT`.

Review is a `PeoAdmin` decision and carries a `decision` of either `APPROVE` or `RETURN`, optionally accompanied by a `reviewer_note` that is stored on the packet either way. Only a `SUBMITTED` packet may be reviewed. `APPROVE` moves the packet `SUBMITTED → APPROVED` and bubbles up: the packet's `WorksiteEmployee` moves `PENDING_ONBOARDING → ACTIVE`, and the client's `active_employee_count`, `fte_count` and `is_ale` are recomputed from the new population. `RETURN` moves the packet `SUBMITTED → RETURNED` and burns a correction round, adding 1 to `revision_rounds`. `APPROVED` and `VOIDED` are terminal packet states.

Termination is available to a `PeoAdmin` or `ClientAdmin` against any employee not already `TERMINATED` — a `PENDING_ONBOARDING` hire who never showed up and an `ACTIVE` long-timer follow the same path. It sets `status` to `TERMINATED` and stamps `termination_date` with the current clock date, and it triggers a four-level cascade. Any onboarding packet of that employee still in `DRAFT`, `SUBMITTED` or `RETURNED` becomes `VOIDED`. Every benefit enrollment of that employee still in `PENDING` becomes `CANCELLED`, and every one still `ACTIVE` becomes `TERMINATED` with its `coverage_end_date` set to the first day of the month following the current clock date (the end date is exclusive, so coverage runs through the last day of the current month). Every pooled plan that just lost a seat has its `enrolled_count` re-derived, and from that new count its `pool_status` is re-derived — a full pool may fall back to `ACTIVE`, an active one to `AT_RISK`, an at-risk one to `FORMING`. Finally the client's `active_employee_count`, `fte_count` and `is_ale` are recomputed. `TERMINATED` is terminal for an employee.

An employee's own self-service record exposes their `status`, their `benefits_eligible` flag and their three year-to-date accumulators — `ytd_taxable_wages_cents`, `ytd_ss_taxable_cents` and `ytd_futa_taxable_cents` — alongside the identifying fields. Their full pay history and every packet ever opened for them, `VOIDED` ones included, are separately readable. Employees may be listed by their `client_id`, by `wc_class_code_id`, and by `status`.

### 3.3. The Master Policy and Its Class Codes

Workers' compensation in a PEO is bought once, centrally. A `PeoAdmin` records the master policy with its `master_policy_number` (unique across the system), the `carrier_name` writing it, the `policy_year` it covers, and the `master_ein` under which all client payroll will be reported to the tax authority. A `payroll_cap_cents` may also be supplied, defaulting to 15,000,000 cents (one hundred fifty thousand dollars); it is the per-employee, per-run ceiling used by the audited premium variant described in §3.5, and it must be strictly positive.

Hanging off the master policy are its **class codes**, each added by a `PeoAdmin` with a `wc_policy_id` linking it back to the policy, its NCCI `class_code` string, a human `description` of the covered duties, a strictly positive `base_rate_per_100_cents` — premium cents charged for every $100 (that is, every 10,000 cents) of covered payroll, before the client's experience modification — and a `hazard_tier` of `LOW`, `MEDIUM` or `HIGH`, defaulting to `LOW`. Class codes are PEO-level records: a worksite employee at any client points at one of them, which is why the same clerical class code can be shared by twenty clients while each client's premium still differs, through its own `wc_experience_mod`.

### 3.4. Pooling Benefits: Plans, Windows, Seats and Prices

A pooled benefit plan is created by a `PeoAdmin` and shared across every client. It records the `carrier_name` underwriting it, a `plan_type` of `MEDICAL`, `DENTAL` or `VISION`, the `plan_year` its rates apply to (and against which enrollee ages are computed), and a `rating_method` of `COMPOSITE` or `AGE_BANDED`, defaulting to `COMPOSITE`. Both rate inputs are always supplied and both must be strictly positive: `composite_rate_cents` is the flat monthly premium per enrollee under composite rating, and `age_band_base_rate_cents` is the monthly base premium that age-banded rating multiplies by the enrollee's band factor. `employer_contribution_pct` — the share of the monthly premium the client absorbs, with the remainder becoming the employee's pre-tax payroll deduction — defaults to 0.60 and must lie between 0 and 1 inclusive. The carrier's commercial terms arrive as `pool_capacity`, the maximum number of concurrently occupied seats (strictly positive), and `participation_minimum_count`, the minimum seat count below which the carrier considers the pool under-subscribed (at least 1). A new plan starts with `enrolled_count` at 0 and `pool_status` at `FORMING`.

**Seat occupancy** is a conserved quantity. A plan's `enrolled_count` is always the number of that plan's enrollments whose `status` is `PENDING` or `ACTIVE` — both occupy a seat — while `CANCELLED` and `TERMINATED` enrollments release theirs. Available seats are the plan's `pool_capacity` minus its `enrolled_count`. From the count alone, `pool_status` is re-derived every time the count changes, and the four cases are checked in this order: the pool is `FULL` when `enrolled_count` has reached or passed `pool_capacity`; otherwise it is `FORMING` when `enrolled_count` is exactly 0; otherwise it is `AT_RISK` when `enrolled_count` is above 0 but strictly below `participation_minimum_count`; otherwise — the participation minimum is met and capacity is not — it is `ACTIVE`.

Enrollment is gated by an **open-enrollment window**, scheduled per client and plan year by a `PeoAdmin` with a `plan_year`, an `open_date` and a `close_date` (which must not precede the open date). A window's `status` is not stored but derived from the logical clock: `SCHEDULED` while the clock date is before `open_date`, `OPEN` while the clock date lies between `open_date` and `close_date` with both endpoints inclusive, and `CLOSED` once the clock date is past `close_date`. Windows of the same client and the same `plan_year` must be kept apart by a **seven-day buffer**: a new window's `open_date` must fall at least 7 days after the `close_date` of every existing earlier window of that client and plan year, and its `close_date` must fall at least 7 days before the `open_date` of every existing later one. A window that crowds another is refused with `ERR_WINDOW_OVERLAP`.

Enrolling an employee into a plan is done by the employee themselves or by their `ClientAdmin`, and the payload names the `benefit_plan_id` being joined, the `coverage_start_date`, and an optional `coverage_end_date`. Coverage windows are **half-open**: the start date is inclusive, the end date is exclusive, and a null `coverage_end_date` means open-ended coverage, treated as `9999-12-31` for comparison purposes. Five gates guard the create, and they are evaluated in this order. First, benefits eligibility: the enrollee's `benefits_eligible` must be true, which it is only when their `status` is `ACTIVE` **and** the current clock date is on or after their `hire_date` plus a thirty-day waiting period; a failure here is `ERR_EMPLOYEE_NOT_BENEFITS_ELIGIBLE`. Second, the window: the enrollee's client must have an open-enrollment window for the plan's `plan_year` whose derived status is `OPEN` at the current clock date, or the enrollment is refused with `ERR_ENROLLMENT_WINDOW_CLOSED`. Third, coverage overlap: the new half-open coverage window must not intersect that of any other `PENDING` or `ACTIVE` enrollment of the *same employee and the same coverage line*. Because the end is exclusive, an enrollment starting exactly on a prior enrollment's `coverage_end_date` is adjacent, not overlapping, and is accepted; a genuine intersection is refused with `ERR_COVERAGE_OVERLAP`. Fourth, capacity: a seat must be free, meaning `enrolled_count` is strictly below `pool_capacity`, or the enrollment is refused with `ERR_PLAN_POOL_FULL`. Fifth, the client must be `ACTIVE`.

The enrollment is created in `PENDING`, its `plan_type` snapshotted from the plan (that snapshot is what the overlap check keys on, together with the `worksite_employee_id`), and it is **priced immediately** at creation. Under `COMPOSITE` rating every enrollee costs the plan's flat `composite_rate_cents`, so a composite pool's premium is a pure headcount multiple and is entirely insensitive to *who* is enrolled. Under `AGE_BANDED` rating the enrollee's age is the plan's `plan_year` minus the employee's `birth_year`, and the plan's `age_band_base_rate_cents` is multiplied by the band factor for that age, rounded half up: the factor is 0.80 for an age below 30, 1.00 for ages 30 through 39, 1.30 for ages 40 through 49, 1.75 for ages 50 through 59, and 2.20 for age 60 and above. Either way the result lands in `monthly_premium_cents`. The split is then taken from that rounded premium and is itself pinned: `employer_share_cents` is the monthly premium multiplied by the plan's `employer_contribution_pct`, rounded half up, and `employee_share_cents` is simply the monthly premium minus the employer share — the remainder absorbs the rounding, so the two shares always reconstitute the premium exactly. That employee share is a *monthly* figure; halved, it becomes the semi-monthly pre-tax deduction that payroll applies. Creating an enrollment re-derives the plan's `enrolled_count` and, from it, the plan's `pool_status`.

A `PENDING` enrollment becomes `ACTIVE` on its own, without any caller action, when the logical clock is advanced to a date at or after its `coverage_start_date`. This activation is a system move driven by the clock: every `PENDING` enrollment whose coverage has begun transitions `PENDING → ACTIVE` in `created_at` ascending order, and the number activated is reported back as `activated_enrollment_count`. Because both `PENDING` and `ACTIVE` occupy a seat, this transition leaves `enrolled_count` and `pool_status` untouched.

Cancellation, available to a `ClientAdmin` or `PeoAdmin`, releases the seat. A `PENDING` enrollment moves `PENDING → CANCELLED` outright. An `ACTIVE` enrollment moves `ACTIVE → TERMINATED` and has its `coverage_end_date` set to the first day of the month following the current clock date, so the exclusive end leaves the current month covered. In both cases the plan's `enrolled_count` is re-derived and its `pool_status` re-derived from the new count, returning the available-seat figure to exactly its pre-enrollment value. `CANCELLED` and `TERMINATED` are terminal enrollment states.

Finally, a plan's **premium quote** lets a `PeoAdmin` or `ClientAdmin` re-price the currently seated population under a `rating_method` of their own choosing, without touching a single stored enrollment. The quote walks the plan's seated enrollees — those in `PENDING` or `ACTIVE`, in `created_at` ascending order — prices each one under the requested method exactly as an enrollment would be priced (rounding half up per enrollee), and reports `enrollee_count` alongside the pool's `monthly_premium_cents` (the sum of the per-enrollee premiums), its `employer_share_cents` (that sum multiplied by the plan's `employer_contribution_pct`, rounded half up) and its `employee_share_cents` (the sum minus the employer share). The `benefit_plan_id` and the `rating_method` used are echoed back. The same seated population deliberately yields a different pool premium and a different split under the two methods — that difference is the entire point of the capability.

### 3.5. Running Payroll

A payroll run is opened for one client by a `PayrollSpecialist` or `PeoAdmin` and covers a `period_start` and `period_end` (both inclusive calendar dates, with the end never before the start) and a `check_date` on which wages are actually paid (never before the period end). `pay_frequency` may be supplied but only `SEMI_MONTHLY` is supported, and that is its default. The run is created with a `processing_status` of `DRAFT` and a `funding_status` of `UNFUNDED`, and it may only be opened against an `ACTIVE` client.

**Pay periods of one client are closed intervals and may not touch.** Because both `period_start` and `period_end` are inclusive, two periods that merely abut — where an existing run's `period_end` equals the new run's `period_start` — genuinely collide, and the create is refused with `ERR_PAY_PERIOD_OVERLAP`. Any intersection with an existing run of the same client produces the same refusal.

The run carries **two independent status dimensions**, and it is worth being explicit that they are orthogonal. `processing_status` walks `DRAFT → CALCULATED → APPROVED → PAID`; `funding_status` walks `UNFUNDED → DEBIT_PENDING → FUNDED`, with a `FAILED` detour. A run can only be funded once it has been approved, but funding can bounce back and forth between `DEBIT_PENDING` and `FAILED` while the processing dimension sits patiently at `APPROVED`. Runs may be listed by `client_id` and by either dimension, using the `processing_status` and `funding_status` filters.

Calculation is a `PayrollSpecialist` (or `PeoAdmin`) operation on an `ACTIVE` client's run whose `processing_status` is `DRAFT` or already `CALCULATED` — recalculating an already-calculated run is explicitly allowed and simply re-runs everything, which is how an operator corrects an overtime figure. Every existing pay line of the run is discarded and regenerated, `calculated_by_user_id` is overwritten with the calling operator's `X-User-ID` (see §2.8 for what that costs them at approval time), and `processing_status` is set to `CALCULATED`.

The **payable set** is the population the run pays: the worksite employees of the run's client whose `status` is `PENDING_ONBOARDING` or `ACTIVE`, whose `hire_date` is on or before the run's `period_end`, and whose `termination_date` is either null or on or after the run's `period_start` — walked in `created_at` ascending order. If that set is empty the calculation is refused with `ERR_NO_PAYABLE_EMPLOYEES`; if any member of it lacks an `APPROVED` onboarding packet the whole run is refused with `ERR_ONBOARDING_INCOMPLETE`, as §2.8 sets out.

One **pay line** is generated per payable employee, carrying the `payroll_run_id` that produced it and the `worksite_employee_id` it pays. Its wages come first. `base_wages_cents` is the employee's `annual_salary_cents` divided by 24 semi-monthly pay periods per year, rounded half up. `overtime_premium_cents` is the overtime premium supplied for that employee on the calculate call, and 0 when none is supplied; the calculate payload accepts an optional `overtime_entries` collection, each entry naming a `worksite_employee_id` and the `overtime_premium_cents` to apply to that employee's line. `gross_wages_cents` is the base wages plus the overtime premium.

Next comes the benefit deduction. The enrollments that cover this pay period are the employee's enrollments whose `status` is `ACTIVE` at calculate time and whose coverage window overlaps the run period on the half-open rule — that is, whose `coverage_start_date` is on or before the run's `period_end` and whose `coverage_end_date` is either null or strictly after the run's `period_start`. For each such covering enrollment, half of its `employee_share_cents` (a monthly figure, so halved for a semi-monthly period, rounded half up) is deducted; the sum across covering enrollments is the line's `pretax_benefit_deduction_cents`. Subtracting it from gross gives `taxable_wages_cents`, the base on which every tax below is computed.

**Taxes are computed against the employee's year-to-date position, which is itself derived, never incremented.** For a given employee and a given check date, the finalized pay lines are those belonging to runs whose `processing_status` is `APPROVED` or `PAID` and whose `check_date` is **strictly earlier** than the check date in question, walked in ascending `check_date` order and, for ties, ascending `created_at` order (never by id). `ytd_taxable_wages_cents` is the sum of `taxable_wages_cents` over those finalized lines; `ytd_ss_taxable_cents` is the sum of the Social-Security-taxable portion actually charged on each of them; `ytd_futa_taxable_cents` is the sum of the FUTA-taxable portion actually charged on each. Because lines of `DRAFT` and `CALCULATED` runs are excluded, a run being calculated never sees its own not-yet-approved lines. The figures stored on the employee record are these same three sums taken over *all* finalized lines.

With those in hand, the employee side of the line is computed, each component rounded half up **independently, on the line**:

- The Social-Security-taxable portion is the smaller of the line's `taxable_wages_cents` and the remaining Social Security wage base — 17,610,000 cents ($176,100) minus the employee's `ytd_ss_taxable_cents` — floored at 0 so an employee already at the base is charged nothing. `employee_ss_tax_cents` is that portion multiplied by 6.2 percent.
- `employee_medicare_tax_cents` is the full `taxable_wages_cents` multiplied by 1.45 percent. Medicare has no wage base.
- Additional Medicare applies only to year-to-date taxable wages above 20,000,000 cents ($200,000). The portion of this line that sits above that threshold is the employee's `ytd_taxable_wages_cents` plus this line's `taxable_wages_cents`, minus the threshold — capped at the line's own taxable wages so it never exceeds them, and floored at 0. `employee_addl_medicare_tax_cents` is that portion multiplied by 0.9 percent.
- `employee_income_tax_cents` is a flat federal withholding: the line's `taxable_wages_cents` multiplied by 10 percent.
- `employee_tax_total_cents` is the sum of those four rounded components.

The employer side mirrors it:

- `employer_ss_tax_cents` is the employer's match: the same Social-Security-taxable portion multiplied by 6.2 percent.
- `employer_medicare_tax_cents` is the match on Medicare: the full `taxable_wages_cents` multiplied by 1.45 percent.
- FUTA applies only to the first 700,000 cents ($7,000) of an employee's annual wages. The FUTA-taxable portion is the smaller of the line's `taxable_wages_cents` and 700,000 cents minus the employee's `ytd_futa_taxable_cents`, floored at 0; `employer_futa_tax_cents` is that portion multiplied by 0.6 percent.
- `employer_tax_total_cents` is the sum of those three rounded components.

`net_pay_cents` closes the line: gross wages, less the pre-tax benefit deduction, less the employee tax total. The employer's taxes are a cost to the client, not a deduction from the employee, and never touch net pay.

Each line also carries its **estimated workers'-comp premium**, `wc_premium_estimated_cents`, which is what the PEO accrues at calculate time. Premium for any payroll base is that base divided by 10,000 cents (a $100 unit), multiplied by the `base_rate_per_100_cents` of the class code the employee's `wc_class_code_id` points at, multiplied by the client's `wc_experience_mod`, and rounded half up. The **estimated** variant uses the line's full `gross_wages_cents` as the payroll base: no per-employee cap, and the overtime premium fully included. (Its sibling, the **audited** variant, is billed later and computes a strictly smaller figure whenever overtime or a cap is in play — see §3.6.)

The run's totals are then recomputed by summing the regenerated lines, and only the already-rounded line values are summed: `total_gross_wages_cents`, `total_taxable_wages_cents`, `total_employee_tax_cents`, `total_employer_tax_cents`, `total_benefit_deduction_cents` (the sum of the lines' pre-tax deductions) and `total_wc_premium_estimated_cents`.

### 3.6. Approval, the Invoice Cascade, and Getting Paid

Approval is exclusively a `PeoAdmin` act, and it is where the money becomes real. It requires the run to be `CALCULATED`; it requires the approver's `X-User-ID` to differ from the run's `calculated_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`; and it requires the client's `outstanding_balance_cents` to be no greater than its `credit_limit_cents` at that instant, on pain of `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). As §2.7 notes, the credit check reads the balance *before* this approval's own invoice exists, so an approval may legitimately leave the client over its limit; the consequence lands on the next approval.

Approval sets `processing_status` to `APPROVED` and stamps `approved_by_user_id` with the approver's `X-User-ID`, and it recomputes the three year-to-date accumulators of every employee the run paid, since their lines have just become finalized. It then issues a `ClientInvoice` in `ISSUED` status against the run's `client_id` and its `payroll_run_id`, minting a human-readable `invoice_number`, and that invoice emits **exactly five invoice lines, always in this order, even where the amount is zero**. Each line carries the `client_invoice_id` it belongs to, its `line_type`, a `description`, and its `amount_cents`.

1. `ADMIN_FEE` — the PEO's own fee, computed below.
2. `PASS_THROUGH_GROSS_WAGES` — the run's `total_gross_wages_cents`.
3. `PASS_THROUGH_EMPLOYER_TAX` — the run's `total_employer_tax_cents`, which is the sum of the per-line, already-rounded employer components; the system never re-derives employer tax from the run's aggregate wages.
4. `PASS_THROUGH_BENEFIT_PREMIUM` — summed across the employees the run paid, and for each of them across every `ACTIVE` benefit enrollment whose coverage window covers the run period on the same half-open rule used at calculate time, of that enrollment's **full** `monthly_premium_cents`. The client is billed the whole pooled premium; only the employee's half-share was withheld from the paycheck.
5. `PASS_THROUGH_WC_PREMIUM` — summed across the run's pay lines, of that line's workers'-comp premium under the **audited** variant.

The **audited** workers'-comp variant reads the same lines the estimated one did and differs only in the payroll base it feeds into the identical rate formula (payroll base divided by 10,000 cents, times the class code's `base_rate_per_100_cents`, times the client's `wc_experience_mod`, rounded half up per line, then summed). Its base is the line's `gross_wages_cents` capped at the master policy's `payroll_cap_cents`, then reduced by the line's `overtime_premium_cents` — the overtime premium portion is not covered payroll — and floored at 0 so the base never goes negative. For a line with no overtime and wages below the cap the two variants agree exactly; for any line with overtime, or above the cap, the audited premium is strictly smaller than the estimated one.

The **administrative fee** is the PEO's revenue on the run, and its evaluation order is pinned — tier, then raw fee, then collar, then surcharge. Reversing any two steps produces a different number.

First, the **volume tier**. Take the run's `total_gross_wages_cents` as the billable payroll volume. The tier chooses a single rate that applies to the *whole* volume — this is not a marginal-rate schedule. A volume below 5,000,000 cents ($50,000) is billed at 4.5 percent. A volume from 5,000,000 cents up to but not including 20,000,000 cents ($200,000) is billed at 3.5 percent. A volume of 20,000,000 cents or more is billed at 2.75 percent. Second, the **raw fee** is the volume multiplied by that single rate, rounded half up. Third, the **collar**: the raw fee is lifted to a floor of 25,000 cents ($250) if it falls below it, and cut down to a cap of 2,500,000 cents ($25,000) if it rises above it. Fourth, the **delinquency surcharge**: if the client's `delinquency_strikes` at the moment of approval is 1 or more, the collared fee is multiplied by 1.10 and rounded half up again; otherwise the collared fee stands as it is. The result is the invoice's `admin_fee_cents` and the amount of its `ADMIN_FEE` line.

The invoice's `pass_through_total_cents` is the sum of the four pass-through amounts, its `total_cents` is the administrative fee plus that pass-through total — which is by construction the sum of all five `amount_cents` — and its `amount_paid_cents` starts at 0. The client's `outstanding_balance_cents` is then recomputed per §2.7 and therefore rises by exactly the new invoice's `total_cents`.

**Payment** is exclusively the `ClientAdmin`'s act, against their own invoice, and it is OCC-protected: the payload carries `expected_invoice_version` (which must equal the invoice's current `version`, else `ERR_STALE_INVOICE_VERSION`) and a strictly positive `amount_cents`. The payment may not exceed the invoice's unpaid remainder — its `total_cents` minus its `amount_paid_cents` — and an attempt to pay more is refused with `ERR_OVERPAYMENT`. The invoice must be `ISSUED` or `PARTIALLY_PAID`. The paid amount is added to `amount_paid_cents`; if that leaves a remainder the invoice moves to `PARTIALLY_PAID` (whether it was `ISSUED` or already `PARTIALLY_PAID` — further partial payments simply accumulate), and if it settles the remainder exactly the invoice moves to `PAID` with `amount_paid_cents` equal to `total_cents`. Either way the client's ledger is recomputed; and if the client was `SUSPENDED` and the recomputed balance is exactly 0, the client is restored to `ACTIVE` with `delinquency_strikes` back to 0.

**Voiding** an invoice is a `PeoAdmin` act and the compensating action for the whole approval cascade. An `ISSUED` or `PARTIALLY_PAID` invoice moves to `VOID`; any `amount_paid_cents` already applied is retained on the record for audit but the invoice's unpaid remainder simply drops out of the ledger sum, so with no payment applied the client's `outstanding_balance_cents` returns to exactly its pre-issue value with no drift. A `SUSPENDED` client whose recomputed balance reaches 0 through a void is likewise restored to `ACTIVE` with `delinquency_strikes` reset to 0. What a void does **not** do is unwind the payroll: the underlying run keeps its `processing_status` and its `funding_status` untouched. `PAID` and `VOID` are terminal invoice states. Invoices may be listed by `client_id`, by the `payroll_run_id` that produced them, and by `status`, and an invoice's five lines are separately readable.

### 3.7. Funding the Debit, and the Cost of a Return

Funding an approved run means debiting the client's bank account. A `PayrollSpecialist` or `PeoAdmin` initiates the debit on a run whose `processing_status` is `APPROVED` and whose `funding_status` is `UNFUNDED`; the funding dimension moves `UNFUNDED → DEBIT_PENDING`. The bank's answer arrives later, as a funding event recorded by a `PeoAdmin`, carrying an `outcome` of either `SETTLED` or `RETURNED`, and only against a run whose funding dimension is `DEBIT_PENDING`.

A `SETTLED` outcome moves the funding dimension `DEBIT_PENDING → FUNDED` — a terminal funding state — and bubbles **across dimensions**: the processing dimension advances `APPROVED → PAID`, which is what makes the run's lines eligible for a quarterly filing.

A `RETURNED` outcome is where delinquency begins. The funding dimension moves `DEBIT_PENDING → FAILED`, and the processing dimension is deliberately left untouched at `APPROVED` — the payroll was approved and the invoice stands; only the money bounced. The client's `delinquency_strikes` is incremented by 1. And if that increment brings the strike count to 2 or more while the client is still `ACTIVE`, the client is moved `ACTIVE → SUSPENDED`, freezing everything §3.1 lists as frozen. Note the knock-on effect on revenue: a client carrying one or more strikes pays the 10-percent delinquency surcharge on the administrative fee of every subsequent invoice.

A `FAILED` run can be re-debited: the same `PayrollSpecialist` or `PeoAdmin` capability moves the funding dimension `FAILED → DEBIT_PENDING` again, and this is deliberately permitted **even while the client is `SUSPENDED`**. Funding an already-approved run, and paying down the invoices it produced, is precisely how a suspended client digs itself back out.

### 3.8. Filings: The Quarterly Master-EIN Return, and Client Compliance

Every client's payroll is reported to the tax authority under one number — the `master_ein` recorded on the PEO's master workers'-comp policy, which the filing copies onto itself at creation. A `PeoAdmin` opens a quarterly filing by naming the `year`, the `quarter` (1 through 4) and a `basis` of `CASH` or `ACCRUAL`, defaulting to `CASH`. Only one filing may exist for a given combination of `year`, `quarter` and `basis`; a second is refused with `ERR_DUPLICATE_TAX_FILING`.

The **basis chooses which date decides a run's quarter**, and this is the whole reason both variants exist. Under `CASH`, a run belongs to the quarter containing its `check_date` — the quarter in which wages were actually paid. Under `ACCRUAL`, it belongs to the quarter containing its `period_end` — the quarter in which the wages were earned. A run whose period ends on the last day of June but whose check date falls in early July therefore lands in the third quarter under `CASH` and in the second quarter under `ACCRUAL`, and a second-quarter cash filing and a second-quarter accrual filing over identical data will report different figures. That is the point.

A filing's member set is **derived, never stored on the run**: it is every payroll run, **pooled across every client**, whose `processing_status` is `APPROVED` or `PAID` and whose basis-selected date falls inside the requested quarter's boundaries, inclusive of both the first day of the quarter (January 1, April 1, July 1, October 1) and its last (March 31, June 30, September 30, December 31). Runs still in `DRAFT` or `CALCULATED` are excluded — nothing that has not been approved has any tax consequence. Members are walked in ascending `check_date` order, tie-broken by ascending `created_at` (never by id). At creation the filing records `aggregated_run_count` (the number of members) and three sums over them: `total_taxable_wages_cents`, `total_employee_tax_cents` and `total_employer_tax_cents`, each summing the corresponding already-computed run total. If no run at all falls in the requested quarter under the requested basis, the filing is refused with `ERR_NO_RUNS_IN_PERIOD`. The filing is created in `DRAFT` with a null `filed_at`.

Filing the return, again a `PeoAdmin` act, moves it `DRAFT → FILED` (a terminal state) and stamps `filed_at` with the current logical-clock time. Before it does, it **re-evaluates the member set** — the same derivation, using the filing's stored `year`, `quarter` and `basis` — and requires every member run to have reached `processing_status` `PAID`. A member still sitting at `APPROVED` means the PEO has not actually collected the money it is about to remit, and the filing is refused with `ERR_RUNS_NOT_SETTLED`.

Client-level **compliance filings** are a different animal: they report on one client's workforce, not on money. A `PeoAdmin` opens one against a client with a `filing_type` of `ACA_1095C` or `EEO1` and a `plan_year`. Applicability is checked against the client's derived headcount as §2.9 defines it: `ACA_1095C` requires the client's `is_ale` to be true — refused with `ERR_NOT_APPLICABLE_LARGE_EMPLOYER` otherwise — and `EEO1` requires the client's `fte_count` to be at least 15, refused with `ERR_EEO1_NOT_REQUIRED` otherwise. On creation the filing **snapshots** the client's `fte_count`, `is_ale` and `active_employee_count` onto itself, freezing the workforce picture as of that moment even if the client hires or terminates afterwards, and it is created in `DRAFT` with a null `submitted_at`. Submitting it moves it `DRAFT → SUBMITTED` — terminal — and stamps `submitted_at` with the current logical-clock time.

### 3.9. HR Advisory: Working the Ticket Queue

Clients call their PEO when they are about to do something legally risky. A ticket is raised by a `ClientAdmin` or by an `Employee` against their own client, carrying a `category` of `TERMINATION_ADVICE`, `LEAVE`, `HARASSMENT`, `BENEFITS` or `OTHER`, a `subject` line and a `body`. An optional `worksite_employee_id` names the employee the ticket concerns and is left null for company-level advisory. An optional `priority` of `LOW`, `NORMAL` or `HIGH` defaults to `NORMAL`. The ticket is created in `OPEN` status with `reopen_count` at 0, a null `assigned_advisor_user_id`, and the raising client's `client_id`.

The advisory workflow is driven by a single transition capability carrying an `action`, and it cycles. An `HrAdvisor` picks the ticket up with `ASSIGN`, which moves it `OPEN → IN_PROGRESS` and stamps `assigned_advisor_user_id` with the advisor's `X-User-ID`. From `IN_PROGRESS` the advisor may park it on the client with `AWAIT_CLIENT` (`IN_PROGRESS → AWAITING_CLIENT`), which the `ClientAdmin` un-parks with `CLIENT_REPLY` (`AWAITING_CLIENT → IN_PROGRESS`). The advisor may push a hard question upward with `ESCALATE` (`IN_PROGRESS → ESCALATED`), which also forces the ticket's `priority` to `HIGH` regardless of what it was; a `PeoAdmin` may push it back down with `DEESCALATE` (`ESCALATED → IN_PROGRESS`), though the forced priority is not restored. `RESOLVE` is available from either working state — `IN_PROGRESS → RESOLVED` and `ESCALATED → RESOLVED` alike — and a `RESOLVED` ticket has two exits: the `ClientAdmin` may `REOPEN` it (`RESOLVED → IN_PROGRESS`, adding 1 to `reopen_count`), or the advisor may `CLOSE` it (`RESOLVED → CLOSED`, terminal).

The reopen budget is two. A ticket whose `reopen_count` has already reached 2 may not be reopened a third time, and the attempt is refused with `ERR_TICKET_REOPEN_LIMIT`. Any action that is not declared from the ticket's current status — assigning a ticket that is not `OPEN`, closing one that is not `RESOLVED`, replying on one that is not `AWAITING_CLIENT`, de-escalating one that is not `ESCALATED` — is refused with `ERR_TICKET_ACTION_NOT_ALLOWED`, which is the ticket-specific stand-in for the generic invalid-state refusal used everywhere else in the system. Tickets may be listed and filtered by `client_id`, by `worksite_employee_id` and by `status`; an `Employee` sees only their own, a `ClientAdmin` only their own company's.

---

## 4. Endpoint Definitions

The API is multi-rooted: clients, worksite employees, onboarding packets, workers'-comp policies, benefit plans and enrollments, payroll runs, tax and compliance filings, client invoices and HR tickets each sit at their own top-level path, alongside the `/_clock` test-driving namespace. Endpoints that bring a **new** resource into existence answer with HTTP 201; every other successful call — including every state transition, every calculation and every read — answers with HTTP 200. The table below is a routing summary only; the request payloads, response contents and side effects of each operation are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/clients` | Register a prospective co-employment client. | `PeoAdmin` |
| GET | `/clients/{id}` | Read one client, including the derived ledger, strike count, headcount and ACA figures. | `PeoAdmin`, `PayrollSpecialist`, `HrAdvisor`, `ClientAdmin` |
| POST | `/clients/{id}/activate` | Countersign the co-employment agreement and take the client live. | `PeoAdmin` |
| POST | `/clients/{id}/worksite-employees` | Hire a worksite employee into the client's co-employment relationship. | `PeoAdmin`, `ClientAdmin` |
| GET | `/worksite-employees/{id}` | Employee self-service record: status, benefits eligibility and YTD accumulators. | `PeoAdmin`, `PayrollSpecialist`, `HrAdvisor`, `ClientAdmin`, `Employee` |
| GET | `/worksite-employees` | List worksite employees, filterable by client, workers-comp class and status. | `PeoAdmin`, `PayrollSpecialist`, `HrAdvisor`, `ClientAdmin` |
| POST | `/worksite-employees/{id}/terminate` | Terminate co-employment; cascades into enrollments, pooled seats and ACA headcount. | `PeoAdmin`, `ClientAdmin` |
| POST | `/worksite-employees/{id}/onboarding-packet` | Open a new onboarding packet, superseding any non-terminal packet the employee carries. | `PeoAdmin`, `ClientAdmin` |
| GET | `/worksite-employees/{id}/onboarding-packets` | All packets ever opened for this employee, including voided ones. | `PeoAdmin`, `ClientAdmin`, `Employee` |
| POST | `/onboarding-packets/{id}/submit` | Submit the packet for PEO review, or re-submit a returned one. | `PeoAdmin`, `ClientAdmin` |
| POST | `/onboarding-packets/{id}/review` | PEO review decision: approve the packet or return it for correction. | `PeoAdmin` |
| POST | `/wc-policies` | Create the PEO master workers-comp policy, carrying the master EIN. | `PeoAdmin` |
| GET | `/wc-policies/{id}` | Read the master policy. | `PeoAdmin`, `PayrollSpecialist`, `ClientAdmin` |
| POST | `/wc-policies/{id}/class-codes` | Add a workers-comp class code to the master policy. | `PeoAdmin` |
| GET | `/wc-policies/{id}/class-codes` | List the class codes on a master policy. | `PeoAdmin`, `PayrollSpecialist`, `ClientAdmin` |
| POST | `/benefit-plans` | Create a pooled benefit plan shared across all PEO clients. | `PeoAdmin` |
| GET | `/benefit-plans/{id}` | Read a pooled plan, including seat occupancy and pool status. | `PeoAdmin`, `ClientAdmin`, `Employee` |
| GET | `/benefit-plans/{id}/premium-quote` | Re-price the plan's seated population under a caller-chosen rating method. | `PeoAdmin`, `ClientAdmin` |
| POST | `/clients/{id}/enrollment-windows` | Schedule an open-enrollment window for one client and plan year. | `PeoAdmin` |
| GET | `/clients/{id}/enrollment-windows` | List a client's enrollment windows with their clock-derived status. | `PeoAdmin`, `ClientAdmin`, `Employee` |
| POST | `/worksite-employees/{id}/benefit-enrollments` | Enroll an employee into a pooled plan, occupying and pricing a seat. | `ClientAdmin`, `Employee` |
| GET | `/benefit-enrollments/{id}` | Read one enrollment. | `PeoAdmin`, `ClientAdmin`, `Employee` |
| GET | `/benefit-enrollments` | List enrollments, filterable by employee, plan and status. | `PeoAdmin`, `ClientAdmin`, `Employee` |
| POST | `/benefit-enrollments/{id}/cancel` | Cancel a pending enrollment or terminate an active one; the seat is released. | `PeoAdmin`, `ClientAdmin` |
| POST | `/clients/{id}/payroll-runs` | Open a semi-monthly payroll run for a client. | `PayrollSpecialist`, `PeoAdmin` |
| GET | `/payroll-runs/{id}` | Read a payroll run, including both status dimensions and all computed totals. | `PeoAdmin`, `PayrollSpecialist`, `ClientAdmin` |
| GET | `/payroll-runs` | List payroll runs, filterable by client and by either status dimension. | `PeoAdmin`, `PayrollSpecialist`, `ClientAdmin` |
| GET | `/payroll-runs/{id}/lines` | The generated pay lines of a run. | `PeoAdmin`, `PayrollSpecialist`, `ClientAdmin` |
| GET | `/worksite-employees/{id}/payroll-lines` | Employee self-service pay history. | `PeoAdmin`, `PayrollSpecialist`, `ClientAdmin`, `Employee` |
| POST | `/payroll-runs/{id}/calculate` | Generate or regenerate the run's pay lines, taxes and estimated workers-comp premium. | `PayrollSpecialist`, `PeoAdmin` |
| POST | `/payroll-runs/{id}/approve` | Approve a calculated run; cascades into invoice issue and the client ledger. | `PeoAdmin` |
| POST | `/payroll-runs/{id}/fund` | Initiate, or re-initiate after a return, the ACH debit that funds an approved run. | `PayrollSpecialist`, `PeoAdmin` |
| POST | `/payroll-runs/{id}/funding-events` | Record the bank's answer to a pending debit. | `PeoAdmin` |
| POST | `/tax-filings` | Aggregate every client's payroll for a quarter under the PEO master EIN. | `PeoAdmin` |
| GET | `/tax-filings/{id}` | Read a quarterly master-EIN filing. | `PeoAdmin` |
| POST | `/tax-filings/{id}/file` | File the quarterly return; every member run must already be settled. | `PeoAdmin` |
| POST | `/clients/{id}/compliance-filings` | Open an ACA (1095-C) or EEO-1 filing, snapshotting the client's FTE/ALE figures. | `PeoAdmin` |
| GET | `/clients/{id}/compliance-filings` | List a client's compliance filings. | `PeoAdmin`, `ClientAdmin` |
| POST | `/compliance-filings/{id}/submit` | Submit a compliance filing to the agency. | `PeoAdmin` |
| GET | `/client-invoices/{id}` | Read one client invoice. | `PeoAdmin`, `ClientAdmin` |
| GET | `/client-invoices` | List client invoices, filterable by client, originating payroll run and status. | `PeoAdmin`, `ClientAdmin` |
| GET | `/client-invoices/{id}/lines` | The five invoice lines: administrative fee plus four pass-throughs. | `PeoAdmin`, `ClientAdmin` |
| POST | `/client-invoices/{id}/payments` | Apply a payment to an invoice. | `ClientAdmin` |
| POST | `/client-invoices/{id}/void` | Void an issued invoice — the compensating action for the payroll-approval cascade. | `PeoAdmin` |
| POST | `/clients/{id}/hr-tickets` | Raise an HR advisory ticket. | `ClientAdmin`, `Employee` |
| GET | `/hr-tickets/{id}` | Read one HR ticket. | `PeoAdmin`, `HrAdvisor`, `ClientAdmin`, `Employee` |
| GET | `/hr-tickets` | List HR tickets, filterable by client, employee and status. | `PeoAdmin`, `HrAdvisor`, `ClientAdmin`, `Employee` |
| POST | `/hr-tickets/{id}/transition` | Drive the advisory workflow through its declared actions. | `HrAdvisor`, `PeoAdmin`, `ClientAdmin` |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the server's logical clock. | `PeoAdmin` |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_EMPLOYEE_NOT_FOUND` | 404 |
| `ERR_PACKET_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_CLASS_CODE_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_PAYROLL_RUN_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_TAX_FILING_NOT_FOUND` | 404 |
| `ERR_COMPLIANCE_FILING_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_EMPLOYEE_VERSION` | 412 |
| `ERR_STALE_INVOICE_VERSION` | 412 |
| `ERR_DUPLICATE_FEIN` | 409 |
| `ERR_DUPLICATE_TAX_FILING` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TICKET_ACTION_NOT_ALLOWED` | 409 |
| `ERR_CLIENT_NOT_ACTIVE` | 409 |
| `ERR_PAY_PERIOD_OVERLAP` | 409 |
| `ERR_COVERAGE_OVERLAP` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_RUNS_NOT_SETTLED` | 409 |
| `ERR_ONBOARDING_INCOMPLETE` | 422 |
| `ERR_PACKET_INCOMPLETE` | 422 |
| `ERR_PACKET_REVISION_LIMIT` | 422 |
| `ERR_EMPLOYEE_NOT_BENEFITS_ELIGIBLE` | 422 |
| `ERR_NOT_APPLICABLE_LARGE_EMPLOYER` | 422 |
| `ERR_EEO1_NOT_REQUIRED` | 422 |
| `ERR_TICKET_REOPEN_LIMIT` | 422 |
| `ERR_ENROLLMENT_WINDOW_CLOSED` | 422 |
| `ERR_PLAN_POOL_FULL` | 422 |
| `ERR_NO_PAYABLE_EMPLOYEES` | 422 |
| `ERR_NO_RUNS_IN_PERIOD` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
