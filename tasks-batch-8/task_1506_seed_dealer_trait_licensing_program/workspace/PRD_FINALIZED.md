# Seed Dealer & Trait Licensing Program API — Product Requirements Document

## 1. Introduction

A regional seed dealership runs its entire selling season as a sequence of crop-year **programs**. A catalog of corn and soybean varieties — many carrying licensed biotechnology trait packages — is offered to grower accounts under early-order discount tiers, prepay incentives, and per-order volume rebates. Seed then moves to the farm on scheduled delivery or pickup tickets drawn from warehouse lots; unsold or damaged seed comes back through a returns pipeline with restocking fees and repriced credits; weather-damaged stands are compensated through replant claims that spawn zero- or reduced-price replacement orders; and the dealership's own compensation accrues on a per-program commission statement that is finalized when the season settles. Feeding the commercial flow, agronomists issue variety placement recommendations per field and run plot trials whose harvested yield results become quotable marketing only after enough replications exist.

Woven through the commercial flow is a compliance spine. Seed of varieties carrying a trait package flagged as requiring a stewardship agreement may only be sold to growers holding an active, in-window trait/technology agreement, and stewardship actions such as suspension or revocation must freeze in-flight confirmed orders without losing track of their inventory reservations or their money. Segregation of duties governs claims adjudication: the adjuster who reviews or decides a replant claim must never be the person who filed it.

This document specifies the REST API backing that operation. All endpoints are mounted under the `/dealer` prefix and serve five acting roles — dealership administrators, sales representatives, agronomists, growers, and independent claims adjusters. Three commitments shape the design: pricing that is deterministic to the cent (every discount tier, rebate, prepay computation, and return credit has a pinned evaluation order and rounding rule), inventory and cash that are conserved (every seed unit and every prepaid cent is accounted for across receipt, reservation, delivery, return, write-off, and settlement), and a season lifecycle with two explicit ops-run checkpoints — sales close and settlement — whose cascading sweeps are fully specified. A server-side logical clock, never wall-clock time, governs every window, expiry, and eligibility rule so a full season can be driven deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming that user's role. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Once the caller is identified, the caller's role must appear in the endpoint's authorized role list (§4); otherwise the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

Five roles exist, spelled exactly as follows:

- `DealerAdmin` — the dealership operator: owns the program, the catalog, inventory, compliance actions, credit posture, and settlement.
- `SalesRep` — a dealer sales representative: manages grower accounts and their orders, deliveries, returns, and replant claims.
- `Agronomist` — the dealer agronomist: owns placement recommendations and plot trials.
- `Grower` — a farm customer acting on their own account.
- `ClaimsAdjuster` — an independent replant-claim adjudicator who may file claims but may never review or decide a claim they filed.

Identity semantics differ by role. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `GrowerAccount`; ownership checks on any resource that references a grower compare the resource's grower field to `X-User-ID`. Concretely, a grower may only act on resources whose grower chain resolves to their own account: an order's `grower_id`, a recommendation's `grower_id`, a field's `grower_id`, an agreement's `grower_id`, or — for a replant claim — the `grower_id` of the claim's underlying order. A grower acting on a resource outside that chain is rejected with `ERR_GROWER_OWNERSHIP_MISMATCH`. List endpoints visible to growers are implicitly restricted to the caller's own records, and single-record reads visible to growers return the record only when it belongs to the caller.

When `X-User-Role` is `DealerAdmin`, `SalesRep`, `Agronomist`, or `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `filed_by_user_id` on a replant claim at filing time, or as `decided_by_user_id` when a claim is decided — but it is never compared to any entity's `id`.

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

### 2.3. Pagination, Filtering, and List Ordering

Every list endpoint accepts the query parameters `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and identifies how many records of the ordered result set are skipped before the page begins. List responses always report `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the size of the full filtered result set and `has_more` indicates whether records exist beyond the returned page.

Unless a more specific rule applies, list endpoints return records ordered by `created_at` ascending — oldest first. In addition to pagination, list endpoints accept filter query parameters scoped to the resource's natural keys: `status` (and, for orders, `payment_status`) filter by lifecycle state, while foreign-key filters such as `grower_id`, `program_id`, `field_id`, `variety_id`, `trait_package_id`, `order_id`, `order_line_id`, `treatment_option_id`, `inventory_lot_id`, `lot_id`, `delivery_ticket_id`, `recommendation_id`, `replacement_order_id`, `supersedes_agreement_id`, `supersedes_recommendation_id`, and `crop` narrow the collection to records referencing the supplied value. Each list endpoint supports the filter subset natural to its resource.

### 2.4. The Logical Clock

Every time-dependent rule in this system — window boundaries, agreement expiry, lot allocation eligibility, discount tier selection — is evaluated against a **logical clock** maintained by the server, never against wall-clock time. At startup, before any client intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`.

A test-driving capability lets a `DealerAdmin` advance the logical clock by supplying a `to_iso8601` instant; the capability responds with the resulting `current_utc` value. The clock is the single source of temporal truth: two requests evaluated at the same logical instant observe the same season posture regardless of when they physically arrive. Agreement expiry is lazy — a `TraitAgreement` whose `effective_to` has fallen behind the logical clock is treated as expired whenever the clock is consulted, and the season sweeps described in §3.9 perform the same expiry in bulk. Lot allocation eligibility likewise re-evaluates `expiry_date` against the logical clock at every allocation attempt.

### 2.5. Common Resource Properties

Every resource in this system carries a common set of server-managed properties. The `id` is a server-minted UUID with no type prefix — clients never supply it. The `created_at` timestamp records when the resource was created, and `updated_at` records when it was last mutated; both are ISO 8601 UTC timestamps rendered with three fractional digits. The `version` property is an integer that increments by one on every mutation of the resource and anchors the optimistic-concurrency rules of §2.7. Path parameters named `id` in §4 refer to these resource identifiers, and path hierarchies validate left to right: each `id` segment must resolve to an existing resource before the request proceeds.

### 2.6. Money, Basis Points, and Rounding Discipline

All monetary amounts are integers denominated in cents — fields ending in `_cents` or `_cents_per_unit` are never fractional. All percentage-like rates are integer **basis points**, where 10000 basis points equal 100 percent: a `discount_bps` of 1000 is a 10 percent discount, and a `replant_replacement_discount_bps` of 10000 means the replacement seed is free.

Whenever a money computation produces a fractional cent, the result is rounded half-up to zero decimal places (whole cents). One rounding rule is pinned and non-negotiable: when a discount applies to a per-unit price, the discounted **unit** price is rounded half-up to whole cents first, and only then multiplied by the number of units. Multiplying first and rounding the line total is a specification violation, because the two orders of operation diverge. The agronomic `placement_score` is the lone non-money computed quantity: it is rendered with one decimal place, also rounded half-up. Unit counts (seed units, acres affected, replacement units) are integers; the one fractional intermediate — replacement-unit sizing in §3.8 — resolves upward via a ceiling, the smallest integer greater than or equal to the raw quotient.

### 2.7. Optimistic Concurrency on Grower and Field Writes

Two write endpoints guard their parent aggregate with optimistic concurrency control; no other endpoint takes a version field.

A `POST /dealer/trait-agreements` request must carry `expected_grower_version` holding the caller's last observed `version` of the target `GrowerAccount`. If the grower's current `version` has advanced past the supplied value — for example because another writer has just created or signed an agreement for the same grower, legitimately superseding the prior active one — the create is rejected with `ERR_STALE_GROWER_VERSION` (HTTP 412), preventing the caller from writing on top of an agreement stack it has not observed. A successful create increments the grower's `version` by one.

A `POST /dealer/recommendations` request must likewise carry `expected_field_version` holding the caller's last observed `version` of the target `Field`. If the field's current `version` no longer matches — for example because another agronomist has just created a recommendation for the same field, and publishing would legitimately supersede the prior published one — the create is rejected with `ERR_STALE_FIELD_VERSION` (HTTP 412). A successful create increments the field's `version` by one.

### 2.8. Adjudication Order: How Conflicting Failures Are Reported

A single request can fail in several ways at once — an unauthenticated grower might reference a nonexistent order with a malformed body. The server does not collect failures; it evaluates checks in a fixed priority order and reports the **first** failure only. The order below is normative and applies everywhere.

