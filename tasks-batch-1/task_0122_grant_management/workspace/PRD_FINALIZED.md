# Grant Management API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a grantee-side grant management platform. The system serves organizations that receive federal grant funding and must shepherd each award through its full lifecycle: responding to a Notice of Funding Opportunity (NOFO), surviving agency review, receiving an award, standing up its budget and subawards, drawing federal cash against a ceiling, reconciling expenditures through Federal Financial Reports, weathering a Single Audit, and finally reaching closeout. The platform's central obligation is fiscal fidelity — every dollar of federal cash is tracked in integer cents, every drawdown is reconciled against both an award-level ceiling and category-level restricted budgets, and every reimbursement computation is reproducible to the cent.

The domain is defined by strict separation of responsibilities among five operator types and one anonymous baseline. Grant writers prepare applications and performance narratives; finance officers move money and certify spending; program managers govern subawards and progress reviews; an external auditor records Single Audits and their findings; and the federal awarding agency adjudicates application outcomes, accepts financial reports, and controls the award's compliance lifecycle. A recurring theme is that the operator who spends money cannot be the operator who certifies that spending was proper — a segregation-of-duties principle enforced at the point of report certification.

Because grant accounting is a ledger discipline, the system treats certain quantities as conserved: cash that is disbursed and later returned must leave the books in exactly the state it entered, and a drawdown that is unwound must restore every category balance and the award's running federal-drawn total to their pre-disbursement values. The sections that follow define the global contract every endpoint honors (§2), the business workflows and their scattered rules (§3), the endpoint surface (§4), and the canonical error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting as. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed and the role is recognized but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication is always evaluated before authorization.

The recognized roles are exactly: `GrantWriter`, `FinanceOfficer`, `ProgramManager`, `AgencyOfficer`, `Auditor`, and `Anonymous`. The `GrantWriter` prepares and submits NOFO applications and the progress narratives that accompany an active award. The `FinanceOfficer` manages all cash-side artifacts: indirect-cost rates, restricted funds, drawdowns, and Federal Financial Reports. The `ProgramManager` owns subaward governance and the acceptance of progress reports. The `AgencyOfficer` is the federal awarding-agency operator who reviews, awards, and rejects applications, accepts or rejects financial reports, and drives the award's suspension, reinstatement, and closeout lifecycle. The `Auditor` is the independent party who records Single Audits and their findings and drives their resolution. `Anonymous` denotes an unauthenticated caller with no permitted operations; it exists only so that listing and retrieval endpoints can declare a non-anonymous role set explicitly.

Each of these roles carries an opaque identity. When `X-User-Role` is any of `GrantWriter`, `FinanceOfficer`, `ProgramManager`, `AgencyOfficer`, `Auditor`, or `Anonymous`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any entity's `id` to establish ownership. The server may, however, record it where a workflow demands it: when a `FinanceOfficer` creates a drawdown, the acting `X-User-ID` is captured on that drawdown's `initiated_by_user_id`, and when a `FinanceOfficer` certifies a financial report, the acting `X-User-ID` is captured on that report's `certified_by_user_id`. These recorded identifiers exist to support the segregation-of-duties check described in §3, not to gate read or write access by ownership.

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

