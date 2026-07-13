# Textbook Rental API — Product Requirements Document

## 1. Introduction

The Textbook Rental API powers a course-material marketplace in the spirit of subscription textbook services: students rent, buy, or read digital editions of academic titles; they extend loans when a term runs long; they ship books back for inspection; and they sell used copies back to the platform for wallet credit. Every physical copy on the platform has a graded condition, a rental history, and a lifecycle that runs from acquisition through loan, inspection, and eventual retirement or resale. Because a single title may exist in several editions and many physical copies, and because each order threads together pricing, fulfilment, and returns, the system must keep three concerns simultaneously coherent: an accurate money ledger, a correct physical-inventory state, and a deterministic pricing engine.

This document specifies the complete behavioural contract for that system. It is organised so that global, system-wide rules (authentication, response envelopes, pagination, money precision, concurrency, and validation ordering) are stated once in Section 2, while the domain workflows — catalog setup, ordering, fulfilment, the rental loan cycle, return inspection, and the buyback flow — are narrated in Section 3. Sections 4 and 5 provide the endpoint and error-code reference tables. Monetary amounts are always expressed in integer cents, and all time-dependent behaviour is governed by a server-controlled logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognises exactly three roles: `Customer`, `WarehouseAgent`, and `CatalogAdmin`. If either header is missing, or if `X-User-Role` is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The three roles map to identity in different ways. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare that resource's `customer_id` to `X-User-ID`. A `Customer` may act only on resources it owns — its own orders, rentals, subscriptions, buyback quotes, and wallet ledger — and an attempt by one customer to read or mutate another customer's resource is rejected with `ERR_UNAUTHORIZED`. When `X-User-Role` is `WarehouseAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. `WarehouseAgent` handles physical operations: confirming and fulfilling paid orders, inspecting returned copies, and inspecting buyback intake. When `X-User-Role` is `CatalogAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. `CatalogAdmin` owns configuration and operator surfaces: the catalog, physical inventory, customer onboarding, subscription plans, wallet adjustments, and the logical clock.

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

Every primary resource — `CatalogItem`, `InventoryUnit`, `Customer`, `SubscriptionPlan`, `Subscription`, `Order`, `Rental`, `ReturnShipment`, and `BuybackQuote` — carries a standard set of system-managed fields:

- `id`: a unique, server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp recording the most recent mutation of the resource.
- `version`: an integer that begins at its initial value and increments by one on every mutation of the resource. It is the anchor for optimistic concurrency control described in Section 2.7.

Whenever the server mutates a resource — including automatic transitions and derived-field recomputations that the client did not explicitly request on that resource — it refreshes that resource's `updated_at` and increments its `version`.

There is one exception. The `WalletTransaction` ledger entry is an immutable, append-only record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written a ledger entry is never modified.

### 2.5. The Logical Clock

All deadline, expiry, and window computations read a single server-controlled logical clock rather than the host wall-clock. At server startup the clock reads exactly `2026-03-01T00:00:00Z`; before any clock has been set, every time-dependent rule evaluates against that default instant and never against real wall-clock time. A `CatalogAdmin` may advance or reset the clock by supplying a target instant in the `to_iso8601` field; this becomes the value that all subsequent due-date, quote-expiry, subscription-period, and overlap computations observe.

### 2.6. Monetary Values, Precision, and the Wallet Ledger

Every monetary amount in the system is an integer number of cents. Wherever a calculation multiplies by a fraction (a term multiplier, a member discount, a condition multiplier, or a proration ratio) the intermediate result is rounded to the nearest whole cent using the round-half-up convention — a value exactly halfway between two cents rounds up. Day counts derived from timestamp differences use whole-day arithmetic as specified per calculation (ceiling for overdue days, floor for elapsed days).

Money moves exclusively through an append-only ledger of `WalletTransaction` entries. Each entry records the `customer_id` of the wallet owner, a signed `amount_cents` (positive credits the customer, negative debits the customer), a `kind` classifying the entry, and an optional `reference_id` — an opaque identifier of the originating order, rental, quote, or subscription retained for audit (it is not a reverse-queryable foreign key). The permitted values of `kind` are `TOP_UP`, `ORDER_CHARGE`, `ORDER_REFUND`, `EXTENSION_FEE`, `LATE_FEE`, `DAMAGE_FEE`, `REPLACEMENT_CHARGE`, `BUYBACK_CREDIT`, `SUBSCRIPTION_FEE`, and `SUBSCRIPTION_REFUND`.

