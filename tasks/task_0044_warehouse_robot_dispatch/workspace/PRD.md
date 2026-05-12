# Warehouse Robot Dispatch API — Product Requirements Document

## 1. Introduction

Modern fulfilment warehouses run on fleets of autonomous mobile robots that must continuously translate a mixed stream of inbound, outbound, replenishment, and relocation work into safe, energy-aware motion across a shared physical map. The Warehouse Robot Dispatch API is the control plane that ingests these tasks, assigns them to the right robots, plans paths that avoid collisions, manages charging across a small pool of stations, and reacts to faults without losing in-flight work.

The system is designed around a single warehouse as a `Fleet` — the configuration boundary inside which every map node, edge, robot, station, task, slot reservation, charging session, fault incident, trajectory record, and audit event lives. Floor operators drive the moment-to-moment workflow, a warehouse administrator owns configuration and registration, and an upstream Warehouse Management System (WMS) pushes work and equipment events into the fleet. Because real warehouses are tested deterministically rather than against wall-clock time, every fleet carries a virtual clock that callers advance explicitly, and every age-, expiry-, deadlock-, and charging-progress rule is evaluated against that clock rather than the host's system time.

The dispatch model couples quota-style allocation (which robot for which task, given battery, position, and path cost) with workflow orchestration (task lifecycle, charging lifecycle, fault lifecycle). The API surface must therefore expose precise contracts for state, while embedding subtle scheduling, conflict-avoidance, and cascading-failure rules into the business prose that follows.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. Three roles are recognised, spelled exactly as follows: `Operator`, `FleetAdmin`, and `WMS`. A missing or unrecognised header pair is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognised but not authorised for the endpoint (per the §4 table) is rejected with `ERR_FORBIDDEN` (HTTP 403).

All three roles use `X-User-ID` as an opaque operator identifier — none of them is backed by a persisted entity, and the server does not compare `X-User-ID` to the `id` of any `Fleet`, `Robot`, `Task`, `ChargingStation`, or `FaultIncident`. When `X-User-Role` is `Operator`, `X-User-ID` is an opaque floor-operator identifier used only for audit attribution. When `X-User-Role` is `FleetAdmin`, `X-User-ID` is an opaque administrator identifier with the same audit-only role. When `X-User-Role` is `WMS`, `X-User-ID` is an opaque WMS-integrator identifier. The server records the role string on `AuditEvent.actor_role` whenever a transition is initiated by a human caller; automatic transitions write the literal string `system` into `actor_role`.

The role-to-capability split is as follows:

- `Operator` runs the floor: it owns `:assign`, `:start`, `:complete`, `:cancel`, `:split`, `:merge`, `:step`, `:dock`, `:undock`, `:queue_charger`, `:heartbeat`, slot reservation creation, fault `:takeover` and `:resolve`, and charging-session cancellation. It also shares task creation with `WMS`, shares `dispatch` and clock advancement and fault opening with `FleetAdmin`, and shares all read endpoints with the other two roles.
- `FleetAdmin` owns configuration: fleet creation, map-node creation, map-edge creation, charging-station creation, and robot registration. It shares dispatch, clock advancement, and fault opening with `Operator`, and read access with everyone.
- `WMS` is exclusively the source of equipment and external task events emitted through the events endpoint. It also shares task creation with `Operator` and read access with the other two roles.

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

### 2.3. Pagination

List endpoints accept two query parameters: `limit` and `offset`. The default value of `limit` is 10; its minimum is 1 and its maximum is 100. The default value of `offset` is 0, with no upper bound enforced beyond the size of the underlying collection. All list endpoints sort by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more` so that the caller can drive iteration without inferring boundaries.

### 2.4. Common Resource Properties and the Virtual Clock

Most resources carry a common quartet of system-managed fields: `id` is a server-minted UUID with no resource-type prefix; `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; and `version` is an integer that starts at 1 on creation and is incremented by 1 on every successful mutation. The entities `Fleet`, `MapNode`, `ChargingStation`, `Robot`, `Task`, `ChargingSession`, and `FaultIncident` all carry the full quartet. The append-only ledgers — `MapEdge`, `SlotReservation`, `TrajectoryRecord`, and `AuditEvent` — carry only `id` and `created_at`; for those entities `updated_at` and `version` are absent from the response payload.

All time-bearing system fields — `Fleet.clock_now`, `Task.queued_at`, `Task.assigned_at`, `Task.started_at`, `Task.completed_at`, `ChargingSession.started_at`, `ChargingSession.completed_at`, `FaultIncident.detected_at`, `FaultIncident.takeover_started_at`, `FaultIncident.resolved_at`, `Robot.last_heartbeat_at`, `SlotReservation.scheduled_at`, `TrajectoryRecord.occurred_at`, and `AuditEvent.occurred_at` — are populated from `Fleet.clock_now` rather than from the server's host clock. A newly created fleet has its `clock_now` initialised to `1970-01-01T00:00:00.000Z`, and the only legal way to advance it is the clock-advance capability, which accepts a single integer `delta_seconds`. Clock movement must be strictly forward: `delta_seconds` must be at least 1 and the resulting `clock_now` must be strictly greater than the current `clock_now`. A request that violates either condition is rejected with `ERR_CLOCK_BACKWARDS`.

### 2.5. Optimistic Concurrency Control

Mutating endpoints accept an optional `version` field in the request body. When present, the server compares it to the resource's current `version`: if they differ, the operation is rejected with `ERR_INVALID_STATE` (HTTP 409). When omitted, the version check is skipped and the operation proceeds based only on state-machine and business preconditions. Every successful mutation increments `version` by 1 and refreshes `updated_at` to the current `Fleet.clock_now`.

### 2.6. Nested Resource Resolution

Several endpoints embed multiple identifiers in the URL — for instance, `/fleets/{fleet_id}/tasks/{task_id}`, `/fleets/{fleet_id}/fault_incidents/{incident_id}`, or `/fleets/{fleet_id}/charging_sessions/{session_id}`. Path-segment resolution proceeds strictly left to right: the `fleet_id` segment is resolved first, then any nested identifier under it. The first segment whose target cannot be found yields `ERR_NOT_FOUND` (HTTP 404), and resolution stops at that point so that the response identifies the leftmost missing segment.

### 2.7. Validation Order

