# Industrial Laundry Plant API — Product Requirements Document

## 1. Introduction

An industrial laundry plant serving healthcare and hospitality customers lives and dies by two flows that never stop moving: dirty linen coming back from customer sites on route trucks, and clean linen going out again against promised quantities. Between those two flows sit the physical processes that determine whether the plant makes money — sorting and classification, washing under the right chemical or thermal formula, hygienic verification for infection-sensitive categories, ironing and folding at line speed, and the slow bleed of linen loss at every hand-off. Around those physical processes sits a commercial layer just as intricate: some customers rent the plant's linen and pay per piece-day, others ship their own goods and pay per pound washed, RFID-chipped garments must be accounted for individually, shortage disputes turn into credits, and energy and water overconsumption has to be passed through fairly.

This document specifies the REST API that operates such a plant end to end. It covers route and stop management with declared versus scale-verified soiled weights; sort batches whose reject rates can trip plant-level alerts; wash loads governed by machine scheduling, hygienic testing, and a bounded rewash escalation ladder; finish runs with throughput accounting and buffered line scheduling; chip-tracked garments with a full custody state machine and lost-item charging; deliveries with shortage and overage reconciliation, customer confirmation, and dispute settlement; and a billing engine that produces draft invoices under two fundamentally different charging models, layers a tiered utility surcharge on top, applies discrepancy credits, and enforces per-customer credit limits with optimistic concurrency control on the customer's balance.

The intended readers are the engineers who will implement this API and the product stakeholders who will validate it. Every behavior described here is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the acting role. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to call the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes exactly six roles, spelled as follows: `PlantAdmin`, `RouteDriver`, `PlantOperator`, `CustomerServiceRep`, `BillingClerk`, and `CustomerContact`.

- A `PlantAdmin` administers the plant itself: creating plants, linen categories, and customers, upserting par levels, registering chip-tracked garments, suspending and resuming customers, and driving the logical clock. When `X-User-Role` is `PlantAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `RouteDriver` plans and runs routes: creating routes and stops, dispatching, completing, and reconciling routes, arriving at and picking up stops, manifesting deliveries, and recording physical deliveries. When `X-User-Role` is `RouteDriver`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `PlantOperator` works the plant floor: receiving and voiding carts, running sort batches, staging and driving wash loads through their lifecycle, tallying and posting finish runs, and loading garments out. When `X-User-Role` is `PlantOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `CustomerServiceRep` handles after-service care: reviewing, approving, and rejecting discrepancies, and marking garments lost. When `X-User-Role` is `CustomerServiceRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `BillingClerk` runs the money: generating, issuing, paying, and voiding invoices, applying approved credits, posting monthly utility readings, and reading billing previews. When `X-User-Role` is `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `CustomerContact` is the customer-side counterpart. When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID`. A `CustomerContact` confirms or disputes deliveries belonging to their own customer, and may read their own customer's data; any attempt to act on or read another customer's resources is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

A request that matches no route fails with `ERR_NOT_FOUND` (HTTP 404); a matched path called with an unsupported method fails with `ERR_INVALID_REQUEST` at HTTP 405; an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500), in the same envelope.

### 2.3. Pagination

All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0; out-of-range values are clamped to the nearest bound rather than rejected, and non-integer values fall back to the defaults. List responses are always sorted by `created_at` in ascending order, with ties broken by creation order (earlier-created first). The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

Individual list endpoints may accept additional filter query parameters specific to the resource — for example `billing_mode` and `status` on the customer list, `status` and `service_date` on the route list, `machine_id`, `status`, and `category_id` on the plant wash-load list, `line_id` and `status` on the plant finish-run list, `state` on the customer garment list, `status` on the plant sort-batch and invoice lists, `period_month` on the utility-reading list, `batch_id` and `category_id` on the global sort-item list, and `customer_id`, `category_id`, `state`, and `chip_code` on the global garment list.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` field: a server-minted UUID with no type prefix, rendered in the canonical hyphenated string form — five lowercase hexadecimal groups separated by hyphens in the pattern 8-4-4-4-12 (for example, `3f6b2a1c-7e4d-4f2a-9c1b-8d5e6f7a8b9c`). Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set at creation.

All resources except `UtilityReading` additionally carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource. `UtilityReading` is an immutable monthly posting and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

The `version` field is the foundation of optimistic concurrency control (§2.7). Note that several workflows bump a `Customer`'s `version`: marking a delivery delivered, issuing an invoice, marking an invoice paid, and applying a discrepancy credit each increment the customer's `version` by one. Of these, issuing, paying, and credit application also change `account_balance_cents`; marking a delivery delivered changes only the version. By contrast, upserting a par-level row does not touch the customer's `version` at all — the par-level row carries its own `version` and the customer record is left untouched.

### 2.5. The Logical Plant Clock

The server maintains a logical clock rather than reading wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly 2026-05-01T00:00:00Z, and the server must never fall back to wall-clock time. A `PlantAdmin` may advance or set the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting current UTC reading in a body field named `current_utc`. All timestamps the server stamps — `created_at`, `updated_at`, `lost_at`, unload times — are taken from this logical clock. Timestamps accepted in request bodies are parsed as ISO 8601; values without an explicit UTC offset are interpreted as UTC.

### 2.6. Units, Precision, and Rounding

Money is always represented as integer cents; fields such as `credit_limit_cents`, `account_balance_cents`, `replacement_cost_cents`, `cog_wash_rate_cents_per_lb`, `linen_charges_cents`, `lost_item_charges_cents`, `utility_surcharge_cents`, `credits_cents`, `total_due_cents`, `credit_cents`, `kwh_rate_cents`, and `gallon_rate_cents` are whole-cent integers. Wherever a monetary intermediate result must be rounded, it is rounded half-up to whole cents.

Weights (such as `piece_weight_lb`, `declared_soiled_weight_lb`, `actual_soiled_weight_lb`, `scale_weight_lb`, and `clean_weight_lb`), rates (such as `reject_rate_pct`, `reject_rate_alert_pct`, `utility_baseline_kwh_per_lb`, and `utility_baseline_gal_per_lb`), and `throughput_pieces_per_hour` are decimal quantities. Unless a rule states otherwise, computed decimal results are rounded half-up to 2 decimal places. One exception is the customer share percentage used by the utility surcharge, which is rounded half-up to 4 decimal places.

### 2.7. Optimistic Concurrency Control

Two write operations act on a customer's financial position and therefore require the caller to prove it has observed the customer's current state.

