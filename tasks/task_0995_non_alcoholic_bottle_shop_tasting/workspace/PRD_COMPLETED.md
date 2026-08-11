# Non-Alcoholic Bottle Shop API — Product Requirements Document

## 1. Introduction

The non-alcoholic beverage category has exploded past its "mocktail mixer" niche into a full retail vertical — sparkling teas, adaptogenic sodas, hemp-derived seltzers, kava-based botanicals, functional-mushroom elixirs, and dealcoholized wines all sit on the same shelf. Each of those categories carries a different regulatory posture at the state line, and "non-alcoholic" is not a single federal classification: products below 0.5% ABV are federally non-alcoholic, but products between 0.5% and 5% ABV fall into a "dealcoholized" band that several states still treat as restricted. A modern bottle shop that wants to sell both online (direct-to-consumer shipping) and in-store (retail pickup) therefore cannot treat compliance as a bolt-on checkbox; it has to be a first-class dimension of the catalogue.

This document specifies the API for a non-alcoholic bottle shop that operates retail pickup and direct-to-consumer shipping under one roof, runs a bottle club with tiered subscriptions and scheduled billing, hosts in-store tasting flights with capacity-managed seats, manages per-lot inventory with first-expired-first-out allocation, and supports member-initiated special orders for hard-to-source bottles. Because age-neutral compliance is the defining business risk, the system models per-state shipping rules, a per-SKU derived compliance class, an attestation workflow with segregation of duties between the staff member who submits an attestation and the compliance officer who approves it, and compliance holds that gate whether an event may be published at all.

The API is mounted under `/nabs`. All access is role-mediated through two headers on every request, all resources share a uniform identity and audit shape, and the entire system runs against a logical UTC clock so that time-driven transitions (trial expiry, event lock-in, billing recurrence) are reproducible and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API carries two headers: `X-User-ID` and `X-User-Role`. The role value must be exactly one of the following role names — `Anonymous`, `Member`, `ShopStaff`, `ComplianceOfficer`, `PlatformAdmin` — spelled exactly as shown. A request that arrives without a well-formed `X-User-Role`, or with a role value outside this list, is rejected with `ERR_UNAUTHENTICATED`. `X-User-ID` is required for every role except `Anonymous`: an `Anonymous` request may omit `X-User-ID`, while any other role arriving without it is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not on the authorized list for the target endpoint is rejected with `ERR_UNAUTHORIZED`.

The five roles have distinct identity semantics:

- When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` (an order, a subscription, a special order, a tasting seat) compare the resource's `member_id` to `X-User-ID`. On member-scoped collection endpoints a `Member` caller is restricted to their own data: the member fetch and the `/nabs/members/{id}/...` child lists reject a path id naming another member with `ERR_UNAUTHORIZED`, `GET /nabs/orders` silently filters to the caller's own orders (a `member_id` filter naming another member is rejected with `ERR_UNAUTHORIZED`), and `GET /nabs/tasting-events/{id}/seats` returns only the caller's own seats.
- When `X-User-Role` is `ShopStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `approved_by_user_id` on a `SpecialOrder` or as `attested_by_user_id` on a `ComplianceAttestation` — but does not compare it to any entity's `id`. The same holds for `ComplianceOfficer`, `PlatformAdmin`, and `Anonymous`: these identifiers are opaque operator credentials, recorded where the workflow calls for an audit trail but never used as a foreign key.

Two segregation-of-duties constraints rely on this distinction, and are described where they apply in §3: a `ShopStaff` operator approving a `SpecialOrder` may not be the requesting member, and a `ComplianceOfficer` approving a `ComplianceAttestation` may not be the `ShopStaff` operator who originally submitted it.

As a hierarchical override, `PlatformAdmin` is implicitly authorized for every endpoint that authorizes `ShopStaff`, whether or not the endpoint's role list names `PlatformAdmin` explicitly; `PlatformAdmin` does not inherit `Member` or `ComplianceOfficer` authorizations.

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

All list endpoints accept two query parameters: `limit` and `offset`. The default value of `limit` is 10, with a minimum of 1 and a maximum of 100; the default value of `offset` is 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. List endpoints sort results by `created_at` ascending unless otherwise specified, with ties broken by insertion order. The `meta` block of every list response carries four pagination fields — `limit`, `offset`, `total_count`, and `has_more` — so clients can page deterministically without recomputing totals; `has_more` is true exactly when `offset` plus `limit` is less than `total_count`. In addition, list endpoints accept optional exact-match filter query parameters: category list — `active`; SKU list — `category_id`, `discontinued`; member list — `age_attestation_status`, `loyalty_tier`; club-plan subscription list — `status`; lot list — `status`; tasting-event list — `status`; order list — `member_id`, `channel`, `fulfillment_status`; shipping-state-rule list — `allows_dtc`. Boolean filters accept `true`/`1` and `false`/`0` (case-insensitive); any other value is rejected with `ERR_INVALID_REQUEST`.

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every resource in the system shares a uniform identity and audit shape. Each resource carries:

- `id` — a server-minted UUID with no type prefix (the id is a bare UUID, not a string like `sku_...`).
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer starting at 1 at creation that increments by exactly one on every mutation of the resource.

Because the catalogue is shared by many concurrent writers (a member booking a seat while staff adds flight items, a subscriber joining while the plan's capacity counter moves), three write endpoints are guarded by optimistic concurrency control:

- Submitting an order may carry `expected_order_version`, equal to the `Order`'s `version` the client last observed. If the field is present and the order's current `version` differs — because another writer added or removed lines or modified `loyalty_points_redeemed` in the interim — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412); if the field is omitted, no stale-version check is performed.
- Booking a seat on a tasting event may carry `expected_event_version`, equal to the `TastingEvent`'s `version` the client last observed. If the field is present and another seat was booked or cancelled since that read, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412); if the field is omitted, no stale-version check is performed.
- Subscribing a member to a club plan may carry `expected_plan_version`, equal to the `ClubPlan`'s `version` the client last observed. If the field is present and another subscription moved the plan's `active_subscription_count` in the interim, the subscribe is rejected with `ERR_STALE_VERSION` (HTTP 412); if the field is omitted, no stale-version check is performed.

Endpoints not listed above do not take a version field; a `version` value in any other request body is ignored. The OCC rule is purely a stale-read guard — the server does not reason about wall-clock simultaneity, only about whether the version the client saw is still the version the server has.

### 2.5. Money, Precision, and Rounding

All monetary quantities are represented as integer cents. The fields `base_price_cents`, `unit_cost_cents`, `price_cents_per_cycle`, `flight_price_cents`, `price_paid_cents`, `deposit_cents`, `subtotal_cents`, `discount_cents`, `shipping_charge_cents`, `tax_cents`, `grand_total_cents`, `unit_price_cents`, `extended_price_cents`, `surcharge_cents_per_order`, and `wallet_credit_cents` are all integer cents. Where a computation produces a fractional cent — for example a per-line club-discount multiplication, or a destination-state sales-tax computation — the result is rounded half-up to zero decimal places. Loyalty points are integers; where a tier multiplier produces fractional points, the result is likewise rounded half-up to zero decimal places.

### 2.6. The Logical Clock

