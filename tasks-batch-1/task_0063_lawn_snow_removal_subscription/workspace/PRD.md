# Lawn Snow Subscription API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Lawn Snow Subscription service platform: a seasonal grounds-maintenance system that bundles summer lawn care and winter snow removal into prepaid seasonal contracts. The platform exists to remove two recurring sources of friction for property-service operators. The first is weather reactivity — when a storm drops more than two inches of snow on a service area, plow crews must be dispatched across an entire route automatically, without a dispatcher manually inspecting each property. The second is end-of-season reconciliation — customers prepay a flat seasonal fee, then accrue per-visit surcharges (extra-deep snow, fertilization add-ons) and earn credits (skipped visits, prorated refunds) over the course of a season, and the platform must replay every one of those events in order to produce a single defensible invoice.

Underneath the customer-facing subscription sits an operational layer that the platform treats as first-class. Service routes carry ordered stops; crews are homed on routes; equipment (plows, mowers, spreaders) rotates between routes and accumulates wear with every dispatch until it must be pulled for maintenance. The platform is therefore equal parts workflow orchestrator — driving the cascade from a weather reading through route dispatch, visit completion, and equipment wear — and pricing engine, computing both a live provisional balance during the season and an authoritative finalized invoice when the season closes. Several of these flows are deliberately interdependent: a visit completion does not merely close the visit, it ages the equipment that performed it and may force that equipment offline; a contract suspension does not merely change a status, it silently removes that customer's stops from every future dispatch sweep.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply uniformly across every endpoint described in this document.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is absent, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `Customer`, `DispatchManager`, and `CrewLead`. When a request carries valid headers but the named role is not permitted to perform the requested operation, the system responds with `ERR_FORBIDDEN_ROLE`.

`PlatformAdmin` is an operational superuser whose identity is opaque: when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`, and a `PlatformAdmin` may perform any operation in the system for setup or override. `DispatchManager` is likewise opaque: when `X-User-Role` is `DispatchManager`, `X-User-ID` is an operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. A `DispatchManager` owns routes, weather processing, dispatch, skip approval and rejection, contract suspension, and season close.

`Customer` is an entity-backed role: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a `Customer` compare the resource's owning `customer_id` — directly, or reached through the property or contract chain — to `X-User-ID`. When a `Customer` acts on a contract, property, preference, or skip request that does not resolve to their own `customer_id`, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. `CrewLead` is also entity-backed: when `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the acting `Crew`; the crew completes the visits dispatched to its route.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result set; when omitted it defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. Every paginated response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the total number of matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties

Most resources in this system are "common-field" resources and carry a standard set of server-managed properties: an `id` formatted as a UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits recorded at creation; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and a `version`, an integer that begins at its initial value and increments by one on every mutation of the resource. These common fields apply to the `Customer`, `ServiceContract`, `ServiceProperty`, `CustomerPreference`, `Crew`, `ServiceRoute`, `RouteStop`, `Equipment`, `ServiceVisit`, `SkipRequest`, and `SeasonInvoice` resources.

One resource is deliberately leaner. A `WeatherReading` is an immutable observation: it carries only an `id` and a `created_at`, and it has neither an `updated_at` nor a `version` field. The single mutable bit on a reading — whether it has been processed — is tracked through its own `processed` flag rather than through the common versioning machinery.

### 2.5. Monetary and Score Precision

All monetary amounts in this system are stored and returned as integer cents; there are no fractional-cent values anywhere in the API. Wherever a calculation produces a non-integer intermediate, the rounding method is round half up unless a calculation's own rule states a different per-step treatment. The equipment wear score is likewise an integer, produced by rounding its weighted sum half up. Where a calculation specifies a particular order of rounding — for instance, rounding a daily rate to the cent before multiplying, or summing a subtotal before applying tax once — that order is part of the contract and is described with the calculation in Section 3; it is never acceptable to substitute a sum-then-round result where a round-then-sum result is required, or vice versa.

### 2.6. State Propagation and Cross-Entity Cascades

