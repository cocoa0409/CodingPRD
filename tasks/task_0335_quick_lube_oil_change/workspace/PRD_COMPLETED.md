# Quick Lube & Oil Change API — Product Requirements Document

## 1. Introduction

The Quick Lube & Oil Change API powers a high-throughput drive-in service operation where vehicles arrive without appointments, wait in a first-come-first-served queue, and are pulled into a finite set of service bays as those bays free up. The platform must reconcile two competing realities at once: the physical scarcity of bays and certified technicians, and the commercial machinery of service packages, upsell inspections, coupons, fleet discounts, and sales tax. A bay is a conserved resource — it can hold exactly one vehicle at a time, and every assignment, completion, or cancellation must keep the shop's live count of open bays honest.

The system serves four distinct operator surfaces. Shop managers configure the catalog of oil-change packages, upsell items, coupons, bays, technicians, and corporate fleet accounts. Front-desk service advisors run the drive-in queue, register vehicles, create work orders, apply coupons, and settle payment. Technicians perform the physical service, adding or removing inspection upsells and driving each order through its service stages while a throughput clock measures how long the job takes against the shop's target. Fleet managers represent corporate customers and may only see and act on their own account.

Beyond the mechanics of moving cars through bays, the API is a pricing engine and a reminder engine. Every work order accrues a provisional price that is recomputed each time a line is added or removed, then frozen into a final total the moment service is marked ready. When a job completes, the system prints a service sticker and projects the vehicle's next due date and odometer so the shop knows when to remind the customer. Fleet credit must never be overcommitted, coupons must never be over-redeemed, and synthetic-grade oil must never be serviced in a bay or by a technician that is not certified for it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. The collections in this API are flat and root-level: there is no shared URL prefix, and every resource is addressed directly under the server root.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing or malformed in either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `ShopManager`, `ServiceAdvisor`, `Technician`, and `FleetManager`.

For `ShopManager` and `ServiceAdvisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier but does not compare it to any entity's `id`; these two roles are not scoped to ownership of a particular resource. For `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity; ownership checks on any resource that references a technician compare that resource's technician foreign key to `X-User-ID`. For `FleetManager`, `X-User-ID` is the `id` of the acting `FleetAccount` entity; a `FleetManager` may only read and act within its own account, and any attempt to read or act on another account's data — its account, its vehicles, its work orders, or its payments — is rejected with `ERR_FORBIDDEN`. Ownership checks for a `FleetManager` compare the relevant `fleet_account_id` on the target resource (directly, or via the vehicle the resource references) to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint explicitly states otherwise, list endpoints return their resources sorted by `created_at` in ascending order. The one documented exception is the drive-in queue, which is ordered by its intake sequence as described in the queue workflow.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource; it underpins the optimistic concurrency mechanism described in §2.8.

Two entities are deliberate exceptions. A `ServiceSticker` is an immutable printed record: it carries only `id` and `created_at`, and has neither `updated_at` nor `version`. Every other primary resource — `Shop`, `ServicePackage`, `InspectionItem`, `Coupon`, `FleetAccount`, `Vehicle`, `Bay`, `Technician`, `QueueTicket`, `WorkOrder`, `WorkOrderLine`, and `Payment` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

When the server mutates a resource as a side effect of another operation — for example, freeing a bay, re-pricing a work order, or recomputing a fleet account's reserved credit — that reconciliation independently bumps the affected resource's `version` and refreshes its `updated_at`, exactly as a direct mutation would.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several endpoints address a resource through a path that names a parent and then a child — for example, a single line on a work order, or the sticker belonging to a work order. The server validates path identifiers strictly left to right and rejects on the first identifier that does not resolve to an existing row. A request naming a line under a non-existent work order therefore fails with `ERR_WORK_ORDER_NOT_FOUND` before the line is ever consulted; only once the work order is confirmed does a missing line produce `ERR_LINE_NOT_FOUND`.

