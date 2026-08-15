# Team Equipment & Uniform Management API — Product Requirements Document

## 1. Introduction

Every competitive season quietly becomes a logistics campaign long before kickoff. Game jerseys in the right sizes run out mid-season, helmets must be sent out for reconditioning and recertification on a fixed cycle, a Saturday game cannot be locked in until Friday's laundry has come back, and every unreturned pair of game pants is money walking out the door. The equipment manager sits at the center of this campaign, balancing finite stock pools against supplier contracts that cap how much of each garment type can ever be ordered, while the team administrator controls the contracts themselves and an outside laundry vendor drives the turnaround cycle between events.

This document specifies the Team Equipment & Uniform Management API, the system of record for that entire operation. It governs size- and spec-level uniform stock pools with reservation and laundry bookkeeping, supplier contracts with per-garment allocation caps and automatic reorder generation when stock crosses a threshold, numbered kit assignment to players, serialized protective gear with certification gating and a reconditioning loop, game-day events with setup checklists and a parallel laundry pipeline, loss and damage claims with a tiered fee schedule, and end-of-season disposition of remaining inventory. All state in the system is evaluated against a controllable logical clock so that expiry, overdue, and age calculations are deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring their capacity. The system recognizes exactly three roles: `EquipmentManager`, the team equipment manager who runs day-to-day inventory, kits, gear, orders, events, claim assessment, and disposition proposals and execution; `TeamAdmin`, the team administrator who owns supplier contracts, disposition approval, claim waivers and reopens, and the logical clock; and `LaundryVendor`, the external laundry vendor who advances laundry cycles and otherwise only reads state.

A request with a missing header or an unrecognized role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the targeted endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). All three roles may call every read endpoint; write privileges are partitioned per the endpoint table in §4, with the laundry-advance operation shared between `EquipmentManager` and `LaundryVendor`.

