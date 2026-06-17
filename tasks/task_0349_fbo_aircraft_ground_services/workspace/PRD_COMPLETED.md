# FBO & Aircraft Ground Services API — Product Requirements Document

## 1. Introduction

A Fixed-Base Operator (FBO) is the ground-side business at a general-aviation airport that receives transient and based aircraft, fuels them, parks them, and provides the constellation of ramp services — lavatory carts, ground power, de-icing, crew cars, catering — that a flight department needs between landing and the next departure. This API is the system of record for that operation. It coordinates the full ground-handling stay of an aircraft from the moment a visit is scheduled, through arrival, parking, fueling, servicing, and the priority-permission-required movement slots that govern ramp access, all the way to departure and the single consolidated invoice that closes the stay.

The business problem this system solves is reconciliation across three normally-siloed concerns: physical logistics (which truck went where, how many gallons actually came off the meter), capacity (which spot or movement window is free, and whether a heavier aircraft can even use it), and money (volume-discounted contract fuel pricing, weight-based ramp fees, de-ice surcharges, and the operator's running account balance). Fuel, in particular, carries two independent stories at once — the physical fulfillment of an uplift and the after-the-fact reconciliation of the delivery ticket against what was ordered — and the system tracks both on the same order without letting one block the other. Throughout, the system favors precise, auditable arithmetic in integer cents and conservative state gating so that no aircraft departs with unsettled services and no invoice is computed from stale figures.

The intended users are the FBO's own staff — dispatchers who schedule and park, fuel technicians who run the truck and post tickets, billing clerks who price contracts and chase payment, and line managers who supervise and override — together with the aircraft operators themselves, who act as authenticated customers on their own tails and stays.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. The `X-User-ID` header identifies the acting principal, and the `X-User-Role` header declares the operational capacity in which that principal is acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes five roles, spelled exactly as follows: `OpsDispatcher`, `FuelTech`, `BillingClerk`, `LineManager`, and `Operator`. Each operation is restricted to a defined set of roles; an authenticated caller whose role is not authorized for the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Broadly, an `OpsDispatcher` owns scheduling — visits, parking holds and occupation, spot administration, and the slot lifecycle. A `FuelTech` owns fuel logistics and into-plane reconciliation. A `BillingClerk` owns operator accounts, fuel contracts, invoicing, and billing adjustments. A `LineManager` is the hierarchical override who may perform any operation the other staff roles can, plus invoice voids and clock control. An `Operator` is the customer.

For the four staff roles — `OpsDispatcher`, `FuelTech`, `BillingClerk`, and `LineManager` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may accept and log it, but it does not compare it to any entity's `id`; these roles are trusted across the whole tenant. When `X-User-Role` is `Operator`, by contrast, `X-User-ID` is the `id` of the acting `Operator` entity. Ownership checks on any resource that references an operator compare the resource's owning `operator_id` to `X-User-ID`: an `Operator` may act on and read only its own aircraft, visits, fuel orders, services, slots, and invoices. When an `Operator` caller targets a resource whose owning `operator_id` differs from `X-User-ID` — for example, re-requesting a revoked slot that belongs to another operator's visit — the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check is evaluated only for the `Operator` role and follows the authentication and role-permission checks in priority.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result and defaults to 0, with a minimum of 0. A supplied `limit` or `offset` that falls outside its bounds is silently clamped into range rather than rejected (a `limit` below 1 becomes 1, above 100 becomes 100, and a negative `offset` becomes 0); a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION` (HTTP 422).

Unless an endpoint states otherwise, list results are sorted by their creation timestamp, `created_at`, in ascending order. Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — operators, aircraft, fuel contracts, service visits, parking spots, parking assignments, fuel orders, into-plane tickets, ramp services, ramp slots, and invoices — carries a common set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is the ISO 8601 UTC timestamp, with three fractional digits, recorded when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every subsequent mutation of the resource. The `version` field is an integer that begins at creation and increments by one on every mutation; it underpins the optimistic-concurrency contract described in §2.7. Clients never supply `id`, `created_at`, `updated_at`, or `version` directly.

### 2.5. Resource Identity, Existence, and Reference Resolution

Resources in this system are flat and peer-to-peer: they reference one another by foreign-key fields carried in their bodies — an aircraft names its `operator_id`, a service visit names both its `operator_id` and `aircraft_id`, a fuel order names its `service_visit_id`, `aircraft_id`, and `fuel_contract_id`, and so on — rather than nesting under one another in the URL. Whenever a request names a resource, whether by an identifier embedded in the path or by a foreign key supplied in the body, that reference is resolved left to right in the order it appears, and the first reference that does not resolve to an existing resource causes the whole request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated. A required input field that is entirely absent or structurally malformed is rejected earlier still, with `ERR_MISSING_FIELD` (HTTP 400). A field that is present and well-formed but violates a declared value constraint — for instance an `ordered_gallons` below 1, or an `mtow_lb` below 1 — is rejected with `ERR_VALIDATION` (HTTP 422).

### 2.6. Monetary Precision and Rounding

All monetary amounts in this system are stored and returned as integer cents — `base_price_cents_per_gal`, `tankering_fee_cents_per_gal`, `priced_amount_cents`, `fee_cents`, `charge_cents`, `total_cents`, `paid_cents`, and the operator's `open_invoice_balance_cents` are all whole-cent integers, never decimal strings. Where a calculation produces a fractional intermediate — the de-ice fluid base term and any future fractional rate — the system rounds that intermediate to whole cents using the round-half-up method (a value exactly halfway between two cents rounds up to the larger), and each calculation below states the exact point in its evaluation order at which rounding is applied. Percentages that the system derives, such as a delivery ticket's `variance_pct`, are carried to exactly two decimal places, also rounded half up.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control because they apply a delta computed from a client's earlier read, and acting on a stale read would corrupt a balance or double-book a window. Each such write requires the caller to supply the client's last observed `version` of the target resource as a non-optional input field, and the server rejects the write if that supplied version does not equal the target's current `version`.

Applying a payment to an invoice must carry `expected_invoice_version`, and it must equal the target invoice's current `version`. If another writer has advanced the invoice's version since the client last read it — a prior payment that already moved `paid_cents`, or an adjust-billing re-price that recomputed `total_cents` — the supplied value no longer matches and the payment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from applying its delta against figures it never observed. Likewise, confirming occupation of a parking assignment must carry `expected_assignment_version` equal to that assignment's current `version`; if a concurrent action has released or otherwise advanced the assignment since the client's read, occupying on the stale view would double-book the spot's window, so the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field, and where a version field is required it is mandatory, not optional.

### 2.8. Cascades, Bubble-Ups, and Cross-Entity Consistency

Because money and capacity are derived from many child rows, several operations mutate more than one entity in a single call, and the system keeps those derived figures continuously consistent. When a visit is cancelled, its parking and movement children are released and revoked in cascade; when a ramp service is finalized or cancelled, the parent visit's outstanding-service counter bubbles up; when an invoice changes, the owning operator's open balance is recomputed; and when a flagged fuel order is re-priced, the change propagates through the order's amount to the visit's invoice total and on to the operator's balance. Each of these secondary effects is specified in the workflow narratives of §3. Every mutation — including a mutation the server performs automatically on a parent or sibling without a direct client request against it — refreshes that resource's `updated_at` and increments its `version`. Resources whose only change is a derived figure are mutated the same way: a recompute of an operator's `open_invoice_balance_cents` or `jeta_month_cumulative_gallons` is a mutation that bumps `version` and `updated_at`.

## 3. Business Logic & Workflows

### 3.1. Operators, Aircraft, and the Account That Gates Business

The customer of record is the **Operator** — a flight department or aircraft owner registered with a `legal_name` and a `contact_email` for billing and contact. A newly registered operator starts with `account_status` of `ACTIVE`, a `jeta_month_cumulative_gallons` of 0, and an `open_invoice_balance_cents` of 0. The `account_status` is the gate on new business: it is one of `ACTIVE` or `SUSPENDED`, and it flips to `SUSPENDED` automatically when one of the operator's invoices is marked past due (see §3.7). An operator's `jeta_month_cumulative_gallons` is the running total of Jet-A gallons actually delivered to that operator in the current billing month, and it is the lever that drives the volume discount; its `open_invoice_balance_cents` is the sum, across that operator's invoices in `ISSUED` or `PAST_DUE` status, of each invoice's `total_cents` minus its `paid_cents`, recomputed on every invoice change. Both computed fields are read back on the operator record.

Each **Aircraft** belongs to one operator via `operator_id` and is identified by its `tail_number`. The tail number must be unique within that operator; registering a second aircraft with a tail number already used under the same `operator_id` is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409). An aircraft also declares the `fuel_type` it burns — one of `JET_A` or `AVGAS` — and its maximum takeoff weight `mtow_lb`, an integer of at least 1. From the weight, the system derives the aircraft's `weight_class`: an aircraft is `LIGHT` when its `mtow_lb` is below 12,500 pounds, `MID` when its `mtow_lb` is at least 12,500 but below 41,000 pounds, and `HEAVY` at 41,000 pounds and above. The weight class selects which spots the aircraft may use and which ramp rate it pays.

