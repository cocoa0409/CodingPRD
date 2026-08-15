# Fundraiser Product Sale Logistics API — Product Requirements Document

## 1. Introduction

Every fall and spring, PTO fundraising companies run product-sale campaigns at schools: a catalog of gift wrap, cookie dough, or candle products is opened to families for a fixed order window, student sellers collect orders on behalf of their classroom or team, and weeks later a truck arrives with cases that must be sorted into per-student piles, handed out at distribution-day pickup appointments, reconciled against what families actually received, and closed out into per-group proceeds. The operational reality is messy — checks bounce after prizes have been awarded, unsold units come back damaged, a sort table comes up three candles short, and the treasurer needs an auditable, append-only ledger explaining exactly how much each student group earned and why.

This document specifies the Fundraiser Product Sale Logistics API, the system a PTO fundraising company operates to run that lifecycle end to end. The platform covers campaign setup and catalog management with a configurable profit split between each student group and the PTO general fund; seller enrollment with tiered incentive prizes drawn from limited physical stock; family order collection with payment recording, clearing, bouncing, and refunding; supplier order aggregation with case-pack rounding and delivery confirmation; sort-ticket verification, distribution events with capacity-limited pickup appointments; missing/damaged product claims with an appeal chain; an unsold-goods return program with restocking fees; and a final settlement that pins each group's proceeds using actual supplier costs and closes the books to the general fund.

Two design commitments shape everything that follows. First, money is accounted twice on purpose: provisional per-group proceeds are posted the moment an order is submitted (rounded per order line), while final proceeds are computed once at campaign close by summing unrounded per-group shares against supplier-actual costs and rounding a single time, with the rounding remainder absorbed by the PTO general fund. Second, the four operator roles are deliberately segregated — the coordinator who reports a claim may not approve it, the treasurer who recorded a payment may not refund it, and the supplier representative who acknowledged an order may not confirm its delivery — so that no single credential can move money or product unchallenged.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `FundraiserAdmin`, `GroupCoordinator`, `Treasurer`, and `SupplierRep`. A request missing either header, or carrying a role value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the acting role is not listed among an endpoint's permitted roles, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `FundraiserAdmin`, the server may record the identifier (for example, as `submitted_by_user_id` on a supplier order or `reviewed_by_user_id` on a claim) but does not compare it to any entity's `id`. The same holds for `GroupCoordinator` (recorded as `reported_by_user_id` on claims, `requested_by_user_id` on returns, and as the verifying user stamped onto auto-generated shortage claims), for `Treasurer` (recorded as `recorded_by_user_id` on payments and `decided_by_user_id` on return requests), and for `SupplierRep` (recorded as `acknowledged_by_user_id` and `delivered_by_user_id` on supplier orders). Although these identifiers are foreign to the entity model, they drive the segregation-of-duties checks described in §2.9 — the server compares the acting `X-User-ID` against the recorded operator identifier on the targeted resource, never against a persisted user row.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; like every other timestamp in the system, it reads the logical clock of §2.5.
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

Requests that match no declared route (or use an unsupported method on one) are rejected with `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure yields `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Ledger listings (campaign-level and group-level) are the explicit exception: they are ordered by `created_at` ascending with `seq` ascending as the tie-break, matching the ledger's replay order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus `limit` is strictly less than `total_count`.

### 2.4. Common Resource Properties

All primary resources — Campaign, StudentGroup, Product, IncentivePrize, Seller, Order, OrderLine, Payment, SupplierOrder, SupplierOrderLine, DistributionEvent, SortTicket, PickupAppointment, ReconciliationClaim, ReturnRequest, and PrizeAward — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp recording the last modification; refreshed on every mutation.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments by 1 with every modification to the resource; it backs the optimistic concurrency control described in §2.8. At creation `created_at` and `updated_at` are equal.

The one exception is `ProceedsLedgerEntry`, the append-only proceeds ledger row. Ledger entries carry only `id` and `created_at` from the common set — they are never mutated after insertion, so both `updated_at` and `version` are absent from the resource.

### 2.5. The Logical Clock

The server maintains a logical clock rather than consulting wall-clock time, so that a campaign's time-dependent rules are fully deterministic and testable. At startup, before any clock-setting call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time. A `FundraiserAdmin` may set the logical clock to a supplied instant via the test-driving capability that accepts `to_iso8601` and echoes the new `current_utc` with a 200 response; the supplied instant is applied verbatim, whether it lies before or after the current reading. Every rule in this document that says "the current time" or "now" — order-window containment, the return window, event start checks, the `submitted_at` stamp, the `distribution_completed_at` stamp, and prize qualification timestamps — reads this logical clock.

### 2.6. Money, Units, and Rounding

All monetary values are integer cents; the API never represents money as fractional decimal numbers. All unit quantities (ordered, delivered, distributed, returned, lost) are whole units. Where a calculation cannot avoid a fractional intermediate — per-line provisional proceeds, restocking fees, claim loss debits, return debits, and the per-group final share — rounding is always to the nearest whole cent using round half up (a fraction of exactly one-half cent rounds away from zero). The two proceeds variants differ only in *when* the rounding happens: the provisional computation rounds each order line's share to whole cents before summing across the order, whereas the final settlement sums unrounded per-line shares across an entire student group and rounds exactly once per group. Basis-point shares (`default_profit_share_bps`, `profit_share_bps`) are integers from 0 to 10000 inclusive, where 10000 represents one hundred percent.

### 2.7. The Append-Only Proceeds Ledger

Every student group has a signed, append-only ledger of `ProceedsLedgerEntry` rows, and the group's `proceeds_balance_cents` is nothing more than the balance after the latest entry. Each entry records the `group_id` whose balance it moves, the denormalized `campaign_id`, an `entry_type` drawn from `PROVISIONAL_CREDIT`, `SALE_REVERSAL_DEBIT`, `BOUNCE_FEE_DEBIT`, `RETURN_DEBIT`, `CLAIM_LOSS_DEBIT`, `PRIZE_COST_DEBIT`, `PRIZE_COST_REVERSAL`, `FINAL_TRUE_UP_CREDIT`, `FINAL_TRUE_UP_DEBIT`, or `MANUAL_ADJUSTMENT`, a signed `amount_cents` (credits positive, debits negative), a polymorphic `reference_type` — one of `ORDER`, `PAYMENT`, `RETURN_REQUEST`, `CLAIM`, `PRIZE_AWARD`, or `CAMPAIGN` — paired with `reference_id` identifying the originating entity of that type, a human-readable `memo`, a per-group monotonic `seq` starting at 1, and the computed `balance_after_cents` — the group's balance immediately after that entry.

Entries for a group are replayed in `created_at` ascending order with `seq` ascending as the tie-break — never by `id` — starting from a zero baseline: each entry's `seq` is one greater than the previous maximum for the group, and each `balance_after_cents` is the previous entry's `balance_after_cents` plus the entry's `amount_cents`. A group with no entries has a `proceeds_balance_cents` of 0. Ledger entries are never updated or deleted; corrections are posted as new entries. A `Treasurer` may post a `MANUAL_ADJUSTMENT` entry to a group by supplying a signed `amount_cents` and a `memo`; such an entry is created with a 201 response and immediately moves the group's balance. For `MANUAL_ADJUSTMENT` entries both `reference_type` and `reference_id` are null, the `memo` carrying the context.

### 2.8. Optimistic Concurrency Control

Three write endpoints are guarded by optimistic concurrency control, and each requires its own non-optional version field naming the parent entity's `version` as the client last observed it:

- Editing campaign settings requires `expected_campaign_version` to match the campaign's current `version`. If the campaign's version has advanced since the client last read it, the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting settings it has not observed.
- Editing a product's catalog fields requires `expected_product_version` to match the product's current `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).
- Revising a DRAFT supplier order's line quantities requires `expected_supplier_order_version` to match the supplier order's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Because two sequential settings edits are both legitimate under product semantics, the stale writer is detected purely by this version check. Endpoints not listed above do not take a version field.

### 2.9. Segregation of Duties

The platform enforces four actor-separation rules, each rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when violated:

- The `FundraiserAdmin` approving or denying a reconciliation claim must not be the `GroupCoordinator` who reported it — the acting `X-User-ID` must differ from the claim's `reported_by_user_id`.
- The `Treasurer` approving or rejecting a return request must not be the `GroupCoordinator` who filed it — the acting `X-User-ID` must differ from the return's `requested_by_user_id`.
- The `Treasurer` refunding a payment must not be the treasurer who recorded it — the acting `X-User-ID` must differ from the payment's `recorded_by_user_id`.
- The `SupplierRep` confirming delivery of a supplier order must not be the representative who acknowledged it — the acting `X-User-ID` must differ from the supplier order's `acknowledged_by_user_id`.

A related but distinct rule governs voids: only the treasurer who recorded a payment may void it. A void attempted by any other user is rejected with `ERR_NOT_PAYMENT_RECORDER` (HTTP 403).

### 2.10. Nested Resource Retrieval and Validation Ordering

The API's resources are peers linked by references rather than deeply nested URL hierarchies; the only nested paths are read-only collection listings (the groups, products, prizes, sellers, supplier orders, distribution events, and ledger of a campaign; the sellers and ledger of a group; the order lines and supplier order lines of a product; the lines and payments of an order; the lines of a supplier order). When a path does contain multiple identifiers, the server validates their existence left to right and rejects with the per-segment 404 error for the first identifier that does not correspond to an existing resource: `ERR_CAMPAIGN_NOT_FOUND`, `ERR_GROUP_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PRIZE_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_SUPPLIER_ORDER_NOT_FOUND`, `ERR_DISTRIBUTION_EVENT_NOT_FOUND`, `ERR_SORT_TICKET_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or `ERR_PRIZE_AWARD_NOT_FOUND`, as applicable. A body-supplied order line identifier that does not exist yields `ERR_ORDER_LINE_NOT_FOUND`.

Across a single request, checks run in a fixed priority order so that earlier failures mask later ones deterministically. First the authentication and role checks of §2.1 (`ERR_UNAUTHENTICATED`, then `ERR_UNAUTHORIZED_ROLE`). Second, path-segment existence, left to right (the 404 family above). Third, request-body schema validation — required fields present, types and enum members valid, integer ranges respected, non-empty line arrays — rejected with `ERR_VALIDATION` (HTTP 400); a submit request for an order with no lines fails here, as do incomplete `line_costs` or `delivered` coverage maps. Fourth, idempotency replay: an `idempotency_key` resubmitted to the same endpoint for the same seller (on order creation) or the same order (on payment recording) with a *different* payload than the original request is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409); resubmitted with an *identical* payload, the server returns the original stored response verbatim — same status code and body — without re-executing the operation. Fifth, body foreign keys must resolve to existing entities, each yielding its entity-specific 404 (`ERR_PRODUCT_NOT_FOUND` for product ids inside order lines, `ERR_GROUP_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_DISTRIBUTION_EVENT_NOT_FOUND`). Sixth, the OCC version check of §2.8 (`ERR_STALE_VERSION`). Seventh, state-machine admission: the target entity — or, for creates, the related entity whose lifecycle gates creation — must be in a permitting state, else `ERR_INVALID_STATE` (HTTP 409). Eighth, segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). Ninth, temporal window rules (for example `ERR_OUTSIDE_ORDER_WINDOW`, `ERR_ORDER_WINDOW_NOT_YET_CLOSED`, `ERR_RETURN_WINDOW_EXPIRED`, `ERR_RETURN_WINDOW_NOT_ELAPSED`, `ERR_EVENT_NOT_STARTED`, `ERR_APPOINTMENT_WINDOW_OUTSIDE`). Tenth, cross-entity consistency: body entities must belong to the same campaign (`ERR_CROSS_CAMPAIGN_REFERENCE`), and a supplied `order_line_id` must belong to the supplied `order_id` (`ERR_ORDER_LINE_MISMATCH`). Eleventh, business constraints — uniqueness, overlaps, capacity, quantity availability, limits, and policy gates (the 409/422 family including `ERR_DUPLICATE_SKU`, `ERR_DUPLICATE_GROUP_NAME`, `ERR_DUPLICATE_SELLER_NAME`, `ERR_VENUE_OVERLAP`, `ERR_SLOT_CAPACITY_EXCEEDED`, `ERR_QUANTITY_INVALID`, `ERR_CLAIM_QTY_EXCEEDS_AVAILABLE`, `ERR_RETURN_QTY_EXCEEDS_AVAILABLE`, `ERR_INSUFFICIENT_SURPLUS`, `ERR_PER_SELLER_LIMIT_EXCEEDED`, `ERR_PRODUCT_NOT_RETURNABLE`, `ERR_PRODUCT_NOT_ORDERABLE`, `ERR_PAYMENT_METHOD_NOT_BOUNCEABLE`, `ERR_CAMPAIGN_HAS_ACTIVE_SUPPLIER_ORDER`, `ERR_NO_SUBMITTED_ORDERS`, `ERR_SORT_TICKETS_ALREADY_GENERATED`, `ERR_UNVERIFIED_SORT_TICKETS`, `ERR_OPEN_CLAIMS_OR_RETURNS`, `ERR_CAMPAIGN_CANCEL_BLOCKED`, `ERR_ORDER_HAS_CLEARED_PAYMENTS`, `ERR_APPEAL_LIMIT_EXCEEDED`). Twelfth and last, money guards: overpayment (`ERR_OVERPAYMENT`) and refunds exceeding remaining cleared value (`ERR_REFUND_EXCEEDS_CLEARED`).

### 2.11. Cascading State Propagation and Recomputation

Many single operations fan out across entities. When a parent resource transitions, dependent children move with it: closing ordering cancels every DRAFT order and locks every SUBMITTED one; acknowledging and delivering a supplier order advances the campaign in lockstep; cancelling a distribution event cancels its BOOKED appointments; withdrawing a seller cancels their unpaid orders and forfeits their pending prize awards. In the reverse direction, leaf events recompute ancestors: every payment create, clear, bounce, refund, or void re-derives the order's `cleared_cents` and `payment_status`; every mutation that touches orders, payments, claims, returns, or the supplier order refreshes the campaign's computed totals; and every change to a seller's metrics re-runs prize evaluation for that seller. Each mutation of a resource refreshes its `updated_at` and increments its `version` by 1, and campaign transitions increment the campaign's `version` by 1 as stated at each transition. Every lifecycle-bearing resource exposes its current state in a `status` field — supplemented on orders by the derived `payment_status` and the fulfillment-side `fulfillment_status` — whose exact enumeration values appear throughout §3.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Campaign: Settings, Catalog, Groups, and Prizes

A `FundraiserAdmin` opens a new fundraiser by creating a **Campaign** with its display `name`, the `school_name` of the partnering organization, the order window bounds `order_window_start` and `order_window_end`, the planned `expected_delivery_date`, and the `default_profit_share_bps` — the default share of each line's net profit credited to the seller's student group, expressed in basis points, with the remainder flowing to the PTO general fund. The order window end must be strictly later than its start, and the expected delivery date must be strictly later than the order window end; violations are rejected with `ERR_VALIDATION` (HTTP 400). A new campaign's computed totals start at zero (`gross_sales_cents`, `family_credits_cents`, `estimated_supplier_cost_cents`, `actual_supplier_cost_cents`), with `distribution_completed_at` and `general_fund_cents` null until distribution completes and the final settlement runs, respectively. The campaign begins in `DRAFT` and passes through `OPEN`, `ORDERING_CLOSED`, `SUPPLIER_ORDERED`, `DELIVERED`, `SORTED`, `DISTRIBUTION_COMPLETE`, `RECONCILED`, and finally `CLOSED`; `CANCELLED` is the alternative terminal state reachable from `DRAFT` or `OPEN`.

While the campaign is in `DRAFT`, the admin builds the catalog. Each **Product** is created with a `name`, a catalog `sku` unique within the campaign (a duplicate is rejected with `ERR_DUPLICATE_SKU`), the family-facing `unit_price_cents` (strictly positive), the estimated `supplier_unit_cost_cents` (zero or greater), and the `case_pack_size` (at least 1) in which the supplier ships whole cases. Three optional fields tune policy: `profit_share_bps`, which overrides the group share for this product and, when omitted, snapshots the campaign's `default_profit_share_bps` at creation; `per_seller_limit`, an optional cap on the cumulative units of this product one seller may carry across non-cancelled orders, where a null value means unlimited and a provided value must be at least 1; and `returnable`, which defaults to true and governs whether unsold units of this product may come back. Products may only be created while the campaign is in `DRAFT`; attempting catalog creation later yields `ERR_INVALID_STATE`. A product starts `ACTIVE` with all five unit buckets at zero, and may be discontinued while the campaign is `DRAFT` or `OPEN` — discontinuing a product that is not `ACTIVE`, or discontinuing while the campaign is past `OPEN`, is rejected with `ERR_INVALID_STATE` — moving it to `DISCONTINUED`, bumping the product's `version`, and leaving existing order-line snapshots untouched — but any later order submit naming that product fails with `ERR_PRODUCT_NOT_ORDERABLE`.

