# Air-Duct & Dryer-Vent Cleaning API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a back-office platform that runs an air-duct and dryer-vent cleaning operation end to end. A homeowner registers their property and the heating-and-cooling systems within it; a technician inspects the ducts, captures before-and-after photographs, and produces a priced estimate; a dispatcher packs the estimate into a crew member's daily route; and, once the work is done, the system finalizes an invoice, optionally generates a repair-upsell referral, and keeps recurring-service reminders ticking against a logical clock.

The platform is built around two intertwined concerns. The first is a **pricing engine** that must produce two distinct money figures for the same job — a provisional *estimate* quoted before work begins and a finalized *invoice* computed from what was actually performed — using the same arithmetic but different inputs. The second is **temporal windowing**: routes are bounded shifts into which timed service slots must be packed without collision, recurring plans fall due on calendar cadences, and upsell referrals lapse after a fixed lifetime. Because several writers may act on the same route or home, the system also relies on optimistic concurrency control to reject writes that were composed against a stale view of a parent record. The sections below define the contract precisely; the business-logic narrative in Section 3 then ties the rules to the workflows they govern.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles: `PlanAdmin`, `Dispatcher`, `Technician`, and `Homeowner`. A `PlanAdmin` owns pricing configuration and the lifecycle of recurring plans, and manages upsell referrals. A `Dispatcher` owns crews, routes, slot commits, work-order scheduling, and callbacks. A `Technician` performs inspections, quotes, and the on-site work-order lifecycle. A `Homeowner` is the customer: they read their own homes, plans, work orders, and inspections, and may file callback tickets.

Authorization is decided by role membership alone: once the user context is valid and the role is one of those permitted for the endpoint, the request proceeds, and `X-User-ID` is never compared against any persisted entity's `id` or foreign key. The two operator roles carry opaque identity — when `X-User-Role` is `PlanAdmin` or `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The two customer-facing roles are nominally entity-backed: when `X-User-Role` is `Technician`, `X-User-ID` is conceptually the `id` of the acting `CrewMember`, and when it is `Homeowner`, `X-User-ID` is conceptually the `id` of the acting `Homeowner`. However, the system performs no per-instance ownership check on any endpoint: it does not compare a resource's crew or homeowner foreign key to `X-User-ID`, so a `Homeowner` or `Technician` whose role authorizes an endpoint may act on or read any matching resource regardless of which entity backs their identity.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, has a minimum of 1, and a maximum of 100. A supplied `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100 rather than rejected. The `offset` parameter sets how many leading items to skip and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` that is present but not a valid integer is rejected with `ERR_INVALID_REQUEST`. List responses are sorted by `created_at` in ascending order unless an endpoint explicitly states otherwise. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in this system share four server-managed fields. The `id` is a server-minted UUID with no type prefix and serves identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created and never changed thereafter. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, including mutations driven by cascades from other resources. The `version` field is an integer that starts at 1 on creation and increases by one on every mutation; it is the basis for optimistic concurrency control described in Section 2.8.

These four fields are carried by `PricingConfig`, `Homeowner`, `Home`, `HvacSystem`, `CrewMember`, `RoutePlan`, `WorkOrder`, `Inspection`, `RecurringPlan`, `UpsellReferral`, and `CallbackTicket`. Every entity in this system carries the full set; there are no create-only resources that omit `updated_at` or `version`.

For a `WorkOrder` and a `CallbackTicket`, the `created_at` timestamp doubles as a chronological tie-break key: work orders are packed into routes in `created_at` order when ordering matters, and callback tickets are resolved in `created_at` order.

### 2.5. Hierarchical Consistency and Cascading Effects

Several operations mutate more than one record. Whenever a write touches a related record, that related record is itself mutated — its `updated_at` is refreshed and its `version` increases by one — exactly as if it had been written directly.

A `Home` carries two computed fields that must always reflect its children. The `active_system_count` is the number of child `HvacSystem` rows whose `status` is `ACTIVE`; it is recomputed whenever a system is added to or decommissioned from the home, and each such recomputation bumps the home's `version`. The `has_active_plan` flag is true exactly when the home has a `RecurringPlan` whose `lifecycle_status` is `ACTIVE`, and false otherwise; it is recomputed — and the home re-versioned — whenever a plan on that home is created, paused, resumed, or cancelled.

A `RoutePlan` carries the computed `committed_minutes` ledger, described in Section 3, which is maintained by commit and cancel side effects and must always equal a full recomputation over the route's committed work orders. The platform's consistency model is immediate: every cascade lands within the same operation that triggered it, so a read taken after the operation observes the fully reconciled state.

### 2.6. Nested Resource Retrieval and Path Validation

