# Position Management & Headcount Planning API — Product Requirements Document

## 1. Introduction

Workforce planning lives at the intersection of two organizations that rarely speak the same language: Human Resources, which thinks in roles, reporting lines, and people; and Finance, which thinks in budgets, cost centers, and dollars. This API is the system of record that reconciles the two. It models the full life of a **position** — a funded slot in the organization, distinct from the person who happens to occupy it — from the moment an HR Business Partner drafts it, through funding approval by Finance, through the hiring and departure of incumbents, and ultimately to its abolishment. Every position belongs to a cost center, and every cost center holds a finite pool of money and full-time-equivalent (FTE) capacity that its positions draw against.

The platform is deliberately built around the separation between *plan* and *actual*. A vacant-but-funded position still costs money on paper — it is budgeted at the midpoint of its compensation grade — while a filled position costs whatever its real incumbent earns. The system continuously reconciles these figures so that, at any instant, a cost center reports a truthful committed cost, a committed headcount, a filled headcount, and the budget headroom that remains. Layered on top are the controls that large organizations depend on: hiring freezes that ripple down to suspend in-flight requisitions, span-of-control limits that keep the org chart healthy, grade reclassification workflows that route through compensation review and director approval, and forecast periods that snapshot plan-versus-actual headcount for fiscal reporting.

Because several roles act on the same shared budget pool concurrently, the API enforces optimistic concurrency on the operations that consume that pool, and it gates every funding and filling operation on whether the owning cost center is currently frozen. The remainder of this document specifies the global contract every endpoint obeys, the cross-cutting fiscal and structural principles, and the detailed business workflows that an implementer must reproduce exactly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. The `X-User-ID` header is an opaque identifier of the acting operator. The `X-User-Role` header must name exactly one of the four recognized roles: `HRBP`, `FinanceController`, `CompensationAnalyst`, or `HRDirector`. If `X-User-Role` is absent or names a value outside this set, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

All four roles use an opaque identity model. When `X-User-Role` is `HRBP`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `FinanceController`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never matched against an entity's `id`. The same holds when `X-User-Role` is `CompensationAnalyst`: the identifier is opaque and not entity-backed. And when `X-User-Role` is `HRDirector`, `X-User-ID` is again an opaque operator identifier with no persisted-entity backing. In short, ownership and authorization in this system are governed entirely by role, never by matching `X-User-ID` to a stored foreign key.

The roles divide responsibility along an approval chain in which no single role can complete another's exclusive step. An **HR Business Partner** (`HRBP`) drafts and edits positions, repoints the org chart, requisitions positions, fills and vacates incumbencies, and opens, closes, or cancels requisitions. A **Finance Controller** (`FinanceController`) owns cost centers, funds positions, opens and lifts hiring freezes, approves requisitions, creates and snapshots forecast periods, applies budget adjustments, and drives the test clock. A **Compensation Analyst** (`CompensationAnalyst`) owns grade bands and the early stages of reclassification — submitting a reclass, moving it under review, and returning it for revision. An **HR Director** (`HRDirector`) is the final approver: only this role can approve or reject a reclassification, and only this role can abolish a position. Creating an `Employee` is shared between `HRBP` and `HRDirector`. All read (GET) endpoints are available to all four roles.

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

All list endpoints are paginated through two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of records to skip from the start of the result set; its minimum is 0. List results are always sorted by `created_at` in ascending order, so the oldest record appears first. Each paginated response surfaces the four pagination fields inside the `meta` object: `limit` and `offset` echo the effective values used for the query, `total_count` reports the number of records matching the request before pagination is applied, and `has_more` is true exactly when records remain beyond the current page.

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format) that is refreshed on every mutation, and an integer `version` that begins at 1 on creation and increments by exactly 1 on each mutation. Two configuration-style entities are exceptions and are deliberately immutable after creation: a `Grade` and a `BudgetAdjustment` each carry only `id` and `created_at` — they have no `updated_at` and no `version`, because once written they are never mutated. A `Grade` is a fixed compensation-band configuration; a `BudgetAdjustment` is an append-only budget event.

Path and foreign-key resolution is performed left to right. For a nested path, each path segment is resolved in order before the next is considered, and any foreign-key reference carried in the request body is resolved after the path. If any path segment or referenced resource does not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated.

