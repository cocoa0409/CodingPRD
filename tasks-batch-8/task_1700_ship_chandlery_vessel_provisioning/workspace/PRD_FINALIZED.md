# Ship Chandlery & Vessel Provisioning API — Product Requirements Document

## 1. Introduction

A port ship chandler lives and dies on turnaround time. When a vessel berths, the catering officer hands over a requisition list, the chandler prices it against whatever the warehouse actually holds — including bonded stores that may only leave the shed duty-free under customs supervision — and a fleet of vans races the departure tide to deliver at the gangway. Every step is watched: customs officers gate the release of bonded goods, cold stores have hard cubic limits, agents extend trade credit that can be exhausted by a single large order, and the receiver's signature at the gangway is the only proof that quantity and quality were accepted. The traditional paper trail fails precisely where it matters most: at 03:00, with a reefer container half-empty and a vessel sailing at first light.

This document specifies the Ship Chandlery & Vessel Provisioning API, a single-tenant backend that models the full commercial cycle: registering paying agents and vessel port calls, maintaining the catalog and stock lots, capturing vessel requisitions, pricing them into quotations with duty and cold-chain surcharges, reserving stock on acceptance, scheduling and confirming gangway deliveries, issuing final-priced invoices in the agent's settlement currency, recording multi-currency payments with tolerance write-offs, and closing the loop on quality complaints with automatically computed credit notes. The API is mounted under `/chandlery` and is designed for operators on both sides of the quay — chandler staff, the vessel's catering officer, the port customs officer, and the paying agent's clerk — each acting under a strict segregation-of-duties regime.

Two design commitments shape everything that follows. First, time in this system is a **logical clock**: the server never reads wall-clock time; all timestamps the system writes come from a test-driving clock whose startup default is `2026-08-01T00:00:00Z`, and quotation expiry, actual arrival/departure capture, and cold-chain hour calculations all read that same clock. Second, the Order entity carries **two independent status dimensions** — fulfillment and payment — which evolve on separate triggers and only interact at a small number of well-defined gates; readers should resist the urge to collapse them into one lifecycle.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the named role is not permitted for the endpoint — or, for entity-backed roles, the ownership check described below fails — the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognises eight roles, spelled exactly as follows: `ChandlerOpsManager`, `ChandlerSalesRep`, `WarehouseSupervisor`, `VesselCateringOfficer`, `PortCustomsOfficer`, `FinanceController`, `ShipAgentClerk`, `QualityAssuranceLead`.

Identity semantics differ by role. When `X-User-Role` is `VesselCateringOfficer`, `X-User-ID` is the `id` of the acting `VesselCall`; ownership checks on any resource reachable from a vessel call — its requisitions, quotations, orders, deliveries, and complaints — compare the call's `id` to `X-User-ID`. When `X-User-Role` is `ShipAgentClerk`, `X-User-ID` is the `id` of the acting `ShipAgent`; a clerk may record payments only against invoices billed to their own agent. The remaining six roles — `ChandlerOpsManager`, `ChandlerSalesRep`, `WarehouseSupervisor`, `PortCustomsOfficer`, `FinanceController`, and `QualityAssuranceLead` — are opaque: `X-User-ID` is an operator identifier not tied to any persisted entity; the server may record it (for example as `authored_by_user_id` on a `Quotation`, `created_by_user_id` on a `Delivery`, `issued_by_user_id` on an `Invoice`, `recorded_by_user_id` on a `Payment`, or `last_reviewer_user_id` on a `QualityComplaint`) but never compares it to an entity's `id`.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Lists are always sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Resources with full bookkeeping additionally carry `updated_at` (same format, refreshed on every mutation) and an integer `version` that starts at 1 on creation and increments by exactly 1 on every successful mutation. The `Payment` entity is the single exception: it is an append-only event log entry and carries only `id` and `created_at` — neither `updated_at` nor `version` exists on payments, and no payment record is ever mutated after creation.

All system-generated timestamps — `created_at`, `submitted_at`, `accepted_at`, `confirmed_at`, `issued_at`, `actual_eta`, `actual_etd` — are read from the server's logical clock, never from wall-clock time. A `ChandlerOpsManager` may advance that clock through an admin-only test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value and returns the resulting `now_iso8601`; before any such call the clock reads `2026-08-01T00:00:00Z`, and it never falls back to wall-clock. Lazy quotation expiry (§3.4) is re-evaluated against this clock.

### 2.5. Money, Precision, and Rounding

All monetary values are integer cents; no field ever carries a fractional cent. Wherever a multiplication or division produces a fraction — duty computation, volume rebate, currency conversion, credit-note pro-rating, restocking fee — the value is rounded half-up to whole cents at the pinned step and nowhere else inside the same line computation. The substitution price cap likewise rounds half-up. Cold-chain hours are whole hours computed as the floor of elapsed seconds divided by 3600, clamped at zero if the interval is negative.

### 2.6. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control on a parent entity's `version`. Revising a quotation requires the request to carry `expected_quotation_version` equal to the quotation's current `version`; posting a cycle-count adjustment to a stock lot requires `expected_stock_lot_version` equal to the lot's current `version`. In both cases, if the parent entity's version has advanced beyond what the client last observed — because a prior revise legitimately re-priced the quotation, or a prior adjustment re-based the lot's quantities — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from blindly overwriting terms or quantities it has not seen. Endpoints not named here do not accept a version field.

### 2.7. Credit Exposure Accounting

Each `ShipAgent` carries two continuously recomputed exposure figures. `committed_exposure_cents` is the sum of `total_cents` over the agent's orders whose `payment_status` is `UNINVOICED` and whose `fulfillment_status` is one of `OPEN`, `PARTIALLY_DELIVERED`, or `DELIVERED`, plus the `outstanding_cents` of the agent's invoices in `ISSUED` or `PARTIALLY_PAID` status. `settled_exposure_cents` is the narrower figure: only the `outstanding_cents` of those same `ISSUED` or `PARTIALLY_PAID` invoices. Cancelled orders and `VOID`, `PAID`, or `CREDITED` invoices contribute nothing to either figure.

