# Gardenia Community Garden - Product Requirements Document

## 1. Gardenia Community Garden

This document outlines the requirements for the Gardenia Community Garden API, a comprehensive system designed to orchestrate the complex ecological and resource management challenges of community-driven gardening. It provides the necessary facilities for creating seasonal garden plans, scheduling planting tasks, managing plot assignments, and maintaining the delicate balance between resource consumption and ecological health throughout the growing season.

## 2. Global Specifications

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1 Authentication & User Context

User context is determined by two mandatory HTTP request headers for all endpoints:

* `X-User-ID`: (string) The unique identifier of the user making the request. This ID is used for authorization checks and data association.
* `X-User-Role`: (string) The role assigned to the user. Must be one of the following values: `GardenManager`, `Gardener`, `BillingAdmin`.

Failure to provide these headers will result in a `400 Bad Request` with `error_id: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.

While endpoint access is open, actions are restricted by user role. If a user attempts to perform an action not permitted for their role (e.g., a `Gardener` attempting to activate a plan), the API will respond with a `403 Forbidden` error with an `error_id` of `ERR_INSUFFICIENT_PERMISSIONS`.

### 2.2 Standard API Response Formats

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "object" | "array",
  "data": {}
}
```

* The `api_request_id` is a server-generated unique identifier for the request, designed to facilitate logging and traceability, that begins with the prefix 'req_' followed by alphanumeric characters.
* The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
* The `response_type` is either "object" for a single resource or "array" for a list of resources.
* The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object.

In adherence to data consistency principles, unique identifiers such as plan IDs are formatted as UUIDs.

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

* The `error_id` is a unique, machine-readable string that identifies the specific error.
* The `message` provides a human-readable explanation of what went wrong.

### 2.3 Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. In our approach to balancing comprehensive data delivery with performance considerations, clients can specify a `limit` parameter, an integer that, when not provided, defaults to a value of 10, with allowable ranges bounded between a minimum of 1 and a maximum of 100 to prevent overload. The number of initial items to skip is controlled by the `offset` parameter, an integer that, to support sequential data retrieval without gaps, defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

Ordering principles for determinism in processes like harvesting involve sorting chronologically by task start date, followed by assignment ID.

## 3. Business Logic & Workflows

### 3.1 The Garden Plan Lifecycle

The foundational resource in the system is the **Garden Plan**. It represents a complete seasonal gardening initiative and serves as the container for all other resources. A new plan is initiated by a `GardenManager` with a `plan_name` and a `total_water_credits` allocation. Upon creation, the system automatically generates a unique `id` according to the identifier standards defined in Section 2.2., timestamps for `created_at` and `updated_at`, and sets the initial `status` to `PLANNING`. The plan's water resource state is tracked via a read-only equilibrium indicator called `water_credits_balance`, and its ecological stability is monitored by a read-only metric labeled `pest_risk_score`, both of which are derived from their respective ledgers.

A plan must be transitioned from `PLANNING` to `ACTIVE` before any planting work can be scheduled. This is a deliberate action signifying that the planning phase is complete. An attempt to activate a plan not in the appropriate state will result in a `409 Conflict` error with `ERR_PLAN_NOT_IN_PLANNING`. Any attempt to create a Planting Season or Planting Task while the plan is not `ACTIVE` will result in a `409 Conflict` with the error `ERR_PLAN_NOT_ACTIVE`. Once a plan is `ACTIVE`, `Gardener`s can begin defining the phases of work.

As part of the broader water conservation initiative, each plan begins with a base allocation for each plot, set at 100 liters, which represents the standard sustainable usage before drought surcharges apply. When water usage exceeds this threshold for any plot, the system considers the plot to be experiencing water stress, which has both financial and ecological implications as detailed in subsequent sections.

When all planting work is complete and all Task Assignments (see Section 3.3) have been finalized (i.e., are not in a pending proposal phase or approved commitment stage), the plan can be moved by a `GardenManager` to `HARVESTING_PENDING`. This state transition is only possible if closure prerequisites are met; otherwise, the system will reject the request with a `409 Conflict` and an `ERR_UNRESOLVED_ASSIGNMENTS_EXIST` error. The final lifecycle step, managed by a `BillingAdmin`, is to generate the harvest report, which moves the plan to its terminal `CLOSED` state.

