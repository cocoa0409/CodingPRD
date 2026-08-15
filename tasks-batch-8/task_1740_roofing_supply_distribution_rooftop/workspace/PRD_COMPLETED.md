# Roofing Supply Distribution API — Product Requirements Document

## 1. Introduction

Wholesale roofing supply is a business of tight logistics and exposed credit. A branch network stocks shingle bundles by manufacturer lot, contractors estimate roofs in squares and expect material lifted to the rooftop on a scheduled conveyor or crane, and nearly every sale rides on a job-account credit line that the distributor must police through invoicing, payments, and — when balances sour — lien notices. A hailstorm can triple a branch's demand overnight, forcing hard decisions about which contractors receive scarce bundles and at what surge price.

This document specifies the Roofing Supply Distribution API, mounted under `/roofing`, which governs that full cycle: material takeoff estimation with waste factors, contractor-tier order pricing with storm surge premiums, slot-based rooftop delivery scheduling with equipment fees, storm-surge allocation waterfalls, contractor credit ledgering with a lien lifecycle, returns of opened bundles under color/lot matching, delivery damage claims under segregation of duties, and manufacturer warranty registration. It is written for the engineers who will implement the service; every rule stated here is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Eight roles are recognized, spelled exactly as follows: `PlatformAdmin`, `BranchManager`, `SalesRep`, `Dispatcher`, `Contractor`, `CreditAnalyst`, `ClaimsAdjuster`, and `WarehouseClerk`. Each endpoint admits a fixed set of roles (§4); a caller whose role is not admitted, or a `Contractor` attempting to act on another contractor's resources, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity works as follows. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting ContractorAccount; ownership checks on any resource that references a ContractorAccount compare the resource's foreign-key field to `X-User-ID` — for example the `contractor_account_id` carried by a JobAccount or an Allocation, or the account reached through an order's `job_account_id`. When `X-User-Role` is any of `PlatformAdmin`, `BranchManager`, `SalesRep`, `Dispatcher`, `CreditAnalyst`, `ClaimsAdjuster`, or `WarehouseClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server may record it (for example, to remember which adjuster approved a damage claim so that segregation of duties can be enforced at crediting time) but does not compare it to any entity's `id`. Every list endpoint additionally scopes a `Contractor` caller's view to records owned by that contractor's account (resolved through the same foreign-key chains used for ownership checks); resource types with no contractor owner — branches, products, inventory lots, delivery slots, and surge events — therefore list empty for a `Contractor`, while single-resource retrieval of those types remains open to any admitted role.

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

