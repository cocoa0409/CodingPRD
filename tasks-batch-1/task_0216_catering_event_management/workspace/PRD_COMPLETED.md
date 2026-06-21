# Catering Event Management API — Product Requirements Document

## 1. Introduction

Catering an event is, at its heart, a pricing and reconciliation problem dressed up as logistics. A client books a menu package for an expected number of guests, layers on delivery, setup, and staffing add-ons, and then watches the headcount drift as the date approaches. Every drift has a price: a deposit that must be held, a guarantee floor that protects the caterer against last-minute shrinkage, a change fee that scales with how late the swing lands, and a cancellation settlement that splits the held deposit into refunded and forfeited halves. This API exists to make all of that money movement deterministic and auditable.

The system models the full arc of a catering engagement — from a `DRAFT` order through confirmation, guarantee, invoicing, settlement, and final fulfillment, with cancellation possible along the way — while simultaneously tracking an independent settlement dimension that records where the money sits. Underneath the orders sit a catalog of menu packages, venues that carry their own tax and service-fee jurisdictions, and multi-stop service routes whose delivery legs must be dispatched in order against a single vehicle. A negotiation sub-process lets clients and coordinators counter-propose headcount changes, with optimistic-concurrency protection so that a stale quote can never silently overwrite an order that has already moved on.

This document specifies the complete contract: the entities and their fields, the two parallel order state machines, the six calculation rules that price and reconcile every engagement, the priority-ordered validation gauntlet each write must pass, the REST surface, and the error catalogue. It is written for the engineer who will build the service and for the test author who will hold that service to account.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. Where a rule is stated here, it applies uniformly unless a §3 workflow narrows it.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to invoke the targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles: `CateringAdmin`, `Client`, `SalesCoordinator`, and `EventCaptain`.

