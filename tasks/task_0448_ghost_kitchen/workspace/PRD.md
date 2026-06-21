# Ghost Kitchen & Virtual Brand Platform API — Product Requirements Document

## 1. Introduction

The Ghost Kitchen & Virtual Brand Platform is a delivery-only fulfillment system that sits between physical commissary kitchens and the food-delivery marketplaces that send them business. Operators license out individual stalls inside their kitchens; entrepreneurs run "virtual brands" — consumer-facing restaurant concepts that exist only on aggregator apps such as DoorDash and Uber Eats — and lease space across one or more of those stalls. When a hungry consumer places an order, the marketplace pushes it into this platform, which must decide where the food can actually be cooked, reserve a slice of shared equipment time, draw down the right ingredients from commissary inventory, and ultimately reconcile what the brand earns against what the platform charges.

This document specifies the behavioral contract for that platform. The hard problems it solves are temporal and financial: an inbound order has to land on an open brand whose stall is open, claim a contiguous block of time on a fryer, oven, grill, or prep station without colliding with any other booking, and deplete ingredient lots in the order they were received. Money flows in two passes — a forward-looking commission estimate captured the moment an order is routed, and a chronological, first-in-first-out food-cost figure finalized only when the order is actually fulfilled — and the difference between the two settles onto a running brand ledger. Cancellations must surgically undo everything a routed order touched, restoring inventory and freeing equipment, while never crediting money that was never earned.

The reader of this document is the engineer who will implement the API. Every rule that governs routing eligibility, equipment scheduling, inventory accounting, ledger settlement, and concurrency control is described below in business terms; the structural contract (response envelopes, pagination, headers, status codes) is fixed and precise.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present and the role is known but that role is not permitted to perform the requested operation — or an ownership-scoped role is acting on a resource it does not own — the request is rejected with `ERR_FORBIDDEN`.

The platform recognizes exactly four roles, spelled here exactly as they must appear in the header value: `PlatformOps`, `StallOperator`, `BrandOwner`, and `AggregatorGateway`.

`PlatformOps` is the platform operator. When `X-User-Role` is `PlatformOps`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it against any entity's `id`. `PlatformOps` provisions stalls, brands, and leases, drives order routing, rejection, and cancellation, suspends and reinstates leases, and controls the test clock.

`StallOperator` runs a physical kitchen. When `X-User-Role` is `StallOperator`, `X-User-ID` is the `id` of the acting `Stall`; ownership checks on any resource that references a `Stall` compare that resource's stall reference to `X-User-ID`. Concretely, a `StallOperator` may only act on `Equipment`, `IngredientLot`, and maintenance-hold `EquipmentBooking` records whose stall is the one identified by `X-User-ID`, may only open or close that same stall, may only activate or terminate a `KitchenLease` whose `stall_id` is its own stall, and may only start prep or fulfill an `AggregatorOrder` whose `routed_stall_id` is its own stall.

`BrandOwner` owns a virtual brand. When `X-User-Role` is `BrandOwner`, `X-User-ID` is the `id` of the acting `VirtualBrand`; ownership checks on any resource that references a `VirtualBrand` compare that resource's brand reference to `X-User-ID`. A `BrandOwner` may manage menu items and recipes under its own brand and may list, pause, or deactivate only its own brand.

`AggregatorGateway` is the integration identity for marketplace order ingestion. When `X-User-Role` is `AggregatorGateway`, `X-User-ID` is an opaque integration identifier not tied to any persisted entity; the server does not compare it against any entity's `id`. This role's sole writing capability is pushing inbound orders.

Two creation endpoints — registering a stall and registering a brand — still require an authenticated, permitted `PlatformOps` caller even though the created resource has no prior owner; an unauthenticated caller is rejected with `ERR_UNAUTHENTICATED` and a non-`PlatformOps` caller with `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

Every list response carries the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in this platform — `Stall`, `VirtualBrand`, `KitchenLease`, `Equipment`, `EquipmentBooking`, `MenuItem`, `IngredientLot`, and `AggregatorOrder` — carry a uniform set of system-managed fields. Each such resource has an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) marking when it was first created, an `updated_at` timestamp (same format) refreshed on every mutation, and a `version` integer that starts at the resource's creation value and increments by one on every mutation. The `version` field is the basis for optimistic concurrency control described in §2.6.

`RecipeComponent` is the lone exception. A recipe line is immutable once written, so it carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field. Implementers must not emit those two fields on a `RecipeComponent`.

Whenever a rule in this document says an operation "bumps the version" or "refreshes `updated_at`," it means exactly this: the affected resource's `version` increases by one and its `updated_at` is set to the current time. Derived-field changes count as mutations — for example, when an order settlement adjusts a brand's `ledger_balance_cents`, or when equipment retirement adjusts a stall's `equipment_count`, the touched parent resource's `version` increments and its `updated_at` advances.

### 2.5. Nested Path Resolution and Reference Integrity

Several read endpoints are addressed through a parent path segment that scopes a reverse lookup — listing the equipment or ingredient lots under a stall, the menu items under a brand, the recipe components under a menu item, or the bookings under an equipment unit. For any request whose path carries one or more resource identifiers, the server validates those identifiers left to right and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND`. Path identifiers are always checked before body references. After path resolution, any foreign-key reference supplied in a request body (for example, the stall and brand a lease points at, or the brand a menu item belongs to) must also resolve to an existing resource, again under `ERR_NOT_FOUND`. This existence check (priority 3) runs before any state, business, or field-shape validation.

