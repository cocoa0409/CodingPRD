# Hardware Lumber Yard API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Hardware Lumber Yard API, the back-office service that runs a combined hardware store and lumber yard in the style of a member-owned co-op retailer. The business it models is unusually broad for a single counter: the same staff sell discrete packaged goods and lumber cut to length, rent power equipment, mix paint and cut keys and exchange propane at service benches, place drop-ship special orders with suppliers, and carry net-term credit balances for contractor accounts that earn loyalty and co-op rebates. The API exists to keep all of these threads consistent with one another — so that fulfilling a sales order debits the right shelf stock, placing a net-term order reserves the right slice of a contractor's credit, and returning a rented auger bills the right number of days.

The central tension the system manages is that a finite pool of physical inventory and a finite pool of contractor credit are both competed for, provisionally committed, and later either settled or released. A sales order that has been placed but not yet fulfilled has reserved credit it has not yet spent; a lumber line priced by the foot must round to the cent before it is summed into an order total; a special order may be re-quoted several times before a contractor confirms it and locks the bill. Throughout, the API favors immediate consistency: derived balances, loyalty totals, and reorder flags are recomputed the moment the events that move them occur, rather than on a deferred schedule. The sections that follow define the global contracts every endpoint shares, the cross-cutting principles that govern money, stock, and concurrency, and the detailed business workflows for each part of the yard.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. The system recognizes exactly five roles, spelled precisely as follows: `SalesAssociate`, `RentalClerk`, `AccountsManager`, `InventoryManager`, and `Contractor`. If either header is missing, or `X-User-Role` is not one of these five known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

Four of the five roles are operator roles whose identity is opaque. When `X-User-Role` is `SalesAssociate`, `RentalClerk`, `AccountsManager`, or `InventoryManager`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it but does not compare it against any entity's `id`. The `SalesAssociate` runs the front counter — building and processing sales orders, booking and running service tickets, and drafting special orders and vendor quotes. The `RentalClerk` manages the tool-rental desk, its assets and agreements. The `AccountsManager` owns contractor accounts and net-term billing: invoicing, payments, voids, and suspensions. The `InventoryManager` owns the catalog, vendors, stock, service stations, and reorder/co-op purchasing.

The fifth role is entity-backed. When `X-User-Role` is `Contractor`, the `X-User-ID` is the `id` of the acting `ContractorAccount`; any ownership check on a resource that references a `ContractorAccount` compares that resource's `contractor_account_id` to `X-User-ID`, and a mismatch — a `Contractor` acting on or reading a resource that is not their own — is rejected with `ERR_UNAUTHORIZED` (this ownership check runs only after the resource's own existence has been confirmed, so a reference to a non-existent resource still yields `ERR_NOT_FOUND` first). A `Contractor` acts on their own special orders and views their own account, invoices, loyalty ledger, sales orders, and special orders.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result and defaults to 0, with no upper bound beyond the size of the collection. A `limit` outside the range 1 through 100, or a negative `offset`, is an invalid request and is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, every list is sorted by the resource's `created_at` timestamp in ascending order — oldest first. Because the logical clock (Section 3.11) does not advance on its own, many resources can share an identical `created_at`; such ties are broken deterministically by ascending creation order, so within an equal-timestamp group the earlier-created resource is listed first.

Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the full size of the matching set before the page window is applied and `has_more` indicates whether further items remain beyond the current window.

### 2.4. Common Resource Properties and Mutation Semantics

Every primary resource — `Vendor`, `Product`, `ContractorAccount`, `SalesOrder`, `OrderLine`, `Invoice`, `RentalAsset`, `RentalAgreement`, `ServiceStation`, `ServiceTicket`, `SpecialOrder`, and `PurchaseOrder` — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification, refreshed on every mutation. The `version` field is an integer that begins at its initial value on creation and increments by one on each mutation; it is the basis for optimistic concurrency control where that applies.

The one exception is the `LoyaltyLedger` entry, which is an immutable audit record. A loyalty-ledger entry carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field, because once minted it is never modified.

Whenever a derived value on a resource changes as a downstream effect of some other operation — for instance when a contractor account's `balance_cents` is recomputed after an invoice is issued, or when a product's `reorder_needed` flips after stock is debited — that recomputation is itself a mutation of the affected resource: its `updated_at` is refreshed and its `version` increments. State changes propagate immediately and synchronously within the handling of the triggering request.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several endpoints address a resource nested beneath a parent — for example the lines of a sales order, or an action taken on a specific rental agreement. When a path carries more than one identifier, the server validates existence left to right and rejects the request with `ERR_NOT_FOUND` against the first identifier in the path that does not resolve to an existing resource. The same `ERR_NOT_FOUND` applies whenever a body references a resource that does not exist — a `product_id` on a line, a `vendor_id` on a product, a `contractor_account_id` on an order, a `rental_asset_id` on an agreement, and so on. Existence checks of this kind run after authentication and authorization but before any business-rule evaluation.

### 2.6. Money, Precision, and Rounding

