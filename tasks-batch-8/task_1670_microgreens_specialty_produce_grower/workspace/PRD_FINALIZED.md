# Microgreens Specialty Grower API — Product Requirements Document

## 1. Introduction

A chef-direct specialty grower lives and dies by timing. Trays of microgreens, petite greens, edible flowers, and specialty herbs are sown weeks before a restaurant ever plates them; seed lots arrive under quarantine until a germination test clears them; a single failed lot can cascade through the week's crop plans and leave a standing order short. At the same time, chefs expect the freedom to revise their weekly standing order up to a cutoff day, expect delivery only when their stop clears the route's minimum, and expect fair credit when product arrives spoiled. This document specifies the API that holds those tensions together.

The API covers the grower's full operating loop: variety trials and chef tasting panels that decide what enters the catalog, seed-lot intake with germination-based release, crop planning and sow-to-harvest tray scheduling, a food-safety plan whose approval gates every sow and whose sanitation records gate every harvest, chef-facing standing orders with a weekly change window, delivery routes that enforce a per-stop minimum subtotal, spoilage credits posted to a customer balance, and a farmers-market channel for surplus harvest. All endpoints are mounted under `/grow`. Because several workflows depend on the calendar — weekly order lock, harvest scheduling — the service runs on a logical clock rather than wall-clock time, as described in §2.5.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the API: authentication, response shape, pagination, resource identity, the logical clock, food-safety gating, numeric precision, concurrency control, and the order in which validations run.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The API recognizes exactly three roles, spelled as follows: `Grower`, `Chef`, and `OpsManager`. A request with missing or malformed headers is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted to perform the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Grower`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `logged_by` on a sanitation record) but does not compare it to any entity's `id`. When `X-User-Role` is `Chef`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's `customer_id` field to `X-User-ID`. When `X-User-Role` is `OpsManager`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`.

Broadly, the `Grower` owns grow operations — varieties, trials, seed lots, germination tests, crop plans, tray batches, sanitation logs, and surplus listings. The `Chef` owns ordering — standing orders, weekly line changes, confirmation, cancellation — and may report spoilage. The `OpsManager` owns compliance and logistics — customer onboarding, food-safety plans, delivery routes and stops, credit adjudication, and the logical clock. Read access is comparatively broad; the per-endpoint role list in §4 is authoritative.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Many list endpoints additionally accept resource-specific filter parameters (for example, filtering the variety list by `stage` or the order-item list by `fulfillment`); the filters available on each list are introduced alongside that resource in §3.

### 2.4. Resource Identity and Common Fields

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 and increments by one on every mutation, including mutations driven by cascades originating on other resources.

One resource deviates from this convention: a `SanitationLog` is an immutable, append-only record and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from sanitation logs; a log, once written, is never modified.

### 2.5. The Logical Clock

The service keeps a logical clock that is decoupled from wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z, and it must never silently fall back to wall-clock time; the only way it advances is through the `OpsManager`-only capability `POST /grow/_clock/set_current_utc`, which moves the clock to a supplied `to_iso8601` instant. The logical clock is the single source of "now" for the domain: it stamps a tray batch's `sown_at` at sow time, stamps a food-safety plan's `approved_at` at approval, and drives the weekly order cycle — a `CONFIRMED` standing order flips to `LOCKED` once the clock's weekday passes the order's cutoff, and a `LOCKED` order returns to `CONFIRMED` on the weekly rollover into its next effective week.

### 2.6. Food Safety as a Hard Gate

Food safety is not advisory in this system; it is a precondition woven into the grow workflow at two points. First, no crop plan may be sown while the operation's food-safety plan is in any state other than `APPROVED` — the check applies whether the plan was never approved or has been `SUSPENDED`. Second, no tray batch may be harvested until a passing sanitation record exists for that batch. The full lifecycle of the food-safety plan (drafting, approval, suspension, reinstatement) is specified in §3.3 and §3.4 together with the workflows it gates; the rejections it produces are `ERR_FOOD_SAFETY_NOT_APPROVED`, `ERR_SANITATION_NOT_LOGGED`, and `ERR_SANITATION_FAILED`.

### 2.7. Money, Weights, Rates, and Rounding

All monetary amounts are integer cents. Every computed monetary value — a line extension, an order subtotal, a stop subtotal, a spoilage credit — is rounded half-up to whole cents. Where a total is built from per-line amounts, the rounding order is pinned: each line is rounded first, and only then are the rounded lines summed.

