# Appliance Repair & Extended-Warranty Service API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Appliance Repair & Extended-Warranty Service API, a back-office and field-operations platform in the spirit of a national home-services network. The system coordinates the full journey of an appliance repair: a homeowner registers an appliance and opens a service request, a dispatcher books a technician into a timed dispatch window, the technician diagnoses the fault and produces a priced estimate, the customer approves or declines it, parts are drawn from truck stock or ordered from a depot, and the repair is either completed on the first visit or deferred to a callback. Layered across this workflow are three cost-bearing concerns that must stay perfectly reconciled at all times: warranty coverage (manufacturer, extended, and home-warranty contracts), truck-stock inventory reservations, and the diagnostic-fee-and-labor accounting that ultimately determines what the customer owes.

The domain is deliberately unforgiving about consistency. A safety recall can be activated at any moment and must instantly ripple outward — flagging every matching appliance, freezing in-flight repairs, cancelling their appointments, and unwinding any warranty commitments and part reservations they had accrued. Money is tracked to the cent, warranty ledgers must never drift, and a technician's truck can never promise more parts than it physically carries. The API is the single source of truth for all of these invariants, and every rule below exists to keep the operational, fiscal, and safety pictures aligned as the work moves through its many states.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, cross-cutting principles, and request-processing rules that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `Technician`, `Dispatcher`, and `ServiceAdmin`.

Two of these roles are tied to persisted entities, and their identity governs ownership checks:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a customer compare the resource's `customer_id` to `X-User-ID` — for example, a service request may only be paid for or have its estimate decided by the customer whose `customer_id` it carries.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`. Ownership checks compare the relevant technician foreign key to `X-User-ID` — a diagnosis, revision, completion, or second-trip may only be performed by the technician recorded in the request's `assigned_technician_id`, a truck-stock line may only be created by the technician named in its `technician_id`, and a duty-status toggle may only be performed by the technician named in the path.

The other two roles are operator identities not backed by any persisted entity:

- When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; a dispatcher acts across all customers and technicians when scheduling.
- When `X-User-Role` is `ServiceAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. `ServiceAdmin` is the superset back-office operator and is not subject to entity-ownership comparison.

A `Customer` may register their own appliances, open their own service requests, exclusively approve or decline the estimate on their own request, and record payments against their own request. A `Technician` exclusively records diagnoses, issues revised estimates, completes repairs, and orders depot parts (second-trip), and may manage their own truck stock and duty status. A `Dispatcher` exclusively books dispatch appointments and may create service zones and advance parts orders. A `ServiceAdmin` exclusively creates customers, catalog parts, warranty contracts, technicians, and recall notices and drives recall activation/rescission, and additionally may perform any of the shared operations (registering appliances, opening requests, recording payments, creating truck stock, toggling technician status, creating zones, advancing parts orders). All roles may perform read (GET) operations.

Requests are evaluated through a fixed validation pipeline, and the earliest failing stage determines the error returned. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the operation (`ERR_UNAUTHORIZED`); (3) existence of every referenced resource (`ERR_NOT_FOUND`); (4) the target resource being in a state that permits the transition (`ERR_INVALID_STATE`); (5) for a decision, the estimate being pending (`ERR_ESTIMATE_NOT_PENDING`); (6) ownership of the resource by the acting entity-backed user (`ERR_NOT_OWNER`); (7) the appliance being free of an active recall (`ERR_SAFETY_RECALL_HOLD`); (8) the assigned technician being on duty (`ERR_TECHNICIAN_OFF_DUTY`); (9) all parts orders being received when rescheduling from awaiting-parts (`ERR_PARTS_NOT_READY`); (10) the technician being free of a timeline conflict (`ERR_TECH_DOUBLE_BOOKED`); (11) the zone not exceeding its concurrent-window capacity (`ERR_ZONE_CAPACITY_EXCEEDED`); (12) truck-stock line uniqueness (`ERR_DUPLICATE_TRUCK_STOCK`); (13) sufficient available truck stock at approval (`ERR_INSUFFICIENT_TRUCK_STOCK`); (14) payment amount matching what is owed (`ERR_PAYMENT_AMOUNT_MISMATCH`); and (15) the optimistic-concurrency version match on estimate revision (`ERR_STALE_VERSION`). A request whose body is structurally malformed — a missing required field, an unrecognized enum value, or a dispatch window whose end is not strictly after its start — is rejected with `ERR_VALIDATION` (HTTP 400).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may not be less than 1, and may not exceed 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every entity in this system — `Customer`, `Appliance`, `WarrantyContract`, `Part`, `Technician`, `TruckStockItem`, `ServiceZone`, `ServiceRequest`, `Appointment`, `Estimate`, `PartsOrder`, `Payment`, and `RecallNotice` — is a first-class resource that carries the same set of system-managed fields:

- `id`: a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment of creation.
- `updated_at`: an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version`: an integer that begins at 1 on creation and increments by 1 on every mutation. It is the basis for optimistic concurrency control described in §2.7.

