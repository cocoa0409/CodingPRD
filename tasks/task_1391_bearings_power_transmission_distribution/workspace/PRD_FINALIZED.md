# Bearings Power Transmission Distribution API — Product Requirements Document

## 1. Introduction

Distributing bearings and power-transmission components is a business of urgent minutes and slow contracts. A plant maintenance manager whose line goes down at 2 a.m. needs an after-hours branch call-out and a technician who can pull a sealed bearing off the shelf — even if that shelf stock is nominally reserved for someone else's order. A pricing desk, meanwhile, rolls list-price files forward on published effective dates while long-standing customer contracts lag behind, protecting loyal accounts from increases for a negotiated number of days. Between those two tempos sit consigned stock cabinets at customer plants, factory-direct sourcing with tier-dependent lead times, failed-bearing warranty analysis, surplus and obsolete returns, and referrals to independent repair shops when a failure turns out to be misapplication rather than defect.

This document specifies the REST API for such a distribution operation, mounted under the `/motion` prefix. It covers the product catalog with competitor-part interchange mapping, customer accounts with credit enforcement, family-scoped pricing contracts, branch stock with reservations, dual-axis sales orders (fulfillment and billing evolve independently), emergency call-outs, consignment billing in two variants, warranty claims with tiered credit, return authorizations with a credit-netting waterfall, and a selector-driven repair-shop referral workflow. Time is a first-class input: the server maintains a logical clock that drives scheduled transitions, and every "now" in this document refers to that logical clock.

The intended readers are the engineers implementing the service. Business rules are presented in narrative form; endpoint paths and HTTP methods are consolidated in Section 4, while Sections 2 and 3 define the semantics that those endpoints must honor.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other check runs. If the named role is not permitted to invoke the target endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The role names, spelled exactly as the server must recognize them, are `SystemAdmin`, `PricingAnalyst`, `ContractAdministrator`, `CounterSalesRep`, `BranchManager`, `OnCallTechnician`, `WarrantyAnalyst`, `QualityEngineer`, `CustomerPlant`, `ServiceShop`, and the pseudo-role `Any`. `Any` is never supplied as a header value; it denotes that every authenticated role may call the endpoint — all read (GET) endpoints are authorized for `Any`.

Identity semantics differ by role. For `SystemAdmin`, `PricingAnalyst`, `ContractAdministrator`, `CounterSalesRep`, `BranchManager`, `OnCallTechnician`, `WarrantyAnalyst`, and `QualityEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `published_by` on a price file, `responder_id` on a call-out, `filed_by` or `verdict_by` on a warranty claim, `requested_by` or `approved_by` on a return authorization — but it does not compare it to any entity's `id`. For `CustomerPlant`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID`. For `ServiceShop`, `X-User-ID` is the `id` of the acting `ServiceShop`, and a referral action is only valid when the referral's `service_shop_id` equals `X-User-ID`; otherwise the server rejects with `ERR_REFERRAL_SHOP_MISMATCH` (HTTP 403). An entity-backed role acting on a resource owned by a different entity is rejected with `ERR_IDENTITY_MISMATCH` (HTTP 403) — this guards a `CustomerPlant` reporting consumption on another customer's agreement, disputing another customer's billing, cancelling another customer's call-out, requesting a return naming another `customer_id`, and a `ServiceShop` acting on a referral assigned to a different shop.

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

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100; `offset` defaults to 0. List responses are sorted by `created_at` ascending, and the `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and the Logical Clock

Every persisted resource has an `id` that is a server-minted UUID with no type prefix. Resources with the common field set — every entity in this system except the interchange record — also carry `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, and an integer `version` that increments by exactly 1 on every mutation of that resource. An interchange record is immutable once created and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it. Wherever this document says a mutation "bumps the version," it means `version` increases by 1 and `updated_at` refreshes to the logical-clock instant of the mutation.

The server maintains a logical clock. At startup, before any explicit set, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A `SystemAdmin` may advance the logical clock to a supplied `to_iso8601` instant; this is the only way time moves. Advancing the clock fires every scheduled transition whose instant has been reached — price files going from `PENDING` to `EFFECTIVE`, contracts from `ACTIVE` to `EXPIRED`, reservations from `ACTIVE` to `EXPIRED`, and approved returns lapsing to `EXPIRED` — and when several transitions fall due at the same instant they fire in `created_at` ascending order within that instant. Branch-local rules never use UTC directly: local time is always the logical clock shifted by the branch's `timezone_offset_hours`.

### 2.5. Validation Order and Error Precedence

