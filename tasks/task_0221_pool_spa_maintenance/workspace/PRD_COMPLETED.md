# Pool & Spa Maintenance API — Product Requirements Document

## 1. Introduction

Pool and spa service companies juggle a deceptively intricate operation: technicians drive daily routes, water chemistry must be read and corrected at each stop, equipment breaks and needs quoted repairs that the customer must approve, and pools cycle through seasonal opening and winterizing. On top of all this sits a billing layer that charges per visit, honors prepaid packages, and only ever bills work that actually happened. This API is the backend of record for that operation. It models the field-service lifecycle end to end — from registering a customer's pool, through planning recurring or one-time service plans, dispatching route assignments, logging visits and chemical readings, recovering green pools, raising and resolving work orders, to issuing and settling invoices.

The system serves four cooperating operator populations. Account managers own the commercial relationship — customers, pools, plans, and money. Route managers own the field schedule — routes, the visits that fill them, seasonal events, and weather/holiday skips. Field technicians execute the work in the field — completing visits, recording chemistry, and diagnosing repairs. Customers, who are the pool owners themselves, read their own resources and are the sole authority that approves or declines a repair quote. Because the same pool can be touched by all four populations in a single day, the API treats consistency as a first-class concern: derived figures such as a pool's outstanding balance and a plan's remaining visit count are always reconciled immediately, and a deliberate optimistic-concurrency guard protects the one place where two field writers could otherwise clobber each other's same-day log.

This document specifies the complete contract: the global conventions every endpoint obeys, the business rules that govern each workflow, the endpoint surface, and the catalogue of error codes the system can return.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the actor: `X-User-ID`, the acting operator's identifier, and `X-User-Role`, the operational capacity under which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely: `AccountManager`, `RouteManager`, `FieldTechnician`, and `Customer`. When a request is authenticated but the role is not permitted to perform the requested operation, the system responds with `ERR_UNAUTHORIZED`.

Three of these roles are operator-style identities. When `X-User-Role` is `AccountManager`, `RouteManager`, or `FieldTechnician`, the `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it on a resource where a workflow naturally captures it — for example, a route assignment's `technician_id` names the field technician expected to drive that route — but it never compares that opaque id to any entity's `id` for ownership purposes. The fourth role is entity-backed. When `X-User-Role` is `Customer`, the `X-User-ID` is the `id` of the acting `Customer` entity; ownership is enforced only on the two customer-decision work-order actions — declining (hold) and approving (resolve) a quote — and there it compares the work order's owning-account linkage to `X-User-ID`. In practice a customer reaches a work order through its pool: the work order names a pool via `pool_id`, the pool names its account via `customer_id`, and the customer is permitted only when that `customer_id` equals their own `X-User-ID`. A customer acting on a work order they do not own through this chain is rejected with `ERR_NOT_POOL_OWNER`. No ownership comparison is applied to a `Customer`'s read (GET) requests: any authenticated `Customer` may fetch or list any resource the role is permitted to read, regardless of whose account it belongs to.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must fall between a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip before collecting the page; it defaults to 0 and must be at least 0. A `limit` outside its range, a negative `offset`, or a non-integer value supplied for either is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, list results are ordered by `created_at` in ascending order. List responses carry the pagination accounting in the `meta` object, specifically `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in this system — customers, pools, service plans, route assignments, service visits, work orders, seasonal events, and invoices — share a common system-managed core. Each carries an `id`, a server-minted UUID with no type prefix that serves purely as identity and is never itself a business input. Each carries a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording creation. Each carries an `updated_at`, likewise ISO 8601 UTC with three fractional digits, refreshed on every mutation including those reached indirectly through a cascade. And each carries a `version`, an integer that begins at 1 and increments by exactly 1 on every mutation of that resource.

One entity is deliberately leaner. A chemical reading is an append-only record: it carries only `id` and `created_at` (its `created_at` doubling as the chronological ordering key for readings taken during a visit). A chemical reading has no `updated_at` and no `version`, because it is never modified after it is written.

Crucially, the version discipline applies to derived fields too. When the system recomputes a pool's `open_work_order_count` or `balance_due_cents`, or a plan's `visits_remaining`, that recomputation is a mutation of the owning resource: it refreshes `updated_at` and increments `version` just like any field set directly by a client.

### 2.5. Hierarchical Consistency and Cascades