A deliberate accounting asymmetry is pinned by the business and must be implemented as stated: order totals are denominated in USD cents while invoice outstanding amounts are denominated in the agent's settlement-currency cents, and the exposure sums add them **raw, without conversion**. This is a documented conservative approximation — exposure can only be overstated, never understated — and is not a defect to be repaired. The two figures diverge whenever an accepted order has not yet been invoiced: the committed leg counts the order total, the settled leg does not.

### 2.8. Dual-Variant Pricing: Provisional versus Final

Line pricing exists in two variants that share one formula but read different inputs, and the two can legitimately diverge for identical quoted data. The **provisional** variant runs at quotation creation and on every revise: quantities are the quoted quantities, duty-free eligibility is evaluated against the vessel call's *current* `customs_clearance_status` (so `PENDING` or `REJECTED` makes every line dutiable at quote time), and the cold-chain duration is the whole-hour count of the *planned* port stay between `scheduled_eta` and `scheduled_etd`. The **final** variant runs at invoice issuance: quantities are the delivered quantities per line (which may be lower after a shortage), duty-free eligibility is evaluated against the clearance status *at the moment of issuance*, and the cold-chain duration is the whole-hour count between the order's `accepted_at` and the `confirmed_at` of the order's *last* delivered delivery. Rounding order is pinned: every line is fully computed and rounded at its duty step before any summation, then the subtotal is the sum of those rounded line totals. Summing unrounded components and rounding once at the end produces different cents when several lines carry fractional duty and is therefore forbidden.

### 2.9. Parallel Status Dimensions and Cascade Discipline

Two entities carry two independent status dimensions each. `VesselCall` pairs `status` (`SCHEDULED` | `IN_PORT` | `DEPARTED` | `CANCELLED`) with `customs_clearance_status` (`PENDING` | `CLEARED` | `REJECTED`); customs decisions may only be taken while the call is `SCHEDULED` or `IN_PORT`, but otherwise evolve independently of port presence. `Order` pairs `fulfillment_status` (`OPEN` | `PARTIALLY_DELIVERED` | `DELIVERED` | `CANCELLED`) with `payment_status` (`UNINVOICED` | `INVOICED` | `PARTIALLY_PAID` | `PAID` | `CREDITED`); fulfillment moves on delivery confirms and cancels, payment moves on invoice issuance, payments, and credit notes, and the dimensions cross only at two gates — order cancellation requires payment to be `UNINVOICED` or `INVOICED` with zero payments recorded, and invoice issuance requires fulfillment `DELIVERED`, or `PARTIALLY_DELIVERED` once the vessel has departed.

State changes propagate along fixed cascade hops, and every hop must be applied. A vessel departure fails non-terminal deliveries, cancels open orders with their stock released and unpaid issued invoices voided, and releases the undelivered reservation remainder of partially delivered orders; each of those hops in turn recomputes the affected agent's exposure figures. Wherever a cascade touches an entity, that entity's `version` increments and its `updated_at` refreshes, exactly as for a direct write.

## 3. Business Logic & Workflows

### 3.1. Setting the Stage: Agents, Vessel Calls, and the Catalog

A commercial relationship begins when a `FinanceController` registers a paying agent, supplying the agent company `name`, the `settlement_currency` (one of `USD`, `EUR`, `GBP`, or `SGD`), a `credit_limit_cents` ceiling in cents of that currency, and `payment_terms_days` — the number of days from invoice issuance that determines each invoice's `due_date`. Both `credit_limit_cents` and `payment_terms_days` must be zero or positive. Newly registered agents start with `committed_exposure_cents` and `settled_exposure_cents` of zero.

A `ChandlerOpsManager` then registers each vessel port call with its `vessel_name`, `imo_number`, the `agent_id` of the paying agent, the `port_code` (a UN/LOCODE), the planned `scheduled_eta` and `scheduled_etd`, and the `foreign_going` flag that records whether the vessel's next voyage is foreign-going — a precondition for duty-free treatment later. The scheduled departure must be strictly after the scheduled arrival; a call whose `scheduled_etd` is not strictly after its `scheduled_eta` is rejected as `ERR_INVALID_REQUEST`. A new call starts as `SCHEDULED` with `customs_clearance_status` `PENDING`, and `actual_eta` and `actual_etd` remain unset until the corresponding events occur.

The chandler's sellable universe is the catalog. A `ChandlerOpsManager` creates catalog items with a `sku` that must be unique across the entire catalog (duplicates are rejected `ERR_DUPLICATE_SKU`), a display `name`, a `category` of `PROVISIONS`, `BONDED`, `DECK`, `ENGINE`, or `CABIN`, two eligibility flags — `bonded_eligible` (may the item be sold duty-free from bonded stores when customs rules are met) and `requires_cold_chain` (must the item be held in `COLD_STORE` and does it attract the cold-chain surcharge) — a `base_price_cents` of at least 1 in USD cents, and an optional `duty_rate_pct` (zero or positive, defaulting to 0) applied when the line is dutiable. The catalog list supports filtering by `category` and `requires_cold_chain` alongside pagination.

### 3.2. The Warehouse: Stock Lots, Tiers, and Cycle-Count Adjustments

