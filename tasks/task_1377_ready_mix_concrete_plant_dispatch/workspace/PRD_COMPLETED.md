# Ready Mix Dispatch API — Product Requirements Document

## 1. Introduction

A ready-mix concrete plant lives and dies by the drum cycle. Orders arrive with a pour date, a pour window, and a slump requirement; the batch plant can only run one batch per cycle; trucks have finite drum capacity and a mandatory turnaround; cement prices move month to month and must be passed through under an escalation clause; and every yard discharged carries quality liability that is ultimately proven — or lost — on a set of test cylinders broken at seven and twenty-eight days. Coordinating this with phone calls and paper batch tickets produces double-booked batch slots, unbilled Saturday surcharges, short loads nobody priced, and arguments about who authorized the extra water that failed the twenty-eight-day break.

This document specifies a ready-mix concrete plant and dispatch platform covering the mix design catalog and admixture dosing, customer order intake with pour-window and slump constraints, truck dispatch and load rotation, on-site water additions and their strength-liability consequences, short-load / wait-time / Saturday surcharges, the batch ticket and QC cylinder chain of custody, returned concrete and washout, and monthly cement price escalation. The system is built for six distinct operator roles — customers, dispatchers, batch-plant operators, drivers, QC technicians, and plant managers — with strict segregation of duties on the quality-control chain.

All financial amounts are integer cents. All timestamps read a single server-side logical clock rather than wall-clock time, so that pour dates, break ages, batch intervals, and index-month selections are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role the server does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Separately, customer-scoped reads and writes are ownership-checked: when a `Customer` acts on an order or invoice, the `X-User-ID` must equal the `customer_id` recorded on that resource, otherwise the request is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). This ownership rule applies to reading a single order, cancelling an order, reading a single invoice, disputing an invoice, and paying an invoice.

The platform recognizes exactly six roles, spelled as follows: `Customer`, `Dispatcher`, `BatchOperator`, `Driver`, `QCTech`, `PlantManager`.

Role identity semantics differ by role and are normative:

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record. Placing an order stamps the order's `customer_id` from this header, and every ownership check on orders and invoices compares the resource's `customer_id` to `X-User-ID`.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- When `X-User-Role` is `BatchOperator`, `X-User-ID` is an opaque operator identifier; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `Driver`, `X-User-ID` is an opaque operator identifier. The server records it as `added_by_user_id` on each water addition the driver records, but does not compare it to any entity's `id`.
- When `X-User-Role` is `QCTech`, `X-User-ID` is an opaque operator identifier, but it is load-bearing for segregation of duties: the server records it as `cast_by_user_id` when a cylinder set is cast, as `seven_day_recorded_by` or `final_recorded_by` when a break is recorded, and as `certified_by_user_id` when a set is certified, and it enforces exactly the distinctness rules pinned in §3.8 — each break recorder must differ from the caster, and the certifier must differ from the caster and the twenty-eight-day recorder; the seven-day recorder is not barred from also recording the twenty-eight-day break or from later certifying the set.
- When `X-User-Role` is `PlantManager`, `X-User-ID` is an opaque operator identifier; the server does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. Unlike the business timestamps of §2.4, it is generated from the server's wall clock, not the logical clock.
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

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Results are sorted by `created_at` ascending, with ties broken by `id` ascending. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object: `total_count` is the number of records matching the endpoint's filters before pagination, and `has_more` is true if and only if `offset` plus the number of returned items is less than `total_count`. Two single-parent sub-resource reads do not paginate: `GET /v1/loads/{id}/batch-ticket` and `GET /v1/loads/{id}/return-record` ignore any `limit`/`offset` parameters and always report `limit` 10 and `offset` 0 in `meta`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources carry four system-managed fields: `id` (a server-minted UUID with no type prefix), `created_at` (ISO 8601 UTC timestamp with three fractional digits, set at creation), `updated_at` (same format, refreshed on every mutation), and `version` (an integer that starts at 1 at creation and increments on every mutation of the resource). Two resource types are deliberately lighter: cement price index rows and batch tickets carry only `id` and `created_at` — both `updated_at` and `version` are absent on these two resources, and neither can ever be mutated after creation. Water additions are also append-only records; they carry `id`, `created_at`, and `added_at`, with `created_at` and `added_at` stamped identically from the logical clock, and `updated_at` and `version` absent.

All timestamps in the system — pour-date comparisons, batch times, arrival and completion times, break-age checks, index-month selection — read a single server-side logical clock. Before any operator touches it, this clock reads exactly 2026-08-01T00:00:00Z. A plant-manager-only capability sets the clock to a supplied `to_iso8601` instant; the clock never falls back to wall-clock time. An unparseable `to_iso8601` value is rejected with `ERR_VALIDATION` (HTTP 400). The clock endpoint returns the current logical time as `current_utc`.

### 2.5. Plants, Batch Intervals, and Truck Turnaround