**Priority 1 — user context.** The `X-User-ID` and `X-User-Role` headers must be present and non-empty on every request, otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). This check precedes everything else.

**Priority 2 — role authorization.** The caller's role must appear in the endpoint's authorized role list, otherwise `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). Applies to every endpoint.

**Priority 3 — grower ownership.** A `Grower` caller must own the target resource through its grower chain (§2.1), otherwise `ERR_GROWER_OWNERSHIP_MISMATCH` (HTTP 403). Applies to every grower-accessible non-list endpoint.

**Priority 4 — existence.** Every path identifier and every body foreign key must resolve to an existing resource, otherwise `ERR_NOT_FOUND` (HTTP 404). Applies to every endpoint.

**Priority 5 — request shape.** Required fields must be present, enum values must be members of their declared sets, integer quantities must be at least 1, acreage must be greater than zero, and unknown body fields are rejected — any violation yields `ERR_INVALID_REQUEST` (HTTP 400). Applies to every endpoint.

**Priority 6 — referential coherence.** Body references must agree with each other: an `order_line_id` must belong to the referenced `order_id` (otherwise `ERR_ORDER_LINE_MISMATCH`, HTTP 409); a `recommendation_id` on a new order must belong to the order's grower and be in a usable state (otherwise `ERR_RECOMMENDATION_MISMATCH`, HTTP 409); a claim's `field_id` must belong to the order's grower (otherwise `ERR_FIELD_GROWER_MISMATCH`, HTTP 409). This tier governs the creation of delivery tickets, returns, replant claims, and orders, and also the grower-level prepay-refund capability, where a refund naming an order that does not belong to the grower in the path surfaces as `ERR_NOT_FOUND` instead.

**Priority 7 — state legality.** The target resource must be in a state from which the requested transition exists (otherwise `ERR_INVALID_STATE_TRANSITION`, HTTP 409), and program posture gates sales operations: creating or confirming an order, and publishing or accepting a recommendation, all require the program to be `OPEN` (otherwise `ERR_PROGRAM_NOT_OPEN`, HTTP 409). Applies to all action endpoints.

**Priority 8 — optimistic concurrency.** On the two OCC-guarded creates of §2.7, the supplied expected version must equal the parent's current `version`, otherwise `ERR_STALE_GROWER_VERSION` or `ERR_STALE_FIELD_VERSION` (HTTP 412).

**Priority 9 — compliance and stewardship.** Traited seed requires an active in-window trait agreement for the grower and package (otherwise `ERR_TRAIT_AGREEMENT_NOT_ACTIVE`, HTTP 409); a claims adjuster must not be the claim's filer (otherwise `ERR_SEGREGATION_OF_DUTIES`, HTTP 403); agreement operations must respect the effective window (otherwise `ERR_AGREEMENT_EXPIRED`, HTTP 409). This tier governs order-line creation, order confirmation, order hold release, recommendation acceptance, agreement signing and reinstatement, and the claim start-review, request-info, approve, and deny actions.

**Priority 10 — temporal windows.** Prepay tier deadlines, the return window, the replant event window, the delivery scheduling window, and the rule that a delivery cannot complete before its scheduled date are evaluated here, surfacing `ERR_PREPAY_WINDOW_CLOSED`, `ERR_RETURN_WINDOW_CLOSED`, `ERR_REPLANT_WINDOW_CLOSED`, `ERR_DELIVERY_OUTSIDE_WINDOW`, or `ERR_DELIVERY_TOO_EARLY` (all HTTP 409). Applies to prepay, return creation, replant-claim creation, and delivery-ticket creation and completion.

**Priority 11 — capacity, availability, and structure.** Inventory allocation, daily delivery capacity, deliverable remainder, plot-window overlap, plot replication minimums, the requirement that an order have lines, catalog listing status, quarantine-with-no-reservations, treatment crop compatibility, returnable quantity, delivered-units-before-claim, and no-completed-deliveries-before-cancel all fail here, surfacing `ERR_INSUFFICIENT_INVENTORY`, `ERR_DELIVERY_CAPACITY_EXCEEDED`, `ERR_DELIVERY_EXCEEDS_REMAINING`, `ERR_PLOT_WINDOW_OVERLAP`, `ERR_INSUFFICIENT_PLOT_REPLICATIONS`, `ERR_ORDER_HAS_NO_LINES`, `ERR_VARIETY_DELISTED`, `ERR_VARIETY_HAS_OPEN_ORDERS`, `ERR_FIELD_HAS_ACTIVE_PLOTS`, `ERR_LOT_HAS_RESERVATIONS`, `ERR_TREATMENT_INCOMPATIBLE`, `ERR_RETURN_NOT_ALLOWED_TREATED`, `ERR_RETURN_QUANTITY_EXCEEDS`, `ERR_NOTHING_TO_RETURN`, `ERR_NO_DELIVERED_UNITS`, `ERR_ORDER_HAS_DELIVERIES`, or `ERR_GROWER_HAS_OPEN_ORDERS` (all HTTP 409). This tier spans confirmation, hold release, claim approval, delivery-ticket creation and completion, plot-trial creation and publication, line creation, variety delisting, field retirement, lot quarantine, return creation, order cancellation, and grower deactivation.

**Priority 12 — money.** Fiscal checks come last, so a cheaper failure never masks an expensive one: the grower's status must permit new exposure (`ERR_GROWER_NOT_ACTIVE`, HTTP 409), the credit limit must cover outstanding balance plus the order's net (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 409), a prepay amount must cover the post-discount net due (`ERR_PREPAY_AMOUNT_INSUFFICIENT`, HTTP 409), and a grower's ledger must be fully settled before deactivation (`ERR_GROWER_NOT_SETTLED`, HTTP 409). This tier governs order confirmation, prepay, agreement signing, and grower deactivation.

The practical consequence: a confirmation attempted against a closed program reports `ERR_PROGRAM_NOT_OPEN` even if the grower is also over their credit limit, and a compliance-hold rejection surfaces as `ERR_TRAIT_AGREEMENT_NOT_ACTIVE` rather than being masked by a later capacity or money check.

### 2.9. Conservation Ledgers for Cash and Seed

Two quantities in this system are conserved and may be audited at any moment.

The first is prepaid cash. A grower's `prepay_balance_cents` always equals the sum of all prepay amounts collected, minus the sum of all refunded prepay amounts, minus the sum of all prepay applications performed when prepaid orders settle. Prepaying adds to the balance; an administrator-initiated prepay refund subtracts the order's prepaid amount; settling a prepaid order applies the order's net against the balance. Cash that was prepaid above an order's net due stays in the balance unapplied until a refund or a settlement consumes it.

The second is seed. For every inventory lot, `received_units` plus `returned_units` always equals `on_hand_units` plus `delivered_units` plus `written_off_units`. Reservations (`reserved_units`) are a subset of on-hand units — they earmark physical seed without moving it out of the warehouse — so reservation and release never disturb the identity; only deliveries, physical restocks, and expiry write-offs do.

A grower's `outstanding_balance_cents` is not required to stay non-negative: invoicing adds an order's net, payments subtract, and credited returns subtract further, so a sufficiently large credit pushes the balance negative, which represents a refund owed to the grower.

### 2.10. Season Calendar Windows

Each program carries its own calendar, fixed at creation, and every window is evaluated against the logical clock. `delivery_window_start` and `delivery_window_end` bracket the inclusive interval in which delivery and pickup tickets may be scheduled. `return_window_end` is the inclusive last instant at which a return may be requested — a request landing exactly at that instant is still admissible. `replant_claim_window_days` defines the inclusive filing deadline for replant claims: a claim must be filed no later than that many days after its `event_date`, with the boundary day itself still fileable. `sales_close_at` is the earliest instant at which the selling season may be closed. Settlement additionally requires the clock to be strictly past `return_window_end`, so the return window must have fully closed before the books freeze.

## 3. Business Logic & Workflows

### 3.1. Building the Season: Programs, Catalog, and Pricing Tiers

Everything starts with a `DealerAdmin` creating a seed program. The administrator supplies the program's display `name` and the `crop_year` it sells into, then fixes the season's commercial machinery: the `early_order_tiers`, an ascending-by-cutoff list in which each tier pairs a `cutoff_at` instant with a `discount_bps` rate so that an order confirmed at or before a cutoff earns that tier; the optional `prepay_tiers`, each pairing a `pay_by` deadline with a `discount_bps` so prepayment at or before the deadline earns that rate (defaulting to an empty list); and the optional `volume_rebate_tiers`, each pairing a `min_units` threshold with a `rebate_bps` applied against the order's total units (also defaulting to empty). Policy and logistics come next: `return_window_end`, `return_restocking_bps` (the restocking fee, in basis points of the returned merchandise value), the `returns_untreated_only` flag restricting returns to untreated lines when set, `replant_claim_window_days`, `replant_replacement_discount_bps`, `daily_delivery_capacity_units`, `delivery_window_start`, `delivery_window_end`, and `sales_close_at`. Finally the administrator fixes dealer compensation — `commission_base_bps` and an optional `commission_volume_tiers` list pairing `min_net_units` with a `bonus_bps` — and the agronomic gate `min_plot_replications`. A new program is born in `DRAFT`.

Opening the program is a deliberate act with two structural preconditions, both enforced as `ERR_INVALID_REQUEST`: the `early_order_tiers` list must be non-empty and sorted ascending by `cutoff_at`, and `return_window_end` must be strictly later than `delivery_window_end` so the return window outlives the last possible delivery. On success the program moves `DRAFT → OPEN`, `opened_at` records the logical clock, and exactly one `CommissionStatement` is created for the program in `ACCRUING` status with every computed amount at zero — the accrual ledger that will shadow the season until settlement.

The catalog lives alongside the program. A trait package is created with a unique `code`, a free-text `description`, the `requires_stewardship_agreement` flag that gates every downstream sale of traited seed, and `refuge_required_bps`, the refuge-acreage requirement in basis points that stewardship programs impose; packages begin `LISTED` and may later be retired `LISTED → RETIRED`, which leaves existing active agreements untouched. A variety is created with a unique `sku`, a `crop` of `CORN` or `SOYBEAN`, its `relative_maturity_days`, an optional `trait_package_id` (absent means a conventional untraited variety), the `base_price_cents_per_unit` list price, `seeds_per_unit`, the `preferred_soils` it is bred for (a subset of `CLAY`, `LOAM`, `SAND`, `SILT`), and `min_drainage`, the minimum drainage class it tolerates. Varieties begin `LISTED`; delisting moves one `LISTED → DELISTED` but is blocked with `ERR_VARIETY_HAS_OPEN_ORDERS` while any order line references the variety inside an order that is `DRAFT`, `CONFIRMED`, or `COMPLIANCE_HOLD`. A treatment option — a fungicide-plus-insecticide package or similar — is created with a unique `code`, the `crop` it applies to, and `adder_cents_per_unit`, a per-unit price adder that is never discounted by early-order or prepay tiers; options begin `AVAILABLE` and may be discontinued `AVAILABLE → DISCONTINUED`, leaving existing lots and order lines unaffected.

### 3.2. Growers, Fields, and Credit Posture

A `DealerAdmin` or `SalesRep` onboards a farm operation by creating a grower account with its `account_name`, the dealer's own `external_ref` customer reference, and a `credit_limit_cents` capping outstanding exposure. New accounts begin `ACTIVE` with both ledger balances — `outstanding_balance_cents` and `prepay_balance_cents` — at zero. The outstanding balance tracks invoiced-but-unpaid net amounts minus payments minus applied return credits, and may go negative when credits exceed invoicing (a refund owed); the prepay balance holds unapplied prepayment cash under the conservation rule of §2.9.

Credit posture is managed explicitly. Placing a hold moves an account `ACTIVE → CREDIT_HOLD`; existing confirmed orders are unaffected — the hold only gates new exposure through the money checks of §2.8. Releasing the hold returns the account `CREDIT_HOLD → ACTIVE`. Deactivation is the terminal exit `ACTIVE → INACTIVE` and carries two gates evaluated under the adjudication order: no order of the grower may be in `DRAFT`, `CONFIRMED`, or `COMPLIANCE_HOLD` (otherwise `ERR_GROWER_HAS_OPEN_ORDERS`), and both balances must be exactly zero — `outstanding_balance_cents` and `prepay_balance_cents` alike — otherwise `ERR_GROWER_NOT_SETTLED`.

Fields are the agronomic substrate. A `DealerAdmin`, `SalesRep`, or the `Grower` personally creates a field with its owning `grower_id` (a grower caller must pass their own id), a display `name`, its size in `acres` (strictly greater than zero), the `soil_type` (`CLAY`, `LOAM`, `SAND`, or `SILT`), a `drainage` class of `POOR`, `MODERATE`, or `WELL` (ranked 1, 2, and 3 respectively wherever comparisons are needed), whether it is `irrigated`, the `prev_crop` that occupied it last season (`CORN`, `SOYBEAN`, `WHEAT`, `FALLOW`, or `OTHER`), and its `maturity_zone`, an integer from 1 to 13 where zone x targets varieties near ten-times-x relative-maturity days. Fields begin `ACTIVE`; retirement moves a field `ACTIVE → RETIRED` and is available to administrators and sales representatives, but is blocked with `ERR_FIELD_HAS_ACTIVE_PLOTS` while any plot trial on the field is `PLANNED` or `PLANTED`.

### 3.3. Trait Licensing and Stewardship Compliance

Before traited seed can change hands, the grower must hold a trait/technology agreement. A `DealerAdmin` or `SalesRep` creates one by naming the licensed `grower_id`, the `trait_package_id`, and the inclusive license window `effective_from` through `effective_to`; the create is OCC-guarded on the grower's version per §2.7 and increments that version on success. New agreements begin `PENDING_SIGNATURE`.

Signing activates the license and may be performed by a `DealerAdmin` or by the `Grower`. Four preconditions guard the transition `PENDING_SIGNATURE → ACTIVE`: a grower signs only their own agreements, with an ownership mismatch rejected as `ERR_GROWER_OWNERSHIP_MISMATCH`; the logical clock must lie within the inclusive window from `effective_from` to `effective_to` (otherwise `ERR_AGREEMENT_EXPIRED`); the referenced trait package must still be `LISTED` (otherwise `ERR_INVALID_STATE_TRANSITION`); and the grower account must be `ACTIVE` (otherwise `ERR_GROWER_NOT_ACTIVE`). On signing, `signed_at` records the logical clock, and if another agreement for the same grower-and-package pair is currently `ACTIVE`, that prior agreement is pushed to `SUPERSEDED` while the new agreement's `supersedes_agreement_id` records which agreement it replaced.

Stewardship enforcement runs the other way. An administrator may suspend an active agreement, moving it `ACTIVE → SUSPENDED` and recording the request's `reason` — one of `STEWARDSHIP_VIOLATION` or `PAPERWORK` — into `suspension_reason`. Suspension detonates a four-link cascade. First, every seed order whose `grower_id` matches the agreement's grower, whose status is `CONFIRMED`, and which contains at least one line whose variety carries the agreement's trait package moves to `COMPLIANCE_HOLD`. Second, each such order releases every line reservation: the line's `inventory_lot_id` is cleared, the lot's `reserved_units` is decremented by the line's `reserved_units`, and the line's `reserved_units` falls to zero. Third, every lot touched by that release recomputes its status, so a `DEPLETED` lot whose `on_hand_units` is again positive returns to `AVAILABLE`. Fourth, on the commission ledger, held orders leave the provisional inclusion set, so the next statement recompute drops their net amounts and units from the accrual.

Reinstatement moves a suspended agreement `SUSPENDED → ACTIVE`, requires the logical clock to be no later than `effective_to` (otherwise `ERR_AGREEMENT_EXPIRED`), and clears `suspension_reason`. Reinstatement deliberately does **not** release held orders: each held order must be released individually through the order-level hold release described in §3.5, which re-verifies stewardship and re-runs inventory allocation. Revocation is terminal: from `ACTIVE`, revoking an agreement moves it to `REVOKED` and triggers the same order-hold cascade as suspension; from `SUSPENDED`, revoking simply moves the already-quiet agreement to `REVOKED` with no further cascade. Expiry is the system-driven exit — whenever the logical clock advances past an agreement's `effective_to`, and in bulk during the sales-close and settlement sweeps, an agreement in `ACTIVE` or `SUSPENDED` moves to `EXPIRED`.

The commercial teeth of all this: whenever seed of a variety whose trait package has `requires_stewardship_agreement` set is sold or endorsed — adding the line to an order, confirming the order, releasing a held order, or accepting a recommendation for the variety — an `ACTIVE` agreement for the grower-and-package pair must exist with the logical clock inside its window, otherwise the operation is rejected with `ERR_TRAIT_AGREEMENT_NOT_ACTIVE`.

### 3.4. Agronomy: Placement Recommendations and Plot Trials

An `Agronomist` drafts a placement recommendation by naming the target `field_id`, the recommended `variety_id`, the `program_id` the recommendation sells into, the `seeding_rate_seeds_per_acre`, and an `expected_yield_index` where 100 represents the program average. The create is OCC-guarded on the field's version per §2.7 and increments that version on success; the recommendation's `grower_id` is denormalized from the field's owning grower at creation, and its `placement_score` is computed immediately. New recommendations begin `DRAFT`.

The placement score is a weighted fit on a 0–100 scale built from four factors. Soil match contributes a factor of 1 when the field's `soil_type` appears in the variety's `preferred_soils`, and 0.5 otherwise. Drainage match contributes 1 when the field's `drainage` rank (POOR = 1, MODERATE = 2, WELL = 3) is at least the variety's `min_drainage` rank, and 0 otherwise. Maturity fit measures the gap between the variety's `relative_maturity_days` and ten times the field's `maturity_zone`: a gap of five days or fewer contributes 1, a gap greater than five but no more than fifteen contributes 0.5, and a larger gap contributes 0. Rotation bonus contributes 1 when the field's `prev_crop` differs from the variety's `crop`, and 0 otherwise. The score is one hundred times the weighted sum — soil weighted 0.35, drainage 0.25, maturity 0.25, rotation 0.15 — rounded half-up to one decimal place. It is computed at creation and recomputed when the recommendation is published.

Publishing is the `DRAFT → PUBLISHED` step and requires the program to be `OPEN` (otherwise `ERR_PROGRAM_NOT_OPEN`) and the field to be `ACTIVE` (otherwise `ERR_INVALID_STATE_TRANSITION`); `published_at` records the logical clock. Publication enforces one-live-recommendation semantics: if another recommendation for the same field-and-program pair is currently `PUBLISHED`, it moves to `SUPERSEDED` and the new recommendation's `supersedes_recommendation_id` records which one it displaced. Acceptance is the grower's move — `PUBLISHED → ACCEPTED`, grower callers only, on their own recommendations (`ERR_GROWER_OWNERSHIP_MISMATCH`), again requiring the program `OPEN` and, when the variety carries a stewardship-gated trait package, an active in-window agreement (`ERR_TRAIT_AGREEMENT_NOT_ACTIVE`); `decided_at` records the instant. Withdrawal by an `Agronomist` or `DealerAdmin` moves a `DRAFT` or `PUBLISHED` recommendation to `WITHDRAWN`, likewise stamping `decided_at`. And when the selling season closes, every recommendation of that program still sitting in `DRAFT` or `PUBLISHED` is swept to `EXPIRED` — accepted ones survive, because acceptance is the grower's commitment.

Plot trials are the evidence base. An `Agronomist` plans a trial with its `program_id`, `variety_id`, host `field_id`, a `planting_date`, an `expected_harvest_date` that must be strictly later than the planting date (otherwise `ERR_INVALID_REQUEST`), and a `replication_index` numbering this trial within its program-and-variety group. Each trial occupies a half-open interval on its field — inclusive of `planting_date`, exclusive of `expected_harvest_date` — and planning is rejected with `ERR_PLOT_WINDOW_OVERLAP` if that interval overlaps the occupancy interval of another trial on the same field that is `PLANNED`, `PLANTED`, or `HARVESTED`. New trials begin `PLANNED`.

Field execution walks the trial forward: recording planting moves `PLANNED → PLANTED`; recording harvest captures the measured `yield_bu_per_acre` and `moisture_pct`, stamps `actual_harvest_date` with the logical clock, and moves `PLANTED → HARVESTED`. Publication — available to both `Agronomist` and `DealerAdmin` — is where the replication gate bites: the count of trials for the same program-and-variety pair that are `HARVESTED` or `PUBLISHED`, this trial included, must be at least the program's `min_plot_replications`, otherwise `ERR_INSUFFICIENT_PLOT_REPLICATIONS`; success moves the trial `HARVESTED → PUBLISHED` and its yield results become quotable in marketing. Discarding abandons a `PLANNED` or `PLANTED` trial, moving it to `DISCARDED` and freeing the field's occupancy interval for future plans.

### 3.5. Selling Seed: Orders, Lines, and Confirmation

A seed order is three things at once, and the three evolve independently: a lifecycle `status` (`DRAFT`, `CONFIRMED`, `COMPLIANCE_HOLD`, `CLOSED`, `CANCELLED`), a parallel money dimension `payment_status` (`UNPAID`, `PREPAID`, `INVOICED`, `SETTLED`), and a computed fulfillment dimension `fulfillment_status` (`NONE`, `PARTIAL`, `DELIVERED`, `RETURNED_PARTIAL`, `RETURNED_FULL`) derived entirely from line delivery and return counters per §3.7.

A `DealerAdmin`, `SalesRep`, or `Grower` creates an order by naming the buying `grower_id` (growers create only their own), the selling `program_id`, and optionally a `recommendation_id` when the order follows an agronomist's guidance — the recommendation must belong to the same grower and be `PUBLISHED` or `ACCEPTED`, otherwise `ERR_RECOMMENDATION_MISMATCH`. The program must be `OPEN` for selling (otherwise `ERR_PROGRAM_NOT_OPEN`). New orders begin in `DRAFT` with `payment_status` `UNPAID`, `fulfillment_status` `NONE`, all monetary amounts at zero, and `is_replacement` false — that flag is set only by the replant machinery of §3.8.

Lines are added to a `DRAFT` order one at a time by an administrator, sales rep, or the grower; attempting to add to an order in any other status fails as `ERR_INVALID_STATE_TRANSITION`. Each line names a `variety_id`, a `units` quantity of at least one, and an optional `treatment_option_id` (absent means untreated seed). Three catalog rules bite at line creation: the variety must be `LISTED` (`ERR_VARIETY_DELISTED`), the treatment — when present — must be `AVAILABLE` and must target the same `crop` as the variety (`ERR_TREATMENT_INCOMPATIBLE`), and the stewardship gate of §3.3 applies to traited varieties (`ERR_TRAIT_AGREEMENT_NOT_ACTIVE`). At creation the line snapshots the variety's list price into `unit_price_cents`, computes a pre-confirmation estimate of `line_total_cents` as the list price times units plus any treatment adder times units (that is, at a locked discount of zero), and the order's totals recompute from its lines.

Confirmation is the pricing event, available to `SalesRep` and `Grower`, and it enforces its six gates under the adjudication order of §2.8: the order must contain at least one line (`ERR_ORDER_HAS_NO_LINES`); the program must be `OPEN` (`ERR_PROGRAM_NOT_OPEN`); every traited line must pass the stewardship gate (`ERR_TRAIT_AGREEMENT_NOT_ACTIVE`); inventory allocation must succeed for every line (`ERR_INSUFFICIENT_INVENTORY`); the grower must be `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`); and the grower's `outstanding_balance_cents` plus the order's net amount — gross less the volume rebate — must not exceed `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`).

On success, confirmation locks the season's pricing onto the order. The `locked_discount_bps` is chosen by the early-order rule: replacement orders take the program's `replant_replacement_discount_bps` outright; otherwise, orders smaller than 20 total units earn nothing; otherwise the tiers are walked in ascending `cutoff_at` order and the first tier whose cutoff is at or after the confirmation instant wins — the boundary is inclusive — and if the clock has passed every cutoff the discount is zero. Each line's `discounted_unit_price_cents` is then the list price multiplied by the complement of the locked discount (ten thousand minus `locked_discount_bps`, over ten thousand), rounded half-up to whole cents **per unit before any multiplication by units**; the line's `line_total_cents` becomes that discounted unit price times `units` plus the treatment adder times `units`, with the adder never discounted. Order totals follow: `total_units` is the sum of line units; `gross_amount_cents` is the sum of line totals; `rebate_bps_applied` is zero for replacement orders and otherwise the largest `rebate_bps` among volume-rebate tiers whose `min_units` the order's `total_units` meets or exceeds (zero when none qualify); `rebate_amount_cents` is that rate applied to the gross, rounded half-up to whole cents; and `net_amount_cents` is gross minus rebate minus any `prepay_discount_cents` (zero at confirmation). The confirmation instant is stamped into `confirmed_at`, and the order's lifecycle moves `DRAFT → CONFIRMED`.

Inventory allocation is confirmation's physical half, and the same selector runs at confirmation, at hold release, and inside replant approval. A lot is eligible for a line when its `variety_id` equals the line's, its `treatment_option_id` equals the line's (an untreated line matches only untreated lots, null to null), its status is `AVAILABLE`, its `expiry_date` is strictly later than the logical clock, and its unreserved remainder — `on_hand_units` minus `reserved_units` — covers the line's full `units`: a single lot must cover the whole line, and splitting across lots is never performed. Eligible lots are ranked by earliest `expiry_date` first (first-expiry, first-out), with ties broken by earliest `created_at` — never by id — and the first lot in that ranking is selected. An empty eligible pool fails the operation with `ERR_INSUFFICIENT_INVENTORY`. Selection reserves: the lot's `reserved_units` grows by the line's units, the line's `reserved_units` records them, and the line's `inventory_lot_id` points at the chosen lot.

Cancellation unwinds by stage. A `DRAFT` order cancels directly to `CANCELLED`. A `CONFIRMED` order may cancel only while no delivery ticket of the order has reached `COMPLETED` (otherwise `ERR_ORDER_HAS_DELIVERIES`); cancelling releases every line reservation back to its lot, cancels any of the order's tickets still `SCHEDULED`, and — if the order was `PREPAID` — unwinds the prepayment: `payment_status` returns to `UNPAID`, `prepaid_amount_cents` and `prepay_discount_cents` zero out, the net reverts to gross minus rebate, and the cash itself remains in the grower's `prepay_balance_cents`, unapplied — and the order moves `CONFIRMED → CANCELLED`. A `COMPLIANCE_HOLD` order cancels straight to `CANCELLED`, its reservations having already been released by the hold cascade. In all three paths a `Grower` caller may cancel only their own orders (`ERR_GROWER_OWNERSHIP_MISMATCH`); administrators and sales reps cancel freely.

Hold release is the counterpart to the §3.3 cascade: an administrator releasing a held order re-verifies the stewardship gate for every traited line (`ERR_TRAIT_AGREEMENT_NOT_ACTIVE`) and re-runs the allocation selector for every line (`ERR_INSUFFICIENT_INVENTORY`) — fresh lot selection is allowed, since the original reservation was destroyed — before the order returns `COMPLIANCE_HOLD → CONFIRMED`. Orders arrive at `COMPLIANCE_HOLD` only through that cascade; there is no user-driven hold action on orders.

### 3.6. Money Movement: Prepay, Invoicing, and Payment Collection

Prepayment lets a confirmed order capture an extra discount. A `SalesRep` or the owning `Grower` prepays by supplying `amount_cents`; the order must be `CONFIRMED` with `payment_status` `UNPAID` (otherwise `ERR_INVALID_STATE_TRANSITION`), and a grower prepays only their own orders. The computation follows a pinned evaluation order that resolves an apparent circularity — the discount is computed on the pre-prepay net, never on the amount paid, and qualification compares the payment against the post-discount amount due. First, the net before prepay is the order's `gross_amount_cents` minus its `rebate_amount_cents`. Second, the system selects the prepay tier with the largest `discount_bps` among tiers whose `pay_by` is at or after the logical clock; if no such tier remains, the request fails with `ERR_PREPAY_WINDOW_CLOSED`. Third, the `prepay_discount_cents` is that rate applied to the pre-prepay net, rounded half-up to whole cents. Fourth, the net due is the pre-prepay net minus the discount. Fifth, the supplied `amount_cents` must be at least the net due, otherwise `ERR_PREPAY_AMOUNT_INSUFFICIENT`. Sixth, the order's `net_amount_cents` becomes the net due, `prepaid_amount_cents` records the amount actually paid, the grower's `prepay_balance_cents` grows by that amount — any excess over the net due staying unapplied cash in the balance — and the payment dimension moves `UNPAID → PREPAID`.

Refunding a prepayment is a `DealerAdmin`-only act performed at the grower level, naming the `order_id` to unwind. The named order must belong to the grower addressed in the path, otherwise the request surfaces `ERR_NOT_FOUND`. The refund subtracts the order's `prepaid_amount_cents` from the grower's `prepay_balance_cents`, zeroes the order's `prepaid_amount_cents` and `prepay_discount_cents`, restores `net_amount_cents` to gross minus rebate, and returns the payment dimension `PREPAID → UNPAID`.

Invoicing is never a per-order user action: it arrives with the sales-close sweep of §3.9, which moves every still-`UNPAID` confirmed order of the program to `INVOICED` and adds each such order's `net_amount_cents` to its grower's `outstanding_balance_cents`. Collection then proceeds against the grower's ledger: recording a payment, available to `DealerAdmin` and `SalesRep` with an `amount_cents` of at least one (otherwise `ERR_INVALID_REQUEST`), requires the order to be `CONFIRMED` or `CLOSED` (otherwise `ERR_INVALID_STATE_TRANSITION`), adds the amount to the order's `paid_amount_cents`, subtracts it from the grower's `outstanding_balance_cents`, and — once `paid_amount_cents` reaches or exceeds `net_amount_cents` — moves the payment dimension `INVOICED → SETTLED`. Prepaid orders settle differently: the settlement sweep applies their `net_amount_cents` against the grower's `prepay_balance_cents` and moves them `PREPAID → SETTLED` without any cash changing hands at that point.

### 3.7. Fulfillment: Delivery Scheduling, Completion, and Returns

Seed physically moves on delivery tickets. A `DealerAdmin` or `SalesRep` schedules one against a `CONFIRMED` order by naming the `order_id` and a specific `order_line_id` within it — a line belonging to a different order is rejected as `ERR_ORDER_LINE_MISMATCH` — plus the movement `type` (`DELIVERY` or `PICKUP`), the `scheduled_date`, and the `units` to move, at least one. Scheduling is fenced by three rules evaluated under the adjudication order: the scheduled instant must lie within the inclusive interval from `delivery_window_start` to `delivery_window_end` (otherwise `ERR_DELIVERY_OUTSIDE_WINDOW`); the program's daily load must absorb it — summing the units of all the program's tickets, `SCHEDULED` or `COMPLETED`, whose scheduled instants share the same UTC calendar date as the new ticket, that load plus the new units must not exceed `daily_delivery_capacity_units`, with a load landing exactly at capacity still allowed (otherwise `ERR_DELIVERY_CAPACITY_EXCEEDED`); and the ticket's units must not exceed the line's deliverable remainder — `reserved_units` minus `delivered_units` minus the units already sitting on the line's still-scheduled tickets (otherwise `ERR_DELIVERY_EXCEEDS_REMAINING`). A new ticket begins `SCHEDULED`, and its `lot_id` is copied from the line's reserved `inventory_lot_id` at creation.

Completion, by an administrator or sales rep, requires the logical clock to have reached the `scheduled_date` — completing early fails with `ERR_DELIVERY_TOO_EARLY` — and the parent order to be `CONFIRMED` (otherwise `ERR_INVALID_STATE_TRANSITION`). Completion moves the ticket `SCHEDULED → COMPLETED`, stamps `completed_at`, and moves physical seed: on the lot, `reserved_units` and `on_hand_units` each fall by the ticket's units while `delivered_units` grows; on the line, `reserved_units` falls and `delivered_units` grows; the lot's status is recomputed, becoming `DEPLETED` when its on-hand reaches zero; and the order's `fulfillment_status` is recomputed. Cancelling a still-scheduled ticket — also an administrator or sales-rep action, or a cascade from order cancellation — moves it `SCHEDULED → CANCELLED` and deliberately leaves the reservation in place: only order-level cancellation releases reservations.

The fulfillment dimension derives from the lines, nothing else. An order is `NONE` when every line has zero delivered and zero returned units; `PARTIAL` when some but not all ordered units have been delivered and nothing has been returned; `DELIVERED` when every line's `delivered_units` equals its `units` with nothing returned; `RETURNED_PARTIAL` when some line has `returned_units` above zero but not all delivered units have come back; and `RETURNED_FULL` when every line with any deliveries has its `returned_units` equal to its `delivered_units` and at least one return has occurred.

Returns run a four-stage pipeline. A `SalesRep` or the owning `Grower` requests a return naming the `order_id`, the `order_line_id` within it (`ERR_ORDER_LINE_MISMATCH` on mismatch), the `units` coming back, a `reason` of `OVERSTOCK`, `WRONG_HYBRID`, `DAMAGED`, or `OTHER`, and optionally a `delivery_ticket_id` as proof of delivery. The request must land no later than the program's `return_window_end` — the boundary instant itself is admissible — otherwise `ERR_RETURN_WINDOW_CLOSED`. When the program sets `returns_untreated_only`, a line carrying a treatment option is not returnable at all (`ERR_RETURN_NOT_ALLOWED_TREATED`). Quantity rules compare against the line's returnable remainder — delivered units minus units already credited back minus units tied up in still-in-flight returns: when that remainder is zero the request fails with `ERR_NOTHING_TO_RETURN`, and when the requested units exceed it the request fails with `ERR_RETURN_QUANTITY_EXCEEDS`. A new return begins `REQUESTED` with `requested_at` stamped from the logical clock.

Approval, by an administrator or sales rep, moves the return `REQUESTED → APPROVED` and computes the provisional economics: the fee base is the returned units times the line's `discounted_unit_price_cents`; `restocking_fee_cents` is the program's `return_restocking_bps` applied to that base, rounded half-up to whole cents; and `credit_estimate_cents` is the fee base minus the restocking fee — a locked per-unit estimate that ignores any volume-rebate consequences. Physical receipt, again administrator or sales rep, moves `APPROVED → RECEIVED` and restocks the lot when the seed is resalable — that is, when the reason is anything other than `DAMAGED` and the lot is not `EXPIRED`: the lot's `on_hand_units` and `returned_units` each grow by the returned units, and a `DEPLETED` lot with on-hand again positive recomputes back to `AVAILABLE`.

Crediting is the fiscal act, reserved for `DealerAdmin`, and moves `RECEIVED → CREDITED`. The final `credit_cents` reprices the whole order as if the returned units had never been bought: the order's totals are recomputed with the line's units reduced by the returned units — re-selecting the volume rebate tier against the post-return `total_units` while the locked prepay discount stays fixed and excluded from both sides — and the credit equals the drop in the order's gross-minus-rebate, minus the same restocking fee computed at approval. The two variants coincide only when the rebate tier survives the return; when the lost units drop the order into a lower tier, the final credit is smaller than the estimate. Crediting then adds the units to the line's `returned_units`, subtracts `credit_cents` from the grower's `outstanding_balance_cents` (which may push it negative — a refund owed), recomputes the order's `fulfillment_status`, and marks the program's commission statement stale so the next recompute reflects the credit. Rejection is the other exit: an administrator or sales rep may reject a `REQUESTED` or `APPROVED` return, moving it to `REJECTED` and recording the request's `note` into `reject_note`.

Inventory lots themselves carry a small lifecycle. Lots are received with a `variety_id`, an optional `treatment_option_id` (untreated lots carry none), the `warehouse_code`, the `received_units` taken in, and an `expiry_date`; a fresh lot starts `AVAILABLE` with `on_hand_units` equal to `received_units` and `reserved_units`, `delivered_units`, `returned_units`, and `written_off_units` all at zero. An administrator may quarantine an `AVAILABLE` lot — but only while its `reserved_units` is zero, otherwise `ERR_LOT_HAS_RESERVATIONS` — moving it `AVAILABLE → QUARANTINED`; releasing quarantine returns it `QUARANTINED → AVAILABLE`. Depletion is system-driven: whenever a delivery completion drives `on_hand_units` to zero, the lot moves `AVAILABLE → DEPLETED`. Expiry arrives at settlement: a lot in `AVAILABLE` or `QUARANTINED` whose `expiry_date` has fallen behind the logical clock, with units still on hand, is written off — its `written_off_units` grows by the remaining `on_hand_units`, `on_hand_units` zeroes, and the lot moves to `EXPIRED`.

### 3.8. Replant Claims and Replacement Orders

When a stand fails, a `SalesRep`, the owning `Grower`, or even a `ClaimsAdjuster` files a replant claim naming the original `order_id`, the failed `order_line_id` (which must belong to that order, otherwise `ERR_ORDER_LINE_MISMATCH`), the `field_id` where the stand failed (which must belong to the order's grower, otherwise `ERR_FIELD_GROWER_MISMATCH`), the `event_date` of the damaging event, the `event_type` (`FROST`, `FLOOD`, `HAIL`, `DROUGHT`, or `PEST`), and the `acres_affected`. The event may not lie in the future relative to the logical clock, and the claim must be filed no later than `replant_claim_window_days` days after the event — the boundary day itself remains fileable — otherwise `ERR_REPLANT_WINDOW_CLOSED`. The claimed acreage must be greater than zero and no more than the host field's recorded `acres`, otherwise `ERR_INVALID_REQUEST`. And there must be something to replant: the claimed line must hold delivered, unreturned units, otherwise `ERR_NO_DELIVERED_UNITS`. A filed claim begins `FILED` with `filed_by_user_id` recording the caller's `X-User-ID` — the anchor for segregation of duties.

Review is adjuster territory, fenced by segregation: starting review (`FILED → UNDER_REVIEW`), requesting more information (`UNDER_REVIEW → INFO_REQUESTED`), approving, and denying all require that the acting adjuster's `X-User-ID` differ from the claim's `filed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The filer side answers an information request — a sales rep, the grower (on claims for their own orders only, otherwise `ERR_GROWER_OWNERSHIP_MISMATCH`), or an adjuster — moving the claim `INFO_REQUESTED → UNDER_REVIEW`; the loop may repeat as often as needed.