### 2.6. Optimistic Concurrency Control

Cancelling a routed or preparing order is the one mutation in this platform guarded by optimistic concurrency control. A cancel request must carry `expected_order_version`, a non-optional field carrying the client's last observed `version` of the target `AggregatorOrder`. The server compares it against the order's current `version`; if they do not match, the cancel is rejected with `ERR_STALE_VERSION` (HTTP 412). A routed order's `version` is silently advanced by cascaded side effects — a fulfill that finalized food cost, or a prior cancel that already released the booking and restored inventory — so a cancel carrying a stale `expected_order_version` is acting on a view of the order that no longer reflects its committed inventory and booking effects, and is refused on the stale-version check. No other endpoint accepts or requires a version field; only order cancellation participates in this protocol.

### 2.7. Operating Hours and the Logical Clock

A stall's daily operating window is expressed in minutes from midnight in the stall's own timezone. `open_minute_of_day` is the opening moment and must satisfy being at least 0 and strictly less than 1440, and it must be strictly less than `close_minute_of_day`. `close_minute_of_day` is the closing moment and must be strictly greater than 0 and at most 1440 (where 1440 denotes midnight at the end of the day), and it must be strictly greater than `open_minute_of_day`. A stall also carries an IANA `timezone` string (for example, `America/Los_Angeles`) used to interpret those minutes.

All absolute time arithmetic — equipment booking windows in particular — runs against a server-side logical clock rather than wall-clock time. The clock starts at exactly `2026-01-01T00:00:00Z` on server startup, and until it is explicitly set it reads that default and never falls back to real time. An admin-only test-driving capability, available to `PlatformOps`, advances the clock to a supplied instant carried in the `to_iso8601` field. The "current clock minute" used throughout equipment scheduling is the floor of the clock's epoch-second value divided by 60 — that is, the whole number of minutes since the Unix epoch (UTC).

### 2.8. Equipment Scheduling and Turnaround Buffers

Equipment time is reserved as half-open windows expressed as absolute minutes since the Unix epoch: a booking covers `start_minute` (inclusive) up to but not including `end_minute`. A booking's `start_minute` must be at least 0 and strictly less than its `end_minute`, and `end_minute` must be strictly greater than `start_minute`.

Each `Equipment` unit carries a `turnaround_buffer_minutes` value — a mandatory cleaning and cooldown gap enforced *after* every booking on that unit before the next one may begin; it must be 0 or greater, and defaults to 0 when omitted at creation. Two bookings on the same unit are compatible only if a full buffer separates them in both directions: a new booking may start no earlier than an existing booking's `end_minute` plus that unit's `turnaround_buffer_minutes` (the lower bound is inclusive — starting exactly at that minute is allowed), and symmetrically an existing booking may begin no earlier than the new booking's `end_minute` plus the buffer. A new window that intersects any existing `HELD` window on the unit, or that fails to leave the required buffer on either side, is a conflict. Only `HELD` bookings occupy the schedule; a `RELEASED` booking has freed its window and no longer constrains new bookings.

### 2.9. Monetary and Quantitative Precision

Money in this platform is always integer cents, and ingredient quantities are always integer grams; there are no fractional units anywhere. Two specific computations involve a division and therefore a rounding decision:

- **Commission.** The forward-looking commission is the gross revenue in cents multiplied by the brand's commission rate in basis points, divided by 10000, with the result rounded half up to a whole number of cents. The rounding is applied once, to the single final product — never per line item.
- **Everything else.** Gross revenue, food cost, and ledger settlement are pure sums and differences of integers; no rounding occurs because every operand is already an integer.

Basis points are hundredths of a percent, so 100 basis points equal one percent; the divisor that converts basis points into a plain fraction is 10000.

