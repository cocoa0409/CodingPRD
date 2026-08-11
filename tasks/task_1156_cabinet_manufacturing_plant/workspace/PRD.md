# Cabinet Manufacturing Plant (KCMA) API — Product Requirements Document

## 1. Introduction

A cabinet manufacturing plant operating under KCMA certification runs a tightly coupled shop floor: dealers place configured cabinet orders, engineers price and review dimensional modifications, the finish room mixes color batches and matches them against spectrophotometer tolerances, CNC nesting stations cut door blanks from sheet goods, assembly lines build cabinet boxes in scheduled sub-lots, and shipping consolidates finished orders onto cube-limited delivery routes. Each of these stations today coordinates through paper travelers and phone calls, which means a sheet-goods shortage discovered at the nesting saw reaches the dealer only days later, and a failed color match strands finished doors with no systematic path back into production.

This document specifies the REST API for the plant's unified operations platform, mounted under the `/kcma` path prefix. The platform manages the full order-to-delivery lifecycle: a dealer-facing catalog of door styles and finishes with network price levels, order capture with dual-variant pricing (a provisional quote at submission and a final settlement at dispatch), an engineering review loop for modification requests, finish batch management with Delta-E color quality control and sheen lot discipline, nesting run release with deterministic part generation and component reservation, assembly line balancing, an order hold system that automatically freezes orders when components run short or finish quality fails, a damage and replacement door program with warranty windows, and delivery route planning with freight consolidation. Six peer roles — plant administration, dealers, engineering, finish supervision, production planning, and shipping coordination — share read visibility across the floor while owning disjoint write verbs.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` does not name one of the declared roles below, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other processing.

The platform declares exactly six roles, spelled as follows: `PlantAdmin`, `Dealer`, `Engineer`, `FinishSupervisor`, `ProductionPlanner`, and `ShippingCoordinator`. Read access is shared — every role may call every retrieval endpoint — while each mutating capability belongs to exactly one role. A request whose authenticated role is not in the endpoint's permitted set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity resolves as follows. When `X-User-Role` is `Dealer`, `X-User-ID` is the `id` of the acting `Dealer` record; ownership checks on any resource that references a dealer compare the resource's dealer foreign key — an order's `dealer_id`, a claim's `dealer_id`, or the owning order's `dealer_id` for operations on lines and modification requests — against `X-User-ID`. A mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH` (HTTP 403); this applies to submitting and cancelling orders, adding lines, creating or resubmitting modification requests, and filing replacement claims against one's own orders. When `X-User-Role` is `PlantAdmin`, `Engineer`, `FinishSupervisor`, `ProductionPlanner`, or `ShippingCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`.

`PlantAdmin` owns plant administration: dealer registration and maintenance, catalog entries (door styles, finish specifications, components), nesting stations, assembly lines, claim adjudication, manual hold release, and the logical clock. `Dealer` places and manages its own orders, lines, modification requests, and replacement claims. `Engineer` reviews modification requests. `FinishSupervisor` runs the finish room: batches, QC recording, door line assignment, and remixing. `ProductionPlanner` receives component stock, creates and releases nesting runs, and schedules and completes sub-lots. `ShippingCoordinator` builds delivery routes, assigns orders, and locks and dispatches routes.

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

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Every list is sorted by `created_at` in ascending order.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Timestamps are ISO 8601 UTC values rendered with three fractional digits. `version` starts at 1 when the resource is created, increments by exactly 1 on every mutation of that resource, and `updated_at` refreshes to the mutation instant at the same time.

One entity deviates from this contract: generated `Part` records carry only `id` and `created_at`. A part is immutable once generated by a nesting run release, so `updated_at` and `version` are absent from part representations entirely.

### 2.5. Money, Precision, and Rounding Conventions

All monetary values are integer cents; no fractional cents exist anywhere in the system. Every rounding applied to a monetary value is round half up to whole cents. Two quantities are not monetary but carry fixed decimal precision: an order's shipping cube and derived cube figures are rounded half up to two decimal places, and a nesting run's utilization percentage is rounded half up to two decimal places.

Line-level pricing rounds per line before any summation: each line's net is rounded half up to integer cents individually, and order totals sum those already-rounded line values. Summing unrounded line values and rounding only the total is expressly forbidden, because the two strategies diverge on real orders.

### 2.6. The Logical Clock and Scheduling Dates

The server maintains a logical clock that is the sole source of "now" for every date- and time-sensitive rule: schedule-date validation, order `submitted_at` and `shipped_at` stamps, and warranty-window arithmetic all read this clock. At server startup the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time.

An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant (ISO 8601 UTC); monotonicity is not enforced, so tests may set explicit instants. The capability responds with the clock's new value under `current_utc`.

Any `scheduled_date` on a nesting run or sub-lot, and any `route_date` on a delivery route, that falls before the logical clock's current date is rejected with `ERR_SCHEDULE_DATE_IN_PAST` (HTTP 422). Dates equal to the current logical date are acceptable.

### 2.7. Validation Evaluation Order

When a single request violates several rules, the platform evaluates checks in a fixed priority order and surfaces only the first failure. From highest priority to lowest:

1. Header presence and role-name validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role permission for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Entity-backed ownership for dealer-scoped operations (`ERR_RESOURCE_OWNERSHIP_MISMATCH`).
4. Existence of path-templated resource ids, validated left to right along the URL; the first missing segment produces the corresponding not-found error (for example `ERR_ORDER_NOT_FOUND` before `ERR_ORDER_LINE_NOT_FOUND` on a nested path). The per-resource not-found errors are `ERR_DEALER_NOT_FOUND`, `ERR_DOOR_STYLE_NOT_FOUND`, `ERR_FINISH_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_ASSEMBLY_LINE_NOT_FOUND`, `ERR_SUB_LOT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, and `ERR_HOLD_NOT_FOUND`, each at HTTP 404.
5. Existence of foreign keys supplied in the request body (`door_style_id`, `finish_id`, `order_line_id`, `assembly_line_id`, `station_id`, `sheet_component_id`, `order_id`, `original_order_line_id`), each yielding the matching not-found error from the same catalogue.
6. Single-resource state preconditions — whether the target resource is in the state the operation requires (for example an order in `DRAFT` for line addition, modification creation, or submit; a batch in `MIXING` for assignment or QC recording; a route in `PLANNED` for assignment or locking).
7. Cross-entity state gates (`ERR_MODS_PENDING_REVIEW`, `ERR_ORDER_ON_HOLD`, `ERR_ORDERS_NOT_READY_TO_SHIP`).
8. Catalog and configuration resources being active (`ERR_DOOR_STYLE_INACTIVE`, `ERR_FINISH_INACTIVE`, `ERR_ASSEMBLY_LINE_INACTIVE`, `ERR_STATION_INACTIVE`).
9. Shape and type constraints (`ERR_WRONG_LINE_TYPE`, `ERR_COMPONENT_KIND_MISMATCH`, `ERR_CLAIM_LINE_NOT_ELIGIBLE`).
10. Batch-assignment compatibility, which itself always evaluates in this written order: finish match (`ERR_FINISH_MISMATCH`), then the sheen lot rule (`ERR_SHEEN_LOT_MISMATCH`), then batch capacity (`ERR_BATCH_CAPACITY_EXCEEDED`).
11. Temporal interval rules: sub-lot window overlap (`ERR_LINE_WINDOW_OVERLAP`), nesting station window overlap with changeover buffer (`ERR_STATION_WINDOW_OVERLAP`), aggregate line-day capacity (`ERR_LINE_CAPACITY_EXCEEDED`), and schedule dates in the past (`ERR_SCHEDULE_DATE_IN_PAST`).
12. The claim warranty window at adjudication (`ERR_CLAIM_WARRANTY_EXPIRED`).
13. Capacity and fiscal ceilings (`ERR_ROUTE_CUBE_EXCEEDED`, `ERR_DEALER_CREDIT_EXCEEDED`, `ERR_SUB_LOT_QTY_EXCEEDS_LINE`).
14. Field-level sanity, always evaluated last: required fields present (`ERR_VALIDATION`), enum values within their declared sets (`ERR_INVALID_ENUM`), quantities within their positive or non-negative ranges (`ERR_INVALID_QUANTITY`), time windows well formed (`ERR_INVALID_TIME_WINDOW`), and unique codes free of collision (`ERR_DUPLICATE_CODE`).

`ERR_VALIDATION` is therefore the lowest-priority check in the platform and fires only when no earlier rule has failed.

### 2.8. Optimistic Concurrency on Route Assignment

Exactly one write in the platform carries an optimistic concurrency check: assigning an order to a delivery route. The request must include `expected_order_version`, carrying the `version` of the order the client last observed. If the order's current `version` has advanced beyond that observed value — for example because the order was legitimately re-homed to a different route under the supersede rule, or because a submit or cancellation cascade bumped the version — the assignment is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). The version check is the only guard against acting on a stale view of the order; no other endpoint in the platform accepts a version field.

### 2.9. Order Posture: Lifecycle Status and Hold Status

An order's posture is two-dimensional. The primary lifecycle `status` walks `DRAFT` → `SUBMITTED` → `IN_PRODUCTION` → `READY_TO_SHIP` → `SHIPPED`, with `CANCELLED` reachable from `DRAFT` or `SUBMITTED`; both `SHIPPED` and `CANCELLED` are terminal. In parallel, the computed `hold_status` dimension reads `ON_HOLD` whenever at least one `OrderHold` in `PLACED` status references the order, and `NONE` otherwise.

The middle two lifecycle transitions are never invoked directly. Progression from `SUBMITTED` to `IN_PRODUCTION`, and from `IN_PRODUCTION` to `READY_TO_SHIP`, is auto-evaluated by the system after relevant shop-floor events — batch assignment, sub-lot creation, batch QC release, sub-lot completion, and hold release — and each auto-transition increments the order's `version` like any other mutation. While `hold_status` is `ON_HOLD`, both auto-transitions are gated: the order does not advance regardless of how complete its lines are, and the order also blocks route locking.

## 3. Business Logic & Workflows

### 3.1. Dealer Network and Catalog Administration

Plant administration begins with the dealer network. Registering a dealer captures the company `name`, a `dealer_code` that must be unique across all dealers, the dealer's network `price_level` (one of `L1`, `L2`, `L3`, `L4`, `L5`), and a `credit_limit_cents` ceiling on open order exposure, which must be zero or greater. A collision on `dealer_code` — or on any other unique code in the platform, namely `style_code`, `finish_code`, `sku`, `station_code`, `line_code`, or `route_code` — is rejected with `ERR_DUPLICATE_CODE` (HTTP 400). Administration may later update a dealer's `credit_limit_cents` or `price_level`; the update increments the dealer's `version`, and — critically — existing orders are unaffected, because every order froze its own copy of the price level at creation. The dealer list view supports filtering by `price_level`.

The door catalog entries each carry a unique `style_code`, a display `name`, a `construction` family (`SLAB`, `SHAKER`, `RAISED_PANEL`, or `GLASS`), a strictly positive `base_list_price_cents` that serves both as the catalog list price per door and as the valuation basis in the replacement program, and an `active` flag that defaults to true. Deactivating a style does not touch existing lines but forbids referencing the style on new door lines. The finish catalog works similarly: a unique `finish_code`, a `color_name`, a `sheen` family (`MATTE`, `SATIN`, `SEMI_GLOSS`, or `HIGH_GLOSS`), an `upcharge_pct` expressed as a non-negative fraction of the line list price (a value of 0.10 means a ten percent upcharge), a `delta_e_tolerance` giving the maximum acceptable color deviation for QC (strictly positive, defaulting to 1.5 when omitted), and an `active` flag defaulting to true. The door-style list supports filtering by `active`, and the finish list by `active` and `sheen`.

Inventory components round out the catalog. Each component has a unique `sku`, a free-text `description`, a `kind` of `SHEET_GOODS`, `DOOR_BLANK`, or `HARDWARE`, a physical `on_hand_qty` that must be zero or greater at creation and afterward mutates only through receipts, an informational `reorder_level` defaulting to 0, and — only for `SHEET_GOODS` — the sheet dimensions `sheet_width_in` and `sheet_height_in` in whole inches, both strictly positive and both required exactly when the kind is `SHEET_GOODS`. Two counters are computed rather than entered: `reserved_qty`, the number of sheets reserved by released nesting runs, starts at 0; and the read-only `available_qty`, which is always the on-hand quantity minus the reserved quantity. Because released runs are terminal, reservations are sunk — `reserved_qty` is never adjusted back down. The component list supports filtering by `kind`, and retrieving a single component includes the computed `available_qty`.

### 3.2. Building and Submitting an Order

A dealer begins an order with an empty creation call; the platform stamps the new order with the acting dealer's identity in `dealer_id`, copies the dealer's current `price_level` into `price_level_snapshot` — permanently immune to later dealer edits — and initializes `status` to `DRAFT`, `hold_status` to `NONE`, `cube_ft` to 0, and `version` to 1.

Lines are added while the order remains in `DRAFT`. Each line declares a `line_type` of `BOX` (a cabinet box) or `DOOR` (a door line), a `finish_id` referencing the finish specification both line types require, whole-inch dimensions `width_in`, `height_in`, and `depth_in` (all strictly positive), a strictly positive `qty`, and the client-looked-up catalog price `unit_list_price_cents`, which the server validates as strictly positive. Shape discipline is enforced by line type: a `DOOR` line must carry a `door_style_id` and its `depth_in` must equal exactly 1, while a `BOX` line must not carry a `door_style_id` and must not carry a `required_sheen_lot_no`; violations are rejected with `ERR_WRONG_LINE_TYPE` (HTTP 422). Both the referenced door style and the referenced finish must be active — an inactive style yields `ERR_DOOR_STYLE_INACTIVE` and an inactive finish yields `ERR_FINISH_INACTIVE` (both HTTP 422). A door line may optionally pin `required_sheen_lot_no`, which later constrains which finish batch the line may join.

At line creation the platform snapshots the finish's `upcharge_pct` into `finish_upcharge_pct_snapshot`, computes the line's `line_list_cents` as the unit list price multiplied by the quantity, computes `finish_upcharge_cents` as the line list multiplied by the snapshotted upcharge fraction and rounded half up to whole cents, and initializes `mod_surcharge_cents` to 0. Each line is born in `PENDING` status. Line creation also recomputes the order's shipping cube: per non-cancelled line, the width times height times depth times quantity in cubic inches is divided by 1728 (the cubic inches in one cubic foot) and rounded half up to two decimal places, and the order's `cube_ft` is the sum of those per-line cubes, again rounded half up to two decimal places. Cancelling lines removes them from this sum. The order-line list view supports filtering by `order_id`, `door_style_id`, `finish_id`, and `finish_batch_id`.

Submission is the order's first pricing event, and it enforces several checks under the global evaluation order of §2.7. The acting dealer must own the order (`ERR_RESOURCE_OWNERSHIP_MISMATCH`), the order must still be in `DRAFT` (`ERR_ORDER_NOT_SUBMITTABLE`), the order must contain at least one line (`ERR_ORDER_HAS_NO_LINES`), no modification request on any of the order's lines may sit in `UNDER_REVIEW` or `CHANGES_REQUESTED` (`ERR_MODS_PENDING_REVIEW`), and the resulting provisional total must not exceed the dealer's `credit_limit_cents` (`ERR_DEALER_CREDIT_EXCEEDED`, HTTP 402).

The provisional pricing variant discounts everything. The dealer multiplier is read from the order's `price_level_snapshot` using the network schedule — `L1` prices at 0.60 of list, `L2` at 0.65, `L3` at 0.70, `L4` at 0.75, and `L5` at 0.80 — and each line's `provisional_net_cents` is the sum of `line_list_cents`, `finish_upcharge_cents`, and `mod_surcharge_cents`, multiplied by that multiplier and rounded half up to whole cents, per line. The order's `provisional_merchandise_cents` is the sum of those per-line nets. A volume discount then applies by tier: merchandise of at least 10,000,000 cents ($100,000.00) earns eight percent, merchandise of at least 5,000,000 cents ($50,000.00) but below the upper threshold earns five percent, and smaller orders earn nothing; an exact hit on a threshold qualifies for that tier. The discount, `provisional_discount_cents`, is the merchandise total multiplied by the tier rate, rounded half up to whole cents, and `provisional_total_cents` is the merchandise total minus the discount. This provisional total — not the merchandise value — is the basis of the credit check. On successful submission every line moves `PENDING` → `QUOTED` with its provisional net set, `submitted_at` is stamped from the logical clock, and the order's `version` increments.

### 3.3. Modification Requests and Engineering Review

While an order is still in `DRAFT`, its dealer may request a dimensional modification on any of the order's lines. The request names a `mod_code` — `REDUCED_DEPTH`, `INCREASED_DEPTH`, `REDUCED_WIDTH`, `INCREASED_WIDTH`, `TOE_KICK_NOTCH`, or `CUSTOM_BORE` — and a strictly positive `new_dimension_in` giving the requested dimension after modification. The request is born in `UNDER_REVIEW` with `revision` 1, and its `surcharge_cents` is computed immediately.

The surcharge follows a pinned evaluation order: base fee, then tiered percentage, then cap. The dimensional delta is the absolute difference between `new_dimension_in` and the line's current dimension — `depth_in` for the two depth modifications and `width_in` for the two width modifications; for `TOE_KICK_NOTCH` and `CUSTOM_BORE` there is no comparison dimension, so the delta is simply `new_dimension_in` itself. The tiered percentage is fifteen percent of `line_list_cents` when the delta is six inches or more, ten percent when the delta is at least three but fewer than six inches, and five percent when the delta is below three inches. The raw surcharge is a per-code base fee — 2,500 cents for `REDUCED_DEPTH`, 4,000 cents for `INCREASED_DEPTH`, 2,500 cents for `REDUCED_WIDTH`, 4,000 cents for `INCREASED_WIDTH`, 5,500 cents for `TOE_KICK_NOTCH`, and 3,000 cents for `CUSTOM_BORE` — plus the line list multiplied by the tier percentage and rounded half up to whole cents. The cap is forty percent of `line_list_cents`, rounded half up. The final `surcharge_cents` is the smaller of the raw surcharge and the cap, with the cap applied strictly after the tiered fee is formed.

An `Engineer` then reviews the request, supplying a `decision` and an optional `note` that is captured into `reviewer_note`. Review requires the request to be in `UNDER_REVIEW`; any other state is rejected with `ERR_MOD_NOT_REVIEWABLE` (HTTP 409). Three decisions exist. `APPROVE` moves the request to `APPROVED`; the line's `mod_surcharge_cents` — always the sum of the surcharges of the line's `APPROVED` modification requests — then takes effect at the order's next pricing event, whether that is submission or dispatch. `REJECT` moves the request to `REJECTED`. Both are terminal. The third decision, `REQUEST_CHANGES`, moves the request to `CHANGES_REQUESTED` and returns it to the dealer.

A dealer resubmits a `CHANGES_REQUESTED` request with a revised `new_dimension_in`; resubmission from any other state is rejected with `ERR_MOD_NOT_RESUBMITTABLE`, and the acting dealer must own the parent order (`ERR_RESOURCE_OWNERSHIP_MISMATCH`). Resubmission recomputes `surcharge_cents` through the same surcharge rule, increments `revision` by 1, and returns the request to `UNDER_REVIEW` — the review cycle may loop any number of times. Because submission of the parent order is gated on no request being `UNDER_REVIEW` or `CHANGES_REQUESTED` (`ERR_MODS_PENDING_REVIEW`), an order cannot be submitted while any of its lines has a modification still inside the review loop. The requests filed against a line are listed through the line's modification collection.

### 3.4. The Finish Room: Batches, Sheen Lots, and Color QC

The `FinishSupervisor` mixes a finish batch by naming the `finish_id` being batched — the finish must be active, else `ERR_FINISH_INACTIVE` — a `sheen_lot_no` identifying the sheen lot of the mix, and a strictly positive `capacity_doors` giving the maximum door count the batch can finish. A new batch is in `MIXING` status with `assigned_door_count` 0, `remix_count` 0, and no `measured_delta_e` yet. The batch list supports filtering by `finish_id` and `status`.

Assigning a door line to a batch is the finish room's core discipline. The batch must be in `MIXING` (`ERR_BATCH_NOT_MIXING`), and the target line — named by `order_line_id` — must be a `QUOTED`, currently unassigned `DOOR` line; anything else is rejected with `ERR_LINE_NOT_ASSIGNABLE` (HTTP 409). Compatibility is then evaluated in a fixed written order. First, the line's `finish_id` must equal the batch's `finish_id` (`ERR_FINISH_MISMATCH`, HTTP 422). Second, the sheen lot rule: if the line's `required_sheen_lot_no` is set, it must equal the batch's `sheen_lot_no` (`ERR_SHEEN_LOT_MISMATCH`, HTTP 422). Third, capacity: the batch's `assigned_door_count` plus the line's `qty` must not exceed `capacity_doors` (`ERR_BATCH_CAPACITY_EXCEEDED`, HTTP 422). A batch whose `assigned_door_count` exactly reaches `capacity_doors` after the assignment is legitimate, because the rule rejects only strict excess.

A successful assignment sets the line's `finish_batch_id` to the batch, advances the line `QUOTED` → `IN_PROGRESS`, and increases the batch's `assigned_door_count` by the line's `qty`. Assignment also feeds two larger re-evaluations: an order whose every door line is now assigned and every box line fully slotted may auto-advance `SUBMITTED` → `IN_PRODUCTION`; and if the assigned line was the last unassigned door line of an order held for finish QC, that order's `PLACED` `FINISH_QC` holds release (see §3.7).

Color QC is recorded against a batch in `MIXING` by capturing `measured_delta_e`, the measured color deviation. The batch's finish supplies the pass threshold: the batch releases when the absolute value of `measured_delta_e` is less than or equal to the finish's `delta_e_tolerance`, and a deviation exactly equal to the tolerance passes. On a pass the batch moves `MIXING` → `RELEASED`, every assigned door line moves `IN_PROGRESS` → `COMPLETED`, and each affected order re-evaluates progression to `READY_TO_SHIP`.

On a fail — absolute deviation strictly greater than the tolerance — the batch moves `MIXING` → `FAILED` and a three-hop cascade fires. First, every assigned door line is unassigned: its `finish_batch_id` is cleared to null, the line falls back `IN_PROGRESS` → `QUOTED`, and the batch's `assigned_door_count` is recomputed downward by each affected line's `qty`. Second, for each distinct order owning an affected line, an `OrderHold` with `reason` `FINISH_QC` is placed, flipping that order's `hold_status` to `ON_HOLD`. Third, the hold gates the order's auto-transitions toward `IN_PRODUCTION` and `READY_TO_SHIP` and blocks route locking until resolved. In both outcomes the recorded deviation stays on the batch as `measured_delta_e`; while a batch is still `MIXING`, that field is null.

A failed batch is not dead stock. Remixing moves it `FAILED` → `MIXING` — only a `FAILED` batch may be remixed, else `ERR_BATCH_NOT_REMIXABLE` — clearing `measured_delta_e` back to null and incrementing `remix_count` by 1. After remix the batch accepts fresh assignments and another QC recording; the remix cycle may repeat until the color matches.

### 3.5. Nesting Runs and Sheet-Goods Inventory

CNC cutting capacity is organized around nesting stations, each registered with a unique `station_code`, a non-negative `changeover_minutes` buffer that must separate consecutive runs on the station, and an `active` flag defaulting to true; an inactive station rejects new runs with `ERR_STATION_INACTIVE` (HTTP 422).

A `ProductionPlanner` stages a nesting run by naming the `station_id`, the `sheet_component_id` of the sheet goods to consume, the `door_line_ids` to nest (an order-independent set of door lines), and a cutting window: a `scheduled_date` that must not precede the logical clock's current date, a `start_minute` between 0 and 1439 inclusive, and an `end_minute` strictly later than `start_minute` and no later than minute 1440 — a malformed window is rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 400). Every entry of `door_line_ids` must reference a `DOOR` line, and the sheet component's `kind` must be `SHEET_GOODS`, else `ERR_COMPONENT_KIND_MISMATCH` (HTTP 422). Each referenced door line's order must already be in `SUBMITTED` or `IN_PRODUCTION` — at both run creation and run release — else `ERR_LINE_ORDER_NOT_RELEASED_TO_PRODUCTION` (HTTP 409).

The station's calendar is protected by a changeover-aware window check at run creation. Against every other `DRAFT` or `RELEASED` run on the same station and date, the new run must clear the other run by the station's changeover buffer: either the new run's start minute is no earlier than the other run's end minute plus the buffer, or the new run's end minute plus the buffer is no later than the other run's start minute. A window that fails to clear any such neighbor is rejected with `ERR_STATION_WINDOW_OVERLAP` (HTTP 409). A new run is born in `DRAFT`.

Releasing a run — allowed only from `DRAFT`, else `ERR_RUN_NOT_RELEASABLE` — fires a four-hop cascade, all atomic within the request. In the first hop the yield is computed and parts are generated. The run's `total_blank_area_in2` is the sum over its door lines of each line's `width_in` times `height_in` times `qty`. The sheet area is the component's `sheet_width_in` times `sheet_height_in`. The run's `sheets_required` is the total blank area increased by a twelve percent cutting-waste allowance, divided by the sheet area, and rounded up to the next whole sheet — when the division lands exactly on a whole number, no extra sheet is added. The run's `utilization_pct` is one hundred times the total blank area divided by the product of `sheets_required` and sheet area, rounded half up to two decimal places. One `Part` is generated per door line, carrying the run's identity in `nesting_run_id`, the line's identity in `order_line_id`, the consumed sheet component copied from the run into `component_id`, a `part_kind` that is always `DOOR_BLANK`, the line's `width_in`, `height_in`, and `qty`, and a deterministic `part_seq`: parts are sequenced by `height_in` descending, then `width_in` descending, then the order line's `created_at` ascending — never by id. The generated parts are browsable through the parts collection, which filters by `nesting_run_id`, `component_id`, and `order_line_id`.

In the second hop, the sheet component's `reserved_qty` increases by `sheets_required` and its `available_qty` — on hand minus reserved — is recomputed. In the third hop, if the resulting `available_qty` has gone negative, the overdraft places holds: for each distinct order owning one of the run's door lines, an `OrderHold` with `reason` `COMPONENT_SHORTAGE`, the component's identity in `component_id`, and a `shortfall_qty` equal to the magnitude of the negative available balance — except that an order already holding a `PLACED` `COMPONENT_SHORTAGE` hold on this same component is skipped. In the fourth hop, each newly held order's `hold_status` flips to `ON_HOLD`, gating its progression. The run's `version` increments on release, and a released run is terminal — its sheet reservation is never returned.

A run still in `DRAFT` may instead be cancelled (`ERR_RUN_NOT_CANCELLABLE` guards the state), which frees the station window. Run listings filter by `station_id` and `sheet_component_id`.

Recovery from a shortage arrives through the loading dock. Posting a receipt of `qty` units against a component increases `on_hand_qty` by that amount, recomputes `available_qty`, and increments the component's `version`. When the recomputed available quantity is zero or greater, every `PLACED` `COMPONENT_SHORTAGE` hold referencing that component releases automatically; each affected order's `hold_status` is recomputed, and any pending auto-transitions fire. The holds outstanding against a component are visible through the component's holds collection.

### 3.6. Box Assembly: Sub-Lots and Line Balancing

Box production runs on assembly lines, each registered with a unique `line_code`, a strictly positive `capacity_minutes_per_day`, a strictly positive `standard_minutes_per_box` labor standard, a non-negative `setup_minutes_per_sub_lot` charged once per sub-lot, and an `active` flag defaulting to true; an inactive line rejects new sub-lots with `ERR_ASSEMBLY_LINE_INACTIVE` (HTTP 422).

Scheduling a sub-lot covers part of a `BOX` line's quantity on one assembly line and date. The planner supplies the `order_line_id` — which must reference a `BOX` line, else `ERR_WRONG_LINE_TYPE` — the `assembly_line_id`, a `scheduled_date` that must not precede the logical clock's current date, a `start_minute` between 0 and 1439 inclusive, and a strictly positive `qty`. The covered line's order must be in `SUBMITTED` or `IN_PRODUCTION` (`ERR_LINE_ORDER_NOT_RELEASED_TO_PRODUCTION`). The sub-lot quantity must not exceed the line's `qty` minus the quantity already slotted by other non-cancelled sub-lots covering the line; exceeding that remainder is rejected with `ERR_SUB_LOT_QTY_EXCEEDS_LINE` (HTTP 402). The sub-lot's `order_id` is denormalized from the covered line's order.

Work content is computed at scheduling: `work_minutes` is the sub-lot `qty` multiplied by the line's `standard_minutes_per_box`, plus one charge of `setup_minutes_per_sub_lot`. The sub-lot's `end_minute` is `start_minute` plus `work_minutes`, and if that computed end falls beyond minute 1440 the request is rejected with `ERR_INVALID_TIME_WINDOW`. Two further checks protect the day. The sub-lot's half-open window — start minute inclusive, end minute exclusive — must not overlap any non-cancelled sub-lot on the same assembly line and date; adjacency is explicitly allowed, so one sub-lot's start may equal another's end. An overlapping placement is rejected with `ERR_LINE_WINDOW_OVERLAP` (HTTP 409). And the aggregate line-day load — the sum of `work_minutes` over all non-cancelled sub-lots on the same assembly line and date, including the new sub-lot — must not exceed `capacity_minutes_per_day`; an exact tie at capacity is allowed, and a true excess is rejected with `ERR_LINE_CAPACITY_EXCEEDED` (HTTP 409).

A new sub-lot is born `SCHEDULED`, the covered line's `slotted_qty` increases by the sub-lot `qty`, and the first sub-lot created for a `QUOTED` box line moves that line `QUOTED` → `IN_PROGRESS`. When a box line becomes fully slotted — `slotted_qty` equal to its `qty` — and the order's door lines are all batch-assigned, the order's progression to `IN_PRODUCTION` re-evaluates. Sub-lot listings filter by `order_id`, `order_line_id`, and `assembly_line_id`.

Completing a sub-lot requires it to be `SCHEDULED`, else `ERR_SUB_LOT_NOT_COMPLETABLE` (HTTP 409), and moves it to `COMPLETE`. When the covered box line's sub-lots are all complete and its `slotted_qty` equals its `qty`, the line moves `IN_PROGRESS` → `COMPLETED`, and the owning order re-evaluates progression to `READY_TO_SHIP`.

### 3.7. Holds, Order Progression, and Cancellation

The hold system is the plant's automatic brake. An `OrderHold` records the held order in `order_id`, a `reason` of `COMPONENT_SHORTAGE` or `FINISH_QC`, the implicated component in `component_id` (set for shortage holds, null for finish-QC holds), and the `shortfall_qty` recorded at placement for shortage holds (null otherwise). Holds are born `PLACED` and end `RELEASED`. While at least one hold on an order is `PLACED`, the order's computed `hold_status` reads `ON_HOLD`; when the last one releases it returns to `NONE`.

Release arrives three ways. A shortage hold releases automatically when a receipt lifts the component's `available_qty` back to zero or greater. A finish-QC hold releases automatically when the held order's last unassigned door line is assigned to a batch in `MIXING` or `RELEASED`. And a `PlantAdmin` may release any `PLACED` hold manually as an override; releasing a hold that is not `PLACED` is rejected with `ERR_HOLD_NOT_RELEASABLE` (HTTP 409). Every release recomputes the order's `hold_status`, and when it returns to `NONE` the order's pending auto-transitions are re-evaluated immediately. The holds on an order are listed through the order's holds collection, and order listings filter by `dealer_id`, `delivery_route_id`, and `status`.

Progression itself deserves restating as one narrative, because it is derived rather than commanded. From `SUBMITTED`, an order auto-advances to `IN_PRODUCTION` when its `hold_status` is `NONE`, every door line carries a `finish_batch_id`, and every box line has `slotted_qty` equal to its `qty`; the evaluation runs after each batch assignment, sub-lot creation, and hold release. From `IN_PRODUCTION`, an order auto-advances to `READY_TO_SHIP` when its `hold_status` is `NONE` and every line is `COMPLETED` — door lines complete when their batch QC-releases, box lines when their last sub-lot completes — and this evaluation runs after each batch QC release, sub-lot completion, and hold release. Each auto-advance increments the order's `version`.

Cancellation compensates everything the order touched, and the cascade differs by the state it cancels from; cancellation from any state other than `DRAFT` or `SUBMITTED` is rejected with `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409), and the acting dealer must own the order. Cancelling a `DRAFT` order moves all of its lines to `CANCELLED`, moves every non-terminal modification request on its lines to `REJECTED` with `reviewer_note` set to the literal text `ORDER_CANCELLED`, and increments the order's `version`. Cancelling a `SUBMITTED` order does all of that and more: each door line's `finish_batch_id` is cleared and every affected batch recomputes its `assigned_door_count`; every `SCHEDULED` sub-lot covering its box lines moves to `CANCELLED`, which frees the assembly line's window and day load and recomputes each covered line's `slotted_qty` to exclude the cancelled sub-lots; every `PLACED` hold on the order releases; and if the order sat on a delivery route, it is removed — the route's `reserved_cu_ft` decreases by the order's `cube_ft`, the route's `assigned_order_count` decreases by one, and the order's `delivery_route_id` returns to null. Once an order has reached `IN_PRODUCTION` it can no longer be cancelled at all.

