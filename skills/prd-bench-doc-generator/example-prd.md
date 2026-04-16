# Hospital Shift Scheduling API - Product Requirements Document

## 1. Introduction

This document outlines the product requirements for the Hospital Shift Scheduling API. This system is designed to provide a robust framework for managing the allocation of critical medical resources against a backdrop of complex, interdependent clinical and financial constraints. The API governs the entire lifecycle of patient treatment scheduling, from initial planning and budgeting to the finalization of costs and procedures, ensuring that all operations adhere to strict safety, certification, and fiscal protocols.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes three distinct roles: `ChargeNurse`, `AttendingPhysician`, and `HospitalAdministrator`. Failure to provide valid headers will result in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error. Furthermore, access to specific operations is restricted by role. An attempt to perform an action outside of a user's designated role will be rejected with an `ERR_INSUFFICIENT_PERMISSIONS` error.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. System Integrity and Consistency

The system maintains strict integrity constraints across all hierarchical relationships. When a parent resource undergoes a state transition that renders it non-operational, the system ensures that all dependent child resources and their associated financial commitments are appropriately resolved to maintain overall consistency. Conversely, modifications to child resources that impact the criteria for a parent's current state must result in corresponding adjustments to the parent to uphold this hierarchical alignment. This principle applies throughout the resource hierarchy, from treatment plans down to individual assignments. For any operation involving nested resources, the system performs validations in a logical sequence: first confirming the existence and operational status of the parent plan, then verifying child resources within that context, before applying business-specific rules. This ordered approach ensures that invalid container states are caught early, preventing partial or misleading processing. To uphold these invariants, the server may transition parent or child resources automatically when criteria are satisfied or violated, without requiring an explicit client request on that specific resource. Each reconciliation independently mutates the parent resource, updating its updated_at and incrementing its version.

### 2.5. The Principle of Fiscal Responsibility

The system enforces strict management of financial resources. Every Treatment Plan is associated with a `CareBudgetLedger`. This ledger is the single source of truth for all financial transactions and triggers a reconciliation that updates the plan's `cost_balance` in real-time as events occur. It tracks funds that are provisionally committed via a `provisional_debits` account and funds that have been irrevocably spent via a `finalized_debits` account. The system guarantees that the integrity of this ledger is maintained throughout the lifecycle of the plan, ensuring that no action can proceed if it would exceed the plan's available balance. Updates to the ledger occur immediately upon triggering events like proposals, approvals, rejections, cancellations, or finalizations, with reversals only applying to eligible, non-terminal states to avoid redundant adjustments that could drift balances away from their true state. When an assignment is cancelled or rejected, any provisional commitments are promptly released back to the available balance, reflecting the adjustment in the plan's cost_balance.

### 2.6. Patient Safety Governance

The system enforces a strict patient safety protocol, managed by the `PatientSafetyScoreLedger`. This plan-scoped ledger maintains a `safety_score` that triggers a reconciliation that updates the plan's `patient_safety_score` as risk factors change. This score begins at zero and increases as risk factors are introduced, though the system's internal safeguards ensure it never falls below this initial baseline of zero through any ledger operation. It serves as a dynamic, real-time reflection of risk, including reversals for removed risks in non-terminal states, and a lower score is always preferable. The system is designed to flag and, in some cases, prevent actions that would unacceptably compromise patient safety based on this live score.

### 2.7. Resource Utilization and Sterilization Protocols

The system enforces strict protocols regarding the use and reuse of medical resources. The system enforces a 30-minute turnaround between procedures that are not compatible for immediate sequencing, in compliance with CDC guidelines for intermediate-level disinfection. The system's conflict checks for this protocol are comprehensive, considering the resource's entire committed schedule of procedures.

Medical equipment follows industry-standard maintenance cycles, requiring deep cleaning after 100 hours of operation. Furthermore, the system actively monitors the cumulative operational time of each medical resource to mitigate risks associated with overuse. This is governed by the high bio-risk policies.

Important scheduling rule:

- Resources can never be double-booked: time intervals for the same resource can never overlap.

### 2.8. Nested Resource Retrieval

