# Janitorial & Sanitation Supply Distribution API — Product Requirements Document

## 1. Introduction

A janitorial and sanitation (Jan/San) distributor lives in the gap between a warehouse full of consumables and a portfolio of customer facilities — kitchens, laundries, plants, and campuses — whose consumption is steady enough to forecast but erratic enough to matter. Chemical products introduce dilution-safety obligations: a facility employee must be trained and certified before concentrated chemicals may be ordered or a closed-loop dispenser may be commissioned on site. Purchasing departments buy through GPO and co-op contract bids that lock pricing for fixed protection windows, while sales teams seed new accounts with free product through sample and trial programs that convert into paid orders. Freight economics add a delivery minimum and a diesel-indexed fuel surcharge, and supply disruptions force a disciplined substitution workflow when a stocked product suddenly goes into shortage.

This document specifies the API that operates that distribution business end to end. It covers facility onboarding with a credit-exposure ledger, the product catalog and warehouse stock position, usage capture and consumption forecasting with a dual-variant forecast model, dispenser placement under chemical-compatibility and technician-scheduling safety rules, dilution training certification, standing orders with auto-replenishment, the manual order pipeline from draft through placement, delivery repricing, and invoicing, the shortage-driven substitution cascade, contract bid adjudication with price protection, sample trials with conversion credits, and a pinned daily operations sweep. All resources are mounted under the `/jansan` URL prefix. The intended audience is the engineering team building the service; every behavioral rule stated here is normative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` specifies their operational capacity. The system recognizes exactly four roles: `DistributorAdmin`, `FacilityManager`, `SalesRep`, and `FieldTechnician`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is valid but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `FacilityManager`, `X-User-ID` is the `id` of the acting Facility; ownership checks on any resource that references a facility compare the resource's `facility_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `FieldTechnician`, `X-User-ID` is the `id` of the acting Technician; dispenser-install completion compares the dispenser's `technician_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `DistributorAdmin` or `SalesRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Common Fields

Every resource in this system — facilities, products, usage records, forecast profiles, technicians, dispensers, training records, standing orders, orders, order lines, contract bids, substitution proposals, and trial programs — carries the same set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on every mutation.
- `version` (integer): a system-managed integer that increments by one on every modification to the resource, whether the modification comes from a client request, an automatic state transition, or a cascade side effect originating on another entity.

Because cascades in this domain routinely mutate several entities in one operation (a product shortage touches order lines, orders, and the facility ledger at once), each affected entity independently refreshes its `updated_at` and increments its `version`.

### 2.5. Referenced Resources and Existence Validation

Identifiers appearing in the request path are validated for existence in a strict left-to-right order, and identifiers referenced in the request body (for example, a payload carrying a `facility_id` and a `product_id`) must likewise refer to existing resources. The first identifier that does not correspond to an existing resource produces an `ERR_NOT_FOUND` rejection, and no further validation or business logic runs after that point.

### 2.6. Money, Precision, and Rounding

All monetary amounts are represented as integer cents — prices, fees, surcharges, credits, subtotals, totals, and the facility ledger balances alike. Two rounding rules govern every computation in the system. First, final monetary values are produced by the "round half up" method. Second, order line totals are rounded to integer cents per line first, and only then summed into the merchandise subtotal; summing unrounded raw values and rounding once at the end is a different, non-conformant result. The one non-integer quantity in the pricing and forecasting layer is the forecast's average daily usage, which is carried at four decimal places, also rounded half up. No monetary figure is ever approximate: thresholds and tier boundaries are evaluated exactly as stated.

### 2.7. The Logical Clock

A logical clock governs every time-dependent behavior in the system: protection windows, training validity, proposal and trial expiry, forecast windows, standing-order due dates, and the daily sweep. Before any clock-setting call has been made, the clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own. The clock is monotonic: an administrator advances it by supplying a `to_iso8601` timestamp, and the capability returns the new `current_utc`. Setting the clock to a timestamp earlier than the current logical time is rejected with `ERR_CLOCK_REGRESSION`; setting it to the current time or any later time is accepted.

### 2.8. Optimistic Concurrency Control

Exactly one endpoint in the API participates in optimistic concurrency control: the forecast-profile planner update, `PATCH /jansan/forecast-profiles/{forecast_profile_id}`. A request to that endpoint must carry `expected_forecast_profile_version`, a non-optional input field holding the `version` of the ForecastProfile the client last observed. If another writer has advanced the profile's `version` since that observation, the update is rejected with `ERR_STALE_VERSION` (HTTP 412). Two planners may legitimately update `safety_stock` or `current_on_hand` on the same profile, and neither update changes any state field that would reject the other, so the conflict is resolved purely by this version check. Endpoints not named here do not accept a version field at all.

### 2.9. The Facility Exposure Ledger

Each facility carries two ledger counters that summarize its fiscal exposure to the distributor. The `committed_cents` counter is the sum of `total_cents` over all of the facility's orders whose status is `PLACED`, `PARTIALLY_BLOCKED`, or `DELIVERED`, computed over all time with no window. The `outstanding_cents` counter is the sum of `total_cents` over all of the facility's orders in `INVOICED` status, again over all time. Both counters start at zero and are recomputed — or adjusted by the exact delta — on every order event that moves money: placement adds the new order's total to `committed_cents`, delivery repricing adjusts `committed_cents` to the recomputed total, invoicing moves the total out of `committed_cents` and into `outstanding_cents`, and cancellation or a shortage-cascade recompute removes the affected total from `committed_cents`.

A facility's `credit_limit_cents` caps the exposure it may carry. At order placement the system requires that the facility's current `committed_cents` plus the new order's `total_cents` not exceed `credit_limit_cents`; a sum exactly equal to the limit passes, and anything above it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`.

### 2.10. Stock Reservation Semantics

