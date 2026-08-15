# Facility Condition Assessment & Capital Planning API — Product Requirements Document

## 1. Introduction

Owners of large building portfolios face a chronic information problem: they know their facilities are aging, but they lack a disciplined, auditable way to translate field observations into a defensible multi-year capital program. Consultants walk rooftops and mechanical rooms with clipboards, spreadsheets drift out of date, and the deferred-maintenance backlog quietly compounds while boards argue about which roof actually fails first. The Facility Condition Assessment & Capital Planning API replaces that sprawl with a single system of record that carries a facility from raw asset inventory through condition rating, deficiency finding, funding-scenario modeling, and finally an approved, phased capital plan.

The service is built around four cooperating roles. A `Consultant` performs the field work — registering clients and facilities, inventorying building systems, recording condition ratings and deficiency findings, and verifying corrected work. A `FacilityManager` acts on the client side: accepting or rejecting reassessments, driving remediation from start through completion, and retiring systems at end of life. A `CapitalPlanner` drafts multi-year capital plans, models alternative funding scenarios, and bundles funded work into execution phases. An `Approver` is the client executive who signs off on a submitted plan — but is deliberately barred from approving a plan they submitted themselves, enforcing segregation of duties between planning and approval.

Two commitments shape every part of the design. First, every derived number a stakeholder sees — a facility's current replacement value, its deferred-maintenance backlog, its facility condition index — is maintained transactionally as underlying data changes, so the numbers reported at any moment are always consistent with the events that produced them. Second, assessment data has a currency dimension: a formal refresh-cycle mechanism stamps each facility with an assessment epoch, requires every live system to be re-rated before a cycle closes, and exposes a refresh-health read that tells the owner at a glance whether their plan still rests on current observations or has gone stale.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/fca` prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles: `Consultant`, `FacilityManager`, `CapitalPlanner`, and `Approver`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`.

For every role in this system, `X-User-ID` is an **opaque operator identifier** — it is not tied to any persisted entity, and the server never compares it against a resource's `id`. This applies individually: when `X-User-Role` is `Consultant`, `X-User-ID` is an opaque consultant operator identifier; when it is `FacilityManager`, an opaque facility-manager identifier; when `CapitalPlanner`, an opaque planner identifier; when `Approver`, an opaque approver identifier. The one place the identifier takes on semantic weight is segregation of duties: when a plan is submitted, the server records the submitter's `X-User-ID`, and a later approval attempt whose `X-User-ID` equals that recorded submitter identity is rejected with `ERR_SEGREGATION_OF_DUTIES` — see §3.6.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter says how many items to skip before the first returned row and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order — oldest first.

