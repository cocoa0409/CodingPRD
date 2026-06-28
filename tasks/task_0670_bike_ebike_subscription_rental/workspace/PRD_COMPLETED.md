# Bike & E-Bike Subscription Rental API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Bike & E-Bike Subscription Rental platform, a back-end service that operates a fleet of standard bicycles, electric bikes, and cargo electric bikes under both long-term monthly subscriptions and short-term daily rentals. The platform must keep an exact, real-time picture of how many physical units of each model are free to rent while letting individual subscribers and delivery-rider fleet businesses reserve bikes, take delivery, swap units, log maintenance, file theft and damage claims, and ultimately either return or buy out the bike they have been riding.

Two pressures shape almost every rule in this system. The first is scarcity: each bike model is backed by a finite pool of serial-numbered units, and a reservation must reflect the true, current availability of that pool — two clients must never be able to reserve the same last unit on the strength of a stale view of the fleet. The second is money: the platform holds refundable deposits, prorates the first subscription cycle, applies tiered discounts to long daily rentals, accrues late fees, settles return charges against deposits, decays buyout prices by the equity a subscriber has earned, and bills fleet accounts with volume discounts. Every monetary figure is tracked to the cent, and every settlement must be reconstructable from the inputs.

The remainder of this document defines the global contract that all endpoints share (Section 2), the detailed business workflows and their scattered rules (Section 3), the full endpoint catalogue (Section 4), and the canonical error code table (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope conventions, and cross-cutting principles that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request that targets an authenticated endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly five roles, spelled precisely as follows: `Subscriber`, `FleetManager`, `FieldTech`, `OpsAdmin`, and `Anonymous`. If either header is missing on an authenticated endpoint, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

A small number of endpoints are open without authentication: opening an account and setting the logical clock do not require the headers. All other endpoints require them. Creating a bike model is not public: it requires the `X-User-ID` and `X-User-Role` headers and is restricted to the `OpsAdmin` role per Section 4, so the header and role checks of this section apply to it (a missing or unknown-role header yields `ERR_UNAUTHENTICATED`, and a non-`OpsAdmin` role yields `ERR_FORBIDDEN_ROLE`).

Two of the five roles are **entity-backed**. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's account foreign key to `X-User-ID`. Concretely, a `Subscriber` may act on a `RentalAgreement` only when the agreement's `account_id` equals `X-User-ID`, and acting on another account's rental yields `ERR_FORBIDDEN_ROLE`. When `X-User-Role` is `FleetManager`, `X-User-ID` is likewise the `id` of the acting `Account`; the same ownership comparison applies, and a `FleetManager` additionally owns and operates a `FLEET`-type account whose rentals and invoices it administers.

The remaining three roles are **opaque**. When `X-User-Role` is `FieldTech`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `OpsAdmin`, `X-User-ID` is similarly an opaque platform-operator identifier used for catalog, fleet, claim, cycle, and clock administration, again never compared to an entity `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` carries no entity meaning and the caller may only open an account.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. A supplied `limit` outside this range is clamped to the nearest bound (values below 1 become 1 and values above 100 become 100) rather than rejected, and a non-integer or unparseable `limit` falls back to the default of 10. The `offset` parameter sets how many items to skip from the front of the result and defaults to 0; a negative `offset` is clamped to 0 and a non-integer or unparseable `offset` falls back to 0.

Unless an endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of matching records before pagination, `limit` and `offset` echo the effective (post-clamp) values used, and `has_more` is true exactly when `offset` plus the number of items returned in this page is strictly less than `total_count`.

### 2.4. Common Resource Properties and Logical Clock

Most resources in this system share a set of server-managed fields. Every such resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits, an `updated_at` timestamp of the same format that is refreshed on every mutation, and a `version` integer that begins at its initial value of `1` on creation and increments by one on every subsequent mutation. The entities that carry this full set are `BikeModel`, `Account`, `RentalAgreement`, `Delivery`, `ServiceTicket`, `CoverageClaim`, `BuyoutOffer`, `FleetInvoice`, and `Bike`.

The `InspectionReport` is the one exception: it is written once at return time and never mutated. It carries only `id` and `created_at`; it has neither an `updated_at` field nor a `version` field.

This platform does not read the wall clock. Instead it maintains a **logical clock** that drives every time-dependent rule — cycle anchoring, daily billing windows, late-fee accrual, delivery windows, buyout expiry, and incident timestamps. At server startup the logical clock reads exactly `2026-04-01T00:00:00Z`, and before any clock-setting call it holds this default and never falls back to real time. An administrative capability sets the clock to a supplied instant; all subsequent reads of "the current logical clock" return that value until it is set again.

### 2.5. Hierarchical Consistency, Cascades, and Derived Counts

This is a flat domain of peer entities linked by foreign keys rather than a nested ownership tree, but many operations mutate several entities at once, and those secondary mutations must be applied atomically with the primary one. Whenever a `RentalAgreement`, `Delivery`, `ServiceTicket`, `CoverageClaim`, `BuyoutOffer`, or `Bike` is mutated, its `updated_at` is refreshed and its `version` increments by one. When a cascade touches more than one entity, every affected entity has its own `version` incremented and `updated_at` refreshed independently.

Two count fields are **derived** and must be reconciled (fully recomputed, not blindly incremented) whenever the underlying rows change. On a `BikeModel`, `total_bikes` is the count of `Bike` rows whose `model_id` equals that model's `id` regardless of their status, and `available_count` is the count of those `Bike` rows whose `bike_status` is `AVAILABLE`; both are recomputed on every reserve, release, retire, and buyout. On an `Account`, `active_rental_count` is the count of `RentalAgreement` rows for that account whose `lifecycle_status` is one of `RESERVED`, `DELIVERED`, `ACTIVE`, or `IN_SERVICE`, and it is recomputed on every rental lifecycle transition. Also derived on an `Account` is `outstanding_balance_cents`, the sum of `amount_due_cents` across that account's `FleetInvoice` rows still in `ISSUED` status, plus any settlement overflow that was billed but remains unpaid.

For requests whose path or body carries several identifiers, the platform validates them left to right — account, then model, then rental, then bike, then ticket, then claim, then offer, then invoice, then delivery — and the first identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404) before any later identifier or business rule is evaluated.

