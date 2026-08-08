# Demand-Response VPP API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a Demand-Response and Virtual-Power-Plant (VPP) enrollment platform. A sponsoring utility runs seasonal demand-response programs; independent VPP aggregators register customer-owned flexible assets — home batteries, smart thermostats, and EV chargers — and pledge a slice of their curtailment capacity to those programs. When the grid is stressed, a utility operator dispatches an event: participating assets are notified, curtail their load during a defined window, and are then measured against a computed baseline. The platform turns those measured reductions into money, running the full ledger from per-asset performance measurement through incentive and penalty calculation, settlement approval, and aggregator payment.

The service is deliberately a reconciliation engine first and a pricing engine second. Every kilowatt of committed capacity, every delivered kilowatt-hour, and every cent paid must remain reconcilable across four aggregate boundaries — programs, aggregators, enrollments, and settlements — even as enrollments cycle in and out of participation and settlements are disputed and revised. Two families of algorithms coexist: a baseline-and-performance measurement family (Ten-of-Ten versus weather-regression) and a settlement family (pay-for-performance versus capacity payment), each program pinning its own variant. Because real money flows, the system enforces optimistic concurrency on rate configuration and a strict segregation of duties so that no single operator can both call an event and approve its payout.

All timestamps in this system are evaluated against a server-controlled logical clock rather than wall-clock time, so that notification-lead, event-window, and override-window rules can be tested deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly four roles, spelled precisely as follows:

- **`ProgramOperator`** — the utility-side operator. This role creates and manages programs and their rate configuration, onboards aggregators and customers, schedules and drives dispatch events, and runs settlements. Its `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a transition writes it — specifically as `dispatched_by_user_id` on a `DispatchEvent` when an operator notifies an event, and as `approved_by_user_id` on a `Settlement` when an operator approves it — but it never compares that identifier to any entity's `id` for ownership purposes.
- **`Aggregator`** — a VPP aggregator. When `X-User-Role` is `Aggregator`, `X-User-ID` is the `id` of the acting `Aggregator` entity; ownership checks on any resource that references an aggregator compare the resource's aggregator foreign key to `X-User-ID`. An aggregator registers devices, submits meter readings, creates and manages enrollments, acknowledges dispatches and drives curtailment, and may dispute settlements — but only for devices whose `aggregator_id` equals its own `X-User-ID`.
- **`Customer`** — a premise owner. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks compare a device's `customer_id` (reached through the enrollment and dispatch chain) to `X-User-ID`. A customer may opt an enrollment out of the season and may override individual dispatches on its own devices.
- **`Auditor`** — a read-only compliance observer. When `X-User-Role` is `Auditor`, `X-User-ID` is an opaque identifier not tied to any persisted entity and is never compared to any entity's `id`. An auditor may perform any GET read but no write operation.

All four roles may perform every GET read in the system. Write operations are restricted per the endpoint table in §4; an ownership failure by an entity-backed actor (an `Aggregator` or `Customer` acting on a resource it does not own) is reported as `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403), distinct from the role-level `ERR_UNAUTHORIZED`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it reflects the host wall-clock instant at which the request is served and is the one timestamp in the system not driven by the logical clock of §2.10 (unlike `created_at`/`updated_at`, which are minted from `current_utc`).
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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. List results are ordered by `created_at` ascending (oldest first); when several records share the same `created_at` — common because `created_at` is minted from the logical clock, which does not advance on its own — ties are broken by creation order (the order in which the records were inserted). The `meta` block of a list response carries `limit`, `offset`, `total_count` (the count of all matching records before pagination), and `has_more` (true when records remain beyond the returned page). Any endpoint-specific filter parameters (for example `status`, `device_id`, or `program_id`) are applied before pagination, and `total_count` reflects the filtered set.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources — `Program`, `Aggregator`, `Customer`, `Device`, `Enrollment`, `DispatchEvent`, `Dispatch`, `Settlement`, and `Payment` — additionally carry an `updated_at` timestamp (same format as `created_at`) and an integer `version`. The `version` starts at 1 when the resource is created and increments by exactly 1 on every mutation that the workflow narratives below describe as bumping the version; `updated_at` is refreshed to the current logical-clock instant on each such mutation. The sole exception is `MeterReading`: a meter reading is an immutable, append-only record that carries only `id` and `created_at` — it has neither an `updated_at` nor a `version`, because once written it is never modified.

### 2.5. Numeric Precision and Rounding

Monetary amounts are stored as whole integer cents; no sub-cent values are ever persisted. Kilowatt values that are pledged or committed (for example `committed_kw`, `total_committed_kw`, `enrolled_committed_kw`) are held exactly with no rounding. Computed measurement quantities are rounded half-up: a per-device `baseline_kw` is rounded to three decimal places, `delivered_kwh` and `total_delivered_kwh` are rounded to three decimal places, and a dispatch's `performance_ratio` is rounded to four decimal places. Every per-dispatch payout and every settlement total is rounded half-up to whole cents. Wherever a rounding step and a summation step both appear in a calculation, the order in which they are applied is stated explicitly in the relevant workflow narrative, because it changes the result.

### 2.6. Optimistic Concurrency on Program Configuration