For all three roles — `EquipmentManager`, `TeamAdmin`, and `LaundryVendor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any resource's `id`; accountability on resources such as claims and gear holdings is expressed through explicit foreign-key fields (for example, `player_id` on a damage claim), not through the caller header.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

The system never consults wall-clock time. Instead, a logical clock governs every time-dependent computation: certification expiry checks at gear issue, laundry overdue evaluation, damage-fee age factors, expected delivery dates on orders, and the result dates stamped on reconditioning jobs. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. An admin-only test-driving capability lets a `TeamAdmin` set the clock to a supplied `to_iso8601` instant (ISO 8601 UTC); once set, the clock holds that value and never falls back to wall-clock time. Operations that compare timestamps or dates against "now" always read this clock.

### 2.5. Common Resource Properties

Every resource in this system — players, inventory pools, supplier contracts, kit orders, kit assignments, gear items, reconditioning jobs, game events, damage claims, and disposition cases — carries a uniform set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, uniquely identifying the resource.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): starts at its initial value on creation and increments by exactly 1 on every mutation of the resource, including system-driven cascades that touch the resource. This field backs the optimistic concurrency guards described in §2.8.

### 2.6. Stock Conservation and the Availability Ledger

Uniform stock is tracked per **InventoryPool** — a size-and-garment bucket for one season — using three counters: `stock_on_hand` (physical units present), `reserved_quantity` (units held by kit assignments awaiting issue), and `in_laundry_quantity` (units out in an event laundry cycle). A fourth, computed quantity, `available_quantity`, is always the stock on hand minus the reserved units minus the in-laundry units. This is a conservation invariant: at every moment, the stock on hand of a pool equals the sum of its available, reserved, and in-laundry quantities, and every flow in the system preserves it.

Every mutation that touches any of the three counters — kit reservation, issue, release, or return; event completion loads; laundry restock; stock recounts; order receiving; disposition write-off — immediately runs an availability reconciliation on the touched pool, recomputes `available_quantity`, refreshes the pool's `updated_at`, and increments the pool's `version` by 1. Immediately after each reconciliation, the replenishment threshold check described in §3.2 runs against the pool. These value mutations never change a pool's `status`; the only transition out of `ACTIVE` is closure by disposition execution.

### 2.7. Monetary Precision and Pinned Rounding

All money in the system is integer cents — prices, fees, subtotals, totals, and proceeds are never fractional. Where a computation produces a fraction of a cent, the rounding rule is stated alongside the computation: order pricing rounds half-up to a whole cent at each pinned step (§3.3), and damage fees truncate toward zero to a whole cent before their clamps are applied (§3.7). Percentage inputs such as `contract_rebate_pct` and `line_discount_pct` are fractions between 0 and 1 inclusive.

### 2.8. Optimistic Concurrency Control

Exactly two write operations carry an optimistic concurrency guard; no other endpoint accepts a version field.

A stock recount posted against an inventory pool must carry `expected_pool_version`, holding the pool `version` the client last observed. If the pool's version has advanced beyond that value — because another adjustment, a reservation, an issue, a receive, or a laundry movement has since landed — the recount is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412) rather than silently overwriting a newer count.

A contract amendment must carry `expected_supplier_contract_version`, holding the contract `version` the client last observed. If the contract's version has advanced beyond that value — for example because activation or a prior amendment has since landed — the amendment is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), so allocation caps are never rebased on a superseded read.

### 2.9. The Validation Cascade

Incoming requests are checked against a fixed priority cascade so that an earlier failure always masks a later one; the client sees the first failing category, not an arbitrary one. The order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is recognized (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Authorization** — the caller's role is permitted on the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. **Request schema** — required fields are present and types, enums, and ranges are valid: `jersey_number` an integer from 0 to 99 inclusive, quantities strictly positive, percentage fields within 0 to 1 inclusive, dates parseable. A damage claim must carry exactly one of `kit_assignment_id` or `gear_item_id` (violations answer `ERR_INVALID_CLAIM_SUBJECT`), and a memorabilia-sale disposition must carry `unit_price_cents`; all other schema failures answer `ERR_INVALID_REQUEST`.
4. **Existence** — referenced resources exist, checked left-to-right across the path identifiers first and then the identifiers referenced in the body (`player_id`, pool ids, `supplier_contract_id`, `item_id`, and so on), each surfacing its specific not-found error such as `ERR_PLAYER_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_KIT_ASSIGNMENT_NOT_FOUND`, `ERR_GEAR_ITEM_NOT_FOUND`, `ERR_RECONDITIONING_JOB_NOT_FOUND`, `ERR_GAME_EVENT_NOT_FOUND`, `ERR_DAMAGE_CLAIM_NOT_FOUND`, or `ERR_DISPOSITION_CASE_NOT_FOUND`. For kit order lines, the pool is located by the contract's season together with the line's garment type and size code, and a line with no matching pool fails here with `ERR_POOL_NOT_FOUND`.
5. **State preconditions** — the target resources sit in the states the operation requires (the 409 state-error family: `ERR_CONTRACT_NOT_ACTIVE`, `ERR_POOL_CLOSED`, `ERR_ORDER_NOT_OPEN`, `ERR_KIT_NOT_RESERVED`, `ERR_KIT_NOT_ISSUED`, `ERR_GEAR_NOT_IN_STOCK`, `ERR_GEAR_NOT_ISSUED`, `ERR_JOB_NOT_OPEN`, `ERR_EVENT_NOT_SCHEDULED`, `ERR_EVENT_NOT_LOCKED`, `ERR_LAUNDRY_INVALID_TRANSITION`, `ERR_LAUNDRY_NOT_READY`, `ERR_CHECKLIST_INCOMPLETE`, `ERR_CLAIM_NOT_REPORTED`, `ERR_CLAIM_NOT_ASSESSED`, `ERR_DISPOSITION_NOT_PROPOSED`, `ERR_DISPOSITION_NOT_APPROVED`, `ERR_PLAYER_NOT_ACTIVE`, `ERR_PLAYER_HAS_ISSUED_KITS`, `ERR_OPEN_ORDERS_EXIST`, `ERR_INVALID_STATE`).
6. **Protective-gear safety** — certification and condition gates on gear issue (`ERR_GEAR_CERTIFICATION_EXPIRED`, `ERR_GEAR_CONDITION_NOT_ISSUABLE`).
7. **Uniqueness and structural constraints** — jersey numbers, asset tags, pool identity, one-issued-item-per-type, contract garment coverage, claim-subject ownership, and kit-pool season alignment (`ERR_JERSEY_NUMBER_TAKEN`, `ERR_ASSET_TAG_TAKEN`, `ERR_POOL_ALREADY_EXISTS`, `ERR_PLAYER_GEAR_LIMIT_REACHED`, `ERR_GARMENT_NOT_COVERED_BY_CONTRACT`, `ERR_CLAIM_PLAYER_MISMATCH`, `ERR_POOL_SEASON_MISMATCH`).
8. **Temporal windows** — event spacing, reconditioning provider capacity, and the alternate-kit rotation cap (`ERR_EVENT_SPACING_VIOLATION`, `ERR_VENDOR_CAPACITY_EXCEEDED`, `ERR_ALTERNATE_KIT_LIMIT_REACHED`).
9. **Capacity and fiscal limits** — allocation caps, pool sufficiency, recount floors, amendment floors, and receive ceilings (`ERR_ALLOCATION_CAP_EXCEEDED`, `ERR_POOL_INSUFFICIENT_STOCK`, `ERR_STOCK_BELOW_COMMITMENTS`, `ERR_AMENDMENT_BELOW_COMMITTED`, `ERR_RECEIVE_EXCEEDS_OUTSTANDING`). Note that `ERR_ALLOCATION_CAP_EXCEEDED` is answered with HTTP 402, while every other member of this family uses HTTP 409.

## 3. Business Logic & Workflows

### 3.1. Roster Management and Player Status

An `EquipmentManager` builds the roster by creating players with a `full_name` and a `position_group` of `OFFENSE`, `DEFENSE`, or `SPECIAL_TEAMS`. Every player begins life in `ACTIVE` status.

From there, an `EquipmentManager` steers a player through a small status machine by patching the player's `status`. An `ACTIVE` player can be suspended, moving `ACTIVE → SUSPENDED`; the request is rejected with `ERR_INVALID_STATE` if the player is in any other state. A suspended player can be reinstated, moving `SUSPENDED → ACTIVE`. Release is terminal: from either `ACTIVE` or `SUSPENDED`, a player moves to `RELEASED`, but only while the player holds no kit assignment in `ISSUED` status — otherwise the release is refused with `ERR_PLAYER_HAS_ISSUED_KITS`. Releasing a player cascades to that player's kit assignments still in `RESERVED`: each one moves to `RELEASED` as well, and the reservations are restored to the pools (each pool's `reserved_quantity` drops by one, followed by the usual reconciliation and threshold check in the increase direction, which may clear a pool's `reorder_blocked` flag). Every player transition increments the player's `version` by 1.

Player status matters downstream: only an `ACTIVE` player may be issued a kit or a gear item, with violations answered by `ERR_PLAYER_NOT_ACTIVE`.

### 3.2. Building Season Stock: Pools, Reservations, and Automatic Reorder

Stockkeeping starts when an `EquipmentManager` creates an inventory pool for a season: a `season_label` such as `2026-FALL`, a `garment_type` of `GAME_JERSEY`, `GAME_PANTS`, `PRACTICE_JERSEY`, `PRACTICE_PANTS`, or `SOCKS`, a `size_code` such as `M` or `2XL`, an opening `stock_on_hand` (zero or more), a `reorder_point` (zero or more), and a `reorder_batch_size` (strictly positive). The triple of season, garment type, and size code identifies a pool uniquely — a duplicate is rejected with `ERR_POOL_ALREADY_EXISTS`. New pools start `ACTIVE` with both `reserved_quantity` and `in_laundry_quantity` at zero, so the initial `available_quantity` equals the opening stock. The catalog of pools can be listed with filters on `season_label`, `garment_type`, and `status`.

Physical recounts are an explicit operation rather than an edit: an `EquipmentManager` posts a `new_stock_on_hand` absolute value, optionally annotated with a `reason`, together with the OCC guard described in §2.8. The recounted value must be at least the sum of the pool's reserved and in-laundry units, since those units physically exist elsewhere; a lower value is rejected with `ERR_STOCK_BELOW_COMMITMENTS`. A recount against a `CLOSED` pool fails with `ERR_POOL_CLOSED`. A successful recount sets `stock_on_hand` to the new value, runs the reconciliation and threshold check in whichever direction applies, and bumps the pool's `version`.

**Automatic replenishment.** Whenever a reconciliation in the decrease direction pushes a pool's available quantity across its reorder point — the available quantity was strictly above `reorder_point` before the mutation and lands at or below it afterwards — the replenishment engine fires. This crossing test is edge-triggered: an available quantity that merely moves around at or below the point does not re-fire it, and increase-direction movements never create orders at all.

When the engine fires, it first measures the inbound pipeline for the pool: the total line quantities on kit orders in `SUBMITTED` or `PARTIALLY_RECEIVED` status whose season (derived through their contract), garment type, and size code match the pool. Fully received orders are excluded because their stock has already landed; cancelled orders are excluded as well. It then selects a supplier contract among those that are `ACTIVE`, cover the pool's season, and list the pool's garment type in their `allocation_caps`, ranking candidates by creation timestamp ascending and breaking ties by `vendor_name` ascending. If no contract qualifies, the pool's `reorder_blocked` flag is set to true and no order is created.

On the selected contract, the remaining allocation for the garment type is the cap minus the units already committed (§3.3). The authoritative reorder quantity is the forward-looking variant: take the shortfall — the reorder point minus the new available quantity minus the inbound open units — and add the pool's `reorder_batch_size`. A diagnostic on-hand-only variant exists for projection reads; it ignores inbound open orders and therefore yields an equal or larger quantity for identical pool state, but it never creates orders. The requested quantity is the smaller of the raw quantity and the remaining allocation. If that quantity is zero or negative, `reorder_blocked` is set to true and no order is created. Otherwise the system itself creates a kit order with `source` `AUTO_REORDER` in `SUBMITTED` status, containing a single line with the pool's garment type and size code, the computed quantity, a `unit_price_cents` of zero, and a `line_discount_pct` of zero; the committed units for that garment type on the selected contract rise by the ordered quantity. A blocked pool recovers automatically: on any later increase-direction reconciliation that lifts its available quantity back above the reorder point, `reorder_blocked` flips back to false.

### 3.3. Supplier Contracts and Kit Ordering

A `TeamAdmin` sets up purchasing by creating a supplier contract: a `vendor_name`, the `season_label` it covers, a `start_on` and `end_on` date (each `YYYY-MM-DD`), the `allocation_caps` — an array of entries pairing a `garment_type` with a `max_units` ceiling — a strictly positive `default_lead_time_days`, and an optional `contract_rebate_pct` defaulting to 0. A new contract is in `DRAFT`, with committed units zeroed for every capped garment type.

Activation moves a contract `DRAFT → ACTIVE`; a contract in any other state answers activation with `ERR_CONTRACT_NOT_ACTIVE`. Activation additionally requires a non-empty `allocation_caps` array and a `start_on` no later than `end_on`. While `ACTIVE`, the contract's caps can be amended — the amendment payload carries a replacement `allocation_caps` array plus the `expected_supplier_contract_version` guard of §2.8 — but no amended cap may fall below the units already committed for that garment type, on pain of `ERR_AMENDMENT_BELOW_COMMITTED`. Amendments keep the contract `ACTIVE` and increment its `version`. Closing a contract moves it `ACTIVE → CLOSED` and is refused with `ERR_OPEN_ORDERS_EXIST` while any of its orders remains `SUBMITTED` or `PARTIALLY_RECEIVED`. Activation, amendment, and closure each increment the contract's `version` by 1.

**Committed units are derived, never stored.** A contract's `units_committed` array carries one entry per capped garment type, pairing the `garment_type` with its `committed_units` total: the sum of line quantities for that garment type across the contract's kit orders in `SUBMITTED`, `PARTIALLY_RECEIVED`, or `RECEIVED` status, with cancelled orders contributing only their already-received quantities (the outstanding portion is released at cancellation). The remaining allocation is the cap minus the committed total, and the two always sum to the cap. Because the figure is derived on read, creating or cancelling an order does not mutate a stored contract field and therefore does not increment the contract's `version`.

An `EquipmentManager` buys stock by creating a kit order against a contract, supplying the `supplier_contract_id` and an array of `lines`, each line naming a `garment_type`, a `size_code`, a `quantity`, a `unit_price_cents`, and an optional `line_discount_pct` defaulting to 0. The contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE` otherwise). Every line's garment type must appear in the contract's caps, otherwise `ERR_GARMENT_NOT_COVERED_BY_CONTRACT`. Per garment type, the ordered quantity may equal but never exceed the remaining allocation; overshooting is rejected with `ERR_ALLOCATION_CAP_EXCEEDED` (HTTP 402, the sole fiscal error on that status). Each line is also resolved against the pools of the contract's season by garment type and size code, and a line with no matching pool fails with `ERR_POOL_NOT_FOUND`. A created order lands in `SUBMITTED` with `source` `MANUAL`, and its `expected_delivery_on` is computed as the submission date on the logical clock plus the contract's `default_lead_time_days`.

