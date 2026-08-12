# Remote Cardiac Monitoring API — Product Requirements Document

## 1. Introduction

Cardiac monitoring services run on a simple clinical promise with demanding operational mechanics: a physician prescribes a Holter, event, or implantable monitor, the patient wears it for a prescribed span of days, and every transmission must flow back, be screened for arrhythmias, and be distilled into a signed diagnostic report — while devices, technician workload, and billing windows are tracked to the minute and to the cent. This document specifies the Remote Cardiac Monitoring API, the system of record for an Independent Diagnostic Testing Facility (IDTF) operating exactly this service end to end.

The API covers the full operational arc: registering patients, physicians, triage technicians, and devices; creating monitoring orders and driving enrollment through device reservation, patient education, and activation; ingesting device transmissions and detecting connectivity gaps; triaging arrhythmia alerts by severity under explicit notification deadlines; producing interim and final physician reports with measured turnaround; carving the monitoring span into thirty-day billing windows split into technical and professional fee components; and managing device returns, refurbishment, and patient non-compliance follow-up. Two concerns cut across everything. Patient safety is gated directly: no final report may ship while a critical arrhythmia alert on the episode remains unresolved. Staff sustainability is gated as well: each triage technician's open load is measured continuously so that alarm fatigue throttles further self-assignment before quality degrades.

All time-dependent behavior in the system is evaluated against a logical clock rather than wall time, and an administrator can advance that clock deterministically. Every deadline, window, gap detection, and sweep rule in this document is therefore reproducible and testable.

## 2. Global Specifications & System-Wide Principles

All endpoints in this specification are mounted under the `/v1` URL prefix. This section defines the system-wide rules that apply to every one of them.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. The platform recognizes seven roles, spelled exactly as follows: `PlatformAdmin`, `EnrollmentCoordinator`, `Physician`, `MonitoringTechnician`, `BillingSpecialist`, `InventoryManager`, and `DeviceGateway`. A request missing either header, or naming a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target operation — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). One further authorization rule applies to billing adjustments: the user approving a proposed adjustment must differ from the user who proposed it, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting Physician; ownership checks on any resource that references a Physician — a monitoring order's `ordering_physician_id`, a diagnostic report's `reading_physician_id`, a notification attempt's `physician_id` — compare that field to `X-User-ID`. When `X-User-Role` is `MonitoringTechnician`, `X-User-ID` is the `id` of the acting Technician, and assignment checks compare a resource's `assigned_technician_id` to `X-User-ID`. For `PlatformAdmin`, `EnrollmentCoordinator`, `BillingSpecialist`, `InventoryManager`, and `DeviceGateway`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `proposed_by_user_id` and `approved_by_user_id` on a billing period — but never compares it to any entity's `id`.

Read access is broad but not uniform. Every role except `DeviceGateway` may call every read endpoint in the API. `DeviceGateway` is a data-plane identity: beyond its two write capabilities it may read only the transmission listing of an episode.

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

An unexpected internal failure is reported in the same envelope with `error_id` `ERR_INTERNAL` and HTTP status 500.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. A `limit` outside the range 1 to 100 is a field-validation failure rejected with `ERR_VALIDATION` (HTTP 400). A `limit` or `offset` that does not parse as an integer, and a negative `offset`, are rejected the same way; `offset` has no upper bound.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties on the timestamp broken by `id` ascending.

Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource in the system — patients, physicians, technicians, devices, monitoring orders, enrollments, episodes, suspension intervals, transmissions, alerts, notification attempts, diagnostic reports, billing periods, return shipments, and compliance events — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every modification of the resource.
- `version` (integer): starts at 1 at creation and increments on every mutation.

Recomputation of a derived field counts as a mutation of the owning resource: when a technician's load counters shift, when an episode's billed total grows at submission, or when any other computed field is refreshed, the owning resource's `updated_at` advances and its `version` increments. Cascades described in §3 may therefore bump the version of a resource that the client's request never named directly.

### 2.5. The Logical Clock and the Daily Sweep

Time inside the system is logical, not wall-clock. At startup the logical clock reads 2026-05-01T00:00:00Z, and it never falls back to wall time. A `PlatformAdmin`-only test-driving capability sets the current clock to a supplied `to_iso8601` instant; every timestamp the system records from then on — `received_at`, `detected_at`, `attempted_at`, `label_created_at`, `finalized_at`, and the like — is the logical clock value at the moment of the operation.

A second administrator-only capability runs the daily sweep on demand. The sweep applies five stages in a pinned order: (1) refurbishment completion, releasing refurbished devices back to stock; (2) return-shipment staging, in which each shipment undergoes at most one transition per sweep — a label may go overdue, or an already-overdue shipment may be declared lost, but never both in a single sweep; (3) alert SLA escalation for alerts whose deadline has passed; (4) transmission-gap detection with its strike cascade; and (5) billing-window readiness, maturing accrued windows whose end date has arrived. All side effects of a sweep are visible immediately in subsequent reads.

### 2.6. Optimistic Concurrency Control

Exactly one write in the API is version-gated. Creating an enrollment against a monitoring order requires the non-optional request field `expected_order_version`, carrying the order `version` the client last observed. If that value does not match the order's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The gate exists because creating an enrollment legitimately supersedes any prior non-terminal enrollment of the same order — a writer holding a stale version would otherwise abort a record it never saw. No other endpoint accepts a version field; every other write proceeds without an OCC check.

### 2.7. Precision, Rounding, and Units

Four precision regimes govern computed values, and they do not mix:

- **Money** is integer cents. Billing computes each fee line rounded half up to whole cents, and only then sums lines into a total — rounding is per line, never on the sum.
- **Ratios and hour durations** — `fatigue_index`, `throughput_index`, and `turnaround_hours` — are rounded half up to exactly 2 decimal places.
- **Deadlines and gap detection** operate at minute granularity on ISO 8601 UTC timestamps.
- **Billing windows** are measured in whole days; their boundary datetimes remain exact.

