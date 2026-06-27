# Ag Equipment Dealer API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Ag Equipment Dealer API, the system of record for a full-line agricultural equipment dealership operating in the style of a John Deere franchise. A dealership of this kind juggles several intertwined businesses at once: it carries new and used whole goods on a floor-plan line of credit, sells and leases those units to farmers and commercial operations, takes equipment in on trade, runs a service shop that bills against published flat-rate labor and a parts counter that includes precision-agriculture and telematics SKUs, files warranty and manufacturer-campaign reimbursement claims, consigns used iron to auction, and pre-sells next season's equipment through early-order programs. Each of these surfaces touches the same scarce resource — an individual unit of inventory — and the central challenge of the system is keeping that unit's lifecycle coherent as sales, leases, auctions, repossessions, and floor-plan financing compete for it.

The API is consumed by distinct dealership roles, each owning a slice of the operation, and it enforces the financial and state-machine discipline that keeps the books straight: floor-plan interest accrues day by day against a curtailment schedule, deal economics net trades against taxable price, lease payments derive from credit-tier residuals, and warranty reimbursements honor safety recalls without exception. Because several writers may act on the same unit, the system relies on optimistic concurrency control to reject stale funding and settlement attempts rather than allowing one operator to silently overwrite another's view. The remainder of this document defines the global contract that every endpoint honors, the business logic that governs each workflow, and the precise calculations that produce every monetary figure the system stores.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers. The `X-User-ID` header identifies the acting operator, and the `X-User-Role` header declares the operational capacity under which the request is made. If either header is absent, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes exactly six roles, spelled precisely as follows: `DealerAdmin`, `SalesRep`, `FinanceManager`, `ServiceAdvisor`, `PartsClerk`, and `AuctionClerk`. `DealerAdmin` is the dealer principal — a superset operator that may perform every shared operation plus a set of override-only actions (reconditioning a repossessed unit, retiring inventory, flagging a note in default, adjudicating and paying warranty claims, and advancing the logical clock). `SalesRep` sells units, manages trade-in appraisals, quotes and delivers deals, and runs seasonal whole-goods orders. `FinanceManager` owns the credit lifecycle of deals — approval, funding, and unwinding — as well as floor-plan financing. `ServiceAdvisor` owns service work orders and the drafting and submission of warranty claims. `PartsClerk` owns the parts catalog and inventory and adds part lines to work orders. `AuctionClerk` owns the auction lot lifecycle — consign, open, close, settle — and records bids. When a request is well-authenticated but the acting role is not permitted to perform the requested operation under the access matrix described in Section 4, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

All six roles carry an **opaque** identity. That is, for each of `DealerAdmin`, `SalesRep`, `FinanceManager`, `ServiceAdvisor`, `PartsClerk`, and `AuctionClerk`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes, but it never compares `X-User-ID` to any entity's `id`, and ownership of a resource is never determined by matching the acting user against a stored foreign key. Authorization is purely role-based.

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

List endpoints accept two pagination query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and its accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set; when omitted it defaults to 0.

Unless an endpoint states otherwise, list results are sorted by the resource's `created_at` timestamp in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the total number of matching resources before the page window is applied and `has_more` indicates whether further pages exist beyond the current window.

### 2.4. Common Resource Properties

Most resources in this system are "first-class" and carry a standard set of system-managed fields. Each such resource exposes an `id` — a server-minted UUID with no type prefix — along with a `created_at` timestamp (ISO 8601 UTC with three fractional digits) marking when it was created, an `updated_at` timestamp recorded in the same format and refreshed on every mutation, and an integer `version` that begins at 1 and increments by one with each mutation of the resource. The `version` field is what optimistic concurrency control reads, as described in Section 2.7.

`Unit`, `FloorPlanNote`, `Customer`, `TradeIn`, `Deal`, `AuctionLot`, `WorkOrder`, `PartLine`, `Part`, `WarrantyClaim`, and `WholeGoodsOrder` are all first-class resources and carry the full `id`, `created_at`, `updated_at`, and `version` set. The one exception is the `Bid` resource: a bid is an append-only record and is **not** a versioned resource. A `Bid` carries only an `id` and a `created_at` timestamp; it has neither an `updated_at` field nor a `version` field, because a bid is never modified after it is recorded.

### 2.5. Inventory State Propagation and Hierarchical Consistency

The single inventory `Unit` is the spine of the system, and many operations on peer entities mutate a unit as a side effect. Whenever an operation changes a unit's `status`, that mutation refreshes the unit's `updated_at` and increments its `version` by one. The same holds for every other first-class resource that an operation touches: any state transition or field recomputation that alters a resource refreshes its `updated_at` and bumps its `version`.

Several operations cascade across entity boundaries, and every secondary effect of such an operation is part of that operation's contract — not an optional convenience. Funding a deal, settling an auction lot, unwinding a deal, closing a work order, and confirming or cancelling a whole-goods order all reach beyond their primary entity to mutate floor-plan notes, trade-ins, minted units, parts inventory, and reserved counts. The business-logic subsections in Section 3 specify each cascade in full; the governing principle here is that when the system performs a cascade it applies every leg of it atomically, so the books never reflect a half-applied transition.

Several derived fields are recomputed lazily when a resource is read. Retrieving a single floor-plan note recomputes its `interest_accrued_cents` and `days_outstanding` against the current clock before returning it. Retrieving a single part recomputes its `reserved_qty`. These read-time recomputations keep derived figures current without requiring a separate write.

### 2.6. Path Resolution and Referential Existence

Many endpoints reference resources both in the URL path and in the request body — a unit, a deal, an auction lot, a work order, a customer, a part, a trade-in, or a claim. The system validates referenced resources left to right: it resolves each identifier in turn, and the first identifier that does not correspond to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any later identifier or business rule is evaluated. This applies uniformly to path parameters such as the `{id}` of a unit, deal, lot, work order, part line, claim, or order, and to body-supplied foreign keys such as `unit_id`, `customer_id`, `tradein_id`, `part_id`, `lot_id`, `work_order_id`, and `warranty_claim_id`.

