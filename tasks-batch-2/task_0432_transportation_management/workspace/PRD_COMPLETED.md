# Transportation Management API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Transportation Management System (TMS) API, a back-office platform that carries freight from an inbound customer order all the way through to settlement. Shippers raise orders and break them into shipments; the platform rate-shops contract rates across a pool of carriers, tenders the work, consolidates shipments onto trucks, schedules dock appointments, tracks the freight in transit, audits the carrier's invoice against the contract, and adjudicates loss-and-damage claims. The system is built around two intertwined responsibilities. The first is a pricing engine: for every shipment it must choose the cheapest eligible carrier and reconcile a provisional freight quote against the carrier's eventual invoice. The second is a workflow spine that walks each shipment through tendering, booking, loading, dispatch, in-transit, delivery, audit, and claims, while keeping a fleet of derived figures — carrier scorecards, load weights, invoice variances — continuously consistent.

Operationally, four teams collaborate. Shipper operations own demand: orders, shipments, the decision to tender, and claim filing. Carrier operations own supply: the carrier roster, contract rates, tender responses, and the physical movements of departing and delivering. Dock operations own consolidation and the yard: building loads, scheduling doors, and dispatching trucks. Freight auditors own the money trail after delivery: invoice audit and claim adjudication. Because money in this domain is exact, every monetary amount is carried as an integer number of cents, and every weight as an integer number of pounds; there are no fractional currency units anywhere in the system.

A deterministic, integer minute-offset model underlies all scheduling. Promised delivery deadlines, rate effective windows, and dock appointment slots are all expressed as absolute minute offsets supplied directly by the caller, so the system's temporal behavior is fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across the entire API surface. The API is mounted under the `/tms` path prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or empty, the request is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly four roles, spelled precisely as `ShipperOps`, `CarrierOps`, `DockOps`, and `FreightAuditor`. When a role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`. A non-empty `X-User-Role` whose value is not one of these four recognized roles clears the authentication check but is never permitted on any endpoint, so it is likewise rejected with `ERR_FORBIDDEN_ROLE` — including on read (GET) endpoints, whose authorized set is exactly the four recognized roles.

For all four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. When `X-User-Role` is `ShipperOps`, `CarrierOps`, `DockOps`, or `FreightAuditor`, the server may record the identifier for auditing purposes, but it never compares `X-User-ID` to any entity's `id`, and ownership of a resource is never determined by matching the caller's identifier against a stored foreign key. Authorization is therefore purely role-based: what matters is which role the caller claims, not which specific user they are.