Catalog edits and campaign-settings edits are the OCC-guarded surfaces of §2.8. A settings edit is admitted only while the campaign is in `DRAFT` and may touch any of `name`, `school_name`, `order_window_start`, `order_window_end`, `expected_delivery_date`, or `default_profit_share_bps` alongside the mandatory `expected_campaign_version`; the merged result must still satisfy the ordering rules — window end strictly after start, expected delivery strictly after window end — else `ERR_VALIDATION`, and a successful edit increments the campaign's `version` by 1. A product edit is admitted while the campaign is `DRAFT` or `OPEN`, may touch `name`, `unit_price_cents`, `supplier_unit_cost_cents`, `profit_share_bps`, `per_seller_limit`, or `returnable` alongside the mandatory `expected_product_version`, never retro-changes prices or costs already snapshotted onto submitted order lines, and increments the product's `version` by 1.

In parallel, a `GroupCoordinator` enrolls the participating structure. Each **StudentGroup** is created with its `campaign_id`, a `name` unique within the campaign (duplicates rejected with `ERR_DUPLICATE_GROUP_NAME`), and an optional `teacher_name` that defaults to null. Each **Seller** is enrolled into a group by `group_id` with a `display_name` unique within that group (duplicates rejected with `ERR_DUPLICATE_SELLER_NAME`); the seller's `campaign_id` is denormalized from the group at creation and never changes. Group and seller creation are admitted while the campaign is `DRAFT` or `OPEN`. A seller begins `ENROLLED`, flips automatically to `ACTIVE` the moment their first order reaches `SUBMITTED`, may be suspended (`ACTIVE` → `SUSPENDED`) and later reinstated (`SUSPENDED` → `ACTIVE`) by a coordinator, and may be withdrawn from any of `ENROLLED`, `ACTIVE`, or `SUSPENDED` into the terminal `WITHDRAWN` — but only when no order of theirs carries cleared value, otherwise the withdrawal is rejected with `ERR_ORDER_HAS_CLEARED_PAYMENTS`. Withdrawal cascades: the seller's DRAFT and SUBMITTED orders are cancelled (SUBMITTED ones posting their reversal per §3.2), and the seller's prize awards in `QUEUED` or `AWARDED` move to `FORFEITED`, restoring stock, posting `PRIZE_COST_REVERSAL` for `AWARDED` ones, and running queue promotion per §3.8.

The admin also configures the incentive program while the campaign is `DRAFT` or `OPEN`. Each **IncentivePrize** carries a `name`, a `tier_type` of `UNITS_SOLD`, `REVENUE_CENTS`, or `ORDERS_COUNT` selecting which seller metric the threshold reads, a strictly positive `threshold_value` the seller's metric must reach (the boundary is inclusive — a metric exactly equal to the threshold qualifies), a non-negative `prize_cost_cents` charged back to the winner's group at award time, and a `stock_quantity` of physical prizes available, zero or greater (zero is permitted — every qualifier then queues). The prize's computed `remaining_quantity` is its `stock_quantity` minus the count of its awards in `AWARDED` or `FULFILLED`.

With at least one `ACTIVE` product and at least one student group in place — otherwise the open attempt is rejected with `ERR_CAMPAIGN_NOT_READY` — the admin opens the campaign, moving it `DRAFT` → `OPEN`. Opening before the order window has passed its end is required in the other direction too: if the logical clock has already reached or passed `order_window_end`, opening is rejected with `ERR_INVALID_STATE`. Opening increments the campaign's `version` by 1.

A campaign may instead be abandoned: cancellation by a `FundraiserAdmin` is permitted from `DRAFT` or `OPEN` only when no order of the campaign carries cleared value, otherwise `ERR_CAMPAIGN_CANCEL_BLOCKED`. Cancelling a campaign cascades — every DRAFT or SUBMITTED order moves to `CANCELLED` (SUBMITTED cancellations each posting a `SALE_REVERSAL_DEBIT` per §3.2, skipped when the credit is zero), and every payment still in `RECORDED` is moved to `VOIDED`.

### 3.2. Taking Orders and Collecting Family Payments

While the campaign is `OPEN`, a `GroupCoordinator` records each family's order. Order creation takes the `seller_id`, the `family_contact_name`, and an inline `lines` array whose elements name a `product_id` and a `quantity` of at least 1; an optional `idempotency_key` scoped to the endpoint and seller protects against duplicate submissions, and its replay rules follow §2.10. Creation requires the campaign to be `OPEN` — attempting to create against a non-open campaign is rejected with `ERR_CAMPAIGN_NOT_OPEN` — and the seller must already be orderable: creating for a `WITHDRAWN` seller is rejected with `ERR_INVALID_STATE` and for a `SUSPENDED` seller with `ERR_SELLER_SUSPENDED`. Creation produces an **Order** in `DRAFT` whose `campaign_id` and `group_id` are denormalized from the seller at creation; proceeds attribution never moves thereafter.

Submitting the order is the pivotal act, and its preconditions are evaluated in the priority order of §2.10: the order must be in `DRAFT` (else `ERR_INVALID_STATE`); the campaign must be `OPEN` (else `ERR_CAMPAIGN_NOT_OPEN`); the logical clock must lie at or after `order_window_start` and at or before `order_window_end` (else `ERR_OUTSIDE_ORDER_WINDOW`); the seller must be `ENROLLED` or `ACTIVE` (submitting for a `SUSPENDED` seller is rejected with `ERR_SELLER_SUSPENDED`; a `WITHDRAWN` seller fails the state check with `ERR_INVALID_STATE`); the order must carry at least one line (else `ERR_VALIDATION`); every line's product must still be `ACTIVE` (else `ERR_PRODUCT_NOT_ORDERABLE`); and per line, the cumulative quantity of that product across the seller's non-cancelled orders — including the submitting order — must not exceed the product's `per_seller_limit` when one is set (else `ERR_PER_SELLER_LIMIT_EXCEEDED`).

A successful submit snapshots each line: `unit_price_cents` and `unit_cost_cents` are copied from the product onto the `OrderLine`, and `line_total_cents` is computed as the line's `quantity` times its snapshotted `unit_price_cents` with exact integer arithmetic. The order's `total_cents` is the sum of its lines' `line_total_cents`. The submit stamps `submitted_at` with the logical clock, and it posts the seller's group a single `PROVISIONAL_CREDIT` ledger entry referenced to the order: per line, the line's share is the line total minus the line's `quantity` times its snapshotted `unit_cost_cents`, multiplied by the product's `profit_share_bps` and divided by 10000, rounded half up to whole cents *per line*; the order's `provisional_credit_cents` is the sum of those rounded line shares, and that sum is the entry's `amount_cents`. The seller's metrics are recomputed (see §3.8), prize evaluation runs for the seller, and an `ENROLLED` seller flips to `ACTIVE`.

An order in `DRAFT` may be cancelled freely by a coordinator with no ledger impact. Cancelling a `SUBMITTED` order is admitted only while the campaign is `OPEN` or `ORDERING_CLOSED` and only when the order's `cleared_cents` is zero (else `ERR_ORDER_HAS_CLEARED_PAYMENTS`); it posts a `SALE_REVERSAL_DEBIT` to the seller's group equal to the order's `provisional_credit_cents` — no entry is posted when that credit is zero — recomputes seller metrics, and re-runs prize evaluation — which may forfeit awards and promote the queue. Once `LOCKED`, an order can no longer be cancelled directly; it awaits the campaign close sweep of §3.7.

Payments are the `Treasurer`'s domain. Recording a payment takes the `order_id`, a strictly positive `amount_cents`, a `method` of `CASH`, `CHECK`, or `CARD`, and an optional `external_ref` (check number or card reference, defaulting to null), plus an optional `idempotency_key` scoped to the endpoint and order. The order must be in `SUBMITTED`, `LOCKED`, or `COMPLETED` (else `ERR_INVALID_STATE`), and the new payment must not push the order's recorded-plus-cleared coverage — the sum over its payments in `RECORDED` or `CLEARED` of each `amount_cents` minus `refunded_amount_cents` — above its `total_cents`; overpayment is rejected with `ERR_OVERPAYMENT`. A recorded payment begins in `RECORDED` with `recorded_by_user_id` stamped from the acting header and `refunded_amount_cents` at 0.