All monetary amounts are stored and returned as integer cents; there are no fractional-cent values anywhere in the system. Where a calculation produces a non-integer cents value before storage — a percentage-based loyalty discount or co-op rebate, or a by-the-foot lumber charge on a fractional length — the result is rounded to a whole number of cents using the round-half-up convention (a value whose fractional part is exactly one half rounds away from zero, upward). Counts that are not money, such as loyalty points and billed rental days, follow their own rounding rules stated with the relevant calculation.

A pricing subtlety that recurs throughout the order workflow: when an order total is assembled from several lines, each line's charge is rounded to the cent **first**, at the line level, and only then are the rounded line charges summed into the order subtotal. The order subtotal is therefore an exact sum of already-rounded integers, never a rounding of a running real-valued total.

### 2.7. Optimistic Concurrency on Sales Orders

Two sales-order transitions are guarded by optimistic concurrency control, because each one acts on a credit-exposure or stock-availability view that a competing writer could have invalidated. Both the place transition and the fulfill transition require the caller to supply `expected_sales_order_version` in the request body as a non-optional field carrying the `version` the client last observed on that `SalesOrder`. If `expected_sales_order_version` does not equal the order's current `version`, the transition is refused with `ERR_STALE_ORDER_VERSION` and HTTP status 412.

For the place transition, a stale version means the placing client computed its credit-exposure projection against an out-of-date view of the order — for example because the order's lifecycle was advanced by another writer after the client last read it — and so the placement is refused. For the fulfill transition, a stale version means a prior mutation (the order was just placed, or an earlier fulfill attempt already debited stock) has advanced the version since the client's read, leaving the client's stock-availability view stale, so the fulfillment is refused. No other endpoint accepts or requires a version field; in particular, adding an order line does not advance the order's `version`, so the version a client reads when it creates an order remains valid through that order's first placement.

### 2.8. Inventory Invariants and the Reorder Flag

On-hand stock is the system's other finite, contested resource, and it obeys a strict conservation invariant: every debit of `on_hand` at fulfillment is matched, on a compensating cancellation, by an exact restoration of the same quantity. Stock is never partially restored or double-counted. A product's `on_hand` is expressed in whole units when the product's `sell_mode` is `EACH` and in linear feet when its `sell_mode` is `BY_FOOT`. Whenever `on_hand` changes for any reason — product creation, a manual stock adjustment, the cascade of an order fulfillment, the restock of a cancelled order, or the receipt of a purchase order — the product's `reorder_needed` flag is recomputed: it is set true exactly when `on_hand` is at or below the product's `reorder_point` (the comparison is inclusive — equal to the reorder point counts as needing reorder), and false otherwise. A restock that lifts stock back above the reorder point therefore clears the flag.

### 2.9. The Contractor Credit Principle: Settled versus Committed Exposure

An `AccountsManager` opens a contractor account with a non-empty `business_name`, a `credit_limit_cents` (the maximum outstanding net-term balance permitted, at least 0), and a `net_terms_days` payment window that must be one of 0, 15, 30, 45, or 60 days; a new account begins `ACTIVE` with its derived balances and loyalty at 0, and the manager may later suspend it, moving its `status` to `SUSPENDED` — a state in which it accepts no new net-term orders. Each `ContractorAccount` carries three derived fields that the system keeps reconciled in real time, and the distinction between two of them is central to the credit model. The `balance_cents` is the account's **settled** outstanding balance: the sum of `amount_cents` over every `Invoice` on the account whose `status` is `ISSUED`. The `committed_cents` is the account's **provisional** exposure: it equals `balance_cents` plus the sum of `total_cents` over every `SalesOrder` on the account whose `fulfillment_status` is `PLACED` and whose `payment_status` is `UNBILLED`. The `loyalty_points` field is the sum of `delta_points` over every `LoyaltyLedger` entry on the account.

Two derived credit-availability views follow from these, and they are not interchangeable. The **settled available** credit is `credit_limit_cents` minus `balance_cents`. The **committed available** credit is `credit_limit_cents` minus `committed_cents`. Because committed exposure also counts the totals of placed-but-unbilled orders, the committed available credit can be strictly smaller than the settled available credit for the very same account data. The credit-ceiling decision on a new placement or special-order confirmation is taken against the settled `balance_cents` plus only the total being committed by this very operation — that is, the operation is refused when `balance_cents` plus this order's (or special order's) total would exceed `credit_limit_cents`; the already-counted totals of other placed-but-unbilled orders that feed `committed_cents` are not added a second time into this check. The settled view is also used at read time and for payment-side reasoning. When an account is fetched, its `balance_cents`, `committed_cents`, and `loyalty_points` are recomputed from the underlying invoices, orders, and ledger entries so the read reflects current truth.

### 2.10. Loyalty Tiers and Co-op Rebate Principles

Net-term contractor business is rewarded in two independent ways, both of which are pure derivations of amounts the system already tracks. The loyalty program grants a tiered discount on an order's subtotal and mints loyalty points when an order is fulfilled; cash sales — orders with no `contractor_account_id` — earn neither. The co-op buying program reduces the cost of qualifying purchase orders by a vendor-specific rebate fraction. The exact tier thresholds, rates, and minimums are stated where each calculation is described in Section 3, embedded in the workflow that triggers them.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Vendors and Products