### 2.5. Validation Ordering and the Request Pipeline

When several checks could apply to one request, they are evaluated in a fixed priority order so that the same input always yields the same first failure. Authentication is checked first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization is checked second: a recognized but unpermitted role yields `ERR_FORBIDDEN`. Existence is checked third, walking path segments and then body foreign keys left to right, yielding `ERR_NOT_FOUND`. Request well-formedness is checked fourth — required fields must be present, enum fields must hold valid members, every `fte` value must be greater than 0 and at most 1.0 with at most two decimal places, and integer amounts must be at least 0 where the field demands it — with any violation yielding `ERR_INVALID_REQUEST` (HTTP 422). For endpoints guarded by optimistic concurrency, the version match is checked fifth, yielding `ERR_STALE_VERSION` (HTTP 412). The target resource's state is checked sixth against the requested transition, yielding `ERR_INVALID_STATE` (HTTP 409). Only after all of these structural gates pass are the domain-specific business rules — frozen posture, span limits, fill preconditions, freeze-window overlap, FTE cap, and budget — evaluated. In other words, an authentication failure always masks a permission failure, which masks a missing resource, which masks a malformed body, which masks a stale version, which masks an invalid state, which masks the business constraints below.

### 2.6. Optimistic Concurrency on the Cost-Center Pool

A cost center is a shared pool that multiple roles draw against, so the two operations that depend on a freshly read view of that pool are guarded by optimistic concurrency keyed on the cost center's `version`. Both of these operations require the caller to supply `expected_cost_center_version`, carrying the `version` of the owning cost center the client last observed.

The first guarded operation is **funding a position**. When a position is funded, the request must include `expected_cost_center_version`, and the server compares it to the owning cost center's current `version`. If another writer has advanced that `version` since the client last read it — for example by funding a different position, which shrank `available_budget_cents` and raised `committed_fte` — the fund request is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's budget and cap checks were computed against superseded figures and would otherwise overwrite a pool it has not observed.

The second guarded operation is **snapshotting a forecast period**. That operation freezes the owning cost center's `filled_fte` into the period's `actual_fte`, so it too must carry `expected_cost_center_version` matching the cost center's current `version`. If a fill or vacate has advanced the cost center's `version` since the client read it, the snapshot is rejected with `ERR_STALE_VERSION` (HTTP 412), so the period cannot capture a headcount figure the client never actually observed. No other endpoint accepts a version field; only these two consume the concurrency token.

### 2.7. The Plan-versus-Actual Cost Doctrine

The single most important fiscal idea in this system is that a position's cost has two faces. A funded position that is currently vacant is costed at its grade's midpoint — a forward-looking estimate of what filling it will cost — while a filled position is costed at the real salary of the employee occupying it. The system always keeps each position's `planned_cost_cents` and `actual_cost_cents` current, and rolls the appropriate one into the cost center's `committed_cost_cents` depending on whether the position is vacant or filled. This is why filling a position and later vacating it leaves the cost center's committed cost exactly where it started: the basis swings from planned to actual and back to planned, conserving the commitment.

All monetary fields are integer cents. Wherever a multiplication produces a fractional cent, the result is rounded half up to a whole number of cents. Crucially, this rounding is **per position, before any aggregation**: each position's planned or actual cost is rounded to whole cents first, and a cost center's committed cost is then the exact integer sum of those already-rounded per-position contributions. The system never multiplies many positions together and rounds once at the end. FTE quantities are carried to two decimal places; where an FTE total is aggregated across positions, the raw values are summed first and the sum is then rounded half up to two decimals.

### 2.8. The Funding Pool: FTE Cap and Budget Headroom

Each cost center publishes its remaining capacity continuously. Its `fte_cap` is the ceiling on total funded headcount; its `committed_fte` is the sum of the `fte` of every position currently funded or frozen; and the gap between them is the FTE headroom available to fund another position. On the money side, `adjusted_budget_cents` is the spendable budget after adjustments, `committed_cost_cents` is what is already committed, and `available_budget_cents` is the difference between the two. The available budget may dip below zero only when a funding or reclassification approval was performed with an explicit `override`. These derived fields — `committed_fte`, `committed_cost_cents`, `filled_fte`, `available_budget_cents`, and `posture` — are reconciled inside the very request that changes them, never lazily; a reader of a cost center always sees figures consistent with its children.

