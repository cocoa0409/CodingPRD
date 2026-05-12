# Equipment Maintenance API — Product Requirements Document

## 1. Introduction

Industrial sites lose money two ways: equipment that fails unexpectedly and equipment that is taken offline more often than its service profile actually requires. Bridging the gap calls for a single system of record that knows every asset's category, criticality, location, warranty window, and lifecycle state, and that drives a disciplined cadence of inspections, repairs, and parts movements around it. The Equipment Maintenance API is that system of record. It exposes a multi-tenant model rooted at the **Site**, and inside each site it covers the full operational arc — equipment ledger, maintenance-plan catalogue, work-order dispatch, spare-parts inventory, repair documentation, and reliability analytics — under one consistent contract.

The system serves four operational roles plus a read-only viewer role. Site managers maintain the equipment fleet and accept finished work. Plan owners author task templates and maintenance plans. Dispatchers route work and reassign technicians. Technicians (the only role tied to a persisted entity) execute work in the field. Storekeepers run the parts inventory. Each role is bounded by an RBAC matrix, and most state-changing actions also require an explicit ownership match between the caller and the affected resource. Because the system also supplies analytics — mean-time-to-repair, mean-time-between-failures, fault recurrence, and equipment availability — those calculations must be deterministic, reproducible, and explainable from the recorded state alone, including a deterministic logical clock that test harnesses can advance.

The remainder of this document specifies cross-cutting contracts (§2), the business workflows organized by lifecycle and concern (§3), the endpoint catalogue (§4), and the error-code reference (§5). All implementation details — JSON shapes, validation outcomes, calculation rules, audit trails — must conform to the prose of §2 and §3 even where §4 is summarized.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. If both headers are present but the role is not authorized for the endpoint per the RBAC matrix in §4, the request is rejected with `ERR_FORBIDDEN` and HTTP 403.

The system recognizes exactly five role names — `SiteManager`, `PlanOwner`, `Dispatcher`, `Technician`, and `Storekeeper` — plus the pseudo-role `Any`, which means any authenticated role may invoke a read-only endpoint listed as such.

Identity semantics differ by role:

- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity within the addressed site. Ownership checks on a `WorkOrder` compare `WorkOrder.assigned_technician_id` to `X-User-ID`; a mismatch yields `ERR_FORBIDDEN_NOT_OWNER` with HTTP 403. A technician whose record does not exist at the addressed site, or whose record exists but does not match the caller's `X-User-ID`, is treated identically.
- When `X-User-Role` is `SiteManager`, `PlanOwner`, `Dispatcher`, or `Storekeeper`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it in audit entries as `actor_user_id`, but never compares it to any entity's `id`. There is one exception that is not a comparison against an entity `id` but against a free-form field: when a `SiteManager` accepts a completed work order, `X-User-ID` must equal the `responsible_user_id` recorded on the equipment, otherwise the action is rejected with `ERR_FORBIDDEN_NOT_OWNER`. The same `responsible_user_id` is later written into `RepairRecord.acceptance_user_id`.

A workflow is "exclusive" to a role when only that role may invoke it; "shared" operations may be invoked by any role listed as a peer for that operation. The shared/exclusive split for each endpoint is captured by the Authorized Role(s) column of §4.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, the maximum is 100; values outside this range are rejected with `ERR_BAD_REQUEST`. The default `offset` is 0 and must be non-negative. List results are sorted by `created_at` ascending; entities whose schema omits `created_at` are sorted by `id` ascending. The response `meta` block includes `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true precisely when `offset + limit < total_count`.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` that is a plain UUID with no type prefix and is unique system-wide. Most resources also carry `created_at` and `updated_at` (ISO 8601 UTC with three fractional digits) and a monotonic integer `version` that starts at 1 on creation and increases by exactly one on every successful mutation. Three entities are exempt from this set: `TaskTemplate`, `RepairRecord`, `AlarmEvent`, and `AuditEntry` carry only `id` and `created_at` — both `updated_at` and `version` are absent on them. The remaining entities — `Site`, `Equipment`, `MaintenancePlan`, `SparePart`, `Technician`, `WorkOrder`, and `Requisition` — carry the full common set.

### 2.5. Optimistic Concurrency Control

All `PATCH` endpoints accept an optional `version` in the request body. When `version` is supplied, it must equal the current entity `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT` and HTTP 409. When `version` is omitted, the OCC check is skipped and the mutation proceeds against whatever the latest state happens to be. On every successful mutation that returns a 200 response, the entity's `version` increments by exactly one and `updated_at` is refreshed to the site clock.

### 2.6. Site-Scoped Hierarchy and Path Validation

All operational state lives under a `Site`, identified by its `id`. Every nested resource — equipment, templates, plans, spare parts, technicians, work orders, requisitions, repair records, audit entries, analytics queries — is addressed through a URL path rooted at the site (e.g., a work order URL contains `:site_id` then `:wo_id`). Path segments are validated **left to right**: if `:site_id` does not exist, the response is `ERR_NOT_FOUND` with HTTP 404 regardless of subsequent segments; if the site exists but `:equipment_id`, `:plan_id`, `:template_id`, `:part_id`, `:tech_id`, `:wo_id`, or `:req_id` does not exist within that site, the response is again `ERR_NOT_FOUND`. Similarly, every body field that names another resource (`equipment_id`, `template_id`, `plan_id`, `part_id`, `new_technician_id`, `preferred_technician_id`, `scope_id`) must reference an entity that lives in the same site as the URL; otherwise the request fails with `ERR_CROSS_SITE_REFERENCE` and HTTP 422.

### 2.7. Logical Clock and Sweep Tick

Each site has a deterministic logical clock, `Site.clock_now`, initialized at site creation to `2026-01-01T00:00:00.000Z`. All temporal arithmetic — SLA computation, MTTR/MTBF windows, fault-recurrence look-back, availability windows, plan-due evaluations, audit timestamps — uses this clock and only this clock; wall-clock time is irrelevant. The clock is advanced by an admin-only test-driving capability that adds a strictly positive `seconds` value. Site creation also initializes `sweep_run_index` to 0; this counter is incremented on each invocation of the sweep capability described in §3.