### 2.7. Optimistic Concurrency Control on Inventory Units

Because a unit can be acted upon from several surfaces at once — a finance manager funding a sale, an auction clerk settling a lot — two operations carry a mandatory optimistic-concurrency guard keyed to the unit's `version`.

The first is deal funding. A request to fund a deal must carry `expected_unit_version`, a non-optional field whose value is the unit `version` the client last observed. If that value does not match the current `version` of the unit referenced by the deal, the funding request is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412). This captures the case where another writer has already advanced the unit — for example, the unit was moved out of `RESERVED` by a competing auction listing or another deal funding — since the client read it, so the client's funding view is stale and must not be allowed to overwrite the newer state.

The second is auction settlement. A request to settle an auction lot must likewise carry `expected_unit_version` matching the current `version` of the consigned unit. If the unit's version has advanced since the clerk last read it — because the unit was reconditioned, retired, or otherwise claimed by another path between the clerk's read and settlement — the settlement is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412).

These are the only two endpoints that take a version field. Every other mutating endpoint in the system processes without any client-supplied version and performs no optimistic-concurrency check.

### 2.8. Monetary Values, Quantities, and Rounding

All monetary amounts in the system are stored as whole integer cents — there are no fractional-cent fields. Where a calculation produces a fractional cent during evaluation, the system applies **round half up** to the relevant product or sum and stores the resulting whole number of cents. Each calculation in Section 3 names the exact point at which rounding occurs, because for several of them the order in which intermediate results are rounded is significant and is pinned. Quantities (part counts, fulfilled units) are always whole integers. Where a calculation reduces a fractional quantity such as elapsed time, the system takes the floor of the elapsed days, as described with the floor-plan interest rules.

### 2.9. The Logical Clock

Time-sensitive behavior — floor-plan interest accrual, curtailment breakpoints, and auction bidding windows — is governed by a logical clock rather than wall-clock time. At server startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it remains at that default and never falls back to wall-clock time. An administrative capability accepts a `to_iso8601` instant and sets the clock to that value; advancing the clock triggers a recompute of interest accrual and curtailment stage on every floor-plan note that is currently `ACTIVE` or `CURTAILMENT_DUE`. This capability responds `200 OK` with a `data` object carrying a single `current_utc` field set to the new clock value (ISO 8601 UTC with three fractional digits). The clock is the reference for every "current clock" comparison made elsewhere in this document.

## 3. Business Logic & Workflows

### 3.1. Inventory Units and Their Lifecycle

Every piece of whole goods the dealership carries is a `Unit`. A unit is created with a dealer `stock_number`, a `condition` of either `NEW` or `USED`, a manufacturer `model_code` (for example `8R410`), a manufacturer `serial_number`, a `dealer_cost_cents` acquisition/invoice cost, and a `list_price_cents` asking price; an optional `engine_hours` meter reading may be supplied and defaults to 0 (it should be 0 for `NEW` units). Both `dealer_cost_cents` and `list_price_cents` must be zero or greater, and `engine_hours` must be zero or greater. The `stock_number` must be unique across all units and the `serial_number` must be unique across all units; an attempt to create a unit whose stock number or serial number collides with an existing one is rejected with `ERR_DUPLICATE_KEY` (HTTP 409). A newly created unit begins life `AVAILABLE`.

A unit also carries two system-maintained fields that are never set directly by the client. The `floor_planned` boolean reads `true` exactly while an `ACTIVE` floor-plan note references the unit and defaults to `false`. The `acquired_from_tradein_id` field records the lineage of a used unit that was minted from an accepted trade-in — it points back to the originating trade-in — and is `null` for units the dealer purchased outright. This is the self-referential lineage of the inventory: a trade-in becomes a unit, and that unit remembers the trade it came from.

A unit's `status` moves through the values `AVAILABLE`, `RESERVED`, `SOLD`, `LEASED`, `AUCTION_LISTED`, `AUCTION_SOLD`, `REPOSSESSED`, and `RETIRED`. Quoting a sale or lease deal against an `AVAILABLE` unit, or allocating an `AVAILABLE` unit to a whole-goods order, moves it `AVAILABLE → RESERVED` so that no other deal or auction can claim it. Funding a sale deal moves the reserved unit `RESERVED → SOLD`; funding a lease moves it `RESERVED → LEASED`. Consigning a used unit to auction moves it `AVAILABLE → AUCTION_LISTED` and locks it out of sale and lease deals while listed. The lifecycle is also cyclic: a funded sale that is later unwound moves the unit `SOLD → REPOSSESSED`, and a `DealerAdmin` reconditioning capability returns it `REPOSSESSED → AVAILABLE`, completing the cycle `AVAILABLE → SOLD → REPOSSESSED → AVAILABLE`. Reconditioning is permitted only when the unit is currently `REPOSSESSED`. Finally, a `DealerAdmin` may retire a unit, moving it `AVAILABLE → RETIRED` (terminal), but only when the unit is `AVAILABLE` and its `floor_planned` flag is `false` — a unit still under floor-plan financing cannot be retired. Each of reconditioning, retirement, and every other unit transition refreshes the unit and increments its `version` by one. Any transition attempted from a state in which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.2. Floor-Plan Financing: Activation, Accrual, and Curtailment

A `FloorPlanNote` is the lender's financing instrument against a single inventory unit. A finance manager (or admin) drafts a note by supplying the `unit_id` it finances, the `principal_cents` advanced by the floor-plan lender (which must be greater than zero), and the `annual_rate_bps` annual interest rate in basis points (for example, 875 represents 8.75%; this must be greater than zero). A newly drafted note is `DRAFT` and carries the system-maintained fields `curtailment_paid_cents` (cumulative principal curtailment applied, starting at 0), `interest_accrued_cents` (starting at 0), `days_outstanding` (starting at 0), `curtailment_stage` (the count of breakpoints passed, starting at 0), and `activated_on` (the clock time of activation, set later).