### 2.9. Hiring Freeze Posture and the Frozen Gate

A cost center's `posture` is a computed flag that is either `OPEN` or `FROZEN`. It is `FROZEN` exactly when some freeze order on that cost center is active and its window covers the current clock instant; otherwise it is `OPEN`. Freeze windows are half-open: an order covers an instant when its `effective_from` is at or before the instant and its `effective_to` is strictly after it, so an order whose `effective_to` equals the current instant does not freeze. While a cost center is `FROZEN`, a set of growth-oriented operations is blocked and rejected with `ERR_COST_CENTER_FROZEN` (HTTP 409): requisitioning a position, funding a position, filling a position with an incumbent, approving a requisition, and approving a reclassification. Read operations and freeze-lifting are never blocked by posture.

### 2.10. Cascade and Reconciliation Discipline

Several operations in this system mutate more than one entity in a single request, and every such cascade must complete atomically within that request. When a cascade changes a position's `lifecycle_status` or `occupancy_status`, it also bumps that position's `version` and refreshes its `updated_at`, and it recomputes whichever cost-center derived fields the change affects. When a freeze, lift, fill, vacate, or abolish ripples down to requisitions, reclass requests, incumbents, or employees, each touched record likewise advances its own `version` and `updated_at`. The detailed cascade chains — freeze suspending requisitions, abolish vacating incumbents and cancelling requisitions, lift re-opening everything it suspended — are specified in §3, but the governing rule is uniform: a single logical operation leaves the entire graph internally consistent before it returns.

## 3. Business Logic & Workflows

### 3.1. Foundational Configuration: Employees, Grades, and Cost Centers

Before any position can exist, three kinds of reference data are seeded. An `Employee` is created with a `full_name`, an `email` that must be unique among employees, and an `annual_salary_cents` value that is the employee's negotiated base salary in integer cents and may not be negative. Every new employee starts with a `status` of `AVAILABLE`, meaning they do not currently occupy any position; an employee becomes `ASSIGNED` only while actively occupying a position and returns to `AVAILABLE` when that occupancy ends.

A `Grade` is an immutable compensation band created by a `CompensationAnalyst`. It carries a `code` such as G07 that is unique among grades, three salary boundaries in integer cents — `band_min_cents`, `band_mid_cents`, and `band_max_cents` — and an integer `rank`. The boundaries must be ordered: the midpoint must be at least the minimum, and the maximum must be at least the midpoint, with all three being non-negative. The `rank` is an ordinal seniority marker that must be at least 1 and is unique among grades; a higher rank denotes a more senior grade. The midpoint is special because it is the basis on which any vacant funded position is costed.

A `CostCenter` is created by a `FinanceController` with a `name`, a `code` unique among cost centers, an `annual_budget_cents` base budget that may not be negative, and an `fte_cap` that bounds total funded FTE and may not be negative (carried to at most two decimals). At creation the derived fields settle to their empty-pool values: `committed_fte`, `committed_cost_cents`, and `filled_fte` are all zero; `adjusted_budget_cents` equals the base `annual_budget_cents`; `available_budget_cents` equals that same figure; and `posture` is `OPEN`. The cost center's `version` begins at 1.

A cost center's spendable budget can be revised after creation through an append-only budget event. Applying a `BudgetAdjustment` records a signed `amount_cents` (positive grants budget, negative claws it back; zero is never allowed) together with a `memo` explaining it, and the event is born already `APPLIED` with no further lifecycle. Its `adjusted_budget_cents` is then recomputed as the base `annual_budget_cents` plus the sum of `amount_cents` over every `APPLIED` adjustment on that cost center — so with no adjustments the adjusted budget simply equals the base budget — and `available_budget_cents` is refreshed accordingly. Applying an adjustment also increments the cost center's `version` by 1.

### 3.2. Drafting a Position and Shaping the Org Chart

An `HRBP` creates a position against a chosen cost center and grade, supplying the owning `cost_center_id`, the classification `grade_id`, a `title`, and an `fte` allocation that must be greater than 0 and at most 1.0 with no more than two decimals. The owning `cost_center_id` is fixed for the life of the position. Optionally the creator may supply a `manager_position_id` naming the position this one reports to in the org chart; when omitted (its default is null) the position is an organizational root. Every position is born in `lifecycle_status` `DRAFT` and `occupancy_status` `VACANT`, with `version` 1.

