# Trophy, Awards & Engraving API — Product Requirements Document

## 1. Introduction

This document specifies the back-office API for a Trophy, Awards & Engraving shop — the kind of business that takes a club's hand-scrawled order for "twenty-five acrylic stars, engraved, logo on the base, needed by Friday" and turns it into a priced, proofed, produced, and handed-off job. The system has to hold several concerns together at once: a configurable product catalogue with per-character engraving and logo charges, a quantity- and rush-sensitive pricing engine that distinguishes a provisional estimate from a locked invoice, a proof-approval loop that may cycle through several revision rounds before a customer signs off, a physical component inventory that must be reserved and consumed without ever going negative, and a fulfillment step that branches between in-store pickup and shipped parcels.

The core challenge the API solves is keeping money, materials, and production state consistent across a workflow where each step depends on the one before it. An order cannot be confirmed until every line's artwork is approved; production cannot begin until a deposit is collected; a trophy cannot be assembled until its base and column are physically in stock; and the order cannot be handed off until it is paid in full. Because several operators — customers, production staff, and the shop manager — touch the same order over its life, the system also guards against one actor acting on a stale view of an order another actor has already advanced. The sections that follow define the global contract first, then the business workflows, then the concrete endpoint and error surfaces.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and boilerplate that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request other than the two bootstrap operations described below must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes four roles: `Anonymous`, `Customer`, `ShopStaff`, and `ShopManager`. If either header is missing on a protected endpoint, or if `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `Anonymous` role is an opaque, unauthenticated identity: its `X-User-ID` is not tied to any persisted entity, and the server never compares it to any record's `id`. `Anonymous` may perform exactly two operations — registering a customer and setting the test clock — and these two operations do not require authentication headers at all. The `ShopStaff` and `ShopManager` roles are likewise opaque operator identities: their `X-User-ID` values are recorded on requests they make but are never matched against any entity's `id`; permission for these two roles is determined solely by which operations their role is allowed to perform.

The `Customer` role is entity-backed. When `X-User-Role` is `Customer`, the `X-User-ID` is the `id` of the acting `Customer` record. Ownership is enforced on every order a customer touches: the order's `customer_id` must equal the caller's `X-User-ID`, and a customer attempting to read or drive an order it does not own is rejected with `ERR_FORBIDDEN`. This ownership check also reaches resources nested beneath an order — its lines, proofs, payments, and fulfillments inherit the owning order's `customer_id` for the purpose of the check.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` defaults to 0 and represents the number of leading records to skip. List results are ordered by `created_at` in ascending order — oldest record first — unless an endpoint's narrative states otherwise. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in its `meta` block, where `total_count` is the total number of records matching the query before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID carrying no type prefix. Most resources also carry three common audit properties: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 on creation and increases by exactly 1 on every mutation that changes the resource. The `created_at` value is fixed at creation; `updated_at` is refreshed on every mutation.

Two entities are deliberately leaner. A `Payment` record carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because a payment is an immutable event whose only later change is a status flip handled through its owning order. All other entities — `Customer`, `CatalogProduct`, `Component`, `RushPolicy`, `PromoCode`, `Order`, `OrderLine`, `Proof`, `ComponentAllocation`, and `Fulfillment` — carry the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. Monetary Precision and Rounding

All money is represented in integer cents; the API never stores fractional cents. Where a calculation multiplies a cents amount by a fractional rate — a rush surcharge, a percentage promo, or a per-line volume discount — the result is taken **floored** to the nearest whole cent (rounded toward zero, discarding the fractional part). The single exception is the deposit calculation, which is rounded **up** to the next whole cent (ceiling). Pure integer additions and subtractions, such as summing line subtotals, are exact and need no rounding. Percentages reported to the customer — specifically the on-time fulfillment rate — are the lone non-cents value and are rounded half-up to two decimal places.

### 2.6. Nested Resource Addressing

Several resources are addressed through a path that names their ancestors — for example a proof is reached through its owning order line, and a hand-off is reached through its owning order and fulfillment. Path identifiers are validated left to right: the order is checked before the order line, the order line before the proof, and the fulfillment before the hand-off target. The first identifier in the path that names a non-existent record — whether an `order_id`, an `order_line_id`, a proof, a `component_id`, a `catalog_product_id`, a `promo_code_id`, a customer, a fulfillment, or a component allocation — causes the request to be rejected with `ERR_NOT_FOUND` before any deeper identifier or body field is examined. Foreign-key fields supplied in a request body are validated the same way.