A plant is created with a `name` (a string), a `batch_cycle_minutes` value (an integer), and a `daily_capacity_yd3` value (a number), and starts in `ACTIVE` status (plants also support a `DOWN` status). The `batch_cycle_minutes` value defines the half-open batch interval occupied by any batched load: the interval runs from the load's `batch_time` up to but not including `batch_time` plus `batch_cycle_minutes`. No two loads on the same plant whose status is one of `BATCHED`, `EN_ROUTE`, `ON_SITE`, or `POURING` may have overlapping batch intervals; because the interval is half-open, one load's interval may begin exactly when another's ends — adjacency is allowed. A violating batch request is rejected with `ERR_PLANT_BATCH_CONFLICT` (HTTP 409).

Trucks have their own spacing rule. A truck's `batch_time` for a new load must be at least 90 minutes after the latest `batch_time` among that truck's non-cancelled loads. This is a closed interval: a batch exactly 90 minutes after the previous one is allowed. A violation is rejected with `ERR_TRUCK_OVERLAP` (HTTP 409).

### 2.6. Precision, Rounding, and Money

All monetary amounts are integer cents (0 decimal places). Wherever a calculation produces a monetary amount, the result is rounded half-up to a whole cent. Batch weights are rounded half-up to the whole pound; admixture doses are rounded half-up to 0.1 ounce; the water/cement ratio is rounded half-up to 3 decimal places; delivered quantities are carried at 1 decimal place; strengths are integer psi. Rounding is always round-half-up, never banker's rounding, and never truncation.

Several calculations are pinned to a specific evaluation order — round each line first, then sum — because the alternative order (sum first, then round) yields different results. These order-pinned calculations are called out where they occur in §3.

### 2.7. Optimistic Concurrency Control

Two write operations carry a mandatory expected-version field, and only these two:

- Creating a price list always requires `expected_plant_version` (an integer, absent or non-integer values are rejected with `ERR_VALIDATION`), carrying the client's last observed `version` of the target plant. The comparison is enforced only when `activate` is set to true: if the plant's current `version` no longer equals the supplied value — because, for example, another price list was activated against the same plant in the meantime — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). When `activate` is not true, the field must still be present but is not compared.
- Scheduling a load onto an order requires `expected_order_version`, carrying the client's last observed `version` of the order. Scheduling legitimately succeeds many times against the same confirmed order, and each successful schedule bumps the order's `version`; a request whose `expected_order_version` no longer matches the order's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because the writer's view of the rotation is stale.

No other endpoint takes a version field.

### 2.8. Validation Ordering

When a request violates several rules, the server reports the first violation in a fixed priority order. Authentication (missing or unrecognized headers, `ERR_UNAUTHENTICATED`) is checked first, followed by role permission (`ERR_FORBIDDEN`) and customer ownership (`ERR_OWNERSHIP_MISMATCH`). Referenced-resource existence (`ERR_NOT_FOUND`) and basic request shape — missing required fields, wrong types, out-of-range enum values, uniqueness violations (`ERR_VALIDATION`) — come next. State-level checks follow, in this order: the terminal-state check (`ERR_ALREADY_TERMINAL`), the from-state validity check (`ERR_INVALID_STATE`), and the optimistic-concurrency check (`ERR_STALE_VERSION`). Only then are business rules evaluated: safety rules such as segregation of duties and the batch w/c ceiling; referential rules such as mix-active, price-list-unique, slump tolerance, and index-month uniqueness; temporal rules such as window ordering, pour-date, break-age, batch-interval, and truck-turnaround; capacity and quantity constraints; and finally fiscal rules such as credit hold and payment-amount matching.

### 2.9. Credit Exposure

Every customer carries a `credit_limit_cents`, a derived `credit_exposure_cents` (starting at 0), and a derived `credit_status` of `GOOD` or `HOLD`. Exposure is forward-looking: it is the sum of `provisional_total_cents` over the customer's orders whose `delivery_status` is `CONFIRMED`, `SCHEDULED`, or `IN_PROGRESS`, plus the sum of `total_cents` over the customer's invoices whose status is `DRAFT`, `ISSUED`, or `DISPUTED`. Paid and void invoices drop out of exposure; placed and cancelled orders never enter it. The customer is on `HOLD` if and only if the exposure is greater than or equal to `credit_limit_cents` — exact equality puts the customer on hold. Exposure is recomputed, and `credit_status` re-derived, on every event that can change it: order confirmation, invoice auto-creation (including the recomputation run at every load completion), invoice adjustment, invoice payment, order cancellation, and on an explicit plant-manager credit review. A customer also declares `short_load_allowed` (defaulting to true), which governs whether loads below the price list's minimum may be scheduled for them.

## 3. Business Logic & Workflows

### 3.1. Catalog Setup: Mix Designs, Admixtures, and Slump

