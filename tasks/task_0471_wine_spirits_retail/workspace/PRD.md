# Wine & Spirits Retail API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Wine & Spirits Retail API, the back-office and point-of-sale platform behind a large-format beverage retailer in the mold of a national chain. The business sells wine, spirits, beer, and draft products (growler fills and kegs) through several channels — over-the-counter point of sale, in-store pickup, local delivery, and common-carrier shipping — and every one of those channels carries its own regulatory weight. A single sale must simultaneously satisfy federal age law, per-state Alcoholic Beverage Control (ABC) volume caps, bonded-versus-duty-paid inventory accounting, allocation limits on scarce vintages, and the retailer's own case-discount and loyalty-club economics.

The platform's central challenge is that a wine or spirits order is never a simple cart checkout. The same order is priced twice — once provisionally at submit time against estimated tax and zero excise, and again at payment capture against the real excise owed when bonded stock is withdrawn into duty-paid stock. Inventory is reserved across an aggregate boundary, compliance is tracked in a rolling monthly ledger, and a customer's eligibility to buy at all is a derived posture that the system continually re-evaluates. This PRD describes the entities, state machines, calculations, and validation ordering required to make those guarantees hold consistently, so that an implementer can build a server whose behavior is fully determined by the rules below.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint. Unless a later business-logic section overrides a detail in context, the conventions here apply universally.

### 2.1. User and Role-Based Access Control

Every request is authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the principal's operational capacity. If either header is missing, or `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The sole exception is customer self-registration, which is performed by the `Anonymous` role and requires no `X-User-ID`. Once authentication succeeds, the system checks whether the acting role is permitted to perform the requested operation; a role acting outside its authority is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `Customer`, `StoreAssociate`, `ComplianceOfficer`, `Admin`, and `Anonymous`.

