# Salon Professional Distribution API — Product Requirements Document

## 1. Introduction

This document specifies the platform behind a professional-only beauty distribution business — the operating model in which shampoos, color lines, aerosols, and backbar concentrates may be sold exclusively to licensed salons, never to the general public. The distributor's commercial reputation depends on three pillars: every purchasing account is backed by a verified professional license; professional-use (backbar) product stays out of the retail diversion channel; and pricing, promotion, and education-credit economics are applied with auditable precision.

The platform serves five operator populations. Field sales consultants open salon accounts and run visit routes. Salon buyers build and submit orders against their own account. Distribution administrators curate the catalog — brands, products, territory exclusivity windows, promotions — and approve orders. Compliance officers verify licenses, adjudicate diversion cases, and suspend or reinstate salons. Warehouse operators build and advance shipments under hazmat-aware shipping rules. A compliance-focused daily sweep keeps licenses, promotions, and education-credit accruals honest as time advances.

Because the same catalog is priced through tier discounts, backbar discounts, liquidation markdowns, promotional grants, and credit redemptions, and because account standing can change mid-flight (a license expires, a diversion case is substantiated), the system is built around explicit state machines, pinned calculation orders, and optimistic-concurrency guards on the writes most exposed to stale snapshots. Every rule below is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, presenting a role outside the declared set, or — for entity-backed roles — presenting an `X-User-ID` that does not resolve to an existing entity of the backing type, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The declared roles are exactly: `DistributionAdmin`, `ComplianceOfficer`, `SalesConsultant`, `SalonBuyer`, `WarehouseOperator`.

Identity semantics differ by role:

- When `X-User-Role` is `SalesConsultant`, `X-User-ID` is the `id` of the acting `SalesConsultant`; ownership checks on any resource that references a `SalesConsultant` compare the resource's consultant field to `X-User-ID` — a consultant manages only route plans and stops whose `sales_consultant_id` equals `X-User-ID`.
- When `X-User-Role` is `SalonBuyer`, `X-User-ID` is the `id` of the acting `SalonAccount`; the buyer acts only on its own salon's resources — any target whose `salon_account_id` does not equal `X-User-ID` is out of scope.
- When `X-User-Role` is `DistributionAdmin`, `ComplianceOfficer`, or `WarehouseOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `reviewed_by_user_id` on `ProfessionalLicense`, `adjudicated_by_user_id` on `DiversionCase`, or `filed_by_user_id` where a transition writes it) but does not compare it to any entity's `id`.

Ownership violations by entity-backed callers are rejected with `ERR_FORBIDDEN_RESOURCE` (HTTP 403). One additional segregation-of-duties rule applies: the compliance officer who adjudicates a diversion case must not be the user who filed it — a matching pair is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Results are sorted by `created_at` ascending. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Daily Compliance Sweep

All time-sensitive evaluation — license validity, promotion windows, liquidation ladders, trailing-volume windows, credit expiry — reads a single logical clock, never wall-clock time. At server startup, before any operator action, the logical clock reads exactly 2026-08-01T00:00:00Z. A distribution-administrator-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the response echoes the clock as `current_utc`. Advancing the clock is inert on its own: no license expires, no promotion ends, and no credit lapses merely because time moved.

Time-dependent transitions fire inside an explicit ops-run checkpoint, invoked by a `DistributionAdmin` as the daily sweep. One sweep performs three jobs: every `VERIFIED` license whose `valid_until` now lies before the logical clock moves to `EXPIRED` (and if that was the salon's last still-valid verified license while the salon is `ACTIVE`, the salon is suspended with reason `LICENSE_EXPIRED` and the full suspension cascade of §3.3 fires); every promotion in `ACTIVE` or `PAUSED` whose `ends_at` now lies before the logical clock moves to `ENDED`; and every accrual credit entry whose `expires_at` now lies before the logical clock and which still has residual points posts an `EXPIRY` entry of the negative residual — that is, the entry's `points` minus its `consumed_points` — with `consumed_points` then set equal to `points`. The sweep reports `expired_license_count`, `suspended_salon_count`, `expired_credit_points`, and `ended_promotion_count`.

### 2.5. Common Resource Properties and Mutation Semantics

Every persisted entity carries an `id` — a server-minted UUID with no type prefix — plus `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, and an integer `version` that increments by 1 on every mutation of that entity. One entity is exempt: `EducationCreditEntry` is an append-only ledger row and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it. When an operation cascades into another entity (a suspension touching orders, a hold-freeing dismissal, a tier override), the cascaded entity's own `version` increments and its `updated_at` refreshes as part of the same operation.

### 2.6. Optimistic Concurrency Control

Three writes are guarded against stale snapshots. Each requires a non-optional input field carrying the caller's last-observed `version` of the named parent entity; if the parent's current `version` does not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412):

- A tier override on a salon must carry `expected_salon_account_version` matching the salon's current `version`. If the salon's version has advanced since the caller last read it — an evaluate-tier run, a suspension, a cascade — the override is based on stale state and is rejected with `ERR_STALE_VERSION` (HTTP 412).
- A promotion budget adjustment must carry `expected_promotion_version` matching the promotion's current `version`. Budget adjustments are otherwise always legal, so an advanced version means the caller's view of remaining budget is stale; the request is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Adding an item to a draft order must carry `expected_order_version` matching the order's current `version`. If the version has advanced — another item add, a credit or promotion redemption — the stale add is rejected with `ERR_STALE_VERSION` (HTTP 412), so pricing never applies to a snapshot the caller did not see.

Endpoints not listed here take no version field.

### 2.7. Money, Points, and Rounding Conventions

All monetary amounts are integer cents. Unless a rule states otherwise, rounding is round-half-up at each pinned rounding step. The credit ledger is denominated in integer points: each point is worth exactly 100 cents, points accrue by floor division, and the ledger balance of a salon is the signed sum of `points` over all its ledger entries. The diversion risk score is the single exception to integer precision: it is expressed with one decimal place, round-half-up.

### 2.8. Request Validation and Error Ordering

Every request passes a fixed pipeline of checks, evaluated in this order; the first failure wins and later failures are masked:

1. **Authentication context** — headers present, role declared, entity-backed id resolvable (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Body schema** — required fields present, types valid, enum values inside their declared sets, integer fields strictly positive where declared, window fields strictly increasing (start before end). Schema failures yield `ERR_INVALID_REQUEST`; window-ordering failures yield `ERR_INVALID_TIME_WINDOW`.
3. **Role authorization** — caller's role appears in the endpoint's role list (`ERR_UNAUTHORIZED_ROLE`).
4. **Ownership and segregation of duties** — entity-backed callers stay inside their scope (`ERR_FORBIDDEN_RESOURCE`); diversion adjudicator differs from filer (`ERR_SEGREGATION_OF_DUTIES`).
5. **Existence** — path- and body-referenced resource ids exist, validated left-to-right along the path, yielding the resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404).
6. **State legality** — the target entity sits in a valid from-state for the requested transition, yielding the entity-specific invalid-state error (409).
7. **Endpoint-specific business rules** — account activity, hazmat/method pairing, diversion holds, shipment quantities, territory exclusivity, quotas, uniqueness, window overlap, buffers, license dates, promotion eligibility, credit caps, and license availability — each detailed in §3 beside the workflow it guards.

Nested paths are resolved left-to-right: the parent id is validated before the child id under it.

### 2.9. State and Category Enumerations

State fields use exact uppercase strings. Salon accounts move through `PENDING_VERIFICATION`, `ACTIVE`, `SUSPENDED`, `DEACTIVATED`, with tier one of `SILVER`, `GOLD`, `PLATINUM`, and a `suspension_reason` of `MANUAL`, `LICENSE_EXPIRED`, or `DIVERSION_STRIKES` while suspended. Licenses move through `SUBMITTED`, `VERIFIED`, `REJECTED`, `EXPIRED`, with `license_type` one of `COSMETOLOGY`, `ESTHETICIAN`, `BARBER`, `NAIL_TECH`, `SALON_BUSINESS`. Brands are `ACTIVE` or `DISCONTINUED`. Products have a `lifecycle_status` of `ACTIVE`, `DISCONTINUED`, `LIQUIDATION`, or `ARCHIVED`; a `variant_type` of `BACKBAR` (professional use, not for resale) or `RETAIL` (for resale to consumers); and a `hazmat_class` of `NONE`, `AEROSOL`, or `FLAMMABLE_LIQUID`. Consultants are `ACTIVE` or `INACTIVE` with a `commission_model` of `STRAIGHT` or `ACCELERATOR`. Route plans move `DRAFT` → `PUBLISHED` → `COMPLETED`; route stops occupy `SCHEDULED`, `COMPLETED`, `NO_SHOW`, or `CANCELLED`. Orders carry two parallel dimensions: a `fulfillment_status` of `DRAFT`, `SUBMITTED`, `APPROVED`, `FULFILLING`, `SHIPPED`, `DELIVERED`, `CANCELLED`, or `REJECTED`, and a `payment_status` of `UNPAID`, `AUTHORIZED`, `CAPTURED`, `VOIDED`, or `REFUNDED`. Shipments move `PLANNED` → `LABEL_CREATED` → `IN_TRANSIT` → `DELIVERED`, with `method` one of `GROUND` or `AIR`. Promotions move `DRAFT` → `ACTIVE` → `PAUSED` → `ENDED`, with `promo_type` `BUNDLE` or `SAMPLE`; redemptions are `APPLIED` or `REVERSED` with a `reversal_reason` of `ORDER_CANCELLED`, `ORDER_REJECTED`, or `ACCOUNT_SUSPENDED`. Credit ledger entries have an `entry_type` of `PROVISIONAL_ACCRUAL`, `FINAL_ACCRUAL`, `REDEMPTION`, `REVERSAL`, or `EXPIRY`. Diversion cases move `OPEN` → `UNDER_REVIEW` → `SUBSTANTIATED` or `DISMISSED`, with `severity` of `MINOR`, `MAJOR`, or `SEVERE`.

### 2.10. Consistency Model

All writes take effect immediately and atomically: a response that reports success reflects every side effect the operation carries — cascaded state changes, ledger postings, counter recomputations, version increments — with no eventual-consistency window.

## 3. Business Logic & Workflows

### 3.1. Salon Onboarding and Professional Licensing

A `SalesConsultant` opens a salon account by supplying the salon's `legal_name`, the two-letter `territory_code` it operates in, and optionally an `assigned_consultant_id` attributing the account to a consultant. The new account starts in `PENDING_VERIFICATION` with tier `SILVER` and all counters — `education_credit_points`, `diversion_strike_points`, `diversion_risk_score`, `trailing_12m_delivered_volume_cents` — at zero, and `tier_override_active` false.

The account cannot trade until a license clears. A license submission — filed by the consultant or by the salon's own `SalonBuyer` — carries `license_number`, the two-letter `issuing_state`, a `license_type`, and a `valid_until` instant. The `valid_until` must lie strictly after the logical clock at submission; otherwise the submission is rejected with `ERR_LICENSE_DATE_INVALID` (HTTP 400). A submitted license sits in `SUBMITTED`, with `reviewed_by_user_id` null.

A `ComplianceOfficer` then reviews. Rejecting a `SUBMITTED` license moves it to `REJECTED`; verifying it requires the license still be `SUBMITTED` (`ERR_INVALID_LICENSE_STATE` otherwise) and re-checks that `valid_until` is still after the logical clock (`ERR_LICENSE_DATE_INVALID` otherwise). Either review stamps `reviewed_by_user_id` with the caller's `X-User-ID`. Verification has a cascade: if the owning salon is still `PENDING_VERIFICATION` and the verified license's `valid_until` lies after the logical clock, the salon transitions to `ACTIVE` and its `version` increments by 1.

### 3.2. Catalog: Brands, Exclusivity Windows, and Product Lifecycle

A `DistributionAdmin` creates a brand with a `name` unique across brands (a duplicate is `ERR_DUPLICATE_CODE`, HTTP 409); the brand starts `ACTIVE` with `discontinued_at` null. Products are created under a brand — the request names the owning `brand_id` — with a `sku` unique across products, a display `name`, a `variant_type`, a `hazmat_class`, a `base_price_cents` strictly greater than zero, and a `weight_grams` strictly greater than zero. A new product starts with `lifecycle_status` `ACTIVE`, `discontinued_at` null, and `liquidation_started_at` null.

