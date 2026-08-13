# Blow Molding & Bottle Plant API — Product Requirements Document

## 1. Introduction

A blow-molding bottle plant earns its margin in two places at once: on the production floor, where cavitation, cycle time, resin drawdown, and purge losses decide whether a run makes money, and on the shipping dock, where a trailer full of empty bottles is mostly paid-for air. This document specifies the API for operating such a plant end to end — from onboarding a customer and qualifying a bottle specification, through mold installation, cavity blockouts, line scheduling, material release, and production runs, to AQL quality disposition, freight-of-air pricing, and dock appointments. The commercial tension the system must resolve is constant: dense preforms ship cheaply but require a blow-on-site machine fee at the customer's plant, while finished bottles ship expensively but arrive ready to fill, and every scheduling decision consumes customer credit against a hard limit.

The API enforces segregation of duties across six roles, evaluates every request against a logical plant clock rather than wall-clock time, protects four hotspot write operations with optimistic concurrency control, and reconciles every consequence of an action immediately — a closed run debits resin lots, refreshes the line's color memory, rolls order quantities up, and spawns a quality test lot in a single atomic gesture. Sections 2 and 3 together are the complete behavioral contract; section 4 is the HTTP index into that contract; section 5 catalogs every error identifier.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representations, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request whose `X-User-Role` header is missing, does not name one of the declared roles, or whose `X-User-ID` header is missing or empty is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The six declared roles are `PlantAdmin`, `ProcessEngineer`, `QualityTechnician`, `ProductionScheduler`, `LogisticsCoordinator`, and `CustomerQualityRep`. Each endpoint admits a specific set of roles (enumerated in §4); a caller whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

`PlantAdmin` is the plant administrator: it owns configuration (customers, machine lines, molds, freight rate cards, material receiving), drives the logical clock, and is the only role allowed to void a closed production run. `ProcessEngineer` owns bottle specifications and their edits, qualification-run creation and execution, mold installation and removal, cavity blockouts, and the start and close of production runs. `QualityTechnician` is the quality gatekeeper: it releases, re-holds, and rejects material lots, submits qualification runs for customer review, samples and records results on quality test lots, dispositions rejected lots, and places running orders on QC hold. `ProductionScheduler` owns production orders, scheduling and rescheduling, release, cancellation, completion, and slot cancellation. `LogisticsCoordinator` owns freight quotes, shipments, and dock appointments. `CustomerQualityRep` is the customer-side reviewer who decides qualification outcomes.

For five of the six roles — `PlantAdmin`, `ProcessEngineer`, `QualityTechnician`, `ProductionScheduler`, and `LogisticsCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `recorded_by_user_id` or `dispositioned_by_user_id` on a quality test lot, where transitions write it) but never compares it against any entity's `id`. When `X-User-Role` is `CustomerQualityRep`, by contrast, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's customer foreign-key field to `X-User-ID`. A `CustomerQualityRep` who attempts to review a qualification run belonging to a different customer, or to list another customer's specifications, is rejected with `ERR_CROSS_CUSTOMER_ACCESS` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Every list response orders its rows by `created_at` ascending; because timestamps are recorded at millisecond resolution, ties are impossible to observe and no secondary id-based tie-break is ever applied. Paginated list responses expose `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Plant Clock

The plant does not consult wall-clock time. Every datetime comparison the server performs — schedule slot windows, dock appointment windows, the `blocked_at` stamp on a cavity blockout, no-show eligibility — reads a single logical clock. That clock starts at exactly 2026-08-01T00:00:00Z before any client intervention, and the server never falls back to wall-clock time. A `PlantAdmin` advances it through the test-driving capability mounted at `/plant/_clock/set_current_utc`, which accepts a `to_iso8601` instant and answers with the resulting `current_utc`. Workflows in §3 phrase every temporal rule in terms of this clock.

### 2.5. Common Resource Properties

Every resource in the system — customers, freight rate cards, bottle specs, qualification runs, molds, cavity blockouts, machine lines, schedule slots, material lots, production orders, production runs, quality test lots, shipments, and dock appointments — carries four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp is an ISO 8601 UTC value with three fractional digits recording creation. The `updated_at` timestamp follows the same format and refreshes on every modification. The `version` is an integer that increments by one on every mutation of the resource, whether the mutation comes from an explicit client action or from a system-driven cascade or recompute that changes the resource's stored state. Clients never supply `id`, `created_at`, `updated_at`, or `version`; they observe them.

### 2.6. Nested Resources and Identifier Resolution

Requests that name several resources — whether through nested URL paths or through foreign keys in the request body — resolve their identifiers strictly left to right, and the first identifier that fails to resolve determines the error. Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_BOTTLE_SPEC_NOT_FOUND`, `ERR_QUALIFICATION_RUN_NOT_FOUND`, `ERR_MOLD_NOT_FOUND`, `ERR_CAVITY_BLOCKOUT_NOT_FOUND`, `ERR_MACHINE_LINE_NOT_FOUND`, `ERR_SCHEDULE_SLOT_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`, `ERR_PRODUCTION_ORDER_NOT_FOUND`, `ERR_PRODUCTION_RUN_NOT_FOUND`, `ERR_QUALITY_TEST_LOT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, and `ERR_DOCK_APPOINTMENT_NOT_FOUND` (all HTTP 404). A blockout listed under a mold that does not exist therefore surfaces `ERR_MOLD_NOT_FOUND` before the blockout itself is ever considered. One further existence rule is commercial rather than hierarchical: any freight computation requires an `ACTIVE` freight rate card to exist, and its absence is reported as `ERR_RATE_CARD_NOT_FOUND` (HTTP 404).

### 2.7. Optimistic Concurrency Control

Four write operations guard a parent aggregate against stale client views through optimistic concurrency control. In each case the request must carry a non-optional field containing the version of the parent entity the client last observed, and the server compares it against the parent entity's current `version` before applying any other state rule; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Opening a cavity blockout against a mold requires `expected_mold_version` to equal that mold's current `version`. If another writer has advanced the mold's version since the client last read it — for example by opening another blockout or by installing the mold — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the mold's cavitation state is stale. Scheduling a production order, including re-slotting an already `SCHEDULED` order onto a new window, requires `expected_production_order_version` matching the order's current `version`; rescheduling a `HELD` order back onto the calendar requires the same field with the same staleness rejection. Creating a qualification run requires `expected_bottle_spec_version` matching the spec's current `version`, since the run pins the spec's content revision and a client holding an older version may be qualifying a superseded revision. Endpoints not named here take no version field at all.

### 2.8. Numbers, Precision, and Rounding

Money is integer cents throughout: `credit_limit_cents`, `unit_price_cents`, `rate_cents_per_kg`, and `freight_cost_cents` are whole cents, and the freight engine rounds each marginal tier's charge half-up to whole cents before summing. Physical weights reported in kilograms — `actual_drawdown_kg`, `provisional_consumption_kg`, `purge_kg`, `actual_weight_kg`, and the reconciliation variance `consumption_variance_pct` — are rounded half-up to two decimal places. Dimensional weight obeys a deliberately different discipline: it is computed per pallet, each pallet rounded half-up to one decimal of a kilogram, and only then summed. Cycle time is rounded half-up to two decimal places, while cycles-per-hour is carried unrounded and only the final hourly output is rounded down to a whole number. Counts (cavities, cycles, bottles, samples, pallets, trucks) are integers; pallet and truck counts round up, hourly output rounds down.

