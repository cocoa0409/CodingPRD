# Fishery Observer Program API — Product Requirements Document

## 1. Introduction

Fishery observer programs sit at the intersection of conservation science and commercial fishing. Regulators place independent, certified observers aboard fishing vessels to record catch composition, bycatch, and discards first-hand — data that quota management, stock assessment, and enforcement all depend on. Running such a program is a logistics problem as much as a scientific one: the agency must translate a fleet-wide coverage target into a defensible selection of vessels, schedule finite observer capacity against vessel calendars, enforce a safety gate before anyone steps aboard, and protect observers from harassment or interference at sea. On top of that, the program is industry-funded through cost-recovery fees, and some vessels may substitute electronic monitoring (EM) — cameras plus shoreside video review — for a human observer.

This document specifies the API for the Fishery Observer & Catch Monitoring Program, exposed under the `/observer-program` prefix. It governs the full arc of a coverage season: drafting and publishing a coverage plan, scoring and notifying selected vessels, scheduling and safety-checking deployments, collecting and debriefing haul samples, adjudicating harassment reports, operating the EM alternative from enrollment through video review, and finally generating, collecting, adjusting, and — when necessary — escalating cost-recovery invoices. It is written for the engineers who will build the service: §2 pins the system-wide contracts, §3 narrates the business workflows in which every rule lives, §4 lists the HTTP surface, and §5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, invariants, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes six roles, spelled exactly: `ProgramAdmin`, `ProgramCoordinator`, `Observer`, `Debriefer`, `VesselOperator`, and `EMReviewer`. A request missing either header, carrying a role outside this set, or whose `X-User-ID` fails to resolve to an existing record for an entity-backed role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Beyond authentication, each endpoint admits only specific roles (§4); an authenticated caller attempting an operation outside their role, or on a resource they do not own, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity works in two modes. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `reviewed_by_user_id` on an EM enrollment adjudication — but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `ProgramCoordinator`: `X-User-ID` is opaque, and the server may record it (notably as `issued_by_user_id` on an issued invoice, where it later anchors the segregation-of-duties check of §3.9) without ever matching it against an entity identifier.

The four remaining roles are entity-backed. When `X-User-Role` is `Observer`, `X-User-ID` is the `id` of the acting `Observer`; ownership checks on any resource that references an `Observer` — such as a deployment's `observer_id` — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `Debriefer`, `X-User-ID` is the `id` of the acting `Debriefer`, compared against a deployment's `assigned_debriefer_id`. When `X-User-Role` is `VesselOperator`, `X-User-ID` is the `id` of the acting `VesselOperator`; ownership of vessels is decided by comparing a vessel's `operator_id` to `X-User-ID`, and that ownership in turn gates the operator's notices, deployments' invoices, EM enrollments, EM trips, and harassment-report appeals. When `X-User-Role` is `EMReviewer`, `X-User-ID` is the `id` of the acting `EMReviewer`, compared against a trip's `assigned_reviewer_id`.

An entity-backed actor whose registry record is currently in `SUSPENDED` status is refused with `ERR_FORBIDDEN` even on endpoints their role would normally reach.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.7 rather than wall-clock time.
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

List endpoints are paginated through two query parameters. `limit` bounds the page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of records and defaults to 0. Unless stated otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, read from the logical clock of §2.7 — a resource created before the clock is first advanced therefore carries `2026-08-01T00:00:00.000Z`, never a wall-clock reading.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource and likewise read from the logical clock of §2.7 rather than wall-clock time.
- `version` (integer): a system-managed counter that increments by one with every modification to the resource, whether the write came from a client call or from a system cascade.

One deliberate exception: a safety-inspection record is immutable once filed, so it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. Nested Resource Retrieval and Reference Validation

Requests that address a resource nested beneath another — for example, a selection run beneath a coverage plan, or a safety inspection beneath a deployment — are validated strictly left to right. Each path identifier must resolve to an existing resource before the next is examined, and the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. Path identifiers are validated before any foreign-key references carried in the request body, and an unresolvable body reference is likewise `ERR_NOT_FOUND`.

### 2.6. Precision, Rounding, and Monetary Representation

Numeric conventions are fixed so that every implementation computes bit-identical results. Scores, ratios, and percentages — `selection_score`, `sampling_ratio`, `reviewed_pct`, and `coverage_attainment_pct` — are computed to exactly 4 decimal places using round-half-up. Catch weights (`sampled_weight_kg`, `total_haul_weight_kg`, `sampled_catch_kg`, `estimated_total_catch_kg`) are carried at 2 decimal places, with computed catch values rounded half-up to 2 decimals; declared footage `video_hours` is likewise a positive two-decimal figure. All money is integer cents — rates, line subtotals, invoice totals, payments, adjustments — with no fractional cents anywhere. Day counts are whole calendar days; where a window is described as inclusive, both endpoint dates count. Quota-style divisions round up to a whole unit (ceiling), while caps and revenue-based floors round down (floor). Invoice line totals are rounded half-up to whole cents per line before any summation takes place; §3.9 pins that ordering and explains why the alternative is non-conformant.

### 2.7. The Logical Clock and the Operations Checkpoint

The program runs on a logical clock rather than wall-clock time. At startup the clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time. An administrator moves the clock with the test-driving endpoint `POST /observer-program/_clock/set_current_utc`, passing the target instant as `to_iso8601`; the response reports the clock's new reading as `current_utc`. Every temporal rule in this document — notice response deadlines, invoice due dates, issue dates, early-termination dates — reads this clock.

The operations checkpoint, `POST /observer-program/ops/run`, available to `ProgramAdmin` and `ProgramCoordinator`, performs two sweeps against the current clock. First, every selection notice still `ISSUED` whose `response_deadline` lies in the past is moved to `EXPIRED`. Second, every invoice in `ISSUED` or `PARTIALLY_PAID` whose `due_date` lies in the past with `amount_outstanding_cents` still positive is moved to `OVERDUE`, and each such transition fires the delinquency cascade of §2.10. The response tallies the sweep's work in five counters: `expired_notice_count`, `overdue_invoice_count`, `delinquent_operator_count`, `suspended_vessel_count`, and `cancelled_deployment_count`.

### 2.8. Optimistic Concurrency Control

Three write operations participate in optimistic concurrency control (OCC), each against a named parent resource, and each requires its version field as a non-optional input:

- Creating a deployment requires `expected_selection_notice_version`, carrying the client's last-observed `version` of the parent selection notice. If the value does not match the notice's current `version` — because another writer has since created, rescheduled, or cancelled a deployment against that notice and moved its sea-day allocation — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from scheduling against an allocation it has not observed.
- Launching a selection run requires `expected_coverage_plan_version`, matched against the coverage plan's current `version`; a mismatch — the plan was just published, or an earlier run just completed and changed the requirement or the eligibility base — is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Posting an invoice adjustment requires `expected_invoice_version`, matched against the invoice's current `version`; a mismatch — a payment or an earlier adjustment has moved the outstanding balance the client based its arithmetic on — is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not accept a version field.

### 2.9. The Sea-Day Ledger on Every Notice

Each selection notice is a small ledger of sea days, and one invariant holds after every mutation: `allocated_sea_days` always equals the sum of `remaining_sea_days`, `reserved_sea_days`, and `consumed_sea_days`. Every notice is minted with `allocated_sea_days` of 30 — the standard allocation unit — all of it initially sitting in `remaining_sea_days`. From there, four events move days between the three buckets. Creating a deployment moves its `planned_sea_days` from `remaining_sea_days` into `reserved_sea_days`, and the planned days may not exceed the remainder (else `ERR_SEA_DAY_ALLOCATION_EXCEEDED`). Rescheduling moves the day-count delta — new planned days minus old planned days — between the two buckets in the matching direction, and the remainder may never go negative (`ERR_SEA_DAY_ALLOCATION_EXCEEDED`). Cancelling a deployment releases its reservation wholesale: `reserved_sea_days` drops by `planned_sea_days` and `remaining_sea_days` rises by the same. Recording a return — normal or early-terminated — converts the reservation into consumption: `reserved_sea_days` falls by `planned_sea_days`, `consumed_sea_days` rises by `actual_sea_days`, and `remaining_sea_days` is credited with the difference between planned and actual days.

