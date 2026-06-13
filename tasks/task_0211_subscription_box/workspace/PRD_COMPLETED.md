# Subscription Box API — Product Requirements Document

## 1. Introduction

The Subscription Box API powers a recurring-physical-goods commerce platform: subscribers sign up for a curated box that ships on a fixed cadence — monthly or quarterly — and the system orchestrates everything between a subscriber's intent and a parcel leaving the warehouse. Each cycle a box is curated (or skipped, or swapped), a renewal charge is drawn, and the box's contents are reserved against real warehouse inventory before being committed to a shipping wave. The platform must therefore reconcile two normally-separate worlds: the *financial* world of charges, prepaid terms, refunds, and a per-subscriber wallet ledger, and the *physical* world of on-hand stock, reservations, capacity-limited shipping waves, and shipments.

What makes the domain demanding is that a subscription carries two independent status dimensions at once. Its **lifecycle** moves through `ACTIVE`, `PAUSED`, `CANCEL_SCHEDULED`, `CANCELLED`, and `EXPIRED`, while its **billing** posture moves independently through `CURRENT`, `PAST_DUE`, and `PREPAID`. A subscriber can prepay several periods up front at a discount, gift a subscription to someone else, pause within limits, cancel immediately (with a refund) or at period end (without one), and — within a bounded window after cancelling — be won back with a loyalty credit. Each of these levers cascades into inventory reservations and shipping commitments, so the system's correctness rests on getting every cascade, every refund variant, and every capacity check exactly right.

This document specifies the complete contract for that platform: the global conventions every endpoint obeys, the cross-cutting principles that govern money and inventory consistency, the business workflows that move subscriptions and boxes through their lifecycles, and the full endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource paths are mounted at the service root (`/`).

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`.

The system recognizes exactly three roles: `Subscriber`, `CurationAdmin`, and `BillingOperator`. A `Subscriber` is the account holder who owns their own subscriptions, box selections, gift purchases, and wallet. A `CurationAdmin` owns the catalog and fulfillment machinery: plans, products, shipping waves, allocations, and shipments, plus the test-driving clock and renewal controls. A `BillingOperator` owns billing settlement: charge retries, refunds, manual wallet adjustments, and gift revocation. When a request is authenticated but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

Roles differ in how `X-User-ID` is interpreted. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Subscriber`; ownership checks on any resource that references a `Subscriber` compare the resource's owning subscriber foreign key to `X-User-ID`. Concretely, a `Subscriber` may act only on subscriptions, box selections, gifts, and wallet lines whose `subscriber_id` (or, for gifts, `gifter_subscriber_id`) equals their own `X-User-ID`; acting on another subscriber's resource is denied with `ERR_UNAUTHORIZED`. By contrast, when `X-User-Role` is `CurationAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `BillingOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is not matched against any stored ownership field. Both operator roles are scoped by capability rather than by ownership.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific workflow states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Versioning Model

Every primary resource — plans, products, subscribers, subscriptions, gift grants, billing cycles, box selections, shipping waves, allocations, shipments, and invoices — carries a server-managed identity and audit set:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at creation and increments by one on every mutation. It backs optimistic concurrency control (§2.7).

There is one deliberate exception. A `WalletEntry` is an append-only, immutable ledger line: it carries only `id` and `created_at`. A `WalletEntry` has no `updated_at` and no `version`, because it is never modified after it is written. Whenever a derived field changes as a side effect of some operation — for example a product's `allocated_qty`, a wave's `reserved_count`, a subscriber's `wallet_balance_cents`, or a subscription's `prepaid_periods_remaining` — that counts as a mutation of the owning resource: its `updated_at` is refreshed and its `version` is incremented.

### 2.5. Inventory Integrity and the Two-Pool Stock Model

Each `Product` holds its stock in two conceptual pools. `on_hand_qty` is the free pool — units physically in the warehouse and not yet reserved — and `allocated_qty` is the reserved pool, the number of units currently held by `RESERVED` allocations. The quantity *available* for a new reservation is the free pool minus the reserved pool (`on_hand_qty` minus `allocated_qty`), and this available figure must never go below zero. The system maintains this invariant at every reservation, release, and commit, so that the books never promise stock that does not exist. Restocking adds units to the free pool only; reserving moves units from free to reserved without any units leaving the building; shipping is the moment units physically depart.

A `Product` also carries a catalog `status` of either `SELLABLE` or `DISCONTINUED`. A discontinued product can no longer be curated into new boxes, but any allocation already holding its units is unaffected.

### 2.6. Precision, Rounding, and Money

All monetary amounts are stored and returned as integer **cents**; there are no fractional cents and no floating-point money. Two calculations apply explicit rounding that the implementer must reproduce exactly.

- The prepaid-term discount is computed by flooring (rounding *down* to the nearest whole cent) — see §3.4.
- The win-back loyalty grant is computed by rounding *half up* to the nearest whole cent — see §3.7.
- The amortized prepaid unit value is computed by flooring the per-unit division before any multiplication — see §3.6.