Many operations in this system mutate more than the resource named in the request. When such a cascade fires, every affected resource is independently mutated: its `updated_at` is refreshed and, where it is a common-field resource, its `version` is incremented. A contract suspension flips route stops out of dispatch eligibility; a contract reactivation flips them back; a visit completion ages the equipment that served it and may push that equipment into a maintenance posture; a season close synthesizes an invoice and debits the customer's wallet. These cascades are specified in full alongside the workflows that trigger them in Section 3. The governing principle is that the platform never leaves a dependent resource in a state inconsistent with the operation that should have moved it — the server performs these secondary transitions automatically, without a separate client request against each affected resource.

### 2.7. Resource Existence and Referential Consistency

For any request that names resources — by an identifier in the path or by a foreign key in the body — the platform validates their existence left to right, in the order they appear, and rejects the first one that does not resolve with `ERR_NOT_FOUND`. Beyond mere existence, the platform enforces referential coherence between related resources: a route stop must point at a property owned by the same customer that owns the route's contracts, and a service visit's contract and route stop must ultimately reference the same property. A request that violates this coherence is rejected with `ERR_PROPERTY_MISMATCH`.

### 2.8. Optimistic Concurrency on Equipment Rotation

Rotating a piece of equipment onto a different route is the one operation in this system guarded by optimistic concurrency control. A rotation request must carry `expected_equipment_version`, a non-optional field whose value is the `version` of the target `Equipment` as the client last observed it. Before applying the rotation, the platform compares `expected_equipment_version` against the equipment's current `version`. If they do not match — because a prior rotation, or a visit-completion wear recompute, has advanced the equipment's `version` since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), so that a client cannot overwrite a route assignment it never saw. No other endpoint in this system accepts or requires a version field; only equipment rotation is OCC-guarded.

### 2.9. Validation Ordering

When a single operation is subject to several checks, the platform evaluates them in a fixed priority order so that the rejection a client receives is deterministic. Authentication comes first: the presence and validity of the `X-User-Role` and `X-User-ID` headers (`ERR_UNAUTHENTICATED`), then whether the acting role is permitted for the operation (`ERR_FORBIDDEN_ROLE`), then, for a `Customer` acting on owned resources, whether `X-User-ID` matches the resource's owning customer (`ERR_NOT_RESOURCE_OWNER`). Existence of every referenced resource is checked next, left to right (`ERR_NOT_FOUND`). Request well-formedness follows — required fields present and correctly typed, enum values legal, and numeric ranges honored (`ERR_INVALID_REQUEST`) — and then uniqueness on create (`ERR_DUPLICATE_RESOURCE`). Only after those structural checks does the platform evaluate state legality (`ERR_INVALID_STATE`) and the domain-specific business rules described in Section 3. The effect of this ordering is that, for example, an unauthenticated caller never learns whether a resource exists, and a malformed body is rejected before any state machine is consulted.

## 3. Business Logic & Workflows

### 3.1. Customers, Properties, and Service Preferences

Everything in the system hangs off a `Customer`, registered by a `PlatformAdmin` with an `email`, a `full_name`, and a `service_zip`. The `email` is the customer's login identity and must be unique and non-empty across all customers; an attempt to register a second customer with an existing email is rejected with `ERR_DUPLICATE_RESOURCE`. The `service_zip` is a five-digit ZIP that pins which weather region applies to the customer. Every new customer starts with a wallet balance, tracked in `wallet_credit_cents`, of zero — this wallet accumulates skip and proration credits over the season and is drawn down against the final invoice at season close.

A `Customer` (or a `PlatformAdmin` acting on their behalf) registers one or more serviced locations as a `ServiceProperty`, supplying the owning `customer_id`, a street `address`, the `lawn_area_sqft` (which must be greater than zero and drives baseline service minutes), and the property's own five-digit `zip`. That property `zip` is what the platform matches against incoming weather readings to decide whether a storm covers the property. Properties can be listed and filtered by their owning `customer_id`.

For each property a `CustomerPreference` record captures how the customer wants the work done. It references the `property_id` it governs and records `grass_height_mm`, the requested cut height in millimetres for lawn visits, which must fall between 20 and 120 inclusive; a value outside that band is rejected with `ERR_INVALID_REQUEST`. Two booleans complete the preference. `fertilization_enabled` defaults to false; when true, lawn visits also perform fertilization and accrue the fertilization add-on described in Section 3.6. `snow_opt_out` also defaults to false; when true, the property is held out of snow auto-dispatch even when a storm crosses the dispatch threshold for its region. Preferences can be listed and filtered by `property_id`.