Quantities of produce and seed are tracked in kilograms or grams as named. Weekly order quantities and harvested amounts are kilograms carried to three decimal places. Germination rates are carried to four decimal places, rounded half-up. Dates derived from durations (such as an expected harvest date) are computed at day granularity.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two; endpoints not listed here do not accept a version field.

Adding a weekly-change line to a standing order requires the request to carry `expected_standing_order_version`, holding the order's `version` as the client last observed it. If the order's current `version` has advanced past that value — because another write (a line add, a confirm) has landed since the client last read the order — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite an order state it never observed.

Sowing a crop plan follows the same pattern: the sow request must carry `expected_crop_plan_version` matching the plan's current `version`. If the plan's version has advanced since the client last read it — for example because `planned_tray_count` or `seed_grams_required` was edited — the sow is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Resource Addressing, Existence, and Validation Order

Resources are addressed flatly by their own `id`; there is no deep URL nesting. Two collections sit beneath a parent — an order's lines beneath its standing order, and a route's stops beneath the route — and for those, path identifiers are validated left to right: a request naming a non-existent standing order is rejected with `ERR_STANDING_ORDER_NOT_FOUND` before any line-level validation runs, and a request naming a non-existent route is rejected with `ERR_ROUTE_NOT_FOUND` before any stop-level validation runs.

Every request is validated in a fixed priority order, and a failure at any step masks all later checks. First, the user-context headers are verified (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400). Second, the role's permission for the operation is checked (`ERR_INSUFFICIENT_PERMISSIONS`, 403). Third, the existence of every resource named in the path and every foreign key in the body is verified; each resource type has its own 404 — `ERR_CUSTOMER_NOT_FOUND`, `ERR_VARIETY_NOT_FOUND`, `ERR_SEED_LOT_NOT_FOUND`, `ERR_GERMINATION_TEST_NOT_FOUND`, `ERR_CROP_PLAN_NOT_FOUND`, `ERR_TRAY_BATCH_NOT_FOUND`, `ERR_STANDING_ORDER_NOT_FOUND`, `ERR_ORDER_ITEM_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_CREDIT_NOT_FOUND`, and `ERR_TRIAL_NOT_FOUND`. Fourth, state preconditions are checked — the target resource must be in a state that admits the operation — producing the per-resource 409 rejections such as `ERR_ORDER_NOT_EDITABLE`, `ERR_BATCH_NOT_READY`, and `ERR_ROUTE_NOT_DISPATCHED`, with `ERR_INVALID_STATE` as the generic state-precondition failure. Fifth, the food-safety gate runs for the operations it protects. Sixth, business constraints on seed lots (released status, sufficient seed on hand) are enforced. Seventh, temporal business rules are evaluated — the weekly change cutoff and the requirement that an orderable variety be listed. Eighth and last come the fiscal checks: a credit quantity may not exceed the delivered quantity (`ERR_CREDIT_EXCEEDS_DELIVERY`, 422), and an OCC version must match (`ERR_STALE_VERSION`, 412). Independently of this ordering, a request body that is missing a required field or carries a value of the wrong type is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. From Trial Tray to Catalog: Varieties and Chef Panels

Everything the grower sells begins as a `Variety`. A `Grower` registers one with a `name` (say, "Red Garnet Amaranth"), a `crop_category` of `MICROGREEN`, `PETITE_GREEN`, `EDIBLE_FLOWER`, or `SPECIALTY_HERB`, the nominal `days_to_harvest`, the `expected_yield_grams_per_tray` for a standard 1020 tray, the catalog `listed_price_cents_per_kg`, and a `min_order_grams` below which the variety is not sold. A new variety enters in `stage` `TRIAL`: it exists, but it is not yet orderable. The variety list may be filtered by `stage`.

To earn a catalog slot, a variety goes through a `VarietyTrial`. The `Grower` opens a trial by naming the `variety_id`, the `sow_date` the trial trays went down, the `chef_panel_size` — how many chefs will score the harvest — and a `yield_score`, the grower's own yield rating from 0.0 to 10.0 recorded at the trial harvest. The trial's `decision` starts as `PENDING`, and its `avg_flavor_score` stays null until panel scores come in. Trials may be listed filtered by `variety_id`.

