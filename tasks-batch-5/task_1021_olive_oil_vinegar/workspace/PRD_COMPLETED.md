# Olive-Oil & Vinegar Tasting Shop API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Olive-Oil & Vinegar Tasting Shop API, the transactional backbone of a specialty retailer that sells premium oils and vinegars in three fundamentally different ways: pre-bottled goods and accessories sold by the unit, artisanal oils and vinegars dispensed by the millilitre from bulk vessels (known in the trade as *fusti*), and curated gift sets and blends assembled from other products. The business must reconcile physical inventory that decays over time, a tasting-bar booking operation, wholesale relationships with tiered pricing, and recurring subscriptions — all against a single, consistent ledger of money, loyalty, and stock.

Two concerns dominate the design. First, freshness: every bulk batch carries a harvest date and a best-by horizon, and its sensory quality decays faster once a vessel has been opened, so the price a customer ultimately pays and the very eligibility of a batch to be drawn both depend on where the batch sits on its decay curve at the moment of the transaction. Second, allocation integrity: bulk volume is a finite, reserved-then-committed resource shared across concurrent orders, subscriptions, and replenishment cycles, and the system must never let two orders draw the same millilitres or let a vessel go negative. The API therefore models money in integer cents, volume in integer millilitres, and time through an explicit, server-controlled logical clock so that decay and scheduling are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. All resource paths are mounted under the `/api` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes five roles: `Customer`, `ShopStaff`, `InventoryManager`, `WholesaleApprover`, and `PlatformAdmin`.

When `X-User-Role` is `Customer`, the principal is a retail or wholesale shopper acting as their own `Member`; `X-User-ID` is the `id` of that acting `Member`, and ownership checks on any resource that references a member — an order's `member_id`, a subscription's `member_id`, a tasting session's `member_id`, or a wholesale account's `member_id` — compare that foreign key against `X-User-ID`. A `Customer` who attempts to read or mutate a resource they do not own is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403).

