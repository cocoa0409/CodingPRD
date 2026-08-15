# Industrial Fastener VMI API — Product Requirements Document

## 1. Introduction

Industrial fastener distribution increasingly runs on vendor-managed inventory: the distributor, not the customer, owns the responsibility of keeping assembly-plant bins stocked. Route representatives visit each customer site on a schedule, scan the physical count in every bin, and the programme decides what to replenish, how to price it, and when credit or certification concerns should hold a shipment back. When this discipline slips, the consequences are asymmetric — a two-cent missing fastener can idle a production line, while overstocked bins quietly erode the distributor's margin. This document specifies the REST API behind such a VMI bin programme, mounted under `/vmi`, covering the full operating loop from bin sizing and scan-based replenishment through pricing, credit control, lot traceability, kitting, and end-of-life obsolescence.

The API serves three operator populations on the distributor side. Administrators curate the parts catalogue, negotiate bin agreements, and govern credit and certification. Route drivers execute scan routes and deliver stock to the dock or directly to the line side. Warehouse operators run kitting and bagging jobs that package mixed fasteners into assembly-ready kits. Throughout, the system treats inventory quantities, money, and certification status as strictly reconciled ledgers: every scan, delivery, dispute, and packaging run leaves the bin posture, the site's outstanding balance, and the distributor's stock figures in a state that can be re-derived from source records.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, timekeeping, resource identity, monetary precision, concurrency control, the request-validation pipeline, and the inventory-conservation invariants that every workflow in §3 relies on.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403); the per-endpoint role assignments are listed in §4.

The system recognizes exactly three roles:

- `DistributorAdmin` — the distributor-side administrator who owns the catalogue, bin agreements, pricing, credit, certification records, and the order lifecycle, and who alone may schedule routes, set the logical clock, and run the certificate-expiry sweep.
- `RouteDriver` — the distributor's field representative who starts, cancels, and closes scan routes, registers and submits bin counts, delivers orders, and raises count disputes.
- `WarehouseOperator` — warehouse staff who create kitting jobs and drive the picking, holding, packing, completion, and scrapping lifecycle.

All three roles use opaque identities. When `X-User-Role` is `DistributorAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `RouteDriver`, and likewise when `X-User-Role` is `WarehouseOperator`: in each case `X-User-ID` is an opaque operator identifier with no entity backing, recorded nowhere as a foreign key and never matched against a resource's `id`.

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

Paths are matched with or without a trailing slash. A request to an undefined path surfaces `ERR_NOT_FOUND` (HTTP 404) in the same envelope; a defined path called with an unsupported method surfaces the same `error_id` with HTTP 405; an unexpected server failure surfaces `ERR_INVALID_REQUEST` (HTTP 400).

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`; on list endpoints this query-parameter validation runs after the authorization check. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items returned is below `total_count`.

### 2.4. The Logical Clock

