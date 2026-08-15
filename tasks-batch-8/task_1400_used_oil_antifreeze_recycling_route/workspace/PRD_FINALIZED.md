# Used-Oil & Antifreeze Recycling Route API — Product Requirements Document

## 1. Introduction

Industrial generators — quick-lube shops, fleet maintenance yards, agricultural cooperatives — accumulate used crankcase oil and spent antifreeze in on-site tanks, and a scheduled-route collector must pump that material out, pay or charge the generator according to a volatile commodity market, and haul it to a licensed disposal facility under a federally regulated chain of custody. This document specifies the Used-Oil & Antifreeze Recycling Route API: a route-operations platform in the style of a Safety-Kleen collection service, covering customer tank levels and pickup scheduling, sample screening with halogen rejection, volume metering with market-priced settlement, tank ownership and installation, the manifest and bill-of-lading record, blending and product resale, spill response with environmental liability, and route-density minimum-pickup economics.

The API is organized around two hierarchies and three cross-cutting records. A `Customer` owns `TankSite` locations, each of which hosts one or more `Tank` units; a `Route` owned by a planner sequences `RouteStop` visits, each of which produces a `SampleScreening` and, when the material passes, a `PickupTicket`. Cutting across those trees, a `Manifest` ties a route to a `DisposalFacility` under regulatory tracking, a `BlendBatch` consumes settled tickets as resale feedstock, and a `SpillIncident` binds a site, a route, and a reporting user into an environmental-liability workflow. Seven segregated roles cooperate across these workflows, all mutations commit atomically within a single request, and the two write paths most exposed to concurrent editing — adding a stop to a route and settling a ticket against a customer balance — are guarded by optimistic concurrency. All endpoints are mounted under `/recycle-routes`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, resource metadata, validation ordering, concurrency control, numeric precision, derived-state reconciliation, and the logical clock.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly seven roles:

- `RoutePlanner` — owns the customer lifecycle, tank-site activation, driver registration, route planning, manifest drafting and submission, and blend-batch planning.
- `Driver` — executes the route: arrives at stops, begins screening, records metered pickups, logs spills, and drives manifests to the facility.
- `LabTech` — records sample screenings and controls blend-batch quality holds and releases. Deliberately segregated from `Driver`: the person pumping never grades the sample.
- `SettlementClerk` — settles, disputes, and adjusts pickup tickets, manages customer balance top-ups, and marks released batches sold. Segregated from `RoutePlanner` on settlement.
- `EHSOfficer` — Environmental Health & Safety: owns the spill lifecycle after logging, clears tank quarantine, and certifies contaminated sites clean.
- `Regulator` — the state or federal authority: registers disposal facilities, closes manifests, approves or rejects amendments, and publishes commodity market prices.
- `TankInstaller` — creates tanks and performs installation, registration of pre-existing customer tanks, and decommissioning.