The API enforces a strict, hierarchical validation protocol for all requests that target nested resources. When an endpoint path contains multiple resource identifiers (e.g., `/treatment-plans/{planId}/ward-rotations/{rotationId}`), the system validates the existence of each identifier in a sequential, left-to-right order. The request will be rejected immediately with a `404 Not Found` error corresponding to the *first* identifier in the path that does not correspond to an existing resource. For instance, a request for a rotation under a non-existent treatment plan will result in `ERR_PLAN_NOT_FOUND` before the system even attempts to locate the rotation. This principle extends to creation and modification operations, where the parent plan's existence and active status take precedence over child validations, ensuring that operations only proceed in valid, operational contexts.

### 2.9. Common Resource Properties

All primary, top-level resources (such as Treatment Plans, Ward Rotations, Procedures, Medical Resources, and Assignments) include a standard set of system-managed fields:

- `**id` (string):** A unique, system-generated identifier for the resource, formatted as a UUID.
- `**created_at` (string):** An ISO 8601 timestamp in UTC (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- `**updated_at` (string):** An ISO 8601 UTC timestamp indicating when the resource was last modified. This field is updated upon any change to the resource's properties.
- `**version` (integer):** A system-managed integer that increments with every modification to the resource. This field can be used for optimistic concurrency control.
Updates to derived fields like cost_balance and patient_safety_score on a TreatmentPlan are mutations that update updated_at and increment version.
Nested sub-resources, such as certifications within a Medical Resource, also receive a unique `id` (UUID). Resources that are immutable after creation, like an `InfectionRiskPairing`, may omit the `updated_at` field. This convention provides a consistent audit trail and unique addressability for every key entity in the system.

### 2.10. Monetary Values and Precision

All monetary values within the system, such as budgets and costs, must be handled with specific precision to ensure financial accuracy and prevent common floating-point errors.

- **Internal Calculations:** All internal calculations involving monetary values (e.g., calculating provisional or final costs) must be performed using decimal arithmetic.
- **Final Values & Rounding:** Final cost values (like `provisional_cost` and `final_cost`) and budget balances stored on resources must be rounded to exactly 2 decimal places. The standard "round half up" method should be used.
- **API Representation:** All monetary values returned in the API response bodies must be represented as standard numbers (not strings) with a maximum of 2 decimal places. Configuration/rate fields (e.g., `operating_cost_per_minute`) preserve input precision.

### 2.11. Optimistic Concurrency Control

Operations that modify a resource's state (e.g., approving an assignment, updating a rotation's status) can leverage optimistic locking to prevent lost updates in a concurrent environment. Clients may include the latest `version` number of the resource in the request body. If the provided `version` does not match the current version of the resource on the server, the request will be rejected with `ERR_STALE_DATA`. This ensures that a user is not acting on stale data. If the version field is omitted, the server processes the mutation without an OCC check. The system applies this protection to any endpoint that targets a specific resource by its identifier in the path, maintaining consistency across the entire workflow from individual assignments through to plan finalization.

## 3. Business Logic & Workflows

### 3.1. The Treatment Plan Lifecycle

The central organizing entity in the system is the **Treatment Plan**. A `ChargeNurse` initiates a plan by providing a `plan_name` for identification and establishing a `total_budget`. Upon creation, the system automatically instantiates its associated `CareBudgetLedger` and `PatientSafetyScoreLedger`.

The lifecycle culminates in a final review and completion process. Before a plan can be finalized, it must be moved to the `FINAL_REVIEW_PENDING` state, which signifies that all proposed clinical activities have been definitively scheduled or discarded, preparing the plan for a full and final accounting of all incurred costs. The final transition to `COMPLETED` is an atomic transaction restricted to a `HospitalAdministrator`. This critical step involves the final calculation of all incurred costs.

All subsequent scheduling activities, such as defining rotations and procedures, are contingent on the plan being `ACTIVE`. This includes creating or modifying rotations, procedures, assignments, and pairings.

### 3.2. Structuring Clinical Work: Ward Rotations and Procedures

