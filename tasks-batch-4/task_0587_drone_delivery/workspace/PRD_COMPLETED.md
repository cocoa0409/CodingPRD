# Drone BVLOS Delivery API — Product Requirements Document

## 1. Introduction

Autonomous delivery beyond visual line of sight is, at bottom, an exercise in reconciling three ledgers that never fully agree: the physical one (which airframe is where, how much charge is left in which pack, which pad is free at which minute), the regulatory one (which grid cells are authorized, for which altitude, during which window, and who signed off), and the financial one (which customer's money is held, which is captured, and which must be returned when a sortie is abandoned mid-air). This document specifies the API that keeps all three in agreement.

The service operates a fleet of delivery drones out of **nests** — small launch-and-recovery sites with a fixed number of physical pads — inside geographically bounded **service areas**. A customer places an order against a service area; the platform quotes it, selects an airframe, files an airspace authorization with the LAANC authority, obtains an independent BVLOS release from a flight director, launches, drops the payload, and recovers the airframe back at the nest it came from. At every step the sortie can be aborted, the weather can turn, a restriction can be published over the route, a battery can reach the end of its cycle life, or an incident review can ground the airframe outright — and each of those events must unwind every reservation the sortie was holding, without leaking a pad slot or stranding a customer's funds.

The design goal that shapes almost every rule below is *conservation*. A nest's `reserved_pads` count must always equal the number of live sorties booked to recover there. A customer's `held_total` must always equal the sum of the totals of their in-flight orders. If a cascade abandons a flight, it must run through exactly the same unwind path an operator-initiated abort would take. Implementers should read the sections that follow with that invariant in mind: every state transition described here exists to move a conserved quantity from one bucket to another, and never to destroy or duplicate it.

## 2. Global Specifications & System-Wide Principles

### 2.1. Flight Crew Identity and Role-Based Access Control

Every request to this API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the five recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The five roles are `Customer`, `DispatchOperator`, `FlightDirector`, `MaintenanceTech`, and `PlatformAdmin`. Once authentication succeeds, the acting role is matched against the set of roles authorized for the requested operation (§4); a role outside that set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The two headers do not mean the same thing for every role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID`. Concretely, a `Customer` may only place an order whose `customer_id` equals their own `X-User-ID`, and may only cancel an order whose `customer_id` equals their own `X-User-ID`; a mismatch on either operation yields `ERR_NOT_ORDER_OWNER` (HTTP 403).

When `X-User-Role` is `DispatchOperator`, `FlightDirector`, `MaintenanceTech`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares it to an entity's `id`. It does, however, record it where the workflow demands an audit trail: the operator who files an airspace request is stamped onto the flight as `filed_by_user_id`, the director who releases it is stamped as `released_by_user_id`, and the operator who confirms a payload release is stamped onto the drop record as `confirmed_by_user_id`. The segregation-of-duties rule described in §3.5 is enforced by comparing these opaque identifiers to each other, never to an entity key.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read — like every other timestamp this service emits — from the logical clock of §2.4 rather than from wall-clock time.
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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. `offset` is the number of items to skip and defaults to 0; it may not be negative. A `limit` outside the range from 1 to 100 inclusive, or a negative `offset`, is a request-shape violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a section below states otherwise, list endpoints return their resources sorted by `created_at` in ascending order. Because the logical clock only moves when an admin moves it, many resources share the same `created_at` to the millisecond; ties are therefore broken by a hidden, strictly monotonic insertion sequence, so that records created earlier in the same clock instant sort earlier. That hidden sequence is never exposed in any payload. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of items matching the filters before pagination is applied and `has_more` indicates whether items remain beyond the current page.

### 2.4. The Logical Mission Clock

Nothing in this system consults wall-clock time. The server maintains a **logical clock** that begins at exactly `2026-05-01T00:00:00Z` when the process starts and moves only when a `PlatformAdmin` explicitly sets it, supplying the target instant as `to_iso8601`. The clock may be moved forward or backward; it never falls back to real time. Every deadline, authorization window, geofence effective period, maintenance window, pad hold and estimated recovery time in this document is evaluated against this logical clock, and the phrase "now" throughout this document means "the current value of the logical clock."

### 2.5. Resource Identity, Audit Fields and Versioning

Every persisted resource carries an `id`: a server-minted UUID with no type prefix, assigned at creation and never reused. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording the moment of creation — read from the logical clock of §2.4, so that resources created without an intervening clock move share an identical `created_at`.

Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp, likewise read from the logical clock and refreshed on every mutation of the resource — and `version`, an integer that starts at 1 on creation and increments by exactly one on every mutation. This includes mutations the client did not directly request: when a recovery debits a battery pack, the pack's `version` advances and its `updated_at` refreshes just as if the pack had been written directly, and when a grounding cascade aborts a live flight, that flight's `version` advances too.

Two entities are exceptions and are immutable after creation: `WeatherObservation` and `DeliveryDrop`. Both carry `id` and `created_at` only. Neither has an `updated_at` field nor a `version` field, and neither field should appear in their response payloads.

### 2.6. Path Resolution and Referential Integrity

Path parameters are resolved strictly left to right, and the first identifier that names nothing terminates the request with the 404 belonging to that identifier's entity. A request naming a flight that does not exist fails with `ERR_FLIGHT_NOT_FOUND` before any nested lookup is attempted. The full family of not-found codes is `ERR_SERVICE_AREA_NOT_FOUND`, `ERR_NEST_NOT_FOUND`, `ERR_DRONE_NOT_FOUND`, `ERR_BATTERY_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FLIGHT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_GEOFENCE_ZONE_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_MAINTENANCE_LOG_NOT_FOUND`, and — for the two immutable entities of §2.5, which are readable by identifier — `ERR_WEATHER_OBSERVATION_NOT_FOUND` and `ERR_DELIVERY_DROP_NOT_FOUND`, each returning HTTP 404.

The same discipline applies to foreign keys supplied in a request body. Order intake, nest registration, drone registration, battery registration, battery installation, incident filing, maintenance scheduling, geofence publication and weather publication all name other resources by identifier — `customer_id`, `service_area_id`, `home_nest_id`, `nest_id`, `drone_id`, `battery_id`, `flight_id`, `incident_id`, `authorization_id` — and every one of them must resolve to an existing record before any business rule runs. A dangling body-level foreign key yields the corresponding not-found code, not a validation error.

### 2.7. Flat-Earth Geodesy

Every distance in this system is computed with one shared planar formula, and no great-circle correction is applied anywhere. Given two coordinate pairs, take the difference of the latitudes and multiply it by 111.0 kilometres per degree of latitude to obtain the north-south leg; take the difference of the longitudes and multiply it by 85.0 kilometres per degree of longitude to obtain the east-west leg; the distance is the square root of the sum of the squares of the two legs, rounded half up to three decimal places. These two constants are normative — an implementation that substitutes a haversine formula or a different degrees-to-kilometres factor will produce numbers that do not match this specification.

This one helper is used in three places: to measure an order's `distance_km` from its service-area centroid, to measure a flight's `planned_route_km` from its launch nest, and to measure whether a geofence restriction sits close enough to a route point to block a launch.

### 2.8. Numeric Precision and Rounding Discipline

Rounding in this API is *half up* everywhere, and the number of decimal places depends on the quantity:

- Distances in kilometres — `distance_km`, `planned_route_km`, `actual_route_km`, and the internal distances of the geofence check — carry **3 decimal places**.
- Money — `delivery_fee`, `airspace_surcharge`, `order_total`, `held_total`, `billed_total` — carries **2 decimal places** and is represented in responses as a JSON number, never a string.
- Energy percentages — `required_energy_pct`, `actual_energy_pct`, `charge_pct` — and the risk and health scores `advisory_risk_score`, `blocking_risk_score` and `health_pct` carry **1 decimal place**.
- Accumulated airframe hours — `flight_hours` and `hours_since_service` — carry **2 decimal places**.
- Pad-hold arithmetic and estimated recovery times operate on whole minutes; maintenance-window comparisons operate at second resolution on ISO 8601 UTC timestamps.

Where a formula pins a specific rounding *order* — the delivery fee does, notably — that order is part of the contract and is spelled out at the point of definition. Where a formula pins a *single* rounding at the very end — both energy variants do — intermediate products must not be pre-rounded.

### 2.9. Stale-Read Protection

Two write operations in this system are guarded by optimistic concurrency control, because both act on a parent whose version can legitimately advance underneath a client that read it a moment earlier.

Dispatching an order requires `expected_order_version` in the request body. This field is not optional. It must carry the client's last observed `version` of the target order. If it does not equal the order's current `version` at the moment the request is processed, the dispatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) and nothing is mutated. The reason this guard exists is concrete: a prior dispatch of the same order creates a flight, reserves a pad and moves the order to `ASSIGNED`, all of which advance the order's `version`; a subsequent abort returns the order to `QUOTED` and advances the `version` again. A client still holding the pre-abort number would otherwise re-dispatch against a plan it has never observed.

Scheduling a maintenance window requires `expected_drone_version` in the request body. This field is likewise not optional, and must carry the client's last observed `version` of the target drone. A mismatch with the drone's current `version` is rejected with `ERR_STALE_DRONE_VERSION` (HTTP 412). The grounding cascade, a battery retirement, and every dispatch, launch and recovery hop all advance a drone's `version`, so a technician who read an airframe before one of those cascades would otherwise book a window against an airframe whose state has changed underneath them.

No other endpoint accepts a version field, and no other endpoint performs a version check. Reading an order and reading a drone are the two supported ways to obtain the current numbers these guards demand.

### 2.10. Two Conserved Quantities

Neither conserved quantity is a stored column. `reserved_pads`, `held_total` and `billed_total` — like the two risk scores and a pack's `health_pct` — are *computed fields*, derived afresh from the flight and order sets each time the owning resource is serialized, and never written down. That is precisely why no cascade can leak a pad slot or strand a funds hold: the invariants below hold by construction rather than by bookkeeping. The rules that follow describe what those derivations therefore yield.

**Money.** A customer's `held_total` is money authorized but not yet captured, and after every request it must equal — rounded half up to 2 decimal places — the sum of `order_total` across that customer's orders whose `status` is `ASSIGNED` or `IN_TRANSIT`. A customer's `billed_total` is money captured, and after every request it must equal the sum of `order_total` across that customer's orders whose `status` is `DELIVERED`. Orders in `QUOTED` or `CANCELLED` contribute to neither total. The three events that move money are dispatch (which adds the order's `order_total` to `held_total`), abort of a sortie whose order is `ASSIGNED` or `IN_TRANSIT` (which subtracts the same amount from `held_total`), and payload drop (which subtracts the amount from `held_total` and adds it to `billed_total`). A dispatch followed by its compensating abort therefore returns `held_total` to exactly its pre-dispatch value with zero drift, and leaves `billed_total` untouched.

**Pads.** A nest's `reserved_pads` is the count of physical pad slots currently held, and after every request it must equal the number of flights whose `recovery_nest_id` is that nest and whose `ops_state` is one of `PLANNED`, `LAUNCHED`, `DROPPING` or `RETURNING`. Dispatch increments it by one; recovery decrements it by one; an abort from any non-terminal `ops_state` decrements it by one. Flights in `RECOVERED` or `ABORTED` never count. The grounding cascade aborts flights through the very same edge an operator-initiated abort uses, so a cascade that abandons a live sortie must still decrement the pad ledger — a slot leaked there permanently shrinks the nest's usable capacity and eventually starves dispatch.

### 2.11. The Order of Rejection

When several checks could reject the same request, they are evaluated in a fixed order so that the returned error is deterministic. The order, from first-evaluated to last, is:

1. Authentication of the headers (`ERR_UNAUTHENTICATED`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Request shape: required fields present, types correct, enum values in range, and numeric constraints satisfied — `payload_weight_g` greater than zero, `pad_count` at least 1, `requested_alt_ft` greater than zero and at most 400, `hover_alt_ft` greater than zero and at most 400, `target_charge_pct` at least 0 and at most 100, `actual_route_km` at least zero wherever it is reported, `limit` between 1 and 100 inclusive, `offset` at least zero (`ERR_INVALID_REQUEST`, HTTP 422). "Types correct" is strict about integers: `payload_weight_g`, `max_payload_g`, `pad_count`, `cycle_count`, `requested_alt_ft`, `hover_alt_ft`, `expected_order_version` and `expected_drone_version` must arrive as JSON integers, and a fractional value in any of them is a request-shape violation; every other numeric field accepts any JSON number.
4. Existence of every path-parameter resource, left to right (the matching 404).
5. Existence of every foreign key named in the body (the matching 404).
6. Order ownership for a `Customer` actor (`ERR_NOT_ORDER_OWNER`).
7. Global uniqueness of a drone's `tail_number` (`ERR_DUPLICATE_TAIL_NUMBER`).
8. The optimistic-concurrency check of §2.9 (`ERR_STALE_ORDER_VERSION` or `ERR_STALE_DRONE_VERSION`).
9. The state precondition of the transition being attempted (the matching 409 state code).
10. Segregation of duties on a BVLOS release (`ERR_SEGREGATION_OF_DUTIES`).
11. Service-area suspension (`ERR_SERVICE_AREA_SUSPENDED`).
12. Weather flyability at launch (`ERR_WEATHER_NO_GO`).
13. Geofence intersection at launch (`ERR_GEOFENCE_VIOLATION`).
14. Drone grounding (`ERR_DRONE_GROUNDED`).
15. Drone airworthiness risk at release (`ERR_DRONE_RISK_TOO_HIGH`).
16. Airspace authorization approved (`ERR_AUTHORIZATION_NOT_APPROVED`).
17. Airspace authorization window still open (`ERR_AUTHORIZATION_WINDOW_EXPIRED`).
18. Maintenance-window conflict (`ERR_MAINTENANCE_WINDOW_CONFLICT`).
19. Order payload within the service area's limit (`ERR_PAYLOAD_EXCEEDS_LIMIT`).
20. Order distance within the service area's range (`ERR_OUT_OF_SERVICE_RANGE`).
21. Nest open and belonging to the order's area (`ERR_NEST_UNAVAILABLE`).
22. Pad capacity at the recovery nest (`ERR_NEST_PADS_FULL`).
23. Battery readiness (`ERR_BATTERY_NOT_READY`).
24. Battery charge sufficient for the flight's energy requirement (`ERR_INSUFFICIENT_BATTERY`) — the energy budget is the fiscal check of this domain and it runs last among the safety gates.
25. A non-empty candidate set from the dispatch selector (`ERR_NO_ELIGIBLE_DRONE`).

The first three checks and the two existence checks apply to every endpoint. The rest apply only where the workflows in §3 say they do; each such rule names its scope explicitly there.

## 3. Business Logic & Workflows

### 3.1. Geography: Service Areas, Nests, Restrictions and Weather

A `PlatformAdmin` lays down the geography before anything can fly. A **service area** is registered with a human-readable `name`, a centroid given as `center_lat` and `center_lon`, a `max_range_km` (the furthest one-way delivery distance the area will accept, measured from the centroid, and inclusive of the boundary), and a `max_payload_g` (the heaviest order the area will accept, likewise inclusive). Both limits must be strictly greater than zero. A newly registered area's `status` is `ACTIVE`. A `PlatformAdmin` or a `FlightDirector` may suspend an area — a regulatory stand-down — which moves `status` from `ACTIVE` to `SUSPENDED`. Suspension is unconditional and idempotent: no state precondition guards it, so suspending an area that is already `SUSPENDED` succeeds, leaves `status` at `SUSPENDED`, and still advances the area's `version`. A suspended area rejects new order intake, rejects dispatch and rejects launch, all with `ERR_SERVICE_AREA_SUSPENDED`; sorties already airborne are untouched and may complete normally.

Inside an area a `PlatformAdmin` registers **nests**. Each nest names its `service_area_id`, carries a `name`, sits at a `lat` and `lon`, and declares a `pad_count` of at least 1 — the number of physical pads available for simultaneous launch and recovery. A nest's `status` is either `OPEN` or `CLOSED` and defaults to `OPEN` when the caller does not supply it. Every nest starts life with `reserved_pads` at 0. The nest is both the launch point and the recovery point of every sortie it dispatches: a flight's `launch_nest_id` and its `recovery_nest_id` are always the same nest.

Restricted airspace is published as a **geofence zone** by a `PlatformAdmin` or a `FlightDirector`. A zone names the `service_area_id` it sits in, a `kind` of `NO_FLY`, `TFR` or `WEATHER_HOLD`, a centre given as `center_lat` and `center_lon`, a `radius_km` strictly greater than zero, and a half-open effective period bounded by `effective_from` (inclusive) and `effective_to` (exclusive). A published zone's `status` is `ACTIVE`; lifting it moves `status` to `LIFTED`, after which it no longer gates anything. Lifting, like suspension, is unconditional and idempotent — lifting an already-`LIFTED` zone succeeds and advances its `version`. Only `ACTIVE` zones whose effective period contains the current logical clock, and which belong to the same service area as the order being flown, participate in the launch check described in §3.6; `LIFTED` zones and zones of other areas are ignored entirely.

Weather arrives as a stream of **observations** published by a `PlatformAdmin` or a `DispatchOperator` against a `service_area_id`. Each observation carries an `observed_at` timestamp, a sustained `wind_kph`, a peak `gust_kph`, a horizontal `visibility_km` (all three at least zero), and a `precip` intensity of `NONE`, `LIGHT` or `HEAVY`, defaulting to `NONE`. On write, the system computes and freezes a boolean `flyable` on the observation: it is true when the sustained wind is at most 35.0 kph **and** the gust is at most 45.0 kph **and** the visibility is at least 1.5 km **and** the precipitation is either `NONE` or `LIGHT`. All three numeric boundaries are themselves flyable — a 35.0 kph wind, a 45.0 kph gust and a visibility of exactly 1.5 km all pass. `HEAVY` precipitation is never flyable regardless of the other three. Observations are immutable once written.

When any operation needs "the weather" for a service area, it consults exactly one row: the observation with the greatest `observed_at`, with ties broken by the greatest `created_at`, and any remaining tie broken by the later insertion sequence of §2.3 — the last row written wins. If the area has no observations at all, the area is treated as flyable.

### 3.2. The Fleet: Airframes, Packs, and Airworthiness Risk

A `PlatformAdmin` registers an airframe against its `home_nest_id`, giving it a `tail_number` (its registration mark, which must be globally unique across all drones — a collision is rejected with `ERR_DUPLICATE_TAIL_NUMBER`, HTTP 409), an `airframe_class` of either `LIGHT` or `HEAVY`, a `max_payload_g` strictly greater than zero, and a `cruise_speed_kmh` strictly greater than zero that will be used to estimate every recovery time it ever flies. An optional `hours_since_service` may be supplied to import an existing airframe's accumulated hours since its last completed maintenance; it defaults to 0 and may not be negative. A new drone starts with `flight_hours` — its lifetime airframe hours, which are never reset — at 0, with `status` `IDLE`, and with `installed_battery_id` null. A drone's `status` is one of `IDLE`, `RESERVED`, `IN_FLIGHT` or `GROUNDED`.

Battery packs are registered by a `PlatformAdmin` or a `MaintenanceTech` against the `nest_id` of the nest that stores and charges them, with a `serial` number, an optional `charge_pct` (state of charge in percent, defaulting to 100, and constrained to be at least 0 and at most 100) and an optional `cycle_count` (completed charge/discharge cycles, imported for existing packs, defaulting to 0 and never negative). A new pack's `state` is `CHARGING`. A pack's `state` moves through `CHARGING`, `READY`, `IN_USE`, `COOLDOWN` and finally `RETIRED`.

Every pack publishes a computed `health_pct`: one hundred, minus the pack's `cycle_count` divided by 300 and expressed as a percentage — that is, one hundred minus one hundred times the ratio of `cycle_count` to 300 — rounded half up to one decimal place, and floored at zero so that it never goes negative.

A `MaintenanceTech` or a `PlatformAdmin` drives a pack to a set-point using the ground charger, supplying `target_charge_pct` — a required number constrained, like `charge_pct` itself, to be at least 0 and at most 100, with anything outside that range rejected as a request-shape violation (`ERR_INVALID_REQUEST`, HTTP 422). This sets `charge_pct` to exactly the supplied value and moves the pack's `state` to `READY`. It is accepted only when the pack is currently `CHARGING`, `COOLDOWN` or `READY`; a pack that is `IN_USE` or `RETIRED` cannot be charged and the attempt is rejected with `ERR_BATTERY_NOT_READY` (HTTP 409). Charging a `COOLDOWN` pack back up to `READY` is the edge that closes the pack's operating cycle `READY → IN_USE → COOLDOWN → READY`, and a healthy pack goes around that loop until its cycles run out.

Bolting a pack into an airframe is likewise a `MaintenanceTech` or `PlatformAdmin` operation, naming the `battery_id` to install. It requires the drone to be `IDLE` or `GROUNDED`, and requires the named pack to be stored at the drone's home nest and to be neither `IN_USE` nor `RETIRED`; any of those conditions failing yields `ERR_BATTERY_NOT_READY`. On success the drone's `installed_battery_id` is set to the named pack, any pack that was previously installed is un-linked, both risk scores are recomputed, and the drone's `version` advances by one. The un-linking is purely a re-pointing of the drone's foreign key: no battery record is written on install, so neither the incoming pack nor the outgoing one changes `state`, `updated_at` or `version`, and the drone is the only resource mutated by the operation.

**Airworthiness risk.** Every drone publishes two risk numbers. Both are computed fields in the sense of §2.10 — never stored, but derived from the drone, its installed pack and its incidents on every read of the drone, on every dispatch-eligibility evaluation, and on every BVLOS release. Both are built from three terms.

The *service term* is 40.0 multiplied by the ratio of the drone's `hours_since_service` to a 50-hour service interval, with that ratio capped at 1.0 — so an airframe at or beyond 50 hours since its last service contributes the full 40.0 points.

The *cycle term* is 30.0 multiplied by the ratio of the installed pack's `cycle_count` to the 300-cycle retirement life, again with the ratio capped at 1.0. A drone with no pack installed — `installed_battery_id` is null — is treated as the worst case and contributes the full 30.0 points.

The *severity term* sums the points of the drone's incidents, where a `MINOR` incident is worth 5 points, a `MAJOR` incident 15 points, and a `CRITICAL` incident 30 points, and where the resulting sum is capped at 30 points no matter how many incidents contributed to it. No time window applies; the sum is over the airframe's lifetime.

The two published numbers differ only in which incidents the severity term counts. `advisory_risk_score` is the sum of the service term, the cycle term, and the severity points of incidents whose `status` is `CLOSED` — rounded half up to one decimal place. `blocking_risk_score` is the sum of the service term, the cycle term, and the severity points of incidents in **any** status — `OPEN`, `UNDER_REVIEW`, `MAINTENANCE_REQUIRED` or `CLOSED` — likewise rounded half up to one decimal place. Because the blocking bucket is a superset of the advisory bucket, the blocking score is always at least the advisory score on identical data, and the two are equal only when the airframe has no incident outside `CLOSED`.

`advisory_risk_score` gates nothing whatsoever; it exists so that fleet dashboards can show what the airframe's risk *will* settle at once its open paperwork clears. `blocking_risk_score` is the number that bites: an airframe whose `blocking_risk_score` is 70.0 or higher is removed from the dispatch candidate set entirely, and a BVLOS release attempted on a flight whose drone is at or above that same threshold is rejected with `ERR_DRONE_RISK_TOO_HIGH` (HTTP 409). A drone strictly below 70.0 is eligible.

### 3.3. Order Intake and Quoting

A `Customer` is registered by a `PlatformAdmin` with a `name`, an `email`, and a single fixed delivery point given as `dropoff_lat` and `dropoff_lon`. Every order that customer ever places goes to that point. New customers start with `held_total` and `billed_total` both at 0.

An order is placed by the `Customer` themselves or by a `DispatchOperator` acting on their behalf, naming the `customer_id`, the `service_area_id` that must serve it, a gross `payload_weight_g` in grams (strictly greater than zero), and an optional `priority` of `STANDARD`, `URGENT` or `MEDICAL`, defaulting to `STANDARD`. When the actor is a `Customer`, the named `customer_id` must equal their `X-User-ID` or the request is rejected with `ERR_NOT_ORDER_OWNER`. Intake into a `SUSPENDED` service area is rejected with `ERR_SERVICE_AREA_SUSPENDED`.

Intake runs three calculations in a pinned order, and each of them can reject the order.

**Geometry first.** The customer's current `dropoff_lat` and `dropoff_lon` are copied onto the order and frozen there — a later change to the customer's address does not retroactively move an existing order. The order's `distance_km` is then the planar distance (§2.7) from the service area's centroid to that frozen dropoff point, at three decimal places. If the payload is heavier than the area's `max_payload_g`, the order is rejected with `ERR_PAYLOAD_EXCEEDS_LIMIT` (HTTP 422); a payload exactly equal to `max_payload_g` is accepted. If `distance_km` is greater than the area's `max_range_km`, the order is rejected with `ERR_OUT_OF_SERVICE_RANGE` (HTTP 422); a distance exactly equal to `max_range_km` is accepted.

**Then the fee.** The `delivery_fee` is built from two components that are rounded *separately* before they are combined, and the order of rounding is part of the contract. The base component is selected by the order's one-way `distance_km` against inclusive upper bounds: a distance of at most 5.0 km takes a base of 4.00; a distance greater than 5.0 km but at most 12.0 km takes a base of 6.50; any greater distance takes a base of 9.00. The payload component is the payload mass expressed in kilograms — that is, `payload_weight_g` divided by one thousand — multiplied by a rate of 0.90 per kilogram. Each of those two components is rounded half up to two decimal places **on its own**, and only then are the two rounded figures added together to form a subtotal. The subtotal is then multiplied by the priority multiplier — 1.0 for `STANDARD`, 1.35 for `URGENT`, 1.60 for `MEDICAL` — and the product is rounded half up to two decimal places to give `delivery_fee`. Summing the raw components and rounding once at the end is explicitly *not* the rule and will yield different cents on some orders.

**Then the surcharge and the total.** The regulatory `airspace_surcharge` is a percentage of the delivery fee, and the percentage tier is keyed on `delivery_fee` — the pre-surcharge figure — and never on `order_total`, even though `order_total` is what the customer actually pays. A `delivery_fee` of at most 8.00 draws 5 percent; a fee greater than 8.00 but at most 15.00 draws 8 percent; a fee greater than 15.00 draws 12 percent. The `airspace_surcharge` is that percentage of `delivery_fee`, rounded half up to two decimal places. The `order_total` is `delivery_fee` plus `airspace_surcharge`, rounded half up to two decimal places. Both boundary fees — exactly 8.00 and exactly 15.00 — fall into the *lower* tier.

The order comes into existence with `status` `QUOTED` and `version` 1. An order's `status` is one of `QUOTED`, `ASSIGNED`, `IN_TRANSIT`, `DELIVERED` or `CANCELLED`, and a quoted order contributes nothing to the customer's ledgers.

A `QUOTED` order may be cancelled by its owning `Customer` or by a `DispatchOperator`, moving `QUOTED → CANCELLED` and advancing the order's `version` by one. Cancellation is only available from `QUOTED`. An order that is `ASSIGNED` or `IN_TRANSIT` has a live sortie attached to it and must be unwound at the flight level first; an order that is already `DELIVERED` or `CANCELLED` is terminal. In all four of those cases the cancellation attempt is rejected with `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409).