Where a formula prescribes floor versus half-up, that choice is load-bearing and is specified inline with the workflow that uses it. A subscriber's `wallet_balance_cents` is never permitted to be negative.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against a parent resource's `version`, and only these two. In each case the client must supply the parent's last-observed `version`, and a divergence from the live value is rejected before any state changes.

First, reserving a curated box into a wave requires the request to carry `expected_wave_version`, holding the client's last-observed `version` of the target `ShippingWave`. If a prior writer has attached an allocation to that wave since the client last read it — legitimately consuming a capacity slot and advancing the wave's `version` — then the client's view of remaining capacity is stale, and the reservation is rejected with `ERR_STALE_WAVE_VERSION` (HTTP 412) rather than silently overbooking the wave. The `expected_wave_version` field is non-optional on this operation.

Second, purchasing a prepaid term requires the request to carry `expected_subscription_version`, holding the client's last-observed `version` of the target `Subscription`. If another writer has advanced the subscription's `version` since the client last read it — for instance by moving it into `PREPAID` or `PAST_DUE` — the prepay is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412), preventing a second prepaid term from being stacked onto a now-different billing state. The `expected_subscription_version` field is non-optional on this operation.

No other endpoint accepts a version field, and no other endpoint performs a stale-version check.

### 2.8. Validation Ordering

When several checks could fail for the same request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The order is:

1. **Authentication** — headers present and `X-User-Role` known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for the endpoint, and an ownership-scoped `Subscriber` is acting only on its own resources, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource referenced in the path, and then every foreign key in the body, exists; checked left-to-right (path before body), else `ERR_NOT_FOUND` (404).
4. **Request well-formedness** — required fields present, enum values legal, integers within their declared ranges, else `ERR_INVALID_REQUEST` (400).
5. **State** — the target resource is in a state from which the requested transition is defined; for a reservation, the referenced `ShippingWave` must be `OPEN`. A violation yields `ERR_INVALID_STATE` (409).
6. **Optimistic concurrency** — the supplied `expected_wave_version` or `expected_subscription_version` matches the live parent `version` (§2.7), else the corresponding stale-version error (412).
7. **Uniqueness** — `email` and `sku` uniqueness, else `ERR_DUPLICATE_EMAIL` / `ERR_DUPLICATE_SKU` (409).
8. **Business constraints** — the eligibility rules enumerated in §3 (prepaid term offered, plan not retired, gift not reactivatable, pause limit, box item count, gift redeemable, box not already finalized), each yielding HTTP 422.
9. **Temporal constraints** — win-back window, cutoff timing, resume-date sanity, each yielding HTTP 422.
10. **Safety constraints** — empty-wave shipping and insufficient inventory, each yielding HTTP 422.
11. **Capacity (fiscal) constraints** — wave capacity exhaustion (`ERR_WAVE_CAPACITY_FULL`, 422).

Within a single request, an earlier check that fails masks every later one. In particular, an `ERR_INVALID_STATE` surfaces before any optimistic-concurrency, business, temporal, safety, or capacity check on the same call.

### 2.9. Cascades, Reverts, and Hierarchical Consistency

Many operations touch more than one entity. The system applies every cascade synchronously and immediately within the triggering request — there is no eventual consistency. When a curated box is reverted, its inventory reservation is released; releasing a reservation returns the reserved units to the free pool and decrements the holding wave's count; and the box returns to an earlier curation state. When a subscription is cancelled immediately, this revert-and-restock cascade fans out across every upcoming finalized box. Each entity touched by a cascade is itself mutated — its `updated_at` is refreshed and its `version` incremented — exactly as for a direct write. The precise per-operation cascades are specified within the workflows in §3, because the trigger and the cascade belong together.

### 2.10. Nested Reads and Reverse Reachability

