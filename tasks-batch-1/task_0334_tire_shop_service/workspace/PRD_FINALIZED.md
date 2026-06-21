# Tire Shop & Service API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Tire Shop & Service API, the system of record for a full-service tire retailer that sells tires from a fitment-aware catalog and installs them in scheduled service bays. The platform must reconcile two concerns that the front counter and the back shop have historically kept on separate clipboards: the *money* — per-tire pricing, bracketed disposal fees, road-hazard premiums, tax, store credit, and warranty payouts — and the *physical work* — which tires fit which vehicle, whether they are in stock or must be specially ordered, and when a bay with the right equipment is free to mount and balance them.

The API governs the entire arc of a customer visit. A work order is opened against a customer's vehicle, line items for tires and services are added while the order is still a draft, and approval freezes a priced, stock-committed contract. From there the two halves of the order proceed on independent tracks: a payment track that authorizes and captures money, and a fulfillment track that schedules a bay appointment, checks the vehicle in, performs the work, and completes the job. Layered on top are the after-sale obligations the shop carries for years — road-hazard coverage that can be claimed against a damaged tire, and mileage warranties that prorate a credit when a tire wears out before its rated mileage. Every monetary figure in the system is an exact integer count of cents, and every multi-step financial operation is reversible, so that cancelling an order restores stock, store credit, and bay time to exactly the state they held before approval.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that govern every endpoint. Where a rule is stated here it is not repeated in full for each workflow in §3; readers should treat §2 as always in force.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Customer`, `ServiceAdvisor`, `Technician`, and `InventoryManager`.

