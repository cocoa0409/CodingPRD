# Standby Generator Service API — Product Requirements Document

## 1. Introduction

This document specifies the Standby Generator Service API, the system of record for a Generac-style standby-power business that takes a homeowner from a first conversation about backup power all the way through years of warranty service, recalls, and remote monitoring. The platform threads together two distinct phases of a generator's life. The first is an install pipeline: a customer's electrical load is assessed and translated into a continuous-kilowatt sizing requirement, a generator model is selected and locked in, a jurisdiction permit is pulled and the fuel supply (natural gas or propane) is verified to carry the load, the unit is physically installed alongside an automatic transfer switch, and finally the equipment is activated and registered. The second phase begins the moment a physical Unit is minted at activation: maintenance plans with annual or semi-annual visits, periodic self-test exercise logging, warranty adjudication, remote-monitoring health tracking, paid and warranty repair dispatching, and manufacturer recall campaigns that can fan out to every affected unit in the field.

The business runs on a logical clock rather than wall-clock time, because compliance scoring, warranty proration, recall deadlines, and missed-visit detection all depend on the passage of time and must be reproducible. Several of the most consequential fields a customer sees — whether their unit is operational, whether monitoring is healthy, whether the warranty is still good — are not written directly by any single request. They are recomputed from the unit's children, its recall posture, and the clock every time something relevant changes. The sections below describe the precise contract for every response, the system-wide principles that govern consistency and concurrency, and then the full business workflow with all of its gates, calculations, and cascades.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and structural conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes five roles, spelled exactly: `Anonymous`, `Customer`, `Technician`, `ServiceManager`, and `ComplianceOfficer`. A request that omits either header is rejected with `ERR_UNAUTHENTICATED`. The two open self-registration endpoints — registering a customer and registering a technician — may be called by an unauthenticated `Anonymous` caller; every other endpoint, including read-only retrievals, still requires both headers to be present. When a principal presents valid headers but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

Two roles are entity-backed and two are opaque. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that ultimately references a `Customer` compare that resource's owning customer foreign key to `X-User-ID`. Concretely, a project's `customer_id` and a unit's `customer_id` must equal the acting `Customer`'s `X-User-ID` for that customer to mutate the project, the unit, or any of the unit's children. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks compare the resource's assigned or install technician foreign key (such as a visit's `assigned_tech_id`, a dispatch's `assigned_tech_id`, or a project's `install_tech_id`) to `X-User-ID`. A `Customer` or `Technician` acting on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`, and a technician who is not the assigned or install technician for the targeted resource is rejected with `ERR_NOT_ASSIGNED_TECH`. These ownership and assignment checks apply only to mutating operations; read and list endpoints enforce role authorization but not ownership, so a `Customer` or `Technician` who is permitted the read may retrieve resources (including other principals' records and unfiltered list results) that they do not own.

When `X-User-Role` is `ServiceManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it where a transition writes an acting principal (for example, the closing principal compared during segregation-of-duties enforcement) but does not compare it to any entity's `id` for ownership. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is used to drive recall and warranty adjudication authority and is never matched against an entity `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier used only to satisfy the header requirement on the two open registration endpoints.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100; a `limit` outside this range is clamped to the nearest bound (a value below 1 becomes 1, a value above 100 becomes 100) rather than rejected. The `offset` parameter specifies the number of items to skip and defaults to 0; a negative `offset` is clamped to 0, and a `limit` or `offset` that is not a parseable integer is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. When several resources share the same creation timestamp (common under the logical clock), the tie is broken by creation order — the order in which the resources were minted.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification, refreshed on every mutation. The `version` field is an integer that starts at 1 on creation and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.7.

Two entities are deliberately leaner. A `GeneratorModel` carries only `id` and `created_at` — it has no `updated_at` and no `version`. A `LoadAssessment` and an `ExerciseLog` are likewise append-only records carrying only `id` and `created_at`, with no `updated_at` and no `version`. All other entities — `Customer`, `Technician`, `GeneratorProject`, `Unit`, `MaintenancePlan`, `MaintenanceVisit`, `WarrantyClaim`, `RepairDispatch`, `RecallCampaign`, and `RecallRemediation` — carry the full `id`, `created_at`, `updated_at`, and `version` set.

The system keeps a single logical clock that is the authoritative "now" for every time-dependent rule — compliance scoring, warranty proration, recall deadlines, and missed-visit grace windows. On startup the clock reads exactly `2026-01-01T00:00:00Z` and never falls back to wall-clock time; before any clock-setting call it remains at that default. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant. Advancing the clock is not passive: it triggers recompute passes that sweep scheduled visits past their grace window to `MISSED`, sweep pending or scheduled remediations past their deadline to `OVERDUE`, and recompute the posture of every affected unit (see §2.5 and §3).

### 2.5. Unit Posture, Derived Reconciliation, and Hierarchical Consistency

A `Unit` exposes several fields that no client writes directly. These are recomputed by a unit-posture reconciliation whenever a child of the unit mutates, an exercise log is appended, a recall transition fires, or the clock advances in a way that touches the unit. Each such reconciliation independently mutates the affected resource, refreshing its `updated_at` and incrementing its `version`. The compound field `operating_status` takes one of `OPERATIONAL`, `SERVICE_DUE`, `NON_COMPLIANT`, or `DECOMMISSIONED`. The parallel field `monitoring_health` takes one of `OK`, `DEGRADED`, or `OFFLINE` and tracks remote-monitoring health independently of operating status. The `warranty_status` field takes one of `ACTIVE`, `LAPSED`, or `VOID`. The `compliance_score` is an integer from 0 to 100. The `last_exercise_at`, `runtime_hours`, `next_due_at`, `visits_completed_ytd`, and `visits_per_year` derived fields are similarly maintained by the system rather than supplied by clients.