### 2.7. Request Validation Ordering

When a single request could fail several checks, the checks are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization and ownership (`ERR_FORBIDDEN`), then existence of every referenced resource (`ERR_NOT_FOUND`), then structural validity of the body — required fields present, correct types, valid enum members, `quantity` at least 1, amounts not negative (`ERR_INVALID_REQUEST`). Only after all four of those pass does the system evaluate whether the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`), and only then are the domain-specific business rules described throughout Section 3 applied. Within the business-rule tier, the optimistic-concurrency version check precedes the remaining domain checks. Concretely: a request that is both unauthenticated and references a missing resource returns `ERR_UNAUTHENTICATED`, and a request whose target is in the wrong state but also violates a business rule returns `ERR_INVALID_STATE` first.

### 2.8. Optimistic Concurrency on Orders

Two order operations are guarded by optimistic concurrency control against the order's `version`, and both require a non-optional `expected_order_version` field in their request body. The first is order confirmation. Because confirming an order locks its invoice, redeems its promo code, and reserves physical components, a confirmation must reflect the exact priced state the caller last observed. The confirmation request must carry `expected_order_version` equal to the target order's current `version`; if another writer has advanced that order's `version` since the caller last read it — by re-pricing it, editing it, or confirming it first — the confirmation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from committing against a price or line set it has not seen.

The second guarded operation is reorder. A reorder clones a source order's lines and engraving text into a fresh draft, so the caller's intent is pinned to a specific snapshot of that source. The reorder request must carry `expected_order_version` equal to the **source** order's current `version`; if the source has been edited, re-priced, or otherwise advanced since the caller last read it, the reorder is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

### 2.9. Inventory Integrity

Component stock is the system's most jealously guarded invariant. Each `Component` tracks `on_hand_qty`, the physical units actually in the building, and a derived `allocated_qty`, the sum of `qty` across all of that component's allocations currently in `RESERVED` status. Its `available_qty` is `on_hand_qty` minus `allocated_qty`, and this figure must never fall below zero — the workflow rules in Section 3 are designed so that reservations and consumptions can never drive it negative. A component's `low_stock` flag is true exactly when its `available_qty` is less than or equal to its configured `reorder_point`, and false otherwise. Whenever any allocation changes status, stock is received, a line is assembled, or an order is cancelled, the affected component's `allocated_qty`, `available_qty`, and `low_stock` are all recomputed from scratch.

## 3. Business Logic & Workflows

### 3.1. Foundational Configuration: Customers, Catalogue, Inventory, and Policy

Before any order can be taken, the shop's reference data must exist. A customer is registered with a contact `email` (which must be unique across all customers and non-empty), a `full_name`, and an optional `org_name` for the club or organization. A unique-field collision — a second customer with the same `email` — is rejected with `ERR_DUPLICATE_VALUE`. A newly registered customer starts with a `lifetime_completed_orders` of 0 and an `on_time_rate_pct` of null; both are computed values that the customer never sets directly. Registration is open to the `Anonymous` and `ShopManager` roles.

The shop manager builds the catalogue. Each `CatalogProduct` carries a unique, non-empty `sku`, a display `name`, and a `product_type` that is one of `TROPHY`, `PLAQUE`, `MEDAL`, `ACRYLIC`, or `CRYSTAL`. Pricing inputs include a `base_price_cents` charged per unit before any engraving, an `engraving_price_per_char_cents` surcharge applied per engraved character per unit, and a `logo_setup_fee_cents` charged once on any line that includes a logo proof; each of these must be zero or greater. A product also declares its `standard_lead_days`, the number of business days from confirmation that the product needs under standard service, which must be at least 1, and a `bom` — a bill of materials, given as a list of `{ component_id, qty_per_unit }` entries naming the components consumed per finished unit. A product's `active` flag defaults to true; an inactive product cannot be added to new lines but continues to back any lines already referencing it. The manager may later update a product's `active` flag, `base_price_cents`, `engraving_price_per_char_cents`, `logo_setup_fee_cents`, or `standard_lead_days`; each such update increments the product's `version`.

Components are the physical materials. A `Component` has a unique, non-empty `code`, a `name`, an initial `on_hand_qty` (zero or greater), and an optional `reorder_point` that defaults to 0. On creation its `allocated_qty` is 0, its `available_qty` equals its `on_hand_qty`, and its `low_stock` flag is computed against the reorder point. Receiving stock raises `on_hand_qty` by the supplied `received_qty` and recomputes the derived figures, bumping the component's `version`. Components are visible to `ShopStaff` and `ShopManager`; creation and receiving are reserved to `ShopManager`.

Two further pieces of configuration govern pricing. A `RushPolicy` carries a `name`, an `expedited_surcharge_pct` and a `rush_surcharge_pct` (the fractional surcharges applied to expedited and rush jobs respectively), an optional `standard_surcharge_pct` that defaults to 0, an optional `rush_min_business_days` floor that defaults to 1, and an `active` flag. Exactly one rush policy may be active at a time: when a policy is created with `active` set to true, any other currently active policy is set inactive, and the pricing engine always reads the single active policy. A `PromoCode` carries a unique, uppercase `code`, a `kind` of either `PERCENT` or `FLAT`, a `percent_off` fraction (used when the kind is `PERCENT`), a `flat_off_cents` amount (used when the kind is `FLAT`), a `min_subtotal_cents` gate that defaults to 0, an optional `max_uses` cap (null meaning unlimited), a computed `uses_count` starting at 0, and an `active` flag. When a promo code is created, a `PERCENT` code must supply a `percent_off` greater than 0 and at most 1, a `FLAT` code must supply a `flat_off_cents` greater than 0, and any surcharge or discount percentage must be zero or greater; a well-typed but semantically invalid value here — a percent outside that range, a `PERCENT` code with no `percent_off`, or a `FLAT` code with no `flat_off_cents` — is rejected with `ERR_VALIDATION`. The same `ERR_VALIDATION` guards the surcharge percentages supplied when creating a rush policy.

### 3.2. Building a Draft Order and Its Lines

A customer (or staff acting on their behalf) opens an order by naming the owning `customer_id`, a `service_level` of `STANDARD`, `EXPEDITED`, or `RUSH`, a requested `due_date` (a calendar date at UTC midnight), and an optional `promo_code_id` to apply. A new order begins in `production_status` `DRAFT` and `payment_status` `UNPAID`, with `version` 1 and every computed total at its default. The `service_level` may be changed only while the order is still in `DRAFT`.

Lines are added one at a time to a draft order. Each `OrderLine` names a `catalog_product_id`, a `quantity` of at least 1, an optional `engraving_text` (defaulting to an empty string, applied identically to every unit of the line), and an optional `include_logo` flag (defaulting to false) that, when set, brings a logo proof and the product's one-time logo setup fee. The referenced product must be active at the moment the line is created; adding a line for a product whose `active` is false is rejected with `ERR_PRODUCT_INACTIVE`. A new line starts in `line_status` `PENDING` with `assembled_count` 0, and adding it increases the order's `line_count` by 1 and increments the order's `version`. A line's `order_id` is set by the system to its parent order. Lines may also be removed from a draft or priced order; removal decreases `line_count` by 1 and increments the order's `version`.

The header of an order may be edited while it is in `DRAFT` or `PRICED`: a customer or staff member may change the `service_level`, the `due_date`, or the `promo_code_id`. Crucially, any edit to a priced order — whether a header change, an added line, or a removed line — invalidates the provisional estimate. When an order in `PRICED` is edited, added to, or has a line removed, its `production_status` reverts to `DRAFT`, its `rush_tier`, `estimate_subtotal_cents`, and `estimate_total_cents` are cleared back to their defaults, and its `version` increments; the order must then be re-priced before it can be confirmed.

### 3.3. The Proof Approval Loop

Artwork on every line must be approved before that line can be produced. A proof is created against a line by staff, carrying a `proof_kind` of `TEXT` or `LOGO` and a `content_ref` that snapshots the engraving text (for a text proof) or references the logo asset (for a logo proof). A new `Proof` starts in `proof_status` `DRAFT` with `revision_round` 1 and an empty `approved_text_snapshot`; its `order_line_id` ties it to the line it customizes.

Staff send a draft proof to the customer, advancing it `DRAFT → SENT` and stamping `sent_at` with the current time. A proof may only be sent while its owning order is in `production_status` `DRAFT`, `PRICED`, or `IN_PRODUCTION` — proofs are normally prepared before confirmation, but a fresh proof can also be sent during production after a change request; an attempt to send while the order is `CONFIRMED`, `READY`, `FULFILLED`, or `CANCELLED` is rejected with `ERR_INVALID_STATE`. The customer then decides. Approving a sent proof advances it `SENT → APPROVED`, a terminal state, and captures `approved_text_snapshot` from the proof's `content_ref`; the engraving step later runs against this frozen snapshot rather than the live `engraving_text` on the line. Approving any one proof on a line is what unblocks that line for confirmation and for engraving.

Alternatively the customer requests changes, advancing the proof `SENT → CHANGES_REQUESTED`. This is the entry point of the revision cascade: if the owning line is currently in `line_status` `ALLOCATED` or `ENGRAVING`, the line reverts to `PENDING`, its `assembled_count` is reset to 0, and any engraving-stage progress is discarded — but the line's reserved component allocations are kept in `RESERVED` and are not released. Staff then revise the changed proof, advancing it `CHANGES_REQUESTED → DRAFT`; revision increments `revision_round` by 1, clears `sent_at`, clears `approved_text_snapshot`, and may carry a new `content_ref`. From `DRAFT` the proof can be sent again, so the loop `SENT → CHANGES_REQUESTED → DRAFT → SENT` repeats until the customer approves.

### 3.4. Pricing: From Provisional Estimate to Locked Invoice

Pricing happens in two passes against the same arithmetic, differing only in whether the promo is applied. The first pass, the **estimate**, runs when staff price a draft order, advancing it `DRAFT → PRICED`. Pricing requires the order to be in `DRAFT`, to have at least one line (`line_count` of 1 or more), and to have exactly one active rush policy in place. Pricing also requires the due date to be feasible — see the rush-tier rule below — and on success it increments the order's `version`.

Pricing first classifies the job's **rush tier**. The system computes the number of business days from the current date to the `due_date`, counting only weekdays and excluding the current day itself. If that count is below the active policy's `rush_min_business_days`, the due date is infeasible and pricing is rejected with `ERR_DUE_DATE_INFEASIBLE`. Otherwise the tier is resolved against two breakpoints: if the business-day count is fewer than 3, the `rush_tier` is `RUSH` and the surcharge is the policy's `rush_surcharge_pct`; if the count is 3 or more but still fewer than the largest `standard_lead_days` among the products on the order's lines, the `rush_tier` is `EXPEDITED` and the surcharge is the policy's `expedited_surcharge_pct`; otherwise the `rush_tier` is `STANDARD` and the surcharge is the policy's `standard_surcharge_pct`. The threshold at 3 business days is strict: a job due in exactly 3 business days is `EXPEDITED`, while a job due in 2 business days is `RUSH`.

Each line is then priced. A line's character count, `char_count`, is the length of its `engraving_text` with whitespace counted (an empty string yields 0). The per-unit price is the product's `base_price_cents` plus `char_count` multiplied by the product's `engraving_price_per_char_cents`. The line's `line_subtotal_cents` is the `quantity` multiplied by that per-unit price, plus the product's `logo_setup_fee_cents` once if `include_logo` is set (the logo fee is charged a single time per line, never per unit). A per-line **volume discount** is then resolved by the line's `quantity` against three breakpoints, selecting a single tier rather than stacking brackets: a quantity of 100 or more sets `volume_tier` to `TIER3` at a 15 percent rate; a quantity of 50 or more but fewer than 100 sets `TIER2` at 10 percent; a quantity of 25 or more but fewer than 50 sets `TIER1` at 5 percent; and any quantity below 25 sets `NONE` at 0 percent. These breakpoints are inclusive at the lower edge — a quantity of exactly 25 is `TIER1`, while a quantity of 24 is `NONE`. The discount applies only to the engraved goods, excluding the one-time logo fee: take the line's `line_subtotal_cents`, subtract the `logo_setup_fee_cents` if `include_logo` is set, multiply that goods amount by the tier rate, floor it to whole cents, and store the result as `volume_discount_cents`.

The order's totals are then assembled in a pinned order of operations. First, the order subtotal is the exact integer sum, over every line regardless of its status, of each line's `line_subtotal_cents` minus its `volume_discount_cents`. Second, the rush amount is that subtotal multiplied by the resolved tier's surcharge fraction, floored to whole cents; the pre-promo amount is the subtotal plus the rush amount. Third comes the promo: a promo is considered only when a `promo_code_id` is present and the order subtotal is at least the promo's `min_subtotal_cents`; when it applies, a `PERCENT` promo's discount is the subtotal (not the pre-promo amount) multiplied by `percent_off`, floored to whole cents, while a `FLAT` promo's discount is the smaller of `flat_off_cents` and the pre-promo amount. The grand total is the pre-promo amount minus the promo discount, but never below zero.

In the **estimate** pass the promo is deliberately *not* applied even when a `promo_code_id` is present: `estimate_subtotal_cents` is set to the order subtotal, `estimate_total_cents` is set to the pre-promo amount, and the promo's `uses_count` is left untouched. The **invoice** pass runs at confirmation and uses identical subtotal and rush arithmetic, but the promo *is* applied and redeemed: `invoice_subtotal_cents` is set to the subtotal, `invoice_total_cents` is set to the promo-adjusted grand total, and the promo's `uses_count` increases by 1. Because the invoice applies a discount the estimate omits, the invoice total is at most the estimate total whenever a valid promo exists.

### 3.5. Confirmation: Locking the Invoice and Reserving Materials

Confirmation is the pivot of the order's life and the moment money and materials commit. A customer confirms a priced order, advancing it `PRICED → CONFIRMED`. The request must carry `expected_order_version` matching the order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` as described in Section 2.8. Beyond the version check, confirmation enforces a sequence of business rules. The order must be in `PRICED`, or the transition is rejected with `ERR_INVALID_STATE`. Every line on the order must have at least one proof in `proof_status` `APPROVED`; a line lacking an approved proof causes `ERR_PROOF_NOT_APPROVED`. If a `promo_code_id` is set, the promo must be active and, where `max_uses` is not null, its `uses_count` must still be below `max_uses`, or the confirmation is rejected with `ERR_PROMO_INVALID`; the order's subtotal must also meet the promo's `min_subtotal_cents`, or it is rejected with `ERR_PROMO_MIN_NOT_MET`. Finally, for every line, each component named in the product's `bom` must have an `available_qty` at least equal to the quantity the line would reserve, or confirmation is rejected with `ERR_COMPONENT_SHORTAGE`.

