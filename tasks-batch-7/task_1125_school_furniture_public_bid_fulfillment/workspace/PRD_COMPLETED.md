# School Furniture Public Bid Fulfillment API — Product Requirements Document

## 1. Introduction

Public school districts buy classroom furniture under competitive-bid rules that leave no room for improvisation: the specification names an exact manufacturer and model, the winning contractor may not substitute, and every dollar committed is auditable against a district's fiscal-year cap. The School Furniture Public Bid Fulfillment API is the contractor-side system of record for that entire engagement — from the moment a district drafts a bid specification, through award issuance and purchase-order intake, into the compressed summer delivery window when crews uncrate, remove debris, and place furniture in classrooms, and onward for years of warranty and parts support.

The platform exists to make the hard parts of this business mechanically enforceable. Cooperative contract pricing with tier schedules must be applied consistently across a district's cumulative annual volume. Delivery and installation must respect school-site capacity and crew availability inside a fixed summer window. Damage discovered at the loading dock or in the classroom must trigger replacement shipments inside a bounded replacement deadline. Back-orders must be communicated to the district with honest, forward-moving ETAs. And because multiple actors on both the district side and the contractor side touch the same awards and lines, optimistic concurrency guards prevent stale views from overwriting legitimate amendments. This document specifies the API contract, the system-wide principles, and the business workflows an implementation must honor.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Six roles are recognized, with exact spellings: `ContractorAdmin`, `ContractManager`, `FulfillmentCoordinator`, `CrewLead`, `DistrictBuyer`, and `ServiceAgent`. Each endpoint admits a defined set of roles; a well-formed request whose role is not on that endpoint's list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Role identity resolves differently depending on the role. When `X-User-Role` is `DistrictBuyer`, `X-User-ID` is the `id` of the acting `District`; ownership checks on any resource whose district chain resolves to a district — a school site, a bid specification, an award, a purchase order, a PO line, a warranty claim or appeal — compare that resource's district foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_SCOPE_VIOLATION` (HTTP 403). When `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the acting `Crew`; a crew lead may start or complete only install tasks assigned to their own crew, and may file install-phase damage reports only for their own crew's tasks, with violations again rejected as `ERR_SCOPE_VIOLATION`. These ownership checks guard state-changing operations; plain retrieval (GET by id) and list endpoints perform no ownership comparison and are open to every declared role. The remaining four roles — `ContractorAdmin`, `ContractManager`, `FulfillmentCoordinator`, and `ServiceAgent` — are opaque: `X-User-ID` is an operator identifier not tied to any persisted entity. The server never compares it to any entity's `id`; these roles are constrained purely by the per-endpoint role lists.

In brief division of labor: a `ContractorAdmin` administers the platform itself (registering districts and crews, driving the logical clock); a `ContractManager` owns commercial terms (cooperative pricing agreements, award acceptance, damage-replacement decisions); a `FulfillmentCoordinator` runs the warehouse desk (PO acceptance and closeout, shipments, installation scheduling, back-order communication); a `CrewLead` executes physical installation; a `DistrictBuyer` is the district's purchasing official (specs, sites, awards, purchase orders, warranty claims); and a `ServiceAgent` adjudicates warranty claims and orders parts.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A non-integer value, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `total_count` is computed after filtering, and `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in this API — districts, school sites, bid specifications, spec lines, cooperative price agreements, awards, purchase orders, PO lines, shipments, crews, install tasks, damage reports, backorder notices, and warranty claims — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer, 1 at creation, that increments by one on every mutation of the resource, including mutations performed as side effects of operations on related resources.

Two of these fields are load-bearing beyond audit: `version` drives the optimistic concurrency checks of §2.7, and `created_at` fixes the chronological order used by cooperative-volume pricing (§3.4). Date-typed business fields (such as `scheduled_date` or `start_date`) are ISO calendar dates, while `installed_at` and `communicated_at` are full timestamps taken from the logical clock.

### 2.5. The Logical Clock

All date-sensitive validation and calculation in the system reads a single logical clock, never wall-clock time. The clock's startup default — before any call adjusts it — is exactly `2026-05-01T00:00:00Z`. An admin-only, test-driving capability advances the logical clock to a supplied `to` instant expressed as `to_iso8601` — a full ISO 8601 timestamp, or a bare ISO calendar date interpreted as midnight UTC — and returns the resulting `current_utc`; the server never silently falls back to real time. Filing dates such as a damage report's `reported_date` and a warranty claim's `filed_date` are stamped from this clock's calendar date, while `installed_at` on a PO line and `communicated_at` on a backorder notice are stamped from its full timestamp, serialized as an ISO 8601 UTC timestamp with three fractional digits (so the default clock stamps `2026-05-01T00:00:00.000Z`). ETA forwardness checks, warranty-term windows, order-by gates, and replacement deadlines all evaluate against this clock.

### 2.6. Monetary Precision and Rounding Conventions

All money in the system is integer cents. Cooperative tier pricing produces exact integer-cent line totals with no rounding at the summation step; only the derived per-unit price is rounded, half-up, to whole cents. Warranty coverage amounts are likewise integer cents, rounded half-up. Installation closeout is computed at whole-dollar granularity — one hundred cents — with round-half-up applied at each pinned step of the calculation rather than once at the end, so rounding order materially affects the result and must not be reordered. Calendar arithmetic elsewhere is in whole days; a year of warranty proration is 365 days.

### 2.7. Optimistic Concurrency Control

Two write operations require an explicit expected-version field, and both reject stale views with the same error.

An award amendment request must carry `expected_award_version` holding the value of the target award's `version` the client last observed. If the award's current `version` has advanced since then — because another amendment was legitimately applied in the meantime — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no re-pinning occurs.

A revised backorder notice created against a PO line must carry `expected_po_line_version` holding the value of that line's `version` the client last observed. A successful create legitimately supersedes the line's current open notice, so if the line's `version` no longer matches, the client would be superseding a notice it never saw; the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts an expected-version field; requests to any other operation are processed without an OCC check. The OCC comparison is evaluated after all business validations for the request have passed (see §2.8).