### 3.4. Dispatch: Choosing an Airframe and Booking a Pad

Dispatch is the busiest operation in the system. A `DispatchOperator` initiates it against a `QUOTED` order, naming the `nest_id` the sortie should fly out of and supplying `expected_order_version` (§2.9). It ends with a **flight** in existence, an airframe reserved, a pad booked and the customer's funds held.

The gates run in the priority order of §2.11, which puts the optimistic-concurrency check (step 8) ahead of the state precondition (step 9). The supplied `expected_order_version` must therefore match the order's current `version` first — otherwise `ERR_STALE_ORDER_VERSION` (HTTP 412) — and only then is the order's `status` examined: anything other than `QUOTED` is `ERR_ORDER_NOT_QUOTED` (HTTP 409). A dispatch that is both stale *and* aimed at a non-`QUOTED` order surfaces the 412, not the 409. The order's service area must be `ACTIVE` — otherwise `ERR_SERVICE_AREA_SUSPENDED`. The named nest must be `OPEN` and must belong to the order's service area — a `CLOSED` nest, or a nest sitting in a different area, is `ERR_NEST_UNAVAILABLE` (HTTP 409). Then the pad-capacity check runs, and then the airframe selector.

**The route and the flight window.** Before either of the last two gates can be evaluated, the sortie's geometry must be worked out. The `planned_route_km` is twice the planar distance from the nest's coordinates to the order's frozen dropoff point — out and back — at three decimal places. The `wind_kph_at_dispatch` is frozen at this moment from the `wind_kph` of the latest weather observation of the order's service area (latest by `observed_at`, ties broken by `created_at`); when the area has no observation at all, the frozen wind is 0. The estimated recovery time, `eta_recovery_at`, is the logical clock at dispatch, advanced by the cruise leg — the `planned_route_km` divided by the airframe's `cruise_speed_kmh`, converted from hours to minutes by multiplying by sixty, and then **rounded up to a whole number of minutes** — and then advanced by a further 3 minutes of hover allowance.

