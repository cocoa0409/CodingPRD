# Forest Nursery & Reforestation Contract API — Product Requirements Document

## 1. Introduction

Every reforestation contract the state signs begins years before a seedling touches a planting site. Seed must be collected from the right elevation band, sown into nursery beds on a species-specific calendar, lifted inside a narrow window, graded to separate plantable stock from culls, and held under cold-chain conditions until a crew is ready to plant it. This document specifies the API of the state forest nursery's contract-management system, the single system of record that coordinates that supply pipeline — seed zones, seed lots, crop batches, cold storage, and a shipment pipeline governed by a strict 72-hour handling window.

On the demand side, landowners place seedling orders subject to species-specific lead times, contract officers administer planting contracts with spacing specifications and independently verified herbicide site preparation, field auditors score survival and trigger replant obligations, and program administrators shepherd cost-share enrollments from documentation to disbursement. Four peer operator roles share the work with deliberately separated duties, and two automatic cascades keep orders, contracts, crews, and payments consistent whenever reality — a poor grade, a failed survey — diverges from the plan. All endpoints are mounted under the `/reforestation` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles: `NurseryManager` (the state nursery operator responsible for zones, lots, crop batches, cold storage, and dispatch), `ContractOfficer` (the reforestation contract administrator responsible for landowner registration, order confirmation, allocations, contracts, crews, and replant scheduling), `FieldAuditor` (the independent field verifier responsible for site-prep verification, survival surveys, and spoilage reports), `ProgramAdministrator` (the cost-share program authority responsible for enrollment review, approval, payment, and replant waivers), and `Landowner` (the external customer who places and amends their own seedling orders and enrolls in cost-share programs).

When `X-User-Role` is `Landowner`, `X-User-ID` is the `id` of the acting Landowner record, and it must resolve to an existing Landowner; ownership checks on any resource that references a landowner compare the resource's `landowner_id` field to `X-User-ID`, and a `Landowner` caller may touch only resources whose `landowner_id` matches. When `X-User-Role` is `NurseryManager`, `ContractOfficer`, `FieldAuditor`, or `ProgramAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

A request with missing headers, an undeclared role, or an unresolvable Landowner id is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized role list — or a `Landowner` reaching for another landowner's resource — is rejected with `ERR_UNAUTHORIZED` (HTTP 403). On list endpoints, the `Landowner` role always sees only its own records, whatever filters are supplied.


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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. Paginated list responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Change Tracking

Every resource in this system — landowners, seed zones, seed lots, crop batches, seedling orders, allocations, storage units, storage placements, planting contracts, crews, crew assignments, shipments, survival surveys, and cost-share enrollments — carries the same four system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource, including mutations the server applies automatically through cascades and reconciliation.

Because cascaded mutations (for example, an order demoted by a grading shortfall) are real mutations, they too refresh `updated_at` and advance `version` on the affected resource.

### 2.5. The Logical Clock

The server never reads the wall clock. All temporal rules in this document evaluate against a logical clock that, before any adjustment, reads exactly 2026-08-01T00:00:00Z — the server-startup default. Operators in the `NurseryManager`, `ContractOfficer`, `ProgramAdministrator`, or `FieldAuditor` roles may move the clock through the test-driving capability `POST /reforestation/_clock/set_current_utc`, supplying the target instant as `to_iso8601`; the response echoes the new logical time as `current_utc`. Lead times, herbicide age, the survey window, the handling deadline, cold-storage stock age, lift windows, planting windows, and replant scheduling are all judged against this logical clock — "the current date" anywhere below means the logical clock's date.

### 2.6. Validation Order and Error Precedence

Every request passes through a fixed pipeline of checks, and when several checks could reject the same request, the one earliest in this order fires. Resource references — path parameters and body foreign keys alike — are resolved left to right, so the first unresolvable reference determines the `ERR_NOT_FOUND` rejection.

1. Authentication: both headers present, the role declared, and an entity-backed `Landowner` id resolvable — otherwise `ERR_UNAUTHENTICATED` (401).
2. Authorization: the acting role appears in the endpoint's role list, and a `Landowner` caller owns the resource — otherwise `ERR_UNAUTHORIZED` (403).
3. Existence: path parameters and body references resolve to existing resources, validated left to right — otherwise `ERR_NOT_FOUND` (404).
4. Optimistic concurrency: a required `expected_…_version` field matches the parent entity's current `version` — otherwise `ERR_STALE_VERSION` (412).
5. State legality: the state machine's from-state permits the requested transition — otherwise `ERR_INVALID_STATE` (409).
6. Quarantine gate: the seed lot involved is not `QUARANTINED` when sowing, allocating, or shipping — otherwise `ERR_LOT_QUARANTINED` (422).
7. Site-prep verification gate: site prep is recorded and `VERIFIED` before readiness, and verification is performed by a `FieldAuditor` rather than the recording officer — otherwise `ERR_SITE_PREP_NOT_VERIFIED` (422).
8. Order lead time: the requested ship date satisfies the species lead time at order creation, confirmation, and amendment — otherwise `ERR_LEAD_TIME_INSUFFICIENT` (422).
9. Herbicide efficacy window at planting start — otherwise `ERR_SITE_PREP_WINDOW_INVALID` (422).
10. Survey window at survey creation — otherwise `ERR_SURVEY_WINDOW_INVALID` (422).
11. Shipment handling window at plant confirmation — otherwise `ERR_HANDLING_WINDOW_EXCEEDED` (422).
12. Cold-storage stock age at shipment creation — otherwise `ERR_STOCK_AGE_EXCEEDED` (422).
13. Lift window at lifting — otherwise `ERR_LIFT_WINDOW_INVALID` (422).
14. Seed-transfer rule: species match plus the elevation-band midpoint tolerance at allocation and shipment — otherwise `ERR_SPECIES_ZONE_MISMATCH` (422).
15. Crew overlap at assignment creation — otherwise `ERR_CREW_OVERLAP` (409).
16. Spacing specification at contract creation — otherwise `ERR_SPACING_SPEC_INVALID` (422).
17. Interval sanity: ends strictly after starts, window ends no earlier than window starts, elevation bounds ordered — otherwise `ERR_WINDOW_INVERTED` (400).
18. Request shape: required fields present and well-typed, enum values within their declared sets — otherwise `ERR_INVALID_REQUEST` (400).
19. Batch grading status for allocations and shipments — otherwise `ERR_BATCH_NOT_GRADED` (422).
20. Planting quantity floor at planting completion — otherwise `ERR_PLANTING_QUANTITY_SHORT` (422).
21. Allocation availability at allocation creation — otherwise `ERR_ALLOCATION_EXCEEDS_AVAILABLE` (422).
22. Shipment stock sufficiency at shipment creation — otherwise `ERR_INSUFFICIENT_STORED_STOCK` (422).
23. Placement plantable remainder at placement creation — otherwise `ERR_PLACEMENT_EXCEEDS_PLANTABLE` (422).
24. Storage capacity at placement creation — otherwise `ERR_STORAGE_CAPACITY_EXCEEDED` (422).
25. Crew capacity at assignment creation — otherwise `ERR_CREW_CAPACITY_EXCEEDED` (422).
26. Mark-ready allocation coverage — otherwise `ERR_ORDER_UNDER_ALLOCATED` (422).
27. Enrollment documented acreage at submit — otherwise `ERR_ENROLLMENT_ACRES_EXCEEDED` (422).
28. Cancellability of contracts and orders — otherwise `ERR_NOT_CANCELLABLE` (409).
29. Payment hold at disbursement — otherwise `ERR_PAYMENT_HELD` (422).

