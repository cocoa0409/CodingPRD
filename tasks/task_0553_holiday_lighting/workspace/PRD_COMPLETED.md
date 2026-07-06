# Holiday Lighting Installation API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Holiday Lighting Installation platform, a back-office system for a company that designs, installs, services, and stores decorative and permanent architectural lighting (in the style of Trimlight and comparable Christmas-decor operators). The platform must reconcile several very different rhythms of work under a single account of record: a seasonal sales cycle in which a property owner signs a rental or permanent-purchase contract; a design phase in which a footage estimate is quoted and later reconciled against what was actually installed; a field-operations layer of crews, route days, and time-windowed stops that must survive weather delays; a post-season storage operation that parks a customer's lights in bonded bins; and a financing arm that amortizes the cost of a permanent system over monthly installments.

The system's central challenge is temporal and financial consistency. Jobs slip when the weather turns and must cycle back onto the schedule without losing their place in the billing chain. A quoted price and a final price can diverge once a crew measures the real roofline. Cancelling a contract mid-season must unwind the jobs, the booked route stops, and the day-level capacity counters that depend on them, all in one motion. Because dispatchers frequently act on a shared, fast-changing picture of a crew's day, booking a stop is guarded by an explicit version check so that no operator can commit against an availability snapshot that another booking has already invalidated. This API is the authoritative interface for all of these operations, and every rule below is a contract that client applications and downstream billing depend upon.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which the request is made. If the `X-User-Role` header is missing or does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `SalesRep`, `Customer`, `Dispatcher`, `CrewLead`, and `BillingAdmin`. A `SalesRep` sells and manages customers, contracts, and estimates. A `Dispatcher` runs crews, plans route days, books assignments, and schedules field jobs. A `BillingAdmin` handles storage, financing, service classification, and invoicing. A `CrewLead` is a field lead who starts and completes jobs. A `Customer` is a property owner acting on their own resources.

Two of these roles are entity-backed, meaning their `X-User-ID` is compared against persisted data for ownership decisions. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare the resource's `customer_id` to `X-User-ID`. Concretely, accepting a quoted estimate requires that the estimate's `customer_id` equal the caller's `X-User-ID`, and posting a payment requires that the financing plan trace back through its contract to a `customer_id` equal to the caller's `X-User-ID`. When `X-User-Role` is `CrewLead`, `X-User-ID` is the `id` of the acting `Crew`; starting or completing a job requires that the job be reachable through a route assignment whose route day carries a `crew_id` equal to the caller's `X-User-ID`. A violation of either ownership rule is reported as `ERR_UNAUTHORIZED` (HTTP 403).