Warehouse stock for each product is tracked through two counters. `qty_on_hand` is the unallocated stock, set at product creation and never negative, and `qty_allocated` is the stock reserved by order lines in `ALLOCATED` status. Allocation is all-or-nothing at placement: every line must be satisfiable from `qty_on_hand` before any line allocates, and a line whose requested quantity exactly equals the available `qty_on_hand` does allocate. Allocation moves units from `qty_on_hand` into `qty_allocated`; cancellation releases the reservation by returning units to `qty_on_hand`; fulfillment at delivery decrements `qty_allocated` while `qty_on_hand` stays reduced, reflecting that the goods have physically left the warehouse.

### 2.11. The Validation Priority Stack

When several checks could reject the same request, the system evaluates them in the following fixed order, and the first failing check determines the response:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is one of the declared roles; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Endpoint authorization.** The role is listed among the endpoint's authorized roles; otherwise `ERR_FORBIDDEN` (403).
3. **Entity-backed ownership.** A `FacilityManager` may act only on resources whose `facility_id` equals `X-User-ID`, and a `FieldTechnician` may complete only dispensers whose `technician_id` equals `X-User-ID`; otherwise `ERR_FORBIDDEN` (403).
4. **Existence.** Path identifiers, validated left to right, and body-referenced identifiers must all exist; otherwise `ERR_NOT_FOUND` (404).
5. **Request shape.** Required fields are present, types are valid, enum members are valid, quantities are at least 1, `period_end` is on or after `period_start`, `install_end` is strictly after `install_start`, `protection_end` is strictly after `protection_start`, and `score_pct` lies within 0 to 100 inclusive; otherwise `ERR_VALIDATION` (400).
6. **Stale version.** On the forecast-profile planner update, `expected_forecast_profile_version` must equal the profile's current `version`; otherwise `ERR_STALE_VERSION` (412).
7. **State-machine legality.** The resource's current state must allow the attempted transition, and terminal states accept no further transitions; otherwise `ERR_INVALID_STATE` (409).
8. **Facility gate.** The facility must be `ACTIVE` for order placement, order cancellation, standing-order activation, standing-order resumption, dispenser completion, trial conversion, and usage-record creation; otherwise `ERR_FACILITY_INACTIVE` (409).
9. **Product availability at placement.** Every line's product must be `ACTIVE`; otherwise `ERR_PRODUCT_UNAVAILABLE` (409).
10. **Stock sufficiency.** Allocation requires `qty_on_hand` of at least the requested quantity, with equality allocating; this check guards order placement and substitution-proposal acceptance; otherwise `ERR_INSUFFICIENT_STOCK` (409).
11. **Dilution compliance.** Order placement or dispenser completion involving a `dilution_required` chemical requires an existing `CERTIFIED` training record for that facility and product; otherwise `ERR_TRAINING_NOT_CERTIFIED` (409).
12. **Zone incompatibility.** No two dispensers in `SCHEDULED` or `INSTALLED` status in the same facility and zone may pair chemical family `ACID` with `OXIDIZER`; otherwise `ERR_INCOMPATIBLE_PLACEMENT` (409).
13. **Technician window conflict.** A new install window must not overlap another `SCHEDULED` or `INSTALLED` install of the same technician under half-open interval semantics, so one window ending exactly when another begins does not conflict; otherwise `ERR_TECHNICIAN_WINDOW_CONFLICT` (409).
14. **Protection window overlap at award.** No two `AWARDED` bids for the same group sharing a line product may have intersecting closed protection windows, and windows whose endpoints merely touch do intersect; otherwise `ERR_PROTECTION_WINDOW_OVERLAP` (409).
15. **Clock monotonicity.** The clock-setting capability rejects a timestamp earlier than the current logical time with `ERR_CLOCK_REGRESSION` (400).
16. **Standing-order item uniqueness.** No two standing orders of the same facility in `DRAFT`, `ACTIVE`, or `PAUSED` status may share any item product; otherwise `ERR_DUPLICATE_STANDING_ORDER` (409).
17. **Single active trial.** At most one trial program may be `ACTIVE` for a given facility and product; otherwise `ERR_TRIAL_ALREADY_ACTIVE` (409).
18. **Discontinue guard.** A product may not be discontinued while any of its order lines is `PENDING`, `ALLOCATED`, or `SUBSTITUTION_PENDING`; otherwise `ERR_DISCONTINUE_BLOCKED` (409).
19. **Archive guard.** A facility may not be archived while it has orders in `DRAFT`, `PLACED`, `PARTIALLY_BLOCKED`, or `DELIVERED`, or standing orders in `DRAFT`, `ACTIVE`, or `PAUSED`; otherwise `ERR_ARCHIVE_BLOCKED` (409).
20. **Credit limit.** The facility's `committed_cents` plus the order's `total_cents` must not exceed `credit_limit_cents`, with equality passing; this check guards order placement and trial conversion; otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (409).

## 3. Business Logic & Workflows

### 3.1. Facility Onboarding, Suspension, and Archival

A `DistributorAdmin` onboards a facility by providing its display `name`, the `facility_group_code` that ties it to a GPO or co-op purchasing group, a `credit_limit_cents` ceiling, the dispatcher's `service_zone` label, the one-way `delivery_distance_miles` from the warehouse (the value that later selects the fuel-surcharge distance band), and an informational `default_delivery_day`. New facilities are born `ACTIVE` with `committed_cents` and `outstanding_cents` at zero and `closed_loop_enrolled` false. A facility may also be read back by any of the four roles.

