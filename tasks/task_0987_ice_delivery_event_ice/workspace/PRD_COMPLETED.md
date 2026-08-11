# Ice Delivery & Event Ice Service API — Product Requirements Document

## 1. Introduction

Neighborhood bars restocking their ice wells, restaurants bracing for a holiday weekend, and event organizers hauling pallets of dry ice across a fairground all share the same problem: ice is heavy, perishable in transit, and needed at precise times. This document specifies the Ice Delivery & Event Ice Service API, a platform through which depots sell and deliver block, cube, and dry ice to two customer populations — bars and restaurants standing on recurring weekly routes, and event organizers placing one-off orders — with fulfillment either by scheduled delivery or by customer pickup at the depot (will-call).

The API governs the complete commercial lifecycle: onboarding depots and customer accounts, publishing tiered price books, declaring seasonal surge windows, registering dry-ice handler certifications, composing and quoting orders, reserving delivery-slot and freezer capacity, confirming orders under a battery of safety, capacity, and credit gates, staging product into cold storage, dispatching delivery runs, consolidating invoices, and recording payments. Because the underlying resources are finite — freezer pallets, slot pallets, vehicle decks, ventilated dry-ice compartments, and each customer's credit line — the specification leans heavily on derived state: a depot's operating posture, a slot's fullness, and a customer's standing are all computed, and every mutation recomputes them immediately, in the same request. A platform-controlled logical clock drives all date and time derivations, so surge windows, certification expiry, invoice aging, and recurring-order generation are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and derived-state principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying a role value outside the recognized set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The platform recognizes exactly six roles: `PlatformAdmin`, `DepotManager`, `Dispatcher`, `BillingClerk`, `SafetyOfficer`, and `CustomerAgent`. Each operation is restricted to designated roles (§4); an authenticated caller attempting an operation outside their role is rejected with `ERR_FORBIDDEN` (HTTP 403).

Five roles carry an opaque operator identity. When `X-User-Role` is `PlatformAdmin`, `DepotManager`, `Dispatcher`, `BillingClerk`, or `SafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `issued_by_user_id` and `voided_by_user_id` on an `Invoice` — but never compares it to any entity's `id`. When `X-User-Role` is `CustomerAgent`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID` — `customer_id` on an order, route, invoice, or payment, or the linked order's `customer_id` for a waitlist entry. List and detail reads performed by a `CustomerAgent` are scoped to their own resources wherever ownership applies.

One further duty constraint sits on top of the role model and is enforced as a business rule rather than a role restriction: segregation of duties in billing. The `BillingClerk` operator who issued an invoice may not be the one who voids it (§3.8), with violations rejected as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints paginate through two optional query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. A `limit` or `offset` that is not an integer within these bounds (an `offset` must be non-negative) is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless a section states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Platform Logical Clock