**The pad hold.** Each live sortie holds its recovery nest's pad across a closed interval: `pad_hold_start` is 5 minutes before `eta_recovery_at`, and `pad_hold_end` is 10 minutes after `eta_recovery_at`. The capacity check counts the flights already recovering at the requested nest whose `ops_state` is `PLANNED`, `LAUNCHED`, `DROPPING` or `RETURNING`, and whose own closed pad-hold interval intersects the closed candidate interval of the sortie being planned. Endpoints that merely touch **do** intersect: a hold that ends at exactly the minute another begins collides with it. If the number of such overlapping holds is greater than or equal to the nest's `pad_count`, dispatch is rejected with `ERR_NEST_PADS_FULL` (HTTP 409) — the nest tolerates at most `pad_count` minus one concurrent holds beside the newcomer. Flights that have reached `RECOVERED` or `ABORTED` are excluded from the count and free their slot immediately.

The candidate interval that this gate tests is airframe-specific, because `eta_recovery_at` depends on the winning airframe's `cruise_speed_kmh`, yet §2.11 places the pad gate (step 22) *ahead* of the eligible-drone gate (step 25). The two are reconciled as follows: the selector below is evaluated first, but its verdict is withheld. When at least one airframe survives the filter, the interval is the winner's, and a full pad ledger yields `ERR_NEST_PADS_FULL` even though a flight would otherwise have been created. When no airframe survives, the interval is still constructed — from the `eta_recovery_at` that the *longest-registered airframe based at that nest* would have flown (earliest `created_at`, ties broken by the insertion sequence of §2.3, and regardless of that airframe's own eligibility) — so that a nest whose pads are full still reports `ERR_NEST_PADS_FULL` in preference to `ERR_NO_ELIGIBLE_DRONE`. Only when the nest hosts no airframes at all is the pad gate skipped entirely, because there is no cruise speed from which to derive an interval; such a dispatch falls through to `ERR_NO_ELIGIBLE_DRONE`.

**The selector.** The airframe is chosen, never supplied by the caller. A drone is a candidate only if every one of the following holds: its `home_nest_id` is the nest named in the request (drones based at *other* nests of the same service area are not candidates); its `status` is `IDLE`; its `max_payload_g` is at least the order's `payload_weight_g`; its `installed_battery_id` is not null; that installed pack's `state` is `READY`; that pack's `charge_pct` is at least the energy the sortie would require of *that particular airframe*; its `blocking_risk_score` is strictly below 70.0; and it has no `SCHEDULED` maintenance log whose half-open window from `scheduled_start` up to but not including `scheduled_end` overlaps the half-open flight window running from the current logical clock up to but not including that airframe's own `eta_recovery_at`. The route is the same for every candidate at this nest, but `cruise_speed_kmh` differs between airframes, so both the required energy and the estimated recovery time must be evaluated per candidate.

Among the surviving candidates, the winner is the one with the greatest battery `charge_pct`. Ties on charge are broken by the smallest `hours_since_service`. Ties on both are broken by the earliest `created_at` — the longest-registered airframe wins — and, since two airframes registered without an intervening clock move share a `created_at` to the millisecond, any residual tie is broken by the earlier insertion sequence of §2.3, so the airframe registered first still wins. No random or arbitrary key participates in the ranking. If no drone survives the filter, dispatch is rejected with `ERR_NO_ELIGIBLE_DRONE` (HTTP 409); there is no queueing and no deferral.

**The energy requirement, provisional variant.** The energy a sortie will need is a non-linear function of route, payload and wind. Start from a *payload factor*: one, plus the order's payload mass in kilograms — `payload_weight_g` divided by one thousand — multiplied by 0.08. Take a *wind factor*: one, plus 0.02 for every kilometre per hour by which the frozen wind exceeds 10.0 kph, where a wind at or below 10.0 kph contributes nothing at all (the excess is clamped at zero, never negative). The *core* consumption for a given route length is that route length in kilometres, multiplied by 1.6 percent of charge per kilometre, multiplied by the payload factor, multiplied by the wind factor. The provisional figure written to the flight as `required_energy_pct` at dispatch is the core consumption of the `planned_route_km`, plus 3.0 percent of hover allowance, plus a 15.0 percent planning reserve — the whole sum rounded half up to one decimal place, with no intermediate rounding.

**What dispatch writes.** A flight is created with `ops_state` `PLANNED` and `clearance_state` `UNFILED`; its `order_id` names the order, its `drone_id` names the selector's winner, its `launch_nest_id` and `recovery_nest_id` both name the requested nest, and its `battery_id` names the pack currently installed on the winning airframe. `planned_route_km`, `wind_kph_at_dispatch`, `required_energy_pct`, `eta_recovery_at`, `pad_hold_start` and `pad_hold_end` are all computed and stored as described above; `actual_route_km`, `actual_energy_pct`, `filed_by_user_id`, `released_by_user_id` and `abort_reason` all start null. The winning drone moves `IDLE → RESERVED` and its `version` advances by one. The nest's `reserved_pads` increases by one. The customer's `held_total` increases by the order's `order_total`. The order moves `QUOTED → ASSIGNED` and its `version` advances by one. The battery is *not* touched at dispatch — it stays `READY` until the sortie actually leaves the ground.

### 3.5. The Regulatory Track: Filing and Release

A flight carries two entirely independent state dimensions on the same record. `ops_state` — `PLANNED`, `LAUNCHED`, `DROPPING`, `RETURNING`, `RECOVERED`, `ABORTED` — tracks where the airframe physically is. `clearance_state` — `UNFILED`, `FILED`, `CLEARED`, `REVOKED` — tracks the regulatory paperwork. Neither dimension advances the other. The one place they are jointly gated is launch (§3.6); the one place the physical dimension reaches back into the regulatory one is abort (§3.7).

A `DispatchOperator` files the LAANC request while the sortie is still `PLANNED` and its `clearance_state` is still `UNFILED`. The filing carries the `grid_cells` the route traverses (a list of LAANC grid-cell codes), a `requested_alt_ft` altitude ceiling in feet above ground level (strictly greater than zero and at most 400), and a half-open flight window bounded by `window_start` (inclusive) and `window_end` (exclusive). Filing creates an **airspace authorization** for the flight — `flight_id` naming the sortie, `status` `PENDING`, `auth_code` null — moves the flight's `clearance_state` `UNFILED → FILED`, stamps `filed_by_user_id` with the operator's `X-User-ID`, and advances the flight's `version`. Filing against a flight whose `ops_state` is not `PLANNED` is rejected with `ERR_FLIGHT_NOT_PLANNED` (HTTP 409); that check runs first. Only then is the regulatory dimension examined, and a flight whose `clearance_state` is anything other than `UNFILED` — an already-`FILED` sortie being re-filed, a `CLEARED` one, a `REVOKED` one — is rejected with `ERR_FLIGHT_NOT_CLEARED` (HTTP 409). A sortie therefore never carries more than one airspace authorization.

The LAANC authority itself is external and is simulated: a `PlatformAdmin` records its decision by naming the `authorization_id` and an `outcome`, which is one of the two literals `APPROVED` or `DENIED` (any other value is `ERR_INVALID_REQUEST`, HTTP 422). An approval moves the authorization `PENDING → APPROVED` and mints its `auth_code` as the literal prefix `LAANC-` followed by the authorization's own `created_at` compacted to fourteen digits in the form YYYYMMDDHHMMSS. A denial moves it `PENDING → DENIED` and leaves `auth_code` null; the flight's `clearance_state` stays `FILED`, so any later release attempt fails on the not-approved gate. Either way the authorization's `version` advances by one. A decision applied to an authorization that is not `PENDING` — one already approved, denied or revoked — is rejected with `ERR_AUTHORIZATION_NOT_PENDING` (HTTP 409).

BVLOS release is the exclusive act of a `FlightDirector`, and it is the segregation-of-duties point of this system. Release moves the flight's `clearance_state` `FILED → CLEARED` and stamps `released_by_user_id` with the director's `X-User-ID`. Four preconditions guard it, and they are checked in the order of §2.11: the flight's `clearance_state` must be `FILED` (otherwise `ERR_FLIGHT_NOT_CLEARED`, HTTP 409) and its `ops_state` must still be `PLANNED` (otherwise `ERR_FLIGHT_NOT_PLANNED`); the releasing director's `X-User-ID` must differ from the flight's `filed_by_user_id` — the same human may not both file and release, and an attempt to do so is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); the flight's drone must not be `GROUNDED` (otherwise `ERR_DRONE_GROUNDED`, HTTP 409); the drone's freshly computed `blocking_risk_score` must be strictly below 70.0 (otherwise `ERR_DRONE_RISK_TOO_HIGH`, HTTP 409); and the flight's airspace authorization must exist and be `APPROVED` (otherwise `ERR_AUTHORIZATION_NOT_APPROVED`, HTTP 409).

### 3.6. Launch: The Joint Gate

Launch is the single moment where every dimension of this system is checked at once, and it is performed by a `DispatchOperator`. It carries no request body. Ten conditions must hold, and they surface in the priority order of §2.11:

- The flight's `ops_state` must be `PLANNED` — otherwise `ERR_FLIGHT_NOT_PLANNED` (HTTP 409).
- The flight's `clearance_state` must be `CLEARED` — otherwise `ERR_FLIGHT_NOT_CLEARED` (HTTP 409). A sortie that was filed but never released cannot leave the ground.
- The order's service area must be `ACTIVE` — otherwise `ERR_SERVICE_AREA_SUSPENDED` (HTTP 409).
- The latest weather observation of the order's service area must have `flyable` true. A service area with no observations at all counts as flyable. An unflyable latest observation rejects the launch with `ERR_WEATHER_NO_GO` (HTTP 409).
- No `ACTIVE` geofence zone of the order's service area whose half-open effective period contains the current logical clock may intersect the route. The route is sampled at three points: the launch nest's coordinates, the order's dropoff point, and the midpoint between the two (the arithmetic mean of the two latitudes and the arithmetic mean of the two longitudes). A zone intersects if the planar distance from its centre to *any* of those three points is less than **or equal to** its `radius_km` — a point sitting exactly on the boundary circle is a violation, not a near miss. Any intersection rejects the launch with `ERR_GEOFENCE_VIOLATION` (HTTP 409).
- The flight's drone must not be `GROUNDED` — otherwise `ERR_DRONE_GROUNDED` (HTTP 409). `GROUNDED` is the only drone status launch inspects; no separate check demands that the airframe still be `RESERVED`, because a flight that is still `PLANNED` and `CLEARED` can only be holding an airframe that dispatch reserved for it.
- The flight's airspace authorization must be `APPROVED` — a `PENDING`, `DENIED` or `REVOKED` authorization rejects the launch with `ERR_AUTHORIZATION_NOT_APPROVED` (HTTP 409).
- The current logical clock must fall inside the authorization's half-open window: at or after `window_start`, and strictly before `window_end`. A clock at exactly `window_end` is outside the window. A launch outside the window is rejected with `ERR_AUTHORIZATION_WINDOW_EXPIRED` (HTTP 409).
- The installed pack's `state` must be `READY` — otherwise `ERR_BATTERY_NOT_READY` (HTTP 409).
- The installed pack's `charge_pct` must be at least the flight's `required_energy_pct`. A charge exactly equal to the requirement is sufficient. A charge below it rejects the launch with `ERR_INSUFFICIENT_BATTERY` (HTTP 409).

On success, four records move together. The flight goes `PLANNED → LAUNCHED` and its `version` advances. The drone goes `RESERVED → IN_FLIGHT` and its `version` advances. The pack goes `READY → IN_USE` and its `version` advances — no charge is debited yet, because the system does not know what the airframe actually flew. And the order bubbles up from `ASSIGNED → IN_TRANSIT`, its `version` advancing too. The customer's ledgers do not move at launch; the funds were held at dispatch and stay held.

### 3.7. The Sortie: Arrival, Drop, Recovery — and the Abort That Undoes It All

Once airborne, the sortie advances through three `DispatchOperator` reports.

**Arrival over the dropoff point** moves the flight `LAUNCHED → DROPPING` and advances its `version`. It carries no body. Reporting arrival on a flight that is not `LAUNCHED` is rejected with `ERR_FLIGHT_INVALID_STATE` (HTTP 409).

**The drop** confirms payload release and is the moment the money is captured. The operator supplies a `hover_alt_ft` (strictly greater than zero and at most 400) and a `photo_ref` pointing at the drop confirmation photo. Only a flight in `DROPPING` may drop; anything else is `ERR_FLIGHT_INVALID_STATE`. A **delivery drop** record is created for the flight: its `flight_id` names the sortie, its `drop_lat` and `drop_lon` are copied from the order's frozen dropoff coordinates (not from any coordinate the operator supplies), and `confirmed_by_user_id` records the operator's `X-User-ID`. The flight moves `DROPPING → RETURNING` and its `version` advances. The order bubbles up `IN_TRANSIT → DELIVERED` and its `version` advances. And the customer's ledgers settle: the order's `order_total` is subtracted from `held_total` and added to `billed_total`, so the money leaves the authorization bucket and lands in the captured bucket in one step.

**Recovery** brings the airframe home, and it is where the cascade lives. The operator reports the `actual_route_km` the sortie actually flew, at three decimal places; the field is required and may not be negative, and the reported figure is itself rounded half up to three decimal places before it is stored. Only a flight in `RETURNING` may be recovered; anything else is `ERR_FLIGHT_INVALID_STATE`.

The reported route is stored and the flight's `actual_energy_pct` is computed with the **actual** variant of the energy formula — deliberately different from the provisional one. The payload factor and the wind factor are exactly as at dispatch (the actual variant reuses the frozen `wind_kph_at_dispatch` and the order's `payload_weight_g`; it never re-reads the weather feed), and the core consumption is computed on the reported `actual_route_km` rather than the planned one. To that core, 3.0 percent of hover allowance is added — and nothing else. The 15.0 percent planning reserve is a margin that is never consumed, and it is absent from the actual variant entirely. The sum is rounded half up to one decimal place. A consequence worth internalizing: feeding an `actual_route_km` exactly equal to the `planned_route_km` still yields two different numbers, because the reserve is present in one variant and not the other.