### 2.8. Precision and Rounding

Money is represented in integer cents and never as a decimal. All ratio-style analytics — equipment availability, fault recurrence — are rounded **half-up to four decimal places** in the response. Time-style analytics — MTTR (in minutes) and MTBF (in hours) — are rounded **half-up to two decimal places**. Datetime arithmetic operates in seconds, with no rounding. Boundary semantics use the operators stated next to each metric in §3 (typically `<=` for inclusive lower thresholds and `<` for exclusive upper bounds on windows).

### 2.9. Validation Priority

When a request can fail multiple checks, validations are evaluated in a fixed priority order so that the first failure determines the returned `error_id`. The order, from highest to lowest priority, is: (1) authentication header presence — `ERR_UNAUTHENTICATED`; (2) RBAC role permission — `ERR_FORBIDDEN`; (3) URL path existence within the site, left-to-right — `ERR_NOT_FOUND`; (4) cross-aggregate reference site match for `equipment_id`, `template_id`, `plan_id`, `part_id`, and similar — `ERR_CROSS_SITE_REFERENCE`; (5) target resource state for the operation — `ERR_INVALID_STATE`; (6) equipment lifecycle gate — `ERR_EQUIPMENT_LIFECYCLE`; (7) equipment-busy gate — `ERR_EQUIPMENT_BUSY`; (8) acceptance-evidence presence — `ERR_EVIDENCE_MISSING`; (9) technician skill match — `ERR_SKILL_MISMATCH`; (10) acceptance-by-responsible-owner — `ERR_FORBIDDEN_NOT_OWNER` for accept; (11) work-order ownership match for technician transitions — `ERR_FORBIDDEN_NOT_OWNER`; (12) sweep-tick freshness for cancelling a paused work order — `ERR_PAUSE_TOO_FRESH`; (13) no-still-reserved-requisitions gate at completion — `ERR_REQUISITIONS_PENDING`; (14) at-least-one-issued-requisition gate when resuming from a parts wait — `ERR_PARTS_NOT_ISSUED`; (15) plan-kind required-field check — `ERR_PLAN_KIND_FIELDS`; (16) sufficient stock-on-hand for issuance — `ERR_INSUFFICIENT_STOCK`; (17) sufficient available stock (on-hand minus reserved) for reservation — `ERR_INSUFFICIENT_AVAILABLE`; (18) return-quantity bounds — `ERR_RETURN_QTY_INVALID`; (19) temporal invariants on warranty and alarm time — `ERR_TEMPORAL_INVALID`; (20) optimistic-concurrency `version` match — `ERR_VERSION_CONFLICT`. A check at lower priority is never evaluated until every higher check has passed; this ordering matters wherever a single request could trip more than one rule. Inputs that are merely malformed JSON or missing required body fields fail at parse time with `ERR_BAD_REQUEST` and HTTP 400, prior to any of the above.

### 2.10. Audit Trail and Eventing

Every state-changing operation on a `WorkOrder` and every state-changing operation on a `Requisition` produces an `AuditEntry` carrying `actor_role`, `actor_user_id`, an `action` drawn from `WORK_ORDER_STATE_CHANGE`, `PARTS_ISSUED`, `PARTS_RETURNED`, or `TECHNICIAN_ASSIGNED`, the affected resource's `target_id`, the prior status as `from_value` (the empty string on creation), the new status as `to_value`, and `occurred_at` set to the site clock at the moment of the action. Audit entries are append-only and immutable. The system also emits a notification, expressed as a side-effect-only `/events/replenish` event for test fixtures, the first time a spare part crosses the replenishment threshold; this notification does not change any database state beyond setting `replenish_pending` to true.

### 2.11. Cascade and Cross-Entity Consistency

When one operation mutates more than one entity, every cascade is part of the contract. Decommissioning equipment retires every `ACTIVE` `MaintenancePlan` for that equipment to `RETIRED`, cancels every `PENDING` `WorkOrder` to `CANCELLED` with a `cancel_reason` of `EQUIPMENT_DECOMMISSIONED`, and within each cancelled work order cancels all `RESERVED` requisitions and re-evaluates replenishment for the affected spare parts. A work order completing or cancelling restores the equipment lifecycle from `UNDER_MAINTENANCE` to `IN_SERVICE`, clears `Equipment.open_work_order_id`, and on completion stamps `Equipment.last_repair_completed_at` to `Site.clock_now`. Whenever an entity is mutated, its `updated_at` is refreshed and its `version` increments by one for entities that carry `version`.

## 3. Business Logic & Workflows

### 3.1. Establishing a Site and Driving the Logical Clock

Operations begin with a `SiteManager` creating a site by submitting the site `name`. The newly created site has `clock_now` set to `2026-01-01T00:00:00.000Z` and `sweep_run_index` set to 0. From that moment forward, the only way time advances is through the test-driving capability that adds a strictly positive `seconds` value to `clock_now`; both `SiteManager` and `Dispatcher` may invoke this capability. The clock-advance capability does not by itself trigger any plan generation or SLA recomputation — it only moves the clock.

The companion test-driving capability is the **sweep tick**, also reserved to `SiteManager` and `Dispatcher`. Each invocation increments `sweep_run_index` by one, then runs the periodic-time and periodic-usage steps of plan generation described in §3.4, then recomputes `sla_breached` for every open work order at the site. A work order's `sla_breached` flag is true exactly when the site clock is strictly greater than its `sla_due_at` and its status is not in `COMPLETED`, `CLOSED`, or `CANCELLED`; otherwise it is false. The sweep tick is also the gate that controls when a `PAUSED` work order may be cancelled (see §3.7).

### 3.2. The Equipment Lifecycle

Equipment is created by a `SiteManager` who supplies `asset_tag`, `category`, `location`, `responsible_user_id`, `technical_spec`, `criticality`, `warranty_start`, `warranty_end`, and optionally an initial `usage_counter`. The `asset_tag` is unique per site. The `category` is one of `PUMP`, `COMPRESSOR`, `HVAC`, `CONVEYOR`, or `BOILER`; the `criticality` is one of `LOW`, `MEDIUM`, or `HIGH` and feeds the priority-score calculation. The `warranty_end` must be strictly after `warranty_start`, otherwise the request is rejected with `ERR_TEMPORAL_INVALID`. Newly created equipment lands in `lifecycle_status` `INSTALLED`. The `usage_counter` is monotonic non-decreasing; the equipment's owner is the user identified by `responsible_user_id`. The equipment row also carries computed fields `last_failure_at`, `last_repair_completed_at`, and `open_work_order_id`, all initially null.

