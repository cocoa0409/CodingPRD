# Medical Alert PERS API — Product Requirements Document

## 1. Introduction

Personal Emergency Response Systems (PERS) sit at the intersection of life-safety operations and recurring-revenue billing. A vulnerable subscriber wears a pendant or wristband, falls, presses a button, and within seconds a monitoring center must triage the signal, walk a tree of emergency contacts, and — when warranted — dispatch 911 to the subscriber's home. This document specifies the API for such a service in the spirit of Life Alert and Bay Alarm Medical: device and fall-detection enrollment, monitoring-plan tiers, the alarm-signal-to-response protocol, the contact-tree escalation and dispatch flow, periodic device and battery-health testing, false-alarm handling, contract lifecycle with proration and early-termination fees, and the eventual return and inspection of leased equipment.

The platform is organized around the **Subscriber** as the account hub. Each subscriber holds a **Contract** against a **MonitoringPlan**, enrolls one or more **Device** units, and curates an ordered **EmergencyContact** tree. When a device raises an **AlarmEvent**, a call-center operator drives it through a branching response protocol recorded as a sequence of **DispatchAction** steps. Two operational dimensions — billing and service — evolve independently on every contract, and several time-sensitive behaviors (battery decay, test-due deadlines, paid-through cycles, return deadlines) are governed by a server-controlled logical clock rather than wall-clock time, so that the benchmark is fully deterministic and reproducible.

