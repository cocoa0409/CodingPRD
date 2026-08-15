# Manufactured Home Dealer API — Product Requirements Document

## 1. Introduction

A manufactured and modular home dealership runs one of the longest transaction pipelines in retail: a house is configured from a factory catalog, financed like a vehicle or like real estate depending on where it will sit, hauled down public highways in one to three sections under escort rules, set on a prepared foundation, titled, and then serviced under warranty for years afterward. This document specifies the API that backs that dealership — model inventory and factory ordering, land-lease community and lot coordination, site evaluation, financing origination and funding, transport and set-crew scheduling, titling, warranty service, and trade-in reconditioning — in the style of a Clayton Homes retail operation.

The pipeline is unforgiving about sequencing and about who is allowed to do what. A sales desk opens and prices the deal, but only a lender decides and funds the loan; an evaluator records site findings, but only an installation manager approves them and certifies set completion; a service manager who reviews a warranty claim may not be the one who resolves it. Deals routinely fall through mid-pipeline, and when they do the system must unwind cleanly — releasing the reserved home unit, releasing the lot, cancelling scheduled transport, restoring crew capacity, superseding evaluations and loan applications, and refunding the deposit — as one compensating cascade rather than a pile of manual cleanup.

Three engineering constraints shape every workflow in this document. First, all time-dependent rules (factory lead times, rate locks, warranty windows, schedule dates, trade-in depreciation) read a single logical clock that tests can drive deterministically. Second, because creating a site evaluation or a financing application legitimately supersedes the order's prior records, those two creation calls are guarded by optimistic concurrency on the order's version so a stale client cannot silently supersede a baseline it never saw. Third, the order itself carries two independent state dimensions — a deal pipeline and a payment pipeline — that evolve in parallel and only intersect at a few precisely defined moments.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the acting role. If either header is missing, or the role value is not one of the declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is declared but not authorized for the target endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system declares exactly nine roles, spelled as follows:

- `DealershipAdmin` — the dealership operator: catalog, communities and lots, unit inventory, factory completion, titles, order closure, and the logical clock.
- `SalesConsultant` — the sales desk: buyer registration, lot holds, order creation/confirmation/cancellation, option lines, evaluation scheduling, financing origination and submission, order-level delay communications, and trade-in intake.
- `Customer` — the buyer, acting only on resources anchored to their own orders.
- `SiteEvaluator` — field evaluator; records findings only on evaluations assigned to their `X-User-ID`.
- `InstallationManager` — installation authority: approves or rejects evaluations and certifies set completion.
- `TransportCoordinator` — the logistics desk: books, dispatches, delays, reschedules, delivers, and cancels transport jobs.
- `LenderAgent` — the lender-side decision maker; decides and funds applications but cannot originate them (segregation from `SalesConsultant`).
- `ServiceManager` — the warranty service desk; the reviewer and the resolver of a claim must be different users (segregation of duties).
- `Appraiser` — the trade-in appraiser; inspects, offers, and manages reconditioning, but cannot create the appraisal intake (segregation from `SalesConsultant`).

The `X-User-ID` header binds to resources differently per role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field to `X-User-ID` — concretely, warranty claim creation, warranty resubmission, and trade-in decision calls require the referenced order's `customer_id` to equal `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403). For every other role — `DealershipAdmin`, `SalesConsultant`, `SiteEvaluator`, `InstallationManager`, `TransportCoordinator`, `LenderAgent`, `ServiceManager`, and `Appraiser` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `evaluator_id` and `evaluated_by` on a `SiteEvaluation`, as `decided_by` on a `FinancingApplication`, or as `reviewed_by` and `resolved_by` on a `WarrantyClaim`) but does not compare it to any entity's `id`, with one exception: recording site findings is permitted only when `X-User-ID` equals the evaluation's assigned `evaluator_id`, enforced as an ownership check that fails with `ERR_UNAUTHORIZED` (HTTP 403).

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

### 2.3. Pagination and Result Filtering

Every list endpoint accepts two optional query parameters: `limit`, defaulting to 10, with a minimum of 1 and a maximum of 100; and `offset`, defaulting to 0. List responses are always sorted by `created_at` ascending, and the `meta` envelope of a list response carries `limit`, `offset`, `total_count`, and `has_more` alongside the request identifiers.

List endpoints additionally accept resource-specific filter parameters, each matched exactly against the same-named field: the model list accepts `status` and `floor_plan_type`; a community's lot list accepts `status`; the unit list accepts `model_id`, `lot_id`, `sales_order_id`, `unit_kind`, and `status`; the order list accepts `customer_id`, `home_unit_id`, `lot_id`, and `deal_status`; the transport job list accepts `home_unit_id`, `crew_id`, and `status`; the warranty claim list accepts `sales_order_id` and `status`; and the appraisal list accepts `supersedes_appraisal_id`, `model_id`, and `status`. Sub-resource list endpoints (an order's options, evaluations, applications, transport jobs, delay notices, appraisals; a unit's title records, warranty claims, and producing appraisals; a transport job's delay notices) accept only `limit` and `offset` and exist so every foreign key named in §3 is reverse-reachable.

### 2.4. The Logical Clock

All date and time reasoning in the system — factory lead times, rate-lock expiry, warranty coverage windows, scheduled dates, and trade-in depreciation years — reads a single logical clock, never the host wall clock. Before any explicit set call, the clock's startup default is exactly `2026-08-01T00:00:00Z`; it must not fall back to wall-clock time under any circumstance. A `DealershipAdmin` may advance or set the clock through a test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`. Date comparisons everywhere in this document — including the "current clock date" floor on scheduled dates — are evaluated against this clock.

### 2.5. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` minted by the server as a bare UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and a `version` integer. Timestamps are ISO 8601 UTC with three fractional digits. The `version` starts at 1 on creation and increments by exactly 1 on every mutation of that resource; any mutation also refreshes `updated_at`. One entity is exempt from this full envelope: a `DelayNotice` is an immutable communication record and carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

### 2.6. Money, Precision, and Rounding

All monetary values are integer cents, end to end; no floating-point currency ever appears in a request or response. Wherever a computed monetary value requires rounding — the per-line order discount, the documentary fee, the annuity loan payment, and the provisional trade-in credit — the rounding mode is round-half-up to whole cents. Transport quotes are sums of exact integer-cent terms and require no rounding. Transport width is compared exactly at one decimal place. Datetime comparisons (rate locks, warranty windows) are evaluated at second precision, and window ends are inclusive: an instant exactly equal to the window end is still inside coverage.

### 2.7. Optimistic Concurrency on Order-Scoped Writes

Two creation endpoints are guarded by optimistic concurrency control on the parent order: `POST /api/sales-orders/{id}/site-evaluations` and `POST /api/sales-orders/{id}/financing-applications`. Each requires a non-optional request field, `expected_sales_order_version`, carrying the `version` of the `SalesOrder` the client last observed. If that value does not match the order's current `version` — for example because another writer advanced the order since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because each of these creations legitimately supersedes the order's prior active records; a stale view would otherwise supersede a baseline the client never saw. No endpoint other than these two takes a version field of any kind.

### 2.8. Request Validation Pipeline and Priority Order

Incoming requests are validated against the following checks in the stated order; the first failing check determines the response. Layers 1–8 are cross-cutting gates that run before business rules; the business rules (layers 9–32) then apply in the order listed; field-shape validation runs last.