### 2.8. Validation Order of Operations

Every request is validated against a fixed priority ladder. A failure at any rung masks all later rungs: the response always carries the highest-priority failure present, never a lower one. The rungs, highest priority first:

1. **Authentication** — `X-User-Role` and `X-User-ID` present and the role recognized, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — role permitted for the endpoint and entity-backed ownership satisfied, else `ERR_FORBIDDEN_ROLE` (403); adjustment approval by the original proposer yields `ERR_SEGREGATION_OF_DUTIES` (403).
3. **Existence** — path and body resource references resolved left to right, else the applicable 404 (see §2.9).
4. **Field validation** — required inputs present and enums and ranges valid (`prescribed_days` within 5 to 45, `signal_quality` within 0 to 100, `limit` within 1 to 100), else `ERR_VALIDATION` (400). A request with a missing or malformed JSON body is evaluated as an empty payload, so its absent required fields fail at this rung, and a JSON boolean is never accepted where an integer is required.
5. **State-machine preconditions** — from-state and guard checks: generic failures yield `ERR_INVALID_STATE` (409); a device already committed elsewhere yields `ERR_DEVICE_NOT_IN_STOCK` (409); activation before education yields `ERR_EDUCATION_INCOMPLETE` (422); a stale order version yields `ERR_STALE_VERSION` (412).
6. **Business safety** — open critical alerts block report finalization with `ERR_CRITICAL_ALERTS_OPEN` (422); an off-shift, at-capacity, or fatigued technician is blocked from acknowledgement with `ERR_TECHNICIAN_UNAVAILABLE` (422).
7. **Business temporal** — a second concurrently monitoring episode for the same patient yields `ERR_ACTIVE_EPISODE_EXISTS` (409); a refurbishment buffer not yet elapsed yields `ERR_DEVICE_NOT_REFURBISHED` (409); overlapping billing windows yield `ERR_BILLING_WINDOW_OVERLAP` (409).
8. **Business referential** — `ERR_EPISODE_NOT_COMPLETED` (422), `ERR_REPORT_NOT_FINALIZED` (422), `ERR_OPEN_COMPLIANCE_EVENTS` (422), and `ERR_NOTIFICATION_NOT_ACKNOWLEDGED` (422).
9. **Business constraint** — uniqueness conflicts (`ERR_DUPLICATE_MRN`, `ERR_DUPLICATE_NPI`, `ERR_DUPLICATE_SERIAL`, `ERR_DUPLICATE_TRANSMISSION_SEQ`, all 409) and content constraints (`ERR_DEVICE_CATEGORY_MISMATCH` and `ERR_EMPTY_MONITORING_DATA`, both 422).
10. **Business fiscal** — `ERR_EPISODE_SUSPENDED` (422), `ERR_BELOW_MINIMUM_BILLABLE_DAYS` (422), and `ERR_ADJUSTMENT_EXCEEDS_BILLED` (422).

Where several checks from different rungs apply to a single operation, §3 states their relative order alongside the workflow.

### 2.9. Nested Resource Retrieval and Addressing

Requests that target nested or referenced resources are resolved strictly left to right: the system validates the first identifier in the path, then the next, and a body-carried reference is validated when the payload is checked. The response carries the not-found error of the first missing resource, and no later validation runs. The not-found vocabulary is resource-specific: a missing patient yields `ERR_PATIENT_NOT_FOUND`, a missing device reference — whether in the path or in the request body — yields `ERR_DEVICE_NOT_FOUND`, a missing order yields `ERR_ORDER_NOT_FOUND`, a missing episode yields `ERR_EPISODE_NOT_FOUND`, and a missing alert yields `ERR_ALERT_NOT_FOUND` (all HTTP 404). Every other addressed resource — enrollment, physician, technician, transmission, notification attempt, report, billing period, shipment, or compliance event — falls back to the generic `ERR_RESOURCE_NOT_FOUND` (HTTP 404). A request whose path matches no endpoint — or whose method the endpoint does not support — is likewise rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404).

### 2.10. Fleet Accounting and Inventory Conservation

Device inventory is accounted per model — `HOLTER`, `EVENT`, and `IMPLANTABLE`. For each model, the fleet total is the count of registered devices, and the available count is the number currently `IN_STOCK`. A conservation invariant holds at all times: the counts of devices in `IN_STOCK`, `RESERVED`, `DEPLOYED`, `RETURN_IN_TRANSIT`, `REFURBISHING`, and `LOST` always sum to the registered fleet size. State transitions reclassify units; they never create or destroy them, so a lost device still counts toward the registered total even though it is permanently unavailable. The device list read surfaces this accounting and can be filtered by `status` and `model`.

## 3. Business Logic & Workflows

### 3.1. The Registry: Patients, Physicians, Technicians, and Devices

Operations begin with four registries. An `EnrollmentCoordinator` registers a patient with a `full_name`, a `date_of_birth` in ISO `YYYY-MM-DD` form, a contact `phone`, and an `insurance_plan` of `MEDICARE`, `COMMERCIAL`, or `SELF_PAY`. The medical record number `mrn` must be unique across all patients; a duplicate is rejected with `ERR_DUPLICATE_MRN` (HTTP 409). A new patient's `open_compliance_events` starts at 0 and thereafter tracks the count of that patient's unresolved compliance events across all episodes, so a patient read always reflects the current follow-up burden.

