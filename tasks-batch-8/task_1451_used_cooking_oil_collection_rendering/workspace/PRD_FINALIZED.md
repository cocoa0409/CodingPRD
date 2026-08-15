# Used Cooking Oil Collection & Rendering API — Product Requirements Document

## 1. Introduction

Restaurants, commissaries, and food processors generate used cooking oil that must be collected on a dependable cadence, metered honestly, and priced fairly against volatile commodity markets. This document specifies the Used Cooking Oil Collection & Rendering API: the system of record for a rendering operator's route business, from the moment a customer site is onboarded and a locked container is dropped at the dock, through tanker dispatch, pump-metered pickup, laboratory quality grading, market-indexed settlement, and finally the rendering plant where collected oil becomes saleable product.

The commercial heart of the system is a dual pricing regime. Under a rebate contract the operator pays the customer for oil, at a rate derived from a published market index, adjusted for quality grade, and clamped to a contractual floor and cap. Under a service-fee contract the customer pays the operator a flat fee per completed pickup plus an overage rate on gallons beyond a per-pickup allowance. Both regimes settle through the same two-stage pipeline: a provisional settlement computed from field measurements, and a final settlement recomputed from laboratory grades and period-average index prices, posting to a per-customer rebate ledger.

Operationally, the system enforces the disciplines that keep a grease route honest and safe: theft-prevention lock codes and a confirmed-theft cascade that locks containers and suspends habitually skipped accounts; tank-capacity and tank-conservation checks so a tanker never leaves the yard overloaded and never reconciles with unexplained gains or losses; spill and nuisance complaint workflows that gate plant intake; and contract-term, cooling-off, and competitor-poaching rules that govern the commercial relationship itself. All temporal behavior is driven by a controllable logical clock so that contracts expire, complaints auto-close, and pickup windows evaluate deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly seven roles: `SystemAdmin`, `FieldOpsManager`, `RouteDispatcher`, `Driver`, `BillingAnalyst`, `PlantOperator`, and `CustomerContact`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not in the endpoint's authorized role list, or that violates an ownership rule, is rejected with `ERR_FORBIDDEN_ROLE`.

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's customer foreign-key field to `X-User-ID`. For the remaining six roles — `SystemAdmin`, `FieldOpsManager`, `RouteDispatcher`, `Driver`, `BillingAnalyst`, and `PlantOperator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, a route manifest records the responsible driver in its `driver_ref` field) but does not compare it to any entity's `id`, except where an explicit ownership rule states otherwise.

Two ownership rules qualify role-based access. First, a `CustomerContact` may act only on resources belonging to the customer whose `id` equals the caller's `X-User-ID`; filing a complaint whose `customer_id` differs from the caller's `X-User-ID`, for instance, is rejected with `ERR_FORBIDDEN_ROLE`. Second, a `Driver` may start, complete, or fail a pickup visit only when the acting `X-User-ID` equals the owning manifest's `driver_ref`; a driver action against another driver's route is rejected with `ERR_FORBIDDEN_ROLE`.

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

List endpoints paginate via two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above the maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. The Logical Clock and Lazy State Transitions

All temporal logic in the system reads a single logical clock, never the wall clock. A `SystemAdmin`-exclusive test-driving capability advances the logical clock to a supplied `to_iso8601` instant. Before any such call, the clock's startup default is exactly 2026-08-01T00:00:00Z; the server must not fall back to wall-clock time at any point.

Every system-stamped timestamp — a contract's `activated_at`, a quote's `published_at`, a visit's `skipped_at` and `completed_at`, a complaint's `resolved_at`, a settlement's `paid_at` — is drawn from the logical clock at the moment the triggering event occurs and is serialized as an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-08-05T08:00:00.000Z`), in the same format as `api_request_timestamp` and `created_at`.

Two state transitions are **lazy**: they are not fired by timers but are evaluated on any subsequent read or write once the logical clock has passed their threshold. A contract whose coverage window has ended transitions to `EXPIRED`, and a resolved complaint whose reopen window has fully elapsed transitions to `CLOSED`. Advancing the clock therefore takes full effect on the next access to the affected resources.

### 2.5. Common Resource Properties

Every resource in the system — Customer, Contract, Container, Truck, RouteManifest, PickupVisit, QualitySample, MarketIndexQuote, Settlement, SettlementLine, Complaint, TheftIncident, and ProcessingBatch — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, including system-driven side-effect mutations.

Any mutation of a resource — whether from a client request or from a cascade such as a theft confirmation or a quote publication — refreshes `updated_at` and increments `version` on each mutated resource independently.

### 2.6. Measurement Precision, Rounding, and Monetary Units

The system's quantities fall into four precision classes, all using round-half-up where rounding applies:

- **Gallons** — pumped, netted, projected, collected, tipped, yielded — are carried at two decimal places, rounded half-up.
- **Percentages** — field and laboratory moisture and impurity readings — are accepted at two decimal places, and grade-threshold comparisons against them are exact, with no tolerance.
- **Yield rate** is expressed at four decimal places, rounded half-up.
- **Money** — rates, line amounts, settlement totals, and the rebate ledger — is expressed in integer cents (or integer cents per gallon for resolved index prices), with each line amount rounded half-up to whole cents before any summation.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint accepts a version field.

Amending a contract requires the request to carry `expected_contract_version` equal to the contract's current `version`. If another writer has advanced the contract's version since the client last read it — each amendment legitimately supersedes the prior rate schedule — the amend is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a rate schedule it has not observed.

Re-planning the stop list of a draft route manifest requires the request to carry `expected_manifest_version` equal to the manifest's current `version`. If another dispatcher has advanced the manifest's version since the client last read it — the newer stop plan legitimately supersedes the prior one — the patch is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Request Validation Order and Nested Resource Retrieval