Malformed request bodies and field-level validation failures — a missing required field, a value outside its permitted range or enumeration, a non-integer pagination parameter, an unparseable timestamp — are rejected with the catch-all identifier `ERR_INVALID_REQUEST` (HTTP 400), and requests to unmapped paths or unsupported methods surface `ERR_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 and is clamped into the range 1 to 100, so a value below 1 becomes 1 and a value above 100 becomes 100. The `offset` parameter skips a number of items from the front of the result set: it defaults to 0, and a negative value is clamped up to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order; ties in `created_at` — common under the logical clock, which moves only in discrete steps — are broken by insertion order, here and wherever else this document orders or selects by `created_at`.

Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock

All time-dependent behavior in the system is evaluated against a logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before any explicit set call, the logical clock continues to read that default and never falls back to wall-clock time. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant — an instant earlier than the current reading is rejected with `ERR_INVALID_REQUEST` — and echoes back the resulting `current_utc` rendered at second precision. Every advance re-evaluates all time-dependent system transitions: takeoff expiry, storm-surge activation and automatic close, and the lien cure period are all recomputed against the new instant.

### 2.5. Common Resource Properties

Every resource carries an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was first created. Mutable resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on any change to the resource's properties (at creation it equals `created_at`), and `version`, a system-managed integer that starts at 1 on creation and increments with every mutation. Recomputation of derived figures on a resource — an order's repriced `total_cents`, a surge event's `allocated_bundles`, a lot's `reserved_bundles` — is itself a mutation of that resource: its `updated_at` refreshes and its `version` increments.

One entity breaks this pattern deliberately. A WarrantyRegistration is immutable once created and therefore carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Units, Precision, and Rounding

Money is integer cents throughout the API: prices, fees, credits, balances, holds, and claim amounts are all whole numbers of cents, never floats. Whenever a percentage is applied to a monetary figure — the contractor-tier discount, the storm surge premium, the credit for opened return bundles — the result is rounded half up to whole cents at that step before any subsequent step consumes it.

Bundle counts are whole bundles. Estimation rounds up per product line (a ceiling applied to each line's requirement before any summation across lines), because rounding per line and then summing produces a different — and here normative — answer than summing and then rounding. Storm-surge tier caps are the one place the system rounds half down, since a fractional bundle of quota is meaningless. Roof area is recorded in squares (one square equals 100 square feet) with two-decimal precision, and percentages travel as whole numbers — a `surge_multiplier_pct` of 15 means a fifteen percent uplift, and a `waste_factor_pct` of 10 means ten percent.

### 2.7. Inventory Reservation and Color/Lot Discipline

Each stocked lot at a branch maintains two counters: `on_hand_bundles`, the physical bundles present, and `reserved_bundles`, the bundles committed to confirmed order lines or active surge allocations. The read-only `available_bundles` figure is the on-hand count minus the reserved count, floored at zero so a lot never reports negative availability. Receiving stock raises on-hand; confirming an order raises reserved; dispatching a delivery converts reservation into physical draw by decrementing both; a failed delivery restores both; a received return restocks the unopened bundles.

When several lots at the fulfilling branch can satisfy an order line, the reservation is drawn from the eligible lot with the earliest `created_at`. Color identity and lot identity are deliberately separate: a product's `color_code` expresses the color used for matching, while a lot's `lot_code` is the manufacturer's physical lot identity, and one `color_code` can legitimately span many `lot_code` values. Because blended lots weather differently, returns are verified against the reserved lot before restocking (§3.8).

### 2.8. The Contractor Credit Ledger

A contractor's buying power is tracked as four integer-cent counters on the account: `credit_limit_cents`, the maximum allowed outstanding credit; `open_balance_cents`, the sum of invoiced-but-unpaid order totals; `pending_delivery_hold_cents`, a provisional hold for confirmed-but-not-yet-invoiced order totals; and `lien_hold_cents`, the sum of lien notice amounts over the account's jobs whose lien status is `NOTICE_FILED` or `LIEN_RECORDED`. The read-only `credit_available_cents` is the credit limit minus the open balance, minus the pending delivery hold, minus the lien hold. This figure is allowed to go negative; the guard is applied at the point of commitment, where order confirmation requires the available credit to cover the order's full total.

The ledger is read two ways. At order confirmation time the evaluation is conservative and includes the pending delivery hold, so committed-but-uninvoiced work consumes buying power. The account statement read is the post-delivery position: it reports `open_balance_cents`, `pending_delivery_hold_cents`, and `lien_hold_cents` as they stand, but computes its `credit_available_cents` under the invoiced-only variant, leaving the pending delivery hold out of the subtraction.

### 2.9. Nested Resource Retrieval

Requests that target nested resources are validated strictly left to right along the path. When a path contains several resource identifiers — for example `/roofing/contractor-accounts/{id}/job-accounts` — the server confirms the existence of each identifier in sequence and rejects the request immediately with the 404 error corresponding to the first identifier that does not exist: an unknown contractor account id yields `ERR_ACCOUNT_NOT_FOUND` before any job-account lookup is attempted, and an unknown job account id under a valid account yields `ERR_JOB_ACCOUNT_NOT_FOUND`. The same discipline applies everywhere: a missing branch surfaces `ERR_BRANCH_NOT_FOUND`, a missing product `ERR_PRODUCT_NOT_FOUND`, a missing lot `ERR_LOT_NOT_FOUND`, and so on for every resource type in the catalogue (§5). Creation and action endpoints honor the same ordering, so operations never proceed inside an invalid container.

### 2.10. Optimistic Concurrency Control

Two write operations guard against stale client state with optimistic concurrency control, each keyed to the `version` of a parent entity.

Confirming an order accepts an optional `expected_contractor_account_version`, holding the `version` of the order's ContractorAccount as the client last observed it; when the field is omitted, no version check is performed. If a supplied value does not match the account's current `version` — because, for instance, another confirmed order has legitimately consumed credit and advanced the account version since the client last read it — the confirmation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from committing against a credit position it has not observed.

Granting a surge allocation accepts an optional `expected_storm_surge_event_version`, holding the `version` of the parent StormSurgeEvent as the client last observed it; when the field is omitted, no version check is performed. A supplied value that mismatches the event's current `version` — for instance because an earlier grant has already consumed part of the pool — is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), so no grant is computed from a `remaining_pool_bundles` view the writer has not actually seen.

Endpoints not named in this subsection do not take a version field at all.

### 2.11. Validation Order

Incoming requests are checked against a fixed priority cascade, and a higher-priority failure always surfaces before a lower-priority one is evaluated. First, the presence and non-emptiness of `X-User-ID` and `X-User-Role` is verified (priority 1). Second, the caller's role is checked against the endpoint's RBAC admission set (priority 2). Third, path identifiers are resolved left to right for existence (priority 3). Fourth, the target entity is checked to be in the state the requested transition requires (priority 4) — these rejections carry the state-specific codes of §5 such as `ERR_ORDER_NOT_QUOTED` or `ERR_DELIVERY_NOT_SCHEDULED`. Only then do business rules run, in their own pinned order: segregation of duties on claim crediting (priority 5), returned-lot matching on return receiving (priority 6), installer certification on warranty registration (priority 7), delivery-slot capacity and equipment compatibility (priority 8), the lien cure period on lien recording (priority 9), inventory lot availability on order confirmation (priority 10), surge-allocation limits on order confirmation (priority 11), credit sufficiency (priority 12), and finally the lien-recorded order block (priority 13). A concrete consequence: on order confirmation, an allocation breach surfaces as `ERR_SURGE_ALLOCATION_EXCEEDED` rather than being masked by the credit or lien checks behind it, and on lien recording a wrong-state rejection surfaces before the cure-period arithmetic is ever consulted.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Branch Network and Catalog

Everything begins with the branch. A `PlatformAdmin` registers each branch with a unique `branch_code` (for example `DAL-01`; uniqueness here is a data-entry convention, not a server-enforced rejection), a display `name`, and three capacity facts that shape everything the branch can promise: `rooftop_delivery_capacity_per_day`, the maximum number of rooftop deliveries the branch can perform in a single day; `conveyor_fleet_size`, the number of conveyor trucks, which caps how many conveyor deliveries may run concurrently in any single slot; and `crane_available`, recording whether a crane is on site for crane-fee deliveries. These three facts are recorded for planning and reporting; they are not enforced as scheduling gates — only the slot's own `capacity` and `equipment_type` gate scheduling (§3.5). A new branch starts with `status` set to `ACTIVE` — the only branch status in this version of the system, branch lifecycle being out of scope — and with `surge_mode` set to `NORMAL`, a flag that flips to `SURGE` only while a storm event is active (§3.6).

The product catalog is likewise `PlatformAdmin`-maintained. Each product is created with its manufacturer `sku` (unique across the catalog by the same convention, likewise not enforced by rejection), a `manufacturer_name`, the `color_code` used for lot matching, a `bundles_per_square` factor expressing how many bundles cover one square of roof — typically 3.0 for three-tab shingles and 4.0 for architectural shingles — and a `base_price_per_bundle_cents` list price in cents. Products whose warranty registration demands a manufacturer-certified installer are flagged with `requires_certified_installer`, which defaults to false when omitted. Products also carry a `status` of `ACTIVE`, again the only value in this version.

Stock arrives through the warehouse. A `WarehouseClerk` (or `PlatformAdmin`) receives inventory into a branch lot by supplying the `product_id`, the manufacturer `lot_code`, and the received `on_hand_bundles`; receiving either creates the lot or tops up an existing one — the existing lot being the one at the same branch for the same `product_id` with the same `lot_code` — and a fresh lot always starts with `reserved_bundles` at zero. Referencing a product that does not exist is rejected with `ERR_PRODUCT_NOT_FOUND`, and a missing lot is `ERR_LOT_NOT_FOUND`. Lot ledgers can be browsed per branch or across branches, with optional filters by `product_id` and, on the cross-branch view, `branch_id`.

Delivery capacity is scheduled through slots. A `Dispatcher` (or `PlatformAdmin`) opens a delivery slot at a branch by naming a `slot_date` (an ISO calendar date, stored as given without format validation), a `window` of `AM` or `PM` — two windows per day — an `equipment_type` of `GROUND`, `ROOFTOP_CONVEYOR`, or `CRANE`, and a `capacity` bounding how many deliveries the slot accepts for that equipment type. A slot's `booked_count` starts at zero, rises by one when a delivery is scheduled into it, falls by one only when a delivery in it completes or is cancelled, and shifts from the old slot to the new one on reschedule — so `SCHEDULED` and `EN_ROUTE` deliveries occupy their slot, a `FAILED` delivery continues to occupy its old slot until it is rescheduled, and a `RESCHEDULED` delivery already occupies its new one. Slots can be listed per branch with optional filters on `slot_date` and `equipment_type`; an unknown slot reference is `ERR_SLOT_NOT_FOUND`.

### 3.2. Contractor Credit Accounts and Job Accounts

Before a contractor can buy on terms, a `CreditAnalyst` (or `PlatformAdmin`) opens a contractor account with the legal `company_name`, a `credit_limit_cents` ceiling, an optional `pricing_tier` of `STANDARD`, `PREFERRED`, or `VOLUME` (defaulting to `STANDARD`), and an optional `manufacturer_certifications` list naming the manufacturers this account is certified to install (defaulting to empty). New accounts begin with `status` `ACTIVE` and all three ledger counters — `open_balance_cents`, `pending_delivery_hold_cents`, and `lien_hold_cents` — at zero.

Credit discipline is enforced through the account lifecycle. A `CreditAnalyst` may suspend an account, which requires it to be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`) and moves it to `SUSPENDED`; while an account is `SUSPENDED`, new order confirmations are blocked with `ERR_ACCOUNT_NOT_ACTIVE`. Reinstatement requires the account to be `SUSPENDED` (otherwise `ERR_ACCOUNT_NOT_SUSPENDED`) and is refused with `ERR_CREDIT_LIMIT_EXCEEDED` unless the `open_balance_cents` has fallen strictly below the `credit_limit_cents`. The third status, `LIEN_DEFAULT`, is never set by hand: the system moves an account into `LIEN_DEFAULT` automatically the moment any of its job accounts reaches `LIEN_RECORDED`, and moves it back to `ACTIVE` automatically when the last job account leaves the lien-active states, provided the account still sits in `LIEN_DEFAULT` at that moment (§3.7). Accounts may be listed with an optional `status` filter, and any operation against an unknown account id is `ERR_ACCOUNT_NOT_FOUND`.