### 3.2. Fuel Contracts and the Volume-Tier Pricing Engine

Before a tail can be fueled at contract pricing, a `BillingClerk` (or a `LineManager`) establishes a **FuelContract** binding an `operator_id` to a single `product` — `JET_A` or `AVGAS` — at a posted `base_price_cents_per_gal` of at least 1 cent. The contract also carries a `tankering_fee_cents_per_gal`, a flat per-gallon handling fee of at least 0 cents that applies only to tankering orders. A contract is created `ACTIVE`; its `contract_status` is one of `ACTIVE` or `EXPIRED`, and expiring it flips the status to `EXPIRED`, after which it can no longer price new orders.

Pricing happens when a fuel order is dispatched, and the engine has two variants selected by the order's `tankering` flag. For a **tankering** order, the FBO is merely handling fuel uplifted off-field: the priced amount is simply the order's `ordered_gallons` multiplied by the contract's `tankering_fee_cents_per_gal`, with no product cost, no volume discount, and no movement of the operator's tier. For a **non-tankering** order, pricing is marginal across cumulative volume tiers keyed on the operator's running Jet-A cumulative gallons. The system takes the operator's `jeta_month_cumulative_gallons` as it stands at dispatch time as the count of gallons already on the books this month, then walks the order's gallons one at a time: each successive gallon is indexed by where it falls in the operator's cumulative total, and the per-gallon price is the contract `base_price_cents_per_gal` reduced by the discount for that gallon's tier. A gallon whose cumulative index is below 5,000 receives no discount; a gallon whose cumulative index is at least 5,000 but below 20,000 is discounted by 5 cents; a gallon at cumulative index 20,000 or above is discounted by 12 cents. The order's `priced_amount_cents` is the sum of those per-gallon prices, so a single order can cross a tier boundary mid-order and pay different per-gallon rates within the same uplift. All inputs are integer cents and gallons, so the marginal sum is exact with no rounding. Only non-tankering Jet-A orders ever move an operator through these tiers; an `AVGAS` order is priced from its contract base with no discount at any tier and never advances the Jet-A cumulative count.