### 2.6. Monetary Precision and Rounding

All money in this system is stored and computed in integer cents; there are no fractional-cent fields. Where a rule multiplies a cent amount by a fractional rate or a proration factor, the result is rounded **half up** to the nearest whole cent. Two precision conventions are load-bearing and recur throughout Section 3. First, when a per-unit charge is multiplied by a rate and then accumulated across many units (tiered daily rates, per-line fleet discounts), each per-unit amount is rounded half up **before** the amounts are summed — this is round-then-sum, never sum-then-round. Second, the waterfall settlement and late-fee computations operate purely on integer inputs and therefore need no rounding at all.

### 2.7. Optimistic Concurrency on Reservation

Reserving a bike is the one write in this system guarded by optimistic concurrency control, because a reservation draws a unit from a finite model pool and advances that pool's bookkeeping. The reservation request must carry `expected_model_version`, a non-optional field holding the `version` of the target `BikeModel` that the client last observed. The server compares this value against the model's current `version`. If another writer has advanced the model's `version` since the client read it — for example, a prior reservation that already consumed a unit and recomputed `available_count` — then the client is acting on a stale view of pool availability, and the reservation is rejected with `ERR_STALE_MODEL_VERSION` (HTTP 412). A successful reservation itself increments the `BikeModel.version` by one, so a second create still carrying the pre-advance value will fail this check. No other endpoint in the system takes a version field or performs this check.

### 2.8. Status Codes

Creating a new, standalone resource returns HTTP 201. Operations that modify or transition an existing resource return HTTP 200. The specific code for each endpoint is given in Section 4.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog and the Physical Fleet

The platform's inventory begins with an `OpsAdmin` defining a **bike model**, the catalog entry from which rentals draw. A model is created with a marketing `name`, a `model_class` that is one of `STANDARD`, `EBIKE`, or `CARGO_EBIKE`, a base monthly subscription fee `monthly_fee_cents`, a base full daily rate `daily_rate_cents`, a base buyout `purchase_price_cents`, the refundable `deposit_cents` held at the start of any rental of this model, and a declared `fleet_size` target. Each of these money fields must be a non-negative integer number of cents, and `fleet_size` must be at least zero. A freshly created model starts with `total_bikes` and `available_count` both at zero and its `status` set to `ACTIVE`; the status can later be one of `ACTIVE` or `RETIRED`.

Physical units are added one at a time. Adding a **bike** to a model's fleet supplies the `model_id` it belongs to and a `serial_number` that must be globally unique across all bikes; a serial collision is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409). A new bike begins life with `bike_status` `AVAILABLE` and a null `current_rental_id`, and its creation reconciles the owning model's `available_count` and `total_bikes`. Over its life a bike's `bike_status` moves through the set `AVAILABLE`, `RESERVED`, `OUT`, `SERVICING`, and `RETIRED`, while `current_rental_id` points at the agreement currently holding it and is null whenever the bike is `AVAILABLE` or `RETIRED`.

An `OpsAdmin` may retire a bike directly, but only while it is `AVAILABLE`: retiring transitions `bike_status` from `AVAILABLE` to `RETIRED` and reconciles both `available_count` and `total_bikes` on the model. Attempting to retire a bike that is not `AVAILABLE` is an undefined transition and is rejected with `ERR_INVALID_STATE` (HTTP 409). The list of bikes for a model can be filtered by `bike_status`, and the general bike listing can be filtered by `model_id`, `current_rental_id`, and `bike_status`.

### 3.2. Accounts, Suspension, and Fleet Standing

Anyone may open an **account** without authentication. An account is created with an `account_type` that is either `SUBSCRIBER` (an individual rider) or `FLEET` (a delivery-rider business), a `display_name`, and an `email` that is globally unique and compared case-insensitively across all accounts; a duplicate email is rejected with `ERR_DUPLICATE_RESOURCE`. The optional `rental_cap` sets the maximum number of concurrently active rentals the account may hold; it defaults to 1 and must be at least 1, with subscriber accounts typically capped at 1 and fleet accounts higher. On creation the account's `wallet_credit_cents` (its refundable credit balance, into which deposit refunds and overpayments land) starts at 0, its `active_rental_count` starts at 0, and its `status` is `ACTIVE`. An account's `status` is one of `ACTIVE` or `SUSPENDED`.

