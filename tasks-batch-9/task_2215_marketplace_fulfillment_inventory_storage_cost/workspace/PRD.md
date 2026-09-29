# Marketplace Fulfillment Inventory & Storage Cost API — Product Requirements Document

## 1. Introduction

Sellers who hand their inventory to a marketplace fulfillment network trade control for reach, and the bill they receive at the end of a quarter is rarely the bill they expected. Units arrive at the wrong centre without the required polybag and get refused. A pallet is short eleven units and nobody notices until the listing has already gone dark. Cases that sold briskly in November sit untouched through the following summer and quietly cross the long-term storage surcharge threshold. Meanwhile the seller's restock allowance shrinks because a performance score they cannot see has been penalised by a discrepancy they never filed a claim for.

This service is the system of record that makes all of that legible and enforceable. It plans inbound shipments against a destination centre's prep, labelling and case-pack requirements; it allocates a seller's finite restock capacity across competing draft shipments using a performance-derived limit; it tracks every unit from receipt through storage aging, unfulfillable classification, removal or multi-channel dispatch; it assesses monthly storage fees plus long-term surcharges per lot; and it adjudicates reimbursement claims for units the network lost or damaged, inside a hard filing window and under a strict separation between the party that files and the party that decides.

The API is mounted under `/fulfillment`, with a single additional operational path for the logical clock. Every quantity in the system is either an integer count of units, an integer count of cents, or a ratio carried to four decimal places — there are no floating-point currency amounts and no implicit unit conversions. The remainder of this document defines the global contract (§2), the business logic and workflows (§3), the endpoint surface (§4) and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role it acts under. If either header is absent, or if `X-User-Role` is not one of the four declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This check precedes everything else, including request-body parsing. If the headers are well formed but the named role is not authorized for the requested operation, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles are `SellerOperator`, `FcOperator`, `ClaimsAdjudicator` and `MarketplaceAdmin`.

A `SellerOperator` acts for exactly one seller: it creates listings, drafts and confirms inbound shipment plans, adds line items, ships, reverts and cancels plans, requests and cancels removals, files and resubmits reimbursement claims, produces velocity forecasts and places multi-channel orders. When `X-User-Role` is `SellerOperator`, `X-User-ID` is the `id` of the acting `SellerAccount`; ownership checks on any resource that references a `SellerAccount` compare the resource's owning-seller field to `X-User-ID`. Because the topology is flat, that comparison sometimes traverses a short chain — a removal order resolves to a lot, the lot to a listing, and the listing's `seller_account_id` is what must equal `X-User-ID`. A mismatch anywhere along that chain is rejected with `ERR_SELLER_SCOPE_VIOLATION` (HTTP 403).

An `FcOperator` acts for exactly one fulfillment center: it records receipts against inbound plans destined for its own centre, classifies units unfulfillable at its own centre, completes removals drawn from lots it holds, and adjusts its own receiving posture. When `X-User-Role` is `FcOperator`, `X-User-ID` is the `id` of the acting `FulfillmentCenter`; ownership checks compare the target resource's centre reference — a plan's `destination_fc_id`, or a lot's `fulfillment_center_id` — to `X-User-ID`, and a mismatch is rejected with `ERR_FC_SCOPE_VIOLATION` (HTTP 403).

Claims are governed by segregation of duties. When `X-User-Role` is `ClaimsAdjudicator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`. A `ClaimsAdjudicator` is the only role that may request further information on a claim or decide it, and it may never file or resubmit one. Symmetrically, `MarketplaceAdmin` is likewise an opaque identifier not tied to any persisted entity, and it has no claim powers whatsoever and no inventory powers: it onboards seller accounts and fulfillment centers, opens quota periods, triggers storage billing runs and moves the logical clock, but it cannot file, resubmit, question or decide a claim, and it cannot touch a lot's unit pools.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Both appear in the `meta` object of the response envelope alongside `total_count` (the total number of items matching the filter, ignoring pagination) and `has_more` (true when items remain beyond the current page).

Unless a specific list operation says otherwise, list results are sorted by `created_at` in ascending order. Two operations invert that default because recency is what the reader wants: the seller's quota periods are returned newest first, and a listing's velocity forecasts are returned newest first. A lot's storage fee assessments are returned oldest first, and a plan's line items are returned in creation order — both of which coincide with the ascending default.

Filters, where a list operation offers them, are exact-match equality on the named field and combine conjunctively. Listings may be filtered by `listing_status` and by `inventory_health`; quota periods by `status`; forecasts by `forecast_variant`; plans by `seller_account_id`, by `destination_fc_id` and by `status`; lots by `sku_listing_id`, by `fulfillment_center_id`, by `lot_status`, by `reconciliation_status` and by `aged_bucket`; a listing's multi-channel orders by `fulfillment_channel`; and a lot's removal orders and reimbursement claims each by `status`.

### 2.4. Resource Identity, Timestamps and the Logical Clock

Every persisted resource carries an `id`: a server-minted UUID with no type prefix, never supplied by the client. Alongside it, most resources carry three further system-managed properties:

- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written.
- `updated_at` (string): an ISO 8601 UTC timestamp, in the same format, refreshed on every mutation of the resource — including mutations that only touch derived fields such as a seller's `restock_reserved_units` or a lot's `storage_fee_accrued_cents`.
- `version` (integer): starts at 1 when the resource is created and increments by exactly 1 on every subsequent mutation of that resource, again including derived-field-only mutations.

Two resource kinds are append-only records of a computation rather than living entities, and they carry only `id` and `created_at`: `StorageFeeAssessment` and `VelocityForecast` both omit `updated_at` and omit `version` entirely. Neither is ever mutated after it is written.

All time-dependent behaviour in this system reads a **logical clock** rather than wall-clock time. The clock's startup value is exactly `2026-08-01T00:00:00Z`, and it never falls back to real time; a `MarketplaceAdmin` moves it by supplying a `to_iso8601` instant to the clock-setting capability, which answers with the resulting `current_utc`. Inventory aging, claim filing deadlines, appointment-window sanity checks, removal-window opening, quota expiry, plan closure and multi-channel peak-period detection all read this clock, which makes every one of those behaviours deterministically testable.

### 2.5. Path Resolution and Foreign-Key Existence

Path parameters are resolved strictly left to right, and the first identifier that fails to resolve determines the error. A request addressed to a listing's velocity forecasts under a listing that does not exist fails with `ERR_LISTING_NOT_FOUND` before any forecast logic runs; a request against a seller's quota periods under an unknown seller fails with `ERR_SELLER_NOT_FOUND`. The full set of path-resolution failures is `ERR_SELLER_NOT_FOUND`, `ERR_FC_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_REMOVAL_ORDER_NOT_FOUND` and `ERR_CLAIM_NOT_FOUND`, each carrying HTTP 404.

Foreign keys supplied in a request body are resolved with the same vocabulary. A `seller_account_id` that does not resolve yields `ERR_SELLER_NOT_FOUND`; a `destination_fc_id` yields `ERR_FC_NOT_FOUND`; a `sku_listing_id` yields `ERR_LISTING_NOT_FOUND`; an `inventory_lot_id` yields `ERR_LOT_NOT_FOUND`. Inside a receipt payload, a `shipment_line_item_id` that does not resolve — or that resolves to a line item belonging to a different plan than the one being received — yields `ERR_LINE_ITEM_NOT_FOUND` (HTTP 404).

### 2.6. Validation Precedence

Because several operations are guarded by many rules at once, the order of evaluation is part of the contract: the first rule that fails determines the response, and no later rule may mask an earlier one. Validation proceeds in this fixed ladder.