Every request is validated against a fixed sequence of check categories, and a failure in an earlier category surfaces its error without evaluating later categories. The order is: first, authentication — the presence and validity of `X-User-Role` and `X-User-ID` (`ERR_UNAUTHENTICATED`); second, authorization — the acting role's membership in the endpoint's role list plus the ownership rules of §2.1 (`ERR_FORBIDDEN_ROLE`); third, existence — every resource identifier in the request path must exist (`ERR_NOT_FOUND`); fourth, request schema — required fields present, types valid, enum values within their declared sets, and numeric bounds such as container capacity and positive pump readings (`ERR_VALIDATION`); fifth, state-machine legality — the requested transition must be defined from the entity's current state, including terminal-state lockdown (`ERR_INVALID_STATE`); sixth, domain state guards — container not locked, contract engagement, sample re-grade discipline, customer not suspended (`ERR_CONTAINER_LOCKED`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_SAMPLE_ALREADY_GRADED`, `ERR_CUSTOMER_SUSPENDED`); seventh, optimistic concurrency (`ERR_STALE_VERSION`); eighth, safety gates — truck availability and open spill complaints (`ERR_TRUCK_UNAVAILABLE`, `ERR_SPILL_COMPLAINT_OPEN`); ninth, business constraints — contract term overlap, manifest date uniqueness, tank capacity, container capacity, tank balance, and duplicate billing periods (`ERR_CONTRACT_TERM_OVERLAP`, `ERR_MANIFEST_DATE_CONFLICT`, `ERR_TANK_CAPACITY_EXCEEDED`, `ERR_CONTAINER_CAPACITY_EXCEEDED`, `ERR_TANK_IMBALANCE`, `ERR_DUPLICATE_PERIOD`); tenth, temporal windows — pickup timing, period closure, cooling-off, and complaint reopen (`ERR_PICKUP_WINDOW_FUTURE`, `ERR_PERIOD_NOT_CLOSED`, `ERR_CONTRACT_IN_COOLING_OFF`, `ERR_COMPLAINT_REOPEN_WINDOW_EXPIRED`); eleventh, referential completeness — open settlements, pending grades, index coverage, unresolved theft (`ERR_OPEN_SETTLEMENTS`, `ERR_GRADE_PENDING`, `ERR_QUOTE_NOT_PUBLISHED`, `ERR_THEFT_UNRESOLVED`); and finally the fiscal payout floor (`ERR_PAYOUT_BELOW_MINIMUM`).

For nested resource paths, existence is validated left to right: each identifier in the path is resolved in order, and the request is rejected with `ERR_NOT_FOUND` for the first identifier that does not correspond to an existing resource — a request naming a missing customer fails before the system ever looks for the contract or container beneath it.

### 2.9. Fleet Safety and Tank Conservation

Two physical-safety invariants govern every route. A tanker may be dispatched only while it is in service; dispatch against a truck that is out of service is rejected. And a route's projected fill — the planning estimate of how much oil its stops will yield — must fit the assigned tanker's tank: a projection strictly greater than tank capacity rejects the dispatch, while a projection exactly equal to capacity is permitted.

After the route runs, the tank must account for every gallon. The expected end-of-route tank level is the dispatch start level plus the collected gallons minus any recorded spill loss; reconciliation succeeds only when the measured end level deviates from that expectation by no more than half a gallon in either direction. Additionally, no truck may be double-booked on a date: one manifest per truck per service date.

### 2.10. Rebate Ledger Integrity

Each customer carries an open rebate ledger balance, `rebate_balance_cents`, defined as the sum of `final_total_cents` across that customer's settlements currently in `FINALIZED` status — settlements in `PROVISIONAL`, `PAID`, or `VOID` status never contribute. The ledger mutates at exactly three points: finalizing a settlement adds its `final_total_cents` to the balance; paying a finalized settlement subtracts the same amount, moving it out of the open balance into a disbursement; and voiding a finalized settlement subtracts the amount as a reversal. The compensating invariant follows directly: a finalize-then-void pair leaves the balance exactly as it was, while a finalize-then-pay pair converts the obligation into a recorded payout.

## 3. Business Logic & Workflows

### 3.1. Customer Accounts and Site Onboarding

A `SystemAdmin` or `FieldOpsManager` registers a collection site by supplying its legal `name`, the street `site_address`, and `site_max_container_gal` — the zoning-derived ceiling on the aggregate container gallons the site may host. A newly registered customer starts in `PROSPECT` status, with `missed_pickup_count` at zero and `rebate_balance_cents` at zero. The customer directory supports pagination and an optional `status` filter.

A prospect becomes billable automatically rather than by a separate action: when a contract of a `PROSPECT` customer transitions from `DRAFT` to `ACTIVE`, the customer transitions `PROSPECT` → `ACTIVE` as a system side effect, incrementing the customer's `version` and refreshing its `updated_at`.

Suspension has two paths. A `FieldOpsManager` may manually suspend an `ACTIVE` customer, optionally recording a `reason`, moving the account to `SUSPENDED`. Suspension also fires automatically from the theft-confirm cascade described in §3.3. While a customer is `SUSPENDED`, two operations are blocked and rejected with `ERR_CUSTOMER_SUSPENDED`: placing a new container at one of its sites, and dispatching a route manifest whose stops include that customer's containers. Reinstatement by a `FieldOpsManager` returns the account `SUSPENDED` → `ACTIVE`; the `missed_pickup_count` is recomputed from visit history, not reset to zero.

The `missed_pickup_count` measures recent service failures. It counts the customer's pickup visits in `SKIPPED` status whose `skipped_at` falls within the trailing 90-day window: strictly later than 90 days before the logical clock, and no later than the clock itself (the upper bound is inclusive). Whenever a skip lands and the recomputed count is at least 3 while the customer is `ACTIVE`, the customer transitions `ACTIVE` → `SUSPENDED` automatically.

Terminating a customer is allowed from either `ACTIVE` or `SUSPENDED`, records a `reason`, and is permitted only when every contract of the customer has reached a terminal state — `TERMINATED_VOLUNTARY`, `TERMINATED_POACHED`, or `EXPIRED`. Termination cascades: every container of the customer still in `PLACED`, `ACTIVE`, or `LOCKED` transitions to `REMOVED`. `TERMINATED` is the customer's terminal state.

