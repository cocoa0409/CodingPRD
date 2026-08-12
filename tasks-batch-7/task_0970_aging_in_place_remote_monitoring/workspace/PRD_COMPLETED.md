# Aging In Place Monitoring API — Product Requirements Document

## 1. Introduction

Families increasingly want older relatives to remain in their own homes without sacrificing safety, and monitoring providers need a platform that turns a household full of inexpensive sensors into trustworthy, actionable signals. This document specifies the Aging In Place Monitoring API: a system that provisions sensor and wearable kits, supervises their installation, ingests device telemetry, detects falls and inactivity, drives a severity-aware escalation contact tree when something goes wrong, tracks medication adherence, and packages all of it into periodic wellness reports for caregivers.

The platform serves several distinct populations at once. Field installers schedule and complete kit installations inside strict appointment windows. A 24/7 monitoring center triages alerts and escalates them down each senior's personalized contact tree until someone acknowledges. Caregivers check in, confirm doses, and review dashboards, while the seniors themselves can self-confirm through a companion app. Underneath these workflows sits a commercial layer — subscription plans with tiered features, prorated plan changes, and a billing pipeline that degrades monitoring gracefully when payments fail — and a fully deterministic logical clock so that every timeout, sweep, and window evaluation is reproducible. All endpoints are mounted under the `/v1` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the caller's operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the caller's role must appear in the endpoint's authorized role list; otherwise the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly six roles: `PlatformAdmin`, `MonitoringAgent`, `Caregiver`, `Senior`, `Installer`, and `DeviceHub`.

Three of these roles are entity-backed, meaning `X-User-ID` is the `id` of a persisted record and ownership checks compare resource foreign keys against it. When `X-User-Role` is `Caregiver`, `X-User-ID` is the `id` of the acting `Caregiver`; a caregiver may act only on resources belonging to the senior identified by that caregiver's own `senior_id`. When `X-User-Role` is `Senior`, `X-User-ID` is the `id` of the acting `Senior`, and the senior may act only on their own resources. When `X-User-Role` is `Installer`, `X-User-ID` is the `id` of the acting `Installer`, and the installer may act only on appointments whose `installer_id` matches. A violation of any of these ownership rules is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). An entity-backed caller whose `X-User-ID` does not resolve to a persisted record of the matching entity type — for example, a `Caregiver` id naming no caregiver — fails any request that requires an ownership decision with `ERR_OWNERSHIP_MISMATCH`. On list endpoints, a `Caregiver` or `Senior` caller receives only resources belonging to their own senior, and an explicit `senior_id` filter naming any other senior is likewise rejected with `ERR_OWNERSHIP_MISMATCH`.

The remaining three roles are opaque. When `X-User-Role` is `PlatformAdmin`, `MonitoringAgent`, or `DeviceHub`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow calls for attribution — for example, an acknowledgement performed by a monitoring agent leaves the alert's `acknowledged_by_caregiver_id` null — but it is never compared to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the server's logical clock (§2.4), never the host wall clock.
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
- Requests to unknown paths, and requests to known paths with an unsupported method, are answered in this same error envelope with `ERR_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped into that range rather than rejected, and a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter skips a number of items from the front of the result set and defaults to 0, with negative values clamped to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation sequence. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus `limit` is below `total_count`.

### 2.4. The Logical Clock and Scheduled Sweeps

All temporal reasoning in the system — appointment windows, dose windows, escalation timeouts, offline detection, report periods — is evaluated against a single server-side logical clock, never against wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and the server never silently falls back to the host's wall clock. A `PlatformAdmin` may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. The clock never moves backward: a `to_iso8601` earlier than the current logical clock is rejected with `ERR_INVALID_REQUEST`, while re-setting the current instant is accepted and still runs the full sweep sequence. Every device event also carries its own `observed_at` timestamp, which must not be later than the current logical clock; an event from the future is rejected with `ERR_INVALID_REQUEST`.

Advancing the clock is not a passive operation: each advance runs a fixed sequence of housekeeping sweeps, and the order of those sweeps is pinned. First, devices that have gone silent are marked offline. Second, upcoming medication doses are materialized for the next 48 hours. Third, doses whose confirmation windows have closed are marked missed, which may cascade into streaks and alerts. Fourth, pending alert notifications are checked for timeout, driving escalation or exhaustion. Fifth, inactivity is detected. Sixth, check-in compliance is evaluated. Seventh and last, appointments whose windows have passed unanswered are marked as no-shows. Battery threshold checks are the one exception to this ordering: they run at telemetry ingest time, not during the sweep. The details of each sweep step live with the relevant workflows in §3.

### 2.5. Common Resource Properties

Most resources in the system — `Senior`, `SubscriptionPlan`, `Subscription`, `SensorKit`, `Device`, `Installer`, `InstallAppointment`, `Caregiver`, `ContactTreeEntry`, `Alert`, `MedicationSchedule`, and `WellnessReport` — share a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation.

Four event-like resources are deliberately lighter: `SensorEvent`, `AlertNotification`, `DoseEvent`, and `CheckIn` carry only `id` and `created_at`. Both `updated_at` and `version` are absent on these four, and no endpoint mutates them after creation.

### 2.6. Monitoring Posture, Risk Tiering, and Alert Gating

Each senior's `monitoring_posture` is a computed reflection of their subscription's service dimension — the most recently created subscription's, when several exist: it reads `ACTIVE` when the subscription's `service_status` is `ACTIVE`, `DEGRADED` when the subscription is `SUSPENDED`, and `INACTIVE` in every other case (including a freshly registered senior whose subscription is still `PROVISIONING`, a `CANCELLED` one, and a senior with no subscription at all). Posture is a safety gate on autonomous alerting: while a senior's posture is `DEGRADED` or `INACTIVE`, no new non-`CRITICAL` alerts are created or notified for that senior — the triggering telemetry or sweep evidence is still recorded, but the alert itself is suppressed. `CRITICAL` alerts, such as falls, bypass this gate entirely, and so do alerts raised manually by a `MonitoringAgent` (§3.5), which are created and notified at any severity regardless of posture.

A second derived field, `open_alert_count`, tallies the senior's alerts currently in `RAISED`, `NOTIFYING`, `ESCALATED`, or `ACKNOWLEDGED` status; it increments when such an alert opens and decrements when one resolves or is marked a false alarm. A third derived field, `risk_tier`, reads `ELEVATED` when the senior has any open `CRITICAL` alert or any `ACTIVE` `CRITICAL` medication schedule whose `missed_streak` has reached 3, and `STANDARD` otherwise. All three fields are maintained by the system and are never set directly by clients.

### 2.7. Money, Scores, and Rounding Discipline

All monetary amounts are integer cents; the system never uses fractional cents. Plan-change proration (§3.2) rounds each credit or charge line independently — rounding half up to the nearest whole cent — and only then sums the rounded lines. This per-line-then-sum order is pinned: summing unrounded lines and rounding once can differ from the pinned result by a cent, and implementations must reproduce the pinned behavior. Wellness scores (`activity_score`, `adherence_pct`, `device_health_pct`, `wellness_index`) are numbers between 0 and 100 carried to exactly one decimal place, rounded half up; each score is rounded exactly once, at the end of its computation. Battery percentages are integers from 0 to 100 with inclusive threshold comparisons, as detailed in §3.4.

### 2.8. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and only these two take a version field.

Creating a medication schedule requires the request to carry `expected_senior_version`, holding the `version` of the target `Senior` as the client last observed it. If the senior's current `version` no longer matches — for instance because another writer has since created a schedule for the same medication, legitimately superseding the prior `ACTIVE` one — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a view of the senior it has not re-read.

Regenerating a wellness report similarly requires `expected_report_version` matching the target `WellnessReport`'s current `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client never silently discards another writer's regeneration. Endpoints not named here do not accept a version field at all — one supplied anyway is ignored, as is any other body field an endpoint does not use; unknown fields are never rejected.