A customer's `wallet_credit_cents` is always the exact sum of the `amount_cents` of every `WalletTransaction` whose `customer_id` is that customer; it is recomputed on every ledger append and is order-independent. A newly onboarded customer begins with `wallet_credit_cents` of 0. Operators fund wallets through a wallet adjustment that appends a `WalletTransaction` (defaulting `kind` to `TOP_UP` when the optional `kind` is omitted) carrying the supplied `amount_cents`. Post-fulfilment fees may drive a balance negative, but the two operations that spend money up front — paying for an order and extending a rental — are gated by explicit credit-sufficiency checks (Section 2.8) so that a charge only proceeds when funds cover it.

### 2.7. Optimistic Concurrency Control

Requesting a new buyback quote requires optimistic concurrency control keyed on the seller's `Customer` record. The create request must carry `expected_customer_version` holding the client's last observed `version` of that `Customer`. If `expected_customer_version` does not equal the stored `Customer.version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This exists because requesting a quote supersedes any prior open quote for the same title and advances the seller's `Customer.version`; a create that still carries an out-of-date customer version has not observed that supersession and is refused so it cannot overwrite state it never saw.

Three operations advance a customer's `version` by one as a side effect: an operator wallet adjustment, subscribing the customer to a plan, and requesting a buyback quote. A client that intends to request a quote should therefore read the customer immediately beforehand to obtain the current `version`. No other endpoint accepts or requires a client-supplied version field.

### 2.8. Validation Ordering and Error Precedence

When more than one rule could reject a request, the checks are evaluated in a fixed priority order and the first failing check determines the error returned. The ordering, from highest priority to lowest, is:

1. **Authentication** — headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization by role** — the role may perform this operation, else `ERR_UNAUTHORIZED` (403).
3. **Ownership** — for a `Customer` acting on an owned resource, `X-User-ID` equals the resource's `customer_id`, else `ERR_UNAUTHORIZED` (403).
4. **Existence** — every resource named by a path id or a body foreign key exists, else `ERR_RESOURCE_NOT_FOUND` (404). Referenced resources are checked left to right (see Section 2.9).
5. **State/lifecycle preconditions** — the target resource is in a status that permits the operation (the 409 conflict codes named throughout Section 3, such as `ERR_ORDER_NOT_PAYABLE`, `ERR_RENTAL_NOT_ACTIVE`, or `ERR_QUOTE_NOT_OPEN`).
6. **Delivered-ebook safety** — an already-delivered ebook order may not be cancelled, else `ERR_EBOOK_ALREADY_DELIVERED` (422).
7. **Referential business eligibility** — item-type eligibility flags and inventory availability (`ERR_ITEM_NOT_RENTABLE`, `ERR_ITEM_NOT_BUYABLE`, `ERR_ITEM_NOT_EBOOK_AVAILABLE`, `ERR_NO_AVAILABLE_UNIT`).
8. **Temporal business rules** — window and period overlaps and expiry (`ERR_UNIT_WINDOW_CONFLICT`, `ERR_SUBSCRIPTION_PERIOD_OVERLAP`, `ERR_EBOOK_LICENSE_OVERLAP`, `ERR_QUOTE_EXPIRED`).
9. **Constraint business rules** — extension limits, term validity, edition uniqueness, and generic request well-formedness (`ERR_MAX_EXTENSIONS_REACHED`, `ERR_INVALID_TERM`, `ERR_DUPLICATE_EDITION`, `ERR_INVALID_REQUEST`).
10. **Optimistic concurrency** — `expected_customer_version` matches the stored `Customer.version`, else `ERR_STALE_VERSION` (412).
11. **Fiscal credit sufficiency** — the wallet covers the charge, else `ERR_INSUFFICIENT_CREDIT` (402).

Because existence outranks state, a request against a resource that does not exist always yields `ERR_RESOURCE_NOT_FOUND` before any status conflict is considered; because state outranks the referential and temporal tiers, a lifecycle conflict surfaces before an availability or window check; and because concurrency outranks credit, a stale customer version is reported before any wallet-balance check on the buyback create. Generic well-formedness — required fields present, correct types, enum values in range — is reported as `ERR_INVALID_REQUEST` (400) for any malformed POST body.

### 2.9. Existence and Reference Resolution

Every endpoint that names a resource by a path id or a body foreign key first confirms that the referenced resource exists, validating references left to right in the order they appear. The resource types resolved this way are `CatalogItem`, `InventoryUnit`, `Customer`, `SubscriptionPlan`, `Subscription`, `Order`, `Rental`, `ReturnShipment`, and `BuybackQuote`. The first reference that does not resolve causes the request to be rejected with `ERR_RESOURCE_NOT_FOUND` (404) before any downstream business rule runs. List endpoints accept optional reverse-lookup filters — for example inventory copies filtered by `catalog_item_id` and `status`; orders filtered by `customer_id`, `catalog_item_id`, or `inventory_unit_id`; rentals filtered by `order_id`, `customer_id`, or `inventory_unit_id`; subscriptions filtered by `customer_id` or `plan_id`; and buyback quotes filtered by `customer_id`, `catalog_item_id`, or `inventory_unit_id` — each alongside the standard `limit` and `offset`.

## 3. Business Logic & Workflows

### 3.1. Catalog and Inventory Setup

The catalog is the source of truth for titles and pricing. A `CatalogAdmin` registers a title edition by supplying its thirteen-digit `isbn13`, an `edition` number of at least 1, a `title`, and an `author`. Each edition carries a full set of price points, all in cents: `list_price_cents` is the outright purchase price and also serves as the ceiling on any damage assessment; `rental_base_cents` is the base rental price for a standard ninety-day term; `ebook_price_cents` is the price of digital access for one term; `buyback_base_cents` is the value of the title at pristine condition, from which buyback offers are scaled down; and `replacement_fee_cents` is charged when a rented copy is lost or never returned. Three eligibility flags gate which order types the title accepts: `rentable`, `buyable`, and `ebook_available`. The first two default to true and the third defaults to false. Two further flags govern highlighting: `highlighting_allowed` (default true) states whether marking pages incurs no flat penalty, and `max_highlight_pct` (default 10, in the range 0 to 100) is the share of pages that may be highlighted before per-point overage fees apply. The combination of `isbn13` and `edition` must be unique; registering a duplicate pair is rejected with `ERR_DUPLICATE_EDITION`.

Physical stock is tracked as `InventoryUnit` copies. Adding a copy requires the `catalog_item_id` it belongs to, its graded `condition_grade` — one of `NEW`, `LIKE_NEW`, `GOOD`, or `ACCEPTABLE` — and the `acquisition_cost_cents` the platform paid for it. A new copy begins with `status` of `AVAILABLE` and `times_rented` of 0. Across its life a copy's `status` moves among `AVAILABLE`, `RESERVED`, `RENTED`, `IN_INSPECTION`, `RETIRED`, and `SOLD` as orders reserve it, loans consume it, returns inspect it, and losses retire it. The `times_rented` counter increments once per loan the copy fulfils.

### 3.2. Customers, Wallets, and Subscriptions

A `CatalogAdmin` onboards a `Customer` with a unique `email` and a `full_name`; the customer's `wallet_credit_cents` starts at 0 and its `active_subscription_id` starts null. Customers fund their wallets only through operator adjustments, as described in Section 2.6.

Subscription plans are defined by a `CatalogAdmin`. A `SubscriptionPlan` has a `tier` of either `STUDY` or `SOLUTIONS`, a `monthly_fee_cents` recurring fee, a `rental_discount_pct` (a fraction between 0 and 1 applied to rental base pricing for members, e.g. 0.15), an `includes_solutions` flag stating whether the plan unlocks the step-by-step solutions add-on, and a `term_months` billing-period length that defaults to 1 and must be at least 1.

A `Customer` subscribes to a plan by naming the `plan_id` and optionally a `start_date`. Subscribing creates a `Subscription` in `ACTIVE` status linked by `customer_id` and `plan_id`. On creation the system snapshots the plan's `monthly_fee_cents` and `rental_discount_pct` onto the subscription so that later edits to the plan never disturb an existing membership. The billing window is computed by the subscription-period rule: the period length in days is the plan's `term_months` multiplied by 30; `period_start` is set to the current logical clock (or the supplied `start_date` when present) and `period_end` is `period_start` plus that many days. Subscribing appends a `WalletTransaction` of `kind` `SUBSCRIPTION_FEE` for the negative of the snapshotted `monthly_fee_cents`. If the new period contains the current clock instant, the customer's `active_subscription_id` is set to this subscription. Subscriptions are additive: a customer may hold several sequential periods, but a new period must not overlap any existing non-`CANCELLED` period of that customer. This overlap test treats each period as a closed interval, so even a boundary touch where one period's end equals the next period's start is a conflict, rejected with `ERR_SUBSCRIPTION_PERIOD_OVERLAP`. Creating a subscription also advances the customer's `version` by one.

Cancelling a subscription requires it to be in `ACTIVE` status, otherwise the request is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`. Cancellation moves `status` from `ACTIVE` to `CANCELLED` and refunds the unused remainder of the period on a prorated basis. The proration rule recomputes the period length in days as `term_months` times 30; the elapsed days are the whole-day floor of the interval from `period_start` to the current clock, clamped to lie between 0 and the full period length; the remaining days are the period length minus the elapsed days; and the refund is the snapshotted `monthly_fee_cents` multiplied by remaining days divided by the period length, rounded half up to whole cents. When that refund is greater than zero, a `WalletTransaction` of `kind` `SUBSCRIPTION_REFUND` is appended for that positive amount. If the cancelled subscription was the one referenced by the customer's `active_subscription_id`, that pointer is cleared to null.

