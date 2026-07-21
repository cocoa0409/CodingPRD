# Lighting & Fan Showroom API — Product Requirements Document

## 1. Introduction

The Lighting & Fan Showroom API is the operational backbone for a specialty retailer that sells configurable ceiling fans and decorative lighting to both walk-in retail customers and professional trade accounts. A single fixture is rarely sold "as shown": customers pick finishes, blade spans, downrods, glass, and control options, and each choice shifts both the price and the electrical load of the piece. The platform must therefore turn a base catalog model plus a set of chosen options into a precisely priced, precisely configured line, and then carry that line through quoting, deposit and settlement payments, supplier special-ordering, delivery, professional installation, energy rebates, and returns.

Two audiences pull on the system at once. Sales-floor staff assemble and quote orders and file returns and rebate claims; back-of-house fulfillment staff run supplier orders, deliveries, and install crews; interior designers operating under a trade account act on their own orders and design consultations at a negotiated discount; and a store manager sits above all of them as a superset operator who approves returns, rebates, and design plans, adjusts credit, and controls the logical clock used for lead-time and grace-period accounting. Because trade credit is committed at confirmation and released on completion or cancellation, and because rebate budgets and truck and installer capacity are finite shared resources, the system's correctness depends on disciplined state machines, compensating side effects, and exact integer-cent arithmetic.

This document specifies the complete contract: the global conventions every endpoint obeys, the business rules and lifecycles that govern each entity, the full endpoint surface, and the catalogue of error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. Domain-specific workflow detail lives in Section 3.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or the role is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `ShowroomAssociate`, `FulfillmentCoordinator`, `Designer`, and `StoreManager`. When an authenticated caller invokes an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

The four roles differ in how `X-User-ID` binds to persisted data. When `X-User-Role` is `ShowroomAssociate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. When `X-User-Role` is `FulfillmentCoordinator`, `X-User-ID` is likewise an opaque operator identifier with no entity binding. When `X-User-Role` is `StoreManager`, `X-User-ID` is again an opaque operator identifier; the store manager is a hierarchical-override operator authorized on every endpoint in the system. When `X-User-Role` is `Designer`, however, `X-User-ID` is the `id` of the acting `TradeAccount`; ownership checks on any resource that references a `TradeAccount` compare the resource's `trade_account_id` to `X-User-ID`. A `Designer` may act only on resources belonging to their own account, and only while that account is `ACTIVE`; acting on a resource they do not own, or from an account that is not `ACTIVE`, is rejected with `ERR_ACCOUNT_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp, `created_at`, in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every resource is assigned a server-minted `id` formatted as a UUID with no type prefix. Each resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when it was created. Resources that can be modified after creation additionally carry an `updated_at` timestamp — refreshed on every mutation to the resource — and an integer `version` that starts at 1 and increments by one on every mutation. All entities in this system are mutable and therefore carry the full quartet of `id`, `created_at`, `updated_at`, and `version`.

Whenever a derived or system-managed field changes on a resource — for example when an `Order`'s pricing estimates are recomputed, when a `TradeAccount`'s `available_credit_cents` shifts, or when an `Installer`'s `active_referral_count` moves — that change is a mutation: it refreshes `updated_at` and increments `version` on the affected resource. When one operation reconciles several resources at once, each resource is mutated independently and each independently bumps its own `updated_at` and `version`.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents; there are no fractional cents. Where a calculation multiplies an integer-cent amount by a fractional rate — a trade discount percentage or a rebate rate — the product is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). Additive and subtractive combinations of cent amounts are exact and require no rounding. Whole-day differences between two timestamps are computed by taking the floor of the elapsed time measured in days, discarding any partial day.

### 2.6. Optimistic Concurrency on Quoting

Producing a quote for an order is guarded by optimistic concurrency control on the order's `version`. A quote request must carry `expected_order_version`, and this field is required — it is not optional. The server compares `expected_order_version` against the target order's current `version`. If they match, the quote proceeds; if the order's `version` has advanced since the client last observed it — because another writer added a line or re-quoted the order in the meantime — then `expected_order_version` is stale and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from superseding a quote it computed against an order state it never saw. Because a re-quote legitimately supersedes a prior quote, the concurrency check is the only thing standing between two quote attempts; the version comparison reduces the supersede to a stale-version guard. No other endpoint in the system takes a version field; only quoting is version-checked.