Before any concrete moves, a `PlantManager` builds the catalog. A mix design is created in `DRAFT` status with the owning `plant_id`, a `code` that must be unique within that plant across designs of every status, including `RETIRED` (a duplicate code is rejected with `ERR_VALIDATION`), a human-readable `name`, the specified 28-day compressive strength `design_strength_psi`, the design `slump_in` in inches, the `cement_content_lb_per_yd3`, the `design_wc_ratio` batched at the plant, the absolute legal ceiling `max_wc_ratio` that includes all on-site water, and an `admixtures` array — which may be omitted and then defaults to an empty array — whose entries each pair an `admixture_code` with a `dose_oz_per_cwt`. Activation by a `PlantManager` moves a design `DRAFT → ACTIVE`; retirement moves it `ACTIVE → RETIRED`, and `RETIRED` is terminal — a retired design can never return. Only an `ACTIVE` design may be confirmed onto an order or batched into a load — either attempt against a non-active design is rejected with `ERR_MIX_NOT_ACTIVE` (HTTP 409).

When a customer places an order, the ordered `slump_in` must lie within plus or minus 1.0 inch of the mix design's `slump_in`, inclusive; an order outside that band is rejected with `ERR_SLUMP_OUT_OF_TOLERANCE` (HTTP 422).

### 3.2. Pricing: Price Lists, Escalation Indices, and the Escalation Ratio

A price list attaches commercial terms to a (plant, mix design) pair; any existing plant and any existing mix design may be paired — the mix design is not required to belong to the plant. Its fields are the `base_price_per_yd3_cents`, the `escalation_base_index_points` baseline for the escalation ratio, the `min_load_yd3` threshold, the flat `short_load_fee_cents`, the `wait_free_minutes` allowance, the `wait_rate_per_minute_cents`, the `wait_fee_cap_cents`, and the `saturday_surcharge_pct` (a fraction such as 0.10). A price list is created either in `DRAFT` — carrying `activated_at` null — or, when created with `activate` set to true, directly in `ACTIVE` with `activated_at` stamped from the logical clock. Activation is a superseding event: any prior price list in `ACTIVE` for the same (`plant_id`, `mix_design_id`) transitions `ACTIVE → SUPERSEDED` at that moment, and the plant's `version` increments by 1. `SUPERSEDED` is terminal for a price list. Because activation changes which list is active for the pair, it is guarded by `expected_plant_version` as described in §2.7. Orders already confirmed keep their pinned `price_list_id`; superseding never re-prices a confirmed order.

Cement price indices are published monthly and are append-only. Each row records a `plant_id`, an `effective_month` in YYYY-MM form, and the published `index_points`. Publishing a second index for the same (`plant_id`, `effective_month`) is rejected with `ERR_INDEX_MONTH_DUPLICATE` (HTTP 409).

Escalation selects an index chronologically. For an order with a given `pour_date`, the applicable index is the `index_points` of the plant's index row with the greatest `effective_month` that is on or before the pour month. If no such row has been published, the escalation base itself stands in, making the ratio exactly 1.0. The escalated base price per cubic yard is the `base_price_per_yd3_cents` multiplied by the ratio of the selected index to `escalation_base_index_points`, rounded half-up to a whole cent.

### 3.3. Order Intake and Confirmation

A `Customer` places an order with a payload containing the `plant_id`, the `mix_design_id`, the ordered `qty_yd3`, the `pour_date` in YYYY-MM-DD form, the window endpoints `pour_window_start` and `pour_window_end` in 24-hour HH:MM form, and the ordered `slump_in`. The mix design is not required to belong to the named plant; both references must merely exist. The `customer_id` is stamped from the placing customer's `X-User-ID`, not from the payload; no `Customer` record is required to exist at placement time — the identifier is stored as given. The pour window must be well-formed: `pour_window_end` strictly after `pour_window_start`, otherwise `ERR_ORDER_WINDOW_INVALID` (HTTP 422). The `pour_date` must not be before the current logical-clock date, otherwise `ERR_POUR_DATE_PAST` (HTTP 422). A new order is born with `delivery_status` `PLACED` and `billing_status` `UNPRICED`; these two dimensions are parallel and evolve independently — delivery runs `PLACED | CONFIRMED | SCHEDULED | IN_PROGRESS | DELIVERED | CANCELLED`, with `DELIVERED` and `CANCELLED` terminal, while billing runs `UNPRICED | PRICED | INVOICED | DISPUTED | PAID | VOID`, with `PRICED`, `INVOICED`, `DISPUTED`, and `PAID` reached as billing milestones in §3.9.

Confirmation is a `Dispatcher` action and is where pricing locks in. Only a `PLACED` order can be confirmed, and confirming enforces four further preconditions. After the state-level checks of §2.8, they are evaluated in exactly this order, notwithstanding the generic business-rule ordering of §2.8: the order's customer record must exist (`ERR_NOT_FOUND`); the customer's `credit_status` must not be `HOLD` (otherwise `ERR_CREDIT_HOLD`, HTTP 402); the order's mix design must be `ACTIVE` (`ERR_MIX_NOT_ACTIVE`); exactly one price list in `ACTIVE` must exist for the order's (plant, mix design) pair (`ERR_PRICE_LIST_MISSING`, HTTP 409); and the `pour_date` must still be on or after the current logical date (`ERR_POUR_DATE_PAST`). On success the order moves `PLACED → CONFIRMED`, its `version` increments, `billing_status` moves `UNPRICED → PRICED`, the order pins `price_list_id` to that active list for good, and the customer's exposure is recomputed (§2.9).

