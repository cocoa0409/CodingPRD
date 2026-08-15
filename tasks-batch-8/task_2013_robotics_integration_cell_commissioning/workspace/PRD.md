# Robotics Integration & Cell Commissioning API — Product Requirements Document

## 1. Introduction

A robotic system integrator lives and dies by two numbers: the cycle time it contractually guarantees and the retention it collects only after the customer agrees the cell performs. Between those two numbers sits a long, evidence-heavy commissioning engagement — an application study with offline cycle-time simulation, a safety risk assessment that sizes fencing and light curtains, robot and end-effector selection with payload verification, program development under peer review, factory and site acceptance tests, spare-parts and preventive-maintenance provisioning, operator and technician training, and finally a production throughput guarantee measured on the customer's floor.

This document specifies the Robotics Integration & Cell Commissioning API, the system of record for that engagement. It serves integration firms certified on `FANUC`, `ABB`, or both robot brands, and it models every artifact the engagement produces — from the first simulated cycle time to the last cent of released retention. The API enforces segregation of duties between the engineers who create technical evidence and the leads who approve it, optimistic concurrency on the commercial writes most exposed to stale reads, and an explicit logical clock so that training windows, guarantee windows, and no-show detection behave deterministically. All resources are served under the `/robotics` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold for every endpoint in the API. Where §3 narrates workflows, this section states invariants.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The declared role must be one of seven exact spellings: `ProjectEngineer`, `SafetyLead`, `ControlsProgrammer`, `SiteSupervisor`, `Trainer`, `ServiceManager`, and `FinanceAdmin`. A request missing either header, carrying an empty `X-User-ID`, or carrying a role string outside this set is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

All seven roles are entity-backed. When `X-User-Role` is `ProjectEngineer`, `SafetyLead`, `ControlsProgrammer`, `SiteSupervisor`, `Trainer`, `ServiceManager`, or `FinanceAdmin`, `X-User-ID` is the `id` of the acting `IntegratorUser`; ownership checks on any resource that references an `IntegratorUser` — a training session's `trainer_user_id`, an assessment's `approved_by_safety_lead_id`, an acceptance test's `recorded_by_user_id` — compare the resource's stored user reference to `X-User-ID`. This binding is what makes the segregation-of-duties and trainer-scoring rules of §3 enforceable: the server always knows which persisted user is acting.

The `IntegratorUser` record itself belongs to an org via `integrator_org_id` and carries a `display_name`, a `user_role` attribute with one of the values `PROJECT_ENGINEER`, `SAFETY_LEAD`, `CONTROLS_PROGRAMMER`, `SITE_SUPERVISOR`, `TRAINER`, `SERVICE_MANAGER`, or `FINANCE_ADMIN` recording the user's functional role inside the integrator org, and an `active` flag recording whether the user may act, defaulting to true.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource carries four system-managed properties:

- `id` — a server-minted UUID with no type prefix, assigned at creation.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification.
- `version` — an integer starting at 1 and incrementing on every mutation of the resource.

Exactly one entity breaks this pattern: the `RetentionLedgerEntry` carries only `id` and `created_at`. Both `updated_at` and `version` are absent from ledger entries, because ledger postings are append-only and never modified after posting.

Server-side recomputation of derived fields counts as mutation: when the server recomputes a project's `retention_balance_cents`, a package's `forecast_consumption_months`, or a plan's `hours_until_due`, the owning resource's `updated_at` refreshes and its `version` increments. Cascading transitions triggered by a parent operation follow the same rule on every resource they touch.

### 2.5. Hierarchical Validation of Nested Resources

Paths in this API are deeply nested — an organization contains customer sites, a site contains cell projects, and a project contains every engineering artifact. For any request whose path contains multiple identifiers (for example, `/robotics/integrator-orgs/{id}/customer-sites/{id}`), the server validates existence strictly left-to-right: organization first, then site, then project, then the child resource. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource, and no later validation runs. A request aimed at a child beneath a non-existent parent therefore reports the missing parent, never a child-level failure.

### 2.6. Request Evaluation Order

When several checks could reject the same request, the server evaluates them on a fixed ladder and reports the first failure encountered. The ladder, from first to last, is:

1. Authentication of the request headers — `ERR_UNAUTHENTICATED` (HTTP 401).
2. Role authorization for the target endpoint — `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. Left-to-right existence of path resources — `ERR_NOT_FOUND` (HTTP 404).
4. Whether the target entity stands in a state from which the requested transition is defined — `ERR_INVALID_STATE` (HTTP 409).
5. Optimistic-concurrency freshness on version-guarded writes — `ERR_STALE_PROJECT_VERSION` (HTTP 412).
6. Safety-level sufficiency on assessment approval — `ERR_SAFETY_LEVEL_INSUFFICIENT` (HTTP 422).
7. Segregation of duties on study approval, assessment approval, and program peer review — `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).
8. Payload-margin and wrist-inertia adequacy on selection validation — `ERR_PAYLOAD_CHECK_FAILED` (HTTP 422).
9. Brand scope on selection validation — `ERR_BRAND_OUT_OF_SCOPE` (HTTP 422).
10. Session-window compliance on training start — `ERR_OUTSIDE_SESSION_WINDOW` (HTTP 422).
11. Guarantee-window compliance on guarantee close and waive — `ERR_GUARANTEE_WINDOW_VIOLATION` (HTTP 422).
12. Trainer scheduling on session creation — `ERR_TRAINER_SCHEDULE_CONFLICT` (HTTP 422).
13. Supersede-target validity on study creation — `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 422).
14. Project-code and program-name uniqueness — `ERR_DUPLICATE_CODE` (HTTP 409).
15. Retention conservation on ledger postings and guarantee closure — `ERR_RETENTION_OVERRELEASE` (HTTP 422).
16. Retention-balance sufficiency on retention-releasing advances — `ERR_RETENTION_BALANCE_MISMATCH` (HTTP 422).
17. Maintenance-window validity on plan activation — `ERR_MAINTENANCE_WINDOW_INVALID` (HTTP 422).
18. Required-field presence, types, and numeric ranges — `ERR_INVALID_REQUEST` (HTTP 400).
19. The advance gate's child-state preconditions — `ERR_GATE_PRECONDITION_UNMET` (HTTP 422).

The practical consequence: a request that is unauthenticated and malformed fails with the authentication error; a stale-version advance that would also fail a child-state gate reports the staleness, not the gate.

### 2.7. Optimistic Concurrency Control on Project Writes

Three writes are guarded against the parent `CellProject`'s `version`, and each requires the request to carry `expected_project_version` holding the client's last observed project version:

- `POST /robotics/cell-projects/{id}/application-studies` — creating (or superseding) a study. If the project's version has advanced since the client last read it, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), because a prior supersede may already have replaced the very study the client intended to supersede.
- `POST /robotics/cell-projects/{id}/advance` — advancing the project to its next stage. A version mismatch is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), because an intervening mutation — for example the cascade from a recorded acceptance test — may have changed the gate preconditions the client relied on.
- `POST /robotics/cell-projects/{id}/retention-ledger-entries` — posting a manual adjustment. A mismatch is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), so the adjustment is always computed against a current balance.

`expected_project_version` is a non-optional input on these three endpoints. Endpoints not listed here do not accept a version field at all.

### 2.8. Monetary Values and the Retention Ledger

All monetary quantities are integer cents. Every project owns a retention ledger, and the project's `retention_balance_cents` is a derived figure recomputed from the project's `RetentionLedgerEntry` postings after every entry. Each entry carries an `entry_type` of `WITHHOLD`, `RELEASE`, `PENALTY`, or `ADJUST`; a signed `amount_cents`, with `RELEASE` and `PENALTY` postings negative against the balance while `WITHHOLD` and `ADJUST` follow the sign convention of the entry itself; a `milestone_ref` naming the milestone that authorized the movement — an acceptance test's `id`, a throughput guarantee's `id`, or the literal string `MANUAL` for hand-posted corrections; and a server-stamped `recorded_at_utc` recording when the posting was made.

Conservation is absolute: no posting may drive `retention_balance_cents` below zero, and any posting that would is rejected with `ERR_RETENTION_OVERRELEASE` (HTTP 422). This rule binds both hand-posted adjustments and the automatic postings made when a guarantee closes.

### 2.9. Computed Values and Rounding Conventions

Every computed quantity in the system rounds half-up; only the retained precision varies by quantity. The derated cycle time of an application study retains three decimal places. Percentages produced by the payload-margin check and the throughput-shortfall computation retain two. The training completion score, the safety-function budget percentage, and the spare-parts consumption forecast retain one. Retention amounts are whole cents, rounded half-up at each pinned step of the release schedule in the order that schedule states, rather than once at the end. Input fields keep the precision the client supplies; rounding applies to computed fields only.

### 2.10. The Logical Clock

The server keeps a logical clock, and every time-dependent rule in this document — training session windows, no-show detection, guarantee window boundaries — reads that clock and never the wall clock; the logical clock never falls back to wall-clock time. Before it has ever been set, the logical clock reads exactly 2026-08-01T00:00:00Z. A `FinanceAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant.

Setting the clock triggers exactly one time-driven effect: any training session still `SCHEDULED` whose scheduled window has fully elapsed — that is, the clock has moved past its `scheduled_end_utc` — transitions to `NO_SHOW`. No other time-driven transitions exist anywhere in the system.

### 2.11. Performance Level Conventions

Safety functions are graded on the ISO 13849-1 performance-level scale used throughout this API: `PLc`, `PLd`, and `PLe`, where `PLc` ranks below `PLd` and `PLd` ranks below `PLe`. An integrator org declares a `default_pl_category_target` as its standard target level; each safety risk assessment then carries its own `pl_target` alongside a computed `pl_achieved`. Every comparison between performance levels — in approval gates and in stage gates alike — uses this ordering.

### 2.12. Cascades and Hierarchical Consistency

A cell project is the root of a deep hierarchy: studies, assessments, robot selections, programs, acceptance tests, spare-parts packages, maintenance plans, training sessions, a throughput guarantee, and the retention ledger all hang beneath it, each carrying a `cell_project_id` that ties the artifact back to its commissioning project. When the project undergoes rework or termination, the server does not leave children stranded in now-impossible states — it automatically transitions every affected child to the state the cascade defines, without requiring a separate client request per child. Every such cascade is itself a mutation of the project: `updated_at` refreshes and `version` increments by exactly one, which is precisely the movement the concurrency rules of §2.7 key on. The detailed cascades are specified with their workflows in §3.

## 3. Business Logic & Workflows

### 3.1. Organization Setup, Customer Sites, and Project Intake

A `FinanceAdmin` onboards the integrator organization itself, supplying its registered `legal_name`, a `brand_specialization` of `FANUC`, `ABB`, or `DUAL` recording which robot brands the org is certified to integrate, a `retention_rate_bps` carrying the default contractual retention withheld from milestone invoices in basis points — one hundred basis points make one percent, and the rate must sit between 0 and 2000 inclusive — and a `default_pl_category_target` of `PLc`, `PLd`, or `PLe`. Organizations can be listed (a `FinanceAdmin`-only view) and fetched individually by any role.

Under the org, the same `FinanceAdmin` enrolls each `IntegratorUser` with a `display_name`, a `user_role`, and optionally an `active` flag that defaults to true. The org's roster is listable, individual users are fetchable, and each user exposes three reverse listings that later sections rely on: the safety risk assessments that user has approved, the acceptance tests that user has recorded, and the training sessions assigned to that user as trainer.

A `ProjectEngineer` then registers each `CustomerSite` beneath the org with a human-readable `site_name`, a `plant_tz` holding the IANA timezone of the plant floor that drives shift-window boundary computations, and a `shift_windows_per_day` count between one and three inclusive that feeds the throughput mathematics. Sites are listable per org and fetchable individually by any role. The engineer may later update a site's `site_name`, `plant_tz`, or `shift_windows_per_day`; changing the shift count has a forecasting consequence spelled out in §3.7.