### 3.8. Replacement Claims and Warranty Adjudication

The damage and replacement door program lets a dealer file a claim against a door line of one of its own shipped orders. Filing names the `original_order_line_id`, a `claim_type` of `FREIGHT_DAMAGE`, `MANUFACTURING_DEFECT`, or `DEALER_ERROR`, and a strictly positive `qty` of damaged doors. Eligibility is strict: the referenced line must be a `DOOR` line, its order must be `SHIPPED`, the order must belong to the claiming dealer (the ownership check `ERR_RESOURCE_OWNERSHIP_MISMATCH` guards this first), and the claimed `qty` must not exceed the original line's `qty`; any failure is rejected with `ERR_CLAIM_LINE_NOT_ELIGIBLE` (HTTP 422).

Credit is valued against the dealer's current network standing, not history: `credit_basis_cents` is the original line's `unit_list_price_cents` multiplied by the dealer multiplier for the dealer's `price_level` as it stands at claim creation — using the same `L1` through `L5` schedule as order pricing — multiplied by the claimed `qty`, rounded half up to whole cents. The claim's first credit figure is a provisional estimate: `provisional_credit_cents` is a flat fifty percent of the basis, rounded half up, regardless of claim type or warranty window. A new claim is born in `SUBMITTED` status. Claim listings filter by `dealer_id` and `original_order_line_id`.