### 2.9. Validation Pipeline and Resource Resolution

Every request passes through a uniform validation pipeline, and the stages run in a fixed order. Authentication comes first: header presence and role recognition, then membership of the caller's role in the endpoint's authorized list. Next the request body is checked for well-formedness — every required field present, every type correct — with violations rejected as `ERR_INVALID_REQUEST` — a missing, unparsable, or non-object JSON body is itself such a violation wherever the endpoint requires a body; when the offending content is an enum field carrying an undeclared member, the rejection is specifically `ERR_INVALID_ENUM`, as is an undeclared member carried by an enum-valued query parameter on a list endpoint. Only after the body parses does the system resolve identifiers: path-template identifiers are validated strictly left to right, so a request naming two resources fails with `ERR_NOT_FOUND` for the first unresolvable id in the path, and only once the path fully resolves are foreign keys inside the body checked, also under `ERR_NOT_FOUND`. Entity-backed ownership (§2.1) is enforced next. State preconditions, optimistic-concurrency checks, and business rules follow, in the priority order each workflow in §3 specifies; where several business checks guard the same endpoint, §3 states their relative evaluation order explicitly so that the surfaced error is deterministic.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Seniors, Caregivers, and Plans

A `PlatformAdmin` begins by registering the people and products. Registering a senior takes a `full_name`, a `date_of_birth` as an ISO calendar date, and the `address` where the kit will be installed; the new senior starts with `monitoring_posture` of `INACTIVE`, an `open_alert_count` of zero, and a `risk_tier` of `STANDARD`. Registering a caregiver anchors that caregiver to exactly one senior via `senior_id`, along with a `full_name` and contact `phone`; this anchor is what later authorizes the caregiver to act on that senior's behalf. Registering an installer records a `full_name` and a service `region` code.

Subscription plans are the commercial template. A plan's `tier` is one of `ESSENTIAL`, `PLUS`, or `PREMIUM`, priced by `monthly_fee_cents` per 30-day cycle. Hardware bundling is expressed through `included_motion_sensors`, the number of motion sensors shipped at no extra charge, and `extra_sensor_fee_cents`, the per-extra-motion-sensor fee per cycle. Escalation capacity is capped by `max_contacts`, the maximum number of `ACTIVE` contact-tree entries a senior on this plan may have. Care-supervision policy comes from `checkin_interval_hours`, the longest allowed gap between check-ins before a missed-check-in alert fires. Two boolean feature gates, `medication_reminders_enabled` and `wellness_report_enabled`, control whether medication schedules and wellness reports may be created at all on the plan, and `wellness_report_cadence` (`NONE`, `MONTHLY`, or `WEEKLY`) records the plan's intended reporting cadence.

### 3.2. Subscriptions and the Billing Lifecycle

A subscription ties a senior to a plan: creation supplies `senior_id` and `plan_id` and produces a subscription, thereafter addressed by its `subscription_id`, whose two parallel status dimensions evolve independently — `service_status` begins at `PROVISIONING` while `billing_status` begins at `CURRENT`. The financial counters start at zero: `billing_credit_cents`, `lifetime_charged_cents`, `lifetime_credited_cents`, and `consecutive_failed_payments` all begin at 0, and the `last_change_plan_credit_cents`, `last_change_sensor_credit_cents`, `last_change_total_credit_cents`, `last_change_total_charge_cents`, and `last_change_net_cents` fields stay null until the first plan change, and `current_period_end` likewise stays null until activation.

Activation moves `service_status` from `PROVISIONING` to `ACTIVE`, and its preconditions are evaluated in a fixed order: the state check first — a subscription not in `PROVISIONING` is rejected with `ERR_INVALID_STATE` — then billing must be `CURRENT` (otherwise `ERR_BILLING_NOT_CURRENT`), and only then must at least one of the senior's kits be `INSTALLED` or `ACTIVE` (otherwise `ERR_KIT_NOT_DELIVERED`). On activation, `current_period_end` is set to thirty days from the current clock, the senior's `monitoring_posture` flips to `ACTIVE`, and every `INSTALLED` kit of the senior advances to `ACTIVE` in the same moment.