Whenever a computed or derived field on a resource changes — for instance an appliance's `recall_status` or `health_score`, a warranty contract's `claimed_cents`, or a service request's `warranty_covered_cents` — that change is itself a mutation: it refreshes the resource's `updated_at` and increments its `version`. A newly created service request is created with `status` `INTAKE` and `version` 1.

Path parameters are the UUIDs embedded in a resource address. For any endpoint whose path names more than one resource (for example an action sub-path under a specific service request), the identifiers are validated for existence left-to-right, and the first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404) before any deeper validation runs. This principle is described further in §2.8.

### 2.5. Monetary Precision and Cent-Based Arithmetic

All money in this system is expressed and stored as an integer number of cents; there are no fractional cents and no floating-point money. Catalog prices (`unit_price_cents`), deductibles (`deductible_cents`), coverage caps (`coverage_cap_cents`), labor charges, diagnostic fees, warranty-covered amounts, customer-responsibility amounts, payment amounts, and every `*_cents` field are integers. Rounding, where it occurs, is described precisely by the calculation that requires it (see §3.3 for labor rounding); no other rounding is applied. Because every amount is already an integer number of cents, comparisons and sums are exact.

### 2.6. Safety, Recall Cascades, and Hierarchical Consistency

Appliance safety is the highest business concern after authentication and authorization. Each `Appliance` carries a computed `recall_status` that is either `CLEAR` or `RECALLED`. An appliance is `RECALLED` exactly when at least one `RecallNotice` whose `status` is `ACTIVE` matches the appliance on both `brand` and `model`; otherwise it is `CLEAR`. At the moment an appliance is registered, its `recall_status` is set to `RECALLED` if a matching `ACTIVE` recall already exists, and to `CLEAR` otherwise.

A recall notice is created in the `ISSUED` state and moves through `ISSUED → ACTIVE → RESCINDED`. Activating a recall — transitioning it to `ACTIVE` — sets off a three-link cascade that must complete atomically. First, every `Appliance` matching the recall's `brand` and `model` has its `recall_status` set to `RECALLED`. Second, every non-terminal `ServiceRequest` on a now-recalled appliance is driven to `SAFETY_HOLD`, and in doing so any warranty claim and any part reservation that request had committed are reversed (the exact reversal is described in §3.7). Third, each such request's currently `BOOKED` `Appointment` is transitioned to `CANCELLED`, and the cancelled appointment releases the zone concurrent-window slot it had occupied. Rescinding a recall — transitioning it from `ACTIVE` to `RESCINDED` — sets matching appliances back to `recall_status` `CLEAR`, but only for appliances that have no other still-`ACTIVE` recall covering them. Rescission does not resume any held request: a `SAFETY_HOLD` service request is terminal and never auto-resumes.

This is one instance of a broader hierarchical-consistency rule. When a parent resource changes state in a way that invalidates dependent work, the system propagates the consequence to the children without a separate client call: cancelling an appointment releases its zone slot; a service request entering `SAFETY_HOLD` or any terminal state causes its open depot parts orders to be cancelled; completing a repair advances the appointment. Every such automatic propagation is a real mutation on each affected resource, refreshing its `updated_at` and incrementing its `version`.

### 2.7. Optimistic Concurrency on Estimate Revision

Issuing a revised estimate against a service request is guarded by optimistic concurrency control. The revision request must carry `expected_service_request_version`, a non-optional field holding the `version` of the target `ServiceRequest` the technician last observed. The server compares it against the request's current `version`. If they differ — meaning the request's version has advanced since it was read, for example because a prior revision already superseded the pending estimate and bumped the version — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the technician from acting on a stale view of the request. No other endpoint takes a version field; only the estimate-revision write is version-checked.

### 2.8. Nested Resource Retrieval and Validation Ordering

