# Tour Merch & Venue Splits API — Product Requirements Document

## 1. Introduction

A touring merchandise operation runs on thin margins and hard deadlines. Every night a truck of t-shirts, hoodies, and poster bundles rolls into a new city; sellers staff the venue's merch stands with counted cash floats; the venue takes its commission off the top of gross sales; the artist and any outside licensors take their negotiated splits of what remains; and whatever does not sell has to be shipped forward to the next city, returned to the warehouse, or liquidated on the spot. Between the drawer in a seller's hand and the final wire to the artist's management there are dozens of places where money or units can quietly go missing — an over-counted float, a misrecorded sale, a royalty rate that changed mid-tour, a shipment dispatched too late to matter.

This document specifies the API for the Tour Merchandise & Venue Split Management platform, mounted under `/merch`. It covers the full operating cycle: standing up a tour with its catalog and royalty terms, scheduling shows and pinning at-show prices, splitting inventory across size curves and routing restock shipments, staffing sellers and reconciling their cash drawers against the register, walking a show's settlement from provisional figures through dispute to finalization, closing out unsold stock, and running the parallel online store with its bundle fulfillment. A segregated-duty control model keeps the person who counts the money from being the person who verifies it, and a pinned-snapshot discipline keeps mid-tour royalty renegotiations from silently rewriting settlements already in flight.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. The role must be exactly one of `TourManager`, `Seller`, `Accountant`, or `VenueRep`. A request missing either header, carrying an unrecognized role, or — when the role is `Seller` — carrying an `X-User-ID` that is not the `id` of an existing `Seller` is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller`; ownership checks on any resource that references a `Seller` — a `SellerSession` through its `seller_id`, or a `SaleRecord` through the session it was recorded in — compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

When `X-User-Role` is `TourManager`, `Accountant`, or `VenueRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `verified_by_user_id` on a verified session, `reconciled_by_user_id` on a settlement, `dispatched_by_user_id` or `received_by_user_id` on a shipment, or `voided_by_user_id` on a voided sale — but it does not compare it to any entity's `id`.

A caller whose authenticated role is not in an endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

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
- List rows, and the resource objects returned by create or modify operations, carry the same fields — including computed fields such as `warehouse_stock_by_size`, `quantity_on_hand`, `expected_cash_cents`, or `royalty_payable_cents` — as a single-resource read of the same resource.

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

A request that matches no route, or whose method a matched route does not support, is answered with this same error envelope carrying `ERR_VALIDATION` at HTTP 404 or 405 respectively; an unexpected server failure is answered the same way at HTTP 500.

### 2.3. Pagination

All list endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0; a non-integer `limit` or `offset`, a `limit` outside that range, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus `limit` is less than `total_count`. Every list is sorted by `created_at` ascending unless otherwise stated.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in this domain carries a common set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every accepted mutation. `version` is an integer that starts at 1 on creation and increments by exactly one on every accepted mutation of the resource — activation, closing, and royalty-config updates each bump a tour's `version`; a reprice bumps a show product's `version`. All entity families described in §3 carry this full common set.

When a URL nests one resource beneath another, path identifiers are validated left to right: the outermost id is resolved first, and the first id that does not resolve produces the corresponding not-found error from §2.7 before any inner id is examined.

### 2.5. Money, Units, and Rounding Discipline

All monetary values are integer cents, carried in fields suffixed `_cents`; there is no floating-point money anywhere in the system. Percentage rates are expressed in basis points and applied by multiplying the base by the basis-point figure and dividing by 10000. Wherever a rate application produces a fractional cent, the result is rounded half up to a whole cent, and rounding is always applied per segment — per commission tier, per royalty segment, per licensing arm — with the rounded segments then summed; the system never sums unrounded segments and rounds once at the end. Subtractions such as `net_to_tour_cents` and `company_share_cents` are exact integer arithmetic with no rounding. Inventory quantities are exact non-negative integers throughout.

### 2.6. The Logical Clock

The server keeps a logical clock that is deliberately decoupled from wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A test-driving capability, `POST /merch/_clock/set_current_utc`, advances the logical clock to the instant supplied in `to_iso8601`; it is available to all four roles and returns the standard success envelope with an empty data object. Anything in the domain that needs "now" — the dispatch lead-time check and the `dispatched_at` stamp on a shipment, every `created_at` and `updated_at` entity timestamp, and every `api_request_timestamp` in a response envelope — reads this logical clock.

### 2.7. Validation Order and Error Precedence

When several checks could fail on the same request, exactly one error is reported: the checks below run in the order listed, and the earliest failing check wins.

1. Authentication context — both headers present, role recognized, and a `Seller` role backed by a real seller id — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. Role authorization and resource ownership — `ERR_FORBIDDEN_ROLE` or `ERR_NOT_RESOURCE_OWNER` (both HTTP 403).
3. Existence of every path id and every body-supplied foreign-key id, validated left to right — the matching one of `ERR_TOUR_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_SHOW_PRODUCT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_ONLINE_ORDER_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, or `ERR_SHIPMENT_NOT_FOUND` (all HTTP 404).
4. State preconditions, including cross-entity state gates (an `ACTIVE` tour to open a show, sessions verified to reconcile, and so on) — the state errors `ERR_INVALID_TOUR_STATE`, `ERR_TOUR_NOT_ACTIVE`, `ERR_INVALID_SHOW_STATE`, `ERR_SESSION_NOT_OPEN`, `ERR_SESSION_NOT_COUNTED_OUT`, `ERR_UNRESOLVED_SESSIONS`, `ERR_SETTLEMENT_NOT_RECONCILED`, `ERR_INVALID_SETTLEMENT_STATE`, `ERR_SHIPMENT_NOT_DRAFT`, `ERR_SHIPMENT_NOT_DISPATCHED`, `ERR_ORDER_NOT_PLACED`, `ERR_ALREADY_TERMINAL`, or `ERR_SHOWS_NOT_TERMINAL` (all HTTP 409).
5. Optimistic-concurrency staleness on version-guarded writes — `ERR_STALE_VERSION` (HTTP 412), checked after state and before business rules.
6. Cross-tour referential coherence — `ERR_CROSS_TOUR_REFERENCE` (HTTP 422).
7. Required related configuration — the at-show price row needed to record a sale, `ERR_PRICE_NOT_SET` (HTTP 422).
8. Venue calendar conflict — `ERR_VENUE_DATE_CONFLICT` (HTTP 409).
9. Seller double-booking — `ERR_SELLER_DOUBLE_BOOKED` (HTTP 409).
10. Restock lead time — `ERR_LEAD_TIME_VIOLATION` (HTTP 409).
11. Uniqueness — `ERR_SESSION_EXISTS`, `ERR_SHOW_PRODUCT_EXISTS`, or `ERR_ALLOCATIONS_EXIST` (all HTTP 409).
12. Request and configuration shape — `ERR_INVALID_SIZE_CURVE`, `ERR_INVALID_COMMISSION_CONFIG`, `ERR_BUNDLE_COMPONENT_INVALID` (all HTTP 400), `ERR_PRODUCT_NOT_SELLABLE_AT_SHOW` (HTTP 422), or the catch-all `ERR_VALIDATION` (HTTP 400) for missing required fields, wrong types, non-positive quantities or prices, invalid enum values, out-of-range basis-point rates or negative cent amounts, and malformed size maps.
13. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
14. Cash variance gate — `ERR_VARIANCE_OVERRIDE_REQUIRED` (HTTP 409).
15. Quantity and stock sufficiency — `ERR_INSUFFICIENT_ALLOCATION` or `ERR_INSUFFICIENT_STOCK` (both HTTP 409).
16. Royalty snapshot currency at finalization — `ERR_STALE_ROYALTY_CONFIG` (HTTP 409).