Territory exclusivity is the anti-diversion lever. Granting exclusivity on a brand creates a window with a `territory_code`, an inclusive `effective_from`, and an exclusive `effective_to` — a half-open window in which `effective_to` must be strictly after `effective_from` (`ERR_INVALID_TIME_WINDOW` otherwise). Two windows for the same brand and territory pair must not overlap: overlap exists precisely when the new window's `effective_from` falls before the existing window's `effective_to` and the existing window's `effective_from` falls before the new window's `effective_to`; mere adjacency — the new window starting exactly where the old one ends — is allowed. An overlapping grant is rejected with `ERR_TERRITORY_WINDOW_OVERLAP` (HTTP 409).

Product lifecycle transitions are driven by a `DistributionAdmin` supplying a `target_status`. From `ACTIVE`, a product may move to `DISCONTINUED`, stamping `discontinued_at` with the logical clock and pausing every `ACTIVE` promotion that references the product as its required, free, or sample product. From `DISCONTINUED`, a product may return to `ACTIVE` only while its owning brand is still `ACTIVE` — `discontinued_at` clears to null — or move to `LIQUIDATION`, which stamps `liquidation_started_at` with the logical clock exactly once: leaving and re-entering `LIQUIDATION` later does not reset that timestamp. From `LIQUIDATION`, a product may move back to `DISCONTINUED` or forward to terminal `ARCHIVED`. Any lifecycle transition attempted from a non-matching state is rejected with `ERR_INVALID_PRODUCT_STATE` (HTTP 409).

Discontinuing a whole brand stamps the brand's `discontinued_at`, moves every `ACTIVE` product of the brand to `DISCONTINUED` — which in turn pauses every referencing `ACTIVE` promotion — and a repeat discontinuation of an already `DISCONTINUED` brand is rejected with `ERR_INVALID_REQUEST`.

### 3.3. Salon Standing: Suspension, Reinstatement, Deactivation, and Tier Management

Suspension has three doors, all landing on the same cascade. A `ComplianceOfficer` may manually suspend an `ACTIVE` salon (reason `MANUAL`, submitted with a free-text `reason` on the request). The daily sweep suspends an `ACTIVE` salon whose last still-valid `VERIFIED` license has expired (reason `LICENSE_EXPIRED`). And a diversion substantiation that pushes the salon's `diversion_strike_points` to at least 3 suspends an `ACTIVE` salon (reason `DIVERSION_STRIKES`). Suspending a salon that is not `ACTIVE` is rejected with `ERR_INVALID_ACCOUNT_STATE`. In every case the `suspension_reason` is set, the salon's `version` increments, and the order-cancellation cascade fires: every order of the salon sitting in `SUBMITTED` or `APPROVED` is cancelled under the compensation rules of §3.6, while `DRAFT` carts survive intact — they simply cannot be submitted while the salon is suspended.

Reinstatement moves a `SUSPENDED` salon back to `ACTIVE` and clears `suspension_reason` to null, incrementing `version`. It is legal only from `SUSPENDED` (`ERR_INVALID_ACCOUNT_STATE` otherwise) and only while the salon holds at least one `VERIFIED` license whose `valid_until` still lies after the logical clock — otherwise `ERR_NO_VALID_LICENSE` (HTTP 409). Deactivation is permanent and one-way: from either `ACTIVE` or `SUSPENDED` the salon moves to terminal `DEACTIVATED`, the same order-cancellation cascade fires for `SUBMITTED` and `APPROVED` orders, `DRAFT` carts survive, and `version` increments.

Tier management is deliberately dual. An evaluate-tier run by a `DistributionAdmin` recomputes the salon's trailing delivered volume: the sum of `net_merch_cents` over the salon's `DELIVERED` orders whose `delivered_at` falls inside the trailing 365-day window, both endpoints inclusive, measured against the logical clock. The result is stored on `trailing_12m_delivered_volume_cents`. If `tier_override_active` is true, the tier is left untouched; otherwise the tier is derived from the volume — `PLATINUM` when the volume is at least 5000000 cents, else `GOLD` when it is at least 2000000 cents, else `SILVER` — with inclusive boundaries, so a volume of exactly 2000000 cents yields `GOLD`. Separately, a `DistributionAdmin` may pin a tier directly through a tier override, supplying the target `tier` and the OCC field `expected_salon_account_version` per §2.6; a successful override sets `tier` to the supplied value, sets `tier_override_active` to true, and increments the salon's `version` by 1. While `tier_override_active` holds, evaluate-tier must not change the tier.

### 3.4. Pricing Engine: Tier, Backbar, and Liquidation

Every order line is priced at the moment it is added, and the computed unit price is frozen onto the line as `unit_price_cents`; the human-readable pricing context is recorded alongside as `pricing_snapshot` (for example `GOLD+BACKBAR` or `LIQUIDATION_W1`). Two branches exist, selected by the product's `lifecycle_status` at add time.

Liquidation branch. When the product is in `LIQUIDATION`, the discount is a flat ladder off base price, and tier and backbar discounts do not apply at all. Elapsed whole days are measured from `liquidation_started_at` to the logical clock. Fewer than 14 days elapsed: 20 percent off. At least 14 but fewer than 28 days elapsed: 40 percent off. At least 28 days elapsed: 60 percent off. The unit price is the base price multiplied by one minus the ladder percentage, rounded half-up to integer cents. The steps are left-closed: at exactly 14 days elapsed the 40 percent step applies.

Normal branch. When the product is `ACTIVE`, two discounts compound with pinned nesting order. First the tier discount — 0 percent for `SILVER`, 10 percent for `GOLD`, 15 percent for `PLATINUM` — is applied to the base price and the result rounded half-up to integer cents. Then, if the line's `variant_type` is `BACKBAR`, the backbar discount of 20 percent is applied to the already-rounded tier-adjusted value and rounded half-up again. A `RETAIL` line takes only the tier discount. This nesting is pinned: the tier discount rounds first and the backbar discount applies to the rounded value.

Only `ACTIVE` and `LIQUIDATION` products may be added to orders; a line referencing a product in any other lifecycle state is rejected with `ERR_INVALID_PRODUCT_STATE`.

### 3.5. Order Assembly, Credit Redemption, and Promotion Redemption