The org chart is a self-referential reporting tree: each position's `manager_position_id` points at the `id` of its managing position. A manager's `span_of_control` is the count of positions whose `manager_position_id` equals that manager's `id` and whose `lifecycle_status` is anything other than `ABOLISHED`. The platform protects against unmanageably wide reporting lines through a `MAX_SPAN_OF_CONTROL` ceiling of eight: a single manager may have no more than eight non-abolished direct reports. Consequently, when creating a position under a manager — or when repointing a position to a new manager — if that manager's direct-report count would rise to nine, the operation is rejected with `ERR_SPAN_LIMIT_EXCEEDED` (HTTP 409); a manager reaching exactly eight reports is permitted, since the cap is the eighth report, not the ninth.

While a position is still `DRAFT` or `REQUISITIONED`, an `HRBP` may edit its mutable attributes: its `title`, its `fte`, and its `manager_position_id`. Repointing the manager triggers the same span gate on the prospective new manager and recomputes the `span_of_control` of both the old and the new manager. Changing `fte` while the position is `DRAFT` or `REQUISITIONED` recomputes the position's `planned_cost_cents`. A position's `planned_cost_cents` is, at all times, its grade's `band_mid_cents` multiplied by its `fte`, rounded half up to whole cents.

### 3.3. Requisitioning and Funding: Drawing Against the Pool

Funding a position is a two-step climb through the lifecycle, driven by a single lifecycle command whose `action` field selects the requested move — `REQUISITION`, `FUND`, or `ABOLISH`. First, an `HRBP` requisitions it (an `action` of `REQUISITION`), which advances `lifecycle_status` from `DRAFT` to `REQUISITIONED`; this is permitted only while the position is `DRAFT` and the owning cost center's posture is `OPEN`, otherwise the request is rejected with `ERR_COST_CENTER_FROZEN`. Requisitioning bumps the position's `version`.

Second, a `FinanceController` funds the requisitioned position, advancing `lifecycle_status` from `REQUISITIONED` to `FUNDED`. Funding is the operation that actually consumes the cost-center pool, so it carries the heaviest set of preconditions. The position must currently be `REQUISITIONED`, and the owning cost center must be `OPEN` (else `ERR_COST_CENTER_FROZEN`). Because funding draws on the shared pool, the request must also carry `expected_cost_center_version`, and a mismatch with the cost center's live `version` is rejected with `ERR_STALE_VERSION` as described in §2.6.

Two fiscal admission checks then run together against the cost center's current headroom. The FTE headroom is the cost center's `fte_cap` minus its `committed_fte`; the budget headroom is its `adjusted_budget_cents` minus its `committed_cost_cents`. For funding, the FTE being added is the position's own `fte`, and the cost being added is the position's `planned_cost_cents`. The position is admitted only when the added FTE is less than or equal to the FTE headroom **and** the added cost is less than or equal to the budget headroom — with both comparisons admitting equality, so a position whose FTE or cost exactly consumes the remaining headroom is allowed. If the FTE being added exceeds the FTE headroom, funding is rejected with `ERR_FTE_CAP_EXCEEDED` (HTTP 409). If the FTE fits but the cost exceeds the budget headroom, funding is rejected with `ERR_BUDGET_EXCEEDED` (HTTP 409) — unless the caller passed `override` as true, in which case the budget check is waived and the cost center is permitted to go into negative `available_budget_cents`. The `override` flag never waives the FTE cap.

On a successful fund, `lifecycle_status` becomes `FUNDED`; the cost center's `committed_fte` is recomputed (it now includes this position's `fte`), its `committed_cost_cents` grows by this position's planned contribution, and its `available_budget_cents` is refreshed. The position's `version` increments by 1, and — because funding consumes the shared pool — the cost center's own `version` also increments by 1, which is what makes a concurrent client's previously read version stale.

### 3.4. Filling and Vacating: Incumbents and the Actual-Cost Swing