### 2.8. Segregation of Duties and Control Pairs

Three control pairs keep any one operator from both performing and approving the same sensitive step. The same `X-User-ID` may not stand on both sides of any pair: the verifier of a seller session must differ from that session's seller; the finalizer of a settlement must differ from the accountant recorded in the settlement's `reconciled_by_user_id`; and the receiver of a shipment must differ from the user recorded in `dispatched_by_user_id`. Violating any of the three is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.9. Optimistic Concurrency Control

Two writes are guarded by optimistic concurrency control. Updating a tour's royalty configuration requires the request to carry `expected_tour_version` equal to the tour's current `version`; repricing a show product requires `expected_show_product_version` equal to the show product's current `version`. If another accepted write — a config patch, an activation, a close, a prior reprice — has advanced the entity's `version` since the caller last observed it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller would otherwise overwrite terms it has never seen. The expected-version field is required on both endpoints: a request omitting it or carrying a non-integer value fails with `ERR_VALIDATION` (HTTP 400), while a present-but-stale integer fails with `ERR_STALE_VERSION`, a check that runs before the remaining body-shape validation. No endpoint other than these two accepts a version field.

### 2.10. Pinned Royalty Snapshots

A tour's royalty terms — `standard_rate_bps`, `tier_threshold_cents`, `tier_bonus_bps`, `licensed_flat_per_unit_cents`, and `licensed_rate_bps` — are living configuration: a tour manager may renegotiate them mid-tour. A settlement, by contrast, must be reproducible, so at the moment a settlement is created it copies the tour's then-current terms into five pinned snapshot fields: `pinned_standard_rate_bps`, `pinned_tier_threshold_cents`, `pinned_tier_bonus_bps`, `pinned_licensed_flat_per_unit_cents`, and `pinned_licensed_rate_bps`. All royalty and licensing arithmetic on that settlement uses the snapshot, not the live tour record. Patching the tour's royalty configuration does not rewrite any existing settlement's snapshot — affected settlements simply go stale, and finalization refuses to complete while the snapshot and the live config disagree (see §3.5). The remedy is an explicit rebase that re-pins the snapshot to the tour's current terms.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Tour and Its Catalog

