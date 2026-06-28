# Soft-Wash Exterior Cleaning API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Soft-Wash Exterior Cleaning platform, a back-office system that runs a residential and light-commercial pressure-and-chemical cleaning operation end to end. The business quotes jobs by surface area, building height, surface type, service type, and chemical mix; schedules crews around weather forecasts and geographic routes; documents each job with before-and-after photography; and bills customers per visit. The platform must reconcile two recurring tensions that define the domain. First, money: every job is quoted as an estimate from measured square footage, then re-priced at completion against what the crew actually measured on site, and a customer's outstanding balance gates whether new work can be booked. Second, safety and weather: chemical soft-washing is a regulated, ladder-borne activity that cannot proceed in high wind or rain, and a technician's ladder certification and insurance status determine which buildings that technician may legally work.

The system is built around a quoting engine, a weather-and-route scheduling layer, and a per-visit billing ledger, all of which must stay mutually consistent within each request. Recurring service plans add a loyalty dimension, rewarding repeat visits with tiered discounts, while a satisfaction-guarantee workflow allows a dissatisfied customer to trigger a free re-clean. Because quotes can be superseded and visits re-scheduled, the platform applies optimistic concurrency control at the points where a stale client view could silently overwrite committed work. The remainder of this document defines the global contracts every endpoint obeys (§2), the business workflows and their interlocking rules (§3), the endpoint surface (§4), and the catalogue of error identifiers (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that every endpoint shares. All collections are mounted at the API root.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_AUTH_HEADER`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as `Dispatcher`, `FieldTech`, `Customer`, and `BillingAdmin`.

- A `Dispatcher` is the operations role. `X-User-ID` for a `Dispatcher` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. Dispatchers build and send quotes, manage routes, weather windows, and crews, run recurring plans, schedule and cancel visits, and adjudicate satisfaction claims.
- A `BillingAdmin` is the finance role. `X-User-ID` for a `BillingAdmin` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`. BillingAdmins manage the invoice lifecycle and suspend customers.
- A `FieldTech` is a crew member on site. When `X-User-Role` is `FieldTech`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on any resource that references a `Technician` compare the resource's technician foreign key to `X-User-ID`. A FieldTech starts and completes visits and uploads photographs.
- A `Customer` is a property owner. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's owning-customer foreign key to `X-User-ID`. A Customer accepts or declines quotes, files satisfaction claims, and disputes invoices.

Whenever an entity-backed user (a `Customer` or a `FieldTech`) attempts to act on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. For a `Customer`, ownership extends to the properties, quotes, recurring plans, visits, photo sets, invoices, and satisfaction claims that trace back to that customer through the owning property; in particular a `Customer` may act on or read a visit, its photo sets, or a satisfaction claim only when the underlying property's `customer_id` equals `X-User-ID`, otherwise the request is rejected with `ERR_NOT_RESOURCE_OWNER`; for a `FieldTech`, ownership means the technician is assigned to the visit being acted on — that is, the technician must hold a crew assignment on that visit; this assigned-to-visit ownership gate applies to every FieldTech operation that references a visit, including starting and completing the visit, uploading a photo set, listing a visit's photo sets, and reading the visit (a FieldTech listing visits sees only those it is assigned to).

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

For endpoints that return lists of resources, pagination is controlled via two query parameters. The `limit` parameter specifies the maximum number of items to return; if omitted, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Each list response includes the following fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every primary, top-level resource — `Customer`, `Technician`, `Route`, `Property`, `ServiceQuote`, `RecurringPlan`, `Visit`, `CrewAssignment`, `WeatherWindow`, `Invoice`, and `SatisfactionClaim` — carries a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix. It conveys identity only.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that begins at its initial value on creation and increments by one on every mutation. It is the basis for optimistic concurrency control.

Two record types are append-only evidence rows and therefore carry **only** `id` and `created_at`: a `QuoteLineItem` (a priced line on a quote) and a `PhotoSet` (a before/after photo record on a visit). For these two record types, both `updated_at` and `version` are absent; they are never modified after creation.

Whenever a derived field is recomputed as a side effect of a mutation — for example, a customer's outstanding balance or a technician's scheduled minutes — that recomputation is itself a mutation of the owning resource: its `updated_at` is refreshed and its `version` increments by one. All mutations and their cascades complete atomically within the single request that triggers them.

### 2.5. Monetary Values, Doses, and Rounding

All monetary amounts in the system are stored and returned as integer counts of whole cents — for instance `subtotal_cents`, `travel_surcharge_cents`, `total_cents`, `line_total_cents`, `provisional_cost_cents`, `final_cost_cents`, `amount_due_cents`, `loyalty_discount_cents`, `credit_limit_cents`, and `outstanding_balance_cents`. Every price computation rounds to whole cents using the round-half-up method. Chemical dose, by contrast, is expressed in fluid ounces and is rounded to one decimal place, also round-half-up.

A rounding-order rule governs every multi-line price and is non-negotiable: each individual line is rounded to whole cents first, and the rounded per-line amounts are then summed. The system never sums raw, unrounded line amounts and rounds at the end. This applies both when a quote subtotal is frozen and when a visit's final cost is re-derived at completion.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to present the version it last observed of a parent resource, so that a client acting on a stale view cannot silently overwrite committed work.

Creating a new quote requires the field `expected_property_version`, carrying the client's last observed `version` of the target `Property`. Creating a new quote legitimately supersedes whatever prior non-terminal quote already exists on that property, and doing so advances the property's `version`. Consequently, if the property's `version` has already advanced since the client read it, the supplied `expected_property_version` will no longer equal the property's current `version`, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from creating a quote against a property view it has not re-observed since the last supersede.

Scheduling a visit requires the field `expected_visit_version`, carrying the client's last observed `version` of the target `Visit`. If that value does not equal the visit's current `version`, the schedule request is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints other than quote creation and visit scheduling do not take a version field and perform no concurrency check.

### 2.7. Resource Existence and Left-to-Right Validation

Before any business rule runs, the system validates that every resource identifier referenced by the request — whether in the URL path or in the request body — names an existing resource. Identifiers are validated left to right, parents before children, and the first identifier that does not resolve produces the corresponding not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_WEATHER_WINDOW_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`. Each carries HTTP 404.

The validation pipeline is strictly ordered. Authentication headers are checked first (`ERR_MISSING_AUTH_HEADER`); then role authorization (`ERR_UNAUTHORIZED`); then resource existence as just described; then resource ownership for entity-backed actors (`ERR_NOT_RESOURCE_OWNER`); then request-body well-formedness (`ERR_INVALID_REQUEST`); then the legality of the requested state transition (`ERR_INVALID_STATE`); and finally the domain-specific business rules described throughout §3. A check earlier in this order always takes precedence over a later one.

### 2.8. Request Well-Formedness

A create or update request body must be well-formed before any business rule is evaluated. Every enumerated field must carry one of its declared values; every integer field must fall within its declared range. Specifically, a property's `stories` must be at least 1; `roof_sqft`, `siding_sqft`, and `concrete_sqft` must each be at least 0; a line item's `measured_sqft` must be at least 1; a plan's `cadence_days` must be at least 1; a weather window's `wind_mph` must be at least 0; and a weather window's `window_end_utc` must be strictly later than its `window_start_utc`. Any violation — a bad enum value, an out-of-range integer, a missing required field, or an end timestamp at or before the start timestamp — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Cascades and Conserved Quantities

Several operations mutate more than one entity within the same request, and the secondary effects are as binding as the primary one.

A technician's `scheduled_minutes` is a derived, conserved quantity: it always equals the sum of the `duration_minutes` of that technician's crew assignments whose status is `RESERVED` or `CONFIRMED`. Reserving an assignment increases it; releasing an assignment decreases it by exactly that assignment's `duration_minutes`, the result being floored at 0 so it can never go negative. Every path that releases an assignment — direct release, visit unschedule, visit cancel, or plan cancel — must decrement the technician's `scheduled_minutes` accordingly, so the conserved relationship always holds.

A customer's `outstanding_balance_cents` is likewise derived: it is the sum of `amount_due_cents` across that customer's invoices whose status is `ISSUED` or `DISPUTED`, recomputed on every invoice mutation and floored at 0 so it can never go negative. Invoices in `PAID` or `VOIDED` status drop out of this sum. When an invoice is voided, the balance returns to exactly the value it held before that invoice was issued.

### 2.10. The Logical Clock

The server maintains a logical clock used for every `now()` reading the system performs. At startup the clock is fixed at exactly `2026-04-01T00:00:00Z`, and before any clock-setting call it reads exactly that default and never falls back to wall-clock time. An administrative test-driving capability advances the logical clock to a supplied `to_iso8601` instant, after which all subsequent time readings use the new value.

## 3. Business Logic & Workflows

### 3.1. Customers, Properties, Routes, and Technicians

The operational world is seeded by a `Dispatcher`, who registers the parties and places involved in service. A `Customer` is created with a `full_name` and an `email`, the latter unique across all customers, and an optional `credit_limit_cents` that defaults to 0. A credit limit of 0 means the customer has no credit and must effectively prepay — the credit gate described in §3.5 treats it as zero headroom. On creation the customer's `status` is `ACTIVE` and the derived `outstanding_balance_cents` is 0. A `BillingAdmin` may later suspend a customer, moving `status` to `SUSPENDED`; while a customer is `SUSPENDED`, new quote and visit creation for that customer is blocked with `ERR_INVALID_STATE`. This `SUSPENDED` gate is evaluated before the optimistic-concurrency check on quote creation, so a suspended customer's quote create is rejected with `ERR_INVALID_STATE` even when the supplied `expected_property_version` is stale. The two recognized values of customer `status` are `ACTIVE` and `SUSPENDED`.

A `Technician` is created with a `full_name` and two safety attributes: `ladder_cert_max_stories`, the greatest building height in stories the technician may safely reach by ladder, defaulting to 1; and `insurance_status`, defaulting to `ACTIVE`, whose two values are `ACTIVE` and `EXPIRED`. A technician with `EXPIRED` insurance may not be confirmed onto any visit. The technician's `scheduled_minutes` is a computed field that starts at 0 and tracks committed crew time as described in §2.9.

A `Route` names a geographic service zone with a `name` and a `travel_buffer_minutes` value that defaults to 30; this buffer pads the technician interval-overlap check described in §3.6. A `Property` belongs to a customer and a route: it is created with a `customer_id`, a `route_id`, an `address`, a `stories` count, and the three measured surface areas `roof_sqft`, `siding_sqft`, and `concrete_sqft`, each of which defaults to 0. The `stories` count drives both the height surcharge on pricing and the ladder-reach gate on crew assignment.

### 3.2. Building, Sending, and Revising a Quote

A `ServiceQuote` is the priced scope for a property. A `Dispatcher` opens a quote against a `property_id`, optionally setting `soiling_level`, which defaults to `MODERATE` and takes the values `LIGHT`, `MODERATE`, or `HEAVY`. The soiling level drives the chemical dose tier described below. A new quote begins in `DRAFT` status; the full set of quote statuses is `DRAFT`, `SENT`, `ACCEPTED`, `DECLINED`, and `SUPERSEDED`. Creating a quote is also an optimistic-concurrency write: it carries `expected_property_version` and, on success, supersedes the prior non-terminal quote on the same property, as detailed in §2.6 and §3.3.

Into a `DRAFT` quote, the dispatcher adds one or more line items. A `QuoteLineItem` carries a `quote_id` linking it to its parent quote, a `surface_type` (one of `ROOF`, `SIDING`, or `CONCRETE`), a `service_type` (one of `ROOF_SOFT_WASH`, `HOUSE_WASH`, or `CONCRETE_CLEAN`), and a `measured_sqft` area. On creation the system computes two derived values for the line: the chemical dose `chemical_dose_oz` and the priced `line_total_cents`.

The chemical dose, expressed in fluid ounces of sodium hypochlorite, is derived from three inputs: the line's `measured_sqft`, the line's `service_type`, and the parent quote's `soiling_level`. First, take a base concentration per 100 square feet that depends on the service type — 6 ounces for `ROOF_SOFT_WASH`, 3 ounces for `HOUSE_WASH`, and 4 ounces for `CONCRETE_CLEAN`. Multiply that base by the number of hundred-square-foot units in the line, that is, by `measured_sqft` divided by 100. Then apply the soiling tier multiplier — 0.8 for `LIGHT`, 1.0 for `MODERATE`, and 1.4 for `HEAVY`. The resulting raw ounce figure is then clamped into the safe mixing band: it is first capped at the maximum tank capacity of 320.0 ounces (the raw figure or 320.0, whichever is smaller), and then raised to the priming minimum of 8.0 ounces if it falls below it (the just-capped figure or 8.0, whichever is larger). The final dose is rounded to one decimal place, round-half-up.

The line price is derived from the same `measured_sqft` together with three multipliers. Begin with a surface rate in cents per square foot keyed on `surface_type` — 22 cents for `ROOF`, 15 cents for `SIDING`, and 11 cents for `CONCRETE`. Apply a service multiplier keyed on `service_type` — 1.25 for `ROOF_SOFT_WASH`, 1.0 for `HOUSE_WASH`, and 1.1 for `CONCRETE_CLEAN`. Apply a height multiplier equal to 1.0 plus 0.10 for each story above the first; that is, 1.0 plus 0.10 multiplied by the property's `stories` minus one. Multiply `measured_sqft` by the surface rate, by the service multiplier, and by the height multiplier, and round the product half-up to whole cents to obtain `line_total_cents`. This per-line rounding happens before any summation, per §2.5.

A quote may be sent only when it holds at least one line item. Sending a quote that has an empty line-item set is rejected with `ERR_QUOTE_EMPTY`. Sending is the act of a `Dispatcher` and is legal only from `DRAFT` status; attempting it from any other status yields `ERR_INVALID_STATE`. Sending advances the quote from `DRAFT` to `SENT` and freezes its monetary totals in a pinned order. First the `subtotal_cents` is computed as the sum of the already-rounded `line_total_cents` across all of the quote's line items. Second, the `travel_surcharge_cents` is computed from the subtotal as described next. Third, the `total_cents` is set to the sum of `subtotal_cents` and `travel_surcharge_cents`. This subtotal-then-surcharge-then-total order is mandatory.

The travel surcharge is a function of the subtotal alone, never of the total — this is what breaks the apparent circularity between total and surcharge. If `subtotal_cents` is at least 5,000,000 cents (that is, fifty thousand dollars), the surcharge is 0, because large jobs ship with free travel. Otherwise, if `subtotal_cents` is at least 1,500,000 cents (fifteen thousand dollars), the surcharge is half of the flat travel charge, that is, 7,500 cents divided by two. Otherwise the surcharge is the full flat travel charge of 7,500 cents (seventy-five dollars). The result is rounded half-up to whole cents, since the halved branch can be fractional. Note that a subtotal of exactly 1,500,000 cents falls in the half-travel branch, not the full-travel branch, because the comparison is "at least".

A `SENT` quote can be revised back into editing. When a `Dispatcher` revises a quote, it returns from `SENT` to `DRAFT` — legal only from `SENT`, otherwise `ERR_INVALID_STATE` — reopening it for line-item edits and clearing the frozen subtotal and total so they recompute on the next send. This `SENT → DRAFT → SENT` cycle is the revision loop.

### 3.3. The Customer's Quote Decision and Supersede

A `Customer` who owns the quoted property decides on a `SENT` quote. Accepting advances the quote from `SENT` to `ACCEPTED`; it is legal only from `SENT` (otherwise `ERR_INVALID_STATE`) and only when the acting customer owns the quote's property (otherwise `ERR_NOT_RESOURCE_OWNER`). An `ACCEPTED` quote becomes eligible to back visits and recurring plans. Declining a `SENT` quote advances it to the terminal `DECLINED` status, again legal only from `SENT`.

Supersede is a system-driven transition, not a client action. When a newer quote is created on a property that already has a non-terminal quote, the prior quote — whether it was in `DRAFT`, `SENT`, or `ACCEPTED` — is moved to the terminal `SUPERSEDED` status, and the property's `version` is incremented by one. Because that version bump is exactly what the optimistic-concurrency check on quote creation guards (§2.6), a create that still carries the pre-supersede property version observed a stale view and is rejected with `ERR_STALE_VERSION`.

### 3.4. Weather Windows and Routes

Weather governs whether work can be scheduled. A `Dispatcher` records a `WeatherWindow` against a `route_id`, supplying a `window_start_utc`, a `window_end_utc` strictly later than the start, a `wind_mph` reading, and an optional `precip_flag` that defaults to false. The window's `condition` is derived, not supplied: it is `BLOCKED` if the `wind_mph` is at least the maximum safe wind of 35 mph, or if `precip_flag` is true; otherwise it is `CLEAR`. The two condition values are `CLEAR` and `BLOCKED`.

A weather window covers a closed forecast interval that includes both its start and end instants. On creation, the new window must not overlap any existing window on the same route; because the interval is closed, two windows that merely touch at an endpoint are considered to overlap and collide. An overlapping create is rejected with `ERR_WEATHER_WINDOW_OVERLAP`.

### 3.5. Scheduling a Visit: Weather, Credit, and Concurrency

A `Visit` is one execution of cleaning work at a property. A `Dispatcher` creates a one-off visit with a `property_id`, a `quote_id` naming the backing quote, a `scheduled_date` given as a `YYYY-MM-DD` UTC calendar day, and an optional `duration_minutes` estimating on-site minutes, which defaults to 120. On creation the visit's `route_id` is copied from the property's route, its `billing_status` is `UNBILLED`, and its `status` is `REQUESTED`. The backing quote referenced at creation must be in `ACCEPTED` status; a visit that references a non-accepted quote is rejected with `ERR_QUOTE_NOT_ACCEPTED`. The full set of visit statuses is `REQUESTED`, `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `RECLEAN_REQUESTED`, and `CANCELLED`; the billing-status values are `UNBILLED`, `BILLED`, and `VOIDED`.

Scheduling moves a visit from `REQUESTED` to `SCHEDULED` and is the gate where weather, credit, and concurrency all converge. The transition is legal only from `REQUESTED` (otherwise `ERR_INVALID_STATE`). It is an optimistic-concurrency write requiring `expected_visit_version` to equal the visit's current `version`, failing with `ERR_STALE_VERSION` otherwise (§2.6). There must be a weather window on the visit's route whose `condition` is `CLEAR` and whose closed interval covers the visit's `scheduled_date`; the `scheduled_date` is taken as the full UTC calendar day spanning from its `00:00:00` instant to its `23:59:59.999999` instant, and a window covers it when the window's closed interval intersects that day span at any point (it need not fully contain the day). Absent such a window, scheduling fails with `ERR_NO_CLEAR_WEATHER`. Finally, the credit gate applies: if the owning customer's `outstanding_balance_cents` plus this job's provisional amount would exceed the customer's `credit_limit_cents`, the schedule is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). On success, the visit's `provisional_cost_cents` is set to the backing quote's frozen `total_cents` — the estimate — and the visit's `version` is incremented by one. The backing quote here is the visit's own `quote_id` when set, or, for a plan-generated visit, the plan's `source_quote_id`.

If a forecast turns and a window becomes `BLOCKED`, a `Dispatcher` can unschedule a `SCHEDULED` visit, returning it to `REQUESTED`. Unscheduling is legal only from `SCHEDULED` (otherwise `ERR_INVALID_STATE`); it releases all of the visit's `RESERVED` and `CONFIRMED` crew assignments to `RELEASED` — each release freeing the technician's interval and decrementing that technician's `scheduled_minutes` by the assignment's `duration_minutes` — and clears `provisional_cost_cents` back to null. This is the re-schedule loop.

A `Dispatcher` may cancel a visit while it is `REQUESTED` or `SCHEDULED`, moving it to the terminal `CANCELLED` status; from any other status the cancel is rejected with `ERR_INVALID_STATE`. Cancelling likewise releases all `RESERVED` and `CONFIRMED` crew assignments to `RELEASED`, decrementing the affected technicians' `scheduled_minutes`. A visit may also be cancelled by the system when its parent recurring plan is cancelled, with the same release cascade.

### 3.6. Staffing a Visit: Ladder Safety, Insurance, and Double-Booking

Crew is attached to a visit through a `CrewAssignment`, created by a `Dispatcher` with a `visit_id`, a `technician_id`, and a `window_start_utc` marking the start of the technician's on-site interval. The assignment's `duration_minutes` is copied from the visit at reservation time and defines the interval end as the start plus that duration; the interval is treated as half-open, including its start instant but excluding its end. A new assignment begins in `RESERVED` status; the three assignment statuses are `RESERVED`, `CONFIRMED`, and `RELEASED`. On reservation the technician's `scheduled_minutes` increases by the assignment's `duration_minutes`.

Two safety checks guard reservation. First, the ladder-reach gate: the assigned technician's `ladder_cert_max_stories` must be at least the property's `stories`, because ladder reach is a physical gate that must hold before a technician is put on the job; a shortfall is rejected with `ERR_TECH_NOT_ASSIGNABLE` (HTTP 403). Second, the double-booking gate: the new assignment's interval must not overlap any of that technician's existing `RESERVED` or `CONFIRMED` intervals. For this overlap test the half-open interval is padded on both sides by the route's `travel_buffer_minutes`, so that setup and travel time is respected; an overlap is rejected with `ERR_TECH_DOUBLE_BOOKED`.

Confirming an assignment moves it from `RESERVED` to `CONFIRMED`, legal only from `RESERVED` (otherwise `ERR_INVALID_STATE`). Because insurance can lapse between reservation and confirmation, the technician's assignability is re-checked at confirm time: the technician's `insurance_status` must be `ACTIVE` and the technician's `ladder_cert_max_stories` must still be at least the property's `stories`. If either fails, confirmation is rejected with `ERR_TECH_NOT_ASSIGNABLE`. A `Dispatcher` may release a `RESERVED` or `CONFIRMED` assignment directly, moving it to the terminal `RELEASED` status (otherwise `ERR_INVALID_STATE`); releasing frees the technician's interval and decrements the technician's `scheduled_minutes` by the assignment's `duration_minutes`, preserving the conserved-minutes relationship of §2.9. Assignments are also released by the system when their visit is unscheduled or cancelled, or when the parent plan is cancelled.

### 3.7. Performing the Visit: Photos, Completion, and Final Cost

Two photo gates bracket the on-site work. A `FieldTech` uploads a `PhotoSet` for a visit, supplying a `phase` (either `BEFORE` or `AFTER`) and a `photo_url`. A `BEFORE` photo set must already exist before work can start, and an `AFTER` photo set before work can complete.

A `FieldTech` starts a `SCHEDULED` visit, moving it to `IN_PROGRESS`. Starting is legal only from `SCHEDULED` (otherwise `ERR_INVALID_STATE`), requires at least one crew assignment in `CONFIRMED` status (otherwise `ERR_NO_CONFIRMED_CREW`), and requires a `BEFORE` photo set on the visit (otherwise `ERR_BEFORE_PHOTO_MISSING`).

Completing a visit moves it from `IN_PROGRESS` to `COMPLETED`, legal only from `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`) and only when an `AFTER` photo set exists (otherwise `ERR_AFTER_PHOTO_MISSING`). At completion the `FieldTech` supplies the on-site re-measured areas — `re_measured_roof_sqft`, `re_measured_siding_sqft`, and `re_measured_concrete_sqft` — and the system re-derives the actual cost. For each line of the backing quote, take that surface's actual re-measured area, multiply by the same surface rate keyed on the line's `surface_type` (22, 15, or 11 cents per square foot for `ROOF`, `SIDING`, `CONCRETE`), by the same service multiplier keyed on `service_type` (1.25, 1.0, or 1.1), and by the same height multiplier of 1.0 plus 0.10 for each story above the first, then round that line half-up to whole cents. Sum the rounded per-line amounts into an actual subtotal, then add the travel surcharge computed from that actual subtotal using the very same tiered surcharge rule as a quote (0 at or above 5,000,000 cents, half of 7,500 at or above 1,500,000 cents, otherwise the full 7,500 cents, rounded half-up). The result is the visit's `final_cost_cents`. A re-clean visit — one whose `reclean_of_visit_id` is set — is free: its `final_cost_cents` is 0 regardless of measurements.