An `OpsAdmin` may suspend an account, setting its `status` to `SUSPENDED`. A suspended account is blocked from creating new reservations, as Section 3.3 describes. The account fetch endpoint exposes the computed `active_rental_count` and `outstanding_balance_cents` alongside the stored fields, and an account's rentals can be listed and filtered by `lifecycle_status`.

### 3.3. Reserving a Bike

A `Subscriber` or `FleetManager` reserves a bike by submitting the `account_id` that will hold the rental, the `model_id` whose pool to draw from, a `rental_mode` of either `MONTHLY` or `DAILY`, a scheduled `return_due_clock`, and the `expected_model_version` for the concurrency check of Section 2.7. The server itself selects which physical unit to commit and snapshots the deposit; the client never names a `bike_id`.

Several guards apply to a reservation, and their relative order matters because the platform reports the first violation it reaches. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN_ROLE`). Concretely, the platform then checks that the required fields (`account_id`, `model_id`, `rental_mode`, `return_due_clock`, `expected_model_version`) are all present, raising `ERR_INVALID_REQUEST` (HTTP 400) for any missing field before it resolves the referenced ids; next it resolves existence of every referenced id left to right (`ERR_NOT_FOUND`), starting with `account_id` then `model_id`; next it applies the ownership check that the entity-backed caller's `X-User-ID` equals the resolved account's `id` (`ERR_FORBIDDEN_ROLE`); and only then does it complete the remaining request-body well-formedness checks that `rental_mode` is a valid enum, `expected_model_version` is an integer, and `return_due_clock` is a well-formed instant (`ERR_INVALID_REQUEST`, HTTP 400). The optimistic-concurrency comparison of `expected_model_version` against the model's current `version` comes next and rejects a stale request with `ERR_STALE_MODEL_VERSION` (HTTP 412). After that the business guards apply in this order: a `SUSPENDED` account cannot reserve and is rejected with `ERR_ACCOUNT_SUSPENDED` (HTTP 409); an account already holding a number of active rentals equal to or greater than its `rental_cap` is rejected with `ERR_RENTAL_CAP_EXCEEDED` (HTTP 409); and a model whose pool has no free unit — that is, whose `available_count` is below one — is rejected with `ERR_NO_BIKES_AVAILABLE` (HTTP 409).

When all guards pass, the reservation is created. The server picks the `AVAILABLE` bike of that model with the earliest `created_at`, sets that `bike_status` from `AVAILABLE` to `RESERVED` and points its `current_rental_id` at the new agreement. The new `RentalAgreement` records its `account_id`, the chosen `bike_id`, the requested `model_id`, the `rental_mode`, the supplied `return_due_clock`, and a `reserved_at_clock` set to the current logical clock — this instant anchors the first billing cycle. Its `deposit_cents` is snapshotted from the model's `deposit_cents` at this moment. The agreement opens with `lifecycle_status` `RESERVED` and `billing_status` `DEPOSIT_HELD`, `completed_cycles` at 0, and `accrued_charge_cents` at 0. The reservation then recomputes the model's `available_count`, recomputes the account's `active_rental_count`, and increments the `BikeModel.version` by one. A holding `Subscriber` or `FleetManager` may cancel a reservation while it is still `RESERVED` (any other `lifecycle_status` is rejected with `ERR_INVALID_STATE`): cancellation transitions `lifecycle_status` to `CANCELLED`, returns the bike from `RESERVED` to `AVAILABLE` and clears its `current_rental_id`, recomputes the model's `available_count`, sets `billing_status` to `SETTLED` and refunds the full `deposit_cents` to the account's `wallet_credit_cents` (a compensating refund since the reservation was never consumed), and cancels any `SCHEDULED` delivery for the rental. Rentals can be listed and filtered by `account_id`, `model_id`, `bike_id`, `rental_mode`, and `lifecycle_status`; when the caller is an entity-backed role (`Subscriber` or `FleetManager`), the rental list is implicitly restricted to rentals whose `account_id` equals `X-User-ID` before any supplied filter is applied, whereas `OpsAdmin` and `FieldTech` see all rentals.

The `lifecycle_status` of a rental progresses through the set `RESERVED`, `DELIVERED`, `ACTIVE`, `IN_SERVICE`, `RETURN_REQUESTED`, `RETURNED`, `BOUGHT_OUT`, and `CANCELLED`, with `RETURNED`, `BOUGHT_OUT`, and `CANCELLED` being terminal. Running in parallel and evolving independently, the `billing_status` moves through `DEPOSIT_HELD`, `BILLING_ACTIVE`, `SETTLED`, and `WRITTEN_OFF`.

### 3.4. Delivery, Swap, and Activation

A delivery is scheduled by an `OpsAdmin` or `FieldTech` against a `rental_id`, with a `delivery_type` of `INITIAL` (the first drop-off), `SWAP` (exchanging the current bike for a replacement), or `PICKUP` (collecting a bike on return), a destination `address`, and a half-open requested window described by an inclusive `window_start_clock` and an exclusive `window_end_clock`. The window must be well-formed: `window_start_clock` must be strictly earlier than `window_end_clock`, otherwise the delivery is rejected with `ERR_DELIVERY_WINDOW_CONFLICT` (HTTP 409). Beyond well-formedness, a new delivery must not collide with an existing `SCHEDULED` delivery for the **same** rental: if the two half-open intervals `[start, end)` share any single instant, the new request is rejected with the same `ERR_DELIVERY_WINDOW_CONFLICT`. The `delivery_type` must also match the rental's current `lifecycle_status` — `INITIAL` requires the rental to be `RESERVED`, `PICKUP` requires it to be `RETURN_REQUESTED`, and `SWAP` requires it to be either `DELIVERED` or `ACTIVE` — and a mismatch is rejected with `ERR_DELIVERY_TYPE_MISMATCH` (HTTP 409). A delivery's own `status` is one of `SCHEDULED`, `COMPLETED`, or `CANCELLED`, beginning at `SCHEDULED`. When the delivery is a `SWAP`, the server selects a replacement `AVAILABLE` bike from the same model's pool — the `AVAILABLE` bike with the earliest `created_at` — and records it as `swap_to_bike_id`; if the pool has no free unit at scheduling time the `SWAP` is still created with `swap_to_bike_id` left null (no error is raised for an unavailable replacement). For non-swap deliveries that field stays null. Deliveries can be listed and filtered by `rental_id`, `swap_to_bike_id`, and `status`.

Completing a delivery is a `FieldTech` action that sets the delivery `status` to `COMPLETED` and then branches on `delivery_type`. Completing any delivery first requires that the delivery's own `status` be `SCHEDULED`, and a delivery that is already `COMPLETED` or `CANCELLED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Completing the `INITIAL` delivery advances the rental's `lifecycle_status` from `RESERVED` to `DELIVERED` and transitions the bike's `bike_status` from `RESERVED` to `OUT`; this transition requires that the rental be `RESERVED`, that this `INITIAL` delivery be `SCHEDULED`, and that the bike be `RESERVED`, with a rental not `RESERVED` or a bike not `RESERVED` likewise rejected with `ERR_INVALID_STATE`. Completing a `SWAP` delivery returns the old bike from `OUT` to `AVAILABLE` and clears its `current_rental_id`, transitions the replacement `swap_to_bike_id` bike from `RESERVED` to `OUT`, repoints the agreement's `bike_id` to the replacement, and recomputes the model's `available_count`.