The detailed trigger condition of each rule is defined in §3 alongside the workflow it guards; the catalogue in §5 lists identifiers and status codes only.

### 2.7. Optimistic Concurrency Control on Lot and Order Writes

Exactly two write operations carry an optimistic-concurrency obligation; endpoints not named here accept no version field at all. Creating a crop batch requires `expected_seed_lot_version`, carrying the client-observed `version` of the seed lot the batch is planned against. If the lot's current `version` has advanced past the submitted value — a quarantine, a release, or another batch plan having been recorded since the client last read the lot — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the planner would otherwise size the sow from a stale view of the lot's `remaining_grams`. Amending a seedling order likewise requires `expected_seedling_order_version` matching the order's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since the amendment's quantity and pricing were computed against a particular observed order state.

Version advancement is visible and deterministic: recording a crop-batch plan advances the seed lot's `version` by one, as do quarantining and releasing a lot and recording a sow; a successful order amendment advances the order's `version` by one, as does creating an allocation against the order.

### 2.8. Seedling Counts and Cents: Precision and Rounding

Seedling counts are whole numbers. Whenever a computation produces a count, the result is an integer: `required_seedlings`, escalated replant quantities, and crew daily loads are rounded up (ceiling), while the yield projection `projected_plantable` is rounded down (floor). Monetary amounts are integer cents; discounted order totals and each cost-share award component are rounded half-up to a whole cent. Survival percentages are carried to exactly two decimal places, rounded half-up. Dates are ISO calendar dates (YYYY-MM-DD), and datetimes are ISO 8601 UTC instants; the handling deadline is computed at hour granularity, and cold-storage stock age at day granularity.

### 2.9. Whole-Chain Consistency: Cascades A and B

Two automatic cascades keep the supply chain and the contract chain mutually consistent, and both are fired by the server without any client request on the affected resources. CASCADE A runs when grading reveals that a batch's plantable stock cannot cover its reservations: allocations are released newest-first, their orders drop below full allocation and demote, and planting contracts fed by those orders lose their readiness. CASCADE B runs when a survival survey lands below threshold: the survey's embedded replant obligation opens, the contract's pending crew work is released, and the landowner's approved cost-share money is held until the obligation resolves. Each link of each cascade is a real mutation — it refreshes `updated_at` and advances `version` on every resource it touches, per §2.4. The full mechanics of both cascades are specified in §3.2, §3.3, §3.5, §3.6, and §3.7, each link stated beside the workflow that owns it.

## 3. Business Logic & Workflows

The workflows below follow the pipeline from seed to survival check: first the supply side (zones, lots, crop batches), then demand (orders and allocations), then storage and shipment, then planting and crews, then survival surveys and the replant cycle, and finally cost-share settlement.

### 3.1. Landowners, Seed Zones, and Seed Lots

A `ContractOfficer` registers each participating landowner with a `legal_name`, a primary `contact_email`, and the `tax_id` that will later appear on cost-share documentation. The `cost_share_eligible` flag records whether the landowner may enroll in cost-share programs and defaults to true when omitted. A registered landowner record can be read by a `ContractOfficer` or `ProgramAdministrator`; a caller in the `Landowner` role may read only the record whose `id` matches their own `X-User-ID`.

`NurseryManager` staff define the seed collection zones. Each zone carries a `zone_code` that must be unique across all zones and an elevation band bounded by `min_elevation_ft` and `max_elevation_ft`, both whole feet, where the lower bound must be at least zero and strictly below the upper bound — an unordered pair is rejected with `ERR_WINDOW_INVERTED`. From the two bounds the server derives `band_midpoint_ft`, the arithmetic midpoint of the band. That midpoint anchors the seed-transfer tolerance rule exercised later by allocations and shipments: stock may move between a source zone and a destination zone only when the two band midpoints differ by no more than 500 feet in absolute terms.

Collected seed is registered as lots. Registering a lot captures the `source_zone_id` of the zone where the seed was collected, the `species` — one of `DOUGLAS_FIR`, `LOBLOLLY_PINE`, or `WHITE_OAK` — the `collected_on` date, the total `quantity_grams` as a positive whole number of grams, and the latest laboratory `germination_pct`, a fraction greater than zero and at most one. The server maintains `remaining_grams` as the lot's original mass less the sown grams of every crop batch of that lot, whatever status those batches are in. Lots can be listed with optional `source_zone_id`, `species`, and `status` filters.