Activating a draft note moves it `DRAFT → ACTIVE`, sets `activated_on` to the current clock as the accrual anchor, and sets the financed unit's `floor_planned` to `true`. Activation is permitted only when the referenced unit is `AVAILABLE` and the unit has no other note already in `ACTIVE` or `CURTAILMENT_DUE` status; a violation of the defined transition surfaces as `ERR_INVALID_STATE`.

**Interest accrual.** The note's `days_outstanding` is the count of whole days between `activated_on` and the current clock, inclusive of the start day and exclusive of the end day — that is, the floor of the elapsed days. Interest accrues on the principal that remains after curtailment payments. The daily rate is the annual rate in basis points divided by 10,000 and then divided by 365. The outstanding base is `principal_cents` minus `curtailment_paid_cents`. The accrued interest is that outstanding base multiplied by the daily rate and multiplied by `days_outstanding`, with the result rounded half up to whole cents and stored in `interest_accrued_cents`. When no curtailment has been paid, the base is simply the full `principal_cents`; once one or more curtailments have been applied, accrual is recomputed from `activated_on` each time against the reduced base. Recompute happens both when the logical clock is advanced and when a note is explicitly recomputed; reading a single note also refreshes `interest_accrued_cents` and `days_outstanding` to the current clock.

**Curtailment schedule.** The note carries curtailment breakpoints at 90, 180, and 270 whole days outstanding. The stage is 0 below 90 days; it is 1 once `days_outstanding` reaches at least 90, 2 once it reaches at least 180, and 3 once it reaches at least 270 — each boundary is inclusive, so exactly 90 days outstanding already triggers stage 1. Each crossed breakpoint requires a cumulative 10% of the principal to have been paid: the required cumulative curtailment is `principal_cents` multiplied by 0.10 multiplied by the current stage, rounded half up to whole cents. The shortfall is the required cumulative amount minus `curtailment_paid_cents`, floored at zero. A note is considered to owe a curtailment exactly when that shortfall is greater than zero. When a recompute (whether triggered by a clock advance or an explicit recompute request) finds that the curtailment stage has increased since the last recompute and the new stage's required curtailment is unpaid (its shortfall is positive), the note moves `ACTIVE → CURTAILMENT_DUE` and its `interest_accrued_cents` and `curtailment_stage` are recomputed.

A finance manager clears a due curtailment by making a curtailment payment carrying `payment_cents`. The payment must be at least the shortfall required for the current stage, as computed above; a payment below that shortfall is rejected with `ERR_CURTAILMENT_SHORT` (HTTP 409). A sufficient payment adds `payment_cents` to `curtailment_paid_cents`, and if all due stages are thereby satisfied the note returns `CURTAILMENT_DUE → ACTIVE`. A `DealerAdmin` may instead flag a curtailment-due note as defaulted, moving it `CURTAILMENT_DUE → DEFAULTED` (terminal); in default the unit's `floor_planned` flag remains `true` because the lender holds title. Default is permitted only from `CURTAILMENT_DUE`.

A floor-plan note is paid off as a cascade, never directly: when the financed unit is sold, leased, or sold at auction, an `ACTIVE` or `CURTAILMENT_DUE` note on that unit moves to `PAID_OFF` (terminal), its `interest_accrued_cents` is frozen at its final value, and the unit's `floor_planned` flag clears to `false`. Both `PAID_OFF` and `DEFAULTED` are terminal states for a note.

### 3.3. Customers and Trade-In Appraisal

A `Customer` represents a farm or buyer and is created with a `name`, a `customer_type` of `RETAIL`, `COMMERCIAL_AG`, or `GOVERNMENT`, an optional `credit_tier` of `PRIME`, `STANDARD`, or `SUBPRIME` (defaulting to `STANDARD`), and an optional `tax_exempt` boolean (defaulting to `false`) that marks qualifying agricultural or government buyers. The credit tier drives lease residual and rate bands, and tax-exempt status suppresses sales tax at funding.

A trade-in begins as an appraisal. A sales rep appraises a `TradeIn` by supplying the `customer_id` offering the trade, the trade unit's `model_code` and `serial_number`, its `engine_hours` (which must be zero or greater), a `condition_grade` of `EXCELLENT`, `GOOD`, `FAIR`, or `POOR`, and a guide-book `base_value_cents` before adjustments (which must be greater than zero). At creation the system computes the `appraised_value_cents` allowance and sets the trade-in's `status` to `APPRAISED`. The appraisal applies a grade factor — `EXCELLENT` is 1.00, `GOOD` is 0.85, `FAIR` is 0.65, and `POOR` is 0.40 — and an hours penalty. The hours penalty is one percent of base for each full 100 engine hours, capped at 40 percent: take the floor of `engine_hours` divided by 100, multiply by 0.01, and use the smaller of that figure and 0.40 as the penalty fraction. The appraised allowance is `base_value_cents` multiplied by the grade factor and then multiplied by one minus the hours-penalty fraction, with a single round-half-up applied to the final product (multiply both factors first, then round once) and stored in `appraised_value_cents`.

A trade-in also carries a `minted_unit_id`, which is `null` until the trade is accepted into inventory and then points to the used `Unit` created from it. The appraisal lifecycle runs `APPRAISED → OFFERED → ACCEPTED` or `→ DECLINED`. A sales rep offers an appraised trade — moving it `APPRAISED → OFFERED` — to make the allowance available to attach to a deal. An offered trade can be declined by a sales rep, moving it `OFFERED → DECLINED`, after which it can no longer be attached and any deal still referencing it must drop the trade before funding. Acceptance is never a direct action: when a deal that names the trade in its `tradein_id` is funded, the system moves the trade `OFFERED → ACCEPTED` as a cascade and mints a new used unit from it (see Section 3.4). Should that funding deal later be unwound, the trade is reverted `ACCEPTED → DECLINED` and the minted unit is retired, again as a cascade. `ACCEPTED` and `DECLINED` are the terminal grades of a trade-in.