When all checks pass, the invoice arithmetic of Section 3.4 runs and locks `invoice_subtotal_cents` and `invoice_total_cents`. The deposit is then computed: `deposit_due_cents` is the invoice total multiplied by one half, rounded up to the next whole cent — except that a `RUSH`-tier order requires full prepayment, so for a `RUSH` order the `deposit_due_cents` equals the full `invoice_total_cents`. Confirmation also creates the material reservations: one `ComponentAllocation` in `alloc_status` `RESERVED` is created for each (line, bom-component) pair, with its `qty` equal to the component's `qty_per_unit` multiplied by the line's `quantity`, and its `order_line_id` and `component_id` set accordingly. Each affected component's `allocated_qty`, `available_qty`, and `low_stock` are recomputed. If a `promo_code_id` is set, its `uses_count` increases by 1, redeeming the code exactly here. The order's `version` increments.

### 3.6. Payments and the Deposit Gate

The payment dimension runs in parallel to production and is driven by the customer. A `Payment` records an `amount_cents` (at least 1), a `kind` of `DEPOSIT`, `BALANCE`, or `FULL`, and is created in `pay_status` `CAPTURED`; its `order_id` ties it to the order, and recording it adds its `amount_cents` to the order's `amount_paid_cents`, which is the running sum of captured payments less any refunds.