A new lot starts `AVAILABLE`. After a failed germination retest, a `NurseryManager` quarantines the lot (`AVAILABLE` → `QUARANTINED`); while a lot is `QUARANTINED`, every attempt to sow against it, to allocate stock grown from it, or to ship that stock is rejected with `ERR_LOT_QUARANTINED`. Release from quarantine requires a passing retest: the release carries `retest_germination_pct`, which must be greater than zero and at most one, overwrites the lot's `germination_pct`, and recomputes `projected_plantable` on every crop batch of the lot still in `PLANNED`. The quarantine-and-release cycle may repeat without limit, and each quarantine and each release advances the lot's `version`. Independently, whenever a successful sow debit brings `remaining_grams` to exactly zero, the lot moves automatically to `DEPLETED`, its terminal state.

### 3.2. Crop Batches: Sowing, Lifting, and Grading

Planning a crop batch is a `NurseryManager` action that names the `seed_lot_id` of the lot to sow, a `planned_sow_date`, and the lifting window as `lift_window_start` and `lift_window_end`; the window's end may equal its start but may not precede it (`ERR_WINDOW_INVERTED`). Because the planner sizes the batch from a current view of the lot, the create must also carry `expected_seed_lot_version` under the rule of §2.7, and recording the plan itself advances the lot's `version`. A new batch starts `PLANNED`.

Recording the sow moves the batch from `PLANNED` to `SOWN` and requires the lot to be `AVAILABLE` (a quarantined lot fails with `ERR_LOT_QUARANTINED`). The payload's `sown_grams` must be a positive whole number no greater than the lot's `remaining_grams`; the debit reduces `remaining_grams`, advances the lot's `version`, and tips the lot into `DEPLETED` if the remainder reaches zero. The payload's `actual_sow_date` is stored on the batch. At the same moment the server computes the batch's `projected_plantable`, the forward-looking estimate used for planning reads: the whole-number floor of `sown_grams` multiplied by the seeds-per-gram figure for the lot's species — 88 for `DOUGLAS_FIR`, 55 for `LOBLOLLY_PINE`, and two-tenths of a seed per gram for `WHITE_OAK` — multiplied by the lot's current `germination_pct`, and finally multiplied by 0.88 to allow for the expected cull rate of twelve percent. The estimate deliberately ignores field reality and almost always differs from the physical count that grading later records.

Lifting moves the batch from `SOWN` to `LIFTED`. The recorded `lifted_on` date must fall on or after `lift_window_start` and on or before `lift_window_end` — a lift outside the inclusive window is rejected with `ERR_LIFT_WINDOW_INVALID` — and the `lifted_count` of seedlings must be a positive whole number. Grading then moves the batch from `LIFTED` to `GRADED`, recording the `plantable_count` of grade-acceptable seedlings, which must be positive and no greater than `lifted_count`; the server sets the batch's `cull_count` to the difference between `lifted_count` and `plantable_count`.

Grading can reveal a shortfall against reservations, and that fires CASCADE A. The batch's `reserved_plantable` is the total quantity across its `ACTIVE` allocation rows. While that reserved total exceeds the freshly recorded `plantable_count`, the server releases the batch's most recently created `ACTIVE` allocation — strictly in descending order of creation time, with no secondary tie-break on the identifier — and repeats until the reserved total no longer exceeds the plantable count; each released allocation flips to `RELEASED`. Every release recomputes its order's `allocated_quantity`, and an order that was `ALLOCATED` demotes back to `CONFIRMED` the moment its recomputed allocation total falls below the ordered `quantity`. Each such order demotion re-evaluates every planting contract supplied by that order, and a contract sitting at `READY_TO_PLANT` drops to `BLOCKED`. Finally, a graded batch moves automatically to its terminal `DEPLETED` state once the total quantity across all of its shipments — in any shipment status — equals the `plantable_count` and no `ACTIVE` storage placements remain for the batch.

### 3.3. Seedling Orders: Pricing, Lead Time, and Allocation

A landowner places a seedling order for their own account: the `landowner_id` in the payload must equal the caller's `X-User-ID` (a mismatch is rejected with `ERR_UNAUTHORIZED`), alongside the `destination_zone_id` where the seedlings will be planted, the requested `species` (one of `DOUGLAS_FIR`, `LOBLOLLY_PINE`, `WHITE_OAK`), the `quantity` of seedlings as a positive whole number, and the `requested_ship_date`. Lead time is judged against the logical clock: the requested ship date must lie at least 210 days after the current date for the conifer species (`DOUGLAS_FIR` and `LOBLOLLY_PINE`) and at least 120 days after it for the hardwood `WHITE_OAK`, with a date exactly at the limit passing; anything shorter is rejected with `ERR_LEAD_TIME_INSUFFICIENT`. A new order enters `PENDING_REVIEW`.

Pricing is computed entirely server-side. The `unit_price_cents` is fixed per species — 320 cents per `DOUGLAS_FIR` seedling, 280 for `LOBLOLLY_PINE`, and 540 for `WHITE_OAK`. The `total_price_cents` applies a volume discount keyed on the pre-discount subtotal, meaning `quantity` multiplied by `unit_price_cents`: fifteen percent off when that subtotal is at least 5,000,000 cents, ten percent off when it is at least 2,000,000 cents but below the higher tier, and full price below that. Keying the tier on the post-discount total would be circular and is not permitted. The discounted figure is rounded half-up to a whole cent. Two running totals track fulfilment from zero: `allocated_quantity`, the sum of quantities over the order's `ACTIVE` allocations, and `shipped_quantity`, the sum of quantities over shipments of the order's contracts in `DISPATCHED`, `DELIVERED`, or `PLANTED` status.

