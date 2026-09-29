# Student Loan Repayment Match Benefit API — Product Requirements Document

## 1. Introduction

Plan sponsors that offer a qualified student loan payment (QSLP) match face an awkward accounting problem: the retirement plan already pays an employer match on elective deferrals, and the statute lets the sponsor pay the *same* match formula on certified student loan payments — but only once. The same three-percent-at-full-rate and two-percent-at-half-rate ladder must be shared between two entirely different data feeds: payroll, which arrives period by period, and participant certifications, which arrive once a year as a claim. A dollar of tier space consumed by an elective deferral is not available to a certified loan payment, and neither feed knows what the other has already used.

This service is the sponsor's ledger of record for that shared space. It tracks plan years and the executed plan-document amendment that authorizes the benefit, the participant roster with highly-compensated-employee status and vesting service, payroll lines carrying compensation and deferrals, registered student loan accounts and the annual certification claims filed against them, the match allocations those claims produce, the funding batches that carry money to the recordkeeper, the forfeitures that flow back when an unvested participant terminates, the ACP nondiscrimination test that judges the whole picture, and the correction adjustments that unwind erroneous matches. Every one of those artifacts is a top-level collection linked by explicit identifier references; nothing is nested except two convenience reads (the payment lines of a claim, and an employee's audit packet).

The system deliberately supports two different answers to the question "how much QSLP match is this participant owed?" An interim answer, computed when a claim is accepted, mirrors the elective-deferral match period by period and can strand certified dollars in periods where deferrals already exhausted the ladder. A final answer, computed by the annual true-up once the plan year is locked, ignores period boundaries, recomputes the combined annual entitlement, and pays the difference. Reconciling those two answers — and propagating the reconciliation into nondiscrimination testing, funding, vesting and audit correction — is the core of the product.

## 2. Global Specifications & System-Wide Principles

Endpoints are mounted at the API root; there is no additional path prefix.

### 2.1. Actors, Headers and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing or empty, or if `X-User-Role` does not name one of the five declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the header names a valid role that is not listed among the authorized roles for the requested endpoint (see the table in §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles are `BenefitsAdministrator`, `Employee`, `PayrollOperator`, `Recordkeeper`, and `ComplianceAuditor`.

- **`BenefitsAdministrator`** — plan sponsor benefits staff. Configures plan years and amendments, enrolls employees, records mid-year employment changes, verifies loan accounts, decides claims, runs the annual true-up, and records match corrections. When `X-User-Role` is `BenefitsAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition demands it — as `accepted_by_user_id` on a `LoanCertification` accepted by this role, and as `created_by_user_id` on a `CorrectionAdjustment` — but never compares it to any entity's `id`.
- **`Employee`** — the plan participant. Registers loan accounts and files the annual certification of qualified student loan payments. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's `employee_id` (or, for a certification line, the `employee_id` of its parent claim) to `X-User-ID`.
- **`PayrollOperator`** — payroll data-exchange operator. Maintains payroll periods, posts compensation and deferral lines, and opens and transmits funding batches. When `X-User-Role` is `PayrollOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`.
- **`Recordkeeper`** — the external retirement plan recordkeeper that settles or rejects transmitted funding batches. When `X-User-Role` is `Recordkeeper`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`.
- **`ComplianceAuditor`** — independent compliance reviewer. Audits certification documentation, voids improper claims (never the ones it accepted itself), and runs ACP nondiscrimination testing. When `X-User-Role` is `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is recorded as `created_by_user_id` on adjustments this role produces and is compared against the stored `accepted_by_user_id` only by the segregation-of-duties rule described in §2.11, never against an entity's `id`.

A caller acting as `Employee` is confined to its own records. On the following operations the target resource's owning employee must equal `X-User-ID`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403): `POST /loan-accounts`, `POST /loan-certifications`, `POST /loan-certifications/{certification_id}/lines`, `POST /loan-certifications/{certification_id}/submit`, `GET /employees/{employee_id}`, `GET /loan-certifications/{certification_id}`, `GET /loan-certifications/{certification_id}/lines`, `GET /loan-accounts/{loan_account_id}`, and `GET /match-allocations/{allocation_id}`. No ownership scoping applies to the four operator roles.

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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of items to skip; when omitted it defaults to 0, and its minimum accepted value is 0.

Unless a specific endpoint states otherwise, every list is sorted by the resource's creation timestamp in ascending order.

List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope described in §2.2.

### 2.4. Record Identity, Timestamps and the Logical Clock

Ten of the fourteen collections are versioned resources: plan years, plan amendments, employees, payroll periods, contribution records, loan accounts, loan certifications, match allocations, funding batches, and nondiscrimination tests. Each of these carries:

- `id` (string) — a server-minted UUID. It carries no type prefix.
- `created_at` (string) — an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written.
- `updated_at` (string) — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the resource, including mutations that only change derived totals.
- `version` (integer) — starts at 1 on creation and increments by exactly 1 on each mutation of that resource.

Four collections are append-only audit rows and are deliberately leaner: leave events, certification lines, forfeiture records, and correction adjustments carry only `id` and `created_at`. For these four, `updated_at` and `version` are absent from the resource entirely — not null, not zero, simply not present.

All temporal evaluation in this system reads a server-side **logical clock** rather than wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. `POST /_clock/set_current_utc` accepts a `to_iso8601` instant and returns the new value as `current_utc`; it is available to `BenefitsAdministrator`, `PayrollOperator`, and `ComplianceAuditor`. Every temporal validation, every stamped timestamp (`submitted_at`, `decided_at`, `adopted_at`, `notice_sent_at`, `effective_at`, `transmitted_at`, `settled_at`, `computed_at`), and every leave-window evaluation reads this clock.

### 2.5. Identifier Resolution Order

Where a request carries more than one identifier — in the path, or in the path plus the body — identifiers are resolved strictly left to right, path before body, and the first identifier that fails to resolve determines the rejection. Each identifier has its own dedicated 404: `plan_year_id` yields `ERR_PLAN_YEAR_NOT_FOUND`; `employee_id` yields `ERR_EMPLOYEE_NOT_FOUND`; `payroll_period_id` yields `ERR_PAYROLL_PERIOD_NOT_FOUND`; `loan_account_id` yields `ERR_LOAN_ACCOUNT_NOT_FOUND`; `certification_id` — and also `supersedes_certification_id` when supplied in a body — yields `ERR_CERTIFICATION_NOT_FOUND`; `allocation_id` yields `ERR_ALLOCATION_NOT_FOUND`; `funding_batch_id` yields `ERR_FUNDING_BATCH_NOT_FOUND`; `amendment_id` yields `ERR_AMENDMENT_NOT_FOUND`; `test_id` yields `ERR_TEST_NOT_FOUND`. The remaining single-row reads — those addressed by `leave_event_id`, `certification_line_id`, `contribution_record_id`, `correction_id`, or `forfeiture_id` — share one code, `ERR_RECORD_NOT_FOUND`. All of these are HTTP 404.

Identifier resolution always precedes ownership scoping, concurrency checks, state checks and business rules, so a request that names a nonexistent parent is answered with the parent's 404 rather than with a downstream conflict.

### 2.6. The Shared Statutory Tier Space

The single most important invariant in this product is that elective deferrals and certified student loan payments draw on **one** ladder of match space, and elective deferrals draw first.

The ladder is configured per plan year. `tier1_pct` (default 0.03) expresses the first rung as a fraction of counted compensation and `tier1_match_rate` (default 1.00) is the rate paid on it; `tier2_pct` (default 0.02) expresses the second rung and `tier2_match_rate` (default 0.50) is the rate paid on it. In the default configuration the sponsor therefore matches the first three percent of counted compensation dollar for dollar and the next two percent at fifty cents on the dollar.

Two ceilings bound the ladder. Counted compensation for a plan year stops accumulating once `compensation_cap_cents` is reached — by default 34,500,000 cents, that is $345,000 of annual pay. Certified student loan dollars are additionally bounded by `annual_deferral_limit_cents`, the statutory annual elective-deferral dollar limit, by default 2,300,000 cents, that is $23,000 per participant per plan year; the deferrals the participant already made in that plan year and the certified dollars already reserved by that participant's other claims both consume that same limit. This is the mechanism that prevents double counting: a dollar cannot be matched as a deferral and again as a certified loan payment.

One ladder, two match answers. The base entitlement on any contribution is always computed the same way — the portion of the contribution up to counted compensation multiplied by `tier1_pct` is matched at `tier1_match_rate`, and the next portion up to counted compensation multiplied by `tier2_pct` is matched at `tier2_match_rate` — but the *scope* over which it is applied differs between the two variants the system supports. The `PAY_PERIOD_MIRROR` variant, described in §3.5, applies the ladder period by period at claim acceptance and can leave certified dollars unmatched where deferrals already consumed that period's space. The `ANNUAL_TRUE_UP` variant, described in §3.8, applies the ladder once over annual compensation and annual contributions and pays the shortfall. The same certified dollars therefore produce two different totals, and reconciling them is not optional bookkeeping — it is the product.

Compensation above `hce_prior_comp_threshold_cents` in the prior plan year — by default 15,500,000 cents, that is $155,000 — makes a participant highly compensated for nondiscrimination purposes. The comparison is strictly greater than: prior-year compensation exactly equal to the threshold is *not* highly compensated.

### 2.7. Cents Arithmetic, Rounding and Ratio Precision

Every monetary quantity in this system is an integer number of cents. Tier ceilings computed as a percentage of counted compensation are carried at full arithmetic precision inside a calculation; only the values written to a resource are reduced to whole cents, and the reduction always uses **round half up**.

Where a formula rounds, the *point* at which it rounds is part of the contract:

- The per-period elective-deferral match rounds once, on the sum of the two tier products, after both tiers have been measured.
- The pay-period mirror match rounds once **per payroll-period allocation** and then sums the already-rounded allocations into the derived totals. Summing raw tier products first and rounding once at the end is not the declared behavior.
- The annual true-up rounds once, on the combined annual entitlement, before any subtraction of what was already funded.
- Vesting rounds the vested portion **per allocation**, and the per-allocation forfeitures are then summed into the plan-year pool.

Nondiscrimination ratios are carried to four decimal places with round half up, and the rounding is applied twice: once per participant, and again on the group average of the already-rounded participant ratios. Averaging raw ratios and rounding once is not the declared behavior and can differ in the fourth decimal place. `prior_year_nhce_acp`, `hce_acp`, `nhce_acp`, and `limit_acp` are all four-decimal values.

### 2.8. Derived Totals, Conserved Quantities and Cascading Recomputation

Many fields in this system are never written directly by a client; they are recomputed from their inputs whenever those inputs move, and each recomputation is a mutation of the owning resource that refreshes `updated_at` and increments `version`.

A plan year exposes four such rollups. `total_deferral_match_funded_cents` is the sum of `deferral_match_cents` across the contribution records of the plan year's payroll periods, plus the sum of `amount_cents` over the plan year's correction adjustments whose `reason_code` is `ACP_CORRECTIVE_FORFEITURE`. `total_qslp_match_funded_cents` is the sum of `amount_cents` over the plan year's match allocations whose `funding_status` is `SCHEDULED` or `FUNDED`, plus the sum of `amount_cents` over the plan year's correction adjustments whose `reason_code` is `TRUE_UP_RECOUPMENT`. `accepted_certification_count` is the number of loan certifications of the plan year whose `status` is `ACCEPTED` or `AUDIT_HOLD`. `forfeiture_balance_cents` is whatever remains of the forfeiture pool after the offset waterfall of §3.6 has distributed it across the plan year's pending funding batches.

Two of these rollups behave as **conserved quantities**, and the tests of this system lean on that property. The plan year's `total_qslp_match_funded_cents` must return to its exact pre-acceptance value once a claim's acceptance is fully unwound by a void. An employee's `remaining_qslp_space_cents` must return to its exact pre-submission value once a submitted claim is returned, voided, or superseded, because the statuses `DRAFT`, `RETURNED`, `VOIDED`, and `SUPERSEDED` all sit outside the set of statuses that reserve space.

Cascades run to completion within the request that triggers them. Accepting a claim writes allocations, attaches them to a pending batch, moves the batch's totals, moves the plan year's totals, and stales the plan year's completed nondiscrimination tests — all before the response is produced. Terminating an employee evaluates vesting on that employee's allocations, writes forfeiture records, recomputes the plan year's forfeiture balance, and re-runs the offset waterfall over every pending batch of the plan year. The system also performs state transitions on parents and siblings without an explicit client request against those resources, and each such transition independently increments that resource's `version`.

### 2.9. Optimistic Concurrency Control

Exactly two write operations require the client to prove it is acting on a view of the ledger it has actually read. Both compare a client-supplied expected version against a *parent* resource's current `version`.

Creating a loan certification through `POST /loan-certifications` requires `expected_employee_version` as a non-optional field of the request body, carrying the client's last observed `version` of the target `Employee`. If it does not equal that employee's current `version`, the create is rejected with `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412). The employee's version advances whenever a newer claim is accepted for the same employee and plan year — legitimately superseding the prior one — or whenever a payroll line changes the employee's remaining statutory space, so a mismatch means the submitting client's view of eligibility is stale.

