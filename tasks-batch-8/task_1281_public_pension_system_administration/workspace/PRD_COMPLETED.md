# Public Pension Administration API — Product Requirements Document

## 1. Introduction

A state or municipal pension fund lives and dies by the accuracy of its ledgers. Members accrue service credit across decades of employment, employers remit contribution reports that must reconcile to the cent, and a single miscalculation in a final average salary propagates into thirty years of monthly payments. This document specifies the Public Pension Administration API: a system that administers the full arc of a public employee's pension — enrollment and service credit accrual, purchase of military or prior service, employer contribution reporting and reconciliation, retirement and disability application processing, cost-of-living adjustments, return-to-work earnings surveillance, and survivor benefit processing.

The fund's operating reality imposes three structural demands on the design. First, every money figure is an integer number of cents and every derived quantity is recomputed from source records rather than accumulated incrementally, so that an auditor can always walk from a monthly benefit back to the contribution lines that produced it. Second, the workflow enforces segregation of duties: the caseworker who reviews a retirement application may not be the approver who signs off on it, and a disability appeal must be decided by a fresh pair of medical eyes. Third, time itself is a controlled input — vesting windows, quote expirations, appeal deadlines, and claim filing windows all evaluate against a logical clock that the fund administrator can set, because pension rules speak in calendar years and months rather than server uptime.

The audience for this document is the engineering team building the API. Business rules are stated as the fund's caseworkers and actuaries state them; the HTTP contract is summarized at the end. Where a rule has a boundary — an inclusive threshold, a strict inequality, a closed versus half-open interval — the boundary is stated exactly, because these boundaries are where pension disputes are won and lost.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the acting party, and `X-User-Role` declares the capacity in which they act. A request missing either header, or presenting a role name the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly seven roles. **FundAdmin** is the pension fund administrator: fund configuration, COLA runs, employer registration, and the logical clock. **MemberServicesAnalyst** is the fund caseworker: enrollment, contribution line review and finalization, purchase quotes, application intake and review, and benefit reinstatement. **BenefitApprover** is the approving authority for retirement approvals and survivor claims, deliberately separated from the reviewing caseworker. **MedicalReviewer** is the independent medical reviewer for disability cases. **EmployerClerk** is the employer's reporting clerk. **Member** is the pension member acting in self-service. **SurvivorClaimant** is a designated beneficiary filing a survivor claim.

For four roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. These are FundAdmin, MemberServicesAnalyst, BenefitApprover, and MedicalReviewer. The server may record such an identifier where a workflow calls for it — for example as `reviewed_by_user_id` on a retirement application when an analyst moves it to `UNDER_REVIEW`, or as `submitted_by_user_id` and `last_reviewer_user_id` on a disability application — but it never compares these opaque identifiers against any entity's `id`.

For three roles, `X-User-ID` is entity-backed. When `X-User-Role` is EmployerClerk, `X-User-ID` is the `id` of the acting Employer, and the clerk may only touch that employer's contribution reports and lines; the same scoping governs every employer-scoped read the clerk is authorized for — the employer's own record, its member and report lists, individual report and line reads, and the contribution-line lists of members employed by it — so a clerk presenting another employer's id (or targeting a member of another employer) is `ERR_FORBIDDEN`. When `X-User-Role` is Member, `X-User-ID` is the `id` of the acting Member, and ownership checks compare the owning member id of the targeted resource against `X-User-ID`. When `X-User-Role` is SurvivorClaimant, `X-User-ID` is the `id` of the acting Beneficiary designation, and the claimant may file a claim only on the designation whose `id` equals `X-User-ID`; likewise, the claimant's reads of a member record and of the member's benefit and designation lists are limited to the member that designation belongs to — a claimant whose `X-User-ID` matches no designation of the targeted member is `ERR_FORBIDDEN`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server wall clock (never from the logical clock of §2.5).
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

List endpoints accept two query parameters (equivalently, they may be supplied in the JSON request body). `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and may not be negative. A non-integer or out-of-range value for either is `ERR_INVALID_REQUEST`. Results are always sorted by `created_at` ascending, with ties — common under a frozen logical clock — broken by creation order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through an employer's reports or a member's contribution history without holding the collection in memory. The same query-or-body convention applies to the non-list parameters `variant` (benefit estimate) and `fiscal_year` (member contribution-line filter), and a non-integer `fiscal_year` is likewise `ERR_INVALID_REQUEST`.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — plus `created_at` and `updated_at` timestamps rendered as ISO 8601 UTC with three fractional digits and stamped from the logical clock (§2.5) at the moment of creation or mutation, and an integer `version` that starts at 1 and increments by exactly 1 on every mutation of that resource, including mutations performed as side effects of operations on other resources. The `version` counter is the linchpin of optimistic concurrency control (§2.6): it is what a client reads, holds, and later presents back when it wants to write against the state it observed. Action timestamps outside the common pair — `quote_expires_at`, `applied_at`, `decided_at`, `claim_filed_at` — render as ISO 8601 UTC at seconds precision when the instant lands on a whole second, and with three fractional digits otherwise.

All entities in this domain — funds, employers, members, contribution reports and lines, service purchases and their payments, retirement and disability applications, benefits, and beneficiary designations — carry the full set of common fields; none is a bare create-only record.

### 2.5. The Logical Clock

All time-dependent rules in the fund — retirement age, quote expiry, appeal windows, claim deadlines, COLA eligibility months, effective dates — evaluate against a logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z` and holds that fixed instant until a FundAdmin sets it via the test-driving capability, which accepts a `to_iso8601` instant (a malformed or missing `to_iso8601` is `ERR_INVALID_REQUEST`) and responds 200 with `{"current_utc": <the new instant>}`; from then on, every subsequent rule evaluation uses the new logical time. This design lets a test suite or a demonstration walk a member through thirty years of service in an afternoon.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control. In each case the request body may carry a version field naming the client's last observed `version` of the entity being acted upon; when the field is present and its value does not match the entity's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing changes, and when the field is absent the write proceeds without a version check. The guarded operations are:

- Final approval of a retirement application takes `expected_application_version`, matching the current `version` of the application itself. If another writer — a review cycle, or any cascade — has advanced the application's version since the approver last read it, the approval is rejected, forcing the approver to re-read the application before re-issuing.
- Applying an installment payment takes `expected_purchase_version`, matching the current `version` of the parent service purchase. Because each successful payment itself increments the purchase's `version`, a payer who has not re-read the purchase since the prior payment will be rejected, preventing a payment from being booked against a balance the payer never observed.
- Updating fund configuration takes `expected_fund_version`, matching the current `version` of the pension fund. A configuration change issued against an unobserved fund version is rejected.

Endpoints not named above do not take a version field at all.

### 2.7. Monetary Precision, Rounding, and Units

All money is stored and transmitted as integer cents — `contribution_amount_cents`, `period_salary_cents`, `monthly_amount_cents`, and their siblings. Wherever a calculation produces a fractional cent, the result is rounded half-up to the nearest whole cent, exactly once per calculation step the formula prescribes; the benefit estimate in particular performs a single final rounding with no intermediate rounding. Service credit, by contrast, is expressed in years with exactly two decimal places, also rounded half-up. Rates and factors are decimal fractions: the fund's `cola_rate_pct` of 0.025 means 2.5 percent per year, the flat purchase rate is 0.10 of current annual salary per year purchased, and the disability benefit draws 0.60 of the final average salary.

### 2.8. Validation Order

When a request fails several rules at once, the error the client sees is determined by a fixed evaluation order, not by implementation convenience. The order, from first to last, is:

1. **Authentication** — the headers are present and the role is known (`ERR_UNAUTHENTICATED`).
2. **Authorization and ownership** — the role is listed for the endpoint and any entity-backed ownership check passes (`ERR_FORBIDDEN`).
3. **Segregation of duties** — on the two endpoints that enforce it, the approver or appeal reviewer is not the previously recorded reviewer (`ERR_SEGREGATION_OF_DUTIES`).
4. **Existence** — every path id exists, validated left to right, and every foreign-key reference in the body resolves (`ERR_NOT_FOUND`).
5. **Optimistic concurrency** — the `expected_*_version` field matches (`ERR_STALE_VERSION`).
6. **State gates** — generic invalid from-state (`ERR_INVALID_STATE`), member lifecycle gates (`ERR_MEMBER_NOT_ACTIVE`, `ERR_MEMBER_DECEASED`), and resource-specific status gates (`ERR_PLAN_NOT_ACTIVE`, `ERR_BENEFIT_NOT_ACTIVE`, `ERR_BENEFIT_NOT_TERMINATED`).
7. **Single-active-application guard** — at most one non-terminal application of each type per member (`ERR_ACTIVE_APPLICATION_EXISTS`).
8. **Referential business rules** — survivor entitlement and designation status (`ERR_NO_SURVIVOR_ENTITLEMENT`, `ERR_DESIGNATION_REVOKED`), and required-field shape for joint options (`ERR_INVALID_REQUEST`).
9. **Clock-relative windows** — quote expiry, appeal window, claim deadline (`ERR_QUOTE_EXPIRED`, `ERR_APPEAL_WINDOW_CLOSED`, `ERR_CLAIM_DEADLINE_PASSED`).
10. **Interval and uniqueness constraints** — report period overlap, purchase period overlap, duplicate line period, installment bounds (`ERR_REPORT_PERIOD_OVERLAP`, `ERR_PURCHASE_PERIOD_OVERLAP`, `ERR_DUPLICATE_LINE_PERIOD`, `ERR_INVALID_REQUEST`).
11. **Eligibility and fiscal gates** — vesting, retirement age, outstanding purchase balances, and reconciliation outcomes (`ERR_NOT_VESTED`, `ERR_MEMBER_UNDER_RETIREMENT_AGE`, `ERR_OUTSTANDING_BALANCE`, `ERR_LINES_PENDING`, `ERR_RECONCILIATION_VARIANCE`).

A concrete consequence: an approval request that is both stale and from the wrong approver surfaces `ERR_SEGREGATION_OF_DUTIES` only after passing authentication and authorization, but a stale version surfaces before any state-gate complaint, because OCC is evaluated ahead of state.

### 2.9. Hierarchy, Nested Retrieval, and Recompute-on-Read Discipline

Paths that nest one resource under another — an employer's contribution reports, a member's retirement applications, a report's lines — validate their path identifiers from left to right: the outermost id must resolve before the inner id is examined, and the inner resource must genuinely belong to the outer one, otherwise the request is `ERR_NOT_FOUND`. Foreign keys are never declared in responses as such; a contribution line reaches its member because the line was created with a payload containing the `member_id`, and a service purchase reaches its member likewise.

Derived member aggregates are never accumulated incrementally as a running tally that could drift. Each time a contribution line is accepted or rejected, or a service purchase completes, the member's `total_service_years` and `current_annual_salary_cents` are recomputed in full from the underlying source records, per the formulas of §3.2. This recompute-on-event discipline is what keeps the audit trail consistent: the member record is always a pure function of its lines and purchases. A recompute that leaves every stored value unchanged is not a mutation and advances no `version` — the member's `version` increments only when a recomputed aggregate actually differs, and a contribution report's `version` likewise increments only when its `accepted_total_cents` or `status` changes (so a line rejection, which never alters the accepted total, does not by itself advance the report's version).

## 3. Business Logic & Workflows

### 3.1. Fund Configuration and the Rhythm of the Plan Year

Everything begins with the pension fund itself. A FundAdmin creates the fund with a display `fund_name`, the annual `cola_rate_pct` expressed as a decimal fraction, and the `earnings_limit_annual_cents` that governs return-to-work retirees. The earnings limit deserves emphasis: it is the calendar-year ceiling on what a retiree may earn before the benefit suspends, and suspension triggers only when year-to-date earnings strictly exceed it — a retiree whose earnings land exactly on the limit keeps the benefit. Fund configuration is thereafter mutable only through the OCC-guarded update described in §2.6; each successful update increments the fund's `version`. Only `cola_rate_pct` and `earnings_limit_annual_cents` are mutable — `fund_name` is fixed at creation and ignored if supplied in an update.