Within an `ACTIVE` Treatment Plan, an `AttendingPhysician` can structure the clinical workflow by creating **Ward Rotations**. A rotation represents a logical block of time and is defined with a `name`, a `start_minute` (as a non-negative integer offset in the schedule), and an `end_minute`. Each rotation is associated with the parent plan via its `plan_id`. During its lifecycle, a rotation's status can be in a `PLANNING` state and can change to `READY_FOR_ASSIGNMENT`, `COMPLETED`, or `CANCELLED`. A rotation reaches `COMPLETED` when all procedures within it have reached their final outcomes—that is, when every procedure is either `COMPLETED` or `CANCELLED`, reflecting that the clinical work block has been fully resolved. Invalid minute specifications, such as non-integer values or those not satisfying the end greater than start, trigger validation errors like `ERR_INVALID_ROTATION_MINUTES`.

Within a rotation, the `AttendingPhysician` defines one or more **Procedures**. Each `Procedure` is created with a `procedure_type` and its own `start_minute` and `end_minute`. The procedure includes a read-only `duration_minutes` field, derived from its start and end times. For addressability and rule evaluation, a procedure response includes both its `rotation_id` and its parent `plan_id`. Procedures of the same `procedure_type` are considered compatible for immediate sequencing without requiring additional protocols. A critical piece of information for each procedure is the `required_certification`, which specifies the level of qualification a medical resource must have to be assigned. This can be one of `BSL-3_CERTIFIED`, `CARDIAC_CATHETERIZATION_LAB`, or `NONE`. If omitted during creation, it defaults to `NONE`. Non-integer or invalid minute ranges for procedures result in errors such as `ERR_INVALID_PROCEDURE_MINUTES`. Procedures that have not yet reached a terminal outcome—those in PENDING, SCHEDULED, or ASSIGNED states—represent active clinical commitments requiring continued resource coordination and oversight.

A `Procedure`'s `status` is directly influenced by the assignment process. When an assignment is proposed, it moves to `SCHEDULED`, and upon confirmation, it becomes `ASSIGNED`. Ultimately, a procedure can be transitioned to `COMPLETED` following the finalization process. `READY_FOR_ASSIGNMENT` requires that every procedure within the rotation be in the `ASSIGNED` state. A rotation's status must reflect the operational reality of its procedures per §2.4 and the defined state machines. As procedures transition to their terminal states, the system evaluates whether the rotation's completion criteria have been satisfied and transitions it accordingly to maintain alignment.

Cancellation of a `Procedure` is only possible when it is in the `PENDING` state. Cancelling a `WardRotation`, a more significant event, is only permissible when the rotation is in PLANNING or READY_FOR_ASSIGNMENT. When a rotation is cancelled, the system ensures consistency by addressing all resources that were allocated or planned within its scope. A cancelled rotation is terminal. The system maintains consistency by resolving dependent work within its scope. Updating a rotation’s status (via the `PUT` endpoint) is only allowed while the parent Treatment Plan is `ACTIVE`; otherwise the request is rejected with `ERR_PLAN_NOT_ACTIVE`.

### 3.3. The Assignment Process: Proposal and Approval

The core operational workflow is the assignment of a **Medical Resource** to a **Procedure**. An `AttendingPhysician` proposes an **Assignment** via a payload containing the `procedure_id` and the `resource_id`. This action creates an `Assignment` resource, which includes a `plan_id`, the `procedure_id`, and the `resource_id`, starting in a `PENDING_SCHEDULE` status as it awaits review. This proposal triggers a multi-faceted validation process, but only for procedures still in their `PENDING` state under non-terminal rotations.

The system first verifies that the proposed `MedicalResource`—defined by its `resource_name`, `resource_model`, and `operating_cost_per_minute`—holds the necessary qualifications. The resource's `resource_certifications` list—a collection of records each containing the certification `name` and the `applied_date`—is checked to ensure it contains a certification matching the procedure's `required_certification`. For a certification to be considered valid, its `applied_date` must be on or before the date the assignment is proposed. To ensure resources are properly credentialed for advanced procedures, an `AttendingPhysician` is authorized to update a resource's profile by submitting a new certification, including its `name` and the `applied_date`.

Next, the proposal undergoes operational validation. The system evaluates scheduling constraints to ensure proper sterilization protocols are maintained, followed by an assessment of infection control policies to prevent cross-contamination risks.

The system's validation cascade prioritizes patient safety above all else; therefore, it first evaluates all scheduling and safety-related constraints before proceeding to fiscal checks. If these checks pass, the system calculates a `provisional_cost` for the assignment. This cost is validated against the Treatment Plan's available `cost_balance`. If the budget is sufficient, the assignment is created.

