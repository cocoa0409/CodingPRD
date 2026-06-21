# General Retail POS & Inventory API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the General Retail POS & Inventory API, a back-office and point-of-sale platform that runs the floor and the stockroom of a multi-store retail chain. The system is responsible for the full commercial life of merchandise: cataloguing products by SKU and barcode, holding per-store stock with reorder thresholds, ringing up sales, returns, and exchanges, splitting payment across mixed tenders, running discounts and loyalty redemption, parking goods on layaway, moving stock between stores, and squaring the cash drawer at the end of each shift.

Retail operations are unforgiving about consistency. A point of sale that lets a cashier sell stock that is already reserved for a layaway, or that drifts a loyalty balance, or that closes a drawer whose tally does not survive an audit, erodes trust quickly. The API is therefore built around immediate, atomic effects: every sale, deposit, transfer, and count posts its inventory, ledger, loyalty, and cash consequences within the request that triggers it, and every contested write is guarded so that two operators working the same resource cannot silently overwrite each other. A single sale carries two independent fates — how it is paid for and how it touches stock — and the platform tracks those two dimensions separately so that the money side and the goods side can never be confused for one another.

The intended readers are the engineers building the service. The sections below first fix the system-wide contract — authentication, the response envelope, pagination, precision, concurrency, and the cross-cutting principles that govern stock, cash, and loyalty — and then walk the business workflows in narrative form. Field names, thresholds, and the precise conditions that trigger each error are woven through that narrative; they are not collected into schema tables.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles, spelled precisely as `StoreManager`, `Cashier`, `InventoryClerk`, and `Customer`. A request that omits `X-User-Role` or presents a value that is not one of these four recognized roles is rejected with `ERR_UNAUTHENTICATED`. A request that is authenticated but whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

Three of the four roles are operator identities not tied to any persisted record. When `X-User-Role` is `StoreManager`, `Cashier`, or `InventoryClerk`, the `X-User-ID` is an opaque operator identifier not tied to any stored entity; the server may record it for audit but does not compare it to any entity's `id`. The `Customer` role is different: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `LoyaltyAccount`, and ownership checks on any resource that references a loyalty member — a member's own loyalty account, their layaways, and their sales — compare the resource's loyalty foreign key to `X-User-ID`.

Authority is divided by job function. A `StoreManager` owns store setup, promotions, cash-drawer lifecycle and reconciliation, product discontinuation, and the layaway overrides (forfeit and cancel); the manager also holds the two test-driving capabilities (granting loyalty points and advancing the clock). A `Cashier` owns the sale, return, and exchange register: creating and editing draft sales, appending tenders, and voiding. An `InventoryClerk` owns stock: count sheets and inventory transfers between stores. Several operations are shared — product and inventory-item creation are open to both `InventoryClerk` and `StoreManager`; loyalty enrollment and layaway creation and deposits are open to both `Cashier` and `StoreManager`; transfer creation and the cancel of a still-requested transfer are open to both `InventoryClerk` and `StoreManager`. Read endpoints are broadly available; a `Customer` may read only their own loyalty account, layaways, and sales, plus the public catalogue and store records.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the permitted range is rejected as a generic validation failure with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — `Store`, `Product`, `InventoryItem`, `LoyaltyAccount`, `Promotion`, `CashDrawerSession`, `Sale`, `Layaway`, `Transfer`, and `CountSheet` — carries a common set of system-managed fields. The `id` is a server-minted UUID used for identity only and carries no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded at creation. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that starts at 1 and increments by one on every mutation that changes the resource; it underpins the optimistic concurrency control described in §2.7.

`TenderLine` is the one exception. A tender line carries only `id` and `created_at` — it has no `updated_at` and no `version` — because tenders are immutable once recorded: a tender line is never edited, only appended, and any reversal is expressed as a new compensating tender line rather than a mutation of an existing one. The `created_at` on a tender line additionally fixes its append order.

Whenever a derived field on a resource changes — for example `available_qty` or `below_reorder` on an `InventoryItem`, `expected_cash_cents` on a `CashDrawerSession`, or `tier` on a `LoyaltyAccount` — that change is a mutation of the owning resource: it refreshes `updated_at` and increments `version` just as an input edit would.

### 2.5. Nested Resource Retrieval and Reference Resolution

Some endpoints address a child collection through a parent in the URL, for example the tender lines of a sale. For any path that names a resource by identifier, the system validates each identifier left-to-right and rejects the first one that does not resolve with `ERR_NOT_FOUND` (404) before any deeper work begins. A request for the tenders of a sale that does not exist fails on the sale before the tender collection is ever consulted.

