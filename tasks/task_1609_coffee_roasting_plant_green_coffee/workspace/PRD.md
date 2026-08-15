# Coffee Roasting Plant API — Product Requirements Document

## 1. Introduction

A commercial coffee roaster lives between two clocks. The market clock re-prices unbought green coffee by the tick, and the biological clock degrades roasted coffee by the day. Sitting between them is a warehouse full of finite green mass that contracts, roast batches, blend recipes, and a lender's collateral reserve all compete for at once. This document specifies the Coffee Roasting Plant API, the system of record for that roastery: it books green coffee under both outright and price-to-be-fixed terms, tracks shipments from bill of lading to the quarantine pile, cups and disputes quality, finances inventory against pledged lots, governs roast profiles and versioned blend recipes, schedules roast batches whose inputs are allocated from released stock, and fulfills private-label, subscription, and wholesale orders against freshness-dated finished goods. All resources are mounted under the `/roastery` prefix.

Because the same pounds can be promised to a contract, a recipe, and a bank simultaneously, the API maintains a single derived warehouse position and refuses any mutation that would over-commit it. Because trading authority and risk authority must never sit in one pair of hands, approval-sensitive operations enforce segregation of duties. And because price-to-be-fixed contracts accumulate value event by event, every price-fix, hedge lift, and receipt recomputes counterparty exposure immediately. The sections below define the structural contract first, then the business workflows in pipeline order — green coffee in, roasted coffee out.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold for every endpoint and every resource in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operational capacity in which they act. The system recognizes exactly nine role names: `Trader`, `RiskManager`, `LogisticsCoordinator`, `WarehouseClerk`, `HeadRoaster`, `RoastOperator`, `QAGrader`, `FulfillmentPlanner`, and `PlatformAdmin`. A request with missing or malformed headers, or whose declared role is not one of these nine names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not authorized for the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

User identity in this system is deliberately opaque. When `X-User-Role` is `Trader`, `RiskManager`, `LogisticsCoordinator`, `WarehouseClerk`, `HeadRoaster`, `RoastOperator`, `QAGrader`, `FulfillmentPlanner`, or `PlatformAdmin` — this applies individually to each of the nine roles — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, for example as `fixed_by_trader_id` on a price-fix event, as `reviewed_by_qa_id` on a finalized cupping session, or as `approved_by_risk_id` on an approved futures hedge, but it never compares `X-User-ID` against any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification.
- `version` (integer): starts at its initial value on creation and increments by exactly 1 on every mutation of the resource — including system-driven mutations such as cascades, recomputations, and automatic state transitions, not only client-initiated writes.

One entity is the exception. A price-fix event is an append-only ledger entry: it carries `id` and `created_at`, and both `updated_at` and `version` are absent. It is never modified after recording; its `fixed_at` timestamp and `fixed_by_trader_id` are immutable.

A consequence worth internalizing: when a workflow below says a parent entity is "recomputed" or "transitioned," the parent's `version` moves. Clients relying on optimistic concurrency (§2.9) must therefore re-read after any operation that touches a related aggregate.

### 2.5. Money, Mass, and Measurement Precision

Different magnitudes in this domain carry different precision contracts, and the rules are uniform across the API.

Dollar amounts are rounded half-up to exactly 2 decimal places. This covers `priced_notional_usd`, `open_exposure_usd`, `reserve_advance_usd`, `realized_pnl_usd`, `utilized_usd`, and `collateral_value_usd`. Per-pound price levels and cost bases are kept at 5 decimal places, rounded half-up: `futures_price_usd_per_lb`, `weighted_avg_fixed_futures_usd`, `landed_cost_usd_per_lb`, `weighted_avg_landed_cost_usd`, `entry_price_usd_per_lb`, and `exit_price_usd_per_lb`. The roast shrinkage ratio `actual_yield_loss_pct` is likewise computed at 5 decimal places, rounded half-up. Mass is tracked in whole pounds: `total_lbs`, `fix_lbs`, `planned_lbs`, `received_lbs`, `allocated_lbs`, `reserved_lbs`, `hedge_lbs`, `packed_lbs`, and all position quantities are integers. Cupping arithmetic produces a `final_score` rounded half-up to 2 decimal places, while the `cup_score` stamped onto a green lot is expressed on the 0–100 Specialty Coffee Association scale with 1 decimal; the ten attribute scores that feed it are each between 0 and 10 in quarter-point (0.25) steps. The financing utilization ratio is the one value computed at full float precision, with no rounding.

### 2.6. The Warehouse Position and the Open-to-Sell Invariant

The system maintains exactly one warehouse position — a singleton, fully derived read model whose `position_as_of` timestamp is refreshed on every position-affecting mutation. It is never written directly; it is recomputed from source-of-truth rows whenever a green lot is created, released, rejected, or depleted, whenever a roast input allocation is created, consumed, or released, and whenever a financing reserve is created or released.

Four mass quantities define it. `physical_lbs` is the sum of `received_lbs` over all green lots whose `lot_status` is `RELEASED` or `QUARANTINE` — rejected lots do not count. `committed_lbs` is the sum of `allocated_lbs` over all roast input allocations in `allocation_status` `ACTIVE`. `reserved_for_financing_lbs` is the sum of `reserved_lbs` over all financing reserves in `reserve_status` `ACTIVE`. From these, `open_to_sell_lbs` is what remains once commitments and financing pledges are subtracted from the physical pile: physical minus committed minus reserved. This value must remain greater than or equal to zero at all times; any mutation that would drive it negative is rejected rather than applied.

The position also carries `weighted_avg_landed_cost_usd`, the mass-weighted average landed cost across `RELEASED` lots only — each released lot contributes its received pounds times its landed cost, summed, then divided by the total released pounds — at 5 decimal places, rounded half-up. When no lot is in `RELEASED`, this value is null.

### 2.7. Provisional and Final: the Dual Accounting Basis

Two financial quantities in this system are deliberately double-ledgered, and implementers must keep the variants distinct.