Confirmation also computes the provisional quote — the PROVISIONAL variant of the per-load final charge calculation. The escalated base is computed as in §3.2 except that the index month is the greatest `effective_month` on or before the month of the confirmation date. The concrete line uses the ordered `qty_yd3` rather than any discharged quantity; the wait line and the short-load line are both zero at this stage; the Saturday surcharge still applies when the `pour_date` falls on a Saturday, computed on the concrete line alone (there is no short-load line to include). The resulting escalated base is stored as `escalated_base_cents` and the quote total as `provisional_total_cents`; both remain null until the order is confirmed.

Cancelling an order is available to the owning `Customer` or a `Dispatcher`. Cancelling from `PLACED` is unconditional and moves billing `UNPRICED → VOID`. Cancelling from `CONFIRMED`, `SCHEDULED`, or `IN_PROGRESS` is blocked while any load of the order sits in `SCHEDULED`, `BATCHED`, `EN_ROUTE`, `ON_SITE`, or `POURING` — the rejection is `ERR_ORDER_HAS_ACTIVE_LOADS` (HTTP 409). When such a cancel succeeds, billing moves `PRICED → VOID` (the provisional pricing is voided as compensation), the customer's exposure is recomputed, and `credit_status` returns to `GOOD` if and only if the exposure is now strictly below `credit_limit_cents`. If the order's invoice is still in `DRAFT` when the order is cancelled, that invoice automatically moves `DRAFT → VOID`.

### 3.4. Scheduling Loads and the Truck Selector

With an order confirmed, a `Dispatcher` builds the rotation. Scheduling a load onto an order requires the order's `delivery_status` to be one of `CONFIRMED`, `SCHEDULED`, or `IN_PROGRESS`, and the request carries `qty_yd3`, the OCC field `expected_order_version` (§2.7), and optionally a `truck_id`. The load's `order_id` comes from the scheduling path, and its `plant_id` is denormalized from the order's plant at schedule time. Each successful schedule increments the order's `version` by 1 — which is exactly what makes a stale `expected_order_version` detectable on the next schedule.

Four quantity and availability constraints guard scheduling. If a `truck_id` is given, that truck must currently be `AVAILABLE`, otherwise `ERR_TRUCK_NOT_AVAILABLE` (HTTP 409); an explicitly supplied truck is not required to belong to the order's plant. The load's `qty_yd3` must not exceed the truck's `capacity_yd3`, otherwise `ERR_TRUCK_CAPACITY_EXCEEDED` (HTTP 422). If the load's `qty_yd3` is below the pinned price list's `min_load_yd3` and the customer's `short_load_allowed` is false, the schedule is rejected with `ERR_SHORT_LOAD_FORBIDDEN` (HTTP 422); when `short_load_allowed` is true, such a load schedules fine and will simply incur the short-load fee at completion.

When `truck_id` is omitted, the selector runs. Candidates are trucks of the order's plant that are `AVAILABLE` and whose `capacity_yd3` is at least the requested `qty_yd3`. Candidates are ranked by `last_available_at` ascending — longest-idle first — with ties broken by `created_at` ascending and any remaining ties broken by `id` ascending. `last_available_at` is stamped from the logical clock at truck creation, so it is never null. An empty candidate set is rejected with `ERR_NO_TRUCK_AVAILABLE` (HTTP 409). A truck is registered by a `Dispatcher` with its `plant_id`, a `fleet_number` unique within the plant, and its drum `capacity_yd3`; its `status` starts at `AVAILABLE`. The dispatcher may move a truck `AVAILABLE → OUT_OF_SERVICE` and back `OUT_OF_SERVICE → AVAILABLE`, the latter re-stamping `last_available_at`; while `OUT_OF_SERVICE` the truck is never selected or batchable. The remaining truck transitions — `AVAILABLE → ON_DELIVERY` at batch, `ON_DELIVERY → AVAILABLE` at completion, `ON_DELIVERY → IN_WASHOUT` at return, and `IN_WASHOUT → AVAILABLE` at washout — are system-driven by the load lifecycle in §3.5 through §3.7, with `ON_DELIVERY` covering the whole batched-but-not-closed interval and `IN_WASHOUT` holding the truck out of the selector until washout records it back to `AVAILABLE`.

The first successful schedule on an order moves the order `CONFIRMED → SCHEDULED` automatically. A scheduled load can be cancelled by a `Dispatcher` while still in `SCHEDULED`, moving it to `CANCELLED`.

### 3.5. Batching, the Batch Ticket, and Plant Safety Interlocks

Batching is a `BatchOperator` action that turns a `SCHEDULED` load into a `BATCHED` one and cuts its batch ticket. The batch request may specify an explicit `batch_time`; otherwise the current logical-clock time is used. It may also request `extra_batch_water_gal` — extra batch water added at the plant, defaulting to 0.

