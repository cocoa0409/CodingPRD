# Christmas Tree Farm Wholesale API — Product Requirements Document

## 1. Introduction

An Oregon Christmas tree grower operates on an unforgiving calendar. Roughly a decade passes between planting a seedling cohort and selling its first tree, yet nearly all revenue is compressed into a few weeks between late autumn harvest and the December shipping rush. Capital sits in the ground as standing inventory; buyers book trees months before a single one is cut; crews must be scheduled, paid, and laid off inside a narrow window; and every tree promised to a wholesaler, delivered to a retail lot on consignment, or tagged at the choose-and-cut gate draws down the same finite pool of standing stems. This document specifies an API that runs that entire operation: planting rotation and inventory tracked by height class, a pre-season wholesale order book with credit enforcement, harvest crew ticketing with piece-rate payroll, load building and shipping windows, retail lot consignment with unsold-return settlement, choose-and-cut tagging, cull and replanting workflows, and the seasonal close-out.

The system is built around one hard reality: inventory promises made in July must survive contact with a wet November. Physical counts drift from the ledger through disease, storm damage, and grading losses, so the API supports formal field surveys that re-baseline inventory and automatically unwind over-reservations. A season-wide posture gate — from `PLANNING` through `BOOKING`, `HARVEST`, `SHIPPING`, and `SETTLEMENT` to `CLOSED` — controls which operations are legal at which moment, mirroring the compressed revenue window the farm lives by.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `Owner`, `FarmManager`, `WholesaleBuyer`, and `CrewLead`. A request that arrives without these headers, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to specific operations is restricted by role, and an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity is bound to `X-User-ID` differently per role, and the binding determines how ownership checks behave:

- When `X-User-Role` is `Owner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares it to any entity's `id`.
- When `X-User-Role` is `FarmManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `proposed_by_user_id` on a replant plan) but does not compare it to any entity's `id`.
- When `X-User-Role` is `WholesaleBuyer`, `X-User-ID` is the `id` of the acting `BuyerAccount`. Ownership checks on any resource that references a buyer compare the resource's `buyer_account_id` field to `X-User-ID`: a wholesale buyer may create orders only under its own account, may read only its own account and its own orders, may cancel only its own orders, and sees only allocations belonging to its own orders. Any mismatch is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the acting `Crew`. A crew lead may post a harvest ticket only when the ticket's `crew_id` equals `X-User-ID`, and sees only its own crew's tickets; violations are rejected with `ERR_FORBIDDEN`.

A further segregation-of-duties rule governs replant approvals: the operator who approves or rejects a replant plan must not be the operator who proposed it. A violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The single documented exception is a crop lot's stand-bucket listing, which is always returned in declared height-class order, beginning with `H_4_5` and ending with `H_9_PLUS`.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every time-dependent rule in the system — booking windows, harvest and shipping windows, tag expiry, order expiry, survey posting timestamps — is evaluated against a **logical clock** maintained by the server, never against wall-clock time. At startup the logical clock reads exactly 2026-05-01T00:00:00Z. An `Owner`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc` value. Workflow language throughout this document — "now", "at this instant", "the current time" — always refers to this logical clock.

### 2.5. Common Resource Properties

Every resource in this API carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, 2025-05-24T10:30:00.123Z), set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed upon any change to the resource's properties.
- `version` (integer): starts at 1 at creation and increments by exactly 1 on every mutation of the resource, including mutations the server applies automatically as side effects of other operations.

### 2.6. Existence Ordering and the Validation Pipeline

For any request whose path contains resource identifiers, and for any foreign-key reference carried in a request body, the system validates existence in a strict left-to-right order and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource. A request body that is missing a required field, carries a value of the wrong type, names an enum member outside the declared set, or supplies a quantity below its minimum is rejected with `ERR_MALFORMED_REQUEST` (HTTP 400).

When several checks could reject the same request, the system evaluates them in a fixed pipeline order, and the earliest failing check determines the error returned. That order is: first authentication of the `X-User-Role` and `X-User-ID` headers (`ERR_UNAUTHENTICATED`); second, role permission and entity-backed ownership (`ERR_FORBIDDEN`); third, segregation of duties on replant decisions (`ERR_SOD_VIOLATION`); fourth, existence of path identifiers and referenced resources, left to right (`ERR_NOT_FOUND`); fifth, request well-formedness (`ERR_MALFORMED_REQUEST`); sixth, state-machine from-state validity, including terminal-state lockdown and the requirement that a posture advance name the immediate next posture (`ERR_INVALID_STATE`); seventh, the season posture gate (`ERR_POSTURE_FORBIDS`); eighth, the advance-posture guard conditions (`ERR_POSTURE_GUARD_FAILED`); ninth, temporal window checks (`ERR_OUTSIDE_HARVEST_WINDOW`, `ERR_OUTSIDE_SHIPPING_WINDOW`); tenth, referential business rules such as block harvestability, block occupancy, u-cut designation, crew activity, buyer standing, and ticket-block alignment; eleventh, business constraints such as inventory sufficiency, capacity, double-booking, and dock-window conflicts; and twelfth, fiscal checks (`ERR_CREDIT_LIMIT_EXCEEDED`). Later checks never mask an earlier failure.

### 2.7. Season Posture: The Master Gate

