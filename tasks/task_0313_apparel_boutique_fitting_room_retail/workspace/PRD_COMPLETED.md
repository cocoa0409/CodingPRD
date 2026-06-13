# Apparel Boutique & Fitting-Room Retail API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Apparel Boutique & Fitting-Room Retail API, a back-office platform that runs a single specialty-apparel boutique from the stockroom to the sales floor. The system organizes merchandise as a size-by-color matrix beneath each style, tracks every physical unit through fitting-room holds, styling appointments, sales, returns, exchanges, and ship-from-store special orders, and keeps a finite inventory honest as it is reserved, committed, and released across all of those flows.

Three forces make the domain demanding, and the platform exists to reconcile them. First, inventory is scarce and must never be over-promised: the same physical unit cannot be simultaneously held in a fitting room, sold, and reserved for a remote shipment, so every reservation, sale, and release threads through one conservation invariant. Second, pricing is layered: a style carries a full list price that seasonal markdowns and deeper clearance markdowns reduce, sometimes stacking on one another, and the boutique must be able to preview a markdown before it goes live and then re-price the floor when it activates. Third, the boutique rewards repeat customers with loyalty points, tier-based discounts, and a redeemable store-credit wallet, all of which must stay conserved across captures, refunds, returns, and the occasional voided refund.

The API serves four operational roles — shoppers, floor associates, merchandisers, and store managers — each with a distinct slice of authority, and it runs on a deterministic store clock so that fitting-room expirations, markdown effective dates, and return windows are all reproducible. The sections below define the global contract (authentication, response envelope, pagination, consistency, and money handling) and then walk the business workflows in narrative form.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which they are acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `StoreAssociate`, `Merchandiser`, and `StoreManager`. When an authenticated principal attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The four roles divide responsibility along business lines. A `Customer` is a shopper acting on their own fitting-room holds, styling appointments, returns, and special orders. A `StoreAssociate` is floor staff who run holds, sales, captures, returns intake, special-order fulfillment, and appointment confirmation and completion. A `Merchandiser` owns the product catalog: styles, SKU variants, restocks, markdown schedules, and lookbooks. A `StoreManager` is the operational override and administrative surface: boutique setup, the store clock, store-credit grants, return rejection and voiding, and the stylist roster.

Identity binds to entities differently per role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare that resource's `customer_id` to `X-User-ID`. Concretely, a shopper may only create or act on a fitting-room hold, styling appointment, return, or special order whose `customer_id` is their own `id`, and a violation is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `StoreAssociate`, `Merchandiser`, or `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authentication and audit but does not compare it to any entity's `id`, and these three roles are not subject to per-resource ownership checks.

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

Endpoints that return collections are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range of 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_LIMIT` (HTTP 400).

Unless an endpoint states otherwise, list results are sorted by the resource's `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Store Clock

Every persisted resource carries a server-minted `id` formatted as a UUID, with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system are mutable audit-bearing resources, so each also carries an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every change to the resource) and an integer `version` that begins at its initial value and increments by one on every mutation. The `version` field underpins optimistic concurrency control described in §2.7.

The boutique runs on a deterministic logical clock rather than wall-clock time. Each `Boutique` carries a `current_business_date`, an integer day index that begins at 0 and only advances when an administrator drives the test clock. To advance the clock, an administrator names the `boutique_id`, supplies a `to_business_date` that becomes the boutique's new `current_business_date`, and may supply an optional `to_minute` setting the intraday minute-of-day position used when sweeping fitting-room holds. Many time-sensitive rules — fitting-room expiry, markdown effective dates, and return windows — are evaluated against this day index and, for intraday operations, against the minute-of-day position the clock carries. Because the clock is explicit, the same sequence of requests always produces the same expirations and window outcomes.

### 2.5. Inventory Conservation Across Reservations

The heart of the system is a strict inventory conservation invariant maintained on every `SkuVariant`, the leaf of the size-by-color matrix under a `Style`. Each variant tracks three integer counters: `on_hand`, the physical units present in the store; `reserved`, the units currently spoken for but not yet sold; and `available`, the units free to sell. The platform holds `available` equal to `on_hand` minus `reserved` at all times, and `available` is never negative. A variant also carries a `status` of either `STOCKED`, meaning it is sellable, or `DISCONTINUED`, which blocks any new reservation against it.

Reservations accrue from two sources: an `ACTIVE` or `EXTENDED` fitting-room hold reserves one unit of its variant, and a `PLACED` or `SOURCED` special order reserves its full quantity on the source variant. Whenever `reserved` or `on_hand` changes, the system recomputes `available` on the variant and then bubbles the change upward to recompute the parent `Style`'s `total_available`, which is the sum of `available` across that style's variants. This propagation from variant to style happens on every inventory-moving operation described in §3, so a reader can always treat `total_available` as a derived roll-up that never drifts from its variants.

### 2.6. Pricing, Loyalty, and Monetary Precision