The order's `payment_status` is a pure derivation over its payments, recomputed after every payment create, clear, bounce, refund, or void: `cleared_cents` is the sum over the order's payments in `CLEARED` status — and only those; `RECORDED`, `BOUNCED`, `VOIDED`, and `REFUNDED` payments contribute nothing — of each payment's `amount_cents` minus its `refunded_amount_cents`. The order is `UNPAID` when `cleared_cents` is zero, `PAID` when `cleared_cents` equals `total_cents` (with `total_cents` positive), and `PARTIALLY_PAID` when `cleared_cents` lies strictly between. Because overpayment is rejected at record time, cleared value can never exceed the total. The lifecycle begins at `UNPAID` and moves among the three values as the derivation dictates — `UNPAID` → `PARTIALLY_PAID` or `PAID` as value clears, and regressions `PAID` → `PARTIALLY_PAID` or `UNPAID`, and `PARTIALLY_PAID` → `UNPAID`, when bounces or refunds drain cleared value. Every regression recomputes the seller's `revenue_cents` and re-runs prize evaluation, with possible forfeiture and queue promotion.

A `RECORDED` payment is cleared by a treasurer (`RECORDED` → `CLEARED`), which counts it toward `cleared_cents`, re-derives the order's payment status, recomputes the seller's `revenue_cents`, and runs prize evaluation. A `RECORDED` payment may instead be voided by the same treasurer who recorded it — anyone else is rejected with `ERR_NOT_PAYMENT_RECORDER` — moving it to `VOIDED`; since `RECORDED` payments never counted toward cleared value, the order's payment status is unchanged by a void.

A `CLEARED` check that bounces moves `CLEARED` → `BOUNCED`. Bouncing is admitted only for payments whose `method` is `CHECK` (a bounce attempt on `CASH` or `CARD` is rejected with `ERR_PAYMENT_METHOD_NOT_BOUNCEABLE`), only while the payment's `refunded_amount_cents` is still zero, and only while the campaign is neither `CLOSED` nor `CANCELLED` — the latter two gates fail with `ERR_INVALID_STATE`. The bounce accepts an optional `reason`. Its side effects ripple: a `BOUNCE_FEE_DEBIT` entry for the fixed bounce fee of 2500 cents is posted to the order's group, the order's cleared value and payment status are re-derived (possibly regressing `PAID` → `PARTIALLY_PAID` or `UNPAID`), the seller's `revenue_cents` is recomputed, and prize evaluation runs with possible forfeiture and queue promotion.

A `CLEARED` payment may be refunded, partially or in full, by a treasurer who is not the payment's recorder (segregation per §2.9). The refund supplies an `amount_cents` that must not exceed the payment's remaining un-refunded value — its `amount_cents` minus its `refunded_amount_cents` — else `ERR_REFUND_EXCEEDS_CLEARED`, and the order must not be `CANCELLED` (else `ERR_INVALID_STATE`). The refunded amount accumulates into `refunded_amount_cents`; when that accumulation reaches the payment's full `amount_cents` the payment moves to `REFUNDED`, otherwise it remains `CLEARED`. The order's cleared value and payment status are re-derived, the seller's `revenue_cents` recomputed, and prize evaluation runs with possible forfeiture and queue promotion.

### 3.3. Closing Ordering and Aggregating the Supplier Order

Once the order window has fully passed — the logical clock at or past `order_window_end`, else the close attempt is rejected with `ERR_ORDER_WINDOW_NOT_YET_CLOSED` — the admin closes ordering, moving the campaign `OPEN` → `ORDERING_CLOSED`. The cascade is immediate: every order still in `DRAFT` for the campaign is cancelled with no ledger impact, every `SUBMITTED` order moves to `LOCKED`, seller metrics are recomputed (the removal of DRAFT orders from the input set is a no-op since they never counted, and the newly `LOCKED` orders remain in the input set), and the campaign's `version` increments by 1.

With ordering closed, the admin creates the campaign's **SupplierOrder** in `DRAFT`. Creation requires the campaign to be `ORDERING_CLOSED`, and only one active supplier order may exist per campaign — creating a second while a non-cancelled, non-delivered one exists is rejected with `ERR_CAMPAIGN_HAS_ACTIVE_SUPPLIER_ORDER`. Creation aggregates demand per product: for each product of the campaign (whether `ACTIVE` or `DISCONTINUED`), `requested_units` is the sum of line quantities over order lines whose orders are in `SUBMITTED` or `LOCKED` — `CANCELLED` and `DRAFT` orders are excluded — and a product whose aggregated demand is zero is omitted from the supplier order entirely. Each surviving product becomes a **SupplierOrderLine** carrying the `supplier_order_id` and `product_id`, the `requested_units`, a `case_pack_size` snapshotted from the product, and a `unit_cost_estimated_cents` snapshotted from the product's `supplier_unit_cost_cents`. Case-pack rounding applies at creation: `ordered_cases` is `requested_units` divided by `case_pack_size` rounded up to a whole number, and `ordered_units` is `ordered_cases` times `case_pack_size`. The supplier order's `total_ordered_units` is the sum of `ordered_units` across its lines.

While the supplier order remains in `DRAFT`, the admin may revise it: a revision supplies `line_adjustments` alongside the mandatory `expected_supplier_order_version` per §2.8, re-derives cases and units per the same case-pack rule, and increments the supplier order's `version` by 1. Each element of `line_adjustments` addresses one line of the supplier order either by the line's own `line_id` or by the `product_id` the line aggregates (creation produces at most one line per product per supplier order, so either key is unambiguous) and supplies that line's new `requested_units`, an integer of zero or greater (zero is permitted — the line then rounds up to zero cases); when an element carries both keys, `line_id` takes precedence, an element carrying neither is rejected with `ERR_VALIDATION`, and an element whose addressed line does not exist on the supplier order is likewise rejected with `ERR_VALIDATION`. A DRAFT or SUBMITTED supplier order may also be cancelled outright, moving it to `CANCELLED`.

Submitting the supplier order moves it `DRAFT` → `SUBMITTED`, requires at least one supplier order line (an order with zero aggregated units is rejected with `ERR_NO_SUBMITTED_ORDERS`), pins the `estimated_cost_cents` as the sum over lines of `ordered_units` times `unit_cost_estimated_cents`, and stamps `submitted_by_user_id` from the acting admin. A mistaken submission can be walked back: unsubmitting returns `SUBMITTED` → `DRAFT` and increments the supplier order's `version` by 1, reopening the revision loop.

The supplier side then takes over. A `SupplierRep` acknowledges a `SUBMITTED` order, moving it to `ACKNOWLEDGED`. The acknowledgement supplies a `confirmed_delivery_date` and a `line_costs` map — accepted either as a JSON object keyed by `product_id` or as an array of entries each naming `product_id` and its cost — whose values are integer cents of zero or greater and that must cover every line's product exactly once, with no extras (incomplete, duplicate, or excess coverage is rejected with `ERR_VALIDATION`); it sets each line's `unit_cost_actual_cents`, stamps `acknowledged_by_user_id`, and — as a cross-entity cascade — automatically advances the campaign from `ORDERING_CLOSED` to `SUPPLIER_ORDERED`, incrementing the campaign's `version` by 1.

Delivery confirmation is a second, separately-authorized `SupplierRep` act: acknowledging delivery moves the supplier order `ACKNOWLEDGED` → `DELIVERED`. The delivery supplies an `actual_delivery_date` and a `delivered` map — accepted either as a JSON object keyed by `product_id` or as an array of entries each naming `product_id` and `delivered_units` — whose values are whole units of zero or greater and that must cover every line's product exactly once, with no extras (else `ERR_VALIDATION`), with each line's `delivered_units` no greater than its `ordered_units` (else `ERR_QUANTITY_INVALID`); per §2.9, the delivering representative must differ from the one who acknowledged, else `ERR_SEGREGATION_OF_DUTIES`. Delivery stamps `delivered_by_user_id`, sets each line's `delivered_units` and computes each line's `shortage_units` as `ordered_units` minus `delivered_units`, and pins the supplier order's `actual_cost_cents` as the sum over lines of `delivered_units` times `unit_cost_actual_cents`. The campaign then advances automatically from `SUPPLIER_ORDERED` to `DELIVERED` with its version incremented, and each product's unit buckets absorb the physical receipt: the product's `delivered_units` is set to its line's `delivered_units`, and the same quantity is added into the product's `surplus_units` — the unallocated pile from which distribution will draw. The campaign's `estimated_supplier_cost_cents` mirrors the non-cancelled supplier order's estimate (zero when none exists), and its `actual_supplier_cost_cents` mirrors the delivered order's actual cost, staying zero until delivery.

