# 3PL Fulfillment API — Product Requirements Document

## 1. Introduction

This document specifies the API for a third-party logistics (3PL) fulfillment platform — the operational backbone a warehouse operator runs on behalf of many merchant clients at once. A single physical building holds inventory that belongs to dozens of independent merchants, and the platform's central responsibility is to keep each merchant's goods, orders, and charges cleanly separated while moving units through a shared pick-pack-ship pipeline. The lifecycle begins when a client and its SKUs are onboarded, continues through inbound receiving and putaway into physical bins, flows into order import, wave-based batch picking, packing and cartonization, rate-shopping and labelling, and ends at shipment — with a parallel reverse flow for returns grading and restock, and a billing layer that meters both per-pallet storage and per-order handling.

The platform serves several distinct operator personas working the same goods from different stations: warehouse staff who receive and put away inbound freight, wave planners who batch orders for efficient picking, pick and pack operators on the floor, shipping staff who buy carrier labels, returns clerks who grade what comes back, and billing staff who onboard clients and meter charges. Two themes dominate the design. The first is **inventory ownership**: every lot of stock is owned by exactly one client, and no operation may let one client's units commingle with another's on a pallet or be reserved against another client's order. The second is **estimate-versus-actual accounting**: handling fees are estimated when an order is packed and then re-derived — possibly higher — when it actually ships, and carrier costs are quoted at list price but billed at a negotiated discount. Getting these two themes exactly right, across cascading inventory and billing side effects, is the core of a correct implementation.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, the caller's unique identifier, and `X-User-Role`, the caller's role. If either header is missing, or `X-User-Role` does not name a known role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognises exactly eight roles, spelled precisely as follows: `BillingClerk`, `ClientUser`, `ReceivingClerk`, `WavePlanner`, `PickOperator`, `PackStation`, `ShipStation`, and `ReturnsClerk`.

Of these eight, only one is tied to a persisted entity. When `X-User-Role` is `ClientUser`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare that resource's `client_id` foreign key (directly, or transitively through the order it belongs to) against `X-User-ID`, so a `ClientUser` operates only within its own client's scope. The remaining seven roles — `BillingClerk`, `ReceivingClerk`, `WavePlanner`, `PickOperator`, `PackStation`, `ShipStation`, and `ReturnsClerk` — each carry an `identity` that is opaque: their `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record such an identifier where appropriate but does not compare it to any entity's `id`; these operators act across whichever clients the warehouse is servicing.

Responsibilities divide by station. A `BillingClerk` onboards clients, suspends them, and runs the storage-accrual sweep, and is the only role that may create clients or post storage charges. A `ClientUser` onboards and discontinues its own SKUs and imports and cancels its own orders. A `ReceivingClerk` administers bins, drives the full receipt lifecycle (announce, receive, putaway, cancel), and applies cycle counts. A `WavePlanner` builds, populates, releases, and cancels waves. A `PickOperator` confirms picks and declares an order short. A `PackStation` packs picked orders into cartons. A `ShipStation` rate-shops and buys labels, ships orders, and marks shipments delivered or voided. A `ReturnsClerk` opens, grades, and closes returns. Read (`GET`) access is shared broadly across roles as detailed in the endpoint table; the authoritative permission set per endpoint is the Authorized Role(s) column of §4.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and counts from the start of the result set. List results are always sorted by `created_at` in ascending order. The pagination fields surfaced in the `meta` block of a list response are `limit`, `offset`, `total_count` (the total number of matching records across all pages), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and Identifiers

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix. Most resources additionally carry three audit fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 when the resource is created and increments by one on every mutation that changes the resource.

One entity is an exception. A `BillingCharge` is an append-only ledger event: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because a billing charge, once posted, is never modified — there is no reversal entry and no in-place edit. Wherever this document speaks of bumping `version` or refreshing `updated_at` on mutation, that applies to every entity except `BillingCharge`.

### 2.5. Nested Resource Resolution

Many endpoints address a resource nested beneath a client, such as a receipt, order, wave, return, shipment, pick task, or cycle count under `/clients/{clientId}/...`. Path identifiers are validated left to right: the `clientId` is resolved first, and if no such client exists the request fails with `ERR_CLIENT_NOT_FOUND` before any nested identifier is examined. Only once the client resolves does the server check the nested resource (for example a `receiptId`, `orderId`, `waveId`, `returnId`, `shipmentId`, `pickTaskId`, or `cycleCountId`), returning the resource-specific not-found error if it is absent. Each resource type has its own 404 code: an absent SKU yields `ERR_SKU_NOT_FOUND`, a bin `ERR_BIN_NOT_FOUND`, an inventory lot `ERR_LOT_NOT_FOUND`, a receipt `ERR_RECEIPT_NOT_FOUND`, an order `ERR_ORDER_NOT_FOUND`, a wave `ERR_WAVE_NOT_FOUND`, a pick task `ERR_PICK_TASK_NOT_FOUND`, a carton `ERR_CARTON_NOT_FOUND`, a shipment `ERR_SHIPMENT_NOT_FOUND`, a return `ERR_RETURN_NOT_FOUND`, a cycle count `ERR_CYCLE_COUNT_NOT_FOUND`, and a billing charge `ERR_CHARGE_NOT_FOUND`. A nested resource that exists but belongs to a different client is treated as a cross-ownership violation (see §2.6), not a plain not-found.

### 2.6. Inventory Ownership and Cross-Client Integrity

Inventory ownership is the platform's hardest boundary. Every `Sku`, `InventoryLot`, `Order`, and the goods they represent belong to exactly one client. When an operation references these across a client-scoped path, the referenced resources must all belong to the path's client: a SKU's `client_id`, a lot's `client_id`, and an order's `client_id` must match the path client, and a lot's `sku_id` must point to a SKU owned by that same client. Any mismatch is rejected with `ERR_CLIENT_OWNERSHIP_MISMATCH` (HTTP 409). This check guards receiving, order import, inventory-lot references, cycle counts, and returns.

A second facet of ownership is **pallet exclusivity**. A bin whose `bin_type` is `PALLET` is a single-tenant pallet position: it may hold inventory for at most one client at a time. Putting away or restocking one client's units into a `PALLET` bin that already holds at least one unit of a different client's inventory is rejected with `ERR_PALLET_OCCUPIED_BY_OTHER_CLIENT` (HTTP 409), even when the bin still has volume to spare. Bins whose `bin_type` is `GENERAL` are each-pick shelves that permit commingling and are exempt from this rule.

### 2.7. Bin Capacity and Volume Accounting

Each bin tracks its `occupied_cc`, a read-only figure recomputed as the sum, over every `InventoryLot` resting in that bin, of the lot's `on_hand_qty` multiplied by the `unit_volume_cc` of its SKU. A putaway or a sellable-return restock must not push `occupied_cc` above the bin's `capacity_cc`. The boundary is inclusive: `occupied_cc` may reach `capacity_cc` exactly, and only a result strictly greater than `capacity_cc` is rejected, with `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409). A bin's `status` is `OPEN` when created and may be moved to `BLOCKED`; a `BLOCKED` bin rejects putaway, pick confirmation, and sellable-return restock with `ERR_BIN_BLOCKED` (HTTP 409).