### 2.9. The Validation Pipeline

Every request passes through one validation pipeline whose stages run in a fixed priority order, and a failure at an earlier stage masks every later stage. Authentication comes first: the header check of §2.1. Authorization comes second: the endpoint role check, the `CustomerQualityRep` cross-customer ownership rule, and the quality disposition segregation-of-duties rule. Third is request shape: all required fields present, no unknown fields, every enum value inside its declared set, numeric fields non-negative, `planned_start` strictly before `planned_end`, `window_start` strictly before `window_end`, and datetime fields in ISO 8601 — violations are `ERR_INVALID_REQUEST` (HTTP 400). Fourth is existence, resolved per §2.6. Fifth is state: on OCC-guarded endpoints the stale-version check of §2.7 is evaluated before all other state rules; a resource already in a terminal state rejects any further transition with `ERR_ALREADY_TERMINAL` (HTTP 409); a transition that is simply not defined for the resource's current state is rejected with `ERR_INVALID_STATE` (HTTP 409); and specialized state rules named in §3 (such as `ERR_SPEC_NOT_QUALIFIED` or `ERR_ORDER_NOT_RELEASED`) take precedence over the generic one for the cases they name. Sixth come business-safety rules (quality-hold blockouts and resin compatibility), seventh temporal rules (schedule overlap, dock window conflicts, dock load timing, no-show timing), eighth business constraints (tolerances, cavitation, uniqueness, and their kin), ninth referential-consistency rules (spec revision baselines, shipment-mode matching), and tenth fiscal rules (customer credit, material sufficiency, accepted stock). When two declared rules share the same priority tier, the rule listed earlier in this document wins.

### 2.10. Cascading State Consistency

The aggregate graph is reconciled immediately, never eventually. When a parent crosses a state boundary that invalidates its children — a customer suspended, a production spec edited mid-flight, an order placed on hold — the server transitions the affected children in the same gesture: orders are cancelled, their schedule slots are cancelled, and the machine line falls back from `RUNNING` to `CHANGEOVER` without any separate client call. Cascades run in both directions of a relationship: a voided production run reaches back into the material lots it debited, the quality lot it spawned, the order rollups it fed, and the color memory of the line it ran on. Every resource touched by a cascade is itself mutated, so its `updated_at` refreshes and its `version` increments per §2.5. A reader who only ever watches parent states will therefore still observe consistent children at every instant.

## 3. Business Logic & Workflows

### 3.1. Customers, Credit, and Plant Configuration

Before the first bottle can be quoted, a `PlantAdmin` onboards the commercial account. Creating a customer requires the legal `name`, a `customer_code` that must be unique across all customers (a collision is refused with `ERR_DUPLICATE_CODE`), and the `credit_limit_cents` that caps the customer's open production-order exposure. The creator may also supply a `default_logistics_mode` of `WAREHOUSE` or `BLOW_ON_SITE`; when omitted it is `WAREHOUSE`, and in either case it is the value new production orders for this customer inherit when they do not name their own mode. A customer is born `ACTIVE` and later moves between `ACTIVE` and `SUSPENDED`.

Suspension is the plant's emergency brake, and only a `PlantAdmin` may pull it. Suspending a customer (`ACTIVE` → `SUSPENDED`) cancels every one of that customer's production orders still in `DRAFT`, `SCHEDULED`, `RELEASED`, or `HELD`, and every schedule slot those orders held in `CONFIRMED` or `IN_PROGRESS` is cancelled in the same gesture. An order already `RUNNING` is deliberately left to finish — the line cannot be unloaded mid-shot by a commercial decision. Reactivation returns a `SUSPENDED` customer to `ACTIVE` and touches nothing else.

Freight pricing rests on a single active rate card. A `PlantAdmin` creates a FreightRateCard with a globally unique `lane_code` and a `tiers` array of marginal chargeable-weight brackets, each bracket pairing a `min_kg` with a `rate_cents_per_kg`; brackets must ascend in `min_kg`, and the first bracket's `min_kg` must be 0 so that pricing starts at the origin. Creating a card makes it `ACTIVE` and flips every other card to `INACTIVE`, so exactly one card prices freight at any moment. Any freight computation attempted while no `ACTIVE` card exists fails with `ERR_RATE_CARD_NOT_FOUND`. Both the administrator and the `LogisticsCoordinator` may read a card back by id.

### 3.2. Bottle Specifications and the Customer Qualification Loop

Everything producible begins as a BottleSpec authored by a `ProcessEngineer` against an owning customer, referenced through the payload's `customer_id`. The spec carries a `spec_code` unique within that customer (uniqueness violations are again `ERR_DUPLICATE_CODE`), the `resin_type` family (`PET`, `HDPE`, or `PP`), a `color_contrast_class` of `CLEAR`, `LIGHT`, or `DARK` that will later drive purge waste, and the geometric and commercial envelope: `target_weight_g` with a `weight_tolerance_pct` that defaults to 2.0 when omitted, `neck_finish` (for example PCO1881), `height_mm`, `diameter_mm`, the `bottle_cube_cm3` and `preform_cube_cm3` shipping cubes that feed freight-of-air, the `preform_weight_g`, the contract `unit_price_cents` used for credit exposure, the `label_type` (`NONE`, `PRESSURE_SENSITIVE`, `SHRINK_SLEEVE`, or `IN_MOLD`), and the `min_cavitation_required` floor a mold must clear to run this spec. From `label_type` the server derives `requires_inline_labeler`, which is true exactly when `label_type` is anything other than `NONE`. Every spec is born in `DRAFT` with `content_revision` set to 1, `qualified_revision` and `rejected_revision` null, and `qualification_round` — the count of qualification runs opened against it — at zero.

Editing a spec is a content act with revision consequences. A `ProcessEngineer` may patch any of the twelve content fields — `target_weight_g`, `weight_tolerance_pct`, `color_contrast_class`, `bottle_cube_cm3`, `preform_cube_cm3`, `preform_weight_g`, `neck_finish`, `height_mm`, `diameter_mm`, `unit_price_cents`, `label_type`, and `min_cavitation_required` — and any change to a content field bumps `content_revision` by one. When the spec is `PRODUCTION_ACTIVE` at that moment, the edit is disruptive: the spec falls back to `REVISION_REQUESTED`, `rejected_revision` is pinned to the freshly incremented `content_revision` (so resubmission requires at least one further content edit), every order of the spec in `DRAFT` or `SCHEDULED` is cancelled, and those orders' `CONFIRMED` or `IN_PROGRESS` slots are cancelled with them. Edits in earlier lifecycle states revise the content without the cascade.

Submission moves a spec from `DRAFT` to `SUBMITTED`, and likewise from `REVISION_REQUESTED` back to `SUBMITTED` — but the resubmission path is guarded: the spec's `content_revision` must have advanced beyond the `rejected_revision` pinned when the spec entered `REVISION_REQUESTED`, and an unchanged resubmission is refused with `ERR_SPEC_UNCHANGED_SINCE_REJECTION`. From `SUBMITTED`, beginning qualification moves the spec to `IN_QUALIFICATION`.