### 3.4. Sorting Day: Tickets, Shortages, and Auto-Claims

Once the truck has been confirmed, a `GroupCoordinator` generates the sort plan for the `DELIVERED` campaign. Generation is one-shot: if sort tickets already exist for the campaign, the attempt is rejected with `ERR_SORT_TICKETS_ALREADY_GENERATED`. It creates one **SortTicket** per (seller, product) pair with aggregated sold units, each stamped with the denormalized `campaign_id`, the `seller_id`, the `product_id`, an `expected_qty` equal to the pair's aggregated sold units at generation time, and a `distribution_event_id` pointing at the campaign's earliest `SCHEDULED` distribution event — earliest by `window_start` ascending with `created_at` ascending as the tie-break — or null when no event has been scheduled yet. The generation call returns a `created_count` and the list of `ticket_ids`. Each ticket begins `PENDING` with `verified_qty` null.

Verification is the physical count. A coordinator verifies a `PENDING` ticket by supplying `verified_qty`, which must lie between zero and the ticket's `expected_qty` inclusive (else `ERR_QUANTITY_INVALID`). When the count matches expectation, the ticket moves to `VERIFIED`. When the count falls short, the ticket moves to `SHORT` and the system performs a three-way cascade. First, the unit buckets move: the gap — `expected_qty` minus `verified_qty` — is subtracted from the product's `surplus_units` and added to its `lost_units`. Second, the gap is allocated onto the seller's non-cancelled order lines for that product, choosing the line with the greatest `submitted_at` first and breaking ties by the greatest line quantity, and adding the gap into that line's `sort_shortage_qty`. Third, the system auto-creates a **ReconciliationClaim** on that line with `claim_type` `MISSING`, `quantity` equal to the gap, `auto_generated` true, and `reported_by_user_id` set to the verifying user — the claim then flows through the normal adjudication of §3.6.

Only when every sort ticket of the campaign has left `PENDING` — each one `VERIFIED` or `SHORT`, else the mark-sorted attempt is rejected with `ERR_UNVERIFIED_SORT_TICKETS` — may the coordinator mark the campaign sorted, moving it `DELIVERED` → `SORTED`. The cascade moves every non-cancelled order whose `fulfillment_status` is still `PENDING` to `SORTED`, and increments the campaign's `version` by 1.

### 3.5. Distribution Day: Events, Appointments, and Hand-Off

Distribution events may be scheduled once the campaign is `SUPPLIER_ORDERED` or beyond — specifically while the campaign is in `SUPPLIER_ORDERED`, `DELIVERED`, `SORTED`, `DISTRIBUTION_COMPLETE`, or `RECONCILED` — by a `GroupCoordinator` supplying the `campaign_id`, a `venue` label, a half-open occupancy window from `window_start` (inclusive) to `window_end` (exclusive, and strictly later than the start, else `ERR_VALIDATION`), and a `slot_capacity` of at least 1 bounding how many booked pickups may overlap at any instant. Two `SCHEDULED` events for the same campaign and venue may not have overlapping half-open windows; an overlapping creation is rejected with `ERR_VENUE_OVERLAP`. An event begins `SCHEDULED`, may be completed by a coordinator once the logical clock has reached its `window_start` (completing earlier is rejected with `ERR_EVENT_NOT_STARTED`), moving it to `COMPLETED`, and may instead be cancelled (`SCHEDULED` → `CANCELLED`), which cascades its `BOOKED` appointments to `CANCELLED`.

Families pick up their orders through **PickupAppointment** bookings. Booking takes the `distribution_event_id`, the `order_id`, and a slot from `slot_start` (inclusive) to `slot_end` (exclusive). The event must be `SCHEDULED` and the order's fulfillment must be `SORTED` (else `ERR_INVALID_STATE`); the event and the order must belong to the same campaign (else `ERR_CROSS_CAMPAIGN_REFERENCE`). The slot must be contained within the event's window — `slot_start` at or after `window_start`, and `slot_end` strictly after `slot_start` and at or before `window_end` — else `ERR_APPOINTMENT_WINDOW_OUTSIDE`. Capacity is enforced at every instant: if the new booking would push the number of concurrently overlapping `BOOKED` appointments above the event's `slot_capacity` at any instant, the booking is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`. An appointment begins `BOOKED`; a coordinator later completes it with an `outcome` of `COMPLETED` or `NO_SHOW`, moving it accordingly, or cancels it outright to `CANCELLED`.

When at least one of the campaign's distribution events has reached `COMPLETED` — an attempt with no `COMPLETED` event is rejected with `ERR_INVALID_STATE` — and every pickup appointment across the campaign's events has left `BOOKED` — each in `COMPLETED`, `NO_SHOW`, or `CANCELLED`, else the completion attempt is rejected with `ERR_OPEN_CLAIMS_OR_RETURNS` — the coordinator completes distribution, moving the campaign `SORTED` → `DISTRIBUTION_COMPLETE`. The cascade is the heart of hand-off: for each order whose `payment_status` is `PAID` and whose fulfillment is `SORTED`, fulfillment advances to `DISTRIBUTED`, and per line the effective handed-out quantity is the line's `quantity` minus its `sort_shortage_qty` minus its `claim_resolved_refund_qty`; that effective quantity is added to the product's `distributed_units` and subtracted from its `surplus_units` (a line whose effective quantity is zero leaves the buckets untouched). Orders not fully paid keep fulfillment `SORTED` — they hold their pile until money arrives or the close sweep cancels them. The campaign stamps `distribution_completed_at` with the logical clock, anchoring the return window of §3.6, runs a full prize-evaluation sweep across all sellers of the campaign, and increments its `version` by 1.

### 3.6. After the Sale: Reconciliation Claims and Returns

Two remediation channels open after sorting and distribution, and they share one adjudication philosophy: the school side reports, the company side decides, and never the same credential twice.

**Claims.** A `GroupCoordinator` files a **ReconciliationClaim** against an order line by supplying the `order_id`, the `order_line_id` (which must belong to that order, else `ERR_ORDER_LINE_MISMATCH`, and must resolve, else `ERR_ORDER_LINE_NOT_FOUND`), a `claim_type` of `MISSING` or `DAMAGED`, a `quantity` of at least 1, and an optional `note` defaulting to null. The order's fulfillment must be `SORTED`, `DISTRIBUTED`, or `PARTIALLY_RETURNED` (else `ERR_INVALID_STATE`), the order and line must belong to the same campaign context as one another (mismatches surface as `ERR_CROSS_CAMPAIGN_REFERENCE` where applicable), and the claimed quantity must not exceed the line's availability net of returns already received, claims already resolved as refunds, sort shortage allocated to the line, and the quantities of sibling claims on the same line still in `SUBMITTED` or `APPROVED` — else `ERR_CLAIM_QTY_EXCEEDS_AVAILABLE`. The claim's `campaign_id` is denormalized from the order. A claim begins `SUBMITTED` with `reported_by_user_id` stamped.

A `FundraiserAdmin` other than the reporter (segregation per §2.9) approves or denies a `SUBMITTED` claim, stamping `reviewed_by_user_id`; denial accepts an optional `reason`. A `DENIED` claim may be appealed once by a coordinator: the appeal is admitted only when the claim's `supersedes_claim_id` is null — only a root claim may be appealed, one appeal per chain, else `ERR_APPEAL_LIMIT_EXCEEDED` — and it moves the denied claim to `APPEALED` while creating a successor claim in `SUBMITTED` that copies the order, line, type, quantity, and `auto_generated` flag, sets its `supersedes_claim_id` to the denied claim's `id`, stamps its `reported_by_user_id` with the appealing coordinator, and accepts a fresh optional `note`. The appeal endpoint returns the successor claim with a 201 response, and the successor then runs the same adjudication.