When `X-User-Role` is `ShopStaff`, `InventoryManager`, `WholesaleApprover`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`. `ShopStaff` fulfills and returns orders, receives replenishment stock, runs the tasting bar, and renews subscriptions. `InventoryManager` manages the catalog, gift-set/blend components, and fusti inventory posture. `WholesaleApprover` reviews wholesale applications. `PlatformAdmin` is the operational superset that provisions members and controls the logical clock.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, may be no less than 1, and may be no greater than 100. The `offset` parameter is the number of items skipped from the front of the result set and defaults to 0.

Unless a specific workflow states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits. Every other timestamp- or date-valued field the API emits is rendered the same way — as an ISO 8601 UTC instant with exactly three fractional digits — including a fusti's `harvest_date`, `best_by_date`, and `first_draw_at`, a replenishment order's `received_harvest_date`, a subscription's `next_renewal_date`, a tasting session's `start_at` and `end_at`, and the logical clock's `current_utc`. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that starts at its creation value and increments by one on each mutation. The `version` field is the anchor of optimistic concurrency control described in §2.6.

Two resources are intentionally lightweight: a `ProductComponent` (the join between a set and its member product) and a `Reservation` are immutable-by-nature join/ledger rows in the sense that they carry only the common audit fields the scaffold assigns them; where a resource is not marked as carrying the full common-field set it exposes only `id` and `created_at`, with both `updated_at` and `version` absent. When in doubt, a resource that participates in optimistic concurrency (Members, Orders, WholesaleAccounts, Subscriptions, and the like) always exposes `version`.

Whenever a mutation cascades into a second resource — for example a fulfillment that draws a fusti's volume, or an approval that flips a member's type — each affected resource independently refreshes its own `updated_at` and increments its own `version`.

### 2.5. The Logical Clock

Time in this system is not wall-clock time. The server maintains a single logical clock whose startup default is exactly `2026-07-01T00:00:00Z`; before any clock call is made, every time-dependent computation reads exactly this default and never falls back to the host's real time. A `PlatformAdmin` may advance the clock by supplying a target instant in the `to_iso8601` field; the endpoint echoes the new value as `current_utc`. All freshness decay, best-by comparisons, subscription renewal eligibility, and tasting-session scheduling are evaluated against this logical "now".

### 2.6. Optimistic Concurrency Control

Several mutating operations require the client to prove it is acting on a version of the resource it has actually observed. When paying, fulfilling, or cancelling an order, the request must include `expected_order_version` carrying the order's last-observed `version`; when deciding a wholesale account, the request must include `expected_wholesale_account_version` carrying that account's `version`. In each case, if the supplied value does not equal the target resource's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Subscription creation is a distinct and important case. A `Member` may hold at most one `ACTIVE` subscription per product, and creating a new subscription for a product legitimately cancels (supersedes) the member's prior `ACTIVE` subscription for that same product. Because that supersession destroys an object the client may never have seen, a create request must carry `expected_member_version` matching the member's current `version`. If another writer has advanced the member's `version` since the client last read the member, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) — the client is prevented from silently superseding a subscription it never observed. This is a pure stale-version guard: it is not about requests arriving together, but about whether the version the client presents still reflects reality.

### 2.7. Monetary and Volumetric Precision

All money is represented as integers in cents; all bulk volume is represented as integers in millilitres. Prices per millilitre (`price_per_ml_cents`) may be fractional and are held with full precision, but any per-line money amount derived from them is rounded to a whole cent using the round-half-up convention, and — critically — each order line is rounded on its own before the lines are summed into a subtotal. Wholesale discounts are likewise rounded half up to whole cents. Freshness scores are the only non-money computed quantities; they are rounded half up to two decimal places. Volume never carries a fractional part.

### 2.8. Existence and Ownership Validation Order

When a path contains a resource identifier, the server validates existence left to right and rejects the first missing identifier with the matching not-found error (for example `ERR_ORDER_NOT_FOUND`, `ERR_FUSTI_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_WHOLESALE_ACCOUNT_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_REPLENISHMENT_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, or `ERR_SESSION_NOT_FOUND`), each carrying HTTP 404. Body-referenced foreign keys — a `product_id`, a `wholesale_account_id`, a `station_id`, or a `component_product_id` — are validated for existence in the same way when an order, subscription, fusti, component, or tasting session is created.

### 2.9. State Reconciliation and Cascades

Many operations mutate more than one entity. The system treats these cascades as atomic: an order payment that reserves bulk volume increases the reserved balance on the selected vessels; a fulfillment that commits those reservations draws physical volume, may trip a vessel into a low or empty posture, and may spawn a replenishment request; an approval or suspension of a wholesale account recomputes the owning member's type. Each such secondary mutation independently refreshes the affected resource's `updated_at` and `version`, as described in §2.4. The precise cascades are specified in the workflow narratives of §3.

### 2.10. Validation Priority

When several checks could fail on one request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication of the headers comes first, then role authorization, then existence of path-referenced resources, then existence of body-referenced foreign keys, then Customer ownership of the target resource. Only after those pass does the system evaluate state legality (whether the requested transition is defined from the resource's current state), then the optimistic-concurrency version match, then structural body validation (required fields, correct types and enums, quantities and volumes at least 1, and a session's end strictly after its start), then the zero-volume refill guard. Domain rules follow in this order: gift-set component legality, then allergen safety, then — on fulfillment — the past-best-by guard ahead of the vessel-posture guard, then — on booking — station buffer adjacency ahead of member double-booking ahead of the future-start guard, then wholesale-approval status, then bulk-volume availability, and finally SKU uniqueness on product creation. The subsections of §3 restate each of these checks beside the workflow it guards, together with the error it raises.

## 3. Business Logic & Workflows

### 3.1. Members, the Catalog, and Gift-Set Composition