Recall posture dominates maintenance posture. When a unit becomes `SERVICE_DUE` because an `ACTIVE` maintenance plan's `next_due_at` is at or before the current clock with no completed visit covering it, that `SERVICE_DUE` state only applies while the unit is not `NON_COMPLIANT`; a unit that has an overdue mandatory recall remediation is `NON_COMPLIANT` regardless of any maintenance posture. When a completed visit advances `next_due_at` past the current clock, the unit returns from `SERVICE_DUE` to `OPERATIONAL`. A unit enters `NON_COMPLIANT` from either `OPERATIONAL` or `SERVICE_DUE` when a remediation under a `MANDATORY` campaign on that unit goes `OVERDUE`; entering `NON_COMPLIANT` drives `warranty_status` to `VOID` and `monitoring_health` to `OFFLINE`. When no mandatory remediation on the unit remains overdue, the unit returns from `NON_COMPLIANT` to `OPERATIONAL` and `warranty_status` is recomputed (`ACTIVE` if still within the warranty window, otherwise `LAPSED`). A unit may re-enter `NON_COMPLIANT` under a later recall, so this is a recurring cycle rather than a one-way trip.

For requests that target nested resources, the system validates the path left to right: parents before children. When a path names a parent collection and a child identifier, the parent's existence is confirmed first; the first identifier in the path that does not correspond to an existing resource produces `ERR_NOT_FOUND` before any deeper lookup is attempted. This ordering ensures that an invalid container is caught before any child-level rule runs.

### 2.6. Precision, Rounding, and Money

Monetary values are stored and returned as integer cents. Every rounding step in this system uses the round-half-up convention. Where a calculation pins a specific evaluation order (for instance, applying a discount to an integer subtotal before rounding, or taxing each invoice line independently before summing), that order is part of the contract and is described in §3 alongside the workflow it governs. Sizing is the one non-monetary calculation with its own precision rule: required kilowatts are always rounded up to the next 0.25 kW increment (never rounded down or to nearest). BTU comparisons at the permit step are integer BTU-per-hour values compared with a boundary-inclusive threshold.

### 2.7. Optimistic Concurrency Control

Two write operations require the client to present the version of a parent entity it last observed, so that a write computed against a stale view is rejected rather than silently overwriting another writer's change.

Filing a warranty claim against a unit requires the request to carry `expected_unit_version` matching that `Unit`'s current `version`. If another writer has advanced the unit's `version` since the client last read it — for example, a recall transition that drove `warranty_status` to `VOID` and bumped `Unit.version` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the filer from acting on a warranty state it has not observed.

Assigning a technician to a repair dispatch requires the request to carry `expected_dispatch_version` matching that `RepairDispatch`'s current `version`. If another writer has already assigned or cancelled the dispatch, advancing its `version` since the client last read it, the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412). These two endpoints are the only ones that take a version field; no other endpoint accepts or checks an expected-version input.

### 2.8. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. Authentication comes first: a missing header yields `ERR_UNAUTHENTICATED`. Role authorization comes next: a role not permitted for the operation yields `ERR_FORBIDDEN`. Then path-resource existence is confirmed left to right, yielding `ERR_NOT_FOUND` for the first missing path resource. Then foreign-key body references (such as `customer_id`, `model_id`, `assigned_tech_id`, and `install_tech_id`) are resolved, yielding `ERR_REFERENCE_NOT_FOUND` when a referenced row does not exist. Then the request body is checked for well-formedness — required fields present, enum values valid, numeric ranges respected, and the appliances array non-empty — yielding `ERR_INVALID_REQUEST`; a value that parses but violates a field-level semantic rule (such as a starting-watts figure below its running-watts figure) yields `ERR_VALIDATION`. Ownership is checked next, yielding `ERR_NOT_RESOURCE_OWNER` for an entity-backed actor acting on a resource it does not own. Then optimistic concurrency is checked, yielding `ERR_STALE_VERSION`. Then state-transition legality is checked, yielding `ERR_INVALID_STATE` when the target is not in a state from which the requested transition is allowed. Business-safety and business-constraint checks run last; where multiple of these could fire on one endpoint, the specific check that guards that workflow is described in §3 next to the operation it protects.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Customers, Technicians, and the Model Catalog

A customer record is created by submitting an `email`, a `full_name`, and a `service_address`, with an optional `elevation_ft` (the site elevation above sea level in feet, defaulting to 0 and never negative) and an optional `phone` (defaulting to `null`, and always present as a field on the customer record). The `email` must be unique and non-empty; a second registration with an already-used address is rejected with `ERR_DUPLICATE_EMAIL`. The `id` minted here is what a homeowner later presents as `X-User-ID` when acting in the `Customer` role.

A technician is registered with a `name` and a unique, non-empty `license_no`, plus an optional `gas_certified` flag that defaults to false. A duplicate license number is rejected with `ERR_DUPLICATE_LICENSE`. On registration the technician's `status` is `ACTIVE` and the computed `open_dispatch_count` — the number of repair dispatches assigned to that technician currently in `DISPATCHED` or `IN_PROGRESS` — starts at 0. A `ServiceManager` may later update a technician, changing `status` between `ACTIVE` and `SUSPENDED` or toggling `gas_certified`.

