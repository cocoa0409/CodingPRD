# Plant Turnaround API — Product Requirements Document

## 1. Introduction

A plant maintenance shutdown — a turnaround — is one of the most expensive and schedule-sensitive events an industrial operator runs. Thousands of candidate work items compete for inclusion in a fixed execution window, contractor crews must be mobilized and badged before they can turn a wrench, every hazardous job requires a permit tied to verified equipment isolations, and the true scope of the work is never fully known until equipment is opened up mid-execution. The Plant Turnaround API orchestrates this entire lifecycle for a turnaround contractor: freezing and ranking the work list, building the critical-path schedule and the shift plan, coordinating permits and isolations, authorizing discovery work against a contingency pool, staging materials in lay-down areas, posting daily cost and progress reports, and closing out through a startup punch list into formal handover.

The system is deliberately strict about money, safety, and time. Financial exposure is tracked through a continuously recomputed cost forecast exposed in two variants — one committed, one provisional — so that management sees both hard commitments and the softer shadow of pending discovery quotes and critical-path slip. Segregation of duties is enforced at the points where self-dealing would be easiest: the person who reports a discovery cannot be the one who authorizes it, and the person who submits a daily cost report cannot be the one who approves it. Shared state that clients read before writing — a work item's estimate, a lay-down area's free capacity — is guarded by optimistic concurrency so no client can commit on the basis of a stale read. Finally, all temporal behavior — permit validity windows, automatic expiry sweeps, report dating — reads a deterministic logical clock rather than the wall clock, so the full lifecycle is reproducible under test.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint of the API. All collections are mounted at the root of the URL space — for example `/turnarounds`, `/work-items`, `/permits` — with no shared prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly six roles: `TurnaroundManager`, `Planner`, `PermitCoordinator`, `ContractorSupervisor`, `CostController`, and `OperationsRep`.

- A `TurnaroundManager` is the turnaround authority: scope freeze, phase advances, change authorization, handover, and the ops-run checkpoint belong to this role.
- A `Planner` owns planning and scheduling: the work list, the dependency network, the shift plan, and crew assignments.
- A `PermitCoordinator` controls permit-to-work and isolations, and runs worker vetting and badging.
- A `ContractorSupervisor` is the contractor-side supervisor: mobilization, the worker registry, field execution, daily reports, and staging.
- A `CostController` controls the cost ledger: approval, rejection, and voiding of daily reports.
- An `OperationsRep` is the operations representative: verifying completed work, owning punch verification, and witnessing handover.

When `X-User-Role` is `ContractorSupervisor`, `X-User-ID` is the `id` of the acting `Contractor`; ownership checks on any resource that references a `Contractor` compare the resource's foreign-key field to `X-User-ID`. Concretely, mobilizing a contractor, registering a worker under a contractor, and submitting a contractor's daily report all require the acting supervisor's `X-User-ID` to equal the target contractor's `id`; a mismatch is rejected with `ERR_FORBIDDEN`. When acting on shared endpoints — assigning workers to shifts or cancelling assignments — a `ContractorSupervisor` may only touch their own contractor's workers.

When `X-User-Role` is `TurnaroundManager`, `Planner`, `PermitCoordinator`, `CostController`, or `OperationsRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `reported_by_user_id` on a discovery, `authorized_by_user_id` on a discovery decision, or `submitted_by_user_id` and `approved_by_user_id` on a daily report — and segregation-of-duties checks compare these recorded user identifiers against the acting `X-User-ID`, but an opaque role's `X-User-ID` is never compared to any entity's `id`.

Beyond authentication, every endpoint restricts which roles may invoke it, per the endpoint table in §4. A request whose role is not permitted for the endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell how many records exist in total and whether further pages remain.

### 2.4. The Logical Clock

The server maintains a logical clock, and every time-sensitive rule in this document — permit validity windows, the ops-run expiry sweep, the check that a `report_date` is not in the future — reads this clock and never the host's wall clock. At server startup, before any client has set it, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `TurnaroundManager` may move the logical clock through an administrative test-driving capability that accepts a `to_iso8601` instant; the response echoes the new time as `current_utc`, rendered as an ISO 8601 UTC timestamp with three fractional digits — the same format §2.2 pins for server-generated timestamps — rather than by repeating the request string verbatim. The server never falls back to wall-clock time under any circumstance, which makes permit expiry, staging-window release, and reporting deadlines fully deterministic.

### 2.5. Common Resource Properties and Versioning

Every primary resource — turnarounds, work items, contractors, workers, shifts, shift assignments, permits, isolations, discoveries, lay-down areas, staging reservations, daily reports, and punch items — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by exactly one on every mutation, including mutations caused by cascades originating on other resources.

The one exception is the work-item dependency edge. A `WorkItemDependency` is immutable after creation and therefore carries only `id` and `created_at`; `updated_at` and `version` are absent from it.

### 2.6. Money, Hours, and Rounding Discipline

All monetary amounts are represented as integer cents — budgets, costs, quotes, overheads, and ledger totals alike. Where a calculation produces a fractional cent, the result is rounded half-up to a whole cent. Daily-report pricing applies this rounding exactly once per report line, before any aggregation and before any cap; the per-line rounded figures are then summed, and this order — round each line first, sum second — is pinned and must not be inverted. Hour quantities (`estimated_hours`, `planned_hours`, `actual_hours`, and their derivatives) are plain numbers and are never rounded. Work-list ranking arithmetic uses whole-number floor division where specified. Staging areas and their reservations are measured in whole square meters.

### 2.7. Optimistic Concurrency Control

Two write operations commit shared state that the client necessarily read before deciding to write, and both are guarded by optimistic concurrency control.

A request to re-estimate a work item must carry `expected_work_item_version`, holding the `version` of the work item as the planner last observed it. If that value no longer matches the work item's current `version` — because another estimate has already been applied since the client last read the item — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the planner from overwriting an estimate it has not observed.

A request to create a staging reservation must carry `expected_laydown_area_version`, holding the `version` of the lay-down area as the client last observed it. Since creating a reservation commits shared capacity computed from the area's `occupied_sqm` at read time, a mismatch with the area's current `version` — because another reservation or release has already been applied — is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. In particular, state transitions and phase advances rely on their state-machine preconditions rather than on OCC, and any resource `version` supplied to an endpoint not listed above is not consulted.

### 2.8. Validation Order and Error Precedence

Every request is evaluated against a fixed cascade of checks, and the first failing check in this order determines the error returned. The order is not incidental — it guarantees, for example, that an unauthenticated caller learns nothing about resource existence, and that a stale-version rejection surfaces before a request-shape complaint.

1. Authentication: `X-User-ID` and `X-User-Role` are present and the role is one of the six declared roles; failure yields `ERR_UNAUTHENTICATED`.
2. Authorization: the role is permitted for the endpoint and, for contractor-scoped writes, the `ContractorSupervisor` ownership check passes; failure yields `ERR_FORBIDDEN`.
3. Existence: path identifiers resolve, validated left-to-right; failure yields `ERR_NOT_FOUND`.
4. Stale version: on the two OCC-guarded writes, the supplied `expected_work_item_version` or `expected_laydown_area_version` matches the parent's current `version`; failure yields `ERR_STALE_VERSION`.
5. Request shape: required fields are present, enum members are valid, quantities are positive where required, and windows start before they end; failure yields `ERR_INVALID_REQUEST`.
6. Cross-scope references: referenced resources resolve within the same turnaround, and report-line workers belong to the submitting contractor; failure yields `ERR_CROSS_SCOPE_REFERENCE`.
7. State legality: the target resource is in a legal state for the operation per its state machine — this tier also covers scope-frozen edits, since work-item creation, re-estimation, and dependency edits are only legal while the turnaround is `PLANNING`; failure yields `ERR_INVALID_STATE`.
8. Segregation of duties: the discovery decider differs from the reporter, and the daily-report approver differs from the submitter; failure yields `ERR_SOD_VIOLATION`.
9. Safety gates, applicable to crew assignment, daily-report drafting, work-item start, permit transitions, and isolation transitions: the worker's badge is `BADGED` (`ERR_BADGE_NOT_CLEARED`), the projected fatigue penalty stays below the limit (`ERR_FATIGUE_LIMIT`), a permit-requiring item has an `ACTIVE` permit (`ERR_PERMIT_NOT_ACTIVE`), required isolations meet their required status (`ERR_ISOLATION_NOT_VERIFIED`), and de-isolation is not blocked by a live permit (`ERR_ISOLATION_IN_USE`).
10. Temporal rules, applicable to crew assignment, isolation planning, and permit transitions: no half-open shift overlap (`ERR_SHIFT_OVERLAP`), the minimum rest gap holds (`ERR_REST_PERIOD_VIOLATION`), no isolation window conflict (`ERR_ISOLATION_CONFLICT`), and the permit action falls inside its validity window (`ERR_PERMIT_WINDOW_INVALID`).
11. Structural and capacity constraints: the dependency graph stays acyclic (`ERR_DEPENDENCY_CYCLE`), the contractor badge cap holds (`ERR_CONTRACTOR_HEADCOUNT_CAP`), the shift has headcount room (`ERR_SHIFT_HEADCOUNT_FULL`), the shift is still `PLANNED` (`ERR_SHIFT_LOCKED`), a lock has at least one assignment (`ERR_EMPTY_SHIFT`), mobilization prerequisites hold (`ERR_NO_BADGED_WORKERS`, `ERR_NO_MOBILIZED_CONTRACTOR`), the startup gates hold (`ERR_WORK_ITEMS_OPEN`, `ERR_PERMITS_STILL_ACTIVE`, `ERR_ISOLATIONS_ENGAGED`), the handover gate holds (`ERR_OPEN_PUNCH_ITEMS`), the appeal limit holds (`ERR_APPEAL_LIMIT`), the daily report is unique for its date (`ERR_DUPLICATE_REPORT`), and void ordering holds (`ERR_REPORT_SEQUENCE`).
12. Fiscal guard: a discovery authorization fits within the remaining contingency; failure yields `ERR_CONTINGENCY_EXCEEDED`.

### 2.9. Nested Resource Retrieval

Requests that target nested resources are validated strictly left-to-right along the path. The first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` immediately, before any later identifier is examined and before any business rule runs. A request addressed to a work item under a turnaround that does not exist therefore fails on the turnaround identifier, and a reservation request addressed to a non-existent lay-down area fails on the area identifier, regardless of what else the request contains.