All temporal reasoning in the platform is evaluated against a logical clock, never against wall-clock time. At startup the clock reads exactly 2026-05-01T00:00:00Z; before any administrative intervention it continues to read that default, and it never falls back to wall-clock time. A `PlatformAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and answers with the new value echoed as `current_utc`. Every timestamp the server stamps onto a resource or event is the logical clock plus a strictly increasing microsecond offset, so successive stamps never collide and sorting by `created_at` coincides with creation order. Every derivation described in this document — surge-window and price-book status, certification expiry, delivery lead-time checks, invoice due dates and overdue sweeps, slot closure, route generation — evaluates against the current logical clock and the current logical date it implies. Dates are exchanged as YYYY-MM-DD strings and instants as ISO 8601 UTC; window times of day are HH:MM in 24-hour notation.

### 2.5. Common Resource Properties

All primary resources — depots, customers, certifications, price books, surge windows, recurring routes, orders and their lines, delivery slots, cold-storage holds, dispatch runs, and invoices — share a standard set of system-managed fields:

- `id` (string): a unique server-generated identifier formatted as a UUID in the canonical dashed RFC 4122 string form — five hyphen-separated hexadecimal groups of 8, 4, 4, 4 and 12 characters (36 characters in total, lowercase), with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource, including recomputation of derived fields.
- `version` (integer): a system-managed integer incremented by one on every mutation; it is the basis of optimistic concurrency control (§2.7).

Two resources are deliberately slimmer. A `Payment` is an immutable ledger entry, and a `WaitlistEntry` is a transient queue record: both carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them. Waitlist entries instead track their lifecycle through the explicit timestamps `queued_at` and `promoted_at`, and payments through `received_at`.

### 2.6. Request Validation and Evaluation Order

Every request is evaluated against a fixed ladder of checks, and the first failing rung decides the response — later checks are never consulted once an earlier one has failed. The ladder runs in this order:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers must be present and the role must be one of the six declared values, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization and ownership** — the role must be permitted for the endpoint, and for the entity-backed `CustomerAgent` the `X-User-ID` must equal the owning customer's `id` (the order's `customer_id`, the route's `customer_id`, or the waitlist entry's linked order's `customer_id`), else `ERR_FORBIDDEN` (HTTP 403). Where the owned resource is addressed by the URL path, ownership can only be evaluated once the resource is loaded, so for such reads and writes a nonexistent path identifier yields `ERR_NOT_FOUND` (rung 4) while an existing resource owned by a different customer yields `ERR_FORBIDDEN`.
3. **Request-body schema** — required fields are present, types match, enum values are valid, unknown fields are rejected, numeric fields respect the minimum bounds stated with them in §3 (other than the two business-coded minima, line `quantity_units` and payment `amount_cents`), a price-book tier's `tier_max_units` is no less than its `tier_min_units`, an order's `lines` array and a route's `standing_lines` array are non-empty (a price book's `lines` array may be empty), `window_start` falls before `window_end`, `period_start` falls before `period_end`, and a surge window's `start_date` falls no later than its `end_date`, else `ERR_INVALID_REQUEST` (HTTP 400). Endpoints that declare no request-body fields impose no schema checks on the body.
4. **Path existence** — every identifier in the URL must exist, validated left to right (a depot identifier before any segment nested beneath it), else `ERR_NOT_FOUND` (HTTP 404).
5. **Body reference existence** — foreign-key identifiers carried in the body (`customer_id`, `depot_id`, `delivery_slot_id`, and the like) must exist, else `ERR_NOT_FOUND` (HTTP 404).
6. **Optimistic concurrency** — where an endpoint takes an expected-version field (§2.7), it must match the entity's current `version`, else `ERR_STALE_VERSION` (HTTP 412).
7. **Terminal-state guard** — the target must not be in a terminal state for the attempted operation: a `CANCELLED` order, a `TERMINATED` route, a `VOID` invoice — or a `PAID` one, for issuance — a `RELEASED` or `EXPIRED` hold, a `COMPLETED` or `CANCELLED` run, a `PROMOTED`, `WITHDRAWN`, or `EXPIRED` waitlist entry, or an `EXPIRED` certification, else `ERR_ALREADY_TERMINAL` (HTTP 409). A `CLOSED` slot is not a terminal-guard case: no operation targets a slot, and reserving against a closed one fails the state gauntlet of §3.5 with `ERR_INVALID_STATE`.
8. **Required-state guard** — the target must be in the specific non-terminal state the operation requires: quoting needs `DRAFT`; confirming needs `QUOTED`; staging needs `CONFIRMED`; marking ready needs a `STAGED` will-call order; confirming pickup needs `READY_FOR_PICKUP`; slot reservation and repricing need `QUOTED`; issuing needs a `DRAFT` invoice; assigning needs a `PLANNED` run and `STAGED` orders; locking needs `PLANNED`; starting needs `LOCKED`; completing needs `IN_PROGRESS`; pausing needs an `ACTIVE` route; resuming needs a `PAUSED` route — else `ERR_INVALID_STATE` (HTTP 409).

Only after all eight generic rungs do the business rules of §3 apply, in the pinned orders stated with each workflow. One operation splits its state rule across the ladder: voiding an invoice. A void attempted on an already-`VOID` invoice fails at rung seven with `ERR_ALREADY_TERMINAL`; a void attempted on a `PAID` invoice is a business-fiscal rejection with `ERR_INVOICE_NOT_VOIDABLE` (HTTP 409), evaluated after the segregation-of-duties check (§3.8).

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and both treat their expected-version field as non-optional. A request to reprice an order must carry `expected_order_version` holding the order's `version` as the client last observed it. A request to patch a recurring route's standing order must carry `expected_route_version` holding the route's `version` as the client last observed it. In both cases, if the supplied value does not match the entity's current `version` — meaning another write, such as a prior reprice or a pause/resume cycle, has advanced the entity since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from overwriting a state it never observed. No other endpoint takes a version field.

### 2.8. Monetary Precision and Rounding

All monetary amounts in the platform are integer cents. Wherever a computation would yield a fractional cent — the dry-ice handling premium folded into a line, the volume discount, the surge surcharge — the result is rounded half up to the nearest whole cent. Rounding order is pinned: each order line's total is rounded individually before any summation, and within the order's total composition the discount and surcharge steps are the only rounded steps; the merchandise subtotal, delivery fee, deposit, and grand total are exact integer sums of already-integer components. Invoice amounts are component-wise integer sums of their attached orders, and payment allocation runs in integer cents throughout, so no rounding remainder can exist. Monetary values appear in API responses as numbers.

### 2.9. Depot Posture and Freezer Accounting

A depot's freezer state is fully derived from its cold-storage holds. `freezer_reserved_pallets` is the sum of `pallets_required` across the depot's holds currently in `RESERVED` or `OCCUPIED` status, and `freezer_free_pallets` is the `freezer_capacity_pallets` less that reserved total. From the free count the depot's `posture` is derived: `FROZEN` when no pallet space remains — the free count at or below zero; otherwise `SURGE_CONSTRAINED` when the free count is no more than one fifth of total capacity (the capacity multiplied by 20 percent, rounded up to a whole pallet); otherwise `OPEN`. These aggregates and the posture are recomputed on every hold creation, release, or expiry, and a depot read always exposes the current values.

Two semantic rules govern every freezer computation in this document. First, hold intervals are half-open: a hold whose interval ends exactly when another's begins do not overlap, so adjacency is always admitted. Second, holds zoned `DRY_ICE_BUNKER` do not consume general-freezer pallets and are excluded from every freezer sum; the bunker's own exclusivity rule is interval-based instead (§3.5). Posture is also a gate, not merely a display: a `FROZEN` depot accepts no new slot reservations (`ERR_POSTURE_FROZEN`) and blocks waitlist promotion until a release eases it.

### 2.10. Nested Paths and Referential Integrity

Requests that address a resource nested under another — a depot's slots, a customer's certifications, an order's holds — are validated left to right: the parent's existence is confirmed before the nested segment is even examined, and the first missing identifier in the path yields `ERR_NOT_FOUND` (HTTP 404). The same error answers foreign keys supplied in request bodies: creating an order references its `customer_id` and `depot_id`; registering a certification references its customer; creating a recurring route references its customer and depot; creating a surge window or a dispatch run references its depot; reserving a slot references the `delivery_slot_id`; invoice generation and payment recording reference their customer. A body that points at a nonexistent resource is rejected with `ERR_NOT_FOUND` before any business rule runs.

## 3. Business Logic & Workflows

This section walks the business lifecycle from network onboarding through settlement. State values appear as their exact enumeration strings; error identifiers appear where their trigger conditions live; the HTTP contract for every capability named here is collected in §4.

### 3.1. Stocking the Network: Depots, Customers, Price Books, and Surge Windows

A `PlatformAdmin` onboards each fulfillment depot with a `name` and a `freezer_capacity_pallets` of at least one — the total number of pallet spaces in the depot's general freezer. A new depot begins with `freezer_reserved_pallets` at zero, `freezer_free_pallets` equal to its capacity, posture `OPEN`, and an `ops_run_index` of zero; that counter climbs by one with every ops-run checkpoint the depot executes (§3.9).

Customer accounts are likewise opened by a `PlatformAdmin`, who supplies the `account_name`, a `kind` of `BAR_RESTAURANT` or `EVENT_ORGANIZER`, a `tier` of `STANDARD` or `PRIORITY` (the waitlist promotion rank key, §3.6), `credit_terms` of `PREPAID`, `NET_15`, or `NET_30` (the invoice due-date offset, §3.8), and a `credit_limit_cents` of at least zero — the maximum forward-looking exposure the house tolerates. New accounts start with `credit_balance_cents` and `outstanding_exposure_cents` at zero and a `standing` of `GOOD`. Thereafter `standing` is derived: it is `HOLD` whenever any invoice belonging to the customer is `OVERDUE`, and `GOOD` otherwise. The credit balance is a wallet fed by payment overpayments and by funds unapplied when an invoice is voided (§3.8).

Commercial terms live in price books. A book carries a human `scope_label`, an `effective_from` instant, and a set of `lines` — pricing rows keyed by `product_form` and `packaging`, each row bracketed by `tier_min_units` and `tier_max_units` (a null upper bound leaves the tier unbounded) and carrying a `unit_price_cents`. Tier rates are flat: whichever tier a quantity falls into prices the entire quantity at that tier's unit price, never marginally. Alongside the lines sit the book's commercial knobs: a refundable `pallet_deposit_cents` charged per pallet unit, a flat `delivery_fee_cents`, a `free_delivery_threshold_cents` that waives the fee once the post-discount merchandise subtotal reaches it, `volume_discount_tiers` rows pairing a `threshold_cents` with a `discount_bps` (the highest satisfied tier wins), and a `surge_surcharge_bps` levied in basis points during surge windows. A book is `SCHEDULED` until its `effective_from` reaches the logical clock, and creating a book whose `effective_from` is already at or before the clock activates it immediately. Exactly one book is `ACTIVE` at any instant: each activation moves the incumbent to `SUPERSEDED`. Orders already quoted keep their pinned `price_book_id` and `price_book_version` even after the book is superseded (§3.4). Books are listable with an optional `status` filter.

Seasonal pressure is declared per depot through surge windows. A `PlatformAdmin` creates one with a `depot_id`, an inclusive `start_date` and `end_date` — the window covers every date from the first through the last — an `admission_policy` of `OPEN`, `RATIONED`, or `CLOSED`, and, required exactly when the policy is `RATIONED`, a `daily_pallet_cap` of at least one: the maximum committed pallets per covered date. On `OPEN` and `CLOSED` windows the field may still be supplied; it is then validated as an integer of at least one, stored, and echoed on reads, but it is consulted only by `RATIONED` admission. A window's `status` is derived from the logical date: `SCHEDULED` before the start date, `ACTIVE` across the covered dates, `ENDED` after the end date. What each policy does to a confirming order is specified in §3.5; independently of admission, an `ACTIVE` window drives the surge surcharge of §3.4. A depot's windows are listable with an optional `status` filter.

### 3.2. Dry-Ice Safety: Handler Certifications

Dry ice cannot change hands at a depot unless the receiving customer employs a certified handler. A `SafetyOfficer` registers a `HandlerCertification` against a customer account with the `handler_name`, an external `certificate_number`, the `max_dry_ice_lbs` the certificate covers per delivery (at least one pound), and an `expires_at` instant. New certifications are `ACTIVE`.

A certification qualifies an order when three conditions all hold: its status is `ACTIVE`; its `expires_at` is no earlier than the end of the order's event window; and its `max_dry_ice_lbs` is at least the order's total `dry_ice_lbs`. An order containing dry ice that finds no qualifying certification at confirm time is rejected with `ERR_DRY_ICE_CERT_REQUIRED` — whether because none exists, the only candidate is `SUSPENDED`, its poundage cap is too small, or it lapses before the event window ends.

Suspension and reinstatement are `SafetyOfficer` operations. Suspending moves `ACTIVE` to `SUSPENDED`; reinstating moves `SUSPENDED` back to `ACTIVE`, but only while the certificate remains temporally valid — reinstating one whose `expires_at` has passed the logical clock is rejected with `ERR_INVALID_STATE`. Each transition increments the certification's `version`. Independently of any officer action, the ops-run expiry sweep moves both `ACTIVE` and `SUSPENDED` certifications to `EXPIRED` once `expires_at` falls before the clock, and `EXPIRED` is terminal. A customer's certifications are listable as a paginated collection.

### 3.3. Recurring Routes and Standing Orders

A bar or restaurant's standing weekly order is captured as a recurring route. A `CustomerAgent` creates one naming the owning `customer_id` — which must equal the agent's own `X-User-ID`, else `ERR_FORBIDDEN` — the servicing `depot_id`, a `weekday` (`MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, or `SUN`), a delivery window `window_start` and `window_end` with the start strictly before the end, and `standing_lines`: rows of `product_form`, `packaging`, and `quantity_units`, each quantity at least one (`ERR_LINE_QUANTITY_INVALID`). A new route is immediately `ACTIVE`.