When the panel has eaten, the `Grower` records the panel's `scores` — this is done while the trial's `decision` is still `PENDING`. Once scores from the full `chef_panel_size` are in, the system computes `avg_flavor_score` as the mean of the submitted scores and moves the variety from `TRIAL` to `EVALUATION`; the trial itself remains `PENDING` until an explicit decision. The decide action takes an `outcome`. With `outcome` set to `ADOPT`, the variety is promoted only if its `avg_flavor_score` is at least 6.0 and its `yield_score` is at least 5.0 — an adoption attempted against weaker numbers is rejected with `ERR_TRIAL_CRITERIA_NOT_MET`. A successful adoption sets the trial's `decision` to `ADOPTED` and moves the variety from `EVALUATION` to `LISTED`, at which point chefs may put it on standing orders. With `outcome` set to `RETRIAL`, the trial's `decision` becomes `REJECTED` and the variety falls back from `EVALUATION` to `TRIAL`, a revision loop in which the grower may open a fresh trial for the same variety.

A `LISTED` variety can later be retired. Retirement moves it from `LISTED` to the terminal `RETIRED` stage, but only while no order line whose `fulfillment` is `PLANNED` or `ALLOCATED` still references it; if open demand exists, the retire is rejected with `ERR_VARIETY_IN_USE`.

### 3.2. Seed Intake, Quarantine, and Germination Clearance

Seed arrives as a `SeedLot`. A `Grower` receives a lot by recording its `variety_id`, the `supplier_name`, the supplier's `lot_code` — unique per variety, so the same `lot_code` may not repeat under one `variety_id` — the `received_date`, and the starting `seeds_on_hand_grams`. Every new lot lands in `QUARANTINE`: it is on the shelf, but nothing may be sown from it. The lot list may be filtered by `variety_id` and by `status`.

Clearance comes from a `GerminationTest`. The `Grower` starts a test against a `seed_lot_id` by placing `seeds_sown_count` seeds in a test cell; the test's `result` is `PENDING` and its `germinated_count` and `germination_rate` are unset. Tests may be listed filtered by `seed_lot_id`. When the cell is read, the `Grower` records the `germinated_count`; the system computes `germination_rate` as the germinated count divided by the seeds sown, carried to four decimal places rounded half-up. A rate of at least 0.85 — the boundary is inclusive — sets the test's `result` to `PASS`; anything below 0.85 sets it to `FAIL`.

The test result drives the lot. A `PASS` moves a `QUARANTINE` lot to `RELEASED`, and a re-test that passes on an already-`RELEASED` lot simply leaves it `RELEASED`. A `FAIL` moves a `QUARANTINE` lot to `BLOCKED`. More painfully, a `FAIL` recorded on a re-test of a lot that was already `RELEASED` — the supplier-recall case — also moves it to `BLOCKED`, and blocking a live lot triggers the failure cascade: every tray batch drawing from that lot whose status is `SOWN`, `GERMINATING`, or `GROWING` is transitioned to `FAILED`. For each failed batch, its crop plan recomputes the projected shortfall as the plan's `base_harvest_kg` minus the summed `harvested_kg` of its surviving batches, and that shortfall marks matching `PLANNED` order lines `SHORTED` through a fresh allocation pass of the kind described in §3.4. The shortfall in turn reduces the affected stops' `stop_subtotal_cents` and can flip a stop from `INCLUDED` to `SKIPPED` the next time its route is dispatched. `BLOCKED` is terminal, as is `DEPLETED`, which the system applies automatically when a sow draws a lot's `seeds_on_hand_grams` down to exactly zero.

### 3.3. Crop Plans and the Sow Gate

Standing behind every sow is the operation's `FoodSafetyPlan`. An `OpsManager` authors one with a unique `plan_code` (for example, FSP-2026-A), a `water_test_current` flag that is true only while a passing water test is on file and in date, and the `sanitation_sop_version` document string the washroom runs under. The plan enters in `DRAFT`. Approval moves it from `DRAFT` to `APPROVED` and is refused unless `water_test_current` is true — approving against a lapsed water test is rejected with `ERR_FOOD_SAFETY_NOT_APPROVED`; on approval the plan's `approved_at` is stamped from the logical clock. An approved plan can be suspended, moving from `APPROVED` to `SUSPENDED`, and while any plan is suspended the §2.6 gate is no longer satisfied, so sowing stops. Reinstatement is approval again — from `SUSPENDED` back to `APPROVED` under the same water-test precondition — and it refreshes `approved_at`.