This existence pass is the third priority check on any path-parameterized request, evaluated only after authentication and role authorization succeed. The catalog of not-found codes is resource-specific: `ERR_SHOP_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_INSPECTION_ITEM_NOT_FOUND`, `ERR_COUPON_NOT_FOUND`, `ERR_FLEET_ACCOUNT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_BAY_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_QUEUE_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, and `ERR_STICKER_NOT_FOUND`, each returned with HTTP 404.

### 2.6. Validation Order and Precedence

When more than one rule could reject a request, the server evaluates them in a fixed precedence so that the reported error is deterministic. The order is: authentication first (`ERR_UNAUTHENTICATED`, 401), then role authorization (`ERR_FORBIDDEN`, 403), then path-identifier existence (the 404 family above), then referential resolution of foreign keys named in the body (such as a coupon code, a package, or a fleet-account requirement, each producing its own 404 as described where it applies), then state-legality of the targeted transition (the 409 family such as `ERR_INVALID_STATE`, `ERR_BAY_NOT_OPEN`, `ERR_BAY_OCCUPIED`, `ERR_BAY_NOT_READY`, and `ERR_PAYMENT_NOT_SETTLED`), then the optimistic-concurrency version check (412), then the synthetic-capability safety checks (409), then bay and technician scheduling-overlap checks (409), then coupon eligibility (409), and finally the fleet-credit fiscal check (`ERR_FLEET_CREDIT_EXCEEDED`, 402). Whenever this document describes several checks on one operation, that operation's checks fire in this relative order, and the first failure is the one returned.

Body-shape problems — a missing required field, a wrong type, an unrecognized enum value, or a negative amount where a non-negative one is required — are reported as `ERR_VALIDATION` (HTTP 400).

### 2.7. Pricing Precision and Monetary Representation

All monetary amounts in this system are integer cents; there are no fractional-cent fields. Wherever a calculation multiplies cents by a rate — a per-line coupon percentage or the sales-tax step — the result is rounded to a whole number of cents using the round-half-up convention, defined as taking the floor of the real-valued product plus one half. The discount cap is computed by taking the floor of the subtotal multiplied by the shop's maximum-discount fraction, with no rounding up. The precise points at which rounding occurs are spelled out in the pricing workflow; the contract here is simply that every stored monetary field is a whole number of cents and that round-half-up governs each per-line discount and the final tax step.

### 2.8. Optimistic Concurrency Control

Two write operations guard against acting on a stale view of their parent resource by requiring the client to echo back the parent's version.

The first is assigning a waiting queue ticket to a bay. That request must carry `expected_bay_version`, which the client sets to the `version` of the target `Bay` as it last observed it. If another writer has advanced the bay's `version` since then — most commonly because the bay was just claimed by a prior assignment that legitimately moved it from `OPEN` to `OCCUPIED` — the value no longer matches the bay's current `version`, and the assignment is rejected with `ERR_STALE_BAY_VERSION` (HTTP 412) rather than allowing the bay to be double-occupied. This field is mandatory on the assignment request.

The second is adding an upsell line to a work order. That request must carry `expected_work_order_version`, set to the `version` of the target `WorkOrder` as last observed. If a prior line add has since recomputed the order's pricing and bumped its `version`, the echoed value is stale, the request does not match the order's current `version`, and it is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412). This field is mandatory on the add-line request. No other endpoint takes a version field, and on every endpoint that does not appear in this section the server performs no version check.

### 2.9. Bay Conservation and the Open-Bay Invariant

Each `Bay` belongs to a shop, carries a human-readable `label`, and is either `OPEN`, `OCCUPIED`, or `CLOSED`. While occupied, a bay's `current_work_order_id` points at the work order filling it; while open or closed it is null. The shop's `open_bay_count` is a conserved tally: it is the count of that shop's bays whose status is `OPEN`, and it must move by exactly one in lock-step with every bay status change. Creating a bay opens it and raises the count by one; closing an open bay lowers it by one; reopening a closed bay raises it by one; occupying a bay lowers it by one; and freeing an occupied bay raises it by one. This invariant must hold after every operation, including the multi-step cascades described in §3.

### 2.10. Synthetic-Grade Capability Gating

Oil grade drives a capability requirement. A `ServicePackage` whose `oil_grade` is `FULL_SYNTHETIC` or `HIGH_MILEAGE` is flagged `requires_synthetic_certified_bay`; a package whose grade is `CONVENTIONAL` or `SYNTHETIC_BLEND` is not. When a synthetic-grade package is being serviced, both the bay and the technician must be certified: the `Bay` must have `synthetic_certified` true, and the `Technician` must have `synthetic_certified` true. These two checks are enforced where service begins, and each has its own rejection code, as detailed in the service workflow.

### 2.11. Fleet Credit Discipline

A `FleetAccount` extends a corporate customer a line of credit capped by `credit_limit_cents`. The account tracks two derived balances. Its `reserved_credit_cents` is the sum of `total_cents` across all work orders of the account's vehicles whose `payment_status` is `AUTHORIZED` or `PAID` — a forward-looking figure that includes authorized-but-not-yet-captured orders and therefore gates new authorizations conservatively. Its `settled_credit_cents` is the sum of `total_cents` across only those work orders whose `payment_status` is `PAID` — the money actually captured. Both are recomputed whenever a work order on the account authorizes, captures, voids, or cancels. The forward-looking reserved figure is what the authorize step checks against the credit limit; the settled figure is the billing view and governs whether an account may be closed.

## 3. Business Logic & Workflows

### 3.1. Configuring the Shop and Its Catalog

A `ShopManager` stands up a location by creating a `Shop` with a `name`, a `tax_rate` expressed as a decimal fraction (for example 0.0825) that is at least zero and strictly below one, and a `target_throughput_seconds` giving the wall-clock duration a work order is expected to take from the moment service starts to the moment it is marked ready, which must be greater than zero. The manager may also supply `max_discount_pct`, the hard ceiling on the combined coupon-and-fleet discount as a fraction of the subtotal; it must be greater than zero and at most one, and when omitted it defaults to one half. A new shop opens with `status` `OPEN` and an `open_bay_count` of zero, since no bays exist yet.

The service menu is built from service packages. A `ShopManager` creates a `ServicePackage` against a shop by supplying `shop_id`, an `oil_grade` of `CONVENTIONAL`, `SYNTHETIC_BLEND`, `FULL_SYNTHETIC`, or `HIGH_MILEAGE`, a display `name`, a `base_price_cents` that is at least zero, an `included_quarts` count greater than zero, a `labor_minutes` figure greater than zero, an `interval_miles` greater than zero, and an `interval_days` greater than zero. At creation the server derives `requires_synthetic_certified_bay` from the grade as described in §2.10 and sets `active` to true. A package can later be retired, which sets `active` to false but leaves it on record. The recommended mileage interval and day interval are what later drive a serviced vehicle's reminder projection.

Upsell offerings live in inspection items. A `ShopManager` creates an `InspectionItem` with `shop_id`, a `code` drawn from `AIR_FILTER`, `CABIN_FILTER`, `WIPER_BLADES`, `COOLANT_FLUSH`, or `TRANSMISSION_FLUSH`, a display `name`, a `price_cents` of at least zero, and a `labor_minutes` figure of at least zero giving the extra labor the item adds. A new inspection item is `active` true.

Coupons are configured per shop. A `ShopManager` creates a `Coupon` with `shop_id`, a case-sensitive `code` that is unique among that shop's currently active coupons — a creation whose `code` collides with an already-`ACTIVE` coupon of the same shop is rejected with `ERR_VALIDATION` (HTTP 400) — a `discount_type` of `PERCENT` or `FLAT`, and a `usage_limit` greater than zero capping how many work orders may ever redeem it. For a percentage coupon the manager supplies `percent_value`, a fraction that is at least zero and strictly below one (defaulting to zero, and ignored for flat coupons); for a flat coupon the manager supplies `flat_cents`, a non-negative cents-off amount (defaulting to zero, and ignored for percentage coupons). An optional `min_subtotal_cents` (default zero) sets the minimum work-order subtotal at which the coupon becomes eligible, applied as an at-least threshold. An optional `stackable_with_fleet` flag (default false) decides whether this coupon's discount adds to a fleet discount or merely competes with it, as the pricing rules in §3.6 detail. A new coupon starts with `status` `ACTIVE` and a `redeemed_count` of zero; `redeemed_count` is the live count of work orders whose `coupon_code` equals this coupon's `code` and whose `payment_status` is `PAID`. A manager may explicitly expire a coupon, moving its `status` to `EXPIRED`. Separately, the system itself moves a coupon to `EXHAUSTED` once its redemptions reach the limit, as the capture workflow describes.

A `ShopManager` opens a corporate account by creating a `FleetAccount` with `shop_id`, a `company_name`, a `discount_pct` fraction that is at least zero and strictly below one, and a `credit_limit_cents` of at least zero. A new account is `ACTIVE` with both `reserved_credit_cents` and `settled_credit_cents` at zero.

Bays and technicians complete the shop's physical roster. A `ShopManager` creates a `Bay` with `shop_id`, a `label`, and an optional `synthetic_certified` flag (default false); the bay opens and the shop's open-bay count rises by one. A `ShopManager` creates a `Technician` with `shop_id`, a `full_name`, an optional `synthetic_certified` flag (default false), and an optional `cleanup_buffer_seconds` (default 300) giving the mandatory gap the system enforces between that technician's consecutive jobs. A new technician is `active` true.

### 3.2. Registering Vehicles and Reading the Reminder

Vehicles are registered by a `ShopManager`, a `ServiceAdvisor`, or a `FleetManager`. Registration supplies `shop_id`, a `vin` that must be unique among the vehicles of the same shop, a `plate`, a `make`, a `model`, and an `odometer` reading of at least zero. A `fleet_account_id` may be supplied to bind the vehicle to a corporate account, or omitted (defaulting to null) for a retail walk-in. A duplicate VIN within the same shop is rejected with `ERR_DUPLICATE_VIN` (HTTP 409). A `FleetManager` registering a vehicle may only attach it to its own `fleet_account_id`.

A freshly registered vehicle has no service history: `last_service_odometer`, `last_service_date`, `next_service_odometer`, and `next_service_date` are all null, and `service_due` is false. These reminder fields stay null until the vehicle's first work order completes. From then on, `last_service_odometer` is the `odometer_in` recorded at the most recent completed order, `last_service_date` is that order's creation timestamp, `next_service_odometer` is the last-service odometer plus the completed order's package `interval_miles`, and `next_service_date` is the last-service date plus that package's `interval_days`. The vehicle's `service_due` flag becomes true once the vehicle's current `odometer` is at least its `next_service_odometer`, or the clock has reached its `next_service_date`, whichever of the two limits arrives first; with no service history it stays false.

### 3.3. The Drive-In Queue

A `ServiceAdvisor` enqueues an arriving vehicle by creating a `QueueTicket` with `shop_id`, `vehicle_id`, and the `requested_package_id` the customer asked for at intake. The new ticket is `WAITING` and is stamped with a `queue_seq`, a monotonic intake number assigned per shop at creation; lower `queue_seq` means earlier arrival, and this sequence — not the ticket's `id` — is the FIFO ordering key. The queue listing is returned ordered by `queue_seq` ascending. While a ticket waits, its `assigned_bay_id` and `work_order_id` are null.

When a bay is open, a `ServiceAdvisor` assigns a waiting ticket to it. The assignment request carries the target `bay_id` and the `expected_bay_version` described in §2.8. The target bay must be `OPEN`, or the request is rejected with `ERR_BAY_NOT_OPEN`; the bay must also belong to the same shop as the ticket, and a cross-shop bay is likewise rejected with `ERR_BAY_NOT_OPEN`; and the echoed version must match the bay's current `version`, failing which the request is rejected with `ERR_STALE_BAY_VERSION`. A successful assignment advances the ticket from `WAITING` to `ASSIGNED`, moves the bay from `OPEN` to `OCCUPIED` while setting its `current_work_order_id` and lowering the shop's open-bay count by one and bumping the bay's `version`, and creates a fresh `WorkOrder` in service status `DRAFT` and payment status `UNPAID`. That new order takes the assigned bay as its `bay_id`, the ticket's `requested_package_id` as its `package_id`, and the vehicle's current `odometer` as its `odometer_in`; the ticket's `work_order_id` and `assigned_bay_id` are set to the new order and bay.

A `ServiceAdvisor` may return an assigned ticket to the queue. Requeuing is permitted only while the ticket is `ASSIGNED` and its associated work order is still `DRAFT`; once service has started, the ticket can no longer be requeued, and either violation is rejected with `ERR_INVALID_STATE`. Requeuing cancels the draft work order — which releases its bay from `OCCUPIED` back to `OPEN` and raises the open-bay count by one — clears the ticket's `assigned_bay_id` and `work_order_id`, and returns the ticket to `WAITING`, from which it may be assigned again later.

A `ServiceAdvisor` may cancel a still-waiting ticket, moving it from `WAITING` to `CANCELLED`; cancelling anything other than a waiting ticket is rejected with `ERR_INVALID_STATE`. A ticket's status also advances automatically as its work order progresses: when the linked order starts service it moves from `ASSIGNED` to `IN_BAY`, and when that order completes it moves from `IN_BAY` to `DONE`. Both `DONE` and `CANCELLED` are terminal for a ticket.

### 3.4. Opening Work Orders and Claiming the Job

Besides the queue path, a `ServiceAdvisor` may open a `WorkOrder` directly against an already-open bay. Direct creation supplies `shop_id`, `vehicle_id`, `bay_id`, `package_id`, the `odometer_in` reading taken at check-in (at least zero), and optionally a `coupon_code`. The bay must be `OPEN`; creating against it occupies it, sets its `current_work_order_id`, and lowers the open-bay count by one. The order is born `DRAFT` and `UNPAID` with its `package_price_cents` snapshotted from the selected package's `base_price_cents`, and its provisional pricing is computed immediately. A direct order has a null `queue_ticket_id`, whereas an order born from the queue records the originating ticket there.

A new work order's occupancy must not collide on the bay. Conceptually, bay occupancy intervals are treated as half-open windows of the form start-inclusive to end-exclusive. In practice this collision is enforced through the `OPEN`-bay requirement above: because a bay holds at most one live occupancy at a time, any attempt to create an order against a bay already occupied by a live order surfaces as `ERR_BAY_NOT_OPEN` (the bay is not `OPEN`), and the dedicated `ERR_BAY_TIME_OVERLAP` code is reserved for this overlap condition but is not produced by any current creation path.

A `Technician` takes ownership of an order by claiming it, supplying the `technician_id` to record on the order. The named technician must exist, or the claim fails with `ERR_TECHNICIAN_NOT_FOUND`. Claiming also enforces that the technician is not double-booked: a technician's job intervals, each extended by that technician's `cleanup_buffer_seconds`, must not overlap one another, and concretely this is enforced as a concurrency check — a claim is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED` whenever the technician already holds any other non-terminal order (one whose `service_status` is not `COMPLETED` or `CANCELLED`), regardless of bay or elapsed time. Until an order is claimed its `technician_id` is null.

