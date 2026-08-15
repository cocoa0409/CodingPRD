# Reserve Study Funding API — Product Requirements Document

## 1. Introduction

Every community association sits on a slow-moving liability: roofs age out, pavement cracks, boilers reach the end of their service life, and a board that fails to save for those replacements meets them as special assessments — sudden, unpopular levies on every owner. Many states answer with statute: reserve studies on a fixed cadence, minimum funding levels, mandatory disclosure to members. The Reserve Study Funding API operationalizes that discipline. It keeps each association's component inventory with useful-life and remaining-life estimates, projects replacement costs under explicit inflation and interest assumptions, solves for the annual contribution that keeps the reserve fund solvent across a thirty-year horizon, and then reconciles what the association actually spends against what the plan predicted.

Work is divided along an approval chain. A `ReserveSpecialist` builds the study — the component inventory, the funding plans, the annual update cycle. A `BoardMember` adopts or rejects studies, selects the funding plan, and approves, rejects, or reverses expenditures. An `AssociationManager` runs the fieldwork: site visits, expenditure submissions, disclosure distribution. A `PlatformAdmin` seeds the per-state statutory rules that gate everything else. Because statutes differ by state, those rules are data rather than code: each state's minimum percent funded, permitted plan types, site-visit cadence, and disclosure deadline live in a configurable record consulted at every gate.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through the mandatory `X-User-Role` HTTP header, which specifies the caller's operational capacity; an `X-User-ID` header may accompany it to identify the acting operator. The system recognizes exactly four roles: `PlatformAdmin`, `ReserveSpecialist`, `BoardMember`, and `AssociationManager`. A `PlatformAdmin` is the platform operator who seeds statutory state rules and drives the test clock. A `ReserveSpecialist` prepares associations, studies, component inventories, and funding plans, runs annual updates, and accepts expenditure variances. A `BoardMember` adopts or rejects studies, selects the funding plan, and approves, rejects, or reverses expenditures. An `AssociationManager` schedules and completes site visits, submits expenditures, and distributes disclosures.