Role identity semantics differ by role. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver` entity; ownership checks on any resource that references a driver — most notably a route's `driver_id` — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `RoutePlanner`, `LabTech`, `SettlementClerk`, `EHSOfficer`, `Regulator`, or `TankInstaller`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `screened_by_user_id` on a `SampleScreening` or as `reported_by_user_id` on a `SpillIncident`) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp is an ISO 8601 UTC value with three fractional digits recorded at creation, and `updated_at` is the same format, refreshed on every mutation. The `version` is an integer that increments on every mutation of the resource, including mutations driven by derived-field reconciliation and cross-entity cascades; adding a stop to a route, for example, increments the route's `version`.

One entity deviates from this convention: a `MarketPrice` row is an immutable price publication and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from `MarketPrice` responses.

### 2.5. Nested Resource Retrieval and Request Well-Formedness

Endpoints whose paths contain multiple resource identifiers validate those identifiers strictly left to right. The request is rejected immediately with the 404 error corresponding to the first path identifier that does not resolve to an existing resource; later segments are never examined once an earlier segment fails. The per-resource not-found identifiers are: `ERR_CUSTOMER_NOT_FOUND`, `ERR_TANK_SITE_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_ROUTE_STOP_NOT_FOUND`, `ERR_SAMPLE_SCREENING_NOT_FOUND`, `ERR_PICKUP_TICKET_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_BLEND_BATCH_NOT_FOUND`, and `ERR_SPILL_NOT_FOUND` (all HTTP 404).

Foreign-key references carried in a request body — for example the site and tank named when a stop is added, the facility named when a manifest is drafted, or the ticket list named when a blend batch is planned — must likewise resolve to existing resources, and an unresolvable reference is rejected with the referenced resource's not-found error from the same catalog.

Independently of existence, a malformed request body or a missing required field is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a value supplied for an enum-typed field that is not a member of the field's declared set is rejected with `ERR_INVALID_ENUM` (HTTP 400).

### 2.6. Validation Priority Order

When several rules could reject the same request, checks are evaluated in a fixed order, and the first failure short-circuits the remainder. The order is:

1. Header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization against the RBAC matrix (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Existence of every path parameter, validated left to right (the 404 family).
4. Existence of foreign-key references in the request body (the same 404 family).
5. State preconditions of the requested transition (the `ERR_*_NOT_*` family, HTTP 409).
6. Optimistic concurrency, where the endpoint declares a version field (`ERR_STALE_VERSION`, HTTP 412).
7. Business rules, in this relative order: safety rules first (quarantine and site-contamination gates on arrival and screening, the hazmat gate on dispatch, and screening-result consistency), then structural constraints (stop window and sequence, metered volume against tank level, vehicle capacity, zero-volume rejection), then referential gates (facility status, capacity, and stream acceptance on manifest submission; blend-input eligibility), then fiscal gates (prepaid-balance sufficiency at settlement; zero-balance requirements at termination and reinstatement), then temporal gates (market-price availability; the manifest scheduled-date rule), and finally idempotency (the duplicate `client_request_id` check).

Two concrete illustrations of this ordering. When a driver records a metered pickup, the server evaluates, in order: the stop's readiness state, then the metered volume against the tank's current level (`ERR_VOLUME_EXCEEDS_TANK_LEVEL`), then the route's remaining vehicle capacity (`ERR_ROUTE_CAPACITY_EXCEEDED`), then the zero-volume prohibition (`ERR_ZERO_VOLUME_PICKUP`), then market-price availability (`ERR_PRICE_NOT_PUBLISHED`), and only then the idempotency key (`ERR_DUPLICATE_CLIENT_REQUEST`). When a manifest is submitted, the facility gates — facility active, daily capacity, and halogenated-stream acceptance — are evaluated before the temporal check that the route's scheduled date is not in the past (`ERR_MANIFEST_SCHEDULED_DATE_PAST`).

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and no other endpoint accepts a version field.

Adding a stop to a route requires the request body to carry `expected_route_version`, the route `version` the planner last observed. Because every stop addition or removal advances the route's `version`, a writer whose view of the route's capacity and sequence allocation is stale — another planner has since modified the stop list — is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being allowed to allocate a sequence number against a route they have not observed.

Settling a pickup ticket requires the request body to carry `expected_customer_version`, the customer `version` the clerk last observed. Another settlement or top-up against the same customer has just moved `prepaid_balance_cents` or `outstanding_charge_cents`; settling against a stale snapshot could drive a prepaid balance negative or double-post a charge, so the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Units, Precision, and Rounding

All monetary amounts are integer cents; fractional cents are never stored or returned. All volumes are whole gallons. Where a calculation produces a non-integral intermediate, the result is rounded half up to the nearest whole unit at the step the rule specifies: liability after its cause multiplier, the customer half-share of a shared liability, the blended price of a `MIXED` stream, the weighted average halogen history of a blend, and the output gallons of a blend batch. Screening measurements carry their own precision: `water_pct` is recorded to one decimal place within 0.0 to 100.0, and `ph_level` to one decimal place within 0.0 to 14.0. Blend yield is expressed as a whole percent.

### 2.9. Derived State and Hierarchical Reconciliation

Several fields are never written directly; they are derived and reconciled by the server as events occur. A route's `loaded_gallons` accumulates metered volume from completed stops and may never exceed `vehicle_capacity_gallons`; its `posture` is derived — `CLOSED_OUT` once the route is `COMPLETE` or `CANCELLED`, otherwise `AT_CAPACITY` when `loaded_gallons` is greater than or equal to `vehicle_capacity_gallons` (equality counts as full), otherwise `OPEN`. A tank's `current_volume_gallons` is the sum of its intake events minus the sum of its pickup events and always stays within zero and `capacity_gallons` inclusive. A customer's `prepaid_balance_cents`, `outstanding_charge_cents`, and `halogen_violation_count` are maintained by settlement, top-up, and screening events. A facility's `scheduled_gallons_today` aggregates manifest volume (see §3.7).

State changes propagate down the hierarchy to keep the model consistent. Suspending or terminating a customer cascades to its sites, tanks, and scheduled stops; a halogen failure quarantines a tank and cancels its pending stops; a reportable spill contaminates a site and quarantines every tank on it. Each such cascade mutates the affected resources, refreshing `updated_at` and incrementing `version` on each mutated resource. Conversely, child events mutate parents: completing a stop draws down the tank, loads the route, and accrues manifest volume in the same atomic request. All mutations commit immediately within a single request; there is no asynchronous processing.

### 2.10. The Logical Clock

The server maintains a logical clock used wherever "today" or "now" matters — most notably the manifest scheduled-date rule and the facility's daily aggregation. At startup, before any clock-setting call, the logical clock reads exactly `2026-08-01T00:00:00Z` and must not fall back to real wall-clock time. A planner-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding, Credit Terms, and Balances

A `RoutePlanner` onboards a generator by creating a `Customer` with its `legal_name`, its `epa_generator_id` (the twelve-character EPA hazardous-waste generator identifier, required for halogen-bearing streams), its `market_zone` — one of `NORTH`, `SOUTH`, or `COASTAL`, which selects which commodity price applies at pumping time — and its `credit_terms`. New customers start in `PROSPECT` with `prepaid_balance_cents`, `outstanding_charge_cents`, and `halogen_violation_count` all at zero. The customer list supports `limit` and `offset` plus filters on `status` and `market_zone`.

Credit terms govern how money moves at settlement. A `PREPAY` customer must hold prepaid balance and is never invoiced; a `NET30` customer accrues invoiced charges; a `CHARGE_ONLY` customer is never paid for material and is always charged. A `SettlementClerk` may top up a customer's prepaid balance by an `amount_cents` value, which is added to `prepaid_balance_cents`.

Activation (`PROSPECT` → `ACTIVE`) is a planner action with two preconditions, evaluated after existence: the customer must currently be `PROSPECT` (otherwise `ERR_CUSTOMER_NOT_PROSPECT`), and the customer must have at least one tank site hosting at least one tank whose `ownership_status` is `INSTALLED` (otherwise `ERR_NO_SERVICEABLE_TANK`). Suspension (`ACTIVE` → `SUSPENDED`) requires an `ACTIVE` customer (otherwise `ERR_CUSTOMER_NOT_ACTIVE`) and cascades: every tank site under the customer becomes `INACTIVE`, and every future-dated stop still `SCHEDULED` against any tank at those sites becomes `CANCELLED_CUSTOMER`.

Reinstatement (`SUSPENDED` → `ACTIVE`) requires a `SUSPENDED` customer (otherwise `ERR_CUSTOMER_NOT_SUSPENDED`) and a zero `outstanding_charge_cents` (otherwise `ERR_OUTSTANDING_BALANCE`, HTTP 402); sites that were inactivated by the suspension cascade — not sites deactivated by an explicit planner call — return to `ACTIVE`. Termination (`ACTIVE` → `TERMINATED`, the terminal state) requires an `ACTIVE` customer (otherwise `ERR_CUSTOMER_NOT_ACTIVE`), zero `outstanding_charge_cents` (`ERR_OUTSTANDING_BALANCE`), and zero `prepaid_balance_cents` (`ERR_UNRETURNED_PREPAID_BALANCE`, HTTP 402) — the company does not close an account while holding the customer's money or vice versa. Termination cascades: every site becomes `INACTIVE`, every tank's `ownership_status` becomes `DECOMMISSION_PENDING`, and every non-terminal stop referencing those tanks becomes `CANCELLED_CUSTOMER`.

### 3.2. Tank Sites, Tanks, Installation, and Intake

Each `TankSite` belongs to a customer via `customer_id` and is created by a planner with a `site_address`, a `density_zone` of `URBAN`, `SUBURBAN`, or `RURAL` — which drives the minimum-pickup threshold for route eligibility — and an optional `route_eligibility_override` flag that defaults to false and, when true, marks the site as contract-carved so it bypasses the density minimum-pickup check. Sites are born `ACTIVE`. The site list filters by `customer_id` and `status`; a customer's sites are also reachable as a nested collection under the customer.

Deactivating a site (`ACTIVE` → `INACTIVE`) is blocked while any stop referencing a tank at the site is in `SCHEDULED`, `EN_ROUTE`, `SCREENING`, or `READY_TO_PUMP` (`ERR_SITE_HAS_ACTIVE_STOPS`). Reactivating an `INACTIVE` site requires the owning customer to be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE`). Both directions are planner actions.

A `Tank` is created at a site by a `TankInstaller` supplying `tank_site_id`, a `tank_kind` of `USED_OIL`, `ANTIFREEZE`, or `MIXED`, a `capacity_gallons` greater than zero, and an `ownership` of `COMPANY_OWNED` or `CUSTOMER_OWNED`. New tanks begin with `ownership_status` `PENDING_INSTALL`, `quarantine_status` `CLEAR`, and `current_volume_gallons` zero; the tank list filters by `tank_site_id`, `ownership_status`, and `quarantine_status`. Installation splits by ownership with symmetric rigor: a `COMPANY_OWNED` tank is marked installed by the installer, requiring `PENDING_INSTALL` (otherwise `ERR_TANK_NOT_PENDING_INSTALL`) and company ownership (otherwise `ERR_TANK_NOT_COMPANY_OWNED`); a `CUSTOMER_OWNED` tank skips physical installation and is instead registered through the existing-inventory path, requiring `PENDING_INSTALL` (`ERR_TANK_NOT_PENDING_INSTALL`) and customer ownership (otherwise `ERR_TANK_NOT_CUSTOMER_OWNED`). Both paths stamp `installed_at` with the current UTC time and move `ownership_status` to `INSTALLED`.