Once a bike has been delivered, the holding `Subscriber` or `FleetManager` activates the rental. Activation requires the rental to be `DELIVERED` and rejects any other `lifecycle_status` with `ERR_INVALID_STATE` (HTTP 409); it advances `lifecycle_status` from `DELIVERED` to `ACTIVE`, sets `activated_at_clock` to the current logical clock (the start of the daily billing window or first monthly cycle), and sets `billing_status` to `BILLING_ACTIVE`. For a `MONTHLY` rental, activation charges the prorated first cycle described in Section 3.8; for a `DAILY` rental, activation begins the daily accrual that is finalized at return.

### 3.5. Maintenance Tickets and the Service Freeze

Maintenance is included with every rental. A `Subscriber`, `FleetManager`, or `FieldTech` opens a **service ticket** against a `rental_id`, declaring an `issue_type` from the set `FLAT_TIRE`, `BRAKE`, `BATTERY`, `MOTOR`, or `OTHER`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `description`. A ticket's `status` runs through `OPEN`, `IN_PROGRESS`, `RESOLVED`, `REOPENED`, and `CLOSED`, beginning at `OPEN`, with `CLOSED` terminal. Two guards apply at filing time: a ticket may not be opened against a rental whose bike is `RETIRED` (rejected with `ERR_BIKE_RETIRED`, HTTP 409), and a ticket may not be opened against a bike whose `bike_status` is already `SERVICING`, since the physical unit's servicing span is mutually exclusive — that overlap is rejected with `ERR_BIKE_ALREADY_SERVICING` (HTTP 409). Service tickets can be listed and filtered by `rental_id` and `status`.

A `CRITICAL` ticket freezes the rental at filing time: as an automatic side effect the bike's `bike_status` moves from `OUT` to `SERVICING` and the rental's `lifecycle_status` moves from `ACTIVE` to `IN_SERVICE`, with the rental's `version` incremented for the freeze. Non-critical tickets do not freeze the rental.

A `FieldTech` works the ticket: starting it advances an `OPEN` or `REOPENED` ticket to `IN_PROGRESS`; resolving it advances an `IN_PROGRESS` ticket to `RESOLVED` and records the supplied `resolution_note` (a required non-empty string). A holding `Subscriber` or `FleetManager` may reopen a `RESOLVED` ticket back to `REOPENED`, forming a revision loop, after which a `FieldTech` may start it again into `IN_PROGRESS`. Closing is a `FieldTech` action permitted only from `RESOLVED`, moving the ticket to `CLOSED`. Each of these four transitions invoked from a source state outside the one(s) named is an undefined transition rejected with `ERR_INVALID_STATE` (HTTP 409). Closing carries a conditional cascade: if the rental is currently `IN_SERVICE` and no other ticket for that rental remains in `OPEN`, `IN_PROGRESS`, or `REOPENED`, then the rental auto-transitions from `IN_SERVICE` back to `ACTIVE` and the bike returns from `SERVICING` to `OUT`, each with its `version` bumped. The auto-return out of `IN_SERVICE` requires that the triggering ticket be `RESOLVED` and that no other ticket for the rental sit in any of those three open states.