Suspending a facility — an `ACTIVE` → `SUSPENDED` transition available to a `DistributorAdmin` — ripples into its replenishment program: every standing order of the facility currently `ACTIVE` is moved to `PAUSED` with `pause_reason` set to `SUSPENSION`, while standing orders paused manually and those still in `DRAFT` are left untouched. Reinstatement performs the mirror-image conditional cascade: a `SUSPENDED` → `ACTIVE` transition flips only the suspension-paused standing orders back to `ACTIVE` and clears their `pause_reason` to `NONE`, while manually paused standing orders stay `PAUSED`. Both transitions increment the facility's `version`.

Archival is the facility's terminal act. An `ACTIVE` facility may move to `ARCHIVED` only when it carries no order in `DRAFT`, `PLACED`, `PARTIALLY_BLOCKED`, or `DELIVERED` and no standing order in `DRAFT`, `ACTIVE`, or `PAUSED`; otherwise the attempt is rejected with `ERR_ARCHIVE_BLOCKED`. Because `ARCHIVED` is terminal, no further transitions leave it, and any attempt to run a state-changing operation from the wrong source state — suspending an already suspended facility, for instance — is rejected with `ERR_INVALID_STATE`.

### 3.2. The Product Catalog and Warehouse Stock

Products are created by a `DistributorAdmin` with a `sku` that must be unique across the catalog, a display `name`, a `category` of `CHEMICAL`, `PAPER`, `EQUIPMENT`, `DISPENSER_SUPPLY`, or `OTHER`, a list `base_price_cents`, a free-form `unit_of_measure` such as CASE, GAL, or EACH, and the opening `qty_on_hand` stock position. Two optional attributes matter to safety workflows: `dilution_required` (default false) marks chemicals that demand documented dilution training before orders may be placed or dispenser installs completed, and `chemical_family` (default `NONE`) classifies the product as `ACID`, `ALKALINE`, `NEUTRAL`, `OXIDIZER`, or `NONE` — a classification that becomes load-bearing at dispenser placement time, because `ACID` and `OXIDIZER` products may never share a zone. A new product starts `ACTIVE` with `qty_allocated` at zero.

A product's commercial life has three states. `ACTIVE` is the normal selling state. Declaring a shortage moves it to `SHORTAGE` and triggers the substitution cascade described in §3.7; resolving the shortage returns it to `ACTIVE`, and notably does not resolve any still-pending substitution proposals, which live out their own lifecycle. Discontinuation is terminal: a product in `ACTIVE` or `SHORTAGE` may move to `DISCONTINUED` only when none of its order lines remains `PENDING`, `ALLOCATED`, or `SUBSTITUTION_PENDING`; if any such line exists the attempt is rejected with `ERR_DISCONTINUE_BLOCKED`. Products, like facilities, can be fetched by any role.

### 3.3. Usage Capture and Consumption Forecasting

Forecasting begins with raw usage. A `FacilityManager` (for their own facility) or a `DistributorAdmin` submits a usage record carrying the `facility_id`, the `product_id`, a `period_start` and `period_end` bounding the consumption window (the end must be on or after the start), the `quantity_used` (at least one unit), and a `source` of `MANUAL` or `AUTO_DISPENSER`. The facility must be `ACTIVE` or the submission is rejected with `ERR_FACILITY_INACTIVE`. Records are born `SUBMITTED`; a `DistributorAdmin` later posts them, moving `SUBMITTED → POSTED` and stamping `posted_at`, and `POSTED` is terminal. The usage-record list accepts optional `facility_id`, `product_id`, and `status` filters.

On top of that raw history sits the **ForecastProfile**, a planner-tuned projection for one facility and product pairing — at most one profile may exist per pairing. It is created with the `facility_id` and `product_id` plus three tunables: `horizon_days` (the coverage horizon, default 30, at least 1), `safety_stock` (extra units added to the reorder point, default 0, never negative), and `current_on_hand` (the facility-reported stock position, default 0, never negative). A `DistributorAdmin` may patch any of those three tunables, but only under the optimistic-concurrency rule of §2.8: the request must carry `expected_forecast_profile_version` matching the profile's current `version`, a stale value draws `ERR_STALE_VERSION`, and a successful patch increments the `version`. The profile list accepts `facility_id` and `product_id` filters.

Recomputation — invoked by a `DistributorAdmin` or the owning `FacilityManager` with a `variant` input of `PROVISIONAL` or `FINAL` — refreshes all of the profile's computed fields. The engine looks at the trailing 90-day window ending at the current clock time, both endpoints inclusive, matching usage records of the profile's facility and product by their `period_end`. Under the `FINAL` variant only `POSTED` records count, giving the audited view; under `PROVISIONAL` both `SUBMITTED` and `POSTED` records count, giving the operator's forward-looking view, so identical raw data yields a smaller `FINAL` average whenever unposted records exist. The `avg_daily_usage` is the sum of `quantity_used` across included records divided by 90 — the divisor is always 90 regardless of how much of the window the records actually cover — rounded half up to four decimal places. From that average the engine derives `reorder_point` as the average daily usage multiplied by the 7-day lead time, rounded up to the next whole unit, plus `safety_stock`; `recommended_qty` as the larger of zero and the horizon demand (the average daily usage multiplied by `horizon_days`, rounded up to whole units) minus `current_on_hand`; and `replenishment_recommended`, which is true whenever `current_on_hand` is less than or equal to `reorder_point` — equality triggers the recommendation. The recompute stamps `variant_used` with the variant just run, sets `last_computed_at` to the clock time, and increments the profile's `version`.

### 3.4. The Closed-Loop Chemical Program: Dispensers and Dilution Training

Field labor is represented by technicians, created by a `DistributorAdmin` with a `name` and born `ACTIVE` (a technician may later be `INACTIVE`).

