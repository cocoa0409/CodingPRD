# Semiconductor Fab Yield API — Product Requirements Document

## 1. Introduction

A modern wafer fab runs a product through several hundred sequenced operations, each one executed on a qualified chamber of a qualified tool by a gowned and certified operator, against a recipe that is under formal engineering change control. The economics are unforgiving: a single unnoticed process drift can silently damage weeks of work-in-progress, and a single unnecessary tool-down can cost a week of authorised wafer starts. The teams who run the line — process engineering, quality, equipment engineering, planning, yield engineering and the cleanroom floor — currently reconcile all of this across disconnected spreadsheets, MES exports and email approvals, which means nobody can answer "which lots were exposed to this excursion?" quickly enough for the answer to matter.

This document specifies the Semiconductor Fab Yield API, a single system of record for process flow definition, recipe change control, wafer start planning, equipment and chamber availability, in-line metrology with statistical process control, excursion response, engineering experiments, cleanroom contamination control, and final test, sort and speed-grade binning. The API is mounted under the `/fab` prefix. Its guiding design commitment is that every consequential act — releasing a flow, approving a change notice, containing an excursion, dispositioning affected material — leaves a durable, attributable record, and that the automatic consequences of that act (holds, aborts, disqualifications, tool-downs, capacity credits) are applied by the server rather than left to human follow-up.

Two cross-cutting properties shape almost every rule that follows. First, the fab is a **capacity-conserving** system: hours reserved on a tool and wafers authorised by a plan must balance exactly, with no drift, across reservations, completions, aborts and maintenance resets. Second, quality control is **segregated**: the engineer who authors a recipe change may not approve it, and the engineer who contains an excursion may not decide the fate of the material it caught. Both properties are enforced by the server, not by convention.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across every endpoint. Where §3 describes what a workflow means, this section describes the mechanics that workflow inherits.

### 2.1. Fab Personnel and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting person, and `X-User-Role`, declaring the capacity in which they act. Six roles exist, spelled exactly as follows: `ProcessEngineer`, `QualityManager`, `EquipmentEngineer`, `FabPlanner`, `YieldEngineer`, and `Operator`. A request missing either header, or carrying an `X-User-Role` value that is not one of those six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but is not listed among the authorised roles for the endpoint being called is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

`ProcessEngineer` owns process flow definition, recipes, engineering change notices, engineering split lots and rework. `QualityManager` owns change-notice review and approval, excursion containment, operator registration and certification standing, and cleanroom protocol enforcement. `EquipmentEngineer` owns tools, chambers, preventive maintenance and chamber qualification. `FabPlanner` owns wafer start planning, capacity commitment, lot creation and lot release. `YieldEngineer` owns test, die sort, wafer-map yield analysis and speed-grade binning, and may disposition excursions contained by someone else. `Operator` is the cleanroom operator who tracks lots in and out and records metrology.

Identity semantics differ between the roles. When `X-User-Role` is `ProcessEngineer`, `QualityManager`, `EquipmentEngineer`, `FabPlanner`, or `YieldEngineer`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a workflow calls for attribution — as `author_user_id` and `approver_user_id` on a change notice, and as `contained_by_user_id` and `dispositioned_by_user_id` on an excursion — but never compares it to any entity's `id`. When `X-User-Role` is `Operator`, by contrast, `X-User-ID` is the `id` of the acting `Operator` row; ownership checks compare the resource's operator foreign key to `X-User-ID`. Concretely, an `Operator` may only open a step run whose `operator_id` equals their own `X-User-ID`, may only track out, abort or record measurements against a run whose `operator_id` equals their `X-User-ID`, and may only patch the `Operator` row whose `id` equals their `X-User-ID`. A violation of any of these is rejected with `ERR_OPERATOR_IDENTITY_MISMATCH` (HTTP 403).

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

List endpoints are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, has a minimum of 1 and a maximum of 100. `offset` is the number of rows to skip; it defaults to 0 and its minimum is 0. A `limit` outside the range 1 through 100, or a negative `offset`, is a request-shape failure and is rejected with `ERR_VALIDATION` (HTTP 400).

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending. Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system carry a common set of server-managed properties: an `id` that is a server-minted UUID with no type prefix; a `created_at` timestamp in ISO 8601 UTC with three fractional digits; an `updated_at` timestamp in the same format, refreshed on every mutation; and a `version`, an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation of that row, including mutations of purely derived fields. `ProcessFlow`, `ProcessStep`, `Recipe`, `RecipeChangeRequest`, `Equipment`, `Chamber`, `Operator`, `WaferStartPlan`, `Lot`, `StepRun`, `SpcChart`, `Excursion` and `DieSortRun` all carry all four.

`MetrologyMeasurement` is the exception. A metrology reading is an immutable observation, so a measurement row carries only `id` and `created_at`; it has **no** `updated_at` and **no** `version`, and no endpoint modifies one after it is recorded.

Time in this system is a logical clock, never wall-clock time. Before the clock is ever set, it reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. An administrative test-driving capability, available to all six roles at `POST /_clock/set_current_utc`, accepts a `to_iso8601` instant and returns the new `current_utc`; every subsequent read of "now" — for `released_at`, `qualified_at`, `qual_expires_at`, `pm_started_at`, `purge_until`, `gowned_at`, `tracked_in_at`, `tracked_out_at`, `completed_at`, and every elapsed-time computation — returns that instant.

### 2.5. Numeric Precision and Rounding Discipline

All rounding in this system is **round half up**. The number of decimal places is fixed per quantity, and intermediate ratios are carried at full floating-point precision so that only the values named below are rounded.

Hours-denominated and score-denominated quantities are stored to **2 decimal places**: `standard_hours`, `total_standard_hours`, `target_value`, `proposed_target`, `hours_since_pm`, `available_capacity_hours`, `reserved_hours`, `actual_hours`, `dispatch_score`, `particle_count`, `measured_value`, `target`, `sigma`, `risk_score`, `severity_score`, `committed_hours`, `surcharge_hours` and `base_hours`. Day-denominated cycle-time quantities are stored to **3 decimal places**: `cycle_time_target_days`, `actual_cycle_time_days`, and every intermediate of the cycle-time projection. Ratio-denominated quantities are stored to **4 decimal places**: `deviation_sigma`, `baseline_yield`, `sort_yield`, `yield_loss_ratio`, `trigger_value`, the per-wafer yield of an individual wafer, the per-signature share of total fails, and the pre-surcharge utilisation of a wafer start plan. Die counts and wafer counts are integers and are never rounded. In the SPC engine, all comparisons against specification and control limits are made exactly on the stored two-decimal values.

### 2.6. Optimistic Concurrency on Plans, Recipes and Parent Lots

Three write operations mutate a parent row that a client must have observed before acting, and each therefore requires an optimistic-concurrency field in its request body. The field is mandatory, not optional.

Releasing a lot requires `expected_plan_version`, carrying the client's last observed `version` of the `WaferStartPlan` named by the lot's `plan_id`. If that value does not equal the plan's current `version`, the release is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412). A release legitimately debits the plan's remaining authorised wafer starts, so a release carrying a stale plan version would consume authorisation the client never saw allocated.

Approving an engineering change notice requires `expected_recipe_version`, carrying the client's last observed `version` of the `Recipe` named by the notice's `recipe_id`. A mismatch with the recipe's current `version` is rejected with `ERR_STALE_RECIPE_VERSION` (HTTP 412). Approval pins `pinned_recipe_revision` from the recipe as it stands at that moment, so an approval built on a stale read would pin a revision the approver never reviewed.

Creating an engineering split requires `expected_lot_version`, carrying the client's last observed `version` of the parent `Lot`. A mismatch with the parent lot's current `version` is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). Each split legitimately reduces the parent's `wafer_count`, so a split carved from a stale view of the parent would over-commit wafers that an earlier split already removed.

No other endpoint takes a version field, and no other endpoint performs a version check.

### 2.7. Request Validation Order

When several checks could reject the same request, the server evaluates them in a fixed order and returns the error of the **first** failing check. Ordering matters because a lower-priority failure must never mask a higher-priority one. The order is:

1. Header presence and role recognition — `ERR_UNAUTHENTICATED`.
2. Role authorisation for the target endpoint — `ERR_UNAUTHORIZED`.
3. Request shape: required fields present, correct types, enum members inside their constraint set, numeric ranges satisfied (including the per-element shape of `wafer_results` and the per-element membership of `certified_tool_types`), and pagination within bounds — `ERR_VALIDATION`.
4. Path identifier resolution, left to right (see §2.8) — the matching not-found code.
5. Foreign-key resolution for identifiers supplied in the request body — `flow_id`, `recipe_id`, `rework_target_step_id`, `equipment_id`, `qualified_recipe_id`, `step_id`, `lot_id`, `operator_id`, `spc_chart_id`, `step_run_id` and `supersedes_flow_id` — again the matching not-found code.
6. Operator self-identity, for opening a run, tracking out, aborting, recording a measurement, and patching an operator row — `ERR_OPERATOR_IDENTITY_MISMATCH`.
7. Segregation of duties on change-notice approval — `ERR_SOD_SELF_APPROVAL`.
8. Segregation of duties on excursion disposition — `ERR_SOD_SELF_DISPOSITION`.
9. `expected_plan_version` agreement at lot release — `ERR_STALE_PLAN_VERSION`.
10. `expected_recipe_version` agreement at approval — `ERR_STALE_RECIPE_VERSION`.
11. `expected_lot_version` agreement at split — `ERR_STALE_LOT_VERSION`.
12. Flow is `DRAFT`, for step insertion and release — `ERR_FLOW_NOT_DRAFT`.
13. Flow is `RELEASED`, for the flow a plan is written against and for the flow named by `supersedes_flow_id` — `ERR_FLOW_NOT_RELEASED`.
14. Plan is `DRAFT`, for commit — `ERR_PLAN_ALREADY_COMMITTED`.
15. Plan is `COMMITTED`, for lot release — `ERR_PLAN_NOT_COMMITTED`.
16. Lot `flow_state` is admissible for the operation — `ERR_LOT_INVALID_STATE`.
17. Lot `hold_state` is `NONE` — `ERR_LOT_ON_HOLD`.
18. Change-notice `status` is admissible for the requested transition — `ERR_CHANGE_REQUEST_INVALID_STATE`.
19. Excursion `status` is admissible, and containment additionally requires a non-particle source — `ERR_EXCURSION_INVALID_STATE`.
20. Step run `status` is `OPEN` — `ERR_STEP_RUN_NOT_OPEN`.
21. Die sort run `status` is `SORTED` — `ERR_SORT_RUN_ALREADY_BINNED`.
22. Tool `state` is `PM`, for maintenance completion — `ERR_EQUIPMENT_NOT_IN_PM`.
23. Tool `state` is neither `DOWN` nor `PM`, for a qualification run on one of its chambers — `ERR_EQUIPMENT_DOWN`.
24. Chart `status` is `MONITORING` — `ERR_SPC_CHART_SUSPENDED`.
25. Recipe `status` is `QUALIFIED` — `ERR_RECIPE_RESTRICTED`.
26. Recipe `revision` still equals the notice's `pinned_recipe_revision` — `ERR_PINNED_REVISION_STALE`.
27. Acting operator's `cert_status` is `ACTIVE` — `ERR_OPERATOR_CERT_INACTIVE`.
28. Acting operator's `gown_state` is `GOWNED` — `ERR_OPERATOR_NOT_GOWNED`.
29. Acting operator is certified for the step's tool class — `ERR_OPERATOR_NOT_CERTIFIED`.
30. The requested step belongs to the lot's flow — `ERR_STEP_FLOW_MISMATCH`.
31. The requested step is the lot's next admissible step — `ERR_STEP_SEQUENCE_VIOLATION`.
32. The chart's step matches the run's step — `ERR_CHART_STEP_MISMATCH`.
33. The step actually requires metrology — `ERR_METROLOGY_NOT_REQUIRED`.
34. Product-family and flow agreement between plan, flow and lot — `ERR_PRODUCT_FAMILY_MISMATCH`.
35. A rework target is configured at the lot's current step — `ERR_REWORK_TARGET_NOT_SET`.
36. The lot really is an engineering split with a parent — `ERR_NOT_A_SPLIT_LOT`.
37. The tool is outside its post-maintenance purge interval — `ERR_PM_PURGE_ACTIVE`.
38. At least one candidate chamber's qualification has not lapsed — `ERR_CHAMBER_QUAL_EXPIRED`.
39. The chamber eligibility filter yields at least one candidate — `ERR_NO_QUALIFIED_CHAMBER`.
40. Business-key uniqueness — `ERR_DUPLICATE_CODE`.
41. Split quantity is in range — `ERR_INVALID_SPLIT_QUANTITY`.
42. Rework budget not yet exhausted — `ERR_REWORK_LIMIT_EXCEEDED`.
43. Per-wafer sort results are internally consistent — `ERR_WAFER_RESULT_INCONSISTENT`.
44. A measurement exists on a metrology-required step before track-out — `ERR_METROLOGY_MISSING`.
45. The flow has at least one step and every step's recipe is qualified — `ERR_FLOW_HAS_NO_STEPS`.
46. Plan wafer-start authorisation not exceeded — `ERR_PLAN_STARTS_EXCEEDED`.
47. Plan capacity budget not exceeded — `ERR_CAPACITY_BUDGET_EXCEEDED`.
48. Winning tool has capacity for the step — `ERR_EQUIPMENT_CAPACITY_EXHAUSTED`.
49. Chamber `qual_state` admits a qualification run — `ERR_CHAMBER_INVALID_QUAL_STATE`.
50. Tool `state` admits a maintenance start — `ERR_EQUIPMENT_INVALID_STATE`.

### 2.8. Nested Resource Retrieval

