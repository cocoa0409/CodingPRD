# Wholesale Bakery DSD API — Product Requirements Document

## 1. Introduction

A wholesale bread plant running direct-store-delivery (DSD) lives under a set of unforgiving clocks. Dough must move from mixer to oven inside a narrow proof window or the batch is lost. Bread begins staling the moment it leaves the oven, and every store imposes its own freshness floor at the shelf. Order cutoffs precede an early-morning delivery instant, flour and butter cost indices publish monthly against prices set weeks earlier, and every stale loaf picked up on a route is a credit negotiation waiting to happen. This document specifies the Wholesale Bakery DSD API: the system of record for a single-plant bakery operation, spanning store order capture, production planning, line scheduling under allergen segregation, sanitation changeovers, route loading and delivery, settlement and shrink accountability, stale-return credit, thrift-outlet recovery, and ingredient cost pass-through.

The design rests on two pillars. The first is segregation of duties: the operator who bakes a batch may not release it, the operator who starts a sanitation cycle may not verify it, and the driver who records a stale pickup may not verify the resulting credit. The second is ledger discipline: store credit balances, driver shrink liability, lifetime delivery and stale counters, and product surcharges are all derived, auditable amounts that the workflows in Section 3 must reconstruct exactly. All resources are mounted under the `/bakery` path prefix, with one additional administrative endpoint for the logical clock, and every temporal rule in the system evaluates against that server-maintained logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request that omits either header, or names a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes eight roles: `PlantAdmin`, `Planner`, `LineOperator`, `QALead`, `Driver`, `StoreReceiver`, `ThriftClerk`, and `PricingAnalyst`. The pseudo-role `Any` used in Section 4 denotes shared read access: every declared role may call every GET endpoint. A request whose role is not authorized for the target endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Role identity binds to resources in two distinct ways. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting Driver entity; ownership checks on any resource that references a driver compare the resource's `driver_id` field to `X-User-ID`. When `X-User-Role` is `StoreReceiver`, `X-User-ID` is the `id` of the acting Store entity; ownership checks compare the order's or return's `store_id` field to `X-User-ID`. When `X-User-Role` is `PlantAdmin`, `Planner`, `LineOperator`, `QALead`, `ThriftClerk`, or `PricingAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `completed_by_user_id` on a batch, `started_by_user_id` on a sanitation cycle, or `recorded_by_driver_id` on a stale return) and may compare two recorded identifiers against each other for segregation-of-duties purposes, but it never compares an opaque identifier to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and the Ops-Run Day

Every temporal rule in this document — order cutoffs, proof windows, freshness windows, return windows, sanitation dwell times — evaluates against a server-maintained logical clock, never against wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock. A `PlantAdmin` may set the clock by supplying a `to_iso8601` timestamp to the clock endpoint; the response reports the new value as `current_utc`. All clock comparisons in the system are made at second precision.

Each plant carries an ops-run day counter, `day_index`, which starts at 0 when the plant is created. The close-of-day checkpoint is a `PlantAdmin`-only capability that advances the plant's day: it increments `day_index` by 1, increments the plant's `version` by 1, and runs three automated sweeps in the same operation — every batch still in `PROOFING` whose proof has run longer than 120 minutes transitions to `OVERPROOFED`; every `ACTIVE` store whose stale ratio is strictly greater than 0.15 is suspended; and every `CONFIRMED` order whose cutoff has passed is locked by the system (the cutoff rule itself is defined in §3.2).

### 2.5. Common Resource Properties

Every resource in the system carries a uniform set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by 1 on every mutation of the resource, including mutations caused by cascades originating on other resources.

No entity in this system is exempt: plants, products, stores, drivers, lines, orders, plans, batches, sanitation cycles, routes, stops, stale returns, thrift sales, ingredient indices, and surcharge schedules all carry the full set. Any cascade that changes a resource — a version bump on a superseded plan, a balance change on a store, a surcharge update on a product — also refreshes that resource's `updated_at`.

### 2.6. Cascading State Changes and Cross-Entity Consistency

Many operations in this API mutate more than one resource, and all such cascades apply immediately, within the same request. The principal cascades, each specified fully in Section 3, are: rejecting a batch, which adds its quantity to the plan's shortfall, flags every pending stop that referenced the batch, and transitions the affected orders; reconciling a delivered stop, which fulfills or partially fulfills the underlying order; publishing an ingredient index, which finalizes provisional surcharge schedules and rewrites product surcharges; creating a production plan, which supersedes any existing draft for the same plant and bake date; settling a route, which accrues liability onto the driver and delivered volume onto each store; completing a bake, which rewrites the line's residue class and cleanliness; and the close-of-day sweeps described in §2.4. Resources in a terminal state are locked down: any action that names a terminal resource as its target is rejected with `ERR_INVALID_STATE` (HTTP 409) rather than partially applied.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names its guard field explicitly:

- Requesting an amendment to a store order requires the request body to carry `expected_store_order_version`, equal to the order's current `version` as last observed by the client. If the order's `version` has advanced since that observation — for example because a prior amendment was accepted or rejected — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a production plan requires the request body to carry `expected_plant_version`, equal to the plant's current `version`. Because creating a plan supersedes any existing draft for the same plant and bake date, a client whose view of the plant is stale would supersede blindly; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Scheduling a batch requires the request body to carry `expected_production_plan_version`, equal to the production plan's current `version`. Scheduling mutates the plan's line occupation and advances its `version`, so a client scheduling against a previously read version is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not accept a version field; supplying one has no effect and is not part of their contract.

### 2.8. Money, Units, and Rounding Discipline