A `SalonBuyer` opens an order for its own salon by supplying `salon_account_id` and an initial set of `items`, each naming a `product_id` and a strictly positive `quantity`. Order creation requires the salon to be `ACTIVE` — otherwise `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409) — and the territory-exclusivity rule is evaluated per initial line: for each line's brand, if any exclusivity window exists for that brand, the salon's `territory_code` must be covered by a window containing the logical clock under half-open semantics; failure is `ERR_BRAND_TERRITORY_RESTRICTED` (HTTP 422). The new order starts in fulfillment `DRAFT` with payment `UNPAID` and all totals at zero; each line is priced per §3.4 and totals are computed in the pinned order of §3.6.

While the order is `DRAFT`, the buyer may add further items — each add carries `product_id`, `quantity`, and the OCC field `expected_order_version` per §2.6, increments the order's `version` by 1, and re-triggers the territory check for the added line — or remove existing lines. Promotional lines injected by an applied redemption are not removable; attempting to remove one is rejected with `ERR_INVALID_ORDER_STATE`.

Credit redemption converts ledger points to an order discount. The buyer supplies `points`. Two checks are evaluated in a pinned order: first, the requested points must not exceed the salon's redeemable points — the sum over the salon's accrual entries of `points` minus `consumed_points`, counting only entries whose `expires_at` still lies after the logical clock — else `ERR_INSUFFICIENT_CREDIT_BALANCE` (HTTP 422); second, the requested cents (points times 100) must not exceed the cap, which is the floor of half the order's `merchandise_total_cents` — else `ERR_CREDIT_REDEMPTION_EXCEEDS_CAP` (HTTP 422). The cap is inclusive: a request landing exactly at the cap is allowed. On success a `REDEMPTION` ledger entry is posted immediately, consuming non-expired accruals first-in-first-out and bumping each consumed accrual's `consumed_points`; `credit_applied_cents` equals the requested cents and `net_merch_cents` is recomputed. Because the balance check runs first, a request that fails both checks surfaces `ERR_INSUFFICIENT_CREDIT_BALANCE`.

Promotion redemption applies a promotional `code` to a draft order, in one shot, through a waterfall of gates evaluated in order:

1. **Window** — the logical clock must satisfy: at or after the promotion's `starts_at` and strictly before its `ends_at`; otherwise `ERR_PROMOTION_NOT_ACTIVE` (HTTP 409). Redeeming against a promotion in `DRAFT`, `PAUSED`, or `ENDED` state is rejected with `ERR_INVALID_PROMOTION_STATE` (HTTP 409), and an unknown code is `ERR_PROMOTION_NOT_FOUND` (404).
2. **Tier eligibility** — the salon's tier must appear in the promotion's `eligible_tiers`, else `ERR_PROMOTION_TIER_INELIGIBLE` (HTTP 422).
3. **Uniqueness on the order** — the same promotion must not already have an `APPLIED` redemption on this order, else `ERR_PROMOTION_ALREADY_APPLIED` (HTTP 409).
4. **Bundle requirement** — for a `BUNDLE` promotion only, the order must contain at least `required_qty` non-promotional units of `required_product_id`, else `ERR_BUNDLE_REQUIREMENT_NOT_MET` (HTTP 422).
5. **Budget bucket** — the redemption consumes `free_qty` units for a `BUNDLE` or `sample_units_per_redemption` units for a `SAMPLE`; if the promotion's `remaining_budget_units` is smaller than that consumption, the redemption is rejected with `ERR_PROMOTION_BUDGET_EXHAUSTED` (HTTP 422) — there are no partial grants.
6. **Per-salon bucket** — the salon's units already consumed on this promotion (the sum of `units_consumed` over `APPLIED` redemptions of the promotion by this salon) plus this redemption's units must not exceed `per_salon_cap`, else `ERR_PER_SALON_CAP_EXCEEDED` (HTTP 422).

On success the grant is materialized: a zero-priced promotional `OrderItem` is injected — `free_product_id` times `free_qty` for a bundle, `sample_product_id` times `sample_units_per_redemption` for a sample — with `is_promotional` true and `unit_price_cents` zero; a `PromotionRedemption` is created in `APPLIED`, recording the `promotion_id`, the order's `order_id`, the redeeming salon's `salon_account_id`, and `units_consumed` set to the consumed units; `remaining_budget_units` is decremented by the same amount; the order's `promo_applied_code` records the code; and the order's `version` increments. If the decrement drives `remaining_budget_units` to exactly zero, the promotion moves from `ACTIVE` to `ENDED` at once.

### 3.6. Order Totals, Submission, and the Payment Ledger

Order totals follow a pinned evaluation order — order matters, and the pinned order is normative. First, each line's `unit_price_cents` comes from the pricing engine already rounded. Second, each line's `line_total_cents` is the unit price multiplied by the quantity as an exact integer; the alternative ordering (multiplying base by quantity before discounting and rounding once) yields different cents and is wrong. Third, `merchandise_total_cents` is the sum of `line_total_cents` over all items, with promotional lines contributing zero. Fourth, `credit_applied_cents` comes from the credit-redemption rule of §3.5. Fifth, `net_merch_cents` is `merchandise_total_cents` minus `credit_applied_cents`. Sixth, `shipping_total_cents` is the sum of `shipping_charge_cents` over the order's shipments that have not been voided back to `PLANNED`. Seventh, `grand_total_cents` is `net_merch_cents` plus `shipping_total_cents`. These totals recompute on any line add or remove, on credit or promotion redemption, and on shipment creation or label voiding.

Submitting a draft order runs a battery of checks. The order must be `DRAFT` and contain at least one non-promotional item (`ERR_INVALID_ORDER_STATE` otherwise). The salon must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`). The backbar quota must pass: over the trailing 90-day window ending at the logical clock, sum the non-promotional `BACKBAR` and `RETAIL` units on the salon's `DELIVERED` orders whose `delivered_at` falls in the window, add this order's non-promotional units of each variant, and require that the projected backbar units be at most twice the projected retail units — equality is allowed; a violation is `ERR_BACKBAR_QUOTA_EXCEEDED` (HTTP 422). Territory exclusivity is re-checked for every line's brand (`ERR_BRAND_TERRITORY_RESTRICTED`). The credit redemption is revalidated in its pinned order (`ERR_INSUFFICIENT_CREDIT_BALANCE` first, then `ERR_CREDIT_REDEMPTION_EXCEEDS_CAP`). On success, payment moves `UNPAID` → `AUTHORIZED`, `submitted_at` is stamped with the logical clock, a provisional education-credit accrual posts per §3.9, and the order's `version` increments by 1.

