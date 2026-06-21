# Travel Agency Tour Booking API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Travel Agency Tour Booking API, a multi-tenant back-office platform that lets a travel agency assemble tour packages, sell them to customers, and orchestrate the dozens of moving parts that turn a tentative itinerary into a confirmed, paid-up trip. A single booking is rarely a single transaction: it bundles a published package, a roster of travelers, a set of supplier-fulfilled components (flights, hotel nights, ground activities), a layered payment schedule, an optional insurance add-on, and — when plans fall apart — a penalty-aware cancellation and refund. The platform's job is to keep all of these in lockstep so that the price a customer was quoted, the money they have paid, the suppliers who have committed, and the trip's lifecycle status never drift out of agreement.

The central tension the API manages is timing. Prices must stay fluid while an agent is still building a booking, then freeze the instant it is reserved so that payment milestones can be generated against a stable number. Suppliers confirm or decline components on their own schedule, and a single late rejection of a mandatory leg can unwind a reservation back to the drawing board. Cancellation penalties grow as departure approaches, so the same booking refunds in full one week and forfeits everything the next. Because agency staff, customers, and suppliers all act on the same bookings concurrently, the system leans on explicit version checks to reject writes made against stale data. Every monetary amount in the system is an integer count of cents in the agency's currency; there are no fractional-cent values anywhere in the API.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` does not name a recognized role, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the role is recognized but is not permitted to perform the requested operation — or when an ownership check fails — the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly four roles: `AgencyAdmin`, `TravelAgent`, `Customer`, and `Supplier`.