The remaining three roles — `SalesRep`, `Dispatcher`, and `BillingAdmin` — are opaque operator identities. For these roles, `X-User-ID` is an operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id` when making ownership decisions.

Authorization is evaluated ahead of everything else. The presence and validity of the role header is checked first (yielding `ERR_UNAUTHENTICATED` when it fails), the role's permission for the endpoint is checked second (yielding `ERR_UNAUTHORIZED`), and only then does the system look at path resources, request bodies, and business state. Ownership checks for the two entity-backed roles are applied after basic field validation but before the target's state is inspected.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A supplied `limit` below 1 or above 100 is clamped to the nearest bound (1 or 100), and a negative `offset` is clamped to 0; a `limit` or `offset` that is not a valid integer is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Each list endpoint additionally accepts optional exact-match filter query parameters over selected fields of the listed resource — its foreign-key references (for example `customer_id`, `contract_id`, `crew_id`, `route_day_id`, `job_id`, `storage_bin_id`, `estimate_id`, `financing_plan_id`, or `renewed_from_id`) and, where the resource carries them, its `status` and `service_date` — where a supplied filter narrows the result to resources whose field value equals the given value (compared as strings), applied before pagination; unrecognized query parameters are ignored.

Every list response includes the following fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Test-Driving Time

The system does not read wall-clock time for any business decision. Instead it maintains a single server-wide **logical clock**. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and until an operator explicitly advances it, every timestamp the system stamps — a contract's `signed_date`, a payment's `payment_date` — reads from that default rather than falling back to the host machine's clock. An operator advances the clock by supplying a new instant as `to_iso8601`; the endpoint responds with the current logical time as `current_utc`. All early-bird eligibility comparisons and all persisted system-captured timestamps — including every resource's `created_at` and `updated_at`, a contract's `signed_date`, and a payment's `payment_date` — are taken from this clock at the moment the relevant operation executes; the sole exception is the envelope's `api_request_timestamp` (§2.2), which records the real wall-clock instant the request is handled rather than the logical clock.

### 2.5. Common Resource Properties and Versioning

Every persisted resource in this system — customers, contracts, estimates, crews, route days, route assignments, jobs, service calls, storage bins, storage records, financing plans, payments, and invoices — carries a standard set of system-managed fields:

- `id`: a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp, likewise with three fractional digits, refreshed on every mutation of the resource.
- `version`: an integer that begins at 1 on creation and increments by one on every mutation of the resource, including mutations that are merely the recomputation of a derived field.

Whenever a state transition or a recomputation touches a resource, that resource's `updated_at` is refreshed and its `version` is incremented by one. This holds equally for cascade-driven mutations: when a parent operation reaches down and mutates a child (or a child recomputation bubbles a counter back up to a parent), each affected resource independently advances its own `version` and `updated_at`.

### 2.6. Optimistic Concurrency on Route-Day Booking

Booking a route assignment onto a route day is guarded by optimistic concurrency control. The create-route-assignment request must carry a non-optional field, `expected_route_day_version`, holding the `version` of the target `RouteDay` that the client last observed. Booking validates the day's live capacity and its current set of occupied time windows, both of which change every time another stop is booked onto that day (each such booking increments the route day's `version` and recomputes `booked_stops`). If `expected_route_day_version` does not equal the route day's current `version` — that is, if the day has advanced since the client read it — the client's availability snapshot is stale and the booking is refused with `ERR_STALE_VERSION` (HTTP 412), so it cannot commit against an outdated view. This version check is the final gate in the booking sequence, evaluated only after every existence, field, window-validity, bookability, overlap, and capacity check has already passed. No other endpoint in the system takes a version field; booking is the sole OCC-guarded operation.

### 2.7. Nested Resource Retrieval and Referential Existence

Requests that name a resource by its `id` in the path are validated for existence before any business rule runs. When a path contains more than one identifier, the identifiers are validated left to right, and the first one that does not resolve produces the corresponding not-found error for that resource type. Each entity has its own not-found code — for example a missing customer yields `ERR_CUSTOMER_NOT_FOUND`, a missing contract `ERR_CONTRACT_NOT_FOUND`, a missing estimate `ERR_ESTIMATE_NOT_FOUND`, a missing crew `ERR_CREW_NOT_FOUND`, a missing route day `ERR_ROUTE_DAY_NOT_FOUND`, a missing route assignment `ERR_ROUTE_ASSIGNMENT_NOT_FOUND`, a missing job `ERR_JOB_NOT_FOUND`, a missing service call `ERR_SERVICE_CALL_NOT_FOUND`, a missing storage bin `ERR_STORAGE_BIN_NOT_FOUND`, a missing storage record `ERR_STORAGE_RECORD_NOT_FOUND`, a missing financing plan `ERR_FINANCING_PLAN_NOT_FOUND`, a missing payment `ERR_PAYMENT_NOT_FOUND`, and a missing invoice `ERR_INVOICE_NOT_FOUND`, each returned with HTTP 404.

The same existence rule extends to foreign keys carried in a request body. When a create operation references another resource — a `customer_id`, `contract_id`, `crew_id`, `route_day_id`, `job_id`, `storage_bin_id`, `estimate_id`, or `financing_plan_id` — the referenced resource must exist, and a missing target produces that resource type's not-found code with HTTP 404. Foreign-key existence is checked after path existence and before deeper field and state validation.

### 2.8. Request Validation Ordering

Beyond authentication, authorization, and existence, the system applies a fixed validation order so that clients see a predictable error for a given bad request. After the header checks (priority: authentication, then authorization) and the existence checks (path identifiers, then body foreign keys), the system validates the request body itself: required fields must be present, enum fields must carry one of their allowed values, and integer fields must satisfy their declared bounds. A failure here is reported as `ERR_INVALID_REQUEST` (HTTP 422).

Two further validations sit within this general body-validation tier for the booking endpoint and are applied in a defined order relative to the business checks that follow. The time window supplied for a route assignment must be well-formed: `window_end` must be strictly greater than `window_start`, and if it is not, the request is rejected with `ERR_INVALID_WINDOW` (HTTP 422). Only once the body is well-formed does the system evaluate ownership (for the entity-backed roles), then the target resource's own state, then the cross-entity and business rules described throughout §3, and finally — for booking alone — the optimistic-concurrency version check. In every workflow, a state-precondition failure (the target is not in a state that permits the requested transition) is reported with the appropriate `409` code named in §3, and it is evaluated only after the request has cleared authentication, authorization, existence, field validity, and any applicable ownership check.

### 2.9. Monetary Precision and Rounding

All money in the system is represented in integer cents; there are no fractional-cent values in stored fields or in API responses. Wherever a rule requires rounding — a complexity-multiplied footage cost, a per-line tax amount, an early-bird discount, a prepay fee, an amortized interest allocation — the system uses the **round-half-up** convention (a value exactly halfway between two integers rounds up to the larger). The specific point at which rounding is applied is part of each calculation's contract and is stated precisely in §3; rounding is never applied earlier or later than specified, because the order of rounding and summation changes the result.

### 2.10. Hierarchical Consistency and Cascades

Several operations mutate more than one resource in a single motion, and the platform guarantees that these cascades run to completion so that dependent counters and states never drift. Cancelling a contract, for instance, initiates a chain that reaches from the contract down through its jobs, to those jobs' route assignments, and finally back up to the day-level stop counters — each hop is described with its full set of effects in §3. The governing principle is that no counter derived from child rows (a route day's `booked_stops`, a customer's `outstanding_balance_cents`, a financing plan's `remaining_principal_cents`) is ever left stale after an operation that changes the underlying rows; the system recomputes it as part of the same operation and advances the affected resource's `version` and `updated_at`.

### 2.11. Customer Balance Accounting

Each `Customer` carries a computed `outstanding_balance_cents` field that begins at 0. It is defined as the sum of `total_cents` across that customer's invoices whose `status` is `ISSUED`; invoices in `VOID` or `PAID` status are excluded from the sum. This balance is recomputed every time an invoice is created and every time an invoice is voided, so a customer's balance always reflects only their currently outstanding, issued invoices.

## 3. Business Logic & Workflows

### 3.1. Customers and the Seasonal Contract Lifecycle

A `SalesRep` opens the relationship by registering a property owner, supplying the owner's `name`, the `service_address` of the property to be lit, and the total measured `roofline_feet` of that property (a non-negative integer). A newly registered customer starts in `ACTIVE` account `status` (the alternative being `INACTIVE`) and with an `outstanding_balance_cents` of 0. Any role may fetch a customer to read back its computed balance.

Against a customer, a `SalesRep` drafts a **seasonal contract**, providing the `customer_id` it serves, a `contract_type` of either `SEASONAL_RENTAL` (a rental of seasonal lights) or `PERMANENT_PURCHASE` (purchase of a permanent architectural system), the `season_year` the agreement covers, the `base_season_fee_cents` before any adjustment, and the `early_bird_cutoff` instant. Optionally the rep marks `storage_included` (whether off-season storage of the customer's lights is bundled, defaulting to not included) and a `storage_surcharge_cents` to be added when storage is bundled (defaulting to 0). A contract is born in `DRAFT` `status`; its `signed_date`, `early_bird` flag, `subtotal_cents`, `discount_cents`, and `contract_price_cents` are all still unset or zero, and its `renewed_from_id` is empty for a first-season contract.

Signing a draft advances the contract from `DRAFT` to `ACTIVE` and is permitted only when the contract is currently in `DRAFT`; a sign attempt against any other state is rejected with `ERR_CONTRACT_NOT_SIGNABLE`. At sign time the system captures `signed_date` from the logical clock and prices the contract in a strictly pinned order. First it fixes the pre-discount `subtotal_cents` as the `base_season_fee_cents` plus, only when `storage_included` is true, the `storage_surcharge_cents` (and plus nothing otherwise). Second it sets the `early_bird` flag to true exactly when the captured `signed_date` is on or before the `early_bird_cutoff`, treating the cutoff instant itself as still eligible (an inclusive boundary), and false otherwise. Third it selects a discount rate from a tier keyed on the pre-discount `subtotal_cents`, never on the final price: if the contract is not early-bird the rate is zero; otherwise, when the subtotal is at least 100000 cents the rate is ten percent, when the subtotal is at least 50000 cents (but below the higher tier) the rate is five percent, and when the subtotal is below 50000 cents the rate is zero even for an early-bird contract. Fourth it computes `discount_cents` as the subtotal multiplied by that rate, rounded half up to whole cents (zero when not early-bird). Finally it sets `contract_price_cents` to `subtotal_cents` minus `discount_cents`. Signing increments the contract's `version`.

Renewing carries a relationship into the next season. A `SalesRep` may renew a contract only while it is `ACTIVE`; a renew attempt against any other state is rejected with `ERR_CONTRACT_NOT_RENEWABLE`. Renewal moves the prior contract from `ACTIVE` to `RENEWED` (a terminal state for it) and, as its side effect, creates a brand-new contract for the next season in `DRAFT` status whose `renewed_from_id` points back to the prior contract's `id` and which inherits the same `customer_id` and `contract_type`. The renewal call supplies the next season's `season_year`, `base_season_fee_cents`, and `early_bird_cutoff`, and optionally `storage_included` and `storage_surcharge_cents`; the newly created next-season draft is what the operation returns. The prior contract's `version` is incremented by the transition.

Cancelling ends a contract early and unwinds its field commitments. Cancellation is available to a `SalesRep` or a `BillingAdmin` and is permitted only while the contract is `ACTIVE` (a cancel attempt against any other state is rejected with `ERR_CONTRACT_NOT_ACTIVE`). It moves the contract from `ACTIVE` to `CANCELLED` (terminal) and increments the contract's `version`. As the first hop of a three-hop cascade, every job belonging to this contract whose status is `SCHEDULED` or `RESCHEDULED` is transitioned to `CANCELLED`; the second and third hops of that cascade — the release of those jobs' route assignments and the correction of the affected route days' stop counters — are described in §3.4, and they run as part of this same cancellation. Beyond cancellation and renewal, a contract may also reach `COMPLETED` at natural season closeout; `COMPLETED` is a terminal state.

### 3.2. Design Estimates and Footage Pricing

A `SalesRep` prepares a design estimate for a customer, supplying the `customer_id` the design is for, a `product_line` of either `SEASONAL` or `PERMANENT`, the designer's projected `estimated_footage` (a non-negative integer of lit linear feet), and a `roofline_complexity` bucket of `SIMPLE`, `MODERATE`, or `COMPLEX`. Optionally the rep attaches a `contract_id` (an estimate may sit unattached while still in draft) and an `accessory_count` for add-ons such as timers, stakes, and wreaths, defaulting to 0. An estimate opens in `DRAFT` `status`; its `quoted_total_cents`, `measured_footage`, and `final_total_cents` are all unset until the relevant milestone.

Quoting prices the design from the projected footage. A `SalesRep` moves an estimate from `DRAFT` to `QUOTED`, permitted only when the estimate is in `DRAFT`; a quote attempt against any other state is rejected with `ERR_ESTIMATE_NOT_DRAFT` (HTTP 409). The quoted price is a tiered footage calculation written to `quoted_total_cents`. It begins from a base that depends on the product line: 15000 cents for a `SEASONAL` design, or 40000 cents for a `PERMANENT` design. It then charges the lit footage across three tiers: the first 100 feet at 300 cents per foot, the next 100 feet (those from the 101st through the 200th) at 250 cents per foot, and every foot beyond 200 at 200 cents per foot. The sum of those three tier charges is the raw footage cost, which is then multiplied by a complexity factor — 1.00 for `SIMPLE`, 1.15 for `MODERATE`, or 1.30 for `COMPLEX` — with the result of that single multiplication rounded half up to whole cents (rounding is applied only to the multiplied footage cost, not to the base or the accessories). Separately, the accessory cost is the `accessory_count` multiplied by 1200 cents each. The quoted total is the base plus the rounded complexity-adjusted footage cost plus the accessory cost. For the quoted variant, the footage that drives the tiers is the `estimated_footage`.

Acceptance is a customer's act. The owner named on the estimate accepts a quoted estimate, moving it from `QUOTED` to `ACCEPTED`; this is permitted only while the estimate is in `QUOTED` (otherwise `ERR_ESTIMATE_NOT_QUOTED`), and the acting `Customer`'s `X-User-ID` must equal the estimate's `customer_id` or the request is rejected as unauthorized. Acceptance increments the estimate's `version`. An estimate may also reach `REJECTED` when a quote is declined; `REJECTED` is terminal.

The final reconciliation happens automatically when the installation is done. When a completed install job is linked to an accepted estimate, the estimate advances from `ACCEPTED` to `INVOICED` (terminal) as a side effect of that completion: the estimate's `measured_footage` is set to the job's actually installed footage, and its `final_total_cents` is recomputed using the very same tiered footage formula and the same base, complexity factor, and accessory charge as the quote — except that the footage driving the tiers is now the `measured_footage` rather than the projection. Whenever the measured footage differs from the estimated footage, the final total diverges from the quoted total. This transition increments the estimate's `version`.

### 3.3. Crews, Route Days, and Booking Stops

A `Dispatcher` builds the field-operations backbone. First the dispatcher creates a **crew**, giving it a `name`, a `home_zone` it dispatches from, a `daily_stop_capacity` of at least one stop per day, and optionally an `active` flag (whether the crew can be assigned route days) that defaults to true.

The dispatcher then plans a **route day** for a crew by supplying the `crew_id`, the `service_date` the crew is dispatched, the `zone` served that day, and a hard `max_stops` cap of at least one. A route day opens in `PLANNED` `status`. It exposes a computed `booked_stops` counter, defined as the number of route assignments on this day whose status is `BOOKED` or `DISPATCHED`; that counter starts at 0 and is recomputed whenever an assignment on the day is created, released, or dispatched.

Booking a **route assignment** places a job into a time window on a route day. The dispatcher supplies the `route_day_id`, the `job_id` to be worked, the on-site window bounds `window_start` and `window_end` (a half-open interval whose end is exclusive), and the `expected_route_day_version` described in §2.6. A new assignment opens in `BOOKED` `status`. The booking sequence, after existence and field checks, proceeds in a fixed order. The window must be well-formed, with `window_end` strictly after `window_start`, or the request fails with `ERR_INVALID_WINDOW`. The referenced job must be bookable — its status must be `SCHEDULED` or `RESCHEDULED`; a job that is `CANCELLED`, `COMPLETED`, or `IN_PROGRESS` cannot be booked onto a day, and such an attempt is rejected with `ERR_JOB_NOT_BOOKABLE`. The proposed window must not overlap any other `BOOKED` or `DISPATCHED` window already on the same route day; because the interval is half-open, two windows that merely touch (one ending exactly when the next begins) do not overlap, but any true overlap is rejected with `ERR_WINDOW_OVERLAP`. The day must still have room, meaning its `booked_stops` must be strictly less than its `max_stops` before this assignment is added; a full day is rejected with `ERR_ROUTE_DAY_FULL`. Finally the optimistic-concurrency check runs: a stale `expected_route_day_version` yields `ERR_STALE_VERSION`. When all checks pass, the assignment is created in `BOOKED`, the route day's `booked_stops` is recomputed upward, and the route day's `version` is incremented.

Dispatching a route day releases its crew for the day. A `Dispatcher` moves a route day from `PLANNED` to `DISPATCHED`, permitted only while it is `PLANNED` (otherwise `ERR_ROUTE_DAY_NOT_PLANNED`); as a side effect, every assignment on that day currently in `BOOKED` is transitioned to `DISPATCHED`, and the route day's `version` is incremented. Because both `BOOKED` and `DISPATCHED` assignments count toward `booked_stops`, promoting the assignments does not change the day's stop count. A route day may later reach `CLOSED` at end-of-day closeout; `CLOSED` is terminal. Each promoted assignment's `version` is incremented as it moves to `DISPATCHED`.

### 3.4. Work Orders: Installs, Takedowns, Service, and the Weather Cycle

A `Dispatcher` opens a **job** — a field work order — against a contract by supplying the `contract_id` it belongs to, a `job_type` of `INSTALL`, `TAKEDOWN`, or `SERVICE`, and the target `scheduled_date`. For an install, the dispatcher also supplies the `estimate_id` of the accepted design; takedown and service jobs carry no estimate. Creating a job requires the parent contract to be `ACTIVE`; an attempt against a non-active contract is rejected with `ERR_CONTRACT_NOT_ACTIVE`. A job opens in `SCHEDULED` `status`, with `completed_footage` unset and a `reschedule_count` of 0.

Weather drives a cyclic hold-and-rebook loop. When conditions force a delay, a `Dispatcher` places a scheduled job on weather hold, moving it from `SCHEDULED` to `RESCHEDULED` (permitted only while `SCHEDULED`, otherwise `ERR_JOB_NOT_SCHEDULED`) and incrementing its `version`. To put the held job back on the calendar, the dispatcher reschedules it, which moves it from `RESCHEDULED` back to `SCHEDULED` (permitted only while `RESCHEDULED`, otherwise `ERR_JOB_NOT_HELD`); this sets the job's `scheduled_date` to the supplied `new_scheduled_date`, increments the `reschedule_count` by one, and increments the `version`. A job may cycle through this loop any number of times, each pass adding one to its reschedule count.

Starting and completing a job are the `CrewLead`'s actions and are gated on the field schedule. A crew lead starts a job, moving it from `SCHEDULED` to `IN_PROGRESS`, only when three conditions hold: the job is in `SCHEDULED` (otherwise `ERR_JOB_NOT_SCHEDULED`); there exists a route assignment for this job whose route day is in `DISPATCHED` status (otherwise `ERR_ROUTE_DAY_NOT_DISPATCHED`); and the acting crew lead owns that route day's crew, meaning the route day's `crew_id` equals the caller's `X-User-ID`. Starting increments the job's `version`. The same crew lead completes a job, moving it from `IN_PROGRESS` to `COMPLETED`, only while it is `IN_PROGRESS` (otherwise `ERR_JOB_NOT_IN_PROGRESS`) and, again, only when they own the route day's crew. For an install, `completed_footage` must be supplied at completion and is recorded on the job; a missing footage on an install completion is an invalid request. When the completed job is an install that carries an `estimate_id`, completion drives the linked estimate from `ACCEPTED` to `INVOICED` and recomputes its final total from the measured footage, exactly as described in §3.2. Completion increments the job's `version`.

Cancelling a job unwinds its bookings, and this is the second and third hops of the contract-cancellation cascade as well as a standalone dispatcher action. A `Dispatcher` cancels a job from `SCHEDULED` or `RESCHEDULED` to `CANCELLED`; an attempt from any other state is rejected with `ERR_JOB_NOT_CANCELLABLE`. As the cascade's second hop, every route assignment for this job whose status is `BOOKED` or `DISPATCHED` is transitioned to `RELEASED`. As the third hop, each such release recomputes its route day's `booked_stops` downward and refreshes that route day's `updated_at`. The cancelled job's `version` is incremented, as is the `version` of every assignment released and every route day whose counter is corrected. This same cancel-and-release chain is exactly what the contract cancellation of §3.1 triggers for each of its scheduled or held jobs.

### 3.5. Weather and Repair Service Calls

A `Customer` or a `BillingAdmin` opens a **service call** to report a problem, supplying the `contract_id` the service pertains to, a free-text `reported_issue`, a root-cause `cause` of `WEATHER`, `DEFECT`, or `VANDALISM`, and optionally a `service_fee_cents` (defaulting to 0) that will be billed if the visit turns out to be chargeable. A service call opens in `OPEN` `status`, with its `classification` and `job_id` unset.

A `BillingAdmin` classifies an open call, moving it from `OPEN` to `CLASSIFIED` (permitted only while `OPEN`) and recording the supplied `classification` as either `WARRANTY` (covered) or `BILLABLE` (chargeable); this is the branch point that later governs whether the visit generates an invoice. Classification increments the call's `version`.

A `Dispatcher` schedules a classified call, moving it from `CLASSIFIED` to `SCHEDULED`, permitted only while the call is `CLASSIFIED` and only while the parent contract is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`). Scheduling spawns a new service job: a job with `job_type` `SERVICE`, the same `contract_id` as the call, and the supplied `scheduled_date`, created in `SCHEDULED` status, and the call's `job_id` is set to point at that new job. The call's `version` is incremented. Any classify, schedule, or resolve attempted from the wrong service-call state is reported as `ERR_SERVICE_CALL_INVALID_STATE`.

