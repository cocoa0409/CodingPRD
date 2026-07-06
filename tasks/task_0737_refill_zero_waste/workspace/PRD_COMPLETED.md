# Refill & Zero-Waste Store API — Product Requirements Document

## 1. Introduction

The Refill & Zero-Waste Store API powers a packaging-free grocery operation in which customers bring or borrow containers, fill them from bulk dispensing bins, and pay by net weight rather than by the unit. Because nothing is pre-packaged, price is discovered twice: once as a **provisional** estimate when a member drafts a cart from a declared container weight and an intended fill, and once as a **final** figure after a clerk physically weighs the empty and full container at the station. The system must keep these two valuations coherent while it also manages container deposits, membership loyalty, per-station fill scheduling, delivery routing with a container-return loop, and the physical reality of bins that deplete, run low, get restocked, and occasionally lose stock to shrink.

Three cooperating operators share the workload. A member drives their own cart, containers, subscriptions, and deliveries; a counter clerk weighs and finalizes lines, issues deposit containers, and moves logistics along; and an inventory manager owns the catalog, the bins, the recount ledger, the delivery fleet, and the logical clock that the whole system reads time from. This document specifies the entities, the money and weight arithmetic, the cross-entity cascades (a single fill can deplete a bin, flip it to a low-stock state, and mint a restock task in one atomic step), and the validation discipline that keeps deposits, loyalty, and inventory reconciled at all times.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that every endpoint obeys. All resources are mounted under the `/v1` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation — or a member attempts to act on a resource they do not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly three roles: `Member`, `StoreClerk`, and `InventoryManager`.

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare that resource's `member_id` to `X-User-ID`: a member may create and act only on their own orders, containers, subscriptions, and deliveries, and may read only their own or otherwise visible resources.
- When `X-User-Role` is `StoreClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`. A clerk is the only actor who weighs and finalizes lines, voids lines, issues containers to members, starts an order filling, and registers a member at the counter, and a clerk may also act on behalf of any member across the ordering, container, subscription, and delivery flows.
- When `X-User-Role` is `InventoryManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`. The inventory manager exclusively manages products, stations, bins, bin recounts, restock completions, delivery vehicles, and the logical clock, and additionally shares the container-inspection and delivery logistics operations.

Read (GET) endpoints are available to all three roles unless a member ownership restriction narrows visibility.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by a hex string (implementation uses 32 hex characters from a UUID).
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range or non-integer values are silently clamped to that range (a non-integer or missing value falls back to the default of 10, values below 1 are raised to 1, values above 100 are lowered to 100). The `offset` parameter is the number of items to skip and defaults to 0; a non-integer or missing value falls back to 0 and negative values are raised to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order, and ties on `created_at` are broken by a stable server-assigned monotonic sequence number reflecting insertion order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties, Identifiers, and the Logical Clock

Every primary resource carries a server-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created. Most resources additionally carry an `updated_at` timestamp (an ISO 8601 UTC value initialised to the same instant as `created_at` on creation and refreshed on every mutation) and an integer `version` that starts at `1` on creation and increments by one on every mutation. Both `updated_at` and `version` also advance when a resource's derived fields change as a side effect of another operation — for example, when a member's projected balances shift because a wallet-ledger movement was appended.

There is one exception: `WalletLedger` entries are immutable, append-only events. Each such entry carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field, because it is never modified after it is written.

The system reads the current time from a **logical clock**, never from real wall-clock time. Before any client sets it, the clock holds a fixed startup default of `2026-03-01T00:00:00Z`. Every time-derived value — a subscription's `next_run_at`, a bin's `last_recount_at`, and any comparison involving scheduling windows — is computed against this logical clock. An inventory-manager-only test-driving capability sets the clock to a supplied `to_iso8601` instant. A bin's `last_recount_at` is initialised to the current logical-clock reading at bin-creation time (which is the `2026-03-01T00:00:00Z` startup instant unless the clock has been advanced first) and is overwritten at each recount.

### 2.5. Monetary and Weight Precision

All money is handled in integer **cents**, and all weight in integer **grams**; API responses never emit fractional cents or fractional grams. Where a calculation produces a real-valued intermediate — for instance, a per-100-gram rate multiplied by a net weight, or a tax computed from a rate — the result is rounded to a whole cent using the **round half up** convention (a value exactly at the half rounds away from zero).

Line pricing rounds **per line**: each line's price is rounded to a whole cent before any order-level summation, and the order subtotal is the sum of those already-rounded line prices rather than a single rounding applied to the raw goods total. This ordering is deliberate and must be preserved, because summing raw goods and rounding once could differ from the pinned result by up to a cent per line. Shrink and inventory quantities are whole grams throughout.

### 2.6. The Wallet Ledger, Deposit Float, and Derived Member Balances

Every movement of money or points for a member is recorded as an immutable `WalletLedger` entry, and appending a ledger entry additionally advances the referenced member's `updated_at` and `version` (as the projection has effectively changed). Each entry names the `member_id` it applies to, an `entry_type` of `DEPOSIT_COMMIT`, `DEPOSIT_REFUND`, `LOYALTY_ACCRUAL`, or `LOYALTY_REDEEM`, and three signed deltas: `wallet_delta_cents` (change to spendable wallet balance), `liability_delta_cents` (change to outstanding deposit liability), and `points_delta` (change to loyalty points). Each entry also records a `source_kind` of `ORDER`, `CONTAINER`, or `DELIVERY`, a polymorphic `source_id` pointing at the originating resource (an audit reference only, not a validated foreign key), and a human-readable `memo`.