- Issuing an invoice requires the request to carry `expected_customer_version`, the `version` of the invoice's customer as last observed by the client. If the customer's current `version` does not match — because, for example, another writer has since posted a utility surcharge true-up or applied a credit, both of which mutate `account_balance_cents` and bump the customer's `version` — the issue is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Marking a delivery delivered likewise requires the request to carry `expected_customer_version` matching the current `version` of the customer on the delivery's stop. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since `account_balance_cents`, and therefore the credit-limit precondition, may have changed since the driver last read the customer.

Endpoints other than these two do not take a version field.

### 2.8. Machine and Line Scheduling Discipline

Wash machines and finishing lines are shared physical resources, and the system defends their schedules with two distinct interval disciplines.

A wash load occupies its `machine_id` over the half-open interval from `scheduled_start` (inclusive) to `scheduled_end` (exclusive). A conflict exists when another wash load on the same `machine_id`, in any of the states `STAGED`, `RUNNING`, `AWAITING_TEST`, or `REWASH_PENDING`, has an interval satisfying: the other load's start is strictly before this load's end, and this load's start is strictly before the other load's end. Under half-open semantics, adjacent loads — where one load's `scheduled_end` equals the other's `scheduled_start` — are allowed. A conflicting start is rejected with `ERR_MACHINE_TIME_OVERLAP` (HTTP 409).

A finish run occupies its `line_id` over a buffered closed interval: from ten minutes before `scheduled_start` through ten minutes after `scheduled_end`, both endpoints inclusive. A conflict exists when another finish run on the same `line_id`, in state `QUEUED` or `TALLIED`, has its own buffered closed interval intersecting this one; two closed intervals intersect when the first interval's start is less than or equal to the second interval's end, and the second interval's start is less than or equal to the first interval's end. A conflicting tally is rejected with `ERR_LINE_TIME_OVERLAP` (HTTP 409). Because the buffer is closed, two runs whose buffered edges merely touch are in conflict, unlike wash machines where touching is permitted.

For both kinds of scheduling, `scheduled_end` must be strictly later than `scheduled_start`; a non-positive duration is rejected with `ERR_INVALID_TIME_RANGE` (HTTP 422).

### 2.9. Validation Pipeline and Check Ordering

Incoming requests are validated in a fixed priority order, so that when several problems are present the earliest check is the one reported. The order is:

1. Request-body schema validation: required fields present, types correct, quantities non-negative, piece counts at least 1, `reject_reason` present if and only if `disposition` is `REJECTED` (present on an `ACCEPTED` row or absent on a `REJECTED` row is a schema violation), `billing_period_end` strictly after `billing_period_start`, and enum members drawn from their declared value sets. Failures surface as `ERR_INVALID_REQUEST` (HTTP 400). This check applies to every endpoint that takes a request body.
2. Presence and well-formedness of the `X-User-ID` and `X-User-Role` headers — `ERR_UNAUTHENTICATED` (HTTP 401). Applies to all endpoints.
3. Role permission for the target endpoint — `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Applies to all endpoints.
4. Existence of path resources, validated left to right along the URL hierarchy (plant first, then each nested resource in turn) — `ERR_NOT_FOUND` (HTTP 404). Applies to all nested endpoints.
5. Existence of entity ids referenced in the request body (such as `customer_id`, `category_id`, `batch_id`, `invoice_id`) — `ERR_REFERENCED_NOT_FOUND` (HTTP 404). Applies to all creation endpoints.
6. State admissibility: the target resource must be in a state that permits the requested transition — `ERR_INVALID_STATE` (HTTP 409). Applies to all state-transition endpoints.
7. Hygienic-testing discipline: a load whose category requires hygienic testing must record a test outcome before it can be unloaded, and the bypass path is available only for categories that do not require testing — `ERR_TEST_REQUIRED` (HTTP 422). Applies to the test-bypass and unload actions on wash loads.
8. Category membership: a staged wash load's `category_id` must match a category present with disposition `ACCEPTED` in the linked sort batch — `ERR_CATEGORY_NOT_IN_BATCH` (HTTP 422). Applies to wash-load staging.
9. Temporal integrity: the wash-machine half-open overlap guard, the finish-line buffered closed-interval overlap guard, and the strictly-increasing time-range requirement — surfaced as `ERR_MACHINE_TIME_OVERLAP`, `ERR_LINE_TIME_OVERLAP`, or `ERR_INVALID_TIME_RANGE` (HTTP 409 for the two overlap codes, 422 for the time range). Applies across wash-load staging, wash-load starting, finish-run queuing, and finish-run tallying.
10. Uniqueness: the pair of stop and `cart_tag` must be unique within a stop — `ERR_DUPLICATE_CART_TAG` (HTTP 409) — while `chip_code` must be globally unique and the pair of plant and `period_month` must be unique among utility readings — `ERR_DUPLICATE` (HTTP 409). Applies to soiled-cart creation via pickup, garment registration, and utility-reading posting. (Par-level upsert is not on this list: it keeps the customer–category pair unique by updating the existing row instead of rejecting; see §3.1.)
11. Credit limit: neither a delivery nor an invoice issue may push the customer past `credit_limit_cents` — `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Applies to marking a delivery delivered and to issuing an invoice.
12. Credit-target integrity: a discrepancy credit's target invoice must belong to the same customer and must be in `DRAFT` — `ERR_INVOICE_CUSTOMER_MISMATCH` or `ERR_INVOICE_NOT_DRAFT` (HTTP 409). Applies to credit application.
13. Optimistic concurrency: a supplied `expected_customer_version` must match the customer's current `version` — `ERR_STALE_VERSION` (HTTP 412). Applies to exactly the two endpoints named in §2.7.

### 2.10. Resource Hierarchy and Nested Retrieval

The resource tree is rooted at the plant. A `Plant` owns `Customer` records, `LinenCategory` records, `Route` records, `SortBatch` records, `WashLoad` records, `FinishRun` records, and `UtilityReading` records, each stamped with its `plant_id`. A `Customer` owns `CustomerParLevel` rows, `Garment` records, and `Invoice` records through `customer_id`. A `Route` owns `RouteStop` records through `route_id`; a `RouteStop` owns `SoiledCart` records and `Delivery` records through `stop_id`; a `SortBatch` owns `SortItem` rows through `batch_id`; a `Delivery` owns `Discrepancy` records through `delivery_id`; a `FinishRun` points back to its `WashLoad` through `wash_load_id`.

On any nested URL, path parameters are validated left to right: the plant is resolved first, then each successive nested resource; the first id that does not resolve fails the whole request with `ERR_NOT_FOUND`, before any body or state check runs. Because several entities reference their parents by foreign key rather than living strictly under them in the URL space, the API also exposes reverse-reachability list endpoints — for example the stops of a customer, the par levels referencing a category, or the wash loads of a sort batch — each returning the children that point at the named parent.

