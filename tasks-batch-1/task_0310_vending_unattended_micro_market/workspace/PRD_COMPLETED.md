# Vending Micro-Market Operations API — Product Requirements Document

## 1. Introduction

Operators of unattended retail estates — snack vendors, beverage vendors, and open micro-market kiosks — run a logistics and finance problem disguised as a candy machine. A single operator may steward hundreds of machines spread across dozens of host locations, each machine carrying its own planogram of slotted products, each slot drawing down physical lots that expire on a clock, each sale either filling a cash vault or settling cashlessly, and each host expecting a monthly commission cheque whose size depends on what sold, what spoiled, and what walked out the door unpaid. This document specifies the backend API that ties those concerns together into a single source of operational truth.

The system tracks four intertwined disciplines. First, **inventory and planogram management**: what product sits in which slot, how full each slot is, and how stock posture rolls up to a machine-level status. Second, **route logistics**: how a route driver is pre-kitted with recommended refills, dispatched, and reconciled against the physical counts found at each machine. Third, **payment and pricing**: cashless and cash sales drawing inventory in strict first-in-first-out (FIFO) order against expiration, with cash sales accumulating toward a vault-full alert. Fourth, **finance and reconciliation**: theoretical-versus-physical shrink, provisional-versus-final cost of goods, and a tiered or flat commission owed to each host net of a shrink chargeback and floored by a monthly guarantee.

Because field operations, driving, host-side staff, and finance back-office all touch the same machines from different angles, the API is built around precise role separation, immediate consistency (every derived field is recomputed the moment its inputs change), and optimistic concurrency control on the machine record so that a driver reconciling against a stale view of a machine cannot silently double-apply a refill. The remainder of this document defines the global contracts every endpoint obeys (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they act. If either header is missing, or if `X-User-Role` carries a value that is not a recognized role, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles: `FieldOps`, `RouteDriver`, `HostManager`, and `FinanceClerk`. `FieldOps` is the operations technician who provisions the catalog, places machines, configures slots, manages drivers and routes, dispatches and closes routes, services machines, collects cash, voids sales, and rejects visits. `RouteDriver` is the field driver who opens and reconciles restock visits while a route is dispatched. `HostManager` is host-site staff who view their own statements, open service tickets, and record sales at the kiosk. `FinanceClerk` is the finance back-office user who opens and finalizes commission statements. All four roles may read any resource through the GET endpoints.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `FieldOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it against any entity's `id`. When `X-User-Role` is `FinanceClerk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never compared to an entity `id`. When `X-User-Role` is `RouteDriver`, `X-User-ID` is the `id` of the acting `RouteDriverProfile`; any ownership check on a resource that references a driver compares that resource's driver foreign key to `X-User-ID`. When `X-User-Role` is `HostManager`, `X-User-ID` is the `id` of the acting `HostSite`; any ownership check on a resource that references a host site compares that resource's host-site foreign key to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list-based response includes the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID, used as the canonical identifier with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once at creation. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification, refreshed on every mutation. The `version` field is an integer that begins at its initial value on creation and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control.

There is one deliberate exception. A `Sale` is an immutable event record: it carries only `id` and `created_at`, and it has neither `updated_at` nor `version`. Voiding a sale does not mutate the sale's own versioning fields (it has none); instead, voiding flips the sale's `settlement_status` and reverses the side effects the sale produced, as described in Section 3. Every other entity — `HostSite`, `Product`, `Machine`, `PlanogramSlot`, `InventoryLot`, `RestockRoute`, `RouteDriverProfile`, `RouteStop`, `RestockVisit`, `CommissionStatement`, and `ServiceTicket` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Derived Posture and Hierarchical Re-Derivation

A number of fields are read-only and computed; clients never set them directly, and the server recomputes them immediately whenever an input changes. This consistency is immediate, not eventual. The most important derived chains cascade upward through the inventory hierarchy: a slot's `on_hand` is the sum of `remaining_units` over that slot's non-expired, available lots; a machine's stock posture is then derived from the aggregate fill across that machine's slots. Whenever inventory changes — a sale draws lots down, a spoilage purge zeroes expired lots, a reconcile creates new lots, or a void restores units — the server re-derives the affected slot's `on_hand` (cascade hop), then re-derives the owning machine's `stock_status` (a further cascade hop). Any such re-derivation that mutates a resource refreshes that resource's `updated_at` and increments its `version`, except where a specific workflow in Section 3 prescribes its own version handling.

Likewise, a machine's `cash_on_hand_cents` is a computed running total that rises on cash sales and is emptied to zero on a cash collection, and `cash_status` is derived from it. A host's `lifetime_commission_cents` is a computed running sum maintained as statements finalize. Section 3 specifies exactly when each of these recomputations fires.

### 2.6. Nested Resource Retrieval and Path Validation

Many endpoints address nested or referenced resources through path identifiers. When a path contains a resource identifier, the system validates existence left-to-right and rejects the request at the first identifier that does not resolve, returning the not-found error specific to that resource type — `ERR_HOST_SITE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, or `ERR_TICKET_NOT_FOUND`, each carrying HTTP 404. The same not-found discipline applies to body foreign keys on creation: when a POST payload references a `machine_id`, `slot_id`, `product_id`, `host_site_id`, `route_id`, `driver_id`, or `route_stop_id` that does not exist, the request is rejected with the corresponding not-found error.

Several list endpoints exist purely to make a child reachable from its parent or from a referenced entity (reverse-reachability). Slots can be listed under a machine or filtered by `machine_id` or `product_id`; lots can be listed under a slot or filtered by `slot_id`, `machine_id`, or `restock_visit_id`; stops can be listed under a route or filtered by `machine_id` or `route_id`; visits can be filtered by `route_stop_id` or `machine_id`; sales can be filtered by `machine_id` or `slot_id`; service tickets can be listed under a machine or filtered by `machine_id`; routes can be filtered by `driver_id`; machines can be filtered by `host_site_id`; and statements can be filtered by `host_site_id`.

### 2.7. Monetary Precision and Rounding

All monetary amounts are integer cents. Rates and fractions (commission percentages, threshold percentages) are stored as decimal fractions. Wherever a calculation produces a non-integer cent amount, the system rounds to whole cents using the round-half-up method. The precise point at which rounding is applied differs between calculations and is specified in Section 3 — some calculations round once at the end of a summation, while others round each component before summing — and these orderings are deliberate and load-bearing, not interchangeable.

### 2.8. Input Validation and Uniqueness

Malformed requests — a missing required field, a wrong type, or an unparseable body — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). When an enum-typed field carries a value outside its declared set, the request is rejected with `ERR_INVALID_ENUM` (HTTP 422). Several fields must be unique within their scope: a `Product`'s `sku` is unique across all products and a duplicate is rejected with `ERR_DUPLICATE_SKU` (HTTP 422); a `Machine`'s `asset_tag` is unique across all machines and a duplicate is rejected with `ERR_DUPLICATE_ASSET_TAG` (HTTP 422); and a `PlanogramSlot`'s `slot_code` is unique within its machine, with a duplicate folded into `ERR_INVALID_SLOT_CONFIG` (HTTP 422) as described in Section 3.

### 2.9. Validation Ordering

When several checks guard one operation, the system evaluates them in a fixed precedence so that a higher-level failure always surfaces before a lower-level one. The order is: first, user-context presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT`); second, role authorization for the operation (`ERR_FORBIDDEN_ROLE`); third, existence of every path-referenced resource, validated left-to-right (the relevant not-found error); fourth, existence of every body foreign key (the relevant not-found error); fifth, the target resource being in the correct state for the requested transition (the relevant state error at HTTP 409, such as `ERR_VISIT_NOT_DRAFT`, `ERR_STATEMENT_NOT_OPEN`, `ERR_TICKET_NOT_OPEN`, or `ERR_SALE_NOT_SETTLED`); and finally, the operation-specific business rules. Within the business-rule tier, the operation-specific subsections of Section 3 state any further relative ordering that matters.