When a request violates several rules, the first failing check by the following priority order determines the response; later checks are not evaluated against a request that has already failed. Priority 1: the `X-User-ID` and `X-User-Role` headers must be present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400) — this applies to all endpoints. Priority 2: the role must be permitted for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, 403). Priority 3: every path resource id must exist, validated left to right along the path, and every body-supplied foreign key (`customer_id`, `branch_id`, `product_id`, `order_line_id`, `consumption_id`, `branch_stock_id`, `warranty_claim_id`) must also exist before any state or business rule runs; each missing resource yields its own not-found error with HTTP 404 — `ERR_PRODUCT_NOT_FOUND`, `ERR_INTERCHANGE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_BRANCH_NOT_FOUND`, `ERR_BRANCH_STOCK_NOT_FOUND`, `ERR_PRICE_FILE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_CALL_OUT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_CONSUMPTION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, or `ERR_REFERRAL_NOT_FOUND`, according to the resource addressed. Priority 4: entity-backed identity — a `CustomerPlant` may act only on its own customer account's resources and a `ServiceShop` only on referrals whose `service_shop_id` equals its id (`ERR_IDENTITY_MISMATCH`, 403). Priority 5: the target resource must be in the state the requested transition requires (the state-specific 409 errors such as `ERR_ORDER_NOT_CONFIRMABLE` or `ERR_CLAIM_NOT_UNDER_ANALYSIS`). Priority 6: segregation of duties — the verdict-rendering user must differ from the claim's `filed_by` (`ERR_WARRANTY_SOD_VERDICT`, 403), and the return approver or rejector must differ from the return's `requested_by` (`ERR_RETURN_SOD_APPROVAL`, 403). Priority 7: shape and uniqueness constraints — required fields present and well-typed (`ERR_INVALID_REQUEST`, 400), quantities at least 1, branch close hour strictly later than open hour, contract window start strictly before end (`ERR_CONTRACT_WINDOW_INVALID`, 400), a fixed-price contract carrying its pinned price (`ERR_CONTRACT_FIXED_PRICE_MISSING`, 400), product `sku` unique (`ERR_DUPLICATE_SKU`, 400), branch `code` unique (`ERR_DUPLICATE_BRANCH_CODE`, 400), no overlapping active contract window for the same customer and family (`ERR_CONTRACT_WINDOW_OVERLAP`, 409), at most one non-closed consignment agreement per customer, branch, and product (`ERR_DUPLICATE_AGREEMENT`, 409), and a claim referencing exactly one of its two possible sources (`ERR_CLAIM_REFERENCE_INVALID`, 400). Priority 8: time-window rules (`ERR_EFFECTIVE_AT_IN_PAST`, `ERR_CALL_OUT_NOT_AFTER_HOURS`, `ERR_BRANCH_CALLOUT_CAPACITY`, `ERR_FACTORY_ORDER_CUTOFF_PASSED`, `ERR_FACTORY_LEAD_TIME_UNMET`, `ERR_RMA_WINDOW_EXPIRED`, all 409). Priority 9: cross-entity referential rules (for example `ERR_STOCK_LINE_MISMATCH`, `ERR_PARTIAL_RESERVATION`, `ERR_CLAIM_QTY_EXCEEDS_SOURCE`, `ERR_CLAIM_SOURCE_NOT_FINAL`, `ERR_RETURN_QTY_EXCEEDS_SHIPPED`, `ERR_SUPERSEDE_TARGET_INVALID`, `ERR_REFERRAL_VERDICT_NOT_MISAPPLICATION`, `ERR_NO_ELIGIBLE_SHOP`, `ERR_INVALID_RECEIVED_QTY`, `ERR_STOCK_BELOW_RESERVED`, `ERR_CONSIGNMENT_QTY_BELOW_CONSUMED`, `ERR_CONSUMPTION_EXCEEDS_REMAINING`, `ERR_AGREEMENT_CLOSE_BLOCKED`, and `ERR_PRODUCT_NOT_ACTIVE` when an order line names an inactive product; all 409). Priority 10, last: capacity and credit rules — `ERR_INSUFFICIENT_AVAILABLE_STOCK` (409) on reservation and consignment placement, `ERR_CUSTOMER_CREDIT_HOLD` (402) and `ERR_CREDIT_LIMIT_EXCEEDED` (402) on order confirm.

Because existence (priority 3) precedes state (priority 5), a request naming a nonexistent product must fail with 404 even when the request also violates a state rule; because state precedes segregation of duties, a verdict on a claim that is not under analysis fails with `ERR_CLAIM_NOT_UNDER_ANALYSIS` rather than an SoD error; and because all referential checks precede fiscal checks, a reserve request against a mismatched stock record fails with `ERR_STOCK_LINE_MISMATCH` even if the quantity also exceeds availability.

### 2.6. Optimistic Concurrency Control

Exactly three write operations carry an optimistic-concurrency field; no other endpoint accepts a version field.

- Re-pricing an order requires `expected_order_version` in the request body, holding the client's last-observed `version` of the sales order. If the order's current `version` does not match — because a line was added, an expedite tier changed, the order was confirmed, or an earlier reprice ran since the client last read it — the reprice is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Amending a consignment agreement's quantity requires `expected_agreement_version`, the client's last-observed `version` of the agreement. A consumption reported after that read legitimately advanced the agreement (its `consumed_qty` changed), so a stale amendment is rejected with `ERR_STALE_VERSION` (HTTP 412) and must be rebased on a fresh read.
- Publishing a price file requires `expected_product_version`, the client's last-observed `version` of the product. Publishing supersedes the product's currently pending price file, so a writer whose view predates another publish would unknowingly supersede a file it never saw; the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing a fresh read of the product first.

### 2.7. Money, Precision, and Rounding

All monetary amounts are integer cents; fields named with the `_cents` suffix never carry fractional values. Every monetary computation in this system rounds to 0 decimal places (integer cents), and every rounding is round-half-up. Where a calculation involves several rounding steps (discount application, percentage fees, write-downs), each step rounds half-up to integer cents before the next step consumes the result — intermediate fractional cents are never carried. Order-level totals are built per line first and then summed; summing fractional amounts across lines and rounding once at the order level is forbidden. Timestamps anchor every price lookup; the price of anything is meaningless without stating the instant at which it is evaluated.

### 2.8. Stock Accounting and Availability

Each branch keeps one stock record per product, holding `on_hand_qty` (physical units on the shelf) and a derived `reserved_qty`. The reserved quantity is always exactly the sum of `qty` over that stock record's reservations in `ACTIVE` status — reservations in `CONSUMED`, `RELEASED`, `EXPIRED`, or `PREEMPTED` status contribute nothing. Availability is derived, never stored independently: `available_qty` equals `on_hand_qty` minus `reserved_qty`. Shelf quantity mutates on consignment placement and close, on allocation, on factory receipt, on call-out fulfillment, on surplus-return receipt, and on manual adjustment; the reserved quantity recomputes on every reservation create, release, expiry, preemption, or consumption. A manual adjustment takes `qty_delta` and a free-text `reason`, adds the delta to `on_hand_qty`, and is rejected with `ERR_STOCK_BELOW_RESERVED` (409) whenever the resulting shelf quantity would fall below the currently reserved quantity. Every stock mutation bumps the stock record's `version`.

### 2.9. Nested Resource Retrieval

Paths that nest one resource beneath another validate path identifiers left to right: the parent id is resolved first, then the child. A failure at any level yields the not-found error of that level's resource (404) before deeper segments are examined, and before any state or business rule is evaluated, consistent with the priority order in §2.5.

### 2.10. Status Codes

Creating a new resource returns 201 with the created resource in `data`. Every other successful operation — reads, modifications, state transitions, and actions — returns 200 with the affected resource. Errors use the 4xx statuses named with each rule and tabulated in Section 5.

## 3. Business Logic & Workflows

### 3.1. Catalog Stewardship: Products, Interchange, and Price Files

A `PricingAnalyst` builds the catalog one product at a time. Creating a product requires `sku`, `description`, `family`, and `list_price_cents`; the family is one of `BEARING`, `GEARBOX`, `BELT`, `CHAIN`, or `SEAL`, and the `sku` must be unique across the catalog (`ERR_DUPLICATE_SKU`). A new product starts in `ACTIVE` status with `last_price_change_at` null, meaning no price file has ever taken effect for it. Products may be listed with optional `sku`, `family`, `status`, and `superseded_by_id` filters, or fetched individually.

The product lifecycle moves forward only. From `ACTIVE` a `PricingAnalyst` may patch the product to `PHASEOUT`, and from `PHASEOUT` to `OBSOLETE`; a direct leap from `ACTIVE` to `OBSOLETE` is also permitted. Asking for `PHASEOUT` when the product is not `ACTIVE` fails with `ERR_PRODUCT_NOT_ACTIVE` (409); asking for `OBSOLETE` from the `PHASEOUT` leg when the product is not actually in `PHASEOUT` fails with `ERR_PRODUCT_NOT_PHASEOUT` (409). On either transition to `OBSOLETE` the request may carry `superseded_by_id`, a forward pointer to the replacement product; when supplied, the target must exist and be `ACTIVE`, otherwise the update fails with `ERR_SUPERSEDE_TARGET_INVALID` (409). The pointer, when supplied, is persisted on the obsoleted product, and each lifecycle patch bumps the product's `version`. `OBSOLETE` is terminal.

Competitor-part interchange mappings are created once and never change. A mapping names a `competitor_part_number`, the in-catalog `product_id` it interchanges to, an `interchange_class` of `EXACT`, `DIMENSIONAL`, or `FUNCTIONAL`, and the application shaft-diameter envelope `min_shaft_diameter_mm` through `max_shaft_diameter_mm`, both bounds inclusive. The flag `requires_engineering_review` is computed by the server: it is true if and only if the class is `FUNCTIONAL`. Lookups filter by `product_id`, by `competitor_part_number`, or by a `shaft_diameter_mm` probe that matches records whose envelope contains the probe value. Because these records are immutable, they carry no `updated_at` and no `version`.

Price files are how list prices move. A `PricingAnalyst` publishes a price file naming `product_id`, `new_list_price_cents`, and `effective_at`, plus the OCC field `expected_product_version` described in §2.6. The `effective_at` instant must lie strictly in the future of the current logical time at publish, else `ERR_EFFECTIVE_AT_IN_PAST` (409). The new file is born `PENDING`, `published_by` records the analyst's `X-User-ID`, and publishing supersedes the product's previously `PENDING` file, if any — a create-with-supersede pattern that bumps the product's `version`. A still-`PENDING` file may be cancelled by a `PricingAnalyst`, moving it to `CANCELLED`; cancelling anything else fails with `ERR_PRICE_FILE_NOT_PENDING` (409). When the logical clock reaches a pending file's `effective_at`, the file becomes `EFFECTIVE` and, in the same instant, the product's `list_price_cents` takes the file's `new_list_price_cents`, `last_price_change_at` is set to `effective_at`, and the product's `version` bumps with `updated_at` refreshed. If another file of the same product was already `EFFECTIVE`, that older file becomes `SUPERSEDED`. Note the two distinct supersede paths: a pending file can be superseded before ever taking effect (by a newer publish), and an effective file is superseded when the next one takes effect. Price files may be listed with `product_id` and `status` filters.

### 3.2. Commercial Foundations: Customers, Contracts, and Branches

A `ContractAdministrator` onboards a customer plant with a `name` and a `credit_limit_cents`. The account opens with `credit_status` `GOOD`, `status` `ACTIVE`, and `open_receivables_cents` zero. The administrator may later patch `credit_status` (between `GOOD` and `HOLD`) or `status` (between `ACTIVE` and `INACTIVE`); each patch bumps the customer's `version`. Customers may be listed with a `credit_status` filter, and fetching a customer always shows the derived `open_receivables_cents` — the live figure defined in §3.9.

Customer contracts are family-scoped pricing instruments. Drafting one takes `customer_id`, `family`, a `price_basis` of `LIST_LESS` or `CONTRACT_FIXED`, the half-open window `effective_from` (inclusive) to `effective_to` (exclusive), and optionally `discount_pct`, `fixed_unit_price_cents`, and `lag_protection_days`. `discount_pct` is a fraction between 0 and 1 inclusive, defaults to 0, and matters only for `LIST_LESS`; `fixed_unit_price_cents` pins a unit price regardless of list and is required for `CONTRACT_FIXED` (its absence surfaces at activation as `ERR_CONTRACT_FIXED_PRICE_MISSING`, 400); `lag_protection_days` defaults to 0 and grants a grace period against list-price increases. A draft sits in `DRAFT` until a `ContractAdministrator` activates it. Activation requires the contract be `DRAFT` (`ERR_CONTRACT_NOT_DRAFT`, 409), requires `effective_from` strictly before `effective_to` (`ERR_CONTRACT_WINDOW_INVALID`, 400), requires the fixed price when the basis demands it, and — crucially — requires that no other `ACTIVE` contract for the same customer and family have a half-open window overlapping this one; windows that merely touch, this one's start equal to the other's end or vice versa, do not overlap and are allowed (`ERR_CONTRACT_WINDOW_OVERLAP`, 409). An active contract expires automatically when the logical clock reaches its exclusive end, moving to `EXPIRED`. Either a draft or an active contract may be terminated by a `ContractAdministrator`, moving to `TERMINATED`; terminating one in any other state fails with `ERR_CONTRACT_NOT_TERMINABLE` (409). Contracts may be listed with `customer_id`, `family`, and `status` filters.

Branches are created by a `SystemAdmin` and carry the local-time configuration every temporal rule depends on: a unique `code` (`ERR_DUPLICATE_BRANCH_CODE`, 400), a `timezone_offset_hours` from UTC, a `business_open_hour` and `business_close_hour` (each 0–23, close strictly later than open or the create fails with `ERR_INVALID_REQUEST`), an `expedite_cutoff_hour` for same-day factory ordering, and the `after_hours_fee_cents` base call-out charge. A branch is born `OPEN`; a `SystemAdmin` may patch it between `OPEN` and `CLOSED`, bumping its `version`. Local hour is the logical-clock hour shifted by the branch's offset; after-hours means the local hour is before `business_open_hour` or at or after `business_close_hour`.

### 3.3. Shelf and Reservation Mechanics

A `BranchManager` creates a branch stock record per branch and product, supplying `branch_id`, `product_id`, the initial `on_hand_qty`, `factory_lead_time_days` for factory-direct sourcing, and optionally a `reorder_point` (informational only, default 0). The record opens with `reserved_qty` zero and `available_qty` equal to the shelf quantity. Stock records may be listed with `branch_id` and `product_id` filters, and fetching one always shows the computed `reserved_qty` and `available_qty` of §2.8.

Reservations pin shelf stock to an order line for a bounded time. When a line is reserved (see §3.4), the server creates a reservation in `ACTIVE` status whose `expires_at` is exactly 72 hours after creation, and whose `qty` must equal the full order-line quantity — a partial reservation is rejected with `ERR_PARTIAL_RESERVATION` (409). The stock record named by `branch_stock_id` must belong to the order's branch and reference the line's product, else `ERR_STOCK_LINE_MISMATCH` (409). Reservations end in one of four terminal states. Allocation of the line consumes the reservation (`CONSUMED`) and recomputes `reserved_qty`. A `CounterSalesRep` or `BranchManager` may release an active reservation, which requires the reservation still be `ACTIVE` (`ERR_RESERVATION_NOT_ACTIVE`, 409) and cascades: the order line falls back from `STOCK_RESERVED` to `PENDING_SOURCING`, `reserved_qty` recomputes, and the order's fulfillment status is re-evaluated (an order that had reached `FULLY_SOURCED` reverts to `CONFIRMED`). When the logical clock passes `expires_at`, the reservation goes `EXPIRED` with the same three-hop cascade — line back to `PENDING_SOURCING`, reserved quantity recomputed, order re-evaluated. Finally, an emergency call-out may seize the stock out from under a reservation, moving it to `PREEMPTED` with the identical cascade (§3.6). Reservations may be listed with `order_line_id`, `branch_stock_id`, and `status` filters.

### 3.4. The Order Pipeline: Pricing, Sourcing, Shipping, Billing

A `CounterSalesRep` opens a sales order by naming `customer_id`, the fulfilling `branch_id`, and optionally a `price_variant` — `ORDER_DATE` (the default) or `SHIP_DATE`. The order is born on two independent axes: `fulfillment_status` `DRAFT` and `billing_status` `UNBILLED`, with `subtotal_cents`, `expedite_fees_cents`, `total_cents`, and `paid_cents` all zero and `priced_at` null. Orders may be listed with `customer_id`, `branch_id`, `fulfillment_status`, and `billing_status` filters.

Lines join only while the order is `DRAFT`. Adding a line supplies `product_id`, `qty` (at least 1), and optionally an `expedite_tier` of `NONE` (default), `STANDARD`, `RUSH`, or `EMERGENCY`; the referenced product must exist and be `ACTIVE` (`ERR_PRODUCT_NOT_ACTIVE`, 409). The new line starts in `PENDING_SOURCING` with `unit_price_cents` null (unpriced), `price_protection_applied` false, `expedite_fee_cents` and `line_total_cents` zero, and both `factory_ordered_at` and `shipped_at` null. Adding a line bumps the order's `version`. While the order remains `DRAFT`, a rep may also change a line's expedite tier by supplying a new `expedite_tier`; the fee itself recomputes at confirm, and the change bumps the order's `version`. Lines may be listed with `order_id`, `product_id`, and `sourcing_status` filters.

**Confirming** the order is the pricing event. A `CounterSalesRep` confirms an order that is `DRAFT` (`ERR_ORDER_NOT_CONFIRMABLE`, 409) with at least one line (`ERR_ORDER_HAS_NO_LINES`, 409). Credit is then enforced, in this order relative to other checks per §2.5: the customer's `credit_status` must be `GOOD` (`ERR_CUSTOMER_CREDIT_HOLD`, 402), and the customer's `open_receivables_cents` plus the order's freshly computed `total_cents` must not exceed `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`, 402). On success, `priced_at` is set to now and every line is priced per the contract-lag rule below, fees recompute per the stacking rule, and totals aggregate per the order-total rule; the order moves to `CONFIRMED` and its `version` bumps.

**The contract-lag unit price** governs every price the system quotes — order confirm and reprice, the final re-price at ship for the `SHIP_DATE` variant, the pinned price on a consignment agreement, and the parts charge on a fulfilled call-out. Given a customer, a product, and an anchor instant T: first, determine the list price at T as the `new_list_price_cents` of the product's `EFFECTIVE` price file with the greatest `effective_at` not after T; if no such file exists, the product's `list_price_cents` as created (equivalently, its current `list_price_cents` while `last_price_change_at` is null). Only `EFFECTIVE` files participate — `PENDING`, `CANCELLED`, and `SUPERSEDED` files are excluded. Second, find the customer's `ACTIVE` contract for the product's `family` whose half-open window contains T (`effective_from` not after T and T strictly before `effective_to`); at most one such contract can exist. Third, compute the candidate: with a `CONTRACT_FIXED` contract the candidate is `fixed_unit_price_cents`; with a `LIST_LESS` contract the candidate is the list price at T multiplied by one minus `discount_pct`, rounded half-up to integer cents; with no contract the candidate is the list price at T. Fourth, lag protection — one-way, guarding only against increases: if a contract is present and its `lag_protection_days` exceeds 0 and the product's `last_price_change_at` is not null and T falls before `last_price_change_at` plus the lag days, and the most recent change was an increase (the list price that took effect at `last_price_change_at` exceeds the price in effect just before it — the effective file with the greatest `effective_at` earlier than `last_price_change_at`, or the pre-change product price if none), then recompute the candidate exactly as in step three but with the pre-increase price in place of the list price at T; if that protected candidate is lower, it wins and `price_protection_applied` is set true, otherwise it is set false. Whenever any of these conditions fails, `price_protection_applied` is false. Price decreases pass through immediately with no protection. The two order variants differ only in the anchor: for `ORDER_DATE`, T is the order's `created_at` and the price is locked at confirm, never recomputed at ship; for `SHIP_DATE`, T is now at confirm or reprice (provisional) and then each line's `shipped_at` at ship (final) — the two anchors may straddle a price-file effective instant and yield different unit prices for identical line data.

**The expedite fee** stacks, per line, in a pinned order. Start with the protected amount: the line's post-lag `unit_price_cents` times `qty`. The percentage portion by tier is zero for `NONE`, zero for `STANDARD` (flat-only), 8 percent of the protected amount rounded half-up for `RUSH`, and 15 percent rounded half-up for `EMERGENCY`. If the local hour at confirm is at or after the branch's `expedite_cutoff_hour` and the tier is `RUSH` or `EMERGENCY`, the percentage portion alone is multiplied by 1.25 and rounded half-up again — the flat portion is never touched by the multiplier. The flat portion is zero except for `STANDARD`, where it is 1500 cents. The fee is the flat plus the percentage portion, then floored at the tier minimum: 2500 cents for `RUSH`, 5000 cents for `EMERGENCY`, no floor for `NONE` or `STANDARD`. The result lands in the line's `expedite_fee_cents`.

**Order totals** aggregate with per-line-first rounding: each line's goods amount is its `unit_price_cents` times `qty`, rounded half-up (already integer cents unless a discount produced fractions upstream); the line's `line_total_cents` is that goods amount plus `expedite_fee_cents`; the order's `subtotal_cents` is the sum of goods amounts over non-`CANCELLED` lines; `expedite_fees_cents` is the sum of per-line fees over non-`CANCELLED` lines; `total_cents` is subtotal plus fees. Sum-then-round at the order level is forbidden.

**Re-pricing** re-runs the full pricing pass — every line re-priced per the contract-lag rule, fees per stacking, totals per aggregation, `priced_at` set to now — on a `DRAFT` or `CONFIRMED` order (an order in any other state is rejected with `ERR_ORDER_NOT_CONFIRMABLE`). It is the mechanism for picking up contracts that became `ACTIVE` or price files that became `EFFECTIVE` since the last pricing. The request must carry `expected_order_version` per §2.6, and a successful reprice bumps the order's `version`.

**Sourcing** moves each line out of `PENDING_SOURCING`. A rep reserves stock (creating the 72-hour reservation of §3.4; the line moves to `STOCK_RESERVED`, `reserved_qty` recomputes, and the order's fulfillment re-evaluates), provided the line is `PENDING_SOURCING` (`ERR_LINE_NOT_SOURCABLE`, 409), the order is `CONFIRMED` or `FULLY_SOURCED` (`ERR_ORDER_NOT_CONFIRMABLE`), the stock record matches, the quantity matches the line exactly, and `available_qty` covers the full `qty` (`ERR_INSUFFICIENT_AVAILABLE_STOCK`, 409). Alternatively the rep places a factory order, moving the line to `FACTORY_ORDERED` with `factory_ordered_at` set to now; the same line-state and order-state preconditions apply, and if the tier is `NONE` or `STANDARD` and the branch-local hour is at or past `expedite_cutoff_hour`, the placement is rejected with `ERR_FACTORY_ORDER_CUTOFF_PASSED` (409) — `RUSH` and `EMERGENCY` lines are exempt from the cutoff. A `BranchManager` later receives factory goods, which requires the line be `FACTORY_ORDERED` (`ERR_LINE_NOT_FACTORY_ORDERED`, 409) and requires that now be at least `factory_ordered_at` plus the effective lead time — the stock record's `factory_lead_time_days`, halved with a floor of 1 day for `RUSH`, and 0 days for `EMERGENCY` (`ERR_FACTORY_LEAD_TIME_UNMET`, 409). Receipt lands the goods on the shelf first: the branch-and-product stock record's `on_hand_qty` grows by the line `qty`, and the order's fulfillment re-evaluates. Allocation, by a `BranchManager`, picks the goods: the line must be `STOCK_RESERVED` or `FACTORY_RECEIVED` (`ERR_LINE_NOT_ALLOCATABLE`, 409). From `STOCK_RESERVED`, allocation consumes the reservation (`CONSUMED`), decrements `on_hand_qty` by the line quantity, and recomputes `reserved_qty`; from `FACTORY_RECEIVED`, allocation simply decrements the shelf. Either way the line moves to `ALLOCATED`. Shipping, again a `BranchManager` action, requires `ALLOCATED` (`ERR_LINE_NOT_SHIPPABLE`, 409), sets `shipped_at` to now, moves the line to `SHIPPED`, and — if the order's `price_variant` is `SHIP_DATE` — re-prices this line per the contract-lag rule anchored at `shipped_at`, recomputing `line_total_cents` and the order's subtotal, fees, and total. The order's fulfillment then re-evaluates.

Order fulfillment status is a pure function of line states, re-evaluated on every line change: when every line has left `PENDING_SOURCING` into one of `STOCK_RESERVED`, `FACTORY_ORDERED`, `FACTORY_RECEIVED`, `ALLOCATED`, or `SHIPPED`, the order becomes `FULLY_SOURCED`; if any line then reverts to `PENDING_SOURCING` (release, expiry, or preemption), a `FULLY_SOURCED` order falls back to `CONFIRMED`. When at least one line is `SHIPPED` and at least one line is neither `SHIPPED` nor `CANCELLED`, the order is `PARTIALLY_SHIPPED` — reachable from `CONFIRMED` or `FULLY_SOURCED`. When all lines are `SHIPPED` the order is `SHIPPED`, reachable from `CONFIRMED`, `FULLY_SOURCED`, or `PARTIALLY_SHIPPED` as the last lines complete.

**Cancellation** is available to a `CounterSalesRep` only while the order is pre-shipment: `fulfillment_status` must be `DRAFT`, `CONFIRMED`, or `FULLY_SOURCED` and no line may be `SHIPPED` (`ERR_ORDER_NOT_CANCELLABLE`, 409), and `billing_status` must still be `UNBILLED` (`ERR_ORDER_ALREADY_INVOICED`, 409). Cancellation cascades: every non-terminal line moves to `CANCELLED`, every active reservation of those lines moves to `RELEASED` with `reserved_qty` recomputed (stock availability restored), and the billing axis is untouched, remaining `UNBILLED`. The order's `version` bumps.

**The billing axis** evolves independently of fulfillment; neither axis's mutation alters the other. A `BranchManager` invoices an order whose `fulfillment_status` is `SHIPPED` (`ERR_ORDER_NOT_FULLY_SHIPPED`, 409) and whose billing is `UNBILLED` (`ERR_ORDER_ALREADY_INVOICED`, 409); billing moves to `INVOICED` and the customer's `open_receivables_cents` grows by `total_cents`. Payments then arrive against the invoice: recording a payment takes `amount_cents`, which must be strictly greater than zero and no more than `total_cents` minus `paid_cents` (violations are `ERR_INVALID_REQUEST`, 400); `paid_cents` accumulates, billing moves to `PARTIALLY_PAID` while some balance remains and to `PAID` when `paid_cents` equals `total_cents`, and `open_receivables_cents` recomputes. Finally, a `BranchManager` closes an order that is `SHIPPED` (`ERR_ORDER_NOT_FULLY_SHIPPED`) and `PAID` (`ERR_ORDER_NOT_PAID`, 409), moving fulfillment to `CLOSED`. `CLOSED` and `CANCELLED` are terminal.

### 3.5. Consigned Stock at the Customer Plant

A `ContractAdministrator` places consigned stock at a customer plant by creating an agreement with `customer_id`, `branch_id`, `product_id`, `consigned_qty`, and optionally a `billing_variant` of `CONSUMPTION_FIFO` (the default) or `MONTHLY_SNAPSHOT`. At most one non-`CLOSED` agreement may exist for a given customer, branch, and product (`ERR_DUPLICATE_AGREEMENT`, 409). Placement requires `available_qty` on the branch's stock record for this product to be at least `consigned_qty` (`ERR_INSUFFICIENT_AVAILABLE_STOCK`, 409); the shelf `on_hand_qty` then decreases by `consigned_qty` as the units physically move to the customer site. The agreement is born `ACTIVE`, and its `pinned_unit_price_cents` is fixed at creation by evaluating the contract-lag unit price at that instant — the pin survives every later list-price change. `consumed_qty` starts at zero and `remaining_qty` equals `consigned_qty`.

Amendment of `consigned_qty` is a `ContractAdministrator` patch carrying `consigned_qty` and the OCC field `expected_agreement_version` (§2.6). The new quantity must be at least the current `consumed_qty` (`ERR_CONSIGNMENT_QTY_BELOW_CONSUMED`, 409); the shelf `on_hand_qty` adjusts by the delta, `remaining_qty` recomputes, and the agreement's `version` bumps.

The customer — acting as `CustomerPlant`, whose `X-User-ID` must match the agreement's customer (`ERR_IDENTITY_MISMATCH`) — reports consumption by supplying `qty` under the agreement. The agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`, 409); a suspended agreement blocks new consumption reports. The quantity must be at least 1 and no more than the agreement's `remaining_qty` (`ERR_CONSUMPTION_EXCEEDS_REMAINING`, 409). The consumption is born `REPORTED` with `reported_at` set to the logical clock, `unit_price_cents` still null (pricing happens at invoice time, not report time), `billed_amount_cents` and `offset_applied_cents` zero; the agreement's `consumed_qty` and `remaining_qty` recompute, and the agreement's `version` bumps. Consumption events may be listed with `agreement_id` and `status` filters.

