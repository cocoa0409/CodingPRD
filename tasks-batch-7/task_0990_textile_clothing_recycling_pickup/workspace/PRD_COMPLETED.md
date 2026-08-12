# Textile Recycling Pickup API — Product Requirements Document

## 1. Introduction

The Textile Recycling Pickup API powers a municipal-scale programme that diverts post-consumer clothing and household textiles away from landfill. Residents order reusable bag or bin kits, schedule curbside pickup windows, and leave sorted textiles out for collection; separately, a network of street-side drop boxes accepts anonymous deposits that a fleet of drivers empties when fill sensors report the box is nearly full. Every kilogram collected flows through a facility where it is weighed, graded (`RESALE`, `RECYCLE`, or `FIBER`), and inspected for contamination. The graded weight is converted into a monetary diversion credit funded by corporate or philanthropic sponsors, and the proceeds are shared between the resident who diverted the material and a configurable roster of charities anchored to the service zone.

The programme operates under three compounding pressures that shape the API's design. First, the money is not unlimited: each zone's sponsor fund is a finite ledger that must be held, settled, and reconciled with penny-level invariants, and a zone may have at most one `ACTIVE` fund at any moment. Second, downstream partners — the brands and thrift chains that actually take possession of the diverted material — have finite capacity and uneven quality records, so the routing layer must apply eligibility filters, score-based ranking, and a quarantine protocol when contamination findings are upheld. Third, residents behave imperfectly: windows are rescheduled, drivers find no bags at the curb, and inspectors discover contaminants in certified loads. The API therefore models strikes, no-show rebooking, optimistic concurrency, and quarantine cascades as first-class domain concepts rather than afterthoughts.

This document specifies the platform contract that the operations team, residents, drivers, partner managers, inspectors, sponsor managers, charity administrators, and sensor gateways all integrate against. It covers the resource model, the state machines that govern each entity, the scoring and valuation formulas that turn material into money, the validation rules that guard every write, and the endpoint and error catalogues that compose the public surface.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, boilerplate, and cross-cutting invariants that apply to every endpoint of the Textile Recycling Pickup API.

### 2.1. User and Role-Based Access Control

Every call to the API is authenticated by a pair of HTTP headers. The caller must supply `X-User-ID` to identify themselves and `X-User-Role` to declare their operational capacity. If either header is missing, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A second check then evaluates whether the declared role is on the endpoint's authorized list and whether the caller's entity binding matches the resource being acted on; failure here is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes eight roles, spelled exactly as follows: `ZoneOperator`, `Resident`, `Driver`, `PartnerManager`, `Inspector`, `SponsorManager`, `CharityAdmin`, `SensorGateway`. No role is a superset of another; each owns a distinct slice of the resource graph.

Four roles are entity-backed. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident`; ownership checks compare a resource's `resident_id` foreign key (and, on pickup creation, the body's `resident_id`) to the supplied `X-User-ID`. When `X-User-Role` is `PartnerManager`, `X-User-ID` is the `id` of the acting `Partner`; an assignment's `partner_id` must equal it. When `X-User-Role` is `SponsorManager`, `X-User-ID` is the `id` of the acting `SponsorFund`. When `X-User-Role` is `CharityAdmin`, `X-User-ID` is the `id` of the acting `Charity`. Entity-backed bindings also govern reads: a `Resident` may read only their own record, their own kits and pickups, weight tickets sourced from their own pickups, and credits whose `beneficiary_resident_id` equals their id; a `PartnerManager` may read only their own partner record and may act only on assignments whose `partner_id` equals their id; a `SponsorManager` may read only their own fund, and may read a credit only while its `fund_id` is null or equals their id; a `CharityAdmin` may read only their own charity and its allocations. On list endpoints the binding either scopes the result set — ticket-scoped credit lists are filtered to the calling `SponsorManager`'s fund, and ticket-scoped assignment lists are filtered to the calling `PartnerManager` — or rejects the call outright, as noted on the endpoint. A binding that requires the target record is evaluated only when that record exists; when the record is missing the request is rejected with `ERR_NOT_FOUND` instead, while a binding decidable from the path identifier alone (for example a `Resident` id in the path) is enforced before the existence check.

The remaining four roles are opaque. When `X-User-Role` is `ZoneOperator`, `Driver`, `Inspector`, or `SensorGateway`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it (for example, a contamination report persists the filing inspector's id on its `reported_by` field, and a routed pickup persists the assigned driver's id on its `driver_id` field) but does not compare it to any entity's `id`. There is one exception on the `Driver` role: for an already-routed pickup the assigned driver's id is significant, and mark-collected or mark-no-show require `X-User-ID` to equal the pickup's stored `driver_id`; for pickups that have not yet been routed, any `Driver` may attempt the operation, and the request proceeds to the state check.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by 24 lowercase hexadecimal characters.
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

Endpoints that return collections accept two query parameters. The `limit` parameter specifies the maximum number of items to return and defaults to 10 when omitted; the minimum accepted value is 1 and the maximum accepted value is 100. The `offset` parameter specifies the number of items to skip before collecting the page and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1..100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` ascending, with ties broken by insertion order.

Paginated responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the success envelope.

### 2.4. Common Resource Properties

