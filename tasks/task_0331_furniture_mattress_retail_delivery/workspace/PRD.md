# Furniture & Mattress Retail Delivery API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Furniture & Mattress Retail Delivery API, the system of record for a furniture and mattress retailer that sells configurable merchandise and fulfills it through its own delivery fleet. The platform spans the full commercial arc of a sale: a sales associate builds an order out of configured product lines (chosen fabric and size, optional assembly and haul-away), the customer settles the order either by paying in full or through a financing or lease-to-own plan that must clear credit and affordability gates, a dispatcher schedules the order onto a delivery route within a truck's shift window and capacity, and — after delivery — the customer may file a return inside a product-dependent return window, optionally protected by a warranty plan.

Two ideas drive most of the business rules and deserve emphasis up front. First, an order carries **two independent status dimensions** — a payment dimension and a fulfillment dimension — that advance on separate axes and must never be conflated. Second, money is handled exclusively in integer **cents**, and every derived figure (line prices, order totals, financing schedules, refunds, protection premiums) is a server-computed value that the client may never set directly. The sections that follow define the global contract every endpoint obeys (Section 2) and then the domain workflows where the detailed rules live (Section 3), before summarizing the endpoint surface (Section 4) and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `SalesAssociate`, `StoreManager`, `DeliveryDispatcher`, and `Customer`. When a recognized role attempts an operation it is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

The four roles partition the work surface as follows. A `SalesAssociate` owns order intake and the front-line sales flow — creating customers and orders, configuring lines, applying for financing, taking payments, paying in full, and attaching protection plans. A `StoreManager` holds the override surface: managing the catalog, approving/declining/defaulting financing plans, approving/rejecting/refunding returns, closing delivered orders, and driving the test clock; a `StoreManager` may additionally perform any operation available to a `SalesAssociate` or a `DeliveryDispatcher`. A `DeliveryDispatcher` owns routing — creating routes, locking and completing them, and booking, dispatching, completing, or cancelling stops. A `Customer` is a self-service buyer.

Three of these roles — `SalesAssociate`, `StoreManager`, and `DeliveryDispatcher` — carry an opaque identity: when `X-User-Role` is one of them, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it — for example, the `sales_associate_user_id` written onto an `Order` at creation time is copied from the acting associate's `X-User-ID` — but it never compares that value to any entity's `id`. The `Customer` role is entity-backed: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`, and ownership checks compare a resource's customer foreign key against `X-User-ID`. Specifically, when a `Customer` files a return or lists a customer's orders or financing plans, the system verifies that the targeted customer (directly, or transitively via the order line's order) is the one identified by `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN_NOT_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is bounded to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific workflow states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Derived-Field Semantics

Every primary resource is server-minted and carries a system-generated `id` formatted as a UUID with no type prefix, along with a `created_at` timestamp expressed as an ISO 8601 UTC string with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at its initial value and increments by one on each mutation. The `Payment` resource is the sole exception: it is immutable after creation and therefore carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field.

Many fields are read-only and derived; clients never supply them. On an `Order`, the figures `merchandise_subtotal_cents`, `service_total_cents`, `order_total_cents`, `amount_refunded_cents`, and `earliest_schedulable_date` are all computed. On an `OrderLine`, `unit_config_price_cents`, `line_total_cents`, and `addon_fee_cents` are computed. On a `FinancingPlan`, `monthly_payment_cents`, `total_of_payments_cents`, `paid_to_date_cents`, `payoff_balance_cents`, and `payments_made_count` are computed, and `financed_principal_cents` and `customer_id` are filled in by the system. On a `Customer`, `open_financing_count` is read-only. Whenever a computed field changes as a side effect of an operation, that change is itself a mutation of the owning resource: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Monetary Precision and Rounding

All monetary amounts are integer cents. Where a calculation produces an intermediate fractional value (interest, tax, lease markup, protection premium, restocking fee, unearned-interest rebate), the result is rounded to a whole number of cents using the round-half-up convention — a fractional remainder of exactly one-half rounds up to the next cent. Several calculations are deliberately specified to round **once** at a named step on a combined base rather than rounding each component separately; the affected workflows in Section 3 state exactly where the single rounding falls. Two monthly-payment computations instead round **up to the next whole cent** (an integer ceiling) so that the scheduled installments always cover the financed total; those are likewise called out where they apply. Where every operand is already an integer number of cents, no rounding occurs.

### 2.6. The Two Status Dimensions of an Order

An `Order` advances along two independent axes that never share a value space. The **payment dimension**, `payment_status`, moves from `UNPAID` to either `PAID_IN_FULL` or `FINANCED`; both `PAID_IN_FULL` and `FINANCED` are settled states. The **fulfillment dimension**, `fulfillment_status`, moves from `DRAFT` to `CONFIRMED` to `SCHEDULED` to `DELIVERED` to `CLOSED`, with `CANCELLED` reachable from `DRAFT` or `CONFIRMED`; `CLOSED` and `CANCELLED` are terminal. A transition on one axis never implicitly moves the other — for example, paying in full settles the payment dimension while leaving `fulfillment_status` untouched. Each accepted transition on either axis increments the order's `version`. Several fulfillment transitions are driven not by a direct request on the order but by the system reacting to events on a related `DeliveryStop`; those bubble-up transitions are described in Section 3 and likewise increment the order's `version`.