Physicians and technicians are registered by a `PlatformAdmin`. A physician record carries `full_name`, `specialty`, and an `npi` that must be exactly 10 digits and unique across physicians — duplicates are rejected with `ERR_DUPLICATE_NPI` (HTTP 409). The physician's `notification_preference` is either `PHONE` or `PORTAL` and defaults to `PORTAL` when omitted; it determines the channel used whenever the system reaches out to that physician. A technician record carries `full_name`, a `certification_level` of `CCT`, `CRAT`, or `RN`, a `shift_capacity` (a positive integer capping how many open alerts the technician may hold at once), and an `on_shift` flag that defaults to true. At registration every technician counter is zeroed — `open_alert_load`, `alerts_acknowledged_total`, `fatigue_index`, and `throughput_index` all start at 0 — and `fatigue_status` starts at `NORMAL`. Reading a technician by `technician_id` exposes the live load and fatigue fields alongside the static profile.

An `InventoryManager` registers devices into the fleet. Each device is enrolled with a manufacturer `serial_number`, unique across the fleet (duplicates rejected with `ERR_DUPLICATE_SERIAL`, HTTP 409), and a `model` of `HOLTER`, `EVENT`, or `IMPLANTABLE`. A freshly registered device enters in `IN_STOCK` status, immediately eligible for reservation.

### 3.2. Orders, Enrollment, and the Reservation Protocol

A monitoring engagement starts when a `Physician` creates an order naming the `patient_id`, the `monitor_type` (`HOLTER`, `EVENT`, or `IMPLANTABLE`), and the `prescribed_days` — the monitoring length, which must be at least 5 and at most 45 days, with out-of-range values rejected as `ERR_VALIDATION`. An optional `indication_codes` list of ICD-10 codes may accompany the order and defaults to an empty list; a supplied value that is not a list is rejected with `ERR_VALIDATION` (HTTP 400). The `ordering_physician_id` is taken from the caller's `X-User-ID`, never from the payload. A new order is `OPEN` with `version` 1. The orders list can be filtered by `patient_id`, `ordering_physician_id`, and `status`.

An `EnrollmentCoordinator` then creates an enrollment under an order, supplying the `device_id` to reserve and the OCC field `expected_order_version` described in §2.6. Reservation checks run in the ladder order of §2.8. The order must exist, and the payload must be well-formed; the order's own status is not re-checked — the version match is the only order-side gate. At the state rung, the device must not already be committed: a device in `RESERVED`, `DEPLOYED`, `RETURN_IN_TRANSIT`, or `LOST` is rejected with `ERR_DEVICE_NOT_IN_STOCK` (HTTP 409), and a stale `expected_order_version` is rejected with `ERR_STALE_VERSION` (HTTP 412). A device in `REFURBISHING` passes the state rung and is judged instead at the temporal rung: if its 48-hour refurbishment buffer has not yet elapsed — `refurbishment_due_at` still lies in the future — the reservation is rejected with `ERR_DEVICE_NOT_REFURBISHED` (HTTP 409). Finally, at the constraint rung, the device's `model` must equal the order's `monitor_type` — Holter with Holter, event with event, implantable with implantable — else the create fails with `ERR_DEVICE_CATEGORY_MISMATCH` (HTTP 422).

A successful reservation moves the device to `RESERVED`, increments the order's `version`, and supersedes any prior non-terminal enrollment of the same order: each prior enrollment in `INITIATED`, `EDUCATED`, or `ACTIVATION_FAILED` moves to `ABORTED`, and any device those enrollments held is released back to `IN_STOCK`. The new enrollment begins `INITIATED` with `order_id` pointing at its order, `education_completed` false, `education_method` null, `attempts_count` 0, and `episode_id` null. Enrollments can be listed with filters on `order_id`, `device_id`, `episode_id`, and `status`, and read individually by `enrollment_id`.

Two exits close an order early. The ordering physician — and only that physician, by the ownership check of §2.1 — may cancel an order while it is still `OPEN`; an order already `IN_SERVICE` must first run its episode to a terminal state, and cancelling one is rejected with `ERR_INVALID_STATE` (HTTP 409). Cancellation cascades: every non-terminal enrollment of the order (`INITIATED`, `EDUCATED`, or `ACTIVATION_FAILED`) moves to `ABORTED`, their `RESERVED` devices return to `IN_STOCK`, and the order's `version` increments. Independently, a coordinator may abort any single non-terminal enrollment directly, with the same per-enrollment effect: `ABORTED`, and its reserved device released. `FULFILLED` and `CANCELLED` are the order's terminal states; `ACTIVATED` and `ABORTED` are the enrollment's.

### 3.3. Education, Activation, and the Start of Monitoring

Before a device goes live, the patient must be taught to use it. A coordinator records education on an `INITIATED` enrollment by supplying the `education_method` — `IN_PERSON`, `PHONE`, or `VIDEO` — which moves the enrollment to `EDUCATED` and sets `education_completed` to true; recording education on an enrollment in any other state is rejected with `ERR_INVALID_STATE` (HTTP 409). That flag, once earned, is retained across any later retry.

Activation is the pivotal step, and it evaluates its guards in ladder order. The enrollment must be `EDUCATED`; activating earlier is rejected with `ERR_EDUCATION_INCOMPLETE` (HTTP 422). The reserved device must still be held for this enrollment. At the temporal rung, the patient must not already have another episode in clinical status `MONITORING` — one patient, one live stream — else the activation is rejected with `ERR_ACTIVE_EPISODE_EXISTS` (HTTP 409). The request itself carries a single reading, `baseline_signal_quality`, taken from the device at hookup — an integer from 0 to 100, with other values rejected as `ERR_VALIDATION` (HTTP 400).

