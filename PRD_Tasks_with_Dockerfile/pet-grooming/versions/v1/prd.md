# Pet Grooming Services - Product Requirements Document

## 1. Pet Grooming Services

The Pet Grooming Services API provides a comprehensive system for managing the daily operations of a pet grooming salon within a larger veterinary clinic application. This API enables clinic staff to orchestrate complex scheduling workflows, manage resource allocation, and ensure pet safety through sophisticated constraint management.

## 2. Global Specifications

### 2.1 Authentication & User Context

The Pet Grooming Services API employs a role-based access control system to ensure that sensitive operations are restricted to authorized personnel. All API requests must include authentication headers that identify both the user and their operational role within the clinic.

* User context is determined by two mandatory HTTP request headers for all endpoints:
  * `X-User-ID`: (string) The unique identifier of the user making the request. This ID is used for authorization checks and data association.
  * `X-User-Role`: (string) The role assigned to the user. Must be one of the following values: ClinicManager, GroomingTechnician, BillingAdmin.
* Failure to provide these headers will result in a `400 Bad Request` with `error_id: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.

The system recognizes three distinct operational roles, each with specific permissions:
- **ClinicManager**: Senior staff members who oversee daily operations and can approve high-risk assignments
- **GroomingTechnician**: Primary users who create grooming jobs and propose station assignments
- **BillingAdmin**: Financial staff responsible for finalizing invoices and closing daily schedules

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

* The `api_request_id` is a server-generated unique identifier for the request.
* The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
* The `response_type` is either "object" for a single resource or "array" for a list of resources.
* The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object.

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

### 2.2 Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. In our approach to balancing comprehensive data delivery with performance considerations, clients can specify a `limit` parameter, an integer that, when not provided, defaults to a value of 50, with allowable ranges bounded between a minimum of 1 and a maximum of 200 to prevent overload. The number of initial items to skip is controlled by the `offset` parameter, an integer that, to support sequential data retrieval without gaps, defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

## 3. Business Logic & Workflows

### 3.1 Daily Schedule Management and Lifecycle

The foundation of the pet grooming system revolves around the concept of a GroomingDay, which serves as the primary container for all scheduling and resource management activities. To initiate a new day of operations, a `ClinicManager` must create a `GroomingDay` resource, providing a `schedule_name` to identify the day's template and a `total_supply_budget` representing the monetary allocation for supplies. Each `GroomingDay` begins its lifecycle in a `PLANNING` status, during which staff configure the day's structure and constraints. The resource includes essential fields such as a unique identifier in UUID format, the descriptive `schedule_name`, and the critical `total_supply_budget`. It also tracks its `status` through the day's lifecycle (`PLANNING`, `ACTIVE`, `INVOICING_PENDING`, `CLOSED`) and includes standard `created_at` and `updated_at` timestamps.

The system maintains two synchronized ledger-backed fields on each GroomingDay. The supply_stock_balance field provides real-time visibility into remaining supply budget by automatically calculating the difference between the total budget and both provisional and finalized costs tracked in the SupplyStockLedger. Similarly, the allergy_exposure_score field reflects the current accumulated risk level from the AllergyExposureLedger, with lower values indicating safer operating conditions.

Transitioning a GroomingDay from PLANNING to ACTIVE status requires explicit action by a ClinicManager through a dedicated activation endpoint. This transition locks the fundamental structure of the day and enables the creation of SessionBlocks, which serve as temporal subdivisions within the day's schedule.

### 3.2 Session Block Organization

Within each active GroomingDay, the schedule is divided into SessionBlocks that represent logical groupings of appointments. A `GroomingTechnician` can create these blocks by providing a `name` for easy identification (e.g., "Morning Appointments"), along with the `start_time` and `end_time` as Unix timestamps to define its temporal boundaries. Each SessionBlock maintains its own `status` field that progresses through a defined state machine, beginning in `PLANNING` status.

The SessionBlock resource contains a grooming_day_id linking it to its parent day, a human-readable name field for easy identification, critically important start_time and end_time fields stored as Unix timestamps in seconds since epoch, and standard created_at and updated_at timestamps. The temporal boundaries defined by these timestamps play a crucial role in job scheduling validation, as detailed in Section 3.5.

A `ClinicManager` can alter a block's operational state by submitting the new target `status`. A SessionBlock can only transition to `READY_FOR_GROOMING` status when all `GroomingJob`s within that block have achieved `CONFIRMED` status, a condition that also presupposes the existence of at least one job to confirm. This requirement ensures that the grooming team has a fully validated and non-empty schedule before beginning work. Conversely, if a confirmed assignment is later terminated, the system automatically downgrades the SessionBlock from `READY_FOR_GROOMING` back to `PLANNING` to ensure the schedule accurately reflects its new, unconfirmed state. Blocks in either `PLANNING` or `READY_FOR_GROOMING` status can also be explicitly `CANCELLED`.

### 3.3 Pet Service Requirements and Allergy Management

Individual pet grooming services are represented by GroomingJob resources, which capture the specific requirements for each pet's grooming session. Each job includes a `pet_id` identifying the animal, a `job_type` (e.g., "Full Groom"), tracks its fulfillment `status` (`PENDING`, `SCHEDULED`, `CONFIRMED`, `CANCELLED`), defines its service window with `start_time` and `end_time` Unix timestamps, contains a direct reference to its parent `grooming_day_id` for simplified querying, and includes standard `created_at` and `updated_at` timestamps. Beyond these standard identification fields and temporal boundaries, each GroomingJob includes sophisticated allergy management capabilities that directly influence scheduling decisions.

The required_allergen_type field, which defaults to NONE, uses an enumerated set of values including NUT_ALLERGY, GRASS_ALLERGY, and NONE to indicate special handling requirements. When a pet has a specific allergy, the system must ensure that any assigned GroomerStation possesses the corresponding safety capability, as described in Section 3.4.

Perhaps most critically, the GroomingJob resource incorporates a cannot_be_groomed_with_pet_ids field, which contains an array of UUID references to other pets. This field implements a crucial safety constraint: pets listed in this array must never be present in the same SessionBlock due to severe allergy conflicts that could endanger animal health. The validation of this constraint occurs during the job assignment process, as detailed in Section 3.5.

Each GroomingJob also maintains a calculated duration_minutes field that derives its value from the difference between start_time and end_time, converted to minutes. This read-only field updates automatically whenever the temporal boundaries change.

### 3.4 Groomer Station Capabilities

The physical infrastructure of the grooming salon is modeled through GroomerStation resources, which represent individual grooming stations with specific capabilities and cost structures. A `GroomingTechnician` can define these stations for a given day by providing a `station_name`, `station_type`, and the station's `supply_cost_per_hour`. Each station belongs to a specific GroomingDay, allowing for flexible daily configuration of available resources, and includes standard `created_at` and `updated_at` timestamps.

Beyond basic identification via a unique `id` and `station_name`, and categorization via `station_type`, each GroomerStation defines a `supply_cost_per_hour` rate that forms the basis for calculating grooming costs. This hourly rate applies to all jobs performed at the station, though actual costs may be modified by peak pricing rules as described in Section 3.6.

The special_capabilities field enables sophisticated matching between pet requirements and station capabilities. This array contains capability objects, each with a unique identifier (`id`), a `name` from the enumerated set (NUT_ALLERGY_SAFE, GRASS_ALLERGY_SAFE), and an `enabled_date` indicating when the capability was certified. A `GroomingTechnician` can add a new capability to a station by specifying its `name` and the date it was enabled. The presence of a specific capability in this array indicates that the station has the necessary equipment and supplies to safely groom pets with the corresponding allergy type.

### 3.5 Job Assignment Process and Validation Hierarchy

The JobAssignment resource serves as the critical nexus linking GroomingJobs to GroomerStations, and its creation, initiated via a POST request, triggers the most complex validation cascade in the entire system. When a GroomingTechnician proposes a new assignment, they must submit a request body containing the `job_id` of the service to be performed and the `station_id` where it will take place. An optional boolean, `override_allergy_check`, may also be included to handle high-risk scenarios. Based on this payload, the system evaluates multiple interdependent constraints in a specific order that reflects business priorities.

First, the system verifies foundational prerequisites. The most important of these is that the parent GroomingDay must be in an `ACTIVE` state; no assignments can be proposed for a day that is still in `PLANNING`. It also verifies that the target GroomingJob exists within that GroomingDay and currently holds PENDING status. Jobs in any other status cannot receive new assignments, preventing double-booking and maintaining schedule integrity. Once an assignment is successfully proposed, the GroomingJob transitions to a SCHEDULED state, awaiting final confirmation.

Second, capability matching ensures pet safety by confirming that stations possess necessary allergy-handling capabilities. For any job where required_allergen_type is not NONE, the system constructs the required capability name by appending '_SAFE' to the allergen type and searches the station's special_capabilities array for a matching entry.

Third, the groomer break validation protects staff welfare by enforcing mandatory rest periods. The system examines all existing assignments for the proposed station where status is PROPOSED, CONFIRMED, or COMPLETE. For each existing assignment, it retrieves the associated GroomingJob and calculates whether a minimum break period exists between jobs. This break period, defined as 15 minutes by system configuration, must separate the end of one job from the start of another, accounting for break time both before and after each job.

Fourth, pet allergy conflict validation prevents dangerous co-location of incompatible pets. The system identifies all jobs within the same SessionBlock and their existing assignments (specifically those in PROPOSED, CONFIRMED, or COMPLETE status), then constructs a set of pet_ids currently assigned to that block. If any of these assigned pets appear in the proposed job's cannot_be_groomed_with_pet_ids list, the assignment is rejected.

Fifth, allergy threshold validation interacts with the peak session detection logic described in Section 3.6. When a proposed assignment would contribute to a peak session (based on the job count in the SessionBlock), the system adds a 10-point penalty to the current AllergyExposureLedger score. If this projected score would equal or exceed the critical threshold of 50, the assignment requires explicit override authorization through the override_allergy_check parameter, which defaults to false if not provided.

Finally, supply budget validation ensures financial responsibility by calculating the provisional cost of the assignment and verifying sufficient remaining budget in the SupplyStockLedger.

Upon successful validation, the system creates the JobAssignment with carefully computed field values. The `override_allergy_check` boolean from the request is recorded on the assignment for auditing purposes, the `is_peak_session` field captures whether this assignment contributes to peak pricing, while `provisional_supply_cost` stores the estimated cost including any peak multipliers. The `allergy_override_penalty_applied` field becomes true only when specific conditions align: the assignment is for a peak session, the allergy score would breach the threshold, and the override was explicitly authorized. Like other primary resources, JobAssignments also include `created_at` and `updated_at` timestamps.

### 3.6 Peak Session Dynamics and Cost Implications

The system implements sophisticated peak pricing logic that activates when SessionBlocks reach high utilization. Unlike traditional time-based peak pricing, this system counts active job assignments within each block to determine scheduling load. For the purposes of activating peak pricing, this count is strictly defined to include only assignments in a forward-looking state—that is, `PROPOSED` or `CONFIRMED`. When a SessionBlock contains 5 or more such active assignments, any new assignment is designated a peak session job. This calculation deliberately differs from other operational validations (such as those for groomer breaks or pet conflicts as detailed in Section 3.5), which may consider a broader set of statuses, including completed jobs, to ensure historical context is respected.

Peak session designation triggers multiple system responses. The supply cost calculation multiplies the base hourly rate by 1.5, reflecting increased resource consumption during busy periods. Additionally, the system increments the AllergyExposureLedger by 10 points, acknowledging that high-volume periods present increased risk for allergy-related incidents.

The interaction between peak sessions and allergy overrides creates a particularly complex scenario. When a ClinicManager authorizes an override for a peak session assignment that would breach the allergy threshold (50 points), the system applies an additional 25-point penalty to the AllergyExposureLedger. This substantial penalty reflects the compounded risk of combining high utilization with safety protocol overrides.

### 3.7 Ledger Synchronization and Derived Values

The system maintains two critical ledgers that track resource consumption and safety metrics across each GroomingDay. These ledgers operate as append-only audit logs with automatic synchronization to derived fields on the GroomingDay resource.

The SupplyStockLedger tracks two categories of costs: provisional_costs representing the sum of provisional_supply_cost for all assignments in PROPOSED or CONFIRMED status, and finalized_costs containing the sum of final_supply_cost for all COMPLETE assignments. The system automatically updates the GroomingDay's supply_stock_balance field whenever these ledger values change, calculating the remaining budget as total_supply_budget minus both cost categories.

The AllergyExposureLedger is defined by a single field, `allergy_score`, an integer which starts at 0 and cannot be negative. This score accumulates risk points throughout the day as peak session assignments occur or when safety overrides are authorized. The system synchronizes this value to the GroomingDay's allergy_exposure_score field after each change, providing immediate visibility into current risk levels.

### 3.8 Assignment Lifecycle and State Transitions

JobAssignments progress through a sophisticated state machine that reflects the complex approval and execution workflow. New assignments begin in PROPOSED status.

An assignment in PROPOSED status transitions to CONFIRMED status upon approval from a ClinicManager. Furthermore, a confirmed assignment can be temporarily placed ON_HOLD and later resumed.

The termination of an assignment triggers extensive cleanup operations. Beyond transitioning the assignment to TERMINATED status, the system must reopen the associated GroomingJob to PENDING status, enabling reassignment. All provisional costs are reversed from the SupplyStockLedger, and any allergy score penalties (both peak session and override penalties) are decremented from the AllergyExposureLedger. If the parent SessionBlock was in `READY_FOR_GROOMING` status, it is automatically downgraded to `PLANNING` to reflect that its set of confirmed jobs has changed.

### 3.9 Cascading Cancellations and Data Integrity

When a SessionBlock is cancelled, the system initiates a complex cascade of status changes and ledger adjustments to maintain data consistency. This process begins by identifying all GroomingJobs within the cancelled block that haven't already reached CANCELLED status.

For each affected job, the system must locate all associated JobAssignments in PROPOSED or CONFIRMED status. These assignments require individual processing to reverse their ledger impacts before termination. The system reverses the financial and risk impacts of each terminated assignment by decrementing its `provisional_supply_cost` from the SupplyStockLedger and removing any associated allergy penalties from the AllergyExposureLedger, carefully distinguishing between peak session penalties and override penalties.

After completing ledger adjustments, the system transitions each assignment to TERMINATED status and each job to CANCELLED status. This ordered approach ensures that financial and safety metrics remain accurate throughout the cancellation process.

### 3.10 Invoice Generation and Final Reconciliation

The transition from active operations to financial settlement occurs through a two-phase process. First, a ClinicManager initiates the invoicing phase by moving the GroomingDay from ACTIVE to INVOICING_PENDING status. This transition requires that no unresolved assignments remain in PROPOSED status, ensuring a clean operational state.

The actual invoice generation, restricted to BillingAdmin users, performs atomic finalization of all CONFIRMED assignments. Within a database transaction, the system calculates final costs for each assignment (simplified in this version to match provisional costs), updates the assignment's `final_supply_cost` field, and adjusts the `SupplyStockLedger` for each by decrementing `provisional_costs` and incrementing `finalized_costs`.

The transaction includes a critical budget check: if total finalized costs would exceed the day's total_supply_budget, the entire transaction rolls back with an ERR_INVOICING_EXCEEDS_BUDGET error. This atomic approach prevents partial invoice generation that could leave the system in an inconsistent state.

Upon successful completion, all processed assignments transition to COMPLETE status, the SupplyStockLedger's provisional_costs reset to zero, and the GroomingDay advances to CLOSED status, preventing further modifications.

### 3.11 Temporal Constraints and Business Hours

The system enforces strict temporal validation for all scheduling operations. SessionBlock boundaries must maintain logical consistency, with end_time exceeding start_time. Similar validation applies to GroomingJobs, ensuring that service windows are properly defined.

The groomer break requirement adds complexity to temporal validation. When evaluating whether sufficient break time exists between jobs, the system must consider the break period both after the existing job's end and before the proposed job's start. This bidirectional check prevents scenarios where jobs are scheduled too closely together, regardless of which job was created first.

### 3.12 Role-Based Operation Restrictions

The API enforces role-based access control at the operation level, with specific endpoints restricted to authorized roles. Any attempt to perform an operation without the requisite role will result in an `ERR_INSUFFICIENT_PERMISSIONS` error. ClinicManagers possess broad authority including day activation, SessionBlock status updates, assignment confirmation, and assignment termination. These privileges reflect their responsibility for operational oversight and risk management.

GroomingTechnicians handle day-to-day scheduling operations including SessionBlock creation, GroomingJob creation, job cancellation, new JobAssignment proposals, and GroomerStation configuration. Their permissions align with frontline operational needs while preventing unauthorized risk acceptance.

BillingAdmins hold exclusive authority over the invoice generation process, ensuring proper financial controls and separation of duties between operational and financial functions.

## 4. Endpoint Definitions

All successful creation operations return 201 Created, while other successful operations return 200 OK.

### Day Management Operations

**POST /grooming-days** - Creates a new GroomingDay in PLANNING status with specified schedule name and supply budget. Restricted to ClinicManager role. Requires schedule_name and total_supply_budget in request body. Returns 201 with created resource.

**GET /grooming-days** - Retrieves all GroomingDay records sorted by creation timestamp in ascending order. Supports standard pagination parameters.

**GET /grooming-days/{dayId}** - Retrieves a specific GroomingDay by its UUID. Returns 404 with ERR_DAY_NOT_FOUND if the day doesn't exist.

**POST /grooming-days/{dayId}/activate** - Transitions a GroomingDay from PLANNING to ACTIVE status. Restricted to ClinicManager role. Returns 409 with ERR_DAY_NOT_IN_PLANNING if the day is not in PLANNING status.

### Session Block Operations

**POST /grooming-days/{dayId}/session-blocks** - Creates a new SessionBlock within an active GroomingDay. Restricted to GroomingTechnician role. Validates day existence, ACTIVE status, and temporal boundary logic.

**GET /grooming-days/{dayId}/session-blocks** - Lists all SessionBlocks for a specific day, sorted by creation timestamp.

**GET /grooming-days/{dayId}/session-blocks/{blockId}** - Retrieves a specific SessionBlock, validating both existence and parent relationship.

**PUT /grooming-days/{dayId}/session-blocks/{blockId}** - Updates SessionBlock status. Restricted to ClinicManager role. Validates state transitions and enforces job confirmation requirements for READY_FOR_GROOMING transition.

### Grooming Job Operations

**POST /grooming-days/{dayId}/session-blocks/{blockId}/grooming-jobs** - Creates a new GroomingJob within a SessionBlock. Restricted to GroomingTechnician role. Validates temporal boundaries and parent relationships.

**GET /grooming-days/{dayId}/session-blocks/{blockId}/grooming-jobs** - Lists all GroomingJobs within a SessionBlock, sorted by creation timestamp.

**GET /grooming-days/{dayId}/session-blocks/{blockId}/grooming-jobs/{jobId}** - Retrieves a specific GroomingJob, validating complete parent hierarchy.

**POST /grooming-days/{dayId}/session-blocks/{blockId}/grooming-jobs/{jobId}/cancel** - Cancels a GroomingJob in PENDING status. Restricted to GroomingTechnician role. Returns 409 with ERR_JOB_NOT_PENDING_FOR_CANCEL if job is not PENDING.

### Assignment Management Operations

**POST /grooming-days/{dayId}/job-assignments** - Proposes a new JobAssignment linking a job to a station. Restricted to GroomingTechnician role. Executes full validation cascade including capability matching, break periods, allergy conflicts, peak session detection, and budget verification.

**GET /grooming-days/{dayId}/job-assignments** - Lists all JobAssignments for a day, sorted by creation timestamp.

**GET /grooming-days/{dayId}/job-assignments/{assignmentId}** - Retrieves a specific JobAssignment, validating parent relationship.

**POST /grooming-days/{dayId}/job-assignments/{assignmentId}/terminate** - Terminates an assignment and reverts associated ledger changes. Restricted to ClinicManager role. Only assignments in PROPOSED or CONFIRMED status can be terminated.

**POST /grooming-days/{dayId}/job-assignments/{assignmentId}/confirm** - Confirms a proposed assignment. Restricted to ClinicManager role. Transitions assignment to CONFIRMED status and associated job to CONFIRMED status.

### Station Configuration Operations

**POST /grooming-days/{dayId}/groomer-stations** - Creates a new GroomerStation configuration for a day. Restricted to GroomingTechnician role. Requires station_name, station_type, and supply_cost_per_hour.

**GET /grooming-days/{dayId}/groomer-stations** - Lists all GroomerStation configurations for a day, sorted by creation timestamp.

**GET /grooming-days/{dayId}/groomer-stations/{stationId}** - Retrieves a specific GroomerStation configuration.

**POST /grooming-days/{dayId}/groomer-stations/{stationId}/special-capabilities** - Adds a special capability to a station. Restricted to GroomingTechnician role. Requires capability name and enabled date.

### Financial Operations

**POST /grooming-days/{dayId}/initiate-invoicing** - Transitions day from ACTIVE to INVOICING_PENDING status. Restricted to ClinicManager role. Validates no unresolved assignments exist.

**POST /grooming-days/{dayId}/generate-invoice-report** - Finalizes all costs and closes the day. Restricted to BillingAdmin role. Executes atomic transaction to calculate final costs, update ledgers, and complete assignments.

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| :-------------------------------- | :--------------- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 Bad Request |
| ERR_INVALID_REQUEST              | 400 Bad Request |
| ERR_INVALID_BLOCK_TIMES          | 400 Bad Request |
| ERR_INVALID_JOB_TIMES            | 400 Bad Request |
| ERR_CAPABILITY_MISMATCH          | 400 Bad Request |
| ERR_INSUFFICIENT_SUPPLIES        | 402 Payment Required |
| ERR_INVOICING_EXCEEDS_BUDGET     | 402 Payment Required |
| ERR_ALLERGY_THRESHOLD_BREACHED   | 403 Forbidden |
| ERR_INSUFFICIENT_PERMISSIONS     | 403 Forbidden |
| ERR_DAY_NOT_FOUND               | 404 Not Found |
| ERR_BLOCK_NOT_FOUND             | 404 Not Found |
| ERR_JOB_NOT_FOUND               | 404 Not Found |
| ERR_ASSIGNMENT_NOT_FOUND        | 404 Not Found |
| ERR_STATION_NOT_FOUND           | 404 Not Found |
| ERR_DAY_NOT_ACTIVE              | 409 Conflict |
| ERR_DAY_NOT_IN_PLANNING         | 409 Conflict |
| ERR_DAY_NOT_READY_FOR_INVOICING | 409 Conflict |
| ERR_JOB_NOT_PENDING             | 409 Conflict |
| ERR_JOB_NOT_PENDING_FOR_CANCEL  | 409 Conflict |
| ERR_BREAK_PERIOD_VIOLATION      | 409 Conflict |
| ERR_PET_ALLERGY_CONFLICT        | 409 Conflict |
| ERR_ASSIGNMENT_NOT_PROPOSED     | 409 Conflict |
| ERR_ASSIGNMENT_NOT_TERMINABLE   | 409 Conflict |
| ERR_ILLEGAL_BLOCK_STATE_TRANSITION | 409 Conflict |
| ERR_JOBS_NOT_CONFIRMED          | 409 Conflict |
| ERR_UNRESOLVED_ASSIGNMENTS_EXIST | 409 Conflict |