A dispenser install is scheduled by a `DistributorAdmin` supplying the `facility_id`, the `product_id` (which must reference a product of category `CHEMICAL`), the placement `zone` within the facility, the `technician_id` of the installer who owns the appointment, and the install window from `install_start` to `install_end` (the end must be strictly after the start). Two safety checks run at scheduling time. Zone compatibility forbids two dispensers in `SCHEDULED` or `INSTALLED` status within the same facility and zone from pairing an `ACID` product with an `OXIDIZER` product — a violation draws `ERR_INCOMPATIBLE_PLACEMENT`. Technician load treats the window as a half-open interval that must not overlap any other `SCHEDULED` or `INSTALLED` dispenser owned by the same technician; under half-open semantics one install ending at exactly the moment another begins is not a conflict, but any true overlap is rejected with `ERR_TECHNICIAN_WINDOW_CONFLICT`. Dispensers are born `SCHEDULED`, and the dispenser list accepts `facility_id`, `product_id`, `technician_id`, and `status` filters.

Completion belongs to the field: only a `FieldTechnician` may complete an install, and only the one whose `technician_id` matches their `X-User-ID` — anyone else draws `ERR_FORBIDDEN`. The dispenser must be `SCHEDULED`, its facility must be `ACTIVE` (`ERR_FACILITY_INACTIVE` otherwise), and when the dispensed product has `dilution_required` set, there must already exist a `CERTIFIED` training record for that facility and product, or the completion is rejected with `ERR_TRAINING_NOT_CERTIFIED`. A successful completion moves `SCHEDULED → INSTALLED`, stamps `installed_at`, and bubbles upward: the facility's `closed_loop_enrolled` becomes true as soon as it has at least one `INSTALLED` dispenser. A `DistributorAdmin` may later decommission an `INSTALLED` dispenser, moving it to the terminal `DECOMMISSIONED` state and recomputing `closed_loop_enrolled` — which flips back to false when no `INSTALLED` dispenser remains at the facility.

Training is the compliance backbone of the program. A `DistributorAdmin` schedules a training record for a facility `employee_name` against a chemical product, and the record is born `SCHEDULED`. Certification, also by a `DistributorAdmin`, supplies a `score_pct` between 0 and 100: a score of at least 80 moves the record to `CERTIFIED`, stamping `certified_at` and setting `expires_at` exactly 365 days later, while a score below 80 moves it to `FAILED`, which is terminal. Certification does not last forever — when the daily sweep (§3.9) finds a `CERTIFIED` record whose `expires_at` is strictly in the past, the record moves to `EXPIRED`; at the exact `expires_at` instant it is still `CERTIFIED`. The training-record list accepts `facility_id`, `product_id`, and `status` filters.

### 3.5. Standing Orders and Auto-Replenishment

A standing order encodes a recurring replenishment commitment. A `FacilityManager` (for their facility) or a `DistributorAdmin` creates one with the `facility_id`, a non-empty `items` array whose entries each name a `product_id` and a `qty` of at least one, a `frequency` of `WEEKLY`, `BIWEEKLY`, or `MONTHLY`, the `next_run_date` on which generation is next due, and an optional `fuel_index` (default 3.00) that prices the orders this standing order generates. A facility may not hold two standing orders in `DRAFT`, `ACTIVE`, or `PAUSED` status that share any item product; such a create is rejected with `ERR_DUPLICATE_STANDING_ORDER`. New standing orders are born `DRAFT` with `pause_reason` `NONE`, `price_protected` false, and `next_delivery_total_cents` at zero. The standing-order list accepts `facility_id` and `status` filters.

Activation (`DRAFT → ACTIVE`, by a `FacilityManager` or `DistributorAdmin`) requires the facility to be `ACTIVE` — otherwise `ERR_FACILITY_INACTIVE` — and a non-empty item list, and it produces the first commercial preview: `next_delivery_total_cents` is recomputed as a merchandise-only preview, the sum over items of each quantity times the product's current effective unit price (contract pricing included, per §3.8), and `price_protected` is recomputed to true when at least one item product is covered by an `AWARDED` contract bid matching the facility's group. From `ACTIVE`, a pause moves the standing order to `PAUSED` with `pause_reason` `MANUAL`; a resume requires the facility to be `ACTIVE`, returns it to `ACTIVE` with `pause_reason` cleared to `NONE`, and refreshes the `next_delivery_total_cents` preview. Cancellation is available from `DRAFT`, `ACTIVE`, or `PAUSED` and lands in the terminal `CANCELLED` state.

The auto-replenishment engine runs inside the daily sweep (§3.9). Every `ACTIVE` standing order whose `next_run_date` is on or before the current clock time generates a real order — `source` `STANDING_ORDER`, its `standing_order_id` pointing back at the generator, priced with the standing order's `fuel_index` — and attempts to place it through the full placement pipeline of §3.6. When any placement validation fails, the generated order simply stays `DRAFT` for manual attention; the generation attempt is not retried. Either way, success or failure, the `next_run_date` advances by the frequency interval: 7 days for `WEEKLY`, 14 days for `BIWEEKLY`, 30 days for `MONTHLY`.

Facility suspension interacts with this lifecycle asymmetrically by design, as described in §3.1: suspension pauses only `ACTIVE` standing orders with `pause_reason` `SUSPENSION`, and reinstatement resumes only those suspension-paused ones — a manually paused standing order stays `PAUSED` across a suspend-and-reinstate round trip.

### 3.6. Order Placement, Pricing, and Settlement

A manual order is drafted by a `FacilityManager` (for their facility) or a `DistributorAdmin` supplying the `facility_id`, the `lines` array (each entry naming a `product_id`, a `qty` of at least one, and an optional `discount_pct` expressed as a fraction between 0 and 1, defaulting to 0), the requested `delivery_date`, and the `fuel_index` — the diesel index quoted at placement, which becomes the basis of the quoted fuel surcharge. The order is born `DRAFT` with `source` `MANUAL`, a null `standing_order_id`, `trial_credit_cents` of zero, and its lines born `PENDING`. Individual lines are addressable after creation — each carries its `order_id`, `product_id`, `qty`, `discount_pct`, and the computed `unit_price_cents` and `line_total_cents` — and the order-line list accepts `order_id`, `product_id`, and `status` filters, while the order list accepts `facility_id`, `standing_order_id`, and `status` filters.