Employers are registered by the FundAdmin with a display `name` and an `employer_code` that must be unique across all employers — the code is how remittance files are matched to reporting units; a duplicate code is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Once an employer exists, a MemberServicesAnalyst enrolls members against it. Enrollment captures the member's `full_name`, `date_of_birth` as an ISO date, and `hire_date` — the pension system entry date that later decides which service-purchase pricing window applies — along with the `employer_id` of the employing unit. A newly enrolled member starts in `ACTIVE` status with `total_service_years` at zero and `current_annual_salary_cents` null, because no contribution has yet been credited; system-managed fields (`status`, `total_service_years`, `current_annual_salary_cents`, `deceased_at`) supplied in the enrollment payload are ignored.

Member lifecycle is otherwise deliberately thin. An analyst may move a member between `ACTIVE` and `INACTIVE` — in either direction — by patching the `status`; those two pairs are the only status transitions a patch can drive, any other target state (including a direct patch to `RETIRED` or `DECEASED`) is `ERR_INVALID_STATE`, and an unrecognized status string is `ERR_INVALID_REQUEST`. Setting `deceased_at` records the member's death and moves the member to `DECEASED` from `ACTIVE`, `INACTIVE`, `RETIRED`, or `SUSPENDED_RTW`; the consequences of that transition are substantial and are described in §3.7. `DECEASED` is the only terminal member state — recording death on an already-`DECEASED` member is `ERR_INVALID_STATE`. A patch carrying neither `status` nor `deceased_at` changes nothing and advances no version.

### 3.2. Service Credit Accrual and Salary Derivation

The fund measures service in years to two decimal places, rounded half-up, and derives it from exactly two sources. The first is employer-reported contribution lines: each accepted line contributes its `service_months` — an integer from 1 to 12, defaulting to 12 when not supplied — divided by twelve months per year. The second is completed service purchases, each contributing its `years_purchased`. A member's `total_service_years` is the rounded half-up sum, to two decimal places, of all `service_months` over that member's contribution lines in `ACCEPTED` status divided by twelve, plus the sum of `years_purchased` over the member's service purchases in `COMPLETED` status. Lines in `PENDING` or `REJECTED` never count; purchases still on a payment plan never count.

The member's `current_annual_salary_cents` answers a different question: what is this member's pay right now, for pricing service purchases? It is the `period_salary_cents` of the member's `ACCEPTED` contribution line with the highest `fiscal_year`; if two accepted lines share the highest fiscal year, the tie is broken by the later line `created_at`, and any remaining tie (identical timestamps under a frozen clock) by creation order. When a member has no accepted line at all, `current_annual_salary_cents` is null — which, as §3.4 explains, blocks quoting a service purchase. Both aggregates are fully recomputed from source on every triggering event, never patched incrementally.

### 3.3. Employer Contribution Reporting and Reconciliation

Each reporting period, an EmployerClerk opens a contribution report for the clerk's employer by supplying `period_start`, `period_end`, and `declared_total_cents` — the employer's declared contribution total for the period. The period is a half-open interval: it includes `period_start` and runs up to but does not include `period_end`, and it must be non-empty — a `period_end` on or before `period_start` is `ERR_INVALID_REQUEST`. Two reports of the same employer may not overlap, though adjacency is allowed — a new report whose `period_start` equals the prior report's `period_end` is legal. A violating report create is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409). The report is born in `DRAFT` with `accepted_total_cents` at zero.

While the report is in `DRAFT`, the clerk adds lines to it. Each line is bound to its report through the `report_id` it was created under and carries the `member_id` of the employee, the `fiscal_year` the line credits, the member's `period_salary_cents` for that fiscal year, and the `contribution_amount_cents` remitted for that member-year — expected to be eight percent of salary, though a mismatch is a review decision for the analyst rather than a hard error. `service_months` may be supplied and defaults to 12. Two structural constraints are enforced at line creation: a line's `fiscal_year` must fall inside the report's period — fiscal year Y counts as inside exactly when January 1 of Y lies in the half-open period interval, and a fiscal year outside it is `ERR_INVALID_REQUEST` — and a report may contain at most one line per member per fiscal year — a duplicate is `ERR_DUPLICATE_LINE_PERIOD` (HTTP 409). Every line begins life in `PENDING`.

Submitting the report moves it `DRAFT → SUBMITTED` and requires at least one line under the report; submitting an empty report is `ERR_INVALID_REQUEST`. From that point the clerk's role is finished and the MemberServicesAnalyst's begins.

Review proceeds line by line. For each line the analyst records a `decision` of `ACCEPT` or `REJECT`, optionally with a `review_note` that is stored on the line as `review_note` only when supplied (an omitted note leaves the stored value unchanged). Review is permitted only while the parent report is in `SUBMITTED` or `VARIANCE`; attempting to review a line on a `DRAFT` or `RECONCILED` report is `ERR_INVALID_STATE`. Accepting a line moves it to `ACCEPTED` and triggers a full recompute of the report's `accepted_total_cents` — the sum of `contribution_amount_cents` over all `ACCEPTED` lines — and of the member's `total_service_years` and `current_annual_salary_cents` per §3.2. Rejecting a line moves it to `REJECTED` and likewise recomputes the report's accepted total with that line excluded.

A rejected line is not necessarily dead. While the report stands in `VARIANCE`, the analyst may re-review a `REJECTED` line with `decision` `ACCEPT`, moving it `REJECTED → ACCEPTED`; this is the repair path for corrected remittances. Re-review of a rejected line is permitted only in `VARIANCE` — not in `SUBMITTED`. Each acceptance recomputes the same three aggregates.

