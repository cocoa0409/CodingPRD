# Returns Concierge API — Product Requirements Document

## 1. Introduction

Returning an online purchase is the moment where retail goodwill is either kept or lost. Shoppers want to hand a parcel to a locker, a counter clerk, or a courier at their door without printing anything, and they want to know — before they leave the house — roughly how much money is coming back. Merchants, meanwhile, want the reverse logistics to be consolidated, auditable, and billed on a predictable subscription rather than a per-incident negotiation. This document specifies the Returns Concierge API, a platform in the style of Happy Returns that operates a network of staffed counters and self-serve lockers, routes consolidated totes of returned goods through carrier partners, and settles both shopper refunds and merchant invoices from a single ledger-driven core.

The API covers the full reverse-logistics loop: shopper registration and return initiation with a provisional refund estimate; label issuance with QR-based boxless drop-off; locker slot reservation with time-boxed holds; home pickup scheduling against courier zone capacity; carrier routing and tote consolidation with manifest accounting; inspection with per-line deduction tiers; final refund settlement backed by an append-only ledger; exception handling with segregation of duties; and subscription-based merchant billing with volume discounts, overage fees, and a dispute cycle. Time is a first-class input — the platform runs on a logical clock that operators can set explicitly, and every expiry, window, and billing period is evaluated against that clock. All resources are mounted under the `/v1` URL prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that apply uniformly across every resource and workflow in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `Shopper`, `MerchantAdmin`, `LocationOperator`, `SupportAgent`, `CarrierDispatcher`, and `PlatformAdmin`.

Three of these roles are entity-backed. When `X-User-Role` is `Shopper`, `X-User-ID` is the `id` of the acting `Shopper`; ownership checks on any resource that references a `Shopper` compare the resource's `shopper_id` to `X-User-ID`. When `X-User-Role` is `MerchantAdmin`, `X-User-ID` is the `id` of the acting `MerchantAccount`; ownership checks on merchant-scoped resources such as billing cycles compare the resource's `merchant_id` to `X-User-ID`. When `X-User-Role` is `LocationOperator`, `X-User-ID` is the `id` of the `DropoffLocation` the operator runs; ownership checks on location-scoped operations compare the relevant location identifier to `X-User-ID`. An entity-backed caller acting on a resource it does not own is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

The remaining three roles carry opaque identities. When `X-User-Role` is `SupportAgent`, `CarrierDispatcher`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `sealed_by_user_id` on a `ConsolidationTote`, `closed_by_user_id` or `settled_by_user_id` on a `BillingCycle`, `opened_by_user_id` or `resolved_by_user_id` on an `ExceptionCase`, or `actor_user_id` on a `RefundLedgerEntry` — but it never compares the value to any entity's `id` for ownership purposes.

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
- A request whose path matches no declared route is refused with `ERR_NOT_FOUND` (HTTP 404) in this same envelope; a request whose path matches a route but whose HTTP method is not declared for it is refused with `ERR_INVALID_REQUEST` at HTTP 405.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter controls how many items are skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties on `created_at` broken by creation (insertion) order — never by `id`.

Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): starts at 1 on creation and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control as described in §2.7.

The `RefundLedgerEntry` resource is the deliberate exception: it is an immutable, append-only event log and carries only `id` and `created_at`. Both `updated_at` and `version` are absent on ledger entries — an entry, once written, never changes.

### 2.5. The Logical Clock and Scheduled Maintenance

All time-dependent rules in the system — reservation holds, label expiry, pickup windows, billing periods — are evaluated against a **logical clock**, never against wall-clock time. Before any operator sets it, the logical clock starts at exactly `2026-05-01T00:00:00Z`; the server must not fall back to wall-clock time under any circumstance. A `PlatformAdmin` may set the logical clock to exactly a supplied instant by submitting `to_iso8601` through an admin-only test-driving capability — no monotonicity constraint is enforced; the response reports the new `current_utc`.

A second admin-only capability runs the **expiry sweep** at the current logical instant. The sweep processes candidates strictly in `created_at` ascending order, with ties broken by `created_at` only — never by `id`. It expires labels whose ten-day life has elapsed and then expires reservations whose 48-hour hold has elapsed, firing the cascade links described in §3.4 and §3.5 (a label expiry drags its bound reservation down, and a reservation expiry frees its locker slot and refreshes location counts). The sweep response reports `expired_label_count` and `expired_reservation_count`.

### 2.6. Money, Precision, and Rounding

All monetary values are integer counts of cents. No fractional cents exist anywhere in the system.

Rounding is pinned to a single rule with a single method: whenever a computation produces a non-integer cent value — which happens when a percentage is applied — the result is rounded **half-up** to the nearest integer cent. Two rounding disciplines must be observed exactly. First, per-line rounding: each return item's `deduction_cents` is rounded half-up individually **before** any summation, and the order-level refund is then the sum of already-rounded lines. Summing unrounded line values and rounding the total is forbidden, because the two orders of operation diverge by cents on multi-line orders. Second, in merchant billing, only the volume discount is rounded (half-up); every other component is an exact integer sum or product. Percentages and timestamps used as inputs keep their declared precision; timestamps throughout the system use second-precision UTC unless a field explicitly carries three fractional digits.

### 2.7. Optimistic Concurrency Control

Four write operations require the caller to present the version it last observed of the parent resource being mutated. In each case the check is the same: if the presented value does not equal the parent resource's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from overwriting state it has not observed. Endpoints not named below take no version field at all.

- Issuing a label for a return order requires `expected_return_order_version` matching the order's current `version`. Because issuing a label legitimately supersedes the prior active one, a writer holding a stale view of the order — for example, unaware another label was just issued — must be refused.
- Changing an order's fulfilment method likewise requires `expected_return_order_version` matching the order's current `version`, because the change voids the active label and releases the reservation whose existence the stale client could not have seen.
- Adding a member order to a consolidation tote, and the symmetric removal, both require `expected_tote_version` matching the tote's current `version`: capacity decisions on unit and weight headroom were computed from a manifest that may since have changed.
- Resolving an exception case requires `expected_exception_case_version` matching the case's current `version`: an appeal, a shopper response, or a prior resolution may have altered the case state on which the resolver based the decision.

A successful mutation through any of these endpoints increments the parent resource's `version` by one, as with every other mutation in the system.

### 2.8. Order of Validation

