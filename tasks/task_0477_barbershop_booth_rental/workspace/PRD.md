# Barbershop Booth Rental API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Barbershop Booth Rental API, a back-office platform that runs the day-to-day economics of a multi-chair barbershop. The central business tension the system resolves is that two barbers standing side by side may be compensated under entirely different arrangements: one rents a chair for a flat daily fee and keeps everything the chair earns, while another splits a commission with the shop on every service. The same visit data — services rendered, add-ons applied, tips collected, products sold — therefore has to feed two distinct daily settlement formulas, and the platform must hold both interpretations consistently against a shared ledger.

Around that settlement core sits the full operational life of the shop. Customers either book a chair ahead of time against a specific barber's posted shift or take a walk-in number and wait their turn in a first-in-first-out queue. Each visit opens a sales ticket that may carry covered or discounted services for members, retail products that draw down on-hand stock, loyalty punches that mature into free-service rewards, and tips that flow entirely to the barber. Layered on top are the protective rules a real shop needs: a barber may not serve on an expired or suspended license, a customer who repeatedly fails to show is automatically barred from booking, and the shop owner can close the floor, void a mistaken sale, or finalize a barber's books for the day.

Because settlement figures and loyalty counters are derived from many concurrent operations, the platform treats consistency as a first-class concern. Every revenue-bearing action reconciles denormalized ledgers immediately, and the two operations most exposed to stale reads — scheduling a shift against shop configuration and finalizing a barber's day against their accruing revenue — are guarded by optimistic concurrency checks so that no writer can silently overwrite a view it never observed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly four roles, spelled precisely as `ShopOwner`, `Receptionist`, `Barber`, and `Customer`. When a request carries a syntactically valid user context but the role is not permitted to perform the requested operation — or an entity-backed actor reaches for a resource it does not own — the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles split into two identity styles. The `ShopOwner` and `Receptionist` roles are operator roles: when `X-User-Role` is `ShopOwner` or `Receptionist`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow calls for it, but it never compares an opaque identifier to any entity's `id`. The `Barber` and `Customer` roles are entity-backed. When `X-User-Role` is `Barber`, `X-User-ID` is the `id` of the acting `Barber`; ownership checks on any resource that references a `Barber` compare that resource's barber foreign key to `X-User-ID`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare that resource's customer foreign key to `X-User-ID`. Thus a `Customer` may read or act only on their own records — their own appointments, queue tickets, and customer profile — and a `Barber` may read only their own schedule, tickets, and settlements.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless an endpoint states otherwise, list results are sorted by their creation timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object so the client can page deterministically.

### 2.4. The Logical Clock

The platform runs against a logical clock rather than wall-clock time, so that license expiry, appointment punctuality, no-show grace, cancellation deadlines, and business-date bucketing are all reproducible. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it stays at this default and never falls back to real wall-clock time. An administrative test-driving capability sets the clock to an absolute instant supplied in the `to_iso8601` field. Every rule in this document that speaks of "the clock," "now," a date, or a time window reads this logical clock.

### 2.5. Common Resource Properties