A season's `posture` field is the master switch for the entire operation. It walks forward only — `PLANNING` → `BOOKING` → `HARVEST` → `SHIPPING` → `SETTLEMENT` → `CLOSED` — exactly one step per advance call, with `CLOSED` terminal. Naming any target other than the immediate next posture is rejected with `ERR_INVALID_STATE`. Any operation attempted in a posture that does not permit it is rejected with `ERR_POSTURE_FORBIDS` (HTTP 409).

The posture map is as follows. Wholesale order creation and order submission require `BOOKING`; allocation against an order requires `BOOKING` or `HARVEST`. Harvest ticket posting and voiding, and every choose-and-cut tag operation (sell, redeem, release), require `HARVEST`. Load creation requires `HARVEST` or `SHIPPING`; adding lines to a load requires `HARVEST`; shipping a load requires `SHIPPING`. Consignment creation requires `BOOKING` or `HARVEST`; delivering a consignment requires `HARVEST` or `SHIPPING`; reporting returns requires `SHIPPING` or `SETTLEMENT`; settlement and dispute require `SETTLEMENT`. Survey creation and posting, cull recording, and crew hiring are permitted in any posture except `CLOSED`. Read operations are never posture-gated.

### 2.8. Field Inventory Accounting

Standing inventory is tracked per **stand bucket**: one bucket per height class per crop lot. Height classes are exactly `H_4_5`, `H_5_6`, `H_6_7`, `H_7_8`, `H_8_9`, and `H_9_PLUS`; species are exactly `NOBLE_FIR`, `DOUGLAS_FIR`, `GRAND_FIR`, and `NORDMANN_FIR`. Each bucket carries an epoch `baseline_count`, a live `standing_count`, a `reserved_count` of trees promised by reservations not yet cut, a `tagged_active_count` of trees claimed by active choose-and-cut tags, and four epoch counters — `cut_cumulative`, `culled_cumulative`, `ucut_sold_cumulative`, and `consigned_cumulative` — each starting at zero.

Two statements of the same physical truth coexist. The **book stock** is the ledger value exposed as `standing_count` on every read: the epoch baseline minus every recorded consumption event (cuts, culls, tag claims, consignment deliveries, net of reversals). The **survey stock** is the physical count a field crew reports. The two drift apart whenever unrecorded shrink occurs, and identical bucket data can therefore yield a different standing after a survey than before it. Every bucket also records `last_shrink_delta` — the difference between the physical count and the book stock observed at the most recent survey post — which is null until the first survey of the lot is posted. Inventory arithmetic is exact integer arithmetic throughout.

A bucket's `available_count` is always its `standing_count` minus its `reserved_count`; allocation, consignment delivery, tag sales, and culls all draw against this figure. When any consumption event leaves every bucket of a crop lot with zero standing, zero reserved, and zero active tags, the lot automatically transitions from `ACTIVE` to `DEPLETED`, incrementing the lot's `version` and refreshing its `updated_at`.

### 2.9. Money, Piece Rates, and Rounding

All monetary values are integer cents. Wherever a calculation produces a fraction — an invoice discount, a per-line piece product, a settlement figure — the result is rounded **half-up to whole cents**. Two orderings are pinned and must not be rearranged: an order's volume discount is computed from the already-rounded subtotal (never by rounding the net-of-discount product in one step), and a harvest ticket's piece total is computed as the per-line product rounded half-up first and then summed across lines (never by summing raw products and rounding once).

### 2.10. Optimistic Concurrency Control

Exactly two write operations in this API carry an optimistic-concurrency field, and both reject stale writers with `ERR_STALE_VERSION` (HTTP 412). Posting an inventory survey requires the request to carry `expected_crop_lot_version` equal to the target crop lot's current `version`; because posting a survey legitimately supersedes the previously posted survey, a second writer holding a stale lot version must lose with 412 rather than silently re-baselining buckets against counts the first writer already replaced. Allocating against a wholesale order requires the request to carry `expected_order_version` equal to the order's current `version`; because a prior allocation or an ops-run backfill may legitimately have advanced `allocated_qty`, a second writer with a stale order version must lose with 412 rather than over-reserving against an outdated view of the order. No other endpoint accepts a version field.

## 3. Business Logic & Workflows

### 3.1. Seasons, Blocks, and the Planting Rotation

An `Owner` opens the year by creating a **Season**, supplying the operating `year` label (for example, 2026), the `booking_open_at` and `booking_close_at` instants that bracket the wholesale order book, the `harvest_window_start` and `harvest_window_end` ISO calendar dates that bracket legal cutting days, and the `shipping_window_start` and `shipping_window_end` instants that bound dock pickups. A new season is born in `PLANNING` posture with its `ops_run_index` at zero.

Within a season, a `FarmManager` lays out the farm as **Blocks**, each identified by a `block_code` unique within its season and carrying its planted `acreage`. A block flagged `ucut_designated` (defaulting to false when omitted) is open to choose-and-cut retail customers once harvestable. The block list can be filtered by `season_id`.