### 2.10. Hierarchical Consistency and Cascade Discipline

State changes rarely stay on the resource that received the request. When a parent or peer resource is affected by a transition, the server applies the consequential mutation itself, immediately and atomically with the triggering change: placing a work item on hold suspends its active permits; revoking a permit places its in-progress work item on hold; demobilizing a contractor debadges its workers and cancels their pending assignments; authorizing a discovery creates its addendum work item; approving or voiding a daily report moves the turnaround's reported-cost ledger; reserving or releasing staging space moves the area's occupancy. Every resource mutated in such a cascade — parent or child — has its own `updated_at` refreshed and its own `version` incremented by exactly one, so a client holding any member of the cascade sees its version move. Computed aggregates (`committed_cost_cents`, `reported_cost_cents`, `critical_path_slip_hours`, `badged_headcount`, `occupied_sqm`, and the cost forecast) are always recomputed from their input sets at the moment a triggering event lands; they are never adjusted by deltas that could drift from the true state.

## 3. Business Logic & Workflows

### 3.1. Building the Work List and Freezing the Scope

A `TurnaroundManager` opens a turnaround by supplying its `name`, the `plant_unit` identifier (for example a crude unit tag), the planned execution window as `planned_start` and `planned_end`, the `authorized_budget_cents` — which must be strictly positive — and the `contingency_budget_cents` drawdown pool, which may be zero but never negative. A new turnaround begins with `status` of `PLANNING`, `cost_posture` of `WITHIN_BUDGET`, `committed_cost_cents` and `reported_cost_cents` of zero, `critical_path_slip_hours` of zero, `schedule_run_index` of zero, and `scope_frozen_at` and `handed_over_at` both null. Over its life a turnaround's `status` moves through `PLANNING`, `SCOPE_FROZEN`, `MOBILIZATION`, `EXECUTION`, `STARTUP`, and ends in `HANDED_OVER` or `CANCELLED`.

While the turnaround is `PLANNING`, a `Planner` builds the candidate work list. Each proposed item carries a `title`, a `system_area` tag, a `work_type` of `CORRECTIVE`, `PREVENTIVE`, `INSPECTION`, or `DISCOVERY_ADDENDUM`, a `risk_class` of `A`, `B`, or `C` — `A` marking the highest risk — a strictly positive `estimated_hours`, a non-negative `estimated_cost_cents`, and an optional `requires_permit` flag that defaults to false. A proposed item starts in `PROPOSED` with `rank_score` and `rank_position` still null, `is_critical_path` false, and `actual_hours`, `planned_shift_id`, and `discovery_id` all null. The scope-freeze rule is absolute: creating a work item, re-estimating one, and adding a dependency edge are all legal only while the turnaround remains `PLANNING`; once the scope is frozen any of these edits is rejected with `ERR_INVALID_STATE`.

Re-estimation lets a `Planner` revise a `PROPOSED` item's `estimated_hours`, `estimated_cost_cents`, and `risk_class`. Because a second well-formed estimate would succeed on its own merits at any time before freeze, the write is guarded by optimistic concurrency as described in §2.7: the request must carry `expected_work_item_version`, and a stale value is rejected with `ERR_STALE_VERSION`. Each accepted estimate increments the item's `version`.

The `Planner` also wires the dependency network. Adding a dependency to a work item records that the item named in the payload as `predecessor_work_item_id` must finish before the item in the path — recorded on the edge as `successor_work_item_id` — may start, optionally with a non-negative `lag_hours` gap that defaults to zero. Every edge also stores the turnaround's `turnaround_id` as a denormalized scope guard: the predecessor and successor must both belong to the same turnaround as the edge, otherwise the request fails with `ERR_CROSS_SCOPE_REFERENCE`. The network is a directed acyclic graph; any edge that would close a cycle is rejected with `ERR_DEPENDENCY_CYCLE`, and a self-loop — an item depending on itself — counts as a cycle. While the scope is still fluid, every dependency change triggers a recomputation of the critical-path analysis so planners see the network's shape before freeze.