Adjudication is a `PlantAdmin` decision carrying a `decision` of `APPROVE` or `DENY` and an optional `note` captured into `adjudicator_note`; the claim must still be in `SUBMITTED`, else `ERR_CLAIM_NOT_ADJUDICATABLE` (HTTP 409). The final figures depend on type and, for the covered types, on the warranty window measured in whole days from the original order's `shipped_at` against the logical clock. Approving a `FREIGHT_DAMAGE` claim is allowed only within ninety days of `shipped_at`, and approving a `MANUFACTURING_DEFECT` claim only within three hundred sixty-five days; a claim exactly ninety — or exactly three hundred sixty-five — days after `shipped_at` is still within its window, while one day beyond is rejected with `ERR_CLAIM_WARRANTY_EXPIRED` (HTTP 422). An in-window approval of either covered type moves the claim to `APPROVED_NO_CHARGE` with `final_credit_cents` set to the full `credit_basis_cents` and `replacement_charge_cents` set to 0. `DEALER_ERROR` carries no warranty window at all: approving it moves the claim to `APPROVED_CHARGED` with `final_credit_cents` 0 and `replacement_charge_cents` set to sixty percent of the basis, rounded half up. Denying a claim of any type moves it to `DENIED` with both `final_credit_cents` and `replacement_charge_cents` set to 0. All three outcomes are terminal. The provisional estimate and the final adjudication genuinely diverge: for identical claim data they differ whenever the final outcome is zero or one hundred percent of basis.

