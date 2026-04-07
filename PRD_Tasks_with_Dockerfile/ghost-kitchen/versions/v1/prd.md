# Ghost Kitchen - Product Requirements Document

## 1. Ghost Kitchen

This document outlines the requirements for the Ghost Kitchen API, a system designed to manage the scheduling, execution, and monitoring of complex, automated food preparation for delivery. The platform orchestrates a fleet of robotic cooking stations to perform multi-step recipes, while managing resource allocation, enforcing food safety protocols, tracking costs, and ensuring the quality of every meal.

## 2. Global Specifications

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1 Authentication & User Context

User context is determined by two mandatory HTTP request headers for all endpoints:

*   `X-User-ID`: (string) The unique identifier of the user making the request. This ID is used for authorization checks and data association.
*   `X-User-Role`: (string) The role assigned to the user. Must be one of the following values: `HeadChef`, `Operator`.

Failure to provide these headers will result in a `400 Bad Request` with `error_id: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.

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
  "data": { }
}
```

*   The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
*   The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with 3 decimal places.
*   The `response_type` is either "object" for a single resource or "array" for a list of resources.
*   The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object.

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

*   The `error_id` is a unique, machine-readable string that identifies the specific error.
*   The `message` provides a human-readable explanation of what went wrong.

### 2.3 Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. In our approach to balancing comprehensive data delivery with performance considerations, clients can specify a `limit` parameter, an integer that, when not provided, defaults to a value of 10, with allowable ranges bounded between a minimum of 1 and a maximum of 100 to prevent overload. The number of initial items to skip is controlled by the `offset` parameter, an integer that, to support sequential data retrieval without gaps, defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4 Data Scoping & Isolation

The fundamental unit of data isolation is the **Meal Order**. All resources, including recipes, cooking steps, cooking stations, and their associated task executions and safety protocols, are scoped to a single, parent `MealOrder`. An entity created within one order is not visible or accessible from another. While write operations are often restricted by an order's lifecycle status, read-only access to an order and its child resources (e.g., recipes, steps) via GET endpoints is always permitted, regardless of the order's status.