Completion has further side effects. The completed visit becomes invoiceable and an invoice is auto-issued (§3.8). If the visit carries a `plan_id`, the parent plan's `next_due_utc` advances by the plan's `cadence_days`, while the plan's `visits_generated_count` is left unchanged by completion. The visit's `provisional_cost_cents`, set at scheduling, is the forward-looking estimate; the `final_cost_cents` is the actual figure and diverges from the provisional whenever the re-measured areas differ from the quoted areas. The `final_cost_cents` is null until the visit reaches `COMPLETED`.

### 3.8. Per-Visit Billing and the Invoice Lifecycle

Completing a visit auto-issues exactly one `Invoice` for that single visit — billing is strictly per visit. The invoice carries the `visit_id` it bills, a `customer_id` copied from the visit's property owner at issuance, an `amount_due_cents`, a `loyalty_discount_cents`, and a `status` that begins at `ISSUED`. The four invoice statuses are `ISSUED`, `PAID`, `DISPUTED`, and `VOIDED`. On issuance the visit's `billing_status` flips to `BILLED` and the owning customer's `outstanding_balance_cents` is recomputed.

The amount due is the visit's `final_cost_cents` reduced by a loyalty discount. The loyalty discount rewards recurring-plan tenure: let the count be the parent plan's `visits_generated_count` when the visit carries a `plan_id`, or 0 for a one-off visit. If that count is at least 10, the discount percentage is 0.15; otherwise if it is at least 5, the percentage is 0.10; otherwise if it is at least 2, the percentage is 0.05; otherwise it is 0. The `loyalty_discount_cents` is the `final_cost_cents` multiplied by that percentage, rounded half-up to whole cents. The `amount_due_cents` is the `final_cost_cents` minus the `loyalty_discount_cents`, floored at 0 so it can never be negative. Because a re-clean visit has a `final_cost_cents` of 0, both its `loyalty_discount_cents` and its `amount_due_cents` are 0.