Upon the establishment of a garden plan, to establish a clean financial slate, both provisional and finalized debits in the water credit ledger are set to an initial value of 0.0. Similarly, the pest risk score begins at an optimal level of 0 points, providing a baseline from which ecological deviations are measured.

### 3.2 Structuring the Season: Planting Seasons and Tasks

A Garden Plan is broken down into one or more **Planting Seasons**. Each season represents a major phase of the garden's lifecycle, such as "Spring Planting" or "Fall Harvest Prep." A `Gardener` defines a Planting Season with a `name`, a reference to its parent `plan_id`, and its timeline is bounded by a `start_date` and `end_date`, both represented as day of year integers (1-366) to ensure consistency in seasonal planning, where the `end_date` must be strictly after the `start_date`. If the end date is not after the start date, the server will respond with a `400 Bad Request` and an `ERR_INVALID_SEASON_DATES` error. The season's `status` begins in `PLANNING` and can transition to `READY_FOR_PLANTING` or the terminal `CANCELLED` state. An attempt to perform an invalid state transition will result in a `409 Conflict` with an error as per the state machine governance.

Within each Planting Season, specific cultivation activities are defined by a `Gardener` as **Planting Tasks**. A task represents a discrete unit of work, like planting "Roma Tomato" or "Butternut Squash", identified by its `plant_type`. Each task maintains references to its parent `season_id` and `plan_id`, tracks its botanical heritage through a `plant_family` field which plays a crucial role in crop rotation policies, and has a `start_date` and `end_date`, where the `end_date` must be strictly after the `start_date`. Failure to provide a valid end time will result in a `400 Bad Request` with an `ERR_INVALID_TASK_DATES` error. Tasks can specify a `required_amendment` to indicate special soil preparation needs. The value must be one of `ACIDIC_SOIL`, `FUNGICIDE_TREATED`, or `NONE`. If no special amendment is needed, the value is `NONE`. If the `required_amendment` is omitted on creation, it defaults to `NONE`. A task's `status` begins as `PENDING` and can transition through `APPROVED` and `SCHEDULED` states, with `CANCELLED` as a terminal state. A task can only be cancelled directly by a `Gardener` if it is in the `PENDING` state, preventing disruption of scheduled work.

Each planting task carries with it a `water_requirement_liters` field, representing the total volume of water expected to be consumed over the task's duration. This value is critical for resource planning and directly impacts both the financial cost calculations and ecological risk assessments when the task is assigned to a plot.

To be moved to `READY_FOR_PLANTING`, a season must represent a meaningful phase of work with all its child tasks in the `SCHEDULED` state. If an assignment is cancelled and the parent season is in `READY_FOR_PLANTING` state, it will be automatically downgraded back to `PLANNING`. Similarly, trying to move a season to `READY_FOR_PLANTING` when readiness criteria are not met will cause a `409 Conflict` with `ERR_TASKS_NOT_SCHEDULED`. A season can also be directly cancelled from either `PLANNING` or `READY_FOR_PLANTING` states, transitioning to a terminal `CANCELLED` state, which, in preserving resource hierarchy integrity, triggers a cascade effect on all descendant elements such as tasks and their associated assignments, leading to their cancellation as elaborated in subsequent sections.

### 3.3 The Assignment Process: Garden Plots and Task Assignments

Work is performed on **Garden Plots**, which are defined by a `Gardener`. Each plot represents a physical cultivation space and is characterized by a `plot_name`, its `plot_size_sqm` (in square meters), its `water_credits_per_liter` rate, and a reference to its parent `plan_id`. A plot can have one or more `applied_amendments` added to it by a `Gardener`, structured as a list where each amendment has a unique `id`, a `name` which must be one of the enumerated values (`ACIDIC_SOIL` or `FUNGICIDE_TREATED`), and an `applied_date`. These amendments correspond to the `required_amendment` on a PlantingTask. Plots also maintain a `last_task_family` field, which records the botanical family of the most recently completed (billed) task on that plot, enabling the enforcement of crop rotation policies.