The flight then moves `RETURNING → RECOVERED` and its `version` advances, and a four-hop cascade runs:

1. The installed pack moves `IN_USE → COOLDOWN`, its `cycle_count` increases by one, and its `charge_pct` is debited by the flight's `actual_energy_pct` — the new charge is the old charge minus the actual energy, rounded half up to one decimal place, and floored at zero so it never goes negative. Its `health_pct` is recomputed from the new cycle count and its `version` advances.
2. Because hop 1 incremented the cycle count, the pack is re-checked against its retirement life: if `cycle_count` has now reached 300 or more, the pack moves `COOLDOWN → RETIRED`.
3. Because hop 2 may have retired the pack, the drone's fate depends on it. If the pack retired, the drone's `installed_battery_id` is cleared to null and the drone moves `IN_FLIGHT → GROUNDED`. If the pack did not retire, the drone simply moves `IN_FLIGHT → IDLE` and is ready for its next sortie. Either way, the drone's `flight_hours` and its `hours_since_service` both increase by the same amount — the reported `actual_route_km` divided by the airframe's `cruise_speed_kmh`, rounded half up to two decimal places — and the drone's `version` advances.
4. Because hop 3 may have grounded the drone, a maintenance work order follows it: when and only when the drone was grounded by a pack retirement, a maintenance log is created with `work_type` `BATTERY_SWAP`, `status` `SCHEDULED`, `incident_id` null, `scheduled_start` at the current logical clock, and `scheduled_end` 60 minutes later.