### 2.7. Cascading State Consistency

Several operations mutate more than one resource. When an order is cancelled, every one of its order lines that is not already in a terminal line state is set to `CANCELLED`. When the cancelled order was `CONFIRMED`, the cancellation additionally releases the order's committed trade credit back to the account, transitions every non-terminal `SpecialOrder` belonging to that order to `CANCELLED`, and voids every `SCHEDULED` `DeliveryJob` belonging to that order by moving it to `VOIDED`. Voiding a delivery job in turn withdraws every install referral tied to that job that is still in `REFERRED` or `SCHEDULED`, moving each to `WITHDRAWN` and decrementing the relevant installer's active-referral tally. These chained effects are applied immediately and consistently as part of the triggering operation; each affected resource records its own mutation.

The system also propagates state upward. When a delivery job is delivered, its parent order — if `CONFIRMED` — advances to `COMPLETED`, which releases that order's committed credit. When a return reaches its refunded state and every line of the order has become `RETURNED` or `CANCELLED`, the order's payment axis advances from `SETTLED` to `REFUNDED`. These upward transitions are performed by the server without a separate client request against the parent.

### 2.8. Reference Validation Order and Check Precedence

For any request that names a resource in its URL path, the server validates that path-referenced resource exists before doing anything else with the body; a missing path resource yields `ERR_NOT_FOUND`. For creation requests whose body references foreign entities — a `trade_account_id`, `fixture_model_id`, `order_id`, `order_line_id`, `installer_id`, `delivery_truck_id`, `delivery_job_id`, or `rebate_program_id` — each referenced entity must exist, or the request is rejected with `ERR_FK_NOT_FOUND`.

When several checks could apply to one request, they are evaluated in a fixed precedence so that the reported error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of the path resource (`ERR_NOT_FOUND`), then existence of body foreign keys (`ERR_FK_NOT_FOUND`), then structural validity of the request body — required fields present and enum and type values valid (`ERR_INVALID_REQUEST`). Only after all of these pass does the server evaluate stateful and business rules: the quote concurrency check (`ERR_STALE_VERSION`), the draft-only guard on adding lines (`ERR_ORDER_NOT_DRAFT`), the generic "resource is not in a state that permits this transition" guard (`ERR_INVALID_STATE`), and then the domain-specific referential, temporal, safety, and fiscal rules described in Section 3. Within that business tier the ordering is: the special-order confirmation guard and the delivery-creation order-state guard (`ERR_ORDER_NOT_CONFIRMED`); the install-schedule delivery-readiness guard (`ERR_DELIVERY_NOT_READY`); the installer overlap guard (`ERR_INSTALLER_UNAVAILABLE`); the truck buffer guard (`ERR_TRUCK_WINDOW_CONFLICT`); the rebate eligibility guard (`ERR_NO_ELIGIBLE_ITEMS`); the rebate budget guard (`ERR_REBATE_BUDGET_EXCEEDED`); the return-eligibility guard (`ERR_LINE_NOT_RETURNABLE`); the credit-sufficiency guard (`ERR_INSUFFICIENT_CREDIT`); and finally the designer ownership-and-active guard (`ERR_ACCOUNT_FORBIDDEN`). For a delivery-job creation specifically, the installer and truck temporal guards precede the order-state guard, so a truck window conflict surfaces as `ERR_TRUCK_WINDOW_CONFLICT` before the order-not-confirmed condition is examined.

### 2.9. Trade Credit, Spend, and Tier Governance

A `TradeAccount` carries a store-issued credit ceiling, `credit_limit_cents`, and a live `available_credit_cents` derived from it. Available credit equals `credit_limit_cents` minus the sum of `committed_credit_cents` across all of that account's orders whose `fulfillment_status` is `CONFIRMED`. Available credit is recomputed whenever an order is confirmed, cancelled, or completed, and whenever the account is read, so a reader always sees the current figure.

An account also accrues `annual_spend_cents`: the sum of `total_final_cents` over that account's orders whose `payment_status` is `SETTLED` and whose `settled_at` falls within the trailing 365 days of the logical clock. From annual spend the account derives a `tier` and a `discount_pct`. The `tier` is `GOLD` when `annual_spend_cents` is at least 5,000,000 cents (fifty thousand dollars), `SILVER` when it is at least 2,000,000 cents (twenty thousand dollars) but below the gold threshold, and `STANDARD` otherwise; the threshold comparisons are inclusive. The `discount_pct` follows the tier: `STANDARD` earns 0.00, `SILVER` earns 0.08, and `GOLD` earns 0.15. Spend and tier are recomputed immediately after each settlement payment posts. An account's `status` is one of `ACTIVE`, `SUSPENDED`, or `CLOSED`, and is adjusted only by a store manager.