A `TourManager` opens a new engagement by creating a tour with its `name` and `artist_name`, plus the five royalty terms that will later be pinned onto settlements: `standard_rate_bps` (the artist's royalty rate on the royalty base), `tier_threshold_cents` (the per-show net amount above which a bonus rate kicks in), `tier_bonus_bps` (the additional basis points applied to the portion of net strictly above that threshold), `licensed_flat_per_unit_cents` (the licensing minimum owed per unit sold of a licensed product), and `licensed_rate_bps` (the percentage alternative for licensed product sales). Each basis-point field must lie between 0 and 10000 inclusive, and the threshold and flat-per-unit amounts must be non-negative. Two further settings shape day-to-day operations: `default_size_curve`, an object mapping size keys drawn from S, M, L, and XL to non-negative integer weights with at least one weight positive — it defaults to weights of 1 for S, 2 for M, 2 for L, and 1 for XL, and any curve that has no positive weight, carries negative or non-integer weights, or uses keys outside that set is rejected with `ERR_INVALID_SIZE_CURVE`; and `cash_variance_tolerance_cents`, the per-session cash variance magnitude at or below which a count-out verifies without an override, defaulting to 1000 cents (ten dollars) and never negative. A new tour's `status` starts at `PLANNING`.

Activation moves the tour from `PLANNING` to `ACTIVE`; attempting to activate a tour that is not `PLANNING` fails with `ERR_INVALID_TOUR_STATE`. Closing is the mirror: a tour manager may close an `ACTIVE` tour only when every show of the tour has reached a terminal state — `CLOSED` or `CANCELLED` — and a premature close is rejected with `ERR_SHOWS_NOT_TERMINAL`; attempting to close a tour that is not `ACTIVE` at all is rejected with `ERR_INVALID_TOUR_STATE`. Both transitions, and every royalty-config update, increment the tour's `version` by one. A royalty-config patch is accepted while the tour is `PLANNING` or `ACTIVE`; once the tour is `CLOSED` the patch is rejected with `ERR_ALREADY_TERMINAL`. Reading a single tour reports `royalty_payable_cents`, computed on read as the sum of `artist_royalty_cents` plus `licensing_cents` over the tour's `FINALIZED` settlements, plus the sum of `artist_royalty_final_cents` plus `licensing_final_cents` over the tour's `FULFILLED` online orders; provisional, reconciled, or disputed settlements and placed or cancelled orders contribute nothing. The tours listing supports `limit` and `offset`.

Once the tour exists, the catalog follows. Creating a product takes the owning `tour_id`, a merchant `sku`, a display `name`, a `product_type` of `REGULAR` or `BUNDLE` (immutable after creation), a `royalty_treatment` of `STANDARD` or `LICENSED`, and a positive `base_price_cents` that serves as the online list price and the reference point for at-show pricing. The `sized` flag defaults to true: a sized product is sold and allocated in sizes S, M, L, and XL, while a non-sized product exists only in the single OS size. Starting warehouse stock arrives as `initial_stock_by_size`, a map from size to non-negative unit counts defaulting to empty — a sized product's keys must be a subset of S, M, L, XL, and a non-sized product may use only the OS key, with malformed maps rejected under `ERR_VALIDATION`. The live `warehouse_stock_by_size` is never written directly; it is a derived figure whose full reconciliation appears in §3.3.

Bundles deserve their own caution. A `BUNDLE` product is an online-only convenience grouping; it must declare `bundle_components`, a list pairing each `component_product_id` with a `qty_per_bundle`. Every component must be a `REGULAR`, non-sized product belonging to the same tour as the bundle, and the list may not reference the bundle itself or another bundle — any violation, including a component from another tour or a `component_product_id` that matches no product, is rejected with `ERR_BUNDLE_COMPONENT_INVALID`. A `REGULAR` product must leave `bundle_components` null; supplying components for one is likewise rejected with `ERR_BUNDLE_COMPONENT_INVALID`. Products can be listed with a `tour_id` filter, and reading one product reports the computed `warehouse_stock_by_size`.

### 3.2. Scheduling Shows and Setting At-Show Prices

With a tour active in planning, the `TourManager` schedules shows. A show carries its `tour_id`, the `city`, the `venue_name`, a `show_date` given as an ISO 8601 UTC datetime, and a commission configuration. The venue's calendar capacity is one show per venue per day: no two non-`CANCELLED` shows may share a `venue_name` and the calendar-date portion of `show_date`, and a conflicting create is rejected with `ERR_VENUE_DATE_CONFLICT` — adjacent dates at the same venue are perfectly fine. The create validates the request's shape, its `size_curve`, and its commission configuration before this calendar check, so an invalid configuration is reported even when the venue date also conflicts. A show starts in `SCHEDULED` status, and the shows listing can be filtered by `tour_id` or by `settlement_id` to find the show attached to a given settlement.

Commission configuration comes in two shapes, selected by `commission_mode`. A `FLAT` show requires `flat_commission_bps` — a single rate between 0 and 10000 applied to gross — and must leave `commission_tiers` null. A `TIERED` show instead requires `commission_tiers`, a list of bracket objects each carrying `up_to_cents` and `rate_bps`, ordered ascending by `up_to_cents`, with exactly one trailing bracket whose `up_to_cents` is null to catch everything above the last numbered cap; a `TIERED` show leaves `flat_commission_bps` null. A flat show missing its rate, or a tiered show with missing, unsorted, or improperly terminated brackets, is rejected with `ERR_INVALID_COMMISSION_CONFIG`. A show may also carry an optional `size_curve` overriding the tour default at allocation time; it obeys the same key and weight rules as the tour's curve, with violations rejected as `ERR_INVALID_SIZE_CURVE`.

Opening a show transitions it from `SCHEDULED` to `OPEN` and is gated on the parent tour being `ACTIVE` — an attempt against a tour still in `PLANNING` fails with `ERR_TOUR_NOT_ACTIVE`, and against a show in any other status with `ERR_INVALID_SHOW_STATE`; when both gates would fail, the show-state check runs first and `ERR_INVALID_SHOW_STATE` wins. Cancelling is a pre-doors operation only: `SCHEDULED` to `CANCELLED`, and a show that has already opened can no longer be cancelled, failing with `ERR_INVALID_SHOW_STATE`.

Pricing happens per show. A show product row ties a `show_id` to a `product_id` with an at-show `price_cents` that must be positive. The product must be `REGULAR` and belong to the show's tour — a cross-tour pairing is rejected with `ERR_CROSS_TOUR_REFERENCE`, and attempting to price a `BUNDLE` for at-show sale is rejected with `ERR_PRODUCT_NOT_SELLABLE_AT_SHOW`, since bundles are online-only. Only one price row may exist per show-and-product pair (a duplicate fails with `ERR_SHOW_PRODUCT_EXISTS`), and the row can be created only while the show is `SCHEDULED`. Repricing remains possible while the show is `SCHEDULED` or `OPEN` and is concurrency-guarded: the caller supplies the new `price_cents` together with `expected_show_product_version`, and a stale version is rejected with `ERR_STALE_VERSION` as described in §2.9. Later price changes never rewrite history — every sale already recorded keeps the unit price pinned onto it at sale time. Price rows can be listed filtered by `show_id`, by `product_id`, or both.

### 3.3. Allocating and Routing Inventory

Before doors, the tour manager generates allocations: given a `product_id` and a `total_units` count for a `SCHEDULED` show, the system splits the total across sizes using the effective size curve — the show's own `size_curve` when set, otherwise the tour's `default_size_curve`. Generation is allowed only once per show-and-product pair; a second run is rejected with `ERR_ALLOCATIONS_EXIST`, and attempting it on a show no longer `SCHEDULED` fails with `ERR_INVALID_SHOW_STATE`. The product must belong to the show's tour (otherwise `ERR_CROSS_TOUR_REFERENCE`), a `BUNDLE` product cannot be allocated at a show and fails with `ERR_VALIDATION`, and `total_units` must be a non-negative integer. A successful generation answers HTTP 201 with `response_type` "array", the created rows listed in the ascending size order S, M, L, XL, then OS.

The split algorithm is pinned and deterministic. A non-sized product ignores the curve entirely and yields exactly one allocation row with `size` OS and `quantity_allocated` equal to `total_units`. For a sized product, let W be the sum of the curve's weights. Each size with a positive weight receives a raw share of `total_units` multiplied by its weight and divided by W, kept as an exact rational; every such size is first floored to a whole unit, and the leftover units — the total minus the sum of the floors — are dealt out one at a time in order of fractional part, largest first, with ties broken in the fixed ascending size order S, then M, then L, then XL, then OS. One allocation row is created per size with a positive weight; sizes with weight zero get no row. Because the remainder is distributed rather than each size rounded independently, the allocated rows always sum exactly to `total_units`. Each allocation also tracks `quantity_sold` (the sum of quantities over that allocation's `ACTIVE` sale records), `quantity_returned`, `quantity_liquidated`, and `quantity_shrunk` (all zero until close-out), and exposes `quantity_on_hand` — the allocated units minus everything sold, returned, liquidated, or shrunk. Allocations can be listed filtered by `show_id` or `product_id`, and reading one reports the computed sold and on-hand figures.