Most top-level resources — `ServiceZone`, `Resident`, `BagKit`, `PickupRequest`, `Partner`, `RoutingAssignment`, `DropBox`, `WeightTicket`, `DiversionCredit`, `SponsorFund`, `Charity`, `ContaminationReport`, and `ReportingPeriod` — carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` is an ISO 8601 UTC timestamp with three fractional digits set at creation. The `updated_at` is the same format and is refreshed on every mutation. The `version` is a server-managed integer that starts at 1 on creation and increments by one on every mutation; clients use it for optimistic concurrency.

`FillReading` is the deliberate exception. A fill reading is an append-only event sourced from a sensor and is never mutated after ingestion. It carries only `id` and `created_at` from the system-managed set, alongside its event payload (`dropbox_id`, `fill_pct`, `recorded_at`); `updated_at` and `version` are absent from this entity and the API never returns them on a fill-reading payload.

### 2.5. Nested Resource Retrieval and Identifier Validation

Every endpoint path that contains a resource identifier is validated left-to-right. When a path such as `/service-zones/{id}/residents` or `/weight-tickets/{id}/diversion-credits` is hit, the server first confirms that the leftmost identifier resolves to an existing resource, then proceeds rightward. A request whose leftmost identifier is unknown is rejected with `ERR_NOT_FOUND` (HTTP 404) before any deeper checks are evaluated. Identifiers referenced in the request body — for example the `zone_id` on a resident or sponsor fund, the `resident_id` on a bag kit or pickup, or each `charity_id` inside a `charity_splits` line — are subject to the same existence rule and are likewise rejected with `ERR_NOT_FOUND` when they do not resolve. Requests to an undeclared path, or to a declared path with an unsupported method, are likewise rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.6. Monetary Values, Weights, and Rounding

All monetary quantities in the system are integer cents. Whenever a division, multiplication by a non-integer rate, or percentage calculation produces a fractional cent, the value is rounded half-up to the nearest whole cent at the step where the scaffold specifies rounding, and the rounding is applied at each step rather than only at the end. Weights are decimal kilograms; reporting aggregates render weights to two decimal places. Percentages are decimal numbers compared to two decimal places.

Two enumeration tables appear repeatedly in the valuation pipeline. The per-kilogram material rate is keyed by the certified `grade`: `RESALE` is valued at 120 cents per kilogram, `RECYCLE` at 45 cents per kilogram, and `FIBER` at 20 cents per kilogram. The contamination multiplier is keyed by the highest upheld severity: `NONE` multiplies the base by 1.0, `MINOR` by 0.9, `MAJOR` by 0.5, and `SEVERE` by 0.0. A load with an upheld `SEVERE` finding is therefore worth exactly zero cents.

Two further constants shape the credit computation. A load whose certified weight is at least 20.0 kilograms earns a flat bulk bonus of 500 cents; loads below that threshold earn no bonus. On top of the post-contamination material value plus the bulk bonus, the programme offers a sponsor bonus equal to ten percent of the post-contamination material value, rounded half-up to whole cents. At credit creation the sponsor bonus is uncapped; at finalize the bonus is capped by the fund's remaining headroom after the material cost and bulk bonus are accounted for, so the bonus can shrink but the material cost and the bulk bonus themselves are never reduced by the cap.

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control. Every other endpoint does not take a version field and processes mutations without an OCC check.

A reschedule of a `PickupRequest` must carry `expected_pickup_version` equal to the pickup's current `version`. The reschedule legitimately supersedes the prior schedule, so a client holding a stale version would silently discard the newer window; the server instead rejects the request with `ERR_STALE_VERSION` (HTTP 412). A successful reschedule increments the pickup's `version` by one and refreshes `updated_at`.

A replace of a `ServiceZone`'s charity split configuration must carry `expected_zone_version` equal to the zone's current `version`. A stale submission is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful update increments the zone's `version` by one and refreshes `updated_at`. New split percentages apply only to credits settled after the call; previously settled credits retain their frozen allocations.

### 2.8. The Sponsor Fund Ledger

A `ZoneOperator` opens a `SponsorFund` for a zone by supplying the `zone_id` of the zone whose credits the fund will pay for, the `sponsor_name` of the sponsoring organization, and an `initial_cents` opening amount which must be an integer greater than zero, otherwise the create is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Every `ServiceZone` may host at most one `ACTIVE` `SponsorFund` at a time; an attempt to create a second one is rejected with `ERR_FUND_ALREADY_ACTIVE`. A fund tracks three integer-cent totals. The `funded_total_cents` is the opening `initial_cents` plus the cumulative sum of every top-up and only ever grows. The `held_cents` is the sum of `gross_cents` over credits that currently hold a sponsor-fund hold on this fund. The `paid_cents` is the sum of `gross_cents` over credits already in `SETTLED` on this fund. The `available_cents` is derived as `funded_total_cents` minus `held_cents` minus `paid_cents`, and the server maintains the invariant that at all times `held_cents` plus `paid_cents` plus `available_cents` equals `funded_total_cents` exactly.

Three operations move money through the ledger. Finalizing a credit places a hold: `held_cents` increases by the credit's `gross_cents` and `available_cents` falls by the same amount. Settling a credit converts the hold to a payment: `held_cents` decreases by `gross_cents` and `paid_cents` increases by the same amount, leaving `available_cents` unchanged. Voiding or quarantining a credit releases the hold: `held_cents` decreases by `gross_cents` and `available_cents` rises by the same amount. A top-up requires the fund to be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and its `amount_cents` must be an integer greater than zero (otherwise `ERR_INVALID_REQUEST`); a valid top-up increases `funded_total_cents` by the top-up amount and therefore also increases `available_cents` by the same amount. Finalize followed by void on the same credit is therefore net-neutral on `available_cents`.

A fund can be closed only while it is `ACTIVE` and only when no hold is outstanding — `held_cents` must equal zero, otherwise the close is rejected with `ERR_INVALID_STATE`. Closing transitions the fund to `CLOSED`, after which the zone may create a new `ACTIVE` fund.

### 2.9. Partner Quality Scores

Every partner carries two scores. The `routing_score` is an integer between zero and one hundred used operationally by the routing selector. The `report_score` is a decimal value rendered to two decimal places and used only for reporting; it is never consulted by the selector. Both scores default to 100 when the partner is registered. Reads of a partner also carry the derived `committed_kg` (the sum of `assigned_weight_kg` over its `ACCEPTED` assignments), `completed_kg` (the same over `COMPLETED` assignments), and `remaining_kg` (`capacity_kg` minus both).

The event set that drives either score is the collection of contamination reports whose `outcome` is `UPHELD` and that sit on tickets holding a `RoutingAssignment` to this partner in `ACCEPTED` or `COMPLETED` status. Each report contributes a penalty keyed by `severity`: a `SEVERE` finding subtracts 20 points, a `MAJOR` finding subtracts 15 points, and a `MINOR` finding subtracts 0 points.

The two variants differ in how they weigh older findings. The routing variant uses a rolling 30-day window: only reports whose `adjudicated_at` falls within the half-open interval starting thirty days before the current logical clock (inclusive) and ending at the current logical clock contribute; findings older than thirty days contribute zero, so a partner recovers fully once findings age out. The score is the greater of zero and one hundred minus the sum of in-window penalties. The reporting variant is decay-weighted across all time: every finding contributes forever, with its penalty halved every thirty days of age — the contribution is the penalty multiplied by one-half raised to the power of the finding's age in days divided by thirty — and the result is the greater of zero and one hundred minus that weighted sum, rounded half-up to two decimal places.

Recomputation happens on three triggers: when a contamination report is adjudicated, every time the routing selector runs, and on a read of a partner record. The first two triggers can fire the partner's status side effects; the read-only trigger recomputes the score values with the current logical clock but never changes status. A partner whose recomputed `routing_score` falls below the floor of 40 transitions from `ELIGIBLE` to `SUSPENDED`; one whose score recovers to at least 40 transitions from `SUSPENDED` back to `ELIGIBLE`. A partner in `QUARANTINED` has its `routing_score` recomputed but does not automatically leave quarantine even if the score recovers; only the remediation flow can lift quarantine.

### 2.10. The Logical Clock

The platform maintains a logical clock distinct from wall time. The server starts with the logical clock fixed at exactly `2026-05-01T00:00:00Z`, and the clock never falls back to wall-clock time thereafter. An administrative capability lets a `ZoneOperator` set the clock to any valid supplied `to_iso8601` instant — no monotonicity relative to the current value is enforced — and the call returns an object carrying `current_utc` echoing the supplied value. Window-recency checks, reporting-period windows, score windows, kit delivery timelines, and every `created_at` / `updated_at` / `certified_at` / `adjudicated_at` / `settled_at` / `closed_at` / `last_collected_at` timestamp stamped by the server all read from this logical clock.

### 2.11. Validation Ordering

When multiple validation rules apply to a single request, the server evaluates them in a fixed priority order and surfaces only the first failure. The order is: (1) authentication of the headers, (2) role authorization and entity-backed ownership, (3) request well-formedness (a non-empty body must be a JSON object; required fields present; types, enum membership, and numeric ranges valid; undeclared fields are rejected on endpoints that declare a body schema, while endpoints that declare no request fields accept and ignore any supplied body), (4) existence of path identifiers (validated left-to-right) and of body-referenced identifiers, (5) state-machine admissibility of the operation on the target entity, including resident-suspension gating (`ERR_RESIDENT_SUSPENDED`), (6) optimistic concurrency, (7) quarantine safety gating, (8) temporal-window rules, (9) the domain business rules declared in sub-order — buffered pickup window overlap, kit-count limit, reschedule cap, rebook cap, charity-split shape, single-active-fund, unique non-voided credit per ticket, no-open-reports, no pending-or-accepted assignment on the ticket, selector pool non-empty, no open provisional tickets at period close — (10) referential prerequisites such as bags-delivered or active-fund, and (11) fiscal capacity checks covering fund sufficiency, route-day capacity, and partner capacity. The declared sub-order inside (9) is load-bearing: a window conflict, for example, must surface as `ERR_PICKUP_WINDOW_CONFLICT` rather than being masked by a later check such as the reschedule cap.

## 3. Business Logic & Workflows

This section walks the lifecycle of the material and the money, from the moment a resident enrols to the moment a reporting period is closed and frozen.

### 3.1. Enrolling a Zone, Its Residents, and Its Charities

A `ZoneOperator` onboards the programme by creating a `ServiceZone` with a display `name`. At creation the zone's `charity_splits` defaults to an empty array, meaning no charitable split is configured until the operator defines one. To define a split the operator replaces the zone's `charity_splits` with an ordered list of lines, each naming a `charity_id` and an integer `pct` between 1 and 100 inclusive — a `pct` that is not an integer or falls outside that range is likewise rejected with `ERR_SPLIT_SUM_INVALID`. The same charity may not appear twice in one zone's split configuration, and the percentages across all lines must sum to no more than 100; otherwise the update is rejected with `ERR_SPLIT_SUM_INVALID` (HTTP 422). The unallocated remainder — the share of 100 percent not covered by any line — goes to the diversion credit's beneficiary resident for pickup-sourced credits, or to the charity line with the largest percentage for drop-box-sourced credits. Replacing the split is an OCC-guarded supersede as described in §2.7, and the new configuration applies only to credits settled after the change; previously settled credits keep their frozen allocations.

A charity itself is a minimal record. A `ZoneOperator` registers a `Charity` with a `name`, and the server maintains `total_received_cents` as the running sum of the charity's line amounts across every `SETTLED` `DiversionCredit` in the platform.

Residents join a specific zone. A `ZoneOperator` enrols a `Resident` by supplying the `zone_id` of the zone the resident's address belongs to, the resident's `full_name`, a contact `email`, and the street `address` used for pickups. The new resident starts in `ACTIVE` status with `strikes` at 0 and a `credit_balance_cents` of 0. The resident's `credit_balance_cents` is a computed total equal to the sum of `resident_share_cents` over that resident's `SETTLED` diversion credits and updates as those credits settle. A resident whose contamination record deteriorates — see §3.6 — can be suspended by the system; a suspended resident is blocked from ordering new bag kits, creating new pickups, or rebooking after a no-show, and any such attempt is rejected with `ERR_RESIDENT_SUSPENDED` (HTTP 403). A `ZoneOperator` can reinstate a suspended resident, which flips the status back to `ACTIVE` and resets `strikes` to 0; attempting to reactivate a resident who is not currently `SUSPENDED` is rejected with `ERR_INVALID_STATE`.

### 3.2. Bag and Bin Kits

Before leaving textiles at the curb, a resident orders a reusable kit. The resident posts a new `BagKit` under their own record, choosing a `kit_type` of either `BAG` or `BIN`. The resident must be `ACTIVE` and may have at most one other kit still in flight: the count of the resident's kits currently in `REQUESTED`, `DISPATCHED`, or `DELIVERED` must remain below two, otherwise the order is rejected with `ERR_KIT_LIMIT_EXCEEDED`. The new kit starts in `REQUESTED`.

The kit then flows through a short fulfilment chain. A `ZoneOperator` dispatches the kit, transitioning it from `REQUESTED` to `DISPATCHED`. A `Driver` confirms hand-off by marking it delivered, transitioning it from `DISPATCHED` to `DELIVERED`. Either the owning resident or a `ZoneOperator` can retire a delivered kit, moving it from `DELIVERED` to `RETIRED`; the system also auto-retires every `DELIVERED` kit belonging to a resident the moment any of their pickups is marked collected. Each step requires the kit to be in the expected prior state and is otherwise rejected with `ERR_INVALID_STATE`. `RETIRED` is terminal.

### 3.3. The Pickup Lifecycle

A resident schedules a `PickupRequest` against their own record, supplying `resident_id` (which must equal their `X-User-ID`), a `window_start` and `window_end` defining the pickup window in ISO 8601 UTC, and `bags_claimed`, the number of bags or bins they intend to leave out. The window's duration must be at least 60 minutes and at most 240 minutes; a window whose `window_end` is not after `window_start`, or whose length falls outside that range, is rejected with `ERR_INVALID_WINDOW` (HTTP 422). The `window_start` must not be earlier than the current logical clock; otherwise the create is rejected with `ERR_WINDOW_IN_PAST` (HTTP 422). The window must also not conflict with any of the resident's other pickups currently in `SCHEDULED` or `ROUTED`: a conflict exists when the new window's start is earlier than the existing window's end plus a thirty-minute buffer AND the existing window's start is earlier than the new window's end plus the same thirty-minute buffer. A gap of exactly thirty minutes between two windows is permitted and does not constitute a conflict; anything tighter is rejected with `ERR_PICKUP_WINDOW_CONFLICT`. The `bags_claimed` must be an integer at least 1; a value below 1 is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The server derives `est_weight_kg` by multiplying `bags_claimed` by 4.0 — four kilograms per bag, exact to one decimal place — and uses this estimate for route-day capacity planning.

The new pickup starts in `SCHEDULED` with `reschedule_count` and `rebook_count` both at 0, and with `driver_id` and `service_date` unset. From `SCHEDULED` the resident may reschedule, cancel, or wait for an operator to route the pickup.

A reschedule is a self-loop back to `SCHEDULED`. The resident supplies a new `window_start`, a new `window_end`, and the OCC field `expected_pickup_version` as described in §2.7. The replacement window is subjected to the same shape, recency, and buffered-overlap checks as creation; the request fails with `ERR_INVALID_WINDOW`, `ERR_WINDOW_IN_PAST`, or `ERR_PICKUP_WINDOW_CONFLICT` accordingly. The pickup's `reschedule_count` must still be below the hard cap of 3 — otherwise the reschedule is rejected with `ERR_RESCHEDULE_LIMIT_REACHED`. On success the server replaces the window, increments `reschedule_count` by one, and increments `version` by one.

A `ZoneOperator` routes a scheduled pickup by assigning a `driver_id` and a `service_date` in `YYYY-MM-DD` form, transitioning the pickup from `SCHEDULED` to `ROUTED`. Routing enforces route-day vehicle capacity: the sum of `est_weight_kg` over every pickup already in `ROUTED` for the same `driver_id` and `service_date`, plus the `est_weight_kg` of the pickup being routed, must not exceed 800.0 kilograms. A total of exactly 800.0 is permitted; anything strictly greater is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`.

