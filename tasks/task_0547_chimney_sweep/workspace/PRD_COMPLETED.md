# Chimney Sweep & Fireplace Service API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Chimney Sweep & Fireplace Service API, the operational backbone for a field-services company that inspects, sweeps, and repairs residential chimneys and fireplace appliances. The business coordinates three distinct groups of people — a front office that books work and manages the customer book, field technicians who perform inspections and physical work on the roof and in the firebox, and a billing team that closes out jobs and stands behind the work with warranties. The API must keep all three in step while enforcing the safety, scheduling, and fiscal rules that govern regulated hearth work.

The domain is unusually rich because a single service job simultaneously tracks two independent stories: where the job is in its operational lifecycle (booked, on-site, closed) and what the technician has concluded about the safety of the appliance (safe to use, usable only under conditions, or outright condemned). These two dimensions evolve on their own timelines and must never be conflated. Layered on top are tiered sweep pricing that depends on how much creosote is actually found, a repair sub-workflow that can stall and resume, warranty proration that decays over the coverage term, route scheduling with capacity and travel-buffer constraints, and a recurring annual reminder that keeps homeowners coming back. Because pricing and safety outcomes are only known partway through a visit, many values are provisional at booking and finalized on site; the specification is careful to distinguish the two.

To make time-dependent behavior testable, the system runs on a logical clock rather than wall-clock time. All "now" comparisons — warranty expiry, reminder due dates, service dates — resolve against this logical clock, which can be advanced by an operator during testing.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply across every endpoint. Most of it is contract-level: response shape, pagination, common properties, precision, and the cross-cutting consistency and safety principles that individual workflows in §3 rely upon.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing or empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS`. The system recognizes exactly three roles: `Dispatcher`, `Technician`, and `BillingClerk`. When a role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE`.

The three roles partition the work. A `Dispatcher` runs the front office: creating customers, chimneys, technicians, and route days; opening and cancelling service jobs; booking appointments; proposing, approving, rejecting, and cancelling repair orders; and creating and acknowledging reminders. A `Technician` performs field work: inspections, sweeps, safety checks, driving appointments through their on-site lifecycle, and starting, blocking, resuming, and completing repairs. A `BillingClerk` handles money: completing jobs (which finalizes the invoice), issuing warranties, and processing warranty claims. Every role may call all read (GET) endpoints.

Two roles are opaque operator identities. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same holds when `X-User-Role` is `BillingClerk`: the identifier is opaque and is not matched against stored records. The `Technician` role is different: it is entity-backed. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` record. Ownership checks compare a resource's technician foreign key against this identifier. Specifically, when a technician drives an appointment through its lifecycle, `X-User-ID` must equal that appointment's `technician_id`; a mismatch is rejected with `ERR_TECH_IDENTITY_MISMATCH`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. A supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100; these out-of-range numeric values are clamped rather than rejected. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` that is not parseable as an integer is rejected with `ERR_VALIDATION`.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- `id`: a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp (three fractional digits) marking when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp marking the most recent modification. Any change to a resource's fields — including recomputation of a derived field such as `booked_minutes`, `committed_cost_cents`, or a state transition — refreshes this timestamp.
- `version`: an integer that starts at 1 on creation and increments by one on every mutation. It underpins the optimistic concurrency rule in §2.10.

Two record types are append-only measurement logs and are deliberately leaner: `SweepLog` and `SafetyCheck` carry only `id` and `created_at`. They have neither an `updated_at` nor a `version`, because once written they are never modified. All other resources — customers, chimneys, technicians, route days, service jobs, appointments, repair orders, warranties, and reminder schedules — carry the full set above.

### 2.5. The Logical Service Clock

The system keeps a single logical clock that stands in for "now" everywhere the business logic needs the current instant — setting a chimney's `last_service_date`, stamping a warranty's `issued_at`, computing a reminder's `next_due_date`, deciding whether a reminder `is_due`, and measuring warranty elapsed time at claim. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any operator sets it, it stays fixed at that default and never falls back to real wall-clock time. Any of the three roles may advance the clock by supplying a target instant `to_iso8601`; after the call, logical "now" equals that instant. Tests use this capability to fast-forward past warranty terms and reminder cadences.

### 2.6. Monetary Precision and Cent Arithmetic

All money is represented and stored as whole integer cents; there are no fractional cents anywhere in a stored value. Sweep pricing, repair costs, and committed totals are sums of whole-cent terms and therefore require no rounding. Two calculations do introduce rounding because they multiply by a rate or a fraction, and both use the "round half up" method to the nearest whole cent:

- The invoice disposal fee (§3.6) is rounded half up to whole cents **per line item, before the lines are summed**. Rounding once on the summed total is not equivalent and is not permitted; the per-line order is authoritative.
- The prorated parts portion of a warranty claim credit (§3.7) is rounded half up to whole cents.

