# Sewing-Machine & Vacuum Sales/Service API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a specialty retailer that both sells and services household sewing machines and vacuum cleaners. A single storefront has to juggle an unusually wide spread of activities: it sells new and refurbished machines (often taking an old machine in trade), runs a repair bench that quotes and consumes spare parts, teaches customer classes, lends loaner units, sells recurring tune-up subscriptions, and places special orders for models it does not stock. Each of these lines of business keeps its own money — deposits, store credit, appraisals, invoices — and the store's staff expect all of it to reconcile against a single per-customer credit ledger.

The service exists to make that reconciliation trustworthy. Every price is computed by the server from fixed schedules and rates rather than typed in by hand, every state change that touches money is reversible in a way that conserves the ledger, and every safety concern (a recalled product, an overlapping loaner reservation, a double-booked class) is enforced before value changes hands. The API is consumed by four kinds of staff- and customer-facing clients, and because the store operates on immediate consistency, a caller always sees the effect of its write reflected in the very next read.

Because the pricing and scheduling logic is time-sensitive — warranty windows, subscription periods, late fees, proration — the system runs on a **logical clock** that tests and operators can advance deterministically. Nothing in the system reads wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If either header is missing, or if `X-User-Role` is not one of the four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles are `SalesAssociate`, `ServiceTech`, `StoreManager`, and `Customer`.

- When `X-User-Role` is `SalesAssociate`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The `SalesAssociate` is front-of-house staff who open and settle sales orders, loaner rentals, special orders, and subscriptions, and who act on behalf of customers for repair approvals, enrollments, and cancellations.
- When `X-User-Role` is `ServiceTech`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The `ServiceTech` runs the repair bench — diagnosis, parts, repair completion — and may redeem tune-ups.
- When `X-User-Role` is `StoreManager`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity. The `StoreManager` owns the catalog, inventory intake, recalls, class scheduling, manual credit adjustments, sale reversals, and subscription lapses.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a `Customer` compare that resource's `customer_id` to `X-User-ID`. Concretely, when a `Customer` approves or rejects a repair quote, cancels a class enrollment, or cancels a tune-up subscription, the acting `X-User-ID` must equal the owning `customer_id` of the target resource; otherwise the request is rejected with `ERR_FORBIDDEN` (HTTP 403). A `SalesAssociate` performing the same action on a customer's behalf is exempt from this ownership check.

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

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1 and no larger than 100. `offset` defaults to 0 and may be no smaller than 0. A `limit` or `offset` outside these bounds is rejected with `ERR_INVALID_PAGINATION` (HTTP 400). List results are always ordered by `created_at` ascending, with ties among records sharing the same `created_at` broken by creation order (earliest-created first); this same tie-break governs every other "earliest-created" / `created_at`-ascending ordering in this document (for example waitlist promotion in §3.6). The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching records before the page window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Resource Identity, Versioning, and Timestamps

Every persisted resource is assigned a server-minted `id`, a UUID string carrying no type prefix. Every resource also records `created_at`, the ISO 8601 UTC instant of its creation with three fractional digits. All entities in this system additionally carry `updated_at` (the ISO 8601 UTC instant of the last mutation, likewise with three fractional digits) and `version` (an integer that starts at 1 on creation and increments by 1 on every mutation of that resource). Whenever a rule below states that an operation "bumps the version" or "refreshes `updated_at`", it means the resource's `version` increases by one and its `updated_at` is set to the current logical instant.

A subtle but important consequence: an operation that mutates several entities advances the `version` and `updated_at` of **each** entity it touches, not only the entity named in the URL. Cascades described throughout §3 (a class cancellation refunding enrollees, a sale completion adjusting the buyer) each carry their own version bumps on the secondary entities.

### 2.5. The Logical Clock and Temporal Semantics

The service maintains a single logical clock that is the sole source of "now" for the entire system. At startup, before any clock call is made, the clock reads exactly `2026-07-01T00:00:00Z`; it never falls back to wall-clock time. An administrative test-driving capability sets the clock to a supplied instant provided as `to_iso8601`. Every time-dependent computation — subscription period boundaries, warranty expiry, subscription proration, and rental late fees — reads this logical clock as its notion of the present moment.