Filling a position attaches an incumbent. An `HRBP` fills a `FUNDED`, `VACANT` position by naming an `employee_id` and a `start_date` (the inclusive occupancy start). The preconditions are layered: the position must be `FUNDED` (else `ERR_POSITION_NOT_FUNDED`), it must currently be `VACANT` (else `ERR_POSITION_ALREADY_FILLED`), the owning cost center must be `OPEN` (else `ERR_COST_CENTER_FROZEN`), the chosen employee's `status` must be `AVAILABLE` (else `ERR_EMPLOYEE_UNAVAILABLE`), and the employee's `annual_salary_cents` must lie within the grade band — at least `band_min_cents` and at most `band_max_cents`, inclusive at both ends — or the fill is rejected with `ERR_SALARY_OUT_OF_BAND`. Finally, the new occupancy interval, running from `start_date` forward with an open end, must not overlap any existing incumbency interval on that position, whether that prior incumbency is still `ACTIVE` or already `VACATED`; an overlap is rejected with `ERR_INCUMBENCY_OVERLAP`. Because both endpoints are inclusive — a fill's `start_date` is the inclusive occupancy start and a `VACATED` incumbency's `end_date` is the inclusive vacate instant — incumbency intervals are treated as closed, so unlike the half-open freeze windows of §2.9 two incumbency intervals that merely touch at a shared boundary instant **do** overlap. Concretely, the new interval `[start_date, ∞)` overlaps a prior `ACTIVE` interval (whose end is still open) whenever both are on this position, and overlaps a prior `VACATED` interval `[prior_start, prior_end]` exactly when `start_date` is at or before `prior_end`; a refill on a vacated position must therefore begin strictly after the prior `end_date`.

A successful fill creates an `Incumbent` record in `status` `ACTIVE` with its `position_id` and `employee_id` set, an `end_date` of null while active, flips the position's `occupancy_status` to `FILLED`, and moves the employee's `status` to `ASSIGNED`. The position's `actual_cost_cents` is then computed as the incumbent employee's `annual_salary_cents` multiplied by the position's `fte`, rounded half up to whole cents. Because the position is now filled, the cost center swaps this position's contribution from its planned basis to its actual basis when recomputing `committed_cost_cents`, and it recomputes `filled_fte` and `available_budget_cents`. The position's `version` increments by 1.

Vacating reverses the occupancy. An `HRBP` vacates an active incumbency by supplying a `vacate_date`; this is permitted only while the position is `FILLED` and the incumbency is `ACTIVE`. The incumbent's `status` becomes `VACATED` and its `end_date` is set to the supplied `vacate_date` (inclusive), the position returns to `occupancy_status` `VACANT`, and the employee's `status` returns to `AVAILABLE`. The position's `actual_cost_cents` reverts to 0, and the cost center recomputes `committed_cost_cents` with this position's basis restored to planned, along with `filled_fte` and `available_budget_cents`. Vacating increments the position's `version` by 1. Because the basis swings planned → actual → planned across a fill-then-vacate, the cost center's committed cost ends exactly where it began.

### 3.5. Hiring Freezes and Their Cascades

A `FinanceController` opens a hiring freeze on a cost center by declaring a window with an `effective_from` (inclusive lower bound) and an `effective_to` (exclusive upper bound) plus a `reason`. The window must be well-formed — `effective_from` strictly before `effective_to` — and it must not overlap any other still-active freeze order on the same cost center; because windows are half-open, two windows that merely touch at a shared boundary instant do not overlap, but any genuine overlap is rejected with `ERR_FREEZE_WINDOW_OVERLAP` (HTTP 409). A new order is born `ACTIVE`. Creating the order recomputes the cost center's `posture`; if the window covers the current clock instant the cost center becomes `FROZEN`.

When the cost center flips to `FROZEN`, a cascade runs. Each `FUNDED` position on that cost center transitions to `lifecycle_status` `FROZEN`, and each such freeze in turn suspends that position's open requisitions: every requisition in `OPEN` status on a frozen position moves to `SUSPENDED`. A frozen position retains its contribution to `committed_fte` and `committed_cost_cents` — freezing conserves the commitment rather than releasing it. Each position and requisition touched by the cascade advances its own `version`.

Lifting reverses the freeze. A `FinanceController` lifts an active freeze order, moving its `status` from `ACTIVE` to `LIFTED`, which removes it from posture computation, and the cost center's `posture` is recomputed. If, with that order removed, no other active freeze order still covers the current clock instant, the cost center flips back to `OPEN` and a compensating cascade un-freezes its workforce: each `FROZEN` position returns to `FUNDED`, and the un-freezing of each position re-opens the requisitions it had suspended, so every `SUSPENDED` requisition on those positions returns to `OPEN`. A position only un-freezes when no remaining active order still covers the instant for its cost center. Lifting increments the freeze order's `version`.

