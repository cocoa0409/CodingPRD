# Hospital Shifts: Advanced Clinical Operations & Resource Lifecycle Management

## 1. Executive Summary

Building upon our enhanced scheduling controls, we are introducing comprehensive resource lifecycle management capabilities, coordinated multi-resource procedures, and refined clinical preparedness protocols. These updates enable sophisticated equipment retirement workflows, dynamic resource allocation for operational flexibility, equipment-specific sterilization protocols, complex procedures requiring multiple specialized resources simultaneously, and precise overhead time modeling for improved scheduling accuracy.

## 2. Clinical Preparedness Windows

Sterility between distinct clinical activities is preserved by a brief time window on the same equipment. Conventional equipment follows a standard thirty-minute preparation interval; certain models tolerate different regimens based on their construction and cleaning procedures. When creating a resource profile, an `AttendingPhysician` may specify a `sterilization_buffer_override` to define this resource's specific interval. When set to a non‑negative integer, this value replaces the standard interval. When absent or null, the conventional thirty minutes applies. A value of zero removes the required interval entirely; existing overlap rules still apply. The window applies only when the two procedures use the same resource and their clinical types differ.

Clinical procedures often require preparation time before the scheduled start and cleanup time after the scheduled end, during which the resource is occupied but not actively operating. To capture this reality, resource profiles now include `setup_overhead_minutes` and `teardown_overhead_minutes`, representing the preparation and cleanup durations. When not specified during resource creation, these default to zero. Time is modeled as an unbounded integer minute axis; start_minute and end_minute may be any integers. When a resource's setup overhead is applied, the resulting occupancy_start (calculated as procedure.start_minute - setup_overhead_minutes) may be negative. All scheduling validations operate on these integer minutes.

We define two distinct time windows for every assignment:

1. The **Operational Window**, which corresponds exactly to the scheduled procedure duration.
2. The **Occupancy Window**, which includes the Operational Window plus any preceding setup time and subsequent teardown time required for the specific resource(s) involved.

Procedures cannot have overlapping Occupancy Windows on the same resource, regardless of procedure type. This ensures exclusive resource access during the entire occupancy period (setup, operation, and teardown).

For most scheduling purposes—including conflict detection, hold validation, and sterilization buffer requirements—the system must use the Occupancy Window. A resource is considered unavailable during its setup and teardown periods.

When calculating sterilization buffers between adjacent procedures of different types, the required gap applies between the end of the first procedure's Occupancy Window and the start of the second procedure's Occupancy Window.

A full servicing restores a resource to a clean state. When a servicing is recorded after one procedure concludes but not later than the start of the next on that same resource, it satisfies the interval requirement for that pairing. Operational holds restrict availability but do not, by themselves, satisfy sterility.

All windows use half‑open intervals `[start_minute, end_minute)`. A gap equal to the effective interval is sufficient; a smaller gap is not. A servicing at the exact end of the first procedure does not satisfy the interval; it must occur strictly after the prior end and at or before the next start. The interval concerns only the shared resource; other resources are unaffected. Note that existing quarantine protocols remain tied to the scheduled procedure start time, not the beginning of the occupancy window.

## 3. Asset Management and Lifecycle Updates

The system is expanding its capabilities to manage the full lifecycle of medical assets, including their eventual retirement from service. Medical resource profiles now include a `status` field reflecting their operational state. By default, newly provisioned resources are considered `AVAILABLE` for clinical use. However, operational realities dictate that equipment must eventually be retired. A `HospitalAdministrator` can initiate the decommissioning process for a resource via the `/medical-resources/{resourceId}/decommission` endpoint. This action prevents the resource from being allocated to any new clinical work while allowing it to complete its existing commitments.

If a resource has no outstanding commitments (i.e., no assignments in either role in non-terminal states), it is immediately moved to the `DECOMMISSIONED` status. This is a terminal state.

If the resource still has pending or scheduled work, it cannot be immediately retired. In this scenario, it enters a `DECOMMISSIONING_PENDING` state. This indicates that the resource will be retired once its current obligations are fulfilled.

When an assignment is cancelled, rejected, completed, or reallocated away from a resource, the system must evaluate decommissioning completion for all involved resources. Each resource (primary and secondary) must be checked independently. If a resource in `DECOMMISSIONING_PENDING` status has no remaining non-terminal assignments in either role, it automatically transitions to `DECOMMISSIONED`.

A `HospitalAdministrator` may choose to reverse this decision, provided the resource is still in the `DECOMMISSIONING_PENDING` state, by invoking the `/medical-resources/{resourceId}/cancel-decommissioning` endpoint, which returns the resource to `AVAILABLE` status.

## 4. Enhanced Operational Flexibility

