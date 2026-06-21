# Food Bank Pantry Distribution API — Product Requirements Document

## 1. Introduction

A regional food bank sits at the center of a fragile supply chain. Perishable donations and grocery-rescue loads arrive on no fixed schedule, federal commodity stock (TEFAP) and purchased product must be tracked separately for funding audits, and dozens of partner pantries compete for the same finite pool of poundage every cycle. This API is the system of record that holds all of those concerns together: it governs how food enters cold storage, how it is rationed fairly across partner agencies, how households are certified for federal commodities, and how every pound is reconciled from intake to hand-out.

The platform is built around four operational realities. First, **cold chain integrity** — produce, dairy, frozen meat, and dry goods each demand a specific storage temperature, and a lot that lands in the wrong unit is a food-safety incident. Second, **fair allocation** — a limited pool of poundage must be divided among agencies in proportion to their assigned weight, with hard caps that prevent any one agency from over-drawing. Third, **first-expired-first-out (FEFO) discipline** — when an order is approved, the system must consume the inventory closest to expiration before anything else, so that food leaves the warehouse before it spoils. Fourth, **dual-ledger poundage reporting** — the food bank must report both what it *planned* to distribute (a forward-looking projection) and what it *actually* distributed (a chronological accounting of finalized events), and the gap between the two is the shrinkage every grant officer wants to see.

This document specifies the complete contract: the resources, their lifecycles, the calculations that bind them, the validation rules that protect them, and the HTTP surface through which all of it is exercised.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted at the API root.

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they act. The system recognizes exactly four roles: `FoodBankOperator`, `AllocationManager`, `AgencyCoordinator`, and `ComplianceAuditor`. A request that omits either header, or that presents an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles divide along warehouse, allocation, partner, and audit lines. A `FoodBankOperator` is the warehouse hand: they create cold storage units, intake lots, and dispose of spoiled or expired stock. An `AllocationManager` runs the fair-allocation machinery: they register agencies, open and close allocation cycles, and approve, reject, or recall agency orders. An `AgencyCoordinator` is partner-agency staff who register client households, submit and cancel their agency's orders, and run distribution events. A `ComplianceAuditor` certifies household TEFAP eligibility and audits poundage, and is otherwise read-only.

Three of these roles carry an **opaque identity**. When `X-User-Role` is `FoodBankOperator`, `AllocationManager`, or `ComplianceAuditor`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The `AgencyCoordinator` role, by contrast, is **entity-backed**: when `X-User-Role` is `AgencyCoordinator`, `X-User-ID` is the `id` of the acting `Agency`. Ownership checks on any resource that references an `Agency` compare the resource's agency foreign key to `X-User-ID`. Concretely, an `AgencyCoordinator` may submit an order, cancel an order, register a household, or plan, pack, finalize, or void a distribution event only when the target resource belongs to the agency named by their `X-User-ID`. An attempt to act on a resource owned by a different agency is rejected with `ERR_AGENCY_SCOPE_VIOLATION`.

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

