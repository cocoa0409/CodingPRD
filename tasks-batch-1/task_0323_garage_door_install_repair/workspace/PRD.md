# Garage Door Install & Repair API — Product Requirements Document

## 1. Introduction

This document specifies the back-office platform for a garage-door installation and repair business. A single operating company maintains a catalog of door and opener models, a parts-and-stock inventory, and a fleet of technicians and lifting equipment. Around that catalog the platform runs the full commercial lifecycle: a back-office operator drafts a quote for a customer — either a flat-fee **service call** or a full **install** — the customer reviews and accepts it, the accepted quote spawns a dispatchable job, a dispatcher assigns a technician and a scheduling window, the technician drives out, performs the work on site, consumes the reserved parts, and completes the job, after which the office invoices, collects payment, and closes the work order.

The domain is deliberately money-sensitive and safety-sensitive. Quotes carry a forward-looking estimate built from catalog list prices, while the job that the quote spawns carries a separately computed final invoice built from what was actually consumed on site plus any after-hours surcharge — the two figures are intentionally allowed to diverge, and the platform must compute each from its own inputs rather than copying one onto the other. Layered on top are emergency/after-hours pricing bands, a warranty and tune-up program, consumer financing with tiered interest, and a callback (re-visit) workflow that feeds a technician quality score. Throughout, the platform enforces a strict separation of duties between the people who schedule work, the people who execute it on site, and the people who bill for it.

Because several actors operate on the same records, the platform protects shared aggregates with optimistic concurrency control and conserves physical quantities — parts inventory and booked technician time — through compensating side effects whenever work is cancelled or released.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role under which the request is made. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The platform recognizes exactly four roles, spelled precisely as follows: `Customer`, `Dispatcher`, `Technician`, and `ServiceManager`.

- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID`: a customer accepts or declines only quotes whose `customer_id` is their own, and reads their own quotes, jobs, warranty plans, and financing applications.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity. On-site transitions compare the job's assigned `technician_id` to `X-User-ID`; only the assigned technician may drive, arrive, complete, or consume parts on a given job. The technician identity is also what the platform records when a job is completed (see the segregation-of-duties rule), so that a later billing step can compare against it.
- When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server accepts and may log it but does not compare it against any entity's `id`.
- When `X-User-Role` is `ServiceManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server does, however, record the manager's `X-User-ID` in the course of certain operations and compares it for the invoice segregation check described in §3; outside that one comparison it is not matched against any entity `id`.

