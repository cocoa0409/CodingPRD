# Event Staffing Platform - Product Requirements Document

## 1. Overview

The Event Staffing Platform is a comprehensive API system designed to manage the complete lifecycle of staffing engagements for events. This platform facilitates the coordination between event organizers, staffing coordinators, and individual staff members, ensuring that events are properly staffed while maintaining compliance with labor regulations and financial controls.

The system addresses the complex challenges of modern event staffing: matching qualified personnel to specific roles, managing scheduling conflicts, tracking certifications, calculating overtime compensation, monitoring compliance risks, and ensuring accurate payroll processing. Through a carefully orchestrated set of workflows, the platform transforms the traditionally chaotic process of event staffing into a structured, auditable, and efficient operation.

At its core, the platform revolves around Staffing Contracts - comprehensive engagements between staffing agencies and their clients that encompass multiple events, each with their own unique staffing requirements. The system maintains strict financial controls, sophisticated conflict resolution mechanisms, and automated compliance monitoring to protect both the staffing agency and its workforce.

## 2. Global Specifications

### 2.1 Authentication & User Context

User context is determined by two mandatory HTTP request headers for all endpoints:
* `X-User-ID`: (string) The unique identifier of the user making the request. This ID is used for authorization checks and data association.
* `X-User-Role`: (string) The role assigned to the user. Must be one of the following values: StaffingCoordinator, StaffMember, AccountManager.
* Failure to provide these headers will result in a `400 Bad Request` with `error_id: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.

### 2.2 Response Formats

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

* The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
* The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp.
* The `response_type` is either "object" for a single resource or "array" for a list of resources. For 2xx responses with no data, it contains an empty object.

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

### 2.4 Resource Scoping and Data Isolation

The StaffingContract serves as the absolute boundary for all data within an engagement. Every resource, such as an event, shift, or staff profile, is inextricably linked to a single parent contract. The platform enforces this isolation rigorously. When fetching any resource, the system first verifies that the resource belongs to the contract specified in the request path. If a mismatch is detected, or if the specified parent contract does not exist, the system will indicate that the requested resource cannot be found, protecting against both accidental data leakage and unauthorized access.

### 2.5 Ledger Systems

The platform employs sophisticated ledger systems to track financial and compliance metrics across engagements. These ledgers operate as append-only logs with specialized increment and decrement operations that maintain data integrity and provide audit trails.

The financial tracking ledger monitors the monetary flow through each engagement, distinguishing between provisional allocations (estimates based on proposed work) and finalized disbursements (actual payments made). This dual-track system enables real-time budget monitoring while maintaining flexibility for last-minute changes.

A separate compliance monitoring system tracks risk factors that could lead to labor law violations or operational difficulties. This system assigns point values to various risk events and maintains a cumulative score that influences system behavior when certain thresholds are reached.

### 2.6 System Invariants

The system must uphold the following invariants at all times. Endpoints that perform state transitions must include logic to verify these invariants are not violated.

#### 2.6.1 Fiscal Integrity Invariant

All financial operations must adhere to the principle that an engagement's expenditures cannot exceed its allocated budget. This is expressed by the formula:

`(provisional_debits + finalized_debits) <= total_budget`

*   `total_budget`: The immutable total budget of the parent StaffingContract.
*   `provisional_debits`: The sum of `provisional_cost` from all `Assignment` resources with status `PROPOSED`, `ACCEPTED`, or `CONFIRMED`. This represents funds that are committed but not yet paid.
*   `finalized_debits`: The sum of `final_payout` from all `Assignment` resources with status `PAID`. This represents funds that have been disbursed.

Any operation (e.g., creating or confirming an assignment) that would cause this invariant to be violated must be rejected with error `ERR_INSUFFICIENT_BUDGET`.

#### 2.6.2 Event Readiness Invariant

An Event can only be in the `READY_FOR_EXECUTION` state if the following conditions are met simultaneously:

1.  **Shift Fulfillment:** The event must have at least one associated `Shift`, and all associated `Shift` resources must have a status of `FILLED`.
2.  **Contractual Risk Assessment:** The `compliance_risk_score` of the parent `StaffingContract` must be less than 15.

Any attempt to transition an `Event` to `READY_FOR_EXECUTION` when these conditions are not met must be rejected. If a change to the system (e.g., cancellation of a confirmed assignment) causes a `READY_FOR_EXECUTION` event to no longer meet these conditions, its status must be reverted to `PLANNING`.

### 2.7 Error Code Catalogues

#### Financial & Budgeting Errors

| Error ID | HTTP Status Code |
| :--- | :--- |
| `ERR_INSUFFICIENT_BUDGET` | 402 Payment Required |
| `ERR_PAYROLL_EXCEEDS_BUDGET` | 402 Payment Required |

#### State & Validation Errors

| Error ID | HTTP Status Code |
| :--- | :--- |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_IN_PLANNING` | 409 Conflict |
| `ERR_CONTRACT_NOT_READY_FOR_PAYROLL` | 409 Conflict |
| `ERR_SHIFT_NOT_OPEN` | 409 Conflict |
| `ERR_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_NOT_PENDING_CONFIRMATION` | 409 Conflict |
| `ERR_SHIFTS_NOT_FILLED` | 409 Conflict |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_ILLEGAL_EVENT_STATE_TRANSITION` | 409 Conflict |
| `ERR_INVALID_SHIFT_TIMES` | 400 Bad Request |

#### Staffing & Assignment Errors

| Error ID | HTTP Status Code |
| :--- | :--- |
| `ERR_STAFF_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONFLICT_PAIRING_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_MISSING` | 400 Bad Request |
| `ERR_REST_PERIOD_VIOLATION` | 409 Conflict |
| `ERR_INTERPERSONAL_CONFLICT` | 409 Conflict |
| `ERR_SELF_CONFLICT_PAIRING` | 400 Bad Request |
| `ERR_ASSIGNMENT_NOT_PROPOSED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_UNRESOLVED_ASSIGNMENTS_EXIST` | 409 Conflict |

#### Risk Management Errors

| Error ID | HTTP Status Code |
| :--- | :--- |
| `ERR_RISK_THRESHOLD_EXCEEDED` | 403 Forbidden |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |

### 2.8 Monetary Value Precision

All monetary values in the system, including budgets, pay rates, and calculated costs, are represented with two decimal places of precision, reflecting standard currency denomination in dollars and cents.

## 3. Resource Definitions

### 3.1 StaffingContract

The StaffingContract represents the top-level container for a single client engagement, holding all events, shifts, assignments, and financial ledgers.

* `id` (string, uuid): The unique identifier for the Staffing Contract.
* `client_name` (string): The name of the client for this engagement (e.g., "Gala for the Arts 2024").
* `status` (string): The overall status of the contract lifecycle. Valid values are `PLANNING`, `ACTIVE`, `PAYROLL_PENDING`, `CLOSED`.
* `total_budget` (number): The total budget allocated for staffing this entire contract.
* `budget_balance` (number, readOnly): A derived field representing the remaining budget, automatically synchronized with the BudgetLedger and calculated as total_budget minus provisional_debits minus finalized_debits. When a contract is created, this value is initialized to equal the `total_budget`.
* `compliance_risk_score` (integer, readOnly): A derived field reflecting the current value of the contract's ComplianceRiskLedger. When a contract is created, this value is initialized to 0.
* `created_at` (string, date-time): The timestamp when the contract was created.
* `updated_at` (string, date-time): The timestamp when the contract was last updated.

### 3.2 Event

An Event represents a specific function or occasion within a Staffing Contract, such as a rehearsal dinner or main reception.

* `id` (string, uuid): The unique identifier for the Event.
* `contract_id` (string, uuid): The ID of the parent StaffingContract this event belongs to.
* `name` (string): The human-readable name of the event (e.g., "Main Reception").
* `status` (string): The operational status of the event. Valid values are `PLANNING`, `READY_FOR_EXECUTION`, `CANCELLED`.
* `start_time` (integer): The official start time of the event, as a Unix timestamp (seconds since epoch).
* `end_time` (integer): The official end time of the event, as a Unix timestamp (seconds since epoch).
* `created_at` (string, date-time): The timestamp when the event was created.
* `updated_at` (string, date-time): The timestamp when the event was last updated.

### 3.3 Shift

A Shift represents a specific work block for a required role at an Event that needs to be filled by a staff member.

* `id` (string, uuid): The unique identifier for the Shift.
* `event_id` (string, uuid): The ID of the parent Event this shift belongs to.
* `role_name` (string): The role that needs to be filled for this shift (e.g., "Bartender").
* `status` (string): The fulfillment status of the shift. Valid values are `OPEN`, `PENDING_CONFIRMATION`, `FILLED`, `CANCELLED`.
* `certification_needed` (string): The specific certification required for a staff member to be eligible for this shift. Valid values are `FOOD_HANDLER_PERMIT`, `ALCOHOL_SERVICE_LICENSE`, `NONE`. Default is `NONE`.
* `start_time` (integer): The start time of the work shift, as a Unix timestamp (seconds since epoch).
* `end_time` (integer): The end time of the work shift, as a Unix timestamp (seconds since epoch).
* `duration_hours` (number, readOnly): A derived field automatically calculated by the system as the difference between `end_time` and `start_time`.
* `created_at` (string, date-time): The timestamp when the shift was created.
* `updated_at` (string, date-time): The timestamp when the shift was last updated.
* `contract_id` (string, uuid): The ID of the parent StaffingContract this shift belongs to, added for rule simplification and direct querying.

### 3.4 StaffProfile

A StaffProfile is a record of a staff member, including their personal details, pay rate, and certifications, scoped to a specific StaffingContract.

* `id` (string, uuid): The unique identifier for the Staff Profile.
* `contract_id` (string, uuid): The ID of the parent StaffingContract this profile belongs to.
* `first_name` (string): The staff member's first name (e.g., "Jane").
* `last_name` (string): The staff member's last name (e.g., "Doe").
* `base_pay_rate_per_hour` (number): The standard hourly pay rate for this staff member.
* `certifications` (array): A list of certifications held by the staff member, where each certification contains:
  * `id` (string, uuid): The unique identifier for the certification record.
  * `name` (string): The name of the certification. Valid values are `FOOD_HANDLER_PERMIT`, `ALCOHOL_SERVICE_LICENSE`.
  * `issued_date` (string, date): The date the certification was issued.
  * `expiry_date` (string, date): The date the certification expires.
* `created_at` (string, date-time): The timestamp when the profile was created.
* `updated_at` (string, date-time): The timestamp when the profile was last updated.

### 3.5 Assignment

An Assignment is the critical resource linking a StaffProfile to a Shift, representing a work commitment.

* `id` (string, uuid): The unique identifier for the Assignment.
* `contract_id` (string, uuid): The ID of the StaffingContract this assignment falls under, used for scoping rules like rest periods and overtime.
* `shift_id` (string, uuid): The ID of the Shift being filled.
* `staff_profile_id` (string, uuid): The ID of the StaffProfile assigned to the shift.
* `status` (string): The lifecycle status of the assignment. Valid values are `PROPOSED`, `ACCEPTED`, `CONFIRMED`, `PAID`, `DECLINED`, `CANCELLED`.
* `override_risk_check` (boolean): Records if the compliance risk check was overridden for this assignment's proposal. This value is set on creation and is immutable thereafter.
* `risk_override_penalty_applied` (boolean, readOnly): A derived flag that is true if the RISK_OVERRIDE_PENALTY was added to the ComplianceRiskLedger for this assignment.
* `is_overtime_eligible` (boolean): A flag that is true if any portion of this assignment is paid at the overtime rate. This is first calculated at proposal and then refreshed upon confirmation to ensure the ComplianceRiskLedger is accurate.
* `provisional_cost` (number): The estimated cost of this assignment, including potential overtime. This value is first calculated at proposal and may be updated upon confirmation. It is an estimate; the final, authoritative cost is calculated during payroll finalization.
* `final_payout` (number, readOnly): A derived field calculated during payroll finalization. This is the actual amount to be paid to the staff member for this assignment, calculated based on a final snapshot of the staff member's total hours across the entire contract.
* `created_at` (string, date-time): The timestamp when the assignment was created.
* `updated_at` (string, date-time): The timestamp when the assignment was last updated.

When proposing a new assignment, the system performs a sequence of checks to ensure operational integrity. The order of these checks is critical. The system's first priority is to validate the fundamental eligibility of the staff member for the role, which primarily involves confirming they possess any required certifications. Only after confirming a staff member is qualified for a shift does the system proceed to evaluate scheduling-related constraints. It will first check for adherence to mandatory rest periods, and then for any potential interpersonal conflicts with other staff assigned to the same event. If all of these checks pass, the assignment is then evaluated against the contract's financial and risk management guardrails.

**Assignment Constraints and Validations:**

*   **Certification Matching:** If the associated `Shift.certification_needed` is not `NONE`, then the assigned `StaffProfile` must possess a valid, non-expired certification of the required type. An attempt to create an assignment without this will fail with `ERR_CERTIFICATION_MISSING`.
*   **Rest Period:** A staff member must have at least an 8-hour gap between the end of any shift and the beginning of another within the same `contract_id`.
    *   This check is performed at both proposal and confirmation time.
    *   At proposal, the check compares the proposed shift against all other shifts for that staff member with status `PROPOSED`, `ACCEPTED`, `CONFIRMED`, or `PAID`.
    *   At confirmation, the check compares the shift against all other shifts for that staff member with status `ACCEPTED`, `CONFIRMED`, or `PAID`.
    *   Violation of this rule results in `ERR_REST_PERIOD_VIOLATION`.
*   **Interpersonal Conflicts:** A staff member cannot be assigned to a shift if they have a `ConflictPairing` with another staff member already assigned to a shift in the same `Event`. This check is performed at proposal time against other assignments in `PROPOSED`, `ACCEPTED`, or `CONFIRMED` status. Violation results in `ERR_INTERPERSONAL_CONFLICT`.

### 3.6 ConflictPairing

A ConflictPairing indicates that two staff members cannot be assigned to shifts within the same Event for a specific StaffingContract. A staff member cannot be in conflict with themselves.

* `id` (string, uuid): The unique identifier for the conflict pairing record.
* `contract_id` (string, uuid): The ID of the StaffingContract this conflict pairing belongs to.
* `staff_profile_id_1` (string, uuid): The ID of the first staff member in the conflict pair.
* `staff_profile_id_2` (string, uuid): The ID of the second staff member in the conflict pair.
* `reason` (string, nullable): An optional, private note explaining the reason for the conflict (e.g., "Past workplace dispute").
* `created_at` (string, date-time): The timestamp when the conflict pairing was created.

### 3.7 AssignmentCreationPayload

The request body structure for creating a new assignment.

* `shift_id` (string, uuid): The ID of the Shift to be filled.
* `staff_profile_id` (string, uuid): The ID of the StaffProfile to assign to the shift.
* `override_risk_check` (boolean): If true, allows an AccountManager to bypass certain soft-fail validation checks, such as the compliance risk threshold. Default is false.

## 4. Endpoint Definitions

All successful creation operations return 201 Created, while other successful operations return 200 OK.

### 4.1 AccountManager Endpoints

#### POST /staffing-contracts/{contractId}/assignments
Proposes a new staff assignment for a shift within the specified contract. This endpoint initiates the assignment workflow by creating a proposed match between a staff member and an open shift.

**Validation Logic:**
1.  The `contractId` must be `ACTIVE`.
2.  The target `Shift` must exist and its status must be `OPEN`.
3.  The `StaffProfile` must exist and belong to the `contractId`.
4.  The assignment must adhere to all constraints defined in **Section 3.5 Assignment**, including certification, rest period, and interpersonal conflict checks.
5.  The assignment's provisional cost must adhere to the **Fiscal Integrity Invariant**.
6.  The assignment must pass all risk checks defined in **Section 5.4**.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Request Body:** AssignmentCreationPayload

**Success Response:** 201 Created - Returns the newly created Assignment resource

### 4.2 StaffingCoordinator Endpoints

#### POST /staffing-contracts/{contractId}/assignments/{assignmentId}/cancel
Cancels an existing assignment, removing the staff member from the shift and reversing any associated financial or compliance impacts.

**Validation Logic:**
1.  The assignment must exist and belong to the `contractId`.
2.  The assignment's status must not be `PAID`, `DECLINED`, or `CANCELLED`.
3.  Upon successful cancellation, the system reverses associated ledger entries and reverts the parent `Event`'s status if necessary (see **Section 5.6**).

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `assignmentId` (path, uuid): The unique identifier of the assignment to cancel

**Success Response:** 200 OK - Returns the updated Assignment resource

#### POST /staffing-contracts/{contractId}/assignments/{assignmentId}/confirm
Confirms an accepted assignment, finalizing the staff member's commitment to work the shift.

**Validation Logic:**
1.  The assignment must exist and belong to the `contractId`.
2.  The assignment's status must be `ACCEPTED`.
3.  The associated `Shift`'s status must be `PENDING_CONFIRMATION`.
4.  A renewed rest period check is performed as defined in **Section 3.5**.
5.  The system recalculates the `provisional_cost` and `is_overtime_eligible` flag based on the latest data.
6.  This new cost must adhere to the **Fiscal Integrity Invariant**.
7.  Corresponding adjustments are made to the `BudgetLedger` and `ComplianceRiskLedger`.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `assignmentId` (path, uuid): The unique identifier of the assignment to confirm

**Success Response:** 200 OK - Returns the updated Assignment resource

#### POST /staffing-contracts/{contractId}/conflict-pairings
Creates a record indicating that two staff members cannot work at the same event.

**Validation Logic:**
1.  The `contractId` must be `ACTIVE`.
2.  `staff_profile_id_1` and `staff_profile_id_2` must be different, valid `StaffProfile` IDs within the contract.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Request Body:**
- `staff_profile_id_1` (uuid): First staff member in the conflict pair
- `staff_profile_id_2` (uuid): Second staff member in the conflict pair
- `reason` (string, optional): Explanation for the conflict

**Success Response:** 201 Created - Returns the newly created ConflictPairing resource

#### GET /staffing-contracts/{contractId}/conflict-pairings
Lists all conflict pairings within a contract.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Success Response:** 200 OK - Returns an array of ConflictPairing resources

#### GET /staffing-contracts/{contractId}/conflict-pairings/{conflictPairingId}
Retrieves details of a specific conflict pairing.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `conflictPairingId` (path, uuid): The unique identifier of the conflict pairing

**Success Response:** 200 OK - Returns the requested ConflictPairing resource

#### POST /staffing-contracts/{contractId}/events
Creates a new event within a staffing contract.

**Validation Logic:**
1.  The `contractId` must be `ACTIVE`.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Request Body:**
- `name` (string): The name of the event
- `start_time` (integer): Unix timestamp for event start
- `end_time` (integer): Unix timestamp for event end

**Success Response:** 201 Created - Returns the newly created Event resource

#### GET /staffing-contracts/{contractId}/events
Lists all events within a contract.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Success Response:** 200 OK - Returns an array of Event resources

#### GET /staffing-contracts/{contractId}/events/{eventId}
Retrieves details of a specific event.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `eventId` (path, uuid): The unique identifier of the event

**Success Response:** 200 OK - Returns the requested Event resource

#### PUT /staffing-contracts/{contractId}/events/{eventId}
Updates an event's status, either marking it ready for execution or cancelling it.

**Validation Logic:**
1.  To update to `READY_FOR_EXECUTION`:
    *   The event's current status must be `PLANNING`.
    *   The request must adhere to the **Event Readiness Invariant**.
2.  To update to `CANCELLED`:
    *   The event's current status must be `PLANNING` or `READY_FOR_EXECUTION`.
    *   This action triggers a cascade of cancellations (see **Section 5.6**).

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `eventId` (path, uuid): The unique identifier of the event

**Request Body:**
- `status` (string): Either "READY_FOR_EXECUTION" or "CANCELLED"

**Success Response:** 200 OK - Returns the updated Event resource

#### POST /staffing-contracts/{contractId}/events/{eventId}/shifts
Creates a new shift requirement for an event.

**Validation Logic:**
1.  The `contractId` must be `ACTIVE`.
2.  The `end_time` must be after the `start_time`.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `eventId` (path, uuid): The unique identifier of the event

**Request Body:**
- `role_name` (string): The role to be filled
- `certification_needed` (string): Required certification (FOOD_HANDLER_PERMIT, ALCOHOL_SERVICE_LICENSE, or NONE)
- `start_time` (integer): Unix timestamp for shift start
- `end_time` (integer): Unix timestamp for shift end

**Success Response:** 201 Created - Returns the newly created Shift resource

#### GET /staffing-contracts/{contractId}/events/{eventId}/shifts
Lists all shifts for an event.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `eventId` (path, uuid): The unique identifier of the event

**Success Response:** 200 OK - Returns an array of Shift resources

#### GET /staffing-contracts/{contractId}/events/{eventId}/shifts/{shiftId}
Retrieves details of a specific shift.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `eventId` (path, uuid): The unique identifier of the event
- `shiftId` (path, uuid): The unique identifier of the shift

**Success Response:** 200 OK - Returns the requested Shift resource

#### POST /staffing-contracts/{contractId}/finalize-payroll
Finalizes payroll for a contract, calculating final payments and closing the engagement. All rules for this process are detailed in **Section 5.7**.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Success Response:** 200 OK - Returns the updated StaffingContract resource

#### POST /staffing-contracts/{contractId}/initiate-payroll
Moves a contract into the payroll pending state, signaling that all work is complete.

**Validation Logic:**
1.  The `contractId` must be `ACTIVE`.
2.  All assignments within the contract must have a terminal status (`CONFIRMED`, `CANCELLED`, or `DECLINED`).

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Success Response:** 200 OK - Returns the updated StaffingContract resource

#### POST /staffing-contracts/{contractId}/staff-profiles
Creates a new staff profile within a contract.

**Validation Logic:**
1.  The `contractId` must be `ACTIVE`.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Request Body:**
- `first_name` (string): Staff member's first name
- `last_name` (string): Staff member's last name
- `base_pay_rate_per_hour` (number): Hourly pay rate

**Success Response:** 201 Created - Returns the newly created StaffProfile resource

#### GET /staffing-contracts/{contractId}/staff-profiles
Lists all staff profiles within a contract.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Success Response:** 200 OK - Returns an array of StaffProfile resources

#### GET /staffing-contracts/{contractId}/staff-profiles/{staffProfileId}
Retrieves details of a specific staff profile.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `staffProfileId` (path, uuid): The unique identifier of the staff profile

**Success Response:** 200 OK - Returns the requested StaffProfile resource

#### POST /staffing-contracts/{contractId}/staff-profiles/{staffProfileId}/certifications
Adds a certification to a staff member's profile.

**Validation Logic:**
1.  The `contractId` must be `ACTIVE`.
2.  The `staffProfileId` must exist within the contract.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `staffProfileId` (path, uuid): The unique identifier of the staff profile

**Request Body:**
- `name` (string): Certification type (FOOD_HANDLER_PERMIT or ALCOHOL_SERVICE_LICENSE)
- `issued_date` (string, date): Date the certification was issued
- `expiry_date` (string, date): Date the certification expires

**Success Response:** 201 Created - Returns the updated StaffProfile resource

### 4.3 StaffMember Endpoints

#### POST /staffing-contracts/{contractId}/assignments/{assignmentId}/accept
Accepts a proposed assignment, indicating willingness to work the shift.

**Validation Logic:**
1.  The assignment must exist, belong to the `contractId`, and have a status of `PROPOSED`.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `assignmentId` (path, uuid): The unique identifier of the assignment to accept

**Success Response:** 200 OK - Returns the updated Assignment resource

#### POST /staffing-contracts/{contractId}/assignments/{assignmentId}/decline
Declines a proposed assignment, releasing the shift for other staff.

**Validation Logic:**
1.  The assignment must exist, belong to the `contractId`, and have a status of `PROPOSED`.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `assignmentId` (path, uuid): The unique identifier of the assignment to decline

**Success Response:** 200 OK - Returns the updated Assignment resource

### 4.4 General Endpoints

#### POST /staffing-contracts
Creates a new staffing contract for a client engagement.

**Request Body:**
- `client_name` (string): Name of the client
- `total_budget` (number): Total budget for the engagement

**Success Response:** 201 Created - Returns the newly created StaffingContract resource

#### GET /staffing-contracts
Lists all staffing contracts in the system.

**Success Response:** 200 OK - Returns an array of StaffingContract resources

#### GET /staffing-contracts/{contractId}
Retrieves details of a specific staffing contract.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Success Response:** 200 OK - Returns the requested StaffingContract resource

#### POST /staffing-contracts/{contractId}/activate
Activates a contract, allowing staffing operations to begin.

**Validation Logic:**
1.  The contract's status must be `PLANNING`.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Success Response:** 200 OK - Returns the updated StaffingContract resource

#### GET /staffing-contracts/{contractId}/assignments
Lists all assignments within a contract.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract

**Success Response:** 200 OK - Returns an array of Assignment resources

#### GET /staffing-contracts/{contractId}/assignments/{assignmentId}
Retrieves details of a specific assignment.

**Parameters:**
- `contractId` (path, uuid): The unique identifier of the staffing contract
- `assignmentId` (path, uuid): The unique identifier of the assignment

**Success Response:** 200 OK - Returns the requested Assignment resource

## 5. Business Rules

### 5.1 Contract & Event Lifecycle

The system enforces a strict lifecycle for contracts and events to ensure operational integrity.

*   **Contract Lifecycle:** A contract begins in `PLANNING` status. It can be moved to `ACTIVE` status, which is an irreversible transition that permits the creation of events, shifts, and assignments. From `ACTIVE`, it can move to `PAYROLL_PENDING` once all assignments are resolved. Finally, after successful payroll, it moves to `CLOSED`.
*   **Event Lifecycle:** An event begins in `PLANNING` status. It can be moved to `READY_FOR_EXECUTION` if it meets the **Event Readiness Invariant**. It can be `CANCELLED` from either `PLANNING` or `READY_FOR_EXECUTION` status.
*   **Shift Lifecycle:** A shift begins as `OPEN`. When an assignment is proposed, it becomes `PENDING_CONFIRMATION`. Upon confirmation, it becomes `FILLED`. If an assignment is cancelled, it reverts to `OPEN`.

### 5.2 Financial Governance

The financial health of every client engagement is of paramount importance. The system's financial operations are governed by the **Fiscal Integrity Invariant** defined in Section 2.6.1. This ensures that all assignment proposals, confirmations, and final payroll calculations are checked against the contract's budget. When assignment proposals encounter multiple validation failures, financial constraints are evaluated before other operational considerations, reflecting the fundamental requirement that no engagement can operate beyond its allocated resources.

### 5.3 Dynamic Cost Calculation

The fluid nature of staffing means that costs can shift as the overall picture evolves. When a coordinator confirms an accepted assignment, the system recalculates its `provisional_cost` based on the most up-to-date schedule. To do this, it looks at the total hours the staff member will have committed to after the current assignment is confirmed, and then determines how many hours from *this specific assignment* are the ones that cross the forty-hour overtime threshold. This ensures an accurate, up-to-the-minute cost projection. This recalculation is validated against the **Fiscal Integrity Invariant**. Furthermore, this confirmation step serves as a crucial reconciliation point for both financial and compliance ledgers. Any change in the assignment's provisional cost, or in its overtime status, results in an immediate and corresponding adjustment to the engagement's budget and risk score records.

### 5.4 Workforce Compliance and Risk Mitigation

Beyond financial considerations, the platform actively monitors factors that could lead to non-compliance with labor regulations or best practices. Central to this effort is a comprehensive risk scoring system that tracks potentially problematic patterns in staffing decisions. Each engagement maintains a cumulative risk metric that increases when certain conditions are met. Both it and the financial ledgers are managed with a principle of inviolable floors: while values can be incremented and decremented, no operation can ever cause a ledger's balance or score to fall below zero.

*   **Overtime Risk:** When an assignment is first **proposed** or **accepted**, the system performs a provisional overtime evaluation that aggregates hours from all of the staff member's assignments in `PROPOSED`, `ACCEPTED`, and `CONFIRMED` status. If including the newly introduced hours would push the staff member beyond the forty-hour threshold for the engagement, the platform immediately adds **5 points** to the `compliance_risk_score`. These provisional points persist (and are re-evaluated on every status change) until the assignment reaches a terminal outcome. They are automatically removed if the assignment is cancelled or declined, or—during final payroll reconciliation—if the week-wide tally shows the work did not, in fact, constitute overtime.
*   **Risk Threshold:** If a proposed assignment would cause the `compliance_risk_score` to become 20 or greater, it is blocked with `ERR_RISK_THRESHOLD_EXCEEDED`.
*   **Override Penalty:** An AccountManager may use the `override_risk_check` flag to bypass the risk threshold. Doing so incurs an additional 10-point penalty to the `compliance_risk_score`. The use of the override is recorded immutably on the assignment. This penalty reflects the risk inherent in bypassing safety controls, not the overtime status itself, and thus remains in effect regardless of subsequent schedule changes.

### 5.5 Assignment State Transitions

The assignment lifecycle represents a carefully choreographed dance between coordinators and staff members, with multiple decision points and state transitions.

*   **Proposal:** An assignment begins in `PROPOSED` status.
*   **Staff Response:** A staff member can transition a `PROPOSED` assignment to either `ACCEPTED` or `DECLINED`. These actions are final for the staff member.
*   **Coordinator Confirmation:** A coordinator can transition an `ACCEPTED` assignment to `CONFIRMED` after it passes all re-validation checks (see `POST /assignments/{assignmentId}/confirm`).
*   **Final States:** `CONFIRMED` assignments can become `PAID` during payroll. `DECLINED` and `CANCELLED` are terminal states.

### 5.6 Cancellation and Cascading Effects

Coordinators may cancel assignments in `PROPOSED`, `ACCEPTED`, or `CONFIRMED` status. A cancellation has the following effects:
*   The associated `Shift` reverts to `OPEN`.
*   The `provisional_cost` is reversed from the `BudgetLedger`.
*   Any `compliance_risk_score` points are reversed, including overtime assessments and any override penalties.
*   If the parent `Event` was `READY_FOR_EXECUTION`, its status is reverted to `PLANNING` because it no longer satisfies the **Event Readiness Invariant**.

Cancelling an `Event` triggers a comprehensive cancellation cascade. The `Event` itself, along with all associated `Shifts` and `Assignments`, will have their status updated to `CANCELLED`. This action also triggers the same financial and risk-related adjustments as cancelling a single assignment: the `provisional_cost` for each cancelled assignment is reversed from the `BudgetLedger`, and any `compliance_risk_score` points associated with them are also reversed.

### 5.7 Payroll Processing Lifecycle

The culmination of the staffing process is payroll - the point at which provisional estimates become actual payments.

*   **Initiation:** A contract moves from `ACTIVE` to `PAYROLL_PENDING` only when all its assignments are in a terminal state (`CONFIRMED`, `CANCELLED`, or `DECLINED`).
*   **Final Calculation:** The payroll finalization process is an atomic transaction that processes all `CONFIRMED` assignments chronologically by `shift.start_time`. It recalculates each staff member's total hours and determines the final overtime pay (1.5x base rate for hours over 40). It reconciles the `compliance_risk_score` based on the final overtime state of assignments.
*   **Budget Check:** Throughout this process, it validates against the **Fiscal Integrity Invariant**. If the total `final_payout` would exceed the `total_budget`, the entire transaction is rolled back, and the contract remains `PAYROLL_PENDING`.
*   **Closure:** On success, all processed assignments become `PAID`, the provisional ledger is cleared, and the contract becomes `CLOSED`.

### 5.8 Continuous Synchronization of Derived Values

Throughout all these operations, the platform maintains several derived values that provide real-time visibility into the engagement's status. The contract's remaining budget balance is continuously synchronized with the ledger system, calculated as the total budget minus both provisional allocations and finalized disbursements. Similarly, the compliance risk score shown on the contract always reflects the current value in the risk ledger. These synchronizations occur automatically whenever the underlying ledgers change, ensuring that users always see accurate, up-to-date information without manual refresh or recalculation.