# Party Supply Store API — Product Requirements Document

## 1. Introduction

The Party Supply Store API is the operational backbone of a full-service party retailer that sells balloons, tableware, costumes, seasonal Halloween inventory, and custom banner prints, and that additionally rents tableware, delivers goods with optional on-site setup, offers scheduled buy-online-pickup-in-store fulfillment, and packages complete events around a lead-time deposit. Because the same physical store simultaneously operates as a retail counter, a rental desk, a delivery dispatch, a custom print shop, and an event planner, an order is rarely a single line of products; it is a bundle of commitments across shared physical resources — SKU inventory, helium tanks, delivery vans, and staff time — each of which must remain internally consistent as the order progresses.

The API therefore treats every order as a coordination problem rather than a transaction. Prices and stock are captured at the moment of reservation and immutably pinned so that catalog edits made afterwards do not silently mutate a customer's total; helium is drawn deterministically from the oldest active tank; delivery slots are booked per van with half-open intervals to prevent double booking; rental deposits use undiscounted unit prices even when the underlying SKU is on clearance; custom print fees change with the number of revision cycles the customer requests; and refunds are routed to store credit rather than to the original tender. Every one of these rules exists so that the store's clerks, managers, drivers, and customers can operate the same catalog concurrently without producing balances or reservations that drift from physical reality.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply to every endpoint. The entire API is mounted under `/api`.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the role under which the request is made. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED`. If `X-User-Role` is not one of the four declared role names, the request is rejected with `ERR_UNKNOWN_ROLE`. If the declared role is not permitted to invoke the target endpoint according to §4, the request is rejected with `ERR_FORBIDDEN`.

The four declared roles are `StoreManager`, `StoreClerk`, `DeliveryDriver`, and `Customer`. A `StoreManager` owns the catalog and physical inventory: creating SKUs, bundles, helium tanks, event packages, applying and removing clearance, restocking, and refilling helium tanks. A `StoreClerk` is the customer-facing operator who drafts and reserves orders, records payments, prepares pickups, hands off deliveries to the driver, returns and cancels orders, attaches helium orders, rental contracts, and custom print orders to a draft order, books delivery slots, and manages event bookings. A `DeliveryDriver` is the delivery-only operator whose sole exclusive operation is confirming that an order has been delivered on the road. A `Customer` is an end customer with two exclusive operations tied to their own custom print orders: requesting a revision on a proof and approving a proof. A customer is created by a clerk with an `email` (unique across the customer table) and a `full_name`; on creation the customer's `store_credit_cents` is initialised to zero.

For the roles `StoreManager`, `StoreClerk`, and `DeliveryDriver`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity — the server may record it for auditing but does not compare it to any entity's `id`. For the role `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` (for example an `Order` via its `customer_id`, or a `CustomPrintOrder` reached through its parent `Order`) compare the resource's customer foreign key to `X-User-ID`.

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

List endpoints accept the `limit` and `offset` query parameters. `limit` defaults to 10 when not provided; the minimum accepted value is 1 and the maximum is 100. `offset` defaults to 0 and represents the number of leading items to skip. Every list response sorts its resources by `created_at` in ascending order unless the endpoint description says otherwise; when two resources share the same `created_at` (for example because they were created back-to-back at the same logical-clock instant), the tiebreak is insertion order so that the resource written to the store first appears first in the page. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Primary resources of the system — `Sku`, `Bundle`, `Order`, `HeliumTank`, `DeliverySlot`, `RentalContract`, `CustomPrintOrder`, `EventPackage`, `EventBooking`, and `Customer` — all carry the same four system-managed fields:

- `id` is a server-minted UUID with no type prefix.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits, stamped once when the resource is first created.
- `updated_at` is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` is an integer that starts at the initial insertion and increases by one with every mutation. It supports the optimistic concurrency mechanism described in §2.11.

Two child entities are the exception: `BundleLine` and `OrderLine` carry only `id` and `created_at`. Their `updated_at` and `version` are absent — a bundle line or an order line is either present in its current shape or replaced wholesale by a subsequent operation on its parent. The mixed-child entities that hang off an `Order` (`HeliumOrder`, `RentalContract`, `CustomPrintOrder`) all carry the full common-field set because they have independent lifecycles and OCC-sensitive mutations.

### 2.5. Nested Resource Retrieval

Endpoints whose paths contain multiple identifiers (for example an order and its lines, or a bundle and its lines) are validated left-to-right: the parent identifier is resolved first, and only after it is found does the server look for the child. A request for the lines of a non-existent order therefore reports `ERR_NOT_FOUND` referencing the missing order rather than the missing lines. `ERR_FK_NOT_FOUND` is reserved for foreign keys carried in the request body of a create or update — for example a `customer_id`, `sku_id`, `bundle_id`, `event_package_id`, or `order_id` that does not resolve to an existing row.

### 2.6. Monetary Values and Precision

All monetary amounts in the system — `unit_price_cents`, `bundle_price_cents`, `subtotal_cents`, `helium_fee_cents`, `delivery_fee_cents`, `deposit_cents`, `grand_total_cents`, `line_total_cents`, `unit_price_cents_at_capture`, `base_price_cents`, `fill_fee_cents`, `print_fee_cents`, `store_credit_cents` — are stored as integer cents. All monetary calculations use decimal arithmetic and the standard round-half-up rounding rule, and every stored monetary field is rounded to zero decimal places, i.e., whole cents. Field-level input constraints require that `unit_price_cents`, `bundle_price_cents`, and `base_price_cents` are at least zero. `deposit_pct` on an `EventPackage` is a fraction between zero and one inclusive.

Where a calculation combines several line-level amounts, the exact order in which rounding is applied matters and is explicitly pinned per calculation. Two orderings are used by the system: rounding each line before summing (used for the helium fill fee) and summing all line values first before rounding once at the end (used for the custom print fee). These orderings can differ by one or two cents at boundary inputs, so they are not interchangeable.

### 2.7. Parallel Fulfillment and Payment Axes on Orders