All monetary amounts in the API are integer cents — prices, credits, liabilities, and surcharges alike. Where a credit or surcharge computation produces a fractional cent, the result is rounded half-up to a whole cent. Two rounding orders are pinned and must not be interchanged: stale-return credit rounds each line to whole cents first and then sums the lines, while the production requirement's flour figure is summed in grams-equivalent first and rounded once at the end. Planned unit counts and batch counts are whole units obtained by rounding up (ceiling). The flour requirement is expressed in kilograms with exactly one decimal place, rounded half-up. A store's stale ratio is compared as an exact rational number with no rounding at all. Clock comparisons are made at second precision, as noted in §2.4.

### 2.9. Validation Order of Evaluation

When several checks could reject the same request, the server evaluates them in the following fixed order, and the first failing check determines the response:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared; failure yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This check applies to every request.
2. **Role authorization and ownership** — the role is permitted for the endpoint, and entity-backed ownership holds (a driver's `X-User-ID` equals the route's `driver_id`; a store receiver's `X-User-ID` equals the order's or return's `store_id`); failure yields `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. **Existence** — every identifier named in the path and body (plant, product, store, driver, line, order, plan, batch, cycle, route, stop, return, sale, index, schedule) exists; failure yields `ERR_NOT_FOUND` (HTTP 404).
4. **Request shape** — required fields are present, enums are valid, quantities, prices, and capacities are positive, datetimes parse, and `batch_ids` is non-empty where required; failure yields `ERR_INVALID_REQUEST` (HTTP 400).
5. **Optimistic concurrency** — on the three endpoints that declare an `expected_<parent>_version` field (§2.7), the supplied version equals the parent's current `version`; failure yields `ERR_STALE_VERSION` (HTTP 412).
6. **State preconditions** — the target resource is in a valid from-state for the requested transition, including: the plan is released before a batch may start mixing, the pickup stop is delivered before a stale return enters the credit chain, and batches are released before delivery; failure yields `ERR_INVALID_STATE` (HTTP 409).
7. **Safety and duty checks** — allergen segregation, pending sanitation, and segregation of duties; failure yields `ERR_ALLERGEN_SEGREGATION_VIOLATION`, `ERR_SANITATION_REQUIRED` (both HTTP 409), or `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
8. **Temporal windows** — order cutoff, proof window, freshness window, the 72-hour return window, line schedule overlap, the driver rest buffer, and sanitation dwell time; failure yields the corresponding temporal error (`ERR_ORDER_CUTOFF_PASSED`, `ERR_PROOF_WINDOW_VIOLATION`, `ERR_FRESHNESS_WINDOW_VIOLATION`, `ERR_RETURN_WINDOW_CLOSED`, `ERR_LINE_SCHEDULE_OVERLAP`, `ERR_DRIVER_WINDOW_OVERLAP`, or `ERR_SANITATION_NOT_COMPLETE`; HTTP 409).
9. **Referenced-entity state and uniqueness** — the store is active, stop quantities match order totals, no live plan already exists for the plant and bake date, stops are locked before loading, and required indices exist for a schedule; failure yields `ERR_STORE_SUSPENDED`, `ERR_PLANNED_QTY_MISMATCH`, `ERR_DUPLICATE_PLAN_DATE`, `ERR_STOPS_NOT_LOCKED`, `ERR_INDEX_NOT_PUBLISHED`, `ERR_LINE_NOT_AVAILABLE`, or `ERR_THRIFT_STOCK_UNAVAILABLE` (HTTP 409).
10. **Caps and floors** — the stale credit cap, the thrift price floor, truck capacity, the shrink hard limit, and batch quantity within product batch capacity; failure yields `ERR_STALE_CREDIT_CAP_EXCEEDED`, `ERR_THRIFT_PRICE_BELOW_FLOOR`, `ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_SHRINK_LIMIT_EXCEEDED` (HTTP 409), or `ERR_INVALID_REQUEST` (HTTP 400) where the failure is a malformed quantity.

### 2.10. Segregation of Duties on Controlled Steps

Three controlled steps in the plant require two different people. The operator who completes a bake may not QA-release that batch: the releasing `QALead`'s `X-User-ID` must differ from the batch's recorded `completed_by_user_id`. The operator who starts a sanitation cycle may not verify it: the verifying `QALead`'s `X-User-ID` must differ from the cycle's recorded `started_by_user_id`. The driver who records a stale return may not verify it: the verifying `QALead`'s `X-User-ID` must differ from the return's recorded `recorded_by_driver_id`. Any violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Plant Master Data: Products, Stores, Drivers, and Lines

Before any workflow can run, a `PlantAdmin` registers the plant's master data. Creating a plant requires a `name` plus the two cost-pass-through baselines, `baseline_flour_index` and `baseline_butter_index`, which anchor all later surcharge deltas; the new plant's `day_index` starts at 0.

A product is registered against its owning `plant_id` with a `sku` that must be unique within that plant, a display `name`, and an `allergen_class` of `NONE`, `SESAME`, `TREE_NUT`, or `PEANUT` that drives segregation on the lines. Its physical and commercial parameters are `unit_weight_g` (baked weight in grams, greater than zero), `shelf_life_hours` (the length of the staling clock, greater than zero), `base_price_cents` (wholesale unit price before surcharge, greater than zero), `flour_share_pct` and `butter_share_pct` (the fractions of unit cost exposed to each ingredient index, each between 0 and 1 inclusive), and `batch_capacity_units` (the maximum units of this product in any single batch on any line, greater than zero). A product's `current_surcharge_cents` starts at 0 and is thereafter maintained only by the pass-through machinery of §3.9.

A store is registered with its `plant_id`, a `name`, an order `lead_time_hours` (greater than zero), a `min_remaining_life_hours_on_delivery` freshness floor (zero or more), a `shelf_capacity_units` (greater than zero), and an optional `stale_credit_tier` of `STANDARD` or `LIMITED` that defaults to `STANDARD`; the `LIMITED` tier caps the stale credit rate at 0.50 regardless of loaf age (§3.8). A new store's `status` is `ACTIVE` and its `credit_balance_cents` is 0. Three system-maintained counters track the store's standing: `lifetime_delivered_units` and `lifetime_stale_units` both start at 0, and `stale_ratio` is the ratio of `lifetime_stale_units` to `lifetime_delivered_units`, with the denominator treated as at least 1 so a store with no deliveries has ratio 0. A `PlantAdmin` may suspend a store — the request records a free-text `reason` — moving it from `ACTIVE` to `SUSPENDED` and incrementing the store's `version`; reinstatement returns a `SUSPENDED` store to `ACTIVE` and likewise increments `version`. Suspension also happens automatically at close-of-day when the stale ratio breaches its threshold (§2.4).

A driver is registered with `plant_id`, a `name`, and an optional `max_daily_drive_minutes` daily driving cap that defaults to 600 — ten hours. A new driver's `status` is `ACTIVE` (the enum also admits `INACTIVE`) and its `shrink_liability_cents` accumulator starts at 0. A production line is registered with `plant_id`, a `line_code` unique within the plant, and a nominal `hourly_capacity_units` throughput greater than zero; a new line's `cleanliness` is `CLEAN` and its `allergen_class_current` residue class is `NONE`.

### 3.2. The Store Order Lifecycle: Placement, Cutoff, and Amendment

A `Planner` — or a `PlantAdmin` acting in that capacity — places a store order by supplying the `store_id`, a `delivery_date` in `YYYY-MM-DD` form, and the order `lines`, each naming a `product_id` and a `qty` greater than zero; every product on the lines must belong to the same plant as the store. The store must be `ACTIVE`, or placement is rejected with `ERR_STORE_SUSPENDED`. At creation the order's `plant_id` is copied from the store, its `status` is `PLACED`, `placed_at` records the logical clock, and `total_units` is computed as the sum of `qty` across the lines. `pending_lines` is empty until an amendment is requested.

Every order lives against a delivery instant fixed at exactly 08:00:00 UTC on its `delivery_date`. The order cutoff is that instant minus the store's `lead_time_hours`, and a cutoff check passes when the logical clock is at or before the cutoff — equality is allowed. Confirming an order (a `Planner` action) moves it from `PLACED` to `CONFIRMED`, stamps `confirmed_at` with the clock, and enforces two checks: the store must still be `ACTIVE` (else `ERR_STORE_SUSPENDED`), and the clock must be at or before the cutoff (else `ERR_ORDER_CUTOFF_PASSED`).

Once an order is `CONFIRMED`, the store itself may ask for changes. A `StoreReceiver` requests an amendment by supplying replacement `lines` together with `expected_store_order_version`; the caller's `X-User-ID` must equal the order's `store_id` (else `ERR_FORBIDDEN_FOR_ROLE`), the OCC rule of §2.7 applies (else `ERR_STALE_VERSION`), and the cutoff must not have passed (else `ERR_ORDER_CUTOFF_PASSED`). A successful request moves the order to `AMENDMENT_PENDING` with the requested lines parked in `pending_lines`. The planner then decides: accepting the amendment moves the order back to `CONFIRMED` with `lines` replaced by `pending_lines`, `pending_lines` cleared to null, and `total_units` recomputed from the new lines; rejecting it also returns the order to `CONFIRMED` but leaves `lines` untouched and simply clears `pending_lines` to null. Both decisions increment the order's `version`.

Locking finalizes an order for production. A `Planner` may lock a `CONFIRMED` order manually while the clock is still at or before the cutoff; past the cutoff the manual lock is rejected with `ERR_ORDER_CUTOFF_PASSED`. Once the cutoff has passed, the close-of-day sweep locks any still-`CONFIRMED` order automatically. Either way the order moves from `CONFIRMED` to `LOCKED` and its `version` increments. A planner may also cancel an order, but only from `PLACED` or `CONFIRMED`; cancellation moves it to the terminal `CANCELLED` state.

Three of the order's terminal and near-terminal states are never reached by direct request. `SHORTED` arrives only through the batch-rejection cascade of §3.4, and `FULFILLED` and `PARTIALLY_FULFILLED` arrive only through the stop-reconciliation cascade of §3.6. The full status vocabulary is `PLACED`, `CONFIRMED`, `AMENDMENT_PENDING`, `LOCKED`, `SHORTED`, `FULFILLED`, `PARTIALLY_FULFILLED`, and `CANCELLED`, with the last three being terminal. List and detail reads may filter by `store_id`, `plant_id`, or `status`.

### 3.3. Production Planning and Requirement Computation

A `Planner` opens a production plan by naming the `plant_id`, the `bake_date` it bakes for (in `YYYY-MM-DD` form), and `expected_plant_version` per the OCC rule of §2.7. Two guards apply. If a plan in any state other than `DRAFT` already exists for the same plant and bake date, creation is rejected with `ERR_DUPLICATE_PLAN_DATE`. If a `DRAFT` plan exists for that combination, the new plan is created normally and the old draft is superseded — its status moves from `DRAFT` to `SUPERSEDED` and its `version` increments. Creating a plan also increments the plant's `version` by 1, which is precisely why the OCC guard exists. A new plan starts in `DRAFT` with `total_planned_units`, `flour_required_kg`, and `shortfall_units` all at 0.

Locking a plan — moving it from `DRAFT` to `LOCKED` — runs the requirement computation, and its evaluation order is pinned. First, gross units per product are summed over the lines of every `LOCKED` store order for the plan's plant whose `delivery_date` equals the plan's `bake_date`. Second, a buffer percentage is selected for each product keyed on its gross units — never on the later planned figure: below 1,000 gross units the buffer is 10%; from 1,000 up to but not including 5,000 the buffer is 7%; at 5,000 or more the buffer is 5%. Third, planned units per product are the gross units multiplied by one plus the buffer, rounded up to a whole unit, and stored in `planned_units_by_product`. Fourth, `batches_required_by_product` divides each product's planned units by the product's `batch_capacity_units`, again rounding up. Fifth, `flour_required_kg` sums, across products, the product of batches required, `batch_capacity_units`, and `unit_weight_g`, multiplied by the standard 60% flour fraction of dough weight, then divides by 1,000 to convert grams to kilograms and rounds half-up to exactly one decimal place. Finally, `total_planned_units` sums the planned units across products.

Unlocking returns a `LOCKED` plan to `DRAFT`, but only if no batch of the plan has left `SCHEDULED`; if any batch has already started down the line the unlock is rejected with `ERR_PLAN_NOT_RELEASABLE`. A successful unlock clears the computed requirement fields back to empty maps and zeros, increments the plan's `version`, and records the planner's free-text `reason`. Releasing a plan to the floor requires at least one batch in `SCHEDULED` (else `ERR_PLAN_NOT_RELEASABLE`) and requires that no sanitation cycle on any line used by the plan is still `REQUESTED` or `IN_PROGRESS` (else `ERR_SANITATION_REQUIRED`); release moves the plan from `LOCKED` to `RELEASED`. Once every batch of a released plan has reached `RELEASED`, `REJECTED`, or `ABORTED`, the planner reconciles the plan, moving it from `RELEASED` to the terminal `RECONCILED` state; if any batch is still mid-flight the reconcile is rejected with `ERR_INVALID_STATE`. After release, any rejected batch adds its quantity to the plan's `shortfall_units` accumulator (§3.4).

### 3.4. Batch Scheduling and Line Execution

A `Planner` schedules a batch by supplying the `production_plan_id`, the `line_id`, the `product_id`, the `qty_units` to run, the `scheduled_start_at` and `scheduled_end_at` occupation window, and `expected_production_plan_version` per §2.7. The plan must be `LOCKED` or `RELEASED` (otherwise `ERR_INVALID_STATE`). The quantity must be at least 1 and no more than the product's `batch_capacity_units` (otherwise `ERR_INVALID_REQUEST`). The occupation window is a half-open interval — it occupies the line from `scheduled_start_at` up to but not including `scheduled_end_at`, and the end must be after the start; if the interval collides with another scheduled or in-flight batch on the same line, creation is rejected with `ERR_LINE_SCHEDULE_OVERLAP`. A line currently `SANITIZING` rejects scheduling with `ERR_LINE_NOT_AVAILABLE`, and a batch whose allergen class differs from a `DIRTY` line's current residue class — with no verified changeover in between — is rejected with `ERR_ALLERGEN_SEGREGATION_VIOLATION`. A newly created batch starts in `SCHEDULED`, and its creation increments the parent plan's `version` by 1.

Line operators then walk each batch through the floor. Starting the mix is allowed only when the batch's plan is `RELEASED` (else `ERR_INVALID_STATE`); it moves the batch from `SCHEDULED` to `MIXING` and stamps `mix_started_at` with the clock. Starting the proof moves `MIXING` to `PROOFING` and stamps `proof_started_at`. Starting the bake is gated on the proof window: at least 60 minutes and at most 120 minutes must have elapsed since `proof_started_at` — both bounds inclusive — or the transition is rejected with `ERR_PROOF_WINDOW_VIOLATION`. (Independently, the close-of-day sweep forces any batch still `PROOFING` more than 120 minutes past its proof start into `OVERPROOFED`; see §2.4.) Completing the bake moves `BAKING` to `COOLING`, stamps `bake_completed_at` with the clock — this instant is the origin of the loaf's staling clock — and records the operator in `completed_by_user_id`. From `bake_completed_at` the system derives `fresh_until`, exactly the product's `shelf_life_hours` later; until it is baked a batch has no `fresh_until`. Completing a bake also rewrites the line: the line's `allergen_class_current` becomes the product's `allergen_class`, and if that class is anything other than `NONE` the line's `cleanliness` becomes `DIRTY` with the line's `version` incrementing.

QA disposition splits two ways. A `QALead` releases a `COOLING` batch to `RELEASED`, subject to the segregation-of-duties rule of §2.10 — the releaser must not be the operator recorded in `completed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. A `QALead` may instead reject a batch — the request carries a free-text `reason` — from any of `MIXING`, `PROOFING`, `BAKING`, `COOLING`, or `OVERPROOFED`, and may even recall a batch that is already `RELEASED`; all six rejections land in the terminal `REJECTED` state and fire the same three-hop cascade. Hop one adds the batch's `qty_units` to the plan's `shortfall_units` and increments the plan's `version`. Hop two sets `shortfall_flag` to true on every `PENDING` route stop whose `batch_ids` contain this batch. Hop three moves the store order behind each flagged stop from `LOCKED` to `SHORTED`, incrementing each such order's `version`. A planner may also abort a batch, but only while it is still `SCHEDULED`; aborting lands in the terminal `ABORTED` state with no cascade.

### 3.5. Allergen Segregation and Sanitation Changeovers

Allergen control is enforced through the line's residue class and a changeover matrix. A `LineOperator` requests a sanitation cycle by naming the `line_id` and the target `to_allergen_class` (one of `NONE`, `SESAME`, `TREE_NUT`, `PEANUT`); the system captures the line's current residue class into `from_allergen_class` at request time and computes `required_minutes` from the changeover matrix: a change to the same class requires 0 minutes, changing from `NONE` to any allergen requires 30 minutes, changing from any allergen back to `NONE` requires 120 minutes, and changing from one allergen to a different allergen requires 90 minutes. The new cycle starts in `REQUESTED`.

Starting a cycle — a `LineOperator` action — moves it from `REQUESTED` to `IN_PROGRESS`, stamps `started_at` and `started_by_user_id` from the clock and header, and flips the line's `cleanliness` to `SANITIZING`, which in turn blocks new batch scheduling against it (§3.4). Verification belongs to a `QALead` and enforces both the dwell time and §2.10: at least `required_minutes` must have elapsed since `started_at` (else `ERR_SANITATION_NOT_COMPLETE`), and the verifier's `X-User-ID` must differ from `started_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`). A passing verification moves the cycle to the terminal `VERIFIED` state, stamps `verified_at`, returns the line to `CLEAN`, and sets the line's `allergen_class_current` to the cycle's `to_allergen_class`. A failing verification moves the cycle from `IN_PROGRESS` to `FAILED` and drops the line back to `DIRTY` with its residue class unchanged. A failed cycle is not terminal: starting it again loops it from `FAILED` back to `IN_PROGRESS`, resetting `started_at` and `started_by_user_id` and putting the line into `SANITIZING` once more.