The duty-separation model is structural, not merely advisory. A `Dispatcher` schedules and cancels work but may never run an on-site transition; a `Technician` executes on site but never schedules; and a `ServiceManager` who personally completed a job may not be the one who invoices it. The exact operation-to-role assignments appear in the endpoint table of §4.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and counts the number of leading records to skip. List endpoints return their results sorted by `created_at` in ascending order (oldest first). The `meta` block of a list response carries the pagination bookkeeping fields `limit`, `offset`, `total_count` (the number of records matching the query before the page window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is assigned a server-minted `id` that is a UUID carrying no type prefix. Every resource also records a `created_at` timestamp, formatted as an ISO 8601 UTC instant with three fractional digits, fixed at the moment of creation.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `version` begins at the resource's creation and increments by one on every mutation of that resource; `updated_at` is refreshed to the current instant on every such mutation. These two fields exist on the customer, technician, part, equipment unit, quote, quote line, job, part reservation, warranty plan, financing application, and callback resources.

Two catalog resources are immutable reference data and therefore carry **only** `id` and `created_at` — they have **no** `updated_at` field and **no** `version` field: the door model (`DoorModel`) and the opener model (`OpenerModel`).

### 2.5. Monetary Precision and Rounding

All monetary amounts in the platform are expressed in whole **cents** as integers. Wherever a calculation produces a fractional cent, it is rounded **half-up** to the nearest whole cent (a value exactly at the half-cent rounds upward). The rounding granularity and ordering matter and are specified per calculation in §3; in particular, quote-line and consumed-part subtotals are each rounded to whole cents **before** they are summed, never summed in raw form and rounded once at the end. The sole non-monetary rounded quantities are the technician callback rates, which are fractions rounded half-up to four decimal places.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control so that a client cannot blindly overwrite a parent record that has advanced since the client last read it.

The first guarded operation is the creation of a part reservation against an existing job. That request must include a non-optional field `expected_job_version` carrying the `version` of the target `Job` as the client last observed it. If `expected_job_version` does not equal the job's current `version`, the reservation create is rejected with `ERR_STALE_VERSION` (HTTP 412). Each reservation create legitimately supersedes the prior inventory view of the job, so a client holding a stale job version must re-read the job before adding more parts.

The second guarded operation is revising a sent quote. That request must include a non-optional field `expected_quote_version` carrying the `version` of the target `Quote` as the client last observed it. If `expected_quote_version` does not equal the quote's current `version`, the revision is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client carrying a stale quote version cannot overwrite a revision it never saw.

No other endpoint takes a version field; only these two operations participate in concurrency control.

### 2.7. Existence, Type, and Uniqueness Validation

References are resolved left to right. For any operation, the platform first resolves every identifier that appears in the URL path and then every foreign key supplied in the body; if any of them fails to resolve to an existing resource, the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Once existence is established, the platform checks the request body: every required field must be present and of the correct type, every enumerated field must hold one of its declared values, and any quantity field must be at least 1 — failure of any of these yields `ERR_INVALID_REQUEST` (HTTP 422).

Several fields are unique within their resource kind. A customer's `email` must be unique across all customers; the `sku` of a part, the `sku` of a door model, and the `sku` of an opener model must each be unique within their respective catalogs. A creation that collides with an existing value on any of these is rejected with `ERR_DUPLICATE` (HTTP 409).

### 2.8. Validation Ordering

When more than one validation could fire on a single request, the platform evaluates them in a fixed priority order and returns the first failure it encounters. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role authorization for the operation (`ERR_FORBIDDEN_ROLE`); (3) existence of all referenced path ids and body foreign keys (`ERR_NOT_FOUND`); (4) request-body well-formedness, including required fields, types, enum membership, and the at-least-one quantity rule (`ERR_INVALID_REQUEST`); (5) that the target resource is in a state from which the requested transition is allowed (`ERR_INVALID_STATE`); and then the domain-specific business checks. Authentication therefore always precedes authorization, which precedes existence, which precedes body validation, which precedes state validation, which precedes any business rule. The business checks themselves — quote expiry, safety, parts-consumption, technician eligibility, scheduling overlap, equipment availability, stock sufficiency, customer financing standing, tune-up exhaustion, the financing ceiling, the segregation-of-duties check, the stale-version check, and uniqueness — are described alongside the workflows they guard in §3, and each is keyed to its own error code there.

### 2.9. Quantity Conservation and Compensating Effects

The platform treats two quantities as conserved and reconciles them through paired forward and compensating effects. The first is parts inventory: each part tracks the physical units in stock (`on_hand_qty`), the units currently committed to open reservations (`reserved_qty`), and the units free to commit (`available_qty`), where `available_qty` is always `on_hand_qty` minus `reserved_qty` and is never allowed to fall below zero. The second is technician booked time: each technician tracks `booked_minutes`, the total scheduled minutes across that technician's jobs whose dispatch status is anything other than cancelled. Whenever a reservation is held, consumed, or released, or a job is scheduled or cancelled, the relevant counters move in lockstep as described in §3, so that the conserved totals always reconcile against the underlying rows.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Door Models, Opener Models, Parts, and Equipment

Before any quoting can happen, a `ServiceManager` populates the reference catalog. A **door model** is created with a catalog `sku`, a product `name`, a nominal `width_in` and `height_in` in inches, a catalog `list_price_cents`, a standard `install_labor_minutes` budget, and a flag `requires_lift` indicating whether installing this door needs a powered lift; `requires_lift` defaults to false when omitted. An **opener model** is created with its own `sku`, `name`, a motor `horsepower` rating, a `list_price_cents`, and an `install_labor_minutes` budget. Both door and opener models are pure reference records: they carry only their identity and creation timestamp and are never versioned.

A **part** represents a stock item identified by `sku` and classified by `category`, which must be one of `SPRING`, `CABLE`, `PANEL`, `ROLLER`, or `SENSOR`. Each part has a `unit_price_cents` catalog price and a `markup_pct`, the per-line markup fraction applied to the part's price on quote lines — a `markup_pct` of 0.35 means the line is priced at 135% of catalog — defaulting to 0.35 when not supplied. A part is created with its physical `on_hand_qty`; at creation its `reserved_qty` is zero and its `available_qty` equals `on_hand_qty`. An **equipment unit** (a lift or crane) is created with a `name` and a `concurrent_capacity`, the maximum number of overlapping jobs that may book that unit at once; `concurrent_capacity` defaults to 1 when omitted.

### 3.2. Customers, Technicians, and Their Standing

A `ServiceManager` registers a **customer** with a `full_name`, a contact `email` (unique among customers), a `service_address` where work is performed, and an optional IANA `time_zone` used to classify dispatch hours into business and after-hours bands; when omitted, `time_zone` defaults to `America/Los_Angeles`. Two further customer attributes are derived rather than supplied. The `financing_standing` is either `GOOD` or `BLOCKED`: a freshly registered customer is `GOOD`, and a customer becomes `BLOCKED` precisely while they hold any financing application in the `DEFAULTED` state. The `active_warranty_count` is the number of warranty plans for that customer currently in `ACTIVE` status, beginning at zero.

A **technician** is created with a `display_name` and a `skill_level` of `APPRENTICE`, `CERTIFIED`, or `MASTER`, plus an optional `certified_for_install` flag (default false) that governs whether they may run install jobs as opposed to service-only work. A new technician's `status` is `AVAILABLE`; only an available technician may be dispatched. A `ServiceManager` may toggle a technician between `AVAILABLE` and `ON_LEAVE` by supplying the desired `status`. Each technician also carries four computed figures: `booked_minutes` (described in §2.9 and §3.5), `jobs_completed_count` (the count of that technician's jobs in `COMPLETED` or `CLOSED` dispatch status), and two callback quality rates, `callback_rate_provisional` and `callback_rate_settled`, whose computation is given in §3.10.