`ChargeNurse` staff require the ability to substitute resources on existing assignments, provided the procedure has not yet been finalized in the schedule. Complex clinical scenarios now support procedures that require the simultaneous use of multiple, distinct medical resources.

### 4.1. Multi-Resource Procedures

The system now supports procedures that require the simultaneous use of multiple, distinct medical resources. When defining a procedure, an `AttendingPhysician` may specify not only a primary `required_certification` but also a list of `secondary_resource_requirements`, indicating additional specialized equipment needed for the duration of the procedure.

When proposing an assignment for such a procedure, the `AttendingPhysician` must provide the primary `resource_id` along with a corresponding list of `secondary_resource_ids`. The system enforces strict coordination: all specified resources must be simultaneously available and compliant with all operational constraints for the entire duration of the procedure's occupancy.

The primary resource must fulfill the main certification requirement, while each secondary resource must fulfill its corresponding requirement specified in the procedure definition. The list `secondary_resource_requirements` is ordered; the i-th resource in `secondary_resource_ids` must satisfy the i-th certification requirement in `secondary_resource_requirements`. It is critical that all resources involved in a single procedure are unique; a resource cannot serve as both primary and secondary, nor can it fulfill multiple secondary roles simultaneously. When checking availability, the system must account for a resource's commitments across all its assignments, regardless of whether it serves in a primary or secondary capacity.

The assignment resource captures this coordination by storing the `secondary_resource_ids` alongside the primary `resource_id`.

### 4.2. Assignment Reallocation

A `ChargeNurse` may reallocate an assignment that is currently in `PENDING_SCHEDULE` or `PROTOCOL_APPROVED` status to a different `new_resource_id` via the `/assignments/{assignmentId}/reallocate` endpoint. This operation is subject to rigorous re-validation. The system must ensure that the new resource is a fully compliant substitute that meets all existing procedural, scheduling, and resource constraints.

The reallocation workflow is designed for substituting the primary equipment assigned to a procedure. Secondary resource assignments are considered fixed upon proposal and cannot be altered through the reallocation mechanism. When reallocating a multi-resource assignment, the request body MUST NOT include the `secondary_resource_ids` field. If this field is provided, the request fails with `400 ERR_INVALID_REQUEST`. When reallocating, the new primary resource must not be identical to any of the existing secondary resources.

The reallocation process must be treated as an atomic operation. If the new resource is valid and the financial implications are acceptable, the assignment is updated. All lifecycle endpoints support standard optimistic concurrency control via an optional `version` field in the request body, following existing system conventions.

## 5. Updates to Financial and Safety Accounting

Resource substitution capabilities and coordinated multi-resource usage require adjustments to how costs and safety penalties are tracked.

When an assignment is reallocated, its financial impact must be completely re-evaluated based on the new resource's total planned workload. The system must account for all of the resource's scheduled commitments when calculating usage baselines and threshold-crossing points, using the same forecasting principles applied during initial assignment validation.

Similarly, using the same forward-looking approach, the safety implications are re-assessed. The `is_high_biorisk` status is updated based on the new resource's usage profile, and any bio-risk penalties from the original resource assignment that are no longer warranted must be refunded from the `PatientSafetyScoreLedger`. Crucially, any `PROTOCOL_OVERRIDE_PENALTY` applied during the original proposal is considered specific to the context of that proposal and the original resource. Upon successful reallocation, the system must check whether such a penalty is currently applied to the assignment; if so, the penalty is refunded from the ledger, and the associated flags (`override_protocol_check` and `protocol_override_penalty_applied`) are reset to false. This refund occurs at most once per assignment.

For procedures utilizing multiple resources, the total cost charged to the `CareBudgetLedger` is the aggregate sum of the operational costs incurred by the primary resource and all secondary resources. Each resource's contribution is calculated independently, respecting its specific operating rate, maintenance threshold, and current usage baseline. The system must ensure that only the actual clinical operation time contributes to wear accumulation and financial charges.

The `PatientSafetyScoreLedger` reflects the increased risk associated with utilizing any equipment beyond its operational tolerance. When an assignment involves multiple resources, the system assesses the bio-risk status of each resource independently. If any resource operates in a high-risk state during the procedure, the standard bio-risk penalty is applied to the ledger. The total safety impact of the assignment is the accumulation of penalties for every resource that crosses its respective threshold during the operation.

When validating a proposal, the system must consider the total potential safety penalty across all involved resources. If this total impact would cause the plan's safety score to breach the threshold lock, the proposal must be explicitly overridden, following established protocols.

Upon cancellation or rejection of a multi-resource assignment, all safety score penalties that were applied during its proposal must be fully refunded. To ensure symmetry, the system must determine which resources (primary and secondary) crossed their maintenance thresholds at the time of proposal creation, using the operational state as it existed at that moment. The refund must restore exactly the penalties that were applied, irrespective of any subsequent state changes such as maintenance events or additional assignments. The system must refund one `HIGH_BIORISK_PENALTY` for each resource that crossed its threshold at proposal time.

