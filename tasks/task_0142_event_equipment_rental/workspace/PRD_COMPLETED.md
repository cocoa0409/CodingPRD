# Event Equipment Rental API — Product Requirements Document

## 1. Introduction

Party and event outfitters live or die by the calendar. A twenty-by-twenty tent committed to a Saturday wedding cannot also be on a Sunday corporate picnic if there is only one in the yard, and a linen order that comes back stained has to be cleaned, charged against a deposit, and reconciled before the customer is made whole. This document specifies the Event & Party Equipment Rental API, the system of record that a rental yard uses to publish its catalog (tents, tables, chairs, linens, and bounce houses), guard its inventory against double-booking across overlapping event windows, price multi-day rentals, schedule delivery and pickup runs, hold and settle damage deposits, and absorb weather cancellations without losing money or trust.

The platform serves three distinct audiences whose duties are deliberately segregated. Customers browse the catalog, register the venues where their events will take place, file certificates of insurance, assemble and confirm their own orders, and trigger weather cancellations when a storm rolls in. Yard operators — the rental agents — own the catalog, the delivery crews, the run schedule, the insurance approvals, and the physical hand-off and return of goods. A separate back-office function settles the money: deciding whether a returned order's deposit is released in full or partly forfeited for damage. Because the same person who hands over the goods should never also decide how much of the deposit to keep, deposit settlement is walled off into its own role.

Two ideas run through the entire system and are worth stating up front. First, an order carries **two independent status dimensions** at once: a *booking* lifecycle that tracks the physical journey of the goods, and a *settlement* lifecycle that tracks the money. They advance on different triggers and must never be conflated. Second, every figure the system reports — rental charges, delivery fees, deposits, store credits — is an exact whole-cent integer, computed by pinned, reproducible rules so that a quote previewed today matches the charge applied at confirmation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Separately from authentication and authorization, any request whose body is structurally malformed — a missing required field, a value of the wrong type, or an enumerated field carrying a value outside its permitted set — is rejected with `ERR_VALIDATION` (HTTP 400).

The system recognizes exactly three roles: `Customer`, `RentalAgent`, and `DepositAdjuster`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID`: a `Customer` may act only on venues and orders whose `customer_id` equals their own `X-User-ID`, and any attempt by a customer to mutate an order or venue they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). A `Customer` registers themselves, registers and reads their own venues, submits and reads certificates of insurance for those venues, creates and reads their own orders, edits the lines of their own draft orders, confirms, cancels, and weather-cancels their own orders, reads their own deposit ledgers, and browses the shared catalog, item availability, and posted weather events.

When `X-User-Role` is `RentalAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authentication but does not compare it to any entity's `id`, and a rental agent may act on any customer's orders and venues without an ownership check. The rental agent is the yard operator: they create catalog items and retire them, approve, reject, and revoke certificates of insurance, mark orders fulfilled and returned, create delivery crews, schedule and manage delivery runs, and post weather advisories. Rental agents may also act on a customer's behalf for order creation, line editing, confirmation, cancellation, and weather cancellation. Critically, a rental agent **cannot** settle deposits — that authority is withheld to preserve segregation of duties.

When `X-User-Role` is `DepositAdjuster`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server records the actor for audit but never compares it to any entity's `id`. The deposit adjuster is a back-office function whose sole exclusive power is to settle a held deposit — releasing it in full or forfeiting a portion. Beyond settlement, a deposit adjuster may read orders, deposit ledgers, customers, and the catalog. The role that physically fulfills and returns goods (the rental agent) and the role that decides deposit disposition (the deposit adjuster) are intentionally distinct.

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

List endpoints accept two query parameters to control paging. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless an endpoint explicitly states otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order — that is, by `created_at` from oldest to newest.