### 3.3. Drafting and Pricing a Quote

A quote is the commercial offer. A `ServiceManager` creates a quote in `DRAFT` status for a given customer (`customer_id`) with a `quote_type` of either `SERVICE_CALL` or `INSTALL`, which determines the pricing model. On an `INSTALL` quote the manager may name a `door_model_id` and an optional add-on `opener_model_id`; on a `SERVICE_CALL` quote both of those are null, and the manager instead sets a flat `service_call_fee_cents` trip-and-diagnostic fee (zero on installs, and defaulting to zero when omitted). A new quote starts at `revision` 1.

Quote lines are then added. A **quote line** belongs to a quote (`quote_id`) and has an `item_kind` of `PART`, `DOOR`, `OPENER`, or `LABOR`. When `item_kind` is `PART`, the line carries an `item_ref_id` pointing at the part being sold; for `DOOR`, `OPENER`, and `LABOR` lines the `item_ref_id` is null because those derive their price from the quote header. The `qty` field means units for a `PART` line and minutes for a `LABOR` line and must be at least 1. The line captures a snapshot `unit_price_cents` at the time it is created. Each line's `line_total_cents` is computed as a marked-up, rounded per-line subtotal.

The quote's forward-looking total, `estimate_total_cents`, is recomputed whenever the quote is sent or revised, and the line subtotal is recomputed whenever a line is added while the quote is in `DRAFT` or `SENT`. The computation proceeds in a pinned order. First, for each quote line, a raw line amount is computed by item kind: a `PART` line's raw amount is its `qty` multiplied by its `unit_price_cents` multiplied by one plus the part's `markup_pct`; a `DOOR` line's raw amount is the door model's `list_price_cents`; an `OPENER` line's raw amount is the opener model's `list_price_cents`; and a `LABOR` line's raw amount is its `qty` in minutes multiplied by the labor rate of 250 cents per minute. Second, each line's `line_total_cents` is obtained by rounding that raw line amount half-up to whole cents — this per-line rounding happens first, before any summation. Third, the parts-and-goods subtotal is the sum of every line's `line_total_cents`. Fourth, the `estimate_total_cents` is that parts-and-goods subtotal plus the `service_call_fee_cents` when the quote type is `SERVICE_CALL`, or plus nothing when the quote type is `INSTALL`. Summing the raw line amounts and rounding once at the end is incorrect; the rounding must be applied per line first and the rounded line totals then summed.

### 3.4. Sending, Revising, Accepting, and Declining a Quote

A quote moves from `DRAFT` to `SENT` when the `ServiceManager` sends it, which is permitted only if the quote has at least one quote line. Sending stamps `expires_at` to the instant of sending plus 14 days, recomputes `estimate_total_cents`, and advances the quote's `version`.

A `SENT` quote may be revised repeatedly before the customer decides; revising is a self-loop that keeps the quote in `SENT`. Revision is allowed only while the quote is still `SENT` (not yet `ACCEPTED`, `DECLINED`, or `EXPIRED`). A revise request carries `expected_quote_version` and is subject to the stale-version guard of §2.6: a mismatch is rejected with `ERR_STALE_VERSION`. A successful revise increments `revision` by one, resets `expires_at` to the revise instant plus 14 days, recomputes `estimate_total_cents` over the current set of quote lines, and advances the quote's `version`.