Several operations touch more than one resource. The system applies all such secondary effects immediately and synchronously within the triggering request, never deferring them. When a service plan is cancelled, every one of its visits still in `SCHEDULED` or `RECOVERY_SCHEDULED` is cancelled along with it. When a green pool is detected at visit completion, the pool flips into recovery and a follow-up recovery visit is born on the same plan and route. When a work order changes state, the owning pool's `open_work_order_count` is recomputed; when an invoice changes state, the owning pool's `balance_due_cents` is recomputed. Each entity a cascade touches independently undergoes the full mutation discipline of §2.4 — its `updated_at` is refreshed and its `version` is incremented. The detailed mechanics of each cascade live with the workflow that triggers it in §3.

### 2.6. Nested Resource Retrieval and Reference Validation

Some endpoints address a resource through a path that names a parent first — for example, listing the seasonal events of a pool, or recording a reading against a visit. The system validates referenced resources left to right along the path: the parent named earlier in the path is checked for existence before the child named later. The first identifier in the path that does not resolve to an existing resource produces `ERR_NOT_FOUND` immediately, before any later identifier or any business rule is evaluated. The same existence discipline extends to identifiers supplied in a request body: a `pool_id`, `plan_id`, `route_id`, `visit_id`, or `work_order_id` that names no existing resource yields `ERR_NOT_FOUND`.

### 2.7. Money, Dosing Precision, and Rounding

Monetary amounts in this system are always whole integer cents — per-visit rates, surcharges, parts quotes, repair totals, invoice amounts, and pool balances are all integers, and the calculations that combine them are specified so that rounding happens at most once, at the very end of a computation, using the round-half-up convention. Where a calculation involves no fractional intermediate (for example, summing integer-cent parts into an invoice), no rounding is needed at all.

Chemical dosing is the one place fractional precision matters. A recommended dose is expressed in grams and is rounded to exactly one decimal place using round-half-up. The rounding is applied once, after the chlorine and alkalinity dose components have been summed — the system sums first and rounds the total, rather than rounding each component and then adding. The precise dosing formula appears in §3.

### 2.8. Optimistic Concurrency on Same-Day Visit Logs

There is exactly one optimistic-concurrency-controlled write in this system: logging a same-day field visit-record against a pool. A field technician's visit-log supersedes the prior provisional log for that day, and to guarantee the writer is superseding the log they actually observed, the log request must carry `expected_pool_version` as a required field bearing the pool `version` the client last read. The request also accepts a free-text `note` describing the field record. If another writer has already advanced the pool's `version` since the client last read it — for instance by posting a superseding log of their own — then the submitted `expected_pool_version` no longer matches the pool's current `version`, and the request is rejected with `ERR_STALE_VERSION` at HTTP 412. This is framed purely in terms of stale observation: the rejection fires whenever the supplied expected version is behind the pool's actual version, regardless of timing. No other endpoint accepts or requires a version field; only the visit-log write is version-guarded. A successful visit-log write returns `201 Created` and its `data` is the mutated pool resource (with its now-incremented `version`).

### 2.9. Validation Ordering

When several checks could apply to a single request, the system evaluates them in a fixed priority so that the returned error is deterministic. Authentication comes first: a request missing its headers fails with `ERR_UNAUTHENTICATED` before anything else. Authorization is next: a role not permitted for the operation fails with `ERR_UNAUTHORIZED`. Existence is third: any referenced resource that does not exist fails with `ERR_NOT_FOUND`, evaluated left to right along the path. Business-referential ownership is fourth: a customer acting on a work order whose pool they do not own fails with `ERR_NOT_POOL_OWNER`. State validity is fifth: an operation invoked against a resource not in a state from which the transition is defined fails with `ERR_INVALID_STATE`. Only after these gates do the operation-specific business constraints (interval validity, slot overlap, capacity, repair/seasonal blocks, billing rules, the OCC check, and finally generic request-schema validation) apply. Generic request-body schema validation — missing required fields, wrong types, bad enum members, out-of-range numbers — surfaces as `ERR_INVALID_REQUEST` and is the lowest-priority check of all. Within §3, each business constraint is described next to the workflow it guards.

## 3. Business Logic & Workflows

### 3.1. Customers, Pools, and the Commercial Account