Counterparty exposure has two accounting treatments. The **provisional** variant is used for credit-limit gating when a new price-fix is attempted: it sums, over the counterparty's contracts whose `fulfillment_status` is `OPEN` or `PARTIALLY_RECEIVED`, each contract's `unpriced_lbs` marked at the current spot futures level plus the contract's `differential_usd_per_lb`. The current spot futures level is the `futures_price_usd_per_lb` of the most recent price-fix event recorded anywhere in the system, across any contract; if no price-fix exists yet anywhere, the fallback marks each unfixed pound at its differential alone — a flat price with the futures leg at zero. To this the provisional variant adds, for each `FIXED_OUTRIGHT` contract, the not-yet-received remainder (total pounds minus `received_lbs_accum`) times `fixed_price_usd_per_lb`, and finally subtracts, for every futures hedge in `hedge_status` `APPROVED` on those contracts, the hedge's pounds times its `entry_price_usd_per_lb`. The **final** variant is used for margin-call evaluation and counterparty reporting: it sums only the already-priced `priced_notional_usd` of those same `OPEN` or `PARTIALLY_RECEIVED` contracts — the unfixed remainder contributes nothing — and subtracts the same approved-hedge offset. Both variants are rounded half-up to 2 decimal places, and `open_exposure_usd` never goes negative.

Green-lot cost basis has the same split personality. When a lot is received under a `FIXED_OUTRIGHT` contract, its basis is simply the contract's `fixed_price_usd_per_lb`. Under a differential contract with no price-fix recorded at receipt time, the basis is provisional: the `differential_usd_per_lb` alone, and later price-fixes do **not** retroactively revalue the lot. Under a differential contract with at least one price-fix already recorded, the basis is final, locked at the receipt timestamp as `weighted_avg_fixed_futures_usd` plus `differential_usd_per_lb`. All three cases produce `landed_cost_usd_per_lb` at 5 decimal places, rounded half-up.

### 2.8. Validation Order and Nested-Path Resolution

Every request is checked against a fixed validation ladder, and the rung at which it fails determines the error it receives. First, the presence and well-formedness of `X-User-ID` and `X-User-Role` are verified, then that the declared role is a recognized role name — either failure yields `ERR_UNAUTHENTICATED`. Next, the role's authority over the target endpoint is checked, yielding `ERR_FORBIDDEN`. Then existence: every identifier in the URL path must resolve to an existing resource, validated strictly left to right so the first unresolvable identifier produces `ERR_NOT_FOUND` (HTTP 404) before later segments are even examined; identifiers referenced in the request body are likewise checked for existence with the same error. After existence comes state legality — the target entity must be in a state that permits the requested transition, otherwise `ERR_INVALID_STATE` (HTTP 409). Then optimistic concurrency, where applicable (§2.9), yields `ERR_STALE_VERSION` (HTTP 412). Only after all of these do the domain business rules run, each producing its own specific 422 error; where several business rules guard the same endpoint, §3 states the order in which they are evaluated alongside the workflow they protect. Structural request validation — required fields present, unknown fields rejected, enum values within their declared sets, and numeric ranges respected (for example `advance_rate_pct` between 0 and 1, `moisture_pct` between 0 and 100, attribute scores within 0–10 in 0.25 steps) — shares this same post-concurrency priority ordering and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and for each the version field is a non-optional part of the request.

Recording a price-fix against a contract requires the request to carry `expected_contract_version` holding the contract `version` the client last observed. If the contract's current `version` has advanced since — because another writer posted a fix, a receipt landed, or the contract was short-closed — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client never prices exposure it has not observed. Short-closing a contract carries the identical guard: the request must carry `expected_contract_version` matching the contract's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Approving a blend recipe is guarded against the parent product instead: the request must carry `expected_product_version` matching the product's current `version`, because a competing recipe approval may have superseded the recipe landscape since the client last read the product; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field.

### 2.10. Segregation of Duties

Two hand-offs in this plant must cross a desk boundary, and the system enforces both as domain validations rather than state rules — violations surface as `ERR_SEGREGATION_OF_DUTIES` (HTTP 422), never as `ERR_INVALID_STATE`.

A futures hedge is submitted by a `Trader` and approved by a `RiskManager`. The approving user's `X-User-ID` must differ from the submitting trader's `X-User-ID` recorded when the hedge was created; the same person may not approve their own hedge. A cupping session over a roast batch must be finalized by a `QAGrader` who is not the `RoastOperator` who ran that batch; the person who drove the drum may not grade their own roast.

### 2.11. The Logical Clock and Lazy Freshness Aging