### 3.2. Seasonal Contracts and Their Lifecycle

A `ServiceContract` binds a customer to a property for one season. It is created — by the `Customer` or a `PlatformAdmin` — with the owning `customer_id`, the `property_id` being serviced, a `season` that is one of `WINTER` or `SUMMER`, a `contract_price_cents` flat seasonal base fee (which must be at least zero), and a `term_months` count of at least one month that serves as the proration baseline for skip credits. An optional `prepaid_deposit_cents` (defaulting to zero, and never negative) records what the customer paid at signing; this deposit is subtracted last when the season is finalized. A freshly created contract is born in `DRAFT` status with its provisional `accrued_balance_cents` running balance at zero. Contracts can be listed and filtered by `customer_id` or `property_id`.

A contract moves through four states: `DRAFT`, `ACTIVE`, `SUSPENDED`, and `CLOSED`, with `CLOSED` terminal. Activation, performed by the `Customer`, takes a contract from `DRAFT` to `ACTIVE`; it is permitted only when the contract is currently in `DRAFT`, and only when the referenced property exists and is owned by the same customer that owns the contract. On this first activation the platform sets the status to `ACTIVE` and seeds `accrued_balance_cents` to the contract's `contract_price_cents`, establishing the provisional balance's starting point. The same activation capability also serves the recovery path: a contract in `SUSPENDED` returns to `ACTIVE`, which is permitted only from `SUSPENDED`, and which re-activates the property's route stops as described below. Both activation paths increment the contract's `version`.

Suspension, performed by a `DispatchManager`, takes an `ACTIVE` contract to `SUSPENDED` and is permitted only from `ACTIVE`. Beyond setting the status, suspension cascades: every `RouteStop` whose `property_id` matches the contract's property has its `active` flag flipped to false, removing it from all future dispatch sweeps; the contract's `version` is incremented. Reactivation reverses this exactly — every `RouteStop` for that property has its `active` flag flipped back to true. Because a contract can go `ACTIVE → SUSPENDED → ACTIVE` repeatedly, this is a recoverable, cyclic-capable path rather than a one-way exit.

The season ends when a `DispatchManager` closes it, taking an `ACTIVE` contract to `CLOSED`. Closing is permitted only when the contract is `ACTIVE` and when no service visit on the contract is currently in `DISPATCHED` state; an attempt to close a season with an open dispatch outstanding is rejected with `ERR_OPEN_DISPATCH_EXISTS`. A successful close drives a deep cascade. First the contract's status is set to `CLOSED`. Then the platform synthesizes a `SeasonInvoice` for the contract by running the finalized billing replay of Section 3.7. Then — as a second-order effect of that invoice — the customer's `wallet_credit_cents` is debited by the amount the invoice consumed, mutating the `Customer` row. Finally the contract's `version` is incremented. The synthesized invoices for a contract can be listed back, as can the contract's service visits.

### 3.3. Routes, Stops, Crews, and the Equipment Pool

The operational backbone is the `ServiceRoute`, created by a `DispatchManager` with a five-digit `region_zip` (the area whose weather triggers the route) and a `daily_capacity_minutes` ceiling greater than zero, above which an overtime tier applies during load computation. A route is born `OPEN` with `last_dispatch_load_minutes` at zero, and it moves among `OPEN`, `DISPATCHED`, and `CLOSED`, with `CLOSED` terminal. A route can be closed from `OPEN` (only from `OPEN`), and a route that has been dispatched can be reopened from `DISPATCHED` back to `OPEN` — but reopening is permitted only when no service visit on the route is still in `DISPATCHED` state.