### 2.8. Request Evaluation Order

Every request is evaluated against a fixed validation pipeline; earlier stages mask later ones, so the error a client receives is always from the earliest failing stage. The order is:

1. **User context** — presence and validity of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the caller's role appears in the endpoint's role list (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Ownership scope** — entity-backed callers (`DistrictBuyer`, `CrewLead`) act only within their own district or crew (`ERR_SCOPE_VIOLATION`).
4. **Existence** — path identifiers are resolved left to right, and a missing id is rejected with `ERR_NOT_FOUND` (HTTP 404) before any later id is examined; once path ids resolve, body foreign-key references (`district_id`, `bid_spec_id`, `award_id`, `coop_agreement_id`, `purchase_order_id`, `spec_line_id`, `school_site_id`, `crew_id`, `shipment_id`, `install_task_id`, `po_line_id`) must exist as well, on the same error.
5. **Request shape** — required fields present, types valid, enum membership honored, quantities, counts, capacities and costs at least 1 where applicable, `end_date` strictly later than `start_date`, well-formed ISO dates, and conditional requirements met (a cooperative agreement reference when pricing is tiered, a flat price when pricing is flat, the discovery-context reference on damage reports); computed or system-managed fields supplied in a body are ignored. Violations are `ERR_INVALID_REQUEST` (HTTP 400).
6. **State guards** — the target resource's current status permits the requested transition (`ERR_INVALID_STATE`, HTTP 409), including terminal lockdown: resources in `CANCELLED`, `CLOSED`, or `RESOLVED` accept no further actions.
7. **Cross-entity state gates** — award creation requires a `CLOSED` specification (`ERR_BID_SPEC_NOT_CLOSED`); purchase-order creation requires an `ACCEPTED` award (`ERR_AWARD_NOT_ACTIVE`); install-task start requires a `DELIVERED` shipment (`ERR_INVALID_STATE`); warranty filing requires a `VERIFIED` line (`ERR_LINE_NOT_VERIFIED`).
8. **Temporal windows** — order-by, delivery-window, replacement-deadline, warranty-term, and ETA-forwardness checks (`ERR_ORDER_WINDOW_CLOSED`, `ERR_OUTSIDE_DELIVERY_WINDOW`, `ERR_REPLACEMENT_WINDOW_MISSED`, `ERR_WARRANTY_EXPIRED`, `ERR_ETA_NOT_FORWARD`).
9. **Specification version pin** — the spec pin check of §2.9 (`ERR_SPEC_VERSION_STALE`).
10. **No-substitution compliance** — the delivered-goods check of §2.9 (`ERR_SUBSTITUTION_NOT_ALLOWED`).
11. **Crew double-booking** (`ERR_CREW_DOUBLE_BOOKED`).
12. **Site daily capacity** (`ERR_SITE_CAPACITY_EXCEEDED`).
13. **Spec-line drawdown** (`ERR_AWARD_QTY_EXCEEDED`).
14. **Uniqueness and duplicate guards** — duplicate PO numbers, duplicate warranty claims, claim amounts beyond coverage, damage beyond delivered quantity, delivery beyond remaining quantity (`ERR_DUPLICATE_PO_NUMBER`, `ERR_DUPLICATE_CLAIM`, `ERR_CLAIM_EXCEEDS_COVERAGE`, `ERR_DAMAGE_EXCEEDS_DELIVERED`, `ERR_DELIVERY_EXCEEDS_ORDERED`).
15. **District fiscal cap** (`ERR_DISTRICT_FISCAL_CAP_EXCEEDED`).
16. **Backorder posture gate** (`ERR_PO_AT_RISK_BLOCKS_SCHEDULING`).
17. **Optimistic concurrency** — the expected-version comparisons of §2.7 (`ERR_STALE_VERSION`), deliberately last so that a stale write is reported only after every business rule has passed.

### 2.9. Procurement Integrity: No Substitution and the Specification Pin

Two principles give this domain its compliance spine. First, the **no-substitution rule**: a spec line pins an exact `manufacturer` and `model`, and delivered goods must match them exactly — a delivery entry naming a different manufacturer or model is rejected outright with `ERR_SUBSTITUTION_NOT_ALLOWED`. Second, **specification version pinning**: a bid specification carries a monotonically increasing `spec_version` that starts at 1 and increments each time the specification is re-published after an addendum. When an award is created it pins the then-current `spec_version` into `awarded_spec_version`, and every PO line created against that award is validated against the pin — if the specification's `spec_version` no longer equals the award's `awarded_spec_version` (because an addendum was issued and re-published without a corresponding award amendment), line creation is rejected with `ERR_SPEC_VERSION_STALE`. An award amendment re-establishes the pin, as described in §3.3. Together these rules ensure the district always receives exactly what was bid, priced against exactly the terms that were awarded.

### 2.10. Conserved Quantities and Derived Counters

Several quantities in the system are derived rather than stored as free-standing facts, and implementations must keep them conserved through every forward and compensating action. A spec line's `remaining_qty` is always its `qty` minus the summed ordered quantities of non-cancelled PO lines referencing it; ordering debits it and cancelling credits it back, leaving the invariant sum unchanged. A crew's `booked_days` is always the sum of `crew_days` over that crew's tasks currently `SCHEDULED` or `IN_PROGRESS`; assignment debits it, and unassignment or completion credits exactly the same amount back, so the ledger never drifts. A purchase order's `open_backorder_count` is the count of its lines currently in `BACKORDERED` status, and its `posture` — `ON_TRACK` or `AT_RISK` — is recomputed from that count on every change, independently of the order's fulfillment status. Finally, parent records bubble up from their children: a shipment completes when all of its install tasks complete, and a purchase order fulfills when all of its non-cancelled lines are verified. Bubbling requires at least one qualifying child: a shipment whose tasks are all cancelled never completes, and an order with no non-cancelled lines never fulfills. Each such derived mutation updates the owning resource's `updated_at` and increments its `version`.

## 3. Business Logic & Workflows

### 3.1. Foundational Records: Districts, Sites, Cooperative Agreements, and Crews

Before any procurement begins, a `ContractorAdmin` registers each participating **District** with its display `name`, its `annual_cap_cents` — the fiscal-year commitment ceiling across all of the district's accepted purchase orders, expressed in cents — and an `extended_warranty_enrolled` flag, defaulting to false, that selects the extended prorated warranty coverage variant described in §3.9. The same administrator registers installation **crews**, each created with a `name` and a `booked_days` ledger that starts at zero.

A `DistrictBuyer` then registers the district's delivery destinations as **school sites**. Each site carries the owning `district_id`, a `name`, an optional street `address`, and a `daily_crew_capacity` — the maximum total `crew_count` allowed to occupy the site on any single date, which must be at least 1. Sites can be listed with an optional `district_id` filter alongside the standard `limit` and `offset` parameters.

Cooperative purchasing is represented by a **CoopPriceAgreement**, created by a `ContractManager` with a `name`, a `contract_year`, and a `tier_table`. The tier table is an array of rows, each pairing a `min_qty` breakpoint with a `unit_price_cents`, sorted by `min_qty` ascending; a row applies to a cumulative unit position that has reached or passed its `min_qty`. The table must contain at least one row, and each row's `min_qty` and `unit_price_cents` are integers of at least 1; rows are stored as supplied, and because pricing always selects the greatest reached `min_qty` (§3.4), submission order does not affect results. An agreement is `ACTIVE` upon creation and stays referenceable for pricing as described in §3.4.

### 3.2. Authoring the Bid Specification and the Addendum Cycle

A `DistrictBuyer` authors a **bid specification** by supplying the issuing `district_id`, a `title`, the `bid_due_date` on which bids close, and the summer delivery window bounded inclusively by `delivery_window_start` and `delivery_window_end`. A new specification is born in `DRAFT` status with `spec_version` 1.

While a specification is `DRAFT` — and, notably, also while it is `ADDENDUM_ISSUED` — the buyer may add **spec lines**, each naming the exact required `manufacturer` and `model` under the no-substitution rule, a total `qty` of at least 1 that the district may order against the line, a not-to-exceed `max_unit_price_cents` ceiling, and an optional free-text `description`. The line's `remaining_qty` is initialized to its full `qty`; attempting to attach a line to a specification in any other status is rejected with `ERR_INVALID_STATE`. Spec lines can be listed with optional `bid_spec_id` filtering.

Publishing moves a specification from `DRAFT` to `PUBLISHED`, and the first publish leaves `spec_version` at 1. A specification with no lines at all cannot be published — the attempt fails with `ERR_INVALID_REQUEST`. From `PUBLISHED`, the buyer may close the specification to bidding, moving it to `CLOSED`. Awarding (§3.3) moves a `CLOSED` specification to its terminal `AWARDED` status.

The addendum cycle is deliberately cyclic. Issuing an addendum — an action carrying a free-text `addendum_note` — moves a specification from `PUBLISHED` to `ADDENDUM_ISSUED`, from `CLOSED` to `ADDENDUM_ISSUED`, or from `AWARDED` to `ADDENDUM_ISSUED` (the post-award amendment entry), and each issuance increments the specification's `version`. While `ADDENDUM_ISSUED`, lines may again be added or adjusted. Re-publishing from `ADDENDUM_ISSUED` returns the specification to `PUBLISHED` and increments `spec_version` by one — a content-version bump that invalidates existing award pins until the award is amended (§3.3). This `PUBLISHED` → `ADDENDUM_ISSUED` → `PUBLISHED` loop may repeat as many times as procurement requires. Specifications support listing filtered by `district_id` or `status`.

### 3.3. Award Issuance, Acceptance, and Post-Award Amendment

Once a specification is `CLOSED`, a `DistrictBuyer` issues an **award notice** against it. The request names the `bid_spec_id` and the awarding `district_id` — which must equal the specification's district, failing which the request is rejected with `ERR_INVALID_REQUEST` — and a specification not yet `CLOSED` yields `ERR_BID_SPEC_NOT_CLOSED`. The award fixes its commercial terms at creation: a `pricing_mode` of either `COOP_TIERED` or `AWARD_FLAT`; a `coop_agreement_id`, required when the mode is `COOP_TIERED`; a `flat_unit_price_cents`, required when the mode is `AWARD_FLAT` (a missing conditional requirement is `ERR_INVALID_REQUEST`, while a value supplied for the opposite mode is tolerated and stored as given); an `install_rate_cents` per-unit installation labor rate used at closeout; an `order_by_date` beyond which no lines may be added to purchase orders; a `warranty_years` base term measured from each line's installation; and an `extended_years` prorated term, defaulting to 0, extending coverage for enrolled districts.

Creation stamps the award `ISSUED` and pins `awarded_spec_version` to the specification's current `spec_version`; as a cascade, the specification itself transitions `CLOSED` → `AWARDED`. Awards can be listed filtered by `bid_spec_id`, `district_id`, `coop_agreement_id`, or `status`.

A `ContractManager` accepts the award notice, moving it `ISSUED` → `ACCEPTED` and incrementing the award's `version`. Awards have no terminal status — they persist for the life of warranty servicing — but only an `ACCEPTED` award supports purchase-order intake.

When a post-award addendum cycle has advanced the specification's `spec_version`, a `DistrictBuyer` brings the award back into alignment by issuing an amendment, an `ACCEPTED` → `ACCEPTED` self-loop accompanied by a free-text `amendment_note`. The amendment request must carry `expected_award_version` equal to the award's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.7. A successful amendment re-pins `awarded_spec_version` to the specification's current `spec_version` and increments the award's `version` by one, re-enabling line ordering under the new content.

### 3.4. Purchase Order Intake, Line Pricing, and the District Fiscal Cap

Against an `ACCEPTED` award — anything earlier is rejected with `ERR_AWARD_NOT_ACTIVE` — a `DistrictBuyer` submits a **purchase order**, supplying the `award_id`, the district-assigned `po_number`, and the `fiscal_year` used for cap accounting. The `po_number` must be unique among the district's non-`CANCELLED` purchase orders within the same `fiscal_year`; a collision is rejected with `ERR_DUPLICATE_PO_NUMBER`. A new purchase order is `RECEIVED`, with `posture` `ON_TRACK`, `open_backorder_count` 0, and `total_cents` 0. Orders may be listed filtered by `award_id` or `status`.

Lines are added to the order while it remains `RECEIVED` — adding to any other status is `ERR_INVALID_STATE`. Each line references a `purchase_order_id` and a `spec_line_id` and states an `ordered_qty` of at least 1; client-supplied values for computed fields such as `computed_unit_price_cents` are ignored. Line creation enforces four ordered gates after shape and state checks pass: the creation date must fall on or before the award's `order_by_date` (`ERR_ORDER_WINDOW_CLOSED`); the specification pin must hold — the spec's `spec_version` equal to the award's `awarded_spec_version` (`ERR_SPEC_VERSION_STALE`); the drawdown must fit — `ordered_qty` no greater than the spec line's `remaining_qty` (`ERR_AWARD_QTY_EXCEEDED`); and finally the priced line must not breach the spec line's `max_unit_price_cents` ceiling, which is rejected as `ERR_INVALID_REQUEST` — the ceiling breach never raises `ERR_AWARD_QTY_EXCEEDED`, which is reserved for drawdown violations.

Pricing follows the award's `pricing_mode`. Under `AWARD_FLAT`, every unit carries the pinned `flat_unit_price_cents`: `computed_unit_price_cents` equals it exactly, and `line_total_cents` is `ordered_qty` multiplied by it. Under `COOP_TIERED`, pricing is marginal across the cooperative tier schedule keyed on the district's cumulative volume. The system first establishes the district's year-to-date cooperative volume: the sum of `ordered_qty` across every non-`CANCELLED` line that references the same cooperative agreement, sits on a purchase order of the same district, and whose purchase order's `fiscal_year` equals the agreement's `contract_year`, evaluated in line-creation order (`created_at` ascending). Creation order permanently fixes each line's cumulative base; later events never reprice an existing line. The new line's units are then priced one at a time, the first unit occupying cumulative position one past that base and each subsequent unit advancing the position by one; each unit's price is the `unit_price_cents` of the tier row with the greatest `min_qty` that the unit's position has reached or passed — a position that has reached no row contributes zero cents. The line's `line_total_cents` is the exact integer-cent sum of those per-unit prices, and its `computed_unit_price_cents` is that total divided by `ordered_qty`, rounded half-up to whole cents. The two variants can therefore price identical quantities differently: whenever the flat price sits below the first tier or a tier boundary is crossed, the tiered variant yields the higher total. At creation the line inherits the award's `coop_agreement_id` (null under `AWARD_FLAT` unless the award itself carries one), starts `PENDING` with `delivered_qty` 0, debits the spec line's `remaining_qty` by `ordered_qty`, and triggers recompute of the order's `total_cents` — the sum of `line_total_cents` over the order's non-`CANCELLED` lines. Lines can be listed filtered by `purchase_order_id`, `spec_line_id`, `coop_agreement_id`, or `status`.

Acceptance of the order is performed by a `FulfillmentCoordinator` and carries the fiscal-cap check: the sum of `total_cents` across the district's orders in `ACCEPTED`, `IN_FULFILLMENT`, `FULFILLED`, or `CLOSED` status within the same `fiscal_year`, plus this order's `total_cents`, must not exceed the district's `annual_cap_cents`; breach is rejected with `ERR_DISTRICT_FISCAL_CAP_EXCEEDED`. A successful acceptance moves the order `RECEIVED` → `ACCEPTED` and cascades every line on it from `PENDING` to `ORDERED`.

A `DistrictBuyer` may cancel an order, optionally carrying a free-text `cancel_reason`, which is accepted and ignored rather than persisted. From `RECEIVED` cancellation is unconditional: the order becomes `CANCELLED` and every `PENDING` line becomes `CANCELLED`. From `ACCEPTED`, cancellation is permitted only while no shipment has ever been linked to the order — otherwise `ERR_INVALID_STATE` — and moves every `ORDERED` or `BACKORDERED` line to `CANCELLED`, crediting each line's `ordered_qty` back to its spec line's `remaining_qty` as compensating release of the drawdown, resolving any open backorder notice on a cancelled `BACKORDERED` line (`OPEN` or `ETA_UPDATED` → `RESOLVED`), recomputing `open_backorder_count`, and recomputing `posture`. Individual lines may also be cancelled on their own: a line in `PENDING`, or in `ORDERED` or `BACKORDERED` with `delivered_qty` still zero (anything delivered forbids line cancellation with `ERR_INVALID_STATE`), becomes `CANCELLED`; the same drawdown compensation and order-total recompute apply, and cancelling a `BACKORDERED` line additionally resolves its open notice and decrements the order's `open_backorder_count` with posture recomputed.

Fulfillment progress is system-driven from here: the first shipment scheduled against an `ACCEPTED` order moves it to `IN_FULFILLMENT`, and when every non-`CANCELLED` line reaches `VERIFIED` the order bubbles up to `FULFILLED`. Closing is a `FulfillmentCoordinator` action valid only on a `FULFILLED` order, and it computes `closeout_total_cents` — null until this point — in a pinned order that must not be reordered. First, for each non-`CANCELLED` line, the installation charge is `ordered_qty` multiplied by the award's `install_rate_cents`, divided by one hundred, rounded half-up to a whole number, and multiplied back by one hundred — each line's charge rounded half-up to whole dollars before any summation. Second, the per-line charges are summed into a subtotal. Third, the midpoint of the summer delivery window is computed as `delivery_window_start` plus half the number of days between `delivery_window_start` and `delivery_window_end`, that division truncated down to whole days. Fourth, if the latest `installed_at` date among the order's non-`CANCELLED` lines falls on or before that midpoint date, an early-completion credit of three percent of the subtotal — again rounded half-up to whole dollars — is granted; otherwise the credit is zero. Finally, `closeout_total_cents` is the subtotal minus the credit, and the order becomes `CLOSED`, a terminal status.

### 3.5. Summer-Window Shipments and Delivery Verification

With an order accepted, a `FulfillmentCoordinator` schedules **shipments** of its lines to school sites. A shipment is created with the `purchase_order_id`, the destination `school_site_id`, a `scheduled_date`, and a `lines` array whose entries each pair a `po_line_id` with a `qty` to ship; a `kind` of `STANDARD` or `REPLACEMENT` may be supplied and defaults to `STANDARD`. The `lines` array must contain at least one entry, and every referenced PO line must belong to the named purchase order, failing which the request is `ERR_INVALID_REQUEST`. A shipment's `damage_report_id` is null unless the shipment was created by the replacement cascade of §3.7. The scheduled date must lie within the bid specification's delivery window — on or after `delivery_window_start` and on or before `delivery_window_end` — or the request is rejected with `ERR_OUTSIDE_DELIVERY_WINDOW`. Every referenced line must currently be `ORDERED`, `PARTIALLY_DELIVERED`, or `BACKORDERED`; any other line status is `ERR_INVALID_STATE`. Scheduling is also subject to the backorder posture gate: while the order's `posture` is `AT_RISK`, shipment creation is rejected with `ERR_PO_AT_RISK_BLOCKS_SCHEDULING` unless the shipment's `kind` is `REPLACEMENT` or at least one of its lines is currently `BACKORDERED` — remediation shipments are exempt because they are how the order recovers. A shipment is born `SCHEDULED`; the first shipment created against an `ACCEPTED` order moves the order to `IN_FULFILLMENT`. Shipments may be listed filtered by `purchase_order_id`, `school_site_id`, `damage_report_id`, `kind`, or `status`.

Recording delivery is the coordinator's next act, valid only while the shipment is `SCHEDULED`. The delivery payload again carries `lines`, now with each entry reporting the `po_line_id`, the `delivered_qty` actually received, and the actual `manufacturer` and `model` of the delivered goods; the array must contain at least one entry, and every entry must reference a line scheduled on this shipment, failing which the request is `ERR_INVALID_REQUEST`. The no-substitution gate of §2.9 fires first among the business checks: any entry whose `manufacturer` or `model` differs from the pinned spec line's values is rejected with `ERR_SUBSTITUTION_NOT_ALLOWED`. Quantity discipline follows, differing by shipment `kind`: on a `STANDARD` shipment an entry's `delivered_qty` may not exceed the line's remaining undelivered quantity — its `ordered_qty` minus its already accumulated `delivered_qty` — on pain of `ERR_DELIVERY_EXCEEDS_ORDERED`; entries on a `REPLACEMENT`-kind shipment are exempt from that ordered-remainder check and are instead bounded by the quantity scheduled for that line on the shipment itself, with excess rejected as the same `ERR_DELIVERY_EXCEEDS_ORDERED`.

Accepted deliveries accumulate onto each line's `delivered_qty` and drive the line's state machine. A line that reaches partial cumulative delivery moves from `ORDERED` to `PARTIALLY_DELIVERED`; one whose cumulative delivery completes its `ordered_qty` moves `ORDERED` → `DELIVERED`, `PARTIALLY_DELIVERED` → `DELIVERED`, or — resuming out of a backorder — `BACKORDERED` → `DELIVERED`. A `BACKORDERED` line that receives only partial delivery moves to `PARTIALLY_DELIVERED`. Whenever a delivery completes a line that had an open backorder notice, the notice transitions to `RESOLVED`, the order's `open_backorder_count` is decremented, and `posture` is recomputed — dropping back to `ON_TRACK` once the count falls below two. And when the shipment is a replacement whose deliveries complete a damage report's `damaged_qty`, that report moves from `REPLACEMENT_ORDERED` to `RESOLVED` (§3.7). A shipment whose install tasks all complete moves `DELIVERED` → `COMPLETED`, its terminal state (§3.6).

### 3.6. Installation Crews, Site Occupancy, and Classroom Placement

Installation is planned as **install tasks** assigned by a `FulfillmentCoordinator`. Creating a task names the `shipment_id` whose goods are to be installed, the `crew_id` to perform the work, the `school_site_id` (which must equal the shipment's site, else `ERR_INVALID_REQUEST`), a `room_label` identifying the classroom placement, a `start_date` and `end_date` bounding the occupation, and a `crew_count` of at least 1. The occupation interval is half-open: the task occupies every date from `start_date` up to but not including `end_date`, so `end_date` must be strictly later than `start_date`. The referenced shipment must be `SCHEDULED` or `DELIVERED`; any other status is `ERR_INVALID_STATE`. The derived `crew_days` of a task is its `crew_count` multiplied by the number of dates in that half-open interval, and its `completed_checklist` starts empty.

Two booking constraints guard creation, evaluated in this order after the state checks. Crew exclusivity: no two non-`CANCELLED` tasks of the same crew may have overlapping half-open intervals — adjacency, where one task's `end_date` equals the next task's `start_date`, is allowed — and a violation is `ERR_CREW_DOUBLE_BOOKED`. Site capacity: for every date the new task occupies, the sum of `crew_count` across the site's non-`CANCELLED` tasks occupying that date, plus the new task's `crew_count`, must not exceed the site's `daily_crew_capacity`; a load exactly equal to capacity is permitted, and anything beyond it is rejected with `ERR_SITE_CAPACITY_EXCEEDED`. A created task is `SCHEDULED`, and its crew's `booked_days` ledger is debited by the task's `crew_days`. Tasks may be listed filtered by `shipment_id`, `crew_id`, `school_site_id`, or `status`.

The on-site work belongs to the `CrewLead`. Starting a task moves it `SCHEDULED` → `IN_PROGRESS` and requires that the acting crew lead's own crew is the task's assigned crew (`ERR_SCOPE_VIOLATION` otherwise) and that the shipment has reached `DELIVERED` — goods must be on site, otherwise `ERR_INVALID_STATE`. Completion moves the task `IN_PROGRESS` → `COMPLETED` and again enforces crew ownership. The completion payload carries three booleans — `uncrated`, `debris_removed`, and `placed` — and all three must be true; an incomplete checklist is rejected with `ERR_INSTALL_CHECKLIST_INCOMPLETE`. On success the task records `completed_checklist` as the ordered set `UNCRATED`, `DEBRIS_REMOVED`, `PLACED`, its crew's `booked_days` is credited back the task's `crew_days` (the ledger counts only `SCHEDULED` and `IN_PROGRESS` tasks), and the verification cascade fires: every PO line on the shipment with `delivered_qty` greater than zero moves `DELIVERED` → `VERIFIED` with `installed_at` stamped from the logical clock and its `delivered_qty` at that moment retained as the installed quantity — the warranty anchor of §3.9. When all tasks for a shipment have completed, the shipment itself bubbles `DELIVERED` → `COMPLETED`; when all non-`CANCELLED` lines of the order are `VERIFIED`, the order bubbles `IN_FULFILLMENT` → `FULFILLED`, unlocking the closeout of §3.4. A `FulfillmentCoordinator` may also unassign a `SCHEDULED` task, moving it to `CANCELLED` and crediting the crew's `booked_days` back the same `crew_days`, a compensating release that keeps the booking ledger conserved.

### 3.7. Damage Reporting and the Replacement Cascade

Damage surfaces in two phases, and a `CrewLead` files a **damage report** naming the affected `po_line_id`, the `damaged_qty` — at least 1 and no more than the line's `delivered_qty`, with excess rejected as `ERR_DAMAGE_EXCEEDS_DELIVERED` — the `discovered_during` phase (`DELIVERY` or `INSTALL`), and the `fault_type` (`TRANSIT`, `HANDLING`, or `DEFECT`). The discovery context must be self-consistent: a report with `discovered_during` `DELIVERY` must reference the `shipment_id` where the damage was found, while one with `INSTALL` must reference the `install_task_id` — exactly one of the two, matching the phase, or the filing is `ERR_INVALID_REQUEST`. Scope rules apply: a crew lead files install-phase reports only for their own crew's tasks. At filing the report is `OPEN`, its `reported_date` is stamped from the logical clock's date, and its `replacement_deadline` is computed as the earlier of two candidate dates — the bid specification's `delivery_window_end` plus fourteen days, and the `reported_date` plus twenty-one days. Reports may be listed filtered by `shipment_id`, `install_task_id`, `po_line_id`, or `status`.

From `OPEN` the report forks. A `ContractManager` may close it without fault, moving it to the terminal `CLOSED_NO_FAULT` when no contractor obligation arises. Alternatively the manager approves a replacement, moving the report to `REPLACEMENT_ORDERED` — but only if the proposed `scheduled_date` falls on or before the report's `replacement_deadline`, inclusive; a later date is rejected with `ERR_REPLACEMENT_WINDOW_MISSED`. Approval cascades through three linked creations. First, a replacement shipment is created with `kind` `REPLACEMENT`, its `damage_report_id` pointing back to the report, status `SCHEDULED`, the approved `scheduled_date`, a destination site taken from the report's shipment or from the shipment behind the report's install task, and a single shipment line pairing the report's `po_line_id` with a quantity equal to `damaged_qty`. Second, that shipment creation itself spawns a `SCHEDULED` install task built from the request's `crew_id`, `start_date`, `end_date`, `crew_count`, and `room_label` — subject to the same crew double-booking and site-capacity checks of §3.6. Third, the new task debits that crew's `booked_days` by its computed `crew_days`, keeping the ledger synchronized. The replacement shipment then flows through the ordinary delivery and installation pipeline, and when its delivery completes the report's `damaged_qty`, the report moves `REPLACEMENT_ORDERED` → `RESOLVED`, a terminal state.

### 3.8. Backorder Declaration and District Communication

When the undelivered remainder of a line cannot ship on time, a `FulfillmentCoordinator` declares a backorder on a line in `ORDERED` or `PARTIALLY_DELIVERED` status. An undelivered remainder must exist — `ordered_qty` exceeding `delivered_qty` — otherwise the declaration is `ERR_INVALID_STATE`, and the supplied `initial_eta_date` must be strictly later than the logical clock's current date, failing which the declaration is rejected with `ERR_ETA_NOT_FORWARD`. Declaration moves the line to `BACKORDERED` and increments the line's `version`, and it is the head of a three-link cascade: a **backorder notice** is created in `OPEN` status with `revision_count` 0, `current_eta_date` set to the declared `initial_eta_date`, and `communicated_at` stamped from the logical clock; the purchase order's `open_backorder_count` is incremented by one; and the order's `posture` is recomputed — when the count reaches two or more, the order flips `ON_TRACK` → `AT_RISK`, activating the shipment-scheduling gate of §3.5 until the count recovers below two. The declaration endpoint returns the updated line.

Keeping the district informed is an iterative duty. While a notice is `OPEN` or `ETA_UPDATED`, the coordinator may communicate a revised ETA by supplying a `new_eta_date`; the revision is accepted only if it is strictly later than the notice's `current_eta_date` and strictly later than the clock's current date — anything else is `ERR_ETA_NOT_FORWARD`. Each accepted update sets `current_eta_date` to the new date, increments `revision_count` by one, re-stamps `communicated_at` from the clock, and leaves the notice in `ETA_UPDATED`, a loop that may repeat indefinitely. Updating a notice that is already `SUPERSEDED` or `RESOLVED` is rejected with `ERR_BACKORDER_NOT_OPEN`. Notices may be listed filtered by `po_line_id` or `status`.

A fresh backorder situation on the same line calls for a revised notice rather than an edit: the coordinator creates a new notice against the line with a new `initial_eta_date` (which must likewise be strictly later than the clock's current date, else `ERR_ETA_NOT_FORWARD`) and an optional free-text `note`. The create requires a line that is neither `CANCELLED` nor `VERIFIED` and a current open (`OPEN` or `ETA_UPDATED`) notice to supersede; either failing is `ERR_INVALID_STATE`. Because the create supersedes the line's current notice, the request must carry `expected_po_line_version` equal to the line's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.7. On success the prior `OPEN` or `ETA_UPDATED` notice becomes `SUPERSEDED`, a fresh notice opens with `revision_count` 0, `current_eta_date` taken from the request, and `communicated_at` stamped from the clock, and the line's `version` increments. Resolution of a notice, finally, is system-driven: when the linked line is fully delivered or is cancelled, its open notice — whether `OPEN` or `ETA_UPDATED` — moves to `RESOLVED`, and the order's `open_backorder_count` and `posture` are recomputed accordingly.

### 3.9. Warranty Terms, Claims, and Appeals

Warranty coverage anchors on each line's `installed_at` timestamp: the base term runs for the award's `warranty_years` years from the installation date, and districts enrolled via `extended_warranty_enrolled` receive the award's `extended_years` of prorated coverage beyond that. Claims support parts fulfillment for years after installation.

A `DistrictBuyer` files a **warranty claim** against an installed line by naming its `po_line_id`, the claimed `parts_cost_cents` (at least 1), and a `description` of the failure. Filing enforces its gates in order: the line must be `VERIFIED` (`ERR_LINE_NOT_VERIFIED`); the filing date must fall within the applicable term — on or before the base-term end for a non-enrolled district, or on or before the base-term end plus `extended_years` for an enrolled one — with a filing beyond the term rejected as `ERR_WARRANTY_EXPIRED`; no second claim may exist on the same line while one is `FILED`, `UNDER_REVIEW`, `APPEALED`, or `APPROVED` (`ERR_DUPLICATE_CLAIM`); and the claimed `parts_cost_cents` may not exceed the installed value of the line — its `delivered_qty` at verification multiplied by its `computed_unit_price_cents` — on pain of `ERR_CLAIM_EXCEEDS_COVERAGE`. A filed claim is `FILED` with `filed_date` stamped from the clock's date, `appeal_count` 0, and `coverage_cents`, `denial_reason`, and `parts_order_ref` null. Claims may be listed filtered by `po_line_id` or `status`.

Adjudication belongs to the `ServiceAgent`. Review moves a claim from `FILED` to `UNDER_REVIEW` — and likewise from `APPEALED` back to `UNDER_REVIEW` when an appeal is being reconsidered. From `UNDER_REVIEW` the claim is either approved or denied. Denial records the request's `denial_reason` on the claim and moves it to `DENIED`. Approval computes `coverage_cents` per the district's coverage variant and moves the claim to `APPROVED`. Under the standard term — the district not enrolled — a claim approved within term is covered in full: `coverage_cents` equals `parts_cost_cents`. Under the extended prorated variant, the covered share declines with time past the base term: the number of days from the base-term end to the filing date, floored at zero, is divided by 365 and rounded up to count started years beyond the base term; the covered percentage is one minus the ratio of those started years to the award's `extended_years`, floored at zero; and `coverage_cents` is `parts_cost_cents` multiplied by that percentage, rounded half-up to whole cents. When `extended_years` is 0, an enrolled district's term ends with the base term, so its claims are necessarily filed within the base term and are covered in full. Identical claim amounts and dates can therefore produce different coverage under the two variants — past the base term, the standard variant would already have rejected the filing, while the extended variant pays a prorated amount.

A denied district gets exactly one appeal. A `DistrictBuyer` appealing a `DENIED` claim supplies an `appeal_note`; the move to `APPEALED` is permitted only while `appeal_count` is still 0 — a second appeal attempt is `ERR_INVALID_STATE` — and sets `appeal_count` to 1, after which `DENIED` is effectively terminal. The appealed claim re-enters review and may again be approved or denied. Finally, a `ServiceAgent` orders replacement parts against an `APPROVED` claim, moving it to the terminal `CLOSED` status and recording a system-generated `parts_order_ref` that supports parts fulfillment for the life of the warranty relationship.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — state transitions, actions, and the clock set — return `200 OK`. All endpoints are mounted under the `/v1` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock (startup default 2026-05-01T00:00:00Z) | ContractorAdmin |
| POST | `/v1/districts` | Register a school district | ContractorAdmin |
| GET | `/v1/districts/{id}` | Get a District | All roles |
| POST | `/v1/school-sites` | Create a school site (delivery/installation destination) | DistrictBuyer |
| GET | `/v1/school-sites/{id}` | Get a SchoolSite | All roles |
| GET | `/v1/school-sites` | List SchoolSites | All roles |
| POST | `/v1/bid-specs` | Create a bid specification (DRAFT) | DistrictBuyer |
| GET | `/v1/bid-specs/{id}` | Get a BidSpec | All roles |
| GET | `/v1/bid-specs` | List BidSpecs | All roles |
| POST | `/v1/bid-specs/{id}/publish` | Publish a spec (from DRAFT, or re-publish from ADDENDUM_ISSUED) | DistrictBuyer |
| POST | `/v1/bid-specs/{id}/issue-addendum` | Issue an addendum (PUBLISHED/CLOSED/AWARDED → ADDENDUM_ISSUED) | DistrictBuyer |
| POST | `/v1/bid-specs/{id}/close` | Close a published spec to bidding | DistrictBuyer |
| POST | `/v1/spec-lines` | Add a line to a bid spec (only while DRAFT or ADDENDUM_ISSUED) | DistrictBuyer |
| GET | `/v1/spec-lines/{id}` | Get a SpecLine | All roles |
| GET | `/v1/spec-lines` | List SpecLines | All roles |
| POST | `/v1/coop-agreements` | Create a cooperative contract pricing agreement | ContractManager |
| GET | `/v1/coop-agreements/{id}` | Get a CoopPriceAgreement | All roles |
| POST | `/v1/awards` | Issue an award notice against a CLOSED bid spec | DistrictBuyer |
| GET | `/v1/awards/{id}` | Get an Award | All roles |
| GET | `/v1/awards` | List Awards | All roles |
| POST | `/v1/awards/{id}/accept` | Contractor accepts the award notice | ContractManager |
| POST | `/v1/awards/{id}/issue-amendment` | Amend an ACCEPTED award; re-pins the spec version (OCC-guarded) | DistrictBuyer |
| POST | `/v1/purchase-orders` | District PO intake against an ACCEPTED award | DistrictBuyer |
| GET | `/v1/purchase-orders/{id}` | Get a PurchaseOrder | All roles |
| GET | `/v1/purchase-orders` | List PurchaseOrders | All roles |
| POST | `/v1/purchase-orders/{id}/accept` | Contractor accepts a PO (fiscal cap check); lines become ORDERED | FulfillmentCoordinator |
| POST | `/v1/purchase-orders/{id}/cancel` | District cancels a PO (RECEIVED, or ACCEPTED with no shipments) | DistrictBuyer |
| POST | `/v1/purchase-orders/{id}/close` | Close a FULFILLED PO; computes the install closeout total | FulfillmentCoordinator |
| POST | `/v1/po-lines` | Add a line to a RECEIVED PurchaseOrder; computes tiered or flat pricing | DistrictBuyer |
| GET | `/v1/po-lines/{id}` | Get a POLine | All roles |
| GET | `/v1/po-lines` | List POLines | All roles |
| POST | `/v1/po-lines/{id}/declare-backorder` | Declare the undelivered remainder backordered; creates the district notice | FulfillmentCoordinator |
| POST | `/v1/po-lines/{id}/cancel` | Cancel an undelivered line (compensates drawdown) | DistrictBuyer |
| POST | `/v1/po-lines/{id}/backorder-notices` | Create a revised backorder notice superseding the current one (OCC-guarded) | FulfillmentCoordinator |
| POST | `/v1/shipments` | Schedule a summer-window shipment of PO lines to a school site | FulfillmentCoordinator |
| GET | `/v1/shipments/{id}` | Get a Shipment | All roles |
| GET | `/v1/shipments` | List Shipments | All roles |
| POST | `/v1/shipments/{id}/mark-delivered` | Record delivery with per-line quantities and actual manufacturer/model | FulfillmentCoordinator |
| POST | `/v1/crews` | Register an installation crew | ContractorAdmin |
| GET | `/v1/crews/{id}` | Get a Crew | All roles |
| POST | `/v1/install-tasks` | Assign a crew to uncrate/install/place a shipment at a site | FulfillmentCoordinator |
| GET | `/v1/install-tasks/{id}` | Get an InstallTask | All roles |
| GET | `/v1/install-tasks` | List InstallTasks | All roles |
| POST | `/v1/install-tasks/{id}/start` | Crew lead starts the task (requires shipment DELIVERED) | CrewLead |
| POST | `/v1/install-tasks/{id}/complete` | Complete with the uncrate/debris-removal/placement checklist | CrewLead |
| POST | `/v1/install-tasks/{id}/unassign` | Unassign a SCHEDULED task (compensates crew booking) | FulfillmentCoordinator |
| POST | `/v1/damage-reports` | File a damage report for delivered units | CrewLead |
| GET | `/v1/damage-reports/{id}` | Get a DamageReport | All roles |
| GET | `/v1/damage-reports` | List DamageReports | All roles |
| POST | `/v1/damage-reports/{id}/approve-replacement` | Approve replacement within window; cascades shipment, task, crew booking | ContractManager |
| POST | `/v1/damage-reports/{id}/close-no-fault` | Close a damage report without replacement | ContractManager |
| GET | `/v1/backorder-notices/{id}` | Get a BackorderNotice | All roles |
| GET | `/v1/backorder-notices` | List BackorderNotices | All roles |
| POST | `/v1/backorder-notices/{id}/update-eta` | Communicate a revised (later) ETA to the district | FulfillmentCoordinator |
| POST | `/v1/warranty-claims` | District files a warranty claim against a VERIFIED installed line | DistrictBuyer |
| GET | `/v1/warranty-claims/{id}` | Get a WarrantyClaim | All roles |
| GET | `/v1/warranty-claims` | List WarrantyClaims | All roles |
| POST | `/v1/warranty-claims/{id}/review` | Move claim to UNDER_REVIEW (from FILED or APPEALED) | ServiceAgent |
| POST | `/v1/warranty-claims/{id}/approve` | Approve claim; computes the covered amount per coverage variant | ServiceAgent |
| POST | `/v1/warranty-claims/{id}/deny` | Deny claim with reason | ServiceAgent |
| POST | `/v1/warranty-claims/{id}/appeal` | District appeals a denial (at most one appeal) | DistrictBuyer |
| POST | `/v1/warranty-claims/{id}/order-parts` | Order replacement parts under an approved claim | ServiceAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BID_SPEC_NOT_CLOSED` | 409 Conflict |
| `ERR_AWARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_PO_NUMBER` | 409 Conflict |
| `ERR_ORDER_WINDOW_CLOSED` | 409 Conflict |
| `ERR_SPEC_VERSION_STALE` | 409 Conflict |
| `ERR_AWARD_QTY_EXCEEDED` | 409 Conflict |
| `ERR_DISTRICT_FISCAL_CAP_EXCEEDED` | 409 Conflict |
| `ERR_OUTSIDE_DELIVERY_WINDOW` | 409 Conflict |
| `ERR_PO_AT_RISK_BLOCKS_SCHEDULING` | 409 Conflict |
| `ERR_SUBSTITUTION_NOT_ALLOWED` | 409 Conflict |
| `ERR_DELIVERY_EXCEEDS_ORDERED` | 409 Conflict |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_SITE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_DAMAGE_EXCEEDS_DELIVERED` | 409 Conflict |
| `ERR_REPLACEMENT_WINDOW_MISSED` | 409 Conflict |
| `ERR_LINE_NOT_VERIFIED` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM` | 409 Conflict |
| `ERR_CLAIM_EXCEEDS_COVERAGE` | 409 Conflict |
| `ERR_BACKORDER_NOT_OPEN` | 409 Conflict |
| `ERR_ETA_NOT_FORWARD` | 409 Conflict |
| `ERR_INSTALL_CHECKLIST_INCOMPLETE` | 409 Conflict |