Scope freeze is the pivotal ceremony. A `TurnaroundManager` freezes the scope by supplying `scope_cutoff_count`; the action requires at least one `PROPOSED` work item and is rejected with `ERR_INVALID_STATE` on an empty list. At freeze, the system ranks every `PROPOSED` item. An item's downstream count is the number of distinct work items reachable from it by following successor edges through the transitive closure of the turnaround's dependency graph — the graph is guaranteed acyclic by the cycle check above. Its cost term is five hundred minus the whole-number floor division of its `estimated_cost_cents` by ten thousand, floored at zero so cheap items earn the full five hundred and sufficiently expensive items earn nothing from this term. The item's `rank_score` is its risk weight multiplied by one thousand — five for `A`, three for `B`, one for `C` — plus twenty-five for each reachable downstream item, plus the cost term. Items are then ordered by `rank_score` from highest to lowest, with ties broken by `created_at` ascending, and assigned a one-based `rank_position`. Every item whose `rank_position` is less than or equal to `scope_cutoff_count` — the cutoff is inclusive — transitions from `PROPOSED` to `FROZEN` and enters the committed scope; all remaining `PROPOSED` items become `DEFERRED`.

The same freeze computes the critical-path analysis over the `PROPOSED` items as they stood at freeze time; the network is frozen with the scope. Working in topological order — successors evaluated before their predecessors — each item's path length is its own `estimated_hours` plus, for each outgoing edge, the edge's `lag_hours` plus the successor's path length, taking the maximum over successors; an item with no successors contributes simply its own `estimated_hours`. The project length is the greatest path length across all items, an item's total float is the project length minus its own path length, and an item whose total float is exactly zero is marked `is_critical_path`. Freeze also stamps `scope_frozen_at`, recomputes the turnaround's `committed_cost_cents` from the newly frozen set, and increments the turnaround's `version`.

### 3.2. Contractor Mobilization and Worker Badging

Once the scope is frozen — and at any later pre-terminal phase — a `TurnaroundManager` invites contractors by supplying each company's `name`, its primary `craft`, and a `headcount_cap` of at least one, the maximum number of that contractor's workers who may hold a live badge at once. An invited contractor begins with `mobilization_status` of `INVITED` and `badged_headcount` of zero; over its engagement the contractor moves through `INVITED`, `MOBILIZING`, `MOBILIZED`, and finally `DEMOBILIZED`.

Mobilization is driven by the contractor's own supervision, one step per request, and every mobilization step requires the acting `ContractorSupervisor`'s `X-User-ID` to equal the contractor's `id`, failing with `ERR_FORBIDDEN` otherwise. Moving from `INVITED` to `MOBILIZING` requires the turnaround to be in `MOBILIZATION` or `EXECUTION`. Moving from `MOBILIZING` to `MOBILIZED` requires at least one badged worker — a `badged_headcount` of zero draws `ERR_NO_BADGED_WORKERS`. Moving from `MOBILIZED` to `DEMOBILIZED` is permitted only once the turnaround has reached `STARTUP`, and it unwinds the crew: every worker still `BADGED` or `SUSPENDED` is debadged, and each such debadging cancels that worker's `ASSIGNED` shift assignments.

A supervisor registers a worker under their own contractor by supplying the worker's `full_name` and `trade`; the new worker's `contractor_id` ties them to the employing contractor and their `badge_status` begins as `REGISTERED`. A worker's badge lifecycle runs `REGISTERED`, `VETTED`, `BADGED`, `SUSPENDED`, and ends at `DEBADGED`. A `PermitCoordinator` vets a `REGISTERED` worker — possible whenever the turnaround is neither `CANCELLED` nor `HANDED_OVER` — moving them to `VETTED`. Badging a `VETTED` worker requires three conditions: the contractor is `MOBILIZING` or `MOBILIZED`, the turnaround is in `MOBILIZATION` or `EXECUTION`, and the contractor has headcount room — a `badged_headcount` already equal to the `headcount_cap` draws `ERR_CONTRACTOR_HEADCOUNT_CAP`. A successful badging moves the worker to `BADGED` and raises the contractor's `badged_headcount` by one; the `badged_headcount` counter always reflects the number of the contractor's workers whose badge is live, counting both `BADGED` and `SUSPENDED` holders.

Badge transitions are addressed by a desired target carried in the `to` field. A `BADGED` worker may be moved to `SUSPENDED` without further checks. Reinstating a `SUSPENDED` worker to `BADGED` re-checks the headcount cap — an at-cap contractor draws `ERR_CONTRACTOR_HEADCOUNT_CAP` — and raises `badged_headcount` by one on success. Moving a worker to `DEBADGED`, whether from `BADGED` or `SUSPENDED` and whether by a coordinator's request or by the demobilization cascade, cancels every one of that worker's `ASSIGNED` shift assignments and lowers `badged_headcount` by one.

### 3.3. Shift Planning, Crew Assignment, and the Fatigue Gate

A `Planner` shapes the execution calendar by planning shifts. Each shift is defined by its `shift_date` in year-month-day form, a `shift_type` of `DAY` or `NIGHT`, its `starts_at` and `ends_at` instants — the end must be strictly after the start — and a `planned_headcount` of at least one, the maximum number of non-cancelled crew the shift will carry. A shift is born `PLANNED`; its full status vocabulary is `PLANNED`, `LOCKED`, `COMPLETED`, and `CANCELLED`, and the one transition the machine defines is the lock, which moves a `PLANNED` shift to `LOCKED` and requires at least one `ASSIGNED` assignment — locking an empty shift is rejected with `ERR_EMPTY_SHIFT`.

Assigning a worker to a shift — a capability shared by `Planner` and `ContractorSupervisor`, with supervisors restricted to their own contractor's workers — takes a `worker_id` and a strictly positive `planned_hours`, and creates an assignment in `ASSIGNED` whose `shift_id` is taken from the path. The assignment is gated by a battery of checks. The shift must still be `PLANNED`; assignments to a locked shift are refused with `ERR_SHIFT_LOCKED`. The worker's badge must be `BADGED`; anything else — `REGISTERED`, `VETTED`, `SUSPENDED`, or `DEBADGED` — draws `ERR_BADGE_NOT_CLEARED`. The shift must have room: when the number of non-`CANCELLED` assignments already equals `planned_headcount`, the assignment is rejected with `ERR_SHIFT_HEADCOUNT_FULL`. The worker must not already hold an assignment whose shift overlaps the candidate: shift intervals are compared as half-open ranges, so a candidate whose `starts_at` coincides exactly with an existing assignment's `ends_at` does not overlap, while any positive intersection draws `ERR_SHIFT_OVERLAP`. Consecutive assignments must also respect the minimum rest gap: the interval from the end of one kept assignment's shift to the start of the next must be at least ten hours, with a gap of exactly ten hours admitted and anything shorter rejected with `ERR_REST_PERIOD_VIOLATION`.

