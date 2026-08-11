# Lab Reagent Cold Chain API — Product Requirements Document

## 1. Introduction

A laboratory supply distributor lives and dies by two promises: the right reagent arrives at the right bench, and nothing about its journey — temperature, handling, provenance — is ever in doubt. This document specifies the Lab Reagent Cold Chain API, the operational backbone for such a distributor. The system models the full physical loop of reagent supply: warehouses and their controlled-temperature storage zones, catalog products with hazardous-material classifications, physical reagent lots tracked by receipt sequence and expiry, customer orders allocated against that lot inventory, and shipments whose temperature telemetry is audited in transit. Because the catalog includes flammable, corrosive, toxic, and oxidizing chemicals, every shipment is additionally screened against per-class and aggregate hazardous-load limits before it may leave the dock.

On top of this physical core sit the commercial mechanisms that distinguish a distribution business from a warehouse: customer accounts with credit limits and volume discounts, standing orders that regenerate supply on a calendar, consignment agreements that bill only for consumed stock and replenish it automatically, and custom assay kits assembled from component lots. Quality governance runs through everything — a product recall must reach through quarantined lots, held reservations, and allocated orders in a single cascade, and a temperature excursion in transit must be able to reverse an invoice. Time itself is a controlled input: the server maintains a logical clock that drives lot expiry and standing-order generation, so the platform's behavior is deterministic and testable. Every mutation in the system is immediately visible in the response that performs it; there is no eventual-consistency window anywhere in this API.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting party and `X-User-Role` to declare the operational capacity in which they act. The system recognizes exactly six roles: `OpsAdmin`, `CatalogManager`, `InventoryClerk`, `QualityManager`, `AccountManager`, and `Customer`. A request in which either header is missing, or in which `X-User-Role` is not one of these six values, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the context is accepted, each operation is restricted to a designated role list; an authenticated caller whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a `CustomerAccount` compare the resource's `customer_id` field to `X-User-ID`. This ownership rule guards every customer-scoped mutation — submitting, reallocating, or cancelling an order, releasing a reservation, creating or pausing or resuming or cancelling a standing order, and recording consignment consumption — and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_VIOLATION` (HTTP 403). When the target resource id in such a request does not exist at all, ownership is unevaluable and the existence check described in §2.6 reports the per-resource 404 instead. The same scoping applies to reads: whenever a listed entity carries a `customer_id` field, a `Customer`-role caller sees only rows whose `customer_id` equals their `X-User-ID`, while the five operations roles see all rows.

When `X-User-Role` is `OpsAdmin`, `CatalogManager`, `InventoryClerk`, `QualityManager`, or `AccountManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes, but it never compares it to any entity's `id`, and no ownership scoping applies to these roles' reads or writes.

In brief: `OpsAdmin` operates the distribution network itself (warehouses, storage zones, and the logical clock); `CatalogManager` stewards the product catalog and kit definitions; `InventoryClerk` works the warehouse floor (lot receipt and adjustment, shipments, kit assembly); `QualityManager` owns quarantine, recalls, and excursion disposition; `AccountManager` owns customer accounts, payments, and consignment agreements; and `Customer` places and manages its own orders and standing orders. The full operation-by-operation mapping appears in §4.

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

### 2.3. Pagination and List Filtering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Each list endpoint additionally accepts equality filters drawn from its resource's own fields. The warehouse list accepts `status`; the storage-zone list accepts `warehouse_id` and `zone_class`; the product list accepts `status` and `hazard_class`; the lot list accepts `product_id`, `warehouse_id`, `storage_zone_id`, `recall_id`, and `status`; the customer list accepts `status`; the order list accepts `customer_id`, `warehouse_id`, and `status`; the order-line list accepts `order_id`, `product_id`, and `status`; the reservation list accepts `order_line_id`, `lot_id`, and `status`; the shipment list accepts `order_id` and `status`; the excursion list accepts `shipment_id`, `status`, and `severity`; the standing-order list accepts `customer_id`, `product_id`, `warehouse_id`, and `status`; the consignment-agreement list accepts `customer_id`, `product_id`, `replenishment_warehouse_id`, and `status`; the consumption-record list accepts `agreement_id`; the recall list accepts `product_id` and `status`; the kit list accepts `customer_id` and `status`; and the assembly-job list accepts `kit_id`, `warehouse_id`, and `status`.

### 2.4. Common Resource Properties

Every persisted resource carries a standard set of system-managed fields, providing a consistent audit trail and unique addressability:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, including system-driven state transitions applied by cascades.

One resource is deliberately lighter: a `ConsumptionRecord` is an immutable billing fact and carries only `id` and `created_at` — `updated_at` and `version` are absent from it entirely.

### 2.5. The Logical Clock

The server maintains a logical clock that governs every time-dependent rule in the system — lot expiry, standing-order runs, and replenishment ship dates. Before any client sets it, the clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to wall-clock time. An `OpsAdmin` may advance the clock through a test-driving capability that accepts a `to_iso8601` instant. Setting the clock performs two sweeps in its wake: every lot whose `expiry_date` falls before the new current date transitions to `EXPIRED` with the reservation-release cascade described in §3.2, and the standing-order run generation described in §3.8 executes. The capability responds with the new `current_utc` plus three counters: `lots_expired`, `standing_orders_run`, and `orders_generated`.

### 2.6. Resource Existence and Request Validation Order

Path templates address resources with camelCase identifiers — `warehouseId`, `zoneId`, `productId`, `lotId`, `customerId`, `orderId`, `orderLineId`, `reservationId`, `shipmentId`, `excursionId`, `standingOrderId`, `agreementId`, `recordId`, `recallId`, `kitId`, and `jobId`. The system validates the existence of path identifiers strictly left to right, and body-referenced identifiers in the endpoint's declared input order; the first missing reference yields that resource's per-type 404. The mapping is one-to-one: a missing warehouse yields `ERR_WAREHOUSE_NOT_FOUND`, a storage zone `ERR_STORAGE_ZONE_NOT_FOUND`, a product `ERR_PRODUCT_NOT_FOUND`, a lot `ERR_LOT_NOT_FOUND`, a customer `ERR_CUSTOMER_NOT_FOUND`, an order `ERR_ORDER_NOT_FOUND`, an order line `ERR_ORDER_LINE_NOT_FOUND`, a reservation `ERR_RESERVATION_NOT_FOUND`, a shipment `ERR_SHIPMENT_NOT_FOUND`, an excursion `ERR_EXCURSION_NOT_FOUND`, a standing order `ERR_STANDING_ORDER_NOT_FOUND`, a consignment agreement `ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND`, a consumption record `ERR_CONSUMPTION_RECORD_NOT_FOUND`, a recall `ERR_RECALL_NOT_FOUND`, a kit `ERR_KIT_NOT_FOUND`, and an assembly job `ERR_KIT_ASSEMBLY_JOB_NOT_FOUND`.

All requests are evaluated against a fixed validation priority chain, and a higher-priority failure always masks lower-priority ones — the caller sees exactly one error, from the earliest failing stage:

1. **Context headers** — both headers present and the role declared, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — the role appears in the endpoint's role list, else `ERR_FORBIDDEN_ROLE`.
3. **Customer ownership** — for `Customer`-role mutations, `X-User-ID` must equal the target's `customer_id`, else `ERR_RESOURCE_OWNERSHIP_VIOLATION`; when the target does not exist this stage is skipped and stage 4 reports the 404.
4. **Existence** — path ids left to right, then body-referenced ids in declared input order, each yielding its per-resource 404.
5. **Request well-formedness** — required fields present, types correct, enum members valid, integer fields positive where declared, ISO dates parseable, `effective_until` after `effective_from` where applicable, and no unknown fields, else `ERR_INVALID_REQUEST`.
6. **Optimistic concurrency** — on the three OCC endpoints of §2.7, the expected-version field must match the parent's current `version`, else the corresponding 412.
7. **State-machine validity** — the attempted transition's from-state preconditions, else the per-transition 409 (for example `ERR_ORDER_NOT_SUBMITTABLE`, `ERR_LOT_NOT_QUARANTINED`).
8. **Business rules** — hazmat, cold-chain, recall, temporal, capacity, fiscal, and referential rules, in the domain-priority order stated with each workflow in §3.

### 2.7. Optimistic Concurrency Control

Three write operations legitimately supersede a resource's prior state, and each therefore requires the caller to declare the version it last observed; a fourth class of endpoint — everything not listed here — takes no version field at all.

- `POST /lab/lots/{lotId}/adjustments` requires `expected_lot_version`. When it no longer matches the lot's current `version` — because an earlier adjustment, cascade, or reservation flow already advanced it — the adjustment is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), so the client re-reads before correcting stock.
- `POST /lab/orders/{orderId}/reallocate` requires `expected_order_version`. When it no longer matches the order's current `version` — because an earlier submit, cascade, or reallocate already advanced it — the re-plan is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), so allocations are never rebuilt from an outdated view of the order.
- `PATCH /lab/customers/{customerId}` requires `expected_customer_version`. When it no longer matches the account's current `version` — because an invoice, payment, suspension, or an earlier update already advanced it — the update is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412), so commercial terms are never overwritten from a stale view.

### 2.8. Monetary Precision, Rounding, and Measurement Units

All monetary values are integer cents — unit prices, line totals, freight charges, credits, balances, and payments are never fractional. Wherever a multiplication produces a fractional cent, the value is rounded half up to the nearest whole cent, and rounding is always applied per record before any summation: order line totals are rounded per line and then summed, and consignment charges are rounded per consumption record. Summing first and rounding once is expressly forbidden. Temperatures are carried to a precision of 0.1 degree Celsius, durations in whole minutes, calendar arithmetic in whole ISO days, and physical quantities in whole units.

### 2.9. Cold-Chain Temperature Bands and Storage Compatibility

Each storage classification implies an acceptable temperature band, and these bands anchor both shipment monitoring and putaway compatibility. `AMBIENT` spans 15 to 25 degrees Celsius, `REFRIGERATED_2_8` spans 2 to 8, `FROZEN_MINUS_20` spans −25 to −15, and `ULTRACOLD_MINUS_80` spans −90 to −70. A shipment's monitored band is derived from its order's lines (any status except `CANCELLED`): `temp_min_celsius` is the highest of the lines' band lower bounds, and `temp_max_celsius` is the lowest of the lines' band upper bounds, so the shipment is held to the most restrictive intersection of its contents' needs.

Coldness increases in the order `AMBIENT`, `REFRIGERATED_2_8`, `FROZEN_MINUS_20`, `ULTRACOLD_MINUS_80`. A storage zone is compatible with a product when the zone's `zone_class` is at least as cold as the product's `storage_requirement` — an `AMBIENT` zone may hold only `AMBIENT` product, while an `ULTRACOLD_MINUS_80` zone may hold anything. The same at-or-colder rule governs which lots are eligible to satisfy an order line, as detailed in §3.4.

### 2.10. Hazardous Materials Governance

Every product declares a `hazard_class` of `NON_HAZARDOUS`, `FLAMMABLE`, `CORROSIVE`, `TOXIC`, or `OXIDIZER`, and a `unit_haz_factor` — the hazmat load units each unit of the product contributes, which must be at least 1, defaults to 1, and is ignored for `NON_HAZARDOUS` products. Each product also carries a `max_qty_per_shipment`, a per-product cap on how many units of that product may ride in a single shipment.

Customers are credentialed through a `hazmat_endorsement` ladder: `NONE` permits only `NON_HAZARDOUS` product; `LIMITED` additionally covers `FLAMMABLE` and `CORROSIVE`; `FULL` covers everything, adding `TOXIC` and `OXIDIZER`. Warehouses, symmetrically, may only receive or ship hazardous product when their `hazmat_certified` flag is true.

Shipment-level load limits are absolute. The load of each hazard class — the sum, over lines of that class, of line quantity times the product's `unit_haz_factor` — is capped at 30 units for `FLAMMABLE`, 30 for `CORROSIVE`, 10 for `TOXIC`, and 10 for `OXIDIZER`; the aggregate load across all four classes is capped at 50 units. Dry ice is itself a dangerous good: a shipment cooled by `DRY_ICE` may carry at most 20 coolant units. The enforcement mechanics live with shipment creation in §3.5.

### 2.11. Hierarchical Consistency and Cascading Reconciliation

The system maintains strict alignment across its aggregate boundaries, and reconciliations propagate without requiring an explicit client request on each affected resource. When a lot is quarantined, expires, or is pulled by a recall, every held reservation against it is released with its quantity handed back, the owning order lines recompute their allocation, and orders that fall short demote accordingly. When an excursion is dispositioned against further transit, the effects cascade from the excursion through its shipment and order to the customer's balance. Each reconciliation independently mutates every resource it touches: the resource's own state fields change, its `updated_at` refreshes, and its `version` increments by 1. Consistency is immediate — the response to any request reflects every mutation that request triggered, and a subsequent read of any touched resource observes the reconciled state.

## 3. Business Logic & Workflows

### 3.1. Stocking the Network: Warehouses, Storage Zones, and the Product Catalog

Before a single reagent can move, an `OpsAdmin` builds the physical network. A warehouse is registered with a display `name`, a freight `region_code` such as US-NE, and the `hazmat_certified` flag that determines whether hazardous product may be stored in or shipped from it. A warehouse begins `OPERATIONAL`; the operator may later suspend it, moving `status` from `OPERATIONAL` to `SUSPENDED` (attempting to suspend one that is not `OPERATIONAL` is rejected with `ERR_WAREHOUSE_NOT_OPERATIONAL`), and resume it from `SUSPENDED` back to `OPERATIONAL` (resuming one that is not `SUSPENDED` fails with `ERR_WAREHOUSE_NOT_SUSPENDED`). A suspended warehouse blocks dispatch of its shipments, as §3.5 describes. Both transitions increment the warehouse's `version`.

Within each warehouse, storage zones carve out controlled environments. Creating a zone requires its owning `warehouse_id`, a `zone_class` drawn from the four temperature classifications, a positive `capacity_units` ceiling on total on-hand units, and an optional `rotation_policy` of `FEFO` or `FIFO` that defaults to `FEFO` and drives allocation ranking later. A new zone's `occupied_units` starts at 0 and is thereafter maintained by the system as the sum of `quantity_on_hand` over the lots stored in it whose status is `AVAILABLE` or `QUARANTINED`.

The `CatalogManager` authors the product catalog. Each product is created with a catalog `sku` that must be unique across all products, a display `name`, the coldest acceptable `storage_requirement`, its `hazard_class`, a positive `unit_price_cents`, a `requires_cold_chain` flag marking products that must ship with coolant to a certified customer, a positive `shelf_life_days` spanning manufacture to expiry, and a `min_remaining_shelf_life_days` — defaulting to 7 — that sets how much life a lot must still have, measured from the order's requested ship date to the lot's expiry, to be allocatable. Hazmat-bearing products additionally tune `unit_haz_factor` and declare the positive `max_qty_per_shipment` cap. A product enters the catalog `LISTED`; discontinuation moves it to the terminal `DISCONTINUED` from either `LISTED` or `UNDER_RECALL` — attempting it in any other state is rejected with `ERR_PRODUCT_NOT_LISTED`. The `UNDER_RECALL` state itself is never set by hand: it is entered and left only through the recall machinery of §3.7.