One customer may hold at most one live route per weekday: creating a route, or resuming a paused one, while another route for the same customer and weekday is `ACTIVE` or `PAUSED` fails with `ERR_ROUTE_SCHEDULE_CONFLICT`.

Standing lines can be replaced wholesale through the standing-order patch, allowed from either `ACTIVE` or `PAUSED`. The patch is one of the platform's two OCC-guarded writes: it must carry `expected_route_version` equal to the route's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a pause/resume cycle or an earlier patch will have advanced the version beyond what the client observed (§2.7). A successful patch revalidates each line's quantity (`ERR_LINE_QUANTITY_INVALID`) and increments the route's `version` by one.

Pausing flips `ACTIVE` to `PAUSED`; resuming flips back, re-running the weekday-uniqueness check; terminating from either state lands on `TERMINATED`, excluding the route from all future order generation. All three actions require the acting agent to own the route (`ERR_FORBIDDEN`), and pause and resume each increment the route's `version` by one.

Generation itself happens inside the ops-run checkpoint (§3.9). For each `ACTIVE` route the sweep finds the next occurrence: the first date bearing the route's `weekday` that falls strictly after `last_generated_date` — or, while that field is still null, on or after the current logical date — and no more than three days beyond the current logical date. Each occurrence spawns a new order in `DRAFT` with channel `DELIVERY`, its `recurring_route_id` pointing back to the route, `event_date` set to the occurrence date, and the window and lines copied from the route's window and `standing_lines`; the sweep then advances `last_generated_date` to the occurrence date and increments the route's `version`, which also makes generation idempotent per date. Routes are listable per customer or per depot with an optional `status` filter.

### 3.4. Composing, Quoting, and Repricing an Order

Every order lives on two parallel state dimensions recorded on the same row: `fulfillment_status` (`DRAFT`, `QUOTED`, `CONFIRMED`, `WAITLISTED`, `STAGED`, `READY_FOR_PICKUP`, `IN_TRANSIT`, `DELIVERED`, `PICKED_UP`, `NO_SHOW`, `CANCELLED`) and `billing_status` (`UNBILLED`, `INVOICED`, `PAID`). The fulfillment dimension advances through the quoting, reservation, confirmation, staging, dispatch, and pickup actions of §3.4 through §3.7; the billing dimension moves only through the invoice attach, void, and payment cascades of §3.8. Transitions on one dimension never require a particular value of the other except where this document states one.