### 2.10. Optimistic Concurrency Control on Machines

The machine record is the concurrency anchor of the system. One write operation participates in optimistic concurrency control: reconciling a restock visit. A reconcile request must carry `expected_machine_version`, a non-optional field holding the `version` of the target machine that the driver last observed when the counts were captured. At reconcile time the system compares `expected_machine_version` to the machine's current `version`. If another writer has advanced the machine's `version` since the driver last read it — for example, a sale-driven posture change or an earlier reconcile — the values no longer match, and the reconcile is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412). This prevents a driver whose `counted_lines` reflect a stale on-hand baseline from double-applying a refill against an inventory picture that has already moved. No other endpoint takes a version field; only the reconcile operation is version-guarded.

### 2.11. The Logical Clock

Expiration stamping and spoilage are driven by a server-side logical clock rather than wall-clock time, so that lot lifecycles can be exercised deterministically. An administrative test-driving capability sets this clock to a supplied UTC instant via the `to_iso8601` field. The clock value at the moment a lot is filled, combined with the product's shelf life, determines that lot's expiration; the clock value at the moment of a spoilage sweep determines which lots have expired. Both behaviors are detailed in Section 3.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Host Sites and Products

A `HostSite` represents a physical location that hosts machines and is owed commission. When a host site is created, a `FieldOps` operator supplies its `name` and its billing `contact_email`, and may supply a `commission_model`, a `flat_commission_pct`, and a `monthly_guarantee_cents`. The `commission_model` is one of `FLAT` or `TIERED` and defaults to `FLAT`; it selects which branch of the commission computation applies. The `flat_commission_pct` is the fraction (in the range from 0 through 1 inclusive) applied to gross sales when the model is `FLAT`, and defaults to 0.10. The `monthly_guarantee_cents` is the minimum commission, in integer cents no less than zero, the host is guaranteed regardless of sales, and defaults to 0. On creation the host's `status` is set to `ACTIVE` and its read-only `lifetime_commission_cents` is initialized to 0. The host's `status` is one of `ACTIVE` or `SUSPENDED`.

