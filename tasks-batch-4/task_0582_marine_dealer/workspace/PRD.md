# Marine Dealer API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Marine Dealer API, a back-office system that runs a full-service boat dealership as a single coordinated ledger. A dealership of this kind juggles several businesses at once: it takes boats, outboard motors, and trailers into inventory (each tracked by its Hull Identification Number), finances that inventory through floor-plan lenders, sells and delivers units through negotiated retail deals that may fold in trade-ins and consignments, runs a service lane with rigging, mechanical, and haul-out bays, moves parts across a stockroom counter, and rents out wet slips and dry racks for winter storage. The value of the system is that these activities are not independent — funding a sale must pay off the boat's floor plan, settle any consignor, and register the warranty, all in one motion — and the API is the authoritative record that keeps every one of those derived balances reconciled the instant an event occurs.

The API is organized around peer collections joined by foreign-key references carried in request bodies, and around four operational roles that each own a disjoint surface of the business. The dominant design concern is fiscal and inventory reconciliation: floor-plan payoffs, deal financials, consignment payouts, repair-order totals, and part availability are all derived values that must stay correct through cascading state changes and their compensating reversals. A logical clock drives every time-based computation so that aging, interest accrual, and payoff quotes are deterministic and testable. The remainder of this document defines the global contracts every endpoint honors (Section 2) and then the business workflows and their scattered rules (Section 3), before summarizing the endpoint surface (Section 4) and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles, spelled precisely as `Manager`, `SalesRep`, `ServiceAdvisor`, and `PartsClerk`. If the `X-User-Role` header is missing or its value is not one of these four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

For all four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may accept and log it, but it does not compare `X-User-ID` to any resource's `id`, and no ownership relationship is derived from it. Authorization is decided purely by role: `Manager`, `SalesRep`, `ServiceAdvisor`, and `PartsClerk` each own a distinct set of write operations described throughout Section 3, while read access to every collection and resource, and the ability to advance the logical clock, are shared by all four roles.

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

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every entity in this system — `Unit`, `FloorPlan`, `Deal`, `Consignment`, `RepairOrder`, `ServiceLine`, `Part`, `Berth`, `ServiceBay`, and `SlipReservation` — is a first-class resource and carries the same four system-managed properties:

- **`id`** — a server-minted UUID with no type prefix, unique across all resources.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- **`updated_at`** — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource, including mutations to derived fields.
- **`version`** — an integer that starts at creation and increments by one on every mutation of the resource.

Whenever the system recomputes a derived value on a resource — for example refreshing a `Unit`'s `floor_plan_balance_cents` after a curtailment, or a `Part`'s `available_qty` after a line is voided — that recomputation counts as a mutation and therefore advances `updated_at` and increments `version` on the affected resource.

### 2.5. Nested Resource Resolution and Validation Ordering

When a request references other resources — a path `id`, or a foreign key such as `unit_id`, `berth_id`, `service_bay_id`, `part_id`, or `repair_order_id` carried in the body — the system resolves each referenced identifier left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the first identifier that does not resolve to an existing resource.

Validation across the whole API follows a fixed priority order, and the first failing check is the one reported. Authentication is checked first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization is checked next: a role that may not perform the operation yields `ERR_FORBIDDEN`. Existence is checked third, yielding `ERR_NOT_FOUND`. Structural validity of the request body is checked fourth — required fields present, types correct, and enum values within range — yielding `ERR_INVALID_REQUEST` (HTTP 400). Only after these four universal gates pass does the system evaluate the referential, concurrency, state, and business rules described in Section 3; where several such rules apply to one endpoint, their relative ordering is called out in the workflow that owns them.

### 2.6. The Logical Clock and Time-Based Computations

All time-dependent computation in this system reads from a single logical clock rather than wall-clock time. At server startup the clock is initialized to `2026-05-01T00:00:00Z`, and it never falls back to real time. Any of the four roles may advance the clock by supplying a target instant in the `to_iso8601` field; the supplied value becomes the new "now" for every subsequent computation. The logical clock is the source of the current instant used to derive a `Unit`'s `aging_days`, a `FloorPlan`'s `accrued_interest_cents` and `payoff_cents`, and the elapsed-days check that governs curtailment eligibility. Because these values are all functions of the clock, advancing the clock changes them deterministically.

### 2.7. Monetary Precision and Rounding