Restocking between the warehouse and shows runs through shipments. Creating a shipment takes the `tour_id`, an `origin_type` of `WAREHOUSE` or `SHOW`, a `destination_show_id` receiving the goods, and `lines` — a list of product, `size`, and `quantity` triples where each quantity is positive, each size is valid for its product (S, M, L, or XL for sized products, OS for non-sized), and `BUNDLE` products are never shippable (a bundle line is rejected under `ERR_VALIDATION`). A `SHOW`-origin shipment must name an `origin_show_id` that differs from the destination; a `WAREHOUSE`-origin shipment must leave `origin_show_id` null. Origin and destination shows, and every line's product, must belong to the shipment's tour, or the create fails with `ERR_CROSS_TOUR_REFERENCE`; the origin-field and line shape rules above are validated before this cross-tour check. New shipments sit in `DRAFT`.

Dispatching is the controlled step. The shipment must be `DRAFT` (otherwise `ERR_SHIPMENT_NOT_DRAFT`), and the destination show's `show_date` must lie at least 48 hours after the dispatch instant read from the logical clock — exactly 48 hours is permitted, anything tighter fails with `ERR_LEAD_TIME_VIOLATION`. Stock is checked against the source: for a `WAREHOUSE` origin, every line must fit within the product's `warehouse_stock_by_size` for that size, failing with `ERR_INSUFFICIENT_STOCK`; for a `SHOW` origin, every line must fit within the origin allocation's `quantity_on_hand` for that product and size, failing with `ERR_INSUFFICIENT_ALLOCATION`. On dispatch the source is decremented — warehouse stock for a warehouse origin, or the origin show's allocation `quantity_allocated` for a show origin — and the shipment records `dispatched_by_user_id` and a `dispatched_at` stamp taken from the logical clock.

Receiving completes the move. The shipment must be `DISPATCHED` (otherwise `ERR_SHIPMENT_NOT_DISPATCHED`), the receiving user's `X-User-ID` must differ from `dispatched_by_user_id` under the segregation-of-duties rule of §2.8, and the destination show must still be `SCHEDULED` or `OPEN` (otherwise `ERR_INVALID_SHOW_STATE`). For each line, the destination show's allocation for that product and size is upserted — created when absent — and its `quantity_allocated` incremented by the line quantity, and the shipment records `received_by_user_id`. Cancelling works from `DRAFT` or `DISPATCHED`; cancelling a dispatched shipment performs a compensating restore, returning every line's units to the source — warehouse stock for a warehouse origin, origin allocations for a show origin. A shipment already `RECEIVED` or `CANCELLED` is terminal, and any further dispatch, receive, or cancel attempt fails with `ERR_ALREADY_TERMINAL`. Shipments can be listed filtered by `tour_id`, `destination_show_id`, or `origin_show_id`.

The warehouse ledger is fully derivable and is recomputed on read. A product's `warehouse_stock_by_size` for a given size is its `initial_stock_by_size` entry, minus the units of that size on `WAREHOUSE`-origin shipments now in `DISPATCHED` or `RECEIVED` status (a draft-then-cancelled shipment never decremented anything, while a dispatched-then-cancelled one decremented and was then restored), minus the units consumed by `FULFILLED` online orders (a `REGULAR` product's own size quantity, or for a `BUNDLE` each component's OS stock at `qty_per_bundle` times the order quantity; `PLACED` and `CANCELLED` orders consume nothing), plus the units credited back by `RETURN` lines at show close-out.

### 3.4. Show-Day Selling and Cash Drawer Discipline

Sellers join a tour's roster when a `TourManager` creates them with the owning `tour_id`, a `display_name`, and a human badge number in `seller_code`; the roster can be listed filtered by `tour_id`. Once a show is `OPEN`, the tour manager staffs it with seller sessions. Creating a session takes the `show_id`, the `seller_id`, and a count-in `cash_float_cents` (non-negative) representing the drawer's starting float. The float is validated first; then the show must be `OPEN` (otherwise `ERR_INVALID_SHOW_STATE`), the seller must belong to the show's tour (otherwise `ERR_CROSS_TOUR_REFERENCE`), and the seller must not already hold another session on a non-`CANCELLED` show whose `show_date` falls on the same calendar date — a conflicting session on the same show fails with `ERR_SESSION_EXISTS` and one on a different show with `ERR_SELLER_DOUBLE_BOOKED` — so at most one session may exist per show-and-seller pair. A new session starts `OPEN`; sessions can be listed filtered by `show_id` or `seller_id`, and reading one reports the computed `expected_cash_cents` and current `cash_variance_cents`.