Qualification itself is a measured dialogue with the customer. A `ProcessEngineer` opens a QualificationRun for a spec that is `IN_QUALIFICATION` (any other spec state makes the create undefined and it is rejected with `ERR_INVALID_STATE`), supplying the `bottle_spec_id`, the `sample_cavity_count` to be measured, and the OCC guard `expected_bottle_spec_version` per §2.7. Only one run per spec may be in flight: if another run of the same spec sits in `PLANNED`, `EXECUTED`, or `CUSTOMER_REVIEW`, the create fails with `ERR_ACTIVE_QUALIFICATION_EXISTS`. At creation the run pins `spec_revision_pinned` to the spec's current `content_revision` (bumping the spec's `version`), receives the next 1-based `round_no` among the spec's runs ordered by creation, and starts `PLANNED`.

Executing a run — allowed from `PLANNED`, and again from `EXECUTED` itself when the customer has asked for more data — records the first-article measurements `measured_mean_weight_g`, `weight_spread_g` (the max-minus-min spread across sampled cavities), and `visual_defects`. Each execution recomputes `weight_within_tolerance` against the spec's current targets: it is true when the absolute difference between `measured_mean_weight_g` and the spec's `target_weight_g` is less than or equal to `target_weight_g` multiplied by `weight_tolerance_pct` and divided by 100. A `QualityTechnician` then submits an `EXECUTED` run for customer review, moving it to `CUSTOMER_REVIEW`.

The decision belongs to the customer. A `CustomerQualityRep` reviews a `CUSTOMER_REVIEW` run with a `decision` of `APPROVE`, `REJECT`, or `REQUEST_MORE_DATA` and an optional `review_note`; acting on a run whose owning customer's id differs from `X-User-ID` is refused with `ERR_CROSS_CUSTOMER_ACCESS`. Approval is gated twice: `weight_within_tolerance` must be true, otherwise the review is rejected with `ERR_WEIGHT_OUT_OF_TOLERANCE`, and the run's `spec_revision_pinned` must still equal the spec's current `content_revision` — if the spec has drifted since the run pinned it, the approval transition is not defined and the generic `ERR_INVALID_STATE` applies. A successful `APPROVE` moves the run to `APPROVED`, the spec from `IN_QUALIFICATION` to `QUALIFIED`, and writes the spec's `qualified_revision` as the pinned revision. `REJECT` moves the run to `REJECTED` and pushes the spec from `IN_QUALIFICATION` to `REVISION_REQUESTED`, pinning `rejected_revision` to the current `content_revision`. `REQUEST_MORE_DATA` returns the run from `CUSTOMER_REVIEW` to `EXECUTED` for re-measurement. Both terminal decisions advance the spec's `version`. The first time an order is successfully scheduled against a `QUALIFIED` spec, the spec advances to `PRODUCTION_ACTIVE` on its own.

Retirement closes the loop: a `ProcessEngineer` may retire a spec from `DRAFT`, `QUALIFIED`, or `PRODUCTION_ACTIVE`, provided no order of the spec stands in `SCHEDULED`, `RELEASED`, `RUNNING`, or `HELD`. `RETIRED` is terminal.

A spec also answers the plant's recurring commercial question: ship bottles or ship preforms? A computed read on the spec, open to the `LogisticsCoordinator` and the `ProcessEngineer`, takes a requested `quantity` and prices both futures against the `ACTIVE` rate card (its absence is `ERR_RATE_CARD_NOT_FOUND`). It reports `warehouse_total_cents` — the freight-of-air charge for shipping finished bottles — and `blow_on_site_total_cents`, which is the freight-of-air charge for shipping the same number of preforms plus an on-site machine fee of 40 cents per bottle. The `recommended_mode` is `WAREHOUSE` whenever the warehouse total is less than or equal to the blow-on-site total, so ties break toward the warehouse, and `BLOW_ON_SITE` only when it is strictly cheaper. The full freight formula behind both figures lives in §3.8.

### 3.3. Molds, Machine Lines, and Cavity Blockouts

The physical plant is registered by a `PlantAdmin`. Each MachineLine is created with a unique `line_code`, a `has_inline_labeler` flag, the `max_bottle_diameter_mm` the line can handle, and the `resident_volume_kg` of material its extruder and head hold — the basis of every purge calculation. A line is born `IDLE`, and its `last_color_class` — the `color_contrast_class` of the most recently closed, non-voided run on that line — stays null until the first such close. Each Mold is created with a unique `mold_code`, the physical `base_cavities` count, the `compatible_resins` it may run (a subset of `PET`, `HDPE`, `PP`), and the `reference_weight_g` at which its nominal cycle time applies. A mold is born in `STORAGE` with `installed_line_id` null.

Mold changes are the `ProcessEngineer`'s choreography. Installing a mold requires the mold in `STORAGE` and the target line, named by `machine_line_id`, in `IDLE` with no other mold currently `INSTALLED` on it; a line that already hosts a mold rejects the install with `ERR_LINE_BUSY`. A successful install moves the mold to `INSTALLED`, writes `installed_line_id`, and swings the line from `IDLE` to `CHANGEOVER`. Removal requires the mold `INSTALLED`, no `OPEN` production run on that mold, and the hosting line not `RUNNING`; it returns the mold to `STORAGE`, clears `installed_line_id` to null, and lets the line fall from `CHANGEOVER` back to `IDLE`.

Cavities fail in service, and the plant tracks each outage as a CavityBlockout opened by a `ProcessEngineer` against an `INSTALLED` mold — opening one against a mold in `STORAGE` fails with `ERR_MOLD_NOT_INSTALLED`. The create carries `cavity_index`, a `reason` of `DAMAGE`, `CONTAMINATION_HOLD`, `PREVENTIVE`, or `QUALITY_HOLD`, and the OCC guard `expected_mold_version` per §2.7. The `cavity_index` is 1-based and must lie between 1 and the mold's `base_cavities` inclusive, else `ERR_CAVITY_OUT_OF_RANGE`; opening a second `OPEN` blockout on the same mold and cavity is refused with `ERR_CAVITY_ALREADY_BLOCKED`. The new blockout is `OPEN` and stamps `blocked_at` from the logical clock. The mold's `effective_cavities` is always its `base_cavities` minus the number of its `OPEN` blockouts — cleared ones no longer count — and the model floors this at a single effective cavity: a mold is never treated as having zero. The `active_blockout_count` tracks the same `OPEN` population. Clearing an `OPEN` blockout moves it to `CLEARED`, stamps `cleared_at` from the logical clock, and recomputes both mold figures; opening and clearing each advance the mold's `version`. Blockouts with reason `QUALITY_HOLD` or `CONTAMINATION_HOLD` gate production, as §3.6 describes; `DAMAGE` and `PREVENTIVE` merely shrink cavitation.

Before committing a schedule, an engineer or scheduler can ask a line what a given combination would yield. The throughput preview takes a `mold_id`, a `bottle_spec_id`, and a candidate `planned_weight_g`, and answers with the mold's `effective_cavities`, the `cycle_time_s`, the `cycles_per_hour`, and the resulting `hourly_output`. The cycle time is ten seconds plus eight-hundredths of a second for every gram by which the planned weight exceeds the mold's `reference_weight_g` — a lighter-than-reference plan never goes below the ten-second base — rounded half-up to two decimal places. Dividing 3600 by that cycle time gives the raw cycles per hour, carried unrounded; when the spec requires inline labeling and the line actually has an inline labeler, the figure is capped at 240 cycles per hour, and otherwise the raw figure stands. The `hourly_output` is the cycles per hour multiplied by the effective cavities and by a yield fraction of 0.97, rounded down to a whole bottle — so a mold nursing open blockouts previews proportionally lower output, derated linearly with its remaining cavities.