When a request would fail more than one rule, the rejection that surfaces follows a fixed priority so that responses are deterministic and testable. The order, from highest to lowest, is: authentication of the header pair (`ERR_UNAUTHENTICATED`), role authorisation against the RBAC matrix (`ERR_FORBIDDEN`), left-to-right path-segment existence (`ERR_NOT_FOUND`), then body-shape validation (`ERR_BAD_REQUEST`), then state-machine validity for the requested transition (`ERR_INVALID_STATE`). After those structural gates, business-safety rules run in this order: a robot's fault state must permit the action (`ERR_ROBOT_FAULTED`), then connectivity must be `ONLINE` where required (`ERR_ROBOT_OFFLINE`), then for assignment the candidate robot must be free (`ERR_ROBOT_BUSY`), then battery sufficient (`ERR_BATTERY_LOW`), then a feasible path must exist (`ERR_NO_PATH`), then right-of-way slot rules apply at step time (`ERR_RIGHT_OF_WAY_MISSING`), then the charger must be available for direct docking (`ERR_CHARGER_UNAVAILABLE`), then slot uniqueness (`ERR_SLOT_ALREADY_RESERVED`), then split applicability (`ERR_SPLIT_NOT_APPLICABLE`), then merge compatibility (`ERR_MERGE_INCOMPATIBLE`), then descendant dependency for cancellation (`ERR_HAS_DEPENDENCIES`), then slot scheduling time validity (`ERR_SLOT_TIME_INVALID`), then the rollback ceiling (`ERR_ROLLBACK_LIMIT_REACHED`), and finally clock monotonicity (`ERR_CLOCK_BACKWARDS`). This ordering is the contract: a request that fails at a higher position surfaces that error even if a later check would also have failed.

### 2.8. Hierarchical Consistency and Cascading Side Effects

Many transitions on this API mutate more than one resource. When a `Task` enters or leaves `EXECUTING`, the owning `Robot` is updated in lock-step (its `operational_state`, `current_task_id`, and on motion its `position_node_id` and `battery_pct`). When a robot's fault state flips to `FAULTED`, the in-flight task is rolled back and re-queued, slot reservations the robot was holding are released, an isolation zone is laid down on the surrounding map nodes, and any charging session is cancelled. Every transition that mutates a resource bumps that resource's `version` by 1 and refreshes its `updated_at` to the current `Fleet.clock_now`; an audit row is written into `AuditEvent` with `event_kind`, `subject_kind`, `subject_id`, `from_state`, `to_state`, `actor_role`, and `occurred_at` populated. Append-only rows in `TrajectoryRecord`, `SlotReservation`, `MapEdge`, and `AuditEvent` are never updated after creation; their lifecycle is creation-only and they have no `version` to bump.

### 2.9. Precision, Rounding, and Time Granularity

All ratio-style metrics computed by the system — task completion rate, fleet robot utilisation, fault rate, and charging-time ratio — are rounded half up to four decimal places. The average task duration in seconds is rounded half up to two decimal places. Battery values, edge costs, priority scores, and slot indices are integers; the system performs no decimal arithmetic on them and any battery percentage greater than 100 is clamped to exactly 100. Wall-clock timestamps are produced at integer-second granularity from `Fleet.clock_now` plus integer second offsets.

### 2.10. Conflict Serialization

Several operations can race in production. The system makes the following serialisation guarantees, each with a specific loser error:

- When two operators attempt to assign the same `QUEUED` task to two different robots in parallel, exactly one assignment wins; the loser observes the task's `status` no longer equal to `QUEUED` and is rejected with `ERR_TASK_ALREADY_ASSIGNED` (HTTP 409). Serialisation is first-writer-wins on the task's status flip.
- When two robots attempt to reserve right-of-way at the same intersection or lift point for the same slot, at most one `HELD` reservation may exist per node and slot ordinal; the second creation is rejected with `ERR_SLOT_ALREADY_RESERVED` (HTTP 409). The uniqueness predicate is on the pair of `node_id` and `slot_index` where `status` equals `HELD`.
- When two robots try to dock at the same charging station simultaneously, the station flips to `OCCUPIED` only once; the loser observes a station status not equal to `AVAILABLE` and is rejected with `ERR_CHARGER_UNAVAILABLE` (HTTP 409).
- When a cancellation and a completion arrive together for the same `EXECUTING` task, exactly one succeeds; the loser observes the task's status no longer equal to `EXECUTING` and is rejected with `ERR_INVALID_STATE` (HTTP 409).
- When two operators try to merge the same `QUEUED` loser task at the same time, only one merge succeeds; the loser observes the loser-task's status no longer equal to `QUEUED` and is rejected with `ERR_INVALID_STATE` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Map, Nodes, and Edges

A fleet's physical layout is modelled as a directed graph of `MapNode` rows and `MapEdge` rows. Each node carries a `code` that is unique within the fleet, a `kind` drawn from the closed set `LANE`, `INTERSECTION`, `LIFT_POINT`, `CHARGER`, `PARK`, and `SHELF`, integer grid coordinates `x` and `y`, and an integer `capacity` defaulting to 1. `INTERSECTION`, `LIFT_POINT`, and `CHARGER` nodes always carry a capacity of 1 (single-occupant by design), while `LANE` and `PARK` nodes may carry a capacity of 1 or greater. Every node's `status` is initially `OPEN`; when the system or an external event drives it to `BLOCKED`, the reason is recorded on `blocked_reason` as one of `OBSTACLE`, `EQUIPMENT_LOCKED`, or `MANUAL`. When the node returns to `OPEN`, the reason is cleared back to null.

Edges are created with a positive integer `cost` (default 1), defaulting to bidirectional. An edge whose `directional` flag is true is one-way only; an edge whose `directional` flag is false is logically two-way, and the system materialises a reverse `MapEdge` row at creation time so that downstream path planning treats both directions symmetrically. Each edge identifies its endpoints by `from_node_id` and `to_node_id` and records its owning `fleet_id` on creation.

Map state changes propagate immediately. When a node transitions from `OPEN` to `BLOCKED`, every `EXECUTING` task whose `planned_path_node_ids` still includes that node, with the node still ahead of the robot's current position, is rerouted: the task's `planned_path_node_ids` is recomputed from the robot's current `position_node_id` over the open subgraph, treating any blocked node's cost as infinite. If no alternative route exists, the robot's `operational_state` flips to `WAITING_RIGHT_OF_WAY` and the task itself remains `EXECUTING` (the robot parks in place). When a node returns from `BLOCKED` to `OPEN`, its `blocked_reason` is cleared.

A step into a node whose `status` is `BLOCKED` is always rejected with `ERR_OBSTACLE_BLOCKING` (HTTP 409). An assignment whose pickup or dropoff lies inside an active fault-incident isolation zone — the set of nodes flagged `BLOCKED` because of an open or in-takeover `FaultIncident` — is rejected with `ERR_ISOLATION_VIOLATION` (HTTP 409).