### 2.8. Hierarchical Consistency and Cascading Side Effects

Mutations in this system rarely touch a single record. Reserving, consuming, restocking, or recounting inventory cascades into recomputed lot quantities and bin volumes; shipping an order cascades into carton states, a posted billing charge, and possibly the completion of a parent wave. Throughout this document, whenever a side effect changes a lot's `on_hand_qty`, `reserved_qty`, or `available_qty`, the owning bin's `occupied_cc` is recomputed in the same atomic request, and the mutated entities each have their `version` incremented and `updated_at` refreshed (excepting `BillingCharge`, per §2.4). All cascades described for any single operation complete atomically within that one triggering request; a request that fails any precondition makes no partial change.

The three derived inventory quantities maintain a fixed relationship at all times: a lot's `on_hand_qty` is the physical units present, which equals its `reserved_qty` (units committed to picking/packing but not yet shipped) plus its `available_qty` (units free to reserve). Equivalently, `available_qty` is `on_hand_qty` minus `reserved_qty`. A client's two billing balances are likewise derived, not free-standing: `storage_balance_cents` is the running sum of the `amount_cents` of every posted `BillingCharge` for that client whose `charge_type` is `STORAGE`, and `handling_balance_cents` is the running sum of the `amount_cents` of every posted `BillingCharge` whose `charge_type` is `HANDLING`. Storage and handling are distinct conserved-quantity domains; a storage charge never touches the handling balance and vice versa.

### 2.9. Monetary Precision and the Estimate-Versus-Actual Principle

All monetary fields in this system are expressed as integer cents — `storage_rate_per_pallet_cents`, `handling_rate_per_order_cents`, `handling_rate_per_extra_unit_cents`, `handling_surcharge_per_extra_carton_cents`, `estimated_handling_cents`, `billed_handling_cents`, `quoted_cost_cents`, `amount_cents`, the two client balances, and so on. Handling-fee arithmetic is performed entirely in integer cents and produces an integer-cent result with no fractional component and no rounding. Volume figures are integer cubic centimetres, and inventory quantities are integer units.

The one place a fractional intermediate appears is carrier rate-shopping, where a published quote is reduced by a basis-point discount. There, and only there, a single rounding step applies: the discounted amount is rounded half up to the nearest whole cent. Two principles recur and must be honoured precisely. First, handling has an **estimate** computed at pack time and a final **billed** amount computed at ship time, and the billed amount can legitimately exceed the estimate. Second, a carrier's **published** quote (list price) and its **negotiated** quote (after the client's discount) diverge whenever the client has a non-zero discount. The detailed formulas live in §3.

### 2.10. Optimistic Concurrency on Cycle Counts

Applying a cycle count is the one write that uses optimistic concurrency control. A request to apply a cycle count must carry `expected_lot_version`, the integer `version` of the target `InventoryLot` that the counter last observed when reading the lot. The server compares `expected_lot_version` against the lot's current live `version`. If another operation — a putaway top-up, a ship consumption, a return restock, or a prior cycle count — has advanced the lot's `version` since the counter read it, the supplied `expected_lot_version` no longer matches, and the request is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). This prevents a counter from overwriting `on_hand_qty` from an outdated baseline. No other endpoint takes a version field; cycle-count application is the sole optimistic-concurrency-controlled write.

## 3. Business Logic & Workflows

### 3.1. Client and SKU Onboarding