All monetary amounts in this system are stored and returned as integer cents — `list_price_cents`, `current_price_cents`, `total_cents`, `store_credit_cents`, and every other `_cents` field is a whole-number count of cents, never a decimal dollar figure. Where a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent: ties round away from zero to the larger magnitude. Percentages used in pricing are whole percents, and tax rates are expressed in basis points (hundredths of a percent), so a `tax_rate_bps` of 875 denotes an 8.75% rate. No computed price is ever allowed to fall below a floor of one dollar, i.e. 100 cents.

The boutique operates a loyalty program with three tiers — `STANDARD`, `SILVER`, and `GOLD` — and a redeemable store-credit wallet. A customer's tier is a function of cumulative net captured spend, tier discounts are applied at order pricing, and loyalty points are minted from net cash actually paid. The precise thresholds, discount rates, point divisor, and the projected-versus-actual distinction for both pricing and tiering are spelled out within the workflow narratives in §3, where they belong to the operations that drive them.

### 2.7. Optimistic Concurrency on Markdown Creation

Creating a markdown schedule is the one write in this system guarded by optimistic concurrency control, because a new schedule legitimately supersedes any prior draft or scheduled markdown on the same style, and two creates that each believe they start from the same style snapshot must not both proceed. A create-markdown-schedule request must therefore carry an `expected_style_version` field whose value is the client's last observed `version` of the target `Style`. If that value does not match the style's current `version` — because another writer advanced the style since the client read it — the create is rejected with `ERR_STALE_STYLE_VERSION` (HTTP 412), preventing the client from superseding a schedule it never observed. This `expected_style_version` field is mandatory on the create-markdown-schedule call and appears on no other endpoint; no other write in the system takes a version field.

### 2.8. Cascade Consistency and Validation Ordering

Many operations touch more than one entity, and the system applies all of an operation's side effects as one consistent unit. A markdown activation re-prices a style and then cascades that new price onto dependent fitting-room holds and recomputes affected lookbook feature counts; a return approval restocks a variant, rolls the change up to the parent style, and adjusts the customer's wallet, points, and tier; a hold conversion moves a reservation from the fitting room onto a sale. Each of these cascades is described with its triggering workflow in §3, and every entity a cascade mutates has its `updated_at` refreshed and its `version` incremented as part of that mutation.

When a request targets a nested resource, the system validates path and body identifiers left to right and rejects the first one that does not resolve to an existing entity with `ERR_NOT_FOUND` (HTTP 404). More broadly, every write is screened through an ordered gauntlet of checks, and the order matters because it determines which error a caller sees first. Authentication is checked before anything else (`ERR_UNAUTHENTICATED`, HTTP 401); then role authorization (`ERR_FORBIDDEN_ROLE`, HTTP 403); then existence of every referenced id (`ERR_NOT_FOUND`, HTTP 404); then, for customer-owned mutations, resource ownership (`ERR_NOT_RESOURCE_OWNER`, HTTP 403); then request well-formedness — required fields present, enum values in range, every `qty` at least 1, every minute field at least 0 and below 1440, and every `end_minute` strictly greater than its `start_minute` (`ERR_INVALID_REQUEST`, HTTP 400); and then the state check that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409). Domain-specific business rules are evaluated after this common prefix, in the per-workflow orderings given in §3.

## 3. Business Logic & Workflows

### 3.1. Catalog Foundations: Boutiques, Styles, and the Size-by-Color Matrix

A `StoreManager` stands up a boutique by supplying a display `name`, a two-letter uppercase `state_code` that selects the local sales-tax rate, and a `tax_rate_bps` between 0 and 2000 inclusive that expresses that rate in basis points; the manager may optionally supply `return_window_days`, which defaults to 30 and must be at least 0 and governs how long a completed order stays returnable. A new boutique begins with its `current_business_date` initialized to 0 and a `store_credit_outstanding_cents` of 0; the latter is a derived figure equal to the sum of `store_credit_cents` across all of that boutique's customers and serves as the conservation anchor for the store-credit ledger.

A `Merchandiser` populates the catalog. Creating a style requires the owning `boutique_id`, a `style_code` that must be unique within that boutique, a display `name`, a `category` drawn from `TOPS`, `BOTTOMS`, `DRESSES`, `OUTERWEAR`, or `ACCESSORIES`, a `season` drawn from `SPRING`, `SUMMER`, `FALL`, or `WINTER`, and a `list_price_cents` greater than 0. A new style starts with its `current_price_cents` equal to `list_price_cents`, its `clearance` flag false, and its `total_available` at 0. If the `style_code` already exists in the boutique, the create is rejected with `ERR_DUPLICATE_KEY` (HTTP 409).

Beneath a style, the merchandiser builds the size-by-color matrix by adding SKU variants. Each variant is created against its parent style with a `size` from `XS`, `S`, `M`, `L`, or `XL`, a free-text `color`, and an initial `on_hand` count that must be at least 0; on creation its `available` is set equal to `on_hand`, its `reserved` is 0, and the parent style's `total_available` is bubbled up to include the new units. Each variant exposes its parent linkage through `style_id`. A variant's `status` defaults to `STOCKED`. To replenish stock, the merchandiser restocks a variant by supplying a count of `units` (which must be at least 1), which increases both `on_hand` and `available` by that amount and bubbles the increase up to the style's `total_available`. The catalog is browsable by all roles, including listing the variants under a given style and filtering styles by `boutique_id`, `season`, or `category`.

