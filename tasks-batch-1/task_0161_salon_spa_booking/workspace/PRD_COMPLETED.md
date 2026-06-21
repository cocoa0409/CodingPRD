# Salon Spa Booking API — Product Requirements Document

## 1. Introduction

The Salon & Spa Booking API is the operational backbone for a multi-tenant network of salon and spa businesses. Each salon manages its own roster of stylists, its catalog of services, its physical chairs and treatment rooms, its retail shelf, and its clientele — and the system must keep every appointment, every payout, and every inventory count internally consistent as the day unfolds. The recurring pain points it addresses are familiar to any front desk: a stylist double-booked because two receptionists were looking at the same screen a moment apart; a client who never showed but whose deposit was never reconciled; a tip that was supposed to be split across the floor but went entirely to one chair; a package session that was redeemed twice; a product sold off a shelf that was already empty.

This specification governs the full lifecycle of an appointment — from booking, through confirmation, to either completion at checkout or one of its unhappy endings (a cancellation or a no-show) — together with the money movements that each ending implies. Checkout is the system's central ledger event: a single completion fans out into service-revenue recognition, a commission-versus-booth-rent payout split, a tip distribution, package-session redemption, and retail inventory decrements, all committed atomically inside the one request that triggers them. Because the benchmark exercises temporal reasoning, every time-based check is evaluated against a per-salon **simulated clock** rather than the host machine's wall clock, so that test scenarios can advance time deterministically.

A note on units before the detail begins: all monetary amounts in this system are integer **cents**, and all durations that drive scheduling are **minutes**. There are no fractional-cent or fractional-minute values anywhere in the contract.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `SalonOwner`, `FrontDesk`, `Stylist`, and `Client`. When an authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN`.

These four roles form a peer model with deliberately non-overlapping write surfaces. A `SalonOwner` is the owner-operator: they configure the catalog (creating stylists, resources, services, membership plans, packages, and retail SKUs), drive the simulated clock, void checkouts, manage the membership lifecycle, and adjudicate no-show disputes. A `FrontDesk` operator runs the day-to-day desk: booking, confirming, cancelling, and no-showing appointments, running checkouts, registering clients, enrolling memberships, and selling packages — but they cannot configure the catalog and cannot void or dispute. A `Stylist` has read-only reach into the schedule and checkouts. A `Client` is the end customer who self-registers, buys packages, and self-books and self-cancels their own appointments.

Two of the four roles are tied to a persisted entity, and two are not. When `X-User-Role` is `Stylist`, `X-User-ID` is the `id` of the acting `Stylist`; ownership checks on any resource that references a `Stylist` compare the resource's stylist foreign key to `X-User-ID`. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` — an appointment, a membership, a package purchase — compare that resource's client foreign key to `X-User-ID`, and a `Client` acting on a resource it does not own is rejected with `ERR_FORBIDDEN`. By contrast, when `X-User-Role` is `SalonOwner` or `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. A `limit` or `offset` outside its permitted bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, every list is sorted by the resource's creation timestamp, `created_at`, in ascending order. Each list response carries four pagination fields inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Nearly every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that starts at its initial value of `1` on creation and increments by one on every mutation; it is the anchor for optimistic concurrency control described in §2.7.

One resource departs from this convention. A `ProductSale` line — a single retail line item recorded under a checkout — is immutable once written, and it carries only `id` and `created_at`; it has no `updated_at` and no `version`. Every other entity (Salon, Stylist, Resource, Service, Client, MembershipPlan, Membership, Package, PackagePurchase, Appointment, ProductSku, Checkout) carries the full `id`/`created_at`/`updated_at`/`version` quartet.

Whenever an operation mutates a resource as a side effect of acting on another — for example, a booking that advances a stylist's `version`, or a no-show that credits a client's wallet — that touched resource has its own `updated_at` refreshed and its own `version` incremented independently. Cascades are not silent: each entity the request touches advances its own version counter.

### 2.5. The Simulated Clock and Temporal Evaluation

Each salon owns a mutable simulated wall clock exposed as `current_utc`. On salon creation, `current_utc` is initialized to the salon's `created_at`. Every temporal decision in the system — whether a booking lies in the future, whether a slot has begun, whether a cancellation precedes its appointment's start — reads this `current_utc` value, never the host machine's clock. The clock only moves forward through an explicit, owner-driven test-driving capability that sets `current_utc` to a supplied future instant. Because that capability is the only writer of the clock and is concurrency-guarded, time within a salon is fully deterministic.

### 2.6. Precision and Rounding