**Order pricing follows a pinned rounding order.** First, each line's total is its `unit_price_cents` multiplied by its `quantity`, multiplied by one minus its `line_discount_pct`, rounded half-up to a whole cent. Second, `subtotal_cents` is the sum of those per-line totals. Third, `total_cents` is the subtotal multiplied by one minus the contract's `contract_rebate_pct`, again rounded half-up to a whole cent. Summing the unrounded line values and rounding once at the end is a different, non-authoritative variant that can drift by one or more cents; only the pinned per-line-then-sum-then-rebate order is correct.

Receiving is incremental. An `EquipmentManager` posts `received_lines` — each naming a `garment_type`, a `size_code`, and a `received_quantity` — against an order in `SUBMITTED` or `PARTIALLY_RECEIVED` status (`ERR_ORDER_NOT_OPEN` otherwise). Per line, the received quantity may not exceed what is still outstanding — ordered minus already received — or the call fails with `ERR_RECEIVE_EXCEEDS_OUTSTANDING`. Each received line increases the matching pool's `stock_on_hand` by the received quantity, followed by reconciliation and the threshold check in the increase direction (which may clear `reorder_blocked`); committed units on the contract do not change, because they already counted the full line from submission. The order moves to `PARTIALLY_RECEIVED` while any line remains outstanding and to `RECEIVED` once every line is fully received; the accumulated receipts are visible on the order's `received_lines`, and each receive call increments the order's `version`. Cancelling an open order — again only from `SUBMITTED` or `PARTIALLY_RECEIVED`, else `ERR_ORDER_NOT_OPEN` — moves it to `CANCELLED` and releases the outstanding (ordered minus received) quantities from the contract's committed units for each garment type; received quantities stay committed. Orders can be listed filtered by `supplier_contract_id`, `status`, or `source`.