### 2.7. Capacity, Scheduling Windows, and the Delivery Ledger

A `DeliveryRoute` represents one truck running one region on one calendar date, bounded by a shift window measured in minutes since midnight and a finite carrying capacity. The route's `committed_units` is a read-only running tally — the sum of `unit_load` over the stops on that route in `BOOKED` or `DISPATCHED` status — that starts at 0. Booking a stop adds to this tally and cancelling or completing a stop subtracts from it, so the route's available capacity is always reconciled in real time against the truck's `capacity_units`. A route progresses `OPEN` → `LOCKED` → `COMPLETED`: an `OPEN` route accepts new bookings, a `LOCKED` route refuses them, and `COMPLETED` is terminal. Stops and the route's capacity ledger move together; the precise arithmetic and the guards that protect a window from spilling outside its shift or colliding with a neighbor live in Section 3.

### 2.8. Cascade and Reconciliation Across Entities

Several operations mutate more than one entity in a single atomic step, and every secondary effect is mandatory, not optional. Cancelling an order cancels its active lines and declines any open financing plan. Refunding a return marks the covered line returned, voids that line's active protection plan, and advances the order's refund ledger. Approving a financing plan flips the order's payment dimension and bumps the customer's open-plan counter. Completing or cancelling a delivery stop adjusts the route's committed capacity and may move the order's fulfillment dimension. Each of these cascades, where it touches a second resource, refreshes that resource's `updated_at` and increments its `version` exactly as a direct mutation would. The individual cascades are specified in full within the workflow that triggers them.

### 2.9. Nested Resource Retrieval and Reference Resolution

Many read endpoints address a resource through a parent segment (for instance, listing the lines of an order, the stops of a route, or the payments of a financing plan), and several write endpoints reference parents and siblings by foreign key in the body. The system validates referenced resources left-to-right — path identifiers first, in the order they appear, then body foreign keys — and rejects the first identifier that does not resolve to an existing resource with `ERR_NOT_FOUND`. This ordering guarantees that a missing parent is reported before any child-level or business-level rule is evaluated.

These checks sit inside a fixed validation priority that every endpoint shares. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then — for the customer-owned actions of Section 2.1 — ownership (`ERR_FORBIDDEN_NOT_OWNER`), then existence of all referenced resources (`ERR_NOT_FOUND`), and then request-shape validation. Request-shape validation rejects a body that omits a required field, carries a value of the wrong type, supplies an out-of-range number, or names an enum value outside its allowed set, all with `ERR_INVALID_REQUEST`. Only after all of these pass does an endpoint evaluate its own domain-specific business rules described in Section 3.

### 2.10. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency guard so a client cannot act on a parent it has not freshly observed. Booking a delivery stop requires the request to include `expected_route_version` carrying the client's last-observed `version` of the target `DeliveryRoute`; if that value does not equal the route's current `version` — because another writer has booked or cancelled a stop and shifted the route's committed capacity since the client read it — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing a re-read before the client can overbook against a stale view of remaining capacity. Likewise, applying for a financing plan requires `expected_order_version` carrying the client's last-observed `version` of the target `Order`; if that value does not equal the order's current `version` — because the order total moved when a line was added or removed since the client read it — the application is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing a re-read so the plan does not snapshot a stale principal. These two endpoints are the only ones that take a version field; no other operation accepts or requires one.

## 3. Business Logic & Workflows

### 3.1. Catalog, Customers, and Order Intake

The catalog is curated by a `StoreManager`, who registers each `Product` with its `sku` (unique across the catalog), display `name`, and `category` — one of `SOFA`, `SECTIONAL`, `MATTRESS`, `BED_FRAME`, or `TABLE`. A product carries a `base_price_cents` (strictly greater than zero) and two option lists, `available_fabrics` and `available_sizes`; each option is an object with a `code` and a `surcharge_cents`, and every product's fabric list must include the `STANDARD` code at a `surcharge_cents` of 0. A product is flagged `is_special_order` (defaulting to false) when it is build-to-order; such a product also carries `lead_days` (a non-negative build time in days, defaulting to 0 and consulted only when `is_special_order` is true). The `protection_eligible` flag (defaulting to true) records whether warranty coverage may later be attached to lines of this product.

Customers are created at intake by a `SalesAssociate` or `StoreManager`. A `Customer` is recorded with `full_name`, `email` (unique across customers), and three figures that gate financing: `credit_score` (a FICO-style integer where 300 is the floor and 850 the ceiling — at least 300 and at most 850), `monthly_income_cents` (the stated gross monthly income, zero or greater), and `existing_monthly_obligations_cents` (existing recurring monthly debt, zero or greater, defaulting to 0 when omitted). The read-only `open_financing_count` is initialized to 0 at creation and thereafter tracks how many of this customer's financing plans sit in `CURRENT` or `PAST_DUE` status.