The model catalog is curated by a `ServiceManager`. A `GeneratorModel` is created with a unique, non-empty `sku`, a `rated_kw` continuous rating greater than zero, a `fuel_types` array that is a non-empty subset of natural gas (`NG`) and propane (`PROPANE`), a `unit_price_cents` list price of at least zero, and a `warranty_months` standard warranty length of at least zero, plus an optional `active` availability flag that defaults to true. A duplicate SKU is rejected with `ERR_DUPLICATE_SKU`.

### 3.2. Load Assessment and Sizing

Every install project begins as a `GeneratorProject` created by a customer (for their own `customer_id`) or by a `ServiceManager`. Creation captures the owning `customer_id`, the declared `fuel_type` (either `NG` for natural gas or `PROPANE`, the fuel that will be hooked up), and an optional `model_id` that may be left null until sizing is locked. A fresh project starts in `DRAFT` with `permit_status` of `NONE` and `sizing_method` of `STAGGERED`.

Before a project can be sized, the customer or service manager records one or more load assessments against it. A `LoadAssessment` submits an `appliances` array and an optional `method` that defaults to `STAGGERED`. Each appliance entry carries a `name`, its steady `running_watts`, and its `starting_watts` (the inrush draw at startup). The appliances array must be non-empty; each appliance's `running_watts` must be at least zero, and its `starting_watts` must be at least its `running_watts`. A starting-watts figure below the running-watts figure is a semantic field violation rejected with `ERR_VALIDATION`.

Each assessment computes two derived figures. First, the steady running load is the sum of every appliance's `running_watts`. For each appliance, its surge delta is its `starting_watts` minus its `running_watts`. The `peak_demand_w` then depends on the assessment's `method`. Under `STAGGERED`, motor sequencing is assumed, so only the single largest surge delta across all appliances is added to the running load; `peak_demand_w` is the running load plus that one largest surge delta. Under `FULL_LOAD`, no sequencing is assumed, so every surge delta coincides; `peak_demand_w` is the running load plus the sum of all appliance surge deltas — which yields a strictly larger result than `STAGGERED` for the same appliances. From `peak_demand_w` the required volt-amps is the peak watt demand divided by a power factor of 0.8. The `computed_required_kw` is that volt-amps figure divided by 1000, then rounded up to the next 0.25 kW increment — that is, divide by 0.25, take the ceiling to a whole number, and multiply back by 0.25, so the result always lands on a quarter-kilowatt boundary and is never rounded down.

A `ServiceManager` locks sizing by selecting one assessment and one model. The size operation takes an `assessment_id` and a `model_id` in its body and advances the project from `DRAFT` to `SIZED`. The selected assessment must belong to the project; sizing with no assessment, or naming an assessment that is not on the project, is rejected with `ERR_NO_ASSESSMENT`. The chosen model must currently be active — a model with `active` false at sizing time is rejected with `ERR_MODEL_INACTIVE`. The model must be adequate: its `rated_kw` must be at least the selected assessment's required kilowatts, and its `fuel_types` must include the project's declared `fuel_type`; a model whose rating is below the requirement or whose fuel list excludes the project fuel is rejected with `ERR_MODEL_UNDERSIZED`. On success the project's `required_kw` and `sizing_method` are copied from the selected assessment, `model_id` is set, the status moves to `SIZED`, and the project's `version` increments by one.

### 3.3. Permit, Fuel Hookup, and Installation

With sizing locked, a `ServiceManager` pulls the permit and verifies the fuel hookup in a single permit operation that advances the project from `SIZED` to `PERMITTED`. The body carries a `permit_number`, a `permit_decision`, a `fuel_supply_btu_per_hr` figure, and an optional `existing_load_btu_per_hr` (treated as zero when absent). A decision of approve sets `permit_status` to `APPROVED`; a prior `REJECTED` permit may be re-submitted with approve to recover. A decision of reject instead records the `permit_number`, sets `permit_status` to `REJECTED`, runs no fuel BTU check, leaves the project in `SIZED` (so it can later be re-submitted), bumps the project's `version`, and returns 200. Approval also runs the fuel BTU adequacy check: the required BTU per hour is the project's `required_kw` multiplied by 10,000 (the same per-kilowatt demand applies to both natural gas and propane), and the available BTU per hour is `fuel_supply_btu_per_hr` minus `existing_load_btu_per_hr`. The supply is sufficient when the available BTU per hour is greater than or equal to the required BTU per hour — the boundary is inclusive, so available exactly equal to required is sufficient. If the supply is insufficient, the permit is rejected with `ERR_FUEL_INADEQUATE`. On a successful approval the `permit_number` is recorded, `permit_status` becomes `APPROVED`, the computed `fuel_hookup_verified` flag becomes true, the status moves to `PERMITTED`, and the project's `version` increments by one.

A `Technician` (or a `ServiceManager`) then records the physical install, advancing the project from `PERMITTED` to `INSTALLED`. The body supplies an `install_tech_id` and an `ats_amps` ampacity for the automatic transfer switch. The named install technician must be `ACTIVE` and must hold `gas_certified` true — required to sign off the propane or natural-gas fuel hookup; a suspended or non-gas-certified technician is rejected with `ERR_TECH_NOT_QUALIFIED`. The recorded `ats_amps` must be greater than zero. On success `install_tech_id` and `ats_amps` are recorded, the status moves to `INSTALLED`, and the project's `version` increments by one.

### 3.4. Activation, Unit Minting, and Registration