In recognition of companion planting principles and pest management strategies, plots can be designated as incompatible with one another through a list of `incompatible_plot_ids`. This field, manageable by a `GardenManager`, contains references to other plots that should not host concurrent plantings due to pest-attracting combinations. A plot cannot be marked as incompatible with itself, as this would create a logical impossibility.

The critical link between a cultivation activity and a physical space is the **Task Assignment**. An assignment is a proposal, initiated by a `Gardener`, to allocate a specific Planting Task to a compatible Garden Plot. The request body requires a `task_id`, a `plot_id`, and an optional `override_pest_check` boolean flag. Creating an assignment is a multi-step process governed by a strict validation sequence. First, a proposal is made, but only if the task is in the `PENDING` state; any attempt to assign a task not in this state will be rejected with an error.

The system's first responsibility is to ensure basic agricultural compatibility. It validates that the selected Garden Plot possesses the correct soil amendments to match the task's `required_amendment`. A mismatch, which could compromise plant health, results in a `400 Bad Request` (`ERR_AMENDMENT_MISMATCH`), halting further checks. Only after confirming this alignment does the system evaluate ecological constraints. It enforces the crop rotation policy (see Section 3.5) to prevent soil depletion. A violation of this principle will cause a `409 Conflict` with an `ERR_CROP_ROTATION_VIOLATION` error.

With agricultural safety assured, the system then assesses companion planting rules. It verifies that the assignment would not violate any plot incompatibilities that prevent specific plots from hosting plants in the same season. This check examines all existing assignments within the same planting season that are in non-terminal states (`PENDING`, `APPROVED`, `SCHEDULED`, or `BILLED`). A violation results in a `409 Conflict` (`ERR_PLOT_INCOMPATIBILITY`). Following these structural checks, the focus shifts to ecological and resource viability. The system evaluates the assignment's impact on the garden's pest risk score, calculating whether the plot would enter a state of water stress, which occurs when cumulative water usage exceeds the base allocation described in Section 3.1. If the assignment would cause water stress and this would push the pest risk score to or above a critical threshold of 500 points, the assignment is rejected with a `403 Forbidden` error unless the gardener has explicitly set the `override_pest_check` flag to bypass this safety mechanism. Finally, once all other checks have passed, the system validates the financial impact. If the calculated `provisional_credits` exceeds the plan's available water credit balance, the proposal is rejected with a `402 Payment Required` error (`ERR_INSUFFICIENT_WATER_CREDITS`).

Upon successful proposal, a Task Assignment is created with a status of `PENDING`, and the associated Planting Task is moved to `APPROVED`. The system calculates a `provisional_credits` cost for the assignment, an estimate that accurately reflects the water consumption. This calculation considers the task's water requirements and incorporates the potential for a drought surcharge related to water stress conditions, the rules for which are detailed in the ecological management principles. To provide an accurate upfront cost estimate, this calculation considers the cumulative water usage for the target Garden Plot, including usage from other assignments that are also in the `PENDING`, `APPROVED`, or `SCHEDULED` state. An assignment is marked with `is_water_stressed` as true if the cumulative water usage for its plot would exceed the standard allocation. This `provisional_credits` amount is provisionally debited from the plan's water credit balance. If the assignment is determined to cause water stress, a penalty of 50 points is immediately applied to the pest risk score. Additionally, if the `override_pest_check` flag was used to bypass the ecological safety check when the threshold would have been breached, an additional penalty of 100 points is assessed, and this fact is immutably recorded in the assignment's `pest_check_override_penalty_applied` field.