Each list response carries the pagination bookkeeping in the `meta` object of the envelope, exposing `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Most resources in the system share a common set of system-managed fields. Every resource carries an `id`: a server-minted UUID used for identity only, with no type prefix. Resources also carry a `created_at` timestamp — an ISO 8601 UTC value with three fractional digits, recorded at creation and never changed afterward.

The principal aggregates — `CatalogItem`, `Customer`, `Venue`, `InsuranceCertificate`, `RentalOrder`, `OrderLine`, `DeliveryRun`, and `Crew` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and a `version` integer used for optimistic concurrency. Two entities are deliberately leaner: a `DepositLedgerEntry` and a `WeatherEvent` are append-only records that carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field, because once written they are never modified.

The `version` on a `RentalOrder` begins at 1 when the order is created and increases by exactly 1 on every mutation of that order, including mutations driven by cascades rather than by a direct client call. Adding or removing a line, confirming, fulfilling, returning, cancelling, weather-cancelling, and settling the deposit each advance the order's `version` by one.

### 2.5. Monetary Precision and Rounding

All money in the system is stored and transmitted as whole-cent integers — there are no fractional cents and no floating-point currency values. Wherever a calculation could produce a fractional cent, the system rounds half up to the nearest whole cent. This rounding is applied at exactly one well-defined point in the rental-pricing calculation (described in §3) and nowhere else; all other monetary results are exact integer sums of already-rounded inputs and are never re-rounded. Store credit balances and held-deposit balances are likewise whole-cent integers and are floored at zero — they are never permitted to go negative.

### 2.6. The Two Status Dimensions of an Order

A `RentalOrder` is governed by two parallel, independent status fields that evolve on different triggers and must be tracked separately.

The `booking_status` dimension follows the physical lifecycle of the goods and takes one of `DRAFT`, `CONFIRMED`, `FULFILLED`, `RETURNED`, or `CANCELLED`. A newly created order begins in `DRAFT`. The terminal booking states are `RETURNED` and `CANCELLED`.

The `settlement_status` dimension follows the money and takes one of `UNSETTLED`, `DEPOSIT_HELD`, `DEPOSIT_RELEASED`, or `DEPOSIT_FORFEITED`. A newly created order begins `UNSETTLED`. The terminal settlement states are `DEPOSIT_RELEASED` and `DEPOSIT_FORFEITED`. The settlement dimension advances both through explicit deposit actions and as a consequence of booking-dimension events; §3 details exactly how the two interlock.

### 2.7. Inventory Holds and Availability

Inventory is finite. Each `CatalogItem` declares the `total_units` the yard physically owns, and the system must never reserve more units of an item than exist across any overlapping rental window. A line holds inventory only once its order is confirmed: at that point the line's `status` becomes `RESERVED` and the order's event window is stamped onto the line as `reserved_window_start` and `reserved_window_end`. While the order is still a draft, these window fields are null and the line holds nothing.

Availability over a queried window is the item's `total_units` minus the number of units already reserved on lines whose reserved window overlaps the queried window. Two day-spans overlap when each begins on or before the other ends; a reservation that ends on the very day another begins is treated as overlapping, since both occupy that shared day. When the units already reserved over the overlapping window plus a new request's `quantity` would exceed the item's `total_units`, the reservation cannot be granted.

An availability read takes the queried `window_start` and `window_end` and reports, for the item identified by `item_id`, the `total_units` the yard owns, the `reserved_units` already committed over the overlapping window, and the resulting `available_units` (the total minus the reserved).

### 2.8. Delivery Crews and Window Discipline

Delivery runs are executed by crews, and a crew can only be in one place at a time. Each `Crew` declares a `turnaround_minutes` buffer — the minimum gap it needs between finishing one run and starting the next. When a run is scheduled or rescheduled onto a crew, its `window_start` (inclusive) through `window_end` (exclusive) must not collide with any other non-`CANCELLED` run already assigned to that same crew, where a collision means the two windows overlap or are separated by less than the crew's turnaround buffer. A `window_start` opens the window inclusively and a `window_end` closes it exclusively. A scheduling attempt that violates this discipline is rejected; the rule is stated in detail in §3.

### 2.9. Certificate of Insurance and Venue Coverage

Some equipment — specifically tents and bounce houses — may not be confirmed for delivery to a venue unless that venue carries valid liability insurance covering the event. A `Venue` exposes a computed `coi_status` of `NONE`, `PENDING`, `VALID`, or `EXPIRED`, derived from the certificates of insurance on file for that venue and the window in question. §3 specifies precisely how coverage is evaluated against an event window and how certificate decisions recompute this status.

### 2.10. Nested Resource Retrieval and Existence Validation

Several endpoints address resources nested under a parent — a certificate under a venue, a line under an order, a run under an order. For any such request, the system validates the path identifiers from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) on the **first** identifier in the path that does not correspond to an existing resource. A request for a certificate under a venue that does not exist fails on the venue before the certificate is ever looked up. This existence check precedes any business-rule evaluation. The ordering of validations across the whole system is fixed: authentication first, then authorization, then existence of every path- and body-referenced resource, then resource ownership for customer-initiated mutations, then state-validity of the targeted resource, and only then the operation's specific business rules. Earlier checks always mask later ones, so a missing header surfaces as `ERR_UNAUTHENTICATED` even if the targeted resource also happens not to exist.

### 2.11. Optimistic Concurrency Control

Two order mutations are guarded by optimistic concurrency, because they can legitimately be attempted against an order whose state another writer has already advanced. Both confirmation of an order and settlement of an order's deposit require the caller to supply `expected_order_version` as a mandatory field carrying the order `version` the client last observed.

For confirmation, the request must carry an `expected_order_version` equal to the target order's current `version`. A prior writer may have added or removed a line — which legitimately bumps the order's `version` and changes the availability and insurance picture — so a confirmation whose `expected_order_version` is older than the order's current `version` is acting on a stale view and is rejected with `ERR_STALE_VERSION` (HTTP 412).

For deposit settlement, the request must likewise carry an `expected_order_version` equal to the order's current `version`. A deposit may legitimately be settled exactly once out of `DEPOSIT_HELD`; the first settlement advances both the order's `version` and its `settlement_status` to a terminal state. Because the settlement-status state check is evaluated before the concurrency check (per the §2.10 ordering, state-validity precedes the operation's specific business rules, and the version match is checked last), a second settlement is rejected with `ERR_INVALID_STATE` (HTTP 409) — the `settlement_status` is no longer `DEPOSIT_HELD` — rather than with `ERR_STALE_VERSION`, even though the supplied `expected_order_version` is also now outdated. Order cancellation also accepts an `expected_order_version` and rejects a mismatch with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than confirm, cancel, and deposit settle do not take a version field.

### 2.12. Hierarchical State Cascades

A single client action frequently mutates more than one entity, and every secondary effect is part of the contract. When an order changes booking state, the system reconciles the order's lines, its delivery runs, and — where the rule applies — its settlement dimension and the owning customer's store credit, all within the one operation. Each such reconciliation that mutates the order refreshes the order's `updated_at` and increments its `version`. Certificate decisions similarly recompute the affected venue's `coi_status`. The exact cascades are specified alongside the workflows that trigger them in §3.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog and the Yard

A `RentalAgent` stocks the system by creating catalog items. Each `CatalogItem` is created with a stable catalog code `sku` (for example, `TENT-20X20`), which must be unique across all catalog items; a display `name`; a `category` that is one of `TENT`, `TABLE`, `CHAIR`, `LINEN`, or `BOUNCE_HOUSE`; the `total_units` the yard owns, which must be at least 1; and a `daily_rate_cents` base per-unit, per-day price of at least 0. Several attributes are optional at creation and carry defaults. The `multi_day_discount_pct` is a fractional discount applied to rental days beyond the first — for instance, 0.20 means days two onward are billed at 20% off — and it defaults to 0 and must lie between 0 and 0.90 inclusive. The `deposit_per_unit_cents` is the damage deposit charged per reserved unit, defaulting to 0 and never negative. The `requires_cleaning` flag marks an item that incurs a flat per-unit cleaning fee (true for linens and bounce houses) and defaults to false, with the per-unit charge given by `cleaning_fee_cents`, defaulting to 0 and never negative. The `requires_coi` flag marks an item that may only be confirmed when the venue carries valid insurance (true for tents and bounce houses) and defaults to false. Upon creation the item's `status` is `ACTIVE`.

Retiring an item moves its `status` from `ACTIVE` to `RETIRED`; this is permitted only while the item is `ACTIVE`, and an attempt to retire an item that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. `RETIRED` is terminal. Once retired, the item may no longer back a new order line: any attempt to add a line referencing a retired item is rejected with `ERR_INACTIVE_ITEM`, while lines already in a `RESERVED` state are entirely unaffected by the retirement.

The yard's delivery capacity is modeled by crews. A `RentalAgent` creates a `Crew` with a display `name` and an optional `turnaround_minutes` buffer, which defaults to 0 and must be at least 0. The turnaround buffer governs how tightly the crew's runs may be packed, as covered in §3.6.

A `RentalAgent` also posts weather advisories. A `WeatherEvent` is created with the `delivery_zone` it covers — one of `LOCAL`, `EXTENDED`, or `REMOTE` — a `severity` of either `ADVISORY` or `WARNING`, and an `effective_date` (the affected day at midnight UTC). Only a `WARNING`-severity event enables a full weather-cancellation refund; an `ADVISORY` is informational. Each weather event also records its `created_at`.

### 3.2. Customers, Venues, and Certificates of Insurance

A customer enters the system through self-registration, supplying an `email` that must be unique across all customers, a `full_name`, and a `phone`. A new `Customer` starts with an `account_credit_cents` store-credit balance of 0; this balance is computed, accumulating from weather-cancellation refunds and deposit releases as described later, and is never negative. A `RentalAgent` may register a customer on their behalf.

Venues are the physical event locations. A `Venue` is registered against a `customer_id` (the owning customer) with a display `name`, a street `address` used for delivery, and a `delivery_zone` of `LOCAL`, `EXTENDED`, or `REMOTE`, which drives the delivery fee tier. A newly registered venue has a `coi_status` of `NONE`. Both the owning `Customer` and a `RentalAgent` may register and read venues; a customer may only see and act on venues whose `customer_id` is their own.

To insure a venue, a certificate of insurance is filed against it. An `InsuranceCertificate` references its `venue_id` and is submitted with a `carrier_name`, a coverage interval given by `coverage_start` and `coverage_end` (both ISO 8601 UTC instants), and a `coverage_amount_cents` liability amount of at least 0. A freshly submitted certificate has `status` `SUBMITTED`, and filing it recomputes the venue's `coi_status`. A certificate moves through a small lifecycle driven entirely by the rental agent. Approving a submitted certificate advances its `status` `SUBMITTED → APPROVED` and recomputes the venue's `coi_status`; approval is permitted only when the certificate is `SUBMITTED` (otherwise `ERR_INVALID_STATE`) and additionally requires that the `coverage_end` be on or after the `coverage_start`, failing which the approval is rejected with `ERR_INVALID_COVERAGE_WINDOW`. This same coverage-window sanity check — `coverage_end` not earlier than `coverage_start` — is also enforced at submission time. Rejecting a submitted certificate advances its `status` `SUBMITTED → REJECTED`, may carry an optional `reason`, and recomputes the venue's `coi_status`; rejection is permitted only from `SUBMITTED`, otherwise `ERR_INVALID_STATE`. Revoking an approved certificate advances its `status` `APPROVED → REVOKED`, may carry an optional `reason`, and recomputes the venue's `coi_status`; revocation is permitted only from `APPROVED`, otherwise `ERR_INVALID_STATE`. The optional `reason` on a reject or a revoke is accepted by the request but is not persisted — an `InsuranceCertificate` carries no `reason` field, so the certificate object returned and read back never exposes it. Both `REJECTED` and `REVOKED` are terminal. When a certificate is revoked, the system recomputes coverage, and a confirmed order on that venue whose insured lines now find their window uncovered is flagged as such but is explicitly **not** auto-cancelled.

Coverage is evaluated for a specific event window — the inclusive day span from an order's `event_start` to its `event_end`. For that window, the system considers the venue's approved certificates. If at least one approved certificate's `coverage_start` is on or before the event start and whose `coverage_end` is on or after the event end — the coverage interval being inclusive at both ends, so a certificate whose `coverage_start` equals the event start still qualifies — the window's coverage is `VALID`. Otherwise, if any certificate for the venue is still `SUBMITTED`, the coverage reads `PENDING`. Otherwise, if there is an approved certificate that does not cover the window, the coverage reads `EXPIRED`. Failing all of these, coverage is `NONE`. When the venue's `coi_status` is reported without an order context, it is derived from the venue's latest certificate by `coverage_end` descending, ties broken by `created_at` ascending, reporting `VALID`, `PENDING`, or `EXPIRED` accordingly, with rejected certificates treated as contributing `NONE`.

### 3.3. Assembling and Pricing a Draft Order

A `Customer` (or a `RentalAgent` acting for them) opens an order in `DRAFT` by supplying the `customer_id`, a `fulfillment` mode of either `WILL_CALL` (pickup at the yard) or `DELIVERY` (delivered to a venue), the event window `event_start` and `event_end` (each the relevant day at midnight UTC), and, for delivery orders, the `venue_id` of the event location. The event window must be well-formed: the `event_end` must be on or after the `event_start`, otherwise the order is rejected with `ERR_INVALID_EVENT_WINDOW`. From the window the system computes `rental_days` as the inclusive whole-day span — the number of whole days from `event_start` to `event_end` counting both ends, equivalently the day-count difference plus one — which is always at least 1. A delivery order must name a venue that belongs to the ordering customer; a delivery order missing a valid customer-owned `venue_id` is rejected with `ERR_VENUE_REQUIRED`, a check applied both when the order is created and again at confirmation time. A new order starts with `booking_status` `DRAFT`, `settlement_status` `UNSETTLED`, `version` 1, and — having no lines yet — a `weather_cancellable` flag of false.

Lines are added to a draft order one at a time, each supplying the `item_id` of the catalog item and a `quantity` of at least 1. A new `OrderLine` references its owning `order_id`, starts with `status` `PENDING`, and holds no inventory yet (its `reserved_window_start` and `reserved_window_end` are null). Although adding a line both creates the `OrderLine` and mutates the parent order's `version`, the add-line operation's response `data` is the newly-created `OrderLine` object itself (returned with HTTP 201), not the updated order; the freshly created line carries its own `version` of 1. Adding a line is allowed only while the order's `booking_status` is `DRAFT`; an attempt to add a line to a non-draft order is rejected with `ERR_LINE_NOT_DRAFT`, and adding a line that references a retired item is rejected with `ERR_INACTIVE_ITEM`. Each line addition recomputes the order's `weather_cancellable` flag and increments the order's `version` by one. A line may likewise be removed only while the order is `DRAFT`; removing a line from a non-draft order is rejected with `ERR_LINE_NOT_DRAFT`, and a successful removal also recomputes `weather_cancellable` and increments the order's `version` by one. An order's `weather_cancellable` flag is true exactly when at least one of its lines references an item whose `category` is weather-sensitive — that is, a `TENT` or a `BOUNCE_HOUSE`.

The system can preview an order's full pricing without confirming it, returning the computed `rental_subtotal_cents`, `delivery_fee_cents`, `cleaning_fee_total_cents`, `deposit_total_cents`, and `grand_total_cents` for the order as it currently stands. The same calculations that drive this preview are the ones applied at confirmation, so a preview is a faithful forecast of the confirmed charges. The preview is keyed to the `order_id`.

Each line's rental charge is computed with a pinned evaluation order. Let the order's `rental_days` be the inclusive day span. The first day is billed at the item's full `daily_rate_cents`. Each additional day is billed at a discounted day rate, which is the item's `daily_rate_cents` multiplied by one minus the item's `multi_day_discount_pct`, rounded half up to a whole number of cents. The per-unit price is then the full first-day rate plus the discounted day rate applied to each of the remaining days — that is, the discounted day rate multiplied by one fewer than the number of rental days, added to the full first-day rate. This per-unit price is computed and rounded to whole cents **first**, and only then multiplied by the line's `quantity` to give that line's `line_rental_cents`. The rounding happens at the per-unit step, before multiplying by quantity; the system does not round again afterward. Each line also carries a `line_deposit_cents` equal to its `quantity` times the item's `deposit_per_unit_cents`, and a `line_cleaning_cents` equal to its `quantity` times the item's `cleaning_fee_cents` when the item requires cleaning, or 0 when it does not.

The order's `rental_subtotal_cents` is the exact sum of every line's `line_rental_cents` (each already rounded at the per-unit step and multiplied by quantity); this sum is not re-rounded. The order's `cleaning_fee_total_cents` is the sum over every line whose item requires cleaning of that line's `quantity` times the item's `cleaning_fee_cents`. The order's `deposit_total_cents` is the sum over every line of that line's `quantity` times the item's `deposit_per_unit_cents`. The order's `grand_total_cents` is the sum of `rental_subtotal_cents`, `delivery_fee_cents`, and `cleaning_fee_total_cents`; the deposit is held separately and is deliberately **not** part of the grand total.

The delivery fee depends on fulfillment and is computed as a round trip covering both the drop-off and the pickup. For a `WILL_CALL` order the `delivery_fee_cents` is 0. For a `DELIVERY` order the fee starts from a zone base determined by the venue's `delivery_zone`: a local zone contributes a base of 5000 cents, an extended zone 9000 cents, and a remote zone 15000 cents. A big-event surcharge of 4000 cents is added when the order moves a lot of gear — specifically when the total reserved units across all lines is at least 100 (so 99 units adds nothing and 100 units adds the surcharge). A free-delivery waiver then applies: when the order's `rental_subtotal_cents` is at least 200000 cents (that is, $2,000.00, with 199999 cents not qualifying and 200000 cents qualifying), the zone base is waived to 0, but the big-event surcharge is **not** waived. The final `delivery_fee_cents` is therefore the post-waiver base plus the surcharge.

### 3.4. Confirming an Order: Reservation, Pricing, and the Deposit Hold

Confirmation is the pivotal moment when a draft becomes a binding commitment, and it is the most heavily guarded transition in the system. A `Customer` confirming their own order (or a `RentalAgent` acting for them) supplies `expected_order_version` so the system can detect a stale view. Confirmation is gated by a set of preconditions evaluated in the following order. First, after the universal authentication, authorization, existence, ownership, and state checks of §2.10, the system requires that the order hold at least one line; a confirmation on an order with zero lines is rejected with `ERR_ORDER_EMPTY`. Next, the insurance gate: for every line whose item carries the `requires_coi` flag, the order's venue must show `VALID` coverage over the event window, and if any such line lacks valid coverage the confirmation is rejected with `ERR_COI_REQUIRED`. This gate is driven purely by the lines' `requires_coi` flags and never by the fulfillment mode: an order with no `requires_coi` line skips the gate entirely (so a `WILL_CALL` order that has no insured lines never triggers it), while an order that has at least one `requires_coi` line must show `VALID` coverage regardless of fulfillment. A `WILL_CALL` order carries no `venue_id`, so it can never present a venue with `VALID` coverage; consequently a `WILL_CALL` order containing any `requires_coi` line (for instance a `TENT` or `BOUNCE_HOUSE`) is always rejected with `ERR_COI_REQUIRED` at confirmation. Then the availability gate: for every line, the units already reserved on overlapping windows plus this line's `quantity` must not exceed the item's `total_units`, and a shortfall is rejected with `ERR_INVENTORY_UNAVAILABLE`. Finally the concurrency gate: `expected_order_version` must equal the order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`.