The two enforcement points that consume this machinery live elsewhere in the narrative: a plan cannot release while any line it uses has a cycle `REQUESTED` or `IN_PROGRESS` (§3.3), and a batch cannot be scheduled against a `DIRTY` line whose residue class differs from the product's allergen class unless a `VERIFIED` changeover has intervened (§3.4). Completing a bake with an allergen class other than `NONE` is what makes a line `DIRTY` in the first place (§3.4).

### 3.6. Route Composition, Loading, and Delivery

A `Planner` composes a route by supplying the `plant_id`, the `driver_id`, the `route_date`, the driver's `window_start_at` and `window_end_at` (the end must be after the start), and the `truck_capacity_units` (greater than zero). A driver may not be double-booked against the rest buffer: if the same driver already has a route whose window falls within 30 minutes of the requested window, creation is rejected with `ERR_DRIVER_WINDOW_OVERLAP`; the buffer is strict — a separation of exactly 30 minutes between the windows is allowed, and only separations of less than 30 minutes (including overlapping windows) are rejected. New routes start in `PLANNED` with the accumulators `loaded_units`, `delivered_units`, `refused_units`, and `returned_stale_units` all at 0; `shrink_units` and `shrink_liability_cents` carry no value until settlement computes them (§3.7). Reads may filter by `plant_id`, `driver_id`, or `route_date`.