### 3.4. Kit Assignment: Numbers, Issue, and Return

Kit assignment turns anonymous stock into a player's numbered uniform. An `EquipmentManager` reserves a kit by supplying the `player_id`, the `season_label`, a `jersey_number` between 0 and 99 inclusive, and the two pools the garments come from: `jersey_pool_id` and `pants_pool_id`. Both pools must exist (`ERR_POOL_NOT_FOUND`), must belong to the kit's season (`ERR_POOL_SEASON_MISMATCH`), and must be `ACTIVE` (`ERR_POOL_CLOSED`). Within a season, a jersey number may be held by at most one kit assignment in `RESERVED` or `ISSUED` status; a clash is rejected with `ERR_JERSEY_NUMBER_TAKEN`. Reserving requires at least one available unit in each pool (`ERR_POOL_INSUFFICIENT_STOCK`), and it raises each pool's `reserved_quantity` by one — a decrease-direction reconciliation, so it can fire the replenishment engine of §3.2. A fresh assignment sits in `RESERVED`. Assignments can be listed filtered by `player_id`, `jersey_pool_id`, `pants_pool_id`, `season_label`, or `status`.

Issuing moves a kit `RESERVED → ISSUED`. The kit must currently be `RESERVED` (`ERR_KIT_NOT_RESERVED`), the player must be `ACTIVE` (`ERR_PLAYER_NOT_ACTIVE`), and both pools must still be `ACTIVE` (`ERR_POOL_CLOSED`). Issue converts the reservations into physical outflow: each pool's `reserved_quantity` and `stock_on_hand` each drop by one, the reconciliation and threshold check run in the decrease direction, and the assignment's `issued_at` is stamped with the logical clock. Two release paths exist for an unissued kit: an explicit release by an `EquipmentManager`, valid only from `RESERVED` (`ERR_KIT_NOT_RESERVED`), which decrements each pool's `reserved_quantity` by one, stamps `closed_at`, frees the jersey number for the season, and lands the kit in `RELEASED`; and the automatic cascade on player release described in §3.1. Both run the increase-direction reconciliation that can clear `reorder_blocked`.

Returning moves an issued kit `ISSUED → RETURNED` (`ERR_KIT_NOT_ISSUED` from any other state), adding one unit of `stock_on_hand` back to each pool, stamping `closed_at`, and freeing the number. Every issue, release, and return increments the assignment's `version` by 1. Two further terminal outcomes arrive not through manager action but through damage claims: a lost kit settles into `LOST` — `closed_at` stamped, number freed, and no pool restock because the garments were already written out of stock at issue — while a damaged kit settles into `RETURNED` with the same restock cascade as a manager return (§3.7).

### 3.5. Protective Gear: Certification and the Reconditioning Loop