Sales land against an open session. Recording a sale takes the `session_id`, the `allocation_id` being sold from, a positive `quantity`, and a `tender` of `CASH` or `CARD`. The session must be `OPEN` (otherwise `ERR_SESSION_NOT_OPEN`), the caller must be the session's owning seller (otherwise `ERR_NOT_RESOURCE_OWNER`), the allocation must belong to the session's show (otherwise `ERR_CROSS_TOUR_REFERENCE`), a show product price row must exist for that show and product (otherwise `ERR_PRICE_NOT_SET`), and the quantity must fit within the allocation's `quantity_on_hand` (otherwise `ERR_INSUFFICIENT_ALLOCATION`). At the moment of recording, the current show product `price_cents` is pinned onto the record as `unit_price_cents` — later repricing never rewrites it — `gross_cents` is computed as `quantity` times `unit_price_cents`, and the record's `show_id` and `product_id` are denormalized from the session and allocation for reporting. New sale records start `ACTIVE` and can be listed filtered by `session_id`, `show_id`, `allocation_id`, or `product_id`.

The drawer's expected contents are always derivable: a session's `expected_cash_cents` is its `cash_float_cents` plus the sum of `gross_cents` over the session's `ACTIVE` sale records tendered `CASH` — card sales never enter the drawer, and voided records drop out of the expectation. When the seller counts out, they submit `counted_cash_cents`, the physical drawer total as a non-negative integer (otherwise `ERR_VALIDATION`); the session must be `OPEN`, the caller must own it, and the parent show must still be `OPEN` (otherwise `ERR_SESSION_NOT_OPEN`, `ERR_NOT_RESOURCE_OWNER`, or `ERR_INVALID_SHOW_STATE` respectively). Count-out moves the session from `OPEN` to `COUNTED_OUT` and computes `cash_variance_cents` as `counted_cash_cents` minus `expected_cash_cents`; until the first count-out the variance is null.

Verification is a second pair of eyes. A `Seller` verifying a colleague's drawer, or a `TourManager`, acts on a `COUNTED_OUT` session (otherwise `ERR_SESSION_NOT_COUNTED_OUT`) while the parent show is `OPEN` or `RECONCILING` (otherwise `ERR_INVALID_SHOW_STATE`), and the verifier's `X-User-ID` must differ from the session's `seller_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`). The `decision` field selects the outcome. With `decision` `APPROVE`, the variance gate applies: when the absolute `cash_variance_cents` is at or below the tour's `cash_variance_tolerance_cents` the approval goes through freely, but an absolute variance exceeding the tolerance — even by a single cent — requires `variance_override` set to true and the caller's role to be `TourManager`; a `Seller` has no override power, and an over-tolerance approval without a manager override is rejected with `ERR_VARIANCE_OVERRIDE_REQUIRED`. A successful approval stamps `verified_by_user_id` with the verifier's identity and moves the session to `VERIFIED`. With `decision` `REJECT`, the session returns to `OPEN` for a recount: `recount_count` increments by one, and both `counted_cash_cents` and `cash_variance_cents` are cleared back to null until the next count-out.

### 3.5. Settlement: From Provisional Figures to Finalized Splits

When the night's drawers are counted, the tour manager begins reconciliation on the `OPEN` show. Every seller session of the show must be `COUNTED_OUT` or `VERIFIED` — any straggler still `OPEN` fails the operation with `ERR_UNRESOLVED_SESSIONS`, and a show in any other status fails with `ERR_INVALID_SHOW_STATE`. Beginning reconciliation moves the show from `OPEN` to `RECONCILING` and auto-creates the show's one and only settlement in `PROVISIONAL` status, recording its id on the show's `settlement_id`; the response returns the updated show object, and the new settlement is read back through that id or the `show_id` filter. At creation the settlement computes its provisional figures and pins the royalty snapshot per §2.10. `provisional_gross_cents` measures what is physically in the drawers plus what the card processor saw: the sum over the show's sessions of each `counted_cash_cents` minus its `cash_float_cents`, plus the sum of `gross_cents` over the show's `ACTIVE` sale records tendered `CARD`. `venue_commission_provisional_cents` applies the show's commission formula to that provisional base.

The commission formula itself has the two shapes from §3.2, and a commission base at or below zero yields a zero commission. A `FLAT` show's commission on any base is the base multiplied by `flat_commission_bps` and divided by 10000, rounded half up to a whole cent. A `TIERED` show applies its brackets marginally in ascending `up_to_cents` order: each bracket's portion is the amount of the base falling within that bracket — from the previous bracket's cap up to this bracket's cap, with the trailing null-capped bracket catching everything above the last numbered cap, and no bracket contributing less than zero — each bracket's commission is rounded half up to a whole cent first, and the bracket commissions are then summed.

Reconciliation proper belongs to the `Accountant`. Reconciling requires the settlement to be `PROVISIONAL` (otherwise `ERR_INVALID_SETTLEMENT_STATE`) and every session of the show to be `VERIFIED` (otherwise `ERR_UNRESOLVED_SESSIONS` — note the stricter gate than at begin-reconciliation). Reconcile moves the settlement to `RECONCILED` and replaces the provisional view with register truth: `final_gross_cents` is the sum of `gross_cents` over the show's `ACTIVE` sale records across both tenders, with `VOIDED` records excluded; `venue_commission_final_cents` applies the same commission formula to that final base; `net_to_tour_cents` is `final_gross_cents` minus `venue_commission_final_cents`, an exact subtraction. The settlement also records `reconciled_by_user_id` as the reconciling accountant.

Two splits then carve up `net_to_tour_cents`, always against the pinned snapshot. The artist royalty is tiered-marginal: when the net is at or below `pinned_tier_threshold_cents`, `artist_royalty_cents` is the net multiplied by `pinned_standard_rate_bps` and divided by 10000, rounded half up; when the net exceeds the threshold, it is the threshold multiplied by the standard rate and divided by 10000, rounded half up, plus the excess above the threshold multiplied by the sum of `pinned_standard_rate_bps` and `pinned_tier_bonus_bps` and divided by 10000, rounded half up — the two segments rounded separately and then summed, and at a net exactly equal to the threshold the bonus portion is zero because the bonus applies only to the amount strictly above it. Licensing is computed per `LICENSED` product sold at the show: for each such product, take the greater of `pinned_licensed_flat_per_unit_cents` multiplied by the product's total units sold there and the product's show gross multiplied by `pinned_licensed_rate_bps`, divided by 10000, and rounded half up; `licensing_cents` is the sum of those per-product maxima, and `STANDARD` products contribute nothing. What remains is the company's: `company_share_cents` is `net_to_tour_cents` minus `artist_royalty_cents` minus `licensing_cents`, exactly.

