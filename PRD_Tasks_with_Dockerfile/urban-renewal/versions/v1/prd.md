# Urban Renewal Project Management API - Product Requirements Document

## 1. Urban Renewal Project Management API

The Urban Renewal Project Management API provides a comprehensive system for planning, staffing, and executing large-scale urban renovation projects. It enables project managers to define project structures, manage budgets, contract and schedule specialized renovation crews, and monitor community impact. The system's core function is to ensure that projects are completed on budget while balancing the complex scheduling constraints of various work crews and adhering to community disruption regulations.

-----

## 2. Global Specifications

This section defines system-wide rules and formats that apply to the entire API.

### Authentication & User Context

User context is determined by one mandatory HTTP request header for all endpoints:

  * `X-User-ID`: (string) The unique identifier of the user making the request. This ID is used for authorization checks and data association.

Failure to provide a valid `X-User-ID` header will result in a `400 Bad Request` with `error_id: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.

### Data Isolation & Access Control

All resources in the system are strictly isolated by project. Operations on phases, work orders, contracts, crews, and pairings must be accessed through their parent project's endpoints. Attempting to access or modify a resource through a different project's endpoint will result in a `404 Not Found` error, even if the resource exists in another project. The system enforces project-level state integrity as a primary access control measure; before evaluating the validity of any requested state change on a child resource (such as a phase or work order), the system first validates that the parent project is in an active state that permits such modifications. Invalid request structures, including malformed identifiers, are rejected with appropriate error responses.

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
  * Idempotent replays: when a previously accepted request is replayed under idempotency controls, the server returns `200 OK`, sets `meta.idempotency_replay: true`, and returns the canonical resource representation as it was first persisted.

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

-----

### Idempotency

To protect against accidental duplicate resource creation from network retries, the system supports idempotency for all creation operations. Project managers can include an `Idempotency-Key` header with a unique UUID in their request. The first time the system sees a request with a particular key, it will create the resource as requested and return a `201 Created` status. If a request is sent again with the same key, the system will not create a duplicate resource; instead, it will return a `200 OK` response with the details of the originally created resource, and the `meta` object will indicate it's an `idempotency_replay`. When a key is reused, the server returns the cached representation regardless of whether the new request's payload differs from the original.

These keys are scoped to the caller and the specific resource container being addressed by the endpoint, ensuring that replay protection is secure and precise. Keys undergo format validation as part of request processing and are reliably stored for at least 24 hours.

For batch operations, this protection can be applied to individual items by providing an `idempotency_key` for each. The system will recognize if an item has been created before and simply return its details, while still processing any new items in the same request. If the same valid idempotency key appears multiple times with identical payloads within a single request, the system will process the first instance and return its result, echoed in the position of each subsequent duplicate. However, to maintain data integrity, reusing a key with a different payload will cause the entire batch to fail validation. This functionality is available on the following creation endpoints: `POST /projects`, `POST /projects/{projId}/phases`, `POST /projects/{projId}/phases/{phaseId}/work-orders`, `POST /projects/{projId}/crews`, `POST /projects/{projId}/contracts`, `POST /projects/{projId}/crew-conflict-pairings`, `POST /projects/{projId}/phases/{phaseId}/work-orders/batch`, and `POST /projects/{projId}/contracts/batch`.

### Optimistic Concurrency (Versioning)

Mutable resources include a `version` (integer, sequential) field in responses. State-changing operations MAY include an `If-Match` header set to the numeric version the client believes is current. If provided and the stored `version` does not match, the server responds with `ERR_PRECONDITION_FAILED_VERSION`. If the header is absent, the request proceeds without a version precondition check.

Resources with `version`: `UrbanRenewalProject`, `RenovationPhase`, `WorkOrder`, `RenovationCrew`, and `CrewContract`.

State-changing operations covered: `PUT /projects/{projId}/phases/{phaseId}` (status updates) and contract transitions (`POST /projects/{projId}/contracts/{contractId}/specialization-verify`, `/schedule`, `/reject`, `/cancel`).

### Resource Expansion (Include)

To provide a comprehensive overview of project data and reduce the need for multiple API calls, list endpoints support the inclusion of related resources. By using the `include` query parameter with a comma-separated list of resource types, project managers can retrieve a project's phases, crews, and contracts all in one request. When this parameter is present, the response adds a top-level `included` array containing the de-duplicated related resources, each with its `type`, `id`, and attributes. The `type` will be a snake_cased string matching the resource name. If no related resources exist for a given request, the response will still include an empty `included` array.

This functionality extends to nested relationships. For example, when listing phases for a project (`GET /projects/{projId}/phases`), a user can specify `include=work_orders.contracts` to receive both the `work_order` resources and their associated `contract` resources. The system understands that requesting the contracts implies the work orders they belong to, and will include both. The supported expansions are specific to each endpoint:
  - `GET /projects`: `phases`, `crews`, `contracts`
  - `GET /projects/{projId}/phases`: `work_orders`, `work_orders.contracts`
  - `GET /projects/{projId}/contracts`: `work_order`, `crew`

### Numerical Precision and Calculations

Final currency values stored and returned by the API, such as `budget_balance`, `provisional_cost`, and `final_cost`, must be rounded to exactly two decimal places, rounded half-up. All intermediate arithmetic (including multipliers and surcharges) must be computed with at least 15 decimal places of precision, and no intermediate rounding may be applied prior to the final rounding step.

-----

## 3. Business Logic & Workflows

### 3.1 Project Lifecycle & Work Structure

The fundamental unit of work is the **`UrbanRenewalProject`**. Each project is defined by a `project_name` and a total `renovation_budget`, alongside system-generated fields including a unique `id` identifier. Projects begin in a `PLANNING` state where structural decisions are made. Once ready, project managers activate the work phase (`IN_PROGRESS`) where all construction activities occur—this is the only status in which the project's constituent elements such as phases and work orders can be created or have their status manually updated. After work concludes, projects enter `FINAL_AUDIT_PENDING` to reconcile costs before ultimately reaching `READY_FOR_LEASING` status suitable for tenant occupancy.

Projects are broken down into a hierarchy of tasks:

1.  **`RenovationPhase`**: A project is composed of one or more phases (e.g., "Lobby and entryway restoration"). Each phase has a `name` describing its purpose, a `start_hour` and `end_hour` relative to the project start. A phase's `status` can be `PLANNING`, `READY_FOR_EXECUTION` (only once all of its work orders exist and are fully `CONTRACTED`), `COMPLETED`, or `CANCELLED`. The phase maintains its association to the parent project through a `project_id` field. Like all primary resources in the system, each phase is assigned a unique `id` upon creation.
2.  **`WorkOrder`**: Each phase is composed of discrete work orders (e.g., "Install new lighting fixtures"). A work order has a `task_type`, `start_hour`, and `end_hour` (which must be integer values), and a `status` of its own: `PENDING`, `AWAITING_CONFIRMATION`, `CONTRACTED`, `COMPLETED`, or `CANCELLED`. New contracts can only be proposed for work orders in `PENDING` status, with the work order's state evolving through the contract lifecycle. A work order also specifies technical requirements, including a `required_specialization` (e.g., `PLUMBING`, `ELECTRICAL`, `ASBESTOS_REMOVAL`, or `GENERAL`) and a `required_safety_clearance_level` (an integer greater than or equal to 1). If the `required_specialization` field is omitted during creation, it will default to `GENERAL`—representing baseline work that any crew can perform. The `duration_hours` of a work order is automatically calculated based on its start and end times. Each work order tracks its `phase_id` to maintain the hierarchical relationship within the project structure, alongside a `project_id` for direct project association enabling streamlined queries across phase boundaries. Each work order is assigned its own unique `id` upon creation.

A crucial dependency exists between these levels: a `RenovationPhase` is considered complete only when all of its associated `WorkOrder` entities have reached a terminal state (`COMPLETED` or `CANCELLED`). A `CANCELLED` phase cannot contain any active work orders or contracts, and this state is terminal; it cannot be undone.

### 3.2 Crew Management and Contracting

Projects are executed by **`RenovationCrew`** teams. Each crew has a `crew_name`, `company_name`, and a standard `hourly_rate`. Crews are registered within the context of a specific project, maintaining this relationship through their `project_id`. To qualify for specific jobs, a crew's profile must include a list of `crew_certifications`. Each certification has a `specialization_name` and a `clearance_level`. Like all primary resources in the system, each crew is assigned a unique `id` upon creation.

To assign a crew to a `WorkOrder`, a **`CrewContract`** must be created. The contract proposal links a `crew_id` to a `work_order_id` and is automatically assigned its own unique `id`. This proposal triggers a comprehensive validation process. For work orders requiring specialized skills, the system verifies that the selected crew's certifications and clearance level meet those technical requirements; specialized tasks carry additional costs for their unique demands like handling materials or ensuring safety protocols. 

The assignment must not create scheduling overlaps with the crew's existing commitments. To maintain quality and safety, a half-shift buffer must be reserved in a crew's schedule for setup and cleanup when switching between different types of tasks. The system also enforces any registered **`CrewConflictPairing`**s, which project managers use to prevent disruptive work from happening concurrently in the same `RenovationPhase`. Each pairing links `crew_id_1` and `crew_id_2`, receives its own `id`, and maintains a reference to its `project_id`. A contract proposal will be rejected if it would assign a crew to a phase where a conflicting crew already has a non-terminal contract. Additionally, if the proposed contract would result in hazardous pay rates, the system evaluates whether the resulting disruption index increase would breach established thresholds. Finally, the system confirms that sufficient budget remains to cover the contract's estimated cost.

The system ensures all prerequisites are met before evaluating business constraints, with resource availability naturally verified before financial or scheduling considerations.

Once proposed, a `CrewContract` moves through its own lifecycle: `PROPOSED` -> `SPECIALIZATION_VERIFIED` -> `SCHEDULED` -> `COMPLETED`, with `REJECTED` and `CANCELLED` acting as alternative endpoints. Terminal states are `COMPLETED`, `REJECTED`, and `CANCELLED`; contracts in `PROPOSED` or `SPECIALIZATION_VERIFIED` are considered unresolved; all other states are resolved. Each contract maintains immutable records of its initial proposal parameters, including the `permit_waiver_used` decision, alongside computed fields like `is_hazardous_pay_rate` and `permit_waiver_penalty_applied`.

### 3.3 Financial and Community Impact Governance

Every project is governed by two key financial and social metrics, which are tracked on the `UrbanRenewalProject` resource as read-only fields: `budget_balance` and `community_disruption_index`. These values are derived from underlying ledgers that are updated with every relevant action.

#### **Budget Management**

The project's remaining `budget_balance` is calculated as the initial `renovation_budget` less all committed and incurred costs. The system maintains separate tracking of `committed_costs` and `incurred_costs` in its internal ledgers.

  * Proposals record a provisional commitment that contributes to committed costs; as work completes, committed amounts resolve into incurred costs. Budget availability is always measured against the current `renovation_budget` net of both committed and incurred amounts.

A contract proposal will be blocked if its `provisional_cost` exceeds the currently available `budget_balance`. The scheduling operation adjusts the ledger to reflect the difference between the schedule-time cost determination and the original provisional amount.

#### **Cost Calculation & Surcharges**

The cost of work is determined by a crew's `hourly_rate`, but specialized tasks command premium compensation reflecting their unique demands. Asbestos removal, with its stringent compliance and health monitoring requirements, necessitates rates 80% above standard. Electrical work, given its safety equipment needs, carries a 30% premium, while plumbing's material handling complexities add 20% to base rates.

Higher safety clearances reflect increased risk, necessitating a premium that adjusts by a tenth of the base rate for every increment above the minimum to account for additional protective measures.

* **Hazardous Work Rate**: Labor regulations cap standard work at 160 cumulative hours per project—equivalent to 20 full shifts across that crew's assignments—so capacity planned beyond that threshold is treated as hazardous duty. When a crew's assignments cross this standard-capacity boundary, every additional hour is billed at 1.5 times the crew's effective hourly rate (after other surcharges) and sets the contract's `is_hazardous_pay_rate` flag. The cumulative hours calculation, used to determine if a contract enters the hazardous bracket, is dynamic: proposal-time checks consider all active and pending work for the assigned crew, while final accounting replays only the firmly scheduled sequence. Rejected or cancelled contracts never contribute to the running total. Hazardous assignments, due to their extended community strain, automatically qualify as disruption events.

#### **Community Disruption**

The `community_disruption_index` starts at 0 and increases based on disruptive activities. This value, tracked as `disruption_index` in the ledger, must be adjusted in real time whenever a contract's hazardous pay status is re-evaluated.

  * Each significant disruption event adds 25 points to the index.
  * The system enforces a disruption limit of 100 points (also known as the `EVICTION_NOTICE_THRESHOLD`). An assignment that would cause the index to exceed this limit will be blocked unless specific override provisions are utilized.
  * Project managers can bypass threshold restrictions by setting the `permit_waiver_used` flag to `true` in the contract proposal. This waiver allows the disruptive assignment to proceed but incurs a steep penalty—the disruption index increases by an additional 75 points beyond the standard disruption increment. A contract's use of this waiver is recorded in the immutable `permit_waiver_penalty_applied` field, alongside the original waiver decision itself. The penalty is only applied if the contract would actually breach the disruption threshold without the waiver.

### 3.4 Project Finalization

A project enters the `FINAL_AUDIT_PENDING` state when it has no unresolved contracts, and the body of scheduled work is ready for audit. Once in this state, the project can undergo finalization—an atomic, all-or-nothing transaction that performs the final accounting for the entire project. Projects with no contracts can also be finalized, in which case the project transitions directly to `READY_FOR_LEASING` with its full budget intact.

The finalization process performs a comprehensive reconciliation of all `SCHEDULED` contracts. The final accounting must be auditable and reflect the true labor costs as they accrued over the project's timeline. This reconciliation recalculates the true cost for every scheduled contract based on the complete chronological sequence of work assignments. During this process, the system confirms each assignment's final hazardous pay status and determines its `final_cost`. The provisional amounts are moved from the "committed" ledger to the "incurred" ledger, and each contract is transitioned to `COMPLETED`.

When two scheduled contracts have identical `start_hour` values, the reconciliation pass breaks ties deterministically by ascending `contract.id` before applying the chronological replay. This guarantees a single, consistent ordering for cost and hazard determinations in tie scenarios.

As contracts are finalized, their associated work orders naturally reach completion.

If, at the end of this process, the project's total `incurred_costs` exceed the `renovation_budget`, the entire transaction is rolled back, and the project remains in its pre-finalization state. If successful, all committed costs are cleared, and the project's `status` becomes `READY_FOR_LEASING`.

-----

## 4. Endpoint Definitions

### 4.1 Project & Phase Management

#### POST /projects

Create a new Urban Renewal Project. The system generates timestamp fields `created_at` and `updated_at` to track the project's lifecycle.

#### GET /projects

List all Urban Renewal Projects, sorted by `created_at` ascending (oldest first).

Query Parameters:
- `include` (optional): `phases`, `crews`, `contracts`

#### GET /projects/{projId}

Get a specific Urban Renewal Project.

#### POST /projects/{projId}/begin-work

Activate a project, transitioning its status from `PLANNING` to `IN_PROGRESS`.

#### POST /projects/{projId}/initiate-final-audit

Move a project from `IN_PROGRESS` to `FINAL_AUDIT_PENDING`.

#### POST /projects/{projId}/finalize-project

Finalize costs and complete the project, moving it to `READY_FOR_LEASING`.

#### POST /projects/{projId}/phases

Create a new Renovation Phase within a Project. The phase inherits its project association and receives system-managed temporal tracking through `created_at` and `updated_at` fields.

#### GET /projects/{projId}/phases

List all Renovation Phases for a Project, sorted by `created_at` ascending (oldest first).

Query Parameters:
- `include` (optional): `work_orders`, `work_orders.contracts`

#### GET /projects/{projId}/phases/{phaseId}

Get a specific Renovation Phase.

#### PUT /projects/{projId}/phases/{phaseId}

Update a Renovation Phase's status. Supported client-initiated transitions are: `PLANNING → READY_FOR_EXECUTION`, `PLANNING → CANCELLED`, and `READY_FOR_EXECUTION → CANCELLED`. All other attempts—including moving a CANCELLED phase forward—are rejected with ` ERR_ILLEGAL_PHASE_STATE_TRANSITION`.

### 4.2 Work Order & Contract Management

#### POST /projects/{projId}/phases/{phaseId}/work-orders

Create a new Work Order for a Phase. The work order maintains both direct project association and phase hierarchy, with temporal tracking via `created_at` and `updated_at` timestamps. The `required_safety_clearance_level` defaults to 1; supplying a non-integer or any value below 1 is an invalid request.

#### GET /projects/{projId}/phases/{phaseId}/work-orders

List all Work Orders for a Phase, sorted by `created_at` ascending (oldest first).

#### GET /projects/{projId}/phases/{phaseId}/work-orders/{orderId}

Get a specific Work Order.

#### POST /projects/{projId}/contracts

Propose a new Crew Contract for a Work Order. The request body is a `CrewContractPayload` containing `work_order_id`, `crew_id`, and the optional `permit_waiver_used` boolean. Contract proposals require the referenced work order to be in `PENDING` status; work orders already under contract negotiation or completed cannot accept new proposals. Each contract receives system-generated metadata including `created_at` and `updated_at` timestamps, and maintains its project association through an internal `project_id` reference.

#### GET /projects/{projId}/contracts

List all Crew Contracts for a Project, sorted by `created_at` ascending (oldest first).

Query Parameters:
- `include` (optional): `work_order`, `crew`

#### GET /projects/{projId}/contracts/{contractId}

Get a specific Crew Contract.

#### POST /projects/{projId}/contracts/{contractId}/specialization-verify

Move a `PROPOSED` contract to `SPECIALIZATION_VERIFIED`.

#### POST /projects/{projId}/contracts/{contractId}/schedule

Move a `SPECIALIZATION_VERIFIED` contract to `SCHEDULED`. The crew's cumulative hours at this moment determine the contract's final committed cost, superseding any provisional calculation from proposal time. Commitments reflect this schedule-time determination.

Scheduling requires both the contract to be specialization-verified and its associated work order to be awaiting confirmation. State preconditions are evaluated before any `If‑Match` version check; when those pass, a mismatched `If‑Match` yields `412`.

#### POST /projects/{projId}/contracts/{contractId}/reject

Reject a `PROPOSED` Crew Contract.

#### POST /projects/{projId}/contracts/{contractId}/cancel

Cancel a Crew Contract that is in a `PROPOSED`, `SPECIALIZATION_VERIFIED`, or `SCHEDULED` state.

### 4.3 Crew & Conflict Management

#### POST /projects/{projId}/crews

Create a new Renovation Crew profile for a Project. The crew profile is timestamped with `created_at` upon onboarding and tracks modifications through `updated_at`.

#### GET /projects/{projId}/crews

List all Renovation Crew profiles for a Project, sorted by `created_at` ascending (oldest first).

#### GET /projects/{projId}/crews/{crewId}

Get a specific Renovation Crew profile.

#### POST /projects/{projId}/crews/{crewId}/certifications

Add a certification to a Renovation Crew. The certification must include a valid `specialization_name` from the allowed values (`PLUMBING`, `ELECTRICAL`, `ASBESTOS_REMOVAL`, or `GENERAL`) and a `clearance_level` of 1 or higher. Upon success, the server will respond with the updated Renovation Crew object. Certification objects are stored and returned with a server-generated `id`, alongside the provided `specialization_name` and `clearance_level`.

#### POST /projects/{projId}/crew-conflict-pairings

Create a Crew Conflict Pairing. The request body contains `crew_id_1`, `crew_id_2`, and an optional `reason`. The pairing record is assigned a unique identifier and timestamped with `created_at` upon creation.

#### GET /projects/{projId}/crew-conflict-pairings

List all Crew Conflict Pairings for a Project, sorted by `created_at` ascending (oldest first).

#### GET /projects/{projId}/crew-conflict-pairings/{pairId}

Get a specific Crew Conflict Pairing.

-----

### 4.4 Batch Operations

#### POST /projects/{projId}/phases/{phaseId}/work-orders/batch

Create multiple Work Orders atomically within a Phase.

Request Body:

```
{
  "items": [
    {
      "task_type": "string",
      "required_specialization": "GENERAL|PLUMBING|ELECTRICAL|ASBESTOS_REMOVAL",
      "required_safety_clearance_level": 1,
      "start_hour": 0,
      "end_hour": 8,
      "idempotency_key": "uuid-string (optional)"
    }
  ]
}
```

To streamline data entry, project managers can create multiple work orders in a single request. This operation maintains data integrity through atomic processing—either all work orders in the batch are created successfully, or none are, preventing the project from entering a partially updated state if any item fails validation `ERR_BATCH_REJECTED`.

When retrying batch operations, the system recognizes previously submitted items through their `idempotency_key` values. If an entire batch consists of previously successful items with matching payloads, the server acknowledges this with a `200 OK` response including `meta.idempotency_replay: true` and returns the original data. Mixed batches containing both new and previously seen items result in `201 Created`, with only the new items being created while preserving the original request order in the response. Attempting to reuse an idempotency key with different data causes the entire batch to be rejected.

#### POST /projects/{projId}/contracts/batch

Create multiple Crew Contracts atomically within a Project.

Request Body:

```
{
  "items": [
    {
      "work_order_id": "uuid-string",
      "crew_id": "uuid-string",
      "permit_waiver_used": false,
      "idempotency_key": "uuid-string (optional)"
    }
  ]
}
```

To ensure data integrity, the system validates the entire batch for budget availability, disruption thresholds, and scheduling conflicts before committing any changes. This operation maintains atomicity—if any proposed contract fails validation, the entire request is rejected with `ERR_BATCH_REJECTED`, and no contracts are created. Each work order can only appear once within a single batch request; attempting to assign multiple crews to the same work order in one operation will cause validation failure. The idempotency behavior for contract batches mirrors that of work order batches, including the distinction between a `200 OK` response for full replays and `201 Created` for requests that mix new and replayed items.

## 5. Error Code Catalogue

| Error ID                                  | HTTP Status Code |
| :---------------------------------------- | :--------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request  |
| `ERR_INVALID_REQUEST`                     | 400 Bad Request  |
| `ERR_INVALID_PHASE_HOURS`                 | 400 Bad Request  |
| `ERR_INVALID_WORK_ORDER_HOURS`            | 400 Bad Request  |
| `ERR_SELF_PAIRING`                        | 400 Bad Request  |
| `ERR_CERTIFICATION_MISMATCH`              | 400 Bad Request  |
| `ERR_INSUFFICIENT_BUDGET`                 | 402 Payment Required |
| `ERR_FINALIZATION_EXCEEDS_BUDGET`         | 402 Payment Required |
| `ERR_DISRUPTION_INDEX_THRESHOLD_BREACHED`   | 403 Forbidden    |
| `ERR_PROJECT_NOT_FOUND`                   | 404 Not Found    |
| `ERR_PHASE_NOT_FOUND`                     | 404 Not Found    |
| `ERR_WORK_ORDER_NOT_FOUND`                | 404 Not Found    |
| `ERR_CREW_NOT_FOUND`                      | 404 Not Found    |
| `ERR_CONTRACT_NOT_FOUND`                  | 404 Not Found    |
| `ERR_PAIRING_NOT_FOUND`                   | 404 Not Found    |
| `ERR_PROJECT_NOT_IN_PLANNING`             | 409 Conflict     |
| `ERR_PROJECT_NOT_IN_PROGRESS`             | 409 Conflict     |
| `ERR_WORK_ORDER_NOT_PENDING`              | 409 Conflict     |
| `ERR_SETUP_TIME_VIOLATION`                | 409 Conflict     |
| `ERR_CREW_CONFLICT`                       | 409 Conflict     |
| `ERR_CONTRACT_NOT_PROPOSED`               | 409 Conflict     |
| `ERR_CONTRACT_NOT_SPECIALIZATION_VERIFIED`| 409 Conflict     |
| `ERR_WORK_ORDER_NOT_AWAITING_CONFIRMATION`| 409 Conflict     |
| `ERR_ILLEGAL_PHASE_STATE_TRANSITION`      | 409 Conflict     |
| `ERR_WORK_ORDERS_NOT_CONTRACTED`          | 409 Conflict     |
| `ERR_CONTRACT_NOT_CANCELLABLE`            | 409 Conflict     |
| `ERR_PROJECT_NOT_READY_FOR_FINALIZATION`  | 409 Conflict     |
| `ERR_UNRESOLVED_CONTRACTS_EXIST`          | 409 Conflict     |
| `ERR_BATCH_REJECTED`                       | 409 Conflict     |
| `ERR_PRECONDITION_FAILED_VERSION`          | 412 Precondition Failed |