Paginated list responses include four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`, so a client can always reconstruct where it sits in the full result set.

### 2.4. Common Resource Properties and the Facility Aggregate's Derived Fields

All primary resources — Client, Facility, AssetSystem, Deficiency, CapitalPlan, FundingScenario, PlanLineItem, ProjectBundle, and RefreshCycle — carry a standard set of system-managed properties:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control.

One resource deviates from this convention. A **ConditionSnapshot** is an immutable historical record — once written it is never modified — and therefore carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

Any event that touches a resource — including a side-effect cascade that recomputes a derived field on it — counts as a mutation of that resource and therefore refreshes its `updated_at` and increments its `version`. This matters most on the **Facility**, which acts as an aggregate root carrying three derived fields maintained entirely by side effects: `current_replacement_value_cents`, the sum of `replacement_cost_cents` over that facility's asset systems whose lifecycle status is anything other than `RETIRED`; `backlog_cost_cents`, the sum of `cost_estimate_cents` over the facility's deficiencies whose `remediation_status` is either `OPEN` or `IN_PROGRESS` (the deferred-maintenance backlog); and `facility_condition_index`, the ratio of the backlog to the current replacement value. When a facility has no live systems — that is, when the current replacement value is zero — the index is defined as 0 rather than being undefined. A freshly created Facility starts with all three of these fields at 0 and with `assessment_epoch` at 0, meaning its data has not yet been ratified against any refresh cycle.

### 2.5. Money, Precision, and Rounding

All monetary amounts in this system are integer counts of cents — `replacement_cost_cents`, `cost_estimate_cents`, `annual_budget_cents`, `escalated_cost_cents`, `total_programmed_cents`, and `bundled_cost_cents` are all exact integers with no fractional part, and all arithmetic over them is integer arithmetic.

Two computed values follow explicit rounding contracts. The `priority_score` on a Deficiency is rounded half-up to exactly 2 decimal places. The `facility_condition_index` on a Facility is rounded half-up to exactly 4 decimal places. Escalated costs used inside capital planning are rounded half-up to whole cents exactly once per item, at the final step of that item's calculation; a running budget remainder is never re-rounded mid-loop. Remaining-useful-life values are integer year counts with no rounding at all.

### 2.6. Optimistic Concurrency Control

Two write operations in this API carry mandatory optimistic concurrency protection, because each of them rewrites an aggregate that another client may have observed earlier. The version field is **not** optional on these endpoints, and no other endpoint accepts a version field at all.

First, creating a capital plan against a facility requires the request to carry `expected_facility_version`, set to the facility's `version` as the client last observed it. If the facility's current `version` has advanced past that value — for example because another planner has just created a plan for the same facility, which itself bumps the facility's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a planner from programming work against a facility aggregate they have not observed.

Second, running a funding scenario requires the request to carry `expected_capital_plan_version`, set to the owning plan's `version` as the client last observed it. A scenario run rewrites the plan's line items and bumps the plan's version, so a run issued from a stale plan view must be rejected with `ERR_STALE_VERSION` (HTTP 412) rather than allowed to silently double-allocate a program on top of a run it never saw.

### 2.7. Validation Order and Nested Resource Retrieval

Every request is screened by an ordered validation cascade, and the order is part of the contract — it determines which error a request with multiple problems surfaces. The checks run in this sequence:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers must be present and the role must be one of the four declared roles; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role must be permitted for this endpoint by the RBAC matrix; otherwise `ERR_UNAUTHORIZED`.
3. **Path existence** — every identifier embedded in the URL path (facility, asset-system, deficiency, capital-plan, funding-scenario, project-bundle, refresh-cycle) must exist, validated strictly left-to-right so the first missing identifier produces `ERR_NOT_FOUND`. A request for a refresh cycle under a facility that does not exist fails on the facility before the cycle is ever looked up.
4. **Body foreign keys** — every foreign-key identifier carried in the request body (`client_id`, `facility_id`, `asset_system_id`, `capital_plan_id`, `deficiency_id`, `funding_scenario_id`, `project_bundle_id`) must reference an existing resource; otherwise `ERR_REFERENCE_NOT_FOUND`.
5. **State legality** — the target resource must be in a state that permits the requested transition (submit requires `DRAFT`, approve requires `SUBMITTED`, verify requires `remediation_status` of `CORRECTED`, and so on); otherwise `ERR_INVALID_STATE`.
6. **Optimistic concurrency** — where an `expected_*_version` field is required, it must match the parent entity's current `version`; otherwise `ERR_STALE_VERSION`.
7. **Segregation of duties** — the approving `Approver`'s identity must differ from the submitting identity; otherwise `ERR_SEGREGATION_OF_DUTIES`.
8. **Code/accessibility hygiene** — a deficiency flagged as a code or accessibility violation must carry adequate severity; otherwise `ERR_CODE_SEVERITY_TOO_LOW`.
9. **Temporal range** — recommended and planned years must fall inside their permitted windows; otherwise `ERR_YEAR_OUT_OF_RANGE`.
10. **Field shape** — enum membership, integer ranges, and required-field presence; otherwise `ERR_INVALID_REQUEST`.
11. **Uniqueness** — one non-removed line item per deficiency within a plan, and one open refresh cycle per facility; otherwise `ERR_DUPLICATE`.
12. **Referential conflicts** — no deficiency on a retired system, no retirement with open deficiencies, no cross-plan bundle attachment; otherwise `ERR_REFERENTIAL_CONFLICT`.
13. **Cross-entity preconditions** — submit needs at least one funded item, cycle close needs every live system freshly assessed, archive needs all funded work closed out; otherwise `ERR_PRECONDITION_UNMET`.
14. **Fiscal shape** — a scenario's budget and escalation rate must be in range; otherwise `ERR_INVALID_BUDGET`.

Because the cascade is ordered, an early failure masks all later ones: an unauthenticated caller is told only about authentication, never about the state violations their payload would also have triggered.

### 2.8. The Server Logical Clock

Remaining-useful-life computation depends on knowing the current calendar year, and this system deliberately does not read the wall clock for that purpose. A server logical clock governs the notion of "now". At startup it reads exactly 2026-08-01T00:00:00Z — that is, the base year 2026 — and it must not fall back to wall-clock time before it has been explicitly set. A test-driving capability, exclusive to the `Consultant` role, sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The refresh-cycle record's `opened_at` timestamp is also stamped from this same logical clock. Advancing the clock changes what `current_calendar_year()` returns, which in turn changes remaining-useful-life results the next time they are computed — it does not retroactively rewrite already-stored values.

### 2.9. Hierarchical Consistency and Cascading Reconciliation

The resource hierarchy runs Client → Facility → AssetSystem → Deficiency, with CapitalPlan rooted at Facility and FundingScenario, PlanLineItem, and ProjectBundle rooted at CapitalPlan, and RefreshCycle rooted at Facility. Consistency is immediate, not eventual: whenever a child mutation changes an input to a parent's derived field, the parent's derived fields are recomputed as part of the same operation, and each such reconciliation refreshes the parent's `updated_at` and increments its `version`. The two deep cascades to be aware of are the retirement cascade (AssetSystem → PlanLineItem → CapitalPlan, §3.4) and the scenario-run cascade (FundingScenario → PlanLineItem → CapitalPlan, §3.7). Side-effect mutations on an entity also increment that entity's own `version` — state-transition endpoints always increment the acting resource's version by one, in addition to any parent recomputation.

## 3. Business Logic & Workflows

### 3.1. Clients, Facilities, and the Inventory Baseline

Work in this system begins when a `Consultant` registers a **Client** organization, supplying its legal `name` and a primary administrative `contact_email`. Under a client, the same consultant then registers each **Facility**, providing the owning `client_id`, the building or campus `name`, its street `address`, and its `gross_square_feet` — a strictly positive integer; a facility with zero or negative floor area is rejected with `ERR_INVALID_REQUEST`. A facility may be looked up individually or listed, and the facility list may be filtered by `client_id` when a portfolio spans several clients.

From the moment it is created, a facility carries the aggregate fields described in §2.4: `current_replacement_value_cents` at 0, `backlog_cost_cents` at 0, `facility_condition_index` at 0, and `assessment_epoch` at 0. Every subsequent event in this document — a system registered or retired, a deficiency recorded or remediated, a plan created, a cycle closed — flows into one or more of those fields.

Should the derived fields ever need to be forced back into agreement with the underlying rows, a `Consultant` may invoke the facility recompute capability, which re-runs the facility condition index calculation over the facility's live systems and open deficiencies, persists all three derived fields, and increments the facility's `version`.

### 3.2. Asset Inventory, Condition Rating, and Remaining Useful Life

Within a facility, a `Consultant` builds the asset inventory one **AssetSystem** at a time, naming the containing `facility_id`, a `system_category` drawn from the Uniformat-style enumeration `HVAC`, `ROOF`, `ENVELOPE`, `ELECTRICAL`, `PLUMBING`, `FIRE_PROTECTION`, `CONVEYANCE`, `INTERIOR`, `SITE`, or `STRUCTURE`, a human-readable `name` such as "Main Chiller", the `install_year` (a calendar year no earlier than 1900 and no later than 2100), the industry-standard `design_life_years` (a strictly positive integer), the present-day base-year `replacement_cost_cents` (an integer that may be zero but never negative), and the assessor's `condition_rating` on a scale of 1 (failed) to 5 (excellent). Violating any of these shapes is an `ERR_INVALID_REQUEST`. A new system starts in lifecycle `status` `ACTIVE`.

At registration the system computes the system's `remaining_useful_life_years`. The base variant works from raw age: the age in years is the current calendar year from the server logical clock minus the `install_year`; the remaining life is the `design_life_years` minus that age, floored at zero. Condition then overrides age: a `condition_rating` of 1 forces remaining life to 0 outright, and a `condition_rating` of 2 caps remaining life at no more than 2 years even if the raw arithmetic would allow more. Registering a system also immediately recomputes the facility's `current_replacement_value_cents` and `facility_condition_index`.

A stress-test variant of the same calculation exists for plan-health purposes: the **pessimistic** remaining useful life subtracts a further 2 years after all other adjustments, floored at zero. This variant never appears on the AssetSystem itself — `remaining_useful_life_years` always shows the base variant — but it drives the stressed-backlog figure in the refresh-health read (§3.9).

The systems of a facility may be listed through the facility's reverse-lookup collection, or across the portfolio filtered by `facility_id`; a single system may be read directly.

### 3.3. Reassessment Within a Refresh Cycle

Condition data goes stale, so reassessment is a first-class workflow rather than an ad-hoc edit. During an open refresh cycle, a `Consultant` records a fresh condition rating on a system by supplying the new `condition_rating` and an optional free-text `note`. This requires the system to be `ACTIVE` and an `OPEN` refresh cycle to exist for the owning facility; attempting to assess without an open cycle, or on a system that is not `ACTIVE`, is rejected with `ERR_INVALID_STATE`.

An accepted submission moves the system from `ACTIVE` to `REASSESSED` and triggers a chain of bookkeeping: `remaining_useful_life_years` is recomputed under the base variant, a **ConditionSnapshot** is appended capturing the `asset_system_id`, the new `condition_rating`, the recomputed `remaining_useful_life_years`, the facility's current `epoch`, and the `note`, and the system's `last_assessed_epoch` is set to the facility's current assessment epoch. The facility's derived fields are then recomputed — a rating change does not itself alter replacement cost, but the refreshed remaining-life data feeds plan-refresh metrics — and the system's `version` increments.

The decision then passes to the client side. A `FacilityManager` reviewing a `REASSESSED` system may accept the reassessment, returning the system to `ACTIVE` with the new values retained and the version incremented. Alternatively the manager may reject the reassessment: the system likewise returns from `REASSESSED` to `ACTIVE`, but as compensation its `condition_rating` and `remaining_useful_life_years` revert to the values stored on the most recent prior ConditionSnapshot, and the version increments. Either branch requires the system to currently be `REASSESSED`; acting on a system in any other state is `ERR_INVALID_STATE`. A facility's full snapshot history is available both per-system and as a flat list filterable by `asset_system_id` and `epoch`.

### 3.4. Deficiency Findings and the Backlog

The core field output of an assessment is the **Deficiency**. A `Consultant` records a finding on a specific system by posting its `asset_system_id` along with a free-text `description`, the present-day correction `cost_estimate_cents` (a strictly positive integer), a `severity` from 1 (minor) to 5 (critical) capturing the consequence of not correcting, an `urgency` from 1 (can wait years) to 5 (immediate), optional `is_code_violation` and `is_accessibility_violation` flags (both defaulting to false), and the `recommended_year` in which correction should occur. The recommended year must not be earlier than 2026 — the base year — and must lie between 2000 and 2200; a year before 2026 is rejected with `ERR_YEAR_OUT_OF_RANGE`.

Two guards protect the integrity of the finding stream. A deficiency flagged as a code violation or an accessibility violation must carry a `severity` of at least 3 — flagging life-safety or compliance exposure as minor is rejected with `ERR_CODE_SEVERITY_TOO_LOW`. And a deficiency may not be recorded on a system whose lifecycle `status` is `RETIRED`; that attempt is an `ERR_REFERENTIAL_CONFLICT`.

Every deficiency receives a computed `priority_score` at creation: the severity multiplied by a weight of 0.6, plus the urgency multiplied by a weight of 0.4, plus a bonus of 10 when the finding is a code violation, plus a further bonus of 5 when it is an accessibility violation — the total rounded half-up to 2 decimal places. This score is the primary sort key for capital allocation later. Recording the deficiency also immediately adds its cost into the facility's `backlog_cost_cents` and recomputes the `facility_condition_index`.

A new deficiency starts life with `remediation_status` of `OPEN` and `verification_status` of `UNVERIFIED` — two parallel state dimensions that evolve independently. Deficiencies may be listed with filters on `asset_system_id`, `remediation_status`, `is_code_violation`, and `is_accessibility_violation`, or read individually.

### 3.5. Remediation and Verification: The Dual-Axis Close-Out

Remediation is driven by the `FacilityManager`. Starting remediation on an `OPEN` finding moves `remediation_status` from `OPEN` to `IN_PROGRESS`; because in-progress work still represents uncorrected liability, it remains inside the backlog set, and the facility's backlog and index are recomputed to confirm that. Completing remediation moves `remediation_status` from `IN_PROGRESS` to `CORRECTED`, which finally lifts the cost out of the backlog set and recomputes the facility's `backlog_cost_cents` and `facility_condition_index` accordingly. Completion is only legal while the owning system's lifecycle status is not `RETIRED` — a finding cannot be closed out on dead equipment — and the acting deficiency must actually be in the required prior state, else `ERR_INVALID_STATE`. Each of these transitions increments the deficiency's `version`.

A finding can also be deliberately pushed out: deferring moves `remediation_status` from `OPEN` to `DEFERRED`, and reopening reverses it from `DEFERRED` back to `OPEN`. Neither transition changes backlog membership — deferred items remain in the backlog alongside open ones — so no facility recomputation occurs on either, though the deficiency's `version` still increments on each.

Verification is the independent check, performed by a `Consultant` rather than the manager who did the work, and it operates on the second axis. Verifying corrected work requires `remediation_status` of `CORRECTED` with `verification_status` still `UNVERIFIED`; success moves verification to `VERIFIED`, which is the terminal close-out state for a finding, and appends a ConditionSnapshot to the owning AssetSystem recording its current rating and remaining life. Rejecting corrected work requires the same preconditions but moves `verification_status` to `REJECTED` and, as compensation, drives `remediation_status` back to `IN_PROGRESS` — the finding re-enters the backlog set, so the facility's backlog and index are recomputed, and the deficiency's `version` increments. Work funded through an approved capital plan also enters `IN_PROGRESS` automatically at approval time; that path is described in §3.6.

### 3.6. The Capital Plan Lifecycle: Draft, Submit, Approve, Archive

A `CapitalPlanner` frames a **CapitalPlan** against a facility by supplying the `facility_id`, a `title` such as "FY2027-FY2031 Capital Plan", the `start_year` (between 2000 and 2200), and a `horizon_years` span of at least 1 and at most 10 years — horizons outside that band are `ERR_INVALID_REQUEST`. Because plan creation mutates the facility aggregate, the request must also carry `expected_facility_version` under the optimistic concurrency rule of §2.6; a stale view is rejected with `ERR_STALE_VERSION`. A new plan starts in `status` `DRAFT` with `total_programmed_cents` at 0, and its creation increments the owning facility's `version`. Plans may be listed and filtered by `facility_id` or `status`, and read individually.

The plan's approval lifecycle is a branching machine with a revision loop. Submission by a `CapitalPlanner` moves a plan from `DRAFT` to `SUBMITTED` and requires the program to be non-empty: at least one line item of the plan must have `funding_status` of `FUNDED`, otherwise the submission is rejected with `ERR_PRECONDITION_UNMET`. Submission has a portfolio-level side effect — if another plan for the same facility is currently `APPROVED`, that prior plan moves automatically to `SUPERSEDED`; its funded line items remain on the record, but no further bundles may attach to it. Submission increments the plan's `version`.

Approval belongs to the `Approver` and moves the plan from `SUBMITTED` to `APPROVED`. Segregation of duties is enforced here: the approving identity must differ from the identity that submitted the plan, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. On approval, every funded line item's linked deficiency has its `remediation_status` advanced from `OPEN` to `IN_PROGRESS`; deficiencies already `DEFERRED` or already `IN_PROGRESS` are left exactly as they are. Because open findings have now moved into in-progress work (both remain in the backlog set, but the membership mix changed), the facility's `backlog_cost_cents` and `facility_condition_index` are recomputed, and the plan's `version` increments.

An `Approver` may instead reject a submitted plan, moving it from `SUBMITTED` to `REJECTED` with the version incremented. Rejection is not terminal: a `CapitalPlanner` may revise the plan, moving it from `REJECTED` back to `DRAFT` — again incrementing the version — after which scenarios may be re-run and the plan resubmitted.

Finally, once an approved program has run its course, a `CapitalPlanner` may archive the plan, moving it from `APPROVED` to `ARCHIVED`. Archival is gated on close-out: every deficiency linked by the plan's funded line items must have `remediation_status` of either `CORRECTED` or `DEFERRED`; any funded finding still open or in progress causes the archive attempt to be rejected with `ERR_PRECONDITION_UNMET`. A successful archive increments the plan's version. Both `APPROVED` and `ARCHIVED` are terminal states of the plan machine.

### 3.7. Funding Scenarios and the Waterfall Allocation

Under a draft plan, a `CapitalPlanner` configures one or more **FundingScenario** alternatives — a `capital_plan_id`, a `name` such as "Baseline" or "Aggressive", a uniform `annual_budget_cents` envelope applied to every plan year, and an `annual` cost `escalation_rate` expressed as a decimal fraction. The budget must be a strictly positive integer and the escalation rate must lie between 0 and 0.25 inclusive; a non-positive budget or an out-of-range rate is rejected with `ERR_INVALID_BUDGET`. A new scenario starts in `status` `CONFIGURED`.

Running a scenario is the heart of capital planning. It requires the scenario to still be `CONFIGURED` and the owning plan to still be `DRAFT` — running against a plan that has moved on is `ERR_INVALID_STATE` — and it is the second OCC-protected write: the request must carry `expected_capital_plan_version` matching the plan's current `version`, or the run is rejected with `ERR_STALE_VERSION`.

The run executes the **waterfall allocation**. The candidate pool is every deficiency of the plan's facility whose `remediation_status` is `OPEN` or `DEFERRED`, whose owning system is not `RETIRED`, and whose `recommended_year` falls inside the plan horizon — that is, no earlier than `start_year` and no later than `start_year` plus `horizon_years` minus 1. Candidates are ordered deterministically: highest `priority_score` first, with ties broken by earlier `created_at`; resource identifiers are never used as a tiebreaker. The allocator then walks the plan years in order from `start_year` through the final horizon year. For each year, it starts with a full `annual_budget_cents` remaining and considers, in the sorted order, exactly those candidates whose `recommended_year` equals that plan year. For each candidate it computes the escalated cost of correcting the finding in its recommended year; if that cost fits within the year's remaining budget, a **PlanLineItem** is created with `funding_status` `FUNDED`, the budget remainder is reduced by the cost, and the allocator moves on; if it does not fit, the line item is still created but with `funding_status` `UNFUNDED`, and the remainder is unchanged. A single candidate whose escalated cost exceeds the entire annual budget is therefore simply `UNFUNDED` — it is not an error condition. One uniqueness invariant holds across runs: at most one non-`REMOVED` line item may exist per plan per deficiency, and a run that would violate this is rejected with `ERR_DUPLICATE`.

Each line item's `escalated_cost_cents` compounds the deficiency's present-day `cost_estimate_cents` forward from the base year 2026 to the item's `planned_year` at the scenario's `escalation_rate`: the number of compounding years is the planned year minus 2026, and the escalated amount is the estimate multiplied by one-plus-the-rate raised to that power, rounded half-up to a whole cent exactly once, before any budget comparison. The per-year budget remainders are never re-rounded. For reporting outside planning — the facility backlog and deficiency listings — the same cost appears unescalated: the escalation rate is treated as zero, which is to say the `cost_estimate_cents` exactly as recorded.

A run has one supersession cascade. Any other scenario of the same plan already in `RUN` status moves to `SUPERSEDED`, and all of its non-removed line items move to `REMOVED`. The plan's `total_programmed_cents` — always the sum of `escalated_cost_cents` over the plan's `FUNDED` line items — is then recomputed, and the plan's `version` increments. `RUN` and `SUPERSEDED` are both terminal states for a scenario. Line items may be listed with filters on `capital_plan_id`, `funding_scenario_id`, `deficiency_id`, `funding_status`, and `project_bundle_id`, and read individually.

### 3.8. Project Bundling and Phasing

Approved programs execute in phases, and **ProjectBundle** resources give the `CapitalPlanner` that grouping. A bundle is created under a plan with a `capital_plan_id`, a `name` such as "Roof & Envelope Phase 1", and a `phase_number` of at least 1 where 1 denotes the earliest phase; its `bundled_cost_cents` starts at 0.

Attaching a line item to a bundle is done by posting the `plan_line_item_id`. The attachment sets the item's `project_bundle_id` — which is otherwise null for unbundled work — and recomputes the bundle's `bundled_cost_cents` as the sum of `escalated_cost_cents` over the line items attached to it that remain `FUNDED`. Two constraints guard the operation: the attached item must belong to the same capital plan as the bundle — cross-plan attachment is an `ERR_REFERENTIAL_CONFLICT` — and, per §3.6, no bundle may attach to a plan that has been superseded. Each attach increments the bundle's `version`. Bundles may be read individually or listed through their plan.

Retirement interacts with bundling through the plan layer, and this is the deepest cascade in the system. A `FacilityManager` may retire a system only while it is `ACTIVE` and only when none of its deficiencies have `remediation_status` of `OPEN` or `IN_PROGRESS` — retiring with unresolved findings is `ERR_REFERENTIAL_CONFLICT`. Retirement moves the system to the terminal `RETIRED` state, recomputes the facility's `current_replacement_value_cents` (which now excludes the retired system) and `facility_condition_index`, and sweeps the plan layer: any line item that references a deficiency of the retired system, has `funding_status` of `FUNDED`, and belongs to a plan still in `DRAFT` is moved to `REMOVED`, after which that plan's `total_programmed_cents` is recomputed. The system's `version` increments.

### 3.9. Refresh Cycles and Plan Health

Data currency is managed per facility through **RefreshCycle** resources. A `Consultant` opens the first cycle for a facility, and the server assigns it `epoch` 1; each subsequent cycle takes the highest prior epoch for that facility plus one. Only one cycle per facility may be `OPEN` at a time — opening a second is `ERR_DUPLICATE`. The cycle records the server logical clock in `opened_at` and starts in `status` `OPEN`. A facility's cycles may be listed through its reverse-lookup collection.

Closing a cycle is the ratification step, performed by a `Consultant`, and it is gated: every non-`RETIRED` system of the facility must have its `last_assessed_epoch` equal to the closing cycle's epoch — any system not re-rated during this cycle leaves the close rejected with `ERR_PRECONDITION_UNMET`, and acting on a cycle not `OPEN` is `ERR_INVALID_STATE`. A successful close moves the cycle to the terminal `CLOSED` state, sets the facility's `assessment_epoch` to the closed cycle's epoch, and automatically opens the next cycle for the same facility with the following epoch.

Any stakeholder may then consult the facility's **refresh health**, a computed read answering whether the plan still rests on current data. The read counts `stale_systems` — live systems whose `last_assessed_epoch` has fallen behind the facility's `assessment_epoch` — and `total_systems`, the count of all non-retired systems. It also computes `stressed_backlog_cents`: the sum of `cost_estimate_cents` over the facility's open or in-progress deficiencies whose owning system's pessimistic remaining useful life (the stress-test variant of §3.2) has reached zero — work sitting on systems that could fail before the plan gets to them. The headline `health` classification is decided in a fixed order: when the facility has no live systems at all, it reports `NO_DATA`; otherwise, when any system is stale, it reports `STALE`; otherwise the stored four-decimal facility condition index is compared against two bands — an index of at least 0.10 reports `CRITICAL`, an index of at least 0.05 reports `WATCH`, and anything below reports `GOOD`. A value exactly at a band threshold enters the worse band, because both comparisons are inclusive.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code with the created resource in the `data` field. Operations that modify an existing resource — including all state-transition actions, scenario runs, attaches, recomputes, and the clock set — return a `200 OK` with the updated resource. All list and single-resource reads return `200 OK`. Errors follow the envelope of §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fca/clients` | Create a client organization | Consultant |
| GET | `/fca/clients` | List clients (paginated) | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/clients/{id}` | Get one client | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/facilities` | Create a facility under a client | Consultant |
| GET | `/fca/facilities` | List facilities, optionally filtered by `client_id` | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/facilities/{id}` | Get one facility with computed FCI/backlog fields | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/facilities/{id}/refresh-health` | Computed read of refresh health for this facility | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/facilities/{id}/recompute` | Force recompute of CRV/backlog/FCI derived fields | Consultant |
| GET | `/fca/facilities/{id}/asset-systems` | List asset systems of a facility | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/facilities/{id}/capital-plans` | List capital plans of a facility | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/facilities/{id}/refresh-cycles` | List refresh cycles of a facility | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/asset-systems` | Register a system in a facility's inventory | Consultant |
| GET | `/fca/asset-systems` | List asset systems, optionally filtered by `facility_id` | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/asset-systems/{id}` | Get one asset system | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/asset-systems/{id}/assess` | Consultant records a new condition rating during an open refresh cycle | Consultant |
| POST | `/fca/asset-systems/{id}/accept-assessment` | FacilityManager accepts the reassessment | FacilityManager |
| POST | `/fca/asset-systems/{id}/reject-assessment` | FacilityManager rejects the reassessment; values revert to last snapshot | FacilityManager |
| POST | `/fca/asset-systems/{id}/retire` | Retire a system (no open deficiencies allowed) | FacilityManager |
| GET | `/fca/asset-systems/{id}/deficiencies` | List deficiencies of a system | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/asset-systems/{id}/condition-snapshots` | List condition snapshots of a system | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/deficiencies` | Record a deficiency finding on a system | Consultant |
| GET | `/fca/deficiencies` | List deficiencies with filters | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/deficiencies/{id}` | Get one deficiency | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/deficiencies/{id}/start-remediation` | Begin remediation (`OPEN` → `IN_PROGRESS`) | FacilityManager |
| POST | `/fca/deficiencies/{id}/complete-remediation` | Mark remediation complete (`IN_PROGRESS` → `CORRECTED`) | FacilityManager |
| POST | `/fca/deficiencies/{id}/defer` | Defer an open deficiency (`OPEN` → `DEFERRED`) | FacilityManager |
| POST | `/fca/deficiencies/{id}/reopen` | Reopen a deferred deficiency (`DEFERRED` → `OPEN`) | FacilityManager |
| POST | `/fca/deficiencies/{id}/verify` | Consultant verifies corrected work (`UNVERIFIED` → `VERIFIED`) | Consultant |
| POST | `/fca/deficiencies/{id}/reject-verification` | Consultant rejects corrected work; remediation reverts to `IN_PROGRESS` | Consultant |
| POST | `/fca/capital-plans` | Create a draft capital plan for a facility (OCC on facility version) | CapitalPlanner |
| GET | `/fca/capital-plans` | List capital plans with filters | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/capital-plans/{id}` | Get one capital plan | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/capital-plans/{id}/submit` | Submit a draft plan for approval | CapitalPlanner |
| POST | `/fca/capital-plans/{id}/approve` | Approve a submitted plan (segregation of duties enforced) | Approver |
| POST | `/fca/capital-plans/{id}/reject` | Reject a submitted plan | Approver |
| POST | `/fca/capital-plans/{id}/revise` | Return a rejected plan to draft | CapitalPlanner |
| POST | `/fca/capital-plans/{id}/archive` | Archive an approved plan once funded work is closed out | CapitalPlanner |
| GET | `/fca/capital-plans/{id}/funding-scenarios` | List funding scenarios of a plan | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/capital-plans/{id}/plan-line-items` | List line items of a plan | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/capital-plans/{id}/project-bundles` | List project bundles of a plan | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/funding-scenarios` | Create a funding scenario under a draft plan | CapitalPlanner |
| GET | `/fca/funding-scenarios/{id}` | Get one funding scenario | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/funding-scenarios/{id}/run` | Run the waterfall allocation for this scenario (OCC on plan version) | CapitalPlanner |
| GET | `/fca/plan-line-items` | List plan line items with filters | Consultant, FacilityManager, CapitalPlanner, Approver |
| GET | `/fca/plan-line-items/{id}` | Get one plan line item | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/project-bundles` | Create a project bundle (phase grouping) under a plan | CapitalPlanner |
| POST | `/fca/project-bundles/{id}/attach` | Attach a funded line item to this bundle | CapitalPlanner |
| GET | `/fca/project-bundles/{id}` | Get one project bundle | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/facilities/{id}/refresh-cycles` | Open the next refresh cycle for a facility | Consultant |
| POST | `/fca/refresh-cycles/{id}/close` | Close a refresh cycle once all live systems are assessed in this epoch | Consultant |
| GET | `/fca/condition-snapshots` | List condition snapshots with filters | Consultant, FacilityManager, CapitalPlanner, Approver |
| POST | `/fca/_clock/set_current_utc` | Test-driving endpoint — set the server logical clock | Consultant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CODE_SEVERITY_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_YEAR_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_REFERENTIAL_CONFLICT` | 409 Conflict |
| `ERR_PRECONDITION_UNMET` | 409 Conflict |
| `ERR_INVALID_BUDGET` | 422 Unprocessable Entity |