Once routed, the assigned driver either collects the load or marks the resident a no-show. Marking collected requires the pickup to be in `ROUTED`, requires the caller's `X-User-ID` to equal the pickup's stored `driver_id`, and requires the resident to have at least one `BagKit` in `DELIVERED` — if no kit has been delivered the collection is rejected with `ERR_BAGS_NOT_DELIVERED`. The driver supplies a `provisional_weight_kg` reading from the field scale, which must be greater than zero; a non-positive reading is rejected with `ERR_INVALID_REQUEST` (HTTP 400). On success the pickup transitions from `ROUTED` to `COLLECTED`, a new `WeightTicket` is created with `source_type` set to `PICKUP_REQUEST`, `source_id` set to the pickup's `id`, and `status` set to `PROVISIONAL`, the ticket's `projected_credit_cents` is computed per the provisional variant described in §3.4, and every `DELIVERED` kit belonging to the resident auto-transitions to `RETIRED`; the endpoint returns `201 Created` carrying the created ticket.

A no-show is the alternative outcome. The driver marks the pickup, transitioning it from `ROUTED` to `NO_SHOW` and clearing `driver_id` and `service_date` back to null. From `NO_SHOW` the resident may rebook by supplying a fresh `window_start` and `window_end`. The rebook first requires the pickup to be in `NO_SHOW` (otherwise `ERR_INVALID_STATE`), then requires the resident to be `ACTIVE` (otherwise `ERR_RESIDENT_SUSPENDED`), then applies the same shape, recency, and buffered-overlap window checks as a reschedule, and finally requires the `rebook_count` to still be below the hard cap of 2 (otherwise `ERR_REBOOK_LIMIT_REACHED`). On success the pickup returns to `SCHEDULED` and its `rebook_count` increments by one. The `SCHEDULED → ROUTED → NO_SHOW → SCHEDULED` cycle is therefore a bounded loop, capped at two rebooks per pickup.