Read and action endpoints that address a specific resource by its `id` first confirm that the resource exists; a missing resource yields `ERR_NOT_FOUND` (HTTP 404). Where a path or body references several resources, existence is checked in path order, left-to-right, and the first unresolved reference is the one reported. Only once all referenced resources are confirmed to exist does the system proceed to state, ownership, safety, and business-rule checks in the order laid out in §2.1. This ordering guarantees that an invalid container is caught before any deeper, potentially misleading, processing occurs.

### 2.9. The Warranty Ledger and Truck-Stock Invariants

Two running ledgers must remain reconciled at every step, and both follow strict compensating discipline: any commitment made on the way in is exactly reversed if the work is later unwound.

Each `WarrantyContract` tracks `claimed_cents`, the cumulative warranty-covered amount committed against the contract, starting at 0. Its `remaining_coverage_cents` is always its `coverage_cap_cents` minus its `claimed_cents`. When an estimate is approved, the provisional warranty-covered amount is added to the covering contract's `claimed_cents`; when the repair completes, the claim is reconciled by adding the difference between the final covered amount and the previously committed provisional amount; and when a recall hold reverses an approved repair, the committed warranty-covered amount is subtracted back out of `claimed_cents`. A `WarrantyContract`'s `deductible_cents` defaults to 0 and must be exactly 0 when its `coverage_type` is `MANUFACTURER`.

Each `TruckStockItem` tracks `quantity_on_hand` (the physical units on the truck), `quantity_reserved` (units promised to approved repairs but not yet physically consumed, starting at 0), and the computed `quantity_available`, which is always `quantity_on_hand` minus `quantity_reserved`. Reserving a quantity adds it to `quantity_reserved`; releasing the same quantity subtracts it back out (the exact inverse of a reservation); and consuming a quantity subtracts it from both `quantity_on_hand` and `quantity_reserved`. A reservation is permitted only when `quantity_available` is greater than or equal to the requested quantity — the boundary is inclusive, so a truck with exactly the requested number available may reserve it. At most one truck-stock line may exist for any given pair of `technician_id` and `part_id`.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Customers, Appliances, Warranties, Catalog, and Field Resources