A sale begins when a `SalesAssociate` creates an `Order` for a customer, supplying the buyer's `customer_id` and optionally a `delivery_tier`. The order opens with `payment_status` of `UNPAID` and `fulfillment_status` of `DRAFT`, and its `sales_associate_user_id` is stamped from the acting associate's identity. The `delivery_tier` defaults to `THRESHOLD` and may instead be `WHITE_GLOVE`; it is an order-level default that is copied onto each stop at booking time and drives the per-order delivery fee.

### 3.2. Configuring Lines and the Merchandise Calculation

While an order remains in `DRAFT`, a `SalesAssociate` builds it up by adding configured lines and may remove them; both adding and removing a line are permitted only while the order's `fulfillment_status` is `DRAFT`, and any such attempt on a non-draft order is rejected with `ERR_ORDER_NOT_DRAFT`. Adding a line requires the parent `order_id`, the `product_id` being configured, the chosen `fabric_code` and `size_code`, and optionally a `quantity` (a whole number of at least 1, defaulting to 1), `add_assembly` (defaulting to false), and `add_haul_away` (defaulting to false). The chosen `fabric_code` must appear among the product's `available_fabrics` codes and the `size_code` among its `available_sizes` codes; a configuration naming a fabric or size the product does not offer is rejected with `ERR_INVALID_CONFIGURATION`. Removing a line sets that line's `status` to `CANCELLED` rather than deleting it.

Each line's price is computed as it is created or updated. The per-unit configured price, `unit_config_price_cents`, is the product's `base_price_cents` plus the surcharge of the chosen fabric (the `surcharge_cents` of the matching entry in `available_fabrics`) plus the surcharge of the chosen size (the `surcharge_cents` of the matching entry in `available_sizes`). The line's merchandise figure, `line_total_cents`, is that per-unit price multiplied by `quantity`. Because every operand is integer cents, these figures are exact and unrounded. A line's add-on fee, `addon_fee_cents`, accumulates two optional services: when `add_assembly` is set, an assembly charge of 4,900 cents per unit (4,900 multiplied by `quantity`) is added, and when `add_haul_away` is set, a haul-away charge of 3,500 cents per unit (3,500 multiplied by `quantity`) is added; when a flag is unset its contribution is zero. A freshly created line opens in `ACTIVE` status.

The order's `merchandise_subtotal_cents` is the sum of `line_total_cents` over the order's lines whose `status` is `ACTIVE` — lines that have been cancelled or returned are excluded. This subtotal is recomputed whenever a line is added or removed, on confirmation, and on pay-in-full.

### 3.3. Service Fees, Tax, and the Grand-Total Reconciliation

Beyond merchandise, every order carries a service total. The order's `service_total_cents` combines a single flat delivery fee chosen by the order's `delivery_tier` with the sum of the add-on fees across the order's active lines. The delivery fee is 19,900 cents when `delivery_tier` is `WHITE_GLOVE` and 7,900 cents when it is `THRESHOLD`. The add-on portion is the sum of `addon_fee_cents` over the order's `ACTIVE` lines. Thus `service_total_cents` equals the tier's delivery fee plus that add-on sum.

The grand total, `order_total_cents`, is reconciled in a pinned evaluation order to avoid a circular-looking dependency, and the order matters because tax is applied exactly once. First the system establishes `merchandise_subtotal_cents`, then `service_total_cents`. It then forms the taxable base as the sum of those two figures. Tax is then computed once on that combined base: the taxable base multiplied by 825 basis points (that is, multiplied by 825 and divided by 10,000), with the single round-half-up applied to that one product to land on whole cents. Finally, `order_total_cents` is the taxable base plus that tax. Tax is never computed component-by-component and then summed; it is computed once, on the combined base, after both subtotals are known.

When the order is confirmed, the system also sets `earliest_schedulable_date`. This is the calendar date of the order's creation (`created_at`, UTC date component) advanced by the largest `lead_days` found among the order's active special-order lines — that is, the maximum `lead_days` over active lines whose product has `is_special_order` set to true. If no active line is a special order, the advance is zero days. This field is null until the order has at least one line.

### 3.4. Settling the Order: Pay-in-Full and the Confirmation Gate

An order must be settled on its payment axis before it can be confirmed on its fulfillment axis. A `SalesAssociate` settles an unpaid order outright by paying it in full: the order must currently be `UNPAID` (otherwise `ERR_ALREADY_SETTLED`), must have at least one `ACTIVE` line (otherwise `ERR_EMPTY_ORDER`), and must have no financing plan in `PENDING_APPROVAL` or `CURRENT` status (otherwise `ERR_FINANCING_EXISTS`); on success, `payment_status` moves `UNPAID → PAID_IN_FULL` while the fulfillment dimension is untouched.