All listing endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` defaults to 0 and represents the number of leading records to skip. List results are always ordered by `created_at` ascending, so that pagination through a stable result set is deterministic. For every list response, the `meta` block carries `limit`, `offset`, `total_count` (the number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and Versioning

Every resource is identified by an `id`, which is a server-minted UUID with no type prefix. The `id` is identity only — it is never a business-decision input and the server never derives behavior from its value. Most resources also carry three system-managed timestamps and counters: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 on creation and increments by 1 on every mutation of that resource. The `created_at` value is fixed at creation and never changes; `updated_at` is refreshed on every mutation; and `version` advances in lockstep with `updated_at`.

One entity is deliberately lighter. A fund-allocation line — the record produced when a disbursed drawdown posts cash to a restricted fund — carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is an immutable ledger artifact: once written by a disbursement it is never mutated in place, and when a drawdown is returned its allocation lines are reversed by adjusting the fund balances they fed rather than by editing the lines. Implementations must not expose `updated_at` or `version` on fund-allocation lines.

### 2.5. Monetary Precision and Rounding

All monetary quantities are stored and exchanged as integer cents; the API never uses fractional cents or floating-point dollars. Where a computation multiplies an integer-cent base by a decimal rate or fraction and the product is not a whole number of cents, the result is rounded to the nearest whole cent using round-half-up (a value ending in exactly half a cent rounds up to the next cent). This rounding rule applies to the federal ceiling derived at award issuance, to indirect-cost recovery, to the federal share of reimbursements, and to the cumulative approved-expenditure ledger. Sums of integer-cent quantities are exact and require no rounding. Where a calculation specifies that a rate is applied once to a summed base, the rounding occurs once on that single product — never per line item.

### 2.6. Optimistic Concurrency on Award Mutations

Certain operations mutate an award and therefore require the caller to prove it is acting on a current view of that award. Each such request must include `expected_award_version`, carrying the `version` value the client last observed for the target award. The server compares it to the award's current `version`; if they differ, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no change is made. The operations that take `expected_award_version` and are guarded this way are: suspending an award, reinstating an award, initiating closeout, closing an award, and creating an indirect-cost rate for an award.

The indirect-cost-rate case is the subtle one. Creating a new indirect-cost rate legitimately supersedes whichever rate was previously in force for the award, retiring the prior rate. Because that supersede advances the award's `version`, a second create request that still carries the `version` the client first observed describes a stale view: the first create already moved the award forward, so the second is rejected with `ERR_STALE_VERSION` (HTTP 412) on the stale `version`, not on any state precondition. Endpoints that are not in the list above do not accept and do not consider `expected_award_version`.

### 2.7. Cross-Entity Consistency and Ledger Conservation

Several operations touch more than one entity in a single atomic step, and the secondary effects matter as much as the primary one. When a drawdown is disbursed, the award's running federal-drawn ledger and every affected restricted-fund balance move together with the drawdown's own state, and the award's `version` advances. When a drawdown is returned, those same balances are reversed so that the award's federal-drawn total and each fund's allocated total return precisely to their pre-disbursement values — the federal-drawn total is a conserved quantity across a disburse-then-return pair. When a financial report is accepted, the award's cumulative approved-expenditure ledger is recomputed and the award's `version` advances. Each of these award mutations refreshes the award's `updated_at`. The specific arithmetic and ordering of these cascades is given in §3.

### 2.8. Nested Path Resolution

A handful of endpoints address a child collection through a parent path segment — for example, the allocation lines of a drawdown, the allocation lines posted to a restricted fund, and the findings of a single audit. Path parameters are validated left to right: the parent resource named earliest in the path is resolved first, and if it does not exist the request fails with `ERR_NOT_FOUND` (HTTP 404) before any later segment or body field is considered. The same existence rule governs every foreign-key reference supplied in a request body: a body that names an award, a drawdown, a restricted fund, or a single audit that does not exist is rejected with `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. From Funding Opportunity to Award

The grant lifecycle begins when a `GrantWriter` drafts an application in response to a funding opportunity. Creating an application records the `nofo_number` it responds to, the `applicant_org_name` of the grantee, the `requested_amount_cents` (total federal funds requested across the full period of performance, which must be at least 1), and the proposed period of performance as `period_start_date` and `period_end_date`. The period is a half-open interval: the start instant is included and the end instant is excluded. The writer may also supply `federal_share_pct`, the federal share of total project cost expressed as a decimal fraction greater than 0 and at most 1; when omitted it defaults to 0.80, and the recipient's cost-share is understood to be one minus this value. A new application is born in `DRAFT`.

When an application is a resubmission, the writer sets `supersedes_application_id` to the `id` of the prior `REJECTED` application it replaces, establishing a self-referential resubmission lineage; this field is nullable and defaults to null on a first submission. Applications may be listed and filtered by their superseded lineage or by `status`, and any single application may be retrieved on its own.

A `DRAFT` application advances to `SUBMITTED` when the writer submits it, provided it is currently in `DRAFT` and its `period_end_date` is strictly after its `period_start_date`; a period that fails this ordering is rejected with `ERR_INVALID_PERIOD`. The same submit action serves the revision loop: an application in `REVISIONS_REQUESTED` returns to `SUBMITTED` through submission, again subject to the same period-ordering check. Submitting from any state other than `DRAFT` or `REVISIONS_REQUESTED` is rejected with `ERR_INVALID_STATE`. While still in `DRAFT`, the writer may instead withdraw the application, moving it to the terminal `WITHDRAWN` state.

Agency adjudication is the `AgencyOfficer`'s domain. Beginning review moves a `SUBMITTED` application to `UNDER_REVIEW`. From `UNDER_REVIEW`, the officer has three exits. Requesting revisions returns the application to `REVISIONS_REQUESTED`, from which the writer may resubmit — so the cycle `REVISIONS_REQUESTED → SUBMITTED → UNDER_REVIEW` may repeat any number of times. Rejecting moves it to the terminal `REJECTED` state. Awarding moves it to the terminal `AWARDED` state and, in the same step, issues the Award. Each of these officer transitions requires the application to be in `UNDER_REVIEW`; attempting them from any other state yields `ERR_INVALID_STATE`.