Some paths name more than one resource — for example, a system under a home, or the inspections under a work order. The system validates path identifiers left to right and rejects on the first one that does not resolve, before evaluating any deeper identifier or any business rule. A request for a system under a home that does not exist fails with `ERR_HOME_NOT_FOUND`; only once the home is confirmed does the system check the system identifier, which fails with `ERR_SYSTEM_NOT_FOUND` if absent. The same left-to-right discipline governs every other addressable resource: a missing work order yields `ERR_WORK_ORDER_NOT_FOUND`, a missing route yields `ERR_ROUTE_NOT_FOUND`, a missing recurring plan yields `ERR_PLAN_NOT_FOUND`, a missing referral yields `ERR_REFERRAL_NOT_FOUND`, a missing callback ticket yields `ERR_TICKET_NOT_FOUND`, a missing pricing config yields `ERR_PRICING_CONFIG_NOT_FOUND`, a missing homeowner yields `ERR_HOMEOWNER_NOT_FOUND`, and a missing crew member yields `ERR_CREW_NOT_FOUND`. All of these are HTTP 404.

The same not-found codes apply when a foreign key arrives in a request body rather than the path. A create whose body references a non-existent homeowner, home, crew member, work order, or callback ticket is rejected with the corresponding not-found error; in particular, when a service line names a `system_id` that is not an `HvacSystem` belonging to the same home, the request fails with `ERR_SYSTEM_NOT_FOUND`.

### 2.7. Money, Minutes, and Rounding Precision

All money in this system is expressed in integer cents — there are no fractional-cent values stored or returned. Both the estimate and the invoice are computed by rounding **half up** at each pinned step of the calculation rather than once at the end: the multi-system discount is rounded, then the plan-member discount is rounded, then the tax is rounded, and only then are the rounded parts summed. This "round-per-step then sum" discipline (never "sum then round") is part of the contract because the two approaches can differ by a cent. Durations are expressed in integer minutes and are likewise rounded half up where a fractional result would otherwise arise. The contamination risk score is an integer, with rounding applied half up to its density term before weighting.

### 2.8. Optimistic Concurrency Control

Two write operations carry an explicit version expectation; all others do not.

When a dispatcher commits a work-order slot onto a route, the request must include `expected_route_plan_version` carrying the `version` of the target `RoutePlan` that the dispatcher last observed. If that value does not equal the route's current `version` — for example, because another writer has already committed a slot and thereby advanced the route's `committed_minutes` and `version` since the dispatcher read it — the commit is rejected with `ERR_STALE_ROUTE_VERSION` (HTTP 412). This stale-version check is the final guard in the commit, evaluated after every other guard including the read-only slot-overlap test but before any arithmetic actually mutates the route, so a commit composed against an outdated route never silently overwrites a slot the dispatcher has not observed.

When a `PlanAdmin` enrolls a home in a recurring plan, the request must include `expected_home_version` carrying the `version` of the `Home` that the client last observed. If that value does not equal the home's current `version` — for example, because another writer has already enrolled the home in a plan, flipping `has_active_plan` and re-versioning the home — the create is rejected with `ERR_STALE_HOME_VERSION` (HTTP 412), because the client's view of the home is stale. Endpoints not named here take no version field and perform no such check.

### 2.9. The Logical Clock and Scheduled Actions