### 2.10. Cascading Reconciliation

Several operations reconcile far beyond the resource they touch, and the system performs those reconciliations automatically rather than leaving them to clients.

- **The delinquency cascade.** When the operations checkpoint moves an invoice to `OVERDUE`, the cascade walks outward: the invoice's operator has `payment_standing` set to `DELINQUENT`; every vessel of that operator in `ACTIVE` status is suspended (`ACTIVE` → `SUSPENDED`); and every deployment of such a vessel still in `SCHEDULED`, `SAFETY_HOLD`, or `READY_TO_DEPLOY` is cancelled, releasing its reserved sea days back to its notice per §2.9. The reverse direction is deliberately asymmetric: when a payment or waiver leaves an operator with no `OVERDUE` invoices, `payment_standing` returns to `GOOD`, but the suspended vessels stay `SUSPENDED` until an administrator reactivates each one manually.
- **The EM activation cascade.** Activating a vessel's electronic-monitoring enrollment flips the vessel's `monitoring_mode` to `ELECTRONIC_MONITORING`, voids every open selection notice of that vessel (`ISSUED` or `ACCEPTED` → `VOIDED`), and cancels each deployment of a voided notice still in `SCHEDULED`, `SAFETY_HOLD`, or `READY_TO_DEPLOY`, releasing reserved days per §2.9.
- **The harassment substantiation cascade.** Substantiating a report can terminate an at-sea deployment and penalize the vessel; §3.7 details both hops.
- **Notice auto-fulfillment.** When a deployment closes and leaves its notice with `remaining_sea_days` of zero and no other open deployment referencing it, the notice moves from `ACCEPTED` to `FULFILLED` on its own.

Every entity a cascade touches is mutated in its own right — its `updated_at` refreshes and its `version` increments per §2.4 — so downstream OCC checks observe the new state.

### 2.11. Validation Ordering

Incoming writes are checked in a fixed priority order so that a request with several problems always surfaces the same error. Lower numbers win:

1. **Authentication** — headers present, role recognized, entity-backed identity resolvable (`ERR_UNAUTHENTICATED`).
2. **Authorization** — role permission, ownership, and segregation of duties (`ERR_FORBIDDEN`, `ERR_DEBRIEFER_CONFLICT_OF_INTEREST`, `ERR_INVOICE_ADJUSTMENT_FORBIDDEN`).
3. **Existence** — path identifiers first, then body references, left to right (`ERR_NOT_FOUND`).
4. **Request schema** — required fields, types, enum values, and value ranges (`ERR_INVALID_REQUEST`; the fishery coverage target has its own `ERR_COVERAGE_TARGET_OUT_OF_RANGE`).
5. **Optimistic concurrency** — the `expected_..._version` fields of §2.8 (`ERR_STALE_VERSION`).
6. **State-machine legality** — the target resource is in a from-state that permits the transition (`ERR_INVALID_STATE` and the domain state errors `ERR_NOTICE_NOT_ACCEPTED`, `ERR_PLAN_NOT_PUBLISHED`, `ERR_PLAN_HAS_OPEN_DEPLOYMENTS`, `ERR_INVOICE_NOT_ISSUED`, `ERR_SAFETY_CHECK_REQUIRED`, `ERR_DEBRIEFER_NOT_ASSIGNED`, `ERR_REVIEWER_NOT_ASSIGNED`, `ERR_EM_REVIEW_MIN_NOT_MET`, `ERR_SAMPLES_NOT_RESOLVED`).
7. **Safety protocol** — checklist completeness and supersession (`ERR_SAFETY_CHECKLIST_INCOMPLETE`, `ERR_SAFETY_SUPERSESSION_REQUIRED`).
8. **Temporal and window rules** — date ranges, deployment length, observer overlap, vessel turnaround, EM trip overlap, notice deadlines (`ERR_DATE_RANGE_INVALID`, `ERR_DEPLOYMENT_TOO_LONG`, `ERR_OBSERVER_OVERLAP`, `ERR_VESSEL_TURNAROUND_VIOLATION`, `ERR_EM_TRIP_OVERLAP`, `ERR_NOTICE_EXPIRED`).
9. **Cross-entity referential state** — fishery, vessel, observer, operator, and enrollment statuses plus registry uniqueness (`ERR_FISHERY_NOT_ACTIVE`, `ERR_VESSEL_NOT_ACTIVE`, `ERR_VESSEL_NOT_HUMAN_MODE`, `ERR_VESSEL_NOT_EM_MODE`, `ERR_OBSERVER_NOT_AVAILABLE`, `ERR_OPERATOR_DELINQUENT`, `ERR_EM_ENROLLMENT_NOT_ACTIVE`, `ERR_EM_ENROLLMENT_OPEN_EXISTS`, `ERR_UNIQUE_CONSTRAINT`).
10. **Caps and sampling constraints** — observer workload ceilings, the sampling-ratio band, haul-number uniqueness, the verified-coverage gate (`ERR_OBSERVER_CONSECUTIVE_CAP_EXCEEDED`, `ERR_OBSERVER_COMMITMENT_CAP_EXCEEDED`, `ERR_SAMPLE_RATIO_OUT_OF_RANGE`, `ERR_DUPLICATE_HAUL_NUMBER`, `ERR_SAMPLE_COVERAGE_INSUFFICIENT`).
11. **Fiscal and allocation rules** — sea-day allocation, payment bounds, adjustment floors (`ERR_SEA_DAY_ALLOCATION_EXCEEDED`, `ERR_PAYMENT_NOT_POSITIVE`, `ERR_PAYMENT_EXCEEDS_OUTSTANDING`, `ERR_ADJUSTMENT_WOULD_UNDERFLOW`).

Because the ordering is pinned, a request that fails both authentication and a business rule always surfaces the authentication error, and a stale version (step 5) is reported before an illegal state (step 6) or any later rule.

## 3. Business Logic & Workflows

### 3.1. Registries: Fisheries, Operators, Vessels, and Personnel

Before any coverage planning begins, the program's registries must be populated. A `ProgramAdmin` creates each **fishery** with a unique `code` (such as BSAI-PLK), a display `name`, a management `region`, a `coverage_target_pct` between 0.02 and 1.00 inclusive — a target outside that band is rejected with `ERR_COVERAGE_TARGET_OUT_OF_RANGE` — and a `priority_gear` of `TRAWL`, `LONGLINE`, `POT`, or `GILLNET` that earns a scoring multiplier during vessel selection. A fishery is born `ACTIVE`; the administrator may later suspend and reactivate it (`ACTIVE` ↔ `SUSPENDED`) and may amend `name`, `coverage_target_pct`, or `priority_gear` through the same update, each write incrementing the fishery's `version`. Because the coverage calculation of §3.2 reads the fishery's target at the moment it runs, amending `coverage_target_pct` between publish and close changes the final arithmetic.

Vessel operators join the registry through an administrator as well, each carrying a `legal_name`, a unique `license_number`, and a `contact_person_ref` identifying the primary contact natural person. An operator starts with `payment_standing` of `GOOD` and `status` of `ACTIVE`. The standing is thereafter system-managed through the delinquency cascade of §2.10 — no one edits an operator into or out of `DELINQUENT` by hand.