A proposed assignment must be approved by a `GardenManager`, moving its status to `APPROVED`. Alternatively, it can be rejected, transitioning it to `REJECTED` and reverting the task to `PENDING`. This rejection also reverses any provisional costs debited from the water credit tracking mechanism and restores any pest risk penalties that were applied when the assignment was proposed. This action is only valid for an assignment in the `PENDING` state; otherwise, the system returns an error. An approved assignment can then be scheduled by a `GardenManager`, which transitions it to `SCHEDULED` and the Planting Task to `SCHEDULED`. This requires the assignment to be in the `APPROVED` state (otherwise `ERR_ASSIGNMENT_NOT_APPROVED`) and the associated task to be `APPROVED` (otherwise `ERR_TASK_NOT_APPROVED`), with failures returning a `409 Conflict`. The successful scheduling of all of a season's child Planting Tasks is a crucial prerequisite for the season itself to be transitioned to the `READY_FOR_PLANTING` state. During this schedule operation, the system performs another crop rotation validation to ensure conditions haven't changed. It also recalculates the water credit cost based on the current committed water usage from assignments in `APPROVED` or `SCHEDULED` state only. If the new cost would increase and push the plan over its water credit budget, the schedule operation fails with an error. This final confirmation may involve a re-calculation of the `provisional_credits` and `is_water_stressed` flag based on other recently scheduled assignments. If the assignment transitions from non-stressed to stressed, the water stress penalty is applied; if it transitions from stressed to non-stressed, the previously applied penalty is reversed. These changes affect the plan's water credits and pest risk score accordingly. An assignment can be cancelled by a `GardenManager` from `PENDING`, `APPROVED`, or `SCHEDULED` states, which reverts the associated task to `PENDING`, with the system meticulously tracking and reversing all pest risk score modifications that occurred during the assignment's lifecycle, including water stress penalties that were assessed at proposal or subsequent state transitions, as well as any pest check override penalties if the `pest_check_override_penalty_applied` flag indicates such a penalty was levied. Attempting to cancel an assignment in a terminal state will result in an error. To ensure process closure, states such as BILLED for completed harvesting, REJECTED for denied proposals, and CANCELLED for aborted assignments are considered terminal and cannot transition further, maintaining the integrity of the workflow.

The financial implications of water stress are significant: when a plot's cumulative water consumption exceeds the base allocation, any additional water usage is charged at a rate multiplied by a drought surcharge factor of 1.5x the standard `water_credits_per_liter` rate for that plot. This incentivizes efficient water use and reflects the true ecological cost of overconsumption.

### 3.4 Managing Risk: The Pest Risk Score and Overrides

The ecological risk profile of a Garden Plan is tracked through a pest risk metric that serves as a key indicator for managing garden health. Unlike traditional health metrics that start high and deplete, this score begins at a perfect 0 and increases with penalties for actions that deviate from best practices. A lower score indicates better ecological health.

One of the most significant rules is the pest risk threshold lock. If the plan's pest risk score would reach or exceed 500 points after applying penalties for a new water-stressed assignment, the system will reject the proposal. However, in critical situations where planting must proceed despite ecological risks, a `Gardener` can set the `override_pest_check` flag to `true` when proposing an assignment. The `override_pest_check` flag adheres to immutability principles for critical flags. This bypasses the pest risk check, but if the bypass is used when the threshold would have been breached by water stress penalties, it results in a significant penalty to the pest risk score. The fact that an override was used is recorded immutably on the assignment in the `override_pest_check` field, and the application of the penalty is noted in the `pest_check_override_penalty_applied` flag.

The penalties applied to the pest risk score reflect the severity of ecological transgressions. Water-stressed plots incur a 50-point penalty that increases the risk score, acknowledging that over-watered areas are more susceptible to pest infestations and disease. When the override mechanism is employed to bypass safety thresholds, an additional substantial 100-point penalty is assessed, underscoring the gravity of such decisions in ecological management.

### 3.5 Agricultural Principles and Crop Rotation

Central to the garden's long-term health is the enforcement of crop rotation policies. The system maintains careful records of planting history for each plot through the `last_task_family` field. This botanical lineage tracking ensures that consecutive plantings from the same plant family cannot occur on the same plot, a practice essential for preventing soil depletion and pest buildup.