A resident may also cancel outright. Cancellation is permitted while the pickup is in `SCHEDULED` or `ROUTED` and is rejected with `ERR_INVALID_STATE` from any other status. Cancelling a `ROUTED` pickup also clears `driver_id` and `service_date` to null. Cancelling a `SCHEDULED` pickup leaves the (unset) driver fields untouched. The system itself cancels pickups in one circumstance: when a resident's `strikes` reach the suspension threshold, every `SCHEDULED` pickup of that resident auto-transitions to `CANCELLED`, while pickups already in `ROUTED` are left for the assigned driver to resolve through mark-collected or mark-no-show. `CANCELLED` and `SETTLED` are the terminal states of a pickup.

The pickup's later transitions are system-driven bubble-ups. When the pickup's `WeightTicket` is certified (see §3.5), the pickup moves from `COLLECTED` to `WEIGHED`. When the `DiversionCredit` on that ticket settles (see §3.7), the pickup moves from `WEIGHED` to `SETTLED` and the lifecycle closes.

### 3.4. Drop Boxes and Fill Sensors

A parallel collection channel runs unattended. A `ZoneOperator` installs a `DropBox` by supplying the `zone_id` of the hosting zone, a human-readable `label` (for example "Box-17 Maple St"), and a free-text `location`. The new box starts with `fill_pct` at 0, `posture` at `OK`, and `last_collected_at` unset.

A `SensorGateway` gateway posts a `FillReading` to the box on behalf of the physical sensor, addressing the box by its `dropbox_id` path identifier and supplying in the body the observed `fill_pct` and the sensor-side `recorded_at` timestamp. The `fill_pct` must lie between 0 and 100 inclusive; anything else is rejected as `ERR_INVALID_REQUEST`. Fill readings are append-only — each post creates a new reading and never modifies a prior one, and the entity carries no `updated_at` or `version`.

After every new reading the server recomputes the box's `fill_pct` and `posture`. The latest reading is the one with the maximum `recorded_at` for the box; ties are broken by the reading's `created_at`, preferring the later one. The box's `fill_pct` becomes that reading's `fill_pct`. The posture derives from the fill percentage using two inclusive thresholds: a fill of at least 85.0 transitions the box to `FULL_PENDING_COLLECTION`, a fill of at least 50.0 but below 85.0 places it at `FILLING`, and anything below 50.0 returns it to `OK`. The boundary at 85.0 is inclusive — exactly 85.0 flips the box to `FULL_PENDING_COLLECTION`, while 84.99 does not — and the same applies to the 50.0 boundary. Because the latest reading is chosen by sensor-side timestamp, an out-of-order reading can move the posture backward as well as forward: a newer `recorded_at` carrying a fill below 50.0 returns a `FILLING` box to `OK`, and one carrying a fill between 50.0 and 85.0 returns a `FULL_PENDING_COLLECTION` box to `FILLING`.

A box in `FULL_PENDING_COLLECTION` is eligible for collection. A driver records the collection with a `provisional_weight_kg` greater than zero, read from the truck scale; a non-positive reading is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a successful collection returns `201 Created` carrying the created ticket. The server rejects the call with `ERR_DROPBOX_NOT_FULL` if the box's posture is not `FULL_PENDING_COLLECTION`. On success the box's `fill_pct` resets to 0, its `posture` returns to `OK`, its `last_collected_at` is set to the current logical clock, and a new `WeightTicket` is created with `source_type` set to `DROPBOX`, `source_id` set to the box's `id`, `status` set to `PROVISIONAL`, and `projected_credit_cents` computed per the provisional variant described in §3.5.

### 3.5. Weighing, Certification, and the Provisional Credit Projection

Every ticket — whether sourced from a pickup or a drop box — begins life in `PROVISIONAL`. At creation the server computes `projected_credit_cents`, a forward-looking estimate that lets residents and operators see the expected value before certification. The provisional variant applies the material rate for an assumed `RECYCLE` grade to the provisional field weight: it takes `provisional_weight_kg`, multiplies by the `RECYCLE` rate of 45 cents per kilogram, and rounds half-up to whole cents to produce the base. The contamination multiplier is assumed to be `NONE`, so the post-contamination value equals the base. A bulk bonus of 500 cents is added when the provisional weight is at least 20.0 kilograms. The sponsor bonus, uncapped at this stage, is ten percent of the post-contamination value rounded half-up. The projection is the sum of the post-contamination value, the bulk bonus, and the uncapped sponsor bonus. A new ticket's `highest_upheld_severity` starts at `NONE`.

A `ZoneOperator` later certifies the ticket at the facility by supplying the `certified_weight_kg` from the facility scale — which must be greater than zero, with a non-positive weight rejected as `ERR_INVALID_REQUEST` (HTTP 400) — and the `grade`, one of `RESALE`, `RECYCLE`, or `FIBER`. The ticket must currently be `PROVISIONAL`, otherwise the call is rejected with `ERR_INVALID_STATE`. On success the ticket transitions to `CERTIFIED`, `certified_at` is stamped with the current logical clock, and — when the ticket's `source_type` is `PICKUP_REQUEST` — the source pickup bubbles up from `COLLECTED` to `WEIGHED`. A ticket whose `source_type` is `DROPBOX` has no pickup to bubble into.