The platform runs against a server-controlled logical clock rather than wall-clock time. At startup the clock reads exactly `2026-04-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to real time. Every server-recorded instant reads from this logical clock and never from wall-clock time: each `created_at` and `updated_at`, the `enrolled_at` and `next_reminder_at` of a plan, and the `api_request_timestamp` echoed in every response envelope are all taken from the clock's current value at the moment of the write, so a resource created while the clock holds a given instant carries that instant verbatim. An operator advances the clock by supplying a target instant as `to_iso8601`. Advancing the clock is the system's heartbeat for time-driven transitions: on every set, the system re-evaluates recurring plans to surface any whose reminder has come due, and re-evaluates pending upsell referrals to expire any that have outlived their allowed lifetime. These same time-driven transitions are detailed in Section 3 alongside the workflows that depend on them.

### 2.10. Order of Validation

When a single request could fail several checks, the system evaluates them in a fixed priority order so that the reported error is deterministic. Authentication of the user context comes first: a missing or unknown user context surfaces as `ERR_MISSING_OR_INVALID_USER_CONTEXT` before anything else is examined. Role authorization comes second, surfacing as `ERR_FORBIDDEN_ROLE`. Third, the existence of every path resource is checked left to right, as described in Section 2.6. Fourth, foreign keys carried in the request body are checked for existence. Fifth, the request body shape is validated — required fields present, enumerations in range, integers within their declared bounds, and the service-line composition rules — failing as `ERR_INVALID_REQUEST` (HTTP 400). Sixth, the target resource's own state is checked against the requested transition. Seventh, cross-entity state guards are evaluated. Only after all of those do the domain-specific business rules run: crew UV certification, zone matching, shift-window containment, slot overlap, crew double-booking, the after-photo minimum, active-pricing-config rules, the one-plan-per-home rule, and finally the optimistic-concurrency version checks. The practical effect is that a structural problem is always reported ahead of a business-rule problem, and a state problem is reported ahead of a fiscal one.

## 3. Business Logic & Workflows

### 3.1. Homeowners, Homes, and HVAC Systems

The customer record is the `Homeowner`, registered with a `full_name`, an `email`, and a `phone`. The email must be unique among homeowners; a registration whose `email` collides with an existing homeowner's `email` is rejected with `ERR_INVALID_REQUEST`. The phone is used later for reminders and callbacks.

A `Home` belongs to a homeowner and is created against that owner's `homeowner_id`, together with an `address_line`, a `zone_code` (the service zone used for route grouping, such as Z1 or Z2), and a `square_footage` that must be greater than zero. On creation a home starts with an `active_system_count` of zero and `has_active_plan` false. The home's `square_footage` later participates in the duration calculation, and its `zone_code` later participates in route matching.

Each heating-and-cooling unit in a home is an `HvacSystem`, added under the home with a `label` (such as "Upstairs furnace") and a `register_count` — the number of supply and return registers on that system, which must be greater than zero. A newly added system carries `status` `ACTIVE` and is tied to its parent through `home_id`. Adding a system recomputes the home's `active_system_count`. A system may be decommissioned, moving its `status` to `DECOMMISSIONED`; the operation carries no state guard, so decommissioning a system whose `status` is already `DECOMMISSIONED` simply succeeds and re-sets it to `DECOMMISSIONED` rather than being rejected. Decommissioning likewise recomputes the home's `active_system_count`. Both the add and the decommission cascade to the home, refreshing its `updated_at` and incrementing its `version`. The register counts of the home's active systems feed the contamination risk score described in Section 3.6.

### 3.2. Pricing Configuration

All money figures derive from a `PricingConfig`, owned by a `PlanAdmin`. A config is created in `DRAFT` status carrying a full price book: `duct_base_cents` (the flat base for a duct-cleaning line), `duct_per_system_cents` (the marginal price per HVAC system beyond the first, applied to duct service), `dryer_vent_flat_cents` (the flat price for a dryer-vent line), `sanitize_per_system_cents` (the per-system price for a sanitize line), and the three add-on prices `addon_sanitizer_cents`, `addon_uv_cents`, and `addon_coil_cents`. It also carries three fractional rates, each between 0 and 1 inclusive: `multi_system_discount_pct`, the fraction taken off the duct line subtotal when the home has enough active systems; `plan_member_discount_pct`, the fraction taken off the whole service subtotal when the home holds an active recurring plan; and `tax_pct`, the sales-tax fraction applied after discounts. Every cents field must be zero or greater.

At most one config may be `ACTIVE` at any time. Activating a `DRAFT` config moves its `status` from `DRAFT` to `ACTIVE` and, as a cascade, retires whatever config was previously `ACTIVE` by moving its `status` to `RETIRED`. Activation is rejected with `ERR_PRICING_CONFIG_ALREADY_ACTIVE` if the target config is not in `DRAFT` (that is, it is already `ACTIVE` or `RETIRED`). Because quoting depends on a single live price book, a quote attempted when no config is `ACTIVE` fails with `ERR_NO_ACTIVE_PRICING_CONFIG`.

### 3.3. The Work-Order Lifecycle: Draft, Inspect, and Quote

A `WorkOrder` is the unit of service. A `Dispatcher` or `Technician` opens one for a home by supplying the `home_id`, a non-empty `service_lines` array, an optional `addons` array, and a `requested_start_minute` — the minute-of-day, from 0 up to but not including 1440, at which the homeowner would like the visit to begin. A new work order starts in `DRAFT`. Each entry in `service_lines` carries a `service_type` that is one of `DUCT`, `DRYER_VENT`, or `SANITIZE`. A `DUCT` or `SANITIZE` line must carry a `system_id` naming an HVAC system on the same home; a `DRYER_VENT` line must omit `system_id`. The `addons` array holds codes drawn from `SANITIZER`, `UV`, and `COIL`, and is deduplicated; if omitted it defaults to empty. A body that violates any of these shape rules — empty service lines, an unknown enumeration value, an out-of-range integer, or a service-line/`system_id` pairing rule — is rejected with `ERR_INVALID_REQUEST`.

A `Technician` records a before-service inspection on a `DRAFT` work order, advancing it `DRAFT → INSPECTED`. The inspect request body carries `before_photo_count` (zero or greater), a `dust_severity` rated from 0 to 10 inclusive, and an optional `recommend_hvac_repair` flag. Inspecting from `DRAFT` creates one `Inspection` row whose `phase` is `BEFORE`, populated from those body fields, and refreshes the work order's `updated_at`. The inspection row records the work order it belongs to through `work_order_id`, carries an `after_photo_count` (defaulting to 0) that is filled in only at completion, and uses `phase` values `BEFORE` and `AFTER` to distinguish the two captures. A work order whose `status` is not the one required for the requested transition is rejected with `ERR_WORK_ORDER_BAD_STATE`. Every service line in an inspect must reference systems that are `ACTIVE` on the work order's home; a line pointing at a decommissioned system fails with `ERR_SYSTEM_NOT_ACTIVE`.

A `Technician` then quotes an `INSPECTED` work order, advancing it `INSPECTED → QUOTED`. Quoting requires exactly one `ACTIVE` `PricingConfig`; if none is active the quote fails with `ERR_NO_ACTIVE_PRICING_CONFIG`. On a successful quote the active config's `id` is pinned onto the work order as `pricing_config_id`, capturing a snapshot of the price book for the rest of this work order's life. Quoting then computes the work order's `estimate_total_cents` and its `duration_minutes` (both detailed in Sections 3.4 and 3.5) and refreshes `updated_at`. A read of a work order exposes its computed `estimate_total_cents`, its finalized `invoice_total_cents`, and its `duration_minutes`.

A quoted work order may be sent back for revision: a `Technician` re-inspects it, advancing it `QUOTED → INSPECTED`, which replaces the `BEFORE` inspection row with a fresh one from the new inspect body and clears both `estimate_total_cents` and `pricing_config_id` back to null so a re-quote is required. Re-inspection is only allowed while the work order has not been committed to a route: if its `route_plan_id` is set, re-inspect is rejected with `ERR_WORK_ORDER_ALREADY_SCHEDULED`. This `QUOTED → INSPECTED → QUOTED` loop is the revision round.

### 3.4. Estimate Pricing at Quote Time

The estimate is computed when the work order moves from `INSPECTED` to `QUOTED`, using the just-pinned `PricingConfig` snapshot and the home's *current* counts. Let the home's active system count be the value of its `active_system_count` read live at quote time, and let the home's plan-membership be its `has_active_plan` read live at the same moment.

First, the three service-line subtotals are formed from the requested service lines. The duct subtotal is the number of `DUCT` lines multiplied by a per-line price, where that per-line price is `duct_base_cents` plus `duct_per_system_cents` times the number of active systems beyond the first — that is, the greater of zero and the active system count minus one. The sanitize subtotal is the number of `SANITIZE` lines times `sanitize_per_system_cents`. The dryer subtotal is the number of `DRYER_VENT` lines times `dryer_vent_flat_cents`.

Next, the multi-system discount applies to the duct subtotal alone: when the home's active system count is at least two — the multi-system threshold is two systems — the duct subtotal is replaced by the duct subtotal multiplied by one minus `multi_system_discount_pct`, rounded half up. The discount touches no other line. The add-on subtotal is then the sum, over the distinct add-on codes on the work order, of the matching add-on price (`addon_sanitizer_cents` for `SANITIZER`, `addon_uv_cents` for `UV`, `addon_coil_cents` for `COIL`).

The service subtotal is the sum of the (possibly discounted) duct subtotal, the sanitize subtotal, the dryer subtotal, and the add-on subtotal. The plan-member discount applies to that whole service subtotal, but only after the multi-system discount has already been applied — the evaluation order is fixed. When the home's `has_active_plan` is true, the service subtotal is replaced by the service subtotal multiplied by one minus `plan_member_discount_pct`, rounded half up. Tax is then the service subtotal multiplied by `tax_pct`, rounded half up. Finally, `estimate_total_cents` is the service subtotal plus the tax. Each rounding step — the duct discount, the plan discount, and the tax — is taken in that order, and only the rounded results are summed.

Because the estimate is a snapshot, a system added to or decommissioned from the home *after* the quote does not change `estimate_total_cents`; the figure is frozen at quote time.

### 3.5. Estimating On-Site Duration

At the same quote step the system computes `duration_minutes`, the estimated time on site. The base is a fixed twenty-minute setup allowance. To that is added a per-line component: each `DUCT` line contributes thirty-five minutes, each `SANITIZE` line contributes fifteen minutes, and each `DRYER_VENT` line contributes twenty-five minutes. A per-add-on component adds ten minutes for each distinct add-on code on the work order.

A non-linear "big-home" surcharge then applies, but only to the per-line component and only when two conditions hold together: the home's active system count is at least two and the home's `square_footage` is at least three thousand. When both hold, the per-line component is multiplied by a factor of 1.25 and rounded half up before being added in. The final `duration_minutes` is the setup allowance plus the (possibly surcharged) per-line component plus the per-add-on component. This duration is what the route ledger later consumes.

### 3.6. Routes, Crews, and Slot Commitment

A `CrewMember` is created by a `Dispatcher` with a `full_name`, a `home_zone_code` naming the zone the crew is based in, and an optional `certified_for_uv` flag (defaulting to false) marking whether the member may perform the `UV` add-on.

A `RoutePlan` is a single crew member's working day in one zone. A dispatcher creates it with the `crew_member_id`, a `zone_code`, a `service_date` (a calendar date in YYYY-MM-DD form), a `shift_start_minute`, and a `shift_end_minute`. The start minute lies from 0 up to but not including 1440; the end minute must be strictly greater than the start and may run up to 1440. A new route starts in `OPEN` with `committed_minutes` of zero. At create time the system also guards against crew double-booking: the chosen crew member must not already own another route on the same `service_date` whose shift window overlaps the new one. This overlap test uses the whole closed shift window `[shift_start_minute, shift_end_minute]` with no buffer, so two routes that merely touch at a shared boundary minute do count as overlapping; a violation is rejected with `ERR_CREW_DOUBLE_BOOKED`. (This whole-window, no-buffer, closed-interval test is deliberately different from the buffered slot-collision test used at commit time, described below.)

Committing a slot is how a quoted work order is scheduled. A `Dispatcher` commits by supplying the target route in the path together with the `work_order_id`, the `scheduled_start_minute` at which the visit will begin, and `expected_route_plan_version`. A successful commit advances the work order `QUOTED → SCHEDULED`. Before that, a chain of guards is evaluated. The work order must be `QUOTED`, else `ERR_WORK_ORDER_BAD_STATE`. The route must be `OPEN`, else `ERR_ROUTE_NOT_OPEN`. The route's `zone_code` must equal the work order's home `zone_code`, else `ERR_ZONE_MISMATCH`. If the work order's add-ons include `UV`, the route's crew member must have `certified_for_uv` true, else `ERR_CREW_NOT_UV_CERTIFIED`. The committed window must fit inside the shift: `scheduled_start_minute` must be at least `shift_start_minute`, and `scheduled_start_minute` plus the work order's `duration_minutes` must be no greater than `shift_end_minute`, else `ERR_OUTSIDE_SHIFT`. The slot must not collide with any existing committed slot (detailed in Section 3.7), else `ERR_SLOT_OVERLAP`. Finally `expected_route_plan_version` must equal the route's current `version`, else `ERR_STALE_ROUTE_VERSION`.

On a successful commit the work order's `route_plan_id` is set to the route, its `crew_member_id` is copied from the route, and its `scheduled_start_minute` is recorded. The route's `committed_minutes` is increased by the work order's `duration_minutes`, the route's `version` is incremented, and its `updated_at` refreshed. A route is locked by a dispatcher, moving `OPEN → LOCKED`, after which no further commits are accepted because commit requires `OPEN`; a route may only be locked once its `committed_minutes` is greater than zero, so an empty route cannot be locked and the attempt fails with `ERR_ROUTE_EMPTY`. A route whose state does not permit the requested transition fails with `ERR_ROUTE_BAD_STATE`. A locked route is closed by a dispatcher, moving `LOCKED → CLOSED`, but only once every committed work order has settled: if any committed work order is still `SCHEDULED` or `IN_PROGRESS`, the close is rejected with `ERR_ROUTE_HAS_OPEN_WORK`. Locking and closing each increment the route's `version` and refresh its `updated_at`.

### 3.7. The Committed-Minutes Ledger and Slot Geometry

A route's `committed_minutes` is a derived ledger equal to the sum of `duration_minutes` over the work orders whose `route_plan_id` points at that route and whose `status` is one of `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED`. It is maintained incrementally — a commit adds the work order's duration, a cancel subtracts it — and the incremental running total must always equal a full recomputation over that filtered set. The two are reconciled so that a commit of some duration paired with its compensating cancel of the same duration leaves `committed_minutes` exactly where it began.

Slot collision is judged geometrically with half-open intervals and a symmetric buffer. The new slot occupies `[scheduled_start_minute, scheduled_start_minute + duration_minutes)`. For each existing committed work order on the route — those in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` — its slot occupies `[its scheduled_start_minute, its scheduled_start_minute + its duration_minutes)`. Each interval is expanded by a fifteen-minute buffer on both sides before testing: the new slot, expanded, runs from its start minus fifteen up to its end plus fifteen. The new (buffered) slot collides with an existing slot when the buffered new start is less than the existing end and the existing start is less than the buffered new end. A practical consequence is that two slots which merely touch with zero gap do collide once the buffer is applied; adjacent slots therefore need a gap of at least fifteen minutes between them. Any collision rejects the commit with `ERR_SLOT_OVERLAP`.