### 2.10. Scheduling Capacity and Buffer Protocols

Two shared physical resources — delivery trucks and install crews — are protected by temporal rules. Each `DeliveryTruck` has a `capacity_units` describing how many fixture units it can carry, defaulting to 20. Delivery windows on one truck are closed intervals `[window_start, window_end]`, and any two windows on the same truck that are not `VOIDED` must be separated by at least a mandatory turnaround gap of `BUFFER_MINUTES`; a proposed window that sits closer than that buffer to an existing non-voided window on the same truck is rejected with `ERR_TRUCK_WINDOW_CONFLICT`. Each `Installer` has a `daily_capacity` (defaulting to 3) and a running `active_referral_count`. Install appointment windows are half-open intervals `[appointment_start, appointment_end)`: two appointments for the same installer may not overlap, though exact adjacency where one ends at the instant the next begins is permitted; a scheduling attempt that overlaps an existing `SCHEDULED` referral for the same installer is rejected with `ERR_INSTALLER_UNAVAILABLE`.

## 3. Business Logic & Workflows

### 3.1. Catalog and Account Setup

Before any selling happens, a store manager stocks the catalog and stands up the shared resources. A fixture model is created with a base SKU code `sku_base`, a `category` chosen from `CEILING_FAN`, `CHANDELIER`, `PENDANT`, `SCONCE`, or `RECESSED`, a `base_price_cents` list price for the unconfigured fixture, and a `base_wattage` describing the fixture's baseline electrical load. Two boolean attributes gate downstream behavior: `energy_star`, which marks the model as ENERGY STAR certified and is a prerequisite for rebate eligibility, and `special_order_only`, which marks a model as never in stock so that any line built from it always requires supplier fulfillment. A `supplier_lead_days` value records the default supplier lead time in days for special orders of the model. The model also carries an `options` array; each entry is a configuration option with an `option_id`, a `group` drawn from `FINISH`, `BLADE_SPAN`, `DOWNROD`, `GLASS`, or `CONTROL`, a human `label`, a `price_delta_cents` that adjusts price when the option is chosen, a `wattage_delta` that adjusts electrical load, and a `sku_suffix` appended to the base SKU when the option is selected.

The manager also creates the trade accounts, opening each with a `business_name`, a `contact_email`, and an optional `credit_limit_cents` ceiling (defaulting to zero). A freshly created account begins at `STANDARD` tier with a `discount_pct` of 0.00 and its `available_credit_cents` equal to its `credit_limit_cents`. Later the manager may adjust an account's `credit_limit_cents` or move its `status` among `ACTIVE`, `SUSPENDED`, and `CLOSED`; adjusting the ceiling triggers a recomputation of `available_credit_cents`. The manager likewise creates installers (each with a `name`, a `service_area`, and an optional `daily_capacity`), delivery trucks (each with a `name` and optional `capacity_units`), and energy rebate programs (each with a `name`, a `rebate_rate`, a `wattage_ceiling`, and a funded `budget_total_cents`; a new program's `budget_remaining_cents` starts equal to its `budget_total_cents`).

### 3.2. Opening an Order and Configuring Lines

A sales associate, a store manager, or a designer opens an order by supplying a `customer_name` and, for a trade order, a `trade_account_id`; a retail order leaves `trade_account_id` null. A new order begins with `fulfillment_status` of `DRAFT` on its fulfillment axis and `payment_status` of `UNPAID` on its independent payment axis, and all of its estimate and final pricing figures start at their defaults. A designer opening an order may do so only against their own account, and only while that account is `ACTIVE`.