### 3.2. The Award and Its Ledger

Issuing an award is a cross-entity creation triggered by awarding an application. The new Award records `application_id` pointing back at the `AWARDED` application it was issued from. It copies `total_award_cents` from the application's `requested_amount_cents`, copies `federal_share_pct` from the application, and copies the `period_start_date` and `period_end_date`. It then computes `federal_ceiling_cents` as the product of `total_award_cents` and `federal_share_pct`, rounded half-up to whole cents — this ceiling is the maximum federal cash the grantee may ever draw or be reimbursed over the life of the award. The award opens in `ACTIVE` status with its two running ledgers initialized to zero: `federal_drawn_cents` (federal cash actually disbursed) and `federal_approved_expenditures_cents` (cumulative approved federal-eligible expenditures). Awards may be listed, optionally filtered by their source `application_id` or by `status`, and any one award may be retrieved to inspect its `federal_ceiling_cents`, `federal_drawn_cents`, `federal_approved_expenditures_cents`, and `version`.

The `AgencyOfficer` controls the award's compliance lifecycle, and every one of these transitions is optimistic-concurrency-guarded on `expected_award_version` as described in §2.6 and increments the award's `version`. An `ACTIVE` award may be suspended, moving it to `SUSPENDED`; a `SUSPENDED` award may be reinstated back to `ACTIVE`. An `ACTIVE` award may have closeout initiated, moving it to `PENDING_CLOSEOUT`. Each of these requires the award to be in the corresponding source state, failing otherwise with `ERR_INVALID_STATE`.

Closing an award is the most heavily gated transition in the system. It applies only to an award in `PENDING_CLOSEOUT`, requires a matching `expected_award_version`, and is permitted only when several cross-entity preconditions all hold. First, no Federal Financial Report for the award may be in `DRAFT` or `SUBMITTED` status, and no subaward of the award may be in `ACTIVE` status — every subaward must be in `PROPOSED`, `APPROVED`, or `TERMINATED`; a violation here is rejected with `ERR_CLOSEOUT_PRECONDITIONS`. Second, every Single Audit of the award whose audit was required must be in `RESOLVED` status, and no audit finding of severity `MATERIAL_WEAKNESS` may remain `OPEN`; a violation here is rejected with `ERR_AUDIT_UNRESOLVED`. When all preconditions hold, the award moves to the terminal `CLOSED` state, its `version` increments, and the close response surfaces `closeout_unobligated_cents`, computed as the award's `federal_ceiling_cents` minus its current `federal_drawn_cents` — the federal cash authorized but never drawn.

### 3.3. Establishing the Indirect-Cost Rate

Before indirect costs can be recovered on a financial report, a `FinanceOfficer` sets the indirect-cost rate in force for the award. Creating a rate names the `award_id` it applies to and the `rate_type`, which is either `NEGOTIATED` (a federally negotiated rate) or `DE_MINIMIS` (the standard ten-percent rate). When the rate type is `NEGOTIATED`, the officer must supply `negotiated_rate` as a decimal fraction greater than 0 and at most 1; that contextual requirement is enforced, and a `NEGOTIATED` rate missing its `negotiated_rate` is rejected with `ERR_INVALID_REQUEST`. When the rate type is `DE_MINIMIS`, the system applies the fixed ten-percent rate and ignores `negotiated_rate` even if it is present. The officer may also specify `base_type` — either `MTDC` (Modified Total Direct Cost) or `TDC` (Total Direct Cost) — which defaults to `MTDC`. The MTDC base excludes equipment costs entirely and excludes the portion of each subaward pass-through line that exceeds twenty-five thousand dollars.

A newly created rate is born `ACTIVE`, and creating it retires whatever rate was previously `ACTIVE` for that award by moving the prior rate to `SUPERSEDED`. Because this mutates the award, the create requires `expected_award_version` and increments the award's `version`; the stale-version behavior of sequential rate creates is described in §2.6. Indirect-cost rates may be listed, filtered by `award_id` or `status`, and any one rate may be retrieved to inspect its `rate_type`, `status`, and effective rate.

### 3.4. Subawards and Their Governance

A `ProgramManager` may pass federal funds through to a subrecipient by creating a subaward under an award. Creating a subaward records the `award_id` of the prime award, the `subrecipient_name`, the `subaward_amount_cents` committed over the subaward's term (which must be at least 1), and a `risk_tier` of `LOW`, `MEDIUM`, or `HIGH` that defaults to `LOW`. A new subaward is born in `PROPOSED`. Subawards may be listed and filtered by `award_id` or `status`, and any one may be retrieved.

