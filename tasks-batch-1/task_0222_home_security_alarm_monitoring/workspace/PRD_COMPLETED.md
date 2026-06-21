# Home Security & Alarm Monitoring API — Product Requirements Document

## 1. Introduction

This document specifies the Home Security & Alarm Monitoring platform: the back-end service that ties together a subscriber's premises hardware, a central monitoring station, and the back-office administration that governs contracts, permits, and fines. The platform tracks the full inventory of installed equipment — security systems and their sensors — alongside the monitoring plan a subscriber has contracted for, and it is the system of record for every alarm signal that arrives from the field.

The operational heart of the platform is signal handling. When a sensor trips, a raw signal is ingested, classified, and — depending on the arming posture of the system, whether the system is in test mode, and whether the owning account's service is in good standing — either routed to the appropriate emergency responder (police, fire, or medical) and escalated to a real dispatch, or quietly suppressed. Because false alarms carry real municipal cost, the platform layers a permit-and-fine regime on top of dispatch: jurisdictions issue false-alarm permits, the system counts chargeable false alarms over a permit cycle, and it assesses escalating fines as a subscriber's false-alarm history grows. A failure to maintain a valid permit increases those fines.

Surrounding all of this is a contract lifecycle (activation, mid-cycle plan changes with proration, cancellation with an early-termination fee) and a continuous health assessment of each system's communicator path — cellular signal strength, backup battery, and last check-in — that can suspend monitoring service when a premises can no longer reliably reach the central station. The remainder of this document defines the global contracts that every endpoint honours (§2), the business workflows and their precise rules (§3), the endpoint surface (§4), and the catalogue of error identifiers (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. The system recognises exactly three roles, spelled precisely as follows: `Subscriber`, `MonitoringOperator`, and `Administrator`. When a well-authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN`.

The three roles differ not only in what they may do but in how their identity binds to data. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's owning-account foreign key to `X-User-ID`. Concretely, a `Subscriber` may only arm, disarm, bypass or restore a sensor, request or withdraw cancellation, or pay a fine on resources that trace back to their own account; when the targeted resource's owning account is not the caller's `X-User-ID`, the request is rejected with `ERR_NOT_ACCOUNT_OWNER`. (Entering and exiting test mode are not ownership-bound and carry no such check.) When `X-User-Role` is `MonitoringOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `Administrator`, `X-User-ID` is an opaque back-office identifier not tied to any persisted entity and is never compared to any entity's `id`.

A `Subscriber` is the account holder. They arm and disarm their own system, may enter and exit test mode, bypass and restore sensors, request and withdraw a contract cancellation, and pay assessed fines, and they may read any resource. A `MonitoringOperator` is a central-station operator who ingests incoming signals, routes them, orders and cancels dispatches, and resolves events; operators may also toggle test mode, push telemetry updates onto a system, and read freely. An `Administrator` runs the back office: they create monitoring plans, accounts, systems, sensors, and permits; they drive the contract lifecycle (activation, plan changes, cancellation finalization); they revoke or expire permits; they settle fines by waiving them; and they may also share several subscriber- and operator-facing actions. Reads across every collection are open to all three roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set; when omitted it defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their `created_at` timestamp in ascending order.

Each list response carries the pagination bookkeeping in the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Timestamps

Most resources in the system — accounts, security systems, sensors, alarm events, dispatches, permits, and fines — carry a common set of system-managed fields. Each has an `id` that is a server-minted UUID with no type prefix, serving purely as identity. Each has a `created_at` timestamp recorded at creation, expressed as an ISO 8601 UTC instant with three fractional digits. Each also carries an `updated_at` timestamp, in the same format, refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one on every mutation of that resource.

The `MonitoringPlan` entity is the sole exception. A plan is an immutable price-book row, so it carries only `id` and `created_at`; it has neither `updated_at` nor `version`. Once written, a plan's pricing fields are never altered in place — a tier change is modelled by pointing an account at a different plan, not by editing a plan.

### 2.5. Nested Resource Resolution and Reference Integrity

Resources in this system form flat, top-level collections rather than nested URL hierarchies; relationships are carried by foreign-key fields in request bodies and surfaced through filter parameters on list endpoints. Even so, path-referenced resources are resolved before any business rule runs: when a request addresses a resource by its identifier in the path and no such resource exists, the request is rejected with `ERR_NOT_FOUND` before further processing. Where a path carries more than one identifier, identifiers are validated left to right, and the first one that fails to resolve produces the rejection.