Independently of all four hops, the recovery nest's `reserved_pads` decreases by one. The order is already `DELIVERED` and terminal at this point, so recovery touches neither the order nor the customer's ledgers.

**The abort** is the unwind, and it is available to a `DispatchOperator` or a `FlightDirector` on any non-terminal sortie. It optionally carries an `actual_route_km` reporting how far the airframe got; when supplied it may not be negative, and when omitted the abort proceeds with no reported route. Aborting a flight already in `RECOVERED` or `ABORTED` is rejected with `ERR_FLIGHT_TERMINAL` (HTTP 409). Regardless of the `ops_state` it starts from, abort sets the flight's `abort_reason` — the domain of that field is `OPERATOR`, `DRONE_GROUNDED` and `WEATHER`, but only two of the three are ever produced: every abort reached through the `POST /flights/{id}/abort` endpoint is stamped `OPERATOR`, whoever the caller is and whatever their motive, and the grounding cascade of §3.8 is the only writer of `DRONE_GROUNDED`. No endpoint in this API performs a weather stand-down, so `WEATHER` is never written. The abort then moves `ops_state` to `ABORTED`, advances the flight's `version`, and releases the pad: the recovery nest's `reserved_pads` decreases by one, exactly as recovery would have done.

Abort also reaches into the regulatory dimension, which is the only place it does so. A flight whose `clearance_state` is `FILED` or `CLEARED` has it moved to `REVOKED`; a flight still `UNFILED` is left alone (there is nothing to revoke). Its airspace authorization, when its `status` is `PENDING` or `APPROVED`, moves to `REVOKED` and its `version` advances; an authorization already `DENIED` or `REVOKED` is left alone.