Approval, by a `DistributionAdmin`, requires the order to be `SUBMITTED` (`ERR_INVALID_ORDER_STATE`) and the salon still `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`); on success payment moves `AUTHORIZED` → `CAPTURED`. Rejection, also by a `DistributionAdmin` and carrying a free-text `reason`, requires `SUBMITTED`; on success payment moves `AUTHORIZED` → `VOIDED`, the order lands in `REJECTED`, and three compensations fire: any `APPLIED` promotion redemption on the order is reversed with reason `ORDER_REJECTED` and the promotion's `remaining_budget_units` is restored by the redemption's `units_consumed`; the `REDEMPTION` credit entry is reversed by a `REVERSAL` entry that unwinds `consumed_points` on the same accrual entries; and the provisional accrual is reversed by a `REVERSAL` entry.

Buyer cancellation is available while the order is `DRAFT` or `SUBMITTED` (`ERR_INVALID_ORDER_STATE` from any other state — in particular, a buyer cannot cancel an `APPROVED` order). Cancelling from `DRAFT` simply reverses any credit redemption (restoring points via a `REVERSAL` entry) and reverses any applied promotion redemption with reason `ORDER_CANCELLED`, restoring budget. Cancelling from `SUBMITTED` additionally voids the authorization — payment `AUTHORIZED` → `VOIDED` — and reverses the provisional accrual. System cancellation is the cascade arm: when the owning salon enters `SUSPENDED` or `DEACTIVATED`, orders in `SUBMITTED` are cancelled exactly as the buyer path from `SUBMITTED`, while orders in `APPROVED` are cancelled with payment moving `CAPTURED` → `REFUNDED`, the provisional accrual and any credit redemption reversed, and any applied promotion redemption reversed with reason `ACCOUNT_SUSPENDED` and budget restored. Whenever a redemption reverses, the promotion's `remaining_budget_units` grows back by `units_consumed` — but a promotion that has already ended stays `ENDED`.

### 3.7. Shipments, Hazmat, and Delivery

Once an order is `APPROVED` or already `FULFILLING`, a `WarehouseOperator` builds shipments. Each shipment declares a `method` — `GROUND` or `AIR` — and an `items` array of order-line and quantity pairs. Three guards apply at creation, in the validation pipeline's order. The hazmat rule: if any shipped item's product has a `hazmat_class` other than `NONE`, the shipment must use `GROUND`; pairing hazmat with `AIR` is rejected with `ERR_HAZMAT_AIR_FORBIDDEN` (HTTP 422). The diversion hold rule: if the order's salon has any diversion case in `OPEN` or `UNDER_REVIEW` with `hold_shipments` true, shipment creation is rejected with `ERR_SHIPMENT_HELD_DIVERSION` (HTTP 409). The quantity rule: every referenced line must belong to this order, and per-line shipped quantities across the order's non-voided shipments must not exceed the ordered quantity — `ERR_SHIPMENT_QUANTITY_EXCEEDS_ORDER` (HTTP 409).

Charges are computed per shipment. The hazmat grams of a shipment are the sum, over items whose product's `hazmat_class` is not `NONE`, of item quantity times the product's `weight_grams`. When that sum is zero, `hazmat_surcharge_cents` is 0 and `hazmat_declaration_required` is false; otherwise `hazmat_declaration_required` is true and `hazmat_surcharge_cents` is 2500 cents flat plus 2 cents per hazmat gram. The shipment's `shipping_charge_cents` is the method base — 1200 cents for `GROUND`, 3000 cents for `AIR` — plus the surcharge. Creating the first shipment for an order moves it `APPROVED` → `FULFILLING`; the order's `shipping_total_cents` and `grand_total_cents` recompute.

A shipment is born `PLANNED`. Creating its label moves it to `LABEL_CREATED`; voiding the label returns it to `PLANNED` and withdraws that shipment's `shipping_charge_cents` from the order's `shipping_total_cents`, recomputing `grand_total_cents`. Shipping a labelled shipment moves it to `IN_TRANSIT`; when every ordered unit is then covered by shipments in `IN_TRANSIT` or `DELIVERED`, the order moves `FULFILLING` → `SHIPPED`. Delivering an in-transit shipment moves it to terminal `DELIVERED`; when every shipment of the order is `DELIVERED` — including the single-shipment case, where the order moves directly from `FULFILLING` to `DELIVERED` — the order lands in `DELIVERED`, `delivered_at` is stamped with the logical clock, the final education-credit accrual posts per §3.9, and consultant commission is attributed per §3.10. Every shipment transition attempted from a non-matching status is rejected with `ERR_INVALID_SHIPMENT_STATE` (HTTP 409).

### 3.8. Promotions and Budget Administration

A `DistributionAdmin` authors a promotion with a unique `code` (duplicates yield `ERR_DUPLICATE_CODE`), a `promo_type`, a non-empty `eligible_tiers` subset of the tier enumeration, an inclusive `starts_at`, an exclusive `ends_at` strictly after `starts_at` (`ERR_INVALID_TIME_WINDOW` otherwise), a strictly positive `budget_units`, and a strictly positive `per_salon_cap`. Bundle-specific inputs are `required_product_id`, `required_qty`, `free_product_id`, and `free_qty`; sample-specific inputs are `sample_product_id` and `sample_units_per_redemption`. A new promotion sits in `DRAFT` with `remaining_budget_units` not yet initialized.

Activation requires `DRAFT` (`ERR_INVALID_PROMOTION_STATE` otherwise) and re-checks that `ends_at` still lies after the logical clock (`ERR_INVALID_TIME_WINDOW` otherwise); on success `remaining_budget_units` initializes to `budget_units`. An `ACTIVE` promotion may be paused — manually by an administrator, or automatically when a referenced product (required, free, or sample) becomes `DISCONTINUED`. Resuming a `PAUSED` promotion re-checks the window against the logical clock (`ERR_INVALID_TIME_WINDOW`) and requires every referenced product to be `ACTIVE` or `LIQUIDATION` (`ERR_INVALID_PRODUCT_STATE` otherwise). Promotions end three ways: a redemption that drives `remaining_budget_units` to zero ends an `ACTIVE` promotion immediately, and the daily sweep ends any `ACTIVE` or `PAUSED` promotion whose `ends_at` has passed. `ENDED` is terminal.

Budget administration after activation goes through signed adjustments: a `DistributionAdmin` supplies `delta_units` and the OCC field `expected_promotion_version` per §2.6. Both `budget_units` and `remaining_budget_units` shift by `delta_units`, the result must keep `remaining_budget_units` at zero or above (`ERR_INVALID_REQUEST` otherwise), and the promotion's `version` increments by 1.

### 3.9. The Education-Credit Ledger