When a path carries an identifier, the server resolves it before it evaluates any business rule. Where a path carries more than one identifier, resolution proceeds strictly left to right, and the request is rejected on the *first* identifier that names no existing row. Each entity has its own not-found code: `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`, `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`, `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404. The same catalogue serves foreign keys supplied in a request body: an unresolvable `plan_id` yields `ERR_PLAN_NOT_FOUND`, an unresolvable `qualified_recipe_id` yields `ERR_RECIPE_NOT_FOUND`, and so on.

### 2.9. Cascading State Propagation

A single act on the line frequently has consequences on other rows, and the server applies all of them synchronously within the same request. Every row touched by a cascade has its `updated_at` refreshed and its `version` incremented by 1, exactly as if it had been mutated directly — a lot pushed onto hold by an excursion, a chamber disqualified by containment, a tool driven down, and a plan whose released wafer starts advanced are all mutations for versioning purposes.

Cascades chain. Containing an excursion at tool scope drives the tool from `PRODUCTIVE` to `DOWN`, which aborts every open run on that tool's chambers, which credits each run's reservation back to the tool's capacity ledger. Implementing a high-risk recipe change returns the recipe to `QUALIFIED`, which unqualifies every chamber set up on that recipe, which places the in-process lots sitting in those chambers onto qualification hold. The full chains are described in §3.

Hold escalation is one-directional. The precedence order on a lot's `hold_state` is `ENGINEERING_HOLD` above `QUAL_HOLD`, `QUAL_HOLD` above `SPC_HOLD`, and `SPC_HOLD` above `NONE`. A cascade may only raise a lot's hold along that order, never lower it: a lot already on `SPC_HOLD` moves to `QUAL_HOLD` when its chamber leaves `QUALIFIED`, but a lot on `QUAL_HOLD` is never demoted to `SPC_HOLD`. Only an explicit disposition, a rework rewind, a rejoin, a maintenance completion that clears the implicated tool, or a scrap can return a lot to `NONE`.

### 2.10. Segregation of Duties

Two decisions in this system require two different people, and the server enforces the separation by comparing `X-User-ID` against the identifier recorded when the first half of the decision was made.

A change notice records the `ProcessEngineer` who authored it in `author_user_id`. An approval whose `X-User-ID` equals that value is rejected with `ERR_SOD_SELF_APPROVAL` (HTTP 409), even though the caller holds the `QualityManager` role. Symmetrically, an excursion records the engineer who contained it in `contained_by_user_id`, and a disposition whose `X-User-ID` equals that value is rejected with `ERR_SOD_SELF_DISPOSITION` (HTTP 409). Because a particle-sourced excursion is contained automatically with no human in the loop, its `contained_by_user_id` stays null, and any authorised engineer may disposition it.

Resubmission runs the other way: only the original author may re-author a notice sent back for revision, so a resubmit is accepted only when `X-User-ID` equals `author_user_id`.

### 2.11. Cleanroom Contamination Control and Gowning Protocol

The cleanroom protocol has two independent dimensions on an operator, and both are enforced before any floor action. Certification standing lives in `cert_status`, with values `ACTIVE`, `SUSPENDED` and `REVOKED`; gowning posture lives in `gown_state`, with values `STREET` and `GOWNED`. Opening a run, tracking out and recording a measurement all require `cert_status` of `ACTIVE` — otherwise `ERR_OPERATOR_CERT_INACTIVE` (HTTP 403) — and all require `gown_state` of `GOWNED` — otherwise `ERR_OPERATOR_NOT_GOWNED` (HTTP 403). A request that changes an operator's `gown_state` also requires the operator's `cert_status` to be `ACTIVE`, and is likewise rejected with `ERR_OPERATOR_CERT_INACTIVE` when it is not.

Particle discipline is chamber-scoped. Every chamber declares a `particle_limit` and carries the most recent reading in `particle_count`. A chamber whose `particle_count` exceeds its `particle_limit` is excluded from dispatch outright and cannot pass a qualification run, and a reading strictly above the limit escalates into an automatic excursion as described in §3.7.

### 2.12. The Tool Capacity Ledger and Wafer Inventory Conservation

Each tool carries `available_capacity_hours`, a ledger of hours remaining in its current maintenance cycle. It is seeded at 720.00 hours when the tool is commissioned and reset to exactly 720.00 hours whenever maintenance completes. Four events move it, and each individual movement is rounded to 2 decimal places: opening a run subtracts the step's `standard_hours` (recorded on the run as `reserved_hours`); tracking a run out adds `reserved_hours` back and then subtracts the run's `actual_hours`, while adding `actual_hours` to the tool's `hours_since_pm`; aborting a run adds `reserved_hours` back in full and leaves `hours_since_pm` untouched; completing maintenance resets `available_capacity_hours` to 720.00 and `hours_since_pm` to 0.00.

The ledger is a conserved quantity, checked after every mutation: `available_capacity_hours` equals 720.00, minus the sum of `actual_hours` over the tool's `COMPLETED` runs opened since the most recent maintenance completion (all of them when the tool has never been maintained), minus the sum of `reserved_hours` over the tool's currently `OPEN` runs. `ABORTED` runs contribute zero to both sums, which is why a track-in followed by an abort returns `available_capacity_hours` to exactly its pre-track-in value with no drift.

Wafers obey their own conservation law. A lot records the wafers it started with in `origin_wafer_count`, which is never mutated, and its live population in `wafer_count`. After every split and every rejoin, the parent's `wafer_count` plus the sum of `wafer_count` over its non-scrapped children equals the parent's `origin_wafer_count`. Scrapped children leave the conserved pool permanently, which is exactly why the invariant excludes them.

## 3. Business Logic & Workflows

### 3.1. Defining and Releasing a Process Flow

Manufacturing begins with a **process flow** — the ordered list of operations that turns bare silicon into finished die. A `ProcessEngineer` drafts one by supplying a `flow_code`, which must be between 1 and 32 characters and globally unique across all flows, and a `product_family`, one of `LOGIC_N5`, `LOGIC_N7` or `MEMORY_D1`. A newly drafted flow opens in `DRAFT` `status`, with `step_count` at 0, `total_standard_hours` at 0.0, `revision` at 1, `released_at` null and `superseded_by_flow_id` null. A duplicate `flow_code` is rejected with `ERR_DUPLICATE_CODE`. The `revision` counter is a process-engineering artefact distinct from the concurrency `version`: it starts at 1 and advances by 1 each time a step is appended after an earlier release attempt on the flow was rejected.

Steps are appended one at a time while the flow is still `DRAFT`; an attempt to append to a `RELEASED` or `OBSOLETE` flow is rejected with `ERR_FLOW_NOT_DRAFT`. Each step names the `recipe_id` it executes, an ordering key `step_seq` that must be at least 1 and must be unique within the flow (a collision is `ERR_DUPLICATE_CODE`), an operator-facing `step_name`, and the `standard_hours` charged against equipment capacity when a run is opened on it, which must be greater than zero. Two optional properties shape later behaviour: `metrology_required`, defaulting to false, marks a step at which a lot cannot be tracked out until at least one measurement has been recorded; and `rework_target_step_id`, which names another step in the flow that a lot is rewound to when it is reworked from here. A null `rework_target_step_id` means rework is simply not available at that step. Appending a step recomputes the parent flow's `step_count` as the number of steps belonging to it and its `total_standard_hours` as the sum of `standard_hours` over those steps rounded to 2 decimal places, and increments the flow's `version` by 1. Steps within a flow execute in ascending `step_seq`.

Release moves the flow from `DRAFT` to `RELEASED` and is where the flow's cost model is frozen. Release requires the flow to be in `DRAFT`, to have at least one step, and for every one of its steps to resolve a recipe whose `status` is `QUALIFIED`; a flow with no steps, or with a step whose recipe is `RESTRICTED`, is rejected with `ERR_FLOW_HAS_NO_STEPS`. On success the server recomputes and pins `step_count` and `total_standard_hours`, sets `released_at` to the current logical instant, sets `status` to `RELEASED`, and increments the flow's `version` by 1.

Release optionally carries `supersedes_flow_id`, naming a currently `RELEASED` flow of the *same* `product_family` that this release replaces. If the named flow is not `RELEASED`, the release is rejected with `ERR_FLOW_NOT_RELEASED`. When it is, the named flow is driven from `RELEASED` to `OBSOLETE`: its `status` becomes `OBSOLETE`, its `superseded_by_flow_id` is set to the `id` of the releasing flow, and its `version` increments by 1. `OBSOLETE` is terminal for a flow. Lots already running an obsoleted flow continue undisturbed; only the creation of new wafer start plans against it is blocked.

### 3.2. Recipes and Engineering Change Control

A **recipe** is the process program a step executes. A `ProcessEngineer` creates one with a `recipe_code` of 1 to 32 globally unique characters, a `tool_type` from `LITHO`, `ETCH`, `DEPOSITION`, `IMPLANT` and `CMP`, a `target_value` greater than zero representing the current nominal process target such as an etch depth in nanometres, and optionally `qual_expiry_days`, the number of days a chamber qualification against this recipe stays valid, which must be at least 1 and defaults to 90. A new recipe opens with `status` `QUALIFIED`, `restricted_reason` `NONE` and `revision` 1. A duplicate `recipe_code` is `ERR_DUPLICATE_CODE`.

Changing a recipe requires an engineering change notice. The authoring `ProcessEngineer` submits a `change_class` of `MINOR`, `MAJOR` or `CRITICAL` declaring the blast radius, a `proposed_target` greater than zero that will replace the recipe's `target_value`, and a free-text `justification` retained for audit. The server records the author's `X-User-ID` in `author_user_id`, opens the notice in `SUBMITTED` `status` with `revision_round` at 0 and `approver_user_id` and `pinned_recipe_revision` null, and scores the change immediately.

The **risk score** combines three interacting inputs. The first is a discrete class weight: 10.0 for `MINOR`, 35.0 for `MAJOR`, 60.0 for `CRITICAL`. The second is a normalised, saturating relative move: take the absolute difference between `proposed_target` and the recipe's current `target_value`, divide it by that current `target_value`, divide the result by a normalising move of 0.10 — that is, a ten-percent shift saturates the term — take the smaller of that quotient and 1.0, and multiply by 25.0. The third is a normalised, saturating blast radius: `impact_lot_count` is the number of distinct lots whose `flow_state` is `RELEASED` or `IN_PROCESS` and whose flow contains at least one step on this recipe with a `step_seq` greater than the lot's `current_step_seq`; lots that are `PLANNED`, `AT_SORT`, `COMPLETED` or `SCRAPPED` are excluded because the change can no longer harm them. Divide `impact_lot_count` by a normalising count of 20, take the smaller of that quotient and 1.0, and multiply by 15.0. The `risk_score` is the sum of the three terms rounded to 2 decimal places. A notice whose `risk_score` is 70.0 or higher has `requires_full_requal` set true, which is what drives the chamber-requalification cascade at implementation time; below 70.0 it is false.

Review is the `QualityManager`'s. Sending a notice back for revision requires a `reviewer_comment` and requires the notice to be `SUBMITTED`; an inadmissible `status` at any point in this workflow is `ERR_CHANGE_REQUEST_INVALID_STATE`. The revision loop is bounded at two completed rounds. While `revision_round` is strictly below 2, the request drives the notice `SUBMITTED → REVISION_REQUESTED`. Once `revision_round` has reached 2, the same request instead drives the notice `SUBMITTED → REJECTED` — the third review that would send it back terminates the notice outright. `REJECTED` is terminal. Either branch increments the notice's `version` by 1.

Only the original author may re-author a notice in `REVISION_REQUESTED`, supplying a fresh `change_class`, `proposed_target` and `justification`. Resubmission overwrites those three fields, increments `revision_round` by 1, recomputes `impact_lot_count`, `risk_score` and `requires_full_requal` from the current state of the recipe and the line, and drives the notice `REVISION_REQUESTED → SUBMITTED`, incrementing its `version` by 1. This is the cycle that makes the change-control machine cyclic: `SUBMITTED → REVISION_REQUESTED → SUBMITTED`.

Approval is where the recipe is pinned and frozen. A `QualityManager` other than the author approves a `SUBMITTED` notice, carrying `expected_recipe_version` as described in §2.6. On success the server records `approver_user_id` as the approver's `X-User-ID`, sets `pinned_recipe_revision` to the recipe's `revision` as it stands at that instant, drives the notice `SUBMITTED → APPROVED`, and increments the notice's `version` by 1. The recipe is driven `QUALIFIED → RESTRICTED` with `restricted_reason` set to `ECN_PENDING_IMPLEMENTATION`; if a sibling approval has already left the recipe `RESTRICTED`, the recipe stays `RESTRICTED` with its `restricted_reason` unchanged. Either way the recipe's `version` increments by 1, so approval never fails on the recipe's `status`. Several notices may therefore be approved against one recipe, each pinning its own `pinned_recipe_revision`.

Implementation is the author side's again. A `ProcessEngineer` implements an `APPROVED` notice, and the server first checks that the recipe's `revision` still equals the notice's `pinned_recipe_revision`; if a sibling notice has been implemented in the meantime and moved the revision, the request is rejected with `ERR_PINNED_REVISION_STALE`. On success the notice is driven `APPROVED → IMPLEMENTED` — terminal — with its `version` incremented by 1, and the recipe is driven `RESTRICTED → QUALIFIED`: its `target_value` becomes the notice's `proposed_target`, its `revision` increments by 1, its `restricted_reason` returns to `NONE`, and its `version` increments by 1. `QUALIFIED → RESTRICTED → QUALIFIED` is the recipe's cycle.

When the implemented notice has `requires_full_requal` true, implementation additionally cascades: every chamber whose `qualified_recipe_id` names this recipe and whose `qual_state` is `QUALIFIED` is driven `QUALIFIED → UNQUALIFIED`, clearing its `qualified_at` and `qual_expires_at` to null and incrementing its `version`; and every lot in `RELEASED` or `IN_PROCESS` holding an open run on one of those chambers is raised to `QUAL_HOLD`, with `hold_excursion_id` left null because no excursion caused it. A `RESTRICTED` recipe blocks two things while it waits: no chamber may be qualified against it, and no production run may be opened on a step that uses it, both rejected with `ERR_RECIPE_RESTRICTED`.

### 3.3. Tools, Chambers, Preventive Maintenance and Qualification

An `EquipmentEngineer` commissions a tool with a globally unique `equipment_code` of 1 to 32 characters, a `tool_type` from the same five classes as recipes, and three optional operating parameters: `pm_interval_hours`, the productive hours between maintenance events, greater than zero and defaulting to 168.0 — one full week of round-the-clock production; `purge_buffer_hours`, the hours the tool must idle for chamber purge after maintenance, at least zero and defaulting to 2.0; and `hours_since_pm`, at least zero and defaulting to 0.0, which may be seeded at commissioning to reflect productive time accrued before the tool entered this system. A commissioned tool opens in `state` `IDLE` with `available_capacity_hours` at 720.00, `pm_started_at` null and `purge_until` null. A duplicate `equipment_code` is `ERR_DUPLICATE_CODE`.

Chambers are added to a tool one at a time. Each names its `equipment_id`, a `chamber_code` of 1 to 16 characters unique within that tool (a collision is `ERR_DUPLICATE_CODE`), the single `qualified_recipe_id` it is set up to run, and optionally a `particle_limit` greater than zero, defaulting to 50.0. A new chamber opens with `qual_state` `UNQUALIFIED`, `occupancy_state` `FREE`, `particle_count` 0.0, and `qualified_at` and `qual_expires_at` null.

Qualification is recorded as a run against the chamber's set-up recipe, carrying a `qual_result` of either `PASS` or `FAIL`. A qualification run is accepted only while the chamber's `qual_state` is `UNQUALIFIED` or `QUAL_EXPIRED`; a chamber that is already `QUALIFIED` must lapse or be disqualified first, and a `DISQUALIFIED` chamber must be cleared through maintenance, both rejected with `ERR_CHAMBER_INVALID_QUAL_STATE`. The parent tool's `state` must be neither `DOWN` nor `PM`, otherwise `ERR_EQUIPMENT_DOWN`. The recipe named by `qualified_recipe_id` must be `QUALIFIED`, otherwise `ERR_RECIPE_RESTRICTED`. And the chamber's `particle_count` must be less than or equal to its `particle_limit`. A `PASS` run drives the chamber `UNQUALIFIED → QUALIFIED` or `QUAL_EXPIRED → QUALIFIED`, setting `qualified_at` to the current logical instant and `qual_expires_at` to that instant plus the recipe's `qual_expiry_days` days. A `FAIL` run is recorded but drives no transition: the chamber keeps its current `qual_state`, `qualified_at` and `qual_expires_at`. Either result increments the chamber's `version` by 1.

Qualification lapses on its own. Whenever a chamber is evaluated as a dispatch candidate and the current logical instant is at or after its `qual_expires_at`, the chamber is first driven `QUALIFIED → QUAL_EXPIRED` and then excluded from the candidate set, with its `version` incremented. This evaluation runs for every candidate before ranking, so the lapse is observable even when the dispatch itself then fails.

Preventive maintenance is started by an `EquipmentEngineer` with a `pm_reason`. A maintenance start is admissible only from `IDLE` or `DOWN`; a `PRODUCTIVE` tool must track out or abort its open runs first, and a tool already in `PM` cannot restart maintenance, both rejected with `ERR_EQUIPMENT_INVALID_STATE`. Either admissible path drives the tool to `PM`, sets `pm_started_at` to the current logical instant, and increments the tool's `version` by 1. `DOWN` is therefore not terminal — maintenance is the recovery path out of it.

Completing maintenance requires the tool to be in `PM`, otherwise `ERR_EQUIPMENT_NOT_IN_PM`, and does a great deal at once. The tool is driven `PM → IDLE`; `hours_since_pm` resets to 0.0; `available_capacity_hours` resets to 720.00; `purge_until` is set to the current logical instant plus `purge_buffer_hours`; every chamber of the tool whose `qual_state` is `DISQUALIFIED` is driven `DISQUALIFIED → UNQUALIFIED`, which is what closes the chamber cycle `QUALIFIED → DISQUALIFIED → UNQUALIFIED → QUALIFIED`; every lot on `QUAL_HOLD` whose `hold_excursion_id` names an excursion raised on a chamber of this tool is released back to `hold_state` `NONE` with its `hold_excursion_id` cleared to null; and the tool's `version` increments by 1. During the purge window no run may open on any of the tool's chambers: the interval is closed, so a track-in at exactly `purge_until` is still rejected with `ERR_PM_PURGE_ACTIVE`, and only a strictly later instant is admitted. A tool that has never been maintained has a null `purge_until` and no purge restriction.

### 3.4. Wafer Start Planning and Capacity Commitment

A `FabPlanner` drafts a weekly plan naming the `flow_id` of a `RELEASED` flow — a flow that is `DRAFT` or `OBSOLETE` is rejected with `ERR_FLOW_NOT_RELEASED` — plus the `product_family` being planned, which must equal the flow's own `product_family` or the request is rejected with `ERR_PRODUCT_FAMILY_MISMATCH`; a `week_start_date` giving the first instant of the planning week in ISO 8601 UTC; `planned_wafer_starts`, at least 1, being the wafers the plan authorises for release during the week; `capacity_budget_hours`, greater than zero, being the fab capacity allocated to the plan; and `cycle_time_target_days`, greater than zero, the target days from lot release to sort. A drafted plan opens in `DRAFT` `status` with `released_wafer_starts` 0, `committed_hours` 0.0, `surcharge_hours` 0.0 and `commitment_tier` `TIER_0`.

Committing the plan prices it. Commit requires the plan to be in `DRAFT` — a second commit is rejected with `ERR_PLAN_ALREADY_COMMITTED` — and requires the flow still to be `RELEASED` and the product families still to agree. The pricing sequence is fixed and must be evaluated in exactly this order, because the tier looks circular and is resolved by reading the tier from the *pre-surcharge* utilisation only; the surcharge never re-tiers the plan.

First, base hours are `planned_wafer_starts` multiplied by the flow's `total_standard_hours` as pinned at release, rounded to 2 decimal places. Steps added to the flow after release cannot change this, because the flow is no longer `DRAFT`. Second, the pre-surcharge utilisation is the base hours divided by `capacity_budget_hours`, rounded to 4 decimal places. Third, `commitment_tier` is selected from that utilisation against inclusive lower bounds: `TIER_3` when the utilisation is 0.90 or more, otherwise `TIER_2` when it is 0.70 or more, otherwise `TIER_1` when it is 0.50 or more, otherwise `TIER_0`. Fourth, the surcharge rate follows from the tier: zero for `TIER_0`, five percent for `TIER_1`, twelve percent for `TIER_2`, and twenty-five percent for `TIER_3`. Fifth, `surcharge_hours` is the base hours multiplied by that rate, rounded to 2 decimal places. Sixth, `committed_hours` is the base hours plus `surcharge_hours`, rounded to 2 decimal places. Seventh, if `committed_hours` is strictly greater than `capacity_budget_hours`, the commit is rejected with `ERR_CAPACITY_BUDGET_EXCEEDED` and nothing is persisted — the plan stays `DRAFT` with `committed_hours` at 0.0, `surcharge_hours` at 0.0 and `commitment_tier` at `TIER_0`.

A successful commit records `commitment_tier`, `surcharge_hours` and `committed_hours`, drives the plan `DRAFT → COMMITTED`, and increments the plan's `version` by 1. The plan's final state, `CLOSED`, is reached only through lot release, described next, and is terminal.

### 3.5. Lot Creation, Release and Cycle Time

A `FabPlanner` creates a production lot naming the `plan_id` whose wafer starts it will consume and the `flow_id` it will run, which must equal the plan's `flow_id` or the request is rejected with `ERR_PRODUCT_FAMILY_MISMATCH`; a globally unique `lot_number` of 1 to 32 characters, duplicates rejected with `ERR_DUPLICATE_CODE`; a `wafer_count` of at least 1; and optionally a `priority_class` of `STANDARD`, `HOT` or `SUPER_HOT`, defaulting to `STANDARD`. A created lot opens with `flow_state` `PLANNED`, `hold_state` `NONE`, `lot_type` `PRODUCTION`, `current_step_seq` 0, `rework_count` 0, `origin_wafer_count` equal to the supplied `wafer_count`, and `parent_lot_id`, `hold_excursion_id`, `released_at`, `completed_at` and `actual_cycle_time_days` all null. A lot's progress and its hold posture are two independent dimensions: a lot can perfectly well be `IN_PROCESS` and on `SPC_HOLD`, or `RELEASED` and on `ENGINEERING_HOLD`.

Release drives the lot `PLANNED → RELEASED` and is the point at which the plan's authorisation is drawn down. Release requires the lot to be `PLANNED` — any other `flow_state` is `ERR_LOT_INVALID_STATE` — requires the plan to be `COMMITTED`, so a `DRAFT` or `CLOSED` plan is rejected with `ERR_PLAN_NOT_COMMITTED`, and requires the `expected_plan_version` agreement of §2.6. The wafer-start ledger is then evaluated: the candidate total is the plan's `released_wafer_starts` plus the lot's `wafer_count`, and if that candidate is strictly greater than `planned_wafer_starts` the release is rejected with `ERR_PLAN_STARTS_EXCEEDED`. On success the lot's `flow_state` becomes `RELEASED`, `released_at` is set to the current logical instant, the lot's `version` increments by 1, the plan's `released_wafer_starts` is set to the candidate total, and the plan's `version` increments by 1. When the candidate total is exactly equal to `planned_wafer_starts`, the plan is additionally driven `COMMITTED → CLOSED`, with a further increment of the plan's `version`. Engineering split lots never enter this ledger — their wafers were already counted against the plan when the parent was released.

Cycle time is reported two ways, and they deliberately disagree. The forward-looking projection is available on demand for a released lot and returns six values. `remaining_standard_hours` is the sum of `standard_hours` over every step of the lot's flow whose `step_seq` is strictly greater than the lot's `current_step_seq`, rounded to 2 decimal places — the not-yet-completed remainder. `queue_factor` is read from the lot's `priority_class`: 1.60 for `STANDARD`, 1.25 for `HOT`, and 1.05 for `SUPER_HOT`. `projected_remaining_days` is `remaining_standard_hours` multiplied by `queue_factor`, divided by 24, rounded to 3 decimal places. `elapsed_days` is the interval from the lot's `released_at` to the current logical instant, expressed in seconds and divided by 86400, rounded to 3 decimal places. `projected_cycle_time_days` is `elapsed_days` plus `projected_remaining_days`, rounded to 3 decimal places. And `cycle_time_status` is `AT_RISK` when `projected_cycle_time_days` is strictly greater than the plan's `cycle_time_target_days`, and `ON_TARGET` otherwise. Because the projection adds a modelled remainder rather than observed queueing, it is strictly greater than elapsed time whenever any step remains.

The chronological variant is pinned once, at the moment the lot completes, into `actual_cycle_time_days`: the interval from `released_at` to `completed_at` in seconds divided by 86400, rounded to 3 decimal places. It uses no queue factor and no step data at all, and for the same lot at the same instant it differs from the projection by exactly `projected_remaining_days`.

### 3.6. Cleanroom Readiness and Running the Line

Nobody touches product until they are registered, certified and gowned. A `QualityManager` registers a cleanroom operator with a `badge_id` of 1 to 16 characters that must be globally unique across all operators — a duplicate is rejected with `ERR_DUPLICATE_CODE` — a `full_name` for the audit trail, and `certified_tool_types`, a non-empty array whose every element is one of the five tool classes `LITHO`, `ETCH`, `DEPOSITION`, `IMPLANT` and `CMP`; an empty array or an element outside that set is rejected with `ERR_VALIDATION`. A registered operator opens with `cert_status` `ACTIVE`, `gown_state` `STREET` and `gowned_at` null.

Gowning posture and certification standing then evolve as two independent dimensions of the same row, both driven through a patch on that row. An `Operator` may patch only their own row, and only to supply `gown_state`; supplying `gown_state` as `GOWNED` while the operator is in `STREET` drives `STREET → GOWNED` and stamps `gowned_at` with the current logical instant, and supplying `STREET` while `GOWNED` drives `GOWNED → STREET` and clears `gowned_at` back to null. Gowning into the cleanroom requires `cert_status` to be `ACTIVE`, and a gowning change never alters `cert_status`.

Certification standing is the `QualityManager`'s to set, again through a patch supplying `cert_status`. An `ACTIVE` operator may be moved to `SUSPENDED` and a `SUSPENDED` operator restored to `ACTIVE`, so suspension is reversible; either may be moved to `REVOKED`, which is terminal and cannot be undone. Both transitions into `REVOKED` additionally force `gown_state` to `STREET`, because a revoked badge cannot remain gowned in the cleanroom. Otherwise the two dimensions do not interfere: a suspension leaves the recorded `gown_state` and `gowned_at` exactly as they were, so an operator suspended while gowned is still recorded as `GOWNED` and is blocked from floor actions by the certification check alone. Every accepted patch increments the operator's `version` by 1.

Tracking a lot into its next operation is the busiest transaction in the system. A gowned `Operator` supplies the `lot_id`, the `step_id` of the operation, and their own `operator_id`, which must equal their `X-User-ID`. The client never names a chamber — the server chooses one.

Admissibility is checked first. The lot's `flow_state` must be `RELEASED` or `IN_PROCESS`, otherwise `ERR_LOT_INVALID_STATE`; its `hold_state` must be `NONE`, otherwise `ERR_LOT_ON_HOLD`. The operator's `cert_status` must be `ACTIVE` and their `gown_state` must be `GOWNED`. The step's recipe `tool_type` must appear in the operator's `certified_tool_types`, otherwise `ERR_OPERATOR_NOT_CERTIFIED`. The step must belong to the lot's flow, otherwise `ERR_STEP_FLOW_MISMATCH`. And the step must be the lot's *next* operation: its `step_seq` must be the lowest `step_seq` in the lot's flow that is strictly greater than the lot's `current_step_seq`. Skipping ahead or repeating a completed step is rejected with `ERR_STEP_SEQUENCE_VIOLATION`. The recipe behind the step must be `QUALIFIED`, otherwise `ERR_RECIPE_RESTRICTED`.

**Chamber selection** then runs. The candidate set is every chamber satisfying all of the following: its tool's `tool_type` equals the `tool_type` of the recipe named by the step; its `qualified_recipe_id` equals the step's `recipe_id`; its `qual_state` is `QUALIFIED`; its `occupancy_state` is `FREE`; its `particle_count` is less than or equal to its `particle_limit`; its tool's `state` is `IDLE` or `PRODUCTIVE`; the current logical instant is strictly before its `qual_expires_at`; and its tool's `purge_until` is either null or strictly earlier than the current logical instant. Chambers on tools in `PM` or `DOWN` are excluded by that filter, as are chambers already `OCCUPIED` by an open run. If the candidate set is empty because every otherwise-eligible chamber's qualification has lapsed, the rejection is `ERR_CHAMBER_QUAL_EXPIRED`; if it is empty for any other reason, the rejection is `ERR_NO_QUALIFIED_CHAMBER`, and in either case no run is created. If the sole reason is the purge window, the rejection is `ERR_PM_PURGE_ACTIVE`.

Surviving candidates are ranked by a dispatch score that starts at 100 and subtracts three penalties. The **qualification-decay penalty** uses the remaining fraction of the chamber's qualification window: take the interval from the current logical instant to `qual_expires_at`, divide it by the full interval from `qualified_at` to `qual_expires_at`, and floor the result at zero; the penalty is 40.0 multiplied by one minus that remaining fraction, so a freshly qualified chamber loses nothing and a chamber at the very end of its window loses the full 40 points. The **contamination penalty** is 25.0 multiplied by the smaller of 1.0 and the chamber's `particle_count` divided by its `particle_limit`. The **maintenance-proximity penalty** is 20.0 multiplied by the smaller of 1.0 and the tool's `hours_since_pm` divided by its `pm_interval_hours` — except that for a lot whose `priority_class` is `SUPER_HOT` this penalty is forced to zero, so a super-hot lot ignores maintenance proximity entirely and can win a different chamber than a `STANDARD` or `HOT` lot would from exactly the same chamber population. The score is rounded to 2 decimal places, with all intermediate ratios carried at full precision, and only then compared. Candidates are ordered by score descending, and ties are broken by ascending `chamber_code`. The first row wins: its `id` becomes the run's `chamber_id` and its score becomes the run's `dispatch_score`.

One fiscal check remains: the winning chamber's tool must have `available_capacity_hours` greater than or equal to the step's `standard_hours`, otherwise `ERR_EQUIPMENT_CAPACITY_EXHAUSTED`. On success a run is created in `OPEN` `status` with `tracked_in_at` at the current logical instant, `tracked_out_at` and `actual_hours` null, and `reserved_hours` captured from the step's `standard_hours`. The winning chamber's `occupancy_state` becomes `OCCUPIED`. The tool's `available_capacity_hours` is reduced by `reserved_hours` and, if the tool was `IDLE`, it is driven `IDLE → PRODUCTIVE`, with its `version` incremented. A lot in `RELEASED` is driven `RELEASED → IN_PROCESS`.

Tracking out closes the run. It requires the run's `status` to be `OPEN`, otherwise `ERR_STEP_RUN_NOT_OPEN`; requires the caller's `X-User-ID` to equal the run's `operator_id`; requires the operator to be `ACTIVE` and `GOWNED`; and, when the step's `metrology_required` is true, requires at least one measurement to exist against the run, otherwise `ERR_METROLOGY_MISSING`. On success the run is driven `OPEN → COMPLETED`, `tracked_out_at` is set to the current logical instant, and `actual_hours` is the interval from `tracked_in_at` to `tracked_out_at` expressed in hours and rounded to 2 decimal places. The chamber's `occupancy_state` returns to `FREE`. The tool's `available_capacity_hours` has `reserved_hours` credited back and `actual_hours` debited, and its `hours_since_pm` has `actual_hours` added. The lot's `current_step_seq` is set to the tracked-out step's `step_seq`. If the tracked-out step carried the highest `step_seq` in the lot's flow, the lot is additionally driven `IN_PROCESS → AT_SORT`. If no open run remains anywhere on the tool's chambers, the tool is driven `PRODUCTIVE → IDLE`. The run's `version` increments by 1.

Aborting closes the run without charging it. An operator-driven abort carries an `abort_reason`, requires the run to be `OPEN`, and requires `X-User-ID` to equal the run's `operator_id`; the same transition also fires as a cascade when the run's chamber leaves `QUALIFIED` through containment, or when the run's lot is scrapped. Either way the run is driven `OPEN → ABORTED`, `tracked_out_at` is set to the current logical instant, and `actual_hours` **stays null** — it is never set on an abort. The chamber's `occupancy_state` returns to `FREE`. The tool's `available_capacity_hours` has the *full* `reserved_hours` credited back, leaving no drift, while its `hours_since_pm` is untouched. The lot's `current_step_seq` is unchanged, so the lot must run that step again. If no open run remains on the tool and the tool is `PRODUCTIVE`, it is driven `PRODUCTIVE → IDLE`. The run's `version` increments by 1. `COMPLETED` and `ABORTED` are both terminal for a run.

### 3.7. In-Line Metrology, Statistical Process Control and Excursion Onset

An SPC chart is attached to a metrology-bearing step by a `ProcessEngineer` or a `QualityManager`, naming the `step_id` it monitors, a `param_name` label, a centre line `target`, a process standard deviation `sigma` greater than zero, and four limits: `usl` and `lsl` as the upper and lower specification limits, and `ucl` and `lcl` as the upper and lower control limits, ordered so that `lsl` is below `lcl`, `lcl` is below `target`, `target` is below `ucl`, and `ucl` is below `usl`. A new chart opens in `MONITORING` `status` with `consecutive_same_side_count` 0, `last_side` `NONE` and `violation_count` 0.

A gowned, active `Operator` records a reading against an open run by supplying the `step_run_id`, the `spc_chart_id` that will classify it, and the `measured_value`. The run must be `OPEN`, otherwise `ERR_STEP_RUN_NOT_OPEN`. The chart's `step_id` must equal the run's `step_id`, otherwise `ERR_CHART_STEP_MISMATCH`. The step must actually have `metrology_required` true, otherwise `ERR_METROLOGY_NOT_REQUIRED`. And the chart's `status` must be `MONITORING`; a chart frozen by containment rejects the reading outright with `ERR_SPC_CHART_SUSPENDED` and therefore contributes no state to the run rule.

Classification runs synchronously, before the measurement row is persisted. Let the deviation be the reading minus the chart's `target`. `deviation_sigma` is the absolute deviation divided by `sigma`, rounded to 4 decimal places. The boundary semantics are asymmetric on purpose: specification limits are strict, control limits are inclusive. So the `classification` is `OUT_OF_SPEC` when the reading is strictly above `usl` or strictly below `lsl`; otherwise `OUT_OF_CONTROL` when the reading is at or above `ucl` or at or below `lcl`; otherwise `WARN` when the absolute deviation is at least twice `sigma`; otherwise `IN_CONTROL`.

The Western Electric run rule tracks drift that never breaches a limit. The side of the centre line is `ABOVE` when the deviation is positive, `BELOW` when it is negative, and `NONE` when the reading sits exactly on `target`. If the absolute deviation is at least one `sigma` and the side equals the chart's current `last_side`, the chart's `consecutive_same_side_count` increments by 1. If the absolute deviation is at least one `sigma` but the side differs from `last_side`, the count is reset to 1. If the absolute deviation is below one `sigma` — inside the one-sigma band — the count is reset to 0. The chart's `last_side` is then set to the new side. The measurement's `run_rule_triggered` is true when the resulting `consecutive_same_side_count` is 4 or more, meaning four consecutive points on the same side of the centre line, each at least one `sigma` away from it.

When the `classification` is `OUT_OF_CONTROL` or `OUT_OF_SPEC`, or `run_rule_triggered` is true, the chart's `violation_count` increments by 1 and an **excursion** is opened: `source_type` `SPC`, `spc_chart_id` pointing at the chart, `lot_id` copied from the run's `lot_id`, `trigger_value` set to the reading rounded to 4 decimal places, and the measurement's own `excursion_id` set to the new excursion. When no violation occurs, `excursion_id` stays null.

Particle monitoring is the third excursion source. An `EquipmentEngineer` or `QualityManager` records a `particle_reading` on a chamber; the chamber's `particle_count` is set to that reading. When the reading is strictly above the chamber's `particle_limit`, the contamination protocol opens a `PARTICLE` excursion with `chamber_id` pointing at the chamber and `trigger_value` set to the reading, and contains it immediately with no human in the loop. The `lot_id` of a particle excursion is null when the chamber was idle. The automatic `containment_scope` is chosen by magnitude: `EQUIPMENT` when the reading is at or above twice the chamber's `particle_limit`, and `CHAMBER` otherwise.

An excursion records exactly one polymorphic source pointer, indicated by `source_type`: `spc_chart_id` is non-null only for `SPC`, `die_sort_run_id` only for `DIE_SORT`, and `chamber_id` only for `PARTICLE`. Every excursion opens in `OPEN` `status`, `containment_scope` `NONE`, `disposition` `NONE`, `failure_signature` `NONE`, `severity_variant` `PROVISIONAL`, and `contained_by_user_id` and `dispositioned_by_user_id` null.

**Severity** is scored the same way under both variants, and only the lot-spread input differs. A normalised deviation ratio is computed from the source: for `SPC`, the absolute difference between `trigger_value` and the chart's `target`, divided by the chart's `usl` minus its `target`; for `DIE_SORT`, `trigger_value` divided by a maximum modelled yield loss of 0.25; for `PARTICLE`, `trigger_value` divided by the chamber's `particle_limit`. The deviation term is 60.0 multiplied by the smaller of 1.0 and that ratio. The spread term is 3.0 multiplied by the smaller of 10 and `affected_lot_count`, so lot spread saturates at ten lots. A specification penalty of 10.0 is added when the opening measurement's `classification` was `OUT_OF_SPEC`, and 0.0 otherwise. `severity_score` is the sum of those three terms rounded to 2 decimal places, with the deviation ratio carried at full precision. `severity_band` follows from the score against inclusive lower bounds: `HIGH` at 70.0 or above, otherwise `MEDIUM` at 40.0 or above, otherwise `LOW`.

`affected_lot_count` always counts *distinct* lots, and the counted set widens between the variants. Under the `PROVISIONAL` variant, set at creation before any human has looked at the excursion, the set is the narrow "what is in the tool right now" population: for an `SPC` excursion, lots with an `OPEN` run on the chart's `step_id` whose `flow_state` is `RELEASED` or `IN_PROCESS`; for a `PARTICLE` excursion, lots with an `OPEN` run on the excursion's `chamber_id` whose `flow_state` is `RELEASED` or `IN_PROCESS`; for a `DIE_SORT` excursion, exactly one — the sort run's own lot. Under the `FINAL` variant, set at containment, the set widens to the retrospective "what material was exposed" population: for `SPC`, lots with a run on the chart's `step_id` whose `status` is `OPEN` or `COMPLETED` and whose `flow_state` is `RELEASED`, `IN_PROCESS`, `AT_SORT` or `COMPLETED`; for `PARTICLE`, lots with a run on the excursion's `chamber_id` whose `status` is `OPEN`, `COMPLETED` or `ABORTED` and whose `flow_state` is `RELEASED`, `IN_PROCESS`, `AT_SORT` or `COMPLETED`; for `DIE_SORT`, every distinct lot running the same flow as the sort lot whose `flow_state` is `RELEASED`, `IN_PROCESS`, `AT_SORT` or `COMPLETED`. On identical data the `FINAL` set is therefore never smaller than the `PROVISIONAL` one, which is why finalisation can push `severity_band` up a band. No ordering is involved in either variant, so no tie-break is needed.

### 3.8. Excursion Containment, Disposition, Rework and Engineering Splits

Containment is the `QualityManager`'s call, and the moment the blast radius is fixed. Containment requires the excursion to be `OPEN` and its `source_type` to be `SPC` or `DIE_SORT`; a `PARTICLE` excursion was already contained at creation, and either mistake is rejected with `ERR_EXCURSION_INVALID_STATE`. The request supplies the `containment_scope` to apply — `SPC_CHART`, `CHAMBER` or `EQUIPMENT` — and, when the scope implicates a specific chamber, that `chamber_id`. On success the excursion's `severity_variant` becomes `FINAL`, `affected_lot_count` and `severity_score` are recomputed under the `FINAL` variant and `severity_band` re-derived, `containment_scope` is recorded, `contained_by_user_id` is set to the containing engineer's `X-User-ID`, the excursion is driven `OPEN → CONTAINED`, and its `version` increments by 1.

Each scope fires a different cascade. At `SPC_CHART` scope, the chart is driven `MONITORING → SUSPENDED`, and every lot holding an open run on that chart's `step_id` whose `flow_state` is `RELEASED` or `IN_PROCESS` is raised from `NONE` to `SPC_HOLD` with its `hold_excursion_id` set to this excursion. At `CHAMBER` scope, the implicated chamber is driven `QUALIFIED → DISQUALIFIED` with `qualified_at` and `qual_expires_at` cleared to null, its open run is driven `OPEN → ABORTED` with the full reservation credited back to the tool, and that run's lot is raised to `QUAL_HOLD` with its `hold_excursion_id` set to this excursion. At `EQUIPMENT` scope, the tool itself is driven to `DOWN` from either `IDLE` or `PRODUCTIVE`; a `PRODUCTIVE` tool additionally has every open run on its chambers driven `OPEN → ABORTED`, and any chamber leaving `QUALIFIED` as part of that containment raises its in-process lots to `QUAL_HOLD`. A lot already on `SPC_HOLD` when its chamber leaves `QUALIFIED` is raised `SPC_HOLD → QUAL_HOLD`, never the reverse.

Disposition decides the fate of the caught material, and must be performed by someone other than the containing engineer. It requires the excursion to be `CONTAINED`, and carries a `disposition` of `CONTINUE`, `REWORK` or `SCRAP` together with a `root_cause_note` recording the failure analysis. The excursion is driven `CONTAINED → DISPOSITIONED` — terminal — with `dispositioned_by_user_id` set to the acting `X-User-ID` and its `version` incremented. Regardless of which `disposition` was chosen, any chart suspended by this excursion's containment is driven `SUSPENDED → MONITORING`, with `consecutive_same_side_count` reset to 0 and `last_side` reset to `NONE`, so the run rule restarts from a clean slate; that is what closes the chart cycle `MONITORING → SUSPENDED → MONITORING`.

The three dispositions then diverge. `CONTINUE` releases the holds this excursion placed: every lot whose `hold_excursion_id` names this excursion returns to `hold_state` `NONE` with `hold_excursion_id` cleared to null, whether the hold was `SPC_HOLD` or `QUAL_HOLD`. `REWORK` deliberately leaves the affected lots on `SPC_HOLD`, awaiting the rework rewind described below. `SCRAP` drives every affected lot whose `flow_state` is `RELEASED`, `IN_PROCESS` or `AT_SORT` to `SCRAPPED`, clearing its `hold_state` to `NONE` and incrementing its `version`; a lot scrapped out of `IN_PROCESS` additionally has every one of its open runs driven `OPEN → ABORTED`. `SCRAPPED` is terminal, and a scrapped child lot leaves the parent's conserved wafer pool permanently.

Rework is the `ProcessEngineer`'s rewind of a held lot. It requires the lot's `hold_state` to be `SPC_HOLD`, requires the excursion named by `hold_excursion_id` to carry a `disposition` of `REWORK`, requires the lot's `rework_count` to be strictly below the limit of 2 rewinds — a third attempt is rejected with `ERR_REWORK_LIMIT_EXCEEDED` — and requires the step at the lot's `current_step_seq` to declare a non-null `rework_target_step_id`, otherwise `ERR_REWORK_TARGET_NOT_SET`. The lot's `flow_state` must also be `RELEASED` or `IN_PROCESS`. On success the lot's `current_step_seq` is set to one less than the `step_seq` of the step named by that `rework_target_step_id`, so that the rework target step itself becomes the lot's next admissible operation; `rework_count` increments by 1; `hold_state` returns to `NONE` and `hold_excursion_id` to null; and the lot's `version` increments by 1.

Engineering experiments run as **split lots** alongside production. A `ProcessEngineer` carves one out of an in-fab lot by supplying `split_wafer_count`, a `lot_number` for the child, the `expected_lot_version` of the parent, and optionally a `priority_class` for the child. The parent's `flow_state` must be `RELEASED` or `IN_PROCESS`, and `split_wafer_count` must be at least 1 and strictly less than the parent's current `wafer_count` — a split that would empty or over-draw the parent is rejected with `ERR_INVALID_SPLIT_QUANTITY`. On success the parent's `wafer_count` is reduced by `split_wafer_count` and its `version` increments by 1. A child lot is created with `parent_lot_id` set to the parent, `lot_type` `ENGINEERING_SPLIT`, `wafer_count` and `origin_wafer_count` both equal to `split_wafer_count`, the parent's `plan_id` and `flow_id`, `current_step_seq` copied from the parent, `flow_state` `RELEASED`, and `hold_state` `ENGINEERING_HOLD` — the child is born held, because an experiment must be deliberately released. The plan's `released_wafer_starts` is *not* touched, and an engineering split never contributes to it.

Rejoining folds an experiment back into production. It requires the lot's `hold_state` to be `ENGINEERING_HOLD` and the lot to be an `ENGINEERING_SPLIT` with a non-null `parent_lot_id`, otherwise `ERR_NOT_A_SPLIT_LOT`. On success the parent's `wafer_count` is increased by the child's `wafer_count`, the child's `wafer_count` is set to 0, the child's `hold_state` returns to `NONE` and its `flow_state` becomes `COMPLETED`, and both the child's and the parent's `version` increment by 1.

### 3.9. Test, Sort, Wafer-Map Yield and Speed-Grade Binning

A lot that has tracked out of its final step sits at `AT_SORT`, where a `YieldEngineer` records the sort results. The request names the `lot_id`, which must have `flow_state` `AT_SORT` or the request is rejected with `ERR_LOT_INVALID_STATE`, and which must not be on hold or the request is rejected with `ERR_LOT_ON_HOLD`. It supplies `gross_die_per_wafer`, the reticle-derived gross die count per wafer of at least 1, recorded for audit; `baseline_yield`, the product-family baseline sort yield, greater than zero and no more than 1, which serves as the denominator of yield loss; and `wafer_results`, a non-empty array of per-wafer outcomes. Each element of `wafer_results` carries a `wafer_slot` of at least 1, a `tested_die` count of at least 1, a `good_die` count of at least 0, and four failure-mode counts of at least 0 each: `edge_ring_fails`, `center_cluster_fails`, `scratch_line_fails` and `parametric_shift_fails`. Per element, `good_die` must not exceed `tested_die`, and the four failure counts must sum to exactly `tested_die` minus `good_die`; an empty array or any element failing either rule is rejected with `ERR_WAFER_RESULT_INCONSISTENT`.

**Yield.** The rounding order here is pinned and matters: round per wafer first, then average, then round the average. Pooling good and tested die across wafers and rounding once yields a different number and is explicitly not used. Working through the elements in ascending `wafer_slot`, each wafer's yield is its `good_die` divided by its `tested_die`, rounded to 4 decimal places. `sort_yield` is the sum of those per-wafer yields divided by the number of elements, rounded to 4 decimal places. `good_die_total` is the plain sum of `good_die` across all elements — the pool the speed-grade waterfall will later distribute. `yield_loss_ratio` is the greater of 0.0 and the quantity `baseline_yield` minus `sort_yield` divided by `baseline_yield`, rounded to 4 decimal places, so a lot that beats its baseline reports zero loss rather than a negative one. No other sort run contributes to any of these figures.

**Failure signature.** The four failure modes are totalled across all elements, and the grand total of fails is their sum. When there are no fails at all, `dominant_signature` is `NONE` and no division is attempted. Otherwise each mode's share is its total divided by the grand total, rounded to 4 decimal places, and the largest share is taken. If that largest share is strictly below 0.45, no mode dominates and `dominant_signature` is `NONE`. Otherwise `dominant_signature` is the first mode, in the fixed precedence order `SCRATCH_LINE`, then `EDGE_RING`, then `CENTER_CLUSTER`, then `PARAMETRIC_SHIFT`, whose share equals that largest share — the precedence order is the tie-break when two modes share the top.

A sort run opens in `SORTED` `status`, with `premium_target_die`, `standard_target_die`, `premium_die`, `standard_die` and `value_die` all at 0 before binning. When `yield_loss_ratio` reaches 0.10 or more, a `DIE_SORT` excursion is opened with `die_sort_run_id` pointing at this run, `lot_id` copied from the run, `trigger_value` set to `yield_loss_ratio`, and `failure_signature` copied from `dominant_signature`; for excursions from any other source, `failure_signature` stays `NONE`. That excursion is scored under the `PROVISIONAL` variant like any other and awaits containment.

**Binning** allocates the good die pool to speed grades and closes out the lot. A `YieldEngineer` supplies `premium_target_die` and `standard_target_die`, whose sum must be at least 0. Binning requires the run's `status` to be `SORTED` — a second attempt is rejected with `ERR_SORT_RUN_ALREADY_BINNED` — and requires the lot to still be `AT_SORT`. The waterfall then runs in a fixed order: `premium_die` is the smaller of `premium_target_die` and `good_die_total`; `standard_die` is the smaller of `standard_target_die` and whatever remains of `good_die_total` after `premium_die` is taken; and `value_die` absorbs the entire remainder, being `good_die_total` less `premium_die` less `standard_die`. The three buckets therefore always sum to exactly `good_die_total`, and all three are integers with no rounding. The supplied targets are recorded on the run as `premium_target_die` and `standard_target_die`.

Binning drives the run `SORTED → BINNED`, which is terminal, and increments its `version` by 1. It also completes the lot: the lot is driven `AT_SORT → COMPLETED`, its `completed_at` is set to the current logical instant, its `actual_cycle_time_days` is pinned from the chronological variant of the cycle-time calculation described in §3.5, and its `version` increments by 1. `COMPLETED` is terminal for a lot.

## 4. Endpoint Definitions

Operations that mint a new resource return `201 Created`. Operations that modify an existing resource — including state transitions, ledger movements and recorded readings that update an existing row — return `200 OK`. Read operations return `200 OK`. All paths below are absolute; "All roles" means all six roles named in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fab/process-flows` | Create a DRAFT process flow for a product family | ProcessEngineer |
| GET | `/fab/process-flows` | List process flows, filterable by product family, status and superseding flow | All roles |
| GET | `/fab/process-flows/{id}` | Read one process flow | All roles |
| POST | `/fab/process-flows/{id}/steps` | Append a step to a DRAFT flow | ProcessEngineer |
| POST | `/fab/process-flows/{id}/release` | Release a DRAFT flow, optionally superseding a released flow of the same family | ProcessEngineer |
| GET | `/fab/process-steps` | List process steps, filterable by flow, recipe and rework target | All roles |
| GET | `/fab/process-steps/{id}` | Read one process step | All roles |
| POST | `/fab/recipes` | Create a QUALIFIED recipe | ProcessEngineer |
| GET | `/fab/recipes` | List recipes, filterable by tool type and status | All roles |
| GET | `/fab/recipes/{id}` | Read one recipe | All roles |
| POST | `/fab/recipes/{id}/change-requests` | Author an engineering change notice against a recipe and score it | ProcessEngineer |
| GET | `/fab/change-requests` | List engineering change notices, filterable by recipe and status | ProcessEngineer, QualityManager, YieldEngineer |
| GET | `/fab/change-requests/{id}` | Read one engineering change notice | ProcessEngineer, QualityManager, YieldEngineer |
| POST | `/fab/change-requests/{id}/request-revision` | Send a submitted notice back for revision, or reject it on the third request | QualityManager |
| POST | `/fab/change-requests/{id}/resubmit` | Re-author a notice after a revision request and rescore it | ProcessEngineer |
| POST | `/fab/change-requests/{id}/approve` | Approve a submitted notice, pinning the recipe revision | QualityManager |
| POST | `/fab/change-requests/{id}/implement` | Implement an approved notice and cascade requalification when required | ProcessEngineer |
| POST | `/fab/spc-charts` | Attach an SPC chart to a metrology-bearing process step | ProcessEngineer, QualityManager |
| GET | `/fab/spc-charts` | List SPC charts, filterable by step and status | ProcessEngineer, QualityManager, YieldEngineer, Operator |
| GET | `/fab/spc-charts/{id}` | Read one SPC chart | ProcessEngineer, QualityManager, YieldEngineer, Operator |
| POST | `/fab/equipment` | Commission a tool | EquipmentEngineer |
| GET | `/fab/equipment` | List tools, filterable by tool type and state | All roles |
| GET | `/fab/equipment/{id}` | Read one tool | All roles |
| POST | `/fab/equipment/{id}/pm-start` | Take a tool down for preventive maintenance | EquipmentEngineer |
| POST | `/fab/equipment/{id}/pm-complete` | Finish maintenance, reset the capacity ledger and open the purge window | EquipmentEngineer |
| POST | `/fab/chambers` | Add a chamber to a tool, set up for exactly one recipe | EquipmentEngineer |
| GET | `/fab/chambers` | List chambers, filterable by tool, set-up recipe and qualification state | All roles |
| GET | `/fab/chambers/{id}` | Read one chamber | All roles |
| POST | `/fab/chambers/{id}/qualification-runs` | Record a chamber qualification run against its set-up recipe | EquipmentEngineer |
| POST | `/fab/chambers/{id}/particle-readings` | Record a cleanroom particle reading on a chamber | EquipmentEngineer, QualityManager |
| POST | `/fab/operators` | Register a cleanroom operator | QualityManager |
| GET | `/fab/operators` | List operators, filterable by certification standing and gowning posture | All roles |
| GET | `/fab/operators/{id}` | Read one operator | All roles |
| PATCH | `/fab/operators/{id}` | Update gowning posture (Operator, self only) or certification standing (QualityManager) | Operator, QualityManager |
| POST | `/fab/wafer-start-plans` | Draft a weekly wafer start plan against a released flow | FabPlanner |
| GET | `/fab/wafer-start-plans` | List wafer start plans, filterable by flow and status | FabPlanner, ProcessEngineer, QualityManager, YieldEngineer, EquipmentEngineer |
| GET | `/fab/wafer-start-plans/{id}` | Read one wafer start plan | FabPlanner, ProcessEngineer, QualityManager, YieldEngineer, EquipmentEngineer |
| POST | `/fab/wafer-start-plans/{id}/commit` | Commit a draft plan through the utilisation tier ladder | FabPlanner |
| POST | `/fab/lots` | Create a PLANNED production lot against a plan | FabPlanner |
| GET | `/fab/lots` | List lots, filterable by plan, flow, parent lot, holding excursion, hold state, flow state and priority | All roles |
| GET | `/fab/lots/{id}` | Read one lot | All roles |
| POST | `/fab/lots/{id}/release` | Release a planned lot, debiting the plan's authorised wafer starts | FabPlanner |
| POST | `/fab/lots/{id}/splits` | Carve an engineering split lot out of an in-fab lot | ProcessEngineer |
| POST | `/fab/lots/{id}/rejoin` | Fold an engineering split lot back into its parent | ProcessEngineer |
| POST | `/fab/lots/{id}/rework` | Rewind a lot held for rework back to its step's rework target | ProcessEngineer |
| GET | `/fab/lots/{id}/cycle-time-projection` | Forward-looking cycle time projection for a released lot | FabPlanner, ProcessEngineer, QualityManager, YieldEngineer |
| POST | `/fab/step-runs` | Track a lot into its next step; the server selects the chamber | Operator |
| GET | `/fab/step-runs` | List step runs, filterable by lot, step, chamber, operator and status | All roles |
| GET | `/fab/step-runs/{id}` | Read one step run | All roles |
| POST | `/fab/step-runs/{id}/track-out` | Complete an open step run, charging actual hours to the tool ledger | Operator |
| POST | `/fab/step-runs/{id}/abort` | Abort an open step run, crediting the full reservation back | Operator |
| POST | `/fab/measurements` | Record an in-line metrology reading against an SPC chart on an open run | Operator |
| GET | `/fab/measurements` | List metrology measurements, filterable by run, chart, excursion and classification | Operator, ProcessEngineer, QualityManager, YieldEngineer |
| GET | `/fab/measurements/{id}` | Read one metrology measurement | Operator, ProcessEngineer, QualityManager, YieldEngineer |
| GET | `/fab/excursions` | List excursions, filterable by each polymorphic source pointer, lot, source type and status | QualityManager, YieldEngineer, ProcessEngineer, EquipmentEngineer, FabPlanner |
| GET | `/fab/excursions/{id}` | Read one excursion | QualityManager, YieldEngineer, ProcessEngineer, EquipmentEngineer, FabPlanner |
| POST | `/fab/excursions/{id}/contain` | Contain an SPC- or die-sort-sourced excursion at a chosen blast radius | QualityManager |
| POST | `/fab/excursions/{id}/disposition` | Disposition a contained excursion | QualityManager, YieldEngineer |
| POST | `/fab/die-sort-runs` | Record wafer-map sort results for a lot at sort | YieldEngineer |
| GET | `/fab/die-sort-runs` | List die sort runs, filterable by lot, status and dominant signature | YieldEngineer, ProcessEngineer, QualityManager, FabPlanner |
| GET | `/fab/die-sort-runs/{id}` | Read one die sort run | YieldEngineer, ProcessEngineer, QualityManager, FabPlanner |
| POST | `/fab/die-sort-runs/{id}/bin` | Allocate good die to speed grades and complete the lot | YieldEngineer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PROCESS_FLOW_NOT_FOUND` | 404 |
| `ERR_PROCESS_STEP_NOT_FOUND` | 404 |
| `ERR_RECIPE_NOT_FOUND` | 404 |
| `ERR_CHANGE_REQUEST_NOT_FOUND` | 404 |
| `ERR_EQUIPMENT_NOT_FOUND` | 404 |
| `ERR_CHAMBER_NOT_FOUND` | 404 |
| `ERR_OPERATOR_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_STEP_RUN_NOT_FOUND` | 404 |
| `ERR_SPC_CHART_NOT_FOUND` | 404 |
| `ERR_EXCURSION_NOT_FOUND` | 404 |
| `ERR_SORT_RUN_NOT_FOUND` | 404 |
| `ERR_OPERATOR_IDENTITY_MISMATCH` | 403 |
| `ERR_SOD_SELF_APPROVAL` | 409 |
| `ERR_SOD_SELF_DISPOSITION` | 409 |
| `ERR_STALE_PLAN_VERSION` | 412 |
| `ERR_STALE_RECIPE_VERSION` | 412 |
| `ERR_STALE_LOT_VERSION` | 412 |
| `ERR_FLOW_NOT_DRAFT` | 409 |
| `ERR_FLOW_NOT_RELEASED` | 409 |
| `ERR_FLOW_HAS_NO_STEPS` | 422 |
| `ERR_PLAN_ALREADY_COMMITTED` | 409 |
| `ERR_PLAN_NOT_COMMITTED` | 409 |
| `ERR_LOT_INVALID_STATE` | 409 |
| `ERR_LOT_ON_HOLD` | 409 |
| `ERR_CHANGE_REQUEST_INVALID_STATE` | 409 |
| `ERR_EXCURSION_INVALID_STATE` | 409 |
| `ERR_STEP_RUN_NOT_OPEN` | 409 |
| `ERR_SORT_RUN_ALREADY_BINNED` | 409 |
| `ERR_EQUIPMENT_NOT_IN_PM` | 409 |
| `ERR_EQUIPMENT_INVALID_STATE` | 409 |
| `ERR_EQUIPMENT_DOWN` | 409 |
| `ERR_SPC_CHART_SUSPENDED` | 409 |
| `ERR_RECIPE_RESTRICTED` | 409 |
| `ERR_PINNED_REVISION_STALE` | 409 |
| `ERR_OPERATOR_CERT_INACTIVE` | 403 |
| `ERR_OPERATOR_NOT_GOWNED` | 403 |
| `ERR_OPERATOR_NOT_CERTIFIED` | 403 |
| `ERR_STEP_FLOW_MISMATCH` | 422 |
| `ERR_STEP_SEQUENCE_VIOLATION` | 422 |
| `ERR_CHART_STEP_MISMATCH` | 422 |
| `ERR_METROLOGY_NOT_REQUIRED` | 422 |
| `ERR_METROLOGY_MISSING` | 409 |
| `ERR_PRODUCT_FAMILY_MISMATCH` | 422 |
| `ERR_REWORK_TARGET_NOT_SET` | 422 |
| `ERR_NOT_A_SPLIT_LOT` | 422 |
| `ERR_PM_PURGE_ACTIVE` | 409 |
| `ERR_CHAMBER_QUAL_EXPIRED` | 409 |
| `ERR_NO_QUALIFIED_CHAMBER` | 409 |
| `ERR_CHAMBER_INVALID_QUAL_STATE` | 409 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_INVALID_SPLIT_QUANTITY` | 422 |
| `ERR_REWORK_LIMIT_EXCEEDED` | 409 |
| `ERR_WAFER_RESULT_INCONSISTENT` | 422 |
| `ERR_PLAN_STARTS_EXCEEDED` | 409 |
| `ERR_CAPACITY_BUDGET_EXCEEDED` | 409 |
| `ERR_EQUIPMENT_CAPACITY_EXHAUSTED` | 409 |
