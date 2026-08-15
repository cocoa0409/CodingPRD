# Public Refrigerated Warehousing API — Product Requirements Document

## 1. Introduction

Public refrigerated warehousing rests on a simple commercial promise with demanding mechanics behind it: a food producer hands custody of palletized perishables to a third-party cold-storage operator, and the operator answers for every pallet's location, temperature exposure, and condition until the goods ship back out. This document specifies the Public Refrigerated Warehousing API, the system of record for such an operator. It governs the full custody cycle — scheduling inbound trucks against dock-door and zone capacity, putting pallets away into temperature-classified zones, running a blast-freezing service, and releasing inventory first-in-first-out against customer orders — and the commercial cycle that runs alongside it: rate cards, per-event handling charges, monthly storage and aged-inventory billing, and bailment claims when something goes wrong.

Two commitments shape every rule that follows. First, custody is accountable. Inventory is tracked at single-pallet granularity under a bailment relationship, so a temperature excursion observed in one zone, or a recall declared against one lot, must fan out deterministically to every affected pallet, every open allocation, and every order that was counting on that stock. Second, money follows events. Handling and blast-freeze charges accrue onto a live monthly invoice the moment the physical work completes, while storage and aged-inventory dwell charges are pinned down only when a billing run closes the period. The distinction between provisional accrual and finalized statement is deliberate, and the rules below preserve it everywhere.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `CustomerAdmin`, `WarehouseOperator`, `QualityManager`, `ClaimsAdjuster`, and `BillingAdmin`. A request that arrives without these headers, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. Access to specific operations is restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `CustomerAdmin`, `X-User-ID` is the `id` of the acting Customer — the inventory-owning bailor — and ownership checks on any resource that references a Customer compare the resource's `customer_id` field to `X-User-ID`. A `CustomerAdmin` touching a resource whose `customer_id` belongs to a different customer is rejected with `ERR_FORBIDDEN`, and this ownership rule extends to reads: a `CustomerAdmin` sees only their own receipts, orders, lots, pallets, bookings, recalls, claims, and invoices. Temperature excursions carry no `customer_id` — they are zone-scoped — so they are exempt from ownership scoping, and any authenticated role may read any excursion. When `X-User-Role` is `WarehouseOperator`, `QualityManager`, `ClaimsAdjuster`, or `BillingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `reported_by_user_id` on a TemperatureExcursion, where the reporting operator's identity is preserved so that segregation of duties can be enforced later — but it is never compared to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` that is not an integer or falls outside 1–100, and an `offset` that is not an integer or is negative, are rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties on creation timestamp broken by the resources' creation sequence — the order in which the server created the records.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`.

### 2.4. The Logical Clock

Every temporal rule in this document — arrival windows, booking windows, billing periods, dwell age, volume-discount months — is evaluated against a single logical clock maintained by the server. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it never consults wall-clock time. The only way to advance it is an administrative time-setting capability, available to all five roles, that accepts a `to_iso8601` instant and responds with the clock's new reading as `current_utc`. Wherever this document says "now", it means this logical clock.

### 2.5. Common Resource Properties

Every resource in the system — Customer, RateCard, TemperatureZone, InboundReceipt, InventoryLot, Pallet, OutboundOrder, Allocation, BlastFreezeCell, BlastFreezeBooking, TemperatureExcursion, RecallEvent, Claim, and Invoice — carries a standard set of system-managed fields, with no exceptions:

- **`id` (string):** A unique, server-generated identifier for the resource, formatted as a UUID with no type prefix. Every resource is addressable by its `id`.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (for example, 2026-08-01T08:15:30.123Z), recording when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp, in the same format, recording when the resource was last modified. It is refreshed upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that starts at 1 when the resource is created and increments by one with every modification to the resource, including modifications driven by system cascades rather than by a direct client request. It underpins the optimistic concurrency rules of §2.7.

### 2.6. Monetary Representation and Rounding

All monetary values in the system — rates on rate cards, charges on invoices, claim settlements, credit limits, customer balances — are represented as integer cents. Rate and configuration fields supplied by clients are stored exactly as provided.

Where a calculation produces a fractional cent, the rounding method is always "round half up" to whole cents, and the rounding point is pinned per calculation. Storage lines are rounded per pallet to whole cents first and only then summed into the invoice component; the alternative ordering — summing raw per-pallet values and rounding once at the end — is a different, rejected reading. The aged-inventory dwell surcharge is likewise rounded per pallet. The outbound handling fee, whether estimated or final, is rounded per order. An invoice total is then a plain sum of integer-cent components with no further rounding, and it is permitted to go negative when claim credits exceed charges, representing a credit balance owed to the customer; the total is never clamped at zero.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and no other endpoint takes a version field.

Creating a rate card supersedes the customer's currently ACTIVE card, so a create request must carry `expected_customer_version`, holding the client's last observed `version` of that Customer. If the value does not match the Customer's current `version` — because the customer's record has advanced since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from pricing against a customer state it has not observed.

Amending an outbound order releases its allocations and re-prices its estimate, so an amend request must carry `expected_order_version`, holding the client's last observed `version` of that OutboundOrder. A mismatch with the order's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because a previously accepted amend has already changed the requested quantity and the allocation set the caller observed.

### 2.8. Zone Capacity Accounting and Storage Posture

Each temperature zone tracks three capacity figures that together determine what the warehouse can accept. `in_use_pallets` counts the pallets physically present in the zone — those whose custody status is `STORED`, `IN_BLAST_FREEZE`, or `ALLOCATED`; pallets that have shipped or been dispositioned no longer count. `reserved_pallets` is the sum of `expected_pallets` over that zone's inbound receipts currently standing at `ARRIVED`, representing trucks at the dock whose putaway is imminent. `free_pallets` is what remains: the zone's `capacity_pallets` minus `in_use_pallets` minus `reserved_pallets`. Both figures are recomputed whenever a pallet changes custody status and whenever a receipt arrives or completes.