Stops are added while the route is still `PLANNED`. Adding a stop requires the `route_id`, the `store_order_id`, the `planned_units`, and the `batch_ids` that will cover the order. The referenced order must be `CONFIRMED`, `LOCKED`, or `SHORTED` (otherwise `ERR_INVALID_STATE`); `planned_units` must equal the order's `total_units` exactly (otherwise `ERR_PLANNED_QTY_MISMATCH`); and every batch named in `batch_ids` must be `RELEASED`, collectively covering every product on the order's lines (otherwise `ERR_INVALID_REQUEST`). The stop's `store_id` is copied from the order, its status starts `PENDING`, and `shortfall_flag` starts false.

Loading is the driver's job, and only the assigned driver — the request's `X-User-ID` must equal the route's `driver_id`, else `ERR_FORBIDDEN_FOR_ROLE`. Starting loading requires at least one stop on the route (else `ERR_INVALID_STATE`) and requires every stop's order to be `LOCKED` or `SHORTED` (else `ERR_STOPS_NOT_LOCKED`); it moves the route from `PLANNED` to `LOADING` and freezes `loaded_units` as the sum of the stops' `planned_units`. Dispatching moves `LOADING` to `DISPATCHED` and enforces the truck: `loaded_units` must not exceed `truck_capacity_units`, else `ERR_ROUTE_CAPACITY_EXCEEDED`.