The catalog rests on two foundations a `InventoryManager` maintains: vendors and the products they supply. A vendor is created with a display `name` (which must be non-empty), an optional `drop_ship_capable` flag indicating whether the vendor can fulfill special orders by drop-ship (defaulting to false), and an optional `coop_rebate_pct` giving the co-op buying rebate fraction applied to that vendor's purchase-order subtotals (defaulting to 0, and constrained to lie between 0 and 0.25 inclusive). A new vendor begins with `status` of `ACTIVE`; the manager may later move it to `INACTIVE` via a deactivate action.

A product is a single stock-keeping unit located at a bin. It is created with a `sku` (non-empty and unique across all products), a `vendor_id` naming its primary supplier, a `sell_mode` of either `EACH` (discrete units) or `BY_FOOT` (lumber sold by the linear foot), an `aisle` label and a `bin` label within that aisle, and the reorder parameters `reorder_point` (at or below which the product needs reordering, at least 0) and `reorder_qty` (the suggested replenishment quantity, which must be greater than 0). The pair of `aisle` and `bin` must be unique across products — no two SKUs may occupy the same bin location. Pricing inputs depend on the mode: `list_price_cents` is the per-unit price used when the mode is `EACH`, while `price_per_foot_cents` is the per-linear-foot price and `cut_fee_cents` the flat per-cut fee used when the mode is `BY_FOOT`; each of these is a non-negative integer and defaults to 0 where the mode does not require it. A creation attempt whose `sku` already exists, or whose `aisle` and `bin` pair is already taken, is rejected with `ERR_DUPLICATE_RESOURCE`; the same duplicate rule guards a rental asset's `asset_tag` on creation.

A newly created product starts with `on_hand` of 0, a `status` of `ACTIVE`, and `reorder_needed` recomputed from its starting stock against its reorder point per the inventory rule. The `InventoryManager` keeps stock current through a stock-adjustment action that takes a signed `delta`: the product's `on_hand` increases by `delta` (a negative delta reduces it), with the result floored at 0 so stock can never go negative, after which `reorder_needed` is recomputed. The manager may also discontinue a product, moving its `status` to `DISCONTINUED`; a discontinued SKU can no longer pass the active-product check on order placement or fulfillment. Products can be listed and filtered by `vendor_id`, by `reorder_needed`, and by `status`.

### 3.2. Building a Sales Order and Pricing Its Lines

A `SalesAssociate` opens a sales order, optionally naming a `contractor_account_id`. An order with no account is a cash sale: neither net terms nor loyalty applies to it. A fresh order begins with `fulfillment_status` of `DRAFT`, `payment_status` of `UNBILLED`, and `pricing_mode` of `PROVISIONAL`; its computed money fields — `subtotal_cents`, `loyalty_discount_cents`, `total_cents`, and `points_accrued` — all start at 0.

While the order is still `DRAFT`, the associate adds order lines, each carrying a `product_id`, a `qty`, and an optional `cut_count` (the number of cuts requested on lumber, defaulting to 0). The owning order is recorded on each line as `sales_order_id`. The `qty` must be greater than 0, and is interpreted as whole units when the line's product sells `EACH` and as linear feet (which may be fractional) when it sells `BY_FOOT`; `cut_count` must be at least 0 and is only meaningful for lumber. Adding a line is permitted only while the order is `DRAFT` — an attempt to add a line to an order that has already advanced to `PLACED` or beyond is rejected with `ERR_INVALID_STATE`. A new line is created in `status` `PENDING`.

Each line's charge, `line_total_cents`, is computed at creation and again on every order recompute. The computation branches on the product's sell mode. For an `EACH` product, the raw charge in cents is the product's `list_price_cents` multiplied by the line's `qty`. For a `BY_FOOT` product, the raw charge is the lumber component — the product's `price_per_foot_cents` multiplied by the `qty` in feet — plus the cut component, which is the product's `cut_fee_cents` multiplied by the line's `cut_count`. The raw charge is then rounded half-up to a whole number of cents to yield `line_total_cents`. This rounding happens at the line level, before the order ever sums its lines. Adding a line also recomputes the order's provisional `subtotal_cents`, `loyalty_discount_cents`, and `total_cents` as described below, but it does not change the order's `version`.

### 3.3. Placing an Order: Provisional Totals and Credit Commitment

Placing a draft order is the moment its provisional price and, for net-term orders, its credit commitment are locked in. A `SalesAssociate` triggers the placement, which advances `fulfillment_status` from `DRAFT` to `PLACED` while `pricing_mode` remains `PROVISIONAL`. The request must carry `expected_sales_order_version` matching the order's current `version` per the concurrency rule in Section 2.7; a mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412).

Several preconditions are checked before the order moves. The order must hold at least one line in `PENDING` status; an order with no pending lines is rejected as `ERR_EMPTY_ORDER`. Every line's product must be `ACTIVE`; if any line references a product whose `status` is `DISCONTINUED`, the placement is rejected with `ERR_PRODUCT_DISCONTINUED`. If the order names a contractor account, that account's `status` must be `ACTIVE`; placing against a `SUSPENDED` account is rejected with `ERR_ACCOUNT_SUSPENDED`. Also for net-term orders, the placement must not push committed exposure past the credit ceiling: if the account's settled `balance_cents` plus this order's `total_cents` would exceed `credit_limit_cents`, the placement is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. These business preconditions are evaluated in the priority order set out in Section 2.11.