## 3. Business Logic & Workflows

### 3.1. Plant Configuration, Customer Enrollment, and the Linen Catalog

Everything begins with a `PlantAdmin` standing up the plant. Creating a plant requires a `name` and four policy numbers that govern alerting and surcharges for everything that follows: `reject_rate_alert_pct`, the reject-rate percentage at or above which a sort batch raises an alert; `par_shortage_alert_pieces`, a stored par-shortfall alert threshold on which the server never acts — no par-shortage alert is computed or recorded anywhere in the API; and the utility baselines `utility_baseline_kwh_per_lb` and `utility_baseline_gal_per_lb`, which express how much electricity and water a pound of clean linen is expected to consume before excess pass-through charges accrue.

Under the plant, the administrator defines the linen catalog. Each `LinenCategory` carries a `code` label (something like SHEET_KING or GOWN_ISO; the server does not enforce uniqueness of the code), an average `piece_weight_lb`, a `wash_formula_code` drawn from `WF_STANDARD`, `WF_THERMAL_DISINFECT`, `WF_CHEM_DISINFECT`, and `WF_HEAVY_SOIL`, a boolean `hygienic_test_required` marking categories whose wash loads must pass hygienic verification, a `replacement_cost_cents` charged when a piece is lost from rental stock or condemned from customer-owned stock, and a `cog_wash_rate_cents_per_lb` used when billing customer-owned goods at the standard tier.

Customers enroll under a plant with a `name`, a `customer_kind` of `HEALTHCARE` or `HOSPITALITY`, a `billing_mode` of `RENTAL` or `COG` (COG meaning customer-owned goods, billed per pound washed; RENTAL meaning the plant owns the linen and bills per piece-day), a `chip_tracking_enabled` flag deciding whether this customer's garments carry RFID chips, and a `credit_limit_cents` ceiling on outstanding invoice balance. A newly created customer starts in `ACTIVE` status with an `account_balance_cents` of zero; the balance is a stored running figure — issuing an invoice adds its `total_due_cents`, marking an invoice paid subtracts that total, and applying a discrepancy credit subtracts the credited amount, as §3.7 and §3.8 describe — where a positive value means the customer owes the plant.

A `PlantAdmin` may suspend a customer, moving it from `ACTIVE` to `SUSPENDED`; while suspended, issuing an invoice for that customer is blocked. Resuming moves the customer back from `SUSPENDED` to `ACTIVE`. Suspension and resumption are administrative acts with no other preconditions.

Par levels express how many pieces of each category a customer site must hold. Upserting the par level for a customer and category takes `par_pieces` and creates the row if absent, with `current_on_site_pieces` starting at zero; the pair of customer and category is unique, so re-upserting the same pair updates `par_pieces` rather than duplicating the row — there is no create-only variant and `ERR_DUPLICATE` is never raised by this endpoint, which responds with HTTP 200 whether it created or updated the row. The on-site counter is derived, not entered: it rises when deliveries land at the site and falls when soiled linen is sorted out of it, as later sections describe; neither movement is floored at zero, and a category with no par row for the customer moves no counter. The par row carries its own `version`; upserting it deliberately leaves the customer's `version` unchanged.

### 3.2. Route Planning, Dispatch, and Soiled Pickup

A `RouteDriver` builds the day's work as a `Route` under a plant, supplying the `service_date` (an ISO calendar date) and the assigned `driver_name`. A new route starts `PLANNED`. Stops are added to the route one by one — the route's status does not gate adding a stop — each naming its `customer_id`, a `sequence_index` giving its order within the route (at least 1), and the customer-declared `declared_soiled_weight_lb`. A new stop starts `SCHEDULED` with `actual_soiled_weight_lb` at zero.

Dispatch moves a route from `PLANNED` to `DISPATCHED` and requires at least one stop still in `SCHEDULED` state; dispatching a stop-less route fails with `ERR_ROUTE_HAS_NO_STOPS`. Arrival at a stop moves it from `SCHEDULED` to `ARRIVED`, and is only possible while the parent route is `DISPATCHED` — arriving under an undispatched route fails with `ERR_ROUTE_NOT_DISPATCHED`.

The pickup act moves a stop from `ARRIVED` to `PICKED_UP` and is the point where physical carts enter the system. The driver submits a `carts` payload listing one entry per cart, each entry carrying its physical `cart_tag` and the `scale_weight_lb` read at the plant receiving gate. The cart list must be non-empty — an empty pickup fails with `ERR_EMPTY_PICKUP` — and every `cart_tag` must be unique within the stop, with duplicates rejected as `ERR_DUPLICATE_CART_TAG`; these rejections run in the order stop-state admissibility, then non-empty payload, then tag uniqueness, and the response returns the updated stop. For each payload cart the system creates a `SoiledCart` in `DECLARED` status bearing the declared scale weight. For chip-tracking customers, the same act sweeps every garment of that customer currently `AT_CUSTOMER` into `IN_TRANSIT_SOILED`: the truck is now carrying them.

As carts later arrive at the plant gate, a `PlantOperator` receives each one, moving it from `DECLARED` to `RECEIVED`. Receiving is only possible once the parent stop has been picked up — specifically while the stop is `PICKED_UP`, `DELIVERED`, or `DISPUTED`; otherwise the receive fails with `ERR_STOP_NOT_PICKED_UP`. Each receive recomputes the stop's `actual_soiled_weight_lb` as the sum of `scale_weight_lb` over the stop's carts in `RECEIVED` or `SORTED` state — `DECLARED` and `VOIDED` carts are excluded — and, for chip-tracking customers, advances that customer's garments from `IN_TRANSIT_SOILED` to `SOILED_RECEIVED`. Comparing the stop's declared and actual weights yields the pickup variance: the variance in pounds is the actual weight minus `declared_soiled_weight_lb`, and the variance percentage is that pound difference divided by `declared_soiled_weight_lb` and multiplied by 100 when the declared weight is greater than zero, and zero when it is not, rounded half-up to 2 decimal places. A cart that should never have been logged can be voided while still `DECLARED`, moving it to `VOIDED`; attempting to void a cart in any other state fails with `ERR_CART_NOT_VOIDABLE`.

