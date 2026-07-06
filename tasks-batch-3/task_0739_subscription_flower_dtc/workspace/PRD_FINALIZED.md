# Subscription-Flower DTC API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Subscription-Flower DTC API, the back-end platform for a direct-to-consumer subscription flower business. Subscribers choose a cadence, bouquet size, and style, and receive recurring bouquet deliveries that draw on freshly sourced stems held under a cold chain. The platform must reconcile two very different rhythms at once: the customer-facing rhythm of subscribing, pausing, skipping, changing, cancelling, and winning customers back, and the operational rhythm of registering stem lots, reserving and committing stems against perishable inventory, substituting varieties when supply demands it, booking delivery windows on carrier routes, and marking deliveries complete.

Layered on top of both rhythms is money. Every billing cycle opens a renewal charge whose amount is derived from the plan, the chosen size, and optional add-ons, less any active discount; payments can succeed, fail, or be refunded; and refunds, skip credits, and adjustments accumulate in a per-customer wallet. Because operational actions (sourcing, substitution, shipping) and financial actions (renewals, payment outcomes, refunds) can each cascade across several resources within a single request, the system settles all of those cascades synchronously and keeps two conserved quantities exact at all times: physical stems and money. This specification defines the entities, their state machines, the calculations that price and value them, the validation order that guards every request, and the endpoints through which all of this is exercised.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and conventions that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Customer`, `FulfillmentOps`, `BillingAdmin`, and `PlatformAdmin`. Their responsibilities do not overlap:

- A `Customer` is a subscriber acting on their own subscriptions, shipments, wallet, and win-back offers. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks compare the targeted resource back to that identity: a subscription's `customer_id`, a shipment's owning subscription's `customer_id`, and a win-back offer's `customer_id` must all equal `X-User-ID`. When a customer targets a resource they do not own, the request is rejected with `ERR_NOT_OWNER`; the equivalent rejection for win-back offers (and for a redeem body naming a subscription the caller does not own) is `ERR_OFFER_NOT_OWNED`.
- A `FulfillmentOps` operator manages stem lots, allocations, and shipment fulfillment. When `X-User-Role` is `FulfillmentOps`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `BillingAdmin` operator runs renewals, payments, and refunds. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- A `PlatformAdmin` owns configuration — plans, carrier routes, substitution rules, customer accounts — and the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, must be at least 1, and may be at most 100. The `offset` parameter counts how many leading items to skip; it defaults to 0 and must be zero or greater. A `limit` outside the range of 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` reflects the full number of matching items before pagination and `has_more` indicates whether items remain beyond the returned page.

### 2.4. Common Resource Properties

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry an `updated_at` timestamp (refreshed on every mutation) and an integer `version` that begins at its initial value and increments by one on every mutation of the resource. Together `updated_at` and `version` provide an audit trail and the basis for optimistic concurrency control.

Two resources are deliberately lighter: a `WalletEntry` and a `SubstitutionRule` are append-only or configuration records that are never mutated after creation, so they carry only `id` and `created_at` — they have no `updated_at` field and no `version` field. Every other resource in the system (customers, plans, subscriptions, shipments, stem lots, stem allocations, carrier routes, charges, and win-back offers) carries the full set of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Monetary Values, Quantities, and Precision

All monetary amounts in the system are integers denominated in cents; there are no fractional-cent values stored or returned. Whenever a calculation produces a non-integer cent amount, it is resolved to a whole number of cents using the round-half-up method (a value exactly halfway between two integers rounds up). This applies to renewal pricing, per-shipment values, stem valuations, per-line stem costs, and refunds alike. Fractions used inside those calculations — a subscription's discount fraction, a lot's shrinkage fraction, and a substitution rule's maximum substitution fraction — are proper decimal fractions rather than percentages of a stored integer.

Stems are conserved as whole units: for any stem lot, its original `quantity_total` always equals its current `quantity_available` plus the sum of stems currently held by active allocations. Money is likewise conserved: a customer's wallet balance always equals the sum of that customer's wallet entries. These two invariants must hold after every request completes.

### 2.6. The Logical Clock and Time Semantics