An `APPROVED` claim is resolved by a `FundraiserAdmin` supplying a `resolution` of `REPLACEMENT` or `REFUND`, and the two branches diverge sharply. A **replacement** — moving the claim to `RESOLVED_REPLACEMENT` — is admitted only while the order's fulfillment is `DISTRIBUTED` or `PARTIALLY_RETURNED` (else `ERR_INVALID_STATE`) and only while the product's `surplus_units` covers the claimed quantity (else `ERR_INSUFFICIENT_SURPLUS`). It draws the replacement from the unallocated pile: the product's `surplus_units` decreases by the quantity, the family keeps the same net units so `distributed_units` is unchanged, and when the claim type is `DAMAGED` the scrapped unit is added to the product's `lost_units`. No money moves and no ledger entry is posted for a replacement; the claim's `credit_cents` is zero. A **refund** — moving the claim to `RESOLVED_REFUND` — computes the family `credit_cents` as the claim's `quantity` times the line's snapshotted `unit_price_cents`, adds the quantity into the line's `claim_resolved_refund_qty`, and posts a `CLAIM_LOSS_DEBIT` to the order's group equal to the quantity times the difference between the line's snapshotted `unit_price_cents` and `unit_cost_cents`, multiplied by the product's `profit_share_bps` and divided by 10000, rounded half up to whole cents. When the order's fulfillment is `DISTRIBUTED` or `PARTIALLY_RETURNED`, a refund additionally moves the quantity out of the product's `distributed_units` and into its `lost_units` — except for auto-generated sort claims, which skip this bucket move because their units were already counted lost at ticket verification. Either resolution recomputes the order's fulfillment status, recomputes seller metrics, and re-runs prize evaluation.

**Returns.** The return channel opens only after distribution completes: creating a **ReturnRequest** requires the campaign to be in `DISTRIBUTION_COMPLETE` or `RECONCILED` (else `ERR_INVALID_STATE`), and the logical clock must be at or before `distribution_completed_at` plus 7 days — the final instant of day seven is still eligible; later attempts are rejected with `ERR_RETURN_WINDOW_EXPIRED`. A coordinator files the return with the `seller_id`, the `order_id`, the `order_line_id` (which must belong to the order, else `ERR_ORDER_LINE_MISMATCH`), a `quantity` of at least 1, and a `reason` of `UNSOLD`, `DEFECTIVE`, `WRONG_ITEM`, or `FAMILY_CHANGED_MIND`. The seller must match the order's seller (else `ERR_CROSS_CAMPAIGN_REFERENCE`). The product must be `returnable`, else `ERR_PRODUCT_NOT_RETURNABLE`. The requested quantity must not exceed the line's availability: the line's `quantity` minus its `returned_qty`, its `claim_resolved_refund_qty`, and its `sort_shortage_qty`, further reduced by the quantities of sibling return requests on the same line still in `REQUESTED` or `APPROVED` — a request beyond that is rejected with `ERR_RETURN_QTY_EXCEEDS_AVAILABLE`. The return's `campaign_id` is denormalized from the order, it begins `REQUESTED` with `requested_by_user_id` stamped, and `resubmission_count` starts at 0.

A `Treasurer` other than the filer approves or rejects a `REQUESTED` return (segregation per §2.9), stamping `decided_by_user_id`; rejection accepts an optional `reason`. Approval pins the money: the per-unit restocking fee is zero when the reason is `DEFECTIVE` or `WRONG_ITEM`, and otherwise is the line's snapshotted `unit_price_cents` times 1000 basis points divided by 10000, rounded half up to whole cents per unit; the return's `restocking_fee_cents` is that per-unit fee times the `quantity`, and its `refund_cents` is the `quantity` times the snapshotted `unit_price_cents` minus the `restocking_fee_cents`. A `REJECTED` return may be resubmitted by a coordinator with a revised `quantity` and `reason` while the return window is still open (else `ERR_RETURN_WINDOW_EXPIRED`); the product must still be `returnable` (else `ERR_PRODUCT_NOT_RETURNABLE`), the revised quantity must satisfy the same availability check as creation — with the resubmitted request itself excluded from the sibling tally (else `ERR_RETURN_QTY_EXCEEDS_AVAILABLE`) — and the resubmission moves the request back to `REQUESTED` and increments `resubmission_count` by 1.

Physical receipt is the treasurer's final act on an `APPROVED` return, supplying a `disposition`. A `RESTOCKABLE` receipt moves the return to `RECEIVED_RESTOCKED`, adds the quantity into the line's `returned_qty`, moves the quantity from the product's `distributed_units` into its `restocked_units`, and posts a `RETURN_DEBIT` to the seller's group equal to the quantity times the difference between the line's snapshotted `unit_price_cents` and `unit_cost_cents`, multiplied by the product's `profit_share_bps` and divided by 10000, rounded half up to whole cents. A `DAMAGED_WRITE_OFF` receipt moves the return to `RECEIVED_WRITTEN_OFF` with the same `returned_qty` accumulation and the same `RETURN_DEBIT` formula, but the quantity lands in the product's `written_off_units` instead of `restocked_units`. Either receipt recomputes the order's fulfillment status, recomputes seller metrics, and re-runs prize evaluation — with possible forfeiture and queue promotion.

Order fulfillment tracks these flows across three parallel states. From `DISTRIBUTED`, a return receipt or a post-distribution claim refund that reduces held units below the original quantity — but not to zero across every line — moves the order to `PARTIALLY_RETURNED`. When every line's `returned_qty` plus `claim_resolved_refund_qty` reaches its full `quantity`, the order moves to the terminal `RETURNED`, either in one step from `DISTRIBUTED` or from `PARTIALLY_RETURNED`.

### 3.7. Reconciliation and Final Settlement

The campaign leaves `DISTRIBUTION_COMPLETE` only when the dust has settled. Reconciliation by a `FundraiserAdmin` requires the logical clock to be strictly later than `distribution_completed_at` plus 7 days — reconciling while the return window is still running, including its final instant, is rejected with `ERR_RETURN_WINDOW_NOT_ELAPSED` — and requires that no claim of the campaign remain in `SUBMITTED` or `APPROVED` and no return request remain in `REQUESTED`, `APPROVED`, or `REJECTED` (open items reject the reconcile with `ERR_OPEN_CLAIMS_OR_RETURNS`). Reconciliation moves the campaign to `RECONCILED` and increments its `version` by 1.

Closing the books is the `Treasurer`'s act, moving the campaign `RECONCILED` → `CLOSED` and running the final settlement in a pinned evaluation order that breaks the apparent cycle between metrics, prizes, and shares. First, seller metrics are already final — the reconcile gate guarantees no open claims or returns and an expired return window. Second, the prize sweep has already been applied and prize chargebacks stand as posted. Third, each line's actual unit cost is read from the campaign's `DELIVERED` supplier order — the `unit_cost_actual_cents` of the matching supplier order line; a product with no line on that supplier order (or, pathologically, no delivered supplier order at all) falls back to the line's snapshotted `unit_cost_cents`. Fourth, per group, the unrounded final share is summed across all lines of the group's sellers' non-cancelled orders: for each line, the effective quantity — `quantity` minus `returned_qty` minus `claim_resolved_refund_qty` minus `sort_shortage_qty` — times the difference between the line's snapshotted `unit_price_cents` and the actual unit cost, times the product's `profit_share_bps`, divided by 10000; the group's `final_proceeds_cents` is that sum rounded half up to whole cents, rounded exactly once per group. Fifth, the true-up: the difference between the group's freshly computed final share and its `provisional_proceeds_cents` — the sum of the group's `PROVISIONAL_CREDIT` entries minus its `SALE_REVERSAL_DEBIT` entries — is posted as a `FINAL_TRUE_UP_CREDIT` when positive or a `FINAL_TRUE_UP_DEBIT` carrying the signed (negative) difference when negative, and skipped entirely when zero; the group's `final_proceeds_cents` is pinned (null until this moment), and its `provisional_proceeds_cents` is refreshed to the recomputed sum. Sixth, the PTO remainder: the campaign's total net is the sum over the same line set of effective quantity times the difference between price and actual cost, and `general_fund_cents` is that total net minus the sum of all groups' final proceeds minus the campaign's `family_credits_cents` — the general fund deliberately absorbs the per-group rounding remainder.

The close also sweeps: every prize award still `QUEUED` moves to `EXPIRED`; every order that is `PAID` with fulfillment `DISTRIBUTED`, `PARTIALLY_RETURNED`, or `RETURNED` moves to `COMPLETED`; and every order still in `SUBMITTED` or `LOCKED` with `cleared_cents` of zero is cancelled with a `SALE_REVERSAL_DEBIT` posted equal to its `provisional_credit_cents` (no entry when that credit is zero, per §3.2). The campaign's `version` increments by 1. The campaign's computed totals — `gross_sales_cents` (the sum of `total_cents` over orders in `SUBMITTED`, `LOCKED`, or `COMPLETED`) and `family_credits_cents` (the sum of `credit_cents` over claims in `RESOLVED_REFUND` plus the sum of `refund_cents` over returns in `RECEIVED_RESTOCKED` or `RECEIVED_WRITTEN_OFF`) — are maintained continuously on every order, payment, claim, return, and supplier-order mutation, so at close they simply stand.