The final gate is fatigue, which the system evaluates in two variants over the same input set: the worker's assignments with status `ASSIGNED` or `COMPLETED` — `CANCELLED` and `NO_SHOW` are excluded — ordered by each assignment's shift `starts_at` ascending, with ties broken by the assignment's own `created_at` ascending.

The `HOURS_LEDGER` variant is the advisory view. The worker's `ledger_hours` field is the sum of `planned_hours` over the input set, a plain chronological hours accumulator: it would admit any worker whose ledger stays at or below sixty hours, regardless of how their rest is distributed.

The `PENALTY_WEIGHTED` variant is the enforcing gate and feeds the worker's stored `fatigue_penalty_score`. Walking the ordered assignments, each assignment adds five penalty points when its shift is a `NIGHT` shift, and ten penalty points when the gap from the previous kept assignment's shift end to this shift's start is at least ten hours but strictly less than fourteen hours — a rest window long enough to be legal but short enough to accumulate fatigue. When a candidate assignment is evaluated, its shift is inserted into the worker's ordering and the projected penalty score is computed with the candidate included; a projected score of twenty or more rejects the assignment with `ERR_FATIGUE_LIMIT`. This is deliberately stricter than the ledger view — a worker carrying twenty-two ledger hours whose night work and short rests push the projected score to twenty is rejected even though `HOURS_LEDGER` would have admitted them. The stored `fatigue_penalty_score` and `ledger_hours` always reflect only the worker's existing assignments and are recomputed after every assignment creation, completion, and cancellation.

Completing an assignment — a `ContractorSupervisor` action legal only while the turnaround is in `EXECUTION` — records the worked `actual_hours`, moves the assignment from `ASSIGNED` to `COMPLETED`, adds those hours into the worker's `total_shift_hours` (the running sum of `actual_hours` across the worker's `COMPLETED` assignments), and triggers the fatigue recomputation. Cancelling an `ASSIGNED` assignment — available to both `Planner` and `ContractorSupervisor`, and also fired by the system when a worker is debadged — moves it to `CANCELLED` and again recomputes the worker's fatigue fields, since the assignment has left the ledger's input set. An assignment's terminal states are `COMPLETED`, `NO_SHOW`, and `CANCELLED`.

### 3.4. Isolation Control and Permit-to-Work

Hazardous work is fenced twice: equipment isolations establish the physical barrier, and permits-to-work authorize the job against those barriers. A `PermitCoordinator` plans an isolation by naming the `equipment_tag` being isolated, an `isolation_mode` of `EXCLUSIVE` or `SHARED`, and the isolation window as `isolated_from` and `isolated_until`, where the end must be strictly later than the start. Isolation windows are closed intervals — both bounds are inclusive — and the conflict rule is mode-conditional: two `SHARED` isolations may coexist on the same `equipment_tag` even with overlapping windows, but any overlap involving an `EXCLUSIVE` isolation on the same tag is rejected with `ERR_ISOLATION_CONFLICT`; because the intervals are closed, windows that merely touch at an endpoint still count as overlapping. A new isolation is `PLANNED`, and its lifecycle runs `PLANNED`, `ISOLATED`, `VERIFIED`, and the terminal `DEISOLATED`.

Isolation transitions are driven by a `PermitCoordinator` carrying the desired target in the `to` field. Moving from `PLANNED` to `ISOLATED` and from `ISOLATED` to `VERIFIED` carry no further preconditions. De-isolation — from `ISOLATED` or from `VERIFIED` to `DEISOLATED` — is blocked while any permit whose `required_isolation_ids` contains this isolation stands in `ISSUED`, `ACTIVE`, or `SUSPENDED`; the attempt is rejected with `ERR_ISOLATION_IN_USE`. Clients can always enumerate the permits referencing an isolation to discover the blocker.

A `PermitCoordinator` requests a permit against a scoped work item by supplying the `permit_type` — `COLD_WORK`, `HOT_WORK`, or `CONFINED_SPACE` — a `hazard_class` of `LOW` or `HIGH`, the validity window as `valid_from` and `valid_until` with the end strictly after the start, and `required_isolation_ids`, the list of isolations that must underpin the permit, which may be empty. Every referenced isolation must belong to the same turnaround as the covered work item, recorded on the permit as `work_item_id`, or the request fails with `ERR_CROSS_SCOPE_REFERENCE`. A new permit is `REQUESTED`; its full status vocabulary is `REQUESTED`, `ISSUED`, `ACTIVE`, `SUSPENDED`, `CLOSED`, `REVOKED`, and `EXPIRED`.

Permit transitions are likewise driven through the `to` field by a `PermitCoordinator`, with several steps also fired by the system. Issuance — `REQUESTED` to `ISSUED` — requires every isolation in `required_isolation_ids` to stand in `ISOLATED` or `VERIFIED`, drawing `ERR_ISOLATION_NOT_VERIFIED` otherwise, and requires the logical now to fall strictly before `valid_until`, drawing `ERR_PERMIT_WINDOW_INVALID` otherwise. Activation — `ISSUED` to `ACTIVE`, or resumption from `SUSPENDED` to `ACTIVE` — tightens the isolation requirement to full `VERIFIED` status on every required isolation, requires the turnaround to be in `EXECUTION`, and requires the logical now to fall at or after `valid_from` and strictly before `valid_until` — the window is half-open at its end. Activation from `ISSUED` additionally refuses to energize finished work: a covered work item in `VERIFIED`, `CANCELLED`, or `COMPLETE` draws `ERR_INVALID_STATE`.

Suspension moves an `ACTIVE` permit to `SUSPENDED`, either at a coordinator's request or automatically when the covered work item is placed on hold. Closure moves an `ACTIVE` or `SUSPENDED` permit to `CLOSED`. Revocation moves an `ISSUED`, `ACTIVE`, or `SUSPENDED` permit to `REVOKED`; revoking an `ACTIVE` permit fires the first link of a cascade — the covered work item, if `IN_PROGRESS`, is forced `ON_HOLD`, and that hold in turn recomputes the turnaround's critical-path slip and cost forecast as described in §3.5. Expiry is the system's doing: the ops-run checkpoint expires every `ISSUED`, `ACTIVE`, or `SUSPENDED` permit whose `valid_until` has been reached — that is, at or before the logical now — moving it to `EXPIRED`, and an expired `ACTIVE` permit fires the same hold cascade as a revocation.

### 3.5. Field Execution: Scheduling, Starting, Holding, and Verifying Work

Once the turnaround reaches `MOBILIZATION` or `EXECUTION`, a `Planner` schedules each `FROZEN` work item, optionally naming a `planned_shift_id` to pin the item into a specific shift; the item moves from `FROZEN` to `SCHEDULED`. The collection of items scheduled into a shift is always enumerable from the shift's side.