### 3.5. Applying and Replacing Coupons

A `ServiceAdvisor` may apply or replace the coupon on an order — typically a draft one — supplying the `coupon_code`; doing so records the code on the order and recomputes its provisional pricing. No service-status check gates this operation: the request is accepted regardless of the order's current `service_status` so long as the coupon resolves and is eligible. The code must resolve to a coupon on the same shop, or the request is rejected with `ERR_COUPON_NOT_FOUND`. The coupon must currently be eligible, and three conditions are checked: its `status` must be `ACTIVE`, or the request is rejected with `ERR_COUPON_EXPIRED` (which also covers an exhausted coupon); its `redeemed_count` must be strictly below its `usage_limit`, or the request is rejected with `ERR_COUPON_USAGE_EXCEEDED`; and the order's `subtotal_cents` must be at least the coupon's `min_subtotal_cents`, or the request is rejected with `ERR_COUPON_MIN_SUBTOTAL_NOT_MET`.

### 3.6. How a Work Order Is Priced

A work order's price is rebuilt from scratch — never patched incrementally — every time its inputs change: at creation, when a line is added or removed, when an inspection cycle finishes, when the order is marked ready, when a coupon is applied, and when a governing fleet account is suspended or reactivated. All amounts are integer cents and the steps run strictly in the following order.