A `BillingAdmin` resolves a scheduled call, moving it from `SCHEDULED` to `RESOLVED` (permitted only while `SCHEDULED`), and here the two classification branches diverge with equal weight. On the `BILLABLE` branch, resolution runs a two-hop cascade: first it creates an invoice in `ISSUED` status with `source_type` `SERVICE`, a `customer_id` taken from the call's contract, a `job_id` equal to the call's `job_id`, a single line item whose `amount_cents` equals the call's `service_fee_cents` and whose `taxable` flag is false, and a `tax_rate_bps` of 0; then it recomputes the customer's `outstanding_balance_cents`. On the `WARRANTY` branch, resolution creates no invoice and leaves the customer's `outstanding_balance_cents` unchanged. Either way, the call's `version` is incremented on resolution.

### 3.6. Off-Season Storage of Customer Lights

A `BillingAdmin` provisions a **storage bin** by supplying its physical `bin_code`, its `warehouse_zone`, and optionally a `buffer_days` value (defaulting to 0) that mandates an idle cleaning gap between two occupancies of the same bin.

To park a customer's lights, a `BillingAdmin` creates a **storage record** with the `contract_id` whose lights are stored, the `storage_bin_id` holding them, and the occupancy dates `stored_from` (the inclusive first day) and `stored_until` (the inclusive last day) — a closed interval on both ends. A record opens in `STORED` `status`. Before a record is created, the system enforces bin exclusivity with buffer: the proposed closed occupancy interval, inflated by the bin's `buffer_days` on both the leading and trailing side, must not collide with any other currently `STORED` occupancy of the same bin. A collision within that buffered window is rejected with `ERR_BIN_OCCUPIED`.