Approval is where replacement seed is born. Beyond segregation, the adjuster's approval requires that replacement inventory actually allocate under the §3.5 selector, otherwise `ERR_INSUFFICIENT_INVENTORY`. On success the claim moves `UNDER_REVIEW → APPROVED` with `decided_by_user_id` and `decided_at` recorded, and a four-link cascade fires: a replacement `SeedOrder` is created with `grower_id` and `program_id` copied from the original order, `is_replacement` set true, and `status` placed directly into `CONFIRMED`, bypassing `DRAFT`; the replacement carries one line per claimed line with the same variety, no treatment, and units sized as the smaller of two bounds — the claimed `acres_affected` times the original line's `units` divided by the field's `acres`, rounded up to a whole unit, and the line's delivered-not-returned remainder (`delivered_units` minus `returned_units`); the replacement order's confirmation reserves inventory through the same selector, setting each line's `inventory_lot_id` and `reserved_units` and growing the lot's `reserved_units`; and the replacement's `payment_status` lands directly on `SETTLED` when its `net_amount_cents` is zero, otherwise on `UNPAID`. Replacement pricing follows the general rules with two exceptions already stated: the locked discount is the program's `replant_replacement_discount_bps` in place of any early-order tier, and replacement orders earn no volume rebate. The claim's `replacement_order_id` records the created order.