Production itself is scheduled as `CropPlan`s. A `Grower` creates a plan with a `variety_id`, a `planned_sow_date`, a `planned_tray_count`, and the `seed_grams_required` the plan will draw. The plan starts in `PLANNED` with `sown_tray_count` at zero, and the system fixes its `base_harvest_kg` at creation as the planned tray count multiplied by the variety's `expected_yield_grams_per_tray` and divided by 1000 — this figure is frozen at plan creation and is not recomputed if the variety's yield estimate is edited later. Plans may be listed filtered by `variety_id` and `status`, and a plan that is still `PLANNED` may be cancelled outright, moving it to `CANCELLED`.

Sowing is the most heavily guarded write in the system. The sow request names the `seed_lot_id` to draw from and must carry `expected_crop_plan_version` per §2.8. The guards run in the §2.9 order: the operation-wide food-safety plan must be `APPROVED` or the sow is rejected with `ERR_FOOD_SAFETY_NOT_APPROVED`; the named lot must be `RELEASED` — a lot in `QUARANTINE`, `BLOCKED`, or `DEPLETED` yields `ERR_SEED_LOT_NOT_RELEASED`; the plan's `seed_grams_required` must not exceed the lot's remaining `seeds_on_hand_grams`, else `ERR_INSUFFICIENT_SEED`; and only then is the client's expected version compared against the plan's current `version`, a mismatch surfacing as `ERR_STALE_VERSION`. Because of the fixed ordering, a stale version is only reported once the safety and seed checks have passed.

A successful sow creates a `TrayBatch` under the plan, recording the `crop_plan_id`, the `seed_lot_id` it draws from, and a `tray_count` equal to the plan's `planned_tray_count`; the batch starts `SOWN`. The lot's `seeds_on_hand_grams` is decremented by the plan's `seed_grams_required` (which may, as noted in §3.2, tip the lot into `DEPLETED`). The plan's `sown_tray_count` is set to its `planned_tray_count`, the plan moves from `PLANNED` to `SOWING`, and the plan's `version` increments. The batch's `sown_at` is stamped from the logical clock, and its `expected_harvest_date` falls out as the date of `sown_at` plus the variety's `days_to_harvest` days.

### 3.4. Growing Trays, Sanitation, and Harvest Allocation

A tray batch ripens through a fixed chain. Each advance action by a `Grower` moves the batch one step — `SOWN` to `GERMINATING`, `GERMINATING` to `GROWING`, and `GROWING` to `READY` — and each advance requires the batch to be in the immediately preceding state. The parent crop plan follows its batch: the plan leaves `SOWING` for `GROWING` as the batch's germination is confirmed, and reaches `READY` when the batch does, at its `expected_harvest_date`. Batches may be listed filtered by `crop_plan_id`, by `seed_lot_id`, and by `status`. Any batch still in `SOWN`, `GERMINATING`, or `GROWING` can also be torn out of the chain by the §3.2 failure cascade, landing in `FAILED`.

Before any harvest, sanitation must be on record. A `Grower` files a `SanitationLog` naming the `harvest_batch_id` — the tray batch the record covers — whether the `surface_swab_passed`, the `wash_water_ppm` sanitizer concentration measured in the wash water, and a `logged_by` operator identifier. Logs may be listed filtered by `harvest_batch_id`, and per §2.4 a log is immutable once written.

The harvest action, which records the net `harvested_kg`, is gated twice. The batch must be `READY` — harvesting in any other state is rejected with `ERR_BATCH_NOT_READY` — and the sanitation gate must pass: if no `SanitationLog` exists for the batch at all, the rejection is `ERR_SANITATION_NOT_LOGGED`; if a log exists but shows `surface_swab_passed` false or a `wash_water_ppm` outside the inclusive band of 50 to 200 parts per million, the rejection is `ERR_SANITATION_FAILED`. On a clean harvest the batch moves to `HARVESTED` with its `harvested_kg` recorded (it had been zero until then), the parent plan moves to `HARVESTED`, and the allocation pass runs.

Allocation is a waterfall over open demand. The freshly harvested kilograms are offered to order lines whose `fulfillment` is `PLANNED` for the same variety, taken in order of the standing order's `effective_week_start`, earliest first, with ties broken by the standing order's `created_at`, earliest first — never by identifier. Each line is filled against its `qty_kg` in turn: a line that can be fully covered becomes `ALLOCATED`, and when supply runs out mid-line that line is partially allocated with its unfilled remainder marked `SHORTED`. The pass never splits a line: no new `OrderItem` is created for the unfilled remainder — the partially covered line's own `fulfillment` flips to `SHORTED`, its `qty_kg` and `line_extension_cents` are left at the values stamped when the line was created, and the last of the supply is consumed against that line, so every line visited after it in the same pass is likewise marked `SHORTED`. Kilograms left over after every `PLANNED` line for the variety has been visited become surplus and may be offered through the farmers-market channel of §3.8.