### 3.4. Deals: Quoting, Approval, Funding, and Unwind

A `Deal` is the sale, lease, or auction-sale instrument. A sales rep or finance manager quotes a deal by supplying the `unit_id` being transacted, the `customer_id` buyer or lessee, a `deal_type` of `SALE`, `LEASE`, or `AUCTION_SALE`, a `sale_price_cents` (the agreed price for a sale or auction sale, or the capitalized cost for a lease; it must be greater than zero), an optional `lease_term_months` (the lease term in months, defaulting to 0 and required to be zero or greater, with 0 used for non-lease deals), and an optional `tradein_id` naming a trade to apply (or `null` when there is no trade). Quoting a `SALE` or `LEASE` deal reserves the unit, moving it `AVAILABLE → RESERVED`; quoting an `AUCTION_SALE` deal does not reserve the unit and leaves its status `AVAILABLE`. The new deal starts `QUOTED`. A deal also carries the computed fields `trade_allowance_cents`, `tax_cents`, `monthly_payment_cents`, and `amount_due_cents`, all of which default to 0 and are populated at funding.

Quoting requires the referenced unit to be `AVAILABLE`; a quote against a unit that is not available is rejected with `ERR_UNIT_NOT_RESERVABLE` (HTTP 409). If the deal names a trade, that trade may be attached only while it is `OFFERED`; attaching a trade that is `DECLINED` or `ACCEPTED` (or otherwise not `OFFERED`) is rejected with `ERR_TRADEIN_NOT_OFFERED` (HTTP 409). This trade-attach rule is enforced at quote time, at approval, and again at funding.

A finance manager approves a quoted deal, moving it `QUOTED → APPROVED` and recording the credit decision; approval is permitted only when the deal is `QUOTED`, and if the deal names a trade that trade must be `OFFERED` at approval (otherwise `ERR_TRADEIN_NOT_OFFERED`). Approval makes the deal eligible to fund.

Funding is the pivotal transition and is restricted to a finance manager. Funding moves the deal `APPROVED → FUNDED` and requires that the deal be `APPROVED`, that the referenced unit be `RESERVED` (otherwise `ERR_UNIT_NOT_RESERVABLE`), and that any named trade be `OFFERED` (otherwise `ERR_TRADEIN_NOT_OFFERED`). The request must carry `expected_unit_version` matching the unit's current `version`, failing which it is rejected with `ERR_STALE_UNIT_VERSION` (see Section 2.7). On funding, the system computes the deal economics and runs the cascades: for a `SALE` or `AUCTION_SALE` it computes `tax_cents`, `trade_allowance_cents`, and `amount_due_cents`; for a `LEASE` it computes `monthly_payment_cents`. It then moves the unit `RESERVED → SOLD` for a sale or `RESERVED → LEASED` for a lease. If the unit is floor-planned, the `ACTIVE` or `CURTAILMENT_DUE` floor-plan note is paid off as a cascade (note `→ PAID_OFF`, `floor_planned → false`). If the deal named a trade, that trade moves `OFFERED → ACCEPTED` and a used unit is minted from it. The minted unit is created with `condition` `USED`, `status` `AVAILABLE`, `dealer_cost_cents` equal to the trade's `appraised_value_cents`, `list_price_cents` also equal to the trade's `appraised_value_cents`, and `model_code` and `engine_hours` copied from the trade (its `stock_number` and `serial_number` are server-generated and need not match the trade's); the trade's `minted_unit_id` is set to the new unit and the new unit's `acquired_from_tradein_id` is set back to the trade. Funding increments the unit's `version` by one and the deal's `version` by one.

After funding, a sales rep or finance manager delivers a funded deal, moving it `FUNDED → DELIVERED` (terminal) to close it out and mark the unit physically delivered; delivery requires the deal to be `FUNDED`. Alternatively, a finance manager may unwind a funded deal — but only a `SALE` deal, and only while it is `FUNDED`. Unwinding moves the deal `FUNDED → UNWOUND` (terminal) and is a compensating action whose net effect must return the dealer's cash position to its pre-funding value: it reverses `tax_cents` and `trade_allowance_cents` back to 0, moves the unit `SOLD → REPOSSESSED` as a cascade, and, if the deal had a trade-in, retires the minted unit and reverts that trade `ACCEPTED → DECLINED`. Unwinding also requires `expected_unit_version` to match the unit's current `version`, rejecting with `ERR_STALE_UNIT_VERSION` on a mismatch, and increments the deal's `version` and the unit's `version` by one.

**Deal amount due (SALE / AUCTION_SALE).** The cash due from the customer is computed at funding in a pinned order to resolve the apparent circularity between trade and tax. First, the `trade_allowance_cents` is the linked trade-in's `appraised_value_cents` when the deal names a trade, and 0 otherwise. Second, the taxable base is the `sale_price_cents` minus the trade allowance, floored at zero so a trade larger than the price cannot drive the base negative — the trade reduces the taxable base. Third, the `tax_cents` is zero if the customer is tax-exempt; otherwise it is the taxable base multiplied by the tax rate of 0.0725 (7.25%), rounded half up to whole cents — tax is computed on the taxable base after the trade reduction, not on the gross price. Fourth, the `amount_due_cents` is the taxable base plus `tax_cents`.

**Lease monthly payment (LEASE).** The lease payment is computed at funding with two rounding steps in a pinned order. The residual percentage is taken by credit tier — `PRIME` is 0.55, `STANDARD` is 0.50, and `SUBPRIME` is 0.45. The capitalized cost is the `sale_price_cents` minus the trade-in's `appraised_value_cents` when a trade is named (and minus 0 otherwise). The residual is `sale_price_cents` multiplied by the residual percentage and rounded half up to whole cents — this is the first rounding step, and it is taken on the sale price (the MSRP), not on the capitalized cost. The depreciation is the capitalized cost minus the rounded residual. The money factor is taken by credit tier — `PRIME` is 0.0010, `STANDARD` is 0.0015, and `SUBPRIME` is 0.0022. The base monthly amount is the depreciation divided by `lease_term_months`, kept in fractional cents (no integer truncation at this step). The rent charge is the capitalized cost plus the rounded residual, multiplied by the money factor. The `monthly_payment_cents` is the base monthly amount plus the rent charge, with a single round-half-up applied to that sum — this is the second rounding step. The order is pinned: the residual is rounded before depreciation is derived, and the final payment is rounded only after summing the depreciation-per-month and rent components.