Under a site, the engineer opens a `CellProject` — the record carries a `customer_site_id` binding it to the commissioning site — with a customer-facing `project_code` that is unique within the site, collisions rejected by `ERR_DUPLICATE_CODE` (HTTP 409), a `contracted_cycle_time_s` strictly greater than zero, a `contract_value_cents` strictly greater than zero, a `guaranteed_oee_pct` between 50.0 and 99.9 inclusive, and optionally a `guarantee_window_days` that defaults to 90 and must lie between 30 and 365 inclusive. The project opens in `DRAFT` status with `hold_reason` null and `rework_count` at zero. Creation also opens the retention story: the system multiplies `contract_value_cents` by the owning org's `retention_rate_bps`, divides by ten thousand, rounds half-up to a whole cent, seeds `retention_balance_cents` with the result, and posts the opening `WITHHOLD` ledger entry against the project. The site's project list is paginated and filterable by `status`.

Two lifecycle controls apply at nearly every stage. A `ProjectEngineer` may place any project that is neither `CLOSED` nor `TERMINATED` into `ON_HOLD`, supplying a `hold_reason` that the project carries while held; resuming is the only exit from `ON_HOLD`, and it restores exactly the status captured at hold time while clearing `hold_reason`. Both operations increment the project's `version` by one. The third control, termination, belongs to `FinanceAdmin` and is specified with the rest of settlement in §3.9.

### 3.2. Application Studies and Feasibility Analysis

Every engagement begins by proving the cell can hit its contractual beat. Advancing a project from `DRAFT` to `STUDY` — a `ProjectEngineer` action — merely unlocks study work; it creates no study by itself, and it is permitted only while no application study for the project currently sits in `DRAFT` or `SUBMITTED`. A study is then created against the project with a payload carrying `expected_project_version` (the write is version-guarded per §2.7), the engineer's `sim_cycle_time_s` from offline simulation, a `sim_confidence_pct` greater than zero and at most 100, and optionally a `supersedes_study_id`. Every study creation increments the parent project's `version` by one.

Supersedure is the self-referential heart of study work. When `supersedes_study_id` is present it must reference an application study of the same project whose status is `APPROVED`, or the create is rejected with `ERR_SUPERSEDE_TARGET_INVALID`; the project must also stand in `STUDY` or `DESIGN` for supersedure to be legal. A valid supersede moves the prior study from `APPROVED` to `SUPERSEDED` and opens the new study in `DRAFT` with its `revision` counter set one higher than the study it replaces; a project's first study carries `revision` 1 and a null `supersedes_study_id`. The project's study list is filterable by `status` and by `supersedes_study_id`, and every study exposes the reverse listing of the studies that supersede it.

Submitting a study — again a `ProjectEngineer` action, legal only while the project is in `STUDY` and only once `sim_cycle_time_s` and `sim_confidence_pct` are populated — moves the study from `DRAFT` to `SUBMITTED` and computes its two derived fields. The `adjusted_cycle_time_s` is the simulated cycle time divided by one-hundredth of the confidence percentage, rounded half-up to three decimal places; the `feasibility` verdict is `FEASIBLE` when the adjusted time does not exceed the project's `contracted_cycle_time_s`, `MARGINAL` when it exceeds the contract but stays at or under one hundred and ten percent of it, and `INFEASIBLE` beyond that. This derated figure is the provisional, simulation-side estimate; the acceptance workflow of §3.6 uses the measured cycle time directly with no confidence derating, so the same cell legitimately produces two different cycle-time numbers across the two variants.

Approval belongs to the `SafetyLead` alone. Approving moves `SUBMITTED` to `APPROVED`; rejecting moves `SUBMITTED` to `REJECTED`. The approver's `X-User-ID` must differ from the study's creating user id — a creator may never approve their own study, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Both decisions increment the study's `version`.

### 3.3. Safety Risk Assessment and Performance-Level Design

In parallel with the study, a `ProjectEngineer` authors the safety case as a `SafetyRiskAssessment`, supplying a `risk_score_pre_mitigation` — the risk score built from severity, probability, and exposure, an integer from 1 to 1000 inclusive — a `pl_target`, the `fencing_length_m` of hard fencing (zero or more), the `light_curtain_zones` count (zero or more), and whether `muting_required` holds for any curtain zone. The assessment opens in `DRAFT` with `assessment_revision` 1 and `approved_by_safety_lead_id` null. The project's assessment list is filterable by `status` and by `approved_by_safety_lead_id`.

Submission is legal while the project is in `STUDY` and requires the achieved level to be computable — either some positive fencing length or at least one light-curtain zone must be present. Submitting moves the assessment from `DRAFT` to `IN_REVIEW` and computes two derived values. The `safety_function_budget_pct` scores the design in points: the fencing length in meters divided by ten, capped at five points, plus one and a half points per light-curtain zone, minus a two-point penalty when `muting_required` is true; the raw point total is then expressed against the ten-point full budget — one hundred times the raw score divided by ten — and rounded half-up to one decimal place, so ten points correspond to exactly one hundred percent of budget. The `pl_achieved` level derives from the same raw score: nine points or more yields `PLe`, six points or more but fewer than nine yields `PLd`, and anything lower yields `PLc`. Both thresholds are inclusive — a raw score of exactly nine counts as `PLe`.

Approval moves `IN_REVIEW` to `APPROVED` and is a `SafetyLead` decision gated by three rules; consistent with §2.6, the two safety-level rules evaluate before the segregation check. When `risk_score_pre_mitigation` is 400 or higher, `pl_achieved` must be `PLe`. When `muting_required` is true, there must be at least one light-curtain zone and `pl_achieved` must be `PLd` or `PLe`. A breach of either rule is rejected with `ERR_SAFETY_LEVEL_INSUFFICIENT`. Finally, the approver's `X-User-ID` must differ from the assessment's creating user id, on pain of `ERR_SEGREGATION_OF_DUTIES`. A successful approval stamps `approved_by_safety_lead_id` with the approver and increments the assessment's `version`.

Rejection moves `IN_REVIEW` to `REJECTED`, and rejection is not terminal: a `ProjectEngineer` may revise the assessment, returning it to `DRAFT` with `assessment_revision` incremented by one, ready to be submitted again. The terminal `SUPERSEDED` state arrives only through the site-acceptance rework cascade of §3.6, which moves an `APPROVED` assessment to `SUPERSEDED` and creates a successor `DRAFT` shell with `assessment_revision` one higher, forcing the safety case back through approval.