A `CustomerAgent` composes an order with a payload naming the `customer_id` (equal to the caller's `X-User-ID`, on the ownership rule of §2.6), the fulfilling `depot_id`, a `channel` of `DELIVERY` or `WILL_CALL`, the `event_date`, and the service window `window_start` and `window_end`. The event date must fall at least one day after the current logical date — an order for today is too soon and is rejected with `ERR_EVENT_TOO_SOON`, the lead-time check firing before line-quantity validation at creation — and the same lead-time check fires again at confirmation (§3.5). The payload's `lines` array must be non-empty; each line declares a `product_form` of `BLOCK`, `CUBE`, or `DRY_ICE`, a `packaging` of `BAG` or `PALLET`, and a `quantity_units` of at least one (`ERR_LINE_QUANTITY_INVALID`). Creation persists the order in `DRAFT` with `billing_status` `UNBILLED`, writes its line rows, leaves `recurring_route_id` null unless the order was spawned by route generation, and leaves the pricing fields uncomputed until quoting.

Two physical measures are derived from the lines at all times. `pallets_required` sums, across lines, the `quantity_units` of each `PALLET`-packaged line plus — for `BAG`-packaged lines — the quantity divided by twenty and rounded up to a whole pallet space. `dry_ice_lbs` sums, across `DRY_ICE` lines only, the quantity times the unit weight: ten pounds per bag unit, five hundred per pallet unit. Each line also exposes a computed `unit_weight_lbs` from the same weight table — seven pounds for a bag of cubes, nine hundred sixty for a pallet of cubes, twenty-five for a bag of blocks, three hundred for a pallet of blocks, ten for a bag of dry ice, five hundred for a pallet of dry ice.

Quoting moves `DRAFT` to `QUOTED`. An `ACTIVE` price book must exist at that moment, else `ERR_PRICE_BOOK_NOT_ACTIVE`. Quoting pins the book onto the order as `price_book_id` and `price_book_version`, snapshots the matched tier's `unit_price_cents` onto every line, computes the full price stack described below with `pricing_mode` `PROVISIONAL`, and stamps `quoted_at` from the logical clock.

Line pricing is tiered and flat. For each line, the system selects the pinned book's pricing row matching the line's `product_form` and `packaging`, then the tier whose `tier_min_units` the quantity reaches and whose `tier_max_units` — when not null — the quantity does not exceed; when several tiers satisfy a quantity the one with the greatest `tier_min_units` wins, and a line no tier matches at all fails the evaluation with `ERR_INVALID_REQUEST` (HTTP 400). The matched tier's `unit_price_cents` prices the entire quantity; there is no marginal banding. Dry-ice lines additionally absorb a handling premium of seven percent — 700 basis points — folded into the line total before rounding: the quantity times the unit price, increased by the premium. Every line's `line_total_cents` is rounded half up to a whole cent individually, before any summation; non-dry-ice lines, being exact integer products, are unaffected by that rounding.

The order's price stack is then assembled in a pinned evaluation order, which resolves the otherwise circular-looking dependency among fee, discount, and surcharge. First, `merchandise_subtotal_cents` is the sum of the already-rounded line totals. Second, `discount_cents` comes from the `volume_discount_tiers`: the highest row whose `threshold_cents` the pre-discount subtotal reaches supplies its `discount_bps`, and the discount is the subtotal times those basis points divided by ten thousand, rounded half up — no satisfied tier means no discount. Third, the post-discount subtotal is the merchandise subtotal less the discount. Fourth, `delivery_fee_cents` is zero for `WILL_CALL` orders, zero when the post-discount subtotal reaches the book's `free_delivery_threshold_cents`, and otherwise the book's `delivery_fee_cents`. Fifth, when a surge window covering the event date is `ACTIVE` at evaluation time, `surcharge_cents` is the post-discount subtotal times the book's `surge_surcharge_bps` divided by ten thousand, rounded half up; otherwise the surcharge is zero. Sixth, `deposit_cents` sums, over `PALLET` lines, the quantity times the book's `pallet_deposit_cents` — the deposit is exempt from both the discount base and the surcharge base. Finally, `total_cents` is the post-discount subtotal plus the delivery fee, the surcharge, and the deposit.

This stack exists in two variants. The `PROVISIONAL` variant, produced by quoting and repricing, reads the book `ACTIVE` at evaluation time and treats the surcharge as applicable when a covering window is `ACTIVE` at that same moment; the result is stored on the order and returned in the quote response. The `FINAL` variant, produced by confirmation and waitlist promotion, keeps the order's pinned book for lines, discount, fee, and deposit even if that book has since been superseded, and re-evaluates surge coverage at the confirmation or promotion moment. Because book activations and surge windows move with the logical clock between quote and confirm, provisional and final totals for identical lines legitimately differ.

A quoted order can be re-quoted against the book that is active now. Repricing is the second OCC-guarded write: the request must carry `expected_order_version` matching the order's current `version`, with mismatches rejected as `ERR_STALE_VERSION` (HTTP 412) — each reprice legitimately re-pins the book and recomputes provisional totals, so a writer carrying an older observed version would otherwise overwrite a state it never saw. Repricing re-pins `price_book_id` and `price_book_version` (failing with `ERR_PRICE_BOOK_NOT_ACTIVE` when no book is active), recomputes the provisional stack, refreshes `quoted_at`, and increments the order's `version` by one. Quoting requires `DRAFT` and repricing requires `QUOTED`; attempting either from another state is rejected as `ERR_INVALID_STATE`.

Orders are readable individually with all computed pricing fields, and the collection supports optional filters `customer_id`, `depot_id`, `recurring_route_id`, `price_book_id`, `delivery_slot_id`, and `status`, the last matching only the order's `fulfillment_status`. An order's lines, its cold-storage holds, and its waitlist entries are each exposed as paginated sub-lists of the order.

### 3.5. Reserving Capacity and Confirming the Order

Delivery capacity is sold in slots. A `Dispatcher` opens a slot for a depot with a `date` no earlier than the current logical date (`ERR_DELIVERY_WINDOW_PAST`), a window `window_start` and `window_end` with the start before the end, and a `capacity_pallets` of at least one. A slot begins `OPEN` with `reserved_pallets` at zero. Its reserved total is the sum of `pallets_required` over orders linked to it whose fulfillment is `QUOTED`, `CONFIRMED`, `WAITLISTED`, `STAGED`, or `IN_TRANSIT`; the slot turns `FULL` the moment the reserved total reaches capacity, and releases can return it to `OPEN`. Once the slot's date falls behind the current logical date, the ops-run closure sweep moves it to `CLOSED`; historical reservations are unaffected, but no new reservation is accepted. A depot's slots are listable with optional `date` and `status` filters.

Reserving a slot keeps the order in `QUOTED` while attaching capacity. The request names a `delivery_slot_id`, which must exist (`ERR_NOT_FOUND`). The reservation then passes a fixed gauntlet: the order's channel must be `DELIVERY` — will-call orders have no slot — and it must not already hold a reservation, since re-reservation requires cancelling first (both `ERR_INVALID_STATE`); the slot must belong to the order's depot and carry a date equal to the order's `event_date`, and must not be `CLOSED` (`ERR_INVALID_STATE`). The business checks then apply in their pinned order: first containment — the slot's window must cover the order's window, slot start no later than order start and order end no later than slot end, else `ERR_WINDOW_OUTSIDE_SLOT`; then depot posture — a `FROZEN` depot accepts no new reservation, `ERR_POSTURE_FROZEN`; then capacity — the slot's reserved pallets plus the order's `pallets_required` must not exceed `capacity_pallets`, with equality admitted, else `ERR_SLOT_CAPACITY_EXCEEDED`. A successful reservation sets the order's `delivery_slot_id`, raises the slot's reserved total (flipping `OPEN` to `FULL` at equality), and increments both the order's `version` and the slot's `version` by one.

Confirmation is the order's point of commitment and its strictest gate, available from `QUOTED`. After the generic ladder of §2.6, the business gates evaluate in this pinned order, and the ordering matters because an early failure masks later ones. First stands dry-ice safety: when the order's `dry_ice_lbs` is positive, the customer must hold a qualifying certification as defined in §3.2, else `ERR_DRY_ICE_CERT_REQUIRED`. Next, the lead-time check is re-run: the `event_date` must still be at least one day beyond the current logical date, else `ERR_EVENT_TOO_SOON`. A `DELIVERY`-channel order must already hold a slot reservation, else `ERR_INVALID_STATE`. The capacity gate follows — the dry-ice bunker exclusion for orders containing dry ice, or the freezer peak-overlap test for orders without it, never both — then surge admission, and only then the fiscal gates: the customer's `standing` must be `GOOD` (`ERR_CREDIT_HOLD`, HTTP 402), and finally the forward-looking credit check of §3.8 must admit the order (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402, equality admitted). Because of this ordering, a missing certificate surfaces before a capacity problem, and a capacity problem before a credit problem.

The bunker rule protects the ventilated dry-ice compartment. The candidate's buffered interval runs from the event window's start to ninety minutes past its end — a sixty-minute grace for pickup or dispatch plus a thirty-minute ventilation buffer, both pinned constants. If that interval intersects any other cold-storage hold of the same depot zoned `DRY_ICE_BUNKER` and currently `RESERVED` or `OCCUPIED`, confirmation is rejected with `ERR_HOLD_INTERVAL_CONFLICT`. Intervals are half-open: a candidate whose window starts exactly when an existing buffered interval ends is admitted, so adjacency at the ventilation-buffer boundary is allowed.

For orders bound for the general freezer, admission is a peak-overlap test rather than a point-in-time one. The candidate interval runs from four hours before the event window's start — the staging lead — to sixty minutes past its end. At every instant within it, the pallets held by overlapping same-depot general-freezer holds in `RESERVED` or `OCCUPIED`, plus the candidate's own `pallets_required`, must stay within the depot's `freezer_capacity_pallets`; any instant that would overflow rejects the confirmation with `ERR_FREEZER_CAPACITY_EXCEEDED`. Half-open semantics apply here too, and bunker holds neither consume freezer pallets nor enter these sums (§2.9).

Surge admission consults the windows covering the order's `event_date` that are `ACTIVE` at confirm time. With no covering window, or a covering policy of `OPEN`, the order is admitted — the surcharge of §3.4 still applies. A `CLOSED` policy rejects outright with `ERR_SURGE_ADMISSION_CLOSED`. A `RATIONED` policy admits only while the depot's committed pallet total for that date — the sum of `pallets_required` over same-depot orders for the same date in `CONFIRMED`, `STAGED`, `READY_FOR_PICKUP`, or `IN_TRANSIT` (waitlisted orders do not commit) — plus the candidate's own requirement stays within the window's `daily_pallet_cap`, equality admitted. When several windows cover the date, every covering window is consulted: any `CLOSED` among them rejects, and every covering `RATIONED` window must individually admit the candidate — a single rationing failure forks the order to `WAITLISTED`.

A confirmed order recomputes its price stack in the `FINAL` variant against the pinned book and the surge windows active at that moment, stamps `confirmed_at`, and spawns its cold-storage hold (§3.6) in `RESERVED`; the depot's freezer aggregates and posture are recomputed, and both the order's `version` and the depot's `version` increment by one.

When rationing denies headroom and every other confirm gate has passed, the order does not fail — it forks to `WAITLISTED`. The fork enqueues a `WaitlistEntry` in `QUEUED` carrying the `order_id`, the contended `depot_id`, and `requested_pallets` copied from the order's `pallets_required`, stamped with `queued_at`; an order holds at most one `QUEUED` entry. Pricing remains `PROVISIONAL`, no cold-storage hold is created, and any slot reservation is retained — the waitlisted order still occupies its slot capacity. How the entry is later promoted, withdrawn, or expired is the subject of §3.6.

### 3.6. Cold Storage Holds, Cancellation, and the Waitlist

Confirmation reserves physical space. The hold created for a confirmed order copies the order's `depot_id` and `pallets_required`, links back through its `order_id`, and takes a `zone`: `DRY_ICE_BUNKER` when the order contains any dry-ice line, `GENERAL_FREEZER` otherwise. Its `interval_start` and `interval_end` are zone-dependent. A general-freezer hold opens its `interval_start` four hours before the event window's start — the staging lead — and closes its `interval_end` sixty minutes past the window's end, the pickup or dispatch grace. A bunker hold opens its `interval_start` at the window's start and closes its `interval_end` ninety minutes past the window's end, the same grace plus the thirty-minute ventilation buffer. Holds are born `RESERVED`; staging moves them to `OCCUPIED`; and `RELEASED` or `EXPIRED` end them. A depot's holds are listable with optional `status` and `zone` filters, and an order's holds are listable as a sub-list of the order.

Staging is a `DepotManager` action that moves the order from `CONFIRMED` to `STAGED` and requires a `RESERVED` hold for the order to exist (`ERR_INVALID_STATE` otherwise). The hold flips from `RESERVED` to `OCCUPIED` — the depot's reserved total is unchanged, but the occupancy clock starts — and both the order's `version` and the hold's `version` increment by one.

Any release of a hold — cancellation, pickup, dispatch start, or manual release — subtracts its pallets from the depot's `freezer_reserved_pallets`, recomputes posture, and, when that recompute lifts the depot out of `FROZEN`, immediately runs the waitlist promotion sweep described below. A `DepotManager` may also release a `RESERVED` or `OCCUPIED` hold manually — a damaged-stock write-off, for instance — which frees the space while leaving the linked order's own state untouched.

Cancelling unwinds whatever the order has accumulated, in proportion to how far it got. Whatever the starting state, the order itself lands on `CANCELLED` before any release hop runs, so its pallets no longer count toward slot and surge-committed totals during the cascade that follows. From `DRAFT` nothing exists to unwind; the cancellation simply lands on `CANCELLED` and increments the order's `version`. From `QUOTED`, a held slot reservation is released: `delivery_slot_id` clears, the slot's reserved total drops by the order's pallets, and a `FULL` slot can reopen to `OPEN`. From `WAITLISTED`, the `QUEUED` entry moves to `WITHDRAWN` and any slot reservation is likewise released.

Cancellation from `CONFIRMED` is the platform's deepest cascade, four hops long. Before the hops, the slot reservation, if any, is released as above. Hop one: the order's `RESERVED` hold moves to `RELEASED` and its pallets leave the depot's reserved total. Hop two: the depot's posture is recomputed from the newly freed space — a depot may move from `FROZEN` back to `OPEN` here. Hop three: posture having left `FROZEN` triggers the waitlist promotion selection, and the top-ranked `QUEUED` entry becomes `PROMOTED`. Hop four: the promoted order moves from `WAITLISTED` to `CONFIRMED` with `FINAL` pricing, a stamped `confirmed_at`, and a fresh `RESERVED` hold — after which the depot's aggregates and posture are recomputed once more. A single cancellation can therefore confirm someone else's order.

Promotion is by selection, not luck. Candidates are `QUEUED` entries of the depot whose orders are still `WAITLISTED`, whose `event_date` falls strictly after the current logical date, and whose dry-ice needs — if any — are covered by a qualifying `ACTIVE` certification as defined in §3.2. They rank by the owning customer's `tier`, `PRIORITY` before `STANDARD`; ties break by earliest `queued_at`, then earliest order `event_date`, then earliest order `created_at`; the entry `id` is never consulted. Promotion walks that ranking greedily while headroom permits: the depot must not be `FROZEN`; any `ACTIVE` `RATIONED` window covering the entry's date must still fit the entry's `requested_pallets` within its committed total and `daily_pallet_cap`; and a retained slot reservation must still fit — the slot's reserved pallets plus the requested pallets not exceeding the slot's `capacity_pallets`. Each promotion stamps the entry's `promoted_at`, stamps the order's `confirmed_at`, recomputes the order's pricing in the `FINAL` variant against surge windows active at promotion time, creates its `RESERVED` hold, increments the order's `version` by one, and recomputes the depot — a recompute that is itself posture-affecting and may feed the next promotion decision in the same sweep. An empty candidate set or exhausted headroom is a silent no-op, never an error. The waitlist entry itself carries no `version`. A depot's entries are listable with an optional `status` filter.

A customer may also bow out directly: withdrawing a `QUEUED` entry is a `CustomerAgent` action that requires owning the linked order (`ERR_FORBIDDEN`), moves the entry to `WITHDRAWN`, moves the order from `WAITLISTED` to `CANCELLED`, and releases any retained slot reservation. The ops-run expiry sweep (§3.9) instead moves stale entries to `EXPIRED`, with the same cancellation and slot release applied to the linked order.

### 3.7. Dispatch Runs and Will-Call Fulfillment

Street-side fulfillment runs on dispatch runs. A `Dispatcher` plans one with a `depot_id`, a `run_date` no earlier than the current logical date (`ERR_DELIVERY_WINDOW_PAST`), a `vehicle_label`, a deck capacity `max_pallets` of at least one, and a `ventilated_dry_ice_cap_lbs` of at least zero — the ventilated compartment's dry-ice poundage limit. The run begins `PLANNED`.

Assignment is atomic and pre-lock. The run's own guards fire before the listed identifiers are even resolved: assigning to a non-`PLANNED` run fails with the run's state error (`ERR_ALREADY_TERMINAL` or `ERR_INVALID_STATE`) even when an `order_ids` entry does not exist. The dispatcher lists `order_ids`; every listed order must be `STAGED`, channel `DELIVERY`, homed at the run's depot, dated to the run's `run_date`, and not already linked to a run (`ERR_INVALID_STATE`). Two aggregate checks then apply, ventilation before deck capacity: the run's committed dry-ice pounds plus the candidates' `dry_ice_lbs` must stay within `ventilated_dry_ice_cap_lbs` (`ERR_DRY_ICE_VENTILATION_EXCEEDED`), and the committed pallets plus the candidates' `pallets_required` must stay within `max_pallets` (`ERR_RUN_CAPACITY_EXCEEDED`). Any violation rejects the entire assignment — no partial links — while success sets `dispatch_run_id` on every listed order. A run's `assigned_pallets` and `assigned_dry_ice_lbs` sum those measures over its linked orders in `STAGED`, `IN_TRANSIT`, or `DELIVERED`.

Locking moves `PLANNED` to `LOCKED` and closes the manifest to further assignment. Starting requires at least one assigned order (`ERR_INVALID_STATE`) and moves `LOCKED` to `IN_PROGRESS` with a three-hop cascade: each assigned order goes from `STAGED` to `IN_TRANSIT`; each such order's `OCCUPIED` hold is `RELEASED` — the product has left the freezer — returning its pallets to the depot; and the depot's posture recomputes, with any easing out of `FROZEN` triggering the promotion sweep. Completion moves `IN_PROGRESS` to `COMPLETED`: every assigned order goes from `IN_TRANSIT` to `DELIVERED` with `fulfilled_at` stamped from the logical clock, becoming invoice-eligible while its `billing_status` stays `UNBILLED` (§3.8). Cancelling a `PLANNED` or `LOCKED` run lands on `CANCELLED` and clears `dispatch_run_id` from every assigned order, which remain `STAGED`. Runs are listable per depot with optional `run_date` and `status` filters, individually fetchable, and a run's manifest is readable as its order sub-list.

Will-call orders never touch a run. A `DepotManager` marks a staged will-call order ready — from `STAGED` to `READY_FOR_PICKUP`, rejected with `ERR_INVALID_STATE` for delivery-channel orders — incrementing the order's `version`. The pickup itself belongs to the customer: the owning `CustomerAgent` confirms it (any other agent is `ERR_FORBIDDEN`), and only while the logical clock has not passed the `interval_end` of the order's active hold — or of its most recent hold, when none is active — (`ERR_PICKUP_WINDOW_EXPIRED`). Success moves `READY_FOR_PICKUP` to `PICKED_UP`, releases the `OCCUPIED` hold with the usual depot recompute and promotion-on-easing, and stamps `fulfilled_at`.

A customer who never shows is swept, not forgotten: when the ops-run checkpoint finds a will-call order still `READY_FOR_PICKUP` with the logical clock past its hold's `interval_end`, the order moves to `NO_SHOW` and the hold to `EXPIRED`, again with depot recompute and promotion-on-easing, and `fulfilled_at` is stamped — a no-show remains billable. `DELIVERED`, `PICKED_UP`, and `NO_SHOW` are thus the three billable terminal fulfillments; `CANCELLED` is the non-billable one.

### 3.8. Invoicing, Payments, and Customer Credit

The platform meters credit in two variants, and confusing them inverts decisions. The settled variant sums `balance_due_cents` over the customer's invoices in `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE`; this is what `outstanding_exposure_cents` displays, so a customer with large confirmed-but-uninvoiced orders still shows zero. The confirm-time credit check uses the forward-looking variant: settled exposure plus the pipeline — the currently stored `total_cents` of every order of the customer in `CONFIRMED`, `WAITLISTED`, `STAGED`, `READY_FOR_PICKUP`, `IN_TRANSIT`, `DELIVERED`, `PICKED_UP`, or `NO_SHOW` whose `billing_status` is still `UNBILLED` (the `FINAL` figure once an order is confirmed, still the `PROVISIONAL` quote while the order sits `WAITLISTED`). Confirmation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) when the forward-looking exposure plus the candidate order's `total_cents` exceeds the customer's `credit_limit_cents` plus the spendable `credit_balance_cents`; equality is admitted. Separately, any `OVERDUE` invoice puts `standing` on `HOLD`, which blocks confirmation earlier in the gauntlet with `ERR_CREDIT_HOLD` (HTTP 402) (§3.5).

Billing consolidates fulfilled work into invoices. A `BillingClerk` generates one with a `customer_id`, an inclusive `period_start`, and an exclusive `period_end` (the start must fall before the end). Eligible orders are those of the customer whose `billing_status` is `UNBILLED`, whose fulfillment is `DELIVERED`, `PICKED_UP`, or `NO_SHOW`, and whose `fulfilled_at` date falls within the period — inclusive of the start, exclusive of the end. Two rejections guard the operation, period-conflict checked first: if any non-`VOID` invoice already exists for the same customer and the same `period_start` and `period_end`, the request fails with `ERR_INVOICE_PERIOD_CONFLICT`; and if the eligible set is empty, with `ERR_NO_BILLABLE_ORDERS`. Attachment follows the orders' `fulfilled_at` from earliest to latest, ties broken by earliest `created_at`; the invoice's `merchandise_subtotal_cents`, `discount_cents`, `delivery_fee_cents`, `surcharge_cents`, `deposit_cents`, and `total_cents` are component-wise sums of the attached orders' `FINAL` amounts. Each attached order moves from `UNBILLED` to `INVOICED`, has its `invoice_id` set, and its `version` incremented. The new invoice is `DRAFT`; its `due_date`, `issued_by_user_id`, and `voided_by_user_id` remain null.

Issuing is a separate `BillingClerk` act: it moves `DRAFT` to `ISSUED`, records the acting clerk's `X-User-ID` as `issued_by_user_id`, and sets `due_date` to the current logical date plus the customer's credit-terms offset — zero days for `PREPAID`, fifteen for `NET_15`, thirty for `NET_30`. From then on the invoice's `balance_due_cents` — its `total_cents` less its `amount_paid_cents` — counts toward the customer's settled exposure.

Payments arrive through a `BillingClerk` naming the `customer_id`, an `amount_cents` of at least one (`ERR_PAYMENT_AMOUNT_INVALID`), and a `method` of `ACH`, `CARD`, or `CASH`; the payment is stamped with `received_at` from the logical clock. Allocation is a deterministic waterfall. The eligible invoices are the customer's `ISSUED`, `PARTIALLY_PAID`, and `OVERDUE` ones, ordered by earliest `due_date` then earliest `created_at`. The remaining amount walks that order: each invoice receives the lesser of the remaining amount and its own `balance_due_cents`; the allocation is appended to the payment's `allocations` trace as an `invoice_id` / `applied_cents` pair in allocation order; and the invoice lands on `PAID` when its balance reaches zero, otherwise `PARTIALLY_PAID` — except that an `OVERDUE` invoice stays `OVERDUE` under a partial payment and only full payment lifts it to `PAID`. Whatever remains unallocated is the payment's `overpayment_cents`, credited to the customer's `credit_balance_cents`, while `applied_cents` records the allocated total. After the loop the customer's `standing` is recomputed — `GOOD` when no `OVERDUE` invoice remains — and `outstanding_exposure_cents` is recomputed. Payments are immutable ledger entries, listable per customer as a paginated collection.

Full payment cascades outward: every order attached to an invoice that reaches `PAID` sees its own `billing_status` move from `INVOICED` to `PAID`. That state is terminal only when the order's fulfillment has already reached `DELIVERED`, `PICKED_UP`, or `NO_SHOW` — which invoice attachment guarantees.

Voiding reverses an invoice, under segregation of duties. The voiding clerk's `X-User-ID` must differ from the invoice's `issued_by_user_id` whenever that field is set; the clerk who issued an invoice cannot void it, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). That check is evaluated first; only then does the prohibition on voiding a `PAID` invoice apply (`ERR_INVOICE_NOT_VOIDABLE`), while a `VOID` invoice is already terminal (`ERR_ALREADY_TERMINAL`). A successful void from `DRAFT`, `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE` records the clerk as `voided_by_user_id` and cascades in hops: every attached order reverts from `INVOICED` to `UNBILLED` with its `invoice_id` cleared — becoming invoice-eligible again; any `amount_paid_cents` already collected is moved into the customer's `credit_balance_cents` and reset to zero on the invoice; and the customer's `standing` and `outstanding_exposure_cents` are recomputed — voiding the last `OVERDUE` invoice restores `GOOD`. Invoices are fetchable individually, listable per customer with an optional `status` filter, and their attached orders are readable as a sub-list.

