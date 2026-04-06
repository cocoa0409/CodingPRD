# E-Commerce Seller Fulfillment & Settlement API — Product Requirements Document

## 1. Introduction

This document defines the product requirements for the E-Commerce Seller Fulfillment & Settlement API. The system supports a multi-seller commerce platform through the full lifecycle of seller accounts: onboarding and activation, sales channels and product listings, fulfillment-center configuration and logistics allocation, discount-voucher budgeting, compliance scoring, and fee-based settlement against platform service budgets. The API exposes two independent fiscal ledgers—the seller-scoped fee ledger tied to `fee_balance` and the voucher-scoped discount ledger tied to `budget_remaining`—and two deliberately distinct calculation families for shipping and commission: forward-looking provisional amounts versus chronologically finalized amounts at settlement, which may diverge for the same underlying data.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules that apply to the entire API under the path prefix `/seller-accounts`.

### 2.1. User and Role-Based Access Control

All requests must include `X-User-ID` and `X-User-Role` HTTP headers. The system recognizes four role identifiers with exact spelling: `SellerManager`, `OrderProcessor`, `SettlementAdmin`, and `Any`. Missing or invalid headers result in `ERR_MISSING_OR_INVALID_AUTH_HEADER`. Operations outside a caller’s permitted role are rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (HTTP 2xx) use this JSON envelope:

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
  "response_type": "object",
  "data": { }