Protective gear is tracked as serialized items. An `EquipmentManager` registers a gear item with a unique `asset_tag` (duplicates answer `ERR_ASSET_TAG_TAKEN`), an `item_type` of `HELMET`, `SHOULDER_PADS`, `GIRDLE_PADS`, or `KNEE_BRACE`, a free-form `size_spec` such as `HELMET-L`, and the `acquired_on` acquisition date, which later drives the age factor in damage fees. A `condition_grade` may be supplied and defaults to `A`; grades run `A`, `B`, `C`, and `F`, where `F` marks a failed, non-issuable item. A `certification_expires_on` timestamp may be supplied; its absence marks the item uncertified. New items are `IN_STOCK` with no holder. The gear inventory can be listed filtered by `current_holder_id`, `item_type`, or `status`.

Issuing a gear item to a player — the payload carries the `player_id` — is the most heavily gated operation in the system, and its checks follow the cascade of §2.9: the item must be `IN_STOCK` (`ERR_GEAR_NOT_IN_STOCK`), the player must be `ACTIVE` (`ERR_PLAYER_NOT_ACTIVE`); then the safety gates — for `HELMET` and `SHOULDER_PADS`, `certification_expires_on` must be present and strictly later than the logical clock's now (`ERR_GEAR_CERTIFICATION_EXPIRED`), and no item graded `F` may ever be issued (`ERR_GEAR_CONDITION_NOT_ISSUABLE`); finally, a player may hold at most one issued item of each `item_type` (`ERR_PLAYER_GEAR_LIMIT_REACHED`). Issue sets the item's `current_holder_id` to the player and increments its `version`. A return — valid only from `ISSUED` (`ERR_GEAR_NOT_ISSUED`) — moves the item back to `IN_STOCK` and clears the holder. An in-stock item can be retired outright (`ERR_GEAR_NOT_IN_STOCK` otherwise), landing in terminal `RETIRED`; a lost item reaches `RETIRED` through claim settlement instead, with its holder cleared (§3.7).

**The reconditioning cycle** keeps certification current. Sending an item out requires the item to be `IN_STOCK` (`ERR_GEAR_NOT_IN_STOCK`) and names the `provider_name` and the `sent_on` date. Each open job occupies a half-open window covering the send date up to but not including its `due_back_on`, which is exactly 45 days after `sent_on`. Two jobs for the same provider overlap when the new job's send date falls before the existing job's due-back date and the existing job's send date falls before the new job's due-back date; a provider may sustain at most two overlapping open jobs, so creation is rejected with `ERR_VENDOR_CAPACITY_EXCEEDED` when two open jobs for that `provider_name` already overlap the new window. Individual pairwise overlaps beneath that cap are tolerated — the constraint is aggregate capacity, not mutual exclusion. A created job is `OUT`, and the item moves to `OUT_FOR_RECONDITIONING`. Jobs can be listed filtered by `item_id`, `provider_name`, or `status`.

Recording a result closes the loop and is valid only while the job is `OUT` (`ERR_JOB_NOT_OPEN`). The payload carries an `outcome` of `PASSED` or `FAILED`; a pass must also carry a `result_grade` of `A`, `B`, or `C` (a missing or invalid grade is a schema failure, `ERR_INVALID_REQUEST`). On a pass, the job's `result_recorded_on` is stamped with the logical clock's date, its `certification_valid_until` is computed as that date plus 365 days, and the item returns to `IN_STOCK` with its `condition_grade` set to the result grade and its `certification_expires_on` set to that validity date mapped to a timestamp at midnight UTC. On a failure, `result_recorded_on` is stamped the same way, and the item returns to `IN_STOCK` graded `F` with its prior certification untouched. Either outcome increments the job's `version`.

### 3.6. Game Day: Events, Checklists, and the Laundry Turnaround

Scheduling a game event takes a `season_label`, an `opponent_name`, a `kickoff_at` timestamp, a `designated_kit` of `HOME`, `AWAY`, or `ALTERNATE`, and an optional seeded `checklist` — an array of sideline setup entries, each with an `item_ref`, a human-readable `label`, and a `required` flag. Two calendar rules guard creation. Within a season, the new kickoff must sit at least 48 hours away from the kickoff of every other non-cancelled event in that season; exactly 48 hours apart is allowed, while one second less is rejected with `ERR_EVENT_SPACING_VIOLATION`. And a season supports at most three alternate-kit games: an `ALTERNATE` designation is accepted only while fewer than three non-cancelled same-season events carry it — the third succeeds when two exist, the attempt with three already present fails with `ERR_ALTERNATE_KIT_LIMIT_REACHED` — and cancelling an event frees its slot. A new event is `SCHEDULED`, its parallel `laundry_status` dimension starts at `NOT_STARTED`, and every checklist item starts `PENDING`. Checklist items are worked off one at a time by an `EquipmentManager`, marking the named item `DONE` or `NA` per the posted `outcome`.

Before kickoff the kit must be locked, moving the event `SCHEDULED → KIT_LOCKED` (`ERR_EVENT_NOT_SCHEDULED` from any other state). Locking enforces the laundry turnaround gate: if any other same-season event is already `COMPLETED` with its laundry still `COLLECTING` or `IN_WASH`, the lock is refused with `ERR_LAUNDRY_NOT_READY` — the sideline cannot commit to a kit while the previous game's uniforms are still in the wash pipeline.