### 3.8. Performing and Completing Work

Once a route is locked, a `Technician` begins a scheduled work order, advancing it `SCHEDULED → IN_PROGRESS`. The work order must be `SCHEDULED`, else `ERR_WORK_ORDER_BAD_STATE`, and the route that the work order is committed to must be `LOCKED` before any work starts, else `ERR_ROUTE_NOT_LOCKED`.

Completion advances the work order `IN_PROGRESS → COMPLETED`. The complete request carries the after-service capture — `after_photo_count` (an integer zero or greater) and `dust_severity` (an integer 0 to 10 inclusive), both required, plus an optional `recommend_hvac_repair` flag defaulting to false — together with the `performed_service_lines` actually carried out and an optional `performed_addons` list defaulting to empty. The `performed_service_lines` array obeys the same body-shape rules as a work order's `service_lines`: it must be a non-empty array, each line's `service_type`/`system_id` pairing follows the `DUCT`/`SANITIZE`/`DRYER_VENT` rules, and each referenced `system_id` must name an `HvacSystem` on the work order's home (else `ERR_SYSTEM_NOT_FOUND`); `performed_addons` is deduplicated and drawn from `SANITIZER`, `UV`, and `COIL`. The work order must be `IN_PROGRESS`, else `ERR_WORK_ORDER_BAD_STATE`. At least one after-service photo is required: `after_photo_count` must be at least one, else `ERR_INSUFFICIENT_AFTER_PHOTOS`. On completion the system records the `AFTER` inspection row (creating it or updating it) from `after_photo_count`, `dust_severity`, and `recommend_hvac_repair`, then computes the finalized `invoice_total_cents`.