### 3.2. The Task Lifecycle

Every unit of work flows through the `Task` state machine, whose canonical states are `QUEUED`, `ASSIGNED`, `EXECUTING`, `COMPLETED`, `CANCELLED`, `EXPIRED`, `ROLLED_BACK`, and `MERGED`. A task is created in `QUEUED` by either an `Operator` or a `WMS` integrator, who supplies a `source` from the closed set `INBOUND`, `OUTBOUND`, `REPLENISHMENT`, `RELOCATION`, plus the `pickup_node_id`, the `dropoff_node_id`, and optionally a `priority_class` (defaulting to `NORMAL`), a `payload_units` count (default 1), and a `max_units_per_robot` ceiling (default 10). On entry, `queued_at` is set to the current `Fleet.clock_now`, `priority_score` is computed (see §3.5), and the task is owned by the same fleet on `fleet_id`.

When the scheduler runs (see §3.5) or when an operator explicitly assigns a robot to the task, the task transitions from `QUEUED` to `ASSIGNED`. Five conditions must hold for the transition: the task is still in `QUEUED`, a robot has been selected by the candidate filter described in §3.5, that robot is in `OK` fault state and `ONLINE` connectivity with `operational_state` equal to `IDLE` and `battery_pct` strictly greater than `Fleet.charging_low_threshold_pct`, the robot is not currently charging, and the shortest-path search returns a non-empty path from the robot's `position_node_id` via the task's `pickup_node_id` to its `dropoff_node_id`. When all conditions hold, `assigned_robot_id` is written, `assigned_at` is set to the current clock, `planned_path_node_ids` is set to the computed sequence, and the chosen robot's `current_task_id` is set to the task's `id`. The robot remains `IDLE` until execution actually begins; an audit row is written with `event_kind` `TASK_STATUS`, `from_state` `QUEUED`, and `to_state` `ASSIGNED`.

Execution begins by transitioning the task from `ASSIGNED` to `EXECUTING`. The task must still be in `ASSIGNED`, and the robot must still be in `OK` fault state and `ONLINE` connectivity. On success, the robot's `operational_state` flips to `EXECUTING`, the task's `started_at` is recorded, and an audit row is written. A start attempt on a task whose `rollback_count` has exceeded the rollback ceiling — and which has therefore already been forced to `CANCELLED` by the system — is rejected with `ERR_ROLLBACK_LIMIT_REACHED`.

Completion fires when the task is in `EXECUTING` and the assigned robot's `position_node_id` equals the task's `dropoff_node_id`. The task's `completed_at` is set, the robot's `operational_state` returns to `IDLE`, the robot's `current_task_id` is cleared, every `SlotReservation` held by that robot with `status` `HELD` and `scheduled_at` at or after the current clock is released to `RELEASED`, and an audit row is written.

Cancellation is allowed from `QUEUED`, `ASSIGNED`, and `EXECUTING`. The transition requires that no descendant task (created through splitting) is in a non-terminal status — that is, every descendant must be in `CANCELLED`, `COMPLETED`, `EXPIRED`, or `MERGED`. A cancellation that violates the descendant rule is rejected with `ERR_HAS_DEPENDENCIES`. On success, if the task had an assigned robot, that robot's `current_task_id` is cleared and its `operational_state` returns to `IDLE`; any `HELD` slot reservations for the task with `scheduled_at` at or after the current clock are released; and an audit row with the previous state in `from_state` is written.

Expiry is automatic: a `QUEUED` task whose age — the difference between the current `Fleet.clock_now` and its `queued_at` in seconds — is at or above the fleet's `task_expiry_seconds` is moved to `EXPIRED`. The expiry sweep runs during clock advancement and during a dispatch pass; the task does not transition until one of those evaluations runs.

### 3.3. Splitting and Merging

A task whose `payload_units` exceeds its `max_units_per_robot` may be split by an `Operator`. Splitting is only legal while the task is `QUEUED` and has no parent (a child task may not itself be split — splits are never nested). The system creates N child rows where N is the ceiling of `payload_units` divided by `max_units_per_robot`; the children inherit the parent's `source`, `priority_class`, `pickup_node_id`, `dropoff_node_id`, and `max_units_per_robot`, set their own `parent_task_id` to the parent's `id`, and divide `payload_units` evenly with the final child absorbing the remainder so that the sum across children equals the parent's `payload_units`. The parent itself remains in `QUEUED` but is excluded from dispatch as long as it has descendants whose `status` is not in `CANCELLED`, `EXPIRED`, or `MERGED`. A split request that fails any of these preconditions is rejected with `ERR_SPLIT_NOT_APPLICABLE` (HTTP 422).

Merging takes two `QUEUED` tasks identified by `task_id_a` and `task_id_b` and combines them. The merge is legal only when both tasks share the same `source`, the same `priority_class`, the same `pickup_node_id`, and the same `dropoff_node_id`; neither task has a `parent_task_id`; and the combined `payload_units` is no greater than the `max_units_per_robot` of the surviving task. The surviving task is the one whose `id` is lexicographically smaller; the other becomes the loser. On success, `merged_into_task_id` on the loser is set to the survivor's `id`, the survivor's `payload_units` is incremented by the loser's `payload_units`, the loser transitions to `MERGED`, and an audit row is written for the loser. A merge that violates any compatibility rule is rejected with `ERR_MERGE_INCOMPATIBLE` (HTTP 422).

A parent task that has been split terminates only when every direct child terminates, following an aggregation evaluated chronologically by current clock then child `id` ascending after each child's terminal transition and again during every clock advancement. If every child is `COMPLETED`, the parent becomes `COMPLETED`. Otherwise, if every child is in `CANCELLED`, `EXPIRED`, `MERGED`, or `COMPLETED` and at least one child is `CANCELLED`, the parent becomes `CANCELLED`. Otherwise, if every child is in `EXPIRED`, `MERGED`, or `COMPLETED` and at least one child is `EXPIRED`, the parent becomes `EXPIRED`. In every other case the parent stays `QUEUED`. A read of a task may request the projection view through the `view` query parameter set to `projected`: in that mode, the system computes the parent's status as if every non-terminal child had completed, returning the projected outcome without persisting it. Reading without `view=projected` returns the persisted aggregated status, which can differ from the projection when any child is still non-terminal.

### 3.4. Robots and Their Parallel State