Decommissioning is a two-step handshake. Beginning decommission moves `INSTALLED` → `DECOMMISSION_PENDING` and requires the tank to be empty — `current_volume_gallons` exactly zero, otherwise `ERR_TANK_NOT_EMPTY` — and to have no stop in `SCHEDULED`, `EN_ROUTE`, `SCREENING`, or `READY_TO_PUMP` (otherwise `ERR_TANK_HAS_ACTIVE_STOPS`). Confirming decommission requires `DECOMMISSION_PENDING` (otherwise `ERR_TANK_NOT_PENDING_DECOMMISSION`) and lands the tank in the terminal `DECOMMISSIONED` state. Customer termination forces every tank into `DECOMMISSION_PENDING` via cascade, and the same confirmation step applies afterward.

Between service events, a shop drains vehicles into the tank; a driver or planner records each such fill as an intake of `gallons`, which is added to `current_volume_gallons`. An intake that would push the level above `capacity_gallons` is rejected with `ERR_TANK_OVERFLOW` (HTTP 409).

Quarantine is a parallel hazard dimension orthogonal to the ownership lifecycle. A tank moves `CLEAR` → `QUARANTINED` automatically when a screening on that tank returns a halogen failure, or when its site is contaminated by a reportable spill; in the halogen case, any stop referencing that tank still in `SCHEDULED` or `EN_ROUTE` is cancelled to `CANCELLED_HALOGEN`. An `EHSOfficer` clears quarantine only while the tank is `QUARANTINED` (otherwise `ERR_TANK_NOT_QUARANTINED`) and its site is no longer `CONTAMINATED` (otherwise `ERR_SITE_STILL_CONTAMINATED`).

### 3.3. Route Planning, Stop Scheduling, and Dispatch

Before routes run, the planner maintains the driver roster. Registering a driver captures `driver_name`, a `cdl_class` of `A`, `B`, or `C` (tanker work requires class `A` or `B`), and a `hazmat_endorsement` flag — required to haul halogen-quarantined material or any `MIXED` tank. Drivers are born `ACTIVE`; a planner may suspend one, moving it to `SUSPENDED`. The driver list filters by `status`.

A planner creates a `Route` with a human-readable `route_code` unique per `scheduled_date`, the ISO calendar `scheduled_date` the route runs, the assigned `driver_id`, a `vehicle_capacity_gallons` greater than zero, and the route's dominant `density_zone`. A new route is `PLANNED`, with `posture` `OPEN` and `loaded_gallons` zero. Route lists filter by `status`, `scheduled_date`, and `driver_id`; a route's stops and its manifest are reachable as nested collections under the route.

Stops are added to a route by a planner supplying the `tank_site_id` and `tank_id` to service, a `scheduled_window_start` and `scheduled_window_end` in 24-hour local `HH:MM` form with the end strictly after the start, a 1-based `sequence` unique within the route, an `estimated_volume_gallons` used for capacity planning and never for settlement, and the OCC field `expected_route_version` described in §2.7. A duplicated sequence or an inverted window is rejected with `ERR_INVALID_STOP_WINDOW` (HTTP 400); a stale route version is rejected per the OCC rule. A successfully added stop begins `SCHEDULED`, and the route's `version` increments. The stop collection filters by `route_id`, `tank_site_id`, `tank_id`, and `status`.

Dispatch (`PLANNED` → `DISPATCHED`) enforces four preconditions: the route is `PLANNED` (otherwise `ERR_ROUTE_NOT_PLANNED`); at least one stop is `SCHEDULED` (otherwise `ERR_ROUTE_EMPTY`); the assigned driver is `ACTIVE` (otherwise `ERR_DRIVER_SUSPENDED`); and, when any stop's tank has `tank_kind` `MIXED`, the driver holds a hazmat endorsement (otherwise `ERR_DRIVER_NO_HAZMAT`, HTTP 403). The route then moves `DISPATCHED` → `IN_PROGRESS` automatically the moment its first stop goes en route.

Completion (`IN_PROGRESS` → `COMPLETE`) requires every stop on the route to have reached a terminal state — `COMPLETED`, `SKIPPED_BELOW_MINIMUM`, `CANCELLED_HALOGEN`, `CANCELLED_ROUTE`, or `CANCELLED_CUSTOMER` — otherwise `ERR_ROUTE_HAS_OPEN_STOPS`; and, if a manifest exists for the route, it must already be `SUBMITTED`, `IN_TRANSIT`, `DELIVERED`, `AMENDED`, or `CLOSED` — completing against a `DRAFT` manifest is rejected with `ERR_MANIFEST_NOT_SUBMITTED`. Completion sets `posture` to `CLOSED_OUT`.

Cancellation has two branches with symmetric precision. From `PLANNED`, cancellation is permitted while the route is `PLANNED` or `DISPATCHED` (otherwise `ERR_ROUTE_NOT_CANCELLABLE`); every `SCHEDULED` stop becomes `CANCELLED_ROUTE`, and a `DRAFT` manifest, if one exists, remains `DRAFT` but orphaned — while a manifest already `SUBMITTED` blocks the cancellation outright with `ERR_ROUTE_HAS_SUBMITTED_MANIFEST`. From `DISPATCHED`, cancellation additionally requires that no stop has reached `COMPLETED` (otherwise `ERR_ROUTE_HAS_COMPLETED_STOPS`) and again that no manifest is `SUBMITTED` or beyond (`ERR_ROUTE_HAS_SUBMITTED_MANIFEST`); every non-terminal stop becomes `CANCELLED_ROUTE`.

### 3.4. Field Execution: Arrival, Screening, and the Pickup Ticket

When the driver reaches a site, arriving moves the stop `SCHEDULED` → `EN_ROUTE`. Arrival requires the stop to be `SCHEDULED` (otherwise `ERR_STOP_NOT_SCHEDULED`), the route to be `DISPATCHED` or `IN_PROGRESS` (otherwise `ERR_ROUTE_NOT_DISPATCHED`), the tank's `quarantine_status` to be `CLEAR` (otherwise `ERR_TANK_QUARANTINED`), and the site's `status` to be `ACTIVE` (otherwise `ERR_SITE_NOT_ACTIVE`). If the route was `DISPATCHED`, this first arrival advances it to `IN_PROGRESS`. Beginning screening then moves the stop `EN_ROUTE` → `SCREENING`, requiring only that the stop is `EN_ROUTE` (otherwise `ERR_STOP_NOT_EN_ROUTE`).

A `LabTech` — never the driver — records the sample screening with three measurements: `halogen_ppm` as an integer from 0 to 100000, `water_pct` from 0.0 to 100.0 to one decimal, and `ph_level` from 0.0 to 14.0 to one decimal, the pH constraint applying to antifreeze tanks only. The server computes the `result` — `PASS`, `FAIL_HALOGEN`, `FAIL_WATER`, or `FAIL_PH` — by comparing the measurements against the screening thresholds appropriate to the tank's `tank_kind`, stamps the screening with the technician's `screened_by_user_id` and the UTC `screening_recorded_at`, and drives the stop accordingly. A `PASS` moves the stop `SCREENING` → `READY_TO_PUMP`; a stop not in `SCREENING` rejects the recording with `ERR_STOP_NOT_SCREENING`, and a recording whose computed result does not permit the requested transition is rejected with `ERR_SCREEN_FAILED` (HTTP 422).