The same posture machinery responds to the passage of time. An administrative test-driving capability, available only to a `FinanceController`, sets the server's current UTC instant from a supplied `to_iso8601` value, after which the posture of every cost center is recomputed against the new instant and the freeze/un-freeze cascades fire for any window that has just opened or just closed.

### 3.6. Requisition Lifecycle: Backfills and Approvals

A requisition is the formal request to staff a position, opened by an `HRBP` against a position with a `req_type` of either `NEW_HIRE` or `BACKFILL` — a `BACKFILL` re-opens a position vacated by a departed incumbent — together with a `justification`. A requisition is born `OPEN` with `version` 1. From `OPEN` it can travel several ways. A `FinanceController` approves an open requisition, moving it to `APPROVED`; approval is permitted only while the requisition is `OPEN`, the owning position is `FUNDED` (else `ERR_POSITION_NOT_FUNDED`), and the owning cost center is `OPEN` (else `ERR_COST_CENTER_FROZEN`). An `HRBP` may instead cancel an open requisition, moving it to `CANCELLED`, which is allowed only from `OPEN`.

Once `APPROVED`, a requisition is closed by an `HRBP`, moving it to `CLOSED`; closing is permitted only when the requisition is `APPROVED` and the owning position is `FILLED` (else `ERR_POSITION_NOT_FILLED`). The two terminal states are `CLOSED` and `CANCELLED`. Beyond these operator-driven transitions, requisitions also move as a consequence of freeze, un-freeze, and abolish cascades: an `OPEN` requisition becomes `SUSPENDED` when its position freezes, a `SUSPENDED` requisition returns to `OPEN` when its position un-freezes, and a `SUSPENDED` requisition becomes `CANCELLED` when its position is abolished. Every one of these transitions increments the requisition's `version` by 1.

### 3.7. Reclassification: Grade Change Through Review and Approval

Reclassification moves a position from one grade to another and is the one workflow that spans the full approval chain. A `CompensationAnalyst` submits a reclass request against a position, naming a `target_grade_id` and a `justification`. At submission the system snapshots the position's current grade rank into `from_grade_rank` and the target grade's rank into `target_grade_rank`, and derives the request's `direction`: if the target rank is greater than the current rank the direction is `UPGRADE`, if the target rank is less than the current rank it is `DOWNGRADE`, and if the two ranks are equal it is `LATERAL`. The request is born `SUBMITTED` with `version` 1.

The review path is cyclic. The same `CompensationAnalyst` role moves a `SUBMITTED` request to `UNDER_REVIEW`, and from `UNDER_REVIEW` may return it to `SUBMITTED` for revision; a request may bounce between `UNDER_REVIEW` and `SUBMITTED` any number of times. From `UNDER_REVIEW`, an `HRDirector` renders the final decision — approve or reject. Both are permitted only while the request is `UNDER_REVIEW`. Rejecting moves the request to `REJECTED`. Approving is gated further: the owning position's `lifecycle_status` must be either `REQUISITIONED` or `FUNDED` (else `ERR_INVALID_STATE`), and the owning cost center must be `OPEN` (else `ERR_COST_CENTER_FROZEN`).

When the position being reclassified is already `FUNDED` and the move is an `UPGRADE`, approval also consumes budget, so it runs a budget admission check. The check compares the cost center's existing `committed_cost_cents`, with this position's old planned contribution removed and its new planned contribution added, against the cost center's budget — equivalently, the change in this position's planned cost must fit within the budget headroom, admitting equality. If the new commitment would exceed `annual_budget_cents` and `override` is not true, approval is rejected with `ERR_BUDGET_EXCEEDED`; passing `override` as true waives this check and allows `available_budget_cents` to go negative. A `DOWNGRADE` or `LATERAL`, or any approval on a position that is not `FUNDED`, runs no budget check.