### 3.8. Seller Metrics, Prize Evaluation, and the Unit Ledger

Three seller metrics drive the incentive program and are recomputed after every order submit or cancel, every payment clear, bounce, or refund, every return receipt, and every claim resolution. A seller's `units_sold` is the sum, over lines of the seller's orders in `SUBMITTED`, `LOCKED`, or `COMPLETED`, of each line's `quantity` minus its `returned_qty` minus its `claim_resolved_refund_qty`. A seller's `revenue_cents` is the sum, over payments in `CLEARED` status on the seller's orders that are not `CANCELLED`, of each payment's `amount_cents` minus its `refunded_amount_cents`. A seller's `orders_count` is the count of the seller's orders in `SUBMITTED`, `LOCKED`, or `COMPLETED`.

Prize evaluation runs whenever a seller's metrics are recomputed, and sweeps the full campaign roster at complete-distribution (sellers visited in `created_at` ascending order). For each prize of the seller's campaign — evaluated in the prizes' `created_at` ascending order — the tier metric is selected by `tier_type` — `units_sold` for `UNITS_SOLD`, `revenue_cents` for `REVENUE_CENTS`, `orders_count` for `ORDERS_COUNT` — and the seller qualifies when the metric is at least the prize's `threshold_value`, the boundary inclusive. A newly qualifying seller with no existing award for the same seller and tier type in `QUEUED`, `AWARDED`, or `FULFILLED` — one award per seller per tier type, the first qualifying prize of that tier sticks until forfeited — receives a **PrizeAward** recording the `seller_id`, the `prize_id`, and the denormalized `campaign_id`: if the prize's `remaining_quantity` is greater than zero, the award is created directly in `AWARDED`, a `PRIZE_COST_DEBIT` of the prize's `prize_cost_cents` is posted to the seller's group, and the award records the `qualifying_metric_value` at qualification time; if stock is exhausted, the award is created in `QUEUED`, ordering the promotion queue by `qualified_at` ascending with the seller's `created_at` ascending breaking ties. Either way the award stamps `qualified_at` from the logical clock at creation. When a recompute finds a seller no longer qualifying — metric fallen below the threshold after a bounce, refund, cancel, return, or claim — an award in `QUEUED` or `AWARDED` moves to `FORFEITED`: `QUEUED` forfeiture is silent, while `AWARDED` forfeiture posts a `PRIZE_COST_REVERSAL` crediting the `prize_cost_cents` back to the seller's group, restores the stock, and then promotes the head of that prize's `QUEUED` queue — provided the head still qualifies — moving it to `AWARDED` and posting its own `PRIZE_COST_DEBIT` to the promoted seller's group. Awards in `AWARDED` are handed over physically when a coordinator fulfills them — admitted while the campaign is `SORTED`, `DISTRIBUTION_COMPLETE`, `RECONCILED`, or `CLOSED` (else `ERR_INVALID_STATE`) — moving the award to `FULFILLED`. As noted in §3.7, campaign close expires everything still `QUEUED`.