Separately, when a creation request names another resource by a body-level foreign key — a `plan_id` on an account, an `account_id` on a system or permit, a `system_id` on a sensor or alarm event, or a `sensor_id` on an alarm event — that reference must resolve to an existing row. A dangling reference is rejected with `ERR_REFERENCE_NOT_FOUND`.

### 2.6. Monetary Precision and Rounding

All monetary amounts in the system are stored and returned as integer counts of cents — `monthly_fee_cents`, `monitoring_balance_cents`, `early_termination_fee_cents`, `fee_cents`, `fee_total_cents`, and `amount_cents` are all whole-cent integers, never fractional currency. Wherever a calculation divides or scales an amount and a fractional cent would result, the value is rounded half up to the nearest whole cent. The proration calculation pins a specific rounding order described in §3, and the permit late-penalty calculation rounds half up before applying its cap; both are detailed where the calculation is defined.

### 2.7. Optimistic Concurrency Control on Account Writes

Two account-level operations are guarded by optimistic concurrency control, because both re-anchor financial state that the operator must have observed before acting. Each requires the caller to submit `expected_account_version` as a non-optional field carrying the `version` of the `Account` the client last read.

A plan-change request must carry `expected_account_version` matching the target account's current `version`. If another writer has advanced the account's `version` since the client last read it — for example, a previously committed plan change that legitimately superseded the prior proration segment and re-anchored proration — the change is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a segment boundary it never observed. Two strictly sequential plan-change calls that both carry the same observed version reproduce this exactly: the first advances `version`, and the second is rejected as stale.

A cancellation-finalization request likewise must carry `expected_account_version` matching the account's current `version`. If another writer has advanced the account's `version` since the operator last read it — most importantly a withdrawal that returned the account to `ACTIVE` and bumped its version — the finalize view is stale and is rejected with `ERR_STALE_VERSION` (HTTP 412), so the system never terminates a contract the customer has since chosen to keep. No other endpoint takes a version field; only plan-change and finalize-cancellation are version-checked.

### 2.8. Derived Service Posture and Communicator Health

Two fields are never written directly by a client; the server derives them on every read and on any change that could affect them. The first is `communicator_health` on a security system, derived from its telemetry. The second is `monitoring_status` on an account, derived from the contract posture together with the health of the account's systems. Because they are computed, a read of an account or a system always reflects the current derivation, and a telemetry update that changes a system's health may flip the owning account's monitoring posture between `ACTIVE` and `SUSPENDED`. The precise derivation rules live in §3 alongside the workflows that depend on them.

### 2.9. Hierarchical Consistency and Cascades

A single operation in this system frequently mutates more than one resource, and every such cascade is part of the contract. When a contract is finalized into cancellation, the effect ripples from the account down through its systems, their open alarm events, and any ordered dispatches, reversing financial commitments as it goes. When a dispatch is cancelled, the account's running balance is restored. When a sensor is removed, its system's sensor tally is decremented. Each mutated resource independently refreshes its own `updated_at` and increments its own `version` as part of the operation. The complete cascade chains are specified in §3 where the triggering workflow is described; the governing principle here is that no cascade is optional and no secondary effect is silent.

### 2.10. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed order so that the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorisation (`ERR_FORBIDDEN`), then existence of every path-referenced resource (`ERR_NOT_FOUND`), then resolution of body-referenced foreign keys (`ERR_REFERENCE_NOT_FOUND`), then the subscriber ownership check (`ERR_NOT_ACCOUNT_OWNER`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Business-specific safety, constraint, and temporal checks follow, in the relative order given in §3 where each is described, and the optimistic-concurrency comparison is evaluated within that business band as noted for the two guarded account writes. Request-body well-formedness — all required input fields present, every enum member valid, every numeric input within range — is logically enforced immediately after authentication, but it only fires when the body itself is malformed and so never preempts the conflict-resolution checks above; a malformed body is rejected with `ERR_VALIDATION`.

## 3. Business Logic & Workflows

### 3.1. Monitoring Plans and the Account Contract Lifecycle

The price book of the platform is the set of **monitoring plans**. An `Administrator` creates a plan by supplying its `tier` — one of `BASIC`, `PLUS`, or `PRO`, and no two plans may share a tier — together with the `monthly_fee_cents` charged each cycle (which may not be negative), a `police_dispatch_included` flag, a `max_sensors` ceiling (at least 1), and a `cellular_backup_included` flag. These fields are fixed once written. The `police_dispatch_included` flag governs whether a police dispatch carries a per-dispatch fee on this tier; `cellular_backup_included` governs whether systems on this plan may register a cellular communicator path; and `max_sensors` caps how many sensors a system on this plan may carry.