An `Order` maintains two independent status axes on the same row. `fulfillment_status` tracks the movement of goods through the store — the values are `DRAFT`, `RESERVED`, `PICKING`, `READY_FOR_PICKUP`, `PICKED_UP`, `DELIVERED`, `RETURNED`, and `CANCELLED`. `payment_status` tracks the money — the values are `UNPAID`, `DEPOSIT_HELD`, `PAID`, `PARTIALLY_REFUNDED`, and `REFUNDED`. Every new order is created with `fulfillment_status` set to `DRAFT` and `payment_status` set to `UNPAID`. The two axes evolve independently and are never collapsed into a single status field, though some transitions on one axis have preconditions that read the other axis (for example, starting to pick an order requires the payment axis to be in either `DEPOSIT_HELD` or `PAID`, and picking the order up requires the payment axis to be `PAID`).

The `channel` of an order is fixed at creation and takes one of `BOPIS`, `DELIVERY`, or `IN_STORE`. `BOPIS` orders carry a `pickup_window_start` and a `pickup_window_end`; both are null for other channels. `DELIVERY` orders must reference exactly one `DeliverySlot` at reserve time; `BOPIS` and `IN_STORE` orders never carry delivery fees.

### 2.8. Inventory Reservation Ledger

Each `Sku` carries two aggregate counters that are computed rather than input: `on_hand_qty` is the physical stock available across all channels, and `reserved_qty` is the aggregate quantity currently reserved by non-terminal orders and active rental contracts. `reserved_qty` must at all times reconcile against the source of truth: for every SKU, the reserved quantity equals the sum of the `qty` of every `OrderLine` whose parent `Order` is in `fulfillment_status` `RESERVED`, `PICKING`, or `READY_FOR_PICKUP` and whose `sku_id` matches that SKU, plus the sum over every such `OrderLine` whose `bundle_id` matches of `BundleLine.qty` multiplied by `OrderLine.qty` for every bundle line that names the SKU, plus the sum of `qty` for every `RentalContract` whose `status` is `RESERVED` and whose `sku_id` matches. This reconciliation is recomputed on every order reserve, cancellation, pickup, and return.

Available inventory for a new reservation is defined per line as `on_hand_qty` minus `reserved_qty`. If any line — SKU-based or bundle-based — would exceed this availability at reserve time, the reservation is rejected with `ERR_INSUFFICIENT_STOCK`.

### 2.9. Seasonal Availability and Temporal Boundaries

A SKU may be marked as seasonal by specifying an inclusive start and end datetime in `seasonal_window_start` and `seasonal_window_end`; evergreen SKUs leave both fields null. If any line of an order at reserve time references a SKU whose seasonal window is set, the server clock must lie within the closed interval `[seasonal_window_start, seasonal_window_end]`. Reserving outside the window is rejected with `ERR_SEASONAL_WINDOW_CLOSED`.

Two other temporal boundaries govern the order lifecycle. For a BOPIS order, the pickup deadline is computed at reserve time as `pickup_window_end` plus 48 hours and stored in `pickup_deadline`; the customer must be picked up before the server clock reaches this deadline, otherwise the order is swept to `CANCELLED` by the no-show mechanism described in §2.13. The return window for an already picked-up order is 14 days measured from the timestamp at which the order transitioned into `PICKED_UP`. The return endpoint accepts requests only while the server clock is on or before this fourteenth-day boundary — the interval is closed on the right against the pickup timestamp plus fourteen 86,400-second days.

Delivery slots and rental periods use half-open intervals `[window_start, window_end)` and `[rental_start, rental_end)`, meaning that a slot or contract whose end coincides with the next slot's or contract's start does not overlap.

### 2.10. Helium Tank Allocation

Helium is drawn from physical tanks in a deterministic waterfall. When an `Order` is reserved and has an attached `HeliumOrder`, the server computes the required cubic feet as `latex_count` times half a cubic foot plus `foil_count` times one and a half cubic feet, then draws from `HeliumTank` rows with `status` equal to `ACTIVE` in ascending order of `created_at`; ties on `created_at` are broken by `tank_code` in ascending alphabetical order, never by `id`. The current tank is exhausted before the next is touched: for each tank the server takes the smaller of the tank's `remaining_cubic_ft` and the residual required amount, appends the tank's `id` to `helium_tank_ids` on the `HeliumOrder`, and decrements `remaining_cubic_ft` accordingly. If the sum of `remaining_cubic_ft` across all `ACTIVE` tanks falls short of the required amount, the reservation is rejected with `ERR_HELIUM_INSUFFICIENT`. A tank's `status` can additionally take the values `EMPTY` and `OUT_OF_SERVICE`; only `ACTIVE` tanks participate in allocation, and the tank's `capacity_cubic_ft` fixes the ceiling to which a refill restores `remaining_cubic_ft`.

### 2.11. Optimistic Concurrency Control

Two write endpoints protect their target against unobserved mutation by requiring a client-supplied version number.

Reserving an order requires the payload to carry `expected_order_version` as a non-optional input field. This value must equal the current `version` of the target `Order`. If another writer has advanced the order's `version` since the client last read it — for example by editing its order lines or cancelling the order — the reservation is rejected with `ERR_STALE_ORDER_VERSION` and HTTP 412, preventing the client from committing a reservation against an order shape it has not observed. This is framed strictly in stale-version terms and does not depend on any parallelism assumption; a second sequential reserve that still carries the pre-mutation version deterministically fails.

Applying clearance to a SKU requires the payload to carry `expected_sku_version` as a non-optional input field, matching the current `version` of the target `Sku`. If the SKU has been repriced or unclearanced since the client last read it, the request is rejected with `ERR_STALE_SKU_VERSION` and HTTP 412 — the caller's chosen `clearance_pct` was picked against a stale `unit_price_cents`.

No other endpoint takes an expected-version field, and endpoints that are not on the OCC list of these two write endpoints do not perform this check.

### 2.12. Compensating Money Movement and Store Credit

Refunds are never routed back to the tender the customer originally paid on. Instead the system maintains a `store_credit_cents` balance per `Customer`, and cancellations and returns credit that balance so that the composite of the order total plus the store credit remains conserved.