### 2.10. Cascading Consistency and Compensation

Many operations touch more than one entity in a single atomic request. Activating a lease can bubble a brand from onboarding to active. Routing an order reserves equipment, draws down inventory across several lots, and may flip menu items to sold-out. Cancelling an order is a precise compensation that reverses exactly what routing did — crediting back the exact grams each lot gave up, possibly flipping sold-out items back to available, and freeing the reserved equipment window. Fulfilling an order finalizes food cost, credits the brand ledger, and releases the booking. Every entity touched in any of these cascades has its own `version` incremented and its own `updated_at` refreshed, independently. All such side effects either fully commit together or — when a precondition fails partway, such as insufficient inventory during routing — none of them commit; routing in particular performs no partial inventory deduction.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Kitchen: Stalls and Equipment

A `PlatformOps` operator registers a physical kitchen by supplying its display `name`, its IANA `timezone`, and its daily `open_minute_of_day` and `close_minute_of_day`. A freshly registered stall is born `OPEN` with an `equipment_count` of 0. The `status` of a stall is the `OPEN`/`CLOSED` axis: a stall is conceptually open when the current clock minute falls inside its operating window and it has not been manually closed, and closed otherwise, with the manual override transitions described below being authoritative.

The stall owner — the `StallOperator` whose `X-User-ID` equals the stall's `id` — can manually take the stall offline, moving it from `OPEN` to `CLOSED`, which blocks any new order from being routed to that stall regardless of operating hours; attempting this while the stall is already `CLOSED` is an invalid transition rejected with `ERR_INVALID_STATE`. The same operator can bring it back, moving from `CLOSED` to `OPEN`, which is likewise rejected with `ERR_INVALID_STATE` if the stall is not currently `CLOSED`. Both transitions bump the stall's `version`.

Inside a stall, its operator installs shared cooking equipment by supplying the owning `stall_id`, an `equipment_type` (one of `FRYER`, `OVEN`, `GRILL`, or `PREP_STATION`), and optionally a `turnaround_buffer_minutes` gap. A new unit starts `AVAILABLE`, and creating it increments the owning stall's `equipment_count` by one (with the stall's `version` and `updated_at` advancing as a consequence). Equipment has three statuses: `AVAILABLE` means bookable, `MAINTENANCE` means temporarily unbookable, and `RETIRED` is terminal. The operator can take an `AVAILABLE` unit into `MAINTENANCE` and later restore it from `MAINTENANCE` back to `AVAILABLE`; each direction requires the unit to be in the expected starting state and is otherwise rejected with `ERR_INVALID_STATE`, and each bumps the unit's `version`. Retiring a unit moves it from `AVAILABLE` to `RETIRED`, but only when no `EquipmentBooking` for that unit is still `HELD`; a unit with a live held booking cannot be retired and the attempt is rejected with `ERR_INVALID_STATE`. Retirement also decrements the owning stall's `equipment_count` by one and bumps both the equipment's and the stall's `version`. All four equipment write operations are restricted to the `StallOperator` that owns the equipment's stall.

A stall's denormalized `equipment_count` is exactly the number of `Equipment` rows whose stall reference is that stall and whose `status` is not `RETIRED`; it is reconciled on equipment creation and retirement so that it always reflects that count.

### 3.2. Brands, Menus, and Recipes

Virtual brands are the consumer-facing concepts. A `PlatformOps` operator registers a brand with a consumer-facing `name`, an `owner_email` for the proprietor, and a `commission_rate_bps` — the platform's cut of gross order revenue expressed in basis points, which must be between 0 and 5000 inclusive. A new brand starts life with `status` of `ONBOARDING`, `availability` of `PAUSED`, and a `ledger_balance_cents` of 0.

A brand carries two independent state dimensions. The first, `status`, is the lifecycle axis with values `ONBOARDING`, `ACTIVE`, and `DEACTIVATED`. The second, `availability`, is the menu-visibility axis with values `LISTED` (orderable on aggregators) and `PAUSED` (temporarily hidden); these two axes evolve independently of one another. A brand becomes `ACTIVE` only as a side effect of its first lease activating (see §3.3), never by direct request. Once a brand is `ACTIVE`, its owner — the `BrandOwner` whose `X-User-ID` equals the brand's `id` — may toggle availability: moving from `PAUSED` to `LISTED` requires both that availability currently be `PAUSED` and that the brand's `status` be `ACTIVE`, while moving from `LISTED` to `PAUSED` requires only that availability currently be `LISTED`. Each availability toggle bumps the brand's `version`, and an attempt from the wrong starting availability is rejected with `ERR_INVALID_STATE`.