The invoice uses the very same arithmetic as the estimate in Section 3.4 — service-line subtotals, the multi-system duct discount above two systems, the add-on subtotal, the plan-member discount on the whole subtotal, and the half-up tax, each rounding step taken in the same fixed order — but with three different inputs. It is computed from the `performed_service_lines` and `performed_addons` of the complete request, not the originally requested lines; it uses the home's `active_system_count` and `has_active_plan` both read live at completion time, which may differ from the values at quote time; and it uses the *pinned* `PricingConfig` referenced by the work order's `pricing_config_id`, not whatever config is live and `ACTIVE` at completion. When the performed lines match the requested lines and the home's counts have not changed, the invoice equals the estimate; otherwise the two figures legitimately differ.

Completion drives two cascades. First, if the `AFTER` inspection's `recommend_hvac_repair` is true, the system creates an `UpsellReferral` in `PENDING` status; that referral is born from the originating work order and home and snapshots the after-inspection severity, and its creation touches the home denormalization so the home's `updated_at` is refreshed. Second, if the work order's home has a `RecurringPlan` whose `lifecycle_status` is `ACTIVE` and whose `reminder_status` is `DUE`, that plan's `reminder_status` is set to `ACKNOWLEDGED` and its `next_reminder_at` is advanced by its cadence, exactly as an explicit acknowledgement would do. Completion also refreshes the work order's own `updated_at`.