A `BillingAdmin` retrieves stored lights by moving a record from `STORED` to `RETRIEVED`, permitted only while the record is `STORED` (otherwise `ERR_STORAGE_RECORD_NOT_STORED`) and only while the parent contract is `ACTIVE`, since lights are released only against a live contract (otherwise `ERR_CONTRACT_NOT_ACTIVE`). Retrieval increments the record's `version`. A record may also reach `DISPOSED` when unclaimed lights are disposed of; both `RETRIEVED` and `DISPOSED` are terminal.

### 3.7. Financing a Permanent System

For a permanent-purchase contract, a `BillingAdmin` originates a **financing plan** by supplying the `contract_id` being financed, the `original_principal_cents` financed at origination (at least one cent), the `apr_bps` annual rate in basis points (for example 1000 basis points is ten percent), and the `term_months` number of monthly installments (at least one). At origination the plan computes its simple-interest cost over the term: `total_interest_cents` is the original principal multiplied by the annual rate — the `apr_bps` divided by 10000 — multiplied by the term expressed in years, which is `term_months` divided by 12, with the product rounded half up to whole cents. The `monthly_payment_cents` is the sum of the original principal and that total interest, divided by the number of term months, rounded half up to whole cents. The `remaining_principal_cents` begins equal to `original_principal_cents`. A plan opens in `ACTIVE` `status`.