A deposit moves the order `UNPAID → DEPOSIT_PAID`. It is payable only after the invoice is locked — that is, the order's `production_status` must be `CONFIRMED`, or the payment is rejected with `ERR_INVALID_STATE` — and only while `payment_status` is `UNPAID`. Its `amount_cents` must equal `deposit_due_cents` exactly, or the payment is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A balance payment moves the order `DEPOSIT_PAID → PAID_IN_FULL`; its `amount_cents` must equal `invoice_total_cents` minus the `amount_paid_cents` already collected, or it too yields `ERR_PAYMENT_AMOUNT_MISMATCH`. Alternatively, a single full payment moves a confirmed order directly `UNPAID → PAID_IN_FULL`; this requires `production_status` to be `CONFIRMED`, `payment_status` to be `UNPAID`, and `amount_cents` to equal `invoice_total_cents` exactly, again on pain of `ERR_PAYMENT_AMOUNT_MISMATCH`. The `REFUNDED` payment status is terminal and is reached only through cancellation, described in Section 3.9.

### 3.7. Production: Allocate, Engrave, Assemble

Once a deposit (or full payment) is in hand, staff begin production, advancing the order `CONFIRMED → IN_PRODUCTION`. This step requires the order to be in `CONFIRMED` and its `payment_status` to be `DEPOSIT_PAID` or `PAID_IN_FULL`; starting production while the order is still `UNPAID` is rejected with `ERR_DEPOSIT_REQUIRED`. Starting production flips every `PENDING` line to `line_status` `ALLOCATED` — their reserved allocations stay `RESERVED` — and increments the order's `version`.

