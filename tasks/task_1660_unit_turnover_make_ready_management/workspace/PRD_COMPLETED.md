# Unit Turnover & Make-Ready Management API — Product Requirements Document

## 1. Introduction

Every day an apartment sits vacant between residents is a day of lost rent, and the work required to return a unit to a leasable condition — cleaning, painting, repairs, carpet, appliance and fixture decisions — is a small construction project with real budget, schedule, and quality risks. Operations teams juggle vendor calendars, scope creep after the initial walk-through, repair-versus-replace economics on aging assets, and pre-leasing promises made to applicants before the work is finished. When any one of these slips, the delivery commitment made to the next resident is the first thing to break.

This document specifies the Unit Turnover & Make-Ready Management API, the system of record for that entire lifecycle. It governs how a vacancy notice opens a **turn** on a unit, how the turn's scope of work is planned, budgeted, and locked, how vendors are scheduled under calendar and sequencing constraints, how post-approval scope creep is tiered and escalated through a management approval chain, how quality inspections drive a rework loop, how repair-versus-replace decisions classify spending as operating expense or capital, and how pre-lease delivery commitments are tracked against a living projection of the ready date. All endpoints are mounted under the `/make-ready` path prefix. All date-stamping in the system reads from a controllable logical clock rather than wall-clock time, so that every projection and commitment evaluation is deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly six roles: `RegionalManager`, `PropertyManager`, `TurnCoordinator`, `Vendor`, `Inspector`, and `PlatformAdmin`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor` entity; ownership checks on any vendor assignment compare the assignment's `vendor_id` field against `X-User-ID`, and a mismatch is rejected with `ERR_VENDOR_NOT_ASSIGNED`. When `X-User-Role` is `RegionalManager`, `PropertyManager`, `TurnCoordinator`, `Inspector`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

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
- A request that matches no defined route — or a defined route under the wrong method — is rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope.

### 2.3. Pagination

List endpoints are paginated through query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Values outside the declared bounds are clamped to the nearest bound rather than rejected, a `limit` or `offset` that does not parse as an integer falls back to its default, and unrecognized query parameters are ignored. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource — Property, Unit, Turn, ScopeItem, Vendor, VendorAssignment, and LeaseCommitment — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed whenever the resource's properties change.
- `version` (integer): a system-managed counter that starts at 1 when the resource is created and increments with every modification to the resource, used for optimistic concurrency control. The workflow rules in §3 identify each point where a turn's `version` advances.

Two resources are exceptions to this pattern. An **Inspection** and a **ReplacementDecision** are immutable records of a one-time event: each carries only `id` and `created_at`, and both `updated_at` and `version` are absent from them entirely.

### 2.5. The Logical Clock

Every business date the system stamps or computes — the day a scope is finalized, the day an inspection passes, every projected and target ready date, and every calendar comparison the workflows evaluate — reads from a logical clock, never from wall-clock time. The bookkeeping timestamps `created_at` and `updated_at` on resources, like the envelope's `api_request_timestamp`, are operational metadata taken from wall-clock time and carry no workflow meaning. At startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time on its own. A `PlatformAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant. Setting the clock is a system-wide event: it re-triggers recomputation of `projected_ready_date` for every turn in `SCOPED`, `IN_PROGRESS`, or `REWORK` status, and every resulting change re-evaluates the at-risk status of lease commitments as described in §3.8.

### 2.6. Money, Basis Points, and Rounding Discipline

All monetary amounts in the system — estimates, actuals, budgets, rollups, thresholds — are integers denominated in cents; no floating-point money exists anywhere in the API. Variance between a turn's evolving estimate and its locked budget is expressed in basis points. Wherever a calculation produces a fraction, it is rounded half up: per-item overhead allocations are rounded half up to whole cents before any summation, the scope-creep variance is rounded half up to a whole basis point, property benchmark averages are rounded half up to whole integers, and the repair-affordability ceiling under the percentage-of-replacement policy is rounded half up to whole cents. Calendar arithmetic — target dates, projections, assignment windows, commitment promises — is performed in whole ISO dates. Unless a rule in §3 expressly declares a minimum, integer fields accept any whole-number value, including zero and negative amounts.

### 2.7. The Two Views of Turn Spend

Every turn maintains a partitioned view of its booked costs. `expense_actual_cents` accumulates the `actual_cost_cents` of the turn's scope items whose status is `COMPLETED` or `FAILED` and whose `classification` is `EXPENSE`; `capital_actual_cents` accumulates the same over items classified `CAPITAL`. `total_actual_cents` is always exactly the sum of the two — a partition invariant guaranteeing that every booked cent lands in precisely one bucket, no cent counted twice and none dropped. Budget control, scope-creep evaluation, and the property benchmark all operate on the operating view (`expense_actual_cents` and its overhead-loaded derivative `booked_expense_cents`); the all-in cash view (`total_actual_cents`) exists for total spend reporting, and identical item histories yield a different number for the two views whenever any `CAPITAL`-classified item exists on the turn. A replacement decision that reclassifies an already-completed or already-failed item re-partitions these views accordingly.

### 2.8. Validation Order and Error Precedence