Recording a correction through `POST /match-allocations/{allocation_id}/corrections` requires `expected_plan_year_version` as a non-optional field of the request body, carrying the client's last observed `version` of the `PlanYear` that owns the allocation. If it does not equal that plan year's current `version`, the correction is rejected with `ERR_STALE_PLAN_YEAR_VERSION` (HTTP 412). A correction is a deliberate supersede of the plan year's funded match ledger; without the check, a correction written from a superseded ledger snapshot would claim to reconcile totals it never observed, so the writer is forced to re-read the reconciled ledger first.

No other endpoint accepts a version field, and no other endpoint performs a version comparison.

### 2.10. Order of Evaluation

When several rules could reject the same request, the rule with the smallest ordinal below decides the response. The ordering is global; the endpoint-specific substance of each rule is described in §3.

1. Authentication — `ERR_UNAUTHENTICATED`, on every endpoint.
2. Role authorization — `ERR_FORBIDDEN_ROLE`, on every endpoint.
3. Request well-formedness — `ERR_INVALID_REQUEST`, on every endpoint. Required body fields must be present, types correct and enum members valid; `amount_cents` must be greater than zero; `original_principal_cents` must be greater than zero; `account_last4` must be exactly four digits; `covered_period_end` must be strictly after `covered_period_start`; `eligible_compensation_cents` must be zero or greater; `elective_deferral_cents` must be zero or greater; `notice_channel` must be present on a notice transition; `rescinded_reason` must be present on a rescind transition; `rejection_code` must be present on a rejected settlement.
4. `plan_year_id` resolution — `ERR_PLAN_YEAR_NOT_FOUND`, on `POST /plan-amendments`, `POST /payroll-periods`, `POST /loan-certifications`, `POST /nondiscrimination-tests`, `POST /plan-years/{plan_year_id}/status`, `POST /plan-years/{plan_year_id}/true-up`, `POST /funding-batches`, and `GET /plan-years/{plan_year_id}`.
5. `employee_id` resolution — `ERR_EMPLOYEE_NOT_FOUND`, on `POST /contribution-records`, `POST /loan-accounts`, `POST /loan-certifications`, `POST /leave-events`, `POST /employees/{employee_id}/employment-events`, `GET /employees/{employee_id}`, `GET /employees/{employee_id}/audit-packet`, and `POST /plan-years/{plan_year_id}/true-up`.
6. `payroll_period_id` resolution — `ERR_PAYROLL_PERIOD_NOT_FOUND`, on `POST /contribution-records`, `POST /funding-batches`, `POST /payroll-periods/{payroll_period_id}/status`, and `GET /payroll-periods/{payroll_period_id}`.
7. `loan_account_id` resolution — `ERR_LOAN_ACCOUNT_NOT_FOUND`, on `POST /loan-certifications/{certification_id}/lines`, `POST /loan-accounts/{loan_account_id}/verification`, and `GET /loan-accounts/{loan_account_id}`.
8. `certification_id` or `supersedes_certification_id` resolution — `ERR_CERTIFICATION_NOT_FOUND`, on `POST /loan-certifications`, `POST /loan-certifications/{certification_id}/lines`, `POST /loan-certifications/{certification_id}/submit`, `POST /loan-certifications/{certification_id}/decision`, `POST /loan-certifications/{certification_id}/audit-hold`, `POST /loan-certifications/{certification_id}/audit-release`, `GET /loan-certifications/{certification_id}`, and `GET /loan-certifications/{certification_id}/lines`.
9. `allocation_id` resolution — `ERR_ALLOCATION_NOT_FOUND`, on `POST /match-allocations/{allocation_id}/corrections` and `GET /match-allocations/{allocation_id}`.
10. `funding_batch_id` resolution — `ERR_FUNDING_BATCH_NOT_FOUND`, on `POST /funding-batches/{funding_batch_id}/transmit`, `POST /funding-batches/{funding_batch_id}/settlement`, and `GET /funding-batches/{funding_batch_id}`.
11. `amendment_id` resolution — `ERR_AMENDMENT_NOT_FOUND`, on `POST /plan-amendments/{amendment_id}/status` and `GET /plan-amendments/{amendment_id}`.
12. `test_id` resolution — `ERR_TEST_NOT_FOUND`, on `POST /nondiscrimination-tests/{test_id}/compute`, `POST /nondiscrimination-tests/{test_id}/correction`, and `GET /nondiscrimination-tests/{test_id}`.
13. Audit-row resolution — `ERR_RECORD_NOT_FOUND`, on `GET /leave-events/{leave_event_id}`, `GET /certification-lines/{certification_line_id}`, `GET /contribution-records/{contribution_record_id}`, `GET /correction-adjustments/{correction_id}`, and `GET /forfeiture-records/{forfeiture_id}`.
14. Employee ownership — `ERR_NOT_RESOURCE_OWNER`, on the nine operations enumerated in §2.1.
15. Employee version match — `ERR_STALE_EMPLOYEE_VERSION`, on `POST /loan-certifications`.
16. Plan-year version match — `ERR_STALE_PLAN_YEAR_VERSION`, on `POST /match-allocations/{allocation_id}/corrections`.
17. Plan year must be `OPEN` — `ERR_PLAN_YEAR_LOCKED`, on `POST /loan-certifications`, `POST /loan-certifications/{certification_id}/lines`, `POST /loan-certifications/{certification_id}/submit`, `POST /loan-certifications/{certification_id}/decision`, and `POST /contribution-records`.
18. Claim must not be terminal — `ERR_CERTIFICATION_TERMINAL`, on `POST /loan-certifications/{certification_id}/lines`, `POST /loan-certifications/{certification_id}/submit`, `POST /loan-certifications/{certification_id}/decision`, `POST /loan-certifications/{certification_id}/audit-hold`, and `POST /loan-certifications/{certification_id}/audit-release`.
19. Claim from-state must match the requested transition — `ERR_CERTIFICATION_STATE_INVALID`, on the same five claim operations as ordinal 18 and additionally on `POST /plan-years/{plan_year_id}/status`.
20. Batch's payroll period must be closed — `ERR_PERIOD_NOT_CLOSED`, on `POST /funding-batches/{funding_batch_id}/transmit`.
21. Payroll period must accept the operation — `ERR_PERIOD_ALREADY_FUNDED`, on `POST /contribution-records` and `POST /payroll-periods/{payroll_period_id}/status`.
22. Reopen must not strand settled funding — `ERR_PERIOD_HAS_SETTLED_FUNDING`, on `POST /payroll-periods/{payroll_period_id}/status`.
23. Batch from-state must match the requested transition — `ERR_BATCH_STATE_INVALID`, on `POST /funding-batches/{funding_batch_id}/transmit`, `POST /funding-batches/{funding_batch_id}/settlement`, and `POST /plan-years/{plan_year_id}/status`.
24. Amendment from-state must match the requested transition — `ERR_AMENDMENT_STATE_INVALID`, on `POST /plan-amendments/{amendment_id}/status`.
25. Test from-state must match the requested transition — `ERR_TEST_ALREADY_FINAL`, on `POST /nondiscrimination-tests/{test_id}/compute`, `POST /nondiscrimination-tests/{test_id}/correction`, and `POST /plan-years/{plan_year_id}/status`.
26. Plan year must be `LOCKED` for the true-up — `ERR_PLAN_YEAR_NOT_LOCKED`, on `POST /plan-years/{plan_year_id}/true-up`.
27. True-up must not already have run — `ERR_TRUE_UP_ALREADY_RUN`, on `POST /plan-years/{plan_year_id}/true-up`.
28. Allocation must be correctable — `ERR_CORRECTION_NOT_ALLOWED`, on `POST /match-allocations/{allocation_id}/corrections`.
29. At most one open plan year — `ERR_MULTIPLE_OPEN_PLAN_YEARS`, on `POST /plan-years/{plan_year_id}/status`.
30. An effective plan amendment must exist — `ERR_AMENDMENT_NOT_EFFECTIVE`, on `POST /loan-certifications/{certification_id}/decision`.
31. Segregation of duties on a void — `ERR_SEGREGATION_OF_DUTIES`, on `POST /loan-certifications/{certification_id}/audit-release`.
32. Referenced loans must be verified — `ERR_LOAN_NOT_VERIFIED`, on both `POST /loan-certifications/{certification_id}/lines` and `POST /loan-certifications/{certification_id}/decision`.
33. Employee must not be terminated — `ERR_EMPLOYEE_NOT_ELIGIBLE`, on both `POST /loan-certifications` and `POST /loan-certifications/{certification_id}/submit`.
34. Certification window must be open — `ERR_CERTIFICATION_WINDOW_CLOSED`, on `POST /loan-certifications/{certification_id}/submit`.
35. Payment date must fall inside the plan year — `ERR_PAYMENT_DATE_OUTSIDE_PLAN_YEAR`, on `POST /loan-certifications/{certification_id}/lines`.
36. Payment date must not be in the future — `ERR_PAYMENT_DATE_IN_FUTURE`, on `POST /loan-certifications/{certification_id}/lines`.
37. Amendment effective date must have arrived — `ERR_AMENDMENT_EFFECTIVE_DATE_FUTURE`, on `POST /plan-amendments/{amendment_id}/status`.
38. Covered windows must not overlap — `ERR_COVERED_PERIOD_OVERLAP`, on `POST /loan-certifications/{certification_id}/lines`.
39. At most one open claim, and a valid supersede target — `ERR_DUPLICATE_OPEN_CERTIFICATION`, on `POST /loan-certifications`.
40. One payroll line per employee and period — `ERR_DUPLICATE_CONTRIBUTION_RECORD`, on `POST /contribution-records`.
41. Period ordinal and pending-batch uniqueness — `ERR_DUPLICATE_PERIOD_RESOURCE`, on `POST /payroll-periods` and `POST /funding-batches`.
42. Leave intervals must not collide — `ERR_LEAVE_WINDOW_CONFLICT`, on `POST /leave-events`.
43. Unpaid-leave cap — `ERR_LEAVE_CAP_EXCEEDED`, on `POST /leave-events`.
44. A claim must carry at least one line — `ERR_NO_CERTIFIED_LINES`, on `POST /loan-certifications/{certification_id}/submit`.
45. A test needs a non-highly-compensated population — `ERR_NO_NHCE_POPULATION`, on `POST /nondiscrimination-tests/{test_id}/compute`.
46. A batch must carry at least one live allocation — `ERR_BATCH_EMPTY`, on `POST /funding-batches/{funding_batch_id}/transmit`.
47. Statutory space must remain — `ERR_QSLP_SPACE_EXHAUSTED`, on `POST /loan-certifications/{certification_id}/submit`.