Expiry is lazy and time-driven. A `SENT` quote whose `expires_at` instant has been reached or passed is treated as `EXPIRED`; the platform flips a `DRAFT` or `SENT` quote to `EXPIRED` on the next read of the quote or the next transition attempt once the current time is at or after `expires_at`. Once a quote is `EXPIRED`, it is terminal, and any attempt to accept, decline, or revise it is rejected with `ERR_QUOTE_EXPIRED`. `ACCEPTED` and `DECLINED` are likewise terminal.

When the `Customer` who owns the quote **declines** it, the quote moves from `SENT` to `DECLINED` and no job is created. When the customer **accepts**, several preconditions must hold: the quote must be `SENT`; the current time must be before `expires_at` (otherwise the read or transition first flips it to `EXPIRED` and the accept is rejected with `ERR_QUOTE_EXPIRED`); and the customer's `financing_standing` must be `GOOD` — a customer whose standing is `BLOCKED` cannot accept, and the attempt is rejected with `ERR_CUSTOMER_BLOCKED`. A successful accept is a multi-hop cascade. First, the quote moves from `SENT` to `ACCEPTED`. Second, a new job is created in dispatch status `UNSCHEDULED` and billing status `PENDING`. Third, for every `PART` quote line, a part reservation in `HELD` status is created on the new job. Fourth, each reservation creation increases the corresponding part's `reserved_qty` and recomputes its `available_qty`; if any part line's quantity would exceed the part's `available_qty`, the accept is rejected with `ERR_INSUFFICIENT_STOCK`. Finally, the quote's `version` is advanced.

### 3.5. Dispatch: Scheduling and Cancelling a Job

A **job** is the work order spawned by an accepted quote. It records the originating `quote_id`, the `customer_id` denormalized from that quote at creation, the assigned `technician_id` (null while unscheduled), and the booked `equipment_unit_id` (null unless the door requires a lift). It carries two independent status dimensions, the `dispatch_status` and the `billing_status`, each advancing on its own. The dispatch dimension begins at `UNSCHEDULED`.

A `Dispatcher` schedules an unscheduled job, moving its dispatch status from `UNSCHEDULED` to `SCHEDULED`. The request names the `technician_id`, a `scheduled_start` and a `scheduled_end` window (both UTC instants), an optional `equipment_unit_id`, and an optional `is_emergency` flag (default false) indicating the customer requested emergency/after-hours service. Several preconditions are enforced. The chosen technician's `status` must be `AVAILABLE`, and if the originating quote's `quote_type` is `INSTALL` the technician's `certified_for_install` must be true; a technician who is on leave or not install-certified for an install job triggers `ERR_TECH_NOT_ELIGIBLE`. The window must be valid, with `scheduled_start` strictly before `scheduled_end` (the window is half-open). The window must not overlap any of the technician's other non-cancelled jobs once a 30-minute travel buffer is added to each side; treating intervals as half-open and buffered, an overlap is rejected with `ERR_TECH_SCHEDULE_CONFLICT`. If the door on this job requires a lift, an `equipment_unit_id` must be supplied, and the number of existing bookings on that equipment unit whose intervals overlap the requested window (intervals treated as closed for aggregate-capacity counting) must be strictly below the unit's `concurrent_capacity`; otherwise — including the case where a lift is required but no unit is supplied — the request is rejected with `ERR_EQUIPMENT_UNAVAILABLE`. A successful schedule assigns the `technician_id` (and the `equipment_unit_id` when required) and increases the technician's `booked_minutes` by the window length in minutes.

A `Dispatcher` may **cancel** a job while its dispatch status is `UNSCHEDULED`, `SCHEDULED`, or `EN_ROUTE`; cancellation is forbidden once the job is `ON_SITE`, `COMPLETED`, or `CLOSED`, and an attempt from those states is rejected with `ERR_INVALID_STATE`. Cancelling moves the dispatch status to `CANCELLED` and performs compensating effects: every `HELD` part reservation on the job is moved to `RELEASED`, and each release decreases the corresponding part's `reserved_qty` and recomputes its `available_qty`; and if a technician had been assigned, the technician's `booked_minutes` is decreased by that job's window length, restoring the conserved booked-time total.

### 3.6. On-Site Execution and Job Completion

Once a job is `SCHEDULED`, the assigned `Technician` drives the on-site lifecycle. Departing moves the job from `SCHEDULED` to `EN_ROUTE` and records the ETA window start; arriving moves it from `EN_ROUTE` to `ON_SITE`. Each of these transitions requires that the acting technician's `X-User-ID` equals the job's `technician_id`. While on site, the technician records a passing safety inspection through the safety-check capability, which sets `safety_inspection_passed` to true (it starts false).