Invoicing is a `BranchManager` action requiring the consumption be `REPORTED` (`ERR_CONSUMPTION_NOT_REPORTED`, 409). Billing is variant-dependent. Under `CONSUMPTION_FIFO`, `unit_price_cents` is the agreement's `pinned_unit_price_cents` — the price at agreement creation — and later list changes never affect it. Under `MONTHLY_SNAPSHOT`, the unit price is the list price effective at the last instant of the UTC calendar month containing `reported_at`, found via the price-file history (the `EFFECTIVE` file with the greatest `effective_at` not after month-end, else the product's creation list price); a mid-month price increase between agreement creation and month-end therefore yields a different billed amount than `CONSUMPTION_FIFO` for identical consumption data. Either way `billed_amount_cents` is `unit_price_cents` times `qty` exactly, the consumption moves to `INVOICED`, and the customer's `open_receivables_cents` grows by the billed amount.

A `CustomerPlant` may dispute an `INVOICED` consumption of its own account (`ERR_CONSUMPTION_NOT_INVOICED`, 409 if not invoiced; `ERR_IDENTITY_MISMATCH` if another customer's), moving it to `DISPUTED`. Crediting is a `BranchManager` action on a `DISPUTED` or `INVOICED` consumption (`ERR_CONSUMPTION_NOT_CREDITABLE`, 409): the consumption moves to `CREDITED`, the customer's `open_receivables_cents` decreases by the still-outstanding portion (`billed_amount_cents` minus `offset_applied_cents`), and the agreement's `consumed_qty` recomputes excluding `CREDITED` consumptions, so `remaining_qty` is restored. Note that `consumed_qty` always sums consumptions in `REPORTED`, `INVOICED`, or `DISPUTED` status and excludes `CREDITED`.

Agreements may be suspended and resumed by a `ContractAdministrator`: suspending requires `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`) and moves to `SUSPENDED`; resuming requires `SUSPENDED` (`ERR_AGREEMENT_NOT_SUSPENDED`, 409) and returns to `ACTIVE`. Closing requires `ACTIVE` or `SUSPENDED` (`ERR_AGREEMENT_NOT_CLOSABLE`, 409) and requires that no consumptions remain in `REPORTED` or `DISPUTED` status (`ERR_AGREEMENT_CLOSE_BLOCKED`, 409); on close the unconsumed `remaining_qty` returns to the branch shelf, increasing `on_hand_qty`. Close does not reset the counters: `consigned_qty` and the consumption records are untouched, and `consumed_qty` and `remaining_qty` keep their standing derived values — `remaining_qty` equals `consigned_qty` minus `consumed_qty` even once `CLOSED`, so an agreement closed with unconsumed units reads a positive `remaining_qty` at close rather than zero. `CLOSED` is terminal. Agreements may be listed with `customer_id`, `branch_id`, `product_id`, and `status` filters.