### 3.3. Scheduling a Visit and the Stay Lifecycle

A ground-handling stay is a **ServiceVisit**, scheduled by an `OpsDispatcher`, `LineManager`, or the `Operator` itself for one aircraft. A visit names its `operator_id` and `aircraft_id` and carries a scheduled `arrival_utc` and `departure_utc`; the departure must be strictly after the arrival, and a departure that is equal to or before the arrival is rejected with `ERR_INVALID_INTERVAL` (HTTP 422). From the two timestamps the system computes the visit's `nights` as the span from arrival to departure divided into 24-hour blocks and rounded up to the next whole block, with a floor of 1 night, and this night count drives parking and ramp fees. A new visit starts in `SCHEDULED` status with `services_outstanding` of 0; its `status` is one of `SCHEDULED`, `ON_GROUND`, `SERVICING`, `READY_FOR_DEPARTURE`, `DEPARTED`, or `CANCELLED`, and `services_outstanding` counts the visit's ramp-service rows that have not yet reached a `COMPLETED` or `CANCELLED` outcome.

The stay advances through a gated lifecycle, each step owned by an `OpsDispatcher` (a `LineManager` may perform any of them). Recording arrival moves the visit `SCHEDULED → ON_GROUND` and stamps `arrival_utc` to the supplied timestamp or to now; it is permitted only while the visit is `SCHEDULED` and only while the owning operator's `account_status` is `ACTIVE`; an arrive against a non-`ACTIVE` operator is rejected with `ERR_INVALID_STATE` (HTTP 409). Beginning to service the aircraft moves it `ON_GROUND → SERVICING`, but only once at least one of the visit's parking assignments has reached `OCCUPIED` status — the aircraft must physically be on a spot before servicing starts, and a start-servicing request with no `OCCUPIED` assignment on the visit is rejected with `ERR_VISIT_NOT_SERVICEABLE` (HTTP 409). Marking the stay ready moves it `SERVICING → READY_FOR_DEPARTURE` only when the visit is settled: `services_outstanding` must be 0 (every ramp service `COMPLETED` or `CANCELLED`) and no fuel order on the visit may still be in `REQUESTED` or `DISPATCHED` logistics status; a mark-ready that fails either settlement condition is rejected with `ERR_INVALID_STATE` (HTTP 409). Finally, departing the aircraft moves it `READY_FOR_DEPARTURE → DEPARTED`; this is the join that closes the stay and is detailed in §3.7. Any of these step requests against a visit that is not in the required starting state is rejected with `ERR_INVALID_STATE` (HTTP 409); where a downstream operation needs the parent visit to be in a servicing-capable state and finds it is not, that operation is rejected with `ERR_VISIT_NOT_SERVICEABLE` (HTTP 409).

A visit may also be **cancelled** while it is still `SCHEDULED` or `ON_GROUND`, and cancellation cascades to the visit's children. Cancelling a `SCHEDULED` visit moves it `SCHEDULED → CANCELLED` and, in cascade, releases every parking assignment for the visit that is in `HELD` or `OCCUPIED` status to `RELEASED` and revokes every ramp slot in `REQUESTED` or `APPROVED` status to `REVOKED`. Cancelling an `ON_GROUND` visit is permitted only when no fuel order on the visit has reached `FUELED`; it moves the visit `ON_GROUND → CANCELLED` and runs a deeper cascade: every non-terminal parking assignment is released to `RELEASED` and each released assignment frees its spot's occupation window so it no longer blocks overlap checks; every non-terminal ramp service is cancelled to `CANCELLED`; and every ramp slot in `REQUESTED` or `APPROVED` status is revoked to `REVOKED`. A cancellation request against a visit in any state other than `SCHEDULED` or `ON_GROUND` is rejected with `ERR_INVALID_STATE`.