Temporal intervals in this system come in two flavors, and the distinction matters for boundary cases. Loaner rentals use **half-open** intervals `[start_at, due_at)` where the due instant is exclusive, so two rentals that merely touch at that endpoint do not conflict. Class sessions use **closed** intervals `[start_at, end_at]` with a mandatory separation buffer, so sessions that touch at their endpoints do conflict. These are elaborated in §3.5 and §3.6 respectively.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as whole integer cents. Wherever a computation introduces a fractional cent — a percentage-based tax, a percentage-based loyalty discount, a per-day proration, or a multiplier-based late fee — the result is rounded to the nearest whole cent using **round half up** (a value exactly halfway between two cents rounds to the larger). Rounding is applied exactly once per computed amount, at the point specified in each formula in §3; intermediate integer terms are not pre-rounded. Time-derived counts (billable rental days, days late, unused subscription days) are whole-number day counts obtained by taking the ceiling of a fractional-day quantity, as detailed per formula.

### 2.7. The Store-Credit Ledger

Each `Customer` carries a single running balance, `store_credit_cents`, that every line of business debits and credits. This ledger is the connective tissue of the system, and its guiding principle is **conservation under reversal**: any operation that later reverses another (a sale cancellation reversing a completion, a rental cancellation releasing a deposit hold, a class cancellation refunding a fee) must return the ledger to exactly the position it would have held had the reversed operation never occurred. To make exact reversal possible, orders retain the precise amounts they moved (for example, a sales order records the `credit_applied_cents` it consumed so a cancellation can restore that same figure). A `StoreManager` may also move the ledger directly via a manual goodwill adjustment.

Two other per-customer figures are derived from sales activity. `lifetime_spend_cents` accumulates the `total_due_cents` of the customer's completed sales and is reduced when such a sale is reversed. `loyalty_tier` is a pure function of `lifetime_spend_cents`, recomputed every time that figure changes (see §3.2).

### 2.8. Optimistic Concurrency Control for Special-Order Amendments

Amending a special order is guarded by optimistic concurrency control. A special-order amendment request must carry `expected_special_order_version`, the `version` of the `SpecialOrder` that the client last observed. The server compares this value to the target `SpecialOrder`'s current `version`. If they do not match — because a prior amendment or a state transition (receive, fulfill, cancel) has advanced the version since the client last read the order — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the order before amending again. No other endpoint in this system takes a version field; only the special-order amendment is version-guarded.

### 2.9. Cascading State Effects and Hierarchical Consistency

Several operations change more than one entity in a single atomic step. Completing a class session promotes all of its still-enrolled enrollments to `ATTENDED`. Cancelling a class session cancels every enrollment on it — both `ENROLLED` and `WAITLISTED` — and refunds each affected customer's fee back to their store credit, a chain three levels deep (session → enrollment → customer). Cancelling one `ENROLLED` seat refunds that customer and promotes the earliest-created waitlisted enrollment into the freed seat. Completing or reversing a sale moves inventory status, the buyer's credit, and the buyer's lifetime spend and tier all at once. In every such case the secondary entities are mutated in full — their computed fields updated, their `version` bumped, their `updated_at` refreshed — exactly as if each had been changed directly.

### 2.10. Validation Ordering and Error Precedence

When several checks could reject a single request, they are evaluated in a fixed order so that the returned `error_id` is deterministic. The order is:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED` (401).
2. **Role authorization** — the role may perform this operation, else `ERR_FORBIDDEN` (403).
3. **Ownership** — for a `Customer` acting on an owned resource (repair approve, repair reject, enrollment cancel, subscription cancel), `X-User-ID` equals the resource's `customer_id`, else `ERR_FORBIDDEN` (403).
4. **Existence** — path resource ids are resolved left to right, and any foreign-key id in the body (`customer_id`, `inventory_item_id`, `product_id`, `class_session_id`) must reference an existing entity, else the corresponding not-found error (404).
5. **Body well-formedness** — required fields present, enum values valid, integer amounts at least 0, and any end/due instant strictly after its start instant, else `ERR_VALIDATION` (400).
6. **State** — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE`, `ERR_ITEM_NOT_AVAILABLE`, `ERR_ALREADY_RECALLED`, or `ERR_SESSION_NOT_OPEN` as applicable (409).
7. **Business-safety and business-rule checks** — recall blocks, temporal-overlap checks, part-category checks, tune-up exhaustion, trade-in banding, and the special-order OCC check, each with its own error as described in §3.

Existence is checked before body well-formedness; body well-formedness before state; state before the business rules. Within existence, path ids are resolved in their left-to-right order in the URL before body foreign keys are checked.

## 3. Business Logic & Workflows

### 3.1. Catalog, Inventory, and Recalls