From `free_pallets` the zone derives a storage `posture`, recomputed on every change. The tight threshold for a zone is the greater of one pallet position and ten percent of the zone's capacity rounded down to a whole number. When `free_pallets` reaches zero — or falls below it, which an arrival reservation larger than the remaining free capacity can cause — the posture is `FULL`. When `free_pallets` is greater than zero but no more than the tight threshold, the posture is `TIGHT`. Otherwise the posture is `OPEN`. Posture gates physical intake: an arrival attempted against a zone whose posture is `FULL` is rejected, as detailed in §3.2.

### 2.9. Request Validation Order

Every request is evaluated against a fixed, ordered cascade of validation tiers. A request that would fail at several tiers is rejected with the error belonging to the earliest applicable tier, so that a failure deeper in the cascade never masks one nearer the surface. The tiers, in order, are:

1. **Authentication**, applied to all endpoints: the `X-User-ID` and `X-User-Role` headers are present and the role is recognized; otherwise `ERR_UNAUTHENTICATED`.
2. **Request-body schema**, applied to all write endpoints: required fields are present, types are valid, enum values are in range, quantities that must be positive are positive, and any `window_end` is strictly later than its `window_start`; otherwise `ERR_VALIDATION`.
3. **Role authorization**, applied to all endpoints: the caller's role is listed among the endpoint's authorized roles; otherwise `ERR_FORBIDDEN`.
4. **Ownership**, applied to customer-scoped endpoints: a `CustomerAdmin` may only access or modify resources whose `customer_id` equals their `X-User-ID`; otherwise `ERR_FORBIDDEN`.
5. **Existence**, applied to all resource endpoints: path identifiers and foreign-key references in the body are resolved in left-to-right order, and the first reference that does not exist yields `ERR_NOT_FOUND`.
6. **State validity**, applied to all action endpoints: the target resource must stand in a valid from-state for the requested transition, including terminal-state lockdown, and any OCC expectation on the request must match; an invalid from-state is rejected `ERR_INVALID_STATE`, while a stale OCC expectation is rejected `ERR_STALE_VERSION`.
7. **Food-safety gates**, applied to order submission and to excursion confirmation and clearing: an order submitted with a `lot_code` override whose lot stands at `RECALLED` is rejected `ERR_LOT_RECALLED`, and the segregation-of-duties check on excursion adjudication is rejected `ERR_SOD_VIOLATION`.
8. **Temporal window rules**, applied to receipt creation and to booking creation and start: dock-door aggregate overlap (`ERR_DOCK_CAPACITY_EXCEEDED`), cell-window conflict including the turnaround buffer (`ERR_BOOKING_WINDOW_CONFLICT`), and booking start outside its window (`ERR_OUTSIDE_WINDOW`).
9. **Capacity and consistency**, applied to receipt create, arrive, and complete, to booking create and start, and to recall completion: temperature-class agreement (`ERR_TEMP_CLASS_MISMATCH`), a full zone at arrival (`ERR_ZONE_FULL`), putaway capacity (`ERR_ZONE_CAPACITY_EXCEEDED`), cell capacity (`ERR_CELL_CAPACITY_EXCEEDED`), lot production-date continuity (`ERR_LOT_PRODUCTION_DATE_MISMATCH`), freezable-stock sufficiency (`ERR_INSUFFICIENT_FREEZABLE_STOCK`), and undispositioned recalled stock blocking recall completion (`ERR_RECALL_HAS_UNDISPOSITIONED_STOCK`).
10. **Claim cross-references**, applied to claim creation: the referenced excursion must stand at `CONFIRMED_BREACH` (`ERR_EXCURSION_NOT_CONFIRMED`), and the claimed pallet count must not exceed the excursion's quarantined count (`ERR_CLAIM_EXCEEDS_QUARANTINED_COUNT`).
11. **Fiscal gates**, applied to receipt creation, order creation, submission, and amendment, receipt completion, booking completion, claim decision, and invoice settlement: customer standing (`ERR_CUSTOMER_SUSPENDED`), the presence of an ACTIVE rate card wherever a charge is levied (`ERR_NO_ACTIVE_RATE_CARD`), the credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`), and exact settlement amount (`ERR_INVOICE_AMOUNT_MISMATCH`).

### 2.10. Bailment and the Open-Invoice Accrual Model

The warehouse holds goods in bailment: the customer retains ownership, and the operator's financial exposure and charges both follow from that relationship. Fiscally, every customer always has exactly one invoice standing at `OPEN`, covering the current calendar month. Charges accrue onto it as the physical work happens — inbound handling at receipt completion, outbound handling at ship time, blast-freeze fees at booking completion, and claim credits at claim settlement — while the storage and dwell components remain zero until a billing run closes the period. Four charging events require the customer to have an ACTIVE rate card at the moment of the event: receipt completion, order submission, blast-freeze booking completion, and claim approval. Any of them attempted with no ACTIVE card in force is rejected with `ERR_NO_ACTIVE_RATE_CARD`.

A customer's `outstanding_balance_cents`, exposed on every read of the Customer, is the sum of `total_cents` over that customer's invoices standing at `FINALIZED` or `DISPUTED`, plus — from the single `OPEN` invoice — the accrued `handling_in_cents`, `handling_out_cents`, and `blast_freeze_cents`, minus its `claim_credit_cents`. Because storage and dwell are zero on an `OPEN` invoice until finalization, they contribute nothing to the balance mid-period.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and Commercial Terms

A `BillingAdmin` onboards a new customer by supplying a `name` and a `credit_limit_cents`, the maximum outstanding balance the customer may carry, which must be zero or greater. The Customer record begins life at status `ACTIVE`, and creation automatically opens the customer's first invoice: status `OPEN`, `period_start` at the first instant of the calendar month containing now, `period_end` at the first instant of the following month, and every charge component at zero. The customer's `outstanding_balance_cents` is computed on every read per the accrual model of §2.10.

Commercial terms live on the **RateCard**. A `BillingAdmin` creates one by supplying the `customer_id` together with the full rate schedule: a `storage_method` of `DAILY_PRORATED` or `FULL_MONTH`; the monthly pallet rates `frozen_storage_cents_per_pallet_month` and `chilled_storage_cents_per_pallet_month`; the per-pallet inbound and outbound handling rates `handling_in_cents_per_pallet` and `handling_out_cents_per_pallet`; the blast-freeze fees `blast_base_cents` and `blast_per_pallet_cents`; the bailment `liability_model` of `DECLARED_VALUE` or `LIMITED_LIABILITY` with its `liability_per_pallet_cents` cap; and a `dwell_exempt` flag that, when true, excuses the customer from the aged-inventory surcharge. The create must also carry `expected_customer_version` per §2.7. The new card is created `ACTIVE`; any prior `ACTIVE` card for the same customer is immediately superseded, moving to `SUPERSEDED`, and the Customer's `version` increments by one. At most one card per customer is ever `ACTIVE`. Events price off whichever card is `ACTIVE` at the moment the event occurs, while an invoice records the `rate_card_id` used at its finalization.

Suspension is the fiscal safety valve. A `BillingAdmin` may patch a customer's `status` to `SUSPENDED` or restore it to `ACTIVE`, and may likewise adjust `credit_limit_cents`; each such update increments the customer's `version`. While a customer stands at `SUSPENDED`, no new inbound receipt may be scheduled for them and no outbound order may be created or submitted on their behalf — each attempt is rejected with `ERR_CUSTOMER_SUSPENDED`.

### 3.2. Inbound Receiving: Scheduling, Arrival, and Putaway

Before goods can arrive, a `WarehouseOperator` establishes the physical plant. Each **TemperatureZone** is created with a `zone_code` that must be unique across all zones — a duplicate `zone_code` is rejected with `ERR_VALIDATION` — a `temp_class` of `FROZEN` or `CHILLED`, a `capacity_pallets` count of at least one, and a `dock_doors` count of at least one bounding how many arrivals may overlap at the zone's doors. A freshly created zone starts empty: `in_use_pallets` and `reserved_pallets` at zero, `free_pallets` equal to capacity, and `posture` `OPEN`.

A `CustomerAdmin` schedules an inbound receipt for their own customer by providing the `customer_id`, the pre-assigned `zone_id`, the `product_code`, the manufacturer's `lot_code`, the `production_date` as an ISO calendar date — this date is the primary key for FIFO release — the goods' `temp_class`, a declared `expected_pallets` of at least one, and the scheduled arrival window from `window_start` to `window_end`. The receipt is born `SCHEDULED`; its `lot_id` stays null until completion, as does `actual_pallets`. Scheduling enforces three gates. The customer must stand at `ACTIVE`, else `ERR_CUSTOMER_SUSPENDED`. The receipt's `temp_class` must equal the assigned zone's `temp_class`, else `ERR_TEMP_CLASS_MISMATCH`. And the dock doors must absorb the window: counting the zone's other receipts standing at `SCHEDULED` or `ARRIVED` whose windows strictly overlap the new one, the count must remain below the zone's `dock_doors`, else `ERR_DOCK_CAPACITY_EXCEEDED`. Windows that merely touch — one window's end equal to another's start — do not overlap and are always allowed.

When the truck arrives, a `WarehouseOperator` marks the receipt arrived. The zone's posture must not be `FULL` — that is, `free_pallets` must not have reached zero — or the arrival is turned away with `ERR_ZONE_FULL`. On success the receipt moves `SCHEDULED` → `ARRIVED` and its `expected_pallets` is added to the zone's `reserved_pallets`, recomputing free capacity and posture. A receipt still at `SCHEDULED` may instead be cancelled — by the owning `CustomerAdmin` or by a `WarehouseOperator` — moving it to `CANCELLED`; an arrived receipt can no longer be cancelled and such an attempt is rejected with `ERR_INVALID_STATE`.

Putaway completion is the moment custody begins. A `WarehouseOperator` completes an `ARRIVED` receipt by reporting the counted `actual_pallets`, which must be at least one or the request fails `ERR_VALIDATION`. The customer must have an `ACTIVE` rate card, else `ERR_NO_ACTIVE_RATE_CARD`. The reservation comes off first: the receipt's `expected_pallets` is subtracted from the zone's `reserved_pallets`, and only then is the capacity check applied — the counted `actual_pallets` must fit within the zone's capacity minus its `in_use_pallets` minus its now-reduced `reserved_pallets`, else `ERR_ZONE_CAPACITY_EXCEEDED`. Completion then performs a lot upsert keyed on the triple of `customer_id`, `product_code`, and `lot_code`: if no such **InventoryLot** exists it is created, and if one does exist its `production_date` — set by the first receipt ever merged into it — must equal this receipt's `production_date`, else `ERR_LOT_PRODUCTION_DATE_MISMATCH`. With the lot resolved, the system creates exactly `actual_pallets` Pallets, each with status `STORED`, quality `OK`, `received_at` set to now, `zone_id` taken from the receipt, `receipt_id` pointing back to the receipt that created it, `customer_id` denormalized from the receipt, and `lot_id` naming the resolved lot — which is also written back onto the receipt alongside the recorded `actual_pallets`. The zone's `in_use_pallets` grows by `actual_pallets` and posture is recomputed. Finally, the charge lands: the customer's `OPEN` invoice accrues into `handling_in_cents` an amount equal to `actual_pallets` multiplied by the ACTIVE card's `handling_in_cents_per_pallet`, and the receipt stands `COMPLETED`.

### 3.3. Inventory Custody: Pallets, Lots, and the Dual-Dimension Condition Model

Every **Pallet** carries two independent, parallel state dimensions. The custody dimension, `status`, tracks where the pallet is in its physical lifecycle: `STORED` at rest in a zone, `IN_BLAST_FREEZE` inside a freezing cell, `ALLOCATED` to an outbound order, and the terminal `SHIPPED` or `DISPOSITIONED` once it leaves custody. The quality dimension, `quality`, tracks food-safety standing: `OK`, `QUARANTINED`, or `RECALLED`. Neither dimension implies the other, and guards reference both — allocation and blast-freeze selection, for instance, each demand a pallet that is simultaneously `STORED` and `OK`. Four timestamps round out the record: `received_at` is set when the creating receipt completes; `last_blast_frozen_at` stays null until the pallet's first completed blast freeze and, once set, anchors the dwell clock; `out_at` stays null while the pallet is present and is stamped when it leaves custody; and `out_reason`, likewise null while present, then reads `SHIPPED` or `DISPOSED`.

A **InventoryLot** has no lifecycle of its own to drive — its `status` is a compound value recomputed on every pallet creation, custody change, quality change, shipment, or disposal, and its `on_hand_pallets` counts the pallets present, meaning those at `STORED`, `IN_BLAST_FREEZE`, or `ALLOCATED`. The recomputation follows a strict precedence. If any present pallet has quality `RECALLED`, the lot is `RECALLED`. Otherwise, if `on_hand_pallets` has fallen to zero and at least one pallet was ever created for the lot, the lot is `DEPLETED`. Otherwise, if every present pallet is `QUARANTINED` — with at least one present — the lot is `FULL_HOLD`. Otherwise, if some but not all present pallets are `QUARANTINED`, the lot is `PARTIAL_HOLD`. Failing all of those, the lot is `AVAILABLE`. A lot's `lot_code` is unique per pairing of `customer_id` and `product_code`, which is what lets receipts, orders, and recalls refer to lots by their human-readable codes.

Two quality-driven actions are reserved for a `QualityManager`. Releasing a quarantined pallet returns its `quality` from `QUARANTINED` to `OK` and recomputes the parent lot's status. Disposing of a pallet — destruction or return to the bailor — is permitted only from `STORED` custody and only when the pallet's quality is `RECALLED`; any other combination is rejected with `ERR_INVALID_STATE`. Disposition stamps `out_at` with now, sets `out_reason` to `DISPOSED`, moves custody to `DISPOSITIONED`, decrements the zone's `in_use_pallets`, and recomputes the lot.

### 3.4. Blast Freezing Service

Blast freezing runs on dedicated cells. A `WarehouseOperator` creates each **BlastFreezeCell** with a `cell_code` unique across all cells (a duplicate `cell_code` is rejected with `ERR_VALIDATION`), a `capacity_pallets` giving the maximum pallets per booking at at least one, and a `turnaround_minutes` of zero or more — the mandatory gap the cell needs between consecutive bookings.

A `WarehouseOperator` books a cell window by naming the `cell_id`, the `lot_id` whose pallets are to be frozen, a `pallet_count` of at least one, and the window from `window_start` to `window_end`; the booking's `customer_id` is denormalized from the lot, and its `fee_cents` stays null until completion. The requested `pallet_count` must not exceed the cell's `capacity_pallets`, else `ERR_CELL_CAPACITY_EXCEEDED`. The window must also clear the cell's schedule: a conflict exists whenever an existing booking on the same cell standing at `SCHEDULED` or `IN_PROGRESS` is positioned such that the new window's start falls before the existing window's end extended by the cell's `turnaround_minutes`, and the existing window's start falls before the new window's end extended by that same buffer; any such collision is rejected `ERR_BOOKING_WINDOW_CONFLICT`. The practical reading is that the gap between two bookings on one cell must be at least the cell's turnaround, so when the turnaround is positive even back-to-back adjacency conflicts.

Starting a booking — moving it `SCHEDULED` → `IN_PROGRESS` — is gated on time and stock. The logical clock must read within the booking window, inclusive of both `window_start` and `window_end`; a start attempted outside is rejected `ERR_OUTSIDE_WINDOW`. The pallet selector then draws from the booking's lot the pallets standing at `STORED` with quality `OK`, ordered by `received_at` ascending with ties broken by `created_at` ascending and any remaining ties broken by creation sequence, taking `pallet_count` of them; if fewer qualify, the start fails with `ERR_INSUFFICIENT_FREEZABLE_STOCK`. Each selected pallet moves `STORED` → `IN_BLAST_FREEZE`.

Completing a booking returns every selected pallet from `IN_BLAST_FREEZE` to `STORED` and stamps each pallet's `last_blast_frozen_at` with now — resetting its dwell clock for the aged-inventory surcharge. The customer must hold an `ACTIVE` rate card, else `ERR_NO_ACTIVE_RATE_CARD`. The booking's `fee_cents` is fixed at completion as the card's `blast_base_cents` plus the booking's `pallet_count` multiplied by the card's `blast_per_pallet_cents`, and that fee accrues immediately into the customer's `OPEN` invoice under `blast_freeze_cents`. A booking still at `SCHEDULED` may instead be cancelled, moving it to `CANCELLED` and freeing its window: a cancelled booking no longer participates in the overlap check, whose candidate set is exactly the bookings at `SCHEDULED` or `IN_PROGRESS`.

### 3.5. Outbound Release: Orders, FIFO Allocation, and Shipping

A `CustomerAdmin` opens an **OutboundOrder** for their own customer with a `customer_id`, the `product_code` to release, a `requested_pallets` of at least one, and an optional `lot_code` override that restricts release to that lot — left null, release is pure FIFO across all of the customer's lots of that product. The customer must stand at `ACTIVE`, else `ERR_CUSTOMER_SUSPENDED`. The order is born `DRAFT`, with `allocated_pallets` at zero, `estimated_handling_out_cents` null until the first submission or amendment computes it, and `final_handling_out_cents` null, a value it keeps until the order ships.

Submission — `DRAFT` → `SUBMITTED`, by the owning `CustomerAdmin` — runs the safety and fiscal gates in a pinned order. The customer must still stand at `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`) and must hold an `ACTIVE` rate card (`ERR_NO_ACTIVE_RATE_CARD`). If a `lot_code` override is present, that lot must exist (`ERR_NOT_FOUND`) and must not stand at `RECALLED` (`ERR_LOT_RECALLED`). The system then computes and stores the provisional `estimated_handling_out_cents`, and only after that estimate exists does it apply the credit check: the order is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` if and only if the customer's `outstanding_balance_cents` plus the estimated fee is strictly greater than `credit_limit_cents`; a sum exactly equal to the limit passes.