When the baseline reading is at least 40, activation succeeds as an atomic bundle: a monitoring episode is created with `enrollment_id` naming the activating enrollment, `patient_id` denormalized from the order for query isolation, `monitor_type` copied from the order, `started_at` set to the logical clock, `scheduled_end_at` set to `started_at` plus the order's `prescribed_days`, `clinical_status` `MONITORING`, `compliance_status` `COMPLIANT`, `strike_count` 0, the derived counters `transmission_count`, `unacknowledged_critical_count`, and `total_billed_cents` all at 0, and `completed_at` null. In the same motion the enrollment moves to `ACTIVATED` with its `episode_id` populated, the device moves from `RESERVED` to `DEPLOYED`, and the order moves from `OPEN` to `IN_SERVICE` (a mutation that bumps its `version`). The response carries the updated enrollment.

When the baseline reading is below 40, activation fails cleanly instead: the device is pulled from service into `REFURBISHING` with `refurbishment_due_at` set 48 hours out, the enrollment moves to `ACTIVATION_FAILED`, and its `attempts_count` increments by one. Recovery is a retry: the coordinator supplies a replacement `device_id`, which is vetted by the same stock, refurbishment-buffer, and category rules as the original reservation, the new device moves to `RESERVED`, and the enrollment returns to `INITIATED` with `education_completed` retained — the patient is not re-taught, only re-hooked.

### 3.4. Transmission Ingest and Connectivity Gap Surveillance

Once an episode is monitoring, the device's data plane pushes transmissions through the `DeviceGateway` identity. Each ingest names the target episode and carries `seq_no` (the device's sequence number, unique within the episode — a reuse is rejected with `ERR_DUPLICATE_TRANSMISSION_SEQ`, HTTP 409), `bytes_received` (the payload size, a positive integer), and `signal_quality` on a 0-to-100 scale. Ingest is only defined while the episode's `clinical_status` is `MONITORING`; attempts against a terminal episode fail generically with `ERR_INVALID_STATE`. The server stamps `received_at` from the logical clock and assigns the transmission's `status` by quality: a reading of at least 30 yields `PROCESSED` and increments the episode's `transmission_count`; a reading below 30 yields `FAILED` and leaves the count untouched.

Failed transmissions are not dead ends. A `MonitoringTechnician` may reprocess one — addressed by its `transmission_id` — supplying an updated `signal_quality`. When the updated reading is at least 30, the transmission moves from `FAILED` to `PROCESSED`, its stored `signal_quality` is replaced by the updated reading, and the episode's `transmission_count` increments; a reading that remains below 30 leaves the transmission in `FAILED`. `PROCESSED` is terminal. An episode's transmissions can be listed with a `status` filter, and `DeviceGateway` may read that listing as well as write to it.

Connectivity is policed by the sweep's fourth stage. For each episode still `MONITORING`, the sweep establishes a base timestamp: the latest of the episode's `started_at`, the `received_at` of its most recent `PROCESSED` transmission, and the creation time of its most recent `TRANSMISSION_GAP` compliance event — skipping whichever of those terms do not exist. When the elapsed time from that base to the current clock reaches 48 hours, and no `TRANSMISSION_GAP` event is currently `OPEN` for the episode, the sweep creates a new `TRANSMISSION_GAP` compliance event, which enters the strike cascade of §3.6. The boundary is inclusive: exactly 48 hours of silence triggers the event; 47 hours and 59 minutes does not.

### 3.5. Arrhythmia Triage, Physician Notification, and Alarm Fatigue

Detection runs on the data plane: the `DeviceGateway` raises an arrhythmia alert on an episode with a `severity` of `CRITICAL`, `URGENT`, or `ROUTINE` and an `arrhythmia_type` such as AFIB, VTACH, or PAUSE. The raise is not gated on the episode's clinical status; an alert may be raised on an episode in any state. The alert is born `NEW` with `detected_at` stamped from the logical clock, `assigned_technician_id` and `acknowledged_at` null, and an `sla_deadline` computed immediately under the business-hours rule below. Raising a `CRITICAL` alert also increments the episode's `unacknowledged_critical_count` — the figure that later gates report finalization.

The notification SLA is pinned to the BUSINESS_HOURS variant. Business hours run from 08:00 UTC up to but not including 20:00 UTC, every day of the week. A `CRITICAL` alert's deadline is always fifteen minutes after `detected_at`, regardless of the hour. An `URGENT` alert detected within business hours carries a deadline sixty minutes after detection; detected outside business hours, its deadline is thirty minutes past the next 08:00 UTC. A `ROUTINE` alert detected within business hours carries 1,440 minutes — a full day; detected outside business hours, its deadline is 120 minutes past the next 08:00 UTC. A wall-clock reading of the same rule — deadline equals `detected_at` plus the base minutes regardless of hour — is a documented alternative interpretation only and is never what gets stored.

Acknowledgement is self-assignment under a fatigue guard. A `MonitoringTechnician` acknowledges a `NEW` alert: the caller's `X-User-ID` must resolve to a registered technician, else `ERR_RESOURCE_NOT_FOUND` (HTTP 404); from any state other than `NEW` the action fails generically with `ERR_INVALID_STATE`; and three conditions are enforced together, any of which rejects the call with `ERR_TECHNICIAN_UNAVAILABLE` (HTTP 422): the caller's `on_shift` flag must be true, the caller's `open_alert_load` must be below their `shift_capacity`, and the caller's `fatigue_status` must not be `FATIGUED`. On success the alert moves from `NEW` to `ACKNOWLEDGED` with `assigned_technician_id` set to the caller and `acknowledged_at` stamped; the cascade then runs two links into the technician record — `open_alert_load` increments by one, `alerts_acknowledged_total` increments by one (a lifetime counter that is never decremented), and the fatigue figures are recomputed as described below, which may flip `fatigue_status` from `NORMAL` to `AT_RISK` or `FATIGUED`.