The role surfaces are disjoint by responsibility. A `ShipperOps` operator creates and cancels orders, creates and cancels shipments, initiates tendering (the rate-shop), and opens claims. A `CarrierOps` operator creates carriers, suspends and reinstates them, creates and retires contract rates, accepts and declines tenders, and drives physical execution by departing and delivering shipments. A `DockOps` operator creates loads, consolidates shipments onto them, dispatches and closes loads, and schedules, checks in, releases, and cancels dock appointments. A `FreightAuditor` operator records carrier invoices, audits, approves, and disputes them, and approves or denies claims. Expiring a tender is shared between `ShipperOps` and `CarrierOps`. All read (GET) endpoints and the logical clock control are available to every role.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` outside this range is clamped to the nearest bound rather than rejected: a value below 1 is treated as 1 and a value above 100 is treated as 100. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped to 0. When either `limit` or `offset` is supplied but cannot be parsed as an integer, the request is rejected with `ERR_INVALID_REQUEST`. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp, `created_at`, in ascending order, with ties broken by creation order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every primary resource in the system — carriers, contract rates, orders, shipments, tenders, loads, dock appointments, freight invoices, and claims — carries a system-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC value with three fractional digits. All of these entities are also mutable and therefore additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every change, and a `version` integer that begins at its initial value and increments by one with every mutation of the resource. There are no immutable, version-free entities in this domain; every entity listed above carries the full complement of `id`, `created_at`, `updated_at`, and `version`.

The platform maintains a logical UTC clock for determinism. At startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it never falls back to wall-clock time. An operator of any role may set the clock by supplying a `to_iso8601` instant; this is purely a test-driving capability and does not itself mutate any business resource. Note that the minute-offset fields used throughout scheduling and pricing are independent absolute integers supplied directly in request bodies; they are not derived from the logical clock.

### 2.5. Hierarchical Consistency and Automatic State Propagation

Several state changes bubble across entities without the client touching the affected resource directly. The most important is the order-to-shipment linkage: an order is born `OPEN`, advances to `PLANNED` the instant its first child shipment is created, and is automatically driven to `CLOSED` when that shipment reaches delivery. These order transitions are performed by the system, not requested explicitly. Whenever the server mutates a resource as part of such a cascade — whether the order being bubbled up, a carrier whose counters changed, a load whose consolidated weight was recomputed, or a tender swept along by a shipment cancellation — that resource independently has its `updated_at` refreshed and its `version` incremented, exactly as a direct mutation would.

Derived figures are reconciled immediately rather than lazily. A load's consolidated weight, a carrier's on-time percentage and scorecard grade, and an invoice's variance are all recomputed at the moment their inputs change and again whenever the owning resource is read, so a GET always reflects the current truth.

Each lifecycle entity exposes its current lifecycle position in a `status` field — carriers, contract rates, orders, tenders, loads, dock appointments, freight invoices, and claims each carry a single `status`, while a shipment is the one entity that splits its lifecycle across the two independent dimensions `tender_status` and `execution_status` instead of a single `status` field. The exact enumeration values each of these fields may take are given in the workflow narratives of §3.

### 2.6. Nested Resource Retrieval and Referential Existence

When a request targets a resource by an identifier in its path, that identifier must resolve to an existing resource or the request is rejected with the not-found error for that resource type — `ERR_CARRIER_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_TENDER_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_APPT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND` as appropriate. For paths that carry more than one identifier, the identifiers are validated left to right, and the first one that does not exist determines the error returned. Foreign-key identifiers supplied in a request body are subject to the same existence requirement: when a create call references another resource by id, a missing target yields that resource type's not-found error. This referential check applies to the body-supplied ids on shipment creation, contract-rate creation, load creation, dock-appointment creation, freight-invoice creation, claim creation, and the consolidation of a shipment onto a load.

### 2.7. Monetary and Weight Precision

All monetary fields are integer cents, and all weights are integer pounds; nothing is stored or returned as a fractional currency unit or fractional pound. Two computed values require rounding during their derivation. Fuel surcharge, computed as a fraction of the linehaul charge, is rounded to a whole number of cents using the round-half-up convention before it is added into any total. A carrier's on-time percentage is rounded half up to two decimal places. Every other arithmetic step in the system operates on integers and produces integers.

### 2.8. Validation Ordering

When a single endpoint is guarded by several checks, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: first, presence of the authentication headers (`ERR_MISSING_USER_CONTEXT`); second, role authorization (`ERR_FORBIDDEN_ROLE`); third, existence of every resource id named in the path, validated left to right (the appropriate not-found error); fourth, existence of every foreign-key id supplied in the body (the appropriate not-found error); fifth, structural validity of the body — required fields present and well-typed, enum values within their allowed sets, and the positivity and ordering constraints described elsewhere in this document (`ERR_INVALID_REQUEST`); and only then the domain-specific business rules — uniqueness, mode and weight referential checks, state preconditions, cross-entity guards, temporal overlaps, capacity, tolerance, and concurrency. In short, authentication precedes authorization, which precedes existence, which precedes structural validation, which precedes business logic. Within the business tier, a resource's state precondition is checked before the cross-entity and quantitative guards layered on top of it.

### 2.9. Optimistic Concurrency on Load Consolidation

Consolidating a shipment onto a load is the one operation in this system that is guarded by optimistic concurrency control. The consolidation request must carry an `expected_load_version` field carrying the client's last observed `version` of the target load. If that value does not equal the load's current `version`, the request is rejected with `ERR_STALE_LOAD_VERSION` and HTTP status 412. The rationale is that a prior consolidation onto the same load legitimately raised its consolidated weight and bumped its `version`; a client that read the load before that change holds a stale view of the remaining capacity headroom, and a capacity decision made against the outdated version must not be committed. This is the only endpoint that accepts a version field; no other write in the system takes one.

## 3. Business Logic & Workflows

### 3.1. The Carrier Roster and Its Scorecard

A `CarrierOps` operator registers a carrier with a legal `name`, a `scac` (the Standard Carrier Alpha Code), and a `mode` drawn from `TL`, `LTL`, `PARCEL`, or `INTERMODAL`. The `scac` must be unique across all carriers; a collision is rejected with `ERR_DUPLICATE_SCAC`. A new carrier starts `ACTIVE`, with its `delivered_count`, `on_time_count`, and `claim_count` all initialized to zero, its `on_time_pct` null, and its `scorecard_grade` at `PROBATION`. Carriers move between `ACTIVE` and `SUSPENDED` through the state machine: suspending a carrier requires it to currently be `ACTIVE`, otherwise `ERR_CARRIER_NOT_ACTIVE`; reinstating one requires it to currently be `SUSPENDED`, otherwise `ERR_CARRIER_NOT_SUSPENDED`. A suspended carrier is excluded from rate-shop consideration but is otherwise untouched.

Three counters drive the carrier's reputation. The `delivered_count` records how many of its shipments have reached delivery; `on_time_count` records how many of those arrived on or before their promised deadline; and `claim_count` records how many claims have been filed against its shipments. From these the system derives two read-only fields, recomputed on every relevant transition and on every read of the carrier. The `on_time_pct` is the on-time count divided by the delivered count, multiplied by 100 and rounded half up to two decimal places, but only when the delivered count is greater than zero; when no deliveries have occurred it is null. A claim ratio — the claim count divided by the delivered count, or zero when there have been no deliveries — is computed for grading but not stored as a field. The `scorecard_grade` is then assigned by evaluating these conditions from the top, taking the first that matches: if the delivered count is zero, the grade is `PROBATION`; otherwise, if the on-time percentage is at least 95 and the claim ratio is at most 0.02, the grade is `A`; otherwise, if the on-time percentage is at least 90 and the claim ratio is at most 0.05, the grade is `B`; otherwise, if the on-time percentage is at least 80, the grade is `C`; and failing all of these, the grade is `PROBATION`. Every threshold boundary here is inclusive.

### 3.2. Contract Rates and Their Effective Windows

Contract rates are the price book the rate-shop draws from. A `CarrierOps` operator creates a rate against a carrier by supplying `carrier_id`, a `mode`, an `origin_zone` and `dest_zone` lane, a `base_rate_per_mile_cents` linehaul rate, a `min_charge_cents` floor, an optional `fuel_surcharge_pct` (a fraction such that 0.15 means fifteen percent, defaulting to 0 when omitted), and the effective window endpoints `effective_start_minute` and `effective_end_minute`. The rate's `mode` must equal the carrier's own mode, or the request is rejected with `ERR_MODE_MISMATCH`. The window is a closed interval of minute offsets: the end must be greater than or equal to the start (so a one-minute window where start equals end is valid), and the start must be at least zero. A rate is created `ACTIVE`; it may later be retired by a `CarrierOps` operator, which requires the rate to currently be `ACTIVE` (else `ERR_RATE_NOT_ACTIVE`) and moves it to `RETIRED`. A retired rate is excluded from rate-shopping but remains referenced by any shipment already booked against it.

Effective windows on the same lane may not collide. Because a contract rate's window is closed, two `ACTIVE` rates on the same carrier, mode, origin zone, and destination zone lane overlap if their inclusive intervals share any minute at all — including the case where one window's endpoint minute coincides with the other's endpoint minute. When a newly created `ACTIVE` rate's closed window `[effective_start_minute, effective_end_minute]` would overlap an existing `ACTIVE` rate on the same lane in this sense, the create is rejected with `ERR_RATE_WINDOW_OVERLAP`. This closed-interval semantics is deliberately stricter than the half-open semantics used for dock appointments described later — for rates, sharing an endpoint minute is an overlap.

### 3.3. Orders and Shipments

A shipper begins with an order. A `ShipperOps` operator creates one by supplying a `customer_ref`, the `origin_zone` and `dest_zone`, a `weight_lbs` total weight (which must be greater than zero), and a `declared_value_cents` declared cargo value (which must also be greater than zero, and which later serves as the ceiling on any claim). The order opens in the `OPEN` state. While it is still `OPEN`, the shipper may cancel it, which requires the order to be `OPEN` (otherwise `ERR_ORDER_NOT_CANCELLABLE`) and moves it to `CANCELLED`. As described in §2.5, the order leaves `OPEN` for `PLANNED` automatically the moment its first shipment is created, and it is driven from `PLANNED` to `CLOSED` automatically when that shipment is delivered.

From an order a `ShipperOps` operator carves shipments. Creating a shipment requires the `order_id` it fulfills, a `mode`, a `distance_miles` routed linehaul distance (greater than zero), a `weight_lbs` shipment weight, and a `promised_eta_minute` delivery deadline expressed as an absolute minute offset. The shipment weight must be greater than zero and must not exceed the parent order's own weight; a shipment heavier than its order is rejected with `ERR_MODE_MISMATCH`. The shipment's `mode` must be one of the four transport-mode enum values. A new shipment is created with two independent status dimensions: a `tender_status` that starts at `UNTENDERED` and a separate `execution_status` that starts at `PENDING`. These two dimensions advance in parallel and are independent of one another up until cancellation. Several other fields begin empty and are filled in only as the workflow progresses: `load_id` (set when the shipment is consolidated, null otherwise), `assigned_carrier_id` and `contract_rate_id` (set when a tender is accepted, null before), `quoted_cost_cents` (the provisional freight cost locked at acceptance), `audited_cost_cents` (the final freight cost, null until audit), and `actual_delivery_minute` (the minute delivery fired, null before delivery).

### 3.4. Rate Shopping and the Tender Offer

Tendering is where the pricing engine selects a carrier. A `ShipperOps` operator initiates a tender against a shipment by supplying the `tender_minute` at which the tender is being created. The shipment must be in `execution_status` `PENDING` (otherwise `ERR_SHIPMENT_NOT_PENDING`) and `tender_status` `UNTENDERED` (otherwise `ERR_SHIPMENT_ALREADY_TENDERED`). The server then rate-shops: it builds a candidate set of contract rates and chooses one deterministically.

A contract rate is a candidate only if all of the following hold: the rate's status is `ACTIVE`; the rate's mode equals the shipment's mode; the rate's origin zone equals the shipment's order's origin zone and the rate's destination zone equals that order's destination zone; the supplied `tender_minute` falls within the rate's closed effective window, meaning it is at least the effective start minute and at most the effective end minute; the rate's carrier is `ACTIVE`; and that carrier's mode equals the shipment's mode. For each candidate, the server prices it: the linehaul charge is the larger of the rate's per-mile rate multiplied by the shipment's distance in miles and the rate's minimum charge floor; the fuel charge is the linehaul multiplied by the rate's fuel surcharge fraction, rounded half up to a whole number of cents; and the priced cost is the linehaul plus the fuel. The server then ranks the candidates and chooses the one with the lowest priced cost. Ties are broken first in favor of the carrier with the higher on-time percentage, where a null on-time percentage is treated as -1 and therefore ranks last; if a tie remains, it is broken in favor of the candidate contract rate with the earliest `created_at`. The resource id is never used as a ranking input. If the candidate set is empty, the tender create is rejected with `ERR_NO_ELIGIBLE_CARRIER`.

The selected carrier and rate are written onto the new tender as its `carrier_id` and `contract_rate_id`, and the priced cost is recorded as the tender's `offered_rate_cents`. The tender is created in the `OFFERED` state, and creating it automatically advances the shipment's `tender_status` from `UNTENDERED` to `TENDERED`.

### 3.5. Tender Disposition: Accept, Decline, Expire

A `CarrierOps` operator accepts an offered tender. Acceptance requires the tender to be `OFFERED` (otherwise `ERR_TENDER_NOT_OFFERED`) and the shipment to be in `tender_status` `TENDERED` (otherwise `ERR_SHIPMENT_NOT_TENDERED`). Acceptance moves the tender `OFFERED → ACCEPTED` and books the shipment, advancing its `tender_status` from `TENDERED` to `BOOKED`. Booking writes the accepted tender's carrier onto the shipment's `assigned_carrier_id` and the accepted tender's rate onto the shipment's `contract_rate_id`, and it locks the provisional freight cost into `quoted_cost_cents`. That quoted cost is computed from the accepted tender's contract rate in a pinned order: first the linehaul as the larger of the per-mile rate times the shipment distance and the minimum charge floor; then the fuel as that floored linehaul times the fuel surcharge fraction, rounded half up to whole cents; then a flat provisional accessorial reserve of 5000 cents; and finally the quoted cost as the sum of linehaul, fuel, and that 5000-cent reserve. The floor is applied to the linehaul before fuel is computed; computing fuel before flooring would diverge and is incorrect.

Two other dispositions release the shipment. A `CarrierOps` operator may decline an offered tender, and a `ShipperOps` or `CarrierOps` operator may expire one; either requires the tender to be `OFFERED` (otherwise `ERR_TENDER_NOT_OFFERED`). Declining moves the tender `OFFERED → DECLINED` and expiring moves it `OFFERED → EXPIRED`. Both carry the same side effect: the shipment's `tender_status` reverts from `TENDERED` to `UNTENDERED`, making it re-tenderable. When a shipment is reverted this way it carries no carrier assignment — its `assigned_carrier_id` and `quoted_cost_cents` remain null until a future tender is accepted.

### 3.6. Consolidation onto Loads

Loads are the trucks. A `DockOps` operator creates a load against a hauling carrier by supplying `carrier_id` and a `planned_capacity_lbs` maximum weight (greater than zero). The load opens `BUILDING`, with its `consolidated_weight_lbs` at zero. The consolidated weight is always the sum of `weight_lbs` over every shipment whose `load_id` points at this load and whose `execution_status` is not `CANCELLED`; it is recomputed whenever a shipment is added or detached and on every read of the load.

Adding a shipment to a load is permitted only while the load is `BUILDING`; an attempt on a non-building load is rejected with `ERR_LOAD_NOT_BUILDING`. The shipment being added must be a booked shipment that is not already on a load, otherwise `ERR_SHIPMENT_NOT_ON_BUILDING_LOAD`. The request carries the `shipment_id` to add and, as described in §2.9, the `expected_load_version` for the optimistic concurrency check; a mismatch with the load's current version yields `ERR_STALE_LOAD_VERSION`. The capacity guard then applies: if the load's consolidated weight before the add, plus the incoming shipment's weight, would be greater than the load's planned capacity, the add is rejected with `ERR_LOAD_CAPACITY_EXCEEDED`. A new total exactly equal to the planned capacity is allowed; the rejection fires strictly when the new total would exceed capacity. A successful add sets the shipment's `load_id` to this load, recomputes the consolidated weight, and increments the load's version by one; the response body for this consolidation call is the updated load resource (carrying its new `version` and recomputed `consolidated_weight_lbs`), not the shipment. The conserved property is that the total non-cancelled weight assigned to a load always equals its consolidated weight, so adding a shipment and later cancelling it returns the load to its pre-add weight.

### 3.7. The Yard: Dock Appointments and Dispatch

Before a load can roll, it needs a dock slot. A `DockOps` operator schedules a dock appointment by supplying the `load_id` arriving, a `dock_door` identifier, and a half-open time window given by `start_minute` and `end_minute`. The start must be at least zero and the end must be strictly greater than the start. The window is half-open, written `[start_minute, end_minute)`: it includes the start minute but not the end minute. Appointments on the same door may not overlap, but because the window is half-open, two appointments that merely touch at a boundary — one ending exactly where the next begins — do not overlap. A new appointment whose window overlaps an existing `SCHEDULED` or `CHECKED_IN` appointment on the same `dock_door` is rejected with `ERR_DOCK_DOUBLE_BOOKED`. This half-open rule is deliberately looser than the closed-interval rule for contract rate windows in §3.2.

An appointment opens `SCHEDULED`. A `DockOps` operator checks it in, requiring it to be `SCHEDULED` (otherwise `ERR_APPT_NOT_SCHEDULED`), moving it `SCHEDULED → CHECKED_IN`. A checked-in appointment may be released, requiring it to be `CHECKED_IN` (otherwise `ERR_APPT_NOT_CHECKED_IN`), moving it `CHECKED_IN → RELEASED` and freeing its window on the door for future appointments. A scheduled appointment may instead be cancelled, requiring it to be `SCHEDULED` (otherwise `ERR_APPT_NOT_SCHEDULED`), moving it `SCHEDULED → CANCELLED` and likewise freeing its window. Both release and cancel free the door window; a released or cancelled appointment no longer participates in overlap checks.

Dispatch is the gate from yard to road. A `DockOps` operator dispatches a load, which requires the load to be `BUILDING` (otherwise `ERR_LOAD_NOT_BUILDING`), to carry a positive consolidated weight — that is, at least one non-cancelled shipment is consolidated, otherwise `ERR_EMPTY_LOAD` — and to have at least one `SCHEDULED` or `CHECKED_IN` dock appointment, otherwise `ERR_NO_DOCK_APPOINTMENT`. A successful dispatch moves the load `BUILDING → DISPATCHED`. Later, once the freight has all arrived, a `DockOps` operator closes the load, which requires it to be `DISPATCHED` (otherwise `ERR_LOAD_NOT_DISPATCHED`) and requires every non-cancelled shipment on the load to have reached `DELIVERED` (otherwise `ERR_LOAD_HAS_UNDELIVERED_SHIPMENTS`), moving it `DISPATCHED → CLOSED`. Closing a load is always a manual step; the system never closes a load on its own when its last shipment delivers.

### 3.8. In Transit and Delivery

Physical movement is owned by carrier operations. A `CarrierOps` operator departs a shipment, advancing its `execution_status` from `PENDING` to `IN_TRANSIT`. Departure is guarded three ways: the shipment must be `BOOKED` in its tender dimension (otherwise `ERR_SHIPMENT_NOT_BOOKED`), it must be `PENDING` in its execution dimension (otherwise `ERR_SHIPMENT_NOT_PENDING`), and it must be sitting on a load whose status is `DISPATCHED` — that is, its `load_id` is set and that load is dispatched, otherwise `ERR_LOAD_NOT_DISPATCHED`. A shipment cannot leave until the truck carrying it has been dispatched.

Delivery closes the loop. A `CarrierOps` operator delivers an in-transit shipment by supplying the `delivered_minute` at which it arrived; the shipment must be `IN_TRANSIT` (otherwise `ERR_SHIPMENT_NOT_IN_TRANSIT`). Delivery advances the `execution_status` from `IN_TRANSIT` to `DELIVERED` and records the supplied minute on the shipment's `actual_delivery_minute`. It then updates the carrier's scorecard: the assigned carrier's `delivered_count` is increased by one, and additionally, if the delivered minute is at or before the shipment's `promised_eta_minute`, its `on_time_count` is increased by one. As described in §3.1, these counter changes immediately recompute the carrier's `on_time_pct` and `scorecard_grade`. Delivery also bubbles up to the order, driving it from `PLANNED` to `CLOSED` as described in §2.5. If the delivered shipment is the last non-cancelled shipment on its load to reach delivery, the load remains `DISPATCHED` — closing it is the separate manual step covered in §3.7.

### 3.9. Cancelling a Shipment and the Unwind Cascade

A `ShipperOps` operator may cancel a shipment while it is still `PENDING` in its execution dimension; an attempt otherwise is rejected with `ERR_SHIPMENT_NOT_CANCELLABLE`. Cancellation sets the `execution_status` to `CANCELLED` and then unwinds everything the shipment had accumulated, in a defined cascade. First, any `OFFERED` tender for this shipment fires its own `OFFERED → DECLINED` transition; that tender's decline side effect in turn reverts the shipment's `tender_status` from `TENDERED` back to `UNTENDERED`. Where the shipment was already booked — its tender accepted, so there is no `OFFERED` tender left to decline — the cancel instead clears `assigned_carrier_id`, `contract_rate_id`, and `quoted_cost_cents` directly and sets `tender_status` back to `UNTENDERED`. Finally, if the shipment was consolidated onto a load, it is detached: its `load_id` is set back to null and the load's `consolidated_weight_lbs` is recomputed accordingly. This is the serialization point that keeps a load's conserved weight honest — a cancelled shipment no longer counts toward its former load.

### 3.10. Freight Audit: Quoted versus Audited Cost

The freight audit reconciles what was estimated against what the carrier actually billed. After a shipment is delivered, a `FreightAuditor` operator records the carrier's invoice by supplying the `shipment_id` it bills, the `invoiced_linehaul_cents` the carrier charged for linehaul (a figure that already includes the carrier's own fuel), and an optional list of `invoiced_accessorial_codes` the carrier billed; when that list is omitted it defaults to an empty list. Recording the invoice itself requires only that the referenced `shipment_id` resolve to an existing shipment; it does not check the shipment's execution status, so an invoice may be recorded for a shipment in any execution state — the requirement that the shipment be `DELIVERED` is enforced only later, at the audit step. The invoice is created `RECEIVED`, with its `variance_cents` not yet computed.

A `FreightAuditor` operator audits a received invoice. Auditing requires the invoice to be `RECEIVED` (otherwise `ERR_INVOICE_NOT_RECEIVED`) and the billed shipment to be `DELIVERED` in its execution dimension (otherwise `ERR_SHIPMENT_NOT_DELIVERED`). The audit recomputes the authoritative freight cost from the shipment's locked contract rate plus the invoice's actually-billed accessorials. The contract-correct linehaul is the larger of that rate's per-mile rate times the shipment distance and the rate's minimum charge floor; the fuel is the linehaul times the rate's fuel surcharge fraction, rounded half up to whole cents; the accessorial total is the sum, over each code on the invoice, of that code's charge priced as described below; and the shipment's `audited_cost_cents` is the linehaul plus the fuel plus the accessorial total. This differs from the provisional quote in §3.5 precisely in the accessorial term: the quote used a flat 5000-cent reserve, whereas the audit prices the carrier's actual accessorial codes. The audit then computes the invoice's `variance_cents` as the carrier's invoiced linehaul plus the accessorial total, minus the audited cost — a signed figure that isolates the linehaul-and-fuel discrepancy, since the invoiced linehaul already carries the carrier's fuel while the audited linehaul-and-fuel is the contract-correct figure. The audit moves the invoice `RECEIVED → AUDITED` and writes both `audited_cost_cents` onto the shipment and `variance_cents` onto the invoice.

Accessorial pricing depends on the code and, for one code, on the shipment's weight. A `DETENTION` code charges a flat 7500 cents; a `LIFTGATE` code charges a flat 3500 cents; a `RESIDENTIAL` code charges a flat 2500 cents. A `REWEIGH` code is weight-tiered with an inclusive lower boundary: when the shipment weight is below 5000 pounds it charges 1500 cents; when the weight is at least 5000 pounds but below 20000 pounds it charges 4000 cents; and when the weight is at least 20000 pounds it charges 9000 cents. The tier boundaries are inclusive on their lower edge, so a weight of exactly 5000 pounds falls in the 4000-cent tier and a weight of exactly 20000 pounds falls in the 9000-cent tier. Any accessorial code that is not one of `DETENTION`, `LIFTGATE`, `RESIDENTIAL`, or `REWEIGH` causes the audit to be rejected with `ERR_UNKNOWN_ACCESSORIAL`.

### 3.11. Invoice Disposition: Approve or Dispute

Once audited, an invoice resolves one of two ways, both performed by a `FreightAuditor` operator. Approval requires the invoice to be `AUDITED` (otherwise `ERR_INVOICE_NOT_AUDITED`) and requires the absolute value of the invoice's variance to be within a tolerance of 500 cents — that is, the variance's magnitude must be at most 500 cents, otherwise the approval is rejected with `ERR_VARIANCE_EXCEEDS_TOLERANCE`. Approval moves the invoice `AUDITED → APPROVED`. A dispute, by contrast, requires only that the invoice be `AUDITED` (otherwise `ERR_INVOICE_NOT_AUDITED`) and moves it `AUDITED → DISPUTED`; a dispute carries no tolerance condition. The two dispositions are mutually exclusive terminal outcomes of an audited invoice.

### 3.12. Claims and Settlement

Loss-and-damage handling — Over, Short and Damaged, abbreviated OS&D — runs through claims. A `ShipperOps` operator opens a claim against a shipment by supplying the `shipment_id`, a `claim_type` drawn from `OSD_SHORTAGE`, `OSD_OVERAGE`, `DAMAGE`, or `LOSS`, and a `claimed_amount_cents` that must be greater than zero. The claim opens `OPEN`, with its `approved_amount_cents` not yet set. Opening a claim immediately increments the `claim_count` on the carrier assigned to the shipment, which in turn recomputes that carrier's `scorecard_grade` as described in §3.1.

A `FreightAuditor` operator adjudicates the claim. Approval requires the claim to be `OPEN` (otherwise `ERR_CLAIM_NOT_OPEN`) and requires the shipment to be `DELIVERED` in its execution dimension (otherwise `ERR_SHIPMENT_NOT_DELIVERED`); it moves the claim `OPEN → APPROVED` and computes the settlement. The settlement is liability-capped: the order's `declared_value_cents` is the liability ceiling, and the `approved_amount_cents` is the smaller of the claimed amount and that ceiling — so a carrier's exposure on an order can never exceed the order's declared value. There is one special case: a claim whose type is `OSD_OVERAGE` settles to zero regardless of the claimed amount, because an overage is not a carrier liability. Denial requires the claim to be `OPEN` (otherwise `ERR_CLAIM_NOT_OPEN`), moves the claim `OPEN → DENIED`, and sets `approved_amount_cents` to zero.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that transition or otherwise modify an existing resource, including the logical-clock control and all state-action endpoints, return `200 OK`. The request body, response body, side effects, and trigger conditions for each endpoint are described in the §3 narratives above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tms/_clock/set_current_utc` | Set the logical server clock | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/carriers` | Create a carrier | CarrierOps |
| GET | `/tms/carriers` | List carriers (optional scac filter) | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/carriers/{carrierId}` | Get a carrier | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/carriers/{carrierId}/suspend` | Suspend a carrier | CarrierOps |
| POST | `/tms/carriers/{carrierId}/reinstate` | Reinstate a suspended carrier | CarrierOps |
| POST | `/tms/contract-rates` | Create a contract rate | CarrierOps |
| GET | `/tms/contract-rates` | List contract rates (filterable by carrier_id) | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/contract-rates/{rateId}` | Get a contract rate | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/contract-rates/{rateId}/retire` | Retire a contract rate | CarrierOps |
| POST | `/tms/orders` | Create an order | ShipperOps |
| GET | `/tms/orders` | List orders | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/orders/{orderId}` | Get an order | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/orders/{orderId}/cancel` | Cancel an OPEN order | ShipperOps |
| POST | `/tms/shipments` | Create a shipment for an order | ShipperOps |
| GET | `/tms/shipments` | List shipments (filterable by order_id / load_id / assigned_carrier_id / contract_rate_id) | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/shipments/{shipmentId}` | Get a shipment | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/shipments/{shipmentId}/depart` | Mark shipment departed / in-transit | CarrierOps |
| POST | `/tms/shipments/{shipmentId}/deliver` | Mark shipment delivered | CarrierOps |
| POST | `/tms/shipments/{shipmentId}/cancel` | Cancel a PENDING shipment | ShipperOps |
| POST | `/tms/shipments/{shipmentId}/tenders` | Rate-shop and create a tender | ShipperOps |
| GET | `/tms/shipments/{shipmentId}/tenders` | List tenders for a shipment | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/tenders` | List tenders (filterable by carrier_id / shipment_id / contract_rate_id) | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/tenders/{tenderId}` | Get a tender | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/tenders/{tenderId}/accept` | Accept the offered tender; books the shipment | CarrierOps |
| POST | `/tms/tenders/{tenderId}/decline` | Decline the offered tender | CarrierOps |
| POST | `/tms/tenders/{tenderId}/expire` | Expire the offered tender | ShipperOps, CarrierOps |
| POST | `/tms/loads` | Create a load | DockOps |
| GET | `/tms/loads` | List loads (filterable by carrier_id) | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/loads/{loadId}` | Get a load | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/loads/{loadId}/shipments` | List shipments consolidated on a load | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/loads/{loadId}/shipments` | Consolidate a booked shipment onto a building load | DockOps |
| POST | `/tms/loads/{loadId}/dispatch` | Dispatch a load | DockOps |
| POST | `/tms/loads/{loadId}/close` | Close a dispatched load | DockOps |
| POST | `/tms/dock-appointments` | Schedule a dock appointment | DockOps |
| GET | `/tms/dock-appointments` | List dock appointments (filterable by load_id / dock_door) | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/dock-appointments/{apptId}` | Get a dock appointment | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/dock-appointments/{apptId}/check-in` | Check in a scheduled appointment | DockOps |
| POST | `/tms/dock-appointments/{apptId}/release` | Release a checked-in appointment | DockOps |
| POST | `/tms/dock-appointments/{apptId}/cancel` | Cancel a scheduled appointment | DockOps |
| POST | `/tms/freight-invoices` | Record a received carrier freight invoice | FreightAuditor |
| GET | `/tms/freight-invoices` | List freight invoices (filterable by shipment_id) | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/freight-invoices/{invoiceId}` | Get a freight invoice | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/freight-invoices/{invoiceId}/audit` | Audit invoice; recompute audited cost and variance | FreightAuditor |
| POST | `/tms/freight-invoices/{invoiceId}/approve` | Approve an audited invoice within tolerance | FreightAuditor |
| POST | `/tms/freight-invoices/{invoiceId}/dispute` | Dispute an audited invoice | FreightAuditor |
| POST | `/tms/claims` | Open a claim against a shipment | ShipperOps |
| GET | `/tms/claims` | List claims (filterable by shipment_id) | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| GET | `/tms/claims/{claimId}` | Get a claim | ShipperOps, CarrierOps, DockOps, FreightAuditor |
| POST | `/tms/claims/{claimId}/approve` | Approve a claim; settle the amount | FreightAuditor |
| POST | `/tms/claims/{claimId}/deny` | Deny a claim | FreightAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_SCAC` | 409 |
| `ERR_MODE_MISMATCH` | 422 |
| `ERR_RATE_WINDOW_OVERLAP` | 409 |
| `ERR_UNKNOWN_ACCESSORIAL` | 422 |
| `ERR_CARRIER_NOT_FOUND` | 404 |
| `ERR_RATE_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_TENDER_NOT_FOUND` | 404 |
| `ERR_LOAD_NOT_FOUND` | 404 |
| `ERR_APPT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_CARRIER_NOT_ACTIVE` | 409 |
| `ERR_CARRIER_NOT_SUSPENDED` | 409 |
| `ERR_RATE_NOT_ACTIVE` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_SHIPMENT_NOT_PENDING` | 409 |
| `ERR_SHIPMENT_ALREADY_TENDERED` | 409 |
| `ERR_SHIPMENT_NOT_TENDERED` | 409 |
| `ERR_SHIPMENT_NOT_BOOKED` | 409 |
| `ERR_SHIPMENT_NOT_IN_TRANSIT` | 409 |
| `ERR_SHIPMENT_NOT_CANCELLABLE` | 409 |
| `ERR_SHIPMENT_NOT_DELIVERED` | 409 |
| `ERR_NO_ELIGIBLE_CARRIER` | 409 |
| `ERR_TENDER_NOT_OFFERED` | 409 |
| `ERR_LOAD_NOT_BUILDING` | 409 |
| `ERR_LOAD_NOT_DISPATCHED` | 409 |
| `ERR_EMPTY_LOAD` | 409 |
| `ERR_NO_DOCK_APPOINTMENT` | 409 |
| `ERR_LOAD_HAS_UNDELIVERED_SHIPMENTS` | 409 |
| `ERR_LOAD_CAPACITY_EXCEEDED` | 409 |
| `ERR_SHIPMENT_NOT_ON_BUILDING_LOAD` | 409 |
| `ERR_STALE_LOAD_VERSION` | 412 |
| `ERR_APPT_NOT_SCHEDULED` | 409 |
| `ERR_APPT_NOT_CHECKED_IN` | 409 |
| `ERR_DOCK_DOUBLE_BOOKED` | 409 |
| `ERR_INVOICE_NOT_RECEIVED` | 409 |
| `ERR_INVOICE_NOT_AUDITED` | 409 |
| `ERR_VARIANCE_EXCEEDS_TOLERANCE` | 409 |
| `ERR_CLAIM_NOT_OPEN` | 409 |