Confirming an order advances `fulfillment_status` from `DRAFT` to `CONFIRMED` and is performed by a `SalesAssociate`. Confirmation requires the order to be in `DRAFT` (otherwise `ERR_INVALID_STATE`), to hold at least one `ACTIVE` line (otherwise `ERR_EMPTY_ORDER`), and — crucially — to be already settled, meaning `payment_status` is `FINANCED` or `PAID_IN_FULL`; confirming an order still `UNPAID` is rejected with `ERR_ORDER_NOT_SETTLED`. On confirmation the system recomputes `order_total_cents`, `merchandise_subtotal_cents`, and `service_total_cents` to freeze the reference used by any later financing snapshot, sets `earliest_schedulable_date` as described above, and increments the order's `version`. Once an order is `CONFIRMED`, its lines may no longer be added to or removed.

### 3.5. Financing and Lease-to-Own

As an alternative to paying in full, an order may be financed. A `SalesAssociate` applies for a `FinancingPlan` against an order while that order is still `UNPAID` and has no existing plan in `PENDING_APPROVAL` or `CURRENT` status; an application against an already-settled order, or one that would duplicate an open plan, is rejected (the open-plan collision surfaces as `ERR_FINANCING_EXISTS`, an already-settled order as `ERR_ALREADY_SETTLED`). The application supplies the `order_id`, the `plan_type` — `INSTALLMENT` or `LEASE_TO_OWN` — and the `term_months`, and as described in Section 2.10 it must carry `expected_order_version` matching the order's current `version`. For an `INSTALLMENT` plan the `term_months` must be 6, 12, 24, or 36; for a `LEASE_TO_OWN` plan it must be 12 or 18. The new plan opens in `PENDING_APPROVAL`, copies the order's buyer into its own `customer_id`, and at this stage takes no principal snapshot. There is at most one active plan per order.

A `StoreManager` reviews a pending plan and either declines it or approves it. Declining moves the plan `PENDING_APPROVAL → DECLINED` (terminal) and increments its `version`. Approval is the heavily gated transition `PENDING_APPROVAL → CURRENT`, and its checks run in a pinned order so that the financed figures exist before the affordability gates are evaluated. First the plan snapshots `financed_principal_cents` as the order's current `order_total_cents`, version-pinned at this moment. Next the monthly schedule is computed (described below). Then three gates are evaluated in priority order: the credit gate first, then the debt-to-income gate, then the open-plan gate.

The **credit gate** requires the customer's `credit_score` to be at least the floor for the plan type — 640 for an `INSTALLMENT` plan, 600 for a `LEASE_TO_OWN` plan — and a shortfall is rejected with `ERR_CREDIT_TOO_LOW`. The **debt-to-income gate** requires that the customer's existing obligations plus this plan's payment stay within 43 percent of income; to avoid floating-point drift it is evaluated as an exact integer comparison: the sum of `existing_monthly_obligations_cents` and `monthly_payment_cents`, multiplied by 100, must be at most 43 multiplied by `monthly_income_cents`. A violation is rejected with `ERR_DTI_EXCEEDED`. The **open-plan gate** requires the customer's `open_financing_count` to be strictly fewer than 2 open plans; reaching that ceiling is rejected with `ERR_TOO_MANY_OPEN_PLANS`. When more than one gate would fail, the earliest in this order wins: a credit failure surfaces before a DTI failure, and a DTI failure before an open-plan failure. Approval also requires the order to be `UNPAID` with no other competing `CURRENT`/`PENDING_APPROVAL` plan, a collision surfaced as `ERR_ALREADY_SETTLED`, and the plan itself to be in `PENDING_APPROVAL` (otherwise `ERR_INVALID_STATE`).

On a successful approval the plan snapshot is locked, the order's `payment_status` is set to `FINANCED`, the customer's `open_financing_count` is incremented by one, and both the plan's `version` and the order's `version` are incremented.

The monthly schedule depends on `plan_type`. For an `INSTALLMENT` plan, the system applies simple add-on interest: it takes the principal multiplied by 1,200 basis points (that is, by 1,200 divided by 10,000), prorated by the term as `term_months` divided by 12, and rounds that interest half-up to whole cents; `total_of_payments_cents` is the principal plus that interest, and `monthly_payment_cents` is that total divided by `term_months`, rounded **up** to the next whole cent. For a `LEASE_TO_OWN` plan, no interest is computed; instead `total_of_payments_cents` is the principal multiplied by 13 and divided by 10 — a flat 1.30 times markup — rounded half-up to whole cents, and `monthly_payment_cents` is that total divided by `term_months`, again rounded **up** to the next whole cent. In both variants the monthly ceiling guarantees the installments cover the total.

### 3.6. Posting Payments and the Cyclic Plan Lifecycle