The program manager advances a subaward through its lifecycle. Approving moves a `PROPOSED` subaward to `APPROVED`, and this is permitted only while the prime award is `ACTIVE`. Activating moves an `APPROVED` subaward to `ACTIVE`, again only while the prime award is `ACTIVE`. In both cases, if the parent award is not `ACTIVE`, the operation is rejected with `ERR_AWARD_NOT_ACTIVE`; and if the subaward is not in the required source state, the operation is rejected with `ERR_INVALID_STATE`. Termination is available from two states: an `ACTIVE` subaward may be terminated, and an `APPROVED` subaward that was never activated may be terminated; either path moves the subaward to the terminal `TERMINATED` state. Termination from any state other than `ACTIVE` or `APPROVED` is rejected with `ERR_INVALID_STATE`.

### 3.5. Restricted Funds and the Drawdown Waterfall

Federal cash is budgeted into restricted categories before it is drawn. A `FinanceOfficer` creates a restricted fund under an award by supplying the `award_id`, the `category` (one of `PERSONNEL`, `EQUIPMENT`, `TRAVEL`, `SUPPLIES`, `SUBAWARD_PASS_THROUGH`, or `INDIRECT`), the `budgeted_cents` ceiling for that category over the period of performance (which must be at least 0), and a `priority_order` (an integer of at least 1 that ranks the fund in the drawdown waterfall, lower numbers filled first). Each fund tracks `allocated_cents`, a running total of cash posted against it that begins at 0 and may never exceed its `budgeted_cents`. Within a single award, both `priority_order` and `category` must be distinct across funds; a duplicate of either is rejected with `ERR_DUPLICATE`. Restricted funds may be listed by `award_id` and individually retrieved to inspect `allocated_cents`.

Drawing federal cash is a two-step affair owned by the `FinanceOfficer`. First, the officer creates a drawdown naming the `award_id`, the `amount_cents` of federal cash requested (at least 1), and a proposed `allocation_plan` — an ordered list in which each entry names a `restricted_fund_id` and the `amount_cents` to post to it. The sum of the plan's `amount_cents` entries must equal the drawdown's `amount_cents`, or the create is rejected with `ERR_INVALID_REQUEST`. Creating a drawdown records the acting operator on `initiated_by_user_id` and opens the drawdown in `REQUESTED`. Drawdowns may be listed by `award_id` or `status` and individually retrieved.

Disbursing a drawdown is where the money actually moves, and the server independently re-derives the canonical allocation rather than trusting the requester's plan. The server distributes the drawdown's `amount_cents` across all of the award's restricted funds — every fund participates, regardless of its category or status — taken in ascending `priority_order`, with `created_at` ascending as the tie-break. Walking the funds in that order, each fund absorbs the smaller of the cash still remaining and that fund's headroom, where headroom is `budgeted_cents` minus current `allocated_cents`; whenever the amount taken is greater than zero, an allocation line is recorded for that fund and the remaining cash is reduced by the amount taken. The server's derived allocation must equal the requester's `allocation_plan` line for line — the same fund identifiers, the same amounts, and the same order — or the disbursement is rejected with `ERR_ALLOCATION_MISMATCH`; this plan-match comparison is evaluated before the undistributed-remainder check below, consistent with the §3.9 ordering. Then, if, after every fund has been considered, cash still remains undistributed, there is insufficient budget headroom across all funds and the disbursement is rejected with `ERR_BUDGET_WOULD_EXCEED`. (Because the requester's `allocation_plan` must sum to the drawdown's `amount_cents` while the derived waterfall caps each line at headroom, an undistributed remainder forces the derived allocation to fall short of the plan; the plan-match comparison therefore fails first, so `ERR_ALLOCATION_MISMATCH` is the error reported when both conditions are simultaneously true.) A drawdown that needs only its first eligible fund yields a single allocation line and leaves later funds untouched; a drawdown larger than the first fund's headroom fills that fund to its budget and spills the remainder into the next-priority fund or funds.

Two further guards apply at disbursement, beyond the validation ordering of §3.9. The parent award must be `ACTIVE`, failing otherwise with `ERR_AWARD_NOT_ACTIVE`. And the drawdown must not breach the federal ceiling: the award's `federal_drawn_cents` plus the drawdown's `amount_cents` must not exceed the award's `federal_ceiling_cents`, failing otherwise with `ERR_CEILING_EXCEEDED`. The per-fund budget guard is the same condition that drives the waterfall — for every derived line, the fund's `allocated_cents` plus that line's `amount_cents` must not exceed the fund's `budgeted_cents`, and a breach surfaces as `ERR_BUDGET_WOULD_EXCEED`.