The provisional total is recomputed at placement. The order's `subtotal_cents` is the sum, over the order's lines whose `status` is `PENDING`, of each line's already-rounded `line_total_cents` — restocked and fulfilled lines are excluded from the provisional sum. The `loyalty_discount_cents` is then derived from that subtotal against the loyalty tiers: for a cash sale (no account) the discount is 0; otherwise the discount rate is selected from the **pre-discount** subtotal, where a subtotal of at least 100000 cents earns a rate of 5 percent (0.05), a subtotal of at least 50000 but below 100000 cents earns a rate of 2 percent (0.02), and any smaller subtotal earns 0. The tier is fixed from the pre-discount subtotal first; the chosen rate is then multiplied by the subtotal and rounded half-up to whole cents to give the discount, which is never re-tiered against the post-discount figure. The order's `total_cents` is the subtotal minus the loyalty discount, floored at 0 so it can never be negative. On a successful placement the order's `version` increments by one, and for a net-term order the account's `committed_cents` is recomputed to reflect the now-placed order.

### 3.4. Fulfilling an Order: Stock Cascade, Final Pricing, and Loyalty Accrual

Fulfillment is where a placed order draws down physical stock and, for accounts, mints loyalty. A `SalesAssociate` triggers it, advancing `fulfillment_status` from `PLACED` to `FULFILLED`. As with placement, the request carries `expected_sales_order_version`, and a mismatch with the current `version` is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). Fulfillment is refused if the order's `payment_status` is `VOIDED`. Every line's product must still be `ACTIVE`, or the transition fails with `ERR_PRODUCT_DISCONTINUED`. For each `PENDING` line, the line's product must have `on_hand` at least equal to the line's `qty`; if any line cannot be covered, the fulfillment is rejected with `ERR_INSUFFICIENT_STOCK`.

When fulfillment proceeds, the order's `pricing_mode` flips to `FINAL` and its total is recomputed from the final variant. The final `subtotal_cents` sums `line_total_cents` over the order's lines whose `status` is `FULFILLED` (rather than `PENDING`); the loyalty discount and `total_cents` are then derived from that subtotal exactly as in the provisional calculation. The two variants share identical per-line figures but differ in their inclusion set, so an order in which some line never reaches `FULFILLED` can carry a different final total than its provisional total implied.

A depth-three cascade then runs. Each `PENDING` line moves to `status` `FULFILLED`; that transition debits the line's product `on_hand` by the line's `qty`; and that change to `on_hand` recomputes the product's `reorder_needed` flag, flipping it true when stock has fallen to or below the reorder point. Finally, for a net-term order only, loyalty is accrued: the system mints a `LoyaltyLedger` entry with `reason` `ORDER_ACCRUAL` whose `delta_points` is the order's `total_cents` divided by 100 and floored to a whole number of points (one point per whole dollar, with fractional cents dropped), references the originating order via `sales_order_id`, and sets the order's `points_accrued` to that same value; the account's `loyalty_points` is recomputed afterward. Cash sales accrue 0 points and mint no ledger entry. The order's `version` increments by one on fulfillment.

### 3.5. Cancelling an Order: Compensating Restock and Loyalty Reversal

A `SalesAssociate` may cancel an order from either `PLACED` or `FULFILLED`, provided it has not been billed. The billing guard comes first: an order may only be cancelled while its `payment_status` is `UNBILLED`; a cancel attempt on an order that has been invoiced, paid, or voided is rejected with `ERR_ORDER_ALREADY_BILLED`. A successful cancel moves `fulfillment_status` to `CANCELLED`.

The compensating effects depend on how far the order had progressed. Cancelling a `PLACED` order moves all of its lines to `status` `RESTOCKED`; because a placed order never debited stock, no `on_hand` change occurs, and for a net-term order the account's `committed_cents` is recomputed since the order is no longer counted as placed. Cancelling a `FULFILLED` order is a fuller compensation: each `FULFILLED` line moves to `RESTOCKED` and restores its product's `on_hand` by exactly the line's `qty` — preserving the inventory conservation invariant — after which each affected product's `reorder_needed` is recomputed; and if loyalty points had been accrued, the system mints a `LoyaltyLedger` entry with `reason` `ORDER_REVERSAL` whose `delta_points` is the negative of the order's `points_accrued`, the account's `loyalty_points` is recomputed, and the order's `points_accrued` is reset to 0. In either case the order's `version` increments by one.

### 3.6. Net-Term Billing: Invoicing, Payment, and Voids

