# Laundry & Dry-Cleaning Delivery API — Product Requirements Document

## 1. Introduction

The Laundry & Dry-Cleaning Delivery platform coordinates the full journey of a garment order from the moment a customer requests a pickup to the moment a finished, billed bag is handed back at their doorstep or in a locker compartment. The business runs on the seam between two very different worlds: a logistics operation that books pickup and delivery stops into capacity-limited route windows and parks finished bags in shared locker banks, and a plant operation that weighs, counts, cleans, inspects, and re-prices garments piece by piece. This document specifies the API that ties those worlds together so that every order is priced twice (once provisionally from what the customer declares, and once definitively from what the plant actually measures), every garment is tracked through its own cleaning lifecycle, and every financial movement — subscription inclusion, store-credit wallet, lost-item settlement — reconciles to the cent.

Several recurring tensions shape the rules that follow. Pricing must be deterministic and auditable, so each garment line is rounded to whole cents before any totals are summed. Subscriptions complicate billing because wash-fold weight is partly included up to a per-cycle allowance and partly charged as overage, and because dry-clean and alteration work earns a subscriber discount that wash-fold never does. Capacity is finite: a route window holds only so many stops and a locker compartment can hold only one bag at a time plus a turnaround buffer. And because garments are physical objects that can be damaged or lost, the system tracks a per-customer risk index and supports a lost-item claims process with appeals, depreciation, and per-order payout ceilings. The remainder of this document defines the global contracts that govern every endpoint, the business workflows that move orders, garments, claims, subscriptions, lockers, and invoices through their lifecycles, and the complete catalogue of endpoints and error codes.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they act. When either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly five roles, spelled precisely as follows: `PlatformAdmin`, `Customer`, `DispatchAgent`, `PlantOperator`, and `ClaimsAdjuster`. When a well-identified caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The five roles partition responsibility along operational lines. `PlatformAdmin` is the operational superuser: it configures subscription plans, registers and blocks customers, advances the server clock, and otherwise shares broad write access for seeding and operations. `DispatchAgent` owns logistics — route windows, locker banks, pickup and delivery dispatch, and the locker-assignment lifecycle. `PlantOperator` owns garment processing at the plant: intake logging, cleaning, quality control, stain and damage notes, and lost-item marking. `ClaimsAdjuster` owns claim adjudication: investigating, approving or rejecting, finalizing denials, and settling. `Customer` is the end customer who owns their own subscriptions, orders, garments, and claims.

The binding between `X-User-ID` and resource ownership differs by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID`. Concretely, a `Customer` acting on an `Order`, `Subscription`, or `Claim` must own it: `X-User-ID` must equal the `customer_id` recorded on that resource (for a `Claim`, ownership is resolved through the order the claim is filed against). An attempt by a `Customer` to act on a resource they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`. For the remaining four roles — `PlatformAdmin`, `DispatchAgent`, `PlantOperator`, and `ClaimsAdjuster` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow calls for it (for example, the role that logs a garment note is captured as `logged_by_role` on the `GarmentNote`), but it does not compare an opaque operator identifier to any entity's `id` for ownership purposes.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in this system are first-class, versioned records. Every such resource carries a system-managed set of fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits marking when the resource was first created; an `updated_at` ISO 8601 UTC timestamp with the same format, refreshed on every mutation to the resource; and a `version`, an integer that begins at its initial value on creation and increments by one with every modification. This versioned-resource convention applies to `SubscriptionPlan`, `Customer`, `Subscription`, `RouteWindow`, `Locker`, `Order`, `Garment`, `LockerAssignment`, `Claim`, and `Invoice`.

There is one deliberate exception. A `GarmentNote` is an append-only event record: once a plant operator logs a stain or damage observation it is never edited. A `GarmentNote` therefore carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field.

### 2.5. Monetary Values, Measurement Units, and Precision

All monetary amounts in this system are stored and returned as integer counts of cents — there are no fractional-cent values anywhere in a stored field or response body. Wherever a price is derived from a rate and a continuous quantity, the intermediate arithmetic is performed in decimal and the result is rounded to a whole number of cents using the round-half-up convention (a value whose fractional cents portion is exactly one half rounds away from zero, upward). The ordering of rounding relative to summation matters and is specified per calculation below; the governing rule is that each individual garment line is rounded to whole cents first, and order totals are then formed by plain integer addition of those already-rounded lines, with no further rounding applied to the sum.

Weights are expressed in grams in stored fields and request bodies, while wash-fold pricing rates and tier boundaries are expressed per kilogram. One kilogram equals 1000 grams, so any conversion from a gram quantity to the kilogram basis used for pricing divides the gram figure by 1000. Time buffers and SLA targets are expressed in their natural units in the constants that govern them (minutes for locker turnaround buffers, hours for SLA targets) and are described in context where each is used.

### 2.6. Resource Versioning and Optimistic Concurrency Control

A small number of write operations are guarded by optimistic concurrency control because they supersede a prior view of a resource, and acting on a stale view would silently overwrite a change the client never observed. Each such operation requires the client to submit the version it last observed for the relevant parent resource; if that submitted version does not match the resource's current `version`, the write is rejected before any effect is applied.

Filing a lost-item claim against an order requires the field `expected_order_version`, carrying the `version` of the target `Order` as the client last read it. A claim is only meaningful against a settled view of the order's garments: if a garment was marked lost or the order was re-totaled after the client read the order, the client's view is stale and the claim no longer matches the order's true state. When `expected_order_version` does not equal the order's current `version`, the create is rejected with `ERR_STALE_ORDER_VERSION` at HTTP 412.

Changing the plan on a subscription requires the field `expected_subscription_version`, carrying the `version` of the target `Subscription` as the client last read it. A later plan change legitimately supersedes an earlier one, recomputing inclusion and overage against the new plan; a client carrying a stale subscription version would overwrite a change it never saw. When `expected_subscription_version` does not equal the subscription's current `version`, the plan change is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` at HTTP 412.