When a disbursement succeeds, the drawdown moves from `REQUESTED` to `DISBURSED` and a cascade fires in order. First, one fund-allocation line is created for each waterfall line, each carrying its parent `drawdown_id`, the target `restricted_fund_id`, and the `amount_cents` posted. Second, each restricted fund's `allocated_cents` is increased by the amount of its allocation line. Third, the award's `federal_drawn_cents` is increased by the drawdown's `amount_cents`, keeping the federal ledger in sync. Finally, the award's `version` is incremented. The allocation lines produced by a disbursed drawdown can be listed, as can the allocation lines posted to any given restricted fund.

Returning a drawdown unwinds all of this. A `DISBURSED` drawdown may be returned by the `FinanceOfficer`, moving it to the terminal `RETURNED` state; returning from any other state yields `ERR_INVALID_STATE`. The return reverses the disbursement's effects so that conserved balances are restored exactly: for each of the drawdown's allocation lines, the corresponding restricted fund's `allocated_cents` is decreased by that line's amount, and the award's `federal_drawn_cents` is decreased by the drawdown's `amount_cents`, returning the federal-drawn total to its pre-disbursement value. The award's `version` is incremented by the return as well.

### 3.6. Financial Reporting and Reimbursement

A Federal Financial Report (FFR) reconciles spending and computes the reimbursement owed. A `FinanceOfficer` creates a report against an `award_id` with a `period_label` (a reporting-period label such as a fiscal quarter), a `report_basis` of either `INTERIM` or `FINAL`, and `direct_cost_lines` — a list in which each entry names a `category` (one of the restricted-fund categories other than `INDIRECT`) and an `amount_cents`. The officer may also supply `disallowed_cents` (federal-eligible costs disallowed for this report, at least 0, defaulting to 0); this value is applied only on a `FINAL` report and is ignored on an `INTERIM` report. A report's `period_label` must be unique per award among reports that are not `REJECTED`; a clashing label is rejected with `ERR_DUPLICATE`. A new report opens in `DRAFT`. Reports may be listed by `award_id` or `status` and individually retrieved to inspect their computed `approved_direct_cents`, `indirect_cost_cents`, and `reimbursable_cents`.

Certifying a report submits it for agency review. The `FinanceOfficer` certifies a `DRAFT` report, moving it to `SUBMITTED` and recording the acting operator on `certified_by_user_id`. Certification is permitted only when the parent award is in `ACTIVE` or `PENDING_CLOSEOUT` status. Crucially, certification enforces segregation of duties: the acting `X-User-ID` must not equal any `initiated_by_user_id` recorded on any drawdown of the same award, so that the operator who moved the money cannot be the operator who attests to its propriety. A certifier who initiated a drawdown on that award is rejected with `ERR_SEGREGATION_OF_DUTIES`. Certifying a report that is not in `DRAFT` yields `ERR_INVALID_STATE`.

Acceptance is the `AgencyOfficer`'s prerogative and is where all the financial computations land. Accepting a `SUBMITTED` report moves it to `ACCEPTED` and, in one step, computes three derived figures and updates the award ledger. The report's `approved_direct_cents` is set to the exact sum of the `amount_cents` across its `direct_cost_lines`. The report's `indirect_cost_cents` is computed from the award's single `ACTIVE` indirect-cost rate as described below. The report's `reimbursable_cents` is computed according to its `report_basis` variant, also described below. Finally, the award's `federal_approved_expenditures_cents` is recomputed as the award's `federal_share_pct` multiplied by the sum of `approved_direct_cents` over all of that award's `ACCEPTED` reports (including the one just accepted), rounded half-up to whole cents; and the award's `version` is incremented. Accepting a report that is not `SUBMITTED` yields `ERR_INVALID_STATE`.

Indirect-cost recovery is computed once over a single base. Begin with the direct total — the sum of every `direct_cost_lines` entry's `amount_cents`. If the award's `ACTIVE` rate uses the `MTDC` base, two exclusions are subtracted from that direct total: the full amount of every line whose `category` is `EQUIPMENT`, and, for every line whose `category` is `SUBAWARD_PASS_THROUGH`, the portion of that line's amount that exceeds twenty-five thousand dollars (that is, the line amount minus 2,500,000 cents when positive, otherwise nothing). If instead the rate uses the `TDC` base, the base is simply the direct total with no exclusions. The applicable rate is the rate's `negotiated_rate` when its `rate_type` is `NEGOTIATED`, or the fixed ten-percent rate when its `rate_type` is `DE_MINIMIS`. The rate is applied exactly once to the whole computed base — never per line — and the single product is rounded half-up to whole cents to yield `indirect_cost_cents`.