Child entities are not addressed through nested URL paths; they are reached as filtered lists off their parent's foreign key. A subscription's billing cycles, box selections, allocations, invoices, and shipments are each discoverable by filtering the corresponding collection on a `subscription_id`. A subscriber's wallet ledger is discoverable as that subscriber's wallet-entry collection. When a path does carry an identifier, the system validates it before reading any body or filter: a request naming a resource that does not exist is rejected with `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Catalog Setup: Plans and Products

A `CurationAdmin` seeds the catalog before any subscriber activity. A **subscription plan** is created with a display `name`, a `cadence` of either `MONTHLY` or `QUARTERLY`, a `period_price_cents` (the price charged per cadence period, which must be zero or greater), and a `box_item_count` (the number of curated product units placed into each box, which must be at least 1). Two optional levers configure prepaid offers: `prepaid_terms_offered` is an array of allowed multi-period term lengths, where each element is a whole number of at least 2, and an empty array (the default) means the plan offers no prepaid option; `prepaid_discount_pct` is the fractional discount applied to the prepaid total, at least 0 and strictly less than 1, defaulting to 0. A plan is born in `ACTIVE` `status` and can later be retired, moving its `status` to `RETIRED`; retirement is what later blocks win-back against that plan.

A **product** is created with a `sku`, a display `name`, and an initial `on_hand_qty` (zero or greater). Its `allocated_qty` begins at 0 and its `status` begins at `SELLABLE`. The `sku` must be unique across all products; a collision is rejected with `ERR_DUPLICATE_SKU`. An admin replenishes a product by supplying an `add_qty`, which is added to its `on_hand_qty`. An admin may also discontinue a product, moving its `status` from `SELLABLE` to `DISCONTINUED`; this only prevents future curation and leaves existing reservations intact.

### 3.2. Subscribers, Subscriptions, and the Wallet

A person joins by self-registering as a **subscriber** with an `email` and a `full_name`; an admin may also create one on a subscriber's behalf. The `email` must be unique across all subscribers, and a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. A new subscriber's `wallet_balance_cents` starts at 0.

The **wallet** is an append-only ledger. Each `WalletEntry` records a signed `amount_cents` (positive for a credit, negative for a debit), a `kind` drawn from `REFUND_CREDIT`, `WINBACK_CREDIT`, `PERIOD_DEBIT`, or `ADJUSTMENT`, and an optional `source_ref_id`. The `source_ref_id` is a polymorphic reference whose target kind is implied by `kind`: it resolves to a `BillingCycle` for a `PERIOD_DEBIT`, to a `Subscription` for a `WINBACK_CREDIT`, and to an `Invoice` for a `REFUND_CREDIT`. Because it can point at any of these, it is not a single-parent foreign key and carries no canonical prefix; the entry is found by listing a subscriber's wallet ledger. A `subscriber`'s `wallet_balance_cents` is always the running sum of the `amount_cents` of every `WalletEntry` whose `subscriber_id` matches that subscriber, with no status filter because entries are immutable; the sum is recomputed on every insert and may never be negative. A `BillingOperator` may post a manual adjustment, supplying the `amount_cents`, the `kind` (typically `ADJUSTMENT`, though any of the four wallet `kind` values is accepted on this endpoint), and an optional `source_ref_id`.

A **subscription** is created by a `Subscriber` against their own `subscriber_id` and a chosen `plan_id`. It begins life `ACTIVE` in its lifecycle and `CURRENT` in its billing posture, with `is_gift` false and `current_period_index` set to 1. The first period is billed immediately: the system creates a `BillingCycle` for `period_index` 1 with `funding_source` `CHARGE`, settles it `PAID`, and creates an `Invoice` of kind `PERIOD_CHARGE`. The subscription's `next_renewal_at` is set to the current clock plus one cadence period; one cadence period is exactly 30 days for a `MONTHLY` plan and exactly 90 days for a `QUARTERLY` plan, and all `next_renewal_at` arithmetic adds whole multiples of that fixed period length. A subscription exposes both status dimensions and its prepaid fields — `prepaid_periods_remaining`, `prepaid_unit_value_cents`, `paused_until`, `pause_count_in_term`, and `cancelled_at` — on read. The two terminal lifecycle states are `CANCELLED` and `EXPIRED`; once a subscription reaches either, its `next_renewal_at` is null.

### 3.3. Pause, Resume, Cancel, and Win-Back

A `Subscriber` may **pause** their own `ACTIVE` subscription until a future instant supplied as `paused_until`. The pause is allowed only when the subscription's `lifecycle_status` is `ACTIVE`; when the subscription has not already reached its pause ceiling for the term — that is, `pause_count_in_term` is below 3, so the third existing pause is the last permitted and a further pause request once the count has reached 3 is rejected with `ERR_PAUSE_LIMIT_REACHED`; when the supplied `paused_until` is strictly after the current clock, otherwise `ERR_INVALID_RESUME_DATE`; and when no box selection for the upcoming period (`current_period_index` + 1) is already finalized into an `OPEN` or `LOCKED` wave, otherwise `ERR_BOX_ALREADY_FINALIZED`. A successful pause moves `lifecycle_status` to `PAUSED`, sets `paused_until` to the supplied instant, increments `pause_count_in_term` by 1, and freezes `next_renewal_at` so renewal does not fire while paused; the billing posture is left untouched. The `pause_count_in_term` counts pauses taken over the life of the subscription: it starts at 0 at creation and increments by 1 on every successful pause, and the implementation never resets it (there is no term-boundary reset), so the limit of 3 applies across the subscription's whole lifetime.

A `PAUSED` subscription returns to `ACTIVE` either when the subscriber **resumes** it manually or when the renewal run observes the clock has reached `paused_until`. On resume, `next_renewal_at` is advanced by the elapsed pause duration, rounded to whole cadence periods forward so that renewal lands on a future cadence boundary, and `paused_until` is cleared.

A `Subscriber` may **cancel** their subscription, supplying an `effective` value of either `PERIOD_END` or `IMMEDIATE`. A period-end cancellation takes an `ACTIVE` subscription to `CANCEL_SCHEDULED`: `cancelled_at` is set to the current clock, `next_renewal_at` is preserved as the scheduled cancellation date, no refund is issued, and any remaining prepaid periods are forfeited when that scheduled date arrives. An immediate cancellation may be issued from either `ACTIVE` or `PAUSED` and takes the subscription to `CANCELLED`. On an immediate cancel the system sets `cancelled_at` to the current clock, clears `next_renewal_at`, computes the cancellation refund (§3.5), and creates an `Invoice` of kind `CANCEL_REFUND` (a negative `gross_amount_cents`) together with a `WalletEntry` of kind `REFUND_CREDIT` for the refund amount. It then runs the upcoming-box cascade: any box selection for an upcoming period that is finalized into an `OPEN` or `LOCKED` wave is reverted from `FINALIZED` to `SKIPPED`, which releases its allocation (the allocation moves `RESERVED` → `RELEASED`), the release restocks each line item back to the product's free pool and decrements the holding wave's `reserved_count`. Finally, the billing posture is set to `CURRENT`, since any prepaid value has already been consumed by the refund computation. A system-driven transition fires the scheduled cancel: when the renewal run finds a `CANCEL_SCHEDULED` subscription whose scheduled date has arrived, it moves it to `CANCELLED`, clears `next_renewal_at`, forfeits remaining prepaid with no refund, and sets billing to `CURRENT`.

After cancellation, a subscriber may be **won back**, returning a `CANCELLED` subscription to `ACTIVE`. Win-back is permitted only when the subscription's `lifecycle_status` is `CANCELLED`; when the current clock is before `cancelled_at` plus 60 days — the window is the half-open interval that starts at `cancelled_at` and ends exactly at `cancelled_at` plus 60 days, so a request at or after that 60-day boundary is rejected with `ERR_WINBACK_WINDOW_CLOSED`; when `is_gift` is false, because a gift subscription can never be win-back reactivated and such a request is rejected with `ERR_GIFT_NOT_REACTIVATABLE`; and when the plan's `status` is `ACTIVE`, otherwise `ERR_PLAN_RETIRED`. A successful win-back moves `lifecycle_status` to `ACTIVE`, sets `billing_status` to `CURRENT`, clears `cancelled_at`, sets `next_renewal_at` to the current clock plus one cadence period, and grants a one-time loyalty credit by creating a `WalletEntry` of kind `WINBACK_CREDIT` whose `amount_cents` is the win-back grant (§3.7) and whose `source_ref_id` is the subscription's own `id`.

### 3.4. Prepaid Terms and the Prepaid Charge

A `Subscriber` may convert their `CURRENT`, `ACTIVE` subscription into a **prepaid** one by purchasing a multi-period term. The request supplies `term_periods` and the concurrency guard `expected_subscription_version` (§2.7). The purchase is allowed only when `billing_status` is `CURRENT` and `lifecycle_status` is `ACTIVE`, and only when `term_periods` is a member of the plan's `prepaid_terms_offered`; a term that the plan does not offer is rejected with `ERR_PREPAID_TERM_NOT_OFFERED`.

The amount charged is computed with a pinned order of operations. First the gross is the plan's `period_price_cents` multiplied by `term_periods` — an exact integer. Then the discount in cents is the floor of that whole gross multiplied by the plan's `prepaid_discount_pct`; the discount is floored exactly once on the summed gross, never per period (flooring per period and then summing would yield a different, larger discount loss). The prepaid total paid is the gross minus the floored discount. On success the system charges that total, creates an `Invoice` of kind `PREPAID_CHARGE`, sets `billing_status` to `PREPAID`, sets `prepaid_periods_remaining` to `term_periods`, sets `prepaid_unit_value_cents` to the amortized per-period value (the floor of the prepaid total paid divided by the term length), and increments the subscription's `version` by 1.

As renewals draw down a prepaid term, `prepaid_periods_remaining` decrements; when the renewal run draws the last prepaid period — that is, the count was 1 before this draw — the subscription's billing posture returns from `PREPAID` to `CURRENT`, `prepaid_periods_remaining` becomes 0, and `prepaid_unit_value_cents` becomes 0.

### 3.5. Cancellation Refunds — Two Variants

When a subscription is cancelled immediately, the refund depends on its billing posture at cancel time, and the two variants diverge on otherwise-identical inputs. In both cases the relevant input set is this subscription's `BillingCycle` rows with `status` `PAID`, partitioned by whether their allocation is `COMMITTED` (the box actually shipped) or `RESERVED`/absent (paid for but not yet shipped).

Under the **period-proration** variant, which applies when `billing_status` is `CURRENT` (pay-as-you-go) at cancel time, the refund is the sum of `amount_charged_cents` over every unshipped `CURRENT`-funded paid billing cycle — the full per-period price comes back for each period not yet shipped, and any period that already shipped refunds nothing.

Under the **prepaid-amortized** variant, which applies when `billing_status` is `PREPAID` at cancel time, the refund is `prepaid_periods_remaining` multiplied by `prepaid_unit_value_cents`, where that unit value is the floor of the prepaid total paid divided by the prepaid term length, computed per unit *before* the multiplication. Because the bulk discount is amortized into the unit value and is not restored, the same number of remaining periods refunds *less* under this variant than the period-proration variant would for the same nominal price. The refund is in integer cents.

When an immediate cancel happens within the same period that was already paid, the matching `PAID` billing cycle whose `period_index` equals the subscription's `current_period_index` is reversed (`PAID` → `REVERSED`), which voids its matching `Invoice` (moving the invoice's `status` from `SETTLED` to `VOID`); the actual money back to the subscriber is issued by the refund computation above and is not double-counted by this reversal.

### 3.6. Box Curation: Skip and Swap

For each upcoming period a `Subscriber` records a **box selection** against their subscription. The request names a `period_index`, which must equal the subscription's `current_period_index` plus 1 (the next box), and either supplies an ordered list of `product_ids` to curate or sets `skip` to true. A curated (non-skipped) box requires its `product_ids` to have a length exactly equal to the plan's `box_item_count`; a mismatch is rejected with `ERR_BOX_ITEM_COUNT_MISMATCH`. A curated selection lands with `decision` `CURATED`; a skipped one lands `SKIPPED`. A box selection's `decision` proceeds through `PENDING`, `CURATED`, `SKIPPED`, and ultimately `FINALIZED`, and carries an `allocation_id` that is null until inventory is reserved for it.

Before a box is finalized into a wave, the subscriber may **swap** its contents or flip its skip flag, supplying a replacement `product_ids` and/or `skip`. A swap is permitted only while the box has not yet been finalized with an allocation; attempting to swap or skip a box that is already `FINALIZED` into a wave (it holds an allocation) is rejected with `ERR_BOX_ALREADY_FINALIZED`.

### 3.7. Win-Back Loyalty Credit

The one-time credit granted on win-back is a loyalty score on the subscriber, not a cost-accounting figure on the subscription. It is sized from the subscriber's cross-subscription tenure: count every `Shipment` in `PACKED`, `DISPATCHED`, or `DELIVERED` status across all subscriptions owned by this subscriber — call this the committed-box count. The base is the plan's `period_price_cents`. The tenure factor is the lesser of the committed-box count and 6 (the tenure cap), multiplied by 0.05 (the tenure weight). The grant before capping is the base multiplied by the sum of the base grant percentage 0.20 and the tenure factor, rounded half up to integer cents. Finally the grant is capped at 5000 cents, with the cap applied *after* rounding.

Two variants follow from the same formula. For a subscriber with at least one prior committed shipment (the **standard** path), the tenure factor contributes and the grant scales with the committed-box count up to the cap. For a subscriber with zero prior committed shipments (the **cold** path — for instance someone who cancelled before any box shipped), the tenure factor is 0, so the grant is simply the base multiplied by the base grant percentage 0.20, rounded half up.

### 3.8. Shipping Waves, Reservations, and Inventory Allocation

A `CurationAdmin` opens a **shipping wave** for a given `cadence`, supplying a `cutoff_at`, a `ship_date`, and a `capacity` (the maximum number of allocations the wave can hold, at least 1). The `ship_date` must be strictly after `cutoff_at`. A wave opens in `OPEN` `status` with `reserved_count` 0, and its lifecycle runs `OPEN` → `LOCKED` → `SHIPPED`, with an alternate `OPEN` → `CANCELLED`. The invariant `reserved_count` ≤ `capacity` holds at all times.

Reserving a curated box into a wave creates an **allocation**. The request supplies the `subscription_id`, the `wave_id`, the `box_selection_id`, and the concurrency guard `expected_wave_version` (§2.7). The referenced wave must be `OPEN` (otherwise the state check fails with `ERR_INVALID_STATE`), and the referenced box must not already be finalized into a non-released allocation — a box period slot may hold at most one non-released allocation, so a double reservation of the same box period is rejected with `ERR_BOX_ALREADY_FINALIZED`.

Whether the box can be reserved is decided by a non-linear, all-or-nothing fill check over three inputs: the box's `product_ids` (with repeats collapsed to a per-product requested quantity by counting occurrences), each referenced product's available quantity (its `on_hand_qty` minus its `allocated_qty`), and the wave's remaining capacity. For every distinct product in the box, its available quantity must be at least the requested quantity for that product; if any single product is short, the entire box is rejected with `ERR_INSUFFICIENT_INVENTORY` and nothing is reserved. Separately, the wave must have room: if `reserved_count` has already reached `capacity`, the reservation is rejected with `ERR_WAVE_CAPACITY_FULL`. When both checks pass, the allocation is created `RESERVED`: for each distinct product the product's `allocated_qty` is increased by the requested quantity, the wave's `reserved_count` is increased by 1, the box's `line_items` are snapshotted as a list of `{ product_id, qty }` (one entry per distinct product), the box selection's `decision` becomes `FINALIZED` with its `allocation_id` set, and the wave's `version` is incremented by 1.

An admin may **release** a `RESERVED` allocation directly. A release — whether triggered explicitly, by a subscription cancel, by a wave cancel, by a box swap, or by a charge failure — moves the allocation `RESERVED` → `RELEASED`, returns each line item's reserved units to the free pool by decrementing the product's `allocated_qty` (leaving `on_hand_qty` untouched, since the units never left the warehouse), decrements the wave's `reserved_count` by 1, and reverts the linked box selection's `decision` from `FINALIZED` back to `CURATED` with its `allocation_id` cleared to null.

### 3.9. Locking, Shipping, and Wave Cancellation

A `CurationAdmin` **locks** a wave once its cutoff has arrived: locking is permitted only when the wave is `OPEN` and the current clock is at or after `cutoff_at`; an attempt to lock before the cutoff is rejected with `ERR_CUTOFF_NOT_REACHED`. Locking moves the wave `OPEN` → `LOCKED`, after which no new allocations may attach (reservation requires an `OPEN` wave). Note the boundary contrast that governs the cutoff instant: a box may *join* a wave by reservation only while the clock is strictly before `cutoff_at`, so a reservation attempt at or after the cutoff is rejected with `ERR_CUTOFF_PASSED`, whereas *locking* is only allowed once the clock has reached or passed that same `cutoff_at`.

An admin **ships** a `LOCKED` wave. Shipping requires the wave to be `LOCKED` and to hold at least one `RESERVED` allocation; shipping a wave with zero reserved allocations is rejected with `ERR_EMPTY_WAVE`. On ship, every `RESERVED` allocation on the wave is committed (`RESERVED` → `COMMITTED`): for each committed line item the product's `on_hand_qty` is decremented (the units physically leave) and its `allocated_qty` is decremented (they are no longer merely reserved), a `Shipment` is created in `PACKED` status, and the linked box selection's `decision` is set to `FINALIZED` if it is not already. The wave then moves to `SHIPPED`.

An admin may **cancel** an `OPEN` wave. Cancellation cascades: every `RESERVED` allocation on the wave is released, restocking each line item to the product's free pool (decrementing `allocated_qty`) and reverting its box selection's `decision` from `FINALIZED` back to `CURATED`; the wave's `reserved_count` is reset to 0; and the wave moves `OPEN` → `CANCELLED`.

### 3.10. Shipments

Each committed allocation produces a **shipment**, which references its `allocation_id`, its `wave_id`, and the recipient `subscription_id`. A shipment starts `PACKED` and is driven forward by a `CurationAdmin`: dispatching moves a `PACKED` shipment to `DISPATCHED`, and delivering moves a `DISPATCHED` shipment to `DELIVERED`. `DELIVERED` is terminal. Shipments are discoverable by filtering on their `allocation_id`, `wave_id`, or `subscription_id`.

### 3.11. Gifts

A `Subscriber` may purchase a **gift grant**, supplying the `plan_id`, their own `gifter_subscriber_id`, the `term_periods` the gift covers (at least 1), and the `recipient_email` to which the code is issued. The system mints an opaque `redemption_code`, charges the gifter `amount_paid_cents` equal to the plan's `period_price_cents` multiplied by `term_periods` (gifts take no prepaid discount), and creates an `Invoice` of kind `GIFT_CHARGE` whose `subscriber_id` is the gifter and whose `subscription_id` is null (no subscription exists yet). The grant opens in `ISSUED` `status`, with `redeemed_subscription_id` null.

The recipient **redeems** the gift by supplying the `redemption_code` and their own `subscriber_id`. Redemption is allowed only when the code is in `ISSUED` status; a code already `REDEEMED` or `REVOKED` is rejected with `ERR_GIFT_NOT_REDEEMABLE`. On redemption the grant moves `ISSUED` → `REDEEMED` and its `redeemed_subscription_id` is set; a new `Subscription` is created with `is_gift` true, `billing_status` `PREPAID`, `prepaid_periods_remaining` equal to the gift's `term_periods`, `prepaid_unit_value_cents` 0, `lifecycle_status` `ACTIVE`, `current_period_index` 1, and `next_renewal_at` set to the current clock plus one cadence period; the redeem response returns this newly created `Subscription` (not the grant) with status `201 Created`. Gift subscriptions never auto-renew with a charge.

A `BillingOperator` may **revoke** an unredeemed gift grant, moving it `ISSUED` → `REVOKED` and refunding the gifter: the system creates an `Invoice` of kind `CANCEL_REFUND` (negative `gross_amount_cents` equal to the negated `amount_paid_cents`, `subscriber_id` the gifter, `subscription_id` null) and a `WalletEntry` of kind `REFUND_CREDIT` for the grant's `amount_paid_cents`.

### 3.12. Billing Cycles and the Renewal Run

Each period a subscription consumes is recorded as a **billing cycle**, carrying the `subscription_id`, a `period_index`, an `amount_charged_cents` (0 when covered by prepaid or a gift), a `funding_source` of `CHARGE`, `PREPAID_DRAW`, `GIFT`, or `WALLET`, a `status` of `PENDING`, `PAID`, `FAILED`, or `REVERSED`, and a `charged_at` instant that is null while pending. When a cycle settles `PAID`, its `charged_at` is set; if its `funding_source` is `CHARGE` an `Invoice` of kind `PERIOD_CHARGE` is created; if `PREPAID_DRAW` the subscription's `prepaid_periods_remaining` is decremented; if `WALLET` a `WalletEntry` of kind `PERIOD_DEBIT` (negative) is created.

Billing settlement is driven by the renewal run, an admin-only test-driving capability. The logical clock is first set by supplying a `to_iso8601` instant, and then the renewal epoch is run at that clock; the run optionally narrows to a single `subscription_id` and optionally takes a `charge_outcome` that decides whether a `CHARGE`-funded renewal settles `PAID` or `FAILED`; when `charge_outcome` is omitted (or is not one of `PAID`/`FAILED`), the run settles `CHARGE`-funded renewals `PAID`. For each due subscription the run: resumes a paused subscription whose `paused_until` the clock has reached; for an `ACTIVE`/`CURRENT` subscription whose renewal is due, creates a `CHARGE`-funded billing cycle settled per the supplied `charge_outcome`; for a `PREPAID` non-gift subscription, creates a `PREPAID_DRAW` cycle with `amount_charged_cents` 0 and decrements `prepaid_periods_remaining`; for a `PREPAID` gift subscription, creates a `GIFT`-funded cycle with `amount_charged_cents` 0 and decrements `prepaid_periods_remaining`; expires a gift whose last prepaid period was just drawn; and cancels a `CANCEL_SCHEDULED` subscription whose scheduled date is due. It advances `current_period_index` and `next_renewal_at` for each renewed subscription.

When a `CHARGE`-funded renewal cycle settles `FAILED`, the subscription's `billing_status` moves `CURRENT` → `PAST_DUE`, its `current_period_index` and `next_renewal_at` are still advanced by one cadence period (the failed period is consumed exactly as a successful renewal would consume it), and any box selection finalized for that failed period reverts from `FINALIZED` to `SKIPPED`, releasing its allocation with the usual restock-and-decrement cascade. A `BillingOperator` may then **retry the charge** on a `PAST_DUE` subscription, supplying an `outcome`: an `outcome` of `PAID` settles the replacement cycle `PAID` and moves `billing_status` `PAST_DUE` → `CURRENT`, while an `outcome` of `FAILED` leaves it `PAST_DUE`.

A gift subscription whose last prepaid period is drawn at a renewal run — that is, its `prepaid_periods_remaining` was 1 before that draw and `is_gift` is true — moves its lifecycle to `EXPIRED`, with `next_renewal_at` cleared and no further charge or auto-renew.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or return no resource body return `200 OK`. Request and response bodies are not restated here — they are governed by the workflows in §3. The clock-setting and renewal-run endpoints are admin-only test-driving controls that return `200 OK` with no resource body.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a subscription plan | CurationAdmin |
| GET | `/plans/{id}` | Fetch a plan | CurationAdmin, Subscriber, BillingOperator |
| GET | `/plans` | List plans | CurationAdmin, Subscriber, BillingOperator |
| POST | `/plans/{id}/retire` | Retire a plan | CurationAdmin |
| POST | `/products` | Create a catalog product | CurationAdmin |
| GET | `/products/{id}` | Fetch a product | CurationAdmin, Subscriber, BillingOperator |
| GET | `/products` | List products | CurationAdmin, Subscriber, BillingOperator |
| POST | `/products/{id}/restock` | Add units to on-hand inventory | CurationAdmin |
| POST | `/products/{id}/discontinue` | Mark a product discontinued | CurationAdmin |
| POST | `/subscribers` | Register a subscriber | Subscriber, CurationAdmin |
| GET | `/subscribers/{id}` | Fetch a subscriber | Subscriber, CurationAdmin, BillingOperator |
| GET | `/subscribers/{id}/wallet-entries` | List a subscriber's wallet ledger | Subscriber, CurationAdmin, BillingOperator |
| POST | `/subscribers/{id}/wallet-entries` | Post a manual wallet adjustment | BillingOperator |
| POST | `/subscriptions` | Create a pay-as-you-go subscription | Subscriber |
| GET | `/subscriptions/{id}` | Fetch a subscription | Subscriber, CurationAdmin, BillingOperator |
| GET | `/subscriptions` | List subscriptions | Subscriber, CurationAdmin, BillingOperator |
| POST | `/subscriptions/{id}/pause` | Pause an active subscription | Subscriber |
| POST | `/subscriptions/{id}/resume` | Resume a paused subscription | Subscriber |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Subscriber |
| POST | `/subscriptions/{id}/winback` | Reactivate a cancelled subscription | Subscriber |
| POST | `/subscriptions/{id}/prepay` | Purchase a prepaid multi-period term | Subscriber |
| POST | `/subscriptions/{id}/retry-charge` | Retry a failed renewal charge | BillingOperator |
| POST | `/subscriptions/{id}/box-selections` | Curate or skip the upcoming box | Subscriber |
| GET | `/box-selections/{id}` | Fetch a box selection | Subscriber, CurationAdmin |
| GET | `/box-selections` | List box selections | Subscriber, CurationAdmin |
| PATCH | `/box-selections/{id}` | Swap products or flip skip on a box | Subscriber |
| POST | `/waves` | Open a shipping wave | CurationAdmin |
| GET | `/waves/{id}` | Fetch a wave | CurationAdmin, Subscriber, BillingOperator |
| GET | `/waves` | List waves | CurationAdmin, Subscriber, BillingOperator |
| POST | `/waves/{id}/lock` | Lock a wave after cutoff | CurationAdmin |
| POST | `/waves/{id}/ship` | Ship a locked wave | CurationAdmin |
| POST | `/waves/{id}/cancel` | Cancel an open wave | CurationAdmin |
| POST | `/allocations` | Reserve a curated box into a wave | CurationAdmin |
| GET | `/allocations/{id}` | Fetch an allocation | CurationAdmin, Subscriber, BillingOperator |
| GET | `/allocations` | List allocations | CurationAdmin, Subscriber, BillingOperator |
| POST | `/allocations/{id}/release` | Release a reserved allocation | CurationAdmin |
| GET | `/shipments/{id}` | Fetch a shipment | CurationAdmin, Subscriber, BillingOperator |
| GET | `/shipments` | List shipments | CurationAdmin, Subscriber, BillingOperator |
| POST | `/shipments/{id}/dispatch` | Mark a shipment dispatched | CurationAdmin |
| POST | `/shipments/{id}/deliver` | Mark a shipment delivered | CurationAdmin |
| GET | `/billing-cycles/{id}` | Fetch a billing cycle | BillingOperator, Subscriber, CurationAdmin |
| GET | `/billing-cycles` | List billing cycles | BillingOperator, Subscriber, CurationAdmin |
| GET | `/invoices/{id}` | Fetch an invoice | BillingOperator, Subscriber, CurationAdmin |
| GET | `/invoices` | List invoices | BillingOperator, Subscriber, CurationAdmin |
| POST | `/gift-grants` | Purchase a gift subscription | Subscriber |
| GET | `/gift-grants/{id}` | Fetch a gift grant | Subscriber, CurationAdmin |
| GET | `/gift-grants` | List gift grants | Subscriber, CurationAdmin |
| POST | `/gift-grants/redeem` | Redeem a gift code | Subscriber |
| POST | `/gift-grants/{id}/revoke` | Revoke an unredeemed gift grant | BillingOperator |
| POST | `/_clock/set_current_utc` | Set the simulated current UTC instant | CurationAdmin |
| POST | `/_renewal/run` | Run the renewal/wave epoch at the current clock | CurationAdmin |

The list endpoints accept the usual `limit` and `offset` pagination parameters, and several accept filters: `/plans`, `/products`, and `/waves` accept a `status` filter (waves additionally a `cadence`); `/subscriptions` accepts `subscriber_id`, `plan_id`, and `lifecycle_status`; `/box-selections` accepts `subscription_id` and `allocation_id`; `/allocations` accepts `wave_id`, `subscription_id`, and `box_selection_id`; `/shipments` accepts `allocation_id`, `wave_id`, and `subscription_id`; `/billing-cycles` accepts `subscription_id` and `status`; `/invoices` accepts `subscriber_id` and `subscription_id`; and `/gift-grants` accepts `gifter_subscriber_id`, `plan_id`, and `redeemed_subscription_id`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_WAVE_VERSION` | 412 |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_PREPAID_TERM_NOT_OFFERED` | 422 |
| `ERR_PLAN_RETIRED` | 422 |
| `ERR_GIFT_NOT_REACTIVATABLE` | 422 |
| `ERR_PAUSE_LIMIT_REACHED` | 422 |
| `ERR_BOX_ITEM_COUNT_MISMATCH` | 422 |
| `ERR_GIFT_NOT_REDEEMABLE` | 422 |
| `ERR_WINBACK_WINDOW_CLOSED` | 422 |
| `ERR_CUTOFF_PASSED` | 422 |
| `ERR_CUTOFF_NOT_REACHED` | 422 |
| `ERR_INVALID_RESUME_DATE` | 422 |
| `ERR_BOX_ALREADY_FINALIZED` | 422 |
| `ERR_EMPTY_WAVE` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 422 |
| `ERR_WAVE_CAPACITY_FULL` | 422 |