First the base. The `package_price_cents` is the snapshot taken at creation. The `lines_total_cents` is the sum of `price_cents` over this order's non-voided lines. The `subtotal_cents` is `package_price_cents` plus `lines_total_cents`.

Next the coupon component, recorded as `coupon_discount_cents`. If the order has no coupon, or the coupon's status is not `ACTIVE`, or the `subtotal_cents` is below the coupon's `min_subtotal_cents`, the coupon component is zero. Otherwise, for a percentage coupon the discount is computed per line and then summed — treating the package itself as one line — so that the component equals the package price multiplied by the coupon's `percent_value` and rounded half-up, plus, for each non-voided line, that line's `price_cents` multiplied by `percent_value` and rounded half-up, all those per-line rounded figures added together. This per-line-then-sum order is deliberate and is not the same as rounding one product of subtotal times percent. For a flat coupon the component is the smaller of the coupon's `flat_cents` and the `subtotal_cents`.

Then the fleet component, recorded as `fleet_discount_cents`. If the vehicle has no fleet account, or that account's status is not `ACTIVE`, the fleet component is zero. Otherwise it is the `subtotal_cents` multiplied by the account's `discount_pct`, rounded half-up.

The two components are then combined under the stacking rule into a raw discount. If a coupon is present and its `stackable_with_fleet` flag is true, the raw discount is the coupon component plus the fleet component. Otherwise the raw discount is the larger of the two components. A cap is computed as the floor of `subtotal_cents` multiplied by the shop's `max_discount_pct`. The `total_discount_cents` recorded on the order is the smaller of the raw discount and that cap.