A `BillingAdmin` records payment on an `ISSUED` invoice, moving it to the terminal `PAID` status; this is legal only from `ISSUED` (otherwise `ERR_INVALID_STATE`) and recomputes the customer's `outstanding_balance_cents`, from which paid invoices drop out. A `Customer` who owns an invoice may dispute it while it is `ISSUED`, moving it to `DISPUTED`; this is legal only from `ISSUED` (otherwise `ERR_INVALID_STATE`) and only for the owning customer (otherwise `ERR_NOT_RESOURCE_OWNER`), and it leaves `outstanding_balance_cents` unchanged because a disputed invoice remains in the balance sum. A disputed invoice can subsequently be paid by a `BillingAdmin`, moving it from `DISPUTED` to `PAID` (legal only from `DISPUTED`, otherwise `ERR_INVALID_STATE`), again recomputing the balance.

Voiding reverses billing. A `BillingAdmin` may void an invoice that is `ISSUED` or `DISPUTED`, moving it to the terminal `VOIDED` status (from any other status, `ERR_INVALID_STATE`). Voiding has a three-part cascade: the invoice moves to `VOIDED`; the linked visit's `billing_status` is set to `VOIDED`; and the customer's `outstanding_balance_cents` is recomputed to drop this invoice's `amount_due_cents`, restoring the balance to exactly the value it held before the invoice was issued.

