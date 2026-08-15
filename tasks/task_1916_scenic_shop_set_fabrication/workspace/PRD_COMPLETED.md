# Scenic Shop Fabrication API — Product Requirements Document

## 1. Introduction

A scenic construction shop lives and dies by three interlocking scarcities: crew-hours across the planning horizon, physical build bays, and trucks available for the load-in window. Concurrent productions compete for all three while clients revise drawings mid-stream, counter bids, and approve or reject finishes. Without a single system of record tying material takeoffs to bids, bids to productions, and productions back to shop capacity, shops routinely over-commit the build calendar, ship sets whose engineering was never stamped, or let reclaimed scenery leak out of inventory.

This document specifies the Scenic Shop Fabrication API, mounted under the `/scenic` prefix. It governs the full commercial and physical lifecycle of a build: a client uploads a design package, an estimator quantifies it with a material takeoff, a bid is priced either from that takeoff or as a rough-order-of-magnitude, a negotiation cycle may iterate between estimator and client, acceptance spawns a production, engineering reviews and finish samples gate the build, bays and trucks are reserved against hard capacity limits, change orders re-price design revisions against a live production, and strike returns reusable material to a valued stock inventory.

The API is deliberately opinionated about money, time, and concurrency. All monetary amounts are integer cents; all rates and percentages are integer basis points where 10000 represents one hundred percent; all datetimes are ISO 8601 UTC interpreted on a server-side logical clock; and three write operations carry optimistic-concurrency preconditions so that a writer can never price or adjust from a base version it has not observed.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system declares exactly seven roles, spelled exactly as follows: `ShopAdmin`, `Estimator`, `ShopForeman`, `StaffEngineer`, `PaintCharge`, `ClientPM`, and `TransportCoordinator`. A request missing either header, or presenting an `X-User-Role` value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed for the endpoint it targets is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `ClientPM`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` — a bid's `client_id`, a production's `client_id`, a design package's `client_id` — compare the resource's foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWN_RESOURCE` (HTTP 403). When `X-User-Role` is `ShopAdmin`, `Estimator`, `ShopForeman`, `StaffEngineer`, `PaintCharge`, or `TransportCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a rule requires — for example as `estimator_user_id` on a `Takeoff` or `prepared_by_user_id` on an `EngineeringReview` — but never compares it to any entity's `id` except where a specific rule names the comparison (the resubmit-preparer check and the segregation-of-duties check both compare against `prepared_by_user_id`).

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. For action endpoints that touch several resources, the resource named by the request path is returned: every bid action (submit, counter, revise, accept, reject, withdraw) returns the updated bid — acceptance included, not the spawned production — the production lifecycle actions (start-build, complete-build, load-in, strike, close) return the production, engineering-review, finish-sample, change-order, and transport-plan actions return the review, the sample, the change order, and the plan respectively, and run-epoch returns the updated shop.
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

List endpoints accept two query parameters. `limit` specifies the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`. A `limit` that is not an integer or falls outside the 1-to-100 range, and an `offset` that is not an integer or is negative, are rejected with `ERR_VALIDATION` (HTTP 400). Resources that share the same `created_at` are ordered by creation sequence.

### 2.4. The Logical Clock, Money, and Basis Points

All time-dependent rules in the system read a server-side **logical clock**, never wall-clock time. Before any operator has set it, the logical clock reads exactly `2026-08-01T00:00:00Z` — this default is normative. A `ShopAdmin`-only test-driving capability advances the clock: it accepts a `to_iso8601` instant, after which every subsequent time-dependent rule (bid validity, load-in buffers, urgency multipliers, epoch expiry) evaluates against the supplied instant. The capability returns the current reading as `current_utc`; the supplied instant may lie in the past or the future — no range check applies.

All monetary values — prices, costs, subtotals, credit limits, deltas — are integer **cents**. All rates, multipliers, and percentages are integer **basis points** (bp), where 10000 bp equals one hundred percent; an overtime multiplier of 15000 bp therefore means one and a half times straight time, and a condition factor of 6000 bp means sixty percent. Load figures in engineering reviews (`design_load_lb`, `member_capacity_lb`) are numbers with up to two decimal places.

### 2.5. Common Resource Properties

Every top-level resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on any mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments on every mutation of the resource, including mutations driven by cascades originating on another resource.

All datetimes the server emits are rendered uniformly: an ISO 8601 UTC string with exactly three fractional digits and a trailing `Z` (for example, `2026-08-01T00:00:00.000Z`). This convention covers `created_at` and `updated_at` on every resource, the `meta.api_request_timestamp`, the clock capability's `current_utc`, clock-recorded fields such as a bid's `valid_until` and a production's `built_at`, deadline fields such as a production's `load_in_deadline_at`, and request-supplied datetimes echoed back in responses such as `load_in_at`, `strike_at`, `build_start_at`, `window_start`, `window_end`, `depart_at`, and `arrive_at`.

Any mutation described anywhere in §3 — a status transition, a recomputed aggregate, a cascade applying a change order — refreshes `updated_at` and increments `version` on each entity it touches. Where a cascade mutates one entity in several steps (as change-order approval does on its production), the production's `version` is incremented for each mutation step in that cascade.

### 2.6. Existence, Ownership, and the Validation Cascade

Requests are evaluated in a fixed priority order, and a failure at any tier short-circuits the rest:

1. **Authentication and role** — headers present, role declared, role listed for the endpoint (failures: `ERR_UNAUTHENTICATED`, `ERR_FORBIDDEN`).
2. **Ownership** — for `ClientPM`, `X-User-ID` must equal the target resource's `client_id`; for an engineering-review resubmit, `X-User-ID` must equal the review's `prepared_by_user_id` (failure: `ERR_NOT_OWN_RESOURCE`).
3. **Existence** — every path identifier and every body-referenced identifier (`shop_id`, `client_id`, `design_package_id`, `production_id`, `takeoff_id`, `stock_item_id`, and the consistency between a bid's takeoff and its design package) must resolve to an existing resource; the first unresolvable identifier rejects the request with `ERR_NOT_FOUND` (HTTP 404). For nested paths, identifiers are validated left to right.
4. **State legality** — the target entity must be in a state from which the requested transition exists; terminal entities reject all further actions; line mutations against a `LOCKED` takeoff are rejected with `ERR_TAKEOFF_LOCKED`; child-creation is gated on parent state as described in §3 (failures: `ERR_INVALID_STATE`, `ERR_TAKEOFF_LOCKED`).
5. **Safety and segregation** — engineering approval enforces the safety-factor thresholds and the approver-must-differ-from-preparer rule (failures: `ERR_SAFETY_FACTOR_INSUFFICIENT`, `ERR_SEGREGATION_OF_DUTIES`).
6. **Referential freshness** — drawing-revision pins and change-order revision currency (failures: `ERR_STALE_DRAWING_REVISION`, `ERR_REVISION_NOT_CURRENT`).
7. **Structural constraints** — bay-slot range, stock uniqueness, stock sufficiency, non-negative on-hand, conditional required fields (failures: `ERR_BAY_SLOT_INVALID`, `ERR_DUPLICATE_STOCK_ITEM`, `ERR_STOCK_INSUFFICIENT`, `ERR_STOCK_NEGATIVE`, `ERR_VALIDATION`).
8. **Temporal and capacity-window constraints** — bay overlap, reservation windows past the deadline, fleet over-commitment, the load-in buffer, bid expiry (failures: `ERR_BAY_OVERLAP`, `ERR_WINDOW_PAST_DEADLINE`, `ERR_FLEET_OVER_COMMITTED`, `ERR_LOAD_IN_TOO_SOON`, `ERR_BID_EXPIRED`).
9. **Fiscal constraints** — client credit at bid acceptance (failure: `ERR_CREDIT_LIMIT_EXCEEDED`).
10. **Capacity gates** — saturation gating on bid submission and acceptance; bay coverage at start-build (failures: `ERR_SHOP_SATURATED`, `ERR_BAY_UNDER_RESERVED`).
11. **Close barriers** — a close is first checked for unresolved change orders, then for open bay reservations (failures: `ERR_CHANGE_ORDERS_PENDING`, `ERR_RESERVATIONS_OPEN`).
12. **Optimistic concurrency** — where §2.8 applies, the expected parent version must match (failures: `ERR_STALE_PRODUCTION_VERSION`, `ERR_STALE_TAKEOFF_VERSION`, `ERR_STALE_STOCK_VERSION`).

### 2.7. Shop Capacity Posture

Each shop's load is summarized by a **capacity posture** derived from committed crew-hours. The shop's `committed_crew_hours` is the sum of `committed_crew_hours` over its productions whose status is `SCHEDULED`, `IN_BUILD`, or `ON_HOLD` — productions that are `BUILT`, `LOADED_IN`, `STRUCK`, or `CLOSED` are excluded from the sum. The shop's `capacity_ratio_bp` is the committed crew-hours multiplied by 10000 and divided by the product of `weekly_crew_hours_capacity` and `horizon_weeks`, rounded half-up to a whole basis point. The `posture` is `SATURATED` when `capacity_ratio_bp` is at least 10000, `TIGHT` when it is at least 8000 (a ratio of exactly 8000 bp is `TIGHT`), and `OPEN` otherwise. Posture is recomputed whenever any production's committed hours or qualifying status changes, and again by the operations checkpoint described in §3.7. Posture gates commercial activity: bid submission and bid acceptance are both rejected with `ERR_SHOP_SATURATED` while the shop is `SATURATED`, and posture selects the labor multiplier used when pricing change orders (§3.5).

### 2.8. Optimistic Concurrency Control

Three write operations require the caller to declare the version of the parent entity it last observed, as a non-optional request field. If the declared value does not equal the parent entity's current `version`, the request is rejected with the corresponding stale-version error — HTTP 412 in every case — and no mutation occurs. The protected writes and their fields are:

- **Creating a change order** requires `expected_production_version`, matched against the target production's current `version`; a mismatch is rejected with `ERR_STALE_PRODUCTION_VERSION` (HTTP 412). Multiple `PROPOSED` change orders on one production are legitimate, so without this check a second sequential create would silently price from a base — price, deadline, committed hours — the client has not observed.
- **Adding a takeoff line** requires `expected_takeoff_version`, matched against the target takeoff's current `version`; a mismatch is rejected with `ERR_STALE_TAKEOFF_VERSION` (HTTP 412). Adding further lines is always legitimate on a `DRAFT` takeoff, so a writer working from an out-of-date materials subtotal would otherwise price incorrectly.
- **Adjusting a stock item** requires `expected_stock_item_version`, matched against the item's current `version`; a mismatch is rejected with `ERR_STALE_STOCK_VERSION` (HTTP 412). Adjustments are signed deltas applied to the current on-hand value, so a stale writer would base its delta on an out-of-date quantity.

No other endpoint takes an expected-version field.

### 2.9. Drawing Revisions and Package Supersession

A `(client_id, show_title)` pair has exactly one `CURRENT` design package at any moment. When a client uploads a package for a pair that already has a `CURRENT` package, the prior package transitions to `SUPERSEDED` and the new upload becomes the sole `CURRENT` package, its `drawing_revision` set to one greater than the highest prior revision for that pair (the very first upload receives `drawing_revision` 1). Supersession never mutates bids or takeoffs pinned to the older revision in place; their pinned revision simply ceases to be current, and the staleness is detected when the bid is next submitted or accepted (§3.3); a takeoff's `pinned_package_revision` is informational only and is never re-validated against the package. Bids pin the package's revision at creation in `pinned_drawing_revision`; takeoffs pin it in `pinned_package_revision`; change orders consume the next revision by moving a production's `applied_drawing_revision` forward (§3.5).

### 2.10. Precision and Rounding

All rounding in the system is **round half-up**. Calculation results that are monetary are rounded to integer cents; safety factors are rounded to two decimal places; capacity ratios are rounded to whole basis points. Where a calculation specifies intermediate rounding steps — per-line totals before summation, load amplification before division, each stage of the bid build-up — the rounding happens at exactly those pinned steps and never on a later aggregate in their place. Field-level detail: a stock item's `reuse_unit_cost_cents`, `reuse_value_cents`, and `replacement_value_cents`, a takeoff line's `applied_unit_cost_cents` and `line_total_cents`, a bid's `price_cents`, a change order's `delta_price_cents`, and a review's `sf_static` and `sf_dynamic` are all computed values; clients never supply them.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Shop: Configuration, Clients, and Design Packages

A `ShopAdmin` begins by creating the shop itself, supplying its `name` and its capacity configuration: `weekly_crew_hours_capacity`, `horizon_weeks` (the capacity planning horizon in weeks), `bay_count` (the number of build bays; bay slots are numbered from 1 up to `bay_count`), and `truck_fleet_size` (the total trucks available for transport windows) — every one of these four must be greater than zero. The shop's rate card is fixed at the same moment: `labor_rate_cents_per_hour` (greater than zero), `overtime_multiplier_bp` (at least 10000; applied to labor when the posture is `TIGHT` or `SATURATED`), `overhead_pct_bp` (at least 0), and `margin_pct_bp` (at least 0). A new shop starts with `committed_crew_hours` 0, `capacity_ratio_bp` 0, `posture` `OPEN`, `inventory_value_cents` 0, and `epoch_index` 0.

Clients are the shop's commercial counterparties. A `ShopAdmin` registers a client with its `shop_id`, `company_name`, `contact_email`, and `credit_limit_cents` (at least 0); the client's `outstanding_cents` starts at 0 and is thereafter maintained by the system as the sum of `current_price_cents` over that client's productions whose status is `SCHEDULED`, `IN_BUILD`, `ON_HOLD`, `BUILT`, `LOADED_IN`, or `STRUCK` — a closed production drops out of the outstanding set.

With a client registered, a `ClientPM` uploads design packages, each carrying the owning `client_id`, the `show_title`, the `venue`, the contractual `load_in_at` deadline, and the contractual `strike_at` date, which must be strictly later than `load_in_at` (a violation is `ERR_VALIDATION`, HTTP 400). Re-uploading for a `(client_id, show_title)` that already has a current package triggers the supersession described in §2.9: the prior package becomes `SUPERSEDED`, the new one is the sole `CURRENT` package with the next `drawing_revision`, and bids pinned to the older revision are left untouched until they next try to move.

### 3.2. The Material Takeoff and Its Lines

An `Estimator` opens a **takeoff** against a design package, providing `design_package_id`, the estimated `labor_hours_est` (greater than zero), and optionally free-form `notes`. The system stamps the takeoff with the creating estimator's `X-User-ID` as `estimator_user_id`, pins the package's current revision into `pinned_package_revision`, starts `materials_subtotal_cents` at 0, and sets the takeoff's `status` to `DRAFT`. The referenced package may be in any status — a takeoff may be opened against a `SUPERSEDED` package as well as a `CURRENT` one.

The estimator then adds lines. Each line names its owning `takeoff_id`, a `material_code` (identifiers such as `LUMBER_4X8`, `STEEL_TUBE`, or `PAINT_GAL`), a `quantity` (greater than zero), and a `source` of either `PURCHASE` or `STOCK`. Conditional requirements follow the source: a `PURCHASE` line must supply `unit_cost_cents` and must not carry `stock_item_id`; a `STOCK` line must supply `stock_item_id`, and any `unit_cost_cents` is ignored because the unit cost derives from the referenced stock item's condition factor. On the stored line the inapplicable conditional field is echoed as null — `stock_item_id` on a `PURCHASE` line and `unit_cost_cents` on a `STOCK` line. Violating either conditional rule — or, anywhere in the system, omitting a universally required field, supplying a value of the wrong JSON type, sending a malformed or non-object JSON body, supplying an invalid enum value, giving a non-positive quantity, or giving a window or deadline whose end does not strictly follow its start — is rejected with `ERR_VALIDATION` (HTTP 400). The unknown-field rule applies to every endpoint that consumes a request body: passing an unknown field to one is `ERR_VALIDATION`; action endpoints that define no request fields (such as the bid decision endpoints, review and sample approvals, the change-order decisions, transport confirm/cancel, the production lifecycle actions, run-epoch, and the two DELETEs) do not parse a body and ignore any fields supplied. A line may also carry `waste_pct_bp`, a cut-and-waste allowance in basis points that defaults to 0 and must be at least 0.

Each line's economics are computed per line, and the rounding happens per line before any summation. For a `PURCHASE` line, `applied_unit_cost_cents` is the supplied `unit_cost_cents`. For a `STOCK` line, `applied_unit_cost_cents` is the referenced item's `replacement_cost_cents` multiplied by the condition factor for its `condition_grade` — 6000 bp for grade `A`, 4000 bp for grade `B`, 2500 bp for grade `C` — divided by 10000, rounded half-up to a whole cent. The line's `line_total_cents` is then `quantity` multiplied by `applied_unit_cost_cents`, multiplied by the quantity 10000 plus `waste_pct_bp`, divided by 10000, rounded half-up to a whole cent. The takeoff's `materials_subtotal_cents` is the sum of `line_total_cents` over all its lines, recomputed on every line addition or removal.

Stock consumption is immediate. Adding a `STOCK` line decrements the referenced item's `quantity_on_hand` by the line's `quantity`; if the requested quantity exceeds the on-hand quantity the request is rejected with `ERR_STOCK_INSUFFICIENT` (HTTP 409), though consuming exactly down to zero is allowed. The item's `status` flips from `ACTIVE` to `DEPLETED` whenever a mutation leaves `quantity_on_hand` at zero, and the shop's `inventory_value_cents` is recomputed. Removing a line from a draft takeoff compensates: a `STOCK` line's quantity is added back to the item's `quantity_on_hand`, the status flips back from `DEPLETED` to `ACTIVE` when the quantity leaves zero, and the inventory value is recomputed again. Both line addition and line removal increment the parent takeoff's `version` by 1.

A takeoff stops being editable the moment it becomes commercially load-bearing: when a `DETAILED` bid referencing the takeoff is submitted, the takeoff transitions `DRAFT → LOCKED`, and from then on any attempt to add or remove lines against it is rejected with `ERR_TAKEOFF_LOCKED` (HTTP 409). Takeoffs and their lines are discoverable through the filtered list endpoints — takeoffs by `design_package_id` and `status`, lines by `takeoff_id` and by `stock_item_id` (the latter giving reverse reachability from a stock item to every line consuming it).

### 3.3. Bidding and the Negotiation Cycle

An `Estimator` creates a bid with the target `client_id` and `design_package_id`, the `pricing_variant` (`DETAILED` or `ROM`), `has_automation_scope` (true when the design includes moving elements), `bays_required` (greater than zero), the planned `build_start_at` (which must be strictly earlier than the package's `load_in_at`), and `validity_days` (greater than zero). The remaining inputs depend on the variant. A `DETAILED` bid must supply `takeoff_id` and must not supply `floor_area_sqft`, `complexity_class`, or `estimated_crew_hours` — the takeoff's `labor_hours_est` is the capacity commitment source. A `ROM` bid must supply `floor_area_sqft` (greater than zero), `complexity_class` (one of `A_SIMPLE`, `B_STANDARD`, `C_COMPLEX`), and `estimated_crew_hours` (greater than zero), and must not supply `takeoff_id`. Conditional-field violations are `ERR_VALIDATION`. No ownership-consistency check ties the design package to the target client — a bid may reference any existing package regardless of which client owns it — and the package need not be `CURRENT` at creation; a stale pin simply fails later at submission or acceptance. At creation the system pins the package's current revision into `pinned_drawing_revision`, computes `price_cents` per the variant's pricing rule, and sets `status` to `DRAFT`, `round_no` to 1, `production_id` to null, and `valid_until` to null (it stays null until first submission).

**Detailed pricing** walks a pinned evaluation order, with round-half-up to integer cents at every step. First, each of the referenced takeoff's lines contributes its `line_total_cents`, computed per line as in §3.2. Second, the gross materials cost is the sum of those per-line totals. Third, the volume-discount tier is selected on the **pre-discount** gross: if the gross materials cost is at least 500000 cents, the tier discount is 500 bp, otherwise 0. Keying the tier on the discounted subtotal is the forbidden alternative reading — the tier test always sees the undiscounted gross. Fourth, the discounted materials cost is the gross multiplied by 10000 minus the tier discount, divided by 10000, rounded half-up. Fifth, the labor cost is the takeoff's `labor_hours_est` multiplied by the shop's `labor_rate_cents_per_hour`. Sixth, the base is discounted materials plus labor; overhead is the base multiplied by `overhead_pct_bp`, divided by 10000, rounded half-up; margin is base plus overhead, multiplied by `margin_pct_bp`, divided by 10000, rounded half-up; and the final `price_cents` is base plus overhead plus margin.

**ROM pricing** never reads takeoff lines; it prices from area, complexity, and urgency. The days until load-in are the whole days obtained by dividing the span between the package's `load_in_at` and the logical clock at creation by 86400 seconds, discarding any fractional day. When that figure is at most 28 days, the urgency multiplier is 12500 bp; otherwise it is 10000 bp. The price is `floor_area_sqft` multiplied by the complexity rate — 9000 cents per square foot for `A_SIMPLE`, 14000 for `B_STANDARD`, 22000 for `C_COMPLEX` — multiplied by the urgency multiplier, divided by 10000, rounded half-up to a whole cent. The same package priced by both variants will generally yield two different prices; that divergence is expected.

Submission moves the bid `DRAFT → SUBMITTED` and is performed by an `Estimator`. Three preconditions apply: the bid must currently be `DRAFT` (otherwise `ERR_INVALID_STATE`, HTTP 409); the design package must still be `CURRENT` and the bid's `pinned_drawing_revision` must still equal the package's `drawing_revision` (otherwise `ERR_STALE_DRAWING_REVISION`, HTTP 409 — this is where a superseded drawing first bites); and the shop's posture must not be `SATURATED` (otherwise `ERR_SHOP_SATURATED`). On success the bid's `valid_until` is set to the logical clock at submission plus `validity_days`, and for a `DETAILED` bid the referenced takeoff locks as described in §3.2. If that takeoff is already `LOCKED` — for example because another bid referencing it was submitted first — submission still succeeds; the lock is idempotent.

From `SUBMITTED`, the bid can travel several roads. A `ClientPM` acting for the bid's client — `X-User-ID` must equal the bid's `client_id`, else `ERR_NOT_OWN_RESOURCE` — may counter it, supplying a `counter_price_cents` target (any integer; no positivity constraint) and an optional `note`; the bid moves to `COUNTERED`, and the counter values — validated for type only — are not persisted on the bid. An estimator may then revise a `COUNTERED` bid, supplying `revised_price_cents` (any integer; no positivity constraint): the bid's `price_cents` is replaced by the revised value, `round_no` increments by 1, `valid_until` is recomputed as the logical clock at revision plus `validity_days`, and the bid returns to `SUBMITTED` — the negotiation cycle. A client may also simply reject a `SUBMITTED` bid, moving it to `REJECTED`, and an estimator may withdraw a bid from `DRAFT`, `SUBMITTED`, or `COUNTERED` into `WITHDRAWN`; any other starting state for these actions is `ERR_INVALID_STATE`.

Acceptance is the heaviest transition in the commercial half of the system, moving the bid from `SUBMITTED` to `ACCEPTED`. A `ClientPM` accepts a bid that is `SUBMITTED`, owned by their client, still revision-fresh (package `CURRENT` and `pinned_drawing_revision` equal to the package's `drawing_revision`, else `ERR_STALE_DRAWING_REVISION`), not past its `valid_until` against the logical clock (else `ERR_BID_EXPIRED`, HTTP 409), credit-worthy — the client's `outstanding_cents` plus the bid's `price_cents` must be no greater than `credit_limit_cents`, with equality passing (else `ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 409) — and against a shop that is not `SATURATED` (else `ERR_SHOP_SATURATED`). Acceptance spawns a `Production` in `SCHEDULED` status: its `shop_id` is the client's shop; `bid_id`, `client_id`, `show_title`, `build_start_at`, and `bays_required` are copied from the bid and its package; `load_in_deadline_at` is the package's `load_in_at`; `strike_at` is the package's `strike_at`; `committed_crew_hours` is the takeoff's `labor_hours_est` for a `DETAILED` bid or the bid's `estimated_crew_hours` for a `ROM` bid; `applied_drawing_revision` is the bid's `pinned_drawing_revision`; `required_review_scopes` is `STRUCTURAL` alone, or `STRUCTURAL` plus `AUTOMATION` when the bid's `has_automation_scope` is true; and `current_price_cents` starts at the accepted bid's `price_cents`. The bid's `production_id` is set to the new production, the shop's `committed_crew_hours` increases by the production's committed hours with `capacity_ratio_bp` and `posture` recomputed, and the client's `outstanding_cents` is recomputed to include the new production's price.

Finally, bids do not linger forever: the operations checkpoint (§3.7) moves every `SUBMITTED` bid of the shop whose `valid_until` has fallen behind the logical clock into `EXPIRED`.

### 3.4. Engineering Approval, Finish Approval, and the Build Gates

A production in `SCHEDULED` cannot start building until two independent gates pass, enforced when a `ShopForeman` starts the build. First, for every scope in the production's `required_review_scopes` there must exist an `APPROVED` engineering review for this production with that scope — otherwise the start is rejected with `ERR_ENGINEERING_NOT_APPROVED` (HTTP 409). Second, the count of `ACTIVE` bay reservations belonging to the production must be at least the production's `bays_required` — otherwise the start is rejected with `ERR_BAY_UNDER_RESERVED` (HTTP 409). On success the production moves `SCHEDULED → IN_BUILD`.

**Engineering reviews** are created by a `ShopForeman` or `StaffEngineer` with the target `production_id`, a `scope` of `STRUCTURAL` or `AUTOMATION`, the anticipated `design_load_lb`, and the rated `member_capacity_lb` — both positive numbers with up to two decimals. An `AUTOMATION` review must additionally supply `impact_factor_bp` (at least 10000), while a `STRUCTURAL` review must not carry it; violating either conditional rule is `ERR_VALIDATION`. The creating user's `X-User-ID` is recorded as `prepared_by_user_id`, and the review opens in `PENDING` with `round_no` 1. Reviews may be created only while the production is not `STRUCK` or `CLOSED`.

Two safety factors are computed at creation and at every resubmission, each rounded half-up to two decimal places. `sf_static` is `member_capacity_lb` divided by `design_load_lb`. For `AUTOMATION` reviews, the load is amplified before division: the effective load is `design_load_lb` multiplied by `impact_factor_bp`, divided by 10000, rounded half-up to two decimals, and `sf_dynamic` is `member_capacity_lb` divided by that effective load, again rounded half-up to two decimals. A `STRUCTURAL` review carries no `sf_dynamic`. Approval is performed by a `StaffEngineer` and enforces, in this order within the safety tier: the approver must not be the user recorded as `prepared_by_user_id` — segregation of duties, failing with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and the static factor must be at least 1.50 (a value of exactly 1.50 passes) and, for `AUTOMATION`, the dynamic factor must be at least 2.00 (exactly 2.00 passes), failing with `ERR_SAFETY_FACTOR_INSUFFICIENT` (HTTP 422). Identical numbers that pass a `STRUCTURAL` review can fail an `AUTOMATION` one. A review not in `PENDING` rejects both approval and revision requests with `ERR_INVALID_STATE`.

The review cycle is where build work pauses. When a `StaffEngineer` requests a revision, supplying a `revision_note`, the review moves `PENDING → REVISION_REQUIRED`, the note is recorded, and if the production is currently `IN_BUILD` it transitions to `ON_HOLD` — complete-build is rejected while a production is `ON_HOLD`, because that transition is gated to `IN_BUILD`. The preparer alone resubmits: a `ShopForeman` or `StaffEngineer` whose `X-User-ID` equals `prepared_by_user_id` (otherwise `ERR_NOT_OWN_RESOURCE`) supplies fresh `design_load_lb`, `member_capacity_lb`, and, for `AUTOMATION`, `impact_factor_bp`; the review returns `REVISION_REQUIRED → PENDING`, both safety factors are recomputed, `round_no` increments by 1, and the recorded `revision_note` is retained. When an approval lands and the production is `ON_HOLD` and every engineering review of the production is now `APPROVED`, the production automatically returns `ON_HOLD → IN_BUILD`.

**Finish samples** run a parallel client-facing loop. A `PaintCharge` submits a sample with `production_id`, a `finish_code` (a paint or finish specification code such as `SCUFF_BRICK_RED`), and a `texture_ref`; the sample opens in `SUBMITTED` with `round_no` 1. A `ClientPM` acting for the production's client approves it (`SUBMITTED → APPROVED`) or rejects it with a `rejection_note` (`SUBMITTED → REJECTED`); the note is recorded on the sample. A `PaintCharge` resubmits a `REJECTED` sample with a new `texture_ref`, returning it to `SUBMITTED` and incrementing `round_no`; the recorded `rejection_note` is retained. Samples are creatable only while the production is not `STRUCK` or `CLOSED`.

Completing the build is the third gate. A `ShopForeman` marks a production complete only when it is `IN_BUILD` (else `ERR_INVALID_STATE`), no engineering review of the production sits in `PENDING` or `REVISION_REQUIRED` (else `ERR_ENGINEERING_NOT_APPROVED`), every finish sample of the production is `APPROVED` (else `ERR_FINISH_NOT_APPROVED`, HTTP 409), and the gap between the production's `load_in_deadline_at` and the logical clock is at least two full days — a gap of exactly two days passes, anything shorter is rejected with `ERR_LOAD_IN_TOO_SOON` (HTTP 409). On success the production moves `IN_BUILD → BUILT` and the system records the logical clock reading in `built_at`.

### 3.5. Change Orders Against a Live Production

Design revisions do not stop at acceptance. An `Estimator` prices a change order against a production, supplying `production_id`, the OCC field `expected_production_version` (§2.8), `new_drawing_revision`, and three signed deltas: `delta_materials_cents` (whose absolute value may not exceed 100000000 cents), `delta_labor_hours`, and `delta_load_in_days` (a negative value pulls the deadline earlier). A change order may be created only while the production's status is `SCHEDULED`, `IN_BUILD`, `ON_HOLD`, `BUILT`, or `LOADED_IN`. The `new_drawing_revision` must equal the design package's current revision and must be strictly greater than the production's `applied_drawing_revision`; otherwise the create is rejected with `ERR_REVISION_NOT_CURRENT` (HTTP 409).

The change order's price is computed once, at creation, and pinned on the order as `delta_price_cents`; approval later applies this pinned value, never a recomputation. Two ambient facts are captured at creation for the pricing decision: `priced_posture` (the shop's posture at that moment) and `priced_production_status` (the production's status at that moment). The evaluation order is pinned. The labor multiplier is the shop's `overtime_multiplier_bp` when the posture at creation is `TIGHT` or `SATURATED`, and 10000 otherwise. The labor component carries the sign of `delta_labor_hours` and the magnitude of its absolute value multiplied by `labor_rate_cents_per_hour`, multiplied by the labor multiplier, divided by 10000, rounded half-up to a whole cent. The rush component applies only when `delta_load_in_days` is negative and the labor component is positive: the rush rate is 500 bp per day of deadline compression, capped at 3000 bp — the cap binds once the compression reaches six days — and the rush component is the labor component multiplied by the rush rate, divided by 10000, rounded half-up. The materials component applies a rework multiplier of 12000 bp when the production's status at creation is `BUILT` or `LOADED_IN`, and 10000 otherwise: the component is `delta_materials_cents` multiplied by 10000 plus `overhead_pct_bp`, divided by 10000, multiplied by the rework multiplier, divided by 10000, rounded half-up. The pinned `delta_price_cents` is the sum of the materials, labor, and rush components. Change orders deliberately carry **no margin** — cost plus overhead only — a deliberate divergence from bid pricing. Each new change order also receives its `co_no`, a per-production monotone sequence starting at 1 in creation order; because creation is serialized by the production OCC check, ties are impossible. The order opens in `PROPOSED`, and its creation increments the production's `version` by 1.

A `ClientPM` acting for the production's client decides the order. **Approval** runs the full cascade: the production's `current_price_cents` increases by the pinned `delta_price_cents`; `load_in_deadline_at` shifts by `delta_load_in_days` whole days; `committed_crew_hours` becomes the greater of 1 and the prior committed hours plus `delta_labor_hours` — the floor at 1 means hours may shrink but never below one; and `applied_drawing_revision` advances to the order's `new_drawing_revision`. The deadline mutation cascades to the bays: every `ACTIVE` bay reservation of the production whose `window_end` lies after the new `load_in_deadline_at` transitions to `RELEASED`. The hours mutation cascades to the shop: `committed_crew_hours`, `capacity_ratio_bp`, and `posture` are all recomputed. The price mutation cascades to the client: `outstanding_cents` is recomputed. The production's `version` increments for each mutation step in this cascade. **Rejection** is the compensating-invariant anchor: the order moves to `REJECTED` and production fields, bay reservations, and shop aggregates are explicitly untouched. An `Estimator` may instead withdraw a `PROPOSED` order into `WITHDRAWN` with no other effects. Any decision on an order no longer `PROPOSED` is `ERR_INVALID_STATE`, and a client deciding another client's order is `ERR_NOT_OWN_RESOURCE`.

### 3.6. Bays, Trucks, and Load-In

Fabrication occupies physical bays. A `ShopForeman` reserves a bay by supplying `production_id`, the `bay_slot` (which must lie between 1 and the shop's `bay_count` inclusive, else `ERR_BAY_SLOT_INVALID`, HTTP 422), and a `window_start` strictly before `window_end`. Windows are **half-open** — the occupation spans from `window_start` up to but not including `window_end` — so two reservations on the same bay slot may be adjacent, one ending exactly when the next begins. A new reservation is rejected with `ERR_BAY_OVERLAP` (HTTP 409) if its window overlaps any `ACTIVE` reservation on the same `bay_slot` of the same shop, and with `ERR_WINDOW_PAST_DEADLINE` (HTTP 409) if `window_end` lies after the production's `load_in_deadline_at` at creation. Reservations are creatable only while the production is not `STRUCK` or `CLOSED`. Releasing a reservation is a soft delete: the row transitions `ACTIVE → RELEASED`, remains queryable thereafter — list and get endpoints include `RELEASED` rows, distinguishable by `status` — but is excluded from overlap checks and from the reserved-count sums that gate start-build. Releasing a reservation that is not `ACTIVE` is `ERR_INVALID_STATE`.

Transport is planned by a `TransportCoordinator`, who supplies `production_id`, the `truck_count` (at least 1), the `install_crew_hours` (at least 1), and the fleet occupation window from `depart_at` to `arrive_at` (the departure must be strictly earlier than the arrival, and the window is likewise half-open). Fleet capacity is enforced across the shop: the sum of `truck_count` over the shop's plans whose status is not `CANCELLED` and whose windows overlap the new window, plus the new plan's own `truck_count`, must not exceed the shop's `truck_fleet_size` — otherwise the plan is rejected with `ERR_FLEET_OVER_COMMITTED` (HTTP 409). Plans are creatable only while the production is not `STRUCK` or `CLOSED`, and a plan opens in `PLANNED`.

A coordinator confirms a `PLANNED` plan, moving it to `CONFIRMED` — provided the production has not already reached `LOADED_IN`, `STRUCK`, or `CLOSED` (else `ERR_INVALID_STATE`) — or cancels a `PLANNED` plan into `CANCELLED`, at which point it stops counting toward the fleet overlap sums. Load-in itself is executed by a `TransportCoordinator` against a production in `BUILT`: it requires at least one `CONFIRMED` transport plan for the production (else `ERR_TRANSPORT_NOT_CONFIRMED`, HTTP 409), moves the production `BUILT → LOADED_IN`, and as a side effect every `CONFIRMED` plan of that production transitions to `EXECUTED`.

### 3.7. Strike, Stock, Close, and the Operations Checkpoint

When the show comes down, a `ShopForeman` strikes a production in `LOADED_IN`, supplying the `reclaim_lines` — each line naming a `material_code`, a `quantity` (greater than zero), a `condition_grade`, and a `replacement_cost_cents` (greater than zero) — a violation is `ERR_VALIDATION`. For each line the system finds the stock item of the production's shop matching that `material_code` and `condition_grade` — of any origin — or creates one when none matches, with `origin` `RECLAIMED`, `quantity_on_hand` starting at 0, and the line's `replacement_cost_cents`; the line's quantity is then added to the item's `quantity_on_hand`. An existing item keeps its own `replacement_cost_cents` — the line's cost figure is used only when the item is created — and an item minted by a strike records the quantity addition as a mutation, so its `version` is 2 after its first reclaim line. Every touched item whose quantity leaves zero flips `DEPLETED → ACTIVE`, and the shop's `inventory_value_cents` is recomputed after all lines have applied. The production moves to `STRUCK`.

**Stock items** are the shop's reuse inventory. A `ShopAdmin` registers purchased stock with `shop_id`, `material_code`, `condition_grade` (`A`, `B`, or `C`), `quantity_on_hand` (at least 0), and `replacement_cost_cents` (greater than zero); the combination of `shop_id`, `material_code`, and `condition_grade` must be unique among the shop's items, else `ERR_DUPLICATE_STOCK_ITEM` (HTTP 409). Registered items carry `origin` `PURCHASED`. Every item exposes three computed valuations: `reuse_unit_cost_cents` is `replacement_cost_cents` multiplied by the condition factor — 6000 bp for `A`, 4000 bp for `B`, 2500 bp for `C` — divided by 10000, rounded half-up to a whole cent; `reuse_value_cents` is `quantity_on_hand` multiplied by `reuse_unit_cost_cents` (the recovery basis); and `replacement_value_cents` is `quantity_on_hand` multiplied by `replacement_cost_cents` (the replacement basis, which exceeds the recovery basis for every grade since every factor lies below 10000 bp). The shop's `inventory_value_cents` is the sum of `reuse_value_cents` over all its items regardless of status — depleted items contribute zero — and is folded back onto the shop on every quantity mutation. An item's `status` is system-managed: `ACTIVE` exactly when `quantity_on_hand` is greater than zero, `DEPLETED` exactly when it is zero, flipping in either direction on every mutation — creation with zero, an adjustment, takeoff-line consumption or restoration, or strike reclaim. Beyond creation, `quantity_on_hand` changes only through the signed `delta_quantity` adjustment (with an optional `reason`), through takeoff-line consumption and restoration, and through strike reclaim. An adjustment is a `ShopAdmin` operation carrying the OCC field `expected_stock_item_version` (§2.8); it increments the item's `version` by 1 and must never drive `quantity_on_hand` below zero — a result below zero is rejected with `ERR_STOCK_NEGATIVE` (HTTP 409).

**Closing** a production is a `ShopForeman` action against a production in `STRUCK`, guarded by two barriers checked in this order: first, no change order of the production may remain `PROPOSED` — otherwise `ERR_CHANGE_ORDERS_PENDING` (HTTP 409); second, no bay reservation of the production may remain `ACTIVE` — otherwise `ERR_RESERVATIONS_OPEN` (HTTP 409). Closing moves the production to `CLOSED`, recomputes the shop's committed hours, `capacity_ratio_bp`, and `posture` — per §2.7 the production already dropped out of the committed set when it left `IN_BUILD`/`ON_HOLD`, so the close itself removes nothing — and recomputes the client's `outstanding_cents` now that the closed production has dropped out of the outstanding set.

The shop's day-to-day hygiene is an admin-only **operations checkpoint**. Running an epoch increments the shop's `epoch_index` by 1, expires every `SUBMITTED` bid of the shop whose `valid_until` has fallen behind the logical clock into `EXPIRED`, and recomputes the shop's capacity posture. A separate computed read, the shop summary, reports `posture`, `committed_crew_hours`, `capacity_crew_hours_horizon` (the product of `weekly_crew_hours_capacity` and `horizon_weeks`), `capacity_ratio_bp`, `active_productions` (the count of productions in the committed set), `inventory_value_cents`, and `epoch_index` on demand.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`; the two deletion-style operations — removing a takeoff line and releasing a bay reservation — return `204 No Content` with an empty data object. All endpoints are mounted under `/scenic`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/scenic/shops` | Create a shop (capacity configuration and rate card) | ShopAdmin |
| GET | `/scenic/shops/{shopId}` | Get a shop | Any declared role |
| GET | `/scenic/shops/{shopId}/summary` | Computed read: posture, capacity and inventory aggregates | Any declared role |
| POST | `/scenic/shops/{shopId}/run-epoch` | Operations checkpoint: expire stale bids, recompute posture, bump `epoch_index` | ShopAdmin |
| POST | `/scenic/_clock/set-current-utc` | Set the logical clock | ShopAdmin |
| POST | `/scenic/clients` | Create a client (production company) | ShopAdmin |
| GET | `/scenic/clients` | List clients (filterable by `shop_id`) | Any declared role |
| GET | `/scenic/clients/{clientId}` | Get a client | Any declared role |
| POST | `/scenic/design-packages` | Upload design drawings; re-upload for the same client and title supersedes the prior current package | ClientPM |
| GET | `/scenic/design-packages` | List design packages (filterable by `client_id`, `show_title`, `status`) | Any declared role |
| GET | `/scenic/design-packages/{packageId}` | Get a design package | Any declared role |
| POST | `/scenic/takeoffs` | Open a material takeoff against a design package | Estimator |
| GET | `/scenic/takeoffs` | List takeoffs (filterable by `design_package_id`, `status`) | Any declared role |
| GET | `/scenic/takeoffs/{takeoffId}` | Get a takeoff | Any declared role |
| POST | `/scenic/takeoff-lines` | Add a material line to a `DRAFT` takeoff (OCC on the takeoff's version) | Estimator |
| GET | `/scenic/takeoff-lines` | List takeoff lines (filterable by `takeoff_id`, `stock_item_id`) | Any declared role |
| GET | `/scenic/takeoff-lines/{lineId}` | Get a takeoff line | Any declared role |
| DELETE | `/scenic/takeoff-lines/{lineId}` | Remove a line from a `DRAFT` takeoff (compensates stock consumption) | Estimator |
| POST | `/scenic/bids` | Create a bid (`DETAILED` from a takeoff, or `ROM` from area and complexity) | Estimator |
| GET | `/scenic/bids` | List bids (filterable by `client_id`, `design_package_id`, `takeoff_id`, `production_id`, `status`) | Any declared role |
| GET | `/scenic/bids/{bidId}` | Get a bid | Any declared role |
| POST | `/scenic/bids/{bidId}/submit` | Submit a `DRAFT` bid to the client | Estimator |
| POST | `/scenic/bids/{bidId}/counter` | Client counters with a target price | ClientPM |
| POST | `/scenic/bids/{bidId}/revise` | Estimator re-prices a `COUNTERED` bid and resubmits | Estimator |
| POST | `/scenic/bids/{bidId}/accept` | Client accepts a `SUBMITTED` bid; spawns the production | ClientPM |
| POST | `/scenic/bids/{bidId}/reject` | Client rejects a `SUBMITTED` bid | ClientPM |
| POST | `/scenic/bids/{bidId}/withdraw` | Estimator withdraws a `DRAFT`/`SUBMITTED`/`COUNTERED` bid | Estimator |
| GET | `/scenic/productions` | List productions (filterable by `shop_id`, `client_id`, `bid_id`, `status`) | Any declared role |
| GET | `/scenic/productions/{productionId}` | Get a production | Any declared role |
| POST | `/scenic/productions/{productionId}/start-build` | Begin fabrication; gated on required engineering approvals and bay coverage | ShopForeman |
| POST | `/scenic/productions/{productionId}/complete-build` | Mark fabrication complete; gated on finish approvals, clean reviews, and the two-day load-in buffer | ShopForeman |
| POST | `/scenic/productions/{productionId}/load-in` | Execute load-in; requires a `CONFIRMED` transport plan | TransportCoordinator |
| POST | `/scenic/productions/{productionId}/strike` | Strike the set; reclaim reusable materials into stock | ShopForeman |
| POST | `/scenic/productions/{productionId}/close` | Close the production; releases committed crew-hours back to the shop | ShopForeman |
| POST | `/scenic/engineering-reviews` | Create a structural or automation safety review | ShopForeman, StaffEngineer |
| GET | `/scenic/engineering-reviews` | List engineering reviews (filterable by `production_id`, `scope`, `status`) | Any declared role |
| GET | `/scenic/engineering-reviews/{reviewId}` | Get an engineering review | Any declared role |
| POST | `/scenic/engineering-reviews/{reviewId}/approve` | Stamp approval; approver must differ from preparer and safety factors must pass | StaffEngineer |
| POST | `/scenic/engineering-reviews/{reviewId}/request-revision` | Send the review back for redesign; holds an in-progress build | StaffEngineer |
| POST | `/scenic/engineering-reviews/{reviewId}/resubmit` | Preparer resubmits revised numbers | ShopForeman, StaffEngineer |
| POST | `/scenic/finish-samples` | Submit a finish and texture sample for client approval | PaintCharge |
| GET | `/scenic/finish-samples` | List finish samples (filterable by `production_id`, `status`) | Any declared role |
| GET | `/scenic/finish-samples/{sampleId}` | Get a finish sample | Any declared role |
| POST | `/scenic/finish-samples/{sampleId}/approve` | Client approves the sample | ClientPM |
| POST | `/scenic/finish-samples/{sampleId}/reject` | Client rejects the sample with a note | ClientPM |
| POST | `/scenic/finish-samples/{sampleId}/resubmit` | Paint charge resubmits a rejected sample with a new texture reference | PaintCharge |
| POST | `/scenic/change-orders` | Price a design revision against a production (OCC on the production's version) | Estimator |
| GET | `/scenic/change-orders` | List change orders (filterable by `production_id`, `status`) | Any declared role |
| GET | `/scenic/change-orders/{coId}` | Get a change order | Any declared role |
| POST | `/scenic/change-orders/{coId}/approve` | Client approves a proposed change order; runs the price, deadline, and hours cascade | ClientPM |
| POST | `/scenic/change-orders/{coId}/reject` | Client rejects a proposed change order; the production is explicitly untouched | ClientPM |
| POST | `/scenic/change-orders/{coId}/withdraw` | Estimator withdraws a proposed change order | Estimator |
| POST | `/scenic/bay-reservations` | Reserve a bay slot for a production window (half-open; same-slot adjacency allowed) | ShopForeman |
| GET | `/scenic/bay-reservations` | List bay reservations (filterable by `production_id`, `bay_slot`, `status`; `RELEASED` rows included) | Any declared role |
| GET | `/scenic/bay-reservations/{reservationId}` | Get a bay reservation (`RELEASED` rows included) | Any declared role |
| DELETE | `/scenic/bay-reservations/{reservationId}` | Release an `ACTIVE` reservation (soft delete) | ShopForeman |
| POST | `/scenic/stock-items` | Register a purchased stock item; unique per shop, material, and condition grade | ShopAdmin |
| GET | `/scenic/stock-items` | List stock items (filterable by `shop_id`, `material_code`, `condition_grade`, `status`, `origin`) | Any declared role |
| GET | `/scenic/stock-items/{itemId}` | Get a stock item | Any declared role |
| POST | `/scenic/stock-items/{itemId}/adjust` | Adjust on-hand quantity by a signed delta (OCC on the item's version) | ShopAdmin |
| POST | `/scenic/transport-plans` | Plan transport and install for a production; fleet aggregate capacity enforced over overlapping windows | TransportCoordinator |
| GET | `/scenic/transport-plans` | List transport plans (filterable by `production_id`, `status`) | Any declared role |
| GET | `/scenic/transport-plans/{planId}` | Get a transport plan | Any declared role |
| POST | `/scenic/transport-plans/{planId}/confirm` | Confirm a planned transport | TransportCoordinator |
| POST | `/scenic/transport-plans/{planId}/cancel` | Cancel a planned transport | TransportCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_OWN_RESOURCE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TAKEOFF_LOCKED` | 409 |
| `ERR_STALE_PRODUCTION_VERSION` | 412 |
| `ERR_STALE_TAKEOFF_VERSION` | 412 |
| `ERR_STALE_STOCK_VERSION` | 412 |
| `ERR_SAFETY_FACTOR_INSUFFICIENT` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ENGINEERING_NOT_APPROVED` | 409 |
| `ERR_FINISH_NOT_APPROVED` | 409 |
| `ERR_TRANSPORT_NOT_CONFIRMED` | 409 |
| `ERR_BAY_OVERLAP` | 409 |
| `ERR_BAY_SLOT_INVALID` | 422 |
| `ERR_WINDOW_PAST_DEADLINE` | 409 |
| `ERR_BAY_UNDER_RESERVED` | 409 |
| `ERR_FLEET_OVER_COMMITTED` | 409 |
| `ERR_LOAD_IN_TOO_SOON` | 409 |
| `ERR_STALE_DRAWING_REVISION` | 409 |
| `ERR_REVISION_NOT_CURRENT` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 |
| `ERR_SHOP_SATURATED` | 409 |
| `ERR_STOCK_INSUFFICIENT` | 409 |
| `ERR_STOCK_NEGATIVE` | 409 |
| `ERR_DUPLICATE_STOCK_ITEM` | 409 |
| `ERR_BID_EXPIRED` | 409 |
| `ERR_CHANGE_ORDERS_PENDING` | 409 |
| `ERR_RESERVATIONS_OPEN` | 409 |