Note in particular that ordinal 19, the claim from-state check, outranks every business rule below it, so an audit hold attempted on a claim that is not `ACCEPTED` reports `ERR_CERTIFICATION_STATE_INVALID` rather than any downstream compliance code; and that ordinal 32, loan verification, is evaluated before the duplicate and window rules that follow it but after the segregation-of-duties rule at ordinal 31.

### 2.11. Segregation of Duties and Audit Documentation

The sponsor's control environment requires that the person who approves money is not the person who unwinds it. When a claim is accepted, the accepting operator's `X-User-ID` is written to `accepted_by_user_id` on that claim and retained for the life of the record. An audit release that voids the claim must be issued under a different `X-User-ID`; if the voiding caller matches the stored `accepted_by_user_id`, the release is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). An audit release that merely clears the hold carries no such restriction.

Every correction adjustment is an audit artifact. It records `created_by_user_id` (the `X-User-ID` of the actor whose operation produced it), the `employee_id` and `plan_year_id` whose ledger it reconciles, a `reason_code`, a signed `amount_cents` in which negative values remove previously credited match, an optional free-text `note` that is null when omitted, an optional `match_allocation_id` that is null for ACP corrective forfeitures and for negative true-ups that reference no single allocation, and an optional `nondiscrimination_test_id` that is set only when a failed-test correction produced the row and null otherwise. The four recognized reasons are `ERRONEOUS_MATCH`, `CERTIFICATION_VOID`, `TRUE_UP_RECOUPMENT`, and `ACP_CORRECTIVE_FORFEITURE`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Plan Year and Amending the Plan Document

A `BenefitsAdministrator` opens the program by creating a **plan year**, which is the configuration record every other calculation reads. The creating payload carries the calendar `year` — an integer in the range 2024 through 2099, unique across plan years — together with the window fields `period_start` and `period_end`, the first and last instants of the plan year inclusive, and `certification_window_open` and `certification_deadline`, the first and last instants at which a participant may submit an annual claim, also inclusive. The economic parameters `compensation_cap_cents`, `annual_deferral_limit_cents`, `hce_prior_comp_threshold_cents`, `tier1_pct`, `tier1_match_rate`, `tier2_pct`, and `tier2_match_rate` are all optional and fall back to the defaults given in §2.6. So are the four remaining knobs: `nondiscrimination_test_method`, which is either `CURRENT_YEAR` (the default) or `PRIOR_YEAR` and records the plan year's default ACP testing method; `prior_year_nhce_acp`, the stored prior-year non-highly-compensated average contribution percentage carried to four decimal places and used only by the prior-year method, defaulting to 0.0000; `unpaid_leave_day_cap`, the greatest number of merged unpaid-leave days one employee may accrue inside the plan year, defaulting to 180 days; and `leave_merge_buffer_days`, defaulting to 14 days — two weeks — and used both by the leave-collision rule and by unpaid-leave merging. A newly created plan year is in `DRAFT` with `version` 1, `true_up_completed` false, `reopened_count` zero, and all four derived rollups at zero.

The plan year's `status` walks `DRAFT` → `OPEN` → `LOCKED` → `CLOSED`, with a revision loop back from `LOCKED` to `OPEN`; `CLOSED` is terminal. Advancing the status is a `BenefitsAdministrator` operation that names the destination in a `to_status` field.

`DRAFT` → `OPEN` is the moment the program becomes live, and it is guarded twice. No other plan year may already be in `OPEN`, or the transition is rejected with `ERR_MULTIPLE_OPEN_PLAN_YEARS`; and the plan year's own windows must be coherent, meaning `period_start` must be strictly earlier than `period_end` and `certification_window_open` must be no later than `certification_deadline`. Opening recomputes `hce_flag` for every enrolled employee against this plan year's `hce_prior_comp_threshold_cents`, causes every employee's `remaining_qslp_space_cents` to become non-null, and increments the plan year's `version` by one.

`OPEN` → `LOCKED` closes the certification window for the plan year and is what makes the annual true-up available. It requires that no loan certification of this plan year be sitting in `SUBMITTED` or `AUDIT_HOLD`; an in-flight claim or an open audit blocks the lock with `ERR_CERTIFICATION_STATE_INVALID`. The transition increments the plan year's `version` by one.

`LOCKED` → `OPEN` exists so a sponsor can reopen a plan year for revision. It is refused with `ERR_TEST_ALREADY_FINAL` when any nondiscrimination test of the plan year stands in `PASSED` or `CORRECTED`, because a finalized test is an authoritative statement about the plan year's numbers. When it succeeds it increments `reopened_count` by one, resets `true_up_completed` to false so a corrected true-up may run again, and increments `version` by one. The `LOCKED` → `OPEN` → `LOCKED` loop may repeat any number of times, and each pass re-opens the true-up.

`LOCKED` → `CLOSED` finalizes the plan year, and it requires that no funding batch of the plan year remain in `PENDING` or `TRANSMITTED`; unsettled money in flight blocks the close with `ERR_BATCH_STATE_INVALID`. Closing means no plan year is `OPEN` any more, which causes every employee's `remaining_qslp_space_cents` to become null, and it increments `version` by one.

Running the QSLP match at all requires an executed **plan amendment**. A `BenefitsAdministrator` records one by supplying the `plan_year_id` it authorizes, a `document_ref` pointing at the executed amendment page, and an `effective_date` on or after which the amendment may be declared effective. The amendment begins in `DRAFTED` and its `status` moves through `ADOPTED`, `NOTICE_SENT`, and finally `EFFECTIVE`; from either `ADOPTED` or `NOTICE_SENT` it may instead be abandoned into `RESCINDED`. `EFFECTIVE` and `RESCINDED` are both terminal. As with plan years, the destination is named in a `to_status` field, and a destination that does not match the amendment's current state is rejected with `ERR_AMENDMENT_STATE_INVALID`.

The four forward and abandon branches carry disjoint effects, and each of them increments the amendment's `version` by one:

- `DRAFTED` → `ADOPTED` requires the referenced plan year to still be in `DRAFT` or `OPEN`. It stamps `adopted_at` with the current logical clock; before this transition `adopted_at` is null.
- `ADOPTED` → `NOTICE_SENT` requires a `notice_channel` in the request body — one of `EMAIL`, `MAIL`, or `PORTAL` — and is rejected with `ERR_INVALID_REQUEST` when it is omitted. It stores the channel and stamps `notice_sent_at`, which is null before it.
- `NOTICE_SENT` → `EFFECTIVE` requires the current logical clock to be at or after the amendment's `effective_date`, and is rejected with `ERR_AMENDMENT_EFFECTIVE_DATE_FUTURE` when the date has not yet arrived; it also requires the referenced plan year to still be in `DRAFT` or `OPEN`. It stamps `effective_at`, which is null before it, and it is the event that unblocks claim acceptance for that plan year.
- `ADOPTED` → `RESCINDED` and `NOTICE_SENT` → `RESCINDED` both require a `rescinded_reason` in the request body, rejected with `ERR_INVALID_REQUEST` when absent, and both store it. Rescinding from `ADOPTED` means the amendment can no longer become effective; rescinding from `NOTICE_SENT` additionally retracts the participant notice. `rescinded_reason` is null on any amendment that was never rescinded.

### 3.2. The Participant Roster: Enrollment, HCE Status and Leave

A `BenefitsAdministrator` enrolls a participant by supplying an `external_id` — the sponsor's payroll identifier, unique across employees — a `hire_date`, and `prior_year_compensation_cents`, the prior plan-year compensation used solely for highly-compensated determination. `vesting_service_months`, the completed months of vesting service as of the plan-year end, is optional and defaults to 0. A new employee is created with `employment_status` `ACTIVE`, `termination_date` and `rehire_date` both null, and both the highly-compensated flag and the vested percentage computed immediately.