### 3.9. Delivery Routes, Consolidation, and Dispatch

A `ShippingCoordinator` opens a delivery route with a unique `route_code`, a `route_date` that must not precede the logical clock's current date, and a strictly positive `capacity_cu_ft` of truck cube. A new route is `PLANNED` with `reserved_cu_ft` 0 and `assigned_order_count` 0; route listings filter by `status`.

Assigning an order to a route is the platform's one optimistic-concurrency-guarded write (§2.8): the request names the `order_id` and must carry `expected_order_version` equal to the order's current `version`, with a stale view rejected as `ERR_STALE_ORDER_VERSION` (HTTP 412). The route must be `PLANNED` (`ERR_ROUTE_NOT_PLANNED`, HTTP 409), and the order must be in `SUBMITTED`, `IN_PRODUCTION`, or `READY_TO_SHIP` — assigning an order in any other state is rejected with `ERR_ORDER_NOT_ROUTE_ASSIGNABLE` (HTTP 409). Capacity is a fiscal-grade ceiling: the route's `reserved_cu_ft` plus the order's `cube_ft` must not exceed `capacity_cu_ft`, else `ERR_ROUTE_CUBE_EXCEEDED` (HTTP 402). Assignment supersedes: the order's `delivery_route_id` is set to the new route, and if the order had sat on a prior route, that route's `reserved_cu_ft` and `assigned_order_count` are decremented accordingly — so a second sequential assignment carrying a current version legitimately succeeds. The receiving route's `reserved_cu_ft` increases by the order's `cube_ft`, its `assigned_order_count` increases by one, and the order's `route_stop_seq` is assigned as a 1-based sequence in the order that assignment calls are accepted, earliest accepted assignment first. The order's `version` increments on every assignment.