Activation is the hinge between the two phases. A `ServiceManager` activates an installed project, advancing it from `INSTALLED` to its terminal `ACTIVATED` state and minting a `Unit`. The body supplies a `serial_no` and an optional `monitoring_enabled` toggle (defaulting to false) that is stored as the minted unit's `monitoring_enabled` flag (the unit's `monitoring_health` is `OFFLINE` at mint regardless of this toggle). Activation is gated twice: the project's `permit_status` must be `APPROVED` and `fuel_hookup_verified` must be true, otherwise the request is rejected with `ERR_PERMIT_NOT_APPROVED`; and the supplied `serial_no` must be unique and non-empty across all units, with a collision rejected as `ERR_DUPLICATE_SERIAL`. On success the system mints a `Unit` that snapshots the project's `model_id`, the model's `rated_kw` into the unit's `rated_kw`, the project's `fuel_type`, and the model's warranty length into `warranty_total_months`; the unit's `warranty_start` is set to the current clock as the warranty-clock origin, its `serial_no` is recorded, `registration_status` is `UNREGISTERED`, `operating_status` is `OPERATIONAL`, `monitoring_health` is `OFFLINE`, `warranty_status` is `ACTIVE`, `compliance_score` is 0, and `runtime_hours` is 0. The unit's `project_id` and `customer_id` are carried from the project. The project's `unit_id` is then set to the new unit, the project's status moves to `ACTIVATED`, and the project's `version` increments by one. Because activation is terminal for the project, all further lifecycle lives on the unit.

A non-activated project may be cancelled by a `ServiceManager` from `DRAFT`, `SIZED`, `PERMITTED`, or `INSTALLED`, capturing a `cancellation_reason` and moving the project to its terminal `CANCELLED` state with the `version` incremented by one. A project that is already `ACTIVATED` or `CANCELLED` cannot be cancelled — once a unit exists, the decommission path on the unit is used instead.

Once a unit exists, a customer (for their own unit) or a `ServiceManager` can toggle remote monitoring or register the unit. The update accepts an optional `monitoring_enabled` toggle and an optional `register` flag. Setting `register` true moves `registration_status` to `REGISTERED` and extends coverage by adding a 12-month registration bonus to `warranty_total_months`. Registration is idempotent: if the unit is already `REGISTERED`, a later `register` true leaves `registration_status` unchanged and adds no further bonus — the 12-month bonus is applied only on the first registration. Any such update recomputes `monitoring_health` and increments the unit's `version` by one (the version is bumped even when the body changes nothing).

### 3.5. Exercise Logging, Compliance Scoring, and Monitoring Health

Standby generators self-test on a schedule, and the system tracks that discipline through append-only exercise logs. A customer (or a `ServiceManager`) appends an `ExerciseLog` to a unit by submitting an `occurred_at` instant (a logical-clock timestamp), a `result` of either `SUCCESS` or `FAULT`, and an optional `runtime_minutes` duration that defaults to 12 and must be at least zero. A `SUCCESS` log updates the unit's `last_exercise_at`. Appending a log recomputes the compliance score and then monitoring health.

The compliance score measures how faithfully the unit has self-tested against an expected weekly cadence. The number of whole days the unit has been in service is the floor of the elapsed days from `warranty_start` to the current clock, never below zero. The expected number of exercises so far is that day count divided by 7 and floored — one expected exercise per week of service. The completed count is the number of this unit's exercise logs whose `result` is `SUCCESS` and whose `occurred_at` is at or before the current clock; `FAULT` exercises are logged but never count toward completed. If the expected count is zero or below, `compliance_score` is 100. Otherwise it is 100 multiplied by completed divided by expected, rounded half up and then clamped to the 0-to-100 range.

Monitoring health is a parallel axis that flips on a compliance threshold of 70, evaluated only while `monitoring_enabled` is true and the unit is not `NON_COMPLIANT`. From `OFFLINE`, the unit's `monitoring_health` becomes `OK` once monitoring is enabled and `compliance_score` is at least 70. From `OK` it drops to `DEGRADED` when `compliance_score` falls below 70 while monitoring stays enabled, and from `DEGRADED` it recovers to `OK` when `compliance_score` returns to at least 70 — the threshold is inclusive on the at-least-70 side, so a score of exactly 70 is healthy. Turning `monitoring_enabled` off, or the unit becoming `NON_COMPLIANT`, drives `monitoring_health` back to `OFFLINE`.

### 3.6. Maintenance Plans and Visits

A maintenance plan covers a unit with a recurring visit cadence. A customer (or a `ServiceManager`) creates a `MaintenancePlan` on a unit by choosing a `frequency` of either `ANNUAL` or `SEMI_ANNUAL` and an optional `monitoring_bundled` flag that defaults to false. A unit that is `NON_COMPLIANT` because of an overdue mandatory recall cannot accept a new maintenance plan; the create is rejected with `ERR_UNIT_NON_COMPLIANT`. On creation the plan starts `ACTIVE`, its `visits_per_year` is set to 2 for `SEMI_ANNUAL` or 1 for `ANNUAL`, its `visits_completed_ytd` starts at 0, its `next_due_at` is computed as the plan's creation instant advanced by (`visits_completed_ytd` + 1) cadence periods — a cadence period being twelve months for `ANNUAL` or six months for `SEMI_ANNUAL` — so a brand-new plan is due exactly one period after creation and each completed visit later pushes `next_due_at` forward by one further period (day-of-month overflow is clamped to the last valid day of the target month), and its `annual_price_cents` is priced as follows.

The per-visit price is tiered by the unit's `rated_kw`: a unit rated at 14 kW or below prices each visit at 18000 cents; a unit rated above 14 kW but at or below 24 kW prices each visit at 26000 cents; a unit rated above 24 kW prices each visit at 34000 cents. The subtotal is that per-visit price multiplied by `visits_per_year`, plus a 6000-cent monitoring add-on when `monitoring_bundled` is true (and nothing when it is false). When and only when the plan is both `monitoring_bundled` and `SEMI_ANNUAL`, a 10% bundle discount applies: `annual_price_cents` is the subtotal multiplied by the remaining 90% (one minus the discount), rounded half up — the discount is applied to the integer subtotal before rounding. In every other combination, `annual_price_cents` equals the subtotal with no discount.

