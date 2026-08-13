# Pole Inspection Program API — Product Requirements Document

## 1. Introduction

Electric utilities run cyclical wood-pole inspection programs to find decay before it finds them: crews bore and sound each pole at the groundline, estimate how much of its original bending strength remains, and route the pole into monitoring, routine replacement, or priority replacement accordingly. Groundline preservative treatments extend the service life of poles worth keeping, and joint-use attachers — telephone and cable operators sharing the pole — must be audited so unauthorized attachments are detected, noticed, and cured on a deadline. All of this happens under a fixed fiscal-year appropriation, so every replacement decision is ultimately a budget decision.

This document specifies the Pole Inspection Program API, mounted under `/pole-program`, which manages that entire operating loop. An `InspectionCycle` samples the eligible pole population and generates field tasks; an `Inspector` submits decay readings and photo evidence; a `QAReviewer` accepts or rejects that work under segregation of duties; accepted classifications cascade onto the `Pole` and, for the worst poles, automatically queue a `ReplacementWorkOrder`. `TreatmentWorkOrder` resources drive groundline treatment through scheduling, application, warranty tracking, and quality review, while `ContractorCrew` quality scores govern who may be scheduled at all. The cycle closes with a reconcile checkpoint that requeues deferred replacements, escalates overdue attachment violations, funds the queued backlog against a `ProgramBudget` in priority order, computes per-crew production billing, and records an immutable `BacklogSnapshot` of the result.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to specify their operational capacity. The system recognizes exactly five roles, spelled precisely as follows: `ProgramManager`, `Inspector`, `QAReviewer`, `Contractor`, and `AttacherRep`. A request missing either header, or carrying a role value outside this set, is rejected with `ERR_UNAUTHENTICATED`. Access to specific operations is further restricted by role; an authenticated caller attempting an operation outside their role's remit is rejected with `ERR_FORBIDDEN`.

The `ProgramManager` is the utility program office: it owns budgets, cycles, the pole register, inspection-task creation and waiver, treatment-order creation and scheduling, warranty-claim filing and adjudication, replacement-order funding, attachment-audit adjudication, crew registration, and the logical clock. The `Inspector` performs field decay tests and submits inspection tasks. The `QAReviewer` decides quality reviews on both inspection tasks and treatment orders and is barred from reviewing work it submitted itself. The `Contractor` performs field work — applying treatment orders and completing replacement orders. The `AttacherRep` is a joint-use attacher representative who responds to violation notices by marking them cured. All five roles may call any read endpoint.

Role identity semantics differ by role. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `ContractorCrew`; ownership checks on any resource that references a `ContractorCrew` compare the resource's foreign-key field to `X-User-ID` — concretely, a `Contractor` may apply only a treatment order whose `crew_id` equals the caller's `X-User-ID`, and any mismatch is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `ProgramManager`, `Inspector`, `QAReviewer`, or `AttacherRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `submitted_by_user_id` on an `InspectionTask` or `filed_by_user_id` on a `WarrantyClaim`) but does not compare it to any entity's `id`, except where the segregation-of-duties rule in §3.4 applies.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. List endpoints in this API also expose domain filters documented per endpoint — inspection tasks filter by `pole_id`, `cycle_id`, and `status`; treatment orders by `pole_id`, `crew_id`, `status`, and `source_claim_id`; replacement orders by `pole_id`, `budget_id`, `cycle_id`, and `status`; attachment audits by `pole_id` and `inspection_task_id`; backlog snapshots by `cycle_id` and `budget_id`.

### 2.4. Common Resource Properties and Versioning

All primary resources — `ProgramBudget`, `InspectionCycle`, `Pole`, `InspectionTask`, `TreatmentWorkOrder`, `WarrantyClaim`, `ContractorCrew`, `ReplacementWorkOrder`, and `AttachmentAudit` — carry a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- **`version` (integer):** a system-managed integer that increments by one on every mutation of the resource, including mutations caused by cascades originating from operations on other resources.

The `BacklogSnapshot` resource is the single exception: it carries `id` and `created_at` only. Both `updated_at` and `version` are absent on snapshots, because a snapshot is an immutable record written once at reconcile time and never modified thereafter.

### 2.5. The Logical Clock

The server maintains a logical clock that is the single source of truth for every timestamp the system stamps and every temporal validation it evaluates — cycle open and reconcile instants, task due windows, treatment application times, warranty windows, claim filing times, cure deadlines, and quality-event ordering all read this clock. At server startup the logical clock is set to exactly `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time. An administrative, test-driving capability restricted to `ProgramManager` advances the clock to a supplied `to_iso8601` instant and returns the resulting `now_iso8601`.

### 2.6. Units, Precision, and Rounding

All monetary amounts in this API are integer cents: budget totals, committed and spent balances, estimated and actual replacement costs, treatment quotes, and crew billings are all whole-cent integers. Wherever a calculation produces a fractional cent — cost escalation, per-line billing components, bonuses — the result is rounded half-up to a whole cent at the step the relevant workflow specifies. Remaining-strength percentages and contractor quality scores are decimal values carried to exactly two decimal places, rounded half-up. Priority scores and escalation results are integers. Date-only inputs such as `install_date`, `work_start_date`, and `work_end_date` use the `YYYY-MM-DD` format; all datetimes are ISO 8601 UTC.

### 2.7. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and only those two; no other endpoint accepts a version field.

Funding a replacement order requires the request to carry `expected_budget_version`, a non-optional field holding the `version` of the target `ProgramBudget` as the client last observed it. If the budget's current `version` does not match — because a successful fund, defund, completion, or reconcile waterfall has advanced it since the client's read — the request is rejected with `ERR_STALE_BUDGET_VERSION` (HTTP 412), preventing the client from committing funds against a budget snapshot it has not observed.