The system runs on a logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any client sets it, every time-dependent computation uses that default — the server never falls back to real wall-clock time. A `PlatformAdmin` may advance the clock to a supplied instant for test-driving purposes; advancing the clock does not eagerly rewrite stored rows, but it changes the outcome of every time-dependent computation evaluated on the next read, including stem-lot freshness, the skip cutoff, and win-back offer expiry.

Time comparisons are evaluated at second granularity. Where a boundary is described as inclusive, the boundary instant itself falls on the side stated by the rule that defines it (see cold-chain freshness in §3.5 and the skip window in §3.4).

### 2.7. Parallel Status Axes and Cascading Consistency

A `Subscription` tracks two independent status axes on the same record. Its `lifecycle_status` (one of `ACTIVE`, `PAUSED`, `CANCELLED`, `EXPIRED`) governs the customer-facing lifecycle, while its `billing_status` (one of `CURRENT`, `PAST_DUE`) governs its financial standing. The two evolve independently: a subscription can be `ACTIVE` while `PAST_DUE`, or `PAUSED` while `CURRENT`. A subscription begins life with `lifecycle_status` of `ACTIVE` and `billing_status` of `CURRENT`, and the only terminal condition is `lifecycle_status` of `EXPIRED`.

Many operations mutate more than one resource in a single request. The system settles all such cascades synchronously, before the triggering request returns. When a cascade removes stems that were being held — through a skip, a shipment cancellation, or a subscription cancellation — the released allocations move to `RELEASED` and the affected stem lot's available quantity is restored in the same request, so the stem-conservation invariant of §2.5 always holds on read. Any operation that mutates a resource refreshes that resource's `updated_at` and increments its `version` by one; where an operation bumps a parent subscription's `version` (for example, pause, resume, change, cancel, renew, or a billing cascade), that increment is what a stale concurrent writer will later collide with under §2.8.

### 2.8. Optimistic Concurrency Control

Exactly one operation is guarded by optimistic concurrency control: applying a size, style, vase, or plan change to a subscription. A change request must include `expected_subscription_version`, carrying the `version` of the target subscription that the client last observed. This field is mandatory for the change operation; a change request without it is malformed. Before applying the change, the server compares `expected_subscription_version` to the subscription's current `version`. If they do not match — because a prior change, a renewal, or a billing cascade advanced the subscription's `version` since the client last read it — the request is rejected with `ERR_STALE_VERSION` and HTTP status 412, so that a client can never silently overwrite configuration it never observed. No other endpoint accepts or requires a version field.

### 2.9. Request Validation Order

When more than one validation could reject a request, the checks are evaluated in a fixed priority order, and the first failing check determines the error returned. The order is:

1. **Authentication.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be a recognized one, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The acting role must be permitted for the endpoint, else `ERR_UNAUTHORIZED` (403).
3. **Existence.** Every resource named by a path identifier must exist, validated left to right (see §2.10), else the corresponding not-found error (404).
4. **Well-formedness.** The body must be well-formed — required fields present, enum values valid, numbers within range, and pagination parameters within their bounds — else `ERR_INVALID_REQUEST` (400).
5. **State.** The target resource must be in a state from which the requested transition is legal, including cross-entity state preconditions; failures surface as `ERR_INVALID_STATE`, `ERR_SHIPMENT_NOT_SKIPPABLE`, `ERR_OFFER_NOT_REDEEMABLE`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, or `ERR_LOT_EXPIRED` (all 409).
6. **Concurrency.** For a subscription change, `expected_subscription_version` must match the current `version`, else `ERR_STALE_VERSION` (412).
7. **Ownership.** The acting customer must own the targeted resource, else `ERR_NOT_OWNER` or `ERR_OFFER_NOT_OWNED` (403).
8. **Temporal windows.** Time-window gates must be satisfied, else `ERR_SKIP_WINDOW_CLOSED` or `ERR_OFFER_EXPIRED` (422).
9. **Resource constraints.** Stem availability, route-window non-overlap, lot-hold spacing, and substitution policy must hold, else `ERR_INSUFFICIENT_STEMS`, `ERR_ROUTE_WINDOW_CONFLICT`, `ERR_LOT_HOLD_CONFLICT`, or `ERR_SUBSTITUTION_NOT_ALLOWED` (422).
10. **Fiscal rules.** Fiscal gates must hold, else `ERR_BILLING_PAST_DUE` or `ERR_REFUND_EXCEEDS_CAPTURED` (402 and 422 respectively).