A `Customer` or a `BillingAdmin` posts a **payment** against the plan by supplying only the `amount_cents` (at least one cent); when the caller is a `Customer`, they must own the plan through its contract's customer. Each posted payment splits into a level interest allocation and a principal reduction. The `interest_portion_cents` is the plan's `total_interest_cents` divided by its `term_months`, rounded half up to whole cents — the same interest amount on every payment. The `principal_portion_cents` is the payment's `amount_cents` minus that interest portion, and it is the amount applied against the balance. Posting is refused if it would overpay: the `principal_portion_cents` must not exceed the plan's current `remaining_principal_cents`, and an overpayment is rejected with `ERR_OVERPAYMENT`. Posting is allowed only while the plan is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`). A successful payment is created in `POSTED` `status` with its `payment_date` captured from the logical clock, and the plan's `remaining_principal_cents` is reduced by the principal portion. When that reduction brings `remaining_principal_cents` to exactly zero, the plan automatically transitions from `ACTIVE` to `PAID_OFF` (terminal). A plan may also reach `DEFAULTED` on delinquency; `DEFAULTED` is terminal.

Reversing a payment compensates the balance. A `BillingAdmin` reverses a payment, moving it from `POSTED` to `REVERSED` (permitted only while the payment is `POSTED`, otherwise `ERR_PAYMENT_NOT_POSTED`) and only while the parent plan is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`); as the compensating action, the plan's `remaining_principal_cents` is increased by the reversed payment's `principal_portion_cents`. Reversal increments the payment's `version`.