Every request is evaluated against a fixed, ordered validation chain, and the first failing check determines the error returned — later checks are never reached once an earlier one fails. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the six declared roles; failure yields `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization** — the declared role appears in the endpoint's permitted role list; failure yields `ERR_UNAUTHORIZED` (HTTP 403).
3. **Request shape** — required fields are present, types are valid, enum values are within their declared domains, unknown fields are rejected, an assignment's `end_date` falls after its `start_date`, a turn's `move_out_date` falls on or after its `notice_date`, and an inspection's `failed_scope_item_ids` is present and non-empty exactly when `result` is `FAIL` and absent or empty exactly when `result` is `PASS`; failure yields `ERR_INVALID_REQUEST` (HTTP 400).
4. **Existence** — path identifiers exist, validated left to right, and body foreign-key identifiers (`unit_id`, `turn_id`, `scope_item_id`, `vendor_id`, `property_id`) refer to existing resources; failure yields `ERR_NOT_FOUND` (HTTP 404).
5. **Vendor ownership** — on the vendor action endpoints (accept, decline, complete), `X-User-ID` must equal the assignment's `vendor_id`; failure yields `ERR_VENDOR_NOT_ASSIGNED` (HTTP 403).
6. **State validity** — the target resource is in a valid state for the requested operation: the turn's status for item adds, finalize, close, cancel, inspections, and commitments; the item's status for approve, reject, void, and decisions; the assignment's status for accept, decline, and complete; the unit's status for move-in; and the requirement that inspection-failed items are `COMPLETED`. The generic failure is `ERR_INVALID_STATE` (HTTP 409), with one specialization: opening a turn on a unit that is not `OCCUPIED` yields `ERR_UNIT_NOT_OCCUPIED` (HTTP 409).
7. **Stale version** — on scope-item approval only, the optimistic-concurrency check of §2.9, evaluated after the state preconditions and before any business rule; failure yields `ERR_STALE_VERSION` (HTTP 412).
8. **Business referential rules** — vendor trade matching on assignment creation, replacement-decision applicability and uniqueness on decision creation, and lease-commitment uniqueness on commitment creation; failures yield `ERR_VENDOR_TRADE_MISMATCH`, `ERR_DECISION_NOT_APPLICABLE`, `ERR_DECISION_ALREADY_EXISTS`, or `ERR_COMMITMENT_EXISTS` (all HTTP 422).
9. **Business temporal rules** — vendor calendar overlap, same-turn unit-window overlap, the paint-to-carpet cure buffer on assignment creation, and the delivery-date floor on commitment creation; failures yield `ERR_VENDOR_OVERLAP`, `ERR_UNIT_WINDOW_OVERLAP`, `ERR_CURE_BUFFER_VIOLATION`, or `ERR_DELIVERY_BEFORE_PROJECTED` (all HTTP 422).
10. **Business constraint rules** — category sequencing on assignment creation, the at-least-one-planned-item requirement on scope finalization, and repair economics on decision creation; failures yield `ERR_SEQUENCE_VIOLATION`, `ERR_NO_SCOPE_ITEMS`, or `ERR_UNECONOMICAL_REPAIR` (all HTTP 422).
11. **Approval authority** — on scope-item approval and rejection, the acting manager's tier authority; failure yields `ERR_APPROVAL_AUTHORITY_EXCEEDED` (HTTP 403).

Because the chain is ordered, a single request that would violate several rules always surfaces the earliest one — for example, an approval attempt on an item that is not `PENDING_APPROVAL` reports `ERR_INVALID_STATE` rather than any staleness or authority problem, and a stale-version problem surfaces before any authority problem.

### 2.9. Turn Versioning and Optimistic Concurrency Control

One write operation in the API is guarded by optimistic concurrency control: approving a pending scope item (`POST /make-ready/scope-items/{id}/approve`). The request must carry `expected_turn_version`, holding the `version` of the owning turn as the client last observed it. If the value does not match the turn's current `version` — because another writer has advanced the turn since the client last read it, for instance by approving a different pending item and thereby raising `approved_budget_cents` and re-tiering future scope adds — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from amending a budget baseline it has not observed. No other endpoint accepts a version field.

### 2.10. Nested Paths and Foreign-Key Existence

For any request whose path contains resource identifiers — including nested paths such as the inspections and replacement decisions recorded under a turn, or the lease commitments listed under a unit — the server validates each identifier's existence sequentially from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. Foreign-key identifiers supplied in request bodies (`unit_id` on turns and lease commitments, `turn_id` on scope items, `scope_item_id` on assignments and replacement decisions, `vendor_id` on assignments, `property_id` on units) receive the same treatment after the path is validated.

### 2.11. Derived Rollups and Cascading Reconciliation

Computed fields are never accepted from clients; they are maintained by the server and reconciled immediately as events occur. A turn's rollups — `estimated_cost_cents`, `expense_actual_cents`, `capital_actual_cents`, `total_actual_cents`, `booked_expense_cents`, and the forward-looking `projected_ready_date` — are re-derived from the turn's scope items and vendor assignments whenever those inputs change. Cascades flow strictly outward from the triggering event: a turn cancellation resolves its scope items, which in turn resolve their vendor assignments, and separately cancels the unit's open lease commitments and returns the unit to an occupiable state; a failed inspection rewrites item states, spawns rework items, refreshes every cost view, and re-projects the ready date. Whenever a recomputed projection crosses a lease commitment's promised date, the commitment's risk status flips without any client action on the commitment itself. Each state transition that §3 marks as advancing the turn also increments the turn's `version` by exactly one and refreshes its `updated_at`.

## 3. Business Logic & Workflows

### 3.1. Portfolio Setup: Properties, Units, and Vendors

A `RegionalManager` onboards a property by supplying its `name` together with the four policy numbers that will govern every turn on that property: `days_to_ready_target`, the calendar-day goal from scope finalization to ready; `pm_threshold_bp`, the scope-creep variance in basis points at or below which post-finalization additions auto-approve; `rm_threshold_bp`, the variance above which only regional authority suffices; and `capital_threshold_cents`, the replacement-cost level at or above which a replacement decision classifies as capital. The `rm_threshold_bp` must be greater than or equal to `pm_threshold_bp`; a property creation that inverts them is rejected with `ERR_INVALID_REQUEST`. The property also declares its `replacement_policy`, exactly one of `PERCENT_OF_REPLACE` or `COST_PER_YEAR`, which selects the repair-economics variant applied to every future replacement decision (§3.6). A new property's benchmark aggregates — `benchmark_turn_count`, `avg_booked_expense_cents`, and `avg_days_to_ready` — all initialize to zero and stay zero until the property's first turn closes (§3.9).

Units are created by a `PropertyManager` with a `property_id` placing them under an existing property, a `unit_number` label, and `square_feet`. A unit is born `OCCUPIED`, and its `status` thereafter cycles through `NOTICE` when a vacancy notice is recorded, `IN_TURN` while work proceeds, `READY` when the turn passes inspection, and back to `OCCUPIED` when the next resident moves in — a loop with no terminal state. Units can be listed with optional `property_id` and `status` filters, and fetched individually.

A `PropertyManager` also registers vendors, each with a `name` and a `trade` of `REPAIR`, `PAINT`, `CARPET`, or `CLEAN`. Trade discipline is enforced at scheduling time: a scope item in category `REPAIR`, `PAINT`, `CARPET`, or `CLEAN` accepts only a vendor of exactly that trade, while items in category `APPLIANCE`, `FIXTURE`, or `OTHER` are handled by `REPAIR`-trade vendors; any other pairing is rejected with `ERR_VENDOR_TRADE_MISMATCH`. Each vendor carries `open_assignment_count`, the count of its assignments currently in `SCHEDULED` or `ACCEPTED` status, initialized to zero at registration.

### 3.2. Recording the Notice and Building the Scope

A turn begins when a `TurnCoordinator` records a vacancy notice against a specific unit, supplying `unit_id`, the `notice_date` on which the resident gave notice, and the `move_out_date` on which the resident vacates; a `move_out_date` earlier than the `notice_date` is rejected with `ERR_INVALID_REQUEST`. The unit must be `OCCUPIED` — a unit already in `NOTICE`, `IN_TURN`, or `READY` refuses a new turn with `ERR_UNIT_NOT_OCCUPIED`. A successful creation opens the turn in `OPEN` status, moves the unit from `OCCUPIED` to `NOTICE`, and initializes every cost rollup to zero: `approved_budget_cents`, `estimated_cost_cents`, `expense_actual_cents`, `capital_actual_cents`, `total_actual_cents`, and `booked_expense_cents` all start at zero, while `started_on`, `target_ready_date`, `actual_ready_date`, and `projected_ready_date` remain null until the workflow reaches them.

With the turn open, the coordinator builds the work scope one item at a time, each item carrying `turn_id`, a `category` of `REPAIR`, `PAINT`, `CARPET`, `CLEAN`, `APPLIANCE`, `FIXTURE`, or `OTHER`, a free-text `description`, and an `estimated_cost_cents`. Every item is assigned a `sequence_rank` derived purely from its category — `REPAIR` ranks 1, `APPLIANCE` 2, `FIXTURE` 3, `PAINT` 4, `CARPET` 5, `CLEAN` 6, and `OTHER` 7 — which later governs scheduling order (§3.4). New items are born with `classification` `EXPENSE` (capital arises only through a replacement decision, §3.6), `approval_tier` `NONE`, and `rework_of_item_id` null; items created while the turn is `OPEN` enter `PLANNED` status immediately. Items may be added whenever the turn is `OPEN`, `SCOPED`, `IN_PROGRESS`, or `REWORK`; attempts against a `READY`, `CLOSED`, or `CANCELLED` turn are rejected with `ERR_INVALID_STATE`. Scope items can be listed with optional `turn_id`, `rework_of_item_id`, and `status` filters, and fetched individually.

### 3.3. Finalizing the Scope and Locking the Budget

Finalization is the pivot of the turn lifecycle: a `TurnCoordinator` locks the scope of an `OPEN` turn, and everything downstream — budgets, targets, projections, commitment risk — keys off that moment. A turn that is not `OPEN` rejects finalization with `ERR_INVALID_STATE`, and a turn with no `PLANNED` scope item rejects it with `ERR_NO_SCOPE_ITEMS`. On success the turn moves `OPEN` → `SCOPED` and, in the same atomic step: `approved_budget_cents` is locked to the turn's current `estimated_cost_cents` (the sum over its `PLANNED` items); `started_on` is stamped with the current logical-clock date; `target_ready_date` is set to `started_on` plus the property's `days_to_ready_target` calendar days; `projected_ready_date` is computed for the first time; the unit moves from `NOTICE` to `IN_TURN`; and the turn's `version` increments by one.

Two definitions govern every number seen from this point on. First, the turn's `estimated_cost_cents` is always the sum of each scope item's `estimated_cost_cents` over the items in `PLANNED`, `SCHEDULED`, `COMPLETED`, or `FAILED` status — items in `PENDING_APPROVAL`, `VOIDED`, or `REJECTED` are excluded — and it is re-derived whenever a scope item is created as `PLANNED`, approved, voided, rejected, or failed, or when a rework item is auto-created; the cancellation cascade of §3.9 is the sole exception, resolving the items without re-deriving the turn's rollups. Second, the `projected_ready_date` is a forward-looking computation: an anchor date begins at the later of the current logical-clock date and the latest `end_date` among the turn's vendor assignments in `SCHEDULED` or `ACCEPTED` status (the clock date alone when no such assignment exists); then each `PLANNED` scope item is processed in ascending `sequence_rank` order, ties broken by ascending `created_at`, and for each item the anchor advances by that category's standard duration — two days for `REPAIR`, two for `PAINT`, and one day each for `CARPET`, `CLEAN`, `APPLIANCE`, `FIXTURE`, and `OTHER`. There is one mandatory interruption: before each `PLANNED` `CARPET` item's day is added, if the turn still has any `PAINT`-category item whose status is not `COMPLETED`, `VOIDED`, `REJECTED`, or `FAILED`, one full cure day is added to the anchor first, giving the paint time to cure before carpet is laid — two planned carpet items under still-open paint contribute two cure days in all. The final anchor is the `projected_ready_date`, expressed as a whole ISO date. The projection is recomputed whenever a scope item is created as `PLANNED`, approved, voided, or rejected; whenever a vendor assignment is created, accepted, declined, completed, or cancelled; whenever an inspection is submitted; and whenever the logical clock is set. Every recomputation re-evaluates the risk status of the unit's open lease commitments (§3.8).

### 3.4. Scheduling Vendors: Calendars, Sequencing, and the Cure Buffer

Scheduling assigns real calendar windows to `PLANNED` work. A `TurnCoordinator` creates a vendor assignment with `scope_item_id`, `vendor_id`, a `start_date` on which work begins (inclusive), and an `end_date` on which it ends (exclusive) — the window is the half-open interval from `start_date` up to but not including `end_date`, and an `end_date` that does not fall after `start_date` is rejected with `ERR_INVALID_REQUEST`. The scope item must be `PLANNED`; scheduling against an item in any other status is rejected with `ERR_INVALID_STATE`. Beyond shape and state, four business rules guard the calendar, and the referential rule runs before the temporal ones per §2.8.

The first rule is trade matching (§3.1): a mismatched vendor is rejected with `ERR_VENDOR_TRADE_MISMATCH`. The second is vendor capacity: the new half-open window may not intersect any other `SCHEDULED` or `ACCEPTED` assignment of the same vendor, though pure adjacency — one assignment's `end_date` equalling the other's `start_date` — is allowed; a colliding request is rejected with `ERR_VENDOR_OVERLAP`. The third rule keeps one crew in the unit at a time: the new assignment may not share any calendar day with another `SCHEDULED` or `ACCEPTED` assignment on the same turn — a day-granularity rule which, because every window spans whole ISO dates, coincides with the half-open interval intersection test and so admits pure adjacency exactly as the vendor rule does — and a violation is rejected with `ERR_UNIT_WINDOW_OVERLAP`. The fourth is the cure buffer, the scheduling-time counterpart of the projection's cure day: the floor is computed from the latest `end_date` among the turn's `PAINT` assignments in `SCHEDULED`, `ACCEPTED`, or `COMPLETED` status, and a `CARPET` assignment whose `start_date` falls before that latest paint `end_date` plus one day is rejected with `ERR_CURE_BUFFER_VIOLATION` — the buffer binds even after the paint work has completed, still granting the finished paint its cure day. Finally, category sequencing requires that no same-turn item with a lower `sequence_rank` still sits in `PLANNED`, `PENDING_APPROVAL`, or `SCHEDULED` when the assignment is created — repairs before appliances, appliances before fixtures, fixtures before paint, paint before carpet, carpet before cleaning — and a violation is rejected with `ERR_SEQUENCE_VIOLATION`.

A created assignment enters `SCHEDULED`, moves its scope item from `PLANNED` to `SCHEDULED`, adds one to the vendor's `open_assignment_count`, and triggers a recomputation of the turn's `projected_ready_date` with commitment risk re-evaluated. From there the vendor itself drives the lifecycle, and only the assigned vendor may act — any other `X-User-ID` on these actions is rejected with `ERR_VENDOR_NOT_ASSIGNED`.

Acceptance moves a `SCHEDULED` assignment to `ACCEPTED` (any other starting status yields `ERR_INVALID_STATE`). The first acceptance on a `SCOPED` turn advances the turn to `IN_PROGRESS`; likewise, when the turn is `REWORK`, acceptance of an assignment on a rework item — one whose `rework_of_item_id` is set — returns the turn to `IN_PROGRESS`. Both transitions increment the turn's `version` by one, and every acceptance recomputes the projection and re-evaluates commitment risk. Decline moves a `SCHEDULED` assignment to `DECLINED`: the scope item falls back from `SCHEDULED` to `PLANNED`, the vendor's `open_assignment_count` drops by one (conserving the count across create-and-decline round trips), and the projection is recomputed with risk re-evaluated.

Completion is the money event. The assigned vendor completes an `ACCEPTED` assignment by reporting the invoiced `actual_cost_cents`; the assignment becomes `COMPLETED`, the vendor's `open_assignment_count` drops by one, and the scope item moves from `SCHEDULED` to `COMPLETED` with its own `actual_cost_cents` set from the assignment. Until that moment, `actual_cost_cents` is null on both the assignment and the scope item. That item completion recomputes the turn's actuals: the item's cost joins `expense_actual_cents` or `capital_actual_cents` according to its `classification`, `total_actual_cents` re-derives as their sum, and `booked_expense_cents` is rebuilt. Booked cost carries the property-management overhead allocation: for each `EXPENSE`-classified item in `COMPLETED` or `FAILED` status, an overhead of 250 basis points — two and a half percent — of the item's `actual_cost_cents` is computed and rounded half up to whole cents *per item*, the item's booked cost is its actual plus its own overhead, and `booked_expense_cents` is the sum of those per-item booked costs. Rounding each item before summing is mandatory; summing first and rounding once is forbidden. Concretely, two items of 1010 cents each contribute 25 cents of overhead apiece — 50 cents total, for a booked 2070 cents — whereas a sum-then-round scheme would round the combined 50.50 cents of overhead to 51 and incorrectly report 2071. The completion also recomputes `projected_ready_date` and re-evaluates commitment risk. Assignments can be listed with optional `vendor_id`, `scope_item_id`, and `status` filters, and fetched individually; vendors may read assignments alongside the management roles.

### 3.5. Scope Creep, Approval Tiers, and Budget Amendments

Reality intrudes after the budget is locked: walls open up, fixtures corrode, and the coordinator must add work to a turn that is already `SCOPED`, `IN_PROGRESS`, or `REWORK`. Every such post-finalization addition is tiered the moment it is created. The system computes a would-be estimate — the turn's current `estimated_cost_cents` plus the new item's `estimated_cost_cents` — and from it a variance in basis points: the would-be estimate minus the turn's `approved_budget_cents`, the difference multiplied by ten thousand, divided by `approved_budget_cents`, and rounded half up to a whole basis point. If `approved_budget_cents` is zero the division is skipped: the variance reads zero basis points when the would-be estimate is zero or negative, and an effectively unbounded 10^12 basis points when the would-be estimate is positive. The variance may legitimately be negative, for instance when earlier voids have pulled the estimate below budget. A variance at or below the property's `pm_threshold_bp` earns `approval_tier` `NONE` and the item is created directly in `PLANNED` — auto-approved, with equality at the threshold still approving. A variance above `pm_threshold_bp` but at or below `rm_threshold_bp` earns tier `PM`; anything above `rm_threshold_bp` earns tier `RM` — and note that equality at the regional threshold stays in the `PM` tier. Items in either escalated tier are created in `PENDING_APPROVAL` and are invisible to the turn's estimate and projection until approved. An auto-approved item, by contrast, immediately recomputes the turn's `estimated_cost_cents` and `projected_ready_date`, with commitment risk re-evaluated.

Approval and rejection of pending items belong to the management chain — `PropertyManager` and `RegionalManager` — under three preconditions evaluated in the order of §2.8. The item must be `PENDING_APPROVAL`, else `ERR_INVALID_STATE`. The request must carry `expected_turn_version` matching the turn's current `version`, else `ERR_STALE_VERSION`; this is the serialization point that stops a manager from approving against a budget baseline another writer has already moved. Finally, tier authority is enforced: a `PM`-tier item may be approved or rejected by either a `PropertyManager` or a `RegionalManager`, but an `RM`-tier item admits only a `RegionalManager`, and a `PropertyManager` attempting one is rejected with `ERR_APPROVAL_AUTHORITY_EXCEEDED`. Approval moves the item `PENDING_APPROVAL` → `PLANNED`, adds the item's `estimated_cost_cents` to the turn's `approved_budget_cents` — the budget legitimately grows to absorb sanctioned creep — increments the turn's `version` by one, and recomputes the estimate and projection with commitment risk re-evaluated. Rejection moves the item `PENDING_APPROVAL` → `REJECTED` under the same state and authority checks; rejected items are excluded from the estimate and the projection, and both are re-derived accordingly.

A `TurnCoordinator` may also void an item outright while it is `PLANNED` or `SCHEDULED`; against any other status the void is rejected with `ERR_INVALID_STATE`. Voiding a `PLANNED` item simply moves it to `VOIDED` and re-derives the turn's estimate and projection, with commitment risk re-evaluated. Voiding a `SCHEDULED` item additionally cascades: any of that item's assignments still in `SCHEDULED` or `ACCEPTED` is cancelled to `CANCELLED`, and then the estimate and projection are re-derived with risk re-evaluated.

### 3.6. Repair or Replace: Asset Decisions and Capital Classification

When a scope item in category `APPLIANCE` or `FIXTURE` represents an aging asset, a `TurnCoordinator` records a formal repair-versus-replace decision against the item's turn. The decision names the `scope_item_id` and carries the two competing estimates — `repair_estimate_cents` and `replace_estimate_cents` — the `repair_life_years` expected from a repair and the `remaining_life_years` expected from a brand-new asset (each at least one year, smaller values rejected with `ERR_INVALID_REQUEST`), and the coordinator's `decision` of `REPAIR` or `REPLACE`. The named item must belong to the path turn: a `scope_item_id` naming an item of a different turn is rejected with `ERR_NOT_FOUND`, exactly as if the item did not exist. A decision against a `VOIDED` or `REJECTED` item fails state validity with `ERR_INVALID_STATE` — a check that, per §2.8, precedes the category guard — while items in every other status admit a decision. Two referential guards then apply, before any economics: a decision on an item whose category is not `APPLIANCE` or `FIXTURE` is rejected with `ERR_DECISION_NOT_APPLICABLE`, and a second decision on an item that already has one is rejected with `ERR_DECISION_ALREADY_EXISTS` — at most one decision ever attaches to an item, so the per-item decision listing returns at most one element, while the per-turn listing returns every decision recorded on the turn.

Whether a `REPAIR` verdict is even permitted depends on the property's `replacement_policy`, and the policy in force at decision time is stamped onto the record as `policy_applied`. Under `PERCENT_OF_REPLACE`, a repair is economical only when `repair_estimate_cents` is strictly less than one-half of `replace_estimate_cents` rounded half up to whole cents — half the replacement estimate forms a ceiling the repair estimate must clear strictly from below. Under `COST_PER_YEAR`, a repair is economical only when `repair_estimate_cents` multiplied by `remaining_life_years` is strictly less than `replace_estimate_cents` multiplied by `repair_life_years` — an integer-exact, cross-multiplied comparison of cost per year of service, with no floating point involved. Identical inputs can yield opposite verdicts under the two variants: a 49000-cent repair against a 100000-cent replacement with a three-year repair life and a ten-year new-asset life is permitted by the percentage variant (49000 falls strictly below the 50000-cent ceiling) yet denied by the cost-per-year variant (490000 — the repair estimate times the ten-year new-asset life — is not strictly less than 300000, the replacement estimate times the three-year repair life). An uneconomical `REPAIR` is rejected with `ERR_UNECONOMICAL_REPAIR`; a `REPLACE` decision is never rejected by this rule.

Every recorded decision stamps `resulting_classification`: `REPAIR` always classifies `EXPENSE`, while `REPLACE` classifies `CAPITAL` exactly when `replace_estimate_cents` is greater than or equal to the property's `capital_threshold_cents`, and `EXPENSE` otherwise. The decision then rewrites the scope item it judged: the item's `estimated_cost_cents` is overwritten with the chosen path's estimate — `repair_estimate_cents` for a repair, `replace_estimate_cents` for a replacement — and its `classification` becomes `resulting_classification`. The turn's cost rollups are recomputed accordingly, including a re-partition of the expense and capital actuals when the decision lands on an item already `COMPLETED` or `FAILED`, and `projected_ready_date` is refreshed. Like inspections, replacement decisions are immutable records carrying `id` and `created_at` only.

### 3.7. Inspection, Rework, and the Recovery Loop

Quality control is deliberately segregated: only an `Inspector` — never the coordinator who ran the work — submits the verdict, and only while the turn is `IN_PROGRESS`; a turn in any other status rejects the submission with `ERR_INVALID_STATE`. The inspection carries a `result` of `PASS` or `FAIL`, an optional free-text `notes`, and `failed_scope_item_ids`, the list of items that failed. The list must be present and non-empty exactly when the result is `FAIL`, and absent or empty exactly when the result is `PASS`; any other combination is rejected with `ERR_INVALID_REQUEST`. Each listed item must currently be `COMPLETED` — failing work that was never finished is a state error, rejected with `ERR_INVALID_STATE`, and an identifier that belongs to another turn or to no item at all fails the same way. Duplicate identifiers in the list are de-duplicated, so each unique item fails exactly once, though the stored record echoes the submitted list verbatim; on a `PASS` record `failed_scope_item_ids` reads null. Inspections are immutable once submitted, carrying `id` and `created_at` but no `updated_at` or `version`, and the full inspection history of a turn can be listed.

A `PASS` is the happy ending: `actual_ready_date` is stamped with the current logical-clock date, the turn moves `IN_PROGRESS` → `READY` with its `version` incremented by one, the unit moves from `IN_TURN` to `READY`, and the projection machinery runs once more with commitment risk re-evaluated.

A `FAIL` opens the rework loop, and its cascade is the widest single-event mutation in the system. Each listed item moves from `COMPLETED` to `FAILED`, and for each failed item the system auto-creates a rework scope item: same `category` as the failed original, born in `PLANNED` status, its `estimated_cost_cents` seeded from the failed item's `actual_cost_cents`, its `classification` forced to `EXPENSE`, its `approval_tier` forced to `NONE`, its `rework_of_item_id` pointing back at the failed original, and its `description` seeded as "Rework of failed item: " followed by the failed item's description. The turn itself moves `IN_PROGRESS` → `REWORK` with its `version` incremented by one. Because failed items remain in the estimate's input set and their actuals stay in the expense actuals, the turn's `estimated_cost_cents`, `expense_actual_cents`, `capital_actual_cents`, `total_actual_cents`, and `booked_expense_cents` are all re-derived, and — driven by the newly created rework items — `projected_ready_date` is recomputed; if the projection now lands after some `ACTIVE` commitment's promised date on the unit, that commitment flips to `AT_RISK`. The turn then works its rework scope exactly like fresh scope: rework items are scheduled, accepted (returning the turn to `IN_PROGRESS`), and completed, and a later inspection either passes the turn to `READY` or fails it into another loop.

### 3.8. Pre-Leasing and Delivery Commitments

Turns rarely happen in a commercial vacuum: leasing wants the unit promised as early as possible. A `TurnCoordinator` creates a lease commitment against a unit with `unit_id`, the `applicant_name`, and a `committed_delivery_date` on which the unit is promised. Pre-leasing requires an active turn on the unit — one in `SCOPED`, `IN_PROGRESS`, or `REWORK` status — whose projection has been established; without one the request is rejected with `ERR_INVALID_STATE`. Two business rules then guard the promise. The unit may hold at most one open commitment at a time — if another commitment in `ACTIVE` or `AT_RISK` already exists on the unit, the request is rejected with `ERR_COMMITMENT_EXISTS`. And the promise may not undercut the projection: a `committed_delivery_date` earlier than the active turn's current `projected_ready_date` is rejected with `ERR_DELIVERY_BEFORE_PROJECTED`. A valid commitment is born `ACTIVE`. The commitments recorded against a unit can be listed through the unit's commitment collection.

From then on, the commitment rides the projection. Every recomputation of the active turn's `projected_ready_date` — whether driven by scope changes, assignment events, inspections, or a clock set — re-evaluates each open commitment on the unit: a projection now later than `committed_delivery_date` flips the commitment from `ACTIVE` to `AT_RISK`, and a later recomputation bringing the projection back to on or before the promised date flips it from `AT_RISK` back to `ACTIVE`. Either a `TurnCoordinator` or a `PropertyManager` may cancel a commitment while it is `ACTIVE` or `AT_RISK`, moving it to `CANCELLED`; against any other status the cancellation is rejected with `ERR_INVALID_STATE`.

The commitment resolves for good at move-in. A `TurnCoordinator` records the new resident's arrival with a `move_in_date`; the unit must be `READY`, else `ERR_INVALID_STATE`. The unit moves from `READY` back to `OCCUPIED`, closing the unit lifecycle loop, and if the unit holds a commitment in `ACTIVE` or `AT_RISK`, that commitment resolves in the same step: a `move_in_date` on or before `committed_delivery_date` resolves it to `FULFILLED` — from either `ACTIVE` or `AT_RISK` — while a `move_in_date` after `committed_delivery_date` resolves it to `BREACHED`, again from either status.

### 3.9. Closing the Books: Turn Closure, Cancellation, and the Property Benchmark

When the dust settles, a `PropertyManager` closes a `READY` turn — any other status is rejected with `ERR_INVALID_STATE` — moving it to the terminal `CLOSED` state and incrementing its `version` by one. Closure is what feeds the portfolio's memory: the property's benchmark aggregates are recomputed at the moment each turn closes, over exactly the set of that property's turns in `CLOSED` status, with cancelled and still-open turns excluded and no time window applied; later events touching an already-closed turn do not reopen the aggregates. `benchmark_turn_count` is the size of that set; `avg_booked_expense_cents` is the mean of those turns' `booked_expense_cents` — the overhead-loaded operating cost of §3.4 — rounded half up to a whole integer; and `avg_days_to_ready` is the mean of each closed turn's calendar-day span from `started_on` to `actual_ready_date`, likewise rounded half up. When no turn has ever closed, all three aggregates read zero. A `RegionalManager` or `PropertyManager` can read the computed benchmark for a property at any time.

Not every notice becomes a finished turn. A `PropertyManager` may cancel a turn while it is `OPEN` or `SCOPED`; against any later status the cancellation is rejected with `ERR_INVALID_STATE`, because work already in flight must be run to its conclusion. Cancellation is a full rollback cascade, symmetric across its two entry states. Cancelling an `OPEN` turn returns the unit from `NOTICE` to `OCCUPIED` — the notice is rescinded before the scope was ever locked. Cancelling a `SCOPED` turn returns the unit from `IN_TURN` to `OCCUPIED` — the notice is rescinded after the lock but before work began. In both cases the turn lands in the terminal `CANCELLED` state with its `version` incremented by one, its scope items move from `PLANNED` to `VOIDED`, from `PENDING_APPROVAL` to `REJECTED`, and from `SCHEDULED` to `VOIDED`; each item thus voided cancels any of its assignments still in `SCHEDULED` or `ACCEPTED` down to `CANCELLED`; and every lease commitment on the unit in `ACTIVE` or `AT_RISK` is cancelled to `CANCELLED`. Cancellation does not re-derive the turn's rollups: a `CANCELLED` turn goes on reporting the `estimated_cost_cents`, actuals, `booked_expense_cents`, and `projected_ready_date` it held at the moment of cancellation.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or trigger a state transition return `200 OK`, as do all reads. The table below is a summary only — request payloads, computed fields, preconditions, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/make-ready/_clock/set_current_utc` | Set the logical clock; re-projects non-terminal turns and re-evaluates commitment risk | PlatformAdmin |
| POST | `/make-ready/properties` | Create a property with its turn-policy configuration | RegionalManager |
| GET | `/make-ready/properties/{id}/turn-benchmark` | Read the property's benchmark aggregates over closed turns | RegionalManager, PropertyManager |
| POST | `/make-ready/units` | Create a unit | PropertyManager |
| GET | `/make-ready/units/{id}` | Get a unit | RegionalManager, PropertyManager, TurnCoordinator, Inspector |
| GET | `/make-ready/units` | List units, optionally filtered by property and/or status | RegionalManager, PropertyManager, TurnCoordinator, Inspector |
| POST | `/make-ready/units/{id}/record-move-in` | Record resident move-in; resolves any open lease commitment | TurnCoordinator |
| GET | `/make-ready/units/{id}/lease-commitments` | List lease commitments for a unit | RegionalManager, PropertyManager, TurnCoordinator |
| POST | `/make-ready/turns` | Open a turn on an occupied unit (records the vacancy notice) | TurnCoordinator |
| GET | `/make-ready/turns/{id}` | Get a turn, including all computed rollups and version | RegionalManager, PropertyManager, TurnCoordinator, Inspector |
| GET | `/make-ready/turns` | List turns, optionally filtered by unit and/or status | RegionalManager, PropertyManager, TurnCoordinator, Inspector |
| POST | `/make-ready/turns/{id}/finalize-scope` | Lock the approved budget, stamp start/target/projection, move the unit into turn | TurnCoordinator |
| POST | `/make-ready/turns/{id}/close` | Close a ready turn; the turn enters the property benchmark | PropertyManager |
| POST | `/make-ready/turns/{id}/cancel` | Cancel an open or scoped turn; cascades to items, assignments, commitments, unit | PropertyManager |
| POST | `/make-ready/turns/{id}/inspections` | Submit an inspection; pass readies the turn, fail opens the rework loop | Inspector |
| GET | `/make-ready/turns/{id}/inspections` | List inspections submitted for a turn | RegionalManager, PropertyManager, TurnCoordinator, Inspector |
| POST | `/make-ready/turns/{id}/replacement-decisions` | Record a repair-versus-replace decision for an appliance or fixture item | TurnCoordinator |
| GET | `/make-ready/turns/{id}/replacement-decisions` | List replacement decisions recorded on a turn | RegionalManager, PropertyManager, TurnCoordinator |
| GET | `/make-ready/scope-items/{id}/replacement-decisions` | List replacement decisions recorded against a scope item | RegionalManager, PropertyManager, TurnCoordinator |
| POST | `/make-ready/scope-items` | Add a scope item; post-finalization adds are tiered by scope-creep variance | TurnCoordinator |
| GET | `/make-ready/scope-items/{id}` | Get a scope item | RegionalManager, PropertyManager, TurnCoordinator, Inspector |
| GET | `/make-ready/scope-items` | List scope items, optionally filtered by turn, rework origin, and/or status | RegionalManager, PropertyManager, TurnCoordinator, Inspector |
| POST | `/make-ready/scope-items/{id}/approve` | Approve a pending scope item (OCC-guarded); raises the turn's approved budget | PropertyManager, RegionalManager |
| POST | `/make-ready/scope-items/{id}/reject` | Reject a pending scope item | PropertyManager, RegionalManager |
| POST | `/make-ready/scope-items/{id}/void` | Void a planned or scheduled scope item; cancels its active assignment | TurnCoordinator |
| POST | `/make-ready/vendors` | Register a vendor | PropertyManager |
| POST | `/make-ready/vendor-assignments` | Schedule a vendor against a planned scope item over a half-open window | TurnCoordinator |
| GET | `/make-ready/vendor-assignments/{id}` | Get a vendor assignment | RegionalManager, PropertyManager, TurnCoordinator, Inspector, Vendor |
| GET | `/make-ready/vendor-assignments` | List vendor assignments, optionally filtered by vendor, scope item, and/or status | RegionalManager, PropertyManager, TurnCoordinator, Inspector, Vendor |
| POST | `/make-ready/vendor-assignments/{id}/accept` | Assigned vendor accepts the assignment | Vendor |
| POST | `/make-ready/vendor-assignments/{id}/decline` | Assigned vendor declines; the scope item returns to planned | Vendor |
| POST | `/make-ready/vendor-assignments/{id}/complete` | Assigned vendor completes the work with the invoiced actual cost | Vendor |
| POST | `/make-ready/lease-commitments` | Pre-lease a unit during its turn against its projected ready date | TurnCoordinator |
| POST | `/make-ready/lease-commitments/{id}/cancel` | Cancel an active or at-risk lease commitment | TurnCoordinator, PropertyManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined where the governing rule lives in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VENDOR_NOT_ASSIGNED` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_UNIT_NOT_OCCUPIED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NO_SCOPE_ITEMS` | 422 |
| `ERR_VENDOR_TRADE_MISMATCH` | 422 |
| `ERR_VENDOR_OVERLAP` | 422 |
| `ERR_UNIT_WINDOW_OVERLAP` | 422 |
| `ERR_CURE_BUFFER_VIOLATION` | 422 |
| `ERR_SEQUENCE_VIOLATION` | 422 |
| `ERR_UNECONOMICAL_REPAIR` | 422 |
| `ERR_DECISION_NOT_APPLICABLE` | 422 |
| `ERR_DECISION_ALREADY_EXISTS` | 422 |
| `ERR_COMMITMENT_EXISTS` | 422 |
| `ERR_DELIVERY_BEFORE_PROJECTED` | 422 |
| `ERR_APPROVAL_AUTHORITY_EXCEEDED` | 403 |