Starting work is the field supervisor's action, and the same start action serves three source states: `SCHEDULED` to `IN_PROGRESS` for first mobilization of the job, `ON_HOLD` to `IN_PROGRESS` for resumption, and `REOPENED` to `IN_PROGRESS` for rework. Every start requires the turnaround to be in `EXECUTION`, failing with `ERR_INVALID_STATE` otherwise, and whenever the item's `requires_permit` flag is set, a permit covering this work item must currently stand in `ACTIVE` — the absence of one is rejected with `ERR_PERMIT_NOT_ACTIVE`. When a start lifts a critical-path item out of `ON_HOLD`, the turnaround's `critical_path_slip_hours` is recomputed to reflect the item leaving the held set.

A `ContractorSupervisor` may place an `IN_PROGRESS` item on hold. The hold cascades sideways: every permit covering the item that currently stands in `ACTIVE` is moved to `SUSPENDED`, while permits already `CLOSED`, `REVOKED`, or `EXPIRED` are untouched. If the held item is marked `is_critical_path`, the turnaround's `critical_path_slip_hours` — the sum of `remaining_hours` over all critical-path items currently sitting in `ON_HOLD`, recomputed on every transition of an item into or out of that set — is refreshed first, and the cost forecast is then recomputed off the new slip figure. The same recompute chain fires when the system itself forces the hold through the permit-revocation or permit-expiry cascade of §3.4.

Completion records reality: the supervisor supplies the item's `actual_hours`, the item moves from `IN_PROGRESS` to `COMPLETE`, and its `remaining_hours` is recomputed as the `estimated_hours` minus the recorded `actual_hours` — absent actuals counting as zero — but never below zero. Because a `COMPLETE` item has left the committed input set, the turnaround's `committed_cost_cents` is recomputed at completion.

Verification belongs to the `OperationsRep` and is a two-outcome judgment carried in the `outcome` field. An `outcome` of `VERIFIED` closes the item — `VERIFIED` is terminal. An `outcome` of `REOPENED` loops the item back for rework: it re-enters the committed input set, so `committed_cost_cents` is recomputed upward again, and the item may be started once more through the normal start path. A work item's full status vocabulary is `PROPOSED`, `FROZEN`, `DEFERRED`, `SCHEDULED`, `IN_PROGRESS`, `ON_HOLD`, `COMPLETE`, `REOPENED`, `VERIFIED`, and `CANCELLED`, with `VERIFIED` and `CANCELLED` terminal; the `CANCELLED` state is reached only through the turnaround-cancellation cascade of §3.9, which also recomputes `committed_cost_cents` when a `FROZEN` item is cancelled.

### 3.6. Discovery Work and Change Authorization

Mid-execution surprises are priced, not improvised. While the turnaround is in `EXECUTION`, a `ContractorSupervisor` or a `TurnaroundManager` reports discovery work, supplying a `description`, the contractor's `quoted_cost_cents` — strictly positive — and `quoted_hours` — strictly positive — and optionally the `origin_work_item_id` of the work item where the discovery surfaced. The new discovery is `REPORTED` with `appeal_count` zero, and the reporter's `X-User-ID` is recorded as `reported_by_user_id`, anchoring segregation of duties for everything that follows. Reporting alone moves money: the quote enters the forecast's pending set and the turnaround's cost forecast is recomputed immediately.

A `TurnaroundManager` then triages the discovery, optionally attaching a `triage_note`, moving it from `REPORTED` to `TRIAGED`. The decision step is where segregation of duties bites: the decider's `X-User-ID` must differ from the recorded `reported_by_user_id`, and a match is rejected with `ERR_SOD_VIOLATION`. The decision itself is carried in the `outcome` field.

An `outcome` of `AUTHORIZED` requires `authorized_cost_cents` to be present and strictly positive — its absence or a non-positive value draws `ERR_INVALID_REQUEST` — and the authorized amount must not exceed the turnaround's `contingency_remaining_cents`, defined as the `contingency_budget_cents` minus the sum of `authorized_cost_cents` across all discoveries already standing in `AUTHORIZED`; an overdraw is rejected with `ERR_CONTINGENCY_EXCEEDED`. Authorization fires a two-link cascade. First, an addendum work item is created on the same turnaround with `work_type` of `DISCOVERY_ADDENDUM`, `risk_class` of `C`, `requires_permit` false, `status` of `FROZEN`, `estimated_cost_cents` equal to the authorized amount, `estimated_hours` equal to the discovery's `quoted_hours`, and a `discovery_id` back-reference to the discovery that spawned it; the turnaround's `committed_cost_cents` is then recomputed with the addendum's estimate included. Second, the cost forecast is recomputed and the turnaround's `cost_posture` flips per its own machine. The decision records `authorized_by_user_id` and the authorized amount, and the cascade increments both the discovery's `version` and the turnaround's `version` by one. `AUTHORIZED` is terminal.

An `outcome` of `REJECTED` removes the quote from the forecast's pending set and recomputes the forecast — which can itself relax the turnaround's `cost_posture`. Rejection is not necessarily final: while `appeal_count` remains below two, a `ContractorSupervisor` or `TurnaroundManager` may appeal, moving the discovery back from `REJECTED` to `TRIAGED`, incrementing `appeal_count` by one, and returning the quote to the pending set with a fresh forecast recompute. Once `appeal_count` has reached two, further appeals are rejected with `ERR_APPEAL_LIMIT`.

### 3.7. Materials Staging and Lay-Down Areas

A `TurnaroundManager` establishes staging capacity by creating lay-down areas, each with a `name` and a strictly positive `capacity_sqm`. A new area stands `OPEN` — the area status vocabulary is simply `OPEN` and `CLOSED` — with `occupied_sqm` at zero. Occupancy is an aggregate figure: an area's `occupied_sqm` is always the sum of `area_sqm` over its reservations standing in `RESERVED` or `STAGED`.

Reserving space is a shared capability of `ContractorSupervisor` and `Planner`. The request describes the `material_description`, claims a strictly positive `area_sqm`, and gives the staging window as `window_from` and `window_until` with the end strictly after the start. Because the client sized the request against the free space it last observed, the write is OCC-guarded per §2.7: the request must carry `expected_laydown_area_version` matching the area's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`. Capacity is enforced with aggregate semantics — staging windows may overlap freely because the space is shared — and the sole check is that the area's current `occupied_sqm` plus the candidate `area_sqm` does not exceed `capacity_sqm`; exact equality is admitted, and any excess is rejected with `ERR_LAYDOWN_CAPACITY_EXCEEDED`. A successful reservation is created `RESERVED`, the area's `occupied_sqm` rises by `area_sqm`, and the area's `version` increments by one, recorded on each reservation as `laydown_area_id`.

A reservation's lifecycle runs from `RESERVED` through `STAGED` and ends at `RELEASED` or `CANCELLED`. When material physically arrives, a `ContractorSupervisor` stages the reservation, moving `RESERVED` to `STAGED` — occupancy does not change, since the space was already committed. Releasing is the compensating action and takes two forms depending on where the reservation stands: releasing a `STAGED` reservation moves it to `RELEASED`, while releasing a still-`RESERVED` one moves it to `CANCELLED`; both subtract the reservation's `area_sqm` from the area's `occupied_sqm` and increment the area's `version`. The ops-run checkpoint of §3.8 also sweeps staging: any reservation still `RESERVED` or `STAGED` whose `window_until` has been reached — at or before the logical now — is automatically moved to `RELEASED` with the same occupancy decrement.