At each stop the driver either delivers or skips. Skipping requires only that the route is `DISPATCHED` and records a free-text `reason`, moving the stop from `PENDING` to `SKIPPED`. Delivering requires the route to be `DISPATCHED`, the caller to be the route's driver, and every batch in `batch_ids` to still be `RELEASED` (violations are `ERR_INVALID_STATE`, `ERR_FORBIDDEN_FOR_ROLE`, and `ERR_INVALID_STATE` respectively). Two numeric gates apply. The declared `delivered_units` may not exceed the stop's `planned_units` (else `ERR_INVALID_REQUEST`). And the freshness window must hold: the delivery clock must be no later than the earliest `fresh_until` across the stop's `batch_ids` minus the store's `min_remaining_life_hours_on_delivery` — equality is allowed — otherwise the delivery is rejected with `ERR_FRESHNESS_WINDOW_VIOLATION`. A successful delivery also records the driver's `on_shelf_units_observed` count and runs the shelf-stocking allocation: `stocked_units` is the smaller of `delivered_units` and the room left on the shelf (the store's `shelf_capacity_units` minus `on_shelf_units_observed`, floored at zero), and `refused_units` is the remainder of `delivered_units` that did not fit. Refused units are recorded at zero credit — they become immediate shrink against the route and no stale return is created for them. The route accumulates both figures: `delivered_units` grows by the stop's delivered amount and `refused_units` by the refused amount, while the stop moves from `PENDING` to `DELIVERED`.

Reconciliation belongs to the planner. Reconciling a `DELIVERED` stop moves it to `RECONCILED` and cascades to the order: if the stop's `delivered_units` equal the order's `total_units`, a `LOCKED` order becomes `FULFILLED`; otherwise a `LOCKED` or `SHORTED` order becomes `PARTIALLY_FULFILLED`. Both order transitions increment the order's `version`.

Completing the route requires every stop to be in `DELIVERED`, `SKIPPED`, or `RECONCILED` (else `ERR_INVALID_STATE`) and moves the route from `DISPATCHED` to `COMPLETED`. A planner may cancel a route only while it is `PLANNED` and has no stops at all (else `ERR_INVALID_STATE`), moving it to the terminal `CANCELLED` state.