Locking a route commits its manifest: the route must be `PLANNED` (`ERR_ROUTE_NOT_PLANNED`), at least one order must be assigned (`ERR_ROUTE_EMPTY`, HTTP 409), and no assigned order may be `ON_HOLD` (`ERR_ORDER_ON_HOLD`, HTTP 409). A locked route waits only on readiness: dispatch requires the route in `LOCKED` (`ERR_ROUTE_NOT_LOCKED`, HTTP 409) and every assigned order in `READY_TO_SHIP` (`ERR_ORDERS_NOT_READY_TO_SHIP`, HTTP 409).

Dispatch is the order's final pricing event, computed per assigned order in a pinned evaluation order. First the order's cube; then the base freight, which is the greater of an 8,500-cent flat minimum and the order's `cube_ft` multiplied by 450 cents per cubic foot, rounded half up to whole cents; then the consolidation tier read from the route's `assigned_order_count` at the dispatch instant — a count that includes the order being priced and is identical for every order on the route — granting fifteen percent off when at least five orders ride the route, ten percent off when at least three but fewer than five do, and no consolidation below three; then `freight_cents` as the base freight reduced by the consolidation percentage, rounded half up. Alongside freight, the final pricing variant settles the merchandise: each line's `final_net_cents` is the `line_list_cents` multiplied by the snapshotted dealer multiplier and rounded half up, plus the `finish_upcharge_cents` and `mod_surcharge_cents` charged at full value — surcharges and upcharges are not discountable at settlement, unlike at submission, so for identical line data the final net exceeds the provisional net whenever upcharges plus surcharges are positive and the multiplier is below one. The order's `final_merchandise_cents` sums those per-line final nets, and `final_discount_cents` reapplies the same volume tiers as submission — eight percent at or above 10,000,000 cents, five percent at or above 5,000,000 cents, exact hits qualifying — now against the final merchandise figure. The order's `grand_total_cents` is `final_merchandise_cents` minus `final_discount_cents` plus `freight_cents`, frozen at dispatch.