```

- `api_request_id`: server-generated unique identifier; values begin with `req_` followed by alphanumeric characters.
- `api_request_timestamp`: ISO 8601 UTC timestamp with exactly three fractional digits (milliseconds).
- `response_type`: either `"object"` for a single resource or `"array"` for a list.
- `data`: business payload—an object, an array of objects, or `{}` when no resource body is returned but the operation succeeded.
- For list endpoints, `meta` includes `limit`, `offset`, `total_count`, and `has_more` as shown. Non-list success responses omit the pagination keys from `meta` (only `api_request_id` and `api_request_timestamp` appear).

#### Standard Error Response Format

All error responses (HTTP 4xx) use:

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

- Error `meta` contains only `api_request_id` and `api_request_timestamp`.
- `error_id` is a stable machine-readable identifier; HTTP status is determined by the error type (see §5).
- `message` is human-readable and non-authoritative for automation.

### 2.3. Pagination

List endpoints accept `limit` and `offset` query parameters. Default `limit` is 10; minimum 1; maximum 100. Default `offset` is 0. Unless otherwise stated, list results are sorted by `created_at` ascending. Paginated responses echo the effective `limit` and `offset` and include `total_count` and `has_more` in `meta`.

### 2.4. System Integrity and Consistency

Parent–child relationships enforce hierarchical consistency. When a parent’s state changes in ways that invalidate open work, the system cascades or reverts dependent children per the state machines: for example, cancelling a sales channel may cancel pending offers and in-flight allocations while restoring fee and voucher ledger positions. Child mutations that affect a parent’s eligibility (for example, allocation lifecycle affecting channel readiness) are reconciled so parent `status` and financial aggregates remain coherent. Every successful mutation updates the affected resource’s `updated_at` (where present) and increments `version` for optimistic concurrency. Seller-account aggregates such as `fee_balance` and `compliance_score` count as mutations on the seller account for `updated_at` / `version` purposes where applicable.

### 2.5. Dual Ledger Principles: Fee Budget and Discount Voucher Budget

The seller account maintains `fee_budget` as the cap for the current settlement cycle’s combined platform service charges (shipping plus commission). The running `fee_balance` starts equal to `fee_budget` and decreases as provisional charges are reserved and increases on reversals; at finalize-settlement it is reconciled against finalized totals. Separately, each `DiscountVoucher` carries `total_budget` and `budget_remaining`; applying a voucher to an allocation debits `budget_remaining` by the computed `discount_amount`, and refunds on reject or cancel restore budget. The two ledgers are independent: insufficient voucher budget must not be conflated with insufficient fee budget, and each has its own error surface (`ERR_VOUCHER_BUDGET_EXHAUSTED` versus `ERR_INSUFFICIENT_FEE_BUDGET`).

### 2.6. Provisional vs. Final Shipping and Commission

`provisional_shipping_cost` and `provisional_commission` are forward-looking: they include unresolved work where the rules specify, and may change when an allocation is dispatched because the relevant historical window changes. `final_shipping_cost` and `final_commission` are computed only at finalize-settlement, processing delivered work in chronological order by the associated offer’s `start_minute`. The same underlying facts can therefore yield different provisional and final numbers—two independent divergence families (shipping per fulfillment center, commission per seller across centers).

### 2.7. Nested Resource Retrieval and Body References

For paths that include `{accountId}`, `{channelId}`, `{offerId}`, `{centerId}`, `{allocationId}`, `{restrictionId}`, or `{voucherId}`, the system validates identifiers from left to right. The first missing resource yields the corresponding `ERR_*_NOT_FOUND` before deeper segments are evaluated. Request bodies that reference `product_offer_id`, `fulfillment_center_id`, or `voucher_id` are validated after path existence and role checks, with `ERR_FULFILLMENT_CENTER_NOT_FOUND` or `ERR_VOUCHER_NOT_FOUND` as appropriate.

### 2.8. Common Resource Properties

Resources with `common_fields: true` include: `id` (UUID string), `created_at` (ISO 8601 UTC with three fractional digits), `updated_at` (same format, updated on every mutation), and `version` (integer, incremented on every mutation). `ShippingRestriction` is immutable after creation and exposes only `id` and `created_at` (no `updated_at` or `version`). Each element inside `warehouse_certifications` includes its own `id` (UUID), `name`, and `certified_date`.

### 2.9. Monetary Values, Rates, and Precision

All stored monetary amounts and computed fees (`fee_balance`, `discount_amount`, provisional and final shipping and commission, budgets) are rounded to **2 decimal places** using **round half up**. Internal arithmetic should use decimal-safe logic; API numbers are JSON numbers. Rate-like inputs such as `base_commission_rate` preserve the precision supplied by the client within normal floating-point limits.

### 2.10. Optimistic Concurrency Control

Mutating requests may include `version` in the body where the endpoint updates an existing resource (for example, sales channel status updates). If provided and not equal to the server’s current `version`, the server responds with `ERR_STALE_DATA`. If `version` is omitted, the server applies the update without an OCC check.

### 2.11. Enumerations (Exact Strings)

**SellerAccount.status:** `ONBOARDING`, `ACTIVE`, `SETTLEMENT_PENDING`, `SETTLED`.

**SalesChannel.status:** `PLANNING`, `READY_FOR_DISPATCH`, `FULFILLED`, `CANCELLED`.

**ProductOffer.status:** `PENDING`, `RESERVED`, `CONFIRMED`, `FULFILLED`, `CANCELLED`.

**FulfillmentAllocation.status:** `PENDING_REVIEW`, `QUALITY_CHECKED`, `DISPATCHED`, `DELIVERED`, `SETTLED`, `REJECTED`, `CANCELLED`.

**DiscountVoucher.status:** `DRAFT`, `ACTIVE`, `EXHAUSTED` (may transition back from `EXHAUSTED` to `ACTIVE` when budget is restored).

**ProductOffer.required_warehouse_certification** and certification `name` values: `COLD_CHAIN_CERTIFIED`, `HAZMAT_LICENSED`, `FRAGILE_HANDLING`, `NONE` (default when omitted).

**DiscountVoucher.discount_type:** `PERCENTAGE`, `FIXED_AMOUNT`.

---

## 3. Business Logic & Workflows

### 3.1. Seller Account Onboarding and Activation

A `SellerManager` opens a seller account by supplying `seller_name`, `business_category`, `base_commission_rate`, and `fee_budget`. On creation, the system sets `status` to `ONBOARDING`, initializes `fee_balance` to match `fee_budget`, and sets `compliance_score` to zero. A `SettlementAdmin` activates the account via the activate operation only while `status` is `ONBOARDING`; otherwise the system responds with `ERR_ACCOUNT_NOT_IN_ONBOARDING`. After activation, `status` becomes `ACTIVE`, enabling channels, offers, centers, restrictions, vouchers, and allocations as described below. Operations that require an operational storefront but find `ONBOARDING`, `SETTLEMENT_PENDING`, or `SETTLED` where `ACTIVE` is required fail with `ERR_ACCOUNT_NOT_ACTIVE`.

### 3.2. Sales Channels and Product Offers

Under an `ACTIVE` account, a `SellerManager` defines **SalesChannel** rows with `channel_name`, `start_minute`, and `end_minute` (non-negative integers with `end_minute` strictly greater than `start_minute`; violations surface as `ERR_INVALID_CHANNEL_MINUTES`). Each channel carries `seller_account_id`, and its `status` begins in `PLANNING`.

Within a channel, **ProductOffer** records describe salable inventory: `product_name`, `product_category`, `unit_price`, `quantity_available` (must be a positive integer or the API returns `ERR_INVALID_OFFER_QUANTITY`), optional `required_warehouse_certification`, and a listing window `start_minute` / `end_minute` that must lie fully inside the parent channel’s window—failure yields `ERR_OFFER_TIME_OUTSIDE_CHANNEL` or malformed minute errors via `ERR_INVALID_OFFER_MINUTES`. The read-only `duration_minutes` derives from listing end minus listing start. New offers have `status` `PENDING` and include both `sales_channel_id` and `seller_account_id` for traceability.

An `OrderProcessor` may move a channel from `PLANNING` to `READY_FOR_DISPATCH` only when every product offer on that channel has reached `CONFIRMED`; otherwise `ERR_OFFERS_NOT_CONFIRMED` applies. Illegal transitions (for example, attempting to mutate a terminal channel) produce `ERR_ILLEGAL_CHANNEL_STATE_TRANSITION`. Cancelling a channel while still in `PLANNING` cascades: pending offers become `CANCELLED`, reserved offers with pending-review allocations cancel those allocations and unwind ledgers, and confirmed-style cleanup follows the state machine for higher states. Cancelling from `READY_FOR_DISPATCH` is allowed only if no allocation has reached `DELIVERED`; otherwise the operation cannot complete. Channel cancellation side effects restore `fee_balance`, compliance penalties, and voucher budgets associated with affected allocations.

A `SellerManager` may cancel an individual offer only in `PENDING` via the cancel endpoint; other states yield `ERR_OFFER_NOT_PENDING_FOR_CANCEL`.

### 3.3. Fulfillment Centers, Certifications, and Capacity

**FulfillmentCenter** records belong to the seller account and store `center_name`, `center_region`, per-unit freight input `cost_per_unit`, and `max_capacity` as a hard aggregate shipping limit. The `warehouse_certifications` array starts empty; the seller adds certifications by submitting a `name` drawn from the same certification vocabulary as `required_warehouse_certification` and a `certified_date`, after which the system assigns an `id` to each certification entry. Capacity enforcement is cumulative: creating an allocation that would push total committed units for that center above `max_capacity` fails with `ERR_WAREHOUSE_CAPACITY_EXCEEDED`.

### 3.4. Shipping Restrictions and Mutual Exclusion

To model incompatible warehouses, a `SellerManager` creates **ShippingRestriction** rows scoped by `seller_account_id`, with `fulfillment_center_id_1`, `fulfillment_center_id_2`, and optional `reason`. The pair is unordered; duplicating an existing pair triggers `ERR_DUPLICATE_RESTRICTION`, and pairing a center with itself is `ERR_SELF_RESTRICTION`. If two centers appear in a restriction and one already hosts a committed, non-terminal allocation for an offer in a given `sales_channel`, assigning the paired center to another offer in that same channel conflicts with `ERR_SHIPPING_RESTRICTION_CONFLICT`.

### 3.5. Discount Vouchers

A `SellerManager` drafts **DiscountVoucher** entities under the owning account’s `seller_account_id`, with `voucher_code`, `discount_type`, `discount_value`, `min_order_value`, `max_discount_cap`, and `total_budget`. On creation, `budget_remaining` initializes to `total_budget` and `status` is `DRAFT`. Activation (only from `DRAFT` while the seller account is `ACTIVE`) moves `status` to `ACTIVE`; violating either condition yields `ERR_VOUCHER_NOT_DRAFT` or account-state errors. When an allocation consumes the last budget, the system moves the voucher to `EXHAUSTED`; refunds from cancelled or rejected allocations can increase `budget_remaining` and automatically restore `EXHAUSTED` vouchers to `ACTIVE` when appropriate.

### 3.6. Fulfillment Allocation: Proposal, Review, Dispatch, Delivery

A `SellerManager` proposes a **FulfillmentAllocation** under the same `seller_account_id` as the offer and center, by naming `product_offer_id` and `fulfillment_center_id`, optionally `voucher_id`, and optionally `override_compliance_check`. The offer must be `PENDING` or the request fails with `ERR_OFFER_NOT_PENDING`. The fulfillment center must satisfy the offer’s `required_warehouse_certification` against the center’s `warehouse_certifications` or the API responds with `ERR_CERTIFICATION_MISMATCH`.

**Discount path:** when `voucher_id` is present, the voucher must exist, be `ACTIVE`, and pass order-minimum and budget checks; otherwise expect `ERR_VOUCHER_NOT_FOUND`, `ERR_VOUCHER_NOT_ACTIVE`, `ERR_ORDER_VALUE_BELOW_MINIMUM`, or `ERR_VOUCHER_BUDGET_EXHAUSTED`. The system computes `discount_amount` from `unit_price`, `quantity_available`, `discount_type`, `discount_value`, and `max_discount_cap`, then debits `budget_remaining`.

**Turnaround rule:** On a given fulfillment center, any two offers whose `product_category` differ must respect a minimum gap of **60 minutes** between the earlier offer’s `end_minute` and the later offer’s `start_minute`; same-category listings do not require this gap. Violations raise `ERR_FULFILLMENT_WINDOW_VIOLATION`.

**Compliance path:** creating the allocation may increase `compliance_score` by **30** points when `is_high_volume` is true (see §3.7) and by an additional **80** when `override_compliance_check` is used while the score would already reach or exceed **300** without override—the latter sets `compliance_override_penalty_applied` to true. If, without override, the score would reach or exceed **300**, the API rejects with `ERR_COMPLIANCE_THRESHOLD_BREACHED`. Validation order for fiscal and compliance checks follows: compliance threshold (with override semantics), then whether `provisional_shipping_cost` + `provisional_commission` fits remaining `fee_balance` (`ERR_INSUFFICIENT_FEE_BUDGET`).

On success, the offer becomes `RESERVED`, provisional charges reserve `fee_balance`, and the allocation’s `status` starts in `PENDING_REVIEW`.

An `OrderProcessor` may `quality-check` (to `QUALITY_CHECKED`), `reject`, or `cancel` while in `PENDING_REVIEW`; wrong states raise `ERR_ALLOCATION_NOT_PENDING_REVIEW`. Rejection or cancellation refunds provisional fees and compliance penalties and restores voucher budget; offers return to `PENDING`.

Dispatch moves `QUALITY_CHECKED` → `DISPATCHED`, flips the offer to `CONFIRMED`, and recomputes provisional shipping using only same-center allocations already `DISPATCHED` with strictly earlier `start_minute`, and recomputes provisional commission using seller-wide `DISPATCHED` history with strictly earlier `start_minute`. The system adjusts `fee_balance` by the net provisional delta and may toggle `is_high_volume` and compliance penalties accordingly.

`confirm-delivery` requires `DISPATCHED` and moves to `DELIVERED` (`ERR_ALLOCATION_NOT_DISPATCHED` if not). Cancellation remains available from `PENDING_REVIEW`, `QUALITY_CHECKED`, or `DISPATCHED` (`ERR_ALLOCATION_NOT_CANCELLABLE` otherwise); recalling a dispatched shipment returns offers from `CONFIRMED` to `PENDING` per the state machine.

### 3.7. High-Volume Shipping Surge and Commission Tiering

For provisional and final **shipping**, the system aggregates units per fulfillment center against a surge threshold of **10,000** units. Beyond that threshold, units are charged at **double** the center’s `cost_per_unit` when they fall into the excess portion, using the forward-looking set for provisional calculations and chronological delivery order for final calculations. The boolean `is_high_volume` mirrors whether the relevant forward-looking per-center total exceeds that threshold and drives compliance penalties.

For **commission**, the seller’s total shipped units across centers determine whether the effective rate receives a large-seller **20%** reduction once cumulative units exceed **50,000**; mixed-rate splits apply when a single offer straddles the threshold. Commission uses net merchandise value after `discount_amount` at both provisional and final stages.

### 3.8. Settlement Initiation and Finalization

An `OrderProcessor` may move an `ACTIVE` account to `SETTLEMENT_PENDING` only if no allocations remain in `PENDING_REVIEW` or `QUALITY_CHECKED`; otherwise `ERR_UNRESOLVED_ALLOCATIONS_EXIST` applies.

A `SettlementAdmin` finalizes settlement only from `SETTLEMENT_PENDING`. The operation computes `final_shipping_cost` and `final_commission` for every `DELIVERED` allocation, transitions them to `SETTLED`, marks `CONFIRMED` offers `FULFILLED`, marks `READY_FOR_DISPATCH` channels `FULFILLED`, and sets the account to `SETTLED` if the sum of all finalized shipping plus commission is within the original `fee_budget` (`ERR_SETTLEMENT_EXCEEDS_BUDGET` otherwise). It also reconciles `fee_balance` to reflect remaining budget after finalized totals.

### 3.9. Request Validation and Cross-Cutting Errors

Malformed payloads or type mismatches may be rejected with `ERR_INVALID_REQUEST`. State-specific guardrails include `ERR_ACCOUNT_NOT_READY_FOR_SETTLEMENT` when finalizing outside `SETTLEMENT_PENDING`, and allocation action errors (`ERR_ALLOCATION_NOT_QUALITY_CHECKED`, etc.) as described above. Optimistic concurrency conflicts surface as `ERR_STALE_DATA`. Together, these behaviors complement the auth errors `ERR_MISSING_OR_INVALID_AUTH_HEADER` and `ERR_INSUFFICIENT_PERMISSIONS` and the not-found family (`ERR_SELLER_ACCOUNT_NOT_FOUND`, `ERR_SALES_CHANNEL_NOT_FOUND`, `ERR_PRODUCT_OFFER_NOT_FOUND`, `ERR_FULFILLMENT_CENTER_NOT_FOUND`, `ERR_FULFILLMENT_ALLOCATION_NOT_FOUND`, `ERR_SHIPPING_RESTRICTION_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`).

---

## 4. Endpoint Definitions

Operations that create a new primary resource return **201 Created**. Operations that mutate an existing resource or append to an embedded collection (for example, adding a warehouse certification) return **200 OK**. Read operations return **200 OK** with the envelope described in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | -------------------- |
| POST | `/seller-accounts` | Create seller account | SellerManager |
| GET | `/seller-accounts` | List seller accounts | Any |
| GET | `/seller-accounts/{accountId}` | Get seller account | Any |
| POST | `/seller-accounts/{accountId}/activate` | Activate seller account | SettlementAdmin |
| POST | `/seller-accounts/{accountId}/initiate-settlement` | Begin settlement pending | OrderProcessor |
| POST | `/seller-accounts/{accountId}/finalize-settlement` | Finalize settlement | SettlementAdmin |
| POST | `/seller-accounts/{accountId}/sales-channels` | Create sales channel | SellerManager |
| GET | `/seller-accounts/{accountId}/sales-channels` | List sales channels | Any |
| GET | `/seller-accounts/{accountId}/sales-channels/{channelId}` | Get sales channel | Any |
| PUT | `/seller-accounts/{accountId}/sales-channels/{channelId}` | Update sales channel | OrderProcessor |
| POST | `/seller-accounts/{accountId}/sales-channels/{channelId}/product-offers` | Create product offer | SellerManager |
| GET | `/seller-accounts/{accountId}/sales-channels/{channelId}/product-offers` | List product offers | Any |
| GET | `/seller-accounts/{accountId}/sales-channels/{channelId}/product-offers/{offerId}` | Get product offer | Any |
| POST | `/seller-accounts/{accountId}/sales-channels/{channelId}/product-offers/{offerId}/cancel` | Cancel product offer | SellerManager |
| POST | `/seller-accounts/{accountId}/fulfillment-centers` | Create fulfillment center | SellerManager |
| GET | `/seller-accounts/{accountId}/fulfillment-centers` | List fulfillment centers | Any |
| GET | `/seller-accounts/{accountId}/fulfillment-centers/{centerId}` | Get fulfillment center | Any |
| POST | `/seller-accounts/{accountId}/fulfillment-centers/{centerId}/certifications` | Add warehouse certification | SellerManager |
| POST | `/seller-accounts/{accountId}/fulfillment-allocations` | Create fulfillment allocation | SellerManager |
| GET | `/seller-accounts/{accountId}/fulfillment-allocations` | List fulfillment allocations | Any |
| GET | `/seller-accounts/{accountId}/fulfillment-allocations/{allocationId}` | Get fulfillment allocation | Any |
| POST | `/seller-accounts/{accountId}/fulfillment-allocations/{allocationId}/reject` | Reject allocation | OrderProcessor |
| POST | `/seller-accounts/{accountId}/fulfillment-allocations/{allocationId}/cancel` | Cancel allocation | OrderProcessor |
| POST | `/seller-accounts/{accountId}/fulfillment-allocations/{allocationId}/quality-check` | Quality-check allocation | OrderProcessor |
| POST | `/seller-accounts/{accountId}/fulfillment-allocations/{allocationId}/dispatch` | Dispatch allocation | OrderProcessor |
| POST | `/seller-accounts/{accountId}/fulfillment-allocations/{allocationId}/confirm-delivery` | Confirm delivery | OrderProcessor |
| POST | `/seller-accounts/{accountId}/shipping-restrictions` | Create shipping restriction | SellerManager |
| GET | `/seller-accounts/{accountId}/shipping-restrictions` | List shipping restrictions | Any |
| GET | `/seller-accounts/{accountId}/shipping-restrictions/{restrictionId}` | Get shipping restriction | Any |
| POST | `/seller-accounts/{accountId}/discount-vouchers` | Create discount voucher | SellerManager |
| GET | `/seller-accounts/{accountId}/discount-vouchers` | List discount vouchers | Any |
| GET | `/seller-accounts/{accountId}/discount-vouchers/{voucherId}` | Get discount voucher | Any |
| POST | `/seller-accounts/{accountId}/discount-vouchers/{voucherId}/activate` | Activate discount voucher | SellerManager |

---

## 5. Error Code Catalogue

| error_id | HTTP status |
| -------- | ----------- |
| `ERR_MISSING_OR_INVALID_AUTH_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_SELLER_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_SALES_CHANNEL_NOT_FOUND` | 404 |
| `ERR_PRODUCT_OFFER_NOT_FOUND` | 404 |
| `ERR_FULFILLMENT_CENTER_NOT_FOUND` | 404 |
| `ERR_FULFILLMENT_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_SHIPPING_RESTRICTION_NOT_FOUND` | 404 |
| `ERR_VOUCHER_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_ACCOUNT_NOT_IN_ONBOARDING` | 409 |
| `ERR_ACCOUNT_NOT_READY_FOR_SETTLEMENT` | 409 |
| `ERR_ILLEGAL_CHANNEL_STATE_TRANSITION` | 409 |
| `ERR_OFFER_NOT_PENDING` | 409 |
| `ERR_OFFER_NOT_PENDING_FOR_CANCEL` | 409 |
| `ERR_ALLOCATION_NOT_PENDING_REVIEW` | 409 |
| `ERR_ALLOCATION_NOT_QUALITY_CHECKED` | 409 |
| `ERR_ALLOCATION_NOT_DISPATCHED` | 409 |
| `ERR_ALLOCATION_NOT_CANCELLABLE` | 409 |
| `ERR_VOUCHER_NOT_ACTIVE` | 409 |
| `ERR_VOUCHER_NOT_DRAFT` | 409 |
| `ERR_INVALID_CHANNEL_MINUTES` | 400 |
| `ERR_INVALID_OFFER_MINUTES` | 400 |
| `ERR_OFFER_TIME_OUTSIDE_CHANNEL` | 400 |
| `ERR_INVALID_OFFER_QUANTITY` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CERTIFICATION_MISMATCH` | 400 |
| `ERR_FULFILLMENT_WINDOW_VIOLATION` | 409 |
| `ERR_SHIPPING_RESTRICTION_CONFLICT` | 409 |
| `ERR_WAREHOUSE_CAPACITY_EXCEEDED` | 409 |
| `ERR_SELF_RESTRICTION` | 400 |
| `ERR_DUPLICATE_RESTRICTION` | 409 |
| `ERR_ORDER_VALUE_BELOW_MINIMUM` | 400 |
| `ERR_VOUCHER_BUDGET_EXHAUSTED` | 402 |
| `ERR_COMPLIANCE_THRESHOLD_BREACHED` | 403 |
| `ERR_INSUFFICIENT_FEE_BUDGET` | 402 |
| `ERR_SETTLEMENT_EXCEEDS_BUDGET` | 402 |
| `ERR_OFFERS_NOT_CONFIRMED` | 409 |
| `ERR_UNRESOLVED_ALLOCATIONS_EXIST` | 409 |
| `ERR_STALE_DATA` | 409 |