Placement is the pivotal act, and its checks run in a fixed sequence after the generic stack of §2.11: the order must be `DRAFT` (`ERR_INVALID_STATE` otherwise); the facility must be `ACTIVE` (`ERR_FACILITY_INACTIVE`); every line's product must be `ACTIVE` (`ERR_PRODUCT_UNAVAILABLE`); every line must be stock-sufficient under the all-or-nothing rule of §2.10, where a line exactly equal to the available stock allocates (`ERR_INSUFFICIENT_STOCK`); every line whose product has `dilution_required` set must be backed by an existing `CERTIFIED` training record for the facility and product (`ERR_TRAINING_NOT_CERTIFIED`); and finally the credit check of §2.9 must pass, with a committed-plus-total sum exactly equal to `credit_limit_cents` passing (`ERR_CREDIT_LIMIT_EXCEEDED`).

On success, placement freezes the order's economics. Each line moves `PENDING → ALLOCATED`, its stock moves from `qty_on_hand` into `qty_allocated`, and its `unit_price_cents` is frozen to the effective unit price at the placement instant — the covering `AWARDED` bid's `bid_price_cents` when one exists for the facility's group and the product, otherwise the product's `base_price_cents` (the full selection rule lives in §3.8). Each `line_total_cents` is the quantity times the unit price times one minus the discount fraction, rounded half up to integer cents — per line first, per §2.6 — and `merchandise_subtotal_cents` is the sum of those rounded line totals, with `CANCELLED` lines contributing nothing. The rollup then proceeds in a pinned order that breaks the fee-versus-surcharge circularity: first the merchandise subtotal; then `delivery_fee_cents`, which covers the shortfall between the subtotal and the 5,000-cent ($50.00) delivery minimum and is zero when the subtotal meets or exceeds it; then `fuel_surcharge_cents`, computed on the combined base of subtotal plus delivery fee as that base times a diesel-index percentage — 4 percent when the index is below 3.00, 6 percent when it is at least 3.00 but below 4.00, and 9 percent when it is 4.00 or higher — times a distance multiplier read from the facility's `delivery_distance_miles` — 1.0 under 25 miles, 1.25 at 25 miles or more but under 75, and 1.5 at 75 miles or more — with the result rounded half up to integer cents; and finally `total_cents`, the subtotal plus fee plus surcharge minus `trial_credit_cents`, floored at zero. At placement this surcharge is the `QUOTED` variant, computed from the order's `fuel_index`, and `fuel_surcharge_variant` reads `QUOTED`; `placed_at` is stamped, the order moves `DRAFT → PLACED`, and the facility's `committed_cents` rises by `total_cents`.

Delivery closes the loop on pricing. A `DistributorAdmin` confirming delivery — allowed only from `PLACED` — supplies the `fuel_index_at_delivery`, the diesel index on the delivery day. The surcharge is recomputed under the `ACTUAL` variant from that index on the same combined base, `total_cents` is recomputed, `fuel_surcharge_variant` flips to `ACTUAL`, every `ALLOCATED` line moves to `FULFILLED` with its reservation released from `qty_allocated` (the `qty_on_hand` stays reduced — the goods have shipped), and the facility's `committed_cents` is adjusted to the new total. Identical order data therefore yields a different surcharge whenever the diesel index moved between quote and delivery. Invoicing, also by a `DistributorAdmin`, moves `DELIVERED → INVOICED` and shifts the money across the ledger: `committed_cents` falls by the order's `total_cents` and `outstanding_cents` rises by the same amount. Both `INVOICED` and `CANCELLED` are terminal.

Cancellation is a compensated unwind available to a `FacilityManager` or `DistributorAdmin` from `DRAFT`, `PLACED`, or `PARTIALLY_BLOCKED`, subject to the facility gate (`ERR_FACILITY_INACTIVE` when the facility is not `ACTIVE`). Every line still `PENDING`, `ALLOCATED`, or `SUBSTITUTION_PENDING` moves to `CANCELLED`; allocated reservations are released back to `qty_on_hand`; any still-`PENDING` substitution proposals attached to the cancelled lines are moved to `DECLINED`; and when the cancelled order was `PLACED` or `PARTIALLY_BLOCKED`, the facility's `committed_cents` falls by the order's `total_cents`.

Two automatic transitions keep the order's state honest while substitutions are in flight, and they are spelled out with the cascade in §3.7: a `PLACED` order with at least one line in `SUBSTITUTION_PENDING` drops to `PARTIALLY_BLOCKED`; a `PARTIALLY_BLOCKED` order with no lines left in `SUBSTITUTION_PENDING` and at least one line `ALLOCATED` or `FULFILLED` climbs back to `PLACED` with its money fields recomputed and `committed_cents` adjusted; and a `PLACED` or `PARTIALLY_BLOCKED` order whose lines are all `CANCELLED` collapses to `CANCELLED`, releasing its total from `committed_cents`.

### 3.7. Shortage Response and the Substitution Cascade

When a `DistributorAdmin` declares a shortage on an `ACTIVE` product, the system runs a three-link cascade. The first link walks every order line referencing that product in `PENDING` or `ALLOCATED` status. An `ALLOCATED` line first releases its reservation — units return from `qty_allocated` to `qty_on_hand` — and only then is its fate decided. For each affected line the substitute selector looks for an eligible replacement: a product that is `ACTIVE`, shares the original's category, and is not the original product. Candidates are ranked by lowest `base_price_cents`, ties broken by earliest `created_at`. When the candidate set is non-empty the line moves to `SUBSTITUTION_PENDING` and the system creates a substitution proposal in `PENDING` status naming the `order_line_id`, the `original_product_id`, the selector's `proposed_product_id`, an `expires_at` exactly 7 days out, and a `price_delta_cents` — the proposed product's effective unit price minus the original's, times the line quantity, so a negative delta means the substitute is cheaper. When the candidate set is empty the line moves straight to `CANCELLED` and no proposal is created; a `PENDING` line follows the same fate fork without any reservation to release.