The consequence of this ordering is deliberate. For a subscription change, a stale-version rejection (`ERR_STALE_VERSION`) is decided before the ownership check, which in turn is decided before the past-due fiscal block (`ERR_BILLING_PAST_DUE`). For a shipment skip, the not-skippable state check (`ERR_SHIPMENT_NOT_SKIPPABLE`) precedes the ownership check, which precedes the cutoff-window check (`ERR_SKIP_WINDOW_CLOSED`).

### 2.10. Nested Resource Retrieval

Endpoints whose paths contain more than one resource identifier are validated from left to right. The first identifier in the path that does not resolve to an existing resource determines the not-found error returned, before any deeper identifier or any body rule is considered. Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_STEM_LOT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, and `ERR_OFFER_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Catalog and Configuration

Before subscribers can transact, a `PlatformAdmin` populates the catalog. A plan is created with a `name`, a `cadence`, and a `base_fee_cents`, and may optionally specify a `default_style` and whether it `is_active`. The `cadence` is one of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`, and it fixes how many deliveries a billing cycle contains: four for `WEEKLY`, two for `BIWEEKLY`, and one for `MONTHLY`. The `base_fee_cents` is the plan's monthly base fee in cents before any size, vase, or discount adjustment, and must be zero or greater. The `default_style` is the plan's default bouquet style — one of `ROUND`, `GARDEN`, or `EUROPEAN`, defaulting to `ROUND` — and `is_active` (defaulting to true) indicates whether the plan accepts new subscriptions.

A `PlatformAdmin` also defines carrier routes and substitution policy. A carrier route carries a `zone` label and a `service_date` (the UTC date the route runs, into which delivery windows are booked). A substitution rule declares a `from_variety` (the variety being substituted away from), a `to_variety` (the variety substituted in), whether the substitution is `allowed` (defaulting to true), the `max_substitution_pct` (the maximum fraction of a shipment that may be substituted under the rule, defaulting to 0.5), and a `quality_floor_grade` (the minimum acceptable grade for the substitute, one of `A`, `B`, or `C`, defaulting to `B`). Substitution rules can be listed and optionally filtered by `from_variety`.

Customer accounts are created by a `PlatformAdmin` with an `email` (non-empty and unique across customers), a `full_name`, and an optional `default_zip` (the default delivery ZIP, which may be absent). A new customer's account `status` begins as `ACTIVE` and may otherwise be `CLOSED`. Three fields on a customer are computed rather than supplied: `lifetime_cycles` counts the customer's delivered shipments and starts at 0; `loyalty_tier` is derived from that count and starts at `BRONZE`; and `wallet_credit_cents` is the running sum of the customer's wallet entries and starts at 0. The loyalty tier is `BRONZE` while the customer has fewer than two delivered cycles, becomes `SILVER` once delivered cycles reach two and while they remain below five, and becomes `GOLD` once delivered cycles reach five. Fetching a customer returns these computed values alongside the stored ones.

Finally, a `PlatformAdmin` controls the logical clock described in §2.6, supplying the target instant as `to_iso8601`.

### 3.2. Subscribing and Opening the First Cycle

A subscriber (or a `PlatformAdmin` acting on their behalf) opens a subscription by naming the owning `customer_id`, the `plan_id` it follows, and the bouquet `size` — one of `PETITE`, `ORIGINAL`, `DELUXE`, or `GRAND`. The request may also set `style` (defaulting to `ROUND`), `vase_addon` (defaulting to false), `is_gift` (defaulting to false), an optional `occasion` label, an optional `gift_message`, and an optional `start_date`. When `start_date` is omitted, the subscription starts at the current logical clock instant.