Completing the job moves it from `ON_SITE` to `COMPLETED` and is gated by two business checks. First, the job cannot be completed unless `safety_inspection_passed` is true; if it is still false, the completion is rejected with `ERR_SAFETY_NOT_PASSED`. Second, every part reservation on the job must be in `CONSUMED` status; if any reservation is still `HELD`, the completion is rejected with `ERR_PARTS_NOT_CONSUMED`. On a successful completion, the platform records `completed_by_user_id` as the acting technician's `X-User-ID`, computes the job's `final_total_cents` and its `emergency_surcharge_cents`, increments the technician's `jobs_completed_count` by one, and recomputes that technician's `callback_rate_provisional` and `callback_rate_settled`.

The **final invoice total** is computed once, at completion, from actuals — and it deliberately diverges from the quote's forward-looking estimate. It has three components summed together. The first component is the consumed-parts cost: over every part reservation on the job whose status is `CONSUMED` (held or released reservations are excluded entirely), each reservation contributes its `qty` multiplied by the part's `unit_price_cents` multiplied by one plus the part's `markup_pct`, rounded half-up to whole cents per reservation, and these per-reservation rounded amounts are then summed. The second component is labor: for a `SERVICE_CALL` job the labor cost is the quote's `service_call_fee_cents`; for an `INSTALL` job the labor cost is the sum of the door model's `install_labor_minutes` plus, when an opener is present, the opener model's `install_labor_minutes`, that minute total multiplied by the labor rate of 250 cents per minute. The third component is the `emergency_surcharge_cents` described in §3.7. The `final_total_cents` is the consumed-parts cost plus the labor cost plus the emergency surcharge.

### 3.7. After-Hours Pricing and the Emergency Surcharge

The `emergency_surcharge_cents` is a non-linear function of three inputs: the job's `is_emergency` flag, the local wall-clock hour of `scheduled_start` expressed in the customer's `time_zone`, and the pre-surcharge base (the sum of the consumed-parts cost and the labor cost from §3.6). The surcharge first selects a band from the local hour-of-day of `scheduled_start` converted into the customer's `time_zone`. The `BUSINESS` band covers local times from 08:00:00 inclusive up to but not including 18:00:00 and carries a rate of zero. The `AFTER_HOURS` band covers local times from 18:00:00 inclusive up to but not including 22:00:00 and carries a rate of 0.25; note that a local time of exactly 18:00:00 falls in `AFTER_HOURS`, not `BUSINESS`. The `OVERNIGHT` band covers local times at or after 22:00:00 as well as any local time before 08:00:00, and carries a rate of 0.50.

The raw surcharge is the base multiplied by the band rate when `is_emergency` is true, and is zero when `is_emergency` is false. When that raw surcharge is greater than zero, it is rounded half-up to whole cents and then clamped to lie between a floor of 5,000 cents and a ceiling of 40,000 cents — a positive surcharge below the floor is lifted to 5,000 cents and one above the ceiling is capped at 40,000 cents. The clamp applies only when the raw surcharge is positive: if the raw surcharge is zero (for example, a non-emergency job, or an emergency job scheduled in the `BUSINESS` band where the rate is zero), the `emergency_surcharge_cents` is exactly zero and the floor does not lift it.

### 3.8. Billing, Closing, and the Segregation of Duties

The billing dimension of a job runs in parallel with the dispatch dimension and begins at `PENDING`. A `ServiceManager` **invoices** a job, moving its billing status from `PENDING` to `INVOICED`, which freezes the `final_total_cents` onto the invoice. Two preconditions guard this step: the job's dispatch status must be `COMPLETED` (a cross-dimension guard within the same job), and — enforcing separation of duties — the acting manager's `X-User-ID` must not equal the job's `completed_by_user_id`. A manager attempting to invoice a job they personally completed is rejected with `ERR_SEGREGATION_VIOLATION`. A `ServiceManager` then records **payment**, moving the billing status from `INVOICED` to `PAID`.

Closing a job is the final dispatch transition: a `ServiceManager` moves the dispatch status from `COMPLETED` to `CLOSED`, permitted only once the billing status is `PAID`. Closing carries a cascade: if a warranty plan exists for this job in `PENDING` status, it is activated to `ACTIVE`, and that activation increments the owning customer's `active_warranty_count` by one.

### 3.9. Parts Reservations and Inventory Movement