Reimbursement is computed in one of two mutually exclusive variants determined by `report_basis`, and the two yield different numbers for identical period inputs. For an `INTERIM` report (the provisional variant), the reimbursement is simply the award's `federal_share_pct` multiplied by this report's `approved_direct_cents`, rounded half-up to whole cents; there is no ceiling cap, no disallowance subtraction, and no netting against cash already drawn. For a `FINAL` report (the closeout variant), the computation is cumulative and capped and netted: first take the cumulative approved direct costs across all of the award's `ACCEPTED` reports including this one — this report's `approved_direct_cents` plus the sum of `approved_direct_cents` over every other `ACCEPTED` report on the award. Multiply that cumulative figure by the award's `federal_share_pct`, round half-up to whole cents, and then subtract this report's `disallowed_cents`. Cap the result at the award's `federal_ceiling_cents` by taking the smaller of the two. Finally, subtract the award's current `federal_drawn_cents`. The resulting figure is the report's `reimbursable_cents` under the final variant.

A rejected report can be revised. The `AgencyOfficer` may reject a `SUBMITTED` report, moving it to `REJECTED`; rejecting a report that is not `SUBMITTED` yields `ERR_INVALID_STATE`. The `FinanceOfficer` may then revise a `REJECTED` report, returning it to `DRAFT` so the cycle `REJECTED → DRAFT → SUBMITTED` may repeat; revising a report that is not `REJECTED` yields `ERR_INVALID_STATE`.

### 3.7. Progress Reporting

Separate from financial reporting, performance is tracked through progress reports. A `GrantWriter` submits a progress narrative for an award by naming the `award_id`, a `period_label`, the count of `milestones_met` (at least 0), and the count of `milestones_planned` (at least 1). A progress report is born directly in `SUBMITTED`. Progress reports may be listed by `award_id` or `status`, and any one may be retrieved to inspect its `period_label`, `milestones_met`, `milestones_planned`, and `status`.

The `ProgramManager` adjudicates each progress report. Accepting a `SUBMITTED` report moves it to the terminal `ACCEPTED` state. Returning a `SUBMITTED` report for rework moves it to `RETURNED`. From `RETURNED`, the `GrantWriter` may resubmit, moving the report back to `SUBMITTED`, so the return-and-resubmit cycle may repeat. Each of these transitions requires the report to be in the appropriate source state — `SUBMITTED` for acceptance or return, `RETURNED` for resubmission — and a mismatch yields `ERR_INVALID_STATE`.

### 3.8. Single Audit and Findings

When federal expenditures are large enough, an award fiscal year is subject to a Single Audit. The `Auditor` creates a Single Audit by naming the `award_id`, the `fiscal_year` it covers (at least 2000), and the `federal_expenditures_cents` (total federal awards expended in that fiscal year, at least 0). At creation the system computes `audit_required`: it is true exactly when `federal_expenditures_cents` is at least seven hundred fifty thousand dollars, and false otherwise. The boundary is inclusive — federal expenditures of 74,999,999 cents leave `audit_required` false, while 75,000,000 cents make it true. A new audit opens in `OPEN`. Single audits may be listed by `award_id` or `status` and individually retrieved to inspect `audit_required`.

The audit's resolution path depends on whether it was required. A required audit — one whose `audit_required` is true — is submitted by the `Auditor`, moving it from `OPEN` to `SUBMITTED`; submission of an audit that is not `OPEN`, or of an audit whose `audit_required` is false, is rejected with `ERR_INVALID_STATE`. A `SUBMITTED` audit may then be resolved, but only when every audit finding of that audit with severity `MATERIAL_WEAKNESS` is in `RESOLVED` status; resolution moves the audit to the terminal `RESOLVED` state. An audit that was not required follows the shorter path: when `audit_required` is false, the `Auditor` resolves it directly from `OPEN` to `RESOLVED` with no submission step. A resolve attempt against an audit in a state from which resolution is not defined yields `ERR_INVALID_STATE`.

Within an audit, the `Auditor` records findings. Creating a finding under a single audit names its `severity` (one of `DEFICIENCY`, `SIGNIFICANT_DEFICIENCY`, or `MATERIAL_WEAKNESS`) and optionally `questioned_cost_cents` (costs questioned by the finding, at least 0, defaulting to 0); the finding records its parent `single_audit_id` and opens in `OPEN`. Findings of an audit may be listed, and the `Auditor` resolves an `OPEN` finding to move it to `RESOLVED`. A `MATERIAL_WEAKNESS` finding that remains `OPEN` blocks its parent audit from resolving and, by extension, blocks award closeout, as described in §3.2.