An `Administrator` opens an **account** by declaring its `premises_type` — `RESIDENTIAL` or `COMMERCIAL` — the `plan_id` of the monitoring plan it subscribes to, and a committed `contract_term_months` of at least one month. A freshly created account begins with `contract_status` of `PENDING`; its derived `monitoring_status` reads `SUSPENDED` because no service runs before activation; and every balance and counter starts at zero. While `PENDING`, the account has no `contract_start_utc`, no `cycle_anchor_utc`, and no `current_tier` yet established.

Activation is an `Administrator` action that drives `contract_status` from `PENDING` to `ACTIVE`. It is permitted only when the account is currently `PENDING`, when the account has at least one security system whose `sensor_count` is at least one, and when the referenced monitoring plan still exists. On activation the server stamps `contract_start_utc` to the current clock, sets `cycle_anchor_utc` to the current clock to open a fresh billing cycle, copies the tier of the account's plan into `current_tier` as the proration baseline, and recomputes `monitoring_balance_cents` for the new cycle.

Cancellation is a three-step lifecycle. A `Subscriber` or an `Administrator` may request cancellation, which is allowed only while the contract is `ACTIVE` and which moves `contract_status` from `ACTIVE` to `CANCELLATION_REQUESTED`. At that moment the early-termination fee is computed and frozen onto `early_termination_fee_cents` (see §3.2), and the account's `version` increments by one. From `CANCELLATION_REQUESTED`, the same parties may withdraw the request, allowed only while `contract_status` is `CANCELLATION_REQUESTED`; withdrawal returns the contract to `ACTIVE`, resets `early_termination_fee_cents` back to zero, and increments `version` by one. Finalization is reserved to an `Administrator` and is allowed only while `contract_status` is `CANCELLATION_REQUESTED`; it is the guarded write described in §2.7 and carries the cascade described in §3.7. Across the contract, `monitoring_status` is `TERMINATED` once the account is `CANCELLED`, and `CANCELLED` is the terminal contract state.

The derived `monitoring_status` is recomputed on every account read and whenever contract or communicator state changes. If `contract_status` is `CANCELLED`, monitoring is `TERMINATED`. Otherwise, if `contract_status` is `PENDING`, monitoring is `SUSPENDED`, because no service runs before activation. Otherwise — that is, when `contract_status` is `ACTIVE` or `CANCELLATION_REQUESTED` — monitoring is `SUSPENDED` if the account's worst-health system is `OFFLINE`, and `ACTIVE` only when no system under the account is `OFFLINE`.

### 3.2. Plan Changes, Proration, and Early Termination

An `Administrator` may change an account's monitoring plan mid-cycle by submitting a `new_plan_id` together with `expected_account_version`. A plan change is defined only while the account has an open billing cycle to re-anchor — that is, while `contract_status` is `ACTIVE` or `CANCELLATION_REQUESTED`; from any other contract status (`PENDING` or `CANCELLED`) the request is rejected with `ERR_INVALID_STATE`, and that state check (per §2.10) precedes the open-dispatch and optimistic-concurrency checks below. Beyond the optimistic-concurrency guard of §2.7, the change is blocked while any alarm event under the account is in status `DISPATCHED` — an open responder dispatch must resolve before the proration cycle can be re-anchored — and that block surfaces as `ERR_OPEN_DISPATCH`. A successful change records a proration segment boundary at the current clock, updates `current_tier`, recomputes `monitoring_balance_cents` to its authoritative value, and increments the account's `version` by one.

**Proration is computed day by day, with a pinned rounding order.** The billing cycle covers the 30 days running from `cycle_anchor_utc`; that is, days numbered 0 up to but not including 30. For each whole day that has elapsed from the cycle anchor up to the evaluation instant, the system determines the tier in effect at the start of that day — the most recent plan-change segment boundary on or at the start of that day, or, if none, the `current_tier` recorded at the anchor. That day's charge is the monthly fee of the in-effect tier's plan divided by 30, rounded half up to a whole cent. The proration amount is the sum of those per-day charges across all elapsed days; the elapsed-day count is itself capped at the 30-day cycle length, so once the evaluation instant reaches 30 or more days past the anchor the proration holds at the full 30-day total and never accrues beyond it. The rounding order is fixed: each day is rounded to whole cents first, and only then are the rounded daily charges summed. The system must not sum unrounded daily fractions and round once at the end. For reference, a `BASIC`-to-`PLUS` change at day seven, with monthly fees of 1500 and 3100 cents, yields 2719 cents under this authoritative day-by-day method (a per-segment projection that rounds once per segment would instead yield 2727, but that projection is only a forward quote, never the stored value).