### 2.7. The Parallel Posture Model and Safety Governance

A `ServiceJob` carries two independent state dimensions that advance on separate timelines and must never be collapsed into one. The first is `job_status` — the operational lifecycle (`DRAFT`, `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`). The second is `safety_posture` — the technician's live safety verdict (`PENDING`, `SAFE`, `CONDITIONS`, `UNSAFE`, `CONDEMNED`). A job can be `IN_PROGRESS` while its posture is anything; the two are orthogonal.

`safety_posture` begins at `PENDING` and is only ever changed by on-site evidence: a recorded safety check, a flue inspection result, or a heavy-creosote sweep. `CONDEMNED` is terminal — once a job's posture reaches `CONDEMNED`, no later evidence can move it. Several operations are gated on posture: a repair may only be started or resumed, a job may only be completed, and a warranty may only be issued when the job's `safety_posture` is either `SAFE` or `CONDITIONS`. If any of these is attempted while the posture is `PENDING`, `UNSAFE`, or `CONDEMNED`, the request is rejected with `ERR_JOB_UNSAFE`.

The carbon-monoxide thresholds that drive posture are exact integer comparisons. A reading of at least 70 ppm condemns the appliance; a reading of at least 9 ppm (but below 70) fails it. The boundary is inclusive at 9 — a reading of 8 ppm passes that particular check, a reading of 9 ppm does not. The full derivation lives in §3.4.

### 2.8. Cascading Consistency and Derived-Value Recomputation

Several fields are aggregates that the server maintains, never the client. A `RouteDay`'s `booked_minutes` is always the sum of `on_site_minutes` over that day's appointments whose status is neither `CANCELLED` nor `NO_SHOW`; it starts at 0. A `ServiceJob`'s `committed_cost_cents` is always its `sweep_provisional_cost_cents` plus the sum of `provisional_cost_cents` over its repair orders whose status is neither `REJECTED` nor `CANCELLED`. Both are invariants: booking an appointment and then cancelling it restores `booked_minutes` exactly, and proposing a repair and then cancelling or rejecting it returns `committed_cost_cents` to exactly the value implied by the surviving orders. Each such recomputation that actually changes the stored aggregate is a mutation of the owning resource and therefore refreshes its `updated_at` and bumps its `version`; a recomputation that leaves the value unchanged is a no-op and touches neither.

When a parent resource is torn down, its dependents must be resolved in a well-defined cascade rather than left dangling. Cancelling a service job, for example, propagates through appointments, releases their booked minutes, cancels open repairs, and voids issued warranties. The precise cascade steps are described with the workflows that drive them in §3.

### 2.9. Nested Resource Retrieval and Left-to-Right Validation

When an endpoint path names more than one resource — for instance a job together with one of its sub-resources — the identifiers are validated in strict left-to-right order, and the first identifier that does not resolve determines the error. A request that references a sub-resource under a non-existent service job fails with `ERR_SERVICE_JOB_NOT_FOUND` before the sub-resource is ever considered. The same left-to-right rule governs foreign keys supplied in a request body: each referenced resource must exist, and the corresponding not-found error is raised for the first that does not. The catalogue of not-found errors is `ERR_CUSTOMER_NOT_FOUND`, `ERR_CHIMNEY_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_ROUTE_DAY_NOT_FOUND`, `ERR_SERVICE_JOB_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_WARRANTY_NOT_FOUND`, and `ERR_REMINDER_NOT_FOUND`, each returning HTTP 404.

### 2.10. Optimistic Concurrency on Chimney Reminders

At most one `ACTIVE` `ReminderSchedule` may exist for a given chimney. Creating a new reminder legitimately supersedes any prior `ACTIVE` schedule for that chimney (deactivating it) and, as part of that act, increments the chimney's `version`. To prevent a client from creating a reminder against a stale view of which schedule is currently active, reminder creation is guarded by optimistic concurrency. The create request must carry `expected_chimney_version` holding the `version` of the target `Chimney` that the client last observed. If that value does not match the chimney's current `version` — because another writer has already superseded the reminder and advanced the version — the create is rejected with `ERR_STALE_CHIMNEY_VERSION` (HTTP 412). This is the only endpoint that takes a version field; no other write requires one.

### 2.11. Validation Ordering and Precedence

When several checks could apply to one request, they are evaluated in a fixed precedence so that the returned error is deterministic. The order is:

1. **Authentication headers** — `X-User-ID` and `X-User-Role` present and non-empty, else `ERR_MISSING_AUTH_HEADERS` (400).
2. **Role authorization** — the role may perform this operation, else `ERR_UNAUTHORIZED_ROLE` (403).
3. **Technician identity** — for a technician-driven appointment transition, `X-User-ID` equals the appointment's `technician_id`, else `ERR_TECH_IDENTITY_MISMATCH` (403).
4. **Path existence** — every id in the path resolves, left-to-right, else the matching 404.
5. **Foreign-key existence** — every foreign key in the body resolves, else the matching 404.
6. **Shape and enum domains** — required fields present and enum/numeric domains valid, else `ERR_VALIDATION`, `ERR_INVALID_INSPECTION_LEVEL`, or `ERR_INVALID_CREOSOTE_CLASS` (400).
7. **State validity** — the target is in a legal state for the operation, else the appropriate 409 (`ERR_INVALID_STATE_TRANSITION`, `ERR_JOB_NOT_IN_PROGRESS`, `ERR_JOB_HAS_OPEN_REPAIRS`, `ERR_JOB_TERMINAL`, `ERR_REPAIR_NOT_COMPLETED`, `ERR_WARRANTY_NOT_CLAIMABLE`, or `ERR_REMINDER_NOT_DUE`).
8. **Temporal validity** — appointment and warranty timing rules, else a 422 (`ERR_INVALID_APPOINTMENT_WINDOW`, `ERR_APPOINTMENT_OUTSIDE_WINDOW`, or `ERR_WARRANTY_EXPIRED`).
9. **Safety posture** — posture is `SAFE` or `CONDITIONS` where required, else `ERR_JOB_UNSAFE` (403).
10. **Part referential integrity** — repair part rules, else `ERR_PART_REQUIRED` or `ERR_UNKNOWN_PART` (422).
11. **Scheduling conflicts** — technician double-booking and travel buffer, else `ERR_TECHNICIAN_DOUBLE_BOOKED` (409).
12. **Fiscal limits** — repair authorization ceiling and route capacity, else `ERR_REPAIR_COST_EXCEEDS_AUTH` or `ERR_ROUTE_CAPACITY_EXCEEDED` (402).
13. **Optimistic concurrency** — `expected_chimney_version` matches, else `ERR_STALE_CHIMNEY_VERSION` (412).

A check earlier in this list always takes precedence over one later in the list when both would fail.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Customers, Chimneys, Technicians, and Route Days

Everything begins in the front office. A `Dispatcher` records a homeowner as a `Customer`, capturing their `name`, `service_address` (the street address where the chimney lives), and `phone`; an `email` is optional and, if not supplied, is stored as null. Any of the three roles can later look a customer up by id.

Each physical chimney is registered against its owning homeowner. When a `Dispatcher` creates a `Chimney`, the payload names the owning `customer_id` and describes the structure: its `chimney_type` (one of `MASONRY`, `PREFAB_METAL`, or `FACTORY_BUILT`), the connected `appliance_type` (one of `WOOD_STOVE`, `OPEN_FIREPLACE`, `GAS_INSERT`, or `PELLET`), and the `flue_count`, which must be at least 1. Three descriptors are optional and take defaults when omitted: `cap_installed` records whether a rain cap is currently fitted and defaults to false; `liner_type` is one of `NONE`, `CLAY`, `STAINLESS`, or `ALUMINUM` and defaults to `NONE`; and `damper_type` is one of `THROAT`, `TOP_MOUNT`, or `NONE` and defaults to `THROAT`. A chimney also carries a `last_service_date`, which is null until a service job for it completes, at which point it is stamped with the logical clock's current instant. Chimneys may be listed, optionally filtered by `customer_id`.

Technicians are the field staff. A `Dispatcher` creates a `Technician` with a `name` and a `cert_level` — one of `CSIA_BASIC`, `CSIA_ADVANCED`, or `MASTER`. The technician's server-minted `id` is what a person supplies in `X-User-ID` when acting in the `Technician` role.

A `RouteDay` is a technician's bookable day in the field. The `Dispatcher` creates it against a `technician_id`, a calendar `service_date` label in `YYYY-MM-DD` form, and a working window bounded by `window_start_ts` and `window_end_ts` (both Unix-seconds instants, with the end required to be strictly after the start). The day also carries a `capacity_minutes` ceiling — the maximum aggregate on-site minutes that may be booked — which must be at least 0. The server tracks `booked_minutes` on the day, starting at 0 and always equal to the sum of on-site minutes across that day's live appointments as described in §2.8. Route days may be fetched individually (the response includes the current `booked_minutes`) or listed, optionally filtered by `technician_id`.

### 3.2. Opening a Service Job and the Provisional Quote

A service job is the central unit of work, and it is opened by a `Dispatcher`. The create payload names the `customer_id` and the `chimney_id`, and sets the CSIA `inspection_level`, which must be 1, 2, or 3 — any other value is `ERR_INVALID_INSPECTION_LEVEL`. Three inputs are optional and shape the initial quote: `expected_creosote_class` is the creosote class assumed at booking (1, 2, or 3; defaults to 1, and any out-of-domain value is `ERR_INVALID_CREOSOTE_CLASS`); `trip_zone` is the travel zone driving the trip fee (one of `A`, `B`, or `C`; defaults to `A`); and `repair_authorization_cents` is the homeowner-approved ceiling for any single repair order's quoted cost (defaults to 0, must be at least 0).