Under each account sit its job accounts — one per job site — created by a `CreditAnalyst`, the owning `Contractor`, or a `PlatformAdmin` with just a `job_name` and the delivery `site_address`. A job account opens with `lien_status` `NONE`, a `job_balance_cents` of zero, and no `lien_notice_amount_cents` (zero) or `notice_filed_at` (null). Each job account carries its `contractor_account_id` back to the credit owner, and it is this linkage that makes a contractor's `X-User-ID` meaningful on job-scoped resources. An unknown job account id is `ERR_JOB_ACCOUNT_NOT_FOUND`.

An account statement is available to the `CreditAnalyst`, the owning `Contractor`, and the `PlatformAdmin`; it reports the open balance, pending delivery hold, lien hold, and the invoiced-only reading of available credit described in §2.8.

### 3.3. From Roof Measurement to Quote: The Material Takeoff

A takeoff is the distributor's estimate of what a roof will consume, created under a job account by a `SalesRep` or the `Contractor`. The creator supplies the `product_id` of the primary shingle being estimated, the measured `roof_squares` (two-decimal squares), and a `waste_factor_pct` allowance that must be at least 0 and at most 40; valley and ridge accessory material is captured through `valley_ridge_linear_feet`, which defaults to zero. Every takeoff records the `job_account_id` of the job it belongs to, starts life in `DRAFT`, and unknown takeoff references are `ERR_TAKEOFF_NOT_FOUND`. Takeoffs may be listed per job or across jobs, filtered optionally by `product_id`, `job_account_id`, or `status`.

Creation computes the estimate immediately. The measured area is first scaled by the waste allowance: the adjusted area is `roof_squares` increased by `waste_factor_pct` percent. The shingle requirement is then the adjusted area multiplied by the product's `bundles_per_square`, rounded up to the next whole bundle — this ceiling is applied per product line, before any summation across lines, never after. Accessory bundles are the `valley_ridge_linear_feet` divided by thirty-three linear feet of coverage per accessory bundle, again rounded up to a whole bundle. The read-only `estimated_bundles` is the shingle count plus the accessory count, and the read-only `estimated_amount_cents` prices the shingle bundles at the product's current `base_price_per_bundle_cents` plus 4,200 cents (forty-two dollars) per accessory bundle. While the takeoff remains in `DRAFT` this amount is provisional: it reflects current list prices and is not locked.

Quoting is the `SalesRep`'s commitment device. Moving a takeoff from `DRAFT` to `QUOTED` requires the takeoff to actually be in `DRAFT` (otherwise `ERR_TAKEOFF_NOT_DRAFT`) and requires the contractor account behind the parent job to be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`). At the moment of quoting the estimate is recomputed and frozen: `estimated_bundles` and `estimated_amount_cents` are locked at quote-time prices, and later price changes do not alter them. If measurements change, a `SalesRep` can move the takeoff from `QUOTED` back to `DRAFT` — permitted only from `QUOTED`, otherwise `ERR_TAKEOFF_NOT_QUOTED` — which makes `roof_squares` and `waste_factor_pct` editable again for revision and eventual re-quoting.

Conversion turns paper into an order. The owning `Contractor` converts a `QUOTED` takeoff — any other state draws `ERR_TAKEOFF_NOT_QUOTED` — by naming the fulfilling `branch_id`. Acting on a job account owned by someone else is `ERR_FORBIDDEN`, and conversion is refused with `ERR_CREDIT_LIMIT_EXCEEDED` when the account's `credit_available_cents` does not cover the provisional order total. Conversion creates an Order in `QUOTED` status containing exactly one OrderLine: the line's `product_id` is the takeoff's product and its `quantity_bundles` is the shingle-bundles component of the estimate. Accessory bundles are estimate-only and never become order lines. The order remembers its origin through `takeoff_id` and its billing job through `job_account_id`, and the takeoff itself settles into the terminal `CONVERTED` state.

Takeoffs also age out on the logical clock. A takeoff still sitting in `DRAFT` expires automatically once the clock passes thirty days after its `created_at`, and a `QUOTED` takeoff expires once the clock passes fourteen days after its `updated_at`; both land in the terminal `EXPIRED` state without any side effects.

### 3.4. Order Confirmation, Pricing, and Settlement Gates

An order prices itself from five figures: `subtotal_cents`, `discount_cents`, `delivery_fee_cents`, `surge_premium_cents`, and the resulting `total_cents`, which is the subtotal minus the discount plus the delivery fee plus the surge premium. Alongside `status` (`QUOTED`, `CONFIRMED`, `CLOSED`, `CANCELLED`), an order tracks `fulfillment_status` (`UNFULFILLED`, `PARTIALLY_DELIVERED`, `DELIVERED`, `RETURN_ADJUSTED`) and `payment_status` (`UNPAID`, `INVOICED`, `PAID`, `CREDITED`), both starting at `UNFULFILLED` and `UNPAID` respectively, plus the `storm_surge_event_id` linkage that stays null unless the order consumed surge allocation. Each OrderLine records its `order_id` and `product_id`, the ordered `quantity_bundles`, running `delivered_bundles` and `returned_bundles` counters (both initially zero), an `inventory_lot_id` that stays null until confirmation picks a lot, and the money fields described below. Order lines can be browsed per order or across orders with optional filters by `product_id`, `inventory_lot_id`, or `order_id`, and an unknown order line id is `ERR_ORDER_LINE_NOT_FOUND`; orders themselves list with optional filters on `status`, `job_account_id`, `takeoff_id`, `branch_id`, and `storm_surge_event_id`, and an unknown order id is `ERR_ORDER_NOT_FOUND`.

Confirmation is the pivot of the whole system, performed by the owning `Contractor`. When the request carries `expected_contractor_account_version` per §2.10, a stale credit view is rejected with `ERR_STALE_VERSION` (HTTP 412) before anything else about the account is trusted. The remaining checks run in priority order. The order must be in `QUOTED` (otherwise `ERR_ORDER_NOT_QUOTED`), and a contractor acting on another contractor's order is `ERR_FORBIDDEN`. An account sitting in `SUSPENDED` is rejected next with `ERR_ACCOUNT_NOT_ACTIVE` (§3.2), before lot availability is evaluated. Every order line must find, at the order's branch, an inventory lot holding the same product with `available_bundles` of at least the line's `quantity_bundles`; if any line cannot be satisfied, confirmation fails with `ERR_LOT_UNAVAILABLE`. When the branch's `surge_mode` is `SURGE`, the order auto-links to the branch's single active storm surge event — `storm_surge_event_id` is set — and each line's quantity must not exceed the contractor's unconsumed granted allocation for that product under that event, or confirmation fails with `ERR_SURGE_ALLOCATION_EXCEEDED`. Credit is then checked: `credit_available_cents` must cover the order's `total_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`. Finally, a job account sitting in `LIEN_RECORDED` blocks confirmation outright with `ERR_LIEN_BLOCKS_ORDER`.