An operator registers each of its own vessels, supplying `operator_id` (which must equal the caller's own id, else `ERR_FORBIDDEN`), the `fishery_id` of the permitted fishery, a `vessel_name`, a unique `permit_number`, the `home_port`, the overall `length_ft` (a positive number; under 40 feet qualifies the vessel for the `SMALL_VESSEL` fee variant of §3.9), and a `gear_type` from the same four-value gear enumeration. Two optional seeds bridge pre-program history: `prior_last_observed_end_date` is copied into the vessel's `last_observed_end_date` — the actual return date of the vessel's most recent closed human-observer deployment, null when the vessel has never been observed — and `prior_harassment_points`, defaulting to zero, is copied into `selection_penalty_points`. A new vessel starts in `REGISTERED` status with `monitoring_mode` of `HUMAN_OBSERVER`, a `substantiated_harassment_count` of zero, and `sea_days_observed_ytd` of zero. An administrator activates the vessel (`REGISTERED` → `ACTIVE`) only while its operator is `ACTIVE`, may suspend it later (`ACTIVE` → `SUSPENDED`, an outcome that also arrives unbidden from the delinquency cascade), and may reactivate a suspended vessel (`SUSPENDED` → `ACTIVE`) again only while the operator is `ACTIVE`; the same update path can amend `length_ft`, `gear_type`, `home_port`, or `declared_annual_revenue_cents`, and every write increments the vessel's `version`.

Observers, debriefers, and EM reviewers are personnel registries keyed by natural person. Each observer is created with a unique `person_ref`, a `full_name`, a `home_port`, and a `certification_level` of `TRAINEE`, `CERTIFIED`, or `LEAD`. The certification derives the observer's `max_consecutive_sea_days` ceiling — 20 days for a trainee, 30 for certified, 45 for a lead — and a later change to `certification_level` recomputes that ceiling. Observers start `ACTIVE` with `sea_days_used_ytd` at zero; an administrator may suspend and reinstate them (`ACTIVE` ↔ `SUSPENDED`) or decertify them outright. Decertification — from either `ACTIVE` or `SUSPENDED` into the terminal `DECERTIFIED` — is refused while the observer still holds a deployment in `SCHEDULED`, `SAFETY_HOLD`, `READY_TO_DEPLOY`, or `AT_SEA`. Debriefers and EM reviewers are slimmer registries — a unique `person_ref` plus a `full_name` — each born `ACTIVE` and toggleable between `ACTIVE` and `SUSPENDED`.

Registry identifiers must stay unique across their type: a duplicate fishery `code`, operator `license_number`, vessel `permit_number`, or `person_ref` within any one personnel registry is rejected with `ERR_UNIQUE_CONSTRAINT`.

### 3.2. Coverage Planning: From Draft to Final Accounting

A coverage season opens when a `ProgramCoordinator` creates a **coverage plan** for a fishery. The request names the `fishery_id`, the plan window `period_start` through `period_end` — both dates inclusive, and the end must fall after the start or the create fails with `ERR_DATE_RANGE_INVALID` — and two projections: `projected_fleet_effort_days`, the fleet's expected total fishing days in the window (a positive integer), and `projected_em_effort_days`, the days expected to be covered electronically (zero or more). The plan is born in `DRAFT`.

Publishing the plan fixes the coverage requirement for the selection season. A coordinator may publish only while the fishery is `ACTIVE` — publishing against a suspended fishery yields `ERR_FISHERY_NOT_ACTIVE` — and only from `DRAFT`. Publication runs the coverage calculation in its provisional variant, in four pinned steps that must be applied in this order: first, the electronic-monitoring credit is capped at the whole-day floor of forty percent of the effort-day figure; second, the credited EM days are the lesser of the plan's EM-day figure and that cap; third, the covered base is the effort-day figure minus the credited EM days, never below zero; fourth, the requirement is the covered base multiplied by the fishery's current `coverage_target_pct`, rounded up to a whole day. For the provisional run the effort figures are `projected_fleet_effort_days` and `projected_em_effort_days`, and the result is stored as `required_observer_sea_days`. The plan moves to `PUBLISHED` and its `version` increments. The fishery's target is deliberately read live at each calculation rather than frozen into the plan, so a mid-season amendment to `coverage_target_pct` changes the closing arithmetic.

Selection activity (§3.3) then moves the plan to `SELECTION_COMPLETED`, where the season accumulates results: `actual_observer_sea_days` sums the `actual_sea_days` of deployments closed under the plan, and `actual_em_sea_days` sums the `trip_sea_days` of accepted EM trips credited to it. When the season ends the coordinator closes the plan, supplying `actual_fleet_effort_days`. Closing is refused while any deployment under the plan remains open — that is, in any of `SCHEDULED`, `SAFETY_HOLD`, `READY_TO_DEPLOY`, `AT_SEA`, `RETURNED`, `EARLY_TERMINATED`, `DEBRIEFING`, `DATA_REJECTED`, or `DATA_VALIDATED` — with `ERR_PLAN_HAS_OPEN_DEPLOYMENTS`. Closing re-runs the same four-step calculation in its final variant, substituting `actual_fleet_effort_days` and the accumulated `actual_em_sea_days` for the projections, and stores the outcome as `final_required_observer_sea_days` — a field that remains null until the plan closes, as does `coverage_attainment_pct`; for the same plan, the provisional and final figures diverge whenever actuals departed from projections. Attainment is then recorded as `coverage_attainment_pct`: the plan's `actual_observer_sea_days` divided by `final_required_observer_sea_days`, rounded half-up to four decimal places — and zero when both figures are zero. The close also sweeps the plan's notices as described in §3.3 before the plan lands in `CLOSED`, its terminal state, with `version` incremented.

### 3.3. Vessel Selection: Scoring, Runs, and Notices

With a published plan in hand, the coordinator launches a **selection run**, supplying a `notice_response_deadline` — the timestamp after which unanswered notices of the run may lapse — and the OCC token `expected_coverage_plan_version` of §2.8. The first run requires the plan in `PUBLISHED` and moves it to `SELECTION_COMPLETED`; backfill runs may follow while the plan remains in `SELECTION_COMPLETED`. A run attempted against a plan still in `DRAFT` is rejected with `ERR_PLAN_NOT_PUBLISHED`, a run against a plan in any other non-runnable state is rejected with `ERR_INVALID_STATE`, and in every case the fishery must be `ACTIVE` or the run fails with `ERR_FISHERY_NOT_ACTIVE`.

Eligibility is filtered before any scoring. A vessel may be scored only when all of the following hold: the vessel is `ACTIVE`; its `monitoring_mode` is `HUMAN_OBSERVER`; its `fishery_id` matches the plan's fishery; its operator's `payment_standing` is `GOOD`; and the vessel holds no notice in `ISSUED` or `ACCEPTED` under this plan — the clause that keeps backfill runs from double-notifying a vessel already in play.

Each surviving vessel is then scored on three components. The recency component rewards time away from observation: count the whole days between the vessel's `last_observed_end_date` and the plan's `period_start` — a never-observed vessel counts 365 days — cap that count at 365, express it as a fraction of 365, and multiply by a weight of 50. The compliance component is 30 when the vessel's `substantiated_harassment_count` is zero, and otherwise 30 less 10 points per substantiated report, never dropping below zero. The penalty component is 5 points for every point of the vessel's `selection_penalty_points`. The raw score is the recency component plus the compliance component minus the penalty component; when the vessel's `gear_type` equals the fishery's `priority_gear`, the raw score is then multiplied by 1.25. The result, rounded half-up to four decimal places, becomes the notice's `selection_score`.

Vessels are ranked by score descending; ties break first by `last_observed_end_date` ascending with never-observed vessels ranking ahead of all dated ones, then by the vessel's `created_at` ascending — the vessel's `id` must never be consulted for ranking. The run sizes itself from the requirement: the number of vessels to select is `required_observer_sea_days` divided by the 30-day notice allocation, rounded up to a whole number, and the run takes the top-ranked vessels up to that count, or the whole eligible pool when the pool is smaller. Every selected vessel receives exactly one **selection notice** in `ISSUED` status, carrying `allocated_sea_days` of 30, `reserved_sea_days` and `consumed_sea_days` of zero, `remaining_sea_days` of 30, its `selection_score`, its 1-based `rank` within the run, and a `response_deadline` copied from the run's `notice_response_deadline`. The run itself records its `coverage_plan_id`, a 1-based `run_index` sequenced among the plan's runs by creation time, the `vessels_evaluated` count, the `vessels_selected` count, and `selection_deficit_sea_days` — the requirement minus 30 days per selected vessel, floored at zero. An empty eligible pool is not an error: the run simply completes with `vessels_selected` at zero and the deficit equal to the entire requirement. Whether first run or backfill, the run increments the plan's `version`.

A notice reaches the vessel's operator, who answers it directly. Accepting requires that the caller own the notice's vessel and that the current clock has not passed the `response_deadline` — a late answer is rejected with `ERR_NOTICE_EXPIRED` — and moves the notice `ISSUED` → `ACCEPTED`, incrementing its `version`. Declining, under the same ownership rule, moves it `ISSUED` → `DECLINED`, a terminal state, likewise incrementing `version`. Notices that outlive their deadline unanswered are moved `ISSUED` → `EXPIRED` by the operations checkpoint of §2.7.

From `ACCEPTED`, a notice has three terminal exits, all system-driven. It is fulfilled automatically when a closing deployment leaves it with `remaining_sea_days` of zero and no other open deployment referencing it (§2.10). It is defaulted by the plan-close cascade when the season ends with `remaining_sea_days` still positive — an outcome that also adds 2 points to the vessel's `selection_penalty_points`. And it is voided, reserved days released, if the vessel activates electronic monitoring (§3.8). The plan-close cascade itself sweeps every notice of the plan symmetrically: notices still `ISSUED` move to `EXPIRED`; `ACCEPTED` notices whose `remaining_sea_days` is zero move to `FULFILLED`; and `ACCEPTED` notices with days remaining move to `DEFAULTED` with the 2-point penalty.

### 3.4. Scheduling a Deployment and the Pre-Boarding Safety Gate

A coordinator schedules a **deployment** against an accepted notice, naming the `selection_notice_id`, the `observer_id`, the `scheduled_departure_date`, and the `scheduled_return_date`, and presenting `expected_selection_notice_version` for the concurrency check of §2.8. The request is screened end-to-end before anything is written. The notice must be `ACCEPTED` — anything else yields `ERR_NOTICE_NOT_ACCEPTED`. The return date must fall after the departure, else `ERR_DATE_RANGE_INVALID`, and the resulting `planned_sea_days` — the inclusive calendar-day count from departure through return — must not exceed 45 days, else `ERR_DEPLOYMENT_TOO_LONG`. The vessel must be `ACTIVE` (`ERR_VESSEL_NOT_ACTIVE`), must still fish in `HUMAN_OBSERVER` mode (`ERR_VESSEL_NOT_HUMAN_MODE`), and its operator must stand at `GOOD` (`ERR_OPERATOR_DELINQUENT`). The observer must be `ACTIVE` (`ERR_OBSERVER_NOT_AVAILABLE`).

Two workload ceilings guard the observer. The consecutive cap rejects the write with `ERR_OBSERVER_CONSECUTIVE_CAP_EXCEEDED` when `planned_sea_days` exceeds the observer's `max_consecutive_sea_days` — landing exactly on the cap is allowed. The commitment cap sums the planned days of the observer's other deployments in `SCHEDULED`, `SAFETY_HOLD`, `READY_TO_DEPLOY`, or `AT_SEA` and rejects with `ERR_OBSERVER_COMMITMENT_CAP_EXCEEDED` when that sum plus the new `planned_sea_days` would exceed 90 days — again, equality is allowed.

Two calendar-conflict rules complete the screen. The observer must hold no other deployment in `SCHEDULED`, `SAFETY_HOLD`, `READY_TO_DEPLOY`, or `AT_SEA` whose closed departure-to-return interval intersects the new one — touching dates count as overlap — else `ERR_OBSERVER_OVERLAP`. And the vessel must enjoy at least one full in-port calendar day between any such existing deployment's return and the new departure — formally, the day gap from the existing return to the new departure, minus one, must be at least one — else `ERR_VESSEL_TURNAROUND_VIOLATION`. Finally, the planned days must fit within the notice's `remaining_sea_days`, else `ERR_SEA_DAY_ALLOCATION_EXCEEDED`.

On acceptance the deployment is born in `SCHEDULED` with its `coverage_plan_id` and `vessel_id` denormalized from the notice, and the sea-day ledger reconciles per §2.9: the planned days move from the notice's `remaining_sea_days` into its `reserved_sea_days`, and the notice's `version` increments.

Rescheduling reopens the dates while the deployment is in `SCHEDULED` or `SAFETY_HOLD`. The new `scheduled_departure_date` and `scheduled_return_date` are re-validated against every rule above — range, length, observer overlap, vessel turnaround, both observer caps, and notice allocation — and the ledger moves the day-count delta between `remaining_sea_days` and `reserved_sea_days`, never letting the remainder go negative. A reschedule out of `SAFETY_HOLD` returns the deployment to `SCHEDULED` and resets `latest_safety_result` to null; either way, the deployment's `version` and the notice's `version` each increment.

Cancellation is available to the coordinator while the deployment is in `SCHEDULED`, `SAFETY_HOLD`, or `READY_TO_DEPLOY` — and also arrives unbidden from the delinquency and EM cascades of §2.10. Cancellation releases the reservation: `reserved_sea_days` drops by `planned_sea_days`, `remaining_sea_days` rises by the same amount, the notice's `version` increments, and the deployment lands in the terminal `CANCELLED`.

Before anyone boards, the assigned observer conducts the pre-boarding **safety inspection** — only the deployment's own observer may file it, anyone else drawing `ERR_FORBIDDEN`. The checklist records five booleans: `life_raft_certified`, `epirb_registered`, `immersion_suits_adequate`, `fire_suppression_ok`, and `comms_equipment_ok`. All five must be present; a checklist with missing entries is rejected with `ERR_SAFETY_CHECKLIST_INCOMPLETE`. The `result` is computed, never supplied: `PASS` exactly when all five booleans are true, otherwise `FAIL`. A pass from `SCHEDULED` advances the deployment to `READY_TO_DEPLOY` and sets `latest_safety_result` to `PASS`. A fail requires `deficiency_notes` — absent notes on a failing checklist again yield `ERR_SAFETY_CHECKLIST_INCOMPLETE` — drops the deployment into `SAFETY_HOLD`, and sets `latest_safety_result` to `FAIL`. Re-inspection from `SAFETY_HOLD` must reference the failed inspection it supersedes via `supersedes_inspection_id`; pointing anywhere but the deployment's most recent `FAIL` inspection yields `ERR_SAFETY_SUPERSESSION_REQUIRED`, and a passing re-inspection lifts the deployment to `READY_TO_DEPLOY`. Each inspection is stamped with its `deployment_id`, the inspected `vessel_id`, and the acting `observer_id`, and inspection records are immutable once filed (§2.4). Boarding itself is the observer's act, permitted only from `READY_TO_DEPLOY` and moving the deployment to `AT_SEA`; a boarding attempt from `SCHEDULED` or `SAFETY_HOLD` — that is, without a current passing inspection — is rejected with `ERR_SAFETY_CHECK_REQUIRED`.

### 3.5. At Sea: Haul Sampling, Return, and Early Termination

While the deployment is `AT_SEA` — and only then, attempts in any other status drawing `ERR_INVALID_STATE` — the deployment's observer records **haul samples**. Each sample carries the `haul_date`, which must fall within the scheduled departure-to-return window inclusive (`ERR_DATE_RANGE_INVALID`); a `haul_number` starting at 1 and unique within the deployment (`ERR_DUPLICATE_HAUL_NUMBER`); the `species_code`; the `sampled_weight_kg`, a positive two-decimal weight; and the `total_haul_weight_kg`, which must be at least the sampled weight. The computed `sampling_ratio` — the sampled weight divided by the total haul weight, rounded half-up to four decimals — must lie between 0.2000 and 1.0000 inclusive, else `ERR_SAMPLE_RATIO_OUT_OF_RANGE`. Samples are born `RECORDED` and are resolved later during debriefing (§3.6).

The observer ends the trip by recording the `actual_return_date` — null until this moment, as is `actual_sea_days` — which must fall on or after the scheduled departure and on or before the scheduled return, else `ERR_DATE_RANGE_INVALID`. The deployment moves `AT_SEA` → `RETURNED`, its `actual_sea_days` is computed as the inclusive day count from `scheduled_departure_date` through `actual_return_date`, and the notice ledger converts the reservation into consumption exactly as §2.9 describes: `reserved_sea_days` falls by `planned_sea_days`, `consumed_sea_days` rises by `actual_sea_days`, and `remaining_sea_days` is credited with the difference between planned and actual days.

A deployment can also end early through the harassment cascade of §3.7, landing in `EARLY_TERMINATED` with `early_termination_reason` set to `HARASSMENT`. In that case the `actual_return_date` is set to the current clock date, and `actual_sea_days` is the inclusive count from `scheduled_departure_date` through that date, clamped to at least 1 day and at most `planned_sea_days`. The notice reconciliation is identical to a normal return.

### 3.6. Debriefing, Sample Verification, and Deployment Close

Data review is segregated from data collection. After a return — or an early termination — the observer submits the trip's data, which requires at least one haul sample to exist on the deployment: a submission with none is rejected with `ERR_INVALID_REQUEST`. The submission stamps `submitted_at` with the current clock and moves the deployment `RETURNED` → `DEBRIEFING` (or `EARLY_TERMINATED` → `DEBRIEFING`). Independently, a coordinator assigns the review to a debriefer by supplying `debriefer_id`; the deployment records the choice in `assigned_debriefer_id`. Segregation of duties forbids assigning a debriefer whose `person_ref` equals the deployment observer's `person_ref` — such a pairing is rejected with `ERR_DEBRIEFER_CONFLICT_OF_INTEREST`. The validation and rejection calls that follow require an assigned debriefer (`ERR_DEBRIEFER_NOT_ASSIGNED` when none is set) and require the caller to be exactly that debriefer (`ERR_FORBIDDEN` otherwise).

During `DEBRIEFING`, the assigned debriefer works through the samples one by one. Flagging a `RECORDED` sample moves it to `FLAGGED` and stores the supplied `reason` as `flagged_reason`. Verification moves a `RECORDED` or a `FLAGGED` sample to the terminal `VERIFIED`. Discarding moves a `FLAGGED` sample to the terminal `DISCARDED`, again taking a `reason`. Whichever action the debriefer takes stamps the sample's `verified_by_debriefer_id` with their id.

Validation closes the review and is gated three times, in order. Gate one: every haul sample of the deployment must stand in `VERIFIED` or `DISCARDED` — any sample still `RECORDED` or `FLAGGED` fails validation with `ERR_SAMPLES_NOT_RESOLVED`. Gate two: at least one sample must be `VERIFIED`, else `ERR_SAMPLE_COVERAGE_INSUFFICIENT`. Gate three: the verified coverage — the sum of `sampled_weight_kg` over the verified samples divided by the sum of their `total_haul_weight_kg`, rounded half-up to four decimals — must be at least 0.2000 (0.2000 passes; 0.1999 fails), again else `ERR_SAMPLE_COVERAGE_INSUFFICIENT`. Passing all three moves the deployment `DEBRIEFING` → `DATA_VALIDATED`. Alternatively, the debriefer rejects the data with a `rejection_reason`, moving the deployment to `DATA_REJECTED`, from which the observer may resubmit the trip data — resubmission restamps `submitted_at` and returns the deployment to `DEBRIEFING` for another pass.

Closing is the coordinator's final act on a validated deployment and credits the season tallies in one sweep: the observer's `sea_days_used_ytd` grows by `actual_sea_days`, the vessel's `sea_days_observed_ytd` grows by the same, the vessel's `last_observed_end_date` is set to the `actual_return_date`, and the plan's `actual_observer_sea_days` grows by `actual_sea_days`. If the deployment's notice now shows `remaining_sea_days` of zero and no other open deployment references it, the notice fulfills itself to `FULFILLED` per §2.10. The deployment lands in `CLOSED`, its terminal state, with `version` incremented.

### 3.7. Harassment and Interference Reporting

An observer who experiences coercion or meddling files a **harassment report** against their own deployment, supplying the `report_type` — `HARASSMENT`, `INTERFERENCE`, or `SAFETY_COERCION` — a free-text `narrative`, and the `incident_date`. The report captures the `deployment_id`, the filing `observer_id`, and the deployment's `vessel_id`, opens in `FILED`, and carries `penalty_applied` initialized to false. A coordinator opens review (`FILED` → `UNDER_REVIEW`, the report's `version` incrementing); the same action later reopens an `APPEALED` report for a second look (`APPEALED` → `UNDER_REVIEW`).

