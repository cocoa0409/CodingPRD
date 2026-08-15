# School District Budget & Bond/Levy Election API — Product Requirements Document

## 1. Introduction

A public school district's fiscal calendar leaves no room for improvisation: the annual budget must be built fund by fund from enrollment projections, staffing must follow position-control formulas tied to projected pupils, the operating levy is capped by property-tax extension limitation law, a public hearing must be noticed and held before the board may adopt, and every dollar of bonded construction must trace back to a ballot question the voters actually passed. This document specifies the API through which the district business office administers that entire cycle — budget development by fund and enrollment projection, staffing allocation and position control, revenue estimation with its state-aid and local-levy components, the public hearing and adoption deadline, the bond project list against the legal debt-capacity limit, the election calendar with ballot-language certification and campaign restrictions, bond sales, and project accounting with capital-plan amendments.

The API is mounted under `/district` and serves six segregated roles, from the analyst who drafts the numbers to the treasurer who sells the bonds and disburses the proceeds. Because the domain is deadline-driven, every calendar rule in the system evaluates against a server-side logical clock rather than wall-clock time, so notice windows, adoption timing, certification deadlines, and sale dates behave deterministically. Monetary and tax-rate arithmetic follow pinned rounding rules, and the two creation flows that supersede or consume shared aggregates are guarded by optimistic concurrency, so a stale view of a fiscal year or a bond proposal can never silently overwrite a newer one.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, formats, and guarantees that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their capacity. The system recognizes exactly six roles: `BudgetAnalyst`, `BusinessManager`, `BoardClerk`, `Superintendent`, `DistrictTreasurer`, and `Auditor`. A request missing either header, or presenting a role outside these six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). An authenticated role attempting an operation its role is not authorized for is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles divide the work along segregation-of-duties lines:

- `BudgetAnalyst` — the business-office analyst: drafts enrollment projections, budget versions, appropriation lines and transfers, staffing allocations, position slots, and capital-plan amendments.
- `BusinessManager` — the chief business official: creates, opens, and closes fiscal years; certifies enrollment projections; computes revenue estimates and tax rates; reviews project expenditures.
- `BoardClerk` — secretary to the board and keeper of the official record: proposes, returns, and adopts budget versions; schedules, holds, and cancels public hearings; schedules elections and canvasses them; drafts bond proposals and their project lists; drafts and certifies ballot measures; issues district publications.
- `Superintendent` — hiring and construction authority: fills, vacates, and eliminates positions; activates, completes, and cancels bond projects; approves or rejects capital-plan amendments.
- `DistrictTreasurer` — plans, closes, and cancels bond sales; posts, disburses, and voids project expenditures.
- `Auditor` — external read-only access: every retrieval endpoint, with no mutation rights.

All six roles may call every retrieval endpoint and the test-driving clock capability; mutation rights are enumerated per endpoint in §4.