Each property served by a route is wired in as a `RouteStop`, added by a `DispatchManager` with the parent `route_id`, the `property_id` visited, a `sequence` of at least one that orders the stop within the route (lower runs first, and the sequence is the tie-break for dispatch ordering), a `base_service_minutes` greater than zero that is the stop's baseline service time before any snow-depth multiplier, and an optional `travel_minutes` (defaulting to zero, never negative) of fixed travel time added to the stop's load. A new stop is created `active`. Recall that a stop's `active` flag is what contract suspension and reactivation toggle; an inactive stop is excluded from dispatch sweeps. When a stop is added, the platform confirms its `property_id` resolves to a property consistent with the route's customer; an inconsistent pairing is rejected with `ERR_PROPERTY_MISMATCH`. Stops can be listed and filtered by `property_id`, and a route's stops, homed crews, and assigned equipment can each be listed back through the route.

A `Crew` is created by a `DispatchManager` with a `name` and a `home_route_id` identifying the route it services; a crew tracks its availability through `status`, one of `AVAILABLE`, `ON_DISPATCH`, or `OFF_DUTY`, starting `AVAILABLE`.

Equipment is the platform's wearing asset. Each `Equipment` is registered by a `DispatchManager` with a unique, non-empty `asset_tag`, an `equipment_type` of `PLOW`, `MOWER`, or `SPREADER`, an `age_months` of at least zero, and an optional `assigned_route_id` naming the route it currently sits on (nullable until a first rotation). A duplicate `asset_tag` on creation is rejected with `ERR_DUPLICATE_RESOURCE`. Equipment carries a cluster of wear counters, all server-computed and all starting at zero: `cumulative_runtime_hours` (total runtime across all completed visits using the asset), `runtime_at_last_service_hours` (the snapshot of cumulative runtime taken at the last maintenance reset, which is the baseline for wear scoring), `dispatch_count_since_service` (completed dispatches since the last reset), and `wear_score` (the weighted wear metric). New equipment is created `IDLE` with a `wear_score` of zero, and its `status` moves among `IDLE`, `IN_SERVICE`, `MAINTENANCE_DUE`, and `UNDER_MAINTENANCE`. Equipment can be listed and filtered by `assigned_route_id`.

Rotating equipment onto a different route is a `DispatchManager` operation that supplies a new `assigned_route_id` together with `expected_equipment_version`. It is the OCC-guarded write of Section 2.8: a stale `expected_equipment_version` is rejected with `ERR_STALE_VERSION`. On success the platform sets the new `assigned_route_id`, recomputes the equipment's `wear_score` (per Section 3.5), and increments the equipment's `version`.

### 3.4. Weather Readings and Automatic Snow Dispatch

A `WeatherReading` is recorded by a `DispatchManager` (or a `PlatformAdmin`) with a `region_zip`, a measured `snow_depth_in` of at least zero, and an `observed_at` ISO 8601 UTC timestamp. A reading enters the system with its `processed` flag false. A negative `snow_depth_in` is rejected with `ERR_VALIDATION_RANGE`.

Processing a reading is how the snow-trigger fan-out fires. A `DispatchManager` processes a reading against a named route by supplying the `route_id`. The platform will dispatch only when the reading's measured depth is strictly greater than 2.0 inches — a reading whose `snow_depth_in` is at or below 2.0 produces no dispatch and is rejected with `ERR_SNOW_THRESHOLD_NOT_MET`. A reading may be processed for dispatch at most once; a second attempt against an already-processed reading (its `processed` already true) is rejected with `ERR_READING_ALREADY_PROCESSED`. Processing also requires that the route be `OPEN`; the reading's `region_zip` must match the route's `region_zip`, and the route's owning contracts must be `ACTIVE` for any stop to be dispatchable (an attempt to dispatch against a contract that is not `ACTIVE` is rejected with `ERR_CONTRACT_NOT_ACTIVE`).

When the threshold is met and the route is `OPEN`, processing transitions the route from `OPEN` to `DISPATCHED` and drives a fan-out. The platform computes the route's dispatch load (Section 3.5) and writes it to `last_dispatch_load_minutes`. For every active route stop on the route whose property is not snow-opted-out, the platform creates a `SNOW` service visit and immediately advances it from `SCHEDULED` to `DISPATCHED`, selecting equipment for it under the dispatch rules of Section 3.5. The reading's `processed` flag is set to true, and the route's `status` becomes `DISPATCHED`. Stops belonging to opted-out properties (those whose preference has `snow_opt_out` true) are skipped entirely in this fan-out.