Cancelling a subscription likewise requires `expected_subscription_version` to match the subscription's current `version`, and cancelling an order likewise requires `expected_order_version` to match the order's current `version`; a mismatch on the subscription cancel is rejected with `ERR_STALE_SUBSCRIPTION_VERSION`, and a mismatch on the order cancel is rejected with `ERR_STALE_ORDER_VERSION`, both at HTTP 412. No other write endpoint takes a version field, and endpoints that do not name one of these version fields perform no optimistic-concurrency check.

### 2.7. Nested Resource Retrieval and Existence Ordering

Several endpoints address resources nested inside a path — most prominently garments and garment-scoped actions that live under an order, written as path segments such as `orderId` followed by `garmentId`. For any request whose path contains more than one resource identifier, the system validates existence left to right and rejects the request at the first identifier that does not resolve, before evaluating any later identifier or any business rule. A garment action under a non-existent order therefore fails with `ERR_ORDER_NOT_FOUND` before the garment is ever looked up; only once the order resolves is the garment identifier checked, yielding `ERR_GARMENT_NOT_FOUND` if it does not exist or does not belong to that order.

The same left-to-right existence discipline governs all path and body foreign-key references across the API. Each resource family has its own not-found code: `ERR_PLAN_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_LOCKER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_GARMENT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, and `ERR_CLAIM_NOT_FOUND`. Existence is checked after authentication and authorization but before request-body validation and business rules, so that callers are never told a body is malformed when the resource they addressed does not exist.

### 2.8. Hierarchical Consistency and Cascading Effects

Many operations in this system mutate more than one resource. The platform applies all such side effects immediately and synchronously within the operation that triggers them, and every resource that changes as a result has its `updated_at` refreshed and its `version` incremented (with the sole exception of `GarmentNote`, which is never mutated). When an order transition books or releases a stop in a route window, when a garment transition or note adjusts a customer's risk index, when a quality-control pass creates an invoice and advances a subscription's cycle tally, or when a cancellation unwinds those effects — each affected `RouteWindow`, `Customer`, `Subscription`, `Invoice`, `LockerAssignment`, and `Garment` is independently mutated and versioned alongside the order itself. The specific cascades are described in the workflow narratives of Section 3; the principle here is that the system never leaves a derived field, a booking count, a wallet balance, or a child status out of alignment with the event that should have changed it.

### 2.9. Request Validation and Evaluation Order

When several checks could reject the same request, they are evaluated in a fixed priority order so that the most fundamental failure is reported first. The order is: first, presence and well-formedness of the `X-User-ID` and `X-User-Role` headers; second, whether the role is permitted to perform the operation; third, existence of every path-referenced resource, validated left to right as described above; fourth, request-body schema validity — required fields present, types and enumerations correct, and numeric ranges honored, with a violation reported as `ERR_INVALID_REQUEST`; fifth, interval validity for resources that carry a time window; sixth, owner identity for customer-initiated actions; seventh, the target resource being in the correct state for the requested transition; eighth, the cross-entity garment-state gates; and then the remaining domain-specific business rules. A malformed body is reported with `ERR_INVALID_REQUEST` only after headers, permissions, and existence have all passed.

Two structural interval rules share `ERR_INVALID_INTERVAL` at HTTP 400: a route window's `end_utc` must be strictly later than its `start_utc`, and a locker assignment's `hold_end_utc` must be strictly later than its `hold_start_utc`. These interval checks apply when creating a route window and when creating a locker assignment, respectively.

## 3. Business Logic & Workflows

### 3.1. Platform Configuration: Plans, Customers, Subscriptions, Windows, and Lockers

Before any order can flow, a `PlatformAdmin` seeds the operational catalogue. A **subscription plan** is created with a `tier` label that is one of `LITE`, `PLUS`, or `PREMIUM`; a `monthly_fee_cents` recurring fee of at least zero cents; an `included_wash_fold_grams` allowance of at least zero grams that the plan covers per billing cycle; an `overage_rate_cents_per_kg` of at least zero cents charged per kilogram of wash-fold weight above the included allowance; and a `dryclean_discount_pct`, a fractional discount applied to dry-clean and alteration line prices for subscribers, which must be at least 0.0 and at most 0.5. Two optional flags complete the plan: `rush_waived`, which defaults to false and, when true, suppresses the rush surcharge for this plan's subscribers' orders; and `active`, which defaults to true and controls whether new subscriptions may select the plan.

A `PlatformAdmin` registers each **customer** with a unique login `email` that must be unique across all customers, a `full_name` display name, a `default_address` for doorstep handoff, and a `zone_code` naming the delivery zone the customer belongs to. On registration the customer's `status` is `ACTIVE`, their `wallet_credit_cents` store-credit balance starts at 0, and their `risk_score` starts at 0. The `wallet_credit_cents` balance is store credit measured in cents, never negative, credited by claim settlements and debited when applied against an invoice. The `risk_score` is a non-negative garment-handling risk index that accumulates from logged damage and stain notes and from settled lost-item claims and is floored at 0. A customer's `status` is either `ACTIVE` or `BLOCKED`; a `PlatformAdmin` may administratively move a customer to `BLOCKED`, after which that customer cannot create orders.

A **subscription** ties a customer to a plan. It is created — by a `PlatformAdmin` or by the `Customer` for themselves — by supplying `customer_id` and `plan_id`. On creation its `status` is `ACTIVE`, its `cycle_start_utc` is set to the current server time marking the start of the current billing cycle, its `cycle_wash_fold_grams_used` (the running sum of wash-fold grams billed to this subscriber in the current cycle, which resets to 0 on a cycle roll) is 0, and its `outstanding_balance_cents` (the unpaid amount billed to this subscription in the current cycle) is 0. A subscription is a lightweight resource whose only mutating operations are changing its plan and cancelling it. Changing the plan supplies a new `plan_id` together with `expected_subscription_version`; the subscription's recorded plan is updated and inclusion and overage are recomputed against the new plan on the next billing event, and the subscription's `version` increments by one. Cancelling a subscription is permitted only while its `status` is `ACTIVE` — otherwise the cancel is rejected with `ERR_INVALID_SUBSCRIPTION_STATE` — and moves its `status` from `ACTIVE` to `CANCELLED`, incrementing `version` by one. Both mutating operations are optimistic-concurrency guarded as described in Section 2.6.

A **route window** is a bookable slot on a pickup or delivery route. A `PlatformAdmin` or `DispatchAgent` creates one with a `zone_code` it serves, a `window_kind` that is either `PICKUP` or `DELIVERY`, an inclusive `start_utc`, an exclusive `end_utc` that must be later than `start_utc`, and a `stop_capacity` of at least one — the maximum number of distinct orders that may be booked into the window. On creation its `status` is `OPEN` and its `booked_stops` count is 0. The `booked_stops` field counts orders currently booked into the window for the relevant leg (excluding cancelled orders) and is bounded between 0 and `stop_capacity`. A window's `status` is derived: it becomes `FULL` exactly when `booked_stops` equals `stop_capacity`, and it reverts to `OPEN` when a booked stop is released by an order cancellation.

A **locker bank** is created by a `PlatformAdmin` or `DispatchAgent` with a `zone_code` it serves, a human-readable `location_label`, a `compartment_count` of at least one giving the number of physically distinct compartments, and an optional `hold_buffer_minutes` (defaulting to 30) that sets the minimum cleaning and turnaround buffer enforced between two assignments in the same compartment of this bank. A locker has a single-state lifecycle: its `status` is always `OPEN` once created.

### 3.2. Order Intake and Garment Declaration

A `Customer` (or a `PlatformAdmin` acting on their behalf) opens an **order** in the `CREATED` state by submitting `customer_id`, an optional `subscription_id` (omitted for pay-as-you-go orders, supplied to claim wash-fold inclusion benefits), a `pickup_window_id`, a `delivery_window_id`, a `handoff_method` that is either `DOORSTEP` or `LOCKER`, and an optional `rush` flag that defaults to false. A fresh order starts with `status` `CREATED`, `estimate_total_cents` 0, `final_total_cents` 0, and `risk_flag` false. The `ready_by_utc` SLA target is not set at creation — it is computed only when the order is picked up. The `rush` flag, when set, shortens the SLA and adds a rush surcharge to pricing unless the subscriber's plan waives rush. An order may not be opened for a customer whose `status` is `BLOCKED` or whose `risk_score` has reached the customer-block threshold; such an attempt is rejected with `ERR_CUSTOMER_BLOCKED`.

Onto a `CREATED` order, garment lines are added one at a time. Each **garment** declares a `service_type` of `WASH_FOLD`, `DRY_CLEAN`, or `ALTERATION`, and carries an owning `order_id`. For wash-fold work the customer supplies `declared_weight_grams` (the customer-declared weight in grams, at least zero) and leaves the piece count at its default of zero; for dry-clean and alteration work the customer supplies `declared_piece_count` (the declared number of pieces, at least zero) and leaves the declared weight at zero. An alteration line additionally carries a flat per-garment `alteration_fee_cents` (at least zero cents). These declared fields must be internally consistent with the service type: a `WASH_FOLD` line requires `declared_weight_grams` greater than zero with both the declared piece count and the alteration fee zero; a `DRY_CLEAN` line requires `declared_piece_count` greater than zero with declared weight and alteration fee zero; and an `ALTERATION` line requires `declared_piece_count` greater than zero, `alteration_fee_cents` greater than zero, and declared weight zero. Any line whose measurement fields contradict its service type is rejected with `ERR_SERVICE_TYPE_FIELD_MISMATCH` at HTTP 422.

A new garment starts in `INTAKE_PENDING` status, and its priced fields begin empty: the plant-measured `actual_weight_grams` and `actual_piece_count` are both 0 until intake is logged, and `estimate_line_cents` (the provisional line price from declared values) is 0 until the order is scheduled, while `final_line_cents` (the final line price from actual values) is 0 until the garment is finished. Garments and the entire order are read back through their respective list and single-resource reads.

### 3.3. Scheduling the Pickup Leg and Provisional Pricing

When the garments are declared, the customer schedules the order, which moves it from `CREATED` to `SCHEDULED` and books a stop on the pickup leg. Scheduling enforces a sequence of preconditions. The order must carry at least one garment, or the request is rejected with `ERR_NO_GARMENTS`. The owning customer's `status` must be `ACTIVE`, or the request is rejected with `ERR_CUSTOMER_BLOCKED` (the same safety gate that guards order creation, here re-checked against block status and the risk threshold). The chosen pickup window must have `window_kind` `PICKUP` and a `zone_code` equal to the customer's `zone_code`, or the request is rejected with `ERR_WINDOW_ZONE_MISMATCH`. And the pickup window must have spare capacity — its `booked_stops` must be strictly less than its `stop_capacity` — or the booking is rejected with `ERR_WINDOW_FULL`.

On a successful schedule two effects occur. First, the pickup window's `booked_stops` is increased by one, and if that brings `booked_stops` to equal `stop_capacity` the window's `status` flips to `FULL`. Second, the order's provisional total is computed: each garment's `estimate_line_cents` is computed from its declared measurements, and the order's `estimate_total_cents` is set to the sum of the estimate line prices of all garments on the order (none are lost at schedule time). Because every line is already rounded to whole cents, the estimate total is a plain integer sum with no further rounding.

The per-garment line price is computed as follows, using the declared measurements at this estimate stage. For a `WASH_FOLD` garment, the weight in grams is converted to kilograms by dividing by 1000; the first 5 kilograms are priced at 400 cents per kilogram, and any weight beyond the first 5 kilograms is priced at 300 cents per kilogram, so a garment at or under 5 kilograms is simply its kilogram weight times 400 cents, and a heavier garment is 5 kilograms times 400 cents plus the excess kilograms times 300 cents. For a `DRY_CLEAN` garment, the base is the piece count times 900 cents per piece. For an `ALTERATION` garment, the base is the piece count times the line's `alteration_fee_cents`. After the base is formed, a subscriber discount applies only to `DRY_CLEAN` and `ALTERATION` lines and never to `WASH_FOLD`: when the order belongs to an active subscription, the base for those two service types is multiplied by one minus the plan's `dryclean_discount_pct`. Then, if the order is a rush order and the plan does not waive rush, the line is multiplied by the rush surcharge factor of 1.25; for a pay-as-you-go order with no subscription, treat the discount as zero and apply the rush surcharge whenever `rush` is set. Finally the line is rounded to whole cents using round-half-up; this rounded integer is the line price. At the estimate stage this value is written to the garment's `estimate_line_cents`.

### 3.4. Pickup, Intake Logging, and the SLA Clock

A `DispatchAgent` marks a scheduled order as picked up, moving it from `SCHEDULED` to `PICKED_UP`; the order must be in `SCHEDULED`, or the request is rejected with `ERR_INVALID_ORDER_STATE`. Picking up the order starts the SLA clock: the order's `ready_by_utc` is set to the current server time plus the standard SLA duration, or plus the rush SLA duration when the order is a rush order. The standard service-level target is the longer turnaround and the rush target is the shorter one; both are fixed durations in hours applied from the moment of pickup. The garments remain in `INTAKE_PENDING` at pickup, awaiting the plant to log their measured values.

At the plant, a `PlantOperator` logs intake for each garment, moving it from `INTAKE_PENDING` to `INTAKE_LOGGED`. Intake logging requires the parent order to be in `PICKED_UP`, or the request is rejected with `ERR_ORDER_NOT_PICKED_UP`. The operator records the plant-measured values from the request: `actual_weight_grams` for wash-fold garments and `actual_piece_count` for dry-clean and alteration garments. A wash-fold garment must be logged with `actual_weight_grams` greater than zero, and a dry-clean or alteration garment must be logged with `actual_piece_count` greater than zero; a missing or zero measurement inconsistent with the garment's service type is rejected with `ERR_INVALID_INTAKE_MEASUREMENT` at HTTP 422.

### 3.5. Cleaning, Quality Control, and the Rework Loop

Once every garment on a picked-up order has been logged, a `PlantOperator` starts processing, moving the order from `PICKED_UP` to `IN_PROCESSING`. This requires the order to be in `PICKED_UP` (otherwise `ERR_INVALID_ORDER_STATE`) and every garment on the order to be in `INTAKE_LOGGED`; if any garment has not been logged, the request is rejected with `ERR_GARMENTS_NOT_LOGGED`. Starting processing carries every garment from `INTAKE_LOGGED` to `CLEANING` as a system-driven child transition.

The operator finishes cleaning garments individually. Finishing a garment moves it from `CLEANING` to `CLEANED` and requires the garment to be in `CLEANING`, or the request is rejected with `ERR_GARMENT_NOT_CLEANING`. On finish, the garment's `final_line_cents` is recomputed using the same line-pricing rule described in Section 3.3 but driven by the plant-measured actual values — `actual_weight_grams` for wash-fold and `actual_piece_count` for dry-clean and alteration — rather than the declared values; the subscriber discount and rush surcharge are applied identically, and the result is rounded to whole cents with round-half-up and written to `final_line_cents`. A garment that has been marked lost contributes nothing to the final pricing.

A cleaned garment can be sent back for a rewash, moving it from `CLEANED` back to `CLEANING`. Rewash requires the garment to be in `CLEANED` (otherwise `ERR_GARMENT_NOT_CLEANED`) and the parent order to be in either `IN_PROCESSING` or `QC_HOLD` (otherwise `ERR_INVALID_ORDER_STATE`). If the parent order is in `QC_HOLD` when a garment is rewashed, the order must be reopened to processing before the garment can be re-finished. This is the per-garment side of the cyclic rework relationship `CLEANED → CLEANING → CLEANED`.

When all garments have reached a terminal cleaning outcome, the operator places the order on quality-control hold, moving it from `IN_PROCESSING` to `QC_HOLD`. This requires the order to be in `IN_PROCESSING` (otherwise `ERR_INVALID_ORDER_STATE`) and every garment to be in either `CLEANED` or `LOST`; if any garment is neither cleaned nor lost, the request is rejected with `ERR_GARMENTS_NOT_CLEANED`. Entering `QC_HOLD` recomputes the order's `final_total_cents` as the sum of the `final_line_cents` of all garments on the order that are not lost — lost garments are excluded entirely — and this sum of already-rounded integer line prices receives no further rounding. Entering `QC_HOLD` also recomputes the order's `risk_flag` from the accumulated severity of stain and damage notes, as described in Section 3.8.

From `QC_HOLD` the operator has two ways forward. The first is to reopen processing, moving the order from `QC_HOLD` back to `IN_PROCESSING`. Reopening requires the order to be in `QC_HOLD` (otherwise `ERR_INVALID_ORDER_STATE`) and either that at least one garment has been moved from `CLEANED` to `CLEANING` (a rewash) since the order entered `QC_HOLD`, or that the caller explicitly requests rework by setting `rework_requested`; if neither condition holds, the request is rejected with `ERR_NO_REWORK_REQUESTED`. Reopening clears `final_total_cents` back to 0 — it will be recomputed the next time the order returns to `QC_HOLD`. This completes the order-level cyclic rework relationship `IN_PROCESSING → QC_HOLD → IN_PROCESSING`.

### 3.6. Passing QC, Invoicing, Dispatch, and Delivery

The second way forward from `QC_HOLD` is to pass quality control, moving the order from `QC_HOLD` to `READY`. Passing requires the order to be in `QC_HOLD` (otherwise `ERR_INVALID_ORDER_STATE`) and every non-lost garment to be in `CLEANED`; if any non-lost garment is not cleaned, the request is rejected with `ERR_GARMENTS_NOT_CLEANED`. Passing QC sets in motion several effects. Every non-lost garment is carried from `CLEANED` to `PACKED` as a system-driven child transition. A draft **invoice** is created for the order, recording the order's `final_total_cents` as its `gross_cents`. The invoice begins in `DRAFT` status.

The invoice's monetary fields are computed in a fixed waterfall at the moment of draft creation. The `gross_cents` is the order's `final_total_cents`. For a subscriber order, the `subscription_credit_cents` covered by wash-fold inclusion is computed first (see the subscription-billing rule below) and is otherwise zero for a non-subscriber order; the amount remaining after the subscription credit is the gross minus the subscription credit, floored at zero. Against that remainder the customer's store credit is applied: `wallet_applied_cents` is the smaller of the remaining amount and the customer's available `wallet_credit_cents`. The `amount_due_cents` is then the remaining amount minus the wallet applied, floored at zero. At draft creation the `wallet_applied_cents` is reserved by debiting it from the customer's `wallet_credit_cents`; this reservation is restored if the invoice is later voided and is retained once the invoice is issued or paid. The waterfall order is fixed: subscription credit first, then wallet credit, then the amount due.

The subscription-billing computation that produces `subscription_credit_cents` for a subscriber order is evaluated in a strict order so its self-referential dependency is well defined. First, the wash-fold grams attributable to this order are summed: the total of `actual_weight_grams` across the order's garments whose `service_type` is `WASH_FOLD` and whose status is not lost. Second, the subscriber's prior cycle usage is read from `cycle_wash_fold_grams_used` before this order is added. Third, the remaining inclusion is the plan's `included_wash_fold_grams` minus that prior usage, floored at zero. Fourth, the grams this order can cover is the smaller of this order's wash-fold grams and the remaining inclusion. Fifth, the `subscription_credit_cents` is the covered grams converted to kilograms (divided by 1000) times the tier-1 wash-fold rate of 400 cents per kilogram — inclusion is always valued at the tier-1 rate and never the tier-2 rate — rounded once with round-half-up. Sixth and last, the subscriber's `cycle_wash_fold_grams_used` is advanced to its prior value plus this order's wash-fold grams. Reading prior usage before the write and advancing it after is what makes the credit well defined.

A `DispatchAgent` then dispatches delivery, moving the order from `READY` to `OUT_FOR_DELIVERY` and booking a stop on the delivery leg. Dispatch requires the order to be in `READY` (otherwise `ERR_INVALID_ORDER_STATE`). The chosen delivery window must have `window_kind` `DELIVERY` and a `zone_code` equal to the customer's `zone_code`, or the request is rejected with `ERR_WINDOW_ZONE_MISMATCH`. The delivery window must have spare capacity — its `booked_stops` strictly less than its `stop_capacity` — or the booking is rejected with `ERR_WINDOW_FULL`. The delivery window's `start_utc` must be at or after the order's `ready_by_utc`, or the request is rejected with `ERR_DELIVERY_BEFORE_READY`. And if the order's `handoff_method` is `LOCKER`, there must already exist a locker assignment for this order in either `OCCUPIED` or `RESERVED` status, or the request is rejected with `ERR_NO_LOCKER_ASSIGNED`. On a successful dispatch the delivery window's `booked_stops` increases by one (flipping its `status` to `FULL` if that reaches `stop_capacity`), and the order's invoice moves from `DRAFT` to `ISSUED`; the invoice amounts were already finalized at draft, so no recompute and no further wallet debit occur at issuance.

Finally a `DispatchAgent` confirms delivery, moving the order from `OUT_FOR_DELIVERY` to `DELIVERED`, the order's terminal happy-path state; the order must be in `OUT_FOR_DELIVERY`, or the request is rejected with `ERR_INVALID_ORDER_STATE`. On confirmation, if the handoff method is `LOCKER` the order's locker assignment moves from `OCCUPIED` to `RELEASED`, and the invoice moves from `ISSUED` to `PAID` — the amount due is settled from the previously reserved wallet credit, the plan inclusion, and the remainder marked paid.

### 3.7. Cancellation and Its Unwinding

A `Customer` (or a `PlatformAdmin`) may cancel an order at any point in its working life — that is, from `CREATED`, `SCHEDULED`, `PICKED_UP`, `IN_PROCESSING`, `QC_HOLD`, or `READY`. Cancellation is forbidden once the order is `OUT_FOR_DELIVERY`, `DELIVERED`, or already `CANCELLED`; an attempt in any of those states is rejected with `ERR_INVALID_ORDER_STATE`. Cancellation carries `expected_order_version`, which must match the order's current `version` or the request is rejected with `ERR_STALE_ORDER_VERSION` at HTTP 412. A successful cancel moves the order to `CANCELLED`, its terminal cancelled state, and increments the order's `version` by one.

Cancellation unwinds every reservation the order made. If a pickup stop was booked, the pickup window's `booked_stops` is decreased by one, and if that window was `FULL` it returns to `OPEN`. If a delivery stop was booked, the delivery window's `booked_stops` is decreased by one, and if it was `FULL` it returns to `OPEN`. Any locker assignment for this order that is `RESERVED` or `OCCUPIED` is moved to `RELEASED`, freeing its compartment. Any `DRAFT` invoice for this order is voided, moving to `VOID`: voiding restores the reserved `wallet_applied_cents` back to the customer's `wallet_credit_cents`, and for a subscriber order it reverses the `cycle_wash_fold_grams_used` increment that the QC-pass billing made. The garments themselves remain where they are — no packing transition is applied on cancel — but the order is closed.

### 3.8. Stain and Damage Notes, Risk Scoring, and the Order Risk Flag

During processing a `PlantOperator` may log a **garment note** recording a stain or damage observation. A note carries the annotated `garment_id`, a `note_kind` of either `STAIN` or `DAMAGE`, a `severity` integer between 1 and 10 inclusive that weights its contribution to risk, a free-text `description`, and a system-recorded `logged_by_role` capturing the role that recorded the note (the plant operator). A garment note is an immutable event record, so it carries only `id` and `created_at` and never an `updated_at` or `version`.

Each logged note has two immediate effects. First, it contributes provisionally to the customer's running `risk_score`: the note's `severity` is added to the owning customer's `risk_score`. Second, it feeds the order's `risk_flag`: the system sums the `severity` across all notes attached to any garment of the order, and sets `risk_flag` to true when that severity sum is at least the order-risk threshold of 12, and false otherwise — a severity sum of exactly 12 sets the flag, since the comparison is at-or-above the threshold, not strictly above it. The order's `risk_flag` is recomputed both when a note is logged and when the order enters `QC_HOLD`.

The customer's `risk_score` is a forward-accumulating index, floored at 0 and never decreased by these forward actions. Logging a note adds the note's `severity` immediately. Marking a garment lost adds a fixed 15 points for the lost garment. Settling a claim adds a fixed 25 points on top of any earlier note contributions. The risk index is never reset by these events; once a customer's `risk_score` reaches the customer-block threshold of 100, the next attempt to create or schedule an order for that customer is gated and rejected with `ERR_CUSTOMER_BLOCKED`, though the score itself is not reset.

A `PlantOperator` may mark a garment lost while the order is in processing, moving the garment to `LOST` from `INTAKE_LOGGED`, `CLEANING`, or `CLEANED`. Marking lost requires the garment to be in one of those three statuses (otherwise `ERR_GARMENT_NOT_LOSABLE`) and the parent order to be in `IN_PROCESSING` or `QC_HOLD` (otherwise `ERR_INVALID_ORDER_STATE`). A lost garment is excluded from the order's final total and becomes eligible as the subject of a garment-level claim; marking it lost adds 15 points to the owning customer's `risk_score`. `LOST` and `PACKED` are the two terminal garment states.

### 3.9. Locker Assignments and Compartment Conflicts

When an order will be handed off via a locker, a `PlatformAdmin` or `DispatchAgent` reserves a compartment by creating a **locker assignment**. It is created with the `order_id` whose finished bag will occupy the compartment, the `locker_id` of the bank, a `compartment_index` identifying which compartment is occupied (between 1 and the locker's `compartment_count` inclusive), an inclusive `hold_start_utc`, and an exclusive `hold_end_utc` that must be later than `hold_start_utc` (otherwise `ERR_INVALID_INTERVAL`). A new assignment begins in `RESERVED` status.

A new assignment must not collide with another assignment already holding the same compartment. The system rejects a new assignment whose occupation interval overlaps that of any existing non-terminal assignment in the same compartment of the same locker, where the comparison extends each existing occupation by the locker's `hold_buffer_minutes` turnaround buffer so that two bags in one compartment are separated by at least that cleaning buffer; a collision is reported as `ERR_LOCKER_COMPARTMENT_CONFLICT`. Route-window contention, by contrast, is governed purely by the `booked_stops`-versus-`stop_capacity` capacity count described earlier and not by interval geometry.

The assignment lifecycle is driven by a `DispatchAgent`. Occupying a reserved compartment moves the assignment from `RESERVED` to `OCCUPIED`; this requires the assignment to be in `RESERVED` (otherwise `ERR_INVALID_ASSIGNMENT_STATE`) and the parent order to be in `READY` (otherwise `ERR_INVALID_ORDER_STATE`). Releasing an occupied compartment moves the assignment from `OCCUPIED` to `RELEASED` and requires the assignment to be in `OCCUPIED` (otherwise `ERR_INVALID_ASSIGNMENT_STATE`); this same release also happens automatically when the parent order's delivery is confirmed. Expiring an assignment moves it from `RESERVED` or `OCCUPIED` to `EXPIRED` and requires the assignment to be in one of those two statuses (otherwise `ERR_INVALID_ASSIGNMENT_STATE`) and the current server time to be at or after the assignment's `hold_end_utc` (otherwise `ERR_HOLD_NOT_EXPIRED`). `RELEASED` and `EXPIRED` are the terminal assignment states.

### 3.10. Lost-Item Claims: Filing, Adjudication, Appeals, and Settlement

A `Customer` (or a `PlatformAdmin`) files a lost-item **claim** against an order. A claim carries the `order_id` it is filed against, a `subject_kind` of either `ORDER` (the whole order) or `GARMENT` (one garment), an optional `garment_id`, a `declared_value_cents` replacement value of at least one cent, and `expected_order_version`. Claim subject integrity is enforced: when `subject_kind` is `GARMENT` the `garment_id` must be present and must name a garment whose `order_id` equals the claim's `order_id`; when `subject_kind` is `ORDER` the `garment_id` must be absent. A subject inconsistency is rejected with `ERR_CLAIM_SUBJECT_MISMATCH` at HTTP 422. As described in Section 2.6, the `expected_order_version` must match the order's current `version`, or the filing is rejected with `ERR_STALE_ORDER_VERSION` at HTTP 412. A new claim begins in `SUBMITTED` status with `settlement_cents` 0 and `appeal_count` 0.

A `ClaimsAdjuster` works the claim. Opening an investigation moves it from `SUBMITTED` to `INVESTIGATING` and requires it to be in `SUBMITTED`, or the request is rejected with `ERR_INVALID_CLAIM_STATE`. From `INVESTIGATING` the adjuster may approve or reject. Approving moves the claim from `INVESTIGATING` to `APPROVED` and requires it to be in `INVESTIGATING` (otherwise `ERR_INVALID_CLAIM_STATE`); additionally, for a garment-subject claim the referenced garment must be in `LOST`, or the approval is rejected with `ERR_CLAIM_GARMENT_NOT_LOST`. Approving computes the claim's `settlement_cents` via the settlement waterfall described below. Rejecting moves the claim from `INVESTIGATING` to `REJECTED`, requires it to be in `INVESTIGATING` (otherwise `ERR_INVALID_CLAIM_STATE`), and sets `settlement_cents` to 0.

A rejected claim may be appealed or finally denied. Appealing — performed by the `Customer` or a `PlatformAdmin` — moves the claim from `REJECTED` back to `INVESTIGATING`, requires it to be in `REJECTED` (otherwise `ERR_INVALID_CLAIM_STATE`), requires `appeal_count` to be strictly less than the maximum allowed appeals (otherwise `ERR_APPEAL_LIMIT_REACHED`), and increments `appeal_count` by one; this is the cyclic appeal relationship `REJECTED → INVESTIGATING`. Finalizing a denial — performed by a `ClaimsAdjuster` — moves the claim from `REJECTED` to `DENIED_FINAL`, requires it to be in `REJECTED` (otherwise `ERR_INVALID_CLAIM_STATE`), and requires `appeal_count` to have reached the maximum allowed appeals (otherwise `ERR_APPEAL_LIMIT_NOT_REACHED`). The maximum number of appeals a claim may exhaust before it can be finally denied bounds the `appeal_count`; once that bound is reached no further appeal is permitted and final denial becomes available. `SETTLED` and `DENIED_FINAL` are the two terminal claim states.

An approved claim is settled by a `ClaimsAdjuster`, moving it from `APPROVED` to `SETTLED`; it must be in `APPROVED`, or the request is rejected with `ERR_INVALID_CLAIM_STATE`. Settling credits the computed `settlement_cents` to the owning customer's `wallet_credit_cents` and adds 25 points to that customer's `risk_score`.

The settlement amount is computed at approval as a capped, depreciated, ceiling-bounded waterfall. First, the declared value is capped at a per-item cap of 20000 cents: the working amount is the smaller of `declared_value_cents` and 20000 cents. Second, that capped amount is depreciated by 20 percent — the working amount is multiplied by one minus 0.20 and rounded once with round-half-up. Third, an aggregate per-order ceiling is applied: the system sums the `settlement_cents` of all other claims on the same order that are in `APPROVED` or `SETTLED` status (excluding this claim), and the remaining ceiling is the per-order payout ceiling of 30000 cents minus that already-paid total, floored at zero. Fourth, the claim's `settlement_cents` is the smaller of the depreciated amount and the remaining ceiling.

### 3.11. Reading Resources and the Test Clock

All collections are readable. Customers and orders may be listed with filters; for example, customers may be filtered by `zone_code`, route windows by `zone_code` and `window_kind`, lockers by `zone_code`, subscriptions by `customer_id` and `plan_id`, orders by `customer_id`, `subscription_id`, `pickup_window_id`, `delivery_window_id`, and `status`, garment notes by `garment_id`, locker assignments by `order_id` and `locker_id`, and claims by `order_id`, `garment_id`, and `status`. An order's invoice is retrieved through the order, and garments are listed and fetched under their owning order. All list reads honor the pagination and sort rules of Sections 2.3.

For deterministic testing of SLA targets and locker-hold expiry, a `PlatformAdmin` may set the server's logical clock to a supplied instant via the field `to_iso8601`; this capability simply sets the server's current UTC time and returns no resource body. SLA computation at pickup and the hold-expiry check at assignment expiry both read this logical clock.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/subscription-plans` | Create a subscription plan | PlatformAdmin |
| GET | `/subscription-plans` | List subscription plans | PlatformAdmin, Customer, DispatchAgent, PlantOperator, ClaimsAdjuster |
| GET | `/subscription-plans/{planId}` | Get a subscription plan | PlatformAdmin, Customer, DispatchAgent, PlantOperator, ClaimsAdjuster |
| POST | `/customers` | Register a customer | PlatformAdmin |
| GET | `/customers` | List customers (filterable by zone) | PlatformAdmin, DispatchAgent, ClaimsAdjuster |
| GET | `/customers/{customerId}` | Get a customer | PlatformAdmin, Customer, DispatchAgent, ClaimsAdjuster |
| POST | `/customers/{customerId}/block` | Administratively block a customer | PlatformAdmin |
| POST | `/subscriptions` | Create a subscription for a customer on a plan | PlatformAdmin, Customer |
| GET | `/subscriptions` | List subscriptions (filterable) | PlatformAdmin, Customer |
| GET | `/subscriptions/{subscriptionId}` | Get a subscription | PlatformAdmin, Customer |
| POST | `/subscriptions/{subscriptionId}/change-plan` | Change the plan of a subscription (OCC-guarded) | PlatformAdmin, Customer |
| POST | `/subscriptions/{subscriptionId}/cancel` | Cancel a subscription (OCC-guarded) | PlatformAdmin, Customer |
| POST | `/route-windows` | Create a pickup or delivery route window | PlatformAdmin, DispatchAgent |
| GET | `/route-windows` | List route windows (filterable by zone/kind) | PlatformAdmin, Customer, DispatchAgent |
| GET | `/route-windows/{windowId}` | Get a route window | PlatformAdmin, Customer, DispatchAgent |
| POST | `/lockers` | Create a locker bank | PlatformAdmin, DispatchAgent |
| GET | `/lockers` | List lockers (filterable by zone) | PlatformAdmin, DispatchAgent |
| GET | `/lockers/{lockerId}` | Get a locker | PlatformAdmin, DispatchAgent |
| POST | `/orders` | Create an order in CREATED state | PlatformAdmin, Customer |
| GET | `/orders` | List orders | PlatformAdmin, Customer, DispatchAgent, PlantOperator |
| GET | `/orders/{id}` | Get an order | PlatformAdmin, Customer, DispatchAgent, PlantOperator, ClaimsAdjuster |
| POST | `/orders/{id}/garments` | Add a garment line to a CREATED order | PlatformAdmin, Customer |
| GET | `/orders/{id}/garments` | List garments of an order | PlatformAdmin, Customer, DispatchAgent, PlantOperator, ClaimsAdjuster |
| GET | `/orders/{id}/garments/{garmentId}` | Get a garment | PlatformAdmin, Customer, DispatchAgent, PlantOperator, ClaimsAdjuster |
| POST | `/orders/{id}/schedule` | Schedule pickup; reserve pickup stop; compute estimate | PlatformAdmin, Customer |
| POST | `/orders/{id}/pickup` | Mark order picked up; set ready-by SLA | DispatchAgent |
| POST | `/orders/{id}/garments/{garmentId}/log-intake` | Record plant-measured weight/pieces for a garment | PlantOperator |
| POST | `/orders/{id}/start-processing` | Begin processing; move logged garments to cleaning | PlantOperator |
| POST | `/orders/{id}/garments/{garmentId}/finish-clean` | Finish cleaning a garment; compute final line price | PlantOperator |
| POST | `/orders/{id}/garments/{garmentId}/rewash` | Send a cleaned garment back to cleaning | PlantOperator |
| POST | `/orders/{id}/garments/{garmentId}/mark-lost` | Mark a garment lost during processing | PlantOperator |
| POST | `/orders/{id}/garments/{garmentId}/notes` | Log a stain/damage note on a garment | PlantOperator |
| GET | `/garment-notes` | List garment notes | PlatformAdmin, PlantOperator, ClaimsAdjuster |
| GET | `/garment-notes/{noteId}` | Get a garment note | PlatformAdmin, PlantOperator, ClaimsAdjuster |
| POST | `/orders/{id}/qc-hold` | Move order to QC hold; compute final total + risk flag | PlantOperator |
| POST | `/orders/{id}/reopen-processing` | Reopen processing from QC hold | PlantOperator |
| POST | `/orders/{id}/qc-pass` | Pass QC; pack garments; create DRAFT invoice | PlantOperator |
| POST | `/orders/{id}/dispatch-delivery` | Dispatch delivery; reserve delivery stop; issue invoice | DispatchAgent |
| POST | `/orders/{id}/confirm-delivery` | Confirm delivery; settle invoice; release locker | DispatchAgent |
| POST | `/orders/{id}/cancel` | Cancel a non-terminal order (OCC-guarded) | PlatformAdmin, Customer |
| GET | `/orders/{id}/invoice` | Get the order's invoice | PlatformAdmin, Customer, DispatchAgent |
| POST | `/locker-assignments` | Reserve a locker compartment for a READY order's bag | PlatformAdmin, DispatchAgent |
| GET | `/locker-assignments` | List locker assignments | PlatformAdmin, DispatchAgent |
| GET | `/locker-assignments/{assignmentId}` | Get a locker assignment | PlatformAdmin, DispatchAgent |
| POST | `/locker-assignments/{assignmentId}/occupy` | Mark a reserved compartment occupied | DispatchAgent |
| POST | `/locker-assignments/{assignmentId}/release` | Release an occupied compartment | DispatchAgent |
| POST | `/locker-assignments/{assignmentId}/expire` | Expire an assignment past its hold-end | DispatchAgent |
| POST | `/claims` | File a lost-item claim against an order (OCC-guarded) | PlatformAdmin, Customer |
| GET | `/claims` | List claims | PlatformAdmin, ClaimsAdjuster, Customer |
| GET | `/claims/{claimId}` | Get a claim | PlatformAdmin, ClaimsAdjuster, Customer |
| POST | `/claims/{claimId}/investigate` | Open investigation on a claim | ClaimsAdjuster |
| POST | `/claims/{claimId}/approve` | Approve a claim; compute settlement | ClaimsAdjuster |
| POST | `/claims/{claimId}/reject` | Reject a claim | ClaimsAdjuster |
| POST | `/claims/{claimId}/appeal` | Appeal a rejected claim | PlatformAdmin, Customer |
| POST | `/claims/{claimId}/finalize-denial` | Finally deny a rejected claim that exhausted appeals | ClaimsAdjuster |
| POST | `/claims/{claimId}/settle` | Settle an approved claim; credit wallet; bump risk | ClaimsAdjuster |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock for deterministic tests | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_INTERVAL` | 400 Bad Request |
| `ERR_SERVICE_TYPE_FIELD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_SUBJECT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_LOCKER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_GARMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_NO_GARMENTS` | 409 Conflict |
| `ERR_ORDER_NOT_PICKED_UP` | 409 Conflict |
| `ERR_GARMENTS_NOT_LOGGED` | 409 Conflict |
| `ERR_GARMENTS_NOT_CLEANED` | 409 Conflict |
| `ERR_NO_REWORK_REQUESTED` | 409 Conflict |
| `ERR_DELIVERY_BEFORE_READY` | 409 Conflict |
| `ERR_NO_LOCKER_ASSIGNED` | 409 Conflict |
| `ERR_GARMENT_NOT_CLEANING` | 409 Conflict |
| `ERR_GARMENT_NOT_CLEANED` | 409 Conflict |
| `ERR_GARMENT_NOT_LOSABLE` | 409 Conflict |
| `ERR_INVALID_INTAKE_MEASUREMENT` | 422 Unprocessable Entity |
| `ERR_INVALID_CLAIM_STATE` | 409 Conflict |
| `ERR_CLAIM_GARMENT_NOT_LOST` | 409 Conflict |
| `ERR_APPEAL_LIMIT_REACHED` | 409 Conflict |
| `ERR_APPEAL_LIMIT_NOT_REACHED` | 409 Conflict |
| `ERR_INVALID_SUBSCRIPTION_STATE` | 409 Conflict |
| `ERR_INVALID_ASSIGNMENT_STATE` | 409 Conflict |
| `ERR_LOCKER_COMPARTMENT_CONFLICT` | 409 Conflict |
| `ERR_HOLD_NOT_EXPIRED` | 409 Conflict |
| `ERR_WINDOW_ZONE_MISMATCH` | 409 Conflict |
| `ERR_WINDOW_FULL` | 409 Conflict |
| `ERR_CUSTOMER_BLOCKED` | 403 Forbidden |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 Precondition Failed |