A `BillingClerk` onboards a merchant by creating a `Client` carrying a `name` and a billing rate card. The rate card comprises `storage_rate_per_pallet_cents` (the daily charge for one occupied pallet bin) and `handling_rate_per_order_cents` (the base handling fee for one shipped order), both required, plus three optional rate fields that each default to 0 when omitted: `handling_rate_per_extra_unit_cents` (charged per shipped unit beyond the first), `handling_surcharge_per_extra_carton_cents` (charged per carton beyond the first, but only at ship time — see §3.6), and `carrier_discount_bps` (a negotiated carrier discount in basis points, where one basis point is one hundredth of one percent, constrained to the range 0 through 10000 inclusive). A newly created client starts with `status` set to `ACTIVE`, and both `storage_balance_cents` and `handling_balance_cents` initialised to 0.

A client may later be suspended by a `BillingClerk`, moving its `status` from `ACTIVE` to `SUSPENDED`. A `SUSPENDED` client rejects new receipts and new orders with `ERR_CLIENT_SUSPENDED` (HTTP 409); existing work already in flight is unaffected.

Acting as itself, a `ClientUser` onboards SKUs under its client. A `Sku` carries a `code` (unique within the client — the pair of owning `client_id` and `code` must be unique), a `unit_volume_cc` (the volume of one unit, used for cartonization and bin accounting), an optional `unit_cost_cents` (declared per-unit cost for valuation, defaulting to 0), and an optional `hazmat` flag (defaulting to false) marking the SKU as hazardous. The SKU's `client_id` is taken from the path, and its `status` starts at `ACTIVE`. A `ClientUser` may discontinue a SKU, moving its `status` to `DISCONTINUED`; a `DISCONTINUED` SKU rejects new receipts with `ERR_SKU_DISCONTINUED` (HTTP 409).

### 3.2. Bins and Inbound Receiving

A `ReceivingClerk` creates the warehouse's physical bins. A `Bin` carries a globally unique `location_code`, a `bin_type` of either `GENERAL` or `PALLET`, and a `capacity_cc` (total volume capacity). On creation a bin's `status` is `OPEN` and its `occupied_cc` is 0. A clerk may block a bin, moving `status` from `OPEN` to `BLOCKED`.

Inbound goods arrive against an advance shipment notice. A `ReceivingClerk` announces a `Receipt` for a client by supplying the inbound `sku_id`, the destination `bin_id`, and an `expected_qty` (the announced unit count, which must be strictly greater than 0). The receipt begins in `ANNOUNCED` status with `received_qty` 0. The receipt is rejected at announce time if the owning client is `SUSPENDED` or the named SKU is `DISCONTINUED`.

Receiving proceeds in two confirmed steps. First, a clerk dock-counts the receipt, supplying the `received_qty` actually counted on the dock (which must be at least 0); this requires the receipt to be in `ANNOUNCED` status, else `ERR_RECEIPT_NOT_ANNOUNCED` (HTTP 409), and a `received_qty` below 0 is rejected as `ERR_INVALID_REQUEST`. The dock-count records `received_qty` and advances the receipt from `ANNOUNCED` to `RECEIVED`. An announced receipt that has not been counted may instead be cancelled, moving `ANNOUNCED` to `CANCELLED`; cancellation likewise requires the `ANNOUNCED` status and otherwise raises `ERR_RECEIPT_NOT_ANNOUNCED`.

Putaway is the second step and the moment stock enters inventory. Putting a receipt away requires it to be in `RECEIVED` status, else `ERR_RECEIPT_NOT_RECEIVED`. The destination bin must be `OPEN`, else `ERR_BIN_BLOCKED`. If the destination bin's `bin_type` is `PALLET`, it must hold no `InventoryLot` belonging to a different client, else `ERR_PALLET_OCCUPIED_BY_OTHER_CLIENT`. Adding the `received_qty` units must keep the bin's resulting `occupied_cc` at or below `capacity_cc`, else `ERR_BIN_CAPACITY_EXCEEDED`. When all of these hold, putaway creates — or, if one already exists for the same combination of `client_id`, `sku_id`, `bin_id`, and originating `receipt_id`, tops up — an `InventoryLot`: its `on_hand_qty` and its `available_qty` each increase by `received_qty`, the owning bin's `occupied_cc` is recomputed, and the receipt advances from `RECEIVED` to `PUTAWAY`. The created lot records the `receipt_id` of the receipt that produced it.

### 3.3. Order Import and Wave Building

A `ClientUser` imports a fulfillment `Order` by supplying a `ship_to_zone` (a destination zone, an integer from 1 through 8 inclusive, used later by rate-shop) and a non-empty `lines` array. Each line is an object naming a `sku_id` and a `qty` that must be strictly greater than 0, and at least one line is required; an empty `lines` array, a zone outside 1 through 8, or a non-positive line quantity is rejected as `ERR_INVALID_REQUEST`. On import the order's `total_units` is computed as the sum of `qty` across all lines, its `status` is `IMPORTED`, its `wave_id` is null, and both `estimated_handling_cents` and `billed_handling_cents` are 0. Import is rejected when the client is `SUSPENDED`. While in `IMPORTED` status, an order may be cancelled by a `ClientUser` (see §3.8).