### 3.3. Placing and Paying for Orders

A `Customer` places an `Order` against a title by supplying the `catalog_item_id`, a `fulfillment_type` of `RENT`, `BUY`, or `EBOOK`, and — for rentals and ebooks — a `rental_term_days`. The order's `customer_id` is taken from `X-User-ID`. Order type is gated against the title's eligibility flags: a `RENT` order requires `rentable` to be true (else `ERR_ITEM_NOT_RENTABLE`), a `BUY` order requires `buyable` to be true (else `ERR_ITEM_NOT_BUYABLE`), and an `EBOOK` order requires `ebook_available` to be true (else `ERR_ITEM_NOT_EBOOK_AVAILABLE`). Term supply is also constrained: a `RENT` order's `rental_term_days` must be one of 30, 60, 90, or 120; an `EBOOK` order must supply `rental_term_days`; and a `BUY` order must not supply it at all — any violation is `ERR_INVALID_TERM`. Every order starts with `payment_status` of `UNPAID` and `fulfillment_status` of `PENDING`; these two axes move independently.

At creation the provisional charge is computed and stored in `quoted_charge_cents` by the order-charge rule. For a `RENT` order the quote is the title's `rental_base_cents` multiplied by the term multiplier for the chosen term — 0.5 for a 30-day term, 0.75 for 60 days, 1.0 for 90 days, and 1.25 for 120 days — multiplied by one minus the member discount, then rounded half up to whole cents. The member discount is the `rental_discount_pct` snapshotted on the customer's `ACTIVE` subscription when one exists, and zero otherwise. For a `BUY` order the quote is simply the title's `list_price_cents`. For an `EBOOK` order the quote is the title's `ebook_price_cents`. The `final_charge_cents` remains null until a rental closes, and `refunded_cents` starts at 0.