A reconciled settlement is not yet immutable. A `VenueRep` or `TourManager` may dispute it — the settlement must be `RECONCILED`, otherwise `ERR_SETTLEMENT_NOT_RECONCILED` — supplying a `reason` that is recorded on `dispute_reason`, moving the settlement to `DISPUTED`. An `Accountant` then resolves the dispute, moving it back from `DISPUTED` to `RECONCILED` (a settlement in any other status fails with `ERR_INVALID_SETTLEMENT_STATE`); resolution recomputes every final, royalty, licensing, and company figure from the current register state, so audit voids recorded during the dispute flow into the numbers, and `reconciled_by_user_id` is updated to the resolving accountant.

Finalization is the point of no return, guarded twice. The settlement must be `RECONCILED` (otherwise `ERR_SETTLEMENT_NOT_RECONCILED`); the finalizer's `X-User-ID` must differ from `reconciled_by_user_id` under §2.8 (otherwise `ERR_SEGREGATION_OF_DUTIES`); and the pinned royalty snapshot must equal the tour's current royalty configuration — if the tour's terms were patched after the snapshot was pinned, finalization fails with `ERR_STALE_ROYALTY_CONFIG`, and the remedy is to rebase first. A successful finalize moves the settlement to `FINALIZED` and cascades outward: the parent show transitions from `RECONCILING` to `SETTLED`, and every `VERIFIED` session of the show locks, moving from `VERIFIED` to `LOCKED`.

Rebasing is the pressure valve for stale snapshots, and it never changes the settlement's status. An `Accountant` may rebase while the settlement is `PROVISIONAL`, `DISPUTED`, or `RECONCILED`; rebasing a `FINALIZED` settlement is rejected with `ERR_INVALID_SETTLEMENT_STATE`. The five `pinned_*` fields are overwritten with the tour's current royalty terms. When the settlement is `RECONCILED` at rebase time, `artist_royalty_cents`, `licensing_cents`, and `company_share_cents` are immediately recomputed from the unchanged `final_gross_cents` and `venue_commission_final_cents` using the new snapshot; in `PROVISIONAL` or `DISPUTED` the re-pin alone suffices because the figures will be computed (or recomputed) at the next reconcile or resolve. Settlements can be listed filtered by `show_id` — since the relationship is one-to-one, such a filtered list has length zero or one.

### 3.6. Show Close-Out: Returns, Liquidation, and Shrinkage

A settled show still has physical stock on the tables, and close-out is where every remaining unit is accounted for. Each line's `allocation_id` is resolved first — an unknown id fails with `ERR_ALLOCATION_NOT_FOUND` — and then the show must be `SETTLED` (otherwise `ERR_INVALID_SHOW_STATE`). The tour manager submits `lines` covering the show's allocations: each line carries an `allocation_id`, an `action` of `RETURN` or `LIQUIDATE`, and a non-negative integer `quantity`, directing units of one allocation back to the warehouse or to liquidation on the spot; a line whose allocation belongs to another show, an unrecognized action, or a malformed quantity fails with `ERR_VALIDATION`. Every allocation row whose `quantity_on_hand` is positive must appear in the lines at least once — an omitted row fails with `ERR_CLOSEOUT_INCOMPLETE` — and an allocation may be split across several lines, whose quantities are then aggregated per action. On the money side, `actual_proceeds_cents` and `handling_fee_cents` are required non-negative integers, and `handling_fee_cents` may not exceed `actual_proceeds_cents` (otherwise `ERR_VALIDATION`). Finally, the returned plus liquidated quantities aggregated across an allocation's lines may not exceed that allocation's `quantity_on_hand` (otherwise `ERR_INSUFFICIENT_ALLOCATION`).

Close-out writes the residue onto every lined allocation: `quantity_returned` and `quantity_liquidated` come from the lines, and `quantity_shrunk` takes whatever remains — the on-hand units neither returned nor liquidated — so that afterwards a strict conservation invariant holds per allocation: `quantity_allocated` equals `quantity_sold` plus `quantity_returned` plus `quantity_liquidated` plus `quantity_shrunk`. Returned units flow back into the product's `warehouse_stock_by_size` per size, as described in §3.3. The show records `closeout_credit_cents` as `actual_proceeds_cents` minus `handling_fee_cents` and moves from `SETTLED` to `CLOSED`. If that close-out removed the tour's last non-terminal show — no other show remains outside `CLOSED` or `CANCELLED` — the tour automatically follows, transitioning from `ACTIVE` to `CLOSED` without any manual close call.

### 3.7. Online Store Orders and Bundle Fulfillment

The online store runs in parallel with the shows and sells from warehouse stock. Placing an order takes the `tour_id` — the tour must be `ACTIVE`, otherwise `ERR_TOUR_NOT_ACTIVE` — a `product_id` that may be `REGULAR` or `BUNDLE` and must belong to that tour (otherwise `ERR_CROSS_TOUR_REFERENCE`), a positive `quantity`, and a `size` that is required (one of S, M, L, XL) exactly when the product is sized and must be null for non-sized products and for bundles. The order's `unit_price_cents` is pinned from the product's `base_price_cents` at creation, `gross_cents` is `quantity` times that pinned price, and the order starts `PLACED`. Orders can be listed filtered by `tour_id` or `product_id`.

Two provisional royalty figures are snapshotted at creation from the tour configuration in effect at that moment. `artist_royalty_provisional_cents` is the order's `gross_cents` multiplied by the tour's `standard_rate_bps` and divided by 10000, rounded half up, regardless of treatment. `licensing_provisional_cents` is zero for a `STANDARD` product; for a `LICENSED` product it is the greater of `licensed_flat_per_unit_cents` multiplied by `quantity` and the order's `gross_cents` multiplied by `licensed_rate_bps`, divided by 10000, and rounded half up.