Before any repair can begin, the back office assembles the reference data. A `ServiceAdmin` creates a `Customer` by supplying `full_name`, `email`, `phone`, and `address`. The same admin, or a `Customer` acting for themselves, registers an `Appliance` under a `customer_id`, describing it with `brand`, `model`, `serial_number`, and `purchase_date` (an ISO date, `YYYY-MM-DD`, that later drives the appliance's age in its health score). Recall matching is performed on the `(brand, model)` pair, so those two fields are load-bearing for safety. A registered appliance exposes its computed `recall_status`, its `completed_repair_count` (the number of `COMPLETED` service requests that reference it), and its `health_score`.

A `ServiceAdmin` also curates the parts catalog and warranty book. A `Part` is created with a unique `part_number`, a human-readable `name`, and a `unit_price_cents`. A `WarrantyContract` is written against an `appliance_id` with a `coverage_type` of `MANUFACTURER`, `EXTENDED`, or `HOME_WARRANTY`; a `coverage_start` and `coverage_end` date; a `deductible_cents` (the per-repair deductible or trade-call fee, which must be 0 for `MANUFACTURER`); and a `coverage_cap_cents` (the lifetime coverage cap). On creation, the contract's `claimed_cents` is 0 and its `remaining_coverage_cents` equals its `coverage_cap_cents`. Coverage is considered active on a given service date when `coverage_start` is on or before that date and that date is on or before `coverage_end` — both ends inclusive.

Field capacity is modeled by three resources. A `Technician` is created with a `full_name` and begins with `status` `ON_DUTY`; the status enum is `ON_DUTY` or `OFF_DUTY`. A technician (for their own record) or a `ServiceAdmin` may toggle duty status by supplying a `to_status`, driving `ON_DUTY → OFF_DUTY` or `OFF_DUTY → ON_DUTY`; a technician may only toggle their own status, while a `ServiceAdmin` may toggle anyone's. A `TruckStockItem` records that a technician carries a part: it is created with a `technician_id`, a `part_id`, and a `quantity_on_hand`, and derives `quantity_reserved` (0 at creation) and `quantity_available` (equal to `quantity_on_hand` at creation). A `ServiceZone` is created with a `name` and a `max_concurrent_appointments`, the aggregate ceiling on how many `BOOKED` appointments whose windows overlap a given window the zone may hold at once. Appliances may be listed and filtered by `customer_id`; warranty contracts by `appliance_id`; truck-stock lines by `technician_id` and/or `part_id`.

### 3.2. Opening a Request and Booking the Dispatch Window

A `Customer` (or a `ServiceAdmin` on their behalf) opens a `ServiceRequest` by supplying a `customer_id`, an `appliance_id`, and a free-text `reported_issue`. The request is born in `INTAKE` with no technician yet assigned — its `assigned_technician_id`, `covering_contract_id`, and `warranty_routing` are null until later stages populate them (`warranty_routing` stays null through `INTAKE` and `SCHEDULED` and is first assigned a `coverage_type` or `NONE` at diagnosis per §3.3). Requests may be listed and filtered by `customer_id`, `appliance_id`, `assigned_technician_id`, `covering_contract_id`, and `status`.

A `Dispatcher` (or `ServiceAdmin`) books a dispatch appointment against the request, supplying a `technician_id`, a `zone_id`, and the window bounds `window_start` and `window_end`. Booking from `INTAKE` advances the request `INTAKE → SCHEDULED`; the same booking action is also how a callback visit is scheduled later, advancing `AWAITING_PARTS → SCHEDULED` (see §3.5). The window is a half-open interval `[window_start, window_end)`, and `window_end` must be strictly after `window_start`, otherwise the request is rejected with `ERR_VALIDATION`.

Several guards run before a booking is accepted. The appliance must not be under an active recall — a `RECALLED` appliance is rejected with `ERR_SAFETY_RECALL_HOLD`. The named technician must be `ON_DUTY`, or the booking is rejected with `ERR_TECHNICIAN_OFF_DUTY`. The technician must have no timeline conflict, and the zone must have room. When a booking succeeds, the system creates an `Appointment` with `status` `BOOKED` bound to the request, technician, zone, and window; sets the request's `assigned_technician_id` to the appointment's `technician_id`; and increments the request's `visit_count` by 1. The `visit_count` counts every `BOOKED` appointment ever created for the request across all visits.

A technician's schedule is protected by a buffered, pairwise conflict check applied across all `BOOKED` appointments belonging to that same technician. A proposed window conflicts with an existing one when the proposed `window_start` is earlier than the existing `window_end` plus a half-hour travel buffer of 30 minutes, and simultaneously the existing `window_start` is earlier than the proposed `window_end` plus that same 30-minute buffer. Any such conflict rejects the booking with `ERR_TECH_DOUBLE_BOOKED`; because the buffer is added on both sides, two appointments that abut within 30 minutes of each other still conflict.

Zone capacity is an aggregate check with no buffer. Among the `BOOKED` appointments already in the same zone, the system counts those that strictly overlap the proposed window — that is, appointments where the proposed `window_start` is earlier than the existing `window_end` and the existing `window_start` is earlier than the proposed `window_end`. If that overlap count plus the one new appointment would exceed the zone's `max_concurrent_appointments`, the booking is rejected with `ERR_ZONE_CAPACITY_EXCEEDED`. Overlap here is strict: two windows that merely touch end-to-end (a zero-length gap) do not count as overlapping. Appointments may be listed and filtered by `service_request_id`, `technician_id`, and `zone_id`.

### 3.3. Diagnosis: Warranty Routing, Health Score, and the Estimate

Once a technician is on site, the assigned technician records the diagnosis, advancing the request `SCHEDULED → DIAGNOSED`. Only the technician whose `id` equals the request's `assigned_technician_id` may do so, otherwise `ERR_NOT_OWNER`; the appliance must still be `CLEAR`, otherwise `ERR_SAFETY_RECALL_HOLD`; and no estimate may already exist for the request, otherwise `ERR_INVALID_STATE`. The diagnosis payload carries `labor_tasks` — an array of objects each shaped `{ minutes: <integer> }` — and `required_parts` — an array of objects each shaped `{ part_id: <string>, quantity: <integer> }`. Recording the diagnosis transitions the current `BOOKED` appointment to `COMPLETED` and creates an `Estimate` in `PENDING_APPROVAL`.

The **service date** used throughout diagnosis is the calendar date of the diagnosis appointment's `window_start`. Using that date, the system selects the covering warranty contract. It gathers every `WarrantyContract` for the request's appliance whose coverage is active on the service date — that is, where `coverage_start` is on or before the service date and the service date is on or before `coverage_end`, both ends inclusive. If there are no such contracts, `warranty_routing` is set to `NONE` and `covering_contract_id` stays null. If there are candidates, they are ranked by `coverage_type` with `MANUFACTURER` preferred first, then `EXTENDED`, then `HOME_WARRANTY`; ties within the same coverage type are broken by the earliest `created_at` in ascending order (never by `id`). The best candidate wins: `warranty_routing` becomes its `coverage_type` and `covering_contract_id` becomes its `id`. The request's provisional `diagnostic_fee_cents` is then set to 8900 cents (that is, an $89.00 diagnostic fee) when `warranty_routing` is `NONE`, and to 0 otherwise.

Diagnosis also captures the appliance's health at that moment into `health_score_at_diagnosis`. The health score starts from a baseline of 100 and subtracts penalties. First compute the appliance's age in whole years as the floor of the number of days between the `purchase_date` and the service date divided by 365. The raw score is 100, minus the age in years multiplied by 5, minus the number of prior repairs multiplied by 8, minus a further 20 if the appliance's `recall_status` is `RECALLED` (and nothing on that account if it is `CLEAR`). The stored score is that raw value clamped to lie between 0 and 100 inclusive — never below 0, never above 100. For `health_score_at_diagnosis`, the count of prior repairs is the number of this appliance's `COMPLETED` service requests and excludes the current in-flight request (which has not yet completed). The appliance's own `health_score` field is the post-completion form of the same computation and is recomputed when a repair completes, at which point the just-completed request is included in the prior-repair count — one more prior repair, lowering the score by a further 8 points relative to the at-diagnosis capture.

The estimate priced at diagnosis exposes a family of computed amounts. Its `estimated_parts_total_cents` is the sum, over each line in `required_parts`, of the referenced `Part`'s `unit_price_cents` multiplied by that line's `quantity`. Its `estimated_labor_total_cents` applies the labor rule to `labor_tasks`: for each task independently, take its `minutes`, divide by 15 and round up to the next whole quarter-hour, and multiply that number of quarter-hours by 3000 cents (a $30.00 charge per started quarter-hour); the estimate's labor total is the sum of those per-task charges. The rounding order is fixed — each task is rounded up on its own and only then are the tasks summed; summing the raw minutes first and rounding once would generally understate the labor and is not permitted. The `estimated_repair_subtotal_cents` is `estimated_parts_total_cents` plus `estimated_labor_total_cents`. The `estimated_diagnostic_fee_cents` is the provisional diagnostic assessment described below. The `estimated_total_cents` is the estimate-variant repair total: the repair subtotal plus the effective diagnostic fee. Finally, `estimated_customer_responsibility_cents` is the provisional customer out-of-pocket under the warranty rule described in §3.4.

The **diagnostic fee assessment** is a small tiered decision whose evaluation order matters, because it looks circular but is not. First the repair subtotal is computed as parts total plus labor cost. Then the effective diagnostic fee is decided from the subtotal tier and completion status — not from any grand total: if `warranty_routing` is anything other than `NONE`, the effective diagnostic fee is 0, because warranty routings waive it; otherwise, if the request has reached `COMPLETED` and the repair subtotal is at least 15000 cents ($150.00), the fee is waived to 0; otherwise the effective diagnostic fee is 8900 cents. The threshold is inclusive — a subtotal of exactly 15000 cents waives the fee. Only after the effective fee is known is the total formed as repair subtotal plus effective diagnostic fee. Because the waiver depends on completion, the estimate captured at diagnosis (where the request has not yet completed) carries the full 8900-cent effective fee whenever routing is `NONE`.

### 3.4. Warranty Responsibility, Estimate Revision, and the Customer Decision

The split between what warranty covers and what the customer owes follows a single tiered rule evaluated in a pinned order, taking as inputs the repair subtotal, the covering contract's remaining cap and deductible, the routing, and whether a recall applies. Begin by computing the contract's remaining cap as `coverage_cap_cents` minus `claimed_cents` (treat it as 0 when there is no covering contract). Then branch: if a recall applies to the appliance, both the warranty-covered amount and the customer responsibility are 0, because an active recall covers the repair entirely. Otherwise, if `warranty_routing` is `NONE`, the warranty-covered amount is 0 and the customer responsibility is the repair subtotal plus the effective diagnostic fee. Otherwise, if routing is `MANUFACTURER`, the warranty-covered amount is the smaller of the repair subtotal and the remaining cap, and the customer responsibility is the repair subtotal minus that covered amount — that is, only the overflow above the cap, with no deductible (manufacturer deductibles are always 0). Otherwise, when routing is `EXTENDED` or `HOME_WARRANTY`, the warranty-covered amount is again the smaller of the repair subtotal and the remaining cap, and the customer responsibility is the contract's `deductible_cents` plus the repair subtotal minus that covered amount. This rule is evaluated in a provisional form at approval (from the estimate's subtotal) and again in a final form at completion (from the actual subtotal).