When all gates pass, confirmation advances `booking_status` `DRAFT → CONFIRMED` and triggers a cascade. Every line's `status` moves `PENDING → RESERVED`, and the order's `event_start` and `event_end` are copied onto each line as its `reserved_window_start` and `reserved_window_end`, establishing the inventory hold over that window. The system then recomputes and records `rental_subtotal_cents`, `delivery_fee_cents`, `cleaning_fee_total_cents`, `deposit_total_cents`, and `grand_total_cents` using the pricing rules of §3.3. As a cross-dimension cascade, the settlement side advances `settlement_status` `UNSETTLED → DEPOSIT_HELD` and the system appends a deposit ledger entry of kind `HOLD` whose `amount_cents` equals the order's `deposit_total_cents`. The order's `version` is incremented by one.

### 3.5. Fulfillment, Return, and Cancellation

Once an order is `CONFIRMED`, the rental agent fulfills it when the goods physically leave the yard, advancing `booking_status` `CONFIRMED → FULFILLED`. Fulfillment requires the order to be `CONFIRMED`, otherwise `ERR_INVALID_STATE`. For a `DELIVERY` order, fulfillment additionally requires that the drop-off run for the order has reached `COMPLETED`; if the drop-off run is not yet complete, fulfillment is rejected with `ERR_DELIVERY_NOT_COMPLETED`. A `WILL_CALL` order carries no such delivery precondition. Fulfillment increments the order's `version` by one.