A `ContractOfficer` confirms a reviewed order, moving it from `PENDING_REVIEW` to `CONFIRMED`; the lead-time rule is re-evaluated at confirmation, again against the logical clock. The landowner may amend an order in `PENDING_REVIEW` or `CONFIRMED`, changing `quantity`, `requested_ship_date`, or both. An amendment must keep the lead-time rule satisfiable (`ERR_LEAD_TIME_INSUFFICIENT` otherwise), must carry `expected_seedling_order_version` under §2.7, recomputes `total_price_cents`, and returns the order to `PENDING_REVIEW` to be reviewed anew; the confirm-and-amend loop may cycle without limit, and each amendment advances the order's `version`. Either the landowner or a `ContractOfficer` may cancel an order still in `PENDING_REVIEW` or `CONFIRMED`, but only while nothing has shipped — once `shipped_quantity` is positive the cancel is rejected with `ERR_NOT_CANCELLABLE`. A successful cancel moves the order to the terminal `CANCELLED` state, releases every `ACTIVE` allocation of the order as compensation, and recomputes `reserved_plantable` on each affected batch. Orders can be listed with optional `landowner_id`, `destination_zone_id`, and `status` filters; the `Landowner` role sees only its own.

Reserving stock for an order is a `ContractOfficer` action naming the `crop_batch_id` and the `quantity` to reserve, which must be positive. The batch must be in `SOWN`, `LIFTED`, or `GRADED` — a batch still `PLANNED` or already `DEPLETED` fails with `ERR_BATCH_NOT_GRADED` — and its seed lot must not be quarantined (`ERR_LOT_QUARANTINED`). The seed-transfer rule binds the reservation: the batch's species must match the order's species, and the band midpoints of the batch lot's source zone and the order's destination zone may differ by no more than 500 feet, otherwise `ERR_SPECIES_ZONE_MISMATCH`. The reservable ceiling is the smaller of the order's uncovered remainder (its `quantity` minus its `allocated_quantity`) and the batch's unreserved basis — the `plantable_count` for a `GRADED` batch, the `projected_plantable` while the batch is `SOWN` or `LIFTED` — less the batch's `reserved_plantable`; a reservation above that ceiling is rejected with `ERR_ALLOCATION_EXCEEDS_AVAILABLE`. When a new allocation brings `allocated_quantity` exactly level with the order's `quantity`, the order moves automatically from `CONFIRMED` to `ALLOCATED`, and creating the allocation advances the order's `version` by one. New allocations start `ACTIVE`.

A `ContractOfficer` may also release an `ACTIVE` allocation manually, provided no shipment in `DISPATCHED` or `DELIVERED` status references that allocation's batch for any of the order's contracts. Release subtracts the allocation's quantity from the order's `allocated_quantity` and from the batch's `reserved_plantable`, flips the allocation to `RELEASED`, demotes an `ALLOCATED` order back to `CONFIRMED` when coverage drops below the ordered quantity, and runs the contract-demotion link of CASCADE A on any contract fed by a demoted order. Allocations can be listed with optional `seedling_order_id`, `crop_batch_id`, and `status` filters.

### 3.4. Cold Storage and the Shipment Pipeline

Cold storage lives in units created by the `NurseryManager`. A unit carries a `unit_code` unique across all units, a positive whole-number `capacity_units` ceiling on the seedlings it may hold at any instant, and the cold-chain temperature bounds `temp_min_c` and `temp_max_c`, where the upper bound must be strictly greater than the lower; an inverted temperature range is rejected as malformed with `ERR_INVALID_REQUEST`. The unit's `current_load` is derived, not stored by hand: the sum, over its `ACTIVE` placements, of each placement's `quantity` minus its `withdrawn_quantity`.

Graded stock is placed into units as placements carrying the `crop_batch_id`, the receiving `storage_unit_id`, the `quantity` placed as a positive whole number, and the `placed_on` date. Two ceilings guard placement creation. The placement may not exceed the batch's unplaced plantable remainder — the batch's `plantable_count` less the quantities on all of the batch's placements that have not been discarded — otherwise `ERR_PLACEMENT_EXCEEDS_PLANTABLE`. And the unit's `current_load` plus the new `quantity` may not exceed `capacity_units`, with a placement that exactly fills the unit passing — otherwise `ERR_STORAGE_CAPACITY_EXCEEDED`. A new placement starts `ACTIVE` with `withdrawn_quantity` at zero. When shipments withdraw the full quantity, the placement moves automatically to `WITHDRAWN`; a `NurseryManager` may instead discard an `ACTIVE` placement outright, recording a `reason`, which writes off the unwithdrawn remainder as culls — without altering the batch's `cull_count` — and moves the placement to `DISCARDED`. Withdrawal and discard both recompute the unit's `current_load`. Placements can be listed with optional `crop_batch_id`, `storage_unit_id`, and `status` filters.

Dispatching stock to a planting site creates a shipment naming the destination `planting_contract_id`, the `crop_batch_id` drawn from, and the `quantity` as a positive whole number; it is the pipeline's most heavily gated write. The destination contract must be `READY_TO_PLANT` or `PLANTING` — any other status is rejected with `ERR_INVALID_STATE`. The batch must be `GRADED` (`ERR_BATCH_NOT_GRADED`) and its lot must not be quarantined (`ERR_LOT_QUARANTINED`). The seed-transfer rule must hold between the batch lot's source zone and the contract's `site_zone_id` — species match with the order plus band midpoints no more than 500 feet apart — otherwise `ERR_SPECIES_ZONE_MISMATCH`. Stock age is enforced at day granularity: for every `ACTIVE` placement the withdrawal touches, the dispatch date minus the placement's `placed_on` may not exceed 45 days, with a placement exactly 45 days old passing, otherwise `ERR_STOCK_AGE_EXCEEDED`. Sufficiency requires both that the batch's stored unwithdrawn stock covers the shipment quantity and that the order's `ACTIVE` allocations on this batch sum to at least the quantity, otherwise `ERR_INSUFFICIENT_STORED_STOCK`. On success the server stamps `dispatched_at` from the logical clock, computes `handling_deadline` as exactly 72 hours after `dispatched_at`, withdraws from the batch's `ACTIVE` placements oldest-first — earliest `placed_on` first, earliest `created_at` breaking ties — flips any emptied placement to `WITHDRAWN`, adds the quantity to the order's `shipped_quantity`, and moves the order automatically to `FULFILLED` once `shipped_quantity` reaches the ordered `quantity`. A new shipment starts `DISPATCHED`.