### 3.5. Dispatch, Equipment Selection, and Wear Scoring

A service visit reaches `DISPATCHED` one of two ways: as part of the automatic weather fan-out just described, or by a `DispatchManager` manually dispatching a `SCHEDULED` visit. Either path obeys the same rules. Dispatch is permitted only when the visit is `SCHEDULED` and the owning contract of the visit's stop is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`). Dispatch must then find a piece of equipment to assign: among equipment whose `assigned_route_id` equals the stop's route and whose `status` is either `IDLE` or `IN_SERVICE`, the platform selects the one with the lowest `wear_score`, breaking ties by earliest `created_at`. If no equipment on the route is in `IDLE` or `IN_SERVICE` status — for instance, when the entire pool is `MAINTENANCE_DUE` or `UNDER_MAINTENANCE` — dispatch is rejected with `ERR_NO_EQUIPMENT_AVAILABLE`. On a successful dispatch the visit's `status` becomes `DISPATCHED`, the visit's `equipment_id` is set to the selected asset, that equipment's `status` becomes `IN_SERVICE`, and the crew homed on the stop's route (the crew whose `home_route_id` matches) moves to `ON_DISPATCH`.

Wear scoring is the weighted metric that decides when an asset must come off the line. The score is the sum of three weighted terms, rounded half up to an integer: two times the runtime hours accumulated since the last service, plus five times the number of dispatches since the last service, plus one-half times the equipment's age in months. The runtime-hours-since-service term is the difference between the equipment's `cumulative_runtime_hours` and its `runtime_at_last_service_hours`; the dispatch term is `dispatch_count_since_service`; the age term uses `age_months`. The maintenance threshold is 100: whenever a recompute yields a `wear_score` of 100 or more, the asset is forced into `MAINTENANCE_DUE`.

The platform exposes a forecasting read — an estimated post-completion wear score — for an asset that has an in-flight `DISPATCHED` visit. This estimate answers, "if I complete the visit now, where will the score land?" It is computed exactly like the actual score but on projected counters: it adds the in-flight visit's projected `runtime_hours` to the hours-since-service term and adds one more dispatch to the dispatch term, before completion is applied. The estimate is purely a read; it is never written back to the equipment's stored `wear_score`. The read returns the asset's `equipment_id`, its forecast `estimated_wear_score`, and its current `actual_wear_score` side by side.

### 3.6. Visit Completion, Surcharges, and Provisional Balance

A service visit is the unit of work. Visits are scheduled directly for lawn and fertilization work by a `DispatchManager` (or `PlatformAdmin`) against a `contract_id` and a `route_stop_id`, naming a `service_type` of `LAWN`, `SNOW`, or `FERTILIZATION`, with an optional `snow_depth_in` (the depth recorded at dispatch for snow visits, defaulting to zero and never negative) and an optional `runtime_hours` (the equipment runtime the visit will consume, defaulting to zero and never negative). Snow visits, by contrast, are usually born from the weather fan-out. A new visit starts in `SCHEDULED` and carries a computed `surcharge_cents` of zero until completion. A visit's `status` is one of `SCHEDULED`, `DISPATCHED`, `COMPLETED`, `SKIPPED`, or `CANCELLED`; the latter three are terminal. At creation the platform confirms the visit's contract and route stop reference the same property (otherwise `ERR_PROPERTY_MISMATCH`). A visit created with a negative `snow_depth_in` or `runtime_hours` is rejected with `ERR_VALIDATION_RANGE`. Visits can be listed and filtered by `route_stop_id`, `equipment_id`, or `contract_id`; a `DispatchManager` may also cancel a `SCHEDULED` visit, moving it to `CANCELLED`.

Completion is the `CrewLead`'s action and the system's busiest cascade. A visit may be completed only from `DISPATCHED`, and only when its assigned `equipment_id` is set and that equipment's `status` is still `IN_SERVICE`; an asset pulled into a maintenance posture mid-flight causes completion to be rejected with `ERR_EQUIPMENT_NOT_READY`. A completion request may carry a `runtime_hours` value for the work actually performed. On completion the platform first computes the visit's `surcharge_cents`, then sets the visit's `status` to `COMPLETED`, then ages the equipment, then folds the surcharge into the contract's provisional balance.