For all four roles — `PlatformAdmin`, `ReserveSpecialist`, `BoardMember`, and `AssociationManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never requires, records, or compares it — a request without `X-User-ID` is processed exactly as one carrying it — and no ownership rule depends on it.

A request whose `X-User-Role` header is missing or does not name one of the four declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the addressed endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

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
- Requests addressed to undefined paths, or to defined paths with unsupported methods, are answered in this same envelope with `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure surfaces `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at 100. The `offset` parameter sets the number of items skipped and defaults to 0. Both parameters are optional on every list endpoint, and neither is ever rejected: a non-integer `limit` falls back to 10 and an integer `limit` outside the 1–100 range is clamped to it, while a non-integer `offset` falls back to 0 and a negative `offset` is clamped up to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`. `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. The Logical Clock

Every temporal judgment the server makes — fiscal-year assignment, study window derivation, site-visit cadence windows, the reversal window, disclosure due dates, lateness — reads a single logical clock, never wall-clock time. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time on its own.

A `PlatformAdmin` may set the clock through `POST /_clock/set_current_utc`, supplying the new reading in the request field `to_iso8601` as an ISO 8601 UTC instant (a reading without an explicit UTC designator is interpreted as UTC). The response echoes the new reading as `current_utc`. Event timestamps recorded on resources — `adopted_at` on a study, `computed_at` on a funding plan, `completed_at` on a site visit, `approved_at` on an expenditure, `distributed_at` on a disclosure — are stamped from this logical clock at the moment the corresponding transition occurs; the bookkeeping timestamps `created_at` and `updated_at` on every resource and the envelope's `api_request_timestamp` read the same clock, and date-derived values such as `due_date`, `next_site_visit_due_date`, and every `fiscal_year` are computed from its current reading.

### 2.5. Fiscal Calendars and Study Windows

Each association runs on a fiscal calendar anchored by its `fiscal_year_end_month`, an integer from 1 to 12, where 12 marks a calendar-year association. The fiscal-year label of any date is derived from that anchor: for a calendar-year association, the label is simply the calendar year of the date; otherwise, the label is the calendar year of the date plus one when the date's month falls after the end month, and the calendar year of the date when it does not. This derivation assigns every expenditure its `fiscal_year`, bounds the annual-update guard, and defines the reversal window.

A reserve study covering a `fiscal_year` spans a half-open window derived from the same anchor. For a calendar-year association, the window runs from January 1 of the fiscal year (inclusive) to January 1 of the following year (exclusive). For any other association, the window runs from the first day of the month following the end month in the prior calendar year (inclusive) to the first day of that same month in the fiscal year's own calendar year (exclusive). The study exposes these bounds as `window_start_date` and `window_end_date_exclusive`. All dates are rendered `YYYY-MM-DD`, all day arithmetic is in whole days, and wherever a duration in years must become a duration in days, one year counts as exactly 365 days.

### 2.6. Cents, Percents, and Rounding

All monetary values in the system — cash balances, replacement costs, contributions, expenditures, allocation lines — are carried as integer numbers of cents; there are no fractional cents anywhere. Percentages that describe funding position are carried to exactly two decimal places. Whenever a calculation produces a value that must be rounded, the method is round half up. Intermediate rounding is applied exactly where the business rules in Section 3 specify it — per replacement event, per year-step, per component term — because rounding at a different point in the pipeline produces different integers.

### 2.7. Common Resource Properties

Every resource in the system — state reserve rules, associations, reserve studies, components, funding plans, site visits, expenditures, and disclosures alike — carries four system-managed fields:

- **`id` (string):** a server-minted unique identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer that starts at 1 on creation and increments on every mutation, including mutations the server performs as a side effect of another operation — a study's `version`, for example, advances when one of its components is retired because the study's derived totals are recomputed.

### 2.8. Validation Precedence

Every request is screened by an ordered validation cascade, and an earlier failure masks all later checks — the client always sees the first applicable rejection, not a later one. The cascade runs in this order:

1. **Authentication.** The `X-User-Role` header is present and names a declared role; failures surface `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role is permitted for the endpoint; failures surface `ERR_FORBIDDEN`.
3. **Existence.** Path identifiers resolve to existing resources, strictly left to right per §2.11; failures surface `ERR_NOT_FOUND`. Body foreign keys (`association_id`, `study_id`, `component_id`) likewise resolve to existing resources, but on collection-level creation endpoints — whose paths carry no resource identifier — the missing-required-field and unknown-field screens of step 4 run first, then foreign-key existence, and only then the remaining shape rules of step 4.
4. **Request shape.** Required fields are present, no unknown fields are supplied, enum values are members of their declared sets, and numeric ranges hold — `useful_life_years` at least 1, `remaining_useful_life_years` at least 0 and no greater than the useful life, `fiscal_year` an integer, the monetary amounts a client may supply that pay for work — a component's `current_replacement_cost_cents` and an expenditure's `amount_cents` — strictly positive, while the balance fields `reserve_cash_balance_cents` and `current_annual_contribution_cents` may be zero, rates non-negative, `fiscal_year_end_month` between 1 and 12, `min_percent_funded_pct` between 0 and 100, `allowed_plan_types` a non-empty subset of the three plan types, `site_visit_interval_years` a positive integer, `disclosure_deadline_days` a non-negative integer, and supplied dates (`visit_date`, `incurred_date`) parseable as calendar dates. The unknown-field screen applies to the payloads that declare fields — the creation payloads and the component-update payload; the state-transition actions declare no payload beyond the optional `reason` noted in §3.5 and §3.6 and ignore any other body content sent. Failures surface `ERR_INVALID_REQUEST`.
5. **Target state.** The addressed entity sits in the state the action requires: the study `DRAFT` or `SUBMITTED` as the operation demands (surfacing `ERR_INVALID_STATE` or `ERR_STUDY_NOT_DRAFT`), the plan in a compatible status, the visit `SCHEDULED`, the expenditure `SUBMITTED` or `APPROVED`, the disclosure `PENDING`, exactly one `SELECTED` plan at adoption (`ERR_NO_PLAN_SELECTED`).
6. **Optimistic concurrency.** On funding-plan creation, `expected_study_version` must equal the study's current `version`; a mismatch surfaces `ERR_STALE_VERSION` (see §2.9).
7. **Referential configuration.** Referenced configuration and current aggregates exist: a state rule for the association's `state_code` (`ERR_STATE_RULE_MISSING`), a current `ADOPTED` study for the association (`ERR_NO_ADOPTED_STUDY`), a component that belongs to that study and is `ACTIVE` (`ERR_COMPONENT_NOT_CURRENT`, re-checked at approval).
8. **Temporal rules.** The site-visit cadence at study submission (`ERR_SITE_VISIT_CADENCE`), the reversal inside the expenditure's own fiscal year (`ERR_REVERSAL_WINDOW_CLOSED`), and the annual update at most once per fiscal year (`ERR_ANNUAL_UPDATE_ALREADY_RUN`).
9. **Statutory compliance at adoption.** The selected plan's type is permitted by the state rule (`ERR_PLAN_TYPE_NOT_ALLOWED`) and the study's percent funded meets the state minimum (`ERR_PERCENT_FUNDED_BELOW_MINIMUM`).
10. **Uniqueness, overlap, gap, and content minimums.** One in-progress study per association (`ERR_STUDY_IN_PROGRESS`), no fiscal-window overlap with another adopted study (`ERR_STUDY_WINDOW_OVERLAP`), the site-visit minimum gap (`ERR_SITE_VISIT_TOO_SOON`), state-rule `state_code` uniqueness (`ERR_STATE_RULE_EXISTS`), one `SELECTED` plan per study (`ERR_PLAN_ALREADY_SELECTED`), same-type plan replacement only over a `DRAFT` plan (`ERR_PLAN_TYPE_LOCKED`), and submission content minimums (`ERR_STUDY_EMPTY`, `ERR_NO_FUNDING_PLAN`).
11. **Fiscal sufficiency.** At expenditure approval, the association's `reserve_cash_balance_cents` must cover the expenditure's `amount_cents`; failures surface `ERR_CASH_INSUFFICIENT`.