A **part reservation** ties a quantity of a part to a job. Reservations are created two ways. Most arise automatically when a quote is accepted (one `HELD` reservation per `PART` quote line, as described in §3.4). Additionally, a `Dispatcher` or `ServiceManager` may manually reserve more parts for an existing job by supplying the `job_id`, the `part_id`, the `qty` (at least 1), and the `expected_job_version` for the optimistic-concurrency guard of §2.6. A manual reservation create is rejected with `ERR_INSUFFICIENT_STOCK` if its `qty` exceeds the part's `available_qty`. A successful manual create records the reservation in `HELD` status, increases the part's `reserved_qty`, recomputes its `available_qty`, and advances the job's `version`.

A reservation's `status` moves among `HELD`, `CONSUMED`, and `RELEASED`. The assigned `Technician` **consumes** a held reservation while the parent job is `ON_SITE`; consuming requires that the parent job's dispatch status is `ON_SITE`, moves the reservation from `HELD` to `CONSUMED`, and decreases both the part's `on_hand_qty` and its `reserved_qty` by the reservation `qty`, recomputing `available_qty` — the consumed stock leaves both pools, keeping inventory conserved. A held reservation is **released** either automatically when its parent job is cancelled or explicitly by a `Dispatcher` or `ServiceManager`; release requires the reservation be `HELD`, moves it from `HELD` to `RELEASED`, and decreases the part's `reserved_qty` (recomputing `available_qty`) without touching `on_hand_qty`.

### 3.10. Callbacks and the Technician Quality Score

When a customer is dissatisfied with completed work, a `Customer` or `ServiceManager` **opens** a callback against the original job by supplying its `job_id` and a free-text `reason`; the callback begins in `OPEN` status. A `Dispatcher` schedules the callback, moving it from `OPEN` to `SCHEDULED`, which is allowed only when the parent job's dispatch status is `COMPLETED` or `CLOSED`. A `Technician` then arrives, moving the callback from `SCHEDULED` to `ON_SITE`, and finally resolves it, moving it from `ON_SITE` to `RESOLVED` and setting `fault_confirmed` from the request body (recording whether the original work was actually at fault). Alternatively, a `Dispatcher` may **reopen** an on-site callback that could not be resolved, moving it from `ON_SITE` back to `OPEN` for re-triage; this is the cyclic branch of the callback lifecycle.

Both completing a job and resolving a callback recompute the responsible technician's two callback rates, where the responsible technician is the one assigned to the original job referenced through the callback's `job_id`. The denominator for both rates is that technician's `jobs_completed_count` (jobs in `COMPLETED` or `CLOSED`). The **provisional** rate is pessimistic: its numerator counts every callback on the technician's jobs that is either not yet `RESOLVED`, or is `RESOLVED` with `fault_confirmed` true — open, scheduled, and on-site callbacks are all counted as faults. The **settled** rate is confirmed: its numerator counts only callbacks that are `RESOLVED` with `fault_confirmed` true. When the denominator is zero, both rates are zero. Otherwise each rate is its numerator divided by the denominator, rounded half-up to four decimal places. The two rates coincide only once every callback for the technician has been resolved; while unresolved callbacks remain, `callback_rate_provisional` is at least as large as `callback_rate_settled`.

### 3.11. Warranty Plans and Tune-Ups

A `ServiceManager` creates a **warranty plan** tied to a completed job by supplying its `job_id` and the owning `customer_id`, with an optional `tune_ups_included` count (the number of free tune-up visits over the plan term, defaulting to 2). A new plan starts in `PENDING` status with `tune_ups_used` at zero. As described in §3.8, a `PENDING` plan is activated to `ACTIVE` as a cascade when its job is closed, and activation increments the customer's `active_warranty_count`.

A tune-up visit is redeemed against the plan by a `Customer` or `ServiceManager`; each redemption increments `tune_ups_used` by one, but only while it is below the limit — a redemption attempted when `tune_ups_used` is greater than or equal to `tune_ups_included` is rejected with `ERR_TUNEUPS_EXHAUSTED`. A `ServiceManager` may **cancel** an active plan, moving it from `ACTIVE` to `CANCELLED` and decrementing the customer's `active_warranty_count` by one. A `ServiceManager` may also **expire** a plan, moving it from `ACTIVE` to `EXPIRED`, permitted only once the plan is exhausted — that is, once `tune_ups_used` is greater than or equal to `tune_ups_included` — and likewise decrementing the customer's `active_warranty_count` by one.

### 3.12. Consumer Financing

