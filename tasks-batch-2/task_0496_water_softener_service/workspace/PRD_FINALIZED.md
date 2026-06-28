# Water Softener Service API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Water Softener Service API, the back-office platform that runs a residential and light-commercial water-treatment operation in the style of a Culligan-type dealer. The business begins with a water test at the customer's address, recommends and sizes a softening system from the measured chemistry, installs that system as either a purchase or a rental, and then sustains it through years of recurring field service: salt deliveries, scheduled regenerations, reverse-osmosis and ultraviolet cartridge replacements, billing cycles, and warranty repairs. The platform is the single coordination point across four operational silos — field service, route dispatch, billing, and the customer's own self-service — and its central job is to keep the physical state of each installed unit, the financial state of each account, and the scheduled state of each route mutually consistent as work flows between those silos.

Several characteristics of this domain make the orchestration non-trivial. A softener carries two independent health dimensions at once — where it sits in its install-to-decommission lifecycle, and how close it is to needing a regeneration — and these advance on entirely different clocks. Money and physical service are coupled: terminating a rental can spawn a fee invoice that debits an account ledger, a confirmed repair visit emits a charge, and voiding either must compensate the ledger back to exactly where it was. Time matters everywhere — cartridge due dates, warranty coverage windows, billing periods, service-gap spacing — so the platform runs against a controllable logical clock rather than wall-clock time, allowing operators and tests to drive temporal rules deterministically. The remainder of this document defines the global contract every endpoint shares (Section 2), the business workflows that scatter across the service lifecycle (Section 3), the endpoint surface (Section 4), and the catalogue of error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled precisely as follows: `ServiceManager`, `FieldTech`, `Dispatcher`, `BillingClerk`, and `Customer`. A `ServiceManager` is the operations supervisor and a hierarchical superset: it may perform every operation any other role can perform, plus a set of exclusive overrides — decommissioning a system, voiding a service visit, and resolving, denying, or closing warranty claims. A `FieldTech` performs water tests, installs and activates systems, records meter readings, runs regenerations, services route stops, replaces cartridges, triages claims, and confirms visits. A `Dispatcher` owns route planning, stop scheduling, route dispatch, and cartridge evaluation. A `BillingClerk` owns rental contracts and their lifecycle, invoices, and account credit top-ups. A `Customer` is the account holder, who may read their own resources, accept a recommendation, and file a warranty claim.