### 2.9. Optimistic Concurrency on Plan Creation

Exactly one endpoint in the system is guarded by optimistic concurrency control: `POST /reserve-studies/{id}/funding-plans`, the funding-plan creation endpoint. Its request body must carry `expected_study_version` — a non-optional field holding the `version` of the parent study as the client last observed it. If the supplied value does not equal the study's current `version` on the server, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because plan creation legitimately retires an existing same-type `DRAFT` plan: a creation issued from a stale view of the study would otherwise retire a plan the client never observed. Endpoints not named here take no version field at all; clients must not send one.

### 2.10. Derived Totals and the Compliance Posture

Derived state is never lazy. `fully_funded_balance_cents`, `percent_funded`, `statutory_compliance_status`, `next_site_visit_due_date`, and `annual_update_overdue` reflect the underlying data at the moment of any read, and reading an association returns the compliance and cadence fields as computed at that moment. Mutations propagate immediately and visibly: a component edit, retirement, or restoration, an expenditure approval or reversal, and the annual update each recompute the affected study's totals, advance the study's `version`, and refresh its `updated_at`; cash movements advance the association's `version` in the same way.

The compliance posture compares the adopted study's `percent_funded` against the state rule's `min_percent_funded_pct`. An association that has never adopted a study sits at `COMPLIANCE_UNKNOWN`. On adoption the posture necessarily lands on `COMPLIANT`, because adoption itself enforces the minimum. On expenditure approval, on expenditure reversal, and at every annual update the comparison is re-run against the freshly recomputed percent funded: meeting or exceeding the minimum yields `COMPLIANT`, and falling below it yields `NON_COMPLIANT`.

### 2.11. Nested Path Resolution

Several endpoints address a collection through a parent resource in the path — the studies of an association, the components of a study, and similar constructions. Such paths are validated strictly left to right: the server first confirms that the leftmost identifier exists, then the next, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, before any later segment or business rule is examined. A request addressed at the components of a study that does not exist therefore fails on the study, without any component lookup being attempted.

## 3. Business Logic & Workflows

### 3.1. Statutory Ground Rules and Association Onboarding

Before any association can exist, a `PlatformAdmin` seeds the statutory ground rules of its state. A state reserve rule records the two-letter `state_code`; the `min_percent_funded_pct`, the statutory minimum percent funded a study must reach to be adoptable, between 0 and 100; `allowed_plan_types`, a non-empty subset of `BASELINE`, `THRESHOLD`, and `FULL` naming the funding plan types the state permits at adoption; `site_visit_interval_years`, the statutory maximum gap between physical inspections; `disclosure_deadline_days`, the number of days after an adoption or an annual update within which the member disclosure must reach members; and `annual_update_required`, whether the state mandates a yearly reserve-study update. One rule exists per state: attempting to file a second rule for a `state_code` already on record is rejected with `ERR_STATE_RULE_EXISTS`.

A `ReserveSpecialist` then onboards each association with its legal `name`, the `state_code` whose rule governs it — a rule for that state must already exist, and creation fails with `ERR_STATE_RULE_MISSING` when none does — the `fiscal_year_end_month` anchoring its fiscal calendar, its current `reserve_cash_balance_cents` on hand, and optionally the `current_annual_contribution_cents` it presently funds each year, which defaults to 0 when omitted. The cash balance is initialized at creation and afterwards moves only through expenditure approval and reversal; there is no direct edit. A new association's `statutory_compliance_status` starts at `COMPLIANCE_UNKNOWN`, its `next_site_visit_due_date` starts null, and its `last_annual_update_fiscal_year` stays null until the first annual update runs.

### 3.2. Site Visits and the Inspection Cadence

Physical inspections anchor the study in observed reality. An `AssociationManager` schedules a site visit by supplying the `association_id` and a `visit_date`. Inspections cluster poorly, so the new date must sit at least thirty days away from every other visit of the association in either direction; visits of any status count toward the gap, a spacing of exactly thirty days is acceptable, and a tighter gap is rejected with `ERR_SITE_VISIT_TOO_SOON`. A new visit opens in `SCHEDULED` status. Completing the visit stamps `completed_at` from the logical clock, moves it to `COMPLETED`, and recomputes the association's `next_site_visit_due_date` as the most recent completed `visit_date` plus the statutory cadence window — 365 days per year of `site_visit_interval_years` — leaving it null when no completed visit exists yet; the association's `version` advances with the recompute. An association's visits can be listed and filtered by `status`.

The cadence gate bites later, when a study is submitted for board review, and it is measured against the logical clock's current date. The statutory window in days is 365 multiplied by the rule's `site_visit_interval_years`. A study whose `study_type` is `FULL` or `UPDATE_WITH_VISIT` may be submitted only when some `COMPLETED` visit of the association falls inside that window: the visit's date must be no later than the submit date, and the gap between visit and submit date must not exceed the window's length. An `UPDATE_NO_VISIT` study is granted a doubled window — twice the statutory length — under the same conditions. A submission with no qualifying completed visit fails with `ERR_SITE_VISIT_CADENCE`.

### 3.3. The Component Inventory and the Fully Funded Balance