Payment evolves on an axis independent of fulfillment, and only an `AccountsManager` drives it. Issuing an invoice advances `payment_status` from `UNBILLED` to `INVOICED`. Two preconditions guard it: the order's `fulfillment_status` must be `FULFILLED`, since an unfulfilled order cannot be invoiced (rejected `ERR_ORDER_NOT_FULFILLED`); and the order must name a contractor account, since cash sales are never invoiced (rejected `ERR_NOT_NET_TERM_ORDER`). Issuing the invoice creates an `Invoice` whose `amount_cents` is copied from the order's `total_cents`, whose `sales_order_id` and `contractor_account_id` record the billed order and account, whose `status` is `ISSUED`, and whose `due_at` is the current clock time plus the account's `net_terms_days` days. Because the new invoice is `ISSUED`, the account's `balance_cents` is recomputed to include it, and the order's `version` increments.

Marking an invoiced order paid advances `payment_status` from `INVOICED` to `PAID`. There must be an `ISSUED` invoice on the order, or the request is rejected with `ERR_INVOICE_NOT_FOUND`. The invoice's `status` moves to `PAID`, which drops it out of the issued-invoice sweep, so the account's `balance_cents` is recomputed downward; the order's `version` increments. Voiding an invoice is the compensating money operation: from `INVOICED` it moves `payment_status` to `VOIDED`, again requiring an `ISSUED` invoice on the order (else `ERR_INVOICE_NOT_FOUND`), setting the invoice's `status` to `VOID`, and recomputing the account's `balance_cents` back to exactly its pre-invoice value. The order's `version` increments. Invoices and loyalty-ledger entries are both reverse-reachable: invoices can be listed by `sales_order_id` and filtered by `status`, and a contractor's invoices and loyalty ledger can be listed from the account.

### 3.7. Tool Rentals: Reservation, Checkout, Return, and Day Billing

The rental desk turns on a half-open interval model. A `RentalClerk` (or, for asset creation, an `InventoryManager`) registers a rental asset with an `asset_tag` (non-empty and unique across assets), a `category` label such as AUGER or TILLER, a `daily_rate_cents` (greater than 0) charged per started rental day, and a refundable `deposit_cents` (at least 0) held during the rental. A new asset's `status` is `AVAILABLE`. The clerk may flag an asset for maintenance through a set-maintenance action taking a boolean `maintenance`: a true value moves `status` to `MAINTENANCE` (a state from which the asset cannot be reserved), and a false value returns it to `AVAILABLE` when it is not currently rented.

A reservation is created against an asset for the half-open interval from `start_at` (inclusive) to `due_at` (exclusive); `due_at` must be strictly after `start_at`. The agreement records the `rental_asset_id`, an optional `contractor_account_id` (absent for a cash renter), and begins in `status` `RESERVED` with `returned_at` unset and `rental_charge_cents` at 0. The reservation is rejected with `ERR_RENTAL_OVERLAP` if its interval overlaps any non-terminal agreement already on the same asset; because the interval is half-open, two agreements that meet exactly end-to-start do not overlap and are both allowed.

Checking out a reserved agreement advances it from `RESERVED` to `CHECKED_OUT`. The asset must be `AVAILABLE` at checkout, or the request is rejected with `ERR_ASSET_UNAVAILABLE`, and the clock must have reached the reservation's `start_at`, or it is rejected with `ERR_RENTAL_NOT_STARTED`. On checkout the asset's `status` moves to `RENTED`. Returning a checked-out agreement advances it from `CHECKED_OUT` to `RETURNED`: the agreement's `returned_at` is set to the current clock time (which is at or after `start_at`), the rental charge is computed, and the asset's `status` returns to `AVAILABLE`, freeing the interval. The `rental_charge_cents` is the asset's `daily_rate_cents` multiplied by the number of billed days, where billed days counts every distinct started UTC calendar day the asset was out: a same-day return bills 1 day, crossing one midnight bills 2 days, and a zero-length window where the return instant equals `start_at` bills a minimum of 1 day. Concretely, billed days is the number of whole calendar dates spanned from the start date through the return date inclusive, but never fewer than 1. A reserved agreement that has not been checked out may be cancelled, moving it from `RESERVED` to `CANCELLED` and freeing its interval; a checked-out rental cannot be cancelled, and the attempt is rejected with `ERR_INVALID_STATE`. Agreements are reverse-reachable by `rental_asset_id` and by `contractor_account_id`.

### 3.8. Service Bench Operations: Stations and Tickets

The store's service benches — paint mixing, key cutting, propane exchange — are modeled as stations and tickets. An `InventoryManager` creates a service station with a `name` (non-empty) and an optional `buffer_minutes`, the mandatory clean-down buffer in minutes that must separate two tickets on that station (defaulting to 0, at least 0). A station begins `ACTIVE`; the manager can take it offline or bring it back online through a set-offline action taking a boolean `offline`, where true moves `status` to `OFFLINE` and false returns it to `ACTIVE`. An offline station accepts no new work.

A `SalesAssociate` books a service ticket on a station, supplying the `service_station_id`, an optional `contractor_account_id` (absent for a cash customer), a `service_type` of `KEY_CUT`, `PAINT_MIX`, or `PROPANE_EXCHANGE`, an optional `cylinder_certified` boolean (whether the customer-supplied propane cylinder passed certification, defaulting to false), and the appointment window from `scheduled_start` (inclusive) to `scheduled_end` (exclusive), where `scheduled_end` must be strictly after `scheduled_start`. A ticket begins in `status` `BOOKED` with `fee_cents` at 0. The booking is checked for conflicts against the station: the requested window, expanded by the station's `buffer_minutes` on both ends, must not overlap any non-terminal ticket on that station, or the booking is rejected with `ERR_STATION_BOOKING_CONFLICT`. A cancellation of a booked ticket frees this same buffer-expanded reservation window on the station.