The failure branches diverge sharply. A `FAIL_HALOGEN` result moves the stop to `CANCELLED_HALOGEN`, quarantines the tank (`CLEAR` → `QUARANTINED`, which also cancels any other `SCHEDULED` or `EN_ROUTE` stop on the same tank), and increments the customer's `halogen_violation_count` by one; when the count crosses the third or fifth violation, an internal customer-notification flag is set. A `FAIL_WATER` or `FAIL_PH` result is recoverable: the stop returns to `SCHEDULED` and a reschedule note is attached. Screening history for a stop is listable, and the screening collection filters by `route_stop_id` and `result`.

With the stop `READY_TO_PUMP`, the driver records the metered pickup. The request carries a `client_request_id` — an idempotency key supplied by the driver's handheld, unique per stop — and the `metered_volume_gallons` actually pumped, which must be greater than zero and no more than the tank's `current_volume_gallons` at pump time. The checks fire in the §2.6 order: a stop not `READY_TO_PUMP` yields `ERR_STOP_NOT_READY_TO_PUMP`; volume above the tank level yields `ERR_VOLUME_EXCEEDS_TANK_LEVEL` (HTTP 422); volume that would push the route's `loaded_gallons` past `vehicle_capacity_gallons` yields `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 422); a zero metered volume yields `ERR_ZERO_VOLUME_PICKUP` (HTTP 400) — the driver must use the skip path instead; and a repeated `client_request_id` on the same stop yields `ERR_DUPLICATE_CLIENT_REQUEST` (HTTP 409). On success the stop becomes `COMPLETED`, the tank's `current_volume_gallons` decreases by the metered volume, the route's `loaded_gallons` increases by the same amount (pushing `posture` to `AT_CAPACITY` when the load reaches capacity exactly), a `PickupTicket` is created in `PROVISIONAL` with the full settlement calculation of §3.5, and — if a manifest already exists for the route — its `total_gallons_manifested` increases by the metered volume.

The skip path handles the below-minimum tank. A driver may skip a `READY_TO_PUMP` stop only when the tank's `current_volume_gallons` is below the site zone's minimum (otherwise `ERR_VOLUME_ABOVE_MINIMUM`, signalling the pickup path must be used) and the site does not carry `route_eligibility_override` (otherwise `ERR_SITE_OVERRIDE_ACTIVE`). The skip request also carries a `client_request_id`. Skipping moves the stop to `SKIPPED_BELOW_MINIMUM` and creates a zero-volume `PickupTicket` — a metered volume of exactly zero is permitted only through this path — with `density_fee_cents` posted for audit. The density thresholds themselves are: 50 gallons for an `URBAN` site, 100 for `SUBURBAN`, and 150 for `RURAL`. A volume exactly equal to the zone minimum counts as meeting it — no density fee is charged and skipping is not permitted; a volume one gallon below the minimum triggers the fee-or-skip logic. A `READY_TO_PUMP` pickup with a sub-minimum (but non-zero) volume still completes normally, with the density fee assessed on the ticket.

A planner may cancel a stop on the customer's behalf while it is `SCHEDULED` or `EN_ROUTE` (otherwise `ERR_STOP_NOT_CANCELLABLE`), moving it to `CANCELLED_CUSTOMER`. Two system cascades can also terminate a stop without any direct call on it: route cancellation moves `SCHEDULED` stops to `CANCELLED_ROUTE`, and tank quarantine from a halogen screen at another stop on the same tank moves `SCHEDULED` or `EN_ROUTE` stops to `CANCELLED_HALOGEN`. A stop's tickets are listable as a nested collection.

### 3.5. Market Pricing and the Settlement Calculation

Commodity prices are published by a `Regulator` as `MarketPrice` rows keyed by `market_zone`, `tank_kind`, and an `effective_date` that acts as an inclusive lower bound; the `price_cents_per_gal` is signed — positive means the company pays the generator, negative means the generator pays the company — and zero is permitted. Price lists filter by `market_zone`, `tank_kind`, and `effective_date`.

When a pickup is priced, the server selects, among the rows for the customer's `market_zone` and the tank's `tank_kind`, the most recent row whose `effective_date` is on or before the route's `scheduled_date` — a row dated exactly the scheduled date is used — and never uses a future-dated row. If no such row exists, the pickup is rejected with `ERR_PRICE_NOT_PUBLISHED` (HTTP 422). The sign convention differs by stream: `USED_OIL` prices are always non-negative, since the company pays the generator; `ANTIFREEZE` prices are signed, positive when recycled glycol value dominates and negative when disposal cost dominates. A `MIXED` tank is priced as the weighted blend of that zone's used-oil and antifreeze prices: the used-oil price multiplied by the tank's declared oil-share percent, plus the antifreeze price multiplied by the remainder of one hundred, the sum divided by one hundred and rounded half up to whole cents; when no oil share is declared, a fifty-percent oil share is assumed.

Every `PickupTicket` snapshots the resolved price into `commodity_price_cents_per_gal` and freezes the customer's `halogen_violation_count` at screening time into `frozen_halogen_count` for later blend-yield weighting; the ticket also denormalizes the tank's `tank_kind` and the stop's `route_id` for blend-mix analysis and the manifest cascade. The settlement calculation then proceeds in a pinned order — gross first, then surcharge, then density fee, then the sign:

- `gross_amount_cents` is the absolute value of the signed price multiplied by the metered volume, computed in exact integer cents.
- `surcharge_cents` tiers on the frozen halogen violation count: zero violations means no surcharge; one or two violations assess a flat 500 cents (five dollars); three or four violations assess 1,500 cents (fifteen dollars); beyond four, the surcharge is 1,500 cents plus 250 cents multiplied by the number of violations beyond the fourth.
- `density_fee_cents` is zero when the metered volume meets or exceeds the site's zone minimum or the site carries `route_eligibility_override`; otherwise it is the shortfall — the zone minimum minus the metered volume — multiplied by the zone's per-gallon fee: 20 cents per gallon for `URBAN`, 15 for `SUBURBAN`, and 10 for `RURAL`.
- `net_amount_cents` is signed. When the price is positive, the net is the gross amount minus the surcharge minus the density fee. When the price is negative, the net is the negation of the sum of gross, surcharge, and density fee. When the price is exactly zero, the net is zero.
- `settlement_direction` derives from the net: a positive net is `PAY_CUSTOMER`, a negative net is `CHARGE_CUSTOMER`, and zero is `ZERO_NET`.

This calculation runs twice in a ticket's life. The provisional variant runs at creation, uses the price as of the route's `scheduled_date`, and leaves `payment_status` `PROVISIONAL` until settlement. The adjusted variant runs after a dispute and recomputes from a corrected metered volume or, when the dispute re-attributes the service date, the price of a different scheduled date; only the difference between the new and old net is posted to the customer. Ticket lists filter by `payment_status` and `route_stop_id`.

### 3.6. Settlement, Disputes, and Adjustments