A reserve study is born in `DRAFT` status when a `ReserveSpecialist` creates it with its `association_id`, the `fiscal_year` it covers, a `study_type` of `FULL`, `UPDATE_WITH_VISIT`, or `UPDATE_NO_VISIT`, and the two economic assumptions: `inflation_rate`, the annual cost-inflation assumption expressed as a decimal, and `interest_rate`, the annual yield earned on reserve cash — both must be non-negative. An association may have at most one study in flight at a time: creating another while a `DRAFT` or `SUBMITTED` study exists fails with `ERR_STUDY_IN_PROGRESS`. The new study's fiscal window, derived per §2.5, must also not overlap the window of any `ADOPTED` study of the same association, on pain of `ERR_STUDY_WINDOW_OVERLAP`. A freshly created study reports a `fully_funded_balance_cents` of 0 and, by the pinned edge of the percent-funded rule below, a `percent_funded` of exactly 100.00. The studies of one association can be listed with an optional `status` filter, and a cross-association listing additionally accepts `association_id` and `adopted_plan_id` filters — the latter answering which study adopted a given plan.

Components fill the study's inventory. The specialist adds a component by naming its `study_id`, a `name` such as "Roof - Building A", a `category` drawn from `ROOFING`, `PAVING`, `MECHANICAL`, `EXTERIOR`, `INTERIOR`, `RECREATION`, or `OTHER`, its `useful_life_years` of at least 1, its `remaining_useful_life_years` of at least 0 and no greater than the useful life, and today's `current_replacement_cost_cents`, strictly positive. The optional `is_included_in_funding` flag defaults to true and governs whether the component participates in funding projections and in the fully funded balance. A component opens in `ACTIVE` status with `actual_expenditure_cents` at 0 and `last_replaced_fiscal_year` null. A study's components can be listed with an optional `status` filter.

The study's fully funded balance is the accumulated-deterioration measure of that inventory. For each `ACTIVE`, funding-included component, the consumed life is `useful_life_years` minus `remaining_useful_life_years`, and the component contributes its `current_replacement_cost_cents` multiplied by the ratio of consumed life to useful life; each per-component term is rounded half-up to integer cents before the terms are summed into `fully_funded_balance_cents`. The study's `percent_funded` then measures the association's position against that obligation: the association's `reserve_cash_balance_cents` multiplied by one hundred and divided by the fully funded balance, rounded half-up to two decimal places. When no obligation exists — a fully funded balance of zero — `percent_funded` is pinned at exactly 100.00 rather than being left undefined.

The inventory is editable only while its study is `DRAFT`. While it is, the specialist may update a component's `name`, `category`, life figures, replacement cost, or funding inclusion; may retire a component, moving it from `ACTIVE` to `RETIRED`, when it leaves scope; and may restore a retired component back to `ACTIVE`. Any of these mutations against a study that is no longer `DRAFT` fails with `ERR_STUDY_NOT_DRAFT`. Each of them also recomputes the study's `fully_funded_balance_cents` and `percent_funded` immediately and advances the study's `version`, so a change deep in the inventory is always visible on the study itself.

### 3.4. Funding Plans and the Contribution Solve

With the inventory in place, the specialist models funding plans. Creating a plan requires the `plan_type` — one of `BASELINE`, `THRESHOLD`, or `FULL` — and the `expected_study_version` concurrency token described in §2.9; a token that no longer matches the study's current `version` is rejected with `ERR_STALE_VERSION`. Plans may only be created while the study is `DRAFT`, failing with `ERR_STUDY_NOT_DRAFT` otherwise. At most one working draft of each type exists: creating a plan of a type that already has a `DRAFT` plan retires that older plan to `RETIRED`, while creating one whose type already has a `RECOMMENDED` or `SELECTED` plan is rejected with `ERR_PLAN_TYPE_LOCKED`. Creating a plan is itself a mutation of the study and advances the study's `version` by one — which is precisely why the concurrency token matters. A study's plans can be listed with optional `plan_type` and `status` filters.

Every projection starts from the replacement schedule of the study's included components — those in `ACTIVE` status with `is_included_in_funding` true. A component is projected to be replaced in the projection year equal to its `remaining_useful_life_years`, then again every `useful_life_years` years thereafter, for as long as the resulting year does not exceed 29; the horizon spans thirty years, indexed 0 through 29. The cost of a replacement landing in year y is the component's `current_replacement_cost_cents` grown at the study's `inflation_rate`, compounded annually for y years, with each replacement event individually rounded half-up to integer cents. Summing the inflated costs of all replacements scheduled in the same year yields that year's total outflow, which is zero in years with no scheduled replacement.

The plan is solved once, at creation, and the result is frozen onto it. The projection opens with `starting_cash_cents`, a snapshot of the association's `reserve_cash_balance_cents` taken at computation time. Given a candidate constant annual contribution, each successive year-end balance is the prior balance plus the contribution minus that year's scheduled outflow, the difference then grown by one year of interest at the study's `interest_rate`, with the result rounded half-up to integer cents — rounding is applied exactly once per year-step. The plan's `annual_contribution_cents` is the smallest non-negative integer number of cents for which the projected balance stays at or above the plan type's floor in every year-end position from the first projected year through the thirtieth. The solve searches the range from zero cents to one trillion cents, and the minimal feasible value is unique. The computation moment is recorded as `computed_at`, stamped from the logical clock.