The assignee controls the middle of the lifecycle. Releasing an alert — permitted only to the technician whose id equals `assigned_technician_id` — returns it from `ACKNOWLEDGED` to `NEW`, clears the assignment (the earlier `acknowledged_at` is retained), decrements the technician's `open_alert_load`, and recomputes fatigue. Triaging moves `ACKNOWLEDGED` to `TRIAGED`, again only for the assignee, and accepts an optional `severity_reclass`: when supplied, the alert's `severity` is updated and its `sla_deadline` is recomputed from the original `detected_at` under the new severity; reclassifying into `CRITICAL` increments the episode's `unacknowledged_critical_count`, and reclassifying a `CRITICAL` alert out to another severity decrements it.

Notifying the physician creates a `NotificationAttempt` and moves the alert to `NOTIFIED`. The attempt's `physician_id` is resolved by walking the episode's enrollment back to the order's `ordering_physician_id` — the ordering physician is always the one notified — and its `channel` is that physician's `notification_preference`. The attempt is born `PENDING` with `attempted_at` stamped from the clock and `within_sla` null until the physician acknowledges, and every created attempt raises the alert's `notification_attempt_count`. From `TRIAGED`, the notifying technician must be the assignee; from `ESCALATED`, the same notify action is not gated on assignment, and it likewise produces a preference-channel attempt.

Escalation has two doors into the same state. A technician may manually escalate a `TRIAGED` alert, and the sweep's third stage escalates any alert still in `NEW`, `ACKNOWLEDGED`, or `TRIAGED` whose `sla_deadline` has passed. Either way the alert lands in `ESCALATED` and a `NotificationAttempt` with `channel` `ESCALATION` is created, counted like any other.

Closing an alert depends on how far it traveled. From `ACKNOWLEDGED`, the assignee closes with `outcome` `FALSE_POSITIVE`. From `NOTIFIED`, closing with `outcome` `RESOLVED` additionally requires that at least one notification attempt for the alert has been acknowledged by the physician; without one, the close is rejected with `ERR_NOTIFICATION_NOT_ACKNOWLEDGED` (HTTP 422). An `outcome` that does not fit the from-state — anything other than `FALSE_POSITIVE` from `ACKNOWLEDGED`, or anything other than `RESOLVED` from `NOTIFIED` — and any close attempted from another state are rejected with `ERR_INVALID_STATE` (HTTP 409). Either close records `closed_outcome`, moves the alert to its terminal `CLOSED` state, decrements the holding technician's `open_alert_load`, and — for `CRITICAL` alerts — decrements the episode's `unacknowledged_critical_count`.

The physician side of the loop is a single act: the addressed physician — the caller's id must equal the attempt's `physician_id`, else `ERR_FORBIDDEN_ROLE` — acknowledges a `PENDING` attempt, moving it to its terminal `ACKNOWLEDGED` status. At that moment `within_sla` is computed: true when the acknowledgement happened at or before the alert's `sla_deadline`, false otherwise. Attempts can be listed with filters on `alert_id`, `physician_id`, and `status`, and read individually by `attempt_id`.

Two computed figures keep triage staffing honest, and both are refreshed whenever a technician's `open_alert_load` changes — on acknowledge, release, or close — and whenever the technician record is read. The load ratio `fatigue_index` is the technician's `open_alert_load` divided by `shift_capacity`, rounded half up to two decimal places; a value of 0.80 or higher marks the technician `FATIGUED`, a value of 0.60 or higher but below 0.80 marks `AT_RISK`, and anything lower is `NORMAL`. Only open work counts toward the load: alerts assigned to the technician in `ACKNOWLEDGED`, `TRIAGED`, `ESCALATED`, or `NOTIFIED` — never `NEW`, never `CLOSED`. The `throughput_index` is the cumulative companion: the sum of `alerts_acknowledged_total` and `open_alert_load`, divided by `shift_capacity` multiplied by the number of full days between the technician's `created_at` and the current time — that day count treated as at least one — rounded half up to two decimal places. It is stored for analytics only and never gates an action. Alerts themselves can be listed with filters on `episode_id`, `assigned_technician_id`, `status`, and `severity`, and read individually by `alert_id`.

### 3.6. Compliance Strikes, Suspension, and Patient Follow-Up

Non-compliance is recorded as `ComplianceEvent` rows against an episode, each carrying an `event_type` of `TRANSMISSION_GAP` or `RETURN_OVERDUE` and born `OPEN` with `resolution_action` null. Creating an event increments the episode's `strike_count` and the patient's `open_compliance_events`. While the episode's `clinical_status` is `MONITORING`, the new strike count is immediately mapped onto the compliance dimension: zero strikes is `COMPLIANT`, one or two strikes is `WATCH`, and three or more is `SUSPENDED` — exactly three already suspends, from `WATCH` or directly from `COMPLIANT` when the count jumps. Entering `SUSPENDED` opens a `SuspensionInterval` on the episode with `started_at` stamped from the clock and `ended_at` null. Once the episode's clinical status has gone terminal, further strikes may still be recorded, but the mapping no longer applies. `WATCH` never auto-decays: it persists until the episode either suspends or reaches a clinical terminal state, and the only way back to `COMPLIANT` is the resume below.

Resuming is a coordinator's act with a hard precondition: the episode must have zero `OPEN` compliance events, else the resume is rejected with `ERR_OPEN_COMPLIANCE_EVENTS` (HTTP 422). A successful resume moves the compliance dimension from `SUSPENDED` to `COMPLIANT`, closes the open suspension interval by stamping its `ended_at`, and resets `strike_count` to 0.

Follow-up itself is tracked per event. A coordinator resolves an `OPEN` event by recording a `resolution_action` of `CONTACTED_PATIENT`, `DEVICE_REPLACED`, or `PHYSICIAN_NOTIFIED`, which moves the event to its terminal `RESOLVED` status and decrements the patient's `open_compliance_events`. Compliance events can be listed with filters on `episode_id`, `status`, and `event_type`, and read individually by `event_id`; an episode's suspension intervals are listed as a reverse lookup, each row exposing its `episode_id`, `started_at`, and `ended_at`.

