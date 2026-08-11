# Golf Club Fitting & Repair API — Product Requirements Document

## 1. Introduction

A full-service golf shop runs two revenue engines that share one floor, one staff roster, and one wall of component stock. The first engine is custom fitting: a customer books time on a launch-monitor bay with a fitting specialist, walks out of the session with a build spec, and — once the quote is approved — the shop reserves a head, a shaft, and a grip from finite inventory and assembles a finished club. The second engine is the repair bench: regrips, reshafts, and loft-and-lie adjustments on clubs the customer already owns, quoted instantly, gated on a deposit, and subject to quality checks before pickup. Wrapped around both are the commercial periphery of a modern shop: lesson packages whose credits pay for bay time, a trade-in desk that turns used clubs into store credit and a used-club showcase, and a warranty program that covers delivered builds and completed repairs for bounded windows.

This document specifies the API that backs those operations. It is written for the engineers who will implement the service and for the product managers who will sign off on its behavior. Every endpoint is mounted under the `/golf-shop` prefix. The specification is deliberately precise about the things that must be exact — money arithmetic in integer cents, state names, error identifiers, stock accounting, and the logical clock that drives every timestamp and every time-based sweep — and deliberately narrative about how those pieces compose into day-to-day workflows. Two design commitments pervade the whole system: all side effects of an operation are applied atomically within the triggering request, and the passage of time is never observed from the wall clock but from a server-held logical clock that tests and operations staff can advance explicitly.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role the principal acts in. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); a role value outside the six defined below is on no endpoint's authorized list and is therefore rejected with `ERR_FORBIDDEN_ROLE` as well.

Six roles exist, spelled exactly as follows: `Customer`, `FittingSpecialist`, `RepairTechnician`, `Instructor`, `ShopManager`, and `ShopAdmin`.

Role identity is resolved in two different ways. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `FittingSpecialist`, `RepairTechnician`, `Instructor`, or `ShopManager`, `X-User-ID` is the `id` of the acting `StaffMember` entity. Staff-attribution fields recorded on resources — the fitting specialist assigned to a session, the staff member who issued a trade-in offer, the appraiser recorded on a used-club listing — are informational only and are never compared to `X-User-ID`: any holder of an endpoint's authorized role may act on such a resource regardless of which staff member is recorded on it. The single exception is the listing price-adjustment segregation rule of Section 3.6, which does compare the acting manager's id to the listing's `appraised_by_staff_id`. When `X-User-Role` is `ShopAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

Ownership scoping for customers applies to every owner-scoped action in this document — approving builds and tickets, paying tickets, accepting or declining offers, appealing claims, reserving or purchasing listings, cancelling one's own sessions, specs, and tickets — and to customer self-reads of owned resources. On creation endpoints, a caller acting as `Customer` must supply a `customer_id` equal to their own `X-User-ID`; creating a resource for someone else is rejected with `ERR_NOT_RESOURCE_OWNER`. Used-club listings are the public exception: they are readable by every role as a discovery channel. On list endpoints, customer ownership scoping narrows the result set to the caller's own resources rather than rejecting the request; the credit-ledger list is the exception — a `Customer` paging another customer's ledger entries is rejected with `ERR_NOT_RESOURCE_OWNER`.

The roles' capabilities in brief. A `Customer` books and cancels their own fitting sessions, approves quoted builds and repair tickets, makes ticket payments, submits and responds to trade-in appraisals, reserves and purchases used clubs, and files and appeals warranty claims. A `FittingSpecialist` runs fitting sessions (check-in and completion), authors and quotes build specs, issues trade-in offers, and delivers finished builds. A `RepairTechnician` opens repair tickets, starts bench work, submits quality checks, marks builds ready, and cancels or hands over tickets. An `Instructor` has read-only visibility into lesson packages and fitting sessions. A `ShopManager` administers customers, bays, component stock and receipts, lesson-package sales, listing price adjustments, trade-in offers, build delivery, and warranty decisions. A `ShopAdmin` bootstraps customers and staff and drives the logical clock.

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

All list endpoints accept two query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. A `limit` outside that range, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_VALIDATION` (HTTP 400). List responses are always sorted by `created_at` ascending, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` so clients can page deterministically. List endpoints additionally accept the filter parameters named in the workflow narratives of Section 3; each filter narrows the result set to rows whose corresponding field equals the supplied value.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and a `version` integer. Both timestamps are ISO 8601 UTC values with three fractional digits, and both are stamped from the server's logical clock — never from wall-clock time. The `version` of an entity starts at 1 on creation and increments by exactly one on every mutation of that entity, including mutations caused by state transitions and administrative status changes. One entity deviates from this pattern: a credit ledger entry is append-only and carries only `id` and `created_at`; `updated_at` and `version` are absent from it by design.