A `WavePlanner` batches orders for efficient picking by creating a `Wave` for a client. A new wave begins in `BUILDING` status with `order_count` 0. The planner adds an order to a building wave by supplying its `order_id`; the order must be in `IMPORTED` status (else `ERR_ORDER_NOT_IMPORTED`) and the wave must be in `BUILDING` (else `ERR_WAVE_NOT_BUILDING`). Adding an order sets that order's `wave_id` to the wave and increments the wave's `order_count`. Every order placed in a wave must belong to the wave's client. A building wave may be cancelled, which detaches every member order by clearing its `wave_id` back to null (the orders remain `IMPORTED`) and moves the wave from `BUILDING` to `CANCELLED`; cancellation requires the `BUILDING` status, else `ERR_WAVE_NOT_BUILDING`.

### 3.4. Wave Release, Reservation, and Pick Generation

Releasing a wave is the pivotal step that commits inventory and generates floor work. Release requires the wave to be in `BUILDING` status (else `ERR_WAVE_NOT_BUILDING`) and to have at least one member order (else `ERR_WAVE_EMPTY`). Before anything is reserved, the server verifies inventory coverage: for every line of every member order, the line's `qty` must be coverable by the `available_qty` held across the client's lots for that SKU. If any line cannot be covered, the entire release is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409) and nothing is reserved.

When coverage holds, release reserves stock line by line. For each line, the lot to draw from is chosen by a **FEFO selector** — first-expiry-first-out approximated by oldest stock first — which orders the client's eligible lots for that SKU by their `created_at` ascending and picks from the earliest; the lot's own `id` is never used as a tiebreak or selector input. Reserving a line increases the chosen lot's `reserved_qty` by the line's `qty`, with the lot's `available_qty` recomputed downward by the same amount. For each reserved line the server creates a `PickTask` in `ASSIGNED` status, bound to the chosen lot via `lot_id`, recording the `order_id` it fulfils, the picked SKU's `sku_id` (denormalised for inventory sync), the `qty` to pick, and a `picked_qty` of 0. As release completes, each member order advances from `IMPORTED` to `RESERVED` and immediately onward to `PICKING`, and the wave moves from `BUILDING` to `RELEASED`.

A released wave completes automatically. Whenever the last of a wave's member orders reaches a terminal order state — `SHIPPED`, `CANCELLED`, or `SHORT` — the system advances the wave from `RELEASED` to `COMPLETED`. This auto-completion is re-evaluated after every order-terminating event described below.

### 3.5. Picking and the Short Path

A `PickOperator` works the assigned pick tasks. Confirming a pick requires the task to be in `ASSIGNED` status (else `ERR_PICK_NOT_ASSIGNED`) and the bin owning the task's `lot_id` to be `OPEN` (else `ERR_BIN_BLOCKED`). The operator submits a `picked_qty` that must be at least 0 and no greater than the task's `qty`, else `ERR_INVALID_REQUEST`. A successful confirmation records `picked_qty` and moves the task from `ASSIGNED` to `PICKED`.

When the floor cannot fully satisfy an order's picks, a `PickOperator` declares the order short. This is permitted only while the order is in `PICKING` status (else `ERR_ORDER_NOT_PICKING`) and only when at least one of the order's pick tasks has a `picked_qty` strictly less than its `qty` (else `ERR_NOT_SHORT`). Declaring short releases the unconsumed reservation for every line: for each line the chosen lot's `reserved_qty` is reduced by the shortfall — the line's `qty` minus its `picked_qty` — and the lot's `available_qty` is increased by that same delta, with the bin's `occupied_cc` recomputed. Every still-`ASSIGNED` pick task for the order is closed, moving from `ASSIGNED` to `SHORT_CLOSED`, the order moves from `PICKING` to `SHORT`, and the parent wave auto-completes if all its members are now terminal.

### 3.6. Packing, Cartonization, and the Handling Estimate

Once every pick task for an order is confirmed `PICKED`, a `PackStation` packs the order into cartons. Packing requires the order to be in `PICKING` status (else `ERR_ORDER_NOT_PICKING`) and every pick task for the order to be in `PICKED` status (else `ERR_PICKS_INCOMPLETE`). The station submits a `cartons` payload, each entry describing a carton's `order_id` and its `packed_units` (the unit count placed in that carton, which must be strictly greater than 0 and must not exceed the units still unpacked from what was picked). The submitted carton `packed_units` must sum exactly to the order's `total_units`, else `ERR_PACK_UNIT_MISMATCH` (HTTP 409).

For each submitted carton the server computes a `fill_volume_cc` as the sum, over the units placed in that carton, of each unit's SKU `unit_volume_cc`, and then assigns a `carton_size` by **cartonization**: it selects the smallest box whose inner volume is at least the carton's `fill_volume_cc`, evaluating the three box sizes in ascending order. A fill at or below 1000 cubic centimetres is a `SMALL` box; a fill above 1000 but at or below 5000 cubic centimetres is a `MEDIUM` box; a fill above 5000 but at or below 20000 cubic centimetres is a `LARGE` box. The boundary is inclusive — a fill of exactly 1000 cubic centimetres is `SMALL`. A carton whose `fill_volume_cc` exceeds 20000 cubic centimetres cannot be boxed and is rejected with `ERR_CARTON_OVERFLOW` (HTTP 409); each submitted carton must therefore fit within the `LARGE` box. Each created carton begins in `PACKED` status.