### 3.7. Settlement, Shrink, and Driver Liability

Settlement closes the financial loop on a `COMPLETED` route and is a `Planner` action. The settlement walks the route's stops in stop creation order — a tie-break only, since the sums are order-independent — and accumulates three figures: delivered volume, summed over stops in `DELIVERED` or `RECONCILED`; refused volume, summed across stops; and returned stale volume, summed from the declared lines of stale returns recorded on this route's stops that are not in `REJECTED`. The returned stale figure is old stock picked up at the store: it feeds the route's informational `returned_stale_units` counter and the store's stale ratio, but it is not part of the route's fresh-load accounting. Refused units are a subset of delivered units that bounced back to the plant, so they are not subtracted a second time.

Shrink is then `shrink_units` equals `loaded_units` minus the delivered total, and the shrink ratio divides that by `loaded_units` with the denominator treated as at least 1. If the ratio exceeds 0.10 the settle is rejected with `ERR_SHRINK_LIMIT_EXCEEDED` — unless the planner deliberately passes `override_shrink_limit` set to true. Driver liability engages only when the ratio exceeds the 2% tolerance: liability units are then `shrink_units` minus the tolerated allowance of `loaded_units` multiplied by 0.02 and rounded up to a whole unit, floored at zero; at or below the 2% ratio the liability is zero regardless of the raw shrink. The route's `shrink_liability_cents` is the liability units multiplied by a penalty of 150 cents per unit, and settlement adds that amount onto the driver's cumulative `shrink_liability_cents`. Settlement also adds each stop's `delivered_units` onto the corresponding store's `lifetime_delivered_units`. With those postings complete the route moves from `COMPLETED` to the terminal `SETTLED` state.

### 3.8. Stale Returns, Store Credit, and the Thrift Outlet

When a driver picks up stale bread at a stop, they record a stale return naming the `store_id`, the `route_stop_id` of the pickup event, and the `lines` — each a `batch_id` and a `qty` greater than zero. The referenced stop must be in the `DELIVERED` state, or the create is rejected with `ERR_INVALID_STATE`. The return window is 72 hours: a pickup recorded more than 72 hours after a line's `bake_completed_at` is rejected with `ERR_RETURN_WINDOW_CLOSED`. At creation the return enters `PENDING_VERIFICATION`, the recording driver is captured in `recorded_by_driver_id` from the header, `dispute_round` starts at 0, and a provisional credit is computed into `provisional_credit_cents`; the pickup also accrues into the route's `returned_stale_units`.

The credit formula runs in two variants that share one rate table. A line's age in hours is the whole number of hours between the pickup clock and the batch's `bake_completed_at`, any partial hour discarded. At 24 hours or less the line credits at the full rate of 1.00; from 25 through 48 hours the rate is 0.50; beyond 48 hours the rate is 0.00. For a store on the `LIMITED` `stale_credit_tier`, the applicable rate is capped at 0.50 whatever the age-based rate would be. The rounding order is pinned: each line's credit is its `qty` multiplied by the product's `base_price_cents` and the applicable rate, rounded half-up to whole cents, and the return's credit is the sum of those per-line amounts. The provisional variant, computed at creation, uses the driver-declared `lines` and the creation clock. The verified variant, computed at QA verification, takes its quantities from the QA-supplied `verified_lines` but recomputes each line's age from the original creation clock — pickup time is fixed at creation and does not move with the verification.

QA verification requires the verifier to differ from `recorded_by_driver_id` (§2.10, else `ERR_SEGREGATION_OF_DUTIES`); it stores the supplied `verified_lines`, computes `final_credit_cents` via the verified variant, adds the sum of the verified quantities onto the store's `lifetime_stale_units`, and moves the return from `PENDING_VERIFICATION` to `VERIFIED`. QA may instead reject a pending return outright — the request carries a `reason` — moving it to the terminal `REJECTED` state. A store that disagrees with a verification disputes it: a `StoreReceiver` whose `X-User-ID` equals the return's `store_id` (else `ERR_FORBIDDEN_FOR_ROLE`) moves the return from `VERIFIED` to `DISPUTED`. Resolution is again QA's: supplying fresh `verified_lines` moves the return from `DISPUTED` back to `VERIFIED`, recomputes `final_credit_cents` with the same verified variant, and increments `dispute_round` by 1.

Applying the credit is a `Planner` action with two guards: the store must be `ACTIVE` (else `ERR_STORE_SUSPENDED`) and `final_credit_cents` must not exceed 50,000 cents (else `ERR_STALE_CREDIT_CAP_EXCEEDED`). Crediting sets `credited_amount_cents` to `final_credit_cents`, adds that amount onto the store's `credit_balance_cents`, increments the store's `version`, and moves the return from `VERIFIED` to `CREDITED`. Should a credit need unwinding, a `PlantAdmin` reverses it: the store's `credit_balance_cents` is reduced by `credited_amount_cents`, the store's `version` increments again, and the return moves from `CREDITED` to the terminal `REVERSED` state.

Verified stale stock feeds the thrift outlet channel. The thrift stock pool for a product is its inflow minus its outflow: inflow is the sum of quantities over `verified_lines` of returns in `VERIFIED`, `DISPUTED`, `CREDITED`, or `REVERSED` status whose line earned a positive rate — which, given the rate table, means loaves aged 48 hours or less at pickup — and outflow is the sum of `units` over that product's thrift sales in `RECORDED` status. A `ThriftClerk` records an outlet sale with the `product_id`, the `units` sold (greater than zero), and a `unit_price_cents`; the price must be at least half the product's `base_price_cents` rounded up to a whole cent (else `ERR_THRIFT_PRICE_BELOW_FLOOR`), and the requested units must not exceed the pool's available stock (else `ERR_THRIFT_STOCK_UNAVAILABLE`). The sale's `plant_id` is copied from the product, its `total_cents` is `units` multiplied by `unit_price_cents`, and its status starts `RECORDED`. A `PlantAdmin` may void a recorded sale, moving it from `RECORDED` to the terminal `VOIDED` state and crediting its units back into the pool — a sale followed by its own void leaves the pool exactly unchanged.