The credit ledger is an append-only, signed-point log per salon. Each entry carries the salon's `salon_account_id`, an `order_id` (null on `EXPIRY` entries), an `entry_type`, signed `points` — positive for accruals and for reversals of redemptions, negative for redemptions, reversals of accruals, and expiries — a `consumed_points` counter on accrual entries only (starting at 0, bumped first-in-first-out as redemptions and expiries consume the entry), an `earned_at` instant taken from the logical clock, and — on accrual entries only — an `expires_at` exactly 12 calendar months after `earned_at` (null on non-accrual entries). The salon's `education_credit_points` is always the signed sum of `points` across all its entries, and every posting bumps that balance by its signed amount. The salon-facing ledger view lists entries chronologically by `earned_at`, then by `created_at`, and may be filtered by `entry_type`; a parallel view lists the credit entries tied to a single order.

Accrual is dual-posted, provisional then final. At order submit, a `PROVISIONAL_ACCRUAL` entry posts: the point value is the floor of `net_merch_cents` divided by 1000, multiplied by the tier multiplier — 1 for `SILVER`, 2 for `GOLD`, 3 for `PLATINUM` — using the salon's tier at submit time. At delivery, a `FINAL_ACCRUAL` entry posts as a signed delta: the final points are recomputed chronologically over the delivered non-promotional lines' `line_total_cents` minus `credit_applied_cents`, floored by the same 1000-cent divisor and multiplied by the tier multiplier at the salon's tier at delivery time, and the posted delta is the final points minus the provisional points — the delta may be negative. Note that the accrual base is `net_merch_cents`, the after-credit figure, not the gross merchandise total.

Redemptions and expiries consume accruals first-in-first-out: a `REDEMPTION` posts negative points at redeem time as described in §3.5; reversals post `REVERSAL` entries that restore `consumed_points` on the same accrual rows; and the daily sweep posts `EXPIRY` entries for accruals whose 12-month life has lapsed with residual points, per §2.4.

### 3.10. Consultants, Commissions, and Route Operations

A `DistributionAdmin` creates a consultant with a `full_name`, a non-empty array of two-letter `territory_codes` the consultant covers, and a `commission_model`. The consultant starts `ACTIVE` with `commission_accrued_cents` at zero and `commission_month_volume_cents` at zero; `commission_month` stays null until the first attribution. An administrator may later patch the consultant's `status` between `ACTIVE` and `INACTIVE`.

Commission is attributed when an order reaches `DELIVERED`, to the salon's `assigned_consultant_id`; attribution is skipped when that field is null or the consultant is `INACTIVE`. The base is the delivered order's `net_merch_cents`. Under the `STRAIGHT` variant, the commission is 5 percent of the base, rounded half-up to integer cents. Under the `ACCELERATOR` variant, commission accrues on monthly marginal tiers evaluated chronologically within the calendar month of the logical clock: the consultant's `commission_month` and `commission_month_volume_cents` reset whenever the delivery month differs from the stored `commission_month`. Let the consultant's month-to-date delivered volume before this order be the running volume; the portion of the order's base falling below 1000000 cents of cumulative volume earns 4 percent, the portion from 1000000 up to 3000000 cents earns 6 percent, and the portion at or beyond 3000000 cents earns 8 percent — the order's base can straddle a boundary, in which case each slice earns its own rate. The commission is rounded half-up to integer cents, added to `commission_accrued_cents`, and the order's base is added to `commission_month_volume_cents`.

Route plans organize field visits. A plan is created in `DRAFT` naming its `sales_consultant_id` and a `name`. Stops are added to a `DRAFT` plan with a `salon_account_id`, a `start_at`, and an `end_at` strictly after `start_at` (`ERR_INVALID_TIME_WINDOW` otherwise). Each stop records the plan's `route_plan_id` it belongs to. Two constraints guard stop creation, in pipeline order: adjacent non-`CANCELLED` stops on the same plan, sorted by `start_at`, must keep at least a 30-minute gap between one stop's `end_at` and the next stop's `start_at` — a violation is `ERR_ROUTE_STOP_BUFFER_VIOLATION` (HTTP 409), checked for the new stop against all siblings; and the stop's salon territory must appear in the plan consultant's `territory_codes` — a violation is `ERR_CONSULTANT_TERRITORY_MISMATCH` (HTTP 422). A new stop starts `SCHEDULED` with `visited_at` null.

Publishing requires the plan to be `DRAFT`, to hold at least one `SCHEDULED` stop, and to belong to an `ACTIVE` consultant — violations surface as `ERR_INVALID_ROUTE_PLAN_STATE` or, for the consultant condition, `ERR_INVALID_CONSULTANT_STATE` (HTTP 409). Unpublishing returns a `PUBLISHED` plan to `DRAFT` only while no stop of the plan is `COMPLETED` (`ERR_INVALID_ROUTE_PLAN_STATE` otherwise). On a published plan, a stop can be completed — stamping `visited_at` with the logical clock — marked `NO_SHOW`, rescheduled from `NO_SHOW` back to `SCHEDULED` with a replacement `start_at`/`end_at` window that re-passes the 30-minute buffer rule against all non-`CANCELLED` siblings, or cancelled from either `SCHEDULED` or `NO_SHOW`. Stop actions require the stop to be in the matching from-state (`ERR_INVALID_ROUTE_STOP_STATE`) and the owning plan to be `PUBLISHED` (`ERR_INVALID_ROUTE_PLAN_STATE` — stop actions on a `DRAFT` plan are rejected). Completing or cancelling a stop bubbles up: when every stop of the plan is terminal and at least one is `COMPLETED`, the plan moves `PUBLISHED` → `COMPLETED`. Consultants manage only their own plans; `DistributionAdmin` shares the same operations across all plans.

### 3.11. Diversion Cases and Compliance Adjudication

A diversion case reports product leaking into unauthorized channels. It is filed by a `SalesConsultant` or a `ComplianceOfficer`, naming the `salon_account_id`, the diverted `product_id`, a `severity` — `MINOR` worth 1 strike point, `MAJOR` worth 2, `SEVERE` worth 3 — a free-text `evidence_note`, and an optional `hold_shipments` flag defaulting to false. The case opens in `OPEN`; the system records `filed_by_user_id` from the caller's `X-User-ID` and, when the filer is a consultant, `filed_by_consultant_id` (null otherwise). `adjudicated_by_user_id` and `strike_points_awarded` start null and zero respectively. While any case for a salon sits in `OPEN` or `UNDER_REVIEW` with `hold_shipments` true, shipment creation for that salon's orders is blocked per §3.7.