A route completes when the driver ends the run: moving from `DISPATCHED` to `COMPLETED` requires every stop of the route to be in one of `PICKED_UP`, `DELIVERED`, `CLOSED`, or `DISPUTED`, and any straggler fails the completion with `ERR_ROUTE_STOPS_OPEN`. Reconciliation is the final, terminal step: moving from `COMPLETED` to `RECONCILED` requires every stop to be in `CLOSED` or `DISPUTED` — otherwise `ERR_ROUTE_STOPS_UNRESOLVED` — and additionally requires that no discrepancy on any delivery of any stop of the route still sits in `FILED`, `UNDER_REVIEW`, or `APPROVED`; open review work blocks reconciliation with `ERR_ROUTE_DISCREPANCIES_OPEN`.

### 3.3. Receiving, Sorting, Classification, and Reject Alerts

Back at the plant, a `PlantOperator` opens a `SortBatch` for a stop by referencing its `stop_id`; the batch is stamped with the plant of the stop's route and starts `OPEN` with all counters at zero. Classification work proceeds row by row: each sort item posted into the batch names a `category_id`, a `pieces` count of at least 1, a `disposition` of `ACCEPTED` or `REJECTED`, and — exactly when the disposition is `REJECTED` — a `reject_reason` of `STAIN`, `TEAR`, or `CONTAMINATION`. Supplying a `reject_reason` on an accepted row, or omitting it on a rejected row, is a schema violation rejected with `ERR_INVALID_REQUEST`. As items are posted the batch's counters are recomputed: `total_sorted_pieces` is the total pieces across all rows, `accepted_pieces` the pieces in rows disposed `ACCEPTED`, and `rejected_pieces` the pieces in rows disposed `REJECTED`.

Locking the batch freezes the quality picture. The move from `OPEN` to `LOCKED` requires at least one sorted piece — locking an empty batch fails with `ERR_EMPTY_SORT_BATCH` — and requires the parent stop to be past pickup, that is in `PICKED_UP`, `DELIVERED`, or `DISPUTED`, failing otherwise with `ERR_STOP_NOT_PICKED_UP`. At lock time the batch's `reject_rate_pct` is computed: zero when `total_sorted_pieces` is zero, otherwise the rejected pieces divided by the total sorted pieces, multiplied by 100, and rounded half-up to 2 decimal places. The alert flag `alert_raised` is then set to true exactly when the computed reject rate is greater than or equal to the plant's `reject_rate_alert_pct` — a rate landing exactly on the threshold raises the alert.

If the lock picture looks wrong, unlocking reverts the batch from `LOCKED` back to `OPEN`, resetting `alert_raised` to false and `reject_rate_pct` to zero; unlocking is blocked while any wash load references the batch, failing with `ERR_BATCH_HAS_WASH_LOADS`. Voiding abandons an `OPEN` batch entirely, moving it to `VOIDED` and discarding all of its sort items with the batch counters zeroed; voiding carries the same wash-load guard and fails with `ERR_BATCH_HAS_WASH_LOADS` when a load already exists.

Posting is the point of commitment, moving a batch from `LOCKED` to `POSTED`. Posting cascades in two directions at once. Every cart of the batch's stop still in `RECEIVED` moves automatically to `SORTED` — the physical carts have now been emptied into classification rows. And for each category, the customer par row's `current_on_site_pieces` is decremented by that category's accepted piece count: soiled linen acknowledged at sort time has left the customer site, and the on-site ledger must reflect it.

### 3.4. Wash Operations, Hygienic Testing, and Rewash Escalation

Staging a wash load draws accepted pieces from a sort batch into a machine schedule. The operator supplies the `batch_id`, the `category_id` (a single category per load), the `machine_id` of the washing machine resource, and the occupancy window `scheduled_start` and `scheduled_end`. The category must be one actually present with disposition `ACCEPTED` in the linked batch; staging a load for a category the batch never accepted fails with `ERR_CATEGORY_NOT_IN_BATCH`. The window must be strictly increasing, with violations rejected as `ERR_INVALID_TIME_RANGE`. Staging also enforces the machine's half-open overlap guard of §2.8 against the proposed window, rejecting conflicts with `ERR_MACHINE_TIME_OVERLAP`. A new load starts `STAGED`: its `formula_code` is resolved from the category's `wash_formula_code`, its `rewash_count` starts at zero, and its `hygienic_test_result` starts `PENDING`. Nothing prevents staging several loads for the same batch and category; each such load independently computes its `clean_weight_lb` from the batch's accepted pieces at unload.

Starting a load moves it from `STAGED` to `RUNNING`. Two guards apply: the source batch must be `LOCKED` or `POSTED` — starting against an unresolved batch fails with `ERR_BATCH_NOT_LOCKED` — and the machine's half-open overlap guard of §2.8 must pass, with conflicts rejected as `ERR_MACHINE_TIME_OVERLAP`. When a load containing a chip-tracked garment's category for that garment's customer starts running — whether from `STAGED` or, later, from `REWASH_PENDING` — the customer's garments in `SOILED_RECEIVED` cascade into `WASHING`.

Finishing the mechanical cycle moves the load from `RUNNING` to `AWAITING_TEST`, where the hygienic-testing discipline takes over. Categories divide on `hygienic_test_required`. When the category requires testing, the operator records the outcome: submitting an `outcome` of `PASS` moves the load from `AWAITING_TEST` to `TESTED_PASS`, and an `outcome` of `FAIL` moves it from `AWAITING_TEST` to `TESTED_FAIL`; attempting to record a test for a category that does not require one fails with `ERR_TEST_NOT_REQUIRED`. When the category does not require testing, the operator instead bypasses testing, moving the load directly from `AWAITING_TEST` to `TESTED_PASS`; attempting the bypass on a category that does require testing fails with `ERR_TEST_REQUIRED`. A failed load sets no alert flag, whatever the originating customer's kind: the plant itself keeps operating, and the obligation to rewash is carried solely by the load's progression into `REWASH_PENDING`.

Rewash is a bounded escalation. Requesting a rewash moves a `TESTED_FAIL` load to `REWASH_PENDING`, but only while `rewash_count` remains below the plant-wide ceiling of 2; a load that has already been rewashed twice is rejected with `ERR_REWASH_LIMIT_REACHED`. Each granted rewash increments `rewash_count` by one and escalates the `formula_code` one step up the ladder: `WF_STANDARD` climbs to `WF_HEAVY_SOIL`, `WF_CHEM_DISINFECT` climbs to `WF_THERMAL_DISINFECT`, and `WF_THERMAL_DISINFECT` and `WF_HEAVY_SOIL` are already at the top and remain unchanged. A `REWASH_PENDING` load starts again into `RUNNING` under the same machine-overlap guard as a fresh start, conflicts again drawing `ERR_MACHINE_TIME_OVERLAP`.