Lines may be added only while the order's `fulfillment_status` is `DRAFT`; attempting to add a line to an order in any other fulfillment state is rejected with `ERR_ORDER_NOT_DRAFT`. A line is added by naming the `fixture_model_id`, a `quantity` (which must be at least 1), and an optional `selected_option_ids` array — the subset of the fixture's option identifiers chosen for this configuration. Every identifier in `selected_option_ids` must be one of the fixture's own `options[].option_id` values; a quantity below 1, a bad enum, or an option id that is not part of the fixture is rejected with `ERR_INVALID_REQUEST`. On creation the line's derived fields are computed. Its `configured_sku` is formed by taking the fixture's `sku_base` and appending the `sku_suffix` of each selected option, with the suffixes concatenated in the order the options are declared in the fixture's `options` array (not in the order they were selected). Its `unit_price_cents` is the fixture's `base_price_cents` plus the sum of the `price_delta_cents` of each selected option. Its `is_special_order` flag is copied from the fixture's `special_order_only`. Each line also records the `order_id` it belongs to, and its `line_status` starts at `ACTIVE` and can later become `RETURNED` or `CANCELLED`.

### 3.3. Quoting and Confirming

Once lines exist, the order is quoted. Quoting recomputes the order's provisional pricing and, on the fulfillment axis, moves a `DRAFT` order to `QUOTED`; a `QUOTED` order may be quoted again, remaining `QUOTED` while the new quote supersedes the prior one. Both forms require the order to currently be in the state they act on and both require the concurrency token described earlier: the request carries `expected_order_version`, which must equal the order's current `version`, failing which the quote is rejected with `ERR_STALE_VERSION`. A successful quote increments the order's `version` by one.

The provisional pricing works as follows. The `subtotal_estimate_cents` is the sum, over every `ACTIVE` line of the order, of that line's `unit_price_cents` multiplied by its `quantity`. A discount percentage is then resolved: for a trade order it is the account's current `discount_pct` as observed at quote time, and for a retail order (no `trade_account_id`) it is zero. The raw discount is that percentage applied to the subtotal, rounded half-up to the nearest cent. The `discount_estimate_cents` is the smaller of that raw discount and a hard cap of 200,000 cents (two thousand dollars) — the discount can never exceed that cap regardless of tier or order size. The `total_estimate_cents` is `subtotal_estimate_cents` minus `discount_estimate_cents`. The estimate includes every `ACTIVE` line present at the moment of the quote and reflects the tier observed at that moment.

Confirming an order acts on a `QUOTED` order and advances it to `CONFIRMED`. For a trade order, confirmation is permitted only when the account's `available_credit_cents` is at least the order's `total_estimate_cents`; if available credit falls short the confirmation is rejected with `ERR_INSUFFICIENT_CREDIT`. On success the order's `committed_credit_cents` is set to its `total_estimate_cents`, which debits the account's available credit by that amount, and the order's `version` increments by one. When the order later completes or is cancelled, that committed credit is released back to zero, restoring the account's availability.

### 3.4. Payments, Settlement, and Tier Recomputation

The payment axis moves independently of fulfillment. A payment request names a `kind` — either `DEPOSIT` or `SETTLEMENT` — and an `amount_cents`. A deposit is accepted only when the order's `payment_status` is `UNPAID` and its `fulfillment_status` is either `QUOTED` or `CONFIRMED`; it advances the payment axis from `UNPAID` to `DEPOSIT_PAID` and adds `amount_cents` to the order's running `amount_paid_cents`. A settlement is accepted when the order's `payment_status` is `UNPAID` or `DEPOSIT_PAID` and its `fulfillment_status` is `CONFIRMED`; it advances the payment axis to `SETTLED` from either prior state.

Settlement is where final pricing is locked. At settlement the system computes `subtotal_final_cents`, `discount_final_cents`, and `total_final_cents` using the same subtotal, tier-discount, and 200,000-cent cap logic as the estimate, but with two differences: the tier (and thus the discount percentage) is re-read at settlement time, so an account that has upgraded since the quote gets the better rate, and the subtotal is taken over the lines that are still `ACTIVE` at settlement, excluding any line that became `RETURNED` or `CANCELLED` after the quote. Settlement also adds `amount_cents` to `amount_paid_cents`, sets `settled_at` to the current logical-clock instant, and then folds `total_final_cents` into the account's `annual_spend_cents` before recomputing that account's `tier` and `discount_pct` from the updated spend.

### 3.5. Special Orders and Supplier Lead Times