### 3.5. Standing Orders and the Weekly Change Window

Before anyone can order, an `OpsManager` onboards a `Customer` with a `business_name`, a `contact_email`, and a `delivery_zone` code (such as `NORTH`, `SOUTH`, or `MARKET`) used for route assignment. The customer's `credit_balance_cents` starts at zero — it only ever grows through resolved spoilage credits, §3.7 — and `is_active` starts true; a deactivated customer cannot place changes.

A `Chef` opens a `StandingOrder` by naming the `customer_id`, the `effective_week_start` — the ISO Monday date of the first week the revision covers — and a `change_cutoff_day`, a day-of-week index running from 0 for Monday to 6 for Sunday, after which weekly changes lock for the coming week. The order starts in `DRAFT` with `version` 1. Standing orders may be listed filtered by `customer_id` and `status`.

Weekly change lines are the heartbeat of the order. When a `Chef` adds a line, the payload carries the `variety_id`, the weekly `qty_kg` to three decimal places, optionally a `unit_price_cents_per_kg` — which defaults from the variety's `listed_price_cents_per_kg` when omitted — and the `expected_standing_order_version` required by §2.8. The gates apply in §2.9 order: the order must still be editable — line edits against an order that is neither `DRAFT` nor `CONFIRMED` are rejected with `ERR_ORDER_NOT_EDITABLE`; then the temporal checks — if the logical clock has moved the order into `LOCKED` the add is rejected with `ERR_WEEKLY_CHANGE_LOCKED`, and a line naming a variety whose `stage` is anything other than `LISTED` is rejected with `ERR_VARIETY_NOT_LISTED`; finally the OCC comparison rejects a stale writer with `ERR_STALE_VERSION`. An accepted line is created as an `OrderItem` in `PLANNED` `fulfillment`; its `line_extension_cents` is computed as the `qty_kg` multiplied by the line's `unit_price_cents_per_kg`, rounded half-up to whole cents, with each line rounded before any summing. The order's `weekly_subtotal_cents` — the sum of the `line_extension_cents` over all of the order's current lines — is recomputed on every line change, and the order's `version` increments with each accepted line. Order lines may be listed filtered by `standing_order_id`, by `variety_id`, and by `fulfillment`, and the lines of one order may be listed beneath it.

Confirming moves the order from `DRAFT` to `CONFIRMED`. A confirm requires at least one line — an empty order is rejected with `ERR_EMPTY_ORDER` — and carries `expected_standing_order_version` like any other guarded write; confirmation recomputes the `weekly_subtotal_cents` and increments `version`. From `CONFIRMED`, the calendar takes over: once the logical clock's weekday passes the order's `change_cutoff_day` relative to its `effective_week_start`, the system moves the order to `LOCKED` and no further line changes are accepted for that week. The subtotal of a `LOCKED` order is the final variant — frozen from the locked lines — and it is this frozen figure that dispatch later uses for stop subtotals, in contrast to the provisional subtotal of a `DRAFT` or `CONFIRMED` order, which simply reflects the current editable lines. When the week rolls over into the next effective week, a `LOCKED` order returns to `CONFIRMED` and may be edited again.

Two reads help both sides plan. Alongside the order itself, a revenue projection reports two totals over the same order: an all-lines total summing the `line_extension_cents` of every `OrderItem` regardless of status — the grower's capacity-planning view, which includes draft edits — and a confirmed-only total summing lines only while the parent order is `CONFIRMED` or `LOCKED`, the operations and fiscal view, which excludes unconfirmed draft edits and is therefore the smaller figure whenever mid-week edits are pending.

Cancellation has two shapes. Cancelling a `DRAFT` order simply drops its draft lines. Cancelling a `CONFIRMED` order releases committed demand: every line still in `PLANNED` `fulfillment` becomes `SHORTED`, and any linked delivery stop's `outcome` is flipped to `SKIPPED`. Either way the order lands in the terminal `CANCELLED` state.

### 3.6. Delivery Routes, Stop Minimums, and the Drop-Off

