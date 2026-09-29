# RV Assembly Plant API — Product Requirements Document

## 1. Introduction

A recreational-vehicle plant is three businesses wearing one roof. It is a factory, where a bare chassis arriving on a truck becomes a forty-foot coach through a fixed sequence of stations — sidewall lamination, roof set, systems rough-in, appliance installation, finish, water test, pre-delivery inspection. It is a capacity broker, because the line has only so many station hours per day and every franchised dealer holds a contractual share of them. And it is a lender, because most units leave the plant on floor-plan financing: the plant advances the majority of the invoice, the dealer carries the unit in inventory, and the principal is curtailed on a schedule as the coach ages on the lot. When any one of those three businesses loses track of the other two, the plant builds coaches nobody can pay for, or slots capacity a dealer is not entitled to, or ships a unit carrying a recalled water heater.

This API is the transactional system of record that keeps the three aligned. It holds the plant's master data — suppliers and their trust scores, floor plans, the option catalogue with its requires-and-excludes web, dealer agreements with their capacity shares and credit lines, assembly lines, and test booths. It holds the supply side: chassis received into an unmatched pool, and component lots whose piece counts must be conserved from receipt through installation, reversal, or recall quarantine. It holds demand: dealer unit orders that carry two independent lifecycles at once — a build-progress dimension and a floor-plan financing dimension that advance on their own clocks. And it holds the after-sale tail: warranty claims adjudicated against a flat-rate labour schedule with bounded goodwill authority, and recall campaigns that reach backwards from a supplier's lot code through every installation, every build, and every order still standing in the yard.

Two design commitments run through every section that follows. The first is that quantities are conserved and derived, never asserted: station hours, piece counts, credit exposure, goodwill spend, and supplier penalty weight are all recomputed from their underlying rows rather than trusted as stored totals. The second is that ordering is part of the contract. Validation bands fire in a fixed sequence, discount lines round individually before they are summed, warranty reimbursement steps read each other's outputs, and a stale reader is told it is stale before it is told about a capacity problem it cannot yet see. Section 2 fixes the global contract, Section 3 specifies the domain workflows and the arithmetic behind them, Section 4 lists the endpoint surface, and Section 5 catalogues every error identifier. Every path in this API is absolute and root-level; there is no common URL prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. Caller Identity and the Seven Plant Roles

Every request must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which that principal acts. If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (401), and this check runs before the role is examined at all — so an unauthenticated call to an endpoint that no role may reach still returns 401 rather than 403. If the declared role is not one of the seven names below, or is a valid name that is not listed among the authorised roles for the target operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (403). Authorisation strictly precedes body parsing: a wrong-role call carrying a malformed body returns 403, never 400.

The seven roles are `PlantAdmin`, `DealerPrincipal`, `ProductionScheduler`, `LineSupervisor`, `QualityInspector`, `WarrantyAdministrator`, and `RecallCoordinator`. None is a superset of another; the model is deliberately one of segregated duties. `PlantAdmin` owns master data and plant finance — suppliers, floor plans, options, dealers, lines, booths, supply intake, floor-plan funding decisions, the logical clock, the daily-close checkpoint, and the test-driving injection capability — and is deliberately barred from acting inside the shop floor, quality, warranty, and recall workflows. `DealerPrincipal` is the ordering dealer. `ProductionScheduler` owns capacity and the order-to-line handoff: slot reservation, chassis matching, release to line, and shipment. `LineSupervisor` runs the stations: advancement, component installation, and installation reversal. `QualityInspector` books booth windows and grades inspections. `WarrantyAdministrator` adjudicates claims. `RecallCoordinator` files, opens, expands, and closes recall campaigns and records remedies on affected installations.

Identity binds differently per role. When `X-User-Role` is `DealerPrincipal`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a dealer compare that resource's dealer reference to `X-User-ID`. Concretely, a `DealerPrincipal` may only address a `UnitOrder` whose `dealer_id` equals its `X-User-ID`, may only file or resubmit a `WarrantyClaim` whose `dealer_id` equals its `X-User-ID`, and on order creation must supply a `dealer_id` in the body equal to its own `X-User-ID`; any of these mismatches is rejected with `ERR_DEALER_SCOPE_VIOLATION` (403). For the other six roles — `PlantAdmin`, `ProductionScheduler`, `LineSupervisor`, `QualityInspector`, `WarrantyAdministrator`, and `RecallCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands an audit trail (as `inspector_user_id` and `completed_by_user_id` on a `QualityInspection`, and as `approved_by_user_id` and `paid_by_user_id` on a `WarrantyClaim`) and compares recorded values against each other for the duty splits described in §2.11, but it never compares such an identifier to any entity's `id`.

Ownership is evaluated after existence. A `DealerPrincipal` probing an order identifier that does not exist receives a 404, not a 403 that would leak the identifier space.

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

### 2.3. Pagination and List Ordering

Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100. A `limit` below 1 or above 100 is rejected with `ERR_INVALID_REQUEST` (400). `offset` is the zero-based index of the first row returned and defaults to 0.

List results are ordered by `created_at` ascending unless a subsection below says otherwise, and that default applies to every collection in the API. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of rows matching the supplied filters before pagination is applied, and `has_more` is true exactly when rows matching the filters remain beyond the returned page.

### 2.4. Resource Identity, Timestamps and the Version Counter

Every resource in this API — `Supplier`, `FloorPlan`, `OptionItem`, `Dealer`, `UnitOrder`, `ProductionLine`, `ProductionSlot`, `ChassisReceipt`, `ComponentLot`, `UnitBuild`, `ComponentInstallation`, `TestBooth`, `QualityInspection`, `WarrantyClaim`, and `RecallCampaign` — carries the same four system-managed properties.