The authoritative `monitoring_balance_cents` is the sum of the day-by-day proration to date plus the fees of every dispatch on the account that is in status `ORDERED` or `CONFIRMED`; cancelled dispatches contribute nothing. The result is floored at zero and is never negative. This balance is recomputed on activation, on plan change, on dispatch creation and cancellation, and on every account read. A `PENDING` account reports a balance of zero outright (it has no open cycle); for every other `contract_status` — including `CANCELLATION_REQUESTED` and `CANCELLED` — the balance is the computed proration-plus-dispatches sum, so proration continues to accrue against the original `cycle_anchor_utc` even after the contract reaches `CANCELLED`.

The **early-termination fee**, frozen at the instant cancellation is requested, depends on how much of the committed term remains. The system counts elapsed months as the whole number of 30-day spans between `contract_start_utc` and the request clock — that is, the difference floored to whole 30-day months. Remaining months is the committed `contract_term_months` minus those elapsed months, but never less than zero. When no months remain, `early_termination_fee_cents` is zero; otherwise it is the number of remaining months multiplied by 2000 cents per remaining month. Withdrawal resets it to zero.

### 3.3. Security Systems and Communicator Health

An `Administrator` registers a **security system** against an account by supplying the `account_id` it belongs to, its `primary_path` — `BROADBAND` or `CELLULAR` — and three telemetry readings: `cellular_signal_dbm` (the last reported cellular RSSI in dBm, a negative number where values closer to zero are stronger), `backup_battery_pct` (the backup battery charge as a percentage from 0 to 100), and `last_checkin_minutes_ago` (whole minutes since the communicator last checked in, never negative). A newly registered system starts `DISARMED`, with `test_mode` false, `sensor_count` zero, and `communicator_health` derived from the telemetry. A `CELLULAR` primary path may only be set on a system whose plan has `cellular_backup_included` set to true; otherwise the request is rejected with `ERR_CELLULAR_NOT_ENTITLED`, and this entitlement check applies both at system registration and when telemetry or path is patched.

A `MonitoringOperator` or `Administrator` may push a telemetry update to a system, optionally revising `primary_path`, `cellular_signal_dbm`, `backup_battery_pct`, or `last_checkin_minutes_ago`. Any such update re-derives `communicator_health`, which may in turn flip the owning account's `monitoring_status` between `ACTIVE` and `SUSPENDED` per §3.1.

**Communicator health** is derived as follows. First the most recent check-in is assessed: if `last_checkin_minutes_ago` is greater than 360 minutes (that is, more than six hours), the system is `OFFLINE` outright and no further checks are made. Otherwise — when the last check-in is at most 360 minutes ago — the system evaluates two boundary-inclusive thresholds: the signal is acceptable when `cellular_signal_dbm` is at or above −85 dBm, and the battery is acceptable when `backup_battery_pct` is at or above 20 percent. When both are acceptable, health is `HEALTHY`; when the system is not `OFFLINE` but at least one of signal or battery falls below its threshold, health is `DEGRADED`.

### 3.4. Arming, Disarming, and Test Mode

A `Subscriber` arms their own system by supplying a `mode` of either `ARMED_STAY` or `ARMED_AWAY`; the system's `arming_state` moves from `DISARMED` to the chosen mode. Arming is permitted only when the owning account's `contract_status` is `ACTIVE`, when the system's `communicator_health` is not `OFFLINE`, and when `test_mode` is false. These three gates are evaluated in that order: an account that is not `ACTIVE` is rejected first with `ERR_INVALID_STATE`; then a system whose communicator cannot reach the monitoring centre — that is, one whose `communicator_health` is `OFFLINE` — cannot be armed, and the attempt is rejected with `ERR_COMMUNICATOR_OFFLINE`; finally, attempting to arm a system whose `test_mode` is true is rejected with `ERR_INVALID_STATE`. The arming state is otherwise free to cycle among `DISARMED`, `ARMED_STAY`, and `ARMED_AWAY` while the account is `ACTIVE`.

Disarming returns the system to `DISARMED` and is permitted only from `ARMED_STAY` or `ARMED_AWAY`. Disarming carries a targeted side effect: any alarm event on this system that is still `RECEIVED` and whose `signal_type` is `BURGLARY` (and therefore not yet routed) is resolved to `RESOLVED_FALSE`, with its `resolution` set to `FALSE_ALARM`; this disarm-driven resolution creates no fine and assigns no `chargeable_ordinal`, but because it carries a `FALSE_ALARM` resolution and no linked fine (and so is not waived), the event does contribute to the owning account's derived `false_alarm_count_cycle`. Fire, medical, and panic events on the system are left untouched by a disarm.