### 3.6. Emergency After-Hours Call-Outs

When a plant goes down at night, either the plant itself (`CustomerPlant`, acting on its own account) or a `CounterSalesRep` requests a call-out naming `branch_id`, `customer_id`, `product_id`, and `qty` (at least 1). The call-out is born `REQUESTED` with `call_out_fee_cents`, `parts_amount_cents`, and `total_charge_cents` zero, `responder_id` null, and `preempted_reservation_ids` empty. Call-outs may be listed with `branch_id`, `customer_id`, `product_id`, and `status` filters.

Dispatch is the `OnCallTechnician`'s. It requires the call-out be `REQUESTED` (`ERR_CALL_OUT_NOT_REQUESTED`, 409), requires branch-local after-hours — local hour before `business_open_hour` or at or after `business_close_hour` (`ERR_CALL_OUT_NOT_AFTER_HOURS`, 409) — and enforces one-truck capacity: the branch must have zero other call-outs in `DISPATCHED` status (`ERR_BRANCH_CALLOUT_CAPACITY`, 409). On dispatch, `responder_id` records the technician's `X-User-ID` and the fee computes: start with the branch's `after_hours_fee_cents`; if the branch-local day is a Saturday or Sunday, multiply by 1.5 with round-half-up; then add 250 cents per unit of `qty` for handling. After-hours eligibility is a dispatch precondition, not part of the fee.