From `CERTIFIED` the ticket has three possible fates. It can be the basis of a routing assignment and a diversion credit in the normal flow. It can be quarantined by an upheld `SEVERE` contamination finding — a system-driven transition covered in §3.6. Or it can be voided outright by a `ZoneOperator`. Voiding is permitted from either `CERTIFIED` or `QUARANTINED` and is rejected with `ERR_INVALID_STATE` from any other state; it is also rejected with `ERR_INVALID_STATE` if a `SETTLED` `DiversionCredit` exists on the ticket, since settled money cannot be clawed back through a void. The void cascade is described in §3.6 alongside the quarantine cascade. `VOIDED` is terminal.

### 3.6. Contamination, Adjudication, and Cascading Penalties

An `Inspector` files a `ContaminationReport` against a `CERTIFIED` ticket by supplying a `severity` of `MINOR`, `MAJOR`, or `SEVERE`, plus an optional free-text `notes` (defaulting to an empty string when omitted). The server stamps `reported_by` with the caller's `X-User-ID` and sets the new report's `status` to `OPEN` and its `outcome` to null. Two gating rules apply, with the one-open-report rule evaluated first. At most one report per ticket may be open at a time; a second concurrent `OPEN` report on the same ticket is rejected with `ERR_INVALID_REQUEST`. The report window is open only while the ticket is `CERTIFIED` and no `SETTLED` credit exists on it — filing against a `PROVISIONAL`, `QUARANTINED`, or `VOIDED` ticket, or against a ticket whose credit has already settled, is rejected with `ERR_REPORT_WINDOW_CLOSED`.

A `ZoneOperator` adjudicates an open report by supplying an `outcome` of `UPHELD` or `OVERTURNED`. The report transitions from `OPEN` to `ADJUDICATED` and `adjudicated_at` is stamped with the current logical clock. Alternatively the operator can dismiss the report, transitioning it from `OPEN` to `DISMISSED` with no penalties and leaving `adjudicated_at` null. `ADJUDICATED` and `DISMISSED` are both terminal.

An `OVERTURNED` outcome applies no penalties anywhere. An `UPHELD` outcome triggers a family of consequences. The ticket's `highest_upheld_severity` is recomputed as the maximum severity across all `UPHELD` reports on the ticket (one of `NONE`, `MINOR`, `MAJOR`, or `SEVERE`). For every partner holding an `ACCEPTED` or `COMPLETED` routing assignment on this ticket, both the `routing_score` and the `report_score` are recomputed per §2.9, and the partner transitions `ELIGIBLE → SUSPENDED` if the recomputed `routing_score` falls below 40.

Two severities carry escalated consequences. An `UPHELD` `MAJOR` or `SEVERE` report on a ticket whose `source_type` is `PICKUP_REQUEST` increments the source pickup's resident's `strikes` by one. When the incremented count reaches the strike limit of 3 — the boundary is inclusive, so exactly 3 suspends — and the resident is still `ACTIVE`, the resident transitions to `SUSPENDED`, every `SCHEDULED` pickup of that resident auto-transitions to `CANCELLED` (leaving `ROUTED` pickups for the driver to resolve), and subsequent pickup creations, bag-kit orders, and rebooks are rejected with `ERR_RESIDENT_SUSPENDED`. An `UPHELD` `SEVERE` report additionally quarantines the ticket itself, firing the cascade described next.

The ticket-quarantine cascade is one of the widest side effects in the system. When a `SEVERE` report is upheld on a `CERTIFIED` ticket, the ticket transitions from `CERTIFIED` to `QUARANTINED`. Any `DiversionCredit` on the ticket in `PROVISIONAL`, `DISPUTED`, or `FINALIZED` transitions to `VOIDED`; if the credit had `has_hold` set to true, the sponsor-fund hold is released by reducing the fund's `held_cents` by `gross_cents` and raising `available_cents` by the same amount, and `has_hold` flips to false. Any `PENDING` `RoutingAssignment` on the ticket transitions to `DECLINED` with `decline_reason` set to the literal string `SYSTEM_QUARANTINE`. Any partner holding an `ACCEPTED` or `COMPLETED` assignment on this ticket transitions to `QUARANTINED` from either `ELIGIBLE` or `SUSPENDED`. And when the ticket's `source_type` is `PICKUP_REQUEST`, the resident strike increment and possible suspension described above fire as part of the same cascade.

The same cascade shape applies when a `ZoneOperator` voids a ticket directly. Any non-settled credit on the ticket transitions to `VOIDED` with the hold release described above, and any `PENDING` assignment transitions to `DECLINED` with `decline_reason` set to `SYSTEM_QUARANTINE`. Direct voiding does not, however, escalate the partner to `QUARANTINED` and does not touch the resident.

Quarantined tickets are blocked from the normal commercial flow. Creating a routing assignment or a diversion credit on a `QUARANTINED` ticket is rejected with `ERR_TICKET_QUARANTINED`; this gate sits logically after the broader state check that admitted `QUARANTINED` as a certified-equivalent state, and it exists so that the routing and credit creation flows can distinguish a certified ticket from a quarantined one. By contrast, routing-assignment creation or credit creation against a `PROVISIONAL` or `VOIDED` ticket never reaches the quarantine gate and is instead rejected with `ERR_TICKET_NOT_CERTIFIED`.

A partner in `QUARANTINED` does not recover on its own, even if its recomputed `routing_score` rises back above the floor. A `ZoneOperator` must explicitly remediate the partner, which transitions the partner from `QUARANTINED` to `SUSPENDED`, then immediately recomputes the `routing_score`; if the recomputed score is at least 40, the partner continues in the same request from `SUSPENDED` to `ELIGIBLE`. Remediation against a partner that is not currently `QUARANTINED` is rejected with `ERR_INVALID_STATE`.

### 3.7. Routing to a Partner and the Diversion Credit Pipeline

Once a ticket is `CERTIFIED`, a `ZoneOperator` can ask the routing selector to pick a partner. Partners are registered with a `name`, a `partner_type` of `BRAND` or `THRIFT`, an `accepted_grades` list, and a total `capacity_kg` — `capacity_kg` must be an integer greater than zero and `accepted_grades` a non-empty list drawn from the three grades, with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400); the new partner starts in `ELIGIBLE` with both scores at 100. The selector first recomputes the `routing_score` of every partner and applies any resulting `ELIGIBLE ↔ SUSPENDED` transitions (per §2.9), so a partner whose findings have just aged out of the 30-day window may be reinstated, and one whose score has just dipped below the floor may be suspended. The eligible pool is then filtered to partners whose `status` is `ELIGIBLE`, whose `accepted_grades` — a non-empty subset of `RESALE`, `RECYCLE`, `FIBER` chosen at registration — contains the ticket's `grade`, whose `remaining_kg` (computed as `capacity_kg` minus `committed_kg` minus `completed_kg`) is at least the ticket's `certified_weight_kg`, and who do not already hold a `DECLINED` assignment for this ticket. Ranking is by `routing_score` descending, with ties broken by the partner's `created_at` ascending. An empty pool is rejected with `ERR_NO_ELIGIBLE_PARTNER` (HTTP 422). Otherwise the server creates a new `RoutingAssignment` in `PENDING` with `partner_id` set to the selected partner and `assigned_weight_kg` snapshotting the ticket's `certified_weight_kg` at creation.