The handling-out fee is volume-discounted, and the order under pricing counts toward its own tier. The volume figure is the count of pallets this customer has `SHIPPED` with an `out_at` falling inside the calendar month of now, plus this order's own quantity — `requested_pallets` when estimating at submit or amend, `allocated_pallets` when fixing the final fee at ship. A volume reaching five hundred pallets earns a twenty percent discount; reaching one hundred earns ten percent; below that, none. The fee is the quantity multiplied by the ACTIVE card's `handling_out_cents_per_pallet`, multiplied by one minus the discount, rounded half up to whole cents. The estimate stored at submit or amend uses the current month's shipped volume and is provisional; the final fee computed at ship uses the ship month's shipped volume, so the two diverge whenever cumulative volume crosses a tier boundary between submission and shipment.

Allocation is run by a `WarehouseOperator` and follows strict FIFO. Candidate pallets are those belonging to the order's customer, in lots whose `product_code` equals the order's, standing at `STORED` with quality `OK`, restricted to the named lot when the order carries a `lot_code`, and never a pallet already actively allocated to this same order. Candidates are ordered by their lot's `production_date` ascending, then by the pallet's `received_at` ascending, then by `created_at` ascending, with any remaining ties broken by creation sequence — the pallet identifier is never used as an ordering key. The selector takes from the front of that ordering as many pallets as are needed to close the gap between `requested_pallets` and the order's current `allocated_pallets`. Each pick creates an **Allocation** standing at `ACTIVE` — recording the `order_id`, the `pallet_id`, and the `lot_id` denormalized from the pallet — and moves the pallet `STORED` → `ALLOCATED`. When the fill is complete, meaning `allocated_pallets` now equals `requested_pallets`, the order advances to `ALLOCATED`; a partial or empty fill leaves it at `SHORTED`. From `SHORTED`, a later allocation run after more stock arrives tops the order up: a full fill advances it to `ALLOCATED`, while a still-short fill leaves it at `SHORTED`.