`hce_flag` is derived rather than supplied. It is evaluated against the unique plan year in `OPEN`: when no plan year is `OPEN`, `hce_flag` is false; otherwise it is true exactly when the employee's `prior_year_compensation_cents` is strictly greater than that plan year's `hce_prior_comp_threshold_cents`. It is re-evaluated when the employee is enrolled, when a plan year moves from `DRAFT` to `OPEN`, and on every read of the employee.

An employee read also surfaces five year-to-date aggregates, all measured inside the unique plan year in `OPEN` and all treating an absent contribution as zero rather than null: `ytd_eligible_compensation_cents` sums the employee's `counted_compensation_cents` across that plan year's payroll periods; `ytd_deferral_cents` sums `elective_deferral_cents`; `ytd_deferral_match_cents` sums `deferral_match_cents`; and `ytd_qslp_match_cents` sums `amount_cents` over the employee's match allocations in that plan year whose `funding_status` is `SCHEDULED` or `FUNDED`.

The sixth derived figure, `remaining_qslp_space_cents`, is the participant-facing expression of the anti-double-counting rule. When no plan year is in `OPEN` it is null. Otherwise, the reserved amount is the sum of `certified_total_cents` over the employee's certifications in that plan year whose `status` is `SUBMITTED`, `ACCEPTED`, or `AUDIT_HOLD`; and the remaining space is that plan year's `annual_deferral_limit_cents` less the employee's `ytd_deferral_cents` less the reserved amount, floored at zero. Because `DRAFT`, `RETURNED`, `VOIDED`, and `SUPERSEDED` sit outside the reserved set, submitting a claim and then having it returned restores the pre-submission figure exactly. The value is refreshed on every read of the employee and after any payroll line or claim status change.

Leave is recorded as an interval. Either a `BenefitsAdministrator` or a `PayrollOperator` may file one, naming the `employee_id`, the `leave_type` — one of `UNPAID`, `PAID_FMLA`, or `MILITARY` — and the inclusive `start_date` and `end_date`. The stored row exposes a computed `day_count`, the inclusive whole-day count between its own start and end. Leave events are audit rows: they carry `id` and `created_at` only.

Two rules guard a new leave interval. The **collision rule** inflates both the new interval and each existing interval of the same employee — of any leave type — by the plan year's `leave_merge_buffer_days` on both sides: the new interval is rejected with `ERR_LEAVE_WINDOW_CONFLICT` when its `start_date` is at or before an existing interval's `end_date` plus the buffer *and* its `end_date` is at or after that existing interval's `start_date` minus the buffer. Both intervals are closed, so equality collides. The **cap rule** then recomputes the merged unpaid-leave day count as it would stand after the new event were added, and rejects with `ERR_LEAVE_CAP_EXCEEDED` when that count would exceed the plan year's `unpaid_leave_day_cap`.

`unpaid_leave_days_ytd` on the employee is the merged figure itself. With no plan year in `OPEN` it is zero. Otherwise the system takes every `UNPAID` leave event of the employee that intersects the plan-year window — meaning its `end_date` is at or after `period_start` and its `start_date` is at or before `period_end` — and clips each one to that window, so the span begins at the later of the leave's `start_date` and `period_start` and ends at the earlier of the leave's `end_date` and `period_end`. The clipped spans are sorted by start ascending, ties broken by end ascending, and two adjacent spans are merged whenever the next span's start is at or before the previous span's end plus `leave_merge_buffer_days` days. Each merged span contributes the whole number of days between its own start and end, plus one for inclusivity, and `unpaid_leave_days_ytd` is the sum over merged spans.

Filing an `UNPAID` leave whose closed interval contains the current logical clock moves the employee from `ACTIVE` to `LEAVE_UNPAID`, provided the employee is not `TERMINATED`, the collision rule passes, and the merged unpaid-day count after the event is at or below the cap. The transition sets `employment_status` to `LEAVE_UNPAID`, refreshes `unpaid_leave_days_ytd`, and increments the employee's `version` by one. The employee returns from `LEAVE_UNPAID` to `ACTIVE` on its own: once the logical clock has advanced strictly past the `end_date` of every `UNPAID` leave of that employee, the next read of the employee observes `employment_status` `ACTIVE`, and that transition increments `version` by one as well. The `ACTIVE` → `LEAVE_UNPAID` → `ACTIVE` cycle may repeat any number of times. Leave of type `PAID_FMLA` or `MILITARY` is recorded without moving `employment_status`; the value `LEAVE_PAID` exists in the employment enumeration for paid-leave populations and is not produced by the unpaid-leave path.

### 3.3. Payroll Periods and the Elective-Deferral Match

A `PayrollOperator` divides each plan year into **payroll periods**, supplying the `plan_year_id`, an integer `period_number` of at least 1 that must be unique inside the plan year and that drives all chronological processing, the inclusive `start_date` and `end_date` of the pay period, and the `pay_date` on which wages for the period are paid. A duplicate ordinal inside the same plan year is rejected with `ERR_DUPLICATE_PERIOD_RESOURCE`. A new period starts in `status` `OPEN` with `reopen_count` at zero and both of its rollups — `total_eligible_compensation_cents`, the sum of `counted_compensation_cents` across its payroll lines, and `total_deferral_match_cents`, the sum of `deferral_match_cents` across the same lines — at zero.

A period's `status` walks `OPEN` → `CLOSED` → `FUNDED`, with a correction loop back from `CLOSED` to `OPEN`; `FUNDED` is terminal. Closing a period is a `PayrollOperator` action naming the destination in `to_status`, and it requires the owning plan year to be in `OPEN` or `LOCKED`. After the close no further payroll line may be created for the period, and the period's funding batch becomes transmittable. Reopening a period, `CLOSED` → `OPEN`, is refused with `ERR_PERIOD_HAS_SETTLED_FUNDING` when any funding batch of that period stands in `TRANSMITTED` or `SETTLED`; when it succeeds it increments `reopen_count` by one. A period that has reached `FUNDED` may never be reopened, and an attempt is rejected with `ERR_PERIOD_ALREADY_FUNDED` — the same code that rejects a payroll line posted to a period that is not `OPEN`. The move from `CLOSED` to `FUNDED` is not client-driven at all: it happens when a funding batch of that period reaches `SETTLED`. Every one of these transitions increments the period's `version` by one.

Posting a payroll line — a **contribution record** — is the `PayrollOperator`'s core operation and the point at which the elective-deferral match and the leftover tier space are computed. The payload carries `employee_id`, `payroll_period_id`, `eligible_compensation_cents` (plan-eligible compensation paid in the period, which must be zero or greater, with zero explicitly allowed for unpaid-leave periods) and `elective_deferral_cents` (the deferral withheld in the period, also zero or greater). Only one line may exist per employee and period; a second attempt is rejected with `ERR_DUPLICATE_CONTRIBUTION_RECORD`. The plan year must be `OPEN` and the period must be `OPEN`.

The line's four computed fields follow from a chronological accumulator over that employee's own lines in the same plan year, ordered by the owning period's `period_number` ascending with ties broken by the line's `created_at` ascending:

1. The prior counted amount is the sum of `counted_compensation_cents` over the employee's lines in that plan year whose period ordinal is strictly less than this line's.
2. `counted_compensation_cents` is the lesser of `eligible_compensation_cents` and the plan year's `compensation_cap_cents` less that prior counted amount, floored at zero. This is how the $345,000 annual pay ceiling stops counting mid-year.
3. The first tier ceiling is `counted_compensation_cents` multiplied by `tier1_pct`, and the second tier ceiling is `counted_compensation_cents` multiplied by `tier2_pct`. Both ceilings are carried at full precision.
4. The deferral dollars consumed at the first tier are the lesser of `elective_deferral_cents` and the first tier ceiling. The dollars consumed at the second tier are the lesser of the second tier ceiling and the excess of `elective_deferral_cents` over the first tier ceiling, that excess floored at zero.
5. `deferral_match_cents` is the first-tier consumption multiplied by `tier1_match_rate`, plus the second-tier consumption multiplied by `tier2_match_rate`, with the sum rounded half up to whole cents once.
6. `qslp_space_tier1_cents` is the first tier ceiling less the first-tier consumption, floored at zero, and `qslp_space_tier2_cents` is the second tier ceiling less the second-tier consumption, floored at zero. These two fields are the leftover ladder space that certified student loan payments are later allowed to fill, and they are the only channel by which the two feeds communicate.

A period in which `counted_compensation_cents` lands on zero — an unpaid-leave period, or a period posted after the compensation cap was already exhausted — yields zero tier ceilings, a zero match, and zero leftover space. No division occurs anywhere in this calculation.

Posting a line also recomputes the period's and the plan year's rollups, refreshes the employee's year-to-date aggregates and `remaining_qslp_space_cents`, and increments both the employee's and the plan year's `version` by one. One further effect closes the rehire loop: if the employee stands in `REHIRED` and the line's period has a `start_date` on or after the employee's `rehire_date`, the employee returns to `ACTIVE`, which increments the employee's `version` by one.

### 3.4. Registering Loans and Building the Annual Claim

Before a payment can be certified, the debt it was paid against must be on file. A participant — or a `BenefitsAdministrator` acting for one — registers a **loan account** with the borrower's `employee_id`, the `servicer_name`, `account_last4` (exactly four digits of the loan account number), and `original_principal_cents`, which must be strictly greater than zero. The account is created with `status` `UNVERIFIED` and `evidence_ref` null.

Verifying a loan is reserved to the `BenefitsAdministrator`, who names the destination in a `to_status` field — `VERIFIED` when the account is confirmed qualified education debt of that employee, `DISQUALIFIED` when it is not — and may attach an `evidence_ref` pointing at the supporting servicer statement. The operation writes both fields and increments the loan account's `version` by one.

The annual claim itself is a **loan certification**, and only the participant may open one. The creating payload carries the participant's own `employee_id`, the `plan_year_id` the annual claim covers, a `certification_method` of either `SELF_CERTIFICATION` or `SERVICER_STATEMENT` recording the evidence standard used, the `expected_employee_version` demanded by §2.9, and optionally `supersedes_certification_id` — the identifier of an already-accepted claim that this one replaces, left null for a first claim. Claim creation requires the plan year to be `OPEN` and the participant not to be `TERMINATED`, the latter enforced with `ERR_EMPLOYEE_NOT_ELIGIBLE`. It also enforces a one-claim-at-a-time discipline: no other certification of the same employee and plan year may stand in `DRAFT` or `SUBMITTED`, and when `supersedes_certification_id` is supplied it must name a certification of the same employee and plan year whose status is `ACCEPTED`. Either failure is reported as `ERR_DUPLICATE_OPEN_CERTIFICATION`. A new claim begins in `DRAFT` with `submitted_at`, `decided_at`, and `accepted_by_user_id` all null, `return_count` at zero, `certified_total_cents`, `eligible_total_cents`, `matched_total_cents`, and `unmatched_eligible_cents` all zero, `capped_by_statutory_room` false, and `audit_hold_reason` and `void_reason` null. Creating the claim increments the employee's `version` by one.