### 3.2. Customers, the Store-Credit Wallet, and Loyalty Tiers

A `StoreManager` or `StoreAssociate` registers a customer under a boutique by supplying `boutique_id`, `full_name`, and `email`; the email must be unique within the boutique, and a collision is rejected with `ERR_DUPLICATE_KEY` (HTTP 409). A fresh customer is created `ACTIVE` with `store_credit_cents` of 0, `loyalty_points` of 0, `captured_spend_cents` of 0, and a `loyalty_tier` of `STANDARD`. The `status` field carries either `ACTIVE` or `SUSPENDED`; an order may only be authorized for an `ACTIVE` customer. The wallet balance in `store_credit_cents` is never negative.

A customer's tier is derived from `captured_spend_cents`, the cumulative net captured spend (lifetime captures minus refunds). The actual tier is evaluated by threshold: a customer reaches `GOLD` once their captured spend is at least 1,500 dollars (150,000 cents), and reaches `SILVER` once it is at least 500 dollars (50,000 cents) but below the gold threshold; otherwise they remain `STANDARD`. These comparisons are boundary-exact: a customer whose captured spend equals exactly the gold threshold is `GOLD`, and one at exactly the silver threshold is `SILVER`. This actual tier is the value stored on `loyalty_tier`, and it is recomputed by the capture and refund side effects described later.

The boutique also exposes a forward-looking tier projection. A projection read returns three values — `actual_tier`, `projected_tier`, and `projected_basis_cents` — where the actual tier is the stored tier just described, and the projected tier is computed against a `projected_basis_cents` equal to `captured_spend_cents` plus the sum of `total_cents` over every sales order of that customer currently in `AUTHORIZED` payment status (authorized but not yet captured). The same two thresholds applied to that larger basis can yield a higher tier than the actual one, letting a shopper see the tier they are about to earn. The `loyalty_points` field is the customer's lifetime points net of reversals and is described where it is minted, in §3.6. Separately, a `StoreManager` may grant store credit directly as a goodwill adjustment by supplying an `amount_cents` that must be at least 0; the grant increases the customer's `store_credit_cents` and refreshes the boutique's `store_credit_outstanding_cents`. A store-credit grant creates no new stand-alone resource but returns the updated customer with HTTP 201.

### 3.3. Fitting-Room Holds: Reserving a Unit Off the Floor

Fitting rooms are created by a `StoreManager` or `StoreAssociate` against a `boutique_id` with a `label` such as "Room 3"; a room's `status` is `OPEN` to accept holds or `CLOSED` to block new ones. A fitting-room hold reserves a single physical unit off the sales floor for a shopper to try on. Creating a hold requires the `fitting_room_id`, the `customer_id`, the `sku_variant_id` of the unit to reserve, and a half-open time interval given as `start_minute` and `end_minute`, each a minute-of-day position interpreted within the boutique's `current_business_date`; `start_minute` is at least 0 and below 1440, and `end_minute` is greater than `start_minute` and at most 1440. A shopper acting as `Customer` may only create a hold under their own `customer_id`.

Two business checks guard hold creation, evaluated in this order after the common prefix. First, the requested interval must not overlap any other non-terminal hold on the same fitting room; intervals are half-open `[start_minute, end_minute)`, so a hold ending exactly when another begins is back-to-back and permitted, but any true overlap is rejected with `ERR_ROOM_DOUBLE_BOOKED` (HTTP 409). Second, the variant must be reservable: its `available` must be at least the one unit requested and its `status` must be `STOCKED`, otherwise the create is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409). On success the hold begins in `ACTIVE` status, the variant's `reserved` is incremented by one with `available` recomputed and `total_available` bubbled up to the style, and the hold snapshots the style's `current_price_cents` into its own `held_price_cents`. The hold's `sales_order_id` is null until it is converted.

A hold moves through a small lifecycle. Extending a hold (`ACTIVE → EXTENDED`) takes a new `end_minute` and lengthens the interval; the same half-open room-overlap check applies and yields `ERR_ROOM_DOUBLE_BOOKED` on collision, while the reservation simply persists with no inventory change. Releasing a hold (from `ACTIVE` or `EXTENDED` to `RELEASED`) frees the reservation by decrementing the variant's `reserved` by one, recomputing `available`, and bubbling `total_available` up to the style — a compensating action that returns the unit to the floor. Converting a hold (`ACTIVE → CONVERTED` or `EXTENDED → CONVERTED`) requires a `sales_order_id` naming a sales order that already contains an order line for this hold's `sku_variant_id`; conversion sets the hold's `sales_order_id`, and the reservation transfers to the sale — `reserved` is decremented and `available` recomputed here, with the corresponding `on_hand` decrement deferred to order capture — and `total_available` is bubbled up. A `StoreAssociate` performs conversions; holds may be created, extended, and released by either a `StoreAssociate` or the owning `Customer`. Holds can be listed for a room and filtered by `customer_id`, `sku_variant_id`, or `sales_order_id`.