A member's three balance fields are **projections** over that member's ledger, never stored independently: `wallet_balance_cents` is the sum of all `wallet_delta_cents` for the member, `deposit_liability_cents` is the sum of all `liability_delta_cents`, and `loyalty_points_balance` is the sum of all `points_delta`. Because deposits are only ever refunded (never charged to the wallet), the wallet balance is non-negative by construction. The store maintains a global **deposit float** invariant: at every instant, the total `deposit_cents` across all containers currently in the `IN_USE` status equals the total `deposit_liability_cents` across all members. Committing a deposit raises both sides together; refunding one lowers both together.

### 2.7. Cascading Consistency and Automatic Restocking

Several operations mutate more than one entity in a single atomic request, and every downstream effect must land before the request returns. The signature cascade is bin depletion: when a line is finalized, the resolved bin's `on_hand_g` is decreased by the line's net weight; if that drives `on_hand_g` to at or below the bin's `reorder_threshold_g`, the bin's `status` flips from `OPEN` to `LOW` and a `RestockTask` is auto-created for that bin in the same step. Compensating actions run in reverse: voiding a finalized line, or cancelling an order that is mid-fill, returns the line's grams to the bin's `on_hand_g`, and if that lifts `on_hand_g` back above the reorder threshold, the bin returns from `LOW` to `OPEN`. Each such cascade independently updates the touched resources' `updated_at` and `version`. The system may transition a bin, container, or order automatically as a consequence of another operation, without an explicit client request against that specific resource.

### 2.8. Scheduling Windows: Fill-Windows and Delivery Turnaround

Two kinds of time windows are enforced. An order occupies a **fill-window** on its station, delimited by `fill_window_start_at` and `fill_window_end_at`; the end must be strictly after the start. Fill-windows are **half-open** intervals `[start, end)`: two windows on the same station conflict when they overlap on that half-open basis, but exact adjacency (one window's start equal to another's end) is permitted. A new order whose window overlaps another non-cancelled order's window on the same station is rejected with `ERR_STATION_SESSION_OVERLAP`.

A delivery occupies a **window** on its assigned vehicle, delimited by `window_start_at` and `window_end_at`, with the end strictly after the start. Delivery windows are treated as **closed** intervals `[start, end]` and additionally require a turnaround gap: any two non-cancelled windows on the same vehicle must be separated by at least `TURNAROUND_BUFFER_MIN` minutes of clear time. `TURNAROUND_BUFFER_MIN` is `30` minutes. A new delivery whose window falls within `TURNAROUND_BUFFER_MIN` minutes of another non-cancelled window on the same vehicle is rejected with `ERR_VEHICLE_WINDOW_CONFLICT`.

### 2.9. Request Validation Order and Nested Resource Resolution

