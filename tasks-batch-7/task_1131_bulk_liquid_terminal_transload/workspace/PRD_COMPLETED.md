# Bulk Liquid Terminal API — Product Requirements Document

## 1. Introduction

A bulk liquid terminal lives and dies by two things: the accuracy of the barrels it says it holds, and the discipline with which it schedules the steel that carries those barrels in and out. This document specifies the Bulk Liquid Terminal API, a system that governs tank leasing, receipt and discharge scheduling across vessel, rail, and truck modes, gauging and custody transfer measurement, quality sampling and retain, throughput billing with minimum volume commitments, loss and shrinkage accounting, vapor-control safety permitting, and demurrage and dwell charges.

The system is built for an operator running a multi-customer terminal in the style of a Kinder Morgan facility. Customers lease capacity; terminal staff allocate that capacity against physical tanks; schedulers nominate and drive movements of product; independent gaugers and quality inspectors provide the measurement and laboratory evidence; billing clerks close monthly statements; and a terminal manager adjudicates amendments, permits, custody certification, and disputes. Segregation of duties is a first-class concern — the person who gauges a tank is not the person who certifies its custody transfer, and the person who collects a sample is not the person who records its lab result.

Underneath the workflow sits a precise fiscal and physical model. Tank capacity is finite and leased against a working capacity derived from shell capacity, safe-fill percentage, and unpumpable heel. Custody volume is temperature-corrected and, at certification, further corrected by the lab's specific gravity. Shrinkage is measured against a contractual loss allowance and excess loss carries a per-barrel charge that, when it breaches a terminal-wide cap on a monthly statement, automatically suspends the lease. Demurrage is charged against free-hours allowances that differ by mode, with both a forward-looking estimate at schedule time and an actual settlement at completion. The sections that follow define the contracts, state machines, calculations, and validation rules in full.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply uniformly across every endpoint and every entity in the terminal.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes seven roles, spelled exactly as follows: `TerminalManager`, `TerminalOperator`, `Scheduler`, `Gauger`, `QualityInspector`, `BillingClerk`, and `CustomerRep`.

- A `TerminalManager` holds terminal authority: customer onboarding, the lease lifecycle (activate, suspend, reactivate, terminate), amendment approval and rejection, permit approval and revocation, custody certification, resolution and voiding, and control of the logical clock.
- A `TerminalOperator` runs the physical plant: tank registration and maintenance, terminal resource registration, tank allocations and their activation and release, and permit requests.
- A `Scheduler` nominates movements and drives them through their lifecycle — schedule, arrive, start, complete, cancel, resume.
- A `Gauger` records opening and closing gauge tickets on movements.
- A `QualityInspector` collects quality samples, records laboratory results, and releases retains.
- A `BillingClerk` creates monthly statements, closes them after period end, and invoices them.
- A `CustomerRep` acts on behalf of a customer organization: creating lease agreements, proposing lease amendments, and disputing custody transfers.

For the roles `TerminalManager`, `TerminalOperator`, `Scheduler`, `Gauger`, `QualityInspector`, and `BillingClerk`, the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `recorded_by_user_id` on a gauge ticket, `collected_by_user_id` or `result_recorded_by_user_id` on a sample, or `certified_by_user_id` on a custody transfer), but it never compares such an identifier to any entity's `id`. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` — the `customer_id` on a lease being created, the lease targeted by an amendment proposal, or the lease owning a custody transfer being disputed — compare that resource's customer foreign key to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

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

Requests falling outside the endpoint surface of §4 — an unknown path, or an unsupported method on a known path — are rejected with a framework-level `404` (`ERR_NOT_FOUND`) or `405` (`ERR_METHOD_NOT_ALLOWED`) error body whose `meta` is empty; these two identifiers are not part of the §5 catalogue.

### 2.3. Pagination