Denial moves `UNDER_REVIEW → DENIED`, recording the request's `denial_reason` alongside `decided_by_user_id` and `decided_at`. Withdrawal is the filer side's exit — a sales rep, or the grower for their own orders' claims — moving a claim from `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED` to `WITHDRAWN`.

### 3.9. Season Closeout: Sales Close, Settlement, and Dealer Commission

Closing sales is the season's first ops-run checkpoint, a `DealerAdmin` action requiring the logical clock to have reached the program's `sales_close_at` (otherwise `ERR_INVALID_STATE_TRANSITION`). The transition `OPEN → SALES_CLOSED` stamps `sales_closed_at` and runs a four-part sweep: every order of the program still in `DRAFT` moves to `CANCELLED` (no reservations ever existed on drafts); every confirmed order still `UNPAID` moves its payment dimension to `INVOICED` and adds its `net_amount_cents` to the grower's `outstanding_balance_cents`; every recommendation of the program in `DRAFT` or `PUBLISHED` moves to `EXPIRED`; and every trait agreement whose `effective_to` has fallen behind the clock, whether `ACTIVE` or `SUSPENDED`, moves to `EXPIRED`.

Settlement is the second checkpoint and the program's terminal move `SALES_CLOSED → SETTLED`. Four preconditions guard it, all surfacing `ERR_PROGRAM_NOT_SETTLABLE`: the logical clock must be strictly later than `return_window_end`; no order of the program may sit in `COMPLIANCE_HOLD`; no replant claim on the program's orders may sit in `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED`; and no delivery ticket on the program's orders may remain `SCHEDULED`. The settle sweep then closes the books: every `CONFIRMED` order of the program moves to `CLOSED`; each closed order that was `PREPAID` applies its prepayment, subtracting `net_amount_cents` from the grower's `prepay_balance_cents` and moving its payment dimension to `SETTLED`; orders standing `INVOICED` stay `INVOICED`, with post-season collection continuing against the grower's outstanding balance through payment recording; every expired lot with units on hand is written off per §3.7; the program's commission statement is finalized as described below; and `settled_at` records the instant.