For each of the six roles — `BudgetAnalyst`, `BusinessManager`, `BoardClerk`, `Superintendent`, `DistrictTreasurer`, and `Auditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on designated audit fields — `drafted_by_user_id` and `certified_by_user_id` on a ballot measure, `published_by_user_id` on a district publication, and `submitted_by_user_id` on a capital-plan amendment — and the segregation-of-duties rules compare the `X-User-ID` values supplied by the two operators of a segregated pair; the server never compares `X-User-ID` to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its items ordered by `created_at` ascending — a stable creation order, with no id-based ordering anywhere in the API.

Paginated list responses carry four pagination fields in the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Audit Trail

Every resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits (for example `2026-08-01T00:00:00.000Z`). All resources except district publications additionally carry `updated_at`, refreshed upon any change to the resource's properties, and `version`, a system-managed integer that increments with every modification to the resource. A `DistrictPublication` is an append-only record: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent.

Whenever a workflow mutates an entity — whether at an operator's explicit request or as one link of a cascade — the mutation refreshes that entity's `updated_at`, and where the workflow specifies it, increments the entity's `version`. Derived aggregates, such as a fiscal year's `authorized_fte_total` or a bond project's `spent_amount`, are recomputed by the server at the moment any underlying fact changes; clients never write them.

### 2.5. The Logical Clock and Calendar Semantics

All deadline and window arithmetic in the system evaluates against a server-side logical clock, never against wall-clock time. Before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. An operator-facing capability, available to all six roles, sets the clock by posting `to_iso8601` to `/_clock/set_current_utc`; the response echoes the new clock value as `current_utc`, and from that point on every date-derived rule — notice windows, adoption timing, certification deadlines, campaign windows, canvass timing, sale effectiveness — evaluates against the new clock value.

Date-valued fields — `hearing_date`, `election_date`, `sale_date`, `construction_start`, `construction_end`, `start_date`, and `end_date` — are ISO calendar dates in YYYY-MM-DD form. All calendar arithmetic is performed at whole-day granularity in UTC: throughout this document, "today" means the calendar date of the server's logical clock, and phrasings such as "at least ten days after" count whole calendar days.

### 2.6. Nested Resource Retrieval

Requests that name nested resources are validated strictly left to right along the path — the fiscal year first, then the nested resource beneath it. The request is rejected immediately with the 404 that corresponds to the first path identifier that does not resolve: `ERR_FISCAL_YEAR_NOT_FOUND`, `ERR_ENROLLMENT_PROJECTION_NOT_FOUND`, `ERR_BUDGET_VERSION_NOT_FOUND`, `ERR_STAFFING_ALLOCATION_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`, `ERR_REVENUE_ESTIMATE_NOT_FOUND`, `ERR_PUBLIC_HEARING_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_BOND_PROPOSAL_NOT_FOUND`, `ERR_BOND_PROJECT_NOT_FOUND`, `ERR_BALLOT_MEASURE_NOT_FOUND`, `ERR_BOND_SALE_NOT_FOUND`, `ERR_PROJECT_EXPENDITURE_NOT_FOUND`, or `ERR_CAPITAL_PLAN_AMENDMENT_NOT_FOUND`. A request referencing a budget line fails with `ERR_BUDGET_LINE_NOT_FOUND` only when a transfer's body names an unknown line, since budget lines are never addressed by path.

Identifiers supplied inside request bodies are checked separately and later in the pipeline (§2.9): an unknown `enrollment_projection_id` on a staffing allocation surfaces `ERR_ENROLLMENT_PROJECTION_NOT_FOUND`; an unknown `bond_proposal_id` on a ballot-measure draft surfaces `ERR_BOND_PROPOSAL_NOT_FOUND`; an unknown `from_line_id` or `to_line_id` on a transfer surfaces `ERR_BUDGET_LINE_NOT_FOUND`; an unknown `ballot_measure_id` inside a canvass `results` entry surfaces `ERR_BALLOT_MEASURE_NOT_FOUND`; and an unknown project identifier inside an amendment's `adjustments` surfaces `ERR_BOND_PROJECT_NOT_FOUND`.

### 2.7. Money, Tax Rates, and Rounding Discipline

Money fields are decimal numbers, and all money arithmetic rounds half-up to exactly 2 decimal places. Tax rates round half-up to 4 decimal places, per fund, before any summation: the district computes the operating rate and the debt-service rate independently, rounds each one, and only then forms their sum — the sum itself is never re-rounded. Enrollment and vote figures are integers, and weighted pupil counts round half-up to a whole pupil. Staffing FTE values move in half-step (0.5) increments.

### 2.8. Optimistic Concurrency Control on Parent Aggregates

Two creation endpoints guard their parent aggregate with optimistic concurrency control; no other endpoint accepts a version field.

- Creating a budget version against a fiscal year requires a non-optional `expected_fiscal_year_version` carrying the fiscal year's `version` as the client last observed it. Because a successful create legitimately supersedes the currently adopted version and advances the fiscal year's `version`, a create whose `expected_fiscal_year_version` no longer matches the fiscal year's current `version` is operating on a stale view of the year and is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a bond sale against a bond proposal requires a non-optional `expected_bond_proposal_version` carrying the proposal's `version` as the client last observed it. Multiple series sales against one passed proposal are legitimate, and each planned sale advances the proposal's `version`, so a create whose `expected_bond_proposal_version` no longer matches the proposal's current `version` is operating on a stale view of the proposal's remaining authorization and is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. The Validation Pipeline

Every mutation request passes a fixed validation pipeline, and the earliest failing stage determines the error returned — a request that would fail several checks surfaces the error from the earliest of them:

1. **Authentication** — the two headers are present and the role is one of the six (`ERR_UNAUTHENTICATED`, HTTP 401).
2. **Role authorization** — the acting role appears in the endpoint's authorized role list (`ERR_FORBIDDEN_ROLE`, HTTP 403).
3. **Path existence** — path identifiers resolve, validated left to right (the 404 family of §2.6).
4. **Request-body shape** — required fields present, types correct, enum members valid (`ERR_INVALID_REQUEST`, HTTP 400).
5. **Semantic field values** — amounts positive where required, position `fte` one of 0.5 or 1.0, `allocated_fte` a multiple of 0.5, `construction_end` after `construction_start`, fiscal-year `end_date` after `start_date`, pupil counts non-negative (`ERR_INVALID_FIELD_VALUE`, HTTP 422).
6. **Body-referenced identifiers** — resource identifiers supplied in the request body resolve (§2.6).
7. **Optimistic concurrency** — the `expected_fiscal_year_version` and `expected_bond_proposal_version` tokens of §2.8 (`ERR_STALE_VERSION`, HTTP 412).
8. **State admission** — the target entity's state machine admits the requested transition, and child creation finds its parent in a mutable state (`ERR_INVALID_STATE`, `ERR_FISCAL_YEAR_NOT_OPEN`, `ERR_BUDGET_VERSION_NOT_DRAFT`, `ERR_BUDGET_VERSION_NOT_HEARING_HELD`, `ERR_EXPENDITURE_NOT_REVIEWED`, HTTP 409).
9. **Segregation of duties and prohibited activity** (`ERR_SEGREGATION_OF_DUTIES`, `ERR_PROHIBITED_CAMPAIGN_ACTIVITY`, HTTP 403).
10. **Calendar rules** — the statutory election date, the notice window, the hearing-hold date, adoption timing, the certification deadline, the campaign restriction window, canvass timing, and the sale windows (`ERR_STATUTORY_ELECTION_DATE`, `ERR_NOTICE_WINDOW_TOO_SHORT`, `ERR_HEARING_DATE_NOT_TODAY`, `ERR_ADOPTION_TOO_SOON`, `ERR_ADOPTION_DEADLINE_PASSED`, `ERR_CERTIFICATION_DEADLINE_PASSED`, `ERR_CAMPAIGN_RESTRICTION_WINDOW`, `ERR_CANVASS_BEFORE_ELECTION`, `ERR_AUTHORIZATION_LAPSED`, `ERR_SALE_NOT_YET_EFFECTIVE`, HTTP 409).
11. **Uniqueness and structural constraints** — duplicate grade bands, venue-and-date conflicts, duplicate ballot measures, the ballot word limit, site-window conflicts, duplicate priority ranks, the one-estimate-per-version rule, project-list totals, canvass completeness, and duplicate series labels (`ERR_DUPLICATE_GRADE_BAND`, `ERR_HEARING_VENUE_DATE_CONFLICT`, `ERR_DUPLICATE_BALLOT_MEASURE`, `ERR_SITE_WINDOW_CONFLICT`, `ERR_DUPLICATE_PRIORITY_RANK`, `ERR_REVENUE_ESTIMATE_EXISTS`, `ERR_DUPLICATE_SERIES_LABEL` at HTTP 409; `ERR_BALLOT_LANGUAGE_TOO_LONG`, `ERR_PROJECT_LIST_EXCEEDS_AMOUNT`, and `ERR_CANVASS_INCOMPLETE` at HTTP 422 — the per-error status in §5 is authoritative).
12. **Cross-entity references** — same-fiscal-year rules, transfer pairing, recertification prerequisites, amendment project ownership, activation and completion prerequisites, adoption prerequisites, and the non-empty project list (`ERR_PROJECTIONS_NOT_ALL_CERTIFIED`, `ERR_NO_ADOPTED_BUDGET_VERSION`, `ERR_NO_CLOSED_BOND_SALE`, `ERR_UNREVIEWED_EXPENDITURES_EXIST`, `ERR_NO_REVENUE_ESTIMATE`, `ERR_EMPTY_PROJECT_LIST` at HTTP 409; `ERR_CROSS_FISCAL_YEAR_REFERENCE`, `ERR_TRANSFER_LINE_MISMATCH`, and `ERR_AMENDMENT_PROJECT_MISMATCH` at HTTP 422).
13. **Fiscal guards, always last** — the staffing formula and ceilings, position headroom, the tax-rate cap, budget balance at adoption, bond capacity, sale authorization and proceeds, project budgets, transfer sufficiency, and amendment floors and ceiling (`ERR_ALLOCATION_EXCEEDS_FORMULA`, `ERR_FTE_CEILING_EXCEEDED`, `ERR_POSITION_FTE_EXCEEDED`, `ERR_TAX_RATE_CAP_EXCEEDED`, `ERR_BUDGET_NOT_BALANCED`, `ERR_BOND_CAPACITY_EXCEEDED`, `ERR_SALE_EXCEEDS_REMAINING_AUTHORIZATION`, `ERR_NONPOSITIVE_NET_PROCEEDS`, `ERR_PROJECT_BUDGET_EXCEEDED`, `ERR_INSUFFICIENT_PROCEEDS`, `ERR_TRANSFER_EXCEEDS_LINE`, `ERR_AMENDMENT_BELOW_SPENT`, `ERR_AMENDMENT_EXCEEDS_AUTHORIZATION`, HTTP 422).

### 2.10. Derived Totals and Cascade Consistency

The server keeps a set of derived aggregates continuously reconciled with their underlying facts: a budget version's `total_appropriations`; a fiscal year's `authorized_fte_total` and `open_position_count`; a staffing allocation's `positions_fte_total`, `cost_estimate_projected`, and `cost_estimate_actual`; a bond project's `authorized_amount` and `spent_amount`; and a bond proposal's `remaining_authorization` and `available_proceeds`. Clients never supply these values. Each recomputation is a mutation of the owning entity and marks its `updated_at`.

Two large cascades dominate the lifecycle. The adoption-and-supersede cascade (§3.5) propagates a budget version's adoption downward through its staffing allocations, positions, and budget lines, and retires any previously adopted version of the same fiscal year. The canvass cascade (§3.7) propagates an election's results into its ballot measures, then into the referenced bond proposals, then into the projects those proposals fund. Consistency is immediate: no derived figure is ever left waiting for a later reconciliation pass, and no child is ever left in a state its parent's state contradicts.

## 3. Business Logic & Workflows

### 3.1. Fiscal Year Setup and Enrollment Projection

A `BusinessManager` opens the budget cycle by creating a **fiscal year** with a unique `label` (for example, FY2028), its `start_date` and `end_date`, the current and prior equalized assessed valuations `eav_current` and `eav_prior`, the `prior_year_extension` that anchors the tax-cap base, the `outstanding_debt_principal` already on the books, and the `fte_ceiling` that position control will enforce. The `end_date` must fall after the `start_date`, and a violation is rejected with `ERR_INVALID_FIELD_VALUE`. A new fiscal year begins in `DRAFT` status, with `authorized_fte_total` and `open_position_count` both zero.

While the year is `DRAFT` it accepts no children. Opening the year — `DRAFT` → `OPEN`, an action that increments the fiscal year's `version` — admits the creation of enrollment projections, budget versions, and bond proposals; attempting any of these against a year that is not `OPEN` fails with `ERR_FISCAL_YEAR_NOT_OPEN`. Closing the year moves it `OPEN` → `CLOSED`, requires that some budget version of the year has reached `ADOPTED` (otherwise `ERR_NO_ADOPTED_BUDGET_VERSION`), sweeps every hearing of every version of the year that is still `NOTICE_PUBLISHED` to `CANCELLED`, and increments the fiscal year's `version`. The fiscal year list accepts optional `label` and `status` filters alongside the standard pagination parameters.

With the year open, a `BudgetAnalyst` files one **enrollment projection** per grade band. The band — `grade_band`, one of `ELEMENTARY`, `MIDDLE`, or `HIGH` — is unique within the fiscal year: a second projection for a band already filed in that year is rejected with `ERR_DUPLICATE_GRADE_BAND`. The analyst supplies `projected_pupils`, a non-negative integer, and the server derives `weighted_pupils_projected` by multiplying the projected count by the band's weight — 1.00 for `ELEMENTARY`, 1.05 for `MIDDLE`, and 1.15 for `HIGH` — and rounding half-up to a whole pupil. Each projection starts `PROVISIONAL`, and both `actual_pupils` and `weighted_pupils_certified` remain null until certification. The projection's `fiscal_year_id` is set from the path at creation.

Certification belongs to the `BusinessManager`, who supplies the certified `actual_pupils` count; a negative or absent count is rejected with `ERR_INVALID_FIELD_VALUE`. Certification records the actuals, derives `weighted_pupils_certified` from the actual count using the same band weight and the same half-up rounding to a whole pupil, retains the provisional weighted figure alongside it, moves the projection `PROVISIONAL` → `CERTIFIED`, and increments the projection's `version`.

### 3.2. Drafting the Budget: Versions, Appropriation Lines, and Transfers

A `BudgetAnalyst` creates a **budget version** against an open fiscal year. The create carries the concurrency token `expected_fiscal_year_version` described in §2.8, and a stale token is refused with `ERR_STALE_VERSION`. The server assigns each version a `version_label` — v1, v2, and so on per fiscal year, in creation order — and the new version starts in `DRAFT` with `hearing_held_date` and `adopted_at` both null. Creation is itself a supersession event: if another version of the same fiscal year is currently `ADOPTED`, it is retired to `SUPERSEDED` with the full supersede cascade of §3.5, and the fiscal year's `version` increments.

Inside a `DRAFT` version the analyst adds **budget lines**, each carrying a `fund_code` — `EDUCATION`, `OPERATIONS`, `TRANSPORTATION`, `DEBT_SERVICE`, or `CAPITAL_PROJECTS` — plus a `function_code` classification, an `object_code` classification, a `cost_center` label for the school or department, and an `appropriation_amount` that must be positive (otherwise `ERR_INVALID_FIELD_VALUE`). Lines may only be added while the version is `DRAFT`; against a version in any other state the write fails with `ERR_BUDGET_VERSION_NOT_DRAFT`. The version's `total_appropriations` is the running sum of the `appropriation_amount` over all of its lines, recomputed as lines are added or moved, and each line's `budget_version_id` ties it back to its version.

Appropriations may be reshaped without changing the total by a **transfer** between two lines of the same version, naming `from_line_id`, `to_line_id`, and an `amount`. Like line creation, a transfer is a draft-phase act: against a budget version in any state other than `DRAFT` it fails with `ERR_BUDGET_VERSION_NOT_DRAFT`. The two identifiers must reference two distinct lines of this budget version — a pair drawn from different versions, or a line paired with itself, fails with `ERR_TRANSFER_LINE_MISMATCH` — and the `amount` may not exceed the source line's current `appropriation_amount`; when it does, the transfer fails with `ERR_TRANSFER_EXCEEDS_LINE`. A transfer subtracts the amount from the source line's `appropriation_amount` and adds it to the destination line's, increments both lines' `version`, and leaves the version's `total_appropriations` unchanged. The response echoes `from_line_id`, `to_line_id`, and `amount`, and reports the resulting balances as `from_line_appropriation` and `to_line_appropriation`.

When the draft is ready for the board, a `BoardClerk` proposes it — `DRAFT` → `PROPOSED`, incrementing the version's `version`. Returning to draft remains available to the clerk from either later pre-adoption state: from `PROPOSED`, the return sweeps every still-`NOTICE_PUBLISHED` hearing of the version to `CANCELLED`; from `HEARING_HELD`, it additionally clears `hearing_held_date` back to null. Both returns land in `DRAFT` and increment the version's `version`.

### 3.3. Staffing Allocations and Position Control

Staffing begins with a `BudgetAnalyst` creating a **staffing allocation** on a `DRAFT` budget version, naming the `enrollment_projection_id` it is computed from, the `grade_band` it covers, and the board's `allocated_fte`. The referenced projection must exist, and it must belong to the same fiscal year as the budget version — a cross-year reference fails with `ERR_CROSS_FISCAL_YEAR_REFERENCE`. The allocation's `grade_band` must equal the referenced projection's band, and the band is unique within the version: a second allocation for a band already covered in the same version is rejected with `ERR_DUPLICATE_GRADE_BAND`. Per the pipeline, these checks run after body-reference existence and the `DRAFT`-state gate, and before the fiscal guards below. The allocation's `budget_version_id` is set from the path at creation.

The **formula FTE floor** derives `required_fte` from the referenced projection's current pupil count — the certified `actual_pupils` when the projection is `CERTIFIED`, otherwise its `projected_pupils`. A band with fewer than 40 pupils requires exactly 1.0 FTE. Otherwise the requirement is the pupil count divided by the band's staffing ratio — 20 for `ELEMENTARY`, 22 for `MIDDLE`, 25 for `HIGH` — with the quotient multiplied by two, rounded up to the next whole number, and divided by two, yielding half-FTE granularity. The supplied `allocated_fte` must be positive and a multiple of 0.5 (otherwise `ERR_INVALID_FIELD_VALUE`), and it may not exceed `required_fte`; an allocation above the formula fails with `ERR_ALLOCATION_EXCEEDS_FORMULA`.

Position control adds a district-wide ceiling. The sum of `allocated_fte` over all staffing allocations of the same budget version, including the one being created, may not exceed the fiscal year's `fte_ceiling`. A sum that lands exactly on the ceiling is permitted; a strictly greater sum fails with `ERR_FTE_CEILING_EXCEEDED`.

Every allocation maintains two cost estimates, both rounded half-up to two decimal places. `cost_estimate_projected` is formula-driven: `allocated_fte` multiplied by the district average salary of 62,000 and by 1.34, loading 34 percent for benefits. `cost_estimate_actual` is position-driven: the sum over the allocation's positions that are not `ELIMINATED` of each position's salary basis — its `incumbent_salary` when the position is `FILLED`, otherwise its `base_salary` — multiplied by the position's `fte` and by the same 1.34 load. The two variants diverge whenever slot salaries depart from the district average, and with no positions yet the actual estimate starts at zero.

The analyst then slots **positions** under an allocation, each with a `title`, an `fte` of exactly 0.5 or 1.0 (any other value is `ERR_INVALID_FIELD_VALUE`), and a `base_salary` greater than zero. Headroom is enforced at creation: the new position's `fte` may not exceed the allocation's `allocated_fte` minus the summed `fte` of its positions that are not `ELIMINATED`; landing exactly on the headroom is permitted, and any excess is rejected with `ERR_POSITION_FTE_EXCEEDED`. A position created while its allocation is `DRAFT` starts `PROPOSED`; one created under an already-`AUTHORIZED` allocation starts `OPEN`, and the fiscal year's `open_position_count` is recomputed. Either way, the allocation's `positions_fte_total` — the summed `fte` of its non-`ELIMINATED` positions — and its `cost_estimate_actual` are recomputed, and the position's `staffing_allocation_id` ties it to its allocation. A position's `incumbent_salary` stays null until the slot is filled.

Hiring actions belong to the `Superintendent`. Filling an `OPEN` position moves it to `FILLED` and records the supplied `incumbent_salary`, which must be positive (otherwise `ERR_INVALID_FIELD_VALUE`); the fiscal year's `open_position_count` and the allocation's `cost_estimate_actual` are recomputed, and the position's `version` increments. Vacating reverses the act — `FILLED` back to `OPEN`, `incumbent_salary` cleared to null, the same recomputations, and a version increment. Elimination removes a `PROPOSED` or `OPEN` position to `ELIMINATED`, recomputing the allocation's `positions_fte_total` and `cost_estimate_actual` and, when the eliminated slot was `OPEN`, the fiscal year's `open_position_count`; the operator-driven elimination increments the position's `version`. An operator may not eliminate a `FILLED` position — the attempt is rejected with `ERR_INVALID_STATE` — although the supersede cascade of §3.5 eliminates positions in any of the three live states.

### 3.4. Revenue Estimation, the PTELL Cap, and Tax Rates

A `BusinessManager` attaches a **revenue estimate** to a budget version — at most one per version, with a second attempt failing as `ERR_REVENUE_ESTIMATE_EXISTS` — supplying the `operating_levy_request` (which must be positive), the `debt_service_levy` and `other_revenue` (both non-negative), and the `cpi_rate` used by the tax cap, expressed as a decimal such as 0.034. The estimate's `budget_version_id` is set from the path at creation.

The PTELL cap evaluation runs in a pinned order, each step consuming only earlier steps. First, the raw request is taken from `operating_levy_request`. Second, the cap is formed as the fiscal year's `prior_year_extension` grown by one plus the lesser of `cpi_rate` and 5 percent. Third, `capped_operating_levy` is set to the lesser of the raw request and that cap. Fourth, the operating rate is computed from the capped levy — never from the raw request — by dividing the capped levy by the applicable EAV basis, multiplying by 100, and rounding half-up to four decimal places; if that rounded rate exceeds 1.8400, the estimate is rejected outright with `ERR_TAX_RATE_CAP_EXCEEDED`. Fifth, `total_levy` is the `capped_operating_levy` plus the `debt_service_levy`, which sits outside the PTELL cap.

At creation the estimate is the provisional variant. State aid is the greater of zero and the difference between the foundation amount — 7,600 per weighted pupil, multiplied by the summed `weighted_pupils_projected` over every enrollment projection of the fiscal year — and 2.3 percent of the prior-year EAV; the `eav_basis` field reads `PRIOR`, and `state_aid` is rounded half-up to two decimal places. The per-fund rates are then struck independently: `operating_rate` from the capped levy and `debt_service_rate` from the debt-service levy, each divided by the prior-year EAV, multiplied by 100, and rounded half-up to four decimal places. `total_tax_rate` is the exact sum of the two already-rounded per-fund rates and is never re-rounded; striking a single rate from the summed levies is not a permitted equivalent. `total_revenue` closes the estimate as `state_aid` plus `total_levy` plus `other_revenue`, rounded half-up to two decimal places.

Once every enrollment projection of the fiscal year has been certified, the `BusinessManager` may **recertify** the estimate; an attempt while any projection remains uncertified fails with `ERR_PROJECTIONS_NOT_ALL_CERTIFIED`. Recertification freezes the current provisional figures into `state_aid_provisional` and `total_revenue_provisional`, then recomputes the authoritative fields on the certified variant: state aid now uses the summed `weighted_pupils_certified` over the year's projections against the current-year EAV, `eav_basis` flips to `CURRENT`, the per-fund rates and `total_tax_rate` are restruck on that basis, and the operating-rate cap of 1.8400 is re-checked against the new rate, failing with `ERR_TAX_RATE_CAP_EXCEEDED` when exceeded. The estimate moves `PROVISIONAL` → `RECERTIFIED` with its `version` incremented.

### 3.5. Public Hearings and Budget Adoption

A `BoardClerk` schedules a **public hearing** for a budget version in `PROPOSED` — against a version in any other state the request fails with `ERR_INVALID_STATE` — supplying the `venue` and the `hearing_date`. The act of scheduling publishes notice: `notice_publication_date` is set to the logical clock's calendar date at creation, and the hearing begins in `NOTICE_PUBLISHED` with its `budget_version_id` set from the path. Statute requires at least ten days of notice, so the `hearing_date` must fall no earlier than ten days after the `notice_publication_date`; the tenth day itself is acceptable, and anything shorter fails with `ERR_NOTICE_WINDOW_TOO_SHORT`. The calendar is venue-exclusive across the whole district: no two hearings in `NOTICE_PUBLISHED` or `HELD` status may share the same `venue` on the same calendar date, regardless of which budget version they belong to — day-equality semantics with no buffer — and a conflicting request is rejected with `ERR_HEARING_VENUE_DATE_CONFLICT`.

Holding the hearing is a same-day act, and its two gates run in pipeline order: the owning budget version must still be `PROPOSED`, failing otherwise with `ERR_INVALID_STATE`, and the clock's calendar date must equal the `hearing_date` exactly, failing otherwise with `ERR_HEARING_DATE_NOT_TODAY`. A held hearing moves `NOTICE_PUBLISHED` → `HELD`, increments the hearing's `version`, and pulls its budget version from `PROPOSED` to `HEARING_HELD`, stamping the version's `hearing_held_date` with the hearing's `hearing_date` and incrementing the version's `version`. A clerk may also cancel a published hearing outright — `NOTICE_PUBLISHED` → `CANCELLED` — and the clerk-driven cancellation increments the hearing's `version`; the automatic cancellations fired by a return-to-draft (§3.2) or by a fiscal-year close (§3.1) carry no such increment.

Adoption is the budget's point of no return, and its guards run in pipeline order. The version must be `HEARING_HELD`, failing with `ERR_BUDGET_VERSION_NOT_HEARING_HELD` otherwise. The calendar then imposes both ends of the window: adoption is permitted no earlier than seven days after the `hearing_held_date` — sooner fails with `ERR_ADOPTION_TOO_SOON` — and it must complete strictly before the fiscal year's `start_date`, with `ERR_ADOPTION_DEADLINE_PASSED` on or after that first day. A revenue estimate must exist for the version, failing with `ERR_NO_REVENUE_ESTIMATE` when absent. Finally the budget must balance: the version's `total_appropriations` may not exceed the estimate's current authoritative `total_revenue`, and an unbalanced adoption is rejected with `ERR_BUDGET_NOT_BALANCED`.

A successful adoption moves the version `HEARING_HELD` → `ADOPTED`, stamps `adopted_at` with the current timestamp, and fires the adoption cascade downward through the version. Every staffing allocation of the version moves `DRAFT` → `AUTHORIZED`; each such authorization opens its positions, moving every `PROPOSED` position of the allocation to `OPEN`; and the fiscal year's `authorized_fte_total` — the summed `allocated_fte` over the year's `AUTHORIZED` allocations — together with its `open_position_count` are recomputed against the new reality. In parallel, every budget line of the version moves `DRAFT` → `ADOPTED`. If any other version of the same fiscal year was `ADOPTED`, it is retired to `SUPERSEDED` with the supersede cascade below, and the newly adopted version's `version` increments.

Supersession unwinds everything adoption built. Whether triggered by the adoption of a successor or by the creation of a fresh version (§3.2), the retired version's staffing allocations move `AUTHORIZED` → `SUPERSEDED`; each superseded allocation eliminates its positions, moving every position in `PROPOSED`, `OPEN`, or `FILLED` to `ELIMINATED`; and the fiscal year's `authorized_fte_total` and `open_position_count`, along with each allocation's `positions_fte_total`, are recomputed. The version's budget lines move `ADOPTED` → `SUPERSEDED`, and the retired version's `version` increments. `SUPERSEDED` is terminal for a budget version, as it is for its lines and allocations.

### 3.6. Bond Proposals and the Project List

When the board wants voter authority for capital work, a `BoardClerk` drafts a **bond proposal** against an open fiscal year, supplying a short `question_title`, the statutory `purpose` statement, and the `total_amount` of voter-authorized par being requested, which must be positive. The proposal starts in `DRAFT`, its `remaining_authorization` initialized to the full `total_amount`, its `available_proceeds` at zero, and `passed_at` null; its `fiscal_year_id` is set from the path.

Before a proposal may be referred to the ballot, the board approves it. Approval requires at least one project of the proposal still in `PLANNED` status — an empty list fails with `ERR_EMPTY_PROJECT_LIST` — and it enforces the district's legal debt capacity: the year's `outstanding_debt_principal`, plus the summed `remaining_authorization` of the fiscal year's *other* proposals in `BOARD_APPROVED`, `REFERRED`, or `PASSED` status (proposals in `DRAFT` or `FAILED` consume nothing), plus this proposal's `total_amount`, may not exceed 6.9 percent of the year's `eav_current`. Landing exactly on the limit is permitted; exceeding it fails with `ERR_BOND_CAPACITY_EXCEEDED`. Approval moves the proposal `DRAFT` → `BOARD_APPROVED` and increments its `version`.

The clerk builds the **project list** while the proposal is in `DRAFT`. Each **bond project** carries a `name`, a `site_code` identifying the site for construction-window conflict checks, an `estimated_cost` that must be positive, a construction window from `construction_start` (inclusive) to `construction_end` (exclusive, and necessarily after the start, otherwise `ERR_INVALID_FIELD_VALUE`), and a `priority_rank` unique among the proposal's non-`CANCELLED` projects — a reused rank fails with `ERR_DUPLICATE_PRIORITY_RANK`. The summed `estimated_cost` over the proposal's non-`CANCELLED` projects may never exceed the proposal's `total_amount`; an addition that would push the list over fails with `ERR_PROJECT_LIST_EXCEEDS_AMOUNT`. A new project starts `PLANNED`, with `authorized_amount` and `spent_amount` both zero and its `bond_proposal_id` set from the path.

Construction windows at the same site may not collide. Windows are half-open — the start day is in, the end day is out — and a new project is checked against every other project sharing its `site_code` that is in `PLANNED`, `AUTHORIZED`, or `IN_PROGRESS` (cancelled and completed projects are ignored). The new project conflicts when its window overlaps the other's window, or when the whole-day gap separating the two windows is strictly less than 14 days; either condition rejects the create with `ERR_SITE_WINDOW_CONFLICT`. A gap of exactly 14 days is permitted, while windows that merely touch — one's end day equal to the other's start day — have a gap of zero and are rejected, the buffer dominating the adjacency.

Passage and failure arrive through the election canvass of §3.7: a passed proposal moves `REFERRED` → `PASSED`, stamps `passed_at`, and authorizes its projects — each `PLANNED` project moving to `AUTHORIZED` with its `authorized_amount` set to its `estimated_cost` — while a failed one moves `REFERRED` → `FAILED`. A failed proposal is not dead: the clerk may return it `FAILED` → `DRAFT` for revision, which increments the proposal's `version` and reopens the `total_amount` and the project list to further drafting; the capacity check runs again at the next board approval.

### 3.7. Elections, Ballot Language, and the Canvass

A `BoardClerk` schedules an **election** by supplying the `election_date` and the `election_type`, one of `REGULAR` or `SPECIAL`. Statute confines election days to the first Tuesday of March, June, or November of any year — computed by taking the first day of the month and advancing it to the first Tuesday — and any other date is rejected with `ERR_STATUTORY_ELECTION_DATE`. A new election starts `SCHEDULED`, with `canvassed_at` null until the canvass.

To place a proposal before the voters, the clerk drafts a **ballot measure** on a scheduled election, supplying the `bond_proposal_id` of the proposal being referred — which must be `BOARD_APPROVED` — and the full `ballot_language` of the question. A proposal may appear at most once per election: a second measure for the same proposal on the same election fails with `ERR_DUPLICATE_BALLOT_MEASURE`. At drafting, the server computes the `word_count` as the number of whitespace-separated tokens in the `ballot_language`, records the drafting operator in `drafted_by_user_id`, and starts the measure in `LANGUAGE_DRAFT` with `certified_by_user_id`, `yes_votes`, and `no_votes` all null. The measure's `election_id` is set from the path.

Certification formalizes the language, and its three gates run in pipeline order. Segregation of duties comes first: the certifying `BoardClerk`'s `X-User-ID` must differ from `drafted_by_user_id`, and self-certification is refused with `ERR_SEGREGATION_OF_DUTIES`. The calendar comes next: certification is permitted on any day up to and including the day 61 days before the `election_date`, and a later attempt fails with `ERR_CERTIFICATION_DEADLINE_PASSED`. Finally, the `word_count` must not exceed 200 words, with an over-long question rejected as `ERR_BALLOT_LANGUAGE_TOO_LONG`. Certification records the certifier in `certified_by_user_id`, moves the measure `LANGUAGE_DRAFT` → `LANGUAGE_CERTIFIED`, pulls the referenced proposal from `BOARD_APPROVED` to `REFERRED`, and increments the measure's `version`.

While a measure is before the voters, district communications are restricted. The clerk may issue a **district publication** about a measure with a `publication_type` of `FACTUAL` or `PROMOTIONAL` and the publication `content`. Advocacy is never permitted: a `PROMOTIONAL` publication is always rejected with `ERR_PROHIBITED_CAMPAIGN_ACTIVITY`, regardless of the calendar. Neutral information has its own window: a `FACTUAL` publication about a `LANGUAGE_CERTIFIED` measure is rejected with `ERR_CAMPAIGN_RESTRICTION_WINDOW` whenever today falls inside the campaign restriction window — the thirty days before the election's `election_date` through election day itself, inclusive. A publication that passes these gates is recorded immediately in `PUBLISHED` status, stamped with the issuing operator's `published_by_user_id` and tied to its measure by `ballot_measure_id`; publications are append-only and are never edited or withdrawn.

After election day, the clerk **canvasses** the election. The canvass is permitted only when today is strictly later than the `election_date` — an attempt on or before election day fails with `ERR_CANVASS_BEFORE_ELECTION` — and the supplied `results` must cover every `LANGUAGE_CERTIFIED` measure of the election exactly once, with any gap, extra, or duplicate entry failing as `ERR_CANVASS_INCOMPLETE`; measures still in `LANGUAGE_DRAFT` are ignored by the canvass and remain `LANGUAGE_DRAFT`. Each entry identifies its measure by `ballot_measure_id` and carries the tallies recorded into the measure's `yes_votes` and `no_votes`.

The canvass then cascades. Each covered measure is decided by strict plurality: `PASSED` when its `yes_votes` are strictly greater than its `no_votes`, otherwise `FAILED` — a tie fails the measure — with the votes recorded and the measure's `version` incremented in either case. A passing measure pulls its proposal from `REFERRED` to `PASSED` and stamps `passed_at` with the current timestamp; a failing measure pulls its proposal from `REFERRED` to `FAILED`. Each newly passed proposal then authorizes its project list, moving every `PLANNED` project to `AUTHORIZED` with `authorized_amount` set to the project's `estimated_cost`. The election itself moves `SCHEDULED` → `CANVASSED`, stamps `canvassed_at`, increments its `version`, and the response reports the number of measures decided as `canvassed_count`.

### 3.8. Bond Sales and the Proceeds Ledger

Once a proposal has `PASSED`, the `DistrictTreasurer` may plan a **bond sale** series against it — a proposal in any other status rejects the create with `ERR_INVALID_STATE`. The create carries the concurrency token `expected_bond_proposal_version` of §2.8, refused with `ERR_STALE_VERSION` when stale, and supplies a `series_label` (for example, 2027-A) that is unique among the proposal's non-`CANCELLED` sales — a reused label fails with `ERR_DUPLICATE_SERIES_LABEL` — along with the `par_amount` (positive), the `premium` and `issuance_costs` (both non-negative), and the scheduled `sale_date`. In pipeline order, the shape and semantic checks run first, then the stale-version gate, then the `PASSED` state gate, then the calendar and uniqueness rules, and only then the fiscal guards.

Two fiscal guards bind the sale. The `par_amount` may not exceed the proposal's `remaining_authorization` — the `total_amount` less the summed `par_amount` over the proposal's sales in `PLANNED` or `CLOSED` status, with cancelled sales releasing their reservation — and selling for exactly the remaining authorization is permitted while anything more fails with `ERR_SALE_EXCEEDS_REMAINING_AUTHORIZATION`. The economics must also be real: `net_proceeds`, computed at creation as the `par_amount` plus the `premium` minus the `issuance_costs`, must be greater than zero, and a non-positive result fails with `ERR_NONPOSITIVE_NET_PROCEEDS`. Statute also bounds the calendar: the `sale_date` may be no later than 36 months after the proposal's `passed_at`, and a later sale is rejected with `ERR_AUTHORIZATION_LAPSED`. A planned sale starts in `PLANNED`, its creation reduces the proposal's `remaining_authorization`, and — because each sale consumes shared authorization — increments the proposal's `version`.

Closing the sale is permitted only on or after its `sale_date`; an early close fails with `ERR_SALE_NOT_YET_EFFECTIVE`. A close moves the sale `PLANNED` → `CLOSED` and settles the ledgers: the proposal's `available_proceeds` — the summed `net_proceeds` over its `CLOSED` sales, less the summed `amount` of all non-`VOIDED` expenditures across the proposal's projects — grows by the sale's `net_proceeds`, the fiscal year's `outstanding_debt_principal` grows by the `par_amount`, the proposal's `remaining_authorization` is recomputed, and the sale's `version` increments. Cancelling a planned sale moves it `PLANNED` → `CANCELLED`, releases its reservation by recomputing `remaining_authorization`, and increments its `version`.

### 3.9. Project Execution: Expenditures, Retainage, and Capital-Plan Amendments

With bond proceeds in hand, the `Superintendent` activates a project — `AUTHORIZED` → `IN_PROGRESS` — which requires at least one `CLOSED` bond sale on the owning proposal, failing otherwise with `ERR_NO_CLOSED_BOND_SALE`, and increments the project's `version`. Construction accounting happens through **project expenditures**, which the `DistrictTreasurer` posts against an `IN_PROGRESS` project — any other project state fails with `ERR_INVALID_STATE` — naming the `vendor_name`, a positive `amount`, and a `description`. Two fiscal guards apply, both permitting exact equality: the `amount` may not exceed the project's available budget — its `authorized_amount` minus its `spent_amount` — failing with `ERR_PROJECT_BUDGET_EXCEEDED`, and it may not exceed the proposal's `available_proceeds`, failing with `ERR_INSUFFICIENT_PROCEEDS`. A posted expenditure starts with `review_status` in `PENDING_REVIEW` and `payment_status` in `UNPAID`, with `retainage_amount` and `disbursed_amount` both zero while unpaid; posting immediately adds the `amount` to the project's `spent_amount` and subtracts it from the proposal's `available_proceeds`. The expenditure's `bond_project_id` is set from the path.

Review belongs to the `BusinessManager`, who submits an `approved` verdict on an unpaid expenditure — review of an expenditure whose `payment_status` is not `UNPAID` fails with `ERR_INVALID_STATE`. A verdict of true moves `PENDING_REVIEW` → `REVIEWED`, and also rehabilitates a `FLAGGED` expenditure to `REVIEWED` on re-review; a verdict of false moves `PENDING_REVIEW` → `FLAGGED`. Each review increments the expenditure's `version`.

Only a `REVIEWED` expenditure may be paid: disbursement against any other review state fails with `ERR_EXPENDITURE_NOT_REVIEWED`. Disbursement by the `DistrictTreasurer` moves the payment `UNPAID` → `DISBURSED`, withholds a retainage of ten percent — `retainage_amount` is the `amount` multiplied by 0.10, rounded half-up to two decimal places — and pays out the remainder as `disbursed_amount`, the `amount` minus the retainage, incrementing the expenditure's `version`. An expenditure may instead be voided from `UNPAID` or `DISBURSED`: voiding moves the payment to `VOIDED`, compensates the ledgers by subtracting the `amount` from the project's `spent_amount` and adding it back to the proposal's `available_proceeds`, resets `retainage_amount` and `disbursed_amount` to zero when the expenditure had been disbursed, and increments the expenditure's `version`.

Completion closes a project out. The `Superintendent`'s completion of an `IN_PROGRESS` project requires that no expenditure of the project remain in `PENDING_REVIEW` or `FLAGGED` with a `payment_status` other than `VOIDED` — unreviewed work blocks the close with `ERR_UNREVIEWED_EXPENDITURES_EXIST`. Completion moves the project to `COMPLETED`, releases every `DISBURSED` expenditure's retainage by moving it to `RETAINAGE_RELEASED` — the retainage is paid out, while `retainage_amount` and `disbursed_amount` are retained on the record for audit — and increments the project's `version`. Cancellation is available earlier: a `PLANNED` project may be cancelled freely, while an `AUTHORIZED` project may be cancelled only when no expenditure with a `payment_status` other than `VOIDED` exists, failing otherwise with `ERR_INVALID_STATE`; either cancellation moves the project to `CANCELLED`, resets its `authorized_amount` to zero, and increments its `version`.

When construction realities shift money between projects, a `BudgetAnalyst` drafts a **capital-plan amendment** against a `PASSED` proposal, giving a `reason` and a set of `adjustments`, each naming a `bond_project_id` and a signed `delta_authorized`; an unknown project reference fails with `ERR_BOND_PROJECT_NOT_FOUND`. The draft starts in `DRAFT` with `submitted_by_user_id` null, its `bond_proposal_id` set from the path. Submission by the analyst moves it `DRAFT` → `SUBMITTED`, records the submitting operator in `submitted_by_user_id`, and increments the amendment's `version`.

Approval belongs to the `Superintendent`, and its four gates run in pipeline order. Segregation of duties first: the approver's `X-User-ID` must differ from `submitted_by_user_id`, and self-approval is refused with `ERR_SEGREGATION_OF_DUTIES`. Ownership next: every adjustment must reference a project of the amendment's own proposal, failing with `ERR_AMENDMENT_PROJECT_MISMATCH`. Then the floors: for every adjusted project, the resulting `authorized_amount` after applying the `delta_authorized` must not fall below the project's `spent_amount` — landing exactly on it is permitted — failing with `ERR_AMENDMENT_BELOW_SPENT`. Finally the ceiling: the summed `authorized_amount` over all of the proposal's non-`CANCELLED` projects after the deltas must not exceed the proposal's `total_amount`, failing with `ERR_AMENDMENT_EXCEEDS_AUTHORIZATION`. Approval applies each delta to its project's `authorized_amount`, moves the amendment `SUBMITTED` → `APPROVED`, and increments its `version`. Rejection moves a `SUBMITTED` amendment to `REJECTED` with a version increment, and a rejected amendment may be returned `REJECTED` → `DRAFT` for revision, which clears `submitted_by_user_id` back to null and increments the `version` once more.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — state transitions, certifications, canvasses, closes — return a `200 OK` status code. Retrieval endpoints return `200 OK`. Request and response payloads are specified by the workflows of §3; the table below is the HTTP contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (default 2026-08-01T00:00:00Z before any call) | All roles |
| POST | `/district/fiscal-years` | Create a fiscal year (starts DRAFT) | BusinessManager |
| GET | `/district/fiscal-years` | List fiscal years (created_at ASC); supports envelope pagination params | All roles |
| GET | `/district/fiscal-years/{fyId}` | Get one fiscal year | All roles |
| POST | `/district/fiscal-years/{fyId}/open` | Open a fiscal year (DRAFT -> OPEN) for budget development | BusinessManager |
| POST | `/district/fiscal-years/{fyId}/close` | Close a fiscal year (OPEN -> CLOSED); requires an ADOPTED budget version | BusinessManager |
| POST | `/district/fiscal-years/{id}/enrollment-projections` | Create an enrollment projection for one grade band (PROVISIONAL) | BudgetAnalyst |
| GET | `/district/fiscal-years/{id}/enrollment-projections` | List enrollment projections of a fiscal year | All roles |
| GET | `/district/enrollment-projections/{epId}` | Get one enrollment projection | All roles |
| POST | `/district/enrollment-projections/{epId}/certify` | Certify a projection with actual pupils (PROVISIONAL -> CERTIFIED) | BusinessManager |
| POST | `/district/fiscal-years/{id}/budget-versions` | Create a budget version (OCC-guarded; supersedes the currently ADOPTED version with its full supersede cascade) | BudgetAnalyst |
| GET | `/district/fiscal-years/{id}/budget-versions` | List budget versions of a fiscal year (created_at ASC) | All roles |
| GET | `/district/budget-versions/{bvId}` | Get one budget version | All roles |
| POST | `/district/budget-versions/{bvId}/propose` | Propose a draft budget (DRAFT -> PROPOSED) | BoardClerk |
| POST | `/district/budget-versions/{bvId}/return-to-draft` | Send a proposed/hearing-held budget back to draft (PROPOSED or HEARING_HELD -> DRAFT); cancels unpublished-pending hearings | BoardClerk |
| POST | `/district/budget-versions/{bvId}/adopt` | Adopt the budget (HEARING_HELD -> ADOPTED); fires the adoption cascade | BoardClerk |
| POST | `/district/budget-versions/{id}/budget-lines` | Add an appropriation line to a DRAFT budget version | BudgetAnalyst |
| GET | `/district/budget-versions/{id}/budget-lines` | List budget lines of a budget version (created_at ASC) | All roles |
| POST | `/district/budget-versions/{id}/transfers` | Transfer appropriation between two lines of the same DRAFT budget version (conserves the version's total) | BudgetAnalyst |
| POST | `/district/budget-versions/{id}/staffing-allocations` | Create a staffing allocation for one grade band from an enrollment projection (DRAFT budgets only) | BudgetAnalyst |
| GET | `/district/budget-versions/{id}/staffing-allocations` | List staffing allocations of a budget version | All roles |
| GET | `/district/enrollment-projections/{id}/staffing-allocations` | List staffing allocations computed from an enrollment projection | All roles |
| GET | `/district/staffing-allocations/{saId}` | Get one staffing allocation | All roles |
| POST | `/district/staffing-allocations/{id}/positions` | Create a position slot under an allocation (PROPOSED while allocation DRAFT; OPEN when allocation AUTHORIZED) | BudgetAnalyst |
| GET | `/district/staffing-allocations/{id}/positions` | List positions of a staffing allocation (created_at ASC) | All roles |
| POST | `/district/positions/{pId}/fill` | Fill an OPEN position with an incumbent salary (OPEN -> FILLED) | Superintendent |
| POST | `/district/positions/{pId}/vacate` | Vacate a FILLED position (FILLED -> OPEN); incumbent salary cleared | Superintendent |
| POST | `/district/positions/{pId}/eliminate` | Eliminate a PROPOSED or OPEN position (position control) | Superintendent |
| POST | `/district/budget-versions/{id}/revenue-estimates` | Create the revenue estimate for a budget version (PROVISIONAL variant; at most one per version) | BusinessManager |
| GET | `/district/budget-versions/{id}/revenue-estimates` | List the revenue estimate of a budget version (array of 0 or 1) | All roles |
| POST | `/district/revenue-estimates/{reId}/recertify` | Switch the estimate to the CERTIFIED variant (requires all projections CERTIFIED) | BusinessManager |
| POST | `/district/budget-versions/{id}/hearings` | Publish notice and schedule a public hearing for a PROPOSED budget version | BoardClerk |
| GET | `/district/budget-versions/{id}/hearings` | List hearings of a budget version | All roles |
| POST | `/district/public-hearings/{hId}/hold` | Hold the hearing on its scheduled date (NOTICE_PUBLISHED -> HELD); moves the budget version to HEARING_HELD | BoardClerk |
| POST | `/district/public-hearings/{hId}/cancel` | Cancel a published hearing (NOTICE_PUBLISHED -> CANCELLED) | BoardClerk |
| POST | `/district/elections` | Schedule an election on a statutory date (first Tuesday of March/June/November) | BoardClerk |
| GET | `/district/elections` | List elections (election calendar) | All roles |
| GET | `/district/elections/{eId}` | Get one election | All roles |
| POST | `/district/elections/{eId}/canvass` | Canvass results for all certified measures of the election; fires cascade B | BoardClerk |
| POST | `/district/fiscal-years/{id}/bond-proposals` | Create a bond proposal (DRAFT) | BoardClerk |
| GET | `/district/fiscal-years/{id}/bond-proposals` | List bond proposals of a fiscal year | All roles |
| GET | `/district/bond-proposals/{bpId}` | Get one bond proposal | All roles |
| POST | `/district/bond-proposals/{bpId}/approve-board` | Board approves the proposal for referral (DRAFT -> BOARD_APPROVED); bond capacity check | BoardClerk |
| POST | `/district/bond-proposals/{bpId}/revise` | Return a FAILED proposal to DRAFT for revision (revision loop) | BoardClerk |
| POST | `/district/bond-proposals/{id}/projects` | Add a project to a DRAFT proposal's bond project list (site-window and aggregate checks) | BoardClerk |
| GET | `/district/bond-proposals/{id}/projects` | List projects of a bond proposal (created_at ASC) | All roles |
| GET | `/district/bond-projects/{prjId}` | Get one bond project | All roles |
| POST | `/district/bond-projects/{prjId}/activate` | Start construction accounting (AUTHORIZED -> IN_PROGRESS); requires a CLOSED sale on the proposal | Superintendent |
| POST | `/district/bond-projects/{prjId}/complete` | Complete a project; releases retainage on all DISBURSED expenditures | Superintendent |
| POST | `/district/bond-projects/{prjId}/cancel` | Cancel a PLANNED or AUTHORIZED project (AUTHORIZED requires no active expenditures) | Superintendent |
| POST | `/district/elections/{id}/ballot-measures` | Refer a BOARD_APPROVED proposal to this election's ballot with draft language | BoardClerk |
| GET | `/district/elections/{id}/ballot-measures` | List ballot measures of an election | All roles |
| GET | `/district/bond-proposals/{id}/ballot-measures` | List ballot measures referencing a bond proposal | All roles |
| GET | `/district/ballot-measures/{bmId}` | Get one ballot measure | All roles |
| POST | `/district/ballot-measures/{bmId}/certify` | Certify ballot language (segregation of duties: certifier differs from drafter); moves proposal BOARD_APPROVED -> REFERRED | BoardClerk |
| POST | `/district/ballot-measures/{bmId}/publications` | Publish district material about a measure (campaign restriction enforced) | BoardClerk |
| GET | `/district/ballot-measures/{id}/publications` | List publications of a ballot measure | All roles |
| POST | `/district/bond-proposals/{id}/bond-sales` | Plan a bond sale series against a PASSED proposal (OCC-guarded) | DistrictTreasurer |
| GET | `/district/bond-proposals/{id}/bond-sales` | List bond sales of a proposal | All roles |
| POST | `/district/bond-sales/{bsId}/close` | Close a planned sale on/after its sale date; delivers proceeds and adds to outstanding debt | DistrictTreasurer |
| POST | `/district/bond-sales/{bsId}/cancel` | Cancel a planned sale; releases the reserved authorization | DistrictTreasurer |
| POST | `/district/bond-projects/{id}/expenditures` | Post an expenditure against an IN_PROGRESS project (budget and proceeds checks) | DistrictTreasurer |
| GET | `/district/bond-projects/{id}/expenditures` | List expenditures of a project (created_at ASC) | All roles |
| POST | `/district/project-expenditures/{peId}/review` | Review an unpaid expenditure (PENDING_REVIEW -> REVIEWED or FLAGGED; FLAGGED -> REVIEWED on re-review) | BusinessManager |
| POST | `/district/project-expenditures/{peId}/disburse` | Disburse a REVIEWED unpaid expenditure; ten percent retainage withheld | DistrictTreasurer |
| POST | `/district/project-expenditures/{peId}/void` | Void an UNPAID or DISBURSED expenditure; restores project budget and proposal proceeds (compensation) | DistrictTreasurer |
| POST | `/district/bond-proposals/{id}/amendments` | Draft a capital-plan amendment moving authorized amounts between projects of a PASSED proposal | BudgetAnalyst |
| GET | `/district/bond-proposals/{id}/amendments` | List capital-plan amendments of a proposal | All roles |
| POST | `/district/capital-plan-amendments/{caId}/submit` | Submit a draft amendment for approval (DRAFT -> SUBMITTED) | BudgetAnalyst |
| POST | `/district/capital-plan-amendments/{caId}/approve` | Approve a submitted amendment (segregation of duties: approver differs from submitter); applies deltas to project authorizations | Superintendent |
| POST | `/district/capital-plan-amendments/{caId}/reject` | Reject a submitted amendment (SUBMITTED -> REJECTED) | Superintendent |
| POST | `/district/capital-plan-amendments/{caId}/revise` | Return a rejected amendment to DRAFT for revision (REJECTED -> DRAFT) | BudgetAnalyst |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this catalogue is authoritative for the HTTP status of each error.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_FIELD_VALUE` | 422 Unprocessable Entity |
| `ERR_FISCAL_YEAR_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_PROJECTION_NOT_FOUND` | 404 Not Found |
| `ERR_BUDGET_VERSION_NOT_FOUND` | 404 Not Found |
| `ERR_BUDGET_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_STAFFING_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_POSITION_NOT_FOUND` | 404 Not Found |
| `ERR_REVENUE_ESTIMATE_NOT_FOUND` | 404 Not Found |
| `ERR_PUBLIC_HEARING_NOT_FOUND` | 404 Not Found |
| `ERR_ELECTION_NOT_FOUND` | 404 Not Found |
| `ERR_BOND_PROPOSAL_NOT_FOUND` | 404 Not Found |
| `ERR_BOND_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_BALLOT_MEASURE_NOT_FOUND` | 404 Not Found |
| `ERR_BOND_SALE_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_EXPENDITURE_NOT_FOUND` | 404 Not Found |
| `ERR_CAPITAL_PLAN_AMENDMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EXPENDITURE_NOT_REVIEWED` | 409 Conflict |
| `ERR_FISCAL_YEAR_NOT_OPEN` | 409 Conflict |
| `ERR_BUDGET_VERSION_NOT_DRAFT` | 409 Conflict |
| `ERR_BUDGET_VERSION_NOT_HEARING_HELD` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PROHIBITED_CAMPAIGN_ACTIVITY` | 403 Forbidden |
| `ERR_STATUTORY_ELECTION_DATE` | 409 Conflict |
| `ERR_NOTICE_WINDOW_TOO_SHORT` | 409 Conflict |
| `ERR_HEARING_DATE_NOT_TODAY` | 409 Conflict |
| `ERR_ADOPTION_TOO_SOON` | 409 Conflict |
| `ERR_ADOPTION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_CERTIFICATION_DEADLINE_PASSED` | 409 Conflict |
| `ERR_CAMPAIGN_RESTRICTION_WINDOW` | 409 Conflict |
| `ERR_CANVASS_BEFORE_ELECTION` | 409 Conflict |
| `ERR_AUTHORIZATION_LAPSED` | 409 Conflict |
| `ERR_SALE_NOT_YET_EFFECTIVE` | 409 Conflict |
| `ERR_DUPLICATE_GRADE_BAND` | 409 Conflict |
| `ERR_HEARING_VENUE_DATE_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_BALLOT_MEASURE` | 409 Conflict |
| `ERR_BALLOT_LANGUAGE_TOO_LONG` | 422 Unprocessable Entity |
| `ERR_SITE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_PRIORITY_RANK` | 409 Conflict |
| `ERR_REVENUE_ESTIMATE_EXISTS` | 409 Conflict |
| `ERR_PROJECT_LIST_EXCEEDS_AMOUNT` | 422 Unprocessable Entity |
| `ERR_CANVASS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SERIES_LABEL` | 409 Conflict |
| `ERR_CROSS_FISCAL_YEAR_REFERENCE` | 422 Unprocessable Entity |
| `ERR_TRANSFER_LINE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PROJECTIONS_NOT_ALL_CERTIFIED` | 409 Conflict |
| `ERR_NO_ADOPTED_BUDGET_VERSION` | 409 Conflict |
| `ERR_AMENDMENT_PROJECT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_CLOSED_BOND_SALE` | 409 Conflict |
| `ERR_UNREVIEWED_EXPENDITURES_EXIST` | 409 Conflict |
| `ERR_NO_REVENUE_ESTIMATE` | 409 Conflict |
| `ERR_EMPTY_PROJECT_LIST` | 409 Conflict |
| `ERR_ALLOCATION_EXCEEDS_FORMULA` | 422 Unprocessable Entity |
| `ERR_FTE_CEILING_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_POSITION_FTE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TAX_RATE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BUDGET_NOT_BALANCED` | 422 Unprocessable Entity |
| `ERR_BOND_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SALE_EXCEEDS_REMAINING_AUTHORIZATION` | 422 Unprocessable Entity |
| `ERR_NONPOSITIVE_NET_PROCEEDS` | 422 Unprocessable Entity |
| `ERR_PROJECT_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_PROCEEDS` | 422 Unprocessable Entity |
| `ERR_TRANSFER_EXCEEDS_LINE` | 422 Unprocessable Entity |
| `ERR_AMENDMENT_BELOW_SPENT` | 422 Unprocessable Entity |
| `ERR_AMENDMENT_EXCEEDS_AUTHORIZATION` | 422 Unprocessable Entity |