### 3.8. Daily Cost Reporting, the Cost Forecast, and the Ops-Run Checkpoint

Each contractor accounts for its labor daily. A `ContractorSupervisor` drafts a report by supplying the `report_date` — which must not fall after the current logical date, else `ERR_INVALID_REQUEST` — and a non-empty `lines` array, each line naming a `worker_id`, a `shift_id`, the worked `hours`, and a `hazard_flag`. The report's `contractor_id` is taken from the submitter's `X-User-ID`, every line's shift must belong to the same turnaround and every line's worker must be employed by the submitting contractor — violations draw `ERR_CROSS_SCOPE_REFERENCE` — and every line worker must currently hold a `BADGED` badge, else `ERR_BADGE_NOT_CLEARED`. One report per contractor per date is the rule: while a non-`VOIDED` report already exists for the same turnaround, contractor, and `report_date`, a further draft is rejected with `ERR_DUPLICATE_REPORT`. A drafted report stands in `DRAFT`, and its computed fields — `line_costs_cents`, `labor_cost_cents`, `overhead_cents`, and `total_cost_cents` — remain null until submission.

Submission is restricted to the supervisor whose `X-User-ID` equals the report's `contractor_id`, failing with `ERR_FORBIDDEN` otherwise, and it prices the report line by line. For each line, the first eight hours are regular hours; the next four — hours beyond eight, up to a further four — form the first overtime tier; and any hours beyond twelve form the second tier, so a line of exactly twelve hours contributes nothing at all to the second tier. The line's base price is its regular hours times the base rate of 8500 cents per hour, plus its first-tier hours times the base rate times one and a half, plus its second-tier hours times the base rate times two. If the line's shift is a `NIGHT` shift the whole base is then multiplied by 1.20, and if the line's `hazard_flag` is set the result is further multiplied by 1.15. Only now is the line rounded — half-up to a whole cent, exactly once — and only after rounding is the per-line cap of 250000 cents applied, so the cap can never interact with fractional cents. The resulting `line_costs_cents` array preserves the input order of `lines`.

The report's `labor_cost_cents` is then the sum of those already-rounded per-line costs. This order is pinned: rounding each line first and summing second is the only legal evaluation. Consider two lines of one-tenth of an hour each, both hazard-flagged on day shifts: each raw line value is 977.5 cents, per-line rounding yields 978 plus 978 for a total of 1956 cents, whereas summing first and rounding once would illegally yield 1955. Overhead follows with its own pinned order, resolving what looks like a circular dependency. First the system takes the turnaround's `reported_cost_cents` excluding this candidate report — that is, the sum of `total_cost_cents` over the turnaround's other `APPROVED` reports only. If that base is below 200000 cents the report falls in the low tier and its `overhead_cents` is its `labor_cost_cents` multiplied by ten percent; at or above that threshold the high tier applies fifteen percent. The product is rounded half-up to whole cents. Only then is `total_cost_cents` computed as `labor_cost_cents` plus `overhead_cents`. Keying the tier on a total that would include this very report is forbidden; the base must be settled before the percentage is applied. Submission records `submitted_by_user_id` and moves the report from `DRAFT` to `SUBMITTED`.

Approval belongs to the `CostController`, and segregation of duties applies again: the approver's `X-User-ID` must differ from the recorded `submitted_by_user_id`, else `ERR_SOD_VIOLATION`. Approval posts to the ledger — the turnaround's `reported_cost_cents` rises by the report's `total_cost_cents`, the cost forecast and posture are recomputed, `approved_by_user_id` is recorded, and both the report's and the turnaround's `version` increment. A `CostController` may instead reject a `SUBMITTED` report, optionally with a `reason`, returning it to `DRAFT` with no ledger effect; the computed cost fields are retained so the supervisor can review them before resubmission. Voiding is the compensation for an approved posting: a `CostController` may void an `APPROVED` report only when no `APPROVED` report with a later `report_date` exists for the same turnaround and contractor — out-of-order voids are rejected with `ERR_REPORT_SEQUENCE` — and a void subtracts the report's `total_cost_cents` from `reported_cost_cents`, recomputes the forecast, and increments both versions. A report's terminal states are `APPROVED` and `VOIDED`.

The turnaround's cost forecast — the estimate at completion — is maintained continuously and read through a dedicated summary that exposes `committed_cost_cents`, `reported_cost_cents`, `forecast_committed_cents`, `forecast_provisional_cents`, `contingency_remaining_cents`, and `cost_posture`. The committed figure is the sum of `estimated_cost_cents` over the turnaround's work items standing in `FROZEN`, `SCHEDULED`, `IN_PROGRESS`, `ON_HOLD`, or `REOPENED`. The pending-quote figure is the sum of `quoted_cost_cents` over discoveries standing in `REPORTED` or `TRIAGED`. The schedule-overrun figure prices critical-path slip: the whole number of eight-hour slip days contained in `critical_path_slip_hours` — fractional days are discarded by floor division — multiplied by a daily overhead of 50000 cents. The forecast then comes in two variants with a pinned evaluation order. The committed variant, `forecast_committed_cents`, is simply the committed figure and excludes both pending quotes and schedule overrun; it feeds the `OVERRUN` leg of the posture machine. The provisional variant, `forecast_provisional_cents`, is the committed figure plus the pending quotes plus the schedule overrun — it diverges from the committed variant by exactly those two terms — and feeds the `AT_RISK` leg. Posture is decided only after both variants are settled: `cost_posture` is `OVERRUN` when `committed_cost_cents` exceeds `authorized_budget_cents`, otherwise `AT_RISK` when `forecast_provisional_cents` exceeds `authorized_budget_cents`, otherwise `WITHIN_BUDGET`.

The forecast is recomputed at every event that can move an input: scope freeze, any work-item transition into or out of the committed set, discovery reporting, triage, decision, and appeal, daily-report approval and void, and every `critical_path_slip_hours` recomputation. Posture therefore moves in both directions along its machine — `WITHIN_BUDGET` to `AT_RISK` when the provisional figure crosses the budget while commitments still fit, straight to `OVERRUN` when commitments themselves cross it, `AT_RISK` to `WITHIN_BUDGET` when, say, a rejected discovery's quote leaves the pending set, `OVERRUN` back to `AT_RISK` when commitments return under budget while the provisional figure still exceeds it, and `OVERRUN` all the way back to `WITHIN_BUDGET` when both figures are once again within the authorized budget.

The ops-run checkpoint is a `TurnaroundManager` capability that advances the operational world to the logical now in one sweep. It expires every permit standing in `ISSUED`, `ACTIVE`, or `SUSPENDED` whose `valid_until` has been reached, with the hold cascade of §3.4 firing for any `ACTIVE` permit so caught; it auto-releases every reservation still `RESERVED` or `STAGED` whose `window_until` has been reached, with the occupancy decrement of §3.7; and it increments the turnaround's `schedule_run_index` — the monotone counter of ops runs that started at zero — while bumping the turnaround's `version`.

### 3.9. Phase Advancement, Startup Gating, Punch List, and Handover