A line then moves through engraving. Staff advance a line `ALLOCATED → ENGRAVING`; this requires the line to be `ALLOCATED`, the owning order to be `IN_PRODUCTION`, and the line to have a proof in `proof_status` `APPROVED`, failing which the request is rejected with `ERR_PROOF_NOT_APPROVED`. Engraving uses the proof's frozen `approved_text_snapshot`, not whatever `engraving_text` currently sits on the line. Staff then assemble the line, advancing it `ENGRAVING → ASSEMBLED`. Assembly requires the line to be `ENGRAVING` and requires that every `RESERVED` allocation for the line have a backing component whose physical `on_hand_qty` is at least the allocation's `qty`; if physical stock has fallen short, assembly is rejected with `ERR_COMPONENT_SHORTAGE`. On success the line's `assembled_count` is set to its `quantity`, and each of the line's allocations advances `RESERVED → CONSUMED`: every affected component's `on_hand_qty` and `allocated_qty` are both reduced by the allocation's `qty`, and its `available_qty` and `low_stock` are recomputed.

Assembly carries a bubble-up effect. When the assembly that finishes a line leaves every line on the order in `ASSEMBLED`, the order auto-advances `IN_PRODUCTION → READY`, stamping `ready_at` with the current time and incrementing the order's `version`. This system transition fires only when the order is `IN_PRODUCTION` and all of its lines are assembled. Recall from Section 3.3 that a change request on an in-flight line (one that is `ALLOCATED` or `ENGRAVING`) reverts that line to `PENDING` and zeroes its `assembled_count` while keeping its allocations `RESERVED`, so a late change request can pull a line back out of the production pipeline.