Unloading is the exit for a passing load, moving it from `TESTED_PASS` to `FINISHED`. At unload the load's `clean_weight_lb` is computed: the accepted pieces for the load's category within the load's batch, multiplied by the category's `piece_weight_lb`, rounded half-up to 2 decimal places. For chip-tracking customers, the same unload cascades the customer's garments of this load's category from `WASHING` to `CLEAN_STOCK`. A load may also be cancelled outright: from `STAGED` or from `REWASH_PENDING`, cancellation moves it to the terminal `CANCELLED` state with no further effect.

### 3.5. Finishing Lines, Throughput, and Linen Loss

Clean linen leaving the washer feeds the ironer and folder lines. Queuing a finish run references the `wash_load_id` being finished, the `line_id` of the line resource, and a strictly increasing occupancy window `scheduled_start` to `scheduled_end`. Queuing also enforces the line's buffered closed-interval guard of §2.8 against other `QUEUED` or `TALLIED` runs on the same line, rejecting conflicts with `ERR_LINE_TIME_OVERLAP`. Queuing does not gate on the wash load's state — the referenced load may be in any state. The new run starts `QUEUED`, and its `pieces_in` is captured once at creation as the wash load's accepted piece count at that moment.

Tallying is where the line tells the truth about its output. The operator submits `pieces_out`, the pieces successfully finished. Tallying moves the run from `QUEUED` to `TALLIED` under two guards: `pieces_out` may not exceed `pieces_in` — an over-tally fails with `ERR_TALLY_EXCEEDS_INPUT` — and the line's buffered closed-interval guard of §2.8 must pass against other `QUEUED` or `TALLIED` runs on the same line, with conflicts rejected as `ERR_LINE_TIME_OVERLAP`. The tally computes two derived figures. The run's `linen_loss_pieces` is `pieces_in` minus `pieces_out`, and is never negative by construction of the guard. The run's `throughput_pieces_per_hour` is `pieces_out` divided by the occupancy duration in hours — the difference between `scheduled_end` and `scheduled_start` measured in seconds and divided by 3600 — rounded half-up to 2 decimal places, and zero when the duration is not positive.

Posting a tallied run moves it from `TALLIED` to `POSTED` and credits its `pieces_out` to the clean stock of the originating stop's customer and category. Posting deliberately does not modify `CustomerParLevel.current_on_site_pieces` — the on-site counter moves only when a delivery is marked delivered at the customer site. The run's `linen_loss_pieces` lives only on the run itself; the API maintains and exposes no plant-level loss aggregate. A queued run that should never run can be abandoned, moving from `QUEUED` to `VOIDED`.

### 3.6. Garment Chip Tracking and Lost-Item Charges

For customers with `chip_tracking_enabled`, individual garments carry RFID identities. A `PlantAdmin` registers a garment by naming its `customer_id`, `category_id`, and `chip_code`; the chip code is globally unique across the system, and a colliding registration is rejected with `ERR_DUPLICATE`. Registration itself does not require the customer's `chip_tracking_enabled` flag — the flag gates the automatic cascades and mark-lost, not registration. A freshly registered garment starts `AT_CUSTOMER` with `lost_at` empty.

From there the garment rides the physical flows described in earlier sections through automatic cascades: pickup of the customer's stop moves `AT_CUSTOMER` garments to `IN_TRANSIT_SOILED`; cart receiving moves `IN_TRANSIT_SOILED` to `SOILED_RECEIVED`; a wash load of the garment's category and customer starting its run moves `SOILED_RECEIVED` to `WASHING`; unloading moves `WASHING` to `CLEAN_STOCK`. A `PlantOperator` then loads clean garments onto the outgoing truck, moving each from `CLEAN_STOCK` to `LOADED_OUT`. Finally, when a delivery of the garment's category and customer is marked delivered, `LOADED_OUT` garments return to `AT_CUSTOMER` — up to the delivered piece count, chosen by earliest garment `created_at` first, with ties broken by `chip_code` in ascending order; the chip code serves as a deterministic business key for this selection rather than any random identifier.

Garments die by declaration. A `CustomerServiceRep` may mark a garment lost from `AT_CUSTOMER`, from `IN_TRANSIT_SOILED`, or from `LOADED_OUT` — the three states in which custody is ambiguous between site and truck. Marking lost requires the owning customer to have `chip_tracking_enabled`; without it the act fails with `ERR_CHIP_TRACKING_DISABLED`. The transition stamps `lost_at` with the current logical time, moves the garment to the terminal `LOST` state, and queues a lost-item charge equal to the garment category's `replacement_cost_cents`. The charge does not bill immediately: it waits in an unbilled queue and is summed into the `lost_item_charges_cents` of the customer's next invoice when one is generated, draining the queue in the process.

### 3.7. Deliveries, Shortages, and Discrepancy Settlement

Deliveries close the loop back to the customer. Once a stop is `PICKED_UP` and every cart of the stop has been resolved into `RECEIVED`, `SORTED`, or `VOIDED` — unresolved carts block the delivery phase with `ERR_CARTS_PENDING` — the `RouteDriver` manifests one delivery row per category at the stop, supplying the `category_id` and the `pieces_promised` the plant committed to return. Each manifest starts `MANIFESTED`. The server enforces no uniqueness of category within a stop — manifesting the same category twice creates two delivery rows.

Recording the physical drop is the pivotal act. Marking a delivery delivered requires the parent stop to be in `PICKED_UP` — a stop not yet there fails with `ERR_STOP_NOT_PICKED_UP` — and requires the customer's `account_balance_cents` to be no greater than their `credit_limit_cents`, since a customer already past their ceiling may not receive new goods; a breached ceiling fails with `ERR_CREDIT_LIMIT_EXCEEDED`. The request also carries the OCC field `expected_customer_version` per §2.7, rejected with `ERR_STALE_VERSION` when the customer's `version` has moved on. On success the submitted `pieces_delivered` is recorded, and the system derives `shortfall_pieces` as the promised minus delivered count floored at zero, and `overage_pieces` as the delivered minus promised count floored at zero. The par row's `current_on_site_pieces` for this customer and category is incremented by the delivered count when a par row exists for the pair; no par-shortage alert is computed or recorded — the plant's `par_shortage_alert_pieces` is inert configuration. For chip-tracking customers the loaded-out garments of this customer and category come home, cascading `LOADED_OUT` to `AT_CUSTOMER` up to the delivered count by the selection order of §3.6. The customer's `version` increments by one with the balance-relevant mutation. And when the delivery that just left `MANIFESTED` was the stop's last remaining manifested row, the stop itself advances from `PICKED_UP` to `DELIVERED`.