When the store clock advances past a hold's interval, the system sweeps it. Any hold still in `ACTIVE` or `EXTENDED` whose `end_minute` is at or before the boutique's current minute at the sweep, or whose business day has been left behind by an advancing `current_business_date`, transitions to `EXPIRED`; the intraday minute comparison is applied only when the clock advance supplied a `to_minute`, so when `to_minute` is omitted a hold expires solely on the day-advance condition (its business day left behind) and a hold still on the new current business day is never swept by minute. Expiry frees its reservation exactly as a release does — decrement the variant's `reserved` by one, recompute `available`, and bubble `total_available` up to the style. `CONVERTED`, `EXPIRED`, and `RELEASED` are the terminal hold states.

### 3.4. Styling Appointments and Stylist Scheduling

A `StoreManager` creates a stylist against a `boutique_id` with a `full_name` and an optional `buffer_minutes`, the mandatory cleanup gap required between two appointments on that stylist; `buffer_minutes` defaults to 15 and must be at least 0. A stylist's `status` is `ACTIVE` to accept appointments or `OFF` to block new confirmations, and a manager flips it by setting `status` directly. A styling appointment is requested by a `StoreAssociate` or the owning `Customer` against a `stylist_id` and `customer_id` with a `start_minute` and `end_minute` interpreted as minutes-of-day within the current business date, subject to the same range rules as holds (`start_minute` at least 0 and below 1440, `end_minute` greater than `start_minute` and at most 1440). A new appointment begins in `REQUESTED` status.

Confirming an appointment (`REQUESTED → CONFIRMED`) is a `StoreAssociate` action guarded by two checks evaluated in this order. First, the stylist must be `ACTIVE`; if the stylist's `status` is `OFF`, confirmation is rejected with `ERR_STYLIST_NOT_ACTIVE` (HTTP 409). Second, the appointment must not collide with another already-`CONFIRMED` appointment on the same stylist when the stylist's `buffer_minutes` is taken into account; this overlap test is closed-buffer, meaning the cleanup gap is enforced on both sides of an existing appointment, and a collision is rejected with `ERR_STYLIST_DOUBLE_BOOKED` (HTTP 409). The stylist-active check is evaluated before the double-booking check, so a confirmation attempt against an off-duty stylist surfaces the not-active error rather than a scheduling conflict. A confirmed appointment can be completed by a `StoreAssociate` (`CONFIRMED → COMPLETED`) or marked a no-show by a `StoreAssociate` (`CONFIRMED → NO_SHOW`), the latter simply releasing the slot with no penalty in this version. Cancellation is a `Customer` action available from either `REQUESTED` or `CONFIRMED` (to `CANCELLED`), releasing the stylist slot. `COMPLETED`, `NO_SHOW`, and `CANCELLED` are terminal. Appointments can be listed per stylist and filtered by `customer_id`.

### 3.5. Seasonal Markdowns and Clearance Pricing

Markdown schedules let a `Merchandiser` reduce a style's price on a planned date and are the system's dual-variant pricing engine. A schedule is created against a `style_id` with a `phase` of either `SEASONAL` (a percent-off markdown) or `CLEARANCE` (a deeper terminal markdown that stacks), a `markdown_pct` between 1 and 90 inclusive expressing whole percent off, an `effective_date` day index of at least 0 on or after which the schedule may activate, and the `expected_style_version` required by the optimistic-concurrency rule of §2.7. Creation places the schedule in `DRAFT` status and supersedes any prior `DRAFT` or `SCHEDULED` schedule of the same style — transitioning each such prior schedule to `SUPERSEDED` and clearing its `projected_price_cents` back to null — so that at most one schedule is live per style; the create also increments the style's `version` by one. The schedule's `projected_price_cents` and `applied_price_cents` are both null until computed by the transitions below; `applied_price_cents` is the final price written onto the style at activation.

Scheduling a markdown (`DRAFT → SCHEDULED`) computes its `projected_price_cents`, a provisional forward-looking preview, while un-scheduling it (`SCHEDULED → DRAFT`) clears `projected_price_cents` back to null. Activation (`SCHEDULED → ACTIVE`) is permitted only when the boutique's `current_business_date` has reached or passed the schedule's `effective_date`; an early activation is rejected with `ERR_MARKDOWN_NOT_EFFECTIVE` (HTTP 409). At most one schedule of a style may be `ACTIVE` at a time, so activating a new one first supersedes the prior active schedule. Activation computes the schedule's `applied_price_cents`, writes it onto the style's `current_price_cents`, and — if the phase is `CLEARANCE` — sets the style's `clearance` flag true. Activation then cascades: for every `ACTIVE` or `EXTENDED` fitting-room hold whose variant belongs to this style, the hold's `held_price_cents` is refreshed to the new `current_price_cents`, and every lookbook that contains this style has its `featured_count` recomputed. Ending a markdown (`ACTIVE → ENDED`) restores `current_price_cents` to `list_price_cents`, sets `clearance` back to false, and refreshes the same dependent hold prices and lookbook feature counts. A schedule may also be retired to `SUPERSEDED` by the system when a newer schedule is created against the same style (from `DRAFT` or `SCHEDULED`) or when a newer schedule is activated against the same style (from `ACTIVE`); `ENDED` and `SUPERSEDED` are terminal.