Delivery moves a shipment from `DISPATCHED` to `DELIVERED`, recording a `delivered_at` that may not precede `dispatched_at`. Confirming the stock in the ground moves it from `DELIVERED` to `PLANTED`; that confirmation is a `ContractOfficer` action requiring the destination contract to be `PLANTING`, and the recorded `planted_confirmed_at` must fall no later than the shipment's `handling_deadline` — a confirmation exactly at the deadline passes, anything later is rejected with `ERR_HANDLING_WINDOW_EXCEEDED`. A `FieldAuditor` may instead write off a shipment still in `DISPATCHED` or `DELIVERED`, supplying a `reason` that is recorded as `spoilage_reason`, one of `TEMP_EXCURSION`, `WINDOW_EXPIRED`, or `HANDLING_DAMAGE`. Spoilage moves the shipment to `SPOILED` and subtracts its quantity from the order's `shipped_quantity`: spoiled stock is written off rather than returned to storage, so it no longer counts toward fulfilment. Shipments can be listed with optional `planting_contract_id`, `crop_batch_id`, and `status` filters.

### 3.5. Planting Contracts and Crew Scheduling

A `ContractOfficer` drafts a planting contract binding a `landowner_id`, the supply order via `seedling_order_id`, and the planting site's `site_zone_id`, together with the `acres` under contract (a positive number, fractional acreage permitted), the spacing specification `trees_per_acre` as a whole number between 200 and 800 inclusive (outside that band the create is rejected with `ERR_SPACING_SPEC_INVALID`), a `contingency_pct` overage fraction for culls and mortality between 0 and 0.25 inclusive, and the planting window from `planting_window_start` to `planting_window_end`, where the end may equal the start but not precede it (`ERR_WINDOW_INVERTED`). At creation the server computes `required_seedlings`: the `acres` multiplied by `trees_per_acre`, multiplied by one plus the effective contingency fraction, with the product rounded up to a whole seedling. The effective contingency is the contract's `contingency_pct` alone for sites under 50 acres, and the `contingency_pct` plus a further 0.05 large-site surcharge when the contract covers at least 50 acres. A new contract opens in `DRAFT` with `site_prep_status` `NONE` and `planted_quantity` zero.

Site preparation follows a strict record-then-verify separation of duties. Recording a herbicide application — a `ContractOfficer` action carrying the `herbicide_applied_on` date — moves the contract from `DRAFT` to `SITE_PREP` and sets `site_prep_status` to `RECORDED`; the recorded date may not lie in the future of the logical clock. The same recording action from `REPLANT_REQUIRED` closes the replant loop, again landing at `SITE_PREP` with `RECORDED`, which supersedes any earlier `VERIFIED` from the prior cycle. Independent verification by a `FieldAuditor` then advances `site_prep_status` from `RECORDED` to `VERIFIED`; the officer who recorded the prep can never verify it — the recording and verifying roles are distinct by design — and any readiness check attempted before verification is rejected with `ERR_SITE_PREP_NOT_VERIFIED`. The `site_prep_status` field can hold `NONE`, `RECORDED`, `VERIFIED`, or `STALE`.

Marking a contract ready moves it from `SITE_PREP` or `BLOCKED` to `READY_TO_PLANT` and requires two things: verified site prep, and a fully covered supply order whose `allocated_quantity` reaches the contract's `required_seedlings` — a shortfall is rejected with `ERR_ORDER_UNDER_ALLOCATED`. Readiness is deliberately fragile: whenever CASCADE A demotes the linked supply order below full allocation, the contract drops automatically from `READY_TO_PLANT` back to `BLOCKED`, from which it can be marked ready again once coverage and verification still hold.

Opening the planting window moves the contract from `READY_TO_PLANT` to `PLANTING` and checks three conditions against the logical clock. The herbicide's age — the current date minus `herbicide_applied_on` — must be at least 14 days and at most 120 days, both bounds inclusive; outside that efficacy window the start is rejected with `ERR_SITE_PREP_WINDOW_INVALID`. At least one `CONFIRMED` crew assignment of the contract must cover the current date within its half-open interval. And the current date must fall within the contract's planting window from `planting_window_start` to `planting_window_end`. Completing a planting moves the contract from `PLANTING` to `PLANTED` and records the `planted_qty`. On the initial planting — when the contract's `obligation_count` is zero — the recorded quantity must be at least the contract's `acres` multiplied by `trees_per_acre`, with an exact match passing; on replant cycles, when one or more earlier surveys have failed, it must reach the `owed_quantity` of the most recent obligation still `OPEN` or `SCHEDULED`. Either shortfall is rejected with `ERR_PLANTING_QUANTITY_SHORT`. The recorded quantity accumulates into the contract's `planted_quantity` across replant cycles, `last_planted_on` is set to the current logical date, and every `CONFIRMED` crew assignment of the contract is automatically marked `COMPLETED`, releasing its booked crew capacity.

A contract can be cancelled by a `ContractOfficer` from `DRAFT`, `SITE_PREP`, `READY_TO_PLANT`, or `BLOCKED`, so long as none of its shipments has reached `DISPATCHED`, `DELIVERED`, or `PLANTED` — once any such shipment exists the cancel is rejected with `ERR_NOT_CANCELLABLE`. A successful cancel moves the contract to the terminal `CANCELLED` state and releases all of the contract's `SCHEDULED` and `CONFIRMED` crew assignments, restoring their crews' capacity, but deliberately leaves the supply order's allocations untouched: the order lifecycle is independent of the contract's.