The catalog is a set of `Product` records, each a model the store may stock or service. A `StoreManager` creates a product by supplying its `model_name`, its `category` — one of `SEWING_MACHINE`, `VACUUM`, `PART`, or `ACCESSORY` — its `brand`, and its `msrp_cents` (the manufacturer suggested retail price in cents). An optional `warranty_months` gives the length of the factory warranty in whole months and defaults to 12 when omitted. A newly created product begins with `recall_status` of `NONE` and a null `recall_reason`. Products may be listed, optionally filtered by `category`, and fetched individually.

A recall is issued against a product by a `StoreManager`, who supplies a `recall_reason`. This transitions the product's `recall_status` from `NONE` to `RECALLED` and stores the supplied reason text. A product already in `RECALLED` cannot be recalled again; a second attempt is rejected with `ERR_ALREADY_RECALLED`. A recall has downstream teeth: once a product is `RECALLED`, completing a sale of that product's unit and approving a repair on that product are both blocked (see §3.3 and §3.4).

Physical stock is tracked as `InventoryItem` records, each an instance of a catalog `Product`. A `StoreManager` takes a unit into stock by supplying its `product_id`, an optional `serial_number` (null for bulk parts and accessories), an optional `condition` grade — one of `NEW`, `REFURBISHED`, or `USED_TRADE_IN`, defaulting to `NEW` — the `acquisition_cost_cents` the store paid, and the `list_price_cents` at which it is offered (this same list price is also what a part unit charges when it is consumed on a repair). A new item enters with `status` of `IN_STOCK`. Inventory may be listed and filtered by `product_id` and by `status`, and fetched individually.

The allocation lifecycle of an inventory item runs over `IN_STOCK`, `RESERVED`, `SOLD`, and `SCRAPPED`. Reserving happens when a sales order opens; a sale completion moves the unit `RESERVED → SOLD`; cancelling a reserved order returns it `RESERVED → IN_STOCK`; cancelling a completed order returns it `SOLD → IN_STOCK`. Because a released unit can be reserved again by a fresh order, the `IN_STOCK → RESERVED → IN_STOCK` path is a genuine cycle. Consuming a part on a repair moves that part unit `IN_STOCK → SOLD`. A `StoreManager` may scrap an in-stock unit, moving it `IN_STOCK → SCRAPPED`; scrapping requires the unit to be `IN_STOCK`, else `ERR_ITEM_NOT_AVAILABLE`. Rentals, by deliberate contrast, do **not** change an inventory item's `status` at all — loaner availability is governed purely by temporal overlap of active rentals (§3.5), not by this field.

### 3.2. Customers, Loyalty, and Store Credit

A `Customer` is registered by a `SalesAssociate` or a `StoreManager` with a `full_name` and an `email`. On registration the customer's `store_credit_cents`, `lifetime_spend_cents` both begin at 0 and `loyalty_tier` begins at `STANDARD`. Customers may be fetched individually.

The `loyalty_tier` is derived strictly from `lifetime_spend_cents` and is recomputed every time that figure changes: the tier is `PLATINUM` when lifetime spend is at least 1,500,000 cents, otherwise `GOLD` when lifetime spend is at least 500,000 cents, and otherwise `STANDARD`. Both thresholds are inclusive lower bounds — a spend landing exactly on a threshold takes the higher tier.

A `StoreManager` may directly adjust a customer's store-credit ledger for goodwill or corrections, supplying an `amount_cents` (which may be negative to debit) and a `reason`. The adjustment adds `amount_cents` to the customer's `store_credit_cents`. Every other movement of the ledger arises as a side effect of the sales, repair, rental, class, and subscription workflows described below.

### 3.3. Sales Orders, Trade-Ins, and Loyalty Pricing

A sale is a two-phase affair: reservation, then completion. A `SalesAssociate` opens a `SalesOrder` by supplying the buyer's `customer_id`, the `inventory_item_id` of the machine being sold, the negotiated pre-tax `sale_price_cents`, and — when the buyer trades an old machine in — a free-text `trade_in_model` and a `trade_in_condition` graded `GOOD`, `FAIR`, or `POOR`. A trade-in is all-or-nothing at intake: supplying a `trade_in_condition` without a `trade_in_model`, or a `trade_in_model` without a `trade_in_condition`, is rejected with `ERR_INVALID_TRADE_IN`. Opening the order requires the target inventory item to be `IN_STOCK`; if it is not, the reservation fails with `ERR_ITEM_NOT_AVAILABLE`. On success the order enters `RESERVED`, the inventory item moves `IN_STOCK → RESERVED`, and a provisional `trade_in_estimate_cents` is set from a fixed condition schedule — 40,000 cents for a `GOOD` machine, 25,000 cents for `FAIR`, 10,000 cents for `POOR`, and 0 when there is no trade-in. Sales orders may be listed, filtered by `customer_id` and by `inventory_item_id`, and fetched individually.