### 3.4. Spots, Parking Holds, and Occupation Conflicts

Physical capacity lives in **ParkingSpot** rows created by an `OpsDispatcher` or `LineManager`. A spot has a human `label` that must be unique across all spots — a duplicate label is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409) — a `spot_type` of `HANGAR`, `TIE_DOWN`, or `RAMP`, and a `max_weight_class` of `LIGHT`, `MID`, or `HEAVY` naming the heaviest aircraft it accepts. A spot's `spot_status` is one of `AVAILABLE` or `OUT_OF_SERVICE`; an administrator may toggle a spot out of service, and an occupy attempt against a spot whose `spot_status` is `OUT_OF_SERVICE` is rejected with `ERR_SPOT_OUT_OF_SERVICE` (HTTP 409).

Reserving capacity is a two-step **ParkingAssignment**. First, a dispatcher holds a spot for a visit by creating an assignment that names the `service_visit_id` and `spot_id` and the half-open occupation interval from `occupy_start_utc` (inclusive) to `occupy_end_utc` (exclusive); the end must be strictly after the start or the request is rejected with `ERR_INVALID_INTERVAL`. A new assignment is created in `HELD` status with `fee_cents` of 0; its `status` is one of `HELD`, `OCCUPIED`, or `RELEASED`. At creation the system also checks that the spot can bear the aircraft's weight: a `HEAVY` spot accepts any weight class, a `MID` spot accepts only `LIGHT` and `MID` aircraft, and a `LIGHT` spot accepts only `LIGHT` aircraft; an aircraft whose `weight_class` exceeds the spot's `max_weight_class` is rejected with `ERR_WEIGHT_CLASS_REJECTED` (HTTP 422).

Second, the dispatcher **confirms occupation**, which moves the assignment `HELD → OCCUPIED`, prices it, and is the OCC-guarded write described in §2.7 — the request must carry `expected_assignment_version`. Occupation is permitted only while the assignment is `HELD`, only while the parent visit is `ON_GROUND` or `SERVICING`, and only while the spot's `spot_status` is `AVAILABLE`. Before granting it, the system runs a spot-conflict check whose geometry depends on the spot type. For a `HANGAR` spot, the assignment's interval is widened by a 30-minute tow buffer at each side, and if that buffered window collides with any already-`OCCUPIED` assignment's window on the same spot (a closed, buffer-inclusive overlap), the request is rejected with `ERR_SPOT_TOW_BUFFER_CONFLICT` (HTTP 409). For a `TIE_DOWN` or `RAMP` spot, the system uses plain half-open overlap with no buffer — two intervals conflict only if they actually overlap, so one window ending exactly when the next begins is allowed — and a true overlap against an `OCCUPIED` assignment on the same spot is rejected with `ERR_SPOT_WINDOW_CONFLICT` (HTTP 409). On a clean occupy the system computes `fee_cents` (see §3.5) and increments the assignment's `version`.

An assignment can be **released** from either `HELD` or `OCCUPIED` to `RELEASED`. Releasing frees the spot's occupation window so it no longer participates in overlap checks; a release out of `OCCUPIED` retains the already-computed `fee_cents` for billing, whereas a release out of `HELD` had no fee to keep.

### 3.5. Ramp and Parking Fees

The parking fee is computed at the moment an assignment is confirmed into `OCCUPIED`, and it is a function of the aircraft's weight class and the visit's night count. The per-night rate is read from the weight class of the aircraft on the parent visit: 7,500 cents per night for a `LIGHT` aircraft, 15,000 cents per night for a `MID` aircraft, and 32,500 cents per night for a `HEAVY` aircraft. The fee accumulates one night at a time, rounding each night's rate to whole cents (round half up) before adding it to the running total, and summing across the visit's `nights` — the rounding-then-sum order is fixed so that any future fractional rate remains well defined.

One waiver applies. If, at occupy time, the same operator has at least 200 Jet-A gallons delivered on this visit — measured as the sum of `delivered_gallons` across the into-plane tickets of this visit's `FUELED`, non-tankering, Jet-A fuel orders — then the parking fee is forced to 0 cents, but only for a `RAMP` spot (transient ramp parking). A `HANGAR` or `TIE_DOWN` spot never waives, and a `RAMP` spot below the 200-gallon threshold pays the full weight-class rate times nights. The resulting `fee_cents` is pinned on the assignment.

### 3.6. Fueling: Logistics and Reconciliation on Two Independent Axes

A **FuelOrder** carries two independent state stories on the same row, and they evolve separately. The first is `logistics_status` — the physical fulfillment of the uplift — one of `REQUESTED`, `DISPATCHED`, `FUELED`, or `CANCELLED`. The second is `reconciliation_status` — the after-the-fact matching of the delivery ticket — one of `NOT_STARTED`, `RECONCILED`, `IN_REVIEW`, or `ADJUSTED`. Advancing one axis does not advance the other.