Once a plan is `CURRENT` it accumulates payments, and its lifecycle is cyclic: routine payments keep it `CURRENT`, a missed period can push it to `PAST_DUE`, a catch-up payment restores it to `CURRENT`, and a sufficient payment from either state pays it off. A `SalesAssociate` posts a payment by supplying an `amount_cents` (strictly greater than zero); the payment is appended as a `Payment` row whose `applied_period_index` — the 1-based monthly period it satisfies — is assigned in chronological order of `created_at` ascending. The `Payment` row references its `financing_plan_id`. After each accepted payment the system recomputes `paid_to_date_cents` (the sum of accepted payment amounts, starting at 0), `payments_made_count` (the count of accepted payments, starting at 0), and `payoff_balance_cents`, and increments the plan's `version`.

The effect of a payment on plan status depends on its size relative to the payoff balance **before** the payment is applied. An ordinary in-schedule payment posted against a `CURRENT` plan whose `amount_cents` is below the current `payoff_balance_cents` keeps the plan `CURRENT` (a self-loop). A payment posted against a `PAST_DUE` plan whose `amount_cents` is below the payoff balance restores the schedule only if it brings `paid_to_date_cents` up to at least `monthly_payment_cents` multiplied by the number of periods elapsed; if it does, the plan moves `PAST_DUE → CURRENT`, and if it falls short the catch-up is rejected with `ERR_INSUFFICIENT_CATCH_UP`. From either `CURRENT` or `PAST_DUE`, a payment whose `amount_cents` is at least the current `payoff_balance_cents` pays the plan off in one shot, moving it to `PAID_OFF`: the final payment is appended, `paid_to_date_cents` and `payments_made_count` are recomputed, `payoff_balance_cents` is set to 0, the order's `payment_status` is set to `PAID_IN_FULL`, the customer's `open_financing_count` is decremented by one, and both the plan's `version` and the order's `version` are incremented. A payment that is meant as a payoff but falls below the payoff balance is rejected with `ERR_PAYMENT_BELOW_PAYOFF`.

A `StoreManager` may flag a current plan as overdue, moving it `CURRENT → PAST_DUE`, but only when a period is genuinely owed — that is, when `payments_made_count` is fewer than the number of periods elapsed; if nothing is actually owed the request is rejected with `ERR_NO_PERIOD_DUE`. A `StoreManager` may also declare default on a past-due plan, moving it `PAST_DUE → DEFAULTED` (terminal), which decrements the customer's `open_financing_count` by one and increments the plan's `version`. The number of periods elapsed is the count of whole calendar months from the plan's activation date (the date it entered `CURRENT`) to the current clock, advancing month by month so that a partial month does not count, capped at `term_months`. A period is owed for the past-due flag exactly when `payments_made_count` is below that elapsed count, and a catch-up is sufficient exactly when `paid_to_date_cents` reaches at least `monthly_payment_cents` multiplied by that elapsed count.

The payoff balance is recomputed on every accepted payment, and its convention is pinned per plan type. For an `INSTALLMENT` plan, early payoff rebates unearned interest by the sum-of-digits method: with periods remaining defined as `term_months` minus `payments_made_count`, the unearned interest is the total interest multiplied by periods-remaining and multiplied by (periods-remaining plus one), divided by the product of `term_months` and (`term_months` plus one), rounded half-up to whole cents; the payoff balance is then `total_of_payments_cents` minus `paid_to_date_cents`, minus that unearned-interest rebate. For a `LEASE_TO_OWN` plan, the markup is never rebated: the payoff balance is simply `total_of_payments_cents` minus `paid_to_date_cents`. In both cases the payoff balance is floored at zero — it never goes negative.

### 3.7. Protection Plans

A `SalesAssociate` may attach warranty coverage to a configured line by creating a `ProtectionPlan`, supplying the covered `order_line_id`, a `tier`, and a `coverage_years`. The `tier` is either `BASIC` (covering manufacturing defects only) or `PREMIUM` (also covering accidental damage). For a `BASIC` plan the `coverage_years` must be 1 or 2; for a `PREMIUM` plan it must be 3 or 5. A protection plan may be attached only to a line whose product has `protection_eligible` set to true and that does not already carry an active plan — there is at most one active plan per line — and a violation of either condition is rejected with `ERR_PROTECTION_NOT_ALLOWED`. The new plan opens in `ACTIVE` status.

The plan's `premium_cents` is computed once at creation. The system takes the covered line's `line_total_cents`, multiplies it by the tier's annual rate — 650 basis points (that is, 650 divided by 10,000) for a `PREMIUM` plan, or 300 basis points for a `BASIC` plan — and multiplies by `coverage_years`, applying a single round-half-up across the whole product to land on whole cents. A protection plan's `status` later becomes `VOIDED` if the covered line is returned, as described in the return workflow.

### 3.8. Scheduling Deliveries: Routes and Stops