Specifically, when a `READY_FOR_PICKUP` order is swept to `CANCELLED` for missing the pickup deadline, the order's `payment_status` moves from either `DEPOSIT_HELD` or `PAID` to `REFUNDED` and the customer's `store_credit_cents` is increased by the order's `grand_total_cents`. When an `EventBooking` is cancelled with at least seven days of remaining lead time, the customer's `store_credit_cents` is increased by the booking's `deposit_cents` and the parent order's `payment_status` flips from `DEPOSIT_HELD` to `REFUNDED`. When a rental contract is returned on time, the customer's `store_credit_cents` is increased by the contract's `deposit_cents`; a late return or a damaged-contract transition forfeits the deposit — the customer's `store_credit_cents` is not adjusted.

An event booking that reaches its lead-time cutoff without being confirmed and completed is forfeited: the deposit is intentionally not refunded, expressing the fact that the store's operational capacity was blocked. The compensating money invariant is deliberately not satisfied in this case.

### 2.13. Scheduled System Sweeps

The server maintains a logical clock that starts at `2026-03-01T00:00:00Z` before any explicit set operation. Advancing this clock via the test-driving clock endpoint — which accepts the new instant as an ISO 8601 UTC value in the `to_iso8601` field — runs two sweeps synchronously as part of the same request.

The first is the no-show sweep. Every `Order` whose `fulfillment_status` is `READY_FOR_PICKUP` and whose `pickup_deadline` is now on or before the new clock is moved to `CANCELLED`. Its reservations release: `reserved_qty` on every affected SKU decreases by the corresponding line quantity, any helium allocation is returned to the source tanks, and any attached `DeliverySlot` moves from `RESERVED` to `CANCELLED`. The payment axis moves from `DEPOSIT_HELD` or `PAID` to `REFUNDED` and the customer's `store_credit_cents` is credited with the order's `grand_total_cents`.

The second is the event forfeit sweep. Every `EventBooking` whose `status` is `HELD` or `CONFIRMED` and whose `event_date` minus the new clock is strictly less than seven days is moved to `FORFEITED`. The booking's `deposit_cents` is not refunded and `store_credit_cents` is not increased.

Both sweeps also refresh `updated_at` on every affected row and increment its `version`.

## 3. Business Logic & Workflows

### 3.1. Catalog Curation: SKUs, Bundles, and Clearance

The catalog is authored by a `StoreManager`. A SKU is created with a business `sku_code` that is unique across the catalog, a `category` from the enumeration `BALLOON_LATEX`, `BALLOON_FOIL`, `COSTUME`, `TABLEWARE`, `DECOR`, `PRINT_CUSTOM`, `HELIUM`, and `SEASONAL_HALLOWEEN`, a `unit_price_cents` retail price in whole cents, an optional `theme_tag` — commonly a string such as `UNICORN`, `STAR_WARS`, or `HALLOWEEN_CLASSIC` — and an optional pair of seasonal boundaries `seasonal_window_start` and `seasonal_window_end`. On creation the server initialises `on_hand_qty` and `reserved_qty` to zero, sets `is_clearance` to false, and sets `clearance_pct` to zero. Restocking increases `on_hand_qty` by a caller-supplied `delta` and increments the SKU's `version`.

Bundles are the second catalog surface. A `Bundle` has a unique `bundle_code`, a `theme_tag`, a fixed `bundle_price_cents` charged whenever the bundle is ordered as a unit, and a computed `status` that is one of `ACTIVE` or `DISCONTINUED` and defaults to `ACTIVE`. Bundles are created together with their `BundleLine` rows in a single request through a `lines` payload; every `BundleLine` names its parent `bundle_id`, the constituent `sku_id`, and a `qty` of at least one that expresses how many units of that SKU are consumed per bundle unit ordered. The bundle price is therefore a dual-variant pricing subject: buying the components as separate order lines produces a different `subtotal_cents` from buying the bundle as one line, and the choice belongs to the customer.

Clearance is a two-state transition on `Sku`. Moving a SKU from `is_clearance` false to `is_clearance` true requires the manager to supply a `pct` value that is strictly greater than zero and at most nine-tenths — a value outside this range is rejected with `ERR_CLEARANCE_PCT_OUT_OF_RANGE`. The transition sets `is_clearance` to true, stores `pct` into `clearance_pct`, and increments the SKU's `version`. Reversing clearance moves `is_clearance` back to false, resets `clearance_pct` to zero, and again increments `version`. The clearance transition is OCC-guarded on the SKU version — see §2.11. Once a SKU carries `is_clearance` true, order lines referencing it are pinned at the discounted price at reservation time, but the SKU is also permanently marked non-returnable in the sense of the return endpoint: any attempt to return an order at least one of whose lines references an `is_clearance` true SKU is rejected with `ERR_CLEARANCE_NON_RETURNABLE`.

### 3.2. Helium Tank Fleet

A `HeliumTank` is a physical unit of the store's helium fleet, authored by a `StoreManager` with a unique `tank_code` and an initial `capacity_cubic_ft` of at least zero. On creation, `remaining_cubic_ft` is set equal to `capacity_cubic_ft` and `status` is set to `ACTIVE`. A test-driving refill capability restores `remaining_cubic_ft` to `capacity_cubic_ft` and forces `status` back to `ACTIVE`; the general-purpose fleet lifecycle in the catalog does not otherwise mutate a tank outside of the allocation waterfall described in §2.10 and the reversals described in §3.5.

### 3.3. Delivery Slot Booking

A delivery slot is a per-van block of on-the-road time authored by a `StoreClerk`. Creating a slot supplies `window_start` and `window_end` (interpreted as half-open per §2.9), the `van_id` that will run it, and an optional `setup_included` boolean that defaults to false. On creation, `status` is set to `AVAILABLE`, `order_id` is null, and the row is persisted. The system rejects a create request whose half-open interval `[window_start, window_end)` overlaps another slot's interval on the same `van_id` with `ERR_DELIVERY_SLOT_CONFLICT`; two slots that share only an endpoint (one ends exactly when the other starts) do not overlap.