Lines built from special-order-only fixtures — or any line needing supplier fulfillment — are tracked as special orders. A sales associate or store manager files one by naming the `order_id`, the `order_line_id` of the line requiring fulfillment, and a promised `supplier_lead_days`. The special order opens in `REQUESTED`. A fulfillment coordinator confirms it, which is allowed only while it is `REQUESTED` and only when the parent order named by its `order_id` has `fulfillment_status` of `CONFIRMED`; a parent that is not confirmed causes rejection with `ERR_ORDER_NOT_CONFIRMED`. Confirmation moves the special order to `CONFIRMED`, stamps `confirmed_at` with the current clock, and projects an `estimated_ready_date` equal to `confirmed_at` plus the promised `supplier_lead_days`.

Completing a confirmed special order moves it to `READY`, stamps `actual_ready_date` with the current clock, and computes `variance_days` as the whole-day floor of the difference between `actual_ready_date` and the projected `estimated_ready_date` — a positive variance meaning the supplier ran late and a negative one meaning early. A special order that is still `REQUESTED` or `CONFIRMED` when its parent order is cancelled is swept to `CANCELLED` by the cascade; `READY` and `CANCELLED` are terminal.

### 3.6. Design Consultations

Designers drive a lightweight review cycle for lighting plans. A designer or store manager opens a design consult against a `trade_account_id`, a `room_type` (for example a kitchen or great room), an optional `fee_cents` consultation fee, and an optional `order_id` if a plan is already tied to an order. The consult opens in `REQUESTED` with a `revision_count` of zero. Submitting the plan for review moves a `REQUESTED` consult to `IN_REVIEW`. From `IN_REVIEW` the designer may request a revision, which moves it to `REVISION` and increments `revision_count` by one; re-submitting after revising loops a `REVISION` consult back to `IN_REVIEW`. This review-and-revise cycle may repeat any number of times. Only a store manager may approve a consult, and only from `IN_REVIEW`, moving it to the terminal `APPROVED` state. Any of these moves attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

### 3.7. Delivery and Installation

Delivered fixtures ride trucks and are installed by crews, and both are booked by fulfillment coordinators (a store manager may also act). A delivery job is scheduled by naming the `order_id`, the `delivery_truck_id`, and a `window_start` and `window_end`. The window must be well-formed — a `window_end` at or before `window_start` is rejected with `ERR_VALIDATION` — and must respect the same-truck buffer described earlier, failing which it is rejected with `ERR_TRUCK_WINDOW_CONFLICT`. Creating a delivery job also requires the parent order to have advanced to `CONFIRMED` or `COMPLETED`; otherwise it is rejected with `ERR_ORDER_NOT_CONFIRMED`. A new job opens in `SCHEDULED`. Marking it delivered moves it to `DELIVERED` and bubbles the parent order from `CONFIRMED` to `COMPLETED`, which releases the order's committed credit. A `SCHEDULED` job caught by an order cancellation is instead moved to `VOIDED`.

Installation is arranged through referrals. Creating an install referral names the `order_id`, the `installer_id`, and the `delivery_job_id` on which the install depends; a new referral opens in `REFERRED` and increments the chosen installer's `active_referral_count` by one. Scheduling a referral requires it to be `REFERRED`, requires the linked delivery job identified by `delivery_job_id` to have reached `DELIVERED` (otherwise `ERR_DELIVERY_NOT_READY`), and requires the proposed appointment window not to overlap any other `SCHEDULED` referral for the same installer (otherwise `ERR_INSTALLER_UNAVAILABLE`); the window is supplied as `appointment_start` and `appointment_end` and is treated as half-open so back-to-back adjacency is allowed. Scheduling sets the appointment window and moves the referral to `SCHEDULED` but leaves `active_referral_count` unchanged, since the referral remains active. Completing a `SCHEDULED` referral moves it to `COMPLETED` and decrements the installer's `active_referral_count` by one. When a referral's delivery job is voided, any referral still in `REFERRED` or `SCHEDULED` is withdrawn to `WITHDRAWN`, and that withdrawal likewise decrements the installer's `active_referral_count` by one, restoring the crew's availability.

### 3.8. Returns, Restocking, and Refunds

Returns are filed against a single order line and adjudicated by a store manager. A sales associate or store manager files a return naming the `order_id`, the `order_line_id` being returned, and a `reason` drawn from `DAMAGE`, `DEFECTIVE`, `CHANGED_MIND`, or `WARRANTY`; the request opens in `REQUESTED`. Approval is permitted only while the return is `REQUESTED`, only when the parent order's `payment_status` is `DEPOSIT_PAID` or `SETTLED`, and only when the target line's `line_status` is still `ACTIVE`; a parent whose payment is in neither of those states, or a line no longer active, is rejected with `ERR_LINE_NOT_RETURNABLE`. Approving with an `adjudication` of `DENY` instead moves the return to the terminal `DENIED` state and has no financial effect.

