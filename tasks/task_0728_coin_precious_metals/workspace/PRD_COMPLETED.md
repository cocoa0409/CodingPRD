# Coin & Precious-Metals Dealer API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a full-service coin and precious-metals dealership. The business buys bullion and numismatic coins from the public, sells inventory to retail and retirement-account (IRA) customers, runs layaway and price-lock programs, brokers consignment items through timed auction sessions, and hedges its metal inventory against spot-price movement. Every price the dealer quotes is derived from a live, per-metal spot rate, so the pricing engine sits at the center of the system: a buy payout, a retail ask, and a locked layaway price are all computed from the same melt-value foundation, differentiated only by spread direction and the presence of a collectible premium.

Layered on top of pricing is a compliance and audit obligation. Large cash purchases from the public trip a federal reporting threshold (1099-B / ID verification), IRA allocations may only flow into approved custodial accounts, and consignment proceeds must be split precisely between the consignor and the house. The service therefore enforces a strict separation of duties across four operator roles, an immutable audit trail through monotonic entity versioning, and optimistic concurrency control on the two write paths where a stale client view could corrupt a running balance.

The remainder of this document defines the global contract (authentication, response envelope, pagination, precision, and concurrency), the business logic and lifecycle of each entity, the complete endpoint surface, and the error catalogue. All monetary amounts are integer cents; all metal weights are troy ounces.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When both headers are present but the named role is not permitted to invoke the target endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows:

- **`Trader`** — manages spot rates, catalog products, physical inventory lots, and inventory hedge positions.
- **`SalesAgent`** — runs the sales floor: sell orders, buy orders, layaways, consignments, appraisers, appraisal appointments, and auction sessions.
- **`ComplianceOfficer`** — owns customer KYC, the IRA account lifecycle, reportable-buy approval and rejection, and consignment settlement.
- **`Customer`** — a registered customer acting on their own layaways.