The floor is what distinguishes the three plan types, and each is specified with the same care:

- A `BASELINE` plan — cash-flow funding aimed at special-assessment avoidance — sets the floor at zero in every year: the projected balance may never turn negative.
- A `THRESHOLD` plan sets the floor in every year to the plan's `threshold_floor_cents`, defined as one half of the largest single-year scheduled outflow anywhere in the thirty-year horizon, rounded half-up to integer cents; when no replacement is scheduled at all, the largest outflow is zero and the floor collapses to zero. `threshold_floor_cents` is populated only on `THRESHOLD` plans and is null on `BASELINE` and `FULL` plans.
- A `FULL` plan requires the projected balance in each year to cover that year's projected fully funded balance. For a projection year y, each included component's effective age is its current consumed life — useful life minus remaining life — advanced by y years and taken modulo its useful life, so a component cycles back to age zero whenever a projected replacement occurs. The year's floor is then the sum over included components of the component's replacement cost inflated for y years at the study's `inflation_rate` and rounded half-up to cents, multiplied by the ratio of that effective age to the useful life, with the product rounded half-up to cents again before the terms are summed.

Once the plans exist, the specialist signals a preference by recommending one: a `DRAFT` plan moves to `RECOMMENDED`, provided its study is `DRAFT` or already `SUBMITTED` — any other study state fails with `ERR_INVALID_STATE`. Recommending one plan quietly reverts any other `RECOMMENDED` plan of the same study back to `DRAFT`, so at most one recommendation is outstanding per study at any time.

### 3.5. Board Review: Submission, Selection, Adoption, and Revision

When the inventory and at least one plan are in place, the specialist submits the study for board review, moving it from `DRAFT` to `SUBMITTED` and advancing its `version`. Three gates guard submission, in this order of narrative priority. First, the statutory inspection cadence of §3.2 must be satisfied for the study's `study_type`, failing with `ERR_SITE_VISIT_CADENCE`. Second, the study must contain at least one component that is `ACTIVE` and included in funding — submitting an empty study is rejected with `ERR_STUDY_EMPTY`. Third, at least one funding plan in `DRAFT`, `RECOMMENDED`, or `SELECTED` status must exist, failing with `ERR_NO_FUNDING_PLAN` otherwise.

While the study is `SUBMITTED`, a `BoardMember` selects the plan the board intends to fund. Selection moves a `DRAFT` or `RECOMMENDED` plan to `SELECTED` and is valid only while the study is `SUBMITTED`; any other study state yields `ERR_INVALID_STATE`. At most one plan per study may hold the selection: attempting to select a plan while another is already `SELECTED` is rejected with `ERR_PLAN_ALREADY_SELECTED`.

Adoption is the board's final word, moving the study from `SUBMITTED` to `ADOPTED`. Three statutory checks stand in front of it: exactly one plan of the study must be `SELECTED` (otherwise `ERR_NO_PLAN_SELECTED`); the selected plan's `plan_type` must appear in the state rule's `allowed_plan_types` (otherwise `ERR_PLAN_TYPE_NOT_ALLOWED`); and the study's `percent_funded` must meet or exceed the state rule's `min_percent_funded_pct` (otherwise `ERR_PERCENT_FUNDED_BELOW_MINIMUM`). On success the study stamps `adopted_at` from the logical clock, records the selected plan in `adopted_plan_id`, and advances its `version`. Adoption is also a regime change for the association: any previously `ADOPTED` study of the same association moves to `SUPERSEDED` with its `version` advanced, its `DRAFT`, `RECOMMENDED`, and `SELECTED` plans move to `RETIRED`, and its still-`PENDING` disclosures move to `VOIDED`. The newly adopted study spawns a member disclosure of `disclosure_type` `ADOPTION_SUMMARY` in `PENDING` status, whose `due_date` falls `disclosure_deadline_days` after the adoption date. Because adoption enforces the funding minimum, the association's `statutory_compliance_status` lands on `COMPLIANT` at this moment — set directly, without advancing the association's `version`. The newly adopted study's own plans are left untouched by adoption: its selected plan remains `SELECTED`.

The board may instead send the study back for revision, returning it from `SUBMITTED` to `DRAFT`; the rejection may carry an optional `reason`, which is accepted but not persisted or echoed. The study's `version` advances, its `SELECTED` plan — if one exists — reverts to `DRAFT` as compensation so that a re-submitted study must go through selection again, and any plan sitting in `RECOMMENDED` likewise falls back to `DRAFT`, clearing the endorsement along with the board's pick. This revision loop may repeat as often as needed.

A specialist may also abandon a study outright while it is still `DRAFT`, moving it to `WITHDRAWN`, a terminal state; the study's `version` advances and its `DRAFT` and `RECOMMENDED` plans move to `RETIRED`.

### 3.6. Reserve Expenditures and Plan-versus-Actual Reconciliation