All server-side timestamps in the system — `fixed_at`, `approved_at`, `packed_at`, `roast_completed_at`, `position_as_of` — are read from a logical clock, not the wall clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z; until an operator sets it, the clock returns precisely this default and never falls back to wall-clock time. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`.

Freshness aging is lazy. A finished goods lot does not flip from `FRESH` to `STALE` by timer; the transition is evaluated when the lot is read or allocated against, comparing the current server time to its `sellable_until`. Advancing the logical clock therefore triggers re-evaluation on the next read of any finished goods lot.

## 3. Business Logic & Workflows

### 3.1. Counterparty Onboarding and the Contract Book

Everything commercial begins with a counterparty. A `Trader` registers one by supplying a `counterparty_ref` (the external supplier or importer reference code), a `legal_name`, a `counterparty_kind` of `SUPPLIER`, `IMPORTER`, or `CUSTOMER`, and a `credit_limit_usd` bounding the open exposure the house will tolerate. A new counterparty arrives with `counterparty_status` `ACTIVE` and `open_exposure_usd` zero. The counterparty book can be browsed with a `counterparty_kind` filter.

Exposure is a living number. It is recomputed on contract booking, on every price-fix, on hedge approval and lift, on shipment receipt, and on short-close or cancellation, always per the provisional and final variants of §2.7. When a recompute shows `open_exposure_usd` strictly greater than `credit_limit_usd`, the counterparty's `counterparty_status` flips from `ACTIVE` to `SUSPENDED`; when a later recompute brings exposure back to at or below the limit, the status returns from `SUSPENDED` to `ACTIVE`. (A manual `RiskManager` suspension also exists operationally but exposes no endpoint in this version; it is treated as derived, informational bookkeeping.) Both flips increment the counterparty's `version`. Closure — `ACTIVE` to `CLOSED` — is terminal bookkeeping likewise not exposed as an endpoint in v1, and is permitted only when the counterparty has no contract whose `fulfillment_status` is `OPEN` or `PARTIALLY_RECEIVED`.

Against an active counterparty, the `Trader` books a green coffee contract: a `contract_ref` such as a desk reference code, a `pricing_mode` of `DIFFERENTIAL_PTBF` or `FIXED_OUTRIGHT`, a `coffee_grade` of `SHB`, `HG`, `NY2_3`, or `ROBUSTA_GRADE1`, the `total_lbs` contracted, and a delivery window bounded by `delivery_window_start` and `delivery_window_end`. The window end must be strictly after the start; a non-positive window is rejected with `ERR_INVALID_DELIVERY_WINDOW`. The price fields are mode-conditional: an outright contract carries `fixed_price_usd_per_lb` and leaves `differential_usd_per_lb` null, while a differential contract carries `differential_usd_per_lb` over the ICE C futures and leaves `fixed_price_usd_per_lb` null. The contract's `counterparty_id` ties it to the selling counterparty in whose book it was created.

A new contract's two parallel state dials start at `fulfillment_status` `OPEN` on the receipt side. On the pricing side, a differential contract starts at `pricing_status` `UNFIXED` with `fixed_lbs_accum` zero; an outright contract moves immediately to `NOT_APPLICABLE`, with `fixed_lbs_accum` set to `total_lbs`, `unpriced_lbs` zero, `weighted_avg_fixed_futures_usd` left null (there is no futures leg), and `priced_notional_usd` computed as `total_lbs` times the outright price, rounded half-up to 2 decimals. Either way, `received_lbs_accum` starts at zero and the counterparty's `open_exposure_usd` is recomputed.

A contract that never got off the ground can be cancelled by a `Trader`: from `OPEN` to `CANCELLED`, permitted only while no shipment exists for the contract, no price-fix event has been recorded, and no futures hedge is in `WORKING` or `APPROVED`. Cancellation writes `unpriced_lbs` to zero, recomputes counterparty exposure, and increments the contract `version`; attempting it against a contract that has already seen shipments, fixes, or live hedges is rejected with `ERR_INVALID_STATE`. The book can be listed filtered by `counterparty_id`, `pricing_status`, or `fulfillment_status`.

### 3.2. Pricing the Unpriced: Price-Fix Events

A differential contract is a promise to name a futures level later. A `Trader` converts floating pounds into priced pounds by recording a price-fix event carrying `fix_lbs` and the `futures_price_usd_per_lb` observed at the moment of the fix (5 decimal places), together with the OCC guard `expected_contract_version` described in §2.9.

Three gates guard the fix, evaluated in this order after the generic ladder of §2.8. First the credit gate: the fix must not push the counterparty's **provisional** open exposure above `credit_limit_usd`, otherwise the fix is refused with `ERR_CREDIT_LIMIT_EXCEEDED` — this is the one place the provisional variant of §2.7 gates a write. Second the over-fix cap: the cumulative `fixed_lbs_accum` plus the new `fix_lbs` must not exceed the contract's `total_lbs`, otherwise `ERR_OVER_FIX`. Third the quantity sanity check: `fix_lbs` must be strictly positive and `futures_price_usd_per_lb` strictly positive, otherwise `ERR_INVALID_FIX_QUANTITY`. State preconditions apply before all of these: the contract must be a `DIFFERENTIAL_PTBF` contract — a fix attempt against an outright contract is rejected with `ERR_INVALID_STATE` — and its `fulfillment_status` must be `OPEN`, `PARTIALLY_RECEIVED`, or `FULLY_RECEIVED`, since pricing legitimately continues after the coffee has finished arriving; a fix against a `SHORT_CLOSED` or `CANCELLED` contract is likewise `ERR_INVALID_STATE`.

A recorded fix appends an immutable `PriceFixEvent` whose `contract_id` ties it to the contract, stamped with the server clock as `fixed_at` and the caller as `fixed_by_trader_id`. The contract's `fixed_lbs_accum` grows by `fix_lbs`, and `weighted_avg_fixed_futures_usd` is recomputed as the pound-weighted average futures level across **all** of the contract's price-fix events — each event contributes its `fix_lbs` times its `futures_price_usd_per_lb`, the products summed and divided by the total fixed pounds, at 5 decimal places rounded half-up; the value stays null until the first fix exists. `priced_notional_usd` follows as `fixed_lbs_accum` times the sum of `weighted_avg_fixed_futures_usd` and `differential_usd_per_lb`, rounded half-up to 2 decimals, and `unpriced_lbs` is `total_lbs` minus `fixed_lbs_accum`. The counterparty's `open_exposure_usd` is recomputed, and the contract `version` increments by 1.

The pricing dial moves with the accumulation. A fix that leaves pounds still unpriced carries the contract from `UNFIXED` to `PARTIALLY_FIXED`. A fix whose cumulative total lands exactly on `total_lbs` — neither more (that is the over-fix rejection above) nor less — carries the contract to `FULLY_FIXED`, whether from `UNFIXED` in a single full fix or from `PARTIALLY_FIXED` as the final tranche. Reaching `FULLY_FIXED` has one far-reaching side effect: every futures hedge on the contract still sitting in `APPROVED` is lifted automatically, as detailed in §3.3. Price-fix history is listed per contract, oldest first.

### 3.3. Futures Hedges, Lifts, and Short-Close Bookkeeping

Against a differential contract's floating exposure, a `Trader` places a futures hedge naming the contract in the request path context, with a `hedge_side` of `BUY_FUTURES` or `SELL_FUTURES`, a strictly positive `hedge_lbs`, and an `entry_price_usd_per_lb` at 5 decimal places. The hedge is born `WORKING`, and the submitter's `X-User-ID` is recorded for the segregation-of-duties check that comes later.

Approval belongs to the `RiskManager`. Two business validations guard it, evaluated in order: first segregation of duties — the approver must not be the trader who submitted the hedge, per §2.10, otherwise `ERR_SEGREGATION_OF_DUTIES`; then the over-hedge cap — the cumulative `hedge_lbs` across the contract's already-`APPROVED` hedges plus this hedge's pounds must not exceed the contract's `unpriced_lbs` at approval time, otherwise `ERR_OVER_HEDGE`. Because both are validations rather than state preconditions, their failures never masquerade as `ERR_INVALID_STATE`. A successful approval moves `hedge_status` from `WORKING` to `APPROVED`, stamps `approved_by_risk_id` with the approver's `X-User-ID`, recomputes counterparty exposure, and increments the hedge `version`.

Lifting belongs back to the `Trader`, who supplies an `exit_price_usd_per_lb` that must be provided and strictly positive. Realized P&L is then computed at 2 decimals, rounded half-up: for a `BUY_FUTURES` hedge, the exit price minus the entry price, times `hedge_lbs`; for a `SELL_FUTURES` hedge, the entry price minus the exit price, times `hedge_lbs`. `realized_pnl_usd` is null until the hedge is lifted. The lift closes the offsetting position, so counterparty `open_exposure_usd` is recomputed. A hedge can also be lifted without a human touch: when its contract reaches `FULLY_FIXED` (§3.2), every `APPROVED` hedge auto-transitions to `LIFTED` with `exit_price_usd_per_lb` set to the contract's final `weighted_avg_fixed_futures_usd`, and P&L is realized by the same formula.

Cancellation rounds out the hedge lifecycle. A `Trader` may cancel a hedge only while it is `WORKING`; and when a contract is short-closed, every hedge of that contract in `WORKING` or `APPROVED` transitions to `CANCELLED` automatically. Hedges can be listed per contract, filterable by `hedge_status`.

Short-closing is how a `Trader` writes off a shortfall. From `PARTIALLY_RECEIVED` — and only from there, with `received_lbs_accum` still below `total_lbs` and no shipment of the contract still in `BOOKED`, `IN_TRANSIT`, or `ARRIVED` — the short-close moves the contract to `SHORT_CLOSED`, sets `unpriced_lbs` to zero (the undelivered remainder is written off; there is no obligation to fix it), cancels the working and approved hedges as just described, recomputes counterparty exposure, and increments the contract `version`. The request must carry the `expected_contract_version` OCC guard of §2.9; attempting the transition from any other fulfillment state is `ERR_INVALID_STATE`.

### 3.4. Inbound Logistics: Booking, Transit, and Warehouse Receipt

A `LogisticsCoordinator` books a shipment against a contract with a `shipment_ref` (the bill-of-lading or booking reference), a `planned_lbs`, and a `scheduled_arrival` timestamp. Two booking validations run in order: first the delivery-window check — `scheduled_arrival` must fall within the contract's delivery window, inclusive of both `delivery_window_start` and `delivery_window_end`, otherwise `ERR_DELIVERY_WINDOW_VIOLATION`; then the aggregate capacity check — the new `planned_lbs` plus the summed `planned_lbs` of the contract's sibling shipments that are not `CANCELLED` must not exceed the contract's `total_lbs`, otherwise `ERR_CONTRACT_CAPACITY_EXCEEDED`. A booked shipment starts with `transit_status` `BOOKED`, `qc_status` `NOT_REQUIRED`, `dispute_status` `NONE`, and `received_lbs` null.

Transit is a two-step drumbeat owned by the `LogisticsCoordinator`: departing moves `BOOKED` to `IN_TRANSIT`, arriving moves `IN_TRANSIT` to `ARRIVED`, and each step increments the shipment `version`. A booking can be cancelled only before it ships — `BOOKED` to `CANCELLED` — because once the coffee is moving it must be received or disputed, not erased. Any of these attempted from the wrong state is `ERR_INVALID_STATE`.

Receipt belongs to the `WarehouseClerk`, who records `received_lbs`, a `lot_code` (the mill or ICO lot code), the intake `moisture_pct` (a percentage between 0 and 100), and a `warehouse_location` zone code. The received mass must be strictly positive and must not exceed `planned_lbs` — over-receipt is not permitted — or the receipt is rejected with `ERR_INVALID_STATE`; and the shipment must be `ARRIVED` to be received at all. Receipt moves the shipment to `RECEIVED`, flips its `qc_status` from `NOT_REQUIRED` to `PENDING_CUP`, and creates exactly one green lot child in `QUARANTINE` carrying the received mass and intake measurements. The lot's `landed_cost_usd_per_lb` is fixed at this moment per the dual-basis rule of §2.7, and its `available_lbs` is derived as its `received_lbs` minus any `ACTIVE` roast allocations against it minus any pounds pledged under active financing reserves.

Receipt rolls uphill. The contract's `received_lbs_accum` is recomputed as the sum of lot `received_lbs` across its shipments in `RECEIVED` or later; crossing above zero for the first time moves `fulfillment_status` from `OPEN` to `PARTIALLY_RECEIVED`, and reaching `total_lbs` exactly moves it on to `FULLY_RECEIVED`. Both the shipment and the contract increment their `version`. Green lots can be listed filtered by `shipment_id` or `lot_status`.

A green lot's own lifecycle is short and quality-gated: from `QUARANTINE` it is either released or rejected by cupping (or released later via a dispute, §3.5), and a `RELEASED` lot becomes `DEPLETED` when its `available_lbs` reaches zero with no `ACTIVE` allocation remaining. Every transition recomputes the warehouse position of §2.6.

### 3.5. Quality Cupping, Verdicts, and Dispute Resolution

Quality is adjudicated in a cupping session opened by a `QAGrader`. The session's `subject_kind` is `GREEN_LOT` or `ROAST_BATCH`, and its `subject_id` is polymorphic: for a green-lot subject the caller may pass either the lot's own `id` or the parent shipment's `id` — the server resolves a shipment reference to that shipment's single green lot child, since each receipt produces exactly one lot, and the stored value is always the resolved lot `id`, never the alias — while for a roast-batch subject the batch `id` is required directly. The panel records `panelist_count` and ten attribute scores — `score_aroma`, `score_flavor`, `score_aftertaste`, `score_acidity`, `score_body`, `score_balance`, `score_uniformity`, `score_clean_cup`, `score_sweetness`, and `score_overall` — each between 0 and 10 in 0.25 steps, plus `defects_subtracted`, a non-negative integer of total defect deductions across the panel. A freshly opened session sits with `session_verdict` `PENDING_REVIEW`.

Not everything is cuppable at all times. A green lot is cuppable only in `QUARANTINE`; a roast batch is cuppable only while its `qc_status` is `PENDING_QC`. The check is applied both when a session is opened and when it is finalized, and a subject out of position is rejected with `ERR_NOT_CUPPABLE` (HTTP 409).

Finalization by a `QAGrader` runs its checks in a fixed order: segregation of duties first — for a `ROAST_BATCH` subject the finalizer must not be the `RoastOperator` who ran the batch (§2.10), otherwise `ERR_SEGREGATION_OF_DUTIES`; then the cuppable-state check, `ERR_NOT_CUPPABLE`; then the panel check — a `panelist_count` below 3 cannot produce a decisive verdict and is rejected with `ERR_PANEL_TOO_SMALL`. A successful finalization computes `final_score` as the sum of the ten attribute scores minus `defects_subtracted`, rounded half-up to 2 decimal places, stamps `reviewed_by_qa_id` with the caller's `X-User-ID`, and sets the verdict. The pass bar differs by subject: a green lot passes with a `final_score` of at least 80.00 — exactly 80.00 passes — while roasted product passes at a lower bar, at least 78.00, with exactly 78.00 passing. Anything below the bar fails.

The verdict cascades. A green-lot `PASS` moves the lot from `QUARANTINE` to `RELEASED`, sets its `cup_score` to the session's final score, moves the shipment's `qc_status` from `PENDING_CUP` to `CUP_PASSED`, and recomputes the warehouse position — the lot now counts toward physical mass and becomes eligible for allocation and financing collateral. A green-lot `FAIL` moves the lot from `QUARANTINE` to `REJECTED`, still sets `cup_score`, moves the shipment to `CUP_FAILED`, opens a dispute by moving `dispute_status` from `NONE` to `DISPUTED`, and recomputes the position with the rejected lot excluded from physical mass. Over a roast batch, a `PASS` moves the batch's `qc_status` from `PENDING_QC` to `QC_PASSED`; a `FAIL` moves it to `QC_FAILED` and, defensively, any finished goods lots already packed from the batch transition to `RECALLED` — packing normally requires a pass, so this path exists only as a consistency backstop.

A disputed shipment is settled by a `Trader` with an `outcome` of `ACCEPT` or `REJECT`, provided the shipment is `DISPUTED` and its `qc_status` is `CUP_FAILED` — otherwise `ERR_INVALID_STATE`. Accepting the coffee at a negotiated discount moves `dispute_status` to `RESOLVED_ACCEPTED` and, remarkably, moves the lot from `REJECTED` back to `RELEASED`: its `landed_cost_usd_per_lb` is recomputed as the original landed cost times one minus the supplied `discount_pct`, at 5 decimal places rounded half-up, and the warehouse position is recomputed with the lot once again counting toward physical mass. Rejecting the coffee moves the dispute to `RESOLVED_REJECTED`; the lot stays `REJECTED` and is marked for return or destruction, leaving the position's physical mass unchanged since the rejected lot was already excluded. The rejection typically leaves the contract under-received; whether to write the shortfall off via a short-close (§3.3) is a separate, deliberate `Trader` decision.

### 3.6. Collateral and Credit: Inventory Financing Lines and Reserves

Released green coffee is bankable. A `RiskManager` opens an inventory financing line by naming the `lender_name`, a `facility_limit_usd` capping total borrowings, and an `advance_rate_pct` — the fraction of eligible collateral value the lender will advance, between 0 and 1. A new line opens with `financing_status` `OPEN` and `utilized_usd` and `collateral_value_usd` both zero.

Pledging coffee to the line creates a financing reserve naming the `green_lot_id` pledged and the `reserved_lbs` — strictly positive — within the line's context (the reserve's `financing_line_id` records which line it belongs to), and the line's `version` increments with the pledge. Two validations guard the pledge, evaluated in order: first facility headroom — the line's `utilized_usd` plus the new reserve's advance must not exceed `facility_limit_usd`, otherwise `ERR_FACILITY_LIMIT_EXCEEDED`; then pledgeability — the lot must be in `RELEASED` and `reserved_lbs` must not exceed the lot's `available_lbs` at pledge time, otherwise `ERR_LOT_NOT_PLEDGEABLE`. The reserve's `reserve_advance_usd` is computed as `reserved_lbs` times the lot's `landed_cost_usd_per_lb` times the line's `advance_rate_pct`, rounded half-up to 2 decimals. Pledging moves the pounds out of the open pool: the lot's `available_lbs` falls by `reserved_lbs`, the line's `utilized_usd` rises by the advance, its `collateral_value_usd` rises by `reserved_lbs` times the lot's landed cost, and the warehouse position is recomputed (§2.6). A suspension interlocks here: a line in `SUSPENDED` blocks the creation of new reserves.

Releasing a reserve is the mirror image. An `ACTIVE` reserve transitions to `RELEASED`; the pledged mass returns to the lot's `available_lbs`; the line's `utilized_usd` falls by the reserve's advance and its `collateral_value_usd` falls by the reserve's poundage times the lot's landed cost; the position recomputes; and both the reserve and the line increment their `version`. Releasing a reserve that is not `ACTIVE` is `ERR_INVALID_STATE`.

The line itself is managed by the `RiskManager` through three state moves. Suspending moves `OPEN` to `SUSPENDED`, blocking new reserves while leaving existing ones untouched. Unsuspending moves `SUSPENDED` back to `OPEN`. Closing moves `OPEN` to `CLOSED` — terminal — and is permitted only when `utilized_usd` is zero and no reserve remains `ACTIVE`. The line's utilization ratio, `utilized_usd` divided by `collateral_value_usd` at full float precision (null when collateral is zero), is informational only: it drives no state. Reserves can be listed filtered by `financing_line_id`, `green_lot_id`, or `reserve_status`.

### 3.7. Products, Roast Profiles, and Blend Recipe Governance

On the production side, the `HeadRoaster` first defines roast profiles: a `profile_code` such as a city-roast curve code, a `charge_temp_c` in Celsius, a `target_drop_temp_c` that must be strictly greater than the charge temperature, an `expected_yield_loss_pct` shrinkage fraction between 0 and 1 (0.16 for a sixteen percent expected loss), and a `shrinkage_alert_band_pct` tolerance band between 0 and 0.10 around that expectation.

Products come next: a `sku`, a `display_name`, a `channel` of `PRIVATE_LABEL`, `SUBSCRIPTION`, or `WHOLESALE`, a `target_roast_profile_id` naming the profile the product is roasted to, and a strictly positive `freshness_days` shelf life counted from roast completion. A product's `product_status` is always `ACTIVE` — that is the sole value in this version, set at creation with no transitions defined. Products can be listed filtered by `target_roast_profile_id`, `channel`, or `product_status`.

Blend recipes are versioned per product. Creating a recipe produces a `DRAFT` whose `recipe_version` is one more than the highest version existing for that product — 1, 2, 3, and so on monotonically. Components are added to the draft with a `required_grade` (one of the four green grades), a `component_pct` fraction of the blend between 0 and 1, and an optional substitution pair: a `substitution_grade` that may stand in when the required grade runs short — which must differ from `required_grade`, with null meaning no substitution is permitted — and a `substitution_max_pct` capping what fraction of the component's mass may come from the substitute. The pair is all-or-nothing: `substitution_grade` is non-null exactly when `substitution_max_pct` is non-null, and any inconsistency — a grade without a cap, a cap without a grade, or a substitute equal to the required grade — is rejected with `ERR_SUBSTITUTION_RULE_INVALID`, both when a component is added and again at approval time.

Approval is the governance gate, exercised by the `HeadRoaster` and guarded by the `expected_product_version` OCC rule of §2.9 against the parent product. The approval validations run in a fixed order after the generic ladder: first the component-sum check — the `component_pct` values across all of the recipe's components must sum to exactly 1.00000 at five-decimal precision, otherwise `ERR_RECIPE_COMPONENT_SUM_INVALID`; then the substitution-consistency check, otherwise `ERR_SUBSTITUTION_RULE_INVALID`; and no other recipe for the same product may already sit in `APPROVED` bearing the same `recipe_version`. On approval the recipe moves from `DRAFT` to `APPROVED`, `approved_at` is stamped from the server clock, any previously `APPROVED` recipe for the same product auto-transitions from `APPROVED` to `SUPERSEDED`, and both the recipe and the product increment their `version` — which is precisely why approval carries a product-version guard. Supersession does not disturb batches already scheduled: they keep their `recipe_version_pinned`, and the staleness check fires later, at roast start (§3.8). A draft that was never used can be moved from `DRAFT` to `RETIRED` by the `HeadRoaster`, but only while no roast batch references it. Recipes are listed per product, filterable by `recipe_status`.

### 3.8. Roast Production: Scheduling, Allocation, and Yield Accounting

A `RoastOperator` schedules a batch by naming a `product_id`, a `recipe_id`, and the `scheduled_green_lbs` to charge into the drum. Creation runs the inventory check first — sufficient `RELEASED` green mass must exist to satisfy every component, within the substitution rules, otherwise `ERR_INSUFFICIENT_GREEN_INVENTORY` — and then the recipe check: the pinned recipe must be `APPROVED` and must belong to the specified product, otherwise `ERR_RECIPE_NOT_APPROVED`. At schedule time the recipe's current `recipe_version` is copied into the batch's `recipe_version_pinned`, freezing the batch's view of the recipe even if the recipe book moves on.

Allocation happens in the same call, atomically, as a waterfall over the pinned recipe's components. Components are processed in descending order of `component_pct`, ties broken by the component's earlier creation. Each component's target is `scheduled_green_lbs` times its `component_pct`, rounded half-up to whole pounds; the rounding remainder is then reconciled into the largest component by percentage (ties again broken by earliest creation) so the allocated total equals `scheduled_green_lbs` exactly. For each component the waterfall draws first from primary lots — `RELEASED` green lots whose grade matches the component's `required_grade`, oldest lot first by creation order, a strict first-in-first-out by receipt — taking from each lot the smaller of its `available_lbs` and the component's remaining target. When the primary pipeline runs short and the component declares a `substitution_grade`, substitute lots of that grade are drawn in the same oldest-first order, but only up to a cap: the component's substitution allowance is its target pounds times `substitution_max_pct`, rounded down to whole pounds (zero when no substitution is declared). Any allocation drawn from a lot whose grade differs from the component's `required_grade` is flagged `is_substitution`. If a component still cannot be filled, the entire batch creation fails with `ERR_INSUFFICIENT_GREEN_INVENTORY` — no partial batch is persisted. Each allocation row records its `roast_batch_id`, `green_lot_id`, and `component_id`, with a strictly positive `allocated_lbs`, and starts `ACTIVE`; the warehouse position's committed mass rises accordingly. Batches can be listed filtered by `product_id`, `recipe_id`, `production_status`, or `qc_status`, and allocations filtered by `roast_batch_id`, `green_lot_id`, `component_id`, or `allocation_status`.

Starting the roast — `SCHEDULED` to `IN_DRUM` — re-validates the world. The pinned recipe must still be `APPROVED` and its current `recipe_version` must still equal `recipe_version_pinned`; a recipe superseded since scheduling trips this stale-recipe guard and the start is rejected with `ERR_INVALID_STATE`. Every allocation must still be `ACTIVE`, and the allocations must sum exactly to `scheduled_green_lbs`. Starting consumes the inputs: every allocation moves from `ACTIVE` to `CONSUMED`, each referenced lot's `available_lbs` falls by its allocated pounds — a lot driven to zero with no remaining `ACTIVE` allocations becomes `DEPLETED` — and the warehouse position recomputes.

Finishing the roast — `IN_DRUM` to `ROASTED` — is where yield is booked. The operator reports `actual_roasted_lbs`, which must be strictly positive and strictly less than `scheduled_green_lbs`; a zero or a hundred-percent yield is physically impossible and is rejected with `ERR_INVALID_YIELD`. The batch's `actual_yield_loss_pct` is computed as one minus the ratio of `actual_roasted_lbs` to `scheduled_green_lbs`, at 5 decimal places rounded half-up, and its `yield_variance_flag` is set against the product's roast profile: strictly above `expected_yield_loss_pct` plus `shrinkage_alert_band_pct` is `ABOVE_BAND`, strictly below the expectation minus the band is `BELOW_BAND`, and anything in between — including exactly on either boundary — is `WITHIN_BAND`. Until the roast is finished and this comparison can be made, the flag reads `UNKNOWN`. The `roast_completed_at` timestamp is stamped from the server clock — this is the instant the freshness clock starts — and the batch's `qc_status` moves from `NOT_REQUIRED` to `PENDING_QC`, awaiting the cupping verdict of §3.5.

Packing — `ROASTED` to `PACKED` — is allowed only after the batch's `qc_status` is `QC_PASSED`, and the `packed_lbs` must be strictly positive and no more than `actual_roasted_lbs`, otherwise `ERR_INVALID_PACK_QUANTITY`. Packing creates a finished goods lot (§3.9). Finally, a batch still in `SCHEDULED` can be voided: voiding moves it to `VOIDED`, releases every allocation from `ACTIVE` back to `RELEASED`, returns the mass to each lot's `available_lbs`, and recomputes the position. Actions attempted from the wrong production state are `ERR_INVALID_STATE`.

### 3.9. Finished Goods, Freshness, and Order Fulfillment

Packing a passed batch produces a finished goods lot: its `product_id` is copied from the batch, `packed_at` is stamped from the server clock, and `packed_lbs` records the packed mass. The lot's `sellable_until` is computed as the batch's `roast_completed_at` plus the product's `freshness_days` days — each day exactly 86,400 seconds — and its `available_lbs` is `packed_lbs` minus the pounds held by `ACTIVE` fulfillment lines. It is born `FRESH`.

Freshness decays lazily, per §2.11: when the current server time is strictly greater than `sellable_until`, the lot's `lot_status` flips from `FRESH` to `STALE` at the moment it is read or allocated against — at exactly `sellable_until` the lot is still `FRESH`. Staling honors existing reservations: `ACTIVE` fulfillment lines stay `ACTIVE`, but new allocations against the lot are rejected. A lot at zero `available_lbs` becomes `DEPLETED`, whether from `FRESH` or from `STALE` once everything has shipped. And if a packed batch's `qc_status` ever flips to `QC_FAILED`, the defensive recall cascade moves the lot from `FRESH` to `RECALLED`; its active fulfillment lines are `RELEASED`, and the recalled mass is **not** returned to sellable inventory — recalled product is destroyed. Finished lots can be listed filtered by `roast_batch_id`, `product_id`, or `lot_status`.

Outbound, a `FulfillmentPlanner` drafts an order against a buying counterparty with `customer_counterparty_id`, a `channel` of `PRIVATE_LABEL`, `SUBSCRIPTION`, or `WHOLESALE`, and a `requested_ship_date`; the order opens in `DRAFT` with `total_reserved_lbs` zero. Lines are added to the draft naming a `finished_goods_lot_id` and the `allocated_lbs` to draw from it, with the line's `order_id` tying it to its order.

Reservation — `DRAFT` to `RESERVED` — is the inventory commitment point, and it requires at least one line. Its validations run in order: first freshness — every referenced lot must be `FRESH` at reservation time, since `STALE` or `RECALLED` lots cannot be allocated, otherwise `ERR_STALE_GOODS`; then sufficiency — each line's `allocated_lbs` must not exceed its lot's `available_lbs` at that moment, otherwise `ERR_INSUFFICIENT_FINISHED_GOODS`. Reserving activates every line (each moves to `ACTIVE`), decrements each lot's `available_lbs`, and computes the order's `total_reserved_lbs` as the sum of its `ACTIVE` lines. From there the planner packs the order — `RESERVED` to `PACKED` — and ships it — `PACKED` to `SHIPPED` — which moves every line to `SHIPPED` and depletes any finished lot whose `available_lbs` has reached zero. Cancellation is possible from `DRAFT` and from `RESERVED`: cancelling a reserved order releases every `ACTIVE` line to `RELEASED` and returns the pounds to each lot's `available_lbs`, while cancelling a draft has no inventory to unwind. Every one of these moves increments the order's `version`, and any transition attempted from the wrong state is `ERR_INVALID_STATE`. Orders are listed with filters by `customer_counterparty_id`, `order_status`, or `channel`; lines by `order_id`, `finished_goods_lot_id`, or `line_status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request bodies, response payloads, and side effects are defined by the workflows of §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/roastery/counterparties` | Register a new counterparty (supplier, importer, or customer) | Trader |
| GET | `/roastery/counterparties/{id}` | Fetch one counterparty | Trader, RiskManager, HeadRoaster, FulfillmentPlanner |
| GET | `/roastery/counterparties` | List counterparties | Trader, RiskManager, HeadRoaster, FulfillmentPlanner |
| POST | `/roastery/counterparties/{counterparty_id}/contracts` | Book a green coffee contract with a counterparty | Trader |
| GET | `/roastery/contracts/{id}` | Fetch one contract | Trader, RiskManager, LogisticsCoordinator |
| GET | `/roastery/contracts` | List contracts | Trader, RiskManager, LogisticsCoordinator |
| POST | `/roastery/contracts/{contract_id}/price-fixes` | Record a price-fix event against a PTBF contract; OCC-guarded | Trader |
| GET | `/roastery/contracts/{id}/price-fixes` | List price-fix events for a contract | Trader, RiskManager |
| POST | `/roastery/contracts/{contract_id}/short-close` | Write off the un-received shortfall of a partially received contract; OCC-guarded | Trader |
| POST | `/roastery/contracts/{contract_id}/cancel` | Cancel an unshipped, unfixed contract | Trader |
| POST | `/roastery/contracts/{contract_id}/shipments` | Book a shipment against a contract | LogisticsCoordinator |
| GET | `/roastery/shipments/{id}` | Fetch one shipment | Trader, LogisticsCoordinator, WarehouseClerk, QAGrader |
| GET | `/roastery/contracts/{id}/shipments` | List shipments for a contract | Trader, LogisticsCoordinator, WarehouseClerk |
| POST | `/roastery/shipments/{shipment_id}/depart` | Mark shipment IN_TRANSIT | LogisticsCoordinator |
| POST | `/roastery/shipments/{shipment_id}/arrive` | Mark shipment ARRIVED | LogisticsCoordinator |
| POST | `/roastery/shipments/{shipment_id}/receive` | Receive a shipment into the warehouse; creates the GreenLot child | WarehouseClerk |
| POST | `/roastery/shipments/{shipment_id}/cancel` | Cancel a BOOKED shipment | LogisticsCoordinator |
| POST | `/roastery/shipments/{shipment_id}/resolve-dispute` | Resolve a quality dispute on a CUP_FAILED shipment | Trader |
| GET | `/roastery/green-lots/{id}` | Fetch one green lot | Trader, WarehouseClerk, RoastOperator, HeadRoaster, RiskManager, QAGrader |
| GET | `/roastery/green-lots` | List green lots | Trader, WarehouseClerk, RoastOperator, HeadRoaster, RiskManager, QAGrader |
| GET | `/roastery/warehouse-position` | Fetch the singleton warehouse position (derived) | Trader, RiskManager, HeadRoaster, WarehouseClerk |
| POST | `/roastery/financing-lines` | Open an inventory financing line | RiskManager |
| GET | `/roastery/financing-lines/{id}` | Fetch one financing line | RiskManager, Trader |
| POST | `/roastery/financing-lines/{line_id}/reserves` | Pledge a green lot to the line (creates FinancingReserve) | RiskManager |
| POST | `/roastery/financing-reserves/{reserve_id}/release` | Release a FinancingReserve, returning pledged mass to the open pool | RiskManager |
| POST | `/roastery/financing-lines/{line_id}/suspend` | Suspend a financing line | RiskManager |
| POST | `/roastery/financing-lines/{line_id}/unsuspend` | Un-suspend a financing line | RiskManager |
| POST | `/roastery/financing-lines/{line_id}/close` | Close an empty financing line | RiskManager |
| GET | `/roastery/financing-reserves/{id}` | Fetch one financing reserve | RiskManager, Trader |
| GET | `/roastery/financing-reserves` | List financing reserves | RiskManager, Trader |
| POST | `/roastery/roast-profiles` | Define a roast profile | HeadRoaster |
| GET | `/roastery/roast-profiles/{id}` | Fetch one roast profile | HeadRoaster, RoastOperator |
| POST | `/roastery/products` | Define a finished product (SKU) | HeadRoaster |
| GET | `/roastery/products/{id}` | Fetch one product | HeadRoaster, RoastOperator, FulfillmentPlanner, Trader |
| GET | `/roastery/products` | List products | HeadRoaster, RoastOperator, FulfillmentPlanner, Trader |
| POST | `/roastery/products/{product_id}/recipes` | Create a new draft blend recipe for a product | HeadRoaster |
| GET | `/roastery/recipes/{id}` | Fetch one recipe | HeadRoaster, RoastOperator |
| GET | `/roastery/products/{id}/recipes` | List recipes for a product | HeadRoaster, RoastOperator |
| POST | `/roastery/recipes/{recipe_id}/components` | Add a component line to a draft recipe | HeadRoaster |
| GET | `/roastery/recipes/{id}/components` | List components of a recipe | HeadRoaster, RoastOperator |
| POST | `/roastery/recipes/{recipe_id}/approve` | Approve a recipe (supersedes any previously APPROVED recipe for the product); OCC-guarded on Product.version | HeadRoaster |
| POST | `/roastery/recipes/{recipe_id}/retire` | Retire a DRAFT recipe that has never been used | HeadRoaster |
| POST | `/roastery/roast-batches` | Schedule a roast batch; waterfall-allocates green lots per the pinned recipe (creates RoastInputAllocation rows atomically) | RoastOperator |
| GET | `/roastery/roast-batches/{id}` | Fetch one roast batch | RoastOperator, HeadRoaster, QAGrader |
| GET | `/roastery/roast-batches` | List roast batches | RoastOperator, HeadRoaster, QAGrader |
| GET | `/roastery/roast-batches/{id}/allocations` | List input allocations of a batch | RoastOperator, HeadRoaster |
| GET | `/roastery/roast-input-allocations/{id}` | Fetch one roast input allocation | RoastOperator, HeadRoaster |
| GET | `/roastery/roast-input-allocations` | List input allocations | RoastOperator, HeadRoaster |
| POST | `/roastery/roast-batches/{batch_id}/start` | Start the roast (SCHEDULED → IN_DRUM); consumes input allocations | RoastOperator |
| POST | `/roastery/roast-batches/{batch_id}/finish` | Finish the roast (IN_DRUM → ROASTED); records actual output | RoastOperator |
| POST | `/roastery/roast-batches/{batch_id}/pack` | Pack a roasted batch into a finished-goods lot (requires QC_PASSED) | RoastOperator |
| POST | `/roastery/roast-batches/{batch_id}/void` | Void a SCHEDULED batch, releasing its input allocations | RoastOperator |
| POST | `/roastery/cupping-sessions` | Open a cupping session on a GreenLot (QUARANTINE) or RoastBatch (PENDING_QC) | QAGrader |
| GET | `/roastery/cupping-sessions/{id}` | Fetch one cupping session | QAGrader, HeadRoaster, Trader |
| POST | `/roastery/cupping-sessions/{session_id}/finalize` | Finalize a cupping session; computes final_score and applies verdict to the subject | QAGrader |
| GET | `/roastery/finished-goods-lots/{id}` | Fetch one finished goods lot | FulfillmentPlanner, RoastOperator, HeadRoaster |
| GET | `/roastery/finished-goods-lots` | List finished goods lots | FulfillmentPlanner, RoastOperator, HeadRoaster |
| POST | `/roastery/fulfillment-orders` | Create a draft fulfillment order | FulfillmentPlanner |
| GET | `/roastery/fulfillment-orders/{id}` | Fetch one fulfillment order | FulfillmentPlanner, Trader |
| GET | `/roastery/fulfillment-orders` | List fulfillment orders | FulfillmentPlanner, Trader |
| POST | `/roastery/fulfillment-orders/{order_id}/lines` | Add a fulfillment line to a DRAFT order | FulfillmentPlanner |
| GET | `/roastery/fulfillment-orders/{id}/lines` | List lines of an order | FulfillmentPlanner |
| GET | `/roastery/fulfillment-lines/{id}` | Fetch one fulfillment line | FulfillmentPlanner |
| GET | `/roastery/fulfillment-lines` | List fulfillment lines | FulfillmentPlanner |
| POST | `/roastery/fulfillment-orders/{order_id}/reserve` | Reserve all lines against finished-goods inventory (DRAFT → RESERVED) | FulfillmentPlanner |
| POST | `/roastery/fulfillment-orders/{order_id}/pack` | Mark order PACKED | FulfillmentPlanner |
| POST | `/roastery/fulfillment-orders/{order_id}/ship` | Mark order SHIPPED | FulfillmentPlanner |
| POST | `/roastery/fulfillment-orders/{order_id}/cancel` | Cancel a DRAFT or RESERVED order; RESERVED cancellation releases lines | FulfillmentPlanner |
| POST | `/roastery/contracts/{contract_id}/futures-hedges` | Place a futures hedge against a PTBF contract's unpriced exposure | Trader |
| GET | `/roastery/futures-hedges/{id}` | Fetch one futures hedge | Trader, RiskManager |
| GET | `/roastery/contracts/{id}/futures-hedges` | List hedges for a contract | Trader, RiskManager |
| POST | `/roastery/futures-hedges/{hedge_id}/approve` | Approve a WORKING hedge (segregation-of-duties enforced) | RiskManager |
| POST | `/roastery/futures-hedges/{hedge_id}/lift` | Lift an APPROVED hedge, realizing P&L | Trader |
| POST | `/roastery/futures-hedges/{hedge_id}/cancel` | Cancel a WORKING hedge | Trader |
| POST | `/roastery/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the workflow narratives of §2 and §3; this catalogue is the identifier-to-status contract only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_RECIPE_COMPONENT_SUM_INVALID` | 422 |
| `ERR_SUBSTITUTION_RULE_INVALID` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_OVER_FIX` | 422 |
| `ERR_FACILITY_LIMIT_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_GREEN_INVENTORY` | 422 |
| `ERR_RECIPE_NOT_APPROVED` | 422 |
| `ERR_STALE_GOODS` | 422 |
| `ERR_INSUFFICIENT_FINISHED_GOODS` | 422 |
| `ERR_DELIVERY_WINDOW_VIOLATION` | 422 |
| `ERR_INVALID_DELIVERY_WINDOW` | 422 |
| `ERR_LOT_NOT_PLEDGEABLE` | 422 |
| `ERR_INVALID_PACK_QUANTITY` | 422 |
| `ERR_OVER_HEDGE` | 422 |
| `ERR_INVALID_FIX_QUANTITY` | 422 |
| `ERR_NOT_CUPPABLE` | 409 |
| `ERR_PANEL_TOO_SMALL` | 422 |
| `ERR_INVALID_YIELD` | 422 |
| `ERR_CONTRACT_CAPACITY_EXCEEDED` | 422 |
