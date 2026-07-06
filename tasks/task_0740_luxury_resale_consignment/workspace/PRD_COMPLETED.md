# Luxury Resale Consignment API — Product Requirements Document

## 1. Introduction

The luxury resale market lives or dies on trust. A consignor hands over a five-figure handbag or a rare timepiece and expects it to be authenticated by an expert, priced fairly, sold at the right moment, and paid out on a schedule that protects everyone from fraud and buyer's remorse alike. A shopper, in turn, wants confidence that what arrives in the box is genuine, graded honestly, and returnable if something is wrong. This document specifies the backend API that mediates that entire relationship — from the moment an item is dropped off or collected by a white-glove concierge, through authentication and grading, listing and negotiation, sale and fulfilment, and finally payout settlement or dispute resolution.

The platform is a pricing engine wrapped around a multi-party negotiation flow. Commission rates bend to a consignor's loyalty tier, buyer protection fees and sales tax stack onto every order, and refunds branch by the reason a buyer returns an item. Several distinct principals — consignors, shoppers, authentication experts, field concierges, and platform operators — each touch a different slice of the workflow, and the money that moves between them is tracked through per-seller ledgers whose balances must always reconcile to the underlying payout records. Because value is high and states are interdependent, the system favours explicit, ordered validation and immediate consistency: every automatic cascade (a sold listing pulling its item along, a resolved dispute unwinding a payout) is applied synchronously so that no reader ever observes a half-settled world.

The whole API is mounted under the `/consignment` path prefix. The sections that follow define the system-wide contract first — authentication, response envelopes, pagination, money precision, concurrency, cascades, and ledgers — and then walk the business workflows in the order a real consignment travels through the platform.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 400) before any other processing. The system recognises exactly five roles, spelled precisely as follows: `OpsAdmin`, `Seller`, `Buyer`, `Authenticator`, and `ConciergeAgent`; a value in `X-User-Role` that is not exactly one of these five is treated as malformed and rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 400), not `ERR_UNAUTHORIZED`. When a role is syntactically valid but not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks compare the `seller_id` foreign key on any targeted `ConsignmentItem` or `Listing` to `X-User-ID`.
- When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer`; ownership checks compare the `buyer_id` foreign key on any targeted `Sale` or `Offer` to `X-User-ID`.
- When `X-User-Role` is `Authenticator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `authenticator_id` on the `ConsignmentItem` it grades but never compares it to any entity's `id`.
- When `X-User-Role` is `OpsAdmin`, `X-User-ID` is an opaque operator identifier for platform operations; it is not tied to any persisted entity and is not compared to any resource's owner.
- When `X-User-Role` is `ConciergeAgent`, `X-User-ID` is an opaque operator identifier for the field agent completing a pickup; it is not tied to any persisted entity and is not compared to any resource's owner.

A resource whose owner does not match the acting principal (a seller acting on another seller's item, a buyer acting on another buyer's offer) is rejected with `ERR_NOT_OWNER` (HTTP 403). Item authentication is exempt from the ownership comparison, since the `Authenticator` who grades an item is never its owner.

When several checks apply to one request, they are evaluated in a fixed order, and the first failure is the one reported. The canonical order is: (1) authentication-context headers (`ERR_MISSING_AUTH_CONTEXT`); (2) role permission (`ERR_UNAUTHORIZED`); (3) existence of every referenced resource, validated left-to-right (the `ERR_..._NOT_FOUND` family); (4) ownership (`ERR_NOT_OWNER`); (5) the target resource's own state precondition (the `ERR_..._INVALID_STATE` family, plus `ERR_SALE_NOT_DISPUTABLE` and `ERR_PAYOUT_NOT_RELEASABLE`); (6) the optimistic-concurrency version check (`ERR_STALE_LISTING_VERSION`); (7) cross-entity state preconditions on a *different* entity (`ERR_ITEM_NOT_AUTHENTICATED`, `ERR_LISTING_NOT_ACTIVE`); and (8) the remaining domain business rules described throughout §3. A syntactically malformed body — a missing required field, an unrecognised enumeration value, or a non-integer value where whole cents are required — is rejected with `ERR_VALIDATION` (HTTP 400). This body-shape check runs immediately after role permission (step 2) and before resource existence (step 3), so a malformed body is reported ahead of any not-found error.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip; it defaults to 0 and has a minimum of 0. A `limit` or `offset` outside its range is clamped into range rather than rejected (a `limit` below 1 becomes 1, above 100 becomes 100, and a negative `offset` becomes 0); an empty-string value for either is treated as omitted, while a present but non-integer value is rejected with `ERR_VALIDATION`. Unless a subsection states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by creation order (the order in which the resources were persisted). The `meta` object of every list response reports `limit`, `offset`, `total_count` (the total number of matching resources ignoring pagination), and `has_more` (whether any matching resources remain beyond the current page).