A `ChargeNurse` is responsible for reviewing and approving these proposals. They can transition an assignment's `status` to `PROTOCOL_APPROVED`. The final scheduling action, which moves the `status` to `SCHEDULED` and the corresponding `Procedure` to `ASSIGNED`, can only be performed on an assignment that is currently in the `PROTOCOL_APPROVED` state. Scheduling must reflect the plan's most current state for both risk classification and cost exposure. The recalculation for this stage considers only the operational load from assignments whose procedures are scheduled to start before the current one, ensuring fiscal precision as the timeline solidifies. The system adjusts the CareBudgetLedger by the net difference between the newly calculated and prior provisional costs. Upon full confirmation, the assignment reaches a `SCHEDULED` state, ready for later completion during finalization.

An assignment may also be rejected or cancelled by a `ChargeNurse` prior to the plan's finalization, but these actions are constrained by the assignment lifecycle. Specifically: rejection is permitted only while the assignment is in the `PENDING_SCHEDULE` state. Cancellation is permitted while the assignment is in `PENDING_SCHEDULE`, `PROTOCOL_APPROVED`, or `SCHEDULED`. Rejection immediately sets the assignment to `REJECTED` and reopens the associated Procedure to `PENDING`. Cancellation follows a similar process and reopens the associated Procedure to `PENDING`, ensuring flexibility in adjusting schedules before costs are locked in—provided the change aligns with the plan's overall budget and safety commitments as reflected in the ledgers. These state transitions are strictly controlled to maintain ledger accuracy, with reversals only applying to eligible, non-terminal states to avoid redundant adjustments that could drift balances away from their true state.

### 3.4. Infection Control and Resource Pairing

The system allows a `ChargeNurse` to create an **Infection Risk Pairing** to mitigate the risk of cross-contamination. This resource links two medical resources, `resource_id_1` and `resource_id_2`, within the context of a `plan_id`, and can include an optional `reason` for the pairing. Pairings are authored within an operational plan context; as such, creating a pairing requires the parent Treatment Plan to be `ACTIVE` (attempts when the plan is not `ACTIVE` are rejected with `ERR_PLAN_NOT_ACTIVE`). A pairing is unique per unordered resource pair within a plan: attempting to create a pairing that already exists—whether provided as `{A,B}` or `{B,A}`—must be rejected with `409 ERR_DUPLICATE_PAIRING`.

Creating a pairing constrains future proposals: the system rejects a proposed assignment that would place paired resources within the same rotation if one is already committed to that rotation's schedule (committed schedule includes assignments in PENDING_SCHEDULE, PROTOCOL_APPROVED, SCHEDULED, or COMPLETED status). Enforcement occurs at proposal time. Existing assignments are unaffected.

### 3.5. Adherence to Patient Safety Protocols

When an assignment proposal is evaluated, it is subject to the safety governance principles. The system determines if the assignment qualifies as a high bio-risk event. If it does, 50 points are assessed against the `PatientSafetyScoreLedger`. The system maintains strict validation of resource capabilities, automatically rejecting any assignment where the procedure's `required_certification` is not among the standard certification options recognized by the hospital's accreditation system.

The system then checks if this penalty would cause the plan's `safety_score` to meet or exceed a threshold equivalent to ten standard bio-risk events. If the threshold is breached, the assignment is normally rejected. However, the system provides a mechanism for a deliberate override. The assignment payload includes an `override_protocol_check` boolean. If an operator sets this to `true`, they can force the assignment through despite the safety score breach. In such cases, 100 points are added to the `safety_score` on top of any other penalties. The `Assignment` resource permanently records whether the override was used via the `override_protocol_check` field and whether the associated penalty was applied in the read-only `protocol_override_penalty_applied` flag.

### 3.6. High Bio-Risk and Provisional Cost Calculation

The system's cost calculation logic is directly tied to resource utilization. A `MedicalResource` is considered to be in a high bio-risk state when its total cumulative usage time exceeds the standard maintenance cycle duration. Any procedure time that occurs after this threshold is crossed is billed at double the resource's standard operating cost