A `Subscriber` or a `MonitoringOperator` may put a system into **test mode**, in which alarms are logged but never escalated. Entering test mode is permitted only while the owning account's `contract_status` is `ACTIVE`, and only when no test-mode window is currently open. The window is half-open over the interval beginning at entry and ending at `test_mode_expires_utc`, with adjacency allowed: a window is considered open precisely while the current clock is strictly before `test_mode_expires_utc`. Entering is therefore allowed when `test_mode` is false, or when the current clock has reached `test_mode_expires_utc`; a re-entry exactly at `test_mode_expires_utc` is permitted, while any earlier re-entry is rejected with `ERR_TEST_MODE_ALREADY_OPEN`. On entry, `test_mode` is set true, `test_mode_expires_utc` is set to the current clock plus the 120-minute test-mode window, and `arming_state` is forced to `DISARMED`. Exiting test mode — also available to a `Subscriber` or `MonitoringOperator` — sets `test_mode` back to false and clears `test_mode_expires_utc`.

### 3.5. Sensor Inventory

An `Administrator` enrols a **sensor** onto a system by providing the `system_id` it lives under, its `zone_number` (a physical zone identifier of at least 1), and its `sensor_type` — one of `DOOR`, `MOTION`, `GLASS_BREAK`, `SMOKE`, `CO`, or `PANIC`. A new sensor starts in status `ENROLLED`, and enrolling it increments the owning system's `sensor_count`. Two constraints guard enrolment, and when a request would violate both they are evaluated capacity-first. First, capacity must remain within plan limits: enrolling a sensor must not push the system's `sensor_count` above the `max_sensors` of the account's plan, and an over-limit enrolment is rejected with `ERR_SENSOR_LIMIT_EXCEEDED`. Second, the zone must be free: `zone_number` must be unique among the non-`REMOVED` sensors on the same system, and a collision is rejected with `ERR_DUPLICATE_ZONE`.

A sensor's lifecycle is otherwise a small cycle. A `Subscriber` or `Administrator` may bypass an `ENROLLED` sensor, moving its `status` to `BYPASSED`; a bypassed sensor is excluded from arming faults but still counts toward `sensor_count`. The same parties may restore a `BYPASSED` sensor back to `ENROLLED`. An `Administrator` may remove a sensor that is currently `ENROLLED` or `BYPASSED`, moving it to the terminal `REMOVED` status; removal decrements the system's `sensor_count` by one, so that an enrol-then-remove pair leaves the tally conserved. A removed sensor's zone is freed, since uniqueness is enforced only among non-`REMOVED` sensors. The `sensor_count` on a system is always the number of its sensors that are not `REMOVED`.

### 3.6. Signal Ingestion, Routing, Dispatch, and Resolution

A `MonitoringOperator` or `Administrator` ingests an **alarm event** by submitting the `system_id` that raised it, the triggering `sensor_id`, and the raw `signal_type` — one of `BURGLARY`, `FIRE`, `MEDICAL`, or `PANIC`. The server stamps `raised_utc` to the current clock and the event begins in status `RECEIVED`. Two ingest-time outcomes diverge immediately. If the raising system is in test mode, or if the raising system is `DISARMED` and the `signal_type` is `BURGLARY`, the event is auto-resolved to `SUPPRESSED` — logged only, never routed and never dispatched, because test-mode and disarmed-burglary signals must never escalate. Otherwise the event remains `RECEIVED` awaiting an operator.

Ingestion is also debounced to absorb sensor chatter. A new alarm event from the same sensor whose `raised_utc` falls within 60 seconds of a still-open prior event from that sensor — where "still open" means a prior event in `RECEIVED`, `ROUTED`, or `DISPATCHED` — is rejected as a duplicate with `ERR_SIGNAL_DEBOUNCED`. The window is a buffer measured from the prior event and is strict at its boundary: a new event collides only when its offset from the prior event is strictly less than 60 seconds, so two events from the same sensor spaced exactly 60 seconds apart — or any wider gap — never collide.

Routing advances a `RECEIVED` event to `ROUTED`, performed by a `MonitoringOperator`. It is permitted only when the event is `RECEIVED`, when the raising system's `test_mode` is false, and when the owning account's `monitoring_status` is `ACTIVE`. An attempt to route an event whose system is in test mode is rejected with `ERR_TEST_MODE_ACTIVE`, since test-mode signals never escalate; this test-mode check is evaluated after the event-status check and before the monitoring-status check. When the owning account's derived `monitoring_status` is not `ACTIVE` (for example because a system under the account is `OFFLINE` and has suspended the account), routing is rejected with `ERR_INVALID_STATE`. Routing sets `routed_service` by the raw signal: a `BURGLARY` or `PANIC` signal routes to `POLICE`, a `FIRE` signal routes to `FIRE`, and a `MEDICAL` signal routes to `MEDICAL`.