A payoff quote reports two settlement paths side by side and mutates nothing. It first counts the plan's `POSTED` payments and derives `remaining_installments` as the plan's `term_months` minus that posted count. On the scheduled path, `scheduled_remaining_cents` is the plan's `monthly_payment_cents` multiplied by the remaining installments, carrying all future interest. On the early path, `early_payoff_cents` is the plan's current `remaining_principal_cents` plus a prepay fee of two percent of that remaining principal — the remaining principal multiplied by 200 basis points divided by 10000, rounded half up to whole cents. Because the early figure retires principal now and rebates future interest while adding only the fee, it is strictly lower than the scheduled figure whenever the carried interest exceeds the fee. The quote response reports `scheduled_remaining_cents`, `early_payoff_cents`, the plan's `remaining_principal_cents`, and `remaining_installments`.

### 3.8. Invoicing and Customer Balances

A `BillingAdmin` issues an **invoice** directly by supplying the billed `customer_id`, a `source_type` of `INSTALL`, `STORAGE`, `SERVICE`, or `MANUAL`, and the `line_items` array, where each line carries a `description`, an `amount_cents`, and a `taxable` boolean. Optionally the admin supplies a `tax_rate_bps` in basis points (defaulting to 0) and a `job_id` linking the invoice to a job (null for a manual invoice). At creation the invoice computes three figures in a pinned order. The `subtotal_cents` is the sum of `amount_cents` across all line items. The `tax_cents` is computed per line and then summed: for each line whose `taxable` flag is true, the system rounds half up the line's `amount_cents` multiplied by the `tax_rate_bps` and divided by 10000, and the invoice tax is the sum of those per-line rounded amounts — rounding is applied independently to each taxable line before summation, never once over the aggregate. The `total_cents` is the subtotal plus the tax. An invoice opens in `ISSUED` `status`, and its creation recomputes the billed customer's `outstanding_balance_cents`. The same line-item subtotal, per-line tax rounding, and total logic governs the invoice that a billable service-call resolution generates in §3.5.