Fulfillment pulls the goods from the branch shelf. It requires `DISPATCHED` (`ERR_CALL_OUT_NOT_DISPATCHED`, 409). If the stock record's `on_hand_qty` is below `qty`, the call-out collapses to `STOCK_UNAVAILABLE` instead. Otherwise — and this is the emergency override that makes call-outs special — when `available_qty` is short, the server seizes `ACTIVE` reservations for this branch and product in `created_at` descending order (newest first) until the demand is covered; each seized reservation moves to `PREEMPTED`, its order line falls back to `PENDING_SOURCING`, and that line's order has its fulfillment re-evaluated (a `FULLY_SOURCED` order reverts to `CONFIRMED`). The seized ids are recorded on the call-out's `preempted_reservation_ids` in preemption order. The shelf `on_hand_qty` then decreases by `qty` with `reserved_qty` recomputed, `parts_amount_cents` is the `qty` times the contract-lag unit price for this customer and product anchored at the fulfillment instant, `total_charge_cents` is fee plus parts, the call-out moves to `FULFILLED`, and the customer's `open_receivables_cents` grows by the total charge. Cancellation — by the technician or by the plant whose call-out it is — requires `REQUESTED` or `DISPATCHED` (`ERR_CALL_OUT_NOT_CANCELLABLE`, 409) and moves to `CANCELLED`. `FULFILLED`, `STOCK_UNAVAILABLE`, and `CANCELLED` are terminal.

### 3.7. Warranty: Failed-Bearing Analysis and Tiered Credit

A `WarrantyAnalyst` files a claim with `product_id`, a `failure_mode` of `FATIGUE`, `CONTAMINATION`, `MISALIGNMENT`, `LUBRICATION`, `BRINELLING`, or `OTHER`, `operating_hours` (zero or more), `qty` (at least 1), and a source: exactly one of `order_line_id` or `consumption_id` must be supplied — supplying both or neither fails with `ERR_CLAIM_REFERENCE_INVALID` (400). The claim `qty` may not exceed the source line's or consumption's quantity (`ERR_CLAIM_QTY_EXCEEDS_SOURCE`, 409). The claim is born `SUBMITTED`, `filed_by` records the analyst's `X-User-ID`, `verdict` is `NONE`, `verdict_by` null, and `coverage_pct` and `credit_amount_cents` zero. Claims may be listed with `product_id`, `order_line_id`, `consumption_id`, and `status` filters.