Aging is enforced by the ops-run checkpoint rather than by reads: an `ISSUED` or `PARTIALLY_PAID` invoice whose `due_date` falls behind the current logical date while a balance remains moves to `OVERDUE`, pushing the customer's `standing` from `GOOD` to `HOLD` while the balance continues to count toward settled exposure (§3.9).

### 3.9. The Ops-Run Checkpoint

Each depot advances its derived world through an admin-only ops-run checkpoint — a `PlatformAdmin` capability that executes eight sweeps in a pinned order, every step observing the effects of the steps before it, and then increments the depot's `ops_run_index` by one (advancing the depot's `version` as well). The slot-closure, no-show, waitlist-expiry, route-generation, and promotion sweeps act only on this depot's records; price-book activation, certification expiry, and invoice aging are platform-global. The steps run as follows. First, price-book activation: `SCHEDULED` books whose `effective_from` has reached the logical clock become `ACTIVE`, superseding the incumbent book; when several books come due in one checkpoint they activate in ascending `effective_from` order (ties by creation order), each superseding the last, so the latest-effective one ends `ACTIVE`. Second, certification expiry: `ACTIVE` and `SUSPENDED` certifications whose `expires_at` has passed the clock become `EXPIRED`. Third, slot closure: `OPEN` and `FULL` slots whose date has fallen behind the current logical date become `CLOSED`. Fourth, the no-show sweep: `OCCUPIED` holds past their `interval_end` whose linked will-call order is `READY_FOR_PICKUP` move to `EXPIRED`, and the order to `NO_SHOW`, with depot aggregates and posture recomputed. Fifth, invoice aging: `ISSUED` and `PARTIALLY_PAID` invoices past `due_date` with an outstanding balance become `OVERDUE`, with customer standing recomputed. Sixth, waitlist expiry: `QUEUED` entries whose order's `event_date` is on or before the current logical date become `EXPIRED`, cancelling the linked order and releasing any retained slot reservation. Seventh, route generation: each `ACTIVE` route spawns its next occurrence as described in §3.3, within a lead horizon of three days beyond the current logical date, idempotent per date through `last_generated_date`. Eighth, waitlist promotion: the selection of §3.6 runs for this depot. The checkpoint returns the new `ops_run_index` together with per-step identifier lists: `activated_book_ids`, `expired_cert_ids`, `closed_slot_ids`, `expired_hold_ids`, `no_show_order_ids`, `overdue_invoice_ids`, `expired_entry_ids`, `generated_order_ids`, and `promoted_entry_ids`. Each list follows its sweep's iteration order — creation order, except `activated_book_ids`, which follows the activation order just described, and `promoted_entry_ids`, which follows promotion order across the sweeps that triggered it. Slot closure, invoice aging, waitlist expiry, and route generation compare dates; book activation, certification expiry, and the no-show sweep compare instants.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state transition — return `200 OK`. All paths are mounted at the service root. Request payloads, derived fields, and side effects for each operation are specified in §2 and §3; this table collects only the HTTP contract and the authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving; startup default 2026-05-01T00:00:00Z) | PlatformAdmin |
| POST | `/depots` | Create a depot | PlatformAdmin |
| GET | `/depots/{id}` | Fetch a depot with computed freezer fields and posture | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/depots/{id}/run-ops` | Execute the eight pinned ops-run sweeps and increment `ops_run_index` | PlatformAdmin |
| POST | `/customers` | Create a customer account | PlatformAdmin |
| GET | `/customers/{id}` | Fetch a customer with computed balance, exposure, and standing | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/customers/{id}/certifications` | Register a dry-ice handler certification for the customer | SafetyOfficer |
| GET | `/customers/{id}/certifications` | List certifications of a customer (paginated) | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/certifications/{id}/suspend` | Suspend a certification | SafetyOfficer |
| POST | `/certifications/{id}/reinstate` | Reinstate a suspended certification (expired certs rejected) | SafetyOfficer |
| POST | `/price-books` | Create a price book; activates immediately iff `effective_from` has been reached | PlatformAdmin |
| GET | `/price-books` | List price books (paginated) | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/surge-windows` | Create a surge window for a depot | PlatformAdmin |
| GET | `/depots/{id}/surge-windows` | List surge windows of a depot (paginated) | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/recurring-routes` | Create a recurring route (initial status `ACTIVE`) | CustomerAgent |
| GET | `/recurring-routes/{id}` | Fetch a recurring route | PlatformAdmin, DepotManager, CustomerAgent |
| GET | `/customers/{id}/routes` | List recurring routes of a customer (paginated) | PlatformAdmin, DepotManager, CustomerAgent |
| GET | `/depots/{id}/routes` | List recurring routes served by a depot (paginated) | PlatformAdmin, DepotManager, Dispatcher |
| PATCH | `/recurring-routes/{id}/standing-order` | Replace standing lines (OCC on `expected_route_version`) | CustomerAgent |
| POST | `/recurring-routes/{id}/pause` | Pause a route (`ACTIVE` → `PAUSED`) | CustomerAgent |
| POST | `/recurring-routes/{id}/resume` | Resume a route (`PAUSED` → `ACTIVE`; uniqueness re-checked) | CustomerAgent |
| POST | `/recurring-routes/{id}/terminate` | Terminate a route (`ACTIVE`/`PAUSED` → `TERMINATED`) | CustomerAgent |
| POST | `/orders` | Create an order with inline lines (`DRAFT` / `UNBILLED`) | CustomerAgent |
| GET | `/orders/{id}` | Fetch an order with computed pricing fields | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| GET | `/orders` | List orders with optional filters (paginated) | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/orders/{id}/quote` | Quote a `DRAFT` order: pin the active price book, compute `PROVISIONAL` pricing | CustomerAgent |
| POST | `/orders/{id}/confirm` | Confirm a `QUOTED` order: `FINAL` pricing, admission gates, creates the `RESERVED` hold; may fork to `WAITLISTED` | CustomerAgent |
| POST | `/orders/{id}/cancel` | Cancel from `DRAFT`/`QUOTED`/`CONFIRMED`/`WAITLISTED` (compensating releases and promotion cascade) | CustomerAgent |
| POST | `/orders/{id}/reprice` | Re-quote a `QUOTED` order against the currently active book (OCC on `expected_order_version`) | CustomerAgent |
| POST | `/orders/{id}/reserve-slot` | Reserve delivery-slot capacity for a `QUOTED` delivery order | CustomerAgent |
| POST | `/orders/{id}/stage` | Stage a `CONFIRMED` order into cold storage (hold `RESERVED` → `OCCUPIED`) | DepotManager |
| POST | `/orders/{id}/mark-ready` | Mark a staged will-call order ready for pickup | DepotManager |
| POST | `/orders/{id}/confirm-pickup` | Customer picks up a will-call order (hold released) | CustomerAgent |
| GET | `/orders/{id}/lines` | List lines of an order | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| GET | `/orders/{id}/holds` | List cold-storage holds of an order | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| GET | `/orders/{id}/waitlist-entries` | List waitlist entries of an order | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/delivery-slots` | Create a delivery slot for a depot | Dispatcher |
| GET | `/depots/{id}/delivery-slots` | List delivery slots of a depot (paginated) | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| GET | `/depots/{id}/holds` | List cold-storage holds of a depot (paginated) | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/cold-storage-holds/{id}/release` | Manually release a `RESERVED`/`OCCUPIED` hold (e.g. damaged stock write-off) | DepotManager |
| POST | `/dispatch-runs` | Create a dispatch run | Dispatcher |
| GET | `/dispatch-runs/{id}` | Fetch a dispatch run | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| GET | `/depots/{id}/dispatch-runs` | List dispatch runs of a depot (paginated) | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/dispatch-runs/{id}/assign` | Atomically assign `STAGED` delivery orders to a `PLANNED` run (capacity and ventilation checks) | Dispatcher |
| POST | `/dispatch-runs/{id}/lock` | Lock a run (no further assignments) | Dispatcher |
| POST | `/dispatch-runs/{id}/start` | Start a locked run: orders `STAGED` → `IN_TRANSIT`, holds released | Dispatcher |
| POST | `/dispatch-runs/{id}/complete` | Complete a run: orders `IN_TRANSIT` → `DELIVERED` (invoice-eligible) | Dispatcher |
| POST | `/dispatch-runs/{id}/cancel` | Cancel a `PLANNED`/`LOCKED` run; orders stay `STAGED` and unlinked | Dispatcher |
| GET | `/dispatch-runs/{id}/orders` | List orders assigned to a run | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| GET | `/depots/{id}/waitlist-entries` | List waitlist entries of a depot (paginated) | PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer, CustomerAgent |
| POST | `/waitlist-entries/{id}/withdraw` | Withdraw a `QUEUED` entry (order `WAITLISTED` → `CANCELLED`) | CustomerAgent |
| POST | `/invoices/generate` | Consolidate a customer's billable orders for a period into a `DRAFT` invoice | BillingClerk |
| GET | `/invoices/{id}` | Fetch an invoice with computed amounts | PlatformAdmin, BillingClerk, CustomerAgent |
| GET | `/customers/{id}/invoices` | List invoices of a customer (paginated) | PlatformAdmin, BillingClerk, CustomerAgent |
| POST | `/invoices/{id}/issue` | Issue a `DRAFT` invoice (sets `due_date` from terms, records issuer) | BillingClerk |
| POST | `/invoices/{id}/void` | Void a non-`PAID` invoice (segregation of duties; unapplies payments to customer credit; orders revert to `UNBILLED`) | BillingClerk |
| GET | `/invoices/{id}/orders` | List orders attached to an invoice | PlatformAdmin, BillingClerk, CustomerAgent |
| POST | `/payments` | Record a customer payment; waterfall-allocates to open invoices, overpayment to credit balance | BillingClerk |
| GET | `/customers/{id}/payments` | List payments of a customer (paginated, immutable ledger) | PlatformAdmin, BillingClerk, CustomerAgent |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the narratives of §2 and §3; this catalogue collects only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DRY_ICE_CERT_REQUIRED` | 409 Conflict |
| `ERR_DRY_ICE_VENTILATION_EXCEEDED` | 409 Conflict |
| `ERR_EVENT_TOO_SOON` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_PAST` | 409 Conflict |
| `ERR_WINDOW_OUTSIDE_SLOT` | 409 Conflict |
| `ERR_HOLD_INTERVAL_CONFLICT` | 409 Conflict |
| `ERR_PICKUP_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_LINE_QUANTITY_INVALID` | 400 Bad Request |
| `ERR_POSTURE_FROZEN` | 409 Conflict |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_FREEZER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ROUTE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_SURGE_ADMISSION_CLOSED` | 409 Conflict |
| `ERR_PRICE_BOOK_NOT_ACTIVE` | 409 Conflict |
| `ERR_RUN_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_INVOICE_PERIOD_CONFLICT` | 409 Conflict |
| `ERR_NO_BILLABLE_ORDERS` | 409 Conflict |
| `ERR_CREDIT_HOLD` | 402 Payment Required |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_PAYMENT_AMOUNT_INVALID` | 400 Bad Request |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 Conflict |