A `SiteManager` may update equipment fields via the equipment patch capability with `version`, `criticality`, `location`, `responsible_user_id`, `technical_spec`, and `usage_counter`. When `criticality` changes, every open work order for that equipment has its `priority_score` and `priority` recomputed; if the priority bucket changes, `sla_due_at` is also recomputed from the new bucket and the work order's `opened_at`.

The lifecycle progresses through four manager-driven transitions plus two system-driven transitions:

- **Commissioning** advances `lifecycle_status` from `INSTALLED` to `COMMISSIONED`. The transition is rejected with `ERR_NO_ACTIVE_PLAN` unless the equipment has at least one `MaintenancePlan` whose status is `ACTIVE`, of any kind.
- **Placement in service** advances `lifecycle_status` from `COMMISSIONED` to `IN_SERVICE`. From this point onward, periodic-time plans are eligible for sweep generation; if `last_generated_at` is null on such a plan, its `next_due_at` is computed from the placement-in-service site clock plus the plan's interval (see §3.4). There are no other preconditions.
- **Entering maintenance** is a system transition that advances `lifecycle_status` from `IN_SERVICE` to `UNDER_MAINTENANCE` whenever a work order on this equipment moves from `PENDING` to `IN_PROGRESS`. The system requires `Equipment.open_work_order_id` to equal the id of the work order entering progress. While `UNDER_MAINTENANCE`, no additional work order may be opened on this equipment — any creation attempt is rejected with `ERR_EQUIPMENT_BUSY`.
- **Returning to service** is a system transition that advances `lifecycle_status` from `UNDER_MAINTENANCE` to `IN_SERVICE` whenever the open work order moves out of `IN_PROGRESS` or `PAUSED` into `COMPLETED`, `CLOSED`, or `CANCELLED`. The transition clears `Equipment.open_work_order_id`. On a `COMPLETED` event specifically, it also stamps `Equipment.last_repair_completed_at` to the current site clock.
- **Decommissioning** advances `lifecycle_status` from `IN_SERVICE` to the terminal state `DECOMMISSIONED`. It requires `Equipment.open_work_order_id` to be null, otherwise the response is `ERR_EQUIPMENT_BUSY`. As a cascade, every `ACTIVE` `MaintenancePlan` on this equipment moves to `RETIRED`, and every `PENDING` work order on this equipment moves to `CANCELLED` with `cancel_reason` set to `EQUIPMENT_DECOMMISSIONED`. Within each cancelled work order, all `RESERVED` requisitions become `CANCELLED` and replenishment is re-evaluated for each affected spare part.

### 3.3. The Plan Catalogue: Templates and Maintenance Plans

A `PlanOwner` builds the maintenance catalogue. Templates are created by submitting `code` (unique per site), `title`, `equipment_category` (one of the equipment categories from §3.2), `required_skill` (one of `MECHANICAL`, `ELECTRICAL`, `HYDRAULIC`, `HVAC_CERT`, `CONTROLS`), `estimated_minutes` (a planning estimate strictly greater than zero), and `default_priority` (one of `P1`, `P2`, `P3`, `P4`, where `P1` is highest). Templates are immutable after creation and carry no `updated_at` or `version`.

Maintenance plans are created in `DRAFT` status against a target equipment and a source template. The body identifies the plan's `kind`, which is one of four values, and the kind dictates which additional fields are required:

- `PERIODIC_TIME` requires `interval_days` (strictly positive). The `next_due_at` for a periodic-time plan is computed from `last_generated_at + interval_days * 86400 seconds`; if `last_generated_at` is null, it is computed from the activation-time site clock plus the same offset.
- `PERIODIC_USAGE` requires `interval_usage` (strictly positive, in usage units between consecutive work orders).
- `TRIGGER_ALARM` requires `alarm_code` (matched against `AlarmEvent.alarm_code`).
- `TRIGGER_THRESHOLD` requires all three of `threshold_metric`, `threshold_op`, and `threshold_value`. The `threshold_op` is one of `GTE`, `GT`, `LTE`, `LT`.

A plan body that omits any kind-required field — or supplies fields that contradict the kind — is rejected with `ERR_PLAN_KIND_FIELDS`, both on creation and on adjustment. Adjustments via the plan patch capability accept `version`, `interval_days`, `interval_usage`, `alarm_code`, `threshold_metric`, `threshold_op`, and `threshold_value`, but the `kind` itself is immutable. For a `PERIODIC_TIME` plan, an interval adjustment recomputes `next_due_at` as `(last_generated_at OR plan.created_at) + new interval_days * 86400 seconds`.

Plans hold computed fields `last_generated_at`, `last_generated_usage`, and `next_due_at`, which are populated as plan generation advances.

The plan lifecycle proceeds through `DRAFT → ACTIVE → PAUSED ↔ ACTIVE → RETIRED` (with `PAUSED → RETIRED` also allowed). Activation requires the target equipment to be in `COMMISSIONED` or `IN_SERVICE` (otherwise `ERR_EQUIPMENT_LIFECYCLE`) and all kind-required fields to be present. On activation, a `PERIODIC_TIME` plan initializes `next_due_at` to `Site.clock_now + interval_days * 86400 seconds`, and a `PERIODIC_USAGE` plan initializes `last_generated_usage` to the equipment's current `usage_counter`; non-time, non-usage kinds leave `next_due_at` null and `last_generated_usage` null. Pausing makes the plan ineligible for further sweep generation; existing work orders that originated from the plan are unaffected. Resuming a paused `PERIODIC_TIME` plan re-evaluates `next_due_at` to the maximum of `last_generated_at + interval_days * 86400 seconds` and the current site clock; a paused `PERIODIC_USAGE` plan or trigger plan undergoes no schedule change on resume. Retiring is terminal and may also be triggered by the equipment-decommission cascade described in §3.2; either path reaches the same `RETIRED` state and the plan no longer generates work orders.