Every monetary computation in this system resolves to integer cents. Wherever a calculation produces a fractional cent — a membership discount applied to a base price, a per-session package value derived by division, a no-show fee taken as a fraction of a quote — the result is rounded **half up** at the cents level to yield an integer number of cents. "Round half up" means a fractional remainder of exactly one half rounds away from zero to the next whole cent. The precise order in which rounding is applied relative to other arithmetic matters and is pinned individually for each calculation in §3; where a formula divides before rounding, or rounds each line before summing, that ordering is part of the contract and is stated where the calculation lives.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of their parent entity, and both use the same optimistic-concurrency discipline: the request carries the client's last observed `version` of the parent, and the server rejects the request if the parent's current `version` no longer matches.

Booking an appointment is guarded on the serving stylist. A booking request must carry `expected_stylist_version`, which must equal the target stylist's current `version`. Each successful booking advances that stylist's `version` by one, because the stylist's schedule has changed; a subsequent booking still carrying the older `expected_stylist_version` is therefore operating on a stale view of that stylist's availability and is rejected with `ERR_STALE_STYLIST_VERSION` (HTTP 412). This prevents a caller from committing a booking against a schedule it has not re-observed.

Advancing a salon's simulated clock is guarded on the salon. The clock-advance request must carry `expected_salon_version`, which must equal the salon's current `version`. Each successful advance bumps the salon's `version`; a second advance built on the older observed version is stale and is rejected with `ERR_STALE_SALON_VERSION` (HTTP 412), preventing two independent advances from compounding on a view that has moved on. Only these two operations take a version field; no other endpoint requires one.

### 2.8. Resource Resolution and Tenant Scoping

The salon is the tenant root, and almost every other entity belongs to exactly one salon. When a request references resources, the system resolves them left to right and confirms that each exists; the first reference that fails to resolve yields `ERR_NOT_FOUND` (HTTP 404). Tenant scoping is part of resolution: a client, stylist, resource, service, or package referenced in a booking must belong to the salon named on that booking, and a reference that resolves to an entity in a different salon is treated as not found. Cross-aggregate references that the checkout ledger reads — the appointment being settled, its stylist, the client's membership, a redeemed package purchase, the retail SKUs — are resolved before any money math runs; the caller-supplied retail-line SKUs are matched by existence only (an unknown `product_sku_id` yields `ERR_NOT_FOUND`) and are not separately re-scoped against the appointment's salon.

### 2.9. Validation Ordering

When a single operation can fail several independent checks, the checks are applied in a fixed priority order so that the error a caller sees is deterministic. Across the whole API the spine of that order is: authentication first (`ERR_UNAUTHENTICATED`), then authorization (`ERR_FORBIDDEN`), then existence and tenant scoping of every referenced resource (`ERR_NOT_FOUND`), then the target entity's state eligibility for the requested transition (`ERR_INVALID_STATE`), then the operation's domain-specific business rules, and finally field-level request validity (`ERR_INVALID_REQUEST`). The booking operation has the richest domain layer, and its internal ordering is spelled out in §3.3; the principle to carry forward is that a higher-priority failure masks any lower-priority one, so a request that is both unauthorized and malformed reports the authorization failure.

## 3. Business Logic & Workflows

### 3.1. Configuring the Salon and Its Catalog

A salon is brought into being by a `SalonOwner`, who supplies a `name` and may set a `timezone` (an IANA zone used only to interpret business hours for humans — all stored times are UTC; it defaults to `UTC`). Three policy levers are set on the salon at creation and govern downstream money and discipline rules. The `no_show_fee_pct` is the fraction of an appointment's quoted service price forfeited as a no-show fee, charged against the held deposit; it defaults to one half (0.50) and must lie between zero and one inclusive. The `no_show_suspend_threshold` is the count of accumulated no-show strikes at or above which a client is auto-suspended from self-booking; it defaults to 3 and must be at least 1. The `tip_split_policy` is an enum, either `DIRECT` or `POOLED`, defaulting to `DIRECT`, that decides how a checkout distributes the appointment tip. The salon's `current_utc` is system-managed as described in §2.5 and is not a creation input.

A `SalonOwner` populates the catalog with stylists, resources, services, membership plans, packages, and retail SKUs.