### 3.9. Recurring Plans and Cascading Cancellation

A `RecurringPlan` services a property on a cadence. A `Dispatcher` creates a plan with a `property_id`, a `source_quote_id` that must name an `ACCEPTED` quote (otherwise `ERR_QUOTE_NOT_ACCEPTED`) whose line items define each visit's scope and base price, a `cadence_days` interval, and a `start_utc` start instant. On creation the plan's `status` is `ACTIVE`, its `next_due_utc` is set to the supplied start, and its `visits_generated_count` is 0. The two plan statuses are `ACTIVE` and `CANCELLED`.

Generating a visit under an `ACTIVE` plan creates a new `Visit` whose `plan_id` is the plan, whose `quote_id` is the plan's `source_quote_id`, whose `route_id` is copied from the property's route, whose `scheduled_date` is the calendar-day prefix (`YYYY-MM-DD`) of the plan's current `next_due_utc`, and whose `status` is `REQUESTED`, optionally taking a `duration_minutes` that defaults to 120 when omitted; this action increments the plan's `visits_generated_count` by one. The plan's `next_due_utc` first equals the start instant and then advances by `cadence_days` on each visit completion under the plan, as described in §3.7.

Cancelling a plan is a depth-three cascade originating from a `Dispatcher` and legal only while the plan is `ACTIVE` (otherwise `ERR_INVALID_STATE`). First, the plan moves to the terminal `CANCELLED` status. Second, every visit under the plan that is still `REQUESTED` or `SCHEDULED` is moved to `CANCELLED`. Third, each of those cancelled visits' `RESERVED` and `CONFIRMED` crew assignments is moved to `RELEASED`, each release decrementing the relevant technician's `scheduled_minutes`. This propagation — plan to visits to assignments to technician minutes — completes atomically within the cancel request.