A genuine approval computes the return's `restocking_fee_cents` and cascades. The line value is the line's `unit_price_cents` times its `quantity`. For a reason of `DAMAGE`, `DEFECTIVE`, or `WARRANTY` the restocking percentage is zero. For `CHANGED_MIND` the percentage depends on how long the customer has had the goods: the days since delivery are the whole-day floor of the difference between the current clock and the order's delivery window end (treated as zero if the order has no delivery), and if that count is at most 14 days the percentage is zero, otherwise it is 0.20. The `restocking_fee_cents` is the line value times that percentage, rounded half-up to whole cents. Approval also moves the target line's `line_status` from `ACTIVE` to `RETURNED` and recomputes the order's `subtotal_final_cents` and `total_final_cents` over the lines that remain `ACTIVE`. Refunding a return acts on an `APPROVED` return, moves it to `REFUNDED`, and sets `refund_cents` to the line value minus the `restocking_fee_cents`. If, once that line is returned, every line of the order is `RETURNED` or `CANCELLED`, the order's payment axis bubbles from `SETTLED` to `REFUNDED`.

### 3.9. Energy Rebates

Energy rebate claims let orders recover part of their spend on efficient fixtures. A sales associate or store manager submits a claim naming the `order_id` and the `rebate_program_id`. At submission the system determines each eligible line and computes the claim's `claimed_cents`. A line is eligible when its fixture's `energy_star` is true, when the line's effective wattage is at most the program's `wattage_ceiling`, and when the line is still `ACTIVE`. A line's effective wattage is the fixture's `base_wattage` plus the sum of the `wattage_delta` of each selected option on that line. A claim must have at least one eligible line; a claim with none is rejected with `ERR_NO_ELIGIBLE_ITEMS`. The `claimed_cents` is built by taking, for each eligible line, the line's `unit_price_cents` times its `quantity` times the program's `rebate_rate`, rounding that per-line amount half-up to whole cents, and then summing those rounded per-line amounts — the rounding is applied to each line before the sum, not to the total. A new claim opens in `SUBMITTED`.

Only a store manager adjudicates a claim. Approval requires the claim to be `SUBMITTED` and requires the program's `budget_remaining_cents` to be at least the claim's `claimed_cents`; an approval that would overdraw the program is rejected with `ERR_REBATE_BUDGET_EXCEEDED`. A successful approval moves the claim to `APPROVED` and debits the program's `budget_remaining_cents` by `claimed_cents`. Approving with an `adjudication` of `DENY` instead moves the claim to the terminal `DENIED` state with no budget effect. A claim that has been approved may later be voided, which moves it to `VOID` and restores the program's `budget_remaining_cents` by the same `claimed_cents`, compensating the earlier debit.

### 3.10. The Logical Clock