### 3.9. Ingredient Indices and Surcharge Pass-Through

Ingredient cost pass-through is monthly and two-staged. A `PricingAnalyst` creates an ingredient index by naming the `plant_id`, the `ingredient` — `FLOUR` or `BUTTER` — the `period` in `YYYY-MM` form, and a `forecast_value` greater than zero. One index exists per plant, ingredient, and period, and a new index enters in `FORECAST` status with `published_value` empty.

Against those forecasts, a `PricingAnalyst` creates a surcharge schedule naming the `product_id` and the `period`; one schedule exists per product and period. Creation requires the plant's `FLOUR` and `BUTTER` indices for that period to exist in the status the operation needs — forecasts at schedule creation, published values at finalization — and a missing or wrong-status index is rejected with `ERR_INDEX_NOT_PUBLISHED`. Creation computes `provisional_surcharge_cents` from the forecast values and sets the schedule to `PROVISIONAL`.

The surcharge formula is the same in both variants; only the index value differs. For each ingredient, the delta is the index value minus the plant's baseline for that ingredient (`baseline_flour_index` or `baseline_butter_index`), divided by that baseline. The surcharge percentage is the product's `flour_share_pct` multiplied by the flour delta plus its `butter_share_pct` multiplied by the butter delta, then clamped so it is never below 0 and never above 0.15 — fifteen percent. The surcharge in cents is the product's `base_price_cents` multiplied by that clamped percentage, rounded half-up to a whole cent. The provisional variant reads `forecast_value`; the final variant reads `published_value`.