Rate configuration on a `Program` is guarded by optimistic concurrency control. A request that updates a program's rate configuration must carry `expected_program_version`, a required field holding the `version` of the `Program` that the client last observed. If `expected_program_version` does not equal the program's current `version`, the update is rejected with `ERR_STALE_VERSION` (HTTP 412): an earlier update has already advanced the program's `version` and legitimately superseded the configuration the client was working from, so the client's view is stale and its write must not silently overwrite the newer configuration. Only the program-configuration update endpoint takes a version field; no other endpoint in the system accepts or requires `expected_program_version`.

### 2.7. Nested Resource Retrieval and Path Validation

Several resources are addressed through nested paths (for example a device's meter readings, an event's dispatches, an event's settlement, or a settlement's payments). Path parameters are validated left to right: the parent resource is resolved first, and if it does not exist the request fails with that parent's not-found error before any child lookup or body validation runs. The not-found errors are resource-specific — `ERR_PROGRAM_NOT_FOUND`, `ERR_AGGREGATOR_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_DISPATCH_EVENT_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_METER_READING_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`, and `ERR_PAYMENT_NOT_FOUND` — each returning HTTP 404. The same resource-specific not-found errors apply to foreign-key targets supplied in a request body (see §2.8).

### 2.8. Request Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication — `X-User-ID` and `X-User-Role` present and the role recognized, else `ERR_UNAUTHENTICATED`; (2) authorization — the acting role is permitted to call this endpoint, else `ERR_UNAUTHORIZED`; (3) path-resource existence — every id in the URL path resolves left to right, else the corresponding resource-specific not-found error; (4) foreign-key existence — every FK target named in the request body (`customer_id`, `program_id`, `device_id`, `dispatch_event_id`) resolves, else the corresponding not-found error; (5) ownership — an entity-backed actor owns the target resource, else `ERR_FORBIDDEN_OWNERSHIP`; (6) required-and-typed body fields present, else `ERR_VALIDATION` (HTTP 422); (7) enum fields hold a declared value, else `ERR_INVALID_ENUM` (HTTP 422); (8) the target resource is in a state from which the requested transition is allowed, else `ERR_INVALID_STATE` (HTTP 409). Checks beyond these eight are business rules specific to individual workflows and are described where those workflows live; when such a rule shares an endpoint with the generic checks above, it is evaluated after the eight generic checks unless a workflow narrative says otherwise.

### 2.9. Ledger Conservation Invariants

Two running ledgers must stay reconciled at all times. First, committed capacity is conserved: `Program.total_committed_kw` always equals the sum of `committed_kw` over that program's enrollments currently in `ACTIVE` status, and `Aggregator.enrolled_committed_kw` always equals the sum of `committed_kw` over the `ACTIVE` enrollments whose device belongs to that aggregator. Because an enrollment can cycle between participating and opted-out repeatedly, these sums are maintained incrementally by the enrollment transitions (adding on activate and re-enroll, subtracting on opt-out and terminate) and the pledged `committed_kw` is neither lost nor double-counted across a full cycle. Second, paid balance is conserved: `Aggregator.paid_balance_cents` always equals the sum of `amount_cents` over that aggregator's payments whose status is `ISSUED` or `CLEARED`; payments in `REVERSED` status are excluded. These recomputations are triggered whenever payments are issued, cleared, or reversed, as the settlement narratives describe.

### 2.10. Logical Clock and Temporal Rules

The server boots with an internal logical clock, `current_utc`, defaulting to `2026-05-01T00:00:00Z`. Every deadline, window, and lead-time rule in this system reads `current_utc` and never the host wall-clock. An administrative test-driving capability sets the clock to a supplied instant carried as `to_iso8601` in the request body; this capability is reserved to a `ProgramOperator`. All temporal comparisons — notification lead time, event start and end, and the override window — are evaluated against `current_utc` at the moment the request is processed.

## 3. Business Logic & Workflows

### 3.1. Programs and Their Rate Configuration

A demand-response program is the top-level container for a season of events. A `ProgramOperator` creates one by supplying its `name`, the sponsoring `utility_name`, and the three rate constants that drive every downstream payout: `incentive_rate_cents_per_kwh` (the payment in whole cents per delivered kWh), `penalty_rate_cents_per_kwh` (the underperformance penalty in whole cents per shortfall kWh), and `capacity_incentive_cents_per_kw` (the capacity-payment rate in whole cents per committed kW, used only under the capacity settlement method). All three rate fields must be non-negative integers. The creator also supplies `season_start_date` and `season_end_date` as ISO 8601 UTC instants. A newly created program is born in `DRAFT` status and its `total_committed_kw` starts at 0.

Several configuration fields are optional at creation and take documented defaults when omitted. `baseline_method` selects the measurement algorithm applied to every dispatch in the program and is one of `TEN_OF_TEN` or `WEATHER_REGRESSION`, defaulting to `TEN_OF_TEN`. `settlement_method` selects the payout algorithm applied to every settlement and is one of `PAY_FOR_PERFORMANCE` or `CAPACITY_PAYMENT`, defaulting to `PAY_FOR_PERFORMANCE`. `performance_floor_pct` is the minimum performance ratio at or above which no penalty applies; it defaults to 0.75 and must be greater than 0 and at most 1. `notification_lead_minutes` is the minimum number of minutes that must separate the notify time from an event's window start; it defaults to 60 and must be at least 0. `max_events_per_season` caps the number of non-cancelled dispatch events the program may hold; it defaults to 3 and must be at least 0. Any enum value outside its declared set yields `ERR_INVALID_ENUM`; a missing required field or a wrong-typed value yields `ERR_VALIDATION`.