### 3.6. Requesting and Inspecting a Return

A holding `Subscriber` or `FleetManager` requests a return on an `ACTIVE` rental, supplying a `return_address`. This advances `lifecycle_status` from `ACTIVE` to `RETURN_REQUESTED` and creates a `SCHEDULED` `PICKUP` delivery for the rental. A return may not be requested on a rental whose bike is `RETIRED` (rejected with `ERR_BIKE_RETIRED`); the platform evaluates this write-off check first, then rejects a rental whose `lifecycle_status` is not `ACTIVE` with `ERR_INVALID_STATE` (HTTP 409), and only then validates that the required `return_address` is present and a non-empty string (`ERR_INVALID_REQUEST`). The `PICKUP` delivery is created with its `address` set to the supplied `return_address` and a degenerate window whose `window_start_clock` and `window_end_clock` both equal the current logical clock.

A `FieldTech` then files the return **inspection report**, supplying the returned `bike_condition` (one of `GOOD`, `WORN`, or `DAMAGED`), an assessed `damage_charge_cents` (zero when the condition is `GOOD`), and an assessed `cleaning_fee_cents`; both assessed amounts must be non-negative integers. Inspecting requires the rental to be `RETURN_REQUESTED` and that no inspection report already exists for the rental, and like other return-path actions it is blocked with `ERR_BIKE_RETIRED` when the bike has been written off; the write-off check is evaluated first, then the `RETURN_REQUESTED` state requirement, then the no-existing-report requirement, with both the wrong-state case and the already-inspected case rejected as `ERR_INVALID_STATE` (HTTP 409). Filing the report drives a three-hop cascade on a single transition. First, the platform computes the report's `late_fee_cents` and runs the settlement waterfall of Section 3.9 to populate `total_assessed_cents`, `deposit_applied_cents`, `deposit_refund_cents`, and `overflow_billed_cents`; it sets the rental's `returned_at_clock` to the current logical clock; sets `billing_status` to `SETTLED`; and refunds `deposit_refund_cents` to the account's `wallet_credit_cents` while billing `overflow_billed_cents` to the account. Second, the bike returns from `OUT` to `AVAILABLE` and its `current_rental_id` is cleared. Third, the model's `available_count` is reconciled. The rental's `lifecycle_status` becomes `RETURNED` and its `version` increments. Because the inspection files a new standalone `InspectionReport` resource, this endpoint responds with HTTP 201 and returns that newly created `InspectionReport` (not the rental) in the `data` field. Inspection reports can be fetched individually and listed, optionally filtered by `rental_id`.

### 3.7. Buyout Offers and Equity

A holding `Subscriber` or `FleetManager` may request a **buyout quote** on a rental, supplying an `expires_at_clock` after which the quote may no longer be accepted; that instant must be strictly after the current logical clock at the moment of quoting, and a quote with an `expires_at_clock` at or before the current clock is rejected with `ERR_OFFER_EXPIRED` (HTTP 409). Quoting computes the offer's `quoted_price_cents` and `equity_credit_cents` per Section 3.8 and opens the offer with `status` `QUOTED`; an offer's `status` is one of `QUOTED` or `ACCEPTED`. Buyout offers can be listed for a rental and filtered by `status`.

Accepting an offer is permitted only when the rental's `lifecycle_status` is `ACTIVE`, the offer's `status` is `QUOTED`, and the offer's `expires_at_clock` is strictly after the current logical clock. These conditions are checked in that order: a rental whose `lifecycle_status` is not `ACTIVE` is rejected with `ERR_INVALID_STATE` (HTTP 409), then an offer whose `status` is not `QUOTED` is rejected with `ERR_INVALID_STATE`, and finally an accept attempt at or after `expires_at_clock` is rejected with `ERR_OFFER_EXPIRED`. There is no separate expired status; expiry is enforced only at accept time. A successful accept sets the offer's `status` to `ACCEPTED` and runs a two-hop cascade: the bike transitions from `OUT` to `RETIRED` with its `current_rental_id` cleared, and the model's `available_count` and `total_bikes` are recomputed. The rental's `lifecycle_status` becomes `BOUGHT_OUT`, its `billing_status` becomes `SETTLED`, the full `deposit_cents` is refunded to the account's `wallet_credit_cents` (the deposit is released because the unit has been sold), and the rental's `version` increments.

### 3.8. Pricing: Subscription Proration, Tiered Daily Rates, and Buyout Decay

Pricing depends on the model's class. Each `model_class` carries a surcharge: `STANDARD` adds nothing, `EBIKE` adds 2000 cents, and `CARGO_EBIKE` adds 4000 cents. For monthly rentals the surcharge is added to the monthly fee; for daily rentals it is added to the daily rate.

For a `MONTHLY` rental, the **rental cost** accrued at activation is a prorated first cycle and lands in `accrued_charge_cents`. The effective monthly amount is the model's `monthly_fee_cents` plus the class surcharge. The first cycle is anchored at the rental's `reserved_at_clock`. The platform measures the whole-day offset from that anchor to `activated_at_clock` by taking the elapsed time, dividing by one day, and discarding any fractional remainder (a zero-based count of whole days into the first cycle). The remaining days in the cycle are 30 minus that offset. The first-cycle charge is the effective monthly amount multiplied by the remaining days, divided by 30, rounded half up to whole cents, and that value is stored as `accrued_charge_cents`. Later cycles are billed in full through the fleet-invoice and cycle-advance mechanisms rather than re-prorated.

