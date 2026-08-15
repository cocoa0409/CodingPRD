# Stevedoring Labor Ordering API — Product Requirements Document

## 1. Introduction

A marine terminal stevedoring company lives and dies by the gang order: every vessel call must be decomposed into shifts, every shift manned by union labor dispatched from the hall under strict seniority rules, and every hour worked reconciled against payroll tiers, productivity bonuses, equipment bookings, safety stoppages, and cargo-damage liabilities. Today this coordination happens across radio calls, paper dispatch slips, and spreadsheets — a process that cannot enforce seniority-based dispatch ordering, cannot serialize labor-hall offers against last-minute headcount amendments, and cannot produce a defensible invoice when a shipping line disputes a bill after a crane breakdown or a safety stop.

This document specifies the Stevedoring Labor Ordering API, the single system of record for that workflow. The API is mounted under `/api` and manages twelve peer resources — vessel calls, shift windows, gang orders, workers, dispatch assignments, equipment units, equipment assignments, move records, damage claims, safety incidents, timesheet entries, and invoices — spanning the full arc from vessel registration through labor dispatch, work execution, payroll approval, and final billing. Two structural commitments shape everything that follows: a strict segregation of duties (the foreman who reports a claim never adjudicates it; the foreman who submits a timesheet never approves it), and optimistic concurrency control on the small set of writes where a superseding update — a dispatch batch, a headcount amendment, a worker status change, an invoice adjustment — must never be applied against a version the client has not observed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or naming a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (401). The seven declared roles are `StevedoreAdmin`, `StevedoreSuperintendent`, `LaborHallDispatcher`, `GangForeman`, `ClaimsAdjuster`, `PayrollClerk`, and `BillingClerk`. Each endpoint admits a fixed set of roles (enumerated in §4); a request whose role is not admitted is rejected with `ERR_FORBIDDEN` (403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `GangForeman`, `X-User-ID` is the `id` of the acting `Worker` — a foreman is a registered longshore worker — and any resource field that references a worker (such as `recorded_by_worker_id`, `reported_by_worker_id`, or `submitted_by_user_id`) is compared against that `X-User-ID` where a rule requires it. For the six remaining roles — `StevedoreAdmin`, `StevedoreSuperintendent`, `LaborHallDispatcher`, `ClaimsAdjuster`, `PayrollClerk`, and `BillingClerk` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow demands accountability (for example, a claims decision stores the adjuster's `X-User-ID` as `decided_by_user_id`), but it is never matched against an entity's `id`. Two segregation-of-duties invariants follow from this model and are enforced wherever they apply: the claims adjuster deciding a damage claim must not be the worker who reported it, and the payroll clerk approving a timesheet must not be the foreman who submitted it; a violation of either is rejected with `ERR_SEGREGATION_OF_DUTIES` (403).

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

List endpoints are paginated through two query parameters: `limit`, the maximum number of items returned, defaults to 10 and accepts values from a minimum of 1 to a maximum of 100; `offset`, the number of items skipped, defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION` (400). Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Every list endpoint returns items ordered by `created_at` ascending. When several items are created within a single request — for example, a dispatch batch that creates several `OFFERED` assignments in one call — their creation sequence follows the producing rule's ranking order (for dispatch, the selector's seniority ranking), and that creation sequence serves as the secondary order whenever `created_at` values tie.

List endpoints accept optional equality filters corresponding to their resource's foreign keys and lifecycle state: `status`, `vessel_call_id`, `shift_window_id`, `gang_order_id`, `worker_id`, `classification`, `equipment_type`, and `equipment_unit_id`, each applicable to the list endpoints whose resource carries that field, alongside `limit` and `offset`.

### 2.4. Common Resource Properties and Resource Topology

All twelve resources share a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every change to the resource. `version` is a system-managed integer that starts at 1 on creation, increments with every modification, and anchors the optimistic concurrency rules of §2.6. No resource in this system omits any of these four properties.

The topology is flat: resources are peers, and no URL nests one resource beneath another. Linkage travels through foreign-key fields carried in request bodies — `vessel_call_id`, `shift_window_id`, `gang_order_id`, `worker_id`, and `equipment_unit_id` — rather than through nested paths. Every identifier appearing in a path, and every foreign key appearing in a request body, is validated to reference an existing resource; an unresolvable reference is rejected with `ERR_NOT_FOUND` (404). Paths contain at most one identifier, so existence validation is a single lookup per request, performed before any state or business rule is evaluated.

### 2.5. Validation Order and Error Discipline

When several checks would fail on the same request, the failure that surfaces is determined by a fixed priority order — the first failing check wins and later checks are never evaluated for that request. The order is:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is a declared role; failures produce `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The acting role is admitted by the endpoint; failures produce `ERR_FORBIDDEN` (403).
3. **Existence.** Every path identifier and request-body foreign key resolves to an existing resource; failures produce `ERR_NOT_FOUND` (404).
4. **Schema.** Required fields are present, enum values are in range, and numeric ranges hold. The generic failure is `ERR_VALIDATION` (400); three schema conditions carry their own identifiers — `ERR_CARGO_PLAN_REQUIRED`, `ERR_SHIFT_WINDOW_INVALID`, and `ERR_FAULT_PCT_OUT_OF_RANGE` — described with their workflows in §3.
5. **Concurrency.** A mandatory expected-version field equals the target resource's current `version`; mismatches produce the 412 family (`ERR_STALE_GANG_ORDER_VERSION`, `ERR_STALE_WORKER_VERSION`, `ERR_STALE_INVOICE_VERSION`) per §2.6.
6. **State.** The target entity's current state permits the requested operation. The generic failure is `ERR_INVALID_STATE` (409); two state conditions carry their own identifiers — `ERR_SHIFT_NOT_OPEN_FOR_ORDERS` and `ERR_INVOICE_NOT_FINALIZABLE`.
7. **Work-stoppage gates.** The vessel's safety posture blocks the operation; failures produce `ERR_WORK_STOPPAGE_ACTIVE` (409), per §2.10.
8. **Cross-entity referential conditions.** The operation's references satisfy their business linkage rules; failures produce `ERR_WORKER_NOT_ON_GANG` (422) for timesheets and `ERR_NO_EQUIPMENT_ASSIGNED` (409) for starting work.
9. **Temporal interval rules.** Worker double-booking across overlapping shift windows (`ERR_WORKER_DOUBLE_BOOKED`, 409), the equipment buffered-window rule (`ERR_EQUIPMENT_WINDOW_CONFLICT`, 409), move-record period overlap (`ERR_MOVE_PERIOD_OVERLAP`, 409), and the timesheet length cap (`ERR_TIMESHEET_EXCEEDS_SHIFT`, 422). These checks apply, respectively, at dispatch batch and check-in, equipment booking, move-record creation, and timesheet creation.
10. **Capacity, uniqueness, and segregation constraints.** Check-in into a full gang (`ERR_GANG_FULL`, 409), booking a unit that is down (`ERR_EQUIPMENT_UNAVAILABLE`, 409), duplicate worker registration (`ERR_DUPLICATE_REGISTRATION`, 409), segregation-of-duties collisions (`ERR_SEGREGATION_OF_DUTIES`, 403), and dispatch of an ineligible worker (`ERR_WORKER_INELIGIBLE`, 409).
11. **Fiscal limits.** Issuing above the credit limit (`ERR_INVOICE_CREDIT_LIMIT`, 402) and overpaying the balance (`ERR_PAYMENT_EXCEEDS_BALANCE`, 422).

Concretely: a dispatch batch that is both stale-versioned and aimed at a vessel under a full stoppage surfaces `ERR_STALE_GANG_ORDER_VERSION`, never `ERR_WORK_STOPPAGE_ACTIVE`, because concurrency outranks the stoppage gate.

### 2.6. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control, and on each the expected-version field is non-optional. Running a dispatch batch against a gang order requires `expected_gang_order_version` carrying the gang order's `version` as the client last observed it; if the order's version has advanced since that read — for instance because an amendment changed its terms or an earlier batch already ran — the request is rejected with `ERR_STALE_GANG_ORDER_VERSION` (412). Amending a gang order's requirements carries the same field and the same rejection. Changing a worker's status requires `expected_worker_version` matched against the worker's current `version`, rejected on mismatch with `ERR_STALE_WORKER_VERSION` (412). Applying an invoice adjustment requires `expected_invoice_version` matched against the invoice's current `version`, rejected on mismatch with `ERR_STALE_INVOICE_VERSION` (412). The rule is expressed purely in stale-version terms: the request is refused because the version it carries no longer equals the resource's current version, regardless of how the versions diverged. Endpoints not listed here take no version field at all.

### 2.7. Money, Rates, and Rounding

Every monetary amount in the system — rates, claim amounts, invoice lines, payments, adjustments, bonus pools — is represented as integer cents. Whenever a multiplication or division would yield a fractional cent, the result is rounded half up to the nearest integer cent. Two rounding disciplines are pinned where calculations compound: invoice lines are each rounded half up to integer cents individually and only then summed — summing unrounded lines and rounding once at the end is not permitted — while payroll keeps the effective per-minute rate unrounded and applies a single round-half-up at the very end. Moves-per-hour figures are decimal quantities reported at exactly two decimal places, rounded half up. Wherever a percentage-derived amount is computed (provisional claim shares, final claim liabilities, volume discounts), the rounding happens at the point the amount is produced.

### 2.8. Time, Half-Open Intervals, and Equipment Turnaround

Datetime fields — `eta_utc`, `start_utc`, `end_utc`, `window_start_utc`, `window_end_utc`, `period_start_utc`, and `period_end_utc` — are ISO 8601 instants in UTC. Submitted datetime strings are stored and echoed back verbatim; a value arriving without an explicit offset is interpreted as UTC for every comparison the server performs. Date-only fields — `shift_date` and `registered_on` — use the YYYY-MM-DD form and carry local-date semantics. Every interval in the system is half-open: the start instant belongs to the interval and the end instant does not. Adjacency therefore never counts as overlap — a booking or shift that ends exactly when another begins touches it without conflicting — and this holds uniformly for the worker double-booking check, the move-record period check, and equipment bookings. Equipment bookings additionally impose a 30-minute turnaround buffer on either side of each committed window, detailed in §3.4. A shift window's own duration may not exceed 960 minutes — sixteen hours end to end.

### 2.9. Derived Fields, Automatic Transitions, and Cross-Entity Consistency

A number of fields are never supplied by clients; the server derives and maintains them as events occur. On a gang order, `filled_headcount` recounts the assignments in `CHECKED_IN` or `WORKING` status and `offered_count` recounts those in `OFFERED` on every assignment status change, while `assigned_equipment_ok` re-evaluates equipment coverage on every equipment-assignment change, on every accepted amendment (§3.2), and at every evaluation of the start-work gate (§3.5). On a vessel call, `work_posture` derives from open safety incidents, and `actual_moves` and `actual_tons` aggregate from the move records that remain in `RECORDED` status. On a worker, `seniority_rank` recomputes on every worker creation and every status change. On an invoice, the line items, subtotal, discount, totals, and remaining balance are all computed.

The server also moves resources on its own initiative whenever the governing criteria are met — no client call on the affected resource is required. Starting a vessel's first shift advances the vessel itself from `BERTHED` to `WORKING`. Completing the last open gang order of a shift closes the shift. A vessel entering a full stoppage suspends every working gang; a worker suspension bumps that worker's outstanding offers; a breakdown creates a replacement booking when a unit qualifies. Every such mutation — client-initiated or server-initiated — refreshes `updated_at` and increments `version` on each resource it touches, which is precisely what the concurrency guards of §2.6 observe.

### 2.10. Safety Posture Gates

Every vessel call carries a `work_posture` of `NORMAL`, `PARTIAL_STOPPAGE`, or `FULL_STOPPAGE`, derived from its open safety incidents per the rules in §3.7. The posture gates three families of operations. Under `FULL_STOPPAGE`, dispatch batches, assignment check-ins, and starting or resuming gang work are all blocked and rejected with `ERR_WORK_STOPPAGE_ACTIVE` (409). Under `PARTIAL_STOPPAGE`, starting or resuming gang work is blocked with the same error, while dispatch and check-in remain permitted. These gates sit at priority tier 7 in the validation order of §2.5 — after concurrency and state checks, before referential and temporal rules.

## 3. Business Logic & Workflows

### 3.1. Vessel Calls and the Shift Calendar

A `StevedoreAdmin` opens the book of work by registering a vessel call with its `vessel_name`, `voyage_number`, the `shipping_line` that will be billed, the estimated arrival `eta_utc`, the cargo plan in `planned_moves` and `planned_tons`, the productivity commitment `contracted_mph_target`, and the billing ceiling `credit_limit_cents`. The cargo plan may be container-only, breakbulk-only, or mixed, but it may not be empty: a call registered with zero planned moves and zero planned tons is rejected with `ERR_CARGO_PLAN_REQUIRED` (400), while either quantity being positive satisfies the rule (neither may be negative). The contracted moves-per-hour target must be greater than zero, and the credit limit must be greater than zero. A new vessel call is born in `SCHEDULED` status with `work_posture` `NORMAL` and both `actual_moves` and `actual_tons` at zero.

With a call registered, a `StevedoreSuperintendent` lays out the shift calendar by creating shift windows against it, each carrying the parent `vessel_call_id`, a local `shift_date`, a `period` of `DAY`, `NIGHT`, or `GRAVEYARD` (the payroll differential key used in §3.8), and the half-open span from `start_utc` to `end_utc`. The end must be later than the start and the duration no more than 960 minutes; a window failing either condition is rejected with `ERR_SHIFT_WINDOW_INVALID` (400). New shifts are `PLANNED`.

The operating rhythm then proceeds through explicit superintendent actions. Marking the vessel berthed moves it `SCHEDULED` → `BERTHED`. Opening a shift for orders moves it `PLANNED` → `OPEN_FOR_ORDERS` and requires the vessel to be `BERTHED` or `WORKING` — attempting it earlier is rejected with `ERR_INVALID_STATE` (409). Starting a shift moves it `OPEN_FOR_ORDERS` → `IN_PROGRESS`, and when this is the vessel's first shift to enter `IN_PROGRESS` while the vessel is still `BERTHED`, the vessel automatically advances to `WORKING` in the same moment. A shift never closes by hand: it moves `IN_PROGRESS` → `CLOSED` on its own once every gang order placed on it has reached a terminal state (`COMPLETED` or `CANCELLED`), provided at least one gang order exists.

Completing the vessel call moves it `WORKING` → `COMPLETED` and is permitted only when every shift window of the vessel is `CLOSED`; otherwise the completion is rejected with `ERR_INVALID_STATE`. Cancelling is available from either `SCHEDULED` or `BERTHED` and only while no gang order on any of the vessel's shifts remains in a non-terminal state — the same `ERR_INVALID_STATE` guards the attempt otherwise. `COMPLETED` and `CANCELLED` are terminal for the vessel.

### 3.2. Placing, Amending, and Cancelling Gang Orders

Gang orders are the unit of labor demand. A `StevedoreSuperintendent` places one against a shift that is currently `OPEN_FOR_ORDERS`; placing against a shift in any other state is rejected with `ERR_SHIFT_NOT_OPEN_FOR_ORDERS` (409). The order names its `shift_window_id`, a `gang_type` of `CRANE_GANG`, `HOLD_GANG`, `LASHING_GANG`, `DRIVING_GANG`, or `GENERAL`, a `required_classification` of `CRANE_OPERATOR`, `HOLDMAN`, `LASHER`, `DRIVER`, or `CLERK` that defines dispatch eligibility, a `required_headcount` of at least one, a `required_equipment_type` of `SHIP_CRANE`, `RTG`, `FORKLIFT`, or `TRACTOR`, and a `required_equipment_count` of zero or more units of that type that must be covered before work may start. A new order is born `PLACED` with `filled_headcount` and `offered_count` at zero, `assigned_equipment_ok` false, and `suspension_count` at zero. Its productivity fields are likewise born at their zero values — `actual_mph` 0, `bonus_eligible` false, `bonus_pool_cents` 0, and `bonus_per_worker_cents` 0 — and hold them until the completion arithmetic of §3.5 replaces them. The full lifecycle vocabulary of an order is `PLACED`, `DISPATCHING`, `MANNED`, `SHORT_MANNED`, `WORKING`, `SUSPENDED`, `COMPLETED`, and `CANCELLED`.

While an order is in `PLACED`, `DISPATCHING`, `SHORT_MANNED`, or `MANNED`, the superintendent may amend its requirements — a payload optionally carrying a new `required_headcount` or `required_equipment_count`, and always carrying `expected_gang_order_version`; an amendment against any other state is rejected with `ERR_INVALID_STATE`, and one carrying a version the server has already advanced past is rejected with `ERR_STALE_GANG_ORDER_VERSION` (412). Every accepted amendment increments the order's `version` by exactly one in total: the field updates and every derived-field recompute the amendment triggers — the manning and equipment-coverage recomputes described below — constitute a single mutation on the order, so none of those recomputes adds a version increment of its own. When an amendment reduces `required_headcount` below the current `filled_headcount`, a bump waterfall runs: checked-in and working assignments are bumped starting from the least senior — the highest `seniority_rank_at_dispatch` value first, ties broken by the assignment's `created_at` descending so the most recently created goes first — until the filled count equals the new requirement. Amendment-driven bumps never trigger a replacement offer, because headcount is being deliberately reduced. Outstanding `OFFERED` assignments are not cancelled by an amendment; they are turned away later at check-in time with `ERR_GANG_FULL` when the gang is already full. After an amendment the manning status is recomputed, and a `MANNED` order may regress to `DISPATCHING` as a result. Equipment coverage is re-evaluated within the same mutation as well: `assigned_equipment_ok` is recomputed against the possibly amended `required_equipment_count` on every accepted amendment, even when no equipment assignment has changed, so an order born with a zero equipment requirement flips `assigned_equipment_ok` from its birth `false` to `true` at its first accepted amendment.

Cancellation is the superintendent's prerogative from any non-terminal state and always releases the order's holdings. From `PLACED`, `DISPATCHING`, `MANNED`, or `SHORT_MANNED`, cancelling the order moves its assignments in `OFFERED` or `CHECKED_IN` to `CANCELLED` and releases its equipment assignments in `RESERVED`, freeing their units. From `WORKING`, the same action additionally moves assignments in `WORKING` to `CANCELLED` and releases equipment assignments in `ACTIVE` as well. Every freed unit returns to `AVAILABLE` once no other non-terminal booking holds it, per §3.4.

### 3.3. The Labor-Hall Dispatch Pipeline

Workers enter the system when a `StevedoreAdmin` registers them with a `full_name`, a `registration_number` that is unique across all workers (a duplicate is rejected with `ERR_DUPLICATE_REGISTRATION`, 409), a `classification` from the five dispatch classes, a `registered_on` date that anchors seniority, and a `base_hourly_rate_cents` greater than zero. A new worker is born `ACTIVE`, and the server immediately computes `seniority_rank`: within each classification, all workers regardless of status are ordered by `registered_on` ascending — earlier registration means more senior — with ties broken by the worker's `created_at` ascending, and the one-based position is the rank. The rank recomputes on every worker creation and every status change, and it is retained while a worker is `SUSPENDED`: suspension removes dispatch eligibility, not seniority.

Dispatch itself is the `LaborHallDispatcher`'s craft. Running a dispatch batch against a gang order requires the order itself to be `PLACED`, `DISPATCHING`, or `SHORT_MANNED` and the shift to be `OPEN_FOR_ORDERS` or `IN_PROGRESS` (either violation `ERR_INVALID_STATE`), the vessel's `work_posture` to be other than `FULL_STOPPAGE` (otherwise `ERR_WORK_STOPPAGE_ACTIVE`), and `expected_gang_order_version` to match the order's current version (otherwise `ERR_STALE_GANG_ORDER_VERSION`). The batch may optionally carry `worker_ids`, a forced list restricting the candidate pool. Eligibility is then evaluated per worker: the worker must be `ACTIVE`; the worker's `classification` must equal the order's `required_classification`; the worker must hold no assignment on this same gang order in any of `OFFERED`, `CHECKED_IN`, `WORKING`, `NO_SHOW`, or `BUMPED` status — a worker who no-showed or was bumped off this order is never re-offered it; and the worker must hold no assignment in `OFFERED`, `CHECKED_IN`, or `WORKING` on a different gang order whose shift window overlaps this order's shift window under half-open semantics (adjacent shifts do not overlap). When a forced list is present, a listed worker who fails eligibility is not silently skipped: the batch is rejected with `ERR_WORKER_INELIGIBLE` (409), or with `ERR_WORKER_DOUBLE_BOOKED` (409) when the cross-gang overlap clause is the only clause that worker fails.

Eligible candidates are ranked by `seniority_rank` ascending — the most senior first — with ties broken by worker `created_at` ascending; the selection is deterministic and involves no randomness. The batch creates `OFFERED` dispatch assignments for the top candidates, in a count equal to the smaller of the open slots and the eligible-pool size, where open slots equal `required_headcount` minus `filled_headcount` minus `offered_count`. The assignment's `gang_order_id` and `worker_id` are set by the selection itself — never supplied by the client — and each created assignment snapshots the worker's rank at that moment into `seniority_rank_at_dispatch`, the value later used for bump ordering. When the pool runs dry, nothing is created. The first batch moves the order out of `PLACED`; afterwards, if the filled plus offered counts cover the requirement the order stands in `DISPATCHING`, and otherwise it falls to `SHORT_MANNED`. Further batches on a `DISPATCHING` order top it up under the same rules, and a batch on a `SHORT_MANNED` order — after new workers register or an amendment changes the requirement — re-enters `DISPATCHING` the same way. Every batch increments the order's `version` by one, which is why a second batch built on a pre-batch read fails the concurrency check. A successful batch responds with the updated gang order object; the `OFFERED` assignments it created are read back through the dispatch-assignment endpoints.

More generally, whenever assignment statuses change, the order's manning is re-derived while it remains pre-`WORKING`: filled at or above the requirement yields `MANNED`; otherwise filled plus offered at or above the requirement yields `DISPATCHING`; otherwise, when the last selection run established that the eligible pool is empty, `SHORT_MANNED`; otherwise `DISPATCHING`. Once an order reaches `WORKING` these derivations no longer move its status.

Assignments then progress through their own lifecycle. Checking in an offered worker moves the assignment `OFFERED` → `CHECKED_IN`; it requires the shift to be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`), the posture to be other than `FULL_STOPPAGE` (otherwise `ERR_WORK_STOPPAGE_ACTIVE`), the worker to still be `ACTIVE` (otherwise `ERR_WORKER_INELIGIBLE`), and the gang to have an open slot — when `filled_headcount` already equals `required_headcount` the check-in is rejected with `ERR_GANG_FULL` (409). The double-booking rule is re-evaluated at check-in as well. Each successful check-in recomputes `filled_headcount`, and when it reaches the requirement the order advances automatically from `DISPATCHING` or `SHORT_MANNED` to `MANNED`. Completing a working assignment moves it `WORKING` → `COMPLETED` and recomputes the filled count. Marking an offered assignment as no-show (`OFFERED` → `NO_SHOW`) requires the shift to be `IN_PROGRESS` and triggers a single-slot auto-offer: the selection runs again for one slot with the no-show worker excluded from this order's candidate pool, creating one new `OFFERED` assignment when a candidate exists, and the order's manning recomputes. Bumping works the same way from either `OFFERED` or `CHECKED_IN`: the assignment becomes `BUMPED`, a single-slot auto-offer goes to the next eligible candidate with the bumped worker excluded, and the manning recomputes — a bump from `CHECKED_IN` drops the filled count by one, so a `MANNED` order may regress to `DISPATCHING`, or to `SHORT_MANNED` when the pool is exhausted. Unlike a no-show, a bump is not gated on the shift being `IN_PROGRESS`. `COMPLETED`, `NO_SHOW`, `BUMPED`, and `CANCELLED` are terminal for an assignment.

Worker administration closes the loop. A `StevedoreAdmin` changes a worker's `status` — to `ACTIVE`, `SUSPENDED`, or `INACTIVE` — with `expected_worker_version` attached; a stale version is rejected with `ERR_STALE_WORKER_VERSION` (412), and every accepted change increments the worker's `version` by one. Suspending a worker who currently holds assignments in `CHECKED_IN` or `WORKING` is refused with `ERR_INVALID_STATE`. Moving a worker to `SUSPENDED` cascades: every `OFFERED` assignment of that worker becomes `BUMPED`, processed in the assignments' creation order, and each bump in turn triggers the single-slot auto-offer to the next eligible candidate with the suspended worker excluded, with manning recomputing on every affected gang order. Moving a worker to `INACTIVE` carries neither the refusal guard nor the cascade: it is accepted regardless of outstanding assignments and leaves those assignments untouched, and a payload naming the worker's current status is likewise accepted and still increments the version. Any status change also recomputes `seniority_rank` across the classification.

### 3.4. Equipment Booking, Breakdown, and Replacement

Equipment enters the system when a `StevedoreAdmin` registers a unit with a unique `unit_code` — a duplicate `unit_code` is rejected with `ERR_VALIDATION` (400) — and an `equipment_type` of `SHIP_CRANE`, `RTG`, `FORKLIFT`, or `TRACTOR`; the unit is born `AVAILABLE` with `total_breakdowns` at zero.

A `StevedoreSuperintendent` books a unit for a gang order by supplying `gang_order_id`, `equipment_unit_id`, and a half-open window from `window_start_utc` to `window_end_utc`, the end strictly later than the start. Booking imposes no requirement on the gang order's own lifecycle state; only the two constraints below guard it. Two constraints guard the booking. A unit whose status is `DOWN` cannot be booked at all — the attempt is rejected with `ERR_EQUIPMENT_UNAVAILABLE` (409) — whereas a unit that is merely `ASSIGNED` accepts further bookings as long as they satisfy the turnaround rule. That rule imposes a 30-minute buffer around every committed booking: an existing booking of the same unit in `RESERVED` or `ACTIVE` status, with window start s and end e, occupies the buffered span from thirty minutes before s to thirty minutes after e, and a new window conflicts when it begins before e plus thirty minutes and ends after s minus thirty minutes. Because the comparisons are strict, a gap of exactly thirty minutes between windows is allowed. A conflicting booking is rejected with `ERR_EQUIPMENT_WINDOW_CONFLICT` (409). An accepted booking is born `RESERVED`; its unit moves `AVAILABLE` → `ASSIGNED`, or stays `ASSIGNED` when other bookings already hold it; and the gang order's `assigned_equipment_ok` recomputes — that flag is true exactly when the count of the order's equipment assignments in `RESERVED` or `ACTIVE` status whose unit's type matches `required_equipment_type` is at least `required_equipment_count`.

When a gang starts work, its `RESERVED` equipment assignments become `ACTIVE`. A superintendent may also release a booking early: from either `RESERVED` or `ACTIVE` the assignment becomes `RELEASED`, the unit returns to `AVAILABLE` when no other non-terminal assignment holds it, and `assigned_equipment_ok` recomputes. `RELEASED` and `DOWN` are terminal for an equipment assignment.

Breakdowns are the foreman's report to file. Reporting a breakdown on a `RESERVED` or `ACTIVE` assignment moves that assignment to `DOWN`; the unit itself moves `ASSIGNED` → `DOWN` and its `total_breakdowns` increments by one. The replacement selection then runs over the whole fleet: candidates are units whose `equipment_type` matches the failed unit's, whose status is `AVAILABLE`, and whose existing `RESERVED` or `ACTIVE` bookings leave room for the failed assignment's exact window under the thirty-minute buffer rule. Candidates rank by current utilization — the count of their `RESERVED` and `ACTIVE` assignments ascending, least utilized first — with ties broken by the unit's `created_at` ascending. The top unit, when one exists, receives a replacement assignment in `RESERVED` status carrying the failed assignment's window; the failed assignment's `replaced_by_assignment_id` points to that replacement (and stays null when none is created); and the new unit moves `AVAILABLE` → `ASSIGNED`. When no unit qualifies, no replacement is created and the gang remains under-covered: `assigned_equipment_ok` recomputes to false whenever coverage has fallen below `required_equipment_count`. A downed unit returns to service only when a `StevedoreAdmin` marks its repair complete, moving it `DOWN` → `AVAILABLE`.

### 3.5. Working the Gang: Moves, Completion, and the Productivity Bonus

Starting work is the `GangForeman`'s call, from either `MANNED` or `SHORT_MANNED` — the latter only when at least one worker has actually checked in, meaning `filled_headcount` is at least one; a short-manned start with nobody checked in is rejected with `ERR_INVALID_STATE` (409). Three gates guard the start: the shift must be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`); the vessel's `work_posture` must be `NORMAL` — a `PARTIAL_STOPPAGE` blocks the start just as a full one does, both rejected with `ERR_WORK_STOPPAGE_ACTIVE` (409); and `assigned_equipment_ok` must be true, otherwise `ERR_NO_EQUIPMENT_ASSIGNED` (409). On a successful start the order moves to `WORKING`, every `CHECKED_IN` assignment on it becomes `WORKING`, and every `RESERVED` equipment assignment becomes `ACTIVE`.

Stoppage can interrupt at any time. The moment a vessel's posture becomes `FULL_STOPPAGE`, every gang order of that vessel's shifts that is in `WORKING` drops to `SUSPENDED`: the order's `suspension_count` increments by one, its equipment assignments in `RESERVED` or `ACTIVE` are released and their units return from `ASSIGNED` to `AVAILABLE`, and `assigned_equipment_ok` recomputes — false unless surplus coverage somehow remains. Resuming is deliberate, never automatic: the foreman starts work again on the `SUSPENDED` order, the posture must once more be `NORMAL`, and because suspension released the equipment, `assigned_equipment_ok` must be rebuilt through fresh bookings before the gate passes — on resume, the order's new `RESERVED` assignments become `ACTIVE`. The `WORKING` → `SUSPENDED` → `WORKING` cycle may repeat, and each suspension adds another increment to `suspension_count`, which the invoice later converts into stoppage credit.

While the gang works — and also while it stands `SUSPENDED` — the foreman logs productivity in move records. Each record names its `gang_order_id`, a half-open period from `period_start_utc` to `period_end_utc` (end strictly later than start), the `moves_count` and `tons_lifted` for the period, each zero or more, and optionally `stoppage_minutes`, an integer defaulting to zero, at least zero, and no greater than the period's own length in minutes. A record against an order in any state other than `WORKING` or `SUSPENDED` is rejected with `ERR_INVALID_STATE`, and a period that overlaps another `RECORDED` period on the same gang order is rejected with `ERR_MOVE_PERIOD_OVERLAP` (409). The acting foreman's `X-User-ID` is captured as `recorded_by_worker_id` for audit. Each record is born `RECORDED`, and the vessel's `actual_moves` and `actual_tons` recompute on every record as the sums of `moves_count` and `tons_lifted` over the `RECORDED` records of the gang orders across the vessel's shifts. Voiding a record moves it `RECORDED` → `VOIDED` and recomputes those vessel totals with the voided row excluded.

Completing the gang is the foreman's final act on the order, from `WORKING` to `COMPLETED`. The completion cascade moves assignments in `CHECKED_IN` or `WORKING` to `COMPLETED` and cancels any still outstanding in `OFFERED`; equipment assignments in `RESERVED` or `ACTIVE` are released and their units freed; and the productivity arithmetic runs and freezes. Moves per hour: take the order's `RECORDED` move records, sum their `moves_count` into a total move count, and compute productive minutes as the sum over those records of each period's length in minutes minus its `stoppage_minutes`. When productive minutes are zero or negative, `actual_mph` is zero; otherwise `actual_mph` is the total moves multiplied by sixty, divided by the productive minutes, rounded half up to two decimal places. Bonus eligibility follows: `bonus_eligible` is true when `actual_mph` is at least the vessel's `contracted_mph_target` — exact equality qualifies. The bonus pool starts from the target move count, which is the `contracted_mph_target` multiplied by the productive hours (productive minutes divided by sixty, unrounded) and rounded up to the next whole move; excess moves are the amount by which the total moves exceed that target, floored at zero; and `bonus_pool_cents` is the excess multiplied by 1,500 cents — fifteen dollars per excess move. When the pool is zero, `bonus_per_worker_cents` is zero; otherwise it is the pool divided by the greater of one and the number of the order's assignments in `COMPLETED` status immediately after the completion cascade, rounded half up to integer cents. A gang that lands exactly on its target is therefore bonus-eligible but earns a zero pool, because it produced no excess moves. Both figures freeze on the order at completion, and §3.8 describes how timesheets later draw on the per-worker share. Finally, when every gang order of the shift has reached a terminal state, the shift itself closes automatically — the bubble-up of §3.1.

At any point before completion, authorized readers — administrators, superintendents, dispatchers, foremen, and payroll clerks — may consult a computed productivity read on the order. It returns the `gang_order_id`, the live `total_moves` and `productive_minutes` aggregated from `RECORDED` records, the current `actual_mph` at two-decimal precision, the vessel's contracted target surfaced as `mph_target`, and `bonus_eligible_now` indicating whether the present pace meets that target.

### 3.6. Safety Incidents and Work-Stoppage Cascades

Either a `StevedoreSuperintendent` or a `GangForeman` may report a safety incident, supplying the `vessel_call_id`, a `scope` of `GANG`, `VESSEL`, or `TERMINAL`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `description`. The `gang_order_id` field is required exactly when the scope is `GANG`; omitting it then is rejected with `ERR_VALIDATION` (400). It may be supplied under the other scopes as well, in which case it must resolve to an existing gang order and is stored on the incident. Every incident is born `REPORTED`.

The vessel's `work_posture` is a pure derivation over its open incidents — those still in `REPORTED` status. The posture is `FULL_STOPPAGE` when any open incident is `CRITICAL` at any scope, or `MAJOR` at `VESSEL` or `TERMINAL` scope. Otherwise it is `PARTIAL_STOPPAGE` when any open incident is `MAJOR` at `GANG` scope. Otherwise it is `NORMAL`. `MINOR` incidents never move the posture. The derivation re-runs on every incident creation and every clearance, and entering `FULL_STOPPAGE` fires the suspension cascade of §3.5 in the same moment.

The gates that posture imposes are those of §2.10: a full stoppage blocks dispatch batches, check-ins, and work starts or resumes, while a partial stoppage blocks only work starts and resumes — each rejection carrying `ERR_WORK_STOPPAGE_ACTIVE`. Clearing an incident, a superintendent action that moves it `REPORTED` → `CLEARED`, recomputes the posture immediately, and the posture may relax through `PARTIAL_STOPPAGE` back to `NORMAL`. What clearance never does is resume work by itself: gang orders that fell to `SUSPENDED` remain suspended until a foreman explicitly starts work again under the resume rules — and that explicit resume is the only path back to `WORKING`.

### 3.7. Cargo Damage Claims and Segregation of Duties

When cargo is damaged, the `GangForeman` reports a claim against the gang order with a `cargo_ref` identifying the container or cargo, a `damage_description` narrative, and an `estimated_amount_cents` greater than zero. The claim is born `REPORTED`; the acting foreman's `X-User-ID` is recorded as `reported_by_worker_id` and anchors the segregation rule; and a provisional exposure is computed immediately — `provisional_stevedore_share_cents` is one half of the estimated amount, rounded half up to integer cents, with no cap and no deductible at this stage.

Adjudication belongs to the `ClaimsAdjuster`, acting on a `REPORTED` claim with a `decision` of `ACCEPTED` or `DENIED`. Two guards apply. The deciding adjuster's `X-User-ID` must differ from `reported_by_worker_id` — an adjuster may not adjudicate a claim they themselves reported — and a collision is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). And an `ACCEPTED` decision must carry a `fault_pct`, the stevedore's fault percentage as an integer from 0 to 100 inclusive; a missing or out-of-range value is rejected with `ERR_FAULT_PCT_OUT_OF_RANGE` (400). A `DENIED` decision needs no fault percentage; if one is supplied anyway on a denial, an integer value is recorded as-is with no range check, and a non-integer value is ignored. The decision records the adjuster as `decided_by_user_id`; acceptance moves the claim to `ACCEPTED`, while denial moves it to `DENIED` and records `final_stevedore_liability_cents` as zero on the spot.

Settlement closes an `ACCEPTED` claim. The final liability is computed in a pinned evaluation order: first the estimated amount is multiplied by the fault percentage and divided by one hundred, rounded half up to integer cents; then that figure is capped at 25,000,000 cents — a quarter-million dollars; then a deductible of 50,000 cents — five hundred dollars — is subtracted, with the result floored at zero. The outcome is stored as `final_stevedore_liability_cents` and the claim becomes `SETTLED`. `DENIED` and `SETTLED` are terminal; the provisional share remains on the record as the historical estimate, superseded by the final figure.

### 3.8. Timesheets and Payroll

Hours enter the system when a `GangForeman` records a timesheet for a worker on a gang order, supplying `gang_order_id`, `worker_id`, `work_minutes` of zero or more, and optionally `meal_break_taken`, which defaults to false. The worker must hold an assignment on that same gang order in `CHECKED_IN`, `WORKING`, or `COMPLETED` status; a timesheet for anyone else is rejected with `ERR_WORKER_NOT_ON_GANG` (422). The entry may not overstate the shift: when `work_minutes` is greater than the shift's duration in minutes plus a 120-minute grace, the entry is rejected with `ERR_TIMESHEET_EXCEEDS_SHIFT` (422) — a value exactly at the cap is accepted. At creation the worker's current `base_hourly_rate_cents` is copied into `rate_cents_snapshot`, insulating the timesheet from later rate changes, and the entry is born `DRAFT` — until an approval runs, the pay-breakdown fields `straight_minutes`, `ot_minutes`, `dt_minutes`, `meal_penalty_minutes`, and `gross_pay_cents` read null, while `bonus_cents` reads zero and `submitted_by_user_id` reads null.

Submission is the foreman's attestation: submitting moves a `DRAFT` entry to `SUBMITTED` and stamps `submitted_by_user_id` with the acting foreman's `X-User-ID`. A payroll clerk may reject a `SUBMITTED` entry, moving it to `REJECTED`; the foreman may then resubmit through the same submission action, which returns the entry to `SUBMITTED` and refreshes `submitted_by_user_id` to the resubmitting foreman. The `SUBMITTED` → `REJECTED` → `SUBMITTED` cycle may repeat as often as needed.

Approval belongs to the `PayrollClerk`, and the approver's `X-User-ID` must differ from `submitted_by_user_id` — a clerk who submitted a timesheet through a foreman hat may not approve it — with collisions rejected as `ERR_SEGREGATION_OF_DUTIES` (403). Approval computes the full pay breakdown and freezes it on the entry. The minute split: `straight_minutes` is the smaller of `work_minutes` and 480; `ot_minutes` is the amount by which `work_minutes` exceeds 480, capped at 240 and floored at zero; `dt_minutes` is the amount by which `work_minutes` exceeds 720, floored at zero. Overtime therefore accrues only above eight hours — an entry of exactly 480 minutes carries zero overtime — and double time only above twelve hours. The meal rule: `meal_penalty_minutes` is 60 when `work_minutes` exceeds 300 and `meal_break_taken` is false, and zero otherwise — exactly 300 minutes without a break draws no penalty. The rate: the shift's `period` selects a multiplier of 1.00 for `DAY`, 1.10 for `NIGHT`, or 1.20 for `GRAVEYARD`, and the effective hourly base is `rate_cents_snapshot` multiplied by that factor, kept unrounded. Paid minutes weight the components at 1.0 for straight time, 1.5 for overtime, 2.0 for double time, and 1.0 for the meal penalty. `gross_pay_cents` is then the weighted paid minutes multiplied by the effective base and divided by sixty, with a single round-half-up to integer cents at the very end. Approval also attaches the productivity bonus: `bonus_cents` takes the gang order's frozen `bonus_per_worker_cents`, which is zero whenever the order has not yet completed or earned no bonus. `APPROVED` is terminal.

### 3.9. Invoicing from Provisional Draft to Final Payment

Billing opens early. Once a vessel call is `BERTHED`, `WORKING`, or `COMPLETED`, a `BillingClerk` may create its invoice from the `vessel_call_id`; a call still `SCHEDULED` — or already `CANCELLED` — refuses the create with `ERR_INVALID_STATE`. A vessel call carries exactly one invoice — a second create against the same call is rejected with `ERR_INVALID_STATE` (409). The new invoice is a `DRAFT` whose `rate_variant` reads `PROVISIONAL`, and its five lines price the plan rather than the reality: the container line runs the tiered schedule over `planned_moves`, the tonnage line prices `planned_tons`, the man-hour line assumes every non-cancelled gang order's `required_headcount` workers each work a full 480-minute shift, and the equipment and stoppage-credit lines are both zero while the invoice remains a draft.

The line arithmetic is fixed. The container line is marginal and tiered: the first 500 moves are billed at 4,500 cents each, the next 500 moves — those from 501 through 1,000 — at 4,200 cents each, and every move beyond 1,000 at 3,900 cents each, the three tiers summing into the line. The tonnage line is the tons multiplied by 620 cents per ton, rounded half up. The man-hour line sums the `work_minutes` of all `APPROVED` timesheets across the vessel's gang orders first, then multiplies by 6,500 cents per hour, divides by sixty, and rounds half up once. The equipment line bills per equipment type: billable minutes equal the full window minutes of that type's assignments in `ACTIVE` or `RELEASED` status plus one half of the window minutes of its assignments in `DOWN` status — a downed unit bills at half rate — and each type's charge is its billable minutes multiplied by the type's hourly rate and divided by sixty, rounded half up; the hourly rates are 25,000 cents for `SHIP_CRANE`, 12,000 for `RTG`, 6,000 for `FORKLIFT`, and 5,500 for `TRACTOR`, and the line is the sum of the per-type charges. The stoppage credit line is negative 9,000 cents — a ninety-dollar credit — multiplied by the sum of `suspension_count` across the vessel's gang orders. Rounding order is pinned: each of the five lines is computed unrounded, rounded half up to integer cents, and only then summed into `subtotal_cents`; summing unrounded lines and rounding once is forbidden. The invoice exposes each line individually as `container_line_cents`, `tonnage_line_cents`, `manhour_line_cents`, `equipment_line_cents`, and `stoppage_credit_cents`.

Discounts key on the pre-discount subtotal, in that deliberately circular-looking order: a `subtotal_cents` of at least 6,000,000 cents earns a rate of 8 percent; at least 3,000,000 but below 6,000,000 earns 5 percent; below that, no discount. `discount_cents` is the subtotal multiplied by the applicable rate, rounded half up to integer cents, and is zero whenever the subtotal is not positive. The invoice's `total_cents` is the subtotal minus the discount plus `adjustment_total_cents`, the running sum of manual adjustments, which starts at zero. `amount_paid_cents` starts at zero as well, and `remaining_balance_cents` is always the total minus the amount paid.

Finalization converts the estimate into the bill. Finalizing is admitted only against a `DRAFT` invoice — any other invoice state is rejected with `ERR_INVALID_STATE` — and requires the vessel call to be `COMPLETED`; against any earlier vessel state the attempt is rejected with `ERR_INVOICE_NOT_FINALIZABLE` (409). Finalization recomputes every line from actuals — `actual_moves` and `actual_tons` replace the plan, approved timesheets replace the assumed shifts, real equipment windows replace the zero line, and accumulated suspensions produce the credit — and `rate_variant` flips from `PROVISIONAL` to `FINAL`, moving the invoice from `DRAFT` to `FINALIZED`. Issuing is admitted only against a `FINALIZED` invoice — any other state is rejected with `ERR_INVALID_STATE` — and is gated by the credit ceiling: when `total_cents` exceeds the vessel call's `credit_limit_cents`, the issue is rejected with `ERR_INVOICE_CREDIT_LIMIT` (402); otherwise the invoice becomes `ISSUED`.

Against an `ISSUED` invoice, the clerk records payments, each carrying an `amount_cents` that must be a positive integer (anything else is rejected with `ERR_VALIDATION`, 400). A payment may not exceed `remaining_balance_cents` — an overpayment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (422). Each accepted payment adds to `amount_paid_cents`, the remaining balance recomputes, and the invoice moves to `PAID` exactly when the remaining balance reaches zero. A customer who contests the bill instead triggers the dispute path: disputing an `ISSUED` invoice requires a `dispute_reason`, and a missing reason is rejected with `ERR_VALIDATION` (400); the invoice becomes `DISPUTED` and records the reason in `dispute_reason`.

Manual adjustments close the loop on both drafts and disputes; against an invoice in any other state an adjustment is rejected with `ERR_INVALID_STATE`. An adjustment carries `adjustment_cents` — any integer, positive or negative — a free-text `reason`, and `expected_invoice_version`; a version that no longer matches is rejected with `ERR_STALE_INVOICE_VERSION` (412). Every accepted adjustment adds its `adjustment_cents` into `adjustment_total_cents`, recomputes the totals, and increments the invoice's `version` by one. Applied to a `DRAFT`, the invoice stays `DRAFT`. Applied to a `DISPUTED` invoice, the adjustment resolves the dispute by returning the invoice to `FINALIZED`, from which it may be issued again — the `ISSUED` → `DISPUTED` → `FINALIZED` → `ISSUED` cycle may repeat until the balance is paid and the invoice rests in `PAID`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a lifecycle transition return `200 OK`. All paths below are relative to the API mount, and each endpoint admits exactly the roles listed — all other roles receive `ERR_FORBIDDEN`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/vessel-calls` | Register a vessel call | StevedoreAdmin |
| GET | `/api/vessel-calls` | List vessel calls | Any authenticated role |
| GET | `/api/vessel-calls/{id}` | Get a vessel call | Any authenticated role |
| POST | `/api/vessel-calls/{id}/berth` | Mark vessel berthed | StevedoreSuperintendent |
| POST | `/api/vessel-calls/{id}/complete` | Complete the vessel call | StevedoreSuperintendent |
| POST | `/api/vessel-calls/{id}/cancel` | Cancel a vessel call | StevedoreSuperintendent |
| POST | `/api/shift-windows` | Create a shift window on a vessel | StevedoreSuperintendent |
| GET | `/api/shift-windows` | List shift windows | Any authenticated role |
| GET | `/api/shift-windows/{id}` | Get a shift window | Any authenticated role |
| POST | `/api/shift-windows/{id}/open-for-orders` | Open a shift for gang orders | StevedoreSuperintendent |
| POST | `/api/shift-windows/{id}/start` | Start a shift | StevedoreSuperintendent |
| POST | `/api/gang-orders` | Place a gang order on a shift | StevedoreSuperintendent |
| GET | `/api/gang-orders` | List gang orders | Any authenticated role |
| GET | `/api/gang-orders/{id}` | Get a gang order | Any authenticated role |
| PATCH | `/api/gang-orders/{id}` | Amend headcount / equipment requirement | StevedoreSuperintendent |
| POST | `/api/gang-orders/{id}/cancel` | Cancel a gang order | StevedoreSuperintendent |
| POST | `/api/gang-orders/{id}/start-work` | Start or resume gang work | GangForeman |
| POST | `/api/gang-orders/{id}/complete` | Complete a gang order | GangForeman |
| POST | `/api/gang-orders/{id}/dispatch-batch` | Run labor-hall dispatch selection | LaborHallDispatcher |
| GET | `/api/gang-orders/{id}/productivity` | Live MPH and bonus projection | StevedoreAdmin, StevedoreSuperintendent, LaborHallDispatcher, GangForeman, PayrollClerk |
| POST | `/api/workers` | Register a longshore worker | StevedoreAdmin |
| GET | `/api/workers` | List workers | Any authenticated role |
| GET | `/api/workers/{id}` | Get a worker | Any authenticated role |
| PATCH | `/api/workers/{id}` | Change worker status | StevedoreAdmin |
| GET | `/api/dispatch-assignments` | List dispatch assignments | StevedoreAdmin, StevedoreSuperintendent, LaborHallDispatcher, GangForeman, PayrollClerk |
| GET | `/api/dispatch-assignments/{id}` | Get a dispatch assignment | StevedoreAdmin, StevedoreSuperintendent, LaborHallDispatcher, GangForeman, PayrollClerk |
| POST | `/api/dispatch-assignments/{id}/check-in` | Check in an offered worker | LaborHallDispatcher |
| POST | `/api/dispatch-assignments/{id}/complete` | Complete a working assignment | LaborHallDispatcher |
| POST | `/api/dispatch-assignments/{id}/no-show` | Mark an offered assignment no-show | LaborHallDispatcher |
| POST | `/api/dispatch-assignments/{id}/bump` | Bump an offered or checked-in assignment | LaborHallDispatcher |
| POST | `/api/equipment-units` | Register an equipment unit | StevedoreAdmin |
| GET | `/api/equipment-units` | List equipment units | StevedoreAdmin, StevedoreSuperintendent, LaborHallDispatcher, GangForeman |
| GET | `/api/equipment-units/{id}` | Get an equipment unit | StevedoreAdmin, StevedoreSuperintendent, LaborHallDispatcher, GangForeman |
| POST | `/api/equipment-units/{id}/repair-complete` | Return a down unit to service | StevedoreAdmin |
| POST | `/api/equipment-assignments` | Book an equipment unit for a gang order | StevedoreSuperintendent |
| GET | `/api/equipment-assignments` | List equipment assignments | StevedoreAdmin, StevedoreSuperintendent, LaborHallDispatcher, GangForeman |
| GET | `/api/equipment-assignments/{id}` | Get an equipment assignment | StevedoreAdmin, StevedoreSuperintendent, LaborHallDispatcher, GangForeman |
| POST | `/api/equipment-assignments/{id}/report-breakdown` | Report the assigned unit broken down | GangForeman |
| POST | `/api/equipment-assignments/{id}/release` | Release an equipment booking early | StevedoreSuperintendent |
| POST | `/api/move-records` | Log a productivity period for a gang order | GangForeman |
| GET | `/api/move-records` | List move records | StevedoreAdmin, StevedoreSuperintendent, LaborHallDispatcher, GangForeman, PayrollClerk, BillingClerk |
| GET | `/api/move-records/{id}` | Get a move record | StevedoreAdmin, StevedoreSuperintendent, LaborHallDispatcher, GangForeman, PayrollClerk, BillingClerk |
| POST | `/api/move-records/{id}/void` | Void a recorded period | GangForeman |
| POST | `/api/damage-claims` | Report cargo damage on a gang order | GangForeman |
| GET | `/api/damage-claims` | List damage claims | StevedoreAdmin, StevedoreSuperintendent, GangForeman, ClaimsAdjuster |
| GET | `/api/damage-claims/{id}` | Get a damage claim | StevedoreAdmin, StevedoreSuperintendent, GangForeman, ClaimsAdjuster |
| POST | `/api/damage-claims/{id}/decide` | Accept or deny a reported claim | ClaimsAdjuster |
| POST | `/api/damage-claims/{id}/settle` | Settle an accepted claim | ClaimsAdjuster |
| POST | `/api/safety-incidents` | Report a safety incident | StevedoreSuperintendent, GangForeman |
| GET | `/api/safety-incidents` | List safety incidents | StevedoreAdmin, StevedoreSuperintendent, GangForeman |
| GET | `/api/safety-incidents/{id}` | Get a safety incident | StevedoreAdmin, StevedoreSuperintendent, GangForeman |
| POST | `/api/safety-incidents/{id}/clear` | Clear an incident | StevedoreSuperintendent |
| POST | `/api/timesheet-entries` | Enter a worker's hours for a gang order | GangForeman |
| GET | `/api/timesheet-entries` | List timesheets | StevedoreAdmin, StevedoreSuperintendent, GangForeman, PayrollClerk |
| GET | `/api/timesheet-entries/{id}` | Get a timesheet | StevedoreAdmin, StevedoreSuperintendent, GangForeman, PayrollClerk |
| POST | `/api/timesheet-entries/{id}/submit` | Submit a draft or rejected timesheet | GangForeman |
| POST | `/api/timesheet-entries/{id}/approve` | Approve a submitted timesheet | PayrollClerk |
| POST | `/api/timesheet-entries/{id}/reject` | Reject a submitted timesheet | PayrollClerk |
| POST | `/api/invoices` | Create a provisional invoice for a vessel call | BillingClerk |
| GET | `/api/invoices` | List invoices | StevedoreAdmin, StevedoreSuperintendent, BillingClerk |
| GET | `/api/invoices/{id}` | Get an invoice | StevedoreAdmin, StevedoreSuperintendent, BillingClerk |
| PATCH | `/api/invoices/{id}` | Apply a manual adjustment | BillingClerk |
| POST | `/api/invoices/{id}/finalize` | Recompute a draft invoice from actuals | BillingClerk |
| POST | `/api/invoices/{id}/issue` | Issue a finalized invoice | BillingClerk |
| POST | `/api/invoices/{id}/record-payment` | Record a payment against an issued invoice | BillingClerk |
| POST | `/api/invoices/{id}/dispute` | Dispute an issued invoice | BillingClerk |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows they guard in §2 and §3; this catalogue enumerates only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_CARGO_PLAN_REQUIRED` | 400 Bad Request |
| `ERR_SHIFT_WINDOW_INVALID` | 400 Bad Request |
| `ERR_FAULT_PCT_OUT_OF_RANGE` | 400 Bad Request |
| `ERR_STALE_GANG_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_WORKER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_INVOICE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SHIFT_NOT_OPEN_FOR_ORDERS` | 409 Conflict |
| `ERR_INVOICE_NOT_FINALIZABLE` | 409 Conflict |
| `ERR_WORK_STOPPAGE_ACTIVE` | 409 Conflict |
| `ERR_NO_EQUIPMENT_ASSIGNED` | 409 Conflict |
| `ERR_WORKER_NOT_ON_GANG` | 422 Unprocessable Entity |
| `ERR_WORKER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_EQUIPMENT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_MOVE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_TIMESHEET_EXCEEDS_SHIFT` | 422 Unprocessable Entity |
| `ERR_GANG_FULL` | 409 Conflict |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 Conflict |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVOICE_CREDIT_LIMIT` | 402 Payment Required |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_WORKER_INELIGIBLE` | 409 Conflict |