### 3.8. Fulfillment: Pickup or Ship, and Hand-Off

A `READY` order is fulfilled through a staged fulfillment that branches by method. Staff stage a `Fulfillment` naming a `method` of `PICKUP` or `SHIP`, an optional `ship_address`, and an optional `ship_weight_grams`; it is created in `fulfillment_status` `STAGED` with its `order_id` set. For a `PICKUP` the `ship_fee_cents` stays 0. For a `SHIP`, a `ship_address` must be present and `ship_weight_grams` must be greater than 0, or staging is rejected with `ERR_SHIP_WEIGHT_REQUIRED`, and the shipping fee is computed by weight at staging time. The shipping fee is tiered by total parcel weight in grams, selecting a single bracket: a parcel weighing up to and including 1000 grams costs a flat base of 1200 cents; a parcel over 1000 grams and up to 5000 grams costs that 1200-cent base plus 300 cents for each additional whole kilogram above the first, where the number of additional kilograms is the grams above 1000 divided by 1000 and floored; and a parcel over 5000 grams costs the 1200-cent base plus the four mid-tier kilogram charges of 300 cents each (1200 cents) plus 500 cents for each whole kilogram above 5000, where that heavy-kilogram count is the grams above 5000 divided by 1000 and floored. The computed amount is stored as `ship_fee_cents`.