Physical stock lives in lots. A `WarehouseSupervisor` creates a `StockLot` for a `catalog_item_id`, giving it a `lot_code` unique within that catalog item (a duplicate code under the same item is `ERR_DUPLICATE_SKU`), a `storage_tier` of `BONDED_WAREHOUSE`, `COLD_STORE`, or `DRY_STORE`, an initial `received_qty` of zero or more, and a `capacity_qty`. On creation the lot's `on_hand_qty` is set equal to `received_qty` and `reserved_qty` starts at zero. The `capacity_qty` field is meaningful only for `COLD_STORE` lots — it caps the total cold-reserved quantity across overlapping reservation windows — and is ignored for the other tiers. The stock list supports filtering by `catalog_item_id` and `storage_tier`.

Reality drifts from records, so the warehouse performs cycle counts. Posting an adjustment carries an `adjustment_qty` (which may be negative) and a free-text `reason`, and is guarded by OCC as described in §2.6: the request must carry `expected_stock_lot_version` matching the lot's current `version`, else `ERR_STALE_VERSION`. A successful adjustment adds `adjustment_qty` to both `received_qty` and `on_hand_qty` while leaving `reserved_qty` untouched; neither field may be driven negative, and `on_hand_qty` may not be driven below `reserved_qty`, else the write fails with `ERR_INVALID_QTY`. The lot's `version` increments by 1 on success.

### 3.3. The Vessel Speaks: Requisitions

Once a call exists, the vessel's catering officer drafts a requisition against it. Creation is nested under the vessel call — the payload carries a free-text `title` and a `lines` array with at least one element, each line naming a `catalog_item_id`, a `requested_qty` of at least 1, an `allows_substitution` flag, and an optional `notes`. Because the officer's `X-User-ID` *is* the vessel call's `id`, the same identity both authorizes the creation and stamps the requisition's `vessel_call_id` from the nested path. A new requisition is `DRAFT`.

Submission moves the requisition `DRAFT → SUBMITTED`, stamps `submitted_at` from the logical clock, and is only permitted from `DRAFT` (otherwise `ERR_REQUISITION_NOT_SUBMITTABLE`) and only by the officer of that very call (a mismatched identity is `ERR_INSUFFICIENT_PERMISSIONS`). Submission is not one-way: the officer may recall a `SUBMITTED` requisition back to `DRAFT` — the cycle `DRAFT → SUBMITTED → DRAFT` is legal — but recall is blocked while any quotation on the requisition sits in `SENT`, surfacing `ERR_REQUISITION_HAS_LIVE_QUOTATION`; recalling from any state other than `SUBMITTED` is `ERR_REQUISITION_NOT_RECALLABLE`. Two transitions on a requisition are system-driven rather than user-driven: when a quotation of the requisition first goes `DRAFT → SENT`, the requisition advances `SUBMITTED → QUOTED`; and when the last live quotation disappears — the only `SENT` quotation is withdrawn or expires with no other `SENT` quotation remaining — the requisition falls back `QUOTED → SUBMITTED`.

### 3.4. The Commercial Offer: Quotations, Lazy Expiry, and Acceptance

Against a `SUBMITTED` or `QUOTED` requisition (anything else yields `ERR_REQUISITION_NOT_OPEN_FOR_QUOTES`), a `ChandlerSalesRep` drafts a quotation whose `requisition_id` is taken from the nested creation path. The payload carries a `lines` array — each line naming a `catalog_item_id`, a `qty` of at least 1, a `unit_price_cents` of at least 1, an `is_substitution` flag, and a `substitution_of_item_id` required exactly when the line is a substitution — plus a `valid_until` acceptance deadline. Coverage is exact: every requisition line must be covered by exactly one quotation line, and a substitute line covers its original. Creation stamps `authored_by_user_id` from the sales rep's `X-User-ID`, computes `provisional_total_cents` using the provisional pricing variant, and leaves the quotation `DRAFT` with `revision_count` zero.

Sending moves the quotation `DRAFT → SENT` (only `DRAFT` is sendable, else `ERR_QUOTATION_NOT_SENDABLE`), recomputes `provisional_total_cents`, and flips the parent requisition to `QUOTED`. A quotation already `SENT` can be revised — the machine cycles `SENT → SENT`: the revise payload replaces `lines` and `valid_until`, recomputes the provisional total, and increments `revision_count`. Revising from any state other than `SENT` is `ERR_QUOTATION_NOT_REVISABLE`, and revising is OCC-guarded per §2.6 via `expected_quotation_version`. A quotation may also be withdrawn from `DRAFT` or `SENT` (else `ERR_QUOTATION_NOT_WITHDRAWABLE`), landing in the terminal `WITHDRAWN` state; withdrawing the only `SENT` quotation returns the requisition from `QUOTED` to `SUBMITTED`, while withdrawing a `DRAFT` quotation touches nothing else.

Quotation expiry is **lazy**: no background job sweeps for stale quotes. Instead, any send, revise, or accept attempt made when the logical clock reads strictly after `valid_until` flips the quotation to `EXPIRED` and fails with `ERR_QUOTATION_EXPIRED`. The deadline is inclusive — acceptance at exactly `valid_until` is valid. When the only `SENT` quotation on a requisition expires this way, the requisition falls back `QUOTED → SUBMITTED` as described above.

Acceptance is the pivot of the whole system and is performed by the vessel's catering officer — ownership again means the acting `X-User-ID` must equal the vessel call's `id` (else `ERR_INSUFFICIENT_PERMISSIONS`). The checks fire in a defined order, and the ordering matters because earlier failures mask later ones: first the quotation must be `SENT` (else `ERR_QUOTATION_NOT_ACCEPTABLE`); then the validity window is checked, flipping the quotation to `EXPIRED` with `ERR_QUOTATION_EXPIRED` if the deadline has passed; then the cross-entity gate requires the vessel call to be `IN_PORT` — a quotation cannot be accepted for a vessel that has not arrived — else `ERR_VESSEL_CALL_NOT_IN_PORT`; then the credit gate compares the order's total against the agent's remaining credit per §3.9, surfacing `ERR_CREDIT_LIMIT_EXCEEDED`; then stock sufficiency per §3.5, surfacing `ERR_STOCK_INSUFFICIENT`; and finally cold-chain aggregate capacity per §3.5, surfacing `ERR_COLD_CHAIN_CAPACITY_EXCEEDED`.