Only one in-flight assignment may exist for a ticket. If any `PENDING` or `ACCEPTED` assignment already exists for the ticket, creating a new one is rejected with `ERR_ASSIGNMENT_PENDING_EXISTS`; a `DECLINED` or `COMPLETED` assignment does not block a new attempt. The partner declines an assignment by optionally supplying a `reason`; the assignment transitions from `PENDING` to `DECLINED` with the supplied reason persisted on `decline_reason`, and the partner is excluded from the selector pool on any subsequent routing attempt for the same ticket.

The partner accepts an assignment with no body. Acceptance requires the assignment to be `PENDING` and re-checks capacity: the partner's `committed_kg` plus the assignment's `assigned_weight_kg` must not exceed the partner's `capacity_kg`. Equality is permitted; exceeding it is rejected with `ERR_PARTNER_CAPACITY_EXCEEDED`. On success the assignment transitions to `ACCEPTED` and the partner's `committed_kg` increases by `assigned_weight_kg`. Later, when the partner confirms the material was received, the assignment transitions from `ACCEPTED` to `COMPLETED`, the partner's `committed_kg` decreases by `assigned_weight_kg`, and the partner's `completed_kg` increases by the same amount. Both `COMPLETED` and `DECLINED` are terminal.

In parallel with routing, a `ZoneOperator` issues the `DiversionCredit` for the certified ticket, addressing the ticket by its `ticket_id` path identifier. Credit creation requires the ticket to be in `CERTIFIED` or `QUARANTINED` (otherwise `ERR_TICKET_NOT_CERTIFIED`), and the quarantine safety gate described in §3.6 blocks the quarantined branch with `ERR_TICKET_QUARANTINED`. No non-`VOIDED` credit may already exist for the ticket — a duplicate attempt is rejected with `ERR_CREDIT_EXISTS`. No `OPEN` contamination report may exist on the ticket — otherwise the create is rejected with `ERR_OPEN_REPORTS_REMAIN`. The new credit starts in `PROVISIONAL`. Its `beneficiary_resident_id` is set to the source pickup's resident when the ticket is pickup-sourced, and left null for drop-box-sourced tickets. Its `applied_severity` snapshots the ticket's current `highest_upheld_severity`. Its `has_hold` is false. Its `projected_cents` is computed by the final-variant formula below but with the sponsor bonus uncapped — that is, base plus contamination adjustment plus bulk bonus plus the uncapped ten-percent sponsor bonus.

The credit's final value is fixed at finalize. The formula proceeds in five pinned steps. First, the base is the `certified_weight_kg` multiplied by the rate for the credit's `grade` (120, 45, or 20 cents per kilogram for `RESALE`, `RECYCLE`, `FIBER` respectively), rounded half-up to whole cents. Second, the post-contamination value is the base multiplied by the contamination multiplier for the ticket's `highest_upheld_severity` at the time of evaluation (1.0 for `NONE`, 0.9 for `MINOR`, 0.5 for `MAJOR`, 0.0 for `SEVERE`), again rounded half-up to whole cents. Third, the bulk bonus is 500 cents when `certified_weight_kg` is at least 20.0 kilograms, else zero. Fourth, the uncapped sponsor bonus is ten percent of the post-contamination value, rounded half-up. Fifth, the headroom available for the bonus is computed as the greater of zero and the fund's `available_cents` minus the post-contamination value minus the bulk bonus, and the final sponsor bonus is the smaller of the uncapped bonus and that headroom. The credit's `gross_cents` is the sum of the post-contamination value, the bulk bonus, and the capped sponsor bonus. The pinned order matters: the headroom depends on the post-contamination value and the bulk bonus, which is why those must be computed before the bonus is capped.

Finalize is guarded by four checks. The credit must be in `PROVISIONAL` or `DISPUTED` (any other status is rejected with `ERR_INVALID_STATE`). No `OPEN` contamination report may exist on the ticket (otherwise `ERR_OPEN_REPORTS_REMAIN`). The credit's zone must have an `ACTIVE` `SponsorFund` (otherwise `ERR_FUND_NOT_ACTIVE`). And the post-contamination value plus the bulk bonus alone — before the sponsor bonus is added — must not exceed the fund's `available_cents`, since the bonus has already been capped to absorb the slack and only the material cost and the bulk bonus are non-negotiable; otherwise the finalize is rejected with `ERR_FUND_INSUFFICIENT`. On success the credit's `status` becomes `FINALIZED`, `gross_cents` is fixed as above, `applied_severity` is re-snapshotted from the ticket's current `highest_upheld_severity`, `fund_id` is set to the zone's `ACTIVE` fund, and — only if `has_hold` was false — the fund's `held_cents` increases by `gross_cents`, `available_cents` falls by the same amount, and `has_hold` flips to true. A finalize invoked on a `DISPUTED` credit whose `has_hold` was already true retains the existing hold and places no second hold; for that re-finalize the outstanding hold counts toward the credit's own sufficiency check, i.e. the fund's `available_cents` is evaluated plus the held `gross_cents`.

A `PROVISIONAL` or `FINALIZED` credit may be disputed. The dispute is filed by the beneficiary `Resident` or by a `ZoneOperator`, carries a free-text `reason`, and transitions the credit to `DISPUTED`. The hold state is unchanged: if `has_hold` was true, the fund's `held_cents` is unchanged, and a later re-finalize from `DISPUTED` reuses the same hold rather than placing a new one.

A `FINALIZED` credit can be settled by a `ZoneOperator`. Settling requires `has_hold` to be true and the credit to be in `FINALIZED`; a settle attempt against a `PROVISIONAL` or `DISPUTED` credit is rejected with `ERR_CREDIT_NOT_FINAL`, one against a `FINALIZED` credit that holds no hold is likewise rejected with `ERR_CREDIT_NOT_FINAL`, while one against a `SETTLED` or `VOIDED` credit is rejected with `ERR_INVALID_STATE`. Settlement performs four effects. First, the fund's `held_cents` decreases by `gross_cents` and `paid_cents` increases by the same amount — the hold converts to a payment and `available_cents` is unchanged. Second, the credit's `charity_allocations` are computed and frozen per the zone's `charity_splits` at the time of settlement. Third, each charity's `total_received_cents` increases by the amount of its allocation line. Fourth, the beneficiary resident — when the credit is pickup-sourced — has their `credit_balance_cents` increased by `resident_share_cents`, and the source pickup bubbles up from `WEIGHED` to `SETTLED`. The credit's `settled_at` is stamped with the current logical clock.

The charity allocation is computed with a pinned rounding order. For each line in the zone's `charity_splits`, iterated in order of the charity's `created_at` ascending, the line's `amount_cents` is the floor of the credit's `gross_cents` multiplied by the line's `pct` divided by 100. The remainder is the `gross_cents` minus the sum of all line amounts. When the credit is pickup-sourced, that remainder is the `resident_share_cents` — the resident absorbs the rounding slack. When the credit is drop-box-sourced, `resident_share_cents` is null and the remainder is instead added to the charity line with the largest `pct`; ties between lines are broken by the charity with the earliest `created_at`. Computing the per-line floor first and assigning the remainder second is load-bearing — the opposite order (rounding the total first, then splitting) would give different cent values and is rejected.