Dealer commission accrues on the single statement created when the program opened. While the statement is `ACCRUING`, an administrator may recompute it at will — a no-op transition `ACCRUING → ACCRUING` that refreshes the **provisional** variant; recomputation is a state-gated action, so a statement already `FINALIZED` or `PAID` rejects it with `ERR_INVALID_STATE_TRANSITION`. Both variants share one skeleton: the inclusion set is the program's orders in `CONFIRMED` or `CLOSED`; `gross_sales_cents` sums their `net_amount_cents`; `return_credits_cents` sums the `credit_cents` of `CREDITED` returns on those orders; `net_sales_cents` is gross sales minus return credits; `base_commission_cents` is the program's `commission_base_bps` applied to net sales, rounded half-up to whole cents; `volume_bonus_bps` is the largest `bonus_bps` among commission volume tiers whose `min_net_units` the statement's `volume_units` meets or exceeds (zero when none qualify); `volume_bonus_cents` is that rate applied to net sales, rounded half-up; and `total_commission_cents` is base plus bonus.

The variants diverge only in the unit tally. `volume_units` counts the included orders' `total_units` minus the units of `CREDITED` returns on them; the provisional variant — used while the program is `OPEN` or `SALES_CLOSED` — lets replacement-order units count toward the tally, while the final variant, computed at settlement, excludes replacement-order units entirely. Net sales are computed identically in both variants, so the divergence matters exactly when a volume tier was earned provisionally on the strength of replacement units and is lost at settlement: the bonus falls away even though net sales never moved. Crediting a return during the season marks the statement stale, leaving the next recompute to absorb the credit. Settlement stamps `finalized_at` and moves the statement `ACCRUING → FINALIZED` on the final variant's numbers; payment of the dealer is then a separate administrator act moving `FINALIZED → PAID` with `paid_at` recorded.