Paying for an order requires its `payment_status` to be `UNPAID`, else `ERR_ORDER_NOT_PAYABLE`. Payment is drawn from wallet credit, so the customer's `wallet_credit_cents` must be at least `quoted_charge_cents`; if it is not, the payment is refused with `ERR_INSUFFICIENT_CREDIT`. On success the system appends a `WalletTransaction` of `kind` `ORDER_CHARGE` for the negative of `quoted_charge_cents` and moves `payment_status` from `UNPAID` to `PAID`. For an `EBOOK` order, paying also delivers access immediately: `fulfillment_status` moves to `DELIVERED`, `access_start` is set to the current clock, and `access_end` is set to `access_start` plus `rental_term_days` days. When an ebook order is placed, its access window `[access_start, access_end)` must not overlap the customer's existing active ebook access window for the same title; this half-open test adds no buffer, so an adjacency where one window's end equals the next window's start is allowed, and a genuine overlap is rejected with `ERR_EBOOK_LICENSE_OVERLAP`.

Cancelling an order is permitted only while its `fulfillment_status` is `PENDING`; a cancel attempted once the order is `CONFIRMED`, `DELIVERED`, `COMPLETED`, or already `CANCELLED` is rejected with `ERR_ORDER_NOT_CANCELLABLE`. An ebook order whose access has already been delivered cannot be cancelled or refunded, and such an attempt is rejected with `ERR_EBOOK_ALREADY_DELIVERED`. A valid cancel moves `fulfillment_status` to `CANCELLED`; if the order had already been paid, the system appends a compensating `WalletTransaction` of `kind` `ORDER_REFUND` for the positive `quoted_charge_cents`, adds that amount to the order's `refunded_cents`, and sets `payment_status` to `REFUNDED`.