Creating a subscription immediately computes its `renewal_price_cents`, the per-cycle price. The gross price is the plan's `base_fee_cents` plus a size upcharge plus a vase upcharge. The size upcharge is 0 cents for `PETITE`, 0 cents for `ORIGINAL`, 1500 cents for `DELUXE`, and 3000 cents for `GRAND`. The vase upcharge is 1200 cents when `vase_addon` is true and 0 cents otherwise. From that gross, a discount is applied: the raw discount is the gross multiplied by the subscription's `discount_pct` (a fraction that is 0 for a brand-new subscription), rounded half up to whole cents; the applied discount is the smaller of that raw discount and a cap of 1000 cents; and the net price is the larger of (gross minus applied discount) and a floor of 2000 cents. That net value is `renewal_price_cents`.

Opening the subscription also seeds its schedule and its first charge. The subscription's `current_cycle_index` starts at 1, and its `next_renewal_date` is set to the start instant plus 30 days (a billing cycle is 30 days long). A renewal `Charge` is created for cycle 1 in `PENDING` status, whose `amount_cents` equals the freshly computed `renewal_price_cents`. The system then creates one shipment per delivery in the cycle — four, two, or one shipment according to the plan's cadence — each in `SCHEDULED` status and tagged with `cycle_index` 1. The k-th shipment (counting from zero) has its `scheduled_delivery_date` set to the start instant plus a 2-day first-delivery lead plus a per-cadence spacing multiplied by k, where the spacing is 7 days for `WEEKLY`, 14 days for `BIWEEKLY`, and 30 days for `MONTHLY`. Each shipment copies the subscription's `occasion` and `gift_message` onto its own `occasion` and `gift_message` fields at creation. A subscription's `lifecycle_status`, `billing_status`, `discount_pct`, and `renewal_price_cents` are all readable, along with the current `version`, when the subscription is fetched.

### 3.3. Pausing, Resuming, and Changing a Subscription

A subscriber can pause an `ACTIVE` subscription, moving its `lifecycle_status` from `ACTIVE` to `PAUSED`; the request may include a `resume_date`, in which case the subscription's `paused_until` is set to that instant, and the subscription's `version` increments. Resuming reverses this: a `PAUSED` subscription returns to `ACTIVE`, `paused_until` is cleared, and the `version` increments again. Both actions require that the acting customer own the subscription, and each is legal only from its respective source state.

Changing a subscription lets a subscriber adjust the `size`, `style`, `vase_addon`, or `plan_id` for future cycles. Any subset of those four may be supplied, and the request must additionally carry `expected_subscription_version` for the optimistic-concurrency check described in §2.8. A successful change recomputes `renewal_price_cents` (using the same gross/discount/cap/floor rule as at creation, so the new configuration prices the next renewal) and increments the subscription's `version`. A change is refused while the subscription is `PAST_DUE`: the fiscal gate rejects it with `ERR_BILLING_PAST_DUE`. As established by the validation order in §2.9, the stale-version check is evaluated before the ownership check, which is evaluated before this past-due fiscal block.

### 3.4. Skipping a Delivery

A subscriber may skip an upcoming delivery, moving a shipment from `SCHEDULED` to `SKIPPED`. A skip is only legal while the shipment is still `SCHEDULED`; attempting it on a shipment in any other status is rejected with `ERR_SHIPMENT_NOT_SKIPPABLE`. The acting customer must own the shipment's subscription. The skip is also time-boxed: it is permitted only while the current logical clock instant is at or before the shipment's `scheduled_delivery_date` minus a 48-hour cutoff — the boundary itself is inclusive, so a skip exactly 48 hours ahead is still allowed, while a request past that point is rejected with `ERR_SKIP_WINDOW_CLOSED`.

When a skip succeeds, any stems still held for that shipment are released. Every `RESERVED` allocation on the shipment moves to `RELEASED`, and each released allocation restores its lot's `quantity_available` by the stems it had held. The customer is then credited: a wallet entry is created with `reason` of `SKIP_CREDIT` and a positive `amount_cents` equal to the per-shipment value of the subscription. That per-shipment value is the subscription's `renewal_price_cents` divided by the number of deliveries in the cycle (four for `WEEKLY`, two for `BIWEEKLY`, one for `MONTHLY`), rounded half up to whole cents.

### 3.5. Fulfillment: Sourcing, Allocation, and the Cold Chain