Monetary quantities are stored and returned as integer counts of cents. Interest rates, tax rates, commission rates, and minimum-down thresholds are expressed in basis points (bps), where a rate in basis points is applied by multiplying by the basis-point figure and dividing by 10000. Every monetary computation in this document that produces a cents value — tax, interest, payoffs, line extensions, totals, commissions, and payouts — is rounded to a whole number of cents using the round-half-up method (a result whose fractional part is exactly one half rounds away from zero, to the next whole cent). Counts such as inventory quantities and reservation nights are whole integers and are not rounded. Where a calculation both sums and rounds, the exact ordering of rounding versus summation is specified in the relevant Section 3 workflow, because that ordering is fiscally significant.

### 2.8. Optimistic Concurrency Control on Floor-Plan Supersession

Opening a new floor-plan advance against a `Unit` legitimately supersedes whatever prior financing that unit carried, so the operation is guarded by optimistic concurrency on the unit. A request that opens a floor-plan advance must include `expected_unit_version`, carrying the `version` of the target `Unit` that the client last observed. If that value does not equal the unit's current `version` — because some other writer has advanced the unit since the client read it — the request is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412), so a client cannot refinance a unit whose state it has not seen. This version field is required only for the floor-plan advance creation operation; no other endpoint accepts or requires it.

### 2.9. Cascading State Consistency and Compensation

Many operations mutate more than one resource. When a sale is funded, the unit, its floor plan, and any consignment all move together; when that same deal is later cancelled, each of those moves is compensated in reverse. The system applies these cascades and compensations automatically and immediately, without the client acting on the secondary resources directly, and every resource touched in a cascade has its `updated_at` and `version` advanced as described in Section 2.4. The precise chains — which parent transition drives which child transition, and what derived fields are recomputed at each step — are detailed in the Section 3 workflows that own them.

## 3. Business Logic & Workflows

### 3.1. Unit Inventory: Intake, Listing, and Aging

Inventory is the spine of the dealership. A `Manager` takes a boat, motor, or trailer into stock by registering it with its `hin` (a 12-character Hull Identification Number that must be unique across all units), its `make`, `model`, and `model_year`, its `unit_type` — one of `BOAT`, `MOTOR`, or `TRAILER` — its overall `length_ft`, the dealer `cost_cents` and advertised `list_price_cents`, and its `acquisition_type`, which records how the unit came to the lot: `FLOOR_PLAN`, `CASH`, `CONSIGNMENT`, or `TRADE_IN`. The intake payload may also set `open_recall`; when omitted it defaults to false. A newly registered unit begins in `INTAKE` status.

A unit in `INTAKE` is not yet saleable. Only when a `Manager` lists it does its `status` advance from `INTAKE` to `AVAILABLE`, at which point the unit becomes eligible to be sold through a deal and to be reserved into storage. From there the unit's `status` moves through the sales lifecycle — `AVAILABLE`, `RESERVED`, `SOLD`, `DELIVERED` — under system control as its deal progresses (detailed in Section 3.3), and a consigned unit may instead end in `RETURNED`. `DELIVERED` and `RETURNED` are terminal.

Each unit carries three derived read-only fields. `warranty_registered` is false until the unit reaches `DELIVERED` through a funded, delivered deal, at which point it becomes true. `aging_days` is the number of whole days the unit has been in stock, computed as the floor of the elapsed time from `created_at` to the current logical-clock instant. `floor_plan_balance_cents` reflects the outstanding principal of the unit's financing: it equals the `outstanding_principal_cents` of the unit's floor plan whose status is either `ACTIVE` or `CURTAILED` — there is at most one such plan at any time — and is zero when the unit has no such plan. Units can be listed and filtered by `status` and by `acquisition_type`.

### 3.2. Floor-Plan Finance: Advances, Accrual, Payoff, and Curtailment