### 3.4. Fulfilment: Confirming Orders and Selecting a Copy

A `WarehouseAgent` fulfils a paid physical order by confirming it. Confirmation applies only to orders whose `fulfillment_type` is `RENT` or `BUY`, and it requires the order to be in `PENDING` fulfilment with `payment_status` of `PAID`; an order that is not both pending and paid is rejected with `ERR_ORDER_NOT_PAID`. Confirmation then selects the physical copy to allocate. The selector first gathers every `InventoryUnit` of the order's `catalog_item_id` whose `status` is `AVAILABLE`. If no such copy exists at all, confirmation fails with `ERR_NO_AVAILABLE_UNIT`.

For a `RENT` order the selector must also respect loan windows. The requested window runs from the order's `desired_start_date` up to but not including the rental's due date plus a two-day inspection buffer. A copy is eligible only if it has no existing rental window — each existing rental's own window running from its `start_date` up to but not including its due date plus the same two-day buffer — that overlaps the requested window under this half-open test. If `AVAILABLE` copies exist but every one of them collides on the window, confirmation fails with `ERR_UNIT_WINDOW_CONFLICT` — a distinct, temporal outcome separate from the case where no available copy exists at all. Among the eligible copies the selector ranks ascending first by the condition rank of `condition_grade` (with `NEW` best, then `LIKE_NEW`, then `GOOD`, then `ACCEPTABLE`), then by `times_rented`, then by `created_at`, and it breaks any remaining tie by `created_at` ascending — never by `id`. The first-ranked copy is chosen and its identifier stored in the order's `inventory_unit_id`.

Confirming a `RENT` order drives the chosen copy's `status` from `AVAILABLE` through `RESERVED` to `RENTED`, creates a `Rental` in `ACTIVE` status, and increments the copy's `times_rented` by one. The rental copies the `order_id`, `customer_id`, and `inventory_unit_id`, sets its `start_date` from the order's `desired_start_date` (which itself defaults to the clock at order creation when not supplied), sets its `term_days` from `rental_term_days`, and computes its `due_date` as `start_date` plus `term_days` days. Confirming a `BUY` order instead drives the copy's `status` from `AVAILABLE` directly to `SOLD` and moves the order's `fulfillment_status` from `CONFIRMED` straight to `DELIVERED` in a single step; no rental is created.

### 3.5. The Rental Loan Cycle: Extensions and Returns

A rental begins its life in `ACTIVE` status. While active, a `Customer` may extend it or begin its return. Extending applies only to an `ACTIVE` rental (else `ERR_RENTAL_NOT_ACTIVE`) and is bounded on two fronts: the rental's `extension_count` must be below the ceiling of two extensions, and the new total term — the current `term_days` plus the thirty-day extension increment — must not exceed the maximum total term of 210 days. If either bound would be breached, the extension is refused with `ERR_MAX_EXTENSIONS_REACHED`. Each extension carries a flat fee of 1500 cents, so the customer's `wallet_credit_cents` must be at least that fee, else `ERR_INSUFFICIENT_CREDIT`. A successful extension increments `extension_count` by one, adds the thirty-day increment to `term_days`, recomputes `due_date` as `start_date` plus the new `term_days` days, and appends a `WalletTransaction` of `kind` `EXTENSION_FEE` for the negative of the flat fee; the rental remains `ACTIVE`.

Beginning a return first requires that no return is already open for it — that is, no `ReturnShipment` for this rental is currently in `LABEL_ISSUED` status — otherwise the request is refused with `ERR_RETURN_ALREADY_OPEN`; this open-return guard is evaluated before the active-status guard, so a rental that already has an open return (and has therefore left `ACTIVE`) yields `ERR_RETURN_ALREADY_OPEN` rather than `ERR_RENTAL_NOT_ACTIVE`. It then also requires the rental to be `ACTIVE` (else `ERR_RENTAL_NOT_ACTIVE`). Starting a return mints a `ReturnShipment` in `LABEL_ISSUED` status linked by `rental_id` with a generated `carrier_label`, moves the rental's `status` from `ACTIVE` to `RETURN_INITIATED`, and moves the physical copy's `status` from `RENTED` to `IN_INSPECTION`.