Completion, performed by a `SalesAssociate`, is where all pricing is finalized. Completion requires the order to be `RESERVED`, else `ERR_INVALID_STATE`. It is blocked when the reserved unit's product is `RECALLED`, in which case it fails with `ERR_PRODUCT_RECALLED`. When the order carries a trade-in, the manager's final appraisal is supplied at this step as `trade_in_final_cents`; the final figure must fall within 15,000 cents of the provisional estimate — that is, the absolute difference between `trade_in_final_cents` and `trade_in_estimate_cents` must be at most 15,000 cents — otherwise completion is rejected with `ERR_TRADE_IN_OUT_OF_BAND`. It is the final figure, not the estimate, that is ultimately credited.

Pricing at completion runs in a pinned order because loyalty is self-referential. First, the buyer's **pre-sale** tier is read from their `lifetime_spend_cents` as it stands before this order is counted. From that tier a `loyalty_discount_cents` is computed as the `sale_price_cents` multiplied by the tier's discount percentage — 0% for `STANDARD`, 5% for `GOLD`, 10% for `PLATINUM` — rounded half up to whole cents. Next the order total is computed: the taxable amount is `sale_price_cents` minus `loyalty_discount_cents`; the `tax_cents` is that taxable amount multiplied by the tax rate of 8%, rounded half up to whole cents; the `credit_applied_cents` is the smaller of the buyer's store-credit balance as it stood **before** this order and the sum of the taxable amount plus tax; and the `total_due_cents` is the taxable amount plus tax minus the credit applied. Only after the total is fixed does the buyer's `lifetime_spend_cents` increase by `total_due_cents` and their `loyalty_tier` recompute — a promotion earned here affects only the buyer's *next* order, never this one.

Completion also settles the ledger and inventory. The `credit_applied_cents` consumed by the order is deducted from the buyer's `store_credit_cents`. If the order carried a trade-in, the `trade_in_final_cents` is then added to the buyer's `store_credit_cents` — the trade-in grant is applied *after*, and does not offset, this same order's charge. The reserved inventory item moves `RESERVED → SOLD`, and the sales order's own `warranty_expires_at` field (the inventory item carries no such field) is set to the logical clock at completion advanced by the product's `warranty_months` whole calendar months.

Cancellation covers two distinct paths. A `SalesAssociate` (or a `StoreManager`) may cancel a `RESERVED` order that has not yet completed: the order moves `RESERVED → CANCELLED` and the held inventory item is released `RESERVED → IN_STOCK`; no ledger movement is involved because none had occurred. Separately, a `StoreManager` may reverse a `COMPLETED` order as a return: the order moves `COMPLETED → CANCELLED`, the sold unit returns `SOLD → IN_STOCK`, the `credit_applied_cents` originally consumed is added back to the buyer's `store_credit_cents`, and — if the order carried a trade-in — the `trade_in_final_cents` originally granted is clawed back out of the buyer's store credit. Finally the buyer's `lifetime_spend_cents` is reduced by this order's `total_due_cents` and their `loyalty_tier` recomputed. Cancellation from any other state is rejected with `ERR_INVALID_STATE`. Reversing a `COMPLETED` order is restricted to a `StoreManager`; although the cancel endpoint authorizes both roles, a `SalesAssociate` who invokes it on a `COMPLETED` order is rejected with `ERR_FORBIDDEN`. These retained figures are exactly what makes the reversal conserve the ledger.

### 3.4. Repair Tickets, Parts, and Warranty

A repair begins when a `ServiceTech` or `SalesAssociate` opens a `RepairTicket` for a machine, supplying the owner's `customer_id`, the `product_id` of the model being serviced (used for recall and warranty checks), and an optional `is_warranty` flag defaulting to false that records whether the customer claims warranty coverage. A new ticket enters `INTAKE`. Tickets may be listed, filtered by `customer_id` and `product_id`, and fetched individually.

The repair lifecycle runs `INTAKE → AWAITING_APPROVAL → IN_REPAIR → READY → CLOSED`, with a revision loop and a cancellation path. A `ServiceTech` quotes the job from `INTAKE`, supplying a `diagnosis` and the estimated `labor_hours`; this moves the ticket to `AWAITING_APPROVAL`, stores both values, and sets a provisional `labor_estimate_cents` equal to `labor_hours` multiplied by the labor rate of 9,000 cents per hour, rounded half up to whole cents. Quoting from any state other than `INTAKE` is rejected with `ERR_INVALID_STATE`.