### 3.4. Plan Generation, Alarms, and the Selector Pool

The plan-generation routine produces work orders in four ordered steps. Steps 1 and 2 run inside the sweep tick capability described in §3.1; Steps 3 and 4 run inside the alarm-emission test-driving capability and never inside the sweep tick.

**Step 1 — periodic-time plans.** All `ACTIVE` plans of `kind` `PERIODIC_TIME` are considered, ordered by `next_due_at` ascending, with `id` ascending as a tie-break. For each, if `Site.clock_now` is greater than or equal to the plan's `next_due_at`, the target `Equipment.open_work_order_id` is null, and `Equipment.lifecycle_status` is in `COMMISSIONED` or `IN_SERVICE`, then a new work order is created with `source` `PLAN_PERIODIC`, the plan's `last_generated_at` is set to the current site clock, and the plan's `next_due_at` is advanced to `Site.clock_now + interval_days * 86400 seconds`.

**Step 2 — periodic-usage plans.** All `ACTIVE` plans of `kind` `PERIODIC_USAGE` are considered, ordered by `id` ascending. For each, the baseline is `last_generated_usage` if non-null, otherwise zero. If the equipment's `usage_counter` minus the baseline is at least the plan's `interval_usage`, the equipment's `open_work_order_id` is null, and the equipment's lifecycle is `COMMISSIONED` or `IN_SERVICE`, a new work order is created with `source` `PLAN_PERIODIC`, the plan's `last_generated_usage` is set to the equipment's current `usage_counter`, and the plan's `last_generated_at` is set to the current site clock.

**Step 3 — trigger-alarm plans.** Whenever an `AlarmEvent` is emitted with an `alarm_code`, all `ACTIVE` plans of `kind` `TRIGGER_ALARM` for the same equipment whose `alarm_code` matches the event are considered. If the equipment's `open_work_order_id` is null, a new work order is created with `source` `ALARM`, and the alarm event's `generated_work_order_id` is stamped with the new work order's id. If no plan matches, the alarm still records but `generated_work_order_id` remains null.

**Step 4 — trigger-threshold plans.** For the same alarm event, all `ACTIVE` plans of `kind` `TRIGGER_THRESHOLD` for the same equipment whose `threshold_metric` equals the alarm's `alarm_code` are considered. The body's `metric_value` is compared against `threshold_value` using `threshold_op` — that is, "greater than or equal to" for `GTE`, strictly greater than for `GT`, "less than or equal to" for `LTE`, and strictly less than for `LT`. If the predicate holds and `open_work_order_id` is null, a new work order is created with `source` `ALARM`.

Across all four steps, at most one work order is created per equipment per sweep-tick invocation; if multiple plans for one equipment qualify, the first plan in the ordering above wins and the rest defer to the next tick. The `AlarmEvent` body supplies `alarm_code`, `severity` (`INFO`, `WARN`, or `CRITICAL`), and an optional `metric_value`; `emitted_at` is system-set to the current site clock. A client that supplies its own `emitted_at` is rejected with `ERR_TEMPORAL_INVALID`.

For every work-order creation — whether via plan generation, alarm, or the ad-hoc capability — the system runs the **technician selector** to pick `assigned_technician_id`. The selector considers the candidate set of `Technician` rows whose `status` is `ACTIVE`, whose `skills` include the `WorkOrder.required_skill` copied from the source template, and whose `site_id` equals the work order's site. Candidates are ranked by `open_load` ascending (the count of work orders assigned to that technician with status in `PENDING`, `IN_PROGRESS`, or `PAUSED`), with `created_at` ascending as the secondary key, and lexicographic ascending order of `id` as the final tie-break. If the candidate set is empty, the work order is still created in `PENDING` state but `assigned_technician_id` remains null; it is **not** rejected. The same selector runs on the reassign capability when no `new_technician_id` is provided in the body.

When a work order is created, `source` is set to `PLAN_PERIODIC` for periodic generation, `ALARM` for alarm-driven generation, `PLAN_TRIGGER` for trigger-plan generation, or `AD_HOC` for the manual-create capability. The work order's `required_skill` and `estimated_minutes` are copied from `TaskTemplate.required_skill` and `TaskTemplate.estimated_minutes` at creation. Equipment whose `lifecycle_status` is not in `COMMISSIONED` or `IN_SERVICE` cannot host new work and produces `ERR_EQUIPMENT_LIFECYCLE`; equipment that already has an open work order cannot host a new one and produces `ERR_EQUIPMENT_BUSY`.

### 3.5. Priority Scoring and SLA

Every newly created work order receives an integer `priority_score` and a derived `priority` bucket. The score is computed from three weights and one bonus, all integer arithmetic. The criticality weight is 1 when `Equipment.criticality` is `LOW`, 2 when `MEDIUM`, and 4 when `HIGH`. The template-priority weight is 8 when `TaskTemplate.default_priority` is `P1`, 4 when `P2`, 2 when `P3`, and 1 when `P4`. The source bonus is 4 when `WorkOrder.source` is `ALARM`, 2 when `PLAN_TRIGGER`, 1 when `PLAN_PERIODIC`, and 1 when `AD_HOC`. The `priority_score` is the criticality weight multiplied by the template-priority weight, then added to the source bonus.

The bucket is read from the score using inclusive lower bounds: a `priority_score` of at least 30 is `P1`; a score of at least 20 but strictly less than 30 is `P2`; a score of at least 8 but strictly less than 20 is `P3`; and a score strictly less than 8 is `P4`. The score is recomputed when a dispatcher uses the reassign-priority capability, when `Equipment.criticality` changes via the equipment patch capability, and at work-order creation. The `priority_score` is itself an integer, and the bucket boundaries are exact integer comparisons.

The SLA-due timestamp is then derived from the bucket. The SLA in minutes is 240 for `P1`, 480 for `P2`, 1440 for `P3`, and 4320 for `P4`. Note that the `P3` SLA is one full day (1440 minutes), and the `P4` SLA is three full days (4320 minutes). The work order's `sla_due_at` is its `opened_at` plus the SLA in seconds (the SLA in minutes multiplied by 60). The `sla_due_at` is pinned at creation and is recomputed on any priority change. The `sla_breached` flag described in §3.1 is the boolean derived during the sweep tick: true when `Site.clock_now` is strictly greater than `sla_due_at` and the status is not in `COMPLETED`, `CLOSED`, or `CANCELLED`; otherwise false.