At creation the job's three system dimensions are seeded: `job_status` starts at `DRAFT`, `safety_posture` at `PENDING`, and `flue_assessment` at `UNASSESSED`. The server also computes the **provisional sweep quote** and stores it in `sweep_provisional_cost_cents`. That quote is built from four tiered terms. The base charge is set by inspection level: 15000 cents for level 1, 24000 cents for level 2, and 40000 cents for level 3. A creosote surcharge is added by class: nothing for class 1, 6000 cents for class 2, and 18000 cents for class 3 — and the provisional quote uses `expected_creosote_class` for this term while treating the glaze condition as absent (a zero glaze surcharge). A trip fee is added by zone: 0 cents for zone `A`, 3500 cents for zone `B`, and 7000 cents for zone `C`. The provisional quote is the sum of base, creosote surcharge, glaze surcharge, and trip fee. Immediately after, `committed_cost_cents` is initialized to equal `sweep_provisional_cost_cents`, since no repairs exist yet. The job's `sweep_final_cost_cents` and `invoice_total_cents` are both null at this point and remain so until, respectively, the sweep is logged and the job is completed. Jobs can be fetched with all computed fields, or listed with optional `customer_id`, `chimney_id`, and `job_status` filters.

### 3.3. Scheduling: Appointments, Capacity, and the Travel Buffer

To put a job on the calendar, a `Dispatcher` books an `Appointment`, which ties together a `route_day_id`, a `service_job_id`, and a `technician_id`, along with the on-site `start_ts` and `end_ts` (Unix seconds; the end must be strictly after the start). The server derives `on_site_minutes` as the elapsed seconds divided by 60 using integer (floor) division, discarding any sub-minute remainder. A new appointment starts in `SCHEDULED` and carries a `no_show_reason` that is null unless and until it is later marked a no-show.

Several rules guard a booking. Temporally, if `end_ts` is not strictly after `start_ts` (non-positive on-site minutes) the booking is rejected with `ERR_INVALID_APPOINTMENT_WINDOW`; and the appointment must fall entirely within the route day's window, meaning both `start_ts` and `end_ts` lie inside the span from `window_start_ts` to `window_end_ts`, else `ERR_APPOINTMENT_OUTSIDE_WINDOW`. The appointment's `technician_id` must equal the route day's `technician_id`; and the technician must be free — the new interval, treated as half-open from `start_ts` up to but not including `end_ts`, may not overlap another of that technician's non-cancelled appointments, and consecutive appointments must be separated by a gap of at least 30 minutes of travel buffer. A violation of the technician match, an overlap, or an insufficient gap all raise `ERR_TECHNICIAN_DOUBLE_BOOKED`. Finally, the day must have room: the day's current `booked_minutes` plus the new appointment's on-site minutes must not exceed `capacity_minutes`, else `ERR_ROUTE_CAPACITY_EXCEEDED`.

When a booking succeeds, the route day's `booked_minutes` grows by the new appointment's on-site minutes, and if the parent job was in `DRAFT` its `job_status` advances `DRAFT → SCHEDULED`. Appointments can be fetched individually or listed with optional `route_day_id`, `service_job_id`, and `technician_id` filters.

Once on the calendar, an appointment is driven through its own lifecycle by supplying an `action`. A `Technician` departs for the site (`SCHEDULED → EN_ROUTE`), arrives (`EN_ROUTE → ON_SITE`), and completes (`ON_SITE → COMPLETED`); each of these is legal only from the immediately preceding state, and an out-of-sequence attempt is `ERR_INVALID_STATE_TRANSITION`. The arrival step is significant beyond the appointment itself: it advances the parent job `SCHEDULED → IN_PROGRESS`. A `Dispatcher` may instead cancel an appointment that is still `SCHEDULED` or `EN_ROUTE` (`→ CANCELLED`), or mark a still-`SCHEDULED` appointment a no-show (`→ NO_SHOW`), in which case the supplied `no_show_reason` is stored. Both cancellation and no-show release the appointment's minutes: the route day's `booked_minutes` drops by that appointment's on-site minutes. Because a technician-driven appointment transition is entity-backed, the acting `X-User-ID` must match the appointment's `technician_id`, as described in §2.1.

### 3.4. On-Site Field Work: Inspection, Sweep, and Safety Check

Once a technician is on site, three kinds of evidence can update the job — and only a `Technician` may record them. Recording any of the three is permitted regardless of the job's current `job_status`; no operational-lifecycle precondition is enforced on these evidence endpoints.