For a `DAILY` rental, the cost is a tiered sum recomputed at return. The effective daily amount is the model's `daily_rate_cents` plus the class surcharge. The number of billed days is computed from the activation-to-return span — the elapsed time from `activated_at_clock` to `returned_at_clock`, divided by one day and rounded **up** to the next whole day — but never fewer than one day. The charge is then accumulated day by day across that count: each of the first 6 days bills the full effective daily amount; each day from the 7th through the 29th inclusive bills the effective daily amount multiplied by 0.85, rounded half up to whole cents; and each day from the 30th onward bills the effective daily amount multiplied by 0.70, rounded half up to whole cents. Each day's rounded amount is summed (round-then-sum), and the total is stored as `accrued_charge_cents`. There is no proration for daily rentals.

A **buyout price** is dual-variant. The base is the model's `purchase_price_cents`. For a `MONTHLY` (subscription) rental, the rider earns equity: the raw equity is the base multiplied by 0.03 per completed cycle (that is, base × 0.03 × `completed_cycles`), rounded half up; an equity cap equal to the base multiplied by 0.60, rounded half up, bounds it; the `equity_credit_cents` is the smaller of the raw equity and the cap; and the `quoted_price_cents` is the base minus `equity_credit_cents`. For a `DAILY` rental no equity is earned: `equity_credit_cents` is 0 and `quoted_price_cents` equals the base purchase price regardless of how long the bike was held.

The `completed_cycles` counter that drives equity is advanced by an `OpsAdmin` cycle-close capability: each invocation adds one to `completed_cycles`, and it does so only when the rental's `rental_mode` is `MONTHLY` and its `lifecycle_status` is either `ACTIVE` or `IN_SERVICE`; an invocation against a `DAILY` rental or a `MONTHLY` rental in any other `lifecycle_status` is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.9. Late Fees and the Return Settlement Waterfall

The **late fee** for a return is a threshold rule. If `returned_at_clock` is at or before the rental's `return_due_clock`, the late fee is 0. Otherwise the platform computes the overage as the elapsed time from `return_due_clock` to `returned_at_clock`, divided by one day and rounded up to the next whole day (any strictly positive overage rounds up to at least one day), and multiplies that whole-day count by the per-day late fee of 1500 cents to obtain `late_fee_cents`. The boundary is exact: a return at precisely `return_due_clock` incurs no fee, while a return strictly after it does.

The **return settlement** then runs as a waterfall over integer cents with no rounding. The `total_assessed_cents` is the sum of `damage_charge_cents`, `cleaning_fee_cents`, and `late_fee_cents`. The deposit absorbs charges first: `deposit_applied_cents` is the smaller of the rental's `deposit_cents` and `total_assessed_cents`. Any excess beyond the deposit is billed to the account: `overflow_billed_cents` is the greater of zero and `total_assessed_cents` minus the deposit. The remainder of the deposit is refunded to the wallet: `deposit_refund_cents` is the greater of zero and the deposit minus `total_assessed_cents`. The refunded portion lands in the account's `wallet_credit_cents` and the overflow becomes part of the account's outstanding balance.

### 3.10. Coverage Claims for Theft and Damage

A holding `Subscriber` or `FleetManager` files a **coverage claim** against a `rental_id`, declaring a `claim_type` of `THEFT` (the bike was stolen) or `DAMAGE` (accidental damage beyond normal wear), an `incident_clock` recording when the incident is reported to have occurred, and a `claimed_amount_cents` that must be non-negative. A claim opens with `status` `FILED`; the status set is `FILED`, `UNDER_REVIEW`, `APPROVED`, `DENIED`, and `CLOSED`, with `CLOSED` terminal, and its `approved_payout_cents` starts at 0. Claims can be listed and filtered by `rental_id` and `status`.

Claim handling is an `OpsAdmin` workflow. Reviewing moves a `FILED` claim to `UNDER_REVIEW`. From `UNDER_REVIEW` the claim forks: it may be approved or denied. Each of these transitions invoked from a source state outside the one(s) it requires — review from a non-`FILED` claim, approve or deny from a non-`UNDER_REVIEW` claim, or close from a claim that is neither `APPROVED` nor `DENIED` — is rejected with `ERR_INVALID_STATE` (HTTP 409). Approving requires the claim to be `UNDER_REVIEW` and supplies an `approved_payout_cents` (a required non-negative integer; the well-formedness check on this field is evaluated after the `UNDER_REVIEW` state check). The payout is bounded by a **coverage cap**: the cap is the model's `purchase_price_cents` multiplied by a percentage that depends on the claim type — 100% for a `THEFT` claim and 40% for a `DAMAGE` claim — rounded half up; the maximum permitted payout is the smaller of the claim's `claimed_amount_cents` and that cap. If the requested `approved_payout_cents` exceeds the claim's `claimed_amount_cents` or exceeds the coverage cap, the approval is rejected with `ERR_PAYOUT_EXCEEDS_CAP` (HTTP 422). On a valid approval the claim's `approved_payout_cents` is recorded and its `status` becomes `APPROVED`. The two branches diverge by claim type on payout side effects: for a `DAMAGE` claim, the approved payout is credited to the account's `wallet_credit_cents` only, with no rental cascade; for a `THEFT` claim whose rental is still `BILLING_ACTIVE`, the approval triggers the write-off cascade described next. A `THEFT` approval whose rental is not in `BILLING_ACTIVE` runs no cascade and behaves exactly like the `DAMAGE` branch — the approved payout is credited to the account's `wallet_credit_cents` only. Denying a claim, by contrast, requires only that it be `UNDER_REVIEW`, sets its `approved_payout_cents` to 0, moves it to `DENIED`, and produces no payout and no rental cascade. Both `APPROVED` and `DENIED` claims are later closed to `CLOSED`.