Once a study is adopted, the association starts spending against it. An `AssociationManager` reports actual spending by submitting an expenditure carrying the paying `association_id`, the `component_id` being paid for, the `amount_cents` actually paid, the `incurred_date`, and the `kind` of work — `PLANNED_REPLACEMENT` or `UNPLANNED_REPAIR`. Submission requires the association to have a current `ADOPTED` study, failing with `ERR_NO_ADOPTED_STUDY` otherwise, and the component must belong to that study and still be `ACTIVE`, failing with `ERR_COMPONENT_NOT_CURRENT` otherwise. The expenditure's `fiscal_year` is derived from `incurred_date` under the association's fiscal calendar per §2.5. A new expenditure opens on two independent state axes at once: `approval_status` starts at `SUBMITTED` while `reconciliation_status` starts at `UNRECONCILED`, and the two move independently thereafter.

Board approval is the pivotal event. It first re-verifies that the association still has a current `ADOPTED` study and that the component still belongs to it and remains `ACTIVE` — a superseded or entirely missing adopted study, or a component retired since submission, surfaces `ERR_COMPONENT_NOT_CURRENT` — and only then checks that the association's `reserve_cash_balance_cents` covers the `amount_cents`, failing with `ERR_CASH_INSUFFICIENT` when it does not. On success the cascade runs in full: `approval_status` becomes `APPROVED`, `approved_at` is stamped from the logical clock, and the expenditure's `version` advances; the amount is debited from the association's `reserve_cash_balance_cents`, advancing the association's `version`; the amount is added to the component's running `actual_expenditure_cents`; and for a `PLANNED_REPLACEMENT` the component's life is reset — its current `remaining_useful_life_years` is first captured into the expenditure's `component_rul_before_years`, then set to the full `useful_life_years`, with `last_replaced_fiscal_year` recorded as the expenditure's `fiscal_year` — while an `UNPLANNED_REPAIR` leaves component life untouched and `component_rul_before_years` stays null. The component's `version` advances. Because the fully funded balance depends on remaining lives, the adopted study's `fully_funded_balance_cents` and `percent_funded` are recomputed and the study's `version` advances, and the association's `statutory_compliance_status` is re-evaluated, dropping to `NON_COMPLIANT` when the recomputed percent falls below the state minimum.

Approval also fixes the expenditure's reconciliation against the plan as it stood in the expenditure's own fiscal year — the chronological variant. The anchor is the study of the same association whose `fiscal_year` equals the expenditure's `fiscal_year` and whose status is `ADOPTED` or `SUPERSEDED`; when several studies qualify, the most recently created one — the greatest `created_at` — wins, and when none qualifies, the association's current `ADOPTED` study anchors instead. The planned amount under that anchor, stored as `planned_chronological_cents`, is the component's `current_replacement_cost_cents` grown at the anchor study's `inflation_rate`, compounded over the difference between the expenditure's `fiscal_year` and the anchor study's `fiscal_year`, rounded half-up to integer cents. `variance_chronological_cents` is then the actual `amount_cents` minus that planned amount. When the absolute value of the variance is no greater than the tolerance — the larger of 500 cents and ten percent of `planned_chronological_cents` rounded half-up — the expenditure's `reconciliation_status` is set to `MATCHED` automatically; otherwise it remains `UNRECONCILED`. Both chronological figures stay null until the expenditure reaches `APPROVED`, and both remain null when the association has no adopted study to anchor against.

A second, forward-looking reading accompanies every expenditure read. `planned_forward_cents` applies the same growth formula but anchors on the association's current `ADOPTED` study, whatever it happens to be at read time, and `variance_forward_cents` is the actual amount minus it. Because the anchor moves as studies are adopted and superseded, the forward pair is recomputed live on every read and diverges from the stored chronological pair whenever assumptions have changed since the expenditure's fiscal year; when the association has no adopted study at read time, both forward fields are null. Expenditures can be listed with `association_id`, `component_id`, `approval_status`, and `reconciliation_status` filters, and a single-expenditure read returns both reconciliation variants.

The board may reject a `SUBMITTED` expenditure outright: `approval_status` becomes `REJECTED` and `reconciliation_status` becomes `NOT_APPLICABLE`, terminal on both axes.

An approved expenditure may also be reversed, but only inside its own fiscal year: the fiscal year of the logical clock's current date must equal the expenditure's `fiscal_year`, and once the calendar has moved past it the request fails with `ERR_REVERSAL_WINDOW_CLOSED`. Reversal sets `approval_status` to `REVERSED` and `reconciliation_status` to `NOT_APPLICABLE`, credits the `amount_cents` back onto the association's `reserve_cash_balance_cents`, and subtracts the amount from the component's `actual_expenditure_cents`. For a `PLANNED_REPLACEMENT` it additionally restores the component's `remaining_useful_life_years` from the captured `component_rul_before_years` and recomputes `last_replaced_fiscal_year` as the greatest `fiscal_year` among the component's other `APPROVED` planned replacements, or null when none remain. The adopted study's totals are recomputed, the compliance posture is re-evaluated, and every touched resource's `version` advances.