### 3.10. The Satisfaction Guarantee and Re-Clean Loop

A `Customer` who is dissatisfied with a `COMPLETED` visit files a `SatisfactionClaim`, supplying the `visit_id` and a free-text `reason`. A new claim begins in `OPEN` status; the three claim statuses are `OPEN`, `APPROVED`, and `REJECTED`.

A `Dispatcher` adjudicates an `OPEN` claim. Approving is legal only when the claim is `OPEN` (otherwise `ERR_INVALID_STATE`) and the linked visit is in `COMPLETED` status (otherwise `ERR_INVALID_STATE`). Approval is a two-hop cascade: first, a free re-clean `Visit` is spawned, whose `reclean_of_visit_id` is set to the claim's visit, covering the same property and scope — its `property_id`, `quote_id`, `plan_id`, `route_id`, `scheduled_date`, and `duration_minutes` are copied from the source visit — with `billing_status` `UNBILLED` and starting in `REQUESTED` status, and the claim's `reclean_visit_id` is set to that new visit; second, the source visit moves from `COMPLETED` to `RECLEAN_REQUESTED`, closing the completed-to-re-clean cycle. Because the spawned re-clean visit is free, when it is eventually completed its `final_cost_cents` and the resulting invoice's `amount_due_cents` are both 0. Rejecting a claim moves it from `OPEN` to the terminal `REJECTED` status, legal only from `OPEN` (otherwise `ERR_INVALID_STATE`), with no further effects.