The flue inspection records a `flue_assessment` result, one of `UNASSESSED`, `PASS`, `DEFECTS`, or `BLOCKED`. Recording a result stores it on the job. A `BLOCKED` result is a hard stop: it condemns the appliance, driving `safety_posture` to `CONDEMNED` regardless of the current posture. Other results record the assessment without changing posture on their own.

The sweep is logged when the technician actually cleans the flue, and it creates an append-only `SweepLog`. The log names its `service_job_id`, the `measured_creosote_class` observed during the sweep (1, 2, or 3; anything else is `ERR_INVALID_CREOSOTE_CLASS`), and a `glaze_present` flag recording whether glazed, Class-3-style deposits were found (defaults to false). Logging the sweep computes the **final sweep cost** and writes it to the job's `sweep_final_cost_cents`, while the log's own `billed_cost_cents` mirrors that same amount. The final cost uses the identical tiered formula as the provisional quote — base by inspection level, creosote surcharge by class, glaze surcharge, and trip fee by zone — but with the actual field values rather than the booking assumptions: the creosote surcharge is taken from the `measured_creosote_class`, and a glaze surcharge of 5000 cents is added when `glaze_present` is true (and zero when false). Base charges (15000, 24000, 40000 cents for levels 1, 2, 3), creosote surcharges (0, 6000, 18000 cents for classes 1, 2, 3), and trip fees (0, 3500, 7000 cents for zones `A`, `B`, `C`) are exactly as in §3.2. A heavy sweep also affects safety: when the `measured_creosote_class` is 3, and only if the current posture is `PENDING` or `SAFE`, the posture moves to `CONDITIONS`.

The safety check records a live combustion reading and creates an append-only `SafetyCheck` naming its `service_job_id`, the ambient carbon-monoxide reading `co_ppm` (at least 0), the `draft_ok` flag for whether the draft/spillage test passed, and a `spillage_detected` flag for whether combustion spillage was observed (defaults to false). From these three inputs the server derives the check's `outcome`, one of `PASS`, `CONDITIONS`, `FAIL`, or `CONDEMN`, in strict order: if `co_ppm` is at least 70 the outcome is `CONDEMN`; otherwise if `co_ppm` is at least 9 or spillage was detected the outcome is `FAIL`; otherwise if the draft test did not pass the outcome is `CONDITIONS`; otherwise the outcome is `PASS`. The outcome then maps onto `safety_posture`, subject to `CONDEMNED` being terminal. A `PASS` sets the posture to `SAFE` (permitted from any posture except `CONDEMNED`). A `CONDITIONS` outcome sets the posture to `CONDITIONS`, permitted whenever the posture is not already `UNSAFE` or `CONDEMNED`. A `FAIL` sets the posture to `UNSAFE` (permitted from any posture except `CONDEMNED`). A `CONDEMN` sets the posture to `CONDEMNED` from any posture and is final. Both sweep logs and safety checks for a job can be listed by their reverse-lookup endpoints.

### 3.5. Repair Work: Proposal, Approval, and the Blocking Cycle

Repairs are proposed against a job as a `RepairOrder`. Either a `Technician` or a `Dispatcher` may propose one, naming the `service_job_id`, the `repair_type` (one of `CAP`, `LINER`, `DAMPER`, or `GAS_LOG_CONVERSION`), the `quoted_cost_cents` estimated at proposal time (at least 0), and, for parts-bearing work, a `part_sku`. A part is required for a `CAP`, `LINER`, or `DAMPER` repair and must be omitted for a `GAS_LOG_CONVERSION`; a missing part where one is required raises `ERR_PART_REQUIRED`. When present, the SKU must belong to the catalog for its repair type — a `CAP` accepts `CAP-STD` or `CAP-SS`, a `LINER` accepts `LNR-SS6` or `LNR-AL`, and a `DAMPER` accepts `DMP-TOP` or `DMP-THR` — and any other value is `ERR_UNKNOWN_PART`. Fiscally, the `quoted_cost_cents` may not exceed the parent job's `repair_authorization_cents`, else `ERR_REPAIR_COST_EXCEEDS_AUTH`. At proposal — that is, when the order is created and enters `PROPOSED` — the server snapshots `provisional_cost_cents` from the quoted amount and immediately recomputes the job's `committed_cost_cents` to fold this order in, per §2.8; a `PROPOSED` order already counts toward the committed sum, and approving it later changes neither value. A new order starts in `PROPOSED`. Its `final_cost_cents`, `labor_cents`, and `parts_cents` are all null until completion. Repair orders may be fetched or listed with optional `service_job_id` and `status` filters.