A non-settled credit can be voided by a `ZoneOperator`, and is auto-voided when its ticket is voided or quarantined as described in §3.6. Voiding is permitted from `PROVISIONAL`, `DISPUTED`, or `FINALIZED` and rejected with `ERR_INVALID_STATE` from `SETTLED` or `VOIDED`. When `has_hold` is true, the fund's `held_cents` decreases by `gross_cents` and `available_cents` increases by the same amount; `has_hold` flips to false. A credit that was finalized and later disputed and then voided therefore unwinds cleanly.

### 3.8. Reporting Periods and Aggregate Freezing

A `ZoneOperator` opens a `ReportingPeriod` for a zone by supplying `period_start` and `period_end` in ISO 8601 UTC. The end must be strictly after the start, otherwise the create is rejected with `ERR_INVALID_WINDOW`. The new period's half-open window — beginning at `period_start` inclusive and ending at `period_end` exclusive — must not overlap any other period of the same zone. Adjacency is permitted: a prior period whose `period_end` equals the new period's `period_start` does not conflict. Any true overlap is rejected with `ERR_PERIOD_OVERLAP`. The new period starts in `OPEN` with `closed_at` unset and `aggregates` null.

An `OPEN` period can be closed by a `ZoneOperator`. Closing is rejected with `ERR_PERIOD_NOT_OPEN` when the period is not `OPEN`, and with `ERR_OPEN_TICKETS_REMAIN` when any `WeightTicket` whose source belongs to this zone is still in `PROVISIONAL` — the zone must finish certifying (or voiding) every outstanding load before the period can be reported on. A ticket's source belongs to the period's zone when, for pickup-sourced tickets, the source pickup's resident's `zone_id` equals the zone, or, for drop-box-sourced tickets, the source drop box's `zone_id` equals the zone.