### 3.6. Inspection, Fee Assessment, and Rental Close

A `WarehouseAgent` inspects a returned copy against an open shipment. Inspection requires the shipment to be in `LABEL_ISSUED` status, else `ERR_RETURN_NOT_OPEN`. The agent reports the graded `reported_condition` observed, the `highlight_pct_reported` share of pages found highlighted (defaulting to 0), and an `is_lost` flag (defaulting to false) set true when the copy was never received. Inspection forks the shipment into exactly one of three terminal outcomes and cascades the linked rental to its close.

Two fees are computed at close. The **late fee** measures lateness against the logical clock at the inspect call: the raw overdue amount is the fractional-day interval from the rental's `due_date` to that instant; the overdue days are the ceiling of that amount but never below zero (so a copy returned on or before its due date is zero days overdue); the chargeable `late_days` are the overdue days beyond a three-day grace, again floored at zero (so charging begins only once overdue days exceed three); and `late_fee_cents` is `late_days` multiplied by 250 cents per day, capped at the title's `replacement_fee_cents`. The **damage fee** compares conditions and highlighting. Using a grade rank where `NEW` is 0, `LIKE_NEW` is 1, `GOOD` is 2, and `ACCEPTABLE` is 3, the severity is the assessed `reported_condition` rank minus the copy's original `condition_grade` rank — the value the copy held before this close overwrites it — but never below zero; the condition portion of the fee is that severity multiplied by 1500 cents per grade step. For highlighting, when the title's `highlighting_allowed` is true, the overage is the `highlight_pct_reported` beyond the title's `max_highlight_pct` (charged only when the reported percentage strictly exceeds the maximum) and the highlight portion is that overage multiplied by 200 cents per percentage point, rounded half up; when `highlighting_allowed` is false instead, the highlight portion is a flat 2500 cents whenever any highlighting was reported (`highlight_pct_reported` greater than zero) and nothing otherwise. The `damage_fee_cents` is the sum of the condition and highlight portions, capped at the title's `list_price_cents`. The rental records the highlighting it was returned with in `highlight_pct_used`.

The fork resolves as follows. When `is_lost` is false and both the computed damage fee and late fee are zero, the shipment closes as `CLOSED_GOOD`. When `is_lost` is false but either the damage fee is greater than zero or the late fee is greater than zero, the shipment closes as `CLOSED_DAMAGED` and its own `damage_fee_cents` is set to the computed damage fee. In both of these no-loss outcomes the linked rental is driven from `RETURN_INITIATED` to `CLOSED_RETURNED`: the system stores the computed `late_days`, `late_fee_cents`, and `damage_fee_cents` on the rental; appends a `WalletTransaction` of `kind` `LATE_FEE` for the negative late fee when that fee is above zero; appends a `WalletTransaction` of `kind` `DAMAGE_FEE` for the negative damage fee when that fee is above zero; returns the copy's `status` from `IN_INSPECTION` to `AVAILABLE` and overwrites its `condition_grade` with the `reported_condition`; and bubbles the order up from `CONFIRMED` to `COMPLETED`.

When instead `is_lost` is true, or the copy is so overdue that its overdue days exceed the thirty-day loss threshold, the shipment closes as `CLOSED_LOST` and the linked rental is driven to `CLOSED_LOST`. In the loss outcome the rental's `late_fee_cents` and `damage_fee_cents` are both forced to zero, a `WalletTransaction` of `kind` `REPLACEMENT_CHARGE` is appended for the negative of the title's `replacement_fee_cents`, the copy's `status` moves from `IN_INSPECTION` to `RETIRED`, and the order bubbles up from `CONFIRMED` to `COMPLETED`. A rental that is inspected while overdue beyond the loss threshold reaches `CLOSED_LOST` directly from `ACTIVE` via this same chain, with identical side effects.