A **Stylist** belongs to a salon (`salon_id`) and carries a `full_name`. The stylist's `status` is either `ACTIVE` or `INACTIVE`, defaulting to `ACTIVE`; only `ACTIVE` stylists may be booked, and `status` also governs membership in the tip pool. The `compensation_model` is either `COMMISSION` or `BOOTH_RENT` and has no default — it must be supplied. Under `COMMISSION`, the stylist earns the fraction `commission_pct` (between zero and one inclusive, default 0.40) of service revenue, and the salon keeps the rest; `commission_pct` is ignored under `BOOTH_RENT`. Under `BOOTH_RENT`, the stylist keeps the full service revenue minus a flat per-completed-appointment fee, `booth_rent_per_appt_cents` (a non-negative integer, default 1500 cents), owed to the salon; that field is ignored under `COMMISSION`. The stylist's `buffer_minutes` (a non-negative integer, default 10) is the mandatory turnaround padding reserved both before and after every appointment this stylist serves. A `SalonOwner` may later update a stylist's `status`, `compensation_model`, `commission_pct`, `booth_rent_per_appt_cents`, or `buffer_minutes`; each such update advances the stylist's `version`.

A **Resource** is a physical station belonging to a salon (`salon_id`) with a human `label` such as "Chair 3" or "Facial Room A". Its `resource_type` is either `CHAIR` or `ROOM`; both behave as single-occupancy, and the type only matters for matching a service's room requirement. Its `status` is `ACTIVE` or `OUT_OF_SERVICE`, defaulting to `ACTIVE`; only `ACTIVE` resources may be booked.

A **Service** belongs to a salon (`salon_id`) and has a `name`. Its `duration_minutes` (an integer of at least 1) is the chair-or-room occupancy duration and explicitly excludes the stylist's buffer. Its `base_price_cents` (a non-negative integer) is the list price before any membership discount or package coverage. Its `deposit_pct` (between zero and one inclusive, default 0.0) is the fraction of the booked quote collected as a refundable hold; zero means no deposit. The boolean `requires_room` (default false) ties the service to a resource type: when true the booked resource must be a `ROOM`, and when false it must be a `CHAIR`.

A **MembershipPlan** belongs to a salon (`salon_id`) and has a `name`. Its `monthly_fee_cents` (a non-negative integer) is informational and not auto-billed by this system. Its `service_discount_pct` (between zero and one inclusive) is the fraction taken off a service's base price for active members, and its `retail_discount_pct` (between zero and one inclusive, default 0.0) is the fraction taken off retail unit prices for active members.

A **Package** belongs to a salon (`salon_id`) and prepays sessions of exactly one service (`service_id`). Its `session_count` (an integer of at least 1) is the number of prepaid sessions granted on purchase, and its `price_cents` (a non-negative integer) is the total paid for all of them.

A **ProductSku** is a retail item belonging to a salon (`salon_id`) with a stock-keeping code `sku` that must be unique within the salon, a `name`, a `unit_price_cents` retail list price (a non-negative integer) before any member discount, and a `qty_on_hand` integer of units in inventory. A `SalonOwner` creating a SKU supplies its starting `qty_on_hand`; thereafter the field is system-maintained — decremented when a retail line is sold at checkout, restored when such a sale is voided, and increased by an owner restock. A restock adds a supplied `quantity` to `qty_on_hand` and advances the SKU's `version`. The on-hand count is never allowed to go negative.

### 3.2. Clients, Memberships, and Packages

A **Client** belongs to a salon (`salon_id`) and is registered with a `full_name` and an `email`; the email must be unique within the salon, compared case-insensitively, among clients that are not archived. A client may be registered by a `FrontDesk` operator, a `SalonOwner`, or self-registered by a `Client`. A client's `status` is one of `ACTIVE`, `SUSPENDED`, or `ARCHIVED`, defaulting to `ACTIVE`. `ACTIVE` clients may self-book. A `SUSPENDED` client — a state reached automatically once their strike count crosses the salon's suspension threshold — cannot self-book, but may still be booked by a `FrontDesk` operator. An `ARCHIVED` client is soft-deleted and may not be booked by anyone; because the soft-delete hides them, the client list (`GET /clients`) omits `ARCHIVED` clients by default and includes them only when the request explicitly filters on `status=ARCHIVED` (the client list accepts `salon_id` and `status` query filters). Two further fields on the client are system-computed and never set directly by a caller: `no_show_strikes`, a running count of missed appointments that starts at 0 and drives auto-suspension, and `wallet_credit_cents`, a store-credit balance in cents that starts at 0 and is never negative. A client's record, including these two counters, is readable.

A **MembershipPlan** (configured in §3.1) becomes a benefit to a client through a **Membership**, which links a client (`client_id`) to a plan (`plan_id`). A membership's `status` is computed and one of `ACTIVE`, `PAST_DUE`, or `CANCELLED`, beginning `ACTIVE` on enrollment. Only an `ACTIVE` membership grants plan discounts. A `SalonOwner` may mark an `ACTIVE` membership `PAST_DUE` — a lapse that suspends its discounts so that future appointment quotes price as non-member — and may later reinstate a `PAST_DUE` membership back to `ACTIVE`, restoring its discounts; the `ACTIVE` and `PAST_DUE` states therefore form a reversible cycle. Reinstating a membership that is not currently `PAST_DUE` is a state error. From either the `ACTIVE` or the `PAST_DUE` state a `SalonOwner` may cancel the membership, moving it to the terminal `CANCELLED` state, which grants no discounts and cannot be revived. Each of these three transitions advances the membership's `version`. A membership may be enrolled by a `SalonOwner` or a `FrontDesk` operator.