An account manager opens the commercial relationship by creating a customer, supplying the account holder's `full_name` and a contact `email` that must be unique across customers; a create whose `email` duplicates an existing customer's is rejected with `ERR_INVALID_REQUEST`. The billing relationship is captured in `billing_terms`, which is either `PER_VISIT` or `MONTHLY_ACCRUAL` and defaults to `PER_VISIT` when omitted. A new customer starts life with `account_status` of `ACTIVE`. An account manager may later suspend an account, which moves `account_status` to `SUSPENDED`; suspension is not state-gated, so suspending an already-`SUSPENDED` account succeeds and still counts as a mutation (refreshing `updated_at` and incrementing `version`). A suspended account cannot have new plans brought into service, as described in §3.3.

Pools belong to customers. Registering a pool requires the owning `customer_id`, a human `label` such as "Backyard pool", the sanitizer chemistry `water_type` (one of `CHLORINE`, `SALTWATER`, or `BROMINE_SPA`, which selects the dosing constants), and the water `volume_gallons`, an integer of at least 100. Every newly registered pool begins `CLOSED`, recorded in its `service_status`, which moves among `CLOSED`, `OPEN`, `GREEN_RECOVERY`, and `WINTERIZED` as the season and field events unfold. Two figures on the pool are never set by a client but are always derived and kept current. The `open_work_order_count` is the number of this pool's work orders whose status is `OPEN`, `DIAGNOSED`, `ON_HOLD`, or `AWAITING_APPROVAL`, and it is recomputed on every work-order transition. The `balance_due_cents` is the sum of `amount_cents` over this pool's invoices whose status is `ISSUED`; invoices that are `PAID`, `DRAFT`, or `VOIDED` contribute nothing, so only issued-but-unpaid invoices accrue balance, and the figure is recomputed on every invoice transition.

### 3.2. Routes and the Daily Schedule

A route manager plans the field day by creating a route assignment: it names the `technician_id` expected to drive it, the `service_date` it runs (a `YYYY-MM-DD` calendar date), a shift window expressed as `window_start_minute` and `window_end_minute` (minutes from local midnight, treated as the half-open interval from the start up to but not including the end; `window_start_minute` must be in the range 0–1439 and `window_end_minute` in the range 1–1440, and a value outside its range is rejected with `ERR_INVALID_REQUEST`), and a `capacity_visits` ceiling of at least 1 on how many scheduled visits the route may hold. The window must be a valid interval — `window_end_minute` must be strictly greater than `window_start_minute`, and a window whose end does not exceed its start is rejected with `ERR_INVALID_INTERVAL`. A route opens in the `PLANNED` state recorded in its `status`, which then advances to `DISPATCHED` and finally `CLOSED`.

Dispatching is how a planned route goes live for the field, moving its `status` from `PLANNED` to `DISPATCHED`. A route may be dispatched only when it currently holds at least one visit in `SCHEDULED`; dispatching an empty route is rejected with `ERR_EMPTY_ROUTE`. Closing a route advances it from `DISPATCHED` to `CLOSED` and is permitted only once the route has no visit left in `SCHEDULED` or `RECOVERY_SCHEDULED` — every slot must have reached a terminal outcome first. Each of these transitions increments the route's `version`.

### 3.3. Service Plans: Recurring and One-Time

An account manager funds future service through a service plan attached to a pool by `pool_id`. A plan's `plan_type` is either `RECURRING` or `ONE_TIME`. The cadence lives in `frequency`, one of `WEEKLY`, `BIWEEKLY`, `MONTHLY`, or `NONE`, defaulting to `NONE`. The two must agree: a `ONE_TIME` plan must have `frequency` equal to `NONE`, and a `RECURRING` plan must have a `frequency` other than `NONE`. A plan whose type and cadence disagree is rejected with `ERR_FREQUENCY_PLAN_MISMATCH`. The plan also carries a `per_visit_rate_cents`, the base price billed per completed visit before any surcharge, an integer of at least 0; and a `prepaid_visit_count`, the number of visits paid up front, which defaults to 0, must be at least 0, and is meaningful only for `RECURRING` plans (a pure pay-as-you-go arrangement leaves it at 0).