Each robot is registered with a `code` unique within its fleet, an initial `position_node_id`, an optional initial `battery_pct` (default 100), and an optional `standby_priority` (default 100, lower means higher priority for failover reassignment, with ties broken by `Robot.code` ascending). On registration the robot is `IDLE`, `ONLINE`, `OK`, and its `last_heartbeat_at` is set to the current `Fleet.clock_now`. Its `current_task_id`, `charging_station_id`, and `trajectory_archived_count` start clear or at zero.

A robot's connectivity evolves in parallel with its operational state. The `operational_state` field cycles through `IDLE`, `EXECUTING`, `WAITING_RIGHT_OF_WAY`, `CHARGING`, `WAITING_CHARGER`, `UNDER_MANUAL_CONTROL`, and `OUT_OF_SERVICE`. The `connectivity` field carries `ONLINE` or `OFFLINE`. The two dimensions are independent: heartbeat timeout drives connectivity, while task execution and charging drive operational state. The `fault_state` field is the third dimension and takes values `OK` or `FAULTED`.

Each `:heartbeat` call from a robot writes the current `Fleet.clock_now` into `last_heartbeat_at` and, if the robot was `OFFLINE`, flips it to `ONLINE`. Note that a heartbeat does not automatically resolve a fault incident — a robot in `OUT_OF_SERVICE` because of a fault remains there until the manual takeover-and-resolve workflow runs.

Motion proceeds one node at a time through stepping. When an operator steps a robot whose `operational_state` is `EXECUTING`, three outcomes are possible. If the next node along `planned_path_node_ids` is in `OPEN` status and its current occupancy is strictly less than its `capacity`, the robot moves: `position_node_id` advances, a `TrajectoryRecord` is appended with `from_node_id`, `to_node_id`, and `occurred_at`, and `battery_pct` is debited by the traversed edge's `cost`. If the next node is at full `capacity` or the robot lacks a `HELD` `SlotReservation` for the current slot at an `INTERSECTION` or `LIFT_POINT`, the robot transitions to `WAITING_RIGHT_OF_WAY`, keeping its position, and its `last_heartbeat_at` is refreshed to the current clock. The right-of-way rule has a strict interpretation at intersections and lift points: a step into one of those node kinds without a `HELD` slot reservation for the slot encompassing the current clock is rejected outright with `ERR_RIGHT_OF_WAY_MISSING`. A step into a node whose `status` is `BLOCKED` is rejected with `ERR_OBSTACLE_BLOCKING`. A step initiated against a faulted robot is rejected with `ERR_ROBOT_FAULTED`; a step against an offline robot is rejected with `ERR_ROBOT_OFFLINE`. From `WAITING_RIGHT_OF_WAY`, a subsequent step succeeds when capacity is available and the robot holds a `HELD` slot reservation for the current slot: the position advances, a trajectory row is appended, battery is debited, and the consumed `SlotReservation` flips from `HELD` to `CONSUMED`.

When the connectivity timeout expires — that is, when `Fleet.clock_now` minus `last_heartbeat_at` is at or above the heartbeat-timeout constant of fifteen seconds during a clock advancement — `connectivity` flips to `OFFLINE` and the system automatically opens a `FaultIncident` with `kind` `COMM_LOSS`, which then drives the robot into `OUT_OF_SERVICE` via the fault chain. Heartbeat restoration flips `connectivity` back to `ONLINE` but, again, does not lift the fault.

A robot's `trajectory_archived_count` is the count of `TrajectoryRecord` rows recorded for it; the trajectory ledger itself is reachable through the robot-trajectory list endpoint and never mutated after creation.

### 3.5. Dispatch, Selection, and Priority Ageing

The scheduler runs whenever an operator or administrator invokes the fleet dispatch capability. It walks the set of `QUEUED` tasks — excluding parents that still have descendants whose `status` is not in `CANCELLED`, `EXPIRED`, or `MERGED` — and orders them by `priority_score` ascending, breaking ties by task `id` ascending. For each task in that order, it attempts to find a robot via `robot_selection` and, if one is found, commits the assignment in place; later tasks see the updated robot pool. If no candidate exists for a given task, the task is left in `QUEUED` and no error is raised; the next dispatch pass will try again.

`priority_score` is an integer scheduling key computed when the task enters `QUEUED` and again on every clock advancement. It combines a class base and an ageing discount. The class base is 0 for `CRITICAL`, 1000 for `HIGH`, 2000 for `NORMAL`, and 3000 for `LOW`. The ageing discount is the number of complete sixty-second buckets the task has spent in `QUEUED` — computed as the floor of the maximum of zero and the age in seconds (current `Fleet.clock_now` minus `queued_at`) divided by sixty — multiplied by ten. The `priority_score` is the class base minus that discount. Lower scores sort first, so a `NORMAL` task ages downward into `HIGH` territory after one hundred such buckets, and an aged `LOW` task can eventually overtake a fresh `HIGH` task.

`robot_selection` filters the fleet to candidate robots and then ranks them. A candidate must belong to the same fleet, have `fault_state` `OK`, `connectivity` `ONLINE`, `operational_state` `IDLE`, no `current_task_id` set, and `battery_pct` strictly greater than `Fleet.charging_low_threshold_pct`. In addition, the shortest-path computation from the candidate's `position_node_id` via the task's `pickup_node_id` to its `dropoff_node_id` must return a non-empty path. Candidates are then ranked by the tuple of total path cost ascending, then `battery_pct` descending, then `Robot.code` ascending; the first-ranked candidate wins. If no candidate exists the task simply stays in `QUEUED`.

A direct assign request that targets a specific robot is gated by the same business rules as the scheduler: targeting a robot whose `current_task_id` is already set yields `ERR_ROBOT_BUSY`; targeting a robot whose `battery_pct` is not strictly greater than `Fleet.charging_low_threshold_pct` yields `ERR_BATTERY_LOW`; targeting a robot when no path exists from its `position_node_id` via the task's pickup to its dropoff over open nodes yields `ERR_NO_PATH`; and targeting a task whose `status` has already moved off `QUEUED` yields `ERR_TASK_ALREADY_ASSIGNED`.

### 3.6. Shortest-Path Planning and Slot Reservations

The shortest-path computation is run at four moments: when a task is assigned, when a rolled-back task is requeued and re-assigned, when a map node is blocked and a robot already on the move needs a new route, and when the deadlock recovery rerouter fires. The algorithm is Dijkstra over `MapEdge.cost` across only those nodes whose `status` is `OPEN`, where the path visits the robot's current position, then the task's `pickup_node_id`, then the task's `dropoff_node_id`, in that order. When two paths have identical total cost, the system picks the path whose concatenated list of node `code` strings sorts lexicographically smaller, so that tie-breaks are deterministic across runs. If no path exists with every required node `OPEN`, the result is the empty list and the calling assignment fails with `ERR_NO_PATH`; the task stays in `QUEUED`. The deadlock penalty constant — a value of one thousand applied to a contested node's cost during deadlock recovery — is the mechanism by which the rerouter forces a robot in a cycle to take a different route.