### 3.4. Robot Selection and Payload Verification

With the study and safety case in hand, a `ProjectEngineer` proposes a `RobotSelection` naming the `robot_model` (for example a FANUC M-710iC/50 or an ABB IRB 6700-200/2.60), the `brand` (`FANUC` or `ABB`), the nameplate `rated_payload_kg` at the wrist (strictly greater than zero), the `end_effector_weight_kg` and the heaviest handled `part_weight_kg` (both zero or more), the worst-case `wrist_inertia_kgm2` of tool plus part (zero or more), and the manufacturer's `wrist_inertia_limit_kgm2` (strictly greater than zero). The selection opens as `PROPOSED`, and the project's selection list is filterable by `selection_status`.

Validation runs two checks in a pinned order. First the payload and inertia check: the total load is the end-effector weight plus the part weight; the `payload_margin_pct` is one hundred times the difference between rated payload and total load, divided by the rated payload, rounded half-up to two decimal places; validation requires a margin of at least 20.0 percent and a wrist inertia no greater than the manufacturer limit, and any shortfall is rejected with `ERR_PAYLOAD_CHECK_FAILED`. Only then does the brand-scope check run: the selection's `brand` must fall within the org's `brand_specialization`, where a `DUAL` specialization covers both brands; an out-of-scope brand is rejected with `ERR_BRAND_OUT_OF_SCOPE`. Passing both moves the selection from `PROPOSED` to `VALIDATED`.

Locking belongs to the `SiteSupervisor` and is legal only while the project is in `DESIGN` and the selection stands `VALIDATED`; locking moves it to `LOCKED` and freezes its payload fields from further update. A `ProjectEngineer` may instead reject a `PROPOSED` selection outright, ending it at `REJECTED`. The rework cascades of §3.6 move a `LOCKED` selection back to `VALIDATED`, un-locking it so the payload check can be re-run before the cell is rebuilt.

### 3.5. Program Development and Offline Simulation

A `ControlsProgrammer` creates each `RobotProgram` under the project with a `program_name` unique within the project — collisions are rejected with `ERR_DUPLICATE_CODE` (HTTP 409). Programs live on two independent axes. The development axis, `dev_status`, opens at `OUTLINE`; the simulation axis, `sim_status`, opens at `UNSIMULATED`. `sim_iteration_count` starts at zero, `release_revision` starts at zero, and `last_sim_cycle_time_s` remains null until the first passing simulation. The project's program list is filterable by `dev_status` and by `sim_status`.

The development axis runs `OUTLINE` → `CODED` → `PEER_REVIEWED` → `RELEASED`, with a rework loop back through `CODED`. Marking code complete moves `OUTLINE` to `CODED`, legal only while the project stands in `DESIGN` or `BUILD`, and the same action moves a `REWORK` program back to `CODED`. Peer review moves `CODED` to `PEER_REVIEWED`, and the reviewing programmer's `X-User-ID` must differ from the program author's user id — a programmer may never review their own program, and the violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. Release moves `PEER_REVIEWED` to `RELEASED` and additionally requires the simulation axis to stand at `SIM_PASSED`; every release increments `release_revision` by one, so a program released, sent to `REWORK`, and released again accumulates release revisions.

The simulation axis cycles independently. Starting an offline simulation requires the development axis to stand at `CODED`, `PEER_REVIEWED`, or `REWORK`, and moves `UNSIMULATED` to `SIM_RUNNING` — or, on a retry, `SIM_FAILED` back to `SIM_RUNNING`. Recording the run's outcome carries a `measured_sim_cycle_time_s`: when that time does not exceed the project's `contracted_cycle_time_s`, the run moves `SIM_RUNNING` to `SIM_PASSED` and stamps `last_sim_cycle_time_s`; when it exceeds the contract, the run moves `SIM_RUNNING` to `SIM_FAILED`. Either way, `sim_iteration_count` increments by one. The terminal configuration for a program is the pair `RELEASED` with `SIM_PASSED`.

When the project falls back from acceptance to design (§3.6), every program standing `RELEASED` moves to `REWORK` — a development-axis change only, with `sim_status` deliberately left unchanged — so previously released code re-enters the coding loop while its simulation history survives.

### 3.6. Acceptance Testing and Stage-Gate Advancement

Advancing the project through its lifecycle is the single most rule-dense operation in the API. The capability is shared between `ProjectEngineer` and `SiteSupervisor` with each stage pinned to exactly one actor, and every advance is version-guarded with `expected_project_version` per §2.7. Following the ladder of §2.6, an advance request is evaluated state legality first (`ERR_INVALID_STATE` when the project is not in a stage from which advancement is defined), then version freshness (`ERR_STALE_PROJECT_VERSION`), then — on the stages that release retention — sufficiency of the balance (`ERR_RETENTION_BALANCE_MISMATCH` when the computed milestone release exceeds the current `retention_balance_cents`), and only then the child-state gates enumerated below, whose failure is rejected with `ERR_GATE_PRECONDITION_UNMET`. Every successful advance increments the project's `version` by one.

The forward gates, in order:

- `DRAFT` → `STUDY`, by a `ProjectEngineer`: no study for the project may currently sit in `DRAFT` or `SUBMITTED`. Advancing merely unlocks study creation; it creates nothing itself.
- `STUDY` → `DESIGN`, by a `ProjectEngineer`: an application study in `APPROVED` status exists, and a safety risk assessment in `APPROVED` status exists.
- `DESIGN` → `BUILD`, by a `ProjectEngineer`: a robot selection in `LOCKED` status exists, and at least one robot program stands `RELEASED`.
- `BUILD` → `FAT`, by a `SiteSupervisor`: every robot program of the project stands with `dev_status` `RELEASED` and `sim_status` `SIM_PASSED`, and the `APPROVED` assessment's `pl_achieved` ranks at or above its `pl_target` on the `PLc`/`PLd`/`PLe` scale.
- `FAT` → `SHIP`, by a `SiteSupervisor`: the latest acceptance test with `phase` `FAT` holds a `verdict` of `PASS` or `CONDITIONAL_PASS`. This advance posts a `RELEASE` ledger entry for the factory-acceptance milestone and recomputes `retention_balance_cents`.
- `SHIP` → `SAT`, by a `SiteSupervisor`: a spare-parts package with `package_status` `ORDERED` or `DELIVERED` exists for the project.
- `SAT` → `TRAINING`, by a `SiteSupervisor`: the latest `SAT`-phase acceptance test holds a `verdict` of `PASS` or `CONDITIONAL_PASS`. This advance posts a `RELEASE` ledger entry for the site-acceptance milestone, recomputes `retention_balance_cents`, and initializes the project's throughput guarantee: `guarantee_status` moves from `NOT_STARTED` to `MEASURING`, `window_start_utc` is set to the current logical clock, and `window_end_utc` is set `guarantee_window_days` days later.
- `TRAINING` → `GUARANTEE`, by a `ProjectEngineer`: every `OPERATOR` training session of the project stands `COMPLETED` with a `completion_score_pct` of at least 80, every `TECHNICIAN` session stands `COMPLETED` with a `completion_score_pct` of at least 85, a maintenance plan in `ACTIVE` status exists, and the throughput guarantee stands `MEASURING`.