Settlement is the clerk's domain. Settling a ticket (`PROVISIONAL` → `SETTLED`) requires the ticket to be `PROVISIONAL` (otherwise `ERR_TICKET_NOT_PROVISIONAL`), its stop to be `COMPLETED` (otherwise `ERR_STOP_NOT_COMPLETED`), and the OCC field `expected_customer_version` per §2.7, with a mismatch rejected as `ERR_STALE_VERSION`. For a `PREPAY` customer whose ticket net is negative, settlement additionally requires the prepaid balance to absorb the charge — `prepaid_balance_cents` plus the negative `net_amount_cents` must not drop below zero — otherwise the settle is rejected with `ERR_INSUFFICIENT_PREPAID_BALANCE` (HTTP 402). On success, the net posts to the customer according to direction and terms: a `PAY_CUSTOMER` net is added to `prepaid_balance_cents`; a `CHARGE_CUSTOMER` net against a `NET30` or `CHARGE_ONLY` customer adds the absolute net to `outstanding_charge_cents`; a `CHARGE_CUSTOMER` net against a `PREPAY` customer subtracts the absolute net from `prepaid_balance_cents`. The ticket becomes `SETTLED` and the customer's `version` increments.

Dispute is a correction cycle, not a dead end: `SETTLED` is deliberately not terminal. A clerk may dispute a ticket that is `PROVISIONAL` or `SETTLED` (anything else yields `ERR_TICKET_NOT_DISPUTABLE`), moving it to `DISPUTED`. When a previously `SETTLED` ticket is disputed, the original net remains posted to the customer; the later adjustment posts only the delta. Adjusting requires the ticket to be `DISPUTED` (otherwise `ERR_TICKET_NOT_DISPUTED`) and accepts a `corrected_metered_volume_gallons` and an optional `override_price_cents_per_gal`; the net is recomputed per §3.5, and the customer is posted only the delta between the new and the old net when the ticket had previously settled, or the full new net when it never settled. Adjustment lands the ticket in `ADJUSTED`, the only truly terminal payment state.

### 3.7. Manifests and the Disposal-Facility Chain of Custody

A `Regulator` registers each receiving TSDF as a `DisposalFacility` with its `facility_name`, a unique `epa_id`, the `accepted_streams` array drawn from `USED_OIL`, `ANTIFREEZE`, `MIXED`, and `HALOGENATED`, and a `daily_capacity_gallons` ceiling on gallons receivable per calendar day. Facilities start `ACTIVE` with `scheduled_gallons_today` at zero; the facility list filters by `status`. The facility's `scheduled_gallons_today` is the sum of `total_gallons_manifested` across all manifests in `SUBMITTED`, `IN_TRANSIT`, or `AMENDMENT_PENDING` whose route's `scheduled_date` equals the server's current date. The figure is derived from current manifest state on every read rather than stored as a counter: a manifest's total enters the sum on submission, stays counted through departure, and leaves the sum when the manifest is delivered, has an amendment approved, or is rejected by the facility; requesting an amendment on a delivered manifest brings its total back into the sum, while transitions between uncounted states — such as closing an already-delivered manifest — leave the figure unchanged.

A planner drafts the route's regulatory record by creating a `Manifest` — one per route — with a unique `manifest_tracking_number` (the EPA Uniform Hazardous Waste Manifest number) and the destination `disposal_facility_id`. The draft begins in `DRAFT` with `total_gallons_manifested` zero and `halogen_flag` false; the total is recomputed as the sum of metered volumes from the route's `COMPLETED` stops on each stop completion and again on amendment, and `halogen_flag` turns true when any pickup on the route came from a previously quarantined tank, marking the load for the facility. Manifest lists filter by `status`, `disposal_facility_id`, and `route_id`.

Submission (`DRAFT` → `SUBMITTED`, and equally `AMENDED` → `SUBMITTED` in the correction cycle) is gated by five checks: the manifest is `DRAFT` or `AMENDED` (otherwise `ERR_MANIFEST_NOT_SUBMITTABLE`); the route is `IN_PROGRESS` or `COMPLETE` (otherwise `ERR_ROUTE_NOT_READY_FOR_MANIFEST`); the facility is `ACTIVE` (otherwise `ERR_FACILITY_SUSPENDED`); the facility's `scheduled_gallons_today` plus this manifest's total stays within `daily_capacity_gallons` (otherwise `ERR_FACILITY_CAPACITY_EXCEEDED`); and, when `halogen_flag` is true, `HALOGENATED` appears in the facility's `accepted_streams` (otherwise `ERR_FACILITY_REJECTS_HALOGENATED`). After those referential gates, the temporal gate applies: a route whose `scheduled_date` is in the past at submit time is rejected with `ERR_MANIFEST_SCHEDULED_DATE_PAST` (HTTP 422). A successful submission moves the manifest into the counted `SUBMITTED` state, so the manifest total is reflected in the facility's `scheduled_gallons_today` whenever the route's `scheduled_date` equals the server's current date. Resubmission of an `AMENDED` manifest uses the recomputed totals and repeats the same gates.

Transport is the driver's pair of actions: departure requires a `SUBMITTED` manifest (otherwise `ERR_MANIFEST_NOT_SUBMITTED`) and a `COMPLETE` route (otherwise `ERR_ROUTE_NOT_COMPLETE`), moving the manifest to `IN_TRANSIT`; delivery requires `IN_TRANSIT` (otherwise `ERR_MANIFEST_NOT_IN_TRANSIT`) and lands the manifest at `DELIVERED`. Closure is the regulator's act: closing requires `DELIVERED` (otherwise `ERR_MANIFEST_NOT_DELIVERED`) and every spill incident on the route to be in a terminal state (otherwise `ERR_OPEN_SPILL_EXISTS`); closure lands the manifest in the terminal `CLOSED` state and, because a `DELIVERED` manifest is already outside the counted set, leaves the facility's `scheduled_gallons_today` unchanged.

The amendment loop makes the manifest cyclic. A planner may request an amendment on a `DELIVERED` manifest (otherwise `ERR_MANIFEST_NOT_DELIVERED`), moving it to `AMENDMENT_PENDING`. Regulator approval requires `AMENDMENT_PENDING` (otherwise `ERR_MANIFEST_NOT_PENDING_AMENDMENT`), recomputes `total_gallons_manifested` from the route's currently `COMPLETED` stops as a reconciliation, and moves the manifest to `AMENDED` — from which submission restarts the cycle. Separately, the regulator may record the facility's rejection of a `SUBMITTED` manifest (otherwise `ERR_MANIFEST_NOT_SUBMITTED`): the manifest lands in the terminal `REJECTED_BY_FACILITY` state, the facility's `scheduled_gallons_today` is decremented by the manifest total, and the route's `posture` is forced to `CLOSED_OUT` if it is not already.

### 3.8. Blending and Product Resale

Settled tickets are feedstock. A planner creates a `BlendBatch` with a unique `batch_code`, a `target_product` of `RE_REFINED_BASE_OIL`, `RECYCLED_ANTIFREEZE`, or `FUEL_BLENDING_STOCK`, the `input_pickup_ticket_ids` to consume, and the `resale_price_cents_per_gal` at which the output will be sold. The batch is born `PLANNED`, and creation computes an optimistic what-if projection stored as `planned_output_gallons` — computed with zero halogen history and no mix penalty, informational only and never posted to inventory. Batch lists filter by `status`.