Before the customer decides, the technician may replace the pending estimate with a revised one. Issuing a revised estimate supersedes the prior `PENDING_APPROVAL` estimate while the request stays in `DIAGNOSED`. The revision payload carries fresh `labor_tasks` and `required_parts` plus the `expected_service_request_version` for the optimistic-concurrency check of §2.7. When accepted, the prior estimate transitions `PENDING_APPROVAL → SUPERSEDED`, a new `Estimate` is created in `PENDING_APPROVAL` with its `estimated_*` amounts recomputed, and the request's `version` is incremented by 1. A revision whose `expected_service_request_version` does not match the request's current `version` is rejected with `ERR_STALE_VERSION`. Only the assigned technician may issue a revision.

The customer then renders a decision on the pending estimate by supplying a `decision` of either approve or decline; only the customer who owns the request may do so (`ERR_NOT_OWNER`), and the estimate must be `PENDING_APPROVAL` or the decision is rejected with `ERR_ESTIMATE_NOT_PENDING`. **Approving** drives the estimate `PENDING_APPROVAL → APPROVED` and the request `DIAGNOSED → APPROVED`. Approval first requires that the appliance is still `CLEAR` (`ERR_SAFETY_RECALL_HOLD`) and that, for every line in `required_parts`, the assigned technician's matching `TruckStockItem` has `quantity_available` greater than or equal to that line's `quantity`; if any part falls short the approval is rejected with `ERR_INSUFFICIENT_TRUCK_STOCK`. On success the system reserves parts — for each required line, adding its `quantity` to the technician's `quantity_reserved` — commits the warranty claim by adding the provisional `warranty_covered_cents` to the covering contract's `claimed_cents`, and stores the provisional `warranty_covered_cents` and `customer_responsibility_cents` onto the request. **Declining** drives the estimate `PENDING_APPROVAL → DECLINED` and the request `DIAGNOSED → DECLINED`; on decline no parts are reserved and no warranty is committed, and the request's `amount_due_cents` is set to its `diagnostic_fee_cents` — the diagnostic visit is owed even though the repair was refused. In both the approve and decline outcomes the decision endpoint returns the updated `Estimate` resource (not the `ServiceRequest`) in the response `data`.