As dispatch executes, every assigned order moves `READY_TO_SHIP` → `SHIPPED`, each of its lines moves `COMPLETED` → `SHIPPED` with its final net computed, `shipped_at` is stamped from the logical clock, and each order's `version` increments. The route's `reserved_cu_ft` and `assigned_order_count` freeze at their dispatch values, and the route itself moves `LOCKED` → `DISPATCHED`, which is terminal.

## 4. Endpoint Definitions

All endpoints are mounted under `/kcma`. Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource or trigger an action respond with HTTP 200. The table below is a summary only — request payloads, validation behavior, and side effects are defined by the narratives of §2 and §3. Curly-braced segments of the paths are path parameters naming the target resource — `dealerId`, `componentId`, `orderId`, `lineId`, `modId`, `batchId`, `runId`, `partId`, `subLotId`, `claimId`, `routeId`, and `holdId`, plus the generic `id` used on a few nested paths — and each is validated for existence left to right as described in §2.7.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/kcma/dealers` | Register a dealer with network price level and credit limit | `PlantAdmin` |
| PUT | `/kcma/dealers/{dealerId}` | Update a dealer's credit limit and/or price level | `PlantAdmin` |
| GET | `/kcma/dealers` | List dealers | all six roles |
| POST | `/kcma/door-styles` | Create a door style catalog entry | `PlantAdmin` |
| GET | `/kcma/door-styles` | List door styles | all six roles |
| POST | `/kcma/finish-specs` | Create a finish catalog entry (color, sheen, upcharge, Delta-E tolerance) | `PlantAdmin` |
| GET | `/kcma/finish-specs` | List finish specs | all six roles |
| POST | `/kcma/components` | Create an inventory component | `PlantAdmin` |
| GET | `/kcma/components` | List components | all six roles |
| GET | `/kcma/components/{componentId}` | Get one component, including computed availability | all six roles |
| POST | `/kcma/components/{componentId}/receipts` | Receive stock; auto-releases shortage holds when availability recovers | `ProductionPlanner` |
| GET | `/kcma/components/{id}/holds` | List shortage holds referencing a component | all six roles |
| POST | `/kcma/orders` | Create a DRAFT order for the acting dealer | `Dealer` |
| GET | `/kcma/orders` | List orders with filters | all six roles |
| GET | `/kcma/orders/{orderId}` | Get one order (pricing fields, hold status, route linkage) | all six roles |
| POST | `/kcma/orders/{orderId}/lines` | Add a BOX or DOOR line to a DRAFT order | `Dealer` |
| GET | `/kcma/orders/{id}/holds` | List holds on an order | all six roles |
| POST | `/kcma/orders/{orderId}/submit` | Submit a DRAFT order: provisional pricing, volume discount, credit check, mod-review gate | `Dealer` |
| POST | `/kcma/orders/{orderId}/cancel` | Cancel a DRAFT or SUBMITTED order with full compensation cascade | `Dealer` |
| GET | `/kcma/order-lines` | List order lines with filters | all six roles |
| GET | `/kcma/order-lines/{lineId}` | Get one order line | all six roles |
| POST | `/kcma/order-lines/{id}/modifications` | Request a modification on a line of a DRAFT order; surcharge computed immediately | `Dealer` |
| GET | `/kcma/order-lines/{id}/modifications` | List modification requests for a line | all six roles |
| POST | `/kcma/modifications/{modId}/review` | Engineering review decision: approve, request changes, or reject | `Engineer` |
| POST | `/kcma/modifications/{modId}/resubmit` | Resubmit a CHANGES_REQUESTED modification with a revised dimension | `Dealer` |
| POST | `/kcma/finish-batches` | Mix a finish batch with a sheen lot number and door capacity | `FinishSupervisor` |
| GET | `/kcma/finish-batches` | List finish batches | all six roles |
| GET | `/kcma/finish-batches/{batchId}` | Get one finish batch | all six roles |
| POST | `/kcma/finish-batches/{batchId}/qc-record` | Record measured Delta-E; release on pass, fail with unassign cascade and QC holds | `FinishSupervisor` |
| POST | `/kcma/finish-batches/{batchId}/assign` | Assign a QUOTED unassigned DOOR line to a MIXING batch | `FinishSupervisor` |
| POST | `/kcma/finish-batches/{batchId}/remix` | Remix a FAILED batch back to MIXING | `FinishSupervisor` |
| POST | `/kcma/nesting-stations` | Create a CNC nesting station with changeover buffer | `PlantAdmin` |
| GET | `/kcma/nesting-stations` | List nesting stations | all six roles |
| POST | `/kcma/nesting-runs` | Create a DRAFT nesting run over door lines on a station | `ProductionPlanner` |
| GET | `/kcma/nesting-runs` | List nesting runs | all six roles |
| GET | `/kcma/nesting-runs/{runId}` | Get one nesting run | all six roles |
| POST | `/kcma/nesting-runs/{runId}/release` | Release a DRAFT run: generate parts, reserve sheets, place shortage holds on overdraft | `ProductionPlanner` |
| POST | `/kcma/nesting-runs/{runId}/cancel` | Cancel a DRAFT run, freeing the station window | `ProductionPlanner` |
| GET | `/kcma/parts` | List generated parts with filters | all six roles |
| GET | `/kcma/parts/{partId}` | Get one part | all six roles |
| POST | `/kcma/assembly-lines` | Create an assembly line with daily capacity, per-box minutes, and per-sub-lot setup | `PlantAdmin` |
| GET | `/kcma/assembly-lines` | List assembly lines | all six roles |
| POST | `/kcma/sub-lots` | Schedule a sub-lot covering part of a BOX line on a line-and-date window | `ProductionPlanner` |
| GET | `/kcma/sub-lots` | List sub-lots with filters | all six roles |
| GET | `/kcma/sub-lots/{subLotId}` | Get one sub-lot | all six roles |
| POST | `/kcma/sub-lots/{subLotId}/complete` | Mark a sub-lot complete; may complete its BOX line and advance the order | `ProductionPlanner` |
| POST | `/kcma/replacement-claims` | File a damage/replacement claim against a DOOR line of an own SHIPPED order | `Dealer` |
| GET | `/kcma/replacement-claims` | List replacement claims | all six roles |
| GET | `/kcma/replacement-claims/{claimId}` | Get one replacement claim | all six roles |
| POST | `/kcma/replacement-claims/{claimId}/adjudicate` | Adjudicate a claim: approve (window- and type-dependent) or deny | `PlantAdmin` |
| POST | `/kcma/delivery-routes` | Create a delivery route with date and cube capacity | `ShippingCoordinator` |
| GET | `/kcma/delivery-routes` | List delivery routes | all six roles |
| POST | `/kcma/delivery-routes/{routeId}/assign-order` | Assign an order to a PLANNED route (stale-version guarded; supersedes prior route; cube check) | `ShippingCoordinator` |
| POST | `/kcma/delivery-routes/{routeId}/lock` | Lock a PLANNED route (requires at least one assigned order and none on hold) | `ShippingCoordinator` |
| POST | `/kcma/delivery-routes/{routeId}/dispatch` | Dispatch a LOCKED route: orders ship with final pricing and consolidated freight | `ShippingCoordinator` |
| POST | `/kcma/order-holds/{holdId}/release` | Manual release of a PLACED hold (administrative override) | `PlantAdmin` |
| POST | `/kcma/_clock/set_current_utc` | Set the server's logical clock to a supplied ISO 8601 UTC instant | `PlantAdmin` |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is a summary only.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_RESOURCE_OWNERSHIP_MISMATCH` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_QUANTITY` | 400 |
| `ERR_INVALID_TIME_WINDOW` | 400 |
| `ERR_DUPLICATE_CODE` | 400 |
| `ERR_DEALER_NOT_FOUND` | 404 |
| `ERR_DOOR_STYLE_NOT_FOUND` | 404 |
| `ERR_FINISH_NOT_FOUND` | 404 |
| `ERR_COMPONENT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_MODIFICATION_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_RUN_NOT_FOUND` | 404 |
| `ERR_PART_NOT_FOUND` | 404 |
| `ERR_ASSEMBLY_LINE_NOT_FOUND` | 404 |
| `ERR_SUB_LOT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_ROUTE_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_SUBMITTABLE` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_ORDER_HAS_NO_LINES` | 409 |
| `ERR_MOD_NOT_REVIEWABLE` | 409 |
| `ERR_MOD_NOT_RESUBMITTABLE` | 409 |
| `ERR_BATCH_NOT_MIXING` | 409 |
| `ERR_BATCH_NOT_REMIXABLE` | 409 |
| `ERR_RUN_NOT_RELEASABLE` | 409 |
| `ERR_RUN_NOT_CANCELLABLE` | 409 |
| `ERR_SUB_LOT_NOT_COMPLETABLE` | 409 |
| `ERR_ROUTE_NOT_PLANNED` | 409 |
| `ERR_ROUTE_NOT_LOCKED` | 409 |
| `ERR_ROUTE_EMPTY` | 409 |
| `ERR_CLAIM_NOT_ADJUDICATABLE` | 409 |
| `ERR_HOLD_NOT_RELEASABLE` | 409 |
| `ERR_MODS_PENDING_REVIEW` | 409 |
| `ERR_LINE_ORDER_NOT_RELEASED_TO_PRODUCTION` | 409 |
| `ERR_ORDER_ON_HOLD` | 409 |
| `ERR_ORDERS_NOT_READY_TO_SHIP` | 409 |
| `ERR_DOOR_STYLE_INACTIVE` | 422 |
| `ERR_FINISH_INACTIVE` | 422 |
| `ERR_ASSEMBLY_LINE_INACTIVE` | 422 |
| `ERR_STATION_INACTIVE` | 422 |
| `ERR_WRONG_LINE_TYPE` | 422 |
| `ERR_COMPONENT_KIND_MISMATCH` | 422 |
| `ERR_CLAIM_LINE_NOT_ELIGIBLE` | 422 |
| `ERR_FINISH_MISMATCH` | 422 |
| `ERR_SHEEN_LOT_MISMATCH` | 422 |
| `ERR_LINE_NOT_ASSIGNABLE` | 409 |
| `ERR_ORDER_NOT_ROUTE_ASSIGNABLE` | 409 |
| `ERR_BATCH_CAPACITY_EXCEEDED` | 422 |
| `ERR_LINE_WINDOW_OVERLAP` | 409 |
| `ERR_STATION_WINDOW_OVERLAP` | 409 |
| `ERR_LINE_CAPACITY_EXCEEDED` | 409 |
| `ERR_SCHEDULE_DATE_IN_PAST` | 422 |
| `ERR_CLAIM_WARRANTY_EXPIRED` | 422 |
| `ERR_ROUTE_CUBE_EXCEEDED` | 402 |
| `ERR_DEALER_CREDIT_EXCEEDED` | 402 |
| `ERR_SUB_LOT_QTY_EXCEEDS_LINE` | 402 |
| `ERR_STALE_ORDER_VERSION` | 412 |