The price arithmetic itself distinguishes the two phases and the two variants. For a `SEASONAL` schedule the price is the style's `list_price_cents` multiplied by the quantity (100 minus `markdown_pct`) divided by 100, rounded half up to whole cents at that single multiplication step. For a `CLEARANCE` schedule the markdown stacks: if the style currently carries a live seasonal reduction — that is, its `current_price_cents` is below its `list_price_cents` — the clearance basis is that already-reduced `current_price_cents`; otherwise the basis is the `list_price_cents` directly. The clearance price is then that basis multiplied by (100 minus `markdown_pct`) divided by 100, again rounded half up at the single multiplication step. In either phase, if the rounded result would fall below 100 cents, it is raised to 100 cents. The provisional variant — `projected_price_cents`, computed at scheduling time — reads the style's `current_price_cents` as it stands at scheduling and does not write the style or re-read the clearance basis later. The final variant — `applied_price_cents`, computed at activation — re-reads the style's `current_price_cents` at activation; consequently, if a `SEASONAL` markdown went `ACTIVE` on the same style between scheduling and activation of a `CLEARANCE` schedule, the clearance basis differs and `applied_price_cents` diverges from the earlier `projected_price_cents` for the same schedule.

### 3.6. Selling: Order Pricing, Capture, and Loyalty Accrual

A sale begins when a `StoreAssociate` opens a sales order for a customer by supplying the `customer_id`; the order starts with `payment_status` of `UNPAID` and `fulfillment_status` of `OPEN`. Payment and fulfillment are two independent state axes on the same order. The associate adds order lines, each supplying a `sku_variant_id` and a `qty` of at least 1; on creation the line snapshots the style's `current_price_cents` into its own `unit_price_cents` and computes `line_total_cents` as `unit_price_cents` times `qty`. A line's `status` starts at `SOLD`. Lines can be listed under an order, fetched individually, and filtered by `sku_variant_id`.

Authorizing an order (`payment_status` `UNPAID → AUTHORIZED`) is permitted only when the order's `fulfillment_status` is `OPEN`, the order has at least one order line, and the customer's `status` is `ACTIVE`. Authorization prices the order but moves no inventory. Pricing follows a pinned rounding order: each line's `line_total_cents` is the exact integer product of its `unit_price_cents` and `qty`, and `subtotal_cents` is the sum of those per-line integers. Authorization also writes a provisional `total_cents` equal to `subtotal_cents` minus `loyalty_discount_cents` plus `tax_cents` (no store credit is applied at this stage, so this provisional total is the value the tier projection of §3.2 sums over `AUTHORIZED` orders); capture later overwrites `total_cents` with the finalized total defined below. The loyalty discount is then computed once over the summed subtotal — never per line — using a discount rate keyed on the customer's tier read at authorization time, before this order is captured: `STANDARD` earns no discount, `SILVER` earns 5% (500 basis points), and `GOLD` earns 10% (1000 basis points). Concretely, `loyalty_discount_cents` is `subtotal_cents` multiplied by the tier's basis-point rate divided by 10,000, rounded half up to whole cents. Tax is then computed once over the discounted subtotal: `tax_cents` is the quantity (`subtotal_cents` minus `loyalty_discount_cents`) multiplied by the boutique's `tax_rate_bps` divided by 10,000, rounded half up to whole cents.

Capturing an order (`payment_status` `AUTHORIZED → CAPTURED`) settles cash, moves inventory, and mints loyalty. Capture is permitted only from `AUTHORIZED`; before it proceeds, two business checks run in a fixed order. First, inventory is re-checked: every order line's variant must have `available` at least that line's `qty`, or capture is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409). Second, the optional `redeem_store_credit` amount the caller supplies must not exceed the customer's current `store_credit_cents`, or capture is rejected with `ERR_INSUFFICIENT_STORE_CREDIT` (HTTP 422); the inventory check is evaluated before the store-credit check. On success, the store credit actually applied, `store_credit_applied_cents`, is the smaller of the requested `redeem_store_credit` and the order's (`subtotal_cents` minus `loyalty_discount_cents` plus `tax_cents`), and the order's `total_cents` is finalized as `subtotal_cents` minus `loyalty_discount_cents` plus `tax_cents` minus `store_credit_applied_cents`. The customer's `store_credit_cents` is decremented by `store_credit_applied_cents`. For each order line the variant's `on_hand` is decremented by `qty`, `available` is recomputed, and `total_available` is bubbled up to the style.

Capture also accrues loyalty, and the accrual is deliberately ordered to break an apparent circular dependency: points depend on net cash paid, which depends on store credit applied, which depends on the total — so the total is finalized first, and only then are points minted. The accrual basis is the net cash actually paid, namely the finalized `total_cents`; store-credit-funded cents earn nothing. The order's `points_earned` is the net-cash total divided by 100 and taken as the floor (the whole number of points, discarding any remainder), since one point is earned per 100 cents of net cash. Capture increments the customer's `loyalty_points` by `points_earned`, adds the captured net spend to `captured_spend_cents`, and recomputes the actual `loyalty_tier` from the new captured spend.