The contamination risk score is a conceptual measure scored on the `AFTER` inspection rather than on price. A base term is the after-inspection `dust_severity` multiplied by a severity weight of eight. A density term is the sum of `register_count` over the home's `ACTIVE` systems divided by the greater of one and the home's active system count, rounded half up; the density term is then multiplied by a density weight of two. The score is the base plus the weighted density, clamped to lie between zero and a ceiling of one hundred. This score is not stored on any record, is not returned by any endpoint, and does not by itself gate referral creation: the implementation never computes it as part of any request. Whether a repair referral is created is decided solely by the `AFTER` inspection's `recommend_hvac_repair` flag described above — a referral is minted exactly when that flag is true and is not minted when it is false, regardless of what the risk score would evaluate to.

A non-terminal work order can be cancelled by a `Dispatcher` from any of `DRAFT`, `INSPECTED`, `QUOTED`, or `SCHEDULED`, moving it to `CANCELLED`; a cancel from any other state fails with `ERR_WORK_ORDER_BAD_STATE`. If the work order had been committed to a route (its `route_plan_id` is set), cancellation reverses the ledger: the route's `committed_minutes` is decreased by the work order's `duration_minutes`, the route's `version` is incremented, and the work order's `route_plan_id`, `crew_member_id`, and `scheduled_start_minute` are all cleared to null. The cancel refreshes the work order's `updated_at`.

### 3.9. Recurring Plans and Reminders

A `RecurringPlan` keeps a home on a maintenance cadence. A `PlanAdmin` enrolls a home by supplying the home in the path, a `cadence_months` that must be 6, 12, or 24, and `expected_home_version` for the stale-home check. A home may hold at most one plan whose `lifecycle_status` is `ACTIVE` or `PAUSED` at a time; a second enrollment attempt is rejected with `ERR_PLAN_ALREADY_EXISTS`. On enrollment the plan starts with `lifecycle_status` `ACTIVE` and `reminder_status` `WAITING`. Its `enrolled_at` is set to the logical clock's current instant and is the anchor for reminder math; its `next_reminder_at` is set to that instant advanced by `cadence_months`. The plan records the home it covers through `home_id`. Enrollment recomputes the home's `has_active_plan` to true and increments the home's `version`.

The plan carries two parallel state dimensions that evolve independently. The reminder dimension cycles `WAITING → DUE → ACKNOWLEDGED → WAITING`. A waiting reminder becomes `DUE` when the logical clock reaches or passes `next_reminder_at`, provided the plan's `lifecycle_status` is `ACTIVE`; paused or cancelled plans never go due. This evaluation happens both automatically whenever the clock is advanced and on an explicit forced re-evaluation, which moves the reminder `WAITING → DUE` when the clock has reached `next_reminder_at` and the plan is active. A forced re-evaluation of a reminder that is already `DUE` is a no-op that leaves it `DUE` and succeeds. Forcing a reminder due while it is `WAITING` before `next_reminder_at` has been reached, or acknowledging a reminder that is not `DUE`, is rejected with `ERR_REMINDER_NOT_DUE`; attempting a reminder transition on a plan that is not `ACTIVE` is rejected with `ERR_PLAN_NOT_ACTIVE`, and on the forced re-evaluation this not-active check is evaluated before the due check.