Scheduling a visit under a plan creates a `MaintenanceVisit` with a `scheduled_for` timestamp and an optional `assigned_tech_id`. A new visit starts `SCHEDULED`. Two scheduling collisions are enforced. First, the unit cannot already have a `SCHEDULED` visit on the same UTC calendar day: the day is treated as a closed bucket spanning the whole calendar date, so any two visit timestamps sharing the same UTC date collide regardless of the hour, and the second is rejected with `ERR_UNIT_VISIT_COLLISION`. Second, when an `assigned_tech_id` is provided, that technician must not already have a `SCHEDULED` visit whose `scheduled_for` falls within a four-hour buffer of the new one — specifically, the new visit is rejected with `ERR_TECH_DOUBLE_BOOKED` if it lies in the half-open window from four hours before the other visit up to (but not including) four hours after it. A new visit exactly four hours after an existing one is allowed because the right boundary is open.

The assigned `Technician` completes a scheduled visit, optionally supplying `runtime_added_hours` (defaulting to 0, at least zero). Completion is gated: the acting technician must be the visit's `assigned_tech_id`, the owning plan must be `ACTIVE`, and the owning unit must not be `DECOMMISSIONED`; additionally a unit that is `NON_COMPLIANT` cannot have a visit completed, which is rejected with `ERR_UNIT_NON_COMPLIANT`. On completion the visit's `performed_at` is set to the current clock, the supplied `runtime_added_hours` is added to the unit's `runtime_hours`, the plan's `visits_completed_ytd` increments by one, `next_due_at` is recomputed, the unit's posture is recomputed (which may clear `SERVICE_DUE` back to `OPERATIONAL`), and the visit's `version` increments by one. A scheduled visit may instead be cancelled by a customer or `ServiceManager`, moving it to `CANCELLED` and incrementing its `version`. The system also sweeps a still-scheduled visit to `MISSED` when its `scheduled_for` plus a seven-day grace window is earlier than the current clock and it has not been completed; a missed visit can flip the unit to `SERVICE_DUE`.

A plan can be paused and resumed in a cycle. A customer (or `ServiceManager`) suspends an `ACTIVE` plan, freezing `next_due_at` so visits are no longer auto-required and incrementing the plan's `version`. Resuming a `SUSPENDED` plan requires the owning unit not to be `DECOMMISSIONED`; it recomputes `next_due_at`, recomputes the unit's posture, and increments the plan's `version`. A plan may be cancelled from either `ACTIVE` or `SUSPENDED`, which cancels its `SCHEDULED` visits, recomputes the unit's posture, and increments the plan's `version`.

### 3.7. Warranty Claims and Adjudication

A warranty claim travels through a review loop before terminal adjudication. A customer (or `ServiceManager`) files a `WarrantyClaim` on a unit by submitting a `description` and the `expected_unit_version` required by the optimistic-concurrency rule in §2.7; the claim is created in `OPEN` status (with `resolution` null, `refund_cents` 0, `refund_basis` `CALENDAR`, and `dispatch_id` null) and the unit's `version` is bumped. A `ComplianceOfficer` moves a claim from `OPEN` to `UNDER_REVIEW`, but only while the unit's `warranty_status` is `ACTIVE` at the time of review — a unit whose warranty is `LAPSED` or `VOID` blocks review with `ERR_WARRANTY_LAPSED`. From `UNDER_REVIEW` the officer may return the claim for more information, bouncing it back to `OPEN`; the claim can oscillate between `OPEN` and `UNDER_REVIEW` any number of times before a terminal decision.

Adjudication acts on an `UNDER_REVIEW` claim and carries a `decision` plus, for an approval, a `resolution` and an optional `refund_basis`. A decision to approve again requires the unit's `warranty_status` to be `ACTIVE` (not `LAPSED`, not `VOID`), failing with `ERR_WARRANTY_LAPSED` otherwise, and the `resolution` must be either `REPAIR_COVERED` or `PRORATED_REFUND`. When the resolution is `REPAIR_COVERED`, the system spawns a `RepairDispatch` with origin `WARRANTY` in `REQUESTED` status and records its id as the claim's `dispatch_id`. When the resolution is `PRORATED_REFUND`, the system computes `refund_cents` using the chosen `refund_basis` (defaulting to `CALENDAR`) and the warranty proration described below. A decision to deny sets `resolution` to `NO_FAULT_FOUND` and leaves `refund_cents` at 0. Either terminal decision moves the claim to `APPROVED` or `DENIED` and increments its `version`. A customer who owns the claimed unit may withdraw a claim from either `OPEN` or `UNDER_REVIEW`, moving it to `WITHDRAWN` and incrementing its `version`.

The prorated refund proration works as follows. The total warranty term is the unit's `warranty_total_months`. The calendar-elapsed months is the whole months from the unit's `warranty_start` to the current clock, floored. The usage-elapsed months is the unit's `runtime_hours` divided by 50 hours per equivalent month, rounded up to a whole number. The elapsed figure depends on `refund_basis`: under `CALENDAR` the elapsed is the calendar-elapsed months only, ignoring runtime; under `USAGE` the elapsed is the larger of the calendar-elapsed months and the usage-elapsed months, so a heavily run unit ages faster and earns a smaller refund than `CALENDAR` would for the same dates. The remaining months is the total minus the elapsed, floored at zero so it never goes negative. The `refund_cents` is a coverage value of 240000 cents multiplied by remaining divided by total, rounded half up to whole cents.