The claim's `status` enumeration is `DRAFT`, `SUBMITTED`, `RETURNED`, `ACCEPTED`, `AUDIT_HOLD`, `VOIDED`, and `SUPERSEDED`; the last two are terminal, and any operation against a claim already in `VOIDED` or `SUPERSEDED` is refused with `ERR_CERTIFICATION_TERMINAL`.

Payment detail lives in **certification lines**, which the participant adds to a claim while it is in `DRAFT` or `RETURNED`. Each line names the `loan_account_id` the payment was made against, the `payment_date`, the `amount_cents` paid (strictly greater than zero), and the billing window the payment covers as `covered_period_start` and `covered_period_end`. That window is deliberately **half-open**: the start instant is included and the end instant is excluded, and `covered_period_end` must be strictly after `covered_period_start`. Lines are audit rows carrying only `id` and `created_at`, and each addition recomputes the claim's `certified_total_cents` — the sum of `amount_cents` across the claim's lines — and increments the claim's `version` by one.

Four business rules police a new line. Its `payment_date` must fall inside the plan year's `period_start` through `period_end` window, or the line is rejected with `ERR_PAYMENT_DATE_OUTSIDE_PLAN_YEAR`, and it must be at or before the current logical clock, or the line is rejected with `ERR_PAYMENT_DATE_IN_FUTURE`. The referenced loan account must be `VERIFIED`, or the line is rejected with `ERR_LOAN_NOT_VERIFIED`. Finally, the same billing window must not be certified twice: the new line's half-open window must not intersect the window of any existing line on the *same* `loan_account_id` belonging to a certification whose status is `DRAFT`, `SUBMITTED`, `ACCEPTED`, or `AUDIT_HOLD`, and an intersection is rejected with `ERR_COVERED_PERIOD_OVERLAP`. Because the windows are half-open, two lines that merely touch — where the earlier window's end instant equals the later window's start instant — do not intersect and are both accepted.

Submitting the claim moves it `DRAFT` → `SUBMITTED`, and the same operation resubmits a claim `RETURNED` → `SUBMITTED` under identical preconditions. Submission requires the plan year to be `OPEN`, otherwise `ERR_PLAN_YEAR_LOCKED`; the participant not to be `TERMINATED`, otherwise `ERR_EMPLOYEE_NOT_ELIGIBLE`; the current logical clock to fall within the plan year's `certification_window_open` through `certification_deadline` window inclusive on both ends, otherwise `ERR_CERTIFICATION_WINDOW_CLOSED`; the claim to carry at least one line, otherwise `ERR_NO_CERTIFIED_LINES`; and the participant to have statutory room left. That last check computes the plan year's `annual_deferral_limit_cents` less the employee's `ytd_deferral_cents` less the sum of `certified_total_cents` over the employee's **other** certifications in this plan year whose status is `SUBMITTED`, `ACCEPTED`, or `AUDIT_HOLD`, floors the result at zero, and demands that it be strictly greater than zero; a result of zero is rejected with `ERR_QSLP_SPACE_EXHAUSTED`. A successful submission stamps `submitted_at` with the current logical clock, drops the employee's `remaining_qslp_space_cents` by the claim's `certified_total_cents` because the claim now counts in the reserved set, and increments both the employee's and the claim's `version` by one.

### 3.5. Adjudicating the Claim: Statutory Room and the Pay-Period Mirror Match

A `BenefitsAdministrator` adjudicates a `SUBMITTED` claim by recording a `decision` of either `RETURN` or `ACCEPT`, optionally with a `reason`. A claim that is not `SUBMITTED` is refused with `ERR_CERTIFICATION_STATE_INVALID`, and the plan year must still be `OPEN`.

`SUBMITTED` → `RETURNED` sends the claim back to the participant for rework. It increments `return_count` by one, stamps `decided_at` with the current logical clock, and — because `RETURNED` sits outside the reserved status set — restores the employee's `remaining_qslp_space_cents` to exactly its pre-submission value. Both the employee's and the claim's `version` increase by one. The `SUBMITTED` → `RETURNED` → `SUBMITTED` cycle may repeat, and `return_count` records how many times it has.

`SUBMITTED` → `ACCEPTED` is where money is created, and it is guarded by two rules beyond the state check. At least one plan amendment of the claim's plan year must stand in `EFFECTIVE` — the plan document must be amended and participants notified before any claim may be accepted — and otherwise the acceptance is rejected with `ERR_AMENDMENT_NOT_EFFECTIVE`. And every certification line of the claim must reference a loan account whose status is `VERIFIED`, re-checked here even though it was checked when the line was added, with `ERR_LOAN_NOT_VERIFIED` on failure. Acceptance writes `accepted_by_user_id` from the acting `X-User-ID` and stamps `decided_at`.

Acceptance then computes the claim's **eligible** amount, which is the certified amount trimmed to the statutory room actually left. The prior claimed amount is the sum of `eligible_total_cents` over the same employee's *other* certifications in the same plan year whose status is `ACCEPTED` or `AUDIT_HOLD`. The statutory room is the plan year's `annual_deferral_limit_cents` less the employee's `ytd_deferral_cents` less that prior claimed amount, floored at zero. `eligible_total_cents` is then the lesser of `certified_total_cents` and the statutory room, and `capped_by_statutory_room` is set true exactly when `eligible_total_cents` is strictly less than `certified_total_cents`. Where the statutory room lands on zero, `eligible_total_cents` is zero, no allocation is created at all, and `unmatched_eligible_cents` stays at zero.

The eligible dollars are then poured into the leftover tier space period by period — the `PAY_PERIOD_MIRROR` variant, so named because it mirrors the elective-deferral match period by period rather than settling the year as a whole. Let the remaining pool start at `eligible_total_cents`. The system walks the employee's contribution records in that plan year ordered by `period_number` ascending with ties broken by `created_at` ascending, and stops as soon as the remaining pool reaches zero. For each period it first measures how much of that period's space earlier claims already took: the first-tier consumption already recorded is the sum of `tier1_applied_cents` over match allocations for the same employee and the same period whose `funding_status` is `UNFUNDED`, `SCHEDULED`, or `FUNDED`, and the second-tier consumption is the sum of `tier2_applied_cents` over that same set. The free first-tier space is the line's `qslp_space_tier1_cents` less that first-tier consumption, floored at zero, and the free second-tier space is `qslp_space_tier2_cents` less the second-tier consumption, floored at zero. The system then takes the lesser of the remaining pool and the free first-tier space, reduces the pool by that amount, takes the lesser of the now-reduced pool and the free second-tier space, and reduces the pool again. The allocation amount for that period is the first-tier take multiplied by `tier1_match_rate` plus the second-tier take multiplied by `tier2_match_rate`, rounded half up to whole cents. A **match allocation** row is written only when that rounded amount is strictly greater than zero, recording `allocation_type` `MIRROR`, the `payroll_period_id` whose leftover space it consumed, the `certification_id` that produced it, `tier1_applied_cents` and `tier2_applied_cents` as the two takes, and `amount_cents` as the rounded figure. Rounding happens once per period allocation and the already-rounded allocations are then summed into every derived total; summing raw tier products across periods and rounding once at the end is not the declared behavior. Whatever remains in the pool once the walk finishes becomes the claim's `unmatched_eligible_cents` — the certified dollars that found no leftover space in any period and therefore earn nothing under this variant.

Every MIRROR allocation is created with `funding_status` `UNFUNDED` and `vesting_status` `UNVESTED`, and `vested_cents` and `forfeited_cents` at zero. Two things then happen automatically. If the employee's `vested_pct` is already 1.00, the allocation's `vesting_status` moves straight from `UNVESTED` to `FULLY_VESTED` with `vested_cents` equal to `amount_cents`. And if a `PENDING` funding batch exists for the allocation's plan year and target payroll period, the allocation's `funding_status` moves `UNFUNDED` → `SCHEDULED`, its `funding_batch_id` is set to that batch, and the batch's `total_allocated_cents`, `allocation_count`, and `net_funding_cents` are recomputed, as is the plan year's `total_qslp_match_funded_cents`. Where no `PENDING` batch exists for that period, the allocation simply stays `UNFUNDED` with `funding_batch_id` null.

Acceptance cascades further still. The plan year's `total_qslp_match_funded_cents` and `accepted_certification_count` are recomputed from the batch-attached allocations. Every nondiscrimination test of that plan year standing in `PASSED` or `FAILED` moves to `STALE`, because the plan year's funded totals just changed and the stored ratios are no longer authoritative. And when the accepted claim carried a `supersedes_certification_id`, the named claim moves `ACCEPTED` → `SUPERSEDED`: each of its allocations whose `funding_status` is `SCHEDULED` or `FUNDED` moves to `REVERSED`, one correction adjustment per reversed allocation is written with `reason_code` `ERRONEOUS_MATCH` and `amount_cents` equal to the negative of that allocation's `amount_cents`, and the affected funding batch and plan-year totals are recomputed. Acceptance increments the employee's, the plan year's, and the claim's `version` each by one; the superseded claim's `version` increments by one as well.

The claim exposes two further derived figures once allocations exist. `matched_total_cents` is the sum of `amount_cents` over the allocations bearing this `certification_id` whose `funding_status` is `SCHEDULED` or `FUNDED`. `unmatched_eligible_cents` is `eligible_total_cents` less the sum of `tier1_applied_cents` plus `tier2_applied_cents` over that same set of allocations — which is why a reversal, by removing allocations from the set, pushes eligible dollars back into the unmatched figure.

### 3.6. Funding Batches, the Recordkeeper Exchange and Forfeiture Offsets

Money reaches the recordkeeper in **funding batches**. A `PayrollOperator` opens one for a single payroll period by supplying the `plan_year_id` and the `payroll_period_id` it settles. At most one batch of a plan year may be `PENDING` for a given payroll period at a time; a second attempt is rejected with `ERR_DUPLICATE_PERIOD_RESOURCE`. A new batch is created with `status` `PENDING`, `transmitted_at` and `settled_at` null, `rejection_code` null, `retransmit_count` at zero, and its four money fields freshly computed. `total_allocated_cents` is the sum of `amount_cents` over the allocations bearing this batch's identifier whose `funding_status` is anything other than `REVERSED`, and `allocation_count` is how many such allocations there are — reversed allocations retain their `funding_batch_id` for audit purposes but are excluded from both figures. `forfeiture_offset_cents` is set by the forfeiture waterfall described below, and `net_funding_cents` is `total_allocated_cents` less `forfeiture_offset_cents`.

