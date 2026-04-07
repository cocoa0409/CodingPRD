# Hazardous Cargo Logistics API - Product Requirements Document

## 1. Hazardous Cargo Logistics API

This document outlines the requirements for the Hazardous Cargo Logistics API, a system designed to manage the complex process of planning, scheduling, and executing the stowage of hazardous and general cargo across maritime voyages. The system enforces strict compliance rules, manages intricate scheduling constraints, and tracks voyage economics in real-time.

## 2. Global Specifications

### 2.1 Authentication & User Context

All interactions with the API require authenticated user context, determined by two mandatory HTTP request headers:

*   `X-User-ID`: (string) The unique identifier of the user making the request.
*   `X-User-Role`: (string) The role assigned to the user. The system recognizes the following roles:
    *   `LogisticsCoordinator`: Oversees the voyage lifecycle, compliance approvals, and scheduling confirmations.
    *   `CargoPlanner`: Manages port calls, contracts, stowage locations, and proposes stowage plans.
    *   `PortAuthority`: Responsible for the final authorization and completion of the voyage manifest.

Failure to provide these headers, or providing an invalid role, will result in a `400 Bad Request` with `error_id: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Actions attempted by roles without the necessary authorization will result in a `403 Forbidden` with `error_id: ERR_INSUFFICIENT_PERMISSIONS`.

### 2.2 Standard Success Response Format

All successful API responses (2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-08-04T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 15,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

*   The `api_request_id` is a server-generated unique identifier for the request.
*   The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp.
*   Pagination fields (`limit`, `offset`, `total_count`, `has_more`) are included in the `meta` object for list endpoints.
*   The `response_type` is either "object" for a single resource or "array" for a list.
*   The `data` field contains the resource(s). All list endpoints return results sorted by `created_at` in ascending order. All resources utilize a UUID format for their `id` field and track creation (`created_at`) and modification (`updated_at`) timestamps.

### 2.3 Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-08-04T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

## 3. Business Logic & Workflows

### 3.1 Voyage Lifecycle and Economic Framework

The core container for all operations is the `VoyageManifest`. A manifest represents a single voyage and serves as the boundary for economic and compliance tracking.

A manifest is created by a LogisticsCoordinator with a `voyage_name` and a `total_revenue_potential` (a double-precision number representing the maximum revenue this voyage can generate).

The manifest lifecycle progresses through several states, tracked by the `status` field:
1.  `PLANNING`: The initial state upon creation.
2.  `ACTIVE`: The manifest must be activated (via `/activate`) to allow the creation of port calls, contracts, and stowage plans. If an attempt is made to activate a manifest not in the PLANNING state, an `ERR_MANIFEST_NOT_IN_PLANNING` error occurs.
3.  `FINAL_REVIEW_PENDING`: Once all operational planning is complete, the manifest is moved to this state. This transition is only permitted if there are no stowage plans remaining in unresolved states (PENDING_APPROVAL or COMPLIANCE_APPROVED). If unresolved plans exist, the request will fail (`ERR_UNRESOLVED_PLANS_EXIST`).
4.  `COMPLETED`: The final, terminal state achieved after successful revenue realization by the PortAuthority.

Operations requiring an ACTIVE manifest will fail with `ERR_MANIFEST_NOT_ACTIVE` if the manifest is in any other state.

The manifest exposes key derived metrics:
*   `revenue_balance` (read-only): The remaining available revenue potential, calculated by subtracting the sum of all provisionally allocated and finalized revenue from the `total_revenue_potential`.
*   `compliance_risk_score` (read-only): The current compliance standing of the voyage (see Section 3.5).

### 3.2 Operational Planning: Port Calls and Cargo

Once a manifest is ACTIVE, CargoPlanners can define the operational structure.

#### 3.2.1 Port Calls

A `PortCall` represents a scheduled stop within the voyage, linked by its `manifest_id`. It requires a `name` and an operational window defined by `start_hour` and `end_hour` (integers). The end hour must be strictly greater than the start hour (`ERR_INVALID_PORT_CALL_HOURS`).

Port Calls also follow a lifecycle (`status`):
*   `PLANNING`: The initial state.
*   `READY_FOR_STOWAGE`: A LogisticsCoordinator can transition the Port Call to this state only when all associated cargo contracts are in the ASSIGNED state, signaling that the port call's cargo obligations have been fully scheduled. This state serves as a manifest-level checkpoint. The transition is only possible if the port call contains at least one cargo contract. An attempt to move a port call to this state when its cargo is not yet fully scheduled will result in `ERR_CONTRACTS_NOT_ASSIGNED`.
*   `COMPLETED`: Automatically transitions when all associated contracts are either COMPLETED or CANCELLED.
*   `CANCELLED`: A Port Call can be cancelled from PLANNING or READY_FOR_STOWAGE.

Attempting an illegal state transition results in `ERR_ILLEGAL_PORT_CALL_STATE_TRANSITION`.

**Cancellation Impact:** Cancelling a Port Call has a cascading effect. All associated contracts and their stowage plans (that are not already completed) are immediately moved to the `CANCELLED` state. Any provisional revenue associated with these plans is released back into the manifest's `revenue_balance`, and any compliance penalties applied by those plans are reversed.

#### 3.2.2 Cargo Contracts

A `CargoContract` defines a specific shipment within a Port Call (linked by `port_call_id` and `manifest_id`). It includes `cargo_type` (string), `cargo_class` (must be `GENERAL`, `HAZMAT`, or `REEFER`), and its own handling window (`start_hour`, `end_hour`). The `duration_hours` is a derived, read-only field. Invalid hours result in `ERR_INVALID_CONTRACT_HOURS`.

For HAZMAT cargo, a `required_imdg_class_code` may be specified. Valid codes are `IMDG_CLASS_1.1` and `IMDG_CLASS_6.1`. If the cargo is not hazardous, this should be `NONE` (the default).

Contract `status` tracks the fulfillment process:
*   `PENDING`: Awaiting a stowage proposal.
*   `STOWAGE_PROPOSED`: A stowage plan has been submitted and is awaiting approval.
*   `ASSIGNED`: The stowage plan has been fully scheduled.
*   `COMPLETED`: Automatically transitions when the associated stowage plan is finalized.
*   `CANCELLED`: The contract is voided.

A CargoPlanner can explicitly cancel a contract only if it is in the PENDING state (`ERR_CONTRACT_NOT_PENDING_FOR_CANCEL`).

### 3.3 Vessel Configuration and Stowage Locations

CargoPlanners must define the available `StowageLocation` resources within a manifest (linked by `manifest_id`). Each location has a `location_code`, `location_model`, and a `stowage_revenue_per_hour` (the base rate for utilizing this location).

#### 3.3.1 HAZMAT Certifications

Locations can be certified for hazardous materials. Certifications are added to the `location_certifications` array. Each certification is a distinct record, uniquely identified by its `id`, and contains a `name` (e.g., `IMDG_CLASS_1.1` or `IMDG_CLASS_6.1`) and an `applied_date` (YYYY-MM-DD). A certification is only considered valid for stowage planning if the `applied_date` is on or before the date of the stowage proposal request.

#### 3.3.2 Proximity Conflicts

LogisticsCoordinators can define inherent conflicts between locations using `ProximityConflict` resources within a `manifest_id`. This requires specifying `location_id_1` and `location_id_2`. A location cannot conflict with itself (`ERR_SELF_CONFLICT`). An optional `reason` can be provided. These conflicts restrict the simultaneous scheduling of cargo within the same port call (See 3.4.1).

### 3.4 The Stowage Planning and Approval Workflow

The core operational task is the creation and approval of a `StowagePlan`, which links a `CargoContract` to a `StowageLocation` within a `manifest_id`.

#### 3.4.1 Proposing a Stowage Plan

A CargoPlanner proposes a plan by submitting a `contract_id` and `location_id`. The system performs several critical validations:

1.  **Status Checks:** The manifest must be ACTIVE, and the contract must be PENDING (`ERR_CONTRACT_NOT_PENDING`).
2.  **Certification Check:** If the contract has a `required_imdg_class_code` other than NONE, the location must possess a matching, valid certification. Failure results in `ERR_CERTIFICATION_MISMATCH`.
3.  **Scheduling Conflicts:** The proposed plan's time window must not overlap with existing plans (in PENDING_APPROVAL, COMPLIANCE_APPROVED, SCHEDULED, or COMPLETED states) on the same location, accounting for required reshuffle delays (See 3.6.1).
4.  **Proximity Check:** The proposed location must not have a `ProximityConflict` with any other location that is already utilized by a different plan within the *same Port Call* (statuses PENDING_APPROVAL, COMPLIANCE_APPROVED, SCHEDULED, or COMPLETED). If a conflict exists, the proposal is rejected with `ERR_PROXIMITY_CONFLICT`.
5.  **Economic Check:** The system calculates the `provisional_revenue` for the plan (See 3.6.2). If this exceeds the manifest's current `revenue_balance`, the request fails (`ERR_INSUFFICIENT_REVENUE_POTENTIAL`, HTTP 402).
6.  **Compliance Floor Check:** The system assesses if the plan triggers High Stress operations (See 3.5). If it does, and the resulting compliance score penalties would breach the system's compliance floor, the proposal may be rejected unless a special permit is invoked (See 3.5.2).

Upon successful creation, the plan enters the `PENDING_APPROVAL` `status`, the contract moves to `STOWAGE_PROPOSED`, and the `provisional_revenue` is deducted from the `revenue_balance`. The plan records whether it `is_high_stress`. It also records if `used_special_permit` was invoked (based on the `use_special_permit` input) and if the corresponding penalty was applied (`special_permit_penalty_applied`).

#### 3.4.2 Approval and Scheduling

The Stowage Plan lifecycle involves several steps managed by the LogisticsCoordinator:

1.  `PENDING_APPROVAL`: The initial state. The coordinator can either reject or approve compliance.
2.  `COMPLIANCE_APPROVED`: The plan has passed initial review (via `/compliance-approve`). If the plan is not PENDING_APPROVAL, this fails with `ERR_PLAN_NOT_PENDING_APPROVAL`.
3.  `SCHEDULED`: The plan is officially confirmed (via `/schedule`). This requires the plan to be COMPLIANCE_APPROVED (`ERR_PLAN_NOT_COMPLIANCE_APPROVED`) and the contract to be STOWAGE_PROPOSED (`ERR_CONTRACT_NOT_STOWAGE_PROPOSED`).
    *   Crucially, upon scheduling, the system *re-evaluates* the scheduling conflict validations against any newly approved or scheduled plans (`ERR_RESHUFFLE_TIME_VIOLATION`).
    *   Furthermore, the `provisional_revenue` and `is_high_stress` status are recalculated based on the total *committed* hours (COMPLIANCE_APPROVED and SCHEDULED) at the time of scheduling. If the revenue increases, the system must verify sufficient `revenue_balance` remains (`ERR_INSUFFICIENT_REVENUE_POTENTIAL`). The compliance score is adjusted if the stress status changes.
4.  `REJECTED`: If rejected from PENDING_APPROVAL, the contract returns to PENDING, and all provisional revenue and compliance penalties are reversed.
5.  `CANCELLED`: A plan can be cancelled from PENDING_APPROVAL, COMPLIANCE_APPROVED, or SCHEDULED (`ERR_PLAN_NOT_CANCELLABLE`). Similar to rejection, the contract returns to PENDING, and economic/compliance impacts are reversed.
6.  `COMPLETED`: Achieved only during voyage finalization.

### 3.5 Compliance, Risk, and High-Stress Operations

The system maintains a `compliance_risk_score` for every Voyage Manifest, initialized at 1000 points. A higher score indicates better compliance. The score cannot drop below 0.

#### 3.5.1 High-Stress Operations and Penalties

A stowage location enters "High Stress" when the cumulative utilization hours allocated to it exceeds the standard operational threshold of 100 hours.

When a `StowagePlan` is proposed, the system calculates the total utilization hours for the location (including the new plan and all existing plans in PENDING_APPROVAL, COMPLIANCE_APPROVED, or SCHEDULED states). If the new plan causes the total hours to exceed the threshold, or if the threshold was already exceeded, the plan is flagged as `is_high_stress`.

If a plan is flagged as High Stress upon creation (or later upon scheduling if its status changes), an IMDG Violation Penalty of 50 points is immediately deducted from the manifest's compliance score. If a plan is cancelled, rejected, or its stress status changes from true to false during scheduling or finalization, the 50 points are restored.

#### 3.5.2 Compliance Floor and Special Permits

The system enforces a Compliance Score Floor Lock at 500 points. If applying the IMDG Violation Penalty (50 points) for a new High Stress plan would cause the compliance score to drop to or below this floor (500), the proposal is automatically rejected with `ERR_COMPLIANCE_SCORE_FLOOR_BREACHED` (HTTP 403).

However, the CargoPlanner can override this rejection by including `use_special_permit: true` in the proposal payload. If the permit is used to bypass the floor lock:
1.  The proposal is accepted (assuming other validations pass).
2.  The standard IMDG Violation Penalty (50 points) is applied.
3.  An *additional* Special Permit Usage Penalty of 100 points is deducted.
4.  The plan records that `used_special_permit` is true (immutable) and `special_permit_penalty_applied` is true.

If the special permit is used unnecessarily (i.e., the floor was not breached), the extra penalty is not applied.

### 3.6 Scheduling Constraints and Revenue Calculation

#### 3.6.1 Reshuffle Delays

To ensure safe operations, a mandatory Container Reshuffle Delay of 2 hours is required between contracts utilizing the same Stowage Location, *unless* the cargo classes are identical, or if either the preceding or succeeding cargo class is `GENERAL`.

If the required delay is not respected between the proposed plan and any existing plan (in PENDING_APPROVAL, COMPLIANCE_APPROVED, SCHEDULED, or COMPLETED states), the request is rejected with `ERR_RESHUFFLE_TIME_VIOLATION`. This check is performed both at proposal time and again at scheduling time.

#### 3.6.2 Revenue Calculation and Stress Surcharge

The revenue generated by a Stowage Plan is based on the `stowage_revenue_per_hour` of the location and the `duration_hours` of the contract.

However, hours classified as "High Stress" (those exceeding the 100-hour threshold for the location) are billed at a premium rate. The Stress Surcharge Multiplier is 2.0 (double the base rate).

The calculation must determine exactly which portion of the contract's hours fall into the standard rate and which fall into the stress rate, based on the cumulative usage of the location when the plan is added.

### 3.7 Voyage Finalization and Revenue Realization

The final step of the voyage is handled by the PortAuthority via the `/finalize-manifest` endpoint. This is only possible if the manifest is in the `FINAL_REVIEW_PENDING` state (`ERR_MANIFEST_NOT_READY_FOR_FINALIZATION`).

This process is a complex, atomic transaction that realizes the revenue for all `SCHEDULED` plans and completes the voyage.

1.  **Sequential Processing:** The system must process all SCHEDULED plans in the precise order they occurred to ensure accurate economic outcomes. This means processing them chronologically based on their contract's `start_hour`. In the event of identical start times, the `StowagePlan` ID is used as a tie-breaker for deterministic ordering.
2.  **Cumulative Recalculation:** For each plan in sequence, the system recalculates the revenue and High Stress status based on the *actual* cumulative hours used on its location up to that point in the sequence.
3.  **Revenue Realization:** The recalculated revenue becomes the plan's `final_revenue` (a derived, read-only field).
4.  **Compliance Adjustment:** If the `is_high_stress` status changes during this recalculation (compared to its status when it was scheduled), the compliance score is adjusted accordingly (applying or reverting the 50-point penalty).
5.  **State Updates:** The plan and its associated contract are moved to `COMPLETED`.
6.  **Port Call Completion:** If all contracts within a Port Call are now COMPLETED or CANCELLED, the Port Call is moved to `COMPLETED`.
7.  **Economic Finalization:** The total `final_revenue` across all plans replaces the previous `provisional_revenue` allocations (provisional revenue is zeroed out).
8.  **Transactional Integrity Check:** The entire transaction is committed *only if* the total realized `final_revenue` for the entire manifest does not exceed the `total_revenue_potential`. If it does, the entire transaction is rolled back, the state remains `FINAL_REVIEW_PENDING`, and an `ERR_FINALIZATION_EXCEEDS_REVENUE_POTENTIAL` (402 Payment Required) error is returned.

If successful, the VoyageManifest moves to `COMPLETED`.

## 4. Endpoint Definitions

All successful creation operations return 201 Created, while other successful operations return 200 OK.

### 4.1 Voyage Management (LogisticsCoordinator & PortAuthority)

*   **POST /voyage-manifests**
    *   Role: LogisticsCoordinator
    *   Creates a new Voyage Manifest.
*   **GET /voyage-manifests**
    *   Lists all Voyage Manifests.
*   **GET /voyage-manifests/{manifestId}**
    *   Retrieves a specific Voyage Manifest.
*   **POST /voyage-manifests/{manifestId}/activate**
    *   Role: LogisticsCoordinator
    *   Activates the manifest (PLANNING -> ACTIVE).
*   **POST /voyage-manifests/{manifestId}/initiate-final-review**
    *   Role: LogisticsCoordinator
    *   Prepares the manifest for finalization (ACTIVE -> FINAL_REVIEW_PENDING).
*   **POST /voyage-manifests/{manifestId}/finalize-manifest**
    *   Role: PortAuthority
    *   Executes the final revenue realization and completes the manifest (FINAL_REVIEW_PENDING -> COMPLETED).

### 4.2 Port Call and Contract Management

*   **POST /voyage-manifests/{manifestId}/port-calls**
    *   Role: CargoPlanner
    *   Creates a new Port Call.
*   **GET /voyage-manifests/{manifestId}/port-calls**
    *   Lists Port Calls for a Manifest.
*   **GET /voyage-manifests/{manifestId}/port-calls/{portCallId}**
    *   Retrieves a specific Port Call.
*   **PUT /voyage-manifests/{manifestId}/port-calls/{portCallId}**
    *   Role: LogisticsCoordinator
    *   Updates a Port Call's status (e.g., setting `status` to READY_FOR_STOWAGE or CANCELLED).
*   **POST /voyage-manifests/{manifestId}/port-calls/{portCallId}/contracts**
    *   Role: CargoPlanner
    *   Creates a new Cargo Contract.
*   **GET /voyage-manifests/{manifestId}/port-calls/{portCallId}/contracts**
    *   Lists Cargo Contracts for a Port Call.
*   **GET /voyage-manifests/{manifestId}/port-calls/{portCallId}/contracts/{contractId}**
    *   Retrieves a specific Cargo Contract.
*   **POST /voyage-manifests/{manifestId}/port-calls/{portCallId}/contracts/{contractId}/cancel**
    *   Role: CargoPlanner
    *   Cancels a PENDING Cargo Contract.

*(Note: All GET endpoints for specific resources must verify existence and association with the parent manifest ID in the path, returning 404 errors such as `ERR_MANIFEST_NOT_FOUND`, `ERR_PORT_CALL_NOT_FOUND`, or `ERR_CONTRACT_NOT_FOUND` if not found.)*

### 4.3 Vessel Configuration

*   **POST /voyage-manifests/{manifestId}/stowage-locations**
    *   Role: CargoPlanner
    *   Defines a new Stowage Location.
*   **GET /voyage-manifests/{manifestId}/stowage-locations**
    *   Lists Stowage Locations for a Manifest.
*   **GET /voyage-manifests/{manifestId}/stowage-locations/{locationId}**
    *   Retrieves a specific Stowage Location (`ERR_LOCATION_NOT_FOUND`).
*   **POST /voyage-manifests/{manifestId}/stowage-locations/{locationId}/certifications**
    *   Role: CargoPlanner
    *   Adds a certification to a Stowage Location.
*   **POST /voyage-manifests/{manifestId}/proximity-conflicts**
    *   Role: LogisticsCoordinator
    *   Creates a Proximity Conflict.
*   **GET /voyage-manifests/{manifestId}/proximity-conflicts**
    *   Lists Proximity Conflicts.
*   **GET /voyage-manifests/{manifestId}/proximity-conflicts/{conflictId}**
    *   Retrieves a specific Proximity Conflict (`ERR_CONFLICT_NOT_FOUND`).

### 4.4 Stowage Planning and Approval

*   **POST /voyage-manifests/{manifestId}/stowage-plans**
    *   Role: CargoPlanner
    *   Proposes a new Stowage Plan.
*   **GET /voyage-manifests/{manifestId}/stowage-plans**
    *   Lists all Stowage Plans for a Manifest.
*   **GET /voyage-manifests/{manifestId}/stowage-plans/{planId}**
    *   Retrieves a specific Stowage Plan (`ERR_PLAN_NOT_FOUND`).
*   **POST /voyage-manifests/{manifestId}/stowage-plans/{planId}/compliance-approve**
    *   Role: LogisticsCoordinator
    *   Approves the compliance of a proposed plan (PENDING_APPROVAL -> COMPLIANCE_APPROVED).
*   **POST /voyage-manifests/{manifestId}/stowage-plans/{planId}/schedule**
    *   Role: LogisticsCoordinator
    *   Schedules an approved plan (COMPLIANCE_APPROVED -> SCHEDULED).
*   **POST /voyage-manifests/{manifestId}/stowage-plans/{planId}/reject**
    *   Role: LogisticsCoordinator
    *   Rejects a proposed plan (PENDING_APPROVAL -> REJECTED).
*   **POST /voyage-manifests/{manifestId}/stowage-plans/{planId}/cancel**
    *   Role: LogisticsCoordinator
    *   Cancels a plan (PENDING_APPROVAL, COMPLIANCE_APPROVED, or SCHEDULED -> CANCELLED).

## 5. Error Code Catalogue

| Error ID                                     | HTTP Status Code     |
| :------------------------------------------- | :------------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request      |
| `ERR_INVALID_REQUEST`                        | 400 Bad Request      |
| `ERR_INVALID_PORT_CALL_HOURS`                | 400 Bad Request      |
| `ERR_INVALID_CONTRACT_HOURS`                 | 400 Bad Request      |
| `ERR_CERTIFICATION_MISMATCH`                 | 400 Bad Request      |
| `ERR_SELF_CONFLICT`                          | 400 Bad Request      |
| `ERR_INSUFFICIENT_REVENUE_POTENTIAL`         | 402 Payment Required |
| `ERR_FINALIZATION_EXCEEDS_REVENUE_POTENTIAL` | 402 Payment Required |
| `ERR_INSUFFICIENT_PERMISSIONS`               | 403 Forbidden        |
| `ERR_COMPLIANCE_SCORE_FLOOR_BREACHED`        | 403 Forbidden        |
| `ERR_MANIFEST_NOT_FOUND`                     | 404 Not Found        |
| `ERR_PORT_CALL_NOT_FOUND`                    | 404 Not Found        |
| `ERR_CONTRACT_NOT_FOUND`                     | 404 Not Found        |
| `ERR_LOCATION_NOT_FOUND`                     | 404 Not Found        |
| `ERR_PLAN_NOT_FOUND`                         | 404 Not Found        |
| `ERR_CONFLICT_NOT_FOUND`                     | 404 Not Found        |
| `ERR_MANIFEST_NOT_ACTIVE`                    | 409 Conflict         |
| `ERR_MANIFEST_NOT_IN_PLANNING`               | 409 Conflict         |
| `ERR_MANIFEST_NOT_READY_FOR_FINALIZATION`    | 409 Conflict         |
| `ERR_CONTRACT_NOT_PENDING`                   | 409 Conflict         |
| `ERR_CONTRACT_NOT_PENDING_FOR_CANCEL`        | 409 Conflict         |
| `ERR_CONTRACT_NOT_STOWAGE_PROPOSED`          | 409 Conflict         |
| `ERR_RESHUFFLE_TIME_VIOLATION`               | 409 Conflict         |
| `ERR_PROXIMITY_CONFLICT`                     | 409 Conflict         |
| `ERR_PLAN_NOT_PENDING_APPROVAL`              | 409 Conflict         |
| `ERR_PLAN_NOT_COMPLIANCE_APPROVED`           | 409 Conflict         |
| `ERR_PLAN_NOT_CANCELLABLE`                   | 409 Conflict         |
| `ERR_ILLEGAL_PORT_CALL_STATE_TRANSITION`     | 409 Conflict         |
| `ERR_CONTRACTS_NOT_ASSIGNED`                 | 409 Conflict         |
| `ERR_UNRESOLVED_PLANS_EXIST`                 | 409 Conflict         |