Starting the blend (`PLANNED` → `BLENDING`) is a planner action gated on two input checks with equal rigor: every ticket in `input_pickup_ticket_ids` must be `SETTLED` (otherwise `ERR_TICKET_NOT_SETTLED`), and no ticket may already be consumed by another batch that is not `CANCELLED` (otherwise `ERR_TICKET_ALREADY_CONSUMED`); a batch not in `PLANNED` is rejected with `ERR_BATCH_NOT_PLANNED`. Starting the blend computes the actual figures, overwriting the projection: `input_gallons_total` is the sum of the consumed tickets' metered volumes, which must total at least one gallon; the weighted average halogen history is the sum over tickets of each `frozen_halogen_count` multiplied by its metered volume, divided by `input_gallons_total`, rounded half up to a whole number; the base yield is 72 percent for `RE_REFINED_BASE_OIL`, 85 percent for `RECYCLED_ANTIFREEZE`, and 60 percent for `FUEL_BLENDING_STOCK`; the halogen penalty subtracts two percentage points for each average violation above four — never below zero and capped at twenty percentage points; when the consumed tickets span more than one distinct `tank_kind`, a further five-percentage-point mix penalty applies; and `yield_pct` is the base minus both penalties, floored at zero. The `output_gallons` is `input_gallons_total` multiplied by `yield_pct` and divided by one hundred, rounded half up to whole gallons, and `gross_resale_revenue_cents` is `output_gallons` multiplied by `resale_price_cents_per_gal`. The actual figure is almost always at or below the optimistic projection.

Quality control belongs to the `LabTech`. A batch in `BLENDING` may be placed on `QUALITY_HOLD` (any other state yields `ERR_BATCH_NOT_BLENDING`), and a held batch resumes to `BLENDING` (requiring `QUALITY_HOLD`, otherwise `ERR_BATCH_NOT_ON_HOLD`). Releasing a batch for sale requires `BLENDING` (otherwise `ERR_BATCH_NOT_BLENDING`) and moves it to `RELEASED_FOR_SALE`. A `SettlementClerk` then marks a released batch sold (`RELEASED_FOR_SALE` → `SOLD`; otherwise `ERR_BATCH_NOT_RELEASED`), the terminal revenue state. Cancellation is permitted from `PLANNED` or `BLENDING` (otherwise `ERR_BATCH_NOT_CANCELLABLE`) and lands the batch in `CANCELLED`; cancelling releases every ticket in `input_pickup_ticket_ids`, making them eligible for consumption by a later batch.

### 3.9. Spill Response and Environmental Liability

A spill is logged by the driver on scene or by an `EHSOfficer`, naming the `route_id` active at the time, the `tank_site_id` where the release occurred, an estimated `gallons_spilled` greater than zero, and a `cause_code` of `EQUIPMENT_FAILURE`, `CUSTOMER_OVERFILL`, `DRIVER_ERROR`, `THIRD_PARTY`, or `UNKNOWN`; the server records the logging user as `reported_by_user_id`. The incident opens in `OPEN`. The reportable-quantity threshold is 25 gallons: a spill of 25 gallons or more sets `reportable_quantity_exceeded` true, and such a reportable spill immediately drives its tank site to `CONTAMINATED`, which in turn quarantines every tank at the site (`CLEAR` → `QUARANTINED`). Spill lists filter by `status`, `tank_site_id`, and `route_id`.

Investigation moves `OPEN` → `UNDER_INVESTIGATION` under an `EHSOfficer` (otherwise `ERR_SPILL_NOT_OPEN`), and the reportable-quantity contamination cascade is enforced there as well. Remediation requires `UNDER_INVESTIGATION` (otherwise `ERR_SPILL_NOT_UNDER_INVESTIGATION`), moves the incident to `REMEDIATED`, and computes the liability. The base rate is 850 cents per gallon spilled (eight dollars and fifty cents); the raw liability is that base multiplied by the cause multiplier — 1.5 for `EQUIPMENT_FAILURE`, 1.0 for `CUSTOMER_OVERFILL`, 2.0 for `DRIVER_ERROR`, 0.5 for `THIRD_PARTY`, and 1.0 for `UNKNOWN` — rounded half up to whole cents. The `responsible_party` derives in a fixed order: `CUSTOMER_OVERFILL` assigns `CUSTOMER`; `DRIVER_ERROR` assigns `COMPANY`; `EQUIPMENT_FAILURE` assigns `COMPANY` when the tank is `COMPANY_OWNED` and `CUSTOMER` when it is customer-owned; `THIRD_PARTY` assigns `COMPANY`, which absorbs third-party risk on the route; and `UNKNOWN` assigns `SHARED`. `liability_cents` is the raw liability, and for a `SHARED` outcome the customer's share is half of it, rounded half up, while a `CUSTOMER` outcome assigns the customer the full amount and a `COMPANY` outcome assigns the customer nothing. When the reportable quantity was exceeded, a flat 50,000-cent (five-hundred-dollar) regulatory fee is added to `liability_cents` regardless of party.