At pack time the server also stamps the order's `estimated_handling_cents`. The **handling estimate** uses a unit-only basis: it is the client's `handling_rate_per_order_cents` base fee, plus, when the order's `total_units` exceeds one, an incremental component of the client's `handling_rate_per_extra_unit_cents` multiplied by the number of units beyond the first — that is, `total_units` minus one. When `total_units` is one or fewer, the incremental component is zero. The estimate deliberately omits any per-carton surcharge and creates no billing charge — it is a preview written before the shipped carton count is final. A successful pack creates the cartons, stamps `estimated_handling_cents`, and advances the order from `PICKING` to `PACKED`.

### 3.7. Rate-Shop, Labelling, and the Carrier Selector

Before a packed order can ship, a `ShipStation` rate-shops carriers and purchases a label, creating a `Shipment` for the order's `order_id`. Three carriers compete: `GROUND_ECONOMY`, `GROUND_PLUS`, and `AIR_EXPRESS`. Rate-shop runs as a two-stage selector — first an eligibility filter, then a ranking over the eligible candidates.

The eligibility filter is evaluated before ranking. `GROUND_ECONOMY` is excluded from the candidate pool whenever any line SKU on the order is flagged `hazmat`; `GROUND_PLUS` and `AIR_EXPRESS` are always eligible, so the candidate pool is never empty. For each eligible carrier the server first computes a **published quote** in integer cents — the list-price figure with no client discount applied — as that carrier's base component, plus its per-zone component multiplied by the order's `ship_to_zone`, plus its per-carton component multiplied by the count of the order's `PACKED` cartons. The three carriers' rate cards are fixed: `GROUND_ECONOMY` has a base of 300 cents, 50 cents per zone, and 100 cents per carton; `GROUND_PLUS` has a base of 500 cents, 40 cents per zone, and 120 cents per carton; `AIR_EXPRESS` has a base of 1200 cents, 80 cents per zone, and 150 cents per carton.

Ranking is performed on the **negotiated quote**, not the published one, and the evaluation order is pinned because applying the discount before rounding does not generally equal rounding before discounting. For each eligible carrier the server: (1) computes the exact integer `published_cents` as above; (2) forms the exact discounted amount by multiplying `published_cents` by the quantity ten thousand minus the client's `carrier_discount_bps`, then dividing by ten thousand; and (3) rounds that discounted amount half up to a whole cent to obtain the negotiated figure. Rounding happens only at step three, once per carrier, after the discount. The winner is the eligible carrier with the lowest negotiated figure. If two carriers tie on the negotiated figure, the winner is the one earlier in the fixed precedence list `GROUND_ECONOMY`, then `GROUND_PLUS`, then `AIR_EXPRESS`; `created_at` and `id` are never used to break the tie. For a client whose `carrier_discount_bps` is zero the negotiated quote equals the published quote (no rounding changes an exact integer); for a non-zero discount the negotiated quote is strictly below the published quote, so the two diverge on the same shipment inputs.

The winning carrier is written to the shipment's `carrier`, and the winner's negotiated figure is stamped as `quoted_cost_cents`. A `tracking_number` is minted at label purchase, and the shipment begins in `LABELLED` status. A `ShipStation` may also supply an optional `force_carrier` to demand a specific carrier; forcing `GROUND_ECONOMY` for an order carrying any `hazmat` line SKU is rejected with `ERR_HAZMAT_CARRIER_FORBIDDEN` (HTTP 409), mirroring the eligibility exclusion. A `LABELLED` shipment may be voided while its order is still `PACKED`, moving `LABELLED` to `VOIDED` (this requires the shipment to be `LABELLED`, else `ERR_SHIPMENT_NOT_LABELLED`, and the order to be `PACKED`, else `ERR_ORDER_NOT_PACKED`).

### 3.8. Shipping, Consumption, and Handling Billing

Shipping is the cascade that turns reservations into consumption and produces the final handling charge. A `ShipStation` ships a packed order, which requires the order to be in `PACKED` status (else `ERR_ORDER_NOT_PACKED`) and a purchased label — a `LABELLED` `Shipment` for the order — to exist (else `ERR_LABEL_REQUIRED`). On ship, every reserved lot is consumed: each lot's `reserved_qty` is reduced by the reserved quantity and its `on_hand_qty` is reduced by the same amount, leaving `available_qty` unchanged, with each affected bin's `occupied_cc` recomputed. All of the order's cartons move from `PACKED` to `SHIPPED`, and the standing `LABELLED` shipment remains as is.

Shipping then stamps the order's `billed_handling_cents` and posts the handling charge. The **billed handling** shares the estimate's base and unit components — the `handling_rate_per_order_cents` base plus, when `total_units` exceeds one, `handling_rate_per_extra_unit_cents` times `total_units` minus one — and adds a **carton component** the estimate never includes: when the order's `PACKED` carton count exceeds one, the client's `handling_surcharge_per_extra_carton_cents` is charged for each carton beyond the first, that is, the carton count minus one. Because of this surcharge a multi-carton order is billed strictly more than its earlier estimate; a single-carton order is billed exactly its estimate. The server creates a `BillingCharge` whose `charge_type` is `HANDLING`, whose `amount_cents` equals the order's `billed_handling_cents` exactly, and whose `source_order_id` is the shipped order; posting this charge increases the client's `handling_balance_cents` by that `amount_cents`. The order then advances from `PACKED` to `SHIPPED`, and the parent wave auto-completes if all its members are now terminal. A shipped order's standing shipment may later be marked delivered by a `ShipStation`, moving the shipment from `LABELLED` to `DELIVERED`; delivery requires the shipment to be `LABELLED` (else `ERR_SHIPMENT_NOT_LABELLED`) and its order to be `SHIPPED` (else `ERR_ORDER_NOT_SHIPPED`).