Completing an event — valid only from `KIT_LOCKED` (`ERR_EVENT_NOT_LOCKED`) — first requires that every checklist item flagged `required` has left `PENDING` behind (`ERR_CHECKLIST_INCOMPLETE`). The completion payload carries the `laundry_load`, an array of entries pairing a `pool_id` with a `quantity`. Each load line must reference an existing pool (`ERR_POOL_NOT_FOUND`) that is still `ACTIVE` (`ERR_POOL_CLOSED`) and holds at least the requested available units (`ERR_POOL_INSUFFICIENT_STOCK`). Completion then moves each line's quantity out of `stock_on_hand` and into `in_laundry_quantity` on its pool, records the load on the event, sets `laundry_status` to `COLLECTING` when the load is non-empty (an empty load leaves it `NOT_STARTED`), and — with a non-empty load — fixes `laundry_due_at` at exactly 48 hours after `kickoff_at`. Each touched pool's reconciliation and threshold check runs in the decrease direction, so an event completion can itself mint an `AUTO_REORDER` order and commit contract allocation (§3.2, §3.3). Cancelling an event is permitted from `SCHEDULED` or `KIT_LOCKED` (`ERR_EVENT_NOT_SCHEDULED` otherwise); it moves the event to `CANCELLED`, converts every still-`PENDING` checklist item to `NA`, and releases the alternate-kit slot if one was held. Lock, completion, and cancellation each increment the event's `version`.

The laundry cycle is a parallel state dimension advanced one step per call — `COLLECTING → IN_WASH → READY → CLOSED` — by either the `LaundryVendor` or the `EquipmentManager`. A step attempted from `NOT_STARTED` or `CLOSED` is rejected with `ERR_LAUNDRY_INVALID_TRANSITION`. The step into `READY` is the restock: each load line's quantity moves back from `in_laundry_quantity` into `stock_on_hand` on its pool, followed by reconciliation and the threshold check in the increase direction, which may clear a pool's `reorder_blocked`. On every read of an event, `laundry_overdue` reports whether the logical clock is strictly later than `laundry_due_at` while the cycle still sits in `COLLECTING` or `IN_WASH`.

### 3.7. Loss and Damage Accountability

When a uniform or a piece of gear goes missing or comes back broken, an `EquipmentManager` files a damage claim naming the accountable `player_id`, a `claim_type` of `LOST` or `DAMAGED`, the manager-entered replacement value `base_value_cents` (strictly positive), an optional free-text `description`, and exactly one subject: a `kit_assignment_id` or a `gear_item_id` — supplying both or neither fails schema validation with `ERR_INVALID_CLAIM_SUBJECT`. The subject must exist (`ERR_KIT_ASSIGNMENT_NOT_FOUND` or `ERR_GEAR_ITEM_NOT_FOUND`), must currently be `ISSUED` (a kit subject answers `ERR_KIT_NOT_ISSUED`, a gear subject `ERR_GEAR_NOT_ISSUED`), and must belong to the named player — the kit through its `player_id`, the gear through its `current_holder_id` — otherwise `ERR_CLAIM_PLAYER_MISMATCH`. A fresh claim is `REPORTED` and immediately carries a `provisional_fee_cents` estimate computed with the replacement variant below. Claims can be listed filtered by `player_id`, `kit_assignment_id`, `gear_item_id`, or `status`.

**The fee schedule has two variants sharing one skeleton.** The depreciated variant multiplies the base value by a condition factor — grade `A` contributes 1.00, `B` 0.80, `C` 0.60, `F` 0.25 — and by an age factor derived from the days between the subject's acquired date and the logical clock's date: the acquired date is the kit assignment's creation date for a kit subject and the gear item's `acquired_on` for a gear subject; the factor is 1.0 when the age is at most 365 days, 0.7 when the age falls between 366 and 730 days inclusive, and 0.4 beyond 730 days. The product is truncated toward zero to a whole cent, then raised to a floor of 5,000 cents where it falls short and capped at a ceiling of 50,000 cents. Evaluation always proceeds in that fixed order: factor lookup, multiplication, deductible floor, cap. The replacement variant — used for every provisional estimate at report time and for `LOST` claims at assessment — forces both factors to 1.0, so with identical inputs it yields a fee greater than or equal to the depreciated variant whenever the grade is below `A` or the age exceeds 365 days.

Assessment is performed by an `EquipmentManager` on a `REPORTED` claim (`ERR_CLAIM_NOT_REPORTED` otherwise) and records the assessed `condition_grade` supplied in the payload. The `assessed_fee_cents` is then computed with the variant selected by `claim_type`: replacement for `LOST`, depreciated — using the assessed grade — for `DAMAGED`. Assessment moves the claim `REPORTED → ASSESSED` and increments its `version`.

From `ASSESSED`, three resolutions exist, all rejected with `ERR_CLAIM_NOT_ASSESSED` from any other state. An `EquipmentManager` settles the claim: `final_fee_cents` takes the assessed fee, the claim lands in `SETTLED`, and the subject mutates per type — a lost kit's assignment moves to `LOST` (number freed, `closed_at` stamped, no restock), lost gear moves to `RETIRED` with its holder cleared, a damaged kit's assignment moves to `RETURNED` with the full pool-restock cascade of §3.4 (which may clear `reorder_blocked`), and damaged gear returns to `IN_STOCK` wearing the assessed `condition_grade`. A `TeamAdmin` may instead waive the claim: the fee is zeroed in `final_fee_cents`, the claim lands in `WAIVED`, and the subject undergoes exactly the same mutations as a settlement. A `TeamAdmin` may also reopen the claim, moving it back to `REPORTED` with `assessed_fee_cents` and `condition_grade` reset to null, ready for a fresh assessment. Each resolution increments the claim's `version`.