Payment outcomes are recorded against the subscription with an `outcome` of `SUCCEEDED` or `FAILED`, and are only meaningful while the service is not `CANCELLED` (otherwise `ERR_INVALID_STATE`). A `FAILED` outcome first moves billing from `CURRENT` to `PAST_DUE`, incrementing `consecutive_failed_payments` by one. A second failure — billing already `PAST_DUE` with `consecutive_failed_payments` at 1 or more — moves billing to `DELINQUENT` and, in the same mutation, cascades: an `ACTIVE` service becomes `SUSPENDED`, the senior's `monitoring_posture` becomes `DEGRADED`, and every open alert of the senior whose severity is `LOW`, `MEDIUM`, or `HIGH` is auto-resolved with `resolution_note` set to `AUTO_RESOLVED_POSTURE_DEGRADED`, decrementing `open_alert_count` once per alert and superseding their still-`SENT` notifications. `CRITICAL` alerts survive this cascade untouched. Every `FAILED` outcome increments `consecutive_failed_payments` by one — including the failure that triggers this cascade, and any further failures recorded while billing is already `DELINQUENT`, which change nothing else. A `SUCCEEDED` outcome returns billing to `CURRENT` from any billing status and resets `consecutive_failed_payments` to zero, but deliberately leaves `service_status` alone — a suspended service stays suspended until an explicit resume. Resuming moves `service_status` from `SUSPENDED` back to `ACTIVE`, requires billing to be `CURRENT` (else `ERR_BILLING_NOT_CURRENT`), and restores the senior's posture to `ACTIVE`. Cancellation moves `service_status` from `PROVISIONING`, `ACTIVE`, or `SUSPENDED` to `CANCELLED` (any other state yields `ERR_INVALID_STATE`), drops the senior's posture to `INACTIVE`, ends every `ACTIVE` medication schedule of the senior, and marks those schedules' still-`PENDING` dose events `SKIPPED`.