Fulfillment operates on perishable inventory. A `FulfillmentOps` operator registers a stem lot with a `variety`, a quality `grade` (one of `A`, `B`, or `C`), a `quantity_total` (stems originally received, which must be greater than zero), a `unit_cost_cents` (wholesale cost per stem, zero or greater), a `sourced_at` instant (when the lot entered the cold chain), and a `shelf_life_hours` (cold-chain shelf life, greater than zero). A lot exposes three computed fields on read: `quantity_available`, `usable_until`, and `cold_chain_state`. The lot's `usable_until` is its `sourced_at` plus its `shelf_life_hours`. Its `cold_chain_state` is `FRESH` while the logical clock is strictly before `usable_until` and `EXPIRED` once the clock reaches or passes `usable_until` — the boundary instant itself counts as `EXPIRED`. Its `quantity_available` is `quantity_total` minus the sum of `quantity_reserved` across allocations on the lot whose status is `RESERVED` or `COMMITTED`.

Fulfillment of a shipment begins with sourcing. An operator starts sourcing a `SCHEDULED` shipment, advancing it to `SOURCING`, but only while the shipment's subscription is simultaneously `ACTIVE` on its lifecycle axis and `CURRENT` on its billing axis; if the subscription is not in that combined state, the attempt is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`. Once a shipment is `SOURCING`, the operator reserves stems for it. A reservation names the `lot_id` to draw from, the `quantity_reserved` (which must be greater than zero), and an exclusive cold-room hold window given by `hold_start` and `hold_end` (a closed interval). The reservation is refused with `ERR_INSUFFICIENT_STEMS` if `quantity_reserved` exceeds the lot's current `quantity_available`, and refused with `ERR_LOT_HOLD_CONFLICT` if the requested hold window collides with another active hold on the same lot — where a collision means the two closed hold intervals overlap or lie within a 30-minute clean buffer of each other, with the buffer boundary itself treated as a conflict: two holds separated by a gap of exactly 30 minutes still conflict, and only a gap strictly greater than 30 minutes clears the buffer. A successful reservation creates a `StemAllocation` in `RESERVED` status whose `shipment_id` ties it to the consuming shipment, debits the lot's `quantity_available` by `quantity_reserved`, and records a provisional `reserved_value_cents`.

Stem valuation follows a decay model tied to the lot's age. The base value of an allocation is its `quantity_reserved` multiplied by the lot's `unit_cost_cents`. The lot's age at any instant is the number of whole hours elapsed since `sourced_at`, rounded down. While the lot is `FRESH`, a shrinkage fraction applies: it is 0 when the age is under 24 hours, and 0.15 once the age reaches 24 hours or more. The `reserved_value_cents` is the base value multiplied by (one minus the shrinkage evaluated at the reservation time), rounded half up; because a lot is usually reserved when very fresh, this is typically the full base value. The `committed_value_cents`, computed later at commit time, is the base value multiplied by (one minus the shrinkage evaluated at that commit instant), rounded half up; a lot that has aged past 24 hours by commit time therefore loses 15% of its value. Until an allocation is committed, its `committed_value_cents` is absent.

Confirming sourcing closes out the `SOURCING` stage down one of two branches, and in both branches every `RESERVED` allocation on the shipment must belong to a lot that is still `FRESH` at commit time — if any required lot is `EXPIRED`, the confirmation is rejected with `ERR_LOT_EXPIRED`. In the first branch, the operator confirms with `substitution_applied` false: each `RESERVED` allocation moves to `COMMITTED` with its `committed_value_cents` set, the shipment's `stem_cost_cents` is computed, the shipment's `substitution_applied` stays false, and the shipment moves to `SOURCED`. In the second branch, the operator confirms with `substitution_applied` true and supplies the `from_variety` and `to_variety` of the substitution; this branch additionally requires that a substitution rule exist for that variety pair with `allowed` true, failing which the request is rejected with `ERR_SUBSTITUTION_NOT_ALLOWED`. When it succeeds, each `RESERVED` allocation likewise moves to `COMMITTED` with its `committed_value_cents` set and the shipment's `stem_cost_cents` is computed, but the shipment's `substitution_applied` is set to true and the shipment moves to `SUBSTITUTED`. The shipment's `stem_cost_cents` is computed by taking each `COMMITTED` allocation in turn, multiplying its `committed_value_cents` by a stem markup of 1.375 and rounding that line half up to whole cents, and then summing those per-line rounded amounts; the rounding is applied per line and only then summed, never by summing first and rounding once.