Crews are registered with a unique `crew_code`, a positive whole-number `capacity_per_day` in seedlings, and an `active` flag, defaulting to true, that records whether the crew may receive new assignments. Scheduling an assignment names the `crew_id`, the `planting_contract_id`, a half-open work interval from `start_date` up to but not including `end_date` — the end must be strictly after the start, otherwise `ERR_WINDOW_INVERTED` — and the `planned_seedlings` for the interval as a positive whole number. Two crew rules guard creation. First, overlap: a crew's `SCHEDULED` and `CONFIRMED` intervals must never intersect, with assignments on the same contract allowed to abut exactly (one's `start_date` equal to the other's `end_date`), while assignments on different contracts must leave a full day of buffer — the new interval starts at least one day after the existing one ends, or ends at least one day before the existing one starts; violations are rejected with `ERR_CREW_OVERLAP`. Second, capacity: an assignment's daily load is its `planned_seedlings` divided by the interval's length in days, rounded up to a whole seedling per day, and the crew's free capacity on any date is its `capacity_per_day` less the daily loads of its `SCHEDULED` and `CONFIRMED` assignments covering that date; the new assignment's daily load may not exceed the crew's remaining capacity over its interval, otherwise `ERR_CREW_CAPACITY_EXCEEDED`. Confirming an assignment moves it from `SCHEDULED` to `CONFIRMED` and requires the contract to be in `SITE_PREP`, `READY_TO_PLANT`, or `BLOCKED`. Releasing a `SCHEDULED` or `CONFIRMED` assignment restores the crew's capacity; beyond manual release by a `ContractOfficer`, assignments are released automatically when their contract is cancelled or flipped to `REPLANT_REQUIRED`, and completed automatically when the contract's planting completes. Assignments can be listed with optional `crew_id`, `planting_contract_id`, and `status` filters.

### 3.6. Survival Surveys and the Replant Obligation Cycle

A `FieldAuditor` records a survival survey for a contract by supplying the `planting_contract_id`, the `surveyed_on` date, and the `alive_count` of living seedlings. Timing is strict: `surveyed_on` must fall no earlier than 300 days and no later than 400 days after the contract's `last_planted_on`, both bounds inclusive — a survey outside that window is rejected with `ERR_SURVEY_WINDOW_INVALID`. At creation the server snapshots the contract's `planted_quantity` into the survey's `planted_count_snapshot`, and `alive_count` must be non-negative and no greater than that snapshot.

The verdict is arithmetic. The survey's `survival_pct` is the `alive_count` divided by the `planted_count_snapshot`, multiplied by 100, and rounded half-up to exactly two decimal places. The pass bar, `threshold_pct`, is 70.00 — unless the contract's landowner holds any cost-share enrollment in `APPROVED`, `PAYMENT_HELD`, or `PAID`, in which case it rises to 80.00. Identical field data can therefore pass for one landowner and fail for another: a survey at 75.00 passes the standard bar and fails the cost-share bar. The survey's `below_threshold` flag is true exactly when `survival_pct` is strictly less than `threshold_pct`; equality passes.

A successful survey creation moves the contract from `PLANTED` to `SURVEYED` and immediately re-evaluates it: a passing survey closes the contract (`SURVEYED` → `CLOSED`), while a failing one flips it to `REPLANT_REQUIRED` and fires CASCADE B. CASCADE B opens the survey's embedded replant obligation — its `obligation_status` moves from `NONE` to `OPEN` with the `owed_quantity` computed — releases every `SCHEDULED` or `CONFIRMED` crew assignment of the contract, and, if the contract's landowner holds a cost-share enrollment in `APPROVED`, moves that enrollment to `PAYMENT_HELD`. The contract's `obligation_count` counts how many of its surveys have ever landed below threshold, and never decreases. From `REPLANT_REQUIRED`, the contract re-enters the site-prep loop of §3.5, plants again, and is surveyed again in a new window.

The owed quantity grows with repeat failure. The required-survivors figure is the contract's `required_seedlings` multiplied by the survey's `threshold_pct` and divided by 100, rounded up to a whole seedling. The base shortfall is that figure minus the survey's `alive_count`, and never below zero. When the contract has already failed at least one earlier survey — an `obligation_count` of one or more — the base shortfall is escalated by a factor of 1.25 and the product rounded up to a whole seedling; a first failure stands unescalated. The survey's `owed_quantity` is then the smaller of two values: twice the `planted_count_snapshot`, and the smaller of the `planted_count_snapshot` and the possibly escalated shortfall. A passing survey owes nothing.

The obligation embedded in the survey has its own small lifecycle. A `ContractOfficer` schedules the replant, moving `obligation_status` from `OPEN` to `SCHEDULED`, with a `replant_date` no earlier than the current logical date. Reopening sends a `SCHEDULED` obligation back to `OPEN` and clears its `replant_date`; the schedule-and-reopen loop may repeat without limit. Fulfilling the obligation moves it from `SCHEDULED` to `FULFILLED` and requires the contract to be in `PLANTED`, `SURVEYED`, or `CLOSED` with its `last_planted_on` later than the survey's own `created_at` date — evidence that a replant cycle actually completed after the survey was taken. A `ProgramAdministrator` may instead waive an `OPEN` obligation with a non-empty `waiver_reason`, moving it to `WAIVED` and recording the reason on the survey. Either resolution releases the payment hold: once no survey on any of the landowner's contracts still carries an `OPEN` or `SCHEDULED` obligation, that landowner's `PAYMENT_HELD` enrollments return automatically to `APPROVED`. Surveys can be listed with an optional `planting_contract_id` filter.

### 3.7. Cost-Share Enrollments and Payment Holds

A landowner enrolls acreage in a cost-share program by naming their own `landowner_id`, the `program_code` identifying the program, the `enrolled_acres` approved for enrollment, the program's `rate_per_acre_cents`, and the enrollment's `cap_cents` ceiling — the acreage, rate, and cap are all positive, with the rate and cap as whole cents. The server immediately computes a `provisional_award_cents` estimate from the enrolled acreage, and the enrollment starts in `DRAFT`. Submitting practice documentation moves the enrollment from `DRAFT` to `UNDER_REVIEW`, recording the verified `documented_acres` — which must be positive and no greater than `enrolled_acres`, otherwise `ERR_ENROLLMENT_ACRES_EXCEEDED` — and the `documented_cost_cents` of eligible cost, also positive, and recomputing the provisional award from the documented acreage.