### 3.5. Parts Fulfillment: Second Trip, Depot Orders, and the Callback Loop

Sometimes the needed part is not on the truck and must come from the depot. From an `APPROVED` request, the assigned technician initiates a second trip by supplying a `part_id` and a `quantity`, driving the request `APPROVED → AWAITING_PARTS`. Only the assigned technician may do this (`ERR_NOT_OWNER`). The action creates a `PartsOrder` in `ORDERED` for the requested depot part and cancels the current `BOOKED` appointment — transitioning it `BOOKED → CANCELLED` and releasing the zone concurrent-window slot it held, a transitive cascade caused by entering `AWAITING_PARTS`.

A depot parts order moves through a small cycle. A technician, dispatcher, or admin advances an order by supplying a `to_status`: `ORDERED → RECEIVED` when the part arrives, `ORDERED → BACKORDERED` when the depot cannot fill it yet, and `BACKORDERED → ORDERED` to retry — the order may loop between `ORDERED` and `BACKORDERED` any number of times before it is finally received. Parts orders may be listed and filtered by `service_request_id` and `part_id`. Independently of this cycle, if the parent service request reaches a terminal or hold state, any of its parts orders still in `ORDERED` or `BACKORDERED` are cancelled to `CANCELLED`.

Once every parts order on the request is `RECEIVED`, a dispatcher schedules the callback visit, driving the request `AWAITING_PARTS → SCHEDULED` through the same booking action described in §3.2 (supplying a `technician_id`, `zone_id`, `window_start`, and `window_end`). This reschedule additionally requires that every `PartsOrder` for the request is `RECEIVED`; if any is not, the booking is rejected with `ERR_PARTS_NOT_READY`. It is likewise subject to the recall check, the technician on-duty check, the technician timeline conflict check, and the zone capacity check. A successful callback booking creates a new `BOOKED` appointment, sets `assigned_technician_id`, and increments `visit_count`, exactly as an initial booking does — this is the cyclic return into `SCHEDULED`.