Batching enforces a stack of interlocks, evaluated before the optional `batch_time` payload value itself is validated (so a malformed `batch_time` on a load failing an interlock yields the interlock's error, not `ERR_VALIDATION`). The parent order must be in `SCHEDULED` or `IN_PROGRESS`. The mix design must still be `ACTIVE` (`ERR_MIX_NOT_ACTIVE`). The assigned truck must be `AVAILABLE` (`ERR_TRUCK_NOT_AVAILABLE`). The plant batch interval and truck turnaround rules of §2.5 apply, rejecting with `ERR_PLANT_BATCH_CONFLICT` and `ERR_TRUCK_OVERLAP` respectively. And the water/cement safety ceiling is checked up front, using the ticket's rounded weights (§3.5's pinned order below): the rounded `batch_water_lb` — the rounded base batch water plus the requested extra water converted at 8.34 pounds per gallon and rounded to 0.1 pound — divided by the rounded `cement_lb`, compared unrounded, must not exceed the mix's `max_wc_ratio`; a batch that would push the ratio above the ceiling is rejected with `ERR_WC_RATIO_EXCEEDED` (HTTP 422).

On success the batch ticket is created — one ticket per load, 1:1, its `load_id` pointing back at the load — and the ticket's `ticket_number` is sequential per plant: the count of existing tickets for that plant plus one. The ticket's weights are computed in a pinned order. First, `cement_lb` is the mix's `cement_content_lb_per_yd3` multiplied by the load's `qty_yd3`, rounded half-up to the whole pound. Second, the base batch water is the `design_wc_ratio` multiplied by `cement_lb`, rounded half-up to the whole pound. Third, the extra water in pounds is 8.34 multiplied by `extra_batch_water_gal`, rounded half-up to 0.1 pound. The ticket's `batch_water_lb` is the base batch water plus the extra water pounds, and `extra_batch_water_gal` is echoed onto the ticket from the batch input. Each admixture line of the mix is dosed individually: the line's `dose_oz_per_cwt` multiplied by `cement_lb` and divided by 100, rounded half-up to 0.1 ounce, producing the ticket's `admixture_doses` entries, each an object carrying `admixture_code` and `dose_oz`. The ticket's `total_admixture_oz` is the sum of those per-line rounded doses — round per line first, then sum. Summing the raw doses and rounding once at the end is explicitly the wrong order and yields different totals.

Batching stamps the load's `batch_time`, computes the load's initial `actual_wc_ratio` from the batch water alone (see §3.6), and flips the truck `AVAILABLE → ON_DELIVERY`. If this is the order's first load to reach `BATCHED`, the order automatically moves `SCHEDULED → IN_PROGRESS`.

### 3.6. On the Road and On Site: Delivery Events, Water Additions, and Strength Liability

Once batched, the load belongs to the `Driver`. Departure moves it `BATCHED → EN_ROUTE`. Arrival moves it `EN_ROUTE → ON_SITE`, stamps `arrival_time` from the logical clock, and starts the wait-time meter. Beginning the discharge moves it `ON_SITE → POURING`. A scheduled load cancelled before batching goes `SCHEDULED → CANCELLED`.

While the load is `ON_SITE` or `POURING`, the driver may record water added on site; recording against a load in any other non-terminal state is rejected with `ERR_INVALID_STATE` (HTTP 409), and recording against a load in a terminal state (`COMPLETED`, `WASHED_OUT`, or `CANCELLED`) is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). Each addition carries the `gallons` added and a `customer_authorized` flag, and the server stamps `added_by_user_id` from the driver's `X-User-ID` and `added_at` from the logical clock. Every addition recomputes the load's `actual_wc_ratio`: the total water is the batch ticket's `batch_water_lb` plus 8.34 times the sum of `gallons` across all of the load's water additions, and the ratio is that total divided by the ticket's `cement_lb`, rounded half-up to 3 decimal places. The load's `over_watered` flag becomes true if and only if this rounded 3-decimal ratio is strictly greater than the mix's `max_wc_ratio` — a ratio that rounds to exactly the ceiling is not over-watered.

The moment `over_watered` flips to true, two cascades fire. The load's `strength_liability` is set: it becomes `CUSTOMER` if any water addition on the load has `customer_authorized` set to true, and `PLANT` otherwise. And every non-terminal cylinder set cast from that load has its `acceptance_basis` flipped from `DESIGN_BASIS` to `AS_PLACED`. The liability assignment is re-derived on every further water addition recorded while the load remains over-watered, so a later customer-authorized addition moves an already-over-watered load's `strength_liability` from `PLANT` to `CUSTOMER`. The load's `strength_liability` starts at `NONE` and is otherwise only set by a flagged certification (§3.8).

### 3.7. Completing, Returning, and Washing Out a Load

Completion is the money moment. Completing a load from `ON_SITE` or `POURING` requires full discharge: the supplied `discharged_qty_yd3` must equal the load's batched `qty_yd3` exactly, otherwise `ERR_VOLUME_NOT_CONSERVED` (HTTP 422); a partial discharge must go through the return flow instead. Completion stamps `complete_time` and derives `on_site_minutes` as the elapsed seconds between `arrival_time` and `complete_time` divided by 60 and rounded down to the whole minute.

Completion then runs the FINAL variant of the per-load charge calculation, in this pinned order. The escalated base `escalated_base_cents` is recomputed from the pinned price list and the pour month's index (§3.2). The concrete line `concrete_cents` is `discharged_qty_yd3` multiplied by that escalated base, rounded half-up to the whole cent. The short-load line `short_load_fee_cents` is the price list's flat fee when `discharged_qty_yd3` is strictly below `min_load_yd3`, and zero otherwise. The billable wait is the greater of zero and `on_site_minutes` minus `wait_free_minutes`; the wait line `wait_fee_cents` is that billable wait multiplied by `wait_rate_per_minute_cents`, capped at `wait_fee_cap_cents` — the smaller of the two values is charged. The Saturday line `saturday_fee_cents` applies only when the order's `pour_date` falls on a Saturday: it is the sum of the concrete line and the short-load line, multiplied by `saturday_surcharge_pct`, rounded half-up to the whole cent — the wait fee is deliberately excluded from the surcharge base. The load's `final_charge_cents` is the sum of the four lines, each already individually rounded — round per line, then sum. All five charge fields remain null until completion.

Completion's cascade then fans out. The truck returns `ON_DELIVERY → AVAILABLE` with `last_available_at` stamped. The order's `delivered_qty_yd3` is recomputed as the sum of `discharged_qty_yd3` over the order's loads in `COMPLETED` (returned, washed-out, and cancelled loads contribute nothing), and when that delivered total reaches or exceeds the ordered `qty_yd3` — exact equality completes the order — the order moves automatically to `DELIVERED`, from either `SCHEDULED` or `IN_PROGRESS`. Reaching `DELIVERED` auto-creates the order's invoice in `DRAFT` with one `LOAD` line item per completed load priced at that load's `final_charge_cents`, the invoice's `total_cents` being exactly the sum of its line items' `amount_cents`. Finally, the customer's exposure is recomputed (§2.9), putting the customer on `HOLD` if the exposure has reached `credit_limit_cents`.

The return flow handles concrete coming back to the plant. From `BATCHED`, `EN_ROUTE`, `ON_SITE`, or `POURING`, the driver may return the load, supplying `discharged_qty_yd3`, `returned_qty_yd3`, and a `disposition` of `DUMPED`, `RECYCLED`, or `FILL`. The returned quantity must be greater than zero, and volume must be conserved exactly: discharged plus returned must equal the batched `qty_yd3`, otherwise `ERR_VOLUME_NOT_CONSERVED`. The load moves to `RETURNED`, its `discharged_qty_yd3` is set from the input, a return record is created carrying the `returned_qty_yd3` and `disposition`, and the truck moves `ON_DELIVERY → IN_WASHOUT`. Washout is a `BatchOperator` action on the returned load: the load moves `RETURNED → WASHED_OUT`, the supplied `washout_water_gal` is recorded onto the return record (null until then), and the truck returns `IN_WASHOUT → AVAILABLE` with `last_available_at` stamped. `COMPLETED`, `WASHED_OUT`, and `CANCELLED` are the load's terminal states. Note that a returned load does not run the final-charge calculation and does not contribute to `delivered_qty_yd3`.

### 3.8. Quality Control: Cylinder Sets, Breaks, Certification, and Liability

A `QCTech` casts a cylinder set from a load while the load is `ON_SITE`, `POURING`, or `COMPLETED` — casting against any other non-terminal load state is rejected with `ERR_INVALID_STATE`, and casting against a `WASHED_OUT` or `CANCELLED` load is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). The request carries `num_cylinders` (required to be an integer; no range or positivity constraint is applied); the set is created in `CURING` with `cast_by_user_id` stamped from the technician's `X-User-ID`, `cast_at` stamped from the logical clock, and `required_strength_psi` fixed at the mix's `design_strength_psi`. The set's `acceptance_basis` starts at `AS_PLACED` when the load is already over-watered at cast time, and at `DESIGN_BASIS` otherwise, flipping to `AS_PLACED` if the load later becomes over-watered (§3.6).