Time-driven behavior — trial expiry, the 24-hour booking cutoff before an event, the moment an event begins or ends, the date a subscription bills next — all key off a logical UTC clock maintained by the server, not the wall clock. At server startup the logical clock reads `2026-05-01T00:00:00Z` and never falls back to the wall clock thereafter. A `PlatformAdmin` may advance the clock via a dedicated test-driving capability that takes a `to_iso8601` timestamp; the clock is set to exactly the supplied value (the endpoint does not require it to be after the current value), the endpoint responds with HTTP 200 whose `data` carries the new logical time under `now`, and when the clock moves, the system evaluates every pending system-scheduled transition whose preconditions are now satisfied and applies them in dependency order. Business narratives below use phrases like "when the clock reaches..." to refer to this logical clock.

### 2.7. Validation Priority Ordering

When a single request could fail more than one check, the server evaluates checks in a fixed priority order and returns the first failure. The ordering matters because a higher-priority failure masks lower-priority ones. Evaluated in order:

1. Authentication — the `X-User-Role` and (where required) `X-User-ID` headers are present and well-formed (`ERR_UNAUTHENTICATED`).
2. Authorization — the role is permitted for this endpoint (`ERR_UNAUTHORIZED`).
3. Existence — every path-template and foreign-key-referenced entity exists (`ERR_NOT_FOUND`).
4. Shape — required input fields are present and well-typed (`ERR_INVALID_REQUEST`).
5. State — the target entity's current state permits the requested transition (`ERR_INVALID_STATE`).
6. Age attestation — the member is `ATTESTED` when an `ADULT_ONLY_REQUIRED` SKU is involved (`ERR_AGE_ATTESTATION_REQUIRED`).
7. Compliance hold — a tasting event with `compliance_hold` set cannot be published (`ERR_COMPLIANCE_HOLD`).
8. Segregation of duties — actor is not a forbidden related party (`ERR_SEGREGATION_OF_DUTIES`).
9. Time range — `ends_at` strictly after `starts_at`, and reschedule targets strictly in the future (`ERR_INVALID_TIME_RANGE`).
10. Booking window — seat operations only while the event is bookable (`ERR_BOOKING_WINDOW_CLOSED`).
11. Capacity — `seats_booked` below `capacity`, `active_subscription_count` below `max_active_subscriptions` (`ERR_CAPACITY_EXCEEDED`).
12. Uniqueness — `sku_code`, `code`, `email`, `state_code`, `(sku_id, lot_code)` (`ERR_DUPLICATE`).
13. DTC state permission — destination state permits direct-to-consumer shipping (`ERR_DTC_STATE_PROHIBITED`).
14. ABV cap — every line's `abv_basis_points` is at or below the destination state's `abv_cap_basis_points` (`ERR_SKU_ABV_STATE_EXCEEDED`).
15. SKU state prohibition — the SKU and its category are not prohibited in the destination state (`ERR_SKU_STATE_PROHIBITED`).
16. Loyalty redemption — `loyalty_points_balance` covers `loyalty_points_redeemed` (`ERR_INSUFFICIENT_POINTS`).
17. Inventory sufficiency — the FEFO lot walk can satisfy every line (`ERR_INSUFFICIENT_INVENTORY`).
18. Wallet hold — `wallet_credit_cents` covers the special-order deposit (`ERR_INSUFFICIENT_WALLET`).
19. Optimistic concurrency — `expected_<parent>_version` matches the parent's current `version` (`ERR_STALE_VERSION`).

Because checks are evaluated in this order, a single malformed call surfaces exactly one error — the earliest in this list that applies.

### 2.8. Hierarchical Path Resolution

Many resources are nested beneath a parent in the URL: an inventory lot lives under a SKU, a flight item under a tasting event, a seat under an event, an order line under an order (where the line is identified by `line_id` beneath its parent order). Path parameters are validated left to right. If any path segment fails to resolve — the parent id does not exist, or the child id does not exist under that parent — the request is rejected with `ERR_NOT_FOUND`, and no further processing occurs.

## 3. Business Logic & Workflows

### 3.1. Catalogue Foundations — Categories, SKUs, and Age-Neutral Classification

The catalogue is organized into `Category` rows, each identified by a unique kebab-case `code` (lowercase alphanumeric plus dashes, between 2 and 48 characters — examples include `sparkling-tea` and `adaptogenic-soda`), a human-readable `display_name`, a `compliance_class` that determines the age-neutral posture of every SKU filed under it, and an `active` flag (defaulting to true) that is informational and filterable only — the server does not reject SKU creation under an inactive category. The `compliance_class` takes one of five values: `STANDARD`, `SENSITIVE_INGREDIENT`, `HEMP_DERIVED`, `KAVA`, or `FUNCTIONAL_MUSHROOM`. The two values `HEMP_DERIVED` and `KAVA` are the trigger for shipping-state restrictions throughout the system.

A `SKU` is filed under exactly one category via its `category_id`. Beyond the parent reference, a SKU carries a merchant-facing `sku_code` (unique across all SKUs, between 3 and 32 characters), a `title`, a `base_price_cents` (the list price in cents, must be zero or greater), an `abv_basis_points` field recording alcohol-by-volume in basis points, an optional `ship_state_overrides` list, and a `discontinued` flag (defaulting to false). The `abv_basis_points` field carries the federal taxonomy: a value of exactly zero means certified zero-alcohol; a value at or below 50 basis points is federally "non-alcoholic"; a value in the 51-to-500 band is "dealcoholized" and restricted in some states. Any attempt to create a SKU with `abv_basis_points` above 500 is rejected outright — the system never carries inventory above the 5-percent ceiling, and the same 0–500 ceiling applies when a SKU is updated. `PATCH /nabs/skus/{id}` accepts `title`, `base_price_cents`, `abv_basis_points`, `discontinued`, and `ship_state_overrides`; the SKU's `version` is bumped and its `age_neutral_class` recomputed only when at least one of these fields is present in the request body.

Every SKU has a derived `age_neutral_class`, computed at creation and recomputed whenever its `abv_basis_points`, its `ship_state_overrides`, or its parent category's `compliance_class` changes. The classification walks a fixed decision sequence. First, if `abv_basis_points` exceeds 500 the SKU is rejected at creation — this branch never produces a stored value. Otherwise, if the parent category's `compliance_class` is `HEMP_DERIVED`, the SKU's class is `PROHIBITED_STATE_LIST`. If the parent category's `compliance_class` is `KAVA`, the SKU's class is `PROHIBITED_STATE_LIST`. If the parent category's `compliance_class` is `FUNCTIONAL_MUSHROOM`, the SKU's class is `ADULT_ONLY_SUGGESTED`. If none of those category branches apply and the SKU's `abv_basis_points` exceeds 50, the SKU's class is `ADULT_ONLY_REQUIRED`. In every remaining case the class is `OPEN`. A separate override rule runs on top of this base classification: when the SKU's `ship_state_overrides` contains a `PROHIBITED` entry for a target state, the SKU is treated as `PROHIBITED_STATE_LIST` for that state regardless of the category-level classification. Each override entry is an object carrying a state code (under a `state_code` or `state` key) and a `status` of `PROHIBITED` or `ALLOWED`; an `ALLOWED` entry for a state lifts the category-derived prohibition for that state.

The system also maintains a cached `on_hand_cached` integer on every SKU, equal to the sum of `qty_remaining` across all of the SKU's inventory lots whose status is `ACTIVE` or `DEPLETED` — lots in `QUARANTINED` or `EXPIRED` are deliberately excluded from this cached count. The cache is recomputed every time any lot under the SKU is inserted, updated, or deleted.

### 3.2. Inventory — Lots, FEFO Allocation, and Quarantine

