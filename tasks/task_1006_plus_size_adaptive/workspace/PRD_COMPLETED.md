# Plus-Size & Adaptive-Clothing Retail API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Plus-Size & Adaptive-Clothing Retail platform, a commerce system built for shoppers whose needs are poorly served by conventional apparel channels. The platform treats extended sizing and adaptive construction — magnetic closures, seated cuts, sensory-friendly fabrics, one-handed dressing, and medical port access — as first-class catalog dimensions rather than afterthoughts, so that a customer can browse strictly for the garments that fit both their body and their functional requirements. Around that catalog the system layers the operational machinery of a modern retailer: inventory reservation, a two-dimensional order lifecycle that tracks payment and fulfillment independently, an extended-sizing return and exchange desk, a curated subscription-box program, a loyalty ledger with tiered discounts and store credit, and a virtual fit-specialist styling service.

The API serves four constituencies. Anonymous visitors browse the catalog and register. Registered customers shop, book styling appointments, manage subscriptions, and initiate returns against their own resources. Fit specialists confirm and run styling appointments and curate subscription boxes. Store managers operate the back office — catalog, inventory, fulfillment, settlement, returns adjudication, customer standing, and the platform's logical clock. Because many of the platform's rules are time-sensitive (return windows, try-on windows, appointment overlap, late-cancellation fees), the system runs on a server-controlled logical clock rather than wall-clock time; this makes every temporal rule deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. Where a business workflow in Section 3 depends on one of these principles, it is assumed rather than repeated.

### 2.1. User and Role-Based Access Control