A `DeliveryDispatcher` lays out the fleet by creating a `DeliveryRoute` with a `region_code`, a `service_date` (the calendar date the route runs, at UTC midnight), a shift window given as `shift_start_minute` and `shift_end_minute` (each minutes since midnight, with the start at least 0 and strictly less than the end, and the end at most 1,440), and a `capacity_units` (strictly greater than zero). The route opens `OPEN` with `committed_units` at 0. A dispatcher locks an open route, moving it `OPEN → LOCKED` (which is what makes it refuse new bookings), and later completes a locked route, moving it `LOCKED → COMPLETED`; completion is allowed only when every stop on the route is already in `COMPLETED` or `CANCELLED` status, and an attempt to complete a route with stops still `BOOKED` or `DISPATCHED` is rejected with `ERR_STOPS_UNRESOLVED`. Each route transition increments the route's `version`.

Booking a stop ties an order to a route. A `DeliveryDispatcher` books a `DeliveryStop` by supplying the `route_id`, the `order_id` being delivered, the requested `window_start_minute` and `window_end_minute`, and the `expected_route_version` guard. At booking the stop copies its `service_tier` from the order's `delivery_tier`, computes its `unit_load` as the sum of `quantity` over the order's non-cancelled lines at that moment, and opens in `BOOKED` status. Booking is subject to a sequence of guards. The route must be `OPEN`; booking on a route that is not open is rejected with `ERR_ROUTE_NOT_OPEN`. The requested window must lie inside the route's shift — the start at or after `shift_start_minute`, the end after the start and at or before `shift_end_minute` — and a `WHITE_GLOVE` stop additionally requires a service buffer to fit after the window before the next stop; a window that falls outside the shift, or whose white-glove buffer would run past the shift end, is rejected with `ERR_WINDOW_OUT_OF_SHIFT`. The requested window, including the white-glove buffer where it applies, must not overlap any existing `BOOKED` or `DISPATCHED` stop on the same route; an overlap is rejected with `ERR_STOP_OVERLAP`. The route's `service_date` must be on or after the order's `earliest_schedulable_date`, so that special-order lead time is honored; an earlier service date is rejected with `ERR_LEAD_TIME_NOT_MET`. Finally, the booking must not push the route's `committed_units` plus this stop's `unit_load` above the route's `capacity_units`; exceeding capacity is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`. On a successful booking, the route's `committed_units` is increased by the stop's `unit_load`, and — because this is the first stop booked for the order — the order's `fulfillment_status` moves `CONFIRMED → SCHEDULED`; both the route's `version` and the order's `version` are incremented. There is at most one `BOOKED`/`DISPATCHED` stop per order.

### 3.9. Dispatching, Completing, and Cancelling Stops

Once the route is locked, a `DeliveryDispatcher` dispatches a booked stop, moving it `BOOKED → DISPATCHED`; dispatch requires the stop to be `BOOKED` and the route to be `LOCKED`, and dispatching against a route that is not locked is rejected with `ERR_ROUTE_NOT_LOCKED`. Completing a dispatched stop moves it `DISPATCHED → COMPLETED` and is the event that delivers the order: it bubbles the order's `fulfillment_status` from `SCHEDULED` to `DELIVERED`, stamps the covered lines' delivery date as this completion time (the baseline the return window is measured against), decrements the route's `committed_units` by the stop's `unit_load`, and increments both the stop's `version` and the order's `version`. A dispatcher may instead cancel a still-booked stop, moving it `BOOKED → CANCELLED`; cancellation decrements the route's `committed_units` by the stop's `unit_load`, and — when this was the order's only active stop — bubbles the order's `fulfillment_status` back from `SCHEDULED` to `CONFIRMED`, incrementing both the stop's `version` and the order's `version`.

### 3.10. Returns, Refunds, and the Return Window

After delivery, a return may be filed against a delivered line. A `Customer` (or a `SalesAssociate` or `StoreManager` acting on their behalf) files a `ReturnRequest` by supplying the covered `order_line_id` and a `reason` — one of `DAMAGED`, `DEFECTIVE`, or `CHANGED_MIND`. On filing, the system copies the line's order into the request's own `order_id`, stamps `filed_on` with the current clock, and opens the request in `REQUESTED` status. When a `Customer` files the return, ownership is enforced as described in Section 2.1, with a non-owner rejected by `ERR_FORBIDDEN_NOT_OWNER`.

A `StoreManager` resolves a request. Approval is the gated transition `REQUESTED → APPROVED`: it requires the request to be `REQUESTED` (otherwise `ERR_INVALID_STATE`), the covered line to still be `ACTIVE` (a line that is not active is rejected with `ERR_LINE_NOT_RETURNABLE`), and the filing to fall inside the return window. The window deadline is the line's delivery date advanced by a category-dependent number of days — 100 days when the covered product's `category` is `MATTRESS`, and 30 days otherwise — and the gate passes when `filed_on` is on or before that deadline, with the boundary inclusive (a filing exactly on the deadline still passes). A late filing is rejected with `ERR_RETURN_WINDOW_CLOSED`. On approval the system computes the refund figures and increments the request's `version`.

The refund is computed on the merchandise value only — service fees are never refundable. The gross is the covered line's `line_total_cents`. When the `reason` is `DAMAGED` or `DEFECTIVE`, the `restocking_fee_cents` is 0; when the `reason` is `CHANGED_MIND`, the `restocking_fee_cents` is the gross multiplied by 1,500 basis points (that is, by 1,500 divided by 10,000), rounded half-up to whole cents. The `refund_amount_cents` is the gross minus the restocking fee.

A `StoreManager` disburses an approved refund, moving the request `APPROVED → REFUNDED`. This is the cascade that settles the ledger: the covered line's `status` is set to `RETURNED`, that line's protection plan (if it is `ACTIVE`) is moved to `VOIDED`, the order's `amount_refunded_cents` is increased by this request's `refund_amount_cents`, and both the request's `version` and the order's `version` are incremented. A `StoreManager` may instead reject a return: a `REQUESTED → REJECTED` rejection closes the request terminally, and an `APPROVED → REJECTED` rejection is a revert path that may be taken before any refund is disbursed and fires no ledger or line side effects. Both rejection paths require the request to be in the matching source state (otherwise `ERR_INVALID_STATE`) and increment the request's `version`.

### 3.11. Cancelling and Closing Orders

A `SalesAssociate` may cancel an order while its `fulfillment_status` is `DRAFT` or `CONFIRMED`, provided the order has no `DeliveryStop` in `BOOKED` or `DISPATCHED` status; an active stop blocks the cancellation with `ERR_STOP_ACTIVE`, and a cancellation attempted from any other state is rejected with `ERR_INVALID_STATE`. Cancelling moves `fulfillment_status` to `CANCELLED` and runs two mandatory cascades: every `ACTIVE` `OrderLine` is set to `CANCELLED` (each line refreshing its `updated_at`), and any `FinancingPlan` on the order in `PENDING_APPROVAL` or `CURRENT` status is set to `DECLINED` with the customer's `open_financing_count` recomputed accordingly. The order's `version` is incremented.

At the end of the line, a `StoreManager` closes a delivered order, moving `fulfillment_status` from `DELIVERED` to `CLOSED`. Closing requires the order to be `DELIVERED` (otherwise `ERR_INVALID_STATE`) and requires that no `ReturnRequest` on the order is still open — that is, none is in `REQUESTED` or `APPROVED` status; an outstanding open return blocks closing with `ERR_OPEN_RETURNS_EXIST`. Closing increments the order's `version`.

### 3.12. The Test Clock

Because return windows and special-order lead times turn on calendar dates, the system exposes an administrative test-driving capability, restricted to a `StoreManager`, that sets the server's notion of the current UTC time to a supplied `to_iso8601` instant. After the clock is set, every subsequently system-stamped timestamp — `filed_on` on new returns, the delivered-on baseline stamped at stop completion, and `created_at` on newly created rows — uses this clock, which lets the date-based return-window and lead-time gates be exercised deterministically.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition actions and the test-clock capability — return a `200 OK` status code. All endpoints require the authentication headers of Section 2.1, and authorization is enforced per the table below.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer (intake) | SalesAssociate, StoreManager |
| GET | `/customers/{id}` | Fetch a customer | SalesAssociate, StoreManager, Customer |
| GET | `/customers/{id}/orders` | List a customer's orders | SalesAssociate, StoreManager, Customer |
| GET | `/customers/{id}/financing-plans` | List a customer's financing plans | SalesAssociate, StoreManager, Customer |
| POST | `/products` | Create a catalog product | StoreManager |
| GET | `/products/{id}` | Fetch a product | SalesAssociate, StoreManager, Customer |
| GET | `/products/{id}/order-lines` | List order lines configured from a product | SalesAssociate, StoreManager |
| POST | `/orders` | Create a DRAFT order for a customer | SalesAssociate, StoreManager |
| GET | `/orders` | List orders, filterable by customer_id | SalesAssociate, StoreManager |
| GET | `/orders/{id}` | Fetch an order with computed totals | SalesAssociate, StoreManager, Customer |
| GET | `/orders/{id}/lines` | List an order's lines | SalesAssociate, StoreManager, Customer |
| GET | `/orders/{id}/financing-plans` | List financing plans for an order | SalesAssociate, StoreManager, Customer |
| GET | `/orders/{id}/delivery-stops` | List delivery stops for an order | SalesAssociate, StoreManager, DeliveryDispatcher, Customer |
| GET | `/orders/{id}/return-requests` | List return requests for an order | SalesAssociate, StoreManager, Customer |
| POST | `/orders/{id}/confirm` | Confirm a settled DRAFT order | SalesAssociate, StoreManager |
| POST | `/orders/{id}/pay-in-full` | Settle an order by paying in full | SalesAssociate, StoreManager |
| POST | `/orders/{id}/cancel` | Cancel a DRAFT/CONFIRMED order | SalesAssociate, StoreManager |
| POST | `/orders/{id}/close` | Close a delivered order | StoreManager |
| POST | `/order-lines` | Add a configured line to a DRAFT order | SalesAssociate, StoreManager |
| GET | `/order-lines/{id}` | Fetch a single configured line | SalesAssociate, StoreManager, Customer |
| DELETE | `/order-lines/{id}` | Remove a line from a DRAFT order | SalesAssociate, StoreManager |
| GET | `/order-lines/{id}/protection-plans` | List protection plans for a line | SalesAssociate, StoreManager, Customer |
| GET | `/order-lines/{id}/return-requests` | List return requests for a line | Customer, SalesAssociate, StoreManager |
| POST | `/financing-plans` | Apply for financing on an order | SalesAssociate, StoreManager |
| GET | `/financing-plans/{id}` | Fetch a financing plan with computed payoff | SalesAssociate, StoreManager, Customer |
| POST | `/financing-plans/{id}/approve` | Approve a pending financing plan | StoreManager |
| POST | `/financing-plans/{id}/decline` | Decline a pending financing plan | StoreManager |
| POST | `/financing-plans/{id}/mark-past-due` | Flag a current plan as past due | StoreManager |
| POST | `/financing-plans/{id}/default` | Declare default on a past-due plan | StoreManager |
| POST | `/financing-plans/{id}/payments` | Post a payment against a plan | SalesAssociate, StoreManager |
| GET | `/financing-plans/{id}/payments` | List payments for a plan | SalesAssociate, StoreManager, Customer |
| POST | `/delivery-routes` | Create a delivery route | DeliveryDispatcher, StoreManager |
| GET | `/delivery-routes/{id}` | Fetch a route with committed_units | DeliveryDispatcher, StoreManager, SalesAssociate |
| GET | `/delivery-routes/{id}/stops` | List stops on a route | DeliveryDispatcher, StoreManager, SalesAssociate |
| POST | `/delivery-routes/{id}/lock` | Lock a route to new bookings | DeliveryDispatcher, StoreManager |
| POST | `/delivery-routes/{id}/complete` | Complete a locked route | DeliveryDispatcher, StoreManager |
| POST | `/delivery-stops` | Book a delivery stop for an order on a route | DeliveryDispatcher, StoreManager |
| GET | `/delivery-stops/{id}` | Fetch a delivery stop | DeliveryDispatcher, StoreManager, SalesAssociate, Customer |
| POST | `/delivery-stops/{id}/dispatch` | Dispatch a booked stop | DeliveryDispatcher, StoreManager |
| POST | `/delivery-stops/{id}/complete` | Complete a dispatched stop | DeliveryDispatcher, StoreManager |
| POST | `/delivery-stops/{id}/cancel` | Cancel a booked stop | DeliveryDispatcher, StoreManager |
| POST | `/protection-plans` | Attach a protection plan to an order line | SalesAssociate, StoreManager |
| GET | `/protection-plans/{id}` | Fetch a protection plan | SalesAssociate, StoreManager, Customer |
| POST | `/return-requests` | File a return on a delivered order line | Customer, SalesAssociate, StoreManager |
| GET | `/return-requests/{id}` | Fetch a return request | Customer, SalesAssociate, StoreManager |
| POST | `/return-requests/{id}/approve` | Approve a return within the window | StoreManager |
| POST | `/return-requests/{id}/reject` | Reject a requested or approved return | StoreManager |
| POST | `/return-requests/{id}/refund` | Disburse refund for an approved return | StoreManager |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC time | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_CONFIGURATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EMPTY_ORDER` | 409 |
| `ERR_ORDER_NOT_DRAFT` | 409 |
| `ERR_ORDER_NOT_SETTLED` | 409 |
| `ERR_ALREADY_SETTLED` | 409 |
| `ERR_FINANCING_EXISTS` | 409 |
| `ERR_CREDIT_TOO_LOW` | 409 |
| `ERR_DTI_EXCEEDED` | 409 |
| `ERR_TOO_MANY_OPEN_PLANS` | 409 |
| `ERR_NO_PERIOD_DUE` | 409 |
| `ERR_INSUFFICIENT_CATCH_UP` | 409 |
| `ERR_PAYMENT_BELOW_PAYOFF` | 409 |
| `ERR_WINDOW_OUT_OF_SHIFT` | 422 |
| `ERR_STOP_OVERLAP` | 409 |
| `ERR_LEAD_TIME_NOT_MET` | 409 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 |
| `ERR_ROUTE_NOT_OPEN` | 409 |
| `ERR_ROUTE_NOT_LOCKED` | 409 |
| `ERR_STOPS_UNRESOLVED` | 409 |
| `ERR_STOP_ACTIVE` | 409 |
| `ERR_LINE_NOT_RETURNABLE` | 409 |
| `ERR_RETURN_WINDOW_CLOSED` | 409 |
| `ERR_PROTECTION_NOT_ALLOWED` | 409 |
| `ERR_OPEN_RETURNS_EXIST` | 409 |
| `ERR_STALE_VERSION` | 412 |