- `id` is a server-minted UUID string. It carries no type prefix and clients never supply it.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written.
- `updated_at` is an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row.
- `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the row.

No entity in this API is exempt: all fifteen resources carry all four properties. A mutation, for this purpose, includes a change to a derived field. When a curtailment sweep recomputes `curtailment_due_cents` and moves an order's `financing_status`, when a recall quarantine flips a lot's piece counters, or when an installation remedy clears a build's `recall_hold`, the affected row's `version` increments and its `updated_at` is refreshed just as it would for a client-driven edit. Where a single operation touches several rows, each touched row's `version` increments once for that operation.

The `version` counter is load-bearing in three distinct ways: it is the audit trail described above, it is the token the optimistic-concurrency rules of §2.7 compare against, and it is the drift detector behind configuration pinning. Master-data edits are the clearest case — repricing or retiring a floor plan increments that `FloorPlan`'s `version`, and repricing or discontinuing an option increments that `OptionItem`'s `version`, which is precisely how an already-submitted order discovers that the catalogue moved underneath it.

### 2.5. The Logical Clock and the Daily-Close Checkpoint

The plant does not read the wall clock. Every age, window, expiry, and warranty period in this specification is measured against a logical clock whose value before any call is `2026-08-01T00:00:00Z`. A `PlantAdmin` moves it by supplying a `current_utc` instant; the response reports both the new `current_utc` and the `previous_utc` it replaced. The clock may only move forward — a supplied value equal to or earlier than the current clock is rejected with `ERR_INVALID_REQUEST`. Advancing the clock is not itself an operational event: it changes what `curtailment_due_cents` and `in_warranty` evaluate to on the next read, but it releases no slot reservation and curtails no advance on its own.

Those consequential state changes belong to the **daily-close checkpoint**, an ops run also reserved to `PlantAdmin`. A daily close does two sweeps. The expiry sweep finds every `ProductionSlot` whose `status` is `RESERVED` and whose `expires_at` is at or before the current clock and moves it `RESERVED → RELEASED`, cascading as described in §3.3. The curtailment sweep finds every `UnitOrder` whose `financing_status` is `FLOOR_PLAN_FUNDED` and whose computed curtailment obligation is positive and moves it `FLOOR_PLAN_FUNDED → CURTAILED`, persisting the recomputed `curtailment_due_cents`. Afterwards `credit_utilization_bp` and `credit_status` are recomputed for every dealer the sweeps touched. The response reports `released_slot_count`, the `released_order_ids` array of orders that came back out of `SLOTTED`, `curtailed_order_count`, the `curtailed_order_ids` array, and the `evaluated_at` instant at which the checkpoint ran. The checkpoint is idempotent within one clock instant: running it a second time without advancing the clock releases and curtails nothing further and reports zero counts.

Ages derived from the clock are always whole days, computed by discarding any fractional remainder of the elapsed interval — a unit funded at midnight and inspected at 23:59 the same day is zero days old, not one.

### 2.6. Money, Station Hours and Rounding Discipline

Monetary amounts are integers denominated in whole cents; there are no fractional cents anywhere in the system, and no money field is ever represented as a decimal string. Rates and shares are expressed in **basis points** — hundredths of a percent, so 10000 basis points is the whole amount — and basis-point values themselves are integers. Weights are integer pounds, electrical draw is integer amps, water demand and tank capacity are integer gallons, defect points are integers, and piece counts are integers.

Station hours are the plant's scheduling currency and are the one quantity carried to two decimal places. Wherever a station-hour figure is produced by a calculation, it is rounded half up to exactly two decimal places, and — critically — the rounding is applied once, to the final result of the expression, never to intermediate factors. A request supplying a station-hour value with more than two decimal places is rejected with `ERR_INVALID_REQUEST`.

Two rounding boundaries deserve advance warning because a plausible implementation gets them wrong. First, invoice discounts are computed and rounded **per line** before the lines are summed; totalling the raw discounted products and rounding once at the end produces a different figure and is incorrect. Second, ages in days are floored, but every monetary and station-hour product is rounded half up. Where a calculation in Section 3 names a rounding step, that step is part of the contract and its position in the sequence matters as much as its method.

Truncation appears in exactly one place: basis-point utilisation figures derived by division are floored toward zero rather than rounded, as §3.7 spells out.

### 2.7. Version Pinning and Optimistic Concurrency

Two write operations require the caller to prove it has read the parent row it is about to change, and both use an explicit expected-version field that is a required, non-optional part of the request body.

`POST /unit-orders/{id}/production-slots` requires `expected_unit_order_version`, carrying the client's last observed `version` of the target `UnitOrder`. If that value does not equal the order's current `version`, the reservation is rejected with `ERR_STALE_UNIT_ORDER_VERSION` (412). This guard exists because re-slotting is legitimate: a second reservation supersedes the order's prior `RESERVED` slot, so without the check a scheduler working from an outdated view would silently discard a slot it never saw, and would misread the `sequence_position` it was about to receive. The check forces a re-read first.

`POST /recall-campaigns/{id}/expand` requires `expected_recall_campaign_version`, carrying the client's last observed `version` of the target `RecallCampaign`. If that value does not equal the campaign's current `version`, the expansion is rejected with `ERR_STALE_RECALL_CAMPAIGN_VERSION` (412). Each expansion supersedes the prior lot-code scope and drags a fresh quarantine cascade behind it, so a coordinator filing from a stale view would omit lots a previous expansion already added and would misread `affected_installation_count`.

No other endpoint in this API accepts an expected-version field, and no other endpoint performs an optimistic-concurrency check. Where the specification elsewhere speaks of "stale" data — the pinned `locked_floor_plan_version` and `locked_option_versions` re-checked at chassis matching and release to line — that is a different mechanism: the pinned values are captured by the server at submit and compared by the server later, with no client-supplied token involved, and drift there surfaces as `ERR_CONFIG_REFERENCE_STALE` (409) rather than as a 412.

### 2.8. The Validation Precedence Ladder

Validation is a strictly ordered ladder, not a set of independent checks. The **first** violated rule determines the response; later rules are never reported even when they are also violated. Implementations must therefore evaluate in exactly this order.

1. **Identity headers.** `X-User-ID` and `X-User-Role` both present and non-empty, else `ERR_UNAUTHENTICATED` (401).
2. **Authorisation.** The declared role is one of the seven names and appears in the target endpoint's role list, else `ERR_ROLE_NOT_PERMITTED` (403).
3. **Schema.** The body parses; every required field is present; every field matches its declared type; every enum value is a declared member; every money field is a non-negative integer; every station-hour field carries at most two decimals; no array field contains duplicates. Violations are `ERR_INVALID_REQUEST` (400). This band also covers a booth window whose `window_end` is at or before its `window_start`, a booth window shorter than 30 or longer than 240 minutes, an installation `quantity` of zero or less, an `amount_cents` of zero or less, `labor_hours` of zero or less, duplicate entries in `selected_option_ids`, a pagination `limit` outside 1 through 100, a `test_booth_id` absent for a `WATER_TEST` or `FUNCTIONAL` inspection or present for a `PDI` inspection, a `test_booth_id` whose booth `booth_type` does not equal the requested `inspection_type`, and a clock value not strictly after the current clock.
4. **Path existence.** Every `{id}` segment resolves to an existing row of the addressed entity, else the entity-specific 404 code: `ERR_UNIT_ORDER_NOT_FOUND`, `ERR_PRODUCTION_SLOT_NOT_FOUND`, `ERR_CHASSIS_RECEIPT_NOT_FOUND`, `ERR_COMPONENT_LOT_NOT_FOUND`, `ERR_UNIT_BUILD_NOT_FOUND`, `ERR_COMPONENT_INSTALLATION_NOT_FOUND`, `ERR_QUALITY_INSPECTION_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, `ERR_RECALL_CAMPAIGN_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_FLOOR_PLAN_NOT_FOUND`, `ERR_OPTION_ITEM_NOT_FOUND`, `ERR_PRODUCTION_LINE_NOT_FOUND`, or `ERR_TEST_BOOTH_NOT_FOUND`. Where a path carries more than one identifier, they are resolved left to right and the leftmost failure is the one reported.
5. **Body foreign keys.** Every foreign key supplied in the request **body** resolves to an existing row, using the same per-entity 404 codes, and checked in the field order the endpoint declares its inputs. Body keys are always checked after path identifiers. This band guards order creation, configuration replacement, slot reservation, component-lot receipt, chassis receipt, component installation, inspection scheduling, warranty filing, recall drafting, and the delivered-unit injection.
6. **Dealer ownership.** For a `DealerPrincipal`, `X-User-ID` equals the `dealer_id` of the addressed `UnitOrder` or `WarrantyClaim`, and equals the `dealer_id` supplied in the body on creation, else `ERR_DEALER_SCOPE_VIOLATION` (403).
7. **State.** The addressed entity is in a state from which the requested transition exists, and the required companion rows are in their required states. The generic code is `ERR_INVALID_STATE` (409), but a specific code takes its place wherever one is defined: `ERR_ORDER_NOT_SUBMITTABLE`, `ERR_ORDER_NOT_SLOTTABLE`, `ERR_ORDER_ALREADY_MATCHED`, `ERR_CHASSIS_NOT_MATCHED`, `ERR_DEALER_SUSPENDED`, `ERR_FLOOR_PLAN_RETIRED`, `ERR_STATION_SEQUENCE_VIOLATION`, `ERR_LINE_NOT_RUNNING`, `ERR_BOOTH_NOT_OPEN`, `ERR_INSPECTION_STATION_MISMATCH`, `ERR_LOT_QUANTITY_INSUFFICIENT`, `ERR_CLAIM_NOT_DECIDABLE`, `ERR_INFO_REQUEST_LIMIT_REACHED`, `ERR_CAMPAIGN_NOT_CLOSEABLE`, `ERR_PAYMENT_EXCEEDS_PRINCIPAL`, and `ERR_QUALITY_HOLD`.
8. **Optimistic concurrency.** The expected-version fields of §2.7 match their parent rows, else the 412 codes named there. This band sits deliberately **after** the state gate, so reserving a slot for a `CANCELLED` order returns 409 even when the supplied version is also stale; and deliberately **before** every business rule, so a stale caller is never told about a capacity or credit problem it cannot yet see.
9. **Safety.** Two independent rules share this rank and guard disjoint endpoint sets, so their relative order is never observable. The shipment-and-advancement rule fires in this internal order: `ERR_RECALL_SHIP_STOP` first (the build's `recall_hold` is true, or the order's `ship_hold_reason` is `RECALL_HOLD`), then `ERR_WATER_TEST_NOT_PASSED`, then `ERR_PDI_NOT_PASSED` — a unit that is both recall-held and PDI-incomplete reports the recall. The duty-split rule yields `ERR_SEGREGATION_OF_DUTIES` and guards inspection completion and warranty payment as described in §2.11.
10. **Gross weight.** `config_weight_lbs` may not exceed the floor plan's `gvwr_lbs`, else `ERR_PAYLOAD_CAPACITY_EXCEEDED` (422). This is the first physical rule and it outranks every option-compatibility rule: a configuration that is both overweight and missing a required companion option reports the weight.
11. **Shore power.** `total_amp_draw` may not exceed the floor plan's `electrical_service_amps`, else `ERR_ELECTRICAL_SERVICE_EXCEEDED` (422). Checked after weight and before the water system.
12. **Water system.** `total_water_demand_gal` may not exceed the plumbed-demand ceiling of §3.2, else `ERR_WATER_SYSTEM_CAPACITY_EXCEEDED` (422).
13. **Option-set consistency**, in this internal order: `ERR_OPTION_DISCONTINUED` (a selected option whose `status` is `DISCONTINUED`), then `ERR_OPTION_REQUIRES_MISSING` (the transitive requires closure is unsatisfied), then `ERR_OPTION_MUTUALLY_EXCLUSIVE` (an excluding pair is present), then `ERR_STATION_HOURS_LIMIT_EXCEEDED` (the computed `required_station_hours` exceeds the single-unit ceiling). All four carry HTTP 422.
14. **Referential drift**, in this internal order: `ERR_CONFIG_REFERENCE_STALE` (the pinned floor-plan or option versions have moved), then `ERR_NO_MATCHING_CHASSIS`, then `ERR_LOT_QUARANTINED`.
15. **Temporal capacity**, in this internal order: `ERR_BOOTH_WINDOW_CONFLICT` on booth reservations; and on slot reservations `ERR_LINE_DAY_UNIT_CAP_EXCEEDED` first, then `ERR_LINE_DAY_HOURS_EXCEEDED`.
16. **Fiscal**, last of all and in this internal order: `ERR_DEALER_CREDIT_HOLD` (the dealer's `credit_status` is `CREDIT_HOLD`), then `ERR_DEALER_CURTAILMENT_DELINQUENT` (some order of the dealer is `CURTAILED` with a positive `curtailment_due_cents`), then `ERR_DEALER_ALLOCATION_EXCEEDED`, then `ERR_FLOOR_PLAN_FUNDING_REQUIRED`, then `ERR_GOODWILL_BUDGET_EXHAUSTED`. Because this band is last, a slot request that both exceeds line capacity and sits behind a credit hold reports the capacity failure at band 15.

One further consequence of the ladder is worth stating plainly: `ERR_LINE_CLASS_MISMATCH` (422) — raised when the chosen line's `chassis_class_supported` does not equal the floor plan's `chassis_class` — is a configuration incompatibility, not a temporal or fiscal one, and it is reported before the day-bucket capacity checks of band 15.

### 2.9. Cascade Discipline Across Aggregates

Several operations in this plant reach several rows deep, and every hop of every cascade is part of the contract rather than an implementation detail. Three cascades in particular must complete in full within the operation that triggers them, because the intermediate states are observable.

Opening or expanding a recall campaign quarantines matching component lots, which flips every `INSTALLED` installation of those lots to `RECALL_AFFECTED`, which raises `recall_hold` on each affected build, which — for a safety-severity campaign — sets `ship_hold_reason` to `RECALL_HOLD` on each held build's owning order, which in turn rescores the supplier. A daily-close expiry releases a slot, which returns the owning order from `SLOTTED` to `CONFIG_VALIDATED`, which returns that order's matched chassis from `MATCHED` to `RECEIVED`, which recomputes the dealer's allocation counters. A failed inspection past the rework limit scraps the build, which cancels the owning order and stamps `ship_hold_reason` as `QUALITY_HOLD`.

Every row touched by any hop of a cascade has its `version` incremented and its `updated_at` refreshed. Derived aggregates are recomputed rather than incrementally patched where the specification defines them as sums or counts: a dealer's `financed_exposure_cents`, `credit_utilization_bp`, `credit_status`, `goodwill_used_cents`, `entitlement_hours`, `allocation_hours_consumed`, and `allocation_slots_reserved` are all recomputed from their underlying rows whenever an operation could have moved them, and a supplier's `quality_score` and `supplier_status` are recomputed on every penalty event.

### 2.10. Enumerated Vocabularies

The system's enumerations are closed sets and the exact strings below are the contract. A value outside its set is a schema violation under band 3.

Chassis families are `CLASS_A`, `CLASS_C`, and `TOWABLE`. Supplier component categories are `CHASSIS`, `APPLIANCE`, `PLUMBING`, and `ELECTRICAL`, and a component lot's `category` draws from the same four. Option commercial categories are `APPLIANCE`, `PLUMBING`, `ELECTRICAL`, `EXTERIOR`, `INTERIOR`, and `CHASSIS_UPGRADE`. Assembly stations at which an option may be installed, and at which pieces may be recorded as installed, are `SIDEWALL_LAM`, `ROOF_SET`, `ROUGH_IN`, `APPLIANCE_INSTALL`, and `FINISH`. A build's position on the line ranges over the wider set `CHASSIS_PREP`, `SIDEWALL_LAM`, `ROOF_SET`, `ROUGH_IN`, `APPLIANCE_INSTALL`, `FINISH`, `WATER_TEST`, `PDI`, `READY_TO_SHIP`, `SHIPPED`, and `SCRAPPED`.

Dealer regions are `WEST`, `CENTRAL`, `EAST`, and `SOUTH`. Order types are `STOCK`, `SOLD`, and `DEMO`. Inspection types are `WATER_TEST`, `FUNCTIONAL`, and `PDI`; booth types are `WATER_TEST` and `FUNCTIONAL` only. Inspection grades are `PASS`, `CONDITIONAL`, and `FAIL`. Warranty claim types are `APPLIANCE`, `PLUMBING`, `ELECTRICAL`, `STRUCTURAL`, and `WATER_INTRUSION`; goodwill authority tiers are `TIER_A`, `TIER_B`, and `TIER_C`. Recall severities are `SAFETY`, `COMPLIANCE`, and `ADVISORY`. Shipment holds are `NONE`, `RECALL_HOLD`, and `QUALITY_HOLD`.

Lifecycle states are enumerated with their machines in Section 3, but for reference: a `UnitOrder` `status` is one of `DRAFT`, `CONFIG_VALIDATED`, `SLOTTED`, `IN_PRODUCTION`, `BUILT`, `SHIPPED`, `CANCELLED`, and its independent `financing_status` is one of `NOT_FINANCED`, `FUNDING_REQUESTED`, `FLOOR_PLAN_FUNDED`, `CURTAILED`, `PAID_OFF`. A `Supplier` `supplier_status` is `ACTIVE`, `PROBATION`, or `SUSPENDED`. A `Dealer` `credit_status` is `GOOD_STANDING`, `WATCH`, or `CREDIT_HOLD`, and its agreement `status` is `ACTIVE` or `SUSPENDED`. A `FloorPlan` `status` is `ACTIVE` or `RETIRED`; an `OptionItem` `status` is `ACTIVE` or `DISCONTINUED`; a `ProductionLine` `status` is `RUNNING` or `PAUSED`; a `TestBooth` `status` is `OPEN` or `DOWN`. A `ProductionSlot` `status` is `RESERVED`, `CONSUMED`, or `RELEASED`; a `ChassisReceipt` `status` is `RECEIVED`, `MATCHED`, or `INSTALLED`; a `ComponentLot` `status` is `AVAILABLE`, `DEPLETED`, or `QUARANTINED`; a `ComponentInstallation` `status` is `INSTALLED`, `REVERSED`, `RECALL_AFFECTED`, or `REMEDIED`; a `QualityInspection` `status` is `SCHEDULED` or `COMPLETED`; a `WarrantyClaim` `status` is `SUBMITTED`, `INFO_REQUESTED`, `APPROVED`, `DENIED`, or `PAID`; a `RecallCampaign` `status` is `DRAFT`, `OPEN`, or `CLOSED`.

### 2.11. Segregation of Duties Within a Role

Two checks in this plant are not about which role acts but about which *person* acts, and both compare `X-User-ID` against an identifier the system recorded earlier. Both are reported as `ERR_SEGREGATION_OF_DUTIES` (409).

The first governs pre-delivery inspection. When a `QualityInspector` completes a `PDI` inspection on a build, their `X-User-ID` must differ from the `completed_by_user_id` recorded on that build's most recently completed `WATER_TEST` inspection. The person who signed off the water test may not also sign off the coach's final walk-through.

The second governs warranty disbursement. When a `WarrantyAdministrator` pays an approved claim, their `X-User-ID` must differ from the claim's `approved_by_user_id`. The approver may not also pay.

Neither check consults the role — both parties are, by definition, holders of the same role — and neither is relaxed by any override.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Plant: Master Data, Dealers and Supply Intake

Everything in this system hangs off master data that a `PlantAdmin` registers. A **supplier** is registered with a `supplier_code` (unique across suppliers and between 3 and 16 characters), a legal `name`, and a non-empty `component_categories` array whose members are drawn from `CHASSIS`, `APPLIANCE`, `PLUMBING`, and `ELECTRICAL`. On registration a supplier's derived trust fields start clean: `quality_score` is `100.00`, `supplier_status` is `ACTIVE`, `open_recall_count` is 0, and `penalty_event_count` is 0. Those four fields are computed, never supplied; §3.9 explains how they move.

A **floor plan** is the model a dealer orders. It is published with a `model_code` unique across floor plans, a `chassis_class`, an overall coach `length_ft` between 18 and 45 inclusive, a `base_msrp_cents` greater than zero, a `base_station_hours` figure greater than zero carrying at most two decimals, a `base_dry_weight_lbs` greater than zero, a `gvwr_lbs` strictly greater than `base_dry_weight_lbs`, an exact `required_wheelbase_in` greater than zero, an `electrical_service_amps` rating of either 30 or 50, a `fresh_water_capacity_gal` greater than zero, and optionally a `status` that defaults to `ACTIVE`. The plant derives `max_payload_lbs` as the gross vehicle weight rating minus the base dry weight, and re-derives it whenever the plan is edited. A floor plan may later be repriced through `base_msrp_cents` or retired by setting `status` to `RETIRED`; either edit increments the plan's `version`, which invalidates the pinned reference on every already-submitted order that names it. Submitting an order against a `RETIRED` plan is rejected with `ERR_FLOOR_PLAN_RETIRED`.

An **option item** carries far more than a price. It is published with an `option_code` unique across options, a commercial `category` that selects its dealer discount rate, an `install_station` naming where on the line it goes, a `price_cents` of zero or more, an installed `weight_lbs` of zero or more, an `added_station_hours` figure of zero or more with at most two decimals, an `amp_draw` defaulting to 0, a `water_demand_gal` defaulting to 0, a `requires_option_codes` array defaulting to empty, an `excludes_option_codes` array defaulting to empty, and a `status` defaulting to `ACTIVE`. The two array fields are self-referential: they hold `option_code` values of other options, and they are the entire basis of the compatibility web that §3.2 resolves. Repricing `price_cents` or setting `status` to `DISCONTINUED` increments the option's `version`, invalidating the matching pinned entry on every already-submitted order that selected it.

A **dealer** is registered with a `dealer_code` unique across dealers, a freight `region`, an `allocation_share_bp` between 1 and 10000 expressing its share of plant monthly capacity in basis points, a `floor_plan_credit_limit_cents` greater than zero, a `goodwill_budget_cents` of zero or more representing its annual goodwill authority pool, and a `status` defaulting to `ACTIVE`. The identifier minted for the new dealer row *is* the `DealerPrincipal` identity that appears in `X-User-ID`. A dealer's derived position — `financed_exposure_cents`, `credit_utilization_bp`, `credit_status` (initialised to `GOOD_STANDING`), `goodwill_used_cents`, `entitlement_hours`, `allocation_hours_consumed`, and `allocation_slots_reserved` — is recomputed whenever the dealer record is read, so a read is always current. A `PlantAdmin` may later flip a dealer's `status` between `ACTIVE` and `SUSPENDED`; a `SUSPENDED` dealer can no longer submit orders, reserve slots, request funding, be released to a line, or receive a shipment, and each of those attempts is rejected with `ERR_DEALER_SUSPENDED`.

Capacity itself is master data. An **assembly line** is commissioned with a `line_code` unique across lines, the single `chassis_class_supported` it is tooled for, a `daily_station_hour_capacity` greater than zero with at most two decimals, and a `max_units_per_day` of at least 1, and it starts `RUNNING`. Commissioning a line moves every dealer's `entitlement_hours`, because the entitlement formula reads total plant capacity rather than a stored constant. A line may be paused and resumed by either a `PlantAdmin` or a `ProductionScheduler`; while `PAUSED` it blocks station advancement for every build occupying it with `ERR_LINE_NOT_RUNNING`, though slots already reserved on it keep their committed hours and continue to count toward capacity. A **test booth** is commissioned with a `booth_code` unique across booths, the single `booth_type` it serves, a `bay_count` of at least 1, and a `turnaround_minutes` buffer of zero or more that defaults to 30; it starts `OPEN`. A `PlantAdmin` may take a booth `DOWN`, after which new reservations are rejected with `ERR_BOOTH_NOT_OPEN` while already-`SCHEDULED` windows are left untouched.

Supply arrives in two forms. A **chassis receipt** records a bare chassis into the unmatched pool with a `supplier_id`, a `chassis_serial` unique across receipts, the `chassis_class` as received, a `gvwr_lbs` greater than zero, and a `wheelbase_in` greater than zero. The plant stamps `received_at` from the logical clock — this is the primary ranking key of the matching selector in §3.4 — sets `status` to `RECEIVED`, and leaves `matched_unit_order_id` null. A **component lot** records pieces with a `supplier_id`, a `part_number`, a `lot_code` unique within that supplier-and-part-number pair, a `category` that must be among its supplier's `component_categories`, and a `quantity_received` greater than zero. On receipt `quantity_available` equals `quantity_received`, `quantity_installed` is 0, `quantity_quarantined` is 0, and `status` is `AVAILABLE`. Those three counters are an invariant, not bookkeeping: available plus installed plus quarantined always equals `quantity_received`, and every operation in §3.5 and §3.9 that moves one moves another to preserve it. Uniqueness violations on any of the codes above, and a lot `category` outside its supplier's approved categories, are rejected with `ERR_INVALID_REQUEST`.

Chassis receipts and component lots are both listable with filters. Chassis receipts may be narrowed by `supplier_id`, `matched_unit_order_id`, `status`, and `chassis_class`; component lots by `supplier_id`, `part_number`, `lot_code`, and `status`.

Finally, a test-driving capability exists for instances whose subject is not the order-to-ship pipeline: a `PlantAdmin` may materialise a finished, delivered coach in one call by supplying a `dealer_id`, a `floor_plan_id`, and optionally a `shipped_at` instant. That call creates a `UnitOrder` of `order_type` `SOLD` with no options, `status` `SHIPPED`, `financing_status` `NOT_FINANCED`, and `shipped_at` set to the supplied instant or the current clock; a `ChassisReceipt` at `INSTALLED` against a synthetic supplier-less serial; and the returned `UnitBuild` standing at `SHIPPED` with `water_test_passed` and `pdi_passed` both true, `rework_count` 0, and `defect_points_total` 0.

### 3.2. Dealer Ordering: Configuration, Compatibility and Provisional Pricing

A `DealerPrincipal` opens a **unit order** by naming its own `dealer_id`, the `floor_plan_id` it wants built, an `order_type`, a `selected_option_ids` array of option identifiers (an ordered list; duplicates are rejected outright, and an empty array is a perfectly legal base unit), a `requested_delivery_date` expressed as a date at midnight UTC, and — for retail-sold coaches — an optional `customer_reference` that defaults to null. The new order begins with `status` `DRAFT` and `financing_status` `NOT_FINANCED`, and the configuration roll-up runs immediately. Nothing is *enforced* at creation, though: compatibility, weight, electrical, and water rules are all submit-time gates, so a `DRAFT` order may legally hold a configuration that could never be built. Orders are listable with filters on `dealer_id`, `floor_plan_id`, `status`, `financing_status`, and `order_type`, and a `DealerPrincipal` sees only its own rows.

The **configuration roll-up** derives seven figures from the floor plan baseline plus the selected option set, and it re-runs on creation, on configuration replacement, and again at submit. Five of them are exact integer aggregates. `option_price_total_cents` is the sum of `price_cents` across the selected options at list price. `config_weight_lbs` is the floor plan's `base_dry_weight_lbs` plus the sum of `weight_lbs` across the selected options. `payload_remaining_lbs` is the floor plan's `gvwr_lbs` minus `config_weight_lbs`. `total_amp_draw` is the sum of `amp_draw` across the selected options, and `total_water_demand_gal` is the sum of `water_demand_gal` across them.

`required_station_hours` — the sixth figure, and the one the whole scheduling system spends — is built in four movements. Begin with raw hours: the floor plan's `base_station_hours` plus the sum of `added_station_hours` across the selected options. Next choose a complexity factor from the *count* of selected options: four or fewer options (including none at all) gives 1.00; five through nine gives 1.05; ten through fourteen gives 1.12; fifteen or more gives 1.20. Then choose a class factor from the floor plan's `chassis_class`: a towable is 1.00, a Class C is 1.10, and a Class A is 1.15. Then determine the electrical surcharge: a configuration whose `total_amp_draw` is more than 40 amps adds a flat four hours of extra rough-in labour, and one at 40 amps or below adds nothing. Multiply raw hours by the complexity factor and by the class factor, add the surcharge, and round that single final result half up to two decimal places. The rounding happens once, at the end; rounding the intermediate product first is incorrect. A configuration whose `required_station_hours` comes out above 96.00 hours is more coach than the plant will build in one pass and is rejected at submit with `ERR_STATION_HOURS_LIMIT_EXCEEDED`.

The seventh figure is money, and §3.7 develops it fully; at submit the order's `provisional_invoice_cents` is written from the provisional variant of the invoice calculation, and `final_invoice_cents` stays null until the coach ships.

A dealer may **replace** the configuration of an order whose `status` is either `DRAFT` or `CONFIG_VALIDATED`, supplying a new `selected_option_ids` array and optionally a new `requested_delivery_date`. Replacement overwrites those two fields with the supplied values, re-runs the roll-up, and — when the order was `CONFIG_VALIDATED` — walks it back to `DRAFT`, clearing `locked_floor_plan_version`, emptying `locked_option_versions`, and resetting `provisional_invoice_cents` to 0. This is the revision cycle: `CONFIG_VALIDATED → DRAFT → CONFIG_VALIDATED`, traversable as many times as the dealer needs. Replacement attempted from any other status is rejected with `ERR_ORDER_NOT_SUBMITTABLE`.

**Submitting** the order is the moment the configuration becomes a commitment, moving `status` from `DRAFT` to `CONFIG_VALIDATED`. Submit takes no body. It requires the order to be `DRAFT` — a second submit of an already `CONFIG_VALIDATED` order is rejected with `ERR_ORDER_NOT_SUBMITTABLE` — requires the acting `X-User-ID` to be the order's dealer, requires the referenced floor plan's `status` to be `ACTIVE` and the dealer's `status` to be `ACTIVE`, and requires every selected option's `status` to be `ACTIVE`. It then walks the physical and commercial gates in the fixed order of §2.8: gross weight first, where `config_weight_lbs` may not exceed the floor plan's `gvwr_lbs`; then shore power, where `total_amp_draw` may not exceed the floor plan's `electrical_service_amps`; then the water system, where `total_water_demand_gal` may not exceed half of the floor plan's `fresh_water_capacity_gal` — the ceiling is 5000 basis points of tank capacity, rounded half up to a whole gallon, and plumbed options may claim at most that much; then the option-set consistency band.

Option-set consistency is where the self-referential option web is resolved, and its four sub-checks fire in a fixed sequence. A selected option that has been discontinued fails first with `ERR_OPTION_DISCONTINUED`. Then the **requires** relation is resolved transitively: if a selected option lists a companion `option_code` in its `requires_option_codes`, that companion must also be present in the selection, and so must anything *that* companion requires, and so on to closure — an unsatisfied closure at any depth is `ERR_OPTION_REQUIRES_MISSING`. Then the **excludes** relation is checked pairwise: if any selected option lists another selected option's `option_code` in its `excludes_option_codes`, the pair is illegal and the request fails with `ERR_OPTION_MUTUALLY_EXCLUSIVE`. Finally the station-hour ceiling applies as described above.

An order that clears all of it is stamped: the roll-up is recomputed, `provisional_invoice_cents` is written, `locked_floor_plan_version` is pinned to the floor plan's current `version`, and `locked_option_versions` is pinned as one entry per selected option carrying that option's identifier, its `version`, and its `price_cents` at the moment of submit. That pinned price is what the *final* invoice reprices from months later, so a mid-flight catalogue reprice never silently moves an already-committed invoice — it instead trips the drift detector of §3.4.

A dealer may **cancel** an order whose `status` is `DRAFT`, `CONFIG_VALIDATED`, or `SLOTTED`, optionally supplying a `cancel_reason`, driving `status` to `CANCELLED`. Cancellation from `SLOTTED` unwinds the commitments the order was holding: its `RESERVED` slot moves `RESERVED → RELEASED`, any chassis whose `matched_unit_order_id` names this order and whose `status` is `MATCHED` moves `MATCHED → RECEIVED` with `matched_unit_order_id` cleared, and the dealer's `allocation_slots_reserved` and `allocation_hours_consumed` are recomputed. Cancellation attempted from `IN_PRODUCTION`, `BUILT`, `SHIPPED`, or `CANCELLED` is rejected with `ERR_INVALID_STATE`.

### 3.3. Production Slots and the Monthly Allocation Ledger

A `ProductionScheduler` commits a validated order to the calendar by reserving a **production slot**, naming the `line_id` it should run on, the `slot_date` (a calendar day at midnight UTC) it should occupy, and the `expected_unit_order_version` demanded by §2.7. The order's identifier comes from the path and is never taken from the body; the created slot records it as `unit_order_id`. A successful reservation drives the order's `status` from `CONFIG_VALIDATED` to `SLOTTED`.

Reservation is permitted when the order's `status` is `CONFIG_VALIDATED` or already `SLOTTED` — any other status is `ERR_ORDER_NOT_SLOTTABLE`. Re-slotting an order that already holds a reservation is therefore legitimate, and the mechanics of it matter: **the order's prior `RESERVED` slot transitions `RESERVED → RELEASED` first, before the capacity checks run**, so the hours it was holding are freed and excluded from every count the new request is measured against. An order can hold at most one non-released slot at a time.

Beyond state, three gates apply. The line must be tooled for the coach: the line's `chassis_class_supported` must equal the floor plan's `chassis_class`, else `ERR_LINE_CLASS_MISMATCH`. The dealer must be in good order: its `status` must be `ACTIVE` and its `credit_status` must not be `CREDIT_HOLD`, and no order belonging to that dealer may be sitting `CURTAILED` with a positive `curtailment_due_cents` — those two fiscal failures are `ERR_DEALER_CREDIT_HOLD` and `ERR_DEALER_CURTAILMENT_DELINQUENT` respectively. And two capacity ceilings must admit the order's `required_station_hours`.

The **line-day ceiling** looks at one calendar-day bucket on one line. Day buckets never overlap; a slot occupies a whole day keyed by `slot_date`, not an instant range. Gather every slot on that line and that date whose `status` is `RESERVED` or `CONSUMED`, excluding the slot this same request just released, and take two numbers from them: the count of such slots, and the sum of their `station_hours_committed`. The unit ceiling is checked first — if the count plus one would exceed the line's `max_units_per_day`, the request fails with `ERR_LINE_DAY_UNIT_CAP_EXCEEDED`. Only then is the hours ceiling checked — if the summed committed hours plus this order's `required_station_hours` would exceed the line's `daily_station_hour_capacity`, the request fails with `ERR_LINE_DAY_HOURS_EXCEEDED`. The hours ceiling is inclusive: a total landing exactly on the line's daily capacity is admitted, and one hundredth of an hour more is refused. Because the unit cap is evaluated first, a day already holding the maximum number of small units reports the unit cap even when hours to spare remain.

The **monthly entitlement ceiling** looks at the dealer's contractual share of the whole plant. Sum the `daily_station_hour_capacity` of every commissioned line whose `status` is `RUNNING` or `PAUSED` — a paused line still counts toward the plant's nominal capacity — multiply by twenty working days per month, and round half up to two decimals: that is the plant's monthly hours. Multiply that by the dealer's `allocation_share_bp` and divide by 10000, rounding half up to two decimals: that is the dealer's `entitlement_hours`. Multiply the entitlement by 10500 basis points and divide by 10000, rounding half up to two decimals: that is the tolerance ceiling, which permits a five-percent oversubscription. Against that ceiling, sum the `station_hours_committed` of every slot belonging to this dealer's orders whose `status` is `RESERVED` or `CONSUMED` and whose `slot_date` falls in the same calendar month as the requested `slot_date`, again excluding the slot this request just released — that sum is the dealer's `allocation_hours_consumed` for the month. If that sum plus this order's `required_station_hours` exceeds the tolerance ceiling, the request fails with `ERR_DEALER_ALLOCATION_EXCEEDED`; landing exactly on the ceiling is admitted. Because the entitlement is derived from live line capacity rather than stored, commissioning a second line grants every dealer headroom it did not previously have.

The created slot is stamped `RESERVED` with `station_hours_committed` copied from the order's `required_station_hours` at the moment of reservation, a one-based `sequence_position` equal to the day bucket's occupied-unit count plus one (which is the coach's build order on that line that day), and an `expires_at` exactly 72 hours after the slot's `created_at`. The dealer's `allocation_slots_reserved` — the count of that dealer's slots in `RESERVED` or `CONSUMED` — and `allocation_hours_consumed` are recomputed, and the order's `version` increments. Slots are listable with filters on `line_id`, `unit_order_id`, `slot_date`, and `status`.

A reservation is a soft hold with a 72-hour fuse. Three things extinguish it, all landing on the same `RESERVED → RELEASED` transition: the daily-close expiry sweep, which releases any reserved slot whose `expires_at` is at or before the current clock; order cancellation; and supersession by a fresh reservation on the same order. In every case the released hours stop counting toward both the line-day and the monthly ceilings, and the dealer's allocation counters are recomputed. When the release comes from the expiry sweep and it leaves the order with no slot in `RESERVED` or `CONSUMED`, the cascade continues: the order falls back `SLOTTED → CONFIG_VALIDATED` and loses its slot association, and any chassis whose `matched_unit_order_id` names that order and whose `status` is `MATCHED` falls back `MATCHED → RECEIVED` with `matched_unit_order_id` cleared, re-entering the candidate pool for other orders. A slot that has already been consumed by a build is never released.

### 3.4. Chassis Matching and Release to the Line

Before a coach can start down the line it needs a chassis, and the plant does not let the scheduler pick one. Chassis assignment is a **selector policy**: the scheduler asks for a match against a specific order and the system determines the winner deterministically.

Eligibility is a six-part filter, and every part must hold. The candidate's `status` must be `RECEIVED`. Its `matched_unit_order_id` must be null. Its `chassis_class` must equal the floor plan's `chassis_class`. Its `wheelbase_in` must equal the floor plan's `required_wheelbase_in` exactly — a floor plan mounts on one wheelbase and no other, so near misses are not near. Its `gvwr_lbs` must be at least the order's `config_weight_lbs` plus a 500-pound safety margin. And the supplier that shipped it must have a `supplier_status` of `ACTIVE` or `PROBATION`; a `SUSPENDED` supplier's chassis is excluded from matching entirely, which is the sharpest consequence of the trust score in §3.9.

Among the eligible candidates the winner is chosen by three ordered keys. Oldest inventory goes first, so the earliest `received_at` wins. Where two candidates share the same `received_at`, the smaller `gvwr_lbs` wins — the plant does not waste a heavy chassis on a light coach. Where they still tie, the earlier `created_at` wins. The row identifier is never used as a tiebreak. When the eligible set is empty the request is rejected with `ERR_NO_MATCHING_CHASSIS`.

Matching is available while the order's `status` is `CONFIG_VALIDATED` or `SLOTTED`, and only when no other chassis already names this order in its `matched_unit_order_id`; an order that already holds a matched or installed chassis is rejected with `ERR_ORDER_ALREADY_MATCHED`. Before selecting, the system re-checks that the order's pinned references still hold — if the floor plan's current `version` no longer equals `locked_floor_plan_version`, or if any entry of `locked_option_versions` no longer matches its option's current `version`, the request fails with `ERR_CONFIG_REFERENCE_STALE`, and the dealer must revise and resubmit. The winning chassis moves `RECEIVED → MATCHED` with `matched_unit_order_id` set to the order.

**Releasing to the line** is the handoff from paperwork to production, driving the order `SLOTTED → IN_PRODUCTION` and returning the newly created build. It takes no body and demands a great deal of alignment: the order must be `SLOTTED`; a chassis must exist whose `matched_unit_order_id` names this order and whose `status` is `MATCHED`, else `ERR_CHASSIS_NOT_MATCHED`; the order's slot must still be `RESERVED` rather than expired or released; the dealer's `status` must be `ACTIVE` and its `credit_status` must not be `CREDIT_HOLD`, and it must carry no delinquent curtailment; and the pinned floor-plan and option versions must still match, else `ERR_CONFIG_REFERENCE_STALE`.

Release creates the **unit build**, the shop-floor record of one physical coach. It records the order it serves as `unit_order_id` and the chassis it consumed as `chassis_receipt_id` — both taken from the operation's context, never from a body. It receives a `build_sequence` equal to the plant-wide build counter plus one, a one-based monotonic figure in build-creation order, and a `vin` formed from the floor plan's `model_code`, then a hyphen, then that `build_sequence` zero-padded to six digits. It stands at `current_station` `CHASSIS_PREP` with `actual_station_hours` `0.00`, `rework_count` 0, `defect_points_total` 0, `water_test_passed` false, `pdi_passed` false, and `recall_hold` false. In the same operation the slot moves `RESERVED → CONSUMED` and the chassis moves `MATCHED → INSTALLED`. Builds are listable with filters on `unit_order_id`, `chassis_receipt_id`, `current_station`, and `recall_hold`.

### 3.5. On the Line: Station Advancement and Component Installation

A `LineSupervisor` walks a build forward one station at a time by naming the `to_station` it is entering and the `station_hours_used` that the station just consumed. The forward path is fixed and singular: `CHASSIS_PREP → SIDEWALL_LAM → ROOF_SET → ROUGH_IN → APPLIANCE_INSTALL → FINISH → WATER_TEST → PDI → READY_TO_SHIP`. The supplied `to_station` must be the immediate successor of the build's `current_station`; anything else — skipping a station, naming the current one, moving backwards, or touching a build already at `SHIPPED` or `SCRAPPED` — is rejected with `ERR_STATION_SEQUENCE_VIOLATION`. Backward movement is never requested by a client; it happens only as a consequence of a failed inspection, as §3.6 describes.

Every advancement carries the same two ambient conditions. The line the build occupies — the line of the slot the build consumed — must have `status` `RUNNING`, else `ERR_LINE_NOT_RUNNING`. And the build's `recall_hold` must be false, else `ERR_RECALL_SHIP_STOP`; a coach containing a recalled part does not move. On success the reported `station_hours_used` is added to the build's `actual_station_hours`, which accumulates across the whole build including every rework loop, and which later becomes the overtime term of the final invoice.

Three advancements carry an extra precondition. Entering `WATER_TEST` from `FINISH` requires that the systems actually installed match what the order bought: for each of the categories `APPLIANCE` and `PLUMBING` that appears among the order's selected options, at least one installation on this build must be in `status` `INSTALLED` drawing from a component lot of that same category. Entering `PDI` from `WATER_TEST` requires the build's `water_test_passed` to be true, else `ERR_WATER_TEST_NOT_PASSED`. Entering `READY_TO_SHIP` from `PDI` requires `pdi_passed` to be true, else `ERR_PDI_NOT_PASSED`. Reaching `READY_TO_SHIP` is also the moment the paperwork catches up: the owning order moves `IN_PRODUCTION → BUILT` in the same operation.

**Component installation** is how lots become coaches. A `LineSupervisor` records an installation by naming the `unit_build_id` receiving the pieces, the `component_lot_id` they came from, the `station` at which they went in, and a `quantity` of at least one. A lot under recall quarantine cannot be installed and is refused with `ERR_LOT_QUARANTINED`; a `quantity` above the lot's `quantity_available` is refused with `ERR_LOT_QUANTITY_INSUFFICIENT`. On success the lot's `quantity_available` decreases by the installed quantity and its `quantity_installed` increases by the same amount, conserving the piece total, and a lot whose `quantity_available` reaches exactly zero moves `AVAILABLE → DEPLETED`. The new installation starts at `status` `INSTALLED` with `recall_campaign_id` null. Installations are listable with filters on `unit_build_id`, `component_lot_id`, `recall_campaign_id`, and `status`.

Installations can be undone. A `LineSupervisor` **reverses** an installation whose `status` is `INSTALLED`, optionally recording a `reversal_reason`, provided the build is not already at `SHIPPED` or `SCRAPPED`. Reversal moves the installation `INSTALLED → REVERSED` and gives the pieces back: the lot's `quantity_installed` decreases by the installation's quantity and its `quantity_available` increases by the same amount, and a lot that had been `DEPLETED` returns `DEPLETED → AVAILABLE` once its `quantity_available` is above zero. Reversal is the compensating action for an install and it preserves the three-counter invariant exactly. Note that a lot's `quantity_installed` counts pieces held by installations in `INSTALLED`, `RECALL_AFFECTED`, or `REMEDIED` — a recall re-labels an installation without returning its pieces, so only reversal moves them back.

### 3.6. Quality Gates: Booth Windows, Grading, Rework and Scrap

Every coach faces a water test and a pre-delivery inspection, and may face functional tests along the way. A `QualityInspector` **schedules** an inspection by naming the `unit_build_id` and the `inspection_type`. A `WATER_TEST` or `FUNCTIONAL` inspection consumes a physical bay and therefore requires a `test_booth_id`, a `window_start`, and a `window_end`; a `PDI` inspection happens at the coach and requires all three to be omitted. Supplying the wrong combination — a booth for a `PDI`, or no booth for a wet or functional test — is `ERR_INVALID_REQUEST`, as is naming a booth whose `booth_type` does not equal the requested `inspection_type`. The scheduled inspection records `inspector_user_id` from the acting `X-User-ID`, starts at `status` `SCHEDULED` with `result` null, `defect_points` 0, `leak_detected` false, and `completed_by_user_id` null. Inspections are listable with filters on `unit_build_id`, `test_booth_id`, `inspection_type`, `status`, and `result`.

Booth windows are half-open instant intervals with a mandatory trailing buffer. The requested window must have a `window_end` strictly after its `window_start`, and its length must be at least 30 and at most 240 whole minutes. The booth cannot be `DOWN`. The **effective footprint** of any reservation runs from its `window_start` inclusive to its `window_end` plus the booth's `turnaround_minutes` exclusive — the dry-out period after a water test is as much an occupancy as the test itself. Two reservations conflict when each one's start falls strictly before the other one's effective end. Count every existing inspection on that booth whose `status` is `SCHEDULED` or `COMPLETED` that conflicts with the request; if that count plus one would exceed the booth's `bay_count`, the reservation is rejected with `ERR_BOOTH_WINDOW_CONFLICT`. Because the right edge is exclusive, a window starting exactly at a predecessor's buffered end is admitted, while one starting a single minute earlier is not; a two-bay booth admits that earlier window and refuses only a third overlapping one.

**Completing** an inspection moves it `SCHEDULED → COMPLETED` and is where the quality system reaches into the build. The inspector supplies `defect_points` (an integer of zero or more) and `leak_detected` (a boolean). The build must be standing at the right station: a `WATER_TEST` inspection requires `current_station` to be `WATER_TEST`, a `PDI` inspection requires `current_station` to be `PDI`, and a `FUNCTIONAL` inspection is accepted while the build stands at either `WATER_TEST` or `PDI`. A mismatch is rejected with `ERR_INSPECTION_STATION_MISMATCH`. Completing a `PDI` also carries the duty split of §2.11, rejected with `ERR_SEGREGATION_OF_DUTIES`.

The grade is computed, not supplied. Any water intrusion is decisive: if `leak_detected` is true the `result` is `FAIL` regardless of how few defect points were recorded — zero points with a leak still fails. Absent a leak, the grade comes from thresholds that differ by inspection type. For a `WATER_TEST` or `FUNCTIONAL` inspection, more than 12 defect points is `FAIL`, 6 through 12 points is `CONDITIONAL`, and fewer than 6 points is `PASS` — so 12 points is still conditional and 13 points fails. For a `PDI`, where the coach is about to leave the plant, the bands tighten: more than 8 points is `FAIL`, 4 through 8 points is `CONDITIONAL`, and fewer than 4 points is `PASS`.

Completion always does two things regardless of grade: it stamps `completed_by_user_id` from the acting `X-User-ID`, and it adds the recorded `defect_points` to the build's `defect_points_total`, which accumulates over every completed inspection and later becomes a credit against the coach's invoice. Beyond that, the side effects fork three ways with equal force.

A `PASS` or `CONDITIONAL` on a `WATER_TEST` sets the build's `water_test_passed` to true and leaves `current_station` where it is — a conditional pass is a pass, and the coach proceeds. A `PASS` or `CONDITIONAL` on a `PDI` sets `pdi_passed` to true and likewise leaves the station unchanged. A grade of any kind on a `FUNCTIONAL` inspection moves only `defect_points_total`: it sets neither flag and never moves the station.

A `FAIL` sends the coach backwards, and how far back depends on where it failed. A failed `WATER_TEST` increments `rework_count` by one, clears `water_test_passed` back to false, and moves the build `WATER_TEST → ROUGH_IN`, re-opening the rework cycle `WATER_TEST → ROUGH_IN → APPLIANCE_INSTALL → FINISH → WATER_TEST`. A failed `PDI` increments `rework_count` by one, clears `pdi_passed` back to false, and moves the build `PDI → FINISH`. Either rework is permitted only while the incremented `rework_count` would remain at 2 or below — that is, a build may be reworked twice.

The third failure is terminal. When a build already carrying a `rework_count` of 2 fails again, the rework limit is exhausted: `rework_count` still increments, but instead of moving backwards the build moves `WATER_TEST → SCRAPPED` or `PDI → SCRAPPED` according to where it stood, and the cascade continues into the paperwork — the owning order moves `IN_PRODUCTION → CANCELLED` and its `ship_hold_reason` is stamped `QUALITY_HOLD`. Both the build and the order are terminal at that point, and any later attempt to ship that order is refused with `ERR_QUALITY_HOLD`.

### 3.7. Shipment, the Final Invoice, and Floor-Plan Financing

Money enters a unit's life twice, and the same calculation produces both figures under two variants that differ only in which after-the-fact adjustments exist.

The **discount-and-freight core** is common to both. Build a set of discount lines: line zero is the base unit at the floor plan's `base_msrp_cents`, and then one line per selected option at that option's `price_cents`, taken in ascending `option_code` order. Each line carries its own discount rate in basis points. The base unit's rate comes from the order's `order_type`: a `STOCK` order discounts 2200 basis points, a `SOLD` order 2050, and a `DEMO` order 2600. Each option's rate comes from its `category`: `APPLIANCE` discounts 1550 basis points, `PLUMBING` 1450, `ELECTRICAL` 1725, `EXTERIOR` 1600, `INTERIOR` 1350, and `CHASSIS_UPGRADE` 1250. Now discount each line **independently**: multiply the line's gross amount by 10000 minus its rate, divide by 10000, and round that line half up to whole cents. Sum the rounded line amounts to obtain the discounted subtotal. Do not sum the raw products and round once — the per-line rounding boundary is part of the contract and the two approaches disagree by a few cents on a real configuration.

Freight is never discounted. It is a base of 180000 cents, plus 4200 cents for each foot of the floor plan's `length_ft`, plus a regional surcharge drawn from the dealer's `region`: 95000 cents for `WEST`, nothing for `CENTRAL`, 60000 cents for `EAST`, and 35000 cents for `SOUTH`.

Under the **provisional variant**, computed at submit, no build exists yet, so the three build-derived adjustments are all zero and `provisional_invoice_cents` is simply the discounted subtotal plus freight. That figure is the basis of floor-plan financing.

Under the **final variant**, computed at shipment from the finished build, three adjustments apply. Overtime is the excess of the build's `actual_station_hours` over the order's `required_station_hours`, or zero when the coach came in on or under plan; that excess in hours is multiplied by 8500 cents per hour and rounded half up to whole cents. Rework is a flat 45000 cents for each unit of the build's `rework_count`. The quality credit is 1500 cents for each point of the build's `defect_points_total`, capped at 90000 cents. `final_invoice_cents` is then the discounted subtotal plus freight plus the overtime surcharge plus the rework surcharge, minus the quality credit. The final variant reprices the option lines from the `price_cents` values pinned in `locked_option_versions` at submit, not from the catalogue's current prices. Notably, `financed_principal_cents` is *not* recomputed at shipment, so the gap between the provisional and final invoices is exactly the dealer's cash settlement.

**Shipping** a coach moves the order `BUILT → SHIPPED` and takes no body. It is the most heavily gated operation in the system. The order must be `BUILT` and its `ship_hold_reason` must be `NONE`. The build's `recall_hold` must be false, and both `water_test_passed` and `pdi_passed` must be true — those safety checks fire in the order given in §2.8, so a coach that is both recall-held and PDI-incomplete reports `ERR_RECALL_SHIP_STOP`. The dealer's `status` must be `ACTIVE` and its `credit_status` must not be `CREDIT_HOLD`. And the funding gate applies to inventory units only: a `STOCK` order may ship only when its `financing_status` is `FLOOR_PLAN_FUNDED`, else `ERR_FLOOR_PLAN_FUNDING_REQUIRED`; `SOLD` and `DEMO` orders carry no such requirement. On success `shipped_at` is stamped from the logical clock, `final_invoice_cents` is written from the final variant, and the build moves `READY_TO_SHIP → SHIPPED`. The `shipped_at` instant is also the start of the warranty period in §3.8.

**Floor-plan financing** runs on the order's second, independent state dimension. `financing_status` and `status` never gate each other except where a precondition explicitly says so — the funding gate on shipment and the status window on funding requests are the only two places they touch. A `DealerPrincipal` requests funding on its own order, driving `financing_status` `NOT_FINANCED → FUNDING_REQUESTED` while leaving `status` untouched; the request is admissible only while the order's `status` is `CONFIG_VALIDATED`, `SLOTTED`, `IN_PRODUCTION`, or `BUILT`, and only while the dealer's `status` is `ACTIVE`.

A `PlantAdmin` then records a `decision` of either `APPROVED` or `DECLINED`, optionally with a `decline_reason`. An approval requires a positive `provisional_invoice_cents` and advances `financing_status` `FUNDING_REQUESTED → FLOOR_PLAN_FUNDED`: the plant advances 9000 basis points of the provisional invoice, so `financed_principal_cents` is the provisional invoice multiplied by 9000, divided by 10000, and rounded half up to whole cents, and `funded_at` is stamped from the logical clock. A decline returns `financing_status` `FUNDING_REQUESTED → NOT_FINANCED`. Either way the dealer's credit position is recomputed.

**Credit standing** is derived, not stored. A dealer's `financed_exposure_cents` is the sum, across every one of its orders whose `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`, of that order's `financed_principal_cents` minus its `curtailment_paid_cents`. Its `credit_utilization_bp` is that exposure multiplied by 10000 and divided by its `floor_plan_credit_limit_cents`, truncated toward zero to a whole number of basis points — and zero when the credit limit is zero. Its `credit_status` follows from two strictly-greater-than comparisons: utilisation above 9500 basis points is `CREDIT_HOLD`, utilisation above 8000 basis points (but not above 9500) is `WATCH`, and anything at or below 8000 is `GOOD_STANDING`. Because both comparisons are strict, exactly 9500 basis points is `WATCH` and 9501 is `CREDIT_HOLD`.

**Curtailment** is the principal reduction a dealer owes as a funded coach ages on its lot, on a step schedule keyed to whole days since `funded_at`. At 365 days or more the cumulative requirement is 5000 basis points of `financed_principal_cents`; at 270 days or more but under 365 it is 2500 basis points; at 180 days or more but under 270 it is 1000 basis points; and below 180 days nothing is required. Each boundary is inclusive — a coach exactly 180 days old already owes the first stage. The required amount is the principal multiplied by that basis-point figure, divided by 10000, rounded half up to whole cents; and `curtailment_due_cents` is that required amount minus whatever `curtailment_paid_cents` has already been paid, floored at zero. The curtailment sweep inside the daily close moves any `FLOOR_PLAN_FUNDED` order with a positive due amount to `FLOOR_PLAN_FUNDED → CURTAILED`, persisting the recomputed figure.

A `DealerPrincipal` pays down principal on its own order by supplying an `amount_cents`. Payment is accepted while `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`. The amount must be greater than zero and no greater than the remaining principal — that is, no greater than `financed_principal_cents` minus `curtailment_paid_cents` — and an amount above that remainder is rejected with `ERR_PAYMENT_EXCEEDS_PRINCIPAL`. A payment that leaves the paid total short of the full principal adds `amount_cents` to `curtailment_paid_cents` and recomputes `curtailment_due_cents`; if the order was `CURTAILED` and the recomputed amount due reaches zero, it returns `CURTAILED → FLOOR_PLAN_FUNDED`, where a later sweep may curtail it again — this is a genuine cycle, not a one-way door. A payment that brings the paid total to exactly the full `financed_principal_cents` retires the advance: `curtailment_paid_cents` becomes the full principal, `curtailment_due_cents` becomes zero, and `financing_status` moves to the terminal `PAID_OFF` from either `FLOOR_PLAN_FUNDED` or `CURTAILED`, removing the unit from the dealer's exposure set. Every payment recomputes the dealer's `financed_exposure_cents`, `credit_utilization_bp`, and `credit_status`.

Reading a single order recomputes its `curtailment_due_cents` at the current logical clock, so a read after a clock advance shows the obligation even before the next daily close has moved the `financing_status`.

### 3.8. Warranty Adjudication, Goodwill and Supplier Chargeback

A `DealerPrincipal` files a **warranty claim** against a delivered coach by naming the `unit_build_id`, a `claim_type` selecting the flat-rate labour schedule, the `labor_hours` claimed (greater than zero, at most two decimals), the `parts_cost_cents` the dealer paid before handling uplift (zero or more), a failure `narrative`, and optionally the `component_lot_id` of the failed part's lot and a `goodwill_requested_cents` amount defaulting to zero. The claim's `dealer_id` is taken from the submitting principal's `X-User-ID` and never from the body; filing against a build belonging to another dealer is `ERR_DEALER_SCOPE_VIOLATION`. The claim starts at `status` `SUBMITTED` with `denial_reason` null, `info_request_count` 0, `resubmission_count` 0, and both `approved_by_user_id` and `paid_by_user_id` null. Claims are listable with filters on `dealer_id`, `unit_build_id`, `component_lot_id`, `status`, and `claim_type`.

Warranty coverage runs 365 days from the `shipped_at` of the order that owns the claimed build. At filing, `in_warranty` is set true when the logical clock is within that period of `shipped_at` and false otherwise, and that single boolean selects which of the two reimbursement variants governs the payout.

The **reimbursement waterfall** is seven steps that must execute in the written order, because two of its ceilings read values produced by earlier steps.

1. Labour is capped in hours *before* it is priced. The billable hours are the lesser of the claimed `labor_hours` and 8.0 hours. Multiply the billable hours by the flat rate for the claim's `claim_type` — 7800 cents per hour for `APPLIANCE`, 8600 for `PLUMBING`, 9200 for `ELECTRICAL`, 10400 for `STRUCTURAL`, and 11000 for `WATER_INTRUSION` — and round half up to whole cents. That is `labor_reimbursement_cents`.
2. Parts carry a handling uplift of 1500 basis points. Multiply `parts_cost_cents` by 11500, divide by 10000, and round half up to whole cents. That is `parts_reimbursement_cents`.
3. The schedule subtotal is `labor_reimbursement_cents` plus `parts_reimbursement_cents`.
4. The `authority_tier` is chosen **from** that subtotal, so it can never be settled before labour and parts are known: a subtotal at or below 150000 cents is `TIER_A`, a subtotal above that but at or below 750000 cents is `TIER_B`, and anything above 750000 cents is `TIER_C`.
5. Goodwill is throttled by independent ceilings and the authorised amount is the smallest of them. The candidates are the dealer's `goodwill_requested_cents`; the tier ceiling, which is 75000 cents for `TIER_A`, 150000 cents for `TIER_B`, and zero for `TIER_C` — the largest claims carry no goodwill authority at all; the percentage ceiling, which is 2000 basis points of the step-3 subtotal, computed by multiplying the subtotal by 2000, dividing by 10000, and rounding half up to whole cents; and the dealer's remaining budget, which is its `goodwill_budget_cents` minus its `goodwill_used_cents`. Out-of-warranty claims add a fourth ceiling of 50000 cents. The smallest candidate becomes `goodwill_authorized_cents`.
6. The total paid to the dealer is the schedule subtotal plus `goodwill_authorized_cents` — under the in-warranty variant. Under the out-of-warranty variant the subtotal is computed and recorded for the record but is **not** paid, so `total_reimbursement_cents` is `goodwill_authorized_cents` alone. The tier is still derived from the unpaid subtotal, so tier selection is identical across the two variants even though the payout differs.
7. The supplier chargeback is a percentage **of** the step-6 total, scaled by how much the plant currently trusts the supplier. When `component_lot_id` is null there is no supplier to charge and `supplier_chargeback_cents` is zero. Otherwise take the `supplier_status` of the lot's supplier and apply its rate to the total: 6000 basis points for `ACTIVE`, 8000 for `PROBATION`, and 10000 for `SUSPENDED`. Multiply, divide by 10000, and round half up to whole cents.

Filing a claim previews steps 1 through 4 and step 7's structure, writing `labor_reimbursement_cents` and `parts_reimbursement_cents`; `goodwill_authorized_cents`, `total_reimbursement_cents`, and `supplier_chargeback_cents` all stay at zero until a decision is made.

A `WarrantyAdministrator` may send a claim back for more information, driving `status` `SUBMITTED → INFO_REQUESTED` and optionally recording an `info_request_note`. Each such action increments `info_request_count`, and the plant allows at most two: a third request against the same claim is refused with `ERR_INFO_REQUEST_LIMIT_REACHED`. The owning dealer answers by resubmitting, driving `status` `INFO_REQUESTED → SUBMITTED`, optionally supplying revised `labor_hours`, `parts_cost_cents`, and `narrative` — any supplied value replaces the stored one, any omitted value stands. Resubmission increments `resubmission_count` and recomputes steps 1 through 4 and the chargeback structure, with goodwill still held at zero until decision. This is the revision cycle `SUBMITTED → INFO_REQUESTED → SUBMITTED`, bounded by the two-request limit. Requesting information, resubmitting, or deciding from a status that does not allow it is refused with `ERR_CLAIM_NOT_DECIDABLE`.

Deciding a claim requires a `decision` of `APPROVED` or `DENIED` and takes an optional `denial_reason` that becomes mandatory on denial. An approval is blocked when goodwill is requested and the dealer's remaining goodwill budget is zero, which is `ERR_GOODWILL_BUDGET_EXHAUSTED`; a claim requesting no goodwill still approves against an exhausted budget. Approval drives `status` `SUBMITTED → APPROVED`, runs all seven waterfall steps in the pinned order and persists `labor_reimbursement_cents`, `parts_reimbursement_cents`, `authority_tier`, `goodwill_authorized_cents`, `total_reimbursement_cents`, and `supplier_chargeback_cents`, stamps `approved_by_user_id` from the acting `X-User-ID`, and adds the authorised goodwill to the dealer's `goodwill_used_cents`. When the resulting `supplier_chargeback_cents` is positive, the claim itself becomes a penalty event against the lot's supplier: that supplier's `penalty_event_count` increases by one and its `quality_score` and `supplier_status` are recomputed. Denial drives `status` `SUBMITTED → DENIED` with `goodwill_authorized_cents` and `total_reimbursement_cents` both zeroed.

Payment is the last step and the second duty split. A `WarrantyAdministrator` pays a claim whose `status` is `APPROVED`, driving it `APPROVED → PAID` and stamping `paid_by_user_id` from the acting `X-User-ID`, which must differ from `approved_by_user_id`.

### 3.9. Recall Campaigns and the Supplier Trust Score

A `RecallCoordinator` drafts a **recall campaign** against a supplier's part by naming the `supplier_id`, a `campaign_code` unique across campaigns, the recalled `part_number`, a non-empty `lot_codes` array scoping which of that part's lots are affected, and a `severity`. The campaign starts at `status` `DRAFT` with `opened_at` null, all three counters — `affected_installation_count`, `remedied_installation_count`, and `quarantined_piece_count` — at zero, and `ship_stop` derived from severity: it is true exactly when `severity` is `SAFETY` and false for `COMPLIANCE` and `ADVISORY`. Nothing is quarantined while the campaign is a draft. Campaigns are listable with filters on `supplier_id`, `part_number`, `severity`, and `status`.

**Opening** the campaign drives `status` `DRAFT → OPEN` and fires the plant's deepest cascade. It requires at least one component lot to be in scope — matching means the lot's `supplier_id` equals the campaign's, the lot's `part_number` equals the campaign's, and the lot's `lot_code` is one of the campaign's `lot_codes`. Opening stamps `opened_at` from the logical clock, which is also the penalty-event timestamp for supplier scoring, and then runs four hops.

Hop one freezes supply. Every matching lot moves to `QUARANTINED` — from `AVAILABLE` or from `DEPLETED` alike — by adding its remaining `quantity_available` to its `quantity_quarantined` and then setting `quantity_available` to zero. A depleted lot has nothing left to freeze, so it changes state without moving pieces. The frozen piece count is added to the campaign's `quarantined_piece_count`.

Hop two labels the coaches. Every installation drawing from those lots whose `status` is `INSTALLED` moves `INSTALLED → RECALL_AFFECTED`, records the campaign as its `recall_campaign_id`, and increments the campaign's `affected_installation_count`. Each such labelling sets `recall_hold` to true on the build that received the pieces, which immediately blocks that build from advancing another station.

Hop three stops shipment, but only for safety campaigns. For every held build not already `SHIPPED`, when the campaign's `ship_stop` is true the owning order's `ship_hold_reason` becomes `RECALL_HOLD`. A `COMPLIANCE` or `ADVISORY` campaign holds the build without stamping the order.

Hop four rescores the supplier. Its `open_recall_count` increases by one, its `penalty_event_count` increases by one, and its `quality_score` and `supplier_status` are recomputed — which can drop it to `PROBATION` or `SUSPENDED` and thereby, in one stroke, remove its chassis from the matching pool of §3.4 and raise the chargeback rate applied to its warranty claims in §3.8.

An open campaign's scope can grow. **Expanding** it keeps `status` at `OPEN` and requires an `additional_lot_codes` array containing at least one code not already present in `lot_codes`, alongside the `expected_recall_campaign_version` demanded by §2.7. The campaign's `lot_codes` becomes the union of the old scope and the additional codes, and hops one through three run again for lots newly brought into scope only. Hop four does **not** run again: `open_recall_count` is not incremented a second time and no second penalty event is recorded, so expanding a campaign never double-punishes the supplier.

**Closing** a campaign drives `status` `OPEN → CLOSED` and requires that `remedied_installation_count` equal `affected_installation_count` — an unfinished campaign is refused with `ERR_CAMPAIGN_NOT_CLOSEABLE`. Closing decrements the supplier's `open_recall_count` by one and rescores it, but the penalty event itself survives the close: a closed campaign still weighs on the trust score. Quarantined pieces are never returned to `quantity_available`; recalled stock stays frozen permanently.

Remedying is how the counters converge. A `RecallCoordinator` records that a `RECALL_AFFECTED` installation has been remedied, optionally with a `remedy_note`, while the labelling campaign is still `OPEN`, moving the installation `RECALL_AFFECTED → REMEDIED` and incrementing the campaign's `remedied_installation_count`. When that leaves no installation on the build still `RECALL_AFFECTED`, the build's `recall_hold` returns to false, and if the owning order's `ship_hold_reason` was `RECALL_HOLD` it is set back to `NONE` — releasing both the line and the yard.

The **supplier trust score** is a decayed penalty tally on a 0-to-100 scale, and it has two windowing variants. The event set is the same for both: every campaign of that supplier whose `status` is `OPEN` or `CLOSED` and whose `opened_at` is not null, weighted by severity at 15.0 for `SAFETY`, 10.0 for `COMPLIANCE`, and 4.0 for `ADVISORY`, timestamped at `opened_at`; plus every `APPROVED` or `PAID` warranty claim whose component lot belongs to that supplier and whose `supplier_chargeback_cents` is positive, weighted at 2.0 and timestamped at the claim's `created_at`. Each event's age is the whole days between its timestamp and the logical clock, discarding any fractional remainder.

Under the **rolling** variant there is a hard 90-day cutoff and no decay: the penalty is the sum of the weights of events whose age is strictly less than 90 days. An event whose age is exactly 90 days is outside the window and contributes nothing at all. Under the **lifetime** variant nothing is ever dropped: events younger than 90 days count at full weight, and events at or past 90 days keep half their weight, so the lifetime figure is at or below the rolling figure whenever any event has aged out. In both cases the score is 100.00 minus the penalty, floored at 0.00 and rounded half up to two decimal places.

`Supplier.quality_score` always holds the **rolling** figure, and `supplier_status` is derived from it alone: a score of 70.00 or more is `ACTIVE`, a score from 50.00 up to but not including 70.00 is `PROBATION`, and anything below 50.00 is `SUSPENDED`. The score is recomputed on every penalty event — campaign opening, expansion, and closing, and any claim decision that produces a positive chargeback — and again on every daily close.

A **supplier scorecard** read puts both variants side by side. It returns the `supplier_id`, the `rolling_quality_score`, the `lifetime_quality_score`, the current `supplier_status`, the `open_recall_count`, the `penalty_event_count`, and the `evaluated_at` instant at which the figures were computed. The read is not passive: it recomputes and persists the supplier's `quality_score` and `supplier_status` from the rolling variant at the current logical clock, so a scorecard read after a clock advance is what promotes a supplier whose old penalties have finally aged out of the window.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`; this includes registering master data, receiving supply, reserving a production slot, releasing a build to the line, recording a component installation, scheduling an inspection, filing a warranty claim, drafting a recall campaign, and the delivered-unit injection. Operations that modify an existing resource, drive a state transition, or read data return `200 OK`. Every path below is absolute; there is no shared URL prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/suppliers` | Register a component or chassis supplier | PlantAdmin |
| GET | `/suppliers/{id}` | Read one supplier | PlantAdmin, ProductionScheduler, WarrantyAdministrator, RecallCoordinator |
| GET | `/suppliers/{id}/scorecard` | Read both windowing variants of the supplier trust score | PlantAdmin, ProductionScheduler, WarrantyAdministrator, RecallCoordinator |
| POST | `/floor-plans` | Publish a floor plan that dealers may order | PlantAdmin |
| GET | `/floor-plans/{id}` | Read one floor plan | PlantAdmin, DealerPrincipal, ProductionScheduler |
| PATCH | `/floor-plans/{id}` | Reprice or retire a floor plan | PlantAdmin |
| POST | `/option-items` | Publish a dealer-orderable option | PlantAdmin |
| GET | `/option-items/{id}` | Read one option | PlantAdmin, DealerPrincipal, ProductionScheduler |
| PATCH | `/option-items/{id}` | Reprice or discontinue an option | PlantAdmin |
| POST | `/dealers` | Register a dealer with its capacity share, credit line and goodwill pool | PlantAdmin |
| GET | `/dealers/{id}` | Read one dealer including its derived credit and allocation position | PlantAdmin, DealerPrincipal, ProductionScheduler, WarrantyAdministrator |
| POST | `/dealers/{id}/status` | Suspend or reinstate a dealer agreement | PlantAdmin |
| POST | `/production-lines` | Commission an assembly line with its daily hour and unit ceilings | PlantAdmin |
| GET | `/production-lines/{id}` | Read one production line | PlantAdmin, ProductionScheduler, LineSupervisor |
| POST | `/production-lines/{id}/status` | Pause or resume a line | PlantAdmin, ProductionScheduler |
| POST | `/test-booths` | Commission a water-test or functional-test booth | PlantAdmin |
| GET | `/test-booths/{id}` | Read one test booth | PlantAdmin, QualityInspector |
| POST | `/test-booths/{id}/status` | Take a booth down or return it to service | PlantAdmin |
| POST | `/chassis-receipts` | Receive a chassis into the unmatched pool | PlantAdmin |
| GET | `/chassis-receipts/{id}` | Read one chassis receipt | PlantAdmin, ProductionScheduler |
| GET | `/chassis-receipts` | List chassis receipts | PlantAdmin, ProductionScheduler |
| POST | `/component-lots` | Receive a component lot from a supplier | PlantAdmin |
| GET | `/component-lots/{id}` | Read one component lot with its three piece counters | PlantAdmin, LineSupervisor, RecallCoordinator |
| GET | `/component-lots` | List component lots | PlantAdmin, LineSupervisor, RecallCoordinator |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlantAdmin |
| POST | `/daily-close` | Ops checkpoint: release expired slots and curtail aged advances | PlantAdmin |
| POST | `/_inject/delivered-unit` | Test-driving capability: materialise a shipped unit for a dealer | PlantAdmin |
| POST | `/unit-orders` | Open a dealer order against a floor plan and an option set | DealerPrincipal |
| GET | `/unit-orders/{id}` | Read one unit order with both state dimensions and all money fields | PlantAdmin, DealerPrincipal, ProductionScheduler, LineSupervisor, WarrantyAdministrator |
| GET | `/unit-orders` | List unit orders | PlantAdmin, DealerPrincipal, ProductionScheduler |
| PUT | `/unit-orders/{id}/configuration` | Replace the option set of a DRAFT or CONFIG_VALIDATED order | DealerPrincipal |
| POST | `/unit-orders/{id}/submit` | Validate the configuration, price it provisionally and pin the reference versions | DealerPrincipal |
| POST | `/unit-orders/{id}/cancel` | Cancel an order that has not yet reached BUILT | DealerPrincipal |
| POST | `/unit-orders/{id}/production-slots` | Reserve a production slot on a line for a calendar day | ProductionScheduler |
| GET | `/production-slots/{id}` | Read one production slot | PlantAdmin, ProductionScheduler |
| GET | `/production-slots` | List production slots | PlantAdmin, ProductionScheduler |
| POST | `/unit-orders/{id}/match-chassis` | Assign the winning chassis from the received pool to this order | ProductionScheduler |
| POST | `/unit-orders/{id}/release-to-line` | Start the build: consume the slot and chassis and open a unit build | ProductionScheduler |
| POST | `/unit-orders/{id}/ship` | Ship a completed unit and settle the final invoice | ProductionScheduler |
| POST | `/unit-orders/{id}/request-funding` | Ask the plant to floor-plan this unit | DealerPrincipal |
| POST | `/unit-orders/{id}/funding-decision` | Approve or decline a floor-plan funding request | PlantAdmin |
| POST | `/unit-orders/{id}/floor-plan-payment` | Pay down floor-plan principal | DealerPrincipal |
| GET | `/unit-builds/{id}` | Read one build with its station, hour, defect and hold state | PlantAdmin, ProductionScheduler, LineSupervisor, QualityInspector, WarrantyAdministrator |
| GET | `/unit-builds` | List builds | PlantAdmin, ProductionScheduler, LineSupervisor, QualityInspector |
| POST | `/unit-builds/{id}/advance` | Move a build to the next station, booking the hours consumed | LineSupervisor |
| POST | `/component-installations` | Install pieces from a component lot into a build at a station | LineSupervisor |
| GET | `/component-installations/{id}` | Read one installation | PlantAdmin, LineSupervisor, RecallCoordinator |
| GET | `/component-installations` | List installations | PlantAdmin, LineSupervisor, RecallCoordinator |
| POST | `/component-installations/{id}/reverse` | Undo an installation, returning the pieces to the lot | LineSupervisor |
| POST | `/component-installations/{id}/remedy` | Record that a recall-affected installation has been remedied | RecallCoordinator |
| POST | `/quality-inspections` | Schedule a water test, functional test or pre-delivery inspection | QualityInspector |
| GET | `/quality-inspections/{id}` | Read one inspection | PlantAdmin, QualityInspector, LineSupervisor |
| GET | `/quality-inspections` | List inspections | PlantAdmin, QualityInspector, LineSupervisor |
| POST | `/quality-inspections/{id}/complete` | Record findings and grade the inspection | QualityInspector |
| POST | `/warranty-claims` | File a warranty claim against a delivered unit | DealerPrincipal |
| GET | `/warranty-claims/{id}` | Read one claim with its full reimbursement breakdown | PlantAdmin, DealerPrincipal, WarrantyAdministrator |
| GET | `/warranty-claims` | List claims | PlantAdmin, DealerPrincipal, WarrantyAdministrator |
| POST | `/warranty-claims/{id}/request-info` | Send a claim back to the dealer for more information | WarrantyAdministrator |
| POST | `/warranty-claims/{id}/resubmit` | Answer an information request, optionally revising the claim | DealerPrincipal |
| POST | `/warranty-claims/{id}/decide` | Approve or deny a claim, fixing the payout and supplier chargeback | WarrantyAdministrator |
| POST | `/warranty-claims/{id}/pay` | Pay an approved claim | WarrantyAdministrator |
| POST | `/recall-campaigns` | Draft a recall campaign scoped to a supplier part number and lot codes | RecallCoordinator |
| GET | `/recall-campaigns/{id}` | Read one campaign with its affected and remedied counters | PlantAdmin, RecallCoordinator |
| GET | `/recall-campaigns` | List campaigns | PlantAdmin, RecallCoordinator |
| POST | `/recall-campaigns/{id}/open` | Open the campaign, firing the quarantine and hold cascade | RecallCoordinator |
| POST | `/recall-campaigns/{id}/expand` | Add lot codes to an open campaign, rerunning the cascade | RecallCoordinator |
| POST | `/recall-campaigns/{id}/close` | Close a fully remedied campaign | RecallCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_DEALER_SCOPE_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SUPPLIER_NOT_FOUND` | 404 |
| `ERR_FLOOR_PLAN_NOT_FOUND` | 404 |
| `ERR_OPTION_ITEM_NOT_FOUND` | 404 |
| `ERR_DEALER_NOT_FOUND` | 404 |
| `ERR_PRODUCTION_LINE_NOT_FOUND` | 404 |
| `ERR_TEST_BOOTH_NOT_FOUND` | 404 |
| `ERR_UNIT_ORDER_NOT_FOUND` | 404 |
| `ERR_PRODUCTION_SLOT_NOT_FOUND` | 404 |
| `ERR_CHASSIS_RECEIPT_NOT_FOUND` | 404 |
| `ERR_COMPONENT_LOT_NOT_FOUND` | 404 |
| `ERR_UNIT_BUILD_NOT_FOUND` | 404 |
| `ERR_COMPONENT_INSTALLATION_NOT_FOUND` | 404 |
| `ERR_QUALITY_INSPECTION_NOT_FOUND` | 404 |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 |
| `ERR_RECALL_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_NOT_SUBMITTABLE` | 409 |
| `ERR_ORDER_NOT_SLOTTABLE` | 409 |
| `ERR_ORDER_ALREADY_MATCHED` | 409 |
| `ERR_CHASSIS_NOT_MATCHED` | 409 |
| `ERR_DEALER_SUSPENDED` | 409 |
| `ERR_FLOOR_PLAN_RETIRED` | 409 |
| `ERR_STATION_SEQUENCE_VIOLATION` | 409 |
| `ERR_LINE_NOT_RUNNING` | 409 |
| `ERR_BOOTH_NOT_OPEN` | 409 |
| `ERR_INSPECTION_STATION_MISMATCH` | 409 |
| `ERR_LOT_QUANTITY_INSUFFICIENT` | 409 |
| `ERR_CLAIM_NOT_DECIDABLE` | 409 |
| `ERR_INFO_REQUEST_LIMIT_REACHED` | 409 |
| `ERR_CAMPAIGN_NOT_CLOSEABLE` | 409 |
| `ERR_PAYMENT_EXCEEDS_PRINCIPAL` | 409 |
| `ERR_STALE_UNIT_ORDER_VERSION` | 412 |
| `ERR_STALE_RECALL_CAMPAIGN_VERSION` | 412 |
| `ERR_RECALL_SHIP_STOP` | 409 |
| `ERR_WATER_TEST_NOT_PASSED` | 409 |
| `ERR_PDI_NOT_PASSED` | 409 |
| `ERR_QUALITY_HOLD` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_PAYLOAD_CAPACITY_EXCEEDED` | 422 |
| `ERR_ELECTRICAL_SERVICE_EXCEEDED` | 422 |
| `ERR_WATER_SYSTEM_CAPACITY_EXCEEDED` | 422 |
| `ERR_OPTION_DISCONTINUED` | 422 |
| `ERR_OPTION_REQUIRES_MISSING` | 422 |
| `ERR_OPTION_MUTUALLY_EXCLUSIVE` | 422 |
| `ERR_STATION_HOURS_LIMIT_EXCEEDED` | 422 |
| `ERR_CONFIG_REFERENCE_STALE` | 409 |
| `ERR_NO_MATCHING_CHASSIS` | 422 |
| `ERR_LOT_QUARANTINED` | 409 |
| `ERR_LINE_CLASS_MISMATCH` | 422 |
| `ERR_BOOTH_WINDOW_CONFLICT` | 409 |
| `ERR_LINE_DAY_UNIT_CAP_EXCEEDED` | 409 |
| `ERR_LINE_DAY_HOURS_EXCEEDED` | 409 |
| `ERR_DEALER_CREDIT_HOLD` | 422 |
| `ERR_DEALER_CURTAILMENT_DELINQUENT` | 422 |
| `ERR_DEALER_ALLOCATION_EXCEEDED` | 422 |
| `ERR_FLOOR_PLAN_FUNDING_REQUIRED` | 422 |
| `ERR_GOODWILL_BUDGET_EXHAUSTED` | 422 |