Inventory acquired on `FLOOR_PLAN` is financed by a lender, and a `Manager` records that financing by opening a floor-plan advance against a unit. The advance identifies the financed unit by `unit_id`, names the `lender_name`, and captures the original `principal_cents` (immutable once set), the rate `apr_bps` in basis points, the `advanced_at` date on which the money was drawn, and the `curtailment_pct_bps` that governs how much principal is due at each curtailment window. On creation the plan starts `ACTIVE` with `outstanding_principal_cents` set equal to `principal_cents`. Opening a new advance for a unit that already has an `ACTIVE` or `CURTAILED` plan is a refinance: the prior plan is driven to `SUPERSEDED` (a terminal state that accepts no further curtailments), the new plan takes its place, the unit's `version` is incremented by one, and the unit's `floor_plan_balance_cents` is recomputed. Because this create competes with other writers on the unit, it carries `expected_unit_version` and is rejected with `ERR_STALE_UNIT_VERSION` on a version mismatch, exactly as described in Section 2.8.

Two derived quantities are reported on every floor plan, and both are functions of the number of whole days the advance has been outstanding — that is, the floor of the elapsed time from `advanced_at` to the current logical-clock instant. The `accrued_interest_cents` figure is the plain chronological interest to the present moment: the `outstanding_principal_cents` multiplied by `apr_bps`, divided by 10000, multiplied by the days outstanding, divided by 365 days per year, and rounded half up to whole cents. The `payoff_cents` figure is instead forward-looking, quoting what it would cost to retire the plan after the lender's notice period: the day count is projected 10 days beyond the present instant, and the payoff equals the `outstanding_principal_cents` plus the interest computed on that projected day count — `outstanding_principal_cents` times `apr_bps` divided by 10000, times the projected days, divided by 365, rounded half up — added to the principal. The distinction is deliberate: the current-balance view accrues only up to now, while the payoff quote and the sale-settlement snapshot project the ten-day notice.

A `Manager` may record a curtailment paydown against an `ACTIVE` or `CURTAILED` plan, supplying the `payment_cents` to apply. A curtailment moves an `ACTIVE` plan to `CURTAILED` (and leaves an already-`CURTAILED` plan in `CURTAILED`). Two guards protect it, evaluated after the universal gates: first, the advance must have seasoned long enough — the number of days elapsed since `advanced_at` must be at least the 90-day curtailment window, otherwise the request is rejected with `ERR_CURTAILMENT_NOT_DUE` (HTTP 409); second, the payment may not exceed what is owed — `payment_cents` must be less than or equal to `outstanding_principal_cents`, otherwise the request is rejected with `ERR_CURTAILMENT_EXCEEDS_PRINCIPAL` (HTTP 422). When both pass, the payment is subtracted from `outstanding_principal_cents` and the unit's `floor_plan_balance_cents` is recomputed. A plan reaches its other states — `PAID_OFF` on sale and back to `ACTIVE` on a cancelled sale — only through the deal cascades described next; floor plans can be listed and filtered by `unit_id` and by `status`.

### 3.3. The Sales Deal: Draft, Sign, Fund, Deliver, and Cancel

A `SalesRep` opens a sale by drafting a `Deal` against a unit. The draft identifies the unit by `unit_id`, names the `customer_name`, and captures the negotiated `sale_price_cents`, the `financing_type` (`CASH` or `RETAIL_FINANCE`), the `tax_rate_bps`, the `doc_fee_cents`, and the buyer's `down_payment_cents`. A trade-in may be folded in through `trade_allowance_cents` (the gross allowance) and `trade_lien_payoff_cents` (the lien still owed on the trade), each defaulting to 0 when omitted. A new deal begins in `DRAFT`. A unit may carry only one live deal at a time: if the unit already has a deal in `DRAFT`, `SIGNED`, or `FUNDED`, the create is rejected with `ERR_UNIT_HAS_ACTIVE_DEAL` (HTTP 409), a check that follows existence and structural validation.

At draft time the system computes three derived money fields on the deal. The `trade_equity_cents` is the `trade_allowance_cents` minus the `trade_lien_payoff_cents`, and may be negative when the trade is underwater. The taxable base is the `sale_price_cents` reduced by the trade allowance but never taken below zero — specifically, the sale price minus the greater of zero and `trade_allowance_cents`, with the whole result floored at zero — and `tax_cents` is that base multiplied by `tax_rate_bps`, divided by 10000, rounded half up. Finally the net cash the buyer owes at funding, `amount_due_cents`, is the `sale_price_cents` plus `tax_cents` plus `doc_fee_cents`, less the `down_payment_cents`, less the `trade_equity_cents`. Deals may be listed and filtered by `unit_id` and by `status`.