A fuel order is requested by a `FuelTech`, `OpsDispatcher`, or the `Operator` against a `service_visit_id` and an `aircraft_id`, naming the `fuel_contract_id` whose pricing will apply, the `product` ordered, and the `ordered_gallons` (at least 1); an optional `tankering` flag defaults to false. A new order begins with `logistics_status` of `REQUESTED`, `reconciliation_status` of `NOT_STARTED`, and `priced_amount_cents` of 0. The order's `product` must equal the aircraft's `fuel_type` and must equal the named contract's `product`, and that contract's `operator_id` must match the aircraft's `operator_id`; any of these disagreements is rejected with `ERR_PRODUCT_MISMATCH` (HTTP 422). This same product-and-operator coherence is checked again at dispatch.

**Dispatching** the truck (a `FuelTech`-only action) moves the order `REQUESTED → DISPATCHED` and prices it. Dispatch is permitted only while `logistics_status` is `REQUESTED`, only while the parent visit is `ON_GROUND` or `SERVICING`, and only while the chosen contract is `ACTIVE` — a dispatch against an `EXPIRED` contract is rejected with `ERR_CONTRACT_EXPIRED` (HTTP 422). On dispatch the system computes `priced_amount_cents` from the pricing engine of §3.2 using the order's `ordered_gallons`, pinning the amount at this point. **Completing fueling** (also `FuelTech`-only) moves the order `DISPATCHED → FUELED`; this is the ledger-sync point — for a non-tankering Jet-A order, the order's `ordered_gallons` are added to the operator's `jeta_month_cumulative_gallons`, advancing the operator's volume tier for subsequent orders. A fuel order may be **cancelled** while it is `REQUESTED` or `DISPATCHED`; cancellation out of `DISPATCHED` additionally resets `priced_amount_cents` back to 0, while cancellation out of `REQUESTED` has nothing to reset. A logistics step requested from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

The reconciliation axis begins when a `FuelTech` posts an **IntoPlaneTicket** for an order that has reached `FUELED`. The ticket names the `fuel_order_id` and the `delivered_gallons` actually pumped per the truck meter (at least 0). The system computes the ticket's `variance_gallons` as the delivered gallons minus the order's `ordered_gallons` (a signed value), and its `variance_pct` as that variance divided by the ordered gallons, multiplied by 100, carried to two decimal places rounded half up and returned as a JSON number (not a string). The ticket's `outcome` is `RECONCILED` when the absolute value of `variance_pct` is at most 2.00 — exactly 2.00 still reconciles — and `FLAGGED` otherwise. Posting a ticket whose outcome is `RECONCILED` is allowed only while the order is `FUELED` and its `reconciliation_status` is `NOT_STARTED`, and it advances the reconciliation axis `NOT_STARTED → RECONCILED`. Posting a ticket whose outcome is `FLAGGED` under the same preconditions instead advances the axis `NOT_STARTED → IN_REVIEW`, creating the ticket with `outcome` of `FLAGGED`.

A flagged order is resolved by a `BillingClerk` through **adjust-billing**, which moves the reconciliation axis `IN_REVIEW → ADJUSTED` and runs a compensating re-price cascade. The system re-runs the fuel-pricing engine using the ticket's `delivered_gallons` in place of the ordered figure — keyed on the same cumulative-gallon baseline that was captured for this order at dispatch time, so the marginal tier walk reproduces the original pricing context rather than re-reading the operator's now-advanced cumulative — and overwrites the order's `priced_amount_cents`; then, if the order's parent visit already has an `ISSUED` invoice, that invoice's `total_cents` is recomputed; then the owning operator's `open_invoice_balance_cents` is recomputed. This three-step cascade conserves the invariant that an invoice always equals the sum of its current billable lines.

### 3.7. Departure, Invoicing, and the Money Ledger

Departure is the **join** that closes the stay. When an `OpsDispatcher` or `LineManager` departs a visit, it must be `READY_FOR_DEPARTURE`, and no ramp slot for the visit may be `APPROVED` with a movement window still in the future — an approved slot must first be used or revoked. On a clean departure the visit moves `READY_FOR_DEPARTURE → DEPARTED`, the system creates exactly one **Invoice** for the visit in `ISSUED` status, computes that invoice's `total_cents`, recomputes the operator's `open_invoice_balance_cents`, and additionally transitions any of the visit's `APPROVED` ramp slots whose window has already passed to `USED`. An invoice names its `operator_id` and `service_visit_id`; its `status` is one of `ISSUED`, `PAID`, `PAST_DUE`, or `VOID`, and its `paid_cents` begins at 0.

The invoice `total_cents` is the sum of three line groups for the visit: every fuel order on the visit whose `logistics_status` is not `CANCELLED` contributes its `priced_amount_cents`; every parking assignment on the visit in `OCCUPIED` status contributes its `fee_cents`; and every ramp service on the visit in `COMPLETED` status contributes its `charge_cents`. It is a pure integer-cent sum with no rounding.