The brand owner can deactivate an `ACTIVE` brand, which is a consequential, terminal transition to `DEACTIVATED`. Deactivation is permitted only when the brand is `ACTIVE` and no `AggregatorOrder` for that brand is currently in either `ROUTED` or `PREPARING` status; an in-flight order blocks deactivation with `ERR_INVALID_STATE`. When deactivation does proceed, the brand's `status` becomes `DEACTIVATED`, its `availability` is forced to `PAUSED`, every `KitchenLease` for that brand that is currently `ACTIVE` cascades to `TERMINATED`, and the brand's `version` is bumped.

A brand owner builds out the brand's menu by creating menu items, each supplying the owning `brand_id`, a `name`, a `price_cents` list price (which must be strictly greater than 0), a `prep_minutes` value (the equipment-occupancy minutes to make one unit, which must be at least 1), and a `required_equipment_type` (one of `FRYER`, `OVEN`, `GRILL`, or `PREP_STATION`) naming the class of equipment the item must be cooked on. A new menu item starts `AVAILABLE`. A menu item's `availability` is the `AVAILABLE`/`SOLD_OUT` axis, driven entirely by inventory as described in §3.6 — there is no manual toggle.

Each menu item's recipe is a bill of materials. The brand owner adds recipe lines to an item, each carrying the parent `menu_item_id`, a canonical `ingredient_name`, and a `quantity_grams` figure (strictly greater than 0) giving the grams of that ingredient consumed to make one unit of the item. Recipe lines are immutable once created.

### 3.3. Leasing Stalls to Brands

A `KitchenLease` binds a brand to a stall, and because a brand may operate out of several stalls and a stall may host several brands, leases are the many-to-many fabric of the platform. A `PlatformOps` operator creates a lease by supplying the `stall_id` of the physical stall, the `brand_id` of the occupying brand, a `monthly_fee_cents` licensing fee (strictly greater than 0), and a `priority_rank` (an integer of at least 1) that determines routing precedence at that stall — a lower number wins when several leased brands could serve an order. A new lease starts `PENDING`.

Lease lifecycle has four states: `PENDING` at creation, `ACTIVE` once activated, `SUSPENDED` on non-payment (and reversible), and `TERMINATED` as the terminal end. The owning `StallOperator` — the operator of the stall named by the lease's `stall_id` — activates a `PENDING` lease. Activation requires that the lease be `PENDING`, that the referenced stall exist, and that no other `ACTIVE` lease at the same stall already holds this lease's `priority_rank`. A rank collision at the stall is rejected with `ERR_DUPLICATE_PRIORITY_RANK`; a lease not in `PENDING` is rejected with `ERR_INVALID_STATE`. On success the lease becomes `ACTIVE`, its `version` is bumped, and — if the brand referenced by the lease's `brand_id` is still `ONBOARDING` — that brand cascades from `ONBOARDING` to `ACTIVE` as the second hop of the activation cascade, with the brand's own `version` bumped.

`PlatformOps` may suspend an `ACTIVE` lease, moving it to `SUSPENDED` (which excludes it from routing candidate sets) and bumping its `version`; suspending a lease that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. `PlatformOps` may reinstate a `SUSPENDED` lease back to `ACTIVE`, but reinstatement re-checks priority uniqueness: it is allowed only when the lease is `SUSPENDED` and no other `ACTIVE` lease at the same stall holds this lease's `priority_rank` — a collision is rejected with `ERR_DUPLICATE_PRIORITY_RANK` and a non-suspended lease with `ERR_INVALID_STATE`. The reinstatement bumps the lease's `version`. Because a suspended lease can return to active, the lease lifecycle is non-linear.

Finally, the owning `StallOperator` may terminate a lease from either `ACTIVE` or `SUSPENDED`, moving it to the terminal `TERMINATED` state and bumping its `version`; terminating a lease in any other state is rejected with `ERR_INVALID_STATE`. Termination from suspension and termination from active are equally valid paths into the terminal state.

### 3.4. Commissary Inventory