### 3.4. Material Lots and Resin Inventory

Resin and colorant arrive as MaterialLot records created by a `PlantAdmin`. Each lot declares a `material_type` of `RESIN` or `COLORANT`; a resin lot must name its `resin_type` (`PET`, `HDPE`, or `PP`) and carries no `color_code`, while a colorant lot must name its `color_code` and carries no `resin_type`. These conditional shape rules are enforced at the request-shape stage: a create that omits the field its `material_type` requires, or that supplies the other material type's field (a `color_code` on a resin lot or a `resin_type` on a colorant lot), is rejected with `ERR_INVALID_REQUEST`. Every lot has a globally unique `lot_code` and a `received_kg` quantity, and every lot is born `QUARANTINED` with `consumed_kg` and `purge_wasted_kg` at zero. Its `available_kg` is always what remains of the received quantity after consumption and purge waste, and the server never lets it go negative.

Quality disposition of inventory belongs to the `QualityTechnician`. Releasing moves a `QUARANTINED` lot to `RELEASED`; holding moves a `RELEASED` or `IN_USE` lot back to `QUARANTINED`; rejecting a `QUARANTINED` lot moves it to `REJECTED`, which is terminal. Two further transitions belong to the production machinery rather than to any person: a `RELEASED` lot becomes `IN_USE` the first time a run close debits it, and an `IN_USE` lot whose `available_kg` reaches exactly zero becomes `DEPLETED`, also terminal. The lot list can be filtered by `material_type`, `resin_type`, or `status` with the usual `limit` and `offset` pagination.

### 3.5. Production Orders and Line Scheduling

Demand enters the plant as a ProductionOrder created by a `ProductionScheduler` against a spec, via the payload's `bottle_spec_id`, with a `quantity_ordered` and a `planned_weight_g`. The planned weight must sit inside the spec's tolerance band — the absolute difference between `planned_weight_g` and the spec's `target_weight_g` no greater than `target_weight_g` times `weight_tolerance_pct` over 100 — or the create is refused with `ERR_PLANNED_WEIGHT_OUT_OF_TOLERANCE`. The order copies its `customer_id` from the spec, takes its `logistics_mode` (`WAREHOUSE` to ship finished bottles, `BLOW_ON_SITE` to ship preforms) from the request or, when omitted, from the customer's `default_logistics_mode`, and starts in `DRAFT` with every quantity rollup at zero. The order list supports filtering by `customer_id`, `bottle_spec_id`, or `status`.

Scheduling pins an order to a line window, and it is the most heavily guarded write in the plant. The `ProductionScheduler` supplies the `machine_line_id`, the half-open window `planned_start` (inclusive) to `planned_end` (exclusive), and the OCC guard `expected_production_order_version` per §2.7; `planned_start` must precede `planned_end` or the shape check fails with `ERR_INVALID_REQUEST`. From `DRAFT` the order moves to `SCHEDULED`; the same action re-slots an order already `SCHEDULED`, legitimately superseding its prior window. In both cases the spec must be `QUALIFIED` or `PRODUCTION_ACTIVE`, else `ERR_SPEC_NOT_QUALIFIED`. The window must not intersect any other non-`CANCELLED` slot on the line, and the gap to each adjacent slot must be at least the mold-change buffer: zero minutes when both slots carry the same `mold_id` snapshot, ninety minutes otherwise; when re-slotting, the order's own `CONFIRMED` slots being replaced are excluded from the check. Violations surface as `ERR_SCHEDULE_OVERLAP`. Equipment fit is checked too: a spec whose `requires_inline_labeler` is true demands a line whose `has_inline_labeler` is true, and the spec's `diameter_mm` must not exceed the line's `max_bottle_diameter_mm` — either failure is `ERR_LABELER_REQUIRED`. Finally the fiscal gate: the sum over the customer's orders in `SCHEDULED`, `RELEASED`, `RUNNING`, or `HELD` of each order's `quantity_ordered` multiplied by its spec's `unit_price_cents`, plus the value of the order being scheduled, must be less than or equal to the customer's `credit_limit_cents` — equality is allowed — else the schedule is refused with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

A successful schedule creates a ScheduleSlot in `CONFIRMED` for the order and line, snapshotting the `mold_id` currently installed on that line (null when the line hosts no mold) — the snapshot that later decides whether an adjacent slot needs the ninety-minute buffer. Re-slotting a `SCHEDULED` order first cancels its prior `CONFIRMED` slots, then writes the new one. The first successful schedule against a `QUALIFIED` spec quietly advances the spec to `PRODUCTION_ACTIVE`.

A `HELD` order returns to the calendar through rescheduling, which repeats the schedule inputs — `machine_line_id`, `planned_start`, `planned_end`, and the same OCC guard — and the same spec-state, overlap, equipment-fit, and credit checks, then moves the order from `HELD` to `SCHEDULED` with a fresh `CONFIRMED` slot. Rescheduling also re-pins the order's `spec_revision_baseline` to the spec's current `content_revision`, which is how a held order catches up with spec edits made while it was off the line.

Release turns a scheduled order into work the floor may start. Releasing requires the order `SCHEDULED` with a `CONFIRMED` slot in place — without one the release fails with `ERR_NO_ACTIVE_SLOT` — the spec still `QUALIFIED` or `PRODUCTION_ACTIVE`, and the spec's `content_revision` still equal to its `qualified_revision`, else `ERR_SPEC_REVISION_STALE`. The material gate then requires the total `available_kg` across matching `RELEASED` and `IN_USE` resin lots — matching means `material_type` `RESIN` with the spec's `resin_type` — to cover the order's theoretical draw plus a five percent uplift: `quantity_ordered` times `planned_weight_g`, expressed in kilograms, multiplied by 1.05. A shortfall is `ERR_INSUFFICIENT_MATERIAL`. Release pins `spec_revision_baseline` to the current `content_revision` and moves the order to `RELEASED`; the first production run started against it advances it to `RUNNING`.

From `RUNNING`, an order can go three ways. A `QualityTechnician` may hold it (`RUNNING` → `HELD`) — the same transition a rejected quality lot fires automatically, as §3.7 details — which cancels the order's `CONFIRMED` and `IN_PROGRESS` slots and drops the line from `RUNNING` back to `CHANGEOVER` with the mold still installed. A `ProductionScheduler` completes the order (`RUNNING` → `COMPLETED`) only when no run of the order is still `OPEN` and every quality test lot of the order's runs has reached a terminal state — `ACCEPTED`, `SCRAPPED`, or `VOIDED`; completion moves the order's `IN_PROGRESS` slot to `COMPLETED` and again rests the line at `CHANGEOVER`. And cancellation is available from `DRAFT`, `SCHEDULED`, `RELEASED`, or `HELD`, cancelling the order's `CONFIRMED` and `IN_PROGRESS` slots with it; the same cancellation arrives by cascade when the customer is suspended (which also reaches `RELEASED` and `HELD` orders) or when a `PRODUCTION_ACTIVE` spec edit cancels the order's `DRAFT` and `SCHEDULED` kin. `COMPLETED` and `CANCELLED` are terminal.