### 3.5. Used-Equipment Auctions

Used iron the dealership wishes to wholesale is consigned to auction as an `AuctionLot`. An auction clerk (or admin) consigns a used unit by supplying its `unit_id`, a `reserve_price_cents` minimum acceptable hammer price (which must be greater than zero), an `opens_at` instant when bidding opens, and a `closes_at` instant when it closes. The `closes_at` must be strictly after `opens_at`; a window where it is not is rejected with `ERR_AUCTION_WINDOW` (HTTP 409). Consignment is permitted only when the unit is `AVAILABLE` and its `condition` is `USED`; it moves the unit `AVAILABLE → AUCTION_LISTED` and the new lot starts `DRAFT`. The lot also carries the computed fields `high_bid_cents` (the highest bid so far, starting at 0), `high_bidder_customer_id` (the current high bidder, `null` until the first bid), and the system field `winning_deal_id` (the auction-sale deal created at settlement, `null` until settled with a sale).

An auction clerk opens a draft lot, moving it `DRAFT → LIVE`; opening is permitted only when the lot is `DRAFT` and the current clock is at or after `opens_at`. Opening or closing outside the permitted clock window is rejected with `ERR_AUCTION_WINDOW`. While a lot is `LIVE`, a bid is placed by supplying the `bidder_customer_id` and the `amount_cents` of the bid (which must be greater than zero). A bid is a `Bid` resource carrying its `lot_id`, the `bidder_customer_id`, and the `amount_cents`. To be accepted, a bid must be strictly greater than the current `high_bid_cents`; meeting or exceeding the reserve is **not** required to bid. The lot must be `LIVE` and the current clock must be within the window — at or after `opens_at` and strictly before `closes_at`. A bid that is not strictly greater than the current high, or that arrives when the lot is not live or the clock is outside the window, is rejected with `ERR_BID_TOO_LOW` (HTTP 409). When a bid is accepted and its amount strictly exceeds the current high, the lot's `high_bid_cents` and `high_bidder_customer_id` are updated to that bid.

An auction clerk closes a live lot once the current clock is at or after `closes_at`, freezing bidding. If at close the `high_bid_cents` is at or above the `reserve_price_cents`, the lot moves `LIVE → CLOSED_MET`; if the high bid is below the reserve, or there were no bids at all, it moves `LIVE → CLOSED_NO_SALE`.

Settlement resolves a closed lot and carries the `expected_unit_version` optimistic-concurrency guard described in Section 2.7. Settling a `CLOSED_MET` lot moves it `CLOSED_MET → SETTLED` (terminal): it creates an `AUCTION_SALE` deal in `FUNDED` status for the high bidder at the `high_bid_cents` (with no trade-in, so `trade_allowance_cents` is 0, and with `tax_cents` and `amount_due_cents` computed on `high_bid_cents` exactly as for a funded `SALE`/`AUCTION_SALE` per Section 3.4 — `tax_cents` is 0 for a tax-exempt high bidder, otherwise `high_bid_cents` times 0.0725 rounded half up, and `amount_due_cents` is `high_bid_cents` plus `tax_cents`), moves the unit `AUCTION_LISTED → AUCTION_SOLD`, pays off any `ACTIVE` or `CURTAILMENT_DUE` floor-plan note on the unit as a cascade, sets the lot's `winning_deal_id` to the created deal, and increments the unit's `version` by one. Settling a `CLOSED_NO_SALE` lot moves it `CLOSED_NO_SALE → SETTLED` with no deal created, releasing the unit `AUCTION_LISTED → AVAILABLE` as a cascade and incrementing the unit's `version` by one. Settlement is permitted only from `CLOSED_MET` or `CLOSED_NO_SALE`.

### 3.6. The Service Shop: Work Orders, Parts, and Flat-Rate Labor

The service shop tracks repairs as a `WorkOrder`. A service advisor (or admin) opens a work order by supplying the `unit_id` being serviced, the bill-to `customer_id`, a free-text `complaint`, an hourly door `labor_rate_cents` (which must be greater than zero), the published `flat_rate_hours` book time for the job (which must be zero or greater), and an optional `warranty_claim_id` that, when set, directs labor and parts to a warranty, PIP, or recall claim rather than to the customer (`null` for customer-pay). A work order also accepts an `actual_hours` field — the technician's clocked hours — which defaults to 0, must be zero or greater, and is supplied when the job is billed. The work order carries the computed fields `labor_charge_cents`, `parts_charge_cents` (the sum of its part lines' extended amounts), and `total_charge_cents` (the sum of labor and parts charges). A new work order is `OPEN`.

**Flat-rate labor.** Labor is billed dual-variant: an estimate while the job is in flight, and the actual at close. The base is the `labor_rate_cents`. The estimate charge is `flat_rate_hours` multiplied by the base, rounded half up. The final charge is `actual_hours` multiplied by the base, rounded half up. The flat-rate estimate is first written into `labor_charge_cents` when the order is started (`OPEN → IN_PROGRESS`); a freshly opened order that has not yet been started carries `labor_charge_cents` of 0 (along with `parts_charge_cents` and `total_charge_cents`, which reflect only any part lines already added). Once started and while the work order is `IN_PROGRESS` (or `AWAITING_PARTS`), `labor_charge_cents` reflects the flat-rate estimate computed from the book `flat_rate_hours` and ignores `actual_hours`. Once the work order is `CLOSED`, `labor_charge_cents` is recomputed from the technician's `actual_hours`; a job that runs slower than book (actual greater than flat) bills more, and an efficient job (actual below flat) bills less.