Starting a ticket advances it from `BOOKED` to `IN_PROGRESS`. The station must be `ACTIVE`, or the start is rejected with `ERR_STATION_OFFLINE`. A safety rule guards propane: a ticket whose `service_type` is `PROPANE_EXCHANGE` may only start when its `cylinder_certified` is true; otherwise the start is rejected with `ERR_CYLINDER_NOT_CERTIFIED`. Tickets of the other service types are unaffected by the cylinder rule. On a successful start the ticket's `fee_cents` is set from a fixed base-fee table keyed on `service_type`: a `KEY_CUT` is 300 cents, a `PAINT_MIX` is 800 cents, and a `PROPANE_EXCHANGE` is 2499 cents. Completing a ticket advances it from `IN_PROGRESS` to `COMPLETED`; if the ticket names a contractor account, its fee contributes to a follow-on cash settlement that has no effect on the account balance, and services never mint loyalty. A booked ticket may instead be cancelled, moving it from `BOOKED` to `CANCELLED` and freeing its window. Tickets are reverse-reachable by `service_station_id` and by `contractor_account_id`.

### 3.9. Special Orders: The Quote–Revision Loop and Drop-Ship Confirmation

Special orders capture drop-ship items a vendor supplies directly to the contractor. A `SalesAssociate` or a `Contractor` opens a special order in `status` `DRAFT`, naming the drop-ship `vendor_id`, the `contractor_account_id` placing it, a non-empty `description` of the item, and a `qty` greater than 0. The `quoted_unit_cents` starts at 0, `revision_count` at 0, and `confirmed_total_cents` at 0.

A `SalesAssociate` quotes the order, supplying a `quoted_unit_cents` (at least 0) that is stored on the order. Quoting is allowed both from `DRAFT` and from `REVISION_REQUESTED`, and in both cases the vendor must be `ACTIVE` and have `drop_ship_capable` true, or the quote is rejected with `ERR_VENDOR_NOT_DROP_SHIP`. A quote from `DRAFT` simply moves the order to `QUOTED` and stores the price. A `Contractor` who is not satisfied can request a revision, moving a `QUOTED` order to `REVISION_REQUESTED` with no charge; a subsequent quote moves it from `REVISION_REQUESTED` back to `QUOTED`, increments `revision_count` by one, and stores the new `quoted_unit_cents`. This loop may repeat any number of times before confirmation.

A `Contractor` confirms a `QUOTED` order, moving it to `CONFIRMED`. The account must be `ACTIVE`, or the confirm is rejected with `ERR_ACCOUNT_SUSPENDED`, and the confirmation must not push committed exposure past the ceiling: if `balance_cents` plus the projected confirmed total would exceed `credit_limit_cents`, it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. On confirmation the `confirmed_total_cents` is locked: it is the goods value (`quoted_unit_cents` multiplied by `qty`) plus a drop-ship surcharge, where the surcharge is 0 when the goods value is at least 50000 cents (free shipping at or above that threshold) and 1500 cents otherwise. Confirmation also runs a depth-two cascade: it creates an `Invoice` whose `amount_cents` equals `confirmed_total_cents`, whose `contractor_account_id` records the owning account, whose `status` is `ISSUED`, whose `due_at` is the current clock time plus the account's `net_terms_days` days, and whose `sales_order_id` is `null` (a special-order invoice bills no `SalesOrder`); the owning account's `balance_cents` is recomputed to include the new invoice. From `CONFIRMED`, an `InventoryManager` marks the order `RECEIVED` with no inventory change, since drop-ship goods go straight to the contractor. A `Contractor` may cancel a special order while it is in `DRAFT`, `QUOTED`, or `REVISION_REQUESTED`, moving it to `CANCELLED`; a `CONFIRMED` order can no longer be cancelled, and the attempt is rejected with `ERR_INVALID_STATE`. Special orders are reverse-reachable by `vendor_id` and by `contractor_account_id`.

### 3.10. Replenishment: Purchase Orders and Co-op Rebates

Reordering is handled with purchase orders, which an `InventoryManager` raises against a vendor and which also carry the co-op buying rebate. A purchase order is drafted with a `vendor_id` and a `lines` array, where each line is an object holding a `product_id` (which must resolve to an existing product, else `ERR_NOT_FOUND`), a `qty` (a number greater than 0), and a `unit_cost_cents` (an integer at least 0); at draft only the existence of the vendor and of each line's product is checked, while the stronger rule that every line's product must be one the named vendor actually supplies is not enforced until submit (see below). The order begins in `status` `DRAFT` with computed money fields — `gross_cents`, `coop_rebate_cents`, and `net_cost_cents` — at 0.