The **forfeiture offset waterfall** is what lets the sponsor pay new match out of forfeited money rather than fresh cash. It re-runs after any forfeiture record is created, after any funding batch is created, and after any allocation reversal. The pool is the sum of `amount_cents` over every forfeiture record of the plan year. The system walks the plan year's `PENDING` batches in `created_at` ascending order and, for each, sets `forfeiture_offset_cents` to the lesser of the pool still unapplied and that batch's `total_allocated_cents`, reduces the unapplied pool by that offset, and sets `net_funding_cents` to `total_allocated_cents` less the offset. Batches that are no longer `PENDING` keep the `forfeiture_offset_cents` they carried at the moment they left `PENDING` — later forfeitures never reach them — and their `net_funding_cents` remains `total_allocated_cents` less that frozen offset. Whatever is left of the pool once the walk finishes is the plan year's `forfeiture_balance_cents`.

A batch's `status` walks `PENDING` → `TRANSMITTED` → `SETTLED`, with a rejection branch and a retransmission loop; `SETTLED` is terminal. Transmission is a `PayrollOperator` action and is guarded three ways: the batch must be `PENDING`, otherwise `ERR_BATCH_STATE_INVALID`; the batch's payroll period must be `CLOSED`, otherwise `ERR_PERIOD_NOT_CLOSED`; and `allocation_count` must be at least 1, otherwise `ERR_BATCH_EMPTY`. Transmission stamps `transmitted_at` from the logical clock, freezes `forfeiture_offset_cents` at its pending value, and increments the batch's `version` by one.

The `Recordkeeper` answers with a settlement `outcome` of either `SETTLED` or `REJECTED`, and either answer requires the batch to be `TRANSMITTED`, otherwise `ERR_BATCH_STATE_INVALID`. The two branches are deliberately asymmetric:

- `TRANSMITTED` → `SETTLED` stamps `settled_at` from the logical clock, moves every allocation of the batch `SCHEDULED` → `FUNDED` on the funding dimension, moves the batch's payroll period `CLOSED` → `FUNDED`, and increments the batch's `version` by one. Funding leaves `vesting_status` entirely untouched — the two dimensions of an allocation evolve independently and neither gates the other.
- `TRANSMITTED` → `REJECTED` requires a `rejection_code` in the body, rejected with `ERR_INVALID_REQUEST` when omitted, stores that code, leaves every allocation of the batch in `SCHEDULED`, and increments the batch's `version` by one.

A rejected batch is retried through the same transmission operation the `PayrollOperator` used the first time: from `REJECTED` the batch re-enters `PENDING`, `retransmit_count` increases by one, `rejection_code` is cleared, and the batch immediately re-enters `TRANSMITTED` within the same request, incrementing `version`. That `REJECTED` → `PENDING` → `TRANSMITTED` loop may repeat as often as the recordkeeper requires.

### 3.7. Mid-Year Employment Change, Vesting and Forfeiture

Employment changes are recorded as events against the participant by a `BenefitsAdministrator`, naming an `event_type` of `TERMINATE` or `REHIRE` together with the `effective_date` on which it takes force.

`TERMINATE` is accepted from `ACTIVE`, `LEAVE_UNPAID`, `LEAVE_PAID`, or `REHIRED`. It sets `termination_date` to the supplied `effective_date` and then triggers the longest cascade in the system: vesting is evaluated over the employee's allocations, each partially or wholly unvested allocation produces a forfeiture record, the plan year's `forfeiture_balance_cents` is recomputed from those new records, and the offset waterfall re-runs over every `PENDING` funding batch of the plan year, rewriting each batch's `forfeiture_offset_cents` and `net_funding_cents`. The employee's `version` increases by one.

Vesting is a cliff schedule read off `vesting_service_months`: `vested_pct` is 0.00 below 24 months, 0.40 from 24 through 35 months, 0.60 from 36 through 47 months, 0.80 from 48 through 59 months, and 1.00 at 60 months or more. In other words nothing vests before two years of service and everything vests at five. Evaluation touches the employee's match allocations whose `funding_status` is `SCHEDULED` or `FUNDED` and whose `vesting_status` is `UNVESTED` or `PARTIALLY_VESTED`, processed in `created_at` ascending order. For each such allocation, `vested_cents` becomes `amount_cents` multiplied by `vested_pct`, rounded half up to whole cents, and `forfeited_cents` becomes `amount_cents` less `vested_cents`. The resulting `vesting_status` is `FULLY_VESTED` when `forfeited_cents` is zero, `FORFEITED` when `vested_cents` is zero, and `PARTIALLY_VESTED` otherwise. Whenever `forfeited_cents` is strictly greater than zero the system writes a **forfeiture record** carrying the `match_allocation_id`, the `employee_id`, the `plan_year_id` whose pool receives the money, the forfeited `amount_cents`, and a `reason_code` of `TERMINATION_UNVESTED` when `vested_cents` is zero or `TERMINATION_PARTIAL_VESTING` when some portion vested. Forfeiture records are audit rows with only `id` and `created_at`. The rounding order is fixed: the vested portion is rounded per allocation, and the per-allocation forfeitures are then summed into the plan-year pool.

Read as state transitions, the three vesting outcomes are `UNVESTED` → `FULLY_VESTED` when `vested_pct` equals 1.00 (also reachable at allocation creation, as noted in §3.5), `UNVESTED` → `PARTIALLY_VESTED` when `vested_pct` sits strictly between 0.00 and 1.00, and `UNVESTED` → `FORFEITED` when `vested_pct` equals 0.00; the latter two require the allocation's `funding_status` to be `SCHEDULED` or `FUNDED`, and the fully-forfeited case is the one that most visibly moves `forfeiture_balance_cents` and every pending batch's offset.

`REHIRE` closes the loop. It is accepted only when `employment_status` is `TERMINATED` and the supplied `effective_date` is strictly after the stored `termination_date`. It writes `rehire_date`, preserves `vesting_service_months` without reset, restores certification eligibility so the terminated-employee check passes again, moves the employee to `REHIRED`, and increments `version` by one. The participant returns to `ACTIVE` when a payroll line is posted for a period beginning on or after `rehire_date`, as described in §3.3, closing the `ACTIVE` → `TERMINATED` → `REHIRED` → `ACTIVE` cycle.

### 3.8. The Annual True-Up

Once the plan year is `LOCKED`, the `BenefitsAdministrator` runs the annual true-up — the `ANNUAL_TRUE_UP` variant of the match, and the second and final answer to how much QSLP match each participant is owed. It ignores period boundaries entirely, recomputes the combined annual entitlement on annual compensation and annual contributions, and pays or recoups the difference against what the mirror variant already funded — which is how certified dollars stranded by period-level fluctuation are recovered. The run is refused with `ERR_PLAN_YEAR_NOT_LOCKED` unless the plan year is `LOCKED`, and with `ERR_TRUE_UP_ALREADY_RUN` when `true_up_completed` is already true. Supplying an `employee_id` limits the run to that participant; omitting it processes every employee with at least one payroll line in the plan year, in `Employee.created_at` ascending order.

The run captures the current logical clock as its start instant and then, for each participant, executes four steps in exactly this order. The order matters because the true-up reads funded totals and then changes them, so the set of rows it counts must be fixed before it writes anything.

**Step one.** Annual counted compensation is the lesser of the sum of `counted_compensation_cents` over the participant's payroll lines in this plan year and the plan year's `compensation_cap_cents`.

**Step two.** The annual eligible QSLP amount is the sum of `eligible_total_cents` over the participant's certifications in this plan year whose status is `ACCEPTED` or `AUDIT_HOLD`. The combined contribution is the participant's `ytd_deferral_cents` plus that annual eligible amount. The first-tier portion is the lesser of the combined contribution and annual counted compensation multiplied by `tier1_pct`; the second-tier portion is the lesser of annual counted compensation multiplied by `tier2_pct` and the excess of the combined contribution over annual counted compensation multiplied by `tier1_pct`, that excess floored at zero. The combined entitlement is the first-tier portion multiplied by `tier1_match_rate` plus the second-tier portion multiplied by `tier2_match_rate`, rounded half up to whole cents once.

**Step three.** Three already-funded quantities are measured. The funded deferral match is the sum of `deferral_match_cents` over the participant's payroll lines in this plan year. The funded QSLP match is the sum of `amount_cents` over the participant's match allocations in this plan year whose `funding_status` is `SCHEDULED` or `FUNDED` **and** whose `created_at` is strictly earlier than the run's start instant — which excludes reversed allocations and also excludes any row this very run is about to write. The recouped amount is the sum of `amount_cents` over the participant's correction adjustments in this plan year whose `reason_code` is `TRUE_UP_RECOUPMENT`, a quantity that is zero or negative.

**Step four.** The delta is the combined entitlement less the funded deferral match less the funded QSLP match less the recouped amount. When the delta is strictly positive, the run creates a match allocation with `allocation_type` `TRUE_UP`, `amount_cents` equal to the delta, and both `certification_id` and `payroll_period_id` null, because a true-up allocation belongs to no single claim and no single period; its `tier1_applied_cents` and `tier2_applied_cents` are zero. When the delta is strictly negative, the run instead creates a correction adjustment with `reason_code` `TRUE_UP_RECOUPMENT`, `amount_cents` equal to the delta, and `match_allocation_id` null. When the delta is exactly zero, nothing is created.

A `TRUE_UP` allocation still needs a batch. The candidate pool is the plan year's funding batches whose `status` is `PENDING`; among them the system selects the one whose payroll period has the greatest `period_number`, breaking ties by the earliest `created_at`. If the pool is empty the allocation stays at `funding_status` `UNFUNDED` with `funding_batch_id` null.

Completing the run sets `true_up_completed` to true, recomputes the plan year's `total_qslp_match_funded_cents`, moves every nondiscrimination test of the plan year standing in `PASSED` or `FAILED` to `STALE`, increments the plan year's `version` by one, and increments the `version` of each processed employee by one. The response summarizes the run with `true_up_allocation_count`, `recoupment_count`, `total_true_up_cents`, `total_recoupment_cents`, and `employee_count`.

### 3.9. Nondiscrimination Testing, Audit Hold and Correction of Erroneous Matches