A service advisor starts a work order, moving it `OPEN → IN_PROGRESS`, which assigns a technician and sets `labor_charge_cents` to the flat-rate estimate. Parts are added to a work order as `PartLine` records (see below) at any point before close. When a needed part is short, the advisor holds the order for parts, moving it `IN_PROGRESS → AWAITING_PARTS`; this hold is permitted only when at least one part line on the order references a part whose available quantity (its `on_hand_qty` minus its `reserved_qty`) is less than that line's `quantity`. When parts arrive, the advisor resumes the order, moving it `AWAITING_PARTS → IN_PROGRESS` (the order may cycle between these two states). The advisor closes a work order, moving it `IN_PROGRESS → CLOSED` (terminal); closing requires the order to be `IN_PROGRESS` and `actual_hours` to be greater than zero, and is the point at which the technician's `actual_hours` is supplied. At close the `labor_charge_cents` is recomputed from `actual_hours`, the consumed parts are decremented from each part's `on_hand_qty` and their reservations released, and `total_charge_cents` is frozen. Closing also enforces parts availability: if any part line's `quantity` exceeds the part's available quantity (`on_hand_qty` minus `reserved_qty`) at close, the close is rejected with `ERR_PARTS_SHORTAGE` (HTTP 409). The same error guards the hold-for-parts transition when its shortfall preconditions are not met. Finally, a service advisor may void an open work order, moving it `OPEN → VOID` (terminal); voiding releases any reserved parts back to availability and posts no charges.

**Parts and precision-ag inventory.** The catalog holds `Part` records, each with a `sku` (unique across all parts), a `description`, a `category` of `MECHANICAL`, `FILTER`, `PRECISION_AG`, or `TELEMATICS`, a `unit_price_cents` current sell price (greater than zero), and an `on_hand_qty` stock count (zero or greater, defaulting to 0). A part also carries a computed `reserved_qty`: the sum of the `quantity` of every part line that references the part and whose owning work order is `OPEN`, `IN_PROGRESS`, or `AWAITING_PARTS`. The available quantity of a part is its `on_hand_qty` minus its `reserved_qty`. Creating a part with a `sku` that collides with an existing part is rejected with `ERR_DUPLICATE_KEY`.

A `PartLine` attaches a part to a work order. It is created with the owning `work_order_id`, the `part_id` consumed, and a `quantity` (which must be greater than zero). On creation the line snapshots the part's current price into `unit_price_cents` and sets `extended_cents` to the `quantity` multiplied by that snapshot price; adding the line recomputes the owning work order's `parts_charge_cents` and the part's `reserved_qty`.

### 3.7. Warranty, PIP, and Recall Claims

Reimbursement for service work performed under warranty or a manufacturer campaign is filed as a `WarrantyClaim`. A service advisor (or admin) drafts a claim by supplying the `unit_id` the claim covers, a `claim_type` of `WARRANTY`, `PIP`, or `RECALL` (where `PIP` is a Product Improvement Program and `RECALL` is a safety campaign), and an optional `campaign_code` for PIP and recall campaigns (`null` for a plain warranty). The claim carries computed amounts `claimed_cents` and `approved_cents`, both starting at 0, and begins `DRAFT`. Work orders are routed to a claim by setting their `warranty_claim_id`.

A service advisor submits a draft claim, moving it `DRAFT → SUBMITTED`; submission requires at least one `CLOSED` work order to reference the claim, and it freezes `claimed_cents` to the sum of the `total_charge_cents` of every `CLOSED` work order linked to the claim.

A `DealerAdmin` adjudicates a submitted claim by supplying a `decision`. A decision of `FULL` moves the claim `SUBMITTED → APPROVED`; a decision of `PARTIAL` moves it `SUBMITTED → PARTIAL`; a decision of `DENY` moves it `SUBMITTED → DENIED`. There is one absolute safety rule: a `RECALL` claim is a safety campaign that must be honored and can never be denied, so a `DENY` decision on a claim whose `claim_type` is `RECALL` is rejected with `ERR_RECALL_CANNOT_DENY` (HTTP 409).

**Reimbursement amount.** Adjudication sets `approved_cents` from the frozen `claimed_cents` in a dual-variant manner. The full reimbursement depends on claim type: a `PIP` or `RECALL` claim is manufacturer-funded and reimburses 100 percent of `claimed_cents`, so its full amount equals `claimed_cents`; a plain `WARRANTY` claim is subject to a labor cap and its full amount is `claimed_cents` multiplied by 0.90 (90 percent), rounded half up. From that full amount the decision selects the approved figure: a `FULL` decision approves the full amount; a `PARTIAL` decision approves the full amount multiplied by the partial factor of 0.50, rounded half up; a `DENY` decision approves 0.

A `DealerAdmin` pays an approved or partial claim, moving it `APPROVED → PAID` or `PARTIAL → PAID` (terminal) and disbursing the reimbursement. `PAID` and `DENIED` are the terminal states of a claim.

### 3.8. Seasonal Whole-Goods Pre-Orders

Equipment that is not yet in inventory is pre-sold through a `WholeGoodsOrder`. A sales rep (or admin) places an order by supplying the ordering `customer_id`, the `model_code` ordered, a `season_program` of `EARLY_ORDER`, `IN_SEASON`, or `LATE` (which drives the discount band), a `quantity` of units (greater than zero), and a per-unit `unit_msrp_cents` (greater than zero). The order carries the computed fields `deposit_cents`, `net_price_cents`, and `fulfilled_qty` (units fulfilled so far, starting at 0). Placing an order computes `net_price_cents` and starts the order `PLACED`.