A `PlanAdmin` acknowledges a `DUE` reminder, moving it `DUE → ACKNOWLEDGED`, which advances `next_reminder_at` and then immediately re-arms the reminder back to `WAITING` for the next cycle. The advance adds the plan's `cadence_months` to the *prior* `next_reminder_at` — not to the current clock — so the cadence never drifts across cycles; this month arithmetic clamps the day of month to the last valid day of the target month when the original day would overflow. The same `DUE → ACKNOWLEDGED` advance happens as a cascade when a work order completes on the plan's home, as described in Section 3.8.

The lifecycle dimension is `ACTIVE`, `PAUSED`, or `CANCELLED`. A `PlanAdmin` pauses an `ACTIVE` plan (`ACTIVE → PAUSED`), resumes a `PAUSED` plan (`PAUSED → ACTIVE`), or cancels a plan from either `ACTIVE` or `PAUSED` (to `CANCELLED`); a transition from a state that does not permit it is rejected with `ERR_PLAN_BAD_STATE`. Pausing, resuming, and cancelling each recompute the home's `has_active_plan` and cascade to the home — pause and cancel can drop it to false (when no other active plan remains), resume restores it to true — and each increments the plan's `version` and refreshes its `updated_at`. Cancelling additionally freezes `reminder_status` at its current value, after which no further reminder transitions occur.

### 3.10. Upsell Referrals

An `UpsellReferral` is the repair-upsell lead generated when a technician flags HVAC repair at completion. It carries the originating `work_order_id`, the referred `home_id` (denormalized for querying), and `severity_at_referral`, a snapshot of the `AFTER` inspection's `dust_severity` at referral time. A referral starts in `PENDING` and forks from there in two divergent ways. A `PlanAdmin` may decline it, moving `PENDING → DECLINED`, which records an explicit operator decision. Alternatively a referral expires, moving `PENDING → EXPIRED`, when it lapses without action: a referral may be expired only once the logical clock has reached or passed thirty days after its `created_at` — the referral lifetime is thirty days. Expiry happens automatically whenever the clock is advanced past that point, and may also be forced explicitly, in which case it is a no-op leaving the referral `PENDING` if the thirty days have not yet elapsed. Either way, a transition attempted on a referral that is not `PENDING` is rejected with `ERR_REFERRAL_BAD_STATE`, and both transitions refresh the referral's `updated_at`.

### 3.11. Callback Tickets

A `CallbackTicket` captures a post-service complaint. A `Dispatcher` or `Homeowner` files one against a completed work order by supplying the `work_order_id`, a free-text `reason`, an optional `redo_required` flag indicating whether a no-charge redo visit is needed, and an optional `reopened_from_ticket_id`. That last field is self-referential: when a new ticket reopens a prior resolved one, it points at the earlier ticket's `id`, and a value that names no existing ticket is rejected with `ERR_TICKET_NOT_FOUND`. A ticket starts in `OPEN`.