Completing an order (`fulfillment_status` `OPEN → COMPLETED`) is permitted only once `payment_status` is `CAPTURED`; completion makes the order return-eligible and stamps `return_anchor_date` with the boutique's `current_business_date` at that moment, which is the start of the return window. Cancelling an order (`fulfillment_status` `OPEN → CANCELLED`) is permitted only while `payment_status` is `UNPAID` or `AUTHORIZED`; since capture was never reached, no inventory was decremented and the order is simply voided. Cancellation is forbidden once the order is `CAPTURED` — the from-state guard makes such an attempt an `ERR_INVALID_STATE` (HTTP 409). `REFUNDED` is the terminal payment state and `CANCELLED` the terminal fulfillment state.

### 3.7. Returns, Exchanges, and Refund Compensation

A return is filed by a `StoreAssociate` or the owning `Customer` against a sales order by naming the `sales_order_id`, the `order_line_id` of the line being returned, and a `resolution` of either `REFUND` or `EXCHANGE`; when the resolution is `EXCHANGE`, an `exchange_sku_variant_id` naming the replacement variant is required. A new return begins in `REQUESTED` status with `refund_cents` and `points_reversed` at 0. Returns can be listed per order and filtered by `order_line_id` or `exchange_sku_variant_id`.

Approving a return (`REQUESTED → APPROVED`) is a `StoreAssociate` action gated by an ordered sequence of checks, and the order is significant because state is checked before time. The return must still be `REQUESTED`; the underlying order's `fulfillment_status` must be `COMPLETED`, or approval is rejected with `ERR_ORDER_NOT_RETURNABLE_STATE` (HTTP 409); and only then is the window checked — the boutique's `current_business_date` minus the order's completion anchor must be at most the boutique's `return_window_days`, or approval is rejected with `ERR_RETURN_WINDOW_CLOSED` (HTTP 422). For an exchange resolution there is a further requirement, evaluated as its own business check: `exchange_sku_variant_id` must be present and the named variant must have `available` of at least 1, or approval is rejected with `ERR_EXCHANGE_UNAVAILABLE` (HTTP 409).

Approval drives a three-level cascade plus ledger compensation. At the first level the order line's `status` is set — `RETURNED` for a refund or `EXCHANGED` for an exchange. That line-status change, at the second level, increments the line's variant `on_hand` by the line `qty` (the unit is restocked) and recomputes `available`; at the third level the variant's change bubbles up to recompute the parent style's `total_available`. For a `REFUND`, the system grants `refund_cents` equal to the returned line's `line_total_cents` into the customer's `store_credit_cents` and refreshes the boutique's `store_credit_outstanding_cents`. For an `EXCHANGE`, the system instead reserves one unit of the exchange variant, decrementing its `available`. In both resolutions the system reverses the loyalty the line earned: `points_reversed` equals the points minted for that line, prorated as the order's `points_earned` multiplied by the ratio of that line's `line_total_cents` to the order's `subtotal_cents`, rounded half up to a whole number of points; those points are removed from the customer's `loyalty_points` and the line's captured spend is removed from `captured_spend_cents`, after which the actual `loyalty_tier` is recomputed. A customer's net `loyalty_points` is never allowed below 0. Finally, if no order line of the order remains in `SOLD` status after the cascade, the system transitions the order's `payment_status` from `CAPTURED` to `REFUNDED`, reversing any still-outstanding points back to the pre-order baseline and recomputing the tier — the conservation guarantee that points are exactly neutral across a capture followed by a full return.

Rejecting a return (`REQUESTED → REJECTED`) is a `StoreManager` action that makes no inventory or ledger change. Voiding a return (`APPROVED → VOIDED`) is also a `StoreManager` action, permitted only when the return's `resolution` is `REFUND` — only refund returns are voidable in this version — and it fully compensates the approval: the order line's `status` is set back to `SOLD`, the variant's `on_hand` is decremented by `qty` with `available` recomputed and `total_available` bubbled up, the granted `refund_cents` is clawed back from the customer's `store_credit_cents` with `store_credit_outstanding_cents` refreshed, and the previously reversed `points_reversed` are re-minted onto `loyalty_points` and `captured_spend_cents` with the tier recomputed. `REJECTED` and `VOIDED` are terminal return states.

### 3.8. Special Orders: Ship-From-Store Fulfillment

A special order ships a unit from the store to a remote destination. A `StoreAssociate` or the owning `Customer` places one by supplying the `customer_id`, the `source_sku_variant_id` of the unit to ship, a `qty` of at least 1, and a two-letter uppercase `ship_to_state_code` recording the destination nexus jurisdiction. The `ship_to_state_code` is validated as a two-letter uppercase string and stored on the special order, but in this version no destination nexus tax — and indeed no monetary total of any kind — is computed for a special order; the field is purely informational. A placed order begins in `PLACED` status with `reserved_units` at 0, because the reservation does not occur until sourcing.