Every plan exposes a derived `visits_remaining`, recomputed on each visit completion. For a `ONE_TIME` plan it is 1 minus the count of that plan's visits that have been completed or skipped, so it reads 1 before service and 0 afterward. For a `RECURRING` plan it is `prepaid_visit_count` minus the count of that plan's visits in `COMPLETED`, never allowed to fall below 0. A plan's lifecycle status moves through `DRAFT`, `ACTIVE`, `COMPLETED`, and `CANCELLED`, starting at `DRAFT`.

Bringing a plan into service moves it from `DRAFT` to `ACTIVE`, and is allowed only when the owning customer's `account_status` is `ACTIVE`; activating a plan for a suspended customer is rejected through the state machinery as an invalid operation. A plan reaches `COMPLETED` automatically rather than by request: when a visit completes and that completion drives the plan's `visits_remaining` to 0 while the plan is `ACTIVE`, the system bubbles the plan up to `COMPLETED`. An account manager may instead cancel an active plan, moving it from `ACTIVE` to `CANCELLED`; cancellation cascades, cancelling every one of that plan's visits still in `SCHEDULED` or `RECOVERY_SCHEDULED`. Each plan transition increments the plan's `version`.

### 3.4. Scheduling Visits onto Routes

A route manager places a visit onto a route by naming the `pool_id` to be serviced, the `plan_id` funding the work, the `route_id` slot it occupies (each of which must resolve to an existing resource, though the system does not verify that the named plan belongs to the named pool, nor require the plan to be in any particular lifecycle state, nor require the route to be `PLANNED`), and the planned on-site window as `slot_start_minute` and `slot_end_minute` (minutes from local midnight, treated as a half-open occupancy from the start up to but not including the end; `slot_start_minute` must be in the range 0–1439 and `slot_end_minute` in the range 1–1440, a value outside its range being rejected with `ERR_INVALID_REQUEST`). As with route windows, `slot_end_minute` must be strictly greater than `slot_start_minute`, and a slot that fails this is rejected with `ERR_INVALID_INTERVAL`.

A new visit must fit its route cleanly. Its half-open slot must lie entirely within the route's half-open window, and it must not overlap the half-open slot of any existing non-terminal visit already on that route — though two visits may meet exactly at a boundary, since adjacency where one slot's end equals the next slot's start is allowed. A visit that spills outside the window or overlaps a sibling is rejected with `ERR_SLOT_OVERLAP`. Independently, a route that is already full — meaning its count of non-terminal visits equals its `capacity_visits` — rejects any further visit with `ERR_ROUTE_AT_CAPACITY`.

A freshly scheduled visit starts in `SCHEDULED`, recorded in its `status`, which can reach `COMPLETED`, `SKIPPED`, `RECOVERY_SCHEDULED`, or `CANCELLED`. The visit also carries a `skip_reason` that defaults to `NONE`, a derived `billed_amount_cents` that stays 0 until completion, and a `makeup_visit_id` that stays null unless a weather skip spawns a makeup. Cancelling a visit before it runs moves it from `SCHEDULED` to `CANCELLED` and increments its `version`; a recovery visit may likewise be cancelled from `RECOVERY_SCHEDULED` to `CANCELLED`, and when that cancellation leaves no other `RECOVERY_SCHEDULED` visit on the pool, it reverts the pool out of recovery, as detailed in §3.6.

### 3.5. Completing Visits, Recording Chemistry, and Per-Visit Billing

Completing a visit is the field technician's central act, advancing the visit from `SCHEDULED` to `COMPLETED`. Completion is permitted only when the visit is `SCHEDULED`, the owning pool's `service_status` is `OPEN` or `GREEN_RECOVERY`, and the route carrying the visit is `DISPATCHED`; a completion attempted against a visit not in a completable state is rejected with `ERR_INVALID_STATE`. The completion request carries a single business flag, `green_pool`, indicating whether the technician found the water in a green, algae-bloom condition. Completion computes the visit's `billed_amount_cents`, recomputes the funding plan's `visits_remaining`, and increments the visit's `version`. When `green_pool` is true on a `SCHEDULED` visit, completion additionally flips the pool into recovery, as described in §3.6.