A **Package** (configured in §3.1) is acquired by a client through a **PackagePurchase**, which links a client (`client_id`) to a package (`package_id`). A purchase may be made by a `SalonOwner`, a `FrontDesk` operator, or the `Client` themselves. On purchase, `sessions_remaining` is initialized to the package's `session_count` and the purchase's `status` is set to `ACTIVE`. Thereafter `sessions_remaining` is system-computed: it decrements when an appointment redeems a session at checkout, and it is restored when such an appointment is later cancelled, no-showed, or has its checkout voided. The purchase's `status` is `ACTIVE` while `sessions_remaining` is greater than zero and flips to `EXHAUSTED` the moment `sessions_remaining` reaches zero; a restore that lifts a purchase off zero flips it back to `ACTIVE`. `sessions_remaining` is never negative.

### 3.3. Booking an Appointment

An **Appointment** is the junction that brings a client, a stylist, a resource, and a service together at a moment in time. A `SalonOwner`, a `FrontDesk` operator, or a `Client` (booking for themselves) creates one by supplying the `salon_id`, the `client_id`, the `stylist_id` of the serving stylist, the `resource_id` of the chair or room to occupy, the `service_id`, the `start_utc` of the appointment, and the `expected_stylist_version` for the concurrency guard. A booking may optionally carry a `package_purchase_id`: when present, the appointment is set to draw on a prepaid session of the matching service instead of being charged the base price. Booking only earmarks that session — it validates availability but does not yet decrement `sessions_remaining`; the actual redemption (the decrement) happens at checkout per §3.2/§3.5, so a booking that is later cancelled or no-showed before checkout restores no session because none was consumed. On a successful booking the appointment's `status` is set to `BOOKED`, its `end_utc` is computed, its quote and deposit are snapshotted (below), and the serving stylist's `version` is advanced by one.

The booked appointment's occupancy of the chair or room runs over the half-open interval that begins at `start_utc` and ends at `start_utc` plus the service's `duration_minutes`; that end instant is stored as the computed `end_utc`, serialized as an ISO 8601 UTC timestamp with three fractional digits and a trailing `Z` per the §2.4 convention (for example `2026-07-01T13:45:00.000Z`). The caller-supplied `start_utc` is stored and echoed back verbatim as the client submitted it (it is not re-serialized to the three-fractional-digit form), and only its parsed instant is used for temporal checks. The serving stylist's claim on their own time is wider: it runs from `buffer_minutes` before `start_utc` to `buffer_minutes` after `end_utc`, again as a half-open interval, so that the configured turnaround padding is reserved on both sides.

Booking applies a sequence of checks, and their relative order is fixed so that the reported failure is deterministic. After the universal authentication, authorization, and existence-and-scoping checks have passed, the booking-specific checks run in this order. **First**, referential consistency between the service and its resource and package: a service whose `requires_room` is true must be paired with a `ROOM` resource and a service whose `requires_room` is false with a `CHAIR` resource, and if a `package_purchase_id` is given it must belong to the booking client and reference a package whose `service_id` equals the booked `service_id`; any of these failing yields `ERR_RESOURCE_TYPE_MISMATCH` (HTTP 422). **Second**, client bookability: a `Client` self-booking while `SUSPENDED` or `ARCHIVED` is rejected, and any booking of an `ARCHIVED` client is rejected — a `FrontDesk` operator may book a `SUSPENDED` client but never an `ARCHIVED` one — with `ERR_CLIENT_NOT_BOOKABLE` (HTTP 422). **Third**, temporality: `start_utc` must be strictly after the salon's `current_utc` at booking time, so a booking in the past or at exactly the current instant is rejected with `ERR_BOOKING_IN_PAST` (HTTP 422). **Fourth**, resource liveness: the referenced stylist's `status` must be `ACTIVE` and the referenced resource's `status` must be `ACTIVE`, else `ERR_RESOURCE_INACTIVE` (HTTP 422). **Fifth**, stylist availability: the booking's buffer-padded interval must not overlap the buffer-padded interval of any of that stylist's existing appointments still in a `BOOKED` or `CONFIRMED` state; an overlap is rejected with `ERR_STYLIST_DOUBLE_BOOKED` (HTTP 409). **Sixth**, resource availability: the booking's bare occupancy interval (no buffer applied to resources) must not overlap the bare occupancy interval of any existing `BOOKED` or `CONFIRMED` appointment for the same resource; an overlap is rejected with `ERR_RESOURCE_DOUBLE_BOOKED` (HTTP 409). Because both intervals are half-open, two appointments that merely touch at a boundary — one ending exactly when the next begins — do not overlap and are allowed. **Seventh**, package availability: if a `package_purchase_id` is present, that purchase must be `ACTIVE` with `sessions_remaining` of at least 1, else `ERR_PACKAGE_EXHAUSTED` (HTTP 422). **Eighth**, the concurrency guard of §2.7 compares `expected_stylist_version` against the stylist's current `version`, rejecting a mismatch with `ERR_STALE_STYLIST_VERSION` (HTTP 412). Field-level validity of the request body — required fields present, enum members valid, numbers within their declared ranges — backstops the whole sequence and surfaces as `ERR_INVALID_REQUEST` (HTTP 400).