A slot progresses through `AVAILABLE`, `RESERVED`, `COMPLETED`, and `CANCELLED`. Its transitions are always driven by the associated order rather than by a direct action on the slot: attaching the slot to an order at reservation flips it to `RESERVED` and stamps `order_id`; delivering the order flips it to `COMPLETED`; cancelling the order or sweeping it as a no-show flips it to `CANCELLED`.

### 3.4. Order Assembly and Reservation

The order lifecycle begins when a `StoreClerk` creates a new `Order` with a `customer_id` referencing an existing customer, a `channel`, and a `lines` list. Each entry in `lines` becomes an `OrderLine` carrying its parent `order_id`, either a `sku_id` or a `bundle_id` (exactly one; the other is null), and a `qty` of at least one. For `BOPIS` channel orders the request additionally supplies `pickup_window_start` and `pickup_window_end`; for `DELIVERY` channel orders it supplies `delivery_slot_id` referencing an available slot. The new order is created with `fulfillment_status` `DRAFT` and `payment_status` `UNPAID`. While the order is `DRAFT`, add-ons may be attached to it: a `HeliumOrder` recording a `latex_count` (at least zero) of eleven-inch latex balloons and a `foil_count` (at least zero) of eighteen-inch foil balloons to fill; a `CustomPrintOrder` recording an `art_reference` string and a `banner_length_ft` value of at least one; one or more `RentalContract` rows for tableware add-ons; and an `EventBooking` naming an `event_package_id` and an `event_date`.

Reservation is the pivotal transition that moves the order from `DRAFT` to `RESERVED`. The reserve request carries `expected_order_version` per §2.11 and, when it succeeds, has cascading consequences. The order must have at least one order line; if any order line references a SKU the availability check `on_hand_qty` minus `reserved_qty` is at least the line `qty` must hold, and if any order line references a bundle then, aggregated across every `BundleLine` of that bundle, the reservable quantity of each constituent SKU must be at least `BundleLine.qty` multiplied by `OrderLine.qty`. If any of these checks fails, the reserve is rejected with `ERR_INSUFFICIENT_STOCK`. If the order has a helium add-on, the sum of `remaining_cubic_ft` across `ACTIVE` tanks must cover the requirement per §2.10, otherwise `ERR_HELIUM_INSUFFICIENT`. If the order's `channel` is `DELIVERY`, exactly one `DeliverySlot` must be referenced and its `status` must currently be `AVAILABLE`. For every SKU line whose seasonal window is set, the server clock must lie within `[seasonal_window_start, seasonal_window_end]`, otherwise `ERR_SEASONAL_WINDOW_CLOSED`.

When these preconditions all pass, the server performs the cascade. Each affected SKU's `reserved_qty` is increased by the corresponding line quantity. Each affected helium tank's `remaining_cubic_ft` is decreased in waterfall order, and the resulting tank id list is written to `helium_tank_ids` on the `HeliumOrder`. The referenced `DeliverySlot` flips from `AVAILABLE` to `RESERVED` and its `order_id` is set. Each `OrderLine`'s `unit_price_cents_at_capture` is pinned — from the SKU's `unit_price_cents` with `clearance_pct` applied when the SKU is on clearance, or from the bundle's `bundle_price_cents` when the line is a bundle line — and its `line_total_cents` is set to `qty` multiplied by `unit_price_cents_at_capture`. Order-level fees are recomputed as `subtotal_cents`, `helium_fee_cents`, `delivery_fee_cents`, `deposit_cents`, and `grand_total_cents`. For `BOPIS` orders, `pickup_deadline` is set to `pickup_window_end` plus 48 hours. Finally, the order's `version` is incremented by one.