When the goods come back, the rental agent returns the order, advancing `booking_status` `FULFILLED → RETURNED`. Return requires the order to be `FULFILLED`, otherwise `ERR_INVALID_STATE`. For a `DELIVERY` order, return additionally requires that the pickup run for the order has reached `COMPLETED`, failing which it is rejected with `ERR_DELIVERY_NOT_COMPLETED`. Returning cascades by moving every line's `status` `RESERVED → RELEASED`, freeing the inventory window, and then increments the order's `version` by one. `RETURNED` is a terminal booking state.

An order may be cancelled while it is either `DRAFT` or `CONFIRMED`, by the owning customer or by the system; a cancellation attempted from any other booking state is rejected with `ERR_INVALID_STATE`. Cancellation requires the supplied `expected_order_version` to match the order's current `version`, otherwise `ERR_STALE_VERSION`. Cancellation drives a multi-hop cascade. Every line not already `RELEASED` has its `status` set to `RELEASED`, freeing its inventory window. Every delivery run for the order that is `SCHEDULED` or `ATTEMPTED` has its `status` set to `CANCELLED`. And if the order's `settlement_status` is `DEPOSIT_HELD` at the time of cancellation, the settlement dimension advances `DEPOSIT_HELD → DEPOSIT_RELEASED`, the system appends a deposit ledger entry of kind `RELEASE` for the current held balance, and the owning customer's `account_credit_cents` is recomputed to reflect that release. The order's `version` is incremented by one. `CANCELLED` is a terminal booking state.