A successful confirmation does a great deal at once. For each line the system picks the eligible lot with the earliest `created_at`, writes the choice into `inventory_lot_id`, and increments that lot's `reserved_bundles` by the line quantity. The line's `unit_price_cents` is locked from the product's `base_price_per_bundle_cents` at that moment, and its `extended_price_cents` becomes the quantity times that locked price. Pricing then evaluates in a pinned order, because the discount tier keys on the pre-discount subtotal: first `subtotal_cents` is the sum over lines of each `extended_price_cents`; second, the account's `pricing_tier` selects a discount percent — `STANDARD` pays full price, `PREFERRED` takes five percent, and `VOLUME` takes eight percent, except that `VOLUME` earns its eight percent only when the pre-discount subtotal reaches 250,000 cents ($2,500.00), falling back to the five percent `PREFERRED` rate below that floor; third, `discount_cents` is the subtotal times the selected percent, rounded half up to whole cents; fourth, `surge_premium_cents` is the subtotal times the active event's `surge_multiplier_pct` percent, again rounded half up, when the branch is in `SURGE` mode, and zero in `NORMAL` mode; and finally `total_cents` recomputes. Financially, confirmation adds the full `total_cents` to the account's `pending_delivery_hold_cents` and increments the account's `version` by one — the mutation that makes another client's stale `expected_contractor_account_version` fail. When the order is surge-linked, each line's quantity is drawn against the contractor's live grants for that product in earliest-created order — splitting across grants when a single grant does not cover the line — adding to each affected allocation's `consumed_bundles`, and each affected allocation's status recomputes accordingly (§3.6).

Cancellation comes in two flavors with symmetric care. While the order is still `QUOTED`, the owning `Contractor` may cancel it — from any other state the attempt is `ERR_ORDER_NOT_CANCELLABLE` — and since no holds were ever placed, nothing is released. Once `CONFIRMED`, cancellation becomes a `SalesRep` operation, permitted only when no delivery for the order is `SCHEDULED` or `EN_ROUTE` (an active delivery draws `ERR_ACTIVE_DELIVERY_EXISTS`); cancelling then releases each line's reservation by subtracting its quantity from its lot's `reserved_bundles`, subtracts the `total_cents` from the account's `pending_delivery_hold_cents`, and — when the order was surge-linked — subtracts the line quantities from the allocations' `consumed_bundles`, returning consumption to the contractor's grants for that product in latest-created-first order, and recomputes each affected allocation's status. Cancellation never touches the order's deliveries or slots: cancelling a `QUOTED` order leaves any deliveries already scheduled against it in place (they can never dispatch, since dispatch requires a `CONFIRMED` order) and simply discards the accrued delivery fee with the order, and cancelling a `CONFIRMED` order likewise leaves `FAILED` or `RESCHEDULED` deliveries untouched. Both paths end in the terminal `CANCELLED` state.

Closing is the `SalesRep`'s final gate and demands a clean order on five fronts: the order must be `CONFIRMED` (otherwise `ERR_ORDER_NOT_CONFIRMED`); its `fulfillment_status` must be `DELIVERED` or `RETURN_ADJUSTED` (otherwise `ERR_ORDER_NOT_FULLY_DELIVERED`); its `payment_status` must be `PAID` or `CREDITED` (otherwise `ERR_ORDER_UNPAID`); no damage claim on any of the order's deliveries may sit in `FILED`, `UNDER_REVIEW`, `DISPUTED`, or `APPROVED` (otherwise `ERR_OPEN_CLAIMS_EXIST`); and no return on the order may sit in `REQUESTED` or `APPROVED` (otherwise `ERR_OPEN_RETURNS_EXIST`). Passing all five settles the order into the terminal `CLOSED` state.

### 3.5. Scheduling and Running Rooftop Deliveries

With an order in `QUOTED` or `CONFIRMED`, a `Dispatcher` schedules a delivery into a slot by supplying the `delivery_slot_id` and the `equipment_type`; an order in any other status is rejected with `ERR_ORDER_NOT_CONFIRMED`. The delivery's equipment must match the slot's `equipment_type`, and the slot must still have room — its `booked_count` below its `capacity`; both conditions are guarded by `ERR_SLOT_FULL`. Scheduling against a `QUOTED` order is deliberately allowed so that the delivery fee accrues into the order total before the confirmation credit check prices it in. Each new delivery starts in `SCHEDULED` with an `attempt_count` of zero, pushes the slot's `booked_count` up by one, and is priced immediately: its `bundle_count` sums the remaining undelivered quantity (`quantity_bundles` minus `delivered_bundles`, at scheduling time) across the order lines it covers — a delivery covering nothing is permitted and prices at the bare base fee — and its `fee_cents` lands on the order's `delivery_fee_cents` with `total_cents` recomputed. Whenever a delivery's fee changes on an order already `CONFIRMED` — at scheduling, at reschedule repricing, or at cancellation — the account's `pending_delivery_hold_cents` moves by the same delta; on a `QUOTED` order no hold exists yet and the fee is simply priced in at confirmation. An unknown delivery id is `ERR_DELIVERY_NOT_FOUND`, and deliveries may be listed per order or across orders with optional filters on `delivery_slot_id` and `status`.

The fee rule rewards planning and penalizes weight. The base fee is 8,500 cents ($85.00) for a `GROUND` drop and 22,500 cents ($225.00) for anything lifted — `ROOFTOP_CONVEYOR` or `CRANE`. A weight surcharge applies only above the heavy-load line of forty bundles: the surcharge is the excess over forty bundles times 350 cents per bundle, the boundary is strict, and a delivery of exactly forty bundles pays no surcharge at all. Crane work adds a flat `crane_fee_cents` of 60,000 cents ($600.00) whenever the equipment type is `CRANE`, independent of how many bundles ride the hook, and zero otherwise; the fee is the base plus the surcharge plus the crane component, all in integer cents.

Dispatch day is a chain of small, auditable transitions. Sending the truck out moves a delivery from `SCHEDULED` to `EN_ROUTE` and is allowed only from `SCHEDULED` (otherwise `ERR_DELIVERY_NOT_SCHEDULED`) and only while the parent order is `CONFIRMED` (otherwise `ERR_ORDER_NOT_CONFIRMED`); dispatch increments `attempt_count` by one and, for each covered order line, decrements the lot's `on_hand_bundles` and `reserved_bundles` by the delivered quantity — the reservation becomes a physical draw. Completing the run moves `EN_ROUTE` to the terminal `DELIVERED` state (from anywhere else, `ERR_DELIVERY_NOT_EN_ROUTE`), stamps `delivered_at` with the current logical clock, adds the delivery's quantities into each line's `delivered_bundles`, recomputes the order's `fulfillment_status` — `DELIVERED` when every line is fully delivered, otherwise `PARTIALLY_DELIVERED` — and releases the slot by decrementing `booked_count` by one.