### 3.6. Shipping and Delivery

Once a shipment is `SOURCED` or `SUBSTITUTED`, a `FulfillmentOps` operator books it onto a carrier route, advancing it to `SHIPPED`. The request names the `route_id` and the `delivery_window_start` and `delivery_window_end` of the booked window; those three values are recorded on the shipment. The window is treated as half-open, and it must not overlap the window of any other shipment already `SHIPPED` on the same route; because the interval is half-open, two windows that merely touch at a shared endpoint are considered adjacent and are allowed, but any true overlap is rejected with `ERR_ROUTE_WINDOW_CONFLICT`.

Marking a `SHIPPED` shipment delivered advances it to `DELIVERED`, the terminal fulfilled state. Delivery is what grows loyalty: it increments the owning customer's `lifetime_cycles` by one and recomputes the customer's `loyalty_tier` from the new count using the `BRONZE`/`SILVER`/`GOLD` thresholds of §3.1.

### 3.7. Renewals, Payments, and Refunds

A `BillingAdmin` opens the next billing cycle for a subscription. Renewing increments `current_cycle_index`, advances `next_renewal_date` by another 30 days, recomputes `renewal_price_cents` and then resets `discount_pct` to 0 — in that order, so that any discount currently on the subscription is applied to exactly the cycle being opened and then cleared for subsequent cycles. Renewal creates a new `RENEWAL` charge in `PENDING` status and a fresh set of shipments for the new cycle (again four, two, or one according to cadence), and increments the subscription's `version`.

Charges move through payment. A charge's `kind` is `RENEWAL` for the cycle charges the system creates, though the model also allows a `kind` of `UPCHARGE`. A charge's `status` starts at `PENDING`, its `amount_cents` equals the subscription's `renewal_price_cents` at cycle open, and its `refunded_cents` starts at 0. A `BillingAdmin` simulates a payment attempt on a `PENDING` charge by supplying an `outcome`. A `SUCCEEDED` outcome captures the charge, moving it to `CAPTURED`; if that capture clears a subscription that was `PAST_DUE`, the subscription's `billing_status` returns to `CURRENT`. A `FAILED` outcome moves the charge to `FAILED` and cascades on the billing axis: the subscription's `billing_status` flips to `PAST_DUE`, and that flip cancels every current-cycle shipment still in `SCHEDULED` status, moving each to `CANCELLED` and releasing any stems those shipments held. Each such flip increments the subscription's `version`.

Refunds return money to the wallet. A `BillingAdmin` refunds a `CAPTURED` charge by supplying an `amount_cents` to refund. The refund is refused with `ERR_REFUND_EXCEEDS_CAPTURED` if the already-refunded amount plus the requested amount would exceed the charge's `amount_cents`. Otherwise the charge's `refunded_cents` increases by the refunded amount, and once `refunded_cents` reaches the full `amount_cents` the charge's `status` becomes `REFUNDED` (a partial refund leaves the charge `CAPTURED` with a positive `refunded_cents`). Every refund creates a wallet entry with `reason` of `REFUND` and a positive `amount_cents` equal to the refunded amount; that entry may record the originating charge in its `related_charge_id`. Wallet entries can also arise from skips (`reason` of `SKIP_CREDIT`) and from manual `ADJUSTMENT` corrections, and a customer can review the full list of their wallet entries.

### 3.8. Cancellation and Win-Back

A subscriber cancels a subscription that is `ACTIVE` or `PAUSED`, moving its `lifecycle_status` to `CANCELLED`. The request may carry a `reason`, which is stored as the subscription's `cancel_reason`, and a `refund_destination`. Cancellation triggers a three-level cascade that settles entirely within the request: every non-terminal shipment of the subscription — those in `SCHEDULED`, `SOURCING`, `SOURCED`, or `SUBSTITUTED` status — moves to `CANCELLED`; each cancelled shipment releases its `RESERVED` and `COMMITTED` allocations to `RELEASED`; and each released allocation restores its lot's `quantity_available`.