If a `Dispatcher` invokes the ad-hoc create capability with the optional `explicit_priority`, the implementation may use that as the bucket; otherwise the bucket is read off the score. The optional `preferred_technician_id` short-circuits the technician selector if the preferred technician matches selector eligibility (`ACTIVE` status, skill match, same site); otherwise the selector runs as usual.

### 3.6. The Work-Order Workflow

A `Technician` operates a work order. The lifecycle is `PENDING → IN_PROGRESS → (PAUSED ↔ IN_PROGRESS) → COMPLETED → CLOSED`, with `CANCELLED` reachable from `PENDING` or `PAUSED`. Every transition out of `PENDING` initiated by a technician requires `X-User-ID` to equal `WorkOrder.assigned_technician_id`; a mismatch produces `ERR_FORBIDDEN_NOT_OWNER`. Every transition also requires the target work order to be in the correct prior state — a wrong state yields `ERR_INVALID_STATE`.

**Starting** a work order moves it from `PENDING` to `IN_PROGRESS`. The transition is rejected if the equipment's `lifecycle_status` is not in `IN_SERVICE` or `COMMISSIONED` (`ERR_EQUIPMENT_LIFECYCLE`) or if the calling technician is not `ACTIVE`. On a successful start, `WorkOrder.started_at` is set to the current site clock if it was null, the equipment transitions from `IN_SERVICE` to `UNDER_MAINTENANCE`, `Equipment.open_work_order_id` is pinned to the work order's id, and an audit entry with `action` `WORK_ORDER_STATE_CHANGE` is appended.

**Pausing** moves the work order from `IN_PROGRESS` to `PAUSED`. The body must specify `pause_reason` from `WAIT_PARTS`, `WAIT_VENDOR`, or `WAIT_INFO`. On a successful pause, the elapsed minutes since the most recent `IN_PROGRESS` entry — that is, the floor of `(Site.clock_now − last IN_PROGRESS entry) / 60` — are added to `WorkOrder.total_active_minutes`, the `pause_reason` is stored, and an audit entry is appended.

**Resuming** moves the work order from `PAUSED` to `IN_PROGRESS`. If the prior `pause_reason` was `WAIT_PARTS`, then at least one `Requisition` for this work order must be in status `ISSUED`; if not, the resume is rejected with `ERR_PARTS_NOT_ISSUED`. On a successful resume, the active-minute timer restarts from the current site clock, and `pause_reason` is cleared to null.

**Completing** moves the work order from `IN_PROGRESS` to `COMPLETED`. The body must include the full repair-record payload — `fault_description`, `root_cause`, `repair_actions`, `working_minutes` (strictly greater than zero), `before_evidence_url`, and `after_evidence_url`. Completion is rejected with `ERR_REQUISITIONS_PENDING` if any `Requisition` for this work order is still in status `RESERVED`; in other words, every requisition must be in `ISSUED`, `RETURNED`, or `CANCELLED` at completion time. On a successful completion: the elapsed `IN_PROGRESS` minutes are added to `total_active_minutes`; a new `RepairRecord` is created with the body fields, and its `parts_replaced` array is built as a snapshot of every `ISSUED` requisition with `qty_used` equal to `qty − returned_qty` (plus the underlying `requisition_id`, `part_id`, `qty_used`, and `unit_cost_cents`); `WorkOrder.parts_cost_cents` is computed via the parts-cost calculation in §3.8; `WorkOrder.completed_at` is stamped with the current site clock; the equipment transitions from `UNDER_MAINTENANCE` to `IN_SERVICE`, `Equipment.open_work_order_id` is cleared to null, and `Equipment.last_repair_completed_at` is set to the current site clock; the source plan's `last_generated_at` and `last_generated_usage` are not touched (those are set at generation, not completion); and an audit entry is appended.

**Acceptance** moves the work order from `COMPLETED` to `CLOSED` and may only be performed by a `SiteManager` whose `X-User-ID` equals the equipment's `responsible_user_id` (otherwise `ERR_FORBIDDEN_NOT_OWNER`). The associated `RepairRecord` must already exist and must carry both a non-empty `before_evidence_url` and a non-empty `after_evidence_url`; if either is missing or empty, the acceptance is rejected with `ERR_EVIDENCE_MISSING`. On a successful acceptance, `RepairRecord.acceptance_user_id` is set to `X-User-ID`, `RepairRecord.acceptance_at` is set to the current site clock, `WorkOrder.closed_at` is set to the current site clock, and an audit entry is appended.

### 3.7. Reassignment, Cancellation, and Concurrency Outcomes

A `Dispatcher` may **reassign** a `PENDING` work order using the reassign capability with a `new_technician_id`. The new technician must have `status` `ACTIVE` and `skills` that include `WorkOrder.required_skill`; a skill-set mismatch yields `ERR_SKILL_MISMATCH`. On a successful reassign, `WorkOrder.assigned_technician_id` is replaced, `WorkOrder.reassign_count` is incremented by one only if the previous `assigned_technician_id` was non-null, and an audit entry with `action` `TECHNICIAN_ASSIGNED` is appended.

A `Dispatcher` may also **cancel** a work order with an optional `cancel_reason`. From `PENDING`, cancellation requires that no requisition for this work order is in status `ISSUED` (still-`RESERVED` requisitions are acceptable and will be released). On a successful `PENDING → CANCELLED` cancellation, all `RESERVED` requisitions move to `CANCELLED`, decreasing `SparePart.stock_reserved` by the cancelled quantity, replenishment is re-evaluated for each affected part, and an audit entry is appended. From `PAUSED`, cancellation additionally requires that the pause has lasted at least one sweep tick — that is, `sweep_run_index` has advanced by at least one since the pause; otherwise the cancellation is rejected with `ERR_PAUSE_TOO_FRESH`. The `PAUSED → CANCELLED` path also requires no requisition in status `ISSUED` (any issued requisitions must first be returned or cancelled). On a successful `PAUSED → CANCELLED` cancellation, all `RESERVED` requisitions move to `CANCELLED`, the equipment lifecycle is restored from `UNDER_MAINTENANCE` to `IN_SERVICE`, `Equipment.open_work_order_id` is cleared, and an audit entry is appended.