**Activation.** A program advances from `DRAFT` to `ACTIVE` when an operator activates it. Activation is refused with `ERR_INVALID_STATE` unless the program is currently `DRAFT`. Two preconditions guard the transition: `incentive_rate_cents_per_kwh`, `penalty_rate_cents_per_kwh`, and `capacity_incentive_cents_per_kw` must all be set, and `season_start_date` must be strictly earlier than `season_end_date`. On success the status becomes `ACTIVE` and the program's `version` increments by 1. Only an `ACTIVE` program can host enrollments and events.

**Closing.** An operator closes an `ACTIVE` program, moving it to the terminal `CLOSED` status and incrementing `version` by 1. Closing is refused with `ERR_INVALID_STATE` unless the program is `ACTIVE`, and it is additionally blocked while any dispatch event of the program remains open — that is, while any of the program's events is in `SCHEDULED`, `NOTIFIED`, or `ACTIVE` status.

**Rate updates under concurrency control.** After creation, an operator may revise a program's rate configuration. The update accepts any subset of `incentive_rate_cents_per_kwh`, `penalty_rate_cents_per_kwh`, `capacity_incentive_cents_per_kw`, `performance_floor_pct`, `notification_lead_minutes`, and `max_events_per_season`, applying only the supplied fields, and it always increments the program's `version` by 1. As described in §2.6, this update is the one optimistic-concurrency point in the system: it requires `expected_program_version` to match the program's current `version`, rejecting a mismatch with `ERR_STALE_VERSION`. Anyone may fetch a single program or list programs; the list may be filtered by `status`.

### 3.2. Aggregators, Customers, and Devices

The utility onboards the counterparties. A `ProgramOperator` onboards an aggregator by supplying its `name` and `contact_email`; the aggregator is created in `ACTIVE` status (its other allowed status is `SUSPENDED`) with its computed ledgers — `enrolled_committed_kw`, `season_delivered_kwh`, and `paid_balance_cents` — all starting at 0. Fetching an aggregator returns those computed balances alongside its identity. An operator likewise onboards a customer by supplying `name`, `email`, `service_address`, and `utility_account_id`; a customer record has no lifecycle status beyond its identity fields.

**Device registration.** An `Aggregator` registers a flexible asset by supplying the owning `customer_id`, the `device_type` (one of `BATTERY`, `THERMOSTAT`, or `EV_CHARGER`), the rated `nameplate_kw`, and optionally `capacity_kwh`. The `customer_id` must reference an existing customer, else `ERR_CUSTOMER_NOT_FOUND`. The `nameplate_kw` must be strictly greater than 0. `capacity_kwh` is the energy capacity in kWh for batteries and EV chargers and may be omitted (null) for thermostats; it is in fact optional for every device type — never required, including for batteries and EV chargers — and, when supplied, is accepted without any sign or range constraint. The device's `aggregator_id` is not supplied in the body — it is set from the acting aggregator's `X-User-ID`, binding the device to its registrar — and the device is created in `ACTIVE` status. Devices may be fetched individually or listed; the device list supports reverse lookup filtering by `customer_id`, by `aggregator_id`, and by `status`.

**Decommissioning.** An aggregator may decommission its own device, moving it from `ACTIVE` to the terminal `DECOMMISSIONED` status and incrementing the device's `version` by 1. The acting aggregator's `X-User-ID` must equal the device's `aggregator_id`, else `ERR_FORBIDDEN_OWNERSHIP`. Decommissioning is blocked while any enrollment of the device is in `ACTIVE` status; attempting it in that condition is refused with `ERR_INVALID_STATE`, as is any attempt to decommission a device that is already `DECOMMISSIONED`.

**Meter readings.** Load measurement flows in as immutable interval readings. An aggregator appends a reading to one of its devices by supplying `interval_start` and `interval_end` (ISO 8601 UTC, the start inclusive and the end exclusive), the measured average `kw_load` in kW over that interval, and the `reading_type` (one of `BASELINE_WINDOW` or `EVENT_WINDOW`). The `kw_load` must be at least 0. A reading may optionally carry a `dispatch_event_id` naming the event whose window it belongs to; baseline-pool readings leave `dispatch_event_id` null, whereas event-pool readings set it to the event they measure. The reading interval must be well-formed — `interval_start` strictly before `interval_end`, else `ERR_VALIDATION`. A new reading must not overlap an existing reading of the same device that shares the same `reading_type`; two intervals overlap unless one ends at or before the other begins, so exact adjacency (one interval's end equal to the next interval's start) is permitted, but any true overlap is rejected with `ERR_READING_INTERVAL_OVERLAP`. A meter reading, once written, is never modified: it carries only `id` and `created_at`, no `updated_at` and no `version`. Readings can be fetched individually, listed for a specific device (filterable by `reading_type`), or listed across the system with reverse-lookup filters `device_id`, `dispatch_event_id`, and `reading_type`.