Repair orders move through their lifecycle via an `action`. A `Dispatcher` approves a `PROPOSED` order (`PROPOSED → APPROVED`) or rejects it (`PROPOSED → REJECTED`); either is legal only from `PROPOSED`, else `ERR_INVALID_STATE_TRANSITION`. Rejecting an order drops it out of the committed-cost sum, so the job's `committed_cost_cents` is recomputed. A `Technician` then starts an `APPROVED` order (`APPROVED → IN_PROGRESS`). Real jobs stall, so the order is cyclic: a `Technician` can block an `IN_PROGRESS` order (`IN_PROGRESS → BLOCKED`) and later resume it (`BLOCKED → IN_PROGRESS`); this block/resume pair may repeat any number of times. Both starting and resuming are safety-gated — the parent job's `safety_posture` must be `SAFE` or `CONDITIONS`, else `ERR_JOB_UNSAFE` — while blocking carries no such gate. A `Technician` completes an `IN_PROGRESS` order by supplying `final_cost_cents` and `labor_cents`; the labor portion may not exceed the final cost, else `ERR_VALIDATION`. Completion sets `final_cost_cents` and `labor_cents` and derives `parts_cents` as the final cost minus the labor. Each of these transitions is legal only from the state named as its source; any other origin is `ERR_INVALID_STATE_TRANSITION`.

A `Dispatcher` may cancel a repair order from any non-terminal state — `PROPOSED`, `APPROVED`, `IN_PROGRESS`, or `BLOCKED` — moving it to `CANCELLED`; cancelling an already-terminal order (`COMPLETED`, `REJECTED`, or `CANCELLED`) is `ERR_INVALID_STATE_TRANSITION`. Cancellation removes the order from the committed sum, so the job's `committed_cost_cents` is recomputed to its `sweep_provisional_cost_cents` plus the `provisional_cost_cents` of the surviving orders that are neither rejected nor cancelled. The invariant of §2.8 holds: any forward action followed by a compensating cancel returns `committed_cost_cents` to exactly the value implied by the orders that remain.

### 3.6. Closing the Job: Invoice Finalization and Reminder Advance

A job is closed by a `BillingClerk`. Completion is permitted only when the job is currently `IN_PROGRESS` — otherwise `ERR_JOB_NOT_IN_PROGRESS` — and only when its `safety_posture` is `SAFE` or `CONDITIONS`, otherwise `ERR_JOB_UNSAFE`. Completion is also blocked while any repair order on the job remains non-terminal, that is in `PROPOSED`, `APPROVED`, `IN_PROGRESS`, or `BLOCKED`; such an attempt is `ERR_JOB_HAS_OPEN_REPAIRS`. When all three preconditions hold, the job advances `IN_PROGRESS → COMPLETED`.

Completion finalizes the invoice into `invoice_total_cents`. The invoice is built from line items: the first line is the job's `sweep_final_cost_cents` (if no sweep was ever logged this value is still null and contributes no line at all), followed by the `final_cost_cents` of every repair order on the job in `COMPLETED` status (orders that are cancelled, rejected, or still open are excluded). The lines are processed in that pinned order. For each line, a disposal fee is computed as 4.5% of that line (the line multiplied by 0.045) and rounded half up to whole cents; the running total then increases by the line amount plus its rounded fee. The invoice total is the accumulated sum. Because each disposal fee is rounded per line before summing, computing the fee once on the summed lines is not equivalent and must not be used.

Completion also has two cross-entity effects. The parent `Chimney`'s `last_service_date` is set to the logical clock's current instant. And if the chimney has an `ACTIVE` reminder schedule, that schedule's `next_due_date` is reset to the current clock instant plus its `cadence_months`, rolling the recurring reminder forward to the next cycle.

A `Dispatcher` may instead cancel a job that has not yet terminated. The full cancellation cascade is described in §3.9.

### 3.7. Standing Behind the Work: Warranties and Claims

After a repair is completed, a `BillingClerk` may issue a `Warranty` for it. The issue payload names the `repair_order_id` being covered, the `service_job_id` it belongs to, a `coverage_type` (either `LABOR_ONLY` or `PARTS_INCLUSIVE`), and a `term_months` duration of at least 1 whole month. Issuance requires that the referenced repair order is actually `COMPLETED`; otherwise `ERR_REPAIR_NOT_COMPLETED`. The referenced repair order must belong to the named service job; if the order's `service_job_id` does not match the named `service_job_id`, the request is rejected with `ERR_REPAIR_ORDER_NOT_FOUND` (evaluated with the foreign-key existence checks, before the `COMPLETED` and safety gates). Issuance is also safety-gated: the job's `safety_posture` must be `SAFE` or `CONDITIONS`, else `ERR_JOB_UNSAFE`. On issuance the warranty's `issued_at` is stamped with the logical clock, and the covered amounts are snapshotted from the repair order — `covered_labor_cents` copies the order's `labor_cents` and `covered_parts_cents` copies its `parts_cents`. A new warranty starts in `ISSUED`, with `claimed_repair_type` and `last_claim_credit_cents` both null until a claim is filed. Warranties can be fetched or listed with optional `repair_order_id` and `service_job_id` filters.