A `ClientUser` may cancel an order while it is `IMPORTED` or `RESERVED`; any other status yields `ERR_ORDER_NOT_CANCELLABLE`. Cancelling an `IMPORTED` order simply detaches it from any wave it had joined (clearing `wave_id`). Cancelling a `RESERVED` order additionally unwinds its commitments: every reservation is released by reducing the affected lot's `reserved_qty` by the reserved `qty` and increasing the lot's `available_qty` by the same amount (bin `occupied_cc` recomputed), each of the order's `ASSIGNED` pick tasks is closed to `SHORT_CLOSED`, the order is detached from its wave, and the order moves to `CANCELLED`. After cancellation the parent wave auto-completes if all its members are now terminal.

### 3.9. Returns Grading and Restock

After an order ships, a `ReturnsClerk` opens a return against it. A `Return` is created for the SHIPPED order's `order_id` — the order must be in `SHIPPED` status, else `ERR_ORDER_NOT_SHIPPED` — and names the returned `sku_id` (which must have been shipped on that order), a restock `bin_id` (used only if the unit is later graded sellable), and a `qty` that must be strictly greater than 0 and must not exceed the units shipped for that SKU on the order, else `ERR_RETURN_QTY_EXCEEDS_SHIPPED` (HTTP 409). A new return begins in `REQUESTED` status with its `grade` unset.

Grading decides the unit's fate. A `ReturnsClerk` grades a return, which requires it to be in `REQUESTED` status (else `ERR_RETURN_NOT_REQUESTED`) and supplies a `grade` of either `SELLABLE` or `DAMAGED` (any other value is `ERR_INVALID_REQUEST`). The two branches are handled symmetrically but produce opposite inventory outcomes. When the `grade` is `DAMAGED`, the units are scrapped and no inventory changes. When the `grade` is `SELLABLE`, the units are restocked into the return's `bin_id`, and the same bin protections that govern putaway apply: the restock bin's `status` must be `OPEN` (else `ERR_BIN_BLOCKED`); if its `bin_type` is `PALLET`, the bin must hold no different client's lot (else `ERR_PALLET_OCCUPIED_BY_OTHER_CLIENT`); and the restock must keep the bin's `occupied_cc` at or below `capacity_cc` (else `ERR_BIN_CAPACITY_EXCEEDED`). A sellable restock creates or tops up an `InventoryLot` in the `bin_id` for the return's `client_id` and `sku_id`, raising both `on_hand_qty` and `available_qty` by `qty` and recomputing the bin's `occupied_cc`. Whichever branch is taken, the return records the chosen `grade` and advances from `REQUESTED` to `GRADED`. A graded return is finally closed by a `ReturnsClerk`, moving `GRADED` to `CLOSED`; closing requires the `GRADED` status, else `ERR_RETURN_NOT_GRADED`.

### 3.10. Cycle Counts and Inventory Synchronisation

Physical inventory drifts from the system of record, and a `ReceivingClerk` reconciles it with a cycle count applied directly to a lot. The count names the target `lot_id`, the `expected_lot_version` the counter observed when reading the lot, and the `counted_qty` physically counted (which must be at least 0). A cycle count applies immediately on creation, so its `status` is always `APPLIED`. The optimistic-concurrency check of §2.10 runs first: if `expected_lot_version` does not equal the lot's live `version`, the count is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412) and no change is made.

When the version matches, the server reads the lot's `on_hand_qty` at apply time as the before-count baseline and records the count's `variance_qty` as the `counted_qty` minus that baseline; the variance may be negative. The correction then sets the lot's `on_hand_qty` to `counted_qty` while conserving reserved units: the lot's `available_qty` becomes the larger of zero and `counted_qty` minus the lot's `reserved_qty`, so reserved units are protected first. If `counted_qty` is below the lot's `reserved_qty`, `reserved_qty` is clamped down to `counted_qty` and `available_qty` floors at zero — this is a silent clamp, not an error. Applying the correction increments the lot's `version` by one and recomputes the owning bin's `occupied_cc`. (It is precisely this version bump that can make a concurrently-prepared cycle count stale.)

### 3.11. Storage Accrual and the Billing Ledger

Storage is metered separately from handling. A `BillingClerk` runs a daily storage sweep for a client, supplying a `days` count that must be at least 1. The sweep counts the client's **occupied pallet bins**: every bin whose `bin_type` is `PALLET`, whose `occupied_cc` is greater than zero, and which holds at least one `InventoryLot` whose `client_id` is this client. A qualifying pallet bin counts exactly once for the client no matter how many of that client's lots it holds, and a bin holding none of this client's units does not count. The charge `amount_cents` is the number of occupied pallet bins multiplied by the client's `storage_rate_per_pallet_cents`, multiplied again by `days`. The sweep posts a `BillingCharge` whose `charge_type` is `STORAGE`, whose `source_order_id` is null, and increases the client's `storage_balance_cents` by that `amount_cents`.