Several races on the work-order surface are serialized to a single winner with a precise loser response:

- **Two simultaneous create attempts on the same equipment** (a periodic-plan sweep racing an alarm-driven generation, or two ad-hoc attempts) serialize first-writer-wins on `Equipment.open_work_order_id`. The runner-up is rejected with `ERR_EQUIPMENT_BUSY` and HTTP 409.
- **Two technicians attempting to start the same `PENDING` work order** serialize first-writer-wins on `WorkOrder.status`. Exactly one start succeeds; the loser observes the order is already `IN_PROGRESS` and is rejected with `ERR_INVALID_STATE` and HTTP 409.
- **Reassign racing start on the same `PENDING` work order** serializes first-writer-wins on `WorkOrder.status` and `assigned_technician_id`. If start wins, the racing reassign sees the order is `IN_PROGRESS` and is rejected with `ERR_INVALID_STATE`. If reassign wins and the formerly-assigned technician then attempts to start, the start sees that `X-User-ID` no longer matches `assigned_technician_id` and is rejected with `ERR_FORBIDDEN_NOT_OWNER`.
- **Two simultaneous patch attempts** on `Equipment`, `MaintenancePlan`, `SparePart`, or `Technician` with stale `version` values serialize first-writer-wins on `version` (which strictly increments by one per mutation). The stale writer is rejected with `ERR_VERSION_CONFLICT` and HTTP 409.

### 3.8. Spare Parts, Requisitions, and Replenishment

A `Storekeeper` creates spare-part SKUs by submitting `sku` (unique per site), `name`, `unit_cost_cents` (non-negative integer cents), an optional initial `stock_on_hand` (non-negative integer, defaulting to zero), and `reorder_point` (non-negative integer). The replenishment evaluator runs at creation. The spare-part row exposes `stock_on_hand`, `stock_reserved` (the sum of `qty` across `RESERVED` requisitions for this part, satisfying the bound that `stock_reserved` is between 0 and `stock_on_hand`), `reorder_point`, and `replenish_pending` (a boolean, default false). The spare-part patch capability accepts `version`, `unit_cost_cents`, `reorder_point`, and `stock_delta`; a strictly positive `stock_delta` represents a replenishment delivery that increases `stock_on_hand`, after which the replenishment evaluator runs.

Requisitions are created by a `Technician` or `Storekeeper` against a work order. The body specifies `part_id` and `qty` (strictly positive); the requisition row records the owning work order's id in `work_order_id`. The reservation requires available stock, defined as `stock_on_hand − stock_reserved`, to be at least `qty`; otherwise the request is rejected with `ERR_INSUFFICIENT_AVAILABLE` and HTTP 409. On a successful reservation, the requisition starts in `RESERVED`, `stock_reserved` is increased by `qty`, and the replenishment evaluator runs. The requisition row also carries `unit_cost_cents_at_issue` (initially null) and `returned_qty` (initially zero). The `RepairRecord` produced at completion likewise records the owning `work_order_id`, and there is exactly one repair record per completed work order.

The requisition lifecycle is `RESERVED → ISSUED → RETURNED` (with the option to issue partial returns), and `RESERVED → CANCELLED` is terminal:

- **Issuing** a `RESERVED` requisition is performed by a `Storekeeper`. The work order must be in status `PENDING`, `IN_PROGRESS`, or `PAUSED`, and `SparePart.stock_on_hand` must be at least `qty`; insufficient stock is rejected with `ERR_INSUFFICIENT_STOCK`. On a successful issue, `Requisition.unit_cost_cents_at_issue` is snapshotted to the part's current `unit_cost_cents`, `stock_on_hand` decreases by `qty`, and `stock_reserved` decreases by `qty` (the reservation is released because the parts are physically issued). The replenishment evaluator then runs: if available stock (`stock_on_hand − stock_reserved`) is at most `reorder_point` and `replenish_pending` was false, `replenish_pending` is set to true and the replenishment notification described in §2.10 is emitted. An audit entry with `action` `PARTS_ISSUED` is appended.
- **Returning** an `ISSUED` requisition is also performed by a `Storekeeper` with a body `returned_qty` strictly greater than zero and at most `qty − returned_qty` — that is, the new return must not push the cumulative `returned_qty` past the original `qty`. A return outside that range is rejected with `ERR_RETURN_QTY_INVALID`. The work order must be in `IN_PROGRESS`, `PAUSED`, or `COMPLETED-but-not-yet-CLOSED`. On a successful return, `Requisition.returned_qty` is increased by the body's `returned_qty`, `SparePart.stock_on_hand` is increased by the same, the replenishment evaluator runs (if available stock now exceeds `reorder_point`, `replenish_pending` is cleared back to false), and an audit entry with `action` `PARTS_RETURNED` is appended. If the work order is already `COMPLETED`, the snapshot of `RepairRecord.parts_replaced` and `WorkOrder.parts_cost_cents` taken at completion is **final** — neither is recomputed by a post-completion return.
- **Cancelling** a `RESERVED` requisition (manually by a `Technician` or `Storekeeper`, or via cascade from a work-order cancel) decreases `stock_reserved` by `qty`, runs the replenishment evaluator, and appends an audit entry.

The replenishment evaluator works on integer comparisons only. Available stock is `stock_on_hand − stock_reserved`. When available stock is at most `reorder_point` and `replenish_pending` is currently false, `replenish_pending` is set to true and the test-fixture notification fires. When available stock is strictly greater than `reorder_point`, `replenish_pending` is auto-cleared to false. The trigger boundary is inclusive (`<=`).

