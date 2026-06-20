# Farm Management & Crop Planning API — Product Requirements Document

## 1. Introduction

Modern row-crop operations live or die by two things that are notoriously hard to keep in sync: the agronomic plan for a field and the financial reality of what that plan actually cost to execute. A grower commits a parcel of land to a crop for a season, budgets seed, fertilizer, chemical, labor and machine time against it, then spends the next several months logging applications, plantings, harvests, equipment hours, irrigation runs and labor — each of which quietly rewrites the true cost-per-acre and the realized yield. This API is the system of record for that entire arc. It governs the planning of fields and crop plans, the scheduling of planting and harvest, the logging of seed/fertilizer/chemical applications, the derivation of yield and cost-per-acre, the booking of equipment and labor, the scheduling of irrigation, the management of harvest inventory and downstream sale contracts, and — critically — the regulatory compliance record for restricted-use chemicals.

The compliance dimension is what raises the stakes. Restricted-use products impose legally mandated re-entry intervals (how long a field stays off-limits after a spray) and pre-harvest intervals (how long must elapse before the crop may be cut). A certified applicator must perform the work, the application must be auditable, and the field's availability must reflect those windows in real time. Layered on top is a strict separation of duties: the people who approve and close plans are not the people who run them in the field, and the people who sell the harvest are distinct again. The API therefore treats every operation as both an agronomic event and a controlled, role-gated, financially-reconciled transaction.

Because cost and yield are continuously derived from underlying events, the system distinguishes between *provisional* figures (forward-looking estimates carried while a plan is in flight) and *final* figures (chronological actuals locked in at close). Where one operation touches several entities — a confirmed restricted application that in a single step creates a compliance record, restricts the parcel and bumps the parcel's version — every downstream effect is specified and enforced. The remainder of this document defines the global contract every endpoint honors, the business logic of each workflow, the endpoint surface, and the canonical error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly four roles, spelled precisely as `FarmManager`, `Agronomist`, `Applicator`, and `SalesAgent`. If the `X-User-Role` header is missing or names something the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation under the access matrix, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles partition responsibility along separation-of-duties lines. A `FarmManager` owns the registries — parcels, input products, input lots, equipment assets, and the applicator roster — and is the only role that may approve, close, or abandon a crop plan; it also owns the test-driving clock. An `Agronomist` drives the agronomic lifecycle: requesting revisions, beginning growth, beginning harvest, recording plantings and harvests, creating and grading harvest lots, booking equipment usage, scheduling and resolving irrigation, and voiding applications. An `Applicator` is the certified field operator who confirms applications. A `SalesAgent` manages the sales side end to end: creating contracts, committing lots, shipping, and cancelling. Crop-plan creation and labor entry are shared between a `FarmManager` and an `Agronomist`; logging (as opposed to confirming) an application is shared between an `Agronomist` and an `Applicator`. All four roles have read access to GET endpoints.