## 4. Endpoint Definitions

All endpoints are mounted under `/dealer`. Status code rules are uniform: creating a new resource returns **201**, while reads, action transitions, and the clock-setting capability return **200**. Request and response bodies are not restated here — every parameter and effect is specified in the narrative of §2 and §3, and the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/dealer/_clock/set_current_utc` | Set the logical clock (test-driving; startup default 2026-08-01T00:00:00Z) | DealerAdmin |
| POST | `/dealer/programs` | Create a seed program (DRAFT) | DealerAdmin |
| GET | `/dealer/programs/{id}` | Get a program | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/programs` | List programs | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/programs/{id}/open` | Open a program for selling; creates its ACCRUING commission statement | DealerAdmin |
| POST | `/dealer/programs/{id}/close_sales` | Close the selling season: cancels DRAFT orders, invoices CONFIRMED UNPAID orders, expires recommendations and out-of-window agreements | DealerAdmin |
| POST | `/dealer/programs/{id}/settle` | Settle the program: closes orders, applies prepayments, finalizes the commission statement, writes off expired lots | DealerAdmin |
| POST | `/dealer/trait-packages` | Create a trait package (LISTED) | DealerAdmin |
| GET | `/dealer/trait-packages/{id}` | Get a trait package | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/trait-packages` | List trait packages | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/trait-packages/{id}/retire` | Retire a trait package | DealerAdmin |
| POST | `/dealer/varieties` | Create a variety (LISTED) | DealerAdmin |
| GET | `/dealer/varieties/{id}` | Get a variety | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/varieties` | List varieties | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/varieties/{id}/delist` | Delist a variety (blocked while open orders reference it) | DealerAdmin |
| POST | `/dealer/growers` | Create a grower account (ACTIVE) | DealerAdmin, SalesRep |
| GET | `/dealer/growers/{id}` | Get a grower (Grower: own record only) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/growers` | List growers | DealerAdmin, SalesRep |
| POST | `/dealer/growers/{id}/hold` | Place a grower on credit hold | DealerAdmin |
| POST | `/dealer/growers/{id}/release_hold` | Release a grower credit hold | DealerAdmin |
| POST | `/dealer/growers/{id}/deactivate` | Deactivate a grower (requires no open orders and zero balances) | DealerAdmin |
| POST | `/dealer/growers/{id}/refund_prepay` | Refund a PREPAID order's prepayment out of the grower's prepay balance; order returns to UNPAID with the prepay discount removed | DealerAdmin |
| POST | `/dealer/fields` | Create a field (Grower: grower_id must equal X-User-ID) | DealerAdmin, SalesRep, Grower |
| GET | `/dealer/fields/{id}` | Get a field (Grower: own only) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/fields` | List fields (Grower: implicitly restricted to own) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/fields/{id}/retire` | Retire a field (blocked while plot trials occupy it) | DealerAdmin, SalesRep |
| POST | `/dealer/trait-agreements` | Create a trait/technology agreement (PENDING_SIGNATURE); OCC-guarded on the grower's version, which it increments | DealerAdmin, SalesRep |
| GET | `/dealer/trait-agreements/{id}` | Get a trait agreement (Grower: own only) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/trait-agreements` | List trait agreements (Grower: implicitly restricted to own) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/trait-agreements/{id}/sign` | Sign a pending agreement; supersedes any ACTIVE agreement for the same grower and package | DealerAdmin, Grower |
| POST | `/dealer/trait-agreements/{id}/suspend` | Suspend an active agreement; cascades holding affected CONFIRMED orders and releasing their inventory reservations | DealerAdmin |
| POST | `/dealer/trait-agreements/{id}/reinstate` | Reinstate a suspended agreement (does not auto-release held orders) | DealerAdmin |
| POST | `/dealer/trait-agreements/{id}/revoke` | Revoke an agreement (terminal); same order cascade as suspend | DealerAdmin |
| POST | `/dealer/recommendations` | Create a placement recommendation (DRAFT); OCC-guarded on the field's version, which it increments | Agronomist |
| GET | `/dealer/recommendations/{id}` | Get a recommendation (Grower: own only) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/recommendations` | List recommendations (Grower: implicitly restricted to own) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/recommendations/{id}/publish` | Publish a recommendation; supersedes the prior PUBLISHED one for the same field and program | Agronomist |
| POST | `/dealer/recommendations/{id}/accept` | Grower accepts a published recommendation | Grower |
| POST | `/dealer/recommendations/{id}/withdraw` | Withdraw a draft or published recommendation | Agronomist, DealerAdmin |
| POST | `/dealer/orders` | Create a draft seed order (Grower: grower_id must equal X-User-ID) | DealerAdmin, SalesRep, Grower |
| GET | `/dealer/orders/{id}` | Get an order (Grower: own only) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/orders` | List orders (Grower: implicitly restricted to own) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/orders/{id}/lines` | Add a line to a DRAFT order; snapshots the variety list price; requires an active trait agreement for traited varieties | DealerAdmin, SalesRep, Grower |
| GET | `/dealer/order-lines/{id}` | Get an order line (Grower: own order only) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/order-lines` | List order lines (Grower: implicitly restricted to own orders) | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/orders/{id}/confirm` | Confirm a draft order: locks the early-order tier, prices lines (per-unit rounding), selects the volume rebate tier, allocates inventory (FEFO) | SalesRep, Grower |
| POST | `/dealer/orders/{id}/cancel` | Cancel a draft, confirmed, or held order; releases reservations, cancels scheduled tickets, unapplies prepay | DealerAdmin, SalesRep, Grower |
| POST | `/dealer/orders/{id}/release_hold` | Release a compliance hold after agreements are reinstated; re-runs inventory allocation | DealerAdmin |
| POST | `/dealer/orders/{id}/prepay` | Prepay a confirmed order into the grower's prepay balance, earning the prepay tier discount | SalesRep, Grower |
| POST | `/dealer/orders/{id}/record_payment` | Record a cash payment against an invoiced order | DealerAdmin, SalesRep |
| POST | `/dealer/treatment-options` | Create a treatment option (AVAILABLE) | DealerAdmin |
| GET | `/dealer/treatment-options/{id}` | Get a treatment option | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/treatment-options` | List treatment options | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/treatment-options/{id}/discontinue` | Discontinue a treatment option | DealerAdmin |
| POST | `/dealer/inventory-lots` | Receive an inventory lot (AVAILABLE) | DealerAdmin |
| GET | `/dealer/inventory-lots/{id}` | Get an inventory lot | DealerAdmin, SalesRep |
| GET | `/dealer/inventory-lots` | List inventory lots | DealerAdmin, SalesRep |
| POST | `/dealer/inventory-lots/{id}/quarantine` | Quarantine a lot (requires no open reservations) | DealerAdmin |
| POST | `/dealer/inventory-lots/{id}/release_quarantine` | Release a lot from quarantine | DealerAdmin |
| POST | `/dealer/delivery-tickets` | Schedule a delivery or pickup against a confirmed order line (window, daily capacity, and remainder checks) | DealerAdmin, SalesRep |
| GET | `/dealer/delivery-tickets/{id}` | Get a delivery ticket (Grower: own order only) | DealerAdmin, SalesRep, Grower |
| GET | `/dealer/delivery-tickets` | List delivery tickets (Grower: implicitly restricted to own orders) | DealerAdmin, SalesRep, Grower |
| POST | `/dealer/delivery-tickets/{id}/complete` | Complete a scheduled ticket on or after its scheduled date; moves units from reserved to delivered on lot and line | DealerAdmin, SalesRep |
| POST | `/dealer/delivery-tickets/{id}/cancel` | Cancel a scheduled ticket (the reservation remains on the order) | DealerAdmin, SalesRep |
| POST | `/dealer/returns` | Request a return (window, untreated-only, and quantity-remaining rules) | SalesRep, Grower |
| GET | `/dealer/returns/{id}` | Get a return (Grower: own order only) | DealerAdmin, SalesRep, Grower |
| GET | `/dealer/returns` | List returns (Grower: implicitly restricted to own orders) | DealerAdmin, SalesRep, Grower |
| POST | `/dealer/returns/{id}/approve` | Approve a return; computes the provisional credit estimate and restocking fee | DealerAdmin, SalesRep |
| POST | `/dealer/returns/{id}/receive` | Physically receive returned seed; restocks the lot when resalable | DealerAdmin, SalesRep |
| POST | `/dealer/returns/{id}/credit` | Credit a received return; computes the final repriced credit and applies it to the grower balance | DealerAdmin |
| POST | `/dealer/returns/{id}/reject` | Reject a requested or approved return | DealerAdmin, SalesRep |
| POST | `/dealer/replant-claims` | File a replant claim (event window, delivered-units, and field-ownership rules) | SalesRep, Grower, ClaimsAdjuster |
| GET | `/dealer/replant-claims/{id}` | Get a replant claim (Grower: own order only) | DealerAdmin, SalesRep, Grower, ClaimsAdjuster |
| GET | `/dealer/replant-claims` | List replant claims (Grower: implicitly restricted to own orders) | DealerAdmin, SalesRep, Grower, ClaimsAdjuster |
| POST | `/dealer/replant-claims/{id}/start_review` | Adjuster starts review (must not be the filer) | ClaimsAdjuster |
| POST | `/dealer/replant-claims/{id}/request_info` | Adjuster requests more information (review loop) | ClaimsAdjuster |
| POST | `/dealer/replant-claims/{id}/provide_info` | Filer side provides information; claim returns to review | SalesRep, Grower, ClaimsAdjuster |
| POST | `/dealer/replant-claims/{id}/approve` | Approve a claim; creates the zero- or reduced-price replacement order and reserves its inventory | ClaimsAdjuster |
| POST | `/dealer/replant-claims/{id}/deny` | Deny a claim (must not be the filer) | ClaimsAdjuster |
| POST | `/dealer/replant-claims/{id}/withdraw` | Filer side withdraws an open claim | SalesRep, Grower |
| POST | `/dealer/plot-trials` | Plan a plot trial (half-open occupancy interval per field; overlap rejected) | Agronomist |
| GET | `/dealer/plot-trials/{id}` | Get a plot trial | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| GET | `/dealer/plot-trials` | List plot trials | DealerAdmin, SalesRep, Agronomist, Grower, ClaimsAdjuster |
| POST | `/dealer/plot-trials/{id}/record_planting` | Mark a planned trial planted | Agronomist |
| POST | `/dealer/plot-trials/{id}/record_harvest` | Record harvest results | Agronomist |
| POST | `/dealer/plot-trials/{id}/publish` | Publish yield results for marketing; requires the program's minimum replications for the variety | Agronomist, DealerAdmin |
| POST | `/dealer/plot-trials/{id}/discard` | Discard a planned or planted trial | Agronomist |
| GET | `/dealer/commission-statements/{id}` | Get a commission statement | DealerAdmin |
| GET | `/dealer/commission-statements` | List commission statements | DealerAdmin |
| POST | `/dealer/commission-statements/{id}/recompute` | Recompute the provisional accrual (ACCRUING only) | DealerAdmin |
| POST | `/dealer/commission-statements/{id}/mark_paid` | Mark a finalized statement paid | DealerAdmin |