Every endpoint that references a specific resource (via path parameters such as `{orderId}`, `{recipeId}`, `{stepId}`, `{stationId}`, `{recordId}`, or `{protocolId}`) must first verify that the target resource exists and, for child resources, belongs to the specified parent `MealOrder`. If a resource does not exist or does not belong to the correct order hierarchy, the API returns a `404 Not Found` with the appropriate error code from the catalogue in Section 5 (e.g., `ERR_ORDER_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`, `ERR_STEP_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, or `ERR_PROTOCOL_NOT_FOUND`). This validation applies to both read (GET) and action (POST, PUT) endpoints.

### 2.5 Core Systems

The platform operates on two primary background ledger systems that track the state and quality of each `MealOrder`.

*   **Food Cost Ledger:** This financial ledger tracks all ingredient and energy costs against the order's total payment. It maintains a running total of both `provisional_debits` from scheduled work and `finalized_debits` from completed work. The order's `cost_balance` is a read-only field derived directly and automatically from this ledger.
*   **Food Quality Score:** This compliance ledger maintains a score representing deviations from ideal food quality during preparation. The score begins at a perfect 0 and is incremented when actions are taken that could introduce quality issues, such as rushing the cooking process or overriding a quality check. A lower score is better. The order's `food_quality_score` is a read-only field that is a direct, automatically synchronized reflection of this ledger's current value.

### 2.6 System Invariants

The following rules are fundamental, system-wide constraints that govern the behavior of all kitchen operations.

*   **Station Cleaning Protocol:** To ensure food safety and prevent flavor contamination, a mandatory cleaning period must be observed for any given `CookingStation`. The system enforces a minimum gap of **15 minutes** between the end time of one `CookingStep` and the start time of another on the same station within a single `MealOrder`. This is referred to as the `CLEANING_CYCLE_MINUTES`. This check uses the absolute time difference to prevent scheduling steps too closely together, regardless of their chronological order.
*   **Rushed Order Thresholds:** While stations are designed for rapid cooking, proper food preparation requires adequate time for ingredients to thaw and be prepped. Within any given `MealOrder`, there is a `MINIMUM_THAW_TIME_HOURS` of **1 hour**. Any `CookingStep` scheduled to start *before* this minimum time has passed since the `MealOrder` was created is classified as a "Rushed Order." Work performed under these conditions incurs a `RUSHED_RATE_MULTIPLIER` of **1.5** times the standard cost, and also applies a penalty to the `FoodQualityScore` as detailed later.
*   **Food Quality Lock:** To safeguard the quality of the final product, the system imposes a hard limit on rushed procedures. If an order's `FoodQualityScore` (as described in Section 2.5) reaches or exceeds a value of **100**, the system enters a `FOOD_QUALITY_LOCK`. While in this state, no new `CookingStep` that would be classified as a Rushed Order can be scheduled unless a manual override is explicitly provided by a user with the `HeadChef` role.
*   **Food Quality Penalties:** Specific actions incur penalties that increase the `FoodQualityScore` (where a lower score is better):
    *   Scheduling work that qualifies as a Rushed Order results in a **20 point** penalty.
    *   Manually overriding the `FOOD_QUALITY_LOCK` (as described in Section 3.2.1) to force the scheduling of a task that would otherwise be blocked incurs a significant **40 point** penalty, reflecting the increased risk to food quality.

### 2.7 Standard Resource Attributes

Unless otherwise noted, all resources in the system share a set of common attributes.

*   **Identifiers:** All unique identifiers for resources (e.g., `id`, `orderId`, `recipeId`) are strings formatted as RFC 4122 (version 4) UUIDs.
*   **Timestamps:** All resources include `created_at` and `updated_at` fields. These are server-managed, read-only timestamps formatted as ISO 8601 UTC strings (e.g., `2025-05-24T10:30:00.123Z`). `created_at` is set upon resource creation, and `updated_at` is modified whenever the resource's state changes.

## 3. Business Logic & Workflows

### 3.1 Meal Order & Recipe Lifecycle Management

#### 3.1.1 The Meal Order

The lifecycle of any customer transaction is managed within a top-level **Meal Order**. This container is established by providing an `order_name` (e.g., "Order for Jane Doe") and the `total_payment` received for all associated items. Upon creation, the order is initialized with a `status` of `PREPARING`, and its associated `FoodCostLedger` and `FoodQualityScore` ledgers are created, as detailed in Section 2.5. The order's `cost_balance` is a read-only field initialized to match the `total_payment`, representing the remaining funds after all provisional and finalized costs are deducted; as such, it cannot exceed the `total_payment`. Its `food_quality_score` (also read-only) starts at 0.

An order must be transitioned to the `COOKING` state before any scheduling can commence. This is a deliberate action signifying that the customer's order is confirmed and preparation can begin. Once all cooking is finished and all task executions are resolved, the order can be moved to `QUALITY_CHECK_PENDING`. For the purpose of this transition, a task execution is considered "resolved" if it is in a terminal state (`REJECTED`, `CANCELLED`) or if it is `BOUND`. Records in other states (`PROPOSED`, `ACKNOWLEDGED`) are considered unresolved. The final step is to complete the order, which moves it to the `COMPLETE` state after performing final cost calculations.

#### 3.1.2 Recipes

Work is organized into one or more **Recipes**, which can only be created when the parent `MealOrder` is in the `COOKING` state. A recipe represents a single dish in the order, such as 'Deluxe Burger' or 'Caesar Salad', and includes a `meal_order_id` to link back to its parent order. Each recipe is defined with a `name`, and its preparation duration is bounded by a `start_time` and `end_time`, provided as Unix timestamps. The end time must be after the start time.

A recipe begins in a `PLANNING` status. It can only be transitioned to `READY_FOR_COOKING` when it has at least one associated `CookingStep` and all of its constituent `CookingStep`s (as defined in Section 3.2.1) have been fully assigned via a `BOUND` Task Execution. If an attempt is made to transition a recipe to `READY_FOR_COOKING` without meeting these criteria (either by having no steps or by having unassigned steps), the API must return a `409 Conflict` with the error `ERR_STEPS_NOT_ASSIGNED`. A recipe can be cancelled if it is in the `PLANNING` or `READY_FOR_COOKING` state; this action triggers a cascading cancellation of all its child steps and their associated task executions, ensuring any provisional costs and food quality penalties are reversed from the order's ledgers. Specifically, this reversal includes the 20-point rushed order penalty for any executions flagged as `is_rushed_order`, and the 40-point quality check override penalty for any executions where `quality_check_override_penalty_applied` is true. If a recipe that is `READY_FOR_COOKING` is altered in a way that breaks the readiness criteria (e.g., by cancelling a child step's assignment), it will automatically revert to the `PLANNING` state.

### 3.2 Cooking Step Scheduling & Execution

#### 3.2.1 Proposing a Task Execution

The core of the system is the scheduling of discrete cooking tasks. A **Cooking Step** represents a specific procedure, such as 'GrillPatty', to be performed, and it includes both a `meal_order_id` and a `recipe_id` for clear hierarchical linkage. Cooking Steps may only be created when the parent Meal Order is in the `COOKING` state; attempts to create steps while the order is in any other state will result in a `409 Conflict` with `ERR_ORDER_NOT_COOKING`. Each step is defined with a `task_type`, `start_time`, `end_time`, and may specify a `required_utensil` from an enumeration that includes `SPATULA_ATTACHMENT`, `WHISK_HEAD`, or `NONE` if no specific tool is needed. The `end_time` must be after the `start_time`; otherwise the creation fails with `ERR_INVALID_STEP_TIMES`. The duration of the step is also available as a read-only `duration_minutes` field, derived from its start and end times. A step is created in a `PENDING` state, and its status will transition through `SCHEDULED` and `ASSIGNED` as it is fulfilled, though it can also be terminated in a `CANCELLED` state.

A Task Execution can only be proposed if the parent MealOrder is in the `COOKING` state. Any attempt to do so while the order is in another state must be rejected with ERR_ORDER_NOT_COOKING. To execute a step, an operator proposes a **Task Execution**. This record is the critical link that assigns a specific `CookingStation` to a `CookingStep`. Creating this record requires a `cooking_step_id` and a `station_id`. The system will only accept the proposal if the target step is in the `PENDING` state. Upon a valid proposal, the task execution is created with a `status` of `PROPOSED`, and the corresponding `CookingStep` is transitioned to `SCHEDULED`.

A series of validations are performed upon proposal:
1.  **Utensil Compatibility:** The chosen `CookingStation` must possess the `required_utensil` specified by the `CookingStep`. A station's capabilities are defined in its `utensil_capabilities` list. An attempt to assign a step to a station without the necessary utensil will result in an `ERR_UTENSIL_MISMATCH` error.
2.  **Cleaning Cycle:** The proposed time slot must not violate the `CLEANING_CYCLE_MINUTES` invariant (as defined in Section 2.6) with respect to any other execution records for that station in a `PROPOSED`, `ACKNOWLEDGED`, `BOUND`, or `FINALIZED` state.
3.  **Food Safety:** The proposal is checked against all active `FoodSafetyProtocol`s (see Section 3.3.2). If the proposed station is part of a protocol, it cannot be scheduled for a step in the same `Recipe` as the other station in that protocol.
4.  **Cost & Quality:** The system calculates the `provisional_cost` of the operation, including any potential costs from being a Rushed Order (detailed in Section 2.6). If the operation qualifies as a Rushed Order, the system checks if applying the associated quality penalty would cause the `MealOrder`'s `FoodQualityScore` to meet or exceed the `FOOD_QUALITY_LOCK` threshold (see Section 2.6). If so, the proposal will be rejected unless the `override_quality_check` flag in the request is set to `true`. Only a user with the `HeadChef` role can use this flag; attempts by others will fail with `ERR_INSUFFICIENT_PRIVILEGES`. If this override is used to successfully schedule a task that would otherwise be blocked, the record is flagged with `quality_check_override_penalty_applied` as true, and the corresponding penalty from Section 2.6 is applied. Finally, the calculated `provisional_cost` is checked against the `cost_balance` of the parent `MealOrder`. If the cost exceeds the balance, the proposal is rejected with `ERR_INSUFFICIENT_FUNDS`.

If all checks pass, the execution record is created, its `provisional_cost` is added to the `provisional_debits` of the `FoodCostLedger`, and any applicable quality penalties are added to the `FoodQualityScore` ledger. This includes flagging the record with `is_rushed_order` if it qualifies.

#### 3.2.2 The Execution Lifecycle: Acknowledging and Binding

A `PROPOSED` task execution can be either acknowledged or rejected. Rejecting the proposal moves the record to a terminal `REJECTED` state, reverts the associated `CookingStep` to `PENDING`, and reverses any provisional costs and food quality penalties that were applied to the order's ledgers upon the record's creation. If the record does not exist, or does not belong to the order, or is not in the `PROPOSED` state, the rejection will fail with `ERR_RECORD_NOT_PROPOSED`. Acknowledging it transitions its status to `ACKNOWLEDGED`, a system or user action that confirms the initial validity of the proposal. Acknowledgement is only permitted when the record is in the `PROPOSED` state; otherwise the operation fails with `ERR_RECORD_NOT_PROPOSED`.

The final commitment step is to bind the record, which transitions it from `ACKNOWLEDGED` to `BOUND`; this action is only permitted if the record is in the `ACKNOWLEDGED` state and the associated `CookingStep` is in the `SCHEDULED` state. If the record is not `ACKNOWLEDGED`, the bind fails with `ERR_RECORD_NOT_ACKNOWLEDGED`; if the step is not `SCHEDULED`, it fails with `ERR_STEP_NOT_SCHEDULED`. This action triggers a comprehensive re-validation. The system re-checks the cleaning cycle against other committed records (`ACKNOWLEDGED`, `BOUND`, `FINALIZED`). It also re-calculates the `provisional_cost`, re-evaluating if the task qualifies as a Rushed Order at the time of binding. Any increase in provisional cost is checked against the order's remaining funds. If this creates a budget overrun, the bind will fail with `ERR_INSUFFICIENT_FUNDS`. Upon a successful bind, the record's `provisional_cost` and `is_rushed_order` fields are updated, any changes to cost or quality score are applied to the ledgers, and the associated `CookingStep` is moved to the `ASSIGNED` state.

A task execution can be cancelled from the `PROPOSED`, `ACKNOWLEDGED`, or `BOUND` states. Cancelling a record reverts the associated `CookingStep` to `PENDING`, and if the parent `Recipe` was `READY_FOR_COOKING`, it will be downgraded to `PLANNING`. The cancellation also triggers a full reversal of any financial or quality effects the record had on the system's ledgers.

#### 3.2.3 Finalization

When the `mark-order-complete` action is triggered on a `MealOrder` in the `QUALITY_CHECK_PENDING` state, all `BOUND` task executions undergo finalization. To ensure deterministic and fair cost calculation, the system processes these records in chronological order based on the `start_time` of their associated `CookingStep`. The system performs a final, transactional cost calculation for each record to determine its `final_cost`. Prior to this finalization step, the `final_cost` field for a task execution is `null`. During this process, the system also reconciles the `FoodQualityScore` by re-evaluating whether each task qualifies as a Rushed Order based on the order's creation time and the step's start time. If a task's rushed status has changed since it was bound, the corresponding 20-point penalty is either added to or subtracted from the `FoodQualityScore` ledger to maintain consistency. The total `finalized_debits` are calculated, and the entire operation will be rolled back if they exceed the `total_payment`. Upon success, each record's `provisional_cost` is subtracted from the `provisional_debits` ledger, while its newly calculated `final_cost` is added to the `finalized_debits` ledger. Finally, the entire `provisional_debits` ledger is cleared to `0.0`, and the task execution's status is set to `FINALIZED`.

### 3.3 Resource Management

#### 3.3.1 Cooking Stations

**Cooking Stations** are the physical robotic chefs that execute cooking steps. A profile for each station must be created within the scope of a `MealOrder`, and may only be created when the parent order is in the `COOKING` state. This profile includes a `station_name`, a `station_type` (e.g., 'RoboChef-5000'), and the standard `ingredient_and_energy_cost_per_minute` for its operation. The `provisional_cost` for a task is derived from this value using the formula: `provisional_cost = ingredient_and_energy_cost_per_minute * duration_minutes`. An operator can add to the station's `utensil_capabilities` list by providing the utensil's `name` (e.g., `SPATULA_ATTACHMENT`) and `installed_date`; the system will assign a unique `id` to the new capability record.

#### 3.3.2 Food Safety Protocols

To enforce critical food safety standards, an operator can create a **Food Safety Protocol**. This rule defines a pair of stations, identified by `station_id_1` and `station_id_2`, that are incompatible for use within the same recipe (e.g., to prevent cross-contamination of allergens). Both stations must exist and belong to the same `MealOrder`; otherwise the creation fails with `ERR_STATION_NOT_FOUND`. An optional `reason` field can be included for a private note. The existence of this rule prevents the system from scheduling both stations for `CookingStep`s that belong to the same `Recipe`, as described in Section 3.2.1. A station cannot have a safety protocol with itself.

## 4. Endpoint Definitions

All successful creation operations return 201 Created, while other successful operations return 200 OK.

### 4.1 MealOrder Endpoints

#### POST /meal-orders
Create a new Meal Order.

#### GET /meal-orders
List all Meal Orders.

#### GET /meal-orders/{orderId}
Get a specific Meal Order.

#### POST /meal-orders/{orderId}/begin-cooking
Begin cooking an order.

#### POST /meal-orders/{orderId}/finish-cooking
Move an order to the quality check pending state.

#### POST /meal-orders/{orderId}/mark-order-complete
Finalize costs, finalize task executions, and complete the order.

### 4.2 Recipe Endpoints

#### POST /meal-orders/{orderId}/recipes
Create a new Recipe within an Order.

#### GET /meal-orders/{orderId}/recipes
List Recipes for an Order.

#### GET /meal-orders/{orderId}/recipes/{recipeId}
Get a specific Recipe.

#### PUT /meal-orders/{orderId}/recipes/{recipeId}
Update a Recipe's status.

### 4.3 CookingStep Endpoints

#### POST /meal-orders/{orderId}/recipes/{recipeId}/cooking-steps
Create a new Cooking Step for a Recipe.

#### GET /meal-orders/{orderId}/recipes/{recipeId}/cooking-steps
List Cooking Steps for a Recipe.

#### GET /meal-orders/{orderId}/recipes/{recipeId}/cooking-steps/{stepId}
Get a specific Cooking Step.

### 4.4 TaskExecution Endpoints

#### POST /meal-orders/{orderId}/task-executions
Propose a new station execution for a Cooking Step.

#### GET /meal-orders/{orderId}/task-executions
List all Task Execution Records for an Order.

#### GET /meal-orders/{orderId}/task-executions/{recordId}
Get a specific Task Execution Record.

#### POST /meal-orders/{orderId}/task-executions/{recordId}/reject
(System/User) Reject a proposed Execution.

#### POST /meal-orders/{orderId}/task-executions/{recordId}/cancel
(Operator) Cancel a Task Execution.

#### POST /meal-orders/{orderId}/task-executions/{recordId}/acknowledge
(System/User) Acknowledge a proposed Execution.

#### POST /meal-orders/{orderId}/task-executions/{recordId}/bind
(Operator) Bind an acknowledged Cooking Step.

### 4.5 CookingStation Endpoints

#### POST /meal-orders/{orderId}/cooking-stations
Create a new Cooking Station profile for an Order.

#### GET /meal-orders/{orderId}/cooking-stations
List Cooking Station profiles for an Order.

#### GET /meal-orders/{orderId}/cooking-stations/{stationId}
Get a specific Cooking Station profile.

#### POST /meal-orders/{orderId}/cooking-stations/{stationId}/utensil-capabilities
Add a utensil capability to a Cooking Station.

### 4.6 FoodSafetyProtocol Endpoints

#### POST /meal-orders/{orderId}/food-safety-protocols
Create a Food Safety Protocol within an Order.

#### GET /meal-orders/{orderId}/food-safety-protocols
List Food Safety Protocols for an Order.

#### GET /meal-orders/{orderId}/food-safety-protocols/{protocolId}
Get a specific Food Safety Protocol.

## 5. Error Code Catalogue

| Error ID                               | HTTP Status Code        |
|:---------------------------------------|:------------------------|
| `ERR_ORDER_NOT_FOUND`                  | 404 Not Found           |
| `ERR_STATION_NOT_FOUND`                | 404 Not Found           |
| `ERR_SELF_EXCLUSION`                   | 400 Bad Request         |
| `ERR_ORDER_NOT_COOKING`                | 409 Conflict            |
| `ERR_INVALID_RECIPE_TIMES`             | 400 Bad Request         |
| `ERR_RECIPE_NOT_FOUND`                 | 404 Not Found           |
| `ERR_INVALID_STEP_TIMES`               | 400 Bad Request         |
| `ERR_STEP_NOT_FOUND`                   | 404 Not Found           |
| `ERR_INSUFFICIENT_PRIVILEGES`          | 403 Forbidden           |
| `ERR_STEP_NOT_PENDING`                 | 409 Conflict            |
| `ERR_UTENSIL_MISMATCH`                 | 400 Bad Request         |
| `ERR_CLEANING_CYCLE_VIOLATION`         | 409 Conflict            |
| `ERR_FOOD_SAFETY_VIOLATION`            | 409 Conflict            |
| `ERR_QUALITY_THRESHOLD_BREACHED`       | 403 Forbidden           |
| `ERR_INSUFFICIENT_FUNDS`               | 402 Payment Required    |
| `ERR_RECORD_NOT_FOUND`                 | 404 Not Found           |
| `ERR_RECORD_NOT_PROPOSED`              | 409 Conflict            |
| `ERR_RECORD_NOT_ACKNOWLEDGED`          | 409 Conflict            |
| `ERR_STEP_NOT_SCHEDULED`               | 409 Conflict            |
| `ERR_ILLEGAL_RECIPE_STATE_TRANSITION`  | 409 Conflict            |
| `ERR_STEPS_NOT_ASSIGNED`               | 409 Conflict            |
| `ERR_ORDER_NOT_READY_FOR_COMPLETION`   | 409 Conflict            |
| `ERR_FINALIZATION_EXCEEDS_PAYMENT`     | 402 Payment Required    |
| `ERR_RECORD_NOT_CANCELLABLE`           | 409 Conflict            |
| `ERR_UNRESOLVED_RECORDS_EXIST`         | 409 Conflict            |
| `ERR_ORDER_NOT_IN_PREPARING`           | 409 Conflict            |
| `ERR_PROTOCOL_NOT_FOUND`               | 404 Not Found           |
| `ERR_INVALID_PAYLOAD`                  | 400 Bad Request         |