### 2.4. Common Resource Properties and Resource Versioning

Every persisted resource in this system — `Seller`, `Buyer`, `CategoryPolicy`, `ConsignmentItem`, `Listing`, `Offer`, `Sale`, `Payout`, `Dispute`, `Concierge`, `Vehicle`, and `PickupAppointment` — carries a common set of system-managed properties:

- `id`: a server-minted UUID, used for identity only and never a business-decision input. It carries no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is created.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version`: an integer that begins at creation and increments by one on every mutation. It underpins the optimistic-concurrency mechanism described in §2.6.

All twelve resource types expose all four of these fields. Any change to a resource — whether requested directly by a client or applied automatically by a cascade — refreshes `updated_at` and increments `version` on the resource that changed.

### 2.5. Monetary Representation, Precision, and Rounding

All monetary amounts are represented as integer counts of cents; every field whose name ends in `_cents` holds a whole number of cents, and a request that supplies a non-integer value for such a field is rejected with `ERR_VALIDATION`. Rate and fraction fields — such as `base_commission_pct`, `buyer_fee_pct`, `min_offer_pct`, `commission_rate_locked_pct`, and `commission_rate_pct` — are fractions (for example, `0.20` means twenty percent) and preserve their input precision.

Whenever a monetary amount is derived by multiplying a cents value by a rate, the product is rounded to a whole number of cents using the round-half-up convention: a residue of exactly half a cent rounds up to the next whole cent. This rounding is applied component by component in the exact order each calculation specifies; intermediate rounded values, not raw products, feed the next step. The precise ordering for order totals and refunds is spelled out in §3.

### 2.6. Optimistic Concurrency Control on Offer Creation

Making an offer on a listing is guarded by an optimistic-concurrency check. A buyer is expected to hold at most one live offer per listing (an assumption the server does not itself enforce beyond the version guard described here), and a fresh offer legitimately supersedes the buyer's prior view of that listing — so the request that creates an offer must carry `expected_listing_version`, the `version` of the target `Listing` that the buyer last observed. The server compares `expected_listing_version` against the listing's current `version`. If they match, offer creation proceeds. If the listing's version has advanced since the buyer read it — because another offer was created, the seller published or relisted it, or the listing was marked sold — the buyer's observed version is stale, and the create is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412), preventing the buyer from posting against a listing state that no longer exists. This version field is required only on offer creation; no other endpoint accepts or requires an expected-version field.

### 2.7. Cascading State Consistency

Many operations mutate more than one resource. Publishing a listing pulls its item forward; selling a listing pulls both the item and every competing offer along with it; resolving a dispute in the buyer's favour unwinds the sale, its payout, the seller's ledger, the buyer's ledger, and the item all at once. These secondary effects are not optional side channels — they are part of the operation and are applied immediately and synchronously, so that the system never exposes a partially reconciled state. Each resource touched by a cascade independently refreshes its `updated_at` and increments its `version`, exactly as if it had been mutated directly. The specific cascade chains are described alongside the workflows that trigger them in §3; the governing rule here is that a parent's state transition and the child transitions it induces are a single, indivisible unit of consistency.

### 2.8. Seller Payout and Buyer Purchase Ledgers

Each `Seller` maintains four derived money fields that together form a payout ledger, and this ledger must always reconcile exactly to that seller's `Payout` records. `pending_payout_cents` equals the sum of `amount_cents` over the seller's payouts whose status is `SCHEDULED` or `HELD`. `released_payout_cents` equals the sum of `amount_cents` over the seller's payouts whose status is `RELEASED`. `reversed_payout_cents` equals the sum of `amount_cents` over the seller's payouts whose status is `REVERSED`. `payout_balance_cents` equals `pending_payout_cents` plus `released_payout_cents` — money that is owed or already paid, excluding anything reversed. The `lifetime_net_sales_cents` field accumulates `amount_cents` as each payout is released and is the sole basis for the seller's loyalty `tier`. Across all of a seller's payouts, the quantity `pending_payout_cents` + `released_payout_cents` + `reversed_payout_cents` is conserved and always equals the sum of `amount_cents` over every one of that seller's payouts: a reversal simply moves an amount out of the pending bucket and into the reversed bucket, leaving the conserved total unchanged.

Each `Buyer` maintains `lifetime_purchases_cents`, which equals the sum of `order_total_cents` over that buyer's sales whose `fulfillment_status` is `DELIVERED` and is not `RETURNED`. Delivery adds a sale's `order_total_cents` to this total; a buyer-favour return subtracts exactly the same `order_total_cents`, so a sale that is delivered and later returned nets to zero contribution.

### 2.9. Nested Retrieval, Filtered Lists, and Left-to-Right Validation

Entities are flat, top-level collections; children are reached either by filtered list queries or by sub-resource lists hung off a parent. A request that names one or more resource identifiers — whether in the path or as a required foreign key in the body — has each identifier validated in left-to-right order, and the first identifier that does not resolve to an existing resource produces the corresponding not-found error before any later identifier is examined. The not-found codes are resource-specific: `ERR_SELLER_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_CATEGORY_POLICY_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_CONCIERGE_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, and `ERR_PICKUP_NOT_FOUND`. List endpoints accept optional filters that narrow the collection by foreign key or status — items filter by `seller_id`, `category`, and `status`; listings by `item_id`, `seller_id`, and `status`; offers by `listing_id`, `buyer_id`, and `status`; sales by `listing_id`, `buyer_id`, `seller_id`, and `status` (a sale has no single status field, so a `status` filter matches any sale whose `payment_status` or `fulfillment_status` equals the given value); pickups by `concierge_id`, `vehicle_id`, `item_id`, `seller_id`, and `status` — alongside the `limit` and `offset` pagination parameters. The payouts and disputes belonging to a sale are retrieved as sub-resource lists under that sale, giving reverse reachability from a `Sale` to its `Payout` records (by `sale_id`) and its `Dispute` records (by `sale_id`).