### 3.2. Contract Terms, Pricing Regimes, and Competitive Retention

A `FieldOpsManager` or `SystemAdmin` drafts a contract under a customer, choosing a `pricing_mode` of `REBATE` or `SERVICE_FEE`, naming the market `index_code` the contract prices against (for example, `YG_CBI`, the yellow-grease index), and fixing the coverage window with `term_start` and `term_end` as ISO calendar dates. The window is half-open: coverage includes `term_start` and runs up to but does not include `term_end`. Rate fields depend on the regime. A `REBATE` contract carries `floor_cents_per_gal` (the minimum cents-per-gallon rate, defaulting to 0) and `cap_cents_per_gal` (the maximum rate, defaulting to 1000000). A `SERVICE_FEE` contract carries `service_fee_cents` (the flat fee charged per completed pickup, defaulting to 0), `overage_threshold_gal` (the gallons per pickup included in the flat fee before overage accrues, defaulting to 0), and `overage_rate_cents_per_gal` (the per-gallon charge above the threshold, defaulting to 0). A drafted contract starts in `DRAFT` status.

One customer's non-terminal contracts may never have overlapping term windows. Because windows are half-open, adjacency is allowed: a new contract whose `term_start` equals an existing contract's `term_end` does not overlap it. The check runs both when a contract is drafted and when it is activated, and a violation is rejected with `ERR_CONTRACT_TERM_OVERLAP`. The same non-overlap rule governs renewal offers: an offered window that overlaps another non-terminal contract of the same customer is rejected.

Activation moves a contract `DRAFT` → `ACTIVE`. It is permitted only when the logical clock date is on or after `term_start` and strictly before `term_end`, and when no other non-terminal contract of the same customer overlaps the window. Activation stamps `activated_at` from the logical clock — this timestamp anchors the cooling-off window described below — flips a `PROSPECT` customer to `ACTIVE` as a side effect, and increments the contract's `version`.

Renewal is a cycle rather than a new document. From `ACTIVE` or `AT_RISK`, a `FieldOpsManager` offers renewal terms by proposing `new_term_start` and `new_term_end`; the contract moves to `RENEWAL_OFFERED`, records the proposed window in `offered_term_start` and `offered_term_end`, and remembers the originating status in `status_before_renewal`. The response, from the account's `CustomerContact` or a `FieldOpsManager`, carries `accept`. Acceptance replaces `term_start` and `term_end` with the offered values, clears the offered fields and `status_before_renewal`, and returns the contract to `ACTIVE`. Rejection clears the offered fields, leaves the existing term unchanged, and returns the contract to the status remembered in `status_before_renewal` — `ACTIVE` when the offer was made from `ACTIVE`, `AT_RISK` when made from `AT_RISK`. The `ACTIVE` → `RENEWAL_OFFERED` → `ACTIVE` loop may repeat indefinitely.

When a competitor courts the account, a `CustomerContact` (for its own contract) or a `FieldOpsManager` flags the poach, supplying the `competitor_name` and the competitor's offered rate as `offer_cents_per_gal`. The contract moves `ACTIVE` → `AT_RISK`, persisting the competitor's name and the offered rate in `poach_offer_cents_per_gal`. The retention play is an amendment: amending an `AT_RISK` contract updates its rate fields — `floor_cents_per_gal`, `cap_cents_per_gal`, `service_fee_cents`, `overage_threshold_gal`, and `overage_rate_cents_per_gal` are all amendable — clears the recorded competitor fields, and returns the contract to `ACTIVE`. Amending an `ACTIVE` contract updates rate fields in place as an `ACTIVE` → `ACTIVE` self-transition. Either way the amendment increments the contract's `version` and is OCC-guarded per §2.7: the request must carry `expected_contract_version` matching the current `version`, or it fails with `ERR_STALE_VERSION`.

Contract termination records a `reason` of `VOLUNTARY` or `POACHED`, stored in `termination_reason`. Voluntary termination applies from `ACTIVE` and lands in `TERMINATED_VOLUNTARY`; poached termination applies from `AT_RISK` and lands in `TERMINATED_POACHED`; any other state-and-reason combination has no defined transition and is rejected with `ERR_INVALID_STATE`. Two guards protect both paths. Cooling-off: termination is rejected with `ERR_CONTRACT_IN_COOLING_OFF` while the logical clock is earlier than 14 days after `activated_at`; once at least 14 days have elapsed, the guard passes. Open billing: termination while any settlement of the customer is in `PROVISIONAL` or `FINALIZED` status is rejected with `ERR_OPEN_SETTLEMENTS`.

Contracts do not expire on a timer. Expiry is lazy per §2.4: on any read or write of a contract whose `term_end` is strictly before the logical clock date, the contract transitions from `ACTIVE`, `AT_RISK`, or `RENEWAL_OFFERED` to `EXPIRED`, incrementing its `version`. `TERMINATED_VOLUNTARY`, `TERMINATED_POACHED`, and `EXPIRED` are the contract's terminal states.

### 3.3. Container Placement and Theft Response

A `FieldOpsManager` places a container at a customer site by specifying its `capacity_gallons`, an `est_fill_rate_gal_per_week` used for route fill projection, and a driver-facing `lock_code` that secures the unit against theft. Capacity must be at least 30 gallons and at most 2000 gallons; values outside that range fail schema validation with `ERR_VALIDATION`. Placement additionally requires that the customer is not `SUSPENDED` (`ERR_CUSTOMER_SUSPENDED`), that the customer holds an active-era contract — one in `ACTIVE`, `AT_RISK`, or `RENEWAL_OFFERED` status, not `DRAFT` or any terminal state (`ERR_CONTRACT_NOT_ACTIVE`) — and that the aggregate capacity of the customer's non-`REMOVED` containers stays within `site_max_container_gal`. A new container starts in `PLACED` status and remains `PLACED` until a route covering it is dispatched, at which point it flips `PLACED` → `ACTIVE` automatically.