Signing a deal advances it from `DRAFT` to `SIGNED`, an action reserved to a `SalesRep`. Signing requires that the referenced unit currently be `AVAILABLE`; if it is not, the sign is rejected with `ERR_UNIT_NOT_AVAILABLE` (HTTP 409). A successful sign cascades: the unit moves from `AVAILABLE` to `RESERVED`, held against this signing deal.

Funding advances a `SIGNED` deal to `FUNDED` and is a `Manager` action. Before funding, the buyer's cash-in must clear a floor: the `down_payment_cents` must be at least the ceiling of `sale_price_cents` times 1000 divided by 10000 — equivalently, at least ten percent of the sale price, rounded up to the next whole cent — otherwise the request is rejected with `ERR_DOWN_PAYMENT_TOO_LOW` (HTTP 402). Funding sets off the system's central cascade: the unit advances from `RESERVED` to `SOLD`; that `SOLD` transition in turn drives the unit's `ACTIVE` or `CURTAILED` floor plan to `PAID_OFF`, snapshotting its `payoff_cents`, setting its `outstanding_principal_cents` to zero, and recomputing the unit's `floor_plan_balance_cents` to zero; and if the unit's `acquisition_type` is `CONSIGNMENT`, the unit's `ACTIVE` consignment is driven to `SOLD` and its `payout_cents` is computed as described in Section 3.4.

Delivering advances a `FUNDED` deal to `DELIVERED`, again a `SalesRep` action, and is the moment the boat leaves the lot. Delivery is blocked while the unit carries an unresolved recall: if the unit's `open_recall` is true, the request is rejected with `ERR_OPEN_RECALL_BLOCKS_DELIVERY` (HTTP 409). On success the unit cascades from `SOLD` to `DELIVERED` and its `warranty_registered` becomes true. `DELIVERED` is terminal for both deal and unit.

A `Manager` may cancel a deal, and the compensation depends on how far the deal had progressed. Cancelling a `DRAFT` deal has no side effects. Cancelling a `SIGNED` deal releases the reservation, returning the unit from `RESERVED` to `AVAILABLE`. Cancelling a `FUNDED` deal unwinds the entire funding cascade: the unit returns from `SOLD` to `AVAILABLE`, which reactivates its floor plan from `PAID_OFF` back to `ACTIVE` with `outstanding_principal_cents` restored to its pre-payoff value and `floor_plan_balance_cents` recomputed, and reverts its consignment from `SOLD` back to `ACTIVE` with `payout_cents` reset to zero. `CANCELLED` is terminal. Across all of these transition endpoints, a request against a resource that is not in a legal state for the requested move is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.4. Consignment Intake, Payout, and Return

The dealership also sells boats it does not own. A `Manager` records a consignment by attaching it to a unit via `unit_id`, naming the `consignor_name`, and setting the `agreed_floor_cents` — the minimum net the owner insists on receiving — and the dealer's `commission_bps` on the eventual sale price. A consignment starts `ACTIVE`. Consignments may be listed and filtered by `unit_id` and by `status`.

When a consigned unit's deal is funded — that is, at the `RESERVED` to `SOLD` transition of a unit whose `acquisition_type` is `CONSIGNMENT` — the consignment moves to `SOLD` and its `payout_cents` is settled. The dealer's commission is the funded deal's `sale_price_cents` multiplied by `commission_bps`, divided by 10000, rounded half up; the consignor's `payout_cents` is that same `sale_price_cents` minus the computed commission. Should the funded deal later be cancelled, the consignment is reverted from `SOLD` to `ACTIVE` and its `payout_cents` is reset to zero, mirroring the unit's return to `AVAILABLE`.

A `Manager` may instead return a consigned unit to its owner when the consignment is still `ACTIVE`, moving it from `ACTIVE` to `RETURNED`. That return cascades to the unit, moving it from `AVAILABLE` to `RETURNED` and removing it from saleable inventory. Both `RETURNED` and `SOLD` are terminal for a consignment.

### 3.5. The Service Lane: Repair Orders and Flat-Rate Operations