The order grand total is fully pinned at this point and is the finalised variant of the calculation. Before reserve, while the order is still in `DRAFT`, the system exposes a provisional variant of the same total that reads the live `Sku.unit_price_cents` without any clearance snapshot lock, and that excludes `HeliumOrder`, `DeliverySlot`, and `RentalContract` deposits — this provisional total is intended for quoting only and may differ from the finalised total for the same set of entities whenever a SKU is later placed on clearance or an add-on is later attached between draft and reserve. The provisional variant is written onto the DRAFT order's monetary fields at order creation time and is what the create-order response returns: `subtotal_cents` carries the sum of `qty` multiplied by the referenced SKU's live `unit_price_cents` (or the bundle's `bundle_price_cents` for a bundle line) across the initial lines, plus the attached non-cancelled `CustomPrintOrder`'s `print_fee_cents` if one is already pinned; `deposit_cents` carries the attached `EventBooking`'s `deposit_cents` when its `status` is `HELD` or `CONFIRMED` and is zero otherwise; `helium_fee_cents` and `delivery_fee_cents` are zero on a DRAFT order because the provisional variant excludes helium fill fees and delivery fees; and `grand_total_cents` is the sum of `subtotal_cents` and `deposit_cents`. The finalised total is computed as follows. For each order line the server rounds `qty` multiplied by `unit_price_cents_at_capture` (already an integer, so the rounding is a no-op) and sums the results into `subtotal_cents`; if a `CustomPrintOrder` is attached and not cancelled, its `print_fee_cents` is added to `subtotal_cents`. `helium_fee_cents` is the `fill_fee_cents` of the attached `HeliumOrder` when present and zero otherwise. `delivery_fee_cents` is the fee produced by the delivery-fee rule for the attached `DeliverySlot` when the channel is `DELIVERY`, and zero otherwise. `deposit_cents` is the sum of `deposit_cents` across every `RentalContract` on the order whose `status` is `RESERVED` or `PICKED_UP`, plus the `deposit_cents` of the attached `EventBooking` when present and its `status` is `HELD` or `CONFIRMED`. `grand_total_cents` is then `subtotal_cents` plus `helium_fee_cents` plus `delivery_fee_cents` plus `deposit_cents`. The input set for the calculation is every `OrderLine` on the order regardless of status, the single `HeliumOrder` if present, the single `DeliverySlot` if the channel is `DELIVERY`, every `RentalContract` with `status` in `RESERVED` or `PICKED_UP`, the attached `EventBooking` if its `status` is `HELD` or `CONFIRMED`, and the attached `CustomPrintOrder` if its `status` is anything other than `CANCELLED`. Every monetary value is rounded half-up to whole cents at each stated rounding step; per-line rounding happens before the sum. Once the order is reserved, this value is immutable with respect to later catalog edits to the underlying SKUs — subsequently placing one of the SKUs on clearance does not mutate the reserved order's grand total.

The helium fill fee is a two-tier per-line calculation. The latex line is computed as `latex_count` multiplied by 175 cents per balloon, then multiplied by 0.85 if `latex_count` is at least 25 and 1.0 otherwise, and rounded half-up to whole cents. The foil line is computed as `foil_count` multiplied by 425 cents per balloon, then multiplied by 0.90 if `foil_count` is at least 10 and 1.0 otherwise, and rounded half-up to whole cents. The `fill_fee_cents` of the helium order is the sum of the two rounded line values — round each line first, then add. Reversing the rounding order shifts the total by one or two cents on boundary inputs, which is why the order is pinned.

The delivery fee is a base plus two optional surcharges. Base delivery is 2500 cents. If `setup_included` is true, 1500 cents is added. If the weekday of `window_start` in UTC is Saturday or Sunday, an additional 1000 cents weekend surcharge is added. The result is the slot's contribution to `delivery_fee_cents`.

### 3.5. Payment, Fulfillment, and Refund Reversals

Payment is recorded through a payment operation carrying a `mode` field. When `mode` is `DEPOSIT`, the request records a partial payment: it is accepted only while the order is `RESERVED` and the order has either an attached `EventBooking` or an attached `RentalContract`; otherwise the request is rejected with `ERR_DEPOSIT_NOT_APPLICABLE`. On acceptance, `payment_status` moves from `UNPAID` to `DEPOSIT_HELD` and `version` increments. When `mode` is `FULL`, the payment is a full payment: it is accepted while the order's `fulfillment_status` is `RESERVED`, `PICKING`, or `READY_FOR_PICKUP` and while `payment_status` is `UNPAID` or `DEPOSIT_HELD`, moving `payment_status` to `PAID` and incrementing `version`.

Fulfillment then proceeds axis-independently along the fulfillment machine. Starting picking transitions `RESERVED` to `PICKING`, but only if `payment_status` is in `DEPOSIT_HELD` or `PAID`. Marking ready transitions `PICKING` to `READY_FOR_PICKUP`, and is available only for `BOPIS` orders — delivery and in-store channels bypass this state. Picking up transitions `READY_FOR_PICKUP` to `PICKED_UP`, requires `payment_status` to be `PAID`, and requires the server clock to be strictly before `pickup_deadline`. Pickup cascades: for every order line, `reserved_qty` on the referenced SKU decreases by the line quantity and `on_hand_qty` decreases by the same amount, and for every attached `RentalContract` whose `status` is `RESERVED` the contract's `status` becomes `PICKED_UP` while additionally decreasing both `reserved_qty` and `on_hand_qty` on the rental's SKU by the contract's `qty`. Delivering is available only when `channel` is `DELIVERY` and the fulfillment axis is `PICKED_UP`, and additionally only when the server clock is within the half-open interval of the referenced `DeliverySlot`; a successful transition flips the slot from `RESERVED` to `COMPLETED`.

Returning transitions `PICKED_UP` or `DELIVERED` to `RETURNED` and is permitted only if the server clock is on or before the pickup timestamp plus fourteen days and if no line's SKU carries `is_clearance` true — clearance items cannot be returned per §3.1. On success, `on_hand_qty` for each line's SKU is restored by the line quantity, `payment_status` flips from `PAID` to `REFUNDED` (or to `PARTIALLY_REFUNDED` if only part of the amount is refunded), and `store_credit_cents` on the customer is credited with the returned `grand_total_cents`.

Cancellation from `DRAFT`, `RESERVED`, or `PICKING` moves the fulfillment axis to `CANCELLED`. On success, `reserved_qty` on every referenced SKU is decremented, any helium allocation is returned by adding it back to the source tanks' `remaining_cubic_ft`, any attached `DeliverySlot` flips from `RESERVED` to `CANCELLED`, `payment_status` flips from `DEPOSIT_HELD` to `REFUNDED` when a deposit was held, and `version` increments. Attempted transitions on either axis whose preconditions are not met are rejected with `ERR_INVALID_STATE`.

### 3.6. Rental Contracts: Deposits, Returns, and Damage

A `RentalContract` is a tableware add-on attached to a specific `Order`. Creation takes an `order_id`, a `sku_id`, a `qty` of at least one, and a `rental_start` and `rental_end` pair interpreted as half-open per §2.9. The referenced SKU must have `category` equal to `TABLEWARE`; a contract that names any other category is rejected with `ERR_RENTAL_CATEGORY_INVALID`. The contract's `[rental_start, rental_end)` interval is additionally checked against every other non-terminal contract on the same `sku_id`: if the aggregate concurrent reserved quantity — the sum of `qty` across contracts whose intervals overlap this one — would exceed the SKU's `on_hand_qty`, the create is rejected with `ERR_RENTAL_OVERLAP_CAPACITY`. On creation, `status` is set to `RESERVED` and `deposit_cents` is pinned by the rental deposit rule below.

The rental deposit is deliberately insensitive to clearance discount. Let the deposit multiplier be 2.0; the per-unit deposit is the SKU's undiscounted `unit_price_cents` multiplied by 2.0, rounded half-up to whole cents, and the contract's `deposit_cents` is that per-unit value multiplied by `qty`. Even when the underlying SKU is on clearance, the deposit uses the full retail unit price rather than the discounted one — this ring-fences the store's exposure against damage or non-return regardless of promotional pricing.

The rental lifecycle takes the values `RESERVED`, `PICKED_UP`, `RETURNED`, `LATE_RETURN`, and `DAMAGED`. A rental transitions from `RESERVED` to `PICKED_UP` as a side effect of the parent order transitioning into `PICKED_UP`; there is no direct action for this transition. From `PICKED_UP` the contract can go three ways. A return-marking action while the server clock is strictly before `rental_end` transitions the contract to `RETURNED`, sets `returned_at` to the current server clock, adds `qty` back to the SKU's `on_hand_qty`, and credits the customer's `store_credit_cents` by the contract's `deposit_cents`. The same action while the server clock is at or after `rental_end` transitions to `LATE_RETURN` instead, still setting `returned_at` and restoring `on_hand_qty`, but forfeiting the deposit — the customer's `store_credit_cents` is not adjusted, and the effective late fee equals the full deposit. A separate damage-marking action, valid while the contract is `PICKED_UP`, transitions the contract to `DAMAGED` and forfeits the deposit.

### 3.7. Custom Print Workflow

A `CustomPrintOrder` is a banner-printing add-on attached to a `DRAFT` order. Attachment supplies an `art_reference` — a URL or design code identifying the customer-supplied artwork — and a `banner_length_ft` value of at least one. The record is created with `status` `DRAFT`, `revision_count` zero, and no pinned fee.

The workflow is cyclic. A `StoreClerk` sends the first proof to the customer, transitioning `DRAFT` to `PROOF_SENT`. From `PROOF_SENT`, the customer either requests a revision or approves the proof. A revision request transitions `PROOF_SENT` to `REVISION_REQUESTED`, increments `revision_count` by one, and is permitted only when `revision_count` is currently less than 3 — a fourth revision attempt is rejected with `ERR_REVISION_LIMIT`. A subsequent proof send by the clerk takes `REVISION_REQUESTED` back to `PROOF_SENT`, and the loop continues until the customer either approves or the revision cap is hit. Approval transitions `PROOF_SENT` to `APPROVED` and is permitted only when the parent order's `payment_status` is `PAID`. From `APPROVED` the clerk starts printing (`PRINTING`), then marks the print ready (`READY`). Cancellation is permitted from `DRAFT`, `PROOF_SENT`, or `REVISION_REQUESTED` and moves the record to `CANCELLED`. `READY` and `CANCELLED` are terminal.

The print fee is a tiered marginal calculation, pinned by the sum-then-round ordering. Let the first tier end at 5 feet and the second at 15 feet. The first tier rate is 800 cents per foot, the second is 600 cents per foot, and the third — for any additional feet beyond 15 — is 450 cents per foot. Let the number of feet in the first tier be the smaller of `banner_length_ft` and 5; let the number of feet in the second tier be the maximum of zero and the smaller of `banner_length_ft` and 15 reduced by 5; let the number of feet in the third tier be the maximum of zero and `banner_length_ft` reduced by 15. The unrounded fee is the first-tier feet multiplied by 800 plus the second-tier feet multiplied by 600 plus the third-tier feet multiplied by 450 — each per-tier product is left unrounded. To this the server adds a revision surcharge of 500 cents multiplied by the maximum of zero and `revision_count` minus one — the first revision is free, and each additional revision costs 500 cents. The final `print_fee_cents` is this sum rounded half-up once at the end. Unlike the helium fill fee, no per-tier rounding happens; reversing the order would change the total on boundary inputs.

Two variants of the print fee co-exist. When the customer first receives a proof, an estimated variant of the fee — computed with `revision_count` treated as zero — is displayed as the fee the customer would pay if they approved immediately; this estimate is not persisted onto the order. The finalised variant runs at approve time and uses the actual observed `revision_count`; the result is written to `CustomPrintOrder.print_fee_cents`, and the parent order's `subtotal_cents` and `grand_total_cents` are then recomputed to include it. For a ten-foot banner approved after two revision cycles, the finalised fee therefore exceeds the estimated fee by 500 cents per revision beyond the first — identical `banner_length_ft` inputs produce different persisted results whenever revisions accumulate.

### 3.8. Event Packages and Bookings

A `StoreManager` authors reusable `EventPackage` templates. Each package has a unique `package_code`, a `base_price_cents`, a `deposit_pct` between zero and one, and a `min_lead_days` value expressing the minimum number of days that must sit between deposit and event date. A `StoreClerk` then creates an `EventBooking` attached to a specific `Order`, supplying the parent `order_id`, an `event_package_id`, and the scheduled `event_date`. On creation, `status` is set to `HELD` and `deposit_cents` is pinned as the referenced package's `base_price_cents` multiplied by its `deposit_pct` and rounded half-up to whole cents.

Confirming a booking transitions `HELD` to `CONFIRMED`. This is permitted only when the parent order's `payment_status` is `DEPOSIT_HELD` or `PAID`, and when `event_date` minus the server clock is at least `min_lead_days` — a shorter lead time is rejected with `ERR_EVENT_LEAD_TOO_SHORT`. Completing a booking transitions `CONFIRMED` to `COMPLETED` and is permitted only when the server clock has reached or passed `event_date`; on success, the parent order's `payment_status` flips from `DEPOSIT_HELD` to `PAID` unless it was already `PAID`.

Cancelling an event booking transitions `HELD` or `CONFIRMED` to `CANCELLED`, but only while `event_date` minus the server clock is at least seven days; a later cancellation attempt is rejected with `ERR_EVENT_CANCEL_TOO_LATE`. On success, the customer's `store_credit_cents` is credited with the booking's `deposit_cents`, and the parent order's `payment_status` flips from `DEPOSIT_HELD` to `REFUNDED`.

If, in the absence of a completion, the server clock advances to within seven days of the event and the booking's `status` is still `HELD` or `CONFIRMED`, the scheduled forfeit sweep described in §2.13 moves the booking to `FORFEITED` and the deposit is intentionally not refunded.

### 3.9. Validation Priority

The validations above are applied in a fixed priority order so that failures early in the chain surface before the checks that would otherwise mask them. Authentication is checked first — a missing header raises `ERR_UNAUTHENTICATED`. Role recognition is next — an unknown `X-User-Role` raises `ERR_UNKNOWN_ROLE`. Endpoint authorisation is third — a recognised role that is not on the endpoint's allowed list raises `ERR_FORBIDDEN`. Path-referenced resource existence is fourth, raising `ERR_NOT_FOUND`. Body-referenced foreign key existence is fifth, raising `ERR_FK_NOT_FOUND`. State-machine legality of the requested transition is sixth, raising `ERR_INVALID_STATE`. Optimistic-concurrency version match is seventh, raising `ERR_STALE_ORDER_VERSION` or `ERR_STALE_SKU_VERSION` on the two OCC-guarded endpoints. The business-safety clearance-non-returnable check is eighth, raising `ERR_CLEARANCE_NON_RETURNABLE`. Then the business-referential rental category check is ninth, raising `ERR_RENTAL_CATEGORY_INVALID`. The business-temporal checks follow in order: seasonal window at reserve (`ERR_SEASONAL_WINDOW_CLOSED`, tenth), event lead at confirm (`ERR_EVENT_LEAD_TOO_SHORT`, eleventh), delivery slot overlap at slot creation (`ERR_DELIVERY_SLOT_CONFLICT`, twelfth), rental overlap capacity at rental creation (`ERR_RENTAL_OVERLAP_CAPACITY`, thirteenth). Then business-constraint checks: aggregate stock at reserve (`ERR_INSUFFICIENT_STOCK`, fourteenth), helium sufficiency at reserve (`ERR_HELIUM_INSUFFICIENT`, fifteenth), revision limit at revision request (`ERR_REVISION_LIMIT`, sixteenth). Business-fiscal checks: clearance percentage bounds (`ERR_CLEARANCE_PCT_OUT_OF_RANGE`, seventeenth) and deposit applicability (`ERR_DEPOSIT_NOT_APPLICABLE`, eighteenth). Finally, malformed or missing required input fields raise `ERR_INVALID_REQUEST` at nineteenth priority. When several checks would apply to the same request, the earliest priority is the one that determines the reported error.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (for example a new SKU, bundle, order, rental contract, or event booking) return `201 Created`. Operations that modify an existing resource, including state-transition endpoints, return `200 OK`. All list endpoints support the `limit` and `offset` query parameters described in §2.3.

| Method | Path                                             | Description                                                                        | Authorized Role(s)                                     |
| ------ | ------------------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------ |
| POST   | `/api/skus`                                      | Create a SKU                                                                       | StoreManager                                           |
| GET    | `/api/skus/{id}`                                 | Get a SKU                                                                          | StoreManager, StoreClerk, Customer                     |
| GET    | `/api/skus`                                      | List SKUs; supports `theme_tag` and `category` filters                             | StoreManager, StoreClerk, Customer                     |
| POST   | `/api/skus/{id}/clearance`                       | Mark SKU as clearance with `pct` discount; OCC-guarded on `Sku.version`            | StoreManager                                           |
| POST   | `/api/skus/{id}/unclear`                         | Remove clearance flag from SKU                                                     | StoreManager                                           |
| POST   | `/api/skus/{id}/restock`                         | Increase `on_hand_qty` by `delta`                                                  | StoreManager                                           |
| POST   | `/api/bundles`                                   | Create a Bundle with its BundleLines                                               | StoreManager                                           |
| GET    | `/api/bundles/{id}`                              | Get a Bundle (excludes lines)                                                      | StoreManager, StoreClerk, Customer                     |
| GET    | `/api/bundles/{id}/lines`                        | List BundleLines for a specific Bundle                                             | StoreManager, StoreClerk, Customer                     |
| GET    | `/api/bundle-lines`                              | List BundleLines with `sku_id` / `bundle_id` filters                               | StoreManager, StoreClerk, Customer                     |
| GET    | `/api/bundle-lines/{id}`                         | Get a single BundleLine                                                            | StoreManager, StoreClerk, Customer                     |
| POST   | `/api/customers`                                 | Create a Customer                                                                  | StoreClerk                                             |
| GET    | `/api/customers/{id}`                            | Get a Customer                                                                     | StoreClerk, Customer                                   |
| POST   | `/api/orders`                                    | Create Order in DRAFT with lines                                                   | StoreClerk                                             |
| GET    | `/api/orders/{id}`                               | Get an Order                                                                       | StoreClerk, Customer                                   |
| GET    | `/api/orders`                                    | List Orders with optional `customer_id` filter                                     | StoreClerk, Customer                                   |
| GET    | `/api/orders/{id}/lines`                         | List OrderLines for a specific Order                                               | StoreClerk, Customer                                   |
| GET    | `/api/order-lines`                               | List OrderLines with `sku_id` / `bundle_id` / `order_id` filters                   | StoreClerk, Customer                                   |
| GET    | `/api/order-lines/{id}`                          | Get a single OrderLine                                                             | StoreClerk, Customer                                   |
| POST   | `/api/orders/{id}/reserve`                       | Reserve an Order; requires `expected_order_version`; pins prices and allocations   | StoreClerk                                             |
| POST   | `/api/orders/{id}/pay`                           | Record a payment; `mode` is DEPOSIT or FULL                                        | StoreClerk                                             |
| POST   | `/api/orders/{id}/start-picking`                 | Start picking a reserved order                                                     | StoreClerk                                             |
| POST   | `/api/orders/{id}/mark-ready`                    | Mark a BOPIS order ready for pickup                                                | StoreClerk                                             |
| POST   | `/api/orders/{id}/pickup`                        | Record pickup of a ready order                                                     | StoreClerk                                             |
| POST   | `/api/orders/{id}/deliver`                       | Record delivery of an already-picked-up DELIVERY order                             | DeliveryDriver                                         |
| POST   | `/api/orders/{id}/return`                        | Return a picked-up or delivered order                                              | StoreClerk                                             |
| POST   | `/api/orders/{id}/cancel`                        | Cancel an order in DRAFT, RESERVED, or PICKING                                     | StoreClerk                                             |
| POST   | `/api/orders/{id}/helium`                        | Attach a HeliumOrder to a DRAFT order                                              | StoreClerk                                             |
| GET    | `/api/orders/{id}/helium`                        | Get the HeliumOrder for a specific Order                                           | StoreClerk, Customer                                   |
| POST   | `/api/helium-tanks`                              | Create a HeliumTank                                                                | StoreManager                                           |
| GET    | `/api/helium-tanks/{id}`                         | Get a HeliumTank                                                                   | StoreManager, StoreClerk                               |
| GET    | `/api/helium-tanks`                              | List HeliumTanks with optional `status` filter                                     | StoreManager, StoreClerk                               |
| POST   | `/api/delivery-slots`                            | Create a DeliverySlot; overlap check per `van_id`                                  | StoreClerk                                             |
| GET    | `/api/delivery-slots/{id}`                       | Get a DeliverySlot                                                                 | StoreClerk                                             |
| GET    | `/api/delivery-slots`                            | List DeliverySlots with `order_id` / `van_id` / `status` filters                   | StoreClerk                                             |
| POST   | `/api/rental-contracts`                          | Create a RentalContract on an Order                                                | StoreClerk                                             |
| GET    | `/api/rental-contracts/{id}`                     | Get a RentalContract                                                               | StoreClerk, Customer                                   |
| GET    | `/api/rental-contracts`                          | List RentalContracts with `order_id` / `sku_id` / `status` filters                 | StoreClerk, Customer                                   |
| POST   | `/api/rental-contracts/{id}/return`              | Return a rental (RETURNED or LATE_RETURN based on server clock vs `rental_end`)    | StoreClerk                                             |
| POST   | `/api/rental-contracts/{id}/mark-damaged`        | Mark a rental as damaged; forfeits deposit                                         | StoreClerk                                             |
| POST   | `/api/orders/{id}/custom-print`                  | Attach a CustomPrintOrder to a DRAFT Order                                         | StoreClerk                                             |
| GET    | `/api/custom-print-orders/{id}`                  | Get a CustomPrintOrder                                                             | StoreClerk, Customer                                   |
| GET    | `/api/custom-print-orders`                       | List CustomPrintOrders with `order_id` / `status` filters                          | StoreClerk, Customer                                   |
| POST   | `/api/custom-print-orders/{id}/send-proof`       | Send a proof (DRAFT/REVISION_REQUESTED → PROOF_SENT)                               | StoreClerk                                             |
| POST   | `/api/custom-print-orders/{id}/request-revision` | Customer requests revision (PROOF_SENT → REVISION_REQUESTED)                       | Customer                                               |
| POST   | `/api/custom-print-orders/{id}/approve`          | Customer approves the proof; pins `print_fee_cents` and cascades into Order totals | Customer                                               |
| POST   | `/api/custom-print-orders/{id}/start-print`      | APPROVED → PRINTING                                                                | StoreClerk                                             |
| POST   | `/api/custom-print-orders/{id}/mark-ready`       | PRINTING → READY                                                                   | StoreClerk                                             |
| POST   | `/api/custom-print-orders/{id}/cancel`           | Cancel a CustomPrintOrder                                                          | StoreClerk                                             |
| POST   | `/api/event-packages`                            | Create an EventPackage                                                             | StoreManager                                           |
| GET    | `/api/event-packages/{id}`                       | Get an EventPackage                                                                | StoreManager, StoreClerk, Customer                     |
| GET    | `/api/event-packages`                            | List EventPackages                                                                 | StoreManager, StoreClerk, Customer                     |
| POST   | `/api/event-bookings`                            | Create an EventBooking attached to an Order                                        | StoreClerk                                             |
| GET    | `/api/event-bookings/{id}`                       | Get an EventBooking                                                                | StoreClerk, Customer                                   |
| GET    | `/api/event-bookings`                            | List EventBookings with `order_id` / `event_package_id` / `status` filters         | StoreClerk, Customer                                   |
| POST   | `/api/event-bookings/{id}/confirm`               | HELD → CONFIRMED                                                                   | StoreClerk                                             |
| POST   | `/api/event-bookings/{id}/complete`              | CONFIRMED → COMPLETED                                                              | StoreClerk                                             |
| POST   | `/api/event-bookings/{id}/cancel`                | Cancel with at least seven days lead — refunds deposit as store credit             | StoreClerk                                             |
| POST   | `/api/_clock/set_current_utc`                    | Advance server logical clock; runs no-show and event-forfeit sweeps                | StoreManager, StoreClerk                               |
| POST   | `/api/_helium-tanks/{id}/refill`                 | Refill a HeliumTank to full capacity                                               | StoreManager                                           |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_UNAUTHENTICATED`             | 401              |
| `ERR_UNKNOWN_ROLE`                | 401              |
| `ERR_FORBIDDEN`                   | 403              |
| `ERR_NOT_FOUND`                   | 404              |
| `ERR_FK_NOT_FOUND`                | 404              |
| `ERR_INVALID_STATE`               | 409              |
| `ERR_STALE_ORDER_VERSION`         | 412              |
| `ERR_STALE_SKU_VERSION`           | 412              |
| `ERR_CLEARANCE_NON_RETURNABLE`    | 422              |
| `ERR_RENTAL_CATEGORY_INVALID`     | 422              |
| `ERR_SEASONAL_WINDOW_CLOSED`      | 422              |
| `ERR_EVENT_LEAD_TOO_SHORT`        | 422              |
| `ERR_DELIVERY_SLOT_CONFLICT`      | 409              |
| `ERR_RENTAL_OVERLAP_CAPACITY`     | 409              |
| `ERR_INSUFFICIENT_STOCK`          | 422              |
| `ERR_HELIUM_INSUFFICIENT`         | 422              |
| `ERR_REVISION_LIMIT`              | 422              |
| `ERR_CLEARANCE_PCT_OUT_OF_RANGE`  | 422              |
| `ERR_DEPOSIT_NOT_APPLICABLE`      | 422              |
| `ERR_INVALID_REQUEST`             | 400              |
| `ERR_EVENT_CANCEL_TOO_LATE`       | 422              |
