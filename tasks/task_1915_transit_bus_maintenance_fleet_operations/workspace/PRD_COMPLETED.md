# Transit Bus Maintenance API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Transit Bus Maintenance & Fleet Operations API operated by a municipal transit agency. The system governs the full maintenance lifecycle of the agency's revenue bus fleet: preventive maintenance interval tracking by mileage and calendar, operator-initiated defect reporting with road-call response, parts inventory with rebuildable-core exchange accounting, fleet availability and spare-ratio management, daily mileage and fuel logging with anomaly detection, OEM campaign administration, warranty recovery, mechanic certification and shift coverage, and mid-life overhaul and replacement planning.

A distinguishing feature of this API is that operational behavior is gated by a continuously recomputed **fleet posture** derived from the spare ratio. When the proportion of available buses falls below defined thresholds, the system automatically freezes lower-priority work so that emergency and urgent repairs can absorb scarce shop capacity. A second distinguishing feature is the strict separation of duties: the mechanic who leads a work order may not certify its quality, and the clerk who submits a warranty claim may not post the cash recovery against it. The system also maintains a logical clock so that all time-derived transitions (deferral expiry, core aging, certification expiry, shift locking, posture recompute) occur only inside a daily epoch sweep, never spontaneously.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the operational role. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized set is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes six roles: `FleetManager`, `MaintenanceSupervisor`, `Mechanic`, `Operator`, `PartsClerk`, and `WarrantyClerk`.

Of these, only `Mechanic` is **entity-backed**: when `X-User-Role` is `Mechanic`, `X-User-ID` is the `id` of the acting `Mechanic` record. Ownership checks that compare the caller to a mechanic — for example the labor-entry rule that only the work order's lead may post hours, or the road-call rule that only the dispatched mechanic may report arrival or clear — compare the relevant foreign key on the resource directly against `X-User-ID`.

The remaining five roles are **opaque**: when `X-User-Role` is `FleetManager`, `MaintenanceSupervisor`, `Operator`, `PartsClerk`, or `WarrantyClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a transition is specified to do so (for example, `reported_by` on a `DefectReport`, `submitted_by_user_id` on a `WarrantyClaim`, or `recovered_by_user_id` when a `FleetManager` posts recovery), but it never compares the identifier to any entity's `id` field. Segregation-of-duties checks for QA certification and recovery posting compare `X-User-ID` against these recorded opaque values rather than against an entity `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It reads the logical clock (§2.5), never the wall clock.
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

For endpoints that return lists of resources, pagination is controlled by two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, has a minimum of 1, and has a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Out-of-range values are clamped rather than rejected: a `limit` below 1 is treated as 1 and above 100 as 100, and a negative `offset` as 0; a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties (common under the logical clock) broken by insertion order. List endpoints also accept exact-match query filters on their natural foreign-key and status fields (for example `bus_id`, `status`, `stock_status`); unrecognized query parameters are ignored. Every paginated list response includes the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource in the system — `Bus`, `PMPolicy`, `Mechanic`, `MechanicCertification`, `Shift`, `ShiftAssignment`, `Part`, `WorkOrder`, `WorkOrderPartLine`, `DefectReport`, `Campaign`, `MileageFuelLog`, `EmissionsInspection`, `WarrantyClaim`, and `FleetReplacementPlan` — carries a standard set of system-managed fields:

- **`id`** (string): a server-minted UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first persisted. All resource timestamps read the logical clock (§2.5), never the wall clock, so resources persisted between clock movements can share identical `created_at` values.
- **`updated_at`** (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version`** (integer): a system-managed integer starting at 1 and incremented on every mutation. This is the field referenced by optimistic concurrency checks.

Any mutation to a resource — including changes to derived or computed fields such as a bus's `availability_status`, a part's `quantity_on_hand`, or a work order's `labor_total_cents` — counts as a mutation for purposes of `updated_at` and `version`. Within a single request, each affected resource's `version` is incremented at most once no matter how many times it was mutated, and only when the request succeeds; a rejected request increments no versions.

### 2.5. The Logical Clock and the Daily Epoch Sweep

The system keeps a logical clock rather than relying on wall-clock time. At server startup, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A `FleetManager` may set the clock to a supplied `to_iso8601` ISO 8601 UTC instant via a clock-set capability. Setting the clock does not by itself fire any time-derived transition. The clock may be set to any instant, forward or backward; the success response carries the resulting reading as `current_utc`.

All time-derived transitions — deferral expiry on defects, core aging on part lines, certification expiry recompute, emissions certificate expiry grounding, shift locking, and the fleet-posture recompute that follows — fire only inside the daily epoch sweep, which is invoked by a `FleetManager` calling the epoch endpoint. The sweep returns a summary including `epoch_index`, the resulting `posture`, and counters `defects_reopened`, `cores_aged`, `certifications_expired`, and `buses_grounded`. `epoch_index` is 1-based: it starts at 0 before any sweep and each sweep increments it, so the first sweep returns 1. Each counter counts only the transitions effected by that sweep: `defects_reopened` counts `DEFERRED` defects returned to `OPEN`; `cores_aged` counts part lines whose `core_status` changed (`CORE_PENDING` to `CORE_LATE`, `CORE_LATE` to `CORE_REJECTED`, or `CORE_PENDING` directly to `CORE_REJECTED` when the line is already more than 15 days past due); `certifications_expired` counts certifications that became `EXPIRED`; `buses_grounded` counts buses newly given the `EMISSIONS` hold (a bus already carrying that hold is not counted). Because time-derived transitions are confined to the sweep, a client that never calls the epoch endpoint will observe a stable world even as the logical clock advances.

### 2.6. Fleet Posture and Pull-Out Readiness

Fleet posture is recomputed on every mutation that changes any bus's `availability_status` or `service_status` — work order start, close, and cancel; defect create, resolve, and withdraw; emissions inspection fail or pass; retire; and the epoch cert-grounding sweep. Posture classifies the fleet into one of three tiers, `GREEN`, `YELLOW`, or `RED`, and gates what new work may be opened.

Posture is derived from two counts over buses whose `service_status` is not `RETIRED`. The **active count** is the number of buses whose `service_status` is `ACTIVE` or `OVERHAUL_HOLD`. The **available count** is the number of those buses whose `availability_status` is additionally `AVAILABLE`. If the active count is zero, the fleet is treated as vacuously healthy: the spare ratio is reported as exactly 1.0 and the posture is `GREEN`. Otherwise, the **spare ratio** is the available count divided by the active count, rounded half-up to 4 decimal places. The posture tier is then assigned by comparing the spare ratio to two thresholds: `GREEN` when the spare ratio is at least 0.20, `RED` when the spare ratio is below 0.15, and `YELLOW` in between (at least 0.15 and strictly below 0.20).

Independently of the tier, the system tracks **pull-out readiness** for morning service. The pull-out minimum is the ceiling of 0.80 multiplied by the active count — so with an active count of 10 the minimum is 8, and with an active count of 11 the minimum is 9. The fleet is pull-out ready when the available count is greater than or equal to that minimum.

The current posture is exposed by a computed read returning `active_buses`, `available_buses`, `spare_ratio`, `posture`, `pull_out_minimum`, and `pull_out_ready`.

Posture has teeth. When the posture transitions into `RED`, every work order currently in `SCHEDULED` whose `priority` is `ROUTINE` or `ELECTIVE` automatically transitions to `BLOCKED` fleet-wide; `EMERGENCY` and `URGENT` work orders are never frozen by posture. When posture recovers out of `RED` (to either `YELLOW` or `GREEN`), every `BLOCKED` work order is restored to `SCHEDULED`. Independently of the freeze cascade, attempting to create a new work order is also gated by posture (see §3.3): under `YELLOW`, `ELECTIVE` work orders are rejected with `ERR_FLEET_POSTURE_YELLOW`; under `RED`, both `ELECTIVE` and `ROUTINE` work orders are rejected with `ERR_FLEET_POSTURE_RED`.

### 2.7. Bus Availability Derivation and Hold Reasons

A bus's `availability_status` is never set directly by a client. It is recomputed automatically on every mutation of a work order, defect report, emissions inspection, or retirement affecting the bus. The derivation consults, in order of precedence from highest to lowest: `OUT_OF_SERVICE` when the bus's `service_status` is `RETIRED`; else `IN_SHOP` when any work order exists for the bus in one of the statuses `IN_PROGRESS`, `AWAITING_PARTS`, `PENDING_QA`, or `REOPENED`; else `HELD` when the bus's `hold_reasons` set is non-empty; else `AVAILABLE`.

The `hold_reasons` field is a maintained set drawn from `SAFETY`, `EMISSIONS`, `ROAD_CALL`, and `TOWED`. `SAFETY` is added when a `SAFETY_CRITICAL` defect is created and removed when that defect is resolved or withdrawn. `EMISSIONS` is added by a `FAIL` emissions inspection or by the epoch sweep's certificate-expiry grounding, and removed by a subsequent `PASS` retest. `ROAD_CALL` is added on road-call dispatch and removed when the road call is cleared either fixed-on-scene or towed. `TOWED` is added when a road call is cleared towed-in (replacing `ROAD_CALL`) and removed when the underlying defect is resolved, either manually or by the linked work order closing.

### 2.8. Monetary Precision and Rounding Discipline

All monetary values are integer cents. Ratios and scores that are not cents are kept as decimal numbers with the precision each calculation rule specifies; where a percentage is reported (such as `progress_pct`), it is rounded half-up to 2 decimal places; where a unitless score is reported (such as `spare_ratio` or a replacement `score`), it is rounded half-up to 4 decimal places.

Two specific rounding rules deserve emphasis because they are common sources of subtle bugs. First, labor cost is rounded **per entry, before summation**: each labor entry's amount is individually rounded half-up to the nearest cent, and only then are the per-entry amounts summed to form `labor_total_cents`. Three half-hour `NIGHT` entries therefore contribute three times the rounding of one half-hour entry, which is not the same as rounding one 1.5-hour total. Second, the late core-credit tier and the warranty claim's final amount each apply a single round-half-up at the end of the calculation; intermediate products are not pre-rounded. Integer arithmetic elsewhere (parts totals, for example) needs no rounding.

### 2.9. Optimistic Concurrency Control

Two write endpoints are protected by optimistic concurrency control against a parent entity's version. Both are create operations, because each new resource derives its cost or scope basis from the parent's current state.

When creating a work order, the request must carry `expected_bus_version`, set to the `version` of the target `Bus` as the client last observed it. If the bus's `version` has since advanced — because, for example, another writer has opened a work order against the same bus or posted an odometer log that advanced the bus — the create is rejected with `ERR_STALE_BUS_VERSION` (HTTP 412). When creating a warranty claim, the request must carry `expected_work_order_version`, set to the `version` of the target `WorkOrder` as the client last observed it. A mismatch with the work order's current `version` is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), preventing a claim from being built on a labor or parts basis the client has not seen. Endpoints not listed here do not accept a version field and are processed without an OCC check.

### 2.10. Validation Ordering

When a single request triggers multiple validation rules, the system evaluates them in a deterministic priority order. A failed earlier check short-circuits the request; the corresponding `error_id` is what the client observes, even if a later check would also have failed.

The band order is: authentication, then authorization and ownership, then existence of path and body references, then schema/format, then state-machine legality, then optimistic concurrency, then safety (certification, segregation-of-duties, safety-defect handling, on-shift dispatch), then referential uniqueness, then temporal windows, then business constraint, then fiscal. In practical terms this means, for example, that a missing header (`ERR_UNAUTHENTICATED`) is reported before an unknown path id (`ERR_NOT_FOUND`), which in turn is reported before a malformed enum (`ERR_VALIDATION`), which is reported before an illegal state transition (`ERR_INVALID_STATE`), which is reported before an OCC stale-version rejection (`ERR_STALE_BUS_VERSION` or `ERR_STALE_WORK_ORDER_VERSION`), which is reported before a missing certification (`ERR_CERT_REQUIRED`), and so on.

State-machine legality itself has two tiers. A transition attempted against a resource already in a terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) — every transition out of a terminal state is forbidden. A transition attempted against a resource in a non-terminal state that nonetheless is not a valid from-state for that transition is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 2.11. Nested Resource Retrieval

For any endpoint whose path contains multiple resource identifiers (for example a specific part line under a specific work order), identifiers are validated left to right. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource, before any later identifier is consulted. The same rule applies to foreign-key references carried in the request body — `bus_id`, `part_id`, `work_order_id`, `campaign_id`, `defect_report_id`, `mechanic_id`, and `new_part_id` must each resolve to an existing record.

### 2.12. Segregation of Duties

Two segregation-of-duties rules are enforced independently of role-based access.

A mechanic may not certify the quality of work they led. On both the certify and reject quality-assurance transitions of a work order, the caller's `X-User-ID` must not equal the work order's `lead_mechanic_id`; a violation is rejected with `ERR_SOD_QA_SELF_CERTIFY` (HTTP 403). Separately, a warranty clerk may not post the cash recovery against a claim they themselves submitted. On the post-recovery transition of a warranty claim, the caller's `X-User-ID` must not equal the claim's `submitted_by_user_id`; a violation is rejected with `ERR_SOD_RECOVERY_SELF_APPROVAL` (HTTP 403).

## 3. Business Logic & Workflows

This section describes the operational behavior of the system as a set of business workflows. It deliberately spreads rules for any single endpoint across several subsections so that the specification reads as domain narrative rather than as a schema dump.

### 3.1. Fleet Registry and the Bus Lifecycle

The fleet is anchored by the **Bus** aggregate. A `FleetManager` registers a bus by providing its `fleet_number` and `vin` (both descriptive identifiers; their uniqueness is not enforced and duplicate values are accepted), `model_year`, the `in_service_date` on which the bus entered revenue service, and an `initial_odometer_miles` reading; odometer values must be non-negative throughout the system. Registration also captures the financial and warranty basis for the bus: `replacement_cost_cents` (the new-bus replacement cost basis used both by replacement scoring and by the overhaul cap), `base_warranty_expiry_miles` and `base_warranty_expiry_date` (the OEM base-warranty mileage ceiling and calendar expiry), and `overhaul_interval_miles` (the mid-life overhaul interval). Extended-warranty coverage is optional and is described by `extended_warranty_limit_miles` and `extended_warranty_limit_months` when present. At registration the bus's `odometer_miles` is seeded from `initial_odometer_miles`, its `service_status` is set to `ACTIVE`, its `availability_status` to `AVAILABLE`, its `last_overhaul_miles` to 0, its `last_pm_a_miles`, `last_pm_b_miles`, and `last_pm_c_miles` to 0, and `last_pm_a_date`, `last_pm_b_date`, and `last_pm_c_date` to `in_service_date`.

A bus evolves along two independent dimensions. The **lifecycle dimension**, tracked by `service_status`, moves from `ACTIVE` to `OVERHAUL_HOLD` to `RETIRED`. The **availability dimension**, tracked by `availability_status` and derived per §2.7, moves among `AVAILABLE`, `IN_SHOP`, `HELD`, and `OUT_OF_SERVICE`. The two dimensions interact in only one hard-wired way: retiring a bus forces its `availability_status` to `OUT_OF_SERVICE` and clears `hold_reasons`.

A `FleetManager` retires a bus by invoking the retire capability, optionally recording a `retirement_reason`. Retirement is blocked while any work order for the bus is in a non-terminal state (`ERR_OPEN_WORK_ORDERS_EXIST`); because `DRAFT` and `BLOCKED` work orders are themselves non-terminal, this guard fires first and the auto-cancellation of `DRAFT` or `BLOCKED` work orders with `cancel_reason` set to `BUS_RETIRED` is unreachable in practice. On retirement, the bus's `service_status` becomes `RETIRED`, its `availability_status` becomes `OUT_OF_SERVICE`, and its `hold_reasons` are cleared. Because retirement reduces both the active count and (potentially) the available count, the fleet posture is recomputed; if that recomputation lifts the fleet out of `RED`, other buses' `BLOCKED` work orders may auto-restore to `SCHEDULED`.

A bus's total maintenance exposure is accumulated in `total_maintenance_cost_cents`, which is increased by the closing `total_cost_cents` of each work order as it closes.

### 3.2. Preventive Maintenance Policy and Due-Status Projection

Preventive maintenance intervals are governed by a singleton active **PMPolicy**. A `FleetManager` creates a policy with five numbers: `level_a_interval_miles`, `level_b_interval_miles`, `level_c_interval_miles`, `tolerance_miles`, and `calendar_interval_days`. The three mileage intervals must nest as positive multiples — `level_b_interval_miles` must be a positive multiple of `level_a_interval_miles`, and `level_c_interval_miles` a positive multiple of `level_b_interval_miles` — and `tolerance_miles` must be non-negative and strictly less than `level_a_interval_miles`. A policy failing any of these is rejected with `ERR_PM_POLICY_INVALID`. A newly created policy becomes `ACTIVE` and supersedes whatever policy was previously `ACTIVE`, moving it to `SUPERSEDED`. Superseding triggers a recompute of every `ACTIVE` bus's `pm_due_status` against the new policy.

A bus's `pm_due_status` is recomputed at bus registration, on every odometer change (posting or voiding a mileage log), on every work-order close of a PM type, on policy supersede, and during the epoch sweep (the sweep recomputes every non-`RETIRED` bus). If there is no `ACTIVE` policy, every bus's `pm_due_status` is `CURRENT`. Otherwise the system computes a status for each of the three levels A, B, and C and takes the worst. For a level L with mileage interval I, let `miles_since_L` be the bus's current `odometer_miles` minus the corresponding last-PM mileage field (`last_pm_a_miles`, `last_pm_b_miles`, or `last_pm_c_miles`), and let `days_since_L` be the whole-day difference between the logical clock date and the corresponding last-PM date. The **mileage status** for level L is: `CURRENT` when the remaining miles (I minus `miles_since_L`) are strictly greater than `tolerance_miles`; `DUE_SOON` when remaining miles are between 1 and `tolerance_miles` inclusive; `DUE` when remaining miles are exactly zero; and `OVERDUE` when remaining miles are negative. The **calendar status** for level L is computed the same way against `calendar_interval_days`, but with a fixed 14-day warning window in place of `tolerance_miles`: `CURRENT` when more than 14 days remain, `DUE_SOON` when between 1 and 14 days remain inclusive, `DUE` when exactly zero days remain, and `OVERDUE` when negative. The level's status is the worse of its mileage and calendar status under the ordering `CURRENT < DUE_SOON < DUE < OVERDUE`. The bus's `pm_due_status` is the worst of the three level statuses, and `next_pm_level` is the highest level (C preferred over B preferred over A) whose level status is not `CURRENT`, or A when all three are `CURRENT`.

The PM nesting rule determines how the per-level last-PM fields are maintained. When a PM work order closes, the closing odometer and `closed_date` reset a nested subset of fields: a `PM_C` close resets all three levels; a `PM_B` close resets A and B; a `PM_A` close resets A only. In each case the reset writes `last_pm_<level>_miles` to the bus's odometer at close and `last_pm_<level>_date` to the work order's `closed_date`.

A bus's forward-looking PM projection is exposed at the pm-status computed read. The read takes a `variant` parameter, `MILEAGE_RATE` (default) or `CALENDAR`, and returns `pm_due_status`, `next_pm_level`, the per-level miles-since fields `miles_since_pm_a`, `miles_since_pm_b`, and `miles_since_pm_c`, plus `miles_remaining_a`, `avg_daily_miles`, `projected_due_date`, and `projection_variant`. The common mileage basis is `miles_remaining_a` = `level_a_interval_miles` minus the quantity (`odometer_miles` minus `last_pm_a_miles`). Under `MILEAGE_RATE`, the system looks at the last 3 non-voided `MileageFuelLog` records for the bus, ordered by `log_date` ascending with ties broken by `created_at` ascending. If fewer than 3 such logs exist, `avg_daily_miles` falls back to 200; otherwise it is the sum of `miles_driven` over the baseline logs divided by the number of days between the first and last baseline `log_date` (guarded to at least 1), rounded half-up. The projected `days_to_due` is the greater of zero and the ceiling of `miles_remaining_a` divided by `avg_daily_miles`, and `projected_due_date` is the logical clock date plus that many days. Under `CALENDAR`, the projection ignores odometer history entirely and reports `projected_due_date` as `last_pm_a_date` plus `calendar_interval_days`. When no `ACTIVE` policy exists, `miles_remaining_a` and `projected_due_date` are null; `avg_daily_miles` is still computed and returned (200 when the bus has fewer than 3 non-voided logs), `pm_due_status` is `CURRENT`, and `next_pm_level` is A.

### 3.3. Work Orders: Opening, Scheduling, and Posture Gating

The **WorkOrder** is the unit of shop work. A `MaintenanceSupervisor` opens a work order by providing the `bus_id`, the `wo_type` (one of `PM_A`, `PM_B`, `PM_C`, `CAMPAIGN`, `CORRECTIVE`, `EMISSIONS`, `OVERHAUL`), the `priority` (one of `EMERGENCY`, `URGENT`, `ROUTINE`, `ELECTIVE`), the planned window as `planned_start_date` and `planned_end_date` (a closed interval, with `planned_end_date` required to be on or after `planned_start_date`), and the estimate fields `estimated_labor_hours` and `estimated_cost_cents`. Optional foreign keys are `defect_report_id` (when the work order originates from an operator defect report), `campaign_id` (required when `wo_type` is `CAMPAIGN`, and otherwise not set), and `lead_mechanic_id` (which may be assigned at open or later, but must be present before the work order can start). The `emissions_inspection_id` field is system-set only and appears on work orders the system creates automatically from a failed emissions inspection; clients never supply it. Creating a work order is OCC-guarded on the parent bus per §2.9, so the request must carry `expected_bus_version`. At open, the system snapshots `odometer_at_open` from the bus's current `odometer_miles`, sets `opened_date` to the logical clock date, initializes `labor_entries` to an empty list, `labor_total_cents`, `parts_total_cents`, `core_charges_accrued_cents`, `core_credits_cents`, `parts_net_cents`, `total_cost_cents`, and `qa_reject_count` to zero, and increments the bus's `version` by one.

Several guard checks run at create time, in the §2.10 priority order; their effective evaluation order is: body-reference existence, schema, the OCC stale-version check, the duplicate-open and defect-linked checks, the posture gates, the retired-bus check, the campaign-active check, and finally the fiscal cap. The referenced bus must not be `RETIRED` (`ERR_BUS_RETIRED`). The fleet posture gates creation: under `YELLOW`, an `ELECTIVE` work order is rejected with `ERR_FLEET_POSTURE_YELLOW`; under `RED`, both `ELECTIVE` and `ROUTINE` work orders are rejected with `ERR_FLEET_POSTURE_RED`. A bus may have at most one non-terminal work order of a given `wo_type`; a second open one is rejected with `ERR_DUPLICATE_OPEN_WORK_ORDER`. If `defect_report_id` is supplied, that defect must not already be linked to another non-terminal work order (`ERR_DEFECT_ALREADY_LINKED`); the cited defect need not belong to the same bus. If `campaign_id` is supplied, the campaign must be `ACTIVE` at creation as well as at scheduling — a campaign in any other status is rejected with `ERR_CAMPAIGN_NOT_ACTIVE` — and the bus need not be in the campaign's frozen scope (a close for an out-of-scope bus simply does not count toward progress). If `wo_type` is `OVERHAUL`, the estimate is checked against a fiscal cap described in §3.11.

A work order is a state machine in `status`, opening at `DRAFT` and terminating at either `CLOSED` or `CANCELLED`. The scheduling transition moves a work order from `DRAFT` to `SCHEDULED`. At schedule time the planned window is checked against every other non-terminal work order for the same bus under a buffered closed-interval overlap rule: the new window conflicts unless its start is strictly more than one day after the other window's end, or its end is strictly more than one day before the other window's start. A conflict is rejected with `ERR_WO_WINDOW_OVERLAP`. If the work order cites a `campaign_id`, that campaign must currently be `ACTIVE` (otherwise `ERR_CAMPAIGN_NOT_ACTIVE`). If it cites a `defect_report_id`, the defect must currently be in `SHOP_QUEUED` or `TRIAGED` and not already linked (`ERR_DEFECT_ALREADY_LINKED`). On a successful schedule, the linked defect (if any) transitions to `WO_LINKED` with its `linked_work_order_id` set. Scheduling does not change the bus's `version`; only the work order's own `version` increments.

The start transition moves a work order from `SCHEDULED` to `IN_PROGRESS`. It is gated by four checks. The `lead_mechanic_id` must be set (otherwise `ERR_VALIDATION`). The lead mechanic must hold the certification the `wo_type` requires, in `VALID` or `EXPIRING_SOON` status: the certification map is `PM_A`, `PM_B`, and `PM_C` to `PM_INSPECTION`; `EMISSIONS` to `EMISSIONS`; `OVERHAUL` to `ENGINE`; `CAMPAIGN` to the campaign's `required_cert_type`; and `CORRECTIVE` to none. A mechanic entirely lacking the required cert is rejected with `ERR_CERT_REQUIRED`; one whose cert is `EXPIRED` is rejected with `ERR_CERT_EXPIRED`. The bus's `service_status` must not be `RETIRED` (otherwise `ERR_BUS_RETIRED`); that check runs before the availability checks: the bus's `availability_status` must be `AVAILABLE` or `HELD`, and there must be no other work order in the `IN_PROGRESS` family on the same bus (otherwise `ERR_BUS_NOT_AVAILABLE`). On a successful start the work order's `started_date` is set to the clock date, the bus's `availability_status` is recomputed (typically becoming `IN_SHOP`), and — when `wo_type` is `OVERHAUL` — the bus's `service_status` moves from `ACTIVE` to `OVERHAUL_HOLD`. The posture recompute that follows the availability change may, if the fleet tips into `RED`, freeze other `SCHEDULED` work orders fleet-wide.

Once started, a work order can be parked in `AWAITING_PARTS` (from `IN_PROGRESS`) and later resumed to `IN_PROGRESS` either explicitly by a supervisor or mechanic or automatically when the last `RESERVED` part line on it reaches `ISSUED` or `RELEASED`. The rework cycle runs through `PENDING_QA` and is described in §3.4. A work order in `SCHEDULED` can be frozen to `BLOCKED` by the posture cascade described in §2.6 and restored when the fleet recovers. Cancellation is permitted from `DRAFT`, `SCHEDULED`, `IN_PROGRESS`, `AWAITING_PARTS`, `REOPENED`, or `BLOCKED`. On cancel, any still-`RESERVED` part lines are auto-released (decrementing each part's `quantity_reserved` and recomputing `stock_status`), a linked defect reverts from `WO_LINKED` back to `SHOP_QUEUED` with `linked_work_order_id` cleared, an `OVERHAUL` work order's bus returns from `OVERHAUL_HOLD` to `ACTIVE`, and the bus availability and fleet posture are recomputed.

A work order also exposes an `ASSIGN` event which sets `lead_mechanic_id` without changing the work order's state; this is how a supervisor or the mechanic designates the lead before the start gate requires it. `ASSIGN` is accepted from every non-terminal status, requires `lead_mechanic_id` in the payload (otherwise `ERR_VALIDATION`), and rejects an unknown mechanic with `ERR_NOT_FOUND`.

All work-order transitions share a common event endpoint whose payload carries an `event_type` discriminator naming the desired transition (`SCHEDULE`, `START`, `SET_AWAITING_PARTS`, `RESUME_WORK`, `SUBMIT_QA`, `QA_CERTIFY`, `QA_REJECT`, `CANCEL`, or `ASSIGN`), with `lead_mechanic_id`, `qa_note`, and `cancel_reason` as optional payloads consumed by the events that need them. Within the endpoint's authorized roles, `SCHEDULE`, `START`, and `CANCEL` are `MaintenanceSupervisor`-only; `SET_AWAITING_PARTS`, `RESUME_WORK`, and `ASSIGN` accept `MaintenanceSupervisor` or `Mechanic`; `SUBMIT_QA`, `QA_CERTIFY`, and `QA_REJECT` are `Mechanic`-only, with any other role rejected with `ERR_FORBIDDEN`.

### 3.4. Quality Assurance, Rework, and the Close Cascade

Quality assurance is a hard gate between shop work and close. Once a work order is `IN_PROGRESS`, the lead mechanic (and only the lead — the caller's `X-User-ID` must equal `lead_mechanic_id`, otherwise `ERR_FORBIDDEN`) submits the work for QA, moving it to `PENDING_QA`. Three preconditions guard this transition. There must be at least one labor entry (`ERR_QA_WITHOUT_LABOR`). No part line on the work order may still be in `issue_status` `RESERVED` or `ISSUED` (`ERR_LINES_UNRESOLVED`) — everything pulled must be either consumed, returned, or released. And for an `EMISSIONS` work order specifically, a passing retest is required: a `PASS` emissions inspection for the bus must exist whose `created_at` is at or after the work order's most recent entry into `IN_PROGRESS`; without one the transition is rejected with `ERR_EMISSIONS_RETEST_REQUIRED`.

A QA decision is made by a mechanic holding `QA_AUTHORITY` with status `VALID` or `EXPIRING_SOON` (otherwise `ERR_CERT_REQUIRED` or `ERR_CERT_EXPIRED`). The segregation-of-duties rule of §2.12 applies at this gate: the certifier must not be the work order's lead, otherwise `ERR_SOD_QA_SELF_CERTIFY`. Certification moves the work order from `PENDING_QA` to `CLOSED`. Rejection moves it back to `REOPENED`, increments `qa_reject_count` by one, and records the supplied `qa_note`; a `REOPENED` work order can be resumed to `IN_PROGRESS` to continue work.

Closing a work order fans out into a substantial cascade. The `closed_date` is set to the clock date. The bus's `availability_status` is recomputed (returning to `AVAILABLE` when no holds or other open work orders remain). For an `OVERHAUL` close, the bus's `service_status` returns to `ACTIVE` and `last_overhaul_miles` is set to the bus's `odometer_miles` at close. The PM nesting reset of §3.2 fires for `PM_A`, `PM_B`, and `PM_C` closes. The work order's `total_cost_cents` is added to the bus's `total_maintenance_cost_cents`. A linked defect, if any, is auto-resolved with `resolution` set to `SHOP_REPAIRED`, releasing any `SAFETY` or `TOWED` hold that defect was carrying; the bus availability and fleet posture are recomputed accordingly. If the work order cites a campaign, the campaign's progress is recomputed as described in §3.9, and at 100% the campaign auto-completes. Finally, if the `wo_type` is `CORRECTIVE`, `EMISSIONS`, or `CAMPAIGN` and the bus was inside its base warranty at the work order's open, a draft warranty claim is auto-created with `auto_created` set to true, `claim_type` `BASE_OEM`, status `DRAFT`, and null `proration_basis`, `manual_claimed_cents`, and amount fields, ready for a `WarrantyClerk` to review and submit (see §3.10).

### 3.5. Labor Entries and Work Order Costing

Labor is captured as an append-only `labor_entries` list on the work order. Each entry records `work_date`, `shift_type`, `hours`, the acting `mechanic_id`, and a computed `amount_cents`. Only the work order's lead mechanic may append an entry (otherwise `ERR_FORBIDDEN`), and `hours` must satisfy 0 < hours ≤ 16 (otherwise `ERR_LABOR_HOURS_INVALID`); the hours-range check fires before the lead-ownership check. An entry may be appended while the work order is in any non-terminal status — a `CLOSED` or `CANCELLED` work order rejects the append with `ERR_ALREADY_TERMINAL`.

Work-order cost is computed in two variants. The **ESTIMATE** variant applies while the work order is in `DRAFT` or `SCHEDULED`: the estimated cost is `estimated_cost_cents` plus `estimated_labor_hours` multiplied by the base hourly rate, ignoring any posted lines or entries. The **ACTUAL** variant applies once the work order is `IN_PROGRESS` or beyond: only posted labor entries and issued part lines count, and reserved-but-unissued part lines do not contribute.

The ACTUAL variant composes three pieces. **Labor** uses a base hourly rate of 6500 cents, modified by a shift differential — 1.00 for `AM`, 1.10 for `PM`, and 1.25 for `NIGHT`. Each labor entry's `amount_cents` is `hours` multiplied by the base rate multiplied by the differential for its `shift_type`, rounded half-up to the nearest cent *before* any summation. `labor_total_cents` is the sum of those per-entry amounts. **Parts** uses integer math with no rounding: each line's `line_total_cents` is the quantity issued net of unused returns multiplied by the line's snapshotted `unit_cost_cents`, and `parts_total_cents` sums the per-line totals over lines whose `issue_status` is `ISSUED` or `CONSUMED`. A `RETURNED` line contributes zero. **Net and total**: `parts_net_cents` is `parts_total_cents` minus `core_credits_cents`, and `total_cost_cents` is `labor_total_cents` plus `parts_net_cents`.

### 3.6. Parts Inventory, Reservations, and the Core Exchange

The parts catalog is owned by the `PartsClerk`. Creating a part SKU requires `sku` (not checked for uniqueness), `description`, `part_class` (one of `CONSUMABLE`, `REBUILDABLE_CORE`, or `EXPENDABLE`), `unit_cost_cents`, `reorder_point`, an `initial_on_hand` quantity, and a `warranty_eligible` flag. A part whose `part_class` is `REBUILDABLE_CORE` must additionally declare a `core_charge_cents` deposit. At creation, `quantity_on_hand` is seeded from `initial_on_hand`, `quantity_reserved` starts at zero, and `superseded_by_id` is null while the part is current.

A part's **available quantity** is its `quantity_on_hand` minus its `quantity_reserved`; it may go negative after a write-down. The derived `stock_status` classifies the part: `NORMAL` when the available quantity is strictly greater than `reorder_point`; `LOW_STOCK` when it is between zero and `reorder_point` inclusive; and `BACKORDERED` when it is negative. `BACKORDERED` is reachable only via a stock adjustment that writes the on-hand quantity below the already-reserved quantity.

Reservations, issuance, and core exchange happen through **WorkOrderPartLine** records. A part line is created against a work order by a `MaintenanceSupervisor`, `Mechanic`, or `PartsClerk`, naming the `part_id` and the `qty` (which must be at least 1). The parent work order must be in `DRAFT`, `SCHEDULED`, `IN_PROGRESS`, `AWAITING_PARTS`, or `REOPENED`. Two referential checks run at reserve: the part's `quantity_available` must be at least `qty` (otherwise `ERR_PART_STOCK_INSUFFICIENT`), and a part whose `superseded_by_id` is set cannot be reserved on new lines (otherwise `ERR_PART_SUPERSEDED`). On a successful reserve, the line starts in `issue_status` `RESERVED` with `core_status` `NONE`, with `qty_issued` initialized to zero; the part's `quantity_reserved` is increased by `qty`; the line's `unit_cost_cents` snapshots the part's current `unit_cost_cents`; and `stock_status` is recomputed. The line's `qty_issued` tracks the units currently issued out of stock and is incremented by issue events. Line events are role-gated: `ISSUE`, `CONSUME`, `RETURN_UNUSED`, and `RELEASE` accept `Mechanic` or `PartsClerk`; `CORE_RETURN` is `PartsClerk`-only.

Issuance moves a line from `RESERVED` to `ISSUED` and is gated on the parent work order being `IN_PROGRESS` or `AWAITING_PARTS` (otherwise `ERR_INVALID_STATE`). On issue the part's `quantity_on_hand` and `quantity_reserved` are each decremented by `qty`, and `stock_status` is recomputed. If the line's part is a `REBUILDABLE_CORE`, the work order's `core_charges_accrued_cents` is increased by `core_charge_cents` multiplied by `qty`, the line's `core_status` moves from `NONE` to `CORE_PENDING`, and `core_due_date` is set to the issue clock date plus 30 days. If the parent work order was `AWAITING_PARTS` and this issue leaves no remaining `RESERVED` line, the work order automatically returns to `IN_PROGRESS`.

From `ISSUED`, a line may be consumed (finalizing its `line_total_cents`) or returned-unused. Returning unused stock requires the line's `core_status` to be `NONE` or `CORE_PENDING` — a line whose core is `CORE_LATE`, `CORE_CREDITED`, or `CORE_REJECTED` is rejected with `ERR_INVALID_STATE`; a still-pending core is forfeited. On return the part's `quantity_on_hand` is incremented by `qty`, `stock_status` is recomputed, the work order's `core_charges_accrued_cents` is decreased by `core_charge_cents` multiplied by `qty` (reversing the accrual), and the line's `core_status` becomes `CORE_REJECTED` with no credit posted, its `core_due_date` cleared and `qty_issued` reset to zero. A `RESERVED` line may be released outright, which decrements `quantity_reserved` and recomputes `stock_status`; cancellation of the parent work order auto-releases any still-`RESERVED` lines. Only `ISSUE` is gated on the parent work order's status; `CONSUME`, `RETURN_UNUSED`, `RELEASE`, and `CORE_RETURN` run regardless of it.

Core exchange accounting runs on a separate parallel status whose terminal states are `CORE_CREDITED` and `CORE_REJECTED`. When a `REBUILDABLE_CORE` line is issued, the core becomes `CORE_PENDING` with a due date 30 days out. The epoch sweep ages a `CORE_PENDING` line past its due date to `CORE_LATE`, and a `CORE_LATE` line more than 15 days past due to `CORE_REJECTED`. A `PartsClerk` posts a core return against a `CORE_PENDING` or `CORE_LATE` line, supplying a `core_condition`. A return with `core_condition` `BAD` at any date, or any return after the late grace, rejects the core (`CORE_REJECTED`, no credit). A return with `core_condition` `GOOD` is tiered by timing: on or before `core_due_date`, the credit is the full `core_charge_cents` multiplied by `qty` and the line moves to `CORE_CREDITED`; after `core_due_date` but on or before 15 days past it, the credit is half — computed as `core_charge_cents` multiplied by `qty` multiplied by 0.50 and rounded half-up — and the line likewise moves to `CORE_CREDITED`; more than 15 days past due, the return is rejected with no credit (`CORE_REJECTED`). Posting a credit increases the work order's `core_credits_cents`; every `CORE_RETURN`, credited or not, clears the line's `core_due_date`. The core machinery has a conserved-quantity invariant: after an on-time `GOOD` return of the full `qty`, the line's accrued-minus-credited amount is zero. A `CORE_RETURN` against a line whose `core_status` is not `CORE_PENDING` or `CORE_LATE` is rejected with `ERR_CORE_NOT_PENDING`.

A part may be **superseded** by a successor SKU. A `PartsClerk` marks the current part with a `new_part_id` reference — which must resolve to an existing part (`ERR_NOT_FOUND`) and must differ from the part itself (`ERR_VALIDATION`); the system sets `superseded_by_id` on the current part, and subsequent reservation attempts against it are rejected with `ERR_PART_SUPERSEDED`. Stock may also be adjusted up (receiving) or down (write-down) by a signed `delta` with a `reason`; the on-hand quantity may not drop below zero (a write-down that would do so is rejected with `ERR_VALIDATION`), but a write-down may push the available quantity below the reserved quantity, transitioning `stock_status` to `BACKORDERED` and triggering the campaign-suspension cascade described in §3.9.

### 3.7. Daily Mileage, Fuel Logging, and Anomaly Detection

Every revenue bus posts a daily **MileageFuelLog**. An `Operator` submits the log with the `bus_id`, the service `log_date` (an ISO date, which must not be after the logical clock date — otherwise `ERR_LOG_DATE_IN_FUTURE`), the end-of-day `odometer_end`, and the whole-gallon `fuel_gallons` dispensed (which must be strictly greater than zero). Odometer monotonicity is enforced: the new `odometer_end` must be strictly greater than the bus's current `odometer_miles`, otherwise the post is rejected with `ERR_ODOMETER_REGRESSION`. The referenced bus must not be `RETIRED` (otherwise `ERR_BUS_RETIRED`). These guards are evaluated in the order: odometer monotonicity, then the future-`log_date` check, then the retired-bus check.

A successful post advances the bus. The system derives `miles_driven` for the log as the difference between the new `odometer_end` and the bus's `odometer_miles` prior to the post, then updates the bus's `odometer_miles` to the new `odometer_end`, recomputes `pm_due_status`, and increments the bus's `version`. The log itself opens in `POSTED` status.

After the odometer update, a fuel-MPG anomaly check runs against the log's baseline window. The baseline is the last 3 non-voided logs for the bus other than the new log itself, ordered by `log_date` ascending with ties broken by `created_at` ascending. If fewer than 3 baseline logs exist, no anomaly check fires and the new log stays `POSTED`. Otherwise, an anomaly is declared when the new log's implied fuel economy is less than 85 percent of the baseline's aggregate economy. The comparison is performed in integer cross-multiplied form to avoid floating-point drift: an anomaly fires when the new log's `miles_driven` multiplied by the baseline's total `fuel_gallons` multiplied by 100 is strictly less than 85 multiplied by the baseline's total `miles_driven` multiplied by the new log's `fuel_gallons`. Equality at exactly 85 percent is not an anomaly. On an anomaly the log transitions from `POSTED` to `FLAGGED`, and the system auto-creates a `DefectReport` for the bus with `severity` `MAJOR`, `defect_code` `FUEL_SYSTEM`, `description` "Fuel economy anomaly detected by mileage/fuel log", `reported_by` set to the posting operator's `X-User-ID`, `odometer_at_report` set to the log's `odometer_end`, `flagged_by_log_id` pointing at the new log, and `status` `OPEN`.

Logs may be voided as a compensating action, but only the latest one: a `FleetManager` may void a log only when it is the bus's most recent non-voided log ordered by `log_date` descending with ties broken by `created_at` descending, otherwise the void is rejected with `ERR_LOG_NOT_LATEST`. An optional `void_reason` may be recorded. On a successful void the log moves to `VOIDED`; the bus's `odometer_miles` is recomputed as the maximum `odometer_end` over the remaining non-voided logs, or `initial_odometer_miles` if none remain; `pm_due_status` is recomputed; and any auto-created defect still in `OPEN` status (one whose `flagged_by_log_id` is this log) is automatically withdrawn with `resolution` `AUTO_VOIDED`.

### 3.8. Operator Defect Reports and Road Calls

Operators are the eyes of the fleet. An `Operator` files a **DefectReport** against a bus with a `severity` of `SAFETY_CRITICAL`, `MAJOR`, or `MINOR`, a `defect_code` of `ENGINE`, `TRANSMISSION`, `BRAKES`, `ELECTRICAL`, `HVAC`, `FUEL_SYSTEM`, `TIRE`, or `OTHER`, a free-text `description`, and the operator-observed `odometer_at_report`. The reporting operator's opaque `X-User-ID` is recorded as `reported_by`. Filing a `SAFETY_CRITICAL` report immediately places the bus in `HELD` with the `SAFETY` hold added to `hold_reasons`, recomputes the fleet posture (which may trigger the `RED` freeze cascade), and increments the bus's `version`. Filing a defect against a `RETIRED` bus is rejected with `ERR_BUS_RETIRED`. The defect opens in `OPEN` status and terminates at `RESOLVED` or `WITHDRAWN`.

Triage is performed by a `MaintenanceSupervisor` and forks the defect down one of three paths. Triage to `SHOP` moves the defect to `SHOP_QUEUED`, awaiting a work order. Triage to `ROAD_CALL` moves it to `TRIAGED`, awaiting dispatch. Triage to `DEFER` moves it to `DEFERRED`, with a defer window that depends on severity. For a `SAFETY_CRITICAL` defect, `defer_until_date` must equal the clock date — any other value, past or future, is rejected with `ERR_DEFECT_NOT_DEFERRABLE` (so `ERR_DEFER_DATE_INVALID` never fires for a `SAFETY_CRITICAL` defect). A missing `defer_until_date` or `defer_justification` on a `DEFER` triage is rejected with `ERR_VALIDATION`. For a `MAJOR` defect, `defer_until_date` must be no more than 7 days after the clock date. For a `MINOR` defect, it must be no more than 90 days after. In all cases `defer_until_date` must not be before the clock date; violations are rejected with `ERR_DEFER_DATE_INVALID`. A deferral requires a `defer_justification`, increments `defer_count`, and — for a `SAFETY_CRITICAL` defect — keeps the `SAFETY` hold in place even while deferred. The epoch sweep reopens a `DEFERRED` defect back to `OPEN` once its `defer_until_date` has passed, clearing `disposition`.

A road call is dispatched by a supervisor from the `TRIAGED` state. The dispatched `mechanic_id` must hold the certification matching the `defect_code` — `ENGINE` maps to `ENGINE`, `TRANSMISSION` to `TRANSMISSION`, `BRAKES` to `BRAKES`, `ELECTRICAL` to `ELECTRICAL`, `HVAC` to `HVAC`, `FUEL_SYSTEM` to `ENGINE`, and `TIRE` and `OTHER` require none — with status `VALID` or `EXPIRING_SOON` (otherwise `ERR_CERT_REQUIRED`). The mechanic must also have a `CONFIRMED` shift assignment on a `PUBLISHED` shift covering the clock date (otherwise `ERR_MECHANIC_NOT_ON_SHIFT`): the shift's `shift_date` must equal the clock date — the time of day is not otherwise consulted — and a `NIGHT` shift dated the previous day additionally counts until 06:00. On dispatch, `road_call_mechanic_id` is set and the bus is placed in `HELD` with `ROAD_CALL` added to `hold_reasons`; the fleet posture is recomputed.

The dispatched mechanic (and only that mechanic, verified by `X-User-ID` against `road_call_mechanic_id`, otherwise `ERR_FORBIDDEN`) reports arrival to move the defect from `ROAD_CALL_DISPATCHED` to `ON_SCENE`. Clearing the road call then resolves it in one of two ways. A `FIXED_ON_SCENE` clear moves the defect directly to `RESOLVED`, records `resolution` as `ROAD_CALL_FIXED`, and releases both the `ROAD_CALL` hold and — for a `SAFETY_CRITICAL` defect — the `SAFETY` hold. A `TOWED_IN` clear moves the defect back to `SHOP_QUEUED`, replaces the `ROAD_CALL` hold with a `TOWED` hold (the bus remains `HELD`), and records `resolution` as `TOWED_IN`; that resolution is later overwritten to `SHOP_REPAIRED` when the linked work order closes.

Once a defect is `SHOP_QUEUED` (or `TRIAGED`), a work order citing it may be scheduled; that scheduling moves the defect to `WO_LINKED` with `linked_work_order_id` set. When the linked work order reaches `CLOSED`, the defect auto-resolves with `resolution` `SHOP_REPAIRED`, releasing any `SAFETY` or `TOWED` hold. A supervisor may also manually resolve a defect from `OPEN`, `TRIAGED`, `SHOP_QUEUED`, or `DEFERRED`, but only when `severity` is not `SAFETY_CRITICAL` (otherwise `ERR_SAFETY_DEFECT_NEEDS_WORK_ORDER` — safety defects must be resolved via a closed work order) and only when no non-terminal work order is linked (otherwise `ERR_INVALID_STATE`); manual resolution records `resolution` `MANUAL` and releases holds. The operator who filed a defect (or the system) may withdraw it from `OPEN`, `TRIAGED`, or `DEFERRED`; withdrawal is restricted to the `Operator` role and the caller's `X-User-ID` must equal the defect's `reported_by` (otherwise `ERR_FORBIDDEN`); a system-withdrawal triggered by voiding the flagging mileage log records `resolution` `AUTO_VOIDED`. Both resolve and withdraw release holds and recompute availability and posture.

A defect report's `flagged_by_log_id` field is system-set only: it identifies the mileage log whose fuel-anomaly check created the defect, and is otherwise null.

### 3.9. Campaigns, Emissions Inspections, and the Fleet-Wide Compliance Cascades

OEM campaigns and recalls are managed as **Campaign** aggregates. A `FleetManager` creates a campaign in `DRAFT` with a `code` (not checked for uniqueness), a `title`, the in-scope `model_year_from` and `model_year_to` (with `model_year_to` on or after `model_year_from`), the standard `labor_hours_per_bus`, a compliance `deadline_date`, and optionally a `required_part_id` that every campaign work order will reserve and a `required_cert_type` the lead mechanic must hold (when supplied, `required_cert_type` must be one of the eight certification types, otherwise `ERR_VALIDATION`).

Activating a campaign freezes its scope: the set of buses whose `model_year` is within the closed range from `model_year_from` to `model_year_to` and whose `service_status` is `ACTIVE` at that instant, sorted by `fleet_number` ascending with ties broken by `created_at` ascending, is stored as `scope_bus_ids`. An activation whose scope is empty is rejected with `ERR_CAMPAIGN_SCOPE_EMPTY`. On activation, `activated_date` is set to the clock date. If a `required_part_id` was supplied and that part is `BACKORDERED` at activation, the campaign immediately transitions from `ACTIVE` to `SUSPENDED`. A campaign may also be suspended explicitly by a `FleetManager`, or automatically whenever its required part's `stock_status` becomes `BACKORDERED` (the automatic cascade suspends only `ACTIVE` campaigns; `DRAFT` and already-`SUSPENDED` campaigns are unaffected). While a campaign is `SUSPENDED`, attempts to create or schedule a `CAMPAIGN` work order citing it are rejected with `ERR_CAMPAIGN_NOT_ACTIVE`. Resuming a suspended campaign requires that any `required_part_id` part not currently be `BACKORDERED` (otherwise `ERR_PART_STOCK_INSUFFICIENT`).

Campaign progress is computed against the frozen scope. `buses_completed_count` is the number of buses in `scope_bus_ids` that have a `CLOSED` work order citing this campaign. `progress_pct` is one hundred times that count divided by the size of `scope_bus_ids`, rounded half-up to 2 decimal places. When `progress_pct` reaches 100, the campaign automatically transitions from `ACTIVE` to `COMPLETED`. Buses that retire after activation remain in scope — the denominator does not shrink — so progress can stall below 100% if a scoped bus is retired before its campaign work order closes. A `FleetManager` may close an `ACTIVE` or `SUSPENDED` campaign explicitly; closure leaves existing non-terminal campaign work orders in place but prevents any new ones from being created.

**EmissionsInspection** records are append-only and open in their single state `RECORDED`. A `MaintenanceSupervisor` records an inspection against a bus with a `test_type` of `OPACITY`, `OBD`, or `IDLE`, a `test_date` (which must not be after the logical clock date, otherwise `ERR_VALIDATION`), and a `result` of `PASS` or `FAIL`. Recording an inspection against a `RETIRED` bus is rejected with `ERR_BUS_RETIRED`. A `PASS` requires a `certificate_expiry_date` (otherwise `ERR_VALIDATION`), which is then set as the bus's `emissions_cert_expiry_date`. Optionally, the inspection may name a `failed_component_part_id` to be reserved on the auto-created work order.

A `FAIL` result triggers a compliance cascade. The bus is placed in `HELD` with `EMISSIONS` added to `hold_reasons`. The system automatically creates an `EMISSIONS` work order for the bus in `SCHEDULED` status at `EMERGENCY` priority, with a planned window running from the clock date to seven days after, an estimated 8 labor hours and 0 estimated cost cents, and `emissions_inspection_id` set to the inspection that spawned it; if `failed_component_part_id` was supplied, a part line reserving exactly 1 unit of that part is created on the work order, bypassing the usual reserve-time gates — no stock-availability or supersession check runs, so the reservation may drive the part's available quantity negative and its `stock_status` to `BACKORDERED`. The auto-created work order likewise bypasses the create-time guards (no OCC, duplicate-type, window-overlap, or posture check runs). A subsequent `PASS` retest sets the bus's `emissions_cert_expiry_date` to the new certificate expiry and clears the `EMISSIONS` hold; it does not affect the auto-created work order, which remains in place until worked or cancelled. The epoch sweep additionally grounds any bus whose certificate has expired, adding an `EMISSIONS` hold even without a fresh inspection. The bus's `emissions_compliance` derived field reports `COMPLIANT`, `CERT_EXPIRED`, or `NON_COMPLIANT` (the latter when an emissions hold is active).

### 3.10. Warranty Claims and OEM Recovery

Warranty recovery is run by the `WarrantyClerk`, with cash posting reserved to the `FleetManager`. A **WarrantyClaim** is created against a work order that is `CLOSED`, citing the `work_order_id`, a `claim_type` of `BASE_OEM`, `EXTENDED`, `PARTS_ONLY`, or `GOODWILL`, and — because the create is OCC-guarded on the work order per §2.9 — an `expected_work_order_version` matching the work order's current `version`. An `EXTENDED` claim additionally requires a `proration_basis` of `MILES` or `TIME`. A `GOODWILL` claim additionally requires a `manual_claimed_cents`. At creation the claim's `bus_id` is denormalized from the work order, and the work order's `version` is incremented by one.

Eligibility is gated per claim type at creation. A `BASE_OEM` claim requires the work order's `odometer_at_open` to be at or below the bus's `base_warranty_expiry_miles` and the `opened_date` to be on or before the `base_warranty_expiry_date`. An `EXTENDED` claim requires the work order to be outside the base warranty but still within the extended limits: `odometer_at_open` at or below `extended_warranty_limit_miles`, and the whole-day difference between `opened_date` and `in_service_date` at or below `extended_warranty_limit_months` multiplied by 30. A bus missing either extended limit is never eligible for an `EXTENDED` claim. A `PARTS_ONLY` claim requires at least one part line on the work order whose part is `warranty_eligible`. A violation of any of these gates is rejected with `ERR_WARRANTY_NOT_ELIGIBLE`.

A `DRAFT` claim may be submitted by a `WarrantyClerk`. `RECORD_OEM_DECISION`, `APPEAL`, and `WITHDRAW` are likewise `WarrantyClerk`-only; `POST_RECOVERY` is `FleetManager`-only. Submission is gated on the underlying work order still being `CLOSED` — if the work order has since been transitioned out of `CLOSED` (for example, cancelled), the submission is rejected with `ERR_INVALID_STATE`. On a successful submit the claim moves from `DRAFT` to `SUBMITTED`, `submitted_by_user_id` records the caller's opaque `X-User-ID`, and the claim's amount is computed and pinned at submission. The evaluation order is fixed: first the work order's `labor_total_cents` and parts line amounts are frozen as of the submit; then only core credits posted strictly before the submit are subtracted; then `eligible_cents` is computed per claim type from the frozen basis; then the proration fraction is applied; then a single final round-half-up produces `claimed_cents`. For `BASE_OEM`, `eligible_cents` is the frozen `labor_total_cents` plus the sum of frozen line totals whose part is `warranty_eligible`. For `EXTENDED`, the eligible basis is the same as `BASE_OEM`, then prorated: with `proration_basis` `MILES`, the fraction is the greater of zero and (`extended_warranty_limit_miles` minus `odometer_at_open`) divided by `extended_warranty_limit_miles`; with `proration_basis` `TIME`, the fraction is the greater of zero and (`extended_warranty_limit_months` multiplied by 30 minus the days between `opened_date` and `in_service_date`) divided by (`extended_warranty_limit_months` multiplied by 30). For `PARTS_ONLY`, only the eligible line totals count (labor is excluded). For `GOODWILL`, the claimed amount is `manual_claimed_cents` with no proration, and `eligible_cents` equals `manual_claimed_cents` as well. Once submitted, `eligible_cents` and `claimed_cents` are pinned and never recomputed, even if later core credits or labor adjustments would otherwise change the basis.

After submission, the OEM's decision is recorded through a claim event whose payload names a `decision_outcome` of `APPROVED`, `PARTIAL`, or `DENIED`. An `APPROVED` outcome sets `approved_cents` equal to `claimed_cents` and records the `oem_reference`; a `PARTIAL` outcome requires `approved_cents` strictly less than `claimed_cents` (otherwise `ERR_VALIDATION`) and moves the claim to `PARTIALLY_APPROVED`; a `DENIED` outcome sets `approved_cents` to zero. A denied claim may be appealed, returning it to `SUBMITTED` and incrementing `appeal_count`, but only twice — an appeal with `appeal_count` already 2 is rejected with `ERR_APPEAL_LIMIT_EXCEEDED`. An appeal may carry an optional `appeal_note` for the OEM file. Only a `GOODWILL` claim may re-pin its `claimed_cents` on appeal via a new `manual_claimed_cents`; other claim types keep their pinned value.

Cash recovery is posted by a `FleetManager` from `APPROVED` or `PARTIALLY_APPROVED`. The `received_cents` must not exceed `approved_cents` (otherwise `ERR_RECOVERY_EXCEEDS_APPROVED`), and the segregation-of-duties rule of §2.12 requires the caller's `X-User-ID` to differ from the claim's `submitted_by_user_id` (otherwise `ERR_SOD_RECOVERY_SELF_APPROVAL`). On posting, `received_cents` and `recovered_by_user_id` are recorded, `variance_cents` is computed as `approved_cents` minus `received_cents`, and the claim moves to `RECOVERED`. A claim in `DRAFT`, `SUBMITTED`, or `DENIED` may instead be withdrawn, terminating at `WITHDRAWN`. The `auto_created` flag distinguishes claims the system drafted at work-order close from claims a clerk created manually.

### 3.11. Mid-Life Overhaul and Fleet Replacement Planning

Mid-life overhauls are ordinary work orders with `wo_type` `OVERHAUL`, but they interact specially with the bus lifecycle and with a fiscal cap. At create time, an overhaul's `estimated_cost_cents` is checked against a cap of 40 percent of the bus's `replacement_cost_cents`, rounded half-up; an estimate strictly greater than the cap is rejected with `ERR_OVERHAUL_COST_CAP_EXCEEDED`, while an estimate exactly equal to the cap is allowed. Starting an overhaul moves the bus's `service_status` from `ACTIVE` to `OVERHAUL_HOLD`. Closing (or cancelling) the overhaul returns the bus to `ACTIVE`; on a close, `last_overhaul_miles` is set to the bus's `odometer_miles` at close.

Fleet replacement planning produces a **FleetReplacementPlan** snapshot. A `FleetManager` creates a plan for a `plan_year`; the system computes a replacement score for every bus whose `service_status` is `ACTIVE` (buses in `OVERHAUL_HOLD` or `RETIRED` are excluded) and freezes the results into the plan's `scores` array. Only one plan may be open at a time — a create while another plan is in `DRAFT`, `APPROVED`, or `EXECUTING` is rejected with `ERR_PLAN_ALREADY_OPEN`.

Each bus's score composes four weighted terms. The age term is `age_years` — the whole-year floor of the days between `in_service_date` and the clock date divided by 365 — normalized by 12 years and capped at 1, then weighted at 0.30. The mileage term is `odometer_miles` normalized by 500,000 miles and capped at 1, weighted at 0.30. The cost term is `total_maintenance_cost_cents` divided by `replacement_cost_cents`, capped at 1, weighted at 0.25 (when `replacement_cost_cents` is zero the cost ratio is treated as 1). The overhaul term is a binary flag that is 1 when (`odometer_miles` minus `last_overhaul_miles`) exceeds `overhaul_interval_miles`, weighted at 0.15. The weighted sum is then adjusted: if the bus's `pm_due_status` is `OVERDUE` (with no active policy counting as `CURRENT`), the score is multiplied by 1.25 and capped at 1. The final score is rounded half-up to 4 decimal places. Each snapshot entry also carries the input values — `bus_id`, `age_years`, `odometer_miles`, `cost_ratio`, and `overhaul_overdue` — and a `recommendation`: `REPLACE` when the score is at least 0.70, `OVERHAUL` when the score is at least 0.45 but below 0.70, and `KEEP` otherwise. The snapshot is sorted by score descending, with ties broken by `fleet_number` ascending and then by `created_at` ascending.

A plan moves from `DRAFT` through `APPROVED` and `EXECUTING` to `CLOSED` under `FleetManager` events, with no additional side effects.

### 3.12. Mechanics, Certifications, and Shift Coverage

Shop staffing is organized around **Mechanic** records, their certifications, and shifts. A `MaintenanceSupervisor` creates a mechanic with a `name` and an `employee_ref` (not checked for uniqueness); the mechanic's `employment_status` starts at `ACTIVE`. A mechanic holds zero or more **MechanicCertification** records, each created with a `cert_type` of `ENGINE`, `TRANSMISSION`, `BRAKES`, `ELECTRICAL`, `HVAC`, `EMISSIONS`, `PM_INSPECTION`, or `QA_AUTHORITY`, an `issued_date`, and an `expiry_date` (with `issued_date` required to be on or before `expiry_date`). A new certification opens in `VALID` status regardless of its dates. A certification's `status` is recomputed by the epoch sweep against the logical clock: `VALID` moves to `EXPIRING_SOON` when the expiry date is between 0 and 30 days out inclusive, and either `VALID` or `EXPIRING_SOON` moves to `EXPIRED` once the expiry date is strictly before the clock date; the sweep never moves a certification backward (`EXPIRED` stays `EXPIRED`, and `EXPIRING_SOON` never returns to `VALID` outside renewal). Renewal is cyclic — a `MaintenanceSupervisor` renews a certification from any of `VALID`, `EXPIRING_SOON`, or `EXPIRED` by supplying a `new_expiry_date` strictly after the clock date (otherwise `ERR_VALIDATION`), which updates `expiry_date` and returns the certification to `VALID`. A mechanic whose certification has expired no longer counts toward shift coverage and fails every certification gate described in §3.3 and §3.4.

**Shift** records plan daily coverage. A supervisor creates a shift in `DRAFT` with a `shift_date`, a `shift_type`, and a `required_headcount` map from cert type to required confirmed headcount (the map is required but may be empty; keys must be known certification types and values non-negative integers, otherwise `ERR_VALIDATION`). The three shift types are fixed half-open intervals on the clock: `AM` covers 06:00 up to but not including 14:00; `PM` covers 14:00 up to but not including 22:00; and `NIGHT` covers 22:00 up to but not including 06:00 the following day. Publishing a shift moves it to `PUBLISHED` and computes its initial `coverage_by_cert`; with zero assignments yet, every required cert starts short unless `required_headcount` is empty, in which case coverage is vacuously `FULL`. The epoch sweep locks a `PUBLISHED` shift once its `shift_date` has passed, moving it to `LOCKED`. Reconciling a `LOCKED` shift moves it to `RECONCILED` and settles every assignment: each `CONFIRMED` assignment becomes `COMPLETED`, and each still-`SCHEDULED` assignment becomes `NO_SHOW`.

**ShiftAssignment** records staff a shift. A supervisor assigns a mechanic by `mechanic_id` and a `role_in_shift` of `LEAD`, `TECH`, or `QA`; the assignment's `shift_id` references the parent shift, which must be `PUBLISHED` (otherwise `ERR_SHIFT_NOT_PUBLISHED`) — a check evaluated after the two checks below, so `ERR_DUPLICATE_ASSIGNMENT` or `ERR_SHIFT_OVERLAP` is reported first. Two uniqueness checks run at assign: no other non-`REMOVED` assignment may exist for the same shift and mechanic (otherwise `ERR_DUPLICATE_ASSIGNMENT`), and the mechanic's fixed half-open shift intervals on the same `shift_date` must not overlap any existing `SCHEDULED` or `CONFIRMED` assignment — adjacency, where one interval's end equals the other's start, is allowed (otherwise `ERR_SHIFT_OVERLAP`). Intervals are compared as absolute half-open windows, so a `NIGHT` shift occupies 22:00 through 06:00 the following day and is adjacent to, never overlapping, that day's `AM` shift. An assignment opens at `SCHEDULED`. Confirmation moves it to `CONFIRMED` and is permitted either by a supervisor or by the mechanic themselves (with `X-User-ID` equal to the assignment's `mechanic_id`), but only while the parent shift is `PUBLISHED` (otherwise `ERR_SHIFT_NOT_PUBLISHED`). A supervisor may mark a `SCHEDULED` or `CONFIRMED` assignment as `NO_SHOW`, or remove it outright to `REMOVED`; removal and no-show both recompute the shift's coverage. Reconciliation completes `CONFIRMED` assignments and marks `SCHEDULED` ones as `NO_SHOW`.

The shift's `coverage_by_cert` is recomputed on every assignment create, confirm, no-show, and remove, on every certification status change, and at publish. For each cert type in `required_headcount`, the covered count is the number of assignments in `CONFIRMED` status whose mechanic holds a certification of that type with status `VALID` or `EXPIRING_SOON`. A mechanic holding multiple certs counts toward each independently. The shift's `coverage_status` is `FULL` when every required cert meets its headcount (vacuously `FULL` when `required_headcount` is empty) and `SHORT` otherwise.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions, voids, renewals, stock adjustments, supersession, publish/reconcile, and epoch sweeps — return `200 OK`. All endpoints are mounted under the `/fleet` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fleet/_clock/set_current_utc` | Set the logical clock | FleetManager |
| POST | `/fleet/run_epoch` | Daily epoch sweep against the logical clock | FleetManager |
| POST | `/fleet/buses` | Register a bus | FleetManager |
| GET | `/fleet/buses/{id}` | Get one bus | Any |
| GET | `/fleet/buses` | List buses | Any |
| GET | `/fleet/buses/{id}/pm-status` | Computed PM projection for a bus | Any |
| POST | `/fleet/buses/{id}/retire` | Retire a bus | FleetManager |
| GET | `/fleet/buses/{id}/work-orders` | Work orders for a bus | Any |
| GET | `/fleet/buses/{id}/warranty-claims` | Warranty claims for a bus | Any |
| GET | `/fleet/buses/{id}/defect-reports` | Defect reports for a bus | Any |
| GET | `/fleet/buses/{id}/mileage-fuel-logs` | Mileage/fuel logs for a bus | Any |
| GET | `/fleet/buses/{id}/emissions-inspections` | Emissions inspections for a bus | Any |
| POST | `/fleet/pm-policies` | Create a PM policy | FleetManager |
| GET | `/fleet/pm-policies/{id}` | Get one PM policy | Any |
| GET | `/fleet/pm-policies` | List PM policies | Any |
| POST | `/fleet/mileage-fuel-logs` | Post a daily mileage/fuel log | Operator |
| GET | `/fleet/mileage-fuel-logs/{id}` | Get one log | Any |
| GET | `/fleet/mileage-fuel-logs` | List logs | Any |
| GET | `/fleet/mileage-fuel-logs/{id}/defect-reports` | Defect reports auto-created by this log | Any |
| POST | `/fleet/mileage-fuel-logs/{id}/void` | Void the latest non-voided log | FleetManager |
| POST | `/fleet/work-orders` | Open a work order | MaintenanceSupervisor |
| GET | `/fleet/work-orders/{id}` | Get one work order | Any |
| GET | `/fleet/work-orders` | List work orders | Any |
| POST | `/fleet/work-orders/{id}/events` | Work order transitions (SCHEDULE, START, SET_AWAITING_PARTS, RESUME_WORK, SUBMIT_QA, QA_CERTIFY, QA_REJECT, CANCEL, ASSIGN) | MaintenanceSupervisor, Mechanic |
| POST | `/fleet/work-orders/{id}/labor-entries` | Append a labor entry | Mechanic |
| GET | `/fleet/work-orders/{id}/part-lines` | Part lines of a work order | Any |
| GET | `/fleet/work-orders/{id}/warranty-claims` | Warranty claims against a work order | Any |
| GET | `/fleet/work-orders/{id}/defect-reports` | Defect reports linked to this work order | Any |
| POST | `/fleet/work-orders/{id}/part-lines` | Reserve a part line on a work order | MaintenanceSupervisor, Mechanic, PartsClerk |
| GET | `/fleet/part-lines/{id}` | Get one part line | Any |
| GET | `/fleet/part-lines` | List part lines | Any |
| POST | `/fleet/part-lines/{id}/events` | Part line events (ISSUE, CONSUME, RETURN_UNUSED, RELEASE, CORE_RETURN) | Mechanic, PartsClerk |
| POST | `/fleet/parts` | Create a part SKU | PartsClerk |
| GET | `/fleet/parts/{id}` | Get one part | Any |
| GET | `/fleet/parts` | List parts | Any |
| POST | `/fleet/parts/{id}/stock-adjustments` | Receive or write down stock | PartsClerk |
| POST | `/fleet/parts/{id}/supersede` | Mark a part superseded by another part | PartsClerk |
| GET | `/fleet/parts/{id}/emissions-inspections` | Emissions inspections citing this part as failed component | Any |
| GET | `/fleet/parts/{id}/campaigns` | Campaigns requiring this part | Any |
| POST | `/fleet/defect-reports` | Operator files a defect report | Operator |
| GET | `/fleet/defect-reports/{id}` | Get one defect report | Any |
| GET | `/fleet/defect-reports` | List defect reports | Any |
| POST | `/fleet/defect-reports/{id}/events` | Defect events (TRIAGE, DISPATCH_ROAD_CALL, ARRIVE_ON_SCENE, CLEAR_ROAD_CALL, RESOLVE, WITHDRAW) | MaintenanceSupervisor, Mechanic, Operator |
| GET | `/fleet/defect-reports/{id}/work-orders` | Work orders citing this defect | Any |
| POST | `/fleet/campaigns` | Create an OEM campaign | FleetManager |
| GET | `/fleet/campaigns/{id}` | Get one campaign | Any |
| GET | `/fleet/campaigns` | List campaigns | Any |
| POST | `/fleet/campaigns/{id}/events` | Campaign events (ACTIVATE, SUSPEND, RESUME, CLOSE) | FleetManager |
| GET | `/fleet/campaigns/{id}/work-orders` | Work orders citing this campaign | Any |
| POST | `/fleet/emissions-inspections` | Record an emissions inspection | MaintenanceSupervisor |
| GET | `/fleet/emissions-inspections/{id}` | Get one inspection | Any |
| GET | `/fleet/emissions-inspections` | List inspections | Any |
| GET | `/fleet/emissions-inspections/{id}/work-orders` | Work orders auto-created from this inspection | Any |
| POST | `/fleet/warranty-claims` | Create a warranty claim | WarrantyClerk |
| GET | `/fleet/warranty-claims/{id}` | Get one claim | Any |
| GET | `/fleet/warranty-claims` | List claims | Any |
| POST | `/fleet/warranty-claims/{id}/events` | Claim events (SUBMIT, RECORD_OEM_DECISION, APPEAL, POST_RECOVERY, WITHDRAW) | WarrantyClerk, FleetManager |
| POST | `/fleet/shifts` | Create a shift | MaintenanceSupervisor |
| GET | `/fleet/shifts/{id}` | Get one shift | Any |
| GET | `/fleet/shifts` | List shifts | Any |
| POST | `/fleet/shifts/{id}/publish` | Publish a shift | MaintenanceSupervisor |
| POST | `/fleet/shifts/{id}/reconcile` | Reconcile a locked shift | MaintenanceSupervisor |
| POST | `/fleet/shifts/{id}/assignments` | Assign a mechanic to a shift | MaintenanceSupervisor |
| GET | `/fleet/shifts/{id}/assignments` | Assignments of a shift | Any |
| POST | `/fleet/shift-assignments/{id}/events` | Assignment events (CONFIRM, NO_SHOW, REMOVE) | MaintenanceSupervisor, Mechanic |
| POST | `/fleet/mechanics` | Create a mechanic | MaintenanceSupervisor |
| GET | `/fleet/mechanics/{id}` | Get one mechanic | Any |
| GET | `/fleet/mechanics` | List mechanics | Any |
| GET | `/fleet/mechanics/{id}/shift-assignments` | Assignments of a mechanic | Any |
| GET | `/fleet/mechanics/{id}/work-orders` | Work orders led by a mechanic | Any |
| GET | `/fleet/mechanics/{id}/defect-reports` | Defect reports dispatched to a mechanic | Any |
| POST | `/fleet/mechanics/{id}/certifications` | Grant a certification | MaintenanceSupervisor |
| GET | `/fleet/mechanics/{id}/certifications` | Certifications of a mechanic | Any |
| GET | `/fleet/certifications/{id}` | Get one certification | Any |
| POST | `/fleet/certifications/{id}/renew` | Renew a certification | MaintenanceSupervisor |
| POST | `/fleet/replacement-plans` | Create a replacement plan | FleetManager |
| GET | `/fleet/replacement-plans/{id}` | Get one plan | Any |
| POST | `/fleet/replacement-plans/{id}/events` | Plan events (APPROVE, EXECUTE, CLOSE) | FleetManager |
| GET | `/fleet/posture` | Computed fleet posture | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_DUPLICATE_OPEN_WORK_ORDER` | 409 |
| `ERR_DEFECT_ALREADY_LINKED` | 409 |
| `ERR_DUPLICATE_ASSIGNMENT` | 409 |
| `ERR_PLAN_ALREADY_OPEN` | 409 |
| `ERR_OPEN_WORK_ORDERS_EXIST` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_WO_WINDOW_OVERLAP` | 409 |
| `ERR_FLEET_POSTURE_YELLOW` | 409 |
| `ERR_FLEET_POSTURE_RED` | 409 |
| `ERR_BUS_RETIRED` | 409 |
| `ERR_BUS_NOT_AVAILABLE` | 409 |
| `ERR_PART_STOCK_INSUFFICIENT` | 409 |
| `ERR_PART_SUPERSEDED` | 409 |
| `ERR_CORE_NOT_PENDING` | 409 |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 |
| `ERR_QA_WITHOUT_LABOR` | 409 |
| `ERR_LINES_UNRESOLVED` | 409 |
| `ERR_EMISSIONS_RETEST_REQUIRED` | 409 |
| `ERR_SHIFT_NOT_PUBLISHED` | 409 |
| `ERR_LOG_NOT_LATEST` | 409 |
| `ERR_APPEAL_LIMIT_EXCEEDED` | 409 |
| `ERR_SAFETY_DEFECT_NEEDS_WORK_ORDER` | 409 |
| `ERR_MECHANIC_NOT_ON_SHIFT` | 409 |
| `ERR_SOD_QA_SELF_CERTIFY` | 403 |
| `ERR_SOD_RECOVERY_SELF_APPROVAL` | 403 |
| `ERR_STALE_BUS_VERSION` | 412 |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 |
| `ERR_LABOR_HOURS_INVALID` | 422 |
| `ERR_CERT_REQUIRED` | 422 |
| `ERR_CERT_EXPIRED` | 422 |
| `ERR_DEFECT_NOT_DEFERRABLE` | 422 |
| `ERR_DEFER_DATE_INVALID` | 422 |
| `ERR_ODOMETER_REGRESSION` | 422 |
| `ERR_LOG_DATE_IN_FUTURE` | 422 |
| `ERR_CAMPAIGN_SCOPE_EMPTY` | 422 |
| `ERR_PM_POLICY_INVALID` | 422 |
| `ERR_OVERHAUL_COST_CAP_EXCEEDED` | 422 |
| `ERR_WARRANTY_NOT_ELIGIBLE` | 422 |
| `ERR_RECOVERY_EXCEEDS_APPROVED` | 422 |