Dispatch advances a `ROUTED` event to `DISPATCHED`, again by a `MonitoringOperator` and permitted only from `ROUTED`. Dispatching creates a **dispatch** record whose `service` equals the event's `routed_service`, whose `account_id` is the event's owning account, and whose `status` begins `ORDERED`; in the same step the dispatch fee is charged onto the account's `monitoring_balance_cents`. The **dispatch fee** depends on the responder and the plan: a police dispatch costs nothing when the account's plan has `police_dispatch_included` true, but 2500 cents when that flag is false; a fire dispatch costs 4000 cents; and a medical dispatch costs 4000 cents. The chosen amount is recorded on the dispatch's `fee_cents` and added to `monitoring_balance_cents` at creation.

Resolution closes a `DISPATCHED` event, performed by a `MonitoringOperator`, who supplies a `resolution` of either `REAL` or `FALSE_ALARM`. Resolving as `REAL` moves the event to `RESOLVED_REAL`; resolving as `FALSE_ALARM` moves it to `RESOLVED_FALSE`. In both cases the linked dispatch transitions from `ORDERED` to `CONFIRMED` and its fee is retained on the account. A false-alarm resolution carries two further effects in sequence, detailed in §3.8: the account's `false_alarm_count_cycle` rises, and that count change drives assignment of this event's `chargeable_ordinal` and the creation of a fine.

A `MonitoringOperator` may also cancel a dispatch while it is still `ORDERED`, moving its `status` to `CANCELLED`. Cancellation is compensating: the dispatch's `fee_cents` is reversed out of the account's `monitoring_balance_cents`, returning the balance to its pre-dispatch value. Cancellation is permitted only from `ORDERED`; `CONFIRMED` and `CANCELLED` are terminal dispatch states. A dispatch's `alarm_event_id` records the event that produced it.

### 3.7. Contract Finalization and the Cancellation Cascade

Finalizing a cancellation, reserved to an `Administrator` and guarded by the optimistic-concurrency rule of §2.7, drives `contract_status` from `CANCELLATION_REQUESTED` to the terminal `CANCELLED` and causes `monitoring_status` to derive to `TERMINATED`. It then runs a three-hop cascade that forcibly sweeps the account's live operational state. First, every security system under the account is forced to `arming_state` `DISARMED` and has its test mode cleared. Second — caused by that force-disarm — each such system's still-open alarm events, meaning every event in `RECEIVED`, `ROUTED`, or `DISPATCHED`, is moved to `SUPPRESSED`. Third — caused by that suppression — each `ORDERED` dispatch on those events is moved to `CANCELLED`, reversing its `fee_cents` out of `monitoring_balance_cents`. The account's `version` increments by one. Within the cascade only resources whose state actually changes are re-stamped: a system that was already `DISARMED` with no test-mode window open is left untouched and keeps its `version`, and likewise an event already terminal or a dispatch not in `ORDERED` is not re-versioned. Note that finalization deliberately sweeps open events including those already `DISPATCHED`; there is no separate open-dispatch block at finalize time, because the open-dispatch guard belongs to the plan-change path (§3.2) instead.

### 3.8. False-Alarm Permits, Counting, and Fines

A jurisdiction's **permit** is issued by an `Administrator` against an account, supplying the `account_id`, a jurisdiction-issued `permit_number` (unique across all permits), and `filed_days_late` — the whole number of days, never negative, by which the application was filed past its deadline. A new permit is `ACTIVE`, its `cycle_anchor_utc` is stamped to open its false-alarm counting cycle, and its `fee_total_cents` is computed at issuance. An account may hold at most one permit in status `ACTIVE` at a time; a second active permit is rejected with `ERR_PERMIT_ALREADY_ACTIVE`. A duplicate `permit_number` across any account is rejected with `ERR_DUPLICATE_PERMIT_NUMBER`.

The **permit issuance fee** sums a base and a late penalty. The base is 5000 cents, plus a commercial uplift of 3000 cents when the account's `premises_type` is `COMMERCIAL` (and nothing extra for a `RESIDENTIAL` premises). The late penalty is zero when `filed_days_late` is zero. When the filing is late, the penalty is the base permit fee of 5000 cents multiplied by 20 percent per late period, where the number of late periods is `filed_days_late` divided by 30 and rounded up to the next whole period; that product is rounded half up to whole cents and then capped at 4000 cents. The `fee_total_cents` is the base plus this late penalty.