Amendment lets the owning `CustomerAdmin` replace `requested_pallets` while the order stands at `DRAFT` or `SHORTED`; any other state rejects the amend with `ERR_INVALID_STATE`. The request carries `expected_order_version` per §2.7, and a stale expectation fails with `ERR_STALE_VERSION`. Amendment releases every `ACTIVE` allocation on the order — each pallet returning `ALLOCATED` → `STORED`, each allocation moving to `RELEASED` — replaces `requested_pallets`, recomputes the estimate, re-runs the credit check (`ERR_CREDIT_LIMIT_EXCEEDED`), and increments the order's `version` by one. A `SHORTED` order returns to `DRAFT`; a `DRAFT` order remains `DRAFT`.

Individual allocations can also be released by hand. A `WarehouseOperator` releasing an `ACTIVE` allocation moves it to `RELEASED`, returns the pallet `ALLOCATED` → `STORED`, demotes the owning order from `ALLOCATED` back to `SUBMITTED` — an order at `SHORTED` stays `SHORTED` — and recomputes `allocated_pallets`, which is always the count of `ACTIVE` allocations on the order.

Shipping, performed by a `WarehouseOperator` on an order standing at `ALLOCATED`, is the custody exit. Every `ACTIVE` allocation on the order moves to `FULFILLED`; every allocated pallet moves `ALLOCATED` → `SHIPPED` with `out_at` stamped to now and `out_reason` set to `SHIPPED`; the zone's `in_use_pallets` falls by the shipped count; and each affected lot recomputes, which may leave a lot `DEPLETED`. The final `final_handling_out_cents` is computed on the ship-month volume variant described above and accrues into the customer's `OPEN` invoice under `handling_out_cents`; the order stands `SHIPPED`. Shipping is not among the four charging events that require an ACTIVE rate card (§2.10): if the customer has no ACTIVE card at ship time, the final fee is zero and the ship proceeds.