Changing plans is the fiscal heart of the system. The request names the new `plan_id` and may name a `proration_mode`; when omitted, the mode defaults to `DAILY_PRORATE`. Both modes start from the same primitives: the billing cycle is fixed at 30 days; `days_remaining` is the whole number of days from the current clock to `current_period_end`, rounded down and clamped between 0 and 30; and the sensor basis is the `motion_sensor_count` of the senior's most recently created kit (the system has no returned-kit state) — in practice the kit whose installation activated the subscription, since only one kit participates in an activation — or zero when the senior has no kits at all. A plan change is accepted in any service or billing state. Under `DAILY_PRORATE`, two credit lines refund the old plan: the plan-fee credit is the old plan's `monthly_fee_cents` multiplied by `days_remaining` and divided by 30, rounded half up to a whole cent, and the sensor credit is the old plan's `extra_sensor_fee_cents` multiplied by the number of extra sensors — the kit's motion sensor count minus the old plan's `included_motion_sensors`, floored at zero — then by `days_remaining` and divided by 30, again rounded half up. Their sum is the total credit. Two charge lines bill the new plan symmetrically: the new plan's `monthly_fee_cents` prorated by the same fraction, and the new plan's `extra_sensor_fee_cents` times the new plan's extra-sensor count (kit sensors minus the new plan's `included_motion_sensors`, floored at zero) prorated likewise, each line rounded half up before summing. Under `FULL_CYCLE_SWAP` there is no proration: the credit is the old plan's full monthly fee plus its full extra-sensor fees, the charge is the new plan's full monthly fee plus its full extra-sensor fees, and `current_period_end` is reset to thirty days from the current clock; under the default mode `current_period_end` is left unchanged. When `current_period_end` is still null because the subscription was never activated, `DAILY_PRORATE` computes with `days_remaining` of zero — every credit and charge line is zero — while `FULL_CYCLE_SWAP` still resets the period.

The net of a change is the total charge minus the total credit. A non-negative net is added to `lifetime_charged_cents`; a negative net has its absolute value added to both `lifetime_credited_cents` and the spendable `billing_credit_cents`. Every change also snapshots its arithmetic onto the subscription: `last_change_plan_credit_cents` and `last_change_sensor_credit_cents` hold the two credit lines, `last_change_total_credit_cents` and `last_change_total_charge_cents` hold the summed per-line-rounded totals, and `last_change_net_cents` holds charge minus credit. Finally, `plan_id` is updated to the new plan.

### 3.3. Kits, Devices, and the Installation Pipeline

Ordering a sensor kit for a senior is a `PlatformAdmin` action taking the `senior_id` and an optional `motion_sensor_count`; when the count is omitted it defaults to the subscribed plan's `included_motion_sensors` — omitting it when the senior has no subscription to default from fails with `ERR_NOT_FOUND`, and an explicit negative count is rejected with `ERR_INVALID_REQUEST`. The kit is created in `ORDERED` status, and provisioning happens immediately: exactly one device whose `device_type` is `GATEWAY`, exactly one whose `device_type` is `WEARABLE`, and one `MOTION` device per requested motion sensor, each created in `PROVISIONED` status with a system-minted, unique `serial` of the form kit-sequence, device-type, and index joined by hyphens. Every device carries its containing `kit_id` and a denormalized `senior_id` for filtered queries, starts with `battery_percent` at 100, and has a null `last_seen_at` until its first telemetry event arrives.

The kit then moves through the hands of logistics and field staff. A `PlatformAdmin` marks an `ORDERED` kit `SHIPPED`, and a `SHIPPED` kit `DELIVERED`; attempting either step from the wrong state is rejected with `ERR_INVALID_STATE`, and each step refreshes the kit's `updated_at` and increments its `version`. An `Installer` may read a kit only when some appointment assigns that installer to it, else `ERR_OWNERSHIP_MISMATCH`; an installer listing appointments sees only their own, and an `installer_id` filter naming another installer is rejected with `ERR_OWNERSHIP_MISMATCH`.

Installation is scheduled as an `InstallAppointment` naming the `senior_id`, the `kit_id`, the assigned `installer_id`, and a window from `window_start` to `window_end`; the appointment is thereafter addressed by its `appointment_id`. The named senior, kit, and installer are resolved in that order, each under `ERR_NOT_FOUND`, before any window check runs. The kit must belong to the same senior as the appointment, or creation fails with `ERR_KIT_SENIOR_MISMATCH`. The window itself is heavily constrained, and the checks run in a deliberate order: the window's duration must fall between 60 and 240 minutes inclusive (else `ERR_WINDOW_TOO_SHORT`); then the installer-overlap rule; then the senior-overlap rule; then the requirement that `window_start` lie strictly after the current clock (else `ERR_WINDOW_IN_PAST`); and only then the kit-ownership check. The installer-overlap rule treats the new window as a half-open interval and rejects it with `ERR_INSTALLER_WINDOW_CONFLICT` when it intersects any of that installer's non-terminal appointments expanded by a 30-minute travel buffer on each side — adjacency at exactly 30 minutes is permitted. The senior-overlap rule uses closed-interval semantics: the new window conflicts with any non-terminal appointment of the same senior whenever the new start is at or before the existing window's end and the existing window's start is at or before the new end, so windows that merely touch still conflict and are rejected with `ERR_SENIOR_WINDOW_CONFLICT`. Rescheduling supplies a replacement `window_start` and `window_end`, re-runs the duration, past-window, and both overlap checks in the same order, with the appointment itself excluded from both overlap scans, and forces the appointment's status back to `SCHEDULED` even if it had been `CONFIRMED` — a discarded confirmation must be earned again.

Once `SCHEDULED`, the assigned installer — and only that installer, else `ERR_OWNERSHIP_MISMATCH` — confirms the appointment, moving it to `CONFIRMED`. Completing the install is likewise restricted to the assigned installer and requires three conditions beyond identity, evaluated after the state check: the appointment must be `CONFIRMED` (a `SCHEDULED` appointment yields `ERR_INVALID_STATE`), the kit must be `DELIVERED` (else `ERR_KIT_NOT_DELIVERED`), and the current clock must lie within the window inclusive of both endpoints (else `ERR_OUTSIDE_APPOINTMENT_WINDOW`). Completion is a cascade: the kit becomes `INSTALLED`, and every `PROVISIONED` device in it becomes `INSTALLED` with its `version` incremented. Any appointment still `SCHEDULED` or `CONFIRMED` when the clock passes its `window_end` is swept to `NO_SHOW`. A `PlatformAdmin` may cancel an appointment in either `SCHEDULED` or `CONFIRMED` status. Because `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal, any confirm, complete, cancel, or reschedule attempted against a terminal appointment is rejected with `ERR_APPOINTMENT_TERMINAL` — and that terminal check outranks the generic state check, so a terminal appointment never surfaces `ERR_INVALID_STATE`.

### 3.4. Telemetry, Device Health, and Autonomous Detection

Field hardware speaks to the platform through a `DeviceHub` caller pushing one event at a time: the emitting `device_id`, an `event_type` of `HEARTBEAT`, `MOTION`, `DOOR_OPEN`, `DOOR_CLOSE`, `FALL_DETECTED`, or `PILL_DISPENSED`, the `observed_at` instant the event physically occurred (which must not exceed the current clock), an optional `battery_percent` reading between 0 and 100, and an optional free-text `note`. Ingest stamps the event with the device's `senior_id` (each stored event is retrievable later by its `event_id`) and has immediate side effects on the device: a device in `INSTALLED` or `OFFLINE` comes `ONLINE`, its `last_seen_at` is set to the event's `observed_at`, and a carried battery reading replaces `battery_percent`. A `PROVISIONED` device keeps its `PROVISIONED` status on ingest — only `INSTALLED` and `OFFLINE` promote to `ONLINE` — while an event from a `DECOMMISSIONED` device is still recorded, and still feeds fall alerting and dose matching, but changes nothing on the device itself, not even `last_seen_at` or battery.

Battery governance runs right at ingest, with inclusive boundaries. When a reading lands at or below 20 percent and no open `LOW_BATTERY` alert exists for the device, one is created — severity `HIGH` if the reading is at or below 10 percent, `MEDIUM` otherwise. A reading at or below 10 percent while a `MEDIUM` `LOW_BATTERY` alert is still open upgrades that alert's severity to `HIGH` and bumps the alert's `version`. The boundaries are exact: 20 triggers, 21 does not; 10 is `HIGH`, 11 is `MEDIUM`. Device-linked alert types — `FALL`, `DEVICE_OFFLINE`, and `LOW_BATTERY` — record the originating `device_id` on the alert; other alert types leave it null. A `FALL_DETECTED` event raises a `CRITICAL` `FALL` alert immediately, and because falls are `CRITICAL` they are created even when the senior's posture would suppress lesser alerts. A `PILL_DISPENSED` event instead feeds medication confirmation (§3.6).

Two autonomous detectors run inside the clock sweep. The offline detector, which runs first in the pinned sweep order, moves any `ONLINE` device whose `last_seen_at` is more than 90 minutes behind the current clock to `OFFLINE` and creates a `MEDIUM` `DEVICE_OFFLINE` alert — unless an open `DEVICE_OFFLINE` alert already exists for that device. The inactivity detector, which runs fifth, fires only for seniors whose posture is `ACTIVE`, who have at least one `ONLINE` motion device, and who show no `MOTION` event observed within the trailing twelve hours — an event exactly twelve hours old still counts as activity; provided no `INACTIVITY` alert is already open, it raises one at `HIGH` severity. Separately, a `PlatformAdmin` may decommission a device from `INSTALLED`, `ONLINE`, or `OFFLINE`, moving it to the terminal `DECOMMISSIONED` state; doing so auto-resolves that device's open `LOW_BATTERY` and `DEVICE_OFFLINE` alerts with the note `AUTO_RESOLVED_POSTURE_DEGRADED`. One safety guard protects the senior: decommissioning a `GATEWAY` is rejected with `ERR_DEVICE_SAFETY_REQUIRED` when the senior's posture is `ACTIVE` and no other gateway of that senior remains `ONLINE` or `INSTALLED` — the last functional gateway of an actively monitored senior cannot be removed.

### 3.5. The Escalation Contact Tree and the Alert Lifecycle

Each senior's escalation tree is an ordered list of `ContactTreeEntry` rows. Creating one names the `senior_id`, the `caregiver_id`, a `priority_rank` (1 is notified first), a `min_severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` below which the entry is ineligible, and a `response_timeout_seconds` governing how long the system waits for that contact before escalating. The named senior and caregiver are resolved first, in that order, each under `ERR_NOT_FOUND`, and a new entry starts in `ACTIVE` status. The checks run in a fixed order: `priority_rank` must be unique among the senior's `ACTIVE` entries (else `ERR_RANK_CONFLICT`); the referenced caregiver must serve the same senior (else `ERR_CAREGIVER_SENIOR_MISMATCH`); and the senior's `ACTIVE` entries must remain below the plan's `max_contacts` (else `ERR_CONTACT_LIMIT_EXCEEDED`), a check skipped entirely when the senior has no subscription plan to consult. A `PlatformAdmin` may later update an entry's `priority_rank`, `min_severity`, or `response_timeout_seconds` — the entry is addressed by its `entry_id`, and rank uniqueness is re-enforced on update — or remove the entry, which sets its status to `REMOVED`; removal never renumbers the survivors. Update and removal apply regardless of the entry's current status — a `REMOVED` entry may still be patched, and removing an already-`REMOVED` entry succeeds unchanged.

Alerts are born in `RAISED` status with `escalation_level` 0, `escalation_exhausted` false, `reopen_count` 0, and null `acknowledged_by_caregiver_id` and `resolution_note`. Most are raised by the detectors and cascades described elsewhere; a `MonitoringAgent` may also raise one manually for any senior, supplying the `senior_id`, a `severity`, and an optional `note` — accepted but not persisted, since alerts carry no note field — which produces an alert whose `alert_type` is `MANUAL` and which, being operator-driven, bypasses the §2.6 posture gate at any severity. Every newly opened alert increments the senior's `open_alert_count` by one and immediately attempts its first notification: the eligible contacts are the senior's `ACTIVE` tree entries whose `min_severity` is at or below the alert's severity on the `LOW` < `MEDIUM` < `HIGH` < `CRITICAL` scale, ranked by `priority_rank` ascending with ties broken by `created_at` ascending. When at least one eligible contact exists, the alert moves `RAISED` → `NOTIFYING`, an `AlertNotification` is created for the first-ranked contact at `level` 1 in `SENT` status with `sent_at` stamped from the logical clock, and the alert's `escalation_level` becomes 1. When no eligible contact exists, the alert simply stays `RAISED` in the monitoring-center queue.

Escalation is timeout-driven and runs fourth in the clock sweep. The sweep skips non-`CRITICAL` alerts whose senior's posture is no longer `ACTIVE`, leaving their latest notification outstanding. When the latest `SENT` notification has been outstanding longer than its contact's `response_timeout_seconds` and a further eligible contact exists, the current notification becomes `TIMED_OUT`, a new `SENT` notification is created for the next-ranked contact at the next `level`, `escalation_level` increments, and the alert sits in `ESCALATED`. This continues level by level until the final eligible contact times out with nobody left: that notification becomes `TIMED_OUT`, the alert's `escalation_exhausted` flag is set true, and the alert remains in `NOTIFYING` or `ESCALATED` awaiting human action.

Acknowledgement moves an alert from `RAISED`, `NOTIFYING`, or `ESCALATED` to `ACKNOWLEDGED`; any other starting state is rejected with `ERR_ALERT_NOT_ACTIONABLE`. A `MonitoringAgent` may acknowledge any alert, which supersedes all still-`SENT` notifications and leaves `acknowledged_by_caregiver_id` null. A `Caregiver` may acknowledge only after passing, in order, the ownership check (the caregiver must serve the alert's senior, else `ERR_OWNERSHIP_MISMATCH`), the state check, and the notification check: a notification for this alert addressed to that caregiver must exist in `SENT` status, else `ERR_NOT_NOTIFIED_CONTACT`. A caregiver acknowledgement marks that caregiver's notification `ACKED`, supersedes any other `SENT` notifications, and records `acknowledged_by_caregiver_id`.

From `ACKNOWLEDGED`, the alert can be closed two ways. Resolving it — open to any caregiver serving the alert's senior, or to an agent, with caregiver ownership re-checked — sets `resolution_note` from the optional `note` supplied with the request and decrements `open_alert_count`. Marking it a false alarm does the same bookkeeping but carries one extra safeguard: for a `CRITICAL` alert the caller must be a `MonitoringAgent`, or the request fails with `ERR_SAFETY_AGENT_REQUIRED`. Both actions require `ACKNOWLEDGED` status, enforced by `ERR_ALERT_NOT_ACTIONABLE`, and that state check runs before the safety-agent check. Closure is not necessarily final: a `MonitoringAgent` may reopen an alert in `RESOLVED` or `FALSE_ALARM` (anything else yields `ERR_ALERT_NOT_ACTIONABLE`), which increments `reopen_count`, re-increments `open_alert_count`, resets `escalation_exhausted` to false, leaves the prior `resolution_note` and `acknowledged_by_caregiver_id` untouched, and starts a fresh notification round — a new level-1 `SENT` notification and `escalation_level` reset to 1 when an eligible contact exists, or a quiet return to `RAISED` when none does. Individually, a notification's life is simple: born `SENT`, and individually retrievable by its `notification_id`, it ends `ACKED` when its own caregiver acknowledges, `TIMED_OUT` when its timeout elapses in the sweep, or `SUPERSEDED` when the alert is acknowledged by another party, reopened, or auto-resolved. A `Caregiver` listing notifications sees only those addressed to themself, and a `caregiver_id` filter naming another caregiver is rejected with `ERR_OWNERSHIP_MISMATCH`. The posture cascade of §3.2 auto-resolves non-`CRITICAL` open alerts from any open status — `RAISED`, `NOTIFYING`, `ESCALATED`, or `ACKNOWLEDGED` — with the `AUTO_RESOLVED_POSTURE_DEGRADED` note.

### 3.6. Medication Schedules and Dose Adherence

A medication schedule is created for a senior by a `PlatformAdmin` or by that senior's caregiver, and only while the senior's subscription has `service_status` of `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`) and the plan's `medication_reminders_enabled` flag is on (else `ERR_FEATURE_GATED`). Between those two gates sits the optimistic-concurrency check of §2.8: the request's `expected_senior_version` must equal the senior's current `version`, else `ERR_STALE_VERSION` — so the evaluation order is subscription-active first, stale-version second, feature gate third. The payload carries the `senior_id`, a `medication_name`, a `times_of_day` array of one to four strictly ascending `HH:MM` UTC dose times, a `window_minutes` confirmation window between 15 and 240 minutes, a `criticality` of `ROUTINE` or `CRITICAL`, and a `start_date` on which dose generation begins. Creation increments the senior's `version` by one — which is precisely what a concurrent creator's `expected_senior_version` check observes — and enforces a uniqueness-by-replacement rule: if an `ACTIVE` schedule already exists for the same senior and `medication_name`, the newcomer supersedes it, ending the old schedule and marking its `PENDING` doses `SKIPPED`. The new schedule starts `ACTIVE` with `missed_streak` at zero, and its dose events are materialized immediately for the half-open window from the current clock inclusive through the next 48 hours exclusive — never before `start_date`, and never duplicating an already-materialized slot; each clock advance extends that horizon by the same 48-hour look-ahead, which is the second step of the pinned sweep.

Each `DoseEvent` belongs to a `schedule_id` and a denormalized `senior_id`, is addressed by its own `dose_id`, and carries a `scheduled_at` instant computed from the schedule's start date and dose times. A dose begins `PENDING` and can be confirmed — moving it to `TAKEN` — either by a human tap or by hardware. The senior themself or their caregiver may confirm a dose; the caller must own the dose's senior (else `ERR_OWNERSHIP_MISMATCH`), the dose must still be `PENDING` (else `ERR_DOSE_NOT_PENDING`), and confirmation must arrive no later than `scheduled_at` plus `window_minutes` — after that the sweep has already marked it missed. Confirmation stamps `confirmed_at`, resets the schedule's `missed_streak` to zero, and computes `punctual`: true when confirmation lands within fifteen minutes of the scheduled time — inclusive, so exactly fifteen minutes still counts as punctual — false when it lands later but still inside the window, and null for any dose not confirmed `TAKEN`. Hardware confirmation works by matching: a `PILL_DISPENSED` event selects the senior's `PENDING` doses whose window from `scheduled_at` to `scheduled_at` plus `window_minutes` contains the event's `observed_at`, ranks them by `scheduled_at` ascending with ties broken by `created_at` ascending, and confirms the first candidate with `confirmed_at` set to `observed_at`; when nothing matches, the event is still logged and no dose changes.

The third sweep step closes expired windows: a `PENDING` dose whose deadline has passed becomes `MISSED` — expired doses are processed earliest-`scheduled_at`-first — its schedule's `missed_streak` increments by one, and streaks trigger escalation — a `CRITICAL` schedule reaching a streak of 2, or a `ROUTINE` schedule reaching 3, creates a `MISSED_MEDICATION` alert for the senior (`HIGH` severity for `CRITICAL` schedules, `MEDIUM` for `ROUTINE`) provided no such alert is already open, increments `open_alert_count`, and immediately runs the notification step of §3.5. Any `TAKEN` confirmation resets the streak to zero. Ending a schedule — by an explicit end action from a `PlatformAdmin` or the owning caregiver, by supersession, or by subscription cancellation — moves it from `ACTIVE` to terminal `ENDED` and marks its remaining `PENDING` doses `SKIPPED`; ending a schedule that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`, and a caregiver ending one must serve its senior (else `ERR_OWNERSHIP_MISMATCH`).

### 3.7. Check-ins and the Caregiver Dashboard

Check-ins are the human heartbeat of the service. A caregiver or the senior themself records one by supplying the `senior_id`, a `kind` of `SELF_CONFIRM`, `APP_CONFIRM`, `CALL`, or `VISIT`, and an optional `note`; the server stamps `occurred_at` from the logical clock, and the record is thereafter retrievable by its `checkin_id`. Caregiver check-ins record the acting `caregiver_id`; any check-in recorded by a `Senior` caller leaves `caregiver_id` null whatever `kind` is supplied, with `SELF_CONFIRM` the conventional kind for a senior self-check-in. Recording a check-in requires the senior's subscription to be `ACTIVE`, else `ERR_SUBSCRIPTION_NOT_ACTIVE`.

The sixth sweep step enforces check-in discipline: when a senior's subscription is `ACTIVE` and the gap between the current clock and the most recent of the senior's last check-in `occurred_at` and the subscription's activation instant exceeds the plan's `checkin_interval_hours`, the sweep raises a `LOW` `MISSED_CHECKIN` alert unless one is already open.

The caregiver dashboard aggregates a senior's current situation into a single read: the `monitoring_posture`, `open_alert_count`, and `risk_tier` of §2.6; `adherence_today_pct`, the adherence percentage (§3.8's weighting rules) computed over doses scheduled from midnight UTC today through the current clock, counting only terminal doses; `devices_online` and `devices_total` summarizing the fleet, both counts excluding `DECOMMISSIONED` devices; the `last_checkin_at` timestamp, null when the senior has never checked in; and the `next_dose_scheduled_at` instant of the next pending dose, null when no dose is pending. The dashboard is available to `PlatformAdmin`, `MonitoringAgent`, the senior's `Caregiver`, and the `Senior` themself.