### 3.11. Technician Risk Scoring

A `Dispatcher` may read a computed risk score for a technician in one of two modes, selected by the optional `mode` query parameter, which defaults to projected when omitted; a `mode` value other than `projected` or `chronological` is rejected with `ERR_INVALID_REQUEST`. The response `data` is not a resource envelope but an object carrying exactly two fields: `risk_score`, the integer score, and `mode`, the effective mode string. Both modes operate over the same technician's crew assignments but yield different numbers, and both clamp the final result into the range from 0 to a ceiling of 100 (the larger of 0 and the raw value, then the smaller of that and 100), expressed as an integer rounded half-up after weighting.

In **projected** mode, the score is forward-looking. Count the technician's currently committed assignments — those whose status is `RESERVED` or `CONFIRMED`. Multiply that count by the per-load risk weight of 20. Then, if the technician's `insurance_status` is `EXPIRED`, add the uninsured penalty of 50; if the insurance is `ACTIVE`, add nothing. Projected mode applies no decay.

In **chronological** mode, the score replays only history. Consider only those of the technician's assignments whose linked visit has reached `COMPLETED` status, ordered by the linked visit's `updated_at` ascending and then by the linked visit's `created_at` ascending — never by `id`. Walking that ordered list from the earliest completion, contribute for each assignment the per-load weight of 20 multiplied by a geometric decay of 0.5 raised to the position index, where the earliest completion has index 0, the next index 1, and so on. Chronological mode excludes the uninsured penalty entirely, since insurance is a forward-looking concern, and ignores assignments that are only `RESERVED` or `CONFIRMED` without a completed visit.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, including all state transitions, return `200 OK`. The administrative clock-setting endpoint returns `200 OK`. To reconstruct the request and response payloads, side effects, and preconditions for any endpoint below, refer back to the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Dispatcher |
| POST | `/customers` | Create a Customer | Dispatcher |
| GET | `/customers` | List Customers | Dispatcher, BillingAdmin |
| GET | `/customers/{id}` | Get a Customer (includes derived outstanding balance) | Dispatcher, BillingAdmin, Customer |
| POST | `/customers/{id}/suspend` | Suspend a Customer | BillingAdmin |
| POST | `/technicians` | Create a Technician | Dispatcher |
| GET | `/technicians` | List Technicians; filter by insurance status | Dispatcher |
| GET | `/technicians/{id}` | Get a Technician (includes derived scheduled minutes) | Dispatcher |
| GET | `/technicians/{id}/risk-score` | Read the technician risk score in projected or chronological mode | Dispatcher |
| POST | `/routes` | Create a Route / service zone | Dispatcher |
| GET | `/routes/{id}` | Get a Route | Dispatcher |
| POST | `/properties` | Create a Property for a Customer | Dispatcher |
| GET | `/properties` | List Properties; filter by customer or route | Dispatcher, Customer |
| GET | `/properties/{id}` | Get a Property | Dispatcher, Customer |
| POST | `/quotes` | Create a ServiceQuote for a Property (OCC on property version; supersedes prior quote) | Dispatcher |
| GET | `/quotes` | List ServiceQuotes; filter by property or status | Dispatcher, Customer |
| GET | `/quotes/{id}` | Get a ServiceQuote | Dispatcher, Customer |
| POST | `/quotes/{id}/line-items` | Add a QuoteLineItem; computes chemical dose and line total | Dispatcher |
| GET | `/quotes/{id}/line-items` | List QuoteLineItems for a quote | Dispatcher, Customer |
| POST | `/quotes/{id}/send` | Send a DRAFT quote; freezes subtotal/travel/total | Dispatcher |
| POST | `/quotes/{id}/revise` | Return a SENT quote to DRAFT for edits | Dispatcher |
| POST | `/quotes/{id}/accept` | Customer accepts a SENT quote | Customer |
| POST | `/quotes/{id}/decline` | Customer declines a SENT quote | Customer |
| POST | `/recurring-plans` | Create a RecurringPlan from an ACCEPTED quote | Dispatcher |
| GET | `/recurring-plans` | List RecurringPlans; filter by property or source quote | Dispatcher, Customer |
| GET | `/recurring-plans/{id}` | Get a RecurringPlan | Dispatcher, Customer |
| POST | `/recurring-plans/{id}/cancel` | Cancel a RecurringPlan; cascades to future visits | Dispatcher |
| POST | `/recurring-plans/{id}/generate-visit` | Generate the next due Visit under an ACTIVE plan | Dispatcher |
| POST | `/visits` | Create a one-off Visit against an ACCEPTED quote | Dispatcher |
| GET | `/visits` | List Visits; filter by property, quote, plan, route, reclean source, or status | Dispatcher, Customer, FieldTech |
| GET | `/visits/{id}` | Get a Visit (includes provisional/final cost and billing status) | Dispatcher, Customer, FieldTech |
| POST | `/visits/{id}/schedule` | Schedule a REQUESTED visit (OCC on visit version; weather + credit gates) | Dispatcher |
| POST | `/visits/{id}/unschedule` | Return a SCHEDULED visit to REQUESTED | Dispatcher |
| POST | `/visits/{id}/start` | FieldTech starts a SCHEDULED visit | FieldTech |
| POST | `/visits/{id}/complete` | FieldTech completes a visit; supplies re-measured areas; auto-issues an Invoice | FieldTech |
| POST | `/visits/{id}/cancel` | Cancel a REQUESTED/SCHEDULED visit | Dispatcher |
| GET | `/visits/{id}/photos` | List PhotoSets for a visit; filter by phase | Dispatcher, Customer, FieldTech |
| POST | `/visits/{id}/photos` | Upload a BEFORE or AFTER PhotoSet | FieldTech |
| POST | `/crew-assignments` | Reserve a technician for a visit (ladder/insurance + interval checks) | Dispatcher |
| GET | `/crew-assignments` | List CrewAssignments; filter by visit or technician | Dispatcher |
| GET | `/crew-assignments/{id}` | Get a CrewAssignment | Dispatcher |
| POST | `/crew-assignments/{id}/confirm` | Confirm a reserved assignment (re-checks assignability) | Dispatcher |
| POST | `/crew-assignments/{id}/release` | Release a reserved/confirmed assignment | Dispatcher |
| POST | `/weather-windows` | Create a forecast WeatherWindow on a route (closed-interval non-overlap) | Dispatcher |
| GET | `/weather-windows` | List WeatherWindows; filter by route | Dispatcher |
| GET | `/weather-windows/{id}` | Get a WeatherWindow | Dispatcher |
| GET | `/invoices` | List Invoices; filter by visit or customer | Dispatcher, BillingAdmin, Customer |
| GET | `/invoices/{id}` | Get an Invoice | Dispatcher, BillingAdmin, Customer |
| POST | `/invoices/{id}/pay` | Mark an invoice PAID | BillingAdmin |
| POST | `/invoices/{id}/dispute` | Customer disputes an ISSUED invoice | Customer |
| POST | `/invoices/{id}/void` | Void an ISSUED/DISPUTED invoice; reverses billing on the visit | BillingAdmin |
| POST | `/satisfaction-claims` | File a satisfaction claim against a COMPLETED visit | Customer |
| GET | `/satisfaction-claims` | List SatisfactionClaims; filter by disputed visit or spawned re-clean visit | Dispatcher, Customer |
| GET | `/satisfaction-claims/{id}` | Get a SatisfactionClaim | Dispatcher, Customer |
| POST | `/satisfaction-claims/{id}/approve` | Approve a claim; spawns a free re-clean visit | Dispatcher |
| POST | `/satisfaction-claims/{id}/reject` | Reject a claim | Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_NOT_FOUND` | 404 Not Found |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_WEATHER_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_QUOTE_EMPTY` | 409 Conflict |
| `ERR_QUOTE_NOT_ACCEPTED` | 409 Conflict |
| `ERR_NO_CONFIRMED_CREW` | 409 Conflict |
| `ERR_BEFORE_PHOTO_MISSING` | 409 Conflict |
| `ERR_AFTER_PHOTO_MISSING` | 409 Conflict |
| `ERR_NO_CLEAR_WEATHER` | 409 Conflict |
| `ERR_WEATHER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TECH_NOT_ASSIGNABLE` | 403 Forbidden |
| `ERR_TECH_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