At booking time the system snapshots two money fields onto the appointment and freezes them. The first is `quoted_service_price_cents`, the service charge after any membership discount. If the booking redeems a package — a `package_purchase_id` is present — the quote is set to 0, since the session is prepaid, and no deposit is collected. Otherwise the quote starts from the service's `base_price_cents`; if the booking client holds a single membership that is `ACTIVE` at booking time (memberships that are `PAST_DUE` or `CANCELLED` are ignored), the plan's `service_discount_pct` is applied by multiplying the base price by one minus that discount fraction and rounding the product half up to whole cents; if the client has no `ACTIVE` membership, the quote is simply the base price. This quote is frozen: it is not re-priced if the client's membership later changes. The second field is `deposit_held_cents`, the refundable hold, computed as the quoted price multiplied by the service's `deposit_pct`, rounded half up to whole cents — and therefore zero whenever no deposit is required or the appointment is package-covered.

### 3.4. Confirming, Cancelling, and No-Showing

A booked appointment moves through one of several lifecycle endings. The optional acknowledgement step is **confirmation**: a `SalonOwner` or `FrontDesk` operator advances an appointment from `BOOKED` to `CONFIRMED`, permitted only while the appointment is in `BOOKED` and its client is not `ARCHIVED`; confirmation advances the appointment's `version`. A `CONFIRMED` appointment behaves exactly like a `BOOKED` one for every other transition — both states are "non-terminal" for the purposes of double-booking checks and both are eligible for cancellation, no-show, and checkout.