### 3.7. Episode Completion and the Diagnostic Report Pipeline

An episode ends when a coordinator completes it with a `reason` of `COMPLETED` or `TERMINATED_EARLY`. Completion shares the resume precondition — zero `OPEN` compliance events, else `ERR_OPEN_COMPLIANCE_EVENTS` (HTTP 422) — and on success stamps `completed_at` from the clock, moves `clinical_status` to the named terminal state, and bubbles the parent order from `IN_SERVICE` to `FULFILLED`. Episode reads expose the full picture: `enrollment_id`, `patient_id`, `monitor_type`, `started_at`, `scheduled_end_at`, `completed_at`, both status dimensions, `strike_count`, and the derived counters; the episode list can be filtered by `enrollment_id`, `patient_id`, `clinical_status`, and `compliance_status`.

Diagnostic reporting is physician work. A `Physician` creates a report on an episode with a `report_type` of `INTERIM` or `FINAL` and free-text `findings_summary`; `no_significant_findings` may be supplied and defaults to false. The `reading_physician_id` is taken from the caller's `X-User-ID`. A new report is `DRAFT` with `revision_count` 0, `finalized_at` null, and — since turnaround is a final-only measurement — `turnaround_hours` and `sla_met` both null.

Finalization is the most heavily gated write in the system, and its guards fire in a fixed relative order. Ownership comes first: the caller must be the report's reading physician, else `ERR_FORBIDDEN_ROLE`. Then the safety gate: every `CRITICAL` alert on the episode must be `CLOSED`, and finalizing while one remains open is rejected with `ERR_CRITICAL_ALERTS_OPEN` (HTTP 422). Then the referential gate: a `FINAL` report requires the episode's `clinical_status` to be `COMPLETED` or `TERMINATED_EARLY` — an `INTERIM` report may finalize while the episode is still `MONITORING`, but a `FINAL` one is rejected with `ERR_EPISODE_NOT_COMPLETED` (HTTP 422). Last, the constraint gate: a `FINAL` report on an episode whose `transmission_count` is zero must carry `no_significant_findings` true, else `ERR_EMPTY_MONITORING_DATA` (HTTP 422). Finalizing from either `DRAFT` or `AMENDED` moves the report to `FINALIZED` and stamps `finalized_at`.

For `FINAL` reports, finalization also measures turnaround. `turnaround_hours` is the number of hours between the episode's `completed_at` and the report's `finalized_at`, rounded half up to two decimal places. `sla_met` is true when `finalized_at` falls at or before seventy-two hours after the episode's `completed_at`; hitting the seventy-two-hour mark exactly still counts as met. `INTERIM` reports leave both fields null.

Reports are never frozen. The reading physician may amend a `FINALIZED` report with replacement `findings_summary`, moving it to `AMENDED` and incrementing `revision_count`; the cycle `FINALIZED` → `AMENDED` → `FINALIZED` may repeat indefinitely, and the report state machine has no terminal state. Reports can be listed with filters on `episode_id`, `reading_physician_id`, and `status`, and read individually by `report_id`.

### 3.8. Billing Windows, Submission, and Segregated Adjustments

Billing carves each episode into thirty-day windows, generated in one call by a `BillingSpecialist`. The end of service is the episode's `completed_at` when set, otherwise its `scheduled_end_at`. The window with 0-based `period_index` i opens at the episode's `started_at` plus i times thirty days, and closes at the earlier of thirty days after its own start and the end of service. Every window whose start falls before the end of service is generated. Each period is half-open: its `start_date` is included and its `end_date` excluded, so two periods may touch — one ending exactly when the next begins — without overlapping; genuine overlap requires each window to start before the other ends. Generation is rejected with `ERR_BILLING_WINDOW_OVERLAP` (HTTP 409) when any existing billing period of the episode in `ACCRUING`, `READY`, `SUBMITTED`, or `ADJUSTMENT_PROPOSED` overlaps the range; `ADJUSTED` periods no longer block. Each generated period is born `ACCRUING` with `window_days` set to the whole days in its window and a `provisional_total_cents` priced immediately; `billable_days`, `tc_amount_cents`, `pc_amount_cents`, `total_amount_cents`, `submitted_total_cents`, `proposed_delta_cents`, `proposed_by_user_id`, `approved_by_user_id`, and `recognized_total_cents` are born null, and `approved_adjustment_cents` starts at 0 — all filled by the later stages below. A successful generation returns HTTP 201 with the created periods as an array in `data`.

The fee schedule is per monitor type and per thirty days, in integer cents. The technical component is 18,075 cents for `HOLTER`, 54,915 cents for `EVENT`, and 90,000 cents for `IMPLANTABLE`; the professional component is 2,425, 5,205, and 12,000 cents respectively. Pricing computes each line as its fee multiplied by the number of days, divided by thirty, and rounded half up to whole cents; the period total is the sum of the two already-rounded lines — rounding always happens per line, before summation, never on the sum. Two variants use that machinery: at generation time the provisional variant prices each window at its full `window_days` with suspensions ignored and stores the result as `provisional_total_cents`; the final variant, applied when a period matures, prices at `billable_days` and stores `tc_amount_cents`, `pc_amount_cents`, and their sum `total_amount_cents`.

Maturity arrives through the sweep's fifth stage: a period whose `end_date` has been reached moves from `ACCRUING` to `READY`. At that moment `billable_days` is computed as `window_days` minus the whole-day overlap between the window and the union of the episode's suspension intervals — an interval still open at sweep time treated as ending at the sweep time — and the final per-line amounts are written.