### 3.9. Validation Ordering Across Endpoints

When several checks could apply to a single request, they are evaluated in a fixed order so that the earliest applicable failure is the one reported. Authentication comes first: a request with missing headers or an unknown role fails with `ERR_UNAUTHENTICATED` before anything else. Authorization comes second: a recognized role that lacks permission for the operation fails with `ERR_FORBIDDEN`. Existence comes third: any path resource or required foreign key that does not exist fails with `ERR_NOT_FOUND`, with path segments resolved left to right. State validity comes fourth: a transition attempted from a state in which it is not defined fails with `ERR_INVALID_STATE`. Optimistic concurrency comes fifth: on the award-mutating writes that take it, a mismatched `expected_award_version` fails with `ERR_STALE_VERSION`.

After those structural checks, the business guards apply in their own order. The cross-entity active-award guard is evaluated next (sixth): disbursing a drawdown and approving or activating a subaward all require the parent award to be `ACTIVE`, failing with `ERR_AWARD_NOT_ACTIVE`. Seventh, the segregation-of-duties guard fires on report certification with `ERR_SEGREGATION_OF_DUTIES`. Eighth, closeout's audit-resolution guard fires with `ERR_AUDIT_UNRESOLVED`. Ninth, closeout's report-and-subaward guard fires with `ERR_CLOSEOUT_PRECONDITIONS`. Tenth, on disbursement the allocation-plan match against the server-derived waterfall fails with `ERR_ALLOCATION_MISMATCH`. Eleventh, the period-ordering check on application submit fails with `ERR_INVALID_PERIOD`. Twelfth, the federal-ceiling guard on disbursement fails with `ERR_CEILING_EXCEEDED`. Thirteenth, the per-fund budget guard on disbursement fails with `ERR_BUDGET_WOULD_EXCEED`. Fourteenth, general request validity — required fields present, correct types, valid enum members, integer-cent fields non-negative (or at least 1 where noted), and contextual requirements such as a present `negotiated_rate` for a `NEGOTIATED` rate and an `allocation_plan` summing to `amount_cents` — fails with `ERR_INVALID_REQUEST`. Fifteenth, the uniqueness guards on financial-report `period_label` and on restricted-fund `priority_order` and `category` fail with `ERR_DUPLICATE`.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Endpoints that create a new resource return HTTP 201; endpoints that modify or transition an existing resource, and all retrieval and listing endpoints, return HTTP 200. The complete request and response semantics for each endpoint — its body fields, its computations, and its side effects — are defined in the §3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /applications | Create a draft NOFO application | GrantWriter |
| GET | /applications | List applications (paginated; filterable by lineage/status) | GrantWriter, AgencyOfficer |
| GET | /applications/{id} | Retrieve one application | GrantWriter, AgencyOfficer |
| POST | /applications/{id}/submit | Submit a DRAFT or REVISIONS_REQUESTED application | GrantWriter |
| POST | /applications/{id}/withdraw | Withdraw a DRAFT application | GrantWriter |
| POST | /applications/{id}/begin-review | Begin review of a SUBMITTED application | AgencyOfficer |
| POST | /applications/{id}/request-revisions | Request revisions on an application under review | AgencyOfficer |
| POST | /applications/{id}/award | Award a reviewed application; create the Award | AgencyOfficer |
| POST | /applications/{id}/reject | Reject a reviewed application | AgencyOfficer |
| GET | /awards | List awards (paginated; filterable by source application/status) | GrantWriter, FinanceOfficer, ProgramManager, AgencyOfficer, Auditor |
| GET | /awards/{id} | Retrieve one award | GrantWriter, FinanceOfficer, ProgramManager, AgencyOfficer, Auditor |
| POST | /awards/{id}/suspend | Suspend an ACTIVE award (OCC-guarded) | AgencyOfficer |
| POST | /awards/{id}/reinstate | Reinstate a SUSPENDED award (OCC-guarded) | AgencyOfficer |
| POST | /awards/{id}/initiate-closeout | Move an ACTIVE award to PENDING_CLOSEOUT (OCC-guarded) | AgencyOfficer |
| POST | /awards/{id}/close | Close a PENDING_CLOSEOUT award (OCC-guarded) | AgencyOfficer |
| POST | /indirect-cost-rates | Set the in-force indirect-cost rate (OCC-guarded) | FinanceOfficer |
| GET | /indirect-cost-rates | List indirect-cost rates (filterable by award/status) | FinanceOfficer, AgencyOfficer, Auditor |
| GET | /indirect-cost-rates/{id} | Retrieve one indirect-cost rate | FinanceOfficer, AgencyOfficer, Auditor |
| POST | /subawards | Create a PROPOSED subaward | ProgramManager |
| GET | /subawards | List subawards (filterable by award/status) | ProgramManager, AgencyOfficer, Auditor |
| GET | /subawards/{id} | Retrieve one subaward | ProgramManager, AgencyOfficer, Auditor |
| POST | /subawards/{id}/approve | Approve a PROPOSED subaward | ProgramManager |
| POST | /subawards/{id}/activate | Activate an APPROVED subaward | ProgramManager |
| POST | /subawards/{id}/terminate | Terminate an APPROVED or ACTIVE subaward | ProgramManager |
| POST | /restricted-funds | Create a restricted budget category fund | FinanceOfficer |
| GET | /restricted-funds | List restricted funds (filterable by award) | FinanceOfficer, AgencyOfficer, Auditor |
| GET | /restricted-funds/{id} | Retrieve one restricted fund | FinanceOfficer, AgencyOfficer, Auditor |
| POST | /drawdowns | Create a REQUESTED drawdown with a proposed allocation plan | FinanceOfficer |
| GET | /drawdowns | List drawdowns (filterable by award/status) | FinanceOfficer, AgencyOfficer, Auditor |
| GET | /drawdowns/{id} | Retrieve one drawdown | FinanceOfficer, AgencyOfficer, Auditor |
| GET | /drawdowns/{id}/allocations | List allocation lines produced by a disbursed drawdown | FinanceOfficer, AgencyOfficer, Auditor |
| GET | /restricted-funds/{id}/allocations | List allocation lines posted to a restricted fund | FinanceOfficer, AgencyOfficer, Auditor |
| POST | /drawdowns/{id}/disburse | Disburse a REQUESTED drawdown; post the waterfall | FinanceOfficer |
| POST | /drawdowns/{id}/return | Return a DISBURSED drawdown; reverse allocations | FinanceOfficer |
| POST | /financial-reports | Create a DRAFT Federal Financial Report | FinanceOfficer |
| GET | /financial-reports | List financial reports (filterable by award/status) | FinanceOfficer, AgencyOfficer, Auditor |
| GET | /financial-reports/{id} | Retrieve one financial report | FinanceOfficer, AgencyOfficer, Auditor |
| POST | /financial-reports/{id}/certify | Certify (submit) a DRAFT report | FinanceOfficer |
| POST | /financial-reports/{id}/accept | Accept a SUBMITTED report; run computations and ledger update | AgencyOfficer |
| POST | /financial-reports/{id}/reject | Reject a SUBMITTED report | AgencyOfficer |
| POST | /financial-reports/{id}/revise | Return a REJECTED report to DRAFT | FinanceOfficer |
| POST | /progress-reports | Submit a progress/performance narrative | GrantWriter |
| GET | /progress-reports | List progress reports (filterable by award/status) | GrantWriter, ProgramManager, AgencyOfficer |
| GET | /progress-reports/{id} | Retrieve one progress report | GrantWriter, ProgramManager, AgencyOfficer |
| POST | /progress-reports/{id}/accept | Accept a SUBMITTED progress report | ProgramManager |
| POST | /progress-reports/{id}/return | Return a SUBMITTED progress report for rework | ProgramManager |
| POST | /progress-reports/{id}/resubmit | Resubmit a RETURNED progress report | GrantWriter |
| POST | /single-audits | Create a Single Audit; compute audit_required | Auditor |
| GET | /single-audits | List single audits (filterable by award/status) | Auditor, AgencyOfficer |
| GET | /single-audits/{id} | Retrieve one single audit | Auditor, AgencyOfficer |
| POST | /single-audits/{id}/submit | Submit an OPEN required audit | Auditor |
| POST | /single-audits/{id}/resolve | Resolve an audit (from SUBMITTED or directly from OPEN) | Auditor |
| POST | /single-audits/{id}/findings | Record an audit finding | Auditor |
| GET | /single-audits/{id}/findings | List findings for an audit | Auditor, AgencyOfficer |
| POST | /audit-findings/{id}/resolve | Resolve an OPEN finding | Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_AWARD_NOT_ACTIVE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_AUDIT_UNRESOLVED | 409 |
| ERR_CLOSEOUT_PRECONDITIONS | 409 |
| ERR_ALLOCATION_MISMATCH | 422 |
| ERR_INVALID_PERIOD | 422 |
| ERR_CEILING_EXCEEDED | 409 |
| ERR_BUDGET_WOULD_EXCEED | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE | 409 |