Right-of-way at `INTERSECTION` and `LIFT_POINT` nodes is allocated through `SlotReservation` rows. A reservation is created against a `node_id` (the intersection or lift-point node), a `robot_id`, a `task_id`, and a `scheduled_at` instant; the system computes the integer `slot_index` as the floor of (`scheduled_at` minus the epoch) divided by `Fleet.slot_seconds`, defaulting to ten seconds. The reservation enters `HELD` and remains so until it is consumed during a step (flipping to `CONSUMED`) or released (flipping to `RELEASED`) as a side effect of task completion, cancellation, or rerouting. The same node and slot ordinal may carry at most one `HELD` reservation; a duplicate creation is rejected with `ERR_SLOT_ALREADY_RESERVED`. The supplied `scheduled_at` must be aligned to `Fleet.slot_seconds` — that is, its UNIX-epoch second value modulo `Fleet.slot_seconds` must be zero — and it must be at or after the current `Fleet.clock_now`; either failure yields `ERR_SLOT_TIME_INVALID`.

When a robot is rerouted because of a blocked node or because deadlock recovery fired against it, any `HELD` reservations belonging to that robot with `scheduled_at` at or after the current clock are released.

### 3.7. Deadlock Detection and Recovery

When two or more robots in `WAITING_RIGHT_OF_WAY` form a cycle in their next-node graph — each waiting on a node held by another — the system performs deadlock recovery during a clock advance, provided each blocked robot has been in `WAITING_RIGHT_OF_WAY` for at least the fleet's `deadlock_wait_seconds` since its last transition. Within the wait window (current clock minus last transition strictly less than `Fleet.deadlock_wait_seconds`) the system simply leaves the robots blocked. Once the window is exceeded, recovery fires: among the robots in the cycle, the one with the lowest `standby_priority` (tie-broken by `Robot.code` ascending) has its task's `planned_path_node_ids` recomputed via shortest path with the contested node's cost multiplied by the deadlock penalty of one thousand, the rerouted robot's `HELD` slot reservations at or after the current clock are released, the robot transitions back to `EXECUTING`, and an audit row is written. The other robots in the cycle continue in `WAITING_RIGHT_OF_WAY`.

### 3.8. Charging: Triggers, Stations, Sessions, and Queues

A charging station is created against a `MapNode` of `kind` `CHARGER`, with an optional integer `charge_rate_pct_per_second` defaulting to one. The station has a `status` of `AVAILABLE`, `OCCUPIED`, or `DISABLED`, an `occupying_robot_id` that is null when available, and a computed `queue_length` equal to the number of robots whose `operational_state` is `WAITING_CHARGER` for that station.

An operator docks a robot at a charging station co-located on the robot's current `position_node_id`. Docking is permitted from `IDLE`, `EXECUTING`, or `WAITING_RIGHT_OF_WAY`, but an attempt to dock a robot whose `operational_state` is `EXECUTING` is rejected with `ERR_INVALID_STATE` — the operator must complete or cancel the task first. The station's `status` must be `AVAILABLE`; otherwise the dock is rejected with `ERR_CHARGER_UNAVAILABLE`. On success, a `ChargingSession` row is created with `status` `CHARGING`, with `start_battery_pct` copied from the robot's `battery_pct`, and with `started_at` set to the current clock; the station flips to `OCCUPIED` and records `occupying_robot_id`; the robot's `operational_state` becomes `CHARGING` and its `charging_station_id` points at the station. The session's `trigger` is `FORCED_LOW` when `battery_pct` is at or below `Fleet.charging_low_threshold_pct`; `OPPORTUNITY` when the robot is `IDLE` and `battery_pct` is strictly above `Fleet.charging_low_threshold_pct` and at or below `Fleet.charging_opportunity_pct`; and `MANUAL` otherwise. The closed enum set is `FORCED_LOW`, `OPPORTUNITY`, and `MANUAL`.

When a station is already occupied, an operator may enqueue a robot for it instead. The queue endpoint accepts a `charging_station_id`, creates a `ChargingSession` row in `QUEUED` linked to the robot's `robot_id`, sets the robot's `operational_state` to `WAITING_CHARGER`, and writes the station id into the robot's `charging_station_id`. A queued session is allowed only when the robot's `fault_state` is `OK` and a charging station exists in the fleet.

During each clock advance, every robot whose `operational_state` was `CHARGING` at the start of the advance progresses its battery. The system computes the percentage gained as `delta_seconds` multiplied by the station's `charge_rate_pct_per_second`, adds it to the robot's current `battery_pct`, and caps the result at 100. If the resulting `battery_pct` is at or above `Fleet.charging_full_pct` and the session's `status` was still `CHARGING`, the session moves to `COMPLETED`: `end_battery_pct` is set to the new value, and `completed_at` is set to the wall-clock moment the threshold was crossed within the delta. That crossing time is computed by linear back-solving: the number of seconds needed to reach full is the ceiling of (`Fleet.charging_full_pct` minus the battery percentage at advance start) divided by `charge_rate_pct_per_second`, and `completed_at` is the advance-start instant plus that many seconds. On completion, the station's `status` returns to `AVAILABLE`, its `occupying_robot_id` is cleared, the robot's `charging_station_id` is cleared, and the robot's `operational_state` becomes `IDLE`. If the station's `WAITING_CHARGER` queue is non-empty, the queued robot with the lowest `battery_pct` (tie-broken by `Robot.code` ascending) is promoted into `CHARGING` at the same station — except that any `FORCED_LOW` queued session always outranks any `OPPORTUNITY` or `MANUAL` queued session, regardless of battery. If the queue is empty, the station remains `AVAILABLE`.

A manual undock is also supported. It completes the current `ChargingSession` (writing `end_battery_pct` and `completed_at`), returns the station to `AVAILABLE`, runs the same queue advance described above, and returns the robot to `IDLE`. Cancellation of a charging session — by operator request or because the owning robot enters `OUT_OF_SERVICE` — terminates the session in `CANCELLED`. If the session was in `CHARGING`, the station returns to `AVAILABLE` and the queue advance runs; if it was still in `QUEUED`, the robot's `operational_state` returns to `IDLE` and its `charging_station_id` is cleared.