Underpinning all of it, each product conserves units across five buckets whose invariant must always hold: `delivered_units` equals the sum of `distributed_units`, `restocked_units`, `written_off_units`, `surplus_units`, and `lost_units`. The buckets move at five moments — supplier delivery (sets `delivered_units`, adds into `surplus_units`), sort-ticket shortage verification (moves the gap from `surplus_units` to `lost_units`), complete-distribution (moves each line's effective quantity from `surplus_units` to `distributed_units`), claim resolution (replacement draws from `surplus_units`, adding to `lost_units` when the claim is `DAMAGED`; post-distribution refunds move from `distributed_units` to `lost_units`, except auto-generated sort claims whose units were already lost at verification), and return receipt (moves from `distributed_units` into `restocked_units` or `written_off_units` by disposition).

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — state transitions, edits, verifications, resolutions — return a `200 OK` status code. All endpoints are mounted under `/fundraiser`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fundraiser/_clock/set_current_utc` | Set the logical clock | FundraiserAdmin |
| POST | `/fundraiser/campaigns` | Create campaign in DRAFT | FundraiserAdmin |
| GET | `/fundraiser/campaigns/{id}` | Read campaign incl. computed totals | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| PATCH | `/fundraiser/campaigns/{id}` | Edit campaign settings (DRAFT only), OCC-guarded | FundraiserAdmin |
| POST | `/fundraiser/campaigns/{id}/open` | DRAFT → OPEN | FundraiserAdmin |
| POST | `/fundraiser/campaigns/{id}/close-ordering` | OPEN → ORDERING_CLOSED; cancels DRAFT orders, locks SUBMITTED | FundraiserAdmin |
| POST | `/fundraiser/campaigns/{id}/mark-sorted` | DELIVERED → SORTED; requires all sort tickets verified/short | GroupCoordinator |
| POST | `/fundraiser/campaigns/{id}/complete-distribution` | SORTED → DISTRIBUTION_COMPLETE; distributes PAID orders, prize sweep | GroupCoordinator |
| POST | `/fundraiser/campaigns/{id}/reconcile` | DISTRIBUTION_COMPLETE → RECONCILED; gates on closed claims/returns and elapsed return window | FundraiserAdmin |
| POST | `/fundraiser/campaigns/{id}/close` | RECONCILED → CLOSED; runs final settlement | Treasurer |
| POST | `/fundraiser/campaigns/{id}/cancel` | DRAFT/OPEN → CANCELLED; blocked when cleared payments exist | FundraiserAdmin |
| POST | `/fundraiser/campaigns/{id}/generate-sort-tickets` | Bulk-generate per-(seller, product) sort tickets (campaign DELIVERED) | GroupCoordinator |
| GET | `/fundraiser/campaigns/{id}/groups` | List groups of a campaign | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/campaigns/{id}/products` | List products of a campaign | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/campaigns/{id}/prizes` | List prizes of a campaign | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/campaigns/{id}/sellers` | List sellers of a campaign | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/campaigns/{id}/supplier-orders` | List supplier orders of a campaign | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/campaigns/{id}/distribution-events` | List distribution events of a campaign | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/campaigns/{id}/ledger` | All ledger entries of a campaign, ordered (created_at ASC, seq ASC) | FundraiserAdmin, Treasurer |
| POST | `/fundraiser/groups` | Create student group (campaign DRAFT or OPEN) | GroupCoordinator |
| GET | `/fundraiser/groups/{id}` | Read group incl. computed proceeds balances | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/groups/{id}/sellers` | List sellers of a group | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/groups/{id}/ledger` | Ledger entries of a group, ordered (created_at ASC, seq ASC) | FundraiserAdmin, Treasurer |
| POST | `/fundraiser/groups/{id}/adjustments` | Post a MANUAL_ADJUSTMENT ledger entry (signed amount) | Treasurer |
| POST | `/fundraiser/products` | Create product (campaign DRAFT only) | FundraiserAdmin |
| GET | `/fundraiser/products/{id}` | Read product incl. unit buckets | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| PATCH | `/fundraiser/products/{id}` | Edit catalog fields (campaign DRAFT or OPEN), OCC-guarded | FundraiserAdmin |
| POST | `/fundraiser/products/{id}/discontinue` | ACTIVE → DISCONTINUED (campaign DRAFT or OPEN) | FundraiserAdmin |
| GET | `/fundraiser/products/{id}/order-lines` | Order lines referencing this product | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/products/{id}/supplier-order-lines` | Supplier order lines referencing this product | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/prizes` | Create incentive prize (campaign DRAFT or OPEN) | FundraiserAdmin |
| GET | `/fundraiser/prizes/{id}` | Read prize incl. remaining_quantity | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/sellers` | Enroll seller in a group (campaign DRAFT or OPEN) | GroupCoordinator |
| GET | `/fundraiser/sellers/{id}` | Read seller incl. computed metrics | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/sellers/{id}/suspend` | ACTIVE → SUSPENDED | GroupCoordinator |
| POST | `/fundraiser/sellers/{id}/reinstate` | SUSPENDED → ACTIVE | GroupCoordinator |
| POST | `/fundraiser/sellers/{id}/withdraw` | ENROLLED/ACTIVE/SUSPENDED → WITHDRAWN; cancels unpaid orders, forfeits awards | GroupCoordinator |
| POST | `/fundraiser/orders` | Create order in DRAFT with inline lines | GroupCoordinator |
| GET | `/fundraiser/orders` | List/filter orders | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/orders/{id}` | Read order incl. computed payment fields | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/orders/{id}/submit` | DRAFT → SUBMITTED; snapshots prices, posts provisional credit, evaluates prizes | GroupCoordinator |
| POST | `/fundraiser/orders/{id}/cancel` | DRAFT/SUBMITTED → CANCELLED with reversal | GroupCoordinator |
| GET | `/fundraiser/orders/{id}/lines` | Lines of an order | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/orders/{id}/payments` | Payments of an order | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/payments` | Record a family payment (RECORDED) | Treasurer |
| POST | `/fundraiser/payments/{id}/clear` | RECORDED → CLEARED; counts toward cleared_cents | Treasurer |
| POST | `/fundraiser/payments/{id}/bounce` | CLEARED CHECK → BOUNCED; bounce fee debit | Treasurer |
| POST | `/fundraiser/payments/{id}/refund` | Partially or fully refund a CLEARED payment; actor ≠ recorder | Treasurer |
| POST | `/fundraiser/payments/{id}/void` | RECORDED → VOIDED by the recording treasurer | Treasurer |
| POST | `/fundraiser/supplier-orders` | Create DRAFT supplier order by aggregating SUBMITTED/LOCKED orders with case-pack rounding | FundraiserAdmin |
| GET | `/fundraiser/supplier-orders/{id}` | Read supplier order | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/supplier-orders/{id}/lines` | Lines of a supplier order | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| PATCH | `/fundraiser/supplier-orders/{id}` | Adjust requested_units per line while DRAFT, OCC-guarded | FundraiserAdmin |
| POST | `/fundraiser/supplier-orders/{id}/submit` | DRAFT → SUBMITTED; pins estimated cost | FundraiserAdmin |
| POST | `/fundraiser/supplier-orders/{id}/unsubmit` | SUBMITTED → DRAFT revision loop | FundraiserAdmin |
| POST | `/fundraiser/supplier-orders/{id}/acknowledge` | SUBMITTED → ACKNOWLEDGED; sets actual unit costs and confirmed delivery date | SupplierRep |
| POST | `/fundraiser/supplier-orders/{id}/deliver` | ACKNOWLEDGED → DELIVERED; records delivered units; deliverer ≠ acknowledger | SupplierRep |
| POST | `/fundraiser/supplier-orders/{id}/cancel` | DRAFT/SUBMITTED → CANCELLED | FundraiserAdmin |
| POST | `/fundraiser/distribution-events` | Schedule a distribution event; venue half-open overlap check | GroupCoordinator |
| GET | `/fundraiser/distribution-events/{id}` | Read distribution event | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/distribution-events/{id}/complete` | SCHEDULED → COMPLETED (requires now ≥ window_start) | GroupCoordinator |
| POST | `/fundraiser/distribution-events/{id}/cancel` | SCHEDULED → CANCELLED; cancels BOOKED appointments | GroupCoordinator |
| GET | `/fundraiser/sort-tickets` | List/filter sort tickets; deterministic order created_at ASC | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/sort-tickets/{id}` | Read sort ticket | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/sort-tickets/{id}/verify` | Verify counted units; shortage marks SHORT, moves units to lost, auto-creates a MISSING claim | GroupCoordinator |
| POST | `/fundraiser/pickup-appointments` | Book a family pickup slot; slot containment + capacity overlap check | GroupCoordinator |
| GET | `/fundraiser/pickup-appointments` | List/filter pickup appointments | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/pickup-appointments/{id}` | Read pickup appointment | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/pickup-appointments/{id}/complete` | BOOKED → COMPLETED or NO_SHOW | GroupCoordinator |
| POST | `/fundraiser/pickup-appointments/{id}/cancel` | BOOKED → CANCELLED | GroupCoordinator |
| POST | `/fundraiser/reconciliation-claims` | File a MISSING/DAMAGED claim on an order line | GroupCoordinator |
| GET | `/fundraiser/reconciliation-claims` | List/filter claims | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/reconciliation-claims/{id}` | Read claim | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/reconciliation-claims/{id}/approve` | SUBMITTED → APPROVED; approver ≠ reporter | FundraiserAdmin |
| POST | `/fundraiser/reconciliation-claims/{id}/deny` | SUBMITTED → DENIED; approver ≠ reporter | FundraiserAdmin |
| POST | `/fundraiser/reconciliation-claims/{id}/appeal` | DENIED → APPEALED; creates successor claim (one appeal per claim) | GroupCoordinator |
| POST | `/fundraiser/reconciliation-claims/{id}/resolve` | APPROVED → RESOLVED_REPLACEMENT or RESOLVED_REFUND | FundraiserAdmin |
| POST | `/fundraiser/return-requests` | Request a return (window + availability + returnable checks) | GroupCoordinator |
| GET | `/fundraiser/return-requests` | List/filter returns | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/return-requests/{id}` | Read return request | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/return-requests/{id}/approve` | REQUESTED → APPROVED; approver ≠ requester; pins refund | Treasurer |
| POST | `/fundraiser/return-requests/{id}/reject` | REQUESTED → REJECTED; approver ≠ requester | Treasurer |
| POST | `/fundraiser/return-requests/{id}/resubmit` | REJECTED → REQUESTED with revised quantity/reason while window open | GroupCoordinator |
| POST | `/fundraiser/return-requests/{id}/receive` | APPROVED → RECEIVED_RESTOCKED or RECEIVED_WRITTEN_OFF | Treasurer |
| GET | `/fundraiser/prize-awards` | List/filter prize awards | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| GET | `/fundraiser/prize-awards/{id}` | Read prize award | FundraiserAdmin, GroupCoordinator, Treasurer, SupplierRep |
| POST | `/fundraiser/prize-awards/{id}/fulfill` | AWARDED → FULFILLED (campaign SORTED or later) | GroupCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INTERNAL` | 500 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_PAYMENT_RECORDER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_GROUP_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_PRIZE_NOT_FOUND` | 404 |
| `ERR_SELLER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_SUPPLIER_ORDER_NOT_FOUND` | 404 |
| `ERR_DISTRIBUTION_EVENT_NOT_FOUND` | 404 |
| `ERR_SORT_TICKET_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_PRIZE_AWARD_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CAMPAIGN_NOT_READY` | 409 |
| `ERR_CAMPAIGN_NOT_OPEN` | 409 |
| `ERR_OUTSIDE_ORDER_WINDOW` | 422 |
| `ERR_ORDER_WINDOW_NOT_YET_CLOSED` | 422 |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 |
| `ERR_RETURN_WINDOW_NOT_ELAPSED` | 422 |
| `ERR_EVENT_NOT_STARTED` | 422 |
| `ERR_APPOINTMENT_WINDOW_OUTSIDE` | 422 |
| `ERR_SELLER_SUSPENDED` | 409 |
| `ERR_PRODUCT_NOT_ORDERABLE` | 409 |
| `ERR_PER_SELLER_LIMIT_EXCEEDED` | 422 |
| `ERR_DUPLICATE_SKU` | 409 |
| `ERR_DUPLICATE_GROUP_NAME` | 409 |
| `ERR_DUPLICATE_SELLER_NAME` | 409 |
| `ERR_QUANTITY_INVALID` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_REFUND_EXCEEDS_CLEARED` | 422 |
| `ERR_PAYMENT_METHOD_NOT_BOUNCEABLE` | 422 |
| `ERR_ORDER_HAS_CLEARED_PAYMENTS` | 409 |
| `ERR_VENUE_OVERLAP` | 409 |
| `ERR_SLOT_CAPACITY_EXCEEDED` | 422 |
| `ERR_CROSS_CAMPAIGN_REFERENCE` | 422 |
| `ERR_ORDER_LINE_MISMATCH` | 422 |
| `ERR_CAMPAIGN_HAS_ACTIVE_SUPPLIER_ORDER` | 409 |
| `ERR_NO_SUBMITTED_ORDERS` | 422 |
| `ERR_INSUFFICIENT_SURPLUS` | 422 |
| `ERR_APPEAL_LIMIT_EXCEEDED` | 409 |
| `ERR_CLAIM_QTY_EXCEEDS_AVAILABLE` | 422 |
| `ERR_RETURN_QTY_EXCEEDS_AVAILABLE` | 422 |
| `ERR_PRODUCT_NOT_RETURNABLE` | 422 |
| `ERR_SORT_TICKETS_ALREADY_GENERATED` | 409 |
| `ERR_UNVERIFIED_SORT_TICKETS` | 409 |
| `ERR_OPEN_CLAIMS_OR_RETURNS` | 409 |
| `ERR_CAMPAIGN_CANCEL_BLOCKED` | 409 |