The second link repairs each parent order of a mutated line: `merchandise_subtotal_cents`, `delivery_fee_cents`, `fuel_surcharge_cents`, and `total_cents` are recomputed over the surviving lines, and the order's status follows the auto-transition rules — all lines `CANCELLED` collapses the order to `CANCELLED`, otherwise at least one line in `SUBSTITUTION_PENDING` drops it to `PARTIALLY_BLOCKED`. The third link resynchronizes the facility ledger, recomputing `committed_cents` over the facility's `PLACED`, `PARTIALLY_BLOCKED`, and `DELIVERED` orders — which drops by the cancelled order's total when an order auto-cancels. The product's `version` increments once for the whole event. Resolving the shortage later (`SHORTAGE → ACTIVE`) changes none of this retroactively: pending proposals are deliberately not auto-resolved and live out their own 7-day clocks.

Proposal adjudication belongs to the `FacilityManager` who owns the facility behind the proposal's order — anyone else draws `ERR_FORBIDDEN`. Acceptance requires the proposal to be `PENDING` (anything else is `ERR_INVALID_STATE`), its order line still `SUBSTITUTION_PENDING`, and the proposed product stock-sufficient under the same equality-allocates rule as placement (`ERR_INSUFFICIENT_STOCK` when short). An accepted proposal swaps the line's `product_id` to the proposed product, reprices the line at the proposed product's effective unit price at that instant, recomputes `line_total_cents`, allocates the proposed product's stock, finalizes `price_delta_cents`, and moves the proposal to `ACCEPTED`; the parent order's money fields are recomputed, and when no lines remain in `SUBSTITUTION_PENDING` the order climbs back to `PLACED` automatically, with `committed_cents` adjusted to the new total. Decline is the mirror: the proposal must be `PENDING`, the line moves `SUBSTITUTION_PENDING → CANCELLED`, the order is recomputed — collapsing to `CANCELLED` if every line is now cancelled, or returning to `PLACED` if no substitution-pending lines remain — and `committed_cents` is adjusted. Should the `FacilityManager` do nothing, the daily sweep expires a `PENDING` proposal once the clock is strictly past its `expires_at`, moving it to `EXPIRED` with exactly the same line, order, and ledger effects as a decline. The proposal list accepts `order_line_id`, `original_product_id`, `proposed_product_id`, and `status` filters.

### 3.8. Commercial Programs: Contract Bids and Sample Trials

Group purchasing flows through contract bids. A `SalesRep` creates a bid with an external `bid_reference` unique across all bids, the `facility_group_code` it prices, a non-empty `lines` array whose entries each pair a `product_id` with a `bid_price_cents`, and the price-protection window from `protection_start` to `protection_end` (the end must be strictly after the start). Bids are born `DRAFT` with `revision_number` zero, and the bid list accepts `facility_group_code` and `status` filters.

The bid lifecycle is a cycle with adjudication at its apex. Submitting moves `DRAFT → SUBMITTED` (stamping `submitted_at`), opening review moves `SUBMITTED → UNDER_REVIEW`, and from `UNDER_REVIEW` a `SalesRep` has two exits — returning for revision drops back to `DRAFT` and increments `revision_number` by one, closing the revision loop, while marking lost lands in the terminal `LOST` state. The award decision belongs to a `DistributorAdmin` and is guarded by the window-overlap rule: no other `AWARDED` bid for the same `facility_group_code` sharing any line product may have a protection window that intersects this bid's window, where windows are closed intervals — both endpoints inclusive — and windows that merely touch at an endpoint do intersect; a conflict is rejected with `ERR_PROTECTION_WINDOW_OVERLAP`. An `AWARDED` bid ends in one of two terminal states: `TERMINATED`, via termination by a `DistributorAdmin`, or `EXPIRED`, via the daily sweep once the clock is strictly past `protection_end`. Award, termination, and expiry all cascade to the standing-order base: every standing order in `ACTIVE` or `PAUSED` status whose facility's group matches the bid's `facility_group_code` recomputes `price_protected` and `next_delivery_total_cents`, with bid prices applying to covered items on award and ceasing to apply on termination or expiry.

Bid pricing feeds the system-wide effective-unit-price rule used at order placement, substitution reprice, standing-order preview, and standing-order generation. The candidate set is every `AWARDED` bid whose `facility_group_code` equals the facility's group, whose lines include the product, and whose closed protection window covers the current clock time. The overlap rule guarantees at most one candidate in practice; residual ties break by lowest `bid_price_cents`, then earliest `protection_start`, then earliest `created_at`. A non-empty candidate set yields the covering bid's `bid_price_cents`; otherwise the product's `base_price_cents` applies. The selection is pure lookup — no arithmetic, hence no rounding.

Sample and trial programs let a `SalesRep` seed a facility with free product. A trial is created with the `facility_id`, the `product_id`, a `trial_start` and `trial_end` bounding the evaluation window, and the `sample_value_cents` (never negative) recording the value of the free product placed. Trials are born `ACTIVE`, and at most one `ACTIVE` trial may exist per facility-and-product pairing — a duplicate create draws `ERR_TRIAL_ALREADY_ACTIVE`. The trial list accepts `facility_id`, `product_id`, `conversion_order_id`, and `status` filters.