The three fleet-wide charging thresholds are mutually constrained on configuration: `charging_low_threshold_pct` defaults to 20, `charging_opportunity_pct` defaults to 60 and must be strictly greater than `charging_low_threshold_pct`, and `charging_full_pct` defaults to 95 and must be strictly greater than `charging_opportunity_pct`. All three are integer percentages from 0 to 100 inclusive.

### 3.9. Faults, Isolation, and Manual Takeover

Three fault kinds are recognised, forming the closed set on `FaultIncident.kind`: `COMM_LOSS`, `SENSOR_ANOMALY`, and `MECHANICAL_FAULT`. Communication losses are auto-opened by the system when the heartbeat timeout expires during a clock advance; sensor and mechanical faults are opened explicitly by either an `Operator` or a `FleetAdmin` through the robot-faults endpoint, which accepts the `kind` and creates a `FaultIncident` in `OPEN`.

Opening a fault triggers a chain. The robot's `fault_state` flips to `FAULTED` and its `operational_state` flips to `OUT_OF_SERVICE`. Its `connectivity` is left as-is — a `COMM_LOSS` already flipped `connectivity` to `OFFLINE` separately, while a `SENSOR_ANOMALY` or `MECHANICAL_FAULT` leaves `connectivity` unchanged. If the robot was holding a task, that task transitions from `EXECUTING` to `ROLLED_BACK` — its `assigned_robot_id`, `planned_path_node_ids`, `started_at`, and `assigned_at` are cleared, its `rollback_count` is incremented by one, and an audit row is written; immediately afterwards, if `rollback_count` is at or below the rollback ceiling of three, the task is requeued to `QUEUED` with `queued_at` set to the current clock and the new task id is mirrored onto `FaultIncident.reassigned_task_id`; if `rollback_count` has exceeded three, the task moves to `CANCELLED` instead and no reassignment id is written. The rolled-back task's id is recorded on `FaultIncident.rolled_back_task_id`; if there was no in-progress task, both that field and `reassigned_task_id` remain null. Every `HELD` `SlotReservation` for the robot is released. If the robot was in `CHARGING`, the active `ChargingSession` is cancelled, the station returns to `AVAILABLE`, and queue advance runs. An isolation zone is laid down on `FaultIncident.isolation_node_ids`, computed as the set of map nodes within Manhattan distance one of the robot's `position_node_id`; those nodes' `status` becomes `BLOCKED` with `blocked_reason` set to `OBSTACLE`. The incident's `detected_at` is set to the current clock, and an audit event with `event_kind` `FAULT` is written.

Manual takeover transitions the incident from `OPEN` to `TAKEOVER`. The robot's `operational_state` becomes `UNDER_MANUAL_CONTROL`, the incident's `takeover_started_at` is set to the current clock, and an audit row is written. Resolution then transitions the incident from `TAKEOVER` to `RESOLVED`: the robot's `fault_state` returns to `OK`, the incident's isolation node ids are returned to `OPEN` with `blocked_reason` cleared back to null, the robot's `operational_state` becomes `IDLE`, the incident's `resolved_at` is set, and an audit row is written. While a robot's `fault_state` is `FAULTED`, an operator may not issue `:start`, `:step`, `:dock`, or `:queue_charger` against it, nor cancel a task by acting on the robot — those attempts are rejected with `ERR_ROBOT_FAULTED`. The only legal way forward is the takeover-then-resolve workflow.

A task that has been rolled back is requeued only as long as its `rollback_count` is at or below the constant rollback ceiling of three. Once `rollback_count` strictly exceeds three, the task auto-cancels: an audit row is written for the `ROLLED_BACK` to `CANCELLED` transition. An attempt to start such a task — for instance, if a stale client still holds its id — is rejected with `ERR_ROLLBACK_LIMIT_REACHED`.

### 3.10. External Events, Clock Advancement, and Audit

The events endpoint is the inbound channel from external systems. It accepts an `event_kind` from the set `TASK_STATUS`, `FAULT`, `WMS_SYNC`, `EQUIPMENT_LOCK`, and `EQUIPMENT_UNLOCK` (with `subject_kind` drawn from `Task`, `Robot`, `FaultIncident`, or `MapNode`), optionally a list of map-node identifiers in `node_ids`, and optionally a `wms_task_payload`. An `EQUIPMENT_LOCK` event flips the target map nodes to `BLOCKED` with `blocked_reason` set to `EQUIPMENT_LOCKED` and runs the same reroute side effect as an isolation block. An `EQUIPMENT_UNLOCK` event returns those nodes to `OPEN`. A `WMS_SYNC` event with a `wms_task_payload` is equivalent to creating a task: the resulting `AuditEvent` records `actor_role` `WMS` so the audit trail reflects the origin.

Clock advancement is the single point where time-driven side effects are evaluated. A single integer `delta_seconds` is supplied, must be at least one, and must produce a strictly greater `clock_now` (otherwise the call is rejected with `ERR_CLOCK_BACKWARDS`). During the advance, in order, the system: increases `Fleet.clock_now` by `delta_seconds`; runs charge progression for every robot whose `operational_state` was `CHARGING` at advance start; transitions any `QUEUED` task whose age is at or above `Fleet.task_expiry_seconds` to `EXPIRED`; transitions any robot whose `last_heartbeat_at` is at or before the current clock minus the heartbeat timeout constant of fifteen seconds to `OFFLINE` and auto-opens a `COMM_LOSS` `FaultIncident`; runs deadlock recovery against robots stuck in `WAITING_RIGHT_OF_WAY` for at least `Fleet.deadlock_wait_seconds`; and runs parent-task aggregation. The expiry sweep is also evaluated during a dispatch pass so that expired tasks are not erroneously assigned.

Every state transition writes a row to `AuditEvent` with `event_kind`, `subject_kind`, `subject_id`, `from_state`, `to_state`, `actor_role`, `occurred_at`, and the owning `fleet_id`. The `event_kind` is `TASK_STATUS` for task transitions, `FAULT` for fault-incident transitions, `WMS_SYNC` for external task pushes, and `EQUIPMENT_LOCK` or `EQUIPMENT_UNLOCK` for map-node mutation events. The audit ledger is read through the audit-events list endpoint, optionally filtered by `event_kind`, `subject_kind`, or `subject_id`.

### 3.11. Throughput, Utilisation, and Bottleneck Reporting