The **theft write-off cascade** fires when a `THEFT` claim is approved while the rental's `billing_status` is `BILLING_ACTIVE`: the rental's `billing_status` moves to `WRITTEN_OFF`, its `lifecycle_status` is set to `CANCELLED`, the bike transitions from `OUT` to `RETIRED` with its `current_rental_id` cleared, the model's `available_count` and `total_bikes` are recomputed, and the `approved_payout_cents` is credited to the account's `wallet_credit_cents`; the rental's `version` increments. This is why a rental against a bike that has already been written off cannot be inspected, returned, or have a non-critical action filed against it — those operations are rejected with `ERR_BIKE_RETIRED`.

### 3.11. Fleet Invoicing

A `FleetManager` (on its own fleet account) or an `OpsAdmin` generates a **fleet invoice** for an account, supplying the `cycle_index` it covers (a sequential, zero-based billing-cycle index that is a required non-negative integer; a missing or negative `cycle_index` is rejected with `ERR_INVALID_REQUEST`). An invoice may only be generated for an account whose `account_type` is `FLEET`; a request against a non-fleet account is rejected with `ERR_NOT_FLEET_ACCOUNT` (HTTP 409), a check evaluated after the `cycle_index` well-formedness check. A new invoice opens with `status` `ISSUED`; an invoice's `status` is one of `ISSUED` or `PAID`.

The invoice aggregates the account's qualifying rentals. The lines are exactly those `RentalAgreement` rows for the account whose `rental_mode` is `MONTHLY` and whose `lifecycle_status` is either `ACTIVE` or `IN_SERVICE`, taken in ascending `created_at` order for a deterministic line ordering; rentals that are `DELIVERED`, `RESERVED`, or in any terminal state are excluded. The `line_count` is the number of such lines. Each line's charge is the line's model `monthly_fee_cents` plus that model's class surcharge, and `gross_amount_cents` is the sum of those per-line charges before any discount. A volume discount applies when the line count is at least 5: in that case each line's charge is multiplied by (1 − 0.10), rounded half up per line, and `amount_due_cents` is the sum of those discounted per-line amounts (discount applied per line, then rounded half up, then summed — round-then-sum, not sum-then-round). When the line count is below 5, no discount applies and `amount_due_cents` equals `gross_amount_cents`. The `discount_cents` is `gross_amount_cents` minus `amount_due_cents`.

A fleet invoice can be marked paid by a `FleetManager` or `OpsAdmin`, which sets its `status` to `PAID` and recomputes the account's `outstanding_balance_cents`; an invoice that is not in `ISSUED` status is rejected with `ERR_INVALID_STATE` (HTTP 409). Marking an invoice `PAID` only removes its `amount_due_cents` from the `ISSUED`-invoice portion of `outstanding_balance_cents`; settlement overflow billed at return is tracked separately on the account and is not cleared by invoice payment. Invoices can be fetched individually and listed for an account, filtered by `status`.

### 3.12. Administrative Clock Control