Conversion turns goodwill into revenue and belongs to the `FacilityManager` who owns the trial's facility (`ERR_FORBIDDEN` for anyone else). The trial must be `ACTIVE`, and the clock must be on or before `trial_end` — conversion at the exact `trial_end` instant is allowed. The conversion request supplies a `qty`, a `delivery_date`, and a `fuel_index`; the system builds a conversion order with `source` `TRIAL_CONVERSION` and a single line for the trial product, then runs it through the normal placement pipeline of §3.6 — facility `ACTIVE`, dilution training where required, stock sufficiency, and the credit check evaluated on the post-credit total. The trial's reward is a credit: `conversion_credit_cents` is the smaller of the trial's `sample_value_cents` and the conversion order's `merchandise_subtotal_cents`, applied to the order as `trial_credit_cents` so the rollup floors the total at zero. On success the trial moves to the terminal `CONVERTED` state with its `conversion_order_id` set, and the facility's `committed_cents` rises by the conversion order's `total_cents`. Trials that never convert are expired by the daily sweep once the clock is strictly past `trial_end`, landing in the terminal `EXPIRED` state.

### 3.9. The Daily Ops Checkpoint

Once per operational day, a `DistributorAdmin` triggers the ops sweep, which executes five steps in a pinned order. First, `CERTIFIED` training records whose `expires_at` is strictly in the past move to `EXPIRED`. Second, `AWARDED` contract bids whose `protection_end` is strictly in the past move to `EXPIRED`, with the standing-order reprice cascade of §3.8. Third, `ACTIVE` trial programs whose `trial_end` is strictly in the past move to `EXPIRED`. Fourth, `PENDING` substitution proposals whose `expires_at` is strictly in the past move to `EXPIRED`, each running the line-cancellation cascade of §3.7. Fifth and last, the auto-replenishment engine of §3.5 generates orders from due `ACTIVE` standing orders and places them, recomputing each facility's `committed_cents` for every generated order. The sweep reports back a summary payload: `generated_count` and `generated_order_ids` for step five, plus `expired_training_record_ids`, `expired_bid_ids`, `expired_trial_ids`, and `expired_proposal_ids` for the four expiry steps. Because every expiry test is strict — strictly greater than the recorded deadline — a record whose deadline equals the current clock time survives the sweep for one more day.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — state transitions, planner updates, sweeps — return `200 OK`. Read endpoints return `200 OK`. The table below is a summary only; the request payloads, computed responses, and side effects of each operation are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/jansan/facilities` | Create a facility | DistributorAdmin |
| GET    | `/jansan/facilities/{facility_id}` | Fetch one facility | DistributorAdmin, FacilityManager, SalesRep, FieldTechnician |
| POST   | `/jansan/facilities/{facility_id}/suspend` | Suspend a facility; pauses its active standing orders | DistributorAdmin |
| POST   | `/jansan/facilities/{facility_id}/reinstate` | Reinstate a suspended facility; resumes suspension-paused standing orders only | DistributorAdmin |
| POST   | `/jansan/facilities/{facility_id}/archive` | Archive a facility (blocked by open orders or standing orders) | DistributorAdmin |
| POST   | `/jansan/products` | Create a product with initial stock | DistributorAdmin |
| GET    | `/jansan/products/{product_id}` | Fetch one product | DistributorAdmin, FacilityManager, SalesRep, FieldTechnician |
| POST   | `/jansan/products/{product_id}/declare-shortage` | Declare a shortage; runs the substitution cascade over open order lines | DistributorAdmin |
| POST   | `/jansan/products/{product_id}/resolve-shortage` | Resolve a shortage back to active | DistributorAdmin |
| POST   | `/jansan/products/{product_id}/discontinue` | Discontinue a product with no open order lines | DistributorAdmin |
| POST   | `/jansan/usage-records` | Submit a usage record | FacilityManager, DistributorAdmin |
| GET    | `/jansan/usage-records/{usage_record_id}` | Fetch one usage record | DistributorAdmin, FacilityManager, SalesRep |
| GET    | `/jansan/usage-records` | List usage records with filters | DistributorAdmin, FacilityManager, SalesRep |
| POST   | `/jansan/usage-records/{usage_record_id}/post` | Post a submitted usage record | DistributorAdmin |
| POST   | `/jansan/forecast-profiles` | Create a forecast profile for a facility and product | DistributorAdmin |
| GET    | `/jansan/forecast-profiles/{forecast_profile_id}` | Fetch one forecast profile | DistributorAdmin, FacilityManager, SalesRep |
| GET    | `/jansan/forecast-profiles` | List forecast profiles with filters | DistributorAdmin, FacilityManager, SalesRep |
| PATCH  | `/jansan/forecast-profiles/{forecast_profile_id}` | OCC-guarded planner update of profile tunables | DistributorAdmin |
| POST   | `/jansan/forecast-profiles/{forecast_profile_id}/recompute` | Recompute the usage forecast with the given variant | DistributorAdmin, FacilityManager |
| POST   | `/jansan/technicians` | Create a field technician | DistributorAdmin |
| POST   | `/jansan/dispensers` | Schedule a dispenser install (zone and technician-window checks) | DistributorAdmin |
| GET    | `/jansan/dispensers/{dispenser_id}` | Fetch one dispenser | DistributorAdmin, FacilityManager, FieldTechnician |
| GET    | `/jansan/dispensers` | List dispensers with filters | DistributorAdmin, FacilityManager, FieldTechnician |
| POST   | `/jansan/dispensers/{dispenser_id}/complete` | Complete an install (training-gated when applicable) | FieldTechnician |
| POST   | `/jansan/dispensers/{dispenser_id}/decommission` | Decommission an installed dispenser | DistributorAdmin |
| POST   | `/jansan/training-records` | Schedule dilution training for a facility employee | DistributorAdmin |
| GET    | `/jansan/training-records/{training_record_id}` | Fetch one training record | DistributorAdmin, FacilityManager, SalesRep |
| GET    | `/jansan/training-records` | List training records with filters | DistributorAdmin, FacilityManager, SalesRep |
| POST   | `/jansan/training-records/{training_record_id}/certify` | Certify or fail a scheduled training by score | DistributorAdmin |
| POST   | `/jansan/standing-orders` | Create a standing order | FacilityManager, DistributorAdmin |
| GET    | `/jansan/standing-orders/{standing_order_id}` | Fetch one standing order | DistributorAdmin, FacilityManager, SalesRep |
| GET    | `/jansan/standing-orders` | List standing orders with filters | DistributorAdmin, FacilityManager, SalesRep |
| POST   | `/jansan/standing-orders/{standing_order_id}/activate` | Activate a draft standing order; previews next delivery total | FacilityManager, DistributorAdmin |
| POST   | `/jansan/standing-orders/{standing_order_id}/pause` | Pause an active standing order (manual) | FacilityManager, DistributorAdmin |
| POST   | `/jansan/standing-orders/{standing_order_id}/resume` | Resume a paused standing order | FacilityManager, DistributorAdmin |
| POST   | `/jansan/standing-orders/{standing_order_id}/cancel` | Cancel a standing order | FacilityManager, DistributorAdmin |
| POST   | `/jansan/orders` | Create a manual order in draft with its lines | FacilityManager, DistributorAdmin |
| GET    | `/jansan/orders/{order_id}` | Fetch one order | DistributorAdmin, FacilityManager, SalesRep |
| GET    | `/jansan/orders` | List orders with filters | DistributorAdmin, FacilityManager, SalesRep |
| POST   | `/jansan/orders/{order_id}/place` | Place a draft order; freezes prices, allocates stock | FacilityManager, DistributorAdmin |
| POST   | `/jansan/orders/{order_id}/confirm-delivery` | Confirm delivery; reprices the fuel surcharge at the delivery-day index | DistributorAdmin |
| POST   | `/jansan/orders/{order_id}/invoice` | Invoice a delivered order; moves committed exposure to outstanding | DistributorAdmin |
| POST   | `/jansan/orders/{order_id}/cancel` | Cancel an order with allocation and credit compensation | FacilityManager, DistributorAdmin |
| GET    | `/jansan/order-lines/{order_line_id}` | Fetch one order line | DistributorAdmin, FacilityManager, SalesRep |
| GET    | `/jansan/order-lines` | List order lines with filters | DistributorAdmin, FacilityManager, SalesRep |
| GET    | `/jansan/substitution-proposals/{proposal_id}` | Fetch one substitution proposal | DistributorAdmin, FacilityManager |
| GET    | `/jansan/substitution-proposals` | List substitution proposals with filters | DistributorAdmin, FacilityManager |
| POST   | `/jansan/substitution-proposals/{proposal_id}/accept` | Accept a proposal; swaps, reprices, and allocates the line | FacilityManager |
| POST   | `/jansan/substitution-proposals/{proposal_id}/decline` | Decline a proposal; cancels the line | FacilityManager |
| POST   | `/jansan/contract-bids` | Create a GPO/co-op contract bid | SalesRep |
| GET    | `/jansan/contract-bids/{bid_id}` | Fetch one contract bid | DistributorAdmin, SalesRep |
| GET    | `/jansan/contract-bids` | List contract bids with filters | DistributorAdmin, SalesRep |
| POST   | `/jansan/contract-bids/{bid_id}/submit` | Submit a draft bid | SalesRep |
| POST   | `/jansan/contract-bids/{bid_id}/open-review` | Open review on a submitted bid | SalesRep |
| POST   | `/jansan/contract-bids/{bid_id}/return-for-revision` | Return a bid under review to draft, bumping its revision number | SalesRep |
| POST   | `/jansan/contract-bids/{bid_id}/award` | Award a bid under review; runs the window-overlap check and reprice cascade | DistributorAdmin |
| POST   | `/jansan/contract-bids/{bid_id}/mark-lost` | Mark a bid under review as lost | SalesRep |
| POST   | `/jansan/contract-bids/{bid_id}/terminate` | Terminate an awarded bid; runs the reprice cascade | DistributorAdmin |
| POST   | `/jansan/trial-programs` | Create a sample/trial program | SalesRep |
| GET    | `/jansan/trial-programs/{trial_program_id}` | Fetch one trial program | DistributorAdmin, SalesRep, FacilityManager |
| GET    | `/jansan/trial-programs` | List trial programs with filters | DistributorAdmin, SalesRep, FacilityManager |
| POST   | `/jansan/trial-programs/{trial_program_id}/convert` | Convert a trial; generates and places the conversion order with trial credit | FacilityManager |
| POST   | `/jansan/ops/run-daily` | Run the daily ops sweep (expiry steps, then standing-order generation) | DistributorAdmin |
| POST   | `/jansan/_clock/set_current_utc` | Advance the logical clock (monotonic) | DistributorAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The trigger condition for each error is defined where it arises in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FACILITY_INACTIVE` | 409 |
| `ERR_PRODUCT_UNAVAILABLE` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_TRAINING_NOT_CERTIFIED` | 409 |
| `ERR_INCOMPATIBLE_PLACEMENT` | 409 |
| `ERR_TECHNICIAN_WINDOW_CONFLICT` | 409 |
| `ERR_PROTECTION_WINDOW_OVERLAP` | 409 |
| `ERR_CLOCK_REGRESSION` | 400 |
| `ERR_DUPLICATE_STANDING_ORDER` | 409 |
| `ERR_TRIAL_ALREADY_ACTIVE` | 409 |
| `ERR_DISCONTINUE_BLOCKED` | 409 |
| `ERR_ARCHIVE_BLOCKED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 |