Finally the tax and total. The taxable base is `subtotal_cents` minus `total_discount_cents`. The `tax_cents` is that taxable base multiplied by the shop's `tax_rate`, rounded half-up. The `total_cents` is the taxable base plus `tax_cents`.

This same computation yields two variants over the same formula. While the order is `DRAFT`, `IN_SERVICE`, or `INSPECTION`, the result is provisional — a customer-facing quote that reflects only the lines present so far and is recomputed on every line add or remove and on finishing an inspection. The final variant is computed once, when the order is marked ready, over the complete set of upsells accepted during inspection; it is frozen at that point and may exceed the earlier provisional quote because it reflects more lines, but it uses the identical formula.

### 3.7. Performing the Service: the Inspection Cycle and Throughput

A `Technician` starts service on a claimed order, advancing it from `DRAFT` to `IN_SERVICE`. Starting requires that the order's bay is `OCCUPIED` by this very order, failing which the request is rejected with `ERR_BAY_NOT_READY`; that the order has been claimed, i.e. its `technician_id` is set, failing which it is rejected with `ERR_TECHNICIAN_NOT_ASSIGNED`; and, when the order's package requires synthetic certification, that the bay is `synthetic_certified`, failing which it is rejected with `ERR_BAY_CAPABILITY_MISMATCH`, and that the technician is `synthetic_certified`, failing which it is rejected with `ERR_TECHNICIAN_CAPABILITY_MISMATCH`. On a successful start, `service_start_at` is stamped with the current clock, which begins the throughput measurement, and if the order arose from a queue ticket that ticket advances from `ASSIGNED` to `IN_BAY`.

The upsell loop runs through the inspection states. A `Technician` begins an inspection, advancing the order from `IN_SERVICE` to `INSPECTION`; this transition requires the order to actually be `IN_SERVICE`, else `ERR_INVALID_STATE`. During inspection the technician adds upsell lines and may remove them, then finishes the inspection, advancing back from `INSPECTION` to `IN_SERVICE` and recomputing the provisional pricing to reflect whatever lines were added or removed; finishing requires the order to be `INSPECTION`, else `ERR_INVALID_STATE`. The cycle `IN_SERVICE` → `INSPECTION` → `IN_SERVICE` may repeat, giving the technician a revision loop over the upsell set.

Adding a line is performed by a `Technician`, who supplies the `inspection_item_id` of the item to upsell and the `expected_work_order_version` for the concurrency check of §2.8. The referenced inspection item must exist, or the request is rejected with `ERR_INSPECTION_ITEM_NOT_FOUND`. A new `WorkOrderLine` snapshots the item: its `code`, `price_cents`, and `labor_minutes` are copied from the inspection item at the moment of add, its parent `work_order_id` is recorded, and the source `inspection_item_id` is retained as the reference it was created from. The line is born with `voided` false. Adding a line recomputes the order's pricing and bumps the order's `version`. Removing a line is also performed by a `Technician` during inspection; the targeted line must exist on the order, else `ERR_LINE_NOT_FOUND`, and removal recomputes the order's pricing.

A `Technician` marks the order ready, advancing it from `IN_SERVICE` to `READY`; this requires the order to be `IN_SERVICE`, else `ERR_INVALID_STATE`. Marking ready computes the final pricing variant and freezes it, stamps `service_ready_at` with the current clock, and computes the throughput figures. The `throughput_seconds` is the whole-second difference obtained by taking the floor of the elapsed time from `service_start_at` to `service_ready_at`. The `throughput_breach` flag is true exactly when `throughput_seconds` is strictly greater than the shop's `target_throughput_seconds`; equalling the target is not a breach. Both `throughput_seconds` and `throughput_breach` are null until the order reaches `READY`.

### 3.8. Settling Payment

Once an order's total is meaningful, a `ServiceAdvisor` authorizes payment, advancing the order's payment dimension from `UNPAID` to `AUTHORIZED`. Authorization is permitted only while the service status is `INSPECTION` or `READY`, else `ERR_INVALID_STATE`. The request supplies a `payment_method` of `CARD`, `CASH`, or `FLEET_ACCOUNT`; an absent or unrecognized method is an `ERR_VALIDATION`. When the method is `FLEET_ACCOUNT`, the vehicle must be bound to a fleet account — its `fleet_account_id` must be set, else `ERR_VEHICLE_HAS_NO_FLEET_ACCOUNT` — and that account must be `ACTIVE`, else `ERR_FLEET_ACCOUNT_INACTIVE`. A fleet authorization is also held to the credit limit: the account's `reserved_credit_cents` plus this order's `total_cents` must be at most the account's `credit_limit_cents`, and an authorization that would exceed it is rejected with `ERR_FLEET_CREDIT_EXCEEDED` (HTTP 402). A successful authorization creates a `Payment` whose `method` snapshots the order's `payment_method`, whose `amount_cents` snapshots the order's `total_cents`, and whose `status` is `AUTHORIZED`; for a fleet payment the account's `reserved_credit_cents` is recomputed to include this order.