Payment is a `BillingClerk` action and is OCC-guarded per §2.7: it carries `payment_cents` and `expected_invoice_version`. The `payment_cents` must be at least 1, and `paid_cents` plus the payment must not exceed `total_cents` — a payment that would push the paid amount above the total, or a non-positive payment, is rejected with `ERR_OVERPAYMENT` (HTTP 422). A valid payment adds `payment_cents` to `paid_cents` and recomputes the operator's `open_invoice_balance_cents`. When the running `paid_cents` reaches `total_cents`, the invoice moves to `PAID` — this is allowed from either `ISSUED` or `PAST_DUE`. Marking an invoice past due (from `ISSUED`) moves it `ISSUED → PAST_DUE` and, as a cross-entity effect, sets the owning operator's `account_status` to `SUSPENDED`. When a `PAST_DUE` invoice is subsequently paid in full and the operator no longer has any `ISSUED` or `PAST_DUE` invoice carrying a positive balance, the operator's `account_status` is restored to `ACTIVE`. A `LineManager` may **void** an `ISSUED` invoice, moving it `ISSUED → VOID` and recomputing the operator's `open_invoice_balance_cents` so the voided invoice drops out of the balance. Any invoice transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.8. Ramp Services and the De-Ice Charge

Between arrival and departure a visit may request one or more **RampService** rows — a `service_type` of `LAVATORY`, `GPU`, `DE_ICE`, `CREW_CAR`, or `CATERING` — against its `service_visit_id`. Requesting a service is open to an `OpsDispatcher`, `LineManager`, or the `Operator`; a new service begins in `REQUESTED` status, and creating it increments the parent visit's `services_outstanding` by 1. A service's `status` is one of `REQUESTED`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`, and its `charge_cents` stays 0 until completion.

De-ice requests carry extra fields that no other service type may supply. A `DE_ICE` service must carry a `deice_fluid_type` of `TYPE_I` or `TYPE_IV`, a `deice_fluid_gallons` of at least 1, and a `deice_holdover_minutes` of at least 0; a `DE_ICE` request missing any required de-ice field, or any non-de-ice service that supplies de-ice fields, is rejected with `ERR_DEICE_FIELDS_REQUIRED` (HTTP 422). Every ramp service record carries the three de-ice fields back in its body regardless of type: a non-`DE_ICE` service reads back `deice_fluid_type` of `null`, `deice_fluid_gallons` of 0, and `deice_holdover_minutes` of 0.

A service is worked by a `LineManager` or `OpsDispatcher`. Starting it moves it `REQUESTED → IN_PROGRESS`, permitted only while the service is `REQUESTED` and the parent visit is `SERVICING`. Completing it moves it `IN_PROGRESS → COMPLETED`, computes its `charge_cents`, and bubbles up by decrementing the parent visit's `services_outstanding` by 1. Cancelling a service from either `REQUESTED` or `IN_PROGRESS` moves it to `CANCELLED` and likewise decrements the parent visit's `services_outstanding` by 1.

The `charge_cents` for most service types is a flat fee, and that flat fee is 0 cents for every non-`DE_ICE` type (`LAVATORY`, `GPU`, `CREW_CAR`, and `CATERING`), so completing one of those services pins `charge_cents` to 0. For a `DE_ICE` service it is computed at completion from three inputs that interact non-linearly. The fluid base term is `deice_fluid_gallons` multiplied by 1,800 cents per gallon, multiplied by a dilution factor of 1.0 for `TYPE_I` fluid or 1.4 for `TYPE_IV` fluid. The holdover surcharge is the holdover minutes beyond a 15-minute free allowance — that is, the larger of zero and `deice_holdover_minutes` minus 15 — multiplied by 400 cents per minute. The final `charge_cents` is the fluid base term, rounded to whole cents half up, plus the (already whole-cent) surcharge; the rounding is applied to the fluid base term before the surcharge is added, and this order is fixed.

### 3.9. Movement Slots: the Priority-Permission Cycle

Ramp movement on a `RAMP`-type pad is governed by a **RampSlot**, a priority-permission-required (PPR) reservation requested against a `service_visit_id` and a `pad_id` for a half-open movement window from `window_start_utc` (inclusive) to `window_end_utc` (exclusive); the end must be strictly after the start or the request is rejected with `ERR_INVALID_INTERVAL`. A new slot begins `REQUESTED`; its `status` is one of `REQUESTED`, `APPROVED`, `REVOKED`, or `USED`, and the machine is cyclic — an approved slot can be revoked and re-requested.

A dispatcher **approves** a slot, moving it `REQUESTED → APPROVED`, only while the slot is `REQUESTED`, only while the parent visit is `SCHEDULED`, `ON_GROUND`, or `SERVICING`, and only when no other `APPROVED` slot on the same `pad_id` half-open-overlaps this window — adjacency, where one window ends exactly as another begins, is allowed, but a true overlap is rejected with `ERR_SLOT_OVERLAP` (HTTP 409). **Revoking** an approved slot moves it `APPROVED → REVOKED` and frees the pad's approved window so it no longer blocks overlap checks. A revoked slot can be **re-requested** — moving it `REVOKED → REQUESTED` — by the `Operator` (or an `OpsDispatcher`), but only while the parent visit is not `DEPARTED` or `CANCELLED`; this is the point at which the `Operator` ownership check of §2.1 applies, since the caller must own the visit. **Using** an approved slot at movement time moves it `APPROVED → USED` and frees the pad's approved window; it is permitted only while the slot is `APPROVED` and the parent visit is `ON_GROUND`, `SERVICING`, or `READY_FOR_DEPARTURE`. Any slot transition from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.10. Ordering of Checks and the Billing-Month Clock

When a single request could fail several ways, the checks are evaluated in a fixed priority so the rejection a client sees is deterministic. Authentication comes first: a missing or unknown `X-User-Role`, or a missing `X-User-ID`, yields `ERR_UNAUTHENTICATED` before anything else. Role permission comes next, yielding `ERR_FORBIDDEN_ROLE`. For an `Operator`-role caller acting on a resource, the ownership check yields `ERR_NOT_RESOURCE_OWNER` next. Existence of every path identifier and body foreign key, resolved left to right, comes next with `ERR_NOT_FOUND`. State eligibility for the requested transition comes next with `ERR_INVALID_STATE`. Only then are the domain-specific business rules applied — product and operator coherence (`ERR_PRODUCT_MISMATCH`), weight-class fit (`ERR_WEIGHT_CLASS_REJECTED`), de-ice field presence (`ERR_DEICE_FIELDS_REQUIRED`), hangar tow-buffer and tie-down/ramp window conflicts (`ERR_SPOT_TOW_BUFFER_CONFLICT` and `ERR_SPOT_WINDOW_CONFLICT`), slot overlap (`ERR_SLOT_OVERLAP`), interval validity (`ERR_INVALID_INTERVAL`), and uniqueness (`ERR_DUPLICATE_RESOURCE`) — followed by the optimistic-concurrency check (`ERR_STALE_VERSION`) and finally the payment fiscal check (`ERR_OVERPAYMENT`). This ordering matters: it guarantees, for instance, that a stale-version conflict surfaces as a concurrency error and not as some later fiscal complaint.

Finally, the system exposes an administrative test-driving capability that rolls the billing month forward. This `LineManager`-only operation resets every operator's `jeta_month_cumulative_gallons` back to 0, restarting each operator's volume-tier accumulation for the new month; it returns no resource body.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — every state transition, payment, adjustment, or administrative toggle — return a `200 OK` status code. The complete request and response semantics for each endpoint are given by the §3 narratives; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/operators` | Register an operator account | BillingClerk, LineManager |
| GET | `/operators/{id}` | Fetch an operator (with computed cumulative gallons and open balance) | OpsDispatcher, FuelTech, BillingClerk, LineManager, Operator |
| POST | `/aircraft` | Register an aircraft under an operator | OpsDispatcher, LineManager, Operator |
| GET | `/aircraft/{id}` | Fetch an aircraft | OpsDispatcher, FuelTech, LineManager, Operator |
| GET | `/aircraft` | List aircraft, optionally filtered by operator | OpsDispatcher, FuelTech, BillingClerk, LineManager, Operator |
| POST | `/fuel-contracts` | Create a fuel volume contract | BillingClerk, LineManager |
| GET | `/fuel-contracts/{id}` | Fetch a fuel contract | FuelTech, BillingClerk, LineManager, Operator |
| GET | `/fuel-contracts` | List fuel contracts, filterable by operator | FuelTech, BillingClerk, LineManager, Operator |
| POST | `/fuel-contracts/{id}/expire` | Expire a contract | BillingClerk, LineManager |
| POST | `/service-visits` | Schedule a ground-handling visit | OpsDispatcher, LineManager, Operator |
| GET | `/service-visits/{id}` | Fetch a visit | OpsDispatcher, FuelTech, BillingClerk, LineManager, Operator |
| GET | `/service-visits` | List visits, filterable by operator or aircraft | OpsDispatcher, FuelTech, BillingClerk, LineManager, Operator |
| POST | `/service-visits/{id}/arrive` | Mark the aircraft on the ground | OpsDispatcher, LineManager |
| POST | `/service-visits/{id}/start-servicing` | Begin servicing once a spot is occupied | OpsDispatcher, LineManager |
| POST | `/service-visits/{id}/mark-ready` | Mark ready for departure | OpsDispatcher, LineManager |
| POST | `/service-visits/{id}/depart` | Depart and generate the visit invoice | OpsDispatcher, LineManager |
| POST | `/service-visits/{id}/cancel` | Cancel a visit (cascade to children) | OpsDispatcher, LineManager |
| POST | `/parking-spots` | Create a hangar/tie-down/ramp spot | OpsDispatcher, LineManager |
| GET | `/parking-spots/{id}` | Fetch a spot | OpsDispatcher, LineManager, Operator |
| GET | `/parking-spots` | List spots | OpsDispatcher, LineManager, Operator |
| POST | `/parking-spots/{id}/out-of-service` | Toggle a spot out of service | OpsDispatcher, LineManager |
| POST | `/parking-assignments` | Hold a spot for a visit's occupation window | OpsDispatcher, LineManager |
| GET | `/parking-assignments/{id}` | Fetch a parking assignment | OpsDispatcher, BillingClerk, LineManager, Operator |
| GET | `/parking-assignments` | List parking assignments, filterable by visit or spot | OpsDispatcher, BillingClerk, LineManager, Operator |
| POST | `/parking-assignments/{id}/occupy` | Confirm occupation (computes fee; OCC-guarded) | OpsDispatcher, LineManager |
| POST | `/parking-assignments/{id}/release` | Release the spot occupation window | OpsDispatcher, LineManager |
| POST | `/fuel-orders` | Request a fuel uplift for a visit | FuelTech, OpsDispatcher, Operator |
| GET | `/fuel-orders/{id}` | Fetch a fuel order (both state axes) | FuelTech, OpsDispatcher, BillingClerk, LineManager, Operator |
| GET | `/fuel-orders` | List fuel orders, filterable by visit, aircraft, or contract | FuelTech, OpsDispatcher, BillingClerk, LineManager, Operator |
| POST | `/fuel-orders/{id}/dispatch` | Dispatch the truck; prices the order | FuelTech |
| POST | `/fuel-orders/{id}/complete-fueling` | Mark fueling complete | FuelTech |
| POST | `/fuel-orders/{id}/cancel` | Cancel an un-fueled order | FuelTech, OpsDispatcher |
| POST | `/fuel-orders/{id}/adjust-billing` | Resolve a flagged reconciliation by re-pricing | BillingClerk |
| POST | `/into-plane-tickets` | Post a delivery ticket; reconciles the order | FuelTech |
| GET | `/into-plane-tickets/{id}` | Fetch a delivery ticket | FuelTech, BillingClerk, LineManager |
| GET | `/into-plane-tickets` | List delivery tickets, filterable by fuel order | FuelTech, BillingClerk, LineManager |
| POST | `/ramp-services` | Request a ground service for a visit | OpsDispatcher, LineManager, Operator |
| GET | `/ramp-services/{id}` | Fetch a ramp service | OpsDispatcher, FuelTech, BillingClerk, LineManager, Operator |
| GET | `/ramp-services` | List ramp services, filterable by visit | OpsDispatcher, FuelTech, BillingClerk, LineManager, Operator |
| POST | `/ramp-services/{id}/start` | Begin the service | LineManager, OpsDispatcher |
| POST | `/ramp-services/{id}/complete` | Complete the service; compute charge | LineManager, OpsDispatcher |
| POST | `/ramp-services/{id}/cancel` | Cancel a service | LineManager, OpsDispatcher |
| POST | `/ramp-slots` | Request a PPR/slot window on a RAMP pad | OpsDispatcher, LineManager, Operator |
| GET | `/ramp-slots/{id}` | Fetch a ramp slot | OpsDispatcher, LineManager, Operator |
| GET | `/ramp-slots` | List ramp slots, filterable by visit or pad | OpsDispatcher, LineManager, Operator |
| POST | `/ramp-slots/{id}/approve` | Approve the slot (overlap-checked) | OpsDispatcher, LineManager |
| POST | `/ramp-slots/{id}/revoke` | Revoke an approved slot | OpsDispatcher, LineManager |
| POST | `/ramp-slots/{id}/re-request` | Re-request a revoked slot | Operator, OpsDispatcher |
| POST | `/ramp-slots/{id}/use` | Consume an approved slot at movement time | OpsDispatcher, LineManager |
| GET | `/invoices/{id}` | Fetch an invoice | BillingClerk, LineManager, Operator |
| GET | `/invoices` | List invoices, filterable by operator or visit | BillingClerk, LineManager, Operator |
| POST | `/invoices/{id}/pay` | Apply a payment (OCC-guarded) | BillingClerk |
| POST | `/invoices/{id}/mark-past-due` | Flag an invoice past due (suspends the operator) | BillingClerk |
| POST | `/invoices/{id}/void` | Void an issued invoice | LineManager |
| POST | `/_clock/advance_month` | Roll the billing month forward; reset cumulative gallons | LineManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PRODUCT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_WEIGHT_CLASS_REJECTED` | 422 Unprocessable Entity |
| `ERR_DEICE_FIELDS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SPOT_TOW_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_SPOT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_SPOT_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_CONTRACT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_VISIT_NOT_SERVICEABLE` | 409 Conflict |
| `ERR_MISSING_FIELD` | 400 Bad Request |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