A host may be suspended by a `FieldOps` operator, which sets its `status` to `SUSPENDED`. A `SUSPENDED` host blocks two operations: placing a new machine at that host, and opening a new commission statement for it. Both are rejected with `ERR_HOST_SUSPENDED` (HTTP 409). The `lifetime_commission_cents` field is read-only and reflects the running sum of finalized statement net commissions for the host, as described in Section 3.7.

A `Product` is a catalog item. On creation a `FieldOps` operator supplies the `sku` (a stable code, unique across all products), the display `name`, the `category`, the `unit_cost_cents` (wholesale cost per unit, which must be greater than zero), and optionally the `shelf_life_days`. The `category` is one of `BEVERAGE`, `SNACK`, or `FRESH_FOOD`; `FRESH_FOOD` is perishable and, as Section 3.7 explains, is excluded from the tiered commission base. The `shelf_life_days` is the number of days from production to expiration and defaults to 0, where 0 means the product is non-perishable and no expiration is tracked for it. A product is created with `status` set to `ACTIVE`, one of `ACTIVE` or `DISCONTINUED`.

A `FieldOps` operator may update a product's wholesale cost, supplying a new `unit_cost_cents`. This change affects only lots filled after the change: existing lots retain the cost they snapshotted at fill time, so a single slot can hold lots of differing cost after a re-price. A `FieldOps` operator may also discontinue a product, setting its `status` to `DISCONTINUED`. A `DISCONTINUED` product cannot be assigned to a new planogram slot; attempting to do so is rejected with `ERR_PRODUCT_DISCONTINUED` (HTTP 409).

### 3.2. Machines and Their Three-Dimensional Posture

A `Machine` is placed at a host by a `FieldOps` operator, who provides the `host_site_id` of the hosting location, an `asset_tag` (the physical tag, unique across all machines), and a `machine_type` of `SNACK_VENDOR`, `BEVERAGE_VENDOR`, or `MICRO_MARKET_KIOSK`. The operator may also supply `cash_capacity_cents` (the vault capacity in cents, which must be greater than zero, defaulting to 50000), `cash_alert_threshold_pct` (the fraction of capacity at which the cash posture flips to its warning state, in the range above 0 through 1 inclusive, defaulting to 0.80), and `par_fill_threshold_pct` (the fraction of total slot capacity at or below which the stock posture flips to low, strictly between 0 and 1, defaulting to 0.25). Placement against a `SUSPENDED` host is refused as described in Section 3.1. A freshly placed machine has no slots, so its `stock_status` is `STOCKOUT`, its `cash_status` is `CASH_OK`, its `service_status` is `IN_SERVICE`, and its `cash_on_hand_cents` is 0.

A machine carries three independent status dimensions that evolve separately. The **stock dimension**, `stock_status`, is one of `STOCKED`, `LOW_STOCK`, or `STOCKOUT`. The **cash dimension**, `cash_status`, is one of `CASH_OK` or `CASH_FULL_WARN`. The **service dimension**, `service_status`, is one of `IN_SERVICE` or `FROZEN`. All three are read-only and system-derived.

The stock dimension is re-derived on every inventory mutation. Define the aggregate fill ratio as the sum of `on_hand` across the machine's `ACTIVE` slots divided by the sum of `capacity` across those same `ACTIVE` slots. When a machine is `STOCKED` and an inventory mutation (a sale settling, a lot purge, or a visit reconciling) drops the aggregate fill ratio to at or below `par_fill_threshold_pct` while the total on-hand across active slots is still greater than zero, the machine transitions `STOCKED → LOW_STOCK`. When an inventory mutation brings the total on-hand across all `ACTIVE` slots to exactly zero, the machine transitions `LOW_STOCK → STOCKOUT`. When a reconcile raises the aggregate fill ratio strictly above `par_fill_threshold_pct`, the machine transitions `STOCKOUT → STOCKED`.

The cash dimension reacts to cash sales and collections. Let the alert level be the floor of `cash_alert_threshold_pct` multiplied by `cash_capacity_cents`. When a cash sale settles and pushes `cash_on_hand_cents` to at or above that alert level, the machine transitions `CASH_OK → CASH_FULL_WARN`; the boundary is inclusive, so at exactly the alert level the machine warns. When a `FieldOps` operator records a cash collection, the vault's `cash_on_hand_cents` is reset to 0 and the machine transitions `CASH_FULL_WARN → CASH_OK`; a cash collection also increments the machine's `version` by one. After any cash mutation the cash posture is recomputed: if `cash_on_hand_cents` is at or above the alert level the status is `CASH_FULL_WARN`, otherwise it is `CASH_OK`.