Adjudication belongs to the administrator. Substantiating a report — recording `resolution_notes` — fires a two-hop cascade. Hop one: if the linked deployment is still `AT_SEA`, it is terminated on the spot per §3.5's early-termination arithmetic, landing in `EARLY_TERMINATED` with the corresponding notice reconciliation. Hop two, executed only while `penalty_applied` is still false: the vessel's `selection_penalty_points` grows by 3 and its `substantiated_harassment_count` grows by 1, and `penalty_applied` flips to true — the flag that keeps a re-affirmation after appeal from punishing the vessel twice. The report lands in `SUBSTANTIATED` with `version` incremented. Dismissing a report from `UNDER_REVIEW` — again with `resolution_notes` — runs the mirror image only when `penalty_applied` is true, which is precisely the dismissal-after-appeal case: 3 points are refunded from `selection_penalty_points`, the `substantiated_harassment_count` is decremented by 1, and `penalty_applied` flips back to false; a dismissal with no penalty previously applied touches the vessel not at all. The report lands in the terminal `DISMISSED` with `version` incremented.

From `SUBSTANTIATED`, the vessel's operator may appeal — ownership of the report's vessel is checked — moving the report to `APPEALED` with `version` incremented, from which a fresh review can substantiate or dismiss it again. Alternatively, an administrator resolves a substantiated report after remediation, recording `resolution_notes` and moving the report to the terminal `RESOLVED`.