Closing the review is the finalize step, and its outcome is deterministic. The analyst finalizes a `SUBMITTED` report. If any line is still `PENDING`, the finalize is rejected with `ERR_LINES_PENDING` (HTTP 422) and the report's status does not change. If every line has been reviewed and at least one line is `REJECTED`, the report moves to `VARIANCE` — the fund is signaling that the employer's declared total cannot be accepted as submitted. If no line is rejected but the recomputed `accepted_total_cents` does not equal `declared_total_cents`, the finalize is rejected with `ERR_RECONCILIATION_VARIANCE` (HTTP 422): an unexplained variance with nothing to attribute it to. Only when no line is pending, no line is rejected, and the accepted total equals the declared total to the cent does the report reach `RECONCILED`, its terminal state.

From `VARIANCE` there is exactly one exit. When a re-review accepts the last outstanding rejected line — leaving no line in `PENDING` or `REJECTED` — and the accepted total then equals the declared total, the report bubbles up to `RECONCILED` automatically as a side effect of the line review; no second finalize call is needed. Throughout the whole lifecycle the conserved quantity holds: after submit, the sum of accepted amounts plus the sum of rejected amounts plus the sum of pending amounts always equals the sum of all line amounts.

### 3.4. Purchasing Service: Military and Prior Service Credit

A member with prior military or other eligible service can buy that time into the pension. The member — or an analyst filing on the member's behalf — requests a service purchase by supplying the `purchase_type` (`MILITARY` or `PRIOR_SERVICE`), the `service_period_start` and `service_period_end` of the period being purchased, and the `years_purchased` to two decimal places — a value supplied with finer precision is rounded half-up to two decimals at intake. A `service_period_end` preceding `service_period_start` is `ERR_INVALID_REQUEST`; an end equal to the start is a one-day period and is valid. The service period is a closed interval: it includes both its start and its end day, and any shared day with a fiscal year already credited to the member — meaning any fiscal year in which the member holds an `ACCEPTED` contribution line — is an overlap, rejected with `ERR_PURCHASE_PERIOD_OVERLAP` (HTTP 409). The new purchase is born in `REQUESTED`, with `flat_cost_cents`, `actuarial_cost_cents`, `cost_variant`, `quoted_cost_cents`, and `quote_expires_at` all unset.

Pricing happens at quote time, when an analyst runs the quote. Quoting requires that the member's `current_annual_salary_cents` is not null — that the member has at least one accepted contribution line — and fails with `ERR_INVALID_STATE` otherwise, because the price is a multiple of current salary. The system always computes both cost variants and stores both; the variant selector then decides which one the member actually pays.

The **flat** variant is simple: ten percent of the member's `current_annual_salary_cents` per year purchased — `flat_cost_cents` is the product of 0.10, the current annual salary, and `years_purchased`, rounded half-up to whole cents. The **actuarial** variant prices the same credit against the member's distance from retirement age. Let `years_to_60` be sixty minus the member's age in completed years at the quote date (the logical clock). The age factor is 0.35 when `years_to_60` is at least 10, else 0.28 when it is at least 5, else 0.22 — a member already aged 60 or older falls through to the 0.22 factor. `actuarial_cost_cents` is then the product of the current annual salary, `years_purchased`, and the age factor, rounded half-up. For identical salary and years the two variants differ.

The selection rule is a window around hire: if the quote date falls within five years of the member's `hire_date` — that is, `hire_date` plus five years is on or after the quote date (adding five years to a February 29 `hire_date` yields February 28 of a non-leap target year) — the member is entitled to the flat rate and `cost_variant` is `FLAT`; after that window closes, `cost_variant` is `ACTUARIAL`. `quoted_cost_cents` takes the value of `flat_cost_cents` under the flat variant and `actuarial_cost_cents` under the actuarial variant. Every quote carries a shelf life: `quote_expires_at` is the quote datetime plus 90 days, after which the offer lapses. Quoting moves the purchase `REQUESTED → QUOTED`.

Accepting the quote is the member's act — or an analyst acting for the member — and it opens the installment plan. Acceptance must occur while the logical clock reads on or before `quote_expires_at`. An acceptance attempted after expiry is rejected with `ERR_QUOTE_EXPIRED` (HTTP 422), and the purchase itself moves `QUOTED → EXPIRED` in the same stroke — expiry is lazy, discovered at the moment of acceptance, and it is permanent; the expired purchase's `balance_due_cents` is set to 0. The accepting request carries the chosen `installment_count`, which must be a whole number from 1 to 60; anything outside that range is `ERR_INVALID_REQUEST`.

On acceptance the purchase moves `QUOTED → PLAN_ACTIVE`, `balance_due_cents` is set equal to `quoted_cost_cents`, and the installment schedule is generated. The schedule divides the quoted cost into equal monthly payments with a pinned rounding order: the per-installment amount is `quoted_cost_cents` divided by `installment_count`, rounded half-up to whole cents; that rounded per-installment amount is assigned to each of the first `installment_count` − 1 payments; and the final payment receives the remainder — the quoted cost minus the per-installment amount times `installment_count` − 1 — which may be larger than the per-installment amount. The alternative order (rounding only the sum) is deliberately not used. Each payment's `due_date` is the first day of the month that is its `sequence_number` months after the month of acceptance — sequence 1 falls on the first of the month following acceptance — and every generated payment begins in `PENDING` with `applied_at` null.

Paying an installment is the OCC-guarded write of §2.6. Each generated payment row is bound to its plan by `purchase_id`, and the payer names the specific `payment_id` being applied and presents `expected_purchase_version` matching the purchase's current `version`. Payment is only possible while the purchase is in `PLAN_ACTIVE`; paying against a purchase in any other state is `ERR_PLAN_NOT_ACTIVE` (HTTP 409), and paying a payment that is not itself `PENDING` is a generic `ERR_INVALID_STATE`. A stale purchase version is `ERR_STALE_VERSION`. On success the payment moves `PENDING → APPLIED`, its `applied_at` is set to the logical clock, the purchase's `balance_due_cents` is reduced by the payment's `amount_cents`, and the purchase's `version` increments by 1 — which is precisely what serializes consecutive installments; the response carries the updated purchase. When a payment application brings `balance_due_cents` to zero, the purchase moves `PLAN_ACTIVE → COMPLETED` automatically and the member's `total_service_years` is recomputed to include the purchased `years_purchased` — the service credit posts at completion, not before.