Once a stop is delivering, its remaining lifecycle is customer-driven and automatic. The `CustomerContact` owning the customer on the stop — ownership is checked against `X-User-ID`, and a contact acting on another customer's delivery is rejected with `ERR_FORBIDDEN` — may confirm a delivery, moving it from `DELIVERED` to `CONFIRMED`. When every delivery of the stop has reached `CONFIRMED` or `SETTLED`, the stop closes automatically from `DELIVERED` to `CLOSED`.

Alternatively, when the delivered count fell short — `shortfall_pieces` at least 1, otherwise the filing fails with `ERR_NO_SHORTAGE` — the contact files a shortage dispute with a `claimed_shortfall_pieces` of at least 1. Filing creates a `Discrepancy` in `FILED` status under the delivery, moves the delivery from `DELIVERED` to `DISPUTED`, and moves the parent stop from `DELIVERED` to `DISPUTED` if it was not there already.

A `CustomerServiceRep` then works the discrepancy queue. Starting review moves `FILED` to `UNDER_REVIEW`. Approval moves `UNDER_REVIEW` to `APPROVED` and requires the submitted `approved_shortfall_pieces` to be at least 1, no more than `claimed_shortfall_pieces`, and no more than the parent delivery's `shortfall_pieces`; a quantity outside that band fails with `ERR_INVALID_APPROVED_QUANTITY`. On approval the `credit_cents` is computed: the approved shortfall pieces multiplied by the category's `replacement_cost_cents`, multiplied by 60 percent, and rounded half-up to whole cents — the plant credits shortage at sixty percent of replacement cost, never one hundred. Rejection moves `UNDER_REVIEW` to the terminal `REJECTED`.

Credit application is the billing hand-off, performed by a `BillingClerk` who names the target `invoice_id`. The target invoice must belong to the same customer as the disputed delivery's stop — a cross-customer credit fails with `ERR_INVOICE_CUSTOMER_MISMATCH` — and must be in `DRAFT` status, failing otherwise with `ERR_INVOICE_NOT_DRAFT`. Applying the credit moves the discrepancy from `APPROVED` to the terminal `CREDITED`, adds `credit_cents` into the invoice's `credits_cents`, recomputes the invoice's `total_due_cents`, subtracts `credit_cents` from the customer's `account_balance_cents`, and bumps the customer's `version` by one. Whenever all discrepancies of a delivery have reached their terminal states — `CREDITED` or `REJECTED` — the delivery settles automatically from `DISPUTED` to `SETTLED`; this happens both on rejection and on credit application. And when every delivery of a disputed stop has reached `CONFIRMED` or `SETTLED` with at least one delivery having settled, the stop closes automatically from `DISPUTED` to `CLOSED`.

### 3.8. Billing, Utility Surcharge, and Customer Credit

Invoicing assembles everything the period produced. A `BillingClerk` generates an invoice for a customer by supplying `billing_period_start` (inclusive) and `billing_period_end` (exclusive, and strictly after the start; a non-increasing range fails schema validation with `ERR_INVALID_REQUEST`). Generation computes the four money components and lands the invoice in `DRAFT`. Both period bounds are ISO calendar dates in `YYYY-MM-DD` form, and the invoice month — the month whose utility reading and clean pounds drive the surcharge — is the `YYYY-MM` of `billing_period_start`.

The linen component `linen_charges_cents` depends on the customer's `billing_mode`. For a `COG` customer, each linen category contributes the pounds actually washed: the sum of `clean_weight_lb` over the customer's `FINISHED` wash loads of that category whose unload calendar date falls within the billing period, start-date inclusive and end-date exclusive, multiplied by the category's `cog_wash_rate_cents_per_lb` and rounded half-up to whole cents as the category gross. The customer's total washed volume across all categories then sets a volume discount: at least 20000 pounds earns 7 percent; failing that, at least 5000 pounds earns 3 percent; below that the discount is zero. The rounding order is pinned and not negotiable: the discount is applied per category on the already-rounded category gross — the gross multiplied by one hundred minus the discount percent, divided by one hundred, and rounded half-up to whole cents — and the per-category nets are then summed into `linen_charges_cents`. Summing first and discounting once is forbidden.

For a `RENTAL` customer, the charge is forward-looking against the par snapshot at generation time. The period length is the whole number of days from `billing_period_start` to `billing_period_end`. Each par row of the customer contributes its `par_pieces` multiplied by a daily rate and by the day count: the daily rate per piece is the category's `replacement_cost_cents` multiplied by 2 percent — two percent of replacement cost per piece-day — and each category line is rounded half-up to whole cents before the lines are summed into `linen_charges_cents`.

The surcharge component `utility_surcharge_cents` passes through excess utility consumption. When a `UtilityReading` exists for the invoice's month, the actual variant computes the month's true utility cost as `kwh_used` times `kwh_rate_cents` plus `gallons_used` times `gallon_rate_cents`; computes the baseline cost as the month's `clean_lbs_processed` multiplied by the plant's `utility_baseline_kwh_per_lb` times `kwh_rate_cents`, plus `clean_lbs_processed` multiplied by `utility_baseline_gal_per_lb` times `gallon_rate_cents`, the sum rounded half-up to whole cents; and takes the excess as the actual minus the baseline, floored at zero. The excess passes through on a tiered schedule: the first 100000 cents of excess pass at 50 percent, the portion of the excess above 100000 and up to 500000 cents passes at 75 percent, and any portion above 500000 cents passes at 100 percent. The customer's share of that tiered excess is the customer's clean pounds for the month — the sum of `clean_weight_lb` over the customer's `FINISHED` loads unloaded within the invoice month — divided by the reading's `clean_lbs_processed`, multiplied by 100, and rounded half-up to 4 decimal places (the share is zero when that divisor is zero); the surcharge is the tiered excess multiplied by that share percentage, divided by 100, and rounded half-up to whole cents.

When no reading has been posted yet for the invoice month, the estimated variant looks backward. The trailing window is the up-to-three most recent utility readings of the plant whose `period_month` is strictly earlier than the invoice month, ordered newest first; the average of those readings' tiered excess values, rounded half-up to whole cents, stands in for the current month's excess. The share percentage uses the same customer clean pounds for the invoice month, but divides by the `clean_lbs_processed` of the most recent reading in the trailing window (the share is again zero when that divisor is zero). With fewer than three trailing readings the average runs over what is available; with no readings at all the estimated surcharge is zero. Posting the month's reading later — an immutable `UtilityReading` naming its `period_month` in YYYY-MM form (unique per plant, collisions rejected as `ERR_DUPLICATE`) together with `kwh_used`, `gallons_used`, `clean_lbs_processed`, `kwh_rate_cents`, and `gallon_rate_cents` — triggers a true-up: any invoice of that month generated with the estimated variant has the delta between actual and estimated surcharge applied to the customer's earliest-created `DRAFT` invoice, and if none exists, a new `DRAFT` invoice is created holding only the delta, its billing period set to the reading's month (the first day of that month through the first day of the following month).