### 3.8. Repair Dispatch, Invoicing, and Segregation of Duties

A repair dispatch can originate three ways, recorded in its `origin`: a customer or `ServiceManager` requests a `PAID` dispatch directly on a unit (optionally supplying `labor_cents` and `parts_cents`, each defaulting to 0 and at least zero); an approved `REPAIR_COVERED` warranty claim spawns a `WARRANTY` dispatch and links the source claim through `warranty_claim_id`; and a scheduled recall remediation spawns a `RECALL` dispatch. A dispatch is `billable` only when its origin is `PAID` — `WARRANTY` and `RECALL` dispatches are no-charge and carry an `invoice_total_cents` of 0. Every dispatch starts in `REQUESTED`.

A `ServiceManager` assigns a technician, advancing the dispatch from `REQUESTED` to `DISPATCHED`. The assign body carries an `assigned_tech_id` and the `expected_dispatch_version` required by the optimistic-concurrency rule in §2.7. The named technician must be `ACTIVE` (a technician whose `status` is not `ACTIVE` is rejected with `ERR_INVALID_STATE`), and the technician's `open_dispatch_count` must be below 5 — a technician already at five open dispatches is rejected with `ERR_TECH_OVERLOADED`. On assignment the `assigned_tech_id` is recorded, the technician's `open_dispatch_count` increments by one, and the dispatch's `version` increments. The assigned technician then drives the field-work cycle: starting work advances `DISPATCHED` to `IN_PROGRESS`; pausing advances `IN_PROGRESS` back to `DISPATCHED`, and a dispatch may oscillate between `DISPATCHED` and `IN_PROGRESS` across multiple field visits. Each of start, pause, and resolve requires the acting technician to be the dispatch's `assigned_tech_id`.

Resolving advances `IN_PROGRESS` to `RESOLVED`, optionally adding `runtime_added_hours` (defaulting to 0, at least zero) to the unit's `runtime_hours`. A unit that is `NON_COMPLIANT` blocks resolution of a non-recall dispatch with `ERR_UNIT_NON_COMPLIANT`; recall-origin resolution is exempt because it is the very work that clears the non-compliance. On resolve the system records `resolved_by_tech_id` as the acting technician, and, when the dispatch is billable, computes `invoice_total_cents`. The invoice is computed per line then summed: the two lines are `labor_cents` and then `parts_cents` in that fixed order; each present line (a zero line is skipped from the sum) is taxed independently at a tax rate of 8.75% and rounded half up to whole cents, and the rounded line totals are summed last. This per-line-then-sum order is contractual and can differ from taxing the sum: for example, lines of 100, 100, and 100 cents at 8.75% give 327 cents under per-line rounding versus 326 cents under sum-then-round. Resolving also decrements the assigned technician's `open_dispatch_count` by one, and, when the dispatch origin is `RECALL`, cascades the linked recall remediation to `COMPLETED`.

A `ServiceManager` closes a `RESOLVED` dispatch, but segregation of duties forbids self-closing: the closing principal's `X-User-ID` must differ from the dispatch's `resolved_by_tech_id`, otherwise the close is rejected with `ERR_SEGREGATION_VIOLATION`. Closing advances `RESOLVED` to `CLOSED`, recomputes the unit's posture, and increments the dispatch's `version`. A dispatch in `REQUESTED` or `DISPATCHED` may be cancelled by a `ServiceManager` — but it cannot be cancelled once `IN_PROGRESS`; if it was `DISPATCHED`, cancelling decrements the assigned technician's `open_dispatch_count` by one. Both close and cancel move the dispatch to a terminal state (`CLOSED` and `CANCELLED` respectively).

### 3.9. Recall Campaigns, Remediation, and Decommissioning

A `ComplianceOfficer` opens recalls against a model. A `RecallCampaign` is created in `DRAFT` with a `model_id`, a unique non-empty `code`, a `severity` of either `ADVISORY` or `MANDATORY`, and an optional `remediation_window_days` (the days each affected unit has to remediate after the campaign opens, defaulting to 90 and greater than zero). A duplicate recall code is rejected with `ERR_DUPLICATE_RECALL_CODE`. Opening a campaign sets `opened_at` to the current clock and fans out: for every `ACTIVATED` unit whose `model_id` matches the campaign's model and whose `operating_status` is not `DECOMMISSIONED`, the system creates a `RecallRemediation` in `PENDING` status whose `deadline_at` is `opened_at` plus `remediation_window_days`. The campaign's `affected_unit_count` is set to the number of remediations created, and the campaign's `version` increments. A campaign may later be closed by a `ComplianceOfficer`, but only when no remediation under it is still `PENDING` or `SCHEDULED`; closing with open remediations is rejected with `ERR_CAMPAIGN_HAS_OPEN_REMEDIATIONS`. A campaign also tracks `remediated_count`, the number of its remediations that have reached `COMPLETED`.