### 3.6. Scheduling and Running Deliveries

For a delivery order, the rental agent schedules runs against a crew. A `DeliveryRun` is created with the `order_id` it serves, a `leg` of either `DROP_OFF` (the outbound delivery) or `PICK_UP` (the return collection), the `crew_id` of the assigned crew, and a scheduled `window_start` (inclusive) and `window_end` (exclusive). A new run starts with `status` `SCHEDULED` and an `attempt_count` of 0. Scheduling reserves the crew's window, and the system rejects the new window if it collides with any other non-`CANCELLED` run on the same crew once the crew's `turnaround_minutes` buffer is taken into account — two windows conflict if they overlap or sit closer together than the buffer allows — returning `ERR_CREW_WINDOW_CONFLICT`.

A run's outcome is recorded by reporting an `outcome`. Reporting `SUCCESS` advances a scheduled run `SCHEDULED → COMPLETED`; a successful drop-off run is what unblocks the order's fulfillment, and a successful pickup run is what unblocks the order's return. Reporting `FAILED` advances a scheduled run `SCHEDULED → ATTEMPTED` and increments its `attempt_count` by one. Both outcome reports require the run to be `SCHEDULED`, otherwise `ERR_INVALID_STATE`.

An attempted run can be rescheduled back to a fresh window, advancing `status` `ATTEMPTED → SCHEDULED` and updating its `window_start` and `window_end`. Rescheduling requires the run to be `ATTEMPTED`, otherwise `ERR_INVALID_STATE`. It is additionally permitted only while the run's `attempt_count` is at most 2 — a third failure forbids any further reschedule, and a reschedule attempted beyond that is rejected with `ERR_MAX_ATTEMPTS_EXCEEDED`. The new window is re-checked against the crew's other non-`CANCELLED` runs including the turnaround buffer, and a collision is rejected with `ERR_CREW_WINDOW_CONFLICT`. This cyclic loop between `SCHEDULED` and `ATTEMPTED` lets a crew try, fail, and try again until the run succeeds or is exhausted.