### 2.10. The Logical Clock

All time-based evaluation reads a server logical clock, never real wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and it continues to read that default until it is explicitly set. An `OpsAdmin` may advance or set the clock by supplying a `to_iso8601` instant. Every deadline in the system — offer expiry (`expires_at`), the dispute return window (`return_window_ends_at`), and the payout release date (`scheduled_release_at`) — is evaluated against this logical clock. Offer expiry in particular is evaluated lazily: an offer that has passed its `expires_at` is treated as expired the next time it is read or acted upon, rather than by any background process.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Consignors, Shoppers, and Category Policies

An `OpsAdmin` registers a consignor by creating a `Seller` from a `display_name` and an `email`. A newly created seller starts with `status` `ACTIVE`, `tier` `STANDARD`, and every ledger field — `lifetime_net_sales_cents`, `pending_payout_cents`, `released_payout_cents`, `reversed_payout_cents`, and `payout_balance_cents` — initialised to zero. A seller may later read its own record to see its tier and balances. Likewise, an `OpsAdmin` registers a shopper by creating a `Buyer` from a `display_name` and an `email`; a new buyer starts `ACTIVE` with `lifetime_purchases_cents` at zero and can read its own record.

Pricing and return behaviour are governed per category. An `OpsAdmin` creates a `CategoryPolicy` for a `category`, which must be one of `HANDBAGS`, `WATCHES`, `JEWELRY`, `APPAREL`, or `SHOES`, and each category may have at most one policy; an attempt to create a second policy for a category that already has one is rejected with `ERR_VALIDATION` (HTTP 400). The policy carries the `base_commission_pct` (the platform's base commission fraction on the sale price before any tier discount), the `buyer_fee_pct` and `buyer_fee_flat_cents` (the two components of the buyer protection fee), the `return_window_days` (how many days after delivery a dispute may be filed), the `min_offer_pct` (the minimum acceptable offer as a fraction of the list price), the `listable_min_condition_grade` (the worst condition grade still eligible to be listed), and the `pickup_insurance_cap_cents` (the largest declared value insurable on a white-glove pickup for this category). Any principal may read a category policy; the `Authenticator` and `Seller` and `Buyer` roles all have read access to support their own workflows.

### 3.2. Consignment Intake and White-Glove Pickup

A `Seller` (or an `OpsAdmin` acting on their behalf) opens a consignment by creating a `ConsignmentItem` with the owning `seller_id`, the `category`, the `brand`, the `title`, a seller-declared `declared_value_cents`, and an `intake_channel`. The `intake_channel` determines how the item reaches the platform and therefore its starting `status`. A `DROP_OFF` item is received on the spot: it is created directly in `RECEIVED` status, moving from the notional `INTAKE_REQUESTED` state to `RECEIVED` automatically at creation. A `PICKUP` item, by contrast, is created in `INTAKE_REQUESTED` and stays there until a concierge collects it. The item's `category` resolves the matching `CategoryPolicy` for all downstream pricing and eligibility decisions.

White-glove collection is staffed by concierges and vehicles. An `OpsAdmin` creates a `Concierge` from a `name` and a `region`, and a `Vehicle` from a `plate`; both are created `ACTIVE`. To arrange a collection, a `Seller` (or `OpsAdmin`) schedules a `PickupAppointment` for a `PICKUP`-channel item (scheduling does not itself re-validate the item's `intake_channel` or its status), supplying the `item_id`, the assigned `concierge_id`, the assigned `vehicle_id`, and the occupation window bounded by `window_start` (inclusive) and `window_end` (exclusive). The appointment is created `SCHEDULED`, and its `seller_id` and `declared_value_cents` are copied from the item.

Scheduling a pickup runs three domain checks after existence and ownership have passed, in this order (existence also requires the item's category to have a `CategoryPolicy`, else `ERR_CATEGORY_POLICY_NOT_FOUND` (HTTP 404), checked before ownership). First, the item's `declared_value_cents` must be at most the `pickup_insurance_cap_cents` of the item's category; a declared value above the cap is rejected with `ERR_PICKUP_VALUE_EXCEEDS_INSURANCE` (HTTP 422). Second, the assigned concierge must be free. A concierge requires a one-hour travel buffer — sixty minutes — around every appointment: extend the requested window by sixty minutes before `window_start` and sixty minutes after `window_end`, and if that extended interval overlaps the window of any other appointment already `SCHEDULED` for the same concierge, the request is rejected with `ERR_CONCIERGE_UNAVAILABLE` (HTTP 409). Equivalently, two of one concierge's appointments must be separated by at least sixty minutes. Third, the assigned vehicle must be free, but a vehicle carries no travel buffer: its requested half-open window from `window_start` inclusive to `window_end` exclusive must not overlap any other window `SCHEDULED` for the same vehicle. Because the window is half-open, two appointments that merely touch at a boundary — one ending at the exact instant the next begins — do not overlap and are both allowed; any true overlap is rejected with `ERR_VEHICLE_UNAVAILABLE` (HTTP 409).

When the field agent arrives, a `ConciergeAgent` (or `OpsAdmin`) completes the appointment, which requires it to be in `SCHEDULED` (otherwise `ERR_PICKUP_INVALID_STATE`, HTTP 409) and drives it to `COMPLETED`. Completing the pickup cascades to the item, advancing it from `INTAKE_REQUESTED` to `RECEIVED` — the same received state a drop-off reaches immediately.

### 3.3. Authentication and Grading

Once an item is `RECEIVED`, an `Authenticator` examines it. The authenticate action requires the item to be in `RECEIVED` status; attempting it on an item in any other state is rejected with `ERR_ITEM_INVALID_STATE` (HTTP 409). The authenticator submits a `verdict`, a `condition_grade`, and optional free-text `notes`. The submitted `verdict` is recorded on the item as `authenticity_verdict` and may be `AUTHENTIC`, `COUNTERFEIT`, or `INCONCLUSIVE`; the `condition_grade` may be `A`, `B`, `C`, or `D`, where `A` is the best condition and `D` the worst. Every authentication also stamps the item with the `authenticator_id` (the opaque `X-User-ID` of the grading authenticator) and the `authenticated_at` logical-clock instant.

The two verdict outcomes are symmetric transitions out of `RECEIVED`. When the `verdict` is `AUTHENTIC`, the item advances to `AUTHENTICATED`; the server records `authenticity_verdict`, `condition_grade`, `authenticator_id`, and `authenticated_at`, and recomputes the derived `listable` flag. When the `verdict` is `COUNTERFEIT` or `INCONCLUSIVE`, the item instead moves to `REJECTED`, a terminal state, and is returned to the seller; the server still records the `authenticity_verdict` and `condition_grade`, but a rejected item can never be listed.

The `listable` flag is `true` only when two conditions both hold: the `authenticity_verdict` is `AUTHENTIC`, and the item's `condition_grade` is no worse than its category's `listable_min_condition_grade`. Because `A` is best and `D` is worst, "no worse than" means the item's grade is at least as good as the threshold grade — if the policy's `listable_min_condition_grade` is `C`, then grades `A`, `B`, and `C` are listable and `D` is not. Crucially, a low grade does not reject an item at authentication time: an authentic-but-below-threshold item still becomes `AUTHENTICATED` (with `listable` computed as `false`), and the grade eligibility gate is enforced later, at publish.

### 3.4. Listing and Commission Locking

A `Seller` (or `OpsAdmin`) drafts a `Listing` from an item by supplying the `item_id` and a `list_price_cents` asking price; the item's status is not checked when the draft is created (the `AUTHENTICATED` requirement is enforced only at publish, below), so a draft may be created from an item in any status. The listing is created in `DRAFT`, and its `seller_id` and `category` are denormalised from the referenced item.

Publishing takes the listing from `DRAFT` to `ACTIVE` and locks in the economics of any future sale. Three preconditions are checked in order after existence — which also requires the referenced item's category to have a `CategoryPolicy`, else `ERR_CATEGORY_POLICY_NOT_FOUND` (HTTP 404), resolved before ownership — and ownership. The listing itself must be in `DRAFT`, or the attempt is rejected with `ERR_LISTING_INVALID_STATE` (HTTP 409). The referenced item must be in `AUTHENTICATED` status, or the attempt is rejected with `ERR_ITEM_NOT_AUTHENTICATED` (HTTP 409). Finally, the item must be listable — its `authenticity_verdict` must be `AUTHENTIC` and its `condition_grade` no worse than the category's `listable_min_condition_grade` — or the attempt is rejected with `ERR_ITEM_GRADE_NOT_LISTABLE` (HTTP 422). This last check is why an authentic item graded below the category threshold clears authentication but fails at publish.

A successful publish performs several bound-together effects and increments the listing's `version` by one. It captures `commission_tier_locked` as the seller's current `tier`, freezing the commission economics against any later tier change. It computes and pins `commission_rate_locked_pct`: start from the category's `base_commission_pct`, subtract the tier discount — zero for a `STANDARD` seller, three hundredths (`0.03`) for a `PREMIER` seller, five hundredths (`0.05`) for an `ELITE` seller — and take the greater of that discounted rate and the platform minimum commission floor of `0.05`; the locked rate is never allowed below that five-percent floor. It computes the `provisional_payout_cents` estimate as the `list_price_cents` minus the commission on that asking price, where the commission is `list_price_cents` multiplied by `commission_rate_locked_pct` and rounded half up to whole cents. It pins `min_offer_cents` as `list_price_cents` multiplied by the category's `min_offer_pct`, rounded half up to whole cents. And it pulls the item along, advancing it from `AUTHENTICATED` to `LISTED`.

### 3.5. The Closet: Offers, Counter-Offers, and Direct Buy

An active listing can be bought two ways: outright at the asking price, or through a negotiated offer.

A `Buyer` buys outright by referencing the `listing_id` and their own `buyer_id`. The listing must currently be `ACTIVE`, or the purchase is rejected with `ERR_LISTING_NOT_ACTIVE` (HTTP 409). A successful direct buy creates a `Sale` whose `sale_channel` is `DIRECT` and whose `sale_price_cents` is the listing's `list_price_cents`, with the sale's `buyer_id` taken from the acting buyer. Creating the sale drives the listing from `ACTIVE` to `SOLD`, pulls the item from `LISTED` to `SOLD`, and declines every sibling offer on that listing still in `PENDING` or `COUNTERED` (moving each to `DECLINED`); the listing's `version` increments by one.

Alternatively, a `Buyer` makes an `Offer` by supplying the `listing_id`, their `buyer_id`, an `amount_cents`, and the `expected_listing_version` described in §2.6. A new offer starts in `PENDING` with `round_number` at 1 and an `expires_at` set to its creation instant plus seventy-two hours; creating it increments the listing's `version` by one. The listing must be `ACTIVE` (otherwise `ERR_LISTING_NOT_ACTIVE`), the `expected_listing_version` must match the listing's current `version` (otherwise `ERR_STALE_LISTING_VERSION`), and the `amount_cents` must be at least the listing's `min_offer_cents` floor, or the offer is rejected with `ERR_OFFER_BELOW_FLOOR` (HTTP 422).

Negotiation is cyclic between `PENDING` and `COUNTERED`. A `Seller` counters a `PENDING` offer, moving it to `COUNTERED` and setting `counter_amount_cents` to their counter (supplied as the `counter_amount_cents` input). A `Buyer` may counter back a `COUNTERED` offer, moving it to `PENDING`: this sets the offer's `amount_cents` to the buyer's new figure, clears `counter_amount_cents`, and increments `round_number` by one. Either counter requires the listing to still be `ACTIVE` and the offer to be in the state that admits the move (otherwise `ERR_OFFER_INVALID_STATE`, HTTP 409), and the new target amount must meet the `min_offer_cents` floor or the counter is rejected with `ERR_OFFER_BELOW_FLOOR`.

Acceptance closes the negotiation and is likewise symmetric across the two directions. When a `Seller` accepts a `PENDING` offer, it moves to `ACCEPTED` and the `agreed_price_cents` is set to the offer's `amount_cents`. When a `Buyer` accepts a `COUNTERED` offer, it moves to `ACCEPTED` and the `agreed_price_cents` is set to the `counter_amount_cents`. Either acceptance requires the listing to be `ACTIVE` (otherwise `ERR_LISTING_NOT_ACTIVE`) and cascades identically: the listing goes from `ACTIVE` to `SOLD`, a `Sale` is created with `sale_channel` `OFFER`, `sale_price_cents` equal to the `agreed_price_cents`, and `offer_id` referencing the accepted offer; the item goes from `LISTED` to `SOLD`; and every other sibling offer on the listing still in `PENDING` or `COUNTERED` is moved to `DECLINED`. An offer moves from `PENDING` or `COUNTERED` to `DECLINED` only as a system cascade — when a direct buy or an accepted sibling offer closes the listing, every other still-open offer on it is declined; there is no standalone decline endpoint. Finally, an offer whose `expires_at` has passed on the logical clock is treated as `EXPIRED` the moment it is next read, countered, or accepted; acting on such an offer therefore fails the state precondition with `ERR_OFFER_INVALID_STATE`.

### 3.6. Payment, Fulfilment, and Order Totals

Every sale carries two independent state axes: a `payment_status` that runs `PENDING` → `CAPTURED` → `REFUNDED`, and a `fulfillment_status` that runs `AWAITING_SHIPMENT` → `SHIPPED` → `DELIVERED` → `RETURNED`. A new sale begins with `payment_status` `PENDING` and `fulfillment_status` `AWAITING_SHIPMENT`.

At the instant a sale is created — by either channel — its money fields are computed from the settled `sale_price_cents` and the item's `CategoryPolicy`. The `commission_rate_pct` is copied from the listing's locked `commission_rate_locked_pct`. The `commission_cents` is `sale_price_cents` multiplied by `commission_rate_pct`, rounded half up to whole cents. The `seller_net_payout_cents` — the seller's final payout basis — is `sale_price_cents` minus `commission_cents`. Because an accepted offer usually settles below the asking price, this final payout can diverge from the earlier provisional estimate whenever the sale price differs from the list price. The buyer's charges are then assembled in a pinned order, each component rounded before the next consumes it: first the `buyer_fee_cents` is the category's `buyer_fee_flat_cents` plus (`sale_price_cents` multiplied by the category's `buyer_fee_pct`, rounded half up to whole cents); then the `tax_cents` is (`sale_price_cents` plus the already-rounded `buyer_fee_cents`) multiplied by the eight-percent sales tax fraction (`0.08`), rounded half up to whole cents — the tax is deliberately levied on the price plus the rounded fee, not on the price alone; and finally the `order_total_cents` is `sale_price_cents` plus `buyer_fee_cents` plus `tax_cents`.

Fulfilment then proceeds through its transitions. A `Buyer` (or `OpsAdmin`) captures payment, moving `payment_status` from `PENDING` to `CAPTURED`; attempting capture on a sale whose `payment_status` is not `PENDING` is rejected with `ERR_SALE_PAYMENT_INVALID_STATE` (HTTP 409). A `Seller` (or `OpsAdmin`) marks the sale shipped, moving `fulfillment_status` from `AWAITING_SHIPMENT` to `SHIPPED`; this requires the cross-axis condition that `payment_status` already be `CAPTURED`, and shipping before payment is captured or from any state other than `AWAITING_SHIPMENT` is rejected with `ERR_SALE_FULFILLMENT_INVALID_STATE` (HTTP 409). A `Buyer` (or `OpsAdmin`) then confirms delivery, moving `fulfillment_status` from `SHIPPED` to `DELIVERED` — the same fulfilment-state error guards a confirm-delivery attempted from the wrong state.

Confirming delivery is the settlement trigger and fires a bundle of effects. It stamps `delivered_at` with the current logical clock and sets `return_window_ends_at` to `delivered_at` plus the category's `return_window_days` (the inclusive last instant a dispute may be filed). It creates a `Payout` for the seller in `SCHEDULED` status, whose `amount_cents` equals the sale's `seller_net_payout_cents` and whose `scheduled_release_at` is `return_window_ends_at` plus a one-day payout hold. It adds the sale's `seller_net_payout_cents` to the seller's `pending_payout_cents`. And it adds the sale's `order_total_cents` to the buyer's `lifetime_purchases_cents`.

### 3.7. Payout Settlement and Seller Tier Progression

Each delivered sale spawns exactly one `Payout`, whose `sale_id` and `seller_id` are denormalised from the sale. The payout's lifecycle protects the platform against premature payment while a return is still possible. When a dispute is filed against the sale, the payout cascades from `SCHEDULED` to `HELD`; should that dispute later resolve in the seller's favour, the hold is cleared and the payout cascades back from `HELD` to `SCHEDULED`.

An `OpsAdmin` releases a scheduled payout to the seller, moving it from `SCHEDULED` to `RELEASED`. Two conditions gate the release. The payout must be in `SCHEDULED` status: a payout that a filed dispute has already moved to `HELD` (or that is already `RELEASED` or `REVERSED`) is rejected with `ERR_PAYOUT_NOT_RELEASABLE` (HTTP 409). And the current logical clock must have reached the `scheduled_release_at` instant — release attempted before that instant is rejected with `ERR_PAYOUT_HOLD_ACTIVE` (HTTP 409). On release, the server stamps `released_at` with the current clock and adjusts the seller's ledger: it subtracts the payout's `amount_cents` from `pending_payout_cents`, adds it to `released_payout_cents`, and adds it to `lifetime_net_sales_cents`.

Releasing a payout is also the only event that can change a seller's loyalty `tier`, which is recomputed from the freshly updated `lifetime_net_sales_cents`. The thresholds are inclusive: a lifetime net sales total of at least fifty thousand dollars — 5,000,000 cents — earns `ELITE`; a total of at least ten thousand dollars — 1,000,000 cents — but below the elite threshold earns `PREMIER`; anything below the premier threshold is `STANDARD`. Because the boundary is inclusive, a seller sitting exactly at 1,000,000 cents is `PREMIER`, while one at 999,999 cents remains `STANDARD`. A tier change here affects only listings published afterwards; listings already published keep the commission rate they locked in.

### 3.8. Disputes, Returns, and Refunds

A `Buyer` (or `OpsAdmin`) files a `Dispute` against a delivered sale by supplying the `sale_id`, a dispute `type`, and a free-text `reason`. The `type` is one of `AUTHENTICITY`, `CONDITION`, or `CHANGE_OF_MIND`, and it selects the refund treatment. Filing runs several checks in order after existence and ownership: the sale must be disputable — its `fulfillment_status` must be `DELIVERED` and not yet `RETURNED`, or the request is rejected with `ERR_SALE_NOT_DISPUTABLE` (HTTP 409); there must be no other dispute already in `FILED` status for the sale, or it is rejected with `ERR_DISPUTE_ALREADY_EXISTS` (HTTP 409); and the current logical clock must be at or before the sale's `return_window_ends_at`, or it is rejected with `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 409). A successful filing creates the dispute in `FILED` status and cascades the sale's `SCHEDULED` payout to `HELD`, freezing the seller's money while the case is open.

An `OpsAdmin` resolves a filed dispute by supplying an `outcome` of either `SELLER` or `BUYER`, and the resolution must act on a dispute in `FILED` status or it is rejected with `ERR_DISPUTE_INVALID_STATE` (HTTP 409). The resolution stamps `resolved_at` and records the submitted `outcome` verbatim (the value `SELLER` or `BUYER`). The two outcomes are handled with equal weight.

A resolution in the seller's favour (`outcome` `SELLER`, which drives the dispute's own `status` to `RESOLVED_SELLER`) sets both `refund_amount_cents` and `restocking_fee_cents` to zero, leaves the sale otherwise untouched, and cascades the sale's `HELD` payout back to `SCHEDULED` so it can later be released normally.

A resolution in the buyer's favour (`outcome` `BUYER`, which drives the dispute's own `status` to `RESOLVED_BUYER`) computes the refund and unwinds the sale. The `refund_amount_cents` and `restocking_fee_cents` are computed by variant on the dispute `type`. For an `AUTHENTICITY` or `CONDITION` dispute, the `restocking_fee_cents` is zero and the `refund_amount_cents` is the full `order_total_cents` — the buyer gets back the sale price, the buyer fee, and the tax in their entirety. For a `CHANGE_OF_MIND` dispute, the `restocking_fee_cents` is the `sale_price_cents` multiplied by the ten-percent restocking fraction (`0.10`), rounded half up to whole cents, and the `refund_amount_cents` is the `sale_price_cents` plus the `tax_cents` minus that `restocking_fee_cents` — note the `buyer_fee_cents` is non-refundable on a change-of-mind return. In both buyer-favour cases the sale's `payment_status` moves from `CAPTURED` to `REFUNDED`, crediting the computed `refund_amount_cents` to the buyer, and the sale's `fulfillment_status` moves from `DELIVERED` to `RETURNED`. That return cascades outward: the buyer's `lifetime_purchases_cents` is reduced by the sale's `order_total_cents` (the exact reversal of the delivery credit); the sale's payout, whether it was `SCHEDULED` or `HELD`, moves to `REVERSED`, subtracting its `amount_cents` from the seller's `pending_payout_cents` and adding it to the seller's `reversed_payout_cents`. The item's fate depends on the dispute type: an `AUTHENTICITY` or `CONDITION` buyer-favour resolution quarantines the item, moving it from `SOLD` to `DISPOSED` (a terminal state, never relisted), whereas a `CHANGE_OF_MIND` buyer-favour resolution relists it, moving the item from `SOLD` back to `LISTED` and its listing from `SOLD` back to `ACTIVE`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify an existing resource — including the state-transition actions and the logical-clock control — return `200 OK`. All paths below are mounted under the `/consignment` prefix (the logical-clock control excepted).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/consignment/sellers` | Register a consignor | OpsAdmin |
| GET | `/consignment/sellers/{id}` | Get a seller (tier, ledgers) | OpsAdmin, Seller |
| POST | `/consignment/buyers` | Register a buyer | OpsAdmin |
| GET | `/consignment/buyers/{id}` | Get a buyer (lifetime purchases) | OpsAdmin, Buyer |
| POST | `/consignment/category-policies` | Create a per-category pricing/return policy | OpsAdmin |
| GET | `/consignment/category-policies/{id}` | Get a category policy | OpsAdmin, Seller, Buyer, Authenticator |
| POST | `/consignment/items` | Create a consignment intake | Seller, OpsAdmin |
| GET | `/consignment/items` | List items (filtered) | OpsAdmin, Seller |
| GET | `/consignment/items/{id}` | Get an item | OpsAdmin, Seller, Authenticator |
| POST | `/consignment/items/{id}/authenticate` | Authenticate and grade a received item | Authenticator |
| POST | `/consignment/listings` | Create a DRAFT listing from an item | Seller, OpsAdmin |
| GET | `/consignment/listings` | List listings (filtered) | OpsAdmin, Seller, Buyer |
| GET | `/consignment/listings/{id}` | Get a listing | OpsAdmin, Seller, Buyer, Authenticator |
| POST | `/consignment/listings/{id}/publish` | Publish a listing (DRAFT to ACTIVE) | Seller, OpsAdmin |
| POST | `/consignment/offers` | Make an offer on an active listing | Buyer |
| GET | `/consignment/offers` | List offers (filtered) | OpsAdmin, Seller, Buyer |
| GET | `/consignment/offers/{id}` | Get an offer | OpsAdmin, Seller, Buyer |
| POST | `/consignment/offers/{id}/counter` | Counter an offer | Seller, Buyer |
| POST | `/consignment/offers/{id}/accept` | Accept an offer or counter (creates a Sale) | Seller, Buyer |
| POST | `/consignment/sales` | Direct-buy an active listing at list price | Buyer, OpsAdmin |
| GET | `/consignment/sales` | List sales (filtered) | OpsAdmin, Seller, Buyer |
| GET | `/consignment/sales/{id}` | Get a sale | OpsAdmin, Seller, Buyer |
| POST | `/consignment/sales/{id}/capture-payment` | Capture payment (PENDING to CAPTURED) | Buyer, OpsAdmin |
| POST | `/consignment/sales/{id}/ship` | Mark shipped (AWAITING_SHIPMENT to SHIPPED) | Seller, OpsAdmin |
| POST | `/consignment/sales/{id}/confirm-delivery` | Confirm delivery (SHIPPED to DELIVERED) | Buyer, OpsAdmin |
| GET | `/consignment/sales/{id}/payouts` | List payouts for a sale | OpsAdmin, Seller |
| GET | `/consignment/sales/{id}/disputes` | List disputes for a sale | OpsAdmin, Seller, Buyer |
| POST | `/consignment/payouts/{id}/release` | Release a scheduled payout to the seller | OpsAdmin |
| POST | `/consignment/disputes` | File a dispute on a delivered sale | Buyer, OpsAdmin |
| POST | `/consignment/disputes/{id}/resolve` | Resolve a filed dispute | OpsAdmin |
| POST | `/consignment/concierges` | Create a white-glove concierge agent | OpsAdmin |
| POST | `/consignment/vehicles` | Create a pickup vehicle | OpsAdmin |
| POST | `/consignment/pickups` | Schedule a white-glove pickup | Seller, OpsAdmin |
| GET | `/consignment/pickups` | List pickups (filtered) | OpsAdmin, Seller |
| GET | `/consignment/pickups/{id}` | Get a pickup appointment | OpsAdmin, Seller |
| POST | `/consignment/pickups/{id}/complete` | Complete a pickup (SCHEDULED to COMPLETED) | ConciergeAgent, OpsAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_MISSING_AUTH_CONTEXT` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_SELLER_NOT_FOUND` | 404 Not Found |
| `ERR_BUYER_NOT_FOUND` | 404 Not Found |
| `ERR_CATEGORY_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_SALE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYOUT_NOT_FOUND` | 404 Not Found |
| `ERR_DISPUTE_NOT_FOUND` | 404 Not Found |
| `ERR_CONCIERGE_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_PICKUP_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_INVALID_STATE` | 409 Conflict |
| `ERR_ITEM_NOT_AUTHENTICATED` | 409 Conflict |
| `ERR_LISTING_INVALID_STATE` | 409 Conflict |
| `ERR_LISTING_NOT_ACTIVE` | 409 Conflict |
| `ERR_OFFER_INVALID_STATE` | 409 Conflict |
| `ERR_SALE_PAYMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SALE_FULFILLMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SALE_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_DISPUTE_INVALID_STATE` | 409 Conflict |
| `ERR_PAYOUT_NOT_RELEASABLE` | 409 Conflict |
| `ERR_PICKUP_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_LISTING_VERSION` | 412 Precondition Failed |
| `ERR_ITEM_GRADE_NOT_LISTABLE` | 422 Unprocessable Entity |
| `ERR_DISPUTE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_OFFER_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_PICKUP_VALUE_EXCEEDS_INSURANCE` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_PAYOUT_HOLD_ACTIVE` | 409 Conflict |
| `ERR_CONCIERGE_UNAVAILABLE` | 409 Conflict |
| `ERR_VEHICLE_UNAVAILABLE` | 409 Conflict |