### 3.6. Completing the Repair and Reconciling Costs

The assigned technician completes the repair by supplying the `actual_labor_tasks` — the labor actually performed, in the same `{ minutes: <integer> }` shape as an estimate's tasks. Completion can occur two ways: directly from `APPROVED` on the same visit, transitioning `APPROVED → COMPLETED`; or from `SCHEDULED` on a callback visit, transitioning `SCHEDULED → COMPLETED`. In both cases only the assigned technician may complete (`ERR_NOT_OWNER`), and the appliance must still be `CLEAR` (`ERR_SAFETY_RECALL_HOLD`). Completing from a callback `SCHEDULED` additionally requires that an `APPROVED` estimate already exists for the request (the approval that preceded the second trip), otherwise `ERR_INVALID_STATE`.

Completion consumes and reconciles. For each line in the reserved `required_parts`, the technician's `TruckStockItem` has that `quantity` subtracted from both its `quantity_on_hand` and its `quantity_reserved`. The final labor total, `final_labor_total_cents`, is computed from `actual_labor_tasks` by the same per-task-rounded labor rule (each task's minutes divided by 15, rounded up, times 3000 cents, then summed), and `final_parts_total_cents` is the actual consumed-parts total from the reserved lines. Their sum is stored as `final_repair_subtotal_cents`. Because the final calculation uses the actual labor rather than the estimated labor, it diverges from the estimate whenever actual and estimated labor differ. The warranty split is then reconciled from the final subtotal: `warranty_covered_cents` is recomputed in its final form, and the covering contract's `claimed_cents` is adjusted by the difference between the final covered amount and the provisional covered amount committed at approval. The request's `customer_responsibility_cents` is recomputed from the final subtotal, and its `amount_due_cents` is set to that final customer responsibility. Recall that for a `NONE`-routed request the customer responsibility already folds in the effective diagnostic fee, and that a completed repair with routing `NONE` and a final subtotal of at least 15000 cents waives that fee.

Completion also advances the surrounding resources: the current `BOOKED` appointment transitions `BOOKED → COMPLETED`, and the appliance's `completed_repair_count` is incremented by 1, which in turn recomputes the appliance's `health_score` in its post-completion form (now counting the just-finished repair among the prior repairs).

### 3.7. Recalls, Safety Holds, and Compensating Reversals

A `ServiceAdmin` creates a `RecallNotice` with a `brand`, a `model`, and a safety `description`; it starts in `ISSUED`. Activation and rescission are performed by supplying a `to_status`, driving `ISSUED → ACTIVE` or `ACTIVE → RESCINDED`. Activation triggers the safety cascade of §2.6, and its effect on in-flight requests depends on how far the request had progressed. A non-terminal request on a newly recalled appliance is driven to `SAFETY_HOLD`, and its `BOOKED` appointment is cancelled with its zone slot released. If the held request had already been `APPROVED` — meaning it had reserved parts and committed a warranty claim — those commitments are compensated exactly: for each reserved `required_parts` line the reserved `quantity` is subtracted back out of the technician's `quantity_reserved`, and the committed `warranty_covered_cents` is subtracted back out of the covering contract's `claimed_cents`. Requests that had not yet reached approval carry no reservation or claim to unwind, so only their appointment and state change. The recall cascade reaches requests in `INTAKE`, `SCHEDULED`, `DIAGNOSED`, and `AWAITING_PARTS` alike; the only difference between them is whether an approved reservation and claim exist to reverse.

A `SAFETY_HOLD` is terminal. Rescinding the recall clears the appliance's `recall_status` back to `CLEAR` when no other active recall still matches it, but it does not lift the hold on any request that was already frozen.

### 3.8. Payment and Settlement