### 3.8. Electronic Monitoring: Enrollment, Trips, and Video Review

Electronic monitoring is the program's alternative to shipping a human observer. An operator applies for an **EM enrollment** on one of its vessels, supplying the `vessel_id`, the `equipment_vendor`, and the `equipment_install_date`; a vessel may hold only one open enrollment at a time — one in `PENDING_REVIEW`, `APPROVED`, `ACTIVE`, or `SUSPENDED` — and a second application against such a vessel is rejected with `ERR_EM_ENROLLMENT_OPEN_EXISTS`. The application opens in `PENDING_REVIEW`. An administrator adjudicates it: approval moves it to `APPROVED`, rejection moves it to the terminal `REJECTED` with the supplied `rejection_reason` recorded, and either decision stamps `reviewed_by_user_id` with the administrator's `X-User-ID`.

Activation is the coordinator's lever, and it is disruptive by design. Activating an `APPROVED` enrollment moves it to `ACTIVE` and fires the cascade of §2.10: the vessel's `monitoring_mode` flips to `ELECTRONIC_MONITORING`, every open notice of the vessel (`ISSUED` or `ACCEPTED`) is voided, and each deployment of a voided notice still in `SCHEDULED`, `SAFETY_HOLD`, or `READY_TO_DEPLOY` is cancelled with its reserved days released. Reactivating a `SUSPENDED` enrollment (`SUSPENDED` → `ACTIVE`) performs no such cascade. An administrator may suspend an active enrollment (`ACTIVE` → `SUSPENDED`), and may terminate one from either `ACTIVE` or `SUSPENDED` — termination is refused while any of the enrollment's trips remains in `DECLARED`, `FOOTAGE_SUBMITTED`, `IN_REVIEW`, or `REVIEWED` — which lands the enrollment in the terminal `TERMINATED` and flips the vessel's `monitoring_mode` back to `HUMAN_OBSERVER`.