All lead-time, settlement, spend-window, and grace-period accounting reads a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-07-01T00:00:00Z` and never falls back to real time before it is set. A store manager may advance or set the clock by supplying a target instant `to_iso8601`; subsequent timestamps such as `settled_at`, `confirmed_at`, `actual_ready_date`, and the trailing-365-day spend window all read from this clock.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that read a resource or a list, and operations that modify or transition an existing resource, return `200 OK`. Every endpoint is additionally authorized for `StoreManager`, who holds override authority across the entire API; the roles listed below are the full set permitted for each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/trade-accounts` | Create a trade/designer account | StoreManager |
| GET | `/trade-accounts/{id}` | Read a trade account | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| PATCH | `/trade-accounts/{id}` | Adjust credit limit or status | StoreManager |
| POST | `/fixture-models` | Create a fixture model with config options | StoreManager |
| GET | `/fixture-models/{id}` | Read a fixture model | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/installers` | Create an installer | StoreManager |
| GET | `/installers/{id}` | Read an installer | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/delivery-trucks` | Create a delivery truck | StoreManager |
| POST | `/rebate-programs` | Create an energy rebate program | StoreManager |
| GET | `/rebate-programs/{id}` | Read a rebate program | ShowroomAssociate, StoreManager, FulfillmentCoordinator |
| POST | `/orders` | Create an order | ShowroomAssociate, StoreManager, Designer |
| GET | `/orders/{id}` | Read an order | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| GET | `/orders` | List/filter orders | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/orders/{id}/lines` | Add a configured line to a DRAFT order | ShowroomAssociate, StoreManager, Designer |
| GET | `/order-lines/{id}` | Read an order line | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| GET | `/order-lines` | List/filter order lines | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/orders/{id}/quote` | Generate/supersede a quote (OCC-guarded) | ShowroomAssociate, StoreManager, Designer |
| POST | `/orders/{id}/confirm` | Confirm a quoted order | ShowroomAssociate, StoreManager, Designer |
| POST | `/orders/{id}/cancel` | Cancel an order (cascade) | ShowroomAssociate, StoreManager |
| POST | `/orders/{id}/payments` | Record a deposit or settlement payment | ShowroomAssociate, StoreManager |
| POST | `/special-orders` | Create a special order for a line | ShowroomAssociate, StoreManager |
| GET | `/special-orders/{id}` | Read a special order | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| GET | `/special-orders` | List/filter special orders | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/special-orders/{id}/confirm` | Confirm a supplier order | FulfillmentCoordinator, StoreManager |
| POST | `/special-orders/{id}/complete` | Mark a supplier order ready | FulfillmentCoordinator, StoreManager |
| POST | `/design-consults` | Create a design consult | Designer, StoreManager |
| GET | `/design-consults/{id}` | Read a design consult | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| GET | `/design-consults` | List/filter design consults | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/design-consults/{id}/submit-review` | Submit a plan for review | Designer, StoreManager |
| POST | `/design-consults/{id}/request-revision` | Request a revision | Designer, StoreManager |
| POST | `/design-consults/{id}/approve` | Approve a design consult | StoreManager |
| POST | `/delivery-jobs` | Schedule a delivery | FulfillmentCoordinator, StoreManager |
| GET | `/delivery-jobs/{id}` | Read a delivery job | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| GET | `/delivery-jobs` | List/filter delivery jobs | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/delivery-jobs/{id}/deliver` | Mark a delivery delivered | FulfillmentCoordinator, StoreManager |
| POST | `/install-referrals` | Create an install referral | ShowroomAssociate, FulfillmentCoordinator, StoreManager |
| GET | `/install-referrals/{id}` | Read an install referral | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| GET | `/install-referrals` | List/filter install referrals | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/install-referrals/{id}/schedule` | Schedule an install appointment | FulfillmentCoordinator, StoreManager |
| POST | `/install-referrals/{id}/complete` | Complete an install referral | FulfillmentCoordinator, StoreManager |
| POST | `/return-requests` | File a return/damage/warranty request | ShowroomAssociate, StoreManager |
| GET | `/return-requests/{id}` | Read a return request | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| GET | `/return-requests` | List/filter return requests | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/return-requests/{id}/approve` | Approve or deny a return | StoreManager |
| POST | `/return-requests/{id}/refund` | Refund an approved return | StoreManager |
| POST | `/rebate-claims` | Submit an energy rebate claim | ShowroomAssociate, StoreManager |
| GET | `/rebate-claims/{id}` | Read a rebate claim | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| GET | `/rebate-claims` | List/filter rebate claims | ShowroomAssociate, StoreManager, Designer, FulfillmentCoordinator |
| POST | `/rebate-claims/{id}/approve` | Approve or deny a rebate claim | StoreManager |
| POST | `/rebate-claims/{id}/void` | Void an approved rebate claim | StoreManager |
| POST | `/_clock/set_current_utc` | Set the logical clock | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_ACCOUNT_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_NOT_DRAFT` | 409 |
| `ERR_ORDER_NOT_CONFIRMED` | 409 |
| `ERR_DELIVERY_NOT_READY` | 409 |
| `ERR_INSTALLER_UNAVAILABLE` | 409 |
| `ERR_TRUCK_WINDOW_CONFLICT` | 409 |
| `ERR_NO_ELIGIBLE_ITEMS` | 422 |
| `ERR_REBATE_BUDGET_EXCEEDED` | 409 |
| `ERR_LINE_NOT_RETURNABLE` | 409 |
| `ERR_INSUFFICIENT_CREDIT` | 402 |
| `ERR_VALIDATION` | 422 |