A `ComplianceOfficer` drives adjudication. Starting review moves `OPEN` → `UNDER_REVIEW`; requesting more evidence returns `UNDER_REVIEW` → `OPEN` — the evidence cycle can repeat. Both require the matching from-state (`ERR_INVALID_DIVERSION_CASE_STATE`). Substantiation requires `UNDER_REVIEW` and a segregation-of-duties check: the caller's `X-User-ID` must differ from the case's `filed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). On substantiation the case lands in `SUBSTANTIATED`, `adjudicated_by_user_id` is stamped, `strike_points_awarded` is set to the severity points, and the salon's `diversion_strike_points` grows by that award while its `diversion_risk_score` is recomputed: the score is the sum, over the salon's `SUBSTANTIATED` cases only — `OPEN`, `UNDER_REVIEW`, and `DISMISSED` rows are excluded — of each case's severity points times a decay factor evaluated against the logical clock: full weight when the substantiation (dated by the case's `updated_at` at the substantiating transition) lies less than 12 months back, half weight between 12 and 24 months, and zero beyond 24 months; the total is capped at 100 and expressed with one decimal place, round-half-up. When the award pushes `diversion_strike_points` to at least 3 and the salon is `ACTIVE`, the salon is suspended with reason `DIVERSION_STRIKES` and the full suspension cascade of §3.3 fires. Dismissal is available from either `OPEN` or `UNDER_REVIEW`, carries the same segregation-of-duties check, stamps `adjudicated_by_user_id`, and ends the `hold_shipments` effect. Both `SUBSTANTIATED` and `DISMISSED` are terminal — transitions attempted from them are rejected with `ERR_INVALID_DIVERSION_CASE_STATE`.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Requests that create a new resource return 201; modifications and action endpoints return 200; item removal returns 204 with no body; errors return the 4xx status named beside each rule in §2 and §3 and catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Set the logical clock (startup default 2026-08-01T00:00:00Z) | DistributionAdmin |
| POST | /api/ops/run-daily-sweep | Daily sweep: expire licenses (with suspension cascade), end promotions, post credit expiries | DistributionAdmin |
| POST | /api/salon-accounts | Open a salon account (field sales onboarding) | SalesConsultant |
| GET | /api/salon-accounts | List salon accounts | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/salon-accounts/{id} | Get one salon account | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/salon-accounts/{id}/suspend | Manually suspend an ACTIVE salon | ComplianceOfficer |
| POST | /api/salon-accounts/{id}/reinstate | Reinstate a SUSPENDED salon | ComplianceOfficer |
| POST | /api/salon-accounts/{id}/deactivate | Permanently deactivate a salon | ComplianceOfficer |
| POST | /api/salon-accounts/{id}/tier-override | Manually pin a salon tier (OCC-guarded) | DistributionAdmin |
| POST | /api/salon-accounts/{id}/evaluate-tier | Recompute trailing-365-day volume and derive tier | DistributionAdmin |
| POST | /api/salon-accounts/{id}/licenses | Submit a professional license for a salon | SalesConsultant, SalonBuyer |
| GET | /api/salon-accounts/{id}/licenses | List licenses of a salon | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/licenses/{id} | Get one license | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/licenses/{id}/verify | Verify a SUBMITTED license; may activate the salon | ComplianceOfficer |
| POST | /api/licenses/{id}/reject | Reject a SUBMITTED license | ComplianceOfficer |
| POST | /api/brands | Create a brand | DistributionAdmin |
| GET | /api/brands | List brands | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/brands/{id} | Get one brand | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/brands/{id}/discontinue | Discontinue a brand; cascades to products and pauses referencing promotions | DistributionAdmin |
| POST | /api/brands/{id}/territory-exclusives | Grant an exclusive territory window for the brand | DistributionAdmin |
| GET | /api/brands/{id}/territory-exclusives | List exclusivity windows of a brand | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/products | Create a product SKU | DistributionAdmin |
| GET | /api/products | List products | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/products/{id} | Get one product | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/products/{id}/lifecycle | Transition product lifecycle (ACTIVE/DISCONTINUED/LIQUIDATION/ARCHIVED) | DistributionAdmin |
| POST | /api/sales-consultants | Create a sales consultant | DistributionAdmin |
| GET | /api/sales-consultants/{id} | Get one consultant | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| PATCH | /api/sales-consultants/{id} | Update consultant status (ACTIVE/INACTIVE) | DistributionAdmin |
| POST | /api/route-plans | Create a route plan in DRAFT | SalesConsultant, DistributionAdmin |
| GET | /api/route-plans | List route plans | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/route-plans/{id} | Get one route plan | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/route-plans/{id}/publish | Publish a DRAFT route plan | SalesConsultant, DistributionAdmin |
| POST | /api/route-plans/{id}/unpublish | Return a PUBLISHED plan with no completed stops to DRAFT | SalesConsultant, DistributionAdmin |
| POST | /api/route-plans/{id}/stops | Add a stop to a DRAFT route plan | SalesConsultant, DistributionAdmin |
| GET | /api/route-stops | List route stops (filtered) | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/route-stops/{id} | Get one route stop | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/route-stops/{id}/complete | Mark a stop visited | SalesConsultant, DistributionAdmin |
| POST | /api/route-stops/{id}/no-show | Mark a stop NO_SHOW | SalesConsultant, DistributionAdmin |
| POST | /api/route-stops/{id}/reschedule | Reschedule a NO_SHOW stop (buffer re-validated) | SalesConsultant, DistributionAdmin |
| POST | /api/route-stops/{id}/cancel | Cancel a SCHEDULED or NO_SHOW stop | SalesConsultant, DistributionAdmin |
| POST | /api/orders | Create a DRAFT order for a salon, with initial items | SalonBuyer |
| GET | /api/orders | List orders | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/orders/{id} | Get one order | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/orders/{id}/items | Add an item to a DRAFT order (OCC-guarded on Order version) | SalonBuyer |
| DELETE | /api/orders/{id}/items/{itemId} | Remove an item from a DRAFT order | SalonBuyer |
| GET | /api/order-items | List order items (filtered) | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/order-items/{id} | Get one order item | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/orders/{id}/redeem-credits | Apply education-credit points to a DRAFT order | SalonBuyer |
| POST | /api/orders/{id}/redeem-promotion | Redeem a promotion code on a DRAFT order | SalonBuyer |
| POST | /api/orders/{id}/submit | Submit a DRAFT order | SalonBuyer |
| POST | /api/orders/{id}/cancel | Buyer-cancellable while DRAFT or SUBMITTED | SalonBuyer |
| POST | /api/orders/{id}/approve | Approve a SUBMITTED order | DistributionAdmin |
| POST | /api/orders/{id}/reject | Reject a SUBMITTED order | DistributionAdmin |
| POST | /api/orders/{id}/shipments | Create a shipment for an APPROVED or FULFILLING order | WarehouseOperator |
| GET | /api/orders/{id}/shipments | List shipments of an order | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/shipments/{id} | Get one shipment | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/shipments/{id}/create-label | PLANNED to LABEL_CREATED | WarehouseOperator |
| POST | /api/shipments/{id}/ship | LABEL_CREATED to IN_TRANSIT | WarehouseOperator |
| POST | /api/shipments/{id}/deliver | IN_TRANSIT to DELIVERED | WarehouseOperator |
| POST | /api/shipments/{id}/void-label | LABEL_CREATED back to PLANNED; charge withdrawn from order totals | WarehouseOperator |
| POST | /api/promotions | Create a promotion in DRAFT | DistributionAdmin |
| GET | /api/promotions | List promotions | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| GET | /api/promotions/{id} | Get one promotion | DistributionAdmin, ComplianceOfficer, SalesConsultant, SalonBuyer, WarehouseOperator |
| POST | /api/promotions/{id}/activate | DRAFT to ACTIVE; initializes remaining budget | DistributionAdmin |
| POST | /api/promotions/{id}/pause | ACTIVE to PAUSED | DistributionAdmin |
| POST | /api/promotions/{id}/resume | PAUSED to ACTIVE (referenced products must be ACTIVE or LIQUIDATION) | DistributionAdmin |
| POST | /api/promotions/{id}/budget-adjustments | Adjust promotion budget by a signed delta (OCC-guarded) | DistributionAdmin |
| GET | /api/promotion-redemptions | List promotion redemptions (filtered) | DistributionAdmin, ComplianceOfficer, SalonBuyer |
| GET | /api/promotion-redemptions/{id} | Get one redemption | DistributionAdmin, ComplianceOfficer, SalonBuyer |
| POST | /api/diversion-cases | File a diversion case against a salon | SalesConsultant, ComplianceOfficer |
| GET | /api/diversion-cases | List diversion cases (filtered) | DistributionAdmin, ComplianceOfficer |
| GET | /api/diversion-cases/{id} | Get one diversion case | DistributionAdmin, ComplianceOfficer |
| POST | /api/diversion-cases/{id}/start-review | OPEN to UNDER_REVIEW | ComplianceOfficer |
| POST | /api/diversion-cases/{id}/request-evidence | UNDER_REVIEW back to OPEN (evidence cycle) | ComplianceOfficer |
| POST | /api/diversion-cases/{id}/substantiate | UNDER_REVIEW to SUBSTANTIATED; awards strike points; may suspend the salon | ComplianceOfficer |
| POST | /api/diversion-cases/{id}/dismiss | OPEN or UNDER_REVIEW to DISMISSED | ComplianceOfficer |
| GET | /api/salon-accounts/{id}/credit-ledger | List the salon's education-credit ledger (chronological) | DistributionAdmin, ComplianceOfficer, SalonBuyer |
| GET | /api/orders/{id}/credit-entries | List credit ledger entries tied to an order | DistributionAdmin, ComplianceOfficer, SalonBuyer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_TIME_WINDOW | 400 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_RESOURCE | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_SALON_ACCOUNT_NOT_FOUND | 404 |
| ERR_LICENSE_NOT_FOUND | 404 |
| ERR_BRAND_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_CONSULTANT_NOT_FOUND | 404 |
| ERR_ROUTE_PLAN_NOT_FOUND | 404 |
| ERR_ROUTE_STOP_NOT_FOUND | 404 |
| ERR_ORDER_NOT_FOUND | 404 |
| ERR_ORDER_ITEM_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_PROMOTION_NOT_FOUND | 404 |
| ERR_REDEMPTION_NOT_FOUND | 404 |
| ERR_DIVERSION_CASE_NOT_FOUND | 404 |
| ERR_INVALID_ACCOUNT_STATE | 409 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_NO_VALID_LICENSE | 409 |
| ERR_INVALID_LICENSE_STATE | 409 |
| ERR_LICENSE_DATE_INVALID | 400 |
| ERR_INVALID_PRODUCT_STATE | 409 |
| ERR_INVALID_ORDER_STATE | 409 |
| ERR_INVALID_SHIPMENT_STATE | 409 |
| ERR_INVALID_PROMOTION_STATE | 409 |
| ERR_INVALID_DIVERSION_CASE_STATE | 409 |
| ERR_INVALID_ROUTE_PLAN_STATE | 409 |
| ERR_INVALID_ROUTE_STOP_STATE | 409 |
| ERR_INVALID_CONSULTANT_STATE | 409 |
| ERR_HAZMAT_AIR_FORBIDDEN | 422 |
| ERR_SHIPMENT_HELD_DIVERSION | 409 |
| ERR_SHIPMENT_QUANTITY_EXCEEDS_ORDER | 409 |
| ERR_BRAND_TERRITORY_RESTRICTED | 422 |
| ERR_BACKBAR_QUOTA_EXCEEDED | 422 |
| ERR_DUPLICATE_CODE | 409 |
| ERR_TERRITORY_WINDOW_OVERLAP | 409 |
| ERR_ROUTE_STOP_BUFFER_VIOLATION | 409 |
| ERR_CONSULTANT_TERRITORY_MISMATCH | 422 |
| ERR_PROMOTION_NOT_ACTIVE | 409 |
| ERR_PROMOTION_TIER_INELIGIBLE | 422 |
| ERR_PROMOTION_ALREADY_APPLIED | 409 |
| ERR_BUNDLE_REQUIREMENT_NOT_MET | 422 |
| ERR_INSUFFICIENT_CREDIT_BALANCE | 422 |
| ERR_CREDIT_REDEMPTION_EXCEEDS_CAP | 422 |
| ERR_PROMOTION_BUDGET_EXHAUSTED | 422 |
| ERR_PER_SALON_CAP_EXCEEDED | 422 |
| ERR_STALE_VERSION | 412 |