Cancellation is available to the member or an analyst while the purchase is in `REQUESTED`, `QUOTED`, or `PLAN_ACTIVE`, and it can also arrive from the system via the death or retirement cascades of §3.7 and §3.5. Cancelling a `PLAN_ACTIVE` purchase refunds it: every payment in `APPLIED` moves to `REFUNDED`, the purchase's `refunded_total_cents` becomes the sum of those applied amounts, and `balance_due_cents` is zeroed. Cancelling a `REQUESTED` or `QUOTED` purchase has no payments to refund; `refunded_total_cents` simply stays at its default of 0, and `balance_due_cents` — still unset in those states — is set to 0. `COMPLETED`, `CANCELLED`, and `EXPIRED` are the terminal states.

### 3.5. Retirement: Application, Review, Approval

Retirement is a four-party minuet among the member, the analyst, the approver, and the actuarial tables — and it begins with the benefit estimate, which a member or advisor can compute at any time.

**The benefit estimate.** Two variants exist. The PROVISIONAL variant includes `PENDING` contribution lines — salary and service months — projecting not-yet-reconciled service into the totals; the FINAL variant counts only `ACCEPTED` lines, so identical data with one unreviewed pending line yields a lower estimate under FINAL than under PROVISIONAL. The explicit estimate read takes a `variant` parameter defaulting to FINAL — any other value is `ERR_INVALID_REQUEST` — and returns `fas_cents`, `service_years`, `multiplier`, `monthly_single_life_cents`, and the `variant` echoed back; the read always prices the `SINGLE_LIFE` option (factor 1.00) — the joint-option factors below apply only in the submit- and approval-time computations, which draw the election and beneficiary date of birth from the application itself. When the variant's input set contains no lines at all, `fas_cents` is 0 and the estimated monthly amount is 0.

The estimate's machinery is shared with approval. First, the final average salary: take the set of fiscal years having at least one included line, rank them by `fiscal_year` descending, and take the top 3 years; `fas_annual_cents` is the sum of the `period_salary_cents` of the included lines in those years divided by the number of distinct fiscal years taken — if fewer than three included years exist, divide by however many exist — rounded half-up to whole cents. Second, the service total per §3.2's accrual, computed over the variant's input set. Third, the multiplier, tiered by service: 0.025 when service is at least 25 years, else 0.022 when at least 20, else 0.020 when at least 10, else 0.017. The base monthly amount is `fas_annual_cents` times the multiplier times service years divided by twelve, computed with no intermediate rounding.

Fourth, the option factor. For `SINGLE_LIFE` the factor is 1.00. For `JOINT_50` and `JOINT_100` the factor depends on `age_diff`, the completed years between the member's `date_of_birth` and the `beneficiary_date_of_birth`: `JOINT_50` uses 0.95 when `age_diff` is at most 10 years and 0.90 otherwise; `JOINT_100` uses 0.90 when `age_diff` is at most 10 and 0.82 otherwise. The final `monthly_cents` is the base monthly times the option factor, rounded half-up once — a single final rounding.

**Filing.** A retirement application is created in `DRAFT` with an `option_election` of `SINGLE_LIFE`, `JOINT_50`, or `JOINT_100`. The joint options require `beneficiary_name` and `beneficiary_date_of_birth` at creation; omitting either is `ERR_INVALID_REQUEST`. Under `SINGLE_LIFE` the beneficiary fields are not required: a supplied `beneficiary_name` is stored as given, and `beneficiary_date_of_birth` is not captured. A member may hold at most one non-terminal retirement application and at most one non-terminal disability application at any time; a second create of the same type is rejected with `ERR_ACTIVE_APPLICATION_EXISTS` (HTTP 409). Operations on a `DECEASED` member's account — new purchases, new applications — are blocked with `ERR_MEMBER_DECEASED`.