Patching a pole's GIS attributes requires the request to carry `expected_pole_version`, a non-optional field holding the pole's `version` as the client last observed it. If the pole's current `version` has advanced — for example because a quality-review cascade refreshed the pole's classification fields after the client's read — the patch is rejected with `ERR_STALE_POLE_VERSION` (HTTP 412).

### 2.8. Validation Pipeline and Check Ordering

Every request passes through a fixed validation pipeline, and the stages are evaluated in a strict order; a failure at an earlier stage is reported and masks every later check. The stages, in order, are:

1. **Authentication** — `X-User-ID` and `X-User-Role` are present and the role is known, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted on the endpoint per the access matrix (and, for `Contractor`, the caller's `X-User-ID` equals the target order's `crew_id`), else `ERR_FORBIDDEN`.
3. **Well-formedness** — required body fields are present, types are valid, enum values are in their declared domains, and numeric ranges are respected, else `ERR_INVALID_REQUEST`.
4. **Existence** — path identifiers resolve left to right, then body foreign-key identifiers resolve, else the resource-specific 404 (see §2.9).
5. **State validity** — the target entity is in a valid state for the operation, else the state errors (`ERR_INVALID_STATE`, `ERR_CYCLE_NOT_OPEN`, `ERR_TASK_NOT_SUBMITTED`, `ERR_ORDER_NOT_QUEUED`, `ERR_POLE_REPLACED`, `ERR_CYCLE_TASKS_OPEN`, `ERR_CREW_SUSPENDED`).
6. **Optimistic concurrency** — the two OCC checks of §2.7, yielding `ERR_STALE_BUDGET_VERSION` or `ERR_STALE_POLE_VERSION`.
7. **Safety-of-work checks** — segregation of duties (`ERR_SOD_VIOLATION`) and the hazard-flag requirement (`ERR_HAZARD_FLAG_REQUIRED`).
8. **Uniqueness and conflict constraints** — the duplicate and scheduling/window conflict rules (`ERR_DUPLICATE_FISCAL_YEAR`, `ERR_DUPLICATE_POLE_NUMBER`, `ERR_DUPLICATE_CREW_CODE`, `ERR_DUPLICATE_INSPECTION`, `ERR_CLAIM_ALREADY_OPEN`, `ERR_CREW_SCHEDULE_CONFLICT`, `ERR_TASK_WINDOW_OVERLAP`).
9. **Temporal constraints** — window-shape and deadline rules (`ERR_INVALID_WINDOW`, `ERR_WARRANTY_EXPIRED`, `ERR_CURE_DEADLINE_PASSED`).
10. **Evidence requirements** — photo coverage for the computed classification (`ERR_PHOTO_EVIDENCE_REQUIRED`).
11. **Fiscal capacity** — funds sufficiency at funding time (`ERR_BUDGET_EXCEEDED`).

The ordering has observable consequences: a stale-budget rejection at stage 6 surfaces before any uniqueness conflict at stage 8, and a hazard-flag failure at stage 7 surfaces before a photo-coverage failure at stage 10, even when both would independently apply.

### 2.9. Identifier Resolution and Nested Retrieval