From `AWAITING_APPROVAL`, the owning `Customer` (or a `SalesAssociate` acting for them) either approves or rejects the quote. Approval requires the ticket to be `AWAITING_APPROVAL`, else `ERR_INVALID_STATE`; it requires the acting customer to own the ticket unless the actor is a `SalesAssociate`, else `ERR_FORBIDDEN`; and it is blocked when the ticket's product is `RECALLED`, failing with `ERR_PRODUCT_RECALLED`. A successful approval moves the ticket `AWAITING_APPROVAL → IN_REPAIR`. Rejection, which is the revision loop, also requires `AWAITING_APPROVAL` (else `ERR_INVALID_STATE`) and the same ownership rule (else `ERR_FORBIDDEN`); it returns the ticket `AWAITING_APPROVAL → INTAKE` and clears the earlier quote — `diagnosis` back to null, `labor_hours` back to null, and `labor_estimate_cents` reset to 0 — so the technician can re-quote from scratch.

While the ticket is `IN_REPAIR`, a `ServiceTech` may consume stocked parts. Consuming a part supplies the `inventory_item_id` of the part unit; the unit must be `IN_STOCK` (else `ERR_ITEM_NOT_AVAILABLE`) and its product's `category` must be `PART` (else `ERR_NOT_A_PART`). A consumed part moves `IN_STOCK → SOLD` and its `list_price_cents` is added to the ticket's running `parts_cost_cents`. When the work is done, the `ServiceTech` completes the repair, moving it `IN_REPAIR → READY` (else `ERR_INVALID_STATE`) and computing the `final_invoice_cents`: when the ticket is a warranty job, labor is waived entirely and the final invoice equals the accumulated `parts_cost_cents`; otherwise the final invoice equals `labor_estimate_cents` plus `parts_cost_cents`.

Handover is performed by a `SalesAssociate`, who closes a `READY` ticket (else `ERR_INVALID_STATE`), moving it `READY → CLOSED`. At close, the customer's store credit is applied toward the bill: the customer's `store_credit_cents` is reduced by the smaller of their current balance and the `final_invoice_cents`. A `SalesAssociate` may also cancel a ticket that is still in `INTAKE`, `AWAITING_APPROVAL`, or `IN_REPAIR`, moving it to `CANCELLED`; cancelling from any other state is rejected with `ERR_INVALID_STATE`.

### 3.5. Loaner Rentals

A `SalesAssociate` lends a loaner by creating a `RentalAgreement` with the renter's `customer_id`, the `inventory_item_id` of the loaner unit, a `start_at` and a `due_at`, a `daily_rate_cents`, and a refundable `deposit_cents`. The `due_at` must be strictly after `start_at`, else `ERR_VALIDATION`. A new agreement enters `ACTIVE`. Rentals may be listed, filtered by `customer_id` and `inventory_item_id`, and fetched individually.

Availability of a loaner is temporal, not status-based. Before the deposit is taken, the system checks the candidate interval against every existing `ACTIVE` rental of the same inventory item under half-open semantics `[start_at, due_at)`: two intervals conflict when the new start is before the existing due **and** the existing start is before the new due. Intervals that merely touch at an endpoint — the new start equal to an existing due, or vice versa — do not conflict, because the due instant is exclusive. A conflict is rejected with `ERR_RENTAL_OVERLAP`. On success, the billable `rental_days` is computed as the ceiling of the span from `start_at` to `due_at` measured in days, and the `deposit_cents` is placed on hold by deducting it from the renter's `store_credit_cents`.

Returning a loaner is done by a `SalesAssociate` on an `ACTIVE` agreement (else `ERR_INVALID_STATE`). The `returned_at` instant is taken from the request when supplied, otherwise from the logical clock. The late fee is then computed: the number of `days_late` is the ceiling of the span from `due_at` to `returned_at` in days but never less than 0, so a unit returned on or before `due_at` incurs zero days late (returning exactly at `due_at` yields zero, because the due instant is exclusive). The `late_fee_cents` is `days_late` multiplied by `daily_rate_cents` multiplied by the late multiplier of 1.5, rounded half up to whole cents. The `total_charge_cents` is `rental_days` multiplied by `daily_rate_cents` plus the `late_fee_cents`. The agreement moves `ACTIVE → RETURNED`, and the deposit hold is released net of the late fee: the renter's `store_credit_cents` increases by `deposit_cents` minus `late_fee_cents`.

A `SalesAssociate` may instead cancel an `ACTIVE` rental (else `ERR_INVALID_STATE`), moving it `ACTIVE → CANCELLED` and releasing the full deposit hold — the renter's `store_credit_cents` increases by the full `deposit_cents`.