With an `ACTIVE` enrollment in place, the operator declares an **EM trip** with `vessel_id`, `departure_date`, and `return_date`. Declaration requires the vessel to be in `ELECTRONIC_MONITORING` mode (else `ERR_VESSEL_NOT_EM_MODE`), the vessel's enrollment to be `ACTIVE` (a `PENDING_REVIEW`, `APPROVED`, or `SUSPENDED` enrollment yields `ERR_EM_ENROLLMENT_NOT_ACTIVE`), and the return to fall after the departure (`ERR_DATE_RANGE_INVALID`). The new trip's closed date interval must not intersect any other trip of the vessel in `DECLARED`, `FOOTAGE_SUBMITTED`, `IN_REVIEW`, or `REVIEWED`, nor any deployment of the vessel in `SCHEDULED`, `SAFETY_HOLD`, `READY_TO_DEPLOY`, or `AT_SEA` — touching dates count as overlap — else `ERR_EM_TRIP_OVERLAP`. The trip is born `DECLARED`, linked to the enrollment through `em_enrollment_id`, with its `trip_sea_days` computed as the inclusive day count from departure through return.

After the trip, the operator submits its footage declaration: a positive two-decimal `video_hours` (a non-positive value is `ERR_INVALID_REQUEST`), which moves the trip `DECLARED` → `FOOTAGE_SUBMITTED` and stores the figure. A coordinator then assigns a reviewer by `reviewer_id` — the named reviewer must be `ACTIVE` — moving the trip `FOOTAGE_SUBMITTED` → `IN_REVIEW` and stamping `assigned_reviewer_id`. Until footage is submitted, `reviewed_pct` is null; it becomes a number only once `video_hours` exists. Review then proceeds in increments: the assigned reviewer records batches of `additional_reviewed_hours` and `sampled_catch_kg_delta`, each call adding to `reviewed_hours` and `sampled_catch_kg` and recomputing `reviewed_pct` as `reviewed_hours` divided by `video_hours`, rounded half-up to four decimals. Recording before any reviewer is assigned is `ERR_REVIEWER_NOT_ASSIGNED`; recording by anyone other than the assigned reviewer is `ERR_FORBIDDEN`. The moment `reviewed_pct` reaches 0.3000, the trip promotes itself `IN_REVIEW` → `REVIEWED` — 0.2999 stays `IN_REVIEW`, 0.3000 promotes.

A reviewed trip is then accepted or rejected by a coordinator. Acceptance requires the trip to be `REVIEWED` — attempting it earlier yields `ERR_EM_REVIEW_MIN_NOT_MET` — and requires that exactly one coverage plan exists for the vessel's fishery whose window contains the trip's `departure_date` through `return_date` and whose status is `SELECTION_COMPLETED`; with no such unique plan the accept fails with `ERR_NO_COVERAGE_PLAN_FOR_TRIP`. On acceptance, the trip's `estimated_total_catch_kg` — null until this moment — is extrapolated as `sampled_catch_kg` scaled by `video_hours` over `reviewed_hours`, rounded half-up to two decimals, and the plan's `actual_em_sea_days` grows by `trip_sea_days`; the trip lands in the terminal `ACCEPTED`. Rejection, carrying a `rejection_reason`, lands the trip in the terminal `REJECTED` and grants no coverage credit. EM-covered days are never billed under cost recovery (§3.9).

### 3.9. Cost Recovery: Invoices, Payments, Adjustments, and Delinquency

The program recovers observer costs from industry, vessel by vessel, once a season's data has settled. A coordinator triggers invoice generation against a plan in `SELECTION_COMPLETED` or `CLOSED` — any other status yields `ERR_PLAN_NOT_PUBLISHED`. Generation collects the plan's `CLOSED` deployments (linked through their notices' `coverage_plan_id`), groups them by vessel, and produces one **invoice** per vessel with at least one such deployment; a vessel that already has a non-terminal invoice for the same plan is skipped. The response reports `created_invoice_ids` for the invoices minted and `skipped_vessel_ids` for the vessels passed over.

Pricing is cumulative per vessel. The vessel's billable deployments are ordered by `scheduled_departure_date` ascending, ties broken by the deployment's `created_at` ascending, and a running day index walks every billed day of every deployment in that order: days whose running index falls within the first 20 are priced at the tier-1 rate of 39900 cents per day, and every day from the twenty-first onward at the tier-2 rate of 49900 cents per day. Each deployment contributes one entry to the invoice's `line_items` array, recording `deployment_id`, `days`, `tier1_days`, `tier2_days`, `line_subtotal_cents`, and `line_total_cents`. The line subtotal is the tier-1 days at the tier-1 rate plus the tier-2 days at the tier-2 rate, multiplied by the fee-variant factor — 1 for the `STANDARD` variant, one half for the `SMALL_VESSEL` variant that applies when the vessel's `length_ft` is under 40 feet. The line total is the line subtotal inflated by a 3.7 percent surcharge, rounded half-up to whole cents. Rounding order is pinned: each line is rounded to cents first, and `amount_due_cents` is the sum of the already-rounded line totals — summing subtotals first and rounding once produces different cents and is non-conformant. The invoice also records its `fee_variant` and `sea_days_billed`, the sum of `actual_sea_days` over the billed deployments.

One cap protects small earners. When the vessel carries a `declared_annual_revenue_cents` value, the amount due is capped at the whole-cent floor of one half of one percent of that declared revenue; if the cap binds, `amount_due_cents` is replaced by the cap and `fee_cap_applied` is set true, otherwise it stays false. Every invoice tracks `amount_paid_cents` (zero at birth), `amount_adjusted_cents` (zero at birth), and the derived `amount_outstanding_cents` — the amount due plus adjustments minus payments — which must never go negative.

A generated invoice sits in `DRAFT` until a coordinator issues it. Issuing stamps `issued_by_user_id` with the coordinator's `X-User-ID`, sets `issue_date` to the current clock date, and sets `due_date` exactly 30 days after the issue date; the invoice moves to `ISSUED` with `version` incremented.

From there the operator pays it down, in whole or in part, each payment carrying `amount_cents`. A payment must be a positive integer number of cents (`ERR_PAYMENT_NOT_POSITIVE`), must not exceed the current `amount_outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`), and is accepted only while the invoice is in `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE` — against any other status, `ERR_INVOICE_NOT_ISSUED`. A payment smaller than the outstanding balance raises `amount_paid_cents` and moves an `ISSUED` invoice to `PARTIALLY_PAID`, leaves a `PARTIALLY_PAID` invoice in `PARTIALLY_PAID`, and leaves an `OVERDUE` invoice in `OVERDUE`. A payment exactly equal to the outstanding balance zeroes `amount_outstanding_cents` and moves the invoice to the terminal `PAID` from any of the three payable states; and whenever a payment or waiver leaves the operator with no remaining `OVERDUE` invoices, the operator's `payment_standing` returns to `GOOD` — though its vessels remain `SUSPENDED` until manually reactivated (§2.10). Every payment increments the invoice's `version`.