Because the QSLP match is an employer matching contribution, it enters the plan's ACP nondiscrimination test. A `ComplianceAuditor` opens a **nondiscrimination test** for a plan year, choosing the `test_method` — `CURRENT_YEAR` or `PRIOR_YEAR` — that decides which non-highly-compensated average the limit is built from. The test begins in `PENDING` with all five computed figures at their zero defaults and `computed_at` null. Its `status` enumeration is `PENDING`, `PASSED`, `FAILED`, `CORRECTED`, and `STALE`; `CORRECTED` is terminal.

Computing the test is available while its status is `PENDING` or `STALE`; any other status is refused with `ERR_TEST_ALREADY_FINAL`, and the plan year must be `OPEN` or `LOCKED`. The compute payload carries an optional `include_qslp_match` flag, which defaults to true and is stored on the test as the record of whether QSLP match allocations entered each participant's contribution ratio.

The population under test is every employee with at least one payroll line in the plan year whose total `counted_compensation_cents` is strictly greater than zero. For each such participant, the numerator is the sum of `deferral_match_cents` over that participant's payroll lines in the plan year, plus — only when `include_qslp_match` is true — the sum of `amount_cents` over that participant's match allocations in the plan year whose `funding_status` is `SCHEDULED` or `FUNDED`, plus the sum of `amount_cents` over that participant's correction adjustments in the plan year whose `reason_code` is either `ACP_CORRECTIVE_FORFEITURE` or `TRUE_UP_RECOUPMENT`. The denominator is the participant's total `counted_compensation_cents`. The participant's contribution ratio is the numerator divided by the denominator, rounded half up to four decimal places — the first of the two roundings.

Participants split on `hce_flag` into a highly compensated group and a non-highly-compensated group, whose sizes are stored as `hce_count` and `nhce_count`. A test with no non-highly-compensated participant has no reference population and is rejected with `ERR_NO_NHCE_POPULATION`. `hce_acp` is 0.0000 when `hce_count` is zero, and otherwise the sum of the already-rounded highly-compensated ratios divided by `hce_count`, rounded half up to four decimal places — the second rounding. Under the current-year method `nhce_acp` is computed the same way from the non-highly-compensated group; under the prior-year method it is simply read from the plan year's stored `prior_year_nhce_acp`, so identical current-year data can produce a different limit and a different outcome depending on which method the test was opened with. `limit_acp` is the greater of two candidates, rounded half up to four decimal places: `nhce_acp` multiplied by 1.25, and the lesser of `nhce_acp` multiplied by 2 and `nhce_acp` plus 0.02.

The compute stores `hce_acp`, `nhce_acp`, `limit_acp`, `hce_count`, `nhce_count`, `include_qslp_match`, and `computed_at`, and increments the test's `version` by one. The two outcomes fork with genuinely different consequences. When `hce_acp` is less than or equal to `limit_acp` the test moves `PENDING` → `PASSED`, which blocks the plan year's `LOCKED` → `OPEN` reopen with `ERR_TEST_ALREADY_FINAL`. When `hce_acp` is strictly greater than `limit_acp` the test moves `PENDING` → `FAILED`, which does not block the reopen but does open the correction path. Recomputing from `STALE` follows the same two branches — `STALE` → `PASSED` or `STALE` → `FAILED` on the same comparison — overwriting the stored ratios with the recomputed values and incrementing `version` by one.

Any movement in the plan year's funded match totals stales a completed test. Accepting a claim, voiding a claim, correcting an allocation, or running the annual true-up moves each test of that plan year `PASSED` → `STALE` or `FAILED` → `STALE` as applicable: the stored ratios are retained for audit but are no longer authoritative, the plan year's `LOCKED` → `OPEN` reopen becomes available again, and the test's `version` increases by one. The `PASSED` or `FAILED` → `STALE` → `PASSED` or `FAILED` cycle repeats for as long as the ledger keeps moving.

Correcting a failed test is the `ComplianceAuditor`'s remedy and requires status `FAILED`, otherwise `ERR_TEST_ALREADY_FINAL`. The caller names the `correction_method`, either `QNEC` or `CORRECTIVE_FORFEITURE`. The system walks the highly compensated participants in `Employee.created_at` ascending order and, for each whose rounded contribution ratio exceeds `limit_acp`, computes the excess as the difference between that ratio and `limit_acp` multiplied by the participant's total `counted_compensation_cents`, rounded half up to whole cents per participant. It then writes a correction adjustment for that participant carrying the `employee_id`, the `plan_year_id`, the `nondiscrimination_test_id` of this test, `reason_code` `ACP_CORRECTIVE_FORFEITURE`, `match_allocation_id` null, and `amount_cents` equal to the negative of the excess. The test's `total_correction_cents` becomes the sum of `amount_cents` over the adjustments bearing this test's identifier, the plan year's `total_deferral_match_funded_cents` is recomputed, the test moves `FAILED` → `CORRECTED`, and both the test's and the plan year's `version` increase by one.

Audit review of an individual claim runs on a separate track. A `ComplianceAuditor` may place an `ACCEPTED` claim on hold, supplying a `reason` that is stored as `audit_hold_reason`; a claim that is not `ACCEPTED` is refused with `ERR_CERTIFICATION_STATE_INVALID`. Moving `ACCEPTED` → `AUDIT_HOLD` deliberately touches no money: the claim's allocations stay `SCHEDULED` or `FUNDED` and every funded total is unchanged. Only the claim's `version` increases by one.

Releasing the hold takes a `resolution` of either `CLEAR` or `VOID`, with an optional `note`, and requires the claim to be in `AUDIT_HOLD`. `CLEAR` returns the claim `AUDIT_HOLD` → `ACCEPTED`, clears `audit_hold_reason`, and increments the claim's `version` by one; that review cycle may repeat without ever moving money. `VOID` is the compensating branch and is the operation the segregation-of-duties rule of §2.11 guards: it must be issued by a different `X-User-ID` than the stored `accepted_by_user_id`, or it is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful void moves the claim `AUDIT_HOLD` → `VOIDED`, stores the supplied note as `void_reason`, and then unwinds the acceptance completely: every match allocation of the claim whose `funding_status` is `SCHEDULED` or `FUNDED` moves to `REVERSED` and detaches from the batch's arithmetic while retaining its `funding_batch_id` for audit; one correction adjustment is written per reversed allocation with `reason_code` `CERTIFICATION_VOID` and `amount_cents` equal to the negative of that allocation's `amount_cents`; the batch's `total_allocated_cents`, `allocation_count`, and `net_funding_cents` are recomputed; the plan year's `total_qslp_match_funded_cents` returns to exactly its pre-acceptance value; and the employee's `remaining_qslp_space_cents` returns to exactly its pre-submission value. The employee's, the plan year's, and the claim's `version` each increase by one.

Individual erroneous matches are corrected without touching the claim. A `BenefitsAdministrator` records a correction against a single match allocation, supplying the `reason_code`, the `expected_plan_year_version` demanded by §2.9, and an optional `note`. The allocation's `funding_status` must be `SCHEDULED` or `FUNDED`; an allocation that is still `UNFUNDED` or already `REVERSED` is refused with `ERR_CORRECTION_NOT_ALLOWED`. The operation moves the allocation `SCHEDULED` → `REVERSED` or `FUNDED` → `REVERSED` as the case may be, writes a correction adjustment whose `amount_cents` is the negative of the allocation's `amount_cents` and whose `created_by_user_id` is the acting `X-User-ID`, recomputes the funding batch's totals and the plan year's `total_qslp_match_funded_cents`, moves every `PASSED` or `FAILED` nondiscrimination test of the plan year to `STALE`, and increments both the plan year's and the employee's `version` by one. The created adjustment is what the operation returns.

Finally, audit documentation for a single participant is available as a computed **audit packet**, readable by a `ComplianceAuditor` or a `BenefitsAdministrator`. It selects the plan year whose `status` is `OPEN` or `LOCKED`, preferring the `OPEN` one when both exist and otherwise the `LOCKED` one with the greatest `year`, and reports that plan year's identifier as `plan_year_id`. `certification_count` counts the participant's certifications in that plan year whose status is any of `SUBMITTED`, `RETURNED`, `ACCEPTED`, `AUDIT_HOLD`, `VOIDED`, or `SUPERSEDED` — a claim still in `DRAFT` is not yet audit-visible. `accepted_certified_cents` sums `eligible_total_cents` over the participant's claims in that plan year whose status is `ACCEPTED` or `AUDIT_HOLD`. `deferral_match_cents` sums the participant's `deferral_match_cents` across that plan year's payroll lines, and `qslp_match_cents` sums `amount_cents` over the participant's allocations in that plan year whose `funding_status` is `SCHEDULED` or `FUNDED`. `forfeited_cents` sums `amount_cents` over the participant's forfeiture records in that plan year and `correction_cents` sums `amount_cents` over the participant's correction adjustments in that plan year, so a participant whose match was unwound shows a negative correction figure. `remaining_space_cents` simply reports the participant's current `remaining_qslp_space_cents`.

## 4. Endpoint Definitions