Blocks live a cyclic rotation: `RESTING` → `PLANTED` → `GROWING` → `HARVESTABLE` → `HARVESTED` → `RESTING`, with each forward step beyond the first driven by an explicit rotation advance from a `FarmManager`. Planting happens one of two ways. A `FarmManager` may plant a new **CropLot** directly on a `RESTING` block by naming the `block_id`, the `species`, the `planted_year` of the cohort, and `initial_counts` — an object carrying an integer count of at least zero for every one of the six height-class keys. Planting is refused with `ERR_BLOCK_OCCUPIED` (HTTP 409) unless the block is `RESTING` and has no other lot in `ACTIVE`. A successful planting creates the lot in `ACTIVE` status, creates all six stand buckets with each bucket's `baseline_count` and `standing_count` initialized from the supplied counts, and moves the block from `RESTING` to `PLANTED`. Alternatively, a harvested block may be replanted through the replant-plan workflow described below. Crop lots can be listed and filtered by `block_id`; a lot's six buckets and its survey history are reachable as sub-resources of the lot, and every survey list is ordered by creation ascending.

Rotation advances are guarded. Moving `PLANTED` → `GROWING` or `GROWING` → `HARVESTABLE` requires the block to host a lot in `ACTIVE`, failing with `ERR_INVALID_STATE` otherwise. Moving `HARVESTABLE` → `HARVESTED` requires that no allocation on any bucket of the block's lots remains in `RESERVED` or `CUT` and that no choose-and-cut tag on the block is still `ACTIVE`. Moving `HARVESTED` → `RESTING` requires that every crop lot of the block has reached `DEPLETED`. Each successful advance increments the block's `version`.

When a block reaches `HARVESTED`, a `FarmManager` may propose a **ReplantPlan** by naming the `block_id`, the successor `species`, and the `planned_count` of seedlings (at least one); proposing against a block that is not `HARVESTED` fails with `ERR_BLOCK_OCCUPIED`. The proposal is born `PROPOSED`, and the server records the caller's header identity in `proposed_by_user_id`. An `Owner` then decides: approval moves the plan to `APPROVED` and stamps `approved_by_user_id` — null until this point — with the approver's identity, while rejection moves it to `REJECTED`. Both decisions enforce segregation of duties — the deciding `X-User-ID` must differ from `proposed_by_user_id`, else `ERR_SOD_VIOLATION`. Execution of an `APPROVED` plan by a `FarmManager` re-checks that the block is still `HARVESTED` (a block re-occupied in the meantime yields `ERR_BLOCK_OCCUPIED`), then creates the successor crop lot on the block with the plan's species, a `planted_year` equal to the block's season `year`, and six stand buckets whose baselines place the entire `planned_count` on `H_4_5` and zero on every other class. The block moves `HARVESTED` → `PLANTED`, the plan's `created_crop_lot_id` records the server-minted lot identifier, and the plan reaches `EXECUTED`. Replant plans can be listed filtered by `block_id`.

### 3.2. Counting the Standing Crop: Surveys, Culls, and Re-baselining

Field reality and ledger reality diverge over a season. A `FarmManager` captures field reality by creating an **InventorySurvey** against a `crop_lot_id`, supplying `surveyed_counts` — an object carrying the physical count for every one of the six height-class keys, each an integer of at least zero. The survey is born `DRAFT` and touches nothing until posted.

Posting a survey is the inventory system's act of reconciliation, and it is one of the two optimistic-concurrency points in the API: the post must carry `expected_crop_lot_version` matching the lot's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). The lot's season must not be `CLOSED`, or the post fails with `ERR_POSTURE_FORBIDS`. On a successful post, each of the lot's six buckets is re-baselined: the bucket's `last_shrink_delta` records the surveyed count minus the book `standing_count` (negative meaning unrecorded loss), `baseline_count` becomes the surveyed count, `standing_count` is reset to that same physical count, and all four epoch counters — `cut_cumulative`, `culled_cumulative`, `ucut_sold_cumulative`, `consigned_cumulative` — reset to zero. The `reserved_count` and `tagged_active_count` survive the re-baseline untouched. The survey's `posted_at` stamps the logical-clock instant of posting, the previously `POSTED` survey of the same lot moves to `SUPERSEDED`, and the lot's `version` increments.

Re-baselining can strand promises: a bucket may end up with more trees reserved than physically standing. Whenever a posted survey leaves a bucket with `reserved_count` greater than the new `standing_count`, an **over-reservation sweep** runs on that bucket before the post completes. The sweep releases whole allocations against that bucket in youngest-first order (most recently created first), restoring each allocation's quantity to the bucket's `reserved_count` and deducting it from the serving order's `allocated_qty`, until reserved no longer exceeds standing or no allocations in `RESERVED` remain. Only `RESERVED` allocations are ever swept — trees already `CUT` or `LOADED` are never touched — and each released allocation moves to `RELEASED`. An order that drops below full allocation through the sweep regresses from `ALLOCATED` back to `SUBMITTED`. This sweep is the intended serialization point between survey posting and the order book.

Shrink that *is* observed in the field is recorded directly: a `FarmManager` files a **CullRecord** naming the `bucket_id`, the `count` of trees removed (at least one), and a `reason` of `DISEASE`, `DAMAGE`, `GRADING`, or `OTHER`. The count may not exceed the bucket's `available_count`, failing with `ERR_CULL_EXCEEDS_STANDING` (HTTP 422) when it does. Recording a cull decrements the bucket's `standing_count` and accrues into `culled_cumulative`; it is permitted in any posture except `CLOSED`, and it can tip a fully consumed lot into `DEPLETED`. Cull records can be listed filtered by `bucket_id`.

### 3.3. The Wholesale Order Book: Buyers, Credit, and Invoicing