**Cancellation** is available to a `SalonOwner`, a `FrontDesk` operator, or the owning `Client`, and is permitted only while the appointment is `BOOKED` or `CONFIRMED` and only while the salon's `current_utc` is still strictly before the appointment's `start_utc` — that is, before the slot has begun; attempting it on an ineligible state or after start yields `ERR_INVALID_STATE` (HTTP 409). Cancellation sets the appointment to `CANCELLED` and reverses the booking's holds: the full `deposit_held_cents` is refunded into the client's `wallet_credit_cents` (the client's wallet is increased by the deposit amount, and the client's `updated_at` and `version` are refreshed), and if the appointment had redeemed a package session, one session is restored to that purchase (`sessions_remaining` is increased by one, the purchase flips from `EXHAUSTED` back to `ACTIVE` if it had been exhausted, and the purchase's `version` is advanced). The appointment's own `version` advances as well.

**No-show** is available to a `SalonOwner` or a `FrontDesk` operator and is permitted only while the appointment is `BOOKED` or `CONFIRMED` and only once the slot has begun — the salon's `current_utc` is at or after the appointment's `start_utc`; an out-of-state or too-early attempt yields `ERR_INVALID_STATE` (HTTP 409). Marking a no-show is the system's deepest cascade. The appointment is set to `NO_SHOW`. The forfeit is computed as the quoted price multiplied by the salon's `no_show_fee_pct`, rounded half up to whole cents; the salon actually forfeits the smaller of that fee and the held deposit, and the remainder of the deposit (the held deposit minus the amount forfeited) is refunded into the client's `wallet_credit_cents`. The client's `no_show_strikes` is then incremented by one. That strike increment is itself the trigger for a second-order effect: if the client's resulting `no_show_strikes` is at or above the salon's `no_show_suspend_threshold` and the client is currently `ACTIVE`, the client is auto-suspended to `SUSPENDED` within the same request. If the appointment had redeemed a package session, that session is restored exactly as in cancellation. The client's `version` advances for the wallet, strike, and suspension changes, and the appointment's `version` advances as well.

A no-show can be contested. A `SalonOwner` may **dispute** a no-show by citing the offending `appointment_id`. The dispute decrements the client's `no_show_strikes` by one (never below zero); if that brings the count below the salon's `no_show_suspend_threshold` and the client is currently `SUSPENDED`, the client is restored to `ACTIVE`; and any no-show fee that had been forfeited for the cited appointment is credited back to the client's `wallet_credit_cents`. The client's `version` advances. The dispute is rejected with `ERR_DISPUTE_TARGET_INVALID` (HTTP 422) if the cited appointment is not a `NO_SHOW` belonging to this client, or if the client has no strikes left to reverse.

### 3.5. Checkout: Completing the Visit and Settling the Ledger

The happy ending of an appointment is **checkout**, performed by a `SalonOwner` or a `FrontDesk` operator. Creating the checkout is what completes the appointment: it is permitted only when the appointment is `BOOKED` or `CONFIRMED`, only when the salon's `current_utc` is at or after the appointment's `start_utc`, and only when no settled checkout already exists for that appointment. The already-settled check takes precedence over the state and timing checks: if a settled checkout already exists for the appointment, the request is rejected with `ERR_ALREADY_CHECKED_OUT` (HTTP 409) regardless of the appointment's current state — and because a completed appointment always has a settled checkout, attempting to check out an already-completed appointment yields `ERR_ALREADY_CHECKED_OUT`. Only when no settled checkout exists do the state and timing checks apply: an attempt against an appointment in a state other than `BOOKED` or `CONFIRMED` (for instance one that is `CANCELLED` or `NO_SHOW`), or before the slot has begun, yields `ERR_INVALID_STATE` (HTTP 409). A checkout is created against an appointment by supplying its `appointment_id`, an optional `tip_cents` gratuity (a non-negative integer, default 0), and an optional set of retail lines, `retail_lines`. On success the appointment moves to `COMPLETED`, a checkout is created in the `SETTLED` state, and the appointment's `version` advances. The checkout itself is the ledger event, and it computes a fan-out of money fields described below.

Each retail line on the checkout becomes a **ProductSale** record carrying its parent `checkout_id`, the `product_sku_id` sold, the `quantity` of units (an integer of at least 1), and a computed `line_total_cents`. Before any inventory moves, the checkout verifies that no line oversells: for each line the referenced SKU's `qty_on_hand` must be at least the line's `quantity`, checked against the running on-hand within the request so that two lines drawing on the same SKU cannot jointly exceed stock; a shortfall is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 422). On settlement each line decrements its SKU's `qty_on_hand` by the line's `quantity` and advances that SKU's `version`.

The checkout recognizes service revenue as follows. If the appointment redeemed a package, the recognized `service_revenue_cents` is the package's per-session value; otherwise it is the appointment's frozen `quoted_service_price_cents`. Crucially the revenue is never re-priced against the client's current membership — it reads the snapshot taken at booking. The **per-session value** of a package is its total `price_cents` divided by its `session_count`, with the division performed first and the quotient rounded half up to whole cents exactly once.

From recognized service revenue the checkout computes the stylist-versus-salon split and records both halves. When the serving stylist's `compensation_model` is `COMMISSION`, the stylist's share, `stylist_service_earning_cents`, is the recognized service revenue multiplied by the stylist's `commission_pct`, rounded half up to whole cents, and the salon's share, `salon_service_earning_cents`, is the recognized revenue minus the stylist's share. When the model is `BOOTH_RENT`, the salon's share is the booth rent — the smaller of the stylist's `booth_rent_per_appt_cents` and the recognized revenue (clamped so it can never exceed the revenue available) — and the stylist's share is the recognized revenue minus that booth rent. As a worked illustration of why the model matters: on 10000 cents of revenue a commission stylist at 0.40 earns 4000 with the salon keeping 6000, whereas a booth-rent stylist owing 1500 keeps 8500 with the salon earning only 1500.

The checkout also distributes the tip and records this appointment's stylist's share as `stylist_tip_cents`, governed by the salon's `tip_split_policy`. Under `DIRECT`, the entire `tip_cents` goes to the serving stylist and every other stylist gets nothing. Under `POOLED`, the tip is divided evenly across all stylists in the salon whose `status` is `ACTIVE` at checkout time, including the serving stylist, with a pinned distribution order. First, count the `ACTIVE` stylists; the base share for each is the entered `tip_cents` divided down to a whole cent (the floor of the division). The leftover cents — the entered tip minus the base share times the count — are then handed out one per stylist, to the earliest-created stylists first: the `ACTIVE` stylists are ranked by their `created_at` ascending (their `id` is never used as the tiebreaker), and each of the first however-many stylists in that ranking, where "however-many" is the leftover count, receives one extra cent on top of the base share while the rest receive only the base share. The value stored as this checkout's `stylist_tip_cents` is the serving stylist's own resulting share: the base share, plus one cent only if the serving stylist's `created_at` rank falls within the leftover count. For example, a 1000-cent tip pooled across three `ACTIVE` stylists yields shares of 334, 333, and 333 in `created_at` order.