List endpoints accept two pagination query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items to skip and defaults to 0, with no upper bound beyond the available data. A `limit` below 1 or above 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION`.

Unless a specific endpoint says otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in this system carry a uniform set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, marking creation and last modification respectively. The `version` is an integer that begins at its initial value on creation and increments by one on every mutation of the resource; it is the anchor for optimistic concurrency control described in §2.7.

One resource departs from this convention. The `PoundageReport` is a read-time snapshot and carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because it is never mutated in place — it is recomputed on each read. Every other resource — `ColdStorageUnit`, `InventoryLot`, `Agency`, `AllocationCycle`, `AgencyOrder`, `OrderLine`, `ClientHousehold`, and `DistributionEvent` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Cold Chain, Capacity, and Occupancy

Cold storage is the physical substrate of the warehouse, and the system tracks occupancy live. Each `ColdStorageUnit` provides exactly one temperature zone via `temp_zone`, one of `DRY`, `REFRIGERATED`, or `FROZEN`, and advertises a `capacity_lbs` ceiling that must be strictly greater than zero. Its `stored_lbs` is a computed running total: the sum of `remaining_lbs` over every `InventoryLot` whose `cold_storage_unit_id` points at this unit and whose `disposition` is either `AVAILABLE` or `RESERVED`. Lots that have become `DEPLETED`, `EXPIRED`, or `DISPOSED` leave the occupancy count entirely. This total is recomputed on every event that touches a unit's lots — intake, reservation, debit, expiry, and disposal. The unit's `status` is derived directly from this figure: it reads `FULL` when `stored_lbs` equals `capacity_lbs`, and `AVAILABLE` whenever `stored_lbs` is below `capacity_lbs`.

Cold-chain matching is enforced at the moment a lot is taken in. Each `InventoryLot` carries a `food_category` — one of `PRODUCE`, `DAIRY`, `FROZEN_MEAT`, `DRY_GOODS`, or `BAKERY` — from which the system derives `required_temp_zone`: produce and dairy require `REFRIGERATED`, frozen meat requires `FROZEN`, and dry goods and bakery require `DRY`. At intake, the derived `required_temp_zone` must equal the holding unit's `temp_zone`; a mismatch is rejected with `ERR_COLD_CHAIN_MISMATCH`. Capacity is the second gate: a lot whose `intake_lbs` would push the holding unit's `stored_lbs` strictly above its `capacity_lbs` is rejected with `ERR_COLD_STORAGE_CAPACITY_EXCEEDED`. An intake that lands the unit exactly at capacity is permitted; only a strict overage is refused.

### 2.6. Hierarchical Consistency and Nested Retrieval

Many operations in this system mutate more than one resource at once. The governing principle is that the system performs cascades automatically: when an order is approved, inventory lots are reserved and a storage unit's occupancy is recomputed without any separate client call against those resources. Whenever the server mutates a resource as part of such a cascade — debiting a lot, restoring poundage, retitling a unit's occupancy, advancing an order — it refreshes that resource's `updated_at` and increments its `version` by one. The precise cascades are specified in §3, but the invariant is uniform: every secondary mutation is a real mutation, visible through a bumped `version`.

For retrieval, several collections are reachable through a parent resource's path — the lots held in a storage unit, the order lines under an order or against a lot, the households or orders under an agency, the orders or poundage report under a cycle. For any such nested path, the system validates each identifier left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing resource, before attempting to read anything deeper.

### 2.7. Optimistic Concurrency on Inventory Lots

Two write operations in this system act on an `InventoryLot` whose state another writer may have changed since the caller last read it, and both are guarded by optimistic concurrency control keyed on the lot's `version`. In each case the caller must supply `expected_lot_version` in the request body, carrying the `version` of the lot they last observed.

When an `AllocationManager` approves an order, the approval pins the FEFO-earliest `InventoryLot` the manager last observed through `expected_lot_version`. If that lot's `version` has advanced since — because another order's approval has already reserved against it and legitimately changed its remaining balance — the approval is rejected with `ERR_STALE_LOT_VERSION` at HTTP 412, so the manager re-reads the lot before approving against a balance that no longer holds. Likewise, when a `FoodBankOperator` disposes of a lot, the dispose request must carry `expected_lot_version` matching the lot's current `version`; if a shelf-life sweep has meanwhile transitioned the lot from `AVAILABLE` to `EXPIRED` and bumped its `version`, the stale dispose is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), forcing the operator to re-read the lot and confirm its disposition before disposing. No other endpoint takes a version field; these two are the only OCC-guarded writes.

### 2.8. Poundage Precision and Monetary Units

Poundage figures carry meaningful fractions, and every computed poundage total — planned, distributed, TEFAP, shrinkage, and event-level allocations — is rounded to two decimal places using the round-half-up convention. The one exception is the fair-share cap, which is expressed in whole integer pounds and is always rounded down (floored), as described in §3.4. Where the TEFAP eligibility check works in money, it works in integer cents: both `monthly_income_cents` and the derived income threshold are integer-cent quantities, and `unit_cost_cents` is a per-pound acquisition cost recorded in integer cents.

### 2.9. The Test-Driving Clock

The system maintains a logical "current UTC" clock that drives two time-based sweeps. An operator may advance this clock by supplying a `to_iso8601` instant. Advancing the clock runs a shelf-life sweep: every `AVAILABLE` lot whose `expiration_date` is at or before the new current time transitions to `EXPIRED`, its holding unit's occupancy is recomputed, and its `version` is bumped. The same clock advance ages certifications: every `CERTIFIED` household whose certification is now 365 days old or older transitions to `EXPIRED`, bumping its `version`. This capability exists to make time-dependent behavior testable; its HTTP shape is given in §4.

## 3. Business Logic & Workflows

### 3.1. Stocking the Warehouse: Cold Storage and Lot Intake

The warehouse begins with cold storage. A `FoodBankOperator` creates a `ColdStorageUnit` by giving it a `name`, a `temp_zone`, and a `capacity_lbs`. On creation its `stored_lbs` is initialized to 0 and its `status` to `AVAILABLE`; both are computed thereafter and never set directly by a client.

Lots flow in next. To intake an `InventoryLot`, a `FoodBankOperator` names the holding `cold_storage_unit_id`, the `food_category`, the `source_type`, the `intake_lbs`, and the `expiration_date`, and may optionally supply `unit_cost_cents`. The `source_type` records provenance and funding stream — one of `DONATION`, `RESCUE`, `TEFAP`, or `PURCHASED`. Donation and rescue lots carry no acquisition cost, so their `unit_cost_cents` is 0; purchased and TEFAP lots carry a positive per-pound cost in cents, and when omitted the value defaults to 0. The `intake_lbs` must be strictly positive, and `unit_cost_cents`, when present, must be zero or greater. Cold-chain matching (the derived `required_temp_zone` against the unit's `temp_zone`) and capacity (`stored_lbs` against `capacity_lbs`) are both enforced here, as detailed in §2.5. On a successful intake the lot's `remaining_lbs` is set equal to its `intake_lbs`, its `disposition` starts at `AVAILABLE`, and the holding unit's `stored_lbs` and `status` are recomputed.

A lot's life is tracked by its `disposition`, which moves through `AVAILABLE`, `RESERVED`, `DEPLETED`, `EXPIRED`, and `DISPOSED`, with `DISPOSED` terminal. The reservation, depletion, and release transitions are driven by the order workflow and are described in §3.5 and §3.7. Two transitions are warehouse-driven. When the logical clock advances past a lot's `expiration_date`, an `AVAILABLE` lot ages to `EXPIRED`: this fires only for lots whose `disposition` is `AVAILABLE` and whose `expiration_date` is at or before the new current time, and it leaves `RESERVED` lots untouched — reserved poundage is protected until released or distributed. Expiry recomputes the holding unit's `stored_lbs` and bumps the lot's `version`.

Disposal is the operator's manual exit. A `FoodBankOperator` may dispose of a lot whose `disposition` is `EXPIRED` (the normal end of an aged lot) or one whose `disposition` is still `AVAILABLE` (manual disposal of unexpired but spoiled or recalled stock). Either way the lot moves to `DISPOSED`, its `remaining_lbs` is set to 0, the holding unit's `stored_lbs` is recomputed, and its `version` is bumped. Disposal is OCC-guarded: the operator must pass `expected_lot_version` matching the lot's current `version`, per §2.7. Attempting to dispose a lot that is in neither `EXPIRED` nor `AVAILABLE` — for instance a `RESERVED` or already `DISPOSED` lot — has no defined transition and is rejected with `ERR_INVALID_STATE`.

### 3.2. Registering Agencies and Households

An `AllocationManager` registers each partner pantry as an `Agency`, supplying its `name` and `service_area`, and optionally a `fair_share_weight` and an initial `status`. The `fair_share_weight` is a relative integer weight — higher means a larger slice of each cycle's pool — and defaults to 1, never falling below 1. The `status` is `ACTIVE` or `SUSPENDED`, defaulting to `ACTIVE`; a suspended agency cannot submit or have orders approved. Each agency also carries a computed `lifetime_distributed_lbs`, the running sum of poundage actually handed out across all of its finalized distribution events, initialized to 0. The manager may later adjust an agency through a partial update that can change its `status`, its `fair_share_weight`, or its `service_area`; any such update bumps the agency's `version`.

Households are registered by their agency. An `AgencyCoordinator` registers a `ClientHousehold` under an `agency_id` (which must be the coordinator's own agency, per §2.1), recording the `household_size` — at least one person — and the self-reported `monthly_income_cents`, which must be zero or greater. At registration the system computes the household's `tefap_eligible` flag from its income and size (see §3.3) and sets `certification_status` to `PENDING`. The coordinator may update a household's `household_size` or `monthly_income_cents` later; doing so re-derives `tefap_eligible` and bumps the household's `version`.

### 3.3. TEFAP Eligibility and Certification

A household's eligibility for federal commodity food turns on an income test scaled to household size. The income ceiling is computed as a base amount for a one-person household, increased by a fixed per-person increment for every additional member: the threshold in cents equals 199800 cents for the first person plus 70500 cents for each member beyond the first. (Expressed differently, a one-person household's ceiling is $1,998.00 per month and each additional member raises it by $705.00.) The household is `tefap_eligible` when its `monthly_income_cents` is at or below this threshold; a household whose income lands exactly on the threshold is eligible. This `tefap_eligible` flag is recomputed whenever the household is created and whenever its `household_size` or `monthly_income_cents` changes.

Certification is the auditor's act. A `ComplianceAuditor` certifies a household that is in `PENDING` status, and the outcome branches on eligibility. If the household is `tefap_eligible`, certification moves it from `PENDING` to `CERTIFIED` and stamps the moment of certification onto the household as `certified_at`, read from the logical "current UTC" clock of §2.9 (the same clock the aging sweep measures against), not from wall-clock time. If the household is not `tefap_eligible`, the same certification action moves it from `PENDING` to `DENIED`. In both branches the household's `version` is bumped. A certification does not last forever: when the logical clock advances to or past the point 365 days after `certified_at`, a `CERTIFIED` household ages from `CERTIFIED` to `EXPIRED`, bumping its `version`. An expired certification blocks new TEFAP distribution for that household until it is certified afresh.

### 3.4. Allocation Cycles and the Fair-Share Cap

Fair allocation is organized into cycles. An `AllocationManager` creates an `AllocationCycle` in `DRAFT` status with a `label` and a `total_pool_lbs` — the total poundage the food bank will ration this cycle, which must be strictly positive. While `DRAFT`, the cycle's `total_fair_share_weight` is 0; it is frozen at open. Opening a cycle requires that it currently be `DRAFT` and that at least one `Agency` have `status` `ACTIVE`; the open transition moves it from `DRAFT` to `OPEN`, freezes `total_fair_share_weight` as the sum of `fair_share_weight` over every agency that is `ACTIVE` at that instant, and bumps the cycle's `version`. Only orders drawing from an `OPEN` cycle may be submitted or approved.

Closing a cycle is gated on its children. The close transition moves a cycle from `OPEN` to `CLOSED` and is permitted only when no `AgencyOrder` in the cycle is still in `SUBMITTED` or `APPROVED` status — every order must have resolved to `FULFILLED`, `REJECTED`, or `CANCELLED`. The close bumps the cycle's `version`. A close attempted while an order remains open, or against a cycle not in `OPEN`, is refused as an invalid state transition.

The **fair-share cap** is the heart of fair allocation and is evaluated when an order is approved. An agency's cap in whole pounds is the cycle's `total_pool_lbs` multiplied by the agency's share — its `fair_share_weight` divided by the cycle's frozen `total_fair_share_weight` — with that product rounded down to a whole number of pounds. From this cap the system subtracts the poundage the agency has already drawn this cycle: the sum of `approved_lbs` over the agency's orders in this cycle whose `status` is `APPROVED` or `FULFILLED` (orders that are `SUBMITTED`, `REJECTED`, or `CANCELLED` do not count against the cap). The order's `requested_lbs` may be approved only when it is at or below this remaining cap; an order whose `requested_lbs` would push the agency's drawn poundage strictly above the cap is rejected with `ERR_FAIR_SHARE_EXCEEDED`, while an order landing exactly at the cap is allowed.

### 3.5. Submitting and Approving Orders: FEFO Reservation

An `AgencyCoordinator` submits an `AgencyOrder` against an `OPEN` cycle on behalf of their own agency, naming the `agency_id`, the `allocation_cycle_id`, and a `lines` array. Each entry in `lines` becomes a child `OrderLine` carrying a `food_category` and a `requested_lbs` (strictly positive). The order's `requested_lbs` is computed as the sum of its lines' `requested_lbs`, and its `approved_lbs` starts at 0; the order enters `SUBMITTED`. Submission is refused if the ordering agency's `status` is `SUSPENDED` (`ERR_AGENCY_SUSPENDED`) or if the named cycle is not `OPEN` (`ERR_CYCLE_NOT_OPEN`). Each line begins with `line_status` `PENDING`, a `reserved_lbs` of 0, and a null `reserved_lot_id`.

Approval is where inventory is committed. When an `AllocationManager` approves an order, the order must currently be `SUBMITTED`, its cycle must be `OPEN` (`ERR_CYCLE_NOT_OPEN`), the ordering agency must be `ACTIVE` (`ERR_AGENCY_SUSPENDED`), and the order's `requested_lbs` must fit within the agency's remaining fair-share cap (`ERR_FAIR_SHARE_EXCEEDED`, per §3.4). The approval then runs a **FEFO reservation** for each line: it consumes `AVAILABLE` lots of the line's `food_category` in ascending order of `expiration_date`, breaking ties by `created_at`, reserving poundage until either the line's `requested_lbs` is met or no matching lot remains. As poundage is taken, the line's `reserved_lbs` accumulates, its `reserved_lot_id` is set to the single FEFO-earliest lot it reserved against (the one consumed first), and its `line_status` becomes `RESERVED` when its full request is met or `SHORT` when only part of it could be covered. The order's `approved_lbs` is set to the sum of its lines' `reserved_lbs`, the order moves from `SUBMITTED` to `APPROVED`, and the order's `version` is bumped.

Reservation transitions the inventory itself. A reservation against an `AVAILABLE` lot whose `expiration_date` is in the future and whose `remaining_lbs` is positive moves that lot from `AVAILABLE` to `RESERVED`, decreasing its `remaining_lbs` by the reserved amount and bumping its `version`; if a reservation drains a lot's `remaining_lbs` to 0, the lot transitions from `AVAILABLE` to `DEPLETED` instead, its `remaining_lbs` set to 0, the holding unit's `stored_lbs` recomputed, and its `version` bumped. The approval is OCC-guarded on the FEFO-earliest lot: the manager must supply `expected_lot_version` matching that lot's current `version`, and a mismatch is rejected with `ERR_STALE_LOT_VERSION` at HTTP 412, per §2.7. An order that is not `SUBMITTED` cannot be approved.

A submitted order may instead be **rejected** by an `AllocationManager`: a `SUBMITTED` order moves to `REJECTED`, no reservation runs and no inventory is touched, and the order's `version` is bumped.

### 3.6. Recall, Cancel, and the Conservation Invariant

An approved order is not yet final, and two paths can unwind it. An `AllocationManager` may **recall** an `APPROVED` order back to `SUBMITTED` for revision, provided no `DistributionEvent` for that order has reached `PACKED` or `FINALIZED`. The recall releases every line's reservation: each reserved `InventoryLot` moves from `RESERVED` back to `AVAILABLE` with its `remaining_lbs` restored by exactly the released amount, each line's `reserved_lbs` resets to 0, its `reserved_lot_id` to null, and its `line_status` to `PENDING`; the order's `approved_lbs` resets to 0 and its `version` is bumped. Because the released poundage equals the poundage originally reserved, total lot poundage is conserved across the round trip.

An `AgencyCoordinator` may instead **cancel** their own order. A `SUBMITTED` order cancels straight to `CANCELLED` with nothing to release. An `APPROVED` order may be cancelled only when no `DistributionEvent` for it is `PACKED` or `FINALIZED`; cancelling it releases all reservations exactly as recall does — reserved lots return from `RESERVED` to `AVAILABLE`, `remaining_lbs` is restored, lines reset to `PENDING` with `reserved_lbs` 0 and `reserved_lot_id` null — and the order moves to `CANCELLED` with its `version` bumped. Whenever a reservation is released through recall or cancel, the affected lot's holding unit has its `stored_lbs` recomputed and the lot's `version` bumped. The conservation invariant holds in every case: poundage released equals poundage reserved, so no pound is ever created or destroyed by an unwind.

### 3.7. Distribution Events: Plan, Pack, Finalize, Void

Once an order is approved, its food reaches a household through a `DistributionEvent`. An `AgencyCoordinator` plans an event by linking an `agency_order_id` to a `client_household_id`; the event enters `PLANNED` with its `planned_lbs` at 0. The coordinator must own both the order and the household.

**Packing** prepares the hand-out. Packing a `PLANNED` event requires that its linked `AgencyOrder` be `APPROVED` and its linked `ClientHousehold` be `CERTIFIED`; moreover, if any reserved line of the order draws from a TEFAP-sourced lot, the household must be `tefap_eligible`. A pack attempted when the household is not `CERTIFIED`, or when a TEFAP line is being packed for a household that is not `tefap_eligible`, is rejected with `ERR_HOUSEHOLD_NOT_CERTIFIED`. On a valid pack the event moves from `PLANNED` to `PACKED`, its `planned_lbs` is set to the **forward-looking planned poundage** — the sum of `reserved_lbs` over the order's lines whose `line_status` is `RESERVED` or `SHORT` at pack time, using what the FEFO run actually secured rather than what was requested, so a `SHORT` line contributes only its reserved amount and an already-`PACKED` line is excluded. Only the order's `RESERVED` lines are then marked `PACKED` (a `SHORT` line keeps its `SHORT` `line_status`), and the event's `version` is bumped.

**Finalizing** records reality. Finalizing a `PACKED` event requires the operator-recorded `actual_distributed_lbs`, which must be zero or greater and must not exceed the event's `planned_lbs` — handing out more than was packed is rejected with `ERR_OVER_DISTRIBUTION`. On finalization the system computes `tefap_lbs` (see §3.8), transitions the reserved lots backing the order's `PACKED` lines from `RESERVED` to `DEPLETED` (marking that poundage permanently consumed and bumping each lot's `version`), advances the linked `AgencyOrder` from `APPROVED` to `FULFILLED`, increases the receiving agency's `lifetime_distributed_lbs` by the `actual_distributed_lbs`, and bumps the event's `version`. This is the cascade origin of the system: a single finalize depletes lots, fulfills the order, advances the agency's lifetime ledger, and feeds the cycle's poundage report.

**Voiding** is the event's escape hatch. A `PLANNED` event may be voided with nothing moved — the order's lines remain `RESERVED`. A `PACKED` event may also be voided, which reverts its packing: the order's `PACKED` lines return to `line_status` `RESERVED` and the event's `planned_lbs` resets to 0, conserving poundage without consuming any. Either void moves the event to `VOIDED` and bumps its `version`. A void leaves no poundage permanently consumed.

### 3.8. The TEFAP Split at Finalization

At finalization, the system must attribute how much of the distributed poundage came from federal commodity stock, because TEFAP poundage is reported to grant officers separately. The attribution is a **FEFO waterfall** over the order's `PACKED` lines, walked in ascending order of their reserved lot's `expiration_date`, ties broken by that lot's `created_at`. Starting with the full `actual_distributed_lbs` as the amount remaining to attribute, the system visits each line in turn and allocates to it the smaller of the amount still remaining and that line's `reserved_lbs`; if the line's reserved lot has `source_type` `TEFAP`, the amount allocated to that line is added to the event's `tefap_lbs`. Non-TEFAP lines still consume their share of the waterfall but contribute nothing to `tefap_lbs`. The walk stops once the remaining amount to attribute reaches 0. Each line's allocation is rounded to two decimal places before being summed into `tefap_lbs` — the rounding is applied per line and then totaled, never the other way around.

### 3.9. Poundage Reporting: Planned vs. Distributed Ledgers

The food bank's central audit artifact is the `PoundageReport`, a per-cycle snapshot recomputed on read rather than stored. It references the `allocation_cycle_id` it summarizes and carries four computed totals. The **planned** total, `total_planned_lbs`, is forward-looking: the sum of `planned_lbs` over every distribution event for this cycle's orders that has reached `PACKED` or `FINALIZED`, including events that are packed but not yet finalized. The **distributed** total, `total_distributed_lbs`, is chronological: the sum of `actual_distributed_lbs` over only the cycle's `FINALIZED` events, accumulated in ascending order of when each event was finalized, ties broken by `created_at`; a packed-but-unfinalized event contributes nothing to this total. The TEFAP total, `total_tefap_lbs`, is the sum of `tefap_lbs` over the cycle's `FINALIZED` events. `VOIDED` events are excluded from every total.

The divergence between the two ledgers is the report's headline figure: `shrinkage_lbs` is `total_planned_lbs` minus `total_distributed_lbs`, and it may be negative when more was distributed than was planned. The same underlying events feed both the planned and distributed totals, but because planned counts packed-and-finalized events while distributed counts only finalized ones, the gap is the real-world shrinkage. All four totals are rounded to two decimal places, round half up.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions such as approving, packing, or finalizing, and partial updates — return a `200 OK` status code. The clock-advance capability also returns `200 OK`.

Across endpoints, all validations are evaluated in a fixed priority order: authentication first, then role permission, then agency-scope ownership, then existence of every referenced resource (path ids and body foreign keys, left to right), then request well-formedness and enum-domain checks, then state-transition legality, and finally the domain-specific business rules (cold-chain, household certification, agency standing, cycle openness, capacity, over-distribution, fair-share cap, and lot-version OCC, in that order). The earliest failing check determines the error returned.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cold-storage-units` | Create a cold storage unit | FoodBankOperator |
| GET | `/cold-storage-units/{id}` | Fetch a cold storage unit with live occupancy | FoodBankOperator, AllocationManager, ComplianceAuditor |
| GET | `/cold-storage-units` | List cold storage units (paginated) | FoodBankOperator, AllocationManager, ComplianceAuditor |
| GET | `/cold-storage-units/{id}/inventory-lots` | List inventory lots held in this unit | FoodBankOperator, AllocationManager, ComplianceAuditor |
| POST | `/inventory-lots` | Intake a donation/rescue/TEFAP/purchased lot | FoodBankOperator |
| GET | `/inventory-lots/{id}` | Fetch an inventory lot | FoodBankOperator, AllocationManager, ComplianceAuditor |
| GET | `/inventory-lots` | List inventory lots | FoodBankOperator, AllocationManager, ComplianceAuditor |
| POST | `/inventory-lots/{id}/dispose` | Dispose an available or expired lot (OCC-guarded) | FoodBankOperator |
| GET | `/inventory-lots/{id}/order-lines` | List order lines that reserved against this lot | FoodBankOperator, AllocationManager, ComplianceAuditor |
| POST | `/agencies` | Register a partner agency | AllocationManager |
| GET | `/agencies/{id}` | Fetch an agency with lifetime distribution ledger | FoodBankOperator, AllocationManager, ComplianceAuditor, AgencyCoordinator |
| GET | `/agencies` | List agencies (paginated, filter by status) | FoodBankOperator, AllocationManager, ComplianceAuditor |
| PATCH | `/agencies/{id}` | Update agency standing or fair-share weight | AllocationManager |
| GET | `/agencies/{id}/client-households` | List client households registered by this agency | FoodBankOperator, AllocationManager, ComplianceAuditor, AgencyCoordinator |
| GET | `/agencies/{id}/agency-orders` | List orders placed by this agency | FoodBankOperator, AllocationManager, ComplianceAuditor, AgencyCoordinator |
| POST | `/allocation-cycles` | Create a DRAFT allocation cycle | AllocationManager |
| GET | `/allocation-cycles/{id}` | Fetch an allocation cycle | FoodBankOperator, AllocationManager, ComplianceAuditor, AgencyCoordinator |
| POST | `/allocation-cycles/{id}/open` | Open a cycle; freezes fair-share weight | AllocationManager |
| POST | `/allocation-cycles/{id}/close` | Close a cycle once all orders are resolved | AllocationManager |
| GET | `/allocation-cycles/{id}/agency-orders` | List orders drawing from this cycle | FoodBankOperator, AllocationManager, ComplianceAuditor |
| GET | `/allocation-cycles/{id}/poundage-report` | Return the cycle's poundage report as a 0-or-1 array | FoodBankOperator, AllocationManager, ComplianceAuditor |
| POST | `/agency-orders` | Submit an agency order with its order lines | AgencyCoordinator |
| GET | `/agency-orders/{id}` | Fetch an order with rolled-up poundage | FoodBankOperator, AllocationManager, ComplianceAuditor, AgencyCoordinator |
| GET | `/agency-orders/{id}/order-lines` | List the order's lines with reservation detail | FoodBankOperator, AllocationManager, ComplianceAuditor, AgencyCoordinator |
| POST | `/agency-orders/{id}/approve` | Approve an order: run FEFO reservation (OCC-guarded) | AllocationManager |
| POST | `/agency-orders/{id}/reject` | Reject a submitted order | AllocationManager |
| POST | `/agency-orders/{id}/recall` | Recall an approved order back to SUBMITTED | AllocationManager |
| POST | `/agency-orders/{id}/cancel` | Cancel a submitted or approved order | AgencyCoordinator |
| POST | `/client-households` | Register a client household under an agency | AgencyCoordinator |
| GET | `/client-households/{id}` | Fetch a client household | FoodBankOperator, AllocationManager, ComplianceAuditor, AgencyCoordinator |
| PATCH | `/client-households/{id}` | Update household size or income | AgencyCoordinator |
| POST | `/client-households/{id}/certify` | Certify or deny a household's TEFAP eligibility | ComplianceAuditor |
| POST | `/distribution-events` | Plan a distribution event linking an order to a household | AgencyCoordinator |
| GET | `/distribution-events/{id}` | Fetch a distribution event | FoodBankOperator, AllocationManager, ComplianceAuditor, AgencyCoordinator |
| GET | `/distribution-events` | List distribution events | FoodBankOperator, AllocationManager, ComplianceAuditor, AgencyCoordinator |
| POST | `/distribution-events/{id}/pack` | Pack the event: compute planned poundage, mark lines packed | AgencyCoordinator |
| POST | `/distribution-events/{id}/finalize` | Finalize: record actual poundage, deplete lots, fulfill order | AgencyCoordinator |
| POST | `/distribution-events/{id}/void` | Void a planned or packed event | AgencyCoordinator |
| GET | `/poundage-reports/{allocation_cycle_id}` | Generate the cycle's poundage report | FoodBankOperator, AllocationManager, ComplianceAuditor |
| POST | `/_clock/set_current_utc` | Set the server clock; triggers expiry and certification aging | FoodBankOperator, AllocationManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_AGENCY_SCOPE_VIOLATION` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_COLD_CHAIN_MISMATCH` | 422 |
| `ERR_COLD_STORAGE_CAPACITY_EXCEEDED` | 409 |
| `ERR_HOUSEHOLD_NOT_CERTIFIED` | 409 |
| `ERR_AGENCY_SUSPENDED` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_OVER_DISTRIBUTION` | 422 |
| `ERR_FAIR_SHARE_EXCEEDED` | 409 |
| `ERR_STALE_LOT_VERSION` | 412 |
| `ERR_VALIDATION_PAGINATION` | 422 |