An `Administrator` may revoke an `ACTIVE` permit, moving it to the terminal `REVOKED` status, or expire an `ACTIVE` permit, moving it to the terminal `EXPIRED` status. Either transition has the same consequence for billing: from then on, false-alarm fines assessed on the account add the no-permit surcharge, because the account no longer holds a valid permit.

When a dispatched event is resolved as a false alarm, two effects fire in order. First, the account's `false_alarm_count_cycle` — its running tally of non-waived false alarms since the permit cycle anchor — increments. Second, driven by that new count, the event's `chargeable_ordinal` is assigned and a **fine** is created in status `ASSESSED`. The **chargeable ordinal** is the event's 1-based position among the account's chargeable false alarms in the current cycle. To compute it, the system takes the account's alarm events whose `resolution` is `FALSE_ALARM`, whose linked fine is not `WAIVED`, and whose `raised_utc` is at or after the account's `ACTIVE` permit's `cycle_anchor_utc` (or, when the account has no `ACTIVE` permit, at or after the account's own `cycle_anchor_utc`), orders them by `raised_utc` ascending and then by `created_at` ascending as the deterministic tie-break (never by `id`), and takes this event's 1-based position in that ordering. Because waived fines are excluded from this counting, a later false alarm can land in a cheaper tier than its raw chronological position would suggest.

The **false-alarm fine** is built from a tiered base plus a possible surcharge. Let the ordinal be the `chargeable_ordinal` just assigned. The base is zero for the first two chargeable false alarms of the cycle (ordinal 1 or 2, the free allowance); it is 5000 cents for ordinals 3, 4, and 5 (the three-wide warning band above the free allowance); and it is 10000 cents for the sixth and any further chargeable false alarm. On top of the base, a no-permit surcharge of 7500 cents is added when the account holds no permit in status `ACTIVE` at the resolution instant; otherwise no surcharge applies. The fine's `amount_cents` is the base plus the surcharge, and the fine records its `account_id` and the `alarm_event_id` of the false alarm that triggered it.

A `Subscriber` or `Administrator` may pay an `ASSESSED` fine, moving its `settlement_status` to the terminal `PAID`. An `Administrator` may instead waive an `ASSESSED` fine, moving its `settlement_status` to the terminal `WAIVED`. Waiving has a forward-looking effect on counting: a waived fine is excluded from `false_alarm_count_cycle` going forward, but waiving does not renumber the `chargeable_ordinal` values already assigned to prior events. Thus an account whose first fine is waived will see its third raw false alarm counted as ordinal 2 (and so priced in the free band) under this net-of-waived rule, rather than ordinal 3.

### 3.9. Discovering Related Resources and the Logical Clock

Because the collections are flat, related resources are discovered through filter parameters on the list endpoints rather than through nested paths. Accounts may be listed and narrowed by `plan_id` or `contract_status`; systems by `account_id`; sensors by `system_id` or `status`; alarm events by `system_id`, `sensor_id`, or `status`; dispatches by `alarm_event_id`, `account_id`, or `service`; permits by `account_id` or `status`; fines by `account_id`, `alarm_event_id`, or `settlement_status`; and monitoring plans by `tier`. Every list endpoint also accepts `limit` and `offset` per §2.3.