A `BillingClerk` files a claim against a warranty by asserting the `claimed_repair_type` (one of `CAP`, `LINER`, `DAMPER`, or `GAS_LOG_CONVERSION`), moving it `ISSUED → CLAIMED`. A claim is only accepted on a warranty whose status is `ISSUED`; a claim against any other status is `ERR_WARRANTY_NOT_CLAIMABLE`. The claim must also be within term: the logical clock must be no later than `issued_at` advanced by `term_months` whole months, else `ERR_WARRANTY_EXPIRED`. On acceptance the asserted repair type is stored and the claim credit is computed into `last_claim_credit_cents`. The credit depends on coverage. For a `LABOR_ONLY` warranty, the credit is the full `covered_labor_cents`, with parts never covered and no proration. For a `PARTS_INCLUSIVE` warranty, first determine `elapsed_months` as the whole calendar months from `issued_at` to the current clock instant, taking the floor; the remaining fraction of the term is `term_months` minus `elapsed_months`, all divided by `term_months`; the credit is the full `covered_labor_cents` plus the `covered_parts_cents` multiplied by that remaining fraction, with the parts portion rounded half up to whole cents.

### 3.8. The Recurring Annual Reminder

To keep homeowners on a maintenance rhythm, a `Dispatcher` creates a `ReminderSchedule` for a chimney, naming the `customer_id` and the `chimney_id`, and optionally a `cadence_months` interval between reminders (at least 1; defaults to 12 months, one year). On creation the schedule's `next_due_date` is set to the current clock instant plus `cadence_months`, its `status` starts `ACTIVE`, and its `acknowledged_count` starts at 0. A derived `is_due` flag reads true exactly when the schedule is `ACTIVE` and the logical clock has reached or passed its `next_due_date`.

Because at most one active reminder may exist per chimney, creating a new schedule supersedes any prior `ACTIVE` one for the same chimney, moving that older schedule `ACTIVE → DEACTIVATED`, and — as the act of superseding — increments the chimney's `version`. This create is guarded by the optimistic-concurrency rule of §2.10: the request carries `expected_chimney_version`, and a mismatch with the chimney's current `version` is rejected with `ERR_STALE_CHIMNEY_VERSION`. Reminders may be fetched (the response includes the computed `is_due`) or listed with optional `customer_id`, `chimney_id`, and `status` filters.

A `Dispatcher` acknowledges a due reminder to advance it to its next cycle. Acknowledgement is a self-loop that keeps the schedule `ACTIVE`: it is permitted only when the schedule is `ACTIVE` — otherwise `ERR_INVALID_STATE_TRANSITION` — and only when the reminder is due, meaning the clock has reached its `next_due_date`; acknowledging a not-yet-due reminder is `ERR_REMINDER_NOT_DUE`. On acknowledgement the `next_due_date` advances by `cadence_months` and the `acknowledged_count` increases by one. Note that a covered chimney's reminder is also rolled forward automatically when a service job for that chimney completes, as described in §3.6.

### 3.9. Job Cancellation and Its Cascade

A `Dispatcher` cancels a `ServiceJob` that has not already terminated; cancelling a job that is already `COMPLETED` or `CANCELLED` is rejected with `ERR_JOB_TERMINAL`. A successful cancellation drives a layered cascade. First, the job's `job_status` moves to `CANCELLED`. As a direct consequence, every appointment for the job whose status is `SCHEDULED`, `EN_ROUTE`, or `ON_SITE` is moved to `CANCELLED`; and for each appointment cancelled this way, its route day's `booked_minutes` is reduced by that appointment's on-site minutes, releasing the capacity. In parallel, every repair order on the job whose status is not already `COMPLETED`, `REJECTED`, or `CANCELLED` is moved to `CANCELLED`, and the job's `committed_cost_cents` is recomputed to reflect the surviving orders. Finally, every warranty for the job that is currently `ISSUED` is voided (`ISSUED → VOIDED`); a warranty already `CLAIMED` may likewise be voided by the same cascade when the parent job is cancelled.

## 4. Endpoint Definitions