Generation also drains the unbilled lost-item queue into `lost_item_charges_cents` and leaves `credits_cents` at its initial zero until credits are applied later. The invoice's `total_due_cents` is the linen charges plus the lost-item charges plus the utility surcharge minus the credits, floored at zero; the same formula recomputes on every credit application and every lost-item queue drain.

A billing preview capability lets a `PlantAdmin`, `CustomerServiceRep`, or `BillingClerk` read what an invoice for a period would contain — the same five money fields `linen_charges_cents`, `lost_item_charges_cents`, `utility_surcharge_cents`, `credits_cents`, and `total_due_cents` — without persisting anything. The period bounds arrive as the query parameters `billing_period_start` and `billing_period_end`. For a `COG` customer the preview runs the estimated variant: in addition to `FINISHED` loads it counts loads still in `STAGED`, `RUNNING`, `AWAITING_TEST`, `TESTED_PASS`, or `REWASH_PENDING`, using a projected clean weight of accepted pieces times `piece_weight_lb`, so the preview total is always at least the actual total; these in-flight loads are counted without any period filter, whatever their scheduled dates, and the estimated projection applies only to the linen component — the surcharge component is computed exactly as at generation, actual variant included. For a `RENTAL` customer the preview accepts an optional `override_par_pieces` query parameter, a non-negative integer, and projects with the overridden par count substituted on every par row of the customer, without persisting it.

Issuing an invoice moves it from `DRAFT` to `ISSUED` under three guards. The customer must be `ACTIVE` — issuing against a suspended customer fails with `ERR_CUSTOMER_SUSPENDED`. The customer's `account_balance_cents` plus the invoice's `total_due_cents` must not exceed `credit_limit_cents`, unless the total is zero, in which case issue proceeds; a breach fails with `ERR_CREDIT_LIMIT_EXCEEDED`. And the request must carry `expected_customer_version` matching the customer's current `version`, with mismatches rejected as `ERR_STALE_VERSION`. On success the invoice total is added to `account_balance_cents` and the customer's `version` increments by one. Marking an issued invoice paid moves it from `ISSUED` to the terminal `PAID` and subtracts the total from `account_balance_cents`, again bumping the customer's `version`. Voiding abandons a `DRAFT` invoice, moving it to the terminal `VOID`; voiding is blocked while any discrepancy in `CREDITED` references the invoice, failing with `ERR_INVOICE_HAS_CREDITS`, and on success any pending lost-item charge queue entries targeted at this invoice are released back to the unbilled queue.

## 4. Endpoint Definitions