All entities in this system are peers. No resource is nested beneath another in the URL hierarchy; relationships are expressed through identifier fields in request bodies and responses rather than through path structure. Wherever a path contains a resource id, the id is resolved left to right, and a body that references other entities by id has those references resolved after the path. An unresolvable reference is rejected with the corresponding not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_BAY_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_SPEC_NOT_FOUND`, `ERR_COMPONENT_ITEM_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_APPRAISAL_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND` (all HTTP 404).

### 2.5. The Logical Clock and Scheduled Sweeps

The server maintains a logical clock. At startup the clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time; every `created_at`, `updated_at`, and business timestamp in the system is stamped from it. An administrator-only test-driving capability sets the clock to a supplied instant given as `to_iso8601`, and responds with the resulting `current_utc`. Setting the clock is not a passive act: it runs every time-based sweep the system defines. Any appraisal offer whose `offer_expires_at` lies in the past is swept from `OFFERED` to `EXPIRED`. Any used-club reservation whose `reserved_until` lies in the past is swept back from `RESERVED` to `LISTED`, clearing both `reserved_by_customer_id` and `reserved_until`. Any lesson package whose `expires_at` lies in the past is swept from `ACTIVE` or `EXHAUSTED` to `EXPIRED`. And any fitting session still in `BOOKED` whose `ends_at` precedes the new current time is swept to `NO_SHOW`, forfeiting any lesson-package credit the booking consumed — a no-show never refunds.

### 2.6. Money, Precision, and Rounding

All monetary values are integer cents; no fractional cents exist anywhere in the system. Wherever a calculation produces a fractional cent, the value is rounded half-up to the nearest integer cent. Rounding is applied at exactly the points stated in each calculation and nowhere else: build pricing rounds the discount exactly once; trade-in valuations round each club's line individually before summing, so that per-line round-then-sum is the pinned behavior and sum-then-round of the same inputs — which can differ by cents — is explicitly not the specified behavior. Deposit and refund arithmetic likewise rounds half-up, with remainder balances kept exact to the cent on odd totals.

### 2.7. Optimistic Concurrency Control on Quotes and Offers

Two write operations are guarded by optimistic concurrency control, and only those two. A request to quote or re-quote a build spec must carry `expected_build_spec_version`, a non-optional input holding the spec `version` the client last observed. If the spec's current `version` has advanced beyond that observed value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A re-quote legitimately supersedes the prior quote under product semantics, so this version check is the only protection against acting on a stale view of the spec. The same discipline governs trade-in offers: issuing an offer requires `expected_appraisal_version` matching the appraisal's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). A new offer legitimately supersedes any prior offer — including one that was declined — so again the version check is the sole stale-view protection. No endpoint outside these two accepts a version field.

### 2.8. The Store-Credit Ledger

Store credit is tracked in an append-only ledger. Each entry records the `customer_id` it belongs to, a signed `amount_cents` (positive grants credit, negative redeems it), a `reason` drawn from `TRADE_IN_ACCEPT`, `BUILD_PAYMENT`, `BUILD_REFUND`, `WARRANTY_RESOLUTION`, `TICKET_PAYMENT`, or `TICKET_REFUND`, and a `reference_id` naming the originating entity — an appraisal, a build spec, a claim, or a ticket. The `reference_id` is identity only: it is never used for ordering or selection. A customer's `credit_balance_cents` is always exactly the sum of `amount_cents` over every ledger entry for that customer; the ledger is the only mechanism that ever mutates the balance, entries carry no status filter of any kind, and the balance is recomputed on every ledger write. Customers and shop managers may page through a customer's ledger history.

### 2.9. Component Stock Accounting

Component inventory is accounted in four counters per item. `received_total` begins at the item's `initial_stock` and grows by the quantity of every recorded supplier receipt. `stock_reserved` counts units held by allocated component orders or by in-progress reshaft tickets. `consumed_total` counts units permanently used up by completed builds and repairs. `stock_on_hand` — the only figure the allocation logic consults — is the unreserved physical stock, always equal to `received_total` minus `stock_reserved` minus `consumed_total`. Reservations move units from on-hand to reserved; consumption moves them from reserved to consumed; releases move them from reserved back to on-hand. Every reservation release — whether from a cancelled build or a cancelled reshaft — is a stock event, and every stock event re-runs the allocation sweep described in Section 3.3.

### 2.10. Validation Order of Evaluation

When several checks could reject the same request, they are evaluated in a fixed order so that the surfaced error is deterministic. First, the presence and non-emptiness of the two identity headers is verified (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the role's permission for the endpoint (`ERR_FORBIDDEN_ROLE`). Third, request body shape — required fields present, enum values valid, a session's `starts_at` strictly earlier than its `ends_at`, the warranty-subject exclusive-or respected, market comparables present when the offer basis requires them, a denial reason present when a claim is denied — all under `ERR_VALIDATION` (HTTP 400). Fourth, existence: path ids left to right, then body foreign-key ids, under the not-found errors of Section 2.4. Fifth, ownership (`ERR_NOT_RESOURCE_OWNER`). Sixth, optimistic concurrency where it applies (`ERR_STALE_VERSION`). Seventh, the per-transition state guards, each carrying its own domain error. Eighth, segregation of duties on listing price adjustments (`ERR_SEGREGATION_OF_DUTIES`). Ninth, temporal rules — the bay and specialist overlap checks and the warranty window. Tenth, fiscal rules before any parts are committed — customer standing, credit sufficiency, lesson-credit availability, deposit-before-work, payment sequencing, and paid-in-full before pickup. Eleventh and last, structural constraints — reshaft shaft requirements, component-slot type matching, shaft stock for bench work, the appeal cap, and duplicate-claim detection. One deviation from this fixed order is pinned at the used-club showcase: on listing reservation and purchase, the acting customer's existence and standing are verified before the listing's state guard (see Section 3.6).

## 3. Business Logic & Workflows

### 3.1. Staffing the Shop and Managing Customers

Before anything else can happen, the shop needs people and places. A `ShopAdmin` — or a `ShopManager` — registers a customer with a `full_name` and an `email`; the email must be unique across all customers. New customers are born `ACTIVE` and carry two computed counters that follow them everywhere: `completed_builds_count`, starting at zero and incremented each time one of their builds is delivered, and `credit_balance_cents`, the ledger-derived store-credit balance described in Section 2.8. A `ShopManager` may suspend or reactivate a customer by setting a `target_status` of `SUSPENDED` or `ACTIVE`; suspension does not delete history, but it blocks exactly four customer actions elsewhere in the system with `ERR_CUSTOMER_SUSPENDED` (HTTP 409): approving a build spec, approving a repair ticket, reserving a used-club listing, and purchasing one. Booking sessions, submitting trade-in appraisals, making ticket payments, and filing or appealing warranty claims are not suspension-checked. Every status flip increments the customer's `version`.

Staff onboarding is the `ShopAdmin`'s exclusive province: a new staff member is registered with a `full_name`, a `staff_role` of `FITTING_SPECIALIST`, `REPAIR_TECHNICIAN`, `INSTRUCTOR`, or `SHOP_MANAGER`, and an `active` flag defaulting to true; the flag is recorded on the staff record but is not enforced by any endpoint — an inactive staff member may still be assigned to new work. Staff records are readable by `ShopAdmin` and `ShopManager`.

Launch-monitor bays are the shop's scarce rooms. A `ShopManager` or `ShopAdmin` registers a bay with a `bay_name` that must be unique and an optional `cleanup_buffer_minutes`, defaulting to 15, which sets the mandatory gap between consecutive sessions on that bay. Bays are born `AVAILABLE`; a `ShopManager` toggles a bay to `MAINTENANCE` and back by setting its `target_status`, each flip incrementing the bay's `version`. A bay in `MAINTENANCE` refuses check-ins — attempting to check a session in while its bay is under maintenance is rejected with `ERR_BAY_UNAVAILABLE` (HTTP 409).

### 3.2. Lesson Packages and Fitting Sessions

A `ShopManager` sells a lesson package to a customer by supplying the `customer_id`, a `total_credits` of at least one, a `price_cents`, and an `expires_at` instant after which the package dies; `price_cents` may be any integer — no minimum is enforced — and `expires_at` is not required to lie in the future. Packages are born `ACTIVE` with `credits_used` at zero. Two system-driven transitions govern a package's life: when credit consumption pushes `credits_used` to equal `total_credits`, the package flips from `ACTIVE` to `EXHAUSTED`; when an early cancellation refunds a credit so that `credits_used` falls below `total_credits` again, an `EXHAUSTED` package flips back to `ACTIVE`. Either state — `ACTIVE` or `EXHAUSTED` — is swept to terminal `EXPIRED` once the logical clock passes `expires_at`. Instructors, managers, and the owning customer may read packages, and the package list accepts a `customer_id` filter alongside pagination.

Fitting sessions bind a customer, a bay, and a specialist into a time interval. A `Customer` or a `FittingSpecialist` books a session with `customer_id`, `bay_id`, `specialist_id`, `starts_at`, and `ends_at`, plus an optional `lesson_package_id`. The interval must be well-formed — `starts_at` strictly earlier than `ends_at` — or the booking fails shape validation. Booking then runs two overlap checks against existing sessions on the same resource that are in `BOOKED` or `CHECKED_IN`; sessions in `CANCELLED`, `NO_SHOW`, or `COMPLETED` never conflict. The bay check is buffered and half-open: a new session conflicts with an existing one unless the new `ends_at` is no later than the existing `starts_at` minus the bay's `cleanup_buffer_minutes`, or the new `starts_at` is no earlier than the existing `ends_at` plus that buffer — so a gap of exactly the buffer's minutes is allowed, and anything tighter is rejected with `ERR_BAY_TIME_CONFLICT` (HTTP 409). The specialist check, evaluated only after the bay check passes, is a closed interval with no buffer: any overlap at all between the intervals is a conflict, and adjacency — one session ending exactly when the next begins — counts as an overlap, rejected with `ERR_SPECIALIST_TIME_CONFLICT` (HTTP 409). Booking does not consult the bay's status — a session may be booked onto a bay in `MAINTENANCE`, and only check-in refuses it. The `specialist_id` must reference an existing staff member, but neither the member's `staff_role` nor the `active` flag is checked. A lesson package named on a booking is not required to belong to the session's customer: any existing, non-expired package with remaining credits may be consumed.

A booking may draw on a lesson package. When `lesson_package_id` is supplied, the package must not be `EXPIRED` — a booking that tries to consume an expired package is rejected with `ERR_PACKAGE_NOT_ACTIVE` (HTTP 409) — and its `credits_used` must still be below `total_credits`, or the booking is rejected with `ERR_NO_CREDITS_REMAINING` (HTTP 422). On success the booking consumes exactly one credit: the package's `credits_used` increments by one (flipping the package to `EXHAUSTED` if that reaches the total), and the session's `credit_consumed` flag is set true. Every session is born `BOOKED`.

From `BOOKED`, a `FittingSpecialist` checks the customer in — moving the session to `CHECKED_IN`, provided the bay is `AVAILABLE`, with the `BOOKED` state guard evaluated before the bay-availability check — and later completes the session from `CHECKED_IN` to `COMPLETED`. Check-in or cancellation attempted on a session no longer in `BOOKED` is rejected with `ERR_SESSION_NOT_BOOKED`; completion attempted on a session not in `CHECKED_IN` is rejected with `ERR_SESSION_NOT_CHECKED_IN`. Cancellation deserves its own paragraph. The owning customer, a `FittingSpecialist`, or a `ShopManager` may cancel a `BOOKED` session. If the booking consumed a package credit and the cancellation lands at least 24 hours before `starts_at` — the threshold is inclusive, so exactly 24 hours qualifies — the credit is refunded: the package's `credits_used` decrements by one, the session's `credit_refunded` flag is set true, and a package that was `EXHAUSTED` flips back to `ACTIVE` — a refund into a package already swept to `EXPIRED` still decrements `credits_used` but does not revive the package. Cancel inside that window and the credit is simply forfeited; the package is untouched and no refund flag is set. A session whose `ends_at` passes with no check-in is swept by the clock to `NO_SHOW`, and its consumed credit is likewise forfeited. Sessions can be listed with `customer_id`, `bay_id`, `specialist_id`, `lesson_package_id`, and `status` filters, and read singly by any role.

### 3.3. Component Inventory and the Allocation Sweep

The shop's buildable universe is its component wall. A `ShopManager` or `ShopAdmin` registers each component item with a unique `sku`, a `component_type` of `HEAD`, `SHAFT`, or `GRIP`, the shop's acquisition `unit_cost_cents`, the list `msrp_cents`, and an `initial_stock` — the three numeric fields need only be integers; no lower bound is enforced. Registration seeds the counters of Section 2.9: both `stock_on_hand` and `received_total` start at `initial_stock`, while `stock_reserved` and `consumed_total` start at zero. Later supplier deliveries are recorded by a `ShopManager` as a receipt of `qty` units, which adds `qty` to both `stock_on_hand` and `received_total` and increments the item's `version`. Items are readable and listable by `ShopManager`, `FittingSpecialist`, and `RepairTechnician`, with a `component_type` filter on the list.

Component orders are never created directly. Each one is born as a side effect of a customer approving a build spec, carrying the `build_spec_id` of its parent and a `lines` array of exactly three entries — one per component slot — each naming a `component_item_id`, a `required_qty` of one, and an `allocated_qty` that starts at zero; the order's `required_units` is therefore always three. Managers and specialists discover these cascade-created orders through the order read and list endpoints, the latter filterable by `build_spec_id` and `status`.

The allocation sweep is the stock engine, and it runs on three occasions: when a component order is created, when a receipt lands, and when any reservation is released. The sweep considers only orders in `PENDING_ALLOCATION` or `BACKORDERED` — orders that are `ALLOCATED`, `CLOSED`, or `CANCELLED` never re-enter — and processes them oldest first by `created_at`, with exact timestamp ties broken by `required_units` ascending, never by id. For each candidate order it walks the lines and allocates the smaller of the line's remaining requirement and the item's current `stock_on_hand`, moving each allocated unit from `stock_on_hand` to `stock_reserved` and adding it to the line's `allocated_qty`. An order whose every line is fully satisfied flips to `ALLOCATED`, and its parent spec advances from `ORDERED` to `IN_BUILD`; an order with at least one short line becomes `BACKORDERED` and keeps its partial allocations, with the remainders pending. When a later stock event finally satisfies a backordered order's remainders, the same per-line stock mutations complete and the order flips `BACKORDERED` to `ALLOCATED` with the same parent-spec advance. Allocation is also unwound in two ways: marking the parent spec ready turns an `ALLOCATED` order `CLOSED` by consuming its reserved units, and cancelling the parent spec turns an order in `PENDING_ALLOCATION`, `BACKORDERED`, or `ALLOCATED` to `CANCELLED`, releasing its allocated units back to `stock_on_hand`.

### 3.4. The Custom Build Pipeline

A custom build begins on paper. A `FittingSpecialist` drafts a build spec out of a fitting session, supplying `customer_id`, the originating `fitting_session_id`, the three component choices `head_item_id`, `shaft_item_id`, and `grip_item_id`, the playing dimensions `length_inches`, `loft_deg`, and `lie_deg`, and a flat `labor_cents` charge for the assembly work. Each component choice must actually be what its slot claims — the head a `HEAD`, the shaft a `SHAFT`, the grip a `GRIP` — or creation fails with `ERR_COMPONENT_TYPE_MISMATCH` (HTTP 400). Specs are born `DRAFT` with both price fields empty: `provisional_quote_cents` stays null until the first quote, and `final_price_cents` stays null until approval.

Quoting is the specialist's iterative loop. Quoting a `DRAFT` spec moves it to `QUOTED`; quoting an already-`QUOTED` spec keeps it in `QUOTED` and supersedes the prior quote. Quoting a spec in any other state — `ORDERED`, `IN_BUILD`, `READY`, `DELIVERED`, or `CANCELLED` — is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Both forms are guarded by the `expected_build_spec_version` check of Section 2.7, and each successful quote increments the spec's `version` by one. The provisional quote is an MSRP-based figure meant for the showroom floor. Sum the `msrp_cents` of the head, shaft, and grip — the components' stock state is irrelevant to pricing. That sum selects a tier rate: ten percent when the sum is at least 500,000 cents, otherwise five percent when it is at least 200,000 cents, otherwise nothing. A loyalty rate of five percent is added when the customer's `completed_builds_count` at quote time is at least two. The combined discount rate is capped at fifteen percent — the discount rate is the smaller of the tier-plus-loyalty sum and the cap. The discount itself is the sum multiplied by that rate, rounded half-up to integer cents, and this rounding is applied exactly once, to the discount alone. The quoted `provisional_quote_cents` is then the MSRP sum minus the discount plus `labor_cents`.

Approval belongs to the customer. Approving a spec that is not in `QUOTED` is rejected with `ERR_SPEC_NOT_QUOTED`; approving while `SUSPENDED` is rejected with `ERR_CUSTOMER_SUSPENDED`. The approval request names a `payment_method` of `CREDIT` or `EXTERNAL`. Approval is the moment the real price crystallizes, and its evaluation order is pinned so that the circular-looking dependency between the rebate and the discount never materializes. First, the component cost basis is the sum of the three items' `unit_cost_cents`, locked at the approval instant. Second, the tier is selected on that cost sum before any rebate: ten percent at or above 500,000 cents, five percent at or above 200,000 cents, otherwise zero. Third, the same loyalty rule as the provisional quote applies and the combined rate is capped at fifteen percent. Fourth, the discount is the cost sum times that rate, rounded half-up once. Fifth, a fitting-fee rebate of 7,500 cents is granted when the linked fitting session has reached `COMPLETED`, and is zero otherwise; the rebate never influences tier selection. Finally, `final_price_cents` is the cost sum minus the discount, plus `labor_cents`, minus the rebate, floored at zero — a negative result becomes zero. Note that the provisional and final variants use different bases, so identical spec inputs generally produce different totals at quote time and at approval time.

One approval triggers a cascade, all atomically within the request. A component order is created in `PENDING_ALLOCATION` with its three lines, and the allocation sweep of Section 3.3 runs immediately; if the sweep fully allocates the order, the spec advances from `ORDERED` to `IN_BUILD` in the same request, and any later stock event that completes a shortfall drives the same advance. If `payment_method` is `CREDIT`, the customer's `credit_balance_cents` must cover the resulting `final_price_cents` or approval fails with `ERR_INSUFFICIENT_CREDIT` (HTTP 402); on success a ledger entry of negative `final_price_cents` with reason `BUILD_PAYMENT` is written and the balance recomputed. Approval increments the spec's `version`.

From the bench side, a `RepairTechnician` marks an `IN_BUILD` spec ready — anything else earns `ERR_SPEC_NOT_IN_BUILD` — which closes the component order: the order flips from `ALLOCATED` to `CLOSED` and each line's allocated units are consumed, moving from `stock_reserved` into `consumed_total`. Delivery is the customer-facing finale: a `FittingSpecialist` or `ShopManager` delivers a `READY` spec — anything else earns `ERR_SPEC_NOT_READY` — stamping `delivered_at` from the logical clock as the warranty anchor and incrementing the customer's `completed_builds_count` by one.

Cancellation can strike anywhere before the terminal states. The owning customer or a `FittingSpecialist` may cancel a spec in `DRAFT`, `QUOTED`, `ORDERED`, or `IN_BUILD`; cancellation attempted from `READY`, `DELIVERED`, or `CANCELLED` is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). The cancellation unwinds everything: the component order — whether `PENDING_ALLOCATION`, `BACKORDERED`, or `ALLOCATED` — flips to `CANCELLED`, its allocated units are released from `stock_reserved` back to `stock_on_hand`, and that release immediately re-runs the allocation sweep over the remaining `BACKORDERED` and `PENDING_ALLOCATION` orders, so a cancelled build can unblock someone else's. If the spec had been paid by `CREDIT`, a ledger entry of positive `final_price_cents` with reason `BUILD_REFUND` restores the customer's balance. Specs are readable and listable by `ShopManager`, `FittingSpecialist`, and the owning `Customer`, with filters for `customer_id`, `fitting_session_id`, `status`, `head_item_id`, `shaft_item_id`, and `grip_item_id`.

### 3.5. Repair Tickets from Quote to Pickup

The repair bench handles three services, spelled `REGRIP`, `RESHAFT`, and `LOFT_LIE_ADJUST`. A `Customer` or a `RepairTechnician` opens a ticket with the `customer_id`, a free-text `club_description`, the `service_type`, an optional `rush` flag defaulting to false, and — for reshafts only — a `shaft_item_id`. A `RESHAFT` ticket without a `shaft_item_id`, or with one pointing at an item whose `component_type` is not `SHAFT`, is rejected with `ERR_RESHAFT_REQUIRES_SHAFT_ITEM` (HTTP 400); the other two service types carry no component requirement — a `shaft_item_id` supplied on a `REGRIP` or `LOFT_LIE_ADJUST` ticket is accepted without the `SHAFT`-type check and stored, and from then on drives exactly the same stock reservation, consumption, and release rules as a reshaft's shaft.

A ticket is born `QUOTED` with its commercial terms already computed. The base price is 1,800 cents for a regrip, 6,500 cents for a reshaft, and 2,500 cents for a loft-and-lie adjustment. Rush work adds a rush fee of the greater of 1,500 cents and thirty-five percent of the base price rounded half-up; standard work adds nothing. The `quoted_total_cents` is the base plus the rush fee — notably, the replacement shaft's price is not part of the quote, since parts are handled through the stock reservation. The `promised_at` commitment is `created_at` plus 24 hours for rush work or plus 72 hours for standard work. The `deposit_cents` is half of the quoted total, rounded half-up, and the eventual balance payment is exactly the remainder, keeping cents exact even on odd totals.

Work on a ticket and money on a ticket are parallel dimensions that evolve independently except where one gates the other. The payment dimension runs `UNPAID` to `DEPOSIT_PAID` to `PAID`, with `REFUNDED` as the terminal refund state. The owning customer records a payment with a `kind` of `DEPOSIT` or `BALANCE` and a `method` of `CREDIT` or `EXTERNAL`; any other value fails shape validation. Sequence is strict: a `DEPOSIT` payment is accepted only while `UNPAID`, a `BALANCE` payment only while `DEPOSIT_PAID`, and any payment at all while `PAID` or `REFUNDED` is rejected — each sequencing violation earns `ERR_PAYMENT_SEQUENCE` (HTTP 409). Payments are also refused outright when the ticket's `work_status` is anything other than `QUOTED`, `APPROVED`, `IN_PROGRESS`, or `READY`, surfacing `ERR_INVALID_STATE_TRANSITION` (HTTP 409). When `method` is `CREDIT`, the deposit draws against store credit — the balance must cover `deposit_cents` or the payment fails with `ERR_INSUFFICIENT_CREDIT` — and writes a ledger entry of negative `deposit_cents` with reason `TICKET_PAYMENT`; the balance payment likewise requires credit covering `quoted_total_cents` minus `deposit_cents` and writes the corresponding negative entry. Payments by `EXTERNAL` write no ledger entry.

The work dimension begins when the owning customer approves the quote — a ticket not in `QUOTED` earns `ERR_TICKET_NOT_QUOTED`, and a suspended customer earns `ERR_CUSTOMER_SUSPENDED` — moving it to `APPROVED`. A `RepairTechnician` then starts work, moving `APPROVED` to `IN_PROGRESS`; calling start-work on a ticket not in `APPROVED` earns `ERR_TICKET_NOT_APPROVED`. Two gates guard the bench. The deposit must be in: starting work while `payment_status` is still `UNPAID` is rejected with `ERR_DEPOSIT_REQUIRED` (HTTP 422). And for a reshaft, the chosen shaft must physically exist on the wall: if `shaft_item_id` is present and its `stock_on_hand` is below one, start-work fails with `ERR_COMPONENT_SHORTAGE` (HTTP 409). A successful start-work on a reshaft reserves the shaft — one unit moves from `stock_on_hand` to `stock_reserved`.

Quality control closes the loop. The technician submits a QC outcome with `passed`. A pass moves the ticket from `IN_PROGRESS` to `READY` and, for reshafts, consumes the reserved shaft — `stock_reserved` drops by one and `consumed_total` grows by one. A failure keeps the ticket in `IN_PROGRESS` in a rework loop and increments `rework_count` by one; there is no cap on rework. Submitting QC on a ticket not in `IN_PROGRESS` earns `ERR_TICKET_NOT_IN_PROGRESS`. Pickup is the customer's exit: the owning customer or a technician moves `READY` to `PICKED_UP`, but only when the ticket is fully paid — pickup while `payment_status` is anything but `PAID` is rejected with `ERR_TICKET_UNPAID` (HTTP 422), and pickup on a ticket not in `READY` earns `ERR_TICKET_NOT_READY`. A successful pickup stamps `picked_up_at` from the logical clock as the warranty anchor for repairs.

Cancellation unwinds the bench. The owning customer or a technician may cancel from `QUOTED`, `APPROVED`, or `IN_PROGRESS`; cancellation attempted from any other state — including `READY`, `PICKED_UP`, or `CANCELLED` — is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Money paid by `CREDIT` comes back: if `payment_status` is `DEPOSIT_PAID` or `PAID`, a ledger entry of the positive total amount paid by `CREDIT` — and only that amount, since payments made by `EXTERNAL` are not returned through the ledger — is written with reason `TICKET_REFUND`, and `payment_status` flips to `REFUNDED` regardless of how the money was paid; if nothing was paid by `CREDIT`, no ledger entry is written. A held shaft reservation — a ticket cancelled from `IN_PROGRESS` with a `shaft_item_id` — is released: `stock_reserved` drops by one, `stock_on_hand` rises by one, and the release triggers the allocation sweep over backordered and pending component orders, so a cancelled reshaft can unblock a waiting build. Tickets are readable and listable by the owning customer, technicians, and managers, with `customer_id`, `status`, and `shaft_item_id` filters, where the `status` filter matches a ticket when either its `work_status` or its `payment_status` equals the supplied value.

### 3.6. Trade-Ins and the Used-Club Showcase

A customer turns old clubs into store credit through the trade-in desk. The owning customer submits an appraisal with their `customer_id` and a non-empty `clubs` array, each entry naming a `club_type` of `DRIVER`, `FAIRWAY`, `HYBRID`, `IRON_SET`, `WEDGE`, or `PUTTER` and a `condition_grade` of `A`, `B`, `C`, or `D`. Appraisals are born `SUBMITTED`, with `offer_basis`, `offered_value_cents`, `offer_expires_at`, and `offered_by_staff_id` all empty until the first offer.

Offers are written by a `FittingSpecialist` or a `ShopManager`, and the offer pen is deliberately light: an offer may be issued while the appraisal is `SUBMITTED`, `OFFERED`, or even `DECLINED`, and each new offer supersedes whatever came before. The offer request names a `basis` — `GRADE_MATRIX` or `MARKET_COMP` — carries the `expected_appraisal_version` guard of Section 2.7, and, for market-comparison offers, a `market_comps_cents` array with exactly one entry per club in the lot, every entry an integer number of cents; a `MARKET_COMP` offer without per-club integer comparables is rejected with `ERR_VALIDATION`. An offer attempted on an appraisal in `ACCEPTED` or `EXPIRED` is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Valuation differs by basis but shares one pinned rounding order: every club's line is rounded half-up to integer cents individually, and the rounded lines are then summed — never the reverse. Under `GRADE_MATRIX`, each club's line is its book value multiplied by its grade multiplier: book values are 29,999 cents for a driver, 21,999 for a fairway wood, 17,999 for a hybrid, 44,999 for an iron set, 8,999 for a wedge, and 14,999 for a putter; multipliers are sixty percent for grade `A`, forty-five for `B`, thirty for `C`, and fifteen for `D`. Under `MARKET_COMP`, each club's line is its supplied comparable multiplied by eighty percent. The same clubs will generally produce different totals under the two bases. Whichever basis is used, the resulting `offered_value_cents` is stored, `offer_basis` and `offered_by_staff_id` — the latter taken from the acting staff member's `X-User-ID` — are recorded, `offer_expires_at` is set to the offer instant plus 168 hours, and the appraisal moves to `OFFERED` with its `version` incremented. An offer left unanswered past `offer_expires_at` is swept by the clock to `EXPIRED`.

The customer answers from `OFFERED` — accept or decline attempted in any other state earns `ERR_APPRAISAL_NOT_OFFERED`. Declining moves the appraisal to `DECLINED`, a resting state from which a fresh offer can still revive it. Accepting moves it to terminal `ACCEPTED` and fires the commercial cascade in one request: a ledger entry of positive `offered_value_cents` with reason `TRADE_IN_ACCEPT` grants the store credit and recomputes the customer's balance, and a used-club listing is created in `LISTED` with its `appraisal_id` pointing at the source appraisal, its `appraised_by_staff_id` copied from the appraisal's `offered_by_staff_id` — this copy is the segregation-of-duties anchor — and its `list_price_cents` initialized to the offered value multiplied by 1.4, rounded half-up.

The showcase sells itself, with guardrails. Reservation and purchase both first require the acting `X-User-ID` to resolve to a registered customer — an unknown id earns `ERR_CUSTOMER_NOT_FOUND` — and to be `ACTIVE`, with this standing check evaluated before the listing's state guard, so a suspended caller earns `ERR_CUSTOMER_SUSPENDED` even when the listing is not `LISTED`. Any `ACTIVE` customer may then reserve a `LISTED` listing — reserving anything not `LISTED` earns `ERR_LISTING_NOT_LISTED` — which sets `reserved_by_customer_id` to the acting customer's `X-User-ID` and `reserved_until` to the reserve instant plus 24 hours. If the clock sweeps past `reserved_until` with no purchase, the listing falls back to `LISTED` and both reservation fields are cleared. Purchase has two doors. Any `ACTIVE` customer may buy a `LISTED` listing outright, moving it to terminal `SOLD`. A `RESERVED` listing can be bought only by the customer holding the reservation; anyone else's purchase attempt is rejected with `ERR_LISTING_RESERVED_BY_OTHER` (HTTP 409), while the reserving customer's purchase completes the same `SOLD` transition. A purchase attempted on a listing in any other state is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), and a `SOLD` listing retains its `reserved_by_customer_id` and `reserved_until` values as last recorded. Price management belongs to a `ShopManager`, who may set a `LISTED` listing's `list_price_cents` to a supplied `new_price_cents` — but never the manager who appraised it: if the acting staff member's id equals the listing's `appraised_by_staff_id`, the adjustment is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Listings are publicly readable and listable by every role, with filters for `appraisal_id`, `status`, `reserved_by_customer_id`, and `appraised_by_staff_id`; appraisals themselves are readable and listable by the owning customer, fitting specialists, and managers, with `customer_id`, `status`, and `offered_by_staff_id` filters.

### 3.7. Warranty Claims and the Appeal Loop

Delivered builds and picked-up repairs carry warranty coverage measured from their anchors — `delivered_at` for a spec, `picked_up_at` for a ticket. The owning customer files a claim with a `description` and exactly one subject: a `build_spec_id` or a `repair_ticket_id`, never both and never neither — violating that exclusive-or fails shape validation. The claim's `customer_id` is copied from the subject's owner. Two gates guard filing. The subject must be claimable — the spec in `DELIVERED` or the ticket in `PICKED_UP` — or the filing is rejected with `ERR_SUBJECT_NOT_CLAIMABLE` (HTTP 409). And the subject must not already carry an open claim: if a claim in `SUBMITTED` or `APPROVED` exists for the same subject, the new filing is rejected with `ERR_DUPLICATE_CLAIM` (HTTP 409).

Coverage is computed at filing and never recomputed. The subject's age in days is the number of whole days elapsed between its anchor instant and the current logical time. For a build spec, coverage is one hundred percent when the age is at most 90 days, fifty percent when the age is at most 365 days, and nothing beyond that — filing against a spec older than 365 days is rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422). For a repair ticket, coverage is one hundred percent when the age is at most 30 days and nothing beyond — an older ticket earns the same `ERR_CLAIM_WINDOW_EXPIRED`. Boundaries are inclusive: exactly 90 days yields full coverage on a spec, and exactly 30 days yields full coverage on a ticket. The resulting `coverage_pct` is 0, 50, or 100, and `covered_estimate_cents` is the subject's price — `final_price_cents` for a spec, `quoted_total_cents` for a ticket — multiplied by the coverage percentage and divided by one hundred, rounded half-up.

Claims are born `SUBMITTED`. A `ShopManager` decides — a decision attempted on a claim not in `SUBMITTED` earns `ERR_CLAIM_NOT_SUBMITTED`. A `decision` of `APPROVED` moves the claim to `APPROVED`; a `decision` of `DENIED` requires a `denial_reason` — omitting it fails with `ERR_VALIDATION` — records the reason, and moves the claim to `DENIED`. Resolution pays out: a manager resolves an `APPROVED` claim — anything else earns `ERR_CLAIM_NOT_APPROVED` — writing a ledger entry of positive `covered_estimate_cents` with reason `WARRANTY_RESOLUTION` and recomputing the customer's balance, landing the claim in terminal `RESOLVED`. Denial is not the end of the road: the owning customer may appeal a `DENIED` claim — appealing from any other state earns `ERR_CLAIM_NOT_DENIED` — which returns it to `SUBMITTED`, increments `appeal_count` by one, and clears the recorded `denial_reason`. The appeal loop is hard-capped: appealing when `appeal_count` has already reached 2 is rejected with `ERR_APPEAL_LIMIT_REACHED` (HTTP 422). Claims are readable and listable by the owning customer and managers, with `build_spec_id`, `repair_ticket_id`, `customer_id`, and `status` filters.

## 4. Endpoint Definitions

All endpoints are mounted under `/golf-shop`. Creation of a new resource returns HTTP 201 with the created resource; reads, modifications, and state transitions return HTTP 200 with the affected resource (or, for list endpoints, an array). The request and response shapes of each endpoint are defined by the workflows in Section 3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /golf-shop/customers | Register a customer | ShopAdmin, ShopManager |
| GET | /golf-shop/customers/{id} | Read a customer including computed credit balance | ShopAdmin, ShopManager, FittingSpecialist, RepairTechnician, Instructor, Customer |
| POST | /golf-shop/customers/{id}/set-status | Suspend or reactivate a customer | ShopManager |
| POST | /golf-shop/staff | Onboard a staff member | ShopAdmin |
| GET | /golf-shop/staff/{id} | Read a staff member | ShopAdmin, ShopManager |
| POST | /golf-shop/launch-monitor-bays | Register a launch-monitor bay | ShopManager, ShopAdmin |
| GET | /golf-shop/launch-monitor-bays/{id} | Read a bay | ShopAdmin, ShopManager, FittingSpecialist, RepairTechnician, Instructor |
| POST | /golf-shop/launch-monitor-bays/{id}/set-status | Toggle bay between AVAILABLE and MAINTENANCE | ShopManager |
| POST | /golf-shop/fitting-sessions | Book a fitting session, optionally consuming a lesson-package credit | FittingSpecialist, Customer |
| GET | /golf-shop/fitting-sessions/{id} | Read a fitting session | ShopAdmin, ShopManager, FittingSpecialist, RepairTechnician, Instructor, Customer |
| GET | /golf-shop/fitting-sessions | List fitting sessions with filters and pagination | ShopAdmin, ShopManager, FittingSpecialist, RepairTechnician, Instructor, Customer |
| POST | /golf-shop/fitting-sessions/{id}/check-in | BOOKED to CHECKED_IN | FittingSpecialist |
| POST | /golf-shop/fitting-sessions/{id}/complete | CHECKED_IN to COMPLETED | FittingSpecialist |
| POST | /golf-shop/fitting-sessions/{id}/cancel | BOOKED to CANCELLED; lesson credit refunded iff cancellation is at least 24h before start | Customer, FittingSpecialist, ShopManager |
| POST | /golf-shop/lesson-packages | Sell a lesson package | ShopManager |
| GET | /golf-shop/lesson-packages/{id} | Read a lesson package | ShopManager, Instructor, Customer |
| GET | /golf-shop/lesson-packages | List lesson packages | ShopManager, Instructor, Customer |
| POST | /golf-shop/build-specs | Create a build spec from a fitting session | FittingSpecialist |
| GET | /golf-shop/build-specs/{id} | Read a build spec | ShopManager, FittingSpecialist, Customer |
| GET | /golf-shop/build-specs | List build specs | ShopManager, FittingSpecialist, Customer |
| POST | /golf-shop/build-specs/{id}/quote | DRAFT to QUOTED, or QUOTED to QUOTED re-quote superseding the prior quote; OCC-guarded | FittingSpecialist |
| POST | /golf-shop/build-specs/{id}/approve | QUOTED to ORDERED; computes final price, creates the component order, runs the allocation sweep, takes CREDIT payment | Customer |
| POST | /golf-shop/build-specs/{id}/cancel | DRAFT, QUOTED, ORDERED, or IN_BUILD to CANCELLED; releases allocations and refunds CREDIT payment | Customer, FittingSpecialist |
| POST | /golf-shop/build-specs/{id}/mark-ready | IN_BUILD to READY; consumes reserved components | RepairTechnician |
| POST | /golf-shop/build-specs/{id}/deliver | READY to DELIVERED; anchors the warranty clock | FittingSpecialist, ShopManager |
| POST | /golf-shop/component-items | Register a component item with initial stock | ShopManager, ShopAdmin |
| GET | /golf-shop/component-items/{id} | Read a component item | ShopManager, FittingSpecialist, RepairTechnician |
| GET | /golf-shop/component-items | List component items | ShopManager, FittingSpecialist, RepairTechnician |
| POST | /golf-shop/component-items/{id}/receive | Record a supplier stock receipt; triggers the allocation sweep | ShopManager |
| GET | /golf-shop/component-orders/{id} | Read a component order | ShopManager, FittingSpecialist |
| GET | /golf-shop/component-orders | List component orders (discovery channel for cascade-created orders) | ShopManager, FittingSpecialist |
| POST | /golf-shop/repair-tickets | Open a regrip/reshaft/adjustment ticket; born QUOTED with computed price and promise time | Customer, RepairTechnician |
| GET | /golf-shop/repair-tickets/{id} | Read a repair ticket | Customer, RepairTechnician, ShopManager |
| GET | /golf-shop/repair-tickets | List repair tickets | Customer, RepairTechnician, ShopManager |
| POST | /golf-shop/repair-tickets/{id}/approve | QUOTED to APPROVED | Customer |
| POST | /golf-shop/repair-tickets/{id}/start-work | APPROVED to IN_PROGRESS; requires deposit; reserves shaft stock for reshafts | RepairTechnician |
| POST | /golf-shop/repair-tickets/{id}/submit-qc | passed true: IN_PROGRESS to READY (consumes shaft); passed false: rework self-loop | RepairTechnician |
| POST | /golf-shop/repair-tickets/{id}/pickup | READY to PICKED_UP; requires payment in full | Customer, RepairTechnician |
| POST | /golf-shop/repair-tickets/{id}/cancel | QUOTED, APPROVED, or IN_PROGRESS to CANCELLED; refunds CREDIT payments and releases shaft reservation | Customer, RepairTechnician |
| POST | /golf-shop/repair-tickets/{id}/payments | UNPAID to DEPOSIT_PAID to PAID; DEPOSIT then BALANCE; CREDIT draws store credit | Customer |
| POST | /golf-shop/trade-in-appraisals | Submit a trade-in lot for appraisal | Customer |
| GET | /golf-shop/trade-in-appraisals/{id} | Read an appraisal | Customer, FittingSpecialist, ShopManager |
| GET | /golf-shop/trade-in-appraisals | List appraisals | Customer, FittingSpecialist, ShopManager |
| POST | /golf-shop/trade-in-appraisals/{id}/offers | Issue or supersede an offer from SUBMITTED, OFFERED, or DECLINED; OCC-guarded | FittingSpecialist, ShopManager |
| POST | /golf-shop/trade-in-appraisals/{id}/accept | OFFERED to ACCEPTED; grants store credit and creates a used-club listing | Customer |
| POST | /golf-shop/trade-in-appraisals/{id}/decline | OFFERED to DECLINED | Customer |
| GET | /golf-shop/used-club-listings/{id} | Read a listing | ShopAdmin, ShopManager, FittingSpecialist, RepairTechnician, Instructor, Customer |
| GET | /golf-shop/used-club-listings | List listings (discovery channel for cascade-created listings) | ShopAdmin, ShopManager, FittingSpecialist, RepairTechnician, Instructor, Customer |
| POST | /golf-shop/used-club-listings/{id}/reserve | LISTED to RESERVED for the acting customer for 24 hours | Customer |
| POST | /golf-shop/used-club-listings/{id}/purchase | LISTED to SOLD directly, or RESERVED to SOLD by the reserving customer | Customer |
| POST | /golf-shop/used-club-listings/{id}/adjust-price | Adjust list price; forbidden for the appraising staff member | ShopManager |
| POST | /golf-shop/warranty-claims | File a warranty claim against a DELIVERED build spec or PICKED_UP repair ticket | Customer |
| GET | /golf-shop/warranty-claims/{id} | Read a warranty claim | Customer, ShopManager |
| GET | /golf-shop/warranty-claims | List warranty claims | Customer, ShopManager |
| POST | /golf-shop/warranty-claims/{id}/decide | SUBMITTED to APPROVED or DENIED | ShopManager |
| POST | /golf-shop/warranty-claims/{id}/resolve | APPROVED to RESOLVED; grants the covered estimate as store credit | ShopManager |
| POST | /golf-shop/warranty-claims/{id}/appeal | DENIED to SUBMITTED; appeal count capped at 2 | Customer |
| GET | /golf-shop/customers/{id}/credit-ledger-entries | List the append-only credit ledger for a customer | Customer, ShopManager |
| POST | /golf-shop/_clock/set_current_utc | Set the server's logical clock and run all time-based sweeps | ShopAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of Sections 2 and 3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_VALIDATION | 400 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_STAFF_NOT_FOUND | 404 |
| ERR_BAY_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_PACKAGE_NOT_FOUND | 404 |
| ERR_SPEC_NOT_FOUND | 404 |
| ERR_COMPONENT_ITEM_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_TICKET_NOT_FOUND | 404 |
| ERR_APPRAISAL_NOT_FOUND | 404 |
| ERR_LISTING_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_SPEC_NOT_QUOTED | 409 |
| ERR_SPEC_NOT_IN_BUILD | 409 |
| ERR_SPEC_NOT_READY | 409 |
| ERR_SESSION_NOT_BOOKED | 409 |
| ERR_SESSION_NOT_CHECKED_IN | 409 |
| ERR_TICKET_NOT_QUOTED | 409 |
| ERR_TICKET_NOT_APPROVED | 409 |
| ERR_TICKET_NOT_IN_PROGRESS | 409 |
| ERR_TICKET_NOT_READY | 409 |
| ERR_APPRAISAL_NOT_OFFERED | 409 |
| ERR_LISTING_NOT_LISTED | 409 |
| ERR_LISTING_RESERVED_BY_OTHER | 409 |
| ERR_CLAIM_NOT_SUBMITTED | 409 |
| ERR_CLAIM_NOT_APPROVED | 409 |
| ERR_CLAIM_NOT_DENIED | 409 |
| ERR_SUBJECT_NOT_CLAIMABLE | 409 |
| ERR_PACKAGE_NOT_ACTIVE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_BAY_UNAVAILABLE | 409 |
| ERR_BAY_TIME_CONFLICT | 409 |
| ERR_SPECIALIST_TIME_CONFLICT | 409 |
| ERR_CLAIM_WINDOW_EXPIRED | 422 |
| ERR_CUSTOMER_SUSPENDED | 409 |
| ERR_INSUFFICIENT_CREDIT | 402 |
| ERR_NO_CREDITS_REMAINING | 422 |
| ERR_DEPOSIT_REQUIRED | 422 |
| ERR_PAYMENT_SEQUENCE | 409 |
| ERR_TICKET_UNPAID | 422 |
| ERR_RESHAFT_REQUIRES_SHAFT_ITEM | 400 |
| ERR_COMPONENT_TYPE_MISMATCH | 400 |
| ERR_COMPONENT_SHORTAGE | 409 |
| ERR_APPEAL_LIMIT_REACHED | 422 |
| ERR_DUPLICATE_CLAIM | 409 |