The per-visit bill is assembled at completion as follows. The starting figure is the plan's `per_visit_rate_cents`. A recovery visit — one that was in `RECOVERY_SCHEDULED` when completed — adds a flat recovery surcharge of 4500 cents. A green-pool initial visit — one that was `SCHEDULED` and completed with `green_pool` true — instead adds a chemical surcharge tiered by the pool's `volume_gallons`: 12000 cents when the volume is at most 15000 gallons, 18000 cents when the volume is at most 30000 gallons (and above 15000), and 26000 cents when the volume exceeds 30000 gallons. A visit that is neither a recovery visit nor a green-pool initial visit adds no surcharge. The gross figure is the base rate plus whichever surcharge applies. Prepaid coverage then decides what is actually billed: if the plan is `RECURRING` and its `visits_remaining` was greater than 0 immediately before this completion, the base portion is treated as already paid and the billed amount is only the surcharge component (recovery and/or green surcharge); otherwise the billed amount is the full gross. Surcharges are always billed, even when the base is prepaid. The result is stored as `billed_amount_cents`. Because all inputs are integer cents, the figure is exact and no rounding is applied.

During a visit, the field technician records water chemistry as a chemical reading tied to the visit by `visit_id`. A reading may be recorded against a visit in any status — the visit need not be `SCHEDULED` or `COMPLETED`, and no visit-state precondition gates the write. A reading captures the measured `free_chlorine_ppm` (parts per million, at least 0), the measured `ph` (between 0 and 14 inclusive), and the measured `total_alkalinity_ppm` (parts per million, at least 0). The system then computes the reading's `recommended_dose_grams`; any value a client tries to supply for that field is ignored. The dose is derived as follows. The free-chlorine target depends on the pool's `water_type`: it is 3.0 ppm for `CHLORINE`, 3.0 ppm for `SALTWATER`, and 4.0 ppm for `BROMINE_SPA`; the total-alkalinity target is 100 ppm for every water type. A volume factor is the pool's `volume_gallons` divided by 10000. The chlorine dose component is the free-chlorine deficit — the target minus the measured `free_chlorine_ppm`, taken as 0 when the measurement already meets or exceeds target so the deficit is never negative — multiplied by a per-water-type dose constant (14.0 for `CHLORINE`, 20.0 for `SALTWATER`, 11.0 for `BROMINE_SPA`) and by the volume factor. The alkalinity dose component is the alkalinity deficit — 100 minus the measured `total_alkalinity_ppm`, again floored at 0 — multiplied by an alkalinity dose constant of 1.5 and by the volume factor. If the measured `ph` is greater than 7.8, chlorine is less effective, so the chlorine component (and only the chlorine component, never the alkalinity component) is multiplied by a penalty factor of 1.25. Finally the chlorine and alkalinity components are summed and that single sum is rounded to one decimal place, round-half-up, to give `recommended_dose_grams`.

At plan-planning time, before any actual reading exists, the system may show a provisional dosing estimate computed from the pool's last completed reading or from band midpoints; this provisional figure is only an estimate and is always recomputed to the final value above from the actual chemical reading taken at the visit. Likewise, a provisional per-visit quote shown at plan activation uses the base rate alone, assuming no green pool and no recovery, and diverges from the final bill whenever a surcharge fires.

### 3.6. Green-Pool Recovery

A pool turns green when algae blooms, and the system models recovery as a short detour in the pool's posture. When a technician completes a `SCHEDULED` visit with `green_pool` true, the pool's `service_status` is set to `GREEN_RECOVERY` (transitioning it there from `OPEN`, or leaving it at `GREEN_RECOVERY` if it was already in recovery from a prior green finding), the system auto-creates a follow-up visit in `RECOVERY_SCHEDULED` on the same `plan_id` and `route_id` as the triggering visit, and the pool's `version` is incremented. This green-pool initial branch fires for any `SCHEDULED` completion with `green_pool` true that passes the §3.5 completion preconditions (pool `OPEN` or `GREEN_RECOVERY`, route `DISPATCHED`). The green-pool initial visit itself is billed with the volume-tiered green surcharge of §3.5.