The surcharge is the sum of two independent add-ons, in integer cents. A snow component applies only to `SNOW` visits: the platform takes the whole inches of snow over the 2.0-inch baseline — that is, the floor of (`snow_depth_in` minus 2.0) — and, only when that whole-inch overage is positive, adds 500 cents per whole inch over baseline. A reading of exactly 2.0 inches yields no snow surcharge. A fertilization component of 2500 cents applies to any visit whose `service_type` is `FERTILIZATION`, and also to any `LAWN` visit whose property preference has `fertilization_enabled` true. A snow visit with extra depth and a fertilization-enabled lawn are the two ways the surcharge becomes non-zero; the two components are additive when both apply.

Aging the equipment is the cross-entity cascade of completion. The platform adds the visit's `runtime_hours` to the equipment's `cumulative_runtime_hours`, increments its `dispatch_count_since_service` by one, and recomputes its `wear_score` using the actual variant — that is, against the now-incremented counters. If the recomputed `wear_score` is 100 or more, the equipment's `status` flips to `MAINTENANCE_DUE`; otherwise it returns to `IDLE`. Finally the contract's provisional `accrued_balance_cents` is increased by the visit's `surcharge_cents`. This provisional balance is an incremental running figure — base seeded at activation, then surcharges added on each completion and credits subtracted on each skip approval — and it deliberately omits the final tax pass and the wallet and deposit application. It can diverge from the finalized subtotal when visits were completed out of creation order or when a skip was approved after a later visit had already completed; the authoritative figure is computed only at season close.

### 3.7. Skipping Visits and Credit Grants

A `Customer` can ask to skip a scheduled visit by creating a `SkipRequest` against the `visit_id`, with a free-text `reason`. The request is born `PENDING` with a computed `credit_cents` of zero, and its `status` is one of `PENDING`, `APPROVED`, or `REJECTED` (the latter two terminal). A skip request may only target a visit that is in `SCHEDULED` state; a request raised against a visit in any other state is rejected with `ERR_NO_SKIPPABLE_VISIT`. Skip requests can be listed and filtered by `visit_id`.

A `DispatchManager` adjudicates each request. Rejection is permitted only from `PENDING`, sets the request to `REJECTED`, grants no credit, and leaves the referenced visit in `SCHEDULED`. Approval is permitted only when the request is `PENDING` and its referenced visit is still `SCHEDULED`. Approval is a coupled transition: it moves the visit from `SCHEDULED` to `SKIPPED`, computes the request's `credit_cents`, sets the request's `status` to `APPROVED`, adds that credit to the customer's `wallet_credit_cents`, and subtracts the same credit from the contract's provisional `accrued_balance_cents`.

The credit amount depends on the skipped visit's service type. A skipped `SNOW` visit earns a flat credit of 1500 cents. A skipped `LAWN` or `FERTILIZATION` visit earns a prorated daily credit instead: the platform first derives a monthly equivalent of the seasonal base by dividing the contract's `contract_price_cents` by its `term_months`, then derives a daily rate by dividing that monthly figure across 30 billing days and rounding the daily rate half up to the cent, and finally multiplies that rounded daily rate by 3 days — the number of days one lawn skip represents. The rounding happens per day, before the multiplication by three; the platform must not sum first and round once.

### 3.8. Equipment Maintenance Cycle

Once an asset reaches `MAINTENANCE_DUE`, it must be serviced before it can dispatch again. A `DispatchManager` begins maintenance, moving the equipment from `MAINTENANCE_DUE` to `UNDER_MAINTENANCE`; this transition is permitted only from `MAINTENANCE_DUE`. Completing maintenance moves the asset from `UNDER_MAINTENANCE` back to `IDLE` and is permitted only from `UNDER_MAINTENANCE`. The completion is the wear-reset event: the platform snapshots `runtime_at_last_service_hours` to the equipment's current `cumulative_runtime_hours`, resets `dispatch_count_since_service` to zero, recomputes the `wear_score` (which now collapses toward its age-only baseline), and sets the `status` to `IDLE`. Because dispatch refuses any pool with no `IDLE` or `IN_SERVICE` asset, a route whose every asset is `MAINTENANCE_DUE` or `UNDER_MAINTENANCE` cannot be dispatched until at least one asset finishes this cycle.