### 3.3. Enrollment: Pledging and Cycling Capacity

An enrollment binds one device to one program at a pledged curtailment capacity. An `Aggregator` creates an enrollment by supplying the `device_id`, the target `program_id`, and the `committed_kw` it pledges. Both foreign keys must resolve, else `ERR_DEVICE_NOT_FOUND` or `ERR_PROGRAM_NOT_FOUND` respectively. The `committed_kw` must be strictly greater than 0. A new enrollment begins in `PENDING` status with its `season_delivered_kwh` at 0. Enrollments can be fetched individually or listed with reverse-lookup filters `device_id`, `program_id`, and `status`.

**Activation.** An aggregator activates a `PENDING` enrollment, moving it to `ACTIVE`. Four preconditions guard this transition, and when several fail the deterministic outcome follows the priority described below. The acting aggregator's `X-User-ID` must equal the enrolled device's `aggregator_id`, else `ERR_FORBIDDEN_OWNERSHIP`. The target program must be in `ACTIVE` status, else `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409). The device must be in `ACTIVE` status, else `ERR_DEVICE_NOT_ELIGIBLE` (HTTP 409). And no other enrollment for the same `device_id` and `program_id` pair may already be `ACTIVE`, else `ERR_DUPLICATE_ENROLLMENT` (HTTP 409). Among these, the generic state check that the enrollment is itself `PENDING` (else `ERR_INVALID_STATE`) is evaluated first per §2.8; the program-active check, then the device-eligible check, then the duplicate-enrollment check follow in that order. On success the enrollment becomes `ACTIVE`, its own `version` increments by 1, and the pledged `committed_kw` is added to both `Program.total_committed_kw` and the owning `Aggregator.enrolled_committed_kw`.

**Opting out and re-enrolling.** An `ACTIVE` enrollment can leave participation for the season and later rejoin, forming a cycle. Either the `Customer` who owns the device or the `Aggregator` who owns it may opt the enrollment out: for a `Customer` actor the `X-User-ID` must equal the device's `customer_id`, and for an `Aggregator` actor it must equal the device's `aggregator_id`, else `ERR_FORBIDDEN_OWNERSHIP`. Opting out is allowed only from `ACTIVE` status (else `ERR_INVALID_STATE`); it moves the enrollment to `OPTED_OUT`, increments its `version` by 1, and subtracts the pledged `committed_kw` from both `Program.total_committed_kw` and the aggregator's `enrolled_committed_kw`. Re-enrollment is the inverse and is reserved to the `Aggregator`: it moves an `OPTED_OUT` enrollment back to `ACTIVE`, subject to the same aggregator-ownership check, the program being `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`), and the device being `ACTIVE` (else `ERR_DEVICE_NOT_ELIGIBLE`); it re-adds the `committed_kw` to both ledgers and increments `version` by 1. Because opt-out subtracts exactly what activation added and re-enrollment re-adds exactly that amount, the pledged capacity is conserved across any number of opt-out/re-enroll cycles.

**Termination.** An aggregator may permanently terminate one of its `ACTIVE` enrollments (subject to the aggregator-ownership check), moving it to the terminal `TERMINATED` status, subtracting its `committed_kw` from both `Program.total_committed_kw` and the aggregator's `enrolled_committed_kw`, and incrementing `version` by 1. Termination is allowed only from `ACTIVE` status, else `ERR_INVALID_STATE`.

### 3.4. Scheduling and Calling Dispatch Events

A dispatch event is the utility's call to curtail. A `ProgramOperator` schedules one against an existing program by supplying the `program_id`, the `window_start` and `window_end` (ISO 8601 UTC, the start inclusive and the end exclusive), and the aggregate `target_reduction_kw`, which must be strictly greater than 0. The `program_id` must resolve, else `ERR_PROGRAM_NOT_FOUND`. The window must be well-formed with `window_start` strictly before `window_end`, else `ERR_VALIDATION`. At creation the event copies the program's `baseline_method` into its own `baseline_method_snapshot`, freezing the measurement algorithm that will govern this event regardless of later program edits, and the event is born in `SCHEDULED` status with `dispatched_by_user_id` null.

Two business guards apply at scheduling time. First, the program may not exceed its `max_events_per_season`: if the count of the program's non-cancelled dispatch events is already at or above `max_events_per_season`, the new event is refused with `ERR_SEASON_EVENT_CAP_EXCEEDED`. Second, event windows may not crowd each other. Each event's window is padded by a buffer of two hours (120 minutes) on each side, and the new event's padded window must not collide with the window of any non-cancelled event of the same program; concretely, a conflict exists when the new event's `window_start` is earlier than an existing event's `window_end` plus 120 minutes and the new event's `window_end` plus 120 minutes is later than that existing event's `window_start`. A collision is rejected with `ERR_EVENT_WINDOW_CONFLICT`. Events may be fetched individually or listed with reverse-lookup filters `program_id` and `status`.

**Notification and fan-out.** An operator notifies a `SCHEDULED` event to advance it to `NOTIFIED`. Notification must occur early enough: the current logical-clock instant must be at or before `window_start` minus the program's `notification_lead_minutes` — equivalently, the notice must lead the window start by at least the configured lead time — else `ERR_NOTIFY_LEAD_NOT_MET`. Notification also requires that at least one enrollment of the program is currently `ACTIVE`; if the program has zero `ACTIVE` enrollments the call is refused with `ERR_NO_ELIGIBLE_ENROLLMENTS`. On success the event moves to `NOTIFIED`, its `dispatched_by_user_id` is set to the acting operator's `X-User-ID` (this is the identity later barred from approving the settlement), its `version` increments by 1, and the system fans out one child `Dispatch` per `ACTIVE` enrollment of the program. Each new dispatch is created in `PENDING` status, linked to its parent through `dispatch_event_id` and to its enrollment through `enrollment_id`, with `assigned_reduction_kw` snapshotted from that enrollment's `committed_kw` at notify time.

**Starting.** When the window opens, an operator starts a `NOTIFIED` event, moving it to `ACTIVE` and incrementing `version` by 1. Starting requires the current instant to be at or after `window_start`, else `ERR_EVENT_NOT_STARTED`.

**Cancellation.** An operator may cancel an event that is still `SCHEDULED` or `NOTIFIED`, moving it to the terminal `CANCELLED` status and incrementing `version` by 1; there are no further preconditions. Cancellation from `NOTIFIED` additionally withdraws the fanned-out work: every child dispatch still in `PENDING` or `ACKNOWLEDGED` status is moved to `OPTED_OUT` (the event has been withdrawn from under them). Cancelling from `SCHEDULED` has no child dispatches to withdraw. Attempting to cancel an event in any other status is refused with `ERR_INVALID_STATE`.

### 3.5. Dispatch Participation and Customer Override

Each fanned-out dispatch represents one enrollment's obligation for one event, and it walks its own small lifecycle from `PENDING` through acknowledgement and curtailment, or exits early via override. Dispatches may be fetched individually, listed for a specific event (filterable by `status`), or listed across the system with reverse-lookup filters `enrollment_id`, `dispatch_event_id`, and `status`.

**Acknowledgement.** The `Aggregator` that owns the underlying device acknowledges a `PENDING` dispatch, moving it to `ACKNOWLEDGED` and incrementing its `version` by 1. Ownership is checked by resolving the dispatch's enrollment to its device and comparing that device's `aggregator_id` to the acting `X-User-ID`, else `ERR_FORBIDDEN_OWNERSHIP`. Acknowledgement additionally requires the parent event to be in `NOTIFIED` or `ACTIVE` status; if the event is in any other status the call is refused with `ERR_INVALID_STATE`.

**Starting curtailment.** Once the event is live, the owning aggregator starts curtailment on an `ACKNOWLEDGED` dispatch, moving it to `CURTAILING` and incrementing `version` by 1, again subject to the aggregator-ownership check. This step requires the parent event to be in `ACTIVE` status specifically; otherwise the call is refused with `ERR_INVALID_STATE`.

**Customer override.** A `Customer` may pull its own device out of an event at any point before the window closes. Override is available from `PENDING`, `ACKNOWLEDGED`, or `CURTAILING` status and moves the dispatch to the terminal `OVERRIDDEN` status, incrementing `version` by 1. The acting customer's `X-User-ID` must equal the device's `customer_id` (reached through the dispatch's enrollment and device), else `ERR_FORBIDDEN_OWNERSHIP`. Override is permitted only while the override window is still open — the current instant must be strictly before the event's `window_end` — otherwise the call is refused with `ERR_OVERRIDE_WINDOW_CLOSED`. An overridden dispatch is excluded from measurement and settlement: it does not receive computed measurement values and it does not earn a payout.

### 3.6. Completion and Performance Measurement

Completing an event is where measurement happens. A `ProgramOperator` completes an `ACTIVE` event, but only once the window has closed: the current instant must be at or after `window_end`, else `ERR_EVENT_NOT_ENDED`; attempting completion from any status other than `ACTIVE` yields `ERR_INVALID_STATE`. Completion moves the event to `COMPLETED`, increments its `version` by 1, and drives a three-stage measurement cascade.

In the first stage, every child dispatch that is still non-terminal — that is, in `PENDING`, `ACKNOWLEDGED`, or `CURTAILING` — is measured and moved to `COMPLETED`. Dispatches already terminal in `OVERRIDDEN` or `OPTED_OUT` are excluded from measurement and left untouched in their terminal state. For each measured dispatch the system computes, in order, `baseline_kw`, `avg_event_load_kw`, `actual_reduction_kw`, `delivered_kwh`, and `performance_ratio`, as detailed below. In the second stage, because each measured dispatch has reached `COMPLETED`, its `delivered_kwh` is added into the owning enrollment's `season_delivered_kwh`. In the third stage, because those enrollment totals changed, each affected aggregator's `season_delivered_kwh` is recomputed as the sum of `season_delivered_kwh` over that aggregator's enrollments.

**Baseline load.** A dispatch's `baseline_kw` estimates what the device would have drawn absent the event, from its baseline-pool history. The pool is that device's meter readings whose `reading_type` is `BASELINE_WINDOW` and whose `dispatch_event_id` is null, ordered by `interval_start` descending with ties broken by `created_at` ascending; the system takes the most recent five such readings (the baseline lookback). If fewer than three readings are available in that lookback, completion cannot measure the device and the whole request fails with `ERR_BASELINE_DATA_MISSING`. The event's frozen `baseline_method_snapshot` then selects the algorithm. Under `TEN_OF_TEN`, the lookback readings are sorted by `kw_load` descending, ties broken by `interval_start` descending, the top three are selected, and `baseline_kw` is the arithmetic mean of those three `kw_load` values. Under `WEATHER_REGRESSION`, the top-N selection is not used at all: `baseline_kw` is the arithmetic mean of the `kw_load` values across all readings in the lookback, multiplied by a weather adjustment factor of 1.10. In either case `baseline_kw` is rounded half-up to three decimal places.

**Delivered energy and performance.** The event's duration in hours is the difference between `window_end` and `window_start` expressed in seconds, divided by 3600. The device's event-window load is the arithmetic mean of `kw_load` over that device's meter readings whose `reading_type` is `EVENT_WINDOW` and whose `dispatch_event_id` equals this event; that mean is the dispatch's `avg_event_load_kw`, and when no such readings exist it is treated as 0. The `actual_reduction_kw` is the greater of 0 and the baseline load minus the event-window load, so a device that drew more than its baseline records no negative reduction. The `delivered_kwh` is `actual_reduction_kw` multiplied by the event duration in hours, rounded half-up to three decimal places. The `performance_ratio` is `actual_reduction_kw` divided by the dispatch's `assigned_reduction_kw`, rounded half-up to four decimal places; when `assigned_reduction_kw` is 0 the ratio is defined as 0 rather than divided.

### 3.7. Settlement, Payouts, and Payments

Settlement turns a completed event's measurements into money. A `ProgramOperator` creates a settlement by supplying the `dispatch_event_id` of the event to be settled; that id must resolve, else `ERR_DISPATCH_EVENT_NOT_FOUND`. The settlement is born in `DRAFT` status with `total_delivered_kwh` and `net_payment_cents` at 0 and `approved_by_user_id` null, and it copies the program's `settlement_method` into its own `method_snapshot`, freezing the payout algorithm for this settlement. An event's settlement (an array of zero or one) can be fetched through the event, individual settlements can be fetched by id, and a settlement's payments can be listed (filterable by `status`).

**Submission and payout computation.** Submitting a settlement moves it to `PENDING_APPROVAL` and increments its `version` by 1. Submission is allowed from `DRAFT` and from `REVISED`. Submitting from `DRAFT` additionally requires the settled event to be in `COMPLETED` status; if it is not, the submission is refused with `ERR_INVALID_STATE`. On every submission the system recomputes each eligible dispatch's `net_payment_cents` and then the settlement's `total_delivered_kwh` and `net_payment_cents`. The eligible set for all settlement math is the event's dispatches in `COMPLETED` status; dispatches that ended `OVERRIDDEN` or `OPTED_OUT` are excluded from every sum.

**Per-dispatch payout (tiered).** Each eligible dispatch's `net_payment_cents` is computed from its measured `delivered_kwh`, its `assigned_reduction_kw`, its `performance_ratio`, the event duration in hours, and the program's rates — the incentive rate `incentive_rate_cents_per_kwh`, the penalty rate `penalty_rate_cents_per_kwh`, and the performance floor `performance_floor_pct`. First define the dispatch's assigned energy as `assigned_reduction_kw` multiplied by the event duration in hours. Then select one of three tiers by `performance_ratio`. If the ratio is at or above the overperformance threshold of 1.10, the dispatch earns a bonus: its incentive is `delivered_kwh` multiplied by the incentive rate and then by a bonus multiplier of 1.15, with no penalty. Otherwise, if the ratio is at or above the program's `performance_floor_pct`, the incentive is `delivered_kwh` multiplied by the incentive rate, with no penalty. Otherwise — the ratio is below the floor — the incentive is still `delivered_kwh` multiplied by the incentive rate, but a penalty is charged equal to the greater of 0 and (assigned energy minus `delivered_kwh`), multiplied by the penalty rate. The dispatch's net is its incentive minus its penalty. That net is rounded half-up to whole cents and then floored at 0, so `net_payment_cents` is the greater of 0 and the rounded net; no dispatch ever carries a negative payout.

**Settlement total (two variants).** The settlement's `total_delivered_kwh` is the sum of `delivered_kwh` over the eligible dispatches, rounded half-up to three decimal places. The settlement's own `net_payment_cents` depends on the frozen `method_snapshot`. Under `PAY_FOR_PERFORMANCE`, the settlement net is the sum of the eligible dispatches' already-rounded per-dispatch `net_payment_cents` — each line is rounded to whole cents first and only then summed, so the round-then-sum order is authoritative and must not be re-derived from unrounded line values. Under `CAPACITY_PAYMENT`, the per-dispatch tiered payout is not used at all; instead the settlement pays for committed capacity net of an energy shortfall. The capacity component is the sum of `assigned_reduction_kw` over the eligible dispatches, multiplied by the program's `capacity_incentive_cents_per_kw`. The shortfall component is computed per eligible dispatch as the greater of 0 and (that dispatch's `assigned_reduction_kw` multiplied by the event duration in hours, minus its `delivered_kwh`), summed across dispatches, and then multiplied by the program's `penalty_rate_cents_per_kwh`. The settlement net is the capacity component minus the shortfall component, rounded half-up to whole cents and floored at 0 (the greater of 0 and that rounded difference).

**Approval, segregation of duties, and payment issuance.** A `ProgramOperator` approves a `PENDING_APPROVAL` settlement, moving it to `APPROVED` and incrementing its `version` by 1. Segregation of duties is enforced here: the acting operator's `X-User-ID` must differ from the settled event's `dispatched_by_user_id` — the operator who called the event may not approve its payout — else the request is refused with `ERR_SEGREGATION_OF_DUTIES`. On approval the settlement records `approved_by_user_id` as the acting `X-User-ID`, and a two-stage payout cascade runs. First, for each distinct aggregator appearing among the event's `COMPLETED` dispatches, the system creates one `Payment` in `ISSUED` status whose `amount_cents` is that aggregator's summed dispatch `net_payment_cents` across the eligible dispatches, linked to the originating settlement through `settlement_id` and to the payee through `aggregator_id`. Second, because each payment was created `ISSUED`, each affected aggregator's `paid_balance_cents` is recomputed as the sum of its `ISSUED` and `CLEARED` payment amounts. The settled event is moved to `SETTLED` status as part of approval.

**Disputes and payment reversal.** An `Aggregator` that participated in the event — one holding at least one dispatch in this settlement's event — may dispute the settlement, moving it to `DISPUTED` and incrementing `version` by 1; an aggregator with no dispatch in the event is refused with `ERR_FORBIDDEN_OWNERSHIP`. A settlement may be disputed either from `PENDING_APPROVAL` or from `APPROVED`. Disputing an `APPROVED` settlement additionally compensates the already-issued payouts: every payment of this settlement still in `ISSUED` status is moved to `REVERSED`, and each affected aggregator's `paid_balance_cents` is recomputed with the reversed payments excluded, so the paid-balance ledger unwinds exactly what approval added. Disputing from `PENDING_APPROVAL` has no issued payments to reverse.

**Revision, re-submission, and the dispute cycle.** A `ProgramOperator` revises a `DISPUTED` settlement, moving it to `REVISED` and incrementing `version` by 1; revision recomputes each eligible dispatch's `net_payment_cents` and the settlement totals afresh. A `REVISED` settlement can be submitted again, returning to `PENDING_APPROVAL` (recomputing its net) and re-entering the approval path — this forms the recurring `PENDING_APPROVAL → DISPUTED → REVISED → PENDING_APPROVAL` loop until the parties settle.

**Marking paid.** Finally, a `ProgramOperator` marks an `APPROVED` settlement as paid, moving it to the terminal `PAID` status and incrementing `version` by 1. Marking paid clears the money: every payment of this settlement still in `ISSUED` status is moved to `CLEARED`. Because both `ISSUED` and `CLEARED` payments count toward an aggregator's `paid_balance_cents`, clearing does not change that balance. Any settlement transition attempted from a status the transition does not permit is refused with `ERR_INVALID_STATE`.

**Payment records.** Payments are system-created and never posted directly. Each carries its `settlement_id`, `aggregator_id`, `amount_cents`, and a `status` of `ISSUED`, `CLEARED`, or `REVERSED`; each state change increments the payment's `version` by 1. Payments can be fetched by id or listed with reverse-lookup filters `aggregator_id`, `settlement_id`, and `status`.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; all other successful operations, including state transitions and updates, return HTTP 200. Request bodies, response bodies, and side effects are not repeated here — reconstruct them from the workflow narratives in §3. Roles listed are those permitted to invoke the endpoint; all four roles may perform every GET.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/dr/programs` | Create a program (DRAFT) | ProgramOperator |
| GET | `/dr/programs/{id}` | Fetch a program | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/programs` | List programs | ProgramOperator, Aggregator, Customer, Auditor |
| PATCH | `/dr/programs/{id}` | Update program rate configuration (OCC-guarded) | ProgramOperator |
| POST | `/dr/programs/{id}/activate` | Activate a program (DRAFT to ACTIVE) | ProgramOperator |
| POST | `/dr/programs/{id}/close` | Close a program (ACTIVE to CLOSED) | ProgramOperator |
| POST | `/dr/aggregators` | Onboard an aggregator | ProgramOperator |
| GET | `/dr/aggregators/{id}` | Fetch an aggregator (includes computed balances) | ProgramOperator, Aggregator, Customer, Auditor |
| POST | `/dr/customers` | Onboard a customer | ProgramOperator |
| GET | `/dr/customers/{id}` | Fetch a customer | ProgramOperator, Aggregator, Customer, Auditor |
| POST | `/dr/devices` | Register a device (aggregator_id from acting user) | Aggregator |
| GET | `/dr/devices/{id}` | Fetch a device | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/devices` | List/filter devices | ProgramOperator, Aggregator, Customer, Auditor |
| POST | `/dr/devices/{id}/decommission` | Decommission a device (ACTIVE to DECOMMISSIONED) | Aggregator |
| POST | `/dr/devices/{id}/meter-readings` | Append an immutable interval meter reading | Aggregator |
| GET | `/dr/devices/{id}/meter-readings` | List a device's meter readings | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/meter-readings/{id}` | Fetch a meter reading | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/meter-readings` | List/filter meter readings | ProgramOperator, Aggregator, Customer, Auditor |
| POST | `/dr/enrollments` | Enroll a device in a program (PENDING) | Aggregator |
| GET | `/dr/enrollments/{id}` | Fetch an enrollment | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/enrollments` | List/filter enrollments | ProgramOperator, Aggregator, Customer, Auditor |
| POST | `/dr/enrollments/{id}/activate` | Activate an enrollment (PENDING to ACTIVE) | Aggregator |
| POST | `/dr/enrollments/{id}/opt-out` | Opt an enrollment out (ACTIVE to OPTED_OUT) | Customer, Aggregator |
| POST | `/dr/enrollments/{id}/re-enroll` | Re-enroll (OPTED_OUT to ACTIVE) | Aggregator |
| POST | `/dr/enrollments/{id}/terminate` | Terminate an enrollment (ACTIVE to TERMINATED) | Aggregator |
| POST | `/dr/dispatch-events` | Schedule a dispatch event (SCHEDULED) | ProgramOperator |
| GET | `/dr/dispatch-events/{id}` | Fetch a dispatch event | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/dispatch-events` | List/filter dispatch events | ProgramOperator, Aggregator, Customer, Auditor |
| POST | `/dr/dispatch-events/{id}/notify` | Notify event (SCHEDULED to NOTIFIED); fan out dispatches | ProgramOperator |
| POST | `/dr/dispatch-events/{id}/start` | Start event (NOTIFIED to ACTIVE) | ProgramOperator |
| POST | `/dr/dispatch-events/{id}/complete` | Complete event (ACTIVE to COMPLETED); measurement cascade | ProgramOperator |
| POST | `/dr/dispatch-events/{id}/cancel` | Cancel event (SCHEDULED/NOTIFIED to CANCELLED) | ProgramOperator |
| GET | `/dr/dispatch-events/{id}/dispatches` | List an event's dispatches | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/dispatch-events/{id}/settlement` | Fetch the event's settlement(s) | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/dispatches/{id}` | Fetch a dispatch | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/dispatches` | List/filter dispatches | ProgramOperator, Aggregator, Customer, Auditor |
| POST | `/dr/dispatches/{id}/acknowledge` | Acknowledge dispatch (PENDING to ACKNOWLEDGED) | Aggregator |
| POST | `/dr/dispatches/{id}/start-curtailment` | Start curtailment (ACKNOWLEDGED to CURTAILING) | Aggregator |
| POST | `/dr/dispatches/{id}/override` | Customer override (to OVERRIDDEN) | Customer |
| POST | `/dr/settlements` | Create a settlement (DRAFT) for a COMPLETED event | ProgramOperator |
| GET | `/dr/settlements/{id}` | Fetch a settlement | ProgramOperator, Aggregator, Customer, Auditor |
| POST | `/dr/settlements/{id}/submit` | Submit settlement (DRAFT/REVISED to PENDING_APPROVAL) | ProgramOperator |
| POST | `/dr/settlements/{id}/approve` | Approve settlement (PENDING_APPROVAL to APPROVED); SoD-gated | ProgramOperator |
| POST | `/dr/settlements/{id}/dispute` | Dispute settlement (to DISPUTED) | Aggregator |
| POST | `/dr/settlements/{id}/revise` | Revise settlement (DISPUTED to REVISED) | ProgramOperator |
| POST | `/dr/settlements/{id}/mark-paid` | Mark settlement paid (APPROVED to PAID) | ProgramOperator |
| GET | `/dr/settlements/{id}/payments` | List a settlement's payments | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/payments/{id}` | Fetch a payment | ProgramOperator, Aggregator, Customer, Auditor |
| GET | `/dr/payments` | List/filter payments | ProgramOperator, Aggregator, Customer, Auditor |
| POST | `/_clock/set_current_utc` | Test-driving logical clock setter | ProgramOperator |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the §2 and §3 narratives; this catalogue lists only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 422 |
| ERR_INVALID_ENUM | 422 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_AGGREGATOR_NOT_FOUND | 404 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_DEVICE_NOT_FOUND | 404 |
| ERR_ENROLLMENT_NOT_FOUND | 404 |
| ERR_DISPATCH_EVENT_NOT_FOUND | 404 |
| ERR_DISPATCH_NOT_FOUND | 404 |
| ERR_METER_READING_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_PAYMENT_NOT_FOUND | 404 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_INVALID_STATE | 409 |
| ERR_PROGRAM_NOT_ACTIVE | 409 |
| ERR_DEVICE_NOT_ELIGIBLE | 409 |
| ERR_DUPLICATE_ENROLLMENT | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NO_ELIGIBLE_ENROLLMENTS | 409 |
| ERR_NOTIFY_LEAD_NOT_MET | 422 |
| ERR_EVENT_NOT_STARTED | 409 |
| ERR_EVENT_NOT_ENDED | 409 |
| ERR_OVERRIDE_WINDOW_CLOSED | 409 |
| ERR_EVENT_WINDOW_CONFLICT | 409 |
| ERR_SEASON_EVENT_CAP_EXCEEDED | 409 |
| ERR_READING_INTERVAL_OVERLAP | 409 |
| ERR_BASELINE_DATA_MISSING | 422 |
| ERR_STALE_VERSION | 412 |