Cancellation then settles money. The system computes the actual cancellation refund, measured against the shipments' statuses as they stood immediately before the cascade: it is the per-shipment value (as defined in §3.4) multiplied by the number of current-cycle shipments that were in `SCHEDULED` or `SKIPPED` status. This actual refund deliberately excludes any shipment that had progressed past `SCHEDULED` into sourcing or beyond, because those shipments' stems were already committed or in progress. When `refund_destination` is `WALLET`, the system credits that refund by creating a wallet entry with `reason` of `REFUND` and increases the `refunded_cents` of the matching `CAPTURED` renewal charge for the current cycle accordingly. Cancellation also mints a win-back offer for the customer in `OFFERED` status, carrying a `discount_pct` of 0.20 and an `expires_at` set to 30 days after the cancellation instant, and it increments the subscription's `version`.

Before committing to a cancellation, a subscriber can preview the refund. The cancel preview reports an `estimated_refund_cents` and a `refundable_shipment_count` computed under the estimate variant, which is more optimistic than the actual: it counts every current-cycle shipment that is neither `DELIVERED` nor `CANCELLED` (thereby treating shipments in `SOURCING`, `SOURCED`, `SUBSTITUTED`, and beyond as refundable) and multiplies that count by the per-shipment value. The estimate and the actual therefore start from the same per-shipment value but diverge in which shipments they include.

A win-back offer lets a customer come back. Redeeming an offer names the `subscription_id` to reactivate. The offer must be in `OFFERED` status, else the redeem is rejected with `ERR_OFFER_NOT_REDEEMABLE`; the acting customer must own both the offer and the named subscription, else `ERR_OFFER_NOT_OWNED`; the current clock instant must be at or before the offer's `expires_at`, else `ERR_OFFER_EXPIRED`; and the target subscription must currently be `CANCELLED`. A successful redeem moves the offer to `REDEEMED`, moves the subscription's `lifecycle_status` from `CANCELLED` back to `ACTIVE`, sets the subscription's `discount_pct` to the offer's `discount_pct`, recomputes `renewal_price_cents` so the discount lands on the next renewal, and increments the subscription's `version`. A customer can list their win-back offers, optionally filtered by `status`.

Two terminal transitions happen without a client request, observed lazily on read once the clock has advanced. An `OFFERED` win-back offer whose `expires_at` has been reached or passed is treated as `EXPIRED` when the offer is observed through a read endpoint (the list-offers response). The redeem endpoint deliberately does not preempt its state check with this lazy transition: an offer whose stored status is still `OFFERED` at the moment redeem is called passes the state gate and is then subject to the temporal-window check in §2.9, so an expired but not-yet-observed offer surfaces as `ERR_OFFER_EXPIRED` rather than `ERR_OFFER_NOT_REDEEMABLE`. A `CANCELLED` subscription for which no `OFFERED` win-back offer remains unexpired transitions to the terminal `EXPIRED` lifecycle state.

## 4. Endpoint Definitions