Beyond that, what an abort does depends on how far the sortie had got:

- **From `PLANNED`.** The airframe never left the pad. Nothing was flown, so `actual_route_km` and `actual_energy_pct` are both left null even when the caller reports a route — the reported figure is simply ignored from this `ops_state`. The drone moves `RESERVED → IDLE` and its `version` advances — unless the same cascade is grounding that drone, in which case the drone ends up `GROUNDED` instead, or unless the drone is not in fact `RESERVED`, in which case its status and `version` are both left alone. The pack is untouched: it never left `READY`, so no cycle is consumed and no charge is debited. The order moves `ASSIGNED → QUOTED` and its `version` advances, and the customer's `held_total` is reduced by the order's `order_total`, compensating the dispatch hold exactly. The order is now re-dispatchable — an order may be dispatched, aborted, and dispatched again any number of times.
- **From `LAUNCHED`.** The airframe was airborne, so the pack must be debited. The flight's `actual_route_km` is set to the reported value, and to 0.0 whenever no route was reported — which covers both a human abort that omitted the optional field and every abort the system triggered on its own. The flight's `actual_energy_pct` is computed with the actual variant exactly as on recovery. The pack moves `IN_USE → COOLDOWN`, its `cycle_count` increases by one, and its `charge_pct` is debited by `actual_energy_pct`, floored at zero — and the retirement rule applies here exactly as it does on recovery: a `cycle_count` that reaches 300 retires the pack, which in turn un-links it from the drone, grounds the drone and schedules a `BATTERY_SWAP` maintenance log. Otherwise the drone moves `IN_FLIGHT → IDLE` (or straight to `GROUNDED` when the cascade is grounding it). Either way the drone's `flight_hours` and `hours_since_service` both increase by the reported route divided by `cruise_speed_kmh`, rounded half up to two decimal places, and its `version` advances. The order moves `IN_TRANSIT → QUOTED` and its `version` advances, and the customer's `held_total` is reduced by the order's `order_total`.
- **From `DROPPING`.** The payload was never released, so this case is identical to the `LAUNCHED` case in every respect: same battery debit and retirement check, same drone hour accumulation and status change, same pad release, and the same order revert `IN_TRANSIT → QUOTED` with the funds hold released.
- **From `RETURNING`.** The payload *was* released, so the money has already been captured and the order is already `DELIVERED` — a terminal state. The battery, drone and nest side effects are exactly those of the `LAUNCHED` case, but the order's `status`, the customer's `held_total` and the customer's `billed_total` are all left completely untouched. Aborting the return leg does not un-deliver a delivered order and does not refund a captured fare.