Schedule slots themselves have a small lifecycle: created `CONFIRMED`, a slot becomes `IN_PROGRESS` when the first production run starts for its order on its line, becomes `COMPLETED` when its order completes, and can be cancelled from `CONFIRMED` by a `ProductionScheduler` or by any of the cascades above; an `IN_PROGRESS` slot is cancelled only by cascade — order hold, order cancel, customer suspension, spec edit, or reschedule — never by direct request. The slots of a line, of a mold snapshot, or of an order can each be listed, with an optional `status` filter.

An order's rollup tells the whole production story at a glance. `quantity_produced` sums `good_count` plus `scrap_count` over the order's non-`VOIDED` runs; `quantity_good` and `quantity_scrapped` sum the two components separately. `quantity_accepted` sums the `lot_size` of `ACCEPTED` quality lots belonging to the order's non-`VOIDED` runs, and `quantity_qc_scrapped` does the same for `SCRAPPED` lots; `quantity_open_qc` is what remains of `quantity_good` once accepted and QC-scrapped quantities are subtracted. On the outbound side, `quantity_reserved` sums the `quantity` of the order's shipments in `BOOKED`, `LOADING`, or `IN_TRANSIT`, `quantity_shipped` sums those `DELIVERED`, and `quantity_unallocated` is `quantity_accepted` minus reserved minus shipped. A computed summary read on the order exposes `quantity_produced`, `quantity_good`, `quantity_scrapped`, `quantity_accepted`, `quantity_qc_scrapped`, `quantity_reserved`, `quantity_shipped`, and `quantity_unallocated` in one payload.

### 3.6. Production Runs: Start, Close, and Void

A production run is where resin becomes bottles, and starting one is gated from every direction. The `ProcessEngineer` names the `production_order_id`, the `machine_line_id`, the `mold_id`, and the primary resin `material_lot_id`; a `colorant_lot_id` is required whenever the spec's `color_contrast_class` is anything but `CLEAR` and is otherwise optional. The order must be `RELEASED` or `RUNNING`, else `ERR_ORDER_NOT_RELEASED`. A schedule slot for that order on that line must exist in `CONFIRMED` or `IN_PROGRESS` and the logical clock must fall inside its half-open window — at or after `planned_start` and strictly before `planned_end` — else `ERR_NO_ACTIVE_SLOT`. The mold must be `INSTALLED` and installed on exactly this line, else `ERR_MOLD_NOT_INSTALLED`, and the line must not be `RUNNING` a different order, else `ERR_LINE_BUSY`. The resin lot — and the colorant lot when given — must be `RELEASED` or `IN_USE`, else `ERR_MATERIAL_LOT_NOT_RELEASED`. Safety gates follow: any `OPEN` blockout on the mold with reason `QUALITY_HOLD` or `CONTAMINATION_HOLD` stops the start with `ERR_QUALITY_HOLD_BLOCKOUT`, and the spec's `resin_type` must appear in the mold's `compatible_resins`, else `ERR_RESIN_INCOMPATIBLE`. Capacity and revision checks close the gate: the mold's `effective_cavities` must be at least the spec's `min_cavitation_required`, else `ERR_INSUFFICIENT_CAVITATION`, and the order's `spec_revision_baseline` must equal the spec's current `content_revision` — a stale baseline means the spec moved since release and the start is refused with `ERR_SPEC_REVISION_STALE`, curable by rescheduling to re-pin.

A successful start snapshots the mold's `effective_cavities` into `cavities_active_at_start`, stamps `started_at` from the logical clock, and opens the run in `OPEN` status. The first run of an order ripples outward in the same gesture: the order moves `RELEASED` → `RUNNING`, the occupying slot moves `CONFIRMED` → `IN_PROGRESS`, and the line moves `CHANGEOVER` → `RUNNING`. Runs can be listed with filters on `production_order_id`, `machine_line_id`, `mold_id`, `material_lot_id`, `colorant_lot_id`, or `status`.

Closing a run is the plant's moment of accounting, performed by a `ProcessEngineer` reporting `cycles_completed`, `good_count`, `scrap_count`, and the measured silo drawdown `actual_drawdown_kg`. Only an `OPEN` run whose order is still `RUNNING` can close. Since `VOIDED` is the run's only terminal state, a close attempted against a `CLOSED` run is a transition that is not defined for that state and is rejected with `ERR_INVALID_STATE`, while closing a `VOIDED` run is rejected with `ERR_ALREADY_TERMINAL`. The reported units must be physically possible: `good_count` plus `scrap_count` no greater than `cycles_completed` times the `cavities_active_at_start` snapshot, else `ERR_COUNT_EXCEEDS_PRODUCTION`. The close then reconciles consumption in two variants. The provisional variant computes what the machine counters imply — `cycles_completed` times `cavities_active_at_start` times the order's `planned_weight_g`, converted from grams to kilograms, rounded half-up to two decimals — and stores it as `provisional_consumption_kg`. The actual variant is the reported `actual_drawdown_kg`, which differs by scrap and startup loss. Their gap becomes `consumption_variance_pct`: the difference between actual and provisional, divided by the provisional figure, expressed as a percentage and rounded half-up to two decimals. When that percentage is strictly greater than 3.0, `variance_alert` is set; a variance of exactly 3.00 does not alert.

Color memory decides the purge charge. The close compares the line's `last_color_class` against the spec's `color_contrast_class` through the purge matrix: from `CLEAR`, moving to `LIGHT` or `DARK` costs a multiplier of 1.0 while staying `CLEAR` costs 0.0; from `LIGHT`, moving to `CLEAR` costs 2.0, to `DARK` costs 1.0, and staying `LIGHT` costs 0.0; from `DARK`, moving to `CLEAR` costs 3.0, to `LIGHT` costs 2.5, and staying `DARK` costs 0.0. A line with no prior non-voided closed run has no color memory and pays 0.0. The `purge_kg` charged to the run is the line's `resident_volume_kg` multiplied by that multiplier, rounded half-up to two decimals.

The material allocation waterfall then pays the bill from inventory. The requirement is the `actual_drawdown_kg` plus the `purge_kg`; the candidate pool is every resin lot matching the spec's `resin_type` in `RELEASED` or `IN_USE`, ordered by `created_at` ascending with `lot_code` ascending breaking ties. Each lot in turn first absorbs purge waste into its `purge_wasted_kg` and then consumption into its `consumed_kg`, filling its `available_kg` completely before the next lot is touched. A lot debited for the first time moves `RELEASED` → `IN_USE`; a lot whose `available_kg` reaches exactly zero becomes `DEPLETED`. If the whole pool cannot cover the requirement, the close fails with `ERR_INSUFFICIENT_MATERIAL` and no lot is debited at all — the waterfall is all-or-nothing. With the debits settled, the close writes the spec's `color_contrast_class` into the line's `last_color_class`, recomputes the order's produced, good, and scrapped rollups, stamps `ended_at`, and auto-creates the run's QualityTestLot in `PENDING` with `lot_size` snapshotting `good_count` and its sample and accept numbers computed per §3.7.

A `PlantAdmin` can void a closed run, but only while its quality lot is still `PENDING` — once the lot has been sampled the accounting is locked. Voiding reverses every debit the close made, crediting each touched lot's `consumed_kg` and `purge_wasted_kg` back by exactly the amounts taken; each touched lot's status is then recomputed from its corrected balances — `DEPLETED` when `available_kg` is exactly zero, else `IN_USE` when anything has been consumed or purged, else `RELEASED`. The run's `PENDING` quality lot becomes `VOIDED`, the order's rollups recompute with the voided run excluded, and the line's `last_color_class` is rebuilt from the most recent remaining non-voided closed run — null when none remains. The run itself moves from `CLOSED` to `VOIDED`, and `VOIDED` is terminal.