When an assignment is proposed, the system calculates its `provisional_cost`. To maintain a forward-looking and conservative risk profile, this calculation conservatively estimates the resource's future usage by adding the proposed procedure's duration to the resource's projected operational load from its other unresolved assignments across the entire plan, including those scheduled to execute later. This projection is used to determine if any part of the new procedure's time would be subject to high-risk surcharges. The `Assignment` resource tracks this outcome with the `is_high_biorisk` boolean flag.

### 3.7. Cost Finalization and Plan Completion

The final act in a Treatment Plan's lifecycle is the cost finalization process, triggered by a `HospitalAdministrator`. During this process, a `final_cost` is calculated for each `SCHEDULED` assignment. This cost must accurately account for the point at which each resource's cumulative usage across all scheduled procedures exceeds the maintenance threshold, applying surcharges only to the minutes that fall beyond that point. The calculation processes each resource's assignments in the order they are scheduled to execute.

This `final_cost` is recorded on the `Assignment` resource. The `PatientSafetyScoreLedger` is also adjusted if the final risk calculation (`is_high_biorisk`) differs from the provisional one. The entire transaction is committed. If successful, all provisional debits are cleared, and the plan's `status` is moved to `COMPLETED` (Status alignment across the hierarchy follows §2.4 and the state machines.).

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (e.g., a Treatment Plan) or add new, distinct resources to a collection (e.g., a Ward Rotation to a plan) return a `201 Created` status code. Operations that modify an existing resource, including adding data to a resource's internal collection (e.g., adding a certification to a Medical Resource), return a `200 OK` status code.


| Method | Path                                                                                    | Description                                              | Authorized Role(s)    |
| ------ | --------------------------------------------------------------------------------------- | -------------------------------------------------------- | --------------------- |
| POST   | `/treatment-plans`                                                                      | Create a new Treatment Plan                              | ChargeNurse           |
| GET    | `/treatment-plans`                                                                      | List all Treatment Plans                                 | Any                   |
| GET    | `/treatment-plans/{planId}`                                                             | Get a specific Treatment Plan                            | Any                   |
| POST   | `/treatment-plans/{planId}/activate`                                                    | Activate a plan                                          | ChargeNurse           |
| POST   | `/treatment-plans/{planId}/ward-rotations`                                              | Create a new Ward Rotation within a Plan                 | AttendingPhysician    |
| GET    | `/treatment-plans/{planId}/ward-rotations`                                              | List Ward Rotations for a Plan                           | Any                   |
| GET    | `/treatment-plans/{planId}/ward-rotations/{rotationId}`                                 | Get a specific Ward Rotation                             | Any                   |
| PUT    | `/treatment-plans/{planId}/ward-rotations/{rotationId}`                                 | Update a Ward Rotation's status                          | ChargeNurse           |
| POST   | `/treatment-plans/{planId}/ward-rotations/{rotationId}/procedures`                      | Create a new Procedure for a Rotation                    | AttendingPhysician    |
| GET    | `/treatment-plans/{planId}/ward-rotations/{rotationId}/procedures`                      | List Procedures for a Rotation                           | Any                   |
| GET    | `/treatment-plans/{planId}/ward-rotations/{rotationId}/procedures/{procedureId}`        | Get a specific Procedure                                 | Any                   |
| POST   | `/treatment-plans/{planId}/ward-rotations/{rotationId}/procedures/{procedureId}/cancel` | Cancel a specific Procedure                              | AttendingPhysician    |
| POST   | `/treatment-plans/{planId}/assignments`                                                 | Propose a new MedicalResource assignment for a Procedure | AttendingPhysician    |
| GET    | `/treatment-plans/{planId}/assignments`                                                 | List all Assignments for a Plan                          | Any                   |
| GET    | `/treatment-plans/{planId}/assignments/{assignmentId}`                                  | Get a specific Assignment                                | Any                   |
| POST   | `/treatment-plans/{planId}/assignments/{assignmentId}/reject`                           | Reject a proposed Assignment                             | ChargeNurse           |
| POST   | `/treatment-plans/{planId}/assignments/{assignmentId}/cancel`                           | Cancel an Assignment                                     | ChargeNurse           |
| POST   | `/treatment-plans/{planId}/assignments/{assignmentId}/protocol-approve`                 | Protocol Approve a proposed Assignment                   | ChargeNurse           |
| POST   | `/treatment-plans/{planId}/assignments/{assignmentId}/schedule`                         | Schedule a Protocol Approved Procedure                   | ChargeNurse           |
| POST   | `/treatment-plans/{planId}/medical-resources`                                           | Create a new Medical Resource profile for a Plan         | AttendingPhysician    |
| GET    | `/treatment-plans/{planId}/medical-resources`                                           | List Medical Resource profiles for a Plan                | Any                   |
| GET    | `/treatment-plans/{planId}/medical-resources/{resourceId}`                              | Get a specific Medical Resource profile                  | Any                   |
| POST   | `/treatment-plans/{planId}/medical-resources/{resourceId}/certifications`               | Add a certification to a Medical Resource                | AttendingPhysician    |
| POST   | `/treatment-plans/{planId}/infection-risk-pairings`                                     | Create an Infection Risk Pairing within a Plan           | ChargeNurse           |
| GET    | `/treatment-plans/{planId}/infection-risk-pairings`                                     | List Infection Risk Pairings for a Plan                  | Any                   |
| GET    | `/treatment-plans/{planId}/infection-risk-pairings/{pairingId}`                         | Get a specific Infection Risk Pairing                    | Any                   |
| POST   | `/treatment-plans/{planId}/initiate-final-review`                                       | Move a plan to the final review pending state            | ChargeNurse           |
| POST   | `/treatment-plans/{planId}/finalize-plan`                                               | Finalize costs and complete the plan                     | HospitalAdministrator |