Physical stock is tracked as `InventoryLot` rows under a SKU. Each lot carries a `sku_id` linking back to its parent SKU, a vendor-supplied `lot_code` (unique within the pair of `sku_id` and `lot_code`), a `qty_received` (must be at least 1), a derived `qty_remaining`, a `unit_cost_cents` (per-unit acquisition cost), an `expires_on` ISO-8601 date, a derived `status`, and an optional `quarantine_reason`.

The lot's `status` is derived from the relationship between `qty_remaining`, `expires_on`, and any active quarantine. A lot is `ACTIVE` when `qty_remaining` is greater than zero and today's date is on or before `expires_on`. A lot is `DEPLETED` when `qty_remaining` reaches zero. A lot is `EXPIRED` when today's date is strictly after `expires_on`. A lot is `QUARANTINED` while a compliance hold is in effect, with the reason recorded in `quarantine_reason` (the field defaults to null on lots that have never been quarantined). The status derivation runs at creation too — a lot received with an `expires_on` already in the past is stored directly as `EXPIRED` — and a `quarantine_reason` supplied at creation is stored as-is without making the lot `QUARANTINED`.

When stock is needed — either to fill an order line or to reserve bottles for a tasting flight — the system runs a first-expired-first-out walk across the SKU's lots. The walk considers only lots in `ACTIVE` status, ordered by `expires_on` ascending with `created_at` ascending as the tie-break (never the lot `id`). From each lot in turn the walk takes the smaller of that lot's `qty_remaining` and the outstanding demand, decrements the lot's `qty_remaining` accordingly, flips the lot to `DEPLETED` if its `qty_remaining` reaches zero, and continues until the demand is fully satisfied. If the walk ends with demand still outstanding — the non-`EXPIRED`, non-`QUARANTINED` lots cannot cover the request — the operation that triggered the walk is rejected with `ERR_INSUFFICIENT_INVENTORY`. On retail-channel orders, a `ShopStaff` operator may explicitly override and allocate from `QUARANTINED` lots; on direct-to-consumer orders no such override is permitted and the walk is restricted to non-quarantined lots.

A `ComplianceOfficer` may move a lot into `QUARANTINED` status by supplying a `quarantine_reason`; any lot may be quarantined regardless of its current status, and the SKU's `on_hand_cached` is recomputed immediately. The same officer may later release the quarantine — the lot returns to `ACTIVE` provided it still has `qty_remaining` greater than zero and has not yet passed its `expires_on` date (otherwise it lands in `DEPLETED` or `EXPIRED` per the derivation above), the SKU's `on_hand_cached` is recomputed again, and releasing a lot that is not `QUARANTINED` is rejected with `ERR_INVALID_STATE`.

### 3.3. Members, Loyalty, and Wallet

A `Member` registers with an `email` (unique, case-insensitive; the only format check is that the address contains an `@` character), a `full_name`, a `date_of_birth` (ISO date), and a `home_state_code` (stored as an opaque string with no format enforcement) used both as the default shipping destination and as a compliance gate. Registration initializes `age_attestation_status` to `UNVERIFIED`, `loyalty_tier` to `BRONZE`, and `loyalty_points_balance`, `loyalty_points_lifetime`, and `wallet_credit_cents` to zero. Each member carries three computed money-and-points fields: a `loyalty_points_balance` (redeemable points; never negative), a `loyalty_points_lifetime` (cumulative earnings; monotonic — redemptions never decrement it, only an order refund clawback does), and a `wallet_credit_cents` (store credit accumulated from refunds and voids; never negative; consumed before card on checkout).

The member's `loyalty_tier` is derived from `loyalty_points_lifetime` against four inclusive-lower-bound thresholds. When `loyalty_points_lifetime` is at least 50000 the tier is `PLATINUM`. When it is at least 20000 but below 50000 the tier is `GOLD`. When it is at least 5000 but below 20000 the tier is `SILVER`. Below 5000 the tier is `BRONZE`. The boundary at 5000 points is precise: at exactly 5000 lifetime points the tier flips to `SILVER` — the threshold is inclusive, not exclusive. Tier is recomputed whenever `loyalty_points_lifetime` changes, including the no-change case during attestation approval.

The tier drives a multiplier applied to point accrual: `BRONZE` accrues at 1.0×, `SILVER` at 1.25×, `GOLD` at 1.5×, and `PLATINUM` at 2.0×. The multiplier is applied to the base points before any rounding, and the resulting value is rounded half-up to a whole number of points.

A `PlatformAdmin` or `ShopStaff` operator may post a wallet adjustment carrying a `delta_cents` (positive or negative) and a `reason`; the member's `wallet_credit_cents` is incremented by `delta_cents` with a floor of zero — an adjustment that would drive the wallet negative is clamped. The endpoint responds with HTTP 201 carrying the updated `Member` object.

### 3.4. Age Attestation — Segregation of Duties

Because parts of the catalogue are age-gated, each member carries an `age_attestation_status` that progresses through a five-state lifecycle: `UNVERIFIED` (the initial state at registration), `PENDING_REVIEW`, `ATTESTED`, `REJECTED`, and the terminal `REVOKED`.