When an endpoint path contains resource identifiers, the system validates their existence in a sequential, left-to-right order and rejects the request immediately with the 404 corresponding to the first identifier that does not resolve. Only after path identifiers resolve does the system resolve foreign-key identifiers carried in the request body — `pole_id`, `cycle_id`, `crew_id`, `budget_id`, and `treatment_order_id`. Each unresolved identifier maps to its resource-specific error: `ERR_POLE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_TASK_NOT_FOUND`, `ERR_TREATMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, or `ERR_ORDER_NOT_FOUND`.

### 2.10. Cross-Entity Cascades and Compensating Actions

Many operations in this API mutate more than one entity as a single atomic act, and §3 states every cascade explicitly alongside its workflow: accepting an inspection classification rewrites the pole's condition fields and can spawn a replacement order; verifying a treatment updates crew quality counters, the crew's standing, and the pole's treatment state; completing a replacement moves money between budget buckets and retires the pole. Wherever a cascade mutates a resource, that resource's `updated_at` refreshes and its `version` increments by one, so a client watching either entity observes the change.

Two operations are deliberate compensating actions. Defunding a replacement order releases its committed funds and returns the budget's available balance to exactly its pre-fund value. Waiving an inspection task leaves the pole's `last_inspection_date` untouched, which deliberately returns the pole to the eligible sampling pool of a future cycle rather than marking it inspected.

## 3. Business Logic & Workflows

### 3.1. Program Foundations: Budgets, the Pole Register, and Cycle Setup

A fiscal-year budget anchors all program spending. A `ProgramManager` creates a `ProgramBudget` by supplying a `fiscal_year` and a `total_cents` appropriation; the fiscal year must fall between 2000 and 2100 inclusive, the total must be zero or greater, and the fiscal year must be unique across all budgets — a duplicate is rejected with `ERR_DUPLICATE_FISCAL_YEAR`. Three computed balances track the money: `committed_cents` is the sum of `escalated_cost_cents` over every replacement order in `FUNDED` status charged to the budget, `spent_cents` is the sum of `actual_cost_cents` over every `COMPLETED` order charged to the budget, and `available_cents` is the total minus committed minus spent. The invariant that the total always equals available plus committed plus spent holds at all times.

The pole register records every pole in service territory. Registering a `Pole` requires a unique non-empty `pole_number` (a duplicate is rejected with `ERR_DUPLICATE_POLE_NUMBER`), a `species` of `SOUTHERN_PINE`, `DOUGLAS_FIR`, `WESTERN_RED_CEDAR`, or `LARCH`, an `original_class` drawn from the ANSI classes `H1`, `1`, `2`, `3`, `4`, `5`, an `install_date`, coordinates `gis_lat` and `gis_lon`, a zone `gis_tag`, and a `height_ft` greater than zero. Joint-use presence is declared through the optional `joint_use` flag, defaulting to false, and `attachment_count_declared`, the number of third-party attachments on record, defaulting to zero and never negative. A pole begins `IN_SERVICE`; its lifecycle states are `IN_SERVICE`, `MONITOR`, `PRIORITY_REJECT`, and the terminal `REPLACED`. Computed condition fields — `current_remaining_strength_pct`, `current_classification` (initially `NONE`), `last_inspection_date`, `last_treatment_date`, and `open_treatment_count` — start empty or zero and are maintained by the inspection and treatment workflows below. A `gis_tag` of `FEEDER_CRITICAL` marks feeder-critical poles and earns a priority floor in the replacement scoring of §3.8.

GIS attributes drift over time, and a `ProgramManager` may supersede a pole's `gis_lat`, `gis_lon`, and `gis_tag` through the GIS-attribute patch. The patch is one of the two OCC-guarded writes of §2.7: it must carry `expected_pole_version`, a stale version is rejected with `ERR_STALE_POLE_VERSION`, and a successful patch increments the pole's `version` by one.

An `InspectionCycle` organizes one program year. Creating one requires a `year` between 2000 and 2100 (the funding budget for the year is the `ProgramBudget` whose `fiscal_year` matches it), a `cycle_length_years` of at least one expressing the required years between inspections of the same pole, a `sample_pct` between 0 and 100 inclusive governing what percent of the eligible pool is sampled at open, an optional `mandatory_zone_tags` list (defaulting to empty) of `gis_tag` values that force eligibility regardless of last-inspection age, and a `strength_variant_policy` of `CONSERVATIVE` or `STATISTICAL` selecting which remaining-strength variant drives classification for every task in the cycle. A new cycle is `DRAFT`; its only forward moves are `DRAFT` to `OPEN` and `OPEN` to the terminal `RECONCILED`. System counters `sample_pool_size`, `tasks_total`, `tasks_terminal`, and `pending_replacement_count` track its progress, and `opened_at` and `reconciled_at` record the logical-clock instants of its two transitions.

### 3.2. Opening a Cycle: Eligibility, Sampling, and Due Windows

Opening a cycle is a `ProgramManager` action permitted only while the cycle is `DRAFT`. The open stamps `opened_at` from the logical clock and immediately runs population sampling across the entire pole register.

The eligible pool consists of poles whose `status` is `IN_SERVICE` or `MONITOR`, that additionally satisfy at least one of three recency conditions — the pole has never been inspected (`last_inspection_date` is null), or at least `cycle_length_years` years have elapsed between its `last_inspection_date` and now, or its `gis_tag` appears in the cycle's `mandatory_zone_tags` regardless of inspection age — and for which no `InspectionTask` currently exists in `OPEN`, `SUBMITTED`, or `REJECTED` status. The pool is ranked with never-inspected poles first, then by `last_inspection_date` ascending (oldest inspection first), with ties broken by the pole's `created_at` ascending. The sample size is the pool size multiplied by `sample_pct` and divided by 100, rounded down to a whole number, but never less than one when the pool is non-empty and `sample_pct` is above zero; when the pool is empty or `sample_pct` is zero, the sample size is zero. The top-ranked poles up to the sample size each receive one `OPEN` `InspectionTask` whose inclusive due window runs from `opened_at` through the instant 120 days later — a full field season. The open records `sample_pool_size` as the eligible pool size and `tasks_total` as the number of tasks created. Opening with an empty eligible pool succeeds cleanly: zero tasks are created and `sample_pool_size` is zero.

Beyond the automatic sample, a `ProgramManager` may create an inspection task manually — for engineering rechecks between cycles — by supplying `cycle_id`, `pole_id`, `due_window_start`, and `due_window_end`. Manual creation recomputes the cycle's `tasks_total` and enforces four guards: the target cycle must be `OPEN` (creating into a `DRAFT` or `RECONCILED` cycle is rejected with `ERR_CYCLE_NOT_OPEN`); the pole must not be `REPLACED` (`ERR_POLE_REPLACED`); no other non-terminal task may already exist for the same pole within the same cycle (`ERR_DUPLICATE_INSPECTION`); and the task's due window is a closed interval, so `due_window_end` before `due_window_start` is rejected with `ERR_INVALID_WINDOW`, and the window must not touch any other non-terminal task's window for the same pole — because both intervals are closed, even touching at a single shared day is a conflict, rejected with `ERR_TASK_WINDOW_OVERLAP`.

### 3.3. Field Inspection: Submission, Strength Measurement, and Classification

An `Inspector` works an `OPEN` task by submitting decay readings and photo evidence. Submission is permitted only while the task is `OPEN`, only while the owning cycle is still `OPEN` (else `ERR_CYCLE_NOT_OPEN`), and only while the pole has not been `REPLACED` (else `ERR_POLE_REPLACED`). The payload carries four field readings — `shell_thickness_in`, the sound shell thickness measured at the groundline in inches; `sound_wood_pct`, the percent of sound wood in the effective section from 0 to 100; `decay_pocket_depth_in`, the deepest internal decay pocket in inches; and `moisture_pct`, the measured wood moisture percent — plus a `photos` array of evidence objects each carrying a `photo_type`, a `url`, and a `taken_at` timestamp, where `photo_type` is one of `GROUNDLINE`, `DECAY_POCKET`, `TAG`, or `ATTACHMENT`. An optional `hazard_flag` (defaulting to false) lets the inspector declare an immediate hazard, and `found_attachment_count` is collected on joint-use poles for the audit linkage of §3.7.

Submission computes the pole's remaining strength twice, under two variants, and stores both on the task. Both variants begin from the shell ratio: `shell_thickness_in` divided by the required shell thickness for the pole's `original_class`, where the required thickness is 2.75 inches for class `H1`, 2.50 for class `1`, 2.25 for class `2`, 2.00 for class `3`, 1.75 for class `4`, and 1.50 for class `5`. The **CONSERVATIVE** variant multiplies the shell ratio by 100, then by the sound-wood fraction (`sound_wood_pct` divided by 100), then by a species factor — 1.00 for `SOUTHERN_PINE`, 0.95 for `DOUGLAS_FIR`, 0.90 for `WESTERN_RED_CEDAR`, and 1.02 for `LARCH`. From that base it subtracts a decay penalty of 5.0 points per inch of `decay_pocket_depth_in`, and finally applies a moisture derate: when `moisture_pct` exceeds 30.0 the result is multiplied by 0.95, otherwise by 1.00. The outcome is clamped between 0 and 100 and stored as `rs_conservative_pct`. The **STATISTICAL** variant is a weighted blend with no moisture term and a smaller decay penalty: six-tenths of the shell ratio expressed as a percentage, plus four-tenths of `sound_wood_pct`, minus 3.0 points per inch of `decay_pocket_depth_in`, likewise clamped between 0 and 100 and stored as `rs_statistical_pct`. Both percentages are rounded to two decimal places, half-up. The task's `effective_rs_pct` is then the single variant selected by the owning cycle's `strength_variant_policy`.

Classification follows immediately from `effective_rs_pct` against three inclusive lower bounds: at least 60.00 yields `SERVICEABLE`; at least 45.00 but below 60.00 yields `MONITOR`; at least 30.00 but below 45.00 yields `REJECT_ROUTINE`; below 30.00 yields `REJECT_PRIORITY`. The comparisons run against the two-decimal rounded value, so an effective strength of exactly 60.00 is `SERVICEABLE`, exactly 45.00 is `MONITOR`, and exactly 30.00 is `REJECT_ROUTINE`. The task's `classification` field records the outcome.

Two evidence gates guard the submission, ordered as in §2.8. First, when the computed classification is `REJECT_PRIORITY`, the payload's `hazard_flag` must be true — an inspector who has found a pole that far gone is required to declare the hazard — and a missing or false flag is rejected with `ERR_HAZARD_FLAG_REQUIRED`. Second, photo coverage is enforced against the computed classification: every submission must contain at least one `GROUNDLINE` photo and at least one `TAG` photo, and a classification of `REJECT_PRIORITY` or `REJECT_ROUTINE` additionally requires at least one `DECAY_POCKET` photo; insufficient coverage is rejected with `ERR_PHOTO_EVIDENCE_REQUIRED`.

A successful submission stamps `submitted_by_user_id` from the caller's `X-User-ID` — the value that later drives segregation of duties — and moves the task from `OPEN` to `SUBMITTED`. When the pole's `joint_use` flag is true, submission also auto-creates an `AttachmentAudit` linked back to the task, as detailed in §3.7.

### 3.4. Quality Review, Rework, and Pole Status Cascades

Every submitted task passes through a quality review by a `QAReviewer`, who supplies a `decision` and may attach optional `notes`. The review is valid only while the task is `SUBMITTED`; reviewing a task in any other state is rejected with `ERR_TASK_NOT_SUBMITTED`. Segregation of duties is strictly enforced: the reviewer's `X-User-ID` must differ from the task's `submitted_by_user_id`, and a self-review is rejected with `ERR_SOD_VIOLATION`. Either way the review stamps `qa_reviewed_by_user_id`.

An `ACCEPT` decision moves the task to the terminal `ACCEPTED` state and runs the pole's classification cascade. The pole's `current_classification` takes the task's classification, `current_remaining_strength_pct` takes the task's `effective_rs_pct`, `last_inspection_date` is set from the logical clock, and the pole's `version` increments. The pole's own status then moves according to the classification. A `MONITOR` classification moves an `IN_SERVICE` pole to `MONITOR`. A `SERVICEABLE` or `REJECT_ROUTINE` classification leaves the pole's status where it is — the cascade is permitted from either `IN_SERVICE` or `MONITOR` and only the condition fields update; a `REJECT_ROUTINE` pole simply re-enters a future cycle's sampling eligibility, with no automatic order created. A `REJECT_PRIORITY` classification, accepted against a pole in `IN_SERVICE` or `MONITOR`, moves the pole to `PRIORITY_REJECT` and fires the replacement cascade: the system auto-creates a `ReplacementWorkOrder` in `QUEUED` status, linked to the task's cycle through `cycle_id`, carrying the program default estimate of 250,000 cents in `estimated_cost_cents`, with its `priority_score` computed at creation per §3.8, and the owning cycle's `pending_replacement_count` increments as the final link of the cascade. Every `ACCEPT` — regardless of classification — recomputes the cycle's `tasks_terminal` counter.

A `REJECT` decision drives the rework loop. The task's `rework_count` records how many reject decisions it has absorbed, starting at zero. While `rework_count` is below two, a reject moves the task to `REJECTED`, increments `rework_count` by one, and clears the field readings, photos, and computed strength and classification fields back to their null defaults; the system then immediately returns the task from `REJECTED` to `OPEN`, so the inspector can redo the field work from a clean sheet. When a reject arrives with `rework_count` already at two — the third rejection — the task instead moves to the terminal `ESCALATED` state, `rework_count` rises to its final value of three, and the cycle's `tasks_terminal` is recomputed. Terminal task states are `ACCEPTED`, `WAIVED`, and `ESCALATED`.

Some poles cannot be reached — gated yards, flooded access roads. A `ProgramManager` may waive an `OPEN` task, supplying a `reason`, which moves it to the terminal `WAIVED` state and recomputes `tasks_terminal`. Waiver is a compensating action: because it does not touch the pole's `last_inspection_date`, the pole naturally re-enters the next cycle's eligible pool rather than silently dropping out of the inspection population.

### 3.5. Groundline Treatment and Contractor Quality Standing

Poles worth keeping are preserved with groundline treatment, executed by contractor crews. A `ProgramManager` registers a `ContractorCrew` with a unique non-empty `crew_code` (duplicates are rejected with `ERR_DUPLICATE_CREW_CODE`) and an operating `region`. A crew begins `ACTIVE` and carries lifetime counters `qa_pass_count` and `qa_fail_count`, both zero, an append-only `qa_event_log` whose entries record each QA decision with its `decided_at` instant and the `order_id` it concerned, two computed quality scores, and `current_cycle_billing_cents`, the production billing from the most recent cycle reconcile.

Creating a `TreatmentWorkOrder` requires a `pole_id`, a `product_code` of `CCA_WRAP`, `PENTA_GEL`, or `COPPER_NAPHTHENATE`, and a quoted `cost_cents` of zero or more; the pole must not be `REPLACED` (`ERR_POLE_REPLACED`). The order starts in `CREATED`, and its creation increments the pole's `open_treatment_count` — the running count of orders for the pole in `CREATED`, `SCHEDULED`, `APPLIED`, or `FAILED_QA`. The order's lifecycle is `CREATED` to `SCHEDULED` to `APPLIED` to the terminal `VERIFIED`, with a retreat loop from `APPLIED` into `FAILED_QA` and back to `SCHEDULED`.

Scheduling assigns a crew and a work window. Scheduling is valid from `CREATED` and equally from `FAILED_QA` — the retreat loop — and sets `crew_id`, `work_start_date`, and `work_end_date`. Three guards apply: the named crew must exist and be `ACTIVE`, since a `SUSPENDED` crew cannot take new work (`ERR_CREW_SUSPENDED`); the work window is half-open, so `work_end_date` must be strictly after `work_start_date`, else `ERR_INVALID_WINDOW`; and the half-open window must not overlap any other `SCHEDULED` order for the same crew, else `ERR_CREW_SCHEDULE_CONFLICT` — adjacency is not overlap, so one order's start may equal another's end. Rescheduling from `FAILED_QA` additionally resets `applied_at`, `applied_by_crew_id`, and the warranty fields to null, erasing the failed application.

Application is the crew's own act: a `Contractor` whose `X-User-ID` equals the order's `crew_id` marks a `SCHEDULED` order applied, and any other caller is rejected with `ERR_FORBIDDEN`. Applying stamps `applied_at` from the logical clock, records `applied_by_crew_id`, and opens the product's warranty window. `warranty_years` is drawn from the product — ten years for `CCA_WRAP`, eight for `PENTA_GEL`, five for `COPPER_NAPHTHENATE` — and `warranty_end_date` is `applied_at` advanced by that many years, keeping the same month and day, with the convention that a February 29 anniversary lands on February 28 in non-leap years. A claim is within warranty when its filing time falls on or before `warranty_end_date`; the boundary is inclusive. A warranty retreat order, when itself applied, starts an entirely new warranty window from its own `applied_at`.

Quality review closes the loop. A `QAReviewer` decides `PASS` or `FAIL` (again with optional `notes`) on an order in `APPLIED`. A `PASS` moves the order to the terminal `VERIFIED` and cascades in three directions at once: the crew's `qa_pass_count` increments by one and the decision is appended to `qa_event_log`; both quality scores are recomputed; and on the pole, `last_treatment_date` is set to the order's `applied_at`, a pole in `MONITOR` returns to `IN_SERVICE`, and `open_treatment_count` decrements by one. A `FAIL` moves the order to `FAILED_QA`, increments the crew's `qa_fail_count` and the order's own `qa_fail_events`, appends the event, and recomputes both scores — and then the suspension cascade runs: if the crew's rolling quality score has dropped below 70.00, the crew moves from `ACTIVE` to `SUSPENDED`, and every subsequent scheduling attempt for that crew fails with `ERR_CREW_SUSPENDED`. Suspension is not necessarily permanent: when a subsequent `PASS` decision on one of the crew's already-applied orders raises the rolling score back to at least 70.00, the system reinstates the crew from `SUSPENDED` to `ACTIVE`.

The two quality scores share one formula over different windows. Events are taken from `qa_event_log` ordered by `decided_at` ascending with ties broken by the event's `created_at` ascending. `quality_score_lifetime` is one hundred times the number of `PASS` events divided by the total number of events, computed over all events; `quality_score_rolling` applies the same ratio over only the five most recent events. Both are rounded to two decimal places, half-up, and both read exactly 100.00 when the crew has no events at all. The suspension cascade consults the rolling score only — a pass-heavy recent window can sit far above the lifetime figure — while the early-completion billing bonus of §3.9 consults the lifetime score only, requiring at least 90.00, because older failures never age out of it.

### 3.6. Warranty Claims and No-Cost Retreats

When decay recurs or a product fails inside its warranty window, a `ProgramManager` files a `WarrantyClaim` against the treatment order by supplying its `treatment_order_id` and a `claim_reason` of `DECAY_RECURRENCE` or `PRODUCT_FAILURE`. The target order must have reached `VERIFIED`; a claim against an order in any other status is rejected as an invalid-state error (`ERR_INVALID_STATE`). Two further guards apply: only one open claim may exist per treatment order, so filing while another claim for the same order is still `FILED` is rejected with `ERR_CLAIM_ALREADY_OPEN`; and the claim's filing must fall within the warranty window — `filed_at` on or before the order's `warranty_end_date`, inclusively — otherwise the filing is rejected with `ERR_WARRANTY_EXPIRED`. A filed claim is `FILED`, stamped with `filed_at` from the logical clock and `filed_by_user_id` from the caller. All claims against an order can be listed through the order's claim collection, which may hold zero or more claims over the order's life.

Adjudication is a `ProgramManager` decision on a `FILED` claim, carrying an `outcome` and an optional free-text `adjudication_note`. An outcome of `HONOR` moves the claim to the terminal `HONORED` state and auto-creates a retreat `TreatmentWorkOrder`: the new order carries `is_warranty_retreat` set to true, a `cost_cents` of zero, a `source_claim_id` pointing back to the claim, and the same `pole_id` and `product_code` as the original order. Like any order creation, the retreat increments the pole's `open_treatment_count`, and it flows through the ordinary scheduling, application, and quality-review lifecycle of §3.5. An outcome of `DENY` moves the claim to the terminal `DENIED` state and stamps the `adjudication_note`.

### 3.7. Joint-Use Attachment Audits and Violation Enforcement

Joint-use poles carry third-party attachments, and the inspection visit doubles as the audit opportunity. Whenever an inspector submits a task for a pole whose `joint_use` flag is true, submission auto-creates an `AttachmentAudit`: the audit copies the `pole_id` from the task's pole, links back through `inspection_task_id`, and records the `found_attachment_count` supplied in the submit payload — the number of attachments the inspector observed in the field, never negative. The audit's computed `unauthorized_count` is the found count minus the pole's `attachment_count_declared`, floored at zero.

The audit carries two parallel state dimensions on a single row. The review dimension, `audit_status`, begins at `SUBMITTED` and has one terminal move to `ADJUDICATED`. The violation dimension, `violation_status`, begins at `NONE` and evolves independently through `DETECTED`, `NOTIFIED`, and then either `CURED` or `ESCALATED`.

Adjudication by a `ProgramManager` requires the audit to still be `SUBMITTED`. It stamps `adjudicated_at` from the logical clock, moves `audit_status` to `ADJUDICATED`, and drives the violation dimension in the same act: when `unauthorized_count` is greater than zero, `violation_status` advances from `NONE` to `DETECTED` and immediately on to `NOTIFIED` — the notice is issued as part of the adjudication — and the `cure_deadline` is set to `adjudicated_at` plus 45 days. When `unauthorized_count` is zero, the violation dimension simply stays at `NONE` and no deadline is set.

Once notified, the attacher has until the deadline. An `AttacherRep` marks the violation cured, which requires `violation_status` to be `NOTIFIED` and the current logical time to be on or before `cure_deadline`; a late attempt is rejected with `ERR_CURE_DEADLINE_PASSED`. Marking cured stamps `cured_at` and moves the violation dimension to `CURED`; it does not alter `audit_status`, which remains `ADJUDICATED`. If the deadline passes with the violation still `NOTIFIED`, the violation does not drift on its own — it is escalated by the cycle reconcile of §3.9, which moves every overdue `NOTIFIED` violation to `ESCALATED`.

### 3.8. The Replacement Queue: Priority, Funding, Deferral, and Completion

Replacement work orders accumulate in a program-wide queue. Beyond the automatic creation of the §3.4 cascade, a `ProgramManager` may queue an order manually by supplying a `pole_id` and an `estimated_cost_cents` greater than zero; manual orders carry a null `cycle_id`, and the pole must not be `REPLACED` (`ERR_POLE_REPLACED`). Every order begins `QUEUED`, with `deferral_count` at zero and `funded_at` unset.

Two computed fields drive the queue. `escalated_cost_cents` — the amount funding actually commits — is the `estimated_cost_cents` multiplied by 1.08 raised to the power of `deferral_count`, rounded half-up to whole cents; it is computed at creation and recomputed on every defer. `priority_score` is an integer computed at creation and again whenever a deferred order re-enters the queue at reconcile. Its composition is fixed and evaluated in a pinned order: start with a deficiency of 100 minus the pole's `current_remaining_strength_pct`, where a null strength counts as 50.00; add a deferral term of 5 points per deferral; add 10 points when the pole's `joint_use` flag is true; add 5 points when the pole's installation year is 1969 or earlier. That raw sum is then subject to the criticality floor — when the pole's `gis_tag` is `FEEDER_CRITICAL`, the sum is raised to at least 80 — and finally the score is capped at 100. Sum first, then floor, then cap.

Funding commits budget to a `QUEUED` order and is the second OCC-guarded write of §2.7. The request names the `budget_id` and must carry `expected_budget_version`; an order not currently `QUEUED` is rejected with `ERR_ORDER_NOT_QUEUED`, a stale budget version is rejected with `ERR_STALE_BUDGET_VERSION`, and the budget's `available_cents` must be at least the order's `escalated_cost_cents` — the boundary is inclusive, so an order whose escalated cost exactly equals the available balance funds successfully, while a larger cost is rejected with `ERR_BUDGET_EXCEEDED`. A successful fund moves the order to `FUNDED`, adds the escalated cost to the budget's `committed_cents`, sets the order's `budget_id` to the funding budget, stamps `funded_at` from the logical clock, and increments the `version` of both the budget and the order.

Defunding is the compensating action: a `FUNDED` order returns to `QUEUED`, the budget's `committed_cents` is reduced by the escalated cost, the order's `budget_id` is cleared to null, and the budget's `version` increments — restoring `available_cents` to exactly its pre-fund value. Deferring a `QUEUED` order moves it to `DEFERRED`, increments `deferral_count` by one, and recomputes `escalated_cost_cents` at the new deferral power; deferred orders wait out the cycle and are automatically requeued at the next reconcile.

Completion belongs to the `Contractor`. Completing a `FUNDED` order requires a payload `actual_cost_cents` greater than zero and settles the money: the budget's `committed_cents` is reduced by the order's `escalated_cost_cents` and its `spent_cents` is increased by the `actual_cost_cents`. The same act retires the asset: the order moves to the terminal `COMPLETED`, and the pole referenced by the order's `pole_id` — which must be the pole under replacement, and whose order was `FUNDED` — transitions from `PRIORITY_REJECT` to the terminal `REPLACED`. The `version` of both the budget and the pole increments. From that point on, the pole is closed to new field work: task submission, manual task creation, treatment-order creation, and replacement-order creation targeting a `REPLACED` pole are all rejected with `ERR_POLE_REPLACED`.

### 3.9. Cycle Reconciliation: Waterfall Funding, Production Billing, and the Backlog Snapshot

Reconciling a cycle is the program's checkpoint ceremony, performed by a `ProgramManager` while the cycle is `OPEN`, with a payload naming the `budget_id` to fund from. Reconcile is refused while any of the cycle's tasks remain non-terminal — `tasks_terminal` must equal `tasks_total`, otherwise the request is rejected with `ERR_CYCLE_TASKS_OPEN` — and the named budget must resolve. The reconcile then executes five steps in a fixed order.

Step one requeues deferrals: every `ReplacementWorkOrder` in `DEFERRED` returns to `QUEUED` with its `deferral_count` retained, and its `priority_score` is recomputed at the current deferral count. Step two escalates overdue violations: every `AttachmentAudit` whose `violation_status` is `NOTIFIED` and whose `cure_deadline` has passed relative to the current logical time moves to `ESCALATED`. Step three runs the funding waterfall against the payload budget, over the entire program-wide backlog — every order in `QUEUED` status from any cycle. The waterfall's evaluation order is pinned to break the mutual dependency between available funds and the funded set: first, snapshot the budget's `available_cents` as it stands at reconcile start, after the step-one requeue and before any funding; then rank all candidates by `priority_score` descending, breaking ties by `created_at` ascending; then walk the ranking, funding each order whose `escalated_cost_cents` is less than or equal to the remaining snapshot — funding moves the order to `FUNDED`, adds the cost to `committed_cents`, subtracts it from the remaining amount, and sets the order's `budget_id` — while an order whose cost exceeds the remainder is left `QUEUED` and the walk continues to lower-ranked orders rather than stopping. As with manual funding, the boundary is inclusive: an order whose escalated cost exactly equals the remaining funds is funded.

Step four computes production billing for each crew with in-scope work. A crew's in-scope orders are its `VERIFIED` treatment orders whose `applied_at` falls at or after the cycle's `opened_at` and before the reconcile instant; a crew with no in-scope orders is skipped and its billing is left unchanged. Each in-scope order contributes a line amount built from two separately rounded components: the product's base rate — 17,500 cents for `CCA_WRAP`, 21,000 for `PENTA_GEL`, 14,500 for `COPPER_NAPHTHENATE` — multiplied by the treated pole's species multiplier — 1.00 for `SOUTHERN_PINE`, 1.15 for `DOUGLAS_FIR`, 0.90 for `WESTERN_RED_CEDAR`, 1.05 for `LARCH` — rounded half-up to whole cents; plus the order's even share of the 40,000-cent mobilization allowance, that is 40,000 divided by the crew's in-scope order count, rounded half-up to whole cents. The rounding order is pinned and contractual: each line component is rounded per order first, and only then are the lines summed into the crew's subtotal — summing first and rounding once yields a different cents total and is non-conformant. The bonus question is asked next: when every in-scope order reached `VERIFIED` no later than 120 days after the cycle opened, and the crew's lifetime quality score is at least 90.00, an early-completion bonus of five percent of the subtotal, rounded half-up to whole cents, is added; otherwise the bonus is zero. A penalty of 2,500 cents per QA-fail event — the sum of `qa_fail_events` over the in-scope orders — is then subtracted, and the result, floored at zero, is the crew's `billing_cents`, stored on `current_cycle_billing_cents`.

Step five writes the permanent record: a `BacklogSnapshot` whose `snapshot_seq` is a per-cycle monotonically increasing sequence starting at one, recording the reconciled `cycle_id`, the `budget_id` used for the waterfall, the `queued_count` of orders still `QUEUED` after the waterfall, their combined `queued_escalated_cost_cents`, the `funded_count` of orders this reconcile moved from `QUEUED` to `FUNDED`, the budget's post-waterfall `budget_available_cents` and `budget_committed_cents`, and the `crew_billings` array of per-crew objects pairing each `crew_id` with its `billing_cents`. Finally the reconcile stamps `reconciled_at`, moves the cycle to the terminal `RECONCILED`, and increments the `version` of the cycle, the budget, and every order, audit, and crew it mutated along the way.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state transitions, submissions, reviews, and the clock set — return a `200 OK` status code, as do all read endpoints.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pole-program/budgets` | Create a fiscal-year budget (fiscal year unique) | ProgramManager |
| GET | `/pole-program/budgets/{id}` | Read a budget with computed committed/spent/available | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| POST | `/pole-program/inspection-cycles` | Create a cycle in `DRAFT` | ProgramManager |
| GET | `/pole-program/inspection-cycles/{id}` | Read a cycle with computed task counters | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| POST | `/pole-program/inspection-cycles/{id}/open` | Open the cycle and run population sampling; empty pool opens cleanly | ProgramManager |
| POST | `/pole-program/inspection-cycles/{id}/reconcile` | Checkpoint: requeue deferrals, escalate overdue violations, run funding waterfall and crew billing, write a `BacklogSnapshot`, close the cycle `RECONCILED` | ProgramManager |
| POST | `/pole-program/poles` | Register a pole | ProgramManager |
| GET | `/pole-program/poles/{id}` | Read a pole with computed classification fields | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| PATCH | `/pole-program/poles/{id}/gis-attributes` | Supersede GIS attributes (OCC on the pole's `version`) | ProgramManager |
| POST | `/pole-program/inspection-tasks` | Manually create an inspection task; closed-window overlap and duplicate rules apply | ProgramManager |
| GET | `/pole-program/inspection-tasks` | List tasks with filters | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| GET | `/pole-program/inspection-tasks/{id}` | Read a task with computed strength fields | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| POST | `/pole-program/inspection-tasks/{id}/submit` | Submit decay readings and photo evidence; computes both strength variants and classification; auto-creates an `AttachmentAudit` for joint-use poles | Inspector |
| POST | `/pole-program/inspection-tasks/{id}/qa-review` | QA decision on a submitted task under segregation of duties; `ACCEPT` cascades to the pole, `REJECT` loops rework or escalates at the third rejection | QAReviewer |
| POST | `/pole-program/inspection-tasks/{id}/waive` | Waive an inaccessible pole's task, returning the pole to the eligibility pool | ProgramManager |
| POST | `/pole-program/treatment-work-orders` | Create a groundline treatment order in `CREATED` | ProgramManager |
| GET | `/pole-program/treatment-work-orders` | List treatment orders with filters | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| GET | `/pole-program/treatment-work-orders/{id}` | Read a treatment order with warranty fields | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| POST | `/pole-program/treatment-work-orders/{id}/schedule` | Assign crew and half-open work window; crew-overlap and crew-status checks | ProgramManager |
| POST | `/pole-program/treatment-work-orders/{id}/apply` | Crew marks application complete; sets the warranty window from the logical clock | Contractor |
| POST | `/pole-program/treatment-work-orders/{id}/qa-review` | `PASS` verifies with crew-pass and pole cascades; `FAIL` triggers the crew-fail cascade and possible suspension | QAReviewer |
| POST | `/pole-program/warranty-claims` | File a warranty claim against a `VERIFIED` treatment order within its warranty window | ProgramManager |
| GET | `/pole-program/treatment-work-orders/{id}/warranty-claims` | List claims for a treatment order | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| POST | `/pole-program/warranty-claims/{id}/adjudicate` | `HONOR` creates a no-cost retreat order; `DENY` closes the claim | ProgramManager |
| POST | `/pole-program/contractor-crews` | Register a contractor crew | ProgramManager |
| GET | `/pole-program/contractor-crews/{id}` | Read a crew with both quality-score variants and current billing | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| POST | `/pole-program/replacement-work-orders` | Manually queue a replacement order (`cycle_id` null) | ProgramManager |
| GET | `/pole-program/replacement-work-orders` | List replacement orders with filters | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| GET | `/pole-program/replacement-work-orders/{id}` | Read a replacement order | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| POST | `/pole-program/replacement-work-orders/{id}/fund` | Commit budget to a `QUEUED` order (OCC on the budget's `version`; equality of cost and available funds funds) | ProgramManager |
| POST | `/pole-program/replacement-work-orders/{id}/defund` | Release committed funds, returning `available_cents` to its pre-fund value | ProgramManager |
| POST | `/pole-program/replacement-work-orders/{id}/defer` | Defer a `QUEUED` order; `deferral_count` increments and escalated cost recomputes | ProgramManager |
| POST | `/pole-program/replacement-work-orders/{id}/complete` | Complete a `FUNDED` order: committed converts to spent at actual cost; pole moves to `REPLACED` | Contractor |
| GET | `/pole-program/attachment-audits` | List attachment audits with filters | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| GET | `/pole-program/attachment-audits/{id}` | Read an audit (both parallel state dimensions) | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| POST | `/pole-program/attachment-audits/{id}/adjudicate` | Adjudicate: `audit_status` moves to `ADJUDICATED`; violations move `NONE` to `DETECTED` to `NOTIFIED` when unauthorized attachments exist | ProgramManager |
| POST | `/pole-program/attachment-audits/{id}/mark-cured` | Attacher marks the violation cured before the cure deadline (violation dimension only) | AttacherRep |
| GET | `/pole-program/backlog-snapshots` | List reconcile snapshots with filters | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| GET | `/pole-program/backlog-snapshots/{id}` | Read one snapshot | ProgramManager, Inspector, QAReviewer, Contractor, AttacherRep |
| POST | `/pole-program/_clock/set_current_utc` | Test-driving endpoint: set the logical clock | ProgramManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_POLE_NOT_FOUND` | 404 |
| `ERR_CYCLE_NOT_FOUND` | 404 |
| `ERR_TASK_NOT_FOUND` | 404 |
| `ERR_TREATMENT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_BUDGET_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_CYCLE_TASKS_OPEN` | 409 |
| `ERR_TASK_NOT_SUBMITTED` | 409 |
| `ERR_POLE_REPLACED` | 409 |
| `ERR_ORDER_NOT_QUEUED` | 409 |
| `ERR_CREW_SUSPENDED` | 409 |
| `ERR_STALE_BUDGET_VERSION` | 412 |
| `ERR_STALE_POLE_VERSION` | 412 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_HAZARD_FLAG_REQUIRED` | 422 |
| `ERR_PHOTO_EVIDENCE_REQUIRED` | 422 |
| `ERR_CLAIM_ALREADY_OPEN` | 409 |
| `ERR_DUPLICATE_FISCAL_YEAR` | 409 |
| `ERR_DUPLICATE_POLE_NUMBER` | 409 |
| `ERR_DUPLICATE_CREW_CODE` | 409 |
| `ERR_DUPLICATE_INSPECTION` | 409 |
| `ERR_CREW_SCHEDULE_CONFLICT` | 409 |
| `ERR_TASK_WINDOW_OVERLAP` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_CURE_DEADLINE_PASSED` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