The `Owner` onboards each wholesale customer as a **BuyerAccount** with a business `name` and a `credit_limit_cents` of at least zero. A new buyer's `standing` is `GOOD_STANDING` and its exposure is zero. The owner may move a buyer between `GOOD_STANDING` and `CREDIT_HOLD` at will by naming the `to_standing` target, and may move a buyer to `CLOSED` — terminal — only when that buyer holds no order in `DRAFT`, `SUBMITTED`, or `ALLOCATED`, failing with `ERR_INVALID_STATE` otherwise. A buyer's `exposure_cents` is a computed figure: the sum of `invoice_total_cents` over exactly that buyer's orders sitting in `SUBMITTED` or `ALLOCATED` — orders in `DRAFT`, `CLOSED`, `CANCELLED`, or `EXPIRED` contribute nothing. A wholesale buyer may read only its own account.

Once the season posture reaches `BOOKING`, a `WholesaleBuyer` builds its order book. Creating a **WholesaleOrder** names the `season_id`, the `buyer_account_id` (which must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN`), the `species`, the `height_class`, the `quantity` of trees (at least one), and the agreed `unit_price_cents` (at least zero). Orders are born `DRAFT` with `allocated_qty` at zero; creation outside `BOOKING` is refused with `ERR_POSTURE_FORBIDS`. The order list supports filters on `buyer_account_id`, `season_id`, and `status`, and a buyer sees only its own orders.

Submitting an order is the fiscal act. Submission requires the season still in `BOOKING` and the buyer in `GOOD_STANDING` — a buyer on hold or closed is rejected with `ERR_BUYER_CREDIT_HOLD` (HTTP 422). The system then computes the invoice. The `invoice_subtotal_cents` is the product of `quantity` and `unit_price_cents`, an exact integer product. A volume tier is selected by quantity: five percent off when at least 200 trees are ordered, eight percent when at least 500, three percent when at least 100, and no discount below 100 — each threshold inclusive. The chosen fraction is recorded in `discount_pct_applied`, and `invoice_discount_cents` is that fraction multiplied by the *rounded subtotal*, rounded half-up to whole cents — never a single rounding of the net product. The `invoice_total_cents` is the subtotal minus the discount. All three invoice fields are null until the order is submitted. The credit check follows: the buyer's current `exposure_cents` plus this order's `invoice_total_cents` must not exceed the buyer's `credit_limit_cents`, with a sum exactly equal to the limit permitted; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422). A successful submission stamps `submitted_at` with the logical clock, moves the order `DRAFT` → `SUBMITTED`, and adds the invoice total to the buyer's exposure.

Cancellation mirrors submission. A buyer may cancel its own order, and a `FarmManager` may cancel any order. Cancelling from `DRAFT` is unconditional. Cancelling from `SUBMITTED` or `ALLOCATED` requires that no allocation of the order stands in `CUT` or `LOADED`, failing with `ERR_ORDER_HAS_CUT_ALLOCATIONS` (HTTP 409); on success every `RESERVED` allocation of the order is released back to its bucket (each bucket's `reserved_count` is restored by the released quantity) and the buyer's exposure is relieved of the invoice total. `CANCELLED` is terminal, as are `CLOSED` and `EXPIRED`.

### 3.4. Reserving Inventory: The Allocation Waterfall

A `SUBMITTED` order is a promise without trees until a `FarmManager` allocates against it — an operation permitted in `BOOKING` or `HARVEST` posture. This is the API's second optimistic-concurrency point: the request must carry `expected_order_version` equal to the order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a prior allocation or an ops-run backfill may already have advanced the order since the client last read it. The request also names how many trees to reserve via `quantity`.

Allocation follows a strict waterfall over the season's standing inventory. The eligible pool is every stand bucket whose lot's `species` matches the order's `species`, whose `height_class` matches the order's `height_class`, whose lot is `ACTIVE`, and whose `available_count` is at least one. Eligible buckets are ranked oldest cohort first — ascending `planted_year`, then ascending lot creation time, then ascending bucket creation time as the final tie-break. The waterfall fills at most the smaller of the requested `quantity` and the order's unallocated remainder (the order's `quantity` minus its current `allocated_qty`). Walking the ranked pool, each bucket contributes the smaller of the remaining need and its own availability; each contribution creates an **Allocation** in `RESERVED` status recording the `order_id`, the `bucket_id`, and the reserved `quantity`, with its `cut_qty` and `loaded_qty` starting at zero, and adds that quantity to the bucket's `reserved_count`. The walk stops as soon as the remaining need reaches zero. If the eligible pool is empty or every eligible bucket has zero availability — so not a single tree could be reserved — the request fails outright with `ERR_NO_ELIGIBLE_INVENTORY` (HTTP 422); there is no deferred queue. The response reports the `order_id`, the trees reserved by this call (`allocated_now`), the order's cumulative `allocated_total`, the created `allocation_ids`, and the resulting `order_status` and `order_version`.

Order status tracks reservation coverage automatically. When `allocated_qty` reaches the full `quantity` — whether through an explicit allocate call, an ops-run backfill, or a recompute after a release — the order moves `SUBMITTED` → `ALLOCATED`. Conversely, whenever a release or an over-reservation sweep leaves `allocated_qty` below `quantity`, an `ALLOCATED` order regresses to `SUBMITTED`. This `SUBMITTED` ↔ `ALLOCATED` loop can cycle any number of times.

Individual reservations can be unwound: a `FarmManager` may release an allocation that is still `RESERVED`, which returns its full `quantity` to the bucket's `reserved_count`, deducts it from the order's `allocated_qty` (regressing the order as above), and moves the allocation to `RELEASED`. Releasing an allocation in any other state fails with `ERR_INVALID_STATE`. Allocations are readable by the owner, the farm manager, and the buyer whose order they serve, and the allocation list filters by `order_id`, `bucket_id`, and `status`.

### 3.5. Harvest Crews and Cut-and-Bale Tickets

Harvest labor is organized into **Crews**, hired by a `FarmManager` for a season with a `crew_code` unique within that season and a crew `size` of at least one worker. Hiring is allowed in any posture except `CLOSED`. A crew is born `ACTIVE` and can be moved to terminal `LAID_OFF` by the farm manager. The crew list filters by `season_id`.

Once per working day, a `CrewLead` posts a **HarvestTicket** — the cut-and-bale record for the day — naming the `crew_id` (which must equal the caller's `X-User-ID`), the `block_id` worked, the calendar `work_date`, the `hours_worked` (greater than zero), and at least one line in `lines`, each line pairing an `allocation_id` with an integer `cut_count` of at least one. A ticket is born `POSTED` — there is no draft stage — and a battery of guards protects it. The season must be in `HARVEST` posture (`ERR_POSTURE_FORBIDS`). The `work_date` must fall within the season's harvest window, both boundary dates inclusive, else `ERR_OUTSIDE_HARVEST_WINDOW` (HTTP 422). The block's `rotation_state` must be `HARVESTABLE` (`ERR_BLOCK_NOT_HARVESTABLE`, HTTP 409). The crew must be `ACTIVE` (`ERR_CREW_NOT_ACTIVE`, HTTP 409), and a crew may hold at most one `POSTED` ticket per calendar date — whole-day occupation with date-equality semantics — with a second ticket on the same `work_date` rejected as `ERR_CREW_DOUBLE_BOOKED` (HTTP 409). Every line's allocation must belong to a crop lot of the ticket's own block, else `ERR_TICKET_BLOCK_MISMATCH` (HTTP 422), and no line may cut more than its allocation's uncut remainder — the allocation's `quantity` minus its `cut_qty` — else `ERR_CUT_EXCEEDS_ALLOCATION` (HTTP 422).

A posted ticket moves real inventory. For each line, the allocation's `cut_qty` grows by the line's `cut_count`, and an allocation whose `cut_qty` reaches its full `quantity` moves `RESERVED` → `CUT`. The bucket behind each line loses the cut trees from `standing_count`, releases them from `reserved_count`, and accrues them into `cut_cumulative`. A ticket that empties the last of a lot's buckets can tip the lot into `DEPLETED`.

Pay is computed at creation and frozen on the ticket. The piece side values each line at the per-tree piece rate for the line's height class — resolved through the line's allocation to its bucket — where the rates in cents are 180 for `H_4_5`, 220 for `H_5_6`, 260 for `H_6_7`, 310 for `H_7_8`, 380 for `H_8_9`, and 460 for `H_9_PLUS`; each line's product is rounded half-up to whole cents first, and the line amounts are then summed into `piece_total_cents`. The floor side, `hourly_floor_cents`, is the crew's `size` multiplied by the ticket's `hours_worked` multiplied by a statutory minimum of 1500 cents per worker-hour. The ticket's `gross_pay_cents` is the larger of the two sides, and `pay_basis` records which side supplied it — `PIECE` or `HOURLY_FLOOR` — with an exact tie resolving to `PIECE`.

A `FarmManager` may void a `POSTED` ticket, but only while the season remains in `HARVEST` and only when no line's allocation has already been loaded onto a truck; either violation yields `ERR_TICKET_NOT_VOIDABLE` (HTTP 409). Voiding is a full compensating reversal: each line's `cut_count` is deducted from its allocation's `cut_qty` (an allocation that drops below full cut reverts from `CUT` to `RESERVED`), and each bucket's `standing_count`, `reserved_count`, and `cut_cumulative` are restored by the line's count. The ticket itself moves to terminal `VOIDED`. The ticket list filters by `crew_id` and `block_id`, and a crew lead sees only its own crew's tickets.

### 3.6. Building and Shipping Wholesale Loads

Cut trees leave the farm on **Loads**. A `FarmManager` creates a load for a `season_id` with a `carrier_name`, a truck `capacity_units` of at least one, and a dock pickup window bounded by `pickup_window_start` and `pickup_window_end`. Creation requires the season in `HARVEST` or `SHIPPING` posture. The pickup window must lie inside the season's shipping window — the start no earlier than `shipping_window_start`, the end no later than the inclusive `shipping_window_end`, and the end strictly after the start — with violations rejected as `ERR_OUTSIDE_SHIPPING_WINDOW` (HTTP 422). Dock scheduling also enforces a thirty-minute buffer between trucks: a new load conflicts with any other non-cancelled load of the season when the new window's start falls before the other load's window end plus thirty minutes and the other load's window start falls before the new window's end plus thirty minutes; a gap of exactly thirty minutes between windows is permitted and is not a conflict. Conflicts are rejected with `ERR_DOCK_WINDOW_CONFLICT` (HTTP 409). A load is born `BUILDING` with empty `lines` and `total_units` at zero; the load list filters by `season_id`.

While the season is in `HARVEST`, the farm manager fills a building load line by line, each line naming an `allocation_id` and a `quantity`. The allocation must be in `CUT` status with enough cut-but-unloaded headroom — the quantity may not exceed the allocation's `cut_qty` minus its `loaded_qty` — else `ERR_ALLOCATION_NOT_CUT` (HTTP 409). Capacity is enforced in abstract tree-units: each height class weighs 1 unit for `H_4_5`, 2 for `H_5_6`, 3 for `H_6_7`, 5 for `H_7_8`, 7 for `H_8_9`, and 9 for `H_9_PLUS`, and each appended line contributes its `quantity` multiplied by the weight of its allocation's height class — recorded on the line as its `units`. A line that would push the load's `total_units` above `capacity_units` is rejected with `ERR_LOAD_OVER_CAPACITY` (HTTP 422); a load filled to exactly capacity is legal. Each accepted line grows the allocation's `loaded_qty`, and an allocation whose `loaded_qty` reaches its `cut_qty` moves `CUT` → `LOADED`. When an order is fully allocated and every one of its non-released allocations has reached `LOADED`, the order closes itself: it moves `ALLOCATED` → `CLOSED` and the buyer's `exposure_cents` is relieved of the order's `invoice_total_cents`.

Shipping is deliberately simple: while the season is in `SHIPPING` posture and the logical clock sits inside the shipping window — both boundary instants inclusive — the farm manager ships a `BUILDING` load, moving it to terminal `SHIPPED`. A clock outside that window fails with `ERR_OUTSIDE_SHIPPING_WINDOW`. A building load may instead be cancelled in any posture except `CLOSED`; cancellation rolls every line's quantity back off its allocation's `loaded_qty` (an allocation that drops below full loading reverts from `LOADED` to `CUT`), and while the affected order's all-loaded status is recomputed, a load cancellation never closes an order by itself.

### 3.7. Retail Channels: Choose-and-Cut Tags and Lot Consignments

Two retail channels draw on the same standing inventory as the wholesale book. The first is the choose-and-cut gate. During `HARVEST` posture, a `FarmManager` sells a **UcutTag** naming the `block_id`, the `bucket_id` whose height class the customer wants, the `customer_name`, and the gate `price_cents`. The block must be `HARVESTABLE` (`ERR_BLOCK_NOT_HARVESTABLE`), must be flagged `ucut_designated` (`ERR_BLOCK_NOT_UCUT`, HTTP 422), must be the very block hosting the bucket's lot, and the bucket must have at least one tree standing (`ERR_BUCKET_EMPTY`, HTTP 422). The tree is claimed the moment the tag is sold: the bucket's `standing_count` drops by one and its `tagged_active_count` rises by one. Each tag carries an `expires_at` set exactly forty-eight hours after its creation on the logical clock, and the tag is born `ACTIVE`.

Three fates await an active tag. When the customer cuts their tree, redeeming the tag — a `HARVEST`-posture operation — moves it to terminal `REDEEMED`: the bucket's `tagged_active_count` drops by one and `ucut_sold_cumulative` rises by one, the tree now permanently gone from the field ledger. Releasing a tag early, also a `HARVEST`-posture operation, moves it to terminal `RELEASED` and returns the tree to the pool: `tagged_active_count` drops by one and `standing_count` rises by one. Finally, the ops-run checkpoint sweeps any active tag whose `expires_at` has been reached to terminal `EXPIRED` with the same return-to-pool effect. The tag list filters by `block_id`, `bucket_id`, and `status`.

The second channel is retail-lot consignment. A `FarmManager` drafts a **Consignment** during `BOOKING` or `HARVEST`, naming the `season_id`, the source `bucket_id`, the retail partner's `lot_name`, the planned `quantity` of trees, the per-tree `unit_price_cents`, and the contractual `max_return_pct` — a fraction between zero and one inclusive bounding the share of delivered trees the lot may return unsold. The contract is born `DRAFT` with `returned_count` at zero; the consignment list filters by `season_id` and `bucket_id`.

Delivery draws real inventory during `HARVEST` or `SHIPPING`: the call carries `delivered_count`, which must be at least one and no more than the bucket's `available_count`, else `ERR_INSUFFICIENT_STANDING` (HTTP 422). The bucket's `standing_count` falls by the delivered amount and `consigned_cumulative` accrues it. At the same moment the system computes a **provisional settlement**: the delivered count multiplied by the per-tree price, multiplied by one minus the contractual maximum return fraction, rounded half-up to whole cents, and recorded as `provisional_settlement_cents`. The provisional figure is deliberately conservative — it assumes returns at the contractual worst case, before any returns are known. The consignment moves `DRAFT` → `DELIVERED`, and `delivered_count` is null until this point.

As the season winds down, the lot reports unsold trees. A report carries the cumulative `returned_count` — the running total of trees returned so far, never below zero and never above `delivered_count`, else `ERR_RETURN_EXCEEDS_DELIVERED` (HTTP 422). The first report, permitted in `SHIPPING` or `SETTLEMENT` posture, moves the consignment `DELIVERED` → `SETTLING`. Settlement proper requires `SETTLEMENT` posture: it computes the **final settlement** as the delivered count minus the reported returns, multiplied by the per-tree price, rounded half-up to whole cents, and records it as `final_settlement_cents` — identical delivery data yields a different final amount whenever actual returns differ from the worst case assumed provisionally. Settlement moves the consignment to terminal `SETTLED`. When the parties disagree, the farm manager may instead dispute a `SETTLING` consignment during `SETTLEMENT`, moving it to `DISPUTED`; a later re-report of returns — again bounded by zero and `delivered_count`, and only in `SETTLEMENT` — brings it back to `SETTLING`. This `SETTLING` ↔ `DISPUTED` renegotiation loop can cycle until the parties settle.

### 3.8. The Ops-Run Checkpoint and Closing the Season

Seasonal administration runs through an `Owner`-driven ops-run checkpoint. Each invocation performs four steps in order. First, every choose-and-cut tag of the season still `ACTIVE` whose `expires_at` is at or before the logical clock — a tag expiring exactly now expires — moves to `EXPIRED`, returning its tree to the bucket's standing pool. Second, every wholesale order of the season still in `DRAFT` when the clock has passed `booking_close_at` moves to terminal `EXPIRED`. Third — only while the posture is `BOOKING` or `HARVEST` — the backfill walks every `SUBMITTED` order of the season whose `allocated_qty` still falls short of its `quantity`, oldest `submitted_at` first with creation time ascending as the tie-break, and runs the allocation waterfall for each order's unallocated remainder. Fourth, the season's `ops_run_index` increments by one, marking the checkpoint.

Between checkpoints, the `Owner` walks the season forward one posture at a time by naming the immediate next `target_posture`. Each step has its own guard, and a failed guard is rejected with `ERR_POSTURE_GUARD_FAILED` (HTTP 409). Opening the book — `PLANNING` → `BOOKING` — requires the logical clock to have reached `booking_open_at`. Opening harvest — `BOOKING` → `HARVEST` — requires the clock to have reached the season's `harvest_window_start` read as midnight UTC, and requires that no order of the season remains in `DRAFT` (the run-ops expiry sweep is the mechanism that clears stragglers). Opening shipping — `HARVEST` → `SHIPPING` — requires that no allocation on the season's orders remains in `RESERVED` or `CUT`: everything promised must be loaded, released, or otherwise resolved. Opening settlement — `SHIPPING` → `SETTLEMENT` — requires that no load of the season remains in `BUILDING`. Closing the season — `SETTLEMENT` → `CLOSED`, terminal — requires that no consignment of the season remains in `DELIVERED`, `SETTLING`, or `DISPUTED`: every retail-lot account must be settled first.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that read, modify, or act upon an existing resource — including all state-transition actions, the ops-run checkpoint, and the logical-clock setter — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock (startup default 2026-05-01T00:00:00Z) | Owner |
| POST | `/api/seasons` | Create a season in `PLANNING` posture | Owner |
| GET | `/api/seasons/{id}` | Read a season | Owner, FarmManager, WholesaleBuyer, CrewLead |
| POST | `/api/seasons/{id}/advance-posture` | Advance posture exactly one step forward | Owner |
| POST | `/api/seasons/{id}/run-ops` | Run the ops checkpoint sweeps and backfill | Owner |
| POST | `/api/blocks` | Create a block in `RESTING` rotation | FarmManager |
| GET | `/api/blocks/{id}` | Read a block | Owner, FarmManager |
| GET | `/api/blocks` | List blocks, filterable by season | Owner, FarmManager |
| POST | `/api/blocks/{id}/advance-rotation` | Advance the block rotation one step | FarmManager |
| POST | `/api/crop-lots` | Plant a crop lot on a `RESTING` block | FarmManager |
| GET | `/api/crop-lots/{id}` | Read a crop lot | Owner, FarmManager |
| GET | `/api/crop-lots` | List crop lots, filterable by block | Owner, FarmManager |
| GET | `/api/crop-lots/{id}/stand-buckets` | List a lot's stand buckets in height-class order | Owner, FarmManager |
| GET | `/api/crop-lots/{id}/surveys` | List a lot's surveys | Owner, FarmManager |
| POST | `/api/surveys` | Create a survey in `DRAFT` | FarmManager |
| POST | `/api/surveys/{id}/post` | Post a survey, re-baselining buckets (OCC on the lot) | FarmManager |
| POST | `/api/buyer-accounts` | Create a wholesale buyer account | Owner |
| GET | `/api/buyer-accounts/{id}` | Read a buyer account (buyers: own only) | Owner, WholesaleBuyer |
| POST | `/api/buyer-accounts/{id}/set-standing` | Set buyer standing | Owner |
| POST | `/api/wholesale-orders` | Create a `DRAFT` wholesale order | WholesaleBuyer |
| GET | `/api/wholesale-orders/{id}` | Read an order (buyers: own only) | Owner, FarmManager, WholesaleBuyer |
| GET | `/api/wholesale-orders` | List orders (buyers: own only) | Owner, FarmManager, WholesaleBuyer |
| POST | `/api/wholesale-orders/{id}/submit` | Submit a `DRAFT` order, computing the invoice | WholesaleBuyer |
| POST | `/api/wholesale-orders/{id}/cancel` | Cancel an order with no cut or loaded allocations | WholesaleBuyer, FarmManager |
| POST | `/api/wholesale-orders/{id}/allocate` | Allocate inventory to an order via the waterfall (OCC on the order) | FarmManager |
| GET | `/api/allocations/{id}` | Read an allocation | Owner, FarmManager, WholesaleBuyer |
| GET | `/api/allocations` | List allocations | Owner, FarmManager, WholesaleBuyer |
| POST | `/api/allocations/{id}/release` | Release a `RESERVED` allocation | FarmManager |
| POST | `/api/crews` | Hire a crew | FarmManager |
| GET | `/api/crews/{id}` | Read a crew | Owner, FarmManager, CrewLead |
| GET | `/api/crews` | List crews | Owner, FarmManager, CrewLead |
| POST | `/api/crews/{id}/lay-off` | Lay off an `ACTIVE` crew | FarmManager |
| POST | `/api/harvest-tickets` | Post a day's cut-and-bale ticket (born `POSTED`) | CrewLead |
| GET | `/api/harvest-tickets/{id}` | Read a ticket | Owner, FarmManager, CrewLead |
| GET | `/api/harvest-tickets` | List tickets (crew leads: own crew only) | Owner, FarmManager, CrewLead |
| POST | `/api/harvest-tickets/{id}/void` | Void a `POSTED` ticket with full reversal | FarmManager |
| POST | `/api/loads` | Create a `BUILDING` load with a dock pickup window | FarmManager |
| GET | `/api/loads/{id}` | Read a load | Owner, FarmManager |
| GET | `/api/loads` | List loads | Owner, FarmManager |
| POST | `/api/loads/{id}/lines` | Add cut trees to a building load | FarmManager |
| POST | `/api/loads/{id}/ship` | Ship a building load | FarmManager |
| POST | `/api/loads/{id}/cancel` | Cancel a building load, rolling back lines | FarmManager |
| POST | `/api/consignments` | Create a `DRAFT` consignment contract | FarmManager |
| GET | `/api/consignments/{id}` | Read a consignment | Owner, FarmManager |
| GET | `/api/consignments` | List consignments | Owner, FarmManager |
| POST | `/api/consignments/{id}/deliver` | Deliver trees to the retail lot | FarmManager |
| POST | `/api/consignments/{id}/report-return` | Report cumulative unsold returns | FarmManager |
| POST | `/api/consignments/{id}/settle` | Settle a `SETTLING` consignment | FarmManager |
| POST | `/api/consignments/{id}/dispute` | Dispute a `SETTLING` consignment | FarmManager |
| POST | `/api/ucut-tags` | Sell a choose-and-cut tag at the gate | FarmManager |
| GET | `/api/ucut-tags/{id}` | Read a tag | Owner, FarmManager |
| GET | `/api/ucut-tags` | List tags | Owner, FarmManager |
| POST | `/api/ucut-tags/{id}/redeem` | Redeem an `ACTIVE` tag | FarmManager |
| POST | `/api/ucut-tags/{id}/release` | Release an `ACTIVE` tag back to the pool | FarmManager |
| POST | `/api/cull-records` | Record shrink or cull on a bucket | FarmManager |
| GET | `/api/cull-records/{id}` | Read a cull record | Owner, FarmManager |
| GET | `/api/cull-records` | List cull records | Owner, FarmManager |
| POST | `/api/replant-plans` | Propose replanting a `HARVESTED` block | FarmManager |
| GET | `/api/replant-plans/{id}` | Read a replant plan | Owner, FarmManager |
| GET | `/api/replant-plans` | List replant plans | Owner, FarmManager |
| POST | `/api/replant-plans/{id}/approve` | Approve a replant plan (segregation of duties) | Owner |
| POST | `/api/replant-plans/{id}/reject` | Reject a replant plan (segregation of duties) | Owner |
| POST | `/api/replant-plans/{id}/execute` | Execute an `APPROVED` plan, creating the successor lot | FarmManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_MALFORMED_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_POSTURE_FORBIDS` | 409 Conflict |
| `ERR_POSTURE_GUARD_FAILED` | 409 Conflict |
| `ERR_OUTSIDE_HARVEST_WINDOW` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_SHIPPING_WINDOW` | 422 Unprocessable Entity |
| `ERR_BLOCK_NOT_HARVESTABLE` | 409 Conflict |
| `ERR_BLOCK_OCCUPIED` | 409 Conflict |
| `ERR_BLOCK_NOT_UCUT` | 422 Unprocessable Entity |
| `ERR_CREW_NOT_ACTIVE` | 409 Conflict |
| `ERR_BUYER_CREDIT_HOLD` | 422 Unprocessable Entity |
| `ERR_TICKET_BLOCK_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_NOT_CUT` | 409 Conflict |
| `ERR_TICKET_NOT_VOIDABLE` | 409 Conflict |
| `ERR_ORDER_HAS_CUT_ALLOCATIONS` | 409 Conflict |
| `ERR_NO_ELIGIBLE_INVENTORY` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STANDING` | 422 Unprocessable Entity |
| `ERR_CULL_EXCEEDS_STANDING` | 422 Unprocessable Entity |
| `ERR_BUCKET_EMPTY` | 422 Unprocessable Entity |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_DOCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_LOAD_OVER_CAPACITY` | 422 Unprocessable Entity |
| `ERR_CUT_EXCEEDS_ALLOCATION` | 422 Unprocessable Entity |
| `ERR_RETURN_EXCEEDS_DELIVERED` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