Both award variants share one formula and one pinned rounding order. The base component is the acreage basis multiplied by `rate_per_acre_cents`, rounded half-up to a whole cent. The stewardship bonus is ten percent of that base, likewise rounded half-up to a whole cent. The award is the sum of base and bonus, capped at the enrollment's `cap_cents`. Each component is rounded to whole cents before the two are summed; summing first and rounding once is not permitted. The provisional variant uses `enrolled_acres` as the basis at creation and is recomputed from `documented_acres` at submit; the final variant, computed at approval, uses `documented_acres` and therefore diverges from the original provisional whenever documented and enrolled acreage differ.

A `ProgramAdministrator` reviews submissions. Returning one for correction moves it from `UNDER_REVIEW` back to `DRAFT` and requires a non-empty `reason`; the submit-and-return loop may cycle without limit. Approval moves the enrollment from `UNDER_REVIEW` to `APPROVED`, fixing the `final_award_cents` per the final variant while the provisional figure is retained for delta reporting. Disbursement moves an `APPROVED` enrollment to `PAID` and sets `paid_cents` to the full final award in a single payment; an enrollment sitting at `PAYMENT_HELD` cannot be paid, and the attempt is rejected with `ERR_PAYMENT_HELD`. That hold arrives automatically whenever CASCADE B flips any contract of the same landowner to `REPLANT_REQUIRED`, and lifts automatically once the landowner has no remaining `OPEN` or `SCHEDULED` replant obligation on any contract, as described in §3.6. Enrollments can be listed with optional `landowner_id` and `status` filters; the `Landowner` role sees only its own.

## 4. Endpoint Definitions