The service dimension is driven by blocking service tickets, covered in Section 3.8. When a `ServiceTicket` marked as blocking enters an open state, the machine transitions `IN_SERVICE → FROZEN`; when the last such blocking ticket is resolved away, the machine transitions `FROZEN → IN_SERVICE`. A `FROZEN` machine blocks sales and restock reconciles, as the relevant subsections specify.

### 3.3. Planogram Slots and Inventory Lots

A planogram slot is added to a machine by a `FieldOps` operator, who supplies the `product_id` to assign, a `slot_code` (the coordinate such as A1, unique within the machine), the `capacity` (maximum units the slot holds, greater than zero), the `par_level` (the target unit count after restock, greater than zero and no greater than `capacity`), and the `price_cents` (retail price per unit, greater than zero). The slot's configuration is validated as a unit: `par_level` must not exceed `capacity`, `capacity` must be positive, `price_cents` must be positive, and `slot_code` must be unique within the machine; any violation is rejected with `ERR_INVALID_SLOT_CONFIG` (HTTP 422). The assigned product must be `ACTIVE`, or the request is refused with `ERR_PRODUCT_DISCONTINUED`. A new slot starts with `on_hand` at 0 and `status` `ACTIVE` (one of `ACTIVE` or `RETIRED`), and its addition triggers a re-derivation of the owning machine's `stock_status`. A `RETIRED` slot rejects sales and restock. A `FieldOps` operator may change a slot's retail price by supplying a new `price_cents`; this does not retro-price prior sales.

The slot's `on_hand` is read-only: it is the sum of `remaining_units` across the slot's non-expired, available lots. An `InventoryLot` is a physical batch of units placed into a slot. A lot records the `slot_id` of its slot, a denormalized `machine_id` copied from that slot, the `filled_units` placed when the lot was created (greater than zero), and the `restock_visit_id` of the visit that placed it. At fill time the system snapshots `unit_cost_cents` from the slot's product's current `unit_cost_cents`, and this snapshot is immutable — which is why re-pricing a product yields lots of differing cost within one slot. The lot's `remaining_units` is read-only, starting at the filled count and decremented FIFO by sales and zeroed when the lot spoils. The lot's `expiration_date` is computed at fill time as the logical clock at the moment of fill plus the product's `shelf_life_days`; when `shelf_life_days` is 0 the `expiration_date` is null. A lot's `status` is one of `AVAILABLE`, `DEPLETED`, or `SPOILED`: it becomes `DEPLETED` when `remaining_units` reaches zero and `SPOILED` when purged past expiration.

A `FieldOps` operator may run a spoilage purge on a machine, which sweeps lots at the current logical clock. Every `AVAILABLE` lot whose `expiration_date` is at or before the current clock has its `remaining_units` set to 0 and its `status` set to `SPOILED` (the first cascade hop); the system then recomputes each affected slot's `on_hand` (the second cascade hop) and re-derives the machine's `stock_status` (the third cascade hop).

### 3.4. Drivers, Routes, and Stops

A `RouteDriverProfile` is created by a `FieldOps` operator with a `full_name` and an `employee_code` (a stable code, unique across drivers). A driver starts `ACTIVE`, one of `ACTIVE` or `INACTIVE`; an `INACTIVE` driver cannot be assigned to a new route, as enforced at dispatch.

A `RestockRoute` is created by a `FieldOps` operator who supplies the `driver_id` of the assigned driver and the `service_date` (the ISO 8601 date the route is scheduled to run). A route's `status` is one of `DRAFT`, `DISPATCHED`, or `CLOSED`, beginning at `DRAFT`. A `DRAFT` route accepts stop edits; `DISPATCHED` locks the pre-kit; `CLOSED` is terminal.