- When `X-User-Role` is `CateringAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The admin owns the operator surface — the package, venue, and route catalog, client registration, the test-driving clock, and the staffing-pool capacity control — and the server does not compare its `X-User-ID` to any entity's `id`.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` entity. Ownership checks on any resource that references a `Client` compare the resource's owning client to `X-User-ID`. Concretely, when a `Client` acts on an order or on a change request, the system resolves the order's `client_id` (a change request resolves through its parent order) and requires it to equal `X-User-ID`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `SalesCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The coordinator drives the sales and billing lifecycle — confirming, guaranteeing, invoicing, and settling orders, and countering, accepting, or rejecting change requests — and the server does not compare its `X-User-ID` to any entity's `id`.
- When `X-User-Role` is `EventCaptain`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The captain runs field operations — dispatching, delivering, and failing delivery legs, and fulfilling delivered, settled orders — and the server does not compare its `X-User-ID` to any entity's `id`.

The ownership comparison applies only to `Client`-acted order and change-request operations. The three opaque-identity roles are authorized purely by the role-to-endpoint matrix.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result set and defaults to 0. Out-of-range numeric values are silently clamped rather than rejected: a `limit` below 1 is raised to 1, a `limit` above 100 is lowered to 100, and a negative `offset` is raised to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. The deposit ledger listing is the canonical example: its entries are returned oldest-first so a reader can replay the running balance.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. Several list endpoints additionally accept exact-match filter query parameters, applied before pagination: the client and package listings each filter on `status`; the order listing filters on any of `client_id`, `package_id`, `venue_id`, `route_id`, `lifecycle_status`, and `settlement_status`; and the delivery-leg listing filters on any of `order_id`, `route_id`, `preceding_leg_id`, and `stop_status`. An unrecognized filter parameter is simply ignored, and a recognized filter whose value matches no row yields an empty page rather than an error.

### 2.4. Common Resource Properties

Most top-level resources — `Client`, `EventPackage`, `Venue`, `ServiceRoute`, `Order`, `AddOnLine`, `DeliveryLeg`, `StaffingReservation`, and `ChangeRequest` — carry the same four system-managed fields. The `id` is a server-minted UUID with no type prefix; it is identity only and is never an input to a business decision. The `created_at` is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation, including mutations that arrive as cascaded side effects from another entity's transition. The `version` is an integer that starts at 1 and increments by exactly 1 on every mutation.

The `DepositLedgerEntry` is the deliberate exception. Ledger entries are append-only audit records: each carries only an `id` (server-minted UUID, no type prefix) and a `created_at` (ISO 8601 UTC, three fractional digits). A `DepositLedgerEntry` has no `updated_at` and no `version`, because it is never modified after it is written. Its `created_at` is the ordering key by which an order's running deposit balance is replayed — entries are summed in `created_at` ascending order, independent of `id`. When two rows carry an identical `created_at` (the timestamp resolves only to the millisecond, so same-request appends can collide), the tie is broken by insertion order — the order in which the rows were created — which is also the tie-break used by every `created_at`-ascending list endpoint across the system.

### 2.5. Hierarchical Consistency and Cascaded Mutation

The system is immediately consistent: every mutation, including the derived recomputations it triggers, completes inside the request that caused it, with no asynchronous reconciliation. When an order is confirmed, guaranteed, invoiced, settled, cancelled, or fulfilled, the server recomputes the affected derived fields — order totals, the deposit balance, the locked package version, the staffing reservation — in that same request.

Some mutations cascade across entity boundaries, and each cascaded touch is itself a real mutation: it refreshes the touched entity's `updated_at` and increments its `version`. The two prominent cascades are route-posture recomputation and order cancellation. Whenever any delivery leg on a route changes state, the route's derived posture and its dispatched-leg count are recomputed and the route's `version` is bumped. When an order is cancelled, every still-planned delivery leg attached to it is driven to `FAILED`, and each of those leg transitions in turn recomputes its route's posture and bumps both the leg's and the route's `version`. A `ServiceRoute`'s `posture` and `dispatched_leg_count` are computed fields — they are never set directly by a client; they only move as a consequence of leg transitions.

### 2.6. Reverse-Reachability and Path Validation

The entity topology is flat: cross-entity references are foreign-key fields, not nested URL trees. Business resources are addressed at the collection root by their own `id` (for example, a delivery leg is acted on directly by its identifier), and child collections are reached through reverse-reachability list endpoints hung off the owning order or route — the add-ons, delivery legs, change requests, ledger entries, and staffing reservation of an order, and the delivery legs of a route.

For any endpoint whose path carries a resource identifier, the system validates that identifier's existence before applying business rules; a path or body foreign key that does not resolve yields `ERR_NOT_FOUND` (HTTP 404). When more than one identifier participates (a path id plus body foreign keys such as `order_id`, `route_id`, `package_id`, `venue_id`, `client_id`, `change-request` id, `delivery-leg` id, or `preceding_leg_id`), they are resolved left-to-right, and the first one that fails to resolve produces the 404.

### 2.7. Monetary Precision, Basis Points, and Rounding

All monetary amounts in the system are integer cents. Package prices, add-on unit prices, order totals, deposits, change fees, and ledger amounts are all whole-cent integers; there are no fractional-cent values in storage or in responses.

Tax rates and fees are expressed in basis points (bps), where one basis point is one hundredth of one percent. A rate of 875 basis points is 8.75 percent. To apply a basis-point rate to a cent amount, multiply the amount by the basis points and divide by 10000. Wherever a basis-point application or a percentage application does not land on a whole cent, the result is rounded half-up (round half away from zero) to the nearest whole cent. The pure headcount charge needs no rounding because every input is already in whole cents; the service fee, tax, gratuity, deposit, change fee, and refund computations each round half-up where their division would otherwise leave a fraction. Critically, when several rounded components are summed into a grand total, each component is rounded to whole cents independently first and only then added together — the system never sums raw fractional components and rounds once at the end.

### 2.8. The Deposit Ledger and Reconciliation Principle

Each order owns an append-only deposit ledger composed of `DepositLedgerEntry` rows. Every entry records an `entry_type` — one of `DEPOSIT_HOLD`, `DEPOSIT_APPLY`, `REFUND`, `FORFEIT`, or `CHANGE_FEE_DEBIT` — a signed `amount_cents`, and a free-text `reason` note (defaulting to the empty string). The sign convention is fixed: positive amounts move money toward the caterer (a deposit hold, a forfeit, a change-fee debit, or a recorded payment), and negative amounts return money to the client (a refund, or the deposit being credited toward the invoice). An order's deposit balance at any instant is the running sum of its ledger entries' `amount_cents`, replayed in `created_at` ascending order. The ledger is the single source of truth for where the money sits; settlement is permitted only when that running balance equals the order's `final_total_cents`.

### 2.9. The Staffing Pool

The system maintains a single global staffing pool with a total capacity that a `CateringAdmin` can set. The pool's remaining capacity is its total minus the sum of `reserved_staff` across all currently `HELD` `StaffingReservation` rows. When an order confirms, the staff implied by its `STAFFING` add-on lines are reserved against this pool; if the reservation would exceed the remaining capacity, confirmation is rejected with `ERR_STAFF_POOL_EXHAUSTED` (HTTP 409). Releasing a reservation — on fulfillment or on cancellation — credits its `reserved_staff` back to the pool.

### 2.10. The Two Order Dimensions

An `Order` carries two independent state dimensions that evolve on the same row. The `lifecycle_status` is the provisioning dimension and takes the values `DRAFT`, `CONFIRMED`, `GUARANTEED`, `FULFILLED`, and `CANCELLED`, beginning at `DRAFT`; `FULFILLED` and `CANCELLED` are terminal. The `settlement_status` is the money dimension and takes the values `UNBILLED`, `DEPOSIT_HELD`, `INVOICED`, `SETTLED`, `REFUNDED`, and `FORFEITED`, beginning at `UNBILLED`; `SETTLED`, `REFUNDED`, and `FORFEITED` are terminal. The two dimensions move semi-independently, but they are coupled at specific points: confirming an order advances `lifecycle_status` from `DRAFT` to `CONFIRMED` and, as a side effect of that same operation, advances `settlement_status` from `UNBILLED` to `DEPOSIT_HELD`. The settlement transition `UNBILLED → DEPOSIT_HELD` never fires on its own — it is always a consequence of the lifecycle confirm.

### 2.11. Optimistic Concurrency Control

Three catalog and route operations and one negotiation operation use optimistic concurrency control to prevent a client from acting on a stale view. Each such write carries a non-optional expected-version field whose value must equal the targeted parent entity's current `version`; on mismatch the write is rejected.

The OCC anchor for the change-request negotiation is the parent `Order`. Accepting a change request must carry `expected_order_version` matching the target order's current `version`. Acceptance recomputes a new quote — change fee, deposit delta, and provisional total — against the order as the client last observed it. If the order's `version` has advanced since that observation — for instance because an earlier change request was already accepted and legitimately superseded the headcount and totals this acceptance was quoted against — the acceptance is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), so a second acceptance carrying the pre-supersede version cannot operate on numbers that no longer hold.

Order action and edit endpoints likewise take `expected_order_version` and reject a mismatch; package retirement takes `expected_package_version` against the package's current `version`; and the delivery-leg dispatch, deliver, and fail operations take `expected_route_version` against the leg's route's current `version`. Every one of these version-mismatch rejections — the order, package, and route OCC checks alike — surfaces as `ERR_STALE_ORDER_VERSION` (HTTP 412); a missing or non-integer version field is instead a body well-formedness failure rejected with `ERR_INVALID_REQUEST` (HTTP 400) before the mismatch is ever compared. An endpoint that is not a versioned write — for example, a plain GET or a create that mints a brand-new resource — takes no version field.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Packages, Venues, and Routes

Before any order can exist, a `CateringAdmin` populates the catalog. A menu package is created with a display `name`, a base price per guest `per_head_cents` (whole cents, at least 0), a `min_headcount` of at least 1, and a `lead_time_hours` of at least 0 expressing the minimum hours that must separate confirmation from the event. A package may also carry `volume_tiers` — an ordered list of breakpoints, each `{min_headcount, per_head_cents}`, that grant a lower per-head rate above each headcount breakpoint; every tier's `per_head_cents` must be at most the base `per_head_cents`, and the tiers' `min_headcount` values must be strictly increasing. A package may declare `allergen_flags`, a list such as `NUT`, `DAIRY`, or `GLUTEN` describing allergens present in the menu (defaulting to an empty list). A new package is born `ACTIVE` at `version` 1; its `status` is one of `ACTIVE` or `RETIRED`. Retiring a package — an admin capability that requires `expected_package_version` to match the package's current `version` — moves its `status` from `ACTIVE` to `RETIRED` and bumps the package `version`; a retired package can no longer be confirmed against.

A venue is created with a `name` and three jurisdiction parameters: `tax_rate_bps`, the sales-tax rate in basis points (at least 0 and at most 2000); `service_fee_bps`, the service-fee rate in basis points applied to the food-plus-add-on subtotal (at least 0 and at most 5000); and `max_overlapping_events`, the maximum number of confirmed-or-later, non-cancelled orders whose service windows may overlap at that venue (at least 1).

A service route is created with a `route_date` — the UTC-midnight calendar date all its legs share, supplied and stored as a full ISO 8601 UTC timestamp (any parseable instant is accepted as-is and echoed back as an ISO 8601 UTC string with three fractional digits, not normalized to a bare date or to midnight) — and a `vehicle_capacity_legs` of at least 1, the maximum number of delivery legs that may be dispatched on the route's single vehicle. A fresh route opens with `posture` equal to `OPEN` and `dispatched_leg_count` equal to 0. The `posture` enumerates `OPEN`, `ROLLING`, `CLOSED`, and `BLOCKED`, and is always derived from the route's legs rather than set directly.

### 3.2. Clients and the Draft Order

A `CateringAdmin` registers each `Client` with a `company_name` and a `billing_email`. The billing address must be unique among clients whose `status` is `ACTIVE`; registering a second active client with an email already in use is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). Registration also accepts two optional flags: `tax_exempt`, which defaults to false and, when true, suppresses sales tax on every one of that client's orders; and `gratuity_policy`, one of `INCLUDED` or `OPTIONAL`, defaulting to `INCLUDED`, which governs whether gratuity is automatically added to that client's invoices. A client is born `ACTIVE`; its `status` is one of `ACTIVE` or `SUSPENDED`.

Either a `Client` or a `SalesCoordinator` opens an order, which begins life in `DRAFT` with `settlement_status` `UNBILLED`; at creation its `route_id`, `guaranteed_headcount`, `locked_package_version`, and `final_total_cents` are all null, while `provisional_total_cents` and `deposit_due_cents` start at the integer `0` (they are not computed until confirmation), and `dietary_counts` defaults to an empty object. The create payload names the `client_id` who owns it, the `package_id` to cater, the `venue_id` where the event is held, the `booked_headcount` (the guest count at booking, which must be at least the package's `min_headcount`), and the `event_start` and `event_end` timestamps bounding the event. On create, the three referenced ids are resolved for existence left-to-right (`client_id`, then `package_id`, then `venue_id`) before the `Client`-ownership comparison runs, so a `Client` who names a `client_id` that does not exist receives `ERR_NOT_FOUND` rather than `ERR_NOT_RESOURCE_OWNER`; the ownership comparison (a `Client` may open an order only for its own `client_id`, i.e. one equal to `X-User-ID`) is applied only once the named client resolves. The `event_end` must fall strictly after `event_start`; an order whose `event_end` is at or before `event_start` is rejected with `ERR_VALIDATION_WINDOW` (HTTP 422). The payload may also carry `dietary_counts`, a map of dietary tag to guest count such as `{"VEGAN": 10, "NUT_FREE": 5}`, defaulting to an empty map. The sum of the dietary counts across all tags must not exceed the order's effective headcount in scope — the booked headcount at create and edit time (the guaranteed headcount is not separately re-validated against dietary counts at guarantee time, since guarantee carries no `dietary_counts` field). The dietary tags themselves are not constrained against the package's `allergen_flags` — `allergen_flags` is stored on the package but is never consulted when validating an order's dietary counts — and arbitrary tag keys are accepted so long as their values are non-negative integers. A request whose dietary counts sum to more than the in-scope headcount is rejected with `ERR_DIETARY_EXCEEDS_HEADCOUNT` (HTTP 422). A booked headcount below `min_headcount` at create is rejected with `ERR_BELOW_MIN_HEADCOUNT` (HTTP 422). When a single create or edit trips more than one of these three domain checks, the order in which they fire differs by endpoint: a create evaluates the event-window check first, then the booked-headcount minimum, then the dietary-counts sum; an edit evaluates the booked-headcount minimum first, then the event-window check, then the dietary-counts sum. The dietary-counts sum check is evaluated last on both paths.

While an order remains in `DRAFT`, either a `Client` or a `SalesCoordinator` may edit it. The edit carries `expected_order_version` (which must match the order's current `version`) and any of `booked_headcount`, `event_start`, `event_end`, or `dietary_counts`. Edits are permitted only while `lifecycle_status` is `DRAFT`; an edit attempted against an order in any other lifecycle state is rejected with `ERR_INVALID_STATE` (HTTP 409). A successful edit applies the supplied fields and increments the order `version`.

### 3.3. Add-Ons and the Shape of a Bill

Add-on lines enrich a draft order with delivery, setup, and staffing charges. Either a `Client` or a `SalesCoordinator` attaches an `AddOnLine` to an order while it is `DRAFT`; the line's `order_id` is taken from the order being targeted. Each line declares a `kind` — one of `DELIVERY`, `SETUP`, or `STAFFING` — a `unit_cents` price per unit (whole cents, at least 0), and a `quantity` of at least 1. For a `STAFFING` line the quantity is the number of staff; for `SETUP` and `DELIVERY` it is the number of units. A staffing line may opt into per-head scaling: when `per_head_scaled` is true (it defaults to false), the line's effective quantity is recomputed at invoice time as the effective headcount divided by `staff_ratio`, rounded up to the next whole staff member; `staff_ratio` is the number of guests served per staff unit and must be at least 1 when per-head scaling is enabled, and is ignored otherwise — when `per_head_scaled` is false the line stores and returns `staff_ratio` as null regardless of any supplied value. When `per_head_scaled` is false, the stored `quantity` is used unchanged.

The bill for an order is assembled in a strictly pinned order, because the service fee, tax, and gratuity all key off the same food-plus-add-on subtotal and must see the same number. First, the food charge is computed for the order's package at the relevant headcount (see §3.4). Second, the add-on sum is accumulated: for each `AddOnLine` on the order, taken in `created_at` ascending order (independent of `id`), the line's effective quantity is multiplied by its `unit_cents` and the products are summed. In the provisional pass, every line — staffing included — uses its stored `quantity`. In the final pass, a `STAFFING` line whose `per_head_scaled` is true instead uses an effective quantity equal to the effective headcount divided by `staff_ratio`, rounded up to a whole number; all other lines and the entire provisional pass use the stored quantity. Third, the subtotal is the food charge plus the add-on sum. Fourth, the service fee is the subtotal multiplied by the venue's `service_fee_bps`, divided by 10000, rounded half-up to whole cents. Fifth, the tax is zero if the owning client is `tax_exempt`, and otherwise the subtotal multiplied by the venue's `tax_rate_bps`, divided by 10000, rounded half-up to whole cents; tax is levied on the subtotal only, never on the service fee or gratuity. Sixth, the gratuity is zero if the client's `gratuity_policy` is `OPTIONAL`, and otherwise the subtotal multiplied by a gratuity rate in basis points, divided by 10000, rounded half-up to whole cents — where the gratuity rate is the larger tier when the subtotal reaches at least the large-gratuity threshold and the base tier otherwise (see §3.4 for the constants). Seventh, the grand total is the sum of the subtotal, the service fee, the tax, and the gratuity. Each of the service fee, tax, and gratuity is rounded to whole cents independently before this final summation.

### 3.4. Pricing the Headcount, Tiers, and Gratuity Bands

The food charge is a marginal (step) tiering computation over a single package and a headcount. Conceptually, the package's base `per_head_cents` is treated as the rate for an implicit tier starting at headcount 0, and the package's `volume_tiers` are layered above it, sorted by `min_headcount` ascending. The charge starts at zero. Then, for each guest counted from the first to the headcount-th (using a 1-based index), that guest is billed at the `per_head_cents` of the highest-`min_headcount` tier whose `min_headcount` is at most that guest's index; guests below the first explicit tier's breakpoint fall back to the base rate. The per-guest rates are accumulated into the total charge. Because every input is already in whole cents, this charge is exact and requires no rounding. The absent-tier rate — the rate applied to any guest index that falls below every explicit tier — is the base `per_head_cents`.

The provisional pass and the final pass differ only in which headcount they feed into this computation. The provisional pass uses the order's `booked_headcount`. The final pass uses the effective headcount, which embodies the final-count guarantee: the client is billed for at least 90 percent of the headcount booked at confirmation even if they guarantee fewer guests. The effective headcount is the larger of the guaranteed headcount and a floor equal to the booked headcount multiplied by 90 percent and rounded up to the next whole guest. At the boundary, a guarantee exactly equal to the floor bills the guarantee, and a guarantee one guest below the floor bills the floor.

The gratuity rate depends on the subtotal band. When the subtotal is at least 5,000,000 cents (that is, fifty thousand dollars), the large gratuity rate of 2200 basis points (22 percent) applies; below that threshold the base gratuity rate of 1800 basis points (18 percent) applies. These bands are evaluated against the same subtotal the service fee and tax see.

### 3.5. Confirmation: Locking, Pricing, Deposit, and Staff

Confirmation is the pivot of the whole engagement, performed by a `SalesCoordinator` and carrying `expected_order_version`. It is permitted only when the order is in `DRAFT`; otherwise it is rejected with `ERR_INVALID_STATE`. Confirmation runs a gauntlet of preconditions. The package must be `ACTIVE` — confirming against a `RETIRED` package is rejected with `ERR_PACKAGE_RETIRED` (HTTP 409). The booked headcount must be at least the package's `min_headcount`. The order-cutoff gate must hold: the whole hours from the current server time to `event_start`, floored to an integer exactly as the deposit-rush and cancellation-window computations floor it, must be at least the package's `lead_time_hours`; a confirmation whose floored hours-out is strictly below `lead_time_hours` is rejected with `ERR_LEAD_TIME_VIOLATED` (HTTP 409). And the venue must have room: counting the confirmed-or-later orders at the same venue — those whose `lifecycle_status` is `CONFIRMED`, `GUARANTEED`, or `FULFILLED` (DRAFT and CANCELLED orders are not counted) — whose half-open `event_start`-to-`event_end` interval overlaps this order's window — excluding this order itself — that count must be strictly less than the venue's `max_overlapping_events`; a confirmation that would meet or exceed the cap is rejected with `ERR_VENUE_OVERBOOKED` (HTTP 409). Adjacency is allowed, because the overlap interval is half-open: an event that starts exactly when another ends does not overlap it.

When the preconditions pass, confirmation performs a cluster of coupled side effects in one atomic request. It snapshots the package's current `version` into the order's `locked_package_version`, pinning pricing against later catalog edits. It computes `provisional_total_cents` via the provisional grand-total pass and `deposit_due_cents` via the deposit computation. It advances `settlement_status` from `UNBILLED` to `DEPOSIT_HELD` and appends a `DEPOSIT_HOLD` ledger entry whose `amount_cents` equals the positive deposit due. It creates a `StaffingReservation` in status `HELD` whose `reserved_staff` equals the sum of the stored `quantity` of the order's `STAFFING` add-on lines at confirmation (the provisional reading — per-head scaling is not applied here, it only takes effect in the final pass at invoicing), and debits that count from the global staffing pool — if the pool cannot absorb it, the whole confirm fails with `ERR_STAFF_POOL_EXHAUSTED`. A `StaffingReservation`'s `status` is one of `HELD` or `RELEASED`. Finally the order `version` increments by 1, and its `lifecycle_status` becomes `CONFIRMED`.

The deposit due is itself a tiered computation. The base deposit is the provisional total multiplied by 25 percent, rounded half-up to whole cents. But a rush surcharge applies to last-minute bookings: if the whole hours from the current server time to `event_start` (floored) are fewer than 72, the deposit is instead the provisional total multiplied by 50 percent, rounded half-up. Whichever branch applies, the deposit is then raised to an absolute floor of 10,000 cents if it would otherwise fall below it — the deposit is the larger of the computed amount and 10,000 cents.

### 3.6. Guaranteeing the Final Count

Once an order is `CONFIRMED`, a `SalesCoordinator` locks the guaranteed guest count, carrying `expected_order_version` and the `guaranteed_headcount`. The guarantee is permitted only when the order is `CONFIRMED` (otherwise `ERR_INVALID_STATE`), the guaranteed headcount is provided and is at least the package's `min_headcount` (otherwise `ERR_BELOW_MIN_HEADCOUNT`), the current server time is strictly before `event_start` (a past event cannot be guaranteed, otherwise `ERR_INVALID_STATE`), and there is no open negotiation — that is, no change request on this order is in `PROPOSED` or `COUNTERED` status; an attempt to guarantee while an open change request exists is rejected with `ERR_OPEN_CHANGE_REQUEST` (HTTP 409). On success the order records the supplied `guaranteed_headcount`, advances `lifecycle_status` from `CONFIRMED` to `GUARANTEED`, and increments the order `version` by 1. The final-count guarantee floor is not applied here; it is applied at invoicing through the effective-headcount computation. The `guaranteed_headcount` is null until the order reaches `GUARANTEED`.

### 3.7. Invoicing, Payment, and Settlement

Invoicing closes the provisional world and opens the final one. A `SalesCoordinator` invoices an order carrying `expected_order_version`; invoicing is permitted only when `lifecycle_status` is `GUARANTEED` and `settlement_status` is `DEPOSIT_HELD` (otherwise `ERR_INVALID_STATE`). Invoicing computes `final_total_cents` via the final grand-total pass — which uses the effective headcount (the guarantee floor) and recomputes any per-head-scaled staffing lines — advances `settlement_status` from `DEPOSIT_HELD` to `INVOICED`, and credits the held deposit toward the invoice by appending a `DEPOSIT_APPLY` ledger entry whose `amount_cents` is the negative of `deposit_due_cents`. The order `version` increments by 1. The `final_total_cents` is null until the order is invoiced.

Payment is recorded against the ledger so the running balance can climb to meet the invoice. Either a `Client` or a `SalesCoordinator` records a payment carrying `expected_order_version` and an `amount_cents`. A payment appends a `DEPOSIT_APPLY` ledger entry with a positive `amount_cents` equal to the supplied amount, moving the balance toward `final_total_cents`, and increments the order `version`. A payment whose `amount_cents` is at or below zero, or that would push the running ledger balance above `final_total_cents`, is rejected with `ERR_INVALID_PAYMENT` (HTTP 422). A payment recorded before the order has been invoiced — while `final_total_cents` is still null, so there is no invoice to pay against — is likewise rejected with `ERR_INVALID_PAYMENT` rather than a state error; the endpoint imposes no other lifecycle or settlement state-gate.

Settlement is the final money step. A `SalesCoordinator` settles an order carrying `expected_order_version`; settlement is permitted only when `settlement_status` is `INVOICED` and the running deposit-ledger balance for the order exactly equals `final_total_cents`. If the balance does not yet equal the invoice, settlement is rejected with `ERR_BALANCE_UNPAID` (HTTP 409). On success `settlement_status` advances from `INVOICED` to `SETTLED` and the order `version` increments by 1.

### 3.8. Fulfillment

Fulfillment is the lifecycle's terminal step on the operations side, performed by an `EventCaptain` carrying `expected_order_version`. It is permitted only when the order is `GUARANTEED`, its `settlement_status` is `SETTLED` (the invoice must be paid before the event closes), and every delivery leg attached to the order is in `stop_status` `DELIVERED`; a fulfill from any other configuration is rejected with `ERR_INVALID_STATE`. Fulfillment advances `lifecycle_status` from `GUARANTEED` to `FULFILLED`, releases the order's `StaffingReservation` by moving its `status` from `HELD` to `RELEASED` and crediting its `reserved_staff` back to the global pool, and increments the order `version` by 1.

### 3.9. Cancellation, Refund, and Forfeit

A `Client` may cancel its own order, carrying `expected_order_version`. The settlement consequences depend on the lifecycle state at cancellation. Cancelling a `DRAFT` order is the simple case: a draft holds no deposit, so the order moves to `CANCELLED`, the `settlement_status` stays `UNBILLED`, no refund or forfeit ledger entry is written, and the order `version` increments by 1.

Cancelling a `CONFIRMED` or `GUARANTEED` order runs the cancellation settlement, which splits the held deposit by a refund tier keyed to how far out the event is. Let the whole hours from the current server time to `event_start` (floored) be the hours-out value. The refund fraction is determined top-down by inclusive thresholds: if hours-out is at least 168, the fraction is 1.00 (full deposit returned); otherwise if hours-out is at least 72, the fraction is 0.50; otherwise (inside 72 hours) the fraction is 0.00 (full forfeit). The refunded amount is the order's `deposit_due_cents` multiplied by the refund fraction, rounded half-up to whole cents; the forfeited amount is `deposit_due_cents` minus the refunded amount (computed by subtraction so that refunded plus forfeited always conserves exactly to the deposit, with no independent rounding on the forfeit).

When the refund fraction is greater than zero, `settlement_status` moves from `DEPOSIT_HELD` to `REFUNDED`: a `REFUND` ledger entry is appended with `amount_cents` equal to the negative of the refunded amount, and when the forfeited amount is greater than zero a `FORFEIT` ledger entry is appended with `amount_cents` equal to the positive forfeited amount. When the refund fraction is zero, `settlement_status` moves from `DEPOSIT_HELD` to `FORFEITED` and a single `FORFEIT` entry is appended with `amount_cents` equal to the positive full `deposit_due_cents`. In every confirmed-or-later cancellation, the `StaffingReservation` is released (`HELD → RELEASED`, crediting `reserved_staff` back to the pool), and every still-`PLANNED` delivery leg on the order is cascaded to `FAILED`, with each cascaded leg recomputing its route's posture. A settled `GUARANTEED` order is the one exception that cannot be cancelled — when an order's `settlement_status` is already `SETTLED`, cancellation is refused (it must be refunded out of band by an admin), and the attempt is rejected with `ERR_INVALID_STATE`. The order `version` increments by 1 on any cancellation.

### 3.10. The Change-Request Negotiation

When a client wants to change an order's headcount or start time after confirmation, they open a change request — a `Client`-only action permitted against a `CONFIRMED` or `GUARANTEED` order. The request names the `order_id`, a `requested_headcount` (which must be at least the package's `min_headcount`), and a `requested_event_start` (which may equal the order's current start). A new change request begins in `PROPOSED` with its `counter_headcount` null and its `change_fee_cents` at the integer `0` (the fee is not computed until acceptance); its `status` is one of `PROPOSED`, `COUNTERED`, `ACCEPTED`, or `REJECTED`, with `ACCEPTED` and `REJECTED` terminal. The `requested_event_start` may equal the order's current start and is otherwise unconstrained — it is not validated against the clock or the event window.

The negotiation is cyclic. A `SalesCoordinator` may counter a `PROPOSED` request — permitted only when the request is `PROPOSED` and the parent order is `CONFIRMED` or `GUARANTEED` — by supplying a `counter_headcount` (a required integer of at least 1; absence or a value below 1 is rejected as `ERR_INVALID_REQUEST`, and the package `min_headcount` is not re-checked here — that floor is enforced only at acceptance); this moves the request from `PROPOSED` to `COUNTERED`, records the `counter_headcount`, and bumps the request `version`. The `counter_headcount` is null until the request is countered. In response, the `Client` may revise a `COUNTERED` request — permitted only when the request is `COUNTERED` — by supplying a new `requested_headcount`; this moves the request from `COUNTERED` back to `PROPOSED`, clears the `counter_headcount` to null, and bumps the request `version`. This `PROPOSED → COUNTERED → PROPOSED` loop may repeat any number of rounds.

Either party may end the negotiation by rejecting. The reject endpoint authorizes both `SalesCoordinator` and `Client`; it requires only that the request be in `PROPOSED` or `COUNTERED` (otherwise `ERR_INVALID_STATE`) and, for a `Client` caller, that the caller own the parent order — it does not pin the rejecting role to the request's status, so either authorized role may reject from either open status. Whoever rejects, the request moves to `REJECTED`, the request `version` bumps, and the order is left entirely unchanged — it keeps its current headcount and totals.

Acceptance is where the money moves. The accept endpoint authorizes both `SalesCoordinator` and `Client`; conventionally a `SalesCoordinator` accepts a `PROPOSED` request and a `Client` accepts a `COUNTERED` request, but the endpoint does not pin the accepting role to the request's status — either authorized role may accept from either open status, subject only to the `Client` ownership check on the parent order. Both forms carry `expected_order_version`, which must match the parent order's current `version` — a mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) per §2.11. The request must be in `PROPOSED` or `COUNTERED` (otherwise `ERR_INVALID_STATE`), and this state check is evaluated before the `expected_order_version` mismatch check. Accepting a `PROPOSED` request additionally requires the parent order to be `CONFIRMED` or `GUARANTEED` (otherwise `ERR_INVALID_STATE`) and the `requested_headcount` to be at least the package's `min_headcount` (otherwise `ERR_BELOW_MIN_HEADCOUNT`); a `COUNTERED` acceptance re-checks neither the parent order's lifecycle nor the package minimum. The effective new headcount is the `requested_headcount` when accepting a `PROPOSED` request and the `counter_headcount` when accepting a `COUNTERED` request. On acceptance the system computes `change_fee_cents` from the effective new headcount, applies the new headcount to the order's `booked_headcount` (and, for a `PROPOSED` acceptance, the `requested_event_start` to the order's `event_start`), recomputes `provisional_total_cents` via the provisional grand-total pass, recomputes `deposit_due_cents`, and appends two ledger entries: a `DEPOSIT_HOLD` entry whose `amount_cents` is the signed delta between the new and old deposit (which may be negative), and a `CHANGE_FEE_DEBIT` entry whose `amount_cents` is the positive `change_fee_cents`. The change request moves to `ACCEPTED` and its `version` bumps.

Acceptance also cascades on the lifecycle dimension: if the order was `GUARANTEED`, the headcount change invalidates the guarantee, so the order reverts from `GUARANTEED` to `CONFIRMED` and its `guaranteed_headcount` is cleared to null. That revert is itself a mutation that bumps the order `version`; the acceptance then increments the order `version` a further time, so a guaranteed order accepting a change advances its version by two in total (the revert bump plus the acceptance bump).

The change fee is a threshold computation over how late the change lands and how big the swing is. Let the whole hours from the current server time to `event_start` (floored) be the hours-out value, and let the headcount delta be the absolute difference between the effective new headcount and the order's current `booked_headcount`. Both inputs are read from the order as it stands before the acceptance writes anything: the hours-out value uses the order's existing `event_start` (not the `requested_event_start` that a `PROPOSED` acceptance is about to apply), and the delta uses the existing `booked_headcount`. If hours-out is at least 336, the fee is 0. Otherwise if hours-out is at least 72, the fee is a base of 5,000 cents plus 150 cents per head of delta. Otherwise (inside 72 hours, a rush change) the fee is that same base-plus-per-head amount multiplied by 1.5, rounded half-up to whole cents after the multiplier.

### 3.11. Multi-Stop Delivery and Route Posture

Delivery legs carry food along a route. A `CateringAdmin` or a `SalesCoordinator` schedules a `DeliveryLeg` by naming the `order_id` whose food it carries, the `route_id` it rides on, a `window_start` and a `window_end` (the earliest and latest arrival at the stop, with `window_end` required to be strictly after `window_start`, else `ERR_VALIDATION_WINDOW`), and an optional `preceding_leg_id` pointing at the leg immediately before it on the same route (null for the first stop). At schedule time a non-null `preceding_leg_id` is validated only for existence (`ERR_NOT_FOUND` if it does not resolve) — it is not checked to belong to the same route, nor that the parent order is in any particular lifecycle state, and the parent order's terminal status does not block scheduling a leg. The `preceding_leg_id` chains the route's legs into an ordered linked list. Creating a leg sets its `stop_status` to `PLANNED`, sets the owning order's `route_id` to the route if it was still null (and otherwise leaves the order's existing `route_id` untouched, even when this leg rides a different route), and recomputes the route's posture. A leg's `stop_status` is one of `PLANNED`, `DISPATCHED`, `DELIVERED`, or `FAILED`, with `DELIVERED` and `FAILED` terminal.

An `EventCaptain` drives a leg through the field. Dispatching a leg — carrying `expected_route_version` — moves it from `PLANNED` to `DISPATCHED`, but only when several conditions hold: the leg is `PLANNED`; the parent order is `GUARANTEED` (only guaranteed orders ship); the route is not yet full, meaning its `dispatched_leg_count` is strictly less than its `vehicle_capacity_legs`; the route order is respected, meaning `preceding_leg_id` is null or the preceding leg's `stop_status` is `DISPATCHED` or `DELIVERED`; and the single vehicle is not double-booked, meaning no other already-`DISPATCHED` leg on the same route has a window that overlaps this leg's `window_start`-to-`window_end` interval inclusively at the endpoints. A dispatch that violates route ordering or exceeds vehicle capacity is rejected with `ERR_LEG_OUT_OF_ORDER` (HTTP 409); a dispatch whose window inclusively overlaps another dispatched leg's window on the route is rejected with `ERR_LEG_WINDOW_CONFLICT` (HTTP 409); a dispatch from a non-`PLANNED` leg, or one whose parent order is not `GUARANTEED`, is rejected with `ERR_INVALID_STATE` (the leg-state check is evaluated before the parent-order-state check). The two state checks run first, then the route-version OCC check, and only then the three business gates in this fixed precedence: the window-conflict check is evaluated first (so when a dispatch simultaneously conflicts on its window and violates ordering or capacity, `ERR_LEG_WINDOW_CONFLICT` is the error surfaced), followed by the preceding-leg ordering check and finally the vehicle-capacity check, both of which raise `ERR_LEG_OUT_OF_ORDER`. On a successful dispatch the route's `dispatched_leg_count` increases by 1, the route's posture is recomputed (driving `OPEN` toward `ROLLING`), and both the leg's and the route's `version` increment by 1.

Delivering a `DISPATCHED` leg — carrying `expected_route_version` — moves it from `DISPATCHED` to `DELIVERED`, recomputes the route posture (which becomes `CLOSED` once every leg is delivered), and bumps both versions. Failing a `DISPATCHED` leg — carrying `expected_route_version` — moves it from `DISPATCHED` to `FAILED`, decrements the route's `dispatched_leg_count` by 1, recomputes the posture (which becomes `BLOCKED` while any leg is failed), and bumps both versions. A deliver or fail from a non-`DISPATCHED` leg is rejected with `ERR_INVALID_STATE`. Separately, when a parent order is cancelled, each of its still-`PLANNED` legs is cascaded from `PLANNED` to `FAILED` by the system; that cascade recomputes the route posture and bumps both versions, but does not decrement `dispatched_leg_count` because a planned leg was never counted in it.

The route posture is always derived from the full set of the route's legs, with a fixed precedence. Considering every `DeliveryLeg` whose `route_id` is the route (no status filter): if any leg is `FAILED`, the posture is `BLOCKED`; otherwise if the route has at least one leg and all of them are `DELIVERED`, the posture is `CLOSED`; otherwise if any leg is `DISPATCHED`, the posture is `ROLLING`; otherwise the posture is `OPEN`. The precedence is `BLOCKED` over `CLOSED` over `ROLLING` over `OPEN`. The route's `dispatched_leg_count` is maintained separately as the count of legs in `DISPATCHED` or `DELIVERED` status.

### 3.12. Validation Ordering

When several checks guard one write, they are evaluated in a fixed priority so that the right error surfaces first. The order is: first authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then resource ownership for `Client`-acted order and change-request operations (`ERR_NOT_RESOURCE_OWNER`), then existence of every referenced resource id (`ERR_NOT_FOUND`), then request-body well-formedness — required fields present with correct types and valid enum membership (`ERR_INVALID_REQUEST`), then the target's state-validity for the attempted transition across whichever dimension applies (`ERR_INVALID_STATE`). Only after those structural checks pass does the system reach the domain-specific business rules — package-retired, lead-time, venue capacity, leg ordering and window conflicts, headcount minimums, dietary counts, open-change-request blocks, the change-accept staleness check, the settle balance check, the staff-pool check, and the duplicate-email check — each rejecting with its own error as described in the workflows above. Where a single operation could trip more than one business rule, the authentication-through-state ordering always takes precedence over any business rule.

The test-driving surface rounds out the system: a `CateringAdmin` may advance the logical clock to a supplied instant — every lead-time, cutoff, deposit-rush, cancellation-window, and change-fee computation reads this clock — by submitting a `to_iso8601` value, and may set the global staffing pool's capacity by submitting a `total_staff` value (a required integer of at least 0), after which the pool's remaining capacity is recomputed as that total minus all currently `HELD` reservations. Both controls return `200 OK` with an empty object (`{}`) in the response `data` — they expose no resource body. The staffing pool's total defaults to 0 until an admin sets it.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (a client, package, venue, route, order, add-on line, delivery leg, or change request) return `201 Created`. Operations that modify an existing resource — every state-transition action, every edit, and the clock and staff-pool controls — return `200 OK`. All list and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/catering/clients` | Register a client account | CateringAdmin |
| GET | `/catering/clients/{id}` | Fetch a client | CateringAdmin, Client, SalesCoordinator |
| GET | `/catering/clients` | List clients (paginated) | CateringAdmin, SalesCoordinator |
| POST | `/catering/packages` | Create a menu package | CateringAdmin |
| GET | `/catering/packages/{id}` | Fetch a package | CateringAdmin, Client, SalesCoordinator |
| GET | `/catering/packages` | List packages (paginated) | CateringAdmin, Client, SalesCoordinator |
| POST | `/catering/packages/{id}/retire` | Retire a package | CateringAdmin |
| POST | `/catering/venues` | Create a venue | CateringAdmin |
| GET | `/catering/venues/{id}` | Fetch a venue | CateringAdmin, Client, SalesCoordinator |
| POST | `/catering/routes` | Create a multi-stop service route | CateringAdmin |
| GET | `/catering/routes/{id}` | Fetch a route with derived posture | CateringAdmin, EventCaptain, SalesCoordinator |
| GET | `/catering/routes/{id}/delivery-legs` | List the delivery legs riding on a route | CateringAdmin, EventCaptain, SalesCoordinator |
| POST | `/catering/orders` | Create a draft order | Client, SalesCoordinator |
| GET | `/catering/orders/{id}` | Fetch an order with both dimensions and totals | CateringAdmin, Client, SalesCoordinator, EventCaptain |
| GET | `/catering/orders` | List orders (filterable) | CateringAdmin, SalesCoordinator |
| PATCH | `/catering/orders/{id}` | Edit a draft order's mutable fields | Client, SalesCoordinator |
| POST | `/catering/orders/{id}/confirm` | Confirm a draft order | SalesCoordinator |
| POST | `/catering/orders/{id}/guarantee` | Lock the guaranteed headcount | SalesCoordinator |
| POST | `/catering/orders/{id}/invoice` | Issue the final invoice | SalesCoordinator |
| POST | `/catering/orders/{id}/payments` | Record a client payment | Client, SalesCoordinator |
| POST | `/catering/orders/{id}/settle` | Mark the order settled | SalesCoordinator |
| POST | `/catering/orders/{id}/fulfill` | Close out a delivered, settled event | EventCaptain |
| POST | `/catering/orders/{id}/cancel` | Cancel an order | Client |
| GET | `/catering/orders/{id}/add-ons` | List an order's add-on lines | CateringAdmin, Client, SalesCoordinator |
| GET | `/catering/orders/{id}/delivery-legs` | List an order's delivery legs | CateringAdmin, Client, SalesCoordinator, EventCaptain |
| GET | `/catering/orders/{id}/change-requests` | List an order's change requests | CateringAdmin, Client, SalesCoordinator |
| GET | `/catering/orders/{id}/ledger` | List an order's deposit ledger (created_at ASC) | CateringAdmin, Client, SalesCoordinator |
| GET | `/catering/orders/{id}/staffing-reservation` | List an order's staffing reservation(s) | CateringAdmin, SalesCoordinator |
| POST | `/catering/orders/{id}/add-ons` | Attach an add-on to a draft order | Client, SalesCoordinator |
| GET | `/catering/add-ons/{id}` | Fetch an add-on line | CateringAdmin, Client, SalesCoordinator |
| POST | `/catering/delivery-legs` | Schedule a delivery leg | CateringAdmin, SalesCoordinator |
| GET | `/catering/delivery-legs/{id}` | Fetch a delivery leg | CateringAdmin, EventCaptain, SalesCoordinator |
| GET | `/catering/delivery-legs` | List delivery legs (filterable) | CateringAdmin, EventCaptain, SalesCoordinator |
| POST | `/catering/delivery-legs/{id}/dispatch` | Dispatch a planned leg | EventCaptain |
| POST | `/catering/delivery-legs/{id}/deliver` | Mark a dispatched leg delivered | EventCaptain |
| POST | `/catering/delivery-legs/{id}/fail` | Mark a dispatched leg failed | EventCaptain |
| POST | `/catering/change-requests` | Open a change request | Client |
| GET | `/catering/change-requests/{id}` | Fetch a change request | CateringAdmin, Client, SalesCoordinator |
| POST | `/catering/change-requests/{id}/counter` | Counter a proposed change | SalesCoordinator |
| POST | `/catering/change-requests/{id}/revise` | Revise a countered change | Client |
| POST | `/catering/change-requests/{id}/accept` | Accept a change (OCC against the order) | Client, SalesCoordinator |
| POST | `/catering/change-requests/{id}/reject` | Reject a change | SalesCoordinator, Client |
| POST | `/catering/_clock/set_current_utc` | Set the server's current UTC clock | CateringAdmin |
| POST | `/catering/_staff-pool/set_capacity` | Set the global staffing pool capacity | CateringAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PACKAGE_RETIRED` | 409 |
| `ERR_LEAD_TIME_VIOLATED` | 409 |
| `ERR_LEG_WINDOW_CONFLICT` | 409 |
| `ERR_VENUE_OVERBOOKED` | 409 |
| `ERR_LEG_OUT_OF_ORDER` | 409 |
| `ERR_BELOW_MIN_HEADCOUNT` | 422 |
| `ERR_DIETARY_EXCEEDS_HEADCOUNT` | 422 |
| `ERR_OPEN_CHANGE_REQUEST` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_BALANCE_UNPAID` | 409 |
| `ERR_STAFF_POOL_EXHAUSTED` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_INVALID_PAYMENT` | 422 |
| `ERR_VALIDATION_WINDOW` | 422 |