### 3.9. Season Finalization and Invoicing

Closing a season, described as a contract transition in Section 3.2, is where the finalized invoice is built. The `SeasonInvoice` references the `contract_id` being closed and records a `subtotal_cents`, a `tax_cents`, a `total_due_cents`, and a `status` of `ISSUED`, `PAID`, or `VOID`, starting `ISSUED`. The finalized figures are computed by a full chronological replay rather than read from the provisional running balance.

The replay begins from the contract's `contract_price_cents` as a running total. The platform then walks the contract's `COMPLETED` service visits in ascending `created_at` order and adds each visit's already-finalized `surcharge_cents` to the running total; visits in `SKIPPED`, `CANCELLED`, `SCHEDULED`, or `DISPATCHED` state are excluded from this replay. It then subtracts the sum of `credit_cents` across every `APPROVED` skip request for the contract. The resulting running total is the invoice's `subtotal_cents`. Tax is applied once on that subtotal: `tax_cents` is the subtotal multiplied by a tax rate of 7 percent (0.07), rounded half up a single time on the whole subtotal — never per line. The platform then determines how much wallet credit to apply: the lesser of the customer's `wallet_credit_cents` and the sum of subtotal plus tax. The invoice's `total_due_cents` is the subtotal plus tax, minus that applied wallet amount, minus the contract's `prepaid_deposit_cents`, with the result floored at zero so a fully-prepaid season never produces a negative amount due. The wallet amount actually applied is what the close-season cascade debits from the customer's `wallet_credit_cents`. A finalized invoice can be fetched directly by its id.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and every computed read — return `200 OK`. All request and response bodies follow the envelope of Section 2.2; the precise inputs, side effects, and computed outputs of each operation are described in the Section 3 narratives and are not restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | PlatformAdmin |
| GET | `/customers/{id}` | Fetch a customer | PlatformAdmin, Customer, DispatchManager |
| POST | `/properties` | Create a property for a customer | PlatformAdmin, Customer |
| GET | `/properties/{id}` | Fetch a property | PlatformAdmin, Customer, DispatchManager |
| GET | `/properties` | List properties, filterable by owner | PlatformAdmin, Customer, DispatchManager |
| POST | `/preferences` | Set preferences for a property | PlatformAdmin, Customer |
| GET | `/preferences/{id}` | Fetch a preference record | PlatformAdmin, Customer, DispatchManager |
| GET | `/preferences` | List preferences, filterable by property | PlatformAdmin, Customer, DispatchManager |
| POST | `/contracts` | Create a seasonal contract (DRAFT) | PlatformAdmin, Customer |
| GET | `/contracts/{id}` | Fetch a contract | PlatformAdmin, Customer, DispatchManager |
| GET | `/contracts` | List contracts, filterable by owner or property | PlatformAdmin, Customer, DispatchManager |
| POST | `/contracts/{id}/activate` | Activate a DRAFT or reactivate a SUSPENDED contract | Customer, PlatformAdmin |
| POST | `/contracts/{id}/suspend` | Suspend an ACTIVE contract | DispatchManager, PlatformAdmin |
| POST | `/contracts/{id}/close-season` | Close the season; finalize billing into a SeasonInvoice | DispatchManager, PlatformAdmin |
| GET | `/contracts/{id}/invoices` | List SeasonInvoices for a contract | PlatformAdmin, Customer, DispatchManager |
| GET | `/contracts/{id}/visits` | List ServiceVisits for a contract | PlatformAdmin, Customer, DispatchManager, CrewLead |
| POST | `/routes` | Create a service route | PlatformAdmin, DispatchManager |
| GET | `/routes/{id}` | Fetch a route | PlatformAdmin, DispatchManager, CrewLead |
| POST | `/routes/{id}/reopen` | Reopen a DISPATCHED route | DispatchManager, PlatformAdmin |
| POST | `/routes/{id}/close` | Close an OPEN route | DispatchManager, PlatformAdmin |
| GET | `/routes/{id}/stops` | List RouteStops on a route | PlatformAdmin, DispatchManager, CrewLead |
| GET | `/routes/{id}/crews` | List Crews homed on a route | PlatformAdmin, DispatchManager, CrewLead |
| GET | `/routes/{id}/equipment` | List Equipment assigned to a route | PlatformAdmin, DispatchManager, CrewLead |
| POST | `/route-stops` | Add a stop (property) to a route | PlatformAdmin, DispatchManager |
| GET | `/route-stops/{id}` | Fetch a route stop | PlatformAdmin, DispatchManager, CrewLead |
| GET | `/route-stops` | List route stops, filterable by property | PlatformAdmin, DispatchManager, CrewLead |
| POST | `/crews` | Create a crew homed on a route | PlatformAdmin, DispatchManager |
| GET | `/crews/{id}` | Fetch a crew | PlatformAdmin, DispatchManager, CrewLead |
| POST | `/equipment` | Register an equipment asset | PlatformAdmin, DispatchManager |
| GET | `/equipment/{id}` | Fetch an equipment asset | PlatformAdmin, DispatchManager, CrewLead |
| GET | `/equipment` | List equipment, filterable by assigned route | PlatformAdmin, DispatchManager, CrewLead |
| POST | `/equipment/{id}/rotate` | Rotate equipment onto a different route (OCC-guarded) | DispatchManager, PlatformAdmin |
| POST | `/equipment/{id}/start-maintenance` | Begin maintenance on a MAINTENANCE_DUE asset | DispatchManager, PlatformAdmin |
| POST | `/equipment/{id}/complete-maintenance` | Finish maintenance; reset wear baseline | DispatchManager, PlatformAdmin |
| GET | `/equipment/{id}/wear-estimate` | Estimated post-completion wear for the in-flight visit | PlatformAdmin, DispatchManager, CrewLead |
| POST | `/weather-readings` | Record a weather observation | PlatformAdmin, DispatchManager |
| GET | `/weather-readings/{id}` | Fetch a weather reading | PlatformAdmin, DispatchManager |
| POST | `/weather-readings/{id}/process` | Evaluate a reading for snow auto-dispatch on a route | DispatchManager, PlatformAdmin |
| POST | `/visits` | Schedule a LAWN/FERTILIZATION visit against a contract and stop | PlatformAdmin, DispatchManager |
| GET | `/visits/{id}` | Fetch a visit | PlatformAdmin, DispatchManager, CrewLead, Customer |
| GET | `/visits` | List visits, filterable by route stop, equipment, or contract | PlatformAdmin, DispatchManager, CrewLead |
| POST | `/visits/{id}/dispatch` | Manually dispatch a SCHEDULED visit | DispatchManager, PlatformAdmin |
| POST | `/visits/{id}/complete` | Complete a DISPATCHED visit | CrewLead, PlatformAdmin |
| POST | `/visits/{id}/cancel` | Cancel a SCHEDULED visit | DispatchManager, PlatformAdmin |
| POST | `/skip-requests` | Request to skip a scheduled visit | Customer, PlatformAdmin |
| GET | `/skip-requests/{id}` | Fetch a skip request | PlatformAdmin, DispatchManager, Customer |
| GET | `/skip-requests` | List skip requests, filterable by visit | PlatformAdmin, DispatchManager, Customer |
| POST | `/skip-requests/{id}/approve` | Approve a PENDING skip; grant credit and skip the visit | DispatchManager, PlatformAdmin |
| POST | `/skip-requests/{id}/reject` | Reject a PENDING skip | DispatchManager, PlatformAdmin |
| GET | `/invoices/{id}` | Fetch a season invoice | PlatformAdmin, Customer, DispatchManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROPERTY_MISMATCH` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_NO_EQUIPMENT_AVAILABLE` | 409 |
| `ERR_EQUIPMENT_NOT_READY` | 409 |
| `ERR_READING_ALREADY_PROCESSED` | 409 |
| `ERR_SNOW_THRESHOLD_NOT_MET` | 409 |
| `ERR_OPEN_DISPATCH_EXISTS` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION_RANGE` | 422 |
| `ERR_NO_SKIPPABLE_VISIT` | 409 |