A `Customer` is a vehicle owner. The role is entity-backed: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`, and any ownership check on a resource that references a customer compares that resource's customer foreign key to `X-User-ID`. A customer manages their own vehicles, opens and lines up their own work orders, views their pricing, books and requests rescheduling of their own appointments, and submits mileage-warranty claims.

The other three roles are operator roles whose identities are not tied to any persisted entity. When `X-User-Role` is `ServiceAdvisor`, `Technician`, or `InventoryManager`, `X-User-ID` is an opaque operator identifier; the server may log it but does not compare it to any entity's `id`. A `ServiceAdvisor` is the shop-counter staff member who drives the work-order lifecycle: approving pricing, moving money, managing appointments, and adjudicating claims. A `Technician` is the bay worker who checks vehicles in and progresses the physical service. An `InventoryManager` owns the catalog, stock levels, fitment declarations, service bays, and special orders.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set; it defaults to 0.

Unless an endpoint states otherwise, every list is sorted by the resource's creation timestamp in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every resource carries a server-minted `id`, formatted as a UUID with no type prefix. Most resources also carry the standard audit triad: a `created_at` timestamp set once at creation, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that begins at 1 on creation and increases by one with each version-tracked mutation. All three timestamps are ISO 8601 in UTC with three fractional digits.

One entity is the exception. A `FitmentRule` is an immutable junction record once written; it carries only `id` and `created_at`, and has neither an `updated_at` field nor a `version` field. Every other entity in this system — `Customer`, `Vehicle`, `TireModel`, `ServiceBay`, `WorkOrder`, `WorkOrderLine`, `RoadHazardWarranty`, `InstallAppointment`, `SpecialOrder`, and `MileageWarrantyClaim` — carries the full audit triad.

### 2.5. Monetary Values, Precision, and Rounding

All monetary values in the system are integer counts of cents; there are no fractional-cent or floating-point money fields anywhere. Wherever a calculation multiplies a money amount by a rate or fraction, the half-up rounding rule is applied and the result is again an integer count of cents. Each calculation in §3 names exactly where its single rounding step falls; rounding is never applied more than once within a single computed figure, and intermediate products are carried at full precision until that named rounding point. "Round half up" means a value whose fractional part is exactly one-half is rounded away from zero to the next whole cent.

### 2.6. Resource Path Validation and Reference Integrity

When an endpoint path contains a resource identifier, that resource must exist; if it does not, the request fails with `ERR_NOT_FOUND`. When a path contains more than one identifier, they are validated left to right, and the first identifier that does not resolve produces `ERR_NOT_FOUND` before any later identifier is considered.

Separately, request bodies that reference other resources by their foreign keys — among them `customer_id`, `vehicle_id`, `tire_model_id`, `work_order_id`, `service_bay_id`, and `work_order_line_id` — are checked against the store. A body that names a resource that does not exist is rejected with `ERR_REFERENCE_NOT_FOUND`. Field-level input validity — that every enum value is within its declared domain, every bounded number is within range, every quantity is at least 1, and every required field is present — is enforced across all endpoints and, when it fails, raises `ERR_INVALID_REQUEST`.

### 2.7. The Parallel State of a Work Order

A `WorkOrder` is unusual in that it tracks two independent lifecycle dimensions at once. Its `fulfillment_status` records the progress of physical work and moves through `DRAFT`, `APPROVED`, `IN_SERVICE`, and `COMPLETED`, with `CANCELLED` as a terminal sink. Its `payment_status` records the state of the money and moves through `UNPAID`, `AUTHORIZED`, and `PAID`, with `REFUNDED` as a terminal sink. These two axes evolve independently: authorizing payment does not advance fulfillment, and starting service does not advance payment. The only points where the axes interact are spelled out in §3 — the payment gate at completion, the automatic capture that completion may trigger, and the refund that cancellation may trigger.

### 2.8. Cascading Side Effects and Compensation

Several operations in this system mutate more than one entity in a single atomic step, and the system guarantees that the secondary effects always accompany the primary one. Approving an order is the principal example: it does not merely flip a status but commits its lines, debits catalog stock, activates warranties, debits customer store credit, and writes a full set of computed money fields, all at once. Its mirror image is cancellation, which is designed as an exact compensation: stock that was debited is restocked, store credit that was applied is refunded, active warranties are voided, and reserved bay time is released, so that the catalog, the customer's credit balance, and the bay calendar are conserved across the approve/cancel pair. Whenever an operation mutates a resource, that resource's `updated_at` is refreshed; whenever it is one of the version-tracked mutations called out in §3, the resource's `version` is also incremented.

### 2.9. Optimistic Concurrency Control

A small set of writes are guarded by optimistic concurrency control, because they act on a parent whose state may have moved on since the client last read it. Each guarded write requires the client to supply the parent's last-observed `version` as a non-optional field, and the server compares it to the parent's current `version` before proceeding. A mismatch means the client is acting on a stale view, and the write is refused with an HTTP 412 status.

There are two such guards. Adding a line to a work order requires `expected_work_order_version` to equal that work order's current `version`; adding a line refreshes the order's `updated_at` but does not itself increment the order's `version`, so an order accumulates lines while its `version` holds at 1 throughout `DRAFT`. Because an order's version is bumped at approval and at cancellation, a mismatch on line add means the order's lifecycle has already advanced past `DRAFT` under another writer's view, and the line add would be rejected with `ERR_STALE_WORK_ORDER_VERSION`; the `DRAFT`-state requirement (which on violation yields `ERR_INVALID_STATE`) is evaluated before this version comparison, so on any order whose version has actually moved off 1 the state check fires first and `ERR_STALE_WORK_ORDER_VERSION` is in practice unreachable on line add. Booking an install appointment requires `expected_service_bay_version` to equal the chosen bay's current `version`; because a bay's version is bumped whenever an appointment is booked on it or it is closed or reopened, a mismatch means the client booked against an out-of-date picture of the bay's occupancy and the booking is rejected with `ERR_STALE_BAY_VERSION`. The work-order approval, bay-close, and bay-reopen operations are likewise version-checked against their target; where a guarded write's supplied version does not match and no more specific code applies, the generic `ERR_STALE_VERSION` is returned, also with HTTP 412. Endpoints not named here as guarded take no version field.

### 2.10. Catalog, Stock, and Fitment Governance

The catalog is the inventory backbone. Each `TireModel` carries a `status` that is `ACTIVE` when created and may be moved to `DISCONTINUED`; discontinuation is a one-way status change. On-hand inventory is tracked by `stock_qty`, which is set from the optional creation input (defaulting to zero when omitted) and is the live count of sellable units. Stock is debited when tire lines are committed at order approval, restored when an order is cancelled, increased when a special order is received, and adjusted manually by a restock operation that applies a `delta_qty` to the current `stock_qty`. A restock whose `delta_qty` would drive `stock_qty` below zero is rejected with `ERR_NEGATIVE_STOCK`, and `stock_qty` is never permitted to fall below zero through any path.

Fitment is the safety backbone. A `FitmentRule` is a junction record pairing a vehicle with a tire model and grading the pairing as `OE_EXACT`, `APPROVED_PLUS`, or `NOT_RECOMMENDED`. Only the first two grades represent an approved fit; a `NOT_RECOMMENDED` grade, or the absence of any fitment record for the pairing, means the tire is not approved for that vehicle and blocks order approval as described in §3.

## 3. Business Logic & Workflows

### 3.1. Customers, Vehicles, and the Catalog They Draw From

A `ServiceAdvisor` registers a customer at the counter by supplying an `email`, a `full_name`, and a `phone`. The `email` is the customer's unique login identity and must be non-empty and unique across all customers. Each customer carries a running `store_credit_cents` balance that begins at zero, can never be negative, and is moved only by the warranty and order flows described later — it is credited when an approved mileage claim pays out as store credit and debited when a customer elects to apply credit to an order.

Vehicles belong to customers. A customer (or an advisor acting for them) registers a vehicle by naming its owner through `customer_id`, its `make`, its `model`, and its `model_year`, which must be no earlier than 1980 and no later than 2030. The vehicle also records its original-equipment tire size in `oe_tire_size`, its wheel `rim_diameter_in` in inches (no smaller than 13 and no larger than 24), and its `tpms_type`, the tire-pressure-monitoring technology fitted to the vehicle, which is one of `DIRECT`, `INDIRECT`, or `NONE`. Vehicles may be listed and optionally narrowed to a single owner by `customer_id`.

The `InventoryManager` builds and maintains the catalog. A `TireModel` is created with a `brand`, a `model_name`, a `size_token` such as a standard tire-size string, a `load_index` between 70 and 130 inclusive, and a `speed_rating` drawn from `S`, `T`, `H`, `V`, `W`, or `Y`. Pricing and warranty attributes are set at the same time: `unit_price_cents` is the per-tire retail price and must be non-negative; `mileage_warranty_miles` is the treadwear mileage warranty, defaulting to zero, where zero means the model carries no mileage warranty at all; and `original_tread_32nds` is the new-tire tread depth in thirty-seconds of an inch, between 6 and 14 inclusive, which serves as the baseline for warranty proration. Catalog models can be fetched individually and listed or searched, optionally filtered by `size_token` and by `status`. The manager also declares fitment by creating a `FitmentRule` that names a `vehicle_id`, a `tire_model_id`, and a `fitment_grade`; fitment rules can be fetched and listed, filterable by `vehicle_id` or by `tire_model_id`.

### 3.2. Building and Pricing a Work Order

A work order opens against a customer and one of that customer's vehicles. The advisor or customer supplies `customer_id` and `vehicle_id`, and may optionally pre-declare `store_credit_applied_cents`, the amount of store credit they wish to put toward the order at approval. At creation the order is born in `DRAFT` fulfillment and `UNPAID` payment. The vehicle named by `vehicle_id` must be owned by the customer named by `customer_id` — that is, the vehicle's owner must be that same customer — and a mismatch is rejected with `ERR_VEHICLE_NOT_OWNED`. Orders may be fetched with all their computed money fields and listed, filterable by `customer_id`, `vehicle_id`, `fulfillment_status`, and `payment_status`.

Line items are added only while the order is still `DRAFT`; an attempt to add a line to an order in any other state is rejected with `ERR_INVALID_STATE`. Each `WorkOrderLine` declares a `line_type` of `TIRE`, `MOUNT_BALANCE`, `ROTATION`, `TPMS_SERVICE`, or `ALIGNMENT`, a `quantity` of at least one, and may set `road_hazard_opted` to request road-hazard coverage. A `TIRE` line must name the tire it sells through `tire_model_id`, and a non-`TIRE` line must omit `tire_model_id` entirely; either violation — a `TIRE` line without the field or a non-`TIRE` line carrying it — is rejected with `ERR_LINE_TYPE_FIELD_MISMATCH`. For non-`TIRE` lines, `road_hazard_opted` carries no meaning and is forced to false. Because adding a line is a concurrency-guarded write against the parent order, the request also carries `expected_work_order_version` as described in §2.9.

When a line is created the system snapshots its per-unit price into `unit_price_cents_snapshot`: for a `TIRE` line this is the tire model's `unit_price_cents` at that moment, and for a service line it is the fixed service rate for that line type. The line is born `PENDING` in `line_status`, and the `extended_cents` it will eventually carry is computed at approval. Lines may be listed for an order, fetched individually, and listed across orders filterable by `work_order_id` or `tire_model_id`.

Approval is the pivotal event, performed by a `ServiceAdvisor`, that moves `fulfillment_status` from `DRAFT` to `APPROVED` and finalizes the order's economics. Approval requires the order to be in `DRAFT`, to have at least one line, and to carry `expected_work_order_version` matching the order's current `version`; a version mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412. The system evaluates the approval guards in priority order: authentication and authorization first, then existence of the order, then the order's `DRAFT` state, then — before any pricing runs — the fitment and stock guards. Specifically, every `TIRE` line's tire model must have a `FitmentRule` for the order's vehicle whose `fitment_grade` is `OE_EXACT` or `APPROVED_PLUS`; any tire whose only fitment record is `NOT_RECOMMENDED`, or which has no fitment record for the vehicle at all, blocks approval with `ERR_FITMENT_NOT_APPROVED`. Then every `TIRE` line must be coverable: either the tire model's `stock_qty` is sufficient for the line's `quantity`, or a special order that is still open or already received exists to cover the shortfall; a line that can be neither stocked nor sourced blocks approval with `ERR_INSUFFICIENT_STOCK`.

Once the guards pass, pricing runs in a pinned order, and the result is written into the order's computed fields. First, for each line that is not `VOID`, the system sets `extended_cents` to the line's `unit_price_cents_snapshot` multiplied by its `quantity`; since both are integers this product is exact. Second, it sums the extended amounts into two buckets: `parts_subtotal_cents` is the sum of `extended_cents` over `TIRE` lines, and `service_subtotal_cents` is the sum over the four service line types `MOUNT_BALANCE`, `ROTATION`, `TPMS_SERVICE`, and `ALIGNMENT`. Third, it computes `disposal_fee_cents` from the total tire quantity as described in §3.3. Fourth, it computes `road_hazard_premium_cents` as the sum of the per-line premiums over every `TIRE` line that opted into coverage, each premium computed as described in §3.4. Fifth, it computes the tax: the taxable base is `parts_subtotal_cents` plus `service_subtotal_cents` only — disposal fees and road-hazard premiums are not taxable — and `tax_cents` is that taxable base multiplied by the tax rate of 8.25 percent, rounded half up to a whole cent in this single rounding step. Sixth, it forms the pre-credit grand total as the sum of `parts_subtotal_cents`, `service_subtotal_cents`, `disposal_fee_cents`, `road_hazard_premium_cents`, and `tax_cents`; the applied credit is the smallest of three quantities — the order's requested `store_credit_applied_cents`, the customer's available `store_credit_cents`, and that pre-credit grand total — and `total_due_cents` is the pre-credit total minus that applied credit, so it can never go negative. The input set for the whole calculation is exactly the order's lines whose `line_status` is not `VOID`; void lines are excluded.

The non-pricing side effects of approval all fire in the same atomic step. The order's `store_credit_applied_cents` is clamped to the applied-credit amount just computed, and the customer's `store_credit_cents` is debited by that clamped amount. Every line that is not already `VOID` moves from `PENDING` to `COMMITTED` in `line_status`, capturing its `extended_cents`. For each committed `TIRE` line backed by sufficient stock, the tire model's `stock_qty` is debited by the line's `quantity`. For each committed `TIRE` line that opted into road-hazard coverage, a `RoadHazardWarranty` is created and activated as described in §3.4. Finally the order's `version` is incremented by one.

### 3.3. Tire Disposal Fees

Every tire that leaves the shop carries an environmental disposal fee, and the fee per tire steps *down* as the count grows, rewarding larger jobs. The fee is allocated marginally across three brackets by the total number of tires `n` summed over all non-`VOID` `TIRE` lines on the order — not as a flat per-tire rate chosen from the top bracket. The first four tires are charged 350 cents each; tires five through eight are charged 250 cents each; the ninth tire and every tire beyond it are charged 150 cents each. Concretely, `disposal_fee_cents` is the smaller of `n` and four, multiplied by 350 cents; plus the part of `n` lying between five and eight inclusive — that is, `n` minus four, clamped to lie between zero and four — multiplied by 250 cents; plus any tires past the eighth — that is, `n` minus eight when positive, otherwise zero — multiplied by 150 cents. The allocation is exact integer arithmetic with no rounding. This figure becomes the order's `disposal_fee_cents` and is excluded from the taxable base.

### 3.4. Road-Hazard Coverage and Premiums

Road-hazard coverage is purchased per tire line at the moment the line is created, by setting `road_hazard_opted` on a `TIRE` line. The coverage itself does not become real until the order is approved: at approval, for each committed `TIRE` line that opted in, the system creates a `RoadHazardWarranty` recording the covered `work_order_line_id` and the snapshot `tire_model_id`, sets its `covered_quantity` equal to the covered line's `quantity`, computes its `premium_cents`, and moves it from `PENDING` to `ACTIVE` in its `status`. Warranties can be fetched and listed, filterable by `work_order_line_id` or `tire_model_id`.

The premium for one covered line is the larger of two amounts. The first is a percentage term: the line's `extended_cents` multiplied by the road-hazard rate of 12 percent, rounded half up to a whole cent. The second is a per-tire floor: the line's `quantity` multiplied by a floor of 1200 cents per tire. The line's `premium_cents` is the greater of the rounded percentage term and the floor; rounding is applied only to the percentage term, before the comparison. The order's `road_hazard_premium_cents` is the sum of these per-line premiums, and like the disposal fee it is not taxable.

A road-hazard warranty has a short lifecycle beyond `PENDING` and `ACTIVE`. If the order is cancelled, any `ACTIVE` warranty on it is voided, moving its `status` to `VOID`. And if a mileage-warranty claim on the same line is approved while an `ACTIVE` warranty exists on that line, the warranty is consumed and its `status` moves to `CLAIMED` — road-hazard coverage and a paid mileage claim cannot both be drawn from the same line.

### 3.5. Service Bays and Their Schedules

The `InventoryManager` provisions service bays. A `ServiceBay` is created with a `bay_name` that is unique across all bays, an optional `alignment_capable` flag indicating whether the bay has an alignment rack (defaulting to false), and an optional `turnover_buffer_min`, the cleanup time in minutes that must remain free after one appointment ends before the next may begin in that bay; the buffer defaults to 15 minutes and must lie between 0 and 60 inclusive. A bay's `status` is `OPEN` when created. Bays can be fetched and listed, filterable by `status`.

A manager may take a bay out of service, moving its `status` from `OPEN` to `OUT_OF_SERVICE`, but only when the bay currently has no appointment in `SCHEDULED`, `RESCHEDULE_PENDING`, or `CHECKED_IN` — a bay with live work on its calendar cannot be closed — and only when the supplied `expected_service_bay_version` matches the bay's current `version`; closing bumps that `version` by one. Reopening reverses the move, taking `status` from `OUT_OF_SERVICE` back to `OPEN`, again gated by a matching `expected_service_bay_version` and again bumping `version` by one. An `OUT_OF_SERVICE` bay refuses new appointments.

### 3.6. Booking, Rescheduling, and Checking In Appointments

An appointment ties an approved work order to a bay for a window of time. Booking supplies the `work_order_id`, the `service_bay_id`, a `scheduled_start` and a `scheduled_end`, and the `expected_service_bay_version` that guards against a stale view of the bay (see §2.9). The booked window is treated as a half-open interval: `scheduled_start` is included and `scheduled_end` is excluded, and `scheduled_end` must be strictly later than `scheduled_start`, with any non-positive interval rejected as `ERR_INVALID_INTERVAL`. A new appointment is born `SCHEDULED`. The system computes `requires_alignment` from the order's lines — it is true exactly when the order has an `ALIGNMENT` line — and a booking is rejected with `ERR_BAY_NOT_ALIGNMENT_CAPABLE` if the order requires alignment but the chosen bay is not `alignment_capable`. The chosen bay must be `OPEN`; booking against a bay whose `status` is `OUT_OF_SERVICE` is rejected with `ERR_BAY_OUT_OF_SERVICE`. Finally, the requested window must not collide with the bay's existing calendar: the interval, extended past its end by the bay's `turnover_buffer_min`, must not overlap any `SCHEDULED` or `CHECKED_IN` appointment on the same bay, and a collision is rejected with `ERR_BAY_TIME_CONFLICT`. A successful booking bumps the bay's `version` by one. Appointments can be fetched and listed, filterable by `service_bay_id`, `work_order_id`, and `status`.

Plans change, and the appointment lifecycle accommodates a revert cycle. A `Customer` may request a reschedule of their own appointment, moving its `status` from `SCHEDULED` to `RESCHEDULE_PENDING`; while in `RESCHEDULE_PENDING` the appointment's window no longer blocks the bay, so its released slot is available to other overlap checks. A `ServiceAdvisor` then confirms the reschedule, which carries a new `scheduled_start` and `scheduled_end`, re-runs the very same guards as a fresh booking — the new interval must be well formed, the bay must still be `OPEN`, the alignment requirement must still be satisfiable by the bay, and the new window plus the bay's turnover buffer must not overlap any `SCHEDULED` or `CHECKED_IN` appointment on that bay — and on success moves `status` from `RESCHEDULE_PENDING` back to `SCHEDULED`, updating the window so that it once again blocks the bay. The same interval, alignment, and overlap rejections (`ERR_INVALID_INTERVAL`, `ERR_BAY_NOT_ALIGNMENT_CAPABLE`, `ERR_BAY_OUT_OF_SERVICE`, and `ERR_BAY_TIME_CONFLICT`) apply to confirm-reschedule exactly as they do to booking.

A `Technician` checks the vehicle in, moving the appointment from `SCHEDULED` to `CHECKED_IN`. Check-in carries two cross-entity preconditions: the parent work order's `fulfillment_status` must be `APPROVED`, and the appointment's bay `status` must be `OPEN`; checking into a closed bay is rejected with `ERR_BAY_OUT_OF_SERVICE`. Payment is deliberately *not* gated at check-in — an `UNPAID` order may be checked in and serviced — because the money gate lives at completion instead. A `ServiceAdvisor` may cancel an appointment that is in either `SCHEDULED` or `RESCHEDULE_PENDING`, moving its `status` to `CANCELLED` and freeing the bay window. When the parent order completes, its linked `CHECKED_IN` appointment is driven to `COMPLETED` by the system as a side effect rather than by a direct call.

### 3.7. Moving the Vehicle Through Service and Paying for It

The fulfillment and payment axes converge during the service visit. On the payment side, a `ServiceAdvisor` authorizes payment on an order, moving `payment_status` from `UNPAID` to `AUTHORIZED`; this is permitted only once the order's `fulfillment_status` is `APPROVED`, because money is not authorized until pricing is final. The advisor may then capture an authorized payment, moving `payment_status` from `AUTHORIZED` to `PAID`. Capture may also happen automatically, as a completion side effect described below.

On the fulfillment side, a `Technician` starts service, moving `fulfillment_status` from `APPROVED` to `IN_SERVICE`; this requires that an appointment for the order already be in `CHECKED_IN`. The technician later completes the job, moving `fulfillment_status` from `IN_SERVICE` to `COMPLETED`. Completion is where the payment gate bites: an order may be completed only if its `payment_status` is `AUTHORIZED` or `PAID`, and an attempt to complete an order that is still `UNPAID` is rejected with `ERR_PAYMENT_REQUIRED`. Completion carries two side effects: the linked `CHECKED_IN` appointment is moved to `COMPLETED`, and, if `payment_status` was `AUTHORIZED`, it is captured to `PAID` in the same step.

Cancellation is the great unwinder. A `ServiceAdvisor` may cancel an order whose `fulfillment_status` is `DRAFT` or `APPROVED`, but an `APPROVED` order cannot be cancelled once any appointment for it is `CHECKED_IN` — the vehicle is on the rack and the work is underway. Cancellation requires `expected_work_order_version` to match the order's current `version`. The transition drives `fulfillment_status` to `CANCELLED` and performs a full compensation: every line that is not already `VOID` moves to `VOID`; for each `COMMITTED` `TIRE` line that had debited stock, the tire model's `stock_qty` is restocked by the line's `quantity`; any `ACTIVE` `RoadHazardWarranty` on the order is voided; if `store_credit_applied_cents` was greater than zero, that amount is refunded to the customer's `store_credit_cents`; any `SCHEDULED` or `RESCHEDULE_PENDING` appointment for the order is moved to `CANCELLED`, freeing its bay window; and if `payment_status` was `AUTHORIZED`, it is moved to `REFUNDED`. The order's `version` is incremented by one. These compensations are exactly the inverses of the approval side effects, so cancellation conserves catalog stock and customer credit.

### 3.8. Special Orders for Out-of-Stock Tires

When a tire line cannot be filled from stock, an `InventoryManager` or `ServiceAdvisor` places a special order. A `SpecialOrder` names the triggering `work_order_line_id` and the back-ordered `tire_model_id`, and states the `requested_quantity` to procure, which must be at least one. At creation a non-refundable `deposit_cents` is collected and the order is born `ORDERED`. The deposit is a percentage of the goods value, floored: the goods value is the tire model's `unit_price_cents` multiplied by the `requested_quantity`; the percentage term is that goods value multiplied by the deposit rate of 25 percent, rounded half up to a whole cent; and `deposit_cents` is the greater of that rounded percentage term and a minimum deposit of 2000 cents. Special orders can be fetched and listed, filterable by `work_order_line_id`, `tire_model_id`, and `status`.

A special order is a branch point with two terminal outcomes. When the goods arrive, the manager receives the order, moving its `status` from `ORDERED` to `RECEIVED`; receiving increments the tire model's `stock_qty` by the `requested_quantity`, and the linked work-order line becomes eligible for stock debit at order approval. Alternatively, the manager may cancel the back-order, moving its `status` from `ORDERED` to `BACKORDER_CANCELLED`; the `deposit_cents` is forfeited and remains booked, and the linked work-order line is moved to `VOID` if its parent work order is still `DRAFT`.

### 3.9. Mileage-Warranty Claims and Dual-Variant Proration

When tires wear out before their rated mileage, a customer or advisor submits a mileage-warranty claim against the original tire line. A `MileageWarrantyClaim` names the worn line through `work_order_line_id`, snapshots the `tire_model_id`, and records the `measured_tread_32nds` remaining on the tires (which must be at least 2 and no more than the model's `original_tread_32nds`), the `miles_driven` on them (non-negative), the requested `payout_method` of `STORE_CREDIT` or `REFUND`, and the `claim_quantity` of tires being claimed (at least one). A new claim is born `SUBMITTED`. Claims can be fetched and listed, filterable by `work_order_line_id`, `tire_model_id`, and `status`.

A `ServiceAdvisor` adjudicates. Approval requires the claim to be `SUBMITTED` and the covered line's `line_status` to be `COMMITTED` — a claim can only be approved against a tire line that was actually sold, that is, whose order was approved; otherwise the request is rejected with `ERR_INVALID_STATE`. Two eligibility guards then apply. The tire must still be within its mileage warranty: the model's `mileage_warranty_miles` must be greater than zero and the claim's `miles_driven` must be strictly less than that mileage rating; a tire whose driven mileage has reached or passed its rating is rejected with `ERR_MILEAGE_EXCEEDED`. And the tire must be genuinely worn out: the `measured_tread_32nds` must be at or below the wear bar of 2 thirty-seconds of an inch, and the model must carry a mileage warranty at all (`mileage_warranty_miles` greater than zero); a tire whose tread is still above the wear bar, or whose model offers no mileage warranty, is rejected with `ERR_NOT_WORN_TO_BAR`.

On approval the system computes the payout into `prorated_credit_cents` and moves the claim's `status` from `SUBMITTED` to `APPROVED`; if an `ACTIVE` road-hazard warranty exists on the same line, it is consumed to `CLAIMED` at this point. The proration has two defined bases that yield different credits for the same tire, and the system always applies the mileage-based variant. Under the mileage-based variant, the used fraction is the claim's `miles_driven` divided by the model's `mileage_warranty_miles`, the remaining fraction is one minus that used fraction, the per-tire credit is the model's current `unit_price_cents` multiplied by the remaining fraction and rounded half up to a whole cent, and `prorated_credit_cents` is that per-tire credit multiplied by the `claim_quantity` — rounding the per-tire figure first and only then multiplying by quantity. The documented alternative, the tread-based variant, is *not* applied by the system but is recorded here for completeness: it would compute the used fraction as the worn tread (the model's `original_tread_32nds` minus the claim's `measured_tread_32nds`) divided by the usable tread (the model's `original_tread_32nds` minus the wear bar of 2), take one minus that as the remaining fraction, and otherwise round and multiply identically. The two diverge whenever wear is not proportional to mileage. A `ServiceAdvisor` may instead reject a `SUBMITTED` claim, moving its `status` to `REJECTED`.

Finally, the advisor pays an `APPROVED` claim, moving its `status` to `PAID`. If the claim's `payout_method` is `STORE_CREDIT`, the customer who owns the claimed line's work order has their `store_credit_cents` credited by `prorated_credit_cents`. If the `payout_method` is `REFUND`, an external refund is booked and the customer's `store_credit_cents` is left unchanged.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state transition, every restock or discontinue, and every approval, payment, or claim action — return `200 OK`. Reconstruct each endpoint's request body, response shape, and side effects from the workflow narratives in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | ServiceAdvisor |
| GET | `/customers/{id}` | Fetch a customer (includes store credit) | ServiceAdvisor, Customer |
| POST | `/vehicles` | Register a vehicle for a customer | ServiceAdvisor, Customer |
| GET | `/vehicles/{id}` | Fetch a vehicle | ServiceAdvisor, Customer |
| GET | `/vehicles` | List vehicles, optionally by owner | ServiceAdvisor, Customer |
| POST | `/tire-models` | Create a catalog tire model | InventoryManager |
| GET | `/tire-models/{id}` | Fetch a tire model | InventoryManager, ServiceAdvisor, Customer |
| GET | `/tire-models` | List/search catalog tire models | InventoryManager, ServiceAdvisor, Customer |
| POST | `/tire-models/{id}/restock` | Adjust on-hand stock for a tire model | InventoryManager |
| POST | `/tire-models/{id}/discontinue` | Mark a tire model discontinued | InventoryManager |
| POST | `/fitment-rules` | Declare that a tire model fits a vehicle | InventoryManager |
| GET | `/fitment-rules/{id}` | Fetch a single fitment rule | InventoryManager, ServiceAdvisor, Customer |
| GET | `/fitment-rules` | List fitment rules | InventoryManager, ServiceAdvisor, Customer |
| POST | `/service-bays` | Create a service bay | InventoryManager |
| GET | `/service-bays/{id}` | Fetch a service bay | InventoryManager, ServiceAdvisor, Technician |
| GET | `/service-bays` | List service bays | InventoryManager, ServiceAdvisor, Technician |
| POST | `/service-bays/{id}/close` | Take a bay out of service | InventoryManager |
| POST | `/service-bays/{id}/reopen` | Return a bay to service | InventoryManager |
| POST | `/work-orders` | Open a draft work order | ServiceAdvisor, Customer |
| GET | `/work-orders/{id}` | Fetch a work order with computed pricing | ServiceAdvisor, Customer, Technician |
| GET | `/work-orders` | List work orders | ServiceAdvisor, Customer |
| POST | `/work-orders/{id}/lines` | Add a line item to a draft work order | ServiceAdvisor, Customer |
| GET | `/work-orders/{id}/lines` | List line items of a work order | ServiceAdvisor, Customer, Technician |
| GET | `/work-order-lines/{id}` | Fetch a single work order line | ServiceAdvisor, Customer, Technician |
| GET | `/work-order-lines` | List work order lines | ServiceAdvisor, Customer, Technician |
| POST | `/work-orders/{id}/approve` | Approve a draft order; finalize pricing and commit | ServiceAdvisor |
| POST | `/work-orders/{id}/authorize-payment` | Authorize payment on an approved order | ServiceAdvisor |
| POST | `/work-orders/{id}/capture-payment` | Capture an authorized payment | ServiceAdvisor |
| POST | `/work-orders/{id}/start-service` | Begin bay service | Technician |
| POST | `/work-orders/{id}/complete` | Complete service; auto-capture; complete appointment | Technician |
| POST | `/work-orders/{id}/cancel` | Cancel a draft or approved order with compensation | ServiceAdvisor |
| GET | `/road-hazard-warranties/{id}` | Fetch a road-hazard warranty | ServiceAdvisor, Customer |
| GET | `/road-hazard-warranties` | List road-hazard warranties | ServiceAdvisor, Customer |
| POST | `/appointments` | Book an install appointment | ServiceAdvisor, Customer |
| GET | `/appointments/{id}` | Fetch an appointment | ServiceAdvisor, Customer, Technician |
| GET | `/appointments` | List appointments | ServiceAdvisor, Customer, Technician |
| POST | `/appointments/{id}/request-reschedule` | Request a reschedule; release the slot | Customer, ServiceAdvisor |
| POST | `/appointments/{id}/confirm-reschedule` | Confirm a new interval | ServiceAdvisor |
| POST | `/appointments/{id}/check-in` | Check in the vehicle | Technician |
| POST | `/appointments/{id}/cancel` | Cancel an appointment and free the slot | ServiceAdvisor |
| POST | `/special-orders` | Place a special order for a back-ordered line | InventoryManager, ServiceAdvisor |
| GET | `/special-orders/{id}` | Fetch a special order | InventoryManager, ServiceAdvisor |
| GET | `/special-orders` | List special orders | InventoryManager, ServiceAdvisor |
| POST | `/special-orders/{id}/receive` | Mark goods received; restock | InventoryManager |
| POST | `/special-orders/{id}/cancel-backorder` | Cancel an unreceived special order | InventoryManager |
| POST | `/mileage-claims` | Submit a mileage-warranty claim | ServiceAdvisor, Customer |
| GET | `/mileage-claims/{id}` | Fetch a mileage-warranty claim | ServiceAdvisor, Customer |
| GET | `/mileage-claims` | List mileage-warranty claims | ServiceAdvisor, Customer |
| POST | `/mileage-claims/{id}/approve` | Approve a claim; run proration | ServiceAdvisor |
| POST | `/mileage-claims/{id}/reject` | Reject a claim | ServiceAdvisor |
| POST | `/mileage-claims/{id}/pay` | Pay an approved claim | ServiceAdvisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_VEHICLE_NOT_OWNED` | 422 |
| `ERR_LINE_TYPE_FIELD_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FITMENT_NOT_APPROVED` | 422 |
| `ERR_BAY_NOT_ALIGNMENT_CAPABLE` | 422 |
| `ERR_BAY_OUT_OF_SERVICE` | 409 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_BAY_TIME_CONFLICT` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 422 |
| `ERR_MILEAGE_EXCEEDED` | 422 |
| `ERR_NOT_WORN_TO_BAR` | 422 |
| `ERR_PAYMENT_REQUIRED` | 402 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_STALE_BAY_VERSION` | 412 |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_NEGATIVE_STOCK` | 422 |