Three of these roles carry an **opaque** identity. When `X-User-Role` is `Trader`, `SalesAgent`, or `ComplianceOfficer`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`. The `Customer` role, by contrast, is **entity-backed**: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record. Ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`. Specifically, when a `Customer` applies a deposit to a layaway or cancels a layaway, the layaway's `customer_id` must equal the caller's `X-User-ID`; otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. Results are always returned in ascending `created_at` order, with records sharing the same `created_at` ordered by their server-assigned creation sequence (earliest first). For every list response, the `meta` object carries `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by exactly one on every mutation that changes the resource. The `version` field is the anchor for optimistic concurrency (see §2.6) and for the stale-data serialization points described throughout §3.

### 2.5. Monetary Precision and Rounding

All monetary values are stored and returned as integer cents. Whenever a calculation produces a fractional cent, it is resolved with **round half up** (a value exactly halfway between two integers rounds to the larger magnitude). Each calculation in §3 states the precise point at which rounding is applied; unless a calculation says otherwise, rounding is applied exactly once, after all multiplicative factors have been combined. Metal weights (`weight_troy_oz`, `short_troy_oz`) and fractional rates (`purity`, `min_sell_spread_pct`, `buy_spread_pct`, `commission_pct`, `buyer_premium_pct`) are real numbers and are not rounded to cents; only the resulting money amounts are.

### 2.6. Optimistic Concurrency Control

Two write paths are guarded by optimistic concurrency control (OCC), because both mutate a running balance that a stale client could silently corrupt.

Applying a deposit to a layaway requires the request body to carry `expected_layaway_version`, a non-optional field holding the `version` of the `Layaway` the client last observed. If that value does not equal the layaway's current `version` — for example because a prior deposit or a status change advanced the version since the client last read the record — the deposit is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from applying a deposit against a stale `amount_paid_cents` view.

Recording a sale against a consignment requires the request body to carry `expected_consignment_version`, a non-optional field holding the `version` of the `Consignment` the client last observed. If that value does not equal the consignment's current `version` — for example because another actor already recorded the sale or returned the item, advancing the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than layaway deposit and consignment record-sale do not accept a version field and are not subject to this check.

### 2.7. Request Validation and Error Precedence

Requests are validated in a fixed order, and the first failing check determines the error returned. The ordering is: (1) authentication — both headers present, else `ERR_UNAUTHENTICATED` (401); (2) authorization — the role may invoke the endpoint, else `ERR_UNAUTHORIZED` (403); (3) existence — every resource `id` in the path and every foreign key in the body resolves to an existing entity, validated left to right with path ids checked before body foreign keys, else `ERR_NOT_FOUND` (404); (4) ownership — for the entity-backed `Customer` role acting on a layaway deposit or cancel, `X-User-ID` must equal the resource's `customer_id`, else `ERR_NOT_RESOURCE_OWNER` (403); (5) state — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409). Business-rule checks specific to each endpoint follow these in the priority documented alongside each workflow in §3. The lowest-priority check, applied last on every mutating request, verifies that required body fields are present and well-typed, enum fields fall within their declared domain, quantities are positive, and time intervals have an end strictly after their start; a violation yields `ERR_INVALID_REQUEST` (HTTP 400).

Because these checks are strictly ordered, a request that fails several validations surfaces only the highest-priority failure. For instance, on a layaway deposit, an authorization failure masks an ownership failure, an ownership failure masks a state failure, and the OCC stale-version check and the overpayment check are only reached once state has been confirmed valid.

### 2.8. Hierarchical Consistency and Cascade Semantics

Many operations in this system mutate more than one entity in a single logical step. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this applies equally to entities touched as secondary effects of another entity's transition. For example, settling a sell order not only advances the order but also depletes inventory lots and may advance an IRA account's allocated balance — each affected entity's `version` moves independently. The specific cascades (inventory depletion, reservation release, store-credit crediting, lifetime-payout accumulation, IRA allocation) are described in the workflow subsections of §3, and every downstream write is part of the same atomic operation as the triggering transition.

### 2.9. Nested Resource Access and Referential Integrity

All collections are top-level under the `/api` mount; there are no nested resource paths. Relationships between entities are expressed purely through foreign-key fields carried in request bodies (for example, a sell order references its `customer_id` and `product_id`). Every such foreign key must resolve to an existing entity at request time, checked left to right after any path id, and an unresolved reference yields `ERR_NOT_FOUND` (HTTP 404).

## 3. Business Logic & Workflows

### 3.1. Spot Rates and the Melt-Value Pricing Foundation

All pricing begins with the live spot market. A `Trader` records one spot rate per metal, supplying the `metal` (one of `GOLD`, `SILVER`, `PLATINUM`, or `PALLADIUM`) and its `price_per_troy_oz_cents`, the current spot price per troy ounce expressed in integer cents and required to be at least 1. Exactly one live spot-rate row exists per metal — the `metal` value is unique across spot rates, and an attempt to create a second spot rate for a metal that already has one is rejected with `ERR_INVALID_REQUEST` (HTTP 400). When the market moves, the `Trader` updates a metal's `price_per_troy_oz_cents`; such an update affects only pricing computed after the change, leaving already-locked prices on existing orders and layaways untouched. Any of the four roles may read a spot rate.

The catalog is composed of products, each created by a `Trader`. A product carries a `sku` (a human catalog identifier, unique across products, where an attempt to create a product whose `sku` duplicates an existing product is rejected with `ERR_INVALID_REQUEST`, HTTP 400), a `product_type` of either `BULLION` or `NUMISMATIC`, the `metal` whose spot rate governs its value, a fine-metal `weight_troy_oz` per unit (required to be greater than zero; the up-to-four-decimal-place precision is a modeling convention that the server does not separately enforce beyond the positivity check), and a `purity` fineness fraction that is greater than zero and at most 1. Each product also fixes its own spread parameters: `min_sell_spread_pct`, the floor on the dealer's sell markup expressed as a fraction at least 0 and less than 1, and `buy_spread_pct`, the discount below value the dealer pays when buying, likewise at least 0 and less than 1. A product may carry a `numismatic_premium_cents`, the per-unit collectible premium over metal value, which is a non-negative integer defaulting to 0. A `NUMISMATIC` product may carry a positive `numismatic_premium_cents`, but a `BULLION` product must be created with `numismatic_premium_cents` equal to 0; an attempt to create a `BULLION` product with a premium above 0 is rejected with `ERR_BULLION_PREMIUM_FORBIDDEN` (HTTP 422). Finally, `ira_eligible` (a boolean defaulting to false) marks whether the product may be sold into an IRA and shipped to a custodian.

The foundational quantity for every quote is the **unit melt value**. To compute it for a product, the system takes the single live spot rate for the product's `metal`, reads its `price_per_troy_oz_cents`, multiplies that price by the product's `weight_troy_oz` and by its `purity`, and rounds the result half up to whole cents. Rounding is applied exactly once, after all three factors have been multiplied together. This unit melt value in cents is the melt basis on which both the sell price and the buy payout are built. Any operation that must price a product or hedge a metal — placing a sell order, placing a buy order, opening a layaway, or opening or closing a hedge position — requires a live spot rate to exist for the relevant `metal`; if none has been recorded, the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

The **unit sell price** is the dealer's per-unit ask. Starting from the unit melt value, the system forms a base value: for a `NUMISMATIC` product the base is the unit melt value plus the product's `numismatic_premium_cents`; for a `BULLION` product the collectible premium is treated as 0 regardless of any stored field, so the base equals the unit melt value alone. The system then multiplies the base by one plus the product's `min_sell_spread_pct` and rounds the result half up to whole cents, applying that single rounding after the spread has been applied. The two product types thus diverge in exactly one respect: for a numismatic item the collectible premium is added to melt *before* the sell spread is applied, so the spread compounds over the premium as well as the metal. This unit sell price is what locks onto a sell order at placement and onto a layaway at creation.

### 3.2. Physical Inventory, Cost Basis, and FIFO Depletion

A `Trader` records physical stock as inventory lots. Creating a lot supplies its `product_id`, the `total_qty` acquired (at least 1, and fixed forever after creation), and the `acquisition_unit_cost_cents`, the per-unit cost basis at acquisition (a non-negative integer). On creation the lot's `available_qty` is initialized to `total_qty`, while `reserved_qty` and `sold_qty` both start at 0, and the lot's `status` is `AVAILABLE`. These three quantity buckets obey a standing invariant: `available_qty` plus `reserved_qty` plus `sold_qty` always equals `total_qty`. Units move between buckets — never in or out of the lot — as layaways reserve stock and orders deliver it. A lot's `status` is `AVAILABLE` while `available_qty` is greater than 0, and transitions to `DEPLETED` once `available_qty` reaches 0 and `sold_qty` equals `total_qty`. Traders, sales agents, and compliance officers may read individual lots or list them, optionally narrowing a listing by `product_id`.

Two cost-of-goods figures are computed for every sale, and they intentionally diverge. At the moment a sell order is placed, the system estimates a **provisional cost of goods** using a quantity-weighted average across all of the product's currently available lots. It gathers every inventory lot for the order's product whose `available_qty` is greater than 0, sums each lot's `acquisition_unit_cost_cents` multiplied by that lot's `available_qty`, divides that sum by the total available quantity across those lots to obtain a weighted-average unit cost, rounds that unit cost half up to whole cents, and then multiplies the rounded unit cost by the order's `quantity`. The rounding is applied once to the weighted-average unit cost before the multiplication. Placing a sell order does not require any inventory to exist; when the product has no available lots at placement the provisional cost of goods is 0.

At settlement, the system computes the **final cost of goods** by consuming inventory strictly first-in, first-out. It walks the product's lots whose `available_qty` is greater than 0 in ascending `created_at` order (oldest first); when two lots share the same `created_at`, the lot with the smaller `available_qty` is consumed first as a deterministic tie-break, and if `created_at` and `available_qty` are both equal the earlier-created lot (by server creation sequence) is consumed first; lot `id` is never used to break ties. Beginning with the full order `quantity` still to fill, from each lot in turn it takes the smaller of the remaining quantity and that lot's `available_qty`, adds the units taken multiplied by that lot's `acquisition_unit_cost_cents` to a running total, reduces the remaining quantity by the units taken, and stops as soon as the remaining quantity reaches 0. The final cost of goods is the exact sum of those per-lot contributions, with no intermediate rounding. Because the provisional figure weights *all* available lots equally by quantity while the final figure consumes the oldest lots first, when lots for the same product carry different `acquisition_unit_cost_cents` the provisional and final costs will differ for identical order inputs — this divergence is expected and is the whole point of tracking both.

### 3.3. Selling to Customers and Retirement Accounts

A `SalesAgent` places a sell order on behalf of a customer, supplying the `customer_id`, the `product_id`, the `quantity` being purchased (at least 1), and optionally an `ira_account_id` when the order is an allocation into a retirement account (otherwise this field is null). At placement the system locks the `quoted_unit_price_cents` from the unit sell price described in §3.1, sets `total_price_cents` to the quoted unit price multiplied by the `quantity`, records the `provisional_cogs_cents` from the provisional cost-of-goods estimate, leaves `final_cogs_cents` and `realized_margin_cents` null, and sets the order `status` to `PLACED`.

Retirement-account allocations carry extra guards evaluated at placement. If an `ira_account_id` is supplied, the referenced IRA account's `status` must be `ACTIVE`, or the order is rejected with `ERR_IRA_NOT_ACTIVE` (HTTP 422); and the referenced product's `ira_eligible` must be true, or the order is rejected with `ERR_PRODUCT_NOT_IRA_ELIGIBLE` (HTTP 422). The account-active check is applied before the product-eligibility check, so when both fail the order is rejected with `ERR_IRA_NOT_ACTIVE`. Both IRA guards are evaluated before the `quantity` field is validated for well-formedness. Of these two IRA guards, the account-active check is the one re-applied at settlement as well (see below), whereas the product-eligibility check is enforced only at placement.

Settling a placed sell order advances it from `PLACED` to `SETTLED` and is where inventory actually moves. Settlement is permitted only when the order is currently `PLACED`; otherwise the state guard rejects it with `ERR_INVALID_STATE` (HTTP 409). The aggregate `available_qty` across the product's `AVAILABLE` lots must be at least the order `quantity` — if the product has no available inventory or too little, settlement fails with `ERR_INSUFFICIENT_INVENTORY` (HTTP 422). When the order is an IRA allocation, the referenced IRA account's `status` must still be `ACTIVE` at settlement, again guarded by `ERR_IRA_NOT_ACTIVE`; this IRA-active check is applied after the inventory-sufficiency check, so when both the inventory is insufficient and the IRA is no longer active the settlement fails with `ERR_INSUFFICIENT_INVENTORY`. Once these checks pass, the system computes `final_cogs_cents` by the FIFO consumption of §3.2, decrements `available_qty` and increments `sold_qty` across the consumed lots in FIFO order, and any consumed lot whose `available_qty` reaches 0 with `sold_qty` equal to `total_qty` transitions to `DEPLETED`. The system then sets `realized_margin_cents` to `total_price_cents` minus `final_cogs_cents`. If the order carries an `ira_account_id`, the referenced IRA account's `allocated_value_cents` is increased by the order's `total_price_cents`. Finally the order `status` becomes `SETTLED`. A placed sell order may instead be cancelled by a `SalesAgent`, which is allowed only from `PLACED` and simply sets the `status` to `CANCELLED`; because a bare sell order reserves no inventory, no release is needed.

IRA accounts are opened and governed by a `ComplianceOfficer`. Opening an account records the beneficial owner's `customer_id`, the `custodian_name` holding the metal, and the `custodian_account_ref` on the custodian's side; the account begins with `status` `PENDING` and `allocated_value_cents` initialized to 0. Approving a pending account moves it from `PENDING` to `ACTIVE`, but only when the owning customer's `id_document_on_file` is true; if the account is `PENDING` but the owning customer's `id_document_on_file` is not true, approval is rejected with `ERR_ID_REQUIRED_FOR_REPORTABLE` (HTTP 422). This state guard is applied before the ID check, so an account that is not `PENDING` yields `ERR_INVALID_STATE` regardless of the ID flag. Only `ACTIVE` accounts may receive allocations. An active account may later be closed, moving its `status` from `ACTIVE` to `CLOSED`. Both the approve and close transitions require the account to be in the expected starting state (`PENDING` and `ACTIVE` respectively), enforced by the `ERR_INVALID_STATE` guard.

### 3.4. Buying from the Public and 1099-B Reporting

When the dealer buys metal from the public, a `SalesAgent` places a buy order naming the `customer_id` of the seller, the `product_id` being acquired, and the `quantity` (at least 1). At placement the system computes the **unit buy payout**: from the same base value used for selling — the unit melt value, plus the product's `numismatic_premium_cents` only when the `product_type` is `NUMISMATIC` — it multiplies the base by one minus the product's `buy_spread_pct` and rounds half up to whole cents, applying that single rounding after the buy spread. This becomes the `quoted_unit_payout_cents`; the `total_payout_cents` is that unit payout multiplied by the `quantity`. The order's `reportable` flag is then locked: it is true when `total_payout_cents` is at least the reporting threshold of $10,000.00 (that is, 1,000,000 cents), and false otherwise. The order's `status` starts at `PLACED`.

Reportable buys trigger the compliance obligations that give this domain its audit character. A reportable buy order cannot be settled unless two conditions both hold, and each has its own error. First, the selling customer must have `id_document_on_file` set to true; if not, settlement is rejected with `ERR_ID_REQUIRED_FOR_REPORTABLE` (HTTP 422). Second, a `ComplianceOfficer` must have separately approved the reportable buy, setting an approval flag on the order; without that approval, settlement is rejected with `ERR_REPORTABLE_NOT_APPROVED` (HTTP 422). This approval flag is an internal server-side attribute of the order and is not surfaced in any response body. The approve action itself simply records the approval on the referenced buy order and returns it; it applies no state or reportability guard, so it succeeds on any existing buy order regardless of the order's current status or whether the order is actually reportable, and bumps the order's `version`. A non-reportable buy carries neither obligation.

Settling a placed buy order advances it from `PLACED` to `SETTLED` and is the point at which the dealer disburses payment and takes stock in. Settlement requires the order to be `PLACED`, and — for reportable orders — the ID and approval conditions above. On success, the system always creates a brand-new inventory lot for the product (it never augments an existing lot) with `total_qty` equal to the buy order `quantity`, `available_qty` equal to that same `quantity`, `reserved_qty` and `sold_qty` both 0, `status` `AVAILABLE`, and `acquisition_unit_cost_cents` equal to the order's `quoted_unit_payout_cents`, making that stock immediately available for sale; increments the selling customer's `lifetime_buy_payout_cents` by the order's `total_payout_cents`; and sets the order `status` to `SETTLED`. Alternatively, a `ComplianceOfficer` may reject a placed buy order, which is allowed only from `PLACED`, sets the `status` to `REJECTED`, and disburses no payout and creates no inventory.

### 3.5. The Layaway and Price-Lock Program

A layaway lets a customer reserve stock at today's price and pay it off over time. A `SalesAgent` opens a layaway naming the `customer_id`, the `product_id`, the specific `inventory_lot_id` whose units are being held, and the `quantity` to reserve (at least 1). Opening a layaway requires that the aggregate `available_qty` across the product's `AVAILABLE` lots be at least the requested `quantity`, or the request is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 422). The inventory-sufficiency check uses the product-wide aggregate, and the server does not additionally verify that the supplied `inventory_lot_id` belongs to the named `product_id` or that the chosen lot individually holds enough available units. On success the system moves units from available to reserved on the chosen lot — decrementing that lot's `available_qty` (which is not floored at zero) and incrementing its `reserved_qty` by the `quantity` — locks the `locked_unit_price_cents` from the unit sell price of §3.1 (this price is immune to any later spot-rate change, which is the price-lock guarantee), sets `total_price_cents` to the locked unit price multiplied by the `quantity`, initializes `amount_paid_cents` to 0, and sets `status` to `ACTIVE`.

While a layaway is `ACTIVE` it accepts deposits in a repeating self-loop that keeps it `ACTIVE`. A `Customer` — who must own the layaway (its `customer_id` must equal the caller's `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER`) — applies a deposit by supplying an `amount_cents` (at least 1) together with the `expected_layaway_version` for the optimistic-concurrency check of §2.6. The deposit is accepted only when the layaway is `ACTIVE`, the version matches, and the new cumulative total would not exceed the price: that is, `amount_paid_cents` plus `amount_cents` must be at most `total_price_cents`. A deposit that would push `amount_paid_cents` above `total_price_cents` is rejected as an overpayment with `ERR_OVERPAYMENT` (HTTP 422), though paying exactly the remaining balance is allowed. A successful deposit increases `amount_paid_cents` by `amount_cents` and increments the layaway's `version`; the reservation is unchanged.

The layaway then leaves the `ACTIVE` state by exactly one of three exits, each with its own effect on the reserved inventory. A `SalesAgent` completes a fully-paid layaway, allowed only when it is `ACTIVE` and `amount_paid_cents` equals `total_price_cents` (a completion attempt on an `ACTIVE` layaway that is not yet fully paid is rejected with `ERR_INVALID_STATE`, HTTP 409): completion converts the reservation to a delivered sale by decrementing the lot's `reserved_qty` by the `quantity` and incrementing its `sold_qty` by the same `quantity`, and any such lot whose `available_qty` is 0 with `sold_qty` equal to `total_qty` transitions to `DEPLETED`; the layaway `status` becomes `COMPLETED`. Alternatively, a `SalesAgent` may default an active layaway: this releases the reservation by decrementing the lot's `reserved_qty` and incrementing its `available_qty` by the `quantity` (a compensating move that conserves `total_qty`), credits the customer's `store_credit_cents` by the layaway's `amount_paid_cents` so the deposits become refundable store credit, and sets the `status` to `DEFAULTED`. Finally, the owning `Customer` may cancel an active layaway, which likewise releases the reservation back to `available_qty` and refunds the accumulated `amount_paid_cents` into the customer's `store_credit_cents`, setting the `status` to `CANCELLED`. All three exits require the layaway to be `ACTIVE`, guarded by `ERR_INVALID_STATE`.

### 3.6. Consignment Intake, Auction Listing, and the Sale/Return Fork

The dealership also brokers items it does not own, through consignment. A `SalesAgent` intakes a consignment naming the consignor's `customer_id`, a free-text `description` of the item, the `reserve_price_cents` (the minimum hammer price the consignor will accept, a non-negative integer), the `commission_pct` the house takes from the hammer price (a fraction at least 0 and less than 1), and the `buyer_premium_pct` added to the hammer price at auction (likewise at least 0 and less than 1). An `auction_session_id` may be supplied at intake or left null for a private-treaty arrangement. A freshly intaken consignment has `hammer_price_cents` null and `status` `INTAKE`.

To bring a consignment to auction, a `SalesAgent` lists it, supplying the `auction_session_id` of the target session. Listing is permitted only when the consignment is currently `INTAKE` and the referenced auction session's `status` is `SCHEDULED`; a session in any other status yields `ERR_SESSION_NOT_SCHEDULED` (HTTP 422). On success the consignment records its `auction_session_id` and moves from `INTAKE` to `LISTED`.

From the `LISTED` state the consignment forks into one of two mutually exclusive outcomes with sharply divergent effects. In the first branch, a `SalesAgent` records a sale, supplying the winning `hammer_price_cents` and the `expected_consignment_version` for the OCC check of §2.6. Recording a sale is allowed only when the consignment is `LISTED`, the version matches, and the supplied `hammer_price_cents` is at least the consignment's `reserve_price_cents`; these checks are evaluated in that order, so the state check comes first, the OCC stale-version check (`ERR_STALE_VERSION`, HTTP 412) is applied next, and only after the version matches is the reserve check reached — a hammer price below reserve is then rejected with `ERR_RESERVE_NOT_MET` (HTTP 422), and meeting the reserve exactly is allowed. A successful record-sale stores the `hammer_price_cents` on the consignment, advances its `status` from `LISTED` to `SOLD`, and increments its `version`. In the second branch, a `SalesAgent` returns an unsold `LISTED` consignment to the consignor: this simply advances the `status` from `LISTED` to `RETURNED`, and — in deliberate contrast to the sale branch — no settlement is ever created and no proceeds are computed for a returned consignment.

### 3.7. Consignment Settlement and Proceeds Split

Once a consignment is `SOLD`, a `ComplianceOfficer` creates its settlement, supplying only the `consignment_id`; a settlement request against a consignment that is not `SOLD` is rejected with `ERR_INVALID_STATE` (HTTP 409). The settlement copies the `hammer_price_cents` from the sold consignment and splits the money in a rounding order that is pinned: each percentage component is rounded independently first, and only then are the summed figures formed. Concretely, the `commission_cents` is the `hammer_price_cents` multiplied by the consignment's `commission_pct`, rounded half up to whole cents; the `buyer_premium_cents` is the `hammer_price_cents` multiplied by the consignment's `buyer_premium_pct`, rounded half up to whole cents independently of the commission; the `seller_proceeds_cents` is the `hammer_price_cents` minus the already-rounded `commission_cents`; and the `dealer_revenue_cents` is the already-rounded `commission_cents` plus the already-rounded `buyer_premium_cents`. This round-then-sum order is required — rounding the sum of the two percentages together would produce a different cent in edge cases. Creating the settlement credits the consignor's `store_credit_cents` by the `seller_proceeds_cents`.

### 3.8. Grading, Authentication, and Auction Scheduling

Consigned items are graded and authenticated by appraisers. A `SalesAgent` registers an appraiser with a `name` and a `specialty_metal` (one of `GOLD`, `SILVER`, `PLATINUM`, or `PALLADIUM`). Appraisal appointments book an appraiser against a consignment: a `SalesAgent` supplies the `appraiser_id`, the `consignment_id` of the item to be graded, and the `start_at` and `end_at` timestamps (ISO 8601 UTC, with `end_at` required to be after `start_at`). A new appointment must not overlap an existing `BOOKED` appointment for the same appraiser; these intervals are treated as **closed** on both ends, so an appointment that touches another exactly at its boundary (one ending at the instant the next begins) is treated as a collision and rejected with `ERR_APPRAISER_DOUBLE_BOOKED` (HTTP 409). An appointment begins with `status` `BOOKED`, occupying the appraiser's closed time slot; a `SalesAgent` may cancel a `BOOKED` appointment, which sets its `status` to `CANCELLED` and releases the appraiser's slot.

Auction sessions are scheduled by a `SalesAgent`, who supplies the `room` identifier and the `scheduled_start` and `scheduled_end` timestamps (ISO 8601 UTC, with `scheduled_end` required to be after `scheduled_start`). Two sessions in the same `room` may not overlap in time, but unlike appraisal appointments these intervals are **half-open**, spanning from the start up to but not including the end; a session that begins exactly when another ends therefore does not collide, whereas any genuine overlap is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409). A session begins with `status` `SCHEDULED` and may later be closed by a `SalesAgent`, moving its `status` from `SCHEDULED` to `CLOSED`. This half-open-versus-closed distinction between rooms and appraisers is intentional: back-to-back auction sessions in one room are permitted, but back-to-back appraisal slots for one appraiser are not.

### 3.9. Inventory Hedging and Profit-and-Loss

To offset the price risk of holding physical metal, a `Trader` opens short hedge positions. Opening a position names the `metal` being hedged and the `short_troy_oz` sold short to offset the long inventory exposure (a real number greater than zero). At open, the system captures the `entry_spot_cents` from the live spot rate's `price_per_troy_oz_cents` for that metal, and the position begins with `status` `OPEN`; its `exit_spot_cents` and `realized_pnl_cents` remain null while open, and `unrealized_pnl_cents` starts at 0.

A hedge position's profit and loss has two variants that differ in which spot price they use. While the position is `OPEN`, reading it computes an **unrealized** profit-and-loss live: the system subtracts the current spot price for the metal from the position's `entry_spot_cents`, multiplies that difference by the `short_troy_oz`, and rounds half up to whole cents. Because it uses the current spot rate, this value moves as the market moves and is never persisted as a final figure. When a `Trader` closes an open position, the system captures the `exit_spot_cents` from the current spot rate, then computes the **realized** profit-and-loss by subtracting the captured `exit_spot_cents` from the `entry_spot_cents`, multiplying by the `short_troy_oz`, and rounding half up to whole cents; this figure is stored in `realized_pnl_cents` and frozen thereafter. Closing is permitted only from `OPEN`, and sets the `status` to `CLOSED`.

### 3.10. Customer Records and Balances

A customer record is the anchor for every party the dealership transacts with. A `SalesAgent` or `ComplianceOfficer` creates a customer with a `full_name` and optionally the `id_document_on_file` flag (defaulting to false), which records whether a government ID has been captured — a prerequisite both for approving that customer's IRA account and for settling any reportable buy order from them. The same roles may update a customer's KYC flags through a patch that increments the customer's `version`; the only mutable field is `id_document_on_file` (other body fields are ignored), and the patch always refreshes `updated_at` and increments `version` even when the supplied value leaves the flag unchanged or no mutable field is supplied at all. Two balances on the customer are maintained by the system and are never set directly by a client: `lifetime_buy_payout_cents`, the running sum of all settled buy-order payouts from the customer (initialized to 0), and `store_credit_cents`, the refundable credit balance (initialized to 0) that accumulates when a layaway defaults or is cancelled and when a consignment settlement credits the consignor's proceeds. A customer may read their own record; sales agents and compliance officers may read any customer.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Endpoints that create a brand-new resource return HTTP 201; endpoints that modify, transition, or read an existing resource return HTTP 200. Request bodies, response bodies, and side effects for each endpoint are described in the workflow narratives of §3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /api/spot-rates | Create the live spot rate for a metal. | Trader |
| PUT | /api/spot-rates/{id} | Update the spot price for a metal; affects future pricing only. | Trader |
| GET | /api/spot-rates/{id} | Read one spot rate. | Trader, SalesAgent, ComplianceOfficer, Customer |
| POST | /api/products | Create a catalog product. | Trader |
| GET | /api/products/{id} | Read one product. | Trader, SalesAgent, ComplianceOfficer, Customer |
| POST | /api/inventory-lots | Record a physical inventory lot for a product. | Trader |
| GET | /api/inventory-lots/{id} | Read one inventory lot. | Trader, SalesAgent, ComplianceOfficer |
| GET | /api/inventory-lots | List inventory lots, optionally filtered by product. | Trader, SalesAgent, ComplianceOfficer |
| POST | /api/customers | Create a customer. | SalesAgent, ComplianceOfficer |
| PATCH | /api/customers/{id} | Update customer KYC flags such as id_document_on_file. | SalesAgent, ComplianceOfficer |
| GET | /api/customers/{id} | Read one customer. | SalesAgent, ComplianceOfficer, Customer |
| POST | /api/ira-accounts | Open a PENDING IRA account for a customer with a custodian. | ComplianceOfficer |
| POST | /api/ira-accounts/{id}/approve | Approve a PENDING IRA account, moving it to ACTIVE. | ComplianceOfficer |
| POST | /api/ira-accounts/{id}/close | Close an ACTIVE IRA account. | ComplianceOfficer |
| GET | /api/ira-accounts/{id} | Read one IRA account. | ComplianceOfficer, SalesAgent |
| GET | /api/ira-accounts | List IRA accounts, optionally filtered by customer. | ComplianceOfficer, SalesAgent |
| POST | /api/sell-orders | Place a sell order; locks quoted price and provisional COGS. | SalesAgent |
| POST | /api/sell-orders/{id}/settle | Settle a placed sell order: FIFO-consume inventory, compute final COGS and realized margin. | SalesAgent |
| POST | /api/sell-orders/{id}/cancel | Cancel a placed sell order. | SalesAgent |
| GET | /api/sell-orders/{id} | Read one sell order. | SalesAgent, ComplianceOfficer |
| GET | /api/sell-orders | List sell orders, optionally filtered by customer, product, or IRA account. | SalesAgent, ComplianceOfficer |
| POST | /api/buy-orders | Place a buy order; locks payout and reportable flag. | SalesAgent |
| POST | /api/buy-orders/{id}/approve-reportable | Compliance approval that a reportable buy may proceed to settlement. | ComplianceOfficer |
| POST | /api/buy-orders/{id}/settle | Settle a placed buy order: disburse payout and add inventory. | SalesAgent |
| POST | /api/buy-orders/{id}/reject | Compliance rejection of a placed buy order. | ComplianceOfficer |
| GET | /api/buy-orders/{id} | Read one buy order. | SalesAgent, ComplianceOfficer |
| GET | /api/buy-orders | List buy orders, optionally filtered by customer or product. | SalesAgent, ComplianceOfficer |
| POST | /api/layaways | Open a layaway; reserves inventory and locks the sell price. | SalesAgent |
| POST | /api/layaways/{id}/deposit | Apply a deposit to an active layaway (OCC-guarded). | Customer |
| POST | /api/layaways/{id}/complete | Complete a fully-paid layaway; converts the reservation to a sale. | SalesAgent |
| POST | /api/layaways/{id}/default | Mark an active layaway defaulted; release reservation, deposits become store credit. | SalesAgent |
| POST | /api/layaways/{id}/cancel | Cancel an active layaway; release reservation and refund deposits to store credit. | Customer |
| GET | /api/layaways/{id} | Read one layaway. | SalesAgent, ComplianceOfficer, Customer |
| GET | /api/layaways | List layaways, optionally filtered by customer, product, or lot. | SalesAgent, ComplianceOfficer |
| POST | /api/consignments | Intake a consignment item from a consignor. | SalesAgent |
| POST | /api/consignments/{id}/list | List an INTAKE consignment into a SCHEDULED auction session. | SalesAgent |
| POST | /api/consignments/{id}/record-sale | Record the winning hammer price for a LISTED consignment (OCC-guarded). | SalesAgent |
| POST | /api/consignments/{id}/return | Return a LISTED consignment unsold to the consignor. | SalesAgent |
| GET | /api/consignments/{id} | Read one consignment. | SalesAgent, ComplianceOfficer |
| GET | /api/consignments | List consignments, optionally filtered by customer or auction session. | SalesAgent, ComplianceOfficer |
| POST | /api/hedge-positions | Open a short hedge position for a metal at the current spot. | Trader |
| POST | /api/hedge-positions/{id}/close | Close an open hedge position; realize PnL against current spot. | Trader |
| GET | /api/hedge-positions/{id} | Read one hedge position; unrealized PnL recomputed live while OPEN. | Trader |
| POST | /api/settlements | Create the settlement for a SOLD consignment; credits consignor and records dealer revenue. | ComplianceOfficer |
| GET | /api/settlements/{id} | Read one settlement. | ComplianceOfficer, SalesAgent |
| GET | /api/settlements | List settlements, optionally filtered by consignment. | ComplianceOfficer, SalesAgent |
| POST | /api/appraisers | Register an appraiser (grader/authenticator). | SalesAgent |
| GET | /api/appraisers/{id} | Read one appraiser. | SalesAgent, ComplianceOfficer |
| POST | /api/appraisal-appointments | Book an appraisal appointment for a consignment with an appraiser. | SalesAgent |
| POST | /api/appraisal-appointments/{id}/cancel | Cancel a booked appraisal appointment; release the slot. | SalesAgent |
| GET | /api/appraisal-appointments/{id} | Read one appraisal appointment. | SalesAgent, ComplianceOfficer |
| GET | /api/appraisal-appointments | List appraisal appointments, optionally filtered by appraiser or consignment. | SalesAgent, ComplianceOfficer |
| POST | /api/auction-sessions | Schedule an auction session in a room; rejects overlapping sessions in the same room. | SalesAgent |
| POST | /api/auction-sessions/{id}/close | Close a scheduled auction session. | SalesAgent |
| GET | /api/auction-sessions/{id} | Read one auction session. | SalesAgent, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ID_REQUIRED_FOR_REPORTABLE | 422 |
| ERR_REPORTABLE_NOT_APPROVED | 422 |
| ERR_IRA_NOT_ACTIVE | 422 |
| ERR_PRODUCT_NOT_IRA_ELIGIBLE | 422 |
| ERR_BULLION_PREMIUM_FORBIDDEN | 422 |
| ERR_RESERVE_NOT_MET | 422 |
| ERR_ROOM_DOUBLE_BOOKED | 409 |
| ERR_APPRAISER_DOUBLE_BOOKED | 409 |
| ERR_SESSION_NOT_SCHEDULED | 422 |
| ERR_INSUFFICIENT_INVENTORY | 422 |
| ERR_OVERPAYMENT | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