Endpoints that create a new stand-alone resource — a landowner, zone, lot, crop batch, order, allocation, storage unit, placement, contract, crew, assignment, shipment, survey, or enrollment — return `201 Created`. Endpoints that act on or modify an existing resource, including every state-transition action and the logical-clock adjustment, return `200 OK`, as do all reads. Request payloads, computed fields, validation triggers, and side effects for each endpoint are defined by the narratives in §3; this table is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/reforestation/_clock/set_current_utc` | Advance the test-driving logical clock | NurseryManager, ContractOfficer, ProgramAdministrator, FieldAuditor |
| POST | `/reforestation/landowners` | Register a landowner | ContractOfficer |
| GET | `/reforestation/landowners/{id}` | Read one landowner; Landowner reads only its own | ContractOfficer, ProgramAdministrator, Landowner |
| POST | `/reforestation/seed-zones` | Create a seed collection zone | NurseryManager |
| GET | `/reforestation/seed-zones/{id}` | Read one seed zone | NurseryManager, ContractOfficer |
| POST | `/reforestation/seed-lots` | Register a seed lot | NurseryManager |
| GET | `/reforestation/seed-lots/{id}` | Read one seed lot | NurseryManager, ContractOfficer |
| GET | `/reforestation/seed-lots` | List seed lots, optionally filtered | NurseryManager, ContractOfficer |
| POST | `/reforestation/seed-lots/{id}/quarantine` | Quarantine a lot after a failed germination retest | NurseryManager |
| POST | `/reforestation/seed-lots/{id}/release` | Release a quarantined lot with a passing retest | NurseryManager |
| POST | `/reforestation/crop-batches` | Plan a crop batch against a seed lot (OCC on lot version) | NurseryManager |
| GET | `/reforestation/crop-batches/{id}` | Read one crop batch | NurseryManager, ContractOfficer |
| GET | `/reforestation/crop-batches` | List crop batches, optionally filtered | NurseryManager, ContractOfficer |
| POST | `/reforestation/crop-batches/{id}/sow` | Record sowing; debits the lot | NurseryManager |
| POST | `/reforestation/crop-batches/{id}/lift` | Record lifting within the lift window | NurseryManager |
| POST | `/reforestation/crop-batches/{id}/grade` | Record grading; fires CASCADE A on shortfall | NurseryManager |
| POST | `/reforestation/seedling-orders` | Place a seedling order; Landowner acts for self | Landowner |
| GET | `/reforestation/seedling-orders/{id}` | Read one order; Landowner reads only its own | Landowner, ContractOfficer, NurseryManager |
| GET | `/reforestation/seedling-orders` | List orders with filters; Landowner sees only its own | Landowner, ContractOfficer, NurseryManager |
| POST | `/reforestation/seedling-orders/{id}/confirm` | Confirm a pending order | ContractOfficer |
| POST | `/reforestation/seedling-orders/{id}/amend` | Amend quantity/ship date (OCC on order version) | Landowner |
| POST | `/reforestation/seedling-orders/{id}/cancel` | Cancel an order before any shipment | Landowner, ContractOfficer |
| POST | `/reforestation/seedling-orders/{id}/allocations` | Reserve stock from a batch for this order | ContractOfficer |
| GET | `/reforestation/allocations/{id}` | Read one allocation | ContractOfficer, NurseryManager |
| GET | `/reforestation/allocations` | List allocations, optionally filtered | ContractOfficer, NurseryManager |
| POST | `/reforestation/allocations/{id}/release` | Manually release an active allocation | ContractOfficer |
| POST | `/reforestation/storage-units` | Create a cold-storage unit | NurseryManager |
| GET | `/reforestation/storage-units/{id}` | Read one storage unit | NurseryManager |
| POST | `/reforestation/storage-placements` | Place graded stock into a unit | NurseryManager |
| GET | `/reforestation/storage-placements/{id}` | Read one placement | NurseryManager |
| GET | `/reforestation/storage-placements` | List placements, optionally filtered | NurseryManager |
| POST | `/reforestation/storage-placements/{id}/discard` | Write off the unwithdrawn remainder of a placement | NurseryManager |
| POST | `/reforestation/planting-contracts` | Create a planting contract with spacing spec and window | ContractOfficer |
| GET | `/reforestation/planting-contracts/{id}` | Read one contract; Landowner reads only its own | ContractOfficer, FieldAuditor, ProgramAdministrator, Landowner |
| GET | `/reforestation/planting-contracts` | List contracts with filters; Landowner sees only its own | ContractOfficer, FieldAuditor, ProgramAdministrator, Landowner |
| POST | `/reforestation/planting-contracts/{id}/record-site-prep` | Record herbicide application | ContractOfficer |
| POST | `/reforestation/planting-contracts/{id}/verify-site-prep` | FieldAuditor verifies the recorded site prep | FieldAuditor |
| POST | `/reforestation/planting-contracts/{id}/mark-ready` | Gate readiness on verified prep and full allocation | ContractOfficer |
| POST | `/reforestation/planting-contracts/{id}/start-planting` | Open the planting window for the crew | ContractOfficer |
| POST | `/reforestation/planting-contracts/{id}/complete-planting` | Record planted quantity; auto-completes confirmed crews | ContractOfficer |
| POST | `/reforestation/planting-contracts/{id}/cancel` | Cancel a contract before any shipment | ContractOfficer |
| POST | `/reforestation/crews` | Register a planting crew | ContractOfficer |
| GET | `/reforestation/crews/{id}` | Read one crew | ContractOfficer |
| POST | `/reforestation/crew-assignments` | Schedule a crew onto a contract | ContractOfficer |
| GET | `/reforestation/crew-assignments/{id}` | Read one assignment | ContractOfficer |
| GET | `/reforestation/crew-assignments` | List assignments, optionally filtered | ContractOfficer |
| POST | `/reforestation/crew-assignments/{id}/confirm` | Confirm a scheduled assignment | ContractOfficer |
| POST | `/reforestation/crew-assignments/{id}/release` | Release an assignment, restoring crew capacity | ContractOfficer |
| POST | `/reforestation/shipments` | Dispatch seedlings from cold storage to a contract site | NurseryManager |
| GET | `/reforestation/shipments/{id}` | Read one shipment | NurseryManager, ContractOfficer, FieldAuditor |
| GET | `/reforestation/shipments` | List shipments, optionally filtered | NurseryManager, ContractOfficer, FieldAuditor |
| POST | `/reforestation/shipments/{id}/deliver` | Record delivery at the site | NurseryManager |
| POST | `/reforestation/shipments/{id}/confirm-planted` | Confirm seedlings in the ground within the handling window | ContractOfficer |
| POST | `/reforestation/shipments/{id}/report-spoilage` | FieldAuditor writes off a shipment | FieldAuditor |
| POST | `/reforestation/survival-surveys` | Record a survival survey; fires threshold verdict and CASCADE B | FieldAuditor |
| GET | `/reforestation/survival-surveys/{id}` | Read one survey | FieldAuditor, ContractOfficer, ProgramAdministrator |
| GET | `/reforestation/survival-surveys` | List surveys, optionally filtered | FieldAuditor, ContractOfficer, ProgramAdministrator |
| POST | `/reforestation/survival-surveys/{id}/schedule-replant` | Schedule the replant obligation | ContractOfficer |
| POST | `/reforestation/survival-surveys/{id}/reopen-replant` | Send a scheduled obligation back for rescheduling | ContractOfficer |
| POST | `/reforestation/survival-surveys/{id}/fulfill-replant` | Close the obligation after a completed replant cycle | ContractOfficer |
| POST | `/reforestation/survival-surveys/{id}/waive-replant` | Waive the obligation | ProgramAdministrator |
| POST | `/reforestation/cost-share-enrollments` | Enroll a landowner in a cost-share program | Landowner |
| GET | `/reforestation/cost-share-enrollments/{id}` | Read one enrollment; Landowner reads only its own | Landowner, ProgramAdministrator |
| GET | `/reforestation/cost-share-enrollments` | List enrollments; Landowner sees only its own | Landowner, ProgramAdministrator |
| POST | `/reforestation/cost-share-enrollments/{id}/submit` | Submit practice documentation | Landowner |
| POST | `/reforestation/cost-share-enrollments/{id}/approve` | Approve and fix the final award | ProgramAdministrator |
| POST | `/reforestation/cost-share-enrollments/{id}/return-for-correction` | Return documentation to the landowner | ProgramAdministrator |
| POST | `/reforestation/cost-share-enrollments/{id}/pay` | Disburse the final award | ProgramAdministrator |


## 5. Error Code Catalogue

The trigger condition of each error is defined in the narrative of §2 and §3 beside the workflow it guards; this catalogue is a summary of identifiers and status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_WINDOW_INVERTED` | 400 |
| `ERR_LOT_QUARANTINED` | 422 |
| `ERR_SITE_PREP_NOT_VERIFIED` | 422 |
| `ERR_SITE_PREP_WINDOW_INVALID` | 422 |
| `ERR_LEAD_TIME_INSUFFICIENT` | 422 |
| `ERR_SURVEY_WINDOW_INVALID` | 422 |
| `ERR_HANDLING_WINDOW_EXCEEDED` | 422 |
| `ERR_STOCK_AGE_EXCEEDED` | 422 |
| `ERR_LIFT_WINDOW_INVALID` | 422 |
| `ERR_SPECIES_ZONE_MISMATCH` | 422 |
| `ERR_CREW_OVERLAP` | 409 |
| `ERR_SPACING_SPEC_INVALID` | 422 |
| `ERR_BATCH_NOT_GRADED` | 422 |
| `ERR_PLANTING_QUANTITY_SHORT` | 422 |
| `ERR_INSUFFICIENT_STORED_STOCK` | 422 |
| `ERR_ALLOCATION_EXCEEDS_AVAILABLE` | 422 |
| `ERR_PLACEMENT_EXCEEDS_PLANTABLE` | 422 |
| `ERR_STORAGE_CAPACITY_EXCEEDED` | 422 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 422 |
| `ERR_ORDER_UNDER_ALLOCATED` | 422 |
| `ERR_ENROLLMENT_ACRES_EXCEEDED` | 422 |
| `ERR_NOT_CANCELLABLE` | 409 |
| `ERR_PAYMENT_HELD` | 422 |