Not every run succeeds. Marking an en-route delivery failed — again only from `EN_ROUTE`, else `ERR_DELIVERY_NOT_EN_ROUTE` — moves it to `FAILED` and restores inventory: the attempted quantity is added back to the lot's `on_hand_bundles` and `reserved_bundles`. From `FAILED`, the `Dispatcher` reschedules into a new slot by naming a fresh `delivery_slot_id` (the new slot may even be the delivery's current slot, subject to the same capacity check); the attempt is rejected with `ERR_DELIVERY_NOT_FAILED` from any other state, with `ERR_SLOT_FULL` when the new slot is full or its equipment does not match the delivery's `equipment_type`, and success moves the delivery to `RESCHEDULED`, updates `delivery_slot_id`, shifts `booked_count` from the old slot to the new (down one, up one), and reprices: `fee_cents` is recomputed under the fee rule, the order's `delivery_fee_cents` is updated, and `total_cents` recomputes. A rescheduled delivery returns to `SCHEDULED` through reconfirmation, permitted only from `RESCHEDULED` (otherwise `ERR_DELIVERY_NOT_RESCHEDULED`) with no further effects. Finally, a delivery still in `SCHEDULED` may be cancelled outright — from any other state, `ERR_DELIVERY_NOT_SCHEDULED` — which lands it in the terminal `CANCELLED` state, frees the slot (`booked_count` down one), and pulls its `fee_cents` back out of the order's `delivery_fee_cents` with `total_cents` recomputed.

### 3.6. Storm Surge Events and the Allocation Waterfall

When a storm rolls in, a `BranchManager` (or `PlatformAdmin`) declares a surge event on the affected branch with an `event_name` such as `Hail 2026-05-DAL`, a `starts_at` and `ends_at` bounding the surge window in UTC — the end must be strictly later than the start — a `surge_multiplier_pct` uplift applied to material subtotals during the window, and an `allocation_pool_bundles` total dedicating branch stock to surge allocation. A new event is `DECLARED` with `allocated_bundles` at zero; the read-only `remaining_pool_bundles` is the pool minus what is allocated. Unknown event references are `ERR_SURGE_NOT_FOUND`, and events list per branch with an optional `status` filter.

The event activates itself: when the logical clock reaches `starts_at`, the event moves from `DECLARED` to `ACTIVE` and the branch's `surge_mode` flips to `SURGE`. Each branch is expected to run a single `ACTIVE` event at a time, but nothing prevents overlapping declarations from activating together; when several events are `ACTIVE` at one branch, order confirmation auto-links against the one with the earliest `created_at`.

Contractors then request allocations by naming the `contractor_account_id`, the `product_id`, and the `requested_bundles`; each request starts `PENDING`, carries the `storm_surge_event_id` of its event, and takes an `expires_at` equal to the parent event's `ends_at`, so every allocation lapses when the window closes. A request may be filed against an event in any status; only requests under a `DECLARED` or `ACTIVE` event can ever be granted. Unknown allocation references are `ERR_ALLOCATION_NOT_FOUND`, and allocations list per event — filtered optionally by `contractor_account_id` — or across events with optional filters on `contractor_account_id`, `product_id`, `storm_surge_event_id`, and `status`.

Granting is the `BranchManager`'s decision and runs under optimistic concurrency: when the request carries `expected_storm_surge_event_version` per §2.10, a stale pool view is rejected with `ERR_STALE_VERSION` (HTTP 412). The allocation must be `PENDING` (otherwise `ERR_ALLOCATION_NOT_PENDING`) and the parent event must be `DECLARED` or `ACTIVE` (otherwise `ERR_SURGE_NOT_OPEN`). The granted quantity comes out of a waterfall. Grants are computed one allocation at a time, in the order the `BranchManager` chooses to act; the normative working order ranks the event's `PENDING` allocations by their contractor's `pricing_tier` — `VOLUME` first, then `PREFERRED`, then `STANDARD` — with ties inside a tier broken by earliest allocation `created_at`. Each granted allocation receives the smallest of three quantities: its own `requested_bundles`; its contractor's remaining tier allowance, where a single contractor may receive at most fifty percent of the event's `allocation_pool_bundles` on the `VOLUME` tier, thirty-five percent on `PREFERRED`, or twenty-five percent on `STANDARD`, each computed by rounding half down to whole bundles, and where the allowance remaining is the cap minus the bundles already granted to that contractor under the event (counting its `GRANTED`, `PARTIALLY_CONSUMED`, and `CONSUMED` allocations); and the event's `remaining_pool_bundles` at that moment. The tier cap binds before the remaining-pool check, and because earlier grants consume both the pool and the contractor's allowance, the grant order changes results — the ranked order above is therefore normative. A grant writes the outcome into `granted_bundles` (never more than requested), adds it to the event's `allocated_bundles`, increments the event's `version` by one, and moves the allocation to `GRANTED`.

Consumption and revocation keep the pool honest. As surge-linked order confirmations draw on a grant, the allocation's `consumed_bundles` climbs; consuming some but not all of the grant moves `GRANTED` to `PARTIALLY_CONSUMED`, and the moment `consumed_bundles` reaches `granted_bundles` the allocation settles into the terminal `CONSUMED` state — directly from `GRANTED` when a confirmation consumes the full grant in one step, or from `PARTIALLY_CONSUMED` when the remainder is drawn down. A `BranchManager` may revoke an allocation in `GRANTED` or `PARTIALLY_CONSUMED` — from any other state, `ERR_ALLOCATION_NOT_REVOCABLE` — which moves it to the terminal `REVOKED` state and returns the unconsumed portion (granted minus consumed) to the event by subtracting it from `allocated_bundles`.

Closing the event happens two ways with equal care. A `BranchManager` may close an event early — the close requires the event to be `DECLARED` or `ACTIVE`, otherwise `ERR_SURGE_NOT_ACTIVE` — and the system closes it automatically when the logical clock reaches `ends_at`. Closing from `ACTIVE` flips the branch's `surge_mode` back to `NORMAL` and sweeps every allocation still in `PENDING`, `GRANTED`, or `PARTIALLY_CONSUMED` into the terminal `EXPIRED` state, releasing each one's unconsumed granted bundles from the event's `allocated_bundles`. Closing from `DECLARED` — before the window ever opened — instead revokes every `PENDING` allocation into `REVOKED` and releases what they had allocated. Either way the event ends `CLOSED`, terminal.

### 3.7. Invoicing, Payments, and the Lien Lifecycle

Once an order has been delivered, a `CreditAnalyst` posts the invoice, moving the order's `payment_status` from `UNPAID` to `INVOICED`; invoicing requires the order to be `CONFIRMED` (otherwise `ERR_ORDER_NOT_CONFIRMED`), its `fulfillment_status` to be `DELIVERED` or `RETURN_ADJUSTED` (otherwise `ERR_ORDER_NOT_FULLY_DELIVERED`), and its `payment_status` to still be `UNPAID` — an already-invoiced or paid order again draws `ERR_ORDER_NOT_CONFIRMED`. Invoicing settles the provisional into the real: the order's `total_cents` is subtracted from the account's `pending_delivery_hold_cents` and added to its `open_balance_cents`, and the same amount is added to the job account's `job_balance_cents`. That invoice date starts the aging clock.