Every request is authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly four roles: `Anonymous`, `Customer`, `FitSpecialist`, and `StoreManager`. A request that omits `X-User-Role`, or that carries a value which is not one of these four role names, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation — or whose principal fails an ownership check described below — is rejected with `ERR_UNAUTHORIZED`. Two operations are open to `Anonymous`: registering a new customer, and read-only browsing of the catalog (product listings, individual products, a product's variants, and individual variants).

Ownership is resolved from the acting role's identity model. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; every customer-owned resource carries a foreign key back to that customer, and ownership checks compare the resource's owning-customer reference to `X-User-ID`. A `Customer` may act only on their own orders, order lines, returns, appointments, subscriptions, and box shipments. When `X-User-Role` is `FitSpecialist`, `X-User-ID` is the `id` of the acting `FitSpecialist`; a specialist's authority over an appointment is tied to that appointment's assigned specialist reference, again compared against `X-User-ID`. When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server accepts and may log it but never compares it to any entity's `id`, because a store manager operates across all customers' resources. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque, non-entity identifier used only to satisfy the header contract for registration and browsing.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 — a supplied value below 1 is clamped up to 1 and a value above 100 is clamped down to 100 rather than rejected. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_VALIDATION`. Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full unpaginated result set and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties

Most resources in the system share a common set of server-managed fields. Every such resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, expressed as an ISO 8601 UTC value with three fractional digits, recording when the resource first came into being. Resources that can change after creation additionally carry an `updated_at` timestamp, refreshed on every mutation, and a `version` integer that starts at 1 and increments by one on each mutation. The `version` field doubles as the basis for optimistic concurrency control where the platform enforces it (see §2.5).

There is one deliberate exception. An `OrderLine` is an immutable snapshot: once added to an order it is never independently edited, so it carries only `id` and `created_at`. It has no `updated_at` and no `version` field. Every other entity — `Customer`, `FitSpecialist`, `Product`, `ProductVariant`, `StylingAppointment`, `Order`, `ReturnRequest`, `BoxSubscription`, and `BoxShipment` — carries the full complement of `id`, `created_at`, `updated_at`, and `version`. Whenever a server-side cascade mutates a resource that a client did not directly address — for example, when delivering an order raises the owning customer's loyalty balances, or when a no-show suspends a customer's booking standing — that resource's `updated_at` is refreshed and its `version` is incremented exactly as it would be for a direct edit.

### 2.5. Optimistic Concurrency for Box Curation

The platform enforces optimistic concurrency control at exactly one point: curating a new box shipment against a subscription. The curation request must carry `expected_subscription_version`, a non-optional field holding the `version` of the parent `BoxSubscription` that the client last observed. If that value does not equal the subscription's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This guards against a stale curation: if another writer has already curated the current cycle's box — which legitimately supersedes the prior curation and advances the subscription's `version` — the client's view is out of date, and allowing the write would let it overwrite a box it never saw. The subscription's `version` advances both when its status changes and when a shipment is curated against it, so any of those events invalidates a previously read version. No other endpoint accepts or requires a version field; endpoints not guarded by this rule perform their mutations without a concurrency check.

### 2.6. Monetary Precision and Rounding Discipline

All monetary amounts in the system are stored and returned as integer cents; there are no fractional-cent values in any response body. Wherever a rule multiplies an amount by a percentage — a loyalty tier discount, a redemption cap, a restocking fee — the product is rounded to a whole number of cents using the round-half-up convention (a value exactly halfway between two integers rounds up, away from zero) before it participates in any subsequent subtraction. Rounding is applied at the point each rule specifies, and the order of rounding relative to summation is significant: the subscription-box final charge, in particular, rounds each kept item's discounted price individually and only then sums them, rather than summing first and rounding once. Loyalty point earning uses integer arithmetic with a floor (any fractional point is discarded). These conventions are restated with their formulas in Section 3 so that each calculation is self-contained.

### 2.7. The Inventory Reservation Ledger

Each `ProductVariant` maintains a small stock ledger with three quantities. `inventory_on_hand` is the count of physical units in the warehouse. `inventory_reserved` is the count of units spoken for by open order lines and in-flight box items but not yet shipped. `inventory_available` is always the difference `inventory_on_hand` minus `inventory_reserved`, and it is the quantity that matters when deciding whether a new claim can be honored. Three ledger motions occur throughout the system. A reservation increases `inventory_reserved` by the claimed quantity and leaves `inventory_on_hand` untouched. A release decreases `inventory_reserved` by that quantity, again leaving `inventory_on_hand` untouched — this happens when an order is cancelled or a boxed item is not kept. A sale, which happens when an order ships or a boxed item is kept, decreases both `inventory_on_hand` and `inventory_reserved` by the quantity, converting a reservation into a permanent depletion. Any operation that would reserve more units than are available is refused; the specific guard is stated with the workflows that trigger it.

### 2.8. Parallel Order Dimensions

An `Order` advances along two independent status tracks that evolve on separate timelines. The `payment_status` dimension moves through `PENDING`, `AUTHORIZED`, `CAPTURED`, and terminally `REFUNDED`. The `fulfillment_status` dimension moves through `UNFULFILLED`, `PICKING`, `SHIPPED`, `DELIVERED`, and the terminal `CANCELLED`. The two dimensions are not fully independent: fulfillment picking may not begin until payment has been captured, which is the single cross-dimension gate in the model. A newly created order sits at `PENDING` payment and `UNFULFILLED` fulfillment simultaneously. Because these are separate dimensions, a client reading an order must consult both fields to understand its true position in the lifecycle; the exact transitions, actors, and side effects of each track are detailed in §3.3.

### 2.9. Validation Precedence and Error Ordering

Before any business evaluation, a request whose body is malformed, omits a required field, or supplies a value of the wrong type is rejected with `ERR_VALIDATION` (400). Beyond that structural gate, when a single request could fail several checks, the checks are evaluated in a fixed priority order, and the first failure encountered determines the error returned. The order is: (1) authentication — the `X-User-Role` header must be present and name a recognized role, else `ERR_UNAUTHENTICATED` (401); (2) authorization — the role must be permitted for the operation, and for entity-backed roles `X-User-ID` must own the target resource, else `ERR_UNAUTHORIZED` (403); (3) existence — the path resource and every referenced foreign key must exist, else `ERR_NOT_FOUND` (404); (4) concurrency — where applicable, `expected_subscription_version` must match, else `ERR_STALE_VERSION` (412); (5) state — the target must be in a state that permits the requested transition, else `ERR_INVALID_STATE` (409); (6) domain constraints — size range, inventory sufficiency, subset selections, specialty match, and exchange-variant presence, each with its own error (409); (7) referential state — a linked entity must be in the required standing, such as an active customer account for checkout, else the relevant standing error (409); (8) temporal windows — return windows, try-on windows, appointment overlaps, and clock gates, each with its own error (409); and (9) fiscal capacity — sufficient redeemable points and a non-empty order, else the relevant fiscal error (409). This ordering matters: a request that violates several rules surfaces the earliest one, so, for example, an unauthenticated caller never learns whether the target resource exists.

### 2.10. Nested Path Resolution

Several endpoints address a resource nested beneath a parent — a subscription's shipments, a product's variants, an order's lines. For any such path the server validates identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first path segment that does not resolve to an existing resource, before evaluating any deeper segment or applying business rules. Foreign keys supplied in a request body — `product_id`, `variant_id`, `order_id`, `specialist_id`, `subscription_id`, `exchange_variant_id`, and each id in `line_ids` — are validated for existence under the same principle and likewise yield `ERR_NOT_FOUND` when unresolved.

## 3. Business Logic & Workflows

This section describes the platform's domain workflows. Field names, thresholds, and the conditions behind each error are woven into the narrative of the workflow they belong to rather than collected into schema tables; a complete implementation is reconstructed by reading these workflows together with the global principles of Section 2.

### 3.1. Customer Accounts, Loyalty Standing, and the Store Wallet

A prospective shopper joins by registering, an action open to anyone unauthenticated. Registration supplies an `email` — the login address, which the server records as given without enforcing uniqueness in this version — a `full_name`, a preferred numeric `size_code` (the customer's usual size ordinal, such as 22 for a 2X), and optionally `adaptive_needs`, a subset of the adaptive-feature vocabulary `MAGNETIC_CLOSURE`, `SEATED_CUT`, `SENSORY_FRIENDLY`, `ONE_HANDED`, and `PORT_ACCESS` describing the functional features this shopper requires; when omitted, `adaptive_needs` defaults to an empty list. A freshly registered customer is initialized with every ledger field at its baseline: `loyalty_points_balance` and `loyalty_lifetime_points` at 0, `loyalty_tier` at `STANDARD`, `wallet_credit_cents` at 0, `no_show_count` at 0, `booking_status` at `ACTIVE`, and `account_status` at `ACTIVE`.

Two distinct loyalty counters live on the customer. `loyalty_points_balance` is the spendable balance: it grows when an order is delivered or a box is settled, shrinks when points are redeemed at checkout, and is restored when a redemption is reversed. `loyalty_lifetime_points` is the cumulative total ever earned; it drives the customer's tier and is never decremented by redemption. The `loyalty_tier` is derived from lifetime points against two thresholds: a customer reaches `INSIDER` once lifetime points are at least 500, and `VIP` once they are at least 2000; below 500 the tier is `STANDARD`. The tier governs both the checkout discount rate and the per-item box discount described later.

The `wallet_credit_cents` field holds store credit in cents, spendable at checkout. It is funded by refunds, by return settlements directed to the wallet, and by tier-up bonuses, and it is spent when a customer sets `use_wallet_credit` during checkout to apply their standing credit against the amount owed. A store manager may also adjust it directly as a customer-service gesture: a wallet adjustment supplies a signed `delta_cents` and an optional `reason`, and the credit moves by that delta but is floored at 0 so it can never go negative. Separately, a store manager may grant or deduct loyalty as goodwill by supplying a signed `delta_points` and an optional `reason`; such an adjustment moves both `loyalty_points_balance` and `loyalty_lifetime_points` by the delta and recomputes `loyalty_tier` from the new lifetime total, but — unlike organic earning — it never triggers a tier-up wallet bonus, because bonuses are reserved for points earned through delivery and box settlement.

A customer's `account_status` is one of `ACTIVE`, `SUSPENDED`, or `CLOSED` and is controlled exclusively by a store manager supplying a `to_status`. From `ACTIVE` the account may be suspended (permitted only while it is currently `ACTIVE`), transitioning to `SUSPENDED`; from `SUSPENDED` it may be reinstated to `ACTIVE` (permitted only while currently `SUSPENDED`); and from either `ACTIVE` or `SUSPENDED` it may be closed, moving to the terminal `CLOSED`. Account status gates checkout: a customer whose account is not `ACTIVE` cannot authorize an order. A request that names a transition the account's current status does not permit is rejected with `ERR_INVALID_STATE`. Independently of account status, the customer carries a `booking_status` of `ACTIVE` or `SUSPENDED` that governs appointment confirmation; this second flag is never set by a direct endpoint but is driven solely by the no-show cascade described in §3.5, flipping to `SUSPENDED` once `no_show_count` reaches the no-show suspension threshold of 3.

### 3.2. The Catalog: Products, Size Variants, and Stock

A store manager builds the catalog by creating a `Product`, which carries a display `name`, a `category` drawn from `TOPS`, `BOTTOMS`, `DRESSES`, `OUTERWEAR`, and `INTIMATES`, and a `base_price_cents` giving the base retail price before any per-variant surcharge. A product also declares the adaptive construction it offers through `adaptive_features` — a subset of the same `MAGNETIC_CLOSURE`, `SEATED_CUT`, `SENSORY_FRIENDLY`, `ONE_HANDED`, and `PORT_ACCESS` vocabulary, defaulting to an empty list — and the numeric sizing band it spans through `size_min` (the smallest size ordinal offered) and `size_max` (the largest). The optional `is_special_order` flag marks made-to-order garments with extended lead times and defaults to false, and `restock_fee_pct` records the restocking-fee fraction that will apply to non-damaged returned lines of this product, defaulting to 0.15. Every product is created in `status` `ACTIVE`, which is the only product status in this version.

Browsing the catalog is open to everyone. The product listing accepts optional filters that narrow the result: `adaptive_feature` restricts results to garments whose `adaptive_features` include the requested feature; `size_code` restricts to products whose sizing band covers that ordinal, meaning `size_min` is at most the requested `size_code` and `size_max` is at least it; `category` restricts to a single category; and `is_special_order` restricts by the made-to-order flag. These filters combine with the standard `limit` and `offset` pagination parameters.

Each sellable SKU is a `ProductVariant` created under a product by a store manager. A variant records its parent `product_id`, a numeric `size_code`, a `color` colorway, an optional `price_delta_cents` surcharge added to the product's base price for this SKU (extended sizes often cost more, default 0), and an optional starting `inventory_on_hand` (default 0). At creation the variant's `size_code` must fall within the parent product's band — at least `size_min` and at most `size_max` — and a variant whose size falls outside that band is rejected with `ERR_SIZE_OUT_OF_RANGE`. A new variant begins with `inventory_reserved` at 0 and `inventory_available` equal to its `inventory_on_hand`, and its `status` is `ACTIVE`, the only variant status in this version. The stock ledger fields behave exactly as described in §2.7. A store manager can replenish physical stock by supplying a `quantity` to add; the restock raises `inventory_on_hand` by that quantity and recomputes `inventory_available`. Variants are reverse-listable both from their parent product and, for operational review, by the order lines that reference them.

### 3.3. The Order Lifecycle: Cart, Checkout, and Fulfillment

A customer begins shopping by opening an order, which is created empty with `payment_status` at `PENDING` and `fulfillment_status` at `UNFULFILLED`; its `customer_id` is taken from `X-User-ID` and the customer owns it thereafter. Items are added as order lines while the order is still open. Adding a line supplies a `variant_id` and a `quantity` of at least one. At the moment the line is added, the system snapshots its `unit_price_cents` as the parent product's `base_price_cents` plus the variant's `price_delta_cents`, and computes `line_total_cents` as `unit_price_cents` multiplied by `quantity`; both are frozen on the immutable line. Adding the line also reserves stock — the variant's `inventory_reserved` rises by `quantity` — which requires that the variant's `inventory_available` be at least `quantity`; when it is not, the line is refused with `ERR_INSUFFICIENT_INVENTORY`. An order's lines are reverse-listable from the order, and the order itself is reverse-listable by its owning customer.

Checkout authorizes the order, advancing `payment_status` from `PENDING` to `AUTHORIZED`. Three preconditions guard it, and each carries its own error: the order must hold at least one line, else `ERR_EMPTY_ORDER`; the owning customer's `account_status` must be `ACTIVE`, else `ERR_CUSTOMER_SUSPENDED`; and the points the customer asks to redeem must not exceed their current `loyalty_points_balance`, else `ERR_INSUFFICIENT_POINTS`. The checkout request carries two optional inputs: `loyalty_redeem_points`, the number of points to spend (recorded on the order as `loyalty_redeemed_points`; it defaults to 0 when omitted and, if supplied, must be zero or positive, else `ERR_VALIDATION`), and `use_wallet_credit`, a boolean electing whether to apply store credit (defaulting to false). Checkout then computes the order's monetary fields in a single pinned sequence, each step consuming the previous result:

1. `subtotal_cents` is the sum of `line_total_cents` across all of the order's lines.
2. The tier discount rate is taken from the customer's `loyalty_tier`: 0 percent for `STANDARD`, 5 percent for `INSIDER`, 10 percent for `VIP`. `tier_discount_cents` is `subtotal_cents` multiplied by that rate, rounded half up to whole cents.
3. The tier-adjusted amount is `subtotal_cents` minus `tier_discount_cents`.
4. The redemption cap is 30 percent of `subtotal_cents`, rounded half up to whole cents.
5. `loyalty_redeemed_cents` is the least of three quantities: the redeemed points valued at 5 cents per point, the redemption cap from the previous step, and the tier-adjusted amount from step 3.
6. The post-redemption amount is the tier-adjusted amount minus `loyalty_redeemed_cents`.
7. `wallet_applied_cents` is applied only when `use_wallet_credit` is true, in which case it is the lesser of the customer's `wallet_credit_cents` and the post-redemption amount; otherwise it is 0.
8. `total_cents`, the amount authorized, is the post-redemption amount minus `wallet_applied_cents`.

As checkout completes, the customer's `loyalty_points_balance` is reduced by `loyalty_redeemed_points` and their `wallet_credit_cents` is reduced by `wallet_applied_cents`, committing the redemption and the wallet spend.

Once authorized, the order advances through a series of store-manager transitions, each named by an `action` on the order. Capturing payment moves `payment_status` from `AUTHORIZED` to `CAPTURED` and requires that payment currently be `AUTHORIZED`. Fulfillment cannot begin until payment is captured: starting to pick moves `fulfillment_status` from `UNFULFILLED` to `PICKING` and is permitted only when `payment_status` is `CAPTURED`, the single cross-dimension gate of the model. Shipping moves `fulfillment_status` from `PICKING` to `SHIPPED` (permitted only while picking) and realizes the sale — for each order line, the referenced variant's `inventory_on_hand` and `inventory_reserved` are each reduced by the line's `quantity`, converting the reservation into a permanent depletion.

Delivering moves `fulfillment_status` from `SHIPPED` to `DELIVERED` (permitted only while shipped) and is the point at which loyalty is earned. Delivery stamps `delivered_at` with the current clock time — the anchor for the return window — and sets the order's `points_earned` to `total_cents` divided by 100 and rounded down to a whole number (one point per whole dollar authorized). The earned points then drive a three-link cascade on the customer: first, both `loyalty_points_balance` and `loyalty_lifetime_points` increase by `points_earned`; second, `loyalty_tier` is recomputed from the new `loyalty_lifetime_points` against the same thresholds as elsewhere (`INSIDER` at 500 or more, `VIP` at 2000 or more, otherwise `STANDARD`); third, if that recomputation moves the tier strictly upward, the customer's `wallet_credit_cents` increases by the tier-up bonus for the newly reached tier — 1000 cents on reaching `INSIDER`, 2500 cents on reaching `VIP`. The bonus is granted only on an upward crossing, never when the tier is unchanged or recomputed downward.

Cancelling an order is available to the customer or a store manager while `fulfillment_status` is either `UNFULFILLED` or `PICKING`; it moves `fulfillment_status` to the terminal `CANCELLED` and unwinds the order's commitments. For each line, the variant's `inventory_reserved` is reduced by the line's `quantity`, releasing the reservation while leaving `inventory_on_hand` unchanged. The customer's `loyalty_points_balance` is increased by `loyalty_redeemed_points`, reversing any redemption, and their `wallet_credit_cents` is increased by `wallet_applied_cents`, reversing any wallet spend. If payment had already reached `CAPTURED`, the cancellation additionally triggers the compensating refund: `payment_status` moves to the terminal `REFUNDED` and `total_cents` is credited to the customer's `wallet_credit_cents`. This same capture-to-refund transition — refunding `total_cents` to the wallet — is the payment dimension's terminal move and is likewise only permitted while fulfillment is still `UNFULFILLED` or `PICKING`. Any order transition requested from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

### 3.4. Extended-Sizing Returns and Exchanges

Because fit is the central risk in extended and adaptive apparel, returns are a core workflow. A customer opens a `ReturnRequest` against one of their delivered orders. The request names the `order_id`, a `return_type` of either `RETURN` or `EXCHANGE`, and `line_ids` — the order lines being sent back, each of which must belong to the named order. It may also carry a `fit_verdict` of `RUNS_SMALL`, `TRUE_TO_SIZE`, or `RUNS_LARGE` (community fit feedback captured for the size community, defaulting to `TRUE_TO_SIZE`) and a `refund_destination` of `WALLET` or `ORIGINAL` (where the eventual refund is credited, defaulting to `WALLET`). When `return_type` is `EXCHANGE`, the request must also carry an `exchange_variant_id` naming the replacement SKU; an exchange lacking it is rejected with `ERR_EXCHANGE_VARIANT_REQUIRED`, while for a plain return `exchange_variant_id` stays null. Opening a return is permitted only when the underlying order has reached `DELIVERED` and only while the current clock time is within the return window — a fixed 30 days — measured forward from the order's `delivered_at`; a request that arrives strictly after that 30-day deadline (`delivered_at` plus 30 days) is rejected with `ERR_RETURN_WINDOW_CLOSED`. If any of the `line_ids` does not belong to the order, the request is rejected with `ERR_INVALID_LINE_SELECTION`. At creation the request enters `REQUESTED` and its `provisional_refund_cents` is pinned as an estimate: the sum of `line_total_cents` over the named `line_ids`, with no fees or damage yet accounted for.

A store manager adjudicates the return through a lifecycle of transitions. Approving it moves `REQUESTED` to `APPROVED` (permitted only while `REQUESTED`). Inspecting it moves `APPROVED` to `INSPECTED` (permitted only while `APPROVED`) and accepts `damaged_line_ids`, which must be a subset of the return's `line_ids`; a selection that is not a subset is rejected with `ERR_INVALID_LINE_SELECTION`. Inspection pins the final figures. First, the non-damaged returned total is the sum of `line_total_cents` over the returned lines excluding any in `damaged_line_ids`. Then `restock_fee_cents` is computed per non-damaged returned line — each such line's own product `restock_fee_pct` multiplied by that line's `line_total_cents`, accumulated as exact decimals across the non-damaged lines and rounded half up to whole cents once at the end (so lines drawn from products with differing `restock_fee_pct` values each contribute at their own rate). Finally `final_refund_cents` is the non-damaged total minus `restock_fee_cents`. Damaged lines are thus excluded from the refund entirely. Inspection also moves stock: each non-damaged returned line's variant has its `inventory_on_hand` increased by that line's `quantity` (the goods are restocked), while damaged lines are not restocked. When the return is an `EXCHANGE`, inspection additionally reserves one unit of the `exchange_variant_id` by raising that variant's `inventory_reserved` by 1.

Completing the return moves `INSPECTED` to the terminal `COMPLETED` (permitted only while `INSPECTED`) and settles the money and the exchange. For a plain `RETURN` whose `refund_destination` is `WALLET`, the customer's `wallet_credit_cents` increases by `final_refund_cents`; when the destination is `ORIGINAL`, the refund is returned to the original payment method and the wallet is not credited. For an `EXCHANGE`, the reserved replacement unit becomes a sale — the `exchange_variant_id` variant's `inventory_reserved` drops by 1 and its `inventory_on_hand` drops by 1 — and the net price difference, the exchange unit's price (its product `base_price_cents` plus that variant's `price_delta_cents`) minus `final_refund_cents`, is settled against the customer's `wallet_credit_cents` (a positive difference reduces the wallet, a negative difference adds to it). A store manager may instead reject the return, which is permitted while it is either `REQUESTED` or `APPROVED` and moves it to the terminal `REJECTED`; if the return was an exchange for which an inspection reservation had already been taken, that reservation is released. A transition requested from a state that does not allow it is rejected with `ERR_INVALID_STATE`. Returns are reverse-listable by their `order_id` and by their `exchange_variant_id`.

### 3.5. Virtual Styling and Fit Appointments

Fit specialists are staff stylists a store manager onboards with a `full_name`, a list of `specialties` drawn from `ADAPTIVE`, `PLUS_FORMAL`, and `MATERNITY`, and an optional `buffer_minutes` clearance requirement that defaults to 15. A specialist's `status` is `ACTIVE` or `ON_LEAVE`, set by a store manager through a `to_status`; a specialist who is `ON_LEAVE` cannot have appointments confirmed against them. A customer books an appointment by naming a `specialist_id`, a `start_at`, an `end_at`, and an optional `topic` — one of `GENERAL`, `ADAPTIVE`, `PLUS_FORMAL`, or `MATERNITY`, defaulting to `GENERAL`. The appointment's time is treated as a half-open interval running from `start_at` up to but not including `end_at`. A new appointment is created in `REQUESTED` status with its `customer_id` taken from `X-User-ID`, and its `late_cancel_fee_cents` starts at 0. Appointments are reverse-listable by both `customer_id` and `specialist_id`.

Confirming an appointment — an action reserved to a fit specialist or a store manager (a customer may not confirm) — moves it from `REQUESTED` to `CONFIRMED` and is where the scheduling constraints bite. Five preconditions apply, each with its own error: the specialist's `status` must be `ACTIVE`, else `ERR_SPECIALIST_ON_LEAVE`; the customer's `booking_status` must be `ACTIVE`, else `ERR_BOOKING_SUSPENDED`; the `topic` must be `GENERAL` or must appear in the specialist's `specialties`, else `ERR_SPECIALTY_MISMATCH`; the specialist must have no conflicting occupancy, else `ERR_SPECIALIST_UNAVAILABLE`; and the customer must have no conflicting appointment of their own, else `ERR_CUSTOMER_DOUBLE_BOOKED`. The two overlap checks use different geometries. The specialist is a buffered single-occupancy resource: a conflict exists if any other appointment on the same `specialist_id` that is currently `CONFIRMED` or `RESCHEDULE_REQUESTED` has its interval come within the specialist's `buffer_minutes` of this one — precisely, when this appointment's `start_at` minus the buffer is earlier than the other's `end_at`, and the other's `start_at` is earlier than this appointment's `end_at` plus the buffer. The customer is an unbuffered resource compared on the raw half-open intervals: a conflict exists if any other appointment for the same `customer_id` that is `CONFIRMED` has its `start_at` earlier than this appointment's `end_at` while this appointment's `start_at` is earlier than that appointment's `end_at`.

A confirmed appointment can enter a reschedule cycle. The customer requests a reschedule, moving `CONFIRMED` to `RESCHEDULE_REQUESTED`; this requires that the appointment currently be `CONFIRMED` and that the supplied `proposed_start_at` be earlier than the supplied `proposed_end_at`, and it stores those two proposed times. A specialist or store manager then confirms the reschedule, moving `RESCHEDULE_REQUESTED` back to `CONFIRMED`; this re-runs the specialist and customer overlap checks at the proposed interval (again yielding `ERR_SPECIALIST_UNAVAILABLE` or `ERR_CUSTOMER_DOUBLE_BOOKED` on a conflict), then promotes the proposal by setting `start_at` to `proposed_start_at` and `end_at` to `proposed_end_at` and clearing both proposed fields. This forms the loop `CONFIRMED → RESCHEDULE_REQUESTED → CONFIRMED`.

A confirmed appointment reaches its terminal states through completion, no-show, or cancellation. A specialist completes it, moving `CONFIRMED` to `COMPLETED`, only once the clock has reached or passed its `end_at`; completing early is rejected with `ERR_APPOINTMENT_NOT_ENDED`. A specialist or store manager marks a no-show, moving `CONFIRMED` to `NO_SHOW`, only once the clock has reached or passed its `start_at`; marking it before then is rejected with `ERR_APPOINTMENT_NOT_STARTED`. A no-show has a customer-side consequence: the customer's `no_show_count` increases by 1, and if that count reaches the no-show suspension threshold of 3 (`no_show_count` greater than or equal to 3), the customer's `booking_status` flips to `SUSPENDED`, which will block future confirmations until a manager intervenes. Cancellation may be initiated by the customer or the specialist while the appointment is `REQUESTED`, `CONFIRMED`, or `RESCHEDULE_REQUESTED`, moving it to the terminal `CANCELLED`. If the appointment was not in `CONFIRMED` at cancellation, its `late_cancel_fee_cents` is 0. If it was `CONFIRMED` and the gap between its `start_at` and the current clock time is less than the late-cancellation window — a fixed 24 hours — then `late_cancel_fee_cents` is set to the late-cancellation fee of 1500 cents and the customer's `wallet_credit_cents` is reduced by that 1500-cent fee (floored at 0 so it never goes negative); otherwise the fee is 0. Any appointment transition requested from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

### 3.6. The Subscription Box Program

A customer joins the curated-box program by starting a `BoxSubscription`, naming a `plan_tier` of `ESSENTIALS`, `SIGNATURE`, or `LUXE` and an optional `cadence` of `MONTHLY` or `QUARTERLY` (defaulting to `MONTHLY`). The plan tier fixes the subscription's `styling_fee_cents`, which is credited against kept items at settlement: `ESSENTIALS` carries 0, `SIGNATURE` carries 2500, and `LUXE` carries 5000. The subscription is created `ACTIVE` with its `version` at 1 and its `customer_id` taken from `X-User-ID`. The customer manages standing by supplying a `to_status`: an `ACTIVE` subscription may be paused (moving to `PAUSED`, permitted only while `ACTIVE`), a `PAUSED` subscription may be resumed (moving to `ACTIVE`, permitted only while `PAUSED`), and a subscription that is either `ACTIVE` or `PAUSED` may be cancelled (moving to the terminal `CANCELLED`). Every one of these status changes increments the subscription's `version` by 1. Subscriptions are reverse-listable by `customer_id`, and a request to change status from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

A fit specialist or store manager curates a box against a subscription by supplying `expected_subscription_version` — subject to the optimistic-concurrency rule of §2.5 — and `item_variant_ids`, the SKUs selected for this cycle. Curation builds the shipment's immutable `items` snapshot: for each selected variant an object holding its `variant_id` and its `retail_cents`, where `retail_cents` is that variant's product `base_price_cents` plus the variant's `price_delta_cents` captured at curation time. The shipment is created in `CURATED` status, each item's variant has its `inventory_reserved` raised by 1 (one unit reserved per item), and the parent subscription's `version` is incremented by 1. Shipments are reverse-listable from their parent subscription.

Shipping the box, performed by a store manager, moves `CURATED` to `SHIPPED`; it requires that the shipment currently be `CURATED` and that the parent subscription still be `ACTIVE`, else `ERR_SUBSCRIPTION_NOT_ACTIVE`. Shipping stamps `shipped_at` with the current clock time — the start of the try-on window — and pins `provisional_charge_cents` as the sum of `retail_cents` over all items in the box (a full-box authorization, undiscounted). Once the box arrives, the customer records their keep decisions, moving `SHIPPED` to `KEPT_PENDING`; the submitted `kept_variant_ids` must be a subset of the box's item variant ids, else `ERR_INVALID_KEEP_SELECTION`, and the selection is stored on the shipment.

Settling the box, performed by a store manager, moves `KEPT_PENDING` to the terminal `SETTLED`, and it may proceed only after the try-on window — a fixed 7 days — has elapsed: the current clock time must be at or beyond `shipped_at` advanced by 7 days, else `ERR_TRYON_WINDOW_OPEN`. Settlement computes `final_charge_cents` over the kept items only, and the rounding order is pinned to round-each-item-then-sum rather than sum-then-round. For each kept item, its `retail_cents` is multiplied by one minus the customer's tier discount rate (0 percent for `STANDARD`, 5 percent for `INSIDER`, 10 percent for `VIP`) and rounded half up to whole cents; these per-item amounts are summed into the kept subtotal. The styling credit is the lesser of the subscription's `styling_fee_cents` and that kept subtotal, and `final_charge_cents` is the kept subtotal minus the styling credit. Settlement then moves inventory: each kept item's variant has both `inventory_on_hand` and `inventory_reserved` reduced by 1 (a sale), while each not-kept item's variant has only `inventory_reserved` reduced by 1 (a release). Finally, settlement awards loyalty exactly as delivery does: the shipment's `points_earned` is `final_charge_cents` divided by 100 and rounded down to a whole number, after which the same three-link customer cascade runs — `loyalty_points_balance` and `loyalty_lifetime_points` both rise by `points_earned`, `loyalty_tier` is recomputed against the 500-point `INSIDER` and 2000-point `VIP` thresholds, and any strictly upward tier crossing adds the tier-up bonus (1000 cents for `INSIDER`, 2500 cents for `VIP`) to `wallet_credit_cents`. A box transition requested from a disallowed state is rejected with `ERR_INVALID_STATE`.

### 3.7. The Logical Clock

Every time-sensitive rule in the platform — return windows, try-on windows, appointment overlap and completion gates, late-cancellation timing, and delivery timestamps — reads the server's logical clock rather than wall-clock time. A store-manager-only test-driving capability advances that clock to a supplied `to_iso8601` instant, and every subsequent time comparison uses the new value. Until this capability is first exercised, the clock reads a fixed startup default of `2026-07-01T00:00:00Z`; it never falls back to real-world time. This makes every temporal outcome deterministic: a return can be pushed just past its window, a try-on window can be closed on demand, and an appointment can be aged to its start or end for no-show or completion.

## 4. Endpoint Definitions

Operations that create a new, standalone resource — registering a customer, creating a product or variant, opening an order, adding an order line, opening a return, starting a subscription, or curating a shipment — return `201 Created`. Operations that modify an existing resource, advance a state machine, or perform an adjustment return `200 OK`. Read operations return `200 OK`. The request and response bodies for each endpoint are not repeated here; they are reconstructed from the workflow narratives of Section 3 together with the global contracts of Section 2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server logical clock | StoreManager |
| POST | `/customers/register` | Register a new customer | Anonymous |
| GET | `/customers/{id}` | Get a customer | Customer, StoreManager |
| POST | `/customers/{id}/status` | Set a customer's account status | StoreManager |
| POST | `/customers/{id}/wallet-adjustments` | Issue or deduct store credit | StoreManager |
| POST | `/customers/{id}/loyalty-adjustments` | Grant or deduct loyalty points | StoreManager |
| POST | `/products` | Create a catalog product | StoreManager |
| GET | `/products` | List/browse products | Anonymous, Customer, StoreManager |
| GET | `/products/{id}` | Get a product | Anonymous, Customer, StoreManager |
| POST | `/products/{id}/variants` | Create a size/color SKU under a product | StoreManager |
| GET | `/products/{id}/variants` | List a product's variants | Anonymous, Customer, StoreManager |
| GET | `/variants/{id}` | Get a variant | Anonymous, Customer, StoreManager |
| POST | `/variants/{id}/restock` | Adjust physical stock | StoreManager |
| GET | `/variants/{id}/order-lines` | List order lines referencing a variant | StoreManager |
| POST | `/specialists` | Create a fit specialist | StoreManager |
| GET | `/specialists/{id}` | Get a fit specialist | Customer, StoreManager |
| POST | `/specialists/{id}/status` | Set specialist availability | StoreManager |
| POST | `/appointments` | Book a styling/fit appointment | Customer |
| GET | `/appointments/{id}` | Get an appointment | Customer, FitSpecialist, StoreManager |
| GET | `/appointments` | List appointments | Customer, FitSpecialist, StoreManager |
| POST | `/appointments/{id}/transition` | Advance an appointment (CONFIRM, RESCHEDULE_REQUEST, RESCHEDULE_CONFIRM, COMPLETE, CANCEL, NO_SHOW) | Customer, FitSpecialist, StoreManager |
| POST | `/orders` | Open an order (cart) | Customer |
| GET | `/orders/{id}` | Get an order | Customer, StoreManager |
| GET | `/orders` | List orders | Customer, StoreManager |
| POST | `/orders/{id}/lines` | Add a line to an order | Customer |
| GET | `/orders/{id}/lines` | List an order's lines | Customer, StoreManager |
| POST | `/orders/{id}/checkout` | Authorize the order | Customer |
| POST | `/orders/{id}/transition` | Advance an order (CAPTURE, PICK, SHIP, DELIVER, CANCEL) | Customer, StoreManager |
| POST | `/returns` | Open a return/exchange | Customer |
| GET | `/returns/{id}` | Get a return request | Customer, StoreManager |
| GET | `/returns` | List returns | Customer, StoreManager |
| POST | `/returns/{id}/transition` | Advance a return (APPROVE, INSPECT, COMPLETE, REJECT) | StoreManager |
| POST | `/box-subscriptions` | Start a subscription box membership | Customer |
| GET | `/box-subscriptions/{id}` | Get a subscription | Customer, StoreManager |
| GET | `/box-subscriptions` | List subscriptions | Customer, StoreManager |
| POST | `/box-subscriptions/{id}/status` | Set subscription status | Customer |
| POST | `/box-subscriptions/{id}/shipments` | Curate a new box shipment | FitSpecialist, StoreManager |
| GET | `/box-subscriptions/{id}/shipments` | List a subscription's shipments | Customer, StoreManager |
| GET | `/box-shipments/{id}` | Get a box shipment | Customer, FitSpecialist, StoreManager |
| POST | `/box-shipments/{id}/ship` | Ship a curated box | StoreManager |
| POST | `/box-shipments/{id}/keep-decisions` | Record kept items | Customer |
| POST | `/box-shipments/{id}/settle` | Settle the box after the try-on window | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_SIZE_OUT_OF_RANGE` | 409 Conflict |
| `ERR_INVALID_LINE_SELECTION` | 409 Conflict |
| `ERR_INVALID_KEEP_SELECTION` | 409 Conflict |
| `ERR_EXCHANGE_VARIANT_REQUIRED` | 409 Conflict |
| `ERR_SPECIALTY_MISMATCH` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_BOOKING_SUSPENDED` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_SPECIALIST_ON_LEAVE` | 409 Conflict |
| `ERR_RETURN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_TRYON_WINDOW_OPEN` | 409 Conflict |
| `ERR_SPECIALIST_UNAVAILABLE` | 409 Conflict |
| `ERR_CUSTOMER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_ENDED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_STARTED` | 409 Conflict |
| `ERR_INSUFFICIENT_POINTS` | 409 Conflict |