Cancellation, by the owning `CustomerAdmin`, is available from `DRAFT`, `SUBMITTED`, `SHORTED`, or `ALLOCATED` and moves the order to `CANCELLED`. Cancelling from `SHORTED` or `ALLOCATED` first releases all `ACTIVE` allocations, returning their pallets to `STORED`; cancelling from `DRAFT` or `SUBMITTED` has no allocations to unwind.

### 3.6. Temperature Excursions and Quarantine

When a `WarehouseOperator` observes a zone running warm, they report a **TemperatureExcursion** with the `zone_id`, the `observed_temp_c` in Celsius — any JSON number, integer or decimal, stored and echoed exactly as supplied — and the excursion window from `window_start` to `window_end`. The report is born `REPORTED`; the reporter's identity is captured from `X-User-ID` into `reported_by_user_id`, `quarantined_pallet_count` starts at zero, and — critically — no stock is touched at report time.

Adjudication belongs to a `QualityManager`, under segregation of duties: the operator who reported an excursion may not be the one to confirm or clear it. A confirm or clear attempt whose `X-User-ID` equals the excursion's `reported_by_user_id` is rejected with `ERR_SOD_VIOLATION`.

Confirmation — `REPORTED` → `CONFIRMED_BREACH` — fires a four-hop quarantine cascade. First, every pallet in the excursion's zone standing at `STORED`, `ALLOCATED`, or `IN_BLAST_FREEZE`, whose custody overlaps the excursion window, and whose quality is `OK`, moves to `QUARANTINED`, and the count of pallets caught is stored on the excursion as `quarantined_pallet_count`. Overlap is the only temporal test: a pallet overlaps when its `received_at` is earlier than the excursion's `window_end` and it was still in custody after the window opened — either `out_at` is null or `out_at` is later than `window_start`. A pallet that arrived after the window opened is not exempt. Second, each affected lot recomputes its compound status, sliding from `AVAILABLE` to `PARTIAL_HOLD` or `FULL_HOLD` as the quarantined share dictates. Third, any pallet that was `ALLOCATED` when quarantined releases its allocation — the allocation moves to `RELEASED`, the pallet returns to `STORED`, and its `QUARANTINED` quality is retained. Fourth, each order that owned a released allocation demotes from `ALLOCATED` back to `SUBMITTED`; an order at `SHORTED` is unchanged.