Acceptance tests themselves are recorded by a `SiteSupervisor`. Creating a test record for the project supplies the `phase` — `FAT` for the factory run on the integrator's floor or `SAT` for the site run at the customer's plant — together with the `measured_cycle_time_s` averaged across the run, the `measured_oee_pct`, and the `defects_observed` count (zero or more). The record opens with `verdict` `PENDING`, its `attempt` number is one higher than the count of prior attempts in the same phase, and `recorded_by_user_id` is stamped with the acting user. The project's test list is filterable by `phase`, by `verdict`, and by `recorded_by_user_id`.

Recording the verdict derives it from the stored measurements against the contract. A clean run — `measured_cycle_time_s` not exceeding `contracted_cycle_time_s`, `measured_oee_pct` at least `guaranteed_oee_pct`, and `defects_observed` exactly zero — earns `PASS`. A marginal run earns `CONDITIONAL_PASS` when the measured cycle time stays at or under one hundred and two percent of the contract, the measured OEE falls no more than two percentage points below the guarantee, defects number three or fewer, and the run did not in fact meet every `PASS` condition. Anything else, or an explicit failure call by the supervisor, sets `FAIL`. Recording also computes the test's `retention_released_cents` per the release schedule below, but deliberately does not post it — the ledger posting happens on the subsequent project advance, not at record time.

The retention release schedule is a pinned waterfall over the initial retention: thirty percent of the total, rounded half-up to a whole cent, is earmarked for the factory-acceptance milestone; forty percent, rounded half-up the same way, for the site-acceptance milestone; and the guarantee bucket receives whatever remains after those two earmarks, absorbing any rounding difference. The evaluation order is fixed — total first, then factory, then site, then the guarantee as residual. A `CONDITIONAL_PASS` halves the milestone release for that test, rounded half-up to a whole cent; the unreleased half stays in the retention balance and is carried into the guarantee bucket.

Failure triggers the rework cascade. Failing a `PENDING` test whose `phase` is `FAT` moves the project from `FAT` back to `DESIGN`; failing one whose `phase` is `SAT` moves it from `SAT` back to `DESIGN`. Either failure increments the project's `rework_count` by one, moves every `RELEASED` robot program to `REWORK` (with `sim_status` untouched), moves a `LOCKED` robot selection back to `VALIDATED` for re-check, and increments the project's `version`. A site-acceptance failure additionally moves the `APPROVED` safety assessment to `SUPERSEDED` and creates a successor `DRAFT` shell with `assessment_revision` incremented by one, forcing the safety case back through review. The next test record created for the failed phase opens as a fresh `PENDING` record carrying the next `attempt` number, so the cycle `DESIGN` → `BUILD` → `FAT` → `DESIGN` (and its `SAT` analogue) can repeat as often as reality demands.

### 3.7. Spare Parts Provisioning and Preventive Maintenance

A `ServiceManager` quotes each `SparePartsPackage` against the project with a catalog `package_code`, a `list_price_cents` of zero or more, and a `recommended_coverage_months` horizon between 1 and 60 inclusive. The package opens as `QUOTED`, and quoting computes its `forecast_consumption_months`. The forecast works from the unit count the catalog associates with the `package_code`: the reference daily consumption is that unit count divided by the coverage horizon expressed in days at thirty days per month; the shift factor is the site's `shift_windows_per_day` divided by a two-shift baseline; the effective daily burn is the reference consumption multiplied by the shift factor; and the forecast itself is the unit count divided by thirty days' worth of effective burn, rounded half-up to one decimal place. Every recorded maintenance service resets the burn clock, restarting the consumption baseline from that point. The project's package list is filterable by `package_status`.

Two variants of the same forecast exist. The quoted variant, computed while the package stands `QUOTED`, uses the site's then-current `shift_windows_per_day` snapshot. The delivered variant, computed when the `ServiceManager` marks the package `DELIVERED`, re-derives the forecast using the shift count in force at delivery time — so identical package inputs can yield different forecasts if the site's shift pattern changed in between. Marking a package `ORDERED` does not recompute anything. Separately, whenever a `ProjectEngineer` updates a site's `shift_windows_per_day` (§3.1), the forecast is recomputed on every spare-parts package of every project under that site.

Preventive maintenance is planned per project by the same `ServiceManager`, who creates a `MaintenancePlan` with an `interval_operating_hours` between 500 and 10000 inclusive and a `first_due_at_hours` meter reading of zero or more. The plan opens in `DRAFT` with `current_operating_hours` at zero. Activation — legal while the project stands in `SAT`, `TRAINING`, or `GUARANTEE` — requires the first-due reading to be at or beyond the current meter reading, and the interval to lie inside its permitted range; a violation is rejected with `ERR_MAINTENANCE_WINDOW_INVALID`. Activation moves the plan to `ACTIVE` and computes `hours_until_due`: the hours remaining until the next due service, obtained by adding whole maintenance intervals to the first-due reading — zero intervals if the first-due reading alone already reaches or passes the current meter, otherwise however many it takes — and subtracting the current meter reading, so the result is the smallest non-negative remainder of that form. The plan list is filterable by `plan_status`.