An operator who disagrees with an issued invoice disputes it — ownership is checked — moving `ISSUED` → `DISPUTED` with a `reason`; a coordinator later resolves the dispute, moving `DISPUTED` → `ISSUED`, each step incrementing `version`.

Corrections are the administrator's province and carry two safeguards. Posting an adjustment supplies a signed `adjustment_cents`, a `reason`, and the OCC token `expected_invoice_version` of §2.8. Segregation of duties forbids the issuer from adjusting their own invoice: the caller's `X-User-ID` must differ from the invoice's `issued_by_user_id`, else `ERR_INVOICE_ADJUSTMENT_FORBIDDEN`. And the adjustment may not drive `amount_outstanding_cents` below zero, else `ERR_ADJUSTMENT_WOULD_UNDERFLOW`. Adjustments are permitted in `ISSUED`, `OVERDUE`, and `DISPUTED`; each adds to `amount_adjusted_cents`, recomputes the outstanding balance, and increments `version` without changing the invoice's status. Waiving is the heavier instrument, available from the same three statuses under the same segregation-of-duties rule: it sets `amount_adjusted_cents` so that `amount_outstanding_cents` becomes exactly zero — numerically, the adjustment equals `amount_paid_cents` minus `amount_due_cents` — and moves the invoice to the terminal `WAIVED`, with the same standing recompute as a full payment.

Left unpaid, an invoice ages. When the operations checkpoint (§2.7) finds an invoice in `ISSUED` or `PARTIALLY_PAID` whose `due_date` has passed with `amount_outstanding_cents` still positive, it moves the invoice to `OVERDUE` and fires the delinquency cascade of §2.10 — operator to `DELINQUENT`, active vessels to `SUSPENDED`, open deployments cancelled with their reserved days released. Even then the invoice remains payable: partial payments keep it `OVERDUE`, a full payment moves it to `PAID`, and a waiver moves it to `WAIVED`, each restoring the operator's standing once no other `OVERDUE` invoices remain.

## 4. Endpoint Definitions

Operations that create a new resource — registry records, coverage plans, selection runs, deployments, safety inspections, haul samples, harassment reports, EM enrollments, EM trips, invoice generation, payments, and adjustments — return `201 Created`. Operations that modify or transition an existing resource — publishes, closes, answers, boardings, returns, submissions, assignments, validations, disputes, waivers, and the like — return `200 OK`. Request payloads, derived fields, and side effects are specified in §3; this table is the navigational index back to those narratives.