Breaks are recorded in sequence with segregation of duties at every step. Recording a seven-day break (break type `SEVEN_DAY`) requires the current logical time to be at least 7 days after `cast_at`, and the recorder must not be the set's `cast_by_user_id`; a too-early break is rejected with `ERR_BREAK_TOO_EARLY` (HTTP 422) and a same-person break with `ERR_SOD_VIOLATION` (HTTP 403). Within a break request these checks are evaluated in this order, notwithstanding the generic safety-before-temporal ordering of §2.8: state validity (`ERR_ALREADY_TERMINAL`, then `ERR_INVALID_STATE`), then break age, then segregation of duties — so a too-early break recorded by the caster yields `ERR_BREAK_TOO_EARLY`, not `ERR_SOD_VIOLATION`. Success moves the set `CURING → SEVEN_DAY_RECORDED`, storing the supplied `strength_psi` as `seven_day_strength_psi` and the recorder as `seven_day_recorded_by`. Recording the twenty-eight-day break (break type `TWENTY_EIGHT_DAY`) requires the logical time to be at least 28 days after `cast_at` and again forbids the caster from recording — only the caster is excluded at either break, so the seven-day recorder may also record the twenty-eight-day break; success moves the set from `SEVEN_DAY_RECORDED` to `FINAL_RECORDED`, storing `final_strength_psi` and `final_recorded_by`. The break request carries `break_type` (one of `SEVEN_DAY` or `TWENTY_EIGHT_DAY`) together with the measured `strength_psi`.

