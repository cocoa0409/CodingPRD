# Corporate Catering & Cafeteria Management API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a managed corporate-catering and cafeteria operation of the kind an Aramark- or Sodexo-style provider runs on behalf of a corporate client. A single provider operates cafeterias at many client sites; at each site the platform coordinates a rotating cycle menu, plans meal-period service sessions against a production forecast, processes badge- and wallet-based point-of-sale purchases with employer subsidy, tracks purchased inventory and the food cost of what is actually consumed, books special-event catering into bookable venues, reconciles vendor invoices against purchase orders, and gathers diner satisfaction. The recurring theme across the domain is the tension between what things were *expected* to cost and what they *actually* cost: recipe-based theoretical food cost is measured against the FIFO value of the physical inventory drawn down, and a catering order's forward-looking estimate is later replaced by the real cost of the lots consumed to serve it.

The service is a fiscal system of record. Money is always carried in integer cents, inventory is valued lot-by-lot in strict first-in-first-out order, and a client site's period food-cost ratio is continuously reconciled so that operators can see the moment a site drifts over its target. Because several independent workflows — session closes, purchase-order receipts, and catering confirmations — all draw from and revalue the same shared per-site inventory pool, the platform serializes those writes through an explicit version on each site and through optimistic concurrency on the one operation (catering confirmation) that reserves stock the caller may not have seen most recently. Responsibilities are deliberately segregated: the coordinator who drafts a catering order may never be the person who approves it, and only a finance controller may confirm inventory reservations or settle vendor invoices.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` (the caller's identity) and `X-User-Role` (the caller's role). If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authorization is evaluated per operation against the role assignments summarized in §4.

The system recognizes exactly six roles, spelled precisely as follows: `SiteAdmin`, `CafeteriaManager`, `Diner`, `CateringCoordinator`, `CateringApprover`, and `FinanceController`.

Five of these roles carry an **opaque** identity: `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server may record such an identifier where a workflow calls for it, but it never compares it to any entity's `id`. Concretely, a `SiteAdmin`, a `CafeteriaManager`, a `CateringApprover`, and a `FinanceController` are all opaque operators. A `CateringCoordinator` is likewise opaque, but when a coordinator creates a catering order the server records that caller's `X-User-ID` on the order as its `coordinator_id`; this stored value is used later only for the segregation-of-duties check, never as an entity key.

The `Diner` role is **entity-backed**: when `X-User-Role` is `Diner`, `X-User-ID` is the `id` of the acting `Employee`. Ownership checks on any resource that references an employee compare that resource's employee foreign key to `X-User-ID`; in particular, a diner may only create a point-of-sale transaction for which the supplied `employee_id` equals the caller's own `X-User-ID`, and may read their own employee record.

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

All list endpoints are paginated through two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. The `offset` parameter defaults to 0 and counts the number of leading records to skip. A `limit` or `offset` outside its permitted range is a body/parameter validation failure and is rejected with `ERR_VALIDATION` (HTTP 400).

List results are always returned in ascending order of the resource's `created_at` timestamp — that is, oldest first. Each list response reports pagination state in `meta` through four fields: `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. The Logical Clock and Time-Sensitive Fields

The service runs on a **logical clock** rather than the host wall clock, so that time-dependent behavior is fully reproducible under test. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is advanced it continues to read that default — never the real wall-clock time. A `SiteAdmin` may advance the clock by supplying a target instant in the `to_iso8601` field; the operation reports the new `current_utc`. The logical clock is authoritative for every server-stamped instant: the `received_at` on an inventory lot, the `subsidy_day` bucket that governs a diner's daily subsidy, and the boundaries used when checking whether two catering events overlap on a venue.

Datetime inputs such as a service session's `window_start` and `window_end`, and a catering order's `event_start` and `event_end`, are ISO 8601 UTC instants. A session's `window_end` must be strictly later than its `window_start`, and a catering order's `event_end` must be strictly later than its `event_start`; violations are validation failures (`ERR_VALIDATION`). Calendar-day fields such as a session's `service_date` and a catering order's `event_date` are `YYYY-MM-DD` strings.

### 2.5. Common Resource Properties and Versioning

Unless a resource is explicitly noted otherwise below, every resource carries four common properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits, sourced from the logical clock at creation and at each subsequent mutation. The `version` is an integer that begins at 1 when the resource is created and increases by 1 on every mutation of that resource.

Two entities are exceptions that carry **only** `id` and `created_at`, with neither `updated_at` nor `version`: the waste event and the satisfaction survey. Both are immutable append-only records — once written they are never modified — so they do not participate in versioning.

Note that a client site's `version` is bumped not only by direct edits but by any write that changes its shared inventory pool. Receiving a purchase order, closing a service session, confirming or fulfilling a catering order, and cancelling a confirmed catering order each increment the owning `ClientSite`'s `version` by 1, because each of those operations alters inventory that the site's derived value and availability figures depend on. This is the hook the concurrency control in §2.7 relies on.

### 2.6. Monetary Precision and Rounding

All monetary amounts are integer counts of cents; there are no fractional-cent values in stored data. Wherever a computation would produce a fractional cent — applying a subsidy percentage, an overhead factor, a volume discount, or a service-fee percentage — the result is rounded to the nearest whole cent using **round half up** (a residual of exactly one half cent rounds upward). The specific rounding points are called out with each calculation in §3, because the order of rounding relative to summation is significant.

Two derived ratios are not money and follow their own precision. A site's `food_cost_pct` is a ratio computed to four decimal places using round half up. A site's `satisfaction_avg` is a mean rating computed to two decimal places using round half up.

### 2.7. Optimistic Concurrency on the Shared Inventory Pool

Confirming an approved catering order reserves stock from the client site's shared inventory pool, which the same site's session closes, purchase-order receipts, and other catering confirmations also draw down. To prevent a caller from reserving against a view of the pool that has since changed, the confirm operation is guarded by optimistic concurrency keyed on the client site's `version`.

A confirm request must include `expected_client_site_version`, carrying the `version` of the target order's `ClientSite` as the caller last observed it. This field is mandatory on confirm and is not accepted on any other endpoint; operations that are not the catering confirmation neither require nor read a version field. If `expected_client_site_version` does not equal the site's current `version` — because some other inventory-mutating write (a purchase-order receipt, a session close, or another catering confirmation) has advanced the site version since the caller last read it — the confirmation is rejected with `ERR_STALE_SITE_VERSION` (HTTP 412) and no inventory is reserved. The caller must re-read the site, observe the new pool state, and retry with the current version.

### 2.8. Reference Resolution and Validation Ordering

When an endpoint carries path identifiers and body foreign keys, they are resolved left to right; the first identifier that does not resolve to an existing resource causes an `ERR_NOT_FOUND` (HTTP 404). Because entities in this domain are peers linked by foreign keys rather than nested under one another, a request that names, say, a client site and a venue is checked against each referenced resource in turn.

Validation across the whole API follows a fixed priority order, and the **first** failing check in this order determines the error returned; a later check never masks an earlier one:

1. Authentication — both identity headers present, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — the acting role may perform this operation, else `ERR_UNAUTHORIZED` (403).
3. Body validation — required fields present, enums valid, and numeric ranges satisfied (for example a rating between 1 and 5, a quantity of at least 1, or a percentage between 0 and 1), else `ERR_VALIDATION` (400).
4. Existence — path ids and referenced foreign keys resolve, else `ERR_NOT_FOUND` (404).
5. State — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE` (409).
6. Allergen safety — no ordered item conflicts with a diner's restrictions, else `ERR_ALLERGEN_CONFLICT` (422).
7. Referential business rules — the diner is not terminated, and a catering approver is not the order's coordinator, else `ERR_EMPLOYEE_INACTIVE` or `ERR_SEGREGATION_OF_DUTIES` (409).
8. Temporal rules — venue time overlap and session changeover buffer, else `ERR_VENUE_TIME_CONFLICT` or `ERR_SESSION_BUFFER_CONFLICT` (409).
9. Uniqueness and capacity — session slot uniqueness, venue capacity, and badge uniqueness, else `ERR_DUPLICATE_SESSION_SLOT`, `ERR_VENUE_CAPACITY_EXCEEDED`, or `ERR_DUPLICATE_BADGE` (409).
10. Fiscal sufficiency — enough inventory, enough wallet balance, or a small-enough invoice variance, else `ERR_INSUFFICIENT_INVENTORY`, `ERR_WALLET_INSUFFICIENT`, or `ERR_VARIANCE_TOO_LARGE` (409).
11. Optimistic concurrency — the expected site version matches, else `ERR_STALE_SITE_VERSION` (412).

### 2.9. The Period Food-Cost Ledger

Each client site continuously reconciles a period ledger from which its cost health is derived. Two running totals feed it. The `period_food_cost_cents` is the sum of three streams: the finalized actual food cost of every `CLOSED` service session, the cost of every waste event, and the final cost of every catering order that has reached `FULFILLED` or `INVOICED`. The `period_revenue_cents` is the sum of the revenue of every `CLOSED` service session plus the total client charge of every `INVOICED` catering order.

From these, `food_cost_pct` is the period food cost divided by the period revenue, expressed as a ratio to four decimal places with round half up. When `period_revenue_cents` is 0 the division is undefined and `food_cost_pct` is reported as null. The site's `cost_status` is `OVER_TARGET` when `food_cost_pct` is not null and strictly greater than the site's `food_cost_target_pct`; otherwise it is `ON_TARGET` (including whenever `food_cost_pct` is null). This reconciliation runs whenever any of its inputs change — on a session close, a catering fulfillment, a catering invoice, or a waste event.

Two further site figures are derived rather than stored directly. The `inventory_value_cents` is the sum, over the site's `AVAILABLE` inventory lots, of each lot's remaining on-hand quantity multiplied by its unit cost. The `satisfaction_avg` is the mean of the ratings on the site's satisfaction surveys, to two decimal places with round half up, and is null when the site has no surveys.

### 2.10. Inventory Lots, FIFO Valuation, and Reservations

Physical stock is held as **inventory lots**, each owned by one client site and created when a purchase order is received. A lot records the `ingredient` key and `unit_cost_cents` copied from the originating purchase-order line, the `qty_received` it was created with, the `qty_on_hand` still physically present, the `qty_reserved` currently held for confirmed-but-unfulfilled catering orders (0 at creation), its `received_at` instant from the logical clock, and a `status` of `AVAILABLE` or `DEPLETED`. A lot becomes `DEPLETED` the moment its on-hand quantity reaches 0.

Whenever the system values consumed inventory it walks the site's `AVAILABLE` lots of the needed ingredient in strict FIFO order — earliest `received_at` first, breaking ties by earliest `created_at` — taking from each lot the smaller of the remaining need and that lot's on-hand quantity, and accumulating each amount taken multiplied by that lot's unit cost. This same FIFO valuation is used at session close and at catering fulfillment. Reservations, by contrast, do not consume: confirming a catering order raises `qty_reserved` on lots in the same FIFO order without lowering `qty_on_hand`, and the amount available to a *new* reservation for an ingredient is the sum over the site's `AVAILABLE` lots of on-hand minus reserved.

## 3. Business Logic & Workflows

### 3.1. Site, Workforce, Menu, and Venue Setup

A `SiteAdmin` establishes a client site, supplying its display `name`, the `client_name` of the corporate customer, and the fiscal configuration the rest of the platform reads. That configuration includes the `currency` (one of `USD`, `EUR`, or `GBP`, defaulting to `USD`), the `employer_subsidy_pct` (a fraction between 0 and 1 inclusive of the subsidizable subtotal the employer covers on each transaction), the `daily_subsidy_cap_cents` (the most subsidy one employee may draw per logical-clock day), the `food_cost_target_pct` (the target period food-cost ratio, a fraction between 0 and 1 inclusive), and the `session_changeover_buffer_minutes` (the minimum gap required between two sessions on the same date at the site, defaulting to 30). A new site opens `ACTIVE` with `cost_status` of `ON_TARGET`, its ledger counters `period_food_cost_cents`, `period_revenue_cents`, and `inventory_value_cents` at 0, and `version` 1. A site admin may later move a site from `ACTIVE` to `SUSPENDED`, and back from `SUSPENDED` to `ACTIVE`; while a site is `SUSPENDED`, catering confirmations against it are blocked (see §3.6).

Employees are registered at a site by a site admin, who provides the owning `client_site_id`, a `badge_id` unique among employees at that site, and the employee's `full_name`. Optionally the admin supplies `restricted_allergens` (defaulting to an empty list) and an opening `wallet_balance_cents` (defaulting to 0). Each `badge_id` must be unique within its site; a collision is rejected with `ERR_DUPLICATE_BADGE`. A new employee is `ACTIVE` with `daily_subsidy_used_cents` at 0; the `subsidy_day` bucket that this counter accounts for is set from the logical clock on the employee's first transaction. A site admin may `terminate` an employee, moving them from `ACTIVE` to the terminal `TERMINATED` state, after which any attempt to create a point-of-sale transaction for that employee is rejected with `ERR_EMPLOYEE_INACTIVE`.

A `CafeteriaManager` builds the menu. A menu cycle is created in `DRAFT` for a given `client_site_id` with a `name` and a `cycle_length_weeks` rotation length of at least 1. Individual menu items are added to a cycle by `menu_cycle_id`, each with a `name`, a `category` (one of `ENTREE`, `SIDE`, `BEVERAGE`, `DESSERT`, or `HEALTHY`), a `price_cents` of at least 0, a `standard_recipe_cost_cents` of at least 0 representing the theoretical per-portion ingredient cost, and optional `allergens` (defaulting to empty, drawn from `PEANUTS`, `TREE_NUTS`, `DAIRY`, `GLUTEN`, `SOY`, `SHELLFISH`, and `EGGS`). A menu item is created `ACTIVE` and stays `ACTIVE`; the state is retained only for label lifecycle. Publishing a cycle transitions it from `DRAFT` to the terminal `PUBLISHED` state, and requires that at least one menu item already exists for that cycle — publishing an empty cycle is rejected with `ERR_EMPTY_MENU_CYCLE`. Only a `PUBLISHED` cycle can back an open service session.

Catering venues are created by a site admin for a site, each with a `client_site_id`, a room `name`, and a `capacity` (the maximum headcount it seats) of at least 1.

### 3.2. Planning and Opening a Service Session

A cafeteria manager plans a meal-period **service session** for a site, referencing the `client_site_id` and the `menu_cycle_id` to be served, and supplying the `service_date`, the `meal_period` (`BREAKFAST`, `LUNCH`, or `DINNER`), the `window_start` and `window_end` of the service window, and a `forecast_headcount` (a projected diner count of at least 0). A site may hold only one session per combination of site, date, and meal period; a duplicate is rejected with `ERR_DUPLICATE_SESSION_SLOT`. Additionally, any two sessions on the same date at a site must be separated by at least the site's `session_changeover_buffer_minutes`; a session planned too close to an existing one on that date is rejected with `ERR_SESSION_BUFFER_CONFLICT`. A new session begins `PLANNED`, with its computed figures `actual_headcount` and `revenue_cents` at 0, `theoretical_food_cost_cents` at 0, and `actual_food_cost_cents` null until the session is closed.

Before service can begin, the forecast is locked: locking moves the session from `PLANNED` to `FORECAST_LOCKED` and requires that `forecast_headcount` has been set, after which `forecast_headcount` becomes immutable. Opening the session then advances it from `FORECAST_LOCKED` to `IN_SERVICE`, and requires that the referenced menu cycle is `PUBLISHED`; opening against a non-published cycle is rejected with `ERR_MENU_CYCLE_NOT_PUBLISHED`. Only once a session is `IN_SERVICE` may point-of-sale transactions be recorded against it. A cafeteria manager may cancel a session from `PLANNED`, from `FORECAST_LOCKED`, or from `IN_SERVICE`, moving it to the terminal `CANCELLED` state — except that a session already carrying one or more `COMPLETED` transactions cannot be cancelled from `IN_SERVICE`, which is rejected with `ERR_SESSION_HAS_SALES`.

### 3.3. Point-of-Sale: Subsidy, Wallet, and Allergen Safety

A `Diner` makes a badge purchase against an `IN_SERVICE` session by submitting a transaction naming the `employee_id`, the `service_session_id`, the `lines` of the order (each an object with a `menu_item_id` and a `qty` of at least 1), and a `payment_method` of `BADGE_PAYROLL` or `WALLET`. The diner's `X-User-ID` must equal the supplied `employee_id`. The session must be `IN_SERVICE`, or the purchase is rejected with `ERR_SESSION_NOT_OPEN`; the employee must not be `TERMINATED`, or it is rejected with `ERR_EMPLOYEE_INACTIVE`. As a safety gate, no line's menu item may carry an allergen that appears in the employee's `restricted_allergens`; any intersection rejects the whole transaction with `ERR_ALLERGEN_CONFLICT`.

The charge is computed as follows. The transaction's `subtotal_cents` is the sum over its lines of the menu item's `price_cents` times `qty`. The subsidizable portion is the sum over only those lines whose menu item `category` is `ENTREE` or `HEALTHY` of `price_cents` times `qty` — sides, beverages, and desserts are never subsidized. The gross subsidy is that subsidizable amount multiplied by the site's `employer_subsidy_pct`, rounded half up to whole cents. Before applying it, the employee's daily allowance is reconciled against the logical clock: if the employee's `subsidy_day` is not the current clock date, `daily_subsidy_used_cents` is treated as 0 for this transaction (a new day resets the counter). The remaining daily allowance is the site's `daily_subsidy_cap_cents` minus the employee's `daily_subsidy_used_cents`, but never below 0. The `subsidy_applied_cents` actually granted is the smaller of the gross subsidy and that remaining allowance. The `employee_charge_cents` is `subtotal_cents` minus `subsidy_applied_cents`.

When the payment method is `WALLET`, the employee's `wallet_balance_cents` must be at least the employee charge, or the purchase is rejected with `ERR_WALLET_INSUFFICIENT`; on success the wallet is debited by the employee charge. Regardless of method, the granted subsidy is added to `daily_subsidy_used_cents` (and `subsidy_day` is set to the current clock date), and the session's running figures are updated: `revenue_cents` increases by the subtotal, `theoretical_food_cost_cents` increases by the sum over the lines of the menu item's `standard_recipe_cost_cents` times `qty`, and `actual_headcount` increases by 1. A transaction is created `COMPLETED`.

A cafeteria manager may `void` a transaction, moving it from `COMPLETED` to the terminal `VOIDED` state, provided the parent session is still `IN_SERVICE` (otherwise `ERR_SESSION_NOT_OPEN`). Voiding is fully compensating: if the original payment was `WALLET`, the employee's `wallet_balance_cents` is credited back by the `employee_charge_cents`; the employee's `daily_subsidy_used_cents` is reduced by the `subsidy_applied_cents`, floored at 0; and the session's `revenue_cents` is reduced by the `subtotal_cents`, its `theoretical_food_cost_cents` reduced by that transaction's recipe cost, and its `actual_headcount` reduced by 1. Note that `revenue_cents` and `theoretical_food_cost_cents` are maintained incrementally on each completed and voided transaction; only the *actual* food cost is deferred to close.

### 3.4. Closing a Session and Rolling Up Cost

Closing a session advances it from `IN_SERVICE` to the terminal `CLOSED` state and is where actual food cost is finalized. The close request carries `consumed_ingredients`, a list of `{ ingredient, qty }` lines describing what was physically drawn from stock. The manager-supplied consumption is valued by FIFO against the site's `AVAILABLE` lots of each ingredient (earliest `received_at` first, ties broken by earliest `created_at`), producing `actual_food_cost_cents`. If the available inventory cannot cover a consumed line, the close is rejected with `ERR_INSUFFICIENT_INVENTORY` and nothing is consumed — there is no partial drawdown.

On a successful close, several effects cascade. First, each consumed lot has its `qty_on_hand` decremented by the amount taken, and any lot reaching 0 becomes `DEPLETED`. Second, the site ledger is rolled up: `period_food_cost_cents` increases by this session's `actual_food_cost_cents`, `period_revenue_cents` increases by this session's `revenue_cents`, `inventory_value_cents` is recomputed over the remaining available lots, and `food_cost_pct` is recomputed. Third, if the recomputed `food_cost_pct` now exceeds the site's `food_cost_target_pct`, the site's `cost_status` flips to `OVER_TARGET`, and as part of the same cascade every catering order at that site currently in `SUBMITTED` status is stamped with `requires_finance_review` set to true — flagging in-flight orders for extra scrutiny because the site has just breached its target. Finally, the close increments the site's `version` by 1, since the inventory pool has changed.

### 3.5. Procurement, Receiving, and Waste

Purchasing is run by a cafeteria manager and settled by finance. A purchase order is drafted for a `vendor_id` and a destination `client_site_id`, with `lines` each carrying a free-text `ingredient`, a `qty` of at least 1, and a `unit_cost_cents` of at least 0; the order's `total_cents` is the sum over its lines of `qty` times `unit_cost_cents`, and it opens in `DRAFT`. Vendors themselves are created by a site admin with a `name` and a `category` (`PRODUCE`, `PROTEIN`, `DRY_GOODS`, `BEVERAGE`, or `DISPOSABLES`) and remain `ACTIVE`.

Issuing a purchase order moves it from `DRAFT` to `ISSUED` and requires that it have at least one line. Receiving moves it from `ISSUED` to the terminal `RECEIVED` state and materializes stock: for each order line the system creates an inventory lot at the destination site with `qty_received` and `qty_on_hand` equal to the line quantity, `unit_cost_cents` copied from the line, `ingredient` copied from the line, `received_at` stamped from the logical clock, and `status` `AVAILABLE`. The site's `inventory_value_cents` is then recomputed to include the new lots, and the site's `version` is incremented by 1. A purchase order may instead be cancelled from `DRAFT` or from `ISSUED`, moving it to the terminal `CANCELLED` state.

Waste is logged by a cafeteria manager against a specific lot, naming the `client_site_id`, the `inventory_lot_id`, a wasted `qty` of at least 1, and a `reason` (`SPOILAGE`, `OVERPRODUCTION`, `PREP_ERROR`, or `EXPIRY`). The event's `cost_cents` is the wasted quantity multiplied by that lot's `unit_cost_cents`. Logging waste decrements the lot's `qty_on_hand` by the wasted quantity, marks the lot `DEPLETED` if it reaches 0, adds the waste cost to the site's `period_food_cost_cents`, and triggers recomputation of `food_cost_pct`. A waste event is an immutable record and carries no `version`.

### 3.6. The Catering Order Lifecycle

A `CateringCoordinator` drafts a special-event **catering order** for a site, naming the `client_site_id`, the `venue_id` (which must belong to the same site), the `event_date`, the `event_start` and `event_end` instants, an expected `headcount` of at least 1, and the `lines` to be served (each a `menu_item_id` with a `qty` of at least 1). The creating coordinator's `X-User-ID` is captured on the order as `coordinator_id`. The order opens in `DRAFT` with `requires_finance_review` initially false.

Submitting the order advances it from `DRAFT` to `SUBMITTED` and is where pricing is projected. Submission requires that the `lines` be non-empty, that the `headcount` not exceed the venue's `capacity` (otherwise `ERR_VENUE_CAPACITY_EXCEEDED`), and that the event window not overlap any other non-terminal order on the same venue over the half-open interval from `event_start` up to `event_end` (otherwise `ERR_VENUE_TIME_CONFLICT`). On submit, two figures are computed. The `estimated_cost_cents` is a forward-looking recipe projection: the sum over the lines of the menu item's `standard_recipe_cost_cents` times `qty`, multiplied by an event overhead factor of 1.20, rounded half up to whole cents. The client charge is computed with a volume discount driven by headcount — 15 percent when `headcount` is at least 100, otherwise 10 percent when it is at least 50, otherwise 5 percent when it is at least 20, otherwise none. The rounding order here is pinned: for each line, the `line_charge` is the menu item's `price_cents` times `qty` times one minus the discount fraction, rounded half up to whole cents; the `order_charge_cents` is the sum of those per-line charges (rounding each line first, then summing). The `service_fee_cents` is the order charge multiplied by a service-fee rate of 18 percent, rounded half up. The `total_charge_cents` is the order charge plus the service fee.

Review is performed by a `CateringApprover` and enforces **segregation of duties**: the approver's `X-User-ID` must not equal the order's `coordinator_id`, or the review is rejected with `ERR_SEGREGATION_OF_DUTIES`. The approver supplies a `decision`. A `decision` of `APPROVE` advances the order from `SUBMITTED` to `APPROVED`; a `decision` of `REQUEST_REVISION` moves it from `SUBMITTED` to `REVISION_REQUESTED`. Both branches enforce the same segregation-of-duties precondition. From `REVISION_REQUESTED`, the coordinator may revise the order, pulling it back from `REVISION_REQUESTED` to `DRAFT`, where `lines` and `headcount` become editable again and pricing is recomputed on the next submit; the cycle `REVISION_REQUESTED → DRAFT → SUBMITTED` re-enters review. Recall from §3.4 that while an order is `SUBMITTED`, a session close that pushes the site `OVER_TARGET` will stamp `requires_finance_review` true on it.

Confirmation is performed by a `FinanceController` and advances the order from `APPROVED` to `CONFIRMED`, reserving inventory from the shared site pool. The confirm request carries `expected_client_site_version` and `reserved_ingredients` (a list of `{ ingredient, qty }` lines). Confirmation requires, in order, that the site be `ACTIVE` (otherwise `ERR_SITE_SUSPENDED`), that `expected_client_site_version` equal the site's current `version` (otherwise `ERR_STALE_SITE_VERSION`, HTTP 412, as described in §2.7), and that for each reserved line the available quantity — the sum over the site's `AVAILABLE` lots of that ingredient of `qty_on_hand` minus `qty_reserved` — be at least the requested `qty` (otherwise `ERR_INSUFFICIENT_INVENTORY`). On success the system reserves inventory by raising `qty_reserved` on lots in FIFO order (earliest `received_at`, ties by earliest `created_at`), records the per-lot reservation against this order, and increments the site's `version` by 1.

Fulfillment is performed by a cafeteria manager and advances the order from `CONFIRMED` to `FULFILLED`. The fulfill request carries `consumed_ingredients` (`{ ingredient, qty }` lines), which must fit the reserved-plus-available inventory, or fulfillment is rejected with `ERR_INSUFFICIENT_INVENTORY`. On success the order's reservations are released (each lot's `qty_reserved` is lowered by the amount this order held), the `final_cost_cents` is computed by FIFO valuation of the consumed lots — identical arithmetic to a session close, and the value that replaces the earlier estimate — consumed lots have `qty_on_hand` decremented and become `DEPLETED` at 0, the site's `period_food_cost_cents` increases by the final cost, `inventory_value_cents` is recomputed, and the site's `version` is incremented by 1. The `final_cost_cents` is null until fulfillment.

Invoicing is performed by a finance controller and advances the order from `FULFILLED` to the terminal `INVOICED` state, recognizing revenue: the site's `period_revenue_cents` increases by the order's `total_charge_cents`, and `food_cost_pct` and `cost_status` are recomputed. An order may also be cancelled to the terminal `CANCELLED` state: a coordinator may cancel from `DRAFT` or `SUBMITTED`; a finance controller may cancel from `APPROVED` or from `CONFIRMED`. When a `CONFIRMED` order is cancelled, its reservations are released (each lot's `qty_reserved` lowered by the amount this order held) and the site's `version` is incremented by 1; cancelling from the pre-reservation states releases nothing and does not bump the version.

### 3.7. Vendor Invoice Matching and Settlement

Vendor invoices are handled entirely by a `FinanceController`. An invoice is recorded against a `vendor_id` and the `purchase_order_id` it bills, with the vendor's billed `invoiced_amount_cents` (at least 0), and opens in `RECEIVED`. Matching advances it from `RECEIVED` to `MATCHED` and requires that the referenced purchase order be in the `RECEIVED` state (otherwise `ERR_PO_NOT_RECEIVED`); matching computes the signed `matched_variance_cents` as the invoiced amount minus the purchase order's `total_cents`.

Resolution acts on a `MATCHED` invoice and takes a `resolution`. A `resolution` of `APPROVE` advances the invoice from `MATCHED` to `APPROVED`, but only when the absolute value of `matched_variance_cents` is within the match tolerance of 500 cents; a larger absolute variance is rejected with `ERR_VARIANCE_TOO_LARGE`. A `resolution` of `DISPUTE` moves the invoice from `MATCHED` to `DISPUTED` with no tolerance check. A disputed invoice may be resubmitted, moving it from `DISPUTED` back to `RECEIVED` with a corrected `invoiced_amount_cents` supplied in the request; on resubmit the stored amount is replaced and `matched_variance_cents` is cleared, so the cycle `MATCHED → DISPUTED → RECEIVED → MATCHED` can re-run the match. An `APPROVED` invoice is finally paid, advancing it from `APPROVED` to the terminal `PAID` state.

### 3.8. Satisfaction Feedback

A `Diner` may submit a satisfaction survey, which is a polymorphic record that targets either a cafeteria session or a catering event. It names the `client_site_id`, an integer `rating` from 1 to 5 inclusive, and an optional free-text `comment` (defaulting to empty). Exactly one target reference is populated: `service_session_id` is set when the survey concerns a service session, and `catering_order_id` is set when it concerns a catering order; the other is left null. Each survey is an immutable record carrying only `id` and `created_at` — no `version`. Submitting a survey recomputes the site's `satisfaction_avg` as the mean of all ratings on that site's surveys, to two decimal places with round half up (null when the site has none).

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Creating a new resource returns HTTP 201; state transitions and other modifications return HTTP 200; reads return HTTP 200. Request bodies, response bodies, and side effects for each endpoint are described in the §3 workflow narratives above; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | SiteAdmin |
| POST | `/api/client-sites` | Create a client site | SiteAdmin |
| GET | `/api/client-sites/{id}` | Get a client site | SiteAdmin, CafeteriaManager, CateringCoordinator, CateringApprover, FinanceController, Diner |
| GET | `/api/client-sites` | List client sites | SiteAdmin, FinanceController |
| POST | `/api/client-sites/{id}/suspend` | Suspend a site | SiteAdmin |
| POST | `/api/client-sites/{id}/reactivate` | Reactivate a site | SiteAdmin |
| POST | `/api/employees` | Register an employee | SiteAdmin |
| GET | `/api/employees/{id}` | Get an employee | SiteAdmin, CafeteriaManager, Diner |
| GET | `/api/employees` | List employees | SiteAdmin, CafeteriaManager |
| POST | `/api/employees/{id}/terminate` | Terminate an employee | SiteAdmin |
| POST | `/api/menu-cycles` | Create a menu cycle | CafeteriaManager |
| GET | `/api/menu-cycles/{id}` | Get a menu cycle | CafeteriaManager, CateringCoordinator, Diner |
| GET | `/api/menu-cycles` | List menu cycles | CafeteriaManager, CateringCoordinator |
| POST | `/api/menu-cycles/{id}/publish` | Publish a menu cycle | CafeteriaManager |
| POST | `/api/menu-items` | Add a menu item | CafeteriaManager |
| GET | `/api/menu-items/{id}` | Get a menu item | CafeteriaManager, CateringCoordinator, Diner |
| GET | `/api/menu-items` | List menu items | CafeteriaManager, CateringCoordinator, Diner |
| POST | `/api/catering-venues` | Create a venue | SiteAdmin |
| GET | `/api/catering-venues/{id}` | Get a venue | SiteAdmin, CateringCoordinator, CateringApprover, FinanceController |
| GET | `/api/catering-venues` | List venues | SiteAdmin, CateringCoordinator |
| POST | `/api/service-sessions` | Plan a service session | CafeteriaManager |
| GET | `/api/service-sessions/{id}` | Get a service session | CafeteriaManager, FinanceController, Diner |
| GET | `/api/service-sessions` | List service sessions | CafeteriaManager, FinanceController |
| POST | `/api/service-sessions/{id}/lock-forecast` | Lock the forecast headcount | CafeteriaManager |
| POST | `/api/service-sessions/{id}/open` | Open service | CafeteriaManager |
| POST | `/api/service-sessions/{id}/close` | Close service; finalize food cost | CafeteriaManager |
| POST | `/api/service-sessions/{id}/cancel` | Cancel a session | CafeteriaManager |
| POST | `/api/badge-transactions` | Record a POS purchase | Diner |
| GET | `/api/badge-transactions/{id}` | Get a POS transaction | Diner, CafeteriaManager, FinanceController |
| GET | `/api/badge-transactions` | List POS transactions | CafeteriaManager, FinanceController |
| POST | `/api/badge-transactions/{id}/void` | Void a POS transaction | CafeteriaManager |
| POST | `/api/vendors` | Create a vendor | SiteAdmin |
| GET | `/api/vendors/{id}` | Get a vendor | SiteAdmin, CafeteriaManager, FinanceController |
| GET | `/api/vendors` | List vendors | SiteAdmin, CafeteriaManager, FinanceController |
| POST | `/api/purchase-orders` | Create a purchase order | CafeteriaManager |
| GET | `/api/purchase-orders/{id}` | Get a purchase order | CafeteriaManager, FinanceController |
| GET | `/api/purchase-orders` | List purchase orders | CafeteriaManager, FinanceController |
| POST | `/api/purchase-orders/{id}/issue` | Issue a purchase order | CafeteriaManager |
| POST | `/api/purchase-orders/{id}/receive` | Receive a PO; create inventory lots | CafeteriaManager |
| POST | `/api/purchase-orders/{id}/cancel` | Cancel a purchase order | CafeteriaManager |
| GET | `/api/inventory-lots/{id}` | Get an inventory lot | CafeteriaManager, FinanceController |
| GET | `/api/inventory-lots` | List inventory lots | CafeteriaManager, FinanceController |
| POST | `/api/waste-events` | Log a waste event | CafeteriaManager |
| GET | `/api/waste-events/{id}` | Get a waste event | CafeteriaManager, FinanceController |
| GET | `/api/waste-events` | List waste events | CafeteriaManager, FinanceController |
| POST | `/api/catering-orders` | Create a catering order | CateringCoordinator |
| GET | `/api/catering-orders/{id}` | Get a catering order | CateringCoordinator, CateringApprover, FinanceController, CafeteriaManager |
| GET | `/api/catering-orders` | List catering orders | CateringCoordinator, CateringApprover, FinanceController, CafeteriaManager |
| POST | `/api/catering-orders/{id}/submit` | Submit for review; compute pricing | CateringCoordinator |
| POST | `/api/catering-orders/{id}/review` | Approver decision | CateringApprover |
| POST | `/api/catering-orders/{id}/revise` | Pull a revision-requested order to draft | CateringCoordinator |
| POST | `/api/catering-orders/{id}/confirm` | Confirm; reserve inventory (OCC) | FinanceController |
| POST | `/api/catering-orders/{id}/fulfill` | Fulfill; finalize final cost | CafeteriaManager |
| POST | `/api/catering-orders/{id}/invoice` | Invoice; recognize revenue | FinanceController |
| POST | `/api/catering-orders/{id}/cancel` | Cancel a catering order | CateringCoordinator, FinanceController |
| POST | `/api/vendor-invoices` | Record a vendor invoice | FinanceController |
| GET | `/api/vendor-invoices/{id}` | Get a vendor invoice | FinanceController, CafeteriaManager |
| GET | `/api/vendor-invoices` | List vendor invoices | FinanceController, CafeteriaManager |
| POST | `/api/vendor-invoices/{id}/match` | Three-way match against the PO | FinanceController |
| POST | `/api/vendor-invoices/{id}/resolve` | Approve or dispute a matched invoice | FinanceController |
| POST | `/api/vendor-invoices/{id}/resubmit` | Resubmit a disputed invoice | FinanceController |
| POST | `/api/vendor-invoices/{id}/pay` | Pay an approved invoice | FinanceController |
| POST | `/api/satisfaction-surveys` | Submit a satisfaction survey | Diner |
| GET | `/api/satisfaction-surveys/{id}` | Get a survey | Diner, CafeteriaManager, FinanceController |
| GET | `/api/satisfaction-surveys` | List surveys | CafeteriaManager, FinanceController |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ALLERGEN_CONFLICT | 422 |
| ERR_EMPLOYEE_INACTIVE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_VENUE_TIME_CONFLICT | 409 |
| ERR_SESSION_BUFFER_CONFLICT | 409 |
| ERR_DUPLICATE_SESSION_SLOT | 409 |
| ERR_DUPLICATE_BADGE | 409 |
| ERR_VENUE_CAPACITY_EXCEEDED | 409 |
| ERR_MENU_CYCLE_NOT_PUBLISHED | 409 |
| ERR_EMPTY_MENU_CYCLE | 409 |
| ERR_INSUFFICIENT_INVENTORY | 409 |
| ERR_WALLET_INSUFFICIENT | 409 |
| ERR_VARIANCE_TOO_LARGE | 409 |
| ERR_PO_NOT_RECEIVED | 409 |
| ERR_SITE_SUSPENDED | 409 |
| ERR_SESSION_HAS_SALES | 409 |
| ERR_SESSION_NOT_OPEN | 409 |
| ERR_STALE_SITE_VERSION | 412 |