A `ServiceAdvisor` opens a repair order to bring a unit through the shop. The repair order names the serviced unit by `unit_id`, the assigned bay by `service_bay_id`, and the `customer_name`, and declares its `ro_type` — `DIAGNOSTIC`, `FLAT_RATE`, or `CUSTOM`. A flat-rate order additionally carries a `flat_rate_code` (`WINTERIZE` or `REPOWER`, required when `ro_type` is `FLAT_RATE`), together with its book `flat_rate_hours` and fixed `flat_rate_parts_cents`; a diagnostic or custom order instead carries `estimated_hours`. Every order carries the shop's `labor_rate_cents_per_hour`, the service `tax_rate_bps`, and the bay window bounded by `scheduled_start` and `scheduled_end`. A new order opens in `OPEN`.

Two scheduling guards apply when the order is created, after existence and structural checks. The window must be well-formed: `scheduled_end` must be strictly later than `scheduled_start`, otherwise the create is rejected with `ERR_SCHEDULE_WINDOW_INVALID` (HTTP 422). The window must also fit the bay: the order's interval, extended by the standard bay-turnaround buffer of 30 minutes, must not overlap any other repair order in the same bay that has not yet reached `INVOICED`; a conflict is rejected with `ERR_BAY_SCHEDULE_CONFLICT` (HTTP 409). Unlike a slip reservation's half-open interval, a repair order's bay window is treated as closed at both ends and the 30-minute buffer extends it at each end, so the new order conflicts with an existing one whenever `scheduled_start` is at or before the other order's `scheduled_end` plus 30 minutes and the other order's `scheduled_start` is at or before the new order's `scheduled_end` plus 30 minutes. An order scheduled to start 15 minutes after another order in the same bay ends therefore conflicts, because it falls inside that buffer.

At and after creation, the order reports a provisional `estimate_total_cents`. For a `FLAT_RATE` order the labor component is `flat_rate_hours` multiplied by `labor_rate_cents_per_hour`, rounded half up, and the pre-tax base is that labor plus `flat_rate_parts_cents`; for a `DIAGNOSTIC` or `CUSTOM` order the pre-tax base is `estimated_hours` multiplied by `labor_rate_cents_per_hour`, rounded half up. In either case the `estimate_total_cents` is that base plus the tax on the base — the base multiplied by `tax_rate_bps`, divided by 10000, rounded half up.

The order advances through its lifecycle under `ServiceAdvisor` control. Starting work moves it from `OPEN` to `IN_PROGRESS`. Completing work moves it from `IN_PROGRESS` to `COMPLETED` and at that moment computes the final total from the actual service lines (Section 3.6). A completed order may be reopened, moving it from `COMPLETED` back to `IN_PROGRESS` and clearing `final_total_cents` until it is completed again. Invoicing moves a `COMPLETED` order to `INVOICED`, the terminal state. Repair orders may be listed and filtered by `unit_id`, by `service_bay_id`, and by `status`. Service bays themselves are simple records a `Manager` creates with a unique `bay_code` and a `bay_type` of `RIGGING`, `MECHANICAL`, or `HAUL_OUT`.

### 3.6. Service Lines, Parts Inventory, and Invoicing

The detail of a repair order lives in its service lines, added by a `ServiceAdvisor`. Each line references its parent order by `repair_order_id` and declares a `line_type` of `LABOR` or `PART`. A labor line must carry its actual `hours`; a part line must carry a `part_id` and a `quantity`, and may set `warranty_covered` (defaulting to false) to mark work the customer is not billed for. A line may override its price through `unit_price_cents`; when that override is absent, the effective price defaults to the referenced `Part`'s `list_price_cents` for a part line, or the order's `labor_rate_cents_per_hour` for a labor line. A new line is `ACTIVE`. Two referential guards and one quantity guard apply to line creation, in this order after the universal checks: a `PART` line missing its `part_id` is rejected with `ERR_PART_REQUIRED_FOR_LINE` (HTTP 422); a `LABOR` line missing its `hours` is rejected with `ERR_HOURS_REQUIRED_FOR_LABOR` (HTTP 422); and a `PART` line whose `quantity` is less than 1 is rejected with `ERR_INVALID_QUANTITY` (HTTP 422). Each line reports a derived `extended_cents`, the rounded extension described below. Service lines may be listed and filtered by `repair_order_id` and by `part_id`.