The interpretation of `X-User-ID` depends on the role. When `X-User-Role` is `Applicator`, `X-User-ID` is the `id` of the acting `Applicator` entity; ownership checks compare a resource's applicator foreign key to `X-User-ID`. Concretely, when a restricted-use application is confirmed, the acting `Applicator`'s `id` must equal the `applicator_user_id` recorded on the `ApplicationRecord`, or the confirm is rejected. When `X-User-Role` is `FarmManager`, `Agronomist`, or `SalesAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authentication and role-gating but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values run from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0.

Unless a specific endpoint states otherwise, every list is sorted by `created_at` in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching items before pagination and `has_more` indicates whether items remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every entity in this system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. All entities in this domain are full first-class resources: in addition to `id` and `created_at`, each carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and a `version` integer that begins at its initial value on creation and increments by one on every persisted mutation of that resource. The `version` field is the basis for optimistic concurrency control described in §2.6.

A subtle but important rule governs derived fields. Several entities expose computed attributes — a crop plan's `provisional_cost_per_acre`, a parcel's `active_crop_plan_count`, a contract's `committed_quantity` — that change when *other* entities are written. Whenever the server recomputes and persists such a derived field on an entity, that counts as a mutation of the owning entity: its `updated_at` is refreshed and its `version` is incremented. This is why approving a plan or confirming a restricted application advances the parent parcel's `version` even though the caller addressed a different resource.

### 2.5. Hierarchical Consistency and Cascading Effects

Although the URL surface is flat — every resource is a top-level collection linked to others by foreign-key fields rather than nested under a single parent path — the entities form a tightly coupled web, and a single operation routinely reconciles several of them. The governing principle is that whenever an event changes the inputs to another entity's derived state, the server immediately recomputes and re-persists that dependent state in the same operation, with no separate client request required.

Concretely: confirming or voiding an application re-derives the owning crop plan's `actual_input_cost` and its `provisional_cost_per_acre`; recording or voiding a planting re-derives the plan's `planted_acres`; recording a harvest re-derives `harvested_acres`; booking equipment usage re-derives `actual_equipment_cost` and `provisional_cost_per_acre`; recording labor re-derives `actual_labor_cost` and `provisional_cost_per_acre`; committing, shipping, or cancelling against a contract re-derives that contract's `committed_quantity`, `contract_value`, and `status` as well as the affected lots' `quantity_committed`, `sale_status`, and `committed_contract_id`. Restricted-use application events further cascade onto the parcel, re-deriving its `status`, `reentry_blocked_until`, and `active_crop_plan_count`. Each such reconciliation independently mutates its target entity, refreshing `updated_at` and incrementing `version` per §2.4.

### 2.6. Optimistic Concurrency Control on Parcel Approval

A single operation in this system requires the client to prove it is acting on an up-to-date view of a parent resource: approving a crop plan against its parcel. The approve operation mutates the parcel — it recomputes `active_crop_plan_count` and increments `Parcel.version` — and a parcel's version can legitimately advance between reads for reasons unrelated to the caller (another plan on the same parcel was just approved, or a restricted application just flipped the parcel to `RESTRICTED`). To prevent a client from approving against a parcel state it never observed, the approve request must carry `expected_parcel_version`, a non-optional field whose value is the parcel's `version` as the client last read it. If `expected_parcel_version` does not equal the parcel's current `version` at the moment of approval, the request is rejected with `ERR_STALE_PARCEL_VERSION` (HTTP 412), and no state changes. This is the only endpoint that takes a version field; no other operation accepts or requires one.

### 2.7. Left-to-Right Reference Resolution

Several endpoints address a resource by id in the path and reference further resources in the body. The server resolves every referenced id — path identifiers first, then body foreign keys — in left-to-right order, and the first id that fails to resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any later reference or business rule is evaluated. For example, a planting event whose `crop_plan_id` does not exist fails on that reference before its `input_lot_id` is examined.

### 2.8. Precision, Rounding, and Money

Every computed monetary or quantity figure that the scaffolding marks as rounded — `applied_cost`, `labor_cost`, `usage_cost`, `hours`, `net_quantity`, `provisional_cost_per_acre`, `final_cost_per_acre`, `total_yield_units`, `contract_value` — is rounded to exactly two decimal places using the round-half-up convention. Where a figure is a sum of several line items, the rounding is applied once at the very end, after the full sum is formed — never per line item and then summed. Unit quantities tracked for inventory (a lot's `quantity_remaining`, a planting's `seed_units_used`) are exact counts and are not rounded. All monetary and numeric values appear in responses as JSON numbers, not strings.

### 2.9. Enumerations

The system uses fixed enumerations whose values must appear exactly as written. A parcel's `soil_type` is one of `CLAY`, `LOAM`, `SAND`, or `SILT`, and its `status` is one of `AVAILABLE`, `RESTRICTED`, or `RETIRED`. A crop plan's `crop` and a sale contract's `crop` are each one of `CORN`, `SOY`, `WHEAT`, `COTTON`, or `ALFALFA`. An input product's `category` is `SEED`, `FERTILIZER`, or `CHEMICAL`, and its `unit` is `LB`, `GAL`, `SEED_UNIT`, or `TON`. Equipment `kind` is `TRACTOR`, `COMBINE`, `SPRAYER`, or `PLANTER`. A harvest lot's `quality_status` is `UNGRADED`, `GRADE_A`, `GRADE_B`, or `REJECTED`; its `sale_status` is `IN_INVENTORY`, `PARTIALLY_COMMITTED`, `FULLY_COMMITTED`, or `SHIPPED`. A sale contract's `min_quality` is either `GRADE_B` or `GRADE_A`. The full set of lifecycle states for crop plans, applications, contracts, lots, and other stateful entities is defined in §3 where each workflow is described.

### 2.10. Field Validation and Validation Ordering

Write requests undergo a fixed sequence of validations, and the relative ordering matters because the first failing check is the one whose error is returned. The order is: first, authentication — the `X-User-Role` header must be present and recognized, else `ERR_UNAUTHENTICATED`; second, authorization — the role must be permitted for the operation, else `ERR_FORBIDDEN`; third, existence — all path and body resource ids must resolve left-to-right, else `ERR_NOT_FOUND`; fourth, request shape — required body fields must be present and well-typed, enum members must be valid, and numeric ranges must hold (acreage greater than zero, moisture between 0 and 100 inclusive, and the like), else `ERR_INVALID_REQUEST` (HTTP 400).

Only after those four gates pass does the system evaluate domain rules, and these too carry a defined precedence. For transition endpoints, the target resource must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409); this state check precedes the deeper domain checks below. Cross-aggregate referential coherence is evaluated next where it applies (priority above the safety, temporal, rate, and fiscal families). Restricted-use safety rules — certification, applicator identity, re-entry interval, and pre-harvest interval — come next. Booking-window overlap checks follow. The seasonal rate cap is evaluated after those. Inventory sufficiency (seed waterfall coverage and contract overcommit) follows. Finally, the optimistic-concurrency check on parcel version is evaluated last among the domain rules. Each family and its error are described in the workflow sections of §3; the precedence given here is what disambiguates which error surfaces when more than one condition is violated at once.

## 3. Business Logic & Workflows

### 3.1. Parcels, Crops Plans, and the Revision Loop

The foundation of the system is the **parcel** — a field with a display `name`, a tillable `acreage` that must be strictly greater than zero, and a `soil_type`. A `FarmManager` creates parcels; each one begins life with `status` `AVAILABLE` and an `active_crop_plan_count` of zero. The parcel also exposes a `reentry_blocked_until` timestamp, computed from compliance activity (see §3.4), which is null whenever no re-entry block is active.

A **crop plan** commits a parcel to a single crop for a single season. A `FarmManager` or an `Agronomist` drafts a plan by supplying the `parcel_id` it occupies, the `crop`, the `season_year` (a calendar year of at least 2000), the `planned_acres` it intends to plant (which must be greater than zero), and three budget estimates: `budget_input_cost`, `budget_labor_cost`, and `budget_equipment_cost`, all in dollars. A new plan is created in `DRAFT` with `revision_count` zero and its computed cost and yield fields initialized. Beyond the budgets, a plan carries a family of derived figures populated as work proceeds — `planted_acres`, `harvested_acres`, `actual_input_cost`, `actual_labor_cost`, `actual_equipment_cost`, `provisional_cost_per_acre`, `final_cost_per_acre`, and `total_yield_units` — each described where its workflow lives.

Approval is a `FarmManager` action that moves a plan from `DRAFT` to `APPROVED`. Three preconditions guard it. The parcel's `status` must be `AVAILABLE`, or the request is rejected with `ERR_PARCEL_NOT_AVAILABLE`. The plan's `planned_acres` must not exceed the parcel's `acreage`, or it is rejected with `ERR_PLANNED_ACRES_EXCEED_PARCEL`. And the supplied `expected_parcel_version` must match the parcel's current `version`, or it is rejected with `ERR_STALE_PARCEL_VERSION` as described in §2.6. A successful approval recomputes the parcel's `active_crop_plan_count` — the number of plans on that parcel whose `status` is `APPROVED`, `GROWING`, or `HARVESTING` — and increments the parcel's `version` by one.

An `APPROVED` plan is not yet committed to the ground, and an `Agronomist` may send it back for rework. Requesting a revision moves the plan from `APPROVED` to `UNDER_REVISION`, provided no `PlantingEvent` with `status` `RECORDED` exists for the plan; if one does, the request is rejected with `ERR_PLAN_ALREADY_PLANTED`. Each such trip increments the plan's `revision_count` by one, and because the plan leaves the active set, the parcel's `active_crop_plan_count` is recomputed. From `UNDER_REVISION`, the same `FarmManager` approval path returns the plan to `APPROVED` under the identical three preconditions (parcel available, planned acres within acreage, and matching `expected_parcel_version`), again recomputing `active_crop_plan_count` and incrementing the parcel's `version`. A plan may cycle `APPROVED → UNDER_REVISION → APPROVED` any number of times; `revision_count` records how many loops it has taken.

A `FarmManager` may also abandon a plan. From `DRAFT`, abandonment moves the plan straight to `ABANDONED` with no preconditions and no side effects. From `APPROVED`, abandonment is permitted only when no `RECORDED` `PlantingEvent` exists for the plan — otherwise `ERR_PLAN_ALREADY_PLANTED` — and on success it recomputes the parcel's `active_crop_plan_count` and increments the parcel's `version` by one. `CLOSED` and `ABANDONED` are terminal.

### 3.2. Growing, Harvesting, and Closing a Plan

Once a plan is `APPROVED` and seed is in the ground, an `Agronomist` begins growth, advancing the plan from `APPROVED` to `GROWING`. This transition requires that `planted_acres` be greater than zero — that is, at least one `RECORDED` `PlantingEvent` exists — failing which it is rejected with `ERR_NO_PLANTING_RECORDED`. Beginning growth recomputes the plan's `provisional_cost_per_acre`.

A plan in `GROWING` accepts harvest events but cannot itself begin harvest until every regulated spray has cleared its pre-harvest window. An `Agronomist` moves the plan from `GROWING` to `HARVESTING`; the single precondition is that for every non-voided restricted application on the plan, the pre-harvest interval has elapsed (detailed in §3.4). If any restricted application is still inside its pre-harvest window, the transition is rejected with `ERR_PREHARVEST_INTERVAL_ACTIVE`. Once in `HARVESTING`, the plan accepts the recording of harvest events.

Closing is the final act, performed by a `FarmManager`, moving the plan from `HARVESTING` to `CLOSED`. It requires that `harvested_acres` be greater than zero, else `ERR_NO_HARVEST_RECORDED`. Closing triggers four reconciliations: the plan's `final_cost_per_acre` is computed using the final cost variant (§3.7), its `total_yield_units` is recomputed (§3.6), and because the plan leaves the parcel's active set, the parcel's `active_crop_plan_count` is recomputed and the parcel's `version` is incremented by one.

### 3.3. Input Products, Lots, and Inventory

The catalogue of things that can be applied or planted is the **input product**, created by a `FarmManager`. Each product has a `name`, a `category` of `SEED`, `FERTILIZER`, or `CHEMICAL`, a `unit` of measure, a `unit_cost` (dollars per unit, which must be at least zero), and a `restricted_use` flag that defaults to false. Restricted products demand more metadata: a `reentry_interval_hours` (the REI — the whole hours a parcel stays re-entry-blocked after the product is applied) and a `preharvest_interval_days` (the PHI — the minimum whole days that must elapse between application and harvest) are required when `restricted_use` is true and otherwise default to zero. A product may also carry a `max_seasonal_rate_per_acre`, a cap on cumulative applied rate per acre per plan; when null the product is uncapped.

Physical stock arrives as an **input lot**, received by a `FarmManager` against a product. A lot records its `input_product_id`, a supplier `lot_code`, and the `quantity_received` (which must be greater than zero); on receipt its `quantity_remaining` equals `quantity_received` and its `status` is `OPEN`. As plantings draw seed from lots, `quantity_remaining` falls; when it reaches exactly zero the lot's `status` flips to `DEPLETED`.

Seed consumption follows a FIFO waterfall driven when a planting is recorded. The quantity needed is `acres_planted` multiplied by `seed_rate_per_acre`, which is the planting's `seed_units_used`. The debit draws first from the lot named in the planting's `input_lot_id`, then continues across the remaining `OPEN` lots of the *same product* in ascending `created_at` order. At each lot the system takes the smaller of that lot's `quantity_remaining` and the quantity still needed, subtracts it from the lot's `quantity_remaining`, flips the lot to `DEPLETED` if its `quantity_remaining` has reached zero, and reduces the outstanding need by the amount taken; it stops as soon as the need is fully satisfied. If the candidate lots are exhausted and need still remains, the planting is rejected with `ERR_INSUFFICIENT_INVENTORY` and no partial debit is persisted — the inventory is left exactly as it was. Voiding a planting reverses this: the consumed quantities are restored to the lots, lots that were `DEPLETED` may revert to `OPEN`, and the plan's `planted_acres` is recomputed.

### 3.4. Restricted-Use Compliance: Applications, Re-Entry, and Pre-Harvest

The most heavily governed workflow is the logging and confirmation of input applications. An application is logged — by an `Agronomist` or an `Applicator` — against a plan by supplying the `crop_plan_id`, the `input_product_id` of the product applied, the `applicator_user_id` of the person performing the work, the `rate_per_acre` (units of product per acre, greater than zero), and the `acres_treated` (greater than zero). On logging, the record begins in `LOGGED` status; the system computes `quantity_used` as `rate_per_acre` multiplied by `acres_treated`, and `applied_cost` as `quantity_used` multiplied by the product's `unit_cost`, rounded to two decimal places. For non-restricted products any `Agronomist` id is an acceptable `applicator_user_id`; restricted products require a certified `Applicator`. A planting seed product is not an application input — submitting an application whose product `category` is `SEED` is rejected with `ERR_PRODUCT_CATEGORY_MISMATCH`.

Confirmation is exclusively an `Applicator` action and is where compliance is enforced, advancing the record from `LOGGED` to `CONFIRMED`. The owning plan must be in `GROWING`, else `ERR_PLAN_NOT_GROWING`. If the product is restricted, the acting applicator must be certified — the `Applicator`'s `certified` flag must be true, else `ERR_APPLICATOR_NOT_CERTIFIED` — and the acting applicator's `id` must equal the record's `applicator_user_id`, else `ERR_APPLICATOR_MISMATCH`. The re-entry gate is also evaluated at confirm: if the parcel's `status` is `RESTRICTED` and the current clock is earlier than the parcel's `reentry_blocked_until`, the confirm is rejected with `ERR_REENTRY_INTERVAL_ACTIVE`; the boundary is inclusive of clearance, meaning a clock exactly equal to `reentry_blocked_until` is permitted (the block applies strictly before that instant). Finally, the seasonal rate cap is checked: when the product's `max_seasonal_rate_per_acre` is set, the cumulative confirmed `rate_per_acre` for that product on that plan plus this record's `rate_per_acre` must not exceed the cap, else `ERR_SEASONAL_RATE_EXCEEDED`.

On a successful confirm, the system stamps `applied_at` from the server clock, recomputes `quantity_used` and `applied_cost`, and recomputes the plan's `actual_input_cost` and `provisional_cost_per_acre`. The record's `is_restricted` flag is set to mirror the product's `restricted_use` at confirm time. Note that confirming an application does **not** debit any input lot — applications draw conceptually from the product, not from a seed lot; only plantings debit lots.

When the confirmed product is restricted, additional cascades fire. The record's `reentry_clear_at` is computed as `applied_at` plus the product's `reentry_interval_hours` (a non-restricted application leaves `reentry_clear_at` null). A **compliance record** is created in `ACTIVE` status capturing the regulatory snapshot: its `application_record_id`, the denormalized `crop_plan_id`, the `applicator_user_id`, and point-in-time snapshots of `reentry_interval_hours`, `preharvest_interval_days`, and `reentry_clear_at`. The parcel's `status` is set to `RESTRICTED`; the parcel's `reentry_blocked_until` is recomputed as the latest `reentry_clear_at` across all `ACTIVE` compliance records on that parcel; and the parcel's `version` is incremented by one.

The pre-harvest gate that governs begin-harvest (§3.2) reads from these same records. For each non-voided restricted application on the plan, the earliest permissible harvest instant is its `applied_at` plus its `preharvest_interval_days` measured in whole days (24 hours per day). Begin-harvest is blocked while the current clock is earlier than the latest such instant across the plan's restricted applications; a clock exactly equal to that instant satisfies the pre-harvest interval and is allowed (the block applies strictly before the instant). When the gate is not satisfied the transition fails with `ERR_PREHARVEST_INTERVAL_ACTIVE`.

Voiding compensates. An `Agronomist` may void an application from `LOGGED` (no side effects) or from `CONFIRMED`. Voiding a confirmed application moves it to `VOIDED`, drops it out of the plan's `actual_input_cost` (recomputed) and recomputes `provisional_cost_per_acre`. If the voided application was restricted, its linked compliance record's `status` becomes `SUPERSEDED`; the parcel's `reentry_blocked_until` is recomputed as the latest `reentry_clear_at` over the remaining `ACTIVE` compliance records (or null if none remain); if no remaining `ACTIVE` compliance record keeps the parcel blocked and no other restricted record holds it, the parcel's `status` reverts to `AVAILABLE`; and the parcel's `version` is incremented by one. `VOIDED` is terminal for an application.

### 3.5. Planting and Harvest Events

A planting is recorded by an `Agronomist` against a plan with `crop_plan_id`, the seed lot's `input_lot_id`, the `acres_planted` (greater than zero), and the `seed_rate_per_acre` (greater than zero). The lot named by `input_lot_id` must stock a `SEED`-category product; if it does not, the planting is rejected with `ERR_PRODUCT_CATEGORY_MISMATCH`. A planting begins in `RECORDED`, drives the seed waterfall debit of §3.3, and recomputes the plan's `planted_acres` (the sum of `acres_planted` across the plan's non-voided plantings). Voiding a planting, also an `Agronomist` action, moves it to `VOIDED`, restores the debited quantities, and recomputes `planted_acres`.

A harvest is recorded by an `Agronomist` against a plan that is in `HARVESTING`, supplying `crop_plan_id`, the `acres_harvested` (greater than zero), the `gross_quantity` in crop units (at least zero), and the `moisture_pct` (between 0 and 100 inclusive). The event begins in `RECORDED`. Its dry-weight `net_quantity` is computed from the gross quantity reduced by the moisture fraction — that is, `gross_quantity` multiplied by the quantity (one minus `moisture_pct` divided by 100) — rounded to two decimal places. Recording a harvest recomputes the plan's `harvested_acres` (the sum of `acres_harvested` across the plan's `RECORDED` harvest events). A harvest event may be `VOIDED`.

### 3.6. Harvest Inventory: Lots, Grading, and Yield

Physical output is captured as a **harvest lot**, created by an `Agronomist` from a harvest event by naming the `harvest_event_id` and the lot `quantity` (greater than zero). The lot inherits its `crop_plan_id` from the harvest event by denormalization. A lot carries two *independent* state dimensions. The quality axis, `quality_status`, starts at `UNGRADED`. The sale axis, `sale_status`, starts at `IN_INVENTORY`, with `quantity_committed` at zero and `committed_contract_id` null. The two axes advance independently except where the eligibility gate at commit time couples them.

Grading is an `Agronomist` action on the quality axis and is only permitted while the lot is `UNGRADED`; grading an already-graded lot is rejected with `ERR_LOT_ALREADY_GRADED`. The supplied `grade` drives the transition: a lot may move from `UNGRADED` to `GRADE_A`, to `GRADE_B`, or to `REJECTED`. Grading to `GRADE_A` opens sale eligibility for contracts whose `min_quality` is at or below `GRADE_A`. Grading to `GRADE_B` carries no further side effect. Grading to `REJECTED` is the strictest branch: it additionally requires that the lot be `IN_INVENTORY` with `quantity_committed` of zero — a lot that already has committed quantity cannot be rejected and the attempt fails with `ERR_LOT_ALREADY_COMMITTED` — and once rejected the lot is permanently ineligible for any contract.

The plan's realized yield, `total_yield_units`, is the sum over the plan's harvest lots whose `quality_status` is `GRADE_A` or `GRADE_B` of each lot's `quantity`, rounded to two decimal places, with the rounding applied once after the full sum. Lots that are `UNGRADED` or `REJECTED` are excluded from `total_yield_units`. This persisted yield always uses the graded-only filter; an interim gross-basis read that sums quantity over all non-rejected lots including `UNGRADED` is a different figure and never replaces the graded-only `total_yield_units` field. `total_yield_units` is recomputed when a plan is closed.

### 3.7. Cost-Per-Acre: Provisional and Final Variants

Each plan reports a cost-per-acre, but in two distinct flavors. The **provisional** figure is forward-looking and uses budgeted estimates: its numerator is the sum of `budget_input_cost`, `budget_labor_cost`, and `budget_equipment_cost`, and its denominator is `planned_acres`; `provisional_cost_per_acre` is that quotient rounded to two decimal places, rounded once at the end. It ignores actuals entirely and charges the full equipment budget to the plan with no acreage-share split. It is recomputed whenever the inputs change — at begin-growing, and on any confirm or void of an application, or any labor or equipment change.

The **final** figure is computed once, at close, from chronological actuals. Its direct costs are the sum of `actual_input_cost` (the sum of `applied_cost` across the plan's non-voided confirmed applications) and `actual_labor_cost` (the sum of `labor_cost` across the plan's labor entries). Its overhead is `actual_equipment_cost` (the sum of `usage_cost` across the plan's `RECORDED` equipment usages), and that overhead is allocated to the plan by an acreage-share factor. When this plan is the only plan harvested on its parcel for its `season_year`, the allocation factor is one and the full equipment cost lands on the plan. Otherwise the factor is this plan's `harvested_acres` divided by the sum of `harvested_acres` across all plans on the parcel in `CLOSED` or `HARVESTING` status for that `season_year`. The final numerator is the direct costs plus the equipment overhead multiplied by that allocation factor; the denominator is the plan's actual `harvested_acres`, not its planned acres. The denominator is guarded by a minimum of one to avoid division by a smaller figure. The resulting `final_cost_per_acre` is rounded to two decimal places, rounded once at the very end, and remains null until the plan is `CLOSED`.

### 3.8. Equipment, Labor, and Irrigation Scheduling

Machines are registered as **equipment assets** by a `FarmManager`, each with a `name`, a `kind`, and an `hourly_cost` (at least zero). An asset begins `ACTIVE`; an asset whose `status` is `DOWN` cannot take new usage bookings. An asset also reports `total_logged_hours`, the sum of `hours` across its `RECORDED` usages on all plans.

An `Agronomist` books **equipment usage** to a plan by naming the `equipment_asset_id`, the `crop_plan_id` it bills to, and a `window_start` (inclusive) and `window_end` (exclusive) where `window_end` must be strictly after `window_start`; a window where `window_end` is not after `window_start` is rejected with `ERR_VALIDATION_WINDOW_INVALID`. The usage's `hours` is the duration from `window_start` to `window_end` expressed in hours and rounded to two decimal places, and its `usage_cost` is `hours` multiplied by the asset's `hourly_cost`, rounded to two decimal places. Booking against a `DOWN` asset is rejected with `ERR_EQUIPMENT_DOWN`. Equipment windows must not overlap on the same asset, and the geometry is half-open: a new window for an asset conflicts with an existing `RECORDED` usage of that asset when the new start is before the existing end and the existing start is before the new end; back-to-back bookings where the new start equals the existing end do not conflict and are permitted. An overlapping booking is rejected with `ERR_EQUIPMENT_WINDOW_CONFLICT`. A successful booking recomputes the asset's `total_logged_hours` and the plan's `actual_equipment_cost` and `provisional_cost_per_acre`. An equipment usage may be `VOIDED`.

Labor is recorded against a plan — by an `Agronomist` or a `FarmManager` — with the `crop_plan_id`, a `worker_name`, the `hours` worked (greater than zero), and the `hourly_rate` (at least zero). The entry's `labor_cost` is `hours` multiplied by `hourly_rate`, rounded to two decimal places, and recording it recomputes the plan's `actual_labor_cost` and `provisional_cost_per_acre`.

Irrigation is scheduled against a parcel by an `Agronomist`, supplying the `parcel_id`, a `window_start` (inclusive), a `window_end` (inclusive) that must be strictly after `window_start` — otherwise `ERR_VALIDATION_WINDOW_INVALID` — and the `inches_applied` (greater than zero). An irrigation event begins `SCHEDULED`. Its overlap geometry is deliberately *stricter* than equipment's: irrigation uses closed intervals with a six-hour buffer on each side, a soil-saturation guard. A new irrigation event on a parcel conflicts with any `SCHEDULED` or `COMPLETED` event on the same parcel when the new start is at or before the existing end plus six hours, and the existing start is at or before the new end plus six hours. Because the interval is closed and buffered, touching endpoints do conflict, and bookings within six hours of one another also conflict; such an attempt is rejected with `ERR_IRRIGATION_WINDOW_CONFLICT`. An `Agronomist` completes a scheduled event, moving it from `SCHEDULED` to `COMPLETED`, but only once the current clock is at or after its `window_start`; an early attempt is rejected with `ERR_IRRIGATION_NOT_DUE`. An `Agronomist` may instead cancel a scheduled event, moving it from `SCHEDULED` to `CANCELLED`, which frees its window for overlap purposes.

### 3.9. Sale Contracts: Committing, Filling, Shipping, and Cancelling

A `SalesAgent` opens a **sale contract** by supplying the `crop` it buys, the `buyer_name`, the `contracted_quantity` it must be filled with (greater than zero), the `price_per_unit` (at least zero), and an optional `min_quality` that defaults to `GRADE_B`. A new contract is `OPEN` with `committed_quantity` zero and `contract_value` zero.

Filling a contract is done by committing harvest-lot quantity to it. A `SalesAgent` commits by naming the `harvest_lot_id` and the `commit_quantity` to apply from that lot's uncommitted quantity. Several eligibility rules guard the commit. The lot's `quality_status` must be `GRADE_A` or `GRADE_B` and must meet or exceed the contract's `min_quality`; an `UNGRADED`, `REJECTED`, or insufficiently-graded lot is rejected with `ERR_LOT_QUALITY_INSUFFICIENT`. The crop must match: the `crop` of the plan behind the lot must equal the contract's `crop`, else `ERR_CROP_MISMATCH`. A lot already committed to a *different* contract cannot be committed elsewhere, and a continuing commit must target the same `committed_contract_id` already on the lot, else `ERR_LOT_ALREADY_COMMITTED`. The commit must not push the contract's `committed_quantity` beyond its `contracted_quantity`; an overcommit is rejected with `ERR_CONTRACT_OVERCOMMIT`, and the lot must have uncommitted quantity available to draw from, with insufficiency rejected as `ERR_INSUFFICIENT_INVENTORY`.

A successful commit raises the lot's `quantity_committed`, sets the lot's `committed_contract_id`, and advances the lot's `sale_status`: a partial fill of the lot moves it from `IN_INVENTORY` to `PARTIALLY_COMMITTED`; a commit that consumes the whole lot moves it to `FULLY_COMMITTED`, whether from `IN_INVENTORY` directly or from `PARTIALLY_COMMITTED` once the remainder is committed to the same contract. In lockstep, the contract's `committed_quantity` and `contract_value` (its `committed_quantity` multiplied by `price_per_unit`, rounded to two decimal places) are recomputed, and its `status` advances: a contract whose committed quantity is still below contracted moves from `OPEN` to `PARTIALLY_FILLED` (and a further commit that is still short keeps it `PARTIALLY_FILLED`); a commit that brings committed exactly to contracted moves it to `FILLED`, whether reached in one commit from `OPEN` or by reaching the target from `PARTIALLY_FILLED`.

Shipping is a `SalesAgent` action permitted only on a `FILLED` contract, moving it from `FILLED` to `SHIPPED`; attempting to ship a contract that is not `FILLED` is rejected with `ERR_CONTRACT_NOT_FILLED`. Shipping cascades to inventory: every harvest lot whose `committed_contract_id` is this contract has its `sale_status` advanced from `FULLY_COMMITTED` to `SHIPPED`, which is terminal for the lot and freezes it.

Cancellation is the compensating path. A `SalesAgent` may cancel a contract that is `OPEN` or `PARTIALLY_FILLED`, moving it to `CANCELLED`. Cancelling an `OPEN` contract has no committed lots to release. Cancelling a `PARTIALLY_FILLED` contract releases every committed lot: each such lot has its `quantity_committed` reset to zero, its `committed_contract_id` cleared to null, and its `sale_status` returned to `IN_INVENTORY`, and the contract's `committed_quantity` and `contract_value` are recomputed accordingly. `SHIPPED` and `CANCELLED` are terminal for a contract.

### 3.10. Applicators and the Test-Driving Clock

The applicator roster is maintained by a `FarmManager`, who registers an **applicator** with a `full_name`, a restricted-use `license_no`, and a `certified` flag that defaults to true. A restricted-use confirm checks this `certified` flag and matches the acting applicator's identity against the application's `applicator_user_id`, as described in §3.4.

Because re-entry and pre-harvest windows are time-driven, the system exposes an administrative test-driving capability, restricted to a `FarmManager`, that sets the server's current UTC clock to a supplied `to_iso8601` instant. Advancing or rewinding the clock deterministically drives the `applied_at` stamping at confirm time and all subsequent window comparisons — the re-entry block at application confirm, the pre-harvest gate at begin-harvest, and the due-time check at irrigation completion. The capability returns the resulting current clock.

## 4. Endpoint Definitions

Operations that create a new standalone resource return `201 Created`. Operations that read a resource, list resources, or drive a state transition or other modification on an existing resource return `200 OK`. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1; the request and response bodies for each operation are reconstructed from the business narrative in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/parcels` | Create a parcel/field | FarmManager |
| GET | `/parcels/{id}` | Get a parcel | FarmManager, Agronomist, Applicator, SalesAgent |
| GET | `/parcels` | List parcels | FarmManager, Agronomist, Applicator, SalesAgent |
| GET | `/parcels/{id}/crop-plans` | List crop plans on a parcel | FarmManager, Agronomist, Applicator, SalesAgent |
| GET | `/parcels/{id}/irrigation-events` | List irrigation events on a parcel | FarmManager, Agronomist, SalesAgent, Applicator |
| POST | `/crop-plans` | Create a crop plan | Agronomist, FarmManager |
| GET | `/crop-plans/{id}` | Get a crop plan | FarmManager, Agronomist, Applicator, SalesAgent |
| GET | `/crop-plans` | List crop plans | FarmManager, Agronomist, Applicator, SalesAgent |
| POST | `/crop-plans/{id}/approve` | Approve a plan (OCC on parcel version) | FarmManager |
| POST | `/crop-plans/{id}/request-revision` | Send an approved plan back to revision | Agronomist |
| POST | `/crop-plans/{id}/begin-growing` | Move an approved plan to growing | Agronomist |
| POST | `/crop-plans/{id}/begin-harvest` | Move a growing plan to harvesting | Agronomist |
| POST | `/crop-plans/{id}/close` | Close a harvesting plan | FarmManager |
| POST | `/crop-plans/{id}/abandon` | Abandon a draft or approved plan | FarmManager |
| POST | `/input-products` | Create an input product | FarmManager |
| GET | `/input-products/{id}` | Get an input product | FarmManager, Agronomist, Applicator |
| GET | `/input-products/{id}/lots` | List lots of a product | FarmManager, Agronomist, Applicator |
| POST | `/input-lots` | Receive a lot into inventory | FarmManager |
| GET | `/input-lots/{id}` | Get an input lot | FarmManager, Agronomist, Applicator |
| POST | `/application-records` | Log an application against a plan | Agronomist, Applicator |
| GET | `/application-records/{id}` | Get an application record | FarmManager, Agronomist, Applicator |
| GET | `/application-records` | List application records | FarmManager, Agronomist, Applicator |
| POST | `/application-records/{id}/confirm` | Confirm a logged application | Applicator |
| POST | `/application-records/{id}/void` | Void an application | Agronomist |
| GET | `/compliance-records/{id}` | Get a compliance record | FarmManager, Agronomist, Applicator |
| GET | `/compliance-records` | List compliance records | FarmManager, Agronomist, Applicator |
| POST | `/planting-events` | Record a planting | Agronomist |
| GET | `/planting-events/{id}` | Get a planting event | FarmManager, Agronomist |
| GET | `/planting-events` | List planting events | FarmManager, Agronomist |
| POST | `/planting-events/{id}/void` | Void a planting event | Agronomist |
| POST | `/harvest-events` | Record a harvest event | Agronomist |
| GET | `/harvest-events/{id}` | Get a harvest event | FarmManager, Agronomist, SalesAgent |
| GET | `/harvest-events` | List harvest events | FarmManager, Agronomist, SalesAgent |
| GET | `/harvest-events/{id}/harvest-lots` | List lots produced by a harvest event | FarmManager, Agronomist, SalesAgent |
| POST | `/harvest-lots` | Create an inventory lot from a harvest event | Agronomist |
| GET | `/harvest-lots/{id}` | Get a harvest lot | FarmManager, Agronomist, SalesAgent |
| GET | `/harvest-lots` | List harvest lots | FarmManager, Agronomist, SalesAgent |
| POST | `/harvest-lots/{id}/grade` | Set quality grade on a lot | Agronomist |
| POST | `/sale-contracts` | Create a sale contract | SalesAgent |
| GET | `/sale-contracts/{id}` | Get a sale contract | FarmManager, SalesAgent, Agronomist |
| GET | `/sale-contracts` | List sale contracts | FarmManager, SalesAgent, Agronomist |
| GET | `/sale-contracts/{id}/harvest-lots` | List lots committed to a contract | FarmManager, SalesAgent, Agronomist |
| POST | `/sale-contracts/{id}/commit-lot` | Commit a lot's quantity to the contract | SalesAgent |
| POST | `/sale-contracts/{id}/ship` | Ship a filled contract | SalesAgent |
| POST | `/sale-contracts/{id}/cancel` | Cancel an open or partially filled contract | SalesAgent |
| POST | `/equipment-assets` | Create an equipment asset | FarmManager |
| GET | `/equipment-assets/{id}` | Get an equipment asset | FarmManager, Agronomist |
| GET | `/equipment-assets/{id}/usages` | List usages of an asset | FarmManager, Agronomist |
| POST | `/equipment-usages` | Book equipment usage to a plan | Agronomist |
| GET | `/equipment-usages/{id}` | Get an equipment usage | FarmManager, Agronomist |
| GET | `/equipment-usages` | List equipment usages | FarmManager, Agronomist |
| POST | `/labor-entries` | Record labor against a plan | Agronomist, FarmManager |
| GET | `/labor-entries/{id}` | Get a labor entry | FarmManager, Agronomist |
| GET | `/labor-entries` | List labor entries | FarmManager, Agronomist |
| POST | `/irrigation-events` | Schedule an irrigation event on a parcel | Agronomist |
| GET | `/irrigation-events/{id}` | Get an irrigation event | FarmManager, Agronomist |
| POST | `/irrigation-events/{id}/complete` | Mark a scheduled irrigation completed | Agronomist |
| POST | `/irrigation-events/{id}/cancel` | Cancel a scheduled irrigation | Agronomist |
| POST | `/applicators` | Register a certified applicator | FarmManager |
| GET | `/applicators/{id}` | Get an applicator | FarmManager, Agronomist, Applicator |
| POST | `/_clock/set` | Test-driving: set the server UTC clock | FarmManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PARCEL_NOT_AVAILABLE` | 409 Conflict |
| `ERR_PLANNED_ACRES_EXCEED_PARCEL` | 409 Conflict |
| `ERR_STALE_PARCEL_VERSION` | 412 Precondition Failed |
| `ERR_PLAN_ALREADY_PLANTED` | 409 Conflict |
| `ERR_NO_PLANTING_RECORDED` | 409 Conflict |
| `ERR_NO_HARVEST_RECORDED` | 409 Conflict |
| `ERR_PLAN_NOT_GROWING` | 409 Conflict |
| `ERR_APPLICATOR_NOT_CERTIFIED` | 409 Conflict |
| `ERR_APPLICATOR_MISMATCH` | 409 Conflict |
| `ERR_REENTRY_INTERVAL_ACTIVE` | 409 Conflict |
| `ERR_PREHARVEST_INTERVAL_ACTIVE` | 409 Conflict |
| `ERR_SEASONAL_RATE_EXCEEDED` | 409 Conflict |
| `ERR_PRODUCT_CATEGORY_MISMATCH` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_EQUIPMENT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_EQUIPMENT_DOWN` | 409 Conflict |
| `ERR_IRRIGATION_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_IRRIGATION_NOT_DUE` | 409 Conflict |
| `ERR_LOT_QUALITY_INSUFFICIENT` | 409 Conflict |
| `ERR_LOT_ALREADY_GRADED` | 409 Conflict |
| `ERR_LOT_ALREADY_COMMITTED` | 409 Conflict |
| `ERR_CROP_MISMATCH` | 409 Conflict |
| `ERR_CONTRACT_OVERCOMMIT` | 409 Conflict |
| `ERR_CONTRACT_NOT_FILLED` | 409 Conflict |
| `ERR_VALIDATION_WINDOW_INVALID` | 400 Bad Request |