The **parts-cost** calculation runs at the work-order completion transition. It walks every `Requisition` linked to the work order whose status is `ISSUED` (rows that were returned remain status `ISSUED` with non-zero `returned_qty`; cancelled rows are excluded), in `created_at` ascending order for deterministic accumulation. For each such requisition, the used quantity is the requisition's `qty` minus its `returned_qty`. The line cost in cents is the used quantity multiplied by the requisition's `unit_cost_cents_at_issue`. **Per-line, before any summation:** if the used quantity is at least 10, the line cost is replaced by the floor of itself multiplied by 0.90 (a 10% bulk discount, rounded down to the nearest cent). The work order's `parts_cost_cents` is the sum of every line cost obtained this way. The pinned variant of the calculation applies discount and floor on each line and only then sums; the alternative ordering — first sum all lines, then apply discount retroactively to lines whose used quantity was at least 10 — is **not** the canonical order and produces a different cents value on mixed-bulk requisitions; only the per-line-then-sum order is correct.

Two further concurrency outcomes apply to parts:

- **Two storekeepers issuing the same requisition concurrently** serialize first-writer-wins on `Requisition.status`. Exactly one issue succeeds; the loser sees the requisition is already `ISSUED` and is rejected with `ERR_INVALID_STATE` and HTTP 409.
- **Two issues against different requisitions on the same spare part racing past the last available unit** serialize via optimistic stock decrement; the lost decrement is rejected with `ERR_INSUFFICIENT_STOCK` and HTTP 409, since allowing both would drive `stock_on_hand` negative.

### 3.9. Reliability Analytics

The system exposes four read-only analytics queries, all reserved to `SiteManager` and `Dispatcher`. Every analytics query reads the deterministic site clock and the recorded work-order timestamps; all four exclude `PLAN_PERIODIC` and exclude `CANCELLED` work orders by virtue of the `source` filter — they consider only work orders whose `source` is in `ALARM`, `PLAN_TRIGGER`, or `AD_HOC`. Every analytics query takes its window with an inclusive lower bound `window_start` and an exclusive upper bound `window_end`. Round-half-up rules are stated in §2.8.