Between the bookends of freeze and handover, the turnaround advances one phase at a time under the `TurnaroundManager`'s hand, each advance incrementing the turnaround's `version`. Moving from `SCOPE_FROZEN` to `MOBILIZATION` carries no gate. Moving from `MOBILIZATION` to `EXECUTION` requires at least one contractor standing in `MOBILIZED`; without one the advance is rejected with `ERR_NO_MOBILIZED_CONTRACTOR`. Moving from `EXECUTION` to `STARTUP` enforces three gates, evaluated in order so that the earliest failure is the one reported: first, every scope work item — any item not `DEFERRED` or `CANCELLED` — must stand in `VERIFIED`, failing with `ERR_WORK_ITEMS_OPEN`; second, no permit may remain in `REQUESTED`, `ISSUED`, `ACTIVE`, or `SUSPENDED`, failing with `ERR_PERMITS_STILL_ACTIVE`; third, no isolation may remain in `PLANNED`, `ISOLATED`, or `VERIFIED`, failing with `ERR_ISOLATIONS_ENGAGED`. Cancellation runs the other direction: from `PLANNING` or `SCOPE_FROZEN` the `TurnaroundManager` may cancel the turnaround outright, which cancels every work item standing in `PROPOSED` or `FROZEN` — recomputing `committed_cost_cents` as the frozen items leave the committed set — while `DEFERRED` items are left untouched; cancellation from any later phase is rejected with `ERR_INVALID_STATE`.

As execution winds down, deficiencies are tracked on the punch list. An `OperationsRep` or `ContractorSupervisor` raises a punch item against a work item — named in the payload as `work_item_id` — that stands in `COMPLETE` or `VERIFIED`, while the turnaround is in `EXECUTION` or `STARTUP`, supplying a `category` of `A` or `B` and a `description`; the item opens in `OPEN`. Category semantics matter at the gate: category-`A` items must be fully verified before handover, while category-`B` items may carry over into operations. The contractor side marks remedied items ready — both `OPEN` and `REOPENED` items move to `READY` — and the `OperationsRep` then judges each `READY` item through the `outcome` field: `VERIFIED` closes the item terminally, while `REOPENED` loops it back for another round of remedy. A punch item's vocabulary is `OPEN`, `READY`, `VERIFIED`, and `REOPENED`, with `VERIFIED` terminal.