### 3.8. Wellness Reports

A wellness report condenses a period of a senior's life into four scores. Generation is open to `PlatformAdmin` and `MonitoringAgent`, and names the `senior_id`, a `period_start` aligned to midnight UTC and inclusive, an exclusive `period_end`, and a `mode` of `PROVISIONAL` or `FINAL`. The period must span between 1 and 31 days, inclusive — exactly one day or exactly thirty-one days is legal. Both are body-level shape rules: a non-midnight `period_start`, or a span outside that range, is rejected with `ERR_INVALID_REQUEST`. Four gates guard creation, in this order: the subscription must be `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`); a `FINAL` report must not already exist for the same senior and an overlapping period (else `ERR_DUPLICATE_REPORT`); the period must be temporally legal — `FINAL` requires the clock to have passed `period_end`, while `PROVISIONAL` requires the clock to lie within the period from `period_start` through `period_end` inclusive (else `ERR_PERIOD_NOT_CLOSED`); and the plan's `wellness_report_enabled` flag must be on (else `ERR_FEATURE_GATED`). A generated report starts in `READY` status, is addressed by its `report_id`, records `alert_count` — the number of the senior's alerts of any type opened during the period — and computes its scores as follows.

The `activity_score` counts active days: a UTC calendar day inside the period on which the senior logged at least 3 `MOTION` events, judged by `observed_at`. For a `FINAL` report the score is one hundred times the active-day count divided by the full number of days in the period — the exact period length in days, fractional when `period_end` is not itself midnight-aligned; for a `PROVISIONAL` report the divisor is instead the number of whole days elapsed since `period_start`, clamped to at least one so a same-day preview never divides by zero. The result is capped at 100 and rounded half up to one decimal; a period with no motion at all scores 0.0.