When a single request could fail several checks, the checks are evaluated in a fixed priority order and the first failure wins; lower-priority-number checks are decided before higher ones. The order is:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the acting role is permitted for the operation, and a member acts only on resources they own, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every path identifier and every foreign-key reference in the body resolves to an existing resource, validated left to right with **path identifiers checked before body foreign keys**; note that a member-ownership authorization check on a body-carried `member_id` (or on an order/subscription/delivery whose `member_id` is derivable from the request) is evaluated at authorization priority (step 2) and may therefore fire before the corresponding body foreign-key existence check. A miss returns the matching 404: `ERR_MEMBER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_CONTAINER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_RESTOCK_TASK_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, or `ERR_DELIVERY_NOT_FOUND`.
4. **State** — the target resource is in a status permitting the requested transition, else one of `ERR_INVALID_ORDER_STATE`, `ERR_INVALID_CONTAINER_STATE`, or `ERR_INVALID_STATE` (all 409).
5. **Business safety** — allergen compatibility and bin non-quarantine on a fill, yielding `ERR_ALLERGEN_CONFLICT` or `ERR_BIN_QUARANTINED` (409).
6. **Business referential** — container ownership on a fill, yielding `ERR_CONTAINER_NOT_OWNED` (409).
7. **Temporal** — window freedom on order and delivery creation, yielding `ERR_STATION_SESSION_OVERLAP` or `ERR_VEHICLE_WINDOW_CONFLICT` (409).
8. **Structural constraint** — non-empty orders, positive net weight, and email/plate uniqueness, yielding `ERR_EMPTY_ORDER`, `ERR_TARE_EXCEEDS_GROSS`, `ERR_DUPLICATE_EMAIL`, or `ERR_DELIVERY_ORDER_NOT_READY` (422).
9. **Inventory/capacity** — sufficient stock to dispense and no restock overfill, yielding `ERR_INSUFFICIENT_STOCK` (409).
10. **Optimistic concurrency** — the subscription stale-version guard, yielding `ERR_STALE_VERSION` (412).

A malformed body, a missing required field, or a bad type or enum value is rejected up front with `ERR_VALIDATION` (400). This body-shape validation runs after the request-level authentication (priority 1) and authorization (priority 2) header checks, so an unauthenticated or unauthorized request never reaches body validation. An entirely absent body is treated as an empty JSON object rather than as malformed input. For nested reads whose path names more than one resource (for example, a member's wallet-ledger listing), the parent identifier in the path is resolved before the sub-resource is retrieved, and the first unresolved identifier determines the 404 returned.

### 2.10. Optimistic Concurrency Control for Subscription Runs

Running a subscription cycle is guarded by optimistic concurrency on the subscription's `version`. A request to run a subscription must carry `expected_subscription_version` as a required field, carrying the client's last observed `version` of that subscription. If that value does not equal the subscription's current `version` — because an earlier run has already advanced it since the client last read the subscription — the run is rejected with `ERR_STALE_VERSION` (HTTP 412). This is a stale-version rejection, not a timing race: a run legitimately mints a fresh cycle order that supersedes any prior pending run-order, so a client acting on an outdated view of the subscription is refused rather than allowed to mint a duplicate cycle. A successful run increments the subscription's `version` by one. No other endpoint takes a version field.

## 3. Business Logic & Workflows

### 3.1. Members, Wallets, and Loyalty Standing

A clerk registers a member at the counter by supplying an `email` and a `full_name`, and optionally a `membership_tier`; when omitted or `null` the tier defaults to `BASIC`. Member registration is exclusively a `StoreClerk` operation. The `email` must be unique across all members — a collision is rejected with `ERR_DUPLICATE_EMAIL`. A newly registered member starts with all three projected balances at zero: `wallet_balance_cents`, `deposit_liability_cents`, and `loyalty_points_balance`.

Membership tier is one of `BASIC` or `PLUS`. A `PLUS` member enjoys a 10% discount on goods (a discount factor of 0.10 applied at line pricing, so the goods value is multiplied by exactly `1 - 0.10 = 0.90` before rounding) and earns loyalty at 1.5 times the base rate; a `BASIC` member receives no goods discount and earns at the base rate. Fetching a member returns the live projections described in §2.6, recomputed from the member's ledger. A member's full movement history is available as a reverse-reachability listing of `WalletLedger` entries keyed by `member_id`, paginated by `limit` and `offset`.

### 3.2. Catalog and Inventory Setup: Products, Stations, and Bins

The inventory manager builds the catalog. A **product** is a bulk SKU created with a `name`, a `category` of `GRAINS`, `LIQUIDS`, `SPICES`, or `CLEANING`, a base rate `unit_price_cents_per_100g` (nominally at least 1), a bulk-tier boundary `bulk_tier_threshold_g` (nominally at least 1 gram), and a discounted `bulk_tier_price_cents_per_100g` (nominally not exceeding the base rate). These lower bounds and the bulk-vs-base ordering are documented expectations rather than server-side validation constraints: only the presence and integer type of each field is validated on creation. Two optional fields round out the SKU: `allergen_tags`, an array of allergen labels the product carries such as `PEANUT`, `GLUTEN`, or `DAIRY` (defaulting to an empty list; the array's contents are stored verbatim and not restricted to a fixed vocabulary at creation), and `taxable`, a boolean that defaults to false and, when true, subjects the line's goods to tax after discount.

A **refill station** is created with a `name` and an optional `station_status` of `OPEN` (the default) or `MAINTENANCE`; a station in `MAINTENANCE` cannot host new order fills. A **bulk bin** binds a product to a station: it is created with a `product_id`, a `station_id`, a `capacity_g` (at least 1), a `reorder_threshold_g` (at least 0), and a `last_recount_g`. On creation the bin's `on_hand_g` is initialized to `last_recount_g`, its `last_recount_at` is set to the current logical-clock time (which overrides the §2.4 default of `2026-03-01T00:00:00Z` when the clock has moved past it), and its `status` is `OPEN` — unless the initial `last_recount_g` is already at or below `reorder_threshold_g`, in which case the bin is born `LOW`. A bin also tracks `last_shrink_g`, which begins at 0. At most one non-`RETIRED` bin exists per product-and-station pairing, so a fill resolves to a unique bin; the uniqueness is a domain guarantee upheld by callers, not enforced at bin-creation time. Bins can be listed with reverse-reachability filters on `product_id`, `station_id`, and `status`, alongside `limit` and `offset`.

### 3.3. Containers, Deposits, and the Inspection Loop

A **container** is registered with a `container_type` and a member-declared empty weight `declared_tare_g` (at least 0), and optionally a `member_id` for owned stock; when a `Member` role registers a container while supplying a `member_id`, that `member_id` must equal the acting member's id (otherwise the request is refused with `ERR_UNAUTHORIZED`), and the supplied `member_id` must resolve to an existing member. The type is one of `GLASS_500`, `GLASS_1000`, or `BYO`. Deposit value `deposit_cents` is set from the type at registration: a `GLASS_500` carries a 150-cent deposit, a `GLASS_1000` carries 250 cents, and a member-owned `BYO` carries a zero deposit. A fresh container starts `AVAILABLE` with `allergen_hold` of `NONE` and no `measured_tare_g` yet recorded. A container's `allergen_hold` — the residual allergen carried over from the last product filled — is one of `NONE`, `PEANUT`, `GLUTEN`, or `DAIRY`. A container's `status` progresses through `AVAILABLE`, `ISSUED`, `IN_USE`, `RETURNED`, `QUARANTINED`, and the terminal `RETIRED`. Containers can be listed by their owning `member_id` and `status`; the `member_id` filter matches literally, so passing an unowned/null-owner value does not select unowned containers.

Deposit containers follow a cyclic loop. A clerk **issues** an `AVAILABLE` container to a member, supplying the `member_id` (which is a required field and must resolve to an existing member — existence is validated before the current container state is inspected); this sets the container's `member_id` and moves it `AVAILABLE → ISSUED`. Attempting to issue a container that is not `AVAILABLE` is an `ERR_INVALID_CONTAINER_STATE`. The container advances `ISSUED → IN_USE` automatically as a system side effect when the order that references it in a finalized, non-voided line is checked out — that commitment is described in §3.6. A container leaves service in one of two symmetric ways, both moving `IN_USE → RETURNED`: a member or clerk performs an **in-store return** of an `IN_USE` container, or a delivery's container-recovery step returns it (see §3.7). Either path appends a `DEPOSIT_REFUND` ledger entry for the member that adds the deposit to `wallet_delta_cents` and subtracts it from `liability_delta_cents`. Returning a container that is not `IN_USE` is rejected with `ERR_INVALID_CONTAINER_STATE`.

A returned container must be **inspected** before it re-enters service; a clerk or the inventory manager supplies a `result` of `CLEAN`, `RESIDUE`, or `RETIRE`. The results are handled by the pair of the current status and the supplied result. A `CLEAN` result on a `RETURNED` container clears its `allergen_hold` to `NONE`, wipes its `measured_tare_g` back to empty (null), releases its `member_id` to unowned (null), and moves it `RETURNED → AVAILABLE`, re-entering the loop. A `RESIDUE` result on a `RETURNED` container moves it `RETURNED → QUARANTINED`, marking it for deep cleaning; a `RETIRE` result supplied against a `RETURNED` container is not a defined transition and is rejected with `ERR_INVALID_CONTAINER_STATE`. A quarantined container can itself be inspected: a `CLEAN` result clears its `allergen_hold` to `NONE` (leaving its `measured_tare_g` and `member_id` untouched) and moves it `QUARANTINED → AVAILABLE`, while a `RETIRE` result moves it `QUARANTINED → RETIRED`, permanently removing it; a `RESIDUE` result supplied against a `QUARANTINED` container is not a defined transition and is rejected with `ERR_INVALID_CONTAINER_STATE`. `RETIRED` is terminal. Inspecting a container that is neither `RETURNED` nor `QUARANTINED` is an `ERR_INVALID_CONTAINER_STATE`.

### 3.4. Drafting an Order: Cart Creation and Provisional Lines

A member or clerk opens an order by naming the ordering `member_id`, the `station_id` where it will be filled, a `fill_window_start_at`, a `fill_window_end_at`, and optionally a `fulfillment_channel` of `IN_STORE` (the default) or `DELIVERY`. The new order begins with `fulfillment_status` of `CART` and `payment_status` of `UNPAID`, and it claims the requested fill-window on its station under the overlap rule of §2.8, failing with `ERR_STATION_SESSION_OVERLAP` on a conflict. The `fulfillment_status` is one of `CART`, `FILLING`, `FILLED`, `COMPLETED`, or `CANCELLED`, and it evolves independently of the `payment_status`, which is either `UNPAID` or `CAPTURED`. Orders can be listed with reverse-reachability filters on `member_id`, `station_id`, and `fulfillment_status`.

Into a `CART` order, a member or clerk **adds a refill line** by naming the `product_id`, the `container_id` the line will dispense into, and an `estimated_gross_g` (the member's intended full weight, at least 1). Adding a line is only allowed while the order is `CART`; otherwise the attempt fails with `ERR_INVALID_ORDER_STATE`. The `product_id` and `container_id` referenced by the body must resolve to existing resources (else the matching 404), but the container is not required to be owned by the ordering member at add-time — line-add records the container reference and defers ownership enforcement to the fill step (§3.5). On add, the line's `order_id` is taken from the order, its `declared_tare_g` is copied from the container's `declared_tare_g`, and it is priced provisionally: the line's `net_weight_g` is `estimated_gross_g` minus the copied `declared_tare_g`, its `line_price_cents` is computed from that provisional net weight (see §3.5 for the shared pricing rule), and its `pricing_stage` is `PROVISIONAL`. A line's `pricing_stage` is one of `PROVISIONAL`, `FINAL`, or `VOIDED`. Lines can be listed with reverse-reachability filters on `order_id`, `product_id`, `container_id`, `bin_id`, and `pricing_stage`.

### 3.5. Filling: Weighing, Final Pricing, and Bin Depletion

Before any weighing, a clerk **starts the fill**, moving the order `CART → FILLING`. This is permitted only when the order is `CART` (else `ERR_INVALID_ORDER_STATE`), the order has at least one non-voided line (otherwise `ERR_EMPTY_ORDER`), and the station's `station_status` is `OPEN`; a station in `MAINTENANCE` blocks the start with `ERR_INVALID_STATE`.

The clerk then **fills** each line, weighing the container and supplying the `gross_weight_g` (full weight) and the `measured_tare_g` (clerk-weighed empty weight). Filling drives the line `PROVISIONAL → FINAL` and is gated by a sequence of checks that follow the global priority order of §2.9. First, the parent order must be `FILLING` (and the line's own `pricing_stage` must be `PROVISIONAL`), else `ERR_INVALID_ORDER_STATE`. Next come the safety checks: the container's `allergen_hold` must be `NONE` or must be an allergen the product itself carries in its `allergen_tags` (so a residual peanut hold is acceptable only when refilling a peanut product); otherwise the fill is rejected with `ERR_ALLERGEN_CONFLICT`. The line's bin is resolved as the unique non-`RETIRED` bin for the product at the order's station — if no such bin exists the fill fails with `ERR_BIN_NOT_FOUND`, and if the resolved bin is `QUARANTINED` it fails with `ERR_BIN_QUARANTINED` (a bin in `OPEN` or `LOW` is fine to dispense from). Then ownership is checked: the container's `member_id` must equal the order's `member_id`, else `ERR_CONTAINER_NOT_OWNED`. The weighed values must yield a positive net: `gross_weight_g` minus `measured_tare_g` must be greater than zero, else `ERR_TARE_EXCEEDS_GROSS`. Finally, the line's net weight must not exceed the bin's `on_hand_g`, else `ERR_INSUFFICIENT_STOCK`.

On a successful fill, the container's `measured_tare_g` is set from the payload, the line's `gross_weight_g` is recorded, and its `net_weight_g` is recomputed as `gross_weight_g` minus the container's `measured_tare_g`. The line's `line_price_cents` is recomputed with these final inputs and its `pricing_stage` becomes `FINAL`. The line's `bin_id` is bound to the resolved bin, and the bin's `on_hand_g` is decreased by the line's net weight; if that leaves `on_hand_g` at or below `reorder_threshold_g`, the bin flips `OPEN → LOW` and a `RestockTask` is auto-created for it (per §2.7). Finally, if the product carries any `allergen_tags`, the container's `allergen_hold` is set to the first of those tags (in the order they appear in the product's `allergen_tags` array); if the product carries none, the hold is left unchanged.

**The refill line price** is computed identically at both stages, differing only in which net weight feeds it. In the provisional stage the net weight is `estimated_gross_g` minus `declared_tare_g`; in the final stage it is `gross_weight_g` minus the container's `measured_tare_g`. The rate is selected at the bulk boundary: if the net weight is greater than or equal to the product's `bulk_tier_threshold_g`, the discounted `bulk_tier_price_cents_per_100g` applies; otherwise the base `unit_price_cents_per_100g` applies. Because the rate is quoted per 100 grams, the raw goods value in cents is the selected rate multiplied by the net grams and divided by 100. If the owning member's `membership_tier` is `PLUS`, the goods value is then multiplied by 0.90 (one minus the 0.10 discount factor); a `BASIC` member's goods value is unchanged. The `line_price_cents` is that discounted goods value rounded half up to a whole cent, rounded per line. Because the final weighed net weight can cross the bulk-tier boundary that the provisional estimate did not (or fall short of one it did), the final price can legitimately differ from the provisional estimate.

A clerk may **void** a line. Voiding a `PROVISIONAL` line simply moves it `PROVISIONAL → VOIDED`, regardless of the parent order's current fulfillment status. Voiding an already-`VOIDED` line is rejected with `ERR_INVALID_ORDER_STATE`. Voiding a `FINAL` line is permitted only while the parent order's `payment_status` is still `UNPAID` (a captured line cannot be voided); it moves the line `FINAL → VOIDED` and returns its `net_weight_g` to the bin's `on_hand_g` as a grams-conservation compensating action, which may lift the bin from `LOW` back to `OPEN` when `on_hand_g` rises above the reorder threshold.

An order may be **cancelled** by a member or clerk while it is still `CART` or `FILLING`; a cancel attempt on an order in any other state is rejected with `ERR_INVALID_ORDER_STATE`. Cancelling a `CART` order moves it `CART → CANCELLED` and voids all of its `PROVISIONAL` lines, moving each `PROVISIONAL → VOIDED`. Cancelling a `FILLING` order moves it `FILLING → CANCELLED` and, because that order's lines may already hold dispensed stock, voids each `FINAL` line — moving it `FINAL → VOIDED` — and returns that line's `net_weight_g` to its bin's `on_hand_g`, applying the same grams-conservation and possible `LOW → OPEN` recovery as a manual line void.

### 3.6. Checkout: Settlement, Deposits, Tax, and Loyalty

A member or clerk **checks out** a `FILLING` order, optionally supplying `redeem_points` to spend loyalty. Checkout is permitted only when the order is `FILLING`; if any non-voided line has not yet reached `FINAL`, checkout is rejected with `ERR_INVALID_ORDER_STATE`; and if no non-voided `FINAL` line exists, checkout is rejected with `ERR_EMPTY_ORDER`. In a single atomic step, checkout advances `fulfillment_status` `FILLING → FILLED` and `payment_status` `UNPAID → CAPTURED` (the payment dimension evolves independently of fulfillment and advances only here), recomputes the order totals, commits container deposits, and accrues loyalty. If the order's `fulfillment_channel` is `IN_STORE`, the same checkout also completes the handoff, moving `fulfillment_status` `FILLED → COMPLETED`; a `DELIVERY` order instead completes later through its delivery.

**Deposit commitment.** Each distinct `ISSUED` container referenced by a `FINAL` line on the order (a container referenced by more than one `FINAL` line is committed only once) moves `ISSUED → IN_USE`, and for each such container a `DEPOSIT_COMMIT` ledger entry is appended raising `liability_delta_cents` by the container's `deposit_cents` (with `wallet_delta_cents` and `points_delta` both 0). The order's `deposit_total_cents` is the sum of `deposit_cents` over exactly these committed containers.

**Order totals**, recomputed at checkout (and reflected on any subsequent read of the order), follow a pinned order. First, `subtotal_cents` is the sum of `line_price_cents` over the order's `FINAL`, non-voided lines — a sum of already-rounded line prices. Second, `discount_cents` is the loyalty redemption: the smaller of the supplied `redeem_points` (treated as zero when omitted, null, or non-positive) and the subtotal, where one point redeems one cent, so the discount never exceeds the subtotal — note that this cap is applied against the raw `redeem_points` value rather than against the member's actual `loyalty_points_balance`, so the `discount_cents` figure written to the order may exceed the points actually deducted from the ledger; when the order supplies `redeem_points` greater than zero, a `LOYALTY_REDEEM` ledger entry is appended with `points_delta` equal to the negative of the smaller of `redeem_points` and the member's `loyalty_points_balance` at that instant (and the entry is omitted when that smaller value is zero, e.g. when the member's balance is zero). Third, deposits are added after the discount and are themselves never discounted or taxed. Fourth, tax is computed on taxable goods net of the taxable share of the discount: let taxable goods be the sum of `line_price_cents` over `FINAL` non-voided lines whose product is `taxable`; if the subtotal equals the taxable goods, the taxable base is the taxable goods minus the discount, floored at zero; otherwise, when the subtotal is positive, the taxable base is the taxable goods minus a proportional share of the discount, that share being `discount_cents` multiplied by taxable goods divided by the subtotal and rounded half up to a whole cent, and the resulting taxable base is likewise floored at zero should the rounded share exceed the taxable goods; when the subtotal is zero the taxable base is zero. The `tax_cents` is 8% of that taxable base, rounded half up to a whole cent, and is zero when the order has no taxable lines. Fifth, `total_cents` equals `subtotal_cents` minus `discount_cents` plus `deposit_total_cents` plus `tax_cents`.

**Loyalty accrual.** Loyalty is earned as an integer number of points. The base points are the settled amount divided by 100 (one base point per 100 cents, i.e., per dollar), taking the floor; at final checkout the settled amount is `subtotal_cents` minus `discount_cents`. Those base points are multiplied by a tier multiplier of 1.5 for a `PLUS` member or 1.0 for a `BASIC` member, and the product is floored to a whole number. This final figure is recorded as the order's `loyalty_points_earned` and credited by a `LOYALTY_ACCRUAL` ledger entry whose `points_delta` is that value; the accrual entry is appended unconditionally on every checkout (including when `loyalty_points_earned` is zero). A provisional loyalty estimate is conceptually available at start-fill using the same floor-by-100-then-multiply-by-tier-then-floor rule applied to the sum of the `PROVISIONAL` line prices; that estimate is written to no ledger and is not surfaced on the start-fill response (the order's `loyalty_points_earned` remains 0 until checkout), and because it rests on estimated rather than weighed weights its value can legitimately differ from the final accrual.

### 3.7. Delivery and the Container Return Loop

For a `DELIVERY` order, a member or clerk **schedules a delivery** by naming the `order_id`, the `vehicle_id`, a `window_start_at`, and a `window_end_at`. The delivery's `member_id` is copied from the order, and the delivery starts `SCHEDULED`. Delivery scheduling does not require the underlying order's `fulfillment_channel` to be `DELIVERY`; the channel gate is applied later — an `IN_STORE` order's checkout already advances the order to `COMPLETED` in one step, and dispatch/deliver still require the order to be `FILLED` and `CAPTURED`, so an `IN_STORE` order would fail the dispatch readiness check. The requested window must respect the turnaround rule of §2.8 on the chosen vehicle, failing with `ERR_VEHICLE_WINDOW_CONFLICT` when it falls within `TURNAROUND_BUFFER_MIN` minutes of another non-cancelled window on the same vehicle. A delivery vehicle is registered beforehand by the inventory manager with a `plate` (unique across vehicles — a collision is `ERR_DUPLICATE_EMAIL`) and an informational `capacity_orders` (at least 1) giving the maximum concurrent orders per run. `capacity_orders` is purely informational — the server does not enforce it against the count of deliveries actually scheduled on the vehicle. A delivery vehicle carries only the common `id`/`created_at`/`updated_at`/`version` fields alongside `plate` and `capacity_orders` (no `status` field). Deliveries can be listed by `order_id`, `vehicle_id`, `member_id`, and `status`.

The delivery advances through its own states. **Dispatching** a `SCHEDULED` delivery moves it `SCHEDULED → DISPATCHED`, but only when the underlying order is both `FILLED` and `CAPTURED`; if the order is not yet fully filled and paid, dispatch is refused with `ERR_DELIVERY_ORDER_NOT_READY`. **Delivering** a `DISPATCHED` delivery moves it `DISPATCHED → DELIVERED` and, as a cross-entity effect, unconditionally sets the underlying order's `fulfillment_status` to `COMPLETED` (advancing the order even if it was not previously in `FILLED`). **Receiving the return** on a `DELIVERED` delivery moves it `DELIVERED → RETURNED`, closing the container loop: for each distinct container referenced by a `FINAL`, non-voided line on the delivery's order that is currently `IN_USE`, the container is moved `IN_USE → RETURNED` and a `DEPOSIT_REFUND` ledger entry is appended adding the deposit to `wallet_delta_cents` and subtracting it from `liability_delta_cents`, which in turn shifts the member's `wallet_balance_cents` and `deposit_liability_cents` projections. Containers referenced only by `PROVISIONAL` or `VOIDED` lines are not part of this refund cycle. A `SCHEDULED` delivery may instead be **cancelled**, moving it `SCHEDULED → CANCELLED` and freeing its vehicle window for other deliveries. Only a `SCHEDULED` delivery may be cancelled; delivery cancellation is a clerk/inventory-manager operation and is not authorised for members. Each delivery transition is guarded by the delivery's current status, and an out-of-state attempt is an `ERR_INVALID_STATE`; specifically, dispatch requires `SCHEDULED`, deliver requires `DISPATCHED`, return-received requires `DELIVERED`, and cancel requires `SCHEDULED`. The dispatch endpoint additionally evaluates the underlying order's readiness after its own state check, so a `SCHEDULED` delivery whose order is not `FILLED` and `CAPTURED` is rejected with `ERR_DELIVERY_ORDER_NOT_READY`.

### 3.8. Subscriptions and Recurring Refills

A member or clerk creates a **subscription** for a recurring refill by naming the `member_id`, the `product_id`, the default `station_id` for generated orders, a `target_net_g` (net grams to dispense each cycle, at least 1), and an `interval_days` (days between runs, at least 1). The subscription begins `ACTIVE` with a `last_run_order_id` of null, and its `next_run_at` is set to the current logical-clock time plus `interval_days` days.

**Running** a subscription cycle produces a fresh order. The run must carry `expected_subscription_version` and is admitted only when the subscription is `ACTIVE` and that expected version equals the subscription's current `version`; a non-`ACTIVE` subscription is rejected first (state check ahead of the version check) with `ERR_INVALID_STATE`, and a version mismatch on an `ACTIVE` subscription is rejected with `ERR_STALE_VERSION` (see §2.10). A successful run creates a new order for the subscriber (`member_id`, the subscription's `station_id`, `fulfillment_channel` of `DELIVERY`) in `CART`, whose `fill_window_start_at` is the current logical-clock time and whose `fill_window_end_at` is one hour after that start; this generated fill-window is not checked for station overlap against other orders (the overlap rule of §2.8 is skipped for subscription-generated orders). One `PROVISIONAL` refill line is added for the subscription's `product_id` at the `target_net_g`, with `container_id` null, `declared_tare_g` recorded as 0, `estimated_gross_g` equal to `target_net_g`, and `line_price_cents` computed by the same rule as §3.5 with the subscription member's tier applied. The run records the new order's id in `last_run_order_id` (an audit back-reference, not a validated foreign key), sets `next_run_at` to the current logical-clock time plus `interval_days` days, and increments the subscription's `version` by one. Each run legitimately supersedes the prior cycle's pending order, which is precisely why the version guard exists. A member or clerk may **cancel** an `ACTIVE` subscription, moving it `ACTIVE → CANCELLED`. Subscriptions can be listed by `member_id`, `product_id`, `station_id`, and `status`.

### 3.9. Inventory Reconciliation: Restocking and Shrink Recounts

When a fill flips a bin to `LOW`, the auto-created `RestockTask` names the `bin_id` and records a `requested_fill_g` equal to the bin's `capacity_g` minus its `on_hand_g` at creation time; it starts `OPEN` with `restocked_g` null. The inventory manager **completes** a task by supplying a `restocked_g` (which must be a non-negative integer — a negative value is rejected with `ERR_VALIDATION`), and only an `OPEN` task may be completed (any other status yields `ERR_INVALID_STATE`). A `restocked_g` of at least 1 adds those grams to the bin's `on_hand_g` — but only if the addition does not overfill the bin, that is, `on_hand_g` plus `restocked_g` must not exceed `capacity_g`, otherwise the completion is rejected with `ERR_INSUFFICIENT_STOCK`; the grams actually added are recorded in `restocked_g`, the task moves `OPEN → COMPLETED`, and if the resulting `on_hand_g` is now above `reorder_threshold_g` the bin returns `LOW → OPEN`. Symmetrically, a completion call with `restocked_g` equal to 0 adds no grams, leaves the task's `restocked_g` field null, and instead cancels the task, moving it `OPEN → CANCELLED`. Restock tasks can be listed by `bin_id` and `status`.

Independently, the inventory manager records a physical **recount** on a bin by supplying the counted `physical_g`, which reconciles book stock against reality and detects shrink. The reconciliation replays the bin's movements since its `last_recount_at` baseline, in ascending `created_at` order: dispensed grams is the sum of `net_weight_g` over lines with `pricing_stage` of `FINAL` bound to this bin (a line's `pricing_stage` is `FINAL` — never `VOIDED` — for the duration it remains bound to a bin, so voided lines are naturally excluded by the `FINAL`-only filter) whose `created_at` is at or after `last_recount_at`, and restocked grams is the sum of `restocked_g` over `COMPLETED` restock tasks for this bin whose completion instant is at or after that baseline. The theoretical book on-hand is the bin's `last_recount_g` minus dispensed plus restocked. Shrink is that book on-hand minus the counted `physical_g`, and a positive shrink means inventory is missing; the result is stored in `last_shrink_g`. On commit, the bin's `on_hand_g` and `last_recount_g` are both set to `physical_g`, and its `last_recount_at` is set to the current logical-clock time. If the computed shrink is strictly greater than 200 grams, the bin is moved to `QUARANTINED`, blocking dispensing pending investigation; a later re-recount whose shrink is 200 grams or less returns the `QUARANTINED` bin to `OPEN` (a `LOW` bin whose recount both keeps shrink within the allowance and yields the QUARANTINED-clearing branch is not currently re-evaluated for the reorder-threshold and remains `OPEN` after the clear). A recount that keeps shrink within the 200-gram allowance on an `OPEN` or `LOW` bin leaves the bin dispensable.

## 4. Endpoint Definitions

Creation of a new, stand-alone resource returns `201 Created`; state transitions and other modifications of an existing resource return `200 OK`. The reference-data reads return `200 OK`. Consult the §3 narratives for each endpoint's request fields, side effects, and response semantics — the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the server logical clock | InventoryManager |
| POST | `/v1/members` | Register a member | StoreClerk |
| GET | `/v1/members/{memberId}` | Fetch a member with projected balances | Any |
| GET | `/v1/members/{id}/wallet-ledger` | List a member's wallet-ledger movements | Any |
| POST | `/v1/products` | Create a bulk SKU with tier and allergen config | InventoryManager |
| GET | `/v1/products/{productId}` | Fetch a product | Any |
| POST | `/v1/stations` | Create a refill station | InventoryManager |
| GET | `/v1/stations/{stationId}` | Fetch a station | Any |
| POST | `/v1/bins` | Create a bulk bin for a product at a station | InventoryManager |
| GET | `/v1/bins/{binId}` | Fetch a bin | Any |
| GET | `/v1/bins` | List bins | Any |
| POST | `/v1/bins/{binId}/recount` | Record a physical recount; compute shrink | InventoryManager |
| POST | `/v1/containers` | Register a deposit or BYO container | Member, StoreClerk |
| GET | `/v1/containers/{containerId}` | Fetch a container | Any |
| GET | `/v1/containers` | List containers | Any |
| POST | `/v1/containers/{containerId}/issue` | Issue an available container to a member | StoreClerk |
| POST | `/v1/containers/{containerId}/return` | Return an in-use container in store; refund deposit | Member, StoreClerk |
| POST | `/v1/containers/{containerId}/inspect` | Inspect a returned or quarantined container | StoreClerk, InventoryManager |
| POST | `/v1/orders` | Create a cart order occupying a station fill-window | Member, StoreClerk |
| GET | `/v1/orders/{orderId}` | Fetch an order with computed totals | Any |
| GET | `/v1/orders` | List orders | Any |
| POST | `/v1/orders/{orderId}/lines` | Add a provisional refill line to a cart order | Member, StoreClerk |
| POST | `/v1/orders/{orderId}/start-fill` | Move a cart order to filling | StoreClerk |
| POST | `/v1/orders/{orderId}/checkout` | Check out a filling order | Member, StoreClerk |
| POST | `/v1/orders/{orderId}/cancel` | Cancel a cart or filling order | Member, StoreClerk |
| GET | `/v1/refill-lines/{lineId}` | Fetch a refill line | Any |
| GET | `/v1/refill-lines` | List refill lines | Any |
| POST | `/v1/refill-lines/{lineId}/fill` | Weigh and finalize a line | StoreClerk |
| POST | `/v1/refill-lines/{lineId}/void` | Void a provisional or pre-capture final line | StoreClerk |
| GET | `/v1/restock-tasks/{taskId}` | Fetch a restock task | StoreClerk, InventoryManager |
| GET | `/v1/restock-tasks` | List restock tasks | StoreClerk, InventoryManager |
| POST | `/v1/restock-tasks/{taskId}/complete` | Complete or cancel a restock task | InventoryManager |
| POST | `/v1/subscriptions` | Create a recurring refill subscription | Member, StoreClerk |
| GET | `/v1/subscriptions/{subscriptionId}` | Fetch a subscription | Any |
| GET | `/v1/subscriptions` | List subscriptions | Any |
| POST | `/v1/subscriptions/{subscriptionId}/run` | Run a subscription cycle now (OCC on version) | Member, StoreClerk |
| POST | `/v1/subscriptions/{subscriptionId}/cancel` | Cancel an active subscription | Member, StoreClerk |
| POST | `/v1/delivery-vehicles` | Register a delivery vehicle | InventoryManager |
| GET | `/v1/delivery-vehicles/{vehicleId}` | Fetch a delivery vehicle | Any |
| POST | `/v1/deliveries` | Schedule a delivery on a vehicle window | Member, StoreClerk |
| GET | `/v1/deliveries/{deliveryId}` | Fetch a delivery | Any |
| GET | `/v1/deliveries` | List deliveries | Any |
| POST | `/v1/deliveries/{deliveryId}/dispatch` | Dispatch a scheduled delivery | StoreClerk, InventoryManager |
| POST | `/v1/deliveries/{deliveryId}/deliver` | Mark a dispatched delivery delivered; complete order | StoreClerk, InventoryManager |
| POST | `/v1/deliveries/{deliveryId}/return-received` | Close the return loop; refund container deposits | StoreClerk, InventoryManager |
| POST | `/v1/deliveries/{deliveryId}/cancel` | Cancel a scheduled delivery | StoreClerk, InventoryManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_BIN_NOT_FOUND` | 404 Not Found |
| `ERR_CONTAINER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_RESTOCK_TASK_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_INVALID_CONTAINER_STATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALLERGEN_CONFLICT` | 409 Conflict |
| `ERR_BIN_QUARANTINED` | 409 Conflict |
| `ERR_CONTAINER_NOT_OWNED` | 409 Conflict |
| `ERR_STATION_SESSION_OVERLAP` | 409 Conflict |
| `ERR_VEHICLE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 422 Unprocessable Entity |
| `ERR_TARE_EXCEEDS_GROSS` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_DELIVERY_ORDER_NOT_READY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