Clearing — `REPORTED` → `CLEARED`, under the same segregation-of-duties gate — records that no breach occurred: no quarantine happens and `quarantined_pallet_count` stays at zero.

### 3.7. Recall Management and Stock Disposition

A `QualityManager` declares a **RecallEvent** by naming the `customer_id`, the `product_code`, the `lot_code`, and a free-text `reason`. At declaration the system resolves the lot from that triple; if no such lot exists the declaration fails with `ERR_NOT_FOUND`, and otherwise the resolved `lot_id` is stored on the recall, which stands at `DECLARED`.

Activation — `DECLARED` → `ACTIVE` — executes the recall cascade. Every pallet of the recalled lot standing at `STORED`, `ALLOCATED`, or `IN_BLAST_FREEZE` moves to quality `RECALLED`, and a pallet that was `ALLOCATED` first releases its allocation and returns to `STORED` before the recall mark lands. Released allocations move to `RELEASED`, and each order that owned one demotes from `ALLOCATED` to `SUBMITTED`. Pallets of the lot already standing at `QUARANTINED` are caught as well, moving from `QUARANTINED` to `RECALLED`. Finally, the lot itself is marked `RECALLED`.

Completion — `ACTIVE` → `COMPLETED` — is allowed only once the recalled stock is gone: if any pallet of the lot is still present with quality `RECALLED`, completion is rejected with `ERR_RECALL_HAS_UNDISPOSITIONED_STOCK`. Disposition per §3.3 is how recalled stock leaves custody and clears the way. A recall still at `DECLARED` may instead be cancelled, moving it to `CANCELLED` with no effect on stock.

### 3.8. Claims Under Bailment

A bailment claim compensates the inventory owner for goods lost to a confirmed temperature breach. The owning `CustomerAdmin` files a **Claim** with the `customer_id`, the `excursion_id` giving rise to the loss, an `affected_pallet_count` of at least one, and a `declared_value_cents` greater than zero stating the bailor-declared value of the goods. Two cross-reference gates apply at filing: the excursion must stand at `CONFIRMED_BREACH`, else `ERR_EXCURSION_NOT_CONFIRMED`; and the `affected_pallet_count` must not exceed that excursion's `quarantined_pallet_count`, else `ERR_CLAIM_EXCEEDS_QUARANTINED_COUNT` with HTTP status 422. The claim is born `FILED`, and its `settlement_cents` stays null unless and until it is approved.

A `ClaimsAdjuster` moves a claim from `FILED` to `UNDER_REVIEW`, and later renders a decision by supplying a `decision` of `APPROVED` or `DENIED`. Approval requires the customer to hold an `ACTIVE` rate card — else `ERR_NO_ACTIVE_RATE_CARD` — and computes `settlement_cents` off that card's `liability_model`. Under `DECLARED_VALUE`, the settlement is the full `declared_value_cents`. Under `LIMITED_LIABILITY`, the settlement is the lesser of `declared_value_cents` and the `affected_pallet_count` multiplied by the card's `liability_per_pallet_cents` — strictly less than the declared value whenever the declared value exceeds that per-pallet cap times the affected count. Denial moves the claim to `DENIED` with no settlement computed.

The appeal loop runs through the customer: the owning `CustomerAdmin` may reopen a `DENIED` claim, moving it to `REOPENED`, from which a `ClaimsAdjuster`'s review returns it to `UNDER_REVIEW` for another decision. A claim still at `FILED` may instead be withdrawn by its owner, moving to `WITHDRAWN`. Settlement belongs to a `BillingAdmin`: settling an `APPROVED` claim moves it to `SETTLED` and credits its `settlement_cents` into the customer's `OPEN` invoice under `claim_credit_cents`, recomputing the invoice's `total_cents`.

### 3.9. Monthly Billing: Storage, Dwell, and Settlement

Invoices live on a monthly cadence keyed to the logical clock. Each **Invoice** spans from `period_start`, inclusive, to `period_end`, exclusive, and carries the components `storage_cents`, `handling_in_cents`, `handling_out_cents`, `blast_freeze_cents`, `dwell_surcharge_cents`, and `claim_credit_cents`, summing to `total_cents`. While an invoice stands at `OPEN`, the handling, blast, and claim-credit components accrue live as their triggering events occur, while `storage_cents` and `dwell_surcharge_cents` hold at zero.