An `ACTIVE` plan may be moved to `SUSPENDED` and later re-activated, which recomputes `hours_until_due`. Each new meter reading the `ServiceManager` reports — the payload carries `current_operating_hours` — also recomputes `hours_until_due` against the updated meter. When the project ultimately closes or is terminated, the cascade moves any `ACTIVE` plan to `CLOSED`.

### 3.8. Training Delivery and Competency Gates

Training is scheduled per project by a `Trainer`, who supplies the `audience` — `OPERATOR` or `TECHNICIAN` — the `scheduled_start_utc` and `scheduled_end_utc` window, the `trainer_user_id` of the assigned trainer, and an `attendee_count` between 1 and 12 inclusive. Two scheduling rules guard creation, both rejected with `ERR_TRAINER_SCHEDULE_CONFLICT`: the end of the window must come strictly after its start, and the same trainer may not hold two sessions whose windows overlap while either stands in `SCHEDULED` or `IN_PROGRESS`. Overlap is judged on half-open intervals — the start instant counts, the end instant does not — so back-to-back sessions where one begins exactly as the other ends do not conflict. The session opens in `SCHEDULED` with `practical_score_pct`, `written_score_pct`, and `completion_score_pct` not yet set; the project's session list is filterable by `audience`, by `session_status`, and by `trainer_user_id`.

Starting a session is legal only while the project stands in `TRAINING` and only inside the scheduled window — the logical clock (§2.10) must read at or after `scheduled_start_utc` and at or before `scheduled_end_utc`, both ends inclusive; an attempt outside the window is rejected with `ERR_OUTSIDE_SESSION_WINDOW`. A session started in time moves from `SCHEDULED` to `IN_PROGRESS`. One that is never started does not linger: when the logical clock moves past `scheduled_end_utc` with the session still `SCHEDULED`, the system marks it `NO_SHOW`. A `Trainer` may also cancel a `SCHEDULED` session outright, moving it to `CANCELLED`.

Completion is scored by the session's own trainer: completing a session requires both `practical_score_pct` and `written_score_pct` (each between 0 and 100) to be provided, and the acting `X-User-ID` must equal the session's `trainer_user_id`. The `completion_score_pct` is a weighted blend, rounded half-up to one decimal place: for an `OPERATOR` audience, sixty percent of the practical score plus forty percent of the written score; for a `TECHNICIAN` audience, half of each. Passing is audience-dependent — 80 or better for operators, 85 or better for technicians — and the `TRAINING` → `GUARANTEE` gate of §3.6 refuses to advance until every session of each audience stands `COMPLETED` at or above its threshold.

### 3.9. Guarantee Settlement, Termination, and Closure

The throughput guarantee is born the moment the project advances from `SAT` to `TRAINING`: the system creates it with `guarantee_window_days` copied from the project, `guarantee_status` moved from `NOT_STARTED` straight to `MEASURING`, `window_start_utc` stamped from the logical clock, and `window_end_utc` computed as that many days after the window opens. Until then the guarantee's `observed_uptime_pct`, `observed_cycle_time_s`, and `shortfall_pct` remain unset. The guarantee is fetchable directly by `id`, and the project exposes it through a collection-style fetch that returns an array of zero or one element, per the one-to-one reverse-reachability convention.

Once the window has fully elapsed — the logical clock reads at or after `window_end_utc` — a `ServiceManager` closes the guarantee by supplying an `outcome` together with the customer-reported `observed_cycle_time_s` and `observed_uptime_pct` (the latter between 0 and 100). Closing before the window ends is rejected with `ERR_GUARANTEE_WINDOW_VIOLATION`. An `outcome` of `MET` requires the observed cycle time to be no greater than `contracted_cycle_time_s` and the observed uptime to be at least `guaranteed_oee_pct`; it posts the final `RELEASE` ledger entry for the entire remaining retention and recomputes `retention_balance_cents` to zero. An `outcome` of `MISSED` applies when the observed cycle time exceeds the contract or the observed uptime falls below the guarantee. The shortfall is then computed: the cycle shortfall is the excess of observed over contracted cycle time expressed as a percentage of the contracted time, floored at zero; the uptime shortfall is the amount by which observed uptime falls below the guaranteed OEE, in percentage points, likewise floored at zero; `shortfall_pct` is the larger of the two, rounded half-up to two decimal places. The penalty posted is a `PENALTY` ledger entry for the smaller of the outstanding `retention_balance_cents` and the `contract_value_cents` multiplied by the shortfall percentage divided by one hundred, rounded half-up to a whole cent — sized to zero the balance, and capped so the conservation rule of §2.8 can never be breached by a guarantee close.

Before the window ends, a `FinanceAdmin` may instead waive the guarantee, but only while the logical clock reads strictly before `window_end_utc` — a waive at or after window end is rejected with `ERR_GUARANTEE_WINDOW_VIOLATION`, just as a close before it is. Waiving requires a `waiver_reference` documenting the customer's written waiver request, moves the guarantee from `MEASURING` to `WAIVED`, and settles the retention in two postings: a `RELEASE` entry for half of the remaining balance, rounded half-up to a whole cent, and an `ADJUST` entry for the remainder, so `retention_balance_cents` reaches exactly zero.

Project closure follows settlement. When the guarantee closes `MET`, or stands `WAIVED`, the project moves from `GUARANTEE` to `CLOSED` provided `retention_balance_cents` is zero; when the guarantee closes `MISSED`, the project moves to `CLOSED` once the posted penalty has brought the balance to zero. `CLOSED` and `TERMINATED` are the project's terminal states.

Hand-posted corrections round out the ledger story. A `FinanceAdmin` may post a manual entry against a project — a version-guarded write per §2.7 carrying `expected_project_version` — supplying the `entry_type`, the signed `amount_cents`, and a `milestone_ref`, which is the literal string `MANUAL` when no acceptance test or guarantee authorized the movement. Posting recomputes the project's `retention_balance_cents` and increments the project's `version` by one, and any posting that would push the balance below zero is rejected with `ERR_RETENTION_OVERRELEASE`. The project's ledger is listable and filterable by `entry_type`.