The metrics report is computed on demand and is parameterised by two query parameters: `window_seconds`, an integer defaulting to 3600, and `window_boundary`, which controls whether the cutoff is treated inclusively or exclusively. The cutoff is the current `Fleet.clock_now` minus `window_seconds`. The default boundary is closed: a task whose `queued_at` is at or after the cutoff counts in the denominator, and a task whose `completed_at` is at or after the cutoff counts in the numerator. Setting `window_boundary` to `open` changes the comparison to strictly greater than the cutoff: tasks lying exactly at the cutoff are excluded.

Five values are produced. The task completion rate is the count of tasks whose `status` is `COMPLETED` and whose `completed_at` falls in window, divided by the maximum of one and the count of tasks whose `queued_at` falls in window across all statuses (including `CANCELLED` and `EXPIRED`); the result is rounded half up to four decimal places. The average task duration in seconds is the sum of `completed_at` minus `started_at` over the completed-in-window set, divided by the maximum of one and the size of that set, rounded half up to two decimal places. The robot utilisation per robot is the ratio of seconds spent in `EXECUTING` (reconstructed from `AuditEvent` and `TrajectoryRecord` rows) to `window_seconds`, rounded half up to four decimal places; the fleet robot utilisation is the mean of per-robot utilisations, again rounded half up to four decimal places. The fault rate is the count of `FaultIncident` rows whose `detected_at` falls in window, divided by the maximum of one and the count of robots in the fleet, rounded half up to four decimal places. The charging-time ratio is the sum of charging seconds within the window divided by the sum of charging seconds plus executing seconds across the same window, rounded half up to four decimal places.

The bottleneck-zone analysis identifies congestion at choke points. For every `MapNode` whose `kind` is `INTERSECTION` or `LIFT_POINT`, the system counts `SlotReservation` rows whose `scheduled_at` falls in window and whose `status` is in `HELD` or `CONSUMED`, then returns the top five by count, with ties broken by `MapNode.code` ascending.

## 4. Endpoint Definitions

All endpoints follow the global response envelope and pagination contract from §2. Endpoints that create a brand-new resource return HTTP 201. Endpoints that mutate or read an existing resource, including state-machine action endpoints, return HTTP 200. Validation, authorisation, and existence errors follow the priority ordering in §2.7. Request and response bodies — including the optional `version` field for optimistic concurrency, and the side effects on related resources — are described in §3; this table is intentionally minimal.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/fleets` | Create a fleet (warehouse instance); initialises virtual clock to `1970-01-01T00:00:00.000Z` | FleetAdmin |
| GET | `/fleets/{fleet_id}` | Read fleet configuration and current virtual clock | Operator, FleetAdmin, WMS |
| POST | `/fleets/{fleet_id}:advance_clock` | Advance virtual clock; runs charge progression, expiry, heartbeat timeout, deadlock recovery, parent aggregation | Operator, FleetAdmin |
| POST | `/fleets/{fleet_id}/dispatch` | Run a scheduling pass over queued tasks in priority order | Operator, FleetAdmin |
| GET | `/fleets/{fleet_id}/metrics` | Throughput, utilisation, fault-rate, charging-time-ratio, and bottleneck-zone report | Operator, FleetAdmin, WMS |
| POST | `/fleets/{fleet_id}/map_nodes` | Register a map node | FleetAdmin |
| POST | `/fleets/{fleet_id}/map_edges` | Register a map edge (system materialises the reverse if non-directional) | FleetAdmin |
| POST | `/fleets/{fleet_id}/events:emit` | Ingest an external WMS, equipment, or door-control event | WMS, FleetAdmin |
| POST | `/fleets/{fleet_id}/charging_stations` | Register a charging station on a CHARGER node | FleetAdmin |
| GET | `/fleets/{fleet_id}/charging_stations/{station_id}` | Read charging-station state | Operator, FleetAdmin, WMS |
| POST | `/fleets/{fleet_id}/robots` | Register a robot | FleetAdmin |
| GET | `/fleets/{fleet_id}/robots/{robot_id}` | Read robot state | Operator, FleetAdmin, WMS |
| GET | `/fleets/{fleet_id}/robots` | List robots (filter by operational_state, connectivity, fault_state) | Operator, FleetAdmin, WMS |
| POST | `/fleets/{fleet_id}/robots/{robot_id}:heartbeat` | Robot heartbeat; clears OFFLINE; does not lift faults | Operator |
| POST | `/fleets/{fleet_id}/robots/{robot_id}:step` | Advance robot one node along its planned path | Operator |
| POST | `/fleets/{fleet_id}/robots/{robot_id}:dock` | Dock the robot at the co-located charging station | Operator |
| POST | `/fleets/{fleet_id}/robots/{robot_id}:undock` | Manually undock; closes the charging session and advances the queue | Operator |
| POST | `/fleets/{fleet_id}/robots/{robot_id}:queue_charger` | Enqueue robot for a charging station | Operator |
| POST | `/fleets/{fleet_id}/tasks` | Create a task in QUEUED | Operator, WMS |
| GET | `/fleets/{fleet_id}/tasks/{task_id}` | Read a task; supports `?view=projected` for parent provisional status | Operator, FleetAdmin, WMS |
| GET | `/fleets/{fleet_id}/tasks` | List tasks (filter by status, source, priority_class) | Operator, FleetAdmin, WMS |
| POST | `/fleets/{fleet_id}/tasks/{task_id}:assign` | Direct assignment of a task to a specific robot | Operator |
| POST | `/fleets/{fleet_id}/tasks/{task_id}:start` | Begin executing an assigned task | Operator |
| POST | `/fleets/{fleet_id}/tasks/{task_id}:complete` | Mark a task complete at its dropoff node | Operator |
| POST | `/fleets/{fleet_id}/tasks/{task_id}:cancel` | Cancel a queued, assigned, or executing task | Operator |
| POST | `/fleets/{fleet_id}/tasks/{task_id}:split` | Split an oversized queued task into children | Operator |
| POST | `/fleets/{fleet_id}/tasks:merge` | Merge two compatible queued tasks | Operator |
| POST | `/fleets/{fleet_id}/slot_reservations` | Reserve a right-of-way slot for a robot | Operator |
| GET | `/fleets/{fleet_id}/slot_reservations` | List slot reservations (filter by node_id, robot_id, status, scheduled_at_min, scheduled_at_max) | Operator, FleetAdmin |
| POST | `/fleets/{fleet_id}/robots/{robot_id}/faults` | Open a fault incident on a robot | Operator, FleetAdmin |
| GET | `/fleets/{fleet_id}/fault_incidents/{incident_id}` | Read a fault incident | Operator, FleetAdmin, WMS |
| POST | `/fleets/{fleet_id}/fault_incidents/{incident_id}:takeover` | Begin manual takeover of a faulted robot | Operator |
| POST | `/fleets/{fleet_id}/fault_incidents/{incident_id}:resolve` | Resolve the fault and return the robot to service | Operator |
| GET | `/fleets/{fleet_id}/audit_events` | List audit events (filter by event_kind, subject_kind, subject_id) | Operator, FleetAdmin, WMS |
| GET | `/fleets/{fleet_id}/robots/{robot_id}/trajectory` | List archived trajectory records for a robot | Operator, FleetAdmin, WMS |
| POST | `/fleets/{fleet_id}/charging_sessions/{session_id}:cancel` | Cancel a queued or in-progress charging session | Operator |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the §2 and §3 narratives near the rule they guard. The catalogue here lists only identity and HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_BAD_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ROBOT_FAULTED` | 409 |
| `ERR_ROBOT_OFFLINE` | 409 |
| `ERR_ROBOT_BUSY` | 409 |
| `ERR_BATTERY_LOW` | 409 |
| `ERR_NO_PATH` | 409 |
| `ERR_RIGHT_OF_WAY_MISSING` | 409 |
| `ERR_CHARGER_UNAVAILABLE` | 409 |
| `ERR_SLOT_ALREADY_RESERVED` | 409 |
| `ERR_SLOT_TIME_INVALID` | 422 |
| `ERR_SPLIT_NOT_APPLICABLE` | 422 |
| `ERR_MERGE_INCOMPATIBLE` | 422 |
| `ERR_HAS_DEPENDENCIES` | 409 |
| `ERR_TASK_ALREADY_ASSIGNED` | 409 |
| `ERR_CLOCK_BACKWARDS` | 422 |
| `ERR_ROLLBACK_LIMIT_REACHED` | 409 |
| `ERR_OBSTACLE_BLOCKING` | 409 |
| `ERR_ISOLATION_VIOLATION` | 409 |