### 3.8. Incidents, the Fork, and the Grounding Cascade

An incident is filed by a `DispatchOperator`, a `MaintenanceTech` or a `FlightDirector` against a `drone_id`, optionally naming the `flight_id` of the sortie involved (null for a ground incident). It carries a `severity` of `MINOR`, `MAJOR` or `CRITICAL`, a `category` of `HARD_LANDING`, `LOST_LINK`, `PAYLOAD_RELEASE`, `AIRSPACE_DEVIATION` or `GROUND_DAMAGE`, and a free-text `narrative`. A newly filed incident's `status` is `OPEN`.

Filing has an immediate consequence: an `OPEN` incident counts toward the drone's `blocking_risk_score` from the moment it exists, so a `CRITICAL` incident can push an airframe over the 70.0 threshold and remove it from dispatch and from release the instant it is logged. It does *not* count toward `advisory_risk_score`, which continues to reflect only `CLOSED` paperwork.

A `MaintenanceTech` opens the review, moving the incident `OPEN → UNDER_REVIEW` and advancing its `version`; an incident that is not `OPEN` is rejected with `ERR_INCIDENT_NOT_OPEN` (HTTP 409). Review changes neither risk score: `UNDER_REVIEW` still counts toward the blocking score (as `OPEN` did) and still does not count toward the advisory score.

The review then forks. A `MaintenanceTech` records the `outcome`, and the two branches have deliberately disjoint effects. An incident that is not `UNDER_REVIEW` when an outcome is recorded is rejected with `ERR_INCIDENT_NOT_UNDER_REVIEW` (HTTP 409).

**Branch A — `NO_ACTION`.** The incident moves `UNDER_REVIEW → CLOSED` and its `version` advances. The drone is *not* grounded. No maintenance log is created. The one visible effect is a shift in the risk ledger: the incident's severity points now count toward `advisory_risk_score` as well, where before they did not, while `blocking_risk_score` is unchanged (they already counted there). Closing an incident with no action is therefore the operation that makes the advisory score catch up to the blocking score.

**Branch B — `MAINTENANCE_REQUIRED`.** This is the grounding cascade, and it runs in four hops:

1. The incident moves `UNDER_REVIEW → MAINTENANCE_REQUIRED` and its `version` advances.
2. Because of hop 1, the drone named on the incident is forced to `GROUNDED` from whatever state it currently occupies — `IDLE`, `RESERVED` or `IN_FLIGHT` — and its `version` advances.
3. Because of hop 2, every flight of that drone whose `ops_state` is `PLANNED`, `LAUNCHED`, `DROPPING` or `RETURNING` is force-aborted, with `abort_reason` set to `DRONE_GROUNDED` and `actual_route_km` set to 0.0.
4. Because of hop 3, each force-aborted flight unwinds through the very same abort path a human-initiated abort would take: its `clearance_state` moves to `REVOKED`, its airspace authorization moves to `REVOKED`, its recovery nest's `reserved_pads` decreases by one, its order — when the order's `status` is `ASSIGNED` or `IN_TRANSIT` — reverts to `QUOTED` with the customer's `held_total` reduced by that order's `order_total`, and its pack — when the pack was `IN_USE` — moves to `COOLDOWN` with its `cycle_count` incremented. An order already `DELIVERED` is left alone, exactly as in the `RETURNING` abort case of §3.7.

Alongside those four hops, a maintenance work order is created for the drone with `work_type` `REPAIR`, `status` `SCHEDULED`, `incident_id` pointing back at this incident, `scheduled_start` at the current logical clock, and `scheduled_end` 120 minutes later. Note the asymmetry with the battery-retirement work order of §3.7: that one is a `BATTERY_SWAP` with a 60-minute window and a null `incident_id`; this one is a `REPAIR` with a 120-minute window linked to the incident that caused it.

The cascade must not leak. A grounding that abandons a live sortie is still obliged to give back the pad slot and release the funds hold; a slot leaked here permanently shrinks the nest's usable capacity and will eventually starve dispatch with `ERR_NEST_PADS_FULL` even though the nest is physically empty.

### 3.9. Maintenance Work Orders and Returning an Airframe to Service

A `MaintenanceTech` schedules a maintenance window against a `drone_id`, declaring a `work_type` of `INSPECTION`, `REPAIR`, `BATTERY_SWAP` or `OVERHAUL`, a `scheduled_start` (inclusive) and a `scheduled_end` (exclusive), optional free-text `notes` (defaulting to the empty string), and the `expected_drone_version` required by §2.9. A newly scheduled work order has `status` `SCHEDULED`, a null `completed_at`, and — when it is booked manually rather than generated by a cascade — a null `incident_id`. Creating a maintenance log advances the drone's `version` by one.