Every `BillingCharge` is an immutable ledger event. Each carries the charged `client_id`, a `charge_type` of `STORAGE` or `HANDLING`, the computed `amount_cents`, an optional `source_order_id` (the order that produced a `HANDLING` charge, null for `STORAGE`), and a `posted` flag that is always true. Charges post immediately and are never reversed or edited; the client balances are simply the running sums of the relevant posted charges, as established in §2.8.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; all other successful operations, including state transitions on existing resources and read operations, return HTTP 200. Request bodies, response bodies, and side effects are intentionally omitted from this table — refer to the §3 workflow narratives to reconstruct the full contract of each operation.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| GET | /skus | List SKUs, filterable by client_id | ClientUser, WavePlanner, ReceivingClerk, BillingClerk |
| GET | /skus/{skuId} | Get a SKU by id | ClientUser, WavePlanner, ReceivingClerk, BillingClerk |
| GET | /receipts | List receipts, filterable by client_id, sku_id, bin_id | ReceivingClerk, ClientUser, BillingClerk |
| GET | /receipts/{receiptId} | Get a receipt by id | ReceivingClerk, ClientUser, BillingClerk |
| GET | /orders | List orders, filterable by client_id, wave_id | ClientUser, WavePlanner, BillingClerk, ShipStation |
| GET | /orders/{orderId} | Get an order by id | ClientUser, WavePlanner, BillingClerk, ShipStation, PackStation |
| GET | /waves | List waves, filterable by client_id | WavePlanner, ClientUser, BillingClerk |
| GET | /waves/{waveId} | Get a wave by id | WavePlanner, ClientUser, BillingClerk |
| GET | /returns | List returns, filterable by order_id, sku_id, bin_id | ReturnsClerk, ClientUser, BillingClerk |
| GET | /returns/{returnId} | Get a return by id | ReturnsClerk, ClientUser, BillingClerk |
| GET | /billing-charges | List billing charges, filterable by client_id, source_order_id, charge_type | BillingClerk, ClientUser |
| GET | /billing-charges/{chargeId} | Get a billing charge by id | BillingClerk, ClientUser |
| POST | /clients | Onboard a client with billing rate card | BillingClerk |
| GET | /clients | List clients | BillingClerk, ClientUser, WavePlanner, ReceivingClerk |
| GET | /clients/{clientId} | Get a client (includes balances) | BillingClerk, ClientUser, WavePlanner, ReceivingClerk |
| POST | /clients/{clientId}/suspend | Suspend a client | BillingClerk |
| POST | /clients/{clientId}/skus | Onboard a SKU under a client | ClientUser |
| GET | /clients/{clientId}/skus | List a client's SKUs | ClientUser, WavePlanner, ReceivingClerk, BillingClerk |
| GET | /clients/{clientId}/skus/{skuId} | Get a SKU | ClientUser, WavePlanner, ReceivingClerk, BillingClerk |
| POST | /clients/{clientId}/skus/{skuId}/discontinue | Discontinue a SKU | ClientUser |
| POST | /bins | Create a warehouse bin | ReceivingClerk |
| GET | /bins | List bins | ReceivingClerk, WavePlanner, ClientUser, BillingClerk |
| GET | /bins/{binId} | Get a bin (includes occupied_cc) | ReceivingClerk, WavePlanner, ClientUser, BillingClerk |
| POST | /bins/{binId}/block | Block a bin | ReceivingClerk |
| GET | /inventory-lots | List inventory lots, filterable by client_id, sku_id, bin_id, receipt_id | ReceivingClerk, WavePlanner, ClientUser, BillingClerk |
| GET | /inventory-lots/{lotId} | Get one inventory lot (includes quantities, version) | ReceivingClerk, WavePlanner, ClientUser, BillingClerk |
| POST | /clients/{clientId}/receipts | Announce an inbound receipt | ReceivingClerk |
| GET | /clients/{clientId}/receipts | List a client's receipts | ReceivingClerk, ClientUser, BillingClerk |
| GET | /clients/{clientId}/receipts/{receiptId} | Get a receipt | ReceivingClerk, ClientUser, BillingClerk |
| POST | /clients/{clientId}/receipts/{receiptId}/receive | Dock-count an announced receipt | ReceivingClerk |
| POST | /clients/{clientId}/receipts/{receiptId}/putaway | Putaway received units, creating/topping up a lot | ReceivingClerk |
| POST | /clients/{clientId}/receipts/{receiptId}/cancel | Cancel an announced receipt | ReceivingClerk |
| POST | /clients/{clientId}/orders | Import a fulfillment order | ClientUser |
| GET | /clients/{clientId}/orders | List a client's orders | ClientUser, WavePlanner, BillingClerk, ShipStation |
| GET | /clients/{clientId}/orders/{orderId} | Get an order (includes handling fields) | ClientUser, WavePlanner, BillingClerk, ShipStation, PackStation |
| POST | /clients/{clientId}/orders/{orderId}/pack | Pack a fully-picked order into cartons | PackStation |
| POST | /clients/{clientId}/orders/{orderId}/ship | Ship a packed order; consume inventory and bill handling | ShipStation |
| POST | /clients/{clientId}/orders/{orderId}/short | Declare a picking order short | PickOperator |
| POST | /clients/{clientId}/orders/{orderId}/cancel | Cancel an order (IMPORTED or RESERVED only) | ClientUser |
| POST | /clients/{clientId}/waves | Create a wave for a client | WavePlanner |
| GET | /clients/{clientId}/waves | List a client's waves | WavePlanner, ClientUser, BillingClerk |
| GET | /clients/{clientId}/waves/{waveId} | Get a wave (includes order_count) | WavePlanner, ClientUser, BillingClerk |
| POST | /clients/{clientId}/waves/{waveId}/add-order | Add an IMPORTED order to a BUILDING wave | WavePlanner |
| POST | /clients/{clientId}/waves/{waveId}/release | Release a wave: reserve, generate picks, move to PICKING | WavePlanner |
| POST | /clients/{clientId}/waves/{waveId}/cancel | Cancel a BUILDING wave | WavePlanner |
| GET | /pick-tasks | List pick tasks, filterable by order_id, lot_id, sku_id | PickOperator, WavePlanner, PackStation |
| GET | /pick-tasks/{pickTaskId} | Get a pick task | PickOperator, WavePlanner, PackStation |
| POST | /clients/{clientId}/pick-tasks/{pickTaskId}/confirm | Confirm a pick | PickOperator |
| GET | /cartons | List cartons, filterable by order_id | PackStation, ShipStation, BillingClerk |
| GET | /cartons/{cartonId} | Get a carton (includes fill_volume_cc, carton_size) | PackStation, ShipStation, BillingClerk |
| POST | /clients/{clientId}/shipments | Rate-shop and purchase a label for a PACKED order | ShipStation |
| GET | /shipments | List shipments, filterable by order_id | ShipStation, BillingClerk, ClientUser |
| GET | /shipments/{shipmentId} | Get a shipment (includes carrier, quoted_cost_cents, tracking_number) | ShipStation, BillingClerk, ClientUser |
| POST | /clients/{clientId}/shipments/{shipmentId}/deliver | Mark a shipment delivered | ShipStation |
| POST | /clients/{clientId}/shipments/{shipmentId}/void | Void a label while the order is still PACKED | ShipStation |
| POST | /clients/{clientId}/returns | Open an RMA against a SHIPPED order | ReturnsClerk |
| GET | /clients/{clientId}/returns | List a client's returns | ReturnsClerk, ClientUser, BillingClerk |
| GET | /clients/{clientId}/returns/{returnId} | Get a return | ReturnsClerk, ClientUser, BillingClerk |
| POST | /clients/{clientId}/returns/{returnId}/grade | Grade a return; SELLABLE restocks, DAMAGED scraps | ReturnsClerk |
| POST | /clients/{clientId}/returns/{returnId}/close | Close a graded return | ReturnsClerk |
| POST | /clients/{clientId}/cycle-counts | Apply a cycle count to a lot with OCC on the lot version | ReceivingClerk |
| GET | /cycle-counts | List cycle counts, filterable by lot_id | ReceivingClerk, BillingClerk |
| GET | /cycle-counts/{cycleCountId} | Get a cycle count (includes variance_qty) | ReceivingClerk, BillingClerk |
| POST | /clients/{clientId}/storage/accrue | Run the per-pallet daily storage sweep | BillingClerk |
| GET | /clients/{clientId}/billing-charges | List a client's billing charges | BillingClerk, ClientUser |
| GET | /clients/{clientId}/billing-charges/{chargeId} | Get a billing charge | BillingClerk, ClientUser |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CLIENT_NOT_FOUND | 404 |
| ERR_SKU_NOT_FOUND | 404 |
| ERR_BIN_NOT_FOUND | 404 |
| ERR_LOT_NOT_FOUND | 404 |
| ERR_RECEIPT_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_WAVE_NOT_FOUND | 404 |
| ERR_PICK_TASK_NOT_FOUND | 404 |
| ERR_CARTON_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_RETURN_NOT_FOUND | 404 |
| ERR_CYCLE_COUNT_NOT_FOUND | 404 |
| ERR_CHARGE_NOT_FOUND | 404 |
| ERR_RECEIPT_NOT_ANNOUNCED | 409 |
| ERR_RECEIPT_NOT_RECEIVED | 409 |
| ERR_WAVE_NOT_BUILDING | 409 |
| ERR_WAVE_EMPTY | 409 |
| ERR_ORDER_NOT_IMPORTED | 409 |
| ERR_ORDER_NOT_PICKING | 409 |
| ERR_ORDER_NOT_PACKED | 409 |
| ERR_ORDER_NOT_SHIPPED | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_PICKS_INCOMPLETE | 409 |
| ERR_NOT_SHORT | 409 |
| ERR_PICK_NOT_ASSIGNED | 409 |
| ERR_LABEL_REQUIRED | 409 |
| ERR_SHIPMENT_NOT_LABELLED | 409 |
| ERR_RETURN_NOT_REQUESTED | 409 |
| ERR_RETURN_NOT_GRADED | 409 |
| ERR_STALE_LOT_VERSION | 412 |
| ERR_CLIENT_SUSPENDED | 409 |
| ERR_SKU_DISCONTINUED | 409 |
| ERR_CLIENT_OWNERSHIP_MISMATCH | 409 |
| ERR_BIN_BLOCKED | 409 |
| ERR_BIN_CAPACITY_EXCEEDED | 409 |
| ERR_PALLET_OCCUPIED_BY_OTHER_CLIENT | 409 |
| ERR_PACK_UNIT_MISMATCH | 409 |
| ERR_CARTON_OVERFLOW | 409 |
| ERR_INSUFFICIENT_INVENTORY | 409 |
| ERR_HAZMAT_CARRIER_FORBIDDEN | 409 |
| ERR_RETURN_QTY_EXCEEDS_SHIPPED | 409 |