**Deposit and net price.** The per-unit discount is taken by season program — `EARLY_ORDER` is 0.12 (12%), `IN_SEASON` is 0.05 (5%), and `LATE` is 0.00 (no discount). The `net_price_cents` is the `unit_msrp_cents` multiplied by one minus the discount fraction, rounded half up — this per-unit net price is rounded first. The order total is the rounded `net_price_cents` multiplied by `quantity`. The percentage deposit is the order total multiplied by 0.10 (10%), rounded half up. The floor deposit is 50,000 cents per unit (that is, a five-hundred-dollar minimum per unit) multiplied by `quantity`. The required `deposit_cents` is the larger of the percentage deposit and the floor deposit. The order is pinned: round the per-unit net price first, multiply by quantity, then take the maximum of the percentage and floor deposits.

A sales rep confirms a placed order, moving it `PLACED → CONFIRMED`, which computes `deposit_cents`, locks the order into the season program, and commits the deposit; confirmation is permitted only when the order is `PLACED`. The order is then fulfilled one unit at a time by allocation. Allocating supplies a `unit_id` and requires an `AVAILABLE` unit whose `model_code` matches the order; if no such unit exists the allocation is rejected with `ERR_NO_MATCHING_UNIT` (HTTP 409). Each allocation reserves the chosen unit, moving it `AVAILABLE → RESERVED`, and increments `fulfilled_qty` by one. When fulfillment after an allocation is still short of `quantity`, the order moves to `PARTIAL_FULFILLED` (from `CONFIRMED` on the first short allocation, or it remains in `PARTIAL_FULFILLED` on subsequent ones); when an allocation brings `fulfilled_qty` up to `quantity`, the order moves to `FULFILLED` (terminal) — either `PARTIAL_FULFILLED → FULFILLED`, or directly `CONFIRMED → FULFILLED` when the order quantity is exactly 1 and is filled in a single step. Allocation is permitted only while the order is `CONFIRMED` or `PARTIAL_FULFILLED`.

A sales rep may cancel an order while it is `PLACED` or `CONFIRMED`, moving it to `CANCELLED` (terminal); cancellation releases any reserved units back to `AVAILABLE` and forfeits the deposit per program rules. `FULFILLED` and `CANCELLED` are the terminal states of an order.

### 3.9. Validation Ordering and Request Hygiene