Job balances age from the invoice timestamp, measured against the logical clock; no minimum invoice age gates the filing of a preliminary notice. When a contractor owes on several invoices, payments apply to the oldest unpaid invoice first, ordered by `created_at` ascending, and `job_balance_cents` is simply the running sum of unpaid invoice totals attributed to that job. A payment posted by a `CreditAnalyst` or the `Contractor` carries an `amount_cents` and may optionally name a `job_account_id` to direct it — an unknown id, or one belonging to a different contractor account, is rejected with `ERR_JOB_ACCOUNT_NOT_FOUND`; it walks the oldest-first order, reduces the account's `open_balance_cents` by the amount (floored at zero), reduces each touched order's job account's `job_balance_cents` by the amount applied to that order (floored at zero), flips each affected order's `payment_status` to `PAID` when its invoice is fully covered, and reports back the `applied_to_order_ids` it touched along with the resulting `new_open_balance_cents`.

The lien machinery protects the distributor on aging debt. A `CreditAnalyst` files a preliminary lien notice on a job by supplying the `lien_notice_amount_cents`; filing requires the job's `lien_status` to be `NONE` (an active lien draws `ERR_LIEN_ALREADY_ACTIVE`), requires a positive `job_balance_cents` (otherwise `ERR_NO_OUTSTANDING_BALANCE`), and requires the notice amount to be greater than zero and no more than the outstanding job balance (otherwise `ERR_INVALID_LIEN_AMOUNT`). Filing stamps `notice_filed_at` with the current logical clock, moves the job to `NOTICE_FILED`, and adds the notice amount to the account's `lien_hold_cents`, immediately shrinking `credit_available_cents`.

Recording the lien escalates it. The job must be in `NOTICE_FILED` (otherwise `ERR_LIEN_NOT_IN_NOTICE`), and the cure period must have run: the logical clock must have reached at least ten days after `notice_filed_at`, otherwise the recording is rejected with `ERR_LIEN_CURE_PERIOD_ACTIVE`. Recording moves the job to `LIEN_RECORDED` and, because a recorded lien signals default, automatically moves the parent contractor account to `LIEN_DEFAULT`; from that moment the job blocks all new order confirmations with `ERR_LIEN_BLOCKS_ORDER` (§3.4).

Release closes the loop, and the two lien-active states release under the same rule. Whether the job sits in `NOTICE_FILED` or `LIEN_RECORDED` (from anywhere else, `ERR_LIEN_NOT_ACTIVE`), release requires the `job_balance_cents` to have been paid down to exactly zero (otherwise `ERR_BALANCE_STILL_OUTSTANDING`). Releasing subtracts the notice amount from the account's `lien_hold_cents`, zeroes `lien_notice_amount_cents`, clears `notice_filed_at` back to null, and lands the job in the terminal `RELEASED` state; when no job account on the account remains in `NOTICE_FILED` or `LIEN_RECORDED`, an account sitting in `LIEN_DEFAULT` reverts automatically to `ACTIVE`, while an account in any other status is left as it is.

### 3.8. Returns, Damage Claims, and Warranty Registration

Returns begin with the `Contractor`, who files a return against an order by naming the `order_line_id`, the `quantity_bundles` coming back, and optionally how many of them are `opened_bundles` — defaulting to zero and never more than the quantity itself. The request is admitted against an order in any status, and an `order_line_id` that does not identify a line on that order is rejected with `ERR_ORDER_LINE_NOT_FOUND`. A fresh return is `REQUESTED`, carries the `order_id` it belongs to, starts with `lot_match_verified` false and a `credit_amount_cents` of zero until approval, and unknown return references are `ERR_RETURN_NOT_FOUND`; returns list per order or across orders with optional filters on `order_line_id`, `order_id`, and `status`.

A `BranchManager` approves or rejects from `REQUESTED` — any other state draws `ERR_RETURN_NOT_REQUESTED`. Approval first checks arithmetic honesty: the return quantity plus the line's already-`returned_bundles` must not exceed the line's `delivered_bundles`, or the return is refused with `ERR_RETURN_QUANTITY_EXCEEDED`. Approval then computes the credit. Unopened bundles — the quantity minus the opened count — are credited at the line's locked `unit_price_cents` in full. Opened bundles earn back fifty percent of their combined unit-price amount — the opened count times the unit price times fifty percent — rounded half up to whole cents in a single step. The `restocking_fee_cents` is then 900 cents (nine dollars) per opened bundle, and the `credit_amount_cents` is the unopened credit plus the opened credit minus the restocking fee, floored at zero so a return never produces a negative credit. Rejection simply settles the return into the terminal `REJECTED` state with no financial effect.

Receiving is the `WarehouseClerk`'s scan, and it is where color and lot discipline bites. The return must be `APPROVED` (otherwise `ERR_RETURN_NOT_APPROVED`), and the scanned `returned_lot_code` must equal the lot the order line's reservation was drawn from — a mismatch is rejected with `ERR_LOT_MISMATCH` even after approval, because blended lots are exactly what this rule exists to catch. A clean receipt moves the return from `APPROVED` to the terminal `RECEIVED` state, sets `lot_match_verified` true, restocks the unopened bundles by adding the quantity minus the opened count back to the lot's `on_hand_bundles`, adds the full quantity to the line's `returned_bundles`, and marks the order's `fulfillment_status` `RETURN_ADJUSTED`. The credit then posts against money: when the order's `payment_status` is `INVOICED` or `PAID`, the `credit_amount_cents` is subtracted from the account's `open_balance_cents` (floored at zero); otherwise the credit instead reduces the pending delivery hold (likewise floored at zero). An order with open returns cannot close (§3.4).

Damage claims run a stricter, two-key workflow. The owning `Contractor` files a claim against a delivery — in any delivery state — with the `claimed_bundles` and a free-text `evidence_note`, both required; filing computes `claim_amount_cents` as the claimed bundles times the `unit_price_cents` of the delivery's first covered order line, stamps the claim `FILED` with a `review_round` of one and an `approved_amount_cents` of zero, and records the `delivery_id` it is filed against. Unknown claim references are `ERR_CLAIM_NOT_FOUND`, and claims list per delivery.

A `ClaimsAdjuster` opens the file by starting review, permitted from `FILED` or from `DISPUTED` (from anywhere else, `ERR_CLAIM_NOT_FILED`); re-entering review from `DISPUTED` increments `review_round` by one. From `UNDER_REVIEW` the adjuster may reject the claim outright — terminal `REJECTED` — or approve it by setting an `approved_amount_cents`, both transitions requiring `UNDER_REVIEW` (otherwise `ERR_CLAIM_NOT_UNDER_REVIEW`) and approval requiring the approved amount to be greater than zero and no more than the `claim_amount_cents` (otherwise `ERR_INVALID_APPROVED_AMOUNT`); the approved figure may differ from the filed amount. An owning `Contractor` who disagrees with an approved figure may dispute it — the claim must be `APPROVED` (otherwise `ERR_CLAIM_NOT_APPROVED`) and acting on someone else's job is `ERR_FORBIDDEN` — sending the claim to `DISPUTED`, from which a fresh review round begins.

Money moves only under segregation of duties. Crediting an approved claim is a `CreditAnalyst` action requiring the claim in `APPROVED` (otherwise `ERR_CLAIM_NOT_APPROVED`), and the crediting user must be a different person than the user who approved the claim — the same `X-User-ID` on both actions is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Crediting subtracts the `approved_amount_cents` from the account's `open_balance_cents` (floored at zero) and from the `job_balance_cents` of the order's job (also floored at zero); for an order still `UNPAID` or `INVOICED`, when the approved amount fully covers the order's remaining unpaid invoice total the order's `payment_status` becomes `CREDITED`, and otherwise it is unchanged — an order already `PAID` or `CREDITED` keeps its status. The claim itself settles into the terminal `CREDITED` state.