An `AgencyAdmin` is the agency operator. Its `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and act on it, but it is never compared against any entity's `id` for ownership purposes. An `AgencyAdmin` provisions agencies, suppliers, and customers, opens bookings, runs the simulation clock, and records payments. A `TravelAgent` is agency staff who builds, publishes, and retires packages and operates bookings end to end. Like the admin, a `TravelAgent`'s `X-User-ID` is opaque and is not matched against any stored entity.

A `Customer` is a booking owner, and its `X-User-Role` carries an entity-backed identity: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a customer compare that resource back to `X-User-ID` — concretely, a `Customer` may act on a `Booking` (paying its milestones, cancelling it, reading it and its sub-resources) only when the booking's `customer_id` equals `X-User-ID`; otherwise the action is rejected with `ERR_FORBIDDEN_FOR_ROLE`. A `Supplier` likewise has an entity-backed identity: when `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting `Supplier` entity, and a supplier may confirm or reject only those components whose `supplier_id` equals `X-User-ID`. A confirm or reject against a component owned by a different supplier is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order.

Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count` (the total number of matching items across all pages), and `has_more` (true when items remain beyond the current page).

### 2.4. Tenancy, Foreign Keys, and Reverse Reachability

The agency is the tenant scope. Every other entity carries an `agency_id` (directly, as on a `Customer`, `Supplier`, or `TourPackage`, or transitively through its parent `Booking`) and is only ever visible and resolvable within its owning agency. The data model is deliberately flat: entities are linked by foreign keys carried in request bodies — a booking names its `customer_id` and `tour_package_id`, a traveler names its `booking_id`, a component names its `booking_id` and `supplier_id`, a milestone and a payment name their `booking_id`, a payment additionally names its `milestone_id`, an insurance policy names its `booking_id`, and a cancellation record names its `booking_id` — rather than by URL nesting.

Whenever a request body carries a foreign key, that reference must resolve to an existing resource within the same agency, or the request is rejected with `ERR_INVALID_REFERENCE`. This referential check applies to the creation of customers, suppliers, tour packages, bookings, travelers, components, insurance policies, and payments. To make every foreign key reverse-reachable without URL nesting, each collection offers a filtered list: customers and suppliers and tour packages are filterable by `agency_id`; travelers, milestones, insurance policies, and cancellation records are filterable by `booking_id`; components are filterable by `booking_id` and `supplier_id`; payments are filterable by `booking_id` and `milestone_id`; and bookings are filterable by `agency_id`, `customer_id`, and `tour_package_id`. Several lists also accept a `status` filter, suppliers and components accept a `kind` filter, milestones additionally accept a `kind` filter, and customers accept an `email` filter.

When a path names a resource that does not exist within the agency, the request is rejected with `ERR_NOT_FOUND`. Path identifiers are validated left to right, so the first identifier in the path that fails to resolve determines the error.

### 2.5. Common Resource Properties

Every entity in the system is a top-level resource that carries a system-managed `id` and a `created_at` timestamp. The `id` is a server-minted UUID with no type prefix. The `created_at` value is an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is first created.

Every entity in this system additionally carries an `updated_at` timestamp and an integer `version`. The `updated_at` field is an ISO 8601 UTC timestamp (three fractional digits) refreshed on every mutation of the resource. The `version` is an integer that starts at its initial value when the resource is created and increments by one on every mutation. Wherever a state transition or recomputation below is described as mutating an entity, that mutation refreshes the entity's `updated_at` and increments its `version`.

A note on the agency clock: the `now_utc` field on an `Agency` is the agency's simulation clock. It is a system-managed timestamp that begins at `1970-01-01T00:00:00.000Z` when the agency is created and only advances when an operator explicitly sets it. This clock — not wall-clock time — drives milestone due dates and cancellation penalty tiers throughout the system.

### 2.6. Monetary Values and Rounding

All money in the system is expressed as an integer number of cents in the agency's `currency` (an ISO currency code that defaults to `USD`). There are no fractional cents. Wherever a calculation divides — computing a per-person price after a percentage discount, a deposit as a percentage of the grand total, or a cancellation penalty as a percentage of a refundable base — the result is rounded to a whole number of cents using the round-half-up method (a value with a fractional part of exactly one-half rounds up to the next whole cent). Several calculations pin the order in which rounding and multiplication occur; those orderings are spelled out in §3 where each calculation lives, and they must be followed exactly, because rounding before versus after a multiplication can shift the final cents.

### 2.7. Optimistic Concurrency on Booking Writes

Because agents, customers, and suppliers all act on the same booking, a set of booking-mutating operations is guarded by optimistic concurrency control. Adding a traveler to a booking, reserving a booking, confirming a booking, and cancelling a booking each require the caller to supply `expected_booking_version` in the request body, carrying the `version` of the target `Booking` that the client last observed. The server compares it against the booking's current `version`; if they do not match — because some other writer has advanced the booking since the client read it — the request is rejected with `ERR_STALE_VERSION` and an HTTP 412 status, and no mutation occurs.

The traveler-add path makes this concrete: adding a traveler legitimately mutates the booking, recomputing `traveler_count` and re-quoting `subtotal_cents` against the group-discount tiers and so advancing the booking's `version`. A second add that still carries the pre-add `expected_booking_version` is therefore acting on a booking whose price basis has already shifted underneath it, and it is rejected on the stale-version check rather than silently re-quoting against an outdated subtotal. Operations that are not in this guarded set do not take a version field.

### 2.8. Cascading State and Hierarchical Consistency

A booking is a compound aggregate whose status is gated by its children. The server keeps parent and children consistent automatically: when a booking is cancelled, its components, milestones, payments, and insurance policies are swept to their resolved states without the client touching each one individually; when a mandatory component is rejected after reservation, the parent booking is driven back to an editable state and its open milestones are voided. Each such automatic transition is itself a mutation of the affected entity, refreshing its `updated_at` and incrementing its `version`. The precise cascades — which children change, in which direction, and how the booking's derived totals and `payment_status` are recomputed afterward — are described with the workflows in §3 that trigger them.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Agency, Suppliers, Customers, and the Clock

The setup of the platform begins with an `AgencyAdmin`, who creates an `Agency` by supplying its `name` and, optionally, its `currency` (defaulting to `USD`). A freshly created agency's simulation clock `now_utc` sits at the Unix epoch until the admin advances it. Driving that clock is an admin-only test-driving capability: the operator supplies a `now_utc` instant and the agency's clock jumps to it. Because milestone due dates and cancellation penalty tiers are all measured against this clock, setting it is how the agency's "today" is established for everything that follows.

The admin also provisions the supply side. A `Supplier` is created with its owning `agency_id`, a `name`, a `kind` — one of `FLIGHT`, `HOTEL`, or `ACTIVITY` — and an optional `auto_confirm` flag that defaults to false. The `kind` is the linchpin of component routing: a component may only be served by a supplier whose `kind` equals the component's own `kind`. When `auto_confirm` is true, any component requested against that supplier is confirmed immediately at request time rather than waiting for the supplier to act; when false, the component sits and waits.

Customers may be created by either an `AgencyAdmin` or a `TravelAgent`. A `Customer` is created with its `agency_id`, an `email`, and a `full_name`. The `email` must be unique within the agency: a create that reuses an email already present in that agency is rejected with `ERR_DUPLICATE_EMAIL`. A new customer starts with `wallet_credit_cents` of 0; this wallet balance holds refund credits and is only ever increased (never reduced below zero) when a cancellation directs a refund to the wallet, as described in §3.7.

### 3.2. Building and Publishing Tour Packages

A `TourPackage` is the template a booking instantiates, and only a `TravelAgent` may create one. At creation the agent supplies the owning `agency_id`, a `title`, and a `base_price_per_person_cents` — the list price per traveler before any group discount, which must be greater than zero. Three tuning parameters are optional and carry defaults: `deposit_pct`, the deposit as a percentage of the grand total, an integer between 1 and 100 inclusive that defaults to 20 and drives the deposit milestone amount; `balance_due_days_before_departure`, the number of days before departure that the balance milestone falls due, a non-negative integer that defaults to 30; and `min_group_size_for_discount`, the traveler headcount at or above which group-discount tiers begin to apply, defaulting to 5. A `deposit_pct` outside the 1-to-100 range, or a non-positive base price, is rejected as a malformed request with `ERR_INVALID_REQUEST`.

A package is born in `DRAFT` and cannot host bookings there. Publishing a package — which requires its `base_price_per_person_cents` to be greater than zero, otherwise the publish is rejected with `ERR_INVALID_REQUEST` — advances it `DRAFT → PUBLISHED`. Only a `PUBLISHED` package may have bookings opened against it. Retiring a package advances it `PUBLISHED → RETIRED`, but only when no booking in `DRAFT` or `RESERVED` status still references it; a retire attempted while such open bookings exist is rejected with `ERR_PACKAGE_HAS_OPEN_BOOKINGS`. `RETIRED` is terminal. A package's `status` therefore moves through `DRAFT`, `PUBLISHED`, and `RETIRED`, and both the publish and retire transitions increment the package's `version`.

### 3.3. Opening a Booking and Assembling Travelers

An `AgencyAdmin` or `TravelAgent` opens a `Booking` by naming its `agency_id`, the owning `customer_id`, the `tour_package_id` it instantiates, and a `departure_date` (an ISO 8601 UTC timestamp). The referenced package must be `PUBLISHED`, or the open is rejected with `ERR_PACKAGE_NOT_PUBLISHED`; the customer and package must resolve within the agency, or it is rejected with `ERR_INVALID_REFERENCE`. A new booking starts in `DRAFT` with `traveler_count` 0, `subtotal_cents` 0, `insurance_premium_cents` 0, `grand_total_cents` 0, `paid_cents` 0, and a `payment_status` of `UNPAID`.

Travelers are added one at a time, by an `AgencyAdmin` or `TravelAgent`, only while the booking is `DRAFT`; an add attempted in any other state is rejected with `ERR_INVALID_STATE`. Each traveler carries a `full_name` and, optionally, a `passport_no`. The system stamps `is_lead` itself: the very first traveler added to a booking is forced to `is_lead` true, and every traveler added afterward is `is_lead` false. The add request must also carry `expected_booking_version` (see §2.7). On a successful add, the booking's `traveler_count` increases by one, `subtotal_cents` and `grand_total_cents` are re-quoted, and the booking's `version` increments.

The re-quote applies the **group-discount per-person pricing** rule. Let n be the number of travelers now on the booking and let the base be the package's `base_price_per_person_cents`. The discount percentage is selected by headcount: if n is below the package's `min_group_size_for_discount`, the discount is 0 percent; if n is at least `min_group_size_for_discount` but fewer than 8, the discount is 5 percent; if n is at least 8 but fewer than 15, the discount is 10 percent; and if n is 15 or more, the discount is 15 percent. The per-person price is then computed in a pinned order that must not be rearranged: first take the base, multiply by one hundred minus the discount percentage, divide by one hundred, and round that per-person figure half-up to whole cents; only then multiply the rounded per-person price by n to obtain `subtotal_cents`. Rounding happens once, on the per-person amount, before the multiply — never after.

### 3.4. Attaching Insurance and the Live Quote

While a booking is still `DRAFT`, an `AgencyAdmin` or `TravelAgent` may attach a travel-insurance add-on by naming the `booking_id` and a `coverage_tier` of either `BASIC` or `PREMIUM`. An attach attempted when the booking is not `DRAFT` is rejected with `ERR_INVALID_STATE`. The policy's `premium_cents` is computed at attach time from the current `traveler_count`: a `BASIC` policy costs 1500 cents per traveler and a `PREMIUM` policy costs 4000 cents per traveler, with the premium being simply that per-traveler rate multiplied by the headcount in exact whole cents with no rounding. The premium is frozen on the policy thereafter. The `coverage_tier` also fixes the policy's `refundable` flag: `BASIC` policies are non-refundable, and `PREMIUM` policies are refundable. A policy is born `ACTIVE` and can only later become `VOIDED` through booking cancellation.

The booking's `insurance_premium_cents` is the sum of the `premium_cents` of all `ACTIVE` insurance policies attached to it, and its `grand_total_cents` is `subtotal_cents` plus `insurance_premium_cents`. While the booking is `DRAFT`, this is a **provisional quote**: every traveler add and every insurance attach re-derives `subtotal_cents`, `insurance_premium_cents`, and `grand_total_cents` against the live roster of travelers and policies, and no payment milestones exist yet. The grand total is the figure the payment milestones will eventually have to cover.

### 3.5. Sourcing Components from Suppliers

A booking's itinerary is assembled from components, each requested by an `AgencyAdmin` or `TravelAgent` against a chosen supplier. A component request names the `booking_id`, the `supplier_id`, the component `kind` (`FLIGHT`, `HOTEL`, or `ACTIVITY`), a `starts_at` and `ends_at` timestamp pair, and an optional `is_mandatory` flag that defaults to true. The parent booking must be in `DRAFT` or `RESERVED`, otherwise the request is rejected with `ERR_INVALID_STATE`. The chosen supplier's `kind` must equal the component's `kind`, or the request is rejected with `ERR_INVALID_REFERENCE`. The interval must be well-formed — `ends_at` must be strictly after `starts_at` — or it is rejected with `ERR_INVALID_INTERVAL`.

Two distinct overlap rules then guard the request, depending on the component's kind, and they have deliberately different geometry. For a `HOTEL` component, the system looks at the other `HOTEL` components on the **same booking** booked against the **same supplier** that are still in `REQUESTED` or `CONFIRMED` status, and applies a half-open clash test: the new component clashes with an existing one when the new component's `starts_at` is before the existing one's `ends_at` and the existing one's `starts_at` is before the new component's `ends_at`. Both comparisons are strict, so two stays that merely touch at a boundary — where one's `ends_at` equals the next one's `starts_at` — do not clash and are allowed; any genuine overlap is rejected with `ERR_COMPONENT_OVERLAP`. For a `FLIGHT` or `ACTIVITY` component, the resource being protected is the supplier's aggregate capacity across **all bookings**: the system looks at components of the **same supplier** and **same kind** on any booking that are in `REQUESTED` or `CONFIRMED` status (those that are `RELEASED` or `REJECTED` are excluded), and inflates each interval by a two-hour turnaround buffer of 7200 seconds before testing. The new component conflicts when its `starts_at` is before the existing component's `ends_at` plus the buffer and the existing component's `starts_at` is before the new component's `ends_at` plus the buffer; because of the buffer inflation, even adjacent or touching intervals conflict, and the request is rejected with `ERR_SUPPLIER_CAPACITY_CONFLICT`.

A component that survives the checks is born `REQUESTED` — unless the chosen supplier has `auto_confirm` set, in which case the system confirms it immediately, landing it directly in `CONFIRMED` at request time. A component's `status` therefore lives among `REQUESTED`, `CONFIRMED`, `REJECTED`, and `RELEASED`. The `is_mandatory` flag determines how much weight the component carries downstream: a mandatory component must reach `CONFIRMED` before the booking can be confirmed, while an optional one may safely remain `REJECTED`.

### 3.6. Supplier Confirmation, Reservation, and the Bubble-Up Revision Cycle

A `Supplier` works its own queue. Confirming a component it owns advances that component `REQUESTED → CONFIRMED`; rejecting one advances it `REQUESTED → REJECTED`. Both actions require the acting supplier to own the component — its `supplier_id` must equal `X-User-ID`, else `ERR_FORBIDDEN_FOR_ROLE` — and require the parent booking to be in `DRAFT` or `RESERVED`, else `ERR_INVALID_STATE`. (The system itself also performs the `REQUESTED → CONFIRMED` transition at request time for an `auto_confirm` supplier, with no ownership check.)

Reserving a booking is the hinge of the whole workflow, and only a `TravelAgent` performs it, advancing the booking `DRAFT → RESERVED`. The reserve request carries `expected_booking_version`, which must match the booking's current `version` (else `ERR_STALE_VERSION`). Four further preconditions must hold: the booking's `TourPackage` must be `PUBLISHED` (else `ERR_PACKAGE_NOT_PUBLISHED`); the booking must have at least one traveler, i.e. `traveler_count` of 1 or more (else `ERR_NO_TRAVELERS`); and at least one mandatory component must exist on the booking in `REQUESTED` or `CONFIRMED` status (else `ERR_NO_COMPONENTS`). On reserve, the price is frozen — this is the **finalized quote**: `subtotal_cents`, `insurance_premium_cents`, and `grand_total_cents` are computed one final time from the current travelers and active policies and then fixed, so that later traveler adds (now blocked because the booking is no longer `DRAFT`) cannot make the milestone amounts drift from the frozen grand total. Reserve also generates the two payment milestones (§3.8), recomputes `payment_status` to `UNPAID`, and increments the booking's `version`.

The reservation can be unwound from below. When a supplier rejects a component that is `is_mandatory` while its parent booking is `RESERVED`, a bubble-up revision cascade fires: the parent booking is forced back `RESERVED → DRAFT` for re-sourcing, all of its `OPEN` payment milestones are moved to `WAIVED`, its `payment_status` is recomputed (with no open or settled milestones remaining, it lands at `UNPAID`), and the booking's `version` increments. This is the system's mechanism for a late supplier decline reopening a booking that had already been reserved. (Rejecting a non-mandatory component, or rejecting any component while the booking is merely `DRAFT`, simply marks the component `REJECTED` without touching the booking's lifecycle.)

### 3.7. Confirming, Cancelling, Penalties, and Refunds

Confirming a booking is the final lifecycle step before travel, performed by a `TravelAgent`, advancing it `RESERVED → CONFIRMED`. It carries `expected_booking_version` (else `ERR_STALE_VERSION`) and demands that sourcing be complete before money is complete: every `is_mandatory` component on the booking must be `CONFIRMED` (else `ERR_COMPONENTS_NOT_CONFIRMED`), and the deposit milestone must be `SETTLED` (else `ERR_DEPOSIT_NOT_SETTLED`). Confirmation increments the booking's `version`.

Cancellation is available to a `Customer` (only for their own booking — the booking's `customer_id` must equal `X-User-ID`, else `ERR_FORBIDDEN_FOR_ROLE`) or to a `TravelAgent`, from any of `DRAFT`, `RESERVED`, or `CONFIRMED`, driving the booking to the terminal `CANCELLED` state. Every cancel carries `expected_booking_version` (else `ERR_STALE_VERSION`) and an optional `refund_destination` of either `WALLET` or `ORIGINAL`, defaulting to `ORIGINAL`. Cancelling creates exactly one `CancellationRecord` (there is at most one per booking), whose `cancelled_at` is stamped from the agency's `now_utc`.

A cancellation from `DRAFT` is the trivial case: no milestones or payments exist, so the record is written with `penalty_tier` `TIER_FREE`, `penalty_pct` 0, `penalty_cents` 0, `refundable_base_cents` equal to `grand_total_cents`, and `refund_cents` 0. A cancellation from `RESERVED` or `CONFIRMED` computes a real penalty and refund. The **penalty tier** is chosen from how far departure is: let the days to departure be the whole number of 86400-second days between the agency's `now_utc` and the booking's `departure_date`, taking the floor (counting only complete days). If the days to departure are 60 or more, the tier is `TIER_FREE` with a `penalty_pct` of 0; if they are at least 30 but fewer than 60, the tier is `TIER_LOW` with a `penalty_pct` of 25; if they are at least 7 but fewer than 30, the tier is `TIER_HIGH` with a `penalty_pct` of 50; and if they are fewer than 7 (including a departure already in the past), the tier is `TIER_FULL` with a `penalty_pct` of 100. The boundaries are inclusive at the lower end — a booking exactly 30 days out is `TIER_LOW`, while one 29 days out is `TIER_HIGH`.

The **refund** is then computed in cents. First, the `refundable_base_cents` is `grand_total_cents` minus the sum of the `premium_cents` of every `ACTIVE` insurance policy on the booking whose `refundable` flag is false — that is, the non-refundable `BASIC` premiums are carved out of the base before the penalty is taken, while refundable `PREMIUM` premiums stay in the base. The `penalty_cents` is the `refundable_base_cents` multiplied by the chosen `penalty_pct`, divided by one hundred, rounded half-up to whole cents. The `refund_cents` is the booking's `paid_cents` (measured before this cancellation reverses any payments) minus the `penalty_cents`, floored at zero so the refund can never be negative.

The cancel then compensates the whole aggregate. Every `APPLIED` payment on the booking is moved to `REFUNDED` (and each refund reverses its allocation against its milestone's `settled_amount_cents`); every `OPEN` payment milestone is moved to `WAIVED`; the booking's `paid_cents` is recomputed to 0; every `ACTIVE` insurance policy is moved to `VOIDED`; and every component not already `RELEASED` is moved to `RELEASED` (a confirmed, requested, or rejected component all land at `RELEASED`). If the `refund_destination` is `WALLET`, the customer's `wallet_credit_cents` is increased by `refund_cents`; if it is `ORIGINAL`, the `refund_cents` is reported on the `CancellationRecord` and the customer's wallet is left untouched. The booking's `version` increments. The `CancellationRecord` records the chosen `penalty_tier`, `penalty_pct`, `refundable_base_cents`, `penalty_cents`, `refund_cents`, and `refund_destination`.

### 3.8. Payment Milestones, Payments, and Payment Status

When a booking is reserved, the system generates exactly two payment milestones against it, a `DEPOSIT` and a `BALANCE`, each carrying the `booking_id`, a `kind`, an `amount_due_cents`, a `due_date`, a `settled_amount_cents` (starting at 0), and a `status`. The split is computed from the frozen grand total in a pinned order. The deposit's `amount_due_cents` is the `grand_total_cents` multiplied by the package's `deposit_pct`, divided by one hundred, rounded half-up to whole cents. The balance's `amount_due_cents` is then the exact remainder — `grand_total_cents` minus the deposit's `amount_due_cents` — and is never independently rounded, so that the deposit and balance always sum back to the grand total with zero cent drift. The deposit's `due_date` is the agency's `now_utc` at the moment of reservation; the balance's `due_date` is the booking's `departure_date` minus the package's `balance_due_days_before_departure` days.

A milestone's `status` is `OPEN`, `SETTLED`, or `WAIVED`. It is `SETTLED` exactly when its `settled_amount_cents` reaches or exceeds its `amount_due_cents` (a "meets-or-exceeds" test, not strictly greater). It becomes `WAIVED` only through the cancellation sweep or the bubble-up reopen described above.

A payment is recorded by an `AgencyAdmin`, a `TravelAgent`, or the owning `Customer`, naming the `booking_id`, the target `milestone_id`, an `amount_cents` greater than zero, and an optional `method` of `CARD`, `WALLET`, or `BANK_TRANSFER` (defaulting to `CARD`). The booking must be `RESERVED` or `CONFIRMED`, else `ERR_INVALID_STATE`. A payment's `amount_cents` may not exceed the targeted milestone's remaining due — its `amount_due_cents` minus its current `settled_amount_cents` — or the payment is rejected as an overpayment with `ERR_OVERPAYMENT`. Milestones are also ordered: a payment against the `BALANCE` milestone is rejected with `ERR_DEPOSIT_NOT_SETTLED` until the `DEPOSIT` milestone is `SETTLED`. A payment is born `APPLIED`; on apply, the targeted milestone's `settled_amount_cents` increases by the payment's `amount_cents`, the booking's `paid_cents` (the sum of `amount_cents` over all `APPLIED` payments on the booking) is recomputed, and the booking's `payment_status` is recomputed. A payment can only later become `REFUNDED`, which happens through the cancellation sweep; a `REFUNDED` payment no longer counts toward `paid_cents` or toward any milestone's settlement.

The booking's `payment_status` is a parallel dimension derived purely from milestone settlement and evolving independently of the booking's lifecycle `status`. It is recomputed on payment apply, on reserve, and during the cancel and reopen sweeps. If the booking has no payment milestone in `OPEN` or `SETTLED` state — because none were ever generated, or because all have been `WAIVED` — the `payment_status` is `UNPAID`. Otherwise, if the booking has a `BALANCE` milestone that is `SETTLED`, the `payment_status` is `PAID_IN_FULL`; otherwise, if the `DEPOSIT` milestone is `SETTLED`, it is `DEPOSIT_PAID`; otherwise it is `UNPAID`.

### 3.9. System-Driven Payment Reversal

When a booking cancellation refunds an `APPLIED` payment, that payment moves `APPLIED → REFUNDED` and the reversal flows through the ledger: the affected milestone's `settled_amount_cents` decreases by the payment's `amount_cents`, which may flip that milestone back from `SETTLED` to `OPEN` (after which the cancel sweep waives it), and the booking's `paid_cents` is recomputed. This is the same reversal referenced by the cancellation compensation in §3.7, viewed from the payment's own lifecycle, and it is how `paid_cents` lands at 0 after a cancel even when payments had previously settled milestones.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the lifecycle transitions (publish, retire, reserve, confirm, cancel, component confirm/reject) and the clock-setting capability — return a `200 OK` status code. All read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agencies` | Create an Agency | AgencyAdmin |
| GET | `/agencies/{agencyId}` | Get an Agency | AgencyAdmin, TravelAgent, Customer, Supplier |
| POST | `/agencies/{agencyId}/_clock/set` | Set the agency simulation clock | AgencyAdmin |
| POST | `/agencies/customers` | Create a Customer | AgencyAdmin, TravelAgent |
| GET | `/agencies/customers/{customerId}` | Get a Customer | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/customers` | List Customers | AgencyAdmin, TravelAgent |
| POST | `/agencies/suppliers` | Create a Supplier | AgencyAdmin |
| GET | `/agencies/suppliers/{supplierId}` | Get a Supplier | AgencyAdmin, TravelAgent, Supplier |
| GET | `/agencies/suppliers` | List Suppliers | AgencyAdmin, TravelAgent |
| POST | `/agencies/tour-packages` | Create a TourPackage | TravelAgent |
| GET | `/agencies/tour-packages/{packageId}` | Get a TourPackage | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/tour-packages` | List TourPackages | AgencyAdmin, TravelAgent, Customer |
| POST | `/agencies/tour-packages/{packageId}/publish` | Publish a TourPackage | TravelAgent |
| POST | `/agencies/tour-packages/{packageId}/retire` | Retire a TourPackage | TravelAgent |
| POST | `/agencies/bookings` | Open a Booking | AgencyAdmin, TravelAgent |
| GET | `/agencies/bookings/{bookingId}` | Get a Booking | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/bookings` | List Bookings | AgencyAdmin, TravelAgent, Customer |
| POST | `/agencies/bookings/{bookingId}/reserve` | Reserve a Booking | TravelAgent |
| POST | `/agencies/bookings/{bookingId}/confirm` | Confirm a Booking | TravelAgent |
| POST | `/agencies/bookings/{bookingId}/cancel` | Cancel a Booking | Customer, TravelAgent |
| POST | `/agencies/bookings/{bookingId}/travelers` | Add a Traveler to a Booking | AgencyAdmin, TravelAgent |
| GET | `/agencies/travelers/{travelerId}` | Get a Traveler | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/travelers` | List Travelers | AgencyAdmin, TravelAgent, Customer |
| POST | `/agencies/components` | Request a BookingComponent | AgencyAdmin, TravelAgent |
| GET | `/agencies/components/{componentId}` | Get a BookingComponent | AgencyAdmin, TravelAgent, Customer, Supplier |
| GET | `/agencies/components` | List BookingComponents | AgencyAdmin, TravelAgent, Customer, Supplier |
| POST | `/agencies/components/{componentId}/confirm` | Confirm a BookingComponent | Supplier |
| POST | `/agencies/components/{componentId}/reject` | Reject a BookingComponent | Supplier |
| POST | `/agencies/insurance-policies` | Attach an InsurancePolicy | AgencyAdmin, TravelAgent |
| GET | `/agencies/insurance-policies/{policyId}` | Get an InsurancePolicy | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/insurance-policies` | List InsurancePolicies | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/milestones/{milestoneId}` | Get a PaymentMilestone | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/milestones` | List PaymentMilestones | AgencyAdmin, TravelAgent, Customer |
| POST | `/agencies/payments` | Record a Payment | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/payments/{paymentId}` | Get a Payment | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/payments` | List Payments | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/cancellation-records/{recordId}` | Get a CancellationRecord | AgencyAdmin, TravelAgent, Customer |
| GET | `/agencies/cancellation-records` | List CancellationRecords | AgencyAdmin, TravelAgent, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_REFERENCE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_INTERVAL` | 422 Unprocessable Entity |
| `ERR_COMPONENT_OVERLAP` | 409 Conflict |
| `ERR_SUPPLIER_CAPACITY_CONFLICT` | 409 Conflict |
| `ERR_PACKAGE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PACKAGE_HAS_OPEN_BOOKINGS` | 409 Conflict |
| `ERR_NO_TRAVELERS` | 409 Conflict |
| `ERR_NO_COMPONENTS` | 409 Conflict |
| `ERR_COMPONENTS_NOT_CONFIRMED` | 409 Conflict |
| `ERR_DEPOSIT_NOT_SETTLED` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