### 3.7. Quality Testing and AQL Disposition

Every closed run spawns exactly one quality test lot, already `PENDING` with its `lot_size` fixed and its sampling plan computed from the AQL band table. The band is keyed on `lot_size` with inclusive bounds: a lot of 280 units or fewer draws a `sample_size_n` of 20 with an `accept_number_leak` of 1 and an `accept_number_drop` of 1; from 281 through 1200 units the sample is 50 with accept numbers 2 and 2; from 1201 through 10000 the sample is 125 with accept numbers 3 for leak and 4 for drop; and a lot of 10001 units or more draws 200 samples with accept numbers 5 for leak and 6 for drop. The quality lot list can be filtered by `production_run_id` or `status`.

A `QualityTechnician` samples a `PENDING` lot, moving it to `SAMPLED`, then records results by reporting the `leak_failures` and `drop_failures` found in the sample. Neither figure may exceed `sample_size_n` — an impossible count is `ERR_INVALID_REQUEST`. The accept decision treats the two characteristics independently and accepts on an inclusive boundary: the lot becomes `ACCEPTED` when `leak_failures` is at most `accept_number_leak` and `drop_failures` is at most `accept_number_drop`, so failure counts exactly equal to the accept numbers still accept; if either characteristic exceeds its accept number the lot becomes `REJECTED`. Recording writes the technician's `X-User-ID` into `recorded_by_user_id`. Acceptance recomputes the order's `quantity_accepted` and `quantity_open_qc`. Rejection is louder: the order drops from `RUNNING` to `HELD` as a QC hold, which cascades exactly like a manual hold — the order's `CONFIRMED` and `IN_PROGRESS` slots are cancelled and the line falls from `RUNNING` to `CHANGEOVER`.

A `REJECTED` lot awaits disposition by a `QualityTechnician`, and segregation of duties applies: the dispositor's `X-User-ID` must differ from the lot's `recorded_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; whoever dispositions is remembered in `dispositioned_by_user_id`. Disposition with `action` `SCRAP` moves the lot to `SCRAPPED` and recomputes the order's `quantity_qc_scrapped` and `quantity_open_qc`. Disposition with `action` `REWORK` instead returns the lot to `PENDING` for another pass: `retest_count` increments by one and the recorded `leak_failures`, `drop_failures`, and `recorded_by_user_id` are cleared to null, ready for fresh sampling. The remaining transition belongs to the void machinery: a lot still `PENDING` when its parent run is voided becomes `VOIDED`. `ACCEPTED`, `SCRAPPED`, and `VOIDED` are terminal.

### 3.8. Freight, Shipments, and the Shipping Dock

Freight-of-air pricing charges for whichever is greater: what the load weighs or what space it wastes. The computation keys on the shipment mode. For `FINISHED_BOTTLES` a pallet holds 1500 units, the unit cube is the spec's `bottle_cube_cm3`, and the unit weight is its `target_weight_g`; for `PREFORMS` a pallet holds 30000 units, the unit cube is `preform_cube_cm3`, and the unit weight is `preform_weight_g`. The `pallets` count is the shipment `quantity` divided by the pallet capacity, rounded up. The load's `volume_cm3` is the quantity times the unit cube plus 144,000 cubic centimeters of pallet cube per pallet.

Dimensional weight obeys a pinned rounding order that implementers must follow exactly: it is computed per pallet and rounded before summing, never aggregated first. Each full pallet's dimensional weight is its contents' cube plus the 144,000-cubic-centimeter pallet cube, divided by the dim divisor of 6,000 cubic centimeters per kilogram, rounded half-up to one decimal of a kilogram. When the quantity does not fill the last pallet, the remainder pallet's dim weight is computed the same way from the remaining units — and is zero when there is no remainder. The `dim_weight_kg` is the full-pallet figure times the number of full pallets plus the remainder figure. The `actual_weight_kg`, by contrast, is computed in one shot: quantity times unit weight converted to kilograms, plus 20 kilograms of pallet tare per pallet, rounded half-up to two decimals. The `chargeable_weight_kg` is simply the larger of the two weights.

The `freight_cost_cents` then walks the `ACTIVE` rate card's marginal tiers. Tier boundaries are the brackets' `min_kg` values: the first tier covers from zero up to the second tier's `min_kg`, each subsequent tier covers from its own `min_kg` up to the next tier's, and the last tier is unbounded; the kilograms billed in a tier are the portion of the chargeable weight falling inside that span. Each tier's charge — its kilograms times its `rate_cents_per_kg` — is rounded half-up to whole cents first, and the tier charges are then summed; rounding once at the end instead would be a different procedure and is forbidden. Truck planning is capped by both cube and payload: a pallet's cube is its contents' cube plus 144,000, and its gross weight is its contents' weight plus the 20-kilogram tare; the pallets a truck carries is the smaller of the truck's 96,000,000-cubic-centimeter cube divided by the pallet cube and the truck's 24,000-kilogram payload divided by the pallet gross weight, each division rounded down, and the `trucks` needed is the pallet count divided by that capacity, rounded up.

A `LogisticsCoordinator` can price any hypothetical without committing inventory through a freight quote, supplying a `bottle_spec_id`, a `quantity`, and a `shipment_mode`; the answer carries `pallets`, `trucks`, `volume_cm3`, `dim_weight_kg`, `actual_weight_kg`, `chargeable_weight_kg`, and `freight_cost_cents`, computed exactly as above against the `ACTIVE` card (whose absence is `ERR_RATE_CARD_NOT_FOUND`). The same computation, persisted, happens when a real shipment is created against an order via `production_order_id`. Creating a shipment requires the order to be `RUNNING`, `HELD`, or `COMPLETED` — anything earlier has nothing to ship and is `ERR_INVALID_STATE` — a positive integer `quantity`, else `ERR_ZERO_QUANTITY`, and a `shipment_mode` consistent with the order's `logistics_mode`: `WAREHOUSE` orders ship `FINISHED_BOTTLES`, `BLOW_ON_SITE` orders ship `PREFORMS`, and a crossed pairing is `ERR_MODE_MISMATCH`. The shipment copies its `customer_id` from the order, persists the full freight computation, and starts `QUOTED`. Shipment lists filter by `production_order_id`, `customer_id`, or `status`.

Booking ties the shipment to the dock. The coordinator books a `QUOTED` shipment against a dock appointment named by `dock_appointment_id`; the appointment must be `RESERVED` and must belong to this shipment, else `ERR_APPOINTMENT_NOT_RESERVED`, and the shipment's `quantity` must not exceed the order's `quantity_unallocated`, else `ERR_INSUFFICIENT_ACCEPTED_STOCK`. Booking records the appointment in `booked_appointment_id`, reserves the quantity against the order (recomputing `quantity_reserved` and `quantity_unallocated`), and moves the shipment to `BOOKED`. Loading is a clock discipline: the coordinator may start loading only while the logical clock sits inside the booked appointment's window, from `window_start` through `window_end` inclusive at both ends — outside the window the attempt is `ERR_OUTSIDE_DOCK_WINDOW`, and an appointment no longer `RESERVED` is again `ERR_APPOINTMENT_NOT_RESERVED`. Loading moves the shipment to `LOADING` and the appointment from `RESERVED` to `OCCUPIED`. Dispatch moves the shipment from `LOADING` to `IN_TRANSIT`; delivery moves it from `IN_TRANSIT` to `DELIVERED`, completes the appointment (`OCCUPIED` → `COMPLETED`), and settles the order's `quantity_shipped`, `quantity_reserved`, and `quantity_unallocated`. `DELIVERED` is terminal.

Cancellation unwinds gracefully. Cancelling a `QUOTED` shipment simply moves it to `CANCELLED`. Cancelling a `BOOKED` one also releases its reservation on the order, cancels the booked appointment if it is still `RESERVED`, and clears `booked_appointment_id` to null. The reverse direction exists too: when a booked appointment is cancelled, its shipment falls back from `BOOKED` to `QUOTED` with the reservation released and `booked_appointment_id` cleared, while an appointment marked no-show cancels its booked shipment outright — same reservation release, same clearing.

Dock appointments are the scarce resource that disciplines all of this. The coordinator reserves one for a `QUOTED` or `BOOKED` shipment — any other shipment state is `ERR_INVALID_STATE` — naming the `shipment_id`, a `dock_door` numbered 1 through 3, and a closed window `window_start` through `window_end`, with `window_start` strictly before `window_end` enforced by the shape check. Windows on the same door must not intersect: because the intervals are closed, two appointments on one door that merely touch endpoints already conflict, and any overlap with another `RESERVED` or `OCCUPIED` appointment on that door is refused with `ERR_DOCK_WINDOW_CONFLICT`. A new appointment starts `RESERVED`. When a carrier never arrives, the coordinator marks the appointment no-show — allowed only once the logical clock has passed `window_end` strictly, else `ERR_INVALID_STATE` — moving it to `NO_SHOW` and cancelling any shipment booked on it as described above. Cancelling a `RESERVED` appointment instead reverts its booked shipment to `QUOTED`. `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal for appointments, and an appointment's booked shipments can be listed back from the appointment itself.