Independently of approval, the specialist may accept an out-of-tolerance variance, moving `reconciliation_status` from `UNRECONCILED` to `VARIANCE_ACCEPTED`; the request may carry an optional `reason`, likewise accepted but not persisted or echoed. This transition touches only the reconciliation axis — `approval_status` is left untouched — and attempting it from any other reconciliation state fails with `ERR_INVALID_STATE`.

### 3.7. Member Disclosures

Two kinds of member disclosures exist, and both are created by the system rather than by any direct client call: an `ADOPTION_SUMMARY` is created when a study is adopted, and an `ANNUAL_STATEMENT` is created by each annual update. Both open in `PENDING` status with a `due_date` set `disclosure_deadline_days` after the date of creation, per the state rule. An `AssociationManager` distributes a pending disclosure to members, moving it from `PENDING` to `DISTRIBUTED` with `distributed_at` stamped from the logical clock; when the distribution date falls strictly after the `due_date`, `is_late` records true. When a study is superseded, its still-`PENDING` disclosures move to `VOIDED`, a terminal state, so a stale summary never reaches members as if it were current. A study's disclosures can be listed with optional `status` and `disclosure_type` filters.

An `ADOPTION_SUMMARY` disclosure carries `allocation_lines`, a per-component breakdown of the annual contribution of the plan named by the study's `adopted_plan_id`, computed when the disclosure is read. Each component's weight is the inflated cost of its first replacement falling inside the thirty-year projection horizon, computed exactly as the replacement schedule of §3.4 defines it; a component with no replacement inside the horizon weighs zero. When the sum of the weights is positive, each component's share is the floor of the total contribution multiplied by its weight and divided by the weight sum, and the leftover — the contribution minus the sum of the floored shares — is distributed one cent at a time to the components whose exact division left the largest fractional remainder, ties broken in favor of the component created earlier, with no component receiving more than one extra cent. When every weight is zero, the entire contribution falls to the component with the greatest `current_replacement_cost_cents` — ties again broken by earliest creation — and every other line is zero. Lines cover only components that are `ACTIVE` and included in funding, and are ordered by `created_at` ascending. Rounding each line independently would mis-sum the total and is explicitly not the rule: the floor-then-largest-remainder procedure is the specification. An `ANNUAL_STATEMENT` disclosure carries an empty `allocation_lines` list.

### 3.8. The Annual Update

Once per fiscal year, the specialist runs the annual update against an association — the ops checkpoint that ages the inventory and re-arms disclosure. The run requires a current `ADOPTED` study, failing with `ERR_NO_ADOPTED_STUDY` otherwise, and it may not repeat within a fiscal year: the current fiscal year under the logical clock must be strictly later than the association's `last_annual_update_fiscal_year` — a null value, as on a freshly onboarded association, always passes — or the run is rejected with `ERR_ANNUAL_UPDATE_ALREADY_RUN`.

The effects apply in a fixed order. First, every `ACTIVE` component of the current adopted study ages by one year: its `remaining_useful_life_years` decreases by one, floored at zero so a component already at the end of its life stays at zero, and every such component's `version` advances — including one whose remaining life was already zero and therefore does not change. Second, the study's `fully_funded_balance_cents` and `percent_funded` are recomputed against the aged inventory, advancing the study's `version`. Third, an `ANNUAL_STATEMENT` disclosure is created in `PENDING` status, its `due_date` set `disclosure_deadline_days` after the current date. Fourth, the association's `last_annual_update_fiscal_year` is stamped with the current fiscal year and the association's `version` advances. Fifth, the association's `statutory_compliance_status` is re-evaluated against the recomputed percent funded.

Between runs, the association's `annual_update_overdue` flag surfaces neglect: it is true whenever the state rule mandates annual updates — `annual_update_required` — and `last_annual_update_fiscal_year` is either null or earlier than the current fiscal year.

### 3.9. Special-Assessment Risk Analysis

For an adopted study, a computed read projects the association's position under its current funding behavior, answering the question every board asks: will the money run out? The read requires the addressed study to be `ADOPTED`; any other status fails with `ERR_INVALID_STATE`. The projection takes the association's `current_annual_contribution_cents` as the constant annual contribution — not any plan's solved contribution — and opens at the association's live `reserve_cash_balance_cents`, then advances through the same replacement schedule and the same interest-bearing year-step recursion as the contribution solve of §3.4, using the study's `interest_rate` and rounding half-up once per year-step.