Finally, a `Customer` (or `ServiceAdmin` on their behalf) records a `Payment` against a request's outstanding balance by supplying an `amount_cents` and a `method` of `CARD`, `CHECK`, or `CASH`. The payment's `amount_cents` must equal the request's current `amount_due_cents`, otherwise the payment is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A recorded payment is created in `status` `RECORDED`, which is terminal. Payments may be listed and filtered by `service_request_id`. On a declined request the amount owed is the diagnostic fee; on a completed request it is the final customer responsibility — so the same settlement mechanism closes out both the repair-refused and repair-done paths.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`. Operations that modify or transition an existing resource — including status toggles, decisions, completion, second-trip, and recall/parts-order advancement — return `200 OK`. Read operations return `200 OK`. Reconstruct each endpoint's request body, response body, and side effects from the narratives in §3; the table below is intentionally limited to routing and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | ServiceAdmin |
| GET | `/customers/{id}` | Fetch a customer | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/appliances` | Register an appliance for a customer | Customer, ServiceAdmin |
| GET | `/appliances/{id}` | Fetch an appliance | Customer, Technician, Dispatcher, ServiceAdmin |
| GET | `/appliances` | List/lookup appliances (filter by `customer_id`) | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/warranty-contracts` | Create a warranty contract on an appliance | ServiceAdmin |
| GET | `/warranty-contracts/{id}` | Fetch a warranty contract | Customer, Technician, Dispatcher, ServiceAdmin |
| GET | `/warranty-contracts` | List warranty contracts (filter by `appliance_id`) | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/parts` | Create a catalog part | ServiceAdmin |
| POST | `/technicians` | Create a technician | ServiceAdmin |
| GET | `/technicians/{id}` | Fetch a technician | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/technicians/{id}/status` | Toggle technician duty status | Technician, ServiceAdmin |
| POST | `/truck-stock` | Create a truck-stock line for a technician+part | Technician, ServiceAdmin |
| GET | `/truck-stock/{id}` | Fetch a truck-stock line | Customer, Technician, Dispatcher, ServiceAdmin |
| GET | `/truck-stock` | List truck-stock lines (filter by `technician_id`, `part_id`) | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/service-zones` | Create a dispatch zone | ServiceAdmin, Dispatcher |
| POST | `/service-requests` | Open a service request | Customer, ServiceAdmin |
| GET | `/service-requests/{id}` | Fetch a service request | Customer, Technician, Dispatcher, ServiceAdmin |
| GET | `/service-requests` | List/lookup service requests | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/service-requests/{id}/appointments` | Schedule or reschedule a dispatch appointment | Dispatcher, ServiceAdmin |
| POST | `/service-requests/{id}/diagnose` | Record diagnosis; create the estimate | Technician |
| POST | `/service-requests/{id}/estimates` | Issue a revised estimate (OCC-guarded) | Technician |
| POST | `/service-requests/{id}/complete` | Complete the repair | Technician |
| POST | `/service-requests/{id}/second-trip` | Order a depot part; defer to a callback | Technician |
| POST | `/service-requests/{id}/payments` | Record a payment against amount due | Customer, ServiceAdmin |
| GET | `/estimates/{id}` | Fetch an estimate | Customer, Technician, Dispatcher, ServiceAdmin |
| GET | `/estimates` | List estimates (filter by `service_request_id`) | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/estimates/{id}/decision` | Approve or decline the pending estimate | Customer |
| GET | `/parts-orders/{id}` | Fetch a parts order | Customer, Technician, Dispatcher, ServiceAdmin |
| GET | `/parts-orders` | List parts orders (filter by `service_request_id`, `part_id`) | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/parts-orders/{id}/status` | Advance a depot parts order | Technician, Dispatcher, ServiceAdmin |
| GET | `/payments/{id}` | Fetch a payment | Customer, Technician, Dispatcher, ServiceAdmin |
| GET | `/payments` | List payments (filter by `service_request_id`) | Customer, Technician, Dispatcher, ServiceAdmin |
| GET | `/appointments/{id}` | Fetch an appointment | Customer, Technician, Dispatcher, ServiceAdmin |
| GET | `/appointments` | List appointments (filter by `service_request_id`, `technician_id`, `zone_id`) | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/recalls` | Create a recall notice | ServiceAdmin |
| GET | `/recalls/{id}` | Fetch a recall notice | Customer, Technician, Dispatcher, ServiceAdmin |
| POST | `/recalls/{id}/status` | Activate or rescind a recall | ServiceAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ESTIMATE_NOT_PENDING` | 409 Conflict |
| `ERR_SAFETY_RECALL_HOLD` | 409 Conflict |
| `ERR_TECHNICIAN_OFF_DUTY` | 409 Conflict |
| `ERR_PARTS_NOT_READY` | 409 Conflict |
| `ERR_TECH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_TRUCK_STOCK` | 409 Conflict |
| `ERR_INSUFFICIENT_TRUCK_STOCK` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