A run may also be cancelled directly by the rental agent or by the system when its owning order is cancelled. Cancellation is permitted while the run is `SCHEDULED` or `ATTEMPTED`, otherwise `ERR_INVALID_STATE`, and it advances `status` to `CANCELLED` and frees the crew's window. Both `COMPLETED` and `CANCELLED` are terminal run states. Delivery runs may be listed and filtered by their `order_id` or `crew_id`.

### 3.7. The Deposit Ledger and Store Credit

Every deposit movement on an order is recorded as an immutable `DepositLedgerEntry` against the order's `order_id`. Each entry has a `kind` of `HOLD`, `RELEASE`, or `FORFEIT`, an `amount_cents` that is always recorded as a non-negative magnitude (a `HOLD` adds to the held balance while a `RELEASE` or `FORFEIT` reduces it), an optional free-text `reason` such as "torn linen" or "clean return" defaulting to empty, and a `created_at` timestamp. The ledger is append-only and is read back in `created_at` ascending order; ties are broken by `created_at` alone and the entry `id` must never be used as a tie-breaker.

The current held-deposit balance of an order is derived by replaying its ledger entries in `created_at` ascending order, starting from zero, adding each `HOLD` entry's `amount_cents` and subtracting each `RELEASE` and each `FORFEIT` entry's `amount_cents`. The resulting balance equals total holds minus total releases minus total forfeits and is never negative. This held balance is recomputed on every ledger append and is the figure reported when the order's deposit ledger is read.