**Submit.** Submitting moves `DRAFT → SUBMITTED` and computes the PROVISIONAL estimate, storing it as `provisional_monthly_cents`. Three gates guard submission, and they are evaluated only after the generic checks of §2.8: the member must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE` otherwise), the member's `total_service_years` must be at least 5 — the vesting threshold (`ERR_NOT_VESTED` otherwise) — and the member's age at the logical-clock date must be at least 60 completed years (`ERR_MEMBER_UNDER_RETIREMENT_AGE` otherwise).

**Review.** An analyst reviews a `SUBMITTED` application with an `outcome` of `REVIEW_OK`, moving it to `UNDER_REVIEW` and recording the request's `X-User-ID` as `reviewed_by_user_id`, or with `RETURN`, moving it to `RETURNED_FOR_CORRECTION` (from `SUBMITTED` or `UNDER_REVIEW`; a `RETURN` does not alter `reviewed_by_user_id`). The review cycle is unbounded: a returned application can come back to `UNDER_REVIEW` via another `REVIEW_OK`, each time refreshing `reviewed_by_user_id`, and either `SUBMITTED` or `RETURNED_FOR_CORRECTION` is a valid from-state for that transition.

**Approve.** Approval is the preserve of the BenefitApprover and is the second OCC-guarded write: the request must carry `expected_application_version` matching the application's current `version`, else `ERR_STALE_VERSION`. The remaining gates fire in the §2.8 order: the member must still be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`); no service purchase of the member may stand in `PLAN_ACTIVE` (`ERR_OUTSTANDING_BALANCE` — HTTP 422 — because the fund will not retire a member who still owes on a purchase); and the approver's `X-User-ID` must differ from the application's `reviewed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403 — the reviewer may not approve their own review; the check fires only when a `reviewed_by_user_id` is actually recorded, which in practice always holds, since only a review moves an application to the approvable `UNDER_REVIEW` state).

Approval's side effects are the largest cascade in the system. The FINAL benefit estimate runs and is stored as `final_monthly_cents`. A Benefit is created with `benefit_kind` `SERVICE`, `monthly_amount_cents` equal to the final amount, `status` `ACTIVE`, and `effective_date` set to the first day of the month containing the approval date on the logical clock. The member moves to `RETIRED`. Every other retirement application of the member still in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `RETURNED_FOR_CORRECTION` is cancelled. Every service purchase of the member in `REQUESTED`, `QUOTED`, or `PLAN_ACTIVE` is cancelled — with the full refund cascade of §3.4 applying to any plan-active purchase. Finally, the application's own `version` increments by 1. `APPROVED` and `CANCELLED` are the terminal states; cancelling an application directly is available to the member or an analyst from any non-terminal state.

### 3.6. Disability Retirement and the Medical Review Cycle

Disability retirement runs on a parallel track with its own gatekeepers. A member — or an analyst — files a disability application with a `disability_type` of `DUTY` or `NON_DUTY` and an optional free-text `description`. The application enters `UNDER_MEDICAL_REVIEW` immediately upon creation; the filing captures `submitted_by_user_id` from the request's `X-User-ID`, initializes `appeal_count` to 0, and leaves `decided_at` and `last_reviewer_user_id` unset until the first decision. The same single-active-application guard of §3.5 applies: one non-terminal disability application per member, else `ERR_ACTIVE_APPLICATION_EXISTS` — and since `DENIED` is not terminal (it may be appealed), a denied application still blocks a new filing; only an `APPROVED` application frees the slot.

Decisions belong to the MedicalReviewer. An approval requires the member to be `ACTIVE` or `INACTIVE` (`ERR_MEMBER_NOT_ACTIVE` otherwise — notably, a member need not be strictly active in service to receive a disability benefit). For `NON_DUTY` disabilities the member must be vested — `total_service_years` at least 5, else `ERR_NOT_VESTED`; a `DUTY` disability carries no vesting requirement. And when the application has been appealed — `appeal_count` greater than 0 — the deciding reviewer's `X-User-ID` must differ from `last_reviewer_user_id`, the fresh-eyes rule, enforced as `ERR_SEGREGATION_OF_DUTIES`.

Approving a disability application runs the disability benefit calculation over the FINAL input set — accepted contribution lines only: the monthly amount is 0.60 times the final average salary (computed exactly as in §3.5) divided by twelve, rounded half-up to whole cents. A Benefit is created with `benefit_kind` `DISABILITY`, that monthly amount, `status` `ACTIVE`, and `effective_date` on the first day of the decision month. The member moves to `RETIRED`; the member's non-terminal retirement applications are cancelled; open service purchases are cancelled with the refund cascade; and `decided_at` and `last_reviewer_user_id` are recorded. `APPROVED` is terminal.

A denial is lighter: the application moves to `DENIED`, and `decided_at` and `last_reviewer_user_id` are recorded — the fresh-eyes rule applies equally to denial decisions on appealed cases. But `DENIED` is not terminal. The member or an analyst may appeal within 60 days of `decided_at`, measured against the logical clock and inclusive at the boundary — an appeal filed at exactly `decided_at` plus 60 days is still accepted; only a later filing is `ERR_APPEAL_WINDOW_CLOSED` (HTTP 422). A successful appeal moves the application `DENIED → UNDER_MEDICAL_REVIEW` and increments `appeal_count` by 1, reopening the cycle — with the guarantee, via the fresh-eyes rule, that whoever decides next is not the reviewer who decided last.

### 3.7. Death, Benefits in Payment, COLA, and Return-to-Work

**The benefit record.** Every Benefit is born `ACTIVE` from an approval — never created directly — carrying its `member_id`, `benefit_kind` (`SERVICE` or `DISABILITY`), `monthly_amount_cents`, and `effective_date`. It tracks `cola_applied_count`, starting at 0, and a return-to-work accumulation pair: `rtw_calendar_year`, the calendar year of the current accumulation bucket, starting null until the first earnings report, and `rtw_ytd_earnings_cents`, the earnings accumulated for that year, starting at 0.

**COLA.** Once a year — or whenever the FundAdmin chooses — a COLA run applies the fund's `cola_rate_pct` to every benefit in `ACTIVE` status; `SUSPENDED` and `TERMINATED` benefits are excluded from the run entirely and count toward neither reported figure. Eligibility is tenure-based: `months_active` is the whole calendar months between the benefit's `effective_date` and the logical-clock date — a benefit effective 2025-08-01 measured on 2026-08-01 counts 12 months — and a benefit is adjusted only when `months_active` is at least 12; exactly 12 is eligible. Each eligible benefit's `monthly_amount_cents` becomes its prior amount times one plus the `cola_rate_pct`, rounded half-up to whole cents, its `cola_applied_count` increments by 1, and its `version` increments by 1. Ineligible benefits are skipped. The run reports back `applied_count` and `skipped_count`, where `skipped_count` counts exactly the `ACTIVE` benefits whose tenure fell short of 12 months.

**Return-to-work surveillance.** A retired member who goes back to work reports earnings against the benefit by calendar year, supplying `calendar_year` and `amount_cents`. Earnings reports are accepted on benefits in `ACTIVE` or `SUSPENDED` — a suspended retiree may still be working and still accruing toward the limit — but a report against a `TERMINATED` benefit is `ERR_BENEFIT_NOT_ACTIVE` (HTTP 409). When the report's `calendar_year` differs from the benefit's `rtw_calendar_year`, the bucket resets: `rtw_calendar_year` takes the new year and `rtw_ytd_earnings_cents` starts again from 0. The reported `amount_cents` is then added to the year-to-date total. If the resulting total strictly exceeds the fund's `earnings_limit_annual_cents` — when more than one fund exists, the earliest-created fund's limit governs — the benefit moves `ACTIVE → SUSPENDED` and the member moves `RETIRED → SUSPENDED_RTW` in the same stroke; a further over-limit report against an already-`SUSPENDED` benefit leaves it `SUSPENDED` (and the member `SUSPENDED_RTW`). Landing exactly on the limit does not suspend — the comparison is strict.

**Reinstatement.** A suspended benefit can be reinstated by an analyst when two conditions hold: the benefit is in `SUSPENDED` (reinstating an `ACTIVE` benefit is `ERR_INVALID_STATE`), and the `rtw_ytd_earnings_cents` for the current calendar year — the logical clock's year, counting 0 when the benefit's `rtw_calendar_year` bucket belongs to a different year — is within — that is, at most — the fund's `earnings_limit_annual_cents` (again the earliest-created fund's limit); a current-year total over the limit blocks reinstatement with `ERR_INVALID_STATE`. Reinstatement moves the benefit `SUSPENDED → ACTIVE` and the member `SUSPENDED_RTW → RETIRED` in the same request.

**Death.** Recording a member's death — setting `deceased_at` on the member record — moves the member to `DECEASED` and fires the death cascade from whichever of `ACTIVE`, `INACTIVE`, `RETIRED`, or `SUSPENDED_RTW` the member occupied. Every Benefit of the member in `ACTIVE` or `SUSPENDED` moves to `TERMINATED`. Every ServicePurchase of the member in `REQUESTED`, `QUOTED`, or `PLAN_ACTIVE` is cancelled, and each such cancellation of a plan-active purchase runs the refund cascade: its `APPLIED` payments become `REFUNDED`, `refunded_total_cents` is set to the sum of the applied amounts, and `balance_due_cents` zeroes. The cascade does not touch the member's retirement or disability applications. Death also freezes designations: from `DECEASED`, beneficiary revocation is blocked with `ERR_MEMBER_DECEASED`.

### 3.8. Beneficiary Designation and Survivor Claims

While the member lives, beneficiary management is simple self-service. The member — or an analyst on the member's behalf — designates a beneficiary with `full_name`, a free-text `relationship`, and `date_of_birth`; the designation is born `DESIGNATED`. Revocation moves it `DESIGNATED → REVOKED` and is available only while the member is not `DECEASED` — designations freeze at death (`ERR_MEMBER_DECEASED`), and designating a new beneficiary on a `DECEASED` member is likewise `ERR_MEMBER_DECEASED`.

After the member's death has terminated the benefit, a designated beneficiary may file a survivor claim. Filing is the SurvivorClaimant's act — `X-User-ID` must equal the Beneficiary designation's own `id`, else `ERR_FORBIDDEN` — though an analyst may also file. Four gates stand in front of a claim, evaluated within the §2.8 order — which places the state gates ahead of the referential and temporal ones, so the checks fire in this sequence. A designation already past the filing state is rejected generically: filing on a `CLAIM_FILED`, `PAYABLE`, or `DENIED` designation is `ERR_INVALID_STATE`. The member's benefit must be `TERMINATED`; filing while it is in any other state — including when the member has no benefit at all — is `ERR_BENEFIT_NOT_TERMINATED` (HTTP 409); the benefit examined is the member's most recently created one, and it is that benefit's originating application whose election is consulted next. The designation must be live: filing on a `REVOKED` designation is `ERR_DESIGNATION_REVOKED` (HTTP 422). The originating retirement application's `option_election` must entitle survivors — a claim under a `SINGLE_LIFE` election is `ERR_NO_SURVIVOR_ENTITLEMENT` (HTTP 422). And the claim must be filed within 365 days of the member's `deceased_at`, measured in calendar days against the logical clock's date and inclusive of the final day — a filing exactly 365 days after the death is accepted; only later filings are `ERR_CLAIM_DEADLINE_PASSED` (HTTP 422). A successful filing moves the designation `DESIGNATED → CLAIM_FILED` and stamps `claim_filed_at`.

Adjudication belongs to the BenefitApprover, who reviews a `CLAIM_FILED` designation with an `outcome` of `APPROVE` or `DENY`. Adjudicating a designation not in `CLAIM_FILED` is `ERR_INVALID_STATE` — a revoked designation never reaches adjudication at all. Approval re-verifies that the member's latest benefit is still `TERMINATED`, else `ERR_BENEFIT_NOT_TERMINATED`; then the survivor benefit is computed: the survivor percentage is 0.50 when the originating election was `JOINT_50` and 1.00 when it was `JOINT_100`, and `survivor_monthly_cents` is the member's terminated benefit's `monthly_amount_cents` — its COLA-adjusted current amount at termination — times that percentage, rounded half-up to whole cents. The designation moves to `PAYABLE`. A denial moves it to `DENIED`. `REVOKED`, `PAYABLE`, and `DENIED` are all terminal for a designation.

## 4. Endpoint Definitions

All endpoints are mounted under `/`. Creating a new resource returns 201; every other successful operation — modifications, state transitions, action endpoints, computed reads — returns 200. Errors carry their catalogued status codes. The table below is a navigational summary; the full request and response semantics of each operation live in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default `2026-08-01T00:00:00Z`) | FundAdmin |
| POST | `/pension-funds` | Create a pension fund configuration | FundAdmin |
| GET | `/pension-funds/{id}` | Get a pension fund | All seven roles |
| PATCH | `/pension-funds/{id}` | Update fund configuration (OCC-guarded) | FundAdmin |
| POST | `/pension-funds/{id}/cola-runs` | Apply COLA to all eligible ACTIVE benefits | FundAdmin |
| POST | `/employers` | Register an employer reporting unit | FundAdmin |
| GET | `/employers/{id}` | Get an employer | FundAdmin, MemberServicesAnalyst, EmployerClerk |
| GET | `/employers/{id}/members` | List members employed by this employer | FundAdmin, MemberServicesAnalyst, EmployerClerk |
| GET | `/employers/{id}/contribution-reports` | List contribution reports of this employer | FundAdmin, MemberServicesAnalyst, EmployerClerk |
| POST | `/members` | Enroll a member | MemberServicesAnalyst |
| GET | `/members/{id}` | Get a member | All seven roles |
| PATCH | `/members/{id}` | Member lifecycle updates: status changes; `deceased_at` records death and fires the death cascade | MemberServicesAnalyst |
| GET | `/members/{id}/benefit-estimate` | Computed benefit estimate; `variant` PROVISIONAL or FINAL (default FINAL) | Member, MemberServicesAnalyst, BenefitApprover |
| GET | `/members/{id}/contribution-lines` | List contribution lines of a member (filterable by `fiscal_year`) | FundAdmin, MemberServicesAnalyst, EmployerClerk, Member |
| GET | `/members/{id}/service-purchases` | List service purchases of a member | FundAdmin, MemberServicesAnalyst, Member |
| GET | `/members/{id}/retirement-applications` | List retirement applications of a member | FundAdmin, MemberServicesAnalyst, BenefitApprover, Member |
| GET | `/members/{id}/disability-applications` | List disability applications of a member | FundAdmin, MemberServicesAnalyst, MedicalReviewer, Member |
| GET | `/members/{id}/benefits` | List benefits of a member | FundAdmin, MemberServicesAnalyst, BenefitApprover, Member, SurvivorClaimant |
| GET | `/members/{id}/beneficiaries` | List beneficiary designations of a member | FundAdmin, MemberServicesAnalyst, BenefitApprover, Member, SurvivorClaimant |
| POST | `/employers/{id}/contribution-reports` | Create a contribution report (half-open period, no overlap per employer) | EmployerClerk |
| GET | `/contribution-reports/{id}` | Get a contribution report | FundAdmin, MemberServicesAnalyst, EmployerClerk |
| POST | `/contribution-reports/{id}/lines` | Add a contribution line to a DRAFT report | EmployerClerk |
| GET | `/contribution-reports/{id}/lines` | List lines of a report | FundAdmin, MemberServicesAnalyst, EmployerClerk |
| POST | `/contribution-reports/{id}/submit` | Submit a report for review | EmployerClerk |
| POST | `/contribution-reports/{id}/lines/{lineId}/review` | Accept or reject a line; re-review of REJECTED lines allowed in VARIANCE | MemberServicesAnalyst |
| POST | `/contribution-reports/{id}/finalize` | Close review: SUBMITTED to RECONCILED or VARIANCE | MemberServicesAnalyst |
| POST | `/members/{id}/service-purchases` | Request a service purchase (military or prior service) | Member, MemberServicesAnalyst |
| GET | `/service-purchases/{id}` | Get a service purchase | FundAdmin, MemberServicesAnalyst, Member |
| POST | `/service-purchases/{id}/quote` | Compute and pin the purchase cost quote | MemberServicesAnalyst |
| POST | `/service-purchases/{id}/accept` | Accept a quote and open an installment plan | Member, MemberServicesAnalyst |
| POST | `/service-purchases/{id}/payments` | Apply a PENDING installment payment (OCC-guarded) | Member, MemberServicesAnalyst |
| POST | `/service-purchases/{id}/cancel` | Cancel a non-terminal purchase; APPLIED payments are refunded | Member, MemberServicesAnalyst |
| GET | `/service-purchases/{id}/payments` | List installment payments of a purchase | FundAdmin, MemberServicesAnalyst, Member |
| POST | `/members/{id}/retirement-applications` | Create a retirement application (DRAFT) with option election | Member, MemberServicesAnalyst |
| GET | `/retirement-applications/{id}` | Get a retirement application | FundAdmin, MemberServicesAnalyst, BenefitApprover, Member |
| POST | `/retirement-applications/{id}/submit` | Submit application; computes the provisional estimate | Member, MemberServicesAnalyst |
| POST | `/retirement-applications/{id}/review` | Analyst review: REVIEW_OK or RETURN; cycle allowed | MemberServicesAnalyst |
| POST | `/retirement-applications/{id}/approve` | Final approval (OCC-guarded, segregated from reviewer) | BenefitApprover |
| POST | `/retirement-applications/{id}/cancel` | Cancel a non-terminal retirement application | Member, MemberServicesAnalyst |
| POST | `/members/{id}/disability-applications` | File a disability retirement application | Member, MemberServicesAnalyst |
| GET | `/disability-applications/{id}` | Get a disability application | FundAdmin, MemberServicesAnalyst, MedicalReviewer, BenefitApprover, Member |
| POST | `/disability-applications/{id}/decision` | Medical review decision: APPROVE or DENY; appeals require a different reviewer | MedicalReviewer |
| POST | `/disability-applications/{id}/appeal` | Appeal a DENIED decision within 60 days | Member, MemberServicesAnalyst |
| GET | `/benefits/{id}` | Get a benefit | FundAdmin, MemberServicesAnalyst, BenefitApprover, Member, SurvivorClaimant |
| POST | `/benefits/{id}/earnings-reports` | Report return-to-work earnings for a calendar year | Member, MemberServicesAnalyst |
| POST | `/benefits/{id}/reinstate` | Reinstate a SUSPENDED benefit | MemberServicesAnalyst |
| POST | `/members/{id}/beneficiaries` | Designate a beneficiary | Member, MemberServicesAnalyst |
| POST | `/beneficiaries/{id}/revoke` | Revoke a designation (not after member death) | Member, MemberServicesAnalyst |
| POST | `/beneficiaries/{id}/file-claim` | File a survivor claim | SurvivorClaimant, MemberServicesAnalyst |
| POST | `/beneficiaries/{id}/approve` | Approve or deny a survivor claim | BenefitApprover |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narrative of §2 and §3; this table is the authoritative mapping of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_MEMBER_DECEASED` | 409 |
| `ERR_ACTIVE_APPLICATION_EXISTS` | 409 |
| `ERR_QUOTE_EXPIRED` | 422 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_BENEFIT_NOT_ACTIVE` | 409 |
| `ERR_BENEFIT_NOT_TERMINATED` | 409 |
| `ERR_NOT_VESTED` | 422 |
| `ERR_MEMBER_UNDER_RETIREMENT_AGE` | 422 |
| `ERR_OUTSTANDING_BALANCE` | 422 |
| `ERR_LINES_PENDING` | 422 |
| `ERR_RECONCILIATION_VARIANCE` | 422 |
| `ERR_DUPLICATE_LINE_PERIOD` | 409 |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 |
| `ERR_PURCHASE_PERIOD_OVERLAP` | 409 |
| `ERR_DESIGNATION_REVOKED` | 422 |
| `ERR_NO_SURVIVOR_ENTITLEMENT` | 422 |
| `ERR_CLAIM_DEADLINE_PASSED` | 422 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