### 3.8. End-of-Season Disposition

When a season closes, remaining stock is dispositioned rather than abandoned. An `EquipmentManager` proposes a disposition case with a `season_label`, a `garment_type`, an optional `size_code` filter (omitting it scopes the case to every size of that garment), a `method` of `RETURN_TO_STOCK`, `DONATE`, `MEMORABILIA_SALE`, or `DISCARD`, and — for a memorabilia sale — a `unit_price_cents` per-unit price, whose absence fails schema validation with `ERR_INVALID_REQUEST`. A new case is `PROPOSED`.

A `TeamAdmin` then adjudicates. Approval — valid only from `PROPOSED` (`ERR_DISPOSITION_NOT_PROPOSED`) — snapshots the scope into `affected_pool_ids`: every `ACTIVE` pool matching the case's season and garment type, narrowed to the size code when one was given. Rejection from the same state lands the case in terminal `REJECTED`. Both increment the case's `version`.

Execution is the `EquipmentManager`'s act on an `APPROVED` case (`ERR_DISPOSITION_NOT_APPROVED` otherwise). The snapshot must be non-empty (`ERR_DISPOSITION_SCOPE_EMPTY`), and every affected pool must stand clear of commitments — zero reserved and zero in-laundry units — or the execution halts with `ERR_POOL_HAS_ACTIVE_COMMITMENTS`. What happens next depends on the method. A `RETURN_TO_STOCK` execution leaves the pools untouched and still `ACTIVE`, recording zero `units_disposed` and zero `proceeds_cents`. `DONATE` and `DISCARD` write each affected pool's `stock_on_hand` off to zero — the total counted into `units_disposed` — and close the pools (`ACTIVE → CLOSED`), with zero proceeds. `MEMORABILIA_SALE` performs the same write-off and closure, but records `proceeds_cents` as the disposed units multiplied by the case's `unit_price_cents`. Whichever method ran, the case itself lands in terminal `EXECUTED`, and execution increments the case's `version`. Pool closure is exclusively a system act driven by disposition execution; no direct transition exists.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition and action posts — return `200 OK`. All resources are served at the root of the API; the table below is a summary only, and the full request and response semantics for each operation are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/players` | Create a roster player | EquipmentManager |
| GET | `/players/{playerId}` | Get a player | Any |
| PATCH | `/players/{playerId}` | Transition player status (ACTIVE ↔ SUSPENDED, → RELEASED) | EquipmentManager |
| POST | `/inventory-pools` | Create a size/spec uniform stock pool for a season | EquipmentManager |
| GET | `/inventory-pools` | List pools with filters and pagination | Any |
| GET | `/inventory-pools/{poolId}` | Get a pool | Any |
| POST | `/inventory-pools/{poolId}/stock-adjustments` | Absolute stock recount with OCC guard | EquipmentManager |
| POST | `/supplier-contracts` | Create a supplier contract with product allocation caps | TeamAdmin |
| GET | `/supplier-contracts/{contractId}` | Get a contract | Any |
| POST | `/supplier-contracts/{contractId}/activate` | Activate a DRAFT contract | TeamAdmin |
| POST | `/supplier-contracts/{contractId}/amendments` | Amend allocation caps on an ACTIVE contract with OCC guard | TeamAdmin |
| POST | `/supplier-contracts/{contractId}/close` | Close an ACTIVE contract (no open orders) | TeamAdmin |
| POST | `/kit-orders` | Create and submit a uniform order against a contract | EquipmentManager |
| GET | `/kit-orders` | List orders with filters and pagination | Any |
| GET | `/kit-orders/{orderId}` | Get an order | Any |
| POST | `/kit-orders/{orderId}/receive` | Receive (fully or partially) order lines into pools | EquipmentManager |
| POST | `/kit-orders/{orderId}/cancel` | Cancel an open order, releasing outstanding allocation | EquipmentManager |
| POST | `/kit-assignments` | Reserve a numbered season kit for a player from jersey/pants pools | EquipmentManager |
| GET | `/kit-assignments` | List kit assignments with filters and pagination | Any |
| GET | `/kit-assignments/{assignmentId}` | Get a kit assignment | Any |
| POST | `/kit-assignments/{assignmentId}/issue` | Issue a reserved kit to its player | EquipmentManager |
| POST | `/kit-assignments/{assignmentId}/release` | Release a reserved (unissued) kit | EquipmentManager |
| POST | `/kit-assignments/{assignmentId}/return` | Return an issued kit to stock | EquipmentManager |
| POST | `/gear-items` | Register a serialized protective gear item | EquipmentManager |
| GET | `/gear-items` | List gear items with filters and pagination | Any |
| GET | `/gear-items/{itemId}` | Get a gear item | Any |
| POST | `/gear-items/{itemId}/issue` | Issue a gear item to a player (safety-gated) | EquipmentManager |
| POST | `/gear-items/{itemId}/return` | Return an issued gear item to stock | EquipmentManager |
| POST | `/gear-items/{itemId}/retire` | Retire an in-stock gear item | EquipmentManager |
| POST | `/reconditioning-jobs` | Send an in-stock gear item out for reconditioning/recertification | EquipmentManager |
| GET | `/reconditioning-jobs` | List reconditioning jobs with filters and pagination | Any |
| GET | `/reconditioning-jobs/{jobId}` | Get a reconditioning job | Any |
| POST | `/reconditioning-jobs/{jobId}/record-result` | Record a PASSED (with grade) or FAILED outcome | EquipmentManager |
| POST | `/game-events` | Schedule a game event with kit designation and optional seeded checklist | EquipmentManager |
| GET | `/game-events/{eventId}` | Get a game event (checklist, laundry fields, computed overdue) | Any |
| POST | `/game-events/{eventId}/lock-kit` | Lock the kit for the event (turnaround gate on prior laundry) | EquipmentManager |
| POST | `/game-events/{eventId}/complete` | Complete the event and send the sideline load to laundry | EquipmentManager |
| POST | `/game-events/{eventId}/cancel` | Cancel a scheduled or kit-locked event | EquipmentManager |
| POST | `/game-events/{eventId}/laundry-advance` | Advance laundry one step: COLLECTING → IN_WASH → READY → CLOSED | LaundryVendor, EquipmentManager |
| POST | `/game-events/{eventId}/checklist/{itemRef}/complete` | Mark a checklist item DONE or NA | EquipmentManager |
| POST | `/damage-claims` | Report a loss/damage claim against a player's issued kit or gear | EquipmentManager |
| GET | `/damage-claims` | List damage claims with filters and pagination | Any |
| GET | `/damage-claims/{claimId}` | Get a damage claim | Any |
| POST | `/damage-claims/{claimId}/assess` | Assess a reported claim with a condition grade | EquipmentManager |
| POST | `/damage-claims/{claimId}/settle` | Settle an assessed claim (charges fee, mutates subject) | EquipmentManager |
| POST | `/damage-claims/{claimId}/waive` | Waive an assessed claim (no fee, same subject mutation) | TeamAdmin |
| POST | `/damage-claims/{claimId}/reopen` | Reopen an assessed claim back to REPORTED | TeamAdmin |
| POST | `/disposition-cases` | Propose an end-of-season disposition over a pool scope | EquipmentManager |
| GET | `/disposition-cases/{caseId}` | Get a disposition case | Any |
| POST | `/disposition-cases/{caseId}/approve` | Approve a proposed disposition (snapshots affected pools) | TeamAdmin |
| POST | `/disposition-cases/{caseId}/reject` | Reject a proposed disposition | TeamAdmin |
| POST | `/disposition-cases/{caseId}/execute` | Execute an approved disposition (write-off / carryover / sale) | EquipmentManager |
| POST | `/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC); startup default 2026-08-01T00:00:00Z | TeamAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the index of identifiers to HTTP statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_CLAIM_SUBJECT` | 400 Bad Request |
| `ERR_PLAYER_NOT_FOUND` | 404 Not Found |
| `ERR_POOL_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_KIT_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_GEAR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_RECONDITIONING_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_GAME_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_DAMAGE_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_DISPOSITION_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_POOL_CLOSED` | 409 Conflict |
| `ERR_OPEN_ORDERS_EXIST` | 409 Conflict |
| `ERR_ORDER_NOT_OPEN` | 409 Conflict |
| `ERR_RECEIVE_EXCEEDS_OUTSTANDING` | 409 Conflict |
| `ERR_KIT_NOT_RESERVED` | 409 Conflict |
| `ERR_KIT_NOT_ISSUED` | 409 Conflict |
| `ERR_GEAR_NOT_IN_STOCK` | 409 Conflict |
| `ERR_GEAR_NOT_ISSUED` | 409 Conflict |
| `ERR_JOB_NOT_OPEN` | 409 Conflict |
| `ERR_EVENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_EVENT_NOT_LOCKED` | 409 Conflict |
| `ERR_LAUNDRY_INVALID_TRANSITION` | 409 Conflict |
| `ERR_LAUNDRY_NOT_READY` | 409 Conflict |
| `ERR_CHECKLIST_INCOMPLETE` | 409 Conflict |
| `ERR_CLAIM_NOT_REPORTED` | 409 Conflict |
| `ERR_CLAIM_NOT_ASSESSED` | 409 Conflict |
| `ERR_DISPOSITION_NOT_PROPOSED` | 409 Conflict |
| `ERR_DISPOSITION_NOT_APPROVED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PLAYER_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAYER_HAS_ISSUED_KITS` | 409 Conflict |
| `ERR_GEAR_CERTIFICATION_EXPIRED` | 409 Conflict |
| `ERR_GEAR_CONDITION_NOT_ISSUABLE` | 409 Conflict |
| `ERR_PLAYER_GEAR_LIMIT_REACHED` | 409 Conflict |
| `ERR_JERSEY_NUMBER_TAKEN` | 409 Conflict |
| `ERR_ASSET_TAG_TAKEN` | 409 Conflict |
| `ERR_POOL_ALREADY_EXISTS` | 409 Conflict |
| `ERR_POOL_SEASON_MISMATCH` | 409 Conflict |
| `ERR_GARMENT_NOT_COVERED_BY_CONTRACT` | 409 Conflict |
| `ERR_CLAIM_PLAYER_MISMATCH` | 409 Conflict |
| `ERR_EVENT_SPACING_VIOLATION` | 409 Conflict |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ALTERNATE_KIT_LIMIT_REACHED` | 409 Conflict |
| `ERR_ALLOCATION_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_POOL_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_STOCK_BELOW_COMMITMENTS` | 409 Conflict |
| `ERR_AMENDMENT_BELOW_COMMITTED` | 409 Conflict |
| `ERR_DISPOSITION_SCOPE_EMPTY` | 409 Conflict |
| `ERR_POOL_HAS_ACTIVE_COMMITMENTS` | 409 Conflict |
| `ERR_STALE_POOL_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