A customer's `account_credit_cents` is the store credit they have accrued, computed by forward replay of every credit-affecting event for that customer in `created_at` ascending order, with `created_at` as the only tie-breaker and the entry `id` forbidden as a tie-break. It is the sum of every `RELEASE` ledger entry's `amount_cents` across all orders belonging to that customer, plus every weather-cancellation refund credited on that customer's orders. The balance is floored at zero and is never negative.

### 3.8. Deposit Settlement

After an order has been `RETURNED`, the back-office `DepositAdjuster` settles its held deposit by supplying a `disposition` of either `RELEASE` or `FORFEIT`, the `expected_order_version` for the concurrency check, and — for a forfeiture — a `forfeit_amount_cents` and an optional `reason`. Settlement is allowed only when the order's `settlement_status` is `DEPOSIT_HELD` (otherwise `ERR_INVALID_STATE`) and only when the order's `booking_status` is `RETURNED` (otherwise `ERR_NOT_RETURNED`), and the supplied `expected_order_version` must match the order's current `version` (otherwise `ERR_STALE_VERSION`).

A `RELEASE` disposition advances `settlement_status` `DEPOSIT_HELD → DEPOSIT_RELEASED`, appends a deposit ledger entry of kind `RELEASE` for the current held balance, and credits the owning customer's `account_credit_cents` by the released amount. The order's `version` is incremented by one. The same `DEPOSIT_HELD → DEPOSIT_RELEASED` transition is what the system performs automatically when a `DEPOSIT_HELD` order is cancelled, as described in §3.5.

A `FORFEIT` disposition advances `settlement_status` `DEPOSIT_HELD → DEPOSIT_FORFEITED`. The `forfeit_amount_cents` must not exceed the current held balance; a forfeiture larger than what is held is rejected with `ERR_FORFEIT_EXCEEDS_HELD`. On a valid forfeit, the system appends a deposit ledger entry of kind `FORFEIT` for the `forfeit_amount_cents`. If the forfeited amount is less than the held balance, the system additionally appends a deposit ledger entry of kind `RELEASE` for the remainder and credits the owning customer's `account_credit_cents` by that remainder. The order's `version` is incremented by one. Both `DEPOSIT_RELEASED` and `DEPOSIT_FORFEITED` are terminal settlement states.

### 3.9. Weather Cancellation

When a storm threatens, a `Customer` (or a `RentalAgent` on their behalf) may weather-cancel an order. Weather cancellation is permitted only while the order's `booking_status` is `CONFIRMED` or `FULFILLED`; attempted from any other booking state (for example a `DRAFT`, `RETURNED`, or already-`CANCELLED` order) it is rejected with `ERR_INVALID_STATE`, and this state check precedes the matching-event check below. A weather cancellation requires a matching weather event: a `WeatherEvent` of `WARNING` severity whose `delivery_zone` matches the order's situation and whose `effective_date` falls on one of the inclusive days of the order's event window from `event_start` to `event_end`. The zone match is keyed to the order's venue: for a `DELIVERY` order, the event's `delivery_zone` must equal the venue's `delivery_zone`; for a `WILL_CALL` order (which has no venue and therefore no zone), the zone filter is skipped entirely, so any `WARNING` event whose `effective_date` falls within the event window matches regardless of its `delivery_zone`. If no such matching `WARNING` event exists, the request is rejected with `ERR_NO_WEATHER_EVENT`.