Logistics is organized as a `DeliveryRoute`, created by an `OpsManager` with a `route_code` such as R-NORTH-01, the `service_date` the route runs, and a `min_stop_subtotal_cents` — the per-stop minimum below which a stop is not worth the truck's time. A new route is `PLANNED`; routes may be listed filtered by `status`. Stops are added to a route one at a time, each recording its `route_id` along with a `customer_id` and the `standing_order_id` to be fulfilled there, and each stop starts with `outcome` `SCHEDULED`; the stops on a route may be listed beneath it, and the flat stop list may be filtered by `customer_id`, `standing_order_id`, and `outcome`.

Dispatch turns the plan into a manifest. Dispatching requires at least one stop still `SCHEDULED` — otherwise `ERR_EMPTY_ROUTE` — and moves the route from `PLANNED` to `DISPATCHED`. As part of dispatch the system computes each stop's `stop_subtotal_cents` as the sum of the `line_extension_cents` over the stop's order lines, using the order's final, locked subtotal. The minimum is then applied with an inclusive boundary: a stop whose `stop_subtotal_cents` is at least the route's `min_stop_subtotal_cents` becomes `INCLUDED`, and a stop below the minimum becomes `SKIPPED` — a stop landing exactly on the minimum is included. An `OpsManager` may also skip a scheduled stop directly. Skipping is not a credit event: the lines of a skipped stop remain `ALLOCATED` and roll forward to the next route rather than being credited.

At the curb, marking an `INCLUDED` stop delivered requires the route to be `DISPATCHED` — a delivery attempt against a route in any other state is rejected with `ERR_ROUTE_NOT_DISPATCHED`. A successful delivery moves the stop from `INCLUDED` to `DELIVERED`, flips its order lines to `DELIVERED`, and opens the spoilage-credit window described in §3.7. Completing the route — moving it from `DISPATCHED` to `COMPLETED` — requires that every `INCLUDED` stop is either `DELIVERED` or has at least one spoilage credit resolved. `COMPLETED` and `CANCELLED` are the route's terminal states, and `DELIVERED` and `SKIPPED` are the stop's.

### 3.7. Spoilage Credits and the Customer Credit Balance

When product arrives in poor condition, either the receiving `Chef` or an `OpsManager` reports it: the report names the `delivery_stop_id` where the spoilage was found, the `order_item_id` being credited, the `credit_qty_kg` that spoiled, and a `pricing_variant` of `ORIGINAL_PAPER` or `POST_HARVEST_PRICING`. The credit starts `PENDING`, its `credit_cents` is computed per the variant, and credits may be listed filtered by `delivery_stop_id`, `order_item_id`, and `status`.

Under `ORIGINAL_PAPER`, the credit is priced exactly as invoiced: `credit_cents` is the `credit_qty_kg` multiplied by the order line's `unit_price_cents_per_kg`, rounded half-up to whole cents.

Under `POST_HARVEST_PRICING`, the credit is priced against what the harvest actually yielded, and can only be lower than the original-paper figure. The evaluation order is pinned. First, the plan's harvest ratio is computed as the total `harvested_kg` across the crop plan's `HARVESTED` tray batches divided by the plan's `base_harvest_kg`; the plan cap factor is 1.00 when that ratio is at least 0.70, and 0.85 when the harvest fell short of seventy percent of plan. Second, the variety's overweight ratio — the plan's harvested kilograms for the variety divided by the plan's base for that variety — is compared against a ten-percent allowance: the overweight excess is the amount by which the ratio exceeds 1.10, floored at zero, and the price-adjustment factor is one minus that excess, with the excess capped so it never counts more than 0.25. Third, the capped unit price is the line's `unit_price_cents_per_kg` multiplied by the plan cap factor and by the price-adjustment factor. Only then is the capped unit price multiplied by the `credit_qty_kg`, with a single round half-up to whole cents at the very end.

Adjudication rests with the `OpsManager`. Approval is fiscally guarded: the `credit_qty_kg` must not exceed the delivered quantity of the credited order line, or the approval is rejected with `ERR_CREDIT_EXCEEDS_DELIVERY`. An approved credit posts its `credit_cents` onto the customer's `credit_balance_cents`, and when the credited quantity equals the line's full delivered quantity, the order line's `fulfillment` moves to `CREDITED`. A rejected credit simply moves to `REJECTED`. Both `APPROVED` and `REJECTED` are terminal, and a resolved credit — approved or rejected — is what lets a route with a spoiled drop still reach `COMPLETED` per §3.6.

### 3.8. The Farmers-Market Surplus Channel