Retail revenue is rounded per line and then summed, never the other way around. A member retail discount applies when the appointment's client holds an `ACTIVE` membership at checkout time. For each line the effective unit price is the SKU's `unit_price_cents` if there is no active membership, or, if there is, that unit price multiplied by one minus the plan's `retail_discount_pct`, rounded half up to whole cents. The line's `line_total_cents` is that already-integer effective unit price multiplied by the line `quantity`. The checkout's `retail_revenue_cents` is the sum of all the lines' `line_total_cents`. Because the rounding happens once per line before summation, the total can differ from a sum-then-round computation, and this per-line ordering is the contract.

Settlement also resolves the deposit and the package. The deposit held at booking, `deposit_held_cents`, is applied toward the service charge rather than refunded — completing the visit consumes the hold. If the appointment redeemed a package session, that session is now consumed: the purchase's `sessions_remaining` is decremented by one, and if it thereby reaches zero the purchase's `status` flips to `EXHAUSTED`; the purchase's `version` advances.

### 3.6. Voiding a Checkout

A settled checkout is not the final word: a `SalonOwner` may **void** it, and voiding is the system's compensating transition. It is permitted only while the checkout is `SETTLED`; voiding an already-voided checkout is rejected with `ERR_INVALID_STATE` (HTTP 409). A void sets the checkout's `status` to `VOIDED` and unwinds every side effect of the completion. Each child `ProductSale` line restores its SKU's `qty_on_hand` by the line's `quantity` (advancing each touched SKU's `version`), so that total units are conserved. If the appointment had redeemed a package session, that session is restored — `sessions_remaining` increased by one, the purchase flipped back to `ACTIVE` if it had been `EXHAUSTED`, its `version` advanced — so that sessions are conserved. Finally, the void reclassifies the visit as a missed one: the appointment is set to `NO_SHOW` and the full no-show cascade of §3.4 is applied — the client's `no_show_strikes` is incremented, the conditional auto-suspension is evaluated, and the deposit forfeit-and-refund against the client's `wallet_credit_cents` is performed exactly as a direct no-show would do. The checkout's `version` advances.

### 3.7. Reading the Ledger

The retail detail behind a checkout is retrievable. The line items recorded under a checkout can be listed, and an individual product sale can be fetched on its own; product sales can also be listed and filtered by their `checkout_id` or by their `product_sku_id`. A checkout itself, with all of its computed money fields — `service_revenue_cents`, `retail_revenue_cents`, `stylist_service_earning_cents`, `salon_service_earning_cents`, and `stylist_tip_cents` — is readable by a `SalonOwner`, a `FrontDesk` operator, or a `Stylist`, and checkouts can be listed and filtered by `appointment_id` or `status`. Appointments themselves can be listed and filtered by `client_id`, `stylist_id`, `resource_id`, `service_id`, `package_purchase_id`, or `status`, and similar list filters exist across the catalog: stylists and resources by `status` (and resources additionally by `resource_type`); services, packages, plans, SKUs, memberships, and package purchases each filterable by the foreign keys natural to them, such as a membership by `plan_id`. The clock-advance capability accepts the target instant as `to_iso8601` together with the `expected_salon_version` guard described in §2.7.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; creating a checkout (`POST /checkouts`) is such a create and returns `201 Created` even though completing the appointment is a side effect of that creation. Operations that modify an existing resource — including the appointment, membership, clock, inventory state transitions, and a checkout *void* — return `200 OK`. The request body, computed response fields, and side effects of each operation are described in §3; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/salons` | Create a salon (tenant root) | SalonOwner |
| GET | `/salons/{id}` | Fetch a salon | SalonOwner, FrontDesk, Stylist, Client |
| POST | `/salons/{id}/_clock/advance` | Advance the salon's simulated clock | SalonOwner |
| POST | `/stylists` | Create a stylist | SalonOwner |
| GET | `/stylists/{id}` | Fetch a stylist | SalonOwner, FrontDesk, Stylist, Client |
| GET | `/stylists` | List stylists | SalonOwner, FrontDesk, Stylist, Client |
| PATCH | `/stylists/{id}` | Update a stylist's status or compensation config | SalonOwner |
| POST | `/resources` | Create a chair or room | SalonOwner |
| GET | `/resources/{id}` | Fetch a resource | SalonOwner, FrontDesk, Stylist, Client |
| GET | `/resources` | List resources | SalonOwner, FrontDesk, Stylist, Client |
| POST | `/services` | Create a catalog service | SalonOwner |
| GET | `/services/{id}` | Fetch a service | SalonOwner, FrontDesk, Stylist, Client |
| GET | `/services` | List services | SalonOwner, FrontDesk, Stylist, Client |
| POST | `/clients` | Register a client | SalonOwner, FrontDesk, Client |
| GET | `/clients/{id}` | Fetch a client | SalonOwner, FrontDesk, Stylist, Client |
| GET | `/clients` | List clients | SalonOwner, FrontDesk |
| POST | `/clients/{id}/dispute-no-show` | Reverse a no-show strike for a client | SalonOwner |
| POST | `/membership-plans` | Create a membership plan | SalonOwner |
| GET | `/membership-plans/{id}` | Fetch a membership plan | SalonOwner, FrontDesk, Client |
| GET | `/membership-plans` | List membership plans | SalonOwner, FrontDesk, Client |
| POST | `/memberships` | Enroll a client in a plan | SalonOwner, FrontDesk |
| GET | `/memberships/{id}` | Fetch a membership | SalonOwner, FrontDesk, Client |
| GET | `/memberships` | List memberships | SalonOwner, FrontDesk, Client |
| POST | `/memberships/{id}/lapse` | Mark a membership PAST_DUE | SalonOwner |
| POST | `/memberships/{id}/reinstate` | Restore a PAST_DUE membership to ACTIVE | SalonOwner |
| POST | `/memberships/{id}/cancel` | Cancel a membership | SalonOwner |
| POST | `/packages` | Create a prepaid package | SalonOwner |
| GET | `/packages/{id}` | Fetch a package | SalonOwner, FrontDesk, Client |
| GET | `/packages` | List packages | SalonOwner, FrontDesk, Client |
| POST | `/package-purchases` | Purchase a package | SalonOwner, FrontDesk, Client |
| GET | `/package-purchases/{id}` | Fetch a package purchase | SalonOwner, FrontDesk, Client |
| GET | `/package-purchases` | List package purchases | SalonOwner, FrontDesk, Client |
| POST | `/product-skus` | Create a retail SKU with starting inventory | SalonOwner |
| GET | `/product-skus/{id}` | Fetch a SKU | SalonOwner, FrontDesk |
| GET | `/product-skus` | List SKUs | SalonOwner, FrontDesk |
| POST | `/product-skus/{id}/restock` | Add units to a SKU's inventory | SalonOwner |
| POST | `/appointments` | Book an appointment | SalonOwner, FrontDesk, Client |
| GET | `/appointments/{id}` | Fetch an appointment | SalonOwner, FrontDesk, Stylist, Client |
| GET | `/appointments` | List appointments | SalonOwner, FrontDesk, Stylist, Client |
| POST | `/appointments/{id}/confirm` | Acknowledge a booked appointment | SalonOwner, FrontDesk |
| POST | `/appointments/{id}/cancel` | Cancel before start | SalonOwner, FrontDesk, Client |
| POST | `/appointments/{id}/no-show` | Mark a no-show after start | SalonOwner, FrontDesk |
| POST | `/checkouts` | Complete an appointment and settle | SalonOwner, FrontDesk |
| GET | `/checkouts/{id}` | Fetch a checkout | SalonOwner, FrontDesk, Stylist |
| GET | `/checkouts` | List checkouts | SalonOwner, FrontDesk, Stylist |
| POST | `/checkouts/{id}/void` | Void a settled checkout | SalonOwner |
| GET | `/checkouts/{id}/product-sales` | List retail lines under a checkout | SalonOwner, FrontDesk, Stylist |
| GET | `/product-sales/{id}` | Fetch a single product sale line | SalonOwner, FrontDesk |
| GET | `/product-sales` | List product sales | SalonOwner, FrontDesk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RESOURCE_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLIENT_NOT_BOOKABLE` | 422 Unprocessable Entity |
| `ERR_BOOKING_IN_PAST` | 422 Unprocessable Entity |
| `ERR_RESOURCE_INACTIVE` | 422 Unprocessable Entity |
| `ERR_STYLIST_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_RESOURCE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_PACKAGE_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |
| `ERR_ALREADY_CHECKED_OUT` | 409 Conflict |
| `ERR_STALE_STYLIST_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SALON_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DISPUTE_TARGET_INVALID` | 422 Unprocessable Entity |