Creation endpoints that mint a new stand-alone resource return `201 Created`; this includes creating customers, chimneys, technicians, route days, service jobs, appointments, sweep logs, safety checks, repair orders, warranties, and reminder schedules. Endpoints that modify an existing resource — every state transition, job completion, warranty claim, reminder acknowledgement, and the clock control — return `200 OK`. Retrieval endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | Dispatcher |
| GET | `/customers/{id}` | Get a customer | Dispatcher, Technician, BillingClerk |
| POST | `/chimneys` | Create a chimney for a customer | Dispatcher |
| GET | `/chimneys/{id}` | Get a chimney | Dispatcher, Technician, BillingClerk |
| GET | `/chimneys` | List chimneys, optionally by customer | Dispatcher, Technician, BillingClerk |
| POST | `/technicians` | Create a technician | Dispatcher |
| POST | `/route-days` | Create a route day for a technician | Dispatcher |
| GET | `/route-days/{id}` | Get a route day (includes booked_minutes) | Dispatcher, Technician, BillingClerk |
| GET | `/route-days` | List route days, optionally by technician | Dispatcher, Technician, BillingClerk |
| POST | `/service-jobs` | Create a service job | Dispatcher |
| GET | `/service-jobs/{id}` | Get a service job | Dispatcher, Technician, BillingClerk |
| GET | `/service-jobs` | List service jobs, optionally by customer/chimney/status | Dispatcher, Technician, BillingClerk |
| POST | `/service-jobs/{id}/inspect` | Record the flue inspection result | Technician |
| POST | `/service-jobs/{id}/sweep` | Log the sweep and creosote class | Technician |
| POST | `/service-jobs/{id}/safety-check` | Record the CO/draft/spillage safety check | Technician |
| GET | `/service-jobs/{id}/sweep-logs` | List sweep logs for a job | Dispatcher, Technician, BillingClerk |
| GET | `/service-jobs/{id}/safety-checks` | List safety checks for a job | Dispatcher, Technician, BillingClerk |
| POST | `/service-jobs/{id}/complete` | Complete the job; finalize the invoice | BillingClerk |
| POST | `/service-jobs/{id}/cancel` | Cancel the job with cascade | Dispatcher |
| POST | `/appointments` | Book an appointment slot | Dispatcher |
| GET | `/appointments/{id}` | Get an appointment | Dispatcher, Technician, BillingClerk |
| GET | `/appointments` | List appointments, optionally by route day/job/technician | Dispatcher, Technician, BillingClerk |
| POST | `/appointments/{id}/transitions` | Drive an appointment through its lifecycle | Technician, Dispatcher |
| POST | `/repair-orders` | Propose a repair or gas-log conversion | Technician, Dispatcher |
| GET | `/repair-orders/{id}` | Get a repair order | Dispatcher, Technician, BillingClerk |
| GET | `/repair-orders` | List repair orders, optionally by job/status | Dispatcher, Technician, BillingClerk |
| POST | `/repair-orders/{id}/transitions` | Drive a repair order through its lifecycle | Technician, Dispatcher |
| POST | `/warranties` | Issue a warranty for a completed repair | BillingClerk |
| GET | `/warranties/{id}` | Get a warranty | Dispatcher, Technician, BillingClerk |
| GET | `/warranties` | List warranties, optionally by repair order/job | Dispatcher, Technician, BillingClerk |
| POST | `/warranties/{id}/file-claim` | File a warranty claim | BillingClerk |
| POST | `/reminder-schedules` | Create the recurring reminder for a chimney | Dispatcher |
| GET | `/reminder-schedules/{id}` | Get a reminder schedule (includes is_due) | Dispatcher, Technician, BillingClerk |
| GET | `/reminder-schedules` | List reminder schedules, optionally by customer/chimney/status | Dispatcher, Technician, BillingClerk |
| POST | `/reminder-schedules/{id}/acknowledge` | Acknowledge a due reminder | Dispatcher |
| POST | `/_clock/set_current_utc` | Set the logical clock | Dispatcher, Technician, BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADERS` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_TECH_IDENTITY_MISMATCH` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_INSPECTION_LEVEL` | 400 Bad Request |
| `ERR_INVALID_CREOSOTE_CLASS` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_CHIMNEY_NOT_FOUND` | 404 Not Found |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_DAY_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REPAIR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_NOT_FOUND` | 404 Not Found |
| `ERR_REMINDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_JOB_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_JOB_HAS_OPEN_REPAIRS` | 409 Conflict |
| `ERR_JOB_TERMINAL` | 409 Conflict |
| `ERR_REPAIR_NOT_COMPLETED` | 409 Conflict |
| `ERR_WARRANTY_NOT_CLAIMABLE` | 409 Conflict |
| `ERR_REMINDER_NOT_DUE` | 409 Conflict |
| `ERR_INVALID_APPOINTMENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_WARRANTY_EXPIRED` | 422 Unprocessable Entity |
| `ERR_JOB_UNSAFE` | 403 Forbidden |
| `ERR_PART_REQUIRED` | 422 Unprocessable Entity |
| `ERR_UNKNOWN_PART` | 422 Unprocessable Entity |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_REPAIR_COST_EXCEEDS_AUTH` | 402 Payment Required |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_CHIMNEY_VERSION` | 412 Precondition Failed |