A `ServiceAdvisor` then captures the payment, advancing it from `AUTHORIZED` to `PAID`; capture requires the payment to be `AUTHORIZED` and the service status to be `READY`, and a violation of either is rejected with `ERR_INVALID_STATE`. Capture moves the `Payment` from `AUTHORIZED` to `CAPTURED`. If the order carried a coupon, that coupon's `redeemed_count` is recomputed, and if the recomputed count reaches or exceeds the coupon's `usage_limit` the coupon's `status` moves to `EXHAUSTED`. For a fleet payment the account's `settled_credit_cents` is recomputed to include the now-paid order.

A `ServiceAdvisor` may instead void an authorized payment, advancing it from `AUTHORIZED` to `VOIDED`; this requires the payment to be `AUTHORIZED`, else `ERR_INVALID_STATE`. Voiding moves the `Payment` from `AUTHORIZED` to `VOIDED` and, because the order no longer counts as committed, recomputes the fleet account's `reserved_credit_cents` to release the reservation. Both `PAID` and `VOIDED` are terminal for the payment dimension.

### 3.9. Completion and the Freed-Bay Cascade

A `ServiceAdvisor` completes a ready order, advancing its service status from `READY` to `COMPLETED`. Completion requires the order to be `READY`, else `ERR_INVALID_STATE`, and the payment to have settled — its `payment_status` must be `PAID`, else `ERR_PAYMENT_NOT_SETTLED`. Completion sets in motion a chain of consequences.

The bay is freed: it moves from `OCCUPIED` to `OPEN`, its `current_work_order_id` is cleared, and the shop's `open_bay_count` rises by one. That freed bay immediately triggers a promotion: the waiting ticket with the lowest `queue_seq` at this shop, if any exists, is pulled forward — it advances from `WAITING` to `ASSIGNED`, its `assigned_bay_id` is set to the freed bay, a new `DRAFT` work order is created for it, and the bay is occupied again, which lowers the open-bay count by one. The net effect on the open-bay count is therefore unchanged when a ticket was waiting to take the bay, and a rise of one when the queue was empty.

Completion also prints the reminder record. A `ServiceSticker` is created for the order, and the vehicle's reminder fields — `last_service_odometer`, `last_service_date`, `next_service_odometer`, `next_service_date`, and `service_due` — are recomputed from this newly completed order as described in §3.2 and §3.10. Finally, if the order originated from a queue ticket, that ticket advances from `IN_BAY` to `DONE`.

A `ServiceAdvisor` may cancel a non-terminal order — one whose service status is `DRAFT`, `IN_SERVICE`, or `INSPECTION`. An order that is already `READY`, `COMPLETED`, or `CANCELLED` cannot be cancelled and the attempt is rejected with `ERR_INVALID_STATE`. Cancellation voids the order's lines: every `WorkOrderLine` on the order has its `voided` flag set to true and the `lines_total_cents` is recomputed to zero. If the order's payment was `AUTHORIZED`, the compensating path runs: the `Payment` moves from `AUTHORIZED` to `VOIDED`, the order's `payment_status` becomes `VOIDED`, and the fleet account's `reserved_credit_cents` is released. The bay is freed from `OCCUPIED` to `OPEN` with its `current_work_order_id` cleared and the open-bay count raised by one. If the order was linked to a queue ticket, that ticket moves to `CANCELLED`.

### 3.10. Projecting the Next Service

When an order completes, the system computes the next-service projection that drives both the printed sticker and the vehicle's reminder. The `service_odometer` on the sticker is the order's `odometer_in`. The sticker's `next_service_odometer` is that service odometer plus the package's `interval_miles`. The sticker's `next_service_date` is the completion clock instant advanced by the package's `interval_days` days and rendered as a full ISO 8601 UTC timestamp (the time-of-day component of the completion instant is preserved, not truncated to midnight). The sticker also records `vehicle_id` and `work_order_id` snapshots so the printed record stands on its own.

The sticker further records a `basis` indicating which limit is projected to arrive first — `MILEAGE` or `TIME` — so the shop knows which reminder to watch. The system estimates how many days it would take to reach the mileage limit by dividing the package's `interval_miles` by an assumed daily driving distance of 40 miles and rounding that quotient up to a whole number of days. If that projected number of days to hit the mileage limit is at most the package's `interval_days`, the basis is `MILEAGE`; otherwise the basis is `TIME`.

The same completion event updates the vehicle's own reminder fields against its most recent completed order, which is exactly what makes the vehicle's `service_due` flag meaningful: the flag turns true once the vehicle's current odometer reaches or passes the projected next-service odometer, or the clock reaches the projected next-service date, whichever comes first.

### 3.11. Managing Bays and Fleet Accounts Over Time

A `ShopManager` may take a bay out of service. Closing a bay moves it from `OPEN` to `CLOSED` and lowers the shop's open-bay count by one; an occupied bay cannot be closed, and the attempt is rejected with `ERR_BAY_OCCUPIED`. Reopening moves a bay from `CLOSED` back to `OPEN` and raises the count by one; reopening anything not currently closed is rejected with `ERR_INVALID_STATE`.