A `QualityEngineer` opens analysis, requiring `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`, 409) and moving to `UNDER_ANALYSIS`. If more information is needed, the engineer returns the claim to the filer — `UNDER_ANALYSIS` back to `SUBMITTED` (`ERR_CLAIM_NOT_UNDER_ANALYSIS` guards the loop) — and analysis can begin again. The verdict ends analysis. The claim must be `UNDER_ANALYSIS` (`ERR_CLAIM_NOT_UNDER_ANALYSIS`), and segregation of duties forbids the engineer who filed the claim from verdicting it: the verdicting `X-User-ID` must differ from `filed_by` (`ERR_WARRANTY_SOD_VERDICT`, 403). A verdict of `CONFIRMED_DEFECT` approves the claim; a verdict of `MISAPPLICATION` or `WEAR_OUT` denies it. Approval additionally requires the source to be final: an order-linked claim's line must be `SHIPPED`, and a consignment-linked claim's consumption must be `INVOICED` or `REPORTED` (`ERR_CLAIM_SOURCE_NOT_FINAL`, 409). On approval, `verdict` and `verdict_by` persist, and the tiered credit computes: coverage is 100 percent when `operating_hours` is below 2000, 50 percent from 2000 up to but not including 5000, and 25 percent at 5000 hours or more — the lower bounds are inclusive, so exactly 2000 hours yields 50 percent and exactly 5000 yields 25 percent. The source unit price is the order line's `unit_price_cents` for order-linked claims; for consignment-linked claims it is the consumption's `unit_price_cents` if invoiced, else the agreement's `pinned_unit_price_cents`. `credit_amount_cents` is the source unit price times `qty` times `coverage_pct`, rounded half-up to integer cents. On denial, `verdict` and `verdict_by` persist and both `coverage_pct` and `credit_amount_cents` are set to zero.

Issuing the credit is a `BranchManager` action requiring `APPROVED` (`ERR_CLAIM_NOT_APPROVED`, 409). The customer's `open_receivables_cents` decreases by `credit_amount_cents`, and the claim moves to `CREDIT_ISSUED`. When the claim is consignment-linked and the claim `qty` equals the consumption's full `qty`, a cross-entity cascade fires: the consumption moves from `INVOICED` to `CREDITED` (hop 1), the agreement's `consumed_qty` and `remaining_qty` recompute excluding it (hop 2), and the receivables adjustment for the consumption folds into the claim credit — the consumption's own credit path is skipped so no double count occurs. `DENIED` and `CREDIT_ISSUED` are terminal.

### 3.8. Surplus and Obsolete Returns

Either a `CustomerPlant` (for its own account) or a `CounterSalesRep` requests a return authorization with `customer_id`, `product_id`, the receiving `branch_id`, `qty` (at least 1), a `condition` of `SURPLUS` or `OBSOLETE`, and the claimed `original_unit_price_cents`. The return is born `REQUESTED` with `requested_by` recording the caller, `approved_by` and `approved_at` null, `received_qty` zero, and all computed amounts zero. Returns may be listed with `customer_id`, `product_id`, `branch_id`, and `status` filters.

Adjudication belongs to a `BranchManager`, with segregation of duties: the approver or rejector's `X-User-ID` must differ from `requested_by` (`ERR_RETURN_SOD_APPROVAL`, 403). Approval requires `REQUESTED` (`ERR_RETURN_NOT_REQUESTED`, 409) and requires the authorized `qty` not exceed the customer's cumulative shipped quantity of this product across all orders (`ERR_RETURN_QTY_EXCEEDS_SHIPPED`, 409); `approved_by` and `approved_at` persist and the return moves to `APPROVED`. Rejection requires the same `REQUESTED` state and the same SoD check, moving to `REJECTED` with no amounts computed. An approved return that is not received in time lapses automatically to `EXPIRED` when the logical clock passes `approved_at` plus 30 days.

Receipt is a one-shot physical event by a `BranchManager`: the return must be `APPROVED` (`ERR_RETURN_NOT_APPROVED`, 409), the logical clock must be no later than `approved_at` plus the 30-day RMA window (`ERR_RMA_WINDOW_EXPIRED`, 409), and `received_qty` must be at least 1 and no more than the authorized `qty` (`ERR_INVALID_RECEIVED_QTY`, 409). On receipt the credit is computed: the base is `received_qty` times the lesser of `original_unit_price_cents` and the product's current `list_price_cents`; `eligible_credit_cents` is that base reduced by a 15 percent restocking fee — that is, the base multiplied by 0.85, rounded half-up. For `OBSOLETE` returns only, `write_down_cents` is 50 percent of the eligible credit, rounded half-up; surplus returns carry no write-down. Restock is condition-dependent: a `SURPLUS` return of a product still in `ACTIVE` status lands back on the shelf, increasing the receiving branch stock's `on_hand_qty` by `received_qty`; obsolete units are scrapped and never add stock. The return moves to `RECEIVED`.

Issuing the credit, again a `BranchManager` action requiring `RECEIVED` (`ERR_RETURN_NOT_RECEIVED`, 409), applies the netting waterfall. The nettable amount is `eligible_credit_cents` minus `write_down_cents`. Bucket one: the customer's outstanding consignment invoices — consumptions in `INVOICED` status whose outstanding balance (`billed_amount_cents` minus that consumption's `offset_applied_cents`) is positive — are offset oldest first by the consumption's `created_at` ascending (ties broken by `reported_at` ascending), each bucket filled to its full outstanding before the next is touched, until the nettable amount is exhausted. Each touched consumption's `offset_applied_cents` grows accordingly, and the return's `offset_applied_cents` records the total offset, never exceeding the nettable amount. Bucket two: `credit_memo_cents` is whatever remains, nettable minus `offset_applied_cents`, never negative by construction. The customer's `open_receivables_cents` then decreases twice in effect — once by `offset_applied_cents` (receivables extinguished) and once by `credit_memo_cents` (a memo against future obligations). The conservation invariant holds at all times after issue-credit: `eligible_credit_cents` equals `write_down_cents` plus `offset_applied_cents` plus `credit_memo_cents`. The return moves to `CREDIT_ISSUED`, terminal alongside `REJECTED` and `EXPIRED`.

### 3.9. Receivables Reconciliation

The customer's `open_receivables_cents` is a derived, eagerly recomputed figure — visible in the same response that caused any change, under immediate consistency. It is defined as: the sum over the customer's sales orders in `INVOICED` or `PARTIALLY_PAID` billing of `total_cents` minus `paid_cents`; plus the sum over consumptions of the customer's agreements in `INVOICED` status of `billed_amount_cents` minus `offset_applied_cents`; plus the sum over the customer's `FULFILLED` call-outs of `total_charge_cents`; minus the sum over the customer's claims in `CREDIT_ISSUED` status of `credit_amount_cents`; minus the sum over the customer's returns in `CREDIT_ISSUED` status of `offset_applied_cents` plus `credit_memo_cents`. The value may go negative, representing a credit balance. Order invoicing and payment, consumption invoicing and crediting, call-out fulfillment, warranty credit issuance, and return credit issuance each trigger the recomputation.

### 3.10. Repair-Shop Referrals

A `SystemAdmin` maintains the repair-shop registry: creating a shop takes `name`, `capabilities` (a list of product families the shop services, a subset of the family enum), a `region` tag, and `labor_rate_cents` per hour. Shops are born `ACTIVE`; a `SystemAdmin` may patch `status` between `ACTIVE` and `INACTIVE` (bumping `version`), and `INACTIVE` shops are excluded from referral selection. Shops may be listed with `region`, `capability`, and `status` filters.

When a claim is denied with verdict `MISAPPLICATION`, the failure was the customer's application problem, not a defect — and the distributor monetizes the repair introduction. A `WarrantyAnalyst` creates a referral naming `warranty_claim_id` and the required service `region`; the claim's verdict must be `MISAPPLICATION` (`ERR_REFERRAL_VERDICT_NOT_MISAPPLICATION`, 409). The client never picks the shop: the server runs the selector. Eligibility requires the shop be `ACTIVE`, the claim's product family appear in the shop's `capabilities`, the shop's `region` equal the referral's `region`, and the shop's id not appear among the `declined_shop_ids` of this claim's referral chain. Candidates rank by `labor_rate_cents` ascending, ties broken by the shop's `created_at` ascending; the shop's `id` is never used for ranking or tie-break. If no eligible shop exists at creation, the request fails with `ERR_NO_ELIGIBLE_SHOP` (409). The referral is born `OPEN` with `service_shop_id` set to the selector's choice, `quoted_amount_cents` null, `referral_fee_cents` zero, and `declined_shop_ids` empty. Referrals may be listed with `warranty_claim_id`, `service_shop_id`, and `status` filters.