Parts are stocked at the counter by a `PartsClerk`, who creates a part with a unique `sku`, a `name`, an initial `on_hand_qty`, the `unit_cost_cents` and `list_price_cents`, and a `reorder_point`. A part reports three derived quantities. `reserved_qty` is the sum of `quantity` across all `ACTIVE` `PART` service lines that reference this part. `available_qty` is `on_hand_qty` minus `reserved_qty`. `is_low` is true when `available_qty` is less than or equal to `reorder_point`. A `PartsClerk` may receive stock, supplying a `quantity` that is added to `on_hand_qty`, after which `available_qty` is recomputed. Parts may be listed and filtered by `sku`. Whenever an `ACTIVE` `PART` line is added it reserves inventory (raising the part's `reserved_qty` and lowering its `available_qty`), and voiding such a line releases that reservation.

Voiding a line is a `ServiceAdvisor` action that moves it from `ACTIVE` to `VOID`, permitted only while the parent order is in `OPEN`, `IN_PROGRESS`, or `COMPLETED`; a void attempted against a line whose parent has moved beyond those states is rejected with `ERR_INVALID_STATE` (HTTP 409). When a `PART` line is voided, the part's `reserved_qty` decreases by that line's `quantity` and its `available_qty` is recomputed.

Completing an order computes its `final_total_cents` from the actual lines, and the rounding discipline here differs from the estimate. Only `ACTIVE`, non-warranty-covered lines participate. Each such line is extended and rounded individually first: a `LABOR` line's `extended_cents` is its `hours` multiplied by its effective price, rounded half up; a `PART` line's `extended_cents` is its `quantity` multiplied by its effective price, rounded half up. Those already-rounded line extensions are then summed into a subtotal with no further rounding, and the `final_total_cents` is that subtotal plus the tax on it — the subtotal multiplied by `tax_rate_bps`, divided by 10000, rounded half up. The per-line rounding is fixed before summation deliberately, so the final total can differ from taxing a single combined figure.

Invoicing consumes inventory. Before an order may move from `COMPLETED` to `INVOICED`, every non-warranty `PART` line must be satisfiable from stock: each such line's `quantity` must be less than or equal to the referenced part's `on_hand_qty`, otherwise the invoice is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 409). On a successful invoice, the order becomes `INVOICED`, which drives each `ACTIVE` non-warranty `PART` line to `CONSUMED`; each consumed line decreases both the part's `on_hand_qty` and its `reserved_qty` by that line's `quantity`, and the part's `available_qty` is recomputed accordingly.

### 3.7. Storage: Berths, Bays, and Slip Reservations

The dealership also stores boats. A `Manager` creates a berth with a unique `berth_code`, a `berth_type` of `WET_SLIP` or `DRY_RACK`, and a `max_length_ft` describing the longest unit it accepts. A berth begins `OPEN` and can be taken out of service by a `Manager`, moving it from `OPEN` to `CLOSED`; while `CLOSED` it accepts no new reservations.

A `ServiceAdvisor` reserves a berth for a unit by supplying the `berth_id`, the `unit_id`, the `start_date` (inclusive) and `end_date` (exclusive) of the stay, and the `daily_rate_cents`. A reservation begins `RESERVED` and reports two derived fields: `nights`, the whole number of days between `start_date` and `end_date`, and `total_cents`, that night count multiplied by `daily_rate_cents`. Four business guards apply to a reservation, evaluated in this order after existence and structural validation: the dates must be well-formed, with `end_date` strictly after `start_date`, else `ERR_RESERVATION_DATES_INVALID` (HTTP 422); the target berth must be `OPEN`, else `ERR_BERTH_CLOSED` (HTTP 409); the unit must physically fit, with the unit's `length_ft` less than or equal to the berth's `max_length_ft`, else `ERR_UNIT_EXCEEDS_BERTH` (HTTP 422); and the half-open interval from `start_date` up to but not including `end_date` must not overlap any other `RESERVED` reservation on the same berth, else `ERR_BERTH_DOUBLE_BOOKED` (HTTP 409).