A `ServiceManager` schedules a `PENDING` remediation, spawning a `RECALL`-origin repair dispatch in `REQUESTED`, recording its id on the remediation's `dispatch_id`, and moving the remediation to `SCHEDULED`. Scheduling requires the remediation to be `PENDING` and not already `OVERDUE` — an attempt to schedule an already-overdue remediation is rejected with `ERR_REMEDIATION_OVERDUE` — and the owning unit must not be `DECOMMISSIONED`. A remediation goes `OVERDUE` (from `PENDING` or `SCHEDULED`) by a clock-advance sweep when its `deadline_at` is earlier than the current clock and it has not completed; when the campaign's `severity` is `MANDATORY`, going overdue recomputes the unit's posture to `NON_COMPLIANT` and drives `warranty_status` to `VOID`. `OVERDUE` is not terminal: a remediation that has gone overdue can still complete. When the linked `RECALL` dispatch reaches `RESOLVED`, the remediation cascades to `COMPLETED` (reachable whether it was `SCHEDULED` or had already gone `OVERDUE`): its `completed_at` is set to the current clock, the campaign's `remediated_count` increments, and the unit's posture is recomputed — if this cleared the last overdue mandatory remediation, the unit returns from `NON_COMPLIANT` to `OPERATIONAL` and its `warranty_status` is restored. The remediation also tracks the owning `campaign_id` and `unit_id`.