The chosen shop responds under its own identity — `X-User-ID` must equal the referral's `service_shop_id` (`ERR_REFERRAL_SHOP_MISMATCH`, 403). Accepting requires `OPEN` (`ERR_REFERRAL_NOT_OPEN`, 409) and carries the shop's repair quote `quoted_amount_cents`, which must be at least 1 (`ERR_INVALID_REQUEST`, 400); the quote persists and the referral moves to `ACCEPTED`. Declining requires `OPEN` and the same identity check; the referral moves to `DECLINED`, the shop's id is appended to the claim's referral chain `declined_shop_ids`, and the system immediately creates a successor referral in `OPEN` for the same claim, re-running the selector with all decliners excluded; if no eligible shop remains, no successor is created and the claim is left without an open referral. Completion requires `ACCEPTED` (`ERR_REFERRAL_NOT_ACCEPTED`, 409) with the same identity check; the referral fee is 10 percent of `quoted_amount_cents`, rounded half-up, capped at 25000 cents — that is, the fee is the lesser of the rounded percentage and the cap — and the referral moves to `COMPLETED`, the terminal state.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; every other successful operation — reads, updates, transitions, and actions — returns HTTP 200. Errors carry the 4xx statuses catalogued in Section 5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /motion/_clock/set_current_utc | Advance the logical clock; fires all due scheduled transitions | SystemAdmin |
| POST | /motion/products | Create a catalog product | PricingAnalyst |
| GET | /motion/products | List products (`sku?`, `family?`, `status?`, `superseded_by_id?`) | Any |
| GET | /motion/products/{id} | Get a product | Any |
| PATCH | /motion/products/{id} | Lifecycle update: ACTIVE→PHASEOUT→OBSOLETE (or direct), optional `superseded_by_id` | PricingAnalyst |
| POST | /motion/interchange-records | Create a competitor-part interchange/sizing mapping (immutable) | PricingAnalyst |
| GET | /motion/interchange-records | Interchange/sizing lookup (`product_id?`, `competitor_part_number?`, `shaft_diameter_mm?`) | Any |
| GET | /motion/interchange-records/{id} | Get an interchange record | Any |
| POST | /motion/customers | Onboard a customer plant | ContractAdministrator |
| GET | /motion/customers | List customers (`credit_status?`) | Any |
| GET | /motion/customers/{id} | Get a customer (includes derived receivables) | Any |
| PATCH | /motion/customers/{id} | Update `credit_status` or `status` | ContractAdministrator |
| POST | /motion/contracts | Draft a customer family contract | ContractAdministrator |
| GET | /motion/contracts | List contracts (`customer_id?`, `family?`, `status?`) | Any |
| GET | /motion/contracts/{id} | Get a contract | Any |
| POST | /motion/contracts/{id}/activate | Activate a DRAFT contract; enforces half-open window non-overlap | ContractAdministrator |
| POST | /motion/contracts/{id}/terminate | Terminate a DRAFT or ACTIVE contract | ContractAdministrator |
| POST | /motion/branches | Create a distribution branch | SystemAdmin |
| GET | /motion/branches | List branches | Any |
| GET | /motion/branches/{id} | Get a branch | Any |
| PATCH | /motion/branches/{id} | Update branch status (OPEN/CLOSED) | SystemAdmin |
| POST | /motion/branch-stocks | Create a branch+product stock record | BranchManager |
| GET | /motion/branch-stocks | List stock records (`branch_id?`, `product_id?`) | Any |
| GET | /motion/branch-stocks/{id} | Get a stock record (includes computed quantities) | Any |
| POST | /motion/branch-stocks/{id}/adjust | Adjust on-hand quantity (`qty_delta`, `reason`); must stay ≥ reserved | BranchManager |
| POST | /motion/price-files | Publish a price-file update (OCC via `expected_product_version`) | PricingAnalyst |
| GET | /motion/price-files | List price files (`product_id?`, `status?`) | Any |
| GET | /motion/price-files/{id} | Get a price file | Any |
| POST | /motion/price-files/{id}/cancel | Cancel a PENDING price file | PricingAnalyst |
| POST | /motion/orders | Create an order (DRAFT × UNBILLED) | CounterSalesRep |
| GET | /motion/orders | List orders (`customer_id?`, `branch_id?`, `fulfillment_status?`, `billing_status?`) | Any |
| GET | /motion/orders/{id} | Get an order (includes computed totals) | Any |
| POST | /motion/orders/{id}/lines | Add an order line (order must be DRAFT) | CounterSalesRep |
| POST | /motion/orders/{id}/confirm | Price and confirm the order; runs credit checks | CounterSalesRep |
| POST | /motion/orders/{id}/reprice | Re-run pricing (OCC via `expected_order_version`) | CounterSalesRep |
| POST | /motion/orders/{id}/cancel | Cancel a pre-shipment order; releases reservations | CounterSalesRep |
| POST | /motion/orders/{id}/invoice | Invoice a fully shipped order | BranchManager |
| POST | /motion/orders/{id}/record-payment | Record a payment (`amount_cents`) against an invoiced order | BranchManager |
| POST | /motion/orders/{id}/close | Close a SHIPPED + PAID order | BranchManager |
| GET | /motion/order-lines | List order lines (`order_id?`, `product_id?`, `sourcing_status?`) | Any |
| GET | /motion/order-lines/{id} | Get an order line | Any |
| POST | /motion/order-lines/{id}/expedite | Change expedite tier while order is DRAFT | CounterSalesRep |
| POST | /motion/order-lines/{id}/reserve | Reserve branch stock for the full line quantity (72h TTL) | CounterSalesRep |
| POST | /motion/order-lines/{id}/place-factory-order | Source the line factory-direct; cutoff applies to NONE/STANDARD | CounterSalesRep |
| POST | /motion/order-lines/{id}/receive-factory | Receive factory goods after the tier-adjusted lead time | BranchManager |
| POST | /motion/order-lines/{id}/allocate | Pick stock: consumes reservation or decrements shelf | BranchManager |
| POST | /motion/order-lines/{id}/ship | Ship an allocated line; SHIP_DATE orders re-price at ship | BranchManager |
| GET | /motion/stock-reservations | List reservations (`order_line_id?`, `branch_stock_id?`, `status?`) | Any |
| GET | /motion/stock-reservations/{id} | Get a reservation | Any |
| POST | /motion/stock-reservations/{id}/release | Release an ACTIVE reservation; line reverts to PENDING_SOURCING | CounterSalesRep, BranchManager |
| POST | /motion/call-outs | Request an emergency after-hours call-out | CustomerPlant, CounterSalesRep |
| GET | /motion/call-outs | List call-outs (`branch_id?`, `customer_id?`, `product_id?`, `status?`) | Any |
| GET | /motion/call-outs/{id} | Get a call-out | Any |
| POST | /motion/call-outs/{id}/dispatch | Dispatch an on-call technician (after-hours; one per branch) | OnCallTechnician |
| POST | /motion/call-outs/{id}/fulfill | Fulfill from stock; seizes newest ACTIVE reservations when short | OnCallTechnician |
| POST | /motion/call-outs/{id}/cancel | Cancel a REQUESTED or DISPATCHED call-out | OnCallTechnician, CustomerPlant |
| POST | /motion/consignment-agreements | Place consigned stock; pins unit price; moves stock off shelf | ContractAdministrator |
| GET | /motion/consignment-agreements | List agreements (`customer_id?`, `branch_id?`, `product_id?`, `status?`) | Any |
| GET | /motion/consignment-agreements/{id} | Get an agreement | Any |
| PATCH | /motion/consignment-agreements/{id} | Amend `consigned_qty` (OCC via `expected_agreement_version`) | ContractAdministrator |
| POST | /motion/consignment-agreements/{id}/suspend | Suspend an agreement (blocks new consumption reports) | ContractAdministrator |
| POST | /motion/consignment-agreements/{id}/resume | Resume a suspended agreement | ContractAdministrator |
| POST | /motion/consignment-agreements/{id}/close | Close; unconsumed stock returns to the branch shelf | ContractAdministrator |
| POST | /motion/consignment-agreements/{id}/consumptions | Customer reports consumption (`qty`) from consigned stock | CustomerPlant |
| GET | /motion/consignment-consumptions | List consumption events (`agreement_id?`, `status?`) | Any |
| GET | /motion/consignment-consumptions/{id} | Get a consumption event | Any |
| POST | /motion/consignment-consumptions/{id}/invoice | Invoice a REPORTED consumption per billing variant | BranchManager |
| POST | /motion/consignment-consumptions/{id}/dispute | Customer disputes an INVOICED consumption | CustomerPlant |
| POST | /motion/consignment-consumptions/{id}/credit | Credit a DISPUTED or INVOICED consumption | BranchManager |
| POST | /motion/warranty-claims | File a failed-bearing claim against a line or consumption | WarrantyAnalyst |
| GET | /motion/warranty-claims | List claims (`product_id?`, `order_line_id?`, `consumption_id?`, `status?`) | Any |
| GET | /motion/warranty-claims/{id} | Get a warranty claim | Any |
| POST | /motion/warranty-claims/{id}/begin-analysis | Open failure analysis on a claim | QualityEngineer |
| POST | /motion/warranty-claims/{id}/request-info | Return claim to filer for more information | QualityEngineer |
| POST | /motion/warranty-claims/{id}/verdict | Render verdict (`verdict`); approves or denies with tiered credit | QualityEngineer |
| POST | /motion/warranty-claims/{id}/issue-credit | Issue the approved credit; consignment cross-effect applies | BranchManager |
| POST | /motion/return-authorizations | Request a surplus or obsolete return | CustomerPlant, CounterSalesRep |
| GET | /motion/return-authorizations | List returns (`customer_id?`, `product_id?`, `branch_id?`, `status?`) | Any |
| GET | /motion/return-authorizations/{id} | Get a return authorization | Any |
| POST | /motion/return-authorizations/{id}/approve | Approve a return (approver must differ from requester) | BranchManager |
| POST | /motion/return-authorizations/{id}/reject | Reject a return (rejector must differ from requester) | BranchManager |
| POST | /motion/return-authorizations/{id}/receive | Receive goods (`received_qty`) within the RMA window | BranchManager |
| POST | /motion/return-authorizations/{id}/issue-credit | Net against outstanding consignment invoices; remainder as memo | BranchManager |
| POST | /motion/service-shops | Register a repair shop | SystemAdmin |
| GET | /motion/service-shops | List shops (`region?`, `capability?`, `status?`) | Any |
| GET | /motion/service-shops/{id} | Get a repair shop | Any |
| PATCH | /motion/service-shops/{id} | Update shop status; INACTIVE excluded from selection | SystemAdmin |
| POST | /motion/service-referrals | Refer a MISAPPLICATION claim to the selector-chosen shop | WarrantyAnalyst |
| GET | /motion/service-referrals | List referrals (`warranty_claim_id?`, `service_shop_id?`, `status?`) | Any |
| GET | /motion/service-referrals/{id} | Get a referral | Any |
| POST | /motion/service-referrals/{id}/accept | Selected shop accepts with quote `quoted_amount_cents` | ServiceShop |
| POST | /motion/service-referrals/{id}/decline | Selected shop declines; successor referral auto-created | ServiceShop |
| POST | /motion/service-referrals/{id}/complete | Complete the repair; referral fee computed and capped | ServiceShop |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_IDENTITY_MISMATCH | 403 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_INTERCHANGE_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_BRANCH_NOT_FOUND | 404 |
| ERR_BRANCH_STOCK_NOT_FOUND | 404 |
| ERR_PRICE_FILE_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_ORDER_LINE_NOT_FOUND | 404 |
| ERR_RESERVATION_NOT_FOUND | 404 |
| ERR_CALL_OUT_NOT_FOUND | 404 |
| ERR_AGREEMENT_NOT_FOUND | 404 |
| ERR_CONSUMPTION_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_RETURN_NOT_FOUND | 404 |
| ERR_SHOP_NOT_FOUND | 404 |
| ERR_REFERRAL_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE_SKU | 400 |
| ERR_DUPLICATE_BRANCH_CODE | 400 |
| ERR_CONTRACT_WINDOW_INVALID | 400 |
| ERR_CONTRACT_FIXED_PRICE_MISSING | 400 |
| ERR_CONTRACT_WINDOW_OVERLAP | 409 |
| ERR_DUPLICATE_AGREEMENT | 409 |
| ERR_CLAIM_REFERENCE_INVALID | 400 |
| ERR_PRODUCT_NOT_ACTIVE | 409 |
| ERR_PRODUCT_NOT_PHASEOUT | 409 |
| ERR_SUPERSEDE_TARGET_INVALID | 409 |
| ERR_CONTRACT_NOT_DRAFT | 409 |
| ERR_CONTRACT_NOT_TERMINABLE | 409 |
| ERR_PRICE_FILE_NOT_PENDING | 409 |
| ERR_ORDER_NOT_CONFIRMABLE | 409 |
| ERR_ORDER_HAS_NO_LINES | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_ORDER_ALREADY_INVOICED | 409 |
| ERR_ORDER_NOT_FULLY_SHIPPED | 409 |
| ERR_ORDER_NOT_PAID | 409 |
| ERR_LINE_NOT_SOURCABLE | 409 |
| ERR_LINE_NOT_ALLOCATABLE | 409 |
| ERR_LINE_NOT_SHIPPABLE | 409 |
| ERR_LINE_NOT_FACTORY_ORDERED | 409 |
| ERR_RESERVATION_NOT_ACTIVE | 409 |
| ERR_CALL_OUT_NOT_REQUESTED | 409 |
| ERR_CALL_OUT_NOT_DISPATCHED | 409 |
| ERR_CALL_OUT_NOT_CANCELLABLE | 409 |
| ERR_AGREEMENT_NOT_ACTIVE | 409 |
| ERR_AGREEMENT_NOT_SUSPENDED | 409 |
| ERR_AGREEMENT_NOT_CLOSABLE | 409 |
| ERR_AGREEMENT_CLOSE_BLOCKED | 409 |
| ERR_CONSUMPTION_NOT_REPORTED | 409 |
| ERR_CONSUMPTION_NOT_INVOICED | 409 |
| ERR_CONSUMPTION_NOT_CREDITABLE | 409 |
| ERR_CLAIM_NOT_SUBMITTED | 409 |
| ERR_CLAIM_NOT_UNDER_ANALYSIS | 409 |
| ERR_CLAIM_NOT_APPROVED | 409 |
| ERR_RETURN_NOT_REQUESTED | 409 |
| ERR_RETURN_NOT_APPROVED | 409 |
| ERR_RETURN_NOT_RECEIVED | 409 |
| ERR_REFERRAL_NOT_OPEN | 409 |
| ERR_REFERRAL_NOT_ACCEPTED | 409 |
| ERR_REFERRAL_SHOP_MISMATCH | 403 |
| ERR_WARRANTY_SOD_VERDICT | 403 |
| ERR_RETURN_SOD_APPROVAL | 403 |
| ERR_EFFECTIVE_AT_IN_PAST | 409 |
| ERR_CALL_OUT_NOT_AFTER_HOURS | 409 |
| ERR_BRANCH_CALLOUT_CAPACITY | 409 |
| ERR_FACTORY_ORDER_CUTOFF_PASSED | 409 |
| ERR_FACTORY_LEAD_TIME_UNMET | 409 |
| ERR_RMA_WINDOW_EXPIRED | 409 |
| ERR_STOCK_BELOW_RESERVED | 409 |
| ERR_STOCK_LINE_MISMATCH | 409 |
| ERR_PARTIAL_RESERVATION | 409 |
| ERR_CLAIM_QTY_EXCEEDS_SOURCE | 409 |
| ERR_CLAIM_SOURCE_NOT_FINAL | 409 |
| ERR_RETURN_QTY_EXCEEDS_SHIPPED | 409 |
| ERR_REFERRAL_VERDICT_NOT_MISAPPLICATION | 409 |
| ERR_NO_ELIGIBLE_SHOP | 409 |
| ERR_INVALID_RECEIVED_QTY | 409 |
| ERR_CONSIGNMENT_QTY_BELOW_CONSUMED | 409 |
| ERR_CONSUMPTION_EXCEEDS_REMAINING | 409 |
| ERR_INSUFFICIENT_AVAILABLE_STOCK | 409 |
| ERR_CUSTOMER_CREDIT_HOLD | 402 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_STALE_VERSION | 412 |