A successful approval sets the request's `status` to `APPROVED`, repoints the position's `grade_id` to the `target_grade_id`, and recomputes the position's `planned_cost_cents` against the new grade's midpoint. If the position is `FUNDED`, the cost center's `committed_cost_cents` and `available_budget_cents` are recomputed to reflect the new planned basis. Approval increments both the reclass request's `version` and the position's `version` by 1. Each review-loop and reject transition increments the reclass request's `version` by 1.

### 3.8. Abolishing a Position and the Teardown Cascade

Retiring a position is the `HRDirector`'s exclusive act. A position may be abolished from either `REQUISITIONED` or `FUNDED`, moving its `lifecycle_status` to the terminal `ABOLISHED`. The one structural guard is the org chart: a position cannot be abolished while any position reporting to it (any position whose `manager_position_id` equals this position's `id`) is still in a state other than `ABOLISHED`; such an attempt is rejected with `ERR_HAS_DIRECT_REPORTS` (HTTP 409). Reports must be reassigned or abolished from the leaves upward.

Abolishing a `REQUISITIONED` position simply marks it `ABOLISHED` and bumps its `version`. Abolishing a `FUNDED` position runs a fuller teardown. If the position was `FILLED`, its active incumbent is moved to `VACATED`, the position's `occupancy_status` returns to `VACANT`, and the occupied employee's `status` returns to `AVAILABLE`. Any requisition on the position that is `OPEN` or `SUSPENDED` is moved to `CANCELLED`. Any reclass request on the position that is `SUBMITTED` or `UNDER_REVIEW` is moved to `REJECTED`. Finally the cost center recomputes `committed_fte`, `committed_cost_cents`, `filled_fte`, and `available_budget_cents` to release this position's commitment. The position's `version` increments by 1, and every record swept up in the cascade advances its own `version` as well.

### 3.9. Headcount Forecasting: Plan, Snapshot, and Variance

Forecasting closes the loop between intention and reality. A `FinanceController` creates a forecast period on a cost center with a `fiscal_label` (such as FY26-Q1, unique per cost center) and an operator-entered `planned_fte` — the headcount the period plans for, at least 0 and carried to two decimals. A new period is born `DRAFT` with `version` 1; its `actual_fte` and `variance_fte` remain unset until the period is snapshotted.