A `BillingAdmin` triggers the billing checkpoint to close the month. The run finalizes every `OPEN` invoice whose `period_end` has been reached or passed by the logical clock, responding with a `finalized_count` and the list of `finalized_invoice_ids`; when nothing is eligible the run succeeds with a `finalized_count` of zero rather than erroring. Finalization — `OPEN` → `FINALIZED` — records the `rate_card_id` of the card `ACTIVE` at run time, computes storage and dwell as below, recomputes `total_cents`, and opens the successor `OPEN` invoice covering the following month. If the customer has no `ACTIVE` card at run time, storage and dwell are computed at zero rates and the finalized invoice's `rate_card_id` is recorded as null.

The storage charge is built pallet by pallet. For each pallet of the customer, the system counts the calendar dates within the period — from `period_start` up to but not including `period_end` — on which the pallet was present: the date of its `received_at` on or before that date, and either `out_at` null or the date of `out_at` strictly after that date. A pallet shipped or disposed mid-period therefore counts only through the day before its out date. The class rate is the card's `frozen_storage_cents_per_pallet_month` for pallets resting in `FROZEN` zones and `chilled_storage_cents_per_pallet_month` for those in `CHILLED` zones. Under the `DAILY_PRORATED` storage method, the pallet's line is its present-days count multiplied by the class rate and divided by thirty, rounded half up to whole cents. Under `FULL_MONTH`, the line is the full monthly class rate when the pallet was present at least one day in the period, and zero otherwise. The invoice's `storage_cents` is the sum of those per-pallet lines, and per §2.6 the rounding is applied to each line before summing — never once at the end.

The dwell surcharge penalizes aged inventory, measured for each pallet still in custody on the period's last day — the calendar day immediately before `period_end`, with presence tested the same way as for storage. The pallet's dwell anchor is the later of its `received_at` and its `last_blast_frozen_at`, so a completed blast freeze restarts the clock; dwell days are the whole days elapsed between that anchor and `period_end`. The tier percentage applied to the class rate is one hundred percent at one hundred twenty dwell days or more, fifty percent at ninety days or more, twenty-five percent at sixty days or more, and zero below sixty days. The zone multiplier is 1.0 for a `FROZEN` zone and 1.5 for a `CHILLED` zone. Each pallet's surcharge is its class rate multiplied by the tier percentage and the zone multiplier, rounded half up to whole cents — or zero outright when the customer's card is `dwell_exempt`. The surcharges sum into `dwell_surcharge_cents`.

The invoice total is the sum of `storage_cents`, `handling_in_cents`, `handling_out_cents`, `blast_freeze_cents`, and `dwell_surcharge_cents`, minus `claim_credit_cents` — integer-cent components combined with no further rounding, permitted to go negative when credits exceed charges per §2.6.