A `ServiceManager` decommissions a unit from `OPERATIONAL`, `SERVICE_DUE`, or `NON_COMPLIANT`, but only when the unit has no repair dispatch currently in `DISPATCHED` or `IN_PROGRESS`; a blocking in-flight dispatch is rejected with `ERR_DISPATCH_IN_PROGRESS`. Decommissioning moves `operating_status` to its terminal `DECOMMISSIONED` state, cancels the unit's `ACTIVE` and `SUSPENDED` maintenance plans, cancels its `SCHEDULED` maintenance visits, turns `monitoring_enabled` off and `monitoring_health` to `OFFLINE`, and increments the unit's `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection (such as registering a customer, creating a model, filing a warranty claim, or scheduling a visit) return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock and run recompute sweeps | ServiceManager, ComplianceOfficer |
| POST | `/customers` | Register a customer | Anonymous, ServiceManager |
| GET | `/customers/{customer_id}` | Get a customer | Customer, ServiceManager, ComplianceOfficer |
| GET | `/customers/{customer_id}/projects` | List a customer's projects | Customer, ServiceManager, ComplianceOfficer |
| GET | `/customers/{customer_id}/units` | List a customer's units | Customer, ServiceManager, ComplianceOfficer |
| POST | `/technicians` | Register a technician | Anonymous, ServiceManager |
| GET | `/technicians/{technician_id}` | Get a technician | Technician, ServiceManager, ComplianceOfficer |
| PATCH | `/technicians/{technician_id}` | Update technician status / certification | ServiceManager |
| POST | `/models` | Create a catalog model | ServiceManager |
| GET | `/models/{model_id}` | Get a model | Customer, Technician, ServiceManager, ComplianceOfficer |
| GET | `/models/{model_id}/recall-campaigns` | List recall campaigns for a model | ServiceManager, ComplianceOfficer |
| POST | `/projects` | Create a project | Customer, ServiceManager |
| GET | `/projects` | List/filter projects | Customer, ServiceManager, ComplianceOfficer |
| GET | `/projects/{project_id}` | Get a project | Customer, Technician, ServiceManager, ComplianceOfficer |
| POST | `/projects/{project_id}/load-assessments` | Create a load assessment | Customer, ServiceManager |
| GET | `/projects/{project_id}/load-assessments` | List a project's load assessments | Customer, ServiceManager, ComplianceOfficer |
| POST | `/projects/{project_id}/size` | Lock sizing, DRAFT → SIZED | ServiceManager |
| POST | `/projects/{project_id}/permit` | Permit + fuel verification, SIZED → PERMITTED | ServiceManager |
| POST | `/projects/{project_id}/install` | Record install + ATS, PERMITTED → INSTALLED | Technician, ServiceManager |
| POST | `/projects/{project_id}/activate` | Activate & register, mint Unit, INSTALLED → ACTIVATED | ServiceManager |
| POST | `/projects/{project_id}/cancel` | Cancel a non-activated project | ServiceManager |
| GET | `/units` | List/filter units | Customer, ServiceManager, ComplianceOfficer |
| GET | `/units/{unit_id}` | Get a unit | Customer, Technician, ServiceManager, ComplianceOfficer |
| PATCH | `/units/{unit_id}` | Toggle monitoring or register the unit | Customer, ServiceManager |
| POST | `/units/{unit_id}/decommission` | Decommission a unit | ServiceManager |
| POST | `/units/{unit_id}/exercise-logs` | Append an exercise log | Customer, ServiceManager |
| GET | `/units/{unit_id}/exercise-logs` | List a unit's exercise logs | Customer, ServiceManager, ComplianceOfficer |
| POST | `/units/{unit_id}/maintenance-plans` | Create a maintenance plan | Customer, ServiceManager |
| GET | `/units/{unit_id}/maintenance-plans` | List a unit's maintenance plans | Customer, ServiceManager, ComplianceOfficer |
| POST | `/units/{unit_id}/warranty-claims` | File a warranty claim | Customer, ServiceManager |
| GET | `/units/{unit_id}/warranty-claims` | List a unit's warranty claims | Customer, ServiceManager, ComplianceOfficer |
| POST | `/units/{unit_id}/repair-dispatches` | Request a PAID repair dispatch | Customer, ServiceManager |
| GET | `/units/{unit_id}/repair-dispatches` | List a unit's repair dispatches | Customer, Technician, ServiceManager, ComplianceOfficer |
| GET | `/units/{unit_id}/remediations` | List remediations targeting a unit | ServiceManager, ComplianceOfficer |
| GET | `/maintenance-plans` | List/filter maintenance plans | Customer, ServiceManager, ComplianceOfficer |
| GET | `/maintenance-plans/{plan_id}` | Get a maintenance plan | Customer, Technician, ServiceManager, ComplianceOfficer |
| POST | `/maintenance-plans/{plan_id}/suspend` | Suspend a plan | Customer, ServiceManager |
| POST | `/maintenance-plans/{plan_id}/resume` | Resume a suspended plan | Customer, ServiceManager |
| POST | `/maintenance-plans/{plan_id}/cancel` | Cancel a plan | Customer, ServiceManager |
| POST | `/maintenance-plans/{plan_id}/visits` | Schedule a maintenance visit | Customer, ServiceManager |
| GET | `/maintenance-plans/{plan_id}/visits` | List a plan's visits | Customer, Technician, ServiceManager, ComplianceOfficer |
| GET | `/maintenance-visits` | List/filter visits | Customer, Technician, ServiceManager, ComplianceOfficer |
| GET | `/maintenance-visits/{visit_id}` | Get a visit | Customer, Technician, ServiceManager, ComplianceOfficer |
| POST | `/maintenance-visits/{visit_id}/complete` | Complete a visit (assigned tech) | Technician |
| POST | `/maintenance-visits/{visit_id}/cancel` | Cancel a scheduled visit | Customer, ServiceManager |
| GET | `/load-assessments` | List/filter load assessments | Customer, ServiceManager, ComplianceOfficer |
| GET | `/load-assessments/{assessment_id}` | Get a load assessment | Customer, ServiceManager, ComplianceOfficer |
| GET | `/exercise-logs` | List/filter exercise logs | Customer, ServiceManager, ComplianceOfficer |
| GET | `/exercise-logs/{log_id}` | Get an exercise log | Customer, ServiceManager, ComplianceOfficer |
| GET | `/warranty-claims` | List/filter warranty claims | Customer, ServiceManager, ComplianceOfficer |
| GET | `/warranty-claims/{claim_id}` | Get a warranty claim | Customer, ServiceManager, ComplianceOfficer |
| POST | `/warranty-claims/{claim_id}/review` | Move OPEN → UNDER_REVIEW | ComplianceOfficer |
| POST | `/warranty-claims/{claim_id}/return-for-info` | Bounce UNDER_REVIEW → OPEN | ComplianceOfficer |
| POST | `/warranty-claims/{claim_id}/adjudicate` | Adjudicate to APPROVED or DENIED | ComplianceOfficer |
| POST | `/warranty-claims/{claim_id}/withdraw` | Withdraw a claim | Customer, ServiceManager |
| GET | `/repair-dispatches` | List/filter repair dispatches | Customer, Technician, ServiceManager, ComplianceOfficer |
| GET | `/repair-dispatches/{dispatch_id}` | Get a repair dispatch | Customer, Technician, ServiceManager, ComplianceOfficer |
| POST | `/repair-dispatches/{dispatch_id}/assign` | Assign a tech, REQUESTED → DISPATCHED | ServiceManager |
| POST | `/repair-dispatches/{dispatch_id}/start` | Start work, DISPATCHED → IN_PROGRESS | Technician |
| POST | `/repair-dispatches/{dispatch_id}/pause` | Pause work, IN_PROGRESS → DISPATCHED | Technician |
| POST | `/repair-dispatches/{dispatch_id}/resolve` | Resolve, IN_PROGRESS → RESOLVED | Technician |
| POST | `/repair-dispatches/{dispatch_id}/close` | Close, RESOLVED → CLOSED | ServiceManager |
| POST | `/repair-dispatches/{dispatch_id}/cancel` | Cancel a REQUESTED/DISPATCHED dispatch | ServiceManager |
| POST | `/recall-campaigns` | Create a recall campaign | ComplianceOfficer |
| GET | `/recall-campaigns` | List/filter recall campaigns | ServiceManager, ComplianceOfficer |
| GET | `/recall-campaigns/{campaign_id}` | Get a recall campaign | ServiceManager, ComplianceOfficer |
| POST | `/recall-campaigns/{campaign_id}/open` | Open a campaign, fan out remediations | ComplianceOfficer |
| POST | `/recall-campaigns/{campaign_id}/close` | Close a campaign | ComplianceOfficer |
| GET | `/recall-campaigns/{campaign_id}/remediations` | List a campaign's remediations | ServiceManager, ComplianceOfficer |
| GET | `/recall-remediations` | List/filter recall remediations | ServiceManager, ComplianceOfficer |
| GET | `/recall-remediations/{remediation_id}` | Get a recall remediation | ServiceManager, ComplianceOfficer |
| POST | `/recall-remediations/{remediation_id}/schedule` | Schedule a remediation, PENDING → SCHEDULED | ServiceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_UNIT_NON_COMPLIANT` | 409 Conflict |
| `ERR_WARRANTY_LAPSED` | 409 Conflict |
| `ERR_TECH_NOT_QUALIFIED` | 409 Conflict |
| `ERR_MODEL_UNDERSIZED` | 409 Conflict |
| `ERR_FUEL_INADEQUATE` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_SEGREGATION_VIOLATION` | 409 Conflict |
| `ERR_TECH_OVERLOADED` | 409 Conflict |
| `ERR_NO_ASSESSMENT` | 409 Conflict |
| `ERR_PERMIT_NOT_APPROVED` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_LICENSE` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_DUPLICATE_RECALL_CODE` | 409 Conflict |
| `ERR_MODEL_INACTIVE` | 409 Conflict |
| `ERR_REMEDIATION_OVERDUE` | 409 Conflict |
| `ERR_CAMPAIGN_HAS_OPEN_REMEDIATIONS` | 409 Conflict |
| `ERR_DISPATCH_IN_PROGRESS` | 409 Conflict |
| `ERR_NOT_ASSIGNED_TECH` | 403 Forbidden |
| `ERR_TECH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_UNIT_VISIT_COLLISION` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