Certification is the verdict. A `QCTech` — who must be neither the caster nor the twenty-eight-day recorder, otherwise `ERR_SOD_VIOLATION` — certifies a `FINAL_RECORDED` set. The load the set was cast from must be `COMPLETED`; certifying against a load in any other state is rejected with `ERR_INVALID_STATE`. The acceptance test itself is the same under both bases: `acceptance_passed` is true if and only if `final_strength_psi` is greater than or equal to `required_strength_psi`. On a pass the set moves to `CERTIFIED`. On a failure the set moves to `FLAGGED`, and liability is assigned per the acceptance basis: under `DESIGN_BASIS` the load's `strength_liability` becomes `PLANT`; under `AS_PLACED` it becomes `CUSTOMER` if any water addition on the load was customer-authorized, and `PLANT` otherwise. Either way, the certifier is recorded as `certified_by_user_id`. `CERTIFIED` and `FLAGGED` are terminal.

### 3.9. Billing: Invoices, Disputes, Adjustments, and Payment

Invoices are born automatically in `DRAFT` when an order reaches `DELIVERED`, carrying the `order_id`, the `customer_id` denormalized from the order, and a `line_items` array of entries each with a `kind`, a `description` of the form `Load {load_id}`, and an `amount_cents` — one `LOAD` line per completed load at that load's `final_charge_cents`, with the lines ordered by the completed loads' `created_at` ascending. The invariant `total_cents` equals the sum of the line items' `amount_cents` holds at all times. `issued_at` is null while the invoice is in `DRAFT`.

A `PlantManager` issues a draft invoice, stamping `issued_at` from the logical clock and moving the invoice `DRAFT → ISSUED`; the order's `billing_status` follows `PRICED → INVOICED`. The owning `Customer` may then dispute an issued invoice — optionally supplying a `reason`, which is accepted but not persisted on the invoice — moving it `ISSUED → DISPUTED` and the order's billing `INVOICED → DISPUTED`. A `PlantManager` resolves a dispute by adjusting the invoice with a non-empty `adjustment_lines` array (an empty array is rejected with `ERR_VALIDATION`, HTTP 400); each adjustment line must be an object carrying an integer `amount_cents` — a line failing this is rejected with `ERR_VALIDATION` — and no other field, such as `kind` or `description`, is required on adjustment lines; the adjustment lines are appended to `line_items` as supplied, the new `total_cents` equals the old total plus the sum of the adjustment amounts, the invoice returns `DISPUTED → ISSUED`, and the order's billing follows `DISPUTED → INVOICED`. Adjustment also recomputes the customer's exposure, setting `HOLD` if exposure has reached the limit and `GOOD` otherwise.