Handover is the final act. From `STARTUP`, the `TurnaroundManager` hands the plant back to operations with a payload whose `operations_acknowledged` flag must be present and true — a missing or false flag is rejected with `ERR_INVALID_REQUEST`. The gate is precise: the count of punch items with `category` of `A` standing in `OPEN`, `READY`, or `REOPENED` must be exactly zero, and any such straggler blocks the handover with `ERR_OPEN_PUNCH_ITEMS`; category-`B` items impose no constraint. A successful handover moves the turnaround to `HANDED_OVER`, stamps `handed_over_at`, and increments the turnaround's `version` one final time.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource in place — state transitions, estimates, submits, approvals, and the like — return `200 OK`. Retrieval endpoints return `200 OK`. The table below is deliberately minimal: request payloads, response shapes, side effects, and preconditions are all specified by the narratives of §2 and §3, and the state-pair and role framings there map one-to-one onto the rows here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/turnarounds` | Create a turnaround | TurnaroundManager |
| GET | `/turnarounds/{id}` | Get a turnaround | Any |
| POST | `/turnarounds/{id}/freeze-scope` | Freeze scope: rank `PROPOSED` items, freeze up to the inclusive cutoff, defer the rest | TurnaroundManager |
| POST | `/turnarounds/{id}/advance` | Advance the turnaround one phase per its state machine | TurnaroundManager |
| POST | `/turnarounds/{id}/cancel` | Cancel a turnaround from `PLANNING` or `SCOPE_FROZEN` | TurnaroundManager |
| POST | `/turnarounds/{id}/handover` | Hand over to operations; requires zero open category-`A` punch items | TurnaroundManager |
| GET | `/turnarounds/{id}/cost-summary` | Computed cost read: both forecast variants, posture, contingency remaining | TurnaroundManager, Planner, CostController |
| POST | `/turnarounds/{id}/run-ops` | Ops-run checkpoint: expire permits, auto-release stale reservations, bump the run index | TurnaroundManager |
| POST | `/turnarounds/{id}/work-items` | Propose a work item while the turnaround is `PLANNING` | Planner |
| GET | `/turnarounds/{id}/work-items` | List a turnaround's work items; filterable by `status`, `work_type`, `is_critical_path` | Any |
| GET | `/work-items/{id}` | Get a work item | Any |
| POST | `/work-items/{id}/estimate` | Re-estimate a `PROPOSED` work item; OCC-guarded | Planner |
| POST | `/work-items/{id}/dependencies` | Add a predecessor edge onto this work item; cycle-safe | Planner |
| GET | `/work-items/{id}/dependencies` | List dependency edges where this item is predecessor or successor | Any |
| GET | `/turnarounds/{id}/dependencies` | List all dependency edges of a turnaround's work-item graph | Any |
| POST | `/work-items/{id}/schedule` | Schedule a `FROZEN` work item, optionally into a shift | Planner |
| POST | `/work-items/{id}/start` | Start or resume work (`SCHEDULED`, `ON_HOLD`, or `REOPENED` to `IN_PROGRESS`) | ContractorSupervisor |
| POST | `/work-items/{id}/hold` | Place an `IN_PROGRESS` item on hold; its `ACTIVE` permits auto-suspend | ContractorSupervisor |
| POST | `/work-items/{id}/complete` | Complete an `IN_PROGRESS` item, recording actual hours | ContractorSupervisor |
| POST | `/work-items/{id}/verify` | Verify completed work to `VERIFIED`, or reopen it for rework | OperationsRep |
| GET | `/work-items/{id}/permits` | List permits covering a work item | Any |
| GET | `/work-items/{id}/discoveries` | List discoveries whose origin is this work item | Any |
| GET | `/work-items/{id}/punch-items` | List punch items raised on this work item | Any |
| POST | `/turnarounds/{id}/contractors` | Invite a contractor once the scope is frozen or later | TurnaroundManager |
| GET | `/turnarounds/{id}/contractors` | List a turnaround's contractors | Any |
| GET | `/contractors/{id}` | Get a contractor | Any |
| POST | `/contractors/{id}/mobilize` | Advance mobilization one step; the acting supervisor must own the contractor | ContractorSupervisor |
| POST | `/contractors/{id}/workers` | Register a worker under the supervisor's own contractor | ContractorSupervisor |
| GET | `/contractors/{id}/workers` | List a contractor's workers; filterable by `badge_status` | Any |
| GET | `/contractors/{id}/daily-reports` | List daily reports filed by a contractor; filterable by `status` | Any |
| GET | `/workers/{id}` | Get a worker | Any |
| POST | `/workers/{id}/vet` | Vet a `REGISTERED` worker | PermitCoordinator |
| POST | `/workers/{id}/badge` | Badge a `VETTED` worker; headcount cap enforced | PermitCoordinator |
| POST | `/workers/{id}/badge-transition` | Suspend, reinstate, or debadge a worker; debadging cancels pending assignments | PermitCoordinator |
| GET | `/workers/{id}/assignments` | List a worker's shift assignments | Any |
| POST | `/turnarounds/{id}/shifts` | Plan a shift | Planner |
| GET | `/turnarounds/{id}/shifts` | List a turnaround's shifts; filterable by `shift_type`, `status` | Any |
| GET | `/shifts/{id}` | Get a shift | Any |
| GET | `/shifts/{id}/work-items` | List work items scheduled into this shift | Any |
| POST | `/shifts/{id}/lock` | Lock a `PLANNED` shift that has at least one assignment | Planner |
| POST | `/shifts/{id}/assignments` | Assign a worker to a `PLANNED` shift; badge, fatigue, overlap, rest, and headcount gates | Planner, ContractorSupervisor |
| GET | `/shifts/{id}/assignments` | List a shift's assignments | Any |
| POST | `/assignments/{id}/complete` | Complete an `ASSIGNED` assignment with actual hours | ContractorSupervisor |
| POST | `/assignments/{id}/cancel` | Cancel an `ASSIGNED` assignment | Planner, ContractorSupervisor |
| POST | `/turnarounds/{id}/isolations` | Plan an equipment isolation; closed-interval, mode-conditional conflict check | PermitCoordinator |
| GET | `/turnarounds/{id}/isolations` | List a turnaround's isolations; filterable by `equipment_tag`, `status` | Any |
| GET | `/isolations/{id}` | Get an isolation | Any |
| POST | `/isolations/{id}/transition` | Move an isolation along its machine; de-isolation blocked by live permits | PermitCoordinator |
| GET | `/isolations/{id}/permits` | List permits whose required isolations include this one | Any |
| POST | `/work-items/{id}/permits` | Request a permit-to-work covering a scoped work item | PermitCoordinator |
| GET | `/permits/{id}` | Get a permit | Any |
| POST | `/permits/{id}/transition` | Move a permit along its machine; revocation cascades a hold onto in-progress work | PermitCoordinator |
| POST | `/turnarounds/{id}/discoveries` | Report discovery work while in `EXECUTION`; reporter identity recorded | ContractorSupervisor, TurnaroundManager |
| GET | `/turnarounds/{id}/discoveries` | List a turnaround's discoveries; filterable by `status` | Any |
| GET | `/discoveries/{id}` | Get a discovery | Any |
| GET | `/discoveries/{id}/work-items` | List addendum work items created from this discovery | Any |
| POST | `/discoveries/{id}/triage` | Triage a `REPORTED` discovery | TurnaroundManager |
| POST | `/discoveries/{id}/decide` | Authorize against contingency or reject a `TRIAGED` discovery; segregation of duties enforced | TurnaroundManager |
| POST | `/discoveries/{id}/appeal` | Appeal a `REJECTED` discovery back to `TRIAGED`; at most two appeals | ContractorSupervisor, TurnaroundManager |
| POST | `/turnarounds/{id}/laydown-areas` | Create a lay-down area | TurnaroundManager |
| GET | `/turnarounds/{id}/laydown-areas` | List a turnaround's lay-down areas | Any |
| GET | `/laydown-areas/{id}` | Get a lay-down area | Any |
| POST | `/laydown-areas/{id}/reservations` | Reserve staging space; OCC on the area version, aggregate capacity check | ContractorSupervisor, Planner |
| GET | `/laydown-areas/{id}/reservations` | List an area's reservations; filterable by `status` | Any |
| POST | `/reservations/{id}/stage` | Mark reserved material physically staged | ContractorSupervisor |
| POST | `/reservations/{id}/release` | Release staging space (`RESERVED` to `CANCELLED`, `STAGED` to `RELEASED`) | ContractorSupervisor |
| POST | `/turnarounds/{id}/daily-reports` | Draft a daily labor report; one per contractor per date | ContractorSupervisor |
| GET | `/turnarounds/{id}/daily-reports` | List a turnaround's daily reports; filterable by `status`, `contractor_id` | Any |
| GET | `/daily-reports/{id}` | Get a daily report | Any |
| POST | `/daily-reports/{id}/submit` | Submit a `DRAFT` report; computes per-line costs, labor total, overhead, grand total | ContractorSupervisor |
| POST | `/daily-reports/{id}/approve` | Approve a `SUBMITTED` report; approver differs from submitter; posts to the cost ledger | CostController |
| POST | `/daily-reports/{id}/reject` | Reject a `SUBMITTED` report back to `DRAFT` with no ledger effect | CostController |
| POST | `/daily-reports/{id}/void` | Void the latest `APPROVED` report for its contractor; compensates the ledger posting | CostController |
| POST | `/turnarounds/{id}/punch-items` | Raise a punch item on a `COMPLETE` or `VERIFIED` work item | OperationsRep, ContractorSupervisor |
| GET | `/turnarounds/{id}/punch-items` | List a turnaround's punch items; filterable by `category`, `status` | Any |
| GET | `/punch-items/{id}` | Get a punch item | Any |
| POST | `/punch-items/{id}/ready` | Mark an `OPEN` or `REOPENED` punch item ready for verification | ContractorSupervisor |
| POST | `/punch-items/{id}/verify` | Verify (close) or reopen a `READY` punch item | OperationsRep |
| POST | `/_clock/set_current_utc` | Set the logical clock; permit windows, ops-run expiry, and report dating read it | TurnaroundManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_SCOPE_REFERENCE` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_BADGE_NOT_CLEARED` | 409 |
| `ERR_FATIGUE_LIMIT` | 409 |
| `ERR_PERMIT_NOT_ACTIVE` | 409 |
| `ERR_ISOLATION_NOT_VERIFIED` | 409 |
| `ERR_PERMIT_WINDOW_INVALID` | 409 |
| `ERR_ISOLATION_CONFLICT` | 409 |
| `ERR_ISOLATION_IN_USE` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_REST_PERIOD_VIOLATION` | 409 |
| `ERR_SHIFT_LOCKED` | 409 |
| `ERR_SHIFT_HEADCOUNT_FULL` | 409 |
| `ERR_EMPTY_SHIFT` | 409 |
| `ERR_CONTRACTOR_HEADCOUNT_CAP` | 409 |
| `ERR_NO_BADGED_WORKERS` | 409 |
| `ERR_NO_MOBILIZED_CONTRACTOR` | 409 |
| `ERR_WORK_ITEMS_OPEN` | 409 |
| `ERR_PERMITS_STILL_ACTIVE` | 409 |
| `ERR_ISOLATIONS_ENGAGED` | 409 |
| `ERR_OPEN_PUNCH_ITEMS` | 409 |
| `ERR_DEPENDENCY_CYCLE` | 409 |
| `ERR_CONTINGENCY_EXCEEDED` | 409 |
| `ERR_APPEAL_LIMIT` | 409 |
| `ERR_LAYDOWN_CAPACITY_EXCEEDED` | 409 |
| `ERR_DUPLICATE_REPORT` | 409 |
| `ERR_REPORT_SEQUENCE` | 409 |