A successful accept creates the `Order` in one atomic act: the quotation becomes `ACCEPTED`, the parent requisition becomes `CLOSED`, and the new order snapshots the quotation's lines into its own `lines` array — each entry carrying `catalog_item_id`, `qty_ordered`, a `qty_delivered` starting at zero, `unit_price_cents`, the `is_substitution` flag, and an `allocations` array of `{stock_lot_id, qty}` pairs produced by the reservation waterfall. The order's `quotation_id` links back to the accepted quotation; its `agent_id` is denormalized from the vessel call at acceptance time so exposure aggregation need not walk the chain. `subtotal_cents`, `rebate_cents`, and `total_cents` are frozen from the quotation's provisional pricing, `accepted_at` is stamped from the logical clock, `reservation_window_end` is captured from the vessel call's `scheduled_etd`, and the order opens as `OPEN` × `UNINVOICED`. The agent's `committed_exposure_cents` is recomputed to include the new order total. An order lookup returns both status dimensions plus the frozen totals; the orders created from a quotation can be listed as an array of zero or one element, and an agent's billed orders can be listed under the agent.

### 3.5. Holding the Goods: The Reservation Waterfall and the Cold-Chain Gate

Acceptance reserves stock through a deterministic waterfall. Order lines are processed in the order they appear in the quotation payload. For each line, the candidate lots are the stock lots of that catalog item whose free quantity — `on_hand_qty` minus `reserved_qty` — is strictly positive. Candidates are walked oldest first by `created_at` ascending, with ties broken by `lot_code` ascending (never by `id`); each visited lot contributes the minimum of the line's remaining need and the lot's free quantity. If any line cannot be fully allocated, the entire accept fails with `ERR_STOCK_INSUFFICIENT` and no partial reservation persists. Every allocated unit moves from `on_hand_qty` to `reserved_qty` on the contributing lot.

Two additional constraints ride on the waterfall. Items flagged `requires_cold_chain` may only draw from `COLD_STORE` lots — other tiers are not candidates at all. And each `COLD_STORE` lot enforces an aggregate capacity: the sum of reserved allocations whose half-open window `[accepted_at, reservation_window_end)` overlaps the new order's window, plus the new allocation, must not exceed the lot's `capacity_qty`. Windows that merely touch — one order's `reservation_window_end` equal to another's `accepted_at` — do **not** overlap under half-open semantics. A violation rejects the accept with `ERR_COLD_CHAIN_CAPACITY_EXCEEDED`.

### 3.6. To the Gangway: Delivery Scheduling, Dispatch, and Receipt

With an order open, a `WarehouseSupervisor` schedules delivery runs against it. Creation is nested under the order — the delivery's `order_id` comes from the path — and carries a planned `window_start` and `window_end` plus a `lines` array of `{catalog_item_id, qty}` with each `qty` at least 1. The window must be internally sane — `window_end` strictly after `window_start`, else `ERR_DELIVERY_WINDOW_INVERTED` — and it must fit inside the vessel's port stay: `window_start` at or after the call's effective arrival (`actual_eta` once set, otherwise `scheduled_eta`) and `window_end` at or before the effective departure (`actual_etd` once set, otherwise `scheduled_etd`). Containment is a closed interval; a window whose start equals the arrival or whose end equals the departure is admissible. A window outside the stay is `ERR_WINDOW_OUTSIDE_PORT_STAY`.

Two further gates guard scheduling. The quantity cap: for each line, the sum of planned quantities over the order's non-terminal deliveries (those `SCHEDULED` or `OUT_FOR_DELIVERY`) plus the line's already `qty_delivered` must not exceed `qty_ordered`, else `ERR_QTY_EXCEEDS_REMAINING`. And the customs gate: if any planned line's catalog item is `bonded_eligible`, the vessel call's `customs_clearance_status` must be `CLEARED` at scheduling time, else the create is refused with `ERR_CUSTOMS_CLEARANCE_REQUIRED`. A successfully created delivery is `SCHEDULED` and records the supervisor's `X-User-ID` as `created_by_user_id`.