**Mean time to repair (MTTR).** The query takes `scope` (one of `EQUIPMENT`, `CATEGORY`, `SITE`), an optional `scope_id` (the equipment id or category value when applicable), `window_start`, `window_end`, and an optional `mode`. The eligible work orders are those whose `completed_at` is non-null and falls in `[window_start, window_end)`, whose `source` is in the failure-driven set above, and whose scope filter matches (the equipment id, the equipment's category, or the site as a whole). The default behavior — when `mode` is omitted or `active` — is the **active-minutes mean**: the result is the arithmetic mean of `total_active_minutes` over the eligible set, which excludes time spent in `PAUSED` status. When `mode` is `wallclock`, the result is the wallclock mean: the arithmetic mean of `(completed_at − started_at) / 60 seconds` over the eligible set, which includes time spent paused. Both variants are rounded half-up to two decimal places. If the eligible set is empty, the response returns `mttr_minutes` as null. The response also includes `sample_size`, the count of eligible work orders.

**Mean time between failures (MTBF).** The query takes `scope`, optional `scope_id`, `window_start`, and `window_end`. For each equipment in scope, the system orders the equipment's failure-driven completions (work orders whose `source` is in `ALARM`, `PLAN_TRIGGER`, or `AD_HOC`, whose `completed_at` is non-null and lies in `[window_start, window_end)`) by `completed_at` ascending, with `id` ascending as the tie-break. Walking that list from the second element onward, it computes each gap as the `started_at` of the current completion minus the `completed_at` of the previous completion in seconds, and keeps only those gaps that are strictly positive. The per-equipment MTBF in hours is the arithmetic mean of gaps divided by 3600 (one hour in seconds), or null when the list of kept gaps is empty. For `EQUIPMENT` scope, the result is that single equipment's MTBF. For `CATEGORY` or `SITE` scope, the result is the weighted mean across equipment, weighted by the per-equipment number of kept gaps; equipment whose gap list is empty is skipped, and if every equipment is skipped the response returns `mtbf_hours` as null. The result is rounded half-up to two decimal places. The response also includes `gap_count`, the total number of kept gaps that contributed to the result.

**Fault recurrence.** The query takes an optional `look_back_days`, which defaults to 30. For each equipment at the site, the system selects completions whose `source` is failure-driven and whose `completed_at` falls in `[Site.clock_now − look_back_days * 86400 seconds, Site.clock_now)`. The recurrence count is the number of indices (from 1 onward) where the gap from the previous completion's `completed_at` to the current completion's `started_at` is at most 7 days (`RECURRENCE_GAP_DAYS`). The recurrence rate is the recurrence count divided by the maximum of (the count of completions minus 1) and 1, ensuring the rate is zero when there are zero or one completions. The rate is rounded half-up to four decimal places. The response includes one row per equipment with `equipment_id`, `recurrence_rate`, and `completion_count`.

**Equipment availability.** The query takes a required `equipment_id`, `window_start`, `window_end`, and an optional `mode`. The window length in seconds is `window_end − window_start`. For every failure-driven work order on the equipment whose `started_at` is strictly before `window_end` and whose interval `[started_at, completed_at)` overlaps the window (where `completed_at` is null for an open work order), the contribution to downtime in seconds is `min(completed_at OR Site.clock_now, window_end) − max(started_at, window_start)`. The downtime in seconds is the sum of these contributions. The availability is `(window_seconds − downtime_seconds) / window_seconds`, rounded half-up to four decimal places. The default `mode` `provisional` allows open work orders to contribute downtime up to `Site.clock_now` (this is the **forward** variant). The `mode` `final` excludes open work orders entirely from downtime; only `COMPLETED` work orders contribute (this is the **final** variant). The response carries `availability` and `downtime_seconds` (an integer).

### 3.10. Audit Browsing

The audit list is reserved to `SiteManager` and `Dispatcher`. It supports filtering by `action` and `target_id`, plus `limit` and `offset`. Sort order follows §2.3 — by `created_at` ascending. Each entry exposes `actor_role`, `actor_user_id`, `action`, `target_id`, `from_value`, `to_value`, and `occurred_at`.

## 4. Endpoint Definitions

For each endpoint listed below, a successful creation returns HTTP 201 and a successful read or modification returns HTTP 200, except where the table description states otherwise. The body fields, side effects, and validation responses for each endpoint are derived from the workflows in §3 — this table only summarizes the surface.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /sites | Create a Site | SiteManager |
| GET | /sites/:site_id | Get a Site | Any |
| POST | /sites/:site_id/clock/advance | Advance the Site logical clock by N seconds | SiteManager, Dispatcher |
| POST | /sites/:site_id/sweep/run | Increment sweep tick; run periodic plan generation; recompute SLA breach | SiteManager, Dispatcher |
| POST | /sites/:site_id/equipment | Create equipment | SiteManager |
| GET | /sites/:site_id/equipment/:equipment_id | Get equipment | Any |
| PATCH | /sites/:site_id/equipment/:equipment_id | Update equipment fields | SiteManager |
| POST | /sites/:site_id/equipment/:equipment_id/commission | Transition equipment to COMMISSIONED | SiteManager |
| POST | /sites/:site_id/equipment/:equipment_id/place-in-service | Transition equipment to IN_SERVICE | SiteManager |
| POST | /sites/:site_id/equipment/:equipment_id/decommission | Transition equipment to DECOMMISSIONED with cascades | SiteManager |
| POST | /sites/:site_id/equipment/:equipment_id/alarms | Emit an alarm event; runs trigger plan generation | SiteManager, Dispatcher |
| POST | /sites/:site_id/templates | Create a task template | PlanOwner |
| GET | /sites/:site_id/templates/:template_id | Get a task template | Any |
| POST | /sites/:site_id/plans | Create a maintenance plan in DRAFT | PlanOwner |
| GET | /sites/:site_id/plans/:plan_id | Get a maintenance plan | Any |
| PATCH | /sites/:site_id/plans/:plan_id | Adjust plan body (kind is immutable) | PlanOwner |
| POST | /sites/:site_id/plans/:plan_id/activate | Transition plan DRAFT to ACTIVE | PlanOwner |
| POST | /sites/:site_id/plans/:plan_id/pause | Transition plan ACTIVE to PAUSED | PlanOwner |
| POST | /sites/:site_id/plans/:plan_id/resume | Transition plan PAUSED to ACTIVE | PlanOwner |
| POST | /sites/:site_id/plans/:plan_id/retire | Transition plan to RETIRED | PlanOwner |
| POST | /sites/:site_id/spare-parts | Create a spare-part SKU | Storekeeper |
| GET | /sites/:site_id/spare-parts/:part_id | Get a spare part | Any |
| PATCH | /sites/:site_id/spare-parts/:part_id | Adjust unit_cost_cents, reorder_point, or stock_delta | Storekeeper |
| POST | /sites/:site_id/technicians | Create a technician | SiteManager |
| GET | /sites/:site_id/technicians/:tech_id | Get a technician | Any |
| PATCH | /sites/:site_id/technicians/:tech_id | Update skills or status | SiteManager |
| POST | /sites/:site_id/work-orders | Create an ad-hoc WorkOrder; runs technician selector | Dispatcher, SiteManager |
| GET | /sites/:site_id/work-orders/:wo_id | Get a WorkOrder | Any |
| GET | /sites/:site_id/work-orders | List WorkOrders with filtering and pagination | Any |
| POST | /sites/:site_id/work-orders/:wo_id/reassign | Reassign a PENDING WorkOrder | Dispatcher |
| POST | /sites/:site_id/work-orders/:wo_id/start | Technician starts the WorkOrder | Technician |
| POST | /sites/:site_id/work-orders/:wo_id/pause | Pause an IN_PROGRESS WorkOrder | Technician |
| POST | /sites/:site_id/work-orders/:wo_id/resume | Resume a PAUSED WorkOrder | Technician |
| POST | /sites/:site_id/work-orders/:wo_id/complete | Complete the WorkOrder; submits the RepairRecord | Technician |
| POST | /sites/:site_id/work-orders/:wo_id/accept | Accept the completed work; transitions to CLOSED | SiteManager |
| POST | /sites/:site_id/work-orders/:wo_id/cancel | Cancel a PENDING or PAUSED WorkOrder | Dispatcher |
| POST | /sites/:site_id/work-orders/:wo_id/requisitions | Reserve parts against a WorkOrder | Technician, Storekeeper |
| POST | /sites/:site_id/work-orders/:wo_id/requisitions/:req_id/issue | Issue a RESERVED requisition | Storekeeper |
| POST | /sites/:site_id/work-orders/:wo_id/requisitions/:req_id/return | Return some/all of an ISSUED requisition | Storekeeper |
| POST | /sites/:site_id/work-orders/:wo_id/requisitions/:req_id/cancel | Cancel a RESERVED requisition | Technician, Storekeeper |
| GET | /sites/:site_id/work-orders/:wo_id/repair-record | Get the RepairRecord for a completed WorkOrder | Any |
| GET | /sites/:site_id/audit | List audit entries with filtering and pagination | SiteManager, Dispatcher |
| GET | /sites/:site_id/analytics/mttr | MTTR by scope over a window | SiteManager, Dispatcher |
| GET | /sites/:site_id/analytics/mtbf | MTBF by scope over a window | SiteManager, Dispatcher |
| GET | /sites/:site_id/analytics/fault-recurrence | Fault-recurrence rate per equipment over the look-back window | SiteManager, Dispatcher |
| GET | /sites/:site_id/analytics/availability | Equipment availability over a window | SiteManager, Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_BAD_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_FORBIDDEN_NOT_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_EQUIPMENT_LIFECYCLE | 409 |
| ERR_EQUIPMENT_BUSY | 409 |
| ERR_NO_ACTIVE_PLAN | 409 |
| ERR_PAUSE_TOO_FRESH | 409 |
| ERR_REQUISITIONS_PENDING | 409 |
| ERR_PARTS_NOT_ISSUED | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_INSUFFICIENT_AVAILABLE | 409 |
| ERR_PLAN_KIND_FIELDS | 422 |
| ERR_CROSS_SITE_REFERENCE | 422 |
| ERR_EVIDENCE_MISSING | 422 |
| ERR_SKILL_MISMATCH | 422 |
| ERR_RETURN_QTY_INVALID | 422 |
| ERR_TEMPORAL_INVALID | 422 |