Fulfillment is where stock and money become final. The order must be `PLACED` (otherwise `ERR_ORDER_NOT_PLACED`), and warehouse stock must cover it: for a sized `REGULAR` product the `warehouse_stock_by_size` entry for the ordered size must be at least `quantity`; for a non-sized product the OS entry must be; for a `BUNDLE` every component's OS entry must be at least `qty_per_bundle` times `quantity` — any shortfall fails with `ERR_INSUFFICIENT_STOCK`. Fulfillment decrements warehouse stock accordingly (a bundle decrements each component's OS stock), moves the order to `FULFILLED`, and recomputes the royalty arms with the tour configuration in effect at that instant: `artist_royalty_final_cents` and `licensing_final_cents` follow the same formulas as their provisional counterparts but read the live config, so a royalty-config patch between placement and fulfillment makes the final figures diverge from the provisional ones. Cancelling a `PLACED` order moves it to `CANCELLED` with no stock or royalty effects; both final fields simply stay null, and a cancel or fulfill against a non-`PLACED` order fails with `ERR_ORDER_NOT_PLACED`.

### 3.8. Corrections, Overrides, and the Audit Trail

Mistakes at the register are corrected by voiding, and who may void depends on where the night stands. A `Seller` may void a record from their own session while that session is still `OPEN` — a record belonging to another seller's session fails with `ERR_NOT_RESOURCE_OWNER`, and a session already counted out fails with `ERR_SESSION_NOT_OPEN`. An `Accountant` performs the audit void once the money is under review: the parent show must be `RECONCILING` and its settlement `PROVISIONAL` or `DISPUTED`, so an audit void attempted after reconciliation has produced final figures fails with `ERR_INVALID_SETTLEMENT_STATE`. Under either path the record must still be `ACTIVE` — voiding a `VOIDED` record fails with `ERR_ALREADY_TERMINAL`, a check that runs before the session-open or settlement-state gate — and an optional `void_reason` may accompany the request; the system stamps `voided_by_user_id` and moves the record to `VOIDED`.

A void ripples through every derived figure. The allocation's `quantity_sold` is recomputed over `ACTIVE` records only, immediately restoring `quantity_on_hand`. The session's `expected_cash_cents` is recomputed as well; and when the session is already `COUNTED_OUT`, `cash_variance_cents` is recomputed against the recorded `counted_cash_cents`, so an audit void can push a previously passing drawer over the tolerance — the session will then need a recount via the reject loop or a manager's `variance_override` at verify time, as laid out in §3.4. Voids recorded during a dispute are exactly what the resolve step in §3.5 picks up when it recomputes the settlement's final figures from the current register state.

## 4. Endpoint Definitions