List endpoints accept optional filter query parameters naming their resource's foreign keys and status fields, alongside the pagination parameters of §2.3. The fishery list filters by `status`; the operator list by `payment_standing` and `status`; the vessel list by `operator_id`, `fishery_id`, `status`, and `monitoring_mode`; the observer list by `status` and `certification_level`; the debriefer and EM-reviewer lists by `status`; the coverage-plan list by `fishery_id` and `status`; the selection-notice list by `selection_run_id`, `coverage_plan_id`, `vessel_id`, and `status`; the deployment list by `selection_notice_id`, `coverage_plan_id`, `vessel_id`, `observer_id`, `assigned_debriefer_id`, and `status`; the safety-inspection list by `deployment_id`, `observer_id`, `vessel_id`, `supersedes_inspection_id`, and `result`; the haul-sample list by `deployment_id`, `verified_by_debriefer_id`, and `status`; the harassment-report list by `deployment_id`, `observer_id`, `vessel_id`, and `status`; the EM-enrollment list by `vessel_id` and `status`; the EM-trip list by `vessel_id`, `em_enrollment_id`, `assigned_reviewer_id`, and `status`; and the invoice list by `coverage_plan_id`, `vessel_id`, `operator_id`, and `status`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/observer-program/fisheries` | Create a fishery | ProgramAdmin |
| GET | `/observer-program/fisheries` | List fisheries | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/fisheries/{id}` | Get a fishery | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| PATCH | `/observer-program/fisheries/{id}` | Update fishery config or status | ProgramAdmin |
| POST | `/observer-program/vessel-operators` | Register a vessel operator | ProgramAdmin |
| GET | `/observer-program/vessel-operators` | List operators | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/vessel-operators/{id}` | Get an operator | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/vessels` | Register a vessel | VesselOperator |
| GET | `/observer-program/vessels` | List vessels | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/vessels/{id}` | Get a vessel | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| PATCH | `/observer-program/vessels/{id}` | Update vessel attributes or status | ProgramAdmin |
| POST | `/observer-program/observers` | Create an observer | ProgramAdmin |
| GET | `/observer-program/observers` | List observers | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/observers/{id}` | Get an observer | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| PATCH | `/observer-program/observers/{id}` | Update observer attributes or status | ProgramAdmin |
| POST | `/observer-program/debriefers` | Create a debriefer | ProgramAdmin |
| GET | `/observer-program/debriefers` | List debriefers | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/debriefers/{id}` | Get a debriefer | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| PATCH | `/observer-program/debriefers/{id}` | Update debriefer status | ProgramAdmin |
| POST | `/observer-program/em-reviewers` | Create an EM reviewer | ProgramAdmin |
| GET | `/observer-program/em-reviewers` | List EM reviewers | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/em-reviewers/{id}` | Get an EM reviewer | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| PATCH | `/observer-program/em-reviewers/{id}` | Update EM reviewer status | ProgramAdmin |
| POST | `/observer-program/coverage-plans` | Create a coverage plan (DRAFT) | ProgramCoordinator |
| GET | `/observer-program/coverage-plans` | List coverage plans | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/coverage-plans/{id}` | Get a coverage plan | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/coverage-plans/{id}/publish` | Publish plan; computes the provisional coverage requirement | ProgramCoordinator |
| POST | `/observer-program/coverage-plans/{id}/close` | Close plan; computes the final requirement and attainment; cascades notices | ProgramCoordinator |
| POST | `/observer-program/coverage-plans/{id}/selection-runs` | Run vessel selection; creates selection notices | ProgramCoordinator |
| GET | `/observer-program/coverage-plans/{id}/selection-runs` | List selection runs of a plan | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/selection-runs/{id}` | Get a selection run | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/selection-notices` | List selection notices | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/selection-notices/{id}` | Get a selection notice | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/selection-notices/{id}/accept` | Operator accepts the selection notice | VesselOperator |
| POST | `/observer-program/selection-notices/{id}/decline` | Operator declines the selection notice | VesselOperator |
| POST | `/observer-program/deployments` | Create and schedule a deployment against an accepted notice | ProgramCoordinator |
| GET | `/observer-program/deployments` | List deployments | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/deployments/{id}` | Get a deployment | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/deployments/{id}/reschedule` | Change scheduled dates | ProgramCoordinator |
| POST | `/observer-program/deployments/{id}/cancel` | Cancel a pre-boarding deployment | ProgramCoordinator |
| POST | `/observer-program/deployments/{id}/board` | Observer boards the vessel | Observer |
| POST | `/observer-program/deployments/{id}/return` | Observer records return | Observer |
| POST | `/observer-program/deployments/{id}/submit-data` | Observer submits trip data (also resubmission after rejection) | Observer |
| POST | `/observer-program/deployments/{id}/assign-debriefer` | Assign a debriefer; segregation of duties enforced | ProgramCoordinator |
| POST | `/observer-program/deployments/{id}/validate-data` | Debriefer validates trip data | Debriefer |
| POST | `/observer-program/deployments/{id}/reject-data` | Debriefer rejects trip data for rework | Debriefer |
| POST | `/observer-program/deployments/{id}/close` | Close a validated deployment; credits observer, vessel, and plan sea days | ProgramCoordinator |
| POST | `/observer-program/deployments/{id}/safety-inspections` | Record a pre-boarding safety inspection | Observer |
| GET | `/observer-program/safety-inspections` | List safety inspections | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/safety-inspections/{id}` | Get a safety inspection | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/deployments/{id}/haul-samples` | Record a haul sample | Observer |
| GET | `/observer-program/haul-samples` | List haul samples | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/haul-samples/{id}` | Get a haul sample | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/haul-samples/{id}/verify` | Debriefer verifies a sample | Debriefer |
| POST | `/observer-program/haul-samples/{id}/flag` | Debriefer flags a sample | Debriefer |
| POST | `/observer-program/haul-samples/{id}/discard` | Debriefer discards a flagged sample | Debriefer |
| POST | `/observer-program/deployments/{id}/harassment-reports` | Observer files a harassment or interference report | Observer |
| GET | `/observer-program/harassment-reports` | List harassment reports | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/harassment-reports/{id}` | Get a harassment report | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/harassment-reports/{id}/start-review` | Open review (from FILED or APPEALED) | ProgramCoordinator |
| POST | `/observer-program/harassment-reports/{id}/substantiate` | Substantiate a report; terminates an at-sea deployment and penalizes the vessel (first time only) | ProgramAdmin |
| POST | `/observer-program/harassment-reports/{id}/dismiss` | Dismiss a report; compensates vessel penalties when dismissing after appeal | ProgramAdmin |
| POST | `/observer-program/harassment-reports/{id}/appeal` | Operator appeals a substantiated report | VesselOperator |
| POST | `/observer-program/harassment-reports/{id}/resolve` | Resolve a substantiated report after remediation | ProgramAdmin |
| POST | `/observer-program/em-enrollments` | Apply for EM enrollment (one open enrollment per vessel) | VesselOperator |
| GET | `/observer-program/em-enrollments` | List EM enrollments | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/em-enrollments/{id}` | Get an EM enrollment | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/em-enrollments/{id}/approve` | Approve an enrollment | ProgramAdmin |
| POST | `/observer-program/em-enrollments/{id}/reject` | Reject an enrollment | ProgramAdmin |
| POST | `/observer-program/em-enrollments/{id}/activate` | Activate an approved (or reactivate a suspended) enrollment; flips vessel to EM mode and voids its open notices | ProgramCoordinator |
| POST | `/observer-program/em-enrollments/{id}/suspend` | Suspend an active enrollment | ProgramAdmin |
| POST | `/observer-program/em-enrollments/{id}/terminate` | Terminate an enrollment; flips the vessel back to human-observer mode | ProgramAdmin |
| POST | `/observer-program/em-trips` | Declare an EM trip | VesselOperator |
| GET | `/observer-program/em-trips` | List EM trips | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/em-trips/{id}` | Get an EM trip | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/em-trips/{id}/submit-footage` | Submit the video footage declaration | VesselOperator |
| POST | `/observer-program/em-trips/{id}/assign-reviewer` | Assign an EM reviewer | ProgramCoordinator |
| POST | `/observer-program/em-trips/{id}/record-review` | Reviewer records reviewed hours and sampled catch; auto-promotes at the review threshold | EMReviewer |
| POST | `/observer-program/em-trips/{id}/accept` | Accept a reviewed trip; extrapolates catch and credits plan EM sea days | ProgramCoordinator |
| POST | `/observer-program/em-trips/{id}/reject` | Reject a reviewed trip (no coverage credit) | ProgramCoordinator |
| POST | `/observer-program/coverage-plans/{id}/invoices/generate` | Generate DRAFT cost-recovery invoices, one per vessel with closed deployments under the plan | ProgramCoordinator |
| GET | `/observer-program/invoices` | List invoices | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| GET | `/observer-program/invoices/{id}` | Get an invoice | ProgramAdmin, ProgramCoordinator, Observer, Debriefer, VesselOperator, EMReviewer |
| POST | `/observer-program/invoices/{id}/issue` | Issue a DRAFT invoice | ProgramCoordinator |
| POST | `/observer-program/invoices/{id}/payments` | Apply a payment | VesselOperator |
| POST | `/observer-program/invoices/{id}/adjustments` | Post a signed adjustment (segregation of duties versus the issuer) | ProgramAdmin |
| POST | `/observer-program/invoices/{id}/dispute` | Operator disputes an issued invoice | VesselOperator |
| POST | `/observer-program/invoices/{id}/resolve-dispute` | Resolve a dispute back to issued | ProgramCoordinator |
| POST | `/observer-program/invoices/{id}/waive` | Waive the outstanding balance (segregation of duties versus the issuer) | ProgramAdmin |
| POST | `/observer-program/ops/run` | Operations checkpoint: expires lapsed notices and marks past-due invoices overdue, running the delinquency cascade | ProgramAdmin, ProgramCoordinator |
| POST | `/observer-program/_clock/set_current_utc` | Set the logical clock (test-driving endpoint) | ProgramAdmin |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions are defined in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_DEBRIEFER_CONFLICT_OF_INTEREST` | 403 |
| `ERR_INVOICE_ADJUSTMENT_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOTICE_NOT_ACCEPTED` | 409 |
| `ERR_PLAN_NOT_PUBLISHED` | 409 |
| `ERR_PLAN_HAS_OPEN_DEPLOYMENTS` | 409 |
| `ERR_SAFETY_CHECK_REQUIRED` | 409 |
| `ERR_SAFETY_CHECKLIST_INCOMPLETE` | 422 |
| `ERR_SAFETY_SUPERSESSION_REQUIRED` | 422 |
| `ERR_DATE_RANGE_INVALID` | 422 |
| `ERR_DEPLOYMENT_TOO_LONG` | 422 |
| `ERR_OBSERVER_OVERLAP` | 409 |
| `ERR_VESSEL_TURNAROUND_VIOLATION` | 409 |
| `ERR_EM_TRIP_OVERLAP` | 409 |
| `ERR_NOTICE_EXPIRED` | 409 |
| `ERR_FISHERY_NOT_ACTIVE` | 409 |
| `ERR_VESSEL_NOT_ACTIVE` | 409 |
| `ERR_OBSERVER_NOT_AVAILABLE` | 409 |
| `ERR_VESSEL_NOT_HUMAN_MODE` | 409 |
| `ERR_VESSEL_NOT_EM_MODE` | 409 |
| `ERR_EM_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_OPERATOR_DELINQUENT` | 409 |
| `ERR_DEBRIEFER_NOT_ASSIGNED` | 409 |
| `ERR_REVIEWER_NOT_ASSIGNED` | 409 |
| `ERR_OBSERVER_CONSECUTIVE_CAP_EXCEEDED` | 422 |
| `ERR_OBSERVER_COMMITMENT_CAP_EXCEEDED` | 422 |
| `ERR_SAMPLE_RATIO_OUT_OF_RANGE` | 422 |
| `ERR_DUPLICATE_HAUL_NUMBER` | 409 |
| `ERR_EM_ENROLLMENT_OPEN_EXISTS` | 409 |
| `ERR_COVERAGE_TARGET_OUT_OF_RANGE` | 422 |
| `ERR_SAMPLES_NOT_RESOLVED` | 409 |
| `ERR_SAMPLE_COVERAGE_INSUFFICIENT` | 422 |
| `ERR_EM_REVIEW_MIN_NOT_MET` | 409 |
| `ERR_NO_COVERAGE_PLAN_FOR_TRIP` | 409 |
| `ERR_UNIQUE_CONSTRAINT` | 409 |
| `ERR_SEA_DAY_ALLOCATION_EXCEEDED` | 422 |
| `ERR_PAYMENT_NOT_POSITIVE` | 422 |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 422 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_ADJUSTMENT_WOULD_UNDERFLOW` | 422 |