All time-sensitive evaluation in the system reads a server-side logical clock, never wall-clock time. Before any operator call to the clock-setting capability, the logical clock reads exactly 2026-08-01T00:00:00Z. A `DistributorAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant — in either direction, with no monotonic-advance requirement — and returns the supplied string verbatim as `current_utc`; setting the clock mutates no entity by itself. Two subsystems consume the logical clock: route starts compare it against the route's receiving window (§3.3), and certificate expiry is evaluated against it by the expiry sweep (§3.5). Because the clock never falls back to wall-clock time, tests and operations are fully deterministic.

### 2.5. Common Resource Properties and Entity Identity

Every primary resource — customer sites, parts, bin agreements, replenishment routes, route stops, replenishment orders, lot certificates, and kit jobs — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments by one on every mutation, including mutations caused by cascades originating on another entity. When one operation advances several resources — for example, an order confirmation that touches the order, its agreement, and its site — each affected resource's `version` increments independently and each `updated_at` refreshes.

Part cross-references are the deliberate exception: a cross-reference is a lightweight declaration that is only ever deactivated, never edited, so it carries `id` and `created_at` only — both `updated_at` and `version` are absent from it.

### 2.6. Money, Quantities, and Rounding Discipline

All monetary values are integer cents; the API never accepts or emits fractional currency. Three distinct rounding regimes apply, and each calculation in §3 names the regime it uses. Volume-tier discounts on catalogue prices are computed with truncating integer division, discarding any fractional cent toward zero. Advisory bin-sizing figures and per-line packaging charges round up to the next whole piece or whole cent. Site balance rollups are exact integer-cent sums with no rounding at all. Separately, an order's price is fixed at the moment the order is created and is never recomputed afterward, even if the underlying catalogue price or agreement pricing later changes.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both use the same rejection: `ERR_STALE_VERSION` (HTTP 412).

First, the bin-agreement update operation — the one that adjusts sizing and pricing fields — requires the request body to carry `expected_bin_agreement_version`, holding the agreement `version` the client last observed. If the agreement's current `version` has advanced beyond that value — because a scan submission, an order confirmation, or a posture auto-transition has legitimately mutated the agreement since the client read it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than allowed to overwrite a state the client never saw.

Second, scheduling a new replenishment route requires the request body to carry `expected_site_version`, holding the site `version` the client last observed. If the site's current `version` has advanced — because another writer changed the site's credit or delivery configuration, or an earlier route scheduling advanced it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so a route is never scheduled against a stale site snapshot.

No other endpoint accepts a version field; these two are the complete set of OCC-guarded writes.

### 2.8. Request Validation Pipeline and Nested Resource Retrieval

Every request passes through a single validation pipeline whose stages run in a fixed order, so that earlier failures mask later ones deterministically. The stages, in evaluation order, are: (1) authentication — the headers check of §2.1, surfacing `ERR_UNAUTHENTICATED`; (2) request shape — every required input field present, types matching the entity schema, enum values within their declared sets, and `flat_bin_price_cents` present exactly when `pricing_mode` is `COST_PER_BIN`, surfacing `ERR_INVALID_REQUEST`; (3) authorization — the acting role permitted on the endpoint per §4, surfacing `ERR_UNAUTHORIZED`; (4) existence — every path identifier and every foreign key in the request body must reference an existing entity, validated left-to-right (site before route, route before stop, part before cross-reference), surfacing `ERR_NOT_FOUND` for the first identifier that does not resolve; (5) transition legality — the target resource must be in a state from which the requested transition exists, surfacing `ERR_INVALID_STATE`, which also covers terminal-state lockdown and idempotent re-triggers; (6) live-parent requirements — retired sites and agreements block dependent writes, surfacing `ERR_AGREEMENT_OR_SITE_RETIRED`; (7) uniqueness, surfacing `ERR_DUPLICATE`; (8) substitution rules, surfacing `ERR_NO_SUBSTITUTE`; (9) route-window overlap, surfacing `ERR_ROUTE_WINDOW_OVERLAP`; (10) station-window conflict, surfacing `ERR_STATION_WINDOW_CONFLICT`; (11) the certification gate, surfacing `ERR_CERTIFICATION_BLOCKED`; (12) count and quantity bounds, surfacing `ERR_QUANTITY_OUT_OF_BOUNDS`; (13) kit stock sufficiency, surfacing `ERR_INSUFFICIENT_STOCK`; (14) the credit gate, surfacing `ERR_CREDIT_LIMIT_EXCEEDED`; and finally (15) optimistic-concurrency staleness, surfacing `ERR_STALE_VERSION`. A request that would fail several stages receives the error from the earliest stage in this ordering.

### 2.9. Inventory Conservation and Bin Posture Reconciliation

The distributor's stock of each part obeys a strict conservation invariant: for every part, `reserved_qty` plus `available_qty` always equals `total_stock_qty`. Kit-job reservations move quantity from `available_qty` into `reserved_qty`; kit completion removes reserved stock from the building by dropping `reserved_qty` and `total_stock_qty` together; kit scrapping releases the reservation back into availability. No operation may leave the invariant broken.

Each bin agreement continuously maintains a posture derived from two figures: `on_hand_qty`, the last scanned quantity as adjusted by deliveries and dispute pull-backs (it is maintained exclusively by scan submissions, deliveries, and disputes — never written directly), and `open_order_qty`, the sum of ordered quantities over the agreement's orders currently in `CONFIRMED` or `IN_TRANSIT` status. After any event that changes either figure — a scan submission, an order confirmation, a delivery, a cancellation, a dispute, or a sizing update — the system recomputes the posture: when `on_hand_qty` plus `open_order_qty` reaches or exceeds `max_qty`, the agreement auto-transitions from `ACTIVE` to `AT_CAPACITY`; when the sum falls below `max_qty`, it auto-transitions from `AT_CAPACITY` back to `ACTIVE`. Each auto-transition increments the agreement's `version` and refreshes `updated_at` without requiring any explicit client request on the agreement.

A parallel rollup keeps each site's `outstanding_balance_cents` exact: it is the integer-cent sum of `total_price_cents` over every replenishment order belonging to the site whose status is `CONFIRMED` or `IN_TRANSIT`, recomputed from source rows on every contributing transition — confirmation debits, hold-cancellation credits, and delivery settlements. Orders in `DRAFT`, `ON_HOLD`, `DISPUTED`, `DELIVERED`, or `CANCELLED` status contribute nothing to the balance.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Customer Sites and the Parts Catalogue

A `DistributorAdmin` onboards a customer plant by creating a customer site with a human-readable `name`, a `ship_to_code` that uniquely identifies the shipping location, a `credit_limit_cents` fixing the maximum outstanding confirmed-order value the site may carry (zero or positive — a negative value fails the shape check with `ERR_INVALID_REQUEST`), and a `delivery_mode` of either `DOCK_TO_STOCK` or `LINE_SIDE` that declares how replenishment is fulfilled at that site by default. The `ship_to_code` must be unique across all sites regardless of status; a collision is rejected with `ERR_DUPLICATE`. A new site begins in `ACTIVE` status with `outstanding_balance_cents` at zero. Sites can be listed with an optional `status` filter alongside the pagination parameters.

The parts catalogue is likewise administered by a `DistributorAdmin`. Each part is created with a distributor `sku` (unique across all parts in any status, with duplicates rejected as `ERR_DUPLICATE`), a free-text `description`, an `is_critical` flag that defaults to false and marks fasteners requiring lot traceability and certification on every delivery, a catalogue `unit_price_cents` of at least one cent, and a `total_stock_qty` recording physical distributor stock on hand (zero or positive); a `unit_price_cents` below one cent or a negative `total_stock_qty` fails the shape check with `ERR_INVALID_REQUEST`. At creation `available_qty` is initialized to the full `total_stock_qty` and `reserved_qty` starts at zero; both are thereafter maintained by the kitting workflows of §3.6. A part starts `ACTIVE`; once it becomes `OBSOLETE` it can no longer be added to new bin agreements or kit jobs. Parts can also be listed with an optional `status` filter.

Because fastener catalogues are full of functional equivalents, the programme supports declared substitutions. A `DistributorAdmin` registers a part cross-reference naming a `from_part_id` — the requested part that may be substituted — and a `to_part_id` — the substitute that may ship instead — together with a `priority_rank` of at least 1 (a lower value fails the shape check with `ERR_INVALID_REQUEST`) expressing substitution preference: lower ranks are tried first, and ties are broken by `created_at` ascending. A cross-reference whose `is_active` flag is false is never selected by substitution; the flag defaults to true. Declaring a cross-reference from a part to itself is rejected with `ERR_NO_SUBSTITUTE`, and declaring the same (`from_part_id`, `to_part_id`) pair twice is rejected with `ERR_DUPLICATE`. Cross-references are listable and filterable by either endpoint part via the `from_part_id` and `to_part_id` query parameters.

### 3.2. Bin Agreements: Sizing, Pricing Modes, and Capacity Posture

The bin agreement is the commercial heart of the programme: it binds one part to one bin location at one customer site and declares how replenishment for that bin is priced. A `DistributorAdmin` creates an agreement by supplying the `site_id` of the site, the `part_id` of the stocked fastener, a free-text `bin_location` label (aisle and shelf), a `pricing_mode` of `UNIT_PRICE` or `COST_PER_BIN`, a `min_qty` reorder point, and a `max_qty` bin capacity. The reorder point must be zero or positive and strictly below `max_qty`, which must be at least 1; violations are rejected with `ERR_QUANTITY_OUT_OF_BOUNDS`. Under `COST_PER_BIN` pricing a `flat_bin_price_cents` of zero or more is required — it is the flat per-trip charge, and a negative value fails the shape check with `ERR_INVALID_REQUEST` — while under `UNIT_PRICE` pricing the field carries no effect and defaults to 0; per §2.8 the shape check requires `flat_bin_price_cents` exactly when the mode is `COST_PER_BIN`, and a request that omits it there (or supplies it under `UNIT_PRICE`) fails with `ERR_INVALID_REQUEST`. The triple of (`site_id`, `part_id`, `bin_location`) must be unique among agreements that are not `RETIRED`; duplicates are rejected with `ERR_DUPLICATE`. Creating an agreement against a `RETIRED` site, or for a part that is already `OBSOLETE`, is rejected with `ERR_AGREEMENT_OR_SITE_RETIRED`. A new agreement starts in `ACTIVE` status with `compliance_flag` `CLEAR`, `on_hand_qty` zero, and `open_order_qty` zero. Agreements are listable with `site_id`, `part_id`, and `status` filters.

A scan count that lands strictly below `min_qty` triggers replenishment, and replenishment always fills the bin back up to `max_qty` (§3.3). The agreement's posture auto-transitions between `ACTIVE` and `AT_CAPACITY` exactly as specified in §2.9 — reaching or exceeding capacity flips it to `AT_CAPACITY`, and falling back below capacity restores `ACTIVE`.

Sizing and pricing are renegotiable: a `DistributorAdmin` may update `min_qty`, `max_qty`, `pricing_mode`, `flat_bin_price_cents`, and `bin_location` through the agreement update operation. Every field except `expected_bin_agreement_version` is optional in the body; supplied fields are merged onto the current values, and the sizing bounds of the create are re-validated on the merged `min_qty`/`max_qty` (violations surface `ERR_QUANTITY_OUT_OF_BOUNDS`). The mode/flat interplay is enforced on the merged result: setting `pricing_mode` to `COST_PER_BIN` requires `flat_bin_price_cents` in the same body, setting it to `UNIT_PRICE` forbids `flat_bin_price_cents` in the same body, and supplying `flat_bin_price_cents` without `pricing_mode` is accepted only when the agreement is already `COST_PER_BIN` — violations surface `ERR_INVALID_REQUEST`, and whenever the resulting mode is `UNIT_PRICE` the agreement's `flat_bin_price_cents` is reset to 0. Updating a `RETIRED` agreement is rejected with `ERR_INVALID_STATE`, and changing `bin_location` does not re-run the live-triple uniqueness check. That update is one of the two OCC-guarded writes of §2.7 and must carry `expected_bin_agreement_version`; a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful update increments the agreement's `version` and immediately recomputes the posture against the new `max_qty`.

For periodic right-sizing reviews, an advisory sizing-recommendation capability — available to `DistributorAdmin` and `RouteDriver` — proposes a new reorder point and capacity from consumption history. It examines the agreement's four most recent `SUBMITTED` route stops (selected by `created_at` descending, then processed oldest-first so ties resolve by `created_at` ascending). Each stop's weekly usage is the previously recorded on-hand quantity — concretely, the `counted_qty` of the agreement's most recent prior `SUBMITTED` stop, or zero when the stop is the agreement's first submitted count — minus that stop's `counted_qty`, with negative differences — which arise when a delivery landed between scans — clamped to zero. A `method` query parameter selects the variant; an unrecognized `method` value is rejected with `ERR_INVALID_REQUEST`, and the recommendation is computable for an agreement in any status, including `RETIRED`. Under the default `TRAILING` method, the usage figures are averaged plainly over the four weeks — the usage sum is divided by four even when the window holds fewer than four stops — the average is multiplied by a safety factor of one and a half, and the result is rounded up to a whole number of pieces to produce `recommended_min`; `recommended_max` is three times `recommended_min`. Under the `PROJECTED` method, weeks whose stop generated a replenishment order are weighted double — consumption during a stockout-risk week is a stronger signal — so the projected average is the sum of each week's weight times its usage divided by the sum of the weights of the stops actually in the window; the same safety factor of one and a half is applied and then rounded up, and `recommended_max` is again three times the minimum. When the agreement has no `SUBMITTED` stops at all, both methods yield a `recommended_min` of zero and hence a `recommended_max` of zero. The two variants produce different proposals whenever the four-stop window contains an order-generating stop and the weekly usages are not all equal, and in that case `PROJECTED` yields a `recommended_min` at least as high as `TRAILING`. The response carries `recommended_min`, `recommended_max`, and the `method` that produced them.

When a part reaches end of life, the agreement survives through substitution or retires with it; both paths are covered in §3.7.

### 3.3. Scan Routes and Driver Counts

Replenishment demand is discovered physically: a route driver walks the site and records what is actually in each bin. A `DistributorAdmin` schedules a replenishment route by supplying the `site_id` it visits, the `route_date` on which it runs (validated only as an ISO 8601 datetime string and stored exactly as supplied — no midnight-UTC alignment is enforced), and a dock-receiving window bounded by `window_start` and `window_end`. Scheduling is the second OCC-guarded write of §2.7: the request must carry `expected_site_version`, and a mismatch with the site's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Receiving windows are half-open — a route's window includes its start instant and excludes its end instant — so a route ending at a given moment does not overlap another route starting at that same moment, and back-to-back scheduling is allowed. A new route whose window overlaps an existing `SCHEDULED` or `IN_PROGRESS` route on the same site is rejected with `ERR_ROUTE_WINDOW_OVERLAP`, as is a window whose start is not strictly before its end. Scheduling against a `RETIRED` site is rejected with `ERR_AGREEMENT_OR_SITE_RETIRED`. A successful scheduling creates the route in `SCHEDULED` status and increments the site's `version` — which is precisely why the OCC guard exists. Routes are listable with `site_id` and `status` filters.

When the day comes, a `RouteDriver` starts the route, transitioning it from `SCHEDULED` to `IN_PROGRESS`. Starting requires that the logical clock has reached the route's `window_start` and that the site is still `ACTIVE`; a start attempted before the window has opened or against a site no longer `ACTIVE` is rejected with `ERR_INVALID_STATE`, and the transition increments the route's `version`. A scheduled route that will not run can instead be cancelled — `SCHEDULED` to `CANCELLED` — which deletes every one of its `PENDING` stops outright, since pending stops carry no side effects, and increments the route's `version`.

The driver registers a route stop with a payload containing the `bin_agreement_id`; registration is accepted while the route is `SCHEDULED` or `IN_PROGRESS` — any other route state surfaces `ERR_INVALID_STATE` — the agreement is not checked against the route's site, and the same bin may be registered on a route more than once. The new stop records its `route_id`, starts in `PENDING` status with `counted_qty` null until submission, and its `generated_order_id` is null. `RETIRED` bins accept no new stops: attempts are rejected with `ERR_AGREEMENT_OR_SITE_RETIRED`. Later, at the bin, the driver submits the physical count, transitioning the stop from `PENDING` to `SUBMITTED` with a `counted_qty` that must be zero or positive and no greater than the agreement's `max_qty` — a count above capacity is rejected with `ERR_QUANTITY_OUT_OF_BOUNDS`. Submission requires the route to be `IN_PROGRESS` and the agreement to be in `ACTIVE` or `AT_CAPACITY`; a `RETIRED` site or agreement surfaces `ERR_AGREEMENT_OR_SITE_RETIRED`. Submission writes the counted figure into the agreement's `on_hand_qty`. When the count lands strictly below the agreement's `min_qty`, the system creates a replenishment order in `DRAFT` status for that agreement with `ordered_qty` equal to `max_qty` minus the counted quantity, priced immediately per §3.4, and records the new order's id in the stop's `generated_order_id`; when the count is at or above `min_qty`, no order is created and `generated_order_id` stays null. Either way, the agreement's posture is then recomputed per §2.9 — a low scan followed by a fresh order may push the agreement from `ACTIVE` to `AT_CAPACITY` — and both the stop's `version` and the agreement's `version` increment by one.

Closing the route — `IN_PROGRESS` to `CLOSED` — is allowed only when the route has produced work and no loose ends remain: at least one of its stops must be `SUBMITTED`, and no stop may remain `PENDING`. Closing an empty route or one with unsubmitted stops is rejected with `ERR_ROUTE_EMPTY` (HTTP 422). A successful close increments the route's `version`. Stops support reverse reachability: they are listable per route, and the stop listing also accepts `route_id`, `bin_agreement_id`, `generated_order_id`, and `status` filters, so operators can trace which stop produced a given order and which stops a given agreement has seen.

### 3.4. The Replenishment Order Lifecycle

A replenishment order is born `DRAFT` inside a scan submission, never through a standalone create. It records the `bin_agreement_id` it replenishes, the `site_id` denormalized from the agreement for balance rollups, and the `part_id` actually ordered — which is the agreement's currently pointed-at part, reflecting any substitution repoint of §3.7. Its `ordered_qty` is the fill-to-max quantity fixed at trigger time. Both `unit_price_cents` and `total_price_cents` are computed once at creation and never recomputed; the order's `delivery_mode` is null until it is pinned from the site's `delivery_mode` at confirmation, so a later change to the site's default does not rewrite history.

Pricing follows the agreement's `pricing_mode`, and the evaluation order is pinned: tier selection first, then quantity multiplication, then the certification fee. Under `UNIT_PRICE` pricing, the base is the part's catalogue `unit_price_cents`, and a volume discount applies to it: when `ordered_qty` is at least 500 pieces, the applied unit price is the base times 95 divided by 100 — a five percent discount — computed with truncating integer division that discards any fractional cent; when `ordered_qty` is at least 100 but below 500, the applied unit price is the base times 98 divided by 100, a two percent discount under the same truncating division; below 100 pieces the catalogue price applies undiscounted. The order's `total_price_cents` is that unit price multiplied by `ordered_qty`, and its `unit_price_cents` records the discounted unit. Under `COST_PER_BIN` pricing, the order's `unit_price_cents` is zero and `total_price_cents` is simply the agreement's `flat_bin_price_cents` — a flat per-trip fee regardless of quantity. In both modes, when the part `is_critical`, a flat certification handling fee of 1,500 cents is added to `total_price_cents`. The two modes price identically-inputted orders — same count, same part — differently whenever the flat fee differs from the discounted unit total, which is the normal case.

Confirmation by a `DistributorAdmin` moves the order from `DRAFT` to `CONFIRMED` through a gauntlet of gates. The agreement must be in `ACTIVE` or `AT_CAPACITY` — confirmation against a `RETIRED` agreement is rejected with `ERR_AGREEMENT_OR_SITE_RETIRED`. The certification gate of §3.5 applies: the agreement's `compliance_flag` must be `CLEAR`, and when the part is critical at least one `VALID` lot certificate must exist for it, otherwise the confirmation is rejected with `ERR_CERTIFICATION_BLOCKED`. Finally the credit gate: the site's `outstanding_balance_cents` plus the order's `total_price_cents` must not exceed the site's `credit_limit_cents`, or the confirmation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. A successful confirmation pins `delivery_mode` from the site, adds `ordered_qty` to the agreement's `open_order_qty`, adds `total_price_cents` to the site's `outstanding_balance_cents`, recomputes the agreement posture (which may flip it to `AT_CAPACITY`), and increments the `version` of the order, the agreement, and the site by one each.

Shipping by a `DistributorAdmin` moves a `CONFIRMED` order to `IN_TRANSIT` with nothing more than the order's version increment. Delivery by the `RouteDriver` moves `IN_TRANSIT` to `DELIVERED` and is the moment stock lands: the agreement's `on_hand_qty` increases by `ordered_qty`, its `open_order_qty` decreases by `ordered_qty`, and the site's `outstanding_balance_cents` decreases by `total_price_cents` — delivery settles the balance, since invoicing is out of scope. The posture recompute that follows may restore `AT_CAPACITY` to `ACTIVE`, or leave the agreement at capacity when the on-hand figure alone already reaches `max_qty`. Order, agreement, and site versions each increment.

Delivery is not always the end of the story. If the receiving count looks wrong, the `RouteDriver` may dispute the order — but only while it is the most recently delivered order for its agreement, concretely the latest-created order among the agreement's orders currently in `DELIVERED` status; disputing any other order is rejected with `ERR_INVALID_STATE`. Disputing moves `DELIVERED` to `DISPUTED` and pulls the delivered quantity back out of `on_hand_qty`, treating the stock backing the bin as unverified pending resolution; the posture is recomputed, and both the order's and the agreement's versions increment. A `DistributorAdmin` who upholds the delivery resolves the dispute, moving `DISPUTED` back to `DELIVERED` and restoring the quantity into `on_hand_qty`, with the posture recomputed and both versions incrementing again.

Cancellation compensates differently depending on the source state, and all three branches are available to a `DistributorAdmin`. Cancelling from `DRAFT` simply marks the order `CANCELLED` and increments only the order's `version` — a draft never reserved anything, so there is nothing to unwind. Cancelling from `ON_HOLD` marks the order `CANCELLED`, subtracts `ordered_qty` from the agreement's `open_order_qty`, subtracts `total_price_cents` from the site's `outstanding_balance_cents`, recomputes the posture (which may reopen an `AT_CAPACITY` agreement to `ACTIVE`), and increments the `version` of the order, the agreement, and the site. Cancelling from `DISPUTED` marks the order `CANCELLED` with no further bin or balance adjustment at all — the stock was already pulled back when the dispute was raised, and the balance was already settled at delivery — so only the order's `version` increments.

Throughout this lifecycle the site's balance figure obeys the rollup of §2.9: an exact integer-cent sum over the site's `CONFIRMED` and `IN_TRANSIT` orders, recomputed from source rows whenever a transition contributes, never adjusted incrementally without a full recompute check. Orders are listable with `bin_agreement_id`, `site_id`, `part_id`, and `status` filters.

### 3.5. Lot Certification and Critical-Part Compliance

Fasteners marked `is_critical` — structural bolts, safety-rated fasteners — carry a traceability obligation: every delivery must be backed by lot documentation. A `DistributorAdmin` registers a lot certificate for a part by supplying the `part_id`, the manufacturer `lot_number`, and the `cert_expires_at` instant at which the certification lapses. The (`part_id`, `lot_number`) pair must be unique per part. A certificate starts `VALID` and remains so until the logical clock catches up with its expiry. Certificates are listable with `part_id` and `status` filters.

Expiry is applied by a `DistributorAdmin`-invoked system sweep evaluated against the logical clock: every certificate in `VALID` status whose `cert_expires_at` the logical clock has reached or passed transitions to `EXPIRED`, and the sweep reports the affected ids as `expired_cert_ids`, in certificate creation order. The cascade behind each expiry is two levels deep when the part is critical. First, every agreement for that part in `ACTIVE` or `AT_CAPACITY` status has its `compliance_flag` set to `BLOCKED`, freezing new confirmations — confirmation against a `BLOCKED` agreement is rejected with `ERR_CERTIFICATION_BLOCKED`. Second, every order for that part sitting in `CONFIRMED` status drops to `ON_HOLD`: certificate expiry triggers the compliance block, and the compliance block holds the orders. Each expiry increments the certificate's `version` and the `version` of every affected agreement by one. Once set to `BLOCKED`, an agreement's `compliance_flag` is never cleared by any subsequent operation.

The certification gate therefore guards two moments with the same rejection, `ERR_CERTIFICATION_BLOCKED` (HTTP 422): order confirmation, and the release of a held order. Releasing a hold — `ON_HOLD` back to `CONFIRMED`, performed by a `DistributorAdmin` — requires only that at least one `VALID` lot certificate exist for the order's part again; unlike at confirmation, the agreement's `compliance_flag` is not consulted at release, so a held order can be released while its agreement remains `BLOCKED`. A successful release increments only the order's `version`.

### 3.6. Kitting and Bagging at the Packaging Station

Beyond loose-bin replenishment, the distributor bags mixed fasteners into assembly-ready kits. A `WarehouseOperator` creates a kit job with the `site_id` ordering the kit, a human-readable `kit_name`, an ordered `component_part_ids` list of the parts to bag, a `qty_per_part` specifying how many units of each component go into one kit (at least 1), a `kit_count` of identical kits to produce (at least 1), and a reserved packaging-station window bounded by `station_window_start` and `station_window_end`. Creation does not consult the site's status — a job may be created for a `RETIRED` site. The component list must hold between 1 and 20 elements with no duplicates, and every element must reference an `ACTIVE` part; violations are rejected with `ERR_QUANTITY_OUT_OF_BOUNDS`. Station reservations use closed-interval-with-buffer semantics, deliberately stricter than the half-open route windows: the packaging station is a single shared resource, so the new job's window is checked against every existing non-terminal job — one in `DRAFT`, `PICKING`, `ON_HOLD`, or `PACKED` — across all sites, and a conflict exists exactly when the new `station_window_start` falls before the existing job's `station_window_end` plus fifteen minutes and the existing job's `station_window_start` falls at or before the new `station_window_end` (a window lying entirely after the new one therefore never conflicts); the start must also be strictly before the end. Violations are rejected with `ERR_STATION_WINDOW_CONFLICT`. A new job starts in `DRAFT` with `packaging_cost_cents` null until packing computes it. Kit jobs are listable with `site_id` and `status` filters.

Starting picking moves the job from `DRAFT` to `PICKING` and is where stock is committed. Every component part must still be `ACTIVE` — otherwise `ERR_QUANTITY_OUT_OF_BOUNDS` — and each component's `available_qty` must cover `qty_per_part` multiplied by `kit_count`; a shortfall on any component is rejected with `ERR_INSUFFICIENT_STOCK`. On success, each component's `reserved_qty` increases by that product and its `available_qty` decreases by the same amount, preserving the conservation invariant of §2.9, and the `version` of the job and of every component part increments by one.

A picking job can be paused: holding moves `PICKING` to `ON_HOLD` and retains all reservations while held, incrementing the job's `version`. Resuming returns `ON_HOLD` to `PICKING`, but re-verifies that every component part is still `ACTIVE`, rejecting with `ERR_QUANTITY_OUT_OF_BOUNDS` if obsolescence intervened.

Packing moves `PICKING` to `PACKED` and computes the job's `packaging_cost_cents`. The charge is built per component line, in the order the components are listed: each line is the ceiling — rounding up to a whole cent — of 250 cents per bag, plus `qty_per_part` times 3 cents per unit, plus four percent of that component part's current `unit_price_cents`. The per-line figures are rounded first and then summed, and the sum is multiplied by `kit_count` to yield the final `packaging_cost_cents`. The rounding order is canonical: rounding each line and then summing is the specification, while summing raw line costs and rounding once is a different reading that yields different cents and is not correct. Packing increments the job's `version`.

Completion moves `PACKED` to `COMPLETED`: the reserved stock physically leaves the building, so for every component part both `reserved_qty` and `total_stock_qty` decrease by `qty_per_part` times `kit_count`, while `available_qty` is unchanged because reservation and stock drop together. The `version` of the job and of every component part increments.

Scrapping compensates by source state, with all three branches available to a `WarehouseOperator`. Scrapping from `DRAFT` simply marks the job `SCRAPPED` and increments its `version` — no reservations exist to release. Scrapping from `PICKING` performs the compensating release: every component's `reserved_qty` decreases by `qty_per_part` times `kit_count` and its `available_qty` increases by the same amount, restoring the conservation invariant, and the `version` of the job and of each component part increments. Scrapping from `ON_HOLD` performs exactly the same compensating release as scrapping from `PICKING`, with the same version increments.

### 3.7. Obsolescence, Substitution, and Programme Wind-Down

Catalogue entries eventually reach end of life. A `DistributorAdmin` marks a part obsolete, moving it from `ACTIVE` to `OBSOLETE` — a transition the system refuses, surfacing `ERR_INVALID_STATE`, while any replenishment order for the part remains `CONFIRMED` or `IN_TRANSIT`, or while any kit job listing the part is in `PICKING` or `ON_HOLD`. Obsolescence cascades in three directions. Every bin agreement for the part in `ACTIVE` or `AT_CAPACITY` status transitions to `RETIRED` — unless at least one active cross-reference leads from this part to some other part that is still `ACTIVE`, in which case the agreement stays live so the operator can repoint it. Every cross-reference naming this part as its `to_part_id` is deactivated, its `is_active` set to false, because an obsolete part can no longer serve as anyone's substitute; cross-references leading from this part, by contrast, remain active precisely to drive that substitution. The part's `version` increments by one.

Repointing is the companion operation: a `DistributorAdmin` invokes substitution on an agreement — the normal use being that the original part has gone `OBSOLETE` — and the system rewrites the agreement's `part_id` to the best eligible substitute. Eligible candidates resolve only through cross-reference rows leading from the agreement's current part whose `is_active` is true and whose target part is `ACTIVE`, ordered by `priority_rank` ascending with ties broken by `created_at` ascending; the first candidate in that order is selected. When no eligible substitute exists, the repoint is rejected with `ERR_NO_SUBSTITUTE` (HTTP 422). The repoint does not re-run the live-triple uniqueness check of §3.2, so it may leave two live agreements sharing a (`site_id`, `part_id`, `bin_location`) triple. A successful repoint increments the agreement's `version` by one.

Individual bins wind down as well. A `DistributorAdmin` retires a bin agreement from either `ACTIVE` or `AT_CAPACITY`; the system refuses, surfacing `ERR_INVALID_STATE`, while any order for the agreement remains in `DRAFT`, `CONFIRMED`, `ON_HOLD`, or `IN_TRANSIT`, and the transition increments the agreement's `version`. Retirement is also reachable through the obsolescence cascade above. A `RETIRED` bin accepts no new stops and no new orders, and it drops out of the live-triple uniqueness check of §3.2, freeing the (`site_id`, `part_id`, `bin_location`) combination for reuse.

Finally, an entire customer site can be retired by a `DistributorAdmin`, moving it from `ACTIVE` to `RETIRED`. The system refuses, surfacing `ERR_INVALID_STATE`, while any bin agreement at the site remains `ACTIVE` or `AT_CAPACITY`, or while any route for the site remains `SCHEDULED` or `IN_PROGRESS`; a successful retirement increments the site's `version`. Retired sites block route scheduling and stop submission per §2.8, and once any resource in this programme reaches a terminal state — `RETIRED`, `OBSOLETE`, `CLOSED`, `CANCELLED`, `DELIVERED`, `EXPIRED`, `COMPLETED`, or `SCRAPPED` — every further transition attempt against it is rejected with `ERR_INVALID_STATE`, including idempotent re-triggers of the transition that already fired.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every lifecycle action, the clock set, and the sweep — return `200 OK`. Authorized roles below are exhaustive: any role not listed for an endpoint is rejected per §2.8.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vmi/_clock/set_current_utc` | Set the logical clock (test-driving capability) | DistributorAdmin |
| POST | `/vmi/_sweep/cert-expiry` | Expire due lot certificates and fire the compliance cascade | DistributorAdmin |
| POST | `/vmi/sites` | Create a customer site | DistributorAdmin |
| GET | `/vmi/sites/{id}` | Fetch one site | DistributorAdmin, RouteDriver, WarehouseOperator |
| GET | `/vmi/sites` | List sites with pagination and optional status filter | DistributorAdmin, RouteDriver, WarehouseOperator |
| POST | `/vmi/sites/{id}/retire` | Retire a site once it has no live agreements or routes | DistributorAdmin |
| POST | `/vmi/parts` | Create a part | DistributorAdmin |
| GET | `/vmi/parts/{id}` | Fetch one part | DistributorAdmin, RouteDriver, WarehouseOperator |
| GET | `/vmi/parts` | List parts with pagination and optional status filter | DistributorAdmin, RouteDriver, WarehouseOperator |
| POST | `/vmi/parts/{id}/obsolete` | Mark a part obsolete; cascades bin retirement and cross-reference deactivation | DistributorAdmin |
| POST | `/vmi/part-cross-references` | Declare that one part may substitute for another | DistributorAdmin |
| GET | `/vmi/part-cross-references/{id}` | Fetch one cross-reference | DistributorAdmin, RouteDriver, WarehouseOperator |
| GET | `/vmi/part-cross-references` | List cross-references; filterable by either endpoint part | DistributorAdmin, RouteDriver, WarehouseOperator |
| POST | `/vmi/bin-agreements` | Create a VMI bin agreement for a (site, part, location) triple | DistributorAdmin |
| GET | `/vmi/bin-agreements/{id}` | Fetch one bin agreement | DistributorAdmin, RouteDriver, WarehouseOperator |
| GET | `/vmi/bin-agreements` | List bin agreements with filters | DistributorAdmin, RouteDriver, WarehouseOperator |
| PUT | `/vmi/bin-agreements/{id}` | Update sizing/pricing fields; OCC-guarded on the agreement version | DistributorAdmin |
| POST | `/vmi/bin-agreements/{id}/retire` | Retire a bin agreement with no open orders | DistributorAdmin |
| POST | `/vmi/bin-agreements/{id}/substitute` | Repoint the agreement's part to the best eligible substitute | DistributorAdmin |
| GET | `/vmi/bin-agreements/{id}/sizing-recommendation` | Advisory min/max proposal from consumption history | DistributorAdmin, RouteDriver |
| POST | `/vmi/routes` | Schedule a scan route for a site; OCC-guarded on the site version | DistributorAdmin |
| GET | `/vmi/routes/{id}` | Fetch one route | DistributorAdmin, RouteDriver |
| GET | `/vmi/routes` | List routes with filters | DistributorAdmin, RouteDriver |
| POST | `/vmi/routes/{id}/start` | Start a scheduled route once its window opens | RouteDriver |
| POST | `/vmi/routes/{id}/cancel` | Cancel a scheduled route; pending stops are deleted | RouteDriver |
| POST | `/vmi/routes/{id}/close` | Close an in-progress route; requires at least one submitted stop and no pending stops | RouteDriver |
| GET | `/vmi/routes/{id}/stops` | List stops for a route | DistributorAdmin, RouteDriver |
| POST | `/vmi/routes/{id}/stops` | Register a scan stop for a bin on a route | RouteDriver |
| GET | `/vmi/route-stops/{id}` | Fetch one route stop | DistributorAdmin, RouteDriver |
| GET | `/vmi/route-stops` | List route stops with filters (reverse-reachable by bin agreement and by generated order) | DistributorAdmin, RouteDriver |
| POST | `/vmi/route-stops/{id}/submit` | Submit the physical count; triggers order creation below the reorder point | RouteDriver |
| GET | `/vmi/replenishment-orders/{id}` | Fetch one replenishment order | DistributorAdmin, RouteDriver |
| GET | `/vmi/replenishment-orders` | List replenishment orders with filters | DistributorAdmin, RouteDriver |
| POST | `/vmi/replenishment-orders/{id}/confirm` | Confirm a draft order; applies certification and credit gates | DistributorAdmin |
| POST | `/vmi/replenishment-orders/{id}/ship` | Ship a confirmed order | DistributorAdmin |
| POST | `/vmi/replenishment-orders/{id}/deliver` | Deliver an in-transit order; stock lands in the bin and balance settles | RouteDriver |
| POST | `/vmi/replenishment-orders/{id}/dispute` | Dispute the delivered count; pulls the delivered quantity back out of the bin | RouteDriver |
| POST | `/vmi/replenishment-orders/{id}/resolve-dispute` | Resolve a dispute in the distributor's favour; restores the delivered quantity | DistributorAdmin |
| POST | `/vmi/replenishment-orders/{id}/release-hold` | Release a certification hold once a valid lot certificate exists | DistributorAdmin |
| POST | `/vmi/replenishment-orders/{id}/cancel` | Cancel an order from DRAFT, ON_HOLD, or DISPUTED with state-dependent compensation | DistributorAdmin |
| POST | `/vmi/lot-certificates` | Register a lot certificate for a critical part | DistributorAdmin |
| GET | `/vmi/lot-certificates/{id}` | Fetch one lot certificate | DistributorAdmin, RouteDriver, WarehouseOperator |
| GET | `/vmi/lot-certificates` | List lot certificates with filters | DistributorAdmin, RouteDriver, WarehouseOperator |
| POST | `/vmi/kit-jobs` | Create a kitting/bagging job; station window uses closed-interval-with-buffer semantics | WarehouseOperator |
| GET | `/vmi/kit-jobs/{id}` | Fetch one kit job | DistributorAdmin, WarehouseOperator |
| GET | `/vmi/kit-jobs` | List kit jobs with filters | DistributorAdmin, WarehouseOperator |
| POST | `/vmi/kit-jobs/{id}/start-picking` | Begin picking; reserves component stock | WarehouseOperator |
| POST | `/vmi/kit-jobs/{id}/hold` | Pause a picking job, retaining reservations | WarehouseOperator |
| POST | `/vmi/kit-jobs/{id}/resume` | Resume a held job | WarehouseOperator |
| POST | `/vmi/kit-jobs/{id}/pack` | Pack a picked job; computes packaging cost | WarehouseOperator |
| POST | `/vmi/kit-jobs/{id}/complete` | Complete a packed job; reserved stock leaves inventory | WarehouseOperator |
| POST | `/vmi/kit-jobs/{id}/scrap` | Scrap a job from DRAFT, PICKING, or ON_HOLD with state-dependent compensation | WarehouseOperator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_OR_SITE_RETIRED` | 409 Conflict |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_NO_SUBSTITUTE` | 422 Unprocessable Entity |
| `ERR_ROUTE_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_STATION_WINDOW_CONFLICT` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_BLOCKED` | 422 Unprocessable Entity |
| `ERR_QUANTITY_OUT_OF_BOUNDS` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_STOCK` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ROUTE_EMPTY` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