Every resource carries a server-minted `id` formatted as a UUID with no type prefix; the `id` is identity only and is never supplied by the client. All resources also carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. Most resources additionally carry `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation) and `version` (an integer that starts at 1 on creation and increments by one on every mutation). The `version` field is the basis for optimistic concurrency control described in §2.7. All of the resources in this system — `Shop`, `Barber`, `Chair`, `BarberShift`, `ServiceMenuItem`, `AddOn`, `ProductSku`, `Membership`, `Customer`, `Appointment`, `QueueTicket`, `Ticket`, and `DailySettlement` — carry the full set of `id`, `created_at`, `updated_at`, and `version`. New resources are returned with HTTP 201; in-place mutations return HTTP 200.

### 2.6. Monetary Precision, Counters, and Reconciliation

All money in the system is held and exchanged as integer cents — there are no fractional cents and no floating-point money fields. Wherever a percentage or rate produces a fractional cent, the result is rounded half-up to a whole cent, and the precise point at which rounding happens is pinned per calculation in §3 (a per-line rounding rule must not be replaced by a sum-then-round rule, or vice versa, because the two diverge by a cent). Loyalty punches, reward credits, no-show strikes, product stock, and version numbers are all integers.

Several fields are denormalized running totals rather than client input, and the platform reconciles them immediately on each triggering event rather than recomputing them lazily. The shop tracks `gross_service_revenue_cents` and `gross_product_revenue_cents` as running sums across paid tickets; each barber tracks `unsettled_revenue_cents`, the sum of service revenue on their paid-but-not-yet-settled tickets; each customer tracks `punch_count`, `reward_credits`, and `no_show_strikes`. Whenever a checkout, void, no-show, or settlement changes one of these figures, the owning resource is mutated — its `updated_at` is refreshed and its `version` is incremented — exactly as for any other change.

### 2.7. Optimistic Concurrency Control

Two create operations in this system are guarded by optimistic concurrency control, because each one is computed against a parent resource whose `version` another writer may have advanced in the meantime.

Scheduling a shift is guarded against the owning shop. A shift-create request must carry `expected_shop_version`, the `version` of the `Shop` the client last observed. If `expected_shop_version` does not equal the shop's current `version` — for example because another writer reopened the shop or scheduled a shift that bumped the shop in the interim — the create is rejected with `ERR_STALE_SHOP_VERSION` at HTTP 412, so the client cannot create a shift against a stale view of shop configuration. This field is mandatory on shift creation.

Finalizing a barber's day is guarded against that barber. A settlement-create request must carry `expected_barber_version`, the `version` of the `Barber` the client last observed. Because every ticket checkout bumps the barber's `version` as it reconciles `unsettled_revenue_cents`, a settlement computed against a stale revenue snapshot would overwrite figures the client never saw; such a request is rejected with `ERR_STALE_BARBER_VERSION` at HTTP 412. This field is mandatory on settlement creation. No other endpoint accepts or requires a version field; endpoints not named here perform no concurrency check.

### 2.8. Nested Resource Retrieval and Validation Ordering

When a path names a resource by identifier, the server validates the path left to right and rejects on the first identifier that does not resolve, returning that identifier's specific not-found error — `ERR_SHOP_NOT_FOUND`, `ERR_BARBER_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_QUEUE_TICKET_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND`, as applicable.

Across the whole API, checks are applied in a fixed precedence so that the same failure always produces the same error. The order is: first, that the user context headers are present and well-formed (`ERR_MISSING_USER_CONTEXT`, 401); second, that the role is permitted and, for entity-backed actors, owns the targeted resource (`ERR_FORBIDDEN_ROLE`, 403); third, that every path identifier resolves (the not-found errors above, 404); fourth, that every foreign key carried in the body resolves within the shop (`ERR_REFERENCED_ENTITY_NOT_FOUND`, 404); fifth, that the body is well-formed — required fields present, enum values legal, numbers within their declared ranges, `end_utc` strictly later than `start_utc`, and any quantity at least 1 (`ERR_INVALID_REQUEST`, 400). Only once these structural checks pass does the system evaluate the business and state rules described in §3. Within an individual business operation, the relative ordering of its own business checks is stated alongside that operation in §3.

The body-FK existence check covers `shop_id`, `customer_id`, `barber_id`, `chair_id`, `service_item_id`, every member of `addon_ids`, every `product_sku_id` inside `product_lines`, and `membership_id` — any of which, if it names a resource that does not exist within the shop, yields `ERR_REFERENCED_ENTITY_NOT_FOUND`.

### 2.9. Catalog, Stock, and Listing Rules

Service items, add-ons, and retail products each carry a `status` of `LISTED` or `DELISTED`; membership plans carry `OFFERED` or `RETIRED`. A `DELISTED` catalog item may not be added to a new appointment, placed on a ticket line, or carried through checkout, and a `RETIRED` plan accepts no new subscribers. In every such case the rejection is `ERR_ITEM_DELISTED`. Delisting is a one-way transition (`LISTED → DELISTED`) performed by the owner; retirement is likewise one-way (`OFFERED → RETIRED`). A retail product additionally tracks on-hand units in `stock_qty`, which is drawn down at checkout and may never be driven below zero — a checkout whose product quantity exceeds available stock is refused.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Shop and Its Catalog

A `ShopOwner` brings a shop into existence by supplying its `name` together with the economic parameters that drive everything downstream: the `tax_rate_pct` (a sales-tax percentage between 0 and 30, where `8.5` means 8.5 percent), the `default_booth_rent_cents` charged to booth-rent barbers per settled day, and the `default_commission_pct` (between 0 and 100) the shop keeps on commission barbers' service revenue. Several further parameters are optional and fall back to documented defaults when omitted: `product_commission_pct` (0 to 100, default 0) is the share a commission barber earns on commission-eligible product sales; `no_show_fee_cents` (default 0) is the flat fee charged on a no-show; `no_show_strike_limit` (at least 1, default 3) is the strike count at which a customer is auto-suspended; `late_grace_minutes` (default 10) is both the punctuality grace window and the required buffer between shifts; `punch_reward_threshold` (at least 1, default 10) is how many completed paid visits earn one reward; and `punch_reward_value_cents` (default 0) is the service credit a redeemed reward is worth. A new shop is created `OPEN` with `version` 1 and its `gross_service_revenue_cents` and `gross_product_revenue_cents` ledgers at zero.

A shop's `status` governs whether the floor is operational. The owner may close an `OPEN` shop, transitioning `OPEN → CLOSED`, but only when there is no `Appointment` in `CHECKED_IN` and no `Ticket` in `OPEN` anywhere in the shop; otherwise the close is refused with `ERR_OPEN_TICKETS_EXIST`. Reopening moves `CLOSED → OPEN` with no precondition. Both the close and the reopen increment the shop's `version` by one. While a shop is `CLOSED`, booking, taking a queue ticket, checking in, serving, checking out, and marking no-shows are all blocked with `ERR_SHOP_CLOSED`.

Catalog construction is owner-only. A service menu item is defined by its `name`, `price_cents`, and `duration_minutes` (the scheduled chair time, at least 1 minute), plus a `membership_included` flag (default false) that, when true, fully waives the item's price for active members. An add-on carries a `name`, `price_cents`, an `extra_minutes` value (default 0) that lengthens the chair slot, and a `membership_discount_pct` (0 to 100, default 0) applied for active members. A retail product carries a `name`, `price_cents`, an on-hand `stock_qty` (default 0), and a `commission_eligible` flag (default false) marking it as earning product commission for the barber who rings it up. A membership plan carries a `name`, a `monthly_fee_cents`, and an `addon_discount_pct` (0 to 100, default 0) that applies to add-ons whose own per-add-on discount is zero. Chairs are the simplest catalog object: a chair is created with only a `label` and is created `AVAILABLE`, a status it keeps for its lifetime.

### 3.2. Barbers, Licenses, and the License Lifecycle

A `ShopOwner` registers a barber under a shop by providing `shop_id`, `full_name`, `license_number`, `license_expires_on` (an ISO 8601 calendar date), and the all-important `comp_model`, which is either `BOOTH_RENT` or `COMMISSION` and is fixed at creation because it selects the settlement formula for the rest of the barber's life in the system. For a booth-rent barber the owner may set `booth_rent_cents`; when omitted it inherits the shop's `default_booth_rent_cents`. For a commission barber the owner may set `commission_pct`; when omitted it inherits the shop's `default_commission_pct`. Every barber is created with employment `status` of `ACTIVE` and a `license_status` of `PENDING`, and begins with `unsettled_revenue_cents` at zero. The employment `status` is a lifecycle flag distinct from the license; barbers in this version are always created `ACTIVE` on that flag, and the license is tracked independently.

The license itself moves through `PENDING`, `ACTIVE`, `SUSPENDED`, and the terminal `REVOKED`, and the owner drives every transition. Activating a barber — used both for the first `PENDING → ACTIVE` step and to bring a `SUSPENDED → ACTIVE` license back — succeeds only if `license_expires_on` is on or after the logical clock's current date; an expired license is rejected with `ERR_LICENSE_EXPIRED`. Suspending an `ACTIVE` license moves it `ACTIVE → SUSPENDED` and, as a cascade, cancels every `BOOKED` appointment of that barber whose `start_utc` is later than the current clock, moving each `BOOKED → CANCELLED` with no no-show fee. Because activation can follow suspension, the license forms a cycle of `ACTIVE → SUSPENDED → ACTIVE`. Revoking a license is the terminal step and may be taken from `PENDING`, `ACTIVE`, or `SUSPENDED`; it moves the license to `REVOKED` and cascades two cancellations — every `SCHEDULED` shift of the barber whose `end_utc` is later than the clock is cancelled (`SCHEDULED → CANCELLED`), and every `BOOKED` appointment of the barber is cancelled (`BOOKED → CANCELLED`) with no no-show fee. A barber whose license is not `ACTIVE` may not be the barber on a new appointment, may not be resolved as the serving barber when a queue ticket is served, and may not be the barber on a ticket at checkout; each such attempt is refused with `ERR_BARBER_NOT_ACTIVE`.

A `Barber` actor may read their own profile, schedule, tickets, and settlements but performs no mutations; all license and registration actions belong to the `ShopOwner`.

### 3.3. Chairs, Shifts, and Their Scheduling Geometry

Shifts bind a barber to a chair for a window of time and form the scaffolding that appointments must fit inside. A `ShopOwner` schedules a shift by supplying `shop_id`, `barber_id`, `chair_id`, a `start_utc`, an `end_utc` that must be strictly later than `start_utc`, and the `expected_shop_version` required by the concurrency rule in §2.7. A shift's window is the half-open interval running from `start_utc` up to but not including `end_utc`. A successfully created shift is `SCHEDULED` and bumps the shop's `version` by one.

Two scheduled shifts on the same chair must not crowd each other: the system requires a closed buffer of at least `late_grace_minutes` between them, meaning the earlier shift's `end_utc` plus the grace window must be no later than the later shift's `start_utc`. Back-to-back shifts that merely touch — a gap of exactly zero — are therefore rejected, since the buffer is closed rather than half-open. A violation yields `ERR_SHIFT_OVERLAP`. This buffer semantics is deliberately stricter than the appointment-overlap rule in §3.4, where touching endpoints are allowed.

Cancelling a shift is owner-driven and is permitted only while the shift is `SCHEDULED`. The cancellation is refused if any `BOOKED` or `CHECKED_IN` appointment still falls within that shift's window on the same chair, in which case the system returns `ERR_SHIFT_HAS_APPOINTMENTS`; otherwise the shift moves `SCHEDULED → CANCELLED`, freeing the chair window. A cancelled shift is terminal.

### 3.4. Booking Appointments

Customers may reserve a chair ahead of time. A booking — which a `ShopOwner`, a `Receptionist`, or the `Customer` themselves may create — carries `shop_id`, `customer_id`, `barber_id`, `chair_id`, the `service_item_id` of the primary booked service, an optional `addon_ids` array (default empty), and a `start_utc`. The slot's `end_utc` is computed, not supplied: it is `start_utc` advanced by the service's `duration_minutes` plus the sum of `extra_minutes` over every add-on named in `addon_ids`. The resulting slot is half-open, covering `start_utc` up to but not including the computed `end_utc`. The appointment is created `BOOKED`, with `check_in_punctuality` initialized to `UNSET` and `ticket_id` null until check-in.

Booking is gated by a stack of conditions. The shop must be `OPEN`. The requested barber's `license_status` must be `ACTIVE`, else `ERR_BARBER_NOT_ACTIVE`. The customer's `status` must be `ACTIVE`; a suspended customer cannot book and is refused with `ERR_CUSTOMER_SUSPENDED`. The named service and any add-ons must be `LISTED`, else `ERR_ITEM_DELISTED`. Two temporal constraints then apply to the computed slot. First, the slot must lie fully within a single `SCHEDULED` shift of the same barber on the same chair — the shift's start at or before the slot's start, and the slot's end at or before the shift's end — failing which the booking is rejected with `ERR_OUTSIDE_SHIFT`. Second, the slot must not overlap any non-terminal appointment (one in `BOOKED` or `CHECKED_IN`) already on that chair; here the overlap test is half-open, so two slots that merely touch at an endpoint — one ending exactly when the next begins — do not conflict, while any true overlap is refused with `ERR_CHAIR_DOUBLE_BOOKED`.

A `BOOKED` appointment can move in one of three directions. It may be cancelled by a `Receptionist`, a `ShopOwner`, or the owning `Customer`, but only while the logical clock is strictly before `start_utc`; a cancellation at or after the start time is too late and is refused with `ERR_CANCEL_TOO_LATE`. A successful cancel moves `BOOKED → CANCELLED` with no fee. The other two directions — check-in and no-show — are described next.

### 3.5. Walk-Ins and the Queue

Walk-in customers take a numbered queue ticket instead of booking. A `ShopOwner`, `Receptionist`, or the `Customer` enqueues by supplying `shop_id`, `customer_id`, and an optional `requested_barber_id` naming a preferred barber (null means next-available). The new ticket is created `WAITING`, and its `queue_position` is assigned at the back of the line. Queue positions are 1-based and ordered by `created_at` ascending among the shop's `WAITING` tickets, and they are recomputed every time a ticket is enqueued, served, or abandoned. Taking a queue ticket requires an `OPEN` shop and an `ACTIVE` customer; a suspended customer is refused with `ERR_CUSTOMER_SUSPENDED`.

Serving a queue ticket is a `Receptionist`-or-`ShopOwner` action that pulls the front of the line forward. The shop must be `OPEN`. The ticket being served must be the front `WAITING` ticket: either `queue_position` equal to 1 overall, or — when the ticket names a `requested_barber_id` — the earliest-created `WAITING` ticket among those requesting that same barber. Serving anything other than the front is refused with `ERR_NOT_QUEUE_FRONT`. At serve time the system resolves `assigned_barber_id`: if the ticket named a `requested_barber_id`, that barber is used; otherwise the system picks the `ACTIVE` barber in the shop with the fewest tickets currently `SERVING`, breaking ties by earliest barber `created_at`. The resolved barber's `license_status` must be `ACTIVE`, else `ERR_BARBER_NOT_ACTIVE`. Serving moves the queue ticket `WAITING → SERVING`, opens a sales ticket (recording its `id` in the queue ticket's `ticket_id`), and recomputes the remaining waiting positions.

A waiting customer who leaves may be removed from the queue: abandoning, available to a `ShopOwner`, `Receptionist`, or the owning `Customer`, moves a `WAITING` ticket `WAITING → ABANDONED` and recomputes the positions of those still waiting. A queue ticket reaches its other terminal state, `DONE`, automatically when its sales ticket is paid, as covered in §3.6. Across all of these, only a `WAITING` queue ticket may be served or abandoned; acting on one in another state is an invalid-state error.

### 3.6. Opening, Pricing, and Checking Out Tickets

A sales ticket is the unit of revenue. It is never created directly by a client request — it is born `OPEN` as a side effect of check-in or of serving a queue ticket — and it records `customer_id`, `barber_id`, and exactly one of `appointment_id` (for appointment-sourced sales) or `queue_ticket_id` (for walk-ins). When a ticket opens, its `business_date` is stamped from the logical clock as the ISO 8601 date that becomes its settlement-bucket key.

Checking in a `BOOKED` appointment is a `Receptionist`-or-`ShopOwner` action requiring an `OPEN` shop (`ERR_SHOP_CLOSED`), the barber's `license_status` of `ACTIVE` (`ERR_BARBER_NOT_ACTIVE`), and the customer's `status` of `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`). Check-in moves the appointment `BOOKED → CHECKED_IN`, opens its ticket seeded with the appointment's `service_item_id` and `addon_ids`, sets the appointment's `ticket_id`, and stamps the ticket's `business_date`. It also records `check_in_punctuality`: the value is `ON_TIME` when the clock is at or before `start_utc` plus the shop's `late_grace_minutes`, and `LATE` otherwise. Checking in late is permitted and merely recorded; lateness carries no fee or strike, since only a no-show does that.

Before checkout, the lines on an `OPEN` ticket can be replaced wholesale by a `Receptionist` or `ShopOwner`: the line-edit operation accepts `service_line_ids` (the services sold), `addon_line_ids` (the add-ons sold), `product_lines` (an array of retail lines, each an object with a `product_sku_id` and a `qty`), `tip_cents`, and the `redeem_reward` flag. Only an `OPEN` ticket may be edited, and every catalog line named must be `LISTED` or the edit is refused with `ERR_ITEM_DELISTED`.

Checkout, performed by a `Receptionist` or `ShopOwner`, is the moment the ticket is priced and the books move. It is allowed only while the ticket is `OPEN`, and it enforces a battery of preconditions: the shop must be `OPEN` (`ERR_SHOP_CLOSED`); the barber's `license_status` must be `ACTIVE` (`ERR_BARBER_NOT_ACTIVE`); every catalog line must be `LISTED` (`ERR_ITEM_DELISTED`); every product line must have `stock_qty` at least its `qty` (`ERR_INSUFFICIENT_STOCK`); if `redeem_reward` is set, the customer's `reward_credits` must be at least 1 (`ERR_NO_REWARD_CREDITS`); and no `DailySettlement` may yet exist for this barber on this ticket's `business_date` (`ERR_DATE_ALREADY_SETTLED`). Once these pass, the ticket is priced as described below, the ticket moves `OPEN → PAID`, and a cascade of reconciliations fires.

Pricing computes `service_net_cents`, `product_net_cents`, `tax_cents`, and `total_due_cents` in a pinned order that must not be rearranged. The service-and-add-on net is built first. The gross service amount is the sum over `service_line_ids` of each item's `price_cents`, except that an item whose `membership_included` is true contributes zero whenever the customer's `membership_status` is `ACTIVE`. The gross add-on amount is the sum over `addon_line_ids` of each add-on's price after membership treatment: if the customer's `membership_status` is not `ACTIVE`, the add-on contributes its full `price_cents`; if it is `ACTIVE`, the applicable percentage is the add-on's own `membership_discount_pct` when that is greater than zero, otherwise the customer's plan `addon_discount_pct`, and the add-on contributes its `price_cents` reduced by that percentage, with each add-on line rounded half-up to a whole cent individually before any add-on lines are summed. Next a reward waiver is computed: if `redeem_reward` is set and the customer's `reward_credits` is at least 1 and there is at least one service line, the waiver equals the smaller of the cheapest `LISTED` service line's `price_cents` (ties broken by earliest item `created_at`) and the shop's `punch_reward_value_cents`; otherwise the waiver is zero. Finally, `service_net_cents` is the gross service amount plus the gross add-on amount minus the waiver, floored at zero so it can never go negative.

Product and tax follow, again in pinned order. The `product_net_cents` is the sum over `product_lines` of each line's `price_cents` times its `qty`. The taxable base is `service_net_cents` plus `product_net_cents`, summed first; the `tax_cents` is that single summed base multiplied by the shop's `tax_rate_pct` divided by 100, rounded half-up once on the summed base rather than per line. The `total_due_cents` is `service_net_cents` plus `product_net_cents` plus `tax_cents` plus `tip_cents`. The tip is never taxed and is never shared with the shop — it flows entirely to the barber.

The checkout cascade then reconciles every dependent figure. Each product line decrements the matching product's `stock_qty` by its `qty`. The barber's `unsettled_revenue_cents` is increased by `service_net_cents`, and the barber's `version` is incremented by one. The shop's `gross_service_revenue_cents` is increased by `service_net_cents` and its `gross_product_revenue_cents` by `product_net_cents`. The customer's loyalty is advanced as described in §3.7. If the ticket was opened from an appointment that is `CHECKED_IN`, that appointment moves `CHECKED_IN → COMPLETED`; if it was opened from a queue ticket that is `SERVING`, that queue ticket moves `SERVING → DONE`.

### 3.7. Loyalty: Punches, Rewards, and Memberships

Loyalty accrues one punch per paid visit. On every checkout — after pricing is complete — the customer's `punch_count` is incremented by one. If that new count reaches or exceeds the shop's `punch_reward_threshold`, the customer earns one reward: `reward_credits` is increased by one and `punch_count` is reduced by the threshold amount, carrying any surplus forward. If the new count is still below the threshold, it simply stands as the customer's new `punch_count`. The boundary is inclusive: a new count exactly equal to the threshold grants the reward, while a count one short does not. Even a ticket with no service and no product lines still earns its punch.

Redemption and accrual on the same visit are deliberately separated in time. When `redeem_reward` is set at a checkout, the credit it consumes must be one that already existed before this checkout's accrual; a credit earned on this very visit cannot be redeemed on this same visit. Accordingly, redeeming a reward consumes one of the customer's `reward_credits` (decrementing it by one) to fund the service waiver computed in §3.6, and this is gated by the precondition that `reward_credits` be at least 1 beforehand.

Memberships are subscribed, not auto-assigned. A `ShopOwner`, `Receptionist`, or the `Customer` themselves may subscribe a customer to a plan by supplying the `membership_id`; the plan must be `OFFERED`, else the subscription is refused with `ERR_ITEM_DELISTED`. Subscribing sets the customer's `membership_id` and moves their `membership_status` `NONE → ACTIVE`, which is what unlocks the membership pricing in §3.6 — included-service waivers and add-on discounts. A customer is created with `membership_status` of `NONE` and a null `membership_id`. Customers are registered by a `ShopOwner` or `Receptionist` with `shop_id`, `full_name`, and an `email` that is unique within the shop, and they begin `ACTIVE` with `punch_count`, `reward_credits`, and `no_show_strikes` all at zero.

### 3.8. No-Shows, Strikes, and Suspension

When a booked customer fails to appear, a `Receptionist` or `ShopOwner` marks the appointment a no-show — but not too early. The no-show is permitted only once the logical clock has reached `start_utc` plus the shop's `late_grace_minutes`; at exactly that boundary instant the no-show is already allowed, while one moment earlier it is refused with `ERR_NO_SHOW_TOO_EARLY`. Marking the no-show moves the appointment `BOOKED → NO_SHOW` and always adds one to the customer's `no_show_strikes`. If that incremented strike count reaches or exceeds the shop's `no_show_strike_limit`, the customer's `status` moves to `SUSPENDED` — a consequence of the strike increment itself, which thereafter blocks the customer from booking or taking a queue ticket. The suspension boundary is inclusive at the limit. Separately, if the shop's `no_show_fee_cents` is greater than zero, a ticket is opened and immediately paid carrying only the no-show fee — no tax, no tip, no service or product lines — so that its `total_due_cents` equals exactly `no_show_fee_cents`, attributed to the appointment's barber under the current `business_date`.

### 3.9. Voiding a Sale

Mistakes are unwound by voiding, an owner-only action permitted only while a ticket is `OPEN`; acting on a ticket that is already `PAID` or `VOIDED` is rejected as an invalid state. Voiding moves the ticket `OPEN → VOIDED` and restores the upstream resource it came from: if the linked appointment is `CHECKED_IN`, it reverts `CHECKED_IN → BOOKED` and its `ticket_id` is cleared; if the linked queue ticket is `SERVING`, it reverts `SERVING → WAITING` and is placed at the back of the line with positions recomputed. Because a void acts on an `OPEN` ticket — one whose revenue cascade has not yet run — voiding does not reverse settlement figures; it simply releases the source appointment or queue ticket for another attempt.

### 3.10. Daily Settlement and the Two Compensation Models

Settlement is where the shop's dual-economy design pays off. A `ShopOwner` finalizes a barber's books for a given day by creating a `DailySettlement` with the `business_date` to settle and the `expected_barber_version` demanded by §2.7. There may be at most one settlement per barber per `business_date`; a second attempt, or any checkout aimed at a barber-and-date already settled, is refused with `ERR_DATE_ALREADY_SETTLED`. A settlement is created already `FINALIZED` and is immutable thereafter, and it snapshots the barber's `comp_model` into its own `comp_model` field at settlement time.

The settlement aggregates the barber's tickets whose `status` is `PAID` and whose `business_date` matches the settled date; voided tickets are excluded. From those tickets it sums `service_net_cents` into `service_revenue_cents`, `product_net_cents` into `product_revenue_cents`, and `tip_cents` into `tip_total_cents`. It also computes the commission-eligible product subtotal — for each of those tickets, the sum over its product lines whose product is `commission_eligible` of that product's `price_cents` times `qty` — which feeds the commission variant below. A no-show-fee ticket contributes nothing to service or product revenue, since the fee is shop revenue rather than barber earnings.

From here the calculation forks on the snapshotted `comp_model`, and the same trio of service, product, and tip totals produces a different barber payout under each. Under the `BOOTH_RENT` variant, `booth_rent_charged_cents` is the barber's `booth_rent_cents`, `shop_commission_cents` is zero, and `barber_payout_cents` is the sum of tips plus service revenue plus product revenue minus the barber's `booth_rent_cents` — the barber keeps the gross take and simply pays the flat daily rent. Under the `COMMISSION` variant, `booth_rent_charged_cents` is zero, and two commissions are figured independently. The shop's service take is the service revenue multiplied by the barber's `commission_pct` divided by 100, rounded half-up; the barber's product earn is the commission-eligible product subtotal multiplied by the shop's `product_commission_pct` divided by 100, rounded half-up. The `shop_commission_cents` is the shop's service take plus the portion of product revenue the barber did not earn — that is, the service take plus the difference of total product revenue minus the barber's product earn. The `barber_payout_cents` is the sum of tips plus the service revenue net of the shop's service take plus the barber's product earn. The two rounded commissions are rounded independently of each other.

Creating the settlement decrements the barber's `unsettled_revenue_cents` by the service net it just settled, reconciling that figure toward zero for the date, and increments the barber's `version` by one. Settlements may be listed and read back per barber or across the shop, and a `Barber` may read their own settlement rows.

## 4. Endpoint Definitions

Operations that create a new resource return HTTP 201 Created. Operations that modify an existing resource — including every state transition and the logical-clock control — return HTTP 200 OK. All list and read operations return 200. The request and response payloads for each operation are described in the §3 narratives; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to an absolute UTC instant | ShopOwner |
| POST | `/shops` | Create a shop | ShopOwner |
| GET | `/shops` | List shops | ShopOwner, Receptionist, Barber, Customer |
| GET | `/shops/{shopId}` | Get a shop | ShopOwner, Receptionist, Barber, Customer |
| POST | `/shops/{shopId}/close` | Close the shop | ShopOwner |
| POST | `/shops/{shopId}/reopen` | Reopen the shop | ShopOwner |
| POST | `/barbers` | Create a barber | ShopOwner |
| GET | `/barbers` | List barbers (filter by shop_id) | ShopOwner, Receptionist, Barber, Customer |
| GET | `/barbers/{barberId}` | Get a barber | ShopOwner, Receptionist, Barber, Customer |
| POST | `/barbers/{barberId}/license/activate` | Activate a barber license | ShopOwner |
| POST | `/barbers/{barberId}/license/suspend` | Suspend a barber license | ShopOwner |
| POST | `/barbers/{barberId}/license/revoke` | Revoke a barber license | ShopOwner |
| GET | `/barbers/{barberId}/settlements` | List a barber's settlements | ShopOwner, Barber |
| POST | `/barbers/{barberId}/settlements` | Finalize a daily settlement | ShopOwner |
| GET | `/settlements` | List settlements (filter by shop_id, barber_id, business_date) | ShopOwner, Barber |
| GET | `/settlements/{settlementId}` | Get a settlement | ShopOwner, Barber |
| POST | `/chairs` | Create a chair | ShopOwner |
| GET | `/chairs` | List chairs (filter by shop_id) | ShopOwner, Receptionist, Barber, Customer |
| GET | `/chairs/{chairId}` | Get a chair | ShopOwner, Receptionist, Barber, Customer |
| POST | `/shifts` | Schedule a shift | ShopOwner |
| GET | `/shifts` | List shifts (filter by shop_id, barber_id, chair_id) | ShopOwner, Receptionist, Barber, Customer |
| GET | `/shifts/{shiftId}` | Get a shift | ShopOwner, Receptionist, Barber, Customer |
| POST | `/shifts/{shiftId}/cancel` | Cancel a scheduled shift | ShopOwner |
| POST | `/services` | Create a service menu item | ShopOwner |
| GET | `/services` | List services (filter by shop_id) | ShopOwner, Receptionist, Barber, Customer |
| GET | `/services/{serviceId}` | Get a service | ShopOwner, Receptionist, Barber, Customer |
| POST | `/services/{serviceId}/delist` | Delist a service | ShopOwner |
| POST | `/addons` | Create an add-on | ShopOwner |
| GET | `/addons` | List add-ons (filter by shop_id) | ShopOwner, Receptionist, Barber, Customer |
| GET | `/addons/{addonId}` | Get an add-on | ShopOwner, Receptionist, Barber, Customer |
| POST | `/addons/{addonId}/delist` | Delist an add-on | ShopOwner |
| POST | `/products` | Create a product | ShopOwner |
| GET | `/products` | List products (filter by shop_id) | ShopOwner, Receptionist, Barber, Customer |
| GET | `/products/{productId}` | Get a product | ShopOwner, Receptionist, Barber, Customer |
| POST | `/products/{productId}/delist` | Delist a product | ShopOwner |
| POST | `/memberships` | Create a membership plan | ShopOwner |
| GET | `/memberships` | List membership plans (filter by shop_id) | ShopOwner, Receptionist, Barber, Customer |
| GET | `/memberships/{membershipId}` | Get a membership plan | ShopOwner, Receptionist, Barber, Customer |
| POST | `/memberships/{membershipId}/retire` | Retire a membership plan | ShopOwner |
| POST | `/customers` | Create a customer | ShopOwner, Receptionist |
| GET | `/customers` | List customers (filter by shop_id, membership_id) | ShopOwner, Receptionist |
| GET | `/customers/{customerId}` | Get a customer | ShopOwner, Receptionist, Customer |
| POST | `/customers/{customerId}/subscribe` | Subscribe a customer to a plan | ShopOwner, Receptionist, Customer |
| POST | `/appointments` | Book an appointment | ShopOwner, Receptionist, Customer |
| GET | `/appointments` | List appointments (filter by shop_id, customer_id, barber_id, chair_id, service_item_id, ticket_id) | ShopOwner, Receptionist, Barber, Customer |
| GET | `/appointments/{appointmentId}` | Get an appointment | ShopOwner, Receptionist, Barber, Customer |
| POST | `/appointments/{appointmentId}/check-in` | Check in an appointment | ShopOwner, Receptionist |
| POST | `/appointments/{appointmentId}/no-show` | Mark an appointment no-show | ShopOwner, Receptionist |
| POST | `/appointments/{appointmentId}/cancel` | Cancel an appointment | ShopOwner, Receptionist, Customer |
| POST | `/queue` | Take a walk-in queue ticket | ShopOwner, Receptionist, Customer |
| GET | `/queue` | List queue tickets (filter by shop_id, customer_id, requested_barber_id, assigned_barber_id, ticket_id) | ShopOwner, Receptionist, Barber, Customer |
| GET | `/queue/{queueTicketId}` | Get a queue ticket | ShopOwner, Receptionist, Barber, Customer |
| POST | `/queue/{queueTicketId}/serve` | Serve the front queue ticket | ShopOwner, Receptionist |
| POST | `/queue/{queueTicketId}/abandon` | Abandon a waiting queue ticket | ShopOwner, Receptionist, Customer |
| GET | `/tickets` | List tickets (filter by shop_id, customer_id, barber_id, appointment_id, queue_ticket_id, business_date) | ShopOwner, Receptionist, Barber |
| GET | `/tickets/{ticketId}` | Get a ticket | ShopOwner, Receptionist, Barber |
| PUT | `/tickets/{ticketId}/lines` | Replace the lines on an open ticket | ShopOwner, Receptionist |
| POST | `/tickets/{ticketId}/checkout` | Check out and pay a ticket | ShopOwner, Receptionist |
| POST | `/tickets/{ticketId}/void` | Void an open ticket | ShopOwner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SHOP_NOT_FOUND` | 404 |
| `ERR_BARBER_NOT_FOUND` | 404 |
| `ERR_CHAIR_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_QUEUE_TICKET_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SHOP_CLOSED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ITEM_DELISTED` | 409 |
| `ERR_BARBER_NOT_ACTIVE` | 409 |
| `ERR_CUSTOMER_SUSPENDED` | 409 |
| `ERR_LICENSE_EXPIRED` | 409 |
| `ERR_OUTSIDE_SHIFT` | 409 |
| `ERR_CHAIR_DOUBLE_BOOKED` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_SHIFT_HAS_APPOINTMENTS` | 409 |
| `ERR_NOT_QUEUE_FRONT` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_NO_REWARD_CREDITS` | 409 |
| `ERR_NO_SHOW_TOO_EARLY` | 409 |
| `ERR_CANCEL_TOO_LATE` | 409 |
| `ERR_OPEN_TICKETS_EXIST` | 409 |
| `ERR_DATE_ALREADY_SETTLED` | 409 |
| `ERR_STALE_SHOP_VERSION` | 412 |
| `ERR_STALE_BARBER_VERSION` | 412 |