## 5. Error Code Catalogue

The catalogue below is a lookup of identifiers to HTTP statuses. Trigger conditions are specified where each rule lives — §2 for platform-wide rules and §3 for workflow rules — and are deliberately not repeated here.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_GROWER_OWNERSHIP_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_PROGRAM_NOT_OPEN` | 409 |
| `ERR_PROGRAM_NOT_SETTLABLE` | 409 |
| `ERR_STALE_GROWER_VERSION` | 412 |
| `ERR_STALE_FIELD_VERSION` | 412 |
| `ERR_ORDER_LINE_MISMATCH` | 409 |
| `ERR_RECOMMENDATION_MISMATCH` | 409 |
| `ERR_FIELD_GROWER_MISMATCH` | 409 |
| `ERR_TRAIT_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_EXPIRED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PREPAY_WINDOW_CLOSED` | 409 |
| `ERR_PREPAY_AMOUNT_INSUFFICIENT` | 409 |
| `ERR_RETURN_WINDOW_CLOSED` | 409 |
| `ERR_RETURN_NOT_ALLOWED_TREATED` | 409 |
| `ERR_RETURN_QUANTITY_EXCEEDS` | 409 |
| `ERR_NOTHING_TO_RETURN` | 409 |
| `ERR_REPLANT_WINDOW_CLOSED` | 409 |
| `ERR_NO_DELIVERED_UNITS` | 409 |
| `ERR_DELIVERY_OUTSIDE_WINDOW` | 409 |
| `ERR_DELIVERY_TOO_EARLY` | 409 |
| `ERR_DELIVERY_CAPACITY_EXCEEDED` | 409 |
| `ERR_DELIVERY_EXCEEDS_REMAINING` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_VARIETY_DELISTED` | 409 |
| `ERR_VARIETY_HAS_OPEN_ORDERS` | 409 |
| `ERR_FIELD_HAS_ACTIVE_PLOTS` | 409 |
| `ERR_LOT_HAS_RESERVATIONS` | 409 |
| `ERR_TREATMENT_INCOMPATIBLE` | 409 |
| `ERR_PLOT_WINDOW_OVERLAP` | 409 |
| `ERR_INSUFFICIENT_PLOT_REPLICATIONS` | 409 |
| `ERR_ORDER_HAS_NO_LINES` | 409 |
| `ERR_ORDER_HAS_DELIVERIES` | 409 |
| `ERR_GROWER_NOT_ACTIVE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 |
| `ERR_GROWER_HAS_OPEN_ORDERS` | 409 |
| `ERR_GROWER_NOT_SETTLED` | 409 |
