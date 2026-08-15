# Airport Concession Rent API — Product Requirements Document

## 1. Introduction

Airport concessions programs live on a deliberate tension between two revenue philosophies. A concessionaire signs a lease that promises the airport a minimum annual guarantee, yet the airport also shares in the tenant's success through percentage rent on gross sales; at year's end the program must reconcile the two figures, invoice the greater obligation, and track every dollar through to collection. Ringing that fiscal core sit the program's compliance instruments — Airport Concession Disadvantaged Business Enterprise (ACDBE) participation goals, street-pricing rules, required operating hours, buildout milestones, and sales-per-enplanement performance floors — each with its own evidence, deadlines, and remedies, and each capable of pushing a lease into default or cure.

This document specifies the Airport Concession Rent API, the system of record for that program, mounted under `/concessions`. It governs the full concession lifecycle: registering concessionaires, originating leases, collecting monthly gross-sales reports, computing the annual settlement under both a provisional and a final reading of the sales data, receiving and voiding payments, exercising audit rights with restatement cascades, scoring ACDBE participation and sales-per-enplanement performance, administering tenant-improvement draws, and enforcing pricing and hours policy through violations and closure waivers. Every rule below is deterministic by construction: a single logical clock governs all calendar comparisons, all money is carried as integer cents, and all rates are carried in basis points, so two independent implementations reading this document should arrive at the same invoice to the cent.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, wire contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. Four roles are recognized — `AirportAdmin`, `ConcessionAnalyst`, `Tenant`, and `Auditor` — and the spelling of each role name is part of the contract. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the acting role must appear in the endpoint's authorized role list as given in §4; otherwise the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `AirportAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The same holds for `ConcessionAnalyst` and for `Auditor`: in both cases `X-User-ID` is opaque and participates in no ownership comparison. When `X-User-Role` is `Tenant`, by contrast, `X-User-ID` is the `id` of the acting `Tenant` record, and ownership checks on any resource that belongs to a lease compare the lease's `tenant_id` against the presented `X-User-ID`. A `Tenant` may read its own tenant record, its own leases, and the children of those leases, and may perform tenant-scoped writes — filing and revising sales reports, submitting them, posting payments, requesting and cancelling buildout draws, requesting closure waivers, and submitting ACDBE cure evidence — only where the owning lease's `tenant_id` equals `X-User-ID`; acting on another tenant's records is rejected with `ERR_FORBIDDEN`.

An `AirportAdmin` is the concessions program administrator and holds the superset of operational powers: registering tenants, creating and amending leases, driving every lease lifecycle transition, opening annual settlements, approving, rejecting, and disbursing buildout draws, deciding waivers, publishing enplanement snapshots, and setting the logical clock. A `ConcessionAnalyst` runs day-to-day review and enforcement: accepting or disputing sales reports, recalculating and invoicing settlements, voiding payments, recording and resolving policy violations, and scheduling and evaluating ACDBE reviews. An `Auditor` exercises the program's gross-sales audit rights: opening audit cases, issuing findings that restate accepted reports, and closing cases; it reads leases, sales reports, and audit cases. All roles may read and list exactly the collections §4 authorizes to them, subject to the tenant-scoping rule above.

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

Framework-level failures map onto the same envelope: a request to an unknown path is rejected with `ERR_NOT_FOUND` (HTTP 404), a known path addressed with an unsupported method is rejected with `ERR_INVALID_REQUEST` carried on an HTTP 405 status, and an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500) — the one error identifier that does not appear in the §5 catalogue.

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100 — a supplied value outside those bounds is clamped to the nearest bound rather than rejected. `offset` skips a number of items before the page begins and defaults to 0, with a negative value clamped up to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns its resources in creation order — earlier-created first — which coincides with ascending creation timestamps unless the logical clock has been moved backward between creations.

Paginated list responses carry four fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when items remain beyond the returned page.

### 2.4. The Program Clock and Calendar Conventions

A single logical clock governs every date and month comparison in the system: no rule ever reads wall-clock time. On startup the clock holds exactly `2026-08-01T00:00:00Z`, and it never falls back to the host's wall clock. Throughout this document, the phrase "current date" means the UTC date of the logical clock, and "current month" means the calendar month, in `YYYY-MM` form, of the logical clock. Every timestamp the API emits — the envelope's `api_request_timestamp` and each resource's `created_at`, `updated_at`, and `submitted_at` — is rendered from this same logical clock.