### 3.2. Receiving and Correcting Inventory: Lot Receipt, Rotation, Adjustment, and Quarantine

An `InventoryClerk` receives physical stock by declaring the `product_id`, the `warehouse_id`, the putaway `storage_zone_id`, a positive `quantity_received`, and the `manufacture_date` as an ISO calendar date. Receipt stamps the lot with two derived facts. First, a `lot_sequence_number`: one greater than the highest sequence number among all existing lots of the same product regardless of status, or exactly 1 for the product's first receipt. Second, an `expiry_date`: the `manufacture_date` advanced by the product's `shelf_life_days` in calendar days. A lot is expired when the logical clock's current date is strictly after its `expiry_date`; on the expiry date itself the lot remains usable. The system also records `received_at` from the logical clock, initializes `quantity_on_hand` equal to `quantity_received`, and zeroes `quantity_reserved`, `quantity_consumed`, and `adjustment_total`.

Putaway is guarded by four business checks, evaluated after the generic request validations and in this order: the warehouse must be hazmat-certified when the product's `hazard_class` is anything other than `NON_HAZARDOUS` (`ERR_HAZMAT_WAREHOUSE_NOT_CERTIFIED`); the zone's `zone_class` must be at least as cold as the product's `storage_requirement` per the coldness ordering of §2.9 (`ERR_STORAGE_ZONE_INCOMPATIBLE`); the zone must have room — its `occupied_units` plus the incoming quantity may not exceed `capacity_units`, though a receipt that exactly fills the zone is allowed (`ERR_ZONE_CAPACITY_EXCEEDED`); and the declared `storage_zone_id` must actually belong to the declared `warehouse_id` (`ERR_ZONE_WAREHOUSE_MISMATCH`). A received lot starts `AVAILABLE`, and receipt immediately triggers the backorder waitlist retry described in §3.4.

Stock counts are corrected through adjustments carrying a signed `delta` and a free-text `reason`. Because an adjustment supersedes the lot's prior quantity state, the request must carry `expected_lot_version` per §2.7. The delta is applied to `quantity_on_hand` and accumulated into `adjustment_total`; an adjustment that would drive `quantity_on_hand` below zero is rejected with `ERR_ADJUSTMENT_BELOW_ZERO`. Whenever any flow — allocation, dispatch, adjustment, or kit assembly — drives a lot's `quantity_on_hand` to exactly zero, the lot transitions itself from `AVAILABLE` to `DEPLETED`. Every adjustment recomputes the zone's `occupied_units` and increments the lot's `version`.

Quality intervention on a lot is the `QualityManager`'s province. Quarantining moves a lot from `AVAILABLE` to `QUARANTINED` (a lot in any other state yields `ERR_LOT_NOT_AVAILABLE`) and fires the release cascade: every reservation on that lot still `HELD` transitions to `RELEASED`, each released quantity is subtracted from the lot's `quantity_reserved` and added back to its `quantity_on_hand`, each affected order line recomputes its `allocated_quantity` and demotes from `ALLOCATED` or `PARTIALLY_ALLOCATED` back to `PENDING` whenever the recomputed amount falls below the line's `quantity`, and each order whose lines fell short demotes from `ALLOCATED` to `BACKORDERED`. Releasing quarantine returns the lot from `QUARANTINED` to `AVAILABLE`, but only while no `ISSUED` recall covers it — otherwise the attempt is rejected with `ERR_RECALL_ACTIVE_FOR_LOT` — and only from `QUARANTINED` (`ERR_LOT_NOT_QUARANTINED`). A lot carries the `recall_id` of an issued recall that covers it from issuance until that recall closes and clears the reference. Finally, when the logical clock advances past a lot's `expiry_date`, the expiry sweep moves the lot from `AVAILABLE` to `EXPIRED` and fires exactly the same release-and-demote cascade as quarantine. `QUARANTINED`, `RECALLED`, `DEPLETED`, and `EXPIRED` lots are never allocatable.

### 3.3. Customer Accounts, Commercial Terms, and Credit Discipline

An `AccountManager` opens each laboratory account with a `name`, a positive `credit_limit_cents`, and optional commercial terms: a `volume_discount_pct` — a fractional per-line discount between 0 and 0.5 that defaults to 0 — a `hazmat_endorsement` defaulting to `NONE`, and a `cold_chain_certified` flag defaulting to false. New accounts begin `ACTIVE` with `outstanding_balance_cents` at 0. Commercial terms may later be revised through an update accepting any of `credit_limit_cents`, `volume_discount_pct`, `hazmat_endorsement`, and `cold_chain_certified`; because such an update overwrites negotiated terms, it must carry `expected_customer_version` per §2.7.

The outstanding balance is a derived figure, recomputed from its sources: the sum, over the customer's orders in `SHIPPED` or `DELIVERED` status, of each order's `product_total_cents` plus its shipment's `final_freight_cents`; plus the sum of `charge_cents` over the consumption records of the customer's agreements; minus the sum of `amount_cents` over recorded payments. `REFUNDED` orders contribute nothing — the reversal removes them from the set. A payment recorded with a positive `amount_cents` reduces the balance accordingly, never below a floor of zero.

Credit is enforced at two moments. At order submission, a pre-check requires that the current `outstanding_balance_cents`, plus the projected `product_total_cents` of the order being submitted, plus a projected freight estimate — defined as the base rate of the order's own `shipping_service` computed at zero weight with coolant `NONE`, with no hazmat surcharge, with the freight floor applied, and with the free-freight threshold evaluated against the projected product total — together remain at or below `credit_limit_cents`; otherwise the submit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). And after any dispatch invoice posts, an automatic suspension check runs: when the new `outstanding_balance_cents` is strictly greater than 1.2 times `credit_limit_cents` — computed in integer cents so that a balance exactly equal to that threshold does not suspend — the account transitions itself from `ACTIVE` to `SUSPENDED`.

The account lifecycle is otherwise manual. An `AccountManager` may suspend an `ACTIVE` account (`ERR_CUSTOMER_NOT_ACTIVE` otherwise), reactivate a `SUSPENDED` one — which requires the balance to be back at or under the credit limit, failing with `ERR_OUTSTANDING_ABOVE_LIMIT` when it is not, and with `ERR_CUSTOMER_NOT_SUSPENDED` when the account was not `SUSPENDED` — and close an account from either `ACTIVE` or `SUSPENDED`. Closing is guarded by three business checks in order: no order of the customer may sit in `DRAFT`, `ALLOCATED`, `BACKORDERED`, `PACKED`, or `SHIPPED` (`ERR_OPEN_ORDERS_EXIST`); no consignment agreement of the customer may be `ACTIVE` (`ERR_OPEN_AGREEMENTS_EXIST`); and the `outstanding_balance_cents` must be exactly zero (`ERR_OUTSTANDING_BALANCE_NONZERO`). An account already `CLOSED` rejects further lifecycle calls with `ERR_CUSTOMER_ALREADY_CLOSED`, and `CLOSED` is terminal.

### 3.4. Placing an Order: Draft, Submit, Allocation, and the Backorder Waitlist