For deterministic, time-dependent testing, an `OpsAdmin` can set the logical clock to a supplied instant via the `to_iso8601` field. This capability advances the server's logical clock so that all subsequent reads of the current logical clock return the supplied value, governing every cycle anchor, billing window, late-fee computation, delivery-window check, buyout-expiry check, and incident timestamp from that point forward, as described in Section 2.4.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return HTTP 201 Created. Operations that transition or otherwise modify an existing resource return HTTP 200 OK. Endpoints not listed as public require the `X-User-ID` and `X-User-Role` headers.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/bike-models` | Create a bike model (catalog entry) | OpsAdmin |
| GET | `/bike-models/{id}` | Fetch a model with computed counts | OpsAdmin, Subscriber, FleetManager, FieldTech |
| GET | `/bike-models` | List models (paginated) | OpsAdmin, Subscriber, FleetManager, FieldTech |
| GET | `/bike-models/{id}/bikes` | List physical bikes for a model | OpsAdmin, FieldTech |
| POST | `/bikes` | Add a physical bike to a model's fleet | OpsAdmin |
| GET | `/bikes/{id}` | Fetch a bike | OpsAdmin, FieldTech, Subscriber, FleetManager |
| GET | `/bikes` | List/filter physical bikes | OpsAdmin, FieldTech, Subscriber, FleetManager |
| POST | `/bikes/{id}/retire` | Retire an AVAILABLE bike | OpsAdmin |
| POST | `/accounts` | Open a SUBSCRIBER or FLEET account (public) | Anonymous, OpsAdmin |
| GET | `/accounts/{id}` | Fetch an account with computed fields | OpsAdmin, Subscriber, FleetManager |
| POST | `/accounts/{id}/suspend` | Suspend an account | OpsAdmin |
| GET | `/accounts/{id}/rentals` | List rentals for an account | OpsAdmin, Subscriber, FleetManager |
| POST | `/rentals` | Reserve a bike from a model pool (OCC) | Subscriber, FleetManager |
| GET | `/rentals/{id}` | Fetch a rental | OpsAdmin, Subscriber, FleetManager, FieldTech |
| GET | `/rentals` | List/filter rental agreements | OpsAdmin, Subscriber, FleetManager, FieldTech |
| POST | `/rentals/{id}/activate` | Activate a DELIVERED rental; begin billing | Subscriber, FleetManager |
| POST | `/rentals/{id}/request-return` | Request return; schedule PICKUP delivery | Subscriber, FleetManager |
| POST | `/rentals/{id}/inspect` | File return inspection; settle; release bike | FieldTech |
| POST | `/rentals/{id}/cancel` | Cancel a RESERVED rental before delivery | Subscriber, FleetManager |
| POST | `/rentals/{id}/advance-cycle` | Advance a MONTHLY rental one completed cycle | OpsAdmin |
| POST | `/deliveries` | Schedule a delivery (INITIAL/SWAP/PICKUP) | OpsAdmin, FieldTech |
| GET | `/deliveries/{id}` | Fetch a delivery | OpsAdmin, FieldTech, Subscriber, FleetManager |
| GET | `/deliveries` | List/filter deliveries | OpsAdmin, FieldTech, Subscriber, FleetManager |
| POST | `/deliveries/{id}/complete` | Complete a delivery; advance rental/swap bikes | FieldTech |
| POST | `/service-tickets` | Open a maintenance ticket | Subscriber, FleetManager, FieldTech |
| GET | `/service-tickets/{id}` | Fetch a service ticket | OpsAdmin, FieldTech, Subscriber, FleetManager |
| GET | `/service-tickets` | List/filter service tickets | OpsAdmin, FieldTech, Subscriber, FleetManager |
| POST | `/service-tickets/{id}/start` | Begin work (OPEN/REOPENED to IN_PROGRESS) | FieldTech |
| POST | `/service-tickets/{id}/resolve` | Resolve a ticket | FieldTech |
| POST | `/service-tickets/{id}/reopen` | Reopen a RESOLVED ticket | Subscriber, FleetManager |
| POST | `/service-tickets/{id}/close` | Close a ticket; may auto-return rental | FieldTech |
| GET | `/inspection-reports/{id}` | Fetch an inspection report | OpsAdmin, FieldTech, Subscriber, FleetManager |
| GET | `/inspection-reports` | List/filter inspection reports | OpsAdmin, FieldTech, Subscriber, FleetManager |
| POST | `/coverage-claims` | File a theft/damage claim | Subscriber, FleetManager |
| GET | `/coverage-claims/{id}` | Fetch a coverage claim | OpsAdmin, Subscriber, FleetManager |
| GET | `/coverage-claims` | List/filter coverage claims | OpsAdmin, Subscriber, FleetManager |
| POST | `/coverage-claims/{id}/review` | Move a FILED claim to UNDER_REVIEW | OpsAdmin |
| POST | `/coverage-claims/{id}/approve` | Approve a claim with a bounded payout | OpsAdmin |
| POST | `/coverage-claims/{id}/deny` | Deny a claim (no payout) | OpsAdmin |
| POST | `/coverage-claims/{id}/close` | Close an APPROVED or DENIED claim | OpsAdmin |
| POST | `/rentals/{id}/buyout-offers` | Quote a buyout for a rental | Subscriber, FleetManager |
| GET | `/buyout-offers/{id}` | Fetch a buyout offer | OpsAdmin, Subscriber, FleetManager |
| GET | `/rentals/{id}/buyout-offers` | List buyout offers for a rental | OpsAdmin, Subscriber, FleetManager |
| POST | `/buyout-offers/{id}/accept` | Accept a QUOTED, non-expired offer | Subscriber, FleetManager |
| POST | `/accounts/{id}/fleet-invoices` | Generate a fleet invoice (volume discount) | OpsAdmin, FleetManager |
| GET | `/fleet-invoices/{id}` | Fetch a fleet invoice | OpsAdmin, FleetManager |
| GET | `/accounts/{id}/fleet-invoices` | List fleet invoices for an account | OpsAdmin, FleetManager |
| POST | `/fleet-invoices/{id}/pay` | Mark a fleet invoice PAID | OpsAdmin, FleetManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (public) | OpsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_MODEL_VERSION` | 412 Precondition Failed |
| `ERR_BIKE_RETIRED` | 409 Conflict |
| `ERR_DELIVERY_TYPE_MISMATCH` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_BIKE_ALREADY_SERVICING` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_PAYOUT_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_RENTAL_CAP_EXCEEDED` | 409 Conflict |
| `ERR_NO_BIKES_AVAILABLE` | 409 Conflict |
| `ERR_ACCOUNT_SUSPENDED` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_NOT_FLEET_ACCOUNT` | 409 Conflict |