An admin-only, test-driving capability sets the logical clock to a supplied `to_iso8601` instant and returns the new time as `current_utc`. Advancing the clock is not a passive act: the same request runs the lease expiry sweep (§3.2) and the settlement overdue sweep (§3.5) against the new time, so time-dependent state transitions become visible in the very next read. The supplied instant is unconstrained — the clock may be set backward as well as forward, and the sweeps simply evaluate against whatever time results; a value without a UTC offset is read as UTC, and an unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`. The returned `current_utc` is ISO 8601 UTC, rendered with six fractional digits when the set instant carries sub-second precision and with no fractional part otherwise.

### 2.5. Money, Rates, and Rounding Discipline

All monetary values are integer cents — never floats, never decimal strings — and all percentage rates are basis points, where ten thousand basis points equal one hundred percent; a participation goal of twenty percent, for example, is configured as the integer 2000. Every rounding in the system is round half up.

Rounding order is pinned where aggregation occurs. Monthly percentage rent is rounded to integer cents once per monthly report, before any annual aggregation; annual figures then sum the already-rounded monthly values without re-rounding — never sum-then-round (§3.4). Fractional proration weights used in the annual guarantee computation are rounded half up to four decimal places before they are summed (§3.4). Performance and attainment ratios are rounded half up to integer cents per enplanement and integer basis points respectively (§3.7, §3.8).

### 2.6. Common Resource Properties and the Consistency Model

Every resource in the system — Tenant, Lease, SalesReport, RentSettlement, Payment, AuditCase, ACDBEReview, TIDraw, PolicyViolation, OperatingHoursWaiver, and EnplanementSnapshot — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification.
- `version` (integer): a system-managed counter that starts at 1 at creation and increments by one with every mutation of the resource.

A mutation is any change to a resource's stored properties, including the synchronous recomputation of a derived field. The consistency model is immediate: every mutation is visible in the same response that performs it, and derived fields (§2.9) are recomputed synchronously as part of the triggering write rather than by any background process. Where one operation cascades into child or parent resources — a termination cancelling draws, an audit restatement reopening a settlement — each affected resource independently reflects the change: its `updated_at` refreshes and its `version` increments.

### 2.7. Optimistic Concurrency Control on Lease Terms

Lease-term amendment is the one write in the system guarded by optimistic concurrency control. The amendment request must carry a non-optional `expected_lease_version` field holding the client's last observed `version` of the lease. If that value does not match the lease's current `version` — meaning the lease's version has advanced since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so term edits are always based on the currently observed terms. No other endpoint accepts a version field; transitions, payments, draws, reviews, and all other writes proceed without one.

### 2.8. The Validation Pipeline and Referential Existence

Every request is validated in a fixed pipeline, and a request that violates several checks surfaces the error from the earliest stage. The stages, in order, are:

1. Authentication — the two identity headers are present and the role is declared, else `ERR_UNAUTHENTICATED`.
2. Authorization — the acting role is permitted on the endpoint and, for tenant-scoped writes, the acting tenant owns the target lease, else `ERR_FORBIDDEN`.
3. Existence — every identifier the request names must resolve, else `ERR_NOT_FOUND`. Identifiers in the URL path are validated strictly left to right, so a request addressing a child under a non-existent parent fails on the parent identifier first; foreign-key references in the request body are likewise checked for existence.
4. Request shape — every required field is present and well-typed, else `ERR_INVALID_REQUEST`; an empty string fails presence for a string field, a JSON boolean never satisfies an integer field, and a date or month string outside the `YYYY-MM-DD` / `YYYY-MM` calendar formats is malformed.
5. Enum membership — every enum-typed field carries a declared member, else `ERR_INVALID_ENUM`. This covers `category`, `kind`, `milestone`, `method`, `action`, `reason`, and any status-bearing field supplied by the client.
6. State-machine legality — the requested action is valid from the resource's current status, producing the relevant 409 state error (for example `ERR_LEASE_STATE_FORBIDS`, `ERR_REPORT_NOT_SUBMITTABLE`, or `ERR_DRAW_STATE_FORBIDS`).
7. Uniqueness and occupation constraints — one report per lease and month, one settlement per lease and year, one enplanement snapshot per month, and the premises term-overlap rule, each carrying its own 409 error.
8. Temporal windows — date-range coherence, reporting deadlines, the buildout window, the settlement-year-elapsed rule, and the waiver buffer.
9. Fiscal amount rules — sign and positivity rules, payment caps, allowance caps, and cure sufficiency.
10. Stale-version check — the optimistic-concurrency rule of §2.7 runs last.

Two consequences of this fixed order are worth keeping in mind. On lease creation, the premises-occupation check (stage 7) precedes the date-coherence check (stage 8), so a creation that fails both reports `ERR_PREMISES_TERM_OVERLAP`. On lease amendment, the draft-state check (stage 6) precedes the stale-version check (stage 10), so an amendment aimed at a lease that has left `DRAFT` reports `ERR_LEASE_STATE_FORBIDS` even when its `expected_lease_version` is also stale.

### 2.9. Continuously Reconciled Balances

Two balances on the lease are continuously reconciled rather than computed on demand, and every workflow that touches them recomputes them synchronously. `arrears_cents` is the sum of `balance_due_cents` over the lease's settlements whose status is `INVOICED`, `PARTIALLY_PAID`, or `OVERDUE`; settlements still `ACCRUING` and settlements already `PAID` contribute zero. `ti_remaining_cents` is the lease's `ti_allowance_cents` minus the amounts of its `DISBURSED` draws minus the amounts of its `APPROVED` draws still awaiting disbursement — the approved-but-undisbursed portion is a live reserve — while draws in `REQUESTED`, `REJECTED`, or `CANCELLED` contribute nothing.

Other computed fields are point-in-time snapshots, written once when their triggering event occurs and held thereafter: a violation's `penalty_cents` at creation, a settlement's `due_date` at invoicing, an audit case's `understatement_cents` when findings are issued, a review's `total_gross_cents` and `attainment_bp` at evaluation (the latter recomputed once more at cure), and a report's `submitted_at` at each submission. This distinction — continuously reconciled versus snapshot-at-event — governs which later operations cause a stored figure to move.

## 3. Business Logic & Workflows

This section walks the concession program in the order an airport experiences it: onboarding and lease origination, the lease's lifecycle through default and remarketing, the monthly reporting rhythm, the annual settlement and its collection, audits, participation and performance reviews, and the operational rules governing buildout, pricing, hours, and closures.

### 3.1. Onboarding and Lease Origination

An `AirportAdmin` registers a concessionaire by supplying its `legal_name` and `contact_email`, plus an optional `acdbe_certified` flag — defaulted to `false` when omitted — recording whether the tenant is itself an ACDBE-certified firm.

With a tenant on file, the administrator originates a lease. The creation payload names the concessionaire via `tenant_id` and the airport space via `premises_code`, fixes the concession `category` as one of `FOOD`, `RETAIL`, or `SERVICES`, and sets the term with `term_start_date` and `term_end_date`. The term is a half-open interval: occupation begins on `term_start_date` inclusive, and `term_end_date` is the exclusive boundary day — the premises is free for a new lease whose `term_start_date` equals an existing lease's `term_end_date`. The economic clauses are all captured at creation: `mag_annual_cents`, the minimum annual guarantee per lease year; `pct_rate_below_bp`, the percentage-rent rate in basis points applied to monthly gross at or below the breakpoint; `pct_breakpoint_cents`, the monthly gross-sales breakpoint between the two tiers; `pct_rate_above_bp`, the rate applied to the portion of monthly gross above the breakpoint; `acdbe_goal_bp`, the ACDBE participation goal in basis points of gross sales; `ti_allowance_cents`, the total tenant-improvement buildout allowance; `buildout_deadline`, the date through which draws may be requested and approved; and `min_spe_cents`, the sales-per-enplanement floor used by performance reviews. Creation applies no sign or positivity validation to the economic fields; they are stored exactly as supplied.

A new lease is born in `DRAFT` with `arrears_cents` at zero, `ti_remaining_cents` equal to the full `ti_allowance_cents`, and `default_reason` null. Creation enforces the premises-occupation rule: no two leases in `DRAFT`, `ACTIVE`, or `DEFAULTED` may share a `premises_code` with overlapping half-open terms — adjacency, where one term's start equals the other's end, is allowed — and a violation is rejected with `ERR_PREMISES_TERM_OVERLAP`. Term coherence requires `term_start_date` to be strictly before `term_end_date`, else `ERR_INVALID_DATE_RANGE`; recall from §2.8 that the occupation check runs first.

Activation — an `action` of `ACTIVATE` — moves the lease `DRAFT → ACTIVE`, increments its `version`, and unlocks the operating workflows — most downstream writes (report submission, draw requests, violation recording, waiver requests) require an `ACTIVE` lease. While the lease remains in `DRAFT`, the administrator may amend its economics: any of `mag_annual_cents`, `pct_rate_below_bp`, `pct_breakpoint_cents`, `pct_rate_above_bp`, `acdbe_goal_bp`, `ti_allowance_cents`, `buildout_deadline`, and `min_spe_cents` may be supplied, each individually optional, alongside the mandatory `expected_lease_version` of §2.7. A successful amendment increments the lease's `version` by one; an amendment attempted after the lease has left `DRAFT` is rejected with `ERR_LEASE_STATE_FORBIDS`.

### 3.2. Default, Cure, Termination, and Remarketing

The lease lifecycle is driven by an administrator's transition request carrying an `action` — one of `ACTIVATE`, `DECLARE_DEFAULT`, `CURE_DEFAULT`, `TERMINATE`, or `REMARKET` — with an optional `reason` for the actions that need one. Activation aside, four actions govern the distressed end of the lifecycle.

Declaring default, an `action` of `DECLARE_DEFAULT`, moves an `ACTIVE` lease to `DEFAULTED`. The accompanying `reason` is mandatory for this action — a missing value fails request shape with `ERR_INVALID_REQUEST` — and must be one of `NONPAYMENT`, `HOURS_SHORTFALL`, `ACDBE_NONCOMPLIANCE`, or `OTHER` — an undeclared value fails enum validation with `ERR_INVALID_ENUM` — and is recorded on the lease as `default_reason`; the `reason` field is read only for `DECLARE_DEFAULT` and ignored by every other action. The lease's `version` increments. Curing the default, an `action` of `CURE_DEFAULT`, moves `DEFAULTED → ACTIVE` and clears `default_reason` back to null, again incrementing `version`. The `ACTIVE ↔ DEFAULTED` cycle is repeatable across the life of the lease. Either action attempted from an incompatible status is rejected with `ERR_LEASE_STATE_FORBIDS`.

Termination, an `action` of `TERMINATE`, moves a lease from `ACTIVE` or `DEFAULTED` to `TERMINATED` and triggers a three-part cascade across its children. First, every buildout draw of the lease in `REQUESTED` or `APPROVED` moves to `CANCELLED`. Second, `ti_remaining_cents` is recomputed, which releases the approved-but-undisbursed reserve back into the allowance. Third — an independent child set — every closure waiver of the lease still in `REQUESTED` moves to `REJECTED`. The lease's `version` increments. From `TERMINATED`, a remarketing action — an `action` of `REMARKET` — moves the lease to `REMARKETING`: the premises becomes available again because the lease no longer participates in the premises term-overlap check. `EXPIRED` and `REMARKETING` are terminal. A `DRAFT` lease can be neither terminated nor expired — it must be activated first.

Expiry is time-driven rather than administrator-driven. When the logical clock is advanced (§2.4) such that the new current date is later than a lease's `term_end_date`, every lease in `ACTIVE` or `DEFAULTED` sweeps to `EXPIRED`, with the same child cascades as termination — draws cancelled, the TI reserve released, pending waivers rejected. The boundary is strict: a current date exactly equal to `term_end_date` does not expire the lease, because the end date is already the exclusive boundary day.

### 3.3. Monthly Sales Reporting and Analyst Review

Each month, the tenant files a gross-sales report against its lease, supplying `lease_id`, the `period_month` in `YYYY-MM` form, and `gross_sales_cents`, which may be zero but never negative — a negative figure is rejected with `ERR_INVALID_AMOUNT`. Three guards apply at filing, in pipeline order (§2.8): only one report per lease and month may exist among the statuses `DRAFT`, `SUBMITTED`, `ACCEPTED`, and `ADJUSTED`, with a duplicate rejected as `ERR_REPORT_PERIOD_DUPLICATE`; then the period must not be after the logical clock's current month, else `ERR_REPORT_PERIOD_FUTURE`; then the sign rule on the gross figure. Notably, a `DISPUTED` report does not block a fresh filing for the same month — the dispute loop is resolved either by revising and resubmitting the disputed report or by filing anew. Filing itself does not gate on the lease's lifecycle status; the cross-entity active-lease gate, `ERR_LEASE_NOT_ACTIVE`, applies to exactly four operations in the system — report submission, buildout-draw creation, violation recording, and waiver creation — and each is covered in its own subsection. A new report is born in `DRAFT`.

While a report is in `DRAFT` or `DISPUTED`, the owning tenant may revise its `gross_sales_cents`; each revision increments the report's `version`. A revision attempted on a report in any other status is rejected with `ERR_REPORT_NOT_EDITABLE`.

Submission — a transition request with an `action` of `SUBMIT` — moves the report to `SUBMITTED`. It is valid from `DRAFT` and, after analyst pushback, from `DISPUTED`; from any other status the submission is rejected with `ERR_REPORT_NOT_SUBMITTABLE`. Submission re-checks that the lease is `ACTIVE` and that the acting tenant is the lease's concessionaire, and — following the pipeline of §2.8 — the lease-active check precedes the report-state check, so a submission against a non-active lease surfaces `ERR_LEASE_NOT_ACTIVE` regardless of the report's own status. Each submission stamps `submitted_at` with the logical clock — null until the first submission, refreshed on every resubmission — and increments the report's `version`. An optional free-text `note` may accompany any report transition; it is accepted but not persisted on the report.

Review belongs to the `ConcessionAnalyst`. Acceptance, an `action` of `ACCEPT`, moves `SUBMITTED → ACCEPTED`; disputing, an `action` of `DISPUTE`, moves `SUBMITTED → DISPUTED`; either action attempted on a report that is not `SUBMITTED` is rejected with `ERR_REPORT_NOT_REVIEWABLE`. Acceptance has a cross-entity cascade: if a settlement exists for the lease and the calendar year of the report's `period_month`, that settlement is recalculated under the variant implied by its current status (§3.4), and the owning lease's `version` increments with its `updated_at` refreshed. A dispute simply increments the report's `version`, opening the `SUBMITTED → DISPUTED → SUBMITTED` revision loop. The terminal report status, `ADJUSTED`, is reachable only through an audit (§3.6), which is likewise the only way `restated_gross_sales_cents` — null on every report until then — acquires a value.

### 3.4. The Annual Settlement: MAG Proration and Tiered Percentage Rent

An `AirportAdmin` opens the annual settlement for a lease by naming the `lease_id` and the `period_year` being settled. Only one settlement may exist per lease and year; a second opening is rejected with `ERR_SETTLEMENT_YEAR_DUPLICATE`. The settlement is born in `ACCRUING` with `variant_used` set to `PROVISIONAL` and `due_date` still null, and its first calculation runs immediately.

The guarantee side prorates the annual MAG across the portion of the settlement year inside the lease term. For each calendar month of the year, the covered days are the days of that month intersecting the half-open term from `term_start_date` inclusive to `term_end_date` exclusive. A month with no covered days contributes nothing; a fully covered month contributes a weight of one; a partially covered month contributes the fraction of covered days over the days in that month, rounded half up to four decimal places. The weights sum across the year, and `mag_due_cents` is the lease's `mag_annual_cents` multiplied by that total weight and divided by twelve — twelve months per lease year — rounded half up to integer cents.

The percentage side runs per month over the lease's reports, where a month's effective gross is its `restated_gross_sales_cents` for an `ADJUSTED` report and its `gross_sales_cents` otherwise. Each month applies the two-tier rate structure: when the effective gross is at or below `pct_breakpoint_cents`, the entire gross is charged at `pct_rate_below_bp`; when above, the breakpoint portion is charged at `pct_rate_below_bp` and only the excess above the breakpoint is charged at `pct_rate_above_bp`. Either way the product is divided by ten thousand, since rates are carried in basis points, and rounded half up to integer cents — once per monthly report, before any annual aggregation, per §2.5. The boundary is inclusive: an effective gross exactly equal to `pct_breakpoint_cents` stays in the first tier.

Which months enter the sum depends on the settlement's variant. Under `PROVISIONAL` — while the settlement is `ACCRUING`, mid-year — every month of the settlement year contributes: months with an `ACCEPTED` or `ADJUSTED` report contribute their computed percentage rent, and months without one are projected at one-twelfth of the annual guarantee, rounded half up, so the accrual reflects expected full-year exposure. Under `FINAL` — from invoicing onward — only `ACCEPTED` and `ADJUSTED` reports count, and unreported months contribute zero percentage rent. Reports in `DRAFT`, `SUBMITTED`, or `DISPUTED` never contribute to either variant.

The settlement's stored figures follow directly: `percentage_due_cents` is the sum of the per-month rounded values, without re-rounding; `true_up_due_cents` is the excess of `percentage_due_cents` over `mag_due_cents`, floored at zero, so the tenant always owes at least the guarantee; `amount_due_cents` is `mag_due_cents` plus `true_up_due_cents`; `amount_paid_cents` is the sum of the settlement's `POSTED` payments; and `balance_due_cents` is the difference between the two.

A `ConcessionAnalyst` may recompute a settlement at any point while it is `ACCRUING`, `INVOICED`, `PARTIALLY_PAID`, or `OVERDUE`, and the recomputation uses the variant implied by the current status. Manual recalculation of a `PAID` settlement is forbidden and is rejected with `ERR_SETTLEMENT_STATE_FORBIDS`; a paid year reopens only through audit findings (§3.6) or the payment-void re-derivation of §3.5. Every recalculation also recomputes the lease's `arrears_cents`.

### 3.5. Invoicing, Payments, Voids, and Arrears

Invoicing closes the settlement year. A `ConcessionAnalyst` may invoice only from `ACCRUING` — any other status is rejected with `ERR_SETTLEMENT_NOT_INVOICABLE` — and only once the current date is later than the last day of the `period_year`, that is, once the year has fully elapsed; invoicing earlier is rejected with `ERR_SETTLEMENT_PERIOD_OPEN`. Invoicing performs the final recalculation, sets `variant_used` to `FINAL`, stamps `due_date` as the current date plus thirty days, moves the settlement to `INVOICED`, and recomputes the lease's `arrears_cents`.

The tenant then pays down the invoice. Posting a payment requires the settlement to be in `INVOICED`, `PARTIALLY_PAID`, or `OVERDUE` — a payment aimed at an `ACCRUING` or `PAID` settlement is rejected with `ERR_SETTLEMENT_NOT_PAYABLE`. The payment carries `amount_cents`, which must be positive (`ERR_INVALID_AMOUNT`) and no greater than the settlement's `balance_due_cents` at posting time (`ERR_PAYMENT_EXCEEDS_BALANCE`), and a `method` of `ACH`, `CHECK`, `WIRE`, or `CARD`. The new payment's `settlement_id` is taken from the settlement being paid rather than supplied in the body, and the payment is created in `POSTED` status.

Each posted payment recomputes the settlement's balances and repositions its status. A payment exactly covering the outstanding balance moves an `INVOICED`, `PARTIALLY_PAID`, or `OVERDUE` settlement to `PAID`. A smaller payment moves an `INVOICED` settlement to `PARTIALLY_PAID`, and leaves a `PARTIALLY_PAID` or `OVERDUE` settlement in `PARTIALLY_PAID`. Every posting recomputes the lease's `arrears_cents`.

A `ConcessionAnalyst` may void a payment as the compensating action, valid only while the payment is `POSTED`; voiding an already-`VOIDED` payment is rejected with `ERR_PAYMENT_ALREADY_VOIDED`. The void decrements the settlement's paid total by the voided amount, recomputes the balance, and re-derives the settlement's status: when no `POSTED` payments remain the settlement returns to `INVOICED`, otherwise it sits in `PARTIALLY_PAID`. A void never re-applies `OVERDUE` — that status is restored only by the next clock sweep — and the lease's `arrears_cents` recomputes with the rest.

The overdue sweep runs whenever the logical clock is set (§2.4): a settlement in `INVOICED` or `PARTIALLY_PAID` whose `due_date` is earlier than the new current date, and whose balance remains positive, moves to `OVERDUE`. For an `INVOICED` settlement the accrued arrears value itself does not change — the balance was already counted — so the sweep merely refreshes the lease's `updated_at` (with the per-mutation `version` increment of §2.6); a `PARTIALLY_PAID` settlement carries no further effects at all. A `PAID` settlement never sweeps.

### 3.6. Audit Rights and Restatement

The program's audit rights are exercised through an audit case. An `Auditor` opens a case on a lease by naming the audited window as `period_start_month` and `period_end_month`, both in `YYYY-MM` form and both inclusive; the start must not be after the end, else `ERR_INVALID_DATE_RANGE`. The case is born `OPENED` with `understatement_cents` at zero.

Findings are issued from `OPENED` — from any other status the action is rejected with `ERR_AUDIT_STATE_FORBIDS`. The payload is a set of `findings`, each an object pairing `sales_report_id` — the report reference, also accepted under the fallback alias `report_id` — with `restated_gross_sales_cents`, the auditor's restated gross amount. A finding whose restated amount is missing, non-integer, or negative fails request shape with `ERR_INVALID_REQUEST`, and a finding whose report reference does not resolve is rejected with `ERR_NOT_FOUND`; both of these finding-level failures surface before the audit-state check runs. Every finding must reference a report in `ACCEPTED` status, belonging to the audit's lease, and falling within the audited window; a finding that misses any of those three conditions is rejected with `ERR_AUDIT_FINDING_REPORT_STATE`. All findings are validated as a set before any is applied, so one invalid finding rejects the entire request with every report left untouched. An empty set is accepted: the case moves to `FINDINGS_ISSUED` with `understatement_cents` of zero and no report restated. A report named by two findings in one request is restated in payload order, ending with the later amount, and each finding contributes its own restated-minus-original delta to `understatement_cents`.

Issuing findings sets off the widest cascade in the system. Each referenced report moves `ACCEPTED → ADJUSTED`, with its `restated_gross_sales_cents` set to the finding's restated amount. The audit case records `understatement_cents`, the sum over the adjusted reports of the restated gross minus the originally reported gross — a figure that may legitimately be zero. The settlement of each affected year is then recalculated under `FINAL` semantics, and if the recalculated `amount_due_cents` rises above the `amount_paid_cents`, a `PAID` settlement reopens to `PARTIALLY_PAID` with its balance recomputed; this reopen and the payment-void re-derivation of §3.5 are the only ways out of `PAID`. Finally the lease's `arrears_cents` is recomputed from the settlement balances, and the case moves to `FINDINGS_ISSUED`.

Closing is available from `OPENED` — an audit that finds nothing — and from `FINDINGS_ISSUED`, moving the case to its terminal `CLOSED` with no further effects; any audit action from a status that forbids it is rejected with `ERR_AUDIT_STATE_FORBIDS`.

### 3.7. ACDBE Participation Reviews

Each year, participation against the lease's ACDBE goal is scored through a review. A `ConcessionAnalyst` schedules the review by naming the lease and the `period_year`; the review is born `SCHEDULED`.

At evaluation, the analyst declares the year's `certified_revenue_cents` — the revenue attributable to ACDBE-certified participation; a negative declaration fails request shape with `ERR_INVALID_REQUEST`. The system computes `total_gross_cents`, the year's effective gross summed over the lease's `ACCEPTED` and `ADJUSTED` reports, and `attainment_bp`, the certified revenue multiplied by ten thousand, divided by the total gross, and rounded half up to integer basis points. Both figures are stored on the review. When the year's total gross is zero, attainment is zero and the outcome is `DEFICIENT`. Otherwise, attainment at or above the lease's `acdbe_goal_bp` — meeting the goal exactly attains it — is `COMPLIANT`, and anything below is `DEFICIENT`. Evaluation is valid only from `SCHEDULED`; from any other status it is rejected with `ERR_REVIEW_STATE_FORBIDS`.

A `DEFICIENT` outcome is curable. The owning tenant submits `cure_additional_certified_cents` — a negative amount fails request shape with `ERR_INVALID_REQUEST` — and attainment is recomputed with the cure amount added to the certified revenue against the stored total gross. If the recomputed attainment still falls short of the goal, the cure is rejected with `ERR_CURE_INSUFFICIENT` and the review's stored figures are left unchanged; on success the submitted amount is recorded as the review's `cure_additional_certified_cents` — zero until a cure succeeds — the recomputed attainment is stored, and the review moves to `CURED`. A cure attempted from any status other than `DEFICIENT` is rejected with `ERR_REVIEW_STATE_FORBIDS`. Curing a review does not clear a declared lease default — the lease's `default_reason` is untouched — so participation remediation and default remediation remain separate tracks. `COMPLIANT` and `CURED` are the terminal outcomes.

### 3.8. Sales-per-Enplanement Performance

Performance review compares what a concession sells against how many passengers the airport delivers. An `AirportAdmin` publishes each month's traffic as an enplanement snapshot keyed by `month` in `YYYY-MM` form, carrying the month's `enplanements`, which must be positive — a non-positive count is rejected with `ERR_INVALID_AMOUNT`. One snapshot exists per month across the whole program; a duplicate month is rejected with `ERR_ENPLANEMENT_MONTH_DUPLICATE`.

The performance read on a lease — available to the administrator, the analyst, and the owning tenant — returns five figures: `spe_ttm_cents`, `spe_ytd_cents`, `sales_ttm_cents`, `enplanements_ttm`, and `review_outcome`.

Two windows are always computed, and they can disagree because they anchor differently. The trailing-twelve-month window covers the twelve calendar months ending at the latest month having an `ACCEPTED` or `ADJUSTED` report. The year-to-date window covers the months of the logical clock's calendar year up to and including the current month. Within each window, a month qualifies only when both sides of the ratio exist — an effective sales figure from an `ACCEPTED` or `ADJUSTED` report, and an enplanement snapshot — and months missing either side are excluded from both the numerator and the denominator. Sales per enplanement is the window's total sales multiplied by one hundred, divided by the window's total enplanements, and rounded half up to integer cents per enplanement. A window with zero qualifying months yields a null figure; `sales_ttm_cents` and `enplanements_ttm` are reported as zero, never null, in that case.

The `review_outcome` is read off the trailing figure: `INSUFFICIENT_DATA` when `spe_ttm_cents` is null, `UNDERPERFORMING` when it is below the lease's `min_spe_cents` floor, and `SATISFACTORY` when it is at or above the floor — the boundary is satisfactory.

### 3.9. Buildout Draws, Policy Enforcement, and Closure Waivers

Buildout draws meter the tenant-improvement allowance. The owning tenant requests a draw by naming the lease, an `amount_cents`, and a `milestone` of `DESIGN`, `CONSTRUCTION`, `FIXTURES`, or `GRAND_OPENING`. Four guards apply at request time, in pipeline order: the lease must be `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`); the current date must be at or before the lease's `buildout_deadline` (`ERR_BUILDOUT_WINDOW_CLOSED`); the amount must be positive (`ERR_INVALID_AMOUNT`); and the amount must not exceed the lease's `ti_remaining_cents` at that moment (`ERR_TI_ALLOWANCE_EXCEEDED`). A new draw is born `REQUESTED`, and while `REQUESTED` it consumes nothing from the allowance.

An `AirportAdmin` decides the draw. Approval, an `action` of `APPROVE`, moves `REQUESTED → APPROVED` and requires the lease still `ACTIVE` and the current date still at or before the `buildout_deadline`; any failed precondition at decision time is rejected as an invalid draw transition with `ERR_DRAW_STATE_FORBIDS`. Approval converts the amount into the approved-pending reserve, recomputing `ti_remaining_cents`. Disbursement, an `action` of `DISBURSE`, moves `APPROVED → DISBURSED`, converting the reserve into a disbursed amount with `ti_remaining_cents` recomputed again. Rejection, an `action` of `REJECT`, moves `REQUESTED → REJECTED` with no fiscal effect. The owning tenant may cancel its own draw with an `action` of `CANCEL`: a `REQUESTED` draw cancels with no fiscal effect, while cancelling an `APPROVED` draw releases the reserve and recomputes `ti_remaining_cents`. Any action invalid from the draw's current status is rejected with `ERR_DRAW_STATE_FORBIDS`, and termination or expiry of the parent lease cascades cancellations per §3.2. `REJECTED`, `DISBURSED`, and `CANCELLED` are terminal.

Street-pricing and operating-hours enforcement runs through violations. A `ConcessionAnalyst` records a violation against an `ACTIVE` lease — a non-active lease yields `ERR_LEASE_NOT_ACTIVE` — supplying the `lease_id`, the `kind` (`STREET_PRICING` or `OPERATING_HOURS`), the `observed_date`, and the kind-specific measure: `shortfall_minutes`, the positive number of minutes the location fell short of required operating hours that day, for `OPERATING_HOURS`, or `overcharge_cents`, the positive difference between the observed price and the street price, for `STREET_PRICING`. The active-lease gate precedes the measure checks, so a recording against a non-active lease surfaces `ERR_LEASE_NOT_ACTIVE` even when the kind-specific measure is missing or malformed; a missing or non-integer measure otherwise fails request shape with `ERR_INVALID_REQUEST`, a non-positive measure fails with `ERR_INVALID_AMOUNT`, and the measure field of the inapplicable kind is stored as null. The `penalty_cents` is assessed once, at creation. An operating-hours violation costs 25,000 cents — two hundred fifty dollars — per commenced hour of shortfall, so any partial hour counts as a full hour. A street-pricing violation costs the greater of 5,000 cents — a fifty-dollar minimum — or twice the overcharged amount. When exposure is aggregated for a month, the per-violation penalties are summed; the shortfall minutes of separate events are never summed first and converted once. A violation is born `OPEN`, and an analyst resolves it to `RESOLVED`; resolving a violation that is not `OPEN` is rejected with `ERR_VIOLATION_ALREADY_RESOLVED`.

Closure waivers let a tenant bank temporary relief from the operating-hours requirement. The owning tenant requests a window from `closure_start_date` to `closure_end_date`, both days inclusive, with a required free-form `reason` — a missing or empty reason fails request shape with `ERR_INVALID_REQUEST`. The lease must be `ACTIVE`, else `ERR_LEASE_NOT_ACTIVE`, and the start must not be after the end, else `ERR_INVALID_DATE_RANGE`; the active-lease gate runs first (§2.8), so a request failing both surfaces `ERR_LEASE_NOT_ACTIVE`. The waiver is born `REQUESTED`. An `AirportAdmin` then decides it with an `action` of `APPROVE` or `REJECT`; acting on a waiver that has left `REQUESTED` is rejected with `ERR_WAIVER_STATE_FORBIDS`. Approval enforces a fourteen-day buffer against the lease's other approved closures: for every other `APPROVED` waiver of the same lease, the two windows must be separated by at least fourteen days, measured from the end of one window to the start of the other with at least one direction yielding fourteen days or more — overlapping windows yield a negative gap in both directions and always fail. A violation of the buffer is rejected with `ERR_WAIVER_BUFFER_VIOLATION`. Termination or expiry of the parent lease rejects any still-pending waivers per §3.2, and `APPROVED` and `REJECTED` are terminal.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that modify an existing resource, drive a state transition, post a compensating action, or perform a read return `200 OK`. List endpoints accept `limit` and `offset` (§2.3) plus optional filter query parameters matching the resource's natural keys — `tenant_id`, `premises_code`, `status`, `lease_id`, `period_month`, or `kind`, depending on the collection; a `status` or `kind` filter carrying an undeclared member is rejected with `ERR_INVALID_ENUM`, while other filters match literally. Request payloads, response bodies, and side effects are exactly as described in the §3 narratives; the table below is a summary, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/concessions/tenants` | Register a concessionaire | AirportAdmin |
| GET | `/concessions/tenants` | List tenants (paginated) | AirportAdmin, ConcessionAnalyst |
| GET | `/concessions/tenants/{id}` | Get one tenant | AirportAdmin, ConcessionAnalyst, Tenant |
| POST | `/concessions/leases` | Create a concession lease (DRAFT); premises term-overlap check applies | AirportAdmin |
| GET | `/concessions/leases` | List leases with optional filters | AirportAdmin, ConcessionAnalyst, Tenant, Auditor |
| GET | `/concessions/leases/{id}` | Get one lease including computed arrears and TI remaining | AirportAdmin, ConcessionAnalyst, Tenant, Auditor |
| PATCH | `/concessions/leases/{id}` | Amend lease economics (DRAFT only) with OCC on the lease version | AirportAdmin |
| POST | `/concessions/leases/{id}/transition` | Lease lifecycle action: ACTIVATE, DECLARE_DEFAULT, CURE_DEFAULT, TERMINATE, REMARKET | AirportAdmin |
| GET | `/concessions/leases/{id}/performance` | Sales-per-enplanement review read (TTM and YTD) | AirportAdmin, ConcessionAnalyst, Tenant |
| POST | `/concessions/sales-reports` | Tenant files a monthly gross-sales report (DRAFT) | Tenant |
| GET | `/concessions/sales-reports` | List sales reports with optional filters | AirportAdmin, ConcessionAnalyst, Tenant, Auditor |
| GET | `/concessions/sales-reports/{id}` | Get one sales report | AirportAdmin, ConcessionAnalyst, Tenant, Auditor |
| PATCH | `/concessions/sales-reports/{id}` | Revise gross sales while DRAFT or DISPUTED | Tenant |
| POST | `/concessions/sales-reports/{id}/transition` | Report lifecycle action: SUBMIT (Tenant), ACCEPT or DISPUTE (ConcessionAnalyst) | Tenant, ConcessionAnalyst |
| POST | `/concessions/settlements` | Open the annual settlement for a lease and year (ACCRUING) | AirportAdmin |
| GET | `/concessions/settlements` | List settlements with optional filters | AirportAdmin, ConcessionAnalyst, Tenant |
| GET | `/concessions/settlements/{id}` | Get one settlement | AirportAdmin, ConcessionAnalyst, Tenant |
| POST | `/concessions/settlements/{id}/recalculate` | Recompute MAG, percentage, and true-up with the variant implied by current status | ConcessionAnalyst |
| POST | `/concessions/settlements/{id}/invoice` | Close the year: FINAL recalculation, due date set, status INVOICED | ConcessionAnalyst |
| POST | `/concessions/settlements/{id}/payments` | Tenant posts a payment against the settlement | Tenant |
| GET | `/concessions/settlements/{id}/payments` | List payments of a settlement | AirportAdmin, ConcessionAnalyst, Tenant |
| POST | `/concessions/payments/{id}/void` | Void a POSTED payment (compensating action) | ConcessionAnalyst |
| POST | `/concessions/audits` | Open an audit case on a lease for a month window (OPENED) | Auditor |
| GET | `/concessions/audits` | List audit cases with optional filters | AirportAdmin, ConcessionAnalyst, Auditor |
| GET | `/concessions/audits/{id}` | Get one audit case | AirportAdmin, ConcessionAnalyst, Auditor |
| POST | `/concessions/audits/{id}/issue-findings` | Issue findings: restate ACCEPTED reports, triggering settlement and arrears cascades | Auditor |
| POST | `/concessions/audits/{id}/close` | Close an audit case | Auditor |
| POST | `/concessions/acdbe-reviews` | Schedule an annual ACDBE participation review | ConcessionAnalyst |
| GET | `/concessions/acdbe-reviews` | List ACDBE reviews with optional filters | AirportAdmin, ConcessionAnalyst, Tenant |
| GET | `/concessions/acdbe-reviews/{id}` | Get one ACDBE review | AirportAdmin, ConcessionAnalyst, Tenant |
| POST | `/concessions/acdbe-reviews/{id}/evaluate` | Score participation: COMPLIANT if attainment meets the goal, else DEFICIENT | ConcessionAnalyst |
| POST | `/concessions/acdbe-reviews/{id}/cure` | Tenant submits cure evidence (additional certified revenue) | Tenant |
| POST | `/concessions/ti-draws` | Tenant requests a buildout draw against the TI allowance | Tenant |
| GET | `/concessions/ti-draws` | List TI draws with optional filters | AirportAdmin, ConcessionAnalyst, Tenant |
| GET | `/concessions/ti-draws/{id}` | Get one TI draw | AirportAdmin, ConcessionAnalyst, Tenant |
| POST | `/concessions/ti-draws/{id}/transition` | Draw lifecycle action: APPROVE, REJECT, DISBURSE (AirportAdmin); CANCEL (Tenant) | AirportAdmin, Tenant |
| POST | `/concessions/violations` | Record a street-pricing or operating-hours violation; penalty assessed at creation | ConcessionAnalyst |
| GET | `/concessions/violations` | List violations with optional filters | AirportAdmin, ConcessionAnalyst, Tenant |
| GET | `/concessions/violations/{id}` | Get one violation | AirportAdmin, ConcessionAnalyst, Tenant |
| POST | `/concessions/violations/{id}/resolve` | Resolve an OPEN violation | ConcessionAnalyst |
| POST | `/concessions/waivers` | Tenant requests a temporary closure window | Tenant |
| GET | `/concessions/waivers` | List waivers with optional filters | AirportAdmin, ConcessionAnalyst, Tenant |
| GET | `/concessions/waivers/{id}` | Get one waiver | AirportAdmin, ConcessionAnalyst, Tenant |
| POST | `/concessions/waivers/{id}/transition` | Waiver decision: APPROVE (with the fourteen-day buffer check) or REJECT | AirportAdmin |
| POST | `/concessions/enplanement-snapshots` | Publish the monthly enplanement count (month unique) | AirportAdmin |
| GET | `/concessions/enplanement-snapshots` | List enplanement snapshots | AirportAdmin, ConcessionAnalyst, Tenant |
| POST | `/_clock/set_current_utc` | Set the logical clock; runs the lease expiry and settlement overdue sweeps | AirportAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue is a lookup of identifiers to statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_LEASE_NOT_ACTIVE` | 409 Conflict |
| `ERR_LEASE_STATE_FORBIDS` | 409 Conflict |
| `ERR_REPORT_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_REPORT_NOT_EDITABLE` | 409 Conflict |
| `ERR_REPORT_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PAYABLE` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_INVOICABLE` | 409 Conflict |
| `ERR_SETTLEMENT_STATE_FORBIDS` | 409 Conflict |
| `ERR_PAYMENT_ALREADY_VOIDED` | 409 Conflict |
| `ERR_DRAW_STATE_FORBIDS` | 409 Conflict |
| `ERR_WAIVER_STATE_FORBIDS` | 409 Conflict |
| `ERR_AUDIT_STATE_FORBIDS` | 409 Conflict |
| `ERR_AUDIT_FINDING_REPORT_STATE` | 409 Conflict |
| `ERR_REVIEW_STATE_FORBIDS` | 409 Conflict |
| `ERR_VIOLATION_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_PREMISES_TERM_OVERLAP` | 409 Conflict |
| `ERR_REPORT_PERIOD_DUPLICATE` | 409 Conflict |
| `ERR_SETTLEMENT_YEAR_DUPLICATE` | 409 Conflict |
| `ERR_ENPLANEMENT_MONTH_DUPLICATE` | 409 Conflict |
| `ERR_BUILDOUT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_WAIVER_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_REPORT_PERIOD_FUTURE` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_PERIOD_OPEN` | 422 Unprocessable Entity |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_TI_ALLOWANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CURE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