## 6. Error Code Catalogue

| Error ID                              | HTTP Status Code |
| :------------------------------------ | :--------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request  |
| `ERR_INSUFFICIENT_PERMISSIONS`        | 403 Forbidden    |
| `ERR_PLAN_NOT_FOUND`                  | 404 Not Found    |
| `ERR_RESOURCE_NOT_FOUND`              | 404 Not Found    |
| `ERR_SELF_PAIRING`                    | 400 Bad Request  |
| `ERR_DUPLICATE_PAIRING`              | 409 Conflict     |
| `ERR_PROCEDURE_NOT_FOUND`             | 404 Not Found    |
| `ERR_PROCEDURE_NOT_PENDING_FOR_CANCEL`| 409 Conflict     |
| `ERR_PLAN_NOT_ACTIVE`                 | 409 Conflict     |
| `ERR_INVALID_ROTATION_MINUTES`        | 400 Bad Request  |
| `ERR_ROTATION_NOT_FOUND`              | 404 Not Found    |
| `ERR_INVALID_PROCEDURE_MINUTES`       | 400 Bad Request  |
| `ERR_PROCEDURE_NOT_PENDING`           | 409 Conflict     |
| `ERR_CERTIFICATION_MISMATCH`          | 400 Bad Request  |
| `ERR_STERILIZATION_TIME_VIOLATION`    | 409 Conflict     |
| `ERR_INFECTION_RISK`                  | 409 Conflict     |
| `ERR_SAFETY_SCORE_THRESHOLD_BREACHED` | 403 Forbidden    |
| `ERR_INSUFFICIENT_BUDGET`             | 402 Payment Required |
| `ERR_INVALID_REQUEST`                 | 400 Bad Request  |
| `ERR_ASSIGNMENT_NOT_FOUND`            | 404 Not Found    |
| `ERR_ASSIGNMENT_NOT_PENDING_SCHEDULE` | 409 Conflict     |
| `ERR_ASSIGNMENT_NOT_PROTOCOL_APPROVED`| 409 Conflict     |
| `ERR_PROCEDURE_NOT_SCHEDULED`         | 409 Conflict     |
| `ERR_ILLEGAL_ROTATION_STATE_TRANSITION`| 409 Conflict     |
| `ERR_PROCEDURES_NOT_ASSIGNED`         | 409 Conflict     |
| `ERR_PLAN_NOT_READY_FOR_FINALIZATION` | 409 Conflict     |
| `ERR_FINALIZATION_EXCEEDS_BUDGET`     | 402 Payment Required |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE`      | 409 Conflict     |
| `ERR_UNRESOLVED_ASSIGNMENTS_EXIST`    | 409 Conflict     |
| `ERR_PLAN_NOT_IN_PLANNING`            | 409 Conflict     |
| `ERR_PAIRING_NOT_FOUND`               | 404 Not Found    |
| `ERR_STALE_DATA`                      | 409 Conflict     |
| `ERR_INVALID_THRESHOLD`               | 400 Bad Request  |
| `ERR_PAIRING_QUARANTINE_ACTIVE`       | 409 Conflict     |
| `ERR_RESOURCE_ON_HOLD`                | 409 Conflict     |
| `ERR_RESOURCE_HOLD_NOT_FOUND`         | 404 Not Found    |
| `ERR_HOLD_NOT_ACTIVE`                 | 409 Conflict     |
| `ERR_INVALID_HOLD_MINUTES`            | 400 Bad Request  |
| `ERR_HOLD_CONFLICTS_WITH_ASSIGNMENT`  | 409 Conflict     |
| `ERR_MAINTENANCE_EVENT_NOT_FOUND`     | 404 Not Found    |
| `ERR_INVALID_EVENT_MINUTE`            | 400 Bad Request  |
| `ERR_MAINTENANCE_EVENT_CONFLICT`      | 409 Conflict     |
| `ERR_OVERRIDE_NOT_AUTHORIZED`         | 409 Conflict     |
| `ERR_OVERRIDE_NOT_REQUIRED`           | 409 Conflict     |
| `ERR_OVERRIDE_ALREADY_AUTHORIZED`     | 409 Conflict     |
| `ERR_ASSIGNMENT_NOT_PENDING_OR_APPROVED` | 409 Conflict  |
| `ERR_RESOURCE_DECOMMISSIONED`         | 409 Conflict     |
| `ERR_RESOURCE_ALREADY_DECOMMISSIONED` | 409 Conflict     |
| `ERR_DECOMMISSIONING_NOT_PENDING`     | 409 Conflict     |
| `ERR_ASSIGNMENT_NOT_REALLOCATABLE`    | 409 Conflict     |