After finalization, the owning `CustomerAdmin` may dispute a `FINALIZED` invoice, moving it to `DISPUTED`; while disputed, all line amounts are frozen and no component may change. A `BillingAdmin` resolves the dispute, returning the invoice `DISPUTED` → `FINALIZED` with every component unchanged, so the round trip conserves `total_cents`. Settlement is the terminal act: a `BillingAdmin` settles a `FINALIZED` invoice by paying an `amount_cents` that must equal `total_cents` exactly — any other amount is rejected `ERR_INVOICE_AMOUNT_MISMATCH` — moving the invoice to `SETTLED` and triggering recomputation of the customer's `outstanding_balance_cents`. Invoice listings follow the global ordering default, sorted by `created_at` ascending in deterministic index order.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Operations that create new, stand-alone resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, updates, accrual-triggering actions — return a `200 OK` status code. List endpoints accept optional filter parameters corresponding to the resource's foreign keys and status fields, alongside the pagination parameters of §2.3. The table below is a summary only; request payloads, computed fields, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | All roles |
| POST | `/api/customers` | Onboard a customer; auto-creates the OPEN invoice for the current month | BillingAdmin |
| GET | `/api/customers/{id}` | Get a customer, including the computed outstanding balance | All roles |
| GET | `/api/customers` | List customers | All roles |
| PATCH | `/api/customers/{id}` | Update credit limit and/or status (suspend or reactivate) | BillingAdmin |
| POST | `/api/rate-cards` | Create a rate card; supersedes the customer's prior ACTIVE card; OCC-guarded | BillingAdmin |
| GET | `/api/rate-cards/{id}` | Get a rate card | All roles |
| GET | `/api/rate-cards` | List rate cards | All roles |
| POST | `/api/zones` | Create a temperature zone | WarehouseOperator |
| GET | `/api/zones/{id}` | Get a zone with computed capacity fields and posture | All roles |
| GET | `/api/zones` | List zones | All roles |
| POST | `/api/inbound-receipts` | Schedule an inbound receipt with arrival window and pre-assigned zone | CustomerAdmin |
| GET | `/api/inbound-receipts/{id}` | Get a receipt | All roles |
| GET | `/api/inbound-receipts` | List receipts | All roles |
| POST | `/api/inbound-receipts/{id}/arrive` | Mark the truck arrived; reserves zone capacity | WarehouseOperator |
| POST | `/api/inbound-receipts/{id}/complete` | Complete putaway; creates pallets and charges handling-in | WarehouseOperator |
| POST | `/api/inbound-receipts/{id}/cancel` | Cancel a scheduled receipt | CustomerAdmin, WarehouseOperator |
| GET | `/api/lots/{id}` | Get a lot with its compound status | All roles |
| GET | `/api/lots` | List lots | All roles |
| GET | `/api/pallets/{id}` | Get a pallet | All roles |
| GET | `/api/pallets` | List pallets | All roles |
| POST | `/api/pallets/{id}/release-quarantine` | Release a quarantined pallet back to OK quality | QualityManager |
| POST | `/api/pallets/{id}/dispose` | Dispose of a RECALLED pallet, removing it from custody | QualityManager |
| POST | `/api/outbound-orders` | Create a release order | CustomerAdmin |
| GET | `/api/outbound-orders/{id}` | Get an order | All roles |
| GET | `/api/outbound-orders` | List orders | All roles |
| POST | `/api/outbound-orders/{id}/submit` | Submit an order; safety and fiscal gates; stores the provisional handling-out estimate | CustomerAdmin |
| POST | `/api/outbound-orders/{id}/allocate` | Run FIFO allocation; full fill advances, partial or zero fill shorts | WarehouseOperator |
| POST | `/api/outbound-orders/{id}/amend` | Amend requested pallets; releases allocations; OCC-guarded | CustomerAdmin |
| POST | `/api/outbound-orders/{id}/ship` | Ship an allocated order; charges the final handling-out fee | WarehouseOperator |
| POST | `/api/outbound-orders/{id}/cancel` | Cancel a non-terminal order; releases allocations | CustomerAdmin |
| GET | `/api/allocations/{id}` | Get an allocation | All roles |
| GET | `/api/allocations` | List allocations | All roles |
| POST | `/api/allocations/{id}/release` | Manually release an ACTIVE allocation | WarehouseOperator |
| POST | `/api/blast-freeze-cells` | Create a blast-freeze cell | WarehouseOperator |
| GET | `/api/blast-freeze-cells/{id}` | Get a cell | All roles |
| GET | `/api/blast-freeze-cells` | List cells | All roles |
| POST | `/api/blast-freeze-bookings` | Book a cell window for a lot; overlap rule includes the turnaround buffer | WarehouseOperator |
| GET | `/api/blast-freeze-bookings/{id}` | Get a booking | All roles |
| GET | `/api/blast-freeze-bookings` | List bookings | All roles |
| POST | `/api/blast-freeze-bookings/{id}/start` | Start a booking inside its window; selects pallets into the freeze | WarehouseOperator |
| POST | `/api/blast-freeze-bookings/{id}/complete` | Complete a booking; resets dwell clocks and charges the fee | WarehouseOperator |
| POST | `/api/blast-freeze-bookings/{id}/cancel` | Cancel a scheduled booking, freeing the window | WarehouseOperator |
| POST | `/api/temperature-excursions` | Report a temperature excursion on a zone | WarehouseOperator |
| GET | `/api/temperature-excursions/{id}` | Get an excursion | All roles |
| GET | `/api/temperature-excursions` | List excursions | All roles |
| POST | `/api/temperature-excursions/{id}/confirm` | Confirm a breach; fires the quarantine cascade; reporter barred | QualityManager |
| POST | `/api/temperature-excursions/{id}/clear` | Clear a reported excursion; reporter barred | QualityManager |
| POST | `/api/recalls` | Declare a recall for a customer, product, and lot | QualityManager |
| GET | `/api/recalls/{id}` | Get a recall | All roles |
| GET | `/api/recalls` | List recalls | All roles |
| POST | `/api/recalls/{id}/activate` | Activate a recall; marks lot stock RECALLED and releases affected allocations | QualityManager |
| POST | `/api/recalls/{id}/complete` | Complete a recall once all recalled stock is dispositioned | QualityManager |
| POST | `/api/recalls/{id}/cancel` | Cancel a DECLARED recall | QualityManager |
| POST | `/api/claims` | File a bailment claim against a confirmed excursion | CustomerAdmin |
| GET | `/api/claims/{id}` | Get a claim | All roles |
| GET | `/api/claims` | List claims | All roles |
| POST | `/api/claims/{id}/review` | Move a claim to UNDER_REVIEW | ClaimsAdjuster |
| POST | `/api/claims/{id}/decide` | Approve or deny an UNDER_REVIEW claim; approval computes the settlement | ClaimsAdjuster |
| POST | `/api/claims/{id}/settle` | Settle an APPROVED claim; credits the customer's OPEN invoice | BillingAdmin |
| POST | `/api/claims/{id}/reopen` | Reopen a DENIED claim | CustomerAdmin |
| POST | `/api/claims/{id}/withdraw` | Withdraw a FILED claim | CustomerAdmin |
| GET | `/api/invoices/{id}` | Get an invoice | All roles |
| GET | `/api/invoices` | List invoices | All roles |
| POST | `/api/invoices/{id}/dispute` | Dispute a FINALIZED invoice | CustomerAdmin |
| POST | `/api/invoices/{id}/resolve-dispute` | Resolve a dispute; returns the invoice to FINALIZED unchanged | BillingAdmin |
| POST | `/api/invoices/{id}/settle` | Settle a FINALIZED invoice; amount must equal the total exactly | BillingAdmin |
| POST | `/api/billing/run` | Finalize every due OPEN invoice and open each customer's next-month invoice | BillingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_LOT_RECALLED` | 409 Conflict |
| `ERR_DOCK_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BOOKING_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_TEMP_CLASS_MISMATCH` | 409 Conflict |
| `ERR_ZONE_FULL` | 409 Conflict |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CELL_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_FREEZABLE_STOCK` | 409 Conflict |
| `ERR_LOT_PRODUCTION_DATE_MISMATCH` | 409 Conflict |
| `ERR_RECALL_HAS_UNDISPOSITIONED_STOCK` | 409 Conflict |
| `ERR_EXCURSION_NOT_CONFIRMED` | 409 Conflict |
| `ERR_CLAIM_EXCEEDS_QUARANTINED_COUNT` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_NO_ACTIVE_RATE_CARD` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_INVOICE_AMOUNT_MISMATCH` | 409 Conflict |
