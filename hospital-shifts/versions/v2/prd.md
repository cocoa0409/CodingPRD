# Hospital Shifts: Enhanced Scheduling Controls & Lifecycle Management

## 1. Executive Summary

As our hospital's operational needs mature, we require a more granular and dynamic approach to managing our critical medical resources. This update introduces a sophisticated system for tracking equipment wear and servicing, enhances our control over resource availability and safety protocols, and refines our personnel qualification workflows. These changes are designed to improve both financial accuracy and patient outcomes by providing deeper insights and more robust controls throughout the treatment plan lifecycle.

## 2. System-Wide Principles & Enhancements

The foundational principles of the existing system—including user roles, fiscal responsibility, and patient safety governance—remain in full effect. This evolution builds upon those principles with the following enhancements.

### 2.1. Advanced Equipment Lifecycle Management

To more accurately model the operational lifecycle of our equipment, the system must now incorporate the concept of periodic servicing. Equipment wear accumulates incrementally with each operational minute, and servicing resets this accumulation to zero. This directly impacts our financial and safety accounting.

Each operational minute of a procedure incurs costs based on the resource's total usage index at that specific minute, counted from the resource's most recent servicing. Servicing events establish reset points in the usage timeline. Certain specialized equipment operates under different maintenance regimens based on manufacturer specifications and operational tolerances. Resources operating beyond their designated operational tolerance incur elevated per-minute charges, while conventional equipment follows the standard deep-clean maintenance cycle of 6,000 minutes. Bio-risk flags are determined by whether any portion of a procedure's operational minutes fall into this elevated-cost range.

The financial outcome for any assignment must reflect the granular, minute-by-minute accumulation of usage, ensuring that procedures occurring after servicing are charged at rates appropriate to their reduced wear state, while those occurring with substantial accumulated usage reflect the elevated risk and cost associated with intensive use.

To support this, a `ChargeNurse` can now log these servicing events by providing a `resource_id` and the `at_minute` of the service. A servicing event's `at_minute` must not lie inside any active resource hold window for that resource, nor inside any non-terminal assignment window for that resource. However, recording a servicing at the exact conclusion of a hold or assignment (i.e., at their `end_minute`) is permitted. Violations of these constraints return a `409 ERR_MAINTENANCE_EVENT_CONFLICT` error.

### 2.2. Clinical Preparedness and Sterilization

A full equipment servicing restores a resource to a clean, sterile operational state. As such, when a servicing event is recorded at minute M on a specific resource, and M falls after one procedure's completion but at or before the start of a subsequent procedure on that **same resource**, the system recognizes this servicing as satisfying the inter-procedure sterilization requirement between those two procedures. This waiver applies only to procedures using the serviced resource and does not affect sterilization requirements for other resources.

### 2.3. Enhanced Operational Constraints

Charge Nurses require more direct control over resource availability for non-clinical activities like calibration or preventative checks. Resources may be placed on temporary hold to support this need.

While a `ResourceHold` is active, the resource is considered unavailable for any clinical procedures whose scheduled window overlaps the hold window. This constraint is enforced bidirectionally: procedures cannot be proposed or scheduled during active holds, and holds cannot be created if they would overlap with already-committed assignments. A procedure may, however, begin at the exact minute a hold concludes or end at the exact minute a hold begins. It is important to note that these operational holds do not, by themselves, satisfy any sterilization requirements or alter the equipment's wear accumulation.

Hold cancellation supports optimistic concurrency control: if a `version` field is included in the cancellation request and does not match the hold's current version, the operation fails with `409 ERR_STALE_DATA`.

## 3. Refinements to Workflow and Safety Protocols

The core workflows for proposals and scheduling are being updated to incorporate these new system capabilities, ensuring that our commitment to patient safety and fiscal discipline is maintained.

### 3.1. Infection Control and Quarantine Policy

In high-risk situations, infection control policies must be more stringent. Resource pairings may now impose temporary quarantine periods. When a pairing is created with a `quarantine_until_minute` value, neither of the paired resources may be scheduled for any new procedures that begin before the specified quarantine minute, regardless of their existing schedules or availability. This constraint is enforced during both proposal and scheduling operations.

### 3.2. Stricter Governance for High-Risk Overrides

While the system allows for protocol overrides in critical situations, these actions now require a higher level of administrative oversight to ensure accountability. For plans that have this stricter policy enabled, any proposal that bypasses the safety threshold lock will now require explicit authorization from a `HospitalAdministrator` before it can be scheduled.

Each authorization applies only to a single, specific assignment instance. The authorization record captures the `authorized_by_user_id` from the `X-User-ID` header of the authorizing administrator. If an authorized assignment is later cancelled or rejected, its authorization is considered consumed and cannot be reused for a new assignment, even if it is for the same procedure.

## 4. Financial Controls and Consistency

The new lifecycle tracking capabilities are fully integrated into the accounting system to maintain financial accuracy.

Cost estimates are recalculated at finalization based on the complete operational timeline at that moment. When the resource's usage baseline and the set of committed assignments on that resource remain unchanged between scheduling and finalization, the final charge must equal the scheduled estimate. Changes that affect the calculation include: recording new servicing events for the resource, or scheduling additional assignments on that resource that alter the cumulative usage indices. 