## 5. Error Code Catalogue


| Error ID                                     | HTTP Status Code     |
| -------------------------------------------- | -------------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request      |
| `ERR_INSUFFICIENT_PERMISSIONS`               | 403 Forbidden        |
| `ERR_PLAN_NOT_FOUND`                         | 404 Not Found        |
| `ERR_RESOURCE_NOT_FOUND`                     | 404 Not Found        |
| `ERR_SELF_PAIRING`                           | 400 Bad Request      |
| `ERR_DUPLICATE_PAIRING`                      | 409 Conflict         |
| `ERR_PROCEDURE_NOT_FOUND`                    | 404 Not Found        |
| `ERR_PROCEDURE_NOT_PENDING_FOR_CANCEL`       | 409 Conflict         |
| `ERR_PLAN_NOT_ACTIVE`                        | 409 Conflict         |
| `ERR_INVALID_ROTATION_MINUTES`               | 400 Bad Request      |
| `ERR_ROTATION_NOT_FOUND`                     | 404 Not Found        |
| `ERR_INVALID_PROCEDURE_MINUTES`              | 400 Bad Request      |
| `ERR_PROCEDURE_NOT_PENDING`                  | 409 Conflict         |
| `ERR_CERTIFICATION_MISMATCH`                 | 400 Bad Request      |
| `ERR_STERILIZATION_TIME_VIOLATION`           | 409 Conflict         |
| `ERR_INFECTION_RISK`                         | 409 Conflict         |
| `ERR_SAFETY_SCORE_THRESHOLD_BREACHED`        | 403 Forbidden        |
| `ERR_INSUFFICIENT_BUDGET`                    | 402 Payment Required |
| `ERR_INVALID_REQUEST`                        | 400 Bad Request      |
| `ERR_ASSIGNMENT_NOT_FOUND`                   | 404 Not Found        |
| `ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE`        | 409 Conflict         |
| `ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED`       | 409 Conflict         |
| `ERR_PROCEDURE_NOT_SCHEDULED`                | 409 Conflict         |
| `ERR_ILLEGAL_ROTATION_STATE_TRANSITION`      | 409 Conflict         |
| `ERR_PROCEDURES_NOT_ASSIGNED`                | 409 Conflict         |
| `ERR_PLAN_NOT_READY_FOR_FINALIZATION`        | 409 Conflict         |
| `ERR_FINALIZATION_EXCEEDS_BUDGET`            | 402 Payment Required |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE`             | 409 Conflict         |
| `ERR_UNRESOLVED_ASSIGNMENTS_EXIST`           | 409 Conflict         |
| `ERR_PLAN_NOT_IN_PLANNING`                   | 409 Conflict         |
| `ERR_PAIRING_NOT_FOUND`                      | 404 Not Found        |
| `ERR_STALE_DATA`                             | 409 Conflict         |