Termination is the `FinanceAdmin`'s final lever, available from every stage except `CLOSED`, `TERMINATED`, and `GUARANTEE`, and it demands a clean ledger: either `retention_balance_cents` already stands at zero, or a compensating `PENALTY` entry is posted atomically with the termination to zero it. Termination cascades through every child. Application studies in `DRAFT` or `SUBMITTED` move to `REJECTED`. Robot programs freeze on the development axis — any program not `RELEASED` simply stays where it is — while any simulation in flight moves from `SIM_RUNNING` to `SIM_FAILED`. Training sessions in `SCHEDULED` or `IN_PROGRESS` move to `CANCELLED`. Spare-parts packages in `QUOTED` or `ORDERED` move to `SUPERSEDED`. An `ACTIVE` maintenance plan moves to `CLOSED`. And the project's `version` increments by one.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an organization, a user, a site, a project, or any child artifact added to a project's collection — return `201 Created`. Operations that modify an existing resource, including every state transition, verdict recording, and clock operation, return `200 OK`. Request payloads, response bodies, and side effects are specified by the narratives of §2 and §3; this table is the HTTP index only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/robotics/integrator-orgs` | Create an integrator org | FinanceAdmin |
| GET | `/robotics/integrator-orgs` | List integrator orgs (paginated) | FinanceAdmin |
| GET | `/robotics/integrator-orgs/{id}` | Fetch one integrator org | FinanceAdmin, ProjectEngineer, SafetyLead, ControlsProgrammer, SiteSupervisor, Trainer, ServiceManager |
| POST | `/robotics/integrator-orgs/{id}/users` | Create an integrator user under an org | FinanceAdmin |
| GET | `/robotics/integrator-orgs/{id}/users` | List users of an org | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor, ServiceManager |
| GET | `/robotics/users/{id}` | Fetch one user | FinanceAdmin, ProjectEngineer, SafetyLead, ControlsProgrammer, SiteSupervisor, Trainer, ServiceManager |
| GET | `/robotics/users/{id}/approved-safety-assessments` | List safety risk assessments approved by this user | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor, ServiceManager |
| GET | `/robotics/users/{id}/recorded-acceptance-tests` | List acceptance tests recorded by this user | FinanceAdmin, ProjectEngineer, SiteSupervisor, ServiceManager |
| GET | `/robotics/users/{id}/training-sessions` | List training sessions assigned to this trainer | FinanceAdmin, ProjectEngineer, SiteSupervisor, Trainer |
| POST | `/robotics/integrator-orgs/{id}/customer-sites` | Create a customer site under an org | ProjectEngineer |
| GET | `/robotics/integrator-orgs/{id}/customer-sites` | List sites of an org | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor, ServiceManager |
| GET | `/robotics/customer-sites/{id}` | Fetch one customer site | FinanceAdmin, ProjectEngineer, SafetyLead, ControlsProgrammer, SiteSupervisor, Trainer, ServiceManager |
| PATCH | `/robotics/customer-sites/{id}` | Update site fields; a shift-window change re-triggers spare-parts forecasts site-wide | ProjectEngineer |
| POST | `/robotics/customer-sites/{id}/cell-projects` | Create a cell project under a site | ProjectEngineer |
| GET | `/robotics/customer-sites/{id}/cell-projects` | List projects of a site | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor, ServiceManager |
| GET | `/robotics/cell-projects/{id}` | Fetch one project | FinanceAdmin, ProjectEngineer, SafetyLead, ControlsProgrammer, SiteSupervisor, Trainer, ServiceManager |
| POST | `/robotics/cell-projects/{id}/advance` | Advance project to next stage (OCC-guarded) | ProjectEngineer, SiteSupervisor |
| POST | `/robotics/cell-projects/{id}/hold` | Put project ON_HOLD | ProjectEngineer |
| POST | `/robotics/cell-projects/{id}/resume` | Resume from ON_HOLD to prior status | ProjectEngineer |
| POST | `/robotics/cell-projects/{id}/terminate` | Terminate a project, cascading children to terminal states | FinanceAdmin |
| POST | `/robotics/cell-projects/{id}/application-studies` | Create (or supersede) an application study (OCC-guarded) | ProjectEngineer |
| GET | `/robotics/cell-projects/{id}/application-studies` | List studies of a project | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor |
| GET | `/robotics/application-studies/{id}` | Fetch one application study | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor |
| GET | `/robotics/application-studies/{id}/superseded-by` | List studies that supersede this one | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor |
| POST | `/robotics/application-studies/{id}/submit` | Submit a DRAFT study | ProjectEngineer |
| POST | `/robotics/application-studies/{id}/approve` | Approve a SUBMITTED study (not the creator) | SafetyLead |
| POST | `/robotics/application-studies/{id}/reject` | Reject a SUBMITTED study | SafetyLead |
| POST | `/robotics/cell-projects/{id}/safety-risk-assessments` | Create a safety risk assessment | ProjectEngineer |
| GET | `/robotics/cell-projects/{id}/safety-risk-assessments` | List assessments of a project | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor |
| GET | `/robotics/safety-risk-assessments/{id}` | Fetch one safety risk assessment | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor |
| POST | `/robotics/safety-risk-assessments/{id}/submit` | Submit assessment (computes budget and achieved level) | ProjectEngineer |
| POST | `/robotics/safety-risk-assessments/{id}/approve` | Approve an IN_REVIEW assessment (not the creator) | SafetyLead |
| POST | `/robotics/safety-risk-assessments/{id}/reject` | Reject an IN_REVIEW assessment | SafetyLead |
| POST | `/robotics/safety-risk-assessments/{id}/revise` | Revise a REJECTED assessment back to DRAFT with bumped revision | ProjectEngineer |
| POST | `/robotics/cell-projects/{id}/robot-selections` | Propose a robot/end-effector selection | ProjectEngineer |
| GET | `/robotics/cell-projects/{id}/robot-selections` | List robot selections of a project | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor |
| GET | `/robotics/robot-selections/{id}` | Fetch one robot selection | FinanceAdmin, ProjectEngineer, SafetyLead, SiteSupervisor |
| POST | `/robotics/robot-selections/{id}/validate` | Run payload/inertia/brand checks | ProjectEngineer |
| POST | `/robotics/robot-selections/{id}/lock` | Lock a VALIDATED selection | SiteSupervisor |
| POST | `/robotics/robot-selections/{id}/reject` | Reject a PROPOSED selection | ProjectEngineer |
| POST | `/robotics/cell-projects/{id}/robot-programs` | Create a robot program | ControlsProgrammer |
| GET | `/robotics/cell-projects/{id}/robot-programs` | List programs of a project | FinanceAdmin, ProjectEngineer, ControlsProgrammer, SiteSupervisor |
| GET | `/robotics/robot-programs/{id}` | Fetch one robot program | FinanceAdmin, ProjectEngineer, ControlsProgrammer, SiteSupervisor |
| POST | `/robotics/robot-programs/{id}/code-complete` | Mark coding complete (OUTLINE/REWORK to CODED) | ControlsProgrammer |
| POST | `/robotics/robot-programs/{id}/peer-review` | Peer review a CODED program (different programmer than author) | ControlsProgrammer |
| POST | `/robotics/robot-programs/{id}/simulate` | Start an offline simulation run | ControlsProgrammer |
| POST | `/robotics/robot-programs/{id}/simulate/record` | Record the simulation outcome | ControlsProgrammer |
| POST | `/robotics/robot-programs/{id}/release` | Release a PEER_REVIEWED program whose sim passed | ControlsProgrammer |
| POST | `/robotics/cell-projects/{id}/acceptance-tests` | Create an acceptance test record for a phase (PENDING) | SiteSupervisor |
| GET | `/robotics/cell-projects/{id}/acceptance-tests` | List acceptance tests of a project | FinanceAdmin, ProjectEngineer, SiteSupervisor, ServiceManager |
| GET | `/robotics/acceptance-tests/{id}` | Fetch one acceptance test | FinanceAdmin, ProjectEngineer, SiteSupervisor, ServiceManager |
| POST | `/robotics/acceptance-tests/{id}/record` | Record verdict PASS / CONDITIONAL_PASS from measurements | SiteSupervisor |
| POST | `/robotics/acceptance-tests/{id}/fail` | Explicitly fail a PENDING test; triggers rework cascade | SiteSupervisor |
| POST | `/robotics/cell-projects/{id}/spare-parts-packages` | Quote a spare-parts package | ServiceManager |
| GET | `/robotics/cell-projects/{id}/spare-parts-packages` | List spare-parts packages of a project | FinanceAdmin, ProjectEngineer, SiteSupervisor, ServiceManager |
| GET | `/robotics/spare-parts-packages/{id}` | Fetch one spare-parts package | FinanceAdmin, ProjectEngineer, SiteSupervisor, ServiceManager |
| POST | `/robotics/spare-parts-packages/{id}/order` | Mark package ORDERED | ServiceManager |
| POST | `/robotics/spare-parts-packages/{id}/deliver` | Mark package DELIVERED and re-derive forecast | ServiceManager |
| POST | `/robotics/cell-projects/{id}/maintenance-plans` | Create a preventive maintenance plan | ServiceManager |
| GET | `/robotics/cell-projects/{id}/maintenance-plans` | List maintenance plans of a project | FinanceAdmin, ProjectEngineer, SiteSupervisor, ServiceManager |
| GET | `/robotics/maintenance-plans/{id}` | Fetch one maintenance plan | FinanceAdmin, ProjectEngineer, SiteSupervisor, ServiceManager |
| POST | `/robotics/maintenance-plans/{id}/activate` | Activate (or re-activate from SUSPENDED) a plan | ServiceManager |
| POST | `/robotics/maintenance-plans/{id}/suspend` | Suspend an ACTIVE plan | ServiceManager |
| POST | `/robotics/maintenance-plans/{id}/meter-reading` | Report a new operating-hours meter reading | ServiceManager |
| POST | `/robotics/cell-projects/{id}/training-sessions` | Schedule a training session | Trainer |
| GET | `/robotics/cell-projects/{id}/training-sessions` | List training sessions of a project | FinanceAdmin, ProjectEngineer, SiteSupervisor, Trainer |
| GET | `/robotics/training-sessions/{id}` | Fetch one training session | FinanceAdmin, ProjectEngineer, SiteSupervisor, Trainer |
| POST | `/robotics/training-sessions/{id}/start` | Start a scheduled session within its window | Trainer |
| POST | `/robotics/training-sessions/{id}/complete` | Complete a session with assessment scores | Trainer |
| POST | `/robotics/training-sessions/{id}/cancel` | Cancel a scheduled session | Trainer |
| GET | `/robotics/throughput-guarantees/{id}` | Fetch one throughput guarantee by id | FinanceAdmin, ProjectEngineer, SiteSupervisor, ServiceManager |
| GET | `/robotics/cell-projects/{id}/throughput-guarantee` | Fetch the throughput guarantee of a project (array of 0 or 1) | FinanceAdmin, ProjectEngineer, SiteSupervisor, ServiceManager |
| POST | `/robotics/throughput-guarantees/{id}/close` | Close the guarantee window with MET or MISSED outcome | ServiceManager |
| POST | `/robotics/throughput-guarantees/{id}/waive` | Waive the guarantee before window end with a waiver reference | FinanceAdmin |
| GET | `/robotics/cell-projects/{id}/retention-ledger-entries` | List retention ledger entries of a project | FinanceAdmin, ServiceManager |
| POST | `/robotics/cell-projects/{id}/retention-ledger-entries` | Post a manual ADJUST entry (OCC-guarded) | FinanceAdmin |
| POST | `/robotics/_clock/set_current_utc` | Set the logical clock (test-driving endpoint) | FinanceAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_SAFETY_LEVEL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_PAYLOAD_CHECK_FAILED` | 422 Unprocessable Entity |
| `ERR_BRAND_OUT_OF_SCOPE` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_SESSION_WINDOW` | 422 Unprocessable Entity |
| `ERR_GUARANTEE_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_TRAINER_SCHEDULE_CONFLICT` | 422 Unprocessable Entity |
| `ERR_SUPERSEDE_TARGET_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_RETENTION_OVERRELEASE` | 422 Unprocessable Entity |
| `ERR_RETENTION_BALANCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MAINTENANCE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_GATE_PRECONDITION_UNMET` | 422 Unprocessable Entity |