When an assignment reaches its final `BILLED` state during the harvest process, the system updates the plot's `last_task_family` to reflect the completed planting. This creates a historical record that influences future planting decisions. Any attempt to assign a task whose `plant_family` matches the plot's `last_task_family` will be rejected with a crop rotation violation error, protecting the garden's long-term productivity.

The companion planting system works in concert with these rotation policies. By maintaining lists of incompatible plot combinations, the garden can avoid problematic plant pairings that might attract pests or compete for resources. These incompatibilities are evaluated at the season level, ensuring that conflicting plants are not grown simultaneously in adjacent or otherwise incompatible plots.

### 3.6 Finalization and Harvest Reporting

The culmination of a Garden Plan is the generation of a final harvest report. This action can only be performed when the plan is in the `HARVESTING_PENDING` state. Any attempt to generate a report for a plan not in this state will result in an error. The system performs a transactional calculation of all Task Assignments in the `SCHEDULED` stage. It sorts them according to the chronological ordering principles based on task start dates and assignment IDs for determinism. For each assignment, it calculates the `final_credits` cost, maintaining a running tally of cumulative water usage per Garden Plot to accurately apply drought surcharges where applicable based on these cumulative totals. This final calculation also reconciles the plan's pest risk score. If an assignment that was provisionally marked as water-stressed is determined not to have caused water stress in the final calculation (e.g., due to other tasks being cancelled), its associated penalty is reversed. Conversely, a penalty is applied if an assignment becomes water-stressed only during finalization. For each billed assignment, its final cost is added to the `finalized_debits` on the Water Credit Ledger, and its original provisional cost is subtracted from the `provisional_debits`. If the total final cost exceeds the plan's `total_water_credits`, the entire transaction is rolled back and an appropriate error is returned. Otherwise, the transaction is committed, all assignments are moved to the `BILLED` state, each plot's `last_task_family` is updated to reflect the botanical family of its completed task, and the plan itself is transitioned to `CLOSED`. Upon successful commitment, the provisional reservations on the Water Credit Ledger are explicitly set to 0.0 to ensure no residual balance remains.

The water credit calculations during harvest follow a precise methodology: for each plot, usage is accumulated in the order of task start dates, with the standard allocation of 100 liters consumed first before any drought surcharges apply. This ensures fair and predictable billing while maintaining the ecological incentives for water conservation.

## 4. Endpoint Definitions

All successful creation operations return 201 Created, while other successful operations return 200 OK.

### 4.1 Garden Plan Endpoints

* **POST /garden-plans**: Create a new Garden Plan.
* **GET /garden-plans**: List all Garden Plans.
* **GET /garden-plans/{planId}**: Get a specific Garden Plan.
* **POST /garden-plans/{planId}/activate**: Activate a plan, transitioning it from `PLANNING` to `ACTIVE`.
* **POST /garden-plans/{planId}/initiate-harvest**: Move a plan to the `HARVESTING_PENDING` state.
* **POST /garden-plans/{planId}/generate-harvest-report**: Finalize credit costs, bill assignments, and close the plan.

### 4.2 Planting Season Endpoints

* **POST /garden-plans/{planId}/planting-seasons**: Create a new Planting Season within a Plan.
* **GET /garden-plans/{planId}/planting-seasons**: List Planting Seasons for a Plan.
* **GET /garden-plans/{planId}/planting-seasons/{seasonId}**: Get a specific Planting Season.
* **PUT /garden-plans/{planId}/planting-seasons/{seasonId}**: Update a Planting Season's status.

### 4.3 Planting Task Endpoints

* **POST /garden-plans/{planId}/planting-seasons/{seasonId}/planting-tasks**: Create a new Planting Task for a Season.
* **GET /garden-plans/{planId}/planting-seasons/{seasonId}/planting-tasks**: List Planting Tasks for a Season.
* **GET /garden-plans/{planId}/planting-seasons/{seasonId}/planting-tasks/{taskId}**: Get a specific Planting Task.
* **POST /garden-plans/{planId}/planting-seasons/{seasonId}/planting-tasks/{taskId}/cancel**: Cancel a specific Planting Task.