Recovery ends when the follow-up visit is worked. Completing a `RECOVERY_SCHEDULED` visit (permitted only while the pool's `service_status` is `GREEN_RECOVERY` and the route is `DISPATCHED`) advances that visit to `COMPLETED`, applies the flat recovery surcharge to its `billed_amount_cents`, and, when that completion is logged with `green_pool` false, transitions the pool from `GREEN_RECOVERY` back to `OPEN`, incrementing the pool's `version`. Recovery can also unwind by cancellation rather than completion: if the lone outstanding `RECOVERY_SCHEDULED` visit is cancelled and no other `RECOVERY_SCHEDULED` visit remains on the pool, the pool is reverted from `GREEN_RECOVERY` to `OPEN` as a cascade of that cancellation.

### 3.7. Weather, Holiday, and Customer Skips

A route manager skips a visit that will not be serviced, advancing it from `SCHEDULED` to `SKIPPED`. The request must carry a `skip_reason` other than `NONE`; a skip with a missing reason or with `skip_reason` of `NONE` is rejected with `ERR_SKIP_REASON_REQUIRED`. The accepted reasons are `WEATHER`, `HOLIDAY`, and `CUSTOMER_REQUEST`, and the reason chosen governs whether the work is made up. A `WEATHER` skip is made up automatically: the system creates a fresh `SCHEDULED` makeup visit in the next available capacity slot of the same `route_id` and records its identifier on the original visit's `makeup_visit_id`. The makeup is placed at the first free minute within the route's window not already occupied by a non-terminal visit and is given a one-minute slot there (`slot_end_minute` equal to `slot_start_minute` plus one); if the route's window holds no free minute, no makeup visit is created, `makeup_visit_id` stays null, and the skip itself still succeeds. A `HOLIDAY` or `CUSTOMER_REQUEST` skip creates no makeup. Skips are never billed under any reason, and the skip increments the visit's `version`.

### 3.8. Seasonal Open and Close

Seasonal posture is changed through a seasonal event requested against a pool. A route manager requests one by naming the `event_type` — `OPEN` or `CLOSE` — and an `effective_date` (a `YYYY-MM-DD` date the change takes effect). The event opens in `REQUESTED`, recorded in its `status`, and reaches either `APPLIED` or `VOIDED`. Applying a requested event drives the corresponding pool posture change as a cascade and increments both the event's `version` and the pool's `version`; the underlying pool transition's own preconditions must hold for the apply to succeed. Voiding a requested event simply moves it from `REQUESTED` to `VOIDED` without touching the pool.

An `OPEN` event takes a pool from `CLOSED` to `OPEN`, or from `WINTERIZED` to `OPEN`. Opening is blocked while the pool has any work order of `CRITICAL` severity still in `OPEN`, `DIAGNOSED`, `AWAITING_APPROVAL`, or `ON_HOLD`; an open attempted against such an unresolved critical repair is rejected with `ERR_CRITICAL_REPAIR_BLOCKS_OPEN`. A `CLOSE` event takes a pool from `OPEN` to `WINTERIZED`, and is permitted only when the pool has no visit in `SCHEDULED` or `RECOVERY_SCHEDULED`; a winterize attempted while open visits remain is rejected with `ERR_OPEN_VISITS_BLOCK_CLOSE`. Because that precondition guarantees no open visits survive the close, winterizing cancels nothing.

### 3.9. Equipment Repair Work Orders

When equipment fails, a work order is raised against a pool. Either a field technician or a route manager may raise one, naming the `pool_id`, the `component` to repair (`PUMP`, `FILTER`, `HEATER`, `CHLORINATOR`, or `LINER`), and the `severity` (`MINOR`, `MAJOR`, or `CRITICAL`, where `CRITICAL` blocks the pool from opening as in §3.8). A work order may optionally name the `raised_by_visit_id` of the visit that surfaced the problem, which is null when the order is raised directly. Raising a work order creates it in `OPEN` and recomputes the pool's `open_work_order_count`. The lifecycle status moves through `OPEN`, `DIAGNOSED`, `AWAITING_APPROVAL`, `ON_HOLD`, `RESOLVED`, and `CANCELLED`.

A field technician diagnoses an open order, advancing it from `OPEN` to `DIAGNOSED` while setting the `quoted_parts_cents` (the parts cost, at least 0, which stays 0 until diagnosis) and the estimated `labor_minutes` (at least 0). Diagnosis recomputes the pool's `open_work_order_count` and increments the order's `version`. The technician then submits the diagnosed order for the customer's decision, moving it from `DIAGNOSED` to `AWAITING_APPROVAL`. Here the entity-backed customer takes over: the owning customer may approve the quote, resolving the order from `AWAITING_APPROVAL` to `RESOLVED`, or decline it, parking the order from `AWAITING_APPROVAL` to `ON_HOLD`. Both customer actions require that the acting customer own the pool the work order references (its pool's `customer_id` equals the customer's `X-User-ID`); a non-owner is rejected with `ERR_NOT_POOL_OWNER`. A held order is not dead — a field technician may re-diagnose it, cycling it from `ON_HOLD` back to `DIAGNOSED` with a revised `quoted_parts_cents` and `labor_minutes`, after which it can be re-submitted and re-decided. A route manager may cancel a work order that is still `OPEN` or `ON_HOLD`, moving it to `CANCELLED`. Diagnosis re-set, hold, re-diagnosis, resolution, and cancellation each increment the order's `version`, and every transition that changes whether the order is outstanding recomputes the pool's `open_work_order_count`.

Resolution computes the order's `repair_total_cents`, the total repair charge, in a pinned order of operations. First, labor is billed in whole hours: the estimated `labor_minutes` is divided by 60 and rounded up to the next whole hour, then multiplied by a labor rate of 9000 cents per hour. Second, a severity multiplier is applied to the labor figure alone — 1.0 for `MINOR`, 1.15 for `MAJOR`, and 1.35 for `CRITICAL`. Third, the `quoted_parts_cents` is added to the multiplier-adjusted labor; parts are neither multiplied by severity nor taxed separately. Fourth, the running pre-tax total is multiplied by one plus a tax rate of 0.07, and that taxed total is rounded once at the very end using round-half-up to yield the integer-cent `repair_total_cents`. The pre-tax figure is computed exactly, with the single rounding applied only to the final taxed amount.

### 3.10. Invoicing and Pool Balance

Billing is settled through invoices. An account manager creates a draft invoice against a pool by naming the `pool_id` and exactly one of a `visit_id` (for a completed visit) or a `work_order_id` (for a resolved repair). The named `pool_id`, and any named `visit_id` or `work_order_id`, must each resolve to an existing resource, but the system does not verify that the referenced visit or work order actually belongs to `pool_id`; no cross-pool linkage is validated at creation, and the invoice's balance effects accrue to the named `pool_id` regardless. An invoice that names both, or neither, is rejected with `ERR_INVOICE_REFERENCE_MISMATCH`. A new invoice starts in `DRAFT`, recorded in its `status`, which moves through `ISSUED`, `PAID`, and `VOIDED`. It carries a derived `amount_cents` that stays 0 until issuance.

Issuing a draft invoice advances it from `DRAFT` to `ISSUED`. Issuance is gated on the referenced work having actually occurred: if the invoice names a `visit_id`, that visit must be `COMPLETED`; if it names a `work_order_id`, that work order must be `RESOLVED`. At issuance the system computes `amount_cents` as the sum of the referenced visit's `billed_amount_cents` (when a `visit_id` is set) and the referenced work order's `repair_total_cents` (when a `work_order_id` is set) — in practice one part is present and the other contributes 0. An invoice that would compute to an `amount_cents` of 0 cannot be issued and is rejected with `ERR_NOTHING_TO_BILL`. Issuance recomputes the owning pool's `balance_due_cents`. Paying an issued invoice advances it from `ISSUED` to `PAID` and recomputes the pool's `balance_due_cents`, dropping the now-settled amount out of the outstanding balance. An invoice may also be voided: a `DRAFT` invoice voids to `VOIDED` with no balance effect, while an `ISSUED` invoice voids to `VOIDED` and recomputes the pool's `balance_due_cents` to remove the reversed amount. Every invoice transition increments the invoice's `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer account | AccountManager |
| GET | `/customers/{id}` | Fetch a customer | AccountManager, Customer |
| POST | `/customers/{id}/suspend` | Suspend a customer account | AccountManager |
| POST | `/pools` | Register a pool for a customer | AccountManager |
| GET | `/pools/{id}` | Fetch a pool with computed counts and balance | AccountManager, RouteManager, FieldTechnician, Customer |
| GET | `/pools` | List pools, optionally by customer | AccountManager, RouteManager |
| POST | `/pools/{id}/visit-logs` | Log a same-day field visit record (OCC-guarded) | FieldTechnician |
| POST | `/service-plans` | Create a service plan for a pool | AccountManager |
| GET | `/service-plans/{id}` | Fetch a plan with computed visits remaining | AccountManager, RouteManager, Customer |
| GET | `/service-plans` | List service plans, optionally by pool | AccountManager, RouteManager |
| POST | `/service-plans/{id}/activate` | Activate a draft plan | AccountManager |
| POST | `/service-plans/{id}/cancel` | Cancel an active plan; cascades to open visits | AccountManager |
| POST | `/routes` | Create a route assignment for a technician on a date | RouteManager |
| GET | `/routes/{id}` | Fetch a route | RouteManager, FieldTechnician |
| GET | `/routes` | List routes, optionally by technician | RouteManager, FieldTechnician |
| GET | `/routes/{id}/visits` | List the visits on a route | RouteManager, FieldTechnician |
| POST | `/routes/{id}/dispatch` | Dispatch a planned route | RouteManager |
| POST | `/routes/{id}/close` | Close a dispatched route with no open visits | RouteManager |
| POST | `/visits` | Schedule a visit slot on a route for a pool under a plan | RouteManager |
| GET | `/visits/{id}` | Fetch a visit with computed billed amount | AccountManager, RouteManager, FieldTechnician, Customer |
| GET | `/visits` | List visits, optionally by pool, plan, or route | AccountManager, RouteManager, FieldTechnician |
| POST | `/visits/{id}/complete` | Complete a visit; computes billing, may flip recovery | FieldTechnician |
| POST | `/visits/{id}/skip` | Skip a visit; WEATHER skips auto-create a makeup | RouteManager |
| POST | `/visits/{id}/cancel` | Cancel a scheduled or recovery visit | RouteManager |
| POST | `/visits/{id}/readings` | Record a chemical reading; computes recommended dose | FieldTechnician |
| GET | `/visits/{id}/readings` | List readings for a visit | AccountManager, RouteManager, FieldTechnician, Customer |
| POST | `/work-orders` | Raise an equipment-repair work order for a pool | FieldTechnician, RouteManager |
| GET | `/work-orders/{id}` | Fetch a work order with computed repair total | AccountManager, RouteManager, FieldTechnician, Customer |
| GET | `/work-orders` | List work orders, optionally by pool | AccountManager, RouteManager, FieldTechnician, Customer |
| POST | `/work-orders/{id}/diagnose` | Diagnose an open work order; set quote | FieldTechnician |
| POST | `/work-orders/{id}/submit-for-approval` | Submit a diagnosed order for customer approval | FieldTechnician |
| POST | `/work-orders/{id}/hold` | Customer declines the quote; park the order | Customer |
| POST | `/work-orders/{id}/re-diagnose` | Re-diagnose a held order with a revised quote | FieldTechnician |
| POST | `/work-orders/{id}/resolve` | Customer approves; complete the repair | Customer |
| POST | `/work-orders/{id}/cancel` | Cancel an open or held work order | RouteManager |
| POST | `/pools/{id}/seasonal-events` | Request a seasonal open/close for a pool | RouteManager |
| GET | `/seasonal-events/{id}` | Fetch a seasonal event | RouteManager, AccountManager |
| GET | `/pools/{id}/seasonal-events` | List seasonal events for a pool | RouteManager, AccountManager |
| POST | `/seasonal-events/{id}/apply` | Apply a requested seasonal event; drives pool transition | RouteManager |
| POST | `/seasonal-events/{id}/void` | Void a requested seasonal event | RouteManager |
| POST | `/invoices` | Create a draft invoice for a visit or work order | AccountManager |
| GET | `/invoices/{id}` | Fetch an invoice with computed amount | AccountManager, Customer |
| GET | `/invoices` | List invoices, optionally by pool, visit, or work order | AccountManager, Customer |
| POST | `/invoices/{id}/issue` | Issue a draft invoice; computes amount, accrues balance | AccountManager |
| POST | `/invoices/{id}/pay` | Mark an issued invoice paid; reduces balance | AccountManager |
| POST | `/invoices/{id}/void` | Void a draft or issued invoice | AccountManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_POOL_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FREQUENCY_PLAN_MISMATCH` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_CRITICAL_REPAIR_BLOCKS_OPEN` | 409 |
| `ERR_OPEN_VISITS_BLOCK_CLOSE` | 409 |
| `ERR_EMPTY_ROUTE` | 409 |
| `ERR_ROUTE_AT_CAPACITY` | 409 |
| `ERR_SKIP_REASON_REQUIRED` | 422 |
| `ERR_NOTHING_TO_BILL` | 422 |
| `ERR_INVOICE_REFERENCE_MISMATCH` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