When `X-User-Role` is `Customer`, the principal is an entity-backed end buyer: `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a `Customer` — an order, an order line via its parent order, a club membership, a special order, an ID scan, or a compliance window — compare that resource's customer foreign key (directly or through its parent) to `X-User-ID`. A `Customer` attempting to act on a resource owned by a different customer is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `StoreAssociate`, `X-User-ID` is an opaque point-of-sale operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same is true when `X-User-Role` is `ComplianceOfficer` — an opaque regulatory-operator identifier — and when `X-User-Role` is `Admin`, an opaque catalog-and-platform operator identifier. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise opaque and need not be present at all; the `Anonymous` role exists only to register a new customer and may do nothing else.

The roles divide responsibility as follows. A `Customer` manages their own customer record, carts, orders, club membership, special orders, and ID-scan uploads. A `StoreAssociate` runs the point of sale: ID-scan review, payment capture, fulfillment, shipments, and special-order quoting and conversion, and may also create and submit orders on a customer's behalf. A `ComplianceOfficer` handles regulatory operations: bonded lot creation, opening allocation, refunds, club suspension and reinstatement, state-rule maintenance, and compliance-window inspection. An `Admin` owns the catalog (products and vintages), vintage release and delisting, the logical clock, and seeding.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the response envelope's `meta` object.

### 2.4. Common Resource Properties and Resource Lifecycle Fields

Most resources carry a standard set of system-managed fields. Every such resource exposes an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recording when the resource was first created. Resources that may change after creation additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and a `version` — an integer that begins at 1 and increments by one with each mutation. The entities that carry the full set (`id`, `created_at`, `updated_at`, `version`) are `Product`, `Vintage`, `InventoryLot`, `Customer`, `Order`, `OrderLine`, `ClubMembership`, `SpecialOrder`, `Shipment`, and `StateRule`.

Two entities are append-only audit records and carry only `id` and `created_at`; they have neither `updated_at` nor `version`. The first is `IdScan`, the record of a single identity-document scan. The second is `ComplianceWindow`, a single ledger row in the monthly volume accounting. Even though a `ComplianceWindow` row's `active` flag can later be flipped, the row carries no `version` and no `updated_at`; treat the `active` transition as a content change on an audit row, not as a versioned mutation.

Whenever a derived field on a versioned entity is recomputed as a side effect — for example a customer's `compliance_status`, a vintage's `units_committed`, or an order's totals — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the entity it lands on.

### 2.5. Hierarchical Consistency, Cascades, and Compensation

Many operations in this domain mutate more than one entity. The system applies all such cascades immediately and synchronously within the triggering request; there is no eventual consistency. The defining example is order submission, which reserves inventory across an aggregate boundary: committing an order line debits the chosen `InventoryLot`'s `qty_reserved`, then re-derives the owning `Vintage`'s `units_committed`, then re-derives the owning `Customer`'s `compliance_status`. Each affected entity's `version` is bumped and its `updated_at` refreshed as part of the same request.

Compensating operations — cancellation, refund, and shipment return — reverse these effects symmetrically: reservations are released, lot quantities are credited back, derived aggregates are recomputed, and any compliance ledger row produced by the order is deactivated. The detailed cascades are described with each workflow in §3; the principle here is that no cascade is optional and none is deferred.

### 2.6. Nested Resource Retrieval and Path Validation

Several endpoints address a resource through a parent in the URL path — for example a vintage's lots are reached through the vintage, and an order's lines through the order. For any such path, the system validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. A request for the lines of a non-existent order fails on the order before the line collection is consulted. This same left-to-right existence rule applies to foreign-key identifiers supplied in a request body: every referenced `Order`, `OrderLine`, `Vintage`, `Product`, `InventoryLot`, `Customer`, `IdScan`, `ClubMembership`, `SpecialOrder`, `Shipment`, or `StateRule` must exist or the request is rejected with `ERR_NOT_FOUND`.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Where a calculation produces a fractional cent — for example when a discount rate or a sales-tax rate is applied — the result is rounded half up to the nearest whole cent. Volumes are integers in milliliters and are never rounded. Loyalty points are integers; where a tier multiplier produces a fractional point, the result is rounded half up. The specific points at which rounding is applied, and the order in which components are rounded then summed, are pinned in the calculation narratives of §3 and must be followed exactly, because the discount calculation in particular rounds each component before summing rather than rounding a single total.

### 2.8. The Logical Clock

Age verification, ID-document expiry, and the calendar-month bucketing of the compliance ledger all depend on the current time, and to keep those determinations deterministic the system reads time from a logical clock rather than the wall clock. On server startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to wall-clock time. An administrative test-driving capability sets the clock to a supplied instant provided in the `to_iso8601` field; the response echoes the new value as `current_utc`. Every age check, expiry comparison, and `window_month` assignment uses the logical clock's value at the moment of the request.

### 2.9. Optimistic Concurrency Control on Order Submission

Order submission is guarded by optimistic concurrency control to protect the allocation draw and reservation commit from being made against a stale view of the cart. Submitting an order requires a non-optional `expected_order_version` field carrying the client's last observed `version` of the target order. Because every cart mutation — adding a line, removing a line — legitimately increments the order's `version`, a client that read the order, then had its cart altered by another writer, would otherwise commit reservations against an outdated cart and allocation position. Therefore, if `expected_order_version` does not equal the target order's current `version`, the submit is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), and no reservation or pricing side effect occurs. Order submission is the only endpoint that takes a version field; no other endpoint accepts or requires `expected_order_version`.

### 2.10. Validation Ordering

When an endpoint can fail several checks, the checks are evaluated in a fixed priority order so that the error returned is always the highest-priority applicable failure. The global ordering is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) authorization of the role and ownership, yielding `ERR_FORBIDDEN`; (3) existence of every referenced resource, yielding `ERR_NOT_FOUND`; (4) state legality — that the target is in a state from which the requested transition is defined (and, for an order, in the correct dimension), yielding `ERR_INVALID_STATE` (HTTP 409); and (5) for order submission only, the optimistic-concurrency check yielding `ERR_STALE_ORDER_VERSION`.

After those gates, order submission runs its business checks in this pinned order: age verification (`ERR_AGE_NOT_VERIFIED`), then customer-blocked status (`ERR_CUSTOMER_BLOCKED`), then the growler/keg state ban (`ERR_GROWLER_KEG_STATE_BANNED`), then ship-state restriction (`ERR_SHIP_STATE_RESTRICTED`), then allocation cap (`ERR_ALLOCATION_LIMIT_EXCEEDED`), then the ABC monthly volume cap (`ERR_ABC_MONTHLY_LIMIT_EXCEEDED`), then single-lot inventory sufficiency (`ERR_INSUFFICIENT_INVENTORY`). Field-level validity checks — legal enum values, quantities of at least 1, alcohol-by-volume within range, two-letter state codes, and the uniqueness constraints (the `(product_id, vintage_year)` pair, `sku`, `email`, at most one active shipment per order) — surface as `ERR_INVALID_REQUEST` (HTTP 400), and the presence and typing of required body fields surface as `ERR_MISSING_FIELD` (HTTP 400). All HTTP 422 errors in this catalogue denote a business rule that was violated rather than a malformed request.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Products, Vintages, and Inventory Lots

The catalog is a three-level hierarchy maintained primarily by `Admin`, with bonded-inventory duties shared with `ComplianceOfficer`. A **Product** is the stable catalog entry created by an `Admin` with a `sku` (a catalog code that must be unique across all products), a display `name`, a `category`, a `container_type`, a per-unit liquid volume in milliliters (`bottle_volume_ml`, an integer of at least 1), and an alcohol-by-volume percentage (`abv_pct`, a number from 0 to 95 inclusive carried to two decimal places). The `category` is one of `WINE`, `SPIRITS`, `BEER`, `GROWLER`, or `KEG`, and the `container_type` is one of `BOTTLE`, `CAN`, `GROWLER_FILL`, or `KEG_HALF_BBL`; a `GROWLER` or `KEG` category requires the matching draft container. A product may be flagged as allocation-controlled through the optional `is_allocated` boolean, which defaults to false when omitted, marking scarce items such as rare bourbon. On creation a product's `status` is initialized to `ACTIVE` — the only value the catalog status takes in this version — and the product's minimum buyer age, `min_purchase_age`, is computed and stored.

The minimum purchase age is a single legal floor. Regardless of category or alcohol content — including beer below eight percent alcohol by volume — `min_purchase_age` is always set to 21 years, the US federal floor for all alcohol. The field exists so that callers and tests can rely on it being exactly 21 and never read from any other source.

Beneath a product, an `Admin` creates one or more **Vintage** rows, each carrying the parent's `product_id`, a `vintage_year` (an integer from 1900 to 2100 inclusive, unique within the product so that the `product_id` and `vintage_year` pair is unique), a per-unit shelf price in cents exclusive of tax (`list_price_cents`, an integer of at least 1), and a `case_pack_size` (an integer of at least 1, commonly 6 or 12, giving the number of units that make up one full case). An allocation cap may be supplied through `allocation_cap_per_customer`, the maximum units of this vintage a single customer may buy across all orders; it is null (uncapped) by default and is only meaningful when the parent product is allocation-controlled. A vintage tracks `units_committed`, a derived count of units across all of its order lines currently in committed or fulfilled reservation state, initialized to 0. A vintage's `status` begins at `DRAFT`.

Inventory for a vintage lives in **InventoryLot** rows, created by a `ComplianceOfficer` or `Admin` under the vintage. A lot carries its parent's `vintage_id`, a `tax_status` of either `BONDED` (tax-deferred storage) or `TAXED` (duty-paid storage), the physical unit count `qty_on_hand` (an integer of at least 0), and the per-unit excise owed when the lot is withdrawn from bond, `excise_band_cents_per_unit` (an integer of at least 0). The lot also tracks `qty_reserved`, the units held by uncaptured order lines, which starts at 0 and is debited as orders commit and credited back as they cancel or refund.

A vintage moves through a small availability state machine. An `Admin` releases a non-allocated vintage, advancing `DRAFT → RELEASED`; this requires the vintage to be in `DRAFT`, its parent product to be non-allocated, and at least one inventory lot for the vintage to hold `qty_on_hand` of at least 1 — failing the stock requirement (or being called on an allocated product) yields `ERR_RELEASE_REQUIRES_STOCK`. Symmetrically, a `ComplianceOfficer` opens allocation on an allocation-controlled vintage, advancing `DRAFT → ALLOCATION_OPEN`; this requires the vintage to be in `DRAFT`, its parent product to be allocation-controlled, and `allocation_cap_per_customer` to be non-null — any of those failing yields `ERR_ALLOCATION_OPEN_REQUIRES_FLAG`. The system itself advances a vintage `RELEASED → SOLD_OUT` or `ALLOCATION_OPEN → SOLD_OUT` at submit time when, after the triggering commit, the sum across the vintage's lots of available units (each lot's `qty_on_hand` minus its `qty_reserved`) reaches zero; conversely, when a cancel or refund returns availability to a non-allocated, sold-out vintage so that the summed available units rises to at least 1, the system advances it `SOLD_OUT → RELEASED`. Finally an `Admin` may delist a vintage, advancing it to `DELISTED` from `RELEASED`, `SOLD_OUT`, or `DRAFT`, provided no order line of the vintage is currently in `PENDING` or `COMMITTED` reservation state. Each of these transitions bumps the vintage's `version`. A delisted vintage is terminal.

### 3.2. Customer Onboarding, ID Scanning, and Age Verification

A buyer enters the system through self-registration, performed by the `Anonymous` role with no authentication. Registration supplies the customer's login `email` (unique across all customers), `full_name` (the legal name as printed on identification), `date_of_birth`, and `ship_state_code` (a two-uppercase-letter US state code). A new customer is born with `age_verified` false, `compliance_status` set to `CLEAR`, and `lifetime_spend_cents` at 0. The customer record exposes those three derived fields on read.

Age verification runs through the **IdScan** record. A `StoreAssociate` (at the point of sale) or the `Customer` (self-upload) submits a scan carrying the `customer_id` of the person scanned, the issuing state of the document (`id_state_code`, two uppercase letters), the document's expiry date (`id_expiry_date`), and the date of birth read off the document (`scanned_dob`). The scan is created in `PENDING` status. A `StoreAssociate` then reviews it. Verification advances `PENDING → VERIFIED` only when the document is not expired — its `id_expiry_date` is on or after the current logical-clock time — and the scanned date of birth matches the owning customer's recorded `date_of_birth`, and the age in whole years derived from `scanned_dob` at the current time is at least 21. On a successful verify, the owning customer's `age_verified` flips to true and that customer's `compliance_status` is recomputed. Alternatively a `StoreAssociate` rejects a pending scan, advancing `PENDING → REJECTED` and recording a `reject_reason` of `EXPIRED`, `DOB_MISMATCH`, or `UNDERAGE`; rejecting likewise triggers a recompute of the customer's `compliance_status`. The `reject_reason` is null until a rejection populates it.

A customer's **compliance status** is a derived risk posture recomputed after every ID-scan verify or reject, after order submit, after order complete, and after order refund. It is computed by accumulating a risk score: start at zero; add 2 if the customer is not age-verified; add 1 for each `REJECTED` ID scan on file for the customer; and add 3 if there exists any active compliance-window row whose running monthly used volume for its state and month is within 750 milliliters of that state's monthly cap. A final score of exactly 0 yields `CLEAR`; a score of 1 or 2 yields `WATCH`; a score greater than 2 yields `BLOCKED`. The boundary is pinned: a score of exactly 2 is `WATCH`, not `BLOCKED`, and a `WATCH` customer may still submit orders — only a `BLOCKED` posture stops submission.

### 3.3. Building and Submitting an Order

An order begins as a cart. A `Customer` (or a `StoreAssociate` acting at the point of sale) creates an order for a customer by supplying the `customer_id`, the `channel`, and — for shipping channels — the `dest_state_code`. The `channel` is one of `POS`, `PICKUP`, `DELIVERY`, or `SHIP`; `POS` and `PICKUP` are in-store channels that skip shipping-state checks, while `DELIVERY` and `SHIP` enforce them and require a two-letter `dest_state_code` (the field is null and ignored for the in-store channels). A new order is created with `fulfillment_status` `CART`, `payment_status` `UNPAID`, and `version` 1.

Cart contents are **OrderLine** rows. A line is added to a `CART` order with the `vintage_id` being purchased and a `qty` of at least 1; the line is created with `reservation_state` `PENDING`, and adding it bumps the owning order's `version`. The line also carries the order's `order_id`. A pending line on a cart order may be removed; deletion likewise bumps the order's `version`. Each line also has a `lot_id` (the lot chosen to fulfill it, null until submit), a `unit_price_cents` snapshot, and a `line_excise_cents` value resolved later at capture.

Submission is the pivotal transition, advancing `fulfillment_status` `CART → SUBMITTED`, driven by the `Customer` or a `StoreAssociate` and carrying the `expected_order_version` described in §2.9. Submission is permitted only when the order is in `CART`, has at least one order line (an empty cart is rejected with `ERR_EMPTY_ORDER`), the acting customer is not `BLOCKED`, and the acting customer is age-verified. For every line, the parent vintage must be in `RELEASED` or `ALLOCATION_OPEN` status, or the submit is rejected with `ERR_VINTAGE_NOT_PURCHASABLE`. The remaining compliance and inventory checks — age, blocked status, growler/keg state ban, ship-state restriction, allocation cap, monthly volume cap, and single-lot sufficiency, in that priority order — are detailed in §3.4 and §3.5.

On a successful submit the system performs a cascade. First it selects, for each line, a single inventory lot of that vintage whose available units (`qty_on_hand` minus `qty_reserved`) are at least the line's `qty` — the line is never split across lots — and records the chosen lot on the line's `lot_id` while snapshotting the vintage's current `list_price_cents` onto the line's `unit_price_cents`. Each line's `reservation_state` advances `PENDING → COMMITTED`, and the selected lot's `qty_reserved` is increased by the line's `qty`. Next, each affected vintage's `units_committed` is recomputed, and any vintage whose available units have fallen to zero is auto-advanced to `SOLD_OUT`. The order's `discount_cents` and `provisional_total_cents` are then computed (§3.6). For a `DELIVERY` or `SHIP` order, a compliance-window ledger row is created (§3.5). Finally the owning customer's `compliance_status` is recomputed, and the order's `version` is incremented.

### 3.4. Age, Eligibility, and the Draft-Container State Rule

The first business gate on submission is age. The acting customer's `age_verified` flag must be true — meaning a non-expired `VERIFIED` ID scan whose scanned date of birth proves an age of at least 21 is on file — or the submit is rejected with `ERR_AGE_NOT_VERIFIED` (HTTP 422). The same age gate guards the conversion of an accepted special order into an order. Immediately after age, the customer's `compliance_status` is checked: a `BLOCKED` customer is turned away with `ERR_CUSTOMER_BLOCKED` (HTTP 422), and this gate too applies both to order submission and to special-order conversion.

Draft containers carry a state-specific shipping restriction. **StateRule** rows, maintained by a `ComplianceOfficer` or `Admin`, govern shipping into a destination state. Each rule is keyed by a unique two-letter `state_code` and carries `ship_allowed` (whether delivery or shipping into the state is permitted at all, default true), `growler_keg_allowed` (whether growler or keg lines may ship there, default true), `monthly_volume_limit_ml` (the ABC per-customer per-calendar-month total volume cap in milliliters, null meaning uncapped), and `requires_adult_signature` (whether shipments to the state need an adult signature, default true). Creating a state rule for a `state_code` that already exists upserts the existing rule rather than duplicating it.

For a `DELIVERY` or `SHIP` order, if any line's parent product is in the `GROWLER` or `KEG` category, the destination state's rule must have `growler_keg_allowed` true, or the submit is rejected with `ERR_GROWLER_KEG_STATE_BANNED` (HTTP 422). Growler and keg lines are exempt from case discounts, as described in §3.6.

### 3.5. Shipping-State Eligibility and the ABC Monthly Volume Ledger

For any `DELIVERY` or `SHIP` order, the destination must be shippable. A `StateRule` must exist for the order's `dest_state_code` and have `ship_allowed` true; if no rule exists for the destination, or the rule forbids shipping, the submit is rejected with `ERR_SHIP_STATE_RESTRICTED` (HTTP 422). This check follows the growler/keg ban in priority order.

The retailer must also honor each state's ABC monthly volume cap, and to do so it keeps a **ComplianceWindow** ledger. The total alcohol volume of an order is the sum over its lines of the line's `qty` multiplied by the parent product's `bottle_volume_ml`, expressed in milliliters. The calendar-month bucket, `window_month`, is the `YYYY-MM` string (UTC) of the submitting order's logical-clock timestamp. The customer's already-used volume for a destination state in a month is the sum of `volume_ml` over the customer's active compliance-window rows whose `customer_id` is the buyer, whose `state_code` equals the destination, and whose `window_month` equals the submit month. The order is rejected with `ERR_ABC_MONTHLY_LIMIT_EXCEEDED` (HTTP 422) when that already-used volume plus this order's volume would be strictly greater than the destination state's `monthly_volume_limit_ml`; exactly reaching the limit is allowed. When the cap is null the state is uncapped and this check passes. On a successful submit for a shipping channel, the system writes a compliance-window row recording the buyer's `customer_id`, the producing order's `order_id`, the destination `state_code`, the order's `volume_ml`, the `window_month`, and `active` set to true.

When the producing order is later cancelled or refunded, its compliance-window row's `active` flag is flipped to false so that the released volume no longer counts against the month's cap — the compensating invariant that keeps the monthly accounting honest.

Allocation caps are the third constraint class. For each line whose parent product is allocation-controlled, the customer's existing committed-or-fulfilled units of that vintage plus the line's `qty` must not exceed the vintage's `allocation_cap_per_customer`; exceeding the cap rejects the submit with `ERR_ALLOCATION_LIMIT_EXCEEDED` (HTTP 422). The allocation check runs before the monthly-volume check in priority order. Finally, inventory sufficiency is checked last among the business rules: for each line there must be a single inventory lot of the vintage whose available units (`qty_on_hand` minus `qty_reserved`) are at least the line's `qty`; if no single lot can cover the line — splitting across lots is not allowed — the submit is rejected with `ERR_INSUFFICIENT_INVENTORY` (HTTP 422). A `ComplianceOfficer` or `Admin` can inspect the ledger: rows may be listed for a customer (optionally filtered by `state_code`, `window_month`, or `active`) or for the order that produced them.

### 3.6. Order Pricing: Case Discount, Provisional Total, and Settled Total

Pricing happens in two acts. The **case discount** is computed at submit and stored as the order's `discount_cents`. Growler and keg category lines are excluded entirely from the discount — neither their value nor their units count — because draft containers earn no case discount. The calculation over the remaining (discountable) lines proceeds in a pinned order. First, the gross value is the sum over discountable lines of the line's `qty` times the parent vintage's `list_price_cents`, with no rounding yet. Second, the total unit count is the sum over discountable lines of `qty`. Third, the full-case unit count is the sum over discountable lines of the part of each line's `qty` that forms whole multiples of that line's own `case_pack_size` — that is, for each line, its `qty` minus the remainder of `qty` divided by its `case_pack_size`. Fourth, the mixed-case unit count is the total unit count minus the full-case unit count.

The rates apply differentially. Full-case units always earn the full-case rate of fifteen percent. Mixed-case units earn the mixed-case rate of ten percent only when the total discountable unit count is at least 12; otherwise mixed-case units earn nothing. To compute the discount in cents, first determine the full-case value as the sum over discountable lines of (the line's full-case portion of `qty`) times `list_price_cents`, and the mixed-case value as the gross value minus the full-case value. The discount is then the full-case value times fifteen percent, rounded half up to the nearest cent, plus the mixed-case value times the applicable mixed-case rate (ten percent when the total discountable unit count is at least 12, otherwise zero), rounded half up to the nearest cent. The rounding order is pinned: round each of the two components independently and then sum them, never round a single product of total times rate. As worked variants: when every discountable line's `qty` is an exact multiple of its `case_pack_size`, the mixed-case value is zero and the discount is simply the full-case value times fifteen percent rounded half up; and when the total discountable unit count is below 12, the mixed-case units earn zero and only any full-case units earn fifteen percent.

The **provisional total**, stored as `provisional_total_cents`, is also computed at submit, before any bonded stock is withdrawn, and therefore carries an estimated excise of zero. The line subtotal is the sum over all lines of `qty` times the line's snapshotted `unit_price_cents`. The discounted subtotal is that line subtotal minus the order's `discount_cents`. The estimated tax is the discounted subtotal times the destination sales-tax rate, rounded half up to the nearest cent, where the rate is the rate for the destination state (or the store's state for in-store channels) and defaults to 0.0725. The provisional total is the discounted subtotal plus the estimated tax.

The **settled total**, stored as `settled_total_cents`, is computed at payment capture, after any bonded-to-taxed withdrawal, and so includes real excise. The line subtotal and discounted subtotal are computed as before (sum of `qty` times `unit_price_cents`, minus `discount_cents`). The excise total is the sum over lines of each line's `line_excise_cents`, resolved from the lot actually withdrawn. The taxable base — and this ordering is pinned, because excise is itself taxable — is the discounted subtotal plus the excise total. The final tax is that taxable base times the destination sales-tax rate (defaulting to 0.0725), rounded half up to the nearest cent. The settled total is the discounted subtotal plus the excise total plus the final tax. The settled total diverges from the provisional total exactly when some line drew from a bonded lot.

### 3.7. Payment, Bonded Withdrawal, Fulfillment, and Completion

Payment is a parallel dimension on the order, independent of fulfillment, and moves through its own state machine. A `Customer` or `StoreAssociate` authorizes payment, advancing `payment_status` `UNPAID → AUTHORIZED`; this requires the order to be `UNPAID` on the payment dimension and `SUBMITTED` on the fulfillment dimension, and it places a payment hold equal to the order's `provisional_total_cents`. A `StoreAssociate` then captures payment, advancing `AUTHORIZED → CAPTURED`; this requires the order to be `AUTHORIZED` and `SUBMITTED`.

Capture carries the most intricate cascade in the system, the bonded-to-taxed conversion. For each order line whose chosen lot is `BONDED` at capture time, the system withdraws that line's units from bond: it sets the line's `line_excise_cents` to the line's `qty` times the bonded lot's `excise_band_cents_per_unit`; it decrements that bonded lot's `qty_on_hand` by the line's `qty` and its `qty_reserved` by the line's `qty`; it mints or appends a `TAXED` inventory lot for the same vintage and increases that taxed lot's `qty_on_hand` by the line's `qty`; and it repoints the line's `lot_id` to the taxed lot. For a line whose lot was already `TAXED`, the `line_excise_cents` is zero and no withdrawal occurs. After resolving all line excise, the order's `settled_total_cents` is computed (§3.6). Capture increments the order's `version`.

Fulfillment continues on the other dimension. A `StoreAssociate` marks a captured order ready, advancing `fulfillment_status` `SUBMITTED → READY`; this requires the order's fulfillment to be `SUBMITTED` and its payment to be `CAPTURED`, and it advances each line's `reservation_state` `COMMITTED → FULFILLED`. A `StoreAssociate` then completes the order, advancing `READY → COMPLETED`; this requires the order to be `READY`, and — for `DELIVERY` or `SHIP` channels — requires a shipment for the order to be in `DELIVERED` status. Completion recomputes the customer's `lifetime_spend_cents` and `compliance_status`, and if the customer holds an active club membership it accrues loyalty points and re-derives the membership tier (§3.8). Completion increments the order's `version`.

The customer's **lifetime spend** is the sum of `settled_total_cents` over the customer's orders whose `payment_status` is `CAPTURED` and whose `fulfillment_status` is not `CANCELLED`; refunded orders are excluded.

### 3.8. The Wine Club: Membership, Tiers, and Points

A `Customer` (or a `StoreAssociate` on their behalf) enrolls a customer in the wine club by supplying the `customer_id`; the resulting **ClubMembership** is created `ACTIVE` with `tier` `BRONZE` and `accrued_points` at 0. A customer may hold at most one membership that is `ACTIVE` or `SUSPENDED` at a time; enrolling a customer who already has such a membership is rejected with `ERR_DUPLICATE_MEMBERSHIP` (HTTP 409). A `ComplianceOfficer` may suspend an active membership (`ACTIVE → SUSPENDED`) and reinstate a suspended one (`SUSPENDED → ACTIVE`); a `Customer` may cancel their own membership from either `ACTIVE` or `SUSPENDED`, advancing it to the terminal `CANCELLED`. Each membership transition increments the membership's `version`.

When an order completes and the customer has an active membership, the club tier and points are re-derived from the customer's freshly recomputed `lifetime_spend_cents`. If that rolling spend is at least 200000 cents the tier becomes `GOLD` with a multiplier of 1.50; otherwise if it is at least 50000 cents the tier becomes `SILVER` with a multiplier of 1.25; otherwise the tier is `BRONZE` with a multiplier of 1.00. The threshold boundary is pinned to be inclusive: a rolling spend of exactly 50000 cents qualifies as `SILVER`, and exactly 200000 cents qualifies as `GOLD`. Points for the just-completed order are computed by taking the order's `settled_total_cents`, dividing by 100 and discarding any fractional remainder to get a base, then multiplying that base by the tier multiplier and rounding half up to a whole number of points; the result is added to the membership's `accrued_points`.

### 3.9. Special Orders: The Negotiation Loop and Conversion

Rare or non-stock items are handled through a **SpecialOrder**, which runs a cyclic price negotiation. A `Customer` or `StoreAssociate` requests one by supplying the requesting `customer_id`, a free-text `description` of the item, and a `requested_qty` of at least 1; it is created in `REQUESTED` status with `round_count` 0. The negotiation then proceeds. A `StoreAssociate` quotes the request, advancing `REQUESTED → QUOTED` and setting `quoted_unit_price_cents` from the request body. The `Customer` may counter a quote, advancing `QUOTED → COUNTERED`, setting `customer_counter_price_cents` from the request body and incrementing `round_count` by one. A `StoreAssociate` may re-quote a countered request, advancing `COUNTERED → QUOTED` and again setting `quoted_unit_price_cents` — this is the revision loop. Both the counter and the re-quote transitions are guarded by the round limit: they are permitted only while `round_count` is below 3, and an attempt to counter or quote once `round_count` has reached 3 is rejected with `ERR_NEGOTIATION_ROUNDS_EXCEEDED` (HTTP 422).

A `Customer` may accept the current quote, advancing `QUOTED → ACCEPTED`, or decline the request, advancing it to the terminal `DECLINED` from `REQUESTED`, `QUOTED`, or `COUNTERED`. A `StoreAssociate` converts an accepted special order, advancing `ACCEPTED → CONVERTED`; conversion requires the owning customer to be age-verified (else `ERR_AGE_NOT_VERIFIED`) and not `BLOCKED` (else `ERR_CUSTOMER_BLOCKED`), and it creates a new `PICKUP` order for the customer with one order line derived from the special order, recording the new order's identifier on the special order's `converted_order_id`.

### 3.10. Order Cancellation, Refund, and the Shipment Branch

An order can be unwound at two points. A `Customer` or `StoreAssociate` cancels an order. Cancelling a `CART` order simply advances `fulfillment_status` `CART → CANCELLED`. Cancelling a `SUBMITTED` order — permitted only while its `payment_status` is `UNPAID` or `AUTHORIZED` — advances `SUBMITTED → CANCELLED` and runs the compensation cascade: each line's `reservation_state` advances `COMMITTED → RELEASED`, the lot's `qty_reserved` is credited back by the line's `qty`, the affected vintages' `units_committed` are recomputed (and a `SOLD_OUT` non-allocated vintage may return to `RELEASED` when availability comes back), and if the payment was `AUTHORIZED` the hold is voided and `payment_status` returns `AUTHORIZED → UNPAID`. If the order produced a compliance-window row, its `active` flag is set false. Cancellation increments the order's `version`.

A `ComplianceOfficer` refunds a captured order, advancing `payment_status` `CAPTURED → REFUNDED`, permitted only while the order's `payment_status` is `CAPTURED` and its `fulfillment_status` is not yet `COMPLETED`. A refund releases every line's reservation (`reservation_state → RELEASED`), credits `qty_reserved` back, restores `qty_on_hand` on the lot each line drew from, sets the order's `fulfillment_status` to `CANCELLED`, deactivates any compliance-window row for the order, and recomputes the customer's `lifetime_spend_cents` and `compliance_status`. The refund increments the order's `version`.

Shipping is handled by the **Shipment** entity, created by a `StoreAssociate` for a `READY` order on a `DELIVERY` or `SHIP` channel. Creating a shipment for a `POS` or `PICKUP` order, or for an order not in `READY` fulfillment and `CAPTURED` payment, is rejected with `ERR_SHIPMENT_CHANNEL_INVALID` (HTTP 422). At most one non-cancelled shipment may exist per order; a second is rejected with `ERR_DUPLICATE_ACTIVE_SHIPMENT` (HTTP 409). The shipment is created in `LABELED` status with the `carrier` from the request body — one of `STORE_COURIER` or `LICENSED_COMMON_CARRIER` — and snapshots the order's destination into the shipment's own `dest_state_code`. Its `adult_signature_required` flag is derived from the destination state's rule: it takes the value of that `StateRule`'s `requires_adult_signature`, and defaults to true when no rule exists for the destination state.

The shipment then branches. A `StoreAssociate` dispatches a labeled shipment, advancing `LABELED → DISPATCHED`, which requires the shipment to be `LABELED` and the owning order to be `READY` in fulfillment and `CAPTURED` in payment. From `DISPATCHED` the shipment may either be delivered or returned. Confirming delivery advances `DISPATCHED → DELIVERED`; when the shipment's `adult_signature_required` is true the request must provide `signature_captured` set to true, and omitting it is rejected with `ERR_SIGNATURE_REQUIRED` (HTTP 422). Returning a dispatched shipment advances `DISPATCHED → RETURNED` and cascades across the aggregate boundary: the owning order is cancelled from `READY` via the same compensation as an order cancel — reservations released, lot quantities restored, and the compliance-window row deactivated. Each shipment transition increments the shipment's `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a distinct resource to a collection return `201 Created`. Operations that modify an existing resource, including driving a state transition, return `200 OK`. The line-removal operation returns `204 No Content`. The complete request and response semantics for each endpoint are reconstructed from the business narratives in §3; the table below lists only the HTTP contract and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | Admin |
| POST | `/customers/register` | Register a new customer | Anonymous |
| GET | `/customers/{id}` | Read a customer with derived fields | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/customers` | List customers | StoreAssociate, ComplianceOfficer, Admin |
| POST | `/id-scans` | Submit an ID scan for a customer | StoreAssociate, Customer |
| GET | `/id-scans/{id}` | Read an ID scan | StoreAssociate, ComplianceOfficer, Admin, Customer |
| GET | `/customers/{id}/id-scans` | List a customer's ID scans | StoreAssociate, ComplianceOfficer, Admin, Customer |
| POST | `/id-scans/{id}/verify` | Verify an ID scan | StoreAssociate |
| POST | `/id-scans/{id}/reject` | Reject an ID scan with a reason | StoreAssociate |
| POST | `/products` | Create a catalog product | Admin |
| GET | `/products/{id}` | Read a product | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/products` | List products | Customer, StoreAssociate, ComplianceOfficer, Admin |
| POST | `/products/{id}/vintages` | Create a vintage under a product | Admin |
| GET | `/vintages/{id}` | Read a vintage with derived units_committed | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/products/{id}/vintages` | List vintages of a product | Customer, StoreAssociate, ComplianceOfficer, Admin |
| POST | `/vintages/{id}/release` | Release a non-allocated vintage | Admin |
| POST | `/vintages/{id}/open-allocation` | Open allocation for an allocated vintage | ComplianceOfficer |
| POST | `/vintages/{id}/delist` | Delist a vintage | Admin |
| POST | `/vintages/{id}/lots` | Add an inventory lot for a vintage | ComplianceOfficer, Admin |
| GET | `/lots/{id}` | Read an inventory lot | StoreAssociate, ComplianceOfficer, Admin |
| GET | `/vintages/{id}/lots` | List inventory lots of a vintage | StoreAssociate, ComplianceOfficer, Admin |
| POST | `/state-rules` | Create or upsert a per-state rule | ComplianceOfficer, Admin |
| GET | `/state-rules/{id}` | Read a state rule by id | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/state-rules` | List state rules | Customer, StoreAssociate, ComplianceOfficer, Admin |
| POST | `/orders` | Create a cart order | Customer, StoreAssociate |
| GET | `/orders/{id}` | Read an order with computed totals | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/orders` | List orders | Customer, StoreAssociate, ComplianceOfficer, Admin |
| POST | `/orders/{id}/lines` | Add a line to a cart order | Customer, StoreAssociate |
| GET | `/orders/{id}/lines` | List lines of an order | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/order-lines/{id}` | Read a single order line | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/order-lines` | List order lines filtered by vintage or lot | StoreAssociate, ComplianceOfficer, Admin |
| DELETE | `/order-lines/{id}` | Remove a pending line from a cart order | Customer, StoreAssociate |
| POST | `/orders/{id}/submit` | Submit a cart for reservation and pricing | Customer, StoreAssociate |
| POST | `/orders/{id}/authorize-payment` | Place a payment hold | Customer, StoreAssociate |
| POST | `/orders/{id}/capture-payment` | Capture payment and withdraw bonded stock | StoreAssociate |
| POST | `/orders/{id}/mark-ready` | Mark a captured order ready | StoreAssociate |
| POST | `/orders/{id}/complete` | Complete an order | StoreAssociate |
| POST | `/orders/{id}/cancel` | Cancel a cart or submitted order | Customer, StoreAssociate |
| POST | `/orders/{id}/refund` | Refund a captured order | ComplianceOfficer |
| GET | `/customers/{id}/compliance-windows` | List a customer's compliance-window rows | ComplianceOfficer, Admin |
| GET | `/orders/{id}/compliance-windows` | List compliance-window rows produced by an order | ComplianceOfficer, Admin |
| POST | `/orders/{id}/shipments` | Create a shipment for a ready shipping order | StoreAssociate |
| GET | `/shipments/{id}` | Read a shipment | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/orders/{id}/shipments` | List shipments of an order | Customer, StoreAssociate, ComplianceOfficer, Admin |
| POST | `/shipments/{id}/dispatch` | Dispatch a labeled shipment | StoreAssociate |
| POST | `/shipments/{id}/confirm-delivery` | Confirm delivery (signature if required) | StoreAssociate |
| POST | `/shipments/{id}/return` | Mark a dispatched shipment returned | StoreAssociate |
| POST | `/club-memberships` | Enroll a customer in the wine club | Customer, StoreAssociate |
| GET | `/club-memberships/{id}` | Read a club membership | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/customers/{id}/club-memberships` | List a customer's club memberships | Customer, StoreAssociate, ComplianceOfficer, Admin |
| POST | `/club-memberships/{id}/suspend` | Suspend a membership | ComplianceOfficer |
| POST | `/club-memberships/{id}/reinstate` | Reinstate a suspended membership | ComplianceOfficer |
| POST | `/club-memberships/{id}/cancel` | Cancel a membership | Customer |
| POST | `/special-orders` | Request a special order | Customer, StoreAssociate |
| GET | `/special-orders/{id}` | Read a special order | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/customers/{id}/special-orders` | List a customer's special orders | Customer, StoreAssociate, ComplianceOfficer, Admin |
| GET | `/special-orders` | List special orders | StoreAssociate, ComplianceOfficer, Admin |
| POST | `/special-orders/{id}/quote` | Quote or re-quote a special order | StoreAssociate |
| POST | `/special-orders/{id}/counter` | Customer counter-offers | Customer |
| POST | `/special-orders/{id}/accept` | Customer accepts the current quote | Customer |
| POST | `/special-orders/{id}/decline` | Decline the special order | Customer |
| POST | `/special-orders/{id}/convert` | Convert an accepted special order into a pickup order | StoreAssociate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_AGE_NOT_VERIFIED` | 422 |
| `ERR_CUSTOMER_BLOCKED` | 422 |
| `ERR_GROWLER_KEG_STATE_BANNED` | 422 |
| `ERR_SHIP_STATE_RESTRICTED` | 422 |
| `ERR_ALLOCATION_LIMIT_EXCEEDED` | 422 |
| `ERR_ABC_MONTHLY_LIMIT_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 422 |
| `ERR_VINTAGE_NOT_PURCHASABLE` | 422 |
| `ERR_ALLOCATION_OPEN_REQUIRES_FLAG` | 422 |
| `ERR_RELEASE_REQUIRES_STOCK` | 422 |
| `ERR_NEGOTIATION_ROUNDS_EXCEEDED` | 422 |
| `ERR_SIGNATURE_REQUIRED` | 422 |
| `ERR_DUPLICATE_ACTIVE_SHIPMENT` | 409 |
| `ERR_DUPLICATE_MEMBERSHIP` | 409 |
| `ERR_SHIPMENT_CHANNEL_INVALID` | 422 |
| `ERR_EMPTY_ORDER` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_MISSING_FIELD` | 400 |
| `ERR_INVALID_PAGINATION` | 400 |