Hand-off completes the order. Staff hand off (for pickup) or dispatch (for ship) a staged fulfillment, advancing it `STAGED → HANDED_OFF` and stamping `handed_off_at`. Hand-off requires the fulfillment to be `STAGED`, the owning order to be in `READY`, and the order's `payment_status` to be `PAID_IN_FULL`; an order with a balance still owing is rejected with `ERR_BALANCE_DUE`. The same operation drives the order `READY → FULFILLED`: it stamps `fulfilled_at`, computes `due_date_met` as whether the calendar date of `fulfilled_at` is on or before the calendar date of `due_date`, and increments the order's `version`. Fulfillment also updates the customer's standing: the customer's `lifetime_completed_orders` increases by 1, and the customer's `on_time_rate_pct` is recomputed as the count of that customer's `FULFILLED` orders whose `due_date_met` is true, divided by the total count of that customer's `FULFILLED` orders, multiplied by 100, and rounded half-up to two decimal places. Until a customer has a first fulfilled order the rate stays null.

### 3.9. Reorder and Cancellation

A reorder lets a customer or staff clone an earlier order. The reorder names the source order and, optionally, a new `due_date` and `service_level`; it must carry `expected_order_version` matching the source order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` as in Section 2.8. A successful reorder creates a brand-new order in `DRAFT` whose `reorder_source_order_id` points back at the source, copying the source's lines and their `engraving_text` but **not** copying any proofs — the clone must be proofed and approved afresh. The source order's `version` increments.

Cancellation is a compensating teardown available only to the shop manager. Cancelling moves a non-terminal order — one whose `production_status` is `DRAFT`, `PRICED`, `CONFIRMED`, or `IN_PRODUCTION` — to `CANCELLED`; the two terminal states, `FULFILLED` and `CANCELLED`, reject cancellation with `ERR_INVALID_STATE`. Cancellation unwinds every commitment the order made. All of the order's `RESERVED` component allocations advance `RESERVED → RELEASED`, and each affected component's `allocated_qty`, `available_qty`, and `low_stock` are recomputed (the physical `on_hand_qty` is unchanged, since released materials were never consumed). If the order had reached `CONFIRMED` or beyond and thereby redeemed its promo, the promo's `uses_count` is decremented by 1 to compensate. If any money had been captured — that is, the order's `amount_paid_cents` is greater than 0 — every `CAPTURED` payment is moved to `REFUNDED`, the order's `payment_status` is set to `REFUNDED`, and its `amount_paid_cents` is reset to 0. The order's `version` increments.

### 3.10. Reading the System

Reads span the model. A customer, staff, or the manager may fetch an individual order, line, proof, payment, component allocation, customer, catalog product, promo code, rush policy, or fulfillment by id, and may page through collections: a customer's orders, an order's lines, an order's proofs, an order's payments, an order's fulfillments, and a line's component allocations. Component allocations may also be listed across the system and filtered by `component_id` or `order_line_id`; order lines may be listed and filtered by `order_id` or `catalog_product_id`; and orders may be listed and filtered by `customer_id`, `promo_code_id`, or `reorder_source_order_id`. A `ShopManager` can read across all resources, while a `Customer`'s reads of orders and their nested resources remain subject to the ownership rule of Section 2.1. For deterministic due-date and business-day arithmetic during testing, the server's notion of "now" can be set to a supplied UTC instant; this clock-setting capability accepts a `to_iso8601` value and is open to the `Anonymous` and `ShopManager` roles.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Endpoints that create a new resource return HTTP 201; endpoints that read or modify an existing resource return HTTP 200. Request bodies, response payloads, and side effects are described in the Section 3 narratives, not in the table below.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/customers` | Register a customer | Anonymous, ShopManager |
| GET | `/customers/{id}` | Get a customer | Customer, ShopStaff, ShopManager |
| GET | `/customers/{id}/orders` | List a customer's orders | Customer, ShopStaff, ShopManager |
| POST | `/catalog-products` | Create a catalog product | ShopManager |
| GET | `/catalog-products/{id}` | Get a catalog product | Customer, ShopStaff, ShopManager |
| PATCH | `/catalog-products/{id}` | Update a catalog product | ShopManager |
| POST | `/components` | Create a component | ShopManager |
| GET | `/components/{id}` | Get a component | ShopStaff, ShopManager |
| POST | `/components/{id}/receive` | Receive stock for a component | ShopManager |
| GET | `/order-lines/{id}/component-allocations` | List a line's component allocations | ShopStaff, ShopManager |
| GET | `/component-allocations` | List component allocations | ShopStaff, ShopManager |
| GET | `/component-allocations/{id}` | Get a component allocation | ShopStaff, ShopManager |
| POST | `/rush-policies` | Create a rush policy | ShopManager |
| GET | `/rush-policies/{id}` | Get a rush policy | ShopStaff, ShopManager |
| POST | `/promo-codes` | Create a promo code | ShopManager |
| GET | `/promo-codes/{id}` | Get a promo code | Customer, ShopStaff, ShopManager |
| POST | `/orders` | Create a DRAFT order | Customer, ShopStaff, ShopManager |
| GET | `/orders/{id}` | Get an order | Customer, ShopStaff, ShopManager |
| GET | `/orders` | List orders | ShopStaff, ShopManager |
| PUT | `/orders/{id}` | Edit a DRAFT or PRICED order header | Customer, ShopStaff |
| POST | `/orders/{id}/lines` | Add a line to a DRAFT order | Customer, ShopStaff |
| GET | `/orders/{id}/lines` | List an order's lines | Customer, ShopStaff, ShopManager |
| GET | `/order-lines/{id}` | Get an order line | Customer, ShopStaff, ShopManager |
| GET | `/order-lines` | List order lines | Customer, ShopStaff, ShopManager |
| DELETE | `/order-lines/{id}` | Remove a line from a DRAFT/PRICED order | Customer, ShopStaff |
| POST | `/orders/{id}/price` | Price an order (compute estimate) | ShopStaff |
| POST | `/orders/{id}/confirm` | Confirm an order (lock invoice, reserve) | Customer |
| POST | `/orders/{id}/reorder` | Clone a source order into a new draft | Customer, ShopStaff |
| POST | `/orders/{id}/start-production` | Begin production | ShopStaff |
| POST | `/orders/{id}/cancel` | Cancel a non-terminal order | ShopManager |
| POST | `/orders/{id}/payments` | Record a payment | Customer |
| GET | `/orders/{id}/payments` | List an order's payments | Customer, ShopStaff, ShopManager |
| POST | `/order-lines/{id}/proofs` | Create a proof for a line | ShopStaff |
| GET | `/order-lines/{id}/proofs` | List a line's proofs | Customer, ShopStaff, ShopManager |
| GET | `/proofs/{id}` | Get a proof | Customer, ShopStaff, ShopManager |
| POST | `/order-lines/{id}/proofs/{proof_id}/send` | Send a proof to the customer | ShopStaff |
| POST | `/order-lines/{id}/proofs/{proof_id}/approve` | Approve a proof | Customer |
| POST | `/order-lines/{id}/proofs/{proof_id}/request-changes` | Request changes on a proof | Customer |
| POST | `/order-lines/{id}/proofs/{proof_id}/revise` | Revise a proof | ShopStaff |
| POST | `/order-lines/{id}/engrave` | Move a line into engraving | ShopStaff |
| POST | `/order-lines/{id}/assemble` | Assemble a line | ShopStaff |
| POST | `/orders/{id}/fulfillments` | Stage a fulfillment | ShopStaff |
| GET | `/orders/{id}/fulfillments` | List an order's fulfillments | Customer, ShopStaff, ShopManager |
| POST | `/orders/{id}/fulfillments/{fulfillment_id}/hand-off` | Hand off / dispatch a fulfillment | ShopStaff |
| POST | `/_clock/set_current_utc` | Set the server clock (testing) | Anonymous, ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_DUE_DATE_INFEASIBLE | 422 |
| ERR_PRODUCT_INACTIVE | 409 |
| ERR_PROOF_NOT_APPROVED | 409 |
| ERR_PROMO_INVALID | 409 |
| ERR_PROMO_MIN_NOT_MET | 422 |
| ERR_COMPONENT_SHORTAGE | 409 |
| ERR_DEPOSIT_REQUIRED | 409 |
| ERR_BALANCE_DUE | 409 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |
| ERR_SHIP_WEIGHT_REQUIRED | 422 |
| ERR_DUPLICATE_VALUE | 409 |
| ERR_VALIDATION | 422 |