Path resolution is distinct from body-reference resolution. When a request body carries a foreign key — `store_id`, `product_id`, `loyalty_account_id`, `original_sale_id`, `inventory_item_id`, `customer_id`, `from_store_id`, or `to_store_id` — and that key names a row that does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND` (422). Missing path resources surface as 404; unresolvable body references surface as 422.

### 2.6. Monetary, Quantity, and Loyalty Precision

All money in the system is held and exchanged as integer cents; there are no fractional cents and no floating-point money. Quantities are integer units. Loyalty points are integers. The rounding discipline matters because several figures derive from one another in a pinned order.

Two rounding rules apply across the pricing engine. Discounts are computed by flooring — they always round down to the nearest whole cent. Tax is computed by rounding half up: a fractional result of exactly one half rounds up to the next cent. Critically, when a sale spans several taxable lines, the taxable bases of all lines are summed first and the half-up rounding is applied exactly once to that total. Rounding each line's tax independently and then summing is forbidden, because it can differ from the sum-then-round result by a cent. The same sum-then-round discipline governs any allocation that is split across lines and then totalled: allocate, accumulate, then round once.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded against stale-read overwrites, and each requires the client to echo back the `version` it last observed on the parent resource. The guard is keyed on the parent's current `version`: if the supplied expected version does not match, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and the rejection happens before any side effect lands.

Appending a tender to a sale must carry `expected_sale_version` equal to the target sale's current `version`. Because a prior split-payment tender or a line recompute legitimately advances the sale's `version`, a client holding an older view of `total_due_cents` and `tendered_cents` would otherwise risk over-collecting or settling against an outdated total; if another writer has advanced the sale's `version` since the client last read it, the tender is rejected with `ERR_STALE_VERSION` (412). Recording a deposit on a layaway must carry `expected_layaway_version` equal to the layaway's current `version`; if another deposit or a clock-driven move into `DELINQUENT` has advanced the layaway's `version` since the client last read it, the client's view of `balance_cents` is stale and the deposit is rejected with `ERR_STALE_VERSION` (412), preventing an overpayment or a misfired settlement. Dispatching a transfer must carry `expected_transfer_version` equal to the transfer's current `version`; if a concurrent cancel or edit has advanced the transfer's `version` since the client last read it, the dispatch is rejected with `ERR_STALE_VERSION` (412), preventing source stock from being reserved against a transfer that is no longer `REQUESTED`. No other endpoint takes a version field; operations not in this list of three are not subject to the OCC check.

### 2.8. The Drawer Posture Principle

Each `Store` carries a derived `posture` that is never set directly but is recomputed from the store's cash-drawer sessions. A store's `posture` is `DRAWER_OPEN` when exactly one of its `CashDrawerSession` records is in `OPEN` status, and `LOCKED` otherwise — that is, whenever none of its sessions is `OPEN`. The recomputation runs on every drawer transition: opening a session, requesting close, reconciling, reopening, or force-closing. A store enforces at most one session in `OPEN` or `CLOSE_REQUESTED` at a time; an attempt to open a session for a store that already has one in `OPEN` or `CLOSE_REQUESTED` is rejected as a state-constraint violation with `ERR_INVALID_STATE` (not as a uniqueness collision). The practical force of `posture` is that it gates payment: tender capture on a sale is permitted only while the selling store is `DRAWER_OPEN`, and is blocked while the store is `LOCKED`.

### 2.9. Inventory Accounting and Reorder Flagging

An `InventoryItem` tracks stock for one product at one store, and there is at most one such item per (`store_id`, `product_id`) pair. Three quantities are kept in step. `on_hand_qty` is the physical count of units present, whether sellable or reserved; `reserved_qty` is the subset committed to active layaways or in-flight transfers but still physically on the shelf; and `available_qty`, the sellable count, is on-hand minus reserved. Whenever either physical or reserved stock moves — through a sale commitment, a return restock, a transfer leg, a layaway event, or a posted count — `available_qty` is recomputed as `on_hand_qty` minus `reserved_qty`, and the `below_reorder` flag is recomputed as true exactly when `available_qty` is at or below the item's `reorder_point` (the comparison is inclusive at the threshold). The `reorder_qty` carried on the item is the suggested replenishment quantity when the item falls to or below its reorder point. A fresh inventory item is created with both `on_hand_qty` and `reserved_qty` at zero.

### 2.10. Cascading Reversal Integrity

Several operations touch more than one entity, and the platform guarantees that every cascade either lands in full or not at all. When a settled sale is unwound — most dramatically by a drawer force-close — the system reverses the captured tenders with compensating tender lines, restocks the inventory the sale had committed, and restores the loyalty effects, all atomically. When a stock-bearing resource is reserved or released, the affected `InventoryItem` always has its `available_qty` and `below_reorder` re-derived as part of the same operation. The secondary effects are never optional and never deferred: a force-close that voids a sale also reverses its tenders, also restocks, and also restores loyalty in the same request. These cascades are detailed in the workflow sections that follow.

## 3. Business Logic & Workflows

### 3.1. Catalogue, Stores, and Stock Foundations

A `StoreManager` stands up a store by supplying its `name`, a short `code` that is unique across all stores (such as "NYC01"), and a `tax_rate_bps` expressing sales tax in basis points — a value of 875 means 8.75 percent — which must lie between 0 and 2000 inclusive. The manager may also supply `loyalty_earn_rate_bps`, the points earned per currency unit of net merchandise expressed in basis points (a value of 100 earns one point per dollar of net), which defaults to 100 and may not be negative. A newly created store starts `LOCKED`: with no open drawer, no payment can yet be captured. Duplicate store codes are rejected as a uniqueness collision with `ERR_DUPLICATE_RESOURCE`.

Either a `StoreManager` or an `InventoryClerk` catalogues a `Product` by supplying its `sku`, its `barcode`, a `name`, and a `list_price_cents` (the catalogue unit price in cents, which may not be negative). Two booleans tune behaviour: `tax_exempt`, defaulting to false, excludes the line from the tax base when true; and `loyalty_eligible`, defaulting to true, governs whether the line's net accrues loyalty points. Both `sku` and `barcode` are unique across the catalogue, and a collision on either is an `ERR_DUPLICATE_RESOURCE`. A product is born `ACTIVE`; a `StoreManager` may later move it to `DISCONTINUED`. The catalogue list endpoint accepts `sku`, `barcode`, and `status` filters so that a scanner can resolve a product by its scanned code.

Stock is held per store. A `StoreManager` or `InventoryClerk` creates an `InventoryItem` against a `store_id` and `product_id`, optionally seeding the `reorder_point` and `reorder_qty` thresholds. Creating a second inventory item for the same store-and-product pair is rejected as a uniqueness collision with `ERR_DUPLICATE_RESOURCE`. The inventory list endpoint filters by `store_id`, `product_id`, and `below_reorder` so a clerk can pull every item at or below its reorder point.

### 3.2. Opening the Register and the Cash Drawer Lifecycle

Before any sale can be paid for, a `StoreManager` opens a `CashDrawerSession` for a `store_id` with an `opening_float_cents` starting balance. The session begins `OPEN`, and the store's `posture` is recomputed to `DRAWER_OPEN`. Throughout the session the system maintains `expected_cash_cents` — the running expectation of what the till should hold — beginning at the opening float and moving with every cash event on the sessions's settled sales.

When the shift ends, the manager freezes the session for reconciliation, moving it `OPEN → CLOSE_REQUESTED`. This freeze is only permitted when no sale bound to the session is mid-payment — every bound sale must be `DRAFT`, `SETTLED`, or `VOIDED`, never `TENDERING`; a freeze attempted against a transition the session cannot make is rejected with `ERR_INVALID_STATE`. On freeze, `expected_cash_cents` is locked for the count, the store's `posture` is recomputed (dropping to `LOCKED` if this was the only open session), and the session's `version` increments by one.

To reconcile, the manager submits the physically counted till as `counted_cash_cents`, moving the session `CLOSE_REQUESTED → RECONCILED`. The expected figure is the opening float plus all cash collected, minus all cash change handed back, minus all cash refunds paid out, computed over the cash tender lines of the sessions's settled sales: specifically, `expected_cash_cents` is the `opening_float_cents` plus the sum of the positive amounts of cash tenders on settled bound sales, minus the sum of those tenders' change-due amounts, plus the sum of the negative amounts of cash refund tenders on settled bound sales (negatives reduce the drawer). Sales that were voided before settling contribute nothing. The signed `variance_cents` is then the counted cash minus the expected cash. Reconciliation requires `counted_cash_cents` to be present in the request, and it increments the session's `version` by one.

A manager may instead reopen a frozen session, moving it `CLOSE_REQUESTED → OPEN`; this clears `counted_cash_cents` and `variance_cents`, recomputes the store's `posture` back to `DRAWER_OPEN`, and increments the session's `version`. Finally, a manager may force-close an `OPEN` session, moving it `OPEN → FORCE_CLOSED`. A force-close is the most consequential drawer action: every sale bound to the session still in `DRAFT` is voided to `VOIDED` and any reservation it held is released; every bound sale in `TENDERING` is voided as well, with its captured tenders reversed through compensating refund tender lines and its inventory and loyalty effects unwound; the store's `posture` is recomputed to `LOCKED`; and the session's `version` increments by one. The cascade runs force-close → sale voided → tender reversal → inventory restock → loyalty restore, atomically.

### 3.3. Ringing a Sale: Pricing the Basket

A `Cashier` opens a transaction by creating a `Sale` against a `store_id` with a `kind` of `SALE`, `RETURN`, or `EXCHANGE`, and a `lines` array. Each element of `lines` names a `product_id` and a `quantity`, and for returns and exchanges additionally a `return_of_line_no` identifying which original line it returns against. The cashier may attach an optional `loyalty_account_id`, a `promo_code`, a number of points to redeem in `redeem_points` (defaulting to 0), and, for a return or exchange, the `original_sale_id` of the settled sale being returned against. A new sale is born with `settlement_status` of `DRAFT` and `stock_status` of `PENDING`, is bound through `cash_session_id` to the store's current open session, and is immediately priced. A `Cashier` may replace the `lines` of a `DRAFT` sale — and re-supply `promo_code` and `redeem_points` — to reprice it; each such edit recomputes the pricing and increments the sale's `version` by one.

Pricing follows a strictly pinned six-step order, all in integer cents. **First**, the `merchandise_subtotal_cents` is the sum over all lines of the product's `list_price_cents` times the line `quantity`. **Second**, the promo discount on the eligible subtotal is determined: if no promo is supplied, or the resolved promotion is not `ACTIVE`, or the merchandise subtotal is below the promotion's `min_subtotal_cents`, then `discount_cents` is zero; otherwise it depends on the promotion's `kind`. For a `PERCENT_OFF` promotion, `discount_cents` is the merchandise subtotal multiplied by the promotion's `value` percent, divided by one hundred, floored. For an `AMOUNT_OFF` promotion, `discount_cents` is the smaller of the promotion's `value` (cents off) and the merchandise subtotal. For a `BOGO_50` promotion, the promotion's `value` is ignored and instead, for each product line, the number of qualifying pairs is the line `quantity` divided by two and floored, and the discount for that line is that pair count multiplied by half of the product's `list_price_cents` floored; `discount_cents` is the sum of those per-line amounts (fifty percent off the cheaper — here, equal — unit of each qualifying pair). **Third**, the post-discount subtotal is the merchandise subtotal minus `discount_cents`.

**Fourth**, loyalty redemption is applied only when `redeem_points` is greater than zero: `loyalty_redeemed_cents` is the smaller of `redeem_points` (each point worth one cent) and the post-discount subtotal. **Fifth**, tax is computed on the taxable base. Each non-tax-exempt line takes its proportional share of the post-discount, post-redemption amount, allocated in proportion to that line's pre-discount extended price; those line shares are summed into the taxable base, and `tax_cents` is the taxable base multiplied by the store's `tax_rate_bps`, divided by ten thousand, rounded half up exactly once over the summed base — never per line. **Sixth**, `total_due_cents` is the post-discount subtotal minus `loyalty_redeemed_cents` plus `tax_cents`. The sale also exposes `tendered_cents`, the running sum of captured tender amounts, and `points_earned`, the loyalty accrued at settlement (initially zero).

For a return or exchange, the line prices and tax are taken from the original settled sale rather than recomputed from the current catalogue, as the next subsection details.

### 3.4. Promotions, Loyalty Redemption, and Their Interaction

A `StoreManager` creates a `Promotion` with a unique `code`, a `kind` of `PERCENT_OFF`, `AMOUNT_OFF`, or `BOGO_50`, and a `value` whose meaning depends on the kind: for `PERCENT_OFF` it is a percent from 0 to 100; for `AMOUNT_OFF` it is cents off the eligible subtotal; for `BOGO_50` it is ignored. The manager may set a `min_subtotal_cents` floor (defaulting to 0) below which the promotion does not apply, and a `stackable` flag (defaulting to false). A promotion is born `ACTIVE`; a manager may later move it to `DISABLED`. A duplicate promo code is an `ERR_DUPLICATE_RESOURCE`.

Two applicability guards run when a promo is applied to a sale, either at creation or during a line edit. If the resolved promotion is not `ACTIVE`, or the `merchandise_subtotal_cents` is below the promotion's `min_subtotal_cents`, the promo cannot apply and the request is rejected with `ERR_PROMO_NOT_APPLICABLE`. Separately, the `stackable` flag governs the interaction with loyalty: when a non-stackable promotion has actually produced a discount and the customer also asks to redeem points on the same sale, the request is rejected with `ERR_PROMO_NOT_STACKABLE` — a non-stackable discount and a loyalty redemption cannot coexist on one sale.

Loyalty redemption has its own guard. The points a customer asks to redeem cannot exceed the post-discount, pre-tax subtotal, and the attached account must actually hold at least the requested `redeem_points`; a request that asks to redeem more than the account's balance or more than the redeemable subtotal is rejected with `ERR_INSUFFICIENT_POINTS`.

### 3.5. Tendering, Splitting Payment, and Settlement

Once a sale is priced, a `Cashier` captures payment by appending tender lines. Each `TenderLine` records its parent `sale_id`, a `method` of `CASH`, `CARD`, `STORE_CREDIT`, or `GIFT_CARD`, an `amount_cents` (positive collects from the customer, negative refunds to the customer), and the OCC field `expected_sale_version` supplied on the request. Tender capture is permitted only while the selling store is `DRAWER_OPEN`; a tender attempted while the store has no open drawer is rejected with `ERR_DRAWER_NOT_OPEN`. The first tender advances the sale `DRAFT → TENDERING`; the sale's `total_due_cents` must be finalized before the first tender, which it always is, since pricing runs at creation and on every line edit. Each subsequent split tender, while the running tender total has not yet reached the amount due, keeps the sale in `TENDERING` and appends another `TenderLine`; each appended tender updates `tendered_cents` and increments the sale's `version` by one.

Settlement is automatic. For a `SALE`, once the captured tenders bring `tendered_cents` to at least `total_due_cents`, the sale moves `TENDERING → SETTLED`; if the customer overpays in cash, the excess is returned as `change_due_cents` on that closing cash tender. For a net-refund `RETURN` or `EXCHANGE`, where the amount due is zero or negative, settlement occurs when `tendered_cents` reaches at most `total_due_cents` (both being zero or negative). On a non-cash tender, over-collecting beyond `total_due_cents` is not allowed — only `CASH` may exceed the amount due, yielding change — and a `CARD`, `STORE_CREDIT`, or `GIFT_CARD` tender that would over-collect on a `SALE` is rejected with `ERR_OVERTENDER`. The `change_due_cents` on a tender is zero except in the cash-overpayment case on a sale.

Settlement is the moment the sale's two dimensions advance together. On the stock axis, a settled `SALE` moves `stock_status` `PENDING → COMMITTED` and a settled `RETURN` or `EXCHANGE` moves it `PENDING → RESTOCKED`. On the ledger side, loyalty `points_earned` are credited to any attached account, redeemed points are debited, the drawer's `expected_cash_cents` is updated by the net cash movement, and a return reverses both the points and the redemption. A sale that has not yet settled may be voided by a `Cashier`, which is allowed from `DRAFT` or `TENDERING` (anything but `SETTLED`); a void reverses any captured tenders through compensating tender lines, releases any inventory reservation or commitment so there is no net stock change, restores any provisionally debited loyalty redemption, and sets `settlement_status` to `VOIDED`. Tender capture against a transition the sale cannot make — for instance tendering a sale that is already `SETTLED` or `VOIDED` — is rejected with `ERR_INVALID_STATE`.

### 3.6. Committing and Restocking Inventory at Settlement

The stock axis (`stock_status`) of a sale evolves independently of its payment axis and only ever moves at settlement. When a `SALE` settles, it transitions `PENDING → COMMITTED`: for each line, the system first requires that the line's `InventoryItem` has `available_qty` at least the line `quantity`; if any line falls short, settlement is rejected with `ERR_INSUFFICIENT_STOCK`. On success, each line's `on_hand_qty` is decremented by the line `quantity`, and `available_qty` and `below_reorder` are re-derived for each affected item.

When a `RETURN` or `EXCHANGE` settles, it transitions `PENDING → RESTOCKED`. Each return line must map to a line on the `original_sale_id` that has not already been fully returned. Resellable returned units increment the corresponding `on_hand_qty`; for an `EXCHANGE`, the outbound (newly sold) lines decrement `on_hand_qty` as a sale would. Every touched item has its `available_qty` and `below_reorder` recomputed.

### 3.7. Returns and Exchanges: Provisional vs. Final Refund

A `RETURN` or `EXCHANGE` always references the settled `SALE` it reverses, and the platform computes the refund twice — once as an estimate at creation, once exactly at settlement. The reference itself is validated up front: the `original_sale_id` must be present, must point to a sale that is `SETTLED` and of `kind` `SALE`, and each `return_of_line_no` must map to an original line that has not already been fully returned. A missing, non-settled, wrong-kind, or over-returning reference is rejected with `ERR_INVALID_RETURN_REFERENCE`.

The **provisional** refund, shown as the estimated `total_due_cents` at creation, is built line by line: for each return line, the original line's effective unit price — its original net amount (post-discount, post-redemption) divided by its original quantity and floored per unit — is multiplied by the returned quantity, and its proportional original tax is added; these per-line figures are summed. This estimate floors each unit independently and therefore ignores how a basket-level promotion or loyalty redemption was originally distributed.

The **final** refund, computed when the return's tender capture closes it, is a basket recomputation. The system re-runs the original sale's pricing with the returned units removed and takes the difference between the original total due and that recomputed total due without the returned units. This delta method captures exactly the promo and loyalty interaction that the per-unit floor cannot, so the two figures diverge whenever the original sale carried a promotion — especially `BOGO_50` or `AMOUNT_OFF` — or a loyalty redemption. The final refund is the authoritative amount settled.

### 3.8. Loyalty Earning, Tiers, and Clawback

A `StoreManager` or `Cashier` enrolls a member by creating a `LoyaltyAccount` with a `customer_name` and a `phone` that is unique across all accounts; a duplicate phone is an `ERR_DUPLICATE_RESOURCE`. A new account opens with `points_balance` and `lifetime_points` at zero and `tier` at `STANDARD`. The account's `points_balance` is the redeemable balance, earned on settled sales, debited on redemption, and restored on return; `lifetime_points` is the cumulative total ever earned, never decremented, and it alone drives the tier. For test setup, a `StoreManager` may grant points directly by supplying a `loyalty_account_id` and a number of points in `add_points`; the grant adds to both `points_balance` and `lifetime_points` and recomputes the tier.

Earning runs at the settlement of a `SALE`. The eligible net is the sum, over the lines flagged `loyalty_eligible`, of each line's proportional share of the post-discount-minus-redemption amount — allocated in proportion to the line's pre-discount extended price, the same allocation basis used for tax, floored per line and then summed. Base points are that eligible net multiplied by the store's `loyalty_earn_rate_bps`, divided by ten thousand, floored. A tier multiplier then applies to the earn side only: a `SILVER` account multiplies the base points by 1.25 (that is, by 125 percent, floored after the multiply), and a `GOLD` account multiplies by 1.50 (150 percent, floored after the multiply); a `STANDARD` account earns the base unchanged. The resulting `points_earned` credits both `points_balance` and `lifetime_points`.

The tier is recomputed from `lifetime_points` on every change, against inclusive thresholds: `lifetime_points` at or above 5000 is `GOLD`; at or above 1000 (but below 5000) is `SILVER`; below 1000 is `STANDARD`. The boundaries are inclusive — exactly 1000 lifetime points is `SILVER`, exactly 5000 is `GOLD`, and 999 is `STANDARD`. On a `RETURN` settlement against the original sale, the points originally earned for the returned units are clawed back from `points_balance` only — `lifetime_points` is left untouched, so the multiplier never downgrades a member's tier — and any points the original sale had redeemed are restored to `points_balance`.

### 3.9. Layaway: Reserving Goods and the Payment Loop

A `Cashier` or `StoreManager` parks goods for a member by creating a `Layaway` against a `store_id`, `product_id`, and `customer_id` (the owning loyalty member), with a `quantity` of at least one and a `due_date` by which the balance must be fully paid. An optional `initial_deposit_cents` may seed the first deposit. Creation locks the price: `total_price_cents` is the product's `list_price_cents` times the `quantity` at the moment of creation, `deposit_paid_cents` starts at the seeded amount (or zero), and `balance_cents` is the total minus deposits paid. Creating a layaway reserves stock — the item's `reserved_qty` is increased by the `quantity`, and `available_qty` and `below_reorder` are recomputed — which requires `available_qty` to be at least the requested `quantity`; insufficient stock is rejected with `ERR_INSUFFICIENT_STOCK`. A new layaway is `ACTIVE`. The layaway list endpoint filters by `store_id`, `product_id`, `customer_id`, and `status`.

Deposits drive a cyclic payment loop. A `Cashier` records a deposit with an `amount_cents` and the OCC field `expected_layaway_version`; each deposit raises `deposit_paid_cents` and recomputes `balance_cents`, and increments the layaway's `version` by one. The status moves with the balance. While `ACTIVE`, if the clock advances past the `due_date` while `balance_cents` is still above zero, the layaway moves `ACTIVE → DELINQUENT` (reservation retained, further deposits still accepted). A deposit recorded while `DELINQUENT` that leaves `balance_cents` still above zero moves it back `DELINQUENT → ACTIVE`. From either `ACTIVE` or `DELINQUENT`, a deposit that brings `balance_cents` to exactly zero fulfills the layaway, moving it to `FULFILLED`: the reserved units leave with the customer, so the item's `reserved_qty` is decremented by the `quantity` and its `on_hand_qty` is also decremented by the `quantity`, with `available_qty` and `below_reorder` recomputed.

Two manager overrides close a layaway short. A `StoreManager` may forfeit a layaway, but only while it is `DELINQUENT`; a forfeit attempted on a layaway that is not `DELINQUENT` is rejected with `ERR_LAYAWAY_NOT_DELINQUENT`. On forfeit the layaway moves to `FORFEITED`: the `reserved_qty` is decremented by the `quantity` while `on_hand_qty` is unchanged (the goods return to the sellable floor), `available_qty` is recomputed, and the deposits paid are retained by the store with no refund. A `StoreManager` may cancel a layaway only while it is `ACTIVE`, moving it to `CANCELLED`: the `reserved_qty` is decremented by the `quantity`, `available_qty` and `below_reorder` are recomputed, and the deposits paid are refunded to the customer (recorded, not modeled as a tender). A forfeit or cancel requested against a state the layaway cannot leave is otherwise rejected with `ERR_INVALID_STATE`.

### 3.10. Multi-Store Transfers

An `InventoryClerk` or `StoreManager` requests a `Transfer` to move stock between stores, naming a `from_store_id`, a `to_store_id`, a `product_id`, and a `quantity` of at least one. The transfer begins `REQUESTED` and places no stock effect yet.

From `REQUESTED`, an `InventoryClerk` dispatches the transfer, supplying `expected_transfer_version`; dispatch requires the source inventory item at (`from_store_id`, `product_id`) to exist with `available_qty` at least the `quantity`, failing which it is rejected with `ERR_INSUFFICIENT_STOCK`. On dispatch the transfer moves `REQUESTED → DISPATCHED`, the source item's `reserved_qty` is increased by the `quantity`, and its `available_qty` and `below_reorder` are recomputed; the transfer's `version` increments by one.

A dispatched transfer forks two ways at the destination. To receive it, an `InventoryClerk` supplies `received_qty` between zero and the original `quantity` inclusive, and the destination inventory item at (`to_store_id`, `product_id`) must exist; the transfer moves `DISPATCHED → RECEIVED`. On receive, the source item's `on_hand_qty` and `reserved_qty` are each decremented by the original `quantity` (with its `available_qty` and `below_reorder` recomputed), and the destination item's `on_hand_qty` is increased by the `received_qty` (with its `available_qty` and `below_reorder` recomputed). Any shortfall — the original `quantity` minus the `received_qty` — is shrinkage that is written off and lands nowhere. Alternatively, an `InventoryClerk` may reject a dispatched transfer, moving it `DISPATCHED → REJECTED`, which returns the reserved units to the source floor by decrementing the source's `reserved_qty` by the `quantity` and recomputing `available_qty` and `below_reorder`. A still-`REQUESTED` transfer may instead be cancelled — by an `InventoryClerk` or a `StoreManager` — moving it `REQUESTED → CANCELLED` with no inventory effect, since the reservation was never placed; cancel is allowed only from `REQUESTED`. A transfer action requested against a transition the transfer cannot make is rejected with `ERR_INVALID_STATE`. The transfer list endpoint filters by `from_store_id`, `to_store_id`, `product_id`, and `status`.

### 3.11. Physical Counts and Reconciliation

An `InventoryClerk` audits a shelf by opening a `CountSheet` against an `inventory_item_id` with the physically `counted_qty`. Opening the sheet snapshots the item's current on-hand into `snapshot_on_hand_qty` and starts the sheet `DRAFT`. The count list endpoint filters by `inventory_item_id` and `status`.

Posting commits the count. A draft sheet may be posted only when the item has not moved since the sheet was opened — its current `on_hand_qty` must still equal `snapshot_on_hand_qty`; if stock has shifted in the meantime, the post is rejected with `ERR_COUNT_STALE`. On a clean post the sheet moves `DRAFT → POSTED`: the signed `variance_qty` is recorded as `counted_qty` minus `snapshot_on_hand_qty`, the item's `on_hand_qty` is overwritten to `counted_qty`, and its `available_qty` and `below_reorder` are recomputed. The new on-hand may sit below the item's reserved units only insofar as it does not drive `available_qty` negative. A clerk may instead discard a draft sheet, moving it `DRAFT → DISCARDED` with no inventory effect. A post or discard against a sheet not in `DRAFT` is rejected with `ERR_INVALID_STATE`.

### 3.12. The Logical Clock

An administrative test-driving capability lets a `StoreManager` advance the system's logical clock to a supplied instant by passing `to_iso8601`. Advancing the clock sets the current UTC and runs the layaway due-date sweep: every `ACTIVE` layaway whose `due_date` is now in the past and whose `balance_cents` remains above zero is moved `ACTIVE → DELINQUENT`. This is the only mechanism by which a layaway becomes delinquent.

### 3.13. Validation Ordering

When several checks could fire on one request, they are evaluated in a fixed priority so the most fundamental failure surfaces first. Authentication is checked before anything else: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Role authorization (`ERR_FORBIDDEN_ROLE`) comes next, then existence of every path-referenced resource (`ERR_NOT_FOUND`, validated left-to-right along the path), then resolution of every body foreign key (`ERR_REFERENCE_NOT_FOUND`). After those come body well-formedness — required fields present and well-typed, enums valid, quantities meeting their constraints (`ERR_INVALID_REQUEST`) — and then uniqueness collisions (`ERR_DUPLICATE_RESOURCE`). The optimistic-concurrency check (`ERR_STALE_VERSION`) is evaluated next, ahead of the general state-transition check (`ERR_INVALID_STATE`); a stale version is reported before an out-of-state transition. The drawer-posture gate on tendering (`ERR_DRAWER_NOT_OPEN`) follows the state check. The domain-specific guards then apply in order: the return-reference check (`ERR_INVALID_RETURN_REFERENCE`), promo applicability (`ERR_PROMO_NOT_APPLICABLE`), stacking (`ERR_PROMO_NOT_STACKABLE`), loyalty sufficiency (`ERR_INSUFFICIENT_POINTS`), stock availability (`ERR_INSUFFICIENT_STOCK`), over-tender (`ERR_OVERTENDER`), and the count-staleness check (`ERR_COUNT_STALE`).

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including the state-transition actions and the test-driving capabilities — return `200 OK`. The request body, response body, and side effects of each endpoint are not restated here; they are governed by the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/stores` | Create a store | StoreManager |
| GET | `/stores/{store_id}` | Read a store (includes derived posture) | StoreManager, Cashier, InventoryClerk, Customer |
| POST | `/cash-sessions` | Open a cash drawer session for a store | StoreManager |
| GET | `/cash-sessions/{id}` | Read a cash drawer session | StoreManager, Cashier |
| GET | `/cash-sessions` | List cash drawer sessions; filter by store_id, status | StoreManager, Cashier |
| POST | `/cash-sessions/{id}/request-close` | Freeze the session for reconciliation | StoreManager |
| POST | `/cash-sessions/{id}/reconcile` | Submit counted cash and reconcile | StoreManager |
| POST | `/cash-sessions/{id}/reopen` | Reopen a close-requested session | StoreManager |
| POST | `/cash-sessions/{id}/force-close` | Force-close a session, voiding and reversing unsettled bound sales | StoreManager |
| POST | `/products` | Create a catalog product | StoreManager, InventoryClerk |
| GET | `/products/{id}` | Read a product | StoreManager, Cashier, InventoryClerk, Customer |
| GET | `/products` | List/lookup products; filter by sku or barcode for scanning | StoreManager, Cashier, InventoryClerk, Customer |
| POST | `/products/{id}/discontinue` | Mark a product DISCONTINUED | StoreManager |
| POST | `/inventory-items` | Create per-store stock record for a product | InventoryClerk, StoreManager |
| GET | `/inventory-items/{id}` | Read an inventory item | StoreManager, Cashier, InventoryClerk |
| GET | `/inventory-items` | List inventory items; filter by store_id, product_id, below_reorder | StoreManager, Cashier, InventoryClerk |
| POST | `/count-sheets` | Open a count sheet snapshotting an item's on-hand | InventoryClerk |
| GET | `/count-sheets/{id}` | Read a count sheet | StoreManager, InventoryClerk |
| GET | `/count-sheets` | List count sheets; filter by inventory_item_id | StoreManager, InventoryClerk |
| POST | `/count-sheets/{id}/post` | Post a count sheet, overwriting on_hand_qty to counted_qty | InventoryClerk |
| POST | `/count-sheets/{id}/discard` | Discard a draft count sheet | InventoryClerk |
| POST | `/loyalty-accounts` | Enroll a loyalty member | StoreManager, Cashier |
| GET | `/loyalty-accounts/{id}` | Read a loyalty account | StoreManager, Cashier, Customer |
| POST | `/_loyalty/grant` | Test-driving: credit lifetime/balance points directly | StoreManager |
| POST | `/promotions` | Create a promotion | StoreManager |
| GET | `/promotions/{id}` | Read a promotion | StoreManager, Cashier |
| POST | `/promotions/{id}/disable` | Disable a promotion | StoreManager |
| POST | `/sales` | Create a sale/return/exchange in DRAFT; prices it | Cashier |
| GET | `/sales/{id}` | Read a sale | StoreManager, Cashier, Customer |
| GET | `/sales` | List sales; filter by store_id, settlement_status, cash_session_id, loyalty_account_id, original_sale_id | StoreManager, Cashier |
| PUT | `/sales/{id}/lines` | Replace lines on a DRAFT sale and reprice | Cashier |
| POST | `/sales/{id}/tenders` | Append a tender (split payment); may settle the sale | Cashier |
| GET | `/sales/{id}/tenders` | List tender lines for a sale | StoreManager, Cashier |
| POST | `/sales/{id}/void` | Void a non-settled sale, reversing tenders and reservations | Cashier |
| POST | `/layaways` | Create a layaway, reserving stock and locking price | Cashier, StoreManager |
| GET | `/layaways/{id}` | Read a layaway | StoreManager, Cashier, Customer |
| GET | `/layaways` | List layaways; filter by store_id, product_id, customer_id, status | StoreManager, Cashier, Customer |
| POST | `/layaways/{id}/payments` | Record a deposit; may settle (FULFILLED) or clear delinquency | Cashier, StoreManager |
| POST | `/layaways/{id}/forfeit` | Forfeit a delinquent layaway | StoreManager |
| POST | `/layaways/{id}/cancel` | Cancel an active layaway and refund deposit | StoreManager |
| POST | `/transfers` | Request a multi-store inventory transfer | InventoryClerk, StoreManager |
| GET | `/transfers/{id}` | Read a transfer | StoreManager, InventoryClerk |
| GET | `/transfers` | List transfers; filter by from_store_id, to_store_id, product_id, status | StoreManager, InventoryClerk |
| POST | `/transfers/{id}/dispatch` | Dispatch a transfer, reserving source stock | InventoryClerk |
| POST | `/transfers/{id}/receive` | Receive a dispatched transfer at destination | InventoryClerk |
| POST | `/transfers/{id}/reject` | Reject a dispatched transfer; return reserved units to source floor | InventoryClerk |
| POST | `/transfers/{id}/cancel` | Cancel a still-requested transfer | InventoryClerk, StoreManager |
| POST | `/_clock/advance` | Test-driving: set current UTC; sweeps layaways to DELINQUENT | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DRAWER_NOT_OPEN` | 409 |
| `ERR_INVALID_RETURN_REFERENCE` | 422 |
| `ERR_PROMO_NOT_APPLICABLE` | 422 |
| `ERR_PROMO_NOT_STACKABLE` | 422 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_OVERTENDER` | 422 |
| `ERR_COUNT_STALE` | 409 |
| `ERR_VALIDATION` | 400 |
| `ERR_LAYAWAY_NOT_DELINQUENT` | 409 |