## 4. Endpoint Definitions

All endpoints are mounted under the `/plant` prefix. Operations that create a new resource return `201 Created`; operations that modify, transition, or compute against existing resources return `200 OK`. Request bodies, preconditions, side effects, and error behavior are defined by the narratives of §2 and §3; this table is the index, not the contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plant/_clock/set_current_utc` | Advance the logical plant clock | PlantAdmin |
| POST | `/plant/customers` | Create a customer | PlantAdmin |
| GET | `/plant/customers/{id}` | Get a customer | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler, LogisticsCoordinator, CustomerQualityRep |
| POST | `/plant/customers/{id}/suspend` | Suspend a customer; cancels non-terminal orders and their slots | PlantAdmin |
| POST | `/plant/customers/{id}/reactivate` | Reactivate a suspended customer | PlantAdmin |
| GET | `/plant/customers/{id}/bottle-specs` | List the bottle specs of a customer | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler, LogisticsCoordinator, CustomerQualityRep |
| POST | `/plant/freight-rate-cards` | Create a rate card; it becomes ACTIVE and all others INACTIVE | PlantAdmin |
| GET | `/plant/freight-rate-cards/{id}` | Get a rate card | PlantAdmin, LogisticsCoordinator |
| POST | `/plant/freight-quotes` | Compute a freight-of-air quote without creating a shipment | LogisticsCoordinator |
| POST | `/plant/machine-lines` | Create a machine line | PlantAdmin |
| GET | `/plant/machine-lines/{id}` | Get a machine line | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler, LogisticsCoordinator |
| GET | `/plant/machine-lines/{id}/molds` | List molds installed on a line | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler |
| GET | `/plant/machine-lines/{id}/schedule-slots` | List schedule slots of a line | PlantAdmin, ProcessEngineer, ProductionScheduler |
| GET | `/plant/machine-lines/{id}/throughput-preview` | Preview cycle time and hourly output for a mold, spec, and planned weight | ProcessEngineer, ProductionScheduler |
| POST | `/plant/molds` | Create a mold | PlantAdmin |
| GET | `/plant/molds/{id}` | Get a mold | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler |
| POST | `/plant/molds/{id}/install` | Install a mold on an IDLE line | ProcessEngineer |
| POST | `/plant/molds/{id}/remove` | Remove an installed mold to STORAGE | ProcessEngineer |
| GET | `/plant/molds/{id}/schedule-slots` | List schedule slots carrying this mold snapshot | PlantAdmin, ProcessEngineer, ProductionScheduler |
| POST | `/plant/molds/{id}/cavity-blockouts` | Open a cavity blockout on an INSTALLED mold (OCC on mold version) | ProcessEngineer |
| GET | `/plant/molds/{id}/cavity-blockouts` | List blockouts of a mold | PlantAdmin, ProcessEngineer, QualityTechnician |
| GET | `/plant/cavity-blockouts/{id}` | Get a cavity blockout | PlantAdmin, ProcessEngineer, QualityTechnician |
| POST | `/plant/cavity-blockouts/{id}/clear` | Clear an OPEN blockout | ProcessEngineer |
| POST | `/plant/bottle-specs` | Create a bottle spec in DRAFT | ProcessEngineer |
| GET | `/plant/bottle-specs/{id}` | Get a bottle spec | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler, LogisticsCoordinator, CustomerQualityRep |
| PATCH | `/plant/bottle-specs/{id}` | Edit spec content fields; bumps content revision; cascades in PRODUCTION_ACTIVE | ProcessEngineer |
| POST | `/plant/bottle-specs/{id}/submit` | Submit a spec from DRAFT or REVISION_REQUESTED | ProcessEngineer |
| POST | `/plant/bottle-specs/{id}/begin-qualification` | Move a SUBMITTED spec into qualification | ProcessEngineer |
| POST | `/plant/bottle-specs/{id}/retire` | Retire a spec with no open orders | ProcessEngineer |
| GET | `/plant/bottle-specs/{id}/qualification-runs` | List qualification runs of a spec | PlantAdmin, ProcessEngineer, QualityTechnician, CustomerQualityRep |
| GET | `/plant/bottle-specs/{id}/logistics-comparison` | Compare warehouse vs blow-on-site totals for a quantity | LogisticsCoordinator, ProcessEngineer |
| POST | `/plant/qualification-runs` | Create a qualification run (OCC on spec version; pins content revision) | ProcessEngineer |
| GET | `/plant/qualification-runs/{id}` | Get a qualification run | PlantAdmin, ProcessEngineer, QualityTechnician, CustomerQualityRep |
| POST | `/plant/qualification-runs/{id}/execute` | Record first-article measurements (re-measurement allowed from EXECUTED) | ProcessEngineer |
| POST | `/plant/qualification-runs/{id}/submit-review` | Submit an EXECUTED run for customer review | QualityTechnician |
| POST | `/plant/qualification-runs/{id}/review` | Customer decision: APPROVE, REJECT, or REQUEST_MORE_DATA | CustomerQualityRep |
| POST | `/plant/material-lots` | Receive a material lot into QUARANTINED | PlantAdmin |
| GET | `/plant/material-lots` | List material lots with filters and pagination | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler |
| GET | `/plant/material-lots/{id}` | Get a material lot | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler |
| POST | `/plant/material-lots/{id}/release` | Release a QUARANTINED lot | QualityTechnician |
| POST | `/plant/material-lots/{id}/hold` | Re-hold a RELEASED or IN_USE lot | QualityTechnician |
| POST | `/plant/material-lots/{id}/reject` | Reject a QUARANTINED lot | QualityTechnician |
| POST | `/plant/production-orders` | Create a production order in DRAFT | ProductionScheduler |
| GET | `/plant/production-orders` | List production orders with filters and pagination | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler, LogisticsCoordinator |
| GET | `/plant/production-orders/{id}` | Get a production order | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler, LogisticsCoordinator |
| GET | `/plant/production-orders/{id}/summary` | Computed quantity rollup for an order | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler, LogisticsCoordinator |
| POST | `/plant/production-orders/{id}/schedule` | Schedule a DRAFT order or re-slot a SCHEDULED one (OCC on order version) | ProductionScheduler |
| POST | `/plant/production-orders/{id}/reschedule` | Return a HELD order to the calendar with a fresh slot (OCC on order version) | ProductionScheduler |
| POST | `/plant/production-orders/{id}/release` | Release a SCHEDULED order after material and revision checks | ProductionScheduler |
| POST | `/plant/production-orders/{id}/hold` | Place a RUNNING order on QC hold | QualityTechnician |
| POST | `/plant/production-orders/{id}/cancel` | Cancel an order from DRAFT, SCHEDULED, RELEASED, or HELD | ProductionScheduler |
| POST | `/plant/production-orders/{id}/complete` | Complete a RUNNING order once runs and quality lots are settled | ProductionScheduler |
| GET | `/plant/production-orders/{id}/schedule-slots` | List schedule slots of an order | PlantAdmin, ProcessEngineer, ProductionScheduler |
| POST | `/plant/production-runs` | Start a production run; order, slot, and line advance with it | ProcessEngineer |
| GET | `/plant/production-runs` | List production runs with filters and pagination | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler |
| GET | `/plant/production-runs/{id}` | Get a production run | PlantAdmin, ProcessEngineer, QualityTechnician, ProductionScheduler |
| POST | `/plant/production-runs/{id}/close` | Close a run: reconciliation, purge, FIFO material debit, quality lot creation | ProcessEngineer |
| POST | `/plant/production-runs/{id}/void` | Void a CLOSED run while its quality lot is PENDING; exact compensating credit | PlantAdmin |
| GET | `/plant/quality-test-lots` | List quality test lots with filters and pagination | PlantAdmin, ProcessEngineer, QualityTechnician, CustomerQualityRep |
| GET | `/plant/quality-test-lots/{id}` | Get a quality test lot | PlantAdmin, ProcessEngineer, QualityTechnician, CustomerQualityRep |
| POST | `/plant/quality-test-lots/{id}/sample` | Mark a PENDING lot SAMPLED | QualityTechnician |
| POST | `/plant/quality-test-lots/{id}/record-results` | Record leak and drop failures; AQL accept or reject (reject cascades a QC hold) | QualityTechnician |
| POST | `/plant/quality-test-lots/{id}/disposition` | Disposition a REJECTED lot as SCRAP or REWORK (segregation of duties) | QualityTechnician |
| POST | `/plant/shipments` | Create a shipment in QUOTED with persisted freight computation | LogisticsCoordinator |
| GET | `/plant/shipments` | List shipments with filters and pagination | PlantAdmin, ProductionScheduler, LogisticsCoordinator |
| GET | `/plant/shipments/{id}` | Get a shipment | PlantAdmin, ProductionScheduler, LogisticsCoordinator |
| POST | `/plant/shipments/{id}/book` | Book a QUOTED shipment against a RESERVED dock appointment | LogisticsCoordinator |
| POST | `/plant/shipments/{id}/load` | Start loading inside the booked dock window | LogisticsCoordinator |
| POST | `/plant/shipments/{id}/dispatch` | Dispatch a loaded shipment | LogisticsCoordinator |
| POST | `/plant/shipments/{id}/deliver` | Deliver an in-transit shipment; completes the appointment | LogisticsCoordinator |
| POST | `/plant/shipments/{id}/cancel` | Cancel a QUOTED or BOOKED shipment, releasing any reservation | LogisticsCoordinator |
| POST | `/plant/dock-appointments` | Reserve a dock door window for a QUOTED or BOOKED shipment | LogisticsCoordinator |
| GET | `/plant/dock-appointments` | List dock appointments with filters and pagination | PlantAdmin, LogisticsCoordinator |
| GET | `/plant/dock-appointments/{id}` | Get a dock appointment | PlantAdmin, LogisticsCoordinator |
| GET | `/plant/dock-appointments/{id}/shipments` | List shipments booked against an appointment | PlantAdmin, LogisticsCoordinator |
| POST | `/plant/dock-appointments/{id}/no-show` | Mark a RESERVED appointment NO_SHOW after its window ends | LogisticsCoordinator |
| POST | `/plant/dock-appointments/{id}/cancel` | Cancel a RESERVED appointment; a booked shipment reverts to QUOTED | LogisticsCoordinator |
| GET | `/plant/schedule-slots/{id}` | Get a schedule slot | PlantAdmin, ProcessEngineer, ProductionScheduler |
| POST | `/plant/schedule-slots/{id}/cancel` | Cancel a CONFIRMED slot (IN_PROGRESS slots are system-cancelled only) | ProductionScheduler |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_CROSS_CUSTOMER_ACCESS` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_BOTTLE_SPEC_NOT_FOUND` | 404 Not Found |
| `ERR_QUALIFICATION_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_MOLD_NOT_FOUND` | 404 Not Found |
| `ERR_CAVITY_BLOCKOUT_NOT_FOUND` | 404 Not Found |
| `ERR_MACHINE_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SCHEDULE_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_MATERIAL_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCTION_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCTION_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_QUALITY_TEST_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DOCK_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RATE_CARD_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_SPEC_NOT_QUALIFIED` | 409 Conflict |
| `ERR_ORDER_NOT_RELEASED` | 409 Conflict |
| `ERR_NO_ACTIVE_SLOT` | 409 Conflict |
| `ERR_MOLD_NOT_INSTALLED` | 409 Conflict |
| `ERR_LINE_BUSY` | 409 Conflict |
| `ERR_MATERIAL_LOT_NOT_RELEASED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_RESERVED` | 409 Conflict |
| `ERR_QUALITY_HOLD_BLOCKOUT` | 409 Conflict |
| `ERR_RESIN_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_DOCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_OUTSIDE_DOCK_WINDOW` | 409 Conflict |
| `ERR_PLANNED_WEIGHT_OUT_OF_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_LABELER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CAVITATION` | 422 Unprocessable Entity |
| `ERR_CAVITY_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_CAVITY_ALREADY_BLOCKED` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_SPEC_UNCHANGED_SINCE_REJECTION` | 409 Conflict |
| `ERR_ACTIVE_QUALIFICATION_EXISTS` | 409 Conflict |
| `ERR_WEIGHT_OUT_OF_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_COUNT_EXCEEDS_PRODUCTION` | 422 Unprocessable Entity |
| `ERR_ZERO_QUANTITY` | 422 Unprocessable Entity |
| `ERR_SPEC_REVISION_STALE` | 409 Conflict |
| `ERR_MODE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_INSUFFICIENT_MATERIAL` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_ACCEPTED_STOCK` | 422 Unprocessable Entity |