Operations that create a new standalone resource return `201 Created`; operations that modify an existing resource, drive a state transition, or read data return `200 OK`. The specific status codes are as listed below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a subscription plan | `PlatformAdmin` |
| POST | `/carrier-routes` | Create a delivery route for a zone/service date | `PlatformAdmin` |
| GET | `/carrier-routes/{id}` | Fetch a carrier route | `PlatformAdmin`, `FulfillmentOps` |
| GET | `/carrier-routes/{id}/shipments` | List shipments booked on a route | `PlatformAdmin`, `FulfillmentOps` |
| POST | `/substitution-rules` | Create a substitution policy rule | `PlatformAdmin` |
| GET | `/substitution-rules` | List substitution rules, optionally by `from_variety` | `PlatformAdmin`, `FulfillmentOps` |
| POST | `/_clock/set_current_utc` | Test-driving: set the logical clock | `PlatformAdmin` |
| POST | `/customers` | Create a customer account | `PlatformAdmin` |
| GET | `/customers/{id}` | Fetch a customer (with computed fields) | `Customer`, `PlatformAdmin`, `BillingAdmin` |
| GET | `/customers/{id}/wallet-entries` | List a customer's wallet entries | `Customer`, `BillingAdmin` |
| GET | `/customers/{id}/win-back-offers` | List a customer's win-back offers | `Customer`, `BillingAdmin` |
| POST | `/subscriptions` | Create a subscription; opens cycle 1 | `Customer`, `PlatformAdmin` |
| GET | `/subscriptions` | List subscriptions, filterable | `Customer`, `PlatformAdmin`, `BillingAdmin` |
| GET | `/subscriptions/{id}` | Fetch a subscription | `Customer`, `PlatformAdmin`, `BillingAdmin` |
| GET | `/subscriptions/{id}/shipments` | List a subscription's shipments | `Customer`, `FulfillmentOps`, `PlatformAdmin` |
| GET | `/subscriptions/{id}/charges` | List a subscription's charges | `Customer`, `BillingAdmin` |
| POST | `/subscriptions/{id}/pause` | Pause an active subscription | `Customer` |
| POST | `/subscriptions/{id}/resume` | Resume a paused subscription | `Customer` |
| POST | `/subscriptions/{id}/change` | Change size/style/vase/plan (OCC-guarded) | `Customer` |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription (cascade + refund + win-back) | `Customer` |
| GET | `/subscriptions/{id}/cancel-preview` | Estimated refund if cancelled now | `Customer` |
| POST | `/subscriptions/{id}/renew` | Open the next billing cycle | `BillingAdmin` |
| GET | `/shipments/{id}` | Fetch a shipment | `Customer`, `FulfillmentOps` |
| POST | `/shipments/{id}/skip` | Skip a scheduled delivery before the cutoff | `Customer` |
| POST | `/shipments/{id}/source` | Begin sourcing a scheduled shipment | `FulfillmentOps` |
| POST | `/shipments/{id}/allocations` | Reserve stems from a lot for a sourcing shipment | `FulfillmentOps` |
| GET | `/shipments/{id}/allocations` | List a shipment's stem allocations | `FulfillmentOps` |
| POST | `/shipments/{id}/confirm-sourced` | Commit sourcing via the sourced or substituted branch | `FulfillmentOps` |
| POST | `/shipments/{id}/ship` | Book a delivery window on a route | `FulfillmentOps` |
| POST | `/shipments/{id}/deliver` | Mark a shipment delivered | `FulfillmentOps` |
| POST | `/stem-lots` | Register a cold-chain stem lot | `FulfillmentOps` |
| GET | `/stem-lots/{id}` | Fetch a stem lot (with computed fields) | `FulfillmentOps` |
| GET | `/stem-lots/{id}/allocations` | List allocations drawing on a lot | `FulfillmentOps` |
| POST | `/charges/{id}/simulate-payment` | Simulate a payment attempt on a pending charge | `BillingAdmin` |
| POST | `/charges/{id}/refund` | Refund up to the captured amount | `BillingAdmin` |
| POST | `/win-back-offers/{id}/redeem` | Redeem a win-back offer to reactivate a subscription | `Customer` |

The subscription create, plan create, carrier-route create, substitution-rule create, customer create, stem-lot register, allocation reserve, and renewal operations return `201 Created`. All other mutating operations and all reads return `200 OK`. Setting the logical clock returns `200 OK` with an empty data object.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_STEM_LOT_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_CHARGE_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SHIPMENT_NOT_SKIPPABLE` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_LOT_EXPIRED` | 409 |
| `ERR_OFFER_NOT_REDEEMABLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_OFFER_NOT_OWNED` | 403 |
| `ERR_SKIP_WINDOW_CLOSED` | 422 |
| `ERR_OFFER_EXPIRED` | 422 |
| `ERR_INSUFFICIENT_STEMS` | 422 |
| `ERR_ROUTE_WINDOW_CONFLICT` | 422 |
| `ERR_LOT_HOLD_CONFLICT` | 422 |
| `ERR_SUBSTITUTION_NOT_ALLOWED` | 422 |
| `ERR_BILLING_PAST_DUE` | 402 |
| `ERR_REFUND_EXCEEDS_CAPTURED` | 422 |