1. Header presence and role recognition — `ERR_UNAUTHENTICATED`, on every endpoint.
2. Role authorization for the requested operation — `ERR_FORBIDDEN_ROLE`, on every endpoint.
3. Request-body shape on every write: required fields present, enum values drawn from their declared member sets, numeric fields inside their declared bounds, arrays non-null and well-formed — `ERR_INVALID_REQUEST` (HTTP 400).
4. Existence of every path-templated resource, left to right, as described in §2.5.
5. Existence of every body foreign key — `seller_account_id`, `destination_fc_id`, `sku_listing_id`, `inventory_lot_id` and `shipment_line_item_id` — on listing creation, plan creation, line-item creation, removal-order creation, claim filing, receipt recording and multi-channel order placement.
6. Ownership scope: a `SellerOperator` acting outside its own seller chain is rejected with `ERR_SELLER_SCOPE_VIOLATION`; an `FcOperator` receiving a plan bound elsewhere or completing a removal on a lot held elsewhere is rejected with `ERR_FC_SCOPE_VIOLATION`. This applies to every `SellerOperator` and `FcOperator` write.
7. Version guards on the two sizing writes described in §2.10 — `ERR_STALE_SELLER_VERSION` and `ERR_STALE_LOT_VERSION`, both HTTP 412.
8. The target resource's own state permits the operation — `ERR_PLAN_NOT_DRAFT`, `ERR_PLAN_NOT_CONFIRMED`, `ERR_PLAN_NOT_RECEIVABLE`, `ERR_PLAN_NOT_CANCELLABLE`, `ERR_REMOVAL_NOT_REQUESTED`, `ERR_CLAIM_NOT_ACTIONABLE` or `ERR_LISTING_NOT_SUPPRESSED`, all HTTP 409, on every state-transition operation.
9. Cross-entity state preconditions, all HTTP 409: the destination centre's `receiving_status` is not `SUSPENDED` at confirmation (`ERR_FC_RECEIVING_SUSPENDED`); the seller has a quota period whose `status` is `ACTIVE` at confirmation (`ERR_NO_ACTIVE_RESTOCK_QUOTA`); the lot's `reconciliation_status` is `DISCREPANCY_OPEN` when a `LOST_INBOUND` claim is filed (`ERR_LOT_NO_OPEN_DISCREPANCY`); the listing has at least one fulfillable unit at reinstatement (`ERR_SUPPRESSION_CONDITION_PERSISTS`); and the logical clock has reached the removal window's start at completion (`ERR_REMOVAL_WINDOW_NOT_OPEN`). These four operations are plan confirmation, claim filing, listing reinstatement and removal completion.
10. Prep requirement — `ERR_PREP_REQUIREMENT_UNMET` (HTTP 422), enforced on both line-item creation and plan confirmation.
11. Label requirement — `ERR_LABEL_REQUIREMENT_UNMET` (HTTP 422), enforced on both line-item creation and plan confirmation.
12. Appointment-window sanity on plan creation — `ERR_APPOINTMENT_WINDOW_INVALID` when the window's end is not strictly after its start, `ERR_APPOINTMENT_WINDOW_IN_PAST` when its start is strictly before the logical clock's current instant, both HTTP 422.
13. Claim filing window — `ERR_CLAIM_FILING_WINDOW_CLOSED` (HTTP 422), enforced on both claim filing and claim resubmission.
14. Case-pack rules — `ERR_CASE_PACK_VIOLATION` (HTTP 422), enforced on both line-item creation and plan confirmation.
15. Structural constraints: a plan being confirmed has at least one line item (`ERR_PLAN_HAS_NO_LINE_ITEMS`, HTTP 422); a seller's SKU is unique (`ERR_DUPLICATE_SKU`, HTTP 409); a requested removal window does not collide with another requested removal window on the same lot (`ERR_REMOVAL_WINDOW_CONFLICT`, HTTP 409); and a claim has not exhausted its two resubmissions (`ERR_RESUBMISSION_LIMIT_REACHED`, HTTP 422). These guard listing creation, plan confirmation, removal-order creation and claim resubmission respectively.
16. Referential coherence, both HTTP 422: a line item's listing belongs to the plan's own seller (`ERR_LISTING_SELLER_MISMATCH`, on line-item creation), and a claim carries at least the evidence minimum for its type (`ERR_EVIDENCE_REFERENCE_MISSING`, on both claim filing and claim resubmission).
17. Unit availability, all HTTP 422: `ERR_INSUFFICIENT_POOL_UNITS` on removal-order creation and on unfulfillable classification, `ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS` on claim filing, and `ERR_NO_FULFILLABLE_INVENTORY` on multi-channel order placement.
18. Destination-centre receiving-window capacity at confirmation — `ERR_FC_RECEIVING_CAPACITY_EXCEEDED` (HTTP 422).
19. Restock limit at confirmation — `ERR_RESTOCK_LIMIT_EXCEEDED` (HTTP 422).

The practical consequence at confirmation is worth spelling out, since that single operation is guarded by nine of these steps: a plan whose destination centre is suspended surfaces `ERR_FC_RECEIVING_SUSPENDED` even though it also has an unpolybagged line item, because the cross-entity state check sits above the prep check; and a plan that is both over the centre's window capacity and over the seller's restock limit surfaces `ERR_FC_RECEIVING_CAPACITY_EXCEEDED`, because capacity is evaluated before allocation.

### 2.7. Conserved Unit Quantities and Compensating Actions

Four unit quantities are conserved invariants, and every operation that disturbs one must restore it in the same request.

The first is the seller's reservation ledger: `restock_reserved_units` on a `SellerAccount` always equals the sum of `allocated_units` across that seller's inbound shipment plans whose `status` is `CONFIRMED`, `IN_TRANSIT` or `PARTIALLY_RECEIVED`. Any operation that moves a plan into or out of that reserving set adjusts the seller's figure by the plan's `allocated_units` in the same breath.

The second is the lot's unit conservation: the cumulative `units_received_total` of an `InventoryLot` always equals the sum of its `fulfillable_units`, `unfulfillable_units`, `units_reserved_for_removal`, `units_removed` and `units_shipped_mcf`. Classifying units unfulfillable, reserving them for removal, executing that removal and drawing units for a multi-channel order all move units between those pools without changing the total. The lot's `missing_units` is tracked separately: it counts units declared inbound but never received, and it is reduced only by an approved reimbursement claim.

The third is the centre's receiving commitment: `committed_receiving_units` on a `FulfillmentCenter` always equals the sum of `declared_units` across plans whose `destination_fc_id` is that centre and whose `status` is `CONFIRMED`, `IN_TRANSIT` or `PARTIALLY_RECEIVED`.

The fourth is shortfall accounting: once a plan has been received at least once, its `missing_units` equals its `declared_units` minus its `received_units`, and is 0 before any receipt.

Three operations are explicit **compensating actions** that must restore these invariants to their exact pre-operation values: reverting a confirmed plan to draft, cancelling a confirmed plan, and cancelling a requested removal order. Each releases precisely what its counterpart reserved — the same unit counts, returned to the same pools and the same ledgers.

Beyond those four invariants, a seller carries five running ledgers whose values are always the aggregate they claim to be, not merely the accumulation of increments. `open_discrepancy_units` equals the sum of lot-level `missing_units` over the lots of that seller's listings whose `reconciliation_status` is `DISCREPANCY_OPEN` or `DISCREPANCY_CLAIMED`. `suppressed_listing_count` equals the count of that seller's listings whose `listing_status` is `SUPPRESSED`. `storage_fee_accrued_cents` equals the sum of `total_fee_cents` across every storage assessment ever written for lots of that seller's listings. `reimbursement_credit_cents` equals the sum of `reimbursement_amount_cents` across that seller's claims whose `status` is `APPROVED`. And `mcf_fee_accrued_cents` equals the sum of `mcf_fee_cents` across that seller's multi-channel orders whose `order_status` is `MCF_SHIPPED`. At the lot level, the same discipline applies: `units_reserved_for_removal` is exactly the units held by removal orders on that lot whose `status` is `REQUESTED`, `units_removed` is exactly the units retired by removal orders whose `status` is `COMPLETED`, and `units_shipped_mcf` is exactly the units consumed by multi-channel orders whose `order_status` is `MCF_SHIPPED`.

Derived fields are not caches that may lag. Whenever a lot pool changes, the owning listing's rollups and the owning seller's aggregate ledgers are recomputed inside the same request, and each such recomputation is a mutation of the affected resource: it refreshes that resource's `updated_at` and increments its `version`. Cascades propagate in the order given by the workflow that triggered them, and every link of a cascade is part of the same atomic request — either all of it lands or none of it does.

### 2.8. Parallel State Dimensions

Two entities carry two independent state dimensions on the same row, and the interaction between them is a frequent source of misimplementation.

A `SkuListing` has a `listing_status` (either `ACTIVE` or `SUPPRESSED`) and an `inventory_health` (one of `HEALTHY`, `EXCESS_AGED`, `STRANDED` or `OUT_OF_STOCK`). These evolve independently. Health is re-derived automatically on every event that changes a unit pool; suppression, once set, is never cleared automatically — only an explicit reinstatement by a `SellerOperator` clears it. A listing may therefore sit at `listing_status` of `SUPPRESSED` while its `inventory_health` has already recovered to `HEALTHY`, and that combination is correct, not a bug.

An `InventoryLot` has a `lot_status` (`ACTIVE`, `PARTIALLY_REMOVED` or `DEPLETED`) and a `reconciliation_status` (`RECONCILED`, `DISCREPANCY_OPEN`, `DISCREPANCY_CLAIMED` or `DISCREPANCY_RESOLVED`). Removals and multi-channel draws move the first dimension; short receipts and claim decisions move the second. A `DEPLETED` lot with an unclaimed shortfall stays at `DISCREPANCY_OPEN` indefinitely, and that open shortfall keeps contributing to the listing's `missing_units`.

Neither entity has terminal states: both dimensions on both entities can, in principle, keep moving for the lifetime of the row.

### 2.9. Money, Volume and Rounding Discipline

All monetary amounts in this system are integer counts of cents. There are no fractional cents anywhere in a stored field or in a response body. Wherever a monetary amount is produced by multiplying by a rate, a weight or a percentage, the product is rounded to a whole number of cents using **round half up** at the exact step the calculation names, and the intermediate order of those roundings is part of the specification rather than an implementation detail.

Volumes are carried as numbers with four decimal places, again rounded half up: a unit's `unit_cubic_feet`, a lot's `billable_cubic_feet` at assessment time, and a seller's `storage_utilization_ratio`. Performance inputs on a quota period — `sell_through_rate`, `excess_units_ratio`, `stranded_ratio` and `in_stock_rate` — are likewise four-decimal numbers, as is a forecast's `daily_velocity`. A forecast's `seasonal_index` carries two decimal places, and a multi-channel order's `billable_weight_lb` carries two decimal places.

Unit counts are integers and are never rounded, because they are never divided. Where a calculation must convert a fractional quantity into units it says explicitly which direction it truncates: the inventory performance score's derived allowance takes the floor, while a forecast's coverage target takes the ceiling.

### 2.10. Version Guards on Sizing Writes

Exactly two write operations require the client to prove it sized its request against a state it has actually observed, and both use optimistic concurrency control keyed on a parent resource's `version`.