Two roles are entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that ultimately references a `Customer` compare the resource's owning account's `customer_id` to `X-User-ID`. When `X-User-Role` is `FieldTech`, `X-User-ID` is the `id` of the acting `FieldTech` entity; where a resource references a technician (for example, a `Route`'s assigned `tech_id`), ownership compares that foreign key to `X-User-ID`. The remaining three roles are opaque operator identities. When `X-User-Role` is `ServiceManager`, `Dispatcher`, or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Most primary resources in the system — service accounts, water tests, softener systems, rental contracts, routes, route stops, cartridge schedules, service visits, warranty claims, and invoices — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation to the resource. The `version` field is an integer that begins at its initial value when the resource is created and increments by one on every mutation; it is the basis for the optimistic concurrency mechanism described in Section 2.10.

Two reference entities are deliberately lighter. The `Customer` entity and the `FieldTech` entity carry only an `id` (a server-minted UUID) and a `created_at` timestamp; for these two entities both `updated_at` and `version` are absent, because they are registered once and never mutated through the API. Wherever this document refers to incrementing a resource's `version` or refreshing its `updated_at`, that applies to the ten primary resources, not to `Customer` or `FieldTech`.

### 2.5. Nested Resource Retrieval and Path Validation

The platform is built on flat, peer entities wired together by foreign keys rather than deep URL nesting; the one genuinely nested pair is a route and the stops that belong to it. Wherever an endpoint path contains a resource identifier, that identifier is validated for existence before any business rule runs, and where a path contains more than one identifier the validation proceeds strictly left to right. A request whose first path identifier names a non-existent resource is rejected with `ERR_NOT_FOUND` before any subsequent identifier or body field is examined. Several read endpoints also expose reverse-reachability — listing the cartridge schedules, service visits, or warranty claims attached to a given system, or the stops attached to a given route — and those, too, validate the parent identifier in the path before returning the child collection.

### 2.6. Foreign-Key and Request Validation

Beyond path identifiers, create endpoints carry foreign-key fields in their request bodies. Every such foreign key must reference an existing resource; a body foreign key pointing at a non-existent resource is rejected with `ERR_FK_NOT_FOUND`. Independently, every create and action endpoint validates the shape of its payload: required fields must be present and well-typed, enum-valued fields must carry one of their allowed members, and numeric fields must satisfy their stated ranges. Any such structural violation is rejected with `ERR_INVALID_REQUEST`.

The order in which these checks fire is fixed and consistent across the API. Authentication (`ERR_UNAUTHENTICATED`) is evaluated first, then authorization (`ERR_UNAUTHORIZED`), then existence of path-referenced resources (`ERR_NOT_FOUND`), then existence of body foreign keys (`ERR_FK_NOT_FOUND`), then payload shape and field validity (`ERR_INVALID_REQUEST`), then — for state-changing operations — whether the target resource is in a legal state for the transition (`ERR_INVALID_STATE`), and only then the domain-specific business rules described throughout Section 3. This ordering means an operation that violates several rules at once always surfaces the earliest failure in this list, so a permission failure is never masked by a later state or business check.

### 2.7. Parallel State Dimensions and Hierarchical Consistency

A softener system is unusual in carrying two independent state dimensions that advance separately. The `lifecycle_status` dimension tracks installation and decommissioning and moves through `ORDERED`, `INSTALLED`, `ACTIVE`, and `DECOMMISSIONED`. The `regen_health` dimension tracks the regeneration cycle and moves among `NOMINAL`, `DUE`, and `OVERDUE`. These two dimensions are orthogonal: a system can be `ACTIVE` and simultaneously `NOMINAL`, `DUE`, or `OVERDUE`, and a transition on one dimension does not by itself move the other.

Many operations in this domain mutate more than one resource at once — these are cascades, and every secondary effect is part of the contract, not an optional convenience. A route completion force-skips its unserviced stops; a contract termination can spawn a fee invoice that in turn debits an account ledger; a confirmed billable visit emits an invoice; voiding that visit reverses the invoice and credits the ledger back. Each affected resource is mutated independently: when the system changes any resource as a side effect, it refreshes that resource's `updated_at` and increments its `version`, exactly as if a client had acted on it directly. When this document describes a side effect "on the system" or "on the account," that mutation is real and carries its own version bump.

### 2.8. Monetary Values and Rounding

All monetary amounts in the system — account credit balances, rental rates, invoice amounts, termination fees, visit charges, and claim settlements — are represented and stored as whole integer cents. Where a calculation produces a fractional cent before storage, the result is rounded half up to the nearest whole cent unless a specific calculation states a different rounding point. Several calculations pin a precise rounding order — for example, a daily rental rate is rounded to whole cents before it is multiplied by a day count, not after — and those orderings are stated explicitly in the workflows that use them and must be followed exactly. The account credit ledger is a non-negative quantity: it is floored at zero and never represents a negative balance.

### 2.9. Temporal Rules and the Logical Clock

Every time-dependent rule in the platform — cartridge due dates, warranty coverage windows, invoice due dates, service-gap spacing, contract proration, and early-termination calculations — reads "now" from a single server-controlled logical clock rather than the host wall clock. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it stays at that default and never falls back to wall-clock time. An administrative capability lets an authorized operator advance the logical clock to a supplied instant, after which all temporal evaluations use that instant as "now." This makes due-date, coverage, and aging behavior fully deterministic.

### 2.10. Optimistic Concurrency Control

One operation in the system is guarded by optimistic concurrency: terminating a rental contract. The terminate operation requires the request body to carry `expected_rentalcontract_version`, holding the client's last observed `version` of the target `RentalContract`. Before the termination proceeds, the server compares that value against the contract's current `version`; if they differ, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The motivation is concrete: a suspend or resume cycle legitimately changes the contract's accrual basis and bumps its `version`, so a client that read the contract before such a cycle would compute the wrong early-termination fee. Rejecting the stale-version termination forces the client to re-read the current contract before acting. This field is non-optional on the terminate operation; no other endpoint in the system takes a version field, and none of them perform an OCC check.

## 3. Business Logic & Workflows

### 3.1. Accounts, Customers, and Technicians

The operation begins with two reference registrations. A `Customer` is registered with a `full_name` and a unique `email`. A `FieldTech` is registered with a `full_name` and a `home_zone` naming the default service zone the technician works. Neither carries a mutable lifecycle; both are referenced by other resources thereafter.

A service account is the hub of everything an account holder owns. Opening one requires a `customer_id` identifying the holder, a `property_type`, and a `service_zone`. The `property_type` declares the installation site's water source and scope and must be one of `MUNICIPAL_WHOLE_HOUSE`, `WELL_WHOLE_HOUSE`, or `POINT_OF_USE`. The `service_zone` is the geographic routing zone the address falls in, a non-empty label such as a north or south zone code, and it is the value routes match against when stops are scheduled. On creation the account's `credit_balance_cents` ledger is initialized to 0 and its `standing` is set to `GOOD`. The `standing` field is the account's collections posture: it is `GOOD` while no open invoice has passed its due window and flips to `DELINQUENT` once any open invoice ages past due; it gates whether new rental contracts may be opened. The account also carries a `hardness_gpg` field — the latest accepted water-test hardness reading in grains per gallon — which remains null until the first water test for the account is accepted, at which point it is copied from that test. A `BillingClerk` may top up the ledger directly through an account credit capability that supplies an `amount_cents` to add; that capability increases `credit_balance_cents` by the supplied amount and bumps the account's `version`.

### 3.2. Water Testing and System Recommendation

Field service for a new customer opens with a water test. A `FieldTech` records a test against an account by supplying the `account_id`, the measured `hardness_gpg` in grains per gallon (which must be at least 0), the measured `iron_ppm` dissolved iron in parts per million (at least 0), the `tds_ppm` total dissolved solids in parts per million (at least 0), and the `household_size`, the number of residents, which must be at least 1. A new test is created in `DRAFT` status.

Computing the recommendation advances the test from `DRAFT` to `RECOMMENDED`, and is permitted only while the test is `DRAFT`; an attempt to recommend a test that is not `DRAFT` is rejected as an invalid state transition. Recommendation is idempotent only through this state guard — re-running it from `RECOMMENDED` is rejected rather than silently recomputed. The recommendation sizes the system's grain capacity from the measured chemistry and household demand. First, the effective hardness is the measured `hardness_gpg` plus four grains for every part per million of iron measured in `iron_ppm`; this iron contribution is why a test with any positive iron reading is pushed toward a larger tank than its raw hardness alone would suggest. The daily softening demand in grains is the `household_size` multiplied by 80 gallons per person per day, multiplied by that effective hardness. The required capacity is the daily demand multiplied by a six-day target between regenerations, rounded up to the next whole grain. The recommended capacity, written to `recommended_grain_capacity`, is then the smallest standard tank whose capacity is at least the required capacity, choosing from the standard tank sizes of 16000, 24000, 32000, 40000, 48000, and 64000 grains; if the required capacity exceeds the largest standard tank, the largest tank (64000) is selected. The same step sets `recommended_needs_ro` to true when a reverse-osmosis point-of-use unit is warranted, which is driven purely by total dissolved solids: the flag is true when `tds_ppm` reaches or exceeds the reverse-osmosis threshold and false otherwise.

A `Customer` accepts the recommendation, which advances the test from `RECOMMENDED` to `ACCEPTED` and is permitted only from `RECOMMENDED`. Acceptance has two side effects. It copies the test's `hardness_gpg` onto the owning account's `hardness_gpg`, establishing the account's working hardness basis. And it supersedes any prior accepted test for the same account: any other `WaterTest` for that account currently in `ACCEPTED` transitions to `SUPERSEDED` as a cascade. `SUPERSEDED` is terminal. Importantly, a softener already sized from a now-superseded test keeps its installed `grain_capacity` — superseding the test does not resize an installed unit.

### 3.3. Ordering, Installing, and Operating a Softener System

A softener system is ordered against an accepted test. Creating one requires the `account_id` it will serve, the `source_test_id` naming the `WaterTest` it was sized from, the `acquisition_mode` declaring whether the unit was bought outright or rented (one of `PURCHASE` or `RENTAL`), and the installed `grain_capacity`, which must be at least 16000 grains. A newly ordered system begins with `lifecycle_status` of `ORDERED` and `regen_health` of `NOMINAL`.

Installing the system advances `lifecycle_status` from `ORDERED` to `INSTALLED`. Three preconditions guard the install: the system must currently be `ORDERED`, the source water test must be in `ACCEPTED` status, and the system's `grain_capacity` must exactly equal the source test's `recommended_grain_capacity`. A capacity that does not match the source test's recommended capacity is rejected with `ERR_CAPACITY_MISMATCH`. On a successful install the system's `lifecycle_status` becomes `INSTALLED`, its `install_date` is stamped with the current logical-clock instant, and its operating counters are initialized — `regen_health` to `NOMINAL`, `gallons_since_regen` to 0, and `salt_level_pct` to 100. The `install_date` is null while the system is still `ORDERED`.

Activation advances `lifecycle_status` from `INSTALLED` to `ACTIVE` and is permitted only from `INSTALLED`. Only an `ACTIVE` system may be added to route stops or accrue meter readings. Decommissioning is a `ServiceManager`-only override that advances an `ACTIVE` system to `DECOMMISSIONED`; it is permitted only from `ACTIVE` and only when the system has no rental contract still in `ACTIVE` or `SUSPENDED` status — any such contract must be terminated first. On decommission, every `CartridgeSchedule` for that system ceases accruing and is frozen at its current status. `DECOMMISSIONED` is terminal.

The second, parallel dimension — `regen_health` — is driven by treated-water throughput. A `FieldTech` records a meter reading by supplying `gallons_since_regen`, the treated gallons consumed since the last regeneration; this is permitted while the system is `ACTIVE` and re-evaluates the regeneration health. The capacity of one regeneration cycle in gallons is the system's `grain_capacity` divided by the account's working hardness (the `hardness_gpg` copied onto the account from the accepted test), taking the floor of that division to whole gallons. It is essential that this division uses the account's hardness basis, not the system's original source-test hardness, because the source test may since have been superseded and the two readings can diverge. With that cycle capacity in hand, the regeneration health is set by comparing consumed gallons against it: if `gallons_since_regen` is at least the cycle capacity multiplied by the grace factor of 1.25, the health becomes `OVERDUE`; otherwise if `gallons_since_regen` is at least the cycle capacity, the health becomes `DUE`; otherwise it stays `NOMINAL`. Each boundary is inclusive — reaching the threshold exactly counts as having crossed it. These crossings advance `regen_health` from `NOMINAL` to `DUE` and from `DUE` to `OVERDUE` as throughput accumulates.

Running a regeneration resets the cycle. It is permitted while the system is `ACTIVE`, while `regen_health` is `DUE` or `OVERDUE`, and only when the brine tank holds enough salt; the system enforces a safety floor described in Section 3.7. On a successful regeneration `regen_health` returns to `NOMINAL`, `gallons_since_regen` is reset to 0, the salt level is drawn down (Section 3.7), and a regeneration service visit is created automatically with no charge. This regeneration transition takes `regen_health` from either `DUE` or `OVERDUE` back to `NOMINAL`.

### 3.4. Routes, Stops, and Field Execution

Route work is owned by a `Dispatcher`, who plans a route by supplying the `service_zone` it covers, the `route_date` it runs (a UTC date), the `tech_id` of the assigned technician, and the `capacity_stops` ceiling — the maximum number of stops the route may hold, which must be at least 1. A new route starts in `PLANNED` status with `stop_count` at 0; the running `stop_count` must never exceed `capacity_stops`.

Adding a stop to a planned route is the most heavily validated create in the system. A stop carries the `route_id` it belongs to, the `system_id` of the installed unit serviced, a `stop_type` (one of `SALT_DELIVERY`, `FILTER_SWAP`, `REGEN_SERVICE`, or `INSPECTION`), a `window_start` and `window_end` bounding the appointment window, and an optional `salt_bags_delivered` count of salt bags dropped, which defaults to 0 and must be at least 0 (and is only meaningful for a salt delivery). Several rules guard the add, and they correspond to distinct error codes. The appointment window must be coherent and unobstructed: `window_end` must be strictly after `window_start`, and the new window must not overlap any existing `SCHEDULED` stop already on the same route (the overlap check is buffer-aware); a window that is inverted or that collides with an existing scheduled stop on that route is rejected with `ERR_WINDOW_OVERLAP`. The serviced system must be eligible for that route: the system must be `ACTIVE` and its account's `service_zone` must equal the route's `service_zone`, otherwise the add is rejected with `ERR_ZONE_MISMATCH`. The same system may not be serviced twice in close succession: if any two stops servicing the same system — across any route, not just this one — would fall within 24 hours of each other, the add is rejected with `ERR_SERVICE_GAP_VIOLATION`. And the route must have room: if accepting the stop would push `stop_count` above `capacity_stops`, the add is rejected with `ERR_ROUTE_FULL`. A successful add increments the route's `stop_count` and bumps the route's `version`; the new stop begins in `SCHEDULED` status.

Dispatching a route advances it from `PLANNED` to `DISPATCHED` and requires the route to be `PLANNED` and to have at least one stop. Once dispatched the route is locked and no further stops may be added; its stops remain `SCHEDULED`. Completing a route advances it from `DISPATCHED` to `COMPLETED` and force-skips any straggler stops: every `RouteStop` still in `SCHEDULED` transitions to `SKIPPED` as a cascade, and a skipped stop fires no service side effects. `COMPLETED` and `SKIPPED` are the terminal stop states.

Servicing an individual stop advances it from `SCHEDULED` to `COMPLETED` and is permitted only when the stop is `SCHEDULED`, its parent route is `DISPATCHED`, and the serviced system is `ACTIVE`. Completing a stop fires side effects keyed to its `stop_type`, and each one cascades onto other resources. A `SALT_DELIVERY` stop raises the system's `salt_level_pct` by 25 percentage points for each bag recorded in `salt_bags_delivered`, capped at 100; because salt level participates in regeneration eligibility, that bump may flip a pending regeneration's salt readiness. A `REGEN_SERVICE` stop creates a regeneration service visit and resets the system's `gallons_since_regen` to 0 and `regen_health` to `NOMINAL`; because regeneration draws salt, a regeneration serviced through a stop is also subject to the salt floor of Section 3.7. A `FILTER_SWAP` stop finds the matching cartridge schedule for the system, increments its `replacements_logged`, sets its `last_replaced_at` to now, and sets its status back to `ON_TRACK`. Every successful completion bumps the stop's `version`.

### 3.5. Cartridge Schedules and RO/UV Maintenance

Each installed system can carry one or more cartridge schedules tracking its reverse-osmosis and ultraviolet consumables. A schedule is created with the `system_id` it tracks, a `cartridge_type` (one of `RO_MEMBRANE`, `SEDIMENT_FILTER`, `CARBON_FILTER`, or `UV_LAMP`), an `interval_days` replacement cadence (at least 1 day), and a `last_replaced_at` instant. The due date is the `last_replaced_at` instant plus the `interval_days` cadence. A new schedule begins `ON_TRACK` and has `replacements_logged` at 0.

A `Dispatcher` re-evaluates a schedule against the logical clock to advance its status as time passes. The evaluation reads the current clock instant and compares it to the due date. The schedule enters `DUE_SOON` from `ON_TRACK` once the clock reaches the lead window — that is, once now is at or after the due date minus 14 days and still strictly before the due date. The schedule enters `OVERDUE` from either `ON_TRACK` or `DUE_SOON` once the clock reaches the due date plus a 7-day grace period — that is, once now is at or after the due date plus 7 days. Each evaluation that changes the status sets `status` accordingly and bumps the schedule's `version`.

Replacing a cartridge is a `FieldTech` action that returns a `DUE_SOON` or `OVERDUE` schedule to `ON_TRACK`; it is permitted only when the schedule is `DUE_SOON` or `OVERDUE`. On replacement the schedule's `last_replaced_at` is set to now, its `status` returns to `ON_TRACK`, and `replacements_logged` is incremented; a cartridge-replacement service visit is created as well. (A filter swap performed through a route stop, described in Section 3.4, achieves the same schedule reset through the route-execution path.)

### 3.6. Service Visits and Their Financial Footprint

A service visit is the unit of recorded field work. Visits arise two ways: many are spawned automatically as cascades — by a regeneration, by a regeneration-type or filter-swap route stop, by a cartridge replacement, and by a warranty resolution or close — and others are logged directly. Logging an ad-hoc visit requires the `system_id` serviced, an optional `stop_id` naming the route stop that generated it (null for genuinely ad-hoc visits), a `visit_type` (one of `REGEN`, `CARTRIDGE_REPLACE`, `SALT_REFILL`, `REPAIR`, or `INSPECTION`), a `gallons_treated_reading` meter reading of total gallons treated since the last regeneration at visit time (at least 0), and an optional `billable_cents` charge. A new visit begins in `LOGGED` status. The `billable_cents` field is the labor-plus-parts charge for the visit: it is 0 for routine, rental-covered service and non-zero for out-of-warranty repair.

Confirming a visit advances it from `LOGGED` to `CONFIRMED` and is permitted only from `LOGGED`. If the visit's `billable_cents` is greater than 0, confirmation creates a service-repair invoice that debits the account ledger as a cascade. Voiding a visit is a `ServiceManager` override that advances a `LOGGED` or `CONFIRMED` visit to `VOIDED`; it is permitted only from `LOGGED` or `CONFIRMED`. If a service-repair invoice was created when the visit was confirmed and that invoice is still open, voiding the visit voids that invoice and credits the account ledger back, compensating the confirm cascade so the account's credit balance nets back to its pre-confirm value. `VOIDED` is terminal.

### 3.7. Salt Safety and Brine Levels

A softener cannot regenerate without enough salt in the brine tank, and the platform enforces this as a hard safety floor. The system carries `salt_level_pct`, a brine-tank fill percentage between 0 and 100, initialized to 100 at install. Regeneration — whether triggered directly on the system or through a `REGEN_SERVICE` route stop — requires `salt_level_pct` to be at least 20 percent; an attempt to regenerate below that floor is rejected with `ERR_INSUFFICIENT_SALT`. A successful regeneration consumes salt: it decrements `salt_level_pct` by 30 percentage points, floored at 0. Salt is replenished by salt-delivery stops, which add 25 percentage points per bag delivered, capped at 100, as described in Section 3.4. These two movements — drawing down on regeneration and topping up on delivery — are what make the salt floor a live operational constraint rather than a formality.

### 3.8. Rental Contracts and Their Lifecycle

A rental contract binds an account to a rented unit. Creating one requires the `account_id` billed, the `system_id` of the rented unit, a `monthly_rate_cents` base rate (at least 0), a `term_months` committed minimum term (at least 1 month), and a `start_date` that anchors billing and proration. Three conditions gate the create, and all must hold: the account's `standing` must be `GOOD`, the named system's `acquisition_mode` must be `RENTAL`, and that system must not already carry another contract in `ACTIVE` or `SUSPENDED` status. A create that violates any of these is rejected with `ERR_RENTAL_NOT_ALLOWED`. A new contract begins `ACTIVE`, with `months_billed` at 0 and `early_termination_fee_cents` at 0.

The contract lifecycle is cyclic. A `BillingClerk` may suspend an `ACTIVE` contract, moving it to `SUSPENDED`, after which rental ceases to accrue. A `BillingClerk` may resume a `SUSPENDED` contract back to `ACTIVE`, but only when the account's `standing` is `GOOD`; resumption restores accrual. This active-suspended cycle may repeat any number of times. Each suspend and each resume bumps the contract's `version`.

Terminating a contract is the OCC-guarded operation of Section 2.10: the request carries `expected_rentalcontract_version`, and a mismatch with the contract's live `version` is rejected with `ERR_STALE_VERSION`. Termination is permitted from `ACTIVE` or `SUSPENDED`. On termination the system computes the early-termination penalty. It first determines how many whole billing months have elapsed since `start_date` — the number of days between `start_date` and now divided by 30 days per billing month, taking the floor — and the months remaining is the committed `term_months` minus that elapsed count, floored at 0. If no months remain, the fee is 0 and no termination invoice is created. Otherwise the penalty applies a tiered rate to the remaining commitment: if the months remaining are 3 or fewer the rate is the full rate of 1.0; if they are more than 3 but 6 or fewer the rate is 0.6; if they exceed 6 the rate is 0.4. The raw fee is the months remaining multiplied by `monthly_rate_cents` multiplied by that rate; the stored `early_termination_fee_cents` is that raw amount rounded half up to whole cents and then capped at 50000 cents, with the cap applied after rounding. When the computed fee is greater than 0, termination creates a termination invoice for that amount, and that invoice debits the account's `credit_balance_cents` ledger — termination to fee invoice to ledger debit is a three-level cascade. The contract then becomes `TERMINATED`, which is terminal, and its `version` is bumped.

### 3.9. Warranty Claims, Coverage, and Settlement

A warranty claim is filed against a system. Filing requires the `system_id` the defect was found on, an optional `contract_id` naming the covering rental contract (null for a purchased system still under factory warranty), a `defect_class` (one of `VALVE_FAILURE`, `RESIN_FOULING`, `CONTROL_BOARD`, `LEAK`, or `UV_BALLAST`), and the `reported_at` instant the defect was reported. A claim begins in `FILED`.

Triaging a filed claim advances it from `FILED` to `TRIAGED` and determines coverage. Coverage is a per-defect-class window measured in days from the system's `install_date`: a valve failure or a leak is covered for 1825 days, resin fouling for 3650 days, a control board for 730 days, and a UV ballast for 365 days. The age at report is the number of days between the system's `install_date` and the claim's `reported_at`; the claim's `covered` flag is set true when that age at report is at most the window for its defect class, and false otherwise. The boundary is inclusive — an age exactly equal to the window is still covered.

A triaged claim forks. A `ServiceManager` resolves it by supplying a `resolution` of either `REPAIR` or `REPLACE`, denies it, or — once resolved — closes it. Resolving to `REPAIR` moves a `TRIAGED` claim to `REPAIR`; resolving to `REPLACE` moves it to `REPLACE` but is permitted only when `covered` is true, because an uncovered claim cannot elect a free replacement. Both resolution paths compute the settlement and write it to `settlement_cents`: when the claim is covered the settlement is 0 regardless of defect class; when it is not covered the customer pays the parts-plus-labor cost reduced by an age-based goodwill discount. The parts base is keyed to the defect class — 18000 cents for a valve failure, 12000 for resin fouling, 26000 for a control board, 8000 for a leak, and 9000 for a UV ballast — and labor is a flat 9000 cents. The goodwill discount grows with system age: it is 5 percent for each full 365 days between the system's `install_date` and now, capped at 30 percent. The uncovered settlement is the sum of the parts base and the flat labor, multiplied by one minus that goodwill fraction, rounded half up to whole cents — so older systems pay less. Resolving to `REPAIR` additionally creates a repair service visit whose `billable_cents` equals the computed settlement. Resolving to `REPLACE` does not auto-decommission the defective unit; a replacement system must be ordered separately through the normal ordering path.

Denying a claim moves a `TRIAGED` claim to `DENIED` and is permitted only when `covered` is false. Closing a claim moves it from either `REPAIR` or `REPLACE` to `CLOSED`. On close, if the computed `settlement_cents` is greater than 0, the system creates a service-repair invoice that debits the account as a cascade. The fork-join structure is therefore: `TRIAGED` forks to `REPAIR`, `REPLACE`, or `DENIED`; `REPAIR` and `REPLACE` join at `CLOSED`; and `CLOSED` and `DENIED` are the terminal claim states.

### 3.10. Invoicing, the Account Ledger, and Collections Standing

Invoices are the financial backbone. Issuing an invoice requires the `account_id` billed, an optional `contract_id` (null for one-off service invoices), an optional `supersedes_invoice_id`, the `invoice_kind` (one of `RENTAL_CYCLE`, `SERVICE_REPAIR`, `TERMINATION`, or `PRORATION`), a `period_start` and `period_end` bounding the billing period where `period_end` must be strictly after `period_start`, and an optional `due_offset_days` that defaults to 30 and must be at least 0. A new invoice begins `OPEN` with its `amount_cents` computed at issue. When `supersedes_invoice_id` is present it must reference an invoice currently in `VOID` status; a supersede pointer at any non-void invoice is rejected with `ERR_SUPERSEDE_NOT_VOID`, and only a void invoice may be cited this way.

Rental amounts are prorated two ways from the same contract-and-period inputs, and the `invoice_kind` pins which is used. The billable days within the half-open period from `period_start` up to but not including `period_end` are the days on which the contract was `ACTIVE` — days while the contract was `SUSPENDED` are excluded, counting `period_start` inclusive and `period_end` exclusive. For a `RENTAL_CYCLE` invoice the amount is the flat `monthly_rate_cents` for a whole month, regardless of partial occupancy. For a `PRORATION` invoice the amount is a daily rate times the billable days, where the daily rate is the `monthly_rate_cents` divided by 30 days per billing month, rounded half up to whole cents first, and only then multiplied by the billable-day count — the rounding happens before the multiplication, never after. On the same partial or suspended month, these two variants deliberately produce different amounts from identical contract inputs.

Issuing any invoice debits the account ledger through a single rule. The amount applied is the smaller of the invoice's `amount_cents` and the account's `credit_balance_cents` before the debit; the ledger is reduced by that applied amount, leaving any remainder owed on the open invoice itself, and `credit_balance_cents` is floored at 0 and never goes negative. The exact applied amount is recorded so a later void can reverse it precisely. For a `RENTAL_CYCLE` invoice, issuing also increments the contract's `months_billed` by 1.

An invoice can be re-evaluated, paid, or voided. Re-evaluating an `OPEN` invoice against the clock checks whether it has aged past its due date — that is, whether now is later than `period_end` plus `due_offset_days`; if so the invoice becomes `PAST_DUE` and the owning account's `standing` is driven to `DELINQUENT` as a cascade. Paying an invoice is permitted from `OPEN` or `PAST_DUE`; payment clears the receivable (it does not change `credit_balance_cents`), and if the account then has no other open or past-due invoice beyond its due window, the account's `standing` is restored to `GOOD`. Voiding an invoice is permitted from `OPEN` or `PAST_DUE` and reverses its ledger debit: it credits `credit_balance_cents` back by exactly the amount applied at issue. If the voided invoice was a `RENTAL_CYCLE` invoice, the void also decrements the contract's `months_billed` by 1, so that issuing and then voiding a rental-cycle invoice leaves both the ledger and `months_billed` exactly where they were. And if the voided invoice was the one that had driven the account `DELINQUENT` and no other invoice is past due, the void restores `standing` to `GOOD`. Attempting to pay or void an invoice that is already `PAID` or `VOID` is rejected with `ERR_INVOICE_CLOSED`. The terminal invoice states are `PAID` and `VOID`.

### 3.11. Driving the Logical Clock

For deterministic temporal behavior, an authorized operator may advance the logical clock used by every time-dependent rule. This administrative capability accepts a target instant supplied as `to_iso8601` and moves the clock to that instant; thereafter cartridge evaluations, invoice aging, warranty coverage, service-gap checks, and proration all read "now" from the new value. As stated in Section 2.9, the clock starts at `2026-01-01T00:00:00Z` and never falls back to wall-clock time.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (for example, opening an account, recording a water test, ordering a system, planning a route, adding a stop to a route, creating a schedule, logging a visit, filing a claim, or issuing an invoice) return a `201 Created` status code. Operations that modify an existing resource — every state transition, every evaluation, the credit top-up, and the clock control — return a `200 OK` status code. The request body, response body, and side effects of each endpoint are described in Sections 2 and 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | ServiceManager, BillingClerk |
| GET | `/customers/{id}` | Fetch a customer | ServiceManager, BillingClerk, Customer |
| POST | `/field-techs` | Register a field technician | ServiceManager, Dispatcher |
| GET | `/field-techs/{id}` | Fetch a field technician | ServiceManager, Dispatcher |
| POST | `/accounts` | Open a service account | ServiceManager, BillingClerk |
| GET | `/accounts/{id}` | Fetch a service account | ServiceManager, BillingClerk, Customer |
| GET | `/accounts` | List service accounts | ServiceManager, BillingClerk |
| POST | `/accounts/{id}/credit` | Apply a prepaid credit to the account | BillingClerk, ServiceManager |
| POST | `/water-tests` | Record a water test | FieldTech, ServiceManager |
| GET | `/water-tests/{id}` | Fetch a water test | FieldTech, ServiceManager, Customer |
| GET | `/water-tests` | List water tests | FieldTech, ServiceManager, Customer |
| POST | `/water-tests/{id}/recommend` | Compute a system recommendation | FieldTech, ServiceManager |
| POST | `/water-tests/{id}/accept` | Accept a recommendation | Customer, ServiceManager |
| POST | `/systems` | Order a softener system | ServiceManager, FieldTech |
| GET | `/systems/{id}` | Fetch a softener system | ServiceManager, FieldTech, Customer |
| GET | `/systems` | List softener systems | ServiceManager, FieldTech, Customer |
| POST | `/systems/{id}/install` | Install an ordered system | FieldTech, ServiceManager |
| POST | `/systems/{id}/activate` | Place an installed system in service | FieldTech, ServiceManager |
| POST | `/systems/{id}/decommission` | Remove an active system from service | ServiceManager |
| POST | `/systems/{id}/meter-reading` | Record a treated-gallons reading | FieldTech, ServiceManager |
| POST | `/systems/{id}/regenerate` | Run a regeneration cycle | FieldTech, ServiceManager |
| GET | `/systems/{id}/cartridge-schedules` | List cartridge schedules for a system | ServiceManager, FieldTech, Customer |
| GET | `/systems/{id}/service-visits` | List service visits for a system | ServiceManager, FieldTech, Customer |
| GET | `/systems/{id}/warranty-claims` | List warranty claims for a system | ServiceManager, FieldTech, Customer |
| POST | `/rental-contracts` | Create a rental contract | BillingClerk, ServiceManager |
| GET | `/rental-contracts/{id}` | Fetch a rental contract | BillingClerk, ServiceManager, Customer |
| GET | `/rental-contracts` | List rental contracts | BillingClerk, ServiceManager, Customer |
| POST | `/rental-contracts/{id}/suspend` | Suspend an active contract | BillingClerk, ServiceManager |
| POST | `/rental-contracts/{id}/resume` | Resume a suspended contract | BillingClerk, ServiceManager |
| POST | `/rental-contracts/{id}/terminate` | Terminate a contract (OCC-guarded) | BillingClerk, ServiceManager |
| POST | `/routes` | Plan a route | Dispatcher, ServiceManager |
| GET | `/routes/{id}` | Fetch a route | Dispatcher, ServiceManager, FieldTech |
| GET | `/routes` | List routes | Dispatcher, ServiceManager, FieldTech |
| POST | `/routes/{id}/stops` | Add a stop to a planned route | Dispatcher, ServiceManager |
| GET | `/routes/{id}/stops` | List stops on a route | Dispatcher, ServiceManager, FieldTech |
| POST | `/routes/{id}/dispatch` | Lock and dispatch a route | Dispatcher, ServiceManager |
| POST | `/routes/{id}/complete` | Complete a dispatched route | FieldTech, ServiceManager |
| GET | `/route-stops/{id}` | Fetch a route stop | Dispatcher, ServiceManager, FieldTech |
| GET | `/route-stops` | List route stops | Dispatcher, ServiceManager, FieldTech |
| POST | `/route-stops/{id}/complete` | Service a stop on a dispatched route | FieldTech, ServiceManager |
| POST | `/cartridge-schedules` | Create a cartridge schedule | ServiceManager, FieldTech |
| GET | `/cartridge-schedules/{id}` | Fetch a cartridge schedule | ServiceManager, FieldTech, Customer |
| POST | `/cartridge-schedules/{id}/evaluate` | Re-evaluate a schedule against the clock | Dispatcher, ServiceManager |
| POST | `/cartridge-schedules/{id}/replace` | Replace a due cartridge | FieldTech, ServiceManager |
| POST | `/service-visits` | Log an ad-hoc service visit | FieldTech, ServiceManager |
| GET | `/service-visits/{id}` | Fetch a service visit | FieldTech, ServiceManager, Customer |
| GET | `/service-visits` | List service visits | FieldTech, ServiceManager, Customer |
| POST | `/service-visits/{id}/confirm` | Confirm a logged visit | FieldTech, ServiceManager |
| POST | `/service-visits/{id}/void` | Void a visit and compensate its invoice | ServiceManager |
| POST | `/warranty-claims` | File a warranty claim | Customer, FieldTech, ServiceManager |
| GET | `/warranty-claims/{id}` | Fetch a warranty claim | Customer, FieldTech, ServiceManager |
| GET | `/warranty-claims` | List warranty claims | Customer, FieldTech, ServiceManager |
| POST | `/warranty-claims/{id}/triage` | Triage a filed claim and set coverage | FieldTech, ServiceManager |
| POST | `/warranty-claims/{id}/resolve` | Resolve a triaged claim to repair or replace | ServiceManager |
| POST | `/warranty-claims/{id}/deny` | Deny an uncovered triaged claim | ServiceManager |
| POST | `/warranty-claims/{id}/close` | Close a resolved claim | ServiceManager |
| POST | `/invoices` | Issue an invoice | BillingClerk, ServiceManager |
| GET | `/invoices/{id}` | Fetch an invoice | BillingClerk, ServiceManager, Customer |
| GET | `/invoices` | List invoices | BillingClerk, ServiceManager, Customer |
| POST | `/invoices/{id}/evaluate` | Re-evaluate an open invoice against the clock | BillingClerk, ServiceManager |
| POST | `/invoices/{id}/pay` | Mark an invoice paid | BillingClerk, ServiceManager |
| POST | `/invoices/{id}/void` | Void an invoice and reverse its ledger debit | BillingClerk, ServiceManager |
| POST | `/_clock/set_current_utc` | Set the logical clock | ServiceManager, Dispatcher, BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CAPACITY_MISMATCH` | 422 |
| `ERR_ZONE_MISMATCH` | 422 |
| `ERR_INSUFFICIENT_SALT` | 422 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_SERVICE_GAP_VIOLATION` | 409 |
| `ERR_ROUTE_FULL` | 409 |
| `ERR_RENTAL_NOT_ALLOWED` | 422 |
| `ERR_SUPERSEDE_NOT_VOID` | 422 |
| `ERR_INVOICE_CLOSED` | 409 |
</content>
</invoke>