### 4.4 Garden Plot Endpoints

* **POST /garden-plans/{planId}/garden-plots**: Create a new Garden Plot profile for a Plan.
* **GET /garden-plans/{planId}/garden-plots**: List Garden Plot profiles for a Plan.
* **GET /garden-plans/{planId}/garden-plots/{plotId}**: Get a specific Garden Plot profile.
* **POST /garden-plans/{planId}/garden-plots/{plotId}/amendments**: Add a soil amendment to a garden plot.
* **POST /garden-plans/{planId}/garden-plots/{plotId}/incompatibilities**: Set the list of incompatible plots for a given plot.

### 4.5 Task Assignment Endpoints

* **POST /garden-plans/{planId}/task-assignments**: Propose a new plot assignment for a Planting Task.
* **GET /garden-plans/{planId}/task-assignments**: List all Task Assignments for a Plan.
* **GET /garden-plans/{planId}/task-assignments/{assignmentId}**: Get a specific Task Assignment.
* **POST /garden-plans/{planId}/task-assignments/{assignmentId}/approve**: Approve a proposed Assignment.
* **POST /garden-plans/{planId}/task-assignments/{assignmentId}/schedule**: Schedule an approved Task.
* **POST /garden-plans/{planId}/task-assignments/{assignmentId}/reject**: Reject a proposed Assignment.
* **POST /garden-plans/{planId}/task-assignments/{assignmentId}/cancel**: Cancel a Task Assignment.

## 5. Error Code Catalogue

| Error ID                           | HTTP Status Code |
| :--------------------------------- | :--------------- |
| `ERR_PLAN_NOT_FOUND`              | 404 Not Found    |
| `ERR_PLOT_NOT_FOUND`              | 404 Not Found    |
| `ERR_INCOMPATIBLE_PLOT_NOT_FOUND` | 404 Not Found    |
| `ERR_SELF_INCOMPATIBILITY`        | 400 Bad Request  |
| `ERR_TASK_NOT_FOUND`              | 404 Not Found    |
| `ERR_TASK_NOT_PENDING_FOR_CANCEL` | 409 Conflict     |
| `ERR_PLAN_NOT_ACTIVE`             | 409 Conflict     |
| `ERR_INVALID_SEASON_DATES`        | 400 Bad Request  |
| `ERR_SEASON_NOT_FOUND`            | 404 Not Found    |
| `ERR_INVALID_TASK_DATES`          | 400 Bad Request  |
| `ERR_TASK_NOT_PENDING`            | 409 Conflict     |
| `ERR_AMENDMENT_MISMATCH`          | 400 Bad Request  |
| `ERR_CROP_ROTATION_VIOLATION`     | 409 Conflict     |
| `ERR_PLOT_INCOMPATIBILITY`        | 409 Conflict     |
| `ERR_PEST_RISK_THRESHOLD_BREACHED`| 403 Forbidden    |
| `ERR_INSUFFICIENT_WATER_CREDITS`  | 402 Payment Required |
| `ERR_ASSIGNMENT_NOT_FOUND`        | 404 Not Found    |
| `ERR_ASSIGNMENT_NOT_PENDING`      | 409 Conflict     |
| `ERR_ASSIGNMENT_NOT_APPROVED`     | 409 Conflict     |
| `ERR_TASK_NOT_APPROVED`           | 409 Conflict     |
| `ERR_ILLEGAL_SEASON_STATE_TRANSITION` | 409 Conflict |
| `ERR_TASKS_NOT_SCHEDULED`         | 409 Conflict     |
| `ERR_PLAN_NOT_READY_FOR_HARVEST`  | 409 Conflict     |
| `ERR_HARVEST_EXCEEDS_CREDITS`     | 402 Payment Required |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE`  | 409 Conflict     |
| `ERR_UNRESOLVED_ASSIGNMENTS_EXIST`| 409 Conflict     |
| `ERR_PLAN_NOT_IN_PLANNING`        | 409 Conflict     |
| `ERR_INVALID_REQUEST`             | 400 Bad Request  |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS`    | 403 Forbidden    |