On close the period's `aggregates` object is computed and frozen with seven fields, and `closed_at` is stamped with the current logical clock. The window used for every field is the half-open interval starting at `period_start` inclusive and ending at `period_end` exclusive. The `total_certified_weight_kg` is the sum of `certified_weight_kg` over zone tickets whose `certified_at` falls in the window, regardless of their later status. The `diverted_weight_kg` is the same sum restricted to tickets whose status is `CERTIFIED` at the moment of close. The `credits_settled_count` counts credits on those tickets whose `settled_at` falls in the window and whose status is `SETTLED` at close. The `credits_settled_cents` is the sum of `gross_cents` over the same set. The `charity_paid_cents` is the sum of every charity line's `amount_cents` in the `charity_allocations` of the same set. The `severe_reports_count` counts contamination reports on those tickets whose `outcome` is `UPHELD`, whose `severity` is `SEVERE`, and whose `adjudicated_at` falls in the window. The `box_collections_count` counts zone tickets whose `source_type` is `DROPBOX` and whose `created_at` falls in the window. Weights in the aggregates are rendered to two decimal places; counts and cent totals are integers. Once frozen, the aggregates never change: subsequent certifications, settlements, adjudications, or voids do not rewrite a closed period.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — a zone, a resident, a bag kit, a pickup request, a partner, a drop box, a fill reading, a sponsor fund, a charity, a contamination report, a reporting period — or that create a new subordinate resource under an existing parent (a routing assignment, a diversion credit, a weight ticket via mark-collected or box collection, a reporting period under a zone, a bag kit under a resident) return `201 Created`. Operations that modify an existing resource's state — reschedule, rebook, cancel, route, mark-no-show, dispatch, deliver, retire, certify, void, adjudicate, dismiss, finalize, dispute, settle, accept, decline, complete, top up, close, reactivate, remediate, charity-split replace, clock set — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/service-zones` | Create a service zone | ZoneOperator |
| GET | `/service-zones/{id}` | Get a service zone | ZoneOperator, Resident, Driver, PartnerManager, Inspector, SponsorManager, CharityAdmin, SensorGateway |
| PUT | `/service-zones/{id}/charity-split` | Replace the zone's charity split configuration (OCC-guarded supersede) | ZoneOperator |
| GET | `/service-zones/{id}/residents` | List residents of a zone | ZoneOperator |
| GET | `/service-zones/{id}/dropboxes` | List drop boxes of a zone | ZoneOperator, Driver, SensorGateway |
| GET | `/service-zones/{id}/sponsor-funds` | List sponsor funds of a zone | ZoneOperator, SponsorManager |
| GET | `/service-zones/{id}/reporting-periods` | List reporting periods of a zone | ZoneOperator, SponsorManager, CharityAdmin |
| POST | `/service-zones/{id}/reporting-periods` | Open a reporting period for a zone | ZoneOperator |
| POST | `/residents` | Enrol a resident | ZoneOperator |
| GET | `/residents/{id}` | Get a resident (Resident role: self only) | ZoneOperator, Resident |
| POST | `/residents/{id}/reactivate` | Reinstate a SUSPENDED resident and reset strikes | ZoneOperator |
| GET | `/residents/{id}/bag-kits` | List a resident's bag kits | ZoneOperator, Resident |
| POST | `/residents/{id}/bag-kits` | Resident orders a bag/bin kit (self only; resident must be ACTIVE; max 2 active kits) | Resident |
| GET | `/residents/{id}/pickup-requests` | List a resident's pickup requests | ZoneOperator, Resident, Driver |
| POST | `/bag-kits/{id}/dispatch` | Mark kit dispatched to the resident | ZoneOperator |
| POST | `/bag-kits/{id}/deliver` | Mark kit delivered | Driver |
| POST | `/bag-kits/{id}/retire` | Retire a delivered kit (Resident: own kit only) | Resident, ZoneOperator |
| POST | `/pickup-requests` | Schedule a pickup (window 60–240 min, future, buffered-overlap checked) | Resident |
| GET | `/pickup-requests/{id}` | Get a pickup request | ZoneOperator, Resident, Driver |
| POST | `/pickup-requests/{id}/reschedule` | Reschedule a SCHEDULED pickup (OCC-guarded; max 3 reschedules) | Resident |
| POST | `/pickup-requests/{id}/cancel` | Cancel a SCHEDULED or ROUTED pickup | Resident |
| POST | `/pickup-requests/{id}/rebook` | Rebook a NO_SHOW pickup into a new window (max 2 rebooks; resident ACTIVE) | Resident |
| POST | `/pickup-requests/{id}/route` | Assign driver and service date (route-day capacity ≤ 800 kg) | ZoneOperator |
| POST | `/pickup-requests/{id}/mark-collected` | Driver records curb-side collection; creates the PROVISIONAL WeightTicket | Driver |
| POST | `/pickup-requests/{id}/mark-no-show` | Driver marks the resident a no-show | Driver |
| GET | `/pickup-requests/{id}/weight-tickets` | List weight tickets of a pickup (0..1) | ZoneOperator, Resident, Driver, Inspector |
| POST | `/partners` | Register a brand/thrift partner | ZoneOperator |
| GET | `/partners/{id}` | Get a partner (PartnerManager: self only; scores recomputed on read; no status transitions fire on read) | ZoneOperator, PartnerManager |
| POST | `/partners/{id}/remediate` | Lift quarantine: QUARANTINED → SUSPENDED, then immediate recompute may continue to ELIGIBLE | ZoneOperator |
| GET | `/partners/{id}/routing-assignments` | List a partner's routing assignments | ZoneOperator, PartnerManager |
| POST | `/weight-tickets/{id}/routing-assignments` | Run the routing selector for a certified ticket and create a PENDING assignment | ZoneOperator |
| GET | `/weight-tickets/{id}/routing-assignments` | List routing assignments of a ticket (PartnerManager: filtered to own assignments) | ZoneOperator, PartnerManager |
| POST | `/routing-assignments/{id}/accept` | Partner accepts an assignment (capacity re-checked) | PartnerManager |
| POST | `/routing-assignments/{id}/decline` | Partner declines; partner excluded from selector retries for this ticket | PartnerManager |
| POST | `/routing-assignments/{id}/complete` | Partner confirms material received | PartnerManager |
| POST | `/dropboxes` | Install a drop box | ZoneOperator |
| GET | `/dropboxes/{id}` | Get a drop box (fill_pct and posture) | ZoneOperator, Driver, SensorGateway |
| POST | `/dropboxes/{id}/fill-readings` | Sensor gateway posts a fill reading; posture recomputed from the latest reading | SensorGateway |
| GET | `/dropboxes/{id}/fill-readings` | List fill readings of a box | ZoneOperator, SensorGateway |
| POST | `/dropboxes/{id}/collections` | Driver empties a full box; creates the PROVISIONAL WeightTicket | Driver |
| GET | `/dropboxes/{id}/weight-tickets` | List weight tickets of a drop box | ZoneOperator, Driver |
| GET | `/weight-tickets/{id}` | Get a weight ticket (Resident: only tickets sourced from own pickups) | ZoneOperator, Driver, Inspector, Resident |
| POST | `/weight-tickets/{id}/certify` | Facility certification: certified weight + grade | ZoneOperator |
| POST | `/weight-tickets/{id}/void` | Void a certified/quarantined ticket; cascades credit void + hold release + assignment decline | ZoneOperator |
| POST | `/weight-tickets/{id}/contamination-reports` | Inspector files a contamination finding on a CERTIFIED ticket (before its credit settles) | Inspector |
| GET | `/weight-tickets/{id}/contamination-reports` | List contamination reports of a ticket | ZoneOperator, Inspector |
| POST | `/contamination-reports/{id}/adjudicate` | Operator adjudicates: UPHELD applies severity penalties and cascades; OVERTURNED applies none | ZoneOperator |
| POST | `/contamination-reports/{id}/dismiss` | Dismiss an open report without penalties | ZoneOperator |
| POST | `/weight-tickets/{id}/diversion-credits` | Issue the diversion credit for a certified ticket (projected_cents computed; beneficiary from pickup source) | ZoneOperator |
| GET | `/weight-tickets/{id}/diversion-credits` | List credits of a ticket (0..1 non-voided; Resident: only own pickups' tickets; SponsorManager: filtered to own fund's credits) | ZoneOperator, Resident, SponsorManager |
| GET | `/diversion-credits/{id}` | Get a diversion credit | ZoneOperator, Resident, SponsorManager |
| POST | `/diversion-credits/{id}/finalize` | Fix gross_cents and place the sponsor-fund hold (PROVISIONAL or DISPUTED) | ZoneOperator |
| POST | `/diversion-credits/{id}/dispute` | Dispute a PROVISIONAL or FINALIZED credit (hold retained) | Resident, ZoneOperator |
| POST | `/diversion-credits/{id}/void` | Void a non-settled credit; releases any hold | ZoneOperator |
| POST | `/diversion-credits/{id}/settle` | Settle a FINALIZED credit: commit fund, split to charities, pay resident share | ZoneOperator |
| POST | `/sponsor-funds` | Open a sponsor fund for a zone (one ACTIVE fund per zone) | ZoneOperator |
| GET | `/sponsor-funds/{id}` | Get a sponsor fund (SponsorManager: own fund) | ZoneOperator, SponsorManager |
| POST | `/sponsor-funds/{id}/topups` | Sponsor tops up an ACTIVE fund (SponsorManager: own fund) | SponsorManager |
| POST | `/sponsor-funds/{id}/close` | Close a fund with no open holds | ZoneOperator |
| GET | `/sponsor-funds/{id}/diversion-credits` | List credits holding/paid from this fund (SponsorManager: own fund only) | ZoneOperator, SponsorManager |
| POST | `/charities` | Register a charity | ZoneOperator |
| GET | `/charities/{id}` | Get a charity | ZoneOperator, CharityAdmin |
| GET | `/charities/{id}/allocations` | Computed read returned as a single object with three keys: `charity_id` (the path charity), `total_received_cents` (the same running total carried on the charity record), and `allocations` — one entry per frozen allocation line that names this charity, drawn from every `SETTLED` credit platform-wide with credits iterated in `created_at` ascending; each entry carries `credit_id`, `ticket_id`, `pct`, and `amount_cents` | ZoneOperator, CharityAdmin |
| GET | `/reporting-periods/{id}` | Get a reporting period including frozen aggregates | ZoneOperator, SponsorManager, CharityAdmin |
| POST | `/reporting-periods/{id}/close` | Close the period; freeze aggregates (ops-run checkpoint) | ZoneOperator |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving endpoint); startup default is exactly 2026-05-01T00:00:00Z | ZoneOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RESIDENT_SUSPENDED` | 403 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_WINDOW_IN_PAST` | 422 |
| `ERR_PICKUP_WINDOW_CONFLICT` | 409 |
| `ERR_KIT_LIMIT_EXCEEDED` | 409 |
| `ERR_RESCHEDULE_LIMIT_REACHED` | 409 |
| `ERR_REBOOK_LIMIT_REACHED` | 409 |
| `ERR_BAGS_NOT_DELIVERED` | 409 |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 409 |
| `ERR_DROPBOX_NOT_FULL` | 409 |
| `ERR_TICKET_NOT_CERTIFIED` | 409 |
| `ERR_TICKET_QUARANTINED` | 409 |
| `ERR_CREDIT_EXISTS` | 409 |
| `ERR_OPEN_REPORTS_REMAIN` | 409 |
| `ERR_REPORT_WINDOW_CLOSED` | 409 |
| `ERR_NO_ELIGIBLE_PARTNER` | 422 |
| `ERR_PARTNER_CAPACITY_EXCEEDED` | 409 |
| `ERR_ASSIGNMENT_PENDING_EXISTS` | 409 |
| `ERR_SPLIT_SUM_INVALID` | 422 |
| `ERR_FUND_ALREADY_ACTIVE` | 409 |
| `ERR_FUND_NOT_ACTIVE` | 409 |
| `ERR_FUND_INSUFFICIENT` | 409 |
| `ERR_CREDIT_NOT_FINAL` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_PERIOD_NOT_OPEN` | 409 |
| `ERR_OPEN_TICKETS_REMAIN` | 409 |
| `ERR_INTERNAL` | 500 |