Finally, an `Administrator`-only test-driving capability sets the server's logical UTC clock to a supplied `now_utc` instant. All subsequent server-stamped timestamps and elapsed-time computations — `raised_utc`, `contract_start_utc`, `cycle_anchor_utc`, the proration day count, the test-mode window, the debounce window, and the early-termination elapsed-months count — are evaluated against this clock. Until the clock has been set on a fresh server process, the logical clock falls back to the real wall-clock UTC time; once set, it holds the supplied instant for every subsequent evaluation until set again. This capability sits outside the public business surface and exists so that time-dependent rules can be exercised deterministically.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code; operations that modify an existing resource — including all state-transition actions — return a `200 OK` status code. The logical-clock endpoint also returns `200 OK`. To reconstruct the full request and response shape of any operation, refer to the §3 narrative for that workflow.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/monitoring-plans` | Create a monitoring plan tier | Administrator |
| GET | `/monitoring-plans` | List monitoring plans | Administrator, MonitoringOperator, Subscriber |
| GET | `/monitoring-plans/{id}` | Get a monitoring plan | Administrator, MonitoringOperator, Subscriber |
| POST | `/accounts` | Create an account (contract PENDING) | Administrator |
| GET | `/accounts` | List accounts | Administrator, MonitoringOperator |
| GET | `/accounts/{id}` | Get an account (recomputes derived fields) | Administrator, MonitoringOperator, Subscriber |
| POST | `/accounts/{id}/activate` | Activate the contract | Administrator |
| POST | `/accounts/{id}/change-plan` | Change the monitoring plan mid-cycle (OCC-guarded) | Administrator |
| POST | `/accounts/{id}/request-cancellation` | Request contract cancellation | Subscriber, Administrator |
| POST | `/accounts/{id}/withdraw-cancellation` | Withdraw a pending cancellation request | Subscriber, Administrator |
| POST | `/accounts/{id}/finalize-cancellation` | Finalize cancellation (OCC-guarded) | Administrator |
| POST | `/systems` | Register a security system on an account | Administrator |
| GET | `/systems` | List security systems | Administrator, MonitoringOperator, Subscriber |
| GET | `/systems/{id}` | Get a system (recomputes communicator_health, sensor_count) | Administrator, MonitoringOperator, Subscriber |
| PATCH | `/systems/{id}` | Update communicator telemetry / primary path | Administrator, MonitoringOperator |
| POST | `/systems/{id}/arm` | Arm the system (ARMED_STAY or ARMED_AWAY) | Subscriber |
| POST | `/systems/{id}/disarm` | Disarm the system | Subscriber |
| POST | `/systems/{id}/enter-test-mode` | Enter test mode | Subscriber, MonitoringOperator |
| POST | `/systems/{id}/exit-test-mode` | Exit test mode | Subscriber, MonitoringOperator |
| POST | `/sensors` | Enroll a sensor on a system | Administrator |
| GET | `/sensors` | List sensors | Administrator, MonitoringOperator, Subscriber |
| GET | `/sensors/{id}` | Get a sensor | Administrator, MonitoringOperator, Subscriber |
| POST | `/sensors/{id}/bypass` | Bypass an enrolled sensor | Subscriber, Administrator |
| POST | `/sensors/{id}/restore` | Restore a bypassed sensor | Subscriber, Administrator |
| POST | `/sensors/{id}/remove` | Remove a sensor (terminal) | Administrator |
| POST | `/alarm-events` | Ingest an alarm signal | MonitoringOperator, Administrator |
| GET | `/alarm-events` | List alarm events | Administrator, MonitoringOperator, Subscriber |
| GET | `/alarm-events/{id}` | Get an alarm event | Administrator, MonitoringOperator, Subscriber |
| POST | `/alarm-events/{id}/route` | Route a received signal to a responder service | MonitoringOperator |
| POST | `/alarm-events/{id}/dispatch` | Order a dispatch for a routed signal | MonitoringOperator |
| POST | `/alarm-events/{id}/resolve` | Resolve a dispatched event REAL or FALSE_ALARM | MonitoringOperator |
| GET | `/dispatches` | List dispatches | Administrator, MonitoringOperator, Subscriber |
| GET | `/dispatches/{id}` | Get a dispatch | Administrator, MonitoringOperator, Subscriber |
| POST | `/dispatches/{id}/cancel` | Cancel an ordered dispatch (reverses the fee) | MonitoringOperator |
| POST | `/permits` | Issue a false-alarm permit on an account | Administrator |
| GET | `/permits` | List permits | Administrator, MonitoringOperator, Subscriber |
| GET | `/permits/{id}` | Get a permit | Administrator, MonitoringOperator, Subscriber |
| POST | `/permits/{id}/revoke` | Revoke an active permit | Administrator |
| POST | `/permits/{id}/expire` | Expire an active permit | Administrator |
| GET | `/fines` | List fines | Administrator, MonitoringOperator, Subscriber |
| GET | `/fines/{id}` | Get a fine | Administrator, MonitoringOperator, Subscriber |
| POST | `/fines/{id}/pay` | Pay an assessed fine | Subscriber, Administrator |
| POST | `/fines/{id}/waive` | Waive an assessed fine | Administrator |
| POST | `/_clock/set` | Set the server's logical UTC clock (test-driving) | Administrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_ACCOUNT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TEST_MODE_ACTIVE` | 409 |
| `ERR_COMMUNICATOR_OFFLINE` | 409 |
| `ERR_CELLULAR_NOT_ENTITLED` | 422 |
| `ERR_SENSOR_LIMIT_EXCEEDED` | 409 |
| `ERR_DUPLICATE_ZONE` | 409 |
| `ERR_PERMIT_ALREADY_ACTIVE` | 409 |
| `ERR_DUPLICATE_PERMIT_NUMBER` | 409 |
| `ERR_OPEN_DISPATCH` | 409 |
| `ERR_TEST_MODE_ALREADY_OPEN` | 409 |
| `ERR_SIGNAL_DEBOUNCED` | 409 |