A `Customer` or `ServiceManager` submits a **financing application** against a quote by supplying the `customer_id`, the `quote_id` being financed, a `principal_cents` amount (which must equal that quote's `estimate_total_cents` at submission), and a `term_months` of 6, 12, or 24. The application begins in `SUBMITTED` status.

A `ServiceManager` decides the application. **Approving** it moves it from `SUBMITTED` to `APPROVED`, permitted only when the `principal_cents` is at or below the approval ceiling of 1,500,000 cents (fifteen thousand dollars); a principal above that ceiling is rejected with `ERR_FINANCING_CEILING`. Approval computes the `monthly_payment_cents`. **Declining** it moves it from `SUBMITTED` to `DECLINED` with no further effect. An approved application is **activated** to `ACTIVE`, permitted only when the financed quote's status is `ACCEPTED`. An active application may be marked **defaulted**, moving it from `ACTIVE` to `DEFAULTED`; defaulting recomputes the owning customer's `financing_standing` to `BLOCKED`, which is the condition that prevents that customer from accepting further quotes.

The `monthly_payment_cents` is computed at approval by a term-tiered amortization. The annual percentage rate is selected by term: a `term_months` of 6 or fewer carries an APR of 0.00; a term of 7 through 12 months carries an APR of 0.099; and a term of 13 through 24 months carries an APR of 0.149. The monthly rate is that APR divided by 12. When the monthly rate is zero (the 0% tier), the monthly payment is the `principal_cents` divided by `term_months`, rounded up to the next whole cent (ceiling). Otherwise, letting the growth factor be one plus the monthly rate raised to the power of `term_months`, the monthly payment is the `principal_cents` multiplied by the monthly rate, multiplied by that growth factor, divided by the growth factor minus one, with the result rounded half-up to whole cents.

### 3.13. Reading Resources and the Test Clock

All entities are individually retrievable by id and, for the collection resources, listable. List endpoints support reverse-reachability filtering by the foreign keys of their records: quotes filter by `customer_id`, `door_model_id`, `opener_model_id`, and `status`; jobs filter by `quote_id`, `customer_id`, `technician_id`, `equipment_unit_id`, and `dispatch_status`; part reservations filter by `job_id`, `part_id`, and `status`; warranty plans filter by `job_id`, `customer_id`, and `status`; financing applications filter by `customer_id`, `quote_id`, and `status`; and callbacks filter by `job_id` and `status`. Quote lines are listed under their owning quote. Reading a quote is also the moment at which a `SENT` quote past its `expires_at` is lazily flipped to `EXPIRED`.

Because expiry and surcharge banding both depend on time, the platform exposes an administrative test-driving capability that sets the server's notion of the current UTC instant to a supplied `to_iso8601` value. Advancing the clock causes any `SENT` quote past its `expires_at` to expire on its next read. This capability is reserved for the back-office operator role.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201; reads and state-transition or mutation operations that act on an existing resource return HTTP 200. The request body, response body, and side effects of each operation are described in §3 and are not repeated here; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/door-models` | Create door catalog model | ServiceManager |
| GET | `/door-models/{id}` | Get door model | ServiceManager, Customer, Dispatcher, Technician |
| POST | `/opener-models` | Create opener catalog model | ServiceManager |
| GET | `/opener-models/{id}` | Get opener model | ServiceManager, Customer, Dispatcher, Technician |
| POST | `/parts` | Create part / stock item | ServiceManager |
| GET | `/parts/{id}` | Get part incl. inventory pools | ServiceManager, Customer, Dispatcher, Technician |
| POST | `/equipment-units` | Create lift/crane unit | ServiceManager |
| POST | `/customers` | Register a customer | ServiceManager |
| GET | `/customers/{id}` | Get customer | ServiceManager, Customer, Dispatcher |
| POST | `/technicians` | Create a technician | ServiceManager |
| GET | `/technicians/{id}` | Get technician incl. computed rates | ServiceManager, Dispatcher, Technician |
| POST | `/technicians/{id}/set-leave` | Toggle technician status between AVAILABLE and ON_LEAVE | ServiceManager |
| POST | `/quotes` | Create a DRAFT quote | ServiceManager |
| GET | `/quotes/{id}` | Get quote (lazily flips to EXPIRED if past expiry) | ServiceManager, Customer |
| GET | `/quotes` | List quotes | ServiceManager, Customer |
| POST | `/quotes/{id}/lines` | Add a quote line | ServiceManager |
| GET | `/quotes/{id}/lines` | List a quote's lines | ServiceManager, Customer |
| POST | `/quotes/{id}/send` | Send quote to customer | ServiceManager |
| POST | `/quotes/{id}/revise` | Revise a SENT quote (OCC-guarded) | ServiceManager |
| POST | `/quotes/{id}/accept` | Customer accepts; spawns job + reservations | Customer |
| POST | `/quotes/{id}/decline` | Customer declines | Customer |
| GET | `/jobs/{id}` | Get job (both status dimensions + computed totals) | ServiceManager, Dispatcher, Technician, Customer |
| GET | `/jobs` | List jobs | ServiceManager, Dispatcher, Technician |
| POST | `/jobs/{id}/schedule` | Dispatch: assign technician + window (+ equipment if lift) | Dispatcher |
| POST | `/jobs/{id}/depart` | Technician en route | Technician |
| POST | `/jobs/{id}/arrive` | Technician on site | Technician |
| POST | `/jobs/{id}/safety-check` | Record passing safety inspection | Technician |
| POST | `/jobs/{id}/complete` | Complete job; compute final total | Technician |
| POST | `/jobs/{id}/invoice` | Invoice (segregation: invoicer must differ from completer) | ServiceManager |
| POST | `/jobs/{id}/pay` | Record payment | ServiceManager |
| POST | `/jobs/{id}/close` | Close completed and paid job; activates warranty | ServiceManager |
| POST | `/jobs/{id}/cancel` | Cancel pre-on-site job; releases holds + frees minutes | Dispatcher |
| POST | `/part-reservations` | Manually reserve more parts for a job (OCC on job version) | Dispatcher, ServiceManager |
| GET | `/part-reservations` | List reservations | ServiceManager, Dispatcher, Technician |
| GET | `/part-reservations/{id}` | Get a single part reservation | ServiceManager, Dispatcher, Technician |
| POST | `/part-reservations/{id}/consume` | Consume a held reservation on site | Technician |
| POST | `/part-reservations/{id}/release` | Release a held reservation | Dispatcher, ServiceManager |
| POST | `/warranty-plans` | Create a PENDING warranty plan tied to a job | ServiceManager |
| GET | `/warranty-plans/{id}` | Get warranty plan | ServiceManager, Customer |
| GET | `/warranty-plans` | List warranty plans | ServiceManager, Customer |
| POST | `/warranty-plans/{id}/tune-up` | Redeem a tune-up visit | ServiceManager, Customer |
| POST | `/warranty-plans/{id}/cancel` | Cancel an active plan | ServiceManager |
| POST | `/warranty-plans/{id}/expire` | Expire an exhausted plan | ServiceManager |
| POST | `/financing-applications` | Submit a financing application against a quote | Customer, ServiceManager |
| GET | `/financing-applications/{id}` | Get financing application | ServiceManager, Customer |
| GET | `/financing-applications` | List applications | ServiceManager, Customer |
| POST | `/financing-applications/{id}/approve` | Approve (computes monthly payment) | ServiceManager |
| POST | `/financing-applications/{id}/decline` | Decline an application | ServiceManager |
| POST | `/financing-applications/{id}/activate` | Activate an approved application | ServiceManager |
| POST | `/financing-applications/{id}/default` | Mark defaulted; blocks customer | ServiceManager |
| POST | `/callbacks` | Open a callback on a completed/closed job | Customer, ServiceManager |
| GET | `/callbacks/{id}` | Get callback | ServiceManager, Dispatcher, Technician, Customer |
| GET | `/callbacks` | List callbacks | ServiceManager, Dispatcher, Technician |
| POST | `/callbacks/{id}/schedule` | Schedule a callback visit | Dispatcher |
| POST | `/callbacks/{id}/arrive` | Technician arrives for callback | Technician |
| POST | `/callbacks/{id}/resolve` | Resolve callback; sets fault + rescore tech | Technician |
| POST | `/callbacks/{id}/reopen` | Reopen an on-site callback (cyclic) | Dispatcher |
| POST | `/_clock/set_current_utc` | Set the server's notion of current UTC time (test harness) | ServiceManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_SAFETY_NOT_PASSED` | 409 |
| `ERR_PARTS_NOT_CONSUMED` | 409 |
| `ERR_TECH_NOT_ELIGIBLE` | 409 |
| `ERR_TECH_SCHEDULE_CONFLICT` | 409 |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 |
| `ERR_INSUFFICIENT_STOCK` | 409 |
| `ERR_CUSTOMER_BLOCKED` | 409 |
| `ERR_TUNEUPS_EXHAUSTED` | 409 |
| `ERR_FINANCING_CEILING` | 409 |
| `ERR_SEGREGATION_VIOLATION` | 409 |
| `ERR_STALE_VERSION` | 412 |