To maintain the system's conservative forecasting principles from the base workflow, initial cost estimates reflect the resource's complete projected commitment across all unresolved work—including procedures scheduled for later execution—measured from its most recent servicing baseline. At scheduling time, the system recalculates the assignment's cost by considering all other committed assignments on the same resource, excluding the target assignment's own provisional minutes from the cumulative usage calculation to prevent self-inflation. The final cost calculation must accurately reflect when each resource enters its maintenance cycle and the cumulative usage at each procedure's start time.

## 5. API Contract Additions

To support these new capabilities, several new resources and endpoints have been introduced. The public-facing contract for all existing endpoints remains unchanged to ensure backward compatibility.

### 5.0. Time Window Semantics

All time-based windows in the system use **half-open intervals** `[start_minute, end_minute)`, where the start is inclusive and the end is exclusive. An event or procedure at minute M "overlaps" a window `[A, B)` if `M >= A` and `M < B`. Two procedures or holds are said to overlap if they share any minute under this definition. Edge-touching is explicitly allowed in certain contexts (documented per feature).

### 5.1. New Resources
* `MaintenanceEvent`: Records a servicing event. Contains `id`, `plan_id`, `resource_id`, `at_minute`, `created_at`, `version`. This is a create-only resource with no update or delete operations; `version` is always `1`. Optimistic concurrency control does not apply to this resource as it is immutable after creation.
* `ResourceHold`: Represents a planned unavailability window. Contains `id`, `plan_id`, `resource_id`, `start_minute`, `end_minute`, `reason`, `status` (enum: `ACTIVE`, `CANCELLED`), `created_at`, `updated_at`, `version`. The `status` can transition from `ACTIVE` to `CANCELLED`, which increments the `version`. The cancel operation supports optimistic concurrency control.
* `OverrideAuthorization`: Records administrative approval for a risky override. Contains `id`, `plan_id`, `assignment_id`, `authorized_by_user_id`, `created_at`. The `authorized_by_user_id` is extracted from the `X-User-ID` header. This resource is created once per assignment and is immutable thereafter.

### 5.2. Additive Fields
* An optional `maintenance_threshold_override` (integer, nullable) field has been added to the `MedicalResource` resource. When set to a non-negative integer, it specifies the operational threshold (in minutes) at which this specific resource begins to incur elevated bio-risk surcharges. When null or absent, the resource follows the standard maintenance cycle threshold. A value of 0 indicates all operational minutes are immediately subject to bio-risk surcharges.
* An optional `quarantine_until_minute` (integer) field has been added to the `InfectionRiskPairing` resource.
* An optional `policies` object has been added to `TreatmentPlan`, containing:
  - `require_admin_auth_for_overrides` (boolean, default: false): When enabled, risky override assignments require administrative authorization before scheduling.

### 5.3. New Endpoints

| Method | Path                                                                      | Description                                      | Authorized Role(s)      | Success Code | Response Body |
|:-------|:--------------------------------------------------------------------------|:-------------------------------------------------|:------------------------|:-------------|:--------------|
| POST   | `/treatment-plans/{planId}/maintenance-events`                            | Record a new servicing event for a resource.     | ChargeNurse             | 201 Created  | MaintenanceEvent object |
| GET    | `/treatment-plans/{planId}/maintenance-events`                            | List all servicing events for a plan (sorted by `created_at` ascending). | Any | 200 OK | Array of MaintenanceEvent objects |
| GET    | `/treatment-plans/{planId}/maintenance-events/{id}`                       | Get a specific servicing event.                  | Any                     | 200 OK | MaintenanceEvent object |
| POST   | `/treatment-plans/{planId}/resource-holds`                                | Place a temporary hold on a resource.            | ChargeNurse             | 201 Created | ResourceHold object |
| GET    | `/treatment-plans/{planId}/resource-holds`                                | List all resource holds for a plan (sorted by `created_at` ascending). | Any | 200 OK | Array of ResourceHold objects |
| GET    | `/treatment-plans/{planId}/resource-holds/{holdId}`                       | Get a specific resource hold.                    | Any                     | 200 OK | ResourceHold object |
| POST   | `/treatment-plans/{planId}/resource-holds/{holdId}/cancel`                | Cancel an active resource hold. Accepts optional `version` for optimistic concurrency. | ChargeNurse | 200 OK | Updated ResourceHold object |
| POST   | `/treatment-plans/{planId}/assignments/{assignmentId}/override-authorize` | Provide administrative authorization for an override (only when plan policy is enabled). | HospitalAdministrator   | 201 Created | OverrideAuthorization object |

All list endpoints include standard pagination metadata: `limit`, `offset`, `total_count`, `has_more`. List endpoints validate that the specified plan exists and return `404 ERR_PLAN_NOT_FOUND` if the plan is not found. Individual resource GET endpoints follow the hierarchical validation pattern established in the existing system: they first verify the parent plan exists (returning `ERR_PLAN_NOT_FOUND` if not), then verify the specific resource exists and belongs to that plan (returning the resource-specific 404 error if not found or if it belongs to a different plan).

### 5.4. Error Code Catalogue

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