When several rules could reject the same request, the server evaluates them in a fixed priority order so that the surfaced error is deterministic. The order, from first to last, is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is a declared role, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the caller's role appears in the endpoint's authorized role list, else `ERR_UNAUTHORIZED`.
3. **Ownership** — entity-backed callers act only on their own resources: a `Shopper` only on their own `shopper_id` resources, a `MerchantAdmin` only on their own merchant's cycles and orders, a `LocationOperator` only at their own location, else `ERR_OWNERSHIP_MISMATCH`.
4. **Existence and shape** — path- and body-referenced identifiers exist, validated left to right, and enum fields carry a declared member, else `ERR_NOT_FOUND`, `ERR_ENUM_INVALID`, or `ERR_INVALID_REQUEST`.
5. **Optimistic concurrency** — where §2.7 applies, the expected parent version matches, else `ERR_STALE_VERSION`.
6. **State legality** — the target resource is in a valid from-state for the requested transition. When the resource the operation acts on already sits in a terminal status of its state machine and that status is not a legal from-state for the requested operation, the refusal is `ERR_ALREADY_TERMINAL` — terminal resources reject everything — and this check is evaluated before the specific from-state rule; a non-terminal but illegal from-state is refused with `ERR_INVALID_STATE`. The resource acted on is the one addressed by the path or, for operations scoped to a parent aggregate, that parent — for example, the return order named by a reservation, pickup, exception, or tote-add request, or the route named at tote creation; state checks on resources that are merely referenced follow each endpoint's own narrative. (Two exceptions: re-settlement of a billing cycle names `DISPUTED` as its only legal from-state and refuses anything else, including a terminal `SETTLED` cycle, with `ERR_INVALID_STATE`; and label actions on a non-`ISSUED` label carry their own dedicated `ERR_LABEL_NOT_ACTIVE` per §3.4.)
7. **Cross-entity referential integrity** — the merchant is `ACTIVE` at order creation, the shopper is not `RESTRICTED`, an `OPEN` billing cycle covers the current instant, a tote's `location_id` equals its route's `origin_location_id`, and references never cross merchant boundaries — surfacing as `ERR_MERCHANT_SUSPENDED`, `ERR_SHOPPER_RESTRICTED`, `ERR_BILLING_CYCLE_NOT_OPEN`, `ERR_ROUTE_ORIGIN_MISMATCH`, or `ERR_CROSS_MERCHANT_REFERENCE`.
8. **Dimension and oversize safety** — locker flows reject any item whose `longest_side_cm` exceeds 150, and any oversize item requires the plan's `oversize_enabled`, else `ERR_DIM_EXCEEDS_XL` or `ERR_OVERSIZE_NOT_SUPPORTED`.
9. **Feature gates, pairing, and paired-duty constraints** — plan feature flags, slot size-class fit, label/method compatibility, segregation-of-duties pairs, appeal limits, and route weight capacity, surfacing as `ERR_FEATURE_NOT_INCLUDED`, `ERR_SLOT_SIZE_TOO_SMALL`, `ERR_LABEL_METHOD_MISMATCH`, `ERR_SOD_RESOLVER_EQUALS_OPENER`, `ERR_SOD_SETTLER_EQUALS_CLOSER`, `ERR_APPEAL_LIMIT_REACHED`, `ERR_ROUTE_WEIGHT_EXCEEDED`, or `ERR_PLAN_IN_USE`.
10. **Clock-relative rules** — a pickup window must not lie in the past, a reservation must be unexpired at consume, a label must be unexpired at consume or confirm, and a courier start must not precede one hour before the window, else `ERR_PICKUP_WINDOW_PAST`, `ERR_RESERVATION_EXPIRED`, `ERR_LABEL_EXPIRED`, or `ERR_PICKUP_TOO_EARLY`.
11. **Capacity** — slot live-hold exclusivity, zone window aggregate capacity, tote unit and weight headroom, the tote's `FILLING` requirement for membership changes, and the location's `OPERATIONAL` requirement, surfacing as `ERR_SLOT_UNAVAILABLE`, `ERR_PICKUP_WINDOW_FULL`, `ERR_TOTE_CAPACITY_EXCEEDED`, `ERR_TOTE_WEIGHT_EXCEEDED`, `ERR_TOTE_NOT_FILLING`, `ERR_LOCATION_NOT_OPERATIONAL`, `ERR_ORDER_ALREADY_IN_TOTE`, or `ERR_ORDER_NOT_AT_LOCATION`.
12. **Fiscal and mutation guards** — the overage hard cap at order creation, billing-cycle state gates, ledger append legality, duplicate-open-exception prevention, already-inspected items, non-empty totes for sealing, route cancellation without live totes, and location decommission without busy slots — surfacing as `ERR_OVERAGE_LIMIT_EXCEEDED`, `ERR_REFUND_FINAL_POSTED`, `ERR_ADJUSTMENT_EXCEEDS_PAYABLE`, `ERR_CORRECTION_REQUIRES_ADMIN`, `ERR_EXCEPTION_OPEN_EXISTS`, `ERR_ITEM_ALREADY_INSPECTED`, `ERR_TOTE_EMPTY`, `ERR_ROUTE_HAS_LIVE_TOTE`, or `ERR_LOCATION_BUSY`.

Because this order is fixed, an early failure always masks later ones: for example, a stale version surfaces as `ERR_STALE_VERSION` rather than any business error that would also have applied.

### 2.9. Nested Path Resolution

Requests that target nested resources — a merchant's billing cycles, a location's locker slots, a tote's member orders — resolve path identifiers sequentially from left to right. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) for the first identifier in the path that does not correspond to an existing resource, before any deeper identifier is examined and before any business rule runs. Existence validation is part of priority 4 in §2.8, so a missing parent yields a 404 even when a later body field would also have failed.

### 2.10. Cross-Aggregate Consistency and Cascades

Although the entity graph is flat — peer resources joined by foreign-key references rather than nested ownership — state changes routinely propagate across aggregates. Cancelling an order voids its active label, releases its held reservation, and empties the reserved slot. Dispatching a tote advances every member order from `DROPPED_OFF` to `IN_TRANSIT`. Resolving an exception can reroute an order, re-mark item conditions, increment a shopper's fraud strikes, and refresh a billing cycle's accrued refunds, all within one request. The governing principle is that each cascade is atomic with its trigger: a reader never observes a partially applied cascade, and every mutation in the chain refreshes the affected resource's `updated_at` and increments its `version`. Cycles are intentional features of this design — an order may loop between inspection and exception review, a tote may be sealed and unsealed, a billing cycle may be settled, disputed, and re-settled — and the state machines in §3 enumerate every such loop explicitly.

## 3. Business Logic & Workflows

### 3.1. Subscription Plans and Merchant Onboarding

The commercial relationship starts with a **SubscriptionPlan**, which a `PlatformAdmin` authors with a `tier` — one of `STARTER`, `GROWTH`, `SCALE`, or `CUSTOM` — together with the commercial terms: `monthly_fee_cents` as the base fee per billing cycle, `included_returns` as the number of returns fulfilled per cycle before overage pricing applies, and `overage_fee_cents` as the per-return fee charged beyond that inclusion. Three feature flags shape what merchants on the plan may do: `pickup_enabled` permits the `HOME_PICKUP` fulfilment method, `boxless_enabled` permits QR-code boxless drop-off, and `oversize_enabled` permits items whose `longest_side_cm` exceeds 150 through non-locker methods. Two pricing flags complete the picture: `free_returns` waives the `NEW` and `LIGHT_USE` condition deduction at final settlement, and `oversize_surcharge_cents` together with `pickup_fee_cents` define the per-order surcharges billed to the merchant. All monetary plan fields are non-negative integer cents, and `included_returns` is likewise a non-negative integer. A plan is born in `DRAFT` status; a `PlatformAdmin` publishes it, moving `status` from `DRAFT` to `PUBLISHED`, and later retires it from `PUBLISHED` to the terminal `RETIRED`. Retirement is refused with `ERR_PLAN_IN_USE` while any merchant account in `ACTIVE` or `SUSPENDED` status still references the plan.

A **MerchantAccount** is created by a `PlatformAdmin` supplying the merchant's `legal_name` and the `plan_id` of a plan that must be `PUBLISHED` at that moment — a plan in any other status is refused with `ERR_INVALID_STATE`. The account starts `ACTIVE` with a `ledger_balance_cents` of zero; that balance is a running total of the `total_cents` of the merchant's `SETTLED` billing cycles, as §3.2 describes. The merchant roster can be listed with optional `plan_id` and `status` filters. From `ACTIVE`, a `PlatformAdmin` may suspend the account (`ACTIVE` → `SUSPENDED`), which immediately blocks new return order creation for the merchant with `ERR_MERCHANT_SUSPENDED`, and may reactivate it (`SUSPENDED` → `ACTIVE`). Closing the account — from either `ACTIVE` or `SUSPENDED` into the terminal `CLOSED` — requires that no billing cycle of the merchant is in `OPEN` or `CLOSING` status, and is otherwise refused with `ERR_BILLING_CYCLE_OPEN`. Closure is deliberately sweeping: every in-flight (non-terminal) return order of the merchant moves to `CANCELLED`, their active labels move to `VOIDED`, their `HELD` reservations move to `RELEASED`, and the slots those reservations held return to `EMPTY`.

### 3.2. Billing Cycles and Merchant Invoicing

Invoicing revolves around the **BillingCycle**. A `PlatformAdmin` opens a cycle for a merchant by supplying `period_start` (inclusive) and `period_end` (exclusive), both ISO 8601 UTC instants, with `period_end` strictly after `period_start` — a window failing that ordering is refused with `ERR_INVALID_REQUEST`. The new window must not overlap any non-terminal cycle of the same merchant under half-open interval arithmetic — two windows overlap when each starts before the other ends — and a violation is rejected with `ERR_BILLING_PERIOD_OVERLAP`. The cycle is created in `OPEN` status, and a merchant's cycles can be listed with an optional `status` filter.

Two counters track the live shape of an `OPEN` cycle. `fulfilled_count` is the number of the merchant's return orders that reached `REFUND_POSTED` or `REJECTED_CLOSED` with a `resolved_at` falling inside the half-open window from `period_start` to `period_end`. `in_flight_count` counts the merchant's orders created within the window whose status is still non-terminal. Alongside them, `refunds_accrued_cents` accumulates the sum of each resolved order's latest `FINAL` ledger amount, and it is refreshed every time an order covered by the cycle posts its refund.

The charge computation exists in two pinned variants. A **provisional preview**, available to a `PlatformAdmin` or the merchant's own `MerchantAdmin` while the cycle is `OPEN`, is forward-looking: it counts both fulfilled and in-flight orders toward overage. A **final close** counts fulfilled orders only, so identical data with any in-flight orders yields a different total between the two variants. Both variants evaluate in the same fixed order. The base component `base_cents` is the merchant's current plan's `monthly_fee_cents`, snapshotted at close. The overage component `overage_count` is the amount by which the counted returns exceed the plan's `included_returns`, floored at zero, and `overage_fee_cents` is that count multiplied by the plan's `overage_fee_cents`. The surcharge component `surcharge_cents` always uses actual fulfilled orders in both variants: for each fulfilled order, the plan's `oversize_surcharge_cents` is added when the order `has_oversize_item`, and the plan's `pickup_fee_cents` is added when the order's `method` is `HOME_PICKUP`. The gross charge `gross_cents` is the sum of base, overage fee, and surcharge. The volume discount is tiered on the gross: a gross of at least 500,000 cents earns ten percent, a gross of at least 200,000 cents but less than 500,000 earns five percent, and anything below earns nothing; `discount_cents` is the gross multiplied by the applicable percentage, rounded half-up to integer cents. The invoice total `total_cents` is the gross minus the discount. The preview response exposes this arithmetic field by field — `variant` (fixed to the string `provisional_preview`), `fulfilled_count`, `in_flight_count`, `base_cents`, `overage_count`, `overage_fee_cents`, `surcharge_cents`, `gross_cents`, `discount_cents`, and `total_cents`.

Closing, settling, and disputing a cycle enforce segregation of duties. A `PlatformAdmin` closes an `OPEN` cycle, moving it to `CLOSING`; at that moment all of the charge fields above are recomputed using the final variant, and the caller's identity is recorded in `closed_by_user_id`. Settling moves the cycle from `CLOSING` to the terminal `SETTLED` and must be performed by a *different* `PlatformAdmin` than the one who closed it — a settler whose identity equals `closed_by_user_id` is refused with `ERR_SOD_SETTLER_EQUALS_CLOSER`. Settlement records `settled_by_user_id` and adds the cycle's `total_cents` to the merchant's `ledger_balance_cents`. The merchant's own `MerchantAdmin` may then dispute the settled charge, moving `SETTLED` → `DISPUTED`; the caller must be the merchant itself, so a caller whose identity differs from the cycle's `merchant_id` is refused with `ERR_OWNERSHIP_MISMATCH`. A dispute parks the charge: the merchant's `ledger_balance_cents` is reduced by the cycle's `total_cents` while the dispute stands. Re-settlement moves `DISPUTED` back to `SETTLED`, again requiring the settler to differ from the original closer under the same `ERR_SOD_SETTLER_EQUALS_CLOSER` rule, and re-adds the `total_cents` to the merchant's balance.

### 3.3. Shoppers and Return Order Intake

A **Shopper** registers — self-service, or via a `PlatformAdmin` — with an `email` that must be unique across shoppers (a duplicate is refused with `ERR_INVALID_REQUEST`), a `full_name`, and a `postal_code`. The account starts `ACTIVE` with `fraud_strikes` at zero. Fraud strikes are the platform's trust signal: each time a `LABEL_FRAUD` exception resolves `APPROVED` against the shopper, their `fraud_strikes` increments by one, and the moment the count reaches two the shopper's `status` automatically becomes `RESTRICTED`. Exactly one strike leaves the shopper `ACTIVE`; the second strike restricts. A `RESTRICTED` shopper cannot create new return orders — attempts are refused with `ERR_SHOPPER_RESTRICTED` — until a `SupportAgent` or `PlatformAdmin` lifts the restriction, moving `RESTRICTED` → `ACTIVE` and resetting `fraud_strikes` to zero. A shopper's own order history is listable with an optional `status` filter.

The **ReturnOrder** is the spine of the whole product. A `Shopper` creates one for their own account by supplying `shopper_id` and `merchant_id`, choosing a fulfilment `method` of `LOCKER_QR`, `COUNTER_DROP`, or `HOME_PICKUP`, optionally setting `boxless` (defaulting to false when omitted), and embedding an inline `items` array describing what is being sent back — the array may be empty, in which case the order is created normally but can never be issued a label (§3.4). Each line of `items` declares a `sku`, a `quantity` of at least one, a `unit_price_cents` of zero or more, the shopper-declared `declared_condition` of `NEW`, `LIGHT_USE`, `DAMAGED`, `DEFECTIVE`, or `WRONG_ITEM`, and the package dimensions `longest_side_cm` (any number greater than zero) and per-unit `weight_grams` (an integer greater than zero). Each line becomes a `ReturnItem` whose `return_order_id` is bound to the creating order and whose lifecycle starts at `PENDING`.

Creation is guarded by a stack of checks, applied in the priority order of §2.8. The caller must own the referenced shopper; the merchant must be `ACTIVE`, else `ERR_MERCHANT_SUSPENDED`; the shopper must not be `RESTRICTED`; an `OPEN` billing cycle of the merchant must cover the current logical instant, else `ERR_BILLING_CYCLE_NOT_OPEN`. Method eligibility is plan-gated: `HOME_PICKUP` requires the plan's `pickup_enabled`, and boxless flows require `boxless_enabled`, with violations rejected as `ERR_FEATURE_NOT_INCLUDED`. Choosing `LOCKER_QR` forces `boxless` to true and forbids any item whose `longest_side_cm` exceeds 150 — such an item presented for a locker flow is rejected with `ERR_DIM_EXCEEDS_XL`. Regardless of method, any oversize item requires the plan's `oversize_enabled`, else `ERR_OVERSIZE_NOT_SUPPORTED`.

On top of those checks stands the **overage guard**, the platform's hard cap on subscription abuse. The system projects the merchant's load as the current `OPEN` cycle's `fulfilled_count` plus its `in_flight_count` plus one for the order being created. If that projection strictly exceeds twice the plan's `included_returns`, creation is rejected with `ERR_OVERAGE_LIMIT_EXCEEDED`; a projection exactly equal to twice the inclusion is allowed.

A created order lands in `INITIATED` status. At that moment the system computes the shopper-facing provisional refund and stores it in `refund_estimate_cents`, appending a matching `ESTIMATE` entry to the order's refund ledger with `actor_user_id` set to `system`. The provisional variant is deliberately pessimistic: each line's gross is its `unit_price_cents` multiplied by its `quantity`; a deduction percentage is taken from the *declared* condition — zero for `NEW`, ten percent for `LIGHT_USE`, fifty percent for `DAMAGED`, zero for `DEFECTIVE`, and one hundred percent for `WRONG_ITEM`; and the plan's `free_returns` waiver is *not* applied. The line deduction is rounded half-up per line, and the estimate is the sum over lines of gross minus the rounded deduction. Because the waiver is ignored at this stage, the estimate is less than or equal to the final settlement whenever the plan waives `NEW` and `LIGHT_USE`. Three derived counters complete the order's physical profile: `total_units` sums the item quantities, `total_weight_grams` sums each item's `weight_grams` multiplied by its quantity, and `has_oversize_item` is true when any item's `longest_side_cm` exceeds 150. Two physical anchors start empty: `tote_id` stays null until the order joins a consolidation tote and is cleared if it leaves one, and `dropoff_location_id` stays null until the order is dropped off.

While still `INITIATED` or `LABEL_ISSUED`, the shopper (or a `SupportAgent`) may cancel the order, moving it to the terminal `CANCELLED`; from `LABEL_ISSUED` the cancellation also voids the active label, releases the held reservation, and returns the slot to `EMPTY`. Alternatively the shopper may change the fulfilment `method` — and optionally `boxless` — through the method-change operation, which carries `expected_return_order_version` per §2.7 and is rejected with `ERR_STALE_VERSION` when the presented version no longer matches the order's current `version`. When `boxless` is omitted from the request the order's current value is kept, and choosing `LOCKER_QR` forces it to true exactly as at creation. A method change applies the same dimension and feature gates as creation, voids any active label, releases any held reservation and empties its slot, returns the order to `INITIATED`, and increments the order's `version` by one.

### 3.4. Labels and the Drop-Off Moment

A **Label** is how an order physically travels. Its `label_type` is either `QR_CODE` or `CARRIER_LABEL`, and compatibility is strict: `LOCKER_QR` orders and any boxless order may only carry `QR_CODE` labels, so a mismatched request is rejected with `ERR_LABEL_METHOD_MISMATCH`. The shopper issues a label against an order by naming the `label_type` and presenting `expected_return_order_version`; a version mismatch is rejected with `ERR_STALE_VERSION`. Issuance requires the order to carry at least one return item — an item-less order is refused with `ERR_INVALID_STATE`. The first label moves the order `INITIATED` → `LABEL_ISSUED`; issuing while another label is still active **supersedes** the old one — the prior label moves from `ISSUED` to `SUPERSEDED` and the new label's `supersedes_label_id` points back at it, while on a first label that field stays null. Either way the new label starts `ISSUED` with `issued_at` stamped from the logical clock and `expires_at` set exactly ten days later. Labels are listable with optional `return_order_id`, `supersedes_label_id`, and `status` filters; a `Shopper` listing labels without a `return_order_id` filter sees only labels on their own orders, and filtering by another shopper's order is refused with `ERR_OWNERSHIP_MISMATCH`.

Labels decay. The sweep of §2.5 turns any `ISSUED` label whose `expires_at` is at or before the current instant into `EXPIRED` — at exactly `expires_at` the label is expired — and as a cascade the reservation still bound to that label flips from `HELD` to `EXPIRED`, freeing its slot; the order's own status is left unchanged by label expiry. A shopper or support agent may instead void an `ISSUED` label deliberately, moving it to the terminal `VOIDED`; any label action on a non-`ISSUED` label is refused with `ERR_LABEL_NOT_ACTIVE`, and consuming or confirming against an expired label is refused with `ERR_LABEL_EXPIRED`. Voiding cascades: a bound `HELD` reservation moves to `RELEASED`, its slot returns to `EMPTY`, and when the `VOIDED` label was the order's last active one the order falls back from `LABEL_ISSUED` to `INITIATED` — a deliberate cyclic revert, since the order can acquire a fresh label afterwards.

The drop-off itself has two shapes. At a **counter**, the location's operator confirms the hand-off by supplying the `location_id`; the order must use the `COUNTER_DROP` method — an order with any other method is refused with `ERR_INVALID_STATE` — the location must be `OPERATIONAL`, and the operator must own that location. Confirmation moves the order `LABEL_ISSUED` → `DROPPED_OFF`, stamps `dropoff_location_id` with the location, and consumes the active label (`ISSUED` → `CONSUMED`). At a **locker**, the deposit is performed through the reservation consume described in §3.5, which achieves the same `LABEL_ISSUED` → `DROPPED_OFF` transition through its own cascade. Whichever path was taken, an order later re-entering the network through the home-pickup reroute arrives in `IN_TRANSIT`, and a platform admin or location operator can receive it directly into `INSPECTING`.

### 3.5. Locker Network: Locations, Slots, and Reservations

The physical network is built from **DropoffLocation** resources. A `PlatformAdmin` creates one with a display `name`, a `kind` of `LOCKER` or `COUNTER`, and a `postal_code`; the location starts `ONBOARDING`. Activation by a `PlatformAdmin` moves it to `OPERATIONAL`. A pause — available to both a `PlatformAdmin` and the location's own operator — moves `OPERATIONAL` → `PAUSED` and blocks new slot reservations and counter drop-offs with `ERR_LOCATION_NOT_OPERATIONAL`; resuming returns `PAUSED` → `OPERATIONAL`. Decommissioning, a `PlatformAdmin` privilege available from either `OPERATIONAL` or `PAUSED`, requires that no slot at the location is `RESERVED` or `OCCUPIED` — a busy location is refused with `ERR_LOCATION_BUSY` — and moves the location to the terminal `DECOMMISSIONED` while flipping every `EMPTY` slot to `OUT_OF_SERVICE`. Two counters track locker utilization: `reserved_slot_count` is the number of the location's slots currently `RESERVED`, and `occupied_slot_count` the number currently `OCCUPIED`; both are recomputed as slots change state. A location's slots are listable with optional `size_class` and `status` filters, and the orders dropped off there are listable with an optional `status` filter.

**LockerSlot** resources are added to a location by a `PlatformAdmin` naming a `size_class` of `S`, `M`, `L`, or `XL`; the slot's `location_id` is bound from the creation path and its status starts `EMPTY`. The size classes carry hard ceilings: an `S` slot takes packages up to 30 cm on their longest side, `M` up to 60 cm, `L` up to 100 cm, and `XL` up to 150 cm. An `EMPTY` slot can be marked `OUT_OF_SERVICE` and later restored to `EMPTY`, both by the location operator or a `PlatformAdmin`. When a carrier crew empties an `OCCUPIED` locker into staging, the operator's sweep-collect action moves the slot back to `EMPTY` and decrements the location's `occupied_slot_count` by one.

A **SlotReservation** is the shopper's claim on one slot. The shopper creates one by naming the `return_order_id` of an order that must be `INITIATED` with method `LOCKER_QR` and the `slot_id` of a slot that must be neither `OUT_OF_SERVICE` nor `OCCUPIED`. The slot's service state is examined immediately after the order's state and before the size-class fit: a slot sitting `OUT_OF_SERVICE` is refused with `ERR_SLOT_OUT_OF_SERVICE` and an `OCCUPIED` slot with `ERR_SLOT_UNAVAILABLE`. The location must be `OPERATIONAL` — otherwise `ERR_LOCATION_NOT_OPERATIONAL`. The slot's `size_class` must fit the order's largest item as measured by `longest_side_cm`, else `ERR_SLOT_SIZE_TOO_SMALL`. Exclusivity is governed by the live-hold test: a slot accepts a new reservation only when no *other* reservation on that slot is in `HELD` status with a `hold_until` still in the future; an overlapping live hold is rejected with `ERR_SLOT_UNAVAILABLE`, while an adjacency — a previous hold whose `hold_until` is at or before the current instant — blocks nothing. A created reservation stamps `hold_start` at the current instant and sets `hold_until` exactly 48 hours later, forming a half-open window from `hold_start` inclusive to `hold_until` exclusive. Its status starts `HELD`, and its creation cascades broadly: the slot flips `EMPTY` → `RESERVED` and the location's `reserved_slot_count` increments by one; a QR label is auto-issued and recorded on the reservation's `label_id`; and the order advances `INITIATED` → `LABEL_ISSUED`. Reservations are listable with optional `slot_id`, `return_order_id`, `label_id`, and `status` filters.

The reservation then resolves in one of three ways. **Consume** — performed by the location's operator — deposits the package: it requires the reservation still `HELD` and the current instant strictly before `hold_until`, with an attempt at or after `hold_until` rejected as `ERR_RESERVATION_EXPIRED`, and the caller must own the slot's location, else `ERR_OWNERSHIP_MISMATCH`. Consume fires a three-link cascade: first the slot flips `RESERVED` → `OCCUPIED`, decrementing the location's `reserved_slot_count` and incrementing its `occupied_slot_count`; that flip causes the order to move `LABEL_ISSUED` → `DROPPED_OFF` with `dropoff_location_id` set to the slot's location; and the drop-off in turn consumes the bound label (`ISSUED` → `CONSUMED`), while the reservation itself moves from `HELD` to the terminal `CONSUMED`. **Release** — by the shopper or the operator — moves `HELD` → `RELEASED` and unwinds the claim: the slot returns to `EMPTY`, the bound label is voided, and the order falls back `LABEL_ISSUED` → `INITIATED`. **Expiry** — from the §2.5 sweep — moves `HELD` → `EXPIRED` when `hold_until` has been reached, freeing the slot to `EMPTY` and recomputing the location's reserved count.

### 3.6. Home Pickup and Courier Zones

Merchants on pickup-enabled plans can let shoppers hand parcels to a courier at home. Coverage is organized into **CourierZone** resources, created by a `PlatformAdmin` with a unique `zone_code` (a duplicate is refused with `ERR_INVALID_REQUEST`) and a `window_capacity` of at least one — the maximum number of live pickup appointments whose windows may overlap. Two load gauges describe a zone at the current instant. `confirmed_load` counts the zone's appointments in `SCHEDULED` or `EN_ROUTE` status whose window contains the current clock instant. `demand_load` adds to that the `FAILED` appointments with `attempt_count` below three whose window contains now — the expected reschedules — so the demand gauge is always at least the confirmed one and is strictly larger whenever a retryable failure overlaps the present.

A **PickupAppointment** is booked by the shopper for an order that must be `INITIATED` with method `HOME_PICKUP`, naming the `zone_id` and a window from `window_start` (inclusive) to `window_end` (exclusive). The window must lie in the future — a `window_start` preceding the current logical instant is rejected with `ERR_PICKUP_WINDOW_PAST` — and `window_end` must be strictly after `window_start`, with a window failing that ordering refused with `ERR_INVALID_REQUEST`. Zone capacity is an aggregate gate, not an exclusive lock: two windows overlap when each starts before the other ends, and the booking is rejected with `ERR_PICKUP_WINDOW_FULL` only when the zone's count of `SCHEDULED` or `EN_ROUTE` appointments overlapping the requested window has already reached `window_capacity` — up to that many overlapping windows are admitted, and the next one is refused. A booked appointment starts `SCHEDULED` with `attempt_count` at zero, the order itself stays `INITIATED`, and a QR label is auto-issued so the order advances to `LABEL_ISSUED`. Appointments are listable with optional `return_order_id`, `zone_id`, and `status` filters.

The courier's day then drives the appointment machine, with every courier action performed by a `PlatformAdmin`. Starting the run moves `SCHEDULED` → `EN_ROUTE`, but not earlier than one hour before `window_start` — an earlier attempt is rejected with `ERR_PICKUP_TOO_EARLY`. A successful collection moves `EN_ROUTE` → `COLLECTED` and cascades to the order: whether the order sat in `INITIATED` or `LABEL_ISSUED`, it advances to `IN_TRANSIT`, and its active label is consumed. A failed attempt moves `EN_ROUTE` → `FAILED` and increments `attempt_count` by one. The shopper (or a `PlatformAdmin`) may reschedule a `FAILED` appointment back to `SCHEDULED` by supplying a fresh `window_start` and `window_end`, but only while `attempt_count` remains below three — a third-strike reschedule is refused with `ERR_PICKUP_MAX_ATTEMPTS` — and the new window must again pass the not-past and zone-capacity checks. While still `SCHEDULED`, the shopper may also simply cancel the appointment into the terminal `CANCELLED`.

### 3.7. Carrier Routes and Consolidation Totes

Dropped-off parcels leave the network in consolidated totes riding carrier routes. A **CarrierRoute** is created by a `CarrierDispatcher` or `PlatformAdmin` with an `origin_location_id`, a `destination_facility` name, and a `weight_capacity_grams` greater than zero; the route starts `PLANNED`. The dispatcher dispatches it (`PLANNED` → `DISPATCHED`), arrives it (`DISPATCHED` → `ARRIVED`), or cancels it (`PLANNED` → `CANCELLED`) while still `PLANNED`. Cancellation is refused with `ERR_ROUTE_HAS_LIVE_TOTE` when any tote in `SEALED` or `DISPATCHED` references the route; totes still `FILLING` on a cancelled route remain `FILLING` but reject further member additions, since the route is no longer `PLANNED` or `DISPATCHED`. Routes are listable with optional `origin_location_id` and `status` filters.

A **ConsolidationTote** is created by the location's operator with a `route_id` and a `location_id`; the route must be `PLANNED` or `DISPATCHED`, the tote's `location_id` must equal the route's `origin_location_id`, else `ERR_ROUTE_ORIGIN_MISMATCH`, and the location must be `OPERATIONAL`, else `ERR_LOCATION_NOT_OPERATIONAL`. The tote starts `FILLING` with both manifest counters at zero. Totes are listable with optional `route_id`, `location_id`, and `status` filters, and a tote's member orders are listable as a sub-collection.

Membership changes are guarded twice over. Structurally, only a `FILLING` tote accepts adds or removes — otherwise `ERR_TOTE_NOT_FILLING` — and only for orders that are `DROPPED_OFF` at the tote's own location: an order whose `dropoff_location_id` differs is rejected with `ERR_ORDER_NOT_AT_LOCATION`, and an order already holding a tote membership anywhere is rejected with `ERR_ORDER_ALREADY_IN_TOTE`. An add is additionally refused with `ERR_INVALID_STATE` when the tote's route has left `PLANNED`/`DISPATCHED` (for example, a cancelled route), and a remove naming an order that is not a member of the tote is refused with `ERR_NOT_FOUND`. Within an add, the guards fire in this order: the tote's `FILLING` requirement, then route currency, then existing membership, then location match, then unit headroom, then weight headroom. Concurrency-wise, both the add and the remove carry `expected_tote_version` per §2.7, rejected with `ERR_STALE_VERSION` when the tote's manifest has moved on since the client read it. Capacity is checked on the manifest counters, which sum the member orders' `total_units` into `manifest_units` and their `total_weight_grams` into `manifest_weight_grams`. An add is rejected with `ERR_TOTE_CAPACITY_EXCEEDED` when it would push the unit total strictly beyond 40, and with `ERR_TOTE_WEIGHT_EXCEEDED` when it would push the weight strictly beyond 30,000 grams; landing exactly on either bound is allowed. A successful add sets the order's `tote_id`, a remove clears it back to null, and either operation recomputes the manifest totals and increments the tote's `version` by one.

Sealing and shipping complete the loop. The operator seals a `FILLING` tote that holds at least one unit — sealing an empty tote is refused with `ERR_TOTE_EMPTY` — moving it to `SEALED` and recording `sealed_by_user_id`; the seal can be deliberately reverted, moving `SEALED` back to `FILLING` and clearing `sealed_by_user_id`, a cyclic pair that allows repacking before dispatch. Dispatching a `SEALED` tote requires its route already `DISPATCHED`, else `ERR_ROUTE_NOT_DISPATCHED`, and requires the tote's `manifest_weight_grams` not to exceed the route's `weight_capacity_grams`, else `ERR_ROUTE_WEIGHT_EXCEEDED`; dispatch moves the tote to `DISPATCHED` and every member order from `DROPPED_OFF` to `IN_TRANSIT`. Arrival — by a `CarrierDispatcher` or the location operator — moves the tote `DISPATCHED` → `ARRIVED` and every member order from `IN_TRANSIT` to `INSPECTING`. Should the manifest not match the physical contents, a `SupportAgent` or `PlatformAdmin` flags the tote with a `note`, moving `ARRIVED` → `DISCREPANCY`; reconciliation by a `SupportAgent` or the operator moves either `ARRIVED` or `DISCREPANCY` to the terminal `RECONCILED`, closing the audit loop.

### 3.8. Inspection, Refund Settlement, and the Ledger

Every returned item passes through inspection. The location's operator (or a `PlatformAdmin`) inspects a `PENDING` **ReturnItem** by submitting the observed `condition` — one of `NEW`, `LIGHT_USE`, `DAMAGED`, `DEFECTIVE`, or `WRONG_ITEM` — with an optional `note`. The parent order must be in `INSPECTING` or `EXCEPTION_PENDING`, else the attempt fails with `ERR_INVALID_STATE`, and an item already `INSPECTED` rejects a second inspection with `ERR_ITEM_ALREADY_INSPECTED`. A successful inspection moves the item from `PENDING` to `INSPECTED`, stamps `inspected_at`, records the observed `condition`, and computes the line's `deduction_cents` through the tiered deduction rule in its **final settlement** variant: the line gross is `unit_price_cents` multiplied by `quantity`; the deduction percentage follows the *inspected* condition — zero for `NEW`, ten percent for `LIGHT_USE`, fifty percent for `DAMAGED`, zero for `DEFECTIVE`, and one hundred percent for `WRONG_ITEM`; then the plan override applies, so when the merchant's plan has `free_returns`, a `NEW` or `LIGHT_USE` line's percentage is waived to zero — while a `DAMAGED` line is never waived and always keeps its fifty percent. The line deduction is rounded half-up per line before any summation. Because the final variant uses inspected conditions with the plan override, it differs from the provisional estimate whenever the declared and inspected conditions disagree or the waiver applies.

The last uninspected item is a pivot point. When the final `PENDING` item of an order is inspected, the branches are evaluated in a fixed order. First, if any exception is still open on the order, the order simply stays in `EXCEPTION_PENDING` and resolution is deferred until the exception itself resolves — no further case is auto-created, preserving the one-live-exception rule of §3.9. Otherwise, if any item's inspected condition is `WRONG_ITEM`, the system auto-creates an exception of kind `WRONG_ITEM` — recorded as opened by `system`, with its `return_item_id` naming the just-inspected item when that item is the `WRONG_ITEM` one and otherwise the earliest-created `WRONG_ITEM` item of the order — and the order moves `INSPECTING` → `EXCEPTION_PENDING`. Only when no exception is open and no item was inspected `WRONG_ITEM` does the order bubble up through resolution in the same breath: it enters `RESOLVED`, recomputes `refund_final_cents` as the sum over lines of gross minus the per-line rounded deductions, appends a `FINAL` ledger entry for exactly that amount, stamps `resolved_at`, and moves on to the terminal `REFUND_POSTED`; the billing cycle whose window covers `resolved_at` has its `refunds_accrued_cents` refreshed in the same transaction. This order-level re-evaluation also runs whenever an exception resolves: with no further open exceptions and at least one item still `PENDING`, the order returns `EXCEPTION_PENDING` → `INSPECTING`; with all items inspected, it advances to `RESOLVED` and thence to `REFUND_POSTED` as just described. An order may loop between `INSPECTING` and `EXCEPTION_PENDING` many times before settling.

The **RefundLedgerEntry** is the order's financial memory: an append-only, immutable log. Each entry records the `return_order_id`, a `kind` of `ESTIMATE`, `ADJUSTMENT`, `FINAL`, or `CORRECTION`, a signed `amount_cents`, a free-text `note`, and the `actor_user_id` of the caller — with `system` standing in for automatic entries. `ESTIMATE` and `FINAL` entries are system-only and always non-negative; exactly one `FINAL` may ever exist for an order, and any attempt that would introduce a second is refused with `ERR_REFUND_FINAL_POSTED`. Because the two kinds are system-only, the ledger-append endpoint admits only the `ADJUSTMENT` and `CORRECTION` kinds: a request carrying a `kind` of `ESTIMATE` or `FINAL` is refused with `ERR_INVALID_REQUEST` at shape validation (priority 4 of §2.8), before any state or ledger rule is evaluated. Human agents append the other two kinds against an order that has already posted its refund: a `SupportAgent` or `PlatformAdmin` may append an `ADJUSTMENT`, while a `CORRECTION` is reserved for a `PlatformAdmin` and any other role attempting one is refused with `ERR_CORRECTION_REQUIRES_ADMIN`. Every append request must carry an integer `amount_cents` and a `note` string; both are required. Both human kinds may carry negative amounts, but the ledger must never be driven underwater: any entry that would push the order's payable amount below zero is rejected with `ERR_ADJUSTMENT_EXCEEDS_PAYABLE`. Every append triggers a recomputation of the refund projection, and an order's ledger is listable in chronological order.

The **refund projection** is the derived view of that ledger, replayed from its entries in `created_at` ascending order with ties broken by `created_at` alone, never by `id`. The replay yields `estimated_cents` as the amount of the latest `ESTIMATE` entry — zero if none exists — and `final_cents` as the amount of the latest `FINAL` entry, which stays null until one is posted; that value is what populates the order's `refund_final_cents`. The `payable_cents` is the latest `FINAL` amount (or zero when none exists) plus the sum of all `ADJUSTMENT` entries plus the sum of all `CORRECTION` entries. The projection also reports `entry_count` and a `refund_status` of `ESTIMATED` when no `FINAL` entry exists and `POSTED` once one does.

### 3.9. Exception Cases, Appeals, and Shopper Trust

When something goes wrong, an **ExceptionCase** formalizes it. A `SupportAgent` or the location's operator opens one on a non-terminal order by supplying the `return_order_id`, a `kind` of `DAMAGED_ITEM`, `LOST_PARCEL`, `WRONG_ITEM`, `LABEL_FRAUD`, or `OVERSIZE_REJECT`, and an opening `note`; for `DAMAGED_ITEM` (and optionally for other item-linked kinds) the case also carries a `return_item_id`, which is required precisely when the kind is `DAMAGED_ITEM`. A supplied `return_item_id` must name an existing item — an unknown one is `ERR_NOT_FOUND` — belonging to the order named by `return_order_id`: a mismatch is refused with `ERR_CROSS_MERCHANT_REFERENCE` when the item's own order belongs to a different merchant, and with `ERR_INVALID_REQUEST` when it belongs to a different order of the same merchant. Only one exception may be live on an order at a time — a second open attempt while any case sits in `OPEN`, `INVESTIGATING`, `AWAITING_SHOPPER`, or `REOPENED` is refused with `ERR_EXCEPTION_OPEN_EXISTS`. The opener's identity is recorded in `opened_by_user_id`, with `system` standing in for auto-created `WRONG_ITEM` cases, and opening cascades to the order: an order in `DROPPED_OFF`, `IN_TRANSIT`, or `INSPECTING` moves to `EXCEPTION_PENDING`. A case starts `OPEN` with `resolution` null and `appeal_count` at zero. Cases are listable with optional `return_order_id`, `return_item_id`, `kind`, and `status` filters, and an order's own cases are listable as a sub-collection.

Investigation is a support-led loop. A `SupportAgent` starts investigation, moving `OPEN` → `INVESTIGATING` — the same action also re-enters investigation from `REOPENED` after an appeal. When shopper input is needed, the agent moves `INVESTIGATING` → `AWAITING_SHOPPER`; the shopper answers with a `response_note`, moving the case back to `INVESTIGATING`, and the caller must own the order's shopper, else `ERR_OWNERSHIP_MISMATCH`.

Resolution is the case's moment of consequence and is guarded three ways: the case must be `INVESTIGATING`; the resolver must differ from the opener — a resolver whose identity equals `opened_by_user_id` is refused with `ERR_SOD_RESOLVER_EQUALS_OPENER`, and that differing identity is recorded in `resolved_by_user_id`; and the request must carry `expected_exception_case_version` per §2.7, rejected with `ERR_STALE_VERSION` when the case has moved since the resolver read it. The resolver submits a `resolution` of `APPROVED` or `REJECTED` with an optional `note`, moving the case from `INVESTIGATING` to `RESOLVED_APPROVED` or `RESOLVED_REJECTED` respectively, and the per-kind cascades fire. An approved `DAMAGED_ITEM` case rewrites the linked item's condition from `DAMAGED` to `DEFECTIVE` (a linked item whose condition is no longer `DAMAGED` is left alone). Wherever a case re-marks an item `DEFECTIVE`, the re-mark also flips a still-`PENDING` item to `INSPECTED` with `inspected_at` stamped, and recomputes that line's `deduction_cents` under the final-settlement rule of §3.8 — `DEFECTIVE` carrying a zero percent deduction. An approved `LABEL_FRAUD` case increments the shopper's `fraud_strikes` by one, auto-restricts the shopper when the count reaches two, and closes the order into `REJECTED_CLOSED` with `resolved_at` stamped and — deliberately — no `FINAL` ledger entry, so the refund stays unposted. An approved `LOST_PARCEL` case marks every item of the order `DEFECTIVE`, while a *rejected* `LOST_PARCEL` case sends the order to the same terminal `REJECTED_CLOSED` without a final entry. An approved `OVERSIZE_REJECT` case reroutes the order: it returns `EXCEPTION_PENDING` → `INITIATED` with `method` rewritten to `HOME_PICKUP`, the active label voided, and any held reservation released with its slot emptied, so the oversize parcel re-enters the network through the pickup path. Where a resolution instead closes the order, the transition runs from `EXCEPTION_PENDING` to the terminal `REJECTED_CLOSED`. In every remaining resolve path, the order re-evaluates as described in §3.8: back to `INSPECTING` when uninspected items remain, or onward through `RESOLVED` — where `refund_final_cents` is recomputed with the now-current conditions and the `FINAL` entry appended — to `REFUND_POSTED`, with the covering billing cycle's `refunds_accrued_cents` refreshed. A rejected case whose kind carries no terminal cascade follows that same re-evaluation with item conditions unchanged.

Closure and appeal bound the afterlife of a case. A `SupportAgent` closes a resolved case, moving either `RESOLVED_APPROVED` or `RESOLVED_REJECTED` to the terminal `CLOSED`. Alternatively the shopper may appeal a resolved case by submitting an `appeal_note`, moving it to `REOPENED` and incrementing `appeal_count` by one — but only while fewer than two appeals have been filed, with a third attempt refused as `ERR_APPEAL_LIMIT_REACHED`. An appeal on an already-posted refund does not unwind the posting: the order stays `REFUND_POSTED`, and any money correction flows through the ledger's `ADJUSTMENT` and `CORRECTION` machinery of §3.8 rather than by re-opening settlement.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Every endpoint enforces the header, role, ownership, validation-order, and concurrency contracts of §2. The table below is a navigation index only — request payloads, cascades, and guards are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/subscription-plans` | Create a subscription plan (starts `DRAFT`) | PlatformAdmin |
| GET | `/v1/subscription-plans/{id}` | Get a plan | PlatformAdmin, MerchantAdmin, SupportAgent |
| POST | `/v1/subscription-plans/{id}/publish` | Publish a `DRAFT` plan | PlatformAdmin |
| POST | `/v1/subscription-plans/{id}/retire` | Retire a `PUBLISHED` plan with no active merchants | PlatformAdmin |
| POST | `/v1/merchant-accounts` | Create a merchant on a `PUBLISHED` plan | PlatformAdmin |
| GET | `/v1/merchant-accounts/{id}` | Get a merchant | PlatformAdmin, MerchantAdmin, SupportAgent |
| GET | `/v1/merchant-accounts` | List merchants, filterable by plan and status | PlatformAdmin, SupportAgent |
| POST | `/v1/merchant-accounts/{id}/suspend` | Suspend an active merchant | PlatformAdmin |
| POST | `/v1/merchant-accounts/{id}/reactivate` | Reactivate a suspended merchant | PlatformAdmin |
| POST | `/v1/merchant-accounts/{id}/close` | Close a merchant, cascading cancellations | PlatformAdmin |
| GET | `/v1/merchant-accounts/{id}/billing-cycles` | List a merchant's billing cycles | PlatformAdmin, MerchantAdmin |
| GET | `/v1/merchant-accounts/{id}/return-orders` | List a merchant's return orders | PlatformAdmin, MerchantAdmin, SupportAgent |
| POST | `/v1/merchant-accounts/{id}/billing-cycles` | Open a billing cycle for the merchant | PlatformAdmin |
| GET | `/v1/billing-cycles/{id}` | Get a billing cycle | PlatformAdmin, MerchantAdmin |
| GET | `/v1/billing-cycles/{id}/charge-preview` | Provisional forward-looking charge computation on an `OPEN` cycle | PlatformAdmin, MerchantAdmin |
| POST | `/v1/billing-cycles/{id}/close` | Close an `OPEN` cycle with final charge computation | PlatformAdmin |
| POST | `/v1/billing-cycles/{id}/settle` | Settle a `CLOSING` cycle (settler differs from closer) | PlatformAdmin |
| POST | `/v1/billing-cycles/{id}/dispute` | Merchant disputes a `SETTLED` cycle | MerchantAdmin |
| POST | `/v1/billing-cycles/{id}/resettle` | Re-settle a `DISPUTED` cycle (settler differs from closer) | PlatformAdmin |
| POST | `/v1/shoppers` | Register a shopper | Shopper, PlatformAdmin |
| GET | `/v1/shoppers/{id}` | Get a shopper | Shopper, SupportAgent, PlatformAdmin |
| GET | `/v1/shoppers/{id}/return-orders` | List a shopper's return orders | Shopper, SupportAgent, PlatformAdmin |
| POST | `/v1/shoppers/{id}/unrestrict` | Lift a shopper restriction and reset fraud strikes | SupportAgent, PlatformAdmin |
| POST | `/v1/dropoff-locations` | Create a drop-off location (starts `ONBOARDING`) | PlatformAdmin |
| GET | `/v1/dropoff-locations/{id}` | Get a location | PlatformAdmin, LocationOperator, SupportAgent, CarrierDispatcher |
| POST | `/v1/dropoff-locations/{id}/activate` | Activate an `ONBOARDING` location | PlatformAdmin |
| POST | `/v1/dropoff-locations/{id}/pause` | Pause an `OPERATIONAL` location | PlatformAdmin, LocationOperator |
| POST | `/v1/dropoff-locations/{id}/resume` | Resume a `PAUSED` location | PlatformAdmin, LocationOperator |
| POST | `/v1/dropoff-locations/{id}/decommission` | Decommission a location with no busy slots | PlatformAdmin |
| GET | `/v1/dropoff-locations/{id}/locker-slots` | List slots at a location | PlatformAdmin, LocationOperator, SupportAgent, Shopper |
| GET | `/v1/dropoff-locations/{id}/return-orders` | List orders dropped off at a location | PlatformAdmin, LocationOperator, SupportAgent |
| POST | `/v1/dropoff-locations/{id}/locker-slots` | Add a locker slot (starts `EMPTY`) | PlatformAdmin |
| GET | `/v1/locker-slots/{id}` | Get a slot | PlatformAdmin, LocationOperator, SupportAgent |
| POST | `/v1/locker-slots/{id}/out-of-service` | Mark an `EMPTY` slot out of service | LocationOperator, PlatformAdmin |
| POST | `/v1/locker-slots/{id}/restore` | Restore an `OUT_OF_SERVICE` slot | LocationOperator, PlatformAdmin |
| POST | `/v1/locker-slots/{id}/sweep-collect` | Carrier empties an `OCCUPIED` slot into staging | LocationOperator |
| POST | `/v1/return-orders` | Create a return order with inline items and provisional estimate | Shopper |
| GET | `/v1/return-orders/{id}` | Get a return order | Shopper, MerchantAdmin, SupportAgent, PlatformAdmin, LocationOperator, CarrierDispatcher |
| POST | `/v1/return-orders/{id}/cancel` | Cancel an `INITIATED` or `LABEL_ISSUED` order | Shopper, SupportAgent |
| PATCH | `/v1/return-orders/{id}/method` | Change fulfilment method (OCC; voids label, releases reservation) | Shopper |
| GET | `/v1/return-orders/{id}/items` | List an order's items | Shopper, MerchantAdmin, SupportAgent, PlatformAdmin, LocationOperator |
| GET | `/v1/return-items/{id}` | Get a return item | Shopper, MerchantAdmin, SupportAgent, PlatformAdmin, LocationOperator |
| POST | `/v1/return-items/{id}/inspect` | Inspect a `PENDING` item; last item triggers resolution cascade | LocationOperator, PlatformAdmin |
| POST | `/v1/return-orders/{id}/labels` | Issue a label (OCC; supersedes any active label) | Shopper |
| GET | `/v1/labels/{id}` | Get a label | Shopper, SupportAgent, PlatformAdmin, LocationOperator |
| GET | `/v1/labels` | List labels, filterable by order, supersession, and status | Shopper, SupportAgent, PlatformAdmin |
| POST | `/v1/labels/{id}/void` | Void an `ISSUED` label | Shopper, SupportAgent |
| POST | `/v1/return-orders/{id}/confirm-dropoff` | Counter drop-off confirmation by the location operator | LocationOperator |
| POST | `/v1/return-orders/{id}/receive` | Receive an `IN_TRANSIT` order into inspection | PlatformAdmin, LocationOperator |
| POST | `/v1/slot-reservations` | Reserve a locker slot (auto-issues QR label, 48-hour hold) | Shopper |
| GET | `/v1/slot-reservations/{id}` | Get a reservation | Shopper, LocationOperator, SupportAgent, PlatformAdmin |
| GET | `/v1/slot-reservations` | List reservations, filterable by slot, order, label, and status | LocationOperator, SupportAgent, PlatformAdmin |
| POST | `/v1/slot-reservations/{id}/release` | Release a `HELD` reservation | Shopper, LocationOperator |
| POST | `/v1/slot-reservations/{id}/consume` | Deposit the package into the reserved slot | LocationOperator |
| POST | `/v1/courier-zones` | Create a courier zone | PlatformAdmin |
| GET | `/v1/courier-zones/{id}` | Get a zone including its demand projection | PlatformAdmin, SupportAgent, Shopper |
| POST | `/v1/pickup-appointments` | Book a home pickup against zone aggregate capacity | Shopper |
| GET | `/v1/pickup-appointments/{id}` | Get an appointment | Shopper, SupportAgent, PlatformAdmin |
| GET | `/v1/pickup-appointments` | List appointments, filterable by order, zone, and status | SupportAgent, PlatformAdmin |
| POST | `/v1/pickup-appointments/{id}/start` | Courier en route (no earlier than one hour before the window) | PlatformAdmin |
| POST | `/v1/pickup-appointments/{id}/collect` | Courier collected the parcel | PlatformAdmin |
| POST | `/v1/pickup-appointments/{id}/fail` | Record a failed pickup attempt | PlatformAdmin |
| POST | `/v1/pickup-appointments/{id}/reschedule` | Reschedule a `FAILED` appointment | Shopper, PlatformAdmin |
| POST | `/v1/pickup-appointments/{id}/cancel` | Cancel a `SCHEDULED` appointment | Shopper |
| POST | `/v1/carrier-routes` | Create a route from a location to a facility | CarrierDispatcher, PlatformAdmin |
| GET | `/v1/carrier-routes/{id}` | Get a route | CarrierDispatcher, PlatformAdmin, LocationOperator, SupportAgent |
| GET | `/v1/carrier-routes` | List routes, filterable by origin and status | CarrierDispatcher, PlatformAdmin |
| POST | `/v1/carrier-routes/{id}/dispatch` | Dispatch a `PLANNED` route | CarrierDispatcher |
| POST | `/v1/carrier-routes/{id}/arrive` | Arrive a `DISPATCHED` route | CarrierDispatcher |
| POST | `/v1/carrier-routes/{id}/cancel` | Cancel a `PLANNED` route with no live totes | CarrierDispatcher |
| POST | `/v1/consolidation-totes` | Create a tote at a route's origin location | LocationOperator |
| GET | `/v1/consolidation-totes/{id}` | Get a tote | LocationOperator, PlatformAdmin, CarrierDispatcher, SupportAgent |
| GET | `/v1/consolidation-totes` | List totes, filterable by route, location, and status | LocationOperator, PlatformAdmin, CarrierDispatcher |
| GET | `/v1/consolidation-totes/{id}/return-orders` | List member orders of a tote | LocationOperator, PlatformAdmin, CarrierDispatcher, SupportAgent |
| POST | `/v1/consolidation-totes/{id}/return-orders` | Add a `DROPPED_OFF` order to a `FILLING` tote (OCC) | LocationOperator |
| POST | `/v1/consolidation-totes/{id}/return-orders/remove` | Remove a member order from a `FILLING` tote (OCC) | LocationOperator |
| POST | `/v1/consolidation-totes/{id}/seal` | Seal a non-empty `FILLING` tote | LocationOperator |
| POST | `/v1/consolidation-totes/{id}/unseal` | Unseal back to `FILLING` | LocationOperator |
| POST | `/v1/consolidation-totes/{id}/dispatch` | Dispatch a `SEALED` tote; members move to `IN_TRANSIT` | LocationOperator |
| POST | `/v1/consolidation-totes/{id}/arrive` | Arrive a `DISPATCHED` tote; members move to `INSPECTING` | CarrierDispatcher, LocationOperator |
| POST | `/v1/consolidation-totes/{id}/flag-discrepancy` | Flag an `ARRIVED` tote as discrepant | SupportAgent, PlatformAdmin |
| POST | `/v1/consolidation-totes/{id}/reconcile` | Reconcile an `ARRIVED` or `DISCREPANCY` tote | SupportAgent, LocationOperator |
| GET | `/v1/return-orders/{id}/refund-ledger` | List an order's refund ledger entries chronologically | Shopper, MerchantAdmin, SupportAgent, PlatformAdmin |
| POST | `/v1/return-orders/{id}/refund-ledger/entries` | Append an `ADJUSTMENT` or `CORRECTION` entry | SupportAgent, PlatformAdmin |
| GET | `/v1/return-orders/{id}/refund-projection` | Derived refund view replayed from the ledger | Shopper, MerchantAdmin, SupportAgent, PlatformAdmin |
| POST | `/v1/exception-cases` | Open an exception on a non-terminal order | SupportAgent, LocationOperator |
| GET | `/v1/exception-cases/{id}` | Get an exception case | SupportAgent, PlatformAdmin, LocationOperator, Shopper, MerchantAdmin |
| GET | `/v1/exception-cases` | List exception cases, filterable by order, item, kind, and status | SupportAgent, PlatformAdmin |
| GET | `/v1/return-orders/{id}/exception-cases` | List an order's exceptions | Shopper, MerchantAdmin, SupportAgent, PlatformAdmin, LocationOperator |
| POST | `/v1/exception-cases/{id}/start-investigation` | Move `OPEN` or `REOPENED` to `INVESTIGATING` | SupportAgent |
| POST | `/v1/exception-cases/{id}/request-shopper-info` | Move `INVESTIGATING` to `AWAITING_SHOPPER` | SupportAgent |
| POST | `/v1/exception-cases/{id}/provide-shopper-info` | Shopper responds; back to `INVESTIGATING` | Shopper |
| POST | `/v1/exception-cases/{id}/resolve` | Resolve an `INVESTIGATING` case (OCC; resolver differs from opener) | SupportAgent |
| POST | `/v1/exception-cases/{id}/appeal` | Shopper appeals a resolved case into `REOPENED` | Shopper |
| POST | `/v1/exception-cases/{id}/close` | Close a resolved case | SupportAgent |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/v1/_maintenance/run_sweep` | Run the expiry sweep at the current logical instant | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ENUM_INVALID` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_MERCHANT_SUSPENDED` | 409 |
| `ERR_SHOPPER_RESTRICTED` | 403 |
| `ERR_BILLING_CYCLE_NOT_OPEN` | 409 |
| `ERR_BILLING_PERIOD_OVERLAP` | 409 |
| `ERR_ROUTE_ORIGIN_MISMATCH` | 422 |
| `ERR_CROSS_MERCHANT_REFERENCE` | 422 |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 |
| `ERR_ROUTE_HAS_LIVE_TOTE` | 409 |
| `ERR_ROUTE_WEIGHT_EXCEEDED` | 422 |
| `ERR_DIM_EXCEEDS_XL` | 422 |
| `ERR_OVERSIZE_NOT_SUPPORTED` | 422 |
| `ERR_FEATURE_NOT_INCLUDED` | 422 |
| `ERR_LABEL_METHOD_MISMATCH` | 422 |
| `ERR_SLOT_SIZE_TOO_SMALL` | 422 |
| `ERR_SLOT_UNAVAILABLE` | 409 |
| `ERR_SLOT_OUT_OF_SERVICE` | 409 |
| `ERR_RESERVATION_EXPIRED` | 409 |
| `ERR_LABEL_EXPIRED` | 409 |
| `ERR_LABEL_NOT_ACTIVE` | 409 |
| `ERR_PICKUP_WINDOW_PAST` | 422 |
| `ERR_PICKUP_WINDOW_FULL` | 409 |
| `ERR_PICKUP_MAX_ATTEMPTS` | 409 |
| `ERR_PICKUP_TOO_EARLY` | 409 |
| `ERR_TOTE_NOT_FILLING` | 409 |
| `ERR_TOTE_CAPACITY_EXCEEDED` | 409 |
| `ERR_TOTE_WEIGHT_EXCEEDED` | 409 |
| `ERR_TOTE_EMPTY` | 409 |
| `ERR_ORDER_ALREADY_IN_TOTE` | 409 |
| `ERR_ORDER_NOT_AT_LOCATION` | 409 |
| `ERR_ITEM_ALREADY_INSPECTED` | 409 |
| `ERR_REFUND_FINAL_POSTED` | 409 |
| `ERR_ADJUSTMENT_EXCEEDS_PAYABLE` | 422 |
| `ERR_CORRECTION_REQUIRES_ADMIN` | 403 |
| `ERR_EXCEPTION_OPEN_EXISTS` | 409 |
| `ERR_SOD_RESOLVER_EQUALS_OPENER` | 403 |
| `ERR_SOD_SETTLER_EQUALS_CLOSER` | 403 |
| `ERR_APPEAL_LIMIT_REACHED` | 409 |
| `ERR_OVERAGE_LIMIT_EXCEEDED` | 422 |
| `ERR_LOCATION_NOT_OPERATIONAL` | 409 |
| `ERR_LOCATION_BUSY` | 409 |
| `ERR_PLAN_IN_USE` | 409 |
| `ERR_BILLING_CYCLE_OPEN` | 409 |