The order's `final_charge_cents` is settled as the order bubbles to `COMPLETED`, by the final variant of the order-charge rule, in a pinned evaluation order. For a rental that closed as `CLOSED_RETURNED` the steps are: first the late fee, then the damage fee, then the pre-credit total, which is the order's `quoted_charge_cents` plus the rental's `late_fee_cents` plus its `damage_fee_cents`; then a loyalty credit of 500 cents applies when that pre-credit total is at least 10000 cents and is zero otherwise; and finally the `final_charge_cents` is the pre-credit total minus the loyalty credit. The loyalty tier is keyed on the pre-credit total, not on the post-credit figure. For a rental that closed as `CLOSED_LOST` the `final_charge_cents` is instead the order's `quoted_charge_cents` plus the title's `replacement_fee_cents`, and no loyalty credit is applied.

### 3.7. Selling Back a Copy: The Buyback Flow

A `Customer` who wishes to sell a copy back requests a `BuybackQuote` by naming the `catalog_item_id`, the `declared_condition` they believe the copy is in (one of `NEW`, `LIKE_NEW`, `GOOD`, or `ACCEPTABLE`), and the `expected_customer_version` for the concurrency check described in Section 2.7. The quote is created in `QUOTED` status with a `quoted_price_cents` computed by the buyback-price rule: the title's `buyback_base_cents` multiplied by the condition multiplier for the declared condition — 1.0 for `NEW`, 0.9 for `LIKE_NEW`, 0.75 for `GOOD`, and 0.5 for `ACCEPTABLE` — rounded half up to whole cents. Its `quote_expires_at` is set to the creation instant plus the quote validity window. Because a customer should hold only one open quote per title, requesting a new quote for a `(customer_id, catalog_item_id)` pair supersedes any prior quote still in `QUOTED` status for that same pair by moving it to `SUPERSEDED`, and the create advances the seller's `Customer.version` by one.

Accepting a quote requires it to be in `QUOTED` status, else `ERR_QUOTE_NOT_OPEN`, and requires the logical clock to be strictly before `quote_expires_at`; at or after that instant the quote is expired and acceptance is refused with `ERR_QUOTE_EXPIRED`. Acceptance moves `status` from `QUOTED` to `ACCEPTED` with no ledger change yet.

A `WarehouseAgent` then inspects the received copy against an accepted quote, which requires the quote to be in `ACCEPTED` status, else `ERR_QUOTE_NOT_ACCEPTED`. The agent supplies the `assessed_condition` observed. When the assessed condition equals the seller's `declared_condition`, the quote is paid: `status` moves from `ACCEPTED` to `PAID`, `paid_price_cents` is set to `quoted_price_cents`, a new `InventoryUnit` is created for the title with `condition_grade` equal to the assessed condition and `status` `AVAILABLE` (its identifier recorded in the quote's `inventory_unit_id`), and a `WalletTransaction` of `kind` `BUYBACK_CREDIT` is appended crediting the seller the positive `quoted_price_cents`. When the assessed condition differs from the declared condition, the quote instead moves from `ACCEPTED` to `REVISED` and a `revised_price_cents` is computed by the same buyback-price rule but keyed on the assessed condition — generally a lower offer — while no credit or inventory is created yet.