### 3.6. Classes and Enrollment

A `StoreManager` schedules a `ClassSession` with a `title`, a `machine_type` of `SEWING` or `VACUUM`, a `start_at`, an `end_at` (which must be strictly after `start_at`, else `ERR_VALIDATION`), a `capacity` of at least one seat, and a per-seat `fee_cents`. A new session enters `SCHEDULED` with `enrolled_count` and `waitlist_count` both at 0. Sessions may be listed, filtered by `machine_type`, and fetched individually.

A `Customer` (or a `SalesAssociate` on their behalf) enrolls by supplying the enrollee's `customer_id`. Enrollment requires the session to be `SCHEDULED`, else `ERR_SESSION_NOT_OPEN`. It also requires that the enrollee not double-book: the new session's closed interval `[start_at, end_at]` is checked against every session the customer is already enrolled or waitlisted on, with a required separation buffer of 30 minutes. Two sessions are clear of each other only when the existing session's end plus 30 minutes is at or before the new session's start, or the new session's end plus 30 minutes is at or before the existing session's start; anything closer than that buffer is a conflict, rejected with `ERR_SCHEDULE_CONFLICT`. Note that because the buffer must be satisfied, back-to-back sessions (one ending exactly when the other begins) **do** conflict — the opposite of the rental adjacency rule. When the session still has room — `enrolled_count` below `capacity` — the new `ClassEnrollment` enters `ENROLLED` and the session's `enrolled_count` increases by one; when the session is already full, it enters `WAITLISTED` and the session's `waitlist_count` increases by one instead. Either way the seat's `fee_charged_cents` is fixed to the session's `fee_cents` at the moment of enrollment and that amount is debited from the customer's `store_credit_cents`. Enrollments may be listed, filtered by `class_session_id` and `customer_id`, and fetched individually.

A `Customer` (or `SalesAssociate`) may cancel their enrollment. Cancelling an `ENROLLED` seat (else `ERR_INVALID_STATE`, and subject to the ownership rule, else `ERR_FORBIDDEN`) moves it to `CANCELLED`, refunds the `fee_charged_cents` back to that customer's `store_credit_cents`, decrements the session's `enrolled_count` by one, and then promotes the earliest-created `WAITLISTED` enrollment on that session — ordered by `created_at` ascending — into the freed seat, decrementing `waitlist_count` by one and incrementing `enrolled_count` by one. Cancelling a `WAITLISTED` seat (else `ERR_INVALID_STATE`, same ownership rule) moves it to `CANCELLED`, refunds the fee, and decrements the session's `waitlist_count` by one, with no promotion.

Session lifecycle transitions are driven by the `StoreManager`. Completing a `SCHEDULED` session (else `ERR_INVALID_STATE`) moves it `SCHEDULED → COMPLETED` and promotes every enrollment still in `ENROLLED` to `ATTENDED`. Cancelling a `SCHEDULED` session (else `ERR_INVALID_STATE`) moves it `SCHEDULED → CANCELLED` and cascades: every enrollment in `ENROLLED` or `WAITLISTED` becomes `CANCELLED`, and each such cancellation refunds that enrollment's `fee_charged_cents` to its customer's `store_credit_cents` — a three-level cascade from session to enrollments to customers.

### 3.7. Tune-Up Subscriptions

A `SalesAssociate` starts a `TuneUpSubscription` for a subscriber's `customer_id`, choosing a `plan_tier` of `BASIC` or `PRO`, a `monthly_fee_cents`, and the number of `tune_ups_included` per billing period. On creation the subscription enters `ACTIVE`, its `tune_ups_used` begins at 0, its `current_period_start` is set to the logical clock at creation, and its `current_period_end` is set to that start plus the period length of 30 days. Subscriptions may be listed, filtered by `customer_id`, and fetched individually.