A `PlatformAdmin` provisions a `Member` with an `email` (non-empty; the system does not enforce email uniqueness) and a `full_name`, and may attach a list of `allergen_restrictions` — tags drawn from `TREE_NUT` and `SULFITES` — that the member cannot be served. A newly created member begins as a `RETAIL` `member_type` with a `wallet_credit_cents` balance of 0 and `loyalty_points` of 0; neither the wallet nor the loyalty balance may ever go negative. A member's `member_type` is not set directly: it becomes `WHOLESALE` when one of the member's wholesale accounts reaches `APPROVED`, and reverts to `RETAIL` only when every one of the member's wholesale accounts is `SUSPENDED` or `REJECTED`.

An `InventoryManager` builds the catalog by creating a `Product`, supplying a `sku` (unique and non-empty), a `name`, and a `product_type` — one of `BULK_OIL`, `BULK_VINEGAR`, `BOTTLE`, `ACCESSORY`, `GIFT_SET`, or `BLEND`. Attempting to create a product whose `sku` already exists is rejected with `ERR_DUPLICATE_SKU`. A product may declare a `unit_price_cents` (the per-unit price for bottles and accessories, and the per-component reference price used by bundle pricing), a `price_per_ml_cents` (the possibly-fractional per-millilitre price for bulk refills), a list of `allergens` drawn from `TREE_NUT` and `SULFITES`, and a `shelf_life_days` count (the number of days from a batch's harvest to its best-by date for bulk products, and 0 for non-bulk products). All four are optional and default to empty or zero.

Gift sets and blends are assembled from other products. Adding a `ProductComponent` to a `GIFT_SET` or `BLEND` requires a `component_product_id` referencing the member product and a `quantity` of at least 1 unit bundled into one set. A component may not itself reference a set — if the `component_product_id` points at a `GIFT_SET` or `BLEND`, or if a set is offered for sale with no components at all, the request is rejected with `ERR_INVALID_COMPONENT`. The set a component belongs to is identified by its `set_product_id`; the components of a set can be listed back for pricing and display.

### 3.2. Bulk Vessels, Freshness Decay, and Replenishment

Bulk oils and vinegars are dispensed from a `Fusti`, a physical vessel created by an `InventoryManager` against a bulk `product_id` with a stated `capacity_ml` (at least 1), an `initial_volume_ml` seed quantity, a `reorder_point_ml` threshold, and a `harvest_date` for the batch. On creation the vessel's `current_volume_ml` is set from the initial volume, its `reserved_volume_ml` starts at 0, its `best_by_date` is computed as the harvest date plus the product's `shelf_life_days`, and its `first_draw_at` is null. A fresh vessel opens in `IN_SERVICE` posture, except that if its initial volume is at or below the reorder point it opens directly in `LOW`. At all times the vessel exposes an `available_volume_ml` equal to its current volume minus its reserved volume — the quantity a new reservation may draw.

Freshness is reported two ways whenever a vessel is read. Let the elapsed age be the number of days between the logical now and the `harvest_date` (the difference in seconds divided by 86,400). The `label_freshness_score` is one hundred multiplied by one minus the ratio of that elapsed age to the product's shelf life in days, floored at zero and rounded half up to two decimal places — a straight, forward-looking interpolation toward the best-by date. The `sensory_freshness_score` equals the label score for as long as `first_draw_at` is null. Once the vessel has been opened, the sensory score instead decays chronologically from the moment of opening: compute the label-style score using the elapsed age measured at `first_draw_at` (the opening age, again as one hundred times one minus opening-age-over-shelf-life, floored at zero), then subtract 2.5 points for every day elapsed between `first_draw_at` and the logical now, floor the result at zero, and round half up to two decimal places. The vessel also reports `is_past_best_by`, which is true exactly when the logical now is at or after the best-by date.

Operators steer a vessel's posture directly, each transition driven by an `action` in the request body (`QUARANTINE`, `RELEASE`, or `RETIRE`) that names the move; the same `action` field carries the verb for subscription and tasting-session transitions. An `InventoryManager` may quarantine a vessel whose `status` is `IN_SERVICE` or `LOW`, moving it to `QUARANTINED`. Releasing a `QUARANTINED` vessel returns it to `IN_SERVICE` when its current volume is strictly above the reorder point, or to `LOW` when its current volume is at or below the reorder point. A `QUARANTINED` vessel may also be retired, moving it to the terminal `RETIRED` posture. Requesting any of these transitions from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

Replenishment is automatic on the demand side and manual on the supply side. When a fulfillment draws a vessel down to at or below its reorder point while some volume remains, the vessel auto-transitions `IN_SERVICE → LOW`; when a draw empties it to exactly zero, it auto-transitions to `EMPTY` (from either `IN_SERVICE` or `LOW`). Any transition into `LOW` or `EMPTY` spawns a `ReplenishmentOrder` in `REQUESTED` status, whose `fusti_id` and `product_id` are copied from the vessel and whose `requested_volume_ml` is the capacity minus the current volume at that moment. `ShopStaff` (or an `InventoryManager`) closes the loop by receiving the incoming batch, supplying a `received_harvest_date` and an optional `received_volume_ml`; receiving refills the linked vessel's `current_volume_ml` to its full capacity, sets the vessel's `harvest_date` to the received harvest date, recomputes the `best_by_date`, resets `first_draw_at` to null, and returns the vessel from `LOW` or `EMPTY` to `IN_SERVICE`, while the replenishment order moves `REQUESTED → RECEIVED`. Auto-created replenishment rows are discovered through the replenishment list.

### 3.3. Placing an Order and Provisional Pricing

A `Customer` places an `Order` for their own account by submitting `lines`, an optional `wholesale_account_id`, and an optional `use_wallet_credit` flag. The order records the purchasing `member_id` from `X-User-ID` (or, for a subscription renewal, from the subscription's member). Each entry in `lines` is a line object with a `line_type` of `UNIT`, `REFILL`, or `BUNDLE`, a `product_id`, a `quantity`, and — for refills — a `volume_ml`. A `UNIT` line must reference a `BOTTLE` or `ACCESSORY`; a `REFILL` line must reference a bulk product and must carry a `volume_ml`; a `BUNDLE` line must reference a `GIFT_SET` or `BLEND`. The `lines` array must be non-empty, and a refill whose volume is zero or negative is rejected with `ERR_INVALID_QUANTITY`.

At creation the system computes a `provisional_subtotal_cents` from current catalog prices, line by line. A `UNIT` line contributes its product's `unit_price_cents` multiplied by its `quantity`. A `REFILL` line contributes its product's `price_per_ml_cents` multiplied by its `volume_ml`, rounded half up to a whole cent — each refill line rounded individually. A `BUNDLE` line contributes the gift-set bundle price: for every component of the set, take the component product's `unit_price_cents` multiplied by that component's bundled `quantity` and by ninety percent (a ten-percent gift-set discount), round that component amount half up to a whole cent, and then sum the rounded component amounts — components are rounded first and summed second, never the reverse. The subtotal is the sum of all line contributions.

From the subtotal the system derives the order total and stores it as `provisional_total_cents`, in a fixed order. First, the wholesale discount rate is zero unless the order carries a wholesale account that is `APPROVED`, in which case the rate is ten percent for `TIER_1`, twenty percent for `TIER_2`, or thirty percent for `TIER_3`. The `discount_cents` is the subtotal multiplied by that rate, rounded half up to whole cents. The discounted subtotal is the subtotal minus the discount. The `shipping_fee_cents` is then evaluated against that discounted subtotal: it is zero when the discounted subtotal is at least 7,500 cents (seventy-five dollars), and otherwise a flat 995 cents. The total is the discounted subtotal plus the shipping fee. At creation the order sits with `payment_status` of `UNPAID` and `fulfillment_status` of `PENDING`, and its `final_subtotal_cents` and `final_total_cents` remain null until fulfillment.

### 3.4. Payment: Wallet Credit and Volume Reservation

Paying an order is a single act that advances both status axes at once — `payment_status` from `UNPAID` to `PAID` and `fulfillment_status` from `PENDING` to `RESERVED` — and it is available only to the owning `Customer`, who must supply `expected_order_version`. The order must currently be `UNPAID` and `PENDING` (otherwise `ERR_INVALID_STATE`), and the version must match (otherwise `ERR_STALE_VERSION`). If the order names a wholesale account, that account must be `APPROVED`, or the payment is rejected with `ERR_WHOLESALE_NOT_APPROVED`. No line's product may declare an allergen that intersects the member's `allergen_restrictions`; a conflict is rejected with `ERR_ALLERGEN_CONFLICT`.

For every refill line the system must locate an eligible vessel using first-expiry-first-out selection. The candidates are the vessels for the line's product that are `IN_SERVICE` or `LOW`, are not past their best-by, and have an `available_volume_ml` of at least the line's `volume_ml`; among them the vessel with the earliest best-by date wins, breaking ties by the earliest creation timestamp. If no candidate qualifies, the payment is rejected with `ERR_INSUFFICIENT_VOLUME`. For each satisfied refill line the system creates a `Reservation` in `HELD` status recording its `order_id`, its selected `fusti_id`, and the `volume_ml` held, and increases the chosen vessel's `reserved_volume_ml` by that volume (its current volume is untouched at this stage).

Wallet credit, when requested, is applied at payment. If `use_wallet_credit` is true, the `wallet_credit_applied_cents` is the smaller of the member's `wallet_credit_cents` and the order's `provisional_total_cents`; otherwise it is zero. The member's wallet balance is reduced by the applied amount, and the `amount_charged_cents` billed externally is the provisional total minus the applied credit. Payment increments the order's `version`.

### 3.5. Fulfillment: Commitment, Final Pricing, and Loyalty

Fulfillment is performed by `ShopStaff` on an order whose `fulfillment_status` is `RESERVED`, with a matching `expected_order_version`; a wrong state yields `ERR_INVALID_STATE` and a wrong version yields `ERR_STALE_VERSION`. Before anything is committed, every refill line's held vessel is re-checked: if any such vessel is past its best-by, fulfillment is rejected with `ERR_FUSTI_EXPIRED`; if any such vessel is not in `IN_SERVICE` or `LOW` posture (that is, it has become `QUARANTINED`, `EMPTY`, or `RETIRED`), fulfillment is rejected with `ERR_FUSTI_QUARANTINED`.

When the checks pass, the order's price is recomputed as the final settlement and stored in `final_subtotal_cents` and `final_total_cents`, applying a freshness markdown per line: any refill line whose committed vessel has a `sensory_freshness_score` below seventy is repriced as its `price_per_ml_cents` multiplied by its `volume_ml` and by eighty-five percent (a fifteen-percent markdown), rounded half up per line before the subtotal is summed; all other lines price exactly as they did provisionally. The final subtotal then flows through the same discount-then-shipping settlement as the provisional total. Only `final_subtotal_cents` and `final_total_cents` capture this final settlement; the order's `discount_cents` and `shipping_fee_cents` fields keep the provisional values assigned at creation and are not recomputed at fulfillment. If the provisional total exceeded the final total, the difference is returned to the member as store credit — the member's `wallet_credit_cents` is increased by that difference and the order's `amount_refunded_cents` is increased by the same amount.

Each held `Reservation` then moves `HELD → COMMITTED`: its vessel's `current_volume_ml` and `reserved_volume_ml` are both reduced by the reservation's `volume_ml`, and the vessel's `first_draw_at` is set to the logical now if it was null (opening the sensory decay curve). After each draw, the reorder cascade of §3.2 runs — the vessel may trip to `LOW` or `EMPTY` and, where it does, spawn a `ReplenishmentOrder`. Finally, loyalty accrues: the member's `loyalty_points` increase by the whole-dollar portion of the final total, computed as the final total in cents divided by 100 and rounded down to a whole number, then multiplied by one point per dollar. Fulfillment increments the order's `version`.

### 3.6. Cancellations, Releases, and Returns

Cancellation behaves differently depending on where the order stands, and the owning `Customer` (or `ShopStaff`) must always present `expected_order_version`. An order still `UNPAID` and `PENDING` may be cancelled by the owning `Customer` to `CANCELLED` with no reservations, no volume movement, and no wallet change — only the `version` advances (the `payment_status` stays `UNPAID` and only the `fulfillment_status` moves to `CANCELLED`). An order that is `PAID` and `RESERVED` may be cancelled by the `Customer`, moving `payment_status` to `REFUNDED` and `fulfillment_status` to `CANCELLED`: every `HELD` reservation moves `HELD → RELEASED`, its vessel's `reserved_volume_ml` is reduced by the held `volume_ml` while its `current_volume_ml` stays unchanged, the exact `wallet_credit_applied_cents` debited at payment is restored to the member's `wallet_credit_cents`, and the `amount_refunded_cents` is set to the provisional total.

A `PAID` and `FULFILLED` order may be returned by `ShopStaff`, which likewise moves it to `REFUNDED` and `CANCELLED` but reverses the physical and financial effects of fulfillment: every `COMMITTED` reservation's vessel has its `current_volume_ml` increased by the returned `volume_ml` (restocking the batch), the member's `wallet_credit_cents` is increased by the full `final_total_cents`, the member's `loyalty_points` are reduced by exactly the accrual that fulfillment granted (the final total in cents divided by 100, rounded down, times one point per dollar), and the `amount_refunded_cents` is set to the final total. The permitted actor is fixed by the order's current state — the `UNPAID`/`PENDING` and `PAID`/`RESERVED` cancellations are available only to the owning `Customer`, and the `PAID`/`FULFILLED` return only to `ShopStaff`; a request whose role does not match the actor defined for the current state is rejected with `ERR_UNAUTHORIZED` (the owning-`Customer` ownership check, raising `ERR_FORBIDDEN_NOT_OWNER`, is applied first when the caller is a `Customer`). Any cancellation from a state where it is undefined is rejected with `ERR_INVALID_STATE`. Every cancellation increments the order's `version`.

### 3.7. Wholesale Accounts and Tiered Terms

A `Customer` applies for wholesale terms by creating a `WholesaleAccount` for themselves, supplying a `business_name` and a `tax_id`; the `member_id` is taken from `X-User-ID` and the account opens in `DRAFT` with a `tier` of `NONE` and a null `rejection_reason`. The owner submits the application, moving it `DRAFT → SUBMITTED`; a later revision loop is supported, since an account for which changes were requested may be resubmitted `CHANGES_REQUESTED → SUBMITTED`, which clears the `rejection_reason`.

A `WholesaleApprover` decides a `SUBMITTED` application by supplying a `decision` (`APPROVE`, `REQUEST_CHANGES`, or `REJECT`), an `expected_wholesale_account_version`, and — on approval — a `tier`, or — on a change request or rejection — a `rejection_reason`. Approving requires the `tier` to be one of `TIER_1`, `TIER_2`, or `TIER_3`; it sets that tier, moves the account `SUBMITTED → APPROVED`, and flips the owning member's `member_type` to `WHOLESALE`. Requesting changes moves `SUBMITTED → CHANGES_REQUESTED` and records the reason; rejecting moves `SUBMITTED → REJECTED` (a terminal state) and records the reason. An `APPROVED` account may be suspended `APPROVED → SUSPENDED` (through the same decision endpoint with a `decision` of `SUSPEND`, likewise carrying a matching `expected_wholesale_account_version`), which reverts the member's `member_type` to `RETAIL` only if the member has no other `APPROVED` wholesale account; a `SUSPENDED` account may be reinstated `SUSPENDED → APPROVED` (with a `decision` of `REINSTATE`), which returns the member to `WHOLESALE`. A decision presented for an account not in the required state is rejected with `ERR_INVALID_STATE`, and a stale `expected_wholesale_account_version` with `ERR_STALE_VERSION`. Every decision and submission increments the account's `version`.

### 3.8. Subscriptions and Automatic Renewal

A `Customer` creates a `Subscription` for their own account against a `product_id`, specifying either a `quantity` (units per cycle for unit or bundle products, defaulting to 1) or a `volume_ml` (millilitres per cycle for a bulk refill, null otherwise), a `cadence_days` interval of at least 1, and the `expected_member_version` required by the concurrency guard of §2.6. On creation the `member_id` is taken from `X-User-ID`, the subscription opens `ACTIVE` with `renewals_count` at 0 and a null `last_order_id`, its `next_renewal_date` is set to the logical now plus the cadence, the member's `version` is incremented, and any prior `ACTIVE` subscription the member holds for the same product is moved to `CANCELLED`.

The owner may pause an `ACTIVE` subscription (`ACTIVE → PAUSED`), resume a paused one (`PAUSED → ACTIVE`), or cancel from either `ACTIVE` or `PAUSED` to the terminal `CANCELLED`; each increments the subscription's `version`, and an undefined transition is rejected with `ERR_INVALID_STATE`. Renewal is a `ShopStaff` action and an `ACTIVE` self-loop, permitted only when the logical now has reached or passed the `next_renewal_date`: it creates a new `Order` for the subscription's member with a single line derived from the subscription's product, quantity, and volume — the line's `line_type` follows the product's `product_type` (`REFILL` for a bulk product, `BUNDLE` for a `GIFT_SET`/`BLEND`, `UNIT` otherwise), and the order carries no wholesale account and requests no wallet credit, so it prices at retail with standard shipping; the order opening `UNPAID` and `PENDING` — records that order's id as `last_order_id`, advances `next_renewal_date` by another cadence interval, increases `renewals_count` by one, and increments the subscription's `version`.

### 3.9. The Tasting Bar

An `InventoryManager` (or `PlatformAdmin`) creates a `TastingStation` with a display `name`. A `Customer` books a `TastingSession` for themselves against a `station_id`, giving a `start_at`, an `end_at` strictly after the start (else `ERR_VALIDATION`), and an optional `party_size` of at least one guest (defaulting to 1); the `member_id` comes from `X-User-ID` and the session opens `BOOKED`. Three temporal guards apply in turn. The new session must not fall within the station's buffer window of any other non-cancelled session on the same station, or it is rejected with `ERR_STATION_UNAVAILABLE`; the buffer window is 15 minutes, and the collision fires when the time gap between the new session and an existing session on that station is strictly less than 15 minutes, so a session that starts exactly 15 minutes after a prior session ends (a gap of exactly 15 minutes) is accepted. Its half-open interval from its start up to but not including its end must not overlap any other non-cancelled session held by the same member on any station, or it is rejected with `ERR_MEMBER_DOUBLE_BOOKED`. Its start must be strictly later than the logical now, or it is rejected with `ERR_SESSION_IN_PAST`.

Once booked, a session moves through its lifecycle by operator and owner actions. `ShopStaff` checks a `BOOKED` session in (`BOOKED → CHECKED_IN`) and later completes a checked-in one (`CHECKED_IN → COMPLETED`), or marks a `BOOKED` session as `NO_SHOW` once the logical now has reached or passed its start (an attempt to mark `NO_SHOW` before the start is reached is rejected with `ERR_INVALID_STATE`). The owning `Customer` may cancel a `BOOKED` session (`BOOKED → CANCELLED`). Any transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify or transition an existing resource, receive stock, or set the clock return `200 OK`. All paths are mounted under `/api`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/api/members` | Create a member | PlatformAdmin |
| GET | `/api/members/{id}` | Fetch a member (wallet, loyalty, type) | Customer, ShopStaff, InventoryManager, WholesaleApprover, PlatformAdmin |
| POST | `/api/products` | Create a catalog product/SKU | InventoryManager |
| GET | `/api/products/{id}` | Fetch a product | Customer, ShopStaff, InventoryManager, WholesaleApprover, PlatformAdmin |
| POST | `/api/products/{id}/components` | Add a component to a GIFT_SET/BLEND product | InventoryManager |
| GET | `/api/products/{id}/components` | List the components of a set product | Customer, ShopStaff, InventoryManager, WholesaleApprover, PlatformAdmin |
| POST | `/api/fusti` | Create a fusti for a BULK product | InventoryManager |
| GET | `/api/fusti/{id}` | Fetch a fusti with computed freshness/availability | Customer, ShopStaff, InventoryManager, WholesaleApprover, PlatformAdmin |
| GET | `/api/fusti` | List fusti (filterable) | Customer, ShopStaff, InventoryManager, WholesaleApprover, PlatformAdmin |
| POST | `/api/fusti/{id}/transition` | Operator transition of a fusti (QUARANTINE/RELEASE/RETIRE) | InventoryManager |
| GET | `/api/reservations/{id}` | Fetch a reservation | ShopStaff, InventoryManager, PlatformAdmin |
| GET | `/api/reservations` | List reservations | ShopStaff, InventoryManager, PlatformAdmin |
| GET | `/api/replenishment-orders/{id}` | Fetch a replenishment order | ShopStaff, InventoryManager, PlatformAdmin |
| GET | `/api/replenishment-orders` | List replenishment orders | ShopStaff, InventoryManager, PlatformAdmin |
| POST | `/api/replenishment-orders/{id}/receive` | Receive an incoming batch and refill the fusti | ShopStaff, InventoryManager |
| POST | `/api/wholesale-accounts` | Apply for a wholesale account | Customer |
| GET | `/api/wholesale-accounts/{id}` | Fetch a wholesale account | Customer, WholesaleApprover, PlatformAdmin |
| GET | `/api/wholesale-accounts` | List wholesale accounts | WholesaleApprover, PlatformAdmin |
| POST | `/api/wholesale-accounts/{id}/submit` | Submit or resubmit a wholesale application | Customer |
| POST | `/api/wholesale-accounts/{id}/decision` | Approver decision on a wholesale account | WholesaleApprover |
| POST | `/api/orders` | Create an order with lines (provisional pricing) | Customer |
| GET | `/api/orders/{id}` | Fetch an order | Customer, ShopStaff, PlatformAdmin |
| GET | `/api/orders` | List orders | ShopStaff, PlatformAdmin |
| POST | `/api/orders/{id}/pay` | Pay an order; apply wallet credit, reserve volume | Customer |
| POST | `/api/orders/{id}/fulfill` | Fulfill a reserved order | ShopStaff |
| POST | `/api/orders/{id}/cancel` | Cancel or return an order | Customer, ShopStaff |
| POST | `/api/subscriptions` | Create a subscription | Customer |
| GET | `/api/subscriptions/{id}` | Fetch a subscription | Customer, ShopStaff, PlatformAdmin |
| GET | `/api/subscriptions` | List subscriptions | ShopStaff, PlatformAdmin |
| POST | `/api/subscriptions/{id}/transition` | Transition a subscription (PAUSE/RESUME/CANCEL/RENEW) | Customer, ShopStaff |
| POST | `/api/tasting-stations` | Create a tasting-bar station | InventoryManager, PlatformAdmin |
| POST | `/api/tasting-sessions` | Book a tasting session | Customer |
| GET | `/api/tasting-sessions/{id}` | Fetch a tasting session | Customer, ShopStaff, PlatformAdmin |
| GET | `/api/tasting-sessions` | List tasting sessions | ShopStaff, PlatformAdmin |
| POST | `/api/tasting-sessions/{id}/transition` | Transition a session (CANCEL/CHECK_IN/COMPLETE/NO_SHOW) | Customer, ShopStaff |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_FUSTI_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_RESERVATION_NOT_FOUND` | 404 |
| `ERR_REPLENISHMENT_NOT_FOUND` | 404 |
| `ERR_WHOLESALE_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_INVALID_COMPONENT` | 422 |
| `ERR_ALLERGEN_CONFLICT` | 422 |
| `ERR_FUSTI_EXPIRED` | 422 |
| `ERR_FUSTI_QUARANTINED` | 409 |
| `ERR_INSUFFICIENT_VOLUME` | 409 |
| `ERR_WHOLESALE_NOT_APPROVED` | 409 |
| `ERR_STATION_UNAVAILABLE` | 409 |
| `ERR_MEMBER_DOUBLE_BOOKED` | 409 |
| `ERR_SESSION_IN_PAST` | 422 |