Faced with a revised offer, the seller responds. Responding requires the quote to be in `REVISED` status, else `ERR_QUOTE_NOT_REVISED`, and carries an `action` of either `ACCEPT` or `DECLINE`. Accepting the revision moves `status` from `REVISED` to `PAID`, sets `paid_price_cents` to `revised_price_cents`, creates the `AVAILABLE` `InventoryUnit` for the title at the assessed condition with its identifier recorded in `inventory_unit_id`, and appends a `WalletTransaction` of `kind` `BUYBACK_CREDIT` for the positive `revised_price_cents`. Declining the revision moves `status` from `REVISED` to `DECLINED`: the copy is conceptually returned to the seller, no credit is paid, and no `InventoryUnit` is created.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Creating a new resource returns HTTP 201; state-changing actions on an existing resource and clock control return HTTP 200; reads return HTTP 200. The request body, response body, and side effects of each endpoint are described in the Section 3 narratives, not repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock | CatalogAdmin |
| POST | `/catalog` | Create a catalog item (ISBN/edition) | CatalogAdmin |
| GET | `/catalog/{id}` | Fetch a catalog item | CatalogAdmin, Customer, WarehouseAgent |
| POST | `/inventory-units` | Add a physical copy of a catalog item | CatalogAdmin |
| GET | `/inventory-units/{id}` | Fetch a physical copy | CatalogAdmin, WarehouseAgent |
| GET | `/inventory-units` | List/filter physical copies | CatalogAdmin, WarehouseAgent |
| POST | `/customers` | Onboard a customer | CatalogAdmin |
| GET | `/customers/{id}` | Fetch a customer (with wallet balance and version) | CatalogAdmin, Customer |
| POST | `/customers/{id}/wallet/adjustments` | Operator wallet adjustment (top-up / manual credit or debit) | CatalogAdmin |
| GET | `/customers/{id}/wallet-transactions` | Fetch the customer's ledger | CatalogAdmin, Customer |
| POST | `/subscription-plans` | Create a subscription plan (STUDY / SOLUTIONS) | CatalogAdmin |
| POST | `/customers/{id}/subscription` | Subscribe the customer to a plan for a period | Customer |
| GET | `/subscriptions/{id}` | Fetch a subscription | Customer, CatalogAdmin |
| GET | `/subscriptions` | List/filter subscriptions | Customer, CatalogAdmin |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription; prorated refund | Customer |
| POST | `/orders` | Place a RENT / BUY / EBOOK order | Customer |
| GET | `/orders/{id}` | Fetch an order | Customer, CatalogAdmin, WarehouseAgent |
| GET | `/orders` | List/filter orders | Customer, CatalogAdmin, WarehouseAgent |
| POST | `/orders/{id}/pay` | Pay for an order from wallet credit | Customer |
| POST | `/orders/{id}/confirm` | Fulfil a paid RENT/BUY order: select and reserve a copy | WarehouseAgent |
| POST | `/orders/{id}/cancel` | Cancel a PENDING order; refund if paid | Customer |
| GET | `/rentals/{id}` | Fetch a rental | Customer, WarehouseAgent |
| GET | `/rentals` | List/filter rentals | Customer, WarehouseAgent |
| POST | `/rentals/{id}/extend` | Extend a rental for a flat fee | Customer |
| POST | `/rentals/{id}/return` | Start a return: mint a label and open a shipment | Customer |
| GET | `/rentals/{id}/return-shipments` | List a rental's return shipments | Customer, WarehouseAgent |
| POST | `/return-shipments/{id}/inspect` | Inspect the returned copy; fork and cascade the close | WarehouseAgent |
| POST | `/buyback-quotes` | Request a buyback price quote | Customer |
| GET | `/buyback-quotes/{id}` | Fetch a buyback quote | Customer, WarehouseAgent |
| GET | `/buyback-quotes` | List/filter buyback quotes | Customer, WarehouseAgent |
| POST | `/buyback-quotes/{id}/accept` | Seller accepts the quote before expiry | Customer |
| POST | `/buyback-quotes/{id}/inspect` | Inspect the received copy; fork to PAID or REVISED | WarehouseAgent |
| POST | `/buyback-quotes/{id}/respond-revision` | Seller accepts or declines a revised offer | Customer |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the Sections 2 and 3 narratives that govern the relevant operation.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_RESOURCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_ORDER_NOT_PAID | 409 |
| ERR_ORDER_NOT_PAYABLE | 409 |
| ERR_RENTAL_NOT_ACTIVE | 409 |
| ERR_RETURN_ALREADY_OPEN | 409 |
| ERR_RETURN_NOT_OPEN | 409 |
| ERR_QUOTE_NOT_OPEN | 409 |
| ERR_QUOTE_NOT_ACCEPTED | 409 |
| ERR_QUOTE_NOT_REVISED | 409 |
| ERR_SUBSCRIPTION_NOT_ACTIVE | 409 |
| ERR_EBOOK_ALREADY_DELIVERED | 422 |
| ERR_ITEM_NOT_RENTABLE | 422 |
| ERR_ITEM_NOT_BUYABLE | 422 |
| ERR_ITEM_NOT_EBOOK_AVAILABLE | 422 |
| ERR_NO_AVAILABLE_UNIT | 409 |
| ERR_UNIT_WINDOW_CONFLICT | 409 |
| ERR_SUBSCRIPTION_PERIOD_OVERLAP | 409 |
| ERR_EBOOK_LICENSE_OVERLAP | 409 |
| ERR_QUOTE_EXPIRED | 409 |
| ERR_MAX_EXTENSIONS_REACHED | 422 |
| ERR_INVALID_TERM | 422 |
| ERR_DUPLICATE_EDITION | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INSUFFICIENT_CREDIT | 402 |