A `ServiceTech` or `SalesAssociate` redeems an included tune-up. A redemption succeeds only while the subscription is `ACTIVE`, the logical clock is before `current_period_end`, and `tune_ups_used` is strictly less than `tune_ups_included`; a successful redemption increases `tune_ups_used` by one. Redemption on a subscription that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`, and redemption once `tune_ups_used` has reached `tune_ups_included` (they are equal) is rejected with `ERR_TUNE_UPS_EXHAUSTED`. Redemption when the logical clock has reached or passed `current_period_end` is also rejected with `ERR_INVALID_STATE`, and this expired-period check is evaluated before the exhaustion check (so an expired, fully-used subscription yields `ERR_INVALID_STATE`).

The subscription status may move among `ACTIVE`, `PAST_DUE`, and `CANCELLED`. A `StoreManager` lapses an `ACTIVE` subscription (else `ERR_INVALID_STATE`), moving it `ACTIVE → PAST_DUE`. A `SalesAssociate` reinstates a `PAST_DUE` subscription (else `ERR_INVALID_STATE`), moving it `PAST_DUE → ACTIVE`. A `Customer` (or `SalesAssociate`) cancels a subscription that is `ACTIVE` or `PAST_DUE` (else `ERR_INVALID_STATE`, subject to the ownership rule else `ERR_FORBIDDEN`), moving it to `CANCELLED`. When the cancellation is from `ACTIVE` and the logical clock is before `current_period_end`, a prorated refund is credited to the customer's `store_credit_cents`: the period length in whole days is the span from `current_period_start` to `current_period_end` measured in days; the unused days are the ceiling of the span from the logical clock to `current_period_end` in days, never less than 0; and the refund is `monthly_fee_cents` multiplied by the unused days, divided by the period length in days, rounded half up to whole cents — the integer fee is multiplied by the integer unused-day count first, then divided by the period days, and rounded exactly once at the end (the per-day rate is never rounded on its own). Cancelling from `PAST_DUE` yields no refund at all.

### 3.8. Special Orders

A `SalesAssociate` places a `SpecialOrder` for a model the store does not stock, supplying the requester's `customer_id`, the `product_id`, a `quantity` of at least one, an agreed `unit_price_cents`, and a `deposit_cents`. On creation the order enters `REQUESTED` and its `balance_due_cents` is computed as `quantity` multiplied by `unit_price_cents`, minus `deposit_cents`. Special orders may be listed, filtered by `customer_id` and `product_id`, and fetched individually.

A `SalesAssociate` may amend a still-open order's `quantity` and/or `deposit_cents`; the amendment recomputes `balance_due_cents` by the same formula and bumps the order's `version`. Amendment is guarded by optimistic concurrency: the request must carry `expected_special_order_version` equal to the order's current `version`, otherwise it is rejected with `ERR_STALE_VERSION`, as described in §2.8.

The special-order lifecycle runs `REQUESTED → RECEIVED → FULFILLED`, with cancellation available before fulfillment. A `SalesAssociate` marks a `REQUESTED` order received (else `ERR_INVALID_STATE`), moving it `REQUESTED → RECEIVED` and bumping the `version`. A `SalesAssociate` fulfills a `RECEIVED` order (else `ERR_INVALID_STATE`), moving it `RECEIVED → FULFILLED` and bumping the `version`. A `SalesAssociate` may cancel an order that is `REQUESTED` or `RECEIVED` (else `ERR_INVALID_STATE`), moving it to `CANCELLED` and bumping the `version`. Each of these transitions advances the version, which in turn is what a concurrent amendment's `expected_special_order_version` must match.

## 4. Endpoint Definitions

New resource creations return HTTP 201; all other successful operations, including state transitions and modifications, return HTTP 200. All endpoints are mounted at the service root.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /_clock/set_current_utc | Set the server logical clock (test-driving) | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /products | Create a catalog product | StoreManager |
| GET | /products | List products | SalesAssociate, ServiceTech, StoreManager, Customer |
| GET | /products/{id} | Get a product | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /products/{id}/recall | Issue a recall on a product | StoreManager |
| POST | /inventory-items | Intake a physical unit into inventory | StoreManager |
| GET | /inventory-items | List/filter inventory items | SalesAssociate, ServiceTech, StoreManager, Customer |
| GET | /inventory-items/{id} | Get an inventory item | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /inventory-items/{id}/scrap | Scrap an in-stock unit | StoreManager |
| POST | /customers | Register a customer | SalesAssociate, StoreManager |
| GET | /customers/{id} | Get a customer | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /customers/{id}/store-credit/adjustments | Manually adjust a customer's store credit | StoreManager |
| POST | /sales-orders | Open a sales order and reserve the unit | SalesAssociate |
| GET | /sales-orders | List/filter sales orders | SalesAssociate, ServiceTech, StoreManager, Customer |
| GET | /sales-orders/{id} | Get a sales order | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /sales-orders/{id}/complete | Complete the sale and finalize pricing | SalesAssociate |
| POST | /sales-orders/{id}/cancel | Cancel or reverse a sales order | SalesAssociate, StoreManager |
| POST | /repair-tickets | Open a repair ticket | ServiceTech, SalesAssociate |
| GET | /repair-tickets | List/filter repair tickets | SalesAssociate, ServiceTech, StoreManager, Customer |
| GET | /repair-tickets/{id} | Get a repair ticket | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /repair-tickets/{id}/quote | Record diagnosis and quote | ServiceTech |
| POST | /repair-tickets/{id}/approve | Approve the quote | Customer, SalesAssociate |
| POST | /repair-tickets/{id}/reject | Reject the quote (re-quote loop) | Customer, SalesAssociate |
| POST | /repair-tickets/{id}/consume-part | Consume a stocked PART unit onto the ticket | ServiceTech |
| POST | /repair-tickets/{id}/complete | Finish the repair and finalize the invoice | ServiceTech |
| POST | /repair-tickets/{id}/close | Hand over and charge the customer | SalesAssociate |
| POST | /repair-tickets/{id}/cancel | Cancel a non-terminal repair ticket | SalesAssociate |
| POST | /rental-agreements | Create a loaner rental | SalesAssociate |
| GET | /rental-agreements | List/filter rentals | SalesAssociate, ServiceTech, StoreManager, Customer |
| GET | /rental-agreements/{id} | Get a rental | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /rental-agreements/{id}/return | Return a loaner and settle charges | SalesAssociate |
| POST | /rental-agreements/{id}/cancel | Cancel an active rental | SalesAssociate |
| POST | /class-sessions | Schedule a class/lesson | StoreManager |
| GET | /class-sessions | List class sessions | SalesAssociate, ServiceTech, StoreManager, Customer |
| GET | /class-sessions/{id} | Get a class session | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /class-sessions/{id}/complete | Mark a session completed | StoreManager |
| POST | /class-sessions/{id}/cancel | Cancel a session and refund enrollees | StoreManager |
| POST | /class-sessions/{id}/enrollments | Enroll a customer (or waitlist when full) | Customer, SalesAssociate |
| GET | /class-enrollments | List/filter enrollments | SalesAssociate, ServiceTech, StoreManager, Customer |
| GET | /class-enrollments/{id} | Get an enrollment | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /class-enrollments/{id}/cancel | Cancel an enrollment (promotes earliest waitlisted) | Customer, SalesAssociate |
| POST | /tune-up-subscriptions | Start a tune-up subscription | SalesAssociate |
| GET | /tune-up-subscriptions | List/filter subscriptions | SalesAssociate, ServiceTech, StoreManager, Customer |
| GET | /tune-up-subscriptions/{id} | Get a subscription | SalesAssociate, ServiceTech, StoreManager, Customer |
| POST | /tune-up-subscriptions/{id}/redeem | Redeem one included tune-up | ServiceTech, SalesAssociate |
| POST | /tune-up-subscriptions/{id}/lapse | Mark a subscription past due | StoreManager |
| POST | /tune-up-subscriptions/{id}/reinstate | Reinstate a past-due subscription | SalesAssociate |
| POST | /tune-up-subscriptions/{id}/cancel | Cancel a subscription (prorated refund from ACTIVE) | Customer, SalesAssociate |
| POST | /special-orders | Place a special order | SalesAssociate |
| GET | /special-orders | List/filter special orders | SalesAssociate, ServiceTech, StoreManager, Customer |
| GET | /special-orders/{id} | Get a special order | SalesAssociate, ServiceTech, StoreManager, Customer |
| PATCH | /special-orders/{id} | Amend quantity/deposit (OCC-guarded) | SalesAssociate |
| POST | /special-orders/{id}/receive | Mark special order stock received | SalesAssociate |
| POST | /special-orders/{id}/fulfill | Hand over the special order | SalesAssociate |
| POST | /special-orders/{id}/cancel | Cancel a special order | SalesAssociate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_VALIDATION | 400 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_INVENTORY_ITEM_NOT_FOUND | 404 |
| ERR_SALES_ORDER_NOT_FOUND | 404 |
| ERR_REPAIR_TICKET_NOT_FOUND | 404 |
| ERR_RENTAL_NOT_FOUND | 404 |
| ERR_CLASS_SESSION_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_SUBSCRIPTION_NOT_FOUND | 404 |
| ERR_SPECIAL_ORDER_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ITEM_NOT_AVAILABLE | 409 |
| ERR_ALREADY_RECALLED | 409 |
| ERR_SESSION_NOT_OPEN | 409 |
| ERR_PRODUCT_RECALLED | 409 |
| ERR_RENTAL_OVERLAP | 409 |
| ERR_SCHEDULE_CONFLICT | 409 |
| ERR_NOT_A_PART | 409 |
| ERR_TUNE_UPS_EXHAUSTED | 409 |
| ERR_TRADE_IN_OUT_OF_BAND | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_PAGINATION | 400 |
| ERR_INVALID_TRADE_IN | 400 |