Ingredient inventory lives at the stall as dated lots. A `StallOperator` receives a lot at its own stall by supplying the holding `stall_id`, the canonical `ingredient_name` (which is matched against recipe lines' `ingredient_name`), a `received_at` timestamp, a `unit_cost_cents_per_gram` acquisition cost (at least 0), and a `grams_received` total (strictly greater than 0). On receipt, the lot's `grams_remaining` is initialized equal to its `grams_received`.

Lots are consumed in first-in-first-out order: when inventory must be drawn for an order, candidate lots are ordered by `received_at` ascending, and ties are broken by `created_at` ascending — never by `id`. The `grams_remaining` figure tracks how much of each lot is still on hand; it is drawn down when an order routes and restored when an order cancels.

Receiving a lot can revive supply. After a new lot is created at a stall, the platform re-evaluates the availability of every menu item whose recipe uses that ingredient at that stall: any such item currently `SOLD_OUT` that now has enough grams on hand for one unit of every one of its recipe components flips back to `AVAILABLE` (see §3.6).

### 3.5. Order Ingestion and the Routing Cascade

The order lifecycle begins when a marketplace pushes an inbound order. An `AggregatorGateway` ingests an order by supplying the `brand_id` the consumer ordered from, the `aggregator` it came from (one of `DOORDASH` or `UBER_EATS`), the marketplace's own `external_ref` order identifier, and a `line_items` array. Each element of `line_items` is an object naming a `menu_item_id` and an integer `qty` of at least 1. Ingestion is idempotent on the marketplace's identity: the combination of `aggregator` and `external_ref` must be unique, and a repeat submission of an already-seen pair is rejected with `ERR_DUPLICATE_ORDER` rather than silently creating a second order.

A newly ingested order is `INGESTED` and immediately snapshots its `gross_revenue_cents`: the sum, over each line item, of the line item's menu item's `price_cents` multiplied by that line item's `qty`. This snapshot is frozen at ingestion — later menu price changes never alter the gross of an already-ingested order. At ingestion the order's `routed_stall_id`, `booking_id`, `commission_cents`, and `food_cost_cents` are all still unset or zero; food cost in particular stays 0 until the order is fulfilled.

From `INGESTED`, the order forks. A `PlatformOps` operator may reject it outright, moving `INGESTED → REJECTED`; rejection reserves no equipment and consumes no inventory, so there is nothing to compensate later, and it simply bumps the order's `version`. Alternatively, `PlatformOps` routes the order, the platform's central transaction, advancing `INGESTED → ROUTED`. Routing demands, in order:

1. The order must be `INGESTED`; otherwise `ERR_INVALID_STATE`.
2. The ordered brand must be both `status` `ACTIVE` and `availability` `LISTED`; a brand that is not both is rejected with `ERR_BRAND_NOT_LISTED`.
3. There must be at least one routing-eligible stall (defined below); if none qualifies, routing fails with `ERR_NO_ELIGIBLE_STALL` and the order is left untouched.
4. Every recipe component of every line item must be fully satisfiable from FIFO inventory at the chosen stall; if any component cannot be covered, routing fails with `ERR_INSUFFICIENT_INVENTORY` and no grams are deducted.

A stall is **routing-eligible** for an order only when all of the following hold: an `ACTIVE` `KitchenLease` exists binding the order's brand to that stall; the stall's `status` is `OPEN`; for every distinct `required_equipment_type` among the order's line items, the stall owns at least one `AVAILABLE` `Equipment` unit of that type that can host the contiguous prep window for that type without violating the overlap and turnaround rules of §2.8; and the stall holds enough FIFO inventory to satisfy every recipe component of every line item. Among the eligible stalls, the platform picks deterministically: the candidate whose binding lease has the lowest `priority_rank` wins, and if two leases tie on rank, the lease created earlier (by `created_at` ascending) wins — never by `id`. The winning stall is recorded as the order's `routed_stall_id`.

Routing is a three-hop cascade. First, for each required equipment type, the platform reserves a single contiguous half-open window on one `AVAILABLE` unit of that type at the chosen stall: the window starts at the current clock minute and runs for the total occupancy of that type, where total occupancy is the sum, over the line items whose menu item's `required_equipment_type` equals that type, of the menu item's `prep_minutes` multiplied by that line item's `qty`. The reserved booking is created `HELD` and the order's `booking_id` is set to it. Second, the platform deducts ingredient inventory FIFO (see §3.6), recording for the order exactly which lot gave up how many grams. Third, any menu item left short by that deduction flips from `AVAILABLE` to `SOLD_OUT`. Routing also computes the order's forward-looking `commission_cents` from the snapshotted gross and the brand's current rate (see §3.7), sets `status` to `ROUTED`, and bumps the order's `version`.

Once routed, the order is handed to the kitchen. The owning `StallOperator` — the operator of the stall named by `routed_stall_id` — starts preparation, advancing `ROUTED → PREPARING` (rejected with `ERR_INVALID_STATE` if the order is not `ROUTED`), and later marks it fulfilled, advancing `PREPARING → FULFILLED` (rejected with `ERR_INVALID_STATE` if the order is not `PREPARING`). Each transition bumps the order's `version`. Fulfillment finalizes the money and frees the equipment, as detailed in §3.7. An order may instead be cancelled from either `ROUTED` or `PREPARING` by `PlatformOps`, as detailed in §3.8.

### 3.6. Inventory Drawdown, Sold-Out Flips, and Restoration

When an order routes, inventory is drawn down recipe component by recipe component. For each recipe component of each line item's menu item, the platform needs that component's `quantity_grams` multiplied by the line item's `qty`. It gathers the candidate lots at the routed stall whose `ingredient_name` matches the component and whose `grams_remaining` is greater than 0, orders them by `received_at` ascending with `created_at` ascending as the tie-break, and draws from each lot in turn: from each lot it takes the smaller of that lot's `grams_remaining` and the grams still outstanding, subtracts that take from the lot's `grams_remaining`, reduces the outstanding need by the same amount, and records a consumption slice — the lot and the grams taken — on the order for later food-cost finalization and possible restoration. It continues to the next lot until the need is fully met. If, for any single component, the total available across all matching lots is less than what that component needs, routing fails entirely with `ERR_INSUFFICIENT_INVENTORY` and no lot is modified.

A menu item's `availability` is a pure function of whether one more unit can be made at a given stall. For a specific stall, an item "can make one unit" when, for every one of its recipe components, the sum of `grams_remaining` across that stall's lots matching the component's `ingredient_name` is at least the component's `quantity_grams`. The boundary is inclusive: a sum exactly equal to `quantity_grams` still counts as makeable and the item stays `AVAILABLE`, whereas one gram short tips it to `SOLD_OUT`. After routing consumes inventory, any item that can no longer make one unit and is currently `AVAILABLE` flips to `SOLD_OUT`; conversely, after inventory is restored — whether by a new lot being received or by an order being cancelled — any item that is currently `SOLD_OUT` and can once again make one unit of every component flips back to `AVAILABLE`. Every such flip bumps the menu item's `version`.

### 3.7. Settlement: Commission, Food Cost, and the Brand Ledger

Money is reconciled in two passes that deliberately diverge. The first pass, **commission**, is forward-looking and is computed at routing time. It is the order's snapshotted `gross_revenue_cents` multiplied by the brand's `commission_rate_bps` as read at the moment of routing, divided by 10000, rounded half up to a whole number of cents — the rounding applied once to that single product. This routing-time figure is authoritative: commission is *not* recomputed at fulfillment, so whatever rate the brand carried when the order routed is the rate that ultimately settles, even if the brand's rate later changes.

The second pass, **food cost**, is chronological and is finalized only when the order moves `PREPARING → FULFILLED`. It is computed not against current inventory but against the exact consumption slices the order recorded at routing: for each recorded slice, the grams taken from that lot are multiplied by *that lot's* `unit_cost_cents_per_gram`, and these products are summed to give `food_cost_cents`. Because the slices reflect the actual FIFO draw at routing, this figure can differ from any "cheapest lot now" estimate — it is the real cost of the specific lots that were drawn. There is no rounding, since grams and per-gram cents are integers.

At fulfillment the platform settles onto the brand ledger. The net payout for the order is its `gross_revenue_cents` minus its `commission_cents` minus its `food_cost_cents`, and that net amount is added to the owning brand's running `ledger_balance_cents`. Fulfillment then releases the equipment booking referenced by the order's `booking_id` (moving it `HELD → RELEASED` and freeing its window) and bumps the order's `version`; the brand and the booking each have their own `version` bumped as part of the cascade. The brand's `ledger_balance_cents` is therefore the cumulative payout credited at every fulfillment, net of the commission and food cost debited at each one. A brand-performance summary read exposes this same balance alongside the brand's fulfilled-order count and gross, commission, and food-cost totals.

### 3.8. Cancellation as Exact Compensation

Cancelling an order is the precise inverse of routing, and it is reachable from either `ROUTED` or `PREPARING`. Only `PlatformOps` may cancel, and the request must carry `expected_order_version` matching the order's current `version`, per the optimistic concurrency rule of §2.6 — a mismatch is rejected with `ERR_STALE_VERSION`. A cancel attempted from any state other than `ROUTED` or `PREPARING` is rejected with `ERR_INVALID_STATE`.

When a cancel proceeds, it reverses exactly what routing committed. Every consumption slice the order recorded is undone: each `IngredientLot` is credited back the exact grams this order took from it, restoring its `grams_remaining`. Any menu item that this order had flipped to `SOLD_OUT` and that now once again has enough grams for one unit of every component flips back from `SOLD_OUT` to `AVAILABLE`. The `EquipmentBooking` referenced by the order's `booking_id` is released, moving `HELD → RELEASED` and freeing its window. The order's `status` becomes `CANCELLED` and its `version` is bumped, along with the versions of every lot, menu item, and booking touched by the compensation.

Critically, cancellation never credits the brand ledger — ledger credit happens only at fulfillment. A cancelled order therefore leaves the brand's `ledger_balance_cents` exactly where it stood before the order ever existed; the compensation restores inventory and frees equipment but moves no money. This is the compensating invariant that distinguishes the cancellation branch from the fulfillment branch sharing the same `PREPARING` origin.

### 3.9. Maintenance Holds and Manual Bookings

Beyond order-driven reservations, a `StallOperator` can place a manual maintenance hold on one of its equipment units by supplying the `equipment_id` and the absolute `start_minute` and `end_minute` of the window to block; such a hold omits any `order_id`, since it serves no order. A maintenance hold is created `HELD` and is subject to the very same overlap and turnaround-buffer rules as any other booking (§2.8): if its window intersects an existing `HELD` booking on the unit, or fails to leave the unit's `turnaround_buffer_minutes` gap on either side, the request is rejected with `ERR_BOOKING_OVERLAP`. An `EquipmentBooking` has two states — `HELD` while it occupies its window and `RELEASED` once freed. Order-driven bookings are released automatically by fulfillment or cancellation; a manual maintenance hold (one whose `order_id` is null) is instead released explicitly by its stall operator, moving it `HELD → RELEASED` and bumping its `version`; releasing a booking that is not `HELD` is rejected with `ERR_INVALID_STATE`. Only bookings with no associated order may be released this way.

### 3.10. Field-Shape Validation and Validation Ordering

Every write endpoint validates the shape of its input as the last line of defense: required fields must be present, enum-typed fields must carry a recognized value, and integer fields must satisfy their declared constraints — for example, a stall's `open_minute_of_day` must be strictly less than its `close_minute_of_day`, each line item's `qty` must be at least 1, a brand's `commission_rate_bps` must fall within 0 to 5000 inclusive, a lease's `monthly_fee_cents` and a menu item's `price_cents` must be strictly positive, a menu item's `prep_minutes` must be at least 1, a recipe component's `quantity_grams` must be strictly positive, an ingredient lot's `grams_received` must be strictly positive and its `unit_cost_cents_per_gram` at least 0, and an equipment unit's `turnaround_buffer_minutes` must be at least 0. Any such violation is rejected with `ERR_INVALID_REQUEST`.

When several checks could fire on one request, they are evaluated in a fixed precedence so that the most fundamental failure surfaces first. Authentication comes first: missing headers or an unknown role yield `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the endpoint, or an ownership-scoped role acting on a resource it does not own, yields `ERR_FORBIDDEN`. Existence is third: unresolved path identifiers or body foreign keys yield `ERR_NOT_FOUND`, with path identifiers checked before body references. Ingestion idempotency is fourth, applying to order ingestion: a duplicate `aggregator`/`external_ref` pair yields `ERR_DUPLICATE_ORDER`. State validity is fifth: a transition not defined from the resource's current state yields `ERR_INVALID_STATE`. Then come the business rules in their own order — lease priority-rank uniqueness (`ERR_DUPLICATE_PRIORITY_RANK`) on lease activation and reinstatement; brand-listed-ness (`ERR_BRAND_NOT_LISTED`) on routing; eligible-stall existence (`ERR_NO_ELIGIBLE_STALL`) on routing; booking overlap (`ERR_BOOKING_OVERLAP`) on manual maintenance-hold creation; and sufficient inventory (`ERR_INSUFFICIENT_INVENTORY`) on routing. The optimistic-concurrency stale-version check (`ERR_STALE_VERSION`) on cancellation follows. Field-shape validity (`ERR_INVALID_REQUEST`) is evaluated last among these. In short: authentication, then authorization, then existence, then ingestion idempotency, then state, then the business constraints (priority-rank, brand-listed, eligible-stall, booking-overlap, inventory), then the stale-version check, then field shape.

## 4. Endpoint Definitions

Endpoints that create a new, standalone resource return `201 Created`; endpoints that modify an existing resource — including all state transitions and the clock control — return `200 OK`. The request body, response body, and side effects of each endpoint are described in the §3 workflows above; the table below is only a routing and authorization summary. Note that `POST /stalls` and `POST /brands` still require an authenticated `PlatformOps` caller despite creating ownerless resources.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/stalls` | Register a physical kitchen stall | PlatformOps |
| GET | `/stalls/{id}` | Fetch one stall | PlatformOps, StallOperator, BrandOwner |
| GET | `/stalls` | List stalls | PlatformOps, StallOperator, BrandOwner |
| POST | `/stalls/{id}/open` | Manually reopen a stall | StallOperator |
| POST | `/stalls/{id}/close` | Manually close a stall | StallOperator |
| GET | `/stalls/{id}/equipment` | List equipment at a stall | PlatformOps, StallOperator |
| GET | `/stalls/{id}/ingredient-lots` | List ingredient lots at a stall | PlatformOps, StallOperator |
| POST | `/brands` | Register a virtual brand | PlatformOps |
| GET | `/brands/{id}` | Fetch one brand | PlatformOps, BrandOwner, StallOperator |
| GET | `/brands` | List brands | PlatformOps, BrandOwner, StallOperator |
| POST | `/brands/{id}/list` | Set availability LISTED | BrandOwner |
| POST | `/brands/{id}/pause` | Set availability PAUSED | BrandOwner |
| POST | `/brands/{id}/deactivate` | Deactivate a brand (cascades lease termination) | BrandOwner |
| GET | `/brands/{id}/menu-items` | List a brand's menu items | PlatformOps, BrandOwner, StallOperator |
| GET | `/brands/{id}/performance` | Brand performance summary | PlatformOps, BrandOwner |
| POST | `/leases` | Create a kitchen lease | PlatformOps |
| GET | `/leases/{id}` | Fetch one lease | PlatformOps, StallOperator, BrandOwner |
| GET | `/leases` | List leases (filter by `stall_id`, `brand_id`) | PlatformOps, StallOperator, BrandOwner |
| POST | `/leases/{id}/activate` | Activate a lease (may cascade brand active) | StallOperator |
| POST | `/leases/{id}/suspend` | Suspend a lease | PlatformOps |
| POST | `/leases/{id}/reinstate` | Reinstate a suspended lease | PlatformOps |
| POST | `/leases/{id}/terminate` | Terminate a lease | StallOperator |
| POST | `/equipment` | Add an equipment unit to a stall | StallOperator |
| GET | `/equipment/{id}` | Fetch one equipment unit | PlatformOps, StallOperator |
| POST | `/equipment/{id}/maintenance` | Take equipment into maintenance | StallOperator |
| POST | `/equipment/{id}/restore` | Restore equipment to available | StallOperator |
| POST | `/equipment/{id}/retire` | Retire equipment | StallOperator |
| GET | `/equipment/{id}/bookings` | List bookings on a unit | PlatformOps, StallOperator |
| POST | `/equipment-bookings` | Create a manual maintenance hold | StallOperator |
| GET | `/equipment-bookings/{id}` | Fetch one booking | PlatformOps, StallOperator |
| GET | `/equipment-bookings` | List bookings (filter by `order_id`) | PlatformOps, StallOperator |
| POST | `/equipment-bookings/{id}/release` | Release a maintenance hold | StallOperator |
| POST | `/menu-items` | Create a menu item under a brand | BrandOwner |
| GET | `/menu-items/{id}` | Fetch one menu item | PlatformOps, BrandOwner, StallOperator |
| POST | `/menu-items/{id}/recipe-components` | Add a recipe line to a menu item | BrandOwner |
| GET | `/menu-items/{id}/recipe-components` | List a menu item's recipe lines | PlatformOps, BrandOwner, StallOperator |
| POST | `/ingredient-lots` | Receive a commissary ingredient lot | StallOperator |
| GET | `/ingredient-lots/{id}` | Fetch one ingredient lot | PlatformOps, StallOperator |
| POST | `/orders` | Ingest an inbound aggregator order | AggregatorGateway |
| GET | `/orders/{id}` | Fetch one order | PlatformOps, BrandOwner, StallOperator, AggregatorGateway |
| GET | `/orders` | List orders (filter by `brand_id`, `routed_stall_id`, `booking_id`, `status`) | PlatformOps, BrandOwner, StallOperator |
| POST | `/orders/{id}/route` | Route an ingested order to a stall | PlatformOps |
| POST | `/orders/{id}/reject` | Reject an ingested order | PlatformOps |
| POST | `/orders/{id}/start-prep` | Begin preparation | StallOperator |
| POST | `/orders/{id}/fulfill` | Fulfill an order (settles ledger) | StallOperator |
| POST | `/orders/{id}/cancel` | Cancel a routed/preparing order (OCC-guarded) | PlatformOps |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_ORDER` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DUPLICATE_PRIORITY_RANK` | 409 |
| `ERR_BRAND_NOT_LISTED` | 409 |
| `ERR_NO_ELIGIBLE_STALL` | 409 |
| `ERR_BOOKING_OVERLAP` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