Dispatch moves a delivery `SCHEDULED → OUT_FOR_DELIVERY` (any other state yields `ERR_DELIVERY_NOT_DISPATCHABLE`) and is performed by the warehouse. Receipt confirmation is the vessel's act and carries the gangway paperwork: the payload includes the printed `receiver_name`, the `signature_ref` of the gangway receipt signature, and the `confirmed_lines` array giving the actual received `qty` per item — each at least zero and at most the planned quantity on this delivery, else `ERR_QTY_EXCEEDS_REMAINING`. Confirmation requires the delivery to be `OUT_FOR_DELIVERY` (else `ERR_DELIVERY_NOT_CONFIRMABLE`), requires the acting officer to own the underlying vessel call (else `ERR_INSUFFICIENT_PERMISSIONS`), and enforces segregation of duties: the confirming `X-User-ID` must differ from the delivery's `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. A successful confirm stamps `confirmed_at` from the logical clock, moves the delivery to `DELIVERED`, accumulates each confirmed quantity into the order line's `qty_delivered`, deducts the confirmed quantities from both `reserved_qty` and `on_hand_qty` on the allocated lots, and re-derives the order's fulfillment dimension: if any line remains short the order moves `OPEN → PARTIALLY_DELIVERED` (or stays `PARTIALLY_DELIVERED`), and when every line's `qty_delivered` reaches its `qty_ordered` the order becomes `DELIVERED`. Confirmations never change the order's frozen totals, so agent exposure is unaffected by delivery activity, though the order's `version` still increments.

### 3.7. Cutting Losses: Order Cancellation and Vessel Departure

An `OPEN` order can be cancelled by a `ChandlerOpsManager`, but only while its payment dimension is `UNINVOICED`, or `INVOICED` with zero payments recorded on the invoice; any other combination yields `ERR_ORDER_NOT_CANCELLABLE`. Cancellation is a compensating cascade: the order's `fulfillment_status` becomes `CANCELLED`; its `SCHEDULED` and `OUT_FOR_DELIVERY` deliveries become `CANCELLED`; every allocation is released (`reserved_qty` returns to `on_hand_qty` on each lot); an unpaid `ISSUED` invoice is voided; and the agent's settled and committed exposures are recomputed, dropping this order's total from the committed leg.

Vessel departure is the heavier hammer. When a `ChandlerOpsManager` marks an `IN_PORT` call departed — the only state from which departure is permitted, else `ERR_VESSEL_CALL_NOT_IN_PORT` — `actual_etd` is stamped from the logical clock and three cascade hops fire. Every delivery of every order of the call still in `SCHEDULED` or `OUT_FOR_DELIVERY` becomes `FAILED`. Every order still `OPEN` becomes `CANCELLED`, releasing its allocations exactly as in the manual cancel, and if such an order carries an `ISSUED` invoice with no payments, that invoice becomes `VOID`. Orders left `PARTIALLY_DELIVERED` are not cancelled — they keep their delivered quantities — but the undelivered remainder of their reservations is released back to `on_hand_qty`. Every voiding and release recomputes the affected agent's exposure figures.

A scheduled call can also be cancelled outright while still `SCHEDULED` (else `ERR_VESSEL_CALL_NOT_CANCELLABLE`); because acceptance requires the vessel to be `IN_PORT`, no orders can exist for a `SCHEDULED` call, so the cascade is short: every requisition of the call in `DRAFT`, `SUBMITTED`, or `QUOTED` becomes `CLOSED`.

### 3.8. Customs: The Parallel Clearance Dimension

Bonded and duty-free handling is governed by the vessel call's second dimension. A `PortCustomsOfficer` records a decision on a call by submitting a `decision` of `CLEARED` or `REJECTED` with optional `notes`. The customs machine permits `PENDING → CLEARED`, `PENDING → REJECTED`, `REJECTED → CLEARED`, and `CLEARED → REJECTED` — a clearance can be revoked — but every decision requires the call's `status` to be `SCHEDULED` or `IN_PORT` (a departed or cancelled call cannot be re-cleared, surfacing `ERR_VESSEL_CALL_NOT_IN_PORT`), and a decision that merely restates the current clearance value is inadmissible (`ERR_CUSTOMS_STATE_INVALID`). Revoking a clearance does **not** retroactively reprice invoices already issued; it only affects pricing and delivery gating from that moment on.

Customs status reaches into commerce at three points: provisional and final duty-free eligibility (§2.8), the delivery scheduling gate (§3.6), and the substitution rules below (§3.10).

### 3.9. The Bill: Invoicing, FX Conversion, and the Duty Split

Once an order's fulfillment is `DELIVERED` — or `PARTIALLY_DELIVERED` after the vessel has departed — and its payment dimension is still `UNINVOICED`, a `FinanceController` issues the invoice (any other combination is `ERR_ORDER_NOT_INVOICABLE`). At most one non-`VOID` invoice may exist per order. Issuance carries a single input, `fx_rate_to_settlement` — the USD-to-settlement-currency conversion rate, which must be strictly positive, else `ERR_INVALID_FX_RATE` — and snapshots the agent's `settlement_currency` onto the invoice.

Issuance reprices everything with the final variant (§2.8): quantities are the delivered quantities, duty-free eligibility reads the clearance status at issuance, and cold hours are measured on actuals. Each invoice line carries `catalog_item_id`, delivered `qty`, `unit_price_cents`, a `duty_free` flag, its `duty_cents`, its `cold_surcharge_cents`, and the rounded `line_total_cents`. The duty-free test is conjunctive: the vessel call is `foreign_going`, the clearance status at issuance is `CLEARED`, and the item is `bonded_eligible`; items without `bonded_eligible` are always dutiable regardless of clearance. Aggregates follow the pinned rounding order: `duty_free_subtotal_cents` sums the line totals of duty-free lines, `dutiable_subtotal_cents` sums the line totals of dutiable lines (including their duty), `total_duty_cents` sums the per-line `duty_cents`, and `subtotal_cents` is the sum of the two subtotals. The volume rebate (§3.11) is evaluated on that `subtotal_cents` to yield `rebate_cents`, `total_usd_cents` is the subtotal minus the rebate, and `total_cents` converts to settlement cents by multiplying `total_usd_cents` by `fx_rate_to_settlement` and rounding half-up. `issued_at` is stamped from the logical clock, `due_date` is `issued_at` plus the agent's `payment_terms_days`, `issued_by_user_id` records the controller's `X-User-ID`, and `paid_amount_cents`, `credited_amount_cents`, and `fx_writeoff_cents` all start at zero. The invoice opens as `ISSUED`, the order's payment dimension moves `UNINVOICED → INVOICED`, and the agent's exposures are recomputed — the order leg leaves the committed sum and the invoice leg joins both sums.

An invoice's `outstanding_cents` is always `total_cents` minus `paid_amount_cents` minus `credited_amount_cents` minus `fx_writeoff_cents`; the invariant that paid plus credited plus write-off plus outstanding equals the total holds at every observable instant.

### 3.10. Getting Paid: Multi-Currency Payments and the Tolerance Write-Off

Payments are recorded by a `ShipAgentClerk` — and because the clerk's `X-User-ID` is the agent's `id`, a clerk may only pay invoices billed to their own agent (else `ERR_INSUFFICIENT_PERMISSIONS`). The invoice must be `ISSUED` or `PARTIALLY_PAID`; paying a `PAID`, `CREDITED`, or `VOID` invoice is `ERR_INVOICE_NOT_PAYABLE`. Each payment carries `amount_cents` of at least 1 and a `currency` (`USD`, `EUR`, `GBP`, or `SGD`). If the payment currency equals the invoice's `settlement_currency`, the converted amount is the tendered amount; otherwise the request must include a strictly positive `fx_rate_to_invoice_currency` — missing it is `ERR_CURRENCY_MISMATCH`, and a non-positive rate is `ERR_INVALID_FX_RATE` — and the converted amount is the tendered amount multiplied by that rate, rounded half-up. The payment's `converted_amount_cents` is stored on the record alongside `recorded_by_user_id`.

Settlement uses a fifty-cent closing tolerance. Let the new paid figure be the invoice's `paid_amount_cents` plus this payment's `converted_amount_cents`, and let the delta be that figure minus the `outstanding_cents` as it stood **before** this payment. If the delta exceeds 50 cents, the payment is rejected `ERR_PAYMENT_OVERPAYMENT`. If the new paid figure still falls short of outstanding by more than 50 cents, the invoice moves to `PARTIALLY_PAID` and `outstanding_cents` simply decreases by the converted amount. If the delta lands within the inclusive band of minus 50 to plus 50 cents, the invoice closes: it becomes `PAID`, `outstanding_cents` becomes zero, and the difference is booked as `fx_writeoff_cents` on the invoice — a positive write-off forgives an underpayment, a negative write-off books a small overpayment — with the same amount recorded as `writeoff_applied_cents` on this payment. A closing payment's write-off plus the invoice's paid and credited amounts must keep the outstanding invariant intact. Each payment recomputes the agent's exposures, and the order's payment dimension follows the invoice: `PARTIALLY_PAID` or `PAID` accordingly.

### 3.11. The Volume Rebate

The rebate is a threshold calculation applied inside order totals — identically in the provisional and final variants — and its apparent circularity is resolved by a pinned evaluation order. First the subtotal is computed **without** any rebate. Then the tier is read from that pre-rebate subtotal: a subtotal of at least 1,000,000 cents earns 7 percent; a subtotal of at least 500,000 cents but below 1,000,000 earns 4 percent; anything below earns nothing. The boundary is inclusive — a subtotal of exactly 500,000 cents earns 4 percent. The rebate is the subtotal multiplied by the tier percentage and divided by 100, rounded half-up, and the total is the subtotal minus the rebate. The tier is **never** re-evaluated on the post-rebate total, even though that total can drop below the tier boundary — a 500,000-cent subtotal yields a 20,000-cent rebate and a 480,000-cent total, and the 4 percent tier stands.

### 3.12. Quality Complaints, Four-Eyes Review, and Credit Notes

When a delivered order disappoints — spoiled provisions, damaged goods, wrong items, short quantities — the vessel's catering officer files a complaint against a `DELIVERED` delivery, with the complaint's `delivery_id` taken from the nested creation path. The payload carries a `lines` array in which each entry names a `catalog_item_id`, a `rejected_qty` of at least 1, and a `reason` of `SPOILED`, `DAMAGED`, `WRONG_ITEM`, or `SHORT`, plus a free-text `evidence_note`. No line may reject more of an item than that delivery actually delivered, else `ERR_QTY_EXCEEDS_REMAINING`. A new complaint is `SUBMITTED` with `reopen_count` zero and no `last_reviewer_user_id`.

Review belongs to a `QualityAssuranceLead`, who may accept or reject — both require the complaint to be `SUBMITTED`, else `ERR_COMPLAINT_NOT_REVIEWABLE`, and both stamp the reviewer's `X-User-ID` into `last_reviewer_user_id`. Acceptance additionally requires a creditable invoice to exist: among the order's invoices in `ISSUED` or `PARTIALLY_PAID`, the selector picks the latest `created_at` first, breaking ties toward the higher `total_cents`; if the candidate set is empty, or the computed credit amount would be zero or negative, acceptance fails with `ERR_NO_CREDITABLE_INVOICE`. A successful accept auto-creates exactly one `CreditNote` in `APPLIED` status and applies the cascade of §3.13.

Rejection moves the complaint to `REJECTED`. The vessel may then reopen it — `REJECTED → SUBMITTED` — through the officer who owns the call (else `ERR_INSUFFICIENT_PERMISSIONS`); reopening from any other state is `ERR_COMPLAINT_NOT_REOPENABLE`, and each successful reopen increments `reopen_count`. Once a complaint has been reopened at least once, a **four-eyes rule** arms: the next reviewer must be a different person than `last_reviewer_user_id`, else the accept or reject fails with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. The same segregation error also guards the delivery side, where creator and confirmer must differ (§3.6).

### 3.13. Credit Computation and Revocation

The auto-created credit note prices the complaint in three steps. The gross USD value sums, over the accepted complaint lines, the invoice line's `unit_price_cents` multiplied by `rejected_qty`, matching invoice lines by `catalog_item_id`; a complaint about an item absent from the invoice contributes zero. That USD figure is converted at the invoice's `fx_rate_to_settlement` and rounded half-up to yield `gross_amount_cents`. A restocking fee follows: `restocking_fee_cents` is the larger of 500 cents and 5 percent of `gross_amount_cents` rounded half-up. The creditable remainder is the invoice's `total_cents` minus its `credited_amount_cents` at the moment of issuance, and the note's `amount_cents` is the smaller of the gross-minus-fee figure and that remainder; if the result is not positive, the accept fails outright with `ERR_NO_CREDITABLE_INVOICE`.

Applying the note increases the invoice's `credited_amount_cents` by `amount_cents`, recomputes `outstanding_cents`, and may flip the invoice to `CREDITED` — from `ISSUED` when credited now equals the total, or from `PARTIALLY_PAID` when credited now covers the total minus paid — in which case the order's payment dimension becomes `CREDITED` as well. The agent's exposures recompute on every application.

A `FinanceController` may later revoke an `APPLIED` note (any other state yields `ERR_CREDIT_NOTE_NOT_REVOCABLE`); revocation is always permitted from `APPLIED`, even when it reopens a balance on a `CREDITED` invoice. Revocation flips the note to `REVOKED`, subtracts `amount_cents` from the invoice's `credited_amount_cents`, recomputes the outstanding balance, and re-derives the invoice status — a formerly `CREDITED` invoice returns to `ISSUED`, or to `PARTIALLY_PAID` if partial payments stand — with the order's payment dimension following and the agent's exposures recomputed once more.

### 3.14. Substitution: Admissibility and the Price Cap

Substitution rules apply both when a quotation is first drafted and on every revise. A quotation line flagged `is_substitution` must name its `substitution_of_item_id`, and three admissibility tests apply: the original requisition line must have `allows_substitution` true; the substitute item must share the original item's `category` and its `requires_cold_chain` flag; and every requisition line must be covered by exactly one quotation line, with a substitute covering its original. A violation is `ERR_SUBSTITUTION_NOT_ALLOWED`. Bonded parity adds a fourth test: a line may not substitute **into** a `bonded_eligible` item unless the original requisition line's item is also `bonded_eligible` — bonded and non-bonded goods are not interchangeable — and duty-free treatment never applies to items whose `bonded_eligible` is false regardless of customs state; breaching bonded parity is `ERR_BONDED_ITEM_NOT_ELIGIBLE`.

Price discipline caps the substitute: its `unit_price_cents` must not exceed the original item's `base_price_cents` multiplied by 115 and divided by 100, rounded half-up. The boundary is inclusive — a substitute priced exactly at the cap passes — and anything above is `ERR_SUBSTITUTION_PRICE_CAP_EXCEEDED`.

## 4. Endpoint Definitions

All endpoints live under the `/chandlery` prefix. Endpoints that create a new resource return HTTP 201; endpoints that modify an existing resource, drive a state transition, or read data return HTTP 200. The logical-clock endpoint returns 200. All list endpoints paginate per §2.3 and are open to every role.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/chandlery/_clock/set_current_utc` | Advance the server's logical clock to `to_iso8601`; returns `now_iso8601` | `ChandlerOpsManager` |
| POST | `/chandlery/ship-agents` | Register a paying ship agent | `FinanceController` |
| GET | `/chandlery/ship-agents/{id}` | Get one ship agent including computed exposure fields | All roles |
| GET | `/chandlery/ship-agents/{id}/vessel-calls` | List vessel calls served by this agent | All roles |
| GET | `/chandlery/ship-agents/{id}/orders` | List orders billed to this agent | All roles |
| POST | `/chandlery/vessel-calls` | Register a vessel port call | `ChandlerOpsManager` |
| GET | `/chandlery/vessel-calls/{id}` | Get one vessel call | All roles |
| POST | `/chandlery/vessel-calls/{id}/arrive` | Mark the vessel arrived; stamps `actual_eta` | `ChandlerOpsManager` |
| POST | `/chandlery/vessel-calls/{id}/depart` | Mark the vessel departed; cascades to deliveries, orders, invoices, stock, exposures | `ChandlerOpsManager` |
| POST | `/chandlery/vessel-calls/{id}/cancel` | Cancel a `SCHEDULED` vessel call | `ChandlerOpsManager` |
| POST | `/chandlery/vessel-calls/{id}/customs-clearance` | Record a customs `decision` (`CLEARED`/`REJECTED`) with optional `notes` | `PortCustomsOfficer` |
| POST | `/chandlery/catalog-items` | Create a catalog item; `sku` unique | `ChandlerOpsManager` |
| GET | `/chandlery/catalog-items` | List catalog items with filters and pagination | All roles |
| POST | `/chandlery/stock-lots` | Create a stock lot; `lot_code` unique per catalog item | `WarehouseSupervisor` |
| GET | `/chandlery/stock-lots` | List stock lots with filters and pagination | All roles |
| GET | `/chandlery/stock-lots/{id}` | Get one stock lot | All roles |
| POST | `/chandlery/stock-lots/{id}/adjustments` | Post an OCC-guarded cycle-count adjustment | `WarehouseSupervisor` |
| POST | `/chandlery/vessel-calls/{id}/requisitions` | Create a requisition (header + lines) for this call | `VesselCateringOfficer` |
| GET | `/chandlery/vessel-calls/{id}/requisitions` | List requisitions of a vessel call | All roles |
| GET | `/chandlery/requisitions/{id}` | Get one requisition | All roles |
| POST | `/chandlery/requisitions/{id}/submit` | Submit a `DRAFT` requisition | `VesselCateringOfficer` |
| POST | `/chandlery/requisitions/{id}/recall` | Recall a `SUBMITTED` requisition to `DRAFT` | `VesselCateringOfficer` |
| POST | `/chandlery/requisitions/{id}/quotations` | Draft a priced quotation against a `SUBMITTED`/`QUOTED` requisition | `ChandlerSalesRep` |
| GET | `/chandlery/requisitions/{id}/quotations` | List quotations of a requisition | All roles |
| GET | `/chandlery/quotations/{id}` | Get one quotation | All roles |
| POST | `/chandlery/quotations/{id}/send` | Send a `DRAFT` quotation to the vessel | `ChandlerSalesRep` |
| POST | `/chandlery/quotations/{id}/revise` | Revise a `SENT` quotation (OCC-guarded) | `ChandlerSalesRep` |
| POST | `/chandlery/quotations/{id}/accept` | Accept a `SENT` quotation; creates the order and reserves stock | `VesselCateringOfficer` |
| POST | `/chandlery/quotations/{id}/withdraw` | Withdraw a `DRAFT` or `SENT` quotation | `ChandlerSalesRep` |
| GET | `/chandlery/quotations/{id}/orders` | List the order created from this quotation (0 or 1 elements) | All roles |
| GET | `/chandlery/orders/{id}` | Get one order with both status dimensions and totals | All roles |
| POST | `/chandlery/orders/{id}/cancel` | Cancel an undelivered order (compensating cascade) | `ChandlerOpsManager` |
| POST | `/chandlery/orders/{id}/deliveries` | Schedule a gangway delivery within the port stay | `WarehouseSupervisor` |
| GET | `/chandlery/orders/{id}/deliveries` | List deliveries of an order | All roles |
| GET | `/chandlery/deliveries/{id}` | Get one delivery | All roles |
| POST | `/chandlery/deliveries/{id}/dispatch` | Mark a scheduled delivery out for delivery | `WarehouseSupervisor` |
| POST | `/chandlery/deliveries/{id}/confirm` | Vessel-side receipt confirmation with signature | `VesselCateringOfficer` |
| POST | `/chandlery/orders/{id}/invoices` | Issue the final-priced invoice for a delivered (or departed-partial) order | `FinanceController` |
| GET | `/chandlery/orders/{id}/invoices` | List invoices of an order (0 or 1 elements) | All roles |
| GET | `/chandlery/invoices/{id}` | Get one invoice | All roles |
| POST | `/chandlery/invoices/{id}/payments` | Record a payment (multi-currency, tolerance write-off) | `ShipAgentClerk` |
| GET | `/chandlery/invoices/{id}/payments` | List payments of an invoice | All roles |
| POST | `/chandlery/deliveries/{id}/complaints` | File a quality complaint against a delivered delivery | `VesselCateringOfficer` |
| GET | `/chandlery/deliveries/{id}/complaints` | List complaints on a delivery | All roles |
| POST | `/chandlery/complaints/{id}/accept` | Accept a complaint; auto-issues and applies a credit note | `QualityAssuranceLead` |
| POST | `/chandlery/complaints/{id}/reject` | Reject a complaint | `QualityAssuranceLead` |
| POST | `/chandlery/complaints/{id}/reopen` | Reopen a `REJECTED` complaint | `VesselCateringOfficer` |
| GET | `/chandlery/credit-notes` | List credit notes with optional `complaint_id` / `invoice_id` filters | All roles |
| GET | `/chandlery/credit-notes/{id}` | Get one credit note | All roles |
| POST | `/chandlery/credit-notes/{id}/revoke` | Revoke an `APPLIED` credit note (compensation) | `FinanceController` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VESSEL_CALL_NOT_FOUND` | 404 |
| `ERR_AGENT_NOT_FOUND` | 404 |
| `ERR_CATALOG_ITEM_NOT_FOUND` | 404 |
| `ERR_STOCK_LOT_NOT_FOUND` | 404 |
| `ERR_REQUISITION_NOT_FOUND` | 404 |
| `ERR_QUOTATION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_DELIVERY_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_COMPLAINT_NOT_FOUND` | 404 |
| `ERR_CREDIT_NOTE_NOT_FOUND` | 404 |
| `ERR_VESSEL_CALL_NOT_ARRIVABLE` | 409 |
| `ERR_VESSEL_CALL_NOT_IN_PORT` | 409 |
| `ERR_VESSEL_CALL_NOT_CANCELLABLE` | 409 |
| `ERR_CUSTOMS_STATE_INVALID` | 409 |
| `ERR_REQUISITION_NOT_SUBMITTABLE` | 409 |
| `ERR_REQUISITION_NOT_RECALLABLE` | 409 |
| `ERR_REQUISITION_HAS_LIVE_QUOTATION` | 409 |
| `ERR_REQUISITION_NOT_OPEN_FOR_QUOTES` | 409 |
| `ERR_QUOTATION_NOT_SENDABLE` | 409 |
| `ERR_QUOTATION_NOT_REVISABLE` | 409 |
| `ERR_QUOTATION_NOT_ACCEPTABLE` | 409 |
| `ERR_QUOTATION_NOT_WITHDRAWABLE` | 409 |
| `ERR_QUOTATION_EXPIRED` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_ORDER_NOT_INVOICABLE` | 409 |
| `ERR_DELIVERY_NOT_DISPATCHABLE` | 409 |
| `ERR_DELIVERY_NOT_CONFIRMABLE` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_COMPLAINT_NOT_REVIEWABLE` | 409 |
| `ERR_COMPLAINT_NOT_REOPENABLE` | 409 |
| `ERR_CREDIT_NOTE_NOT_REVOCABLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CUSTOMS_CLEARANCE_REQUIRED` | 403 |
| `ERR_BONDED_ITEM_NOT_ELIGIBLE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 |
| `ERR_DELIVERY_WINDOW_INVERTED` | 400 |
| `ERR_WINDOW_OUTSIDE_PORT_STAY` | 409 |
| `ERR_INVALID_QTY` | 400 |
| `ERR_QTY_EXCEEDS_REMAINING` | 409 |
| `ERR_SUBSTITUTION_NOT_ALLOWED` | 422 |
| `ERR_SUBSTITUTION_PRICE_CAP_EXCEEDED` | 422 |
| `ERR_STOCK_INSUFFICIENT` | 409 |
| `ERR_COLD_CHAIN_CAPACITY_EXCEEDED` | 409 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_CURRENCY_MISMATCH` | 422 |
| `ERR_INVALID_FX_RATE` | 400 |
| `ERR_NO_CREDITABLE_INVOICE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_PAYMENT_OVERPAYMENT` | 422 |