Removal retires a container from service. A container in `PLACED` or `ACTIVE` may be removed provided none of its pickup visits is currently `SCHEDULED` or `EN_ROUTE`. A `LOCKED` container carries a second condition: no theft incident on it may remain `CONFIRMED`. Removal or unlocking while a confirmed incident exists is rejected with `ERR_THEFT_UNRESOLVED`; otherwise unlocking returns the container `LOCKED` → `ACTIVE`. `REMOVED` is the container's terminal state, reached either by explicit removal or by the customer-termination cascade of §3.1.

Tampering is reported by a `Driver`, a `CustomerContact`, or a `FieldOpsManager`, filing a theft incident with the `container_id` and an `evidence_note` describing the lock or seal evidence; the incident starts in `REPORTED` status. A `FieldOpsManager` may dismiss a report — recording a `note`, moving the incident `REPORTED` → `DISMISSED` — or confirm it.

Confirmation is the severe path and cascades across four aggregates. The incident moves `REPORTED` → `CONFIRMED`. The container moves `ACTIVE` → `LOCKED`. Every `SCHEDULED` pickup visit of that container moves to `SKIPPED`, with `skipped_at` stamped from the logical clock; visits already `EN_ROUTE` are deliberately not auto-skipped, because the driver is already on site and decides between completing and failing. For each skipped visit, the owning customer's `missed_pickup_count` is recomputed, and when the count reaches the suspension threshold of 3 the customer transitions `ACTIVE` → `SUSPENDED`. Each mutated resource in this cascade increments its own `version`.

Resolving a confirmed incident — for example, recording in `resolution_note` that the lock was replaced — moves it `CONFIRMED` → `RESOLVED`. Once no incident on the container remains `CONFIRMED`, the container's unlock and removal paths reopen. `DISMISSED` and `RESOLVED` are the incident's terminal states.

### 3.4. Route Planning, Dispatch, and Tank Reconciliation

Dispatch operations begin with the fleet. A `SystemAdmin` or `RouteDispatcher` registers a tanker with its unique `plate` and its `tank_capacity_gallons`; the truck starts `IN_SERVICE`. A `RouteDispatcher` toggles a truck between `IN_SERVICE` and `OUT_OF_SERVICE` through the service-status action, which takes the target `status`. Dispatch refuses a truck that is `OUT_OF_SERVICE` with `ERR_TRUCK_UNAVAILABLE`.

A route manifest is drafted by a `RouteDispatcher`, who supplies the `truck_id`, the `driver_ref` (the opaque identifier of the `Driver` who will run the route and the only driver whose visit actions will be accepted), the `service_date`, and the stop list `container_ids`. Creation stamps one `SCHEDULED` pickup visit per stop, each linked to its route via `manifest_id` and to its unit via `container_id`, with `scheduled_date` copied from the manifest's `service_date`. Only one manifest may exist per truck per service date — a date-point uniqueness rule, not an interval rule — and a second manifest for the same truck and date is rejected with `ERR_MANIFEST_DATE_CONFLICT`.

Planning safety rides on the manifest's `projected_fill_gallons`: for each stop, the system takes the smaller of the container's `capacity_gallons` and its `est_fill_rate_gal_per_week`, then sums across all stops, expressed at two decimal places. The figure is computed at creation and recomputed whenever the stop list changes.

While the manifest remains in `DRAFT`, a dispatcher may replace its stop list wholesale. The replacement request must carry `expected_manifest_version` matching the manifest's current `version` (§2.7); a mismatch is rejected with `ERR_STALE_VERSION`, since a newer stop plan legitimately supersedes the one the dispatcher last observed. A successful re-plan deletes the existing `SCHEDULED` visits, recreates them from the new stop list, recomputes `projected_fill_gallons`, and increments the manifest's `version`.

Dispatch moves the manifest `DRAFT` → `DISPATCHED` and records the tank's `start_level_gallons` from the request — usually zero for an empty tank. Dispatch is refused unless every one of the following holds: the truck is `IN_SERVICE` (`ERR_TRUCK_UNAVAILABLE`); the projected fill fits the tank, where a projection strictly greater than `tank_capacity_gallons` is rejected with `ERR_TANK_CAPACITY_EXCEEDED` while a projection exactly equal to capacity dispatches; every stop container is in `PLACED` or `ACTIVE`; and every stop container's customer is `ACTIVE` — a suspended customer anywhere on the route yields `ERR_CUSTOMER_SUSPENDED`. On dispatch, every `PLACED` stop container transitions to `ACTIVE` and the manifest's `version` increments.

The route goes `IN_PROGRESS` automatically the moment its first visit starts. Once every visit of the manifest has reached `COMPLETED`, `SKIPPED`, or `VOID`, the assigned driver closes the route, moving the manifest from `DISPATCHED` or `IN_PROGRESS` to `COMPLETED`. Closing recomputes `collected_gallons` as the sum of `pump_gallons` across the manifest's visits in `COMPLETED` status — `VOID` visits excluded — at two decimal places.

Reconciliation is the dispatcher's final accounting and moves the manifest `COMPLETED` → `RECONCILED`, its terminal state. The dispatcher records the measured `end_level_gallons` and any `spill_loss_gallons` lost en route (zero when nothing spilled). Tank conservation must hold per §2.9: the expected end level is `start_level_gallons` plus `collected_gallons` minus `spill_loss_gallons`, and the reconcile is rejected with `ERR_TANK_IMBALANCE` when the measured end level deviates from that expectation by more than 0.5 gallons in either direction. The invariant is compensating: voiding a completed pickup removes its gallons from `collected_gallons`, so a reconcile performed after a void still balances.

### 3.5. Driver Pickup Execution

A visit begins when the assigned driver marks arrival, moving it `SCHEDULED` → `EN_ROUTE`. The acting `X-User-ID` must equal the manifest's `driver_ref` — a driver working another driver's route is rejected with `ERR_FORBIDDEN_ROLE` — and the manifest must be `DISPATCHED` or `IN_PROGRESS`. The first visit start of a route also moves the manifest `DISPATCHED` → `IN_PROGRESS` as a side effect.

