# Homeowner Rehabilitation Loan Program API — Product Requirements Document

## 1. Introduction

Community Development Block Grant (CDBG) housing rehabilitation is one of the most heavily audited activities a local government runs. A single assisted dwelling accumulates an income certification, a title examination, a property standards inspection, a scope of work with itemized cost estimates, a competitive bid file, a lead-based paint determination, a historic preservation determination, a recorded mortgage lien, a series of inspected construction draws, change orders, a close-out, a forgiveness or repayment schedule, a recapture calculation on sale, and a warranty file against the contractor. Today that record lives in spreadsheets and paper folders, and the program's two hardest obligations — never committing more money than the entitlement allocation holds, and never letting a compliance protocol be skipped — depend entirely on staff memory.

This service replaces that folder with a single system of record for the rehabilitation activity, mounted under `/rehab`. It carries the program year's ledger, the household's eligibility determination, the dwelling's compliance posture, the approved contractor list with its performance standing, and the loan's full money trail from lien recording through recapture. Every state change is a deliberate, role-gated operation, and every dollar movement is conserved across three buckets — uncommitted, committed and disbursed — so that a monitoring visit can reconcile the allocation at any instant.

Two design commitments shape everything that follows. First, compliance is a **second, independent axis** on the case record: a dwelling can be perfectly on schedule in its construction workflow and still be frozen because an approved change order re-opened the lead-based paint protocol. Second, the program deliberately separates preparation from approval and inspection from payment; the same staff member may never sit on both sides of those pairs.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. Program Participants and Role-Based Access Control

Every request must carry two headers. `X-User-ID` identifies the acting user, and `X-User-Role` names the role under which the request is made. A request whose `X-User-Role` header is missing, empty, or not one of the seven role names defined below is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing takes place — no row is loaded, no body is parsed.

The seven roles are `Applicant`, `Contractor`, `IntakeSpecialist`, `RehabSpecialist`, `Inspector`, `LoanOfficer` and `ProgramManager`.

- An `Applicant` is the assisted homeowner. The role reads the progress of its own application, work write-up, loan and complaint cases, and files warranty complaints against the contractor that performed the work.
- A `Contractor` is a firm on the program's approved list. The role submits bids on open solicitations and requests payment for completed construction. It has no access to the logical clock endpoint.
- An `IntakeSpecialist` registers households, certifies income and verifies ownership of record.
- A `RehabSpecialist` prepares the work write-up and its repair lines, solicits and tabulates bids, opens change orders, and may file complaints on the household's behalf.
- An `Inspector` reserves and performs property standards, construction draw and final inspections, and records lead risk assessment clearance.
- A `LoanOfficer` structures and secures the loan, approves and pays draws, posts homeowner payments and closes out construction.
- A `ProgramManager` administers the program year, the approved contractor list, write-up approval, bid awards, historic clearance, change-order decisions, recapture and contractor discipline. A `ProgramManager` may not prepare the work it approves and may not have inspected the draws it pays for.

Role authorization is decided from the endpoint's authorized-role list alone, before any row is loaded, so that a caller in a forbidden role cannot use the response to probe whether a record exists. A caller whose role is not listed for the addressed endpoint receives `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two of the seven roles are entity-backed. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` row; ownership checks on any resource that references an `Applicant` compare the resource's foreign-key field to `X-User-ID` — directly for a `RehabApplication` through its `applicant_id`, and transitively for a `WorkWriteUp`, a `RehabLoan` or a `ComplaintCase` through the application they belong to. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `Contractor` row; ownership checks on a `Bid`, a `DrawRequest` or a `ComplaintCase` compare that resource's `contractor_id` to `X-User-ID`. An entity-backed caller that addresses another party's record receives `ERR_OWNERSHIP_MISMATCH` (HTTP 403), which does not disclose whether the record exists.

The remaining five roles are opaque operator identities. When `X-User-Role` is `IntakeSpecialist`, `RehabSpecialist`, `Inspector`, `LoanOfficer` or `ProgramManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow step demands an audit trail — as `verified_by_user_id` on an `Applicant`, `performed_by_user_id` on a `PropertyInspection`, `prepared_by_user_id` and `approved_by_user_id` on a `WorkWriteUp`, `awarded_by_user_id` on a `BidSolicitation`, `approved_by_user_id` on a `DrawRequest`, and `submitted_by_user_id` on a `ChangeOrder` — but it is never compared to any entity's `id`.

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

### 2.3. Pagination and Sort Order

Collection endpoints accept two pagination query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0. A supplied value outside those ranges is a schema-level violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Every collection is returned in ascending `created_at` order unless a specific endpoint states otherwise. The `meta` object of a collection response carries `limit`, `offset`, `total_count` and `has_more`; `total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true when rows remain beyond the current window.

### 2.4. Collection Filters and Path Resolution

Filters are optional and combine conjunctively — a request that supplies two filters returns only rows matching both.

- Program years accept `fiscal_year`.
- Applicants accept `program_year_id`, `eligibility_status` and `income_category`.
- Rehabilitation applications accept `applicant_id`, `program_year_id`, `awarded_contractor_id`, `workflow_state` and `compliance_posture`.
- Inspections accept `application_id`, `draw_request_id`, `inspection_type` and `status`.
- Work write-ups accept `application_id` and `state`.
- Repair lines accept `write_up_id` and `priority_class`.
- Contractors accept `approved_list_status` and `lead_safe_certified`.
- Bid solicitations accept `application_id`, `write_up_id`, `award_bid_id` and `status`.
- Bids accept `solicitation_id`, `contractor_id` and `status`.
- Loans accept `application_id`, `status` and `structure_type`.
- Draw requests accept `loan_id`, `contractor_id` and `status`.
- Change orders accept `loan_id`, `supersedes_change_order_id` and `status`.
- Complaint cases accept `contractor_id`, `application_id` and `status`.

Single-resource and action endpoints address rows through exactly one path parameter, named for the entity it addresses: `program_year_id`, `applicant_id`, `application_id`, `inspection_id`, `write_up_id`, `work_item_id`, `contractor_id`, `solicitation_id`, `bid_id`, `loan_id`, `draw_request_id`, `change_order_id` or `complaint_id`. Path identifiers are resolved left to right, so when a URL carries more than one identifier a missing parent is reported before a missing child. The 404 error identifier is selected by the entity the unresolved segment addresses: `ERR_PROGRAM_YEAR_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_WRITE_UP_NOT_FOUND`, `ERR_WORK_ITEM_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_DRAW_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND` or `ERR_COMPLAINT_NOT_FOUND`.

Foreign keys supplied in a request body are resolved after path identifiers, in the order the keys appear in the endpoint's input list, and yield the same 404 identifiers. A `bid_id` presented for award that names no existing bid yields `ERR_BID_NOT_FOUND`; a `supersedes_change_order_id` that names no existing change order yields `ERR_CHANGE_ORDER_NOT_FOUND`.

### 2.5. Common Record Properties and Version Semantics

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits.