Fleet accounts have their own lifecycle, and suspending one ripples into pricing. A `ShopManager` suspends an active account, moving it from `ACTIVE` to `SUSPENDED`; the account must be `ACTIVE`, else `ERR_INVALID_STATE`. Because a suspended account no longer grants its discount, every still-`DRAFT` work order belonging to a vehicle on that account is re-priced with the fleet component now zero, recomputing all of that order's discount and total fields; the re-price runs over every such draft order unconditionally (it is not narrowed to those that currently carry a non-zero fleet discount), and each re-priced order independently has its `version` bumped and `updated_at` refreshed. Reactivating moves the account from `SUSPENDED` back to `ACTIVE` — requiring it to be `SUSPENDED`, else `ERR_INVALID_STATE` — and re-prices those vehicles' draft work orders with the fleet discount restored, again over every such draft order unconditionally. Closing an account moves it to `CLOSED`, which is terminal; closure is permitted only when the account's `reserved_credit_cents` is zero, meaning no authorized or paid order is outstanding, and otherwise is rejected with `ERR_FLEET_HAS_OPEN_BALANCE`. The close operation enforces only this open-balance guard — it does not separately validate the account's current status, so an account already `CLOSED` (whose `reserved_credit_cents` is necessarily zero) may be closed again.

### 3.12. Reads, Reverse Lookups, and the Test-Driving Clock

Resources are readable individually and as filtered lists. Shops, service packages, inspection items, coupons, fleet accounts, vehicles, bays, technicians, queue tickets, and work orders each support a single-resource read and a list read; the various list reads accept domain filters such as `shop_id`, `oil_grade`, `status`, `code`, `fleet_account_id`, `vin`, `plate`, `vehicle_id`, `requested_package_id`, `bay_id`, `package_id`, `technician_id`, `service_status`, and `payment_status` as appropriate to the resource, alongside the standard `limit` and `offset`. Several reverse-lookup reads walk a foreign key backward: a fleet account's vehicles, a vehicle's work orders, a work order's lines, a work order's payments, and a work order's sticker. The sticker read is shaped as a paginated list endpoint (`response_type` `"array"`, carrying the standard `limit`/`offset`/`total_count`/`has_more` pagination meta) whose `data` array holds the order's sticker(s) — at most one; it returns `ERR_STICKER_NOT_FOUND` when the caller requests the sticker for an order that has not yet completed and therefore has none. A `FleetManager`'s reads are confined to its own account's data per §2.1.