At the tank, the driver completes the visit (`EN_ROUTE` → `COMPLETED`) by recording `pump_gallons` read off the pump meter and `field_moisture_pct` from the field refractometer — a percentage between 0 and 100, carried at two decimal places. Completion is guarded by four checks: the container must be `ACTIVE`, and completing against a `LOCKED` container is rejected with `ERR_CONTAINER_LOCKED`; the logical clock date must be on or after the visit's `scheduled_date`, otherwise `ERR_PICKUP_WINDOW_FUTURE`; the pump reading must be greater than zero, otherwise `ERR_VALIDATION`; and it must not exceed the container's `capacity_gallons`, otherwise `ERR_CONTAINER_CAPACITY_EXCEEDED`. On completion the system computes `net_gallons_provisional` — the pump gallons multiplied by one minus the field moisture fraction, rounded half-up to two decimal places — stamps `completed_at` from the logical clock, sets the container's `last_completed_pickup_date` to the visit's `scheduled_date`, and recomputes the manifest's `collected_gallons`.

A failed attempt moves the visit `EN_ROUTE` → `FAILED` with the recorded `failure_reason` (supplied as the request's `reason`), then immediately and automatically returns `FAILED` → `SCHEDULED` with `retry_count` incremented by one. The fail-and-retry loop is cyclic: a visit may fail and be rescheduled repeatedly without bound.

A `RouteDispatcher` may void a completed visit as a compensating action while the manifest is `DISPATCHED`, `IN_PROGRESS`, or `COMPLETED` — never once the manifest is `RECONCILED`. Voiding records the `void_reason` (again supplied as `reason`), moves the visit `COMPLETED` → `VOID`, recomputes the manifest's `collected_gallons` excluding the voided visit, removes any settlement lines referencing the visit from settlements still in `PROVISIONAL` status and recomputes those settlements' `provisional_total_cents`, and recomputes the container's `last_completed_pickup_date` from its remaining `COMPLETED` visits. `SKIPPED` and `VOID` are the visit's terminal states; a visit reaches `SKIPPED` only through the theft-lock cascade of §3.3, never by direct request.

### 3.6. Quality Sampling and Laboratory Grading

The driver draws a quality sample at the visit, creating a sample in `COLLECTED` status linked to the visit through `pickup_visit_id`, and later submits it to the laboratory, moving it `COLLECTED` → `SUBMITTED`.

A `PlantOperator` grades a submitted sample by recording the lab results `lab_moisture_pct` and `lab_impurity_pct`, each a percentage between 0 and 100 at two decimal places. Grading computes the sample's `grade` on a worst-dimension rule. The moisture dimension is `A` when lab moisture is below 5.0, `B` when below 15.0, `C` when below 25.0, and `REJECT` at 25.0 or above. The impurity dimension is `A` when lab impurity is below 2.0, `B` when below 6.0, `C` when below 10.0, and `REJECT` at 10.0 or above. Every threshold band is lower-bound inclusive and upper-bound exclusive: a lab moisture of exactly 15.00 lands in `C`, and a lab impurity of exactly 2.00 lands in `B`. The sample's grade is the worse of the two dimensions under the quality ordering `A`, then `B`, then `C`, then `REJECT`.

Grading a sample that is already `GRADED` is rejected with `ERR_SAMPLE_ALREADY_GRADED` — the only legitimate path back through the lab is a dispute. A `FieldOpsManager` disputes a graded sample by supplying a `note`, persisted as `dispute_note`, which moves the sample `GRADED` → `DISPUTED`. Grading a `DISPUTED` sample recomputes and overwrites the grade, returning the sample to `GRADED`. The `GRADED` → `DISPUTED` → `GRADED` re-grade loop may repeat as often as needed.

### 3.7. Market Index Pricing and Settlement Billing

`BillingAnalyst` operators maintain market index quotes. Each quote names an `index_code`, a `week_start` (the Monday of the pricing week, as an ISO date), and a `price_cents_per_gal`, and starts in `DRAFT` status; the quote list supports optional `index_code`, `week_start`, and `status` filters. Publishing a quote stamps `published_at` from the logical clock and moves it `DRAFT` → `PUBLISHED`. Only one quote per index and week may stand published at a time: publishing a quote moves any other `PUBLISHED` quote with the same `index_code` and `week_start` to `SUPERSEDED`, which is terminal.

Publication cascades into open billing. Every settlement still in `PROVISIONAL` whose included pickups are priced — under the provisional variant — against the published `index_code` has its lines recomputed, mutating each affected line's `rate_cents_per_gal` and `line_amount_cents` and the settlement's `provisional_total_cents`.

Provisional pricing keys on the pickup date. The rate source is the `PUBLISHED` quote of the contract's `index_code` with the greatest `week_start` that is on or before the pickup's `scheduled_date`; ties on `week_start` break toward the quote with the later `published_at`, and any remaining tie breaks toward the earlier `created_at`. If no published quote covers the pickup, pricing fails with `ERR_QUOTE_NOT_PUBLISHED`.

Generating a settlement for a `customer_id` and a half-open billing period — `period_start` inclusive, `period_end` exclusive — creates a settlement in `PROVISIONAL` status with one provisional-variant line per eligible pickup: the customer's visits in `COMPLETED` status, excluding `VOID`, whose `scheduled_date` falls inside the period. Each line belongs to its settlement via `settlement_id`, references the billed visit via `pickup_visit_id`, records which calculation variant produced it in `variant` (`PROVISIONAL` or `FINAL`), and snapshots the contract's `pricing_mode`. Generation requires that the period is closed — the logical clock date is on or after `period_end`, otherwise `ERR_PERIOD_NOT_CLOSED`; that no other non-`VOID` settlement of the same customer overlaps the requested period, otherwise `ERR_DUPLICATE_PERIOD`; and that published quote coverage exists for every included pickup, otherwise `ERR_QUOTE_NOT_PUBLISHED`. The generated settlement's `provisional_total_cents` is the sum of its line amounts.

Every line carries the billed volume in `gallons_billed`, the resolved rate in `rate_cents_per_gal`, and the computed `line_amount_cents`. The two variants differ in their inputs. The provisional variant bills `net_gallons_provisional` and maps `field_moisture_pct` through the moisture thresholds of §3.6 to a field grade. The final variant bills lab-netted gallons — the pump gallons multiplied by one minus the lab moisture fraction, rounded half-up to two decimal places, using the `lab_moisture_pct` of the visit's `GRADED` sample — and uses the laboratory `grade` itself. Identical pump gallons can therefore net differently between the variants, and the line amounts diverge accordingly.

Grade factors scale the index price: `A` applies the price in full (factor 1.00), `B` retains 90 percent (factor 0.90), `C` retains 75 percent (factor 0.75), and `REJECT` zeroes the rate (factor 0.00). Under `REBATE` pricing, the raw rate is the resolved index price multiplied by the grade factor; the applied rate clamps the raw rate, raised to `floor_cents_per_gal` if the raw rate is below the floor and lowered to `cap_cents_per_gal` if above the cap; the line amount is the billed gallons multiplied by the applied rate, rounded half-up to whole cents — a positive amount the company owes the customer. Under `SERVICE_FEE` pricing, the line's `rate_cents_per_gal` is null; the overage gallons are the billed gallons exceeding `overage_threshold_gal`, never below zero; and the line amount is the negative of `service_fee_cents` plus the overage gallons multiplied by `overage_rate_cents_per_gal` rounded half-up to whole cents — the customer owes the company.

Rounding order is pinned: each line amount is rounded half-up to integer cents first, and the settlement total is the sum of those rounded integers. Summing unrounded amounts and rounding once at the end produces a different result and is not the contract. The provisional sum is stored in `provisional_total_cents`; the final sum, written at finalization, in `final_total_cents`.

Finalization moves the settlement `PROVISIONAL` → `FINALIZED` and recomputes every line under the final variant: laboratory grade, lab-netted gallons, and a final index price equal to the arithmetic mean of `price_cents_per_gal` across all `PUBLISHED` quotes of the contract's `index_code` whose `week_start` falls inside the half-open billing period, rounded half-up to a whole cent per gallon. Because provisional pricing keys each pickup on the single latest published week on or before its date while final pricing averages all in-period weeks, identical underlying quote data produces different rates between the two variants. Finalization is gated by four preconditions: the period must be closed (`ERR_PERIOD_NOT_CLOSED`); every included pickup must have at least one sample in `GRADED` status (`ERR_GRADE_PENDING`); at least one `PUBLISHED` quote must exist with a `week_start` inside the period for the contract's `index_code` (`ERR_QUOTE_NOT_PUBLISHED`); and the customer's active-era contract used for pricing must be in `ACTIVE`, `AT_RISK`, or `RENEWAL_OFFERED` — a contract in `DRAFT` or any terminal state fails with `ERR_CONTRACT_NOT_ACTIVE`. On success, `final_total_cents` is written and added to the customer's `rebate_balance_cents` per the ledger rule of §2.10.

Disbursement moves the settlement `FINALIZED` → `PAID` and enforces the payout floor: a settlement whose `final_total_cents` is below 100 cents is rejected with `ERR_PAYOUT_BELOW_MINIMUM`. Payment stamps `paid_at` from the logical clock and subtracts `final_total_cents` from the customer's `rebate_balance_cents`, moving the amount out of the open ledger into a recorded disbursement. Voiding is the compensating action and records a `reason`: voiding a `FINALIZED` settlement reverses the ledger posting by subtracting its `final_total_cents`, while voiding a `PROVISIONAL` settlement simply retires it with no ledger movement. Both paths land in `VOID`, which — like `PAID` — is a terminal settlement state.

### 3.8. Spill, Odor, Nuisance, and Theft-Attempt Complaints

A complaint is filed by a `CustomerContact` or a `FieldOpsManager` with a `customer_id`, a `category` of `SPILL`, `ODOR`, `NUISANCE`, or `THEFT_ATTEMPT`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, and a free-text `note`. The complaint may link the originating visit through `pickup_visit_id`; the link is optional in general but required when the category is `SPILL`. A `CustomerContact` files only for its own site — the `customer_id` must equal the caller's `X-User-ID`, otherwise the filing is rejected with `ERR_FORBIDDEN_ROLE`. New complaints start in `OPEN` status.

The investigation workflow belongs to the `FieldOpsManager`. Opening an investigation moves the complaint `OPEN` → `INVESTIGATING`; an investigation may escalate (`INVESTIGATING` → `ESCALATED`) with an optional `note`; and resolution is possible from either `INVESTIGATING` or `ESCALATED`, recording a `resolution_note` and stamping `resolved_at` from the logical clock as the complaint moves to `RESOLVED`.

Resolution is not necessarily final. The customer may reopen a resolved complaint within seven days of `resolved_at` — the logical clock must be no later than seven days after resolution; a later attempt is rejected with `ERR_COMPLAINT_REOPEN_WINDOW_EXPIRED`. Reopening records a fresh `note`, moves the complaint `RESOLVED` → `REOPENED`, and increments `reopen_count`. From `REOPENED` the workflow re-enters investigation, so the `RESOLVED` → `REOPENED` → `INVESTIGATING` → `RESOLVED` recurrence loop may repeat.

Complaints close lazily per §2.4: on any read or write once the logical clock is strictly more than seven days after `resolved_at`, a `RESOLVED` complaint transitions to `CLOSED`, its terminal state. The boundary is exact — exactly seven days after resolution the complaint can still be reopened and is not yet auto-closed; only after that instant does auto-close apply.

Spill complaints gate the rendering plant. Tipping a reconciled manifest into a processing batch is blocked with `ERR_SPILL_COMPLAINT_OPEN` while any `SPILL`-category complaint linked to one of the manifest's pickups is `OPEN`, `INVESTIGATING`, `ESCALATED`, or `REOPENED`. Spill complaints that have reached `RESOLVED` or `CLOSED` do not block intake.

### 3.9. Rendering Batches, Yield, and Product Resale

Once a route is reconciled, a `PlantOperator` tips the raw oil into a processing batch by referencing the source `manifest_id` and declaring the `input_gallons` tipped in, which must equal the manifest's `collected_gallons`. A manifest feeds at most one processing batch.

Intake computes two derived figures. First, `weighted_moisture_pct`: the volume-weighted effective moisture across the manifest's `COMPLETED`, non-`VOID` pickups, where each pickup's effective moisture is its `lab_moisture_pct` when that pickup has a `GRADED` sample and its `field_moisture_pct` otherwise — the sum of each pickup's `pump_gallons` multiplied by its effective moisture, divided by the total pumped gallons, rounded half-up to two decimal places. Second, `est_yield_gallons`: the input gallons multiplied by one minus the weighted moisture fraction, multiplied by the fixed yield coefficient 0.92, rounded half-up to two decimal places. The batch starts in `INTAKE` status, subject to the spill gate of §3.8.

Processing records the metered `actual_output_gallons` of saleable product and moves the batch `INTAKE` → `PROCESSED`, computing `yield_rate` as the metered output divided by `input_gallons`, rounded half-up to four decimal places. The metered yield supersedes the estimate: the formula-derived estimate at intake and the metered reality at process completion commonly diverge for the same batch.

Selling records the agreed `sale_price_cents_per_gal` and moves the batch `PROCESSED` → `SOLD`, its terminal state, computing `sale_revenue_cents` as the metered output gallons multiplied by the sale price, rounded half-up to whole cents.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — a customer, contract, container, truck, manifest, quote, sample, settlement, complaint, theft incident, or processing batch — return `201 Created`. Operations that modify an existing resource, including all lifecycle actions and the stop-list re-plan, return `200 OK`. The complete request and response semantics of each endpoint are defined by the workflows in §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Test-driving endpoint: set the logical clock | SystemAdmin |
| POST | `/api/customers` | Register a customer site | SystemAdmin, FieldOpsManager |
| GET | `/api/customers` | List customers with pagination and optional status filter | SystemAdmin, FieldOpsManager, RouteDispatcher, BillingAnalyst, PlantOperator |
| GET | `/api/customers/{id}` | Get one customer; CustomerContact restricted to own id | SystemAdmin, FieldOpsManager, RouteDispatcher, BillingAnalyst, PlantOperator, CustomerContact |
| POST | `/api/customers/{id}/suspend` | Manually suspend a customer | SystemAdmin, FieldOpsManager |
| POST | `/api/customers/{id}/reinstate` | Reinstate a suspended customer | SystemAdmin, FieldOpsManager |
| POST | `/api/customers/{id}/terminate` | Terminate a customer whose contracts are all terminal | SystemAdmin, FieldOpsManager |
| POST | `/api/customers/{id}/contracts` | Draft a contract for the customer | SystemAdmin, FieldOpsManager |
| GET | `/api/customers/{id}/contracts` | List contracts of a customer | SystemAdmin, FieldOpsManager, BillingAnalyst, CustomerContact |
| GET | `/api/customers/{id}/containers` | List containers of a customer | SystemAdmin, FieldOpsManager, RouteDispatcher, CustomerContact |
| GET | `/api/customers/{id}/settlements` | List settlements of a customer | SystemAdmin, FieldOpsManager, BillingAnalyst, CustomerContact |
| GET | `/api/customers/{id}/complaints` | List complaints of a customer | SystemAdmin, FieldOpsManager, CustomerContact |
| GET | `/api/contracts/{id}` | Get one contract | SystemAdmin, FieldOpsManager, BillingAnalyst, CustomerContact |
| POST | `/api/contracts/{id}/activate` | Activate a draft contract | SystemAdmin, FieldOpsManager |
| POST | `/api/contracts/{id}/amend` | Amend rate fields (OCC-guarded); from AT_RISK this is the retention action returning the contract to ACTIVE | FieldOpsManager |
| POST | `/api/contracts/{id}/offer-renewal` | Offer renewal terms | FieldOpsManager |
| POST | `/api/contracts/{id}/respond-renewal` | Accept or reject the pending renewal offer | CustomerContact, FieldOpsManager |
| POST | `/api/contracts/{id}/flag-poach` | Record a competitor poaching offer | CustomerContact, FieldOpsManager |
| POST | `/api/contracts/{id}/terminate` | Terminate contract with reason VOLUNTARY or POACHED | FieldOpsManager |
| POST | `/api/customers/{id}/containers` | Place a locked container at the customer site | FieldOpsManager |
| GET | `/api/containers/{id}` | Get one container | SystemAdmin, FieldOpsManager, RouteDispatcher, Driver, CustomerContact |
| POST | `/api/containers/{id}/unlock` | Unlock a theft-locked container after incidents are resolved | FieldOpsManager |
| POST | `/api/containers/{id}/remove` | Remove a container from service | FieldOpsManager |
| GET | `/api/containers/{id}/pickup-visits` | List visits of a container | SystemAdmin, FieldOpsManager, RouteDispatcher, Driver, CustomerContact |
| GET | `/api/containers/{id}/theft-incidents` | List theft incidents of a container | SystemAdmin, FieldOpsManager, RouteDispatcher, CustomerContact |
| POST | `/api/market-index-quotes` | Create a draft market index quote | BillingAnalyst |
| POST | `/api/market-index-quotes/{id}/publish` | Publish a quote; supersedes same week/index and recomputes PROVISIONAL settlements | BillingAnalyst |
| GET | `/api/market-index-quotes` | List quotes with optional filters | SystemAdmin, FieldOpsManager, BillingAnalyst |
| POST | `/api/trucks` | Register a tanker | SystemAdmin, RouteDispatcher |
| GET | `/api/trucks/{id}` | Get one truck | SystemAdmin, FieldOpsManager, RouteDispatcher, Driver |
| POST | `/api/trucks/{id}/service-status` | Set truck IN_SERVICE / OUT_OF_SERVICE | RouteDispatcher |
| GET | `/api/trucks/{id}/manifests` | List manifests of a truck | SystemAdmin, RouteDispatcher, Driver |
| POST | `/api/route-manifests` | Create a DRAFT manifest with a stop list; creates one SCHEDULED PickupVisit per container | RouteDispatcher |
| GET | `/api/route-manifests/{id}` | Get one manifest | SystemAdmin, FieldOpsManager, RouteDispatcher, Driver, PlantOperator |
| PATCH | `/api/route-manifests/{id}` | Replace the stop list of a DRAFT manifest (OCC-guarded) | RouteDispatcher |
| POST | `/api/route-manifests/{id}/dispatch` | Dispatch the route | RouteDispatcher |
| POST | `/api/route-manifests/{id}/complete` | Driver closes the route once all visits are terminal | Driver |
| POST | `/api/route-manifests/{id}/reconcile` | Reconcile tank levels against collected gallons | RouteDispatcher |
| GET | `/api/route-manifests/{id}/pickup-visits` | List visits of a manifest | SystemAdmin, FieldOpsManager, RouteDispatcher, Driver |
| GET | `/api/route-manifests/{id}/processing-batches` | List processing batches fed by this manifest (0 or 1) | SystemAdmin, RouteDispatcher, PlantOperator |
| GET | `/api/pickup-visits/{id}` | Get one visit | SystemAdmin, FieldOpsManager, RouteDispatcher, Driver, BillingAnalyst, CustomerContact |
| POST | `/api/pickup-visits/{id}/start` | Driver marks arrival (EN_ROUTE) | Driver |
| POST | `/api/pickup-visits/{id}/complete` | Record pump meter gallons and field moisture | Driver |
| POST | `/api/pickup-visits/{id}/fail` | Record a failed pickup attempt | Driver |
| POST | `/api/pickup-visits/{id}/void` | Compensating reversal of a completed pickup | RouteDispatcher |
| POST | `/api/pickup-visits/{id}/samples` | Draw a quality sample at the visit | Driver |
| GET | `/api/pickup-visits/{id}/samples` | List samples of a visit | SystemAdmin, FieldOpsManager, Driver, PlantOperator, BillingAnalyst |
| GET | `/api/pickup-visits/{id}/settlement-lines` | List settlement lines billing this visit | SystemAdmin, BillingAnalyst, CustomerContact |
| GET | `/api/pickup-visits/{id}/complaints` | List complaints linked to this visit | SystemAdmin, FieldOpsManager, CustomerContact |
| POST | `/api/quality-samples/{id}/submit` | Submit sample to the lab | Driver |
| POST | `/api/quality-samples/{id}/grade` | Record lab results and compute grade | PlantOperator |
| POST | `/api/quality-samples/{id}/dispute` | Dispute a graded sample (opens re-grade loop) | FieldOpsManager |
| POST | `/api/settlements/generate` | Generate a PROVISIONAL settlement for a closed period from COMPLETED non-VOID pickups | BillingAnalyst |
| GET | `/api/settlements/{id}` | Get one settlement | SystemAdmin, BillingAnalyst, CustomerContact |
| GET | `/api/settlements/{id}/lines` | List lines of a settlement | SystemAdmin, BillingAnalyst, CustomerContact |
| POST | `/api/settlements/{id}/finalize` | Recompute lines under the FINAL variant and post to the rebate ledger | BillingAnalyst |
| POST | `/api/settlements/{id}/pay` | Disburse a finalized settlement | BillingAnalyst |
| POST | `/api/settlements/{id}/void` | Void a settlement (compensating action) | BillingAnalyst |
| POST | `/api/complaints` | File a spill/odor/nuisance/theft-attempt complaint | CustomerContact, FieldOpsManager |
| POST | `/api/complaints/{id}/investigate` | Open investigation | FieldOpsManager |
| POST | `/api/complaints/{id}/escalate` | Escalate an investigation | FieldOpsManager |
| POST | `/api/complaints/{id}/resolve` | Resolve the complaint | FieldOpsManager |
| POST | `/api/complaints/{id}/reopen` | Reopen a resolved complaint within 7 days | CustomerContact |
| POST | `/api/processing-batches` | Tip a reconciled manifest into a rendering batch | PlantOperator |
| POST | `/api/processing-batches/{id}/process` | Record metered output | PlantOperator |
| POST | `/api/processing-batches/{id}/sell` | Sell the rendered product | PlantOperator |
| POST | `/api/theft-incidents` | Report container tampering | Driver, CustomerContact, FieldOpsManager |
| POST | `/api/theft-incidents/{id}/confirm` | Confirm tampering: locks the container and cascades | FieldOpsManager |
| POST | `/api/theft-incidents/{id}/dismiss` | Dismiss a report | FieldOpsManager |
| POST | `/api/theft-incidents/{id}/resolve` | Resolve a confirmed incident (lock replaced) | FieldOpsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CONTAINER_LOCKED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SAMPLE_ALREADY_GRADED` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TRUCK_UNAVAILABLE` | 409 Conflict |
| `ERR_SPILL_COMPLAINT_OPEN` | 422 Unprocessable Entity |
| `ERR_CONTRACT_TERM_OVERLAP` | 409 Conflict |
| `ERR_MANIFEST_DATE_CONFLICT` | 409 Conflict |
| `ERR_TANK_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CONTAINER_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TANK_IMBALANCE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PERIOD` | 409 Conflict |
| `ERR_PICKUP_WINDOW_FUTURE` | 422 Unprocessable Entity |
| `ERR_PERIOD_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_CONTRACT_IN_COOLING_OFF` | 422 Unprocessable Entity |
| `ERR_COMPLAINT_REOPEN_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_OPEN_SETTLEMENTS` | 422 Unprocessable Entity |
| `ERR_GRADE_PENDING` | 422 Unprocessable Entity |
| `ERR_QUOTE_NOT_PUBLISHED` | 422 Unprocessable Entity |
| `ERR_THEFT_UNRESOLVED` | 409 Conflict |
| `ERR_PAYOUT_BELOW_MINIMUM` | 422 Unprocessable Entity |