Warranty registration closes the commercial loop. The owning `Contractor` registers the manufacturer warranty for a delivered order — registration requires the order to be `CONFIRMED` (otherwise `ERR_ORDER_NOT_CONFIRMED`) and its `fulfillment_status` to be `DELIVERED` or `RETURN_ADJUSTED` (otherwise `ERR_ORDER_NOT_FULLY_DELIVERED`) — which copies the product's `manufacturer_name` onto the registration and counts `registered_bundles` as the delivered minus the returned bundles at registration time. Certification is enforced at this gate: when a product on the order has `requires_certified_installer` set, the contractor's `manufacturer_certifications` must include that product's manufacturer, or registration is refused with `ERR_CERTIFICATION_REQUIRED` (HTTP 422); `certification_verified` is recorded true on every successful registration, whether or not any product demanded certification. An order may accumulate multiple registrations over time. The registration stamps `registered_at` from the logical clock and, as noted in §2.5, is immutable — it carries `id` and `created_at` only.

## 4. Endpoint Definitions

Operations that create a new resource — a branch, a product, a lot receipt (whether it creates or tops up the lot), an account, a job account, a takeoff, an order created by takeoff conversion, a delivery slot, a scheduled delivery, a surge event, an allocation request, a return request, a damage claim, a payment, or a warranty registration — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, responses, and side effects are defined by the workflows in §3; the table below is the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/roofing/_clock/set_current_utc` | Set the logical clock (test-driving) | PlatformAdmin |
| POST | `/roofing/branches` | Create a branch | PlatformAdmin |
| GET | `/roofing/branches` | List branches | Any authenticated role |
| GET | `/roofing/branches/{id}` | Get one branch | Any authenticated role |
| POST | `/roofing/products` | Create a product | PlatformAdmin |
| GET | `/roofing/products` | List products | Any authenticated role |
| GET | `/roofing/products/{id}` | Get one product | Any authenticated role |
| POST | `/roofing/branches/{id}/inventory-lots` | Receive stock into a branch lot (creates or tops up) | WarehouseClerk, PlatformAdmin |
| GET | `/roofing/branches/{id}/inventory-lots` | List lots at a branch | PlatformAdmin, BranchManager, SalesRep, Dispatcher, WarehouseClerk |
| GET | `/roofing/inventory-lots/{id}` | Get one lot | PlatformAdmin, BranchManager, SalesRep, Dispatcher, WarehouseClerk |
| GET | `/roofing/inventory-lots` | List lots across branches with optional filters | PlatformAdmin, BranchManager, SalesRep, Dispatcher, WarehouseClerk |
| POST | `/roofing/contractor-accounts` | Create a contractor credit account | CreditAnalyst, PlatformAdmin |
| GET | `/roofing/contractor-accounts` | List contractor accounts | PlatformAdmin, BranchManager, SalesRep, CreditAnalyst |
| GET | `/roofing/contractor-accounts/{id}` | Get one contractor account | PlatformAdmin, BranchManager, SalesRep, CreditAnalyst, Contractor |
| GET | `/roofing/contractor-accounts/{id}/statement` | Account statement (invoiced-only credit reading) | CreditAnalyst, Contractor, PlatformAdmin |
| POST | `/roofing/contractor-accounts/{id}/suspend` | Suspend an account | CreditAnalyst |
| POST | `/roofing/contractor-accounts/{id}/reinstate` | Reinstate a suspended account | CreditAnalyst |
| POST | `/roofing/contractor-accounts/{id}/payments` | Post a payment; applies to oldest unpaid invoice first | CreditAnalyst, Contractor |
| POST | `/roofing/contractor-accounts/{id}/job-accounts` | Create a job account under a contractor | CreditAnalyst, Contractor, PlatformAdmin |
| GET | `/roofing/contractor-accounts/{id}/job-accounts` | List job accounts for a contractor | PlatformAdmin, BranchManager, SalesRep, CreditAnalyst, Contractor |
| GET | `/roofing/job-accounts/{id}` | Get one job account | PlatformAdmin, BranchManager, SalesRep, CreditAnalyst, Contractor |
| POST | `/roofing/job-accounts/{id}/file-lien-notice` | File a preliminary lien notice on a job | CreditAnalyst |
| POST | `/roofing/job-accounts/{id}/record-lien` | Record the lien after the cure period | CreditAnalyst |
| POST | `/roofing/job-accounts/{id}/release-lien` | Release a lien once the job balance is zero | CreditAnalyst |
| POST | `/roofing/job-accounts/{id}/takeoffs` | Create a material takeoff | SalesRep, Contractor |
| GET | `/roofing/job-accounts/{id}/takeoffs` | List takeoffs for a job | PlatformAdmin, BranchManager, SalesRep, Contractor |
| GET | `/roofing/takeoffs` | List takeoffs across jobs with optional filters | PlatformAdmin, BranchManager, SalesRep, Contractor |
| GET | `/roofing/takeoffs/{id}` | Get one takeoff | PlatformAdmin, BranchManager, SalesRep, Contractor |
| POST | `/roofing/takeoffs/{id}/quote` | Move takeoff DRAFT to QUOTED, locking the estimate | SalesRep |
| POST | `/roofing/takeoffs/{id}/revise` | Move takeoff QUOTED to DRAFT for revision | SalesRep |
| POST | `/roofing/takeoffs/{id}/convert` | Convert a QUOTED takeoff into an Order | Contractor |
| GET | `/roofing/orders` | List orders | PlatformAdmin, BranchManager, SalesRep, CreditAnalyst, Dispatcher |
| GET | `/roofing/orders/{id}` | Get one order | PlatformAdmin, BranchManager, SalesRep, CreditAnalyst, Dispatcher, Contractor |
| POST | `/roofing/orders/{id}/confirm` | Confirm an order: pick lots, lock prices, reserve inventory, place credit hold | Contractor |
| POST | `/roofing/orders/{id}/cancel` | Cancel a QUOTED or CONFIRMED order | Contractor, SalesRep |
| POST | `/roofing/orders/{id}/invoice` | Invoice a delivered order (UNPAID to INVOICED) | CreditAnalyst |
| POST | `/roofing/orders/{id}/close` | Close an order once delivered and paid | SalesRep |
| GET | `/roofing/orders/{id}/lines` | List order lines | PlatformAdmin, BranchManager, SalesRep, CreditAnalyst, Dispatcher, Contractor, WarehouseClerk |
| GET | `/roofing/order-lines` | List order lines across orders with optional filters | PlatformAdmin, BranchManager, SalesRep, CreditAnalyst, Dispatcher, WarehouseClerk |
| GET | `/roofing/order-lines/{id}` | Get one order line | PlatformAdmin, BranchManager, SalesRep, CreditAnalyst, Dispatcher, WarehouseClerk |
| POST | `/roofing/branches/{id}/delivery-slots` | Create a delivery slot | Dispatcher, PlatformAdmin |
| GET | `/roofing/branches/{id}/delivery-slots` | List slots at a branch | PlatformAdmin, BranchManager, Dispatcher, Contractor |
| GET | `/roofing/delivery-slots/{id}` | Get one slot | PlatformAdmin, BranchManager, Dispatcher, Contractor |
| POST | `/roofing/orders/{id}/deliveries` | Schedule a delivery into a slot | Dispatcher |
| GET | `/roofing/orders/{id}/deliveries` | List deliveries for an order | PlatformAdmin, BranchManager, Dispatcher, Contractor, ClaimsAdjuster |
| GET | `/roofing/deliveries` | List deliveries with optional slot filter | PlatformAdmin, BranchManager, Dispatcher, Contractor, ClaimsAdjuster |
| GET | `/roofing/deliveries/{id}` | Get one delivery | PlatformAdmin, BranchManager, Dispatcher, Contractor, ClaimsAdjuster |
| POST | `/roofing/deliveries/{id}/dispatch` | Dispatch a scheduled delivery | Dispatcher |
| POST | `/roofing/deliveries/{id}/complete` | Complete a delivery | Dispatcher |
| POST | `/roofing/deliveries/{id}/fail` | Mark an en-route delivery failed | Dispatcher |
| POST | `/roofing/deliveries/{id}/reschedule` | Reschedule a failed delivery into a new slot | Dispatcher |
| POST | `/roofing/deliveries/{id}/reconfirm` | Reconfirm a rescheduled delivery | Dispatcher |
| POST | `/roofing/deliveries/{id}/cancel` | Cancel a scheduled delivery | Dispatcher |
| POST | `/roofing/branches/{id}/surge-events` | Declare a storm surge event | BranchManager, PlatformAdmin |
| GET | `/roofing/branches/{id}/surge-events` | List surge events at a branch | PlatformAdmin, BranchManager, SalesRep, Contractor |
| GET | `/roofing/surge-events/{id}` | Get one surge event | PlatformAdmin, BranchManager, SalesRep, Contractor |
| POST | `/roofing/surge-events/{id}/close` | Close a surge event early | BranchManager |
| POST | `/roofing/surge-events/{id}/allocations` | Request a surge allocation | Contractor |
| GET | `/roofing/surge-events/{id}/allocations` | List allocations for an event | PlatformAdmin, BranchManager, Contractor |
| GET | `/roofing/allocations` | List allocations across events with optional filters | PlatformAdmin, BranchManager, Contractor |
| GET | `/roofing/allocations/{id}` | Get one allocation | PlatformAdmin, BranchManager, Contractor |
| POST | `/roofing/allocations/{id}/grant` | Grant a pending allocation per the waterfall | BranchManager |
| POST | `/roofing/allocations/{id}/revoke` | Revoke an unconsumed allocation | BranchManager |
| POST | `/roofing/orders/{id}/returns` | Request a return against an order line | Contractor |
| GET | `/roofing/orders/{id}/returns` | List returns for an order | PlatformAdmin, BranchManager, WarehouseClerk, Contractor |
| GET | `/roofing/returns` | List returns across orders with optional filters | PlatformAdmin, BranchManager, WarehouseClerk, Contractor |
| GET | `/roofing/returns/{id}` | Get one return | PlatformAdmin, BranchManager, WarehouseClerk, Contractor |
| POST | `/roofing/returns/{id}/approve` | Approve a return, computing credit | BranchManager |
| POST | `/roofing/returns/{id}/receive` | Receive returned bundles; verifies lot match and restocks | WarehouseClerk |
| POST | `/roofing/returns/{id}/reject` | Reject a return | BranchManager |
| POST | `/roofing/deliveries/{id}/damage-claims` | File a damage claim on a delivery | Contractor |
| GET | `/roofing/deliveries/{id}/damage-claims` | List claims for a delivery | PlatformAdmin, BranchManager, ClaimsAdjuster, CreditAnalyst, Contractor |
| GET | `/roofing/damage-claims/{id}` | Get one claim | PlatformAdmin, BranchManager, ClaimsAdjuster, CreditAnalyst, Contractor |
| POST | `/roofing/damage-claims/{id}/start-review` | Start reviewing a claim (from FILED or DISPUTED) | ClaimsAdjuster |
| POST | `/roofing/damage-claims/{id}/approve` | Approve a claim with an approved amount | ClaimsAdjuster |
| POST | `/roofing/damage-claims/{id}/reject` | Reject a claim | ClaimsAdjuster |
| POST | `/roofing/damage-claims/{id}/credit` | Credit an approved claim to the contractor account (SoD enforced) | CreditAnalyst |
| POST | `/roofing/damage-claims/{id}/dispute` | Contractor disputes an approved claim amount | Contractor |
| POST | `/roofing/orders/{id}/warranty-registrations` | Register manufacturer warranty for a delivered order | Contractor |
| GET | `/roofing/orders/{id}/warranty-registrations` | List warranty registrations for an order | PlatformAdmin, BranchManager, Contractor |

## 5. Error Code Catalogue

The catalogue below fixes every machine-readable error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_BRANCH_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_TAKEOFF_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_SURGE_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_TAKEOFF_NOT_DRAFT` | 409 Conflict |
| `ERR_TAKEOFF_NOT_QUOTED` | 409 Conflict |
| `ERR_ORDER_NOT_QUOTED` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ORDER_NOT_FULLY_DELIVERED` | 409 Conflict |
| `ERR_ORDER_UNPAID` | 409 Conflict |
| `ERR_OPEN_CLAIMS_EXIST` | 409 Conflict |
| `ERR_OPEN_RETURNS_EXIST` | 409 Conflict |
| `ERR_ACTIVE_DELIVERY_EXISTS` | 409 Conflict |
| `ERR_DELIVERY_NOT_SCHEDULED` | 409 Conflict |
| `ERR_DELIVERY_NOT_EN_ROUTE` | 409 Conflict |
| `ERR_DELIVERY_NOT_FAILED` | 409 Conflict |
| `ERR_DELIVERY_NOT_RESCHEDULED` | 409 Conflict |
| `ERR_SLOT_FULL` | 409 Conflict |
| `ERR_SURGE_NOT_ACTIVE` | 409 Conflict |
| `ERR_SURGE_NOT_OPEN` | 409 Conflict |
| `ERR_ALLOCATION_NOT_PENDING` | 409 Conflict |
| `ERR_ALLOCATION_NOT_REVOCABLE` | 409 Conflict |
| `ERR_SURGE_ALLOCATION_EXCEEDED` | 409 Conflict |
| `ERR_RETURN_NOT_REQUESTED` | 409 Conflict |
| `ERR_RETURN_NOT_APPROVED` | 409 Conflict |
| `ERR_RETURN_QUANTITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_LOT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_FILED` | 409 Conflict |
| `ERR_CLAIM_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVED` | 409 Conflict |
| `ERR_INVALID_APPROVED_AMOUNT` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_LIEN_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_NO_OUTSTANDING_BALANCE` | 422 Unprocessable Entity |
| `ERR_INVALID_LIEN_AMOUNT` | 422 Unprocessable Entity |
| `ERR_LIEN_NOT_IN_NOTICE` | 409 Conflict |
| `ERR_LIEN_CURE_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_LIEN_NOT_ACTIVE` | 409 Conflict |
| `ERR_BALANCE_STILL_OUTSTANDING` | 409 Conflict |
| `ERR_LIEN_BLOCKS_ORDER` | 402 Payment Required |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_LOT_UNAVAILABLE` | 409 Conflict |
| `ERR_CERTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