The `adherence_pct` weighs terminal doses: a dose confirmed `TAKEN` with `punctual` true counts 1.0, `TAKEN` but late counts 0.5, and `MISSED` counts 0.0. The due set for a `FINAL` report is the senior's doses scheduled inside the period with status `TAKEN` or `MISSED`; `SKIPPED` doses are excluded entirely. A `PROVISIONAL` report adds every still-`PENDING` dose already due by the current clock, each counted at full weight 1.0. When the due set is empty, adherence is defined as 100.0; otherwise it is one hundred times the summed weights divided by the due-set size, rounded half up to one decimal. The dashboard's today-scope adherence (§3.7) uses the same weights over the day's terminal doses.

The `device_health_pct` starts at 100 and deducts per non-`DECOMMISSIONED` device of the senior: 10 points if the device is `OFFLINE` at evaluation time, and 5 points if its `battery_percent` is at or below 20 at evaluation time. A device `INSTALLED` but never yet `ONLINE` draws no deduction, and the total never drops below 0; the value is carried to one decimal place, though it is integral in practice.

The `wellness_index` blends the three: forty percent of the activity score, thirty-five percent of adherence, and twenty-five percent of device health. The evaluation order is pinned — weighting first, penalty second, cap third, rounding last. If adherence falls below 60, the blended value is multiplied by 0.8. Then, if any `FALL` alert of the senior was opened inside the period and does not stand in `FALSE_ALARM` status, the value is capped at 59 and the report's `fall_cap_applied` flag is set true. The final index is rounded half up to one decimal, in a single rounding at the very end. `PROVISIONAL` reports evaluate against the elapsed slice of the period and current device state; `FINAL` reports replay the closed period, in which no `PENDING` doses remain because the sweep has run.