A `ShopStaff` (or `ComplianceOfficer`) operator initiates an attestation by submitting a payload containing `attested_by_user_id` (the operator's own opaque user id), an `outcome` (one of `APPROVED` or `REJECTED`), an `attested_on` ISO date, and a `document_reference` (for example an external ID-scan transaction id). This submission is permitted when the member's `age_attestation_status` is either `UNVERIFIED` or `REJECTED` — re-attestation after a rejection is the only way back into the queue — and transitions the member to `PENDING_REVIEW` while creating a `ComplianceAttestation` row and bumping the member's `updated_at`. The segregation-of-duties rule forbids `attested_by_user_id` from equaling the `member_id`; an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`.

While the member is `PENDING_REVIEW`, a `ComplianceOfficer` reviews the attestation. Approval requires the attestation's `outcome` to be `APPROVED` and — as a second segregation-of-duties constraint — the approving officer's user id must differ from the `attested_by_user_id` of the operator who originally submitted. A self-approval attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`. An approval attempt on an attestation whose `outcome` is not `APPROVED` is rejected with `ERR_INVALID_STATE`. Successful approval transitions the member to `ATTESTED` and recomputes the member's `loyalty_tier` (which in practice only changes if the lifetime-points thresholds happen to be crossed). Rejection, by contrast, requires only that the member is currently `PENDING_REVIEW`, and transitions the member to `REJECTED`. Both the approve and reject endpoints respond with HTTP 200 carrying the updated `Member` object. From `REJECTED` the cycle is open — a new attestation submission returns the member to `PENDING_REVIEW`.

A `ComplianceOfficer` may also revoke a member whose `age_attestation_status` is currently `ATTESTED`. Revocation moves the member to `REVOKED` (a terminal state — there is no path back), immediately blocks all future orders containing `ADULT_ONLY_REQUIRED` SKUs for that member, and cascade-cancels any of that member's `Order` rows currently in `DRAFT` or `PICKING` that contain an `ADULT_ONLY_REQUIRED` SKU. The cascade treats a `PICKING` order exactly like a staff cancellation: it restores every line's lot allocation (recomputing the affected SKUs' `on_hand_cached`), sets `payment_status` to `VOIDED`, and credits `loyalty_points_redeemed` back to the member's balance; a `DRAFT` order is simply marked `CANCELLED`.

### 3.5. Tasting Events — From Draft to Completion

A `TastingEvent` begins life in `DRAFT` status with a `title`, a `host_member_id` (any existing `Member` — the server checks only that the referenced member exists, with no role check on the referenced member), a `starts_at` and `ends_at` (both ISO-8601 UTC, with `ends_at` strictly after `starts_at` — anything else is rejected with `ERR_INVALID_TIME_RANGE`), a `capacity` (at least 1), a `flight_price_cents` (zero or greater), and a `min_attendee_age_years` defaulting to zero (zero means age-neutral and open to all; a value of 21 indicates alcohol-adjacent service). The event's `seats_booked` is a derived count of its seats in `RESERVED`, `CONFIRMED`, or `ATTENDED` status.

Once the event has at least one `FlightItem`, a `ShopStaff` operator may publish it. Publication is gated by three preconditions: the event's `compliance_hold` must be false (no flight item references a SKU whose `age_neutral_class` is `PROHIBITED_STATE_LIST` for the shop's home state — a violation surfaces as `ERR_COMPLIANCE_HOLD`); the event must have at least one flight item (a violation surfaces as `ERR_INVALID_REQUEST`); and `starts_at` must be strictly after the current logical UTC time (a violation surfaces as `ERR_INVALID_TIME_RANGE`). Successful publication transitions the event from `DRAFT` to `PUBLISHED`, runs the FEFO lot walk for each flight item — reserving `estimated_bottle_consumption` bottles against real lots, with each item's reservation rounded up to the next whole bottle and demand aggregated per SKU across items before the walk, decrementing `InventoryLot.qty_remaining`, and recomputing the affected SKUs' `on_hand_cached` — and bumps the event's `version`.

From `PUBLISHED`, three paths are available. The clock reaching `starts_at` minus 24 hours transitions the event automatically to `LOCKED`, after which no new seat reservations are accepted. A `ShopStaff` operator may cancel a `PUBLISHED` event, which transitions it to `CANCELLED`, cascade-cancels every `TastingSeat` in `RESERVED` or `CONFIRMED` (a `CONFIRMED` seat's `price_paid_cents` is refunded to its member's `wallet_credit_cents` exactly as in seat-level cancellation), restores the reserved `InventoryLot.qty_remaining`, recomputes the affected SKUs' `on_hand_cached`, and bumps the event's `version`. The clock reaching `starts_at` while the event is `LOCKED` transitions it to `IN_SESSION` with no side effects.

While `IN_SESSION`, the event runs to its natural end: the clock reaching `ends_at` and every seat being in a terminal state (`ATTENDED`, `NO_SHOW`, `CANCELLED`, or `REFUNDED`) together trigger the transition to `COMPLETED`. Seat loyalty points are not granted at completion — each attended seat's `loyalty_points_awarded` was already credited to its member at check-in — so the completion transition itself moves no points.

From `LOCKED` a `ShopStaff` operator may alternatively reschedule the event by supplying a `new_starts_at` and `new_ends_at`; the new `starts_at` must be strictly after the current logical UTC time (otherwise `ERR_INVALID_TIME_RANGE`), a `new_ends_at` not strictly after `new_starts_at` is likewise rejected with `ERR_INVALID_TIME_RANGE`, and the event's `starts_at` and `ends_at` are replaced with the new values as the event transitions to `RESCHEDULED`. Existing seats remain valid through the reschedule — no re-booking is needed. The system then transitions `RESCHEDULED` back to `PUBLISHED` synchronously within the same request, restoring normal booking: the response shows the event already back in `PUBLISHED` with its `version` advanced by two.

### 3.6. Flight Items and Seat Booking

Each `FlightItem` belongs to exactly one `TastingEvent` via `tasting_event_id` and pours exactly one SKU via `sku_id`. The item carries a `pour_size_ml` (between 5 and 60 milliliters per seat), a `sequence_no` (unique within the event, at least 1), and a computed `estimated_bottle_consumption` equal to `pour_size_ml` multiplied by the event's `capacity` and divided by 750 — the standard 750ml bottle. Adding a flight item recomputes the event's `compliance_hold`: if any flight item's SKU has `age_neutral_class` equal to `PROHIBITED_STATE_LIST` for the shop's home state, the hold is set and publication is blocked. A SKU whose `discontinued` flag is true cannot be added as a new flight item; the attempt is rejected with `ERR_SKU_DISCONTINUED`. Flight items may only be added while the event is in `DRAFT` — adding to an event in any later status is rejected with `ERR_INVALID_STATE` — and reusing a `sequence_no` that is already taken within the same event is rejected with `ERR_DUPLICATE`.

A member (or a `ShopStaff` operator on a member's behalf) books a seat by supplying `member_id` and — because booking mutates the parent event's `seats_booked` and `version` — optionally `expected_event_version`; when present it must match the `TastingEvent`'s current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), while an omitted field skips the stale-version check. Booking is permitted only while the event is `PUBLISHED` (or transiently `RESCHEDULED`) — any other status is rejected with `ERR_BOOKING_WINDOW_CLOSED` — and when any of the event's flight items pours an `ADULT_ONLY_REQUIRED` SKU the member must be `ATTESTED`, otherwise the booking is rejected with `ERR_AGE_ATTESTATION_REQUIRED`. There is no per-member seat limit: the same member may hold multiple seats on one event. The seat begins in `RESERVED` status with a `price_paid_cents` locked in at booking time equal to the event's `flight_price_cents` — no tier discount is applied to seat pricing, and the locked price is never re-priced even if the member's tier later changes — and a system-stamped `booked_at`. No tier snapshot is captured at booking; loyalty accrual uses the member's tier in effect at check-in time.

Confirmation of a `RESERVED` seat transitions it to `CONFIRMED`. Three preconditions guard the transition: the event's status must be `PUBLISHED` or `RESCHEDULED` (not `LOCKED` or any later state — violation surfaces as `ERR_BOOKING_WINDOW_CLOSED`); the booking-time age-attestation rule is re-evaluated — when any flight item pours an `ADULT_ONLY_REQUIRED` SKU the member must be `ATTESTED` (violation surfaces as `ERR_AGE_ATTESTATION_REQUIRED`); and the member's age, computed from `date_of_birth` at the event date, must be at least `min_attendee_age_years` (a shortfall surfaces as `ERR_INVALID_STATE`). Capacity is not re-checked at confirmation — the `RESERVED` seat already occupies a counted slot — so successful confirmation leaves the event's `seats_booked` unchanged, though it does bump the event's `version`.

From `CONFIRMED`, check-in (performed by `ShopStaff` while the event is `IN_SESSION`) transitions the seat to `ATTENDED`. At check-in the seat's `loyalty_points_awarded` is computed: the base is the integer floor of `price_paid_cents` divided by 100, multiplied by the member's tier multiplier at check-in time (`BRONZE` 1.0×, `SILVER` 1.25×, `GOLD` 1.5×, `PLATINUM` 2.0×), rounded half-up to a whole number. The award is credited to the member's `loyalty_points_balance` and `loyalty_points_lifetime` immediately at check-in. If the event reaches `COMPLETED` and a confirmed seat was never checked in, that seat transitions automatically to `NO_SHOW`.

Cancellation is available from `RESERVED` or `CONFIRMED` provided the parent event is not `IN_SESSION` and not `COMPLETED`. Cancelling transitions the seat to `CANCELLED`, decrements the event's `seats_booked` by one, and — if the seat had been `CONFIRMED` — refunds the `price_paid_cents` to the member's `wallet_credit_cents`. A `ShopStaff` operator may additionally refund a `CANCELLED` seat, transitioning it to `REFUNDED` and crediting `price_paid_cents` to the member's `wallet_credit_cents` if the credit was not already issued during cancellation; the member's `loyalty_points_lifetime` is unchanged because no points had yet been awarded for the seat.

### 3.7. Club Plans and Subscriptions

A `ClubPlan` is a subscription template carrying a unique `code` (for example `CURATED-MONTHLY`), a `cadence` (one of `MONTHLY`, `QUARTERLY`, or `ANNUAL`), a `bottles_per_shipment` (at least 1), a `price_cents_per_cycle` (zero or greater), an `allowed_category_ids` whitelist (the categories from which club-curated bottles may be drawn — every id in the list must reference an existing `Category`, and a dangling id is rejected with `ERR_NOT_FOUND`), a `discount_bps_on_retail` in basis points (between 0 and 5000 — applied to all retail orders placed by active subscribers), a `max_active_subscriptions` capacity cap (at least 1), and a computed `active_subscription_count` that tracks how many subscriptions under this plan are currently in `ACTIVE` or `PAST_DUE` status.

A member subscribes by supplying `plan_id`, `member_id`, `started_on`, an optional `trial_days` (defaulting to zero, where zero means no trial), and — because subscribing mutates the plan's `active_subscription_count` and `version` — optionally `expected_plan_version`; when present it must match the `ClubPlan`'s current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), while an omitted field skips the stale-version check. A `Member` actor may only subscribe themselves (`member_id` must equal `X-User-ID`, otherwise `ERR_UNAUTHORIZED`). The subscription's initial `next_billing_on` is `started_on` advanced by one cadence interval. The subscribe is also gated by capacity: the plan's `active_subscription_count` must be strictly less than `max_active_subscriptions`, otherwise the request is rejected with `ERR_CAPACITY_EXCEEDED`. The new `ClubSubscription` begins in `TRIALING` status when `trial_days` is greater than zero, and in `ACTIVE` status otherwise; either way the plan's `active_subscription_count` is incremented by one and the plan's `version` is bumped.

From `TRIALING`, two paths exist. When the logical clock reaches `started_on` plus `trial_days` days, the system automatically transitions the subscription to `ACTIVE` and recomputes the plan's `active_subscription_count`. Alternatively, the member (or `ShopStaff` on their behalf) may cancel — permitted when the actor's `X-User-ID` matches the subscription's `member_id` or the actor is `ShopStaff` — which transitions the subscription to `CANCELLED` and decrements the plan's `active_subscription_count` by one.

From `ACTIVE`, a billing run that fails transitions the subscription to `PAST_DUE` and increments `failed_billing_count` by one. If `failed_billing_count` reaches 3, a system rule automatically transitions the subscription to `EXPIRED`; at that moment the plan's `active_subscription_count` is decremented by one and the member immediately loses the club discount — no future `DRAFT` order carries an `applied_club_subscription_id` from that subscription. A successful billing run against a `PAST_DUE` subscription returns it to `ACTIVE`, resets `failed_billing_count` to zero, and advances `next_billing_on` per the plan's cadence. From `ACTIVE`, the member or `ShopStaff` may also pause the subscription — recording an optional `pause_reason` — which transitions it to `PAUSED`; resuming from `PAUSED` returns it to `ACTIVE` (clearing `pause_reason`) and recomputes `next_billing_on` as the later of today and `started_on` plus the smallest whole number of cadence intervals that lands on or after today. Finally, from `ACTIVE` — and likewise from `PAST_DUE` or `PAUSED` — the member or `ShopStaff` may cancel outright, transitioning to `CANCELLED`; the plan's `active_subscription_count`, which counts only `ACTIVE` and `PAST_DUE` subscriptions, is decremented by one when the cancelled subscription was counted in it.

The cadence arithmetic on a successful billing run is as follows: the cadence in months is 1 for `MONTHLY`, 3 for `QUARTERLY`, and 12 for `ANNUAL`. The candidate next-billing date is the current `next_billing_on` advanced by that many months. If the candidate falls strictly before today — catch-up after a pause — the system keeps advancing by the cadence interval until the candidate is on or after today, and that final value becomes the new `next_billing_on`.

A `PlatformAdmin` may also drive a billing simulation against any subscription by supplying a `club_subscription_id` and an `outcome` (one of `SUCCEEDED` or `FAILED`); a `SUCCEEDED` outcome — permitted while the subscription is `ACTIVE`, `PAST_DUE`, or `TRIALING` — advances `next_billing_on` per the cadence rule above, resets `failed_billing_count`, and returns a `PAST_DUE` or `TRIALING` subscription to `ACTIVE`, while a `FAILED` outcome — permitted only from `ACTIVE` or `PAST_DUE` — increments `failed_billing_count` and may trigger the automatic `EXPIRED` transition at the third failure.

### 3.8. Orders — Retail and DTC

An `Order` belongs to exactly one `Member` via `member_id`. At creation the order carries a `channel` (one of `RETAIL` for in-store pickup or `DTC` for direct-to-consumer shipment), an optional `ship_to_state_code` (required for `DTC`; on a `RETAIL` order a supplied value is stored but never used), an optional `loyalty_points_redeemed` defaulting to zero (one hundred points equal one dollar, so each point redeemed is one cent of discount), and an optional `applied_club_subscription_id` linking to the member's currently-active subscription if one exists (this drives the club discount). An `applied_club_subscription_id` referencing another member's subscription is rejected with `ERR_INVALID_REQUEST`; one referencing a subscription that is not currently `ACTIVE` is rejected with `ERR_INVALID_STATE`. A freshly created order starts with `payment_status` set to `UNPAID` and `fulfillment_status` set to `DRAFT` — these two dimensions evolve in parallel. The full `payment_status` enumeration is `UNPAID`, `AUTHORIZED`, `CAPTURED`, `REFUNDED_PARTIAL`, `REFUNDED_FULL`, and `VOIDED`; the full `fulfillment_status` enumeration is `DRAFT`, `PICKING`, `PACKED`, `SHIPPED`, `DELIVERED`, `PICKED_UP`, and `CANCELLED`.

Order lines are added while the order is `DRAFT`. Each `OrderLine` references the order via `order_id` and the SKU via `sku_id`, and carries a `qty` (at least 1), a `unit_price_cents` locked at creation, an `extended_price_cents` computed as the per-line rounded multiplication, and a `lot_allocation` list (empty until the order is submitted). Adding or removing a line recomputes the order's `subtotal_cents` and bumps the order's `version` by one.

The per-line pricing rule runs as follows. For each line, the list price is the SKU's `base_price_cents`. If the order has an `applied_club_subscription_id` (which must reference a currently `ACTIVE` subscription), the line's `unit_price_cents` is the list price multiplied by the quantity (10000 minus the plan's `discount_bps_on_retail`) and divided by 10000, rounded half-up to a whole cent. Otherwise the `unit_price_cents` equals the list price unchanged. The line's `extended_price_cents` is `unit_price_cents` multiplied by `qty`. The order's `subtotal_cents` is the sum of `extended_price_cents` across all lines — per-line rounding wins, and no cross-line reallocation is performed. This is an explicit design choice: the sum of per-line-rounded extended prices must equal the order's `subtotal_cents` exactly.

Loyalty redemption applies after the subtotal. Each point in `loyalty_points_redeemed` converts to one cent of discount — one hundred points equal one hundred cents, one dollar. The conversion produces the loyalty-discount portion of the order's `discount_cents`. At submit time the member's `loyalty_points_balance` must be greater than or equal to `loyalty_points_redeemed`, otherwise the submit is rejected with `ERR_INSUFFICIENT_POINTS`.

Shipping applies only to `DTC` orders. The shipping charge has three components summed together: a flat base of 500 cents, plus 150 cents per bottle where the bottle count is the sum of `qty` across all lines, plus the destination state's `surcharge_cents_per_order`. The server does not enforce a minimum line count on an order, so the bottle count may be zero; the flat base and the destination state's surcharge apply to a `DTC` order regardless of bottle count. For `RETAIL` orders the shipping charge is zero.

Tax is computed after loyalty redemption and shipping are known. The taxable base is `subtotal_cents` minus the loyalty-discount cents plus the shipping charge. The tax amount is this taxable base multiplied by the destination state's `tax_rate_bps` and divided by 10000, rounded half-up to a whole cent. A state whose `tax_rate_bps` is zero produces a tax of zero. For `RETAIL` orders, the destination-state rule used for tax is the shop's home state rule — for the purposes of this specification the shop is pinned to California, so retail orders tax at the California rate. For `DTC` orders the tax rate comes from the destination state's rule.

The grand total is then `subtotal_cents` minus `discount_cents` plus `shipping_charge_cents` plus `tax_cents`. This invariant is maintained at the line level — the grand total always reconciles with the sum of per-line extended prices, the loyalty redemption, the shipping charge, and the tax, with no residual rounding remainder.

Submission of a `DRAFT` order is the heavyweight operation. The member (or `ShopStaff` on their behalf) submits optionally carrying `expected_order_version`; when present it must match the order's current `version` — a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) — and when omitted no stale-version check is performed. Submission then enforces, in the priority order from §2.7, a battery of business rules. There is no minimum line count — an order with zero lines may be submitted. Every line's SKU must have `discontinued` equal to false — adding a discontinued SKU is rejected with `ERR_SKU_DISCONTINUED`. Every line's SKU must be permitted for sale to this member given their `age_attestation_status` and the order's `ship_to_state_code` if the channel is `DTC` — a line whose SKU is `ADULT_ONLY_REQUIRED` requires the member to be `ATTESTED`, otherwise the submission is rejected with `ERR_AGE_ATTESTATION_REQUIRED`. For `DTC` orders a `ShippingStateRule` row must exist for the destination state — if none exists the submission is rejected with `ERR_NOT_FOUND` — and the destination state's `allows_dtc` flag must be true — a false value is rejected with `ERR_DTC_STATE_PROHIBITED`. Every line's `abv_basis_points` must be at or below the destination state's `abv_cap_basis_points` — an excess is rejected with `ERR_SKU_ABV_STATE_EXCEEDED`. The SKU's `ship_state_overrides` must not contain a `PROHIBITED` entry for the destination state, and the SKU's category must not be on the state's prohibited list — a violation is rejected with `ERR_SKU_STATE_PROHIBITED`. The member's `loyalty_points_balance` must cover `loyalty_points_redeemed` — an insufficiency is rejected with `ERR_INSUFFICIENT_POINTS`. Finally, the FEFO lot walk must be able to satisfy every line from non-expired, non-quarantined lots — an insufficiency is rejected with `ERR_INSUFFICIENT_INVENTORY`. On a `RETAIL` order a `ShopStaff` (or `PlatformAdmin`) submitter may include `"override": true` in the submit request body to let the walk allocate from `QUARANTINED` lots; no equivalent override exists for `DTC`.

Successful submission transitions the order from `DRAFT` to `PICKING` on the fulfillment axis, sets `payment_status` to `AUTHORIZED`, deducts `loyalty_points_redeemed` from the member's `loyalty_points_balance`, runs the lot-allocation walk to populate each line's `lot_allocation` (decrementing `InventoryLot.qty_remaining` and recomputing `on_hand_cached` for affected SKUs), recomputes the order's totals, and bumps the order's `version` by one.

From `PICKING` a `ShopStaff` operator packs the order, transitioning `fulfillment_status` to `PACKED` and bumping `version`. From `PACKED` the path diverges by channel. For a `DTC` order, a `ShopStaff` operator creates a shipment by supplying a `carrier`, a `tracking_no`, a `shipped_on` date, and an optional `club_subscription_id` if this dispatch is a club-cycle shipment rather than an ad-hoc order — the new `Shipment` begins in `LABEL_CREATED` status and the order's `fulfillment_status` transitions to `SHIPPED`. Because shipment creation requires the order to be `PACKED` and moves it to `SHIPPED`, an order has at most one shipment; attempting to create a shipment on a non-`DTC` order, or to record pickup on a non-`RETAIL` order, is rejected with `ERR_INVALID_STATE`. For a `RETAIL` order, a `ShopStaff` operator records pickup, which transitions `fulfillment_status` to `PICKED_UP`, sets `payment_status` to `CAPTURED`, credits the member's `loyalty_points_earned` (to both `loyalty_points_balance` and `loyalty_points_lifetime`), and bumps `version`.

Cancellation is available from `DRAFT` and from `PICKING`. From `DRAFT`, either the member or `ShopStaff` may cancel; the member's `loyalty_points_balance` is credited with `loyalty_points_redeemed` (this credit is applied even though a `DRAFT` order never had the points deducted at submission) and the order transitions to `CANCELLED`. From `PICKING`, only `ShopStaff` may cancel, and only while `payment_status` is `AUTHORIZED` or `UNPAID`; the cancellation restores `InventoryLot.qty_remaining` for every entry in every line's `lot_allocation`, recomputes `on_hand_cached` for the affected SKUs, sets `payment_status` to `VOIDED`, reverses the loyalty redemption, and transitions the order to `CANCELLED`.

### 3.9. Shipments and Loyalty Accrual

A `Shipment` belongs to exactly one `Order` via `order_id`, and optionally to a `ClubSubscription` via `club_subscription_id` when the dispatch is part of a club cycle. The shipment carries a `carrier`, a `tracking_no`, a `shipped_on` date, an optional `delivered_on` date (defaulting to null), and a `status` that walks through `LABEL_CREATED`, `IN_TRANSIT`, `OUT_FOR_DELIVERY`, `DELIVERED`, `RETURNED`, and `LOST`.

From `LABEL_CREATED` the shipment moves to `IN_TRANSIT`, then to `OUT_FOR_DELIVERY`. From `OUT_FOR_DELIVERY` it may reach `DELIVERED` — a `ShopStaff` or `PlatformAdmin` operator supplies a `delivered_on` date — which bubbles up to the parent order: the order's `payment_status` transitions to `CAPTURED`, the order's `fulfillment_status` transitions to `DELIVERED`, the member's `loyalty_points_balance` is incremented by the order's `loyalty_points_earned`, the member's `loyalty_points_lifetime` is incremented by the same amount, and — if the shipment's `club_subscription_id` is set — the subscription's `shipments_fulfilled` counter is incremented by one.

The order's `loyalty_points_earned` is computed as one point per dollar of `grand_total_cents`, with the member's tier multiplier applied before rounding half-up to a whole point; it is recomputed every time the order's totals are recomputed, using the member's tier in effect at that moment.

From `IN_TRANSIT` the shipment may alternatively be marked `RETURNED`, which transitions the parent order's `payment_status` to `REFUNDED_FULL`, restores the lot allocation, and claws back the loyalty points that had been earned on the order (decrementing `loyalty_points_lifetime` — the only path in the system that reduces this otherwise monotonic counter). From `OUT_FOR_DELIVERY` the shipment may be marked `LOST`, which likewise sets the order's `payment_status` to `REFUNDED_FULL` and claws back the loyalty points, but does not restore the lot allocation — the bottles are gone. Both transitions also credit any `loyalty_points_redeemed` back to the member's `loyalty_points_balance`, leave the order's `fulfillment_status` untouched (it remains `SHIPPED`), and claw back earned points only if they were actually credited — an order whose points were never credited has nothing clawed back.

### 3.10. Special Orders

A member may file a `SpecialOrder` for a bottle the shop does not currently carry. The request carries the `member_id`, a free-form `requested_sku_code` (the code or name the member has in mind, resolved to a real SKU later), a `quantity` (at least 1), and a `deposit_cents` (zero or greater). The new special order begins in `REQUESTED` status, with `resolved_sku_id`, `approved_by_user_id`, and `decline_reason` all defaulting to null.

A `ShopStaff` operator may approve a `REQUESTED` special order by supplying a `resolved_sku_id` (the SKU the request is being linked to) and an `approved_by_user_id`. Approval enforces segregation of duties — the `approved_by_user_id` must differ from the requesting `member_id`, with violation rejected as `ERR_SEGREGATION_OF_DUTIES` — and requires that the resolved SKU's `discontinued` flag be false. It also places a wallet hold: the member's `wallet_credit_cents` is decremented by `deposit_cents`, which requires the wallet to have at least `deposit_cents` available — an insufficiency is rejected with `ERR_INSUFFICIENT_WALLET`. Successful approval transitions the special order to `APPROVED`.

From `APPROVED` the operator marks the order `SOURCED` once the bottle is located (a status change only — no inventory is created at this step), and then marks it `RECEIVED` once the bottles physically arrive — receiving takes `lot_code`, `qty_received`, `unit_cost_cents`, and `expires_on` and creates a new `InventoryLot` under the resolved SKU carrying the given quantities (reusing an existing `(sku_id, lot_code)` pair is rejected with `ERR_DUPLICATE`). From `RECEIVED` the operator fulfills the order — the transition requires only that the special order is `RECEIVED`; no linked consuming order is checked — at which point the special order transitions to `FULFILLED` and the member's `loyalty_points_balance` is credited with a bonus of ten points per bottle (ten multiplied by `quantity`; the bonus touches the balance only — `loyalty_points_lifetime` and tier are unaffected). From `REQUESTED` the operator may alternatively decline the request — `decline_reason` is required to be non-empty — transitioning the special order to `DECLINED` with no side effects. From `APPROVED` either the member or `ShopStaff` may cancel, transitioning the special order to `CANCELLED` and forfeiting the deposit held in `wallet_credit_cents` to the shop.

### 3.11. Shipping State Rules

Each `ShippingStateRule` row captures the regulatory posture of one US state. It carries a unique two-letter `state_code`, an `allows_dtc` flag (when false, no `DTC` order may ship to this state — submission is rejected with `ERR_DTC_STATE_PROHIBITED`), a `min_age_years` (the minimum recipient age for `ADULT_ONLY_*` SKUs in this state; a value of zero indicates a fully-open state — the field is required at creation and no server-side default is applied), an `abv_cap_basis_points` (the maximum ABV in basis points permitted for `DTC` shipments into this state — a SKU above this cap triggers `ERR_SKU_ABV_STATE_EXCEEDED`), an optional `surcharge_cents_per_order` (a flat state-mandated surcharge, defaulting to zero), and a `tax_rate_bps` (the destination-based sales-tax rate in basis points, between 0 and 5000). These rules are read on every `DTC` submission and on every order-total computation.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications to existing resources are returned with HTTP 200; deletions are returned with HTTP 204. All responses use the envelope defined in §2.2. The roles column below lists every role permitted to invoke the endpoint; any other role receives `ERR_UNAUTHORIZED`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/nabs/categories` | Create a category | PlatformAdmin, ShopStaff |
| GET | `/nabs/categories` | List categories | PlatformAdmin, ShopStaff, Member, Anonymous |
| GET | `/nabs/categories/{id}` | Fetch one category | PlatformAdmin, ShopStaff, Member, Anonymous |
| GET | `/nabs/categories/{id}/skus` | SKUs under a category | PlatformAdmin, ShopStaff, Member, Anonymous |
| POST | `/nabs/skus` | Create a SKU under a category | PlatformAdmin, ShopStaff |
| GET | `/nabs/skus` | List SKUs | PlatformAdmin, ShopStaff, Member, Anonymous |
| GET | `/nabs/skus/{id}` | Fetch one SKU | PlatformAdmin, ShopStaff, Member, Anonymous |
| PATCH | `/nabs/skus/{id}` | Update a SKU (e.g., discontinue) | PlatformAdmin, ShopStaff |
| GET | `/nabs/skus/{id}/flight-items` | Flight items pouring this SKU | PlatformAdmin, ShopStaff |
| GET | `/nabs/skus/{id}/special-orders` | Special orders resolved to this SKU | PlatformAdmin, ShopStaff |
| GET | `/nabs/skus/{id}/order-lines` | Order lines containing this SKU | PlatformAdmin, ShopStaff |
| POST | `/nabs/skus/{id}/lots` | Receive a new lot | PlatformAdmin, ShopStaff |
| GET | `/nabs/skus/{id}/lots` | Lots under a SKU | PlatformAdmin, ShopStaff |
| GET | `/nabs/lots/{id}` | Fetch one lot | PlatformAdmin, ShopStaff |
| POST | `/nabs/lots/{id}/quarantine` | Quarantine a lot | ComplianceOfficer |
| POST | `/nabs/lots/{id}/release-quarantine` | Release a quarantined lot | ComplianceOfficer |
| POST | `/nabs/members` | Register a member | Anonymous, PlatformAdmin, ShopStaff |
| GET | `/nabs/members` | List members | PlatformAdmin, ShopStaff, ComplianceOfficer |
| GET | `/nabs/members/{id}` | Fetch a member | PlatformAdmin, ShopStaff, ComplianceOfficer, Member |
| GET | `/nabs/members/{id}/orders` | Orders of a member | PlatformAdmin, ShopStaff, Member |
| GET | `/nabs/members/{id}/club-subscriptions` | Subscriptions of a member | PlatformAdmin, ShopStaff, Member |
| GET | `/nabs/members/{id}/special-orders` | Special orders of a member | PlatformAdmin, ShopStaff, Member |
| GET | `/nabs/members/{id}/attestations` | Attestations of a member | PlatformAdmin, ShopStaff, ComplianceOfficer, Member |
| POST | `/nabs/members/{id}/wallet/adjustments` | Adjust wallet credit | PlatformAdmin, ShopStaff |
| GET | `/nabs/members/{id}/tasting-events` | Tasting events hosted by this member | PlatformAdmin, ShopStaff, Member |
| GET | `/nabs/members/{id}/tasting-seats` | Tasting seats held by this member | PlatformAdmin, ShopStaff, Member |
| POST | `/nabs/members/{id}/attestations` | Submit an attestation | ShopStaff, ComplianceOfficer |
| POST | `/nabs/members/{id}/attestations/{att_id}/approve` | Approve attestation | ComplianceOfficer |
| POST | `/nabs/members/{id}/attestations/{att_id}/reject` | Reject attestation | ComplianceOfficer |
| POST | `/nabs/members/{id}/attestations/revoke` | Revoke attestation | ComplianceOfficer |
| POST | `/nabs/club-plans` | Create a club plan | PlatformAdmin |
| GET | `/nabs/club-plans` | List club plans | PlatformAdmin, ShopStaff, Member, Anonymous |
| GET | `/nabs/club-plans/{id}` | Fetch a club plan | PlatformAdmin, ShopStaff, Member, Anonymous |
| GET | `/nabs/club-plans/{id}/subscriptions` | Subscriptions under a plan | PlatformAdmin, ShopStaff |
| POST | `/nabs/club-subscriptions` | Subscribe a member to a plan | Member, ShopStaff, PlatformAdmin |
| GET | `/nabs/club-subscriptions/{id}` | Fetch a subscription | PlatformAdmin, ShopStaff, Member |
| POST | `/nabs/club-subscriptions/{id}/pause` | Pause a subscription | Member, ShopStaff |
| POST | `/nabs/club-subscriptions/{id}/resume` | Resume a subscription | Member, ShopStaff |
| POST | `/nabs/club-subscriptions/{id}/cancel` | Cancel a subscription | Member, ShopStaff |
| POST | `/nabs/tasting-events` | Create a tasting event | ShopStaff, PlatformAdmin |
| GET | `/nabs/tasting-events` | List events | PlatformAdmin, ShopStaff, Member, Anonymous |
| GET | `/nabs/tasting-events/{id}` | Fetch an event | PlatformAdmin, ShopStaff, Member, Anonymous |
| GET | `/nabs/tasting-events/{id}/flight-items` | Flight items under an event | PlatformAdmin, ShopStaff, Member, Anonymous |
| GET | `/nabs/tasting-events/{id}/seats` | Seats under an event | PlatformAdmin, ShopStaff, Member |
| POST | `/nabs/tasting-events/{id}/flight-items` | Add a flight item to an event | ShopStaff |
| POST | `/nabs/tasting-events/{id}/publish` | Publish an event | ShopStaff |
| POST | `/nabs/tasting-events/{id}/cancel` | Cancel an event | ShopStaff |
| POST | `/nabs/tasting-events/{id}/reschedule` | Reschedule a locked event | ShopStaff |
| POST | `/nabs/tasting-events/{id}/seats` | Book a seat | Member, ShopStaff |
| POST | `/nabs/tasting-seats/{id}/confirm` | Confirm a reserved seat | Member, ShopStaff |
| POST | `/nabs/tasting-seats/{id}/cancel` | Cancel a seat | Member, ShopStaff |
| POST | `/nabs/tasting-seats/{id}/check-in` | Check in an attendee | ShopStaff |
| POST | `/nabs/tasting-seats/{id}/refund` | Refund a cancelled seat | ShopStaff |
| GET | `/nabs/tasting-seats/{id}` | Fetch a seat | PlatformAdmin, ShopStaff, Member |
| POST | `/nabs/special-orders` | Submit a special-order request | Member, ShopStaff |
| GET | `/nabs/special-orders/{id}` | Fetch a special order | PlatformAdmin, ShopStaff, Member |
| POST | `/nabs/special-orders/{id}/approve` | Approve and link to a SKU | ShopStaff |
| POST | `/nabs/special-orders/{id}/decline` | Decline a special order | ShopStaff |
| POST | `/nabs/special-orders/{id}/mark-sourced` | Mark a special order sourced | ShopStaff |
| POST | `/nabs/special-orders/{id}/receive` | Mark a special order received | ShopStaff |
| POST | `/nabs/special-orders/{id}/fulfill` | Mark a special order fulfilled | ShopStaff |
| POST | `/nabs/special-orders/{id}/cancel` | Cancel an approved special order | Member, ShopStaff |
| POST | `/nabs/orders` | Create an empty draft order | Member, ShopStaff |
| GET | `/nabs/orders` | List orders | PlatformAdmin, ShopStaff, Member |
| GET | `/nabs/orders/{id}` | Fetch an order | PlatformAdmin, ShopStaff, Member |
| GET | `/nabs/orders/{id}/lines` | Lines under an order | PlatformAdmin, ShopStaff, Member |
| POST | `/nabs/orders/{id}/lines` | Add a line to a draft order | Member, ShopStaff |
| DELETE | `/nabs/orders/{id}/lines/{line_id}` | Remove a line from a draft order | Member, ShopStaff |
| POST | `/nabs/orders/{id}/submit` | Submit a draft order | Member, ShopStaff |
| POST | `/nabs/orders/{id}/pack` | Mark an order packed | ShopStaff |
| POST | `/nabs/orders/{id}/pickup` | Mark an order picked up (retail) | ShopStaff |
| POST | `/nabs/orders/{id}/cancel` | Cancel a draft or picking order | Member, ShopStaff |
| POST | `/nabs/orders/{id}/shipments` | Create a shipment for a packed DTC order | ShopStaff |
| GET | `/nabs/shipments/{id}` | Fetch a shipment | PlatformAdmin, ShopStaff, Member |
| GET | `/nabs/orders/{id}/shipments` | Shipments of an order | PlatformAdmin, ShopStaff, Member |
| GET | `/nabs/club-subscriptions/{id}/shipments` | Shipments of a club subscription | PlatformAdmin, ShopStaff, Member |
| GET | `/nabs/club-subscriptions/{id}/orders` | Orders placed under a club subscription | PlatformAdmin, ShopStaff, Member |
| POST | `/nabs/shipments/{id}/mark-in-transit` | Mark a shipment in transit | ShopStaff, PlatformAdmin |
| POST | `/nabs/shipments/{id}/mark-out-for-delivery` | Mark a shipment out for delivery | ShopStaff, PlatformAdmin |
| POST | `/nabs/shipments/{id}/mark-delivered` | Mark a shipment delivered | ShopStaff, PlatformAdmin |
| POST | `/nabs/shipments/{id}/mark-returned` | Mark a shipment returned | ShopStaff, PlatformAdmin |
| POST | `/nabs/shipments/{id}/mark-lost` | Mark a shipment lost | ShopStaff, PlatformAdmin |
| POST | `/nabs/shipping-state-rules` | Create a state rule | PlatformAdmin, ComplianceOfficer |
| GET | `/nabs/shipping-state-rules` | List state rules | PlatformAdmin, ShopStaff, ComplianceOfficer, Member, Anonymous |
| GET | `/nabs/shipping-state-rules/{id}` | Fetch a state rule | PlatformAdmin, ShopStaff, ComplianceOfficer |
| POST | `/nabs/_clock/set_current_utc` | Set the logical UTC clock | PlatformAdmin |
| POST | `/nabs/_billing/simulate` | Simulate a billing run | PlatformAdmin |

## 5. Error Code Catalogue

The table below lists every error code the API may return. Trigger conditions for each error are described in the §2 and §3 narratives.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE` | 409 |
| `ERR_AGE_ATTESTATION_REQUIRED` | 422 |
| `ERR_COMPLIANCE_HOLD` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_BOOKING_WINDOW_CLOSED` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_DTC_STATE_PROHIBITED` | 422 |
| `ERR_SKU_ABV_STATE_EXCEEDED` | 422 |
| `ERR_SKU_STATE_PROHIBITED` | 422 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_INSUFFICIENT_INVENTORY` | 422 |
| `ERR_INSUFFICIENT_WALLET` | 422 |
| `ERR_SKU_DISCONTINUED` | 422 |