Creating an inbound shipment plan requires a non-optional `expected_seller_account_version` field carrying the client's last observed `version` of the target `SellerAccount`. Plan creation re-derives the seller's draft provisional pool, so a client whose view of the seller has gone stale would size its provisional allocation against capacity another plan has already claimed. If `expected_seller_account_version` does not equal the seller's current `version`, the request is rejected with `ERR_STALE_SELLER_VERSION` (HTTP 412) and nothing is persisted. A successful plan creation itself increments the seller's `version` by 1, so the next creation must quote the new value.

Creating a removal order requires a non-optional `expected_inventory_lot_version` field carrying the client's last observed `version` of the target `InventoryLot`. A removal request is sized against a specific pool split on that lot, and any intervening write may have changed that split. If `expected_inventory_lot_version` does not equal the lot's current `version`, the request is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). A successful removal-order creation increments the lot's `version` by 1.

No other endpoint accepts a version field. Confirmation, reversion, shipment, receipt, cancellation, classification, removal completion, claim filing, resubmission, adjudication, forecasting, multi-channel ordering and billing runs all take no expected-version input, and supplying one has no effect.

## 3. Business Logic & Workflows

### 3.1. Onboarding Sellers, Fulfillment Centers and Quota Periods

A `MarketplaceAdmin` registers a seller by supplying a `legal_name`, a `storage_cubic_feet_entitlement` (a positive number carried to four decimals, which becomes the denominator of the seller's storage utilization) and a `unit_cost_cap_cents` (a non-negative integer ceiling that later caps reimbursement valuation). The new account opens with `seller_status` of `ACTIVE` and every derived ledger at zero: `restock_reserved_units`, `open_discrepancy_units`, `suppressed_listing_count`, `storage_fee_accrued_cents`, `reimbursement_credit_cents` and `mcf_fee_accrued_cents` all start at 0, and `storage_utilization_ratio` starts at 0.0.

Registering a fulfillment center is likewise an admin act. The payload carries a `fc_code` that must be unique across all centers, a `region_code` used only for reporting, a `prep_profile` drawn from `POLYBAG_REQUIRED`, `LABEL_ONLY` and `CASE_PACK_STRICT`, a `case_pack_min_units` of at least 1, a `receiving_capacity_units_per_window` of at least 1, and two integer rates in cents per cubic foot: `monthly_storage_rate_cents_per_cubic_foot` and `ltsf_rate_cents_per_cubic_foot`, both non-negative. A new centre opens with `receiving_status` of `OPEN` and `committed_receiving_units` of 0. Either an `FcOperator` acting for that centre or a `MarketplaceAdmin` may later adjust its posture, revising `receiving_status` to `OPEN`, `THROTTLED` or `SUSPENDED`, and revising `receiving_capacity_units_per_window`. Those two levers are what the capacity gate in §3.4 reads.

**Quota periods** are how the platform rations restock capacity. A `MarketplaceAdmin` opens one for a seller by supplying a `period_start` and a `period_end` (the end must be strictly after the start; the interval is inclusive at the start and exclusive at the end), a `base_capacity_units` of at least 1, and four trailing performance inputs: `sell_through_rate` (non-negative), `excess_units_ratio`, `stranded_ratio` and `in_stock_rate` (each between 0 and 1 inclusive). Opening a new period moves any pre-existing period of the same seller whose `status` is `ACTIVE` to `SUPERSEDED`; the superseded row keeps whatever `utilized_units` it had accumulated, and the new row's `utilized_units` is seeded from the sum of `allocated_units` across the seller's plans whose `status` is `CONFIRMED`, `IN_TRANSIT` or `PARTIALLY_RECEIVED`, so live reservations carry forward. A seller has at most one period whose `status` is `ACTIVE` at any instant, and periods whose `status` is `SUPERSEDED` or `EXPIRED` are never re-scored.

Opening a period immediately scores it. The **inventory performance score** is assembled from four weighted components on a 0-to-1000 scale. The sell-through component is the period's `sell_through_rate` divided by the target of 2.5, capped at 1.0, weighted 0.40. The excess component is 1 minus the smaller of 1.0 and the `excess_units_ratio` divided by the target of 0.30, weighted 0.25. The stranded component is 1 minus the smaller of 1.0 and the `stranded_ratio` divided by the target of 0.10, weighted 0.20. The in-stock component is the `in_stock_rate` itself, weighted 0.15. Those four weighted components are summed and the sum is multiplied by 1000; the result is rounded half up to an integer.

Two penalties are then subtracted from that integer. A stranded penalty of 75 points applies when the period's `stranded_ratio` is strictly greater than 0.05. A discrepancy penalty of 50 points applies when the owning seller's `open_discrepancy_units` is strictly greater than 500 units. Both penalties can apply at once, for a maximum deduction of 125 points. The resulting `iprs_score` is the larger of 0 and the rounded score minus the total penalty, so it never goes negative.

From `iprs_score` alone the system derives `base_capacity_tier`: `TIER_ELEVATED` when the score is at least 800, `TIER_STANDARD` when the score is at least 500 but below 800, and `TIER_RESTRICTED` for anything below 500. The effective `capacity_tier` is then that base tier shifted down by `capacity_tier_downgrade_steps`, one step per unit of that counter, where one step moves `TIER_ELEVATED` to `TIER_STANDARD` and `TIER_STANDARD` to `TIER_RESTRICTED`; `TIER_RESTRICTED` is the floor and further steps have no additional effect. The effective tier selects a multiplier — 3.0 for `TIER_ELEVATED`, 1.5 for `TIER_STANDARD`, 0.5 for `TIER_RESTRICTED` — and `restock_limit_units` is the floor of `base_capacity_units` multiplied by that multiplier.

Scoring also has an account-level consequence: whenever the score is (re)computed, the owning seller's `seller_status` is set to `SUSPENDED` if the resulting `iprs_score` is strictly below 200, and to `ACTIVE` otherwise. The score is not computed only at quota opening; it is re-derived whenever the seller's `open_discrepancy_units` changes — that is, on a receipt that opens a shortfall, on a receipt that clears one, and on a claim decision — and again inside a storage billing run whenever a utilization downgrade is applied.

### 3.2. SKU Listings and Their Two Health Dimensions

A `SellerOperator` creates a listing by supplying the owning `seller_account_id`, a `sku`, a positive `unit_cubic_feet` carried to four decimals, and a non-negative `unit_cost_cents` that later drives both liquidation recovery and reimbursement valuation. The pair of owning seller and `sku` must be unique: a second listing with the same `sku` under the same seller is rejected with `ERR_DUPLICATE_SKU`. A fresh listing opens at `listing_status` of `ACTIVE`, `inventory_health` of `OUT_OF_STOCK`, `suppression_reason` of `NONE`, `lot_ever_created` of false, and every unit rollup at 0 — `fulfillable_units`, `unfulfillable_units`, `missing_units`, `aged_over_365_units` and `recommended_replenishment_units`.

Whenever any lot pool of this listing moves, the listing's rollups are re-derived from its lots. Its `fulfillable_units` is the sum of `fulfillable_units` over lots of this listing whose `lot_status` is `ACTIVE` or `PARTIALLY_REMOVED`; `unfulfillable_units` is the sum of `unfulfillable_units` over that same set of lots. Its `missing_units` is the sum of lot-level `missing_units` over a wider set — lots whose `lot_status` is `ACTIVE`, `PARTIALLY_REMOVED` **or** `DEPLETED` — which is what keeps an unreimbursed shortfall visible after the physical units are gone. Its `aged_over_365_units` is the sum of `fulfillable_units` plus `unfulfillable_units` over lots whose `lot_status` is `ACTIVE` or `PARTIALLY_REMOVED` and whose `aged_bucket` is `OVER_365`. And `lot_ever_created` flips to true, permanently, as soon as any lot row exists for this listing.

`inventory_health` is then decided by four rules evaluated in this pinned order, first match winning. If `fulfillable_units` is 0 and `unfulfillable_units` is at least 1, health is `STRANDED`. Otherwise, if `fulfillable_units` is 0, health is `OUT_OF_STOCK`. Otherwise, if `aged_over_365_units` is at least 1, health is `EXCESS_AGED`. Otherwise health is `HEALTHY`. The order matters: a listing holding both aged fulfillable units and unfulfillable units is `EXCESS_AGED`, not `STRANDED`, because the stranded rule requires zero fulfillable units. Movement along this dimension leaves `listing_status` completely untouched — the `HEALTHY` to `EXCESS_AGED` step, the step from any of `HEALTHY`, `EXCESS_AGED` or `OUT_OF_STOCK` into `STRANDED`, and the step from any of `HEALTHY`, `EXCESS_AGED` or `STRANDED` back into `OUT_OF_STOCK` all change health alone. The transition into `EXCESS_AGED` specifically requires at least one fulfillable unit and at least one unit sitting in the `OVER_365` bucket, and in practice fires inside a storage billing run, since that is when age buckets advance.

Suppression is the other dimension and is deliberately asymmetric: it engages automatically and disengages only on request. The same recomputation that derives health also asks whether `fulfillable_units` has fallen to 0 while `lot_ever_created` is true. When both hold, `listing_status` becomes `SUPPRESSED` and `suppression_reason` is pinned by priority, first match winning: `MISSING_INVENTORY` when the listing's `missing_units` is at least 1, otherwise `STRANDED_INVENTORY` when its `unfulfillable_units` is at least 1, otherwise `ZERO_FULFILLABLE`. The owning seller's `suppressed_listing_count` — always the count of that seller's listings whose `listing_status` is `SUPPRESSED` — increases by 1. When the condition does not hold, `listing_status` and `suppression_reason` are left exactly as they were; there is no automatic un-suppression, and a listing that has regained stock stays dark until someone acts. Note that a listing which has never held a lot is never suppressed, however empty it is: `lot_ever_created` of false is the gate.

Reinstatement is that act. A `SellerOperator` reinstates a listing, optionally attaching a `reinstatement_note`, and the transition from `SUPPRESSED` back to `ACTIVE` requires two things: the listing's `listing_status` is currently `SUPPRESSED`, otherwise the attempt fails with `ERR_LISTING_NOT_SUPPRESSED`; and the listing's `fulfillable_units` is at least 1, otherwise it fails with `ERR_SUPPRESSION_CONDITION_PERSISTS`. A successful reinstatement sets `suppression_reason` back to `NONE` and decrements the seller's `suppressed_listing_count` by 1. It does not touch `inventory_health`, which was already tracking reality independently.

### 3.3. Sizing Replenishment: Velocity Forecasts and Draft Shipment Plans

Before committing units to a centre, a `SellerOperator` sizes the shipment with a **velocity forecast** against a listing. The payload names a `forecast_variant` — either `TRAILING_30` or `SEASONAL_WEIGHTED` — together with `trailing_30_units_sold`, `prior_year_same_period_units_sold`, a `seasonal_index` with two decimal places, a `coverage_target_days` and a `lead_time_days`, all non-negative.

The two variants differ only in how `daily_velocity` is derived, and they are genuinely different answers for identical inputs. Under `TRAILING_30`, `daily_velocity` is `trailing_30_units_sold` divided by the 30-day trailing window, rounded half up to four decimal places; the prior-year figure and the `seasonal_index` are ignored even when supplied. Under `SEASONAL_WEIGHTED`, the numerator is 0.60 times `trailing_30_units_sold` plus 0.40 times the product of `prior_year_same_period_units_sold` and `seasonal_index`; that numerator is divided by 30 and rounded half up to four decimal places.

From there both variants follow the same path. `target_units` is `daily_velocity` multiplied by the sum of `coverage_target_days` and `lead_time_days`, rounded **up** to the next whole unit. `in_flight_units` is the sum of `units` over line items for this listing that belong to plans whose `status` is `CONFIRMED`, `IN_TRANSIT` or `PARTIALLY_RECEIVED`; line items on plans in `DRAFT`, `CANCELLED`, `RECEIVED_COMPLETE` or `CLOSED` are excluded. `quota_headroom_units` is the larger of 0 and the seller's `restock_limit_units` minus its `utilized_units`, read from the quota period whose `status` is `ACTIVE`, and is 0 when the seller has no active period at all. The raw need is the larger of 0 and `target_units` minus the listing's `fulfillable_units` minus `in_flight_units`, and `recommended_replenishment_units` is the smaller of that raw need and `quota_headroom_units` — so a recommendation is never larger than the capacity the seller could actually consume. Finally, `stranded_risk_flag` is true when the listing's `unfulfillable_units` is greater than 0, or when `daily_velocity` is exactly 0.0000 while the listing's `fulfillable_units` is greater than 0. Each forecast is written as a new immutable row, and its `recommended_replenishment_units` is copied onto the listing; the listing therefore always reflects the most recent forecast, meaning the forecast row with the latest `created_at`.

With a number in hand, the seller drafts an **inbound shipment plan**. Creation names the owning `seller_account_id`, the `destination_fc_id` of the receiving centre, an `appointment_window_start` and an `appointment_window_end`, plus the `expected_seller_account_version` guard from §2.10. Appointment windows are half-open — inclusive of their start, exclusive of their end — and are validated twice: the end must be strictly after the start, or the request fails with `ERR_APPOINTMENT_WINDOW_INVALID`, and the start must not be strictly before the logical clock's current instant, or it fails with `ERR_APPOINTMENT_WINDOW_IN_PAST`. A window starting exactly at the current instant is accepted. A new plan opens with `status` of `DRAFT`, `declared_units` of 0, `allocation_status` of `WITHIN_LIMIT`, `prep_compliance_status` of `PENDING`, `confirmed_at` of null, and every allocation and receipt figure at 0.

Line items are added to a plan while it remains in `DRAFT`; an attempt against a plan in any other `status` fails with `ERR_PLAN_NOT_DRAFT`. Each line names the `sku_listing_id` being shipped, the `units` on that line (at least 1) and the `case_pack_units` for the line (at least 1), together with the prep declarations covered in §3.4; the line records the plan it belongs to as its `shipment_plan_id`, which is the key a plan's line-item listing reads back. The line's listing must belong to the plan's own seller — if the listing's `seller_account_id` differs from the plan's, the line is rejected with `ERR_LISTING_SELLER_MISMATCH`. Adding a line recomputes the plan's `declared_units` as the sum of `units` across its line items, and re-runs the provisional allocation waterfall.

That waterfall is the heart of quota rationing, and it runs in two variants against the same line items. Both begin from the seller's quota period whose `status` is `ACTIVE`. Two figures are then measured. The **committed charge** is the sum of `allocated_units` over the seller's *other* plans whose `status` is `CONFIRMED`, `IN_TRANSIT` or `PARTIALLY_RECEIVED`. The **sibling draft charge** is the sum of `provisional_allocated_units` over the seller's *other* plans whose `status` is `DRAFT`, read exactly as currently persisted — sibling draft plans are never recursively recomputed while this plan is being evaluated, which is what makes the mutual dependency between drafts well defined. Plans in `CANCELLED`, `RECEIVED_COMPLETE` or `CLOSED` are excluded from both figures.

The `PROVISIONAL` variant, which runs on plan creation and on every line-item creation, works from a pool equal to the larger of 0 and `restock_limit_units` minus the committed charge minus the sibling draft charge. The `FINAL` variant, which runs only at confirmation, works from a pool equal to the larger of 0 and `restock_limit_units` minus the committed charge alone, ignoring every sibling draft. Given a pool, the waterfall walks this plan's line items in ascending `created_at` order, granting each line the smaller of its `units` and the pool remaining at that point, then reducing the remaining pool by the grant. For `PROVISIONAL`, each line's grant is written to its `provisional_allocated_units` and the total to the plan's `provisional_allocated_units`; the plan's `allocation_status` becomes `WITHIN_LIMIT` when that total equals `declared_units` and `OVER_LIMIT` otherwise. For `FINAL`, each line's grant is written to its `final_allocated_units` and the total to the plan's `final_allocated_units`. Because `PROVISIONAL` charges the pool for sibling drafts and `FINAL` does not, the same data legitimately yields a smaller provisional grant than final grant: a plan can read `OVER_LIMIT` in draft and still confirm successfully once the sibling drafts stop counting. When the seller has no active quota period at all, `PROVISIONAL` grants 0 units to every line.

### 3.4. Confirmation Gates, the Final Allocation and the Release Paths

Destination compliance is declared per line and enforced against the destination centre's `prep_profile`. Each line carries a `polybagged` boolean and a `label_type` drawn from `FNSKU`, `MANUFACTURER_BARCODE` and `NONE`. When the destination centre's `prep_profile` is `POLYBAG_REQUIRED` or `CASE_PACK_STRICT`, every line item of the plan must have `polybagged` set to true; any line that does not triggers `ERR_PREP_REQUIREMENT_UNMET`. When the profile is `LABEL_ONLY` or `CASE_PACK_STRICT`, every line item must have `label_type` of exactly `FNSKU`; anything else triggers `ERR_LABEL_REQUIREMENT_UNMET`. Case packing adds a third rule: a line's `units` must be an exact positive multiple of its `case_pack_units`, and when the profile is `CASE_PACK_STRICT` the line's `case_pack_units` must additionally be at least the centre's `case_pack_min_units`; either failure is `ERR_CASE_PACK_VIOLATION`. All three rules are checked twice — once when the line is added, and again for every line of the plan at confirmation, because the destination centre's profile may have changed in between.

A `SellerOperator` confirms a draft plan, optionally attaching a `confirmation_note`. Confirmation is the busiest gate in the system. The plan's `status` must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`); it must carry at least one line item (`ERR_PLAN_HAS_NO_LINE_ITEMS`); the destination centre's `receiving_status` must be `OPEN` or `THROTTLED`, never `SUSPENDED` (`ERR_FC_RECEIVING_SUSPENDED`); the seller must have a quota period whose `status` is `ACTIVE` (`ERR_NO_ACTIVE_RESTOCK_QUOTA`); every line must satisfy the three compliance rules above; the destination centre's window capacity must accommodate the plan; and the `FINAL` allocation must grant the plan's full `declared_units`.

The **window capacity** check aggregates across plans rather than looking at this plan alone. Sum `declared_units` over every plan at the same destination centre whose `status` is `CONFIRMED`, `IN_TRANSIT` or `PARTIALLY_RECEIVED` and whose half-open appointment window intersects this plan's half-open window, then add this plan's own `declared_units`. That total must not exceed the centre's effective capacity, which is `receiving_capacity_units_per_window` when the centre's `receiving_status` is `OPEN` and the floor of half that figure when it is `THROTTLED`. Equality passes; only a strict excess is rejected, with `ERR_FC_RECEIVING_CAPACITY_EXCEEDED`. Because the windows are half-open, a plan ending exactly when another begins does not intersect it.

The restock gate is the last one. The `FINAL` waterfall runs, and if the resulting `final_allocated_units` is strictly below the plan's `declared_units` the confirmation is rejected with `ERR_RESTOCK_LIMIT_EXCEEDED` and nothing is persisted; a grant exactly equal to `declared_units` is accepted.

A successful confirmation moves the plan `DRAFT → CONFIRMED` and lands a coordinated set of writes. The plan's `final_allocated_units` and every line's `final_allocated_units` are written from the `FINAL` waterfall; the plan's `allocated_units` is set equal to its `final_allocated_units`; `prep_compliance_status` becomes `COMPLIANT` and `confirmed_at` is stamped with the logical clock's current instant. The seller's `restock_reserved_units` increases by the plan's `allocated_units`, the active quota period's `utilized_units` increases by the same amount, and the destination centre's `committed_receiving_units` increases by the plan's `declared_units`. Finally, the `PROVISIONAL` waterfall is refreshed for every *other* plan of this seller whose `status` is `DRAFT`, which may flip those siblings' `allocation_status` to `OVER_LIMIT` now that this plan's units have moved into the committed charge.

Three paths release what a confirmation reserved, and they differ in where the plan lands.

**Shipping** does not release anything. A plan whose `status` is `CONFIRMED` moves `CONFIRMED → IN_TRANSIT`, optionally recording a `carrier_reference`; an attempt against a plan in any other status fails with `ERR_PLAN_NOT_CONFIRMED`. No ledger moves, because the plan stays inside the reserving set of `CONFIRMED`, `IN_TRANSIT` and `PARTIALLY_RECEIVED`.

**Reverting to draft** is a compensating action that returns the plan to an editable state. It requires `status` of `CONFIRMED` (otherwise `ERR_PLAN_NOT_CONFIRMED`) and accepts an optional `revert_reason`. It decrements the seller's `restock_reserved_units` by the plan's `allocated_units`, decrements the active quota period's `utilized_units` by the same amount, and decrements the destination centre's `committed_receiving_units` by the plan's `declared_units` — restoring both conserved ledgers exactly. It then zeroes the plan's `allocated_units` and `final_allocated_units` and every line's `final_allocated_units`, resets `prep_compliance_status` to `PENDING`, sets `confirmed_at` back to null, and recomputes the `PROVISIONAL` waterfall for this plan. The plan may then be edited and confirmed again.

**Cancelling** is terminal and accepts an optional `cancellation_reason`. It is permitted from `DRAFT` and from `CONFIRMED` only; from any other status it fails with `ERR_PLAN_NOT_CANCELLABLE`. The two branches carry deliberately different side-effect sets. Cancelling from `DRAFT` moves the plan `DRAFT → CANCELLED`, zeroes the plan's `provisional_allocated_units` and every line's `provisional_allocated_units`, and refreshes the `PROVISIONAL` waterfall for every other draft plan of this seller — no ledger moves, because a draft never reserved anything. Cancelling from `CONFIRMED` moves the plan `CONFIRMED → CANCELLED` and additionally decrements the seller's `restock_reserved_units` by the plan's `allocated_units`, decrements the active quota period's `utilized_units` by the same amount, and decrements the destination centre's `committed_receiving_units` by the plan's `declared_units`, restoring both conserved ledgers exactly; it then zeroes the plan's `allocated_units`, `final_allocated_units` and `provisional_allocated_units` before refreshing the other drafts. Note that a quota period's `utilized_units` is never decremented by a receipt — only by cancellation and by reversion — so consumed capacity stays consumed for the period.

### 3.5. Receiving: the Completion Fork and the Discrepancy Cascade

Receipt is recorded by the `FcOperator` of the destination centre. The plan's `status` must be `IN_TRANSIT` or `PARTIALLY_RECEIVED`, otherwise the attempt fails with `ERR_PLAN_NOT_RECEIVABLE`, and the acting operator's `X-User-ID` must equal the plan's `destination_fc_id`, otherwise `ERR_FC_SCOPE_VIOLATION`. The payload carries a non-empty `received_lines` array plus an optional `receipt_note`. Each element of `received_lines` is an object naming a `shipment_line_item_id`, a `received_units` count of at least 0 and an `unfulfillable_units` count of at least 0. Every referenced line item must belong to the plan being received, or the whole call fails with `ERR_LINE_ITEM_NOT_FOUND`. A line omitted from the array is credited nothing on this call, which is how a partial receipt is expressed.

For each received line the system picks the lot that will absorb it. Candidates are lots whose listing matches the line's `sku_listing_id`, whose `fulfillment_center_id` matches the plan's `destination_fc_id`, and whose `lot_status` is `ACTIVE` or `PARTIALLY_REMOVED`; they are ranked by ascending `first_received_at`, with ascending `created_at` as tie-break, and the first candidate wins. When there is no candidate at all, a new lot is created with `first_received_at` set to the logical clock's current instant, `units_received_total` of 0 and every pool at 0, and is then credited — which means a line that received zero units against a listing with no prior lot at that centre produces a zero-unit discrepancy shell. Crediting a line adds its `received_units` to the lot's `fulfillable_units`, adds its `unfulfillable_units` to the lot's `unfulfillable_units`, and adds both quantities to the lot's `units_received_total`. Each line's own `received_units` accumulates across calls, and the plan's `received_units` is the sum over its lines.

The fork is decided by comparing the plan's cumulative `received_units` against its `declared_units` after the credits land.

**When the cumulative total equals `declared_units`**, the plan reaches `RECEIVED_COMPLETE`, whether it arrived from `IN_TRANSIT` or from `PARTIALLY_RECEIVED`. The plan's `missing_units` is set to 0 and every line's `shortfall_units` is set to 0. The plan leaves the reserving set: the seller's `restock_reserved_units` is decremented by the plan's `allocated_units`, the destination centre's `committed_receiving_units` is decremented by the plan's `declared_units`, and the plan's `allocated_units` is then set to 0 — keeping both conserved ledgers intact. Listing health is recomputed for every touched listing and the seller's storage utilization is recomputed. Arriving from `IN_TRANSIT`, no discrepancy is opened and no suppression cascade fires. Arriving from `PARTIALLY_RECEIVED`, there is more to do first: every lot that was carrying `missing_units` from this plan has that figure reduced by the newly received units, and its `reconciliation_status` returns to `RECONCILED` once its `missing_units` reaches 0; the seller's `open_discrepancy_units` is decremented by the cleared shortfall; and because that seller-level figure changed, the inventory performance score is re-run on the seller's active quota period and listing health is recomputed, before the reservation release described above.

**When the cumulative total is strictly below `declared_units`**, the plan lands in `PARTIALLY_RECEIVED` and a four-link cascade fires. The first link is the crediting itself, together with shortfall arithmetic: the plan's `missing_units` becomes its `declared_units` minus its `received_units`, and each line's `shortfall_units` becomes that line's declared `units` minus its accumulated `received_units`. The second link, caused by the first, is discrepancy opening: every lot that absorbed a short line has that line's `shortfall_units` added to the lot's `missing_units`, its `reconciliation_status` moved from `RECONCILED` to `DISCREPANCY_OPEN`, and its `discrepancy_opened_at` stamped with the logical clock's current instant — this instant is the anchor of the `LOST_INBOUND` filing deadline — while the seller's `open_discrepancy_units` increases by the total shortfall. The third link, caused by the second, is listing health: each affected listing is recomputed and may become `SUPPRESSED` with `suppression_reason` of `MISSING_INVENTORY` and `inventory_health` of `OUT_OF_STOCK` or `STRANDED`, updating the seller's `suppressed_listing_count`. The fourth link, caused by the second link's change to the seller's `open_discrepancy_units`, is quota re-scoring: the inventory performance score is re-run on the seller's active quota period, which may lower `iprs_score`, `base_capacity_tier`, `capacity_tier` and `restock_limit_units`, and may set `seller_status` to `SUSPENDED`. Crucially, a partially received plan **stays inside the reserving set**: the seller's `restock_reserved_units` and the centre's `committed_receiving_units` are left untouched, and the plan's `allocated_units` still stands.

### 3.6. Unfulfillable Classification, Removal Orders and Settlement

An `FcOperator` at the holding centre may reclassify units it can no longer sell, supplying the `units` to move and a `disposition_reason` describing why. The move subtracts that count from the lot's `fulfillable_units` and adds it to the lot's `unfulfillable_units`, leaving `units_received_total` unchanged, and stamps `unfulfillable_recorded_at` with the logical clock's current instant — the anchor of the `DAMAGED_WAREHOUSE` filing deadline. A classification whose `units` exceeds the lot's current `fulfillable_units` is rejected with `ERR_INSUFFICIENT_POOL_UNITS`. Listing health is then recomputed, which can suppress the listing with `suppression_reason` of `STRANDED_INVENTORY` when the fulfillable pool has been emptied.

Getting units out of the network is a two-step affair. A `SellerOperator` requests a removal against a lot by naming the `inventory_lot_id`, a `removal_method` of `DISPOSAL`, `RETURN_TO_SELLER` or `LIQUIDATION`, a `unit_pool` of either `FULFILLABLE` or `UNFULFILLABLE`, a `requested_units` count of at least 1, a `removal_window_start` and a `removal_window_end` (strictly after the start), and the `expected_inventory_lot_version` guard. Removal windows are **closed** intervals — inclusive at both ends — and they occupy the lot exclusively: if the requested window intersects the window of another removal order on the same lot whose `status` is `REQUESTED`, including the case where the two windows merely touch at an endpoint, the request is rejected with `ERR_REMOVAL_WINDOW_CONFLICT`. The requested count must not exceed the named source pool on the lot, or the request is rejected with `ERR_INSUFFICIENT_POOL_UNITS`.

A successful request opens at `status` of `REQUESTED` with `removal_fee_cents`, `liquidation_recovery_cents` and `net_settlement_cents` all at 0 and `completed_at` null. It reserves the units: `requested_units` is subtracted from whichever pool the `unit_pool` names and added to the lot's `units_reserved_for_removal`, leaving `units_received_total` unchanged. The lot's `version` increments by 1, and listing health and the seller's storage utilization are both recomputed — reserved units still count as stored, so utilization does not fall.

**Completion** is the `FcOperator`'s act, optionally recording a `completion_note`. The order's `status` must be `REQUESTED`, otherwise `ERR_REMOVAL_NOT_REQUESTED`; the acting operator's `X-User-ID` must equal the holding lot's `fulfillment_center_id`, otherwise `ERR_FC_SCOPE_VIOLATION`; and the logical clock must have reached the `removal_window_start`, with the exact instant accepted, otherwise `ERR_REMOVAL_WINDOW_NOT_OPEN`. Completion moves the order `REQUESTED → COMPLETED`, converting the reservation into retirement: `requested_units` is subtracted from the lot's `units_reserved_for_removal` and added to its `units_removed`, again leaving `units_received_total` unchanged. The lot's `last_removal_completed_at` is stamped with the logical clock's current instant — the anchor of the `LOST_REMOVAL` filing deadline. The lot's own status dimension then settles: it moves from `ACTIVE` to `PARTIALLY_REMOVED` when, after the completion, `units_removed` is at least 1 and the sum of `fulfillable_units`, `unfulfillable_units` and `units_reserved_for_removal` is still at least 1; and it moves from either `ACTIVE` or `PARTIALLY_REMOVED` to `DEPLETED` when `units_received_total` is at least 1 while `fulfillable_units`, `unfulfillable_units` and `units_reserved_for_removal` are all 0. A `DEPLETED` lot leaves every storage-fee base — subsequent billing runs skip it entirely and it stops contributing to its listing's `fulfillable_units` and to the seller's storage utilization — and reaching `DEPLETED` triggers a listing health recompute. Completion also runs the settlement calculation and, finally, recomputes listing health and the seller's storage utilization.

**Settlement** prices the removal from the method and the unit count. Under `DISPOSAL`, `removal_fee_cents` is a base of 100 cents plus 15 cents for each requested unit. Under `RETURN_TO_SELLER`, it is a base of 200 cents plus 50 cents per unit. Under `LIQUIDATION`, there is no base and the fee is 25 cents per unit. `liquidation_recovery_cents` is 0 for every method other than `LIQUIDATION`; under `LIQUIDATION` it is the smaller of two figures — five percent of the requested units multiplied by the listing's `unit_cost_cents`, rounded half up to whole cents, and a hard ceiling of 120 cents per requested unit. `net_settlement_cents` is `liquidation_recovery_cents` minus `removal_fee_cents`, and is therefore negative for disposal and return-to-seller. Only this removal order participates; other removal orders on the same lot are irrelevant to its settlement.

**Cancelling** a removal is the seller's compensating action, optionally recording a `cancellation_reason`. The order's `status` must be `REQUESTED`, otherwise `ERR_REMOVAL_NOT_REQUESTED`. The move `REQUESTED → CANCELLED` returns the reservation to the pool it came from: `requested_units` is subtracted from the lot's `units_reserved_for_removal` and added back to `fulfillable_units` when the order's `unit_pool` was `FULFILLABLE`, or back to `unfulfillable_units` when it was `UNFULFILLABLE` — restoring the exact pool split and leaving `units_received_total` unchanged. `removal_fee_cents`, `liquidation_recovery_cents` and `net_settlement_cents` all stay at 0, and `completed_at` stays null: a cancelled removal never settles. Listing health and storage utilization are recomputed here too.

### 3.7. Multi-Channel Fulfillment and the Fee Comparison

A `SellerOperator` records a multi-channel order against a listing by naming the `sku_listing_id`, the `units` ordered (at least 1), a positive `billable_weight_lb` per unit with two decimal places, a `destination_zone` of `ZONE_1`, `ZONE_2` or `ZONE_3`, a `fulfillment_channel` of either `MCF` or `SELF_FULFILLED`, and a non-negative `self_fulfilled_cost_cents` representing the seller's own quoted cost for the same order. The fee quote is computed for both channel values, because the comparison is the point of the feature even when the seller has already decided.

The quote proceeds in a pinned order. The zone base fee is 380 cents for `ZONE_1`, 458 cents for `ZONE_2` and 540 cents for `ZONE_3`. The per-unit fee is that base plus an overweight component: the amount by which `billable_weight_lb` exceeds one pound — floored at zero, so a unit at or under a pound adds nothing — multiplied by 42 cents per pound, rounded half up to whole cents. The gross fee is the per-unit fee multiplied by the ordered `units`. `is_peak_period` is true when the calendar month of the logical clock at creation time is October, November or December, and when it is true a peak surcharge of eight percent of the gross fee, rounded half up, is added; otherwise the surcharge is zero. The sum of gross fee and peak surcharge is the pre-discount total.

The volume discount tier is keyed on that **pre-discount** total and never on the discounted figure: ten percent when the pre-discount total is at least 100000 cents, six percent when it is at least 50000 cents, three percent when it is at least 20000 cents, and zero otherwise. The discount amount is the pre-discount total multiplied by that percentage, rounded half up, and `mcf_fee_cents` is the pre-discount total minus the discount. Keying the tier on the post-discount total is circular and drops a tier at the boundaries; that reading is forbidden.

`fee_advantage_cents` is `self_fulfilled_cost_cents` minus `mcf_fee_cents`, and `recommended_channel` is `MCF` when that advantage is at least 0 and `SELF_FULFILLED` when it is negative — an exact tie of zero resolves to `MCF`.

What happens to inventory depends entirely on the chosen channel, and the two branches are fully divergent. When `fulfillment_channel` is `SELF_FULFILLED`, `order_status` is set to `SELF_SHIPPED`, `consumed_lot_allocations` is an empty array, no lot pool is touched, and the seller's `mcf_fee_accrued_cents` is left unchanged — the row exists purely to record the comparison. When `fulfillment_channel` is `MCF`, units are drawn from inventory first-in-first-out. Candidate lots are those whose listing matches the order's `sku_listing_id`, whose `lot_status` is `ACTIVE` or `PARTIALLY_REMOVED`, whose `fulfillable_units` is at least 1, and whose holding centre's `receiving_status` is not `SUSPENDED`; they are walked in ascending `first_received_at` order with ascending `created_at` as tie-break. From each lot in turn the draw is the smaller of that lot's `fulfillable_units` and the units still needed; the lot's `fulfillable_units` decreases by the draw, its `units_shipped_mcf` increases by the draw, and an object naming that lot's identifier and the drawn count is appended to the order's `consumed_lot_allocations` in draw order. The walk stops as soon as the remaining need reaches zero. If the candidates are exhausted while units are still needed, the entire request is rejected with `ERR_NO_FULFILLABLE_INVENTORY` and nothing whatsoever is persisted — no partial draw, no order row. A successful draw sets `order_status` to `MCF_SHIPPED`, increases the seller's `mcf_fee_accrued_cents` by the order's `mcf_fee_cents`, and recomputes listing health plus the seller's storage utilization. A lot emptied by the draw — `units_received_total` of at least 1 with `fulfillable_units`, `unfulfillable_units` and `units_reserved_for_removal` all at 0 — moves to `DEPLETED` exactly as it would after a removal.

### 3.8. Reimbursement Claims: Evidence, Deadlines and Adjudication

When the network loses or damages units, the seller's remedy is a **reimbursement claim**, and the workflow is deliberately split between two roles: only a `SellerOperator` may file or resubmit, and only a `ClaimsAdjudicator` may request information or decide.

Filing names the `inventory_lot_id`, a `claim_type` of `LOST_INBOUND`, `DAMAGED_WAREHOUSE` or `LOST_REMOVAL`, a `claimed_units` count of at least 1, an `evidence_document_count` of at least 0, and a non-empty `evidence_reference` string pointing at the external evidence. The `claim_type` selects three things at once: the eligible unit pool on the lot, the deadline anchor, and the evidence minimum. `LOST_INBOUND` draws on the lot's `missing_units`, anchors on `discrepancy_opened_at`, and requires at least 2 evidence documents. `DAMAGED_WAREHOUSE` draws on the lot's `unfulfillable_units`, anchors on `unfulfillable_recorded_at`, and requires at least 3. `LOST_REMOVAL` draws on the lot's `units_removed`, anchors on `last_removal_completed_at`, and requires at least 2. An `evidence_document_count` below the minimum for the claim's type is rejected with `ERR_EVIDENCE_REFERENCE_MISSING`, and a `claimed_units` figure exceeding the claim type's pool on the lot at submission time is rejected with `ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS`.

A `LOST_INBOUND` claim additionally requires that the lot's `reconciliation_status` be exactly `DISCREPANCY_OPEN`; anything else — including a lot already carrying a claim, whose status is `DISCREPANCY_CLAIMED` — is rejected with `ERR_LOT_NO_OPEN_DISCREPANCY`, which is what locks a lot against a second concurrent inbound-loss claim. A successful `LOST_INBOUND` filing moves the lot's reconciliation dimension `DISCREPANCY_OPEN → DISCREPANCY_CLAIMED` without moving any units.

Filing pins `filing_deadline_at` to the selected anchor plus 60 days, and the claim opens at `status` of `SUBMITTED` with `resubmission_count` of 0, `eligible_units`, `approved_units` and `reimbursement_amount_cents` all at 0, and `decided_at` null. The filing window is then enforced at both filing and resubmission: the logical clock's current instant must be at or before `filing_deadline_at`, with equality accepted, and a clock strictly past the deadline yields `ERR_CLAIM_FILING_WINDOW_CLOSED`.

An adjudicator may bounce a claim back for more evidence, supplying an `information_request_note`. That moves the claim `SUBMITTED → INFO_REQUESTED` with no ledger movement; an attempt against a claim in any other status yields `ERR_CLAIM_NOT_ACTIONABLE`. The seller answers by resubmitting with a fresh `evidence_document_count` and `evidence_reference`, which overwrite the stored values and must again clear the type's evidence minimum. Resubmission requires `status` of `INFO_REQUESTED` (otherwise `ERR_CLAIM_NOT_ACTIONABLE`), a `resubmission_count` strictly below 2, and a logical clock at or before `filing_deadline_at`. It moves the claim `INFO_REQUESTED → SUBMITTED` and increments `resubmission_count` by 1. The cap is hard: a third resubmission attempt, made when `resubmission_count` already stands at 2, is rejected with `ERR_RESUBMISSION_LIMIT_REACHED`.

Deciding requires `status` of `SUBMITTED` (otherwise `ERR_CLAIM_NOT_ACTIONABLE`) and carries a `decision` of either `APPROVED` or `DENIED`, plus an optional `decision_note`. The two branches diverge completely.

Settlement is evaluated **at decision time**, reading the lot's pools live rather than as they stood at submission, so a pool that shrank in the interim shrinks the payout. `eligible_units` is the smaller of the claim's `claimed_units` and the pool selected by `claim_type`. The per-unit value is the smaller of the listing's `unit_cost_cents` and the seller's `unit_cost_cap_cents`. A type factor scales the result: 1.00 for `LOST_INBOUND`, 0.90 for `DAMAGED_WAREHOUSE` and 0.80 for `LOST_REMOVAL`. `reimbursement_amount_cents` is the product of `eligible_units`, the per-unit value and the type factor, with round half up applied once to that whole product. Approval requires `eligible_units` of at least 1.

An **approval** moves the claim `SUBMITTED → APPROVED` and runs a four-link cascade. The first link writes `eligible_units`, sets `approved_units` equal to `eligible_units`, writes `reimbursement_amount_cents`, stamps `decided_at` with the logical clock's current instant, and increases the seller's `reimbursement_credit_cents` by the reimbursed amount. The second link, caused by the first, decrements the claimed pool on the lot: `approved_units` is subtracted from the lot's `missing_units` for a `LOST_INBOUND` claim, from its `unfulfillable_units` for a `DAMAGED_WAREHOUSE` claim, or from its `units_removed` for a `LOST_REMOVAL` claim; when the lot's `missing_units` reaches 0 the reconciliation dimension moves `DISCREPANCY_CLAIMED → DISCREPANCY_RESOLVED`, and the seller's `open_discrepancy_units` drops by the same amount. The third link, caused by the second, recomputes the listing: `fulfillable_units`, `unfulfillable_units`, `missing_units`, `inventory_health` and `suppression_reason` are all re-derived. The fourth link, caused by the second link's change to the seller's `open_discrepancy_units`, re-runs the inventory performance score on the seller's quota period whose `status` is `ACTIVE`, refreshing `iprs_score`, `capacity_tier` and `restock_limit_units`.

A **denial** moves the claim `SUBMITTED → DENIED`, sets `approved_units` to 0 and `reimbursement_amount_cents` to 0, and stamps `decided_at`. No money moves: the seller's `reimbursement_credit_cents` is unchanged and every lot pool is unchanged. For a `LOST_INBOUND` claim the lot's reconciliation dimension moves back `DISCREPANCY_CLAIMED → DISCREPANCY_OPEN`, which unlocks the lot so a fresh inbound-loss claim may be filed — provided the logical clock has not passed the original anchor's 60-day deadline.

### 3.9. Storage Billing Epochs, Aging Surcharges and the Sweep

A `MarketplaceAdmin` advances the storage billing epoch, optionally recording a `run_note`. Each run is stamped with a 1-based `billing_run_sequence`, and it answers with a summary object reporting that `billing_run_sequence`, an `assessment_count`, a `total_assessed_cents`, a `downgraded_quota_count`, an `expired_quota_count` and a `closed_plan_count`.

A run first refreshes each lot's age. `age_days` is the whole number of days between the lot's `first_received_at` and the logical clock's current instant — the elapsed seconds divided by 86400 seconds per day, truncated downward — and it is refreshed both on every read of the lot and on every billing run. The `aged_bucket` follows from `age_days` by four thresholds evaluated top down: `OVER_365` at 365 days or more, `D271_365` at 271 days or more, `D181_270` at 181 days or more, and `UNDER_181` below that.

The run then writes one assessment row per **eligible** lot, where eligible means `lot_status` of `ACTIVE` or `PARTIALLY_REMOVED`; lots whose `lot_status` is `DEPLETED` are excluded entirely and receive no row at all. Eligible lots are processed in ascending `first_received_at` order with ascending `created_at` as tie-break. Each row records its `inventory_lot_id`, the run's `billing_run_sequence`, an `assessed_at` stamped from the logical clock, the lot's `age_days_at_assessment` evaluated at that instant, and the `aged_bucket` pinned at that instant.

Pricing per lot works from volume. The billable unit count is the sum of the lot's `fulfillable_units`, `unfulfillable_units` and `units_reserved_for_removal` — reserved units are still stored and still billable. `billable_cubic_feet` is that count multiplied by the listing's `unit_cubic_feet`, rounded to four decimal places. `monthly_storage_fee_cents` is `billable_cubic_feet` multiplied by the holding centre's `monthly_storage_rate_cents_per_cubic_foot`, rounded half up to whole cents. The long-term surcharge is stepped: two steps when the pinned `aged_bucket` is `OVER_365`, one step when it is `D271_365`, and none for `D181_270` or `UNDER_181`. `ltsf_surcharge_cents` is `billable_cubic_feet` multiplied by the centre's `ltsf_rate_cents_per_cubic_foot` multiplied by that step count, rounded half up to whole cents. `total_fee_cents` is `monthly_storage_fee_cents` plus `ltsf_surcharge_cents`. A lot's `ltsf_exposed` flag is true exactly when its most recent assessment carried a `ltsf_surcharge_cents` greater than zero.

The rounding order here is pinned and must not be rearranged. Each lot's `monthly_storage_fee_cents` and `ltsf_surcharge_cents` are rounded half up to whole cents **first**, then added together per lot, then the per-lot integers are summed into the lot's `storage_fee_accrued_cents` and into the seller's `storage_fee_accrued_cents`. Summing raw cubic feet across lots and rounding once at the end is a different and forbidden result: two lots holding 0.5831 and 0.9163 cubic feet at a rate of 87 cents per cubic foot give 51 plus 80, or 131 cents, under per-lot rounding, whereas rounding the combined 1.4994 cubic feet once gives 130 cents.

Storage utilization is recomputed at the start of a run and, more generally, on every mutation that changes a lot pool. The total stored volume is the sum, over the seller's lots whose `lot_status` is `ACTIVE` or `PARTIALLY_REMOVED`, of that lot's billable unit count multiplied by its listing's `unit_cubic_feet`, each per-lot product rounded to four decimal places before the summation; `DEPLETED` lots contribute nothing. The seller's `storage_utilization_ratio` is that total divided by the seller's `storage_cubic_feet_entitlement`, rounded half up to four decimal places.

Inside a billing run — and only inside a billing run — an over-entitlement seller loses capacity. When the recomputed `storage_utilization_ratio` is strictly greater than 1.0000 and the seller has a quota period whose `status` is `ACTIVE`, that period's `capacity_tier_downgrade_steps` increases by exactly 1, and the inventory performance score is re-run for it so that `capacity_tier` and `restock_limit_units` reflect the new step count. At most one step is added per run, however far above entitlement the seller sits — repeated overuse costs repeated runs.

Two sweeps close out the run. Every quota period whose `status` is `ACTIVE` and whose `period_end` is at or before the logical clock's current instant moves `ACTIVE → EXPIRED`; no ledger moves, but the seller can no longer confirm plans until a new period is opened, and attempts fail with `ERR_NO_ACTIVE_RESTOCK_QUOTA`. And every plan whose `status` is `RECEIVED_COMPLETE` or `PARTIALLY_RECEIVED` and whose `appointment_window_end` plus 30 days is at or before the logical clock's current instant is closed. The two closure branches differ. A plan closing from `RECEIVED_COMPLETE` moves `RECEIVED_COMPLETE → CLOSED` with no ledger movement, since it already left the reserving set at receipt. A plan closing from `PARTIALLY_RECEIVED` moves `PARTIALLY_RECEIVED → CLOSED` and must release what it still holds: the seller's `restock_reserved_units` is decremented by the plan's `allocated_units`, the destination centre's `committed_receiving_units` is decremented by the plan's `declared_units`, and the plan's `allocated_units` is set to 0. That closure deliberately leaves each lot's `missing_units` and `reconciliation_status` untouched — an unclaimed shortfall stays open even after the plan that caused it is closed, and it keeps suppressing the listing until a claim resolves it.

Finally, the run recomputes listing health across the affected listings, which is how a listing holding freshly-aged stock moves from `HEALTHY` to `EXCESS_AGED`.

## 4. Endpoint Definitions

Operations that bring a new resource into existence — registering a seller or a fulfillment center, opening a quota period, creating a listing, drafting a plan, adding a line item, producing a forecast, requesting a removal, filing a claim, placing a multi-channel order, or triggering a billing run — return `201 Created`. Every operation that reads or modifies an existing resource, including all state transitions and all posture updates, returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fulfillment/sellers` | Register a seller account | MarketplaceAdmin |
| GET | `/fulfillment/sellers/{id}` | Read a seller account with its derived quota, storage and reimbursement ledgers | MarketplaceAdmin, SellerOperator, ClaimsAdjudicator |
| GET | `/fulfillment/sellers/{id}/sku-listings` | List the seller's SKU listings | MarketplaceAdmin, SellerOperator |
| GET | `/fulfillment/sellers/{id}/restock-quotas` | List the seller's quota periods, newest first | MarketplaceAdmin, SellerOperator |
| POST | `/fulfillment/sellers/{id}/restock-quotas` | Open a quota period with performance inputs; supersedes the seller's active quota | MarketplaceAdmin |
| POST | `/fulfillment/fulfillment-centers` | Register a fulfillment center with its prep profile, window capacity and storage rates | MarketplaceAdmin |
| GET | `/fulfillment/fulfillment-centers/{id}` | Read a fulfillment center with its committed receiving units | MarketplaceAdmin, FcOperator, SellerOperator |
| PATCH | `/fulfillment/fulfillment-centers/{id}` | Update receiving posture or window capacity | FcOperator, MarketplaceAdmin |
| POST | `/fulfillment/sku-listings` | Create a SKU listing | SellerOperator |
| GET | `/fulfillment/sku-listings/{id}` | Read a listing with both state dimensions and its derived unit rollups | MarketplaceAdmin, SellerOperator, ClaimsAdjudicator, FcOperator |
| POST | `/fulfillment/sku-listings/{id}/reinstate` | Clear a suppression once fulfillable inventory exists again | SellerOperator |
| GET | `/fulfillment/sku-listings/{id}/line-items` | List every shipment line item for this listing | MarketplaceAdmin, SellerOperator |
| GET | `/fulfillment/sku-listings/{id}/velocity-forecasts` | List this listing's forecasts, newest first | MarketplaceAdmin, SellerOperator |
| POST | `/fulfillment/sku-listings/{id}/velocity-forecasts` | Produce a sell-through velocity forecast and a replenishment recommendation | SellerOperator |
| GET | `/fulfillment/sku-listings/{id}/multi-channel-orders` | List this listing's multi-channel orders | MarketplaceAdmin, SellerOperator |
| POST | `/fulfillment/inbound-shipment-plans` | Create an inbound shipment plan against a destination centre appointment window | SellerOperator |
| GET | `/fulfillment/inbound-shipment-plans` | List plans filtered by seller, destination centre or status | MarketplaceAdmin, SellerOperator, FcOperator |
| GET | `/fulfillment/inbound-shipment-plans/{id}` | Read a plan with its provisional and final allocation figures | MarketplaceAdmin, SellerOperator, FcOperator |
| POST | `/fulfillment/inbound-shipment-plans/{id}/line-items` | Add a line item to a draft plan; re-runs the provisional allocation waterfall | SellerOperator |
| GET | `/fulfillment/inbound-shipment-plans/{id}/line-items` | List a plan's line items in creation order | MarketplaceAdmin, SellerOperator, FcOperator |
| POST | `/fulfillment/inbound-shipment-plans/{id}/confirm` | Confirm a draft plan: prep, label, case-pack, window capacity and final allocation are all enforced here | SellerOperator |
| POST | `/fulfillment/inbound-shipment-plans/{id}/revert-to-draft` | Return a confirmed plan to draft, releasing every reservation it holds | SellerOperator |
| POST | `/fulfillment/inbound-shipment-plans/{id}/ship` | Mark a confirmed plan as in transit | SellerOperator |
| POST | `/fulfillment/inbound-shipment-plans/{id}/receive` | Record a receipt at the destination centre; drives the completion fork and the discrepancy cascade | FcOperator |
| POST | `/fulfillment/inbound-shipment-plans/{id}/cancel` | Cancel a draft or confirmed plan, releasing every reservation it holds | SellerOperator |
| GET | `/fulfillment/inventory-lots` | List lots filtered by listing, centre or state | MarketplaceAdmin, SellerOperator, FcOperator |
| GET | `/fulfillment/inventory-lots/{id}` | Read a lot with both state dimensions, every unit pool, its age bucket and accrued storage fees | MarketplaceAdmin, SellerOperator, FcOperator, ClaimsAdjudicator |
| POST | `/fulfillment/inventory-lots/{id}/unfulfillable-classification` | Move units from the fulfillable pool to the unfulfillable pool at the holding centre | FcOperator |
| GET | `/fulfillment/inventory-lots/{id}/storage-fee-assessments` | List a lot's storage assessments, oldest first | MarketplaceAdmin, SellerOperator |
| GET | `/fulfillment/inventory-lots/{id}/removal-orders` | List a lot's removal orders | MarketplaceAdmin, SellerOperator, FcOperator |
| GET | `/fulfillment/inventory-lots/{id}/reimbursement-claims` | List a lot's reimbursement claims | MarketplaceAdmin, SellerOperator, ClaimsAdjudicator |
| POST | `/fulfillment/removal-orders` | Request a removal against a lot pool inside a closed execution window | SellerOperator |
| GET | `/fulfillment/removal-orders/{id}` | Read a removal order with its settlement figures | MarketplaceAdmin, SellerOperator, FcOperator |
| POST | `/fulfillment/removal-orders/{id}/complete` | Execute a requested removal at the holding centre | FcOperator |
| POST | `/fulfillment/removal-orders/{id}/cancel` | Cancel a requested removal and return the units to their source pool | SellerOperator |
| POST | `/fulfillment/reimbursement-claims` | File a reimbursement claim for lost or damaged units with evidence, inside the filing window | SellerOperator |
| GET | `/fulfillment/reimbursement-claims/{id}` | Read a claim with its deadline, resubmission count and settlement figures | MarketplaceAdmin, SellerOperator, ClaimsAdjudicator |
| POST | `/fulfillment/reimbursement-claims/{id}/request-info` | Ask the seller for more evidence | ClaimsAdjudicator |
| POST | `/fulfillment/reimbursement-claims/{id}/resubmit` | Supply fresh evidence and return the claim to the adjudication queue | SellerOperator |
| POST | `/fulfillment/reimbursement-claims/{id}/decide` | Approve or deny a submitted claim | ClaimsAdjudicator |
| POST | `/fulfillment/multi-channel-orders` | Place a multi-channel order and compare the marketplace fee against the seller's own cost | SellerOperator |
| POST | `/fulfillment/storage-billing-runs` | Advance the storage billing epoch: assess lots, apply utilization downgrades, expire quotas and close aged plans | MarketplaceAdmin |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | MarketplaceAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SELLER_NOT_FOUND` | 404 |
| `ERR_FC_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_REMOVAL_ORDER_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 |
| `ERR_SELLER_SCOPE_VIOLATION` | 403 |
| `ERR_FC_SCOPE_VIOLATION` | 403 |
| `ERR_STALE_SELLER_VERSION` | 412 |
| `ERR_STALE_LOT_VERSION` | 412 |
| `ERR_PLAN_NOT_DRAFT` | 409 |
| `ERR_PLAN_NOT_CONFIRMED` | 409 |
| `ERR_PLAN_NOT_RECEIVABLE` | 409 |
| `ERR_PLAN_NOT_CANCELLABLE` | 409 |
| `ERR_REMOVAL_NOT_REQUESTED` | 409 |
| `ERR_CLAIM_NOT_ACTIONABLE` | 409 |
| `ERR_LISTING_NOT_SUPPRESSED` | 409 |
| `ERR_FC_RECEIVING_SUSPENDED` | 409 |
| `ERR_NO_ACTIVE_RESTOCK_QUOTA` | 409 |
| `ERR_LOT_NO_OPEN_DISCREPANCY` | 409 |
| `ERR_SUPPRESSION_CONDITION_PERSISTS` | 409 |
| `ERR_REMOVAL_WINDOW_NOT_OPEN` | 409 |
| `ERR_PREP_REQUIREMENT_UNMET` | 422 |
| `ERR_LABEL_REQUIREMENT_UNMET` | 422 |
| `ERR_APPOINTMENT_WINDOW_INVALID` | 422 |
| `ERR_APPOINTMENT_WINDOW_IN_PAST` | 422 |
| `ERR_CLAIM_FILING_WINDOW_CLOSED` | 422 |
| `ERR_CASE_PACK_VIOLATION` | 422 |
| `ERR_PLAN_HAS_NO_LINE_ITEMS` | 422 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_REMOVAL_WINDOW_CONFLICT` | 409 |
| `ERR_RESUBMISSION_LIMIT_REACHED` | 422 |
| `ERR_LISTING_SELLER_MISMATCH` | 422 |
| `ERR_EVIDENCE_REFERENCE_MISSING` | 422 |
| `ERR_INSUFFICIENT_POOL_UNITS` | 422 |
| `ERR_REIMBURSEMENT_EXCEEDS_ELIGIBLE_UNITS` | 422 |
| `ERR_NO_FULFILLABLE_INVENTORY` | 422 |
| `ERR_FC_RECEIVING_CAPACITY_EXCEEDED` | 422 |
| `ERR_RESTOCK_LIMIT_EXCEEDED` | 422 |