Submission is a specialist's act gated by three checks in ladder order. The referential gate fires first: the episode must have at least one `FINALIZED` diagnostic report, else `ERR_REPORT_NOT_FINALIZED` (HTTP 422). Then the fiscal gates: the episode must not be `SUSPENDED`, else `ERR_EPISODE_SUSPENDED` (HTTP 422), and `billable_days` must be at least 10, else `ERR_BELOW_MINIMUM_BILLABLE_DAYS` (HTTP 422). A successful submit moves the period from `READY` to `SUBMITTED`, snapshots `total_amount_cents` into `submitted_total_cents`, adds `total_amount_cents` into the episode's `total_billed_cents`, and anchors `recognized_total_cents` at the submitted figure.

Corrections after submission follow a segregated propose-and-approve loop, cycling `SUBMITTED` → `ADJUSTMENT_PROPOSED` → `ADJUSTED`, and a further proposal may start again from `ADJUSTED`. Any `BillingSpecialist` may propose an adjustment carrying a signed `delta_cents` and a free-text `reason`; the delta's magnitude may not exceed `submitted_total_cents`, else `ERR_ADJUSTMENT_EXCEEDS_BILLED` (HTTP 422). The proposal records `proposed_delta_cents` and stamps `proposed_by_user_id` with the caller's `X-User-ID`. Approval must come from a different specialist: if the approver's `X-User-ID` equals `proposed_by_user_id`, the call is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On approval the period moves to `ADJUSTED`, `approved_adjustment_cents` accumulates the proposed delta, `approved_by_user_id` records the approver, and `recognized_total_cents` is recomputed as `submitted_total_cents` plus `approved_adjustment_cents` — the invariant anchor that always ties the recognized figure to the submission plus its approved corrections. Billing periods can be listed with filters on `episode_id` and `status`, and read individually by `period_id`.

### 3.9. Device Return, Refurbishment, and Fleet Recovery

Once an episode is clinically terminal, an `InventoryManager` opens a return shipment for its device; attempting to open one earlier is rejected with `ERR_INVALID_STATE` (HTTP 409). The device must still be `DEPLOYED` — an episode whose device is already in transit cannot spawn a second open shipment, and such attempts fail generically with `ERR_INVALID_STATE`. Creation moves the device from `DEPLOYED` to `RETURN_IN_TRANSIT` and produces a shipment in `LABEL_CREATED` with `label_created_at` stamped from the clock, `due_at` set ten days out, and `received_at` null.

The sweep's second stage ages shipments, at most one transition per shipment per sweep. A `LABEL_CREATED` shipment whose `due_at` is strictly in the past moves to `OVERDUE`, and that transition fires a three-link cascade: a `RETURN_OVERDUE` compliance event is created on the episode; the episode's `strike_count` increments and the compliance mapping of §3.6 is re-evaluated while the episode is `MONITORING`; and if the strike count has reached three, the episode suspends and a suspension interval opens. An `OVERDUE` shipment whose lateness passes twenty days beyond `due_at` — the clock strictly later than `due_at` plus twenty days — is declared `LOST` on a later sweep, and its device moves to `LOST` as well, terminal for both.