Publishing is the `PricingAnalyst`'s second act: supplying the `published_value` moves the index from `FORECAST` to `PUBLISHED` and fires a two-hop cascade. First, every `PROVISIONAL` surcharge schedule for that plant and period whose required `FLOUR` and `BUTTER` indices are now all `PUBLISHED` finalizes: its `final_surcharge_cents` is computed with the final variant and its status moves to the terminal `FINALIZED`. Second, each affected product's `current_surcharge_cents` is set to that final amount, with the product's `version` incrementing. A product whose period has no finalized schedule simply keeps whatever `current_surcharge_cents` it already had — 0 if none has ever finalized.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. List endpoints accept the optional query filters named per resource in Section 3 — for example `plant_id`, `status`, `store_id`, `production_plan_id`, `line_id`, `product_id`, `driver_id`, `route_date`, `route_id`, `store_order_id`, `route_stop_id`, `ingredient`, and `period` — and paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlantAdmin |
| POST | `/bakery/plants` | Create a plant | PlantAdmin |
| GET | `/bakery/plants` | List plants | Any |
| GET | `/bakery/plants/{id}` | Get a plant | Any |
| POST | `/bakery/plants/{id}/close_day` | Ops-run checkpoint: advance day, overproof stale batches, suspend high-stale stores | PlantAdmin |
| POST | `/bakery/products` | Create a product | PlantAdmin |
| GET | `/bakery/products` | List products | Any |
| GET | `/bakery/products/{id}` | Get a product | Any |
| POST | `/bakery/stores` | Create a store | PlantAdmin |
| GET | `/bakery/stores` | List stores | Any |
| GET | `/bakery/stores/{id}` | Get a store | Any |
| POST | `/bakery/stores/{id}/suspend` | Suspend a store (credit hold) | PlantAdmin |
| POST | `/bakery/stores/{id}/reinstate` | Reinstate a suspended store | PlantAdmin |
| POST | `/bakery/drivers` | Create a driver | PlantAdmin |
| GET | `/bakery/drivers` | List drivers | Any |
| GET | `/bakery/drivers/{id}` | Get a driver | Any |
| POST | `/bakery/lines` | Create a production line | PlantAdmin |
| GET | `/bakery/lines` | List lines | Any |
| GET | `/bakery/lines/{id}` | Get a line | Any |
| POST | `/bakery/store-orders` | Place a store order | Planner, PlantAdmin |
| GET | `/bakery/store-orders` | List store orders | Any |
| GET | `/bakery/store-orders/{id}` | Get a store order | Any |
| POST | `/bakery/store-orders/{id}/confirm` | Confirm an order (cutoff + store checks) | Planner |
| POST | `/bakery/store-orders/{id}/request-amendment` | Store requests line amendment (OCC on order version) | StoreReceiver |
| POST | `/bakery/store-orders/{id}/accept-amendment` | Planner accepts amended lines | Planner |
| POST | `/bakery/store-orders/{id}/reject-amendment` | Planner rejects amended lines | Planner |
| POST | `/bakery/store-orders/{id}/lock` | Lock an order for production planning | Planner |
| POST | `/bakery/store-orders/{id}/cancel` | Cancel an order | Planner |
| POST | `/bakery/production-plans` | Create a production plan (supersedes existing draft; OCC on plant version) | Planner |
| GET | `/bakery/production-plans` | List production plans | Any |
| GET | `/bakery/production-plans/{id}` | Get a production plan | Any |
| POST | `/bakery/production-plans/{id}/lock` | Lock plan and compute requirements | Planner |
| POST | `/bakery/production-plans/{id}/unlock` | Revert a locked plan to draft | Planner |
| POST | `/bakery/production-plans/{id}/release` | Release plan to the floor | Planner |
| POST | `/bakery/production-plans/{id}/reconcile` | Reconcile a fully-terminal plan | Planner |
| POST | `/bakery/batches` | Schedule a batch on a line (OCC on plan version) | Planner |
| GET | `/bakery/batches` | List batches | Any |
| GET | `/bakery/batches/{id}` | Get a batch | Any |
| POST | `/bakery/batches/{id}/start-mix` | Start mixing | LineOperator |
| POST | `/bakery/batches/{id}/start-proof` | Start proofing | LineOperator |
| POST | `/bakery/batches/{id}/start-bake` | Start baking (proof window enforced) | LineOperator |
| POST | `/bakery/batches/{id}/complete-bake` | Complete baking (starts staling clock) | LineOperator |
| POST | `/bakery/batches/{id}/release` | QA release (segregation of duties vs baker) | QALead |
| POST | `/bakery/batches/{id}/reject` | QA reject (cascades to plan, stops, orders) | QALead |
| POST | `/bakery/batches/{id}/abort` | Abort a scheduled batch | Planner |
| POST | `/bakery/sanitation-cycles` | Request a sanitation changeover cycle | LineOperator |
| GET | `/bakery/sanitation-cycles` | List sanitation cycles | Any |
| GET | `/bakery/sanitation-cycles/{id}` | Get a sanitation cycle | Any |
| POST | `/bakery/sanitation-cycles/{id}/start` | Start (or restart after fail) a cycle | LineOperator |
| POST | `/bakery/sanitation-cycles/{id}/verify` | QA verify a completed cycle | QALead |
| POST | `/bakery/sanitation-cycles/{id}/fail` | QA fail a cycle | QALead |
| POST | `/bakery/routes` | Create a route (driver rest-buffer enforced) | Planner |
| GET | `/bakery/routes` | List routes | Any |
| GET | `/bakery/routes/{id}` | Get a route | Any |
| POST | `/bakery/routes/{id}/start-loading` | Begin loading; freezes loaded units | Driver |
| POST | `/bakery/routes/{id}/dispatch` | Dispatch the truck (capacity enforced) | Driver |
| POST | `/bakery/routes/{id}/complete` | Complete the route | Driver |
| POST | `/bakery/routes/{id}/settle` | Settle route: shrink + driver liability | Planner |
| POST | `/bakery/routes/{id}/cancel` | Cancel a planned route | Planner |
| POST | `/bakery/route-stops` | Add a stop to a route | Planner |
| GET | `/bakery/route-stops` | List stops | Any |
| GET | `/bakery/route-stops/{id}` | Get a stop | Any |
| POST | `/bakery/route-stops/{id}/deliver` | Driver delivers and stocks shelf | Driver |
| POST | `/bakery/route-stops/{id}/skip` | Skip a stop | Driver |
| POST | `/bakery/route-stops/{id}/reconcile` | Reconcile a delivered stop | Planner |
| POST | `/bakery/stale-returns` | Driver records a stale pickup (provisional credit) | Driver |
| GET | `/bakery/stale-returns` | List stale returns | Any |
| GET | `/bakery/stale-returns/{id}` | Get a stale return | Any |
| POST | `/bakery/stale-returns/{id}/verify` | QA verifies quantities (final credit) | QALead |
| POST | `/bakery/stale-returns/{id}/dispute` | Store disputes a verified return | StoreReceiver |
| POST | `/bakery/stale-returns/{id}/resolve-dispute` | QA re-verifies after dispute | QALead |
| POST | `/bakery/stale-returns/{id}/credit` | Apply credit to store balance | Planner |
| POST | `/bakery/stale-returns/{id}/reverse-credit` | Reverse an applied credit | PlantAdmin |
| POST | `/bakery/stale-returns/{id}/reject` | QA rejects a pending return | QALead |
| POST | `/bakery/thrift-sales` | Record a thrift-outlet sale of distressed stock | ThriftClerk |
| GET | `/bakery/thrift-sales` | List thrift sales | Any |
| GET | `/bakery/thrift-sales/{id}` | Get a thrift sale | Any |
| POST | `/bakery/thrift-sales/{id}/void` | Void a thrift sale (restores pool) | PlantAdmin |
| POST | `/bakery/ingredient-indices` | Create a forecast ingredient index | PricingAnalyst |
| GET | `/bakery/ingredient-indices` | List ingredient indices | Any |
| GET | `/bakery/ingredient-indices/{id}` | Get an ingredient index | Any |
| POST | `/bakery/ingredient-indices/{id}/publish` | Publish an index (finalizes schedules, updates surcharges) | PricingAnalyst |
| POST | `/bakery/surcharge-schedules` | Create a provisional surcharge schedule from forecast indices | PricingAnalyst |
| GET | `/bakery/surcharge-schedules` | List surcharge schedules | Any |
| GET | `/bakery/surcharge-schedules/{id}` | Get a surcharge schedule | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ORDER_CUTOFF_PASSED` | 409 Conflict |
| `ERR_DUPLICATE_PLAN_DATE` | 409 Conflict |
| `ERR_PLAN_NOT_RELEASABLE` | 409 Conflict |
| `ERR_SANITATION_REQUIRED` | 409 Conflict |
| `ERR_ALLERGEN_SEGREGATION_VIOLATION` | 409 Conflict |
| `ERR_SANITATION_NOT_COMPLETE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PROOF_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_LINE_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_LINE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_DRIVER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STORE_SUSPENDED` | 409 Conflict |
| `ERR_STOPS_NOT_LOCKED` | 409 Conflict |
| `ERR_PLANNED_QTY_MISMATCH` | 409 Conflict |
| `ERR_FRESHNESS_WINDOW_VIOLATION` | 409 Conflict |
| `ERR_RETURN_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SHRINK_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_STALE_CREDIT_CAP_EXCEEDED` | 409 Conflict |
| `ERR_THRIFT_PRICE_BELOW_FLOOR` | 409 Conflict |
| `ERR_THRIFT_STOCK_UNAVAILABLE` | 409 Conflict |
| `ERR_INDEX_NOT_PUBLISHED` | 409 Conflict |