All endpoints are mounted under `/merch`. Creating a new resource returns HTTP 201 with the created resource in the envelope's `data`; state transitions, modifications, and reads return HTTP 200. Every request requires the headers and follows the validation order described in §2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /merch/tours | Create a tour with royalty terms; starts `PLANNING` | TourManager |
| GET | /merch/tours | List tours, paginated | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/tours/{id} | Get one tour including the computed `royalty_payable_cents` rollup | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/tours/{id}/activate | Transition the tour `PLANNING` → `ACTIVE` | TourManager |
| POST | /merch/tours/{id}/close | Transition the tour `ACTIVE` → `CLOSED` when every show is terminal | TourManager |
| PATCH | /merch/tours/{id}/royalty-config | Update royalty terms; OCC-guarded; does not rewrite existing settlement snapshots | TourManager |
| POST | /merch/shows | Create a show; venue-date uniqueness and commission config validated; starts `SCHEDULED` | TourManager |
| GET | /merch/shows | List shows, optionally filtered by tour or by settlement back-link | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/shows/{id} | Get one show | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/shows/{id}/open | Transition the show `SCHEDULED` → `OPEN`; requires an `ACTIVE` tour | TourManager |
| POST | /merch/shows/{id}/begin-reconciliation | Transition the show `OPEN` → `RECONCILING`; auto-creates the `PROVISIONAL` settlement with the pinned royalty snapshot | TourManager |
| POST | /merch/shows/{id}/cancel | Transition the show `SCHEDULED` → `CANCELLED` (pre-doors only) | TourManager |
| POST | /merch/shows/{id}/close-out | Transition the show `SETTLED` → `CLOSED`; records returns/liquidation/shrinkage, credits proceeds minus fee, restocks the warehouse, auto-closes the tour when it was the last open show | TourManager |
| POST | /merch/products | Create a `REGULAR` or `BUNDLE` product; bundle components and stock maps validated | TourManager |
| GET | /merch/products | List products, optionally filtered by tour | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/products/{id} | Get one product including the computed `warehouse_stock_by_size` | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/show-products | Set the at-show price for a `REGULAR` product; one row per show-and-product; show must be `SCHEDULED` | TourManager |
| GET | /merch/show-products | List price rows, filterable by show and/or product | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/show-products/{id} | Get one price row | TourManager, Seller, Accountant, VenueRep |
| PATCH | /merch/show-products/{id} | Reprice while the show is `SCHEDULED` or `OPEN`; OCC-guarded; recorded sales keep their pinned price | TourManager |
| POST | /merch/shows/{id}/allocations/generate | Split a product's units across sizes by the effective size curve (largest remainder); once per show-and-product; show must be `SCHEDULED` | TourManager |
| GET | /merch/allocations | List allocations, filterable by show and/or product | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/allocations/{id} | Get one allocation with computed `quantity_sold` and `quantity_on_hand` | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/sellers | Roster a seller onto a tour | TourManager |
| GET | /merch/sellers | List sellers, optionally filtered by tour | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/sellers/{id} | Get one seller | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/seller-sessions | Staff a seller onto an `OPEN` show with a count-in float; one session per show-and-seller; cross-tour and same-date double-booking rejected | TourManager |
| GET | /merch/seller-sessions | List sessions, filterable by show and/or seller | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/seller-sessions/{id} | Get one session with computed `expected_cash_cents` and `cash_variance_cents` | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/seller-sessions/{id}/count-out | Transition the session `OPEN` → `COUNTED_OUT` by the owning seller; records the counted drawer and computes variance | Seller |
| POST | /merch/seller-sessions/{id}/verify | `COUNTED_OUT` → `VERIFIED` on `APPROVE` or back to `OPEN` on `REJECT` (recount); verifier must differ from the seller; over-tolerance variance needs a manager override | Seller, TourManager |
| POST | /merch/sale-records | Record an at-show sale against an `OPEN` session; unit price pinned from the price row; overselling rejected | Seller |
| GET | /merch/sale-records | List sale records, filterable by session, show, allocation, or product | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/sale-records/{id} | Get one sale record | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/sale-records/{id}/void | Transition the record `ACTIVE` → `VOIDED`; sellers void own-session records while `OPEN`; accountants audit-void while the show is `RECONCILING` and the settlement `PROVISIONAL` or `DISPUTED` | Seller, Accountant |
| POST | /merch/online-orders | Place an online order (`REGULAR` or `BUNDLE`); price pinned from the product; provisional royalty snapshotted from current tour config; tour must be `ACTIVE` | TourManager |
| GET | /merch/online-orders | List online orders, filterable by tour and/or product | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/online-orders/{id} | Get one online order | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/online-orders/{id}/fulfill | Transition the order `PLACED` → `FULFILLED`; decrements warehouse stock (components for bundles); recomputes final royalty with current tour config | TourManager |
| POST | /merch/online-orders/{id}/cancel | Transition the order `PLACED` → `CANCELLED`; no stock or royalty effects | TourManager |
| GET | /merch/settlements | List settlements, optionally filtered by show (one-to-one, so zero or one row) | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/settlements/{id} | Get one settlement | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/settlements/{id}/reconcile | Transition the settlement `PROVISIONAL` → `RECONCILED`; requires all sessions `VERIFIED`; computes register-based final figures against the pinned snapshot | Accountant |
| POST | /merch/settlements/{id}/dispute | Transition the settlement `RECONCILED` → `DISPUTED`, recording the reason | VenueRep, TourManager |
| POST | /merch/settlements/{id}/resolve | Transition the settlement `DISPUTED` → `RECONCILED`; recomputes final figures from the current register (picks up audit voids) | Accountant |
| POST | /merch/settlements/{id}/finalize | Transition the settlement `RECONCILED` → `FINALIZED`; finalizer must differ from the reconciler; snapshot must match current tour config; cascades the show to `SETTLED` and sessions to `LOCKED` | Accountant |
| POST | /merch/settlements/{id}/rebase-royalty | Re-pin the royalty snapshot to the tour's current config; allowed in `PROVISIONAL`, `DISPUTED`, or `RECONCILED`; recomputes royalty figures when `RECONCILED` | Accountant |
| POST | /merch/shipments | Create a restock shipment (`WAREHOUSE` or `SHOW` origin) to a destination show; starts `DRAFT` | TourManager |
| GET | /merch/shipments | List shipments, filterable by tour, destination show, or origin show | TourManager, Seller, Accountant, VenueRep |
| GET | /merch/shipments/{id} | Get one shipment | TourManager, Seller, Accountant, VenueRep |
| POST | /merch/shipments/{id}/dispatch | Transition the shipment `DRAFT` → `DISPATCHED`; enforces the 48-hour lead time and source stock; decrements the source | TourManager |
| POST | /merch/shipments/{id}/receive | Transition the shipment `DISPATCHED` → `RECEIVED` by a different user than the dispatcher; upserts and increments destination allocations | TourManager |
| POST | /merch/shipments/{id}/cancel | Transition `DRAFT` or `DISPATCHED` → `CANCELLED`; cancelling a dispatched shipment restores the source quantities | TourManager |
| POST | /merch/_clock/set_current_utc | Advance the server's logical clock (test-driving); initial reading 2026-08-01T00:00:00Z | TourManager, Seller, Accountant, VenueRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_SIZE_CURVE | 400 |
| ERR_INVALID_COMMISSION_CONFIG | 400 |
| ERR_BUNDLE_COMPONENT_INVALID | 400 |
| ERR_PRODUCT_NOT_SELLABLE_AT_SHOW | 422 |
| ERR_TOUR_NOT_FOUND | 404 |
| ERR_SHOW_NOT_FOUND | 404 |
| ERR_PRODUCT_NOT_FOUND | 404 |
| ERR_SHOW_PRODUCT_NOT_FOUND | 404 |
| ERR_ALLOCATION_NOT_FOUND | 404 |
| ERR_SELLER_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_SALE_NOT_FOUND | 404 |
| ERR_ONLINE_ORDER_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_SHIPMENT_NOT_FOUND | 404 |
| ERR_INVALID_TOUR_STATE | 409 |
| ERR_TOUR_NOT_ACTIVE | 409 |
| ERR_INVALID_SHOW_STATE | 409 |
| ERR_SESSION_NOT_OPEN | 409 |
| ERR_SESSION_NOT_COUNTED_OUT | 409 |
| ERR_UNRESOLVED_SESSIONS | 409 |
| ERR_SETTLEMENT_NOT_RECONCILED | 409 |
| ERR_INVALID_SETTLEMENT_STATE | 409 |
| ERR_SHIPMENT_NOT_DRAFT | 409 |
| ERR_SHIPMENT_NOT_DISPATCHED | 409 |
| ERR_ORDER_NOT_PLACED | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_SHOWS_NOT_TERMINAL | 409 |
| ERR_CLOSEOUT_INCOMPLETE | 409 |
| ERR_CROSS_TOUR_REFERENCE | 422 |
| ERR_PRICE_NOT_SET | 422 |
| ERR_VENUE_DATE_CONFLICT | 409 |
| ERR_SELLER_DOUBLE_BOOKED | 409 |
| ERR_LEAD_TIME_VIOLATION | 409 |
| ERR_SESSION_EXISTS | 409 |
| ERR_SHOW_PRODUCT_EXISTS | 409 |
| ERR_ALLOCATIONS_EXIST | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_VARIANCE_OVERRIDE_REQUIRED | 409 |
| ERR_INSUFFICIENT_ALLOCATION | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_STALE_ROYALTY_CONFIG | 409 |