Submitting a draft purchase order advances it from `DRAFT` to `SUBMITTED`. The vendor must be `ACTIVE`, or the submit is rejected with `ERR_VENDOR_INACTIVE`; that same error also rejects a submit whose lines reference a product not supplied by the vendor. The `lines` array must be non-empty, or the submit is rejected with `ERR_EMPTY_PURCHASE_ORDER`. On submit the cost figures are locked: `gross_cents` is the sum over the lines of each line's `qty` multiplied by its `unit_cost_cents`; the `coop_rebate_cents` is the gross multiplied by the vendor's `coop_rebate_pct` and rounded half-up to whole cents, but only when `gross_cents` is at least 200000 cents — below that minimum the rebate is 0; and `net_cost_cents` is `gross_cents` minus `coop_rebate_cents`. Receiving a submitted purchase order advances it from `SUBMITTED` to `RECEIVED` and restocks the catalog: for each line the line's product `on_hand` increases by the line's `qty`, and that product's `reorder_needed` is recomputed, which may clear the flag now that stock has risen. A draft or submitted purchase order may be cancelled, moving it to `CANCELLED`. Purchase orders are reverse-reachable by `vendor_id` and filterable by `status`.

### 3.11. Cross-Cutting Validation Order and the Logical Clock

When several checks could apply to one operation, they are evaluated in a fixed priority sequence so that the resulting error is deterministic. Authentication comes first: missing or unknown-role headers yield `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. Existence is third: any unresolved path or body resource yields `ERR_NOT_FOUND`, with path identifiers validated left to right. Request validity is fourth: missing or mistyped required fields, illegal enum values, out-of-range numbers (such as a `qty` not greater than 0 or a cents value below 0), and out-of-range pagination parameters all yield `ERR_INVALID_REQUEST`. Uniqueness on create (a product's `sku`, the `aisle`-and-`bin` pair, a rental asset's `asset_tag`) yields `ERR_DUPLICATE_RESOURCE`. Only after these do the state and business rules run: the general guard that a requested transition must be defined from the resource's current state yields `ERR_INVALID_STATE`, and the domain-specific guards described throughout this section — billing, fulfillment readiness, station availability, empty-order, propane safety, vendor referential integrity, product discontinuation, account suspension, rental and station overlap, stock sufficiency, credit limit, and finally the optimistic-concurrency version check — apply on the endpoints that declare them. Where a single operation could trip more than one of these, the earlier-listed condition surfaces first so that, for example, an authentication failure is never masked by a later business check.

A logical clock governs every temporal rule in the system — rental day counting, invoice `due_at` computation, and the rental-start gate. The server's clock starts at a fixed default of midnight UTC on the first of January 2026 and, until it is explicitly set, reads exactly that default and never falls back to wall-clock time. An operator role may advance the clock to a supplied instant through an administrative test-driving capability that takes a `to_iso8601` value; advancing the clock affects how rental days are counted, what due dates invoices receive, and whether a reservation has reached its start.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify or transition an existing resource, including the action endpoints that drive state machines, return a `200 OK` status code. All endpoints are mounted at the API root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vendors` | Create a vendor | InventoryManager |
| GET | `/vendors/{id}` | Fetch a vendor | InventoryManager, SalesAssociate, AccountsManager, RentalClerk |
| POST | `/vendors/{id}/deactivate` | Set vendor status INACTIVE | InventoryManager |
| POST | `/products` | Create a SKU at a bin/aisle | InventoryManager |
| GET | `/products/{id}` | Fetch a product | InventoryManager, SalesAssociate, AccountsManager, RentalClerk |
| GET | `/products` | List/filter products | InventoryManager, SalesAssociate |
| POST | `/products/{id}/adjust-stock` | Adjust on_hand | InventoryManager |
| POST | `/products/{id}/discontinue` | Set product status DISCONTINUED | InventoryManager |
| POST | `/contractor-accounts` | Open a contractor net-terms account | AccountsManager |
| GET | `/contractor-accounts/{id}` | Fetch account with derived balances | AccountsManager, SalesAssociate, Contractor |
| POST | `/contractor-accounts/{id}/suspend` | Suspend an account | AccountsManager |
| GET | `/contractor-accounts/{id}/loyalty-ledger` | List the account's loyalty ledger entries | AccountsManager, Contractor |
| GET | `/contractor-accounts/{id}/invoices` | List invoices billed to this account | AccountsManager, Contractor |
| POST | `/sales-orders` | Create a DRAFT sales order | SalesAssociate |
| GET | `/sales-orders/{id}` | Fetch a sales order | SalesAssociate, AccountsManager, Contractor |
| GET | `/sales-orders` | List/filter sales orders | SalesAssociate, AccountsManager, Contractor |
| POST | `/sales-orders/{id}/lines` | Add an order line | SalesAssociate |
| GET | `/sales-orders/{id}/lines` | List the order's lines | SalesAssociate, AccountsManager, Contractor |
| GET | `/order-lines/{id}` | Fetch a single order line | SalesAssociate, AccountsManager, Contractor |
| GET | `/order-lines` | List/filter order lines | SalesAssociate, AccountsManager, InventoryManager |
| POST | `/sales-orders/{id}/place` | Place a DRAFT order | SalesAssociate |
| POST | `/sales-orders/{id}/fulfill` | Fulfill a PLACED order | SalesAssociate |
| POST | `/sales-orders/{id}/cancel` | Cancel a PLACED or FULFILLED unbilled order | SalesAssociate |
| POST | `/sales-orders/{id}/invoice` | Issue a net-term invoice | AccountsManager |
| POST | `/sales-orders/{id}/pay` | Mark the order's issued invoice paid | AccountsManager |
| POST | `/sales-orders/{id}/void-invoice` | Void the order's issued invoice | AccountsManager |
| GET | `/invoices/{id}` | Fetch an invoice | AccountsManager, Contractor |
| GET | `/invoices` | List/filter invoices | AccountsManager, Contractor |
| GET | `/loyalty-ledger/{id}` | Fetch a single loyalty-ledger entry | AccountsManager, Contractor |
| GET | `/loyalty-ledger` | List/filter loyalty-ledger entries | AccountsManager, Contractor |
| POST | `/rental-assets` | Register a rentable asset | RentalClerk, InventoryManager |
| GET | `/rental-assets/{id}` | Fetch a rental asset | RentalClerk, InventoryManager |
| POST | `/rental-assets/{id}/set-maintenance` | Flag an asset for maintenance | RentalClerk, InventoryManager |
| POST | `/rental-agreements` | Reserve an asset | RentalClerk |
| GET | `/rental-agreements/{id}` | Fetch a rental agreement | RentalClerk, Contractor |
| GET | `/rental-agreements` | List/filter agreements | RentalClerk, Contractor |
| POST | `/rental-agreements/{id}/check-out` | Check out a reserved asset | RentalClerk |
| POST | `/rental-agreements/{id}/return` | Return a checked-out asset | RentalClerk |
| POST | `/rental-agreements/{id}/cancel` | Cancel a reservation before checkout | RentalClerk |
| POST | `/service-stations` | Create a service station | InventoryManager |
| GET | `/service-stations/{id}` | Fetch a service station | InventoryManager, SalesAssociate |
| POST | `/service-stations/{id}/set-offline` | Take a station offline / back online | InventoryManager |
| POST | `/service-tickets` | Book a service ticket | SalesAssociate |
| GET | `/service-tickets/{id}` | Fetch a service ticket | SalesAssociate, Contractor |
| GET | `/service-tickets` | List/filter tickets | SalesAssociate, Contractor |
| POST | `/service-tickets/{id}/start` | Start service | SalesAssociate |
| POST | `/service-tickets/{id}/complete` | Complete a service ticket | SalesAssociate |
| POST | `/service-tickets/{id}/cancel` | Cancel a booked ticket | SalesAssociate |
| POST | `/special-orders` | Open a drop-ship special order | SalesAssociate, Contractor |
| GET | `/special-orders/{id}` | Fetch a special order | SalesAssociate, Contractor, InventoryManager |
| GET | `/special-orders` | List/filter special orders | SalesAssociate, Contractor, InventoryManager |
| POST | `/special-orders/{id}/quote` | Vendor quote | SalesAssociate |
| POST | `/special-orders/{id}/request-revision` | Request a re-quote | Contractor |
| POST | `/special-orders/{id}/confirm` | Confirm a quote — locks total, bills account | Contractor |
| POST | `/special-orders/{id}/receive` | Mark drop-ship received | InventoryManager |
| POST | `/special-orders/{id}/cancel` | Cancel a non-confirmed special order | Contractor |
| POST | `/purchase-orders` | Draft a reorder / co-op PO | InventoryManager |
| GET | `/purchase-orders/{id}` | Fetch a purchase order | InventoryManager |
| GET | `/purchase-orders` | List/filter POs | InventoryManager |
| POST | `/purchase-orders/{id}/submit` | Submit a PO | InventoryManager |
| POST | `/purchase-orders/{id}/receive` | Receive a submitted PO | InventoryManager |
| POST | `/purchase-orders/{id}/cancel` | Cancel a draft/submitted PO | InventoryManager |
| POST | `/_clock/set_current_utc` | Set the server logical clock | InventoryManager, AccountsManager, RentalClerk, SalesAssociate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_ALREADY_BILLED` | 409 |
| `ERR_ORDER_NOT_FULFILLED` | 409 |
| `ERR_NOT_NET_TERM_ORDER` | 409 |
| `ERR_EMPTY_ORDER` | 409 |
| `ERR_CYLINDER_NOT_CERTIFIED` | 409 |
| `ERR_STATION_OFFLINE` | 409 |
| `ERR_VENDOR_NOT_DROP_SHIP` | 409 |
| `ERR_VENDOR_INACTIVE` | 409 |
| `ERR_PRODUCT_DISCONTINUED` | 409 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_RENTAL_OVERLAP` | 409 |
| `ERR_RENTAL_NOT_STARTED` | 409 |
| `ERR_ASSET_UNAVAILABLE` | 409 |
| `ERR_STATION_BOOKING_CONFLICT` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 |
| `ERR_INVOICE_NOT_FOUND` | 409 |
| `ERR_EMPTY_PURCHASE_ORDER` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