A `Customer` builds an order by naming its own `customer_id`, the fulfilling `warehouse_id`, a `shipping_service` of `STANDARD`, `EXPRESS`, or `PRIORITY_OVERNIGHT`, the `requested_ship_date` that drives the shelf-life gate, and a creation-only `lines` array whose entries each carry a `product_id`, a positive `quantity`, and a `fulfillment_mode` of `ANY` or `SEQUENTIAL` defaulting to `ANY`. Creation materializes each entry as an order line owned by the order via its `order_id`, starting `PENDING`, with `allocated_quantity` at 0 and `unit_price_cents` and `line_total_cents` still null. The order itself begins `DRAFT`, with `product_total_cents` and `submission_seq` null until its first successful submission.

Submission is the pivotal act, and its checks run in a fixed order after the generic chain of §2.6 — the order must be `DRAFT` (`ERR_ORDER_NOT_SUBMITTABLE`), the customer must be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE`), and at least one line must exist (`ERR_ORDER_HAS_NO_LINES`) — after which the business rules fire in strict sequence, each masking the rest: the customer's `hazmat_endorsement` must cover every line product's `hazard_class` per the ladder of §2.10 (`ERR_HAZMAT_ENDORSEMENT_INSUFFICIENT`); when any line's product has `requires_cold_chain` true, the customer must be `cold_chain_certified` (`ERR_COLD_CHAIN_NOT_CERTIFIED`); no line may reference a product covered by an `ISSUED` recall (`ERR_PRODUCT_UNDER_RECALL`); the shelf-life gate must not be totally breached, as detailed below (`ERR_SHELF_LIFE_TOO_SHORT`); every line's product must be `LISTED` (`ERR_PRODUCT_NOT_LISTED`); and finally the credit pre-check of §3.3 must pass (`ERR_CREDIT_LIMIT_EXCEEDED`).

A passing submission prices the order with a pinned rounding order: each line snapshots `unit_price_cents` from the product's current catalog price, then computes `line_total_cents` as the quantity times that unit price times one minus the customer's `volume_discount_pct`, rounded half up to whole cents per line; the order's `product_total_cents` is the sum of those rounded line totals. Sum-then-round is forbidden — two lines of quantity 1 at 105 cents with a 10% discount yield 95 + 95 = 190 cents, never 189.

Allocation then runs per line. Candidate lots must be `AVAILABLE`, belong to the line's `product_id` and the order's `warehouse_id`, sit in a zone at least as cold as the product's `storage_requirement`, and pass the shelf-life gate: the span from the order's `requested_ship_date` to the lot's `expiry_date` must be at least the product's `min_remaining_shelf_life_days`, with equality allocatable and one day less not. The gate has a submit-time hard edge: when at least one `AVAILABLE` lot of a line's product with positive on-hand exists at the order's warehouse but every such lot fails the gate, the submit is rejected outright with `ERR_SHELF_LIFE_TOO_SHORT` rather than silently backordering; otherwise gate-failing lots are simply skipped.

For `ANY` lines, eligible lots are ranked by the rotation policy of their zone — under `FEFO` by earliest `expiry_date`, ties broken by earlier `received_at` then lower `lot_sequence_number`; under `FIFO` by earliest `received_at`, ties broken by lower `lot_sequence_number`, and when policies are mixed the FEFO-ranked lots precede the FIFO-ranked ones. Allocation walks that ranking as a waterfall, taking from each lot the lesser of the remaining need and its `quantity_on_hand`, until the need is met or candidates run out. For `SEQUENTIAL` lines the system instead considers candidate runs — sets of eligible lots whose `lot_sequence_number` values are strictly consecutive, each exactly one greater than the previous — and among runs whose summed on-hand covers the line's `quantity`, prefers the run with the fewest lots, breaking ties toward the lowest starting sequence number and then the earliest expiry date of the run's first lot. Consumption within the chosen run proceeds from the lowest sequence number upward, again taking the lesser of remaining need and on-hand per lot. A sequential line for which no run suffices receives no reservations at all and stays `PENDING` — sequential lines never partially allocate.

Each successful take creates a reservation in `HELD` status recording its `order_line_id`, `lot_id`, and reserved `quantity`, and moves that quantity from the lot's `quantity_on_hand` into its `quantity_reserved`; a lot driven to exactly zero on-hand flips itself to `DEPLETED`. Lines then settle into their allocation states: full coverage moves a line from `PENDING` to `ALLOCATED`, partial coverage moves it to `PARTIALLY_ALLOCATED`, and every one of these line transitions increments the line's `version`. When every line is fully covered the order lands `ALLOCATED`; when at least one line fell short it lands `BACKORDERED`, with whatever partial `HELD` reservations were gathered persisting in place. Either way the order receives its `submission_seq` — a monotonic per-system integer assigned at successful submission that serves as the waitlist ordering key — and its `version` increments.

A `BACKORDERED` order is not dead. Every lot receipt triggers a system waitlist retry over all `BACKORDERED` orders in ascending `submission_seq` order, allocating only each line's remaining shortfall against the newly available lots while keeping the order's existing `HELD` reservations; a retry that fully covers every line promotes the order to `ALLOCATED` (and a line it completes moves from `PARTIALLY_ALLOCATED` to `ALLOCATED`). The customer may alternatively request a manual re-plan from either `BACKORDERED` or `ALLOCATED` — any other order state yields `ERR_ORDER_NOT_REALLOCATABLE`. The manual reallocate must carry `expected_order_version` per §2.7, and it works by first releasing every existing `HELD` reservation on the order with quantity compensation back to the lots, then re-running the full allocation from scratch under the same rules as submission. Reservation loss also flows the other way: the quarantine, expiry, and recall cascades demote lines — from `ALLOCATED` to `PENDING` when released reservations leave nothing remaining, or from `PARTIALLY_ALLOCATED` to `PENDING` when the cascade strips the rest — and an `ALLOCATED` order demoted by such a cascade falls back to `BACKORDERED`.

Individual reservations may also be released by hand, by the owning `Customer` or an `InventoryClerk`. Only a `HELD` reservation can be released — otherwise `ERR_RESERVATION_NOT_HELD` — and the release hands its quantity back to the lot (`quantity_reserved` down, `quantity_on_hand` up), recomputes the zone's `occupied_units`, and triggers the parent line and order's allocation recompute with the same possible demotions as the cascade. Finally, the customer may cancel an order outright while it is `DRAFT`, `BACKORDERED`, or `ALLOCATED` — any other state yields `ERR_ORDER_NOT_CANCELLABLE` — which releases every `HELD` reservation with compensation and moves every line, from whichever of `PENDING`, `PARTIALLY_ALLOCATED`, or `ALLOCATED` it occupied, to `CANCELLED`. `DELIVERED`, `CANCELLED`, and `REFUNDED` are the order's terminal states.

### 3.5. Packing and Shipping: Freight Economics and Hazardous-Load Control

Once an order sits `ALLOCATED`, an `InventoryClerk` creates its shipment by supplying the `order_id`, a `coolant_type` of `NONE`, `GEL_PACK`, or `DRY_ICE`, a `coolant_units` count that may be zero in general but must be at least 1 when any line's product `requires_cold_chain`, and a positive `declared_weight_grams` estimate. An order may have exactly one shipment over its lifetime; a second attempt is rejected with `ERR_SHIPMENT_ALREADY_EXISTS`, and attempting to ship an order that is not `ALLOCATED` yields `ERR_ORDER_NOT_ALLOCATED`.

Creation derives the shipment's monitored band per §2.9 and computes `provisional_freight_cents` from the declared weight. Freight is priced identically in both its provisional and final variants: a base charge keyed on `shipping_service` — 800 cents for `STANDARD`, 1500 for `EXPRESS`, 2500 for `PRIORITY_OVERNIGHT` — covers the first 5000 grams, and each additional started kilogram beyond that inclusion adds 120 cents; coolant adds nothing for `NONE`, 150 cents per unit for `GEL_PACK`, and 400 per unit for `DRY_ICE`. When any line's product is not `NON_HAZARDOUS`, a hazmat surcharge of 25% of that subtotal, rounded half up to whole cents, is added. The resulting total is floored at 500 cents — unless the order's `product_total_cents` reaches the free-freight threshold of 250000 cents, in which case freight is zero and the floor and surcharges are skipped entirely.

Before creation completes, the hazardous-load screen runs against the order's lines and coolant declaration, after the warehouse-certification check (a shipment containing any hazardous line requires the order's warehouse to be `hazmat_certified`, else `ERR_HAZMAT_WAREHOUSE_NOT_CERTIFIED`) and before the one-shipment rule. Each line whose product is hazardous must respect its product's `max_qty_per_shipment` (`ERR_HAZMAT_PRODUCT_LIMIT_EXCEEDED`); the per-class loads — line quantity times `unit_haz_factor`, summed per class — must respect the caps of §2.10, 30 each for `FLAMMABLE` and `CORROSIVE` and 10 each for `TOXIC` and `OXIDIZER` (`ERR_HAZMAT_CLASS_LIMIT_EXCEEDED`); the aggregate across all four classes must not exceed 50 (`ERR_HAZMAT_TOTAL_LIMIT_EXCEEDED`); and `DRY_ICE` shipments must carry at most 20 coolant units (`ERR_DRY_ICE_LIMIT_EXCEEDED`). A compliant shipment begins in `CREATED` status.

Packing — permitted only from `CREATED` (`ERR_SHIPMENT_NOT_PACKABLE`) and only while the order is `ALLOCATED` (`ERR_ORDER_NOT_ALLOCATED`) — commits the allocation: every `HELD` reservation of the order transitions to `COMMITTED`, every order line moves from `ALLOCATED` to `FULFILLED`, the order advances from `ALLOCATED` to `PACKED`, and the shipment becomes `PACKED`. Dispatch requires `PACKED` (`ERR_SHIPMENT_NOT_DISPATCHABLE`) and an `OPERATIONAL` warehouse for the order (`ERR_WAREHOUSE_NOT_OPERATIONAL`); it captures the scale weight into `actual_weight_grams`, recomputes freight in its final variant against that weight and stores it as `final_freight_cents` — the invoiced freight — and moves every `COMMITTED` reservation to `CONSUMED`, shifting each reservation's quantity from its lot's `quantity_reserved` into `quantity_consumed` and recomputing the affected zones' occupancy. The order advances from `PACKED` to `SHIPPED`, the invoice posts by adding `product_total_cents` plus `final_freight_cents` to the customer's `outstanding_balance_cents`, the auto-suspension check of §3.3 runs, and for every `ACTIVE` consignment agreement matching the order's customer and a shipped line's product, the agreement's `stocked_quantity` grows by the line's quantity — without triggering replenishment at this point.

Delivery moves the shipment from `IN_TRANSIT` to `DELIVERED` and the order from `SHIPPED` to `DELIVERED`; it is permitted only from `IN_TRANSIT` (`ERR_SHIPMENT_NOT_IN_TRANSIT`) and is blocked while any excursion of the shipment remains `OPEN` (`ERR_DELIVERY_BLOCKED_OPEN_EXCURSION`). Freight visibility is available throughout: a computed read on the order returns its `product_total_cents`, the shipment's `provisional_freight_cents` and `final_freight_cents`, the `freight_to_product_ratio`, and the `projected_outstanding_cents` impact of the order on the customer's balance.

### 3.6. Cold-Chain Telemetry, Excursions, and Quality Disposition

While a shipment travels, an `InventoryClerk` streams temperature readings into it, each carrying the observed `temp_celsius` and the `duration_minutes` the reading persisted. Telemetry is accepted while the shipment is `IN_TRANSIT` and continues to be accepted while it sits `EXCURSION_HOLD`; any other shipment state rejects the reading with `ERR_SHIPMENT_NOT_IN_TRANSIT`. A reading is tested against the shipment's band: the `deviation_degrees` is the amount by which the temperature exceeds `temp_max_celsius` or falls below `temp_min_celsius`, and an in-band reading — deviation exactly zero — is accepted without creating anything.

An out-of-band reading opens a temperature excursion, provided none of this shipment's excursions is still `OPEN` (a second breach while one is open is rejected with `ERR_EXCURSION_ALREADY_OPEN`). The new excursion records its `shipment_id`, the breaching `peak_temp_celsius`, the reported `duration_minutes`, and the computed `deviation_degrees`, classifies its `severity` — `CRITICAL` when the deviation exceeds 5.0 degrees or the duration reaches at least 240 minutes, otherwise `MAJOR` when the deviation exceeds 2.0 degrees or the duration reaches at least 60 minutes, otherwise `MINOR` — and stores a `provisional_credit_cents` estimate: half of the affected value, rounded half up, where the affected value is the sum of `line_total_cents` over the order's lines whose product `requires_cold_chain`. The excursion begins `OPEN`, `final_credit_cents` stays null until disposition, the shipment moves from `IN_TRANSIT` to `EXCURSION_HOLD`, and the telemetry response reports `excursion_created`, the new `excursion_id`, the `severity`, and the resulting `shipment_status`.

Disposition belongs to the `QualityManager`, who supplies a `decision` on an excursion that must still be `OPEN` (`ERR_EXCURSION_NOT_OPEN`). Three outcomes exist, each stamping `final_credit_cents` differently. An `ACCEPTED` disposition declares the product unaffected: the final credit is zero, nothing else moves, and the shipment becomes eligible to resume. A `DESTROYED` disposition sets the final credit to the full affected cold-chain product value and fires the refund cascade: the shipment moves from `EXCURSION_HOLD` to `RETURNED`, the order moves from `SHIPPED` to `REFUNDED`, and the customer's `outstanding_balance_cents` is reduced by the order's `product_total_cents` plus the shipment's `final_freight_cents` — a full invoice reversal with freight waived. A `RETURNED` disposition sets the final credit to the shipment's `final_freight_cents` plus one quarter of the affected value, rounded half up, and fires the identical shipment-order-customer cascade. The final credit is the credit-memo record of the refund basis; the actual balance movement is always the full invoice reversal. After an `ACCEPTED` disposition, the clerk may resume transit, moving the shipment from `EXCURSION_HOLD` back to `IN_TRANSIT` — attempted from any other shipment state it fails with `ERR_SHIPMENT_NOT_ON_HOLD`, and attempted before the excursion is `ACCEPTED` it fails with `ERR_EXCURSION_NOT_RESOLVED`.

### 3.7. Product Recalls and the Lot Pull

When quality fails at scale, a `QualityManager` authors a recall notice naming the `product_id`, a `scope_type` of `LOT_RANGE` or `PRODUCT_ALL`, the `severity_class` of `CLASS_I`, `CLASS_II`, or `CLASS_III`, and a free-text `reason`. A `LOT_RANGE` notice must also carry `scope_lot_seq_min` and `scope_lot_seq_max`, the inclusive sequence-number bounds of the covered lots. The notice begins `DRAFT` and changes nothing until issued.

Issuance — permitted only from `DRAFT` (`ERR_RECALL_NOT_DRAFT`) — fires a four-hop cascade. First, every lot of the product matching the scope (sequence number between the bounds inclusive for `LOT_RANGE`; all lots for `PRODUCT_ALL`) whose status is `AVAILABLE` or `QUARANTINED` is forced into `QUARANTINED` — available lots transition, quarantined lots remain — and stamped with the recall's id in `recall_id`. Second, every `HELD` reservation on those lots transitions to `RELEASED` with quantity compensation back to its lot. Third, each affected order line recomputes its `allocated_quantity` and demotes to `PENDING` when the recomputed amount reaches zero. Fourth, each affected order in `ALLOCATED` demotes to `BACKORDERED`. When the scope is `PRODUCT_ALL`, the product itself additionally moves from `LISTED` to `UNDER_RECALL`. While a recall is `ISSUED`, its covered products are poison to new business: order submission, kit activation, and consignment consumption referencing such a product are rejected with `ERR_PRODUCT_UNDER_RECALL`, and releasing quarantine on a covered lot is rejected with `ERR_RECALL_ACTIVE_FOR_LOT`.

Closing the recall performs the lot pull. It is permitted only from `ISSUED` (`ERR_RECALL_NOT_CLOSABLE`), and only once every covered lot sits `QUARANTINED` with `quantity_reserved` at exactly zero — a lot still holding reserved quantity blocks the close with `ERR_RECALL_LOTS_PENDING`. On close, each covered quarantined lot transitions from `QUARANTINED` to the terminal `RECALLED` state, its entire remaining `quantity_on_hand` is written off into `quantity_consumed` (both `quantity_on_hand` and `quantity_reserved` end at zero), the `recall_id` reference is cleared, and the affected zones' occupancy is recomputed. For a `PRODUCT_ALL` notice, closing also returns the product from `UNDER_RECALL` to `LISTED`. Every hop of both cascades increments the `version` of each resource it touches.

### 3.8. Recurring Supply: Standing Orders, Consignment, and Replenishment

A `Customer` arranges recurring supply through a standing order naming its `customer_id`, the `product_id`, the fulfilling `warehouse_id`, a positive `quantity_per_run`, a positive `interval_days`, and an inclusive availability window from `effective_from` to `effective_until` (the until date must not precede the from date). Standing orders for the same customer and product respect a buffer rule against existing `ACTIVE` or `PAUSED` standing orders: the new window must clear every existing window by at least seven days in one direction — beginning no earlier than seven days after the existing window's end, or ending no later than seven days before the existing window's start. A gap of exactly seven days passes; a six-day gap or any overlap is rejected with `ERR_STANDING_ORDER_WINDOW_CONFLICT`. A new standing order starts `ACTIVE`, with `next_run_date` initialized to `effective_from` and `generated_order_count` at 0.

Generation rides the logical clock. Each time the clock is set, the system processes `ACTIVE` standing orders in ascending `created_at` order (ties broken by their per-system creation counter, ascending), and for each, while its `next_run_date` is on or before both the current logical date and its `effective_until`, it generates one order — for its customer, product, and warehouse, at its `quantity_per_run`, with fulfillment mode `ANY`, `STANDARD` shipping, and `requested_ship_date` equal to that run date — and auto-submits it. When the generated order's submit-time validation fails, for instance on credit, the order is left in `DRAFT` and the standing order transitions itself from `ACTIVE` to `PAUSED` with no further runs; otherwise `generated_order_count` grows by one and `next_run_date` advances by `interval_days`. Catch-up after a long clock jump generates at most one order per due run date, in date order. The customer may also steer the subscription directly: pausing from `ACTIVE` (`ERR_STANDING_ORDER_NOT_ACTIVE`), resuming from `PAUSED` (`ERR_STANDING_ORDER_NOT_PAUSED`), and cancelling from either `ACTIVE` or `PAUSED` into the terminal `CANCELLED` (`ERR_STANDING_ORDER_TERMINAL` once cancelled).

Consignment inverts the billing model: stock lives at the customer site and is billed only as consumed. An `AccountManager` opens an agreement with the `customer_id` and `product_id`, a positive `ceiling_quantity` capping the units ever stocked under it, a non-negative `reorder_point`, a positive `contract_unit_price_cents`, an optional `discount_pct` between 0 and 0.5 defaulting to 0, the `replenishment_warehouse_id` that will supply top-ups, an optional non-negative `initial_stocked_quantity` — which may not exceed the ceiling — and a half-open window from `effective_from` inclusive to `effective_until` exclusive, the latter strictly after the former. Agreements for the same customer and product may not overlap: considering existing agreements in `ACTIVE` or `SUSPENDED`, overlap exists when the existing window begins before the new window ends and the new window begins before the existing window ends, while mere adjacency — a new window starting exactly when the existing one ends — is allowed; an overlap is rejected with `ERR_CONSIGNMENT_WINDOW_OVERLAP`. The agreement begins `ACTIVE`, its `stocked_quantity` seeded by `initial_stocked_quantity` and `consumed_quantity` at 0. Lifecycle calls mirror the account's: suspend from `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`), reactivate from `SUSPENDED` (`ERR_AGREEMENT_NOT_SUSPENDED`), and close from either into terminal `CLOSED` (`ERR_AGREEMENT_ALREADY_CLOSED`).

Consumption is reported against an `ACTIVE` agreement by the customer itself or its `AccountManager`, as a positive `quantity`. Three business checks guard it in order after the generic chain: the product must not be covered by an `ISSUED` recall (`ERR_PRODUCT_UNDER_RECALL`); the record may not push `consumed_quantity` above the `ceiling_quantity` (`ERR_CONSIGNMENT_CEILING_EXCEEDED`); and the quantity may not exceed the on-hand at customer — `stocked_quantity` minus `consumed_quantity` (`ERR_CONSUMPTION_EXCEEDS_STOCK`). A passing record snapshots the agreement's `contract_unit_price_cents` into its own `unit_price_cents`, computes `charge_cents` as the quantity times that price times one minus the `discount_pct`, rounded half up per record — never summed and rounded across records — and stamps `recorded_at` from the logical clock, carrying its `agreement_id`. The charge posts to the customer's `outstanding_balance_cents` and the agreement's `consumed_quantity` grows by the quantity.

Replenishment is then evaluated: when the on-hand at customer — stocked minus consumed — falls to the `reorder_point` or below, with equality triggering, and the agreement is `ACTIVE`, the system creates a replenishment order for the agreement's customer at its `replenishment_warehouse_id` with quantity equal to the ceiling minus the current on-hand, fulfillment mode `ANY`, `STANDARD` shipping, and `requested_ship_date` set to the day after the current logical date, and auto-submits it in the standing-order style.

### 3.9. Custom Kits and Assembly Jobs

A `CatalogManager` composes account-specific assay kits by naming the owning `customer_id`, a display `name`, and a `components` array whose entries pair a `product_id` with a positive `quantity_per_kit`. The same product may not appear twice in one kit — a duplicate `product_id` is rejected at creation with `ERR_KIT_DUPLICATE_COMPONENT` (HTTP 422). A kit begins `DRAFT` with `kit_price_cents` null.

Activation promotes the kit from `DRAFT` (any other state, `ERR_KIT_NOT_DRAFT`) and applies its checks in the global priority order: no component product may be covered by an `ISSUED` recall (`ERR_PRODUCT_UNDER_RECALL`); the `components` array must be non-empty (`ERR_KIT_COMPONENTS_EMPTY`, HTTP 422) and all components must share one identical `storage_requirement` (`ERR_KIT_STORAGE_MIXED`, HTTP 422); and every component product must be `LISTED` (`ERR_PRODUCT_NOT_LISTED`). Activation also computes the kit price with a pinned evaluation order that forecloses any circularity: first the component cost is summed as each entry's `quantity_per_kit` times its product's current `unit_price_cents`; then the assembly fee is tiered on that pre-fee component cost — 1500 cents when it falls below 100000 cents, 4000 cents when it reaches 100000 but stays below 500000, and 9000 cents at 500000 or above; finally `kit_price_cents` is the component cost plus the fee. The fee tier never sees the fee-inclusive price. An `ACTIVE` kit may later be retired into the terminal `RETIRED` state (`ERR_KIT_NOT_ACTIVE` from any other state).

Physical assembly is planned as a job naming the `kit_id`, the `warehouse_id` supplying components, and a positive `quantity_to_build`; the kit must be `ACTIVE` for a job to be created or executed (`ERR_KIT_NOT_ACTIVE`), and the job begins `PLANNED` with `kits_built` at 0. Execution is atomic and FEFO-driven: from a `PLANNED` job (`ERR_JOB_NOT_EXECUTABLE` otherwise), the system checks for every component that the FEFO waterfall over that product's `AVAILABLE` lots at the job's warehouse can cover `quantity_per_kit` times `quantity_to_build`; if any component falls short, the entire execution is rejected with `ERR_KIT_COMPONENT_SHORTAGE` and all stock is left untouched. On success, each component's requirement is consumed down the waterfall — decrementing each lot's `quantity_on_hand` and incrementing its `quantity_consumed`, flipping lots emptied to exactly zero from `AVAILABLE` to `DEPLETED`, and recomputing the touched zones' occupancy — then `kits_built` is set equal to `quantity_to_build` and the `consumption_summary` is recorded as a map from each component `product_id` to the list of lot-and-quantity pairs consumed. A planned job that is no longer wanted may be cancelled from `PLANNED` into `CANCELLED` (`ERR_JOB_NOT_CANCELLABLE` from any other state); `COMPLETED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Endpoints that create a new resource — a warehouse, zone, product, lot, adjustment record, customer, payment, order, shipment, temperature-excursion report, standing order, consignment agreement, consumption record, recall, kit, or assembly job — return `201 Created`. Operations that modify an existing resource's state or return a computed view return `200 OK`. All endpoints are mounted under the `/lab` prefix, and all GET endpoints are available to every role, with `Customer`-role reads scoped to that customer's own rows wherever the entity carries a `customer_id`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/lab/warehouses` | Create a warehouse | OpsAdmin |
| GET | `/lab/warehouses` | List warehouses (paginated) | All roles |
| GET | `/lab/warehouses/{warehouseId}` | Get one warehouse | All roles |
| POST | `/lab/warehouses/{warehouseId}/suspend` | Suspend a warehouse (blocks dispatch) | OpsAdmin |
| POST | `/lab/warehouses/{warehouseId}/resume` | Resume a suspended warehouse | OpsAdmin |
| POST | `/lab/storage-zones` | Create a storage zone in a warehouse | OpsAdmin |
| GET | `/lab/storage-zones` | List storage zones (paginated) | All roles |
| GET | `/lab/storage-zones/{zoneId}` | Get one storage zone | All roles |
| POST | `/lab/products` | Create a catalog product | CatalogManager |
| GET | `/lab/products` | List products (paginated) | All roles |
| GET | `/lab/products/{productId}` | Get one product | All roles |
| POST | `/lab/products/{productId}/discontinue` | Discontinue a product (terminal) | CatalogManager |
| POST | `/lab/lots` | Receive a reagent lot into a zone; assigns sequence and expiry; retries backordered orders | InventoryClerk |
| GET | `/lab/lots` | List lots (paginated) | All roles |
| GET | `/lab/lots/{lotId}` | Get one lot | All roles |
| POST | `/lab/lots/{lotId}/adjustments` | Stock-count adjustment against a lot (OCC on `expected_lot_version`) | InventoryClerk |
| POST | `/lab/lots/{lotId}/quarantine` | Manually quarantine an `AVAILABLE` lot | QualityManager |
| POST | `/lab/lots/{lotId}/release-quarantine` | Release a quarantined lot back to `AVAILABLE` | QualityManager |
| POST | `/lab/customers` | Open a customer account | AccountManager |
| GET | `/lab/customers` | List customer accounts (paginated) | All roles |
| GET | `/lab/customers/{customerId}` | Get one customer account | All roles |
| PATCH | `/lab/customers/{customerId}` | Update commercial terms (OCC on `expected_customer_version`) | AccountManager |
| POST | `/lab/customers/{customerId}/suspend` | Suspend an account | AccountManager |
| POST | `/lab/customers/{customerId}/reactivate` | Reactivate a suspended account | AccountManager |
| POST | `/lab/customers/{customerId}/close` | Close an account (terminal) | AccountManager |
| POST | `/lab/customers/{customerId}/payments` | Record a payment reducing outstanding balance | AccountManager |
| POST | `/lab/orders` | Create a `DRAFT` order with its lines materialized | Customer |
| GET | `/lab/orders` | List orders (paginated; Customer sees only own) | All roles |
| GET | `/lab/orders/{orderId}` | Get one order | All roles |
| POST | `/lab/orders/{orderId}/submit` | Validate, price, and allocate an order | Customer |
| POST | `/lab/orders/{orderId}/reallocate` | Release current reservations and re-run allocation (OCC on `expected_order_version`) | Customer |
| POST | `/lab/orders/{orderId}/cancel` | Cancel a pre-pack order, releasing all `HELD` reservations | Customer |
| GET | `/lab/orders/{orderId}/cost-summary` | Computed cost read: totals, freight, ratio, credit impact | All roles |
| GET | `/lab/order-lines` | List order lines (paginated) | All roles |
| GET | `/lab/order-lines/{orderLineId}` | Get one order line | All roles |
| GET | `/lab/reservations` | List lot reservations (paginated) | All roles |
| GET | `/lab/reservations/{reservationId}` | Get one reservation | All roles |
| POST | `/lab/reservations/{reservationId}/release` | Manually release a `HELD` reservation back to its lot | Customer, InventoryClerk |
| POST | `/lab/shipments` | Create a shipment for an `ALLOCATED` order | InventoryClerk |
| GET | `/lab/shipments` | List shipments (paginated) | All roles |
| GET | `/lab/shipments/{shipmentId}` | Get one shipment | All roles |
| POST | `/lab/shipments/{shipmentId}/pack` | Pack: commit reservations, fulfill lines, move order to `PACKED` | InventoryClerk |
| POST | `/lab/shipments/{shipmentId}/dispatch` | Dispatch: final freight, consume reservations, invoice the customer | InventoryClerk |
| POST | `/lab/shipments/{shipmentId}/record-temperature` | Record a transit temperature reading; may open an excursion | InventoryClerk |
| POST | `/lab/shipments/{shipmentId}/resume-transit` | Resume transit after an `ACCEPTED` excursion disposition | InventoryClerk |
| POST | `/lab/shipments/{shipmentId}/deliver` | Deliver an in-transit shipment | InventoryClerk |
| GET | `/lab/excursions` | List temperature excursions (paginated) | All roles |
| GET | `/lab/excursions/{excursionId}` | Get one excursion | All roles |
| POST | `/lab/excursions/{excursionId}/disposition` | Disposition an `OPEN` excursion | QualityManager |
| POST | `/lab/standing-orders` | Create a standing order (window buffer rule applies) | Customer |
| GET | `/lab/standing-orders` | List standing orders (paginated; Customer sees only own) | All roles |
| GET | `/lab/standing-orders/{standingOrderId}` | Get one standing order | All roles |
| POST | `/lab/standing-orders/{standingOrderId}/pause` | Pause an `ACTIVE` standing order | Customer |
| POST | `/lab/standing-orders/{standingOrderId}/resume` | Resume a `PAUSED` standing order | Customer |
| POST | `/lab/standing-orders/{standingOrderId}/cancel` | Cancel a standing order (terminal) | Customer |
| POST | `/lab/consignment-agreements` | Open a consignment agreement (window overlap rule applies) | AccountManager |
| GET | `/lab/consignment-agreements` | List consignment agreements (paginated) | All roles |
| GET | `/lab/consignment-agreements/{agreementId}` | Get one consignment agreement | All roles |
| POST | `/lab/consignment-agreements/{agreementId}/suspend` | Suspend an agreement | AccountManager |
| POST | `/lab/consignment-agreements/{agreementId}/reactivate` | Reactivate a suspended agreement | AccountManager |
| POST | `/lab/consignment-agreements/{agreementId}/close` | Close an agreement (terminal) | AccountManager |
| POST | `/lab/consignment-agreements/{agreementId}/consumption` | Record consumption: bills the customer, may trigger replenishment | Customer, AccountManager |
| GET | `/lab/consumption-records` | List consumption records (paginated) | All roles |
| GET | `/lab/consumption-records/{recordId}` | Get one consumption record | All roles |
| POST | `/lab/recalls` | Create a `DRAFT` recall notice | QualityManager |
| GET | `/lab/recalls` | List recalls (paginated) | All roles |
| GET | `/lab/recalls/{recallId}` | Get one recall | All roles |
| POST | `/lab/recalls/{recallId}/issue` | Issue a recall: quarantine covered lots, release reservations, demote lines and orders | QualityManager |
| POST | `/lab/recalls/{recallId}/close` | Close an issued recall: pull covered lots to `RECALLED` | QualityManager |
| POST | `/lab/kits` | Create a `DRAFT` custom kit definition | CatalogManager |
| GET | `/lab/kits` | List kits (paginated) | All roles |
| GET | `/lab/kits/{kitId}` | Get one kit | All roles |
| POST | `/lab/kits/{kitId}/activate` | Activate a kit and compute its price | CatalogManager |
| POST | `/lab/kits/{kitId}/retire` | Retire an `ACTIVE` kit (terminal) | CatalogManager |
| POST | `/lab/kit-assembly-jobs` | Plan a kit assembly job | InventoryClerk |
| GET | `/lab/kit-assembly-jobs` | List kit assembly jobs (paginated) | All roles |
| GET | `/lab/kit-assembly-jobs/{jobId}` | Get one kit assembly job | All roles |
| POST | `/lab/kit-assembly-jobs/{jobId}/execute` | Execute a planned job: atomic FEFO consumption of components | InventoryClerk |
| POST | `/lab/kit-assembly-jobs/{jobId}/cancel` | Cancel a planned job | InventoryClerk |
| POST | `/lab/_clock/set_current_utc` | Advance the logical clock; runs the expiry sweep and standing-order generation | OpsAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API may return and its HTTP status. Trigger conditions for each are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_WAREHOUSE_NOT_FOUND` | 404 Not Found |
| `ERR_STORAGE_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_EXCURSION_NOT_FOUND` | 404 Not Found |
| `ERR_STANDING_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONSUMPTION_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_KIT_NOT_FOUND` | 404 Not Found |
| `ERR_KIT_ASSEMBLY_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_KIT_DUPLICATE_COMPONENT` | 422 Unprocessable Entity |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CUSTOMER_VERSION` | 412 Precondition Failed |
| `ERR_WAREHOUSE_NOT_OPERATIONAL` | 409 Conflict |
| `ERR_WAREHOUSE_NOT_SUSPENDED` | 409 Conflict |
| `ERR_PRODUCT_NOT_LISTED` | 409 Conflict |
| `ERR_LOT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_LOT_NOT_QUARANTINED` | 409 Conflict |
| `ERR_CUSTOMER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CUSTOMER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_CUSTOMER_ALREADY_CLOSED` | 409 Conflict |
| `ERR_ORDER_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_ORDER_NOT_REALLOCATABLE` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_ALLOCATED` | 409 Conflict |
| `ERR_ORDER_HAS_NO_LINES` | 409 Conflict |
| `ERR_RESERVATION_NOT_HELD` | 409 Conflict |
| `ERR_SHIPMENT_NOT_PACKABLE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_DISPATCHABLE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_SHIPMENT_NOT_ON_HOLD` | 409 Conflict |
| `ERR_DELIVERY_BLOCKED_OPEN_EXCURSION` | 409 Conflict |
| `ERR_EXCURSION_ALREADY_OPEN` | 409 Conflict |
| `ERR_EXCURSION_NOT_OPEN` | 409 Conflict |
| `ERR_EXCURSION_NOT_RESOLVED` | 409 Conflict |
| `ERR_STANDING_ORDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_STANDING_ORDER_NOT_PAUSED` | 409 Conflict |
| `ERR_STANDING_ORDER_TERMINAL` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_AGREEMENT_ALREADY_CLOSED` | 409 Conflict |
| `ERR_RECALL_NOT_DRAFT` | 409 Conflict |
| `ERR_RECALL_NOT_CLOSABLE` | 409 Conflict |
| `ERR_RECALL_LOTS_PENDING` | 409 Conflict |
| `ERR_KIT_NOT_DRAFT` | 409 Conflict |
| `ERR_KIT_NOT_ACTIVE` | 409 Conflict |
| `ERR_JOB_NOT_EXECUTABLE` | 409 Conflict |
| `ERR_JOB_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_HAZMAT_ENDORSEMENT_INSUFFICIENT` | 403 Forbidden |
| `ERR_COLD_CHAIN_NOT_CERTIFIED` | 403 Forbidden |
| `ERR_HAZMAT_WAREHOUSE_NOT_CERTIFIED` | 409 Conflict |
| `ERR_HAZMAT_PRODUCT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_HAZMAT_CLASS_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_HAZMAT_TOTAL_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_DRY_ICE_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_PRODUCT_UNDER_RECALL` | 409 Conflict |
| `ERR_RECALL_ACTIVE_FOR_LOT` | 409 Conflict |
| `ERR_SHELF_LIFE_TOO_SHORT` | 409 Conflict |
| `ERR_STANDING_ORDER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CONSIGNMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STORAGE_ZONE_INCOMPATIBLE` | 409 Conflict |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ZONE_WAREHOUSE_MISMATCH` | 409 Conflict |
| `ERR_ADJUSTMENT_BELOW_ZERO` | 409 Conflict |
| `ERR_KIT_COMPONENTS_EMPTY` | 422 Unprocessable Entity |
| `ERR_KIT_STORAGE_MIXED` | 422 Unprocessable Entity |
| `ERR_SHIPMENT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_CONSIGNMENT_CEILING_EXCEEDED` | 409 Conflict |
| `ERR_CONSUMPTION_EXCEEDS_STOCK` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_KIT_COMPONENT_SHORTAGE` | 409 Conflict |
| `ERR_OPEN_ORDERS_EXIST` | 409 Conflict |
| `ERR_OPEN_AGREEMENTS_EXIST` | 409 Conflict |
| `ERR_OUTSTANDING_BALANCE_NONZERO` | 409 Conflict |
| `ERR_OUTSTANDING_ABOVE_LIMIT` | 409 Conflict |