List endpoints accept two pagination query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, and a non-integer value or any value below 1 or above 100 is rejected with `ERR_VALIDATION` (HTTP 400). The `offset` parameter sets how many items to skip, defaults to 0, and must be a non-negative integer on the same error terms. Every list response sorts its resources by `created_at` in ascending order, breaking ties by `id` ascending — except the movements list, which breaks ties by `sequence_no` ascending — and the `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. Beyond pagination, certain list endpoints accept equality filters, each compared exactly against the stored field: `GET /tanks` filters by `status`; `GET /terminal-resources` by `resource_type` and `status`; `GET /lease-agreements` by `customer_id` and `status`; `GET /permits` by `tank_id`, `permit_type`, and `status`; and `GET /movements` by `lease_id`, `tank_id`, `resource_id`, and `status`.

### 2.4. The Logical Clock and Lazy Expiry

The terminal runs on a logical clock, not wall-clock time. At startup the logical clock reads exactly `2026-05-01T00:00:00Z`; until a `TerminalManager` advances it, every entity timestamp the system stamps comes from that default and the clock never falls back to wall time. The one timestamp the logical clock does not govern is the response envelope's `api_request_timestamp`, which is stamped from wall-clock time. A manager-facing test-driving capability accepts a `to_iso8601` value and advances the clock to that instant, returning the new `current_utc`. The logical clock stamps every entity's `created_at` and `updated_at`, every movement's `actual_arrival_at`, `actual_start_at`, and `actual_complete_at`, and every lazy expiry evaluation described below.

Two entities expire lazily rather than by batch job. A lease whose `end_date` is earlier than the current logical clock date transitions from `ACTIVE` or `SUSPENDED` to `EXPIRED` the next time the lease is read or its state is evaluated as a precondition. A permit whose `valid_until` is earlier than the current logical clock likewise transitions from `REQUESTED` or `APPROVED` to `EXPIRED` on next access. List endpoints apply this lazy evaluation row by row as they render.

### 2.5. Common Resource Properties and Optimistic Concurrency

Every top-level resource carries a system-managed `id` formatted as a UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that starts at 1 at creation and increments by one on every modification. The single exception is the `GaugeTicket`: gauge tickets are append-only measurement records and carry only `id` and `created_at`; neither `updated_at` nor `version` exists on a gauge ticket.

Mutations that cascade across entities — for example, an allocation activation that recomputes a lease's `reserved_capacity_bbl`, or a custody certification that recomputes a tank's inventory — count as mutations of each affected entity and therefore refresh `updated_at` and increment `version` on each.

Optimistic concurrency control applies to exactly one write path: proposing an amendment against a lease. Such a proposal must carry `expected_lease_version`, a non-optional field holding the lease `version` the client last observed. If the lease's current `version` does not equal that value — because another amendment was proposed, an allocation was activated or released, or the lease was suspended, reactivated, or otherwise mutated — the proposal is rejected with `ERR_STALE_VERSION` (HTTP 412), and the rejected proposal is not persisted. When the proposal is accepted, the amendment pins `base_lease_version` from the accepted `expected_lease_version`. Endpoints not named in this rule take no version field at all.

### 2.6. Tank Capacity, Working Limits, and the RESTRICTED Posture

A tank's nameplate size is its `capacity_bbl`, which must be greater than zero. Its usable ceiling is lower: `working_capacity_bbl` equals the floor of `capacity_bbl` multiplied by `safe_fill_pct`, minus `heel_bbl` — the floor is applied to the product before the heel is subtracted, so the result is a whole number of barrels before heel subtraction. When `safe_fill_pct` is omitted at tank creation it defaults to 0.95, and it must always lie strictly between 0 and 1 inclusive at the upper bound. `heel_bbl` defaults to 0 when omitted and may not be negative.

The system continuously reconciles certified inventory against those bounds. `current_inventory_bbl` is the read-only certified inventory of a tank: the sum over the tank's custody transfers in `CERTIFIED` or `DISPUTED` status of the signed certified volume, where a `RECEIPT` movement contributes positively and a `DISCHARGE` negatively. `PROVISIONAL` and `VOID` transfers contribute zero to this figure. A second figure, `provisional_inventory_bbl`, starts from `current_inventory_bbl` and adds the signed provisional volumes of the tank's `PROVISIONAL` custody transfers, giving operators a forward view that includes not-yet-certified movements.

Whenever a custody certification, dispute resolution, or void recomputes these figures and `current_inventory_bbl` lands above `working_capacity_bbl` or below `heel_bbl`, the tank automatically transitions from `AVAILABLE` to `RESTRICTED`. While a tank is `RESTRICTED`, allocation creation, allocation activation, and movement creation against that tank all fail with `ERR_TANK_NOT_AVAILABLE`. When a later recompute brings `current_inventory_bbl` back inside the inclusive range from `heel_bbl` to `working_capacity_bbl`, the tank returns from `RESTRICTED` to `AVAILABLE` automatically. A certify followed by a void of the same transfer must leave `current_inventory_bbl` unchanged — voiding is the compensating action that excludes the transfer from the inventory projection.

Manual maintenance is orthogonal to this automatic posture. A `TerminalOperator` may move an `AVAILABLE` tank into `MAINTENANCE`, but only when no movement on that tank is in `ARRIVED`, `IN_PROGRESS`, or `SUSPENDED` status; otherwise the request is rejected with `ERR_INVALID_STATE`. Returning a tank from `MAINTENANCE` to `AVAILABLE` performs no inventory re-evaluation: the bounds are only re-checked on custody certify, resolve, or void, never on maintenance return.

### 2.7. Resource Windows, Concurrency, and Occupation Semantics

Terminal resources — docks, rail racks, and truck bays — are the schedulable steel of the terminal. Each carries a `resource_code` (recorded exactly as supplied; the server enforces no uniqueness constraint on it), a `resource_type` of `DOCK`, `RAIL_RACK`, or `TRUCK_BAY`, and a `concurrent_capacity` that must be an integer of at least 1 and defaults to 1. The mapping between transport mode and resource type is fixed: `VESSEL` movements occupy a `DOCK`, `RAIL` movements occupy a `RAIL_RACK`, and `TRUCK` movements occupy a `TRUCK_BAY`. A `concurrent_capacity` greater than 1 is permitted only on a `TRUCK_BAY`; creating a resource with `concurrent_capacity` above 1 whose `resource_type` is `DOCK` or `RAIL_RACK`, or scheduling a movement onto a resource whose type does not match its mode's mapping, is rejected with `ERR_RESOURCE_TYPE_MISMATCH` (HTTP 422).

Occupation windows are half-open intervals: a movement occupies its resource from `window_start` inclusive to `window_end` exclusive. On a `DOCK` or `RAIL_RACK`, occupation is exclusive — a candidate window conflicts with an existing one whenever the candidate's start is before the existing window's end and the existing window's start is before the candidate's end, considering movements in `SCHEDULED`, `ARRIVED`, `IN_PROGRESS`, or `SUSPENDED` status on that resource. Pure adjacency is allowed: an existing window whose end equals the candidate's start does not conflict. On a `TRUCK_BAY` with `concurrent_capacity` greater than 1, occupation is aggregate: the candidate conflicts only if at some instant the number of simultaneously overlapping occupations — the existing maximum concurrent overlap count plus the candidate — would exceed `concurrent_capacity`. A schedule attempt that collides under these rules is rejected with `ERR_WINDOW_CONFLICT` (HTTP 409). Window comparisons are made on the full timestamp values exactly as supplied and recorded, with no truncation to a coarser precision.

Taking a resource out of service does not displace work already booked: movements in `SCHEDULED`, `ARRIVED`, or `IN_PROGRESS` on the resource continue untouched, but new schedule attempts against an `OUT_OF_SERVICE` resource fail with `ERR_RESOURCE_UNAVAILABLE` (HTTP 409). Returning the resource to service restores normal scheduling.

### 2.8. Vapor Control and Permit Safety

Tanks that store volatile product may be flagged `vapor_control_class` = `VRU_REQUIRED`; all other tanks carry the default `NONE`. A tank requiring vapor control may not begin or resume pumping unless an `APPROVED` permit of `permit_type` `VAPOR_CONTROL` exists for that tank and its validity window covers the current logical clock time — a permit covers the current time when `valid_from` is at or before it and `valid_until` is at or after it (both bounds inclusive). A permit request names the `tank_id`, the `permit_type`, and the `valid_from` and `valid_until` window; a `valid_until` not strictly after `valid_from` is rejected with `ERR_VALIDATION`. Permits also come in a `HOT_WORK` type; both types follow the same lifecycle from `REQUESTED` to `APPROVED`, and thence to `REVOKED` or to the lazily-applied `EXPIRED`.

Revoking an approved permit — an action that accepts an optional free-text `revoked_reason` (validated as a string when present, but not persisted on the permit) — has a cascading safety effect: every movement on the permit's tank that is currently `IN_PROGRESS` — where the tank's `vapor_control_class` is `VRU_REQUIRED` — transitions to `SUSPENDED`. Such a movement can later be driven back to `IN_PROGRESS` by a resume action, but only once a fresh approved vapor-control permit again covers the current time.

### 2.9. Nested Resource Retrieval and Validation Ordering

When an endpoint path contains multiple identifiers — a gauge ticket under a movement, a statement under a lease, an amendment under a lease — the system resolves path identifiers strictly left to right and rejects with the 404 variant corresponding to the first identifier that fails to resolve. The per-entity variants are `ERR_CUSTOMER_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_RESOURCE_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_CUSTODY_TRANSFER_NOT_FOUND`, and `ERR_STATEMENT_NOT_FOUND`, each with HTTP 404. Body-supplied foreign keys are resolved after the path template resolves.

Across a request's full validation pipeline, checks are applied in a fixed priority order so that earlier failures mask later ones deterministically: authentication header presence and role recognition first (`ERR_UNAUTHENTICATED`), then endpoint role authorization (`ERR_UNAUTHORIZED_ROLE`), then request schema and field validity including the requirement that an amendment proposal carry at least one proposed field (`ERR_VALIDATION`), then `CustomerRep` ownership linkage (`ERR_FORBIDDEN_OWNERSHIP`) — evaluated the moment the customer-bearing resource can be located, so a lease named directly in the path or in the body is ownership-checked without waiting on any not-found rejection, while ownership derived through another path identifier (the lease behind a custody transfer being disputed) is checked immediately after that identifier resolves — then path and body reference resolution (the 404 family), except that the state-machine from-state check (`ERR_INVALID_STATE`) of a path-identified resource is applied as soon as that resource has resolved and any applicable ownership check has passed, and therefore precedes the resolution of body-supplied foreign keys and derived references, then the amendment optimistic-concurrency check (`ERR_STALE_VERSION`), then the lease, tank, resource, gauge, custody, amendment-base, segregation-of-duties, permit, quality, and retain state and safety checks in that relative order, and finally the business constraint, temporal, and fiscal checks — product match, gauge sequence, window shape, allocation period, resource-type match, statement uniqueness, window conflict, window lapse, statement period end, allocation capacity, active-allocation presence, and volume-within-allocation.

### 2.10. Monetary Precision and Rounding Discipline

All money amounts the API stores or returns are decimal numbers rounded to exactly 2 decimal places using round-half-up. Volume arithmetic works in whole barrels wherever a custody figure is involved — provisional and certified volumes are rounded half-up to zero decimal places, with the rounding applied exactly once per variant computation. Two rounding disciplines matter and must not be conflated. Within the tiered throughput fee, the marginal per-tier amounts are summed first and the total is rounded once at the end (sum-then-round). Across a monthly statement's excess-loss and demurrage lines, each line is already rounded to 2 decimal places at the moment it is computed — at certify time for excess loss, at complete time for demurrage — and the statement sums those pre-rounded line values exactly (round-per-line-then-sum). Summing unrounded raw line values and rounding the total is forbidden, because the two orders produce different cents.

### 2.11. Segregation of Duties

Custody and quality evidence are worthless if the same hand writes both the measurement and its acceptance. The system therefore enforces two segregation rules, both rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). First, the `X-User-ID` that certifies a custody transfer must differ from the `recorded_by_user_id` on the movement's gauge tickets. Second, the `X-User-ID` that records a sample's laboratory result must differ from the `collected_by_user_id` who drew the sample. Because the gauger and certifier identities are opaque operator identifiers, the comparison is purely between the recorded header values.

## 3. Business Logic & Workflows

### 3.1. Onboarding Customers, Tanks, and Terminal Resources

Before any product moves, the terminal's master data must exist. A `TerminalManager` onboards a counterparty by creating a `Customer` with the customer's legal `name` and a primary `contact_email`.

A `TerminalOperator` registers each storage tank by supplying a `tank_code` (recorded exactly as supplied; the server enforces no uniqueness constraint on it) together with the `product_grade` the tank will hold (`GASOLINE`, `DIESEL`, `JET`, `ETHANOL`, or `CRUDE`), its `capacity_bbl`, and optionally `safe_fill_pct`, `heel_bbl`, and `vapor_control_class`. At creation the tank's `working_capacity_bbl` is computed per §2.6, its `current_inventory_bbl` and `provisional_inventory_bbl` start at 0, and its `status` is `AVAILABLE`.

The same role registers the terminal's schedulable resources. Creating a `TerminalResource` requires a `resource_code`, a `resource_type`, and optionally a `concurrent_capacity`; a new resource starts in `ACTIVE` status. The resource-type constraints of §2.7 apply at creation: a `DOCK` or `RAIL_RACK` declaring more than one unit of concurrent capacity is rejected with `ERR_RESOURCE_TYPE_MISMATCH`.

### 3.2. Lease Agreements and Their Lifecycle

A lease is the commercial spine of the terminal relationship. A `CustomerRep` creates a `LeaseAgreement` for their own customer — the payload's `customer_id` must equal the caller's `X-User-ID`, failing which the request is rejected with `ERR_FORBIDDEN_OWNERSHIP`. The proposal names the `product_grade` being leased, the total `committed_capacity_bbl` (greater than zero), the `min_monthly_throughput_bbl` volume commitment (zero or more), the `throughput_fee_per_bbl` base rate (greater than zero), the `shortfall_fee_per_bbl` applied to commitment shortfalls (zero or more), the `loss_allowance_pct` contractual heel-and-loss fraction (zero or more; for example 0.005 for half a percent), the `excess_loss_rate_per_bbl` charged per excess-loss barrel (zero or more), and the inclusive `start_date` and `end_date` in `YYYY-MM-DD` form, where an end date earlier than the start date is rejected with `ERR_VALIDATION`. A new lease is in `DRAFT` with `reserved_capacity_bbl` at 0.

A lease becomes commercially live when a `TerminalManager` activates it — but activation is refused with `ERR_NO_ACTIVE_ALLOCATION` unless at least one tank allocation for the lease is already `ACTIVE`. From `ACTIVE`, a manager may suspend the lease, which records `suspension_reason` as `MANUAL`; the system itself may also suspend an `ACTIVE` lease when a recomputed open statement's excess loss breaches the cap described in §3.8, in which case `suspension_reason` is recorded as `LOSS_CONTROL`. A suspended lease may be reactivated by a manager, which clears `suspension_reason` back to null. Both `ACTIVE` and `SUSPENDED` leases age into `EXPIRED` lazily per §2.4, and an `ACTIVE` lease may be terminated by a manager provided no movement of the lease is in `SCHEDULED`, `ARRIVED`, `IN_PROGRESS`, or `SUSPENDED` status — a termination attempt while such movements exist is rejected with `ERR_INVALID_STATE`. Termination releases every allocation of the lease that is `RESERVED` or `ACTIVE` into `RELEASED` and recomputes `reserved_capacity_bbl` to 0. Each lease mutation — activate, suspend, reactivate, terminate, amendment proposal, amendment approval, allocation activate or release — increments the lease's `version` by 1 and refreshes `updated_at`.

The lease status gates downstream work. Creating a movement and scheduling it both require the lease to be `ACTIVE`. Creating an allocation and activating it require the lease to be in `DRAFT` or `ACTIVE`. Creating an amendment and approving it require `ACTIVE` or `SUSPENDED`. Creating a monthly statement is refused for a lease that has reached `EXPIRED` or `TERMINATED`. Each of these violations surfaces as `ERR_LEASE_NOT_ACTIVE` (HTTP 409).

### 3.3. Amending Lease Terms

Commercial terms change mid-contract, and the system manages that change through an explicit two-step negotiation with optimistic concurrency at both ends. A `CustomerRep` proposes a `LeaseAmendment` against a lease, supplying `expected_lease_version` per the OCC rule of §2.5 plus at least one of `proposed_committed_capacity_bbl`, `proposed_throughput_fee_per_bbl`, or `proposed_min_monthly_throughput_bbl` — a proposal carrying none of the proposed fields is rejected with `ERR_VALIDATION`. Supplied values must respect their normal bounds: proposed committed capacity and proposed fee must be greater than zero, and the proposed minimum throughput may be zero or more. The proposal is only accepted while the lease is `ACTIVE` or `SUSPENDED`. An accepted amendment is persisted in `PROPOSED` status, its `base_lease_version` pinned from the accepted `expected_lease_version`, and — importantly — the act of proposing itself increments the lease's `version` by 1, because a live proposal legitimately supersedes the prior negotiation basis.

A `TerminalManager` then approves or rejects the proposal. Approval checks two things, in this order relative to the other state checks: the lease must currently be `ACTIVE` or `SUSPENDED` (otherwise `ERR_LEASE_NOT_ACTIVE`), and the lease's current `version` must still equal the amendment's `base_lease_version` plus one — the proposal's own version increment accounts for the plus one. If the lease has moved on since the proposal — through any further version-incrementing mutation — approval fails with `ERR_AMENDMENT_STALE_BASE` (HTTP 409). On a successful approval, each non-null proposed field is applied onto the lease and the lease's `version` increments by 1 again. Rejection simply moves the amendment to `REJECTED` with no lease mutation. Both `APPROVED` and `REJECTED` are terminal for the amendment.

### 3.4. Allocating Tank Capacity to Leases

A lease's committed capacity becomes physical through `TankAllocation` records, each binding the lease to a tank for a closed date range. A `TerminalOperator` creates an allocation by naming the `tank_id` and the `allocated_bbl` — a quantity greater than zero and no greater than the tank's `working_capacity_bbl` — together with `period_start` and `period_end` in `YYYY-MM-DD` form. The period must satisfy `period_end` on or after `period_start` and must lie entirely within the lease's `start_date` to `end_date`; violations are rejected with `ERR_ALLOCATION_PERIOD_INVALID` (HTTP 422). The target tank must be `AVAILABLE`, and the lease must be in `DRAFT` or `ACTIVE`; failures surface as `ERR_TANK_NOT_AVAILABLE` and `ERR_LEASE_NOT_ACTIVE` respectively. A new allocation is `RESERVED`.

Both at creation and at the later activation step, an aggregate capacity sweep runs over the tank. The sweep considers every allocation of the same tank in `RESERVED` or `ACTIVE` status and treats each period as a closed range of calendar dates. For every calendar date covered by the candidate's period, the sweep totals the `allocated_bbl` of all overlapping allocations on that date; if any date's existing total plus the candidate's `allocated_bbl` would exceed the tank's `working_capacity_bbl`, the operation is rejected with `ERR_ALLOCATION_CAPACITY_EXCEEDED` (HTTP 409). Exact equality — the summed total landing exactly on working capacity — is allowed. Because daily totals only change at period boundaries, the sweep evaluates only the finite set of period boundary dates drawn from the candidate and existing periods.

Activation by a `TerminalOperator` moves the allocation from `RESERVED` to `ACTIVE`, re-running the lease-state, tank-state, and capacity-sweep checks described above. Activation recomputes the lease's `reserved_capacity_bbl` as the sum of `allocated_bbl` over the lease's `ACTIVE` allocations and increments the lease's `version` by 1. Release — the compensating action of activation — moves an `ACTIVE` allocation to `RELEASED`, but only when no movement on the same lease-and-tank pair is in `SCHEDULED`, `ARRIVED`, `IN_PROGRESS`, or `SUSPENDED` status; otherwise the release is rejected with `ERR_INVALID_STATE`. Release likewise recomputes the lease's `reserved_capacity_bbl` and increments its `version`.

### 3.5. Nominating and Scheduling Movements

A `Scheduler` nominates a movement — a receipt into a tank or a discharge out of one — by supplying the `lease_id`, the `tank_id`, the `direction` (`RECEIPT` or `DISCHARGE`), the transport `mode` (`VESSEL`, `RAIL`, or `TRUCK`), the `product_grade` moved, the `declared_volume_bbl` from the nomination or bill of lading, and the requested occupation window `window_start` and `window_end`. The window must open before it closes: a `window_end` not strictly after `window_start` is rejected with `ERR_WINDOW_INVALID` (HTTP 422). The movement's `product_grade` must equal both the lease's and the tank's grade; a mismatch is rejected with `ERR_PRODUCT_MISMATCH` (HTTP 422). The lease must be `ACTIVE` and the tank `AVAILABLE`, an `ACTIVE` allocation covering the lease-and-tank pair must exist (`ERR_NO_ACTIVE_ALLOCATION`), and `declared_volume_bbl` must be greater than zero — a schema requirement whose violation is `ERR_VALIDATION` — and no greater than that allocation's `allocated_bbl`, an excess being rejected with `ERR_VOLUME_EXCEEDS_ALLOCATION` (HTTP 422).

A new movement is `NOMINATED`, its `billing_status` is `UNBILLED`, and it receives a `sequence_no` — a per-terminal monotonic intake sequence starting at 1, used only as a deterministic tie-break after `created_at` in waitlist ranking. Its `resource_id` remains null until scheduling assigns it.

Scheduling a nominated movement takes a `resource_id` and, when accepted, moves the movement to `SCHEDULED`. The schedule path checks, in the order established by §2.9: the lease is `ACTIVE` (`ERR_LEASE_NOT_ACTIVE`); the tank is `AVAILABLE` (`ERR_TANK_NOT_AVAILABLE`); the named resource is `ACTIVE` (`ERR_RESOURCE_UNAVAILABLE`) and its type matches the movement's mode per the fixed mapping (`ERR_RESOURCE_TYPE_MISMATCH`); the requested window does not conflict under the occupation semantics of §2.7 (`ERR_WINDOW_CONFLICT`); an `ACTIVE` allocation covers the lease-and-tank pair (`ERR_NO_ACTIVE_ALLOCATION`); and `declared_volume_bbl` does not exceed that allocation's `allocated_bbl` (`ERR_VOLUME_EXCEEDS_ALLOCATION`). On success the movement's `resource_id` is set and its `demurrage_estimated_amount` is computed as the forward-looking estimate of §3.9.

Cancelling a movement is possible from `NOMINATED` or `SCHEDULED`. Cancelling a `NOMINATED` movement is a simple terminal transition. Cancelling a `SCHEDULED` movement frees its resource window and immediately runs waitlist promotion: among all movements still `NOMINATED` whose mode maps to the freed resource's type and whose window would not conflict with the remaining occupation on that resource under the same occupation rule used at schedule time, the system ranks candidates by `created_at` ascending with `sequence_no` ascending as the tie-break — never by id — and promotes the single top-ranked candidate to `SCHEDULED`, setting its `resource_id` and computing its `demurrage_estimated_amount`. After a promotion, selection repeats until no further candidate fits, with at most one promotion per freed unit of `concurrent_capacity` per pass. Promotion runs even if the freed resource has since been taken `OUT_OF_SERVICE`. Cancelling a movement does not clear its `resource_id`. An empty candidate set is a no-op, not an error.

### 3.6. Driving the Movement: Arrival, Start, Suspension, Completion

Once scheduled, the physical dance begins. The arrival of the vessel, rail cut, or truck is recorded by an arrive action, moving the movement from `SCHEDULED` to `ARRIVED` and stamping `actual_arrival_at` with the logical clock.

Starting the pumping operation — moving from `ARRIVED` to `IN_PROGRESS` — is the most heavily gated transition in the system, and its checks run in a defined order. First, an `OPENING` gauge ticket must already exist for the movement; its absence is rejected with `ERR_GAUGE_MISSING` (HTTP 409). Second, if the tank's `vapor_control_class` is `VRU_REQUIRED`, an `APPROVED` permit of `permit_type` `VAPOR_CONTROL` must exist for the tank; if none exists — including the case where every such permit has lazily become `EXPIRED`, an expired permit counting as absent — the start is rejected with `ERR_VAPOR_PERMIT_REQUIRED`, and if an `APPROVED` permit exists but its `valid_from` to `valid_until` window does not cover the current logical time, the start is rejected with `ERR_PERMIT_WINDOW_INSUFFICIENT` (HTTP 409). Third, the logical clock must not have passed the end of the occupation window by more than the late grace allowance of 30 minutes: a start attempted later than `window_end` plus 30 minutes is rejected with `ERR_WINDOW_LAPSED` (HTTP 409). A successful start stamps `actual_start_at` with the logical clock.

If the vapor-control permit covering an in-progress movement's tank is revoked, the movement cascades from `IN_PROGRESS` to `SUSPENDED` automatically, as described in §2.8. A resume action moves it back to `IN_PROGRESS`, re-checking the same vapor-permit conditions as at start: no approved vapor permit yields `ERR_VAPOR_PERMIT_REQUIRED`, and a permit whose window does not cover the current time yields `ERR_PERMIT_WINDOW_INSUFFICIENT`.

Completion moves the movement from `IN_PROGRESS` to `COMPLETED` and requires that a `CLOSING` gauge ticket exist, again enforced as `ERR_GAUGE_MISSING`. Completion stamps `actual_complete_at` with the logical clock, computes `demurrage_actual_amount` per the actual-settlement variant of §3.9, auto-creates the movement's `CustodyTransfer` in `PROVISIONAL` status with its `provisional_volume_bbl` computed per the provisional variant of §3.7, and recomputes the tank's `provisional_inventory_bbl`. `COMPLETED` is terminal; the other terminal state, `CANCELLED`, is reachable only from `NOMINATED` or `SCHEDULED` as described in §3.5. The movement's `billing_status` runs on a parallel dimension independent of `status`: it begins `UNBILLED`, becomes `ACCRUED` when a statement close sweeps the movement into a closed period, and becomes `INVOICED` at statement invoice time.

### 3.7. Gauging, Sampling, and Custody Certification

Measurement evidence is append-only. A `Gauger` records a gauge ticket against a movement — the ticket is path-scoped, and the server pins its `movement_id` from the movement named in the path — by supplying `ticket_type` (`OPENING` or `CLOSING`), the `observed_volume_bbl` (zero or more), the `observed_temp_f` product temperature in Fahrenheit, and the `observed_at` observation timestamp; the server pins `recorded_by_user_id` from the caller's `X-User-ID`. Gauge sequencing is strict: at most one `OPENING` and at most one `CLOSING` ticket exist per movement; a `CLOSING` requires an existing `OPENING`; an `OPENING` ticket may only be recorded while the movement is `ARRIVED` or `IN_PROGRESS`; and a `CLOSING` ticket only while the movement is `IN_PROGRESS`. Any violation — a duplicate, a closing-before-opening, or a ticket outside its permitted status — is rejected with `ERR_GAUGE_SEQUENCE_INVALID` (HTTP 409).

In parallel, a `QualityInspector` collects a `QualitySample` against a movement that is `IN_PROGRESS` or `COMPLETED` — a collection attempt against a movement in any other status is rejected with `ERR_INVALID_STATE` — naming the `sample_type` — `FIRST_FOOT`, `INLINE`, or `ALL_LEVELS`. The server pins `collected_by_user_id` from the caller's header; the sample's `lab_result` starts `PENDING`, its `retain_status` starts `RETAINED`, and its `retain_until` is computed as the sample's `created_at` plus 30 days. Later, a quality inspector records the laboratory outcome via a record-result action carrying `lab_result` (`PASSED` or `FAILED`) and the lab-measured `specific_gravity` (greater than zero); the server pins `result_recorded_by_user_id` from the recording caller, and per §2.11 the recorder must differ from the collector or the action is rejected with `ERR_SEGREGATION_OF_DUTIES`. Recording a result is an attribute update on the sample, not a status-machine transition.

Custody transfer is where measurement becomes money. Every completed movement has exactly one `CustodyTransfer`, auto-created `PROVISIONAL` at completion. The provisional volume is computed from the gauge pair: each ticket's observed volume is corrected to the reference temperature of 60 degrees Fahrenheit by multiplying the observed volume by one minus the temperature correction coefficient 0.0006 times the difference between the observed temperature and the 60-degree reference; the corrected closing volume minus the corrected opening volume yields the raw transfer; a `RECEIPT` movement uses the raw value directly while a `DISCHARGE` uses its negation; and the transferred volume is the absolute value of that result. The provisional variant rounds this transferred volume half-up to whole barrels and stores it as `provisional_volume_bbl` — temperature-corrected only, with standard gravity assumed.

Certification is performed by a `TerminalManager` and is gated, in the order fixed by §2.9: a `QualitySample` for the movement must exist with `lab_result` equal to `PASSED` — a missing sample, a `PENDING` result, or a `FAILED` result all reject as `ERR_QUALITY_NOT_PASSED` (HTTP 409) — and the certifier's `X-User-ID` must differ from the `recorded_by_user_id` on the movement's gauge tickets (`ERR_SEGREGATION_OF_DUTIES`). At least one passed sample is required at certify time, and other samples in any state may coexist; when several samples have passed, the earliest-collected passed sample supplies the `specific_gravity` for the certified-volume computation. On certification the certified variant volume is computed: the same temperature-corrected transferred volume as above, now additionally multiplied by the ratio of the passed sample's `specific_gravity` to the standard gravity for the movement's `product_grade`, where the standard gravities are 0.74 for `GASOLINE`, 0.85 for `DIESEL`, 0.80 for `JET`, 0.79 for `ETHANOL`, and 0.87 for `CRUDE`; the result is rounded half-up to whole barrels and stored as `certified_volume_bbl`. The certified figure diverges from the provisional whenever the lab's specific gravity differs from the grade standard. The certifier's identity is pinned as `certified_by_user_id`.

Certification then computes the loss fields. `shrinkage_bbl` is the movement's `declared_volume_bbl` minus `certified_volume_bbl`, signed — a negative value means a gain — and is recorded truncated toward zero to a whole number of barrels. `allowed_loss_bbl` is the declared volume multiplied by the lease's `loss_allowance_pct`, rounded half-up to whole barrels. `excess_loss_bbl` is the greater of zero and the raw shrinkage (before its own truncation) minus the allowance, itself recorded truncated toward zero to whole barrels; a gain therefore yields zero excess loss, and unused allowance is never banked across transfers. `excess_loss_charge` is the excess loss barrels — before the whole-barrel truncation — multiplied by the lease's `excess_loss_rate_per_bbl`, rounded half-up to 2 decimal places, with the rounding applied per custody transfer at certify time.

The certification cascades outward. The tank's `current_inventory_bbl` and `provisional_inventory_bbl` are recomputed per §2.6, and the tank's `AVAILABLE` to `RESTRICTED` posture is re-evaluated against its bounds. If an `OPEN` monthly statement exists for the lease covering the period containing the movement's `actual_complete_at`, that statement is recomputed per §3.8. And if the recomputed statement's `total_excess_loss_bbl` exceeds the terminal's loss-control cap of 100 barrels, the lease automatically transitions from `ACTIVE` to `SUSPENDED` with `suspension_reason` set to `LOSS_CONTROL`.

A certified transfer may be disputed by the owning customer: a `CustomerRep` whose `X-User-ID` equals the lease's `customer_id` may move the transfer from `CERTIFIED` to `DISPUTED`; any other caller is rejected with `ERR_FORBIDDEN_OWNERSHIP`. A disputed transfer still contributes its `certified_volume_bbl` to tank inventory — the physical barrels do not un-move because paperwork is contested. A `TerminalManager` may resolve the dispute, returning the transfer from `DISPUTED` to `CERTIFIED` and recomputing any open statement under the same rules as at certification. Either a `CERTIFIED` or a `DISPUTED` transfer may be voided by a manager; voiding moves the transfer to the terminal `VOID` state, excludes it from the inventory projection and from all statement input sets, recomputes the tank's `current_inventory_bbl` as the compensating invariant requires (certify-then-void leaves inventory unchanged), and recomputes any open statement. Voiding does not, however, auto-reactivate a lease suspended for loss control, even if the void brings `total_excess_loss_bbl` back to the cap or below.

Retain release closes the sample loop. A `QualityInspector` may release a retained sample only when the movement's custody transfer is `CERTIFIED` — otherwise `ERR_CUSTODY_NOT_CERTIFIED` (HTTP 409) — and only once the logical clock has reached the sample's `retain_until` instant; an earlier attempt is rejected with `ERR_RETAIN_PERIOD_ACTIVE` (HTTP 409). Release moves `retain_status` from `RETAINED` to `RELEASED`.

### 3.8. Monthly Statements and Loss Control

Billing operates on calendar months. A `BillingClerk` creates a `MonthlyStatement` for a lease by supplying a `period` in `YYYY-MM` format; the period is unique per lease, and a duplicate is rejected with `ERR_STATEMENT_EXISTS` (HTTP 409). The server derives `period_start` as the first day of the named month at 00:00:00 UTC inclusive, and `period_end_exclusive` as the first day of the following month at 00:00:00 UTC exclusive. The lease must not be `EXPIRED` or `TERMINATED` (`ERR_LEASE_NOT_ACTIVE`). A new statement is `OPEN` with all charge figures at 0.

A statement's input set is pinned precisely. Throughput and loss figures draw from custody transfers in `CERTIFIED` or `DISPUTED` status whose movement's `actual_complete_at` falls within the period; `PROVISIONAL` and `VOID` transfers are excluded. Demurrage and dwell draw from movements in `COMPLETED` status completing within the period, with `VESSEL` and `RAIL` modes feeding `total_demurrage_amount` and `TRUCK` feeding `total_dwell_amount`. `total_throughput_bbl` is the sum of `certified_volume_bbl` over the custody input set. `total_excess_loss_bbl` sums the per-line `excess_loss_bbl` values. `excess_loss_amount` sums the per-line `excess_loss_charge` values — each already rounded at certify time per the round-per-line-then-sum discipline of §2.10 — and the two demurrage buckets likewise sum pre-rounded `demurrage_actual_amount` line values.

The throughput fee is tiered marginally against `total_throughput_bbl` in whole barrels. The first tier covers throughput from zero up to but not including 50,000 barrels at the lease's full `throughput_fee_per_bbl` rate. The second tier covers throughput from 50,000 up to but not including 200,000 barrels at 0.90 times the base rate. The third tier covers throughput at or beyond 200,000 barrels at 0.75 times the base rate. Because the tiers are half-open, a month landing on exactly 50,000 barrels prices every barrel in the first tier. `throughput_fee_amount` is the sum of the marginal tier amounts, rounded half-up to 2 decimal places exactly once at the end — the evaluation order is pinned as aggregation first, tier split second, single final rounding last.

The minimum commitment check runs against the same throughput figure. `shortfall_bbl` is the greater of zero and the lease's `min_monthly_throughput_bbl` minus `total_throughput_bbl`, recorded truncated toward zero to whole barrels; throughput at or above the commitment yields no shortfall. `shortfall_fee_amount` is the shortfall — before the whole-barrel truncation — multiplied by the lease's `shortfall_fee_per_bbl`, rounded half-up to 2 decimal places. Finally, `statement_total_amount` is the exact sum of `throughput_fee_amount`, `shortfall_fee_amount`, `excess_loss_amount`, `total_demurrage_amount`, and `total_dwell_amount`.

While a statement is `OPEN`, custody certifications, dispute resolutions, and voids touching its input set recompute it in place, as described in §3.7. Every recompute — including the full recompute performed at close — reads the lease's `throughput_fee_per_bbl`, `shortfall_fee_per_bbl`, and `min_monthly_throughput_bbl` at their current values; only the per-line excess-loss and demurrage amounts retain the values fixed when those lines were first computed. A `BillingClerk` closes the statement once the logical clock has reached `period_end_exclusive`; an early close is rejected with `ERR_STATEMENT_PERIOD_NOT_ENDED` (HTTP 409). Closing performs a full deterministic recompute over the pinned input set, transitions the statement from `OPEN` to `CLOSED`, and sweeps every `COMPLETED` movement of the lease completing in the period from `UNBILLED` to `ACCRUED` in `billing_status`. Invoicing a `CLOSED` statement moves it to the terminal `INVOICED` status and advances every movement of the lease in the period whose `billing_status` is `ACCRUED` to `INVOICED`.

The loss-control cap is the terminal's automatic brake on chronic shrinkage. Whenever an `OPEN` statement recompute — triggered by certify, resolve, or void — leaves `total_excess_loss_bbl` greater than 100 barrels, the lease auto-suspends with `suspension_reason` = `LOSS_CONTROL`, as detailed in §3.7. The brake is one-directional: nothing automatically reactivates the lease when the figure later subsides.

### 3.9. Demurrage and Dwell: Estimated and Actual

Demurrage pricing is mode-dependent, with each mode granted a free-hours allowance and an hourly rate beyond it. `VESSEL` movements receive 24 free hours and then accrue at 1,200.00 per hour. `RAIL` movements receive 48 free hours and accrue at 85.00 per hour. `TRUCK` movements receive 4 free hours and accrue at 60.00 per hour; truck charges are reported as dwell rather than demurrage on the monthly statement, but the arithmetic is identical.

The two variants answer different questions. The scheduled estimate, computed when a movement is scheduled and stored as `demurrage_estimated_amount`, is forward-looking: it takes the exact rational duration in hours from `window_start` to `window_end`, subtracts the mode's free hours, clamps the result below at zero, multiplies by the mode's hourly rate, and rounds half-up to 2 decimal places. The actual settlement, computed at completion and stored as `demurrage_actual_amount`, is chronological: it measures the elapsed time from `actual_arrival_at` to `actual_complete_at`, rounds that elapsed time up to the next whole hour (the ceiling of the elapsed seconds divided by 3600), subtracts the free hours, clamps below at zero — where elapsed time exactly equal to the free hours yields a zero charge — multiplies by the hourly rate, and rounds half-up to 2 decimal places. Because one variant reads the requested window and the other reads actual timestamps, the same movement can legitimately carry two different amounts.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, approvals, recording actions — return `200 OK`. The complete endpoint surface is summarized below; request payloads and side effects are defined by the workflows of §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Create a customer | TerminalManager |
| GET | `/customers` | List customers | Any |
| GET | `/customers/{customerId}` | Get a customer | Any |
| POST | `/tanks` | Create a tank; working capacity computed | TerminalOperator |
| GET | `/tanks` | List tanks | Any |
| GET | `/tanks/{tankId}` | Get a tank | Any |
| POST | `/tanks/{tankId}/enter-maintenance` | AVAILABLE to MAINTENANCE | TerminalOperator |
| POST | `/tanks/{tankId}/return-to-service` | MAINTENANCE to AVAILABLE | TerminalOperator |
| POST | `/terminal-resources` | Create a dock, rail rack, or truck bay | TerminalOperator |
| GET | `/terminal-resources` | List terminal resources | Any |
| GET | `/terminal-resources/{resourceId}` | Get a terminal resource | Any |
| POST | `/terminal-resources/{resourceId}/out-of-service` | ACTIVE to OUT_OF_SERVICE | TerminalOperator |
| POST | `/terminal-resources/{resourceId}/return-to-service` | OUT_OF_SERVICE to ACTIVE | TerminalOperator |
| POST | `/lease-agreements` | Create a lease in DRAFT for own customer | CustomerRep |
| GET | `/lease-agreements` | List leases | Any |
| GET | `/lease-agreements/{leaseId}` | Get a lease | Any |
| POST | `/lease-agreements/{leaseId}/activate` | DRAFT to ACTIVE; requires an ACTIVE allocation | TerminalManager |
| POST | `/lease-agreements/{leaseId}/suspend` | ACTIVE to SUSPENDED with reason MANUAL | TerminalManager |
| POST | `/lease-agreements/{leaseId}/reactivate` | SUSPENDED to ACTIVE; clears suspension reason | TerminalManager |
| POST | `/lease-agreements/{leaseId}/terminate` | ACTIVE to TERMINATED; releases allocations | TerminalManager |
| POST | `/lease-agreements/{id}/amendments` | Propose a lease amendment with OCC version pin | CustomerRep |
| GET | `/lease-agreements/{id}/amendments` | List amendments of a lease | Any |
| POST | `/lease-amendments/{amendmentId}/approve` | Approve amendment; rejects stale base version | TerminalManager |
| POST | `/lease-amendments/{amendmentId}/reject` | Reject amendment | TerminalManager |
| POST | `/lease-agreements/{id}/allocations` | Create an allocation in RESERVED | TerminalOperator |
| GET | `/lease-agreements/{id}/allocations` | List allocations of a lease | Any |
| GET | `/tanks/{id}/allocations` | List allocations of a tank | Any |
| GET | `/tank-allocations/{allocationId}` | Get an allocation | Any |
| POST | `/tank-allocations/{allocationId}/activate` | RESERVED to ACTIVE; rechecks capacity sweep | TerminalOperator |
| POST | `/tank-allocations/{allocationId}/release` | ACTIVE to RELEASED | TerminalOperator |
| POST | `/permits` | Request a permit | TerminalOperator |
| GET | `/permits` | List permits | Any |
| GET | `/permits/{permitId}` | Get a permit | Any |
| POST | `/permits/{permitId}/approve` | REQUESTED to APPROVED | TerminalManager |
| POST | `/permits/{permitId}/revoke` | APPROVED to REVOKED; suspends vapor-controlled movements | TerminalManager |
| POST | `/movements` | Nominate a receipt or discharge movement | Scheduler |
| GET | `/movements` | List movements | Any |
| GET | `/movements/{movementId}` | Get a movement | Any |
| POST | `/movements/{movementId}/schedule` | NOMINATED to SCHEDULED with resource assignment | Scheduler |
| POST | `/movements/{movementId}/arrive` | SCHEDULED to ARRIVED | Scheduler |
| POST | `/movements/{movementId}/start` | ARRIVED to IN_PROGRESS | Scheduler |
| POST | `/movements/{movementId}/complete` | IN_PROGRESS to COMPLETED; creates provisional custody | Scheduler |
| POST | `/movements/{movementId}/cancel` | NOMINATED or SCHEDULED to CANCELLED; runs waitlist promotion | Scheduler |
| POST | `/movements/{movementId}/resume` | SUSPENDED to IN_PROGRESS; re-checks vapor permit | Scheduler |
| POST | `/movements/{id}/gauge-tickets` | Record an OPENING or CLOSING gauge ticket | Gauger |
| GET | `/movements/{id}/gauge-tickets` | List gauge tickets of a movement | Any |
| POST | `/movements/{id}/samples` | Collect a quality sample | QualityInspector |
| GET | `/movements/{id}/samples` | List samples of a movement | Any |
| GET | `/quality-samples/{sampleId}` | Get a sample | Any |
| POST | `/quality-samples/{sampleId}/record-result` | Record the laboratory result | QualityInspector |
| POST | `/quality-samples/{sampleId}/release-retain` | Release a retained sample | QualityInspector |
| GET | `/movements/{id}/custody-transfers` | List custody transfers of a movement | Any |
| GET | `/custody-transfers/{ctId}` | Get a custody transfer | Any |
| POST | `/custody-transfers/{ctId}/certify` | PROVISIONAL to CERTIFIED; cascades to inventory and statement | TerminalManager |
| POST | `/custody-transfers/{ctId}/dispute` | CERTIFIED to DISPUTED by owning customer | CustomerRep |
| POST | `/custody-transfers/{ctId}/resolve` | DISPUTED to CERTIFIED | TerminalManager |
| POST | `/custody-transfers/{ctId}/void` | CERTIFIED or DISPUTED to VOID; compensates inventory and statement | TerminalManager |
| POST | `/lease-agreements/{id}/statements` | Create an OPEN statement for a period | BillingClerk |
| GET | `/lease-agreements/{id}/statements` | List statements of a lease | Any |
| GET | `/monthly-statements/{statementId}` | Get a statement | Any |
| POST | `/monthly-statements/{statementId}/close` | OPEN to CLOSED; full recompute; movements ACCRUED | BillingClerk |
| POST | `/monthly-statements/{statementId}/invoice` | CLOSED to INVOICED; movements INVOICED | BillingClerk |
| POST | `/_clock/set_current_utc` | Advance the logical clock | TerminalManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue enumerates only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_TANK_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_FOUND` | 404 |
| `ERR_AMENDMENT_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_MOVEMENT_NOT_FOUND` | 404 |
| `ERR_SAMPLE_NOT_FOUND` | 404 |
| `ERR_CUSTODY_TRANSFER_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LEASE_NOT_ACTIVE` | 409 |
| `ERR_TANK_NOT_AVAILABLE` | 409 |
| `ERR_RESOURCE_UNAVAILABLE` | 409 |
| `ERR_GAUGE_MISSING` | 409 |
| `ERR_GAUGE_SEQUENCE_INVALID` | 409 |
| `ERR_CUSTODY_NOT_CERTIFIED` | 409 |
| `ERR_AMENDMENT_STALE_BASE` | 409 |
| `ERR_VAPOR_PERMIT_REQUIRED` | 409 |
| `ERR_PERMIT_WINDOW_INSUFFICIENT` | 409 |
| `ERR_QUALITY_NOT_PASSED` | 409 |
| `ERR_RETAIN_PERIOD_ACTIVE` | 409 |
| `ERR_PRODUCT_MISMATCH` | 422 |
| `ERR_WINDOW_INVALID` | 422 |
| `ERR_ALLOCATION_PERIOD_INVALID` | 422 |
| `ERR_RESOURCE_TYPE_MISMATCH` | 422 |
| `ERR_STATEMENT_EXISTS` | 409 |
| `ERR_WINDOW_CONFLICT` | 409 |
| `ERR_WINDOW_LAPSED` | 409 |
| `ERR_STATEMENT_PERIOD_NOT_ENDED` | 409 |
| `ERR_ALLOCATION_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_ACTIVE_ALLOCATION` | 409 |
| `ERR_VOLUME_EXCEEDS_ALLOCATION` | 422 |
| `ERR_STALE_VERSION` | 412 |