A `ServiceAdvisor` closes out a stay in one of two ways, both of which free the berth interval for future reservations: ending a reservation moves it from `RESERVED` to `ENDED`, and cancelling one moves it from `RESERVED` to `CANCELLED`. Both are terminal. Reservations may be listed and filtered by `berth_id`, by `unit_id`, and by `status`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and every recompute — return `200 OK`. The logical-clock capability also returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/units` | Create a unit (INTAKE) | Manager |
| GET | `/units/{id}` | Get a unit | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| GET | `/units` | List units | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/units/{id}/list` | List a unit for sale (INTAKE→AVAILABLE) | Manager |
| POST | `/floor-plans` | Open a floor-plan advance; supersedes prior plan (OCC on Unit) | Manager |
| GET | `/floor-plans/{id}` | Get a floor plan | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| GET | `/floor-plans` | List floor plans | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/floor-plans/{id}/curtail` | Record a curtailment paydown | Manager |
| POST | `/deals` | Create a sales deal (DRAFT) | SalesRep |
| GET | `/deals/{id}` | Get a deal | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| GET | `/deals` | List deals | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/deals/{id}/sign` | Sign a deal (DRAFT→SIGNED) | SalesRep |
| POST | `/deals/{id}/fund` | Fund a deal (SIGNED→FUNDED) | Manager |
| POST | `/deals/{id}/deliver` | Deliver a deal (FUNDED→DELIVERED) | SalesRep |
| POST | `/deals/{id}/cancel` | Cancel a deal | Manager |
| POST | `/consignments` | Create a consignment (ACTIVE) | Manager |
| GET | `/consignments/{id}` | Get a consignment | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| GET | `/consignments` | List consignments | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/consignments/{id}/return` | Return a consigned unit (ACTIVE→RETURNED) | Manager |
| POST | `/repair-orders` | Open a repair order (OPEN) | ServiceAdvisor |
| GET | `/repair-orders/{id}` | Get a repair order | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| GET | `/repair-orders` | List repair orders | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/repair-orders/{id}/start` | Start work (OPEN→IN_PROGRESS) | ServiceAdvisor |
| POST | `/repair-orders/{id}/complete` | Complete work (IN_PROGRESS→COMPLETED) | ServiceAdvisor |
| POST | `/repair-orders/{id}/reopen` | Reopen a completed order (COMPLETED→IN_PROGRESS) | ServiceAdvisor |
| POST | `/repair-orders/{id}/invoice` | Invoice a completed order (COMPLETED→INVOICED) | ServiceAdvisor |
| POST | `/service-lines` | Add a labor/part line to an order | ServiceAdvisor |
| GET | `/service-lines/{id}` | Get a service line | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| GET | `/service-lines` | List service lines | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/service-lines/{id}/void` | Void a service line (ACTIVE→VOID) | ServiceAdvisor |
| POST | `/parts` | Create a part | PartsClerk |
| GET | `/parts/{id}` | Get a part | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| GET | `/parts` | List parts | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/parts/{id}/receive` | Receive stock (increment on_hand_qty) | PartsClerk |
| POST | `/berths` | Create a berth (OPEN) | Manager |
| GET | `/berths/{id}` | Get a berth | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/berths/{id}/close` | Close a berth (OPEN→CLOSED) | Manager |
| POST | `/service-bays` | Create a service bay | Manager |
| GET | `/service-bays/{id}` | Get a service bay | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/slip-reservations` | Reserve a berth for a unit (RESERVED) | ServiceAdvisor |
| GET | `/slip-reservations/{id}` | Get a reservation | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| GET | `/slip-reservations` | List reservations | Manager, SalesRep, ServiceAdvisor, PartsClerk |
| POST | `/slip-reservations/{id}/end` | End a reservation (RESERVED→ENDED) | ServiceAdvisor |
| POST | `/slip-reservations/{id}/cancel` | Cancel a reservation (RESERVED→CANCELLED) | ServiceAdvisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_UNIT_VERSION` | 412 Precondition Failed |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_UNIT_HAS_ACTIVE_DEAL` | 409 Conflict |
| `ERR_PART_REQUIRED_FOR_LINE` | 422 Unprocessable Entity |
| `ERR_HOURS_REQUIRED_FOR_LABOR` | 422 Unprocessable Entity |
| `ERR_INVALID_QUANTITY` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_RESERVATION_DATES_INVALID` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_BERTH_CLOSED` | 409 Conflict |
| `ERR_UNIT_EXCEEDS_BERTH` | 422 Unprocessable Entity |
| `ERR_BERTH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_BAY_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_DOWN_PAYMENT_TOO_LOW` | 402 Payment Required |
| `ERR_CURTAILMENT_NOT_DUE` | 409 Conflict |
| `ERR_CURTAILMENT_EXCEEDS_PRINCIPAL` | 422 Unprocessable Entity |
| `ERR_OPEN_RECALL_BLOCKS_DELIVERY` | 409 Conflict |