Harvest rarely lands exactly on demand. Kilograms left over after the §3.4 allocation waterfall can be offered at the farmers market as a `SurplusListing`: the `Grower` names the `variety_id` offered, the `tray_batch_id` the surplus was harvested from, the `qty_kg` listed, a `market_price_cents_per_kg` — typically below the chef catalog price — and the `market_date`. The listing starts `LISTED`, and listings may be filtered by `variety_id`, by `tray_batch_id`, and by `status`. Selling the listing records the farmers-market sale at the listed `market_price_cents_per_kg` and moves it to `SOLD`; withdrawing it moves it to `WITHDRAWN`. Both are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, result recording, line additions to an existing order — return `200 OK`. Request bodies, computed fields, side effects, and the exact preconditions for every transition are specified in §2 and §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/grow/customers` | Create a customer | OpsManager |
| GET | `/grow/customers` | List customers | Grower, Chef, OpsManager |
| GET | `/grow/customers/{id}` | Get a customer | Grower, Chef, OpsManager |
| POST | `/grow/varieties` | Create a variety (starts TRIAL) | Grower |
| GET | `/grow/varieties` | List varieties | Grower, Chef, OpsManager |
| GET | `/grow/varieties/{id}` | Get a variety | Grower, Chef, OpsManager |
| POST | `/grow/varieties/{id}/retire` | Retire a LISTED variety | Grower |
| POST | `/grow/variety-trials` | Open a variety trial | Grower |
| GET | `/grow/variety-trials` | List variety trials | Grower, OpsManager |
| GET | `/grow/variety-trials/{id}` | Get a variety trial | Grower, OpsManager |
| POST | `/grow/variety-trials/{id}/record-panel` | Record chef panel scores; computes avg flavor | Grower |
| POST | `/grow/variety-trials/{id}/decide` | Decide a trial: ADOPT lists; RETRIAL loops back | Grower |
| POST | `/grow/seed-lots` | Receive a seed lot (QUARANTINE) | Grower |
| GET | `/grow/seed-lots` | List seed lots | Grower, OpsManager |
| GET | `/grow/seed-lots/{id}` | Get a seed lot | Grower, OpsManager |
| POST | `/grow/germination-tests` | Start a germination test on a lot | Grower |
| GET | `/grow/germination-tests` | List germination tests | Grower, OpsManager |
| GET | `/grow/germination-tests/{id}` | Get a germination test | Grower, OpsManager |
| POST | `/grow/germination-tests/{id}/record-result` | Record germinated count; sets PASS/FAIL, transitions lot | Grower |
| POST | `/grow/food-safety-plans` | Create a food-safety plan (DRAFT) | OpsManager |
| GET | `/grow/food-safety-plans/{id}` | Get a food-safety plan | Grower, OpsManager |
| POST | `/grow/food-safety-plans/{id}/approve` | Approve a plan (requires current water test) | OpsManager |
| POST | `/grow/food-safety-plans/{id}/suspend` | Suspend a plan | OpsManager |
| POST | `/grow/sanitation-logs` | Log pre-harvest sanitation for a batch | Grower |
| GET | `/grow/sanitation-logs` | List sanitation logs | Grower, OpsManager |
| GET | `/grow/sanitation-logs/{id}` | Get a sanitation log | Grower, OpsManager |
| POST | `/grow/crop-plans` | Create a crop plan | Grower |
| GET | `/grow/crop-plans` | List crop plans | Grower, OpsManager |
| GET | `/grow/crop-plans/{id}` | Get a crop plan | Grower, OpsManager |
| POST | `/grow/crop-plans/{id}/sow` | Sow the plan from a RELEASED seed lot (OCC guarded) | Grower |
| POST | `/grow/crop-plans/{id}/cancel` | Cancel a PLANNED crop plan | Grower |
| GET | `/grow/tray-batches` | List tray batches | Grower, OpsManager |
| GET | `/grow/tray-batches/{id}` | Get a tray batch | Grower, OpsManager |
| POST | `/grow/tray-batches/{id}/advance` | Advance batch SOWN → GERMINATING → GROWING → READY | Grower |
| POST | `/grow/tray-batches/{id}/harvest` | Harvest a READY batch (sanitation gated) | Grower |
| POST | `/grow/standing-orders` | Create a standing order (DRAFT) | Chef |
| GET | `/grow/standing-orders` | List standing orders | Grower, Chef, OpsManager |
| GET | `/grow/standing-orders/{id}` | Get a standing order | Grower, Chef, OpsManager |
| GET | `/grow/standing-orders/{id}/projection` | Revenue projection (all-lines vs confirmed-only) | Grower, OpsManager |
| POST | `/grow/standing-orders/{id}/lines` | Add a weekly-change line (OCC, cutoff, LISTED gated) | Chef |
| GET | `/grow/standing-orders/{id}/lines` | List lines of a standing order | Grower, Chef, OpsManager |
| POST | `/grow/standing-orders/{id}/confirm` | Confirm a DRAFT order | Chef |
| POST | `/grow/standing-orders/{id}/cancel` | Cancel an order | Chef |
| GET | `/grow/order-items` | List order items | Grower, Chef, OpsManager |
| GET | `/grow/order-items/{id}` | Get an order item | Grower, Chef, OpsManager |
| POST | `/grow/delivery-routes` | Create a delivery route (PLANNED) | OpsManager |
| GET | `/grow/delivery-routes` | List delivery routes | Grower, OpsManager |
| GET | `/grow/delivery-routes/{id}` | Get a delivery route | Grower, OpsManager |
| POST | `/grow/delivery-routes/{id}/stops` | Add a stop to a route | OpsManager |
| GET | `/grow/delivery-routes/{id}/stops` | List stops on a route | Grower, OpsManager |
| POST | `/grow/delivery-routes/{id}/dispatch` | Dispatch route; computes stop subtotals, INCLUDED/SKIPPED by minimum | OpsManager |
| POST | `/grow/delivery-routes/{id}/complete` | Complete a route | OpsManager |
| GET | `/grow/delivery-stops` | List delivery stops | Grower, OpsManager |
| GET | `/grow/delivery-stops/{id}` | Get a delivery stop | Grower, OpsManager |
| POST | `/grow/delivery-stops/{id}/deliver` | Mark an INCLUDED stop delivered | OpsManager |
| POST | `/grow/delivery-stops/{id}/skip` | Skip a stop | OpsManager |
| POST | `/grow/spoilage-credits` | Report spoilage on a delivered stop | Chef, OpsManager |
| GET | `/grow/spoilage-credits` | List spoilage credits | Grower, Chef, OpsManager |
| GET | `/grow/spoilage-credits/{id}` | Get a spoilage credit | Grower, Chef, OpsManager |
| POST | `/grow/spoilage-credits/{id}/approve` | Approve a credit; posts to customer balance | OpsManager |
| POST | `/grow/spoilage-credits/{id}/reject` | Reject a credit | OpsManager |
| POST | `/grow/surplus-listings` | List harvest surplus for the farmers market | Grower |
| GET | `/grow/surplus-listings` | List surplus listings | Grower, OpsManager |
| GET | `/grow/surplus-listings/{id}` | Get a surplus listing | Grower, OpsManager |
| POST | `/grow/surplus-listings/{id}/sell` | Mark surplus sold at market | Grower |
| POST | `/grow/surplus-listings/{id}/withdraw` | Withdraw a surplus listing | Grower |
| POST | `/grow/_clock/set_current_utc` | Set the logical clock (drives cutoff lock and harvest scheduling) | OpsManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 where the guarded workflow lives; this table is only an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_VARIETY_NOT_FOUND` | 404 Not Found |
| `ERR_SEED_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_GERMINATION_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_CROP_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_TRAY_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_STANDING_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_STOP_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_TRIAL_NOT_FOUND` | 404 Not Found |
| `ERR_FOOD_SAFETY_NOT_APPROVED` | 409 Conflict |
| `ERR_SANITATION_NOT_LOGGED` | 409 Conflict |
| `ERR_SANITATION_FAILED` | 409 Conflict |
| `ERR_SEED_LOT_NOT_RELEASED` | 409 Conflict |
| `ERR_INSUFFICIENT_SEED` | 409 Conflict |
| `ERR_VARIETY_NOT_LISTED` | 409 Conflict |
| `ERR_WEEKLY_CHANGE_LOCKED` | 409 Conflict |
| `ERR_ORDER_NOT_EDITABLE` | 409 Conflict |
| `ERR_EMPTY_ORDER` | 409 Conflict |
| `ERR_EMPTY_ROUTE` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_BATCH_NOT_READY` | 409 Conflict |
| `ERR_CREDIT_EXCEEDS_DELIVERY` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TRIAL_CRITERIA_NOT_MET` | 409 Conflict |
| `ERR_VARIETY_IN_USE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