Sourcing a special order (`PLACED → SOURCED`) is the reservation step: the source variant's `available` must be at least the order's `qty` at sourcing time, or sourcing is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 409); on success the variant's `reserved` is incremented by `qty`, the order's `reserved_units` is set to `qty`, `available` is recomputed, and `total_available` bubbles up to the style. Shipping (`SOURCED → SHIPPED`) commits the units: the source variant's `on_hand` and `reserved` are each decremented by `qty`, the order's `reserved_units` is set to 0, and `available` and `total_available` are recomputed. Delivering (`SHIPPED → DELIVERED`) closes the order. Cancelling a special order (from `PLACED` or `SOURCED` to `CANCELLED`) releases any reservation by decrementing the source variant's `reserved` by the order's current `reserved_units`, setting `reserved_units` to 0, recomputing `available`, and bubbling `total_available` up — a compensating action that keeps inventory conserved. `DELIVERED` and `CANCELLED` are terminal.

### 3.9. Lookbooks: Curated Style Collections

A `Merchandiser` curates a lookbook against a `boutique_id` with a `title`, a `season` from `SPRING`, `SUMMER`, `FALL`, or `WINTER`, and an optional ordered `style_ids` array of the styles to feature; the array defaults to empty. A new lookbook is `DRAFT` and its `featured_count` is computed as the number of its `style_ids` whose style is not on clearance — that is, whose `clearance` flag is false, counting full-price features only. A `DRAFT` lookbook may be edited by patching its `title` or its `style_ids`, which recomputes `featured_count`. Publishing a lookbook (`DRAFT → PUBLISHED`) freezes it. A frozen lookbook cannot be patched or re-published; any such attempt is rejected with `ERR_LOOKBOOK_FROZEN` (HTTP 409). As noted in §3.5, activating or ending a markdown that flips a contained style's `clearance` flag recomputes the `featured_count` of every lookbook that contains that style.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`; the store-credit grant likewise returns `201 Created`, even though it returns the updated customer rather than a new stand-alone resource. Operations that modify an existing resource — including all state-transition actions, restocks, lookbook patches, and the clock advance — return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/boutiques` | Create a boutique | StoreManager |
| GET | `/boutiques/{id}` | Get a boutique | StoreManager, Merchandiser, StoreAssociate |
| GET | `/boutiques` | List boutiques | StoreManager, Merchandiser, StoreAssociate |
| POST | `/_clock/advance` | Advance the store clock and sweep expired holds | StoreManager |
| POST | `/customers` | Register a customer | StoreManager, StoreAssociate |
| GET | `/customers/{id}` | Get a customer | StoreManager, StoreAssociate, Customer |
| GET | `/customers` | List/filter customers | StoreManager, StoreAssociate |
| GET | `/customers/{id}/tier-projection` | Projected loyalty tier including authorized pending orders | StoreManager, StoreAssociate, Customer |
| POST | `/customers/{id}/store-credit-grants` | Grant store credit | StoreManager |
| POST | `/styles` | Create a style | Merchandiser |
| GET | `/styles/{id}` | Get a style | StoreManager, Merchandiser, StoreAssociate, Customer |
| GET | `/styles` | List/filter styles | StoreManager, Merchandiser, StoreAssociate, Customer |
| POST | `/styles/{id}/sku-variants` | Add a size/color variant | Merchandiser |
| GET | `/styles/{id}/sku-variants` | List a style's variants | StoreManager, Merchandiser, StoreAssociate, Customer |
| GET | `/sku-variants/{id}` | Get a SKU variant | StoreManager, Merchandiser, StoreAssociate, Customer |
| POST | `/sku-variants/{id}/restock` | Restock units onto a variant | Merchandiser |
| POST | `/markdown-schedules` | Create a markdown schedule | Merchandiser |
| GET | `/markdown-schedules/{id}` | Get a markdown schedule | StoreManager, Merchandiser |
| GET | `/markdown-schedules` | List/filter markdown schedules | StoreManager, Merchandiser |
| POST | `/markdown-schedules/{id}/schedule` | Move a schedule from draft to scheduled | Merchandiser |
| POST | `/markdown-schedules/{id}/unschedule` | Move a schedule from scheduled back to draft | Merchandiser |
| POST | `/markdown-schedules/{id}/activate` | Activate a schedule and re-price the style | Merchandiser |
| POST | `/markdown-schedules/{id}/end` | End an active schedule and restore list price | Merchandiser |
| POST | `/fitting-rooms` | Create a fitting room | StoreManager, StoreAssociate |
| GET | `/fitting-rooms/{id}` | Get a fitting room | StoreManager, StoreAssociate, Customer |
| GET | `/fitting-rooms` | List fitting rooms | StoreManager, StoreAssociate, Customer |
| POST | `/fitting-room-holds` | Reserve a unit in a room for an interval | StoreAssociate, Customer |
| GET | `/fitting-room-holds/{id}` | Get a hold | StoreManager, StoreAssociate, Customer |
| GET | `/fitting-rooms/{id}/holds` | List holds of a room | StoreManager, StoreAssociate, Customer |
| GET | `/fitting-room-holds` | List/filter holds | StoreManager, StoreAssociate, Customer |
| POST | `/fitting-room-holds/{id}/extend` | Lengthen a hold's interval | StoreAssociate, Customer |
| POST | `/fitting-room-holds/{id}/convert` | Convert a hold to a sale line | StoreAssociate |
| POST | `/fitting-room-holds/{id}/release` | Release a hold and free its reservation | StoreAssociate, Customer |
| POST | `/stylists` | Create a stylist | StoreManager |
| GET | `/stylists/{id}` | Get a stylist | StoreManager, StoreAssociate, Customer |
| GET | `/stylists` | List stylists | StoreManager, StoreAssociate, Customer |
| POST | `/stylists/{id}/status` | Set a stylist active or off | StoreManager |
| POST | `/styling-appointments` | Request a styling appointment | StoreAssociate, Customer |
| GET | `/styling-appointments/{id}` | Get an appointment | StoreManager, StoreAssociate, Customer |
| GET | `/stylists/{id}/appointments` | List a stylist's appointments | StoreManager, StoreAssociate, Customer |
| GET | `/styling-appointments` | List/filter appointments | StoreManager, StoreAssociate, Customer |
| POST | `/styling-appointments/{id}/confirm` | Confirm an appointment | StoreAssociate |
| POST | `/styling-appointments/{id}/cancel` | Cancel an appointment | StoreAssociate, Customer |
| POST | `/styling-appointments/{id}/complete` | Complete a confirmed appointment | StoreAssociate |
| POST | `/styling-appointments/{id}/no-show` | Mark a confirmed appointment a no-show | StoreAssociate |
| POST | `/sales-orders` | Open a sales order | StoreAssociate |
| GET | `/sales-orders/{id}` | Get a sales order | StoreManager, StoreAssociate, Customer |
| GET | `/sales-orders` | List/filter sales orders | StoreManager, StoreAssociate, Customer |
| POST | `/sales-orders/{id}/lines` | Add an order line | StoreAssociate |
| GET | `/sales-orders/{id}/lines` | List an order's lines | StoreManager, StoreAssociate, Customer |
| GET | `/order-lines/{id}` | Get an order line | StoreManager, StoreAssociate, Customer |
| GET | `/order-lines` | List/filter order lines | StoreManager, StoreAssociate, Customer |
| POST | `/sales-orders/{id}/authorize` | Authorize and price an order | StoreAssociate |
| POST | `/sales-orders/{id}/capture` | Capture payment, move inventory, mint points | StoreAssociate |
| POST | `/sales-orders/{id}/complete` | Complete fulfillment and set the return anchor | StoreAssociate |
| POST | `/sales-orders/{id}/cancel` | Cancel an order before capture | StoreAssociate |
| POST | `/returns` | File a return or exchange | StoreAssociate, Customer |
| GET | `/returns/{id}` | Get a return request | StoreManager, StoreAssociate, Customer |
| GET | `/sales-orders/{id}/returns` | List returns for an order | StoreManager, StoreAssociate, Customer |
| GET | `/returns` | List/filter returns | StoreManager, StoreAssociate, Customer |
| POST | `/returns/{id}/approve` | Approve a return with restock and refund/exchange | StoreAssociate |
| POST | `/returns/{id}/reject` | Reject a return | StoreManager |
| POST | `/returns/{id}/void` | Void an approved refund return | StoreManager |
| POST | `/special-orders` | Place a ship-from-store special order | StoreAssociate, Customer |
| GET | `/special-orders/{id}` | Get a special order | StoreManager, StoreAssociate, Customer |
| GET | `/special-orders` | List/filter special orders | StoreManager, StoreAssociate, Customer |
| POST | `/special-orders/{id}/source` | Source and reserve units | StoreAssociate |
| POST | `/special-orders/{id}/ship` | Ship and commit units | StoreAssociate |
| POST | `/special-orders/{id}/deliver` | Mark a special order delivered | StoreAssociate |
| POST | `/special-orders/{id}/cancel` | Cancel a special order and release reservation | StoreAssociate |
| POST | `/lookbooks` | Create a lookbook | Merchandiser |
| GET | `/lookbooks/{id}` | Get a lookbook | StoreManager, Merchandiser, StoreAssociate, Customer |
| GET | `/lookbooks` | List/filter lookbooks | StoreManager, Merchandiser, StoreAssociate, Customer |
| PATCH | `/lookbooks/{id}` | Edit a draft lookbook | Merchandiser |
| POST | `/lookbooks/{id}/publish` | Publish and freeze a lookbook | Merchandiser |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_STYLE_VERSION` | 412 Precondition Failed |
| `ERR_ORDER_NOT_RETURNABLE_STATE` | 409 Conflict |
| `ERR_RETURN_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_STYLIST_NOT_ACTIVE` | 409 Conflict |
| `ERR_STYLIST_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_INSUFFICIENT_STORE_CREDIT` | 422 Unprocessable Entity |
| `ERR_MARKDOWN_NOT_EFFECTIVE` | 409 Conflict |
| `ERR_EXCHANGE_UNAVAILABLE` | 409 Conflict |
| `ERR_LOOKBOOK_FROZEN` | 409 Conflict |
| `ERR_VALIDATION_LIMIT` | 400 Bad Request |