Closure is deliberately two-branched. Closing with liability requires `REMEDIATED` (otherwise `ERR_SPILL_NOT_REMEDIATED`) and a positive `liability_cents` (otherwise `ERR_SPILL_NO_LIABILITY`), landing the incident in `CLOSED_WITH_LIABILITY`; when the responsible party is `CUSTOMER` or `SHARED`, the customer's share of the liability is added to `outstanding_charge_cents`, and when it is `COMPANY` no customer debit occurs. Closing with no action likewise requires `REMEDIATED` (`ERR_SPILL_NOT_REMEDIATED`) but a zero `liability_cents` (otherwise `ERR_SPILL_HAS_LIABILITY`), landing the incident in `CLOSED_NO_ACTION`. Only once every spill at a site has reached `REMEDIATED`, `CLOSED_NO_ACTION`, or `CLOSED_WITH_LIABILITY` may an `EHSOfficer` certify the site clean (otherwise `ERR_OPEN_SPILL_EXISTS`): certification moves the site `CONTAMINATED` → `ACTIVE` and clears the quarantine of every tank at the site, while each tank's halogen history remains preserved in its screening record.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions — return `200 OK`. Request and response payloads for each endpoint are governed by the workflows in §3; the table below is the routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/recycle-routes/customers` | Create a customer in `PROSPECT` status | RoutePlanner |
| GET | `/recycle-routes/customers` | List customers | RoutePlanner, SettlementClerk, EHSOfficer, Regulator |
| GET | `/recycle-routes/customers/{customerId}` | Get one customer | RoutePlanner, SettlementClerk, EHSOfficer, Regulator |
| POST | `/recycle-routes/customers/{customerId}/activate` | Activate a `PROSPECT` customer | RoutePlanner |
| POST | `/recycle-routes/customers/{customerId}/suspend` | Suspend an `ACTIVE` customer (cascades) | RoutePlanner |
| POST | `/recycle-routes/customers/{customerId}/reinstate` | Reinstate a `SUSPENDED` customer | RoutePlanner |
| POST | `/recycle-routes/customers/{customerId}/terminate` | Terminate an `ACTIVE` customer | RoutePlanner |
| POST | `/recycle-routes/customers/{customerId}/top-up` | Add prepaid balance to a customer | SettlementClerk |
| GET | `/recycle-routes/customers/{customerId}/tank-sites` | List tank sites for a customer | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, TankInstaller, Driver |
| POST | `/recycle-routes/tank-sites` | Create a tank site under a customer | RoutePlanner |
| GET | `/recycle-routes/tank-sites` | List tank sites | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, TankInstaller, Driver |
| GET | `/recycle-routes/tank-sites/{tankSiteId}` | Get one tank site | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, TankInstaller, Driver |
| POST | `/recycle-routes/tank-sites/{tankSiteId}/activate` | Activate an `INACTIVE` tank site | RoutePlanner |
| POST | `/recycle-routes/tank-sites/{tankSiteId}/deactivate` | Deactivate an `ACTIVE` tank site | RoutePlanner |
| POST | `/recycle-routes/tank-sites/{tankSiteId}/certify-clean` | Certify a `CONTAMINATED` site clean | EHSOfficer |
| GET | `/recycle-routes/tank-sites/{tankSiteId}/tanks` | List tanks at a site | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, TankInstaller, Driver |
| POST | `/recycle-routes/tanks` | Create a tank at a site (`PENDING_INSTALL`) | TankInstaller |
| GET | `/recycle-routes/tanks` | List tanks | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, TankInstaller, Driver |
| GET | `/recycle-routes/tanks/{tankId}` | Get one tank | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, TankInstaller, Driver |
| POST | `/recycle-routes/tanks/{tankId}/install` | Mark a `COMPANY_OWNED` tank installed | TankInstaller |
| POST | `/recycle-routes/tanks/{tankId}/register-existing` | Register a `CUSTOMER_OWNED` tank as installed | TankInstaller |
| POST | `/recycle-routes/tanks/{tankId}/decommission` | Begin decommissioning (requires empty tank) | TankInstaller |
| POST | `/recycle-routes/tanks/{tankId}/decommission-confirm` | Confirm decommissioning | TankInstaller |
| POST | `/recycle-routes/tanks/{tankId}/clear-quarantine` | Clear tank quarantine | EHSOfficer |
| POST | `/recycle-routes/tanks/{tankId}/record-intake` | Add volume to a tank (customer fill event) | Driver, RoutePlanner |
| POST | `/recycle-routes/drivers` | Register a driver | RoutePlanner |
| GET | `/recycle-routes/drivers` | List drivers | RoutePlanner, EHSOfficer |
| GET | `/recycle-routes/drivers/{driverId}` | Get one driver | RoutePlanner, EHSOfficer, Driver |
| POST | `/recycle-routes/drivers/{driverId}/suspend` | Suspend a driver | RoutePlanner |
| POST | `/recycle-routes/routes` | Create a route | RoutePlanner |
| GET | `/recycle-routes/routes` | List routes | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| GET | `/recycle-routes/routes/{routeId}` | Get one route | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| POST | `/recycle-routes/routes/{routeId}/dispatch` | Dispatch a `PLANNED` route | RoutePlanner |
| POST | `/recycle-routes/routes/{routeId}/complete` | Mark a route `COMPLETE` | RoutePlanner |
| POST | `/recycle-routes/routes/{routeId}/cancel` | Cancel a route | RoutePlanner |
| GET | `/recycle-routes/routes/{routeId}/route-stops` | List stops on a route | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| GET | `/recycle-routes/routes/{routeId}/manifest` | Get the manifest for a route | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| POST | `/recycle-routes/routes/{routeId}/route-stops` | Add a stop to a route (OCC on route version) | RoutePlanner |
| GET | `/recycle-routes/route-stops/{routeStopId}` | Get one stop | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| GET | `/recycle-routes/route-stops` | List stops | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| POST | `/recycle-routes/route-stops/{routeStopId}/arrive` | Driver arrives; `SCHEDULED` → `EN_ROUTE` | Driver |
| POST | `/recycle-routes/route-stops/{routeStopId}/begin-screening` | Begin screening; `EN_ROUTE` → `SCREENING` | Driver |
| POST | `/recycle-routes/route-stops/{routeStopId}/cancel-by-customer` | Customer cancels a stop | RoutePlanner |
| POST | `/recycle-routes/route-stops/{routeStopId}/skip-below-minimum` | Skip a stop below the zone minimum volume | Driver |
| GET | `/recycle-routes/route-stops/{routeStopId}/sample-screenings` | List screenings for a stop | RoutePlanner, LabTech, EHSOfficer, Regulator, Driver |
| GET | `/recycle-routes/route-stops/{routeStopId}/pickup-tickets` | List pickup tickets for a stop | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| POST | `/recycle-routes/route-stops/{routeStopId}/sample-screenings` | Record a sample screening | LabTech |
| GET | `/recycle-routes/sample-screenings/{screeningId}` | Get one screening | RoutePlanner, LabTech, EHSOfficer, Regulator |
| GET | `/recycle-routes/sample-screenings` | List screenings | RoutePlanner, LabTech, EHSOfficer, Regulator |
| POST | `/recycle-routes/route-stops/{routeStopId}/pickup-tickets` | Record a metered pickup (idempotent) | Driver |
| GET | `/recycle-routes/pickup-tickets/{ticketId}` | Get one ticket | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| GET | `/recycle-routes/pickup-tickets` | List pickup tickets | RoutePlanner, SettlementClerk, EHSOfficer, Regulator |
| POST | `/recycle-routes/pickup-tickets/{ticketId}/settle` | Settle a `PROVISIONAL` ticket (OCC on customer version) | SettlementClerk |
| POST | `/recycle-routes/pickup-tickets/{ticketId}/dispute` | Mark a ticket `DISPUTED` | SettlementClerk |
| POST | `/recycle-routes/pickup-tickets/{ticketId}/adjust` | Adjust a `DISPUTED` ticket; post delta | SettlementClerk |
| POST | `/recycle-routes/disposal-facilities` | Register a disposal facility (TSDF) | Regulator |
| GET | `/recycle-routes/disposal-facilities` | List facilities | RoutePlanner, Regulator, EHSOfficer |
| GET | `/recycle-routes/disposal-facilities/{facilityId}` | Get one facility | RoutePlanner, Regulator, EHSOfficer |
| POST | `/recycle-routes/routes/{routeId}/manifest` | Create a `DRAFT` manifest for a route | RoutePlanner |
| GET | `/recycle-routes/manifests/{manifestId}` | Get one manifest | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| GET | `/recycle-routes/manifests` | List manifests | RoutePlanner, SettlementClerk, EHSOfficer, Regulator, Driver |
| POST | `/recycle-routes/manifests/{manifestId}/submit` | Submit a `DRAFT` or `AMENDED` manifest | RoutePlanner |
| POST | `/recycle-routes/manifests/{manifestId}/depart` | Driver departs for the facility | Driver |
| POST | `/recycle-routes/manifests/{manifestId}/deliver` | Driver delivers at the facility | Driver |
| POST | `/recycle-routes/manifests/{manifestId}/close` | Regulator closes the manifest | Regulator |
| POST | `/recycle-routes/manifests/{manifestId}/request-amendment` | Request amendment on a `DELIVERED` manifest | RoutePlanner |
| POST | `/recycle-routes/manifests/{manifestId}/approve-amendment` | Regulator approves an amendment | Regulator |
| POST | `/recycle-routes/manifests/{manifestId}/facility-reject` | Facility rejects the manifest | Regulator |
| POST | `/recycle-routes/blend-batches` | Create a blend batch in `PLANNED` | RoutePlanner |
| GET | `/recycle-routes/blend-batches` | List blend batches | RoutePlanner, SettlementClerk, LabTech |
| GET | `/recycle-routes/blend-batches/{batchId}` | Get one blend batch | RoutePlanner, SettlementClerk, LabTech |
| POST | `/recycle-routes/blend-batches/{batchId}/start-blending` | Begin blending; compute yield and output | RoutePlanner |
| POST | `/recycle-routes/blend-batches/{batchId}/hold` | Place a batch on quality hold | LabTech |
| POST | `/recycle-routes/blend-batches/{batchId}/resume` | Resume a batch from hold | LabTech |
| POST | `/recycle-routes/blend-batches/{batchId}/release` | Release a batch for sale | LabTech |
| POST | `/recycle-routes/blend-batches/{batchId}/mark-sold` | Mark a batch sold | SettlementClerk |
| POST | `/recycle-routes/blend-batches/{batchId}/cancel` | Cancel a batch (releases tickets) | RoutePlanner |
| POST | `/recycle-routes/spill-incidents` | Log a spill incident | Driver, EHSOfficer |
| GET | `/recycle-routes/spill-incidents` | List spills | RoutePlanner, EHSOfficer, Regulator |
| GET | `/recycle-routes/spill-incidents/{spillId}` | Get one spill | RoutePlanner, EHSOfficer, Regulator |
| POST | `/recycle-routes/spill-incidents/{spillId}/begin-investigation` | Begin investigation | EHSOfficer |
| POST | `/recycle-routes/spill-incidents/{spillId}/remediate` | Mark a spill remediated; compute liability | EHSOfficer |
| POST | `/recycle-routes/spill-incidents/{spillId}/close` | Close a remediated spill | EHSOfficer |
| POST | `/recycle-routes/market-prices` | Publish a market price | Regulator |
| GET | `/recycle-routes/market-prices` | List published market prices | RoutePlanner, SettlementClerk, Regulator, Driver |
| GET | `/recycle-routes/market-prices/{marketPriceId}` | Get one market price | RoutePlanner, SettlementClerk, Regulator, Driver |
| POST | `/recycle-routes/_clock/set_current_utc` | Set the logical clock | RoutePlanner |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the workflows they guard; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 400 Bad Request |
| `ERR_INVALID_STOP_WINDOW` | 400 Bad Request |
| `ERR_ZERO_VOLUME_PICKUP` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_TANK_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_TANK_NOT_FOUND` | 404 Not Found |
| `ERR_DRIVER_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_STOP_NOT_FOUND` | 404 Not Found |
| `ERR_PICKUP_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_MANIFEST_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_BLEND_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_SPILL_NOT_FOUND` | 404 Not Found |
| `ERR_SAMPLE_SCREENING_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_PROSPECT` | 409 Conflict |
| `ERR_CUSTOMER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CUSTOMER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_NO_SERVICEABLE_TANK` | 409 Conflict |
| `ERR_SITE_NOT_ACTIVE` | 409 Conflict |
| `ERR_SITE_HAS_ACTIVE_STOPS` | 409 Conflict |
| `ERR_SITE_STILL_CONTAMINATED` | 409 Conflict |
| `ERR_OPEN_SPILL_EXISTS` | 409 Conflict |
| `ERR_TANK_NOT_PENDING_INSTALL` | 409 Conflict |
| `ERR_TANK_NOT_COMPANY_OWNED` | 409 Conflict |
| `ERR_TANK_NOT_CUSTOMER_OWNED` | 409 Conflict |
| `ERR_TANK_NOT_EMPTY` | 409 Conflict |
| `ERR_TANK_HAS_ACTIVE_STOPS` | 409 Conflict |
| `ERR_TANK_NOT_PENDING_DECOMMISSION` | 409 Conflict |
| `ERR_TANK_NOT_QUARANTINED` | 409 Conflict |
| `ERR_TANK_QUARANTINED` | 409 Conflict |
| `ERR_TANK_OVERFLOW` | 409 Conflict |
| `ERR_DRIVER_SUSPENDED` | 409 Conflict |
| `ERR_DRIVER_NO_HAZMAT` | 403 Forbidden |
| `ERR_ROUTE_NOT_PLANNED` | 409 Conflict |
| `ERR_ROUTE_EMPTY` | 409 Conflict |
| `ERR_ROUTE_NOT_DISPATCHED` | 409 Conflict |
| `ERR_ROUTE_HAS_OPEN_STOPS` | 409 Conflict |
| `ERR_ROUTE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_ROUTE_HAS_COMPLETED_STOPS` | 409 Conflict |
| `ERR_ROUTE_HAS_SUBMITTED_MANIFEST` | 409 Conflict |
| `ERR_ROUTE_NOT_READY_FOR_MANIFEST` | 409 Conflict |
| `ERR_ROUTE_NOT_COMPLETE` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MANIFEST_NOT_SUBMITTED` | 409 Conflict |
| `ERR_STOP_NOT_SCHEDULED` | 409 Conflict |
| `ERR_STOP_NOT_EN_ROUTE` | 409 Conflict |
| `ERR_STOP_NOT_SCREENING` | 409 Conflict |
| `ERR_STOP_NOT_READY_TO_PUMP` | 409 Conflict |
| `ERR_STOP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_STOP_NOT_COMPLETED` | 409 Conflict |
| `ERR_SCREEN_FAILED` | 422 Unprocessable Entity |
| `ERR_VOLUME_EXCEEDS_TANK_LEVEL` | 422 Unprocessable Entity |
| `ERR_VOLUME_ABOVE_MINIMUM` | 409 Conflict |
| `ERR_SITE_OVERRIDE_ACTIVE` | 409 Conflict |
| `ERR_TICKET_NOT_PROVISIONAL` | 409 Conflict |
| `ERR_TICKET_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_TICKET_NOT_DISPUTED` | 409 Conflict |
| `ERR_TICKET_NOT_SETTLED` | 409 Conflict |
| `ERR_TICKET_ALREADY_CONSUMED` | 409 Conflict |
| `ERR_DUPLICATE_CLIENT_REQUEST` | 409 Conflict |
| `ERR_MANIFEST_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_MANIFEST_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_MANIFEST_NOT_DELIVERED` | 409 Conflict |
| `ERR_MANIFEST_NOT_PENDING_AMENDMENT` | 409 Conflict |
| `ERR_FACILITY_SUSPENDED` | 409 Conflict |
| `ERR_FACILITY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_FACILITY_REJECTS_HALOGENATED` | 409 Conflict |
| `ERR_MANIFEST_SCHEDULED_DATE_PAST` | 422 Unprocessable Entity |
| `ERR_BATCH_NOT_PLANNED` | 409 Conflict |
| `ERR_BATCH_NOT_BLENDING` | 409 Conflict |
| `ERR_BATCH_NOT_ON_HOLD` | 409 Conflict |
| `ERR_BATCH_NOT_RELEASED` | 409 Conflict |
| `ERR_BATCH_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SPILL_NOT_OPEN` | 409 Conflict |
| `ERR_SPILL_NOT_UNDER_INVESTIGATION` | 409 Conflict |
| `ERR_SPILL_NOT_REMEDIATED` | 409 Conflict |
| `ERR_SPILL_NO_LIABILITY` | 409 Conflict |
| `ERR_SPILL_HAS_LIABILITY` | 409 Conflict |
| `ERR_INSUFFICIENT_PREPAID_BALANCE` | 402 Payment Required |
| `ERR_OUTSTANDING_BALANCE` | 402 Payment Required |
| `ERR_UNRETURNED_PREPAID_BALANCE` | 402 Payment Required |
| `ERR_PRICE_NOT_PUBLISHED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