1. **Authentication** (all endpoints): `X-User-Role` and `X-User-ID` present and the role declared, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization** (all endpoints): the role is listed for the endpoint, else `ERR_UNAUTHORIZED` (HTTP 403).
3. **Ownership**: `Customer` callers may act only on resources whose order's `customer_id` equals `X-User-ID`, and a `SiteEvaluator` may record findings only when `X-User-ID` equals the evaluation's `evaluator_id`; breaches yield `ERR_UNAUTHORIZED` (HTTP 403). Applies to `POST /api/warranty-claims`, `POST /api/warranty-claims/{id}/resubmit`, `POST /api/trade-in-appraisals/{id}/decide`, and `POST /api/site-evaluations/{id}/record-findings`.
4. **Path existence** (all endpoints with path ids): path template ids resolve, validated left-to-right; the first missing resource yields that entity's not-found error (HTTP 404) — `ERR_HOME_MODEL_NOT_FOUND`, `ERR_COMMUNITY_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_HOME_UNIT_NOT_FOUND`, `ERR_SALES_ORDER_NOT_FOUND`, `ERR_ORDER_OPTION_NOT_FOUND`, `ERR_SITE_EVALUATION_NOT_FOUND`, `ERR_FINANCING_APPLICATION_NOT_FOUND`, `ERR_TRANSPORT_CREW_NOT_FOUND`, `ERR_TRANSPORT_JOB_NOT_FOUND`, `ERR_TITLE_RECORD_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`, or `ERR_TRADE_IN_APPRAISAL_NOT_FOUND`.
5. **Body foreign-key existence** (all create/action endpoints with body FKs): `customer_id`, `home_unit_id`, `lot_id`, `model_id`, `crew_id`, `sales_order_id`, and `supersedes_appraisal_id` must reference existing resources, else the referenced type's not-found error (HTTP 404).
6. **Optimistic concurrency**: `expected_sales_order_version` equals the order's current `version` — checked after existence and before state preconditions — else `ERR_STALE_VERSION` (HTTP 412). Applies to `POST /api/sales-orders/{id}/site-evaluations` and `POST /api/sales-orders/{id}/financing-applications`.
7. **State-machine precondition** (all action endpoints): the target resource is in a state from which the requested transition exists — this covers idempotent re-fires and terminal lockdown — else `ERR_INVALID_STATE` (HTTP 409).
8. **Cancellation guard** (`POST /api/sales-orders/{id}/cancel`): the order cannot be cancelled from `TITLED`, `CLOSED`, or `CANCELLED`, nor while its `payment_status` is `FINANCED`, else `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409).
9. **Escort compliance** (`POST /api/sales-orders/{id}/transport-jobs`): `escort_vehicle_count` must meet or exceed the required count for the model's width, else `ERR_ESCORT_REQUIRED` (HTTP 422).
10. **Set permit** (`POST /api/transport-jobs/{id}/complete-set`): the order's latest non-superseded evaluation must be `APPROVED` and carry a non-null `permit_number`, else `ERR_PERMIT_MISSING` (HTTP 422).
11. **Lot fit** (`POST /api/sales-orders`): the model's section count and length must fit the lot's maxima, else `ERR_LOT_DIMENSION_INSUFFICIENT` (HTTP 422).
12. **Lot availability** (`POST /api/sales-orders`, `POST /api/lots/{id}/reserve`): order creation requires a `RESERVED` lot; lot reservation requires an `AVAILABLE` lot, else `ERR_LOT_NOT_AVAILABLE` (HTTP 409).
13. **Unit availability** (`POST /api/sales-orders`): the unit must be `AT_DEALER` or `RETAIL_READY` and not held by another non-terminal order, else `ERR_HOME_UNIT_UNAVAILABLE` (HTTP 409).
14. **Crew capability** (`POST /api/sales-orders/{id}/transport-jobs`): a multi-section job requires a crew certified for multiwide sets, else `ERR_CREW_CAPABILITY_INSUFFICIENT` (HTTP 422).
15. **Crew window capacity** (`POST /api/sales-orders/{id}/transport-jobs`, `POST /api/transport-jobs/{id}/reschedule`): no date of the move window may exceed the crew's per-date section capacity, else `ERR_CREW_WINDOW_CONFLICT` (HTTP 409).
16. **Evaluator capacity** (`POST /api/sales-orders/{id}/site-evaluations`): the assigned evaluator may hold at most three open evaluations per calendar date, else `ERR_EVALUATOR_CAPACITY_EXCEEDED` (HTTP 409).
17. **Single open title record** (`POST /api/home-units/{id}/title-records`): the unit may have at most one record in `APPLIED` or `ISSUED`, else `ERR_TITLE_ALREADY_ACTIVE` (HTTP 409).
18. **Uniqueness**: `serial_number` on unit registration, `email` on customer registration, `model_code` among non-`DISCONTINUED` models, and `lot_number` within its community; violations yield `ERR_DUPLICATE_RESOURCE` (HTTP 409) on `POST /api/home-units`, `POST /api/customers`, `POST /api/home-models`, and `POST /api/communities/{id}/lots`.
19. **Segregation of duties** (`POST /api/warranty-claims/{id}/resolve`): the resolving user must differ from the claim's `reviewed_by`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
20. **Rate floor** (`POST /api/financing-applications/{id}/decide`): the offered APR must meet the financing type's floor, else `ERR_RATE_BELOW_FLOOR` (HTTP 422).
21. **Term cap** (`POST /api/sales-orders/{id}/financing-applications`, `POST /api/financing-applications/{id}/submit`): the term must not exceed the financing type's cap, else `ERR_TERM_EXCEEDS_CAP` (HTTP 422).
22. **No past scheduling** (`POST /api/sales-orders/{id}/site-evaluations`, `POST /api/sales-orders/{id}/transport-jobs`, `POST /api/transport-jobs/{id}/reschedule`): scheduled dates must not precede the current clock date, else `ERR_SCHEDULE_IN_PAST` (HTTP 422).
23. **Production lead time** (`POST /api/home-units/{id}/mark-ready`): a factory-order unit may be marked ready only after its model's lead time has elapsed, else `ERR_PRODUCTION_INCOMPLETE` (HTTP 409).
24. **Rate lock** (`POST /api/financing-applications/{id}/fund`): funding must occur no later than the rate-lock expiry, else `ERR_RATE_LOCK_EXPIRED` (HTTP 409) and the application transitions to `EXPIRED`.
25. **Warranty coverage** (`POST /api/warranty-claims`): the claim must fall inside its coverage window (inclusive end) and satisfy the transport-damage state gate, else `ERR_WARRANTY_EXPIRED` (HTTP 422).
26. **Delay notification** (`POST /api/transport-jobs/{id}/delay`): a delay longer than three whole days requires buyer notification, else `ERR_DELAY_NOTIFICATION_REQUIRED` (HTTP 422).
27. **Placement coherence** (`POST /api/sales-orders`): `COMMUNITY_LOT` placement requires a `lot_id`; `PRIVATE_LAND` forbids one, else `ERR_PLACEMENT_MISMATCH` (HTTP 422).
28. **Financing-type coherence** (`POST /api/sales-orders`, `POST /api/financing-applications/{id}/submit`, `POST /api/title-records/{id}/convert`): `REAL_PROPERTY` financing requires `PRIVATE_LAND` placement, an application's type must equal its order's type, and title conversion requires a real-property order, else `ERR_FINANCING_TYPE_INCOMPATIBLE` (HTTP 422).
29. **Unit–order coherence** (`POST /api/sales-orders/{id}/transport-jobs`): the job's `home_unit_id` must equal the order's unit, else `ERR_UNIT_ORDER_MISMATCH` (HTTP 422).
30. **Deposit sufficiency** (`POST /api/sales-orders/{id}/confirm`): the deposit must meet five percent of the total price, rounded half-up, else `ERR_DEPOSIT_INSUFFICIENT` (HTTP 422).
31. **Funding amount** (`POST /api/financing-applications/{id}/fund`): the funded amount must equal the application's requested amount, else `ERR_FUNDING_AMOUNT_MISMATCH` (HTTP 422).
32. **Claim approval cap** (`POST /api/warranty-claims/{id}/review`): the approved cost must not exceed the claim's estimated cost, else `ERR_CLAIM_AMOUNT_EXCESS` (HTTP 422).
33. **Field shape** (all endpoints): required fields present, enums in range, numeric ranges honored, and a delay notice carrying exactly one of its two subject references, else `ERR_VALIDATION` (HTTP 400).

### 2.9. The Two Dimensions of Order State

A `SalesOrder` carries two state fields that evolve independently on the same row. The `deal_status` pipeline runs `DRAFT` → `PENDING_SITE_EVAL` → `SITE_APPROVED` → `PENDING_FINANCING` → `FINANCING_APPROVED` → `AWAITING_DELIVERY` → `DELIVERED` → `SET_COMPLETE` → `TITLED` → `CLOSED`, with `CANCELLED` reachable from every pre-`TITLED` state and a reconfiguration loop from `SITE_APPROVED` back to `DRAFT`; `CLOSED` and `CANCELLED` are terminal. The `payment_status` dimension runs `UNPAID` → `DEPOSIT_PAID` → `FINANCED`, with `DEPOSIT_PAID` → `REFUNDED` as the cancellation compensation; `REFUNDED` is terminal. The two dimensions intersect at exactly three moments: confirmation moves payment from `UNPAID` to `DEPOSIT_PAID`, funding moves payment to `FINANCED` while the deal advances to `AWAITING_DELIVERY`, and cancellation refunds a paid deposit.

### 2.10. Cascades, Compensation, and Bubble-Up Consistency

Most lifecycle progress in this system is **bubble-up**: a child resource reaches a milestone state and the owning order advances in the same request — an approved evaluation lifts the order to `SITE_APPROVED`, an approved application lifts it to `FINANCING_APPROVED`, a funded application lifts it to `AWAITING_DELIVERY`, a delivered transport job lifts it to `DELIVERED`, and a completed set lifts it to `SET_COMPLETE` (and, for chattel deals whose title is already issued, straight on to `TITLED` in the same request). Conversely, order cancellation is a compensating cascade that unwinds every resource the deal has touched, detailed in §3.4. Every mutation — whether a direct action, a bubble-up, or a cascade hop — increments the mutated entity's `version` by 1 and refreshes its `updated_at`, so clients holding an order `version` always see superseding activity on it. URLs that nest one resource under another (for example, a lot under its community or an option under its order) resolve path identifiers strictly left-to-right, returning the not-found error of the first unresolvable segment before evaluating anything else.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Factory Models, Communities, and Lots

A `DealershipAdmin` registers each factory model with a dealer-facing `model_code`, a marketing `name`, a `floor_plan_type` of `SINGLE_WIDE`, `DOUBLE_WIDE`, `TRIPLE_WIDE`, or `MODULAR`, the `section_count` of transportable sections (1 for a single-wide, 2 for a double, 3 for a triple, and at least 1 for modular construction), the maximum transport `width_ft` and `length_ft` in feet, the `base_price_cents`, and the `factory_lead_time_days` that gate factory-order completion. A model is `ACTIVE` on creation; a `DISCONTINUED` model cannot be referenced when registering new home units, and `model_code` uniqueness is scoped to non-`DISCONTINUED` models so a retired code does not block reuse checks against live inventory. Width is not merely descriptive: it drives the escort thresholds of §3.6, and length drives lot fit below. The model catalog is browsable by every role, filtered by `status` or `floor_plan_type`.

Land-lease communities are registered with a `name`, a street `address`, and a monthly `lot_rent_cents`. A community is `ACTIVE` on creation and accepts lot reservations only while `ACTIVE`; a `CLOSED` community refuses them. Lots are added to a community with a `lot_number` unique within that community, a `max_sections` and `max_length_ft` describing the largest home the pad accepts, and a `utilities_ready` flag recording whether water, sewer, and electric stubs are present. Every lot carries a `community_id` anchoring it to its parent.

A lot's life is `AVAILABLE` → `RESERVED` → `LEASED`. A `SalesConsultant` reserves an `AVAILABLE` lot — attempting to reserve a lot that is not `AVAILABLE` fails with `ERR_LOT_NOT_AVAILABLE`, and reserving into a `CLOSED` community fails with `ERR_INVALID_STATE` — and may release a `RESERVED` lot back to `AVAILABLE` provided no non-terminal sales order references it (a lot pinned by a live order refuses release with `ERR_INVALID_STATE`). Both transitions bump the lot's `version`. Delivery onto the lot moves it `RESERVED` → `LEASED` automatically, and order cancellation moves it `RESERVED` → `AVAILABLE` as compensation.

When an order targets community placement, the home must physically fit the pad: the model's `section_count` must be at most the lot's `max_sections` and the model's `length_ft` at most the lot's `max_length_ft`, with equality allowed on both dimensions. A home that does not fit rejects the order with `ERR_LOT_DIMENSION_INSUFFICIENT`.

### 3.2. Buyers and Physical Inventory

A `SalesConsultant` registers each buyer with `full_name`, `email` (unique across all customers, enforced as `ERR_DUPLICATE_RESOURCE`), `phone`, and a dealer-assigned `credit_tier` of `TIER_A`, `TIER_B`, or `TIER_C`. A customer is `ACTIVE` on creation (the alternative being `INACTIVE`).

Physical units are registered by a `DealershipAdmin` against a model with a factory `serial_number` (the HUD label, unique across all units), a `unit_kind`, and a `condition_grade`. The `unit_kind` determines where the unit's life begins: `STOCK` units start `AT_DEALER`; `FACTORY_ORDER` units start `AT_FACTORY` and may not be sold until the factory finishes them; `TRADE_IN` units are never registered directly — the system creates them when a trade-in appraisal is accepted (§3.9), minting the `serial_number` itself. New stock and factory units carry `condition_grade` `NEW`; trade-ins carry `A`, `B`, or `C`.

Factory completion is an explicit act: a `DealershipAdmin` marks a `FACTORY_ORDER` unit ready, moving it `AT_FACTORY` → `AT_DEALER`, only once the logical clock has reached the unit's `created_at` plus its model's `factory_lead_time_days`; an early attempt is rejected with `ERR_PRODUCTION_INCOMPLETE`. The full physical lifecycle of a unit is `AT_FACTORY` → `AT_DEALER` → `RESERVED` → `IN_TRANSIT` → `ON_SITE` → `INSTALLED`, with a trade-in branch `AT_DEALER` → `RECONDITIONING` → `RETAIL_READY`, and `RETAIL_READY` → `RESERVED` resuming the retail cycle for a resold reconditioned unit. Along the way the unit accumulates system-maintained links and anchors: `sales_order_id` naming the order currently holding it, `lot_id` naming the community lot it was delivered onto (null for private-land or pre-delivery units), `delivered_at` anchoring the factory-defect warranty, and `set_completed_at` anchoring the installation-damage warranty. Units are listable by `model_id`, `lot_id`, `sales_order_id`, `unit_kind`, or `status`.

### 3.3. Composing the Deal: Orders, Options, and Pricing

A `SalesConsultant` opens a deal by naming the `customer_id`, the `home_unit_id` being purchased, a `placement_type` of `COMMUNITY_LOT` or `PRIVATE_LAND`, a `financing_type` of `CHATTEL` or `REAL_PROPERTY`, and the negotiated `agreed_home_price_cents` for the home itself before options, discount, and fees. Placement coherence is strict: `COMMUNITY_LOT` requires a `lot_id` naming an already-`RESERVED` lot (otherwise `ERR_PLACEMENT_MISMATCH` or `ERR_LOT_NOT_AVAILABLE`), `PRIVATE_LAND` forbids a `lot_id` entirely, and `REAL_PROPERTY` financing — a mortgage — is incompatible with leased community land, so a `REAL_PROPERTY` order with `COMMUNITY_LOT` placement is rejected with `ERR_FINANCING_TYPE_INCOMPATIBLE`. The unit must be `AT_DEALER` or `RETAIL_READY` and not referenced by any other order whose `deal_status` is neither `CLOSED` nor `CANCELLED`, or creation fails with `ERR_HOME_UNIT_UNAVAILABLE`. On success the order is born `DRAFT` with `payment_status` `UNPAID`, and the unit flips to `RESERVED` with its `sales_order_id` pointing at the new order.

Factory options are added to a `DRAFT` order as `OrderOption` lines carrying an `option_code`, a `description`, a `unit_price_cents`, and a `quantity` of at least 1; each line's `line_total_cents` is exactly the unit price multiplied by the quantity. A line is `ACTIVE` on creation and may be voided (`ACTIVE` → `VOIDED`) only while the owning order is still `DRAFT` — voiding against a confirmed order fails with `ERR_INVALID_STATE`. Every option add and every void recomputes the order's pricing fields and increments the order's `version`.

Pricing runs in a pinned order. First, line pricing: the order's lines are the home line (`agreed_home_price_cents`) plus every `ACTIVE` option's `line_total_cents`; `VOIDED` lines are excluded. The **subtotal** is the sum of all line totals, and `options_total_cents` is the sum over the active option lines only. The volume tier is selected by the subtotal: a subtotal of at least $100,000.00 (10,000,000 cents) earns a 3% tier rate; a subtotal of at least $50,000.00 (5,000,000 cents) but under $100,000.00 earns 1.5%; anything less earns no discount. The `discount_cents` is computed **per line** — each line total is multiplied by the tier rate and rounded half-up to whole cents, and those per-line amounts are summed. Computing the discount on the whole subtotal in one shot is a forbidden variant: it diverges by cents and must not be used. Second, the documentary fee: `doc_fee_cents` is one percent of the discounted subtotal — that is, subtotal minus `discount_cents`, not the final total — rounded half-up to whole cents, then clamped to no less than $250.00 (25,000 cents) and no more than $750.00 (75,000 cents). This base is pinned deliberately: the fee is conventionally described as "one percent of the amount financed," which would be circular, since the financed amount depends on the total and the total includes the fee. Third, `total_price_cents` is the subtotal minus `discount_cents` plus `doc_fee_cents`; it excludes any transport charge. Finally, `amount_financed_cents` is the total minus `deposit_cents` minus `trade_in_credit_cents`, floored at zero, and is recomputed on every pricing or trade-in mutation. Two more money fields complete the order's picture: `transport_charge_cents` holds the quoted cost of the order's latest non-`CANCELLED` transport job (0 before any booking), and `delay_compensation_cents` accumulates buyer compensation over the order's delay notices (§3.6). Until confirmation the order's `deposit_cents` is 0, and `trade_in_credit_cents` is 0 while the order has no accepted trade-in appraisal.

### 3.4. Confirming the Deal, Evaluating the Site, and Cancelling Cleanly

Confirmation is the deal's first commitment point. A `SalesConsultant` confirms a `DRAFT` order by supplying `deposit_cents`, which must be at least five percent of `total_price_cents` rounded half-up to whole cents — a shortfall is rejected with `ERR_DEPOSIT_INSUFFICIENT`. Confirmation records the deposit, moves `deal_status` from `DRAFT` to `PENDING_SITE_EVAL`, moves `payment_status` from `UNPAID` to `DEPOSIT_PAID`, and increments the order's `version`. The confirmation gate inspects `deal_status` only: any order in `DRAFT` may be confirmed whatever its `payment_status`. In particular, the reconfiguration loop below returns an order to `DRAFT` with `payment_status` still `DEPOSIT_PAID`, and such an order can be confirmed again — the newly supplied `deposit_cents` replaces the previously recorded deposit.

Site evaluation is then scheduled against the order. Scheduling requires the OCC guard of §2.7 — the request must carry `expected_sales_order_version` matching the order's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) — and names a `scheduled_date` that must not precede the current clock date (`ERR_SCHEDULE_IN_PAST`) and the `evaluator_id` of the assigned `SiteEvaluator`. One evaluator may hold at most three open evaluations (status `SCHEDULED` or `FINDINGS_RECORDED`) on the same calendar date; scheduling a fourth fails with `ERR_EVALUATOR_CAPACITY_EXCEEDED`. Creating a new evaluation for an order supersedes the order's prior evaluations still in `SCHEDULED` or `FINDINGS_RECORDED`, pushing them to `SUPERSEDED`, and increments the order's `version`.

The assigned evaluator — and only that evaluator, by `X-User-ID` matching `evaluator_id`, else `ERR_UNAUTHORIZED` — records findings while the order is `PENDING_SITE_EVAL` (else `ERR_INVALID_STATE`): a `foundation_type` of `SLAB`, `CRAWL_SPACE`, `PIERS`, or `BASEMENT`; whether `utilities_verified` is true; an optional `permit_number`; a `findings_result` of `PASS`, `CONDITIONAL`, or `FAIL`; and an `install_estimate_cents`. Recording moves the evaluation `SCHEDULED` → `FINDINGS_RECORDED` and stamps `evaluated_by` with the recorder's `X-User-ID`. Note that `permit_number` is optional at findings time but becomes mandatory before set completion (§3.6).

An `InstallationManager` then disposes of the recorded findings. Approval is permitted only when `findings_result` is `PASS` or `CONDITIONAL` — approving a `FAIL` evaluation is rejected with `ERR_INVALID_STATE` — and moves the evaluation to `APPROVED`; when that evaluation is the order's latest non-`SUPERSEDED` one, the order bubbles up from `PENDING_SITE_EVAL` to `SITE_APPROVED`. Rejection moves the evaluation to `REJECTED` and, when it is the order's latest non-`SUPERSEDED` one, drops the order back to `DRAFT` from either `PENDING_SITE_EVAL` or `SITE_APPROVED` — the reconfiguration loop that lets the sales desk re-spec the deal and evaluate again. Both bubble effects increment the order's `version`.

Cancellation is the mirror of confirmation. A `SalesConsultant` may cancel from `DRAFT`, `PENDING_SITE_EVAL`, `SITE_APPROVED`, `PENDING_FINANCING`, `FINANCING_APPROVED`, or `AWAITING_DELIVERY`, but never from `TITLED`, `CLOSED`, or `CANCELLED`, and never while `payment_status` is `FINANCED`; a forbidden cancel is rejected with `ERR_ORDER_NOT_CANCELLABLE`. An allowed cancel fires one compensating cascade in the same request: the held unit returns `RESERVED` → `AT_DEALER` with its `sales_order_id` cleared; a community-placement lot returns `RESERVED` → `AVAILABLE`; every transport job of the order still in `SCHEDULED` or `DELAYED` is cancelled, and each such cancellation restores the assigned crew's window capacity by recomputing `booked_dates` with the cancelled job's sections removed from every covered date; every evaluation in `SCHEDULED` or `FINDINGS_RECORDED` becomes `SUPERSEDED`; every financing application in `DRAFT`, `SUBMITTED`, `CONDITIONALLY_APPROVED`, or `APPROVED` becomes `SUPERSEDED`; and when a deposit was recorded, `payment_status` moves `DEPOSIT_PAID` → `REFUNDED`. The order itself lands in `CANCELLED` with its `version` incremented.

### 3.5. Financing the Home: Origination, Underwriting, Rate Lock, and Funding

Once the site is approved, a `SalesConsultant` originates a financing application against the order — again under the §2.7 OCC guard requiring `expected_sales_order_version` — naming the `financing_type` (which must equal the order's own `financing_type`), the `lender_name`, the requested `term_months`, and a `down_payment_cents` that must be at least the order's recorded `deposit_cents`. Term caps depend on type: at most 240 months for `CHATTEL`, at most 360 months for `REAL_PROPERTY`, with over-cap requests rejected as `ERR_TERM_EXCEEDS_CAP` both at creation and again at submission. The first application created for an order bubbles the order `SITE_APPROVED` → `PENDING_FINANCING`; each subsequent application for the same order supersedes the prior one still in `DRAFT`, `SUBMITTED`, `CONDITIONALLY_APPROVED`, or `APPROVED` (the prior becomes `SUPERSEDED`), leaves the order in `PENDING_FINANCING`, and increments the order's `version` again.

Submission is a `SalesConsultant` act that re-verifies coherence: `REAL_PROPERTY` applications require the order's placement to be `PRIVATE_LAND` (leased community land cannot be mortgaged), else `ERR_FINANCING_TYPE_INCOMPATIBLE`. On submission the application moves `DRAFT` → `SUBMITTED` and two computed fields are fixed: `requested_amount_cents` is set to the order's current `amount_financed_cents`, and `estimated_payment_cents` is the annuity payment on that amount at the type's rate floor. The annuity is computed as follows: the monthly rate is the APR in basis points divided by ten thousand and then by twelve; the payment is the requested amount multiplied by that monthly rate, divided by one minus the quantity (one plus the monthly rate) raised to the power of negative `term_months`, rounded half-up to whole cents. The rate floors are 700 basis points (7.00%) for `CHATTEL` and 450 basis points (4.50%) for `REAL_PROPERTY`, so the same principal and term always price a strictly lower estimated payment under real-property financing than under chattel.

Decisions belong to the `LenderAgent`, who calls with a `decision` and, for approvals, an `apr_bps`. Three outcomes exist from `SUBMITTED`. An `APPROVE` decision requires the offered `apr_bps` to meet the type's floor — 700 for chattel, 450 for real property — else `ERR_RATE_BELOW_FLOOR`; on approval the application moves to `APPROVED`, records the agreed `apr_bps`, computes `monthly_payment_cents` as the annuity at that approved rate, sets `rate_lock_expires_at` to exactly 14 days after the approval instant, stamps `decided_by` with the lender's `X-User-ID`, and bubbles the order `PENDING_FINANCING` → `FINANCING_APPROVED`. A `CONDITIONAL` decision (same floor check) moves the application to `CONDITIONALLY_APPROVED`, stamps `decided_by`, and freezes `requested_amount_cents` — from that point the trade-in cascade of §3.9 no longer recomputes it. A conditionally approved application accepts a second decide with `decision` `APPROVE`, which computes `monthly_payment_cents`, sets the 14-day rate lock, and bubbles the order to `FINANCING_APPROVED`. A `DENY` decision moves the application to `DENIED` and stamps `decided_by`.

Funding is the point of no return, gated four ways. The attempt must land no later than `rate_lock_expires_at` — a funding attempted after the lock lapses is rejected with `ERR_RATE_LOCK_EXPIRED` and the application transitions to `EXPIRED` in the same breath. The `funded_amount_cents` must equal the application's `requested_amount_cents` exactly, else `ERR_FUNDING_AMOUNT_MISMATCH`. The order's unit must still be `RESERVED` with its `sales_order_id` naming this order, else `ERR_INVALID_STATE`. And the title gate: an `ISSUED` title record must exist for the unit whose `title_type` matches the financing type — `MANUFACTURED_CERTIFICATE` for `CHATTEL`, `REAL_PROPERTY_AFFIXED` for `REAL_PROPERTY` — else `ERR_INVALID_STATE`. A successful funding moves the application to `FUNDED`, bubbles the order `FINANCING_APPROVED` → `AWAITING_DELIVERY`, and moves `payment_status` to `FINANCED` — which, per §3.4, also locks the order against cancellation.

### 3.6. Moving the Home: Crews, Booking, Escorts, Delays, Delivery, and Set

Transport capacity lives in crews. A `DealershipAdmin` registers each `TransportCrew` with a `name`, a `crew_size` headcount of at least 1, a `can_set_multiwide` certification flag, and a `max_sections_per_window` — the crew's per-calendar-date section capacity. The crew's `booked_dates` is a computed, sorted list of calendar dates on which at least one non-terminal transport job consumes capacity.

Booking a transport job is a `TransportCoordinator` act against an order whose `deal_status` is exactly `FINANCING_APPROVED` — booking in any other deal state fails with `ERR_INVALID_STATE`. The booking names the `home_unit_id` (which must equal the order's own unit, else `ERR_UNIT_ORDER_MISMATCH`), the `crew_id`, an `origin` of `FACTORY` or `DEALER_LOT`, the one-way `distance_miles`, a `scheduled_start_date` that must not precede the current clock date (`ERR_SCHEDULE_IN_PAST`), and the `escort_vehicle_count` booked. At booking the job snapshots `sections_count` from the unit's model and computes whether `escort_required` is true. The escort rule is a hard boundary on the model's `width_ft`: under 14.0 feet requires no escort; at least 14.0 but under 16.0 requires one escort vehicle; 16.0 or more requires two — a width of exactly 14.0 feet therefore does require one escort. If the booked `escort_vehicle_count` falls short of the required count, booking fails with `ERR_ESCORT_REQUIRED`. A crew whose `can_set_multiwide` is false cannot take a job of two or more sections (`ERR_CREW_CAPABILITY_INSUFFICIENT`).

Crew capacity is enforced per calendar date across a half-open move window: the job occupies every date from `scheduled_start_date` up to but not including `scheduled_start_date` plus `sections_count` days. For each date in that window, the crew's load is the sum of `sections_count` over its other active jobs — statuses `SCHEDULED`, `DELAYED`, and `EN_ROUTE` consume capacity — covering that date; if any date's load plus the new job's sections exceeds `max_sections_per_window`, booking fails with `ERR_CREW_WINDOW_CONFLICT`. Because the window is half-open, adjacency is allowed: a job ending on a date and another starting that same date do not overlap.

The quote is computed at booking into `quoted_cost_cents` and copied onto the order's `transport_charge_cents`, always in exact integer cents: the base haul is `sections_count` times `distance_miles` times $2.50 per mile per section (250 cents); the escort term is `escort_vehicle_count` times `distance_miles` times $1.50 per mile (150 cents), charged only when `escort_required` is true; a multiwide flat of $1,500.00 (150,000 cents) applies when the job has two or more sections; mileage beyond the first 100 free miles is charged at $0.90 per mile (90 cents); and a weekend flat of $500.00 (50,000 cents) applies when the `scheduled_start_date` falls on a Saturday or Sunday. The quote is the sum of those five terms.

A booked job cycles `SCHEDULED` ↔ `DELAYED` any number of times before it runs. Declaring a delay requires a `new_scheduled_start_date` strictly after the current `scheduled_start_date` (otherwise `ERR_VALIDATION`), a `reason`, and a `buyer_notified` flag; when the slip exceeds three whole days, `buyer_notified` must be true or the declaration is rejected with `ERR_DELAY_NOTIFICATION_REQUIRED`. A delay moves the job `SCHEDULED` → `DELAYED`, writes the new start date onto the job, creates a `DelayNotice` pinned to the job (its `transport_job_id` set, its `sales_order_id` null, `original_date` taken from the prior start and `new_date` from the new start), stamps the job's `buyer_notified_at` when the buyer was notified, and recomputes the owning order's `delay_compensation_cents`. Rescheduling confirms the new window: the job moves `DELAYED` → `SCHEDULED` only if the `new_scheduled_start_date` is not in the past (`ERR_SCHEDULE_IN_PAST`) and the crew-window capacity check passes for the new window (`ERR_CREW_WINDOW_CONFLICT`).

Delay compensation is computed per notice. The `delay_days` of a notice is the whole number of days from `original_date` to `new_date` — the elapsed seconds divided by 86,400, rounded down. The first two days are a grace period: fewer than three days of delay earns nothing; from the third day the notice earns $75.00 per day (7,500 cents) for each day beyond the two grace days, capped at $750.00 (75,000 cents) per notice — so a five-day slip earns three days of per-diem, and a twelve-day slip hits the cap. The order's `delay_compensation_cents` is the sum of `compensation_cents` over every notice linked to the order — both notices pinned directly to the order and those pinned to its transport jobs. Order-level notices are created by a `SalesConsultant` with a `reason`, an `original_date`, a `new_date` (which must be after `original_date`), and a `buyer_notified` flag, and likewise recompute the order's compensation. Every notice, whichever way it is created, has a `reason` of `WEATHER`, `PERMIT_HOLD`, `FACTORY_DELAY`, `SITE_NOT_READY`, or `ESCORT_UNAVAILABLE`, and must carry exactly one of `transport_job_id` or `sales_order_id` — both or neither is rejected with `ERR_VALIDATION`.

Execution begins with dispatch: the coordinator starts the move, `SCHEDULED` → `EN_ROUTE`, only while the current clock date falls inside the move window (from the start date up to but not including start plus `sections_count` days), else `ERR_INVALID_STATE`; dispatch moves the unit `RESERVED` → `IN_TRANSIT`. Delivery moves the job `EN_ROUTE` → `DELIVERED` and, in the same request, moves the unit `IN_TRANSIT` → `ON_SITE` (stamping `delivered_at`, the factory-defect warranty anchor, and setting the unit's `lot_id` when the order's `placement_type` is `COMMUNITY_LOT`), moves a community-placement lot `RESERVED` → `LEASED`, and bubbles the order `AWAITING_DELIVERY` → `DELIVERED`. Set completion is certified by an `InstallationManager`, not the transport coordinator, and only when the order's latest non-`SUPERSEDED` evaluation is `APPROVED` and carries a non-null `permit_number` — otherwise `ERR_PERMIT_MISSING`. Completing the set moves the job `DELIVERED` → `SET_COMPLETE`, the unit `ON_SITE` → `INSTALLED` (stamping `set_completed_at`, the installation-damage warranty anchor), and the order `DELIVERED` → `SET_COMPLETE`. A job still in `SCHEDULED` or `DELAYED` may instead be cancelled outright — by the coordinator, or by the order-cancellation cascade — landing in `CANCELLED` with the crew's `booked_dates` recomputed so its sections stop consuming capacity.

### 3.7. Titling and Deal Closure

Every unit is titled through `TitleRecord` applications filed by a `DealershipAdmin`, naming a `title_type` of `MANUFACTURED_CERTIFICATE` (the chattel instrument) or `REAL_PROPERTY_AFFIXED` (the conversion target) and the two-letter `state_code` of the titling jurisdiction. A unit may carry at most one open title record — status `APPLIED` or `ISSUED` — at a time; a second application is rejected with `ERR_TITLE_ALREADY_ACTIVE`.

Issuance moves a record `APPLIED` → `ISSUED` and is allowed only while the unit is `AT_DEALER`, `RESERVED`, `ON_SITE`, or `INSTALLED` (else `ERR_INVALID_STATE`); on issuance, if the unit's order is `SET_COMPLETE` and financed as `CHATTEL`, the order bubbles immediately to `TITLED`. Conversion moves `ISSUED` → `CONVERTED`, rewrites the record's `title_type` to `REAL_PROPERTY_AFFIXED`, and is permitted only when the order's `financing_type` is `REAL_PROPERTY` (converting on a chattel deal fails with `ERR_FINANCING_TYPE_INCOMPATIBLE`) and the unit is `INSTALLED` (else `ERR_INVALID_STATE`); conversion likewise bubbles a `SET_COMPLETE` order to `TITLED`. Surrender moves `ISSUED` → `SURRENDERED` and exists for trade-in units only — surrendering a title on any other `unit_kind` fails with `ERR_INVALID_STATE`.

The order side of titling has a chained shortcut: when set completion lands the order in `SET_COMPLETE` and a qualifying `ISSUED` title record already exists for a `CHATTEL` deal, the order advances immediately to `TITLED` within the same request rather than waiting for a later title event. From `TITLED`, a `DealershipAdmin` closes the deal, moving `deal_status` to the terminal `CLOSED` and incrementing the order's `version`.

### 3.8. Warranty Service After the Sale

A warranty claim is filed against a `home_unit_id` and the `sales_order_id` that sold it — the order is the ownership anchor for `Customer` callers, whose `X-User-ID` must equal the order's `customer_id`, else `ERR_UNAUTHORIZED`. Claims may be filed by the buyer or by a `ServiceManager` on the buyer's behalf. The claim names a `claim_type` of `FACTORY_DEFECT`, `TRANSPORT_DAMAGE`, or `INSTALLATION_DAMAGE`, a free-text `description`, and the claimant's `estimated_cost_cents`.

Coverage is anchored per claim type, and the computed `coverage_window_end` is stored on the claim at creation. A `FACTORY_DEFECT` claim is covered from the unit's `delivered_at` through 365 days after it; an `INSTALLATION_DAMAGE` claim is covered from the unit's `set_completed_at` through 90 days after it — a late set date can therefore make an installation claim valid on dates when a factory claim would already be expired, and vice versa. Both windows are inclusive at the end: a claim filed exactly at the window's end instant is still in coverage, and anything later is rejected with `ERR_WARRANTY_EXPIRED`. `TRANSPORT_DAMAGE` claims carry no window at all — `coverage_window_end` stays null — and are instead state-gated: reportable only while the unit is `IN_TRANSIT` or `ON_SITE`. Delivery-anchored and install-anchored claims require the unit to be `ON_SITE` or `INSTALLED`.

Review is a `ServiceManager` decision with three outcomes. `APPROVE` requires the offered `approved_cost_cents` to be no greater than the claim's `estimated_cost_cents`, else `ERR_CLAIM_AMOUNT_EXCESS`; the approved amount and the reviewer's `X-User-ID` are recorded in `reviewed_by`. `DENY` moves the claim to `DENIED`, and `REQUEST_INFO` moves it to `INFO_REQUESTED`; both stamp `reviewed_by` as well. The claim is never stuck: a buyer may resubmit from `INFO_REQUESTED` — returning it to `UNDER_REVIEW` with the `description` replaced by the new text — and may likewise appeal from `DENIED` back into `UNDER_REVIEW` the same way, in each case only as the order's own customer (else `ERR_UNAUTHORIZED`). Resolution closes an `APPROVED` claim into `RESOLVED`, but segregation of duties forbids the resolver from being the reviewer: the resolving `X-User-ID` must differ from the claim's `reviewed_by`, else `ERR_SEGREGATION_OF_DUTIES`, and the resolver's id is stamped into `resolved_by`.

### 3.9. Trade-Ins: Appraisal, Acceptance, and Reconditioning

A buyer trading in a used home gets a `TradeInAppraisal` opened by a `SalesConsultant` against the order receiving the credit, naming the `model_id` of the traded home, the customer-declared `declared_model_year`, the customer-declared `declared_condition` of `A`, `B`, or `C`, and optionally a `supersedes_appraisal_id` for the counter-offer loop — the referenced appraisal must belong to the same order and be `OFFERED`, and opening the counter-appraisal pushes it to `SUPERSEDED`.

At creation the appraisal carries a `provisional_credit_cents` computed purely from the declarations and the logical clock. The depreciable age is the clock's current calendar year minus the declared model year minus a ten-year grace, floored at zero. The condition base is $18,000.00 for grade `A` (1,800,000 cents), $12,000.00 for `B` (1,200,000 cents), and $6,000.00 for `C` (600,000 cents); that base is depreciated by three percent per year of depreciable age, rounded half-up to whole cents, and the provisional credit is the greater of that depreciated figure and a $2,000.00 floor (200,000 cents). The provisional figure takes no notice of any inspected value.

An `Appraiser` then inspects the trade-in, recording `appraised_value_cents`, the `reconditioning_cost_cents` needed to bring it to retail-ready, and the confirmed `condition_grade`; inspection moves the appraisal `DRAFT` → `INSPECTED` and fixes the `final_credit_cents` as the appraised value minus the reconditioning cost, floored at zero — a figure that generally diverges from the provisional credit. Offering moves `INSPECTED` → `OFFERED`, locking the final credit as a formal offer to the buyer.

The buyer's decision is a `Customer` act, again ownership-checked against the order's `customer_id` (else `ERR_UNAUTHORIZED`), expressed as a `decision` of `ACCEPT` or `DECLINE`. Declining moves `OFFERED` → `DECLINED`. Accepting is blocked while the order has any financing application in `CONDITIONALLY_APPROVED`, `APPROVED`, or `FUNDED` (else `ERR_INVALID_STATE`) — credit terms already locked cannot absorb a new trade credit — and on acceptance a three-deep cascade fires in one request: first, a trade-in `HomeUnit` is created with `unit_kind` `TRADE_IN`, status `AT_DEALER`, its `model_id` and `condition_grade` taken from the appraisal and a system-minted `serial_number`, and the appraisal's `trade_in_unit_id` points at it; second, the order's `trade_in_credit_cents` is set to the `final_credit_cents`, its `amount_financed_cents` is recomputed, and its `version` is incremented; third, rippling from the order's recompute, the order's financing application — if still `DRAFT` or `SUBMITTED` — has its `requested_amount_cents` and `estimated_payment_cents` recomputed at the type's rate floor.

The accepted trade-in then enters the used-inventory pipeline: the appraiser starts reconditioning, moving the appraisal `ACCEPTED` → `RECONDITIONING` and the unit `AT_DEALER` → `RECONDITIONING`; completing reconditioning moves the appraisal to its terminal `RETAIL_READY` and the unit `RECONDITIONING` → `RETAIL_READY`, from which it can be reserved and resold through a new sales order like any other unit.

## 4. Endpoint Definitions

All endpoints live under the `/api` mount. Creation endpoints return HTTP 201 with the new resource in `data`; action endpoints that modify an existing resource, all retrieval endpoints, and the clock-set capability return HTTP 200. "All roles" in the table below means every declared role listed in §2.1. Request bodies, response payloads, side effects, and preconditions are defined by the narratives of §2 and §3 and are intentionally not repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Test-driving logical clock; startup default 2026-08-01T00:00:00Z, never wall-clock | DealershipAdmin |
| POST | /api/home-models | Register a factory model in the catalog | DealershipAdmin |
| GET | /api/home-models | List models with optional filters and pagination | All roles |
| GET | /api/home-models/{id} | Fetch one model | All roles |
| POST | /api/communities | Register a land-lease community | DealershipAdmin |
| GET | /api/communities/{id} | Fetch one community | All roles |
| POST | /api/communities/{id}/lots | Add a lot to a community | DealershipAdmin |
| GET | /api/communities/{id}/lots | List a community's lots | All roles |
| GET | /api/lots/{id} | Fetch one lot | All roles |
| POST | /api/lots/{id}/reserve | Hold an AVAILABLE lot (AVAILABLE → RESERVED) | SalesConsultant |
| POST | /api/lots/{id}/release | Release a RESERVED lot not referenced by any non-terminal order | SalesConsultant |
| POST | /api/customers | Register a buyer | SalesConsultant |
| GET | /api/customers/{id} | Fetch one customer | All roles |
| POST | /api/home-units | Register a physical unit (STOCK starts AT_DEALER; FACTORY_ORDER starts AT_FACTORY) | DealershipAdmin |
| GET | /api/home-units/{id} | Fetch one unit | All roles |
| GET | /api/home-units | List units with filters | All roles |
| POST | /api/home-units/{id}/mark-ready | Factory completion: AT_FACTORY → AT_DEALER after the model's lead time | DealershipAdmin |
| POST | /api/sales-orders | Create a DRAFT order; reserves the unit; requires a RESERVED lot for community placement; runs pricing | SalesConsultant |
| GET | /api/sales-orders/{id} | Fetch one order | All roles |
| GET | /api/sales-orders | List orders with filters | All roles |
| POST | /api/sales-orders/{id}/options | Add a factory option line to a DRAFT order | SalesConsultant |
| GET | /api/sales-orders/{id}/options | List an order's options | All roles |
| POST | /api/order-options/{id}/void | Void an ACTIVE option on a DRAFT order | SalesConsultant |
| POST | /api/sales-orders/{id}/confirm | Confirm a DRAFT order with its deposit | SalesConsultant |
| POST | /api/sales-orders/{id}/cancel | Cancel a non-terminal order with full compensation cascade | SalesConsultant |
| POST | /api/sales-orders/{id}/close | Close a TITLED order (terminal) | DealershipAdmin |
| POST | /api/sales-orders/{id}/site-evaluations | Schedule a site evaluation; supersedes prior non-terminal evaluations; OCC-guarded | SalesConsultant |
| GET | /api/sales-orders/{id}/site-evaluations | List an order's evaluations | All roles |
| GET | /api/site-evaluations/{id} | Fetch one evaluation | All roles |
| POST | /api/site-evaluations/{id}/record-findings | Assigned evaluator records findings (SCHEDULED → FINDINGS_RECORDED) | SiteEvaluator |
| POST | /api/site-evaluations/{id}/approve | Approve recorded findings; bubbles the order to SITE_APPROVED | InstallationManager |
| POST | /api/site-evaluations/{id}/reject | Reject recorded findings; returns the order to DRAFT | InstallationManager |
| POST | /api/sales-orders/{id}/financing-applications | Open a financing application (DRAFT); supersedes the prior active application; OCC-guarded | SalesConsultant |
| GET | /api/sales-orders/{id}/financing-applications | List an order's applications | All roles |
| GET | /api/financing-applications/{id} | Fetch one application | All roles |
| POST | /api/financing-applications/{id}/submit | Submit a DRAFT application; computes requested amount and floor-rate estimated payment | SalesConsultant |
| POST | /api/financing-applications/{id}/decide | Lender decision: APPROVE / CONDITIONAL / DENY; CONDITIONALLY_APPROVED accepts a second APPROVE | LenderAgent |
| POST | /api/financing-applications/{id}/fund | Fund an APPROVED application within its rate lock; enforces the title gate | LenderAgent |
| POST | /api/transport-crews | Register a transport/set crew | DealershipAdmin |
| GET | /api/transport-crews/{id} | Fetch one crew including computed booked_dates | All roles |
| POST | /api/sales-orders/{id}/transport-jobs | Book transport for a FINANCING_APPROVED order; validates escort, capability, capacity; computes the quote | TransportCoordinator |
| GET | /api/sales-orders/{id}/transport-jobs | List an order's transport jobs | All roles |
| GET | /api/transport-jobs/{id} | Fetch one transport job | All roles |
| GET | /api/transport-jobs | List transport jobs with filters | All roles |
| POST | /api/transport-jobs/{id}/dispatch | Start the move (SCHEDULED → EN_ROUTE) within the window; unit goes IN_TRANSIT | TransportCoordinator |
| POST | /api/transport-jobs/{id}/delay | Declare a delivery delay (SCHEDULED → DELAYED); creates a delay notice | TransportCoordinator |
| POST | /api/transport-jobs/{id}/reschedule | Confirm the delayed job's new window (DELAYED → SCHEDULED) | TransportCoordinator |
| POST | /api/transport-jobs/{id}/deliver | Deliver on site (EN_ROUTE → DELIVERED); unit ON_SITE, lot LEASED, order DELIVERED | TransportCoordinator |
| POST | /api/transport-jobs/{id}/complete-set | Complete the set (DELIVERED → SET_COMPLETE); requires an approved evaluation with permit | InstallationManager |
| POST | /api/transport-jobs/{id}/cancel | Cancel a SCHEDULED or DELAYED job; frees crew window capacity | TransportCoordinator |
| POST | /api/sales-orders/{id}/delay-notices | Record an order-level buyer delay communication | SalesConsultant |
| GET | /api/transport-jobs/{id}/delay-notices | List a transport job's delay notices | All roles |
| GET | /api/sales-orders/{id}/delay-notices | List an order's delay notices | All roles |
| POST | /api/home-units/{id}/title-records | Apply for a title; at most one open record per unit | DealershipAdmin |
| GET | /api/home-units/{id}/title-records | List a unit's title records | All roles |
| GET | /api/title-records/{id} | Fetch one title record | All roles |
| POST | /api/title-records/{id}/issue | Issue the certificate (APPLIED → ISSUED); bubbles a SET_COMPLETE chattel order to TITLED | DealershipAdmin |
| POST | /api/title-records/{id}/convert | Convert an issued certificate to real-property affixed title (ISSUED → CONVERTED) | DealershipAdmin |
| POST | /api/title-records/{id}/surrender | Surrender the title of a trade-in unit (ISSUED → SURRENDERED) | DealershipAdmin |
| POST | /api/warranty-claims | File a warranty claim; validates coverage window and unit state; enters UNDER_REVIEW | Customer, ServiceManager |
| GET | /api/warranty-claims/{id} | Fetch one claim | All roles |
| GET | /api/home-units/{id}/warranty-claims | List a unit's claims | All roles |
| GET | /api/warranty-claims | List claims with filters | All roles |
| POST | /api/warranty-claims/{id}/review | Service review: APPROVE (sets approved cost) / DENY / REQUEST_INFO | ServiceManager |
| POST | /api/warranty-claims/{id}/resubmit | Return an INFO_REQUESTED claim to review or appeal a DENIED claim | Customer |
| POST | /api/warranty-claims/{id}/resolve | Mark an APPROVED claim resolved; resolver must differ from reviewer | ServiceManager |
| POST | /api/sales-orders/{id}/trade-in-appraisals | Open a trade-in appraisal with provisional credit; optional counter-offer supersession | SalesConsultant |
| GET | /api/sales-orders/{id}/trade-in-appraisals | List an order's appraisals | All roles |
| GET | /api/trade-in-appraisals/{id} | Fetch one appraisal | All roles |
| GET | /api/trade-in-appraisals | List appraisals with filters | All roles |
| GET | /api/home-units/{id}/trade-in-appraisals | List appraisals that produced this trade-in unit | All roles |
| POST | /api/trade-in-appraisals/{id}/inspect | Record inspected value, reconditioning cost, and grade; computes final credit | Appraiser |
| POST | /api/trade-in-appraisals/{id}/offer | Lock the final credit as a formal offer (INSPECTED → OFFERED) | Appraiser |
| POST | /api/trade-in-appraisals/{id}/decide | Customer accepts or declines the offer; acceptance triggers the trade-in cascade | Customer |
| POST | /api/trade-in-appraisals/{id}/start-reconditioning | Begin reconditioning the accepted trade-in (ACCEPTED → RECONDITIONING) | Appraiser |
| POST | /api/trade-in-appraisals/{id}/complete-reconditioning | Finish reconditioning (RECONDITIONING → RETAIL_READY); unit becomes resalable | Appraiser |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_HOME_MODEL_NOT_FOUND | 404 |
| ERR_COMMUNITY_NOT_FOUND | 404 |
| ERR_LOT_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_HOME_UNIT_NOT_FOUND | 404 |
| ERR_SALES_ORDER_NOT_FOUND | 404 |
| ERR_ORDER_OPTION_NOT_FOUND | 404 |
| ERR_SITE_EVALUATION_NOT_FOUND | 404 |
| ERR_FINANCING_APPLICATION_NOT_FOUND | 404 |
| ERR_TRANSPORT_CREW_NOT_FOUND | 404 |
| ERR_TRANSPORT_JOB_NOT_FOUND | 404 |
| ERR_TITLE_RECORD_NOT_FOUND | 404 |
| ERR_WARRANTY_CLAIM_NOT_FOUND | 404 |
| ERR_TRADE_IN_APPRAISAL_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ORDER_NOT_CANCELLABLE | 409 |
| ERR_HOME_UNIT_UNAVAILABLE | 409 |
| ERR_LOT_NOT_AVAILABLE | 409 |
| ERR_LOT_DIMENSION_INSUFFICIENT | 422 |
| ERR_PLACEMENT_MISMATCH | 422 |
| ERR_FINANCING_TYPE_INCOMPATIBLE | 422 |
| ERR_ESCORT_REQUIRED | 422 |
| ERR_PERMIT_MISSING | 422 |
| ERR_CREW_CAPABILITY_INSUFFICIENT | 422 |
| ERR_CREW_WINDOW_CONFLICT | 409 |
| ERR_EVALUATOR_CAPACITY_EXCEEDED | 409 |
| ERR_TITLE_ALREADY_ACTIVE | 409 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_RATE_BELOW_FLOOR | 422 |
| ERR_TERM_EXCEEDS_CAP | 422 |
| ERR_SCHEDULE_IN_PAST | 422 |
| ERR_PRODUCTION_INCOMPLETE | 409 |
| ERR_RATE_LOCK_EXPIRED | 409 |
| ERR_WARRANTY_EXPIRED | 422 |
| ERR_DELAY_NOTIFICATION_REQUIRED | 422 |
| ERR_UNIT_ORDER_MISMATCH | 422 |
| ERR_DEPOSIT_INSUFFICIENT | 422 |
| ERR_FUNDING_AMOUNT_MISMATCH | 422 |
| ERR_CLAIM_AMOUNT_EXCESS | 422 |