Weather cancellation, like an ordinary cancellation, advances the order's `booking_status` to `CANCELLED`, sets every line's `status` to `RELEASED`, and sets every `SCHEDULED` or `ATTEMPTED` delivery run's `status` to `CANCELLED`. What distinguishes it is the refund, whose composition depends on how far the order had progressed. When the order is still `CONFIRMED` at weather-cancel time — the goods have not yet gone out — the rental refund is the full `rental_subtotal_cents` plus `cleaning_fee_total_cents`, and the delivery refund is the full `delivery_fee_cents`, since the delivery has not yet been incurred; the weather refund credited is the sum of these two parts. When the order is already `FULFILLED` at weather-cancel time — the goods are out — the rental and delivery refunds are both 0, because the rental has effectively been consumed once the goods are in the field. In either case the held deposit is released in full. The computed weather refund is credited to the customer's `account_credit_cents`, and the deposit release is credited separately through a `RELEASE` ledger entry. All monetary parts are whole cents and the total is an exact sum. The order's `version` is incremented by one.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify or transition an existing resource, including state transitions and computed reads, return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/catalog-items` | Create a catalog item | RentalAgent |
| GET | `/catalog-items` | List catalog items (filter by category) | RentalAgent, Customer, DepositAdjuster |
| GET | `/catalog-items/{item_id}` | Get a catalog item | RentalAgent, Customer, DepositAdjuster |
| GET | `/catalog-items/{item_id}/availability` | Available units of an item over a queried window | RentalAgent, Customer |
| GET | `/catalog-items/{id}/reservations` | List order lines referencing this item | RentalAgent, Customer, DepositAdjuster |
| POST | `/catalog-items/{item_id}/retire` | Retire a catalog item | RentalAgent |
| POST | `/customers` | Register a customer | RentalAgent, Customer |
| GET | `/customers/{customer_id}` | Get a customer | RentalAgent, Customer, DepositAdjuster |
| POST | `/venues` | Register a venue for a customer | Customer, RentalAgent |
| GET | `/venues/{venue_id}` | Get a venue with computed coi_status | Customer, RentalAgent |
| GET | `/venues` | List venues (filter by customer_id) | Customer, RentalAgent |
| POST | `/venues/{venue_id}/certificates` | Submit a certificate of insurance | Customer, RentalAgent |
| GET | `/venues/{id}/certificates` | List certificates for a venue | Customer, RentalAgent |
| POST | `/venues/{venue_id}/certificates/{certificate_id}/approve` | Approve a submitted certificate | RentalAgent |
| POST | `/venues/{venue_id}/certificates/{certificate_id}/reject` | Reject a submitted certificate | RentalAgent |
| POST | `/venues/{venue_id}/certificates/{certificate_id}/revoke` | Revoke an approved certificate | RentalAgent |
| POST | `/orders` | Create a draft rental order | Customer, RentalAgent |
| GET | `/orders/{order_id}` | Get an order with computed totals | Customer, RentalAgent, DepositAdjuster |
| GET | `/orders` | List orders (filter by customer_id, venue_id) | Customer, RentalAgent, DepositAdjuster |
| POST | `/orders/{order_id}/lines` | Add a line to a draft order | Customer, RentalAgent |
| GET | `/orders/{id}/lines` | List lines on an order | Customer, RentalAgent, DepositAdjuster |
| DELETE | `/orders/{order_id}/lines/{line_id}` | Remove a line from a draft order | Customer, RentalAgent |
| GET | `/orders/{order_id}/quote` | Preview order totals without confirming | Customer, RentalAgent |
| POST | `/orders/{order_id}/confirm` | Confirm a draft order | Customer, RentalAgent |
| POST | `/orders/{order_id}/fulfill` | Mark an order fulfilled | RentalAgent |
| POST | `/orders/{order_id}/return` | Mark an order returned | RentalAgent |
| POST | `/orders/{order_id}/cancel` | Cancel a draft or confirmed order | Customer, RentalAgent |
| POST | `/orders/{order_id}/weather-cancel` | Weather-cancel an order | Customer, RentalAgent |
| POST | `/orders/{order_id}/deposit/settle` | Settle the held deposit (release or forfeit) | DepositAdjuster |
| GET | `/orders/{id}/deposit-ledger` | List the deposit ledger for an order | RentalAgent, DepositAdjuster, Customer |
| POST | `/crews` | Create a delivery crew | RentalAgent |
| GET | `/crews/{crew_id}` | Get a crew | RentalAgent |
| POST | `/delivery-runs` | Schedule a delivery/pickup run | RentalAgent |
| GET | `/delivery-runs/{run_id}` | Get a delivery run | RentalAgent |
| GET | `/delivery-runs` | List delivery runs (filter by order_id, crew_id) | RentalAgent |
| POST | `/delivery-runs/{run_id}/attempt` | Record a delivery attempt outcome | RentalAgent |
| POST | `/delivery-runs/{run_id}/reschedule` | Reschedule an attempted run | RentalAgent |
| POST | `/delivery-runs/{run_id}/cancel` | Cancel a scheduled/attempted run | RentalAgent |
| POST | `/weather-events` | Post a weather advisory/warning | RentalAgent |
| GET | `/weather-events` | List weather events (filter by delivery_zone) | RentalAgent, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_EMPTY` | 422 Unprocessable Entity |
| `ERR_COI_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVENTORY_UNAVAILABLE` | 409 Conflict |
| `ERR_CREW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_MAX_ATTEMPTS_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DELIVERY_NOT_COMPLETED` | 409 Conflict |
| `ERR_NOT_RETURNED` | 409 Conflict |
| `ERR_FORFEIT_EXCEEDS_HELD` | 422 Unprocessable Entity |
| `ERR_NO_WEATHER_EVENT` | 422 Unprocessable Entity |
| `ERR_VENUE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_COVERAGE_WINDOW` | 422 Unprocessable Entity |
| `ERR_INVALID_EVENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_LINE_NOT_DRAFT` | 409 Conflict |
| `ERR_INACTIVE_ITEM` | 422 Unprocessable Entity |
</content>
</invoke>