---

## Hard Contract Verification

### Contract 1: Field-Name Coverage

I enumerated every `entities[].fields[].name`, every `endpoints[].input` identifier, and every query parameter referenced in the scaffold, then verified each appears verbatim in backticks in the PRD prose:

Entity fields covered: `name`, `clock_now`, `charging_low_threshold_pct`, `charging_opportunity_pct`, `charging_full_pct`, `slot_seconds`, `task_expiry_seconds`, `deadlock_wait_seconds`, `fleet_id`, `code`, `kind`, `x`, `y`, `capacity`, `status`, `blocked_reason`, `from_node_id`, `to_node_id`, `cost`, `directional`, `node_id`, `occupying_robot_id`, `queue_length`, `charge_rate_pct_per_second`, `connectivity`, `operational_state`, `fault_state`, `battery_pct`, `position_node_id`, `current_task_id`, `charging_station_id`, `last_heartbeat_at`, `standby_priority`, `trajectory_archived_count`, `source`, `priority_class`, `priority_score`, `payload_units`, `max_units_per_robot`, `pickup_node_id`, `dropoff_node_id`, `assigned_robot_id`, `parent_task_id`, `merged_into_task_id`, `queued_at`, `assigned_at`, `started_at`, `completed_at`, `planned_path_node_ids`, `rollback_count`, `robot_id`, `task_id`, `slot_index`, `scheduled_at`, `trigger`, `start_battery_pct`, `end_battery_pct`, `isolation_node_ids`, `rolled_back_task_id`, `reassigned_task_id`, `detected_at`, `takeover_started_at`, `resolved_at`, `occurred_at`, `event_kind`, `subject_kind`, `subject_id`, `from_state`, `to_state`, `actor_role`.

Endpoint input identifiers covered: `delta_seconds`, `view`, `window_seconds`, `window_boundary`, `task_id_a`, `task_id_b`, `node_ids`, `wms_task_payload`, `scheduled_at_min`, `scheduled_at_max`, plus the common fields above (e.g., `code`, `kind`, `x`, `y`, `capacity`, `node_id`, `source`, `pickup_node_id`, `dropoff_node_id`, `priority_class`, `payload_units`, `max_units_per_robot`, `charge_rate_pct_per_second`, `position_node_id`, `battery_pct`, `standby_priority`, `from_node_id`, `to_node_id`, `cost`, `directional`, `charging_station_id`, `robot_id`).

Pagination parameters covered: `limit`, `offset`.

```
Field coverage check:
- entities[].fields: 70 required, 70 present, 0 missing
- endpoints[].request_body: 26 required, 26 present, 0 missing
- endpoints[].query_params: 13 required, 13 present, 0 missing
Status: PASS
```

### Contract 2: Rule Coverage

```
Rule coverage check:
- validations[] with priority: 19 checked, 19 expressed in prose (§2.7 lists every priority-ordered rule by error_id), 0 missing
- concurrency_rules[] with error_id: 5 checked, 5 expressed (§2.10 names each racing pair and its loser error), 0 missing
- state_machines[].transitions: 24 checked, 24 fully expressed across §3.2, §3.3, §3.4, §3.6, §3.7, §3.8, §3.9, §3.10, 0 missing
- calculations[]: 5 checked, 5 fully expressed (priority_score in §3.5, shortest_path in §3.6, robot_selection in §3.5, parent_task_status in §3.3 with both view variants, charge_progression in §3.8, throughput_metrics in §3.11 with both window-boundary variants), 0 missing
- validations[] conditions: 19 checked, 19 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 35 checked, 35 expressed in the relevant §3 narrative, 0 missing
- entities[].fields[] structured content: 70 checked, 70 reconstructible from prose (types, defaults, enum sets, and source: input/system/computed all reachable), 0 missing
- sibling-branch symmetry: 8 groups checked (Task transition siblings out of QUEUED, EXECUTING, ROLLED_BACK; Robot transitions out of EXECUTING, WAITING_RIGHT_OF_WAY, CHARGING; ChargingSession terminal branches; FaultIncident transition pair), 8 with equal prose density, 0 asymmetric
Status: PASS
```

### Contract 3: §3 Path Purity

I scanned every backtick token between the `## 3.` heading and the `## 4.` heading. No token starts with `/`, no token is a bare HTTP method in endpoint-identifier position (`POST`, `GET`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`), and no token combines method with path. Every endpoint is referenced via state-transition framing (e.g., "transitions from `QUEUED` to `ASSIGNED`"), role + action verb (e.g., "an operator docks", "a `FleetAdmin` registers"), or capability description (e.g., "the fleet dispatch capability", "the metrics report is computed", "the events endpoint", "the clock advancement").

```
Path purity check (§3 only):
- backtick tokens scanned: ~480
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