Snapshotting freezes the period against the live organization. A `FinanceController` snapshots a `DRAFT` period, which is permitted only while the period is `DRAFT` and which is guarded by optimistic concurrency: the request must carry `expected_cost_center_version` matching the owning cost center's current `version`, or it is rejected with `ERR_STALE_VERSION` as described in §2.6. On snapshot, the period's `actual_fte` is captured as the owning cost center's `filled_fte` at that instant — the sum of the `fte` of all currently filled positions, rounded half up to two decimals — and `variance_fte` is computed as that `actual_fte` minus the period's `planned_fte`, also to two decimals. The period's `status` becomes `SNAPSHOTTED`, which freezes both figures. Snapshotting stamps the cost center's headcount baseline by incrementing the cost center's `version` by 1, and it increments the forecast period's own `version` by 1.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Endpoints that create a brand-new resource return HTTP 201; endpoints that modify, transition, or act on an existing resource return HTTP 200; read endpoints return HTTP 200. The request body, response payload, and side effects of each endpoint are described in the §3 narratives, not duplicated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/employees` | Create an Employee | HRBP, HRDirector |
| GET | `/employees/{employeeId}` | Get an Employee | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/employees` | List Employees (paginated; filter by status) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/grades` | Create a Grade band (immutable) | CompensationAnalyst |
| GET | `/grades/{gradeId}` | Get a Grade | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/grades` | List Grades (paginated) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/cost-centers` | Create a CostCenter | FinanceController |
| GET | `/cost-centers/{costCenterId}` | Get a CostCenter with derived budget/posture fields | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/cost-centers` | List CostCenters (paginated) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/positions` | Create a Position in DRAFT/VACANT | HRBP |
| GET | `/positions/{positionId}` | Get a Position with derived span and cost fields | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/positions` | List Positions (paginated; filterable) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| PATCH | `/positions/{positionId}` | Update mutable Position fields | HRBP |
| POST | `/positions/{positionId}/lifecycle` | Drive Position funding lifecycle (REQUISITION, FUND, ABOLISH) | HRBP, FinanceController, HRDirector |
| GET | `/cost-centers/{costCenterId}/positions` | List Positions under a CostCenter | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/positions/{positionId}/reports` | List direct-report Positions | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/positions/{positionId}/incumbents` | Fill a Position; create an ACTIVE Incumbent | HRBP |
| GET | `/positions/{positionId}/incumbents` | List incumbency records for a Position | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/incumbents/{incumbentId}` | Get an Incumbent record | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/incumbents` | List Incumbents (filterable) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/incumbents/{incumbentId}/vacate` | Vacate an active incumbency | HRBP |
| POST | `/cost-centers/{costCenterId}/freeze-orders` | Open a hiring freeze window on a CostCenter | FinanceController |
| GET | `/cost-centers/{costCenterId}/freeze-orders` | List FreezeOrders on a CostCenter | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/freeze-orders/{freezeOrderId}` | Get a FreezeOrder | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/freeze-orders` | List FreezeOrders (filterable) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/freeze-orders/{freezeOrderId}/lift` | Lift a FreezeOrder; may un-freeze positions/requisitions | FinanceController |
| POST | `/positions/{positionId}/requisitions` | Open a requisition (NEW_HIRE or BACKFILL) | HRBP |
| GET | `/positions/{positionId}/requisitions` | List requisitions for a Position | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/requisitions/{requisitionId}` | Get a Requisition | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/requisitions` | List Requisitions (filterable) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/requisitions/{requisitionId}/approve` | Approve an OPEN requisition | FinanceController |
| POST | `/requisitions/{requisitionId}/close` | Close an APPROVED requisition | HRBP |
| POST | `/requisitions/{requisitionId}/cancel` | Cancel an OPEN requisition | HRBP |
| POST | `/positions/{positionId}/reclass-requests` | Submit a reclassification request | CompensationAnalyst |
| GET | `/positions/{positionId}/reclass-requests` | List reclass requests for a Position | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/reclass-requests/{reclassId}` | Get a ReclassRequest | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/reclass-requests` | List ReclassRequests (filterable) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/reclass-requests/{reclassId}/review` | Move a SUBMITTED reclass to UNDER_REVIEW | CompensationAnalyst |
| POST | `/reclass-requests/{reclassId}/return` | Return an UNDER_REVIEW reclass to SUBMITTED | CompensationAnalyst |
| POST | `/reclass-requests/{reclassId}/approve` | Approve an UNDER_REVIEW reclass; applies grade | HRDirector |
| POST | `/reclass-requests/{reclassId}/reject` | Reject an UNDER_REVIEW reclass | HRDirector |
| POST | `/cost-centers/{costCenterId}/forecast-periods` | Create a DRAFT forecast period | FinanceController |
| GET | `/cost-centers/{costCenterId}/forecast-periods` | List forecast periods on a CostCenter | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/forecast-periods/{forecastPeriodId}` | Get a ForecastPeriod | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/forecast-periods` | List ForecastPeriods (filterable) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/forecast-periods/{forecastPeriodId}/snapshot` | Snapshot actual filled FTE and compute variance | FinanceController |
| POST | `/cost-centers/{costCenterId}/budget-adjustments` | Apply a signed budget adjustment (append-only) | FinanceController |
| GET | `/cost-centers/{costCenterId}/budget-adjustments` | List BudgetAdjustments on a CostCenter | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/budget-adjustments/{budgetAdjustmentId}` | Get a BudgetAdjustment | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| GET | `/budget-adjustments` | List BudgetAdjustments (filterable) | HRBP, HRDirector, FinanceController, CompensationAnalyst |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC instant | FinanceController |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_COST_CENTER_FROZEN | 409 |
| ERR_SPAN_LIMIT_EXCEEDED | 409 |
| ERR_HAS_DIRECT_REPORTS | 409 |
| ERR_POSITION_NOT_FUNDED | 409 |
| ERR_POSITION_ALREADY_FILLED | 409 |
| ERR_POSITION_NOT_FILLED | 409 |
| ERR_EMPLOYEE_UNAVAILABLE | 409 |
| ERR_SALARY_OUT_OF_BAND | 409 |
| ERR_INCUMBENCY_OVERLAP | 409 |
| ERR_FREEZE_WINDOW_OVERLAP | 409 |
| ERR_FTE_CAP_EXCEEDED | 409 |
| ERR_BUDGET_EXCEEDED | 409 |