Voiding an invoice removes it from the customer's outstanding balance. A `BillingAdmin` voids an invoice, moving it from `ISSUED` to `VOID` (permitted only while `ISSUED`, otherwise `ERR_INVOICE_NOT_ISSUED`); the void recomputes the customer's `outstanding_balance_cents` so that the voided invoice no longer counts, and it increments the invoice's `version`. An invoice may also reach `PAID` when payment is received; both `PAID` and `VOID` are terminal, and both `PAID` and `VOID` invoices are excluded from the outstanding-balance sum, which counts only `ISSUED` invoices.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code; operations that modify or transition an existing resource return a `200 OK` status code. The one exception among transition endpoints is contract renewal, which returns `201 Created` because its defining effect is the creation of the new next-season contract that it returns. The logical-clock endpoint returns `200 OK`. Request bodies, response bodies, and side effects for each endpoint are specified in the narrative of §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | SalesRep, Dispatcher, BillingAdmin |
| POST | `/customers` | Register a property owner | SalesRep |
| GET | `/customers/{id}` | Fetch a customer with computed balance | SalesRep, Dispatcher, BillingAdmin, CrewLead, Customer |
| POST | `/contracts` | Create a draft seasonal or permanent contract | SalesRep |
| POST | `/contracts/{id}/sign` | Sign a draft contract; compute early-bird pricing | SalesRep |
| POST | `/contracts/{id}/renew` | Renew an active contract into a new draft | SalesRep |
| POST | `/contracts/{id}/cancel` | Cancel an active contract; cascade to jobs | SalesRep, BillingAdmin |
| GET | `/contracts/{id}` | Fetch a contract | SalesRep, Dispatcher, BillingAdmin, Customer |
| GET | `/contracts` | List contracts | SalesRep, Dispatcher, BillingAdmin, Customer |
| POST | `/estimates` | Create a draft design estimate | SalesRep |
| POST | `/estimates/{id}/quote` | Compute the quoted total | SalesRep |
| POST | `/estimates/{id}/accept` | Accept a quoted estimate | Customer |
| GET | `/estimates/{id}` | Fetch an estimate | SalesRep, BillingAdmin, Customer, Dispatcher |
| GET | `/estimates` | List estimates | SalesRep, BillingAdmin, Customer, Dispatcher |
| POST | `/crews` | Create an install crew | Dispatcher |
| POST | `/route-days` | Plan a crew's route day | Dispatcher |
| POST | `/route-days/{id}/dispatch` | Dispatch a planned route day | Dispatcher |
| GET | `/route-days/{id}` | Fetch a route day | Dispatcher, SalesRep, BillingAdmin, CrewLead |
| GET | `/route-days` | List route days | Dispatcher, SalesRep, BillingAdmin, CrewLead |
| POST | `/route-assignments` | Book a job onto a route-day time window | Dispatcher |
| GET | `/route-assignments/{id}` | Fetch a route assignment | Dispatcher, SalesRep, BillingAdmin, CrewLead |
| GET | `/route-assignments` | List route assignments | Dispatcher, SalesRep, BillingAdmin, CrewLead |
| POST | `/jobs` | Create a work order against an active contract | Dispatcher |
| POST | `/jobs/{id}/weather-hold` | Put a scheduled job on weather hold | Dispatcher |
| POST | `/jobs/{id}/reschedule` | Re-book a held job on a new date | Dispatcher |
| POST | `/jobs/{id}/start` | Start a job (requires a dispatched route day) | CrewLead |
| POST | `/jobs/{id}/complete` | Complete a job; install finalizes the estimate | CrewLead |
| POST | `/jobs/{id}/cancel` | Cancel a scheduled/held job; release assignments | Dispatcher |
| GET | `/jobs/{id}` | Fetch a job | Dispatcher, SalesRep, BillingAdmin, CrewLead, Customer |
| GET | `/jobs` | List jobs | Dispatcher, SalesRep, BillingAdmin, CrewLead, Customer |
| POST | `/service-calls` | Open a weather/repair service call | Customer, BillingAdmin |
| POST | `/service-calls/{id}/classify` | Classify the call warranty or billable | BillingAdmin |
| POST | `/service-calls/{id}/schedule` | Schedule the visit; spawn a service job | Dispatcher |
| POST | `/service-calls/{id}/resolve` | Resolve the call; billable creates an invoice | BillingAdmin |
| GET | `/service-calls/{id}` | Fetch a service call | BillingAdmin, Dispatcher, SalesRep, Customer |
| GET | `/service-calls` | List service calls | BillingAdmin, Dispatcher, SalesRep, Customer |
| POST | `/storage-bins` | Create a storage bin | BillingAdmin |
| POST | `/storage-records` | Store a customer's lights in a bin | BillingAdmin |
| POST | `/storage-records/{id}/retrieve` | Retrieve stored lights | BillingAdmin |
| GET | `/storage-records/{id}` | Fetch a storage record | BillingAdmin, SalesRep, Customer |
| GET | `/storage-records` | List storage records | BillingAdmin, SalesRep, Customer |
| POST | `/financing-plans` | Originate a financing plan | BillingAdmin |
| GET | `/financing-plans/{id}/payoff-quote` | Dual-variant payoff quote | BillingAdmin, Customer, SalesRep |
| POST | `/financing-plans/{id}/payments` | Post a payment against the plan | Customer, BillingAdmin |
| GET | `/financing-plans/{id}` | Fetch a financing plan | BillingAdmin, Customer, SalesRep |
| GET | `/financing-plans` | List financing plans | BillingAdmin, Customer, SalesRep |
| POST | `/payments/{id}/reverse` | Reverse a posted payment | BillingAdmin |
| GET | `/payments/{id}` | Fetch a payment | BillingAdmin, Customer, SalesRep |
| GET | `/payments` | List payments | BillingAdmin, Customer, SalesRep |
| POST | `/invoices` | Issue an invoice with explicit line items | BillingAdmin |
| POST | `/invoices/{id}/void` | Void an issued invoice | BillingAdmin |
| GET | `/invoices/{id}` | Fetch an invoice | BillingAdmin, Customer, SalesRep |
| GET | `/invoices` | List invoices | BillingAdmin, Customer, SalesRep |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_ESTIMATE_NOT_FOUND` | 404 |
| `ERR_CREW_NOT_FOUND` | 404 |
| `ERR_ROUTE_DAY_NOT_FOUND` | 404 |
| `ERR_ROUTE_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_JOB_NOT_FOUND` | 404 |
| `ERR_SERVICE_CALL_NOT_FOUND` | 404 |
| `ERR_STORAGE_BIN_NOT_FOUND` | 404 |
| `ERR_STORAGE_RECORD_NOT_FOUND` | 404 |
| `ERR_FINANCING_PLAN_NOT_FOUND` | 404 |
| `ERR_PAYMENT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_CONTRACT_NOT_SIGNABLE` | 409 |
| `ERR_CONTRACT_NOT_RENEWABLE` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_ESTIMATE_NOT_DRAFT` | 409 |
| `ERR_ESTIMATE_NOT_QUOTED` | 409 |
| `ERR_JOB_NOT_SCHEDULED` | 409 |
| `ERR_JOB_NOT_IN_PROGRESS` | 409 |
| `ERR_JOB_NOT_HELD` | 409 |
| `ERR_JOB_NOT_CANCELLABLE` | 409 |
| `ERR_ROUTE_DAY_NOT_PLANNED` | 409 |
| `ERR_ROUTE_DAY_NOT_DISPATCHED` | 409 |
| `ERR_JOB_NOT_BOOKABLE` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_BIN_OCCUPIED` | 409 |
| `ERR_ROUTE_DAY_FULL` | 409 |
| `ERR_SERVICE_CALL_INVALID_STATE` | 409 |
| `ERR_STORAGE_RECORD_NOT_STORED` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_PAYMENT_NOT_POSTED` | 409 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_STALE_VERSION` | 412 |