All endpoints live under the API root. Creating a new resource returns HTTP 201; operations that modify an existing resource, and all reads, return HTTP 200. Request and response bodies follow the envelope of §2.2; the narratives of §3 define each operation's payload fields, preconditions, and side effects.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical server clock (initial reading 2026-05-01T00:00:00Z; never falls back to wall-clock) | PlantAdmin |
| POST | /plants | Create a plant | PlantAdmin |
| GET | /plants/{id} | Get a plant | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| POST | /plants/{id}/linen-categories | Create a linen category under a plant | PlantAdmin |
| GET | /plants/{id}/linen-categories | List categories of a plant | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| GET | /linen-categories/{id} | Get one category | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| GET | /linen-categories/{id}/par-levels | List par levels referencing this category | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /linen-categories/{id}/sort-items | List sort items of this category | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /linen-categories/{id}/wash-loads | List wash loads of this category | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /linen-categories/{id}/garments | List garments of this category | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /linen-categories/{id}/deliveries | List deliveries of this category | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| POST | /plants/{id}/customers | Create a customer under a plant | PlantAdmin |
| GET | /plants/{id}/customers | List customers of a plant | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| GET | /customers/{id} | Get a customer | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| POST | /customers/{id}/suspend | Suspend a customer (blocks invoice issue) | PlantAdmin |
| POST | /customers/{id}/resume | Resume a suspended customer | PlantAdmin |
| GET | /customers/{id}/stops | List route stops of this customer | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| GET | /customers/{id}/garments | List garments of this customer | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| PUT | /customers/{id}/par-levels/{categoryId} | Upsert the par level for (customer, category) | PlantAdmin |
| GET | /customers/{id}/par-levels | List par levels of a customer | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| POST | /plants/{id}/routes | Create a route under a plant | RouteDriver |
| GET | /plants/{id}/routes | List routes of a plant | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| GET | /routes/{id} | Get a route | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| POST | /routes/{id}/dispatch | Dispatch a route | RouteDriver |
| POST | /routes/{id}/complete | Complete a route | RouteDriver |
| POST | /routes/{id}/reconcile | Reconcile a route | RouteDriver |
| POST | /routes/{id}/stops | Add a stop to a route | RouteDriver |
| GET | /routes/{id}/stops | List stops of a route | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| GET | /stops/{id} | Get a stop | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| POST | /stops/{id}/arrive | Mark stop arrived | RouteDriver |
| POST | /stops/{id}/pickup | Record soiled pickup at a stop; creates SoiledCarts | RouteDriver |
| GET | /stops/{id}/carts | List carts of a stop | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| GET | /carts/{id} | Get a cart | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| POST | /carts/{id}/receive | Receive a cart at the plant gate | PlantOperator |
| POST | /carts/{id}/void | Void a DECLARED cart | PlantOperator |
| POST | /sort-batches | Open a sort batch for a stop | PlantOperator |
| GET | /sort-batches/{id} | Get a sort batch | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /plants/{id}/sort-batches | List sort batches of a plant | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /stops/{id}/sort-batches | List sort batches of a stop | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /sort-batches/{id}/items | List sort items of a batch | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| POST | /sort-batches/{id}/items | Add a classification row to a sort batch | PlantOperator |
| POST | /sort-batches/{id}/lock | Lock a batch; computes reject rate and alert | PlantOperator |
| POST | /sort-batches/{id}/unlock | Unlock a batch (revert LOCKED to OPEN) | PlantOperator |
| POST | /sort-batches/{id}/post | Post a locked batch | PlantOperator |
| POST | /sort-batches/{id}/void | Void an open batch | PlantOperator |
| POST | /wash-loads | Stage a wash load from a sort batch | PlantOperator |
| GET | /wash-loads/{id} | Get a wash load | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /plants/{id}/wash-loads | List wash loads of a plant | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /sort-batches/{id}/wash-loads | List wash loads of a sort batch | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| POST | /wash-loads/{id}/start | Start a load (from STAGED or REWASH_PENDING) | PlantOperator |
| POST | /wash-loads/{id}/finish-cycle | Finish the mechanical wash cycle | PlantOperator |
| POST | /wash-loads/{id}/record-test | Record hygienic test outcome | PlantOperator |
| POST | /wash-loads/{id}/bypass-test | Bypass hygienic test (only when category does not require it) | PlantOperator |
| POST | /wash-loads/{id}/request-rewash | Escalate a failed load into rewash | PlantOperator |
| POST | /wash-loads/{id}/unload | Unload a passed load | PlantOperator |
| POST | /wash-loads/{id}/cancel | Cancel a STAGED or REWASH_PENDING load | PlantOperator |
| POST | /finish-runs | Queue a finish run for a wash load | PlantOperator |
| GET | /finish-runs/{id} | Get a finish run | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /plants/{id}/finish-runs | List finish runs of a plant | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| GET | /wash-loads/{id}/finish-runs | List finish runs of a wash load | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |
| POST | /finish-runs/{id}/tally | Tally a finish run with pieces_out | PlantOperator |
| POST | /finish-runs/{id}/post | Post a tallied finish run to clean stock | PlantOperator |
| POST | /finish-runs/{id}/void | Void a queued finish run | PlantOperator |
| POST | /garments/register | Register a chip-tracked garment | PlantAdmin |
| GET | /garments/{id} | Get a garment | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| POST | /garments/{id}/load-out | Load a clean garment onto an outgoing truck | PlantOperator |
| POST | /garments/{id}/mark-lost | Mark a garment lost; queues a lost-item charge | CustomerServiceRep |
| POST | /stops/{id}/deliveries | Manifest a delivery (one row per category) at a stop | RouteDriver |
| GET | /stops/{id}/deliveries | List deliveries of a stop | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| GET | /deliveries/{id} | Get a delivery | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| POST | /deliveries/{id}/mark-delivered | Record physical delivery with pieces_delivered; OCC on Customer version | RouteDriver |
| POST | /deliveries/{id}/confirm | Customer confirms receipt | CustomerContact |
| POST | /deliveries/{id}/disputes | Customer files a shortage dispute; creates a Discrepancy | CustomerContact |
| GET | /deliveries/{id}/disputes | List discrepancies of a delivery | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| GET | /discrepancies/{id} | Get a discrepancy | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk, CustomerContact |
| POST | /discrepancies/{id}/start-review | Move a filed discrepancy into review | CustomerServiceRep |
| POST | /discrepancies/{id}/approve | Approve a discrepancy with an approved shortfall | CustomerServiceRep |
| POST | /discrepancies/{id}/reject | Reject a discrepancy | CustomerServiceRep |
| POST | /discrepancies/{id}/apply-credit | Apply an approved credit to a DRAFT invoice | BillingClerk |
| POST | /customers/{id}/invoices/generate | Generate a DRAFT invoice for a billing period | BillingClerk |
| GET | /customers/{id}/invoices | List invoices of a customer | PlantAdmin, CustomerServiceRep, BillingClerk, CustomerContact |
| GET | /invoices/{id} | Get an invoice | PlantAdmin, CustomerServiceRep, BillingClerk, CustomerContact |
| POST | /invoices/{id}/issue | Issue a DRAFT invoice; OCC on Customer version | BillingClerk |
| POST | /invoices/{id}/mark-paid | Mark an issued invoice paid | BillingClerk |
| POST | /invoices/{id}/void | Void a DRAFT invoice | BillingClerk |
| GET | /customers/{id}/billing-preview | Computed, non-persisting preview of an invoice for the period | PlantAdmin, CustomerServiceRep, BillingClerk |
| POST | /plants/{id}/utility-readings | Post a monthly utility reading (immutable) | BillingClerk |
| GET | /plants/{id}/utility-readings | List utility readings of a plant | PlantAdmin, BillingClerk |
| GET | /utility-readings/{id} | Get a utility reading | PlantAdmin, BillingClerk |
| GET | /garments | List garments (filterable) | PlantAdmin, PlantOperator, RouteDriver, CustomerServiceRep, BillingClerk |
| GET | /sort-items | List sort items (filterable) | PlantAdmin, PlantOperator, CustomerServiceRep, BillingClerk |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCED_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_ROUTE_HAS_NO_STOPS | 409 |
| ERR_ROUTE_STOPS_OPEN | 409 |
| ERR_ROUTE_STOPS_UNRESOLVED | 409 |
| ERR_ROUTE_DISCREPANCIES_OPEN | 409 |
| ERR_ROUTE_NOT_DISPATCHED | 409 |
| ERR_EMPTY_PICKUP | 422 |
| ERR_DUPLICATE_CART_TAG | 409 |
| ERR_CARTS_PENDING | 409 |
| ERR_STOP_NOT_PICKED_UP | 409 |
| ERR_CART_NOT_VOIDABLE | 409 |
| ERR_EMPTY_SORT_BATCH | 422 |
| ERR_BATCH_HAS_WASH_LOADS | 409 |
| ERR_BATCH_NOT_LOCKED | 409 |
| ERR_CATEGORY_NOT_IN_BATCH | 422 |
| ERR_MACHINE_TIME_OVERLAP | 409 |
| ERR_LINE_TIME_OVERLAP | 409 |
| ERR_INVALID_TIME_RANGE | 422 |
| ERR_TEST_REQUIRED | 422 |
| ERR_TEST_NOT_REQUIRED | 422 |
| ERR_REWASH_LIMIT_REACHED | 409 |
| ERR_TALLY_EXCEEDS_INPUT | 422 |
| ERR_CHIP_TRACKING_DISABLED | 422 |
| ERR_DUPLICATE | 409 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_CUSTOMER_SUSPENDED | 409 |
| ERR_NO_SHORTAGE | 422 |
| ERR_INVALID_APPROVED_QUANTITY | 422 |
| ERR_INVOICE_NOT_DRAFT | 409 |
| ERR_INVOICE_CUSTOMER_MISMATCH | 409 |
| ERR_INVOICE_HAS_CREDITS | 409 |
| ERR_INTERNAL | 500 |