Receipt closes the loop. An `InventoryManager` marks a shipment received from either `LABEL_CREATED` or `OVERDUE`; the shipment moves to its terminal `RECEIVED` state with `received_at` stamped, and the device moves from `RETURN_IN_TRANSIT` to `REFURBISHING` with `refurbishment_due_at` set 48 hours after receipt. The sweep's first stage then completes refurbishment: a `REFURBISHING` device whose `refurbishment_due_at` has been reached returns to `IN_STOCK`, reservable again under the eligibility rules of §3.2. Shipments can be listed with filters on `episode_id`, `device_id`, and `status`, and read individually by `shipment_id`. Under the conservation invariant of §2.10, a lost device shrinks the available pool but never the registered fleet — the counts of the six statuses still sum to the total.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`: every registration call, order creation, enrollment creation, transmission ingest, alert raise, report creation, billing-window generation, return-shipment creation, and the notify action (which returns the created notification attempt). Operations that modify an existing resource return `200 OK`, including all action endpoints, state transitions, and reads.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/patients` | Register a patient | EnrollmentCoordinator |
| GET | `/v1/patients/{patient_id}` | Read patient incl. derived open compliance events | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/physicians` | Register a physician | PlatformAdmin |
| GET | `/v1/physicians/{physician_id}` | Read physician | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/technicians` | Register a triage technician | PlatformAdmin |
| GET | `/v1/technicians/{technician_id}` | Read technician incl. load and fatigue fields | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/devices` | Register a device into inventory | InventoryManager |
| GET | `/v1/devices/{device_id}` | Read device | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/devices` | List devices (filters: status, model) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/monitoring-orders` | Create a monitoring order | Physician |
| GET | `/v1/monitoring-orders/{order_id}` | Read order | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/monitoring-orders` | List orders (filters: patient_id, ordering_physician_id, status) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/monitoring-orders/{order_id}/cancel` | Cancel an OPEN order; cascades aborts and device releases | Physician |
| POST | `/v1/monitoring-orders/{order_id}/enrollments` | Create enrollment, reserve device, supersede prior non-terminal enrollments | EnrollmentCoordinator |
| GET | `/v1/enrollments` | List enrollments (filters: order_id, device_id, episode_id, status) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/enrollments/{enrollment_id}` | Read enrollment | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/enrollments/{enrollment_id}/complete-education` | Record patient education | EnrollmentCoordinator |
| POST | `/v1/enrollments/{enrollment_id}/activate` | Activate monitoring: baseline signal check, create episode, deploy device | EnrollmentCoordinator |
| POST | `/v1/enrollments/{enrollment_id}/retry` | Retry a failed activation with a replacement device | EnrollmentCoordinator |
| POST | `/v1/enrollments/{enrollment_id}/abort` | Abort a non-terminal enrollment; release reserved device | EnrollmentCoordinator |
| GET | `/v1/episodes` | List episodes (filters: enrollment_id, patient_id, clinical_status, compliance_status) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/episodes/{episode_id}` | Read episode incl. derived counters | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/episodes/{episode_id}/complete` | Complete or terminate an episode | EnrollmentCoordinator |
| POST | `/v1/episodes/{episode_id}/resume` | Resume a SUSPENDED episode after follow-up | EnrollmentCoordinator |
| GET | `/v1/episodes/{id}/suspension-intervals` | List suspension intervals of an episode | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/episodes/{episode_id}/transmissions` | Ingest a device transmission | DeviceGateway |
| GET | `/v1/episodes/{id}/transmissions` | List transmissions of an episode | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin, DeviceGateway |
| POST | `/v1/transmissions/{transmission_id}/reprocess` | Reprocess a FAILED transmission with an updated signal reading | MonitoringTechnician |
| POST | `/v1/episodes/{episode_id}/alerts` | Raise an arrhythmia alert | DeviceGateway |
| GET | `/v1/alerts` | List alerts (filters: episode_id, assigned_technician_id, status, severity) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/alerts/{alert_id}` | Read alert | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/alerts/{alert_id}/acknowledge` | Acknowledge a NEW alert (self-assign) | MonitoringTechnician |
| POST | `/v1/alerts/{alert_id}/release` | Release an acknowledged alert back to NEW | MonitoringTechnician |
| POST | `/v1/alerts/{alert_id}/triage` | Triage an acknowledged alert; optional severity reclassification | MonitoringTechnician |
| POST | `/v1/alerts/{alert_id}/notify` | Notify the ordering physician; creates a notification attempt | MonitoringTechnician |
| POST | `/v1/alerts/{alert_id}/escalate` | Manually escalate a triaged alert | MonitoringTechnician |
| POST | `/v1/alerts/{alert_id}/close` | Close an alert as FALSE_POSITIVE or RESOLVED | MonitoringTechnician |
| GET | `/v1/notification-attempts` | List notification attempts (filters: alert_id, physician_id, status) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/notification-attempts/{attempt_id}` | Read notification attempt | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/notification-attempts/{attempt_id}/acknowledge` | Addressed physician acknowledges receipt | Physician |
| POST | `/v1/episodes/{episode_id}/reports` | Create a diagnostic report | Physician |
| GET | `/v1/reports` | List reports (filters: episode_id, reading_physician_id, status) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/reports/{report_id}` | Read report | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/reports/{report_id}/finalize` | Finalize a DRAFT or AMENDED report | Physician |
| POST | `/v1/reports/{report_id}/amend` | Amend a FINALIZED report | Physician |
| POST | `/v1/episodes/{episode_id}/billing-periods/generate` | Generate thirty-day half-open billing windows with provisional amounts | BillingSpecialist |
| GET | `/v1/billing-periods` | List billing periods (filters: episode_id, status) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/billing-periods/{period_id}` | Read billing period | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/billing-periods/{period_id}/submit` | Submit a READY billing period | BillingSpecialist |
| POST | `/v1/billing-periods/{period_id}/propose-adjustment` | Propose a signed adjustment delta | BillingSpecialist |
| POST | `/v1/billing-periods/{period_id}/approve-adjustment` | Approve a proposed adjustment; approver must differ from proposer | BillingSpecialist |
| POST | `/v1/episodes/{episode_id}/return-shipments` | Create a device return shipment for a terminal episode | InventoryManager |
| GET | `/v1/return-shipments` | List return shipments (filters: episode_id, device_id, status) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/return-shipments/{shipment_id}` | Read return shipment | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/return-shipments/{shipment_id}/mark-received` | Receive the returned device | InventoryManager |
| GET | `/v1/compliance-events` | List compliance events (filters: episode_id, status, event_type) | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| GET | `/v1/compliance-events/{event_id}` | Read compliance event | EnrollmentCoordinator, MonitoringTechnician, Physician, BillingSpecialist, InventoryManager, PlatformAdmin |
| POST | `/v1/compliance-events/{event_id}/resolve` | Record non-compliance follow-up resolution | EnrollmentCoordinator |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/v1/_ops/run-daily-sweep` | Run the daily sweep in pinned stage order | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_DEVICE_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_EPISODE_NOT_FOUND` | 404 Not Found |
| `ERR_ALERT_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DEVICE_NOT_IN_STOCK` | 409 Conflict |
| `ERR_DEVICE_NOT_REFURBISHED` | 409 Conflict |
| `ERR_EDUCATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_ACTIVE_EPISODE_EXISTS` | 409 Conflict |
| `ERR_BILLING_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CRITICAL_ALERTS_OPEN` | 422 Unprocessable Entity |
| `ERR_EPISODE_NOT_COMPLETED` | 422 Unprocessable Entity |
| `ERR_REPORT_NOT_FINALIZED` | 422 Unprocessable Entity |
| `ERR_OPEN_COMPLIANCE_EVENTS` | 422 Unprocessable Entity |
| `ERR_NOTIFICATION_NOT_ACKNOWLEDGED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_MRN` | 409 Conflict |
| `ERR_DUPLICATE_NPI` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_DUPLICATE_TRANSMISSION_SEQ` | 409 Conflict |
| `ERR_DEVICE_CATEGORY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_EMPTY_MONITORING_DATA` | 422 Unprocessable Entity |
| `ERR_EPISODE_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_BELOW_MINIMUM_BILLABLE_DAYS` | 422 Unprocessable Entity |
| `ERR_ADJUSTMENT_EXCEEDS_BILLED` | 422 Unprocessable Entity |
| `ERR_TECHNICIAN_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_INTERNAL` | 500 Internal Server Error |