Payment is exact-change only: the owning `Customer` pays an issued invoice by supplying `amount_cents`, which must equal the invoice's `total_cents` exactly, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A successful payment moves the invoice `ISSUED → PAID` and the order's billing `INVOICED → PAID`; the paid invoice drops out of the exposure sum, exposure is recomputed, and `credit_status` returns to `GOOD` if and only if the remaining exposure is strictly below `credit_limit_cents`. `PAID` and `VOID` are terminal for an invoice, just as `PAID` and `VOID` are terminal for the billing dimension.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; operations that modify an existing resource (including all state-transition actions) return HTTP 200; reads return HTTP 200. All resources are mounted under the `/v1` prefix.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /v1/plants | Create a plant | PlantManager |
| GET | /v1/plants/{id} | Get a plant | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/mix-designs | Create a mix design (DRAFT) | PlantManager |
| GET | /v1/mix-designs/{id} | Get a mix design | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/mix-designs | List mix designs (`plant_id?`, `status?`) | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/mix-designs/{id}/activate | Activate a mix design | PlantManager |
| POST | /v1/mix-designs/{id}/retire | Retire a mix design | PlantManager |
| POST | /v1/price-lists | Create a price list; `activate=true` activates and supersedes the prior ACTIVE list for the pair | PlantManager |
| GET | /v1/price-lists/{id} | Get a price list | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/price-lists | List price lists (`plant_id?`, `mix_design_id?`, `status?`) | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/cement-price-indices | Publish a monthly cement price index | PlantManager |
| GET | /v1/cement-price-indices/{id} | Get an index row | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/cement-price-indices | List index rows (`plant_id?`, `effective_month?`) | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/customers | Create a customer (credit GOOD, exposure 0) | PlantManager |
| GET | /v1/customers/{id} | Get a customer | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/customers/{id}/credit-review | Recompute the customer's credit exposure and status | PlantManager |
| POST | /v1/trucks | Create a truck (AVAILABLE) | Dispatcher |
| GET | /v1/trucks/{id} | Get a truck | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/trucks | List trucks (`plant_id?`, `status?`) | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/trucks/{id}/out-of-service | Take a truck out of service | Dispatcher |
| POST | /v1/trucks/{id}/return-to-service | Return a truck to service | Dispatcher |
| POST | /v1/orders | Place an order; `customer_id` taken from `X-User-ID` | Customer |
| GET | /v1/orders/{id} | Get an order | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/orders | List orders (`customer_id?`, `plant_id?`, `mix_design_id?`, `price_list_id?`, `delivery_status?`, `billing_status?`) | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/orders/{id}/confirm | Confirm an order: pins the ACTIVE price list and computes the provisional quote | Dispatcher |
| POST | /v1/orders/{id}/cancel | Cancel an order (blocked while it has active loads) | Customer, Dispatcher |
| POST | /v1/orders/{id}/loads | Schedule a load; truck auto-selected when `truck_id` omitted | Dispatcher |
| GET | /v1/loads/{id} | Get a load | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/loads | List loads (`order_id?`, `truck_id?`, `plant_id?`, `status?`) | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/loads/{id}/batch | Batch the load; creates the batch ticket | BatchOperator |
| POST | /v1/loads/{id}/depart | Truck departs the plant | Driver |
| POST | /v1/loads/{id}/arrive | Truck arrives on site; starts wait metering | Driver |
| POST | /v1/loads/{id}/start-pour | Begin discharge | Driver |
| POST | /v1/loads/{id}/complete | Complete discharge; final charge; fulfillment cascade | Driver |
| POST | /v1/loads/{id}/cancel | Cancel a SCHEDULED load | Dispatcher |
| POST | /v1/loads/{id}/return | Return concrete to the plant; enforces volume conservation | Driver |
| POST | /v1/loads/{id}/washout | Record washout of a returned load | BatchOperator |
| POST | /v1/loads/{id}/water-additions | Record water added on site; recomputes actual w/c and the liability cascade | Driver |
| GET | /v1/loads/{id}/water-additions | List water additions of a load | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/loads/{id}/batch-ticket | Get the batch ticket of a load (array of 0–1) | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/loads/{id}/cylinder-sets | Cast a QC cylinder set from a load | QCTech |
| GET | /v1/cylinder-sets/{id} | Get a cylinder set | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/loads/{id}/cylinder-sets | List cylinder sets of a load | QCTech, PlantManager, Dispatcher, BatchOperator, Driver, Customer |
| POST | /v1/cylinder-sets/{id}/breaks | Record a 7-day or 28-day break result | QCTech |
| POST | /v1/cylinder-sets/{id}/certify | Certify the set; pass → CERTIFIED, fail → FLAGGED | QCTech |
| GET | /v1/loads/{id}/return-record | Get the return record of a load (array of 0–1) | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/invoices/{id} | Get an invoice | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| GET | /v1/invoices | List invoices (`order_id?`, `customer_id?`, `status?`) | PlantManager, Dispatcher, BatchOperator, Driver, QCTech, Customer |
| POST | /v1/invoices/{id}/issue | Issue a DRAFT invoice | PlantManager |
| POST | /v1/invoices/{id}/dispute | Customer disputes an issued invoice | Customer |
| POST | /v1/invoices/{id}/adjust | Adjust a disputed invoice with compensating lines; returns it to ISSUED | PlantManager |
| POST | /v1/invoices/{id}/pay | Pay an issued invoice; amount must equal the total exactly | Customer |
| POST | /v1/_clock/set_current_utc | Set the server's logical clock | PlantManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_OWNERSHIP_MISMATCH | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_WC_RATIO_EXCEEDED | 422 |
| ERR_MIX_NOT_ACTIVE | 409 |
| ERR_PRICE_LIST_MISSING | 409 |
| ERR_SLUMP_OUT_OF_TOLERANCE | 422 |
| ERR_ORDER_WINDOW_INVALID | 422 |
| ERR_POUR_DATE_PAST | 422 |
| ERR_BREAK_TOO_EARLY | 422 |
| ERR_PLANT_BATCH_CONFLICT | 409 |
| ERR_TRUCK_OVERLAP | 409 |
| ERR_TRUCK_NOT_AVAILABLE | 409 |
| ERR_NO_TRUCK_AVAILABLE | 409 |
| ERR_TRUCK_CAPACITY_EXCEEDED | 422 |
| ERR_SHORT_LOAD_FORBIDDEN | 422 |
| ERR_VOLUME_NOT_CONSERVED | 422 |
| ERR_INDEX_MONTH_DUPLICATE | 409 |
| ERR_ORDER_HAS_ACTIVE_LOADS | 409 |
| ERR_CREDIT_HOLD | 402 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