A `Dispatcher` resolves an `OPEN` or `REOPENED` ticket, moving it to `RESOLVED`, but only if the referenced work order's `status` is `COMPLETED`; otherwise the resolve is rejected with `ERR_WORK_ORDER_NOT_COMPLETED`. A resolved ticket may be reopened by a dispatcher, moving `RESOLVED → REOPENED`, and a reopened ticket may then be resolved again (`REOPENED → RESOLVED`), forming a revision loop. A transition attempted on a ticket not in the required state is rejected with `ERR_TICKET_BAD_STATE`. When several tickets bear on the same work, they are resolved in `created_at` order. Each transition refreshes the ticket's `updated_at`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and slot commits — return `200 OK`. The request body, response body, and side effects of each endpoint are described in the Section 3 narratives; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pricing-configs` | Create a DRAFT pricing config | PlanAdmin |
| GET | `/pricing-configs/{id}` | Get one pricing config | PlanAdmin, Dispatcher, Technician |
| POST | `/pricing-configs/{id}/activate` | Activate a draft config; retire the prior active one | PlanAdmin |
| POST | `/homeowners` | Register a homeowner | PlanAdmin, Dispatcher |
| POST | `/homes` | Create a home for a homeowner | PlanAdmin, Dispatcher |
| GET | `/homes` | List homes; filter by homeowner_id or zone_code | PlanAdmin, Dispatcher, Technician |
| GET | `/homes/{id}` | Get one home | PlanAdmin, Dispatcher, Technician, Homeowner |
| POST | `/homes/{id}/systems` | Add an HVAC system to a home | PlanAdmin, Dispatcher |
| GET | `/homes/{id}/systems` | List HVAC systems for a home; filter by status | PlanAdmin, Dispatcher, Technician |
| POST | `/homes/{id}/systems/{systemId}/decommission` | Decommission an HVAC system | PlanAdmin, Dispatcher |
| POST | `/homes/{id}/recurring-plans` | Enroll a home in a recurring plan | PlanAdmin |
| GET | `/homes/{id}/recurring-plans` | List recurring plans for a home; filter by lifecycle_status | PlanAdmin, Dispatcher, Homeowner |
| POST | `/recurring-plans/{id}/acknowledge` | Acknowledge a due reminder | PlanAdmin |
| POST | `/recurring-plans/{id}/refresh-reminder` | Re-evaluate a reminder against the clock | PlanAdmin, Dispatcher |
| POST | `/recurring-plans/{id}/pause` | Pause an active plan | PlanAdmin |
| POST | `/recurring-plans/{id}/resume` | Resume a paused plan | PlanAdmin |
| POST | `/recurring-plans/{id}/cancel` | Cancel a plan | PlanAdmin |
| POST | `/crew-members` | Create a crew member | Dispatcher |
| POST | `/route-plans` | Create a route plan for a crew, zone, and date | Dispatcher |
| GET | `/route-plans` | List route plans; filter by crew_member_id, zone_code, or status | PlanAdmin, Dispatcher, Technician |
| GET | `/route-plans/{id}` | Get one route plan | PlanAdmin, Dispatcher, Technician |
| POST | `/route-plans/{id}/commit` | Commit a quoted work order into a slot on this route | Dispatcher |
| POST | `/route-plans/{id}/lock` | Lock a route against further commits | Dispatcher |
| POST | `/route-plans/{id}/close` | Close a locked route | Dispatcher |
| POST | `/work-orders` | Create a draft work order for a home | Dispatcher, Technician |
| GET | `/work-orders` | List work orders; filter by home_id, route_plan_id, crew_member_id, pricing_config_id, or status | PlanAdmin, Dispatcher, Technician |
| GET | `/work-orders/{id}` | Get one work order | PlanAdmin, Dispatcher, Technician, Homeowner |
| POST | `/work-orders/{id}/inspect` | Record a before inspection (draft or re-inspect) | Technician |
| POST | `/work-orders/{id}/quote` | Quote an inspected work order | Technician |
| POST | `/work-orders/{id}/start` | Begin on-site work | Technician |
| POST | `/work-orders/{id}/complete` | Complete work, finalize invoice, run cascades | Technician |
| POST | `/work-orders/{id}/cancel` | Cancel a non-terminal work order | Dispatcher |
| GET | `/work-orders/{id}/inspections` | List inspections for a work order; filter by phase | PlanAdmin, Dispatcher, Technician, Homeowner |
| GET | `/upsell-referrals` | List upsell referrals; filter by work_order_id, home_id, or status | PlanAdmin, Dispatcher |
| GET | `/upsell-referrals/{id}` | Get one upsell referral | PlanAdmin, Dispatcher |
| POST | `/upsell-referrals/{id}/decline` | Decline a pending referral | PlanAdmin |
| POST | `/upsell-referrals/{id}/expire` | Expire a pending referral past its TTL | PlanAdmin, Dispatcher |
| POST | `/callback-tickets` | File a callback ticket against a completed work order | Dispatcher, Homeowner |
| GET | `/callback-tickets` | List callback tickets; filter by work_order_id, reopened_from_ticket_id, or status | PlanAdmin, Dispatcher |
| GET | `/callback-tickets/{id}` | Get one callback ticket | PlanAdmin, Dispatcher, Homeowner |
| POST | `/callback-tickets/{id}/resolve` | Resolve an open or reopened ticket | Dispatcher |
| POST | `/callback-tickets/{id}/reopen` | Reopen a resolved ticket | Dispatcher |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlanAdmin, Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_HOME_NOT_FOUND` | 404 Not Found |
| `ERR_HOMEOWNER_NOT_FOUND` | 404 Not Found |
| `ERR_SYSTEM_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_PRICING_CONFIG_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_WORK_ORDER_BAD_STATE` | 409 Conflict |
| `ERR_WORK_ORDER_ALREADY_SCHEDULED` | 409 Conflict |
| `ERR_SYSTEM_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_ACTIVE_PRICING_CONFIG` | 409 Conflict |
| `ERR_PRICING_CONFIG_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_INSUFFICIENT_AFTER_PHOTOS` | 422 Unprocessable Entity |
| `ERR_ROUTE_BAD_STATE` | 409 Conflict |
| `ERR_ROUTE_NOT_OPEN` | 409 Conflict |
| `ERR_ROUTE_NOT_LOCKED` | 409 Conflict |
| `ERR_ROUTE_EMPTY` | 409 Conflict |
| `ERR_ROUTE_HAS_OPEN_WORK` | 409 Conflict |
| `ERR_ZONE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_NOT_UV_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_SHIFT` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_STALE_ROUTE_VERSION` | 412 Precondition Failed |
| `ERR_PLAN_BAD_STATE` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_REMINDER_NOT_DUE` | 409 Conflict |
| `ERR_PLAN_ALREADY_EXISTS` | 409 Conflict |
| `ERR_STALE_HOME_VERSION` | 412 Precondition Failed |
| `ERR_REFERRAL_BAD_STATE` | 409 Conflict |
| `ERR_TICKET_BAD_STATE` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_COMPLETED` | 409 Conflict |