Across every endpoint, validations are applied in a fixed priority order so that the most fundamental failures surface first and a later check never masks an earlier one. Authentication is checked first: missing or unknown-role headers yield `ERR_UNAUTHENTICATED`. Authorization is checked second: a role not permitted for the operation yields `ERR_FORBIDDEN`. Existence is checked third: any path- or body-referenced resource that does not exist yields `ERR_NOT_FOUND`, with the referenced identifiers resolved left to right. Request well-formedness is checked fourth: required input fields must be present and well-typed, every enum value must lie within its declared set, and numeric constraints (such as a `quantity` greater than zero or a `sale_price_cents` greater than zero) must hold — a violation yields `ERR_INVALID_REQUEST` (HTTP 422). Uniqueness is checked fifth, where applicable: a duplicate `stock_number`, `serial_number`, or `sku` yields `ERR_DUPLICATE_KEY`. State legality is checked sixth: a transition requested from a state in which it is not defined yields `ERR_INVALID_STATE`. The optimistic-concurrency check is seventh on funding and settlement: a stale `expected_unit_version` yields `ERR_STALE_UNIT_VERSION`. Only after these structural gates pass does the system evaluate the deeper business-referential, safety, temporal, and fiscal rules described throughout Section 3 — unit reservability, trade-attach eligibility, recall protection, auction windows, bid minimums, curtailment sufficiency, parts availability, and whole-goods unit matching — each with its own dedicated error as named above.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code; operations that modify an existing resource — including every state-transition action — return a `200 OK` status code. Every endpoint is subject to the authentication, authorization, and validation rules of Sections 2 and 3. The request and response payloads are not restated here; reconstruct them from the workflow narratives of Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/units` | Create an inventory unit | DealerAdmin, SalesRep |
| GET | `/units` | List units (filter by status, condition, model_code, acquired_from_tradein_id) | DealerAdmin, SalesRep, ServiceAdvisor, PartsClerk, FinanceManager, AuctionClerk |
| GET | `/units/{id}` | Get a unit | DealerAdmin, SalesRep, ServiceAdvisor, PartsClerk, FinanceManager, AuctionClerk |
| POST | `/units/{id}/recondition` | Return a repossessed unit to inventory | DealerAdmin |
| POST | `/units/{id}/retire` | Retire an available, non-floor-planned unit | DealerAdmin |
| POST | `/floor-plan-notes` | Draft a floor-plan note on a unit | FinanceManager, DealerAdmin |
| GET | `/floor-plan-notes` | List floor-plan notes (filter by unit_id, status) | FinanceManager, DealerAdmin |
| GET | `/floor-plan-notes/{id}` | Get a floor-plan note (with accrued interest) | FinanceManager, DealerAdmin |
| POST | `/floor-plan-notes/{id}/activate` | Activate a draft note | FinanceManager, DealerAdmin |
| POST | `/floor-plan-notes/{id}/recompute` | Recompute accrual & curtailment stage to current clock | FinanceManager, DealerAdmin |
| POST | `/floor-plan-notes/{id}/curtail` | Make a curtailment payment | FinanceManager, DealerAdmin |
| POST | `/floor-plan-notes/{id}/default` | Flag a curtailment-due note as defaulted | DealerAdmin |
| POST | `/customers` | Create a customer | DealerAdmin, SalesRep, FinanceManager |
| GET | `/customers/{id}` | Get a customer | DealerAdmin, SalesRep, FinanceManager, ServiceAdvisor, AuctionClerk |
| POST | `/trade-ins` | Appraise a trade-in | SalesRep, DealerAdmin |
| GET | `/trade-ins` | List trade-ins (filter by customer_id, minted_unit_id, status) | SalesRep, DealerAdmin, FinanceManager |
| GET | `/trade-ins/{id}` | Get a trade-in | SalesRep, DealerAdmin, FinanceManager |
| POST | `/trade-ins/{id}/offer` | Offer the appraised trade to the customer | SalesRep, DealerAdmin |
| POST | `/trade-ins/{id}/decline` | Decline an offered trade | SalesRep, DealerAdmin |
| POST | `/deals` | Quote a deal (reserves the unit) | SalesRep, FinanceManager |
| GET | `/deals` | List deals (filter by unit_id, customer_id, tradein_id, status) | SalesRep, FinanceManager, DealerAdmin, AuctionClerk |
| GET | `/deals/{id}` | Get a deal | SalesRep, FinanceManager, DealerAdmin, AuctionClerk |
| POST | `/deals/{id}/approve` | Approve a quoted deal (credit decision) | FinanceManager |
| POST | `/deals/{id}/fund` | Fund an approved deal (sells/leases the unit, runs cascades) | FinanceManager |
| POST | `/deals/{id}/deliver` | Deliver a funded deal | SalesRep, FinanceManager |
| POST | `/deals/{id}/unwind` | Unwind a funded SALE (repossess) | FinanceManager |
| POST | `/auction-lots` | Consign a used unit to auction | AuctionClerk, DealerAdmin |
| GET | `/auction-lots` | List auction lots (filter by unit_id, high_bidder_customer_id, winning_deal_id, status) | AuctionClerk, DealerAdmin, SalesRep, FinanceManager |
| GET | `/auction-lots/{id}` | Get an auction lot | AuctionClerk, DealerAdmin, SalesRep, FinanceManager |
| POST | `/auction-lots/{id}/open` | Open bidding on a lot | AuctionClerk |
| POST | `/auction-lots/{id}/bids` | Place a bid | AuctionClerk, SalesRep |
| GET | `/auction-lots/{id}/bids` | List bids on a lot | AuctionClerk, DealerAdmin |
| GET | `/bids` | List bids (filter by lot_id, bidder_customer_id) | AuctionClerk, DealerAdmin |
| GET | `/bids/{id}` | Get a single bid | AuctionClerk, DealerAdmin |
| POST | `/auction-lots/{id}/close` | Close bidding (decides CLOSED_MET vs CLOSED_NO_SALE) | AuctionClerk |
| POST | `/auction-lots/{id}/settle` | Settle a closed lot (create AUCTION_SALE deal or release unit) | AuctionClerk |
| POST | `/parts` | Create a catalog part | PartsClerk, DealerAdmin |
| GET | `/parts` | List parts (filter by category, sku) | PartsClerk, DealerAdmin, ServiceAdvisor |
| GET | `/parts/{id}` | Get a part (with reserved_qty) | PartsClerk, DealerAdmin, ServiceAdvisor |
| POST | `/work-orders` | Open a work order | ServiceAdvisor, DealerAdmin |
| GET | `/work-orders` | List work orders (filter by unit_id, customer_id, warranty_claim_id, status) | ServiceAdvisor, DealerAdmin, FinanceManager |
| GET | `/work-orders/{id}` | Get a work order | ServiceAdvisor, DealerAdmin, FinanceManager |
| POST | `/work-orders/{id}/part-lines` | Add a part line to a work order | ServiceAdvisor, PartsClerk |
| GET | `/work-orders/{id}/part-lines` | List part lines on a work order | ServiceAdvisor, PartsClerk, DealerAdmin |
| GET | `/part-lines` | List part lines (filter by work_order_id, part_id) | ServiceAdvisor, PartsClerk, DealerAdmin |
| GET | `/part-lines/{id}` | Get a single part line | ServiceAdvisor, PartsClerk, DealerAdmin |
| POST | `/work-orders/{id}/start` | Start work (estimate labor) | ServiceAdvisor |
| POST | `/work-orders/{id}/hold-for-parts` | Hold a work order awaiting parts | ServiceAdvisor |
| POST | `/work-orders/{id}/resume` | Resume a held work order | ServiceAdvisor |
| POST | `/work-orders/{id}/close` | Close a work order (bill actual hours; decrement parts) | ServiceAdvisor |
| POST | `/work-orders/{id}/void` | Void an open work order | ServiceAdvisor |
| POST | `/warranty-claims` | Draft a warranty/PIP/recall claim | ServiceAdvisor, DealerAdmin |
| GET | `/warranty-claims` | List warranty claims (filter by unit_id, claim_type, status) | ServiceAdvisor, DealerAdmin, FinanceManager |
| GET | `/warranty-claims/{id}` | Get a warranty claim | ServiceAdvisor, DealerAdmin, FinanceManager |
| POST | `/warranty-claims/{id}/submit` | Submit a claim (freezes claimed_cents) | ServiceAdvisor, DealerAdmin |
| POST | `/warranty-claims/{id}/adjudicate` | Adjudicate a submitted claim | DealerAdmin |
| POST | `/warranty-claims/{id}/pay` | Pay an approved/partial claim | DealerAdmin |
| POST | `/whole-goods-orders` | Place a seasonal whole-goods order | SalesRep, DealerAdmin |
| GET | `/whole-goods-orders` | List whole-goods orders (filter by customer_id, status) | SalesRep, DealerAdmin |
| GET | `/whole-goods-orders/{id}` | Get a whole-goods order | SalesRep, DealerAdmin |
| POST | `/whole-goods-orders/{id}/confirm` | Confirm an order (computes deposit) | SalesRep, DealerAdmin |
| POST | `/whole-goods-orders/{id}/allocate` | Allocate one matching available unit to the order | SalesRep, DealerAdmin |
| POST | `/whole-goods-orders/{id}/cancel` | Cancel an order | SalesRep, DealerAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock (triggers floor-plan recompute) | DealerAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_KEY` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_UNIT_VERSION` | 412 |
| `ERR_UNIT_NOT_RESERVABLE` | 409 |
| `ERR_TRADEIN_NOT_OFFERED` | 409 |
| `ERR_RECALL_CANNOT_DENY` | 409 |
| `ERR_AUCTION_WINDOW` | 409 |
| `ERR_BID_TOO_LOW` | 409 |
| `ERR_CURTAILMENT_SHORT` | 409 |
| `ERR_PARTS_SHORTAGE` | 409 |
| `ERR_NO_MATCHING_UNIT` | 409 |