A `RouteStop` is added to a `DRAFT` route by a `FieldOps` operator, who supplies the `machine_id` of the machine to be serviced and the service window, expressed as `window_start_min` and `window_end_min` (minutes from midnight on the route's service date). The window opens at `window_start_min` (at least 0 and less than 1440) and closes, exclusively, at `window_end_min` (greater than `window_start_min` and no greater than 1440), so a window is the half-open interval from start up to but not including end. A stop's `prekit_json` is a read-only map from slot identifier to recommended fill units, populated at dispatch. A stop's `status` is one of `PLANNED`, `KITTED`, `VISITED`, or `SKIPPED`, beginning at `PLANNED`.

The system enforces that a new stop's service window must not overlap any other stop assigned to the same driver on the same service date. Because windows are half-open, two stops whose windows merely touch at a shared endpoint do not overlap and are allowed; any true overlap is rejected with `ERR_DRIVER_WINDOW_OVERLAP` (HTTP 409). Overlap is evaluated against the driver carried by the stop's route, considering only stops sharing that driver and that `service_date`.

Dispatching a route is a `FieldOps` action that advances the route `DRAFT → DISPATCHED`. Dispatch requires that the route have at least one stop, or it is rejected with `ERR_ROUTE_EMPTY` (HTTP 409), and that the assigned driver be `ACTIVE`, or it is rejected with `ERR_DRIVER_INACTIVE` (HTTP 409). On dispatch, for each stop the system computes `prekit_json` as a map whose entries are, for each `ACTIVE` slot on the stop's machine, the slot identifier paired with the larger of zero and the difference between that slot's `par_level` and its current `on_hand`. Each stop then moves to `KITTED`, and the route becomes `DISPATCHED`.

Closing a route is a `FieldOps` action that advances `DISPATCHED → CLOSED`. Closing requires that every stop be either `VISITED` or `SKIPPED`; if any stop remains unresolved the close is rejected with `ERR_STOPS_UNRESOLVED` (HTTP 409).

### 3.5. Restock Visits: Reconciliation and Shrink

A `RouteDriver` opens a restock visit against a kitted stop by supplying the `route_stop_id` of the stop being executed, the `counted_lines` (the driver-entered list of objects, each carrying a `slot_id`, a `physical_count`, and a number of `refill_units`), and the `expected_machine_version` capturing the machine `version` the driver observed. The visit also stores a denormalized `machine_id` copied from the stop, read-only `total_shrink_units` and `shrink_value_cents` (computed at reconcile, not at open), and a `status` of one of `DRAFT`, `RECONCILED`, or `REJECTED`, beginning at `DRAFT`. The terminal outcomes `RECONCILED` and `REJECTED` represent the apply and discard branches respectively.

Reconciling a visit is a `RouteDriver` action that advances the visit `DRAFT → RECONCILED`. Reconcile is the most heavily guarded operation in the system, and its checks layer on top of the generic ordering in Section 2.9. Beyond user-context, authorization, and existence, reconcile requires: the parent route to be `DISPATCHED`, or it is rejected with `ERR_ROUTE_NOT_DISPATCHED` (HTTP 409); the visit itself to still be `DRAFT`, or it is rejected with `ERR_VISIT_NOT_DRAFT` (HTTP 409); the machine's `service_status` to be `IN_SERVICE`, or — because a `FROZEN` machine refuses reconciles — it is rejected with `ERR_MACHINE_FROZEN` (HTTP 409); the `expected_machine_version` to match the machine's current `version`, or it is rejected with `ERR_STALE_MACHINE_VERSION` (HTTP 412) per the optimistic concurrency rule in Section 2.10; every `slot_id` named in `counted_lines` to belong to this visit's machine and to be `ACTIVE`, or it is rejected with `ERR_SLOT_NOT_ON_MACHINE` (HTTP 409); and, for each line, the sum of its `refill_units` and its `physical_count` to be no greater than the slot's `capacity`, or it is rejected with `ERR_SLOT_OVERFILL` (HTTP 422).

When all checks pass, reconcile computes shrink and then applies refills as a cascade. Shrink is computed per line and summed: for each counted line, the theoretical count is the slot's `on_hand` as the system tracked it before this visit applies; the line's shrink units are the larger of zero and the theoretical count minus the line's `physical_count`; and the line's shrink value is those shrink units multiplied by the slot's current `price_cents`, valuing each shrunk unit at lost retail revenue. The visit's `total_shrink_units` is the sum of the per-line shrink units, and its `shrink_value_cents` is the sum of the per-line shrink values; the per-line multiply-then-sum order is fixed. Then, for each line whose `refill_units` is greater than zero, the system creates an `InventoryLot` with `filled_units` equal to that line's `refill_units`, `unit_cost_cents` snapshotted from the slot's product's current `unit_cost_cents`, `expiration_date` computed from the current clock plus the product's `shelf_life_days`, and `status` `AVAILABLE` (cascade hop one). The system then recomputes each touched slot's `on_hand` from its lots (cascade hop two), re-derives the machine's `stock_status` from aggregate fill (cascade hop three), increments the machine's `version` by one, and sets the parent stop's `status` to `VISITED`.

Rejecting a visit is a `FieldOps` action that advances `DRAFT → REJECTED`; it requires the visit to still be `DRAFT`, or it is rejected with `ERR_VISIT_NOT_DRAFT`. A rejection is a pure revert: no lots are created and neither the slots nor the machine are mutated, but the parent stop's `status` is set to `SKIPPED`.

### 3.6. Sales: FIFO Consumption, Pricing, and Voids

A sale is recorded by a `FieldOps` operator or a `HostManager` (the host's own kiosk staff). The caller supplies the `machine_id` and `slot_id` being vended, the `quantity` purchased (greater than zero), the `payment_method` of `CASHLESS` or `CASH`, and optionally a `settlement_status` of `SETTLED` or `VOID`, which defaults to `SETTLED`. A sale on a `FROZEN` machine is refused with `ERR_MACHINE_FROZEN`. The referenced slot must belong to the target machine and be `ACTIVE`, or the sale is refused with `ERR_SLOT_NOT_ON_MACHINE`. The requested `quantity` must not exceed the slot's `on_hand` (the sum of `remaining_units` across the slot's `AVAILABLE` lots); if the FIFO walk runs short, the sale is refused with `ERR_INSUFFICIENT_STOCK` (HTTP 409).

On a settling sale the system snapshots `unit_price_cents` from the slot's current `price_cents`, and computes `gross_cents` as `quantity` multiplied by `unit_price_cents`. It computes the read-only `provisional_cogs_cents` using a slot weighted-average cost taken over the slot's `AVAILABLE` lots before this sale draws anything down: the average cost is the sum, over those available lots, of each lot's `remaining_units` multiplied by its own snapshot `unit_cost_cents`, divided by the sum of `remaining_units` across those lots, with that average rounded half-up to whole cents; the provisional cost of goods is then that rounded average multiplied by `quantity`. This provisional figure deliberately ignores which specific lots FIFO will actually consume.

The sale then draws inventory FIFO. The slot's `AVAILABLE` lots are ordered by `expiration_date` ascending with null expirations last, breaking ties by `created_at` ascending (never by `id`). Walking that order, the sale takes from each lot the smaller of the remaining quantity to fill and that lot's `remaining_units`, decrements the lot's `remaining_units` by the amount taken, marks the lot `DEPLETED` when its `remaining_units` reaches zero, and appends a record of the lot identifier and units taken to the sale's read-only `lot_consumption_json`; it continues to the next lot until the requested quantity is satisfied. After the draw, the slot's `on_hand` is recomputed and the machine's `stock_status` re-derived. If the `payment_method` is `CASH`, the machine's `cash_on_hand_cents` is increased by `gross_cents` and the cash posture is re-derived, possibly tripping the `CASH_FULL_WARN` warning.

The final realized cost of goods differs from the provisional figure: while the provisional cost uses the slot's weighted-average lot cost at sale time, the final realized cost walks the actual FIFO consumption recorded in `lot_consumption_json` (oldest expiration first), so two otherwise-identical sales can yield different realized totals when the lots they consume carry different `unit_cost_cents`.

A settled sale may be voided by a `FieldOps` operator, which advances the sale `SETTLED → VOID`; it requires the sale's `settlement_status` to be `SETTLED`, or it is rejected with `ERR_SALE_NOT_SETTLED` (HTTP 409). A void is a full compensating reversal: it restores `remaining_units` to each lot recorded in `lot_consumption_json` (reversing the FIFO draw), reverts to `AVAILABLE` any lot that this sale had marked `DEPLETED`, recomputes the affected slot's `on_hand`, and re-derives the machine's `stock_status`. If the voided sale's `payment_method` was `CASH`, the machine's `cash_on_hand_cents` is decreased by `gross_cents` and the cash posture is re-derived.

### 3.7. Commission Statements and the Host Ledger

A `FinanceClerk` opens a commission statement for a host by supplying the `host_site_id`, a `period_start` (inclusive ISO 8601 instant), and a `period_end` (exclusive ISO 8601 instant, strictly after `period_start`). The host must be `ACTIVE`, or the open is refused with `ERR_HOST_SUSPENDED`. A host's statements may not overlap in time: the half-open period from `period_start` up to but not including `period_end` must not overlap an existing statement for the same `host_site_id`, although an existing statement whose `period_end` equals the new `period_start` is allowed (touching boundaries do not overlap). A true overlap is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (HTTP 409). A statement begins with `status` `OPEN`, one of `OPEN` or `FINALIZED`, and its monetary amounts are all read-only.

While a statement is `OPEN`, its four computed amounts — `gross_sales_cents`, `shrink_chargeback_cents`, `gross_commission_cents`, and `net_commission_cents` — are recomputed live on every read, and they are recomputed again when the statement finalizes. The `gross_sales_cents` is the sum of `gross_cents` over the `SETTLED` sales on this host's machines whose sale falls within the period.

The `gross_commission_cents` branches on the host's `commission_model`. Under `FLAT`, it is the host's `gross_sales_cents` multiplied by `flat_commission_pct`, rounded half-up to whole cents. Under `TIERED`, the system first forms a tiered base equal to the sum of `gross_cents` over the period's `SETTLED` sales whose slot's product `category` is not `FRESH_FOOD` (fresh food is excluded from the tiered base), then applies marginal band rates to that base: the portion of the tiered base from 0 up to but not including 500000 cents (that is, 5,000 dollars) is paid at 8 percent; the portion from 500000 cents up to but not including 1500000 cents (that is, 15,000 dollars) is paid at 12 percent; and any portion at or above 1500000 cents is paid at 15 percent. The three band contributions are summed and the total is rounded half-up to whole cents exactly once at the end (sum-then-round).

The `shrink_chargeback_cents` is the host-borne share of shrink over the period. The host bears one half of shrink value. For each `RECONCILED` restock visit on this host's machines whose reconcile time (its `updated_at`) falls within the period, the system takes that visit's `shrink_value_cents`, multiplies by the one-half host share, and rounds that product half-up to whole cents; it then sums those per-visit rounded chargebacks. This rounding order — round each visit's chargeback to cents, then sum — is the opposite of the commission's sum-then-round order, and the two must not be conflated.

The `net_commission_cents` is computed last, after both `gross_commission_cents` and `shrink_chargeback_cents` are known. The raw net is `gross_commission_cents` minus `shrink_chargeback_cents`, and the net commission is the larger of that raw net and the host's `monthly_guarantee_cents`, so the guarantee acts as a floor.

Finalizing a statement is a `FinanceClerk` action that advances `OPEN → FINALIZED`. It requires the statement to be `OPEN`, or it is rejected with `ERR_STATEMENT_NOT_OPEN`, and it requires that no restock visit on this host's machines within the period still be in `DRAFT`, or it is rejected with `ERR_VISITS_PENDING` (HTTP 409). On finalize the four amounts are recomputed and frozen, the host's `lifetime_commission_cents` is increased by this statement's `net_commission_cents` (a ledger-sync cascade onto the host), and the statement's `status` becomes `FINALIZED`.

### 3.8. Service Tickets and Machine Freezing

A service ticket is opened against a machine by a `FieldOps` operator or a `HostManager`. The opener supplies the `issue_type` — one of `JAM`, `TELEMETRY_ALERT`, `VANDALISM`, or `COIN_MECH` — and may supply a `blocking` boolean that defaults to false. A ticket's `status` is one of `OPEN`, `IN_PROGRESS`, `RESOLVED`, or `REOPENED`, beginning at `OPEN`. When a blocking ticket enters an open state, the machine's `service_status` is forced to `FROZEN`. The freezing rule is keyed off the existence of any blocking ticket in an active state: a machine is `FROZEN` whenever at least one of its tickets has `blocking` true and a `status` of `OPEN`, `IN_PROGRESS`, or `REOPENED`, and returns to `IN_SERVICE` only once no such ticket remains.

Ticket handling is cyclic. A `FieldOps` operator starts work on a ticket, which advances it `OPEN → IN_PROGRESS`; this requires the ticket to be `OPEN`, or it is rejected with `ERR_TICKET_NOT_OPEN`. The same start action also advances a reopened ticket `REOPENED → IN_PROGRESS`; taken from the reopened path it requires the ticket to be `REOPENED`, or it is rejected with `ERR_TICKET_NOT_REOPENED`. A `FieldOps` operator resolves an in-progress ticket, advancing it `IN_PROGRESS → RESOLVED`; this requires the ticket to be `IN_PROGRESS`, or it is rejected with `ERR_TICKET_NOT_IN_PROGRESS`, and on resolution, if no other blocking ticket remains in `OPEN`, `IN_PROGRESS`, or `REOPENED` on the machine, the machine's `service_status` returns to `IN_SERVICE`. A `FieldOps` operator reopens a resolved ticket for a recurring fault, advancing it `RESOLVED → REOPENED`; this requires the ticket to be `RESOLVED`, or it is rejected with `ERR_TICKET_NOT_RESOLVED`, and if the reopened ticket is blocking the machine's `service_status` is forced back to `FROZEN`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/operations` prefix. Successful creation of a new resource returns HTTP 201; successful reads and modifications (including state transitions and other mutations that do not create a new resource) return HTTP 200. Request bodies, computed responses, and side effects are described in Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/operations/host-sites` | Create a host site | FieldOps |
| GET | `/operations/host-sites` | List host sites | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/host-sites/{hostSiteId}` | Get a host site | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/host-sites/{hostSiteId}/suspend` | Suspend a host site | FieldOps |
| POST | `/operations/products` | Create a catalog product | FieldOps |
| GET | `/operations/products` | List products | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/products/{productId}` | Get a product | FieldOps, RouteDriver, HostManager, FinanceClerk |
| PATCH | `/operations/products/{productId}/cost` | Update a product's wholesale unit cost | FieldOps |
| POST | `/operations/products/{productId}/discontinue` | Discontinue a product | FieldOps |
| POST | `/operations/machines` | Place a machine at a host site | FieldOps |
| GET | `/operations/machines` | List machines (filterable by host site) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/machines/{machineId}` | Get a machine (includes derived posture and version) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/machines/{machineId}/cash-collections` | Record a cash collection (empties the vault) | FieldOps |
| POST | `/operations/machines/{machineId}/slots` | Add a planogram slot to a machine | FieldOps |
| GET | `/operations/machines/{machineId}/slots` | List slots on a machine | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/slots` | List slots (filter by machine or product) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/slots/{slotId}` | Get a slot (includes derived on-hand) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| PATCH | `/operations/slots/{slotId}/price` | Change a slot's retail price | FieldOps |
| GET | `/operations/slots/{slotId}/lots` | List inventory lots in a slot | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/lots` | List inventory lots (filter by slot, machine, or visit) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/lots/{lotId}` | Get a lot | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/machines/{machineId}/spoilage-purge` | Purge expired lots on a machine | FieldOps |
| POST | `/operations/drivers` | Create a route driver profile | FieldOps |
| GET | `/operations/drivers` | List drivers | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/drivers/{driverId}` | Get a driver | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/routes` | Create a restock route | FieldOps |
| GET | `/operations/routes` | List routes (filter by driver) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/routes/{routeId}` | Get a route | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/routes/{routeId}/stops` | Add a stop to a draft route | FieldOps |
| GET | `/operations/routes/{routeId}/stops` | List stops for a route | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/routes/{routeId}/dispatch` | Dispatch a route: compute pre-kits and lock | FieldOps |
| POST | `/operations/routes/{routeId}/close` | Close a dispatched route once all stops resolved | FieldOps |
| GET | `/operations/stops` | List route stops (filter by machine or route) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/stops/{stopId}` | Get a route stop | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/restock-visits` | Open a draft restock visit for a kitted stop | RouteDriver |
| GET | `/operations/restock-visits` | List restock visits (filter by stop or machine) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/restock-visits/{visitId}` | Get a restock visit | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/restock-visits/{visitId}/reconcile` | Reconcile a visit: apply refills, compute shrink, advance machine | RouteDriver |
| POST | `/operations/restock-visits/{visitId}/reject` | Reject a draft visit (no inventory applied) | FieldOps |
| POST | `/operations/sales` | Record a cashless or cash sale | FieldOps, HostManager |
| GET | `/operations/sales` | List sales (filter by machine or slot) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/sales/{saleId}` | Get a sale (includes lot consumption and provisional cost) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/sales/{saleId}/void` | Void a settled sale (compensating reversal) | FieldOps |
| POST | `/operations/commission-statements` | Open a commission statement for a host over a period | FinanceClerk |
| GET | `/operations/commission-statements` | List commission statements (filter by host) | FieldOps, HostManager, FinanceClerk |
| GET | `/operations/commission-statements/{statementId}` | Get a statement (recomputes amounts while open) | FieldOps, HostManager, FinanceClerk |
| POST | `/operations/commission-statements/{statementId}/finalize` | Finalize a statement: freeze amounts, credit host | FinanceClerk |
| POST | `/operations/machines/{machineId}/service-tickets` | Open a service ticket on a machine | FieldOps, HostManager |
| GET | `/operations/machines/{machineId}/service-tickets` | List service tickets on a machine | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/service-tickets` | List service tickets (filter by machine) | FieldOps, RouteDriver, HostManager, FinanceClerk |
| GET | `/operations/service-tickets/{ticketId}` | Get a service ticket | FieldOps, RouteDriver, HostManager, FinanceClerk |
| POST | `/operations/service-tickets/{ticketId}/start` | Begin work on an open or reopened ticket | FieldOps |
| POST | `/operations/service-tickets/{ticketId}/resolve` | Resolve an in-progress ticket | FieldOps |
| POST | `/operations/service-tickets/{ticketId}/reopen` | Reopen a resolved ticket | FieldOps |
| POST | `/operations/_clock/set_current_utc` | Test-driving: set the server clock | FieldOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 422 |
| ERR_INVALID_SLOT_CONFIG | 422 |
| ERR_DUPLICATE_SKU | 422 |
| ERR_DUPLICATE_ASSET_TAG | 422 |
| ERR_HOST_SITE_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_MACHINE_NOT_FOUND | 404 |
| ERR_SLOT_NOT_FOUND | 404 |
| ERR_LOT_NOT_FOUND | 404 |
| ERR_DRIVER_NOT_FOUND | 404 |
| ERR_ROUTE_NOT_FOUND | 404 |
| ERR_STOP_NOT_FOUND | 404 |
| ERR_VISIT_NOT_FOUND | 404 |
| ERR_SALE_NOT_FOUND | 404 |
| ERR_STATEMENT_NOT_FOUND | 404 |
| ERR_TICKET_NOT_FOUND | 404 |
| ERR_VISIT_NOT_DRAFT | 409 |
| ERR_ROUTE_NOT_DISPATCHED | 409 |
| ERR_ROUTE_EMPTY | 409 |
| ERR_STOPS_UNRESOLVED | 409 |
| ERR_DRIVER_INACTIVE | 409 |
| ERR_STATEMENT_NOT_OPEN | 409 |
| ERR_VISITS_PENDING | 409 |
| ERR_SALE_NOT_SETTLED | 409 |
| ERR_TICKET_NOT_OPEN | 409 |
| ERR_TICKET_NOT_REOPENED | 409 |
| ERR_TICKET_NOT_IN_PROGRESS | 409 |
| ERR_TICKET_NOT_RESOLVED | 409 |
| ERR_MACHINE_FROZEN | 409 |
| ERR_SLOT_NOT_ON_MACHINE | 409 |
| ERR_PRODUCT_DISCONTINUED | 409 |
| ERR_SLOT_OVERFILL | 422 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_DRIVER_WINDOW_OVERLAP | 409 |
| ERR_STATEMENT_PERIOD_OVERLAP | 409 |
| ERR_HOST_SUSPENDED | 409 |
| ERR_STALE_MACHINE_VERSION | 412 |