Twelve of the thirteen resource types — program years, applicants, rehabilitation applications, property inspections, work write-ups, contractors, bid solicitations, bids, rehabilitation loans, draw requests, change orders and complaint cases — additionally carry `updated_at`, in the same timestamp format, and `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row. Whenever a row's stored data changes, whether the change was requested directly or was produced as a side effect of an operation on another row, `updated_at` is refreshed to the current logical instant and `version` is incremented.

The repair-line resource (`WorkItem`) is the single exception: a repair line carries only `id` and `created_at`. It has no `updated_at` field and no `version` field, because a repair line is created and deleted but never edited in place. Adding or deleting a repair line does, however, mutate its parent write-up, so the write-up's `updated_at` and `version` advance.

### 2.6. The Logical Program Clock

The server never reads real wall-clock time for business decisions. It maintains a logical clock that reads exactly `2026-08-01T00:00:00Z` at startup — a mandatory default, with no fall-back to system time — and that can be moved to an explicit UTC instant by a test-driving capability that accepts a single `now` value. Every deadline, warranty window, bid due instant, remedy window and elapsed-month forgiveness computation in this specification is evaluated against that logical clock. The five staff roles may drive the clock; the `Applicant` and `Contractor` roles may not.

### 2.7. Money, Percentages and Rounding Discipline

All monetary amounts are integers denominated in cents. Wherever a monetary computation produces a fractional cent, the result is rounded half up to a whole cent. Where a computation is described as a sequence of steps, the rounding points named in that description are normative: rounding earlier or later than described produces a different answer and is incorrect.

Two quantities are not money and carry their own precision. The area median income percentage `ami_percent` is a number rounded half up to one decimal place. The cumulative change-order exposure `cumulative_delta_pct` is a number rounded half up to two decimal places. The contractor `performance_score` is an integer confined to the closed range from 0 to 100. The per-line `protocol_multiplier` is an exact number formed by adding whole percentage uplifts to 1 and is not rounded.

The program-year ledger performs only addition and subtraction of whole cents; no rounding ever occurs there.

### 2.8. The Two Case Axes and Cascade Propagation

A `RehabApplication` row carries two independent state fields, and both must be satisfied before money moves.

`workflow_state` is the primary case lifecycle axis. Its values are `INTAKE`, `OWNERSHIP_VERIFIED`, `INSPECTED`, `WRITEUP_APPROVED`, `BID_OPEN`, `BID_FAILED`, `AWARDED`, `UNDER_CONSTRUCTION`, `CONSTRUCTION_COMPLETE`, `CLOSED` and `DENIED`. A new application starts at `INTAKE`; `CLOSED` and `DENIED` are terminal. The axis is not strictly forward-only: a new write-up revision moves the case back from `WRITEUP_APPROVED` to `INSPECTED`, and a failed bid can be reopened, cycling `BID_OPEN → BID_FAILED → BID_OPEN`.

`compliance_posture` is the second axis on the same row. Its values are `CLEAR`, `LEAD_HOLD`, `HISTORIC_HOLD`, `DUAL_HOLD`, `CLEARED_WITH_PROTOCOL` and `ADVERSE_EFFECT_BLOCKED`. `ADVERSE_EFFECT_BLOCKED` is terminal on this axis. This axis moves independently of `workflow_state`, and it can regress: approving a change order that disturbs painted surfaces on a pre-1978 dwelling returns the posture from `CLEARED_WITH_PROTOCOL` or `CLEAR` to `LEAD_HOLD`.

Several operations mutate more than one row. When they do, every affected row's `updated_at` and `version` advance, and the cascade is applied in full within the same request — the consistency model is immediate, never deferred. The three multi-row cascades that matter most are: recording a lien, which moves the loan, the application and the program-year ledger; paying a draw, which moves the draw, the loan, the application when the loan becomes fully disbursed, and the program-year ledger; and suspending a contractor, which moves the contractor, its live bids, the affected solicitations and the applications behind those solicitations. Each is specified in full in §3.

### 2.9. Program-Year Ledger Conservation

A program year holds four money figures supplied at creation and four derived figures maintained continuously. The derived figures are defined as follows.

`committed_amount_cents` is the sum, over every loan of that program year whose `status` is `LIEN_RECORDED`, `DISBURSING` or `FULLY_DISBURSED`, of that loan's `principal_cents` less its `disbursed_cents`. `disbursed_amount_cents` is the sum of `disbursed_cents` over every loan of the program year, regardless of status. `program_income_balance_cents` is the cumulative amount recaptured or repaid back into the program year. `uncommitted_amount_cents` is `allocation_budget_cents` plus `program_income_balance_cents`, less `committed_amount_cents`, less `disbursed_amount_cents`.

The following identity must hold after every write: `allocation_budget_cents` plus `program_income_balance_cents` equals the sum of `uncommitted_amount_cents`, `committed_amount_cents` and `disbursed_amount_cents`. Recording a lien moves the loan's principal from uncommitted to committed. Paying a draw moves that draw's net payment from committed to disbursed. Approving a change order shifts the principal delta between uncommitted and committed. Closing out a loan that was only partly disbursed releases the difference between principal and disbursed back to uncommitted. A recapture or a homeowner payment raises `program_income_balance_cents`, and therefore raises `uncommitted_amount_cents` by the same amount.

No operation may leave `uncommitted_amount_cents` negative. When a commitment would exceed the uncommitted balance, the request is refused with `ERR_ALLOCATION_INSUFFICIENT` (HTTP 409) and nothing is written.

### 2.10. Segregation of Duties and Optimistic Concurrency Control

**Segregation of duties.** The program enforces two four-eyes pairings, and both are checked against `X-User-ID`. On write-up approval, `X-User-ID` must differ from the write-up's `prepared_by_user_id`. On draw approval, `X-User-ID` must differ from the `performed_by_user_id` of the construction inspection that passed that draw. A violation of either pairing yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

**Optimistic concurrency control.** Two creation endpoints mutate a parent row that the client must have observed first, and both therefore require a version field as a non-optional part of the request body.

A `POST /rehab/write-ups` request must carry `expected_application_version` matching the target `RehabApplication`'s current `version`. If any writer has advanced the application's `version` since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) and no write-up is opened. This matters because a new write-up legitimately supersedes the application's prior approved write-up and regresses `workflow_state` from `WRITEUP_APPROVED` to `INSPECTED`; a create built on an older observed version would silently discard scope its author never saw.

A `POST /rehab/change-orders` request must carry `expected_loan_version` matching the target `RehabLoan`'s current `version`. If the loan's `version` has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because a change order may supersede an earlier approved change order and moves `approved_project_cost_cents`; a create built on a stale view of the loan would compute `cumulative_delta_pct` from an outdated contract amount.

No other endpoint accepts a version field, and no other endpoint performs a version comparison.

### 2.11. Rejection Precedence

When a request violates more than one rule, exactly one error is returned: the violation with the lowest priority number below. Evaluation short-circuits — once a rule is violated, no later rule is evaluated, and no partial write occurs.

1. The `X-User-Role` header is present and names one of the seven roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. The caller's role appears in the addressed endpoint's authorized-role list — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint.
3. An entity-backed caller addresses only its own rows — otherwise `ERR_OWNERSHIP_MISMATCH` (403). This scoping applies to five operations: reading one rehabilitation application, reading one loan, submitting a bid, creating a draw request, and reading one complaint case.
4. Every identifier in the request path resolves to an existing row — otherwise the entity-specific 404 identifier listed in §2.4. Applies to every endpoint that has a path parameter.
5. Every foreign key in the request body resolves to an existing row — otherwise the entity-specific 404 identifier. Applies to every endpoint that carries foreign keys in its body.
6. Required fields are present, types and enum members are valid, money and count fields are non-negative, and date ranges are ordered — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint. This covers, among others, an inspection whose `scheduled_end_at` is not strictly after its `scheduled_start_at`, a bid whose `proposed_end_date` is earlier than its `proposed_start_date`, an amortizing loan whose `term_months` is below 1, and a `household_size` outside the range 1 through 8.
7. Where the endpoint requires it, `expected_application_version` or `expected_loan_version` equals the parent's current `version` — otherwise `ERR_STALE_VERSION` (412). Applies to opening a write-up revision and to submitting a change order.
8. The addressed row is in a state from which the requested transition is defined — otherwise `ERR_INVALID_STATE` (409). Applies to every state-transition endpoint. It covers repeat triggers on terminal rows, editing an applicant after income verification, adding or deleting repair lines on a write-up that is neither `DRAFT` nor `REVISION_REQUESTED`, structuring a loan before the solicitation is awarded, structuring a second loan for one application, paying a draw whose loan is neither `LIEN_RECORDED` nor `DISBURSING`, closing out while retainage is still held, and resolving a complaint as escalated before its remedy deadline. Draw approval is deliberately carved out of this generic rule; its state gate is the more specific cross-entity rule at priority 13.
9. The referenced applicant has `eligibility_status` equal to `INCOME_VERIFIED` — otherwise `ERR_INCOME_NOT_VERIFIED` (409). Applies to intaking a rehabilitation application.
10. The rehabilitation application has `ownership_verification_status` equal to `VERIFIED` — otherwise `ERR_OWNERSHIP_NOT_VERIFIED` (409). Applies to two operations: reserving an inspection window and opening a work write-up.
11. When the application requires the lead protocol, its `compliance_posture` is neither `LEAD_HOLD` nor `DUAL_HOLD` — otherwise `ERR_LEAD_CLEARANCE_REQUIRED` (409). Applies to two operations: recording the lien and approving a draw.
12. When the application requires historic review, its `compliance_posture` is none of `HISTORIC_HOLD`, `DUAL_HOLD` or `ADVERSE_EFFECT_BLOCKED` — otherwise `ERR_HISTORIC_CLEARANCE_REQUIRED` (409). Applies to recording the lien.
13. The addressed draw is in `INSPECTION_PASSED` — otherwise `ERR_DRAW_INSPECTION_NOT_PASSED` (409). Applies to approving a draw. A draw still in `SUBMITTED` (never inspected) or in `INSPECTION_FAILED` returns this identifier rather than the generic invalid-state identifier, because the gate is the state of the sibling inspection row rather than the draw itself.
14. The referenced loan has `lien_recorded_at` set and `status` in `LIEN_RECORDED` or `DISBURSING` — otherwise `ERR_LIEN_NOT_RECORDED` (409). Applies to two operations: creating a draw request and submitting a change order.
15. The approving user differs from the user who performed the preceding step — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to two operations: approving a write-up and approving a draw.
16. The requested inspection window does not overlap another `SCHEDULED` or `COMPLETED` inspection on the same application — otherwise `ERR_INSPECTION_WINDOW_CONFLICT` (409). Applies to reserving an inspection window.
17. The logical clock is strictly before the solicitation's `bid_due_at` — otherwise `ERR_BID_WINDOW_CLOSED` (409). Applies to submitting a bid.
18. Awarding leaves the contractor within its concurrent-award capacity — otherwise `ERR_CONTRACTOR_CAPACITY_CONFLICT` (409). Applies to awarding a solicitation.
19. The logical clock is at or before the application's `warranty_expires_at` — otherwise `ERR_WARRANTY_EXPIRED` (409). Applies to filing a complaint.
20. The awarded bid amount does not exceed the program year's `max_loan_amount_cents` — otherwise `ERR_LOAN_LIMIT_EXCEEDED` (422). Applies to structuring a loan.
21. `uncommitted_amount_cents` is at least the amount about to be committed — otherwise `ERR_ALLOCATION_INSUFFICIENT` (409). Applies to two operations: recording the lien and approving a change order.
22. The requested draw amount does not exceed the loan's `approved_project_cost_cents` less its `contract_earned_cents` — otherwise `ERR_DRAW_EXCEEDS_CONTRACT_BALANCE` (422). Applies to approving a draw.
23. `cumulative_delta_pct` does not exceed the cumulative change-order limit — otherwise `ERR_CHANGE_ORDER_EXCEEDS_LIMIT` (422). Applies to approving a change order.
24. The contractor has no live bid already on that solicitation — otherwise `ERR_DUPLICATE_BID` (409). Applies to submitting a bid.
25. The solicitation's `bid_count` is at least its `min_bids_required` — otherwise `ERR_INSUFFICIENT_BIDS` (409). Applies to tabulating a solicitation.
26. The bid selected for award has `status` equal to `RESPONSIVE` and belongs to the addressed solicitation — otherwise `ERR_BID_NOT_RESPONSIVE` (422). Applies to awarding a solicitation.
27. The winning bid's contractor has `approved_list_status` equal to `APPROVED` — otherwise `ERR_CONTRACTOR_NOT_APPROVED` (422). Applies to awarding a solicitation.
28. When the application requires the lead protocol, the winning bid's contractor has `lead_safe_certified` true — otherwise `ERR_CONTRACTOR_NOT_LEAD_CERTIFIED` (422). Applies to awarding a solicitation.
29. The write-up has `work_item_count` of at least 1 — otherwise `ERR_WRITE_UP_EMPTY` (422). Applies to submitting a write-up.
30. The write-up has `priority_repair_total_cents` greater than 0 — otherwise `ERR_PRIORITY_REPAIRS_NOT_ADDRESSED` (422). Applies to two operations: submitting a write-up and opening a bid solicitation.
31. The referenced applicant has `income_category` in `EXTREMELY_LOW`, `VERY_LOW` or `LOW` — otherwise `ERR_APPLICANT_OVER_INCOME` (422). Applies to intaking a rehabilitation application.

Note the deliberate ordering of the three fiscal gates on loan structuring and lien recording: the per-household maximum (priority 20) is tested when the loan is structured, while allocation sufficiency (priority 21) is tested only when the lien is recorded, so a loan may exist as a structured note that the allocation cannot yet support. Note also that the two 404 layers precede schema validation, so a request with both a bad identifier and a malformed body reports the missing row.

---

## 3. Business Logic & Workflows

### 3.1. Opening a Program Year and Certifying Household Income

A `ProgramManager` opens the fiscal cycle by creating a program year. The creation payload carries a `fiscal_year` label, which must fall between 2020 and 2035 inclusive and must be unique across program years; the HUD area median family income for a four-person household as `ami_median_income_cents`; the hard per-household rehabilitation assistance cap as `max_loan_amount_cents`; and the entitlement money available to the rehabilitation activity as `allocation_budget_cents`. All three money figures must be greater than zero. At creation, `committed_amount_cents`, `disbursed_amount_cents` and `program_income_balance_cents` are all initialised to zero, and `uncommitted_amount_cents` therefore equals `allocation_budget_cents`.

Household registration is the `IntakeSpecialist`'s first act. The payload names the governing `program_year_id`, the head-of-household legal name as `full_name`, a contact `email` that must be unique across households, the `household_size` (from 1 to 8 persons), and the `income_calc_method` to be used — either `PART_5_ANNUAL` or `IRS_1040_ADJUSTED`. Income sources are declared as `wage_income_cents` for annual gross wage and self-employment income, `benefit_income_cents` for annual social security, pension and public assistance income, `actual_asset_income_cents` for income actually received from household assets, and `household_assets_cents` for the total cash value of those assets. Two further declarations affect only one of the two methodologies: `dependents_count`, the number of IRS dependents claimed, and `elderly_household`, true when the head of household is 62 or older. Each of `benefit_income_cents`, `actual_asset_income_cents`, `household_assets_cents` and `dependents_count` defaults to zero when omitted, and `elderly_household` defaults to false. A newly registered household has `eligibility_status` of `APPLIED`, and its `annual_income_cents`, `income_limit_cents`, `ami_percent` and `income_category` remain unset until certification runs.

Declared figures can be corrected — and the methodology switched — for as long as the household is still `APPLIED`. Correction accepts `income_calc_method`, `wage_income_cents`, `benefit_income_cents`, `actual_asset_income_cents`, `household_assets_cents`, `household_size`, `dependents_count` and `elderly_household`, each optional, and advances the household's `version` by one. Once income has been certified, the household record is frozen and a correction attempt is refused with `ERR_INVALID_STATE`.

**Income certification.** When an `IntakeSpecialist` certifies a household, the system first derives the household-adjusted income limit. `income_limit_cents` is the program year's `ami_median_income_cents` multiplied by the adjustment factor for the household size, rounded half up to whole cents. The factors are 0.70 for a one-person household, 0.80 for two persons, 0.90 for three, 1.00 for four, 1.08 for five, 1.16 for six, 1.24 for seven, and 1.32 for eight or more persons; a household size above eight uses the eight-person factor.

Annual income is then determined by the household's declared methodology, and the two methodologies genuinely disagree on the same household record.

- Under `PART_5_ANNUAL`, gross income from all sources counts, and asset income is imputed. When `household_assets_cents` is strictly greater than five thousand dollars — that is, strictly greater than 500,000 cents — the imputed figure is `household_assets_cents` multiplied by the passbook savings rate of four tenths of one percent, rounded half up to whole cents, and the asset income used is the greater of that imputed figure and `actual_asset_income_cents`. When household assets are at or below the five-thousand-dollar floor, no imputation occurs and the asset income used is `actual_asset_income_cents` exactly. `annual_income_cents` is then the sum of `wage_income_cents`, `benefit_income_cents` and the asset income used. No deductions are applied under this methodology.
- Under `IRS_1040_ADJUSTED`, `benefit_income_cents` is excluded entirely, asset income is never imputed and only `actual_asset_income_cents` counts, and deductions are subtracted. The deduction total is four hundred and eighty dollars — 48,000 cents — for each dependent claimed in `dependents_count`, plus a further four hundred dollars — 40,000 cents — when `elderly_household` is true. `annual_income_cents` is `wage_income_cents` plus `actual_asset_income_cents` less that deduction total, and is floored at zero, so deductions can never drive the certified income negative.

With both figures in hand, `ami_percent` is one hundred multiplied by `annual_income_cents` divided by `income_limit_cents`, rounded half up to one decimal place. The band is read off that rounded percentage: at or below 30.0 percent the `income_category` is `EXTREMELY_LOW`; above 30.0 and at or below 50.0 it is `VERY_LOW`; above 50.0 and at or below 80.0 it is `LOW`; above 80.0 it is `OVER_INCOME`.

Certification always succeeds and always answers 200 OK. A household in one of the three assisted bands moves `APPLIED → INCOME_VERIFIED`; a household above the top band moves `APPLIED → INELIGIBLE`, which is terminal on that axis. In either outcome the four computed figures are stored, `verified_by_user_id` is set to the acting `X-User-ID`, and the household's `version` advances by one. Over-income households are not refused at certification time — they are recorded and then blocked at application intake with `ERR_APPLICANT_OVER_INCOME`.

### 3.2. Intake, Ownership of Record and the Property Standards Inspection

Intake of a rehabilitation case requires a household that has already been certified. The payload names the `applicant_id` and describes the dwelling: `address_line1`, `city`, a two-letter `state_code`, the `year_built` (between 1850 and 2026 inclusive), the county `assessed_value_cents`, the `senior_lien_balance_cents` outstanding on mortgages senior to the program lien (defaulting to zero), a `historic_district` flag (defaulting to false), the `occupancy_type` — either `OWNER_OCCUPIED_SINGLE` or `OWNER_OCCUPIED_DUPLEX` — and the `ownership_doc_type` offered as proof of ownership, one of `WARRANTY_DEED`, `QUITCLAIM_DEED`, `LIFE_ESTATE` or `CONTRACT_FOR_DEED`. A household still in `APPLIED` is refused with `ERR_INCOME_NOT_VERIFIED`; a household certified `OVER_INCOME` is refused with `ERR_APPLICANT_OVER_INCOME`.

Intake copies the household's `program_year_id` onto the case verbatim, and that copy is never editable afterwards: the income limits and the allocation that govern the case are fixed at intake. Two compliance triggers are computed at the same moment. `lead_review_required` is true when `year_built` is earlier than 1978 — pre-1978 target housing — and false otherwise. `historic_review_required` is true exactly when `historic_district` is true. The case opens with `workflow_state` of `INTAKE`, `ownership_verification_status` of `PENDING`, `lead_hazard_detected` false, `lead_hazard_control_method` of `NONE`, `initial_deficiency_count` of zero, and `awarded_contractor_id`, `deed_recorded_date`, `shpo_review_outcome` and `warranty_expires_at` all unset.

**Ownership of record.** The `IntakeSpecialist` records the title examination by supplying the recording date of the instrument as `deed_recorded_date` and a `title_report_clear` boolean. Two eligible instruments exist: a warranty deed and a life estate. When `title_report_clear` is true and `ownership_doc_type` is either `WARRANTY_DEED` or `LIFE_ESTATE`, `ownership_verification_status` becomes `VERIFIED`, the supplied recording date is stored, and the case advances `INTAKE → OWNERSHIP_VERIFIED`. When `title_report_clear` is false, or when the instrument is a `QUITCLAIM_DEED` or a `CONTRACT_FOR_DEED`, `ownership_verification_status` becomes `REJECTED` and the case moves `INTAKE → DENIED`, which is terminal. Either outcome advances the case `version` by one and answers 200 OK.

**Reserving an inspection window.** An `Inspector` reserves a site visit against a case whose ownership is verified; a case whose `ownership_verification_status` is not `VERIFIED` is refused with `ERR_OWNERSHIP_NOT_VERIFIED`. The reservation names the `application_id`, the `inspection_type` — one of `INITIAL_STANDARDS`, `DRAW` or `FINAL` — and the window as `scheduled_start_at` (inclusive) and `scheduled_end_at` (exclusive, and strictly after the start). A `DRAW` visit must also name the `draw_request_id` it inspects; for the other two types that reference must be absent. Reservation sets `performed_by_user_id` to the acting `X-User-ID` and opens the row in `SCHEDULED` with `deficiency_count` of zero, `lead_hazard_present` false, and `result` and `xrf_reading_mg_cm2` unset.

Windows on the same dwelling may not collide. Each reserved window is treated as a half-open interval that includes its start instant and excludes its end instant, and the new window is compared against every `SCHEDULED` and `COMPLETED` inspection already on the same case. A window that begins exactly when an existing window ends is accepted; any interior overlap is refused with `ERR_INSPECTION_WINDOW_CONFLICT`.

**Recording the finding.** Only the inspector who reserved the visit may record its result: the acting `X-User-ID` must equal the row's `performed_by_user_id`. Recording supplies the `result` (`PASS` or `FAIL`), the `deficiency_count` of property-standards deficiencies observed, and optionally the highest XRF lead reading of the visit as `xrf_reading_mg_cm2`. The row moves `SCHEDULED → COMPLETED`, stores all three values, sets `lead_hazard_present` true exactly when the recorded reading is at or above the action level of 1.00 milligrams per square centimetre, and advances its `version` by one.

An `INITIAL_STANDARDS` finding drives the case forward. When at least one deficiency was recorded, `initial_deficiency_count` is set to the recorded count and the case advances `OWNERSHIP_VERIFIED → INSPECTED`. When zero deficiencies were recorded, the dwelling already meets property standards and no rehabilitation need exists: `initial_deficiency_count` is set to zero and the case moves `OWNERSHIP_VERIFIED → DENIED`. In either branch the case `version` advances by one. Independently of the deficiency branch, an `INITIAL_STANDARDS` visit whose reading is at or above 1.00 milligrams per square centimetre sets `lead_hazard_detected` true on the case.

A `DRAW` finding drives the linked draw request instead, and a `FINAL` visit records the closing condition of the dwelling without moving either axis. Both are covered in §3.7.

### 3.3. Scoping the Work: Write-Ups, Repair Lines and the Revision Cycle

A `RehabSpecialist` scopes the rehabilitation by opening a work write-up against the case. The opening payload names the `application_id`, the `expected_application_version` the specialist last observed, and, when the write-up is not the first for that case, a `revision_reason` explaining why the scope is being reopened. Ownership must already be verified, or the request is refused with `ERR_OWNERSHIP_NOT_VERIFIED`. A first write-up opens with `revision_number` of 1 and no revision reason; every later write-up for the same case takes the prior write-up's `revision_number` plus one. Every write-up opens in `DRAFT` with `prepared_by_user_id` set to the acting `X-User-ID`, `work_item_count` of zero, and `base_estimate_cents`, `contingency_cents`, `total_estimate_cents` and `priority_repair_total_cents` all zero, and `approved_by_user_id` unset.

Opening a later revision is a two-row operation with a deliberate regression. The case's prior write-up in `APPROVED` moves `APPROVED → SUPERSEDED`, the new write-up is created in `DRAFT`, and the case itself moves `WRITEUP_APPROVED → INSPECTED` so that the newly widened scope must be approved again before it can be bid. Both rows and the case advance their `version` by one. Because that regression discards approved scope, the stale-version guard described in §2.10 protects it: an `expected_application_version` that does not equal the case's current `version` yields `ERR_STALE_VERSION` and nothing is written.

**Repair lines.** Each repair line belongs to a write-up through its `write_up_id` and carries a `description` of the individual repair scope, a `category` naming the construction trade — `ROOF`, `ELECTRICAL`, `PLUMBING`, `HVAC`, `LEAD_HAZARD_CONTROL`, `ACCESSIBILITY`, `WINDOWS` or `STRUCTURAL` — and a `priority_class` giving the program's priority classification: `HEALTH_SAFETY`, `CODE`, `INCIPIENT` or `GENERAL_PROPERTY_IMPROVEMENT`. The unloaded trade estimate is `estimated_cost_cents` and must be greater than zero. Two compliance flags load the line: `is_lead_hazard_reduction`, true when the line performs lead hazard reduction or disturbs painted surfaces, and `is_historic_sensitive`, true when the line touches character-defining historic features. Both default to false. Lines may be added and removed only while the parent write-up is in `DRAFT` or `REVISION_REQUESTED`; attempting either on a write-up in any other state is refused with `ERR_INVALID_STATE`. Removal addresses the line by its `work_item_id` and answers 204 with no body.

**Cost estimation.** Compliance work practices cost real money, and the program loads them onto the line rather than onto the total. Each line's `protocol_multiplier` starts at 1 and is increased **additively** by the uplifts the line triggers: fifteen percent when `is_lead_hazard_reduction` is true, and twelve percent when `is_historic_sensitive` is true. A line that is both lead-reducing and historic-sensitive therefore carries a multiplier of 1.27 — both surcharges added, never multiplied together. The line's `line_total_cents` is `estimated_cost_cents` multiplied by that multiplier, rounded half up to whole cents.

The order of rounding in the write-up roll-up is normative. Each line is rounded first, as just described. `base_estimate_cents` is then the sum of the already-rounded `line_total_cents` of every line on the write-up. `contingency_cents` is `base_estimate_cents` multiplied by a flat ten percent contingency, rounded half up to whole cents. `total_estimate_cents` is `base_estimate_cents` plus `contingency_cents`. Summing unrounded products before rounding is not equivalent and is incorrect. `priority_repair_total_cents` is the sum of `line_total_cents` restricted to lines whose `priority_class` is `HEALTH_SAFETY` or `CODE`, and `work_item_count` is simply the number of lines on the write-up. All five figures are recomputed whenever a line is added or removed, and again when the write-up is submitted, and each recomputation advances the write-up's `version` by one.

**Review cycle.** Submitting the scope freezes its estimate and moves the write-up `DRAFT → SUBMITTED`. Submission requires at least one repair line — an empty scope is refused with `ERR_WRITE_UP_EMPTY` — and requires that the scope address at least one health-and-safety or code repair, so a `priority_repair_total_cents` of zero is refused with `ERR_PRIORITY_REPAIRS_NOT_ADDRESSED`. A `ProgramManager` reviewing the submitted scope may return it for correction, supplying a `revision_note`; the write-up then moves `SUBMITTED → REVISION_REQUESTED`, the note is recorded on the write-up's audit trail, and its `version` advances. The specialist may edit repair lines again and resubmit, moving `REVISION_REQUESTED → SUBMITTED` under exactly the same two gates and recomputing the same five estimate figures. That loop may repeat without bound on the same row.

Approval by a `ProgramManager` moves the write-up `SUBMITTED → APPROVED`, stamps `approved_by_user_id` with the acting `X-User-ID`, and drives the case `INSPECTED → WRITEUP_APPROVED`; both rows advance their `version` by one. Approval carries two additional gates beyond the write-up's own state: the case must currently be in `INSPECTED`, and the approver must not be the preparer — an `X-User-ID` equal to `prepared_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`.

### 3.4. Compliance Protocols: Lead-Based Paint and Historic Review

The compliance posture is computed the moment the case is intaken, from the two triggers described in §3.2. A pre-1978 dwelling inside a designated historic district opens at `DUAL_HOLD`. A pre-1978 dwelling outside such a district opens at `LEAD_HOLD`. A dwelling built in 1978 or later inside a historic district opens at `HISTORIC_HOLD`. A dwelling that triggers neither review opens at `CLEAR`.

**Lead clearance** is recorded by an `Inspector` and reports two things: `risk_assessment_completed`, which must be true for the clearance to be accepted, and the `hazard_control_method` chosen, which is stored on the case as `lead_hazard_control_method` and is one of `NONE`, `INTERIM_CONTROLS` or `ABATEMENT`. From `DUAL_HOLD`, a completed risk assessment moves the posture `DUAL_HOLD → HISTORIC_HOLD`, leaving the historic axis outstanding; this path additionally requires that the case's `workflow_state` be one of `INSPECTED`, `WRITEUP_APPROVED`, `BID_OPEN`, `BID_FAILED` or `AWARDED`. From `LEAD_HOLD`, a completed risk assessment moves the posture `LEAD_HOLD → CLEARED_WITH_PROTOCOL`; this path requires only the posture and the completed assessment, and places no constraint on `workflow_state`. Both paths store the supplied control method and advance the case `version` by one.

**Historic clearance** is recorded by a `ProgramManager` and reports the State Historic Preservation Office determination as `shpo_review_outcome`, one of `NO_ADVERSE_EFFECT`, `CONDITIONS` or `ADVERSE_EFFECT`. A determination of either `NO_ADVERSE_EFFECT` or `CONDITIONS` clears the historic axis, and where the posture lands depends on whether the lead axis is still outstanding. From `DUAL_HOLD` the posture moves `DUAL_HOLD → LEAD_HOLD`. From `HISTORIC_HOLD` on a case whose `lead_review_required` is true, the posture moves `HISTORIC_HOLD → CLEARED_WITH_PROTOCOL`. From `HISTORIC_HOLD` on a case whose `lead_review_required` is false, the posture moves `HISTORIC_HOLD → CLEAR`. Every one of those three paths stores the supplied determination and advances the case `version` by one.

A determination of `ADVERSE_EFFECT` is fatal to the case's financing. From either `HISTORIC_HOLD` or `DUAL_HOLD`, that outcome is stored and the posture moves to `ADVERSE_EFFECT_BLOCKED`, which is terminal on the compliance axis: lien recording can never proceed from there, no matter what else happens to the case. The case `version` advances by one.

**What the posture gates.** Lien recording tests both axes. When the case requires the lead protocol and the posture is `LEAD_HOLD` or `DUAL_HOLD`, recording is refused with `ERR_LEAD_CLEARANCE_REQUIRED`. When the case requires historic review and the posture is `HISTORIC_HOLD`, `DUAL_HOLD` or `ADVERSE_EFFECT_BLOCKED`, recording is refused with `ERR_HISTORIC_CLEARANCE_REQUIRED`. Because the lead gate is evaluated ahead of the historic gate, a case sitting at `DUAL_HOLD` reports the lead clearance requirement. Recording therefore proceeds only from a posture of `CLEAR` or `CLEARED_WITH_PROTOCOL`. Draw approval tests the lead axis only, with the same lead clearance identifier, and likewise proceeds only from `CLEAR` or `CLEARED_WITH_PROTOCOL`.

**The posture can regress.** Approving a change order whose `affects_lead_hazard_work` is true on a case whose `lead_review_required` is true re-opens the lead protocol: the posture returns from `CLEARED_WITH_PROTOCOL` to `LEAD_HOLD`, or from `CLEAR` to `LEAD_HOLD`, `lead_hazard_control_method` is reset to `NONE`, and the case `version` advances by one. Every further draw approval on that case is then refused with `ERR_LEAD_CLEARANCE_REQUIRED` until a new lead clearance is recorded. This is the intended serialization point between expanding lead-disturbing scope and paying for it.

### 3.5. Soliciting, Tabulating and Awarding Bids

A `ProgramManager` maintains the approved contractor list. Adding a firm records its `legal_name`, its state `license_number` (unique across contractors), the expiration instant of its general liability insurance as `insurance_expires_on`, and two qualification flags: `lead_safe_certified`, true when the firm holds an EPA Renovation, Repair and Painting lead-safe certification, and `historic_qualified`, true when the firm is qualified for historic rehabilitation work. Both flags default to false. A new firm opens with `approved_list_status` of `APPROVED` and `performance_score` of 100, and with `open_complaint_count`, `sanction_count`, `on_time_completion_count` and `active_award_count` all zero. `active_award_count` is the number of awarded solicitations whose winning bid belongs to that firm and whose case is currently in `AWARDED` or `UNDER_CONSTRUCTION`.

**Opening the solicitation.** A `RehabSpecialist` solicits bids against an approved scope. The payload names the `application_id`, the `write_up_id` of the approved scope, the `bid_due_at` cutoff instant, and `min_bids_required`, the minimum number of bids that must be on file before tabulation may run — an integer from 1 to 5 that defaults to 2. The referenced write-up must be in `APPROVED` and must belong to the addressed case, and its `priority_repair_total_cents` must be greater than zero, otherwise the request is refused with `ERR_PRIORITY_REPAIRS_NOT_ADDRESSED`. Opening the solicitation snapshots `independent_cost_estimate_cents` from the write-up's `total_estimate_cents` — a frozen figure that later changes to the write-up cannot move — computes the responsiveness window described below, opens the solicitation in `OPEN` with `bid_count`, `responsive_bid_count` and `reopen_count` all zero and `award_bid_id` and `awarded_by_user_id` unset, and drives the case `WRITEUP_APPROVED → BID_OPEN`, advancing the case `version` by one.

The responsiveness window brackets the independent cost estimate. `responsive_ceiling_cents` is the independent cost estimate increased by ten percent — the estimate multiplied by 1.10 — rounded half up to whole cents. `responsive_floor_cents` is the independent cost estimate reduced by twenty-five percent — the estimate multiplied by 0.75 — rounded half up to whole cents. Both bounds are inclusive: a bid exactly at the ceiling or exactly at the floor is responsive.

**Submitting a bid.** A `Contractor` submits a sealed bid naming the `solicitation_id`, its own `contractor_id`, the lump-sum `amount_cents` (greater than zero), and its proposed construction window as `proposed_start_date` and `proposed_end_date`, both inclusive, with the end date not earlier than the start date. The submitting firm's `contractor_id` must equal the acting `X-User-ID`, or the request is refused with `ERR_OWNERSHIP_MISMATCH`. The bid is accepted only while the logical clock is strictly before the solicitation's `bid_due_at`; a bid arriving exactly at the due instant is late and is refused with `ERR_BID_WINDOW_CLOSED`. One live bid per firm per solicitation is allowed: a firm that already holds a bid on that solicitation in `SUBMITTED`, `RESPONSIVE`, `NON_RESPONSIVE` or `AWARDED` is refused with `ERR_DUPLICATE_BID`, while a bid previously rejected by a reopen, or withdrawn by the program, does not block a fresh submission. Acceptance stamps `submitted_at` from the logical clock, opens the bid in `SUBMITTED` with `non_responsive_reason` and `rank` unset, increases the parent solicitation's `bid_count`, and advances the solicitation's `version` by one.

**Tabulation.** A `RehabSpecialist` tabulates once enough bids are on file. Tabulation requires that the solicitation's `bid_count` be at least its `min_bids_required`; otherwise the request is refused with `ERR_INSUFFICIENT_BIDS` and the solicitation stays `OPEN` so that further bids can still arrive. Only bids currently in `SUBMITTED` are classified; bids in `WITHDRAWN_BY_PROGRAM` or `REJECTED` are excluded from the input set entirely. Each classified bid is tested against four conditions in a fixed order, and the first condition that fails both makes the bid non-responsive and fixes its `non_responsive_reason`:

1. When `amount_cents` is strictly greater than `responsive_ceiling_cents`, the reason is `OVER_CEILING`.
2. Otherwise, when `amount_cents` is strictly less than `responsive_floor_cents`, the reason is `UNDER_FLOOR`.
3. Otherwise, when the bidding firm's `approved_list_status` is anything other than `APPROVED`, the reason is `CONTRACTOR_NOT_APPROVED`.
4. Otherwise, when the case's `lead_review_required` is true and the bidding firm's `lead_safe_certified` is false, the reason is `NOT_LEAD_CERTIFIED`.

A bid that survives all four moves `SUBMITTED → RESPONSIVE`; a bid that fails one moves `SUBMITTED → NON_RESPONSIVE`. Responsive bids are then ranked, with `rank` starting at 1: primarily by `amount_cents` ascending; where two bids carry the same amount, by the bidding firm's `performance_score` descending; and where those also tie, by the bid's `created_at` ascending. Non-responsive bids carry no rank. Tabulation recomputes `bid_count` — the number of bids of that solicitation whose status is `SUBMITTED`, `RESPONSIVE` or `NON_RESPONSIVE` — and `responsive_bid_count`, the number in `RESPONSIVE` or `AWARDED`. Each classified bid and the solicitation advance their `version` by one.

The outcome of tabulation branches on how many bids survived. When at least one bid is responsive, the solicitation moves `OPEN → TABULATED` and the case stays in `BID_OPEN`. When every received bid is non-responsive, the solicitation moves `OPEN → FAILED` and drives the case `BID_OPEN → BID_FAILED`. Note the deliberate distinction between that second branch and an insufficient-bid refusal: too few bids leaves the solicitation open and writes nothing, whereas enough bids that all miss the window fails the solicitation.

**Reopening a failed solicitation.** A `ProgramManager` may rebid on the same solicitation row by supplying a `new_bid_due_at` that is strictly after the logical clock. The solicitation moves `FAILED → OPEN`, its `bid_due_at` is replaced by the supplied instant, `reopen_count` increases by one, every bid of that solicitation in `RESPONSIVE` or `NON_RESPONSIVE` moves to `REJECTED`, both bid counts reset to zero, and the case moves `BID_FAILED → BID_OPEN`. Every touched row advances its `version` by one.

**Award.** A `ProgramManager` awards by naming the winning `bid_id`. Award proceeds only from a solicitation in `TABULATED`. The named bid must be in `RESPONSIVE` and must belong to the addressed solicitation, otherwise the request is refused with `ERR_BID_NOT_RESPONSIVE` — a non-responsive, rejected or program-withdrawn bid can never be awarded. The winning firm's `approved_list_status` must still be `APPROVED` at award time, so a firm demoted to `PROBATION`, `SUSPENDED` or `REMOVED` after bidding is refused with `ERR_CONTRACTOR_NOT_APPROVED`. On a case whose `lead_review_required` is true, the winning firm's `lead_safe_certified` must be true, or the award is refused with `ERR_CONTRACTOR_NOT_LEAD_CERTIFIED`; on a case built in 1978 or later that requirement does not exist.

Crew capacity is the last award gate. The program allows a firm at most one live award at a time, and it insists on a three-day crew turnover buffer between jobs. The winning bid's construction window, running inclusively from `proposed_start_date` to `proposed_end_date`, is inflated by three days at each end, and the inflated window is compared against the construction window of every other bid of the same firm that is already in `AWARDED` and whose case is not yet `CLOSED`. Windows that merely touch after inflation conflict. If any such overlap exists, the award is refused with `ERR_CONTRACTOR_CAPACITY_CONFLICT`.

A successful award is a five-row operation. The solicitation moves `TABULATED → AWARDED` with `award_bid_id` set to the winning bid and `awarded_by_user_id` set to the acting `X-User-ID`. The winning bid moves `RESPONSIVE → AWARDED`. Every other bid of that solicitation still in `RESPONSIVE` or `NON_RESPONSIVE` moves to `REJECTED`. The case records `awarded_contractor_id` as the winning firm and moves `BID_OPEN → AWARDED`. The winning firm's `active_award_count` is recomputed. Every touched row advances its `version` by one.

### 3.6. Structuring the Note and Recording the Lien

A `LoanOfficer` structures the assistance once the contract is awarded. The payload names the `application_id` and the `structure_type` — `DEFERRED`, `FORGIVABLE` or `AMORTIZING` — together with the note's terms. `interest_rate_bps` is the annual nominal rate in basis points and defaults to zero; it must be zero for a `DEFERRED` or `FORGIVABLE` note. `term_months` is the amortization term and defaults to zero; it must be at least 1 for an `AMORTIZING` note and zero for the other two. `forgiveness_term_months` is the forgiveness period and defaults to zero; it must be greater than zero for a `DEFERRED` or `FORGIVABLE` note and zero for an `AMORTIZING` note. A term that contradicts the chosen structure is a schema-level violation and is refused with `ERR_INVALID_REQUEST`. Structuring a loan before the solicitation reaches `AWARDED`, or structuring a second loan for the same case, is refused with `ERR_INVALID_STATE`.

Structuring snapshots `awarded_bid_amount_cents` from the winning bid's `amount_cents`, and `approved_project_cost_cents` opens at that same figure. The awarded amount is first tested against the program year's per-household maximum: an awarded bid greater than `max_loan_amount_cents` cannot be financed at all and is refused with `ERR_LOAN_LIMIT_EXCEEDED`.

**The tiered recording fee is financed into the note.** `lien_recording_fee_cents` is chosen once from the pre-fee project cost: a project cost at or below twenty thousand dollars — 2,000,000 cents — carries a fee of one hundred and fifty dollars, or 15,000 cents; a project cost above that and at or below fifty thousand dollars — 5,000,000 cents — carries a fee of two hundred and fifty dollars, or 25,000 cents; a project cost above fifty thousand dollars carries a fee of four hundred dollars, or 40,000 cents. That tier is locked at structuring: the fee is never re-chosen after it has been added into the principal, is never re-chosen because the per-household cap bound the principal, and is never re-chosen when a change order later moves the project cost.

`principal_cents` is the lesser of two figures: the project cost plus the recording fee, and the program year's `max_loan_amount_cents`. Because the maximum absorbs the financed fee, an awarded bid exactly at the maximum still structures successfully, with a principal capped at the maximum.

The monthly payment depends on the structure. A `DEFERRED` note and a `FORGIVABLE` note both carry a `monthly_payment_cents` of zero. An `AMORTIZING` note at a zero rate carries a `monthly_payment_cents` equal to the principal divided by `term_months`, rounded half up to whole cents. An `AMORTIZING` note at a non-zero rate carries the level annuity payment: the monthly rate is `interest_rate_bps` divided by ten thousand to give the annual rate as a decimal and then divided by twelve; the growth factor is one plus that monthly rate raised to the power of `term_months`; and the payment is the principal multiplied by the monthly rate, multiplied by that growth factor, divided by the growth factor less one. The annuity is evaluated at full precision and rounded half up to whole cents exactly once, at the end.

A newly structured note opens in `STRUCTURED` and commits nothing to the program year. `lien_position`, `lien_recorded_at` and `forgiveness_start_date` are unset; `contract_earned_cents`, `disbursed_cents`, `retainage_held_cents`, `forgiven_cents` and `principal_repaid_cents` are zero; `unforgiven_balance_cents` is the principal less accrued forgiveness less principal repaid, which at this point equals the full principal; and `recapture_event_type`, `recapture_event_date`, `net_proceeds_cents`, `recapture_amount_cents`, `shortfall_forgiven_cents` and `program_income_posted_cents` are all unset.

**Recording the lien** is the moment money is committed and the dwelling is released to construction. The `LoanOfficer` supplies the `lien_position` in which the mortgage was recorded and the `recorded_instrument_number` returned by the recorder. Recording proceeds only from a note in `STRUCTURED`, only from a compliance posture of `CLEAR` or `CLEARED_WITH_PROTOCOL` — with the two clearance identifiers of §3.4 guarding the other postures — and only when the program year's `uncommitted_amount_cents` is at least the note's `principal_cents`; an insufficient balance is refused with `ERR_ALLOCATION_INSUFFICIENT`.

Recording writes across three rows. `lien_position` and `lien_recorded_at`, taken from the logical clock, are stored and the note moves `STRUCTURED → LIEN_RECORDED`. The program year's `committed_amount_cents` increases by the full `principal_cents`. The recording fee is then disbursed immediately: the note's `disbursed_cents` increases by `lien_recording_fee_cents`, the program year's `committed_amount_cents` decreases by that same fee, and its `disbursed_amount_cents` increases by that same fee — so the fee passes straight through the committed bucket into the disbursed bucket in one step. Finally the case moves `AWARDED → UNDER_CONSTRUCTION`. All three rows advance their `version` by one.

### 3.7. Construction Draws, Change Orders and Close-Out

Nothing moves on a construction contract until the lien secures it. A `Contractor` requests payment by naming the `loan_id`, its own `contractor_id`, the value of work certified in this draw as `requested_amount_cents` (greater than zero), and `is_final_draw`, true when this draw closes the construction contract and releases retainage; that flag defaults to false. The requesting firm's `contractor_id` must equal the acting `X-User-ID` and must equal the awarded contractor of the loan's case. A draw against a loan whose lien is not recorded — that is, a loan without `lien_recorded_at` set and whose `status` is neither `LIEN_RECORDED` nor `DISBURSING` — is refused with `ERR_LIEN_NOT_RECORDED`. An accepted draw opens in `SUBMITTED` with `approved_amount_cents`, `retainage_cents`, `net_payment_cents`, `approved_by_user_id` and `paid_at` all unset.

**Draw inspection.** A `DRAW` site visit whose `draw_request_id` names the draw drives the draw's state. A recorded result of `PASS` moves the draw from `SUBMITTED` to `INSPECTION_PASSED`; a recorded result of `FAIL` moves it from `SUBMITTED` to `INSPECTION_FAILED`. A failed draw is not resubmitted — it is re-inspected on the same row, and a later `DRAW` visit on that draw recording `PASS` moves it `INSPECTION_FAILED → INSPECTION_PASSED`. Every one of those transitions advances the draw's `version` by one.

**Approval.** A `LoanOfficer` approves a draw that has passed inspection. Four gates apply. The draw must be in `INSPECTION_PASSED`: a draw still in `SUBMITTED`, never inspected, and a draw in `INSPECTION_FAILED` are both refused with `ERR_DRAW_INSPECTION_NOT_PASSED` rather than the generic invalid-state identifier, because the gate is the state of the sibling inspection row rather than the draw's own lifecycle. The case's compliance posture must be `CLEAR` or `CLEARED_WITH_PROTOCOL`, or the approval is refused with `ERR_LEAD_CLEARANCE_REQUIRED` — which is exactly what happens when an approved change order re-opened the lead hold. The approver must not be the inspector: the acting `X-User-ID` must differ from the `performed_by_user_id` of the `DRAW` inspection that passed this draw, or the approval is refused with `ERR_SEGREGATION_OF_DUTIES`. And the draw must fit inside the construction contract: `requested_amount_cents` must be at or below the loan's `approved_project_cost_cents` less its `contract_earned_cents`, so a draw for exactly the remaining balance is allowed while anything larger is refused with `ERR_DRAW_EXCEEDS_CONTRACT_BALANCE`.

Approval certifies the amount and withholds retainage. `approved_amount_cents` is set to `requested_amount_cents` exactly. On an ordinary draw, `retainage_cents` is ten percent of the approved amount, rounded half up to whole cents, and `net_payment_cents` is the approved amount less that retainage. On a final draw, no new retainage is withheld — `retainage_cents` is zero — and all retainage held on the loan to date is released with this payment, so `net_payment_cents` is the approved amount plus the loan's current `retainage_held_cents`. Approval stamps `approved_by_user_id` with the acting `X-User-ID`, moves the draw `INSPECTION_PASSED → APPROVED`, and advances the draw's `version` by one.

**Payment.** Paying an approved draw is the system's longest cascade, and it runs in four hops within the single request. Payment proceeds only from a draw in `APPROVED` whose loan is in `LIEN_RECORDED` or `DISBURSING`. Hop one moves the draw `APPROVED → PAID`, stamps `paid_at` from the logical clock, and posts the money on the loan: `contract_earned_cents` increases by `approved_amount_cents`, `retainage_held_cents` increases by `retainage_cents` on an ordinary draw or is released to zero on a final draw, and `disbursed_cents` increases by `net_payment_cents`. Hop two posts the same money on the program year: `committed_amount_cents` decreases by `net_payment_cents` and `disbursed_amount_cents` increases by the same figure. Hop three moves the loan: a first payment takes it `LIEN_RECORDED → DISBURSING`, and once the posted payment has brought `disbursed_cents` to equal `principal_cents` exactly, the loan moves `DISBURSING → FULLY_DISBURSED`. Hop four follows only that second loan transition, driving the case `UNDER_CONSTRUCTION → CONSTRUCTION_COMPLETE`. Every row touched by any hop advances its `version` by one.

Across the whole construction phase one identity is conserved on each loan: `contract_earned_cents` plus `lien_recording_fee_cents` equals `disbursed_cents` plus `retainage_held_cents`.

**Change orders.** A `RehabSpecialist` submits a scope change against a secured loan, naming the `loan_id`, the `expected_loan_version` last observed, the signed `amount_delta_cents` (which may not be zero), a written `justification` required by the program file, `affects_lead_hazard_work` (true when the change disturbs painted surfaces or alters lead hazard control scope, defaulting to false), and, when the change replaces an earlier one, the `supersedes_change_order_id` of that earlier change order. A change order against a loan whose lien is not recorded is refused with `ERR_LIEN_NOT_RECORDED`, and a stale `expected_loan_version` is refused with `ERR_STALE_VERSION` as described in §2.10. An accepted change order opens in `SUBMITTED` with `submitted_by_user_id` set to the acting `X-User-ID` and `cumulative_delta_pct` at zero, and advances the loan's `version` by one.

A `ProgramManager` decides the change order. Denial supplies a `reason`, moves the change order `SUBMITTED → DENIED`, has no ledger effect at all, and advances the change order's `version` by one. Both `DENIED` and `APPROVED` are terminal for that row.

Approval runs the cumulative exposure test first. The input set is this change order together with every already-approved change order on the same loan, excluding any change order this one supersedes — following `supersedes_change_order_id` transitively, so a chain of replacements is backed out in full, because a superseded delta is removed before the new delta is applied. The prior delta is the sum of `amount_delta_cents` over the approved change orders that remain in the set; the cumulative delta is that prior sum plus this change order's own `amount_delta_cents`. `cumulative_delta_pct` is one hundred multiplied by the cumulative delta divided by the loan's `awarded_bid_amount_cents`, rounded half up to two decimal places. The program tolerates cumulative growth up to twenty percent of the awarded contract: a cumulative figure exactly at 20.00 percent is approved, and anything above it is refused with `ERR_CHANGE_ORDER_EXCEEDS_LIMIT`. This is an aggregate test — each individual change order may be modest while the running total crosses the limit.

Approval proceeds only from a change order in `SUBMITTED` on a loan in `LIEN_RECORDED` or `DISBURSING`. Where the delta is positive, the program year's `uncommitted_amount_cents` must be at least the resulting increase in `principal_cents`, or the approval is refused with `ERR_ALLOCATION_INSUFFICIENT`. A successful approval moves the change order `SUBMITTED → APPROVED` and cascades: any change order this one supersedes moves `APPROVED → SUPERSEDED` and its `amount_delta_cents` is removed from the loan's `approved_project_cost_cents` before the new delta is applied; the loan's `approved_project_cost_cents` moves by `amount_delta_cents`, its `principal_cents` is recomputed against the same locked `lien_recording_fee_cents` and the program year's per-household maximum; and the program year's `committed_amount_cents` moves by the same principal delta, shifting money between the uncommitted and committed buckets. When `affects_lead_hazard_work` is true and the case's `lead_review_required` is true, the compliance posture returns to `LEAD_HOLD` and `lead_hazard_control_method` resets to `NONE`, as described in §3.4. Every touched row advances its `version` by one.

**Close-out.** A `LoanOfficer` closes out construction by supplying the `completion_date`. Close-out proceeds from a loan in `DISBURSING` or `FULLY_DISBURSED`, requires that `retainage_held_cents` be exactly zero — a loan still holding retainage is refused with `ERR_INVALID_STATE` — and requires that the supplied `completion_date` be no earlier than the loan's `lien_recorded_at`. Close-out releases the unspent commitment: the released amount is `principal_cents` less `disbursed_cents`, and the program year's `committed_amount_cents` decreases by exactly that figure. From a fully disbursed loan the released amount is zero; from a loan closed out while still disbursing it is positive. The note is then reset to the money actually spent — `principal_cents` is reduced to `disbursed_cents`, `unforgiven_balance_cents` is recomputed, and `monthly_payment_cents` is recomputed on the reduced principal for an `AMORTIZING` note using exactly the annuity described in §3.6. `forgiveness_start_date` is set to the supplied `completion_date`, which becomes the zero point of the forgiveness clock, and the loan moves to `SERVICING`. The awarded firm's `on_time_completion_count` increases by one and its `performance_score` is recomputed. Finally the case moves to `CLOSED` — from `CONSTRUCTION_COMPLETE` or directly from `UNDER_CONSTRUCTION` — and its `warranty_expires_at` is stamped as the supplied `completion_date` plus a warranty period of twelve calendar months. Every touched row advances its `version` by one.

### 3.8. Servicing, Forgiveness and Recapture

A servicing note may receive homeowner principal payments. A `LoanOfficer` posts one by supplying the `amount_cents` paid and the `payment_date` it was received. The payment increases the loan's `principal_repaid_cents` by the paid amount, recomputes `unforgiven_balance_cents`, and raises the program year's `program_income_balance_cents` by the same amount — repaid principal returns to the activity as program income and therefore raises `uncommitted_amount_cents` by the same figure. The loan's `version` advances by one.

**Forgiveness accrues with time, not with payment.** When the assisted property is sold or otherwise leaves owner occupancy, a `ProgramManager` records the event and the system settles the note. The elapsed period is the number of whole calendar months from `forgiveness_start_date` to `recapture_event_date`, truncated toward zero and never negative. When `forgiveness_term_months` is zero, `forgiven_cents` is zero — an amortizing note earns no forgiveness. When the elapsed months are at or beyond `forgiveness_term_months`, `forgiven_cents` equals `principal_cents` in full. Otherwise `forgiven_cents` is `principal_cents` multiplied by the elapsed months and divided by `forgiveness_term_months`, rounded half up to whole cents. `unforgiven_balance_cents` is then `principal_cents` less `forgiven_cents` less `principal_repaid_cents`, floored at zero.

What the program collects depends on the event. The `recapture_event_type` is one of `SALE`, `TRANSFER`, `REFINANCE` or `RENTAL_CONVERSION`, and it is recorded together with `recapture_event_date`.

- On a `SALE`, the program shares in net proceeds and collects nothing beyond them. The payload additionally carries `sale_price_cents`, `closing_costs_cents` and `homeowner_investment_cents`. `net_proceeds_cents` is the sale price less the case's `senior_lien_balance_cents`, less the closing costs, less the homeowner investment, floored at zero. `recapture_amount_cents` is the lesser of `unforgiven_balance_cents` and `net_proceeds_cents`.
- On a `TRANSFER`, a `REFINANCE` or a `RENTAL_CONVERSION` there are no sale proceeds to share. `net_proceeds_cents` is zero and `recapture_amount_cents` is the entire `unforgiven_balance_cents`, regardless of any value the property may hold. `shortfall_forgiven_cents` is therefore always zero on these three event types.

`shortfall_forgiven_cents` is `unforgiven_balance_cents` less `recapture_amount_cents` — the balance written off because proceeds were insufficient. `program_income_posted_cents` equals `recapture_amount_cents`, and the program year's `program_income_balance_cents` increases by that figure, raising `uncommitted_amount_cents` by the same amount and making the recaptured money available to the next household. Across every settlement one identity is conserved: `forgiven_cents` plus `principal_repaid_cents` plus `recapture_amount_cents` plus `shortfall_forgiven_cents` equals `principal_cents`.

Settlement branches the loan's terminal state. A settlement that recovers money moves the loan `SERVICING → RECAPTURED`. A settlement where nothing is recoverable — a computed `recapture_amount_cents` of zero — moves the loan `SERVICING → FORGIVEN`, sets `shortfall_forgiven_cents` to the whole `unforgiven_balance_cents`, and leaves `program_income_balance_cents` unchanged. Both are terminal, and both advance the loan's `version` by one.

### 3.9. Warranty Complaints and Contractor Discipline

The program stands behind the work for twelve months after completion, and the warranty file is the homeowner's remedy. An `Applicant` may file a complaint on their own case, and a `RehabSpecialist` may file one on the household's behalf. The filing names the `contractor_id` complained about, the `application_id` whose warranty is invoked, the `defect_category` — `WORKMANSHIP`, `INCOMPLETE_WORK`, `MATERIAL_DEFECT` or `WARRANTY_REFUSAL` — and the homeowner's narrative as `description`. Filing is accepted only while the logical clock is at or before the case's `warranty_expires_at`: a complaint filed exactly at that instant is still accepted, one instant later is refused with `ERR_WARRANTY_EXPIRED`, and a complaint against a case that has never been closed out and therefore has no warranty period is likewise refused with `ERR_WARRANTY_EXPIRED`. An accepted complaint stamps `filed_at` from the logical clock, opens in `FILED`, and snapshots the case's `warranty_expires_at` onto the complaint row so that later movement of the case cannot change the window that governed the filing. `remedy_deadline_at`, `sanction_level` and `resolved_at` are unset.

Filing immediately re-scores the firm. `open_complaint_count` is recomputed as the number of that firm's complaints whose status is `FILED`, `CONTRACTOR_NOTIFIED` or `ESCALATED`, and `performance_score` is recomputed as described below; if the recomputed score falls below the probation threshold while the firm is still `APPROVED`, the firm is demoted `APPROVED → PROBATION` within the same request.

**Scoring the approved list.** A firm's `performance_score` starts from a base of 100, loses 20 points for each open complaint, loses 15 points for each sanction recorded in `sanction_count`, and gains 5 points for each completed rehabilitation counted in `on_time_completion_count`, where the completion credit stops accumulating after four completions. The result is clamped into the closed range from 0 to 100. A score strictly below 50 demotes an `APPROVED` firm to `PROBATION` automatically. Promotion is never automatic: only an explicit standing change by a `ProgramManager` can restore a firm to `APPROVED`, and that restoration from `PROBATION` requires the firm's `performance_score` to be at or above 50. The score is recomputed whenever a complaint is filed, resolved or sanctioned, and whenever a loan is closed out.

**The complaint lifecycle.** A `ProgramManager` notifies the firm, which moves the complaint `FILED → CONTRACTOR_NOTIFIED` and sets `remedy_deadline_at` to the logical clock plus a thirty-day remedy window. From `CONTRACTOR_NOTIFIED` the manager records one of three resolutions, supplying the `resolution` and optionally a `resolution_note`. A `resolution` of `REMEDIED` moves the complaint `CONTRACTOR_NOTIFIED → REMEDIED`; a `resolution` of `DISMISSED` moves it `CONTRACTOR_NOTIFIED → DISMISSED`. Both of those closing outcomes stamp `resolved_at` from the logical clock and recompute the firm's `open_complaint_count` and `performance_score`, and both are terminal. A `resolution` of `ESCALATED` moves the complaint `CONTRACTOR_NOTIFIED → ESCALATED` and is accepted only when the logical clock is at or after `remedy_deadline_at`; escalating before the remedy window has run out is refused with `ERR_INVALID_STATE`. Escalation stamps no `resolved_at` and leaves the complaint open for scoring purposes. Every resolution advances the complaint's `version` by one.

**Sanction.** From `ESCALATED`, a `ProgramManager` sanctions the firm by supplying the `sanction_level` — `PROBATION`, `SUSPENSION` or `REMOVAL` — and optionally a `sanction_note`. The complaint moves `ESCALATED → SANCTIONED`, stores the sanction level, and stamps `resolved_at`. The firm's `sanction_count` increases by one, its `performance_score` is recomputed, and its `approved_list_status` is driven to `PROBATION`, `SUSPENDED` or `REMOVED` to match the sanction level. When the level is `SUSPENSION` or `REMOVAL`, the full bid-withdrawal cascade described next runs as part of the same request. The complaint's `version` advances by one.

**The approved-list standing cascade.** A `ProgramManager` may also move a firm's standing directly, supplying the new `approved_list_status` and optionally a `reason`. The transitions available are `APPROVED → PROBATION`, `PROBATION → APPROVED` (which requires a `performance_score` of at least 50), `APPROVED → SUSPENDED`, `PROBATION → SUSPENDED`, `SUSPENDED → APPROVED` and `SUSPENDED → REMOVED`. `REMOVED` is terminal.

Suspension — reached either directly or through a sanction — runs a four-hop cascade. Hop one moves the firm to `SUSPENDED` and recomputes its `performance_score`. Hop two withdraws its live bids: every bid of that firm whose status is `SUBMITTED` or `RESPONSIVE` and whose solicitation is in `OPEN` or `TABULATED` moves to `WITHDRAWN_BY_PROGRAM`. Hop three re-counts the affected solicitations: each recomputes `bid_count` and `responsive_bid_count`, and a solicitation in `OPEN` or `TABULATED` whose recomputed `responsive_bid_count` has fallen below its `min_bids_required` moves to `FAILED`. Hop four propagates to the cases: each solicitation that just failed drives its case `BID_OPEN → BID_FAILED`. Every row touched by any hop advances its `version` by one.

Reinstating a suspended firm to `APPROVED` runs the compensating restoration. Every bid of that firm still in `WITHDRAWN_BY_PROGRAM` whose solicitation is in `OPEN`, `TABULATED` or `FAILED` returns to the status it held before withdrawal: a bid withdrawn from a solicitation that was `OPEN` returns to `SUBMITTED`, and a bid withdrawn from a solicitation that was `TABULATED` returns to `RESPONSIVE`. Each affected solicitation recomputes `bid_count` and `responsive_bid_count`, and a solicitation sitting in `FAILED` whose recomputed `responsive_bid_count` is at or above its `min_bids_required` moves `FAILED → TABULATED` and drives its case `BID_FAILED → BID_OPEN`. As with the suspension cascade, every touched row advances its `version` by one.

---

## 4. Endpoint Definitions

All endpoints are mounted under the `/rehab` prefix. Creating a new resource answers 201 Created; modifying an existing resource, driving a state transition and reading a resource all answer 200 OK; deleting a repair line answers 204 No Content with no body. Every mutating endpoint returns the created or updated resource in `data`, and every read of a collection returns an array in `data` with pagination fields in `meta`. Request and response payloads are not repeated here — the fields each operation accepts, the computations it runs and the rows it cascades to are specified in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/rehab/_clock/set_current_utc` | Sets the server's logical clock to an explicit UTC instant. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| POST | `/rehab/program-years` | Opens a CDBG program year with its area median income figure, per-unit maximum and annual allocation. | ProgramManager |
| GET | `/rehab/program-years/{program_year_id}` | Reads one program year including its live budget ledger. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| GET | `/rehab/program-years` | Lists program years. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| POST | `/rehab/applicants` | Registers a household applying to the program, capturing income sources and the certification methodology. | IntakeSpecialist |
| PATCH | `/rehab/applicants/{applicant_id}` | Corrects a household's declared income figures or switches the certification methodology before income is verified. | IntakeSpecialist |
| POST | `/rehab/applicants/{applicant_id}/verify-income` | Certifies household income using the declared methodology and records the resulting category. | IntakeSpecialist |
| GET | `/rehab/applicants/{applicant_id}` | Reads one applicant with its certified income figures. | IntakeSpecialist, RehabSpecialist, LoanOfficer, ProgramManager |
| GET | `/rehab/applicants` | Lists applicants, optionally filtered by program year, eligibility status or income category. | IntakeSpecialist, RehabSpecialist, LoanOfficer, ProgramManager |
| POST | `/rehab/applications` | Intakes a rehabilitation application for a verified-income household at a specific dwelling. | IntakeSpecialist |
| POST | `/rehab/applications/{application_id}/verify-ownership` | Records the title examination result and recorded deed date, deciding whether the household holds an eligible ownership interest. | IntakeSpecialist |
| POST | `/rehab/applications/{application_id}/lead-clearance` | Records completion of the lead-based paint risk assessment and the hazard control method chosen. | Inspector |
| POST | `/rehab/applications/{application_id}/historic-clearance` | Records the State Historic Preservation Office determination, clearing or permanently blocking the historic axis. | ProgramManager |
| GET | `/rehab/applications/{application_id}` | Reads one rehabilitation application including both state axes. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Applicant |
| GET | `/rehab/applications` | Lists rehabilitation applications, optionally filtered by household, program year, awarded contractor, workflow state or compliance posture. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| POST | `/rehab/inspections` | Reserves an inspection window for an initial property standards visit, a construction draw inspection or the final inspection. | Inspector |
| POST | `/rehab/inspections/{inspection_id}/record-result` | Records the finding of a completed site visit, including deficiency count and any XRF lead reading. | Inspector |
| GET | `/rehab/inspections/{inspection_id}` | Reads one inspection record. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| GET | `/rehab/inspections` | Lists inspections, optionally filtered by application, draw request, type or status. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| POST | `/rehab/write-ups` | Opens a new work write-up revision for an application, superseding any approved revision. | RehabSpecialist |
| POST | `/rehab/write-ups/{write_up_id}/submit` | Submits a drafted or revised scope of work for program review, freezing its cost estimate. | RehabSpecialist |
| POST | `/rehab/write-ups/{write_up_id}/request-revision` | Returns a submitted scope of work to the rehabilitation specialist for correction. | ProgramManager |
| POST | `/rehab/write-ups/{write_up_id}/approve` | Approves a submitted scope of work. The approver may not be the preparer. | ProgramManager |
| GET | `/rehab/write-ups/{write_up_id}` | Reads one work write-up revision with its estimate roll-up. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Applicant |
| GET | `/rehab/write-ups` | Lists work write-up revisions, optionally filtered by application or state. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| POST | `/rehab/work-items` | Adds one repair line to a write-up that is still DRAFT or REVISION_REQUESTED. | RehabSpecialist |
| DELETE | `/rehab/work-items/{work_item_id}` | Removes a repair line from a write-up that is still DRAFT or REVISION_REQUESTED. | RehabSpecialist |
| GET | `/rehab/work-items/{work_item_id}` | Reads one repair line with its computed protocol multiplier and line total. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| GET | `/rehab/work-items` | Lists repair lines, optionally filtered by write-up revision or priority class. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| POST | `/rehab/contractors` | Adds a contractor to the program's approved list with its licence, insurance and certification profile. | ProgramManager |
| POST | `/rehab/contractors/{contractor_id}/status` | Moves a contractor between approved-list statuses, withdrawing or restoring its live bids. | ProgramManager |
| GET | `/rehab/contractors/{contractor_id}` | Reads one contractor with its live performance score and approved-list status. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| GET | `/rehab/contractors` | Lists contractors, optionally filtered by approved-list status or lead-safe certification. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| POST | `/rehab/bid-solicitations` | Solicits bids against an approved scope of work, snapshotting the independent cost estimate. | RehabSpecialist |
| POST | `/rehab/bid-solicitations/{solicitation_id}/tabulate` | Tabulates received bids, classifying each as responsive or non-responsive and ranking the responsive ones. | RehabSpecialist |
| POST | `/rehab/bid-solicitations/{solicitation_id}/award` | Awards the contract to a responsive bid, subject to approved-list status, lead certification and crew capacity. | ProgramManager |
| POST | `/rehab/bid-solicitations/{solicitation_id}/reopen` | Reopens a failed solicitation with a new due instant so additional bids can be solicited. | ProgramManager |
| GET | `/rehab/bid-solicitations/{solicitation_id}` | Reads one solicitation with its responsiveness window and bid counts. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| GET | `/rehab/bid-solicitations` | Lists solicitations, optionally filtered by application, write-up revision, awarded bid or status. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| POST | `/rehab/bids` | Submits a contractor's sealed bid with its proposed construction window before the due instant. | Contractor |
| GET | `/rehab/bids/{bid_id}` | Reads one bid with its responsiveness classification and rank. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| GET | `/rehab/bids` | Lists bids, optionally filtered by solicitation, contractor or status. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| POST | `/rehab/loans` | Structures the rehabilitation loan on the awarded bid as a deferred, forgivable or amortizing note. | LoanOfficer |
| POST | `/rehab/loans/{loan_id}/record-lien` | Records the mortgage lien, committing the principal against the allocation and releasing the property to construction. | LoanOfficer |
| POST | `/rehab/loans/{loan_id}/close-out` | Closes out construction, releasing unspent commitment and starting the warranty and forgiveness clocks. | LoanOfficer |
| POST | `/rehab/loans/{loan_id}/payments` | Posts a homeowner principal payment against a servicing loan. | LoanOfficer |
| POST | `/rehab/loans/{loan_id}/recapture` | Records a sale or other transfer of the assisted property and computes the amount recaptured as program income. | ProgramManager |
| GET | `/rehab/loans/{loan_id}` | Reads one loan with its full disbursement, forgiveness and recapture ledger. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Applicant |
| GET | `/rehab/loans` | Lists loans, optionally filtered by application, status or structure type. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |
| POST | `/rehab/draw-requests` | Requests payment for completed construction work against a secured loan. | Contractor |
| POST | `/rehab/draw-requests/{draw_request_id}/approve` | Approves a draw whose construction inspection passed, withholding retainage. | LoanOfficer |
| POST | `/rehab/draw-requests/{draw_request_id}/pay` | Pays an approved draw and posts the money movement through the loan and program-year ledgers. | LoanOfficer |
| GET | `/rehab/draw-requests/{draw_request_id}` | Reads one draw request with its retainage and net payment figures. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| GET | `/rehab/draw-requests` | Lists draw requests, optionally filtered by loan, contractor or status. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| POST | `/rehab/change-orders` | Submits a construction change order against a secured loan, optionally superseding an earlier one. | RehabSpecialist |
| POST | `/rehab/change-orders/{change_order_id}/approve` | Approves a change order, adjusting the contract, the committed principal and, where relevant, the compliance posture. | ProgramManager |
| POST | `/rehab/change-orders/{change_order_id}/deny` | Denies a submitted change order. | ProgramManager |
| GET | `/rehab/change-orders/{change_order_id}` | Reads one change order with its cumulative exposure percentage. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| GET | `/rehab/change-orders` | Lists change orders, optionally filtered by loan, superseded change order or status. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Contractor |
| POST | `/rehab/complaints` | Files a workmanship or warranty complaint against the contractor that performed the rehabilitation. | Applicant, RehabSpecialist |
| POST | `/rehab/complaints/{complaint_id}/notify` | Notifies the contractor of the complaint and starts the remedy window. | ProgramManager |
| POST | `/rehab/complaints/{complaint_id}/resolve` | Closes a notified complaint as remedied or dismissed, or escalates it once the remedy window has expired. | ProgramManager |
| POST | `/rehab/complaints/{complaint_id}/sanction` | Sanctions the contractor for an escalated complaint, applying the chosen approved-list consequence. | ProgramManager |
| GET | `/rehab/complaints/{complaint_id}` | Reads one complaint case. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager, Applicant, Contractor |
| GET | `/rehab/complaints` | Lists complaint cases, optionally filtered by contractor, application or status. | IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager |

---

## 5. Error Code Catalogue

The conditions that raise each identifier are stated in the §2 and §3 narratives that govern the operation concerned; the precedence among them is fixed by §2.11.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PROGRAM_YEAR_NOT_FOUND` | 404 |
| `ERR_APPLICANT_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_WRITE_UP_NOT_FOUND` | 404 |
| `ERR_WORK_ITEM_NOT_FOUND` | 404 |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 |
| `ERR_SOLICITATION_NOT_FOUND` | 404 |
| `ERR_BID_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_DRAW_NOT_FOUND` | 404 |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INCOME_NOT_VERIFIED` | 409 |
| `ERR_OWNERSHIP_NOT_VERIFIED` | 409 |
| `ERR_LEAD_CLEARANCE_REQUIRED` | 409 |
| `ERR_HISTORIC_CLEARANCE_REQUIRED` | 409 |
| `ERR_DRAW_INSPECTION_NOT_PASSED` | 409 |
| `ERR_LIEN_NOT_RECORDED` | 409 |
| `ERR_INSPECTION_WINDOW_CONFLICT` | 409 |
| `ERR_BID_WINDOW_CLOSED` | 409 |
| `ERR_CONTRACTOR_CAPACITY_CONFLICT` | 409 |
| `ERR_WARRANTY_EXPIRED` | 409 |
| `ERR_LOAN_LIMIT_EXCEEDED` | 422 |
| `ERR_ALLOCATION_INSUFFICIENT` | 409 |
| `ERR_DRAW_EXCEEDS_CONTRACT_BALANCE` | 422 |
| `ERR_CHANGE_ORDER_EXCEEDS_LIMIT` | 422 |
| `ERR_DUPLICATE_BID` | 409 |
| `ERR_INSUFFICIENT_BIDS` | 409 |
| `ERR_BID_NOT_RESPONSIVE` | 422 |
| `ERR_CONTRACTOR_NOT_APPROVED` | 422 |
| `ERR_CONTRACTOR_NOT_LEAD_CERTIFIED` | 422 |
| `ERR_WRITE_UP_EMPTY` | 422 |
| `ERR_PRIORITY_REPAIRS_NOT_ADDRESSED` | 422 |
| `ERR_APPLICANT_OVER_INCOME` | 422 |