A shortfall year is any projected year-end position, from the first through the thirtieth, whose balance is strictly negative — a balance of exactly zero is not a shortfall. The response carries four figures. `risk` is `AT_RISK` when at least one shortfall year exists and `NONE` otherwise. `first_shortfall_year` is the study's `fiscal_year` plus the one-based index of the earliest shortfall year-end position — a shortfall at the first projected year-end yields `fiscal_year` + 1 — or null when there is none. `projected_min_balance_cents` is the lowest year-end balance across the thirty-year projection. `max_shortfall_cents` is the depth of that trough: the negation of the minimum when the minimum is negative, and zero otherwise.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. All other successful operations — reads, updates, and state-transition actions — return `200 OK`. The table below summarizes the HTTP contract only; request payloads, response bodies, and side effects are specified by the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/state-reserve-rules` | Create the statutory reserve rule for a state | PlatformAdmin |
| POST | `/associations` | Create an association governed by an existing state rule | ReserveSpecialist |
| GET | `/associations/{id}` | Read one association, including computed compliance and cadence fields | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| POST | `/associations/{id}/annual-update` | Run the annual update: age the adopted study's inventory, recompute totals, create the annual statement disclosure | ReserveSpecialist |
| POST | `/reserve-studies` | Create a reserve study in DRAFT for an association | ReserveSpecialist |
| GET | `/reserve-studies/{id}` | Read one reserve study | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| GET | `/associations/{id}/reserve-studies` | List the studies of an association | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| GET | `/reserve-studies` | List and filter studies across associations | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| POST | `/reserve-studies/{id}/submit` | Submit a DRAFT study for board review | ReserveSpecialist |
| POST | `/reserve-studies/{id}/adopt` | Adopt a SUBMITTED study, superseding the prior adopted study | BoardMember |
| POST | `/reserve-studies/{id}/reject` | Reject a SUBMITTED study back to DRAFT | BoardMember |
| POST | `/reserve-studies/{id}/withdraw` | Withdraw a DRAFT study (terminal) | ReserveSpecialist |
| GET | `/reserve-studies/{id}/special-assessment-analysis` | Special-assessment risk projection for an ADOPTED study | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| POST | `/components` | Add a component to a DRAFT study | ReserveSpecialist |
| GET | `/reserve-studies/{id}/components` | List the components of a study | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| PATCH | `/components/{id}` | Update a component while its study is DRAFT | ReserveSpecialist |
| POST | `/components/{id}/retire` | Retire a component while its study is DRAFT | ReserveSpecialist |
| POST | `/components/{id}/restore` | Restore a retired component while its study is DRAFT | ReserveSpecialist |
| POST | `/reserve-studies/{id}/funding-plans` | Create a funding plan for a DRAFT study and solve its annual contribution | ReserveSpecialist |
| GET | `/reserve-studies/{id}/funding-plans` | List the funding plans of a study | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| POST | `/funding-plans/{id}/recommend` | Recommend a DRAFT plan, reverting any other recommendation | ReserveSpecialist |
| POST | `/funding-plans/{id}/select` | Select a plan while the study is SUBMITTED | BoardMember |
| POST | `/site-visits` | Schedule a site visit for an association | AssociationManager |
| POST | `/site-visits/{id}/complete` | Mark a SCHEDULED visit completed | AssociationManager |
| GET | `/associations/{id}/site-visits` | List the site visits of an association | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| POST | `/expenditures` | Submit an actual reserve expenditure | AssociationManager |
| GET | `/expenditures/{id}` | Read one expenditure, with the forward-looking variance recomputed live | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| GET | `/expenditures` | List expenditures with filters | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| POST | `/expenditures/{id}/approve` | Approve a SUBMITTED expenditure, debiting reserve cash and reconciling against plan | BoardMember |
| POST | `/expenditures/{id}/reject` | Reject a SUBMITTED expenditure | BoardMember |
| POST | `/expenditures/{id}/reverse` | Reverse an APPROVED expenditure inside its own fiscal year | BoardMember |
| POST | `/expenditures/{id}/accept-variance` | Accept an out-of-tolerance variance (reconciliation axis only) | ReserveSpecialist |
| GET | `/reserve-studies/{id}/disclosures` | List the disclosures of a study | PlatformAdmin, ReserveSpecialist, BoardMember, AssociationManager |
| POST | `/disclosures/{id}/distribute` | Distribute a PENDING disclosure to members | AssociationManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC) | PlatformAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return and its HTTP status code. The conditions under which each error triggers are specified throughout Sections 2 and 3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STATE_RULE_MISSING` | 422 |
| `ERR_STATE_RULE_EXISTS` | 409 |
| `ERR_STUDY_IN_PROGRESS` | 409 |
| `ERR_STUDY_WINDOW_OVERLAP` | 409 |
| `ERR_SITE_VISIT_TOO_SOON` | 409 |
| `ERR_SITE_VISIT_CADENCE` | 422 |
| `ERR_STUDY_EMPTY` | 409 |
| `ERR_NO_FUNDING_PLAN` | 409 |
| `ERR_STUDY_NOT_DRAFT` | 409 |
| `ERR_PLAN_ALREADY_SELECTED` | 409 |
| `ERR_PLAN_TYPE_LOCKED` | 409 |
| `ERR_NO_PLAN_SELECTED` | 409 |
| `ERR_PLAN_TYPE_NOT_ALLOWED` | 422 |
| `ERR_PERCENT_FUNDED_BELOW_MINIMUM` | 422 |
| `ERR_CASH_INSUFFICIENT` | 409 |
| `ERR_COMPONENT_NOT_CURRENT` | 409 |
| `ERR_NO_ADOPTED_STUDY` | 409 |
| `ERR_REVERSAL_WINDOW_CLOSED` | 409 |
| `ERR_ANNUAL_UPDATE_ALREADY_RUN` | 409 |
| `ERR_INTERNAL` | 500 |