Windows on the same airframe may not overlap, and the overlap geometry here is **half-open** and **exclusive** — deliberately different from the closed, buffered, aggregate-capacity geometry of the nest pad hold in §3.4. Only `SCHEDULED` logs of the same drone participate; `COMPLETED` logs never conflict with anything. A conflict exists when the new window's `scheduled_start` falls strictly before an existing window's `scheduled_end` **and** that existing window's `scheduled_start` falls strictly before the new window's `scheduled_end`. Because both bounds are half-open, a new window beginning at exactly the instant an existing window ends does *not* conflict — adjacency is legal — while one beginning a single second earlier does. Capacity is one: a single overlapping window is fatal, and the request is rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT` (HTTP 409).

Completing a work order is what returns a grounded airframe to service. It requires the log to be `SCHEDULED` — a log already `COMPLETED` is rejected with `ERR_MAINTENANCE_NOT_SCHEDULED` (HTTP 409) — and it requires the drone to have a pack installed whose `state` is `READY`. A drone with `installed_battery_id` null, or with a pack that is not `READY`, cannot be signed back into service and the completion is rejected with `ERR_BATTERY_NOT_READY` (HTTP 409). That gate is why a `BATTERY_SWAP` work order raised by a retirement cannot be closed until a technician has actually bolted in a fresh pack and charged it.

On success the log moves `SCHEDULED → COMPLETED`, its `completed_at` is stamped with the current logical clock, and its `version` advances. The drone's `hours_since_service` is reset to exactly 0 — which collapses the service term of its risk scores to zero — and the drone moves `GROUNDED → IDLE`, with its `version` advancing. Completion does not *require* a grounded airframe: a work order booked against a drone that is still `IDLE`, `RESERVED` or `IN_FLIGHT` may be closed out too, in which case the hour reset and the `version` bump happen exactly as described but the drone's `status` is left where it stands — only a `GROUNDED` airframe is returned to `IDLE`. Note that `flight_hours` is *not* reset; it is the airframe's lifetime total and only ever grows. Finally, when the completed log carries an `incident_id` and that incident's `status` is `MAINTENANCE_REQUIRED`, the incident bubbles up to `CLOSED` and its `version` advances — and with that closure, its severity points migrate from the blocking-only bucket into the advisory bucket as well, so both risk scores end up counting it.

### 3.10. Reading the System Back

Every entity in this system is reachable both by its own identifier and through a filtered, paginated list. Nests are listable by `service_area_id` and `status`. Drones are listable by `home_nest_id`, `installed_battery_id` and `status`, and a single drone read always returns both risk scores freshly computed together with its current `version` — which is exactly where a technician obtains the number that §2.9 demands. Batteries are listable by `nest_id` and `state`. Orders are listable by `customer_id`, `service_area_id` and `status`, and a single order read returns the `version` a dispatch needs. Flights are listable by `order_id`, `drone_id`, `launch_nest_id`, `recovery_nest_id`, `battery_id` and `ops_state`, and a single flight read exposes both state dimensions and both energy figures side by side. Airspace authorizations are listable by `flight_id` and `status`; geofence zones by `service_area_id` and `status`; weather observations by `service_area_id`; incidents by `drone_id`, `flight_id` and `status`; maintenance logs by `drone_id`, `incident_id` and `status`. The drop confirmations of a flight are listable too — there will be either zero or one. All of these accept `limit` and `offset` and obey §2.3.

## 4. Endpoint Definitions

Operations that bring a brand-new resource into existence — a service area, a nest, a drone, a battery, a customer, an order, a flight (created by dispatch), an airspace authorization (created by filing), a delivery drop (created by the payload release), an incident, or a maintenance log — return `201 Created`. Every other mutating operation, including all state transitions on resources that already exist, returns `200 OK`. All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |
| POST | `/_laanc/decision` | Simulate the LAANC authority's decision on a pending authorization | PlatformAdmin |
| POST | `/service-areas` | Register a service area | PlatformAdmin |
| GET | `/service-areas/{id}` | Read one service area | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech, Customer |
| POST | `/service-areas/{id}/suspend` | Suspend a service area | PlatformAdmin, FlightDirector |
| POST | `/nests` | Register a launch/recovery nest | PlatformAdmin |
| GET | `/nests` | List nests | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| GET | `/nests/{id}` | Read one nest with its live pad ledger | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| POST | `/drones` | Register an airframe at a nest | PlatformAdmin |
| GET | `/drones` | List drones | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| GET | `/drones/{id}` | Read one airframe with both risk scores | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| POST | `/drones/{id}/install-battery` | Bolt a pack into an airframe | MaintenanceTech, PlatformAdmin |
| POST | `/batteries` | Register a battery pack at a nest | PlatformAdmin, MaintenanceTech |
| GET | `/batteries` | List battery packs | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| GET | `/batteries/{id}` | Read one battery pack | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| POST | `/batteries/{id}/charge` | Drive a pack to a charge set-point and mark it ready | MaintenanceTech, PlatformAdmin |
| POST | `/customers` | Register a customer with a fixed dropoff point | PlatformAdmin |
| GET | `/customers/{id}` | Read one customer including both ledgers | PlatformAdmin, DispatchOperator, FlightDirector, Customer |
| POST | `/orders` | Intake and quote an order | Customer, DispatchOperator |
| GET | `/orders` | List orders | PlatformAdmin, DispatchOperator, FlightDirector, Customer |
| GET | `/orders/{id}` | Read one order including its version | PlatformAdmin, DispatchOperator, FlightDirector, Customer |
| POST | `/orders/{id}/dispatch` | Select an airframe, create the flight, hold funds and reserve a pad | DispatchOperator |
| POST | `/orders/{id}/cancel` | Cancel a quoted order | Customer, DispatchOperator |
| GET | `/flights` | List flights | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| GET | `/flights/{id}` | Read one flight with both state dimensions | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| POST | `/flights/{id}/file-authorization` | File the LAANC request for a sortie | DispatchOperator |
| POST | `/flights/{id}/release` | BVLOS release of a filed sortie | FlightDirector |
| POST | `/flights/{id}/launch` | Launch the sortie | DispatchOperator |
| POST | `/flights/{id}/arrive` | Report arrival over the dropoff point | DispatchOperator |
| POST | `/flights/{id}/drop` | Confirm payload release and capture the held funds | DispatchOperator |
| POST | `/flights/{id}/recover` | Recover the airframe and debit the pack | DispatchOperator |
| POST | `/flights/{id}/abort` | Abort a non-terminal sortie and unwind its reservations | DispatchOperator, FlightDirector |
| GET | `/flights/{id}/delivery-drops` | List the drop confirmations of a flight | PlatformAdmin, DispatchOperator, FlightDirector, Customer |
| GET | `/delivery-drops/{id}` | Read one delivery drop confirmation | PlatformAdmin, DispatchOperator, FlightDirector, Customer |
| GET | `/airspace-authorizations` | List airspace authorizations | PlatformAdmin, DispatchOperator, FlightDirector |
| GET | `/airspace-authorizations/{id}` | Read one airspace authorization | PlatformAdmin, DispatchOperator, FlightDirector |
| POST | `/geofence-zones` | Publish a no-fly / TFR / weather-hold restriction | PlatformAdmin, FlightDirector |
| GET | `/geofence-zones` | List restrictions | PlatformAdmin, DispatchOperator, FlightDirector |
| GET | `/geofence-zones/{id}` | Read one geofence zone | PlatformAdmin, DispatchOperator, FlightDirector |
| POST | `/geofence-zones/{id}/lift` | Lift a restriction | PlatformAdmin, FlightDirector |
| POST | `/weather-observations` | Publish a weather observation | PlatformAdmin, DispatchOperator |
| GET | `/weather-observations` | List observations | PlatformAdmin, DispatchOperator, FlightDirector |
| GET | `/weather-observations/{id}` | Read one observation with its flyable flag | PlatformAdmin, DispatchOperator, FlightDirector |
| POST | `/incidents` | File an incident against an airframe | DispatchOperator, MaintenanceTech, FlightDirector |
| GET | `/incidents` | List incidents | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| GET | `/incidents/{id}` | Read one incident | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| POST | `/incidents/{id}/review` | Open the review of an incident | MaintenanceTech |
| POST | `/incidents/{id}/outcome` | Record the review outcome, forking the incident | MaintenanceTech |
| POST | `/maintenance-logs` | Schedule a maintenance window on an airframe | MaintenanceTech |
| GET | `/maintenance-logs` | List maintenance logs | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| GET | `/maintenance-logs/{id}` | Read one maintenance work order | PlatformAdmin, DispatchOperator, FlightDirector, MaintenanceTech |
| POST | `/maintenance-logs/{id}/complete` | Close out the work order and return the airframe to service | MaintenanceTech |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_ORDER_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_PAYLOAD_EXCEEDS_LIMIT` | 422 Unprocessable Entity |
| `ERR_OUT_OF_SERVICE_RANGE` | 422 Unprocessable Entity |
| `ERR_SERVICE_AREA_NOT_FOUND` | 404 Not Found |
| `ERR_NEST_NOT_FOUND` | 404 Not Found |
| `ERR_DRONE_NOT_FOUND` | 404 Not Found |
| `ERR_BATTERY_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_FLIGHT_NOT_FOUND` | 404 Not Found |
| `ERR_AUTHORIZATION_NOT_FOUND` | 404 Not Found |
| `ERR_GEOFENCE_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_MAINTENANCE_LOG_NOT_FOUND` | 404 Not Found |
| `ERR_WEATHER_OBSERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_DELIVERY_DROP_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_DRONE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_TAIL_NUMBER` | 409 Conflict |
| `ERR_ORDER_NOT_QUOTED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_FLIGHT_NOT_PLANNED` | 409 Conflict |
| `ERR_FLIGHT_INVALID_STATE` | 409 Conflict |
| `ERR_FLIGHT_TERMINAL` | 409 Conflict |
| `ERR_FLIGHT_NOT_CLEARED` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_PENDING` | 409 Conflict |
| `ERR_AUTHORIZATION_NOT_APPROVED` | 409 Conflict |
| `ERR_AUTHORIZATION_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_INCIDENT_NOT_OPEN` | 409 Conflict |
| `ERR_INCIDENT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_MAINTENANCE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_MAINTENANCE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SERVICE_AREA_SUSPENDED` | 409 Conflict |
| `ERR_WEATHER_NO_GO` | 409 Conflict |
| `ERR_GEOFENCE_VIOLATION` | 409 Conflict |
| `ERR_DRONE_GROUNDED` | 409 Conflict |
| `ERR_DRONE_RISK_TOO_HIGH` | 409 Conflict |
| `ERR_NEST_UNAVAILABLE` | 409 Conflict |
| `ERR_NEST_PADS_FULL` | 409 Conflict |
| `ERR_BATTERY_NOT_READY` | 409 Conflict |
| `ERR_INSUFFICIENT_BATTERY` | 409 Conflict |
| `ERR_NO_ELIGIBLE_DRONE` | 409 Conflict |