Two operations act on a `READY` report. Regeneration, restricted to `PlatformAdmin`, recomputes every metric in place at the current clock under the report's existing `mode` and increments the report's `version`; it is governed by the optimistic-concurrency rule of §2.8 — `expected_report_version` must match or the request fails with `ERR_STALE_VERSION` — and a report no longer `READY` yields `ERR_INVALID_STATE`. Delivery, open to `PlatformAdmin` and `MonitoringAgent`, moves the report from `READY` to the terminal `DELIVERED` state, signifying it has been shared with the care circle; anything but a `READY` report is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource, and all reads, return `200 OK`. The table below is a summary only; the complete request and response semantics for each operation are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/seniors` | Register a senior | PlatformAdmin |
| GET | `/v1/seniors/{senior_id}` | Get a senior | PlatformAdmin, MonitoringAgent, Caregiver, Senior |
| GET | `/v1/seniors` | List seniors | PlatformAdmin, MonitoringAgent |
| GET | `/v1/seniors/{senior_id}/dashboard` | Caregiver dashboard summary | PlatformAdmin, MonitoringAgent, Caregiver, Senior |
| POST | `/v1/subscription-plans` | Create a subscription plan | PlatformAdmin |
| GET | `/v1/subscription-plans/{plan_id}` | Get a plan | PlatformAdmin, MonitoringAgent |
| GET | `/v1/subscription-plans` | List plans | PlatformAdmin, MonitoringAgent |
| POST | `/v1/subscriptions` | Create a subscription for a senior | PlatformAdmin |
| GET | `/v1/subscriptions/{subscription_id}` | Get a subscription | PlatformAdmin, MonitoringAgent |
| GET | `/v1/subscriptions` | List subscriptions, filterable by `senior_id` / `plan_id` | PlatformAdmin, MonitoringAgent |
| POST | `/v1/subscriptions/{subscription_id}/activate` | Activate service | PlatformAdmin |
| POST | `/v1/subscriptions/{subscription_id}/record-payment` | Record a billing payment outcome | PlatformAdmin |
| POST | `/v1/subscriptions/{subscription_id}/change-plan` | Change plan with proration | PlatformAdmin |
| POST | `/v1/subscriptions/{subscription_id}/resume` | Resume a suspended subscription | PlatformAdmin |
| POST | `/v1/subscriptions/{subscription_id}/cancel` | Cancel a subscription | PlatformAdmin |
| POST | `/v1/sensor-kits` | Order a sensor kit (auto-provisions devices) | PlatformAdmin |
| GET | `/v1/sensor-kits/{kit_id}` | Get a kit | PlatformAdmin, MonitoringAgent, Installer |
| GET | `/v1/sensor-kits` | List kits, filterable by `senior_id` | PlatformAdmin, MonitoringAgent |
| POST | `/v1/sensor-kits/{kit_id}/ship` | Mark kit shipped | PlatformAdmin |
| POST | `/v1/sensor-kits/{kit_id}/mark-delivered` | Mark kit delivered | PlatformAdmin |
| GET | `/v1/devices/{device_id}` | Get a device | PlatformAdmin, MonitoringAgent, Caregiver |
| GET | `/v1/devices` | List devices, filterable by `kit_id` / `senior_id` / `status` | PlatformAdmin, MonitoringAgent, Caregiver |
| POST | `/v1/devices/{device_id}/decommission` | Decommission a device | PlatformAdmin |
| POST | `/v1/telemetry` | Ingest one device sensor event | DeviceHub |
| GET | `/v1/sensor-events/{event_id}` | Get a sensor event | PlatformAdmin, MonitoringAgent |
| GET | `/v1/sensor-events` | List sensor events, filterable by `device_id` / `senior_id` / `event_type` | PlatformAdmin, MonitoringAgent |
| POST | `/v1/installers` | Register an installer | PlatformAdmin |
| GET | `/v1/installers/{installer_id}` | Get an installer | PlatformAdmin, Installer |
| GET | `/v1/installers` | List installers | PlatformAdmin |
| POST | `/v1/install-appointments` | Schedule an install appointment | PlatformAdmin |
| GET | `/v1/install-appointments/{appointment_id}` | Get an appointment | PlatformAdmin, Installer |
| GET | `/v1/install-appointments` | List appointments, filterable by `senior_id` / `kit_id` / `installer_id` / `status` | PlatformAdmin, Installer |
| POST | `/v1/install-appointments/{appointment_id}/confirm` | Installer confirms the appointment | Installer |
| POST | `/v1/install-appointments/{appointment_id}/complete` | Installer completes the install | Installer |
| POST | `/v1/install-appointments/{appointment_id}/cancel` | Cancel an appointment | PlatformAdmin |
| POST | `/v1/install-appointments/{appointment_id}/reschedule` | Move the appointment window | PlatformAdmin |
| POST | `/v1/caregivers` | Register a caregiver for a senior | PlatformAdmin |
| GET | `/v1/caregivers/{caregiver_id}` | Get a caregiver | PlatformAdmin, MonitoringAgent, Caregiver |
| GET | `/v1/caregivers` | List caregivers, filterable by `senior_id` | PlatformAdmin, MonitoringAgent |
| POST | `/v1/contact-tree-entries` | Add an escalation contact | PlatformAdmin |
| GET | `/v1/contact-tree-entries/{entry_id}` | Get a contact-tree entry | PlatformAdmin, MonitoringAgent |
| GET | `/v1/contact-tree-entries` | List contact-tree entries, filterable by `senior_id` / `caregiver_id` | PlatformAdmin, MonitoringAgent |
| PATCH | `/v1/contact-tree-entries/{entry_id}` | Update rank, timeout, or minimum severity | PlatformAdmin |
| DELETE | `/v1/contact-tree-entries/{entry_id}` | Remove an entry (no renumbering) | PlatformAdmin |
| POST | `/v1/alerts` | Manually raise a MANUAL alert | MonitoringAgent |
| GET | `/v1/alerts/{alert_id}` | Get an alert | PlatformAdmin, MonitoringAgent, Caregiver |
| GET | `/v1/alerts` | List alerts, filterable by `senior_id` / `status` / `alert_type` / `device_id` | PlatformAdmin, MonitoringAgent, Caregiver |
| POST | `/v1/alerts/{alert_id}/acknowledge` | Acknowledge an alert | Caregiver, MonitoringAgent |
| POST | `/v1/alerts/{alert_id}/resolve` | Resolve an acknowledged alert | Caregiver, MonitoringAgent |
| POST | `/v1/alerts/{alert_id}/mark-false-alarm` | Mark an acknowledged alert as false alarm | Caregiver, MonitoringAgent |
| POST | `/v1/alerts/{alert_id}/reopen` | Reopen a resolved or false-alarm alert | MonitoringAgent |
| GET | `/v1/alert-notifications/{notification_id}` | Get a notification | PlatformAdmin, MonitoringAgent |
| GET | `/v1/alert-notifications` | List notifications, filterable by `alert_id` / `caregiver_id` / `contact_entry_id` / `status` | PlatformAdmin, MonitoringAgent, Caregiver |
| POST | `/v1/medication-schedules` | Create a medication schedule | PlatformAdmin, Caregiver |
| GET | `/v1/medication-schedules/{schedule_id}` | Get a schedule | PlatformAdmin, MonitoringAgent, Caregiver |
| GET | `/v1/medication-schedules` | List schedules, filterable by `senior_id` / `status` | PlatformAdmin, MonitoringAgent, Caregiver |
| POST | `/v1/medication-schedules/{schedule_id}/end` | End a schedule | PlatformAdmin, Caregiver |
| GET | `/v1/dose-events/{dose_id}` | Get a dose event | PlatformAdmin, MonitoringAgent, Caregiver, Senior |
| GET | `/v1/dose-events` | List dose events, filterable by `schedule_id` / `senior_id` / `status` | PlatformAdmin, MonitoringAgent, Caregiver, Senior |
| POST | `/v1/dose-events/{dose_id}/confirm` | Confirm a dose taken | Senior, Caregiver |
| POST | `/v1/check-ins` | Record a check-in | Caregiver, Senior |
| GET | `/v1/check-ins/{checkin_id}` | Get a check-in | PlatformAdmin, MonitoringAgent, Caregiver, Senior |
| GET | `/v1/check-ins` | List check-ins, filterable by `senior_id` / `caregiver_id` | PlatformAdmin, MonitoringAgent, Caregiver, Senior |
| POST | `/v1/wellness-reports` | Generate a wellness report | PlatformAdmin, MonitoringAgent |
| GET | `/v1/wellness-reports/{report_id}` | Get a report | PlatformAdmin, MonitoringAgent, Caregiver |
| GET | `/v1/wellness-reports` | List reports, filterable by `senior_id` / `mode` | PlatformAdmin, MonitoringAgent, Caregiver |
| POST | `/v1/wellness-reports/{report_id}/regenerate` | Recompute a READY report in place | PlatformAdmin |
| POST | `/v1/wellness-reports/{report_id}/deliver` | Mark report delivered | PlatformAdmin, MonitoringAgent |
| POST | `/v1/_clock/set_current_utc` | Advance the logical clock and run the sweeps | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is a reference index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_APPOINTMENT_TERMINAL` | 409 |
| `ERR_ALERT_NOT_ACTIONABLE` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_DOSE_NOT_PENDING` | 409 |
| `ERR_KIT_NOT_DELIVERED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SAFETY_AGENT_REQUIRED` | 403 |
| `ERR_NOT_NOTIFIED_CONTACT` | 403 |
| `ERR_DEVICE_SAFETY_REQUIRED` | 422 |
| `ERR_WINDOW_TOO_SHORT` | 422 |
| `ERR_RANK_CONFLICT` | 409 |
| `ERR_INSTALLER_WINDOW_CONFLICT` | 409 |
| `ERR_SENIOR_WINDOW_CONFLICT` | 409 |
| `ERR_DUPLICATE_REPORT` | 409 |
| `ERR_WINDOW_IN_PAST` | 422 |
| `ERR_OUTSIDE_APPOINTMENT_WINDOW` | 409 |
| `ERR_PERIOD_NOT_CLOSED` | 422 |
| `ERR_CAREGIVER_SENIOR_MISMATCH` | 422 |
| `ERR_KIT_SENIOR_MISMATCH` | 422 |
| `ERR_FEATURE_GATED` | 422 |
| `ERR_CONTACT_LIMIT_EXCEEDED` | 422 |
| `ERR_BILLING_NOT_CURRENT` | 409 |