Because the system mediates emergencies, the requirements lean heavily toward never stranding a live, monitored device, toward strictly ordered escalation, and toward precise, auditable money handling. The sections below define the global contracts every endpoint honors (Section 2) and then the business workflows that distinguish this domain (Section 3), before cataloguing the endpoint surface (Section 4) and the error vocabulary (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across the entire API. The API is mounted under the `/pers` path prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The single test-support clock endpoint is no exception — it too requires both headers even though it carries no domain payload. Once a caller is authenticated, the system checks whether their role is permitted to perform the requested operation; a role acting outside its remit is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles, spelled precisely as follows: `PlatformAdmin`, `Subscriber`, and `CallCenterAgent`. No role is a superset of another — each owns a distinct slice of the workflow, and they cooperate as peers rather than in a hierarchy.

- A `PlatformAdmin` is an operator who configures plan tiers, manages contracts and their billing, runs the equipment-return pipeline, schedules call-center coverage, and drives the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and act on it but does not compare it to any entity's `id`.

- A `Subscriber` is the account holder who registers, enrolls, and tests their own devices, manages their own contact tree, schedules monitoring holds, requests cancellation of their own contract, and may raise their own alarms. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Subscriber`; ownership checks on any resource that references a subscriber compare that resource's `subscriber_id` (directly, or transitively through the owning contract or device) to `X-User-ID`. A subscriber who attempts to act on a contract, device, or contact they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

- A `CallCenterAgent` is a monitoring-center operator who claims alarms and records dispatch steps through the response protocol. When `X-User-Role` is `CallCenterAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — for example, it is written to an alarm's `assigned_agent_id` when an agent claims the alarm, and an agent's on-call coverage is keyed to it via `agent_user_id` on a shift — but it is never compared to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless an endpoint's description states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. (Two list endpoints are explicit exceptions described in Section 3 and noted in their endpoint descriptions: emergency contacts list by ascending `priority_rank`, and dispatch actions list by ascending `recorded_at`.) Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Identifiers, Timestamps, and Resource Versioning

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix. Resources also carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits captured when the resource is first created. Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by exactly one on each mutation. The `version` field is the basis for optimistic concurrency control (Section 2.6).

One entity is deliberately leaner: a **DeviceTest** is an immutable record of a single self-test. It carries only `id` and `created_at`; it has no `updated_at` and no `version`, because it is never mutated after it is written.

### 2.5. Cascading State Consistency

Several operations on a contract drive state changes that must propagate to the contract's devices, and those propagated changes may in turn ripple one hop further. Whenever a parent contract changes its service dimension, every affected child device is transitioned in lockstep, each device's `updated_at` is refreshed, and each device's `version` is incremented. Where a device transition itself recomputes derived timing (for example, when a device becomes `ACTIVE` and the test schedule is reset), that second hop is part of the same atomic operation. The contract that initiated the cascade likewise refreshes its own `updated_at` and increments its own `version`. The specific cascades — activation pushing enrolled devices to `ACTIVE`, suspension pushing active devices to `SUSPENDED`, reinstatement pulling them back to `ACTIVE`, and finalization deactivating every device and opening one equipment return per device — are detailed with their triggering workflows in Section 3.

### 2.6. Optimistic Concurrency Control on Cancellation

Requesting cancellation of a contract is the one operation guarded by optimistic concurrency control. The cancellation-request operation requires `expected_contract_version` as a mandatory field in its body, carrying the `version` of the contract the client last observed. If `expected_contract_version` does not equal the contract's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because a contract's `version` legitimately advances between the client's read and its cancellation request — a billing action such as marking past-due or recording a payment, or a suspend/reinstate cascade, each bump `version` — and the refund and fee computation must be made against the precise state the client actually saw rather than a state that has since moved on. No other endpoint accepts or requires a version field; only the cancellation request performs this check.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Where a calculation divides or scales an amount, the result is rounded using the round-half-up method to a whole number of cents. The two places rounding is applied — the per-day refund rate and the grade-C damage fee — are specified precisely with their workflows in Section 3; in both, rounding is performed at the indicated intermediate step rather than only at the end, and the order is load-bearing.

### 2.8. Logical Clock and Time-Dependent Rules

Every time-dependent rule in the system reads a server-controlled logical clock rather than wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-set call it holds this default and never falls back to real time. A `PlatformAdmin` may advance or set the clock by supplying a target instant as `to_iso8601`. All deadlines, due dates, paid-through boundaries, battery-test windows, shift coverage, and hold buffers are evaluated against whatever instant the clock currently holds.

### 2.9. Validation Ordering and Path Resolution

When a request could fail more than one check, the checks are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: a missing or malformed header yields `ERR_UNAUTHENTICATED`. Role permission is checked next, yielding `ERR_FORBIDDEN`. The system then resolves every referenced resource — both path identifiers and foreign-key fields in the body — validating them left-to-right in the order they appear in the path, and returns `ERR_NOT_FOUND` for the first identifier that does not resolve to an existing resource. For subscriber-scoped writes, resource ownership is then enforced (`ERR_NOT_RESOURCE_OWNER`). Only after these gates does the system evaluate state-machine legality (`ERR_INVALID_STATE`) and the remaining domain rules. Field-level input validity — required fields present, enum values in range, integers within their bounds, amounts non-negative, and interval ordering — is the lowest-priority family and surfaces as `ERR_INVALID_REQUEST`. The remaining domain-specific orderings are stated alongside the workflows they guard in Section 3.

## 3. Business Logic & Workflows

### 3.1. Plan Configuration and the Subscriber Account

A `PlatformAdmin` seeds the catalogue by creating **MonitoringPlan** tiers. A plan is created with a `tier` — one of `BASIC`, `PLUS`, or `PREMIUM` — together with its `monthly_fee_cents` (the base recurring monitoring fee, which must be zero or greater), a `fall_detection_addon_cents` surcharge (the additional monthly cents charged when fall detection is enabled on a device, also zero or greater), the `included_test_interval_days` mandating the number of days between device self-tests for the tier (at least 1), a `response_sla_seconds` ceiling (the maximum seconds the call center may take to assign an agent before an SLA breach, at least 1), an `early_termination_fee_cents` flat fee (zero or greater), and a `min_commitment_months` window (zero or greater). The `tier` must be unique among non-archived plans; a duplicate tier among live plans is rejected with `ERR_DUPLICATE`. Each plan also carries an `archived` flag that begins `false`; archiving a plan flips `archived` to `true` so it can no longer back a new contract, while leaving contracts already pinned to it untouched.

A subscriber account is created by a `PlatformAdmin` with a `full_name`, an `email`, a `residence_address`, and a `phone`. The `email` must be unique across subscribers; a collision is rejected with `ERR_DUPLICATE`. The `residence_address` is significant beyond billing: it is the dispatch location communicated to 911, and the `phone` is the primary number the call center dials first when an alarm is raised. Each subscriber carries a system-managed `status` that is set to `ACTIVE` on creation and is the only value that field takes in this system.

### 3.2. Contract Activation and the Two State Dimensions

A `PlatformAdmin` opens a **Contract** for a subscriber against a plan by supplying the `subscriber_id` and the `plan_id`. A new contract begins with its `service_status` at `PENDING_ACTIVATION` and an independent `billing_status` at `CURRENT`. These two dimensions live on the same contract row and evolve separately: a contract awaiting cancellation can still be `CURRENT` or `PAST_DUE` on its billing dimension, and a `SUSPENDED` contract is suspended for non-payment yet may later return to `CURRENT` once reinstated. The `service_status` ranges over `PENDING_ACTIVATION`, `ACTIVE`, `SUSPENDED`, `CANCELLATION_REQUESTED`, and `CANCELLED`; the `billing_status` ranges over `CURRENT`, `PAST_DUE`, and `WRITTEN_OFF`.

Activation is the pivotal event. A `PlatformAdmin` activates a contract, which is permitted only when the contract's `service_status` is `PENDING_ACTIVATION`, the plan referenced by `plan_id` is not archived, at least one device under the contract is in `ENROLLED` status, and the owning subscriber's `status` is `ACTIVE`; failing the state precondition yields `ERR_INVALID_STATE`. Activation moves `service_status` to `ACTIVE` and, crucially, **pins** the plan's commercial terms onto the contract so that later edits to the plan never disturb an active contract: it copies `monthly_fee_cents` into `pinned_monthly_fee_cents`, `fall_detection_addon_cents` into `pinned_addon_cents`, `early_termination_fee_cents` into `pinned_etf_cents`, and `min_commitment_months` into `pinned_min_commitment_months`. It sets `activated_at` to the current clock instant and sets `paid_through_at` to one month after the current instant, reflecting that the first monitoring cycle is prepaid. As a cascade, every `ENROLLED` device under the contract transitions to `ACTIVE`; and for each device so activated, the system sets that device's `last_test_at` to the current instant and recomputes its `next_test_due_at`. The contract's `version` increments by one.

A contract also accumulates several computed money fields that stay at their defaults until cancellation: `refund_cents` (default 0), `etf_charged_cents` (default 0), and `outstanding_balance_cents`, the running net amount owed by the subscriber when positive or owed to the subscriber when negative. The `cancellation_effective_at` instant is likewise populated only at cancellation request. These fields are described with the cancellation workflow in Section 3.7.

### 3.3. Billing: Past-Due, Payment, and Write-Off

The billing dimension is driven entirely by a `PlatformAdmin` and never touches `service_status` directly. Marking a contract past-due is permitted only when `billing_status` is `CURRENT` and the clock has advanced strictly beyond `paid_through_at`; attempting it before that instant is rejected with `ERR_TEMPORAL_NOT_DUE`, and attempting it from a non-`CURRENT` billing state yields `ERR_INVALID_STATE`. The action sets `billing_status` to `PAST_DUE` and increments the contract `version`.

Recording a payment is permitted only when `billing_status` is `PAST_DUE`; it clears the dimension back to `CURRENT`, advances `paid_through_at` by one month, and increments `version`. Note that recording payment does not by itself restore monitoring — restoring a suspended contract to service is the separate reinstatement action in Section 3.4. Writing off a balance is permitted only when `billing_status` is `PAST_DUE` and `service_status` is already `CANCELLED`; it moves `billing_status` to its terminal `WRITTEN_OFF` and increments `version`. Any of these billing actions from the wrong state surfaces `ERR_INVALID_STATE`.

### 3.4. Suspension and the Reinstatement Cycle

When a subscriber falls behind, a `PlatformAdmin` may suspend monitoring. Suspension is permitted only when `service_status` is `ACTIVE` and `billing_status` is `PAST_DUE`; from any other combination the request is rejected with `ERR_INVALID_STATE`. Suspending sets `service_status` to `SUSPENDED`, cascades every `ACTIVE` device under the contract to `SUSPENDED`, and increments the contract `version`. A suspended device will not accept new alarm signals, which is the safety-relevant consequence discussed in Section 3.8.

Reinstatement reverses this. A `PlatformAdmin` may reinstate only when `service_status` is `SUSPENDED` and `billing_status` is `CURRENT` — meaning the past-due balance must have been cleared first via the payment action of Section 3.3. Reinstating sets `service_status` back to `ACTIVE`, cascades every `SUSPENDED` device under the contract back to `ACTIVE`, and increments `version`. Because a contract can travel `ACTIVE → SUSPENDED → ACTIVE` repeatedly, the service dimension is non-linear, and each traversal bumps `version` — one of the reasons the cancellation request guards itself with optimistic concurrency control (Section 2.6).

### 3.5. Device Registration, Testing, and Enrollment

A **Device** is registered — by either a `PlatformAdmin` or the owning `Subscriber` — under a contract by supplying the `contract_id`, a `serial_number`, a `device_type`, and optionally a `fall_detection_enabled` flag (default `false`). The `serial_number` is unique across all devices; a duplicate is rejected with `ERR_DUPLICATE`. The `device_type` is one of `PENDANT`, `WRISTBAND`, `MOBILE_GPS`, or `HOME_BASE`. A new device begins in `REGISTERED` status; its lifecycle status ranges over `REGISTERED`, `ENROLLED`, `ACTIVE`, `NEEDS_TEST`, `SUSPENDED`, and `DEACTIVATED`. The device also tracks `battery_pct` (last reported battery percentage, an integer from 0 to 100, default 100), a derived `battery_health` classification, `last_test_at` (the instant of the most recent passing test), `next_test_due_at` (the computed next-test deadline), and `open_alarm_count` (the number of non-terminal alarms currently open against it, default 0).

Before a device can be enrolled it must pass a self-test. A `Subscriber` submits a **DeviceTest** against their device, supplying the `reported_battery_pct` (an integer from 0 to 100) and a boolean `signal_ok`. The test's `result` is computed as follows: signal failure dominates. If `signal_ok` is false, the result is `FAIL_SIGNAL`. Otherwise, if `reported_battery_pct` is below 20, the result is `FAIL_BATTERY` — note that a reading of exactly 20 is not a failure and yields `PASS`, so the boundary is strict. Otherwise the result is `PASS`. Every test, whether it passes or fails, records its own `tested_at` instant and always copies `reported_battery_pct` onto the device's `battery_pct` and recomputes `battery_health`; only the status and timing changes below are gated on a `PASS`. This deliberate split keeps a `CRITICAL` battery classification reachable even though a low-battery test fails.

Battery classification (`battery_health`) is derived from `battery_pct` and is one of `GOOD`, `LOW`, or `CRITICAL`. A percentage of 40 or more is `GOOD`; a percentage that is at least 20 but below 40 is `LOW`; anything below 20 is `CRITICAL`. (Both cutoffs are inclusive on their lower bound, in contrast to the strict comparison used for the test-result battery failure.)

A `Subscriber` enrolls a `REGISTERED` device, which requires that the device's status is `REGISTERED`, that a passing test (`result` equal to `PASS`) already exists for the device, and — if `fall_detection_enabled` is true — that the `device_type` is one of `PENDANT`, `WRISTBAND`, or `MOBILE_GPS`, since a `HOME_BASE` unit cannot perform fall detection. A missing passing test, or fall detection requested on a non-fall-capable device type, is rejected with `ERR_ENROLL_PRECONDITION`; attempting to enroll a device that is not in `REGISTERED` status yields `ERR_INVALID_STATE`. A successful enroll moves the device to `ENROLLED` and increments its `version`.

Once a contract activates, its enrolled devices become `ACTIVE` (Section 3.2). An active device drifts toward needing a test: whenever the clock reaches or passes `next_test_due_at`, the next alarm-create or test-submit against that device first auto-transitions it from `ACTIVE` to `NEEDS_TEST` and increments its `version`. A `NEEDS_TEST` device is returned to `ACTIVE` by submitting a test whose `result` is `PASS`; that transition sets `last_test_at` to the current instant, recomputes `next_test_due_at` as `last_test_at` plus the plan's `included_test_interval_days`, and increments `version`. The `ACTIVE ↔ NEEDS_TEST` pair forms a maintenance cycle. Importantly for life-safety, a `NEEDS_TEST` device still raises alarms, but its presence blocks contract finalization until it is tested back to `ACTIVE` (Section 3.7).

### 3.6. The Contact Tree

Each subscriber curates an ordered escalation tree of **EmergencyContact** entries. A `Subscriber` adds a contact by supplying the `subscriber_id`, the contact's `name`, `phone`, a `relationship` (one of `CAREGIVER`, `FAMILY`, `NEIGHBOR`, or `PHYSICIAN`), and a `priority_rank`. The rank determines call order — a lower number is dialed earlier — and must be at least 1 and unique within a subscriber. Optionally the caller may supply `escalates_to_contact_id`, a pointer to the next-fallback contact to try when this one does not answer (null for the last leaf, which is the default), and a `can_authorize_911` flag (default `false`) marking whether this contact may authorize a 911 dispatch on the subscriber's behalf. Each contact also carries a system-managed `active` flag (default `true`); a deactivated contact is skipped during escalation.

The contact tree is validated structurally: `priority_rank` must be unique within the subscriber, and `escalates_to_contact_id` must reference an existing contact belonging to the same subscriber and must not introduce a cycle in the escalation chain. A duplicate rank, an escalation target owned by a different subscriber, or an escalation cycle is rejected with `ERR_CONTACT_TREE_INVALID`. A `Subscriber` may update an existing contact's `priority_rank`, `escalates_to_contact_id`, `can_authorize_911`, or `active` flag; the update increments the contact's `version` and is subject to the same structural validation.

### 3.7. Cancellation, Proration, and Finalization

Cancellation is initiated by the `Subscriber` and is the one OCC-guarded operation: the request carries `expected_contract_version`, which must equal the contract's current `version` or the request is rejected with `ERR_STALE_VERSION` (Section 2.6). Cancellation may be requested from either `ACTIVE` or `SUSPENDED` service status; from any other state the request yields `ERR_INVALID_STATE`. In both cases the request moves `service_status` to `CANCELLATION_REQUESTED`, computes the refund and early-termination figures, sets `outstanding_balance_cents` to `etf_charged_cents` minus `refund_cents`, and increments `version`. The two starting states differ in how the effective date and the refund are computed.

The early-termination fee is the same in both cases: `etf_charged_cents` is set to the pinned `pinned_etf_cents` when the current clock instant is before `activated_at` plus `pinned_min_commitment_months` months — that is, the subscriber is still inside the minimum commitment window — and is otherwise 0.

The refund computation, **prorated_cancellation_refund**, first establishes the applicable monthly amount: it is `pinned_monthly_fee_cents`, plus `pinned_addon_cents` only if at least one device under the contract has `fall_detection_enabled` set, otherwise plus nothing. The prepaid cycle is the whole month ending at `paid_through_at`; its start is `paid_through_at` minus one month, and the cycle's total days is the count of calendar days in that interval.

- When cancellation is requested from `ACTIVE` (the STANDARD variant), service continues to the end of the cycle the subscriber has already paid for, so no unused days are refunded: `refund_cents` is 0, and `cancellation_effective_at` is set to `paid_through_at`.
- When cancellation is requested from `SUSPENDED` (the IMMEDIATE variant), service has already stopped, so the unused portion is refunded and `cancellation_effective_at` is set to the current clock instant. The unused days are the count of calendar days from the current instant to `paid_through_at` (zero if the clock is already at or past `paid_through_at`). The per-day rate is the applicable monthly amount divided by the cycle's total days, rounded half-up to a whole number of cents; this rounded per-day rate is then multiplied by the unused days to give `refund_cents`. The rounding is applied to the per-day rate first and the multiplication second — this per-line-item-then-multiply order is load-bearing and is not the same as rounding only the final product.

Finalizing a cancellation is a `PlatformAdmin` action permitted only when `service_status` is `CANCELLATION_REQUESTED` and the clock has reached or passed `cancellation_effective_at`; a premature attempt is rejected with `ERR_TEMPORAL_NOT_DUE`, and a wrong-state attempt yields `ERR_INVALID_STATE`. Life-safety dominates here: finalization is blocked while any device under the contract is still `ACTIVE` or `NEEDS_TEST`, or while any alarm under any of the contract's devices is in a non-terminal status, with rejection code `ERR_LIVE_MONITORING_BLOCKS_CANCEL` — the system must never strand a live monitored device. When permitted, finalization sets `service_status` to `CANCELLED`, cascades every not-yet-`DEACTIVATED` device under the contract to `DEACTIVATED`, opens one **EquipmentReturn** per deactivated device (each starting `INITIATED` with a `due_back_at` set to 14 days after the current instant), and increments the contract `version`.

### 3.8. Raising and Triaging Alarms

A `Subscriber` or a `CallCenterAgent` raises an alarm on a device by supplying the `signal_type`, one of `MANUAL_BUTTON`, `FALL_DETECTED`, `BATTERY_CRITICAL`, or `PERIODIC_CHECKIN_MISSED`. An alarm may only be raised on a device whose contract `service_status` is `ACTIVE`; a suspended or cancelled contract does not monitor, so the attempt is rejected with `ERR_CONTRACT_NOT_MONITORING`. A new alarm begins in `SIGNAL_RECEIVED` status; its lifecycle ranges over `SIGNAL_RECEIVED`, `AGENT_ASSIGNED`, `CONTACTING_SUBSCRIBER`, `ESCALATING`, `DISPATCHED_911`, `RESOLVED_OK`, and `FALSE_ALARM`. The alarm records `signal_received_at` at the current instant, increments the device's `open_alarm_count`, and — if the device is `ACTIVE` and the clock has reached `next_test_due_at` — first auto-flags the device `NEEDS_TEST` as described in Section 3.5. An alarm also tracks `assigned_agent_id`, `agent_assigned_at`, `resolved_at`, `sla_breached` (default false), `current_escalation_rank` (default 0, the rank of the contact currently being attempted during escalation), and `dispatch_count` (default 0).

At creation the alarm's triage `priority` is computed — one of `ROUTINE`, `ELEVATED`, or `CRITICAL` — by the **alarm_priority_score** rule from three inputs on the device. A base weight is taken from the signal type: `MANUAL_BUTTON` contributes 40, `FALL_DETECTED` contributes 60, `BATTERY_CRITICAL` contributes 20, and `PERIODIC_CHECKIN_MISSED` contributes 50. A bonus of 30 is added only when the device has `fall_detection_enabled` set and the signal type is `FALL_DETECTED`. A further bonus of 25 is added only when the device's `battery_health` is `CRITICAL`. The three terms are summed into a score. The priority tier is then chosen non-linearly: a score of 80 or more is `CRITICAL`; otherwise a score of 50 or more is `ELEVATED`; otherwise it is `ROUTINE`. Each cutoff is inclusive (the comparison is "at least").

### 3.9. Agent Assignment, Shift Coverage, and the SLA

Alarms are claimed by a `CallCenterAgent`. Assignment is permitted only when the alarm is in `SIGNAL_RECEIVED` status (otherwise `ERR_INVALID_STATE`) and only when the acting agent has on-call coverage: a `SCHEDULED` **AgentShift** whose `agent_user_id` equals the agent's `X-User-ID` must cover the current clock instant, meaning `starts_at` is at or before the current instant and the current instant is strictly before `ends_at`. With no covering shift, assignment is rejected with `ERR_NO_SHIFT_COVERAGE`. A successful assignment sets `assigned_agent_id` to the agent's `X-User-ID`, sets `agent_assigned_at` to the current instant, recomputes `sla_breached`, moves the alarm to `AGENT_ASSIGNED`, and increments the alarm `version`.

The SLA check, **sla_breach_check**, measures the whole-second elapsed time between `agent_assigned_at` and `signal_received_at` and sets `sla_breached` to true only when that elapsed time is strictly greater than the plan's `response_sla_seconds`. Equality is not a breach — an elapsed time exactly equal to `response_sla_seconds` leaves `sla_breached` false.

A `PlatformAdmin` schedules on-call coverage by creating an agent shift with an `agent_user_id`, a `starts_at`, and an `ends_at`; `ends_at` must be strictly after `starts_at`. A shift begins `SCHEDULED` and its status is either `SCHEDULED` or `CANCELLED`. Coverage intervals are half-open `[starts_at, ends_at)`: two `SCHEDULED` shifts for the same agent may be exactly adjacent (one shift's `ends_at` equal to the next's `starts_at`) but must not otherwise overlap. A new shift whose half-open interval intersects an existing `SCHEDULED` shift for the same `agent_user_id` is rejected with `ERR_SHIFT_OVERLAP`. A `PlatformAdmin` may cancel a `SCHEDULED` shift, which moves it to `CANCELLED`, frees its interval for new shifts, and increments its `version`; a cancelled shift no longer provides assignment coverage.

### 3.10. The Dispatch Protocol: Contacting, Escalating, and Dispatching

Once an alarm is assigned, the owning `CallCenterAgent` drives it through a branching response protocol, recording each step as a **DispatchAction**. Every dispatch step carries an `action_type` (one of `CALL_SUBSCRIBER`, `CALL_CONTACT`, `DISPATCH_911`, `MARK_FALSE_ALARM`, or `RESOLVE_OK`), an `outcome` (one of `ANSWERED`, `NO_ANSWER`, `DISPATCHED`, `CONFIRMED_OK`, or `CONFIRMED_FALSE`), and optionally a `target_contact_id` (the contact dialed for a `CALL_CONTACT` step, null otherwise); the step also records the parent `alarm_event_id` and its `recorded_at` instant. Every dispatch step requires that the acting agent is the alarm's assigned agent — `assigned_agent_id` must equal `X-User-ID` — or the step is rejected with `ERR_NOT_ASSIGNED_AGENT`. Each recorded step increments the alarm's `dispatch_count` and the alarm `version`; steps that drive the alarm to a terminal status also set `resolved_at` to the current instant and decrement the device's `open_alarm_count` by one.

The agent first calls the subscriber. From `AGENT_ASSIGNED`, a `CALL_SUBSCRIBER` step moves the alarm to `CONTACTING_SUBSCRIBER`. From `CONTACTING_SUBSCRIBER` the event forks:

- A `RESOLVE_OK` step with `outcome` `CONFIRMED_OK` confirms the subscriber is well and moves the alarm to terminal `RESOLVED_OK`.
- A `MARK_FALSE_ALARM` step with `outcome` `CONFIRMED_FALSE` records an accidental press and moves the alarm to terminal `FALSE_ALARM`. The false-alarm branch fires no 911 dispatch and no contact escalation — it is a distinct outcome from `RESOLVED_OK` and shares only the terminal bookkeeping (set `resolved_at`, decrement `open_alarm_count`).
- A `CALL_SUBSCRIBER` step with `outcome` `NO_ANSWER` means the subscriber could not be reached and moves the alarm to `ESCALATING`. This requires the subscriber to have at least one active contact. Entering escalation sets `current_escalation_rank` to the `priority_rank` of the lowest-ranked active contact for the subscriber.
- When the alarm's `priority` is `CRITICAL`, the agent may bypass the contact tree entirely and record a `DISPATCH_911` step with `outcome` `DISPATCHED` directly from `CONTACTING_SUBSCRIBER`, moving the alarm to terminal `DISPATCHED_911`.

During `ESCALATING`, the agent walks the contact tree one hop at a time. A `CALL_CONTACT` step must target the active contact whose `priority_rank` equals the alarm's `current_escalation_rank`; a step that targets any other contact, or an inactive one, is rejected with `ERR_ESCALATION_ORDER`. When that contact does not answer (`outcome` `NO_ANSWER`) and they have a non-null `escalates_to_contact_id` pointing to an active contact, the alarm remains `ESCALATING` and `current_escalation_rank` advances to the `priority_rank` of the contact referenced by that fallback pointer — a self-loop that walks the tree one contact per unanswered call. From `ESCALATING`, two terminal exits are possible: a contact answers and the agent records a `RESOLVE_OK` step, moving the alarm to `RESOLVED_OK`; or the agent records a `DISPATCH_911` step with `outcome` `DISPATCHED`, moving the alarm to `DISPATCHED_911`.

A 911 dispatch is gated for life-safety. A `DISPATCH_911` step is permitted only when the alarm's `priority` is `CRITICAL`, or when an answering contact authorized it — that is, a `CALL_CONTACT` dispatch action with `outcome` `ANSWERED` exists whose targeted contact has `can_authorize_911` set to true. A `DISPATCH_911` step that satisfies neither condition is rejected with `ERR_911_NOT_AUTHORIZED`. The three terminal alarm statuses are `RESOLVED_OK`, `FALSE_ALARM`, and `DISPATCHED_911`; reaching any of them is what unblocks contract finalization in Section 3.7.

### 3.11. Equipment Return and Damage Assessment

When a contract is finalized, one equipment return is opened per deactivated device, each referencing both its `contract_id` and the `device_id` being returned and starting in `INITIATED`. A return's status ranges over `INITIATED`, `KIT_SENT`, `RECEIVED`, `INSPECTED_OK`, `DAMAGED`, and `CLOSED`. A `PlatformAdmin` drives the pipeline: sending the return kit moves an `INITIATED` return to `KIT_SENT`; marking the kit received moves a `KIT_SENT` return to `RECEIVED` and stamps `received_at` with the current instant. Each transition increments the return's `version`, and a transition attempted from the wrong status yields `ERR_INVALID_STATE`.

Inspection records the `condition_grade` — one of `A`, `B`, `C`, or `UNRETURNED` (null until inspection). From `RECEIVED`, a grade of `A` or `B` moves the return to `INSPECTED_OK` and sets `damage_fee_cents` to 0. A grade of `C` moves the return to `DAMAGED` and computes a damage fee. Separately, an `UNRETURNED` grade may be recorded from `INITIATED` or `KIT_SENT` to mark equipment that was never returned, but only once the clock has passed `due_back_at`; a premature `UNRETURNED` inspection is rejected with `ERR_TEMPORAL_NOT_DUE`. The `UNRETURNED` path also moves the return to `DAMAGED`.

The damage fee, **equipment_damage_fee**, starts from a replacement cost that depends on the device's `device_type`: a `PENDANT` is 8000 cents, a `WRISTBAND` is 9000 cents, a `MOBILE_GPS` is 18000 cents, and a `HOME_BASE` is 12000 cents. For a grade-`C` (DAMAGED) inspection, the fee is the replacement cost multiplied by one half, rounded half-up to whole cents. For an `UNRETURNED` inspection, the fee is the full replacement cost. In either damaged outcome the computed `damage_fee_cents` is added to the owning contract's `outstanding_balance_cents` — a cross-aggregate effect that reaches across from the return back to its contract. Finally, a `PlatformAdmin` closes a return that is in `INSPECTED_OK` or `DAMAGED`, moving it to terminal `CLOSED` and incrementing its `version`.

### 3.12. Monitoring Holds

A `Subscriber` may pause monitoring on one of their devices for a planned absence such as a hospital stay or travel by scheduling a **MonitoringHold** on the device with a `device_id`, a `starts_at`, and an `ends_at`; `ends_at` must be strictly after `starts_at`. A hold begins `SCHEDULED` and its status is either `SCHEDULED` or `CANCELLED`. Hold windows are half-open `[starts_at, ends_at)`, but unlike agent shifts they require a buffer: two `SCHEDULED` holds on the same device must be separated by at least 7 days. A new hold is rejected with `ERR_HOLD_OVERLAP` unless its start is at least 7 days after an existing hold's `ends_at`, or its end plus 7 days is at or before that existing hold's `starts_at` — in other words, it is rejected whenever its window comes within 7 days of any existing scheduled hold on that device. This buffered semantics is deliberately distinct from the zero-buffer adjacency allowed for agent shifts. A `Subscriber` may cancel a `SCHEDULED` hold, moving it to `CANCELLED`, which frees its interval (and the surrounding buffer) for new holds and increments the hold's `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions — return a `200 OK` status code. The single exception is recording a dispatch action, which appends a new `DispatchAction` record and therefore returns `201 Created`. All paths are mounted under `/pers`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pers/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/pers/monitoring-plans` | Create a monitoring plan tier | PlatformAdmin |
| GET | `/pers/monitoring-plans` | List monitoring plans (paginated) | PlatformAdmin, Subscriber |
| GET | `/pers/monitoring-plans/{id}` | Get a monitoring plan | PlatformAdmin, Subscriber |
| POST | `/pers/monitoring-plans/{id}/archive` | Archive a plan so it cannot back new contracts | PlatformAdmin |
| POST | `/pers/subscribers` | Create a subscriber account | PlatformAdmin |
| GET | `/pers/subscribers/{id}` | Get a subscriber | PlatformAdmin, Subscriber |
| POST | `/pers/contracts` | Create a contract for a subscriber on a plan | PlatformAdmin |
| GET | `/pers/contracts/{id}` | Get a contract | PlatformAdmin, Subscriber |
| GET | `/pers/contracts` | List contracts, filterable by subscriber and plan | PlatformAdmin, Subscriber |
| POST | `/pers/contracts/{id}/activate` | Activate a contract; pins fees and cascades devices | PlatformAdmin |
| POST | `/pers/contracts/{id}/suspend` | Suspend monitoring on a past-due contract | PlatformAdmin |
| POST | `/pers/contracts/{id}/reinstate` | Reinstate a suspended contract once billing is current | PlatformAdmin |
| POST | `/pers/contracts/{id}/request-cancellation` | Request cancellation; computes refund, ETF, balance | Subscriber |
| POST | `/pers/contracts/{id}/finalize-cancellation` | Finalize cancellation; deactivates devices, opens returns | PlatformAdmin |
| POST | `/pers/contracts/{id}/billing/mark-past-due` | Mark contract billing PAST_DUE | PlatformAdmin |
| POST | `/pers/contracts/{id}/billing/record-payment` | Record a payment clearing PAST_DUE | PlatformAdmin |
| POST | `/pers/contracts/{id}/billing/write-off` | Write off a cancelled, past-due balance | PlatformAdmin |
| POST | `/pers/devices` | Register a device under a contract | PlatformAdmin, Subscriber |
| GET | `/pers/devices/{id}` | Get a device | PlatformAdmin, Subscriber, CallCenterAgent |
| GET | `/pers/devices` | List devices, filterable by contract | PlatformAdmin, Subscriber, CallCenterAgent |
| GET | `/pers/contracts/{id}/devices` | List devices enrolled under a contract | PlatformAdmin, Subscriber |
| POST | `/pers/devices/{id}/enroll` | Enroll a registered device after a passing test | Subscriber |
| POST | `/pers/devices/{id}/tests` | Submit a device self-test / battery-health check | Subscriber |
| GET | `/pers/devices/{id}/tests` | List a device's tests | PlatformAdmin, Subscriber |
| POST | `/pers/emergency-contacts` | Add an emergency contact to the tree | Subscriber |
| GET | `/pers/emergency-contacts/{id}` | Get an emergency contact | PlatformAdmin, Subscriber, CallCenterAgent |
| GET | `/pers/emergency-contacts` | List emergency contacts (ordered by priority_rank ASC) | PlatformAdmin, Subscriber, CallCenterAgent |
| PATCH | `/pers/emergency-contacts/{id}` | Update an emergency contact | Subscriber |
| POST | `/pers/devices/{id}/alarms` | Raise an alarm signal from a device | Subscriber, CallCenterAgent |
| GET | `/pers/alarms/{id}` | Get an alarm event | PlatformAdmin, CallCenterAgent, Subscriber |
| GET | `/pers/alarms` | List alarms, filterable by device and status | PlatformAdmin, CallCenterAgent, Subscriber |
| GET | `/pers/devices/{id}/alarms` | List alarms raised by a device | PlatformAdmin, CallCenterAgent, Subscriber |
| POST | `/pers/alarms/{id}/assign` | Assign an alarm to the acting agent; computes SLA breach | CallCenterAgent |
| POST | `/pers/alarms/{id}/dispatch-actions` | Record a dispatch step; advances alarm status | CallCenterAgent |
| GET | `/pers/alarms/{id}/dispatch-actions` | List dispatch actions (ordered by recorded_at ASC) | PlatformAdmin, CallCenterAgent, Subscriber |
| GET | `/pers/dispatch-actions/{id}` | Get a single dispatch action | PlatformAdmin, CallCenterAgent, Subscriber |
| GET | `/pers/dispatch-actions` | List dispatch actions, filterable by alarm and contact | PlatformAdmin, CallCenterAgent, Subscriber |
| GET | `/pers/equipment-returns/{id}` | Get an equipment return | PlatformAdmin, Subscriber |
| GET | `/pers/equipment-returns` | List equipment returns, filterable by contract and device | PlatformAdmin, Subscriber |
| GET | `/pers/contracts/{id}/equipment-returns` | List equipment returns opened under a contract | PlatformAdmin, Subscriber |
| POST | `/pers/equipment-returns/{id}/send-kit` | Mail the return kit | PlatformAdmin |
| POST | `/pers/equipment-returns/{id}/mark-received` | Mark the kit received | PlatformAdmin |
| POST | `/pers/equipment-returns/{id}/inspect` | Inspect returned equipment and assess any fee | PlatformAdmin |
| POST | `/pers/equipment-returns/{id}/close` | Close an inspected/damaged return | PlatformAdmin |
| POST | `/pers/agent-shifts` | Schedule an on-call coverage shift | PlatformAdmin |
| GET | `/pers/agent-shifts/{id}` | Get an agent shift | PlatformAdmin, CallCenterAgent |
| GET | `/pers/agent-shifts` | List agent shifts, filterable by agent and status | PlatformAdmin, CallCenterAgent |
| POST | `/pers/agent-shifts/{id}/cancel` | Cancel a scheduled shift | PlatformAdmin |
| POST | `/pers/monitoring-holds` | Schedule a monitoring-suspension window on a device | Subscriber |
| GET | `/pers/monitoring-holds/{id}` | Get a monitoring hold | PlatformAdmin, Subscriber |
| GET | `/pers/monitoring-holds` | List monitoring holds, filterable by device and status | PlatformAdmin, Subscriber, CallCenterAgent |
| GET | `/pers/devices/{id}/monitoring-holds` | List monitoring holds scheduled on a device | PlatformAdmin, Subscriber, CallCenterAgent |
| POST | `/pers/monitoring-holds/{id}/cancel` | Cancel a scheduled hold | Subscriber |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_AGENT` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LIVE_MONITORING_BLOCKS_CANCEL` | 409 Conflict |
| `ERR_911_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_CONTRACT_NOT_MONITORING` | 409 Conflict |
| `ERR_ESCALATION_ORDER` | 409 Conflict |
| `ERR_NO_SHIFT_COVERAGE` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_HOLD_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_TEMPORAL_NOT_DUE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ENROLL_PRECONDITION` | 422 Unprocessable Entity |
| `ERR_CONTACT_TREE_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