For deterministic testing of throughput timing and the time-based reminder, a `ShopManager` may drive the logical clock. This administrative capability sets the server's notion of "now" to a supplied UTC instant given as `to_iso8601`, and every subsequently computed timestamp — service start and ready stamps, completion dates, and due-date comparisons — is evaluated against that fixed instant.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including the lifecycle transitions, coupon application, payment steps, and line removal — return `200 OK`. The one transition that produces a brand-new resource, adding an upsell line to a work order, returns `201 Created`. The complete request bodies, side effects, and validation rules for each endpoint are described in the workflow narratives of §3; the table below is only an index of method, path, purpose, and the roles permitted to call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shops` | Create a shop | ShopManager |
| GET | `/shops` | List shops | ShopManager, ServiceAdvisor, Technician, FleetManager |
| GET | `/shops/{id}` | Get a shop (live open-bay count) | ShopManager, ServiceAdvisor, Technician, FleetManager |
| POST | `/service-packages` | Create a service package | ShopManager |
| GET | `/service-packages` | List/look up packages | ShopManager, ServiceAdvisor, Technician, FleetManager |
| GET | `/service-packages/{id}` | Get a package | ShopManager, ServiceAdvisor, Technician, FleetManager |
| POST | `/service-packages/{id}/retire` | Retire a package | ShopManager |
| POST | `/inspection-items` | Create an upsell inspection item | ShopManager |
| GET | `/inspection-items` | List inspection items | ShopManager, ServiceAdvisor, Technician, FleetManager |
| GET | `/inspection-items/{id}` | Get an inspection item | ShopManager, ServiceAdvisor, Technician, FleetManager |
| POST | `/coupons` | Create a coupon | ShopManager |
| GET | `/coupons` | List coupons | ShopManager, ServiceAdvisor |
| GET | `/coupons/{id}` | Get a coupon (live redeemed count) | ShopManager, ServiceAdvisor |
| POST | `/coupons/{id}/expire` | Expire a coupon | ShopManager |
| POST | `/fleet-accounts` | Create a fleet account | ShopManager |
| GET | `/fleet-accounts` | List fleet accounts | ShopManager, FleetManager |
| GET | `/fleet-accounts/{id}` | Get a fleet account (live reserved/settled credit) | ShopManager, FleetManager |
| GET | `/fleet-accounts/{id}/vehicles` | List a fleet account's vehicles | ShopManager, FleetManager |
| POST | `/fleet-accounts/{id}/suspend` | Suspend a fleet account | ShopManager |
| POST | `/fleet-accounts/{id}/reactivate` | Reactivate a fleet account | ShopManager |
| POST | `/fleet-accounts/{id}/close` | Close a fleet account | ShopManager |
| POST | `/vehicles` | Register a vehicle | ShopManager, ServiceAdvisor, FleetManager |
| GET | `/vehicles` | Look up vehicles | ShopManager, ServiceAdvisor, Technician, FleetManager |
| GET | `/vehicles/{id}` | Get a vehicle with reminder fields | ShopManager, ServiceAdvisor, Technician, FleetManager |
| GET | `/vehicles/{id}/work-orders` | List a vehicle's work orders | ShopManager, ServiceAdvisor, Technician, FleetManager |
| POST | `/bays` | Create a bay | ShopManager |
| GET | `/bays` | List bays | ShopManager, ServiceAdvisor, Technician |
| GET | `/bays/{id}` | Get a bay | ShopManager, ServiceAdvisor, Technician |
| POST | `/bays/{id}/close` | Close an open bay | ShopManager |
| POST | `/bays/{id}/reopen` | Reopen a closed bay | ShopManager |
| POST | `/technicians` | Create a technician | ShopManager |
| GET | `/technicians` | List technicians | ShopManager, ServiceAdvisor, Technician |
| GET | `/technicians/{id}` | Get a technician | ShopManager, ServiceAdvisor, Technician |
| POST | `/queue-tickets` | Drive-in: enqueue a vehicle | ServiceAdvisor |
| GET | `/queue-tickets` | List the queue (ordered by intake sequence) | ShopManager, ServiceAdvisor, Technician |
| GET | `/queue-tickets/{id}` | Get a queue ticket | ShopManager, ServiceAdvisor, Technician |
| POST | `/queue-tickets/{id}/assign` | Assign a waiting ticket to an open bay | ServiceAdvisor |
| POST | `/queue-tickets/{id}/requeue` | Return an assigned ticket to waiting | ServiceAdvisor |
| POST | `/queue-tickets/{id}/cancel` | Cancel a waiting ticket | ServiceAdvisor |
| POST | `/work-orders` | Create a work order directly | ServiceAdvisor |
| GET | `/work-orders` | List work orders | ShopManager, ServiceAdvisor, Technician, FleetManager |
| GET | `/work-orders/{id}` | Get a work order | ShopManager, ServiceAdvisor, Technician, FleetManager |
| POST | `/work-orders/{id}/claim` | Technician claims the order | Technician |
| POST | `/work-orders/{id}/apply-coupon` | Apply or replace the coupon on a draft order | ServiceAdvisor |
| POST | `/work-orders/{id}/lines` | Add an upsell inspection line | Technician |
| GET | `/work-orders/{id}/lines` | List a work order's lines | ShopManager, ServiceAdvisor, Technician, FleetManager |
| DELETE | `/work-orders/{id}/lines/{lineId}` | Remove an upsell line during inspection | Technician |
| POST | `/work-orders/{id}/start` | Start service (DRAFT to IN_SERVICE) | Technician |
| POST | `/work-orders/{id}/begin-inspection` | Begin inspection (IN_SERVICE to INSPECTION) | Technician |
| POST | `/work-orders/{id}/finish-inspection` | Finish inspection (INSPECTION to IN_SERVICE) | Technician |
| POST | `/work-orders/{id}/mark-ready` | Mark ready (IN_SERVICE to READY; final pricing) | Technician |
| POST | `/work-orders/{id}/authorize` | Authorize payment (UNPAID to AUTHORIZED) | ServiceAdvisor |
| POST | `/work-orders/{id}/capture-payment` | Capture payment (AUTHORIZED to PAID) | ServiceAdvisor |
| POST | `/work-orders/{id}/void-payment` | Void payment (AUTHORIZED to VOIDED) | ServiceAdvisor |
| POST | `/work-orders/{id}/complete` | Complete the order (READY to COMPLETED; cascade) | ServiceAdvisor |
| POST | `/work-orders/{id}/cancel` | Cancel a non-terminal order | ServiceAdvisor |
| GET | `/work-orders/{id}/sticker` | Get the service sticker for an order | ShopManager, ServiceAdvisor, Technician, FleetManager |
| GET | `/work-orders/{id}/payments` | List payments for a work order | ShopManager, ServiceAdvisor, FleetManager |
| POST | `/_clock/set` | Test-driving: set the server clock | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_SHOP_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_COUPON_NOT_FOUND` | 404 Not Found |
| `ERR_FLEET_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_BAY_NOT_FOUND` | 404 Not Found |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_QUEUE_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_STICKER_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_HAS_NO_FLEET_ACCOUNT` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_BAY_NOT_OPEN` | 409 Conflict |
| `ERR_BAY_OCCUPIED` | 409 Conflict |
| `ERR_BAY_NOT_READY` | 409 Conflict |
| `ERR_TECHNICIAN_NOT_ASSIGNED` | 409 Conflict |
| `ERR_PAYMENT_NOT_SETTLED` | 409 Conflict |
| `ERR_FLEET_ACCOUNT_INACTIVE` | 409 Conflict |
| `ERR_FLEET_HAS_OPEN_BALANCE` | 409 Conflict |
| `ERR_STALE_BAY_VERSION` | 412 Precondition Failed |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_BAY_CAPABILITY_MISMATCH` | 409 Conflict |
| `ERR_TECHNICIAN_CAPABILITY_MISMATCH` | 409 Conflict |
| `ERR_BAY_TIME_OVERLAP` | 409 Conflict |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_COUPON_EXPIRED` | 409 Conflict |
| `ERR_COUPON_USAGE_EXCEEDED` | 409 Conflict |
| `ERR_COUPON_MIN_SUBTOTAL_NOT_MET` | 409 Conflict |
| `ERR_DUPLICATE_VIN` | 409 Conflict |
| `ERR_FLEET_CREDIT_EXCEEDED` | 402 Payment Required |