Operations that bring a brand-new resource into existence — a plan year, an amendment, an employee, a leave event, a payroll period, a payroll line, a loan account, a claim, a claim line, a funding batch, a nondiscrimination test, or a correction adjustment — return `201 Created`. Every other operation, including all state transitions, all computed runs, all reads, and the logical-clock capability, returns `200 OK`. Filter parameters on list endpoints are optional and combine conjunctively; `limit` and `offset` behave as described in §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plan-years` | Create a plan year in `DRAFT` with its match formula, limits and certification window | BenefitsAdministrator |
| GET | `/plan-years/{plan_year_id}` | Read one plan year with its derived funded totals and forfeiture balance | BenefitsAdministrator, PayrollOperator, ComplianceAuditor, Recordkeeper |
| GET | `/plan-years` | List plan years; filter by `status`, `year` | BenefitsAdministrator, PayrollOperator, ComplianceAuditor, Recordkeeper |
| POST | `/plan-years/{plan_year_id}/status` | Advance the plan year `DRAFT` → `OPEN` → `LOCKED` → `CLOSED`, or reopen `LOCKED` → `OPEN` | BenefitsAdministrator |
| POST | `/plan-years/{plan_year_id}/true-up` | Run the annual true-up for one participant or for every participant | BenefitsAdministrator |
| POST | `/plan-amendments` | Record a drafted plan-document amendment authorizing the QSLP match | BenefitsAdministrator |
| GET | `/plan-amendments/{amendment_id}` | Read one amendment with its adoption and notice timestamps | BenefitsAdministrator, ComplianceAuditor |
| GET | `/plan-amendments` | List amendments; filter by `plan_year_id`, `status` | BenefitsAdministrator, ComplianceAuditor |
| POST | `/plan-amendments/{amendment_id}/status` | Adopt, record participant notice, declare effective, or rescind an amendment | BenefitsAdministrator |
| POST | `/employees` | Enroll an employee in the plan | BenefitsAdministrator |
| GET | `/employees/{employee_id}` | Read one employee with HCE flag, YTD aggregates, remaining statutory QSLP space and vested percentage | BenefitsAdministrator, PayrollOperator, ComplianceAuditor, Employee |
| GET | `/employees` | List employees; filter by `employment_status`, `hce_flag`, `external_id` | BenefitsAdministrator, PayrollOperator, ComplianceAuditor |
| POST | `/employees/{employee_id}/employment-events` | Record a mid-year employment change (`TERMINATE` or `REHIRE`) | BenefitsAdministrator |
| GET | `/employees/{employee_id}/audit-packet` | Computed audit-documentation summary for one employee in the current plan year | ComplianceAuditor, BenefitsAdministrator |
| POST | `/leave-events` | Record a leave interval for an employee | BenefitsAdministrator, PayrollOperator |
| GET | `/leave-events/{leave_event_id}` | Read one leave event | BenefitsAdministrator, PayrollOperator, ComplianceAuditor |
| GET | `/leave-events` | List leave events; filter by `employee_id`, `leave_type` | BenefitsAdministrator, PayrollOperator, ComplianceAuditor |
| POST | `/payroll-periods` | Create a payroll period inside a plan year | PayrollOperator |
| GET | `/payroll-periods/{payroll_period_id}` | Read one payroll period with its compensation and match totals | PayrollOperator, BenefitsAdministrator, ComplianceAuditor, Recordkeeper |
| GET | `/payroll-periods` | List payroll periods; filter by `plan_year_id`, `status` | PayrollOperator, BenefitsAdministrator, ComplianceAuditor, Recordkeeper |
| POST | `/payroll-periods/{payroll_period_id}/status` | Close a payroll period or reopen it for late payroll corrections | PayrollOperator |
| POST | `/contribution-records` | Post one employee's payroll line for a period; computes the elective-deferral match and leftover QSLP tier space | PayrollOperator |
| GET | `/contribution-records/{contribution_record_id}` | Read one payroll line with its computed match and QSLP space | PayrollOperator, BenefitsAdministrator, ComplianceAuditor |
| GET | `/contribution-records` | List payroll lines; filter by `employee_id`, `payroll_period_id` | PayrollOperator, BenefitsAdministrator, ComplianceAuditor |
| POST | `/loan-accounts` | Register a student-loan account for an employee | Employee, BenefitsAdministrator |
| GET | `/loan-accounts/{loan_account_id}` | Read one loan account | Employee, BenefitsAdministrator, ComplianceAuditor |
| GET | `/loan-accounts` | List loan accounts; filter by `employee_id`, `status` | Employee, BenefitsAdministrator, ComplianceAuditor |
| POST | `/loan-accounts/{loan_account_id}/verification` | Verify or disqualify a loan account as qualified education debt | BenefitsAdministrator |
| POST | `/loan-certifications` | Open an annual claim in `DRAFT`, optionally superseding an accepted claim | Employee |
| GET | `/loan-certifications/{certification_id}` | Read one annual claim with its certified, eligible, matched and unmatched totals | Employee, BenefitsAdministrator, ComplianceAuditor |
| GET | `/loan-certifications` | List annual claims; filter by `employee_id`, `plan_year_id`, `status`, `supersedes_certification_id` | Employee, BenefitsAdministrator, ComplianceAuditor |
| POST | `/loan-certifications/{certification_id}/lines` | Add a certified qualified payment line to a `DRAFT` or `RETURNED` claim | Employee |
| GET | `/loan-certifications/{certification_id}/lines` | List the payment lines of one claim | Employee, BenefitsAdministrator, ComplianceAuditor |
| GET | `/certification-lines/{certification_line_id}` | Read one certified payment line | Employee, BenefitsAdministrator, ComplianceAuditor |
| GET | `/certification-lines` | List certified payment lines; filter by `certification_id`, `loan_account_id` | Employee, BenefitsAdministrator, ComplianceAuditor |
| POST | `/loan-certifications/{certification_id}/submit` | Submit or resubmit the annual claim for sponsor review | Employee |
| POST | `/loan-certifications/{certification_id}/decision` | Accept or return a submitted claim; acceptance computes the pay-period mirror match | BenefitsAdministrator |
| POST | `/loan-certifications/{certification_id}/audit-hold` | Place an accepted claim on audit hold for documentation review | ComplianceAuditor |
| POST | `/loan-certifications/{certification_id}/audit-release` | Release an audit hold by clearing the claim or voiding it with full compensating reversal | ComplianceAuditor |
| GET | `/match-allocations/{allocation_id}` | Read one QSLP match allocation with both of its independent state dimensions | BenefitsAdministrator, Recordkeeper, ComplianceAuditor, Employee |
| GET | `/match-allocations` | List match allocations; filter by `employee_id`, `plan_year_id`, `certification_id`, `payroll_period_id`, `funding_batch_id`, `allocation_type`, `funding_status`, `vesting_status` | BenefitsAdministrator, Recordkeeper, ComplianceAuditor, Employee |
| POST | `/match-allocations/{allocation_id}/corrections` | Correct an erroneous match: reverse the allocation and record the signed audit adjustment | BenefitsAdministrator |
| GET | `/correction-adjustments/{correction_id}` | Read one correction adjustment | BenefitsAdministrator, ComplianceAuditor |
| GET | `/correction-adjustments` | List correction adjustments; filter by `match_allocation_id`, `employee_id`, `plan_year_id`, `nondiscrimination_test_id`, `reason_code` | BenefitsAdministrator, ComplianceAuditor |
| POST | `/funding-batches` | Open a `PENDING` funding batch for one payroll period | PayrollOperator |
| GET | `/funding-batches/{funding_batch_id}` | Read one funding batch with allocated, offset and net funding amounts | PayrollOperator, Recordkeeper, BenefitsAdministrator, ComplianceAuditor |
| GET | `/funding-batches` | List funding batches; filter by `plan_year_id`, `payroll_period_id`, `status` | PayrollOperator, Recordkeeper, BenefitsAdministrator, ComplianceAuditor |
| POST | `/funding-batches/{funding_batch_id}/transmit` | Transmit the batch to the recordkeeper; a rejected batch re-enters `PENDING` and is transmitted again in the same request | PayrollOperator |
| POST | `/funding-batches/{funding_batch_id}/settlement` | Recordkeeper settlement response: settle every scheduled allocation, or reject for retransmission | Recordkeeper |
| GET | `/forfeiture-records/{forfeiture_id}` | Read one forfeiture record | BenefitsAdministrator, ComplianceAuditor |
| GET | `/forfeiture-records` | List forfeiture records; filter by `employee_id`, `plan_year_id`, `match_allocation_id` | BenefitsAdministrator, ComplianceAuditor |
| POST | `/nondiscrimination-tests` | Open an ACP nondiscrimination test for a plan year under a chosen testing method | ComplianceAuditor |
| GET | `/nondiscrimination-tests/{test_id}` | Read one test with its computed ratios and limit | ComplianceAuditor, BenefitsAdministrator |
| GET | `/nondiscrimination-tests` | List tests; filter by `plan_year_id`, `status` | ComplianceAuditor, BenefitsAdministrator |
| POST | `/nondiscrimination-tests/{test_id}/compute` | Compute the ACP test | ComplianceAuditor |
| POST | `/nondiscrimination-tests/{test_id}/correction` | Correct a failed ACP test, creating per-HCE corrective adjustments | ComplianceAuditor |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical UTC clock | BenefitsAdministrator, PayrollOperator, ComplianceAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PLAN_YEAR_NOT_FOUND` | 404 |
| `ERR_EMPLOYEE_NOT_FOUND` | 404 |
| `ERR_PAYROLL_PERIOD_NOT_FOUND` | 404 |
| `ERR_LOAN_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_FUNDING_BATCH_NOT_FOUND` | 404 |
| `ERR_AMENDMENT_NOT_FOUND` | 404 |
| `ERR_TEST_NOT_FOUND` | 404 |
| `ERR_RECORD_NOT_FOUND` | 404 |
| `ERR_STALE_EMPLOYEE_VERSION` | 412 |
| `ERR_STALE_PLAN_YEAR_VERSION` | 412 |
| `ERR_PLAN_YEAR_LOCKED` | 409 |
| `ERR_CERTIFICATION_TERMINAL` | 409 |
| `ERR_CERTIFICATION_STATE_INVALID` | 409 |
| `ERR_PERIOD_NOT_CLOSED` | 409 |
| `ERR_PERIOD_ALREADY_FUNDED` | 409 |
| `ERR_PERIOD_HAS_SETTLED_FUNDING` | 409 |
| `ERR_BATCH_STATE_INVALID` | 409 |
| `ERR_AMENDMENT_STATE_INVALID` | 409 |
| `ERR_TEST_ALREADY_FINAL` | 409 |
| `ERR_PLAN_YEAR_NOT_LOCKED` | 409 |
| `ERR_TRUE_UP_ALREADY_RUN` | 409 |
| `ERR_CORRECTION_NOT_ALLOWED` | 409 |
| `ERR_MULTIPLE_OPEN_PLAN_YEARS` | 409 |
| `ERR_AMENDMENT_NOT_EFFECTIVE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_LOAN_NOT_VERIFIED` | 422 |
| `ERR_EMPLOYEE_NOT_ELIGIBLE` | 422 |
| `ERR_CERTIFICATION_WINDOW_CLOSED` | 422 |
| `ERR_PAYMENT_DATE_OUTSIDE_PLAN_YEAR` | 422 |
| `ERR_PAYMENT_DATE_IN_FUTURE` | 422 |
| `ERR_AMENDMENT_EFFECTIVE_DATE_FUTURE` | 422 |
| `ERR_COVERED_PERIOD_OVERLAP` | 409 |
| `ERR_DUPLICATE_OPEN_CERTIFICATION` | 409 |
| `ERR_DUPLICATE_CONTRIBUTION_RECORD` | 409 |
| `ERR_DUPLICATE_PERIOD_RESOURCE` | 409 |
| `ERR_LEAVE_WINDOW_CONFLICT` | 409 |
| `ERR_LEAVE_CAP_EXCEEDED` | 422 |
| `ERR_NO_CERTIFIED_LINES` | 422 |
| `ERR_NO_NHCE_POPULATION` | 422 |
| `ERR_BATCH_EMPTY` | 422 |
| `ERR_QSLP_SPACE_EXHAUSTED` | 422 |
