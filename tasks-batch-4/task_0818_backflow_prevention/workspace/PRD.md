# Backflow Prevention API — Product Requirements Document

## 1. Introduction

Water utilities are legally responsible for protecting the public distribution main from cross-connection backflow — the reverse flow of contaminated or non-potable water from a customer's premises into the community supply. This API is the system of record for a utility's backflow prevention program. It tracks every mechanical backflow assembly by the service connection it protects, enforces the annual test cycle that keeps each assembly certified, verifies that the people performing those tests hold a valid state certification at the moment of testing, and adjudicates the pass/fail reports they submit.

The platform's central concern is a single, continuously re-derived judgement about each premises: is this connection compliant, drifting toward non-compliance, already delinquent, or shut off? That judgement gates what may happen to the connection's devices and drives the escalation machinery — hazard surveys that assign a risk tier, shutoff notices with tiered cure windows, daily monetary penalties that accrue while devices sit overdue, repair and replacement orders that bring devices back into service, and periodic reminder batches that warn owners before a test lapses. Because the program runs on calendar deadlines rather than wall-clock events, the system evaluates every date-sensitive rule against a controllable logical clock so that the passage of time can be tested deterministically.

Three parties interact with the system: utility operators who administer the program end to end, certified testers who schedule and report field tests, and premises owners who monitor their own connections and request repairs. The sections below specify the shared platform contract first, then the domain workflows, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles: `UtilityAdmin`, `Tester`, and `PremisesOwner`. If either header is missing, or if `X-User-Role` is not one of these three recognized values, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_UNAUTHORIZED`.

The three roles differ in how `X-User-ID` binds to the data they may touch. When `X-User-Role` is `UtilityAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any record's `id`, and an admin may act on any connection, device, tester, report, survey, notice, order, or reminder. When `X-User-Role` is `PremisesOwner`, `X-User-ID` is likewise an opaque identifier, but ownership is enforced by value: a premises owner may act only where the owning connection's `owner_user_id` field equals the caller's `X-User-ID`. The `owner_user_id` stored on a `ServiceConnection` is not a foreign key to any entity — it is simply the opaque `X-User-ID` string of the owner, and every ownership check on a connection (or on any device, survey, notice, order, or reminder reachable from that connection) compares that stored string to the caller's `X-User-ID`. When `X-User-Role` is `Tester`, `X-User-ID` is the `id` of the acting `Tester` entity; ownership checks on a test appointment or a test report compare the resource's `tester_id` field to `X-User-ID`, so a tester may only book, cancel, or report against work they own.

A failed ownership comparison — a tester acting on another tester's appointment, or an owner reading a connection they do not own — is an `ERR_UNAUTHORIZED` (HTTP 403), distinct from the `ERR_UNAUTHENTICATED` (HTTP 401) returned for missing or unrecognized headers.

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

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a section states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every persisted entity in the system — service connections, backflow devices, testers, test appointments, test reports, hazard surveys, shutoff notices, repair orders, and reminders — carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits recording when the row was first created. All of these entities are mutable and additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every change to the resource) and a `version` integer that starts at 1 on creation and increments by one on every mutation of that resource. The `version` field is the basis for optimistic concurrency control described in §2.9.

A subtle but load-bearing rule concerns the `ServiceConnection.version`: several child operations mutate the connection as a side effect (issuing or rescinding a notice, a device entering or leaving repair, finalizing a survey), and each such mutation bumps the connection's `version` and refreshes its `updated_at`. Where a specific transition is spelled out in §3 as "increment the connection's version", that increment is in addition to — not instead of — the automatic bump that accompanies any recomputation of the connection's derived fields.

### 2.5. The Logical Clock and Temporal Evaluation

All date-sensitive logic in this system is evaluated against a server-controlled logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly advanced it holds that value and never falls back to real-world time. An administrative capability sets the clock to a supplied instant (`to_iso8601`) and returns the new value as `current_utc`. Advancing the clock has side effects of its own: any tester whose certification window has closed relative to the new clock value is expired (see §3.1), and every due-date, overdue, penalty, and posture computation is performed against the clock's current reading. Throughout this document, "now" or "the current time" always means the logical clock value, denoted `current_utc`.

### 2.6. Compliance Posture — the Derived Aggregate Gate

Each `ServiceConnection` exposes a derived field, `compliance_posture`, which is one of `COMPLIANT`, `AT_RISK`, `NON_COMPLIANT`, or `SHUTOFF`. It is never set directly by a client; it is recomputed from the connection's own flags and its children every time a relevant child transition occurs and every time the connection is read. The recomputation evaluates four cases in strict order and stops at the first that matches:

1. If the connection's water is not flowing — that is, `water_service_active` is false — the posture is `SHUTOFF`. This flag is the sole driver of the `SHUTOFF` posture.
2. Otherwise, if the connection has at least one overdue device (its `overdue_device_count` is greater than zero), or any device on it is in `NEEDS_REPAIR` status, or it has at least one open shutoff notice (its `open_notice_count` is greater than zero), the posture is `NON_COMPLIANT`.
3. Otherwise, if at least one of the connection's devices in `ACTIVE` or `NEEDS_REPAIR` status is inside the upcoming-due window — meaning the whole number of days from `current_utc` to that device's `next_test_due_date` is at least 0 and at most 30 — the posture is `AT_RISK`.
4. Otherwise, the posture is `COMPLIANT`.

The 30-day upcoming-due lead is the same window used to generate `UPCOMING_DUE` reminders. The supporting counts are themselves derived: `overdue_device_count` is the number of devices on the connection whose status is `ACTIVE` or `NEEDS_REPAIR` and whose `next_test_due_date` is strictly earlier than `current_utc`; `open_notice_count` is the number of the connection's shutoff notices in `ISSUED` status; `protected_device_count` is the number of devices on the connection whose status is `ACTIVE` or `NEEDS_REPAIR`. All four derived quantities and the posture are recomputed together, and any recomputation that changes the stored connection refreshes `updated_at` and bumps `version`. Because posture is a strict, ordered cascade, a mid-flight change to any input (a device slipping overdue, a notice being issued, a repair completing) can move a connection between postures without a direct client request against the connection itself.

### 2.7. Entity Reachability and Reference Resolution

The domain is flat: entities are peers linked by foreign-key fields carried in request bodies, and there is no nesting of resource identifiers in URL paths. Every child collection is reachable by filtering its own list endpoint — for example, the devices of a connection are retrieved by listing devices filtered on `service_connection_id`, and a tester's reports by listing reports filtered on `tester_id`. When a request references resources — the path `id` plus any foreign keys in the body — the system validates their existence left to right in the order they appear, and returns the not-found error specific to the first missing entity: `ERR_CONNECTION_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_TESTER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or `ERR_REPAIR_ORDER_NOT_FOUND`, each carrying HTTP 404.

### 2.8. Precision, Rounding, and Penalty Accrual

Two numeric domains require exact rounding rules. Monetary penalties are held in whole cents as integers; wherever a fractional cent arises during penalty computation it is rounded half up to the nearest whole cent. Weighted hazard scores are rounded half up to two decimal places, and the aggregate compliance rate in the utility report is likewise rounded half up to two decimal places. Pressure readings on test reports are compared, not rounded, and a reading exactly equal to a threshold satisfies it (the comparisons are inclusive).

The order of operations for penalty accrual is contractually fixed and must not be reordered: each overdue device's daily penalty is computed and rounded to whole cents individually, and only then are the per-device whole-cent amounts summed into `total_penalty_cents`. Rounding the grand total instead of each device would drift the result and is incorrect. The full penalty formula, its per-tier multiplier, and its daily rate live in §3.6.

### 2.9. Optimistic Concurrency Control

Finalizing a hazard survey is guarded by optimistic concurrency on its service connection. A finalize request must carry `expected_service_connection_version`, which is the `version` of the target `ServiceConnection` as the client last observed it. If that value does not equal the connection's current `version` at the moment of finalization, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and no state changes. This is a stale-version guard, not a timing guard: because finalizing a survey rewrites the connection's `risk_tier` and supersedes the connection's prior effective survey, a finalize that still carries a `version` from before some other writer advanced the connection reflects an outdated view and must be refused, reducing the supersede race to a deterministic version check. Finalization is the only endpoint that takes a version field; no other write endpoint accepts or requires one.

### 2.10. Order of Validation

When several checks could reject the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. The ladder, highest priority first, is: (1) authentication — headers present and role recognized, else `ERR_UNAUTHENTICATED`; (2) authorization and ownership — the role may perform the operation and, for tester- or owner-scoped writes, `X-User-ID` matches the owning identity, else `ERR_UNAUTHORIZED`; (3) existence of every referenced resource, left to right, else the entity-specific not-found error; (4) target state permits the transition, else the endpoint-specific state-conflict error; (5) tester certification for test-report and test-appointment writes, else `ERR_TESTER_NOT_CERTIFIED`; (6) the connection-not-shut-off gate on device removal, else `ERR_CONNECTION_SHUTOFF`; (7) the rescind-eligibility gate, else `ERR_NOTICE_RESCIND_BLOCKED`; (8) the enforcement-due gate, else `ERR_ENFORCEMENT_NOT_DUE`; (9) appointment time-range well-formedness, else `ERR_INVALID_TIME_RANGE`; (10) tester double-booking, else `ERR_TESTER_DOUBLE_BOOKED`; (11) premises buffer, else `ERR_PREMISES_BUFFER_CONFLICT`; (12) replacement-serial presence on replacement completion, else `ERR_REPLACEMENT_SERIAL_REQUIRED`; (13) uniqueness of account, serial, and certification numbers, else `ERR_DUPLICATE_VALUE`; (14) body field presence, types, enum membership, and score ranges, else `ERR_VALIDATION`; and finally (15) the optimistic-concurrency version match on finalize, else `ERR_STALE_VERSION`. A check earlier in this ladder always masks a violation that a later check would also have caught.

## 3. Business Logic & Workflows

### 3.1. Establishing the Program: Connections, Devices, and Testers

A `UtilityAdmin` seeds the program by registering a **service connection** for a premises. Registration supplies an `account_number` (the utility account, which must be non-empty and unique across all connections), the premises `address`, the `owner_user_id` that will own the connection, and a `hazard_class` that is either `HIGH_HAZARD` or `LOW_HAZARD`. A newly registered connection opens in the `COMPLIANT` posture with `risk_tier` at `LOW`, `water_service_active` true, and every derived count — `protected_device_count`, `overdue_device_count`, `open_notice_count`, and `total_penalty_cents` — at zero. Registering a second connection with an `account_number` that already exists is rejected with `ERR_DUPLICATE_VALUE`.

Against a connection, the admin installs **backflow devices**, each identified by a `service_connection_id` linking it to the connection it protects and a `serial_number` that must be non-empty and unique across all devices. A device declares its `device_type` — one of `RP` (reduced-pressure), `DC` (double-check), `PVB` (pressure-vacuum-breaker), or `DCDA` (double-check-detector) — and a `hazard_rating` of `HIGH` or `LOW` that establishes the device's contribution to the connection's effective risk floor. The `test_interval_months` sets how many months elapse between required tests; it must be at least 1 and defaults to 12 (the annual cycle) when omitted. The `install_date` is the ISO 8601 UTC date the assembly went into service. A new device starts with its `status` field set to `ACTIVE` and its `last_pass_date` unset (it has no accepted passing test yet). Adding a device increments the connection's `protected_device_count` and triggers a posture recomputation. A duplicate `serial_number` is rejected with `ERR_DUPLICATE_VALUE`.

The device's `next_test_due_date` is computed at creation by advancing a baseline date by `test_interval_months` whole calendar months. Advancing by months preserves the day-of-month of the baseline; when the target month is shorter than that day (for example, advancing a January 31 baseline into February), the due date is clamped to the last day of the target month, and the time-of-day is copied unchanged from the baseline. Before the device has any accepted passing test — while `last_pass_date` is null — the baseline is the `install_date`. Once a passing test is accepted the baseline shifts to `last_pass_date` (see §3.3), which produces a strictly later due date than the install-based value.

Certified field technicians are registered as **testers** by a `UtilityAdmin`, supplying the tester's `name`, a `certification_number` that is unique across all testers, and the inclusive certification validity window bounded by `cert_effective_date` and `cert_expiry_date` (both ISO 8601 UTC). A tester begins in `ACTIVE` status. A duplicate `certification_number` is rejected with `ERR_DUPLICATE_VALUE`. An admin may move a tester from `ACTIVE` to `SUSPENDED` and back; reinstating a suspended tester to `ACTIVE` is permitted only while the certification is still within its window, that is while `current_utc` is on or before `cert_expiry_date`. Independently of these manual actions, advancing the logical clock past a tester's `cert_expiry_date` — `current_utc` strictly later than `cert_expiry_date` — automatically moves that tester to `EXPIRED`, whether it was previously `ACTIVE` or `SUSPENDED`; `EXPIRED` is thus reached as a side effect of the clock, not by an operator call.

### 3.2. Scheduling On-Site Tests

A `Tester` books an on-site **test appointment** for a device by supplying the `device_id` to be tested, their own `tester_id`, and the test window `scheduled_start` (inclusive) and `scheduled_end` (exclusive). The appointment opens in `BOOKED` status and is owned by the tester whose `tester_id` it carries. Several guards protect the booking, and they are evaluated in the precedence of §2.10.

The target device must be testable — its status must be `ACTIVE` or `NEEDS_REPAIR`; a device that has been replaced or removed cannot be scheduled, and the attempt is rejected with `ERR_DEVICE_NOT_TESTABLE`. The tester must be currently certified: the tester's status must be `ACTIVE` and the appointment's `scheduled_start` must fall on or after `cert_effective_date` and on or before `cert_expiry_date`; otherwise the booking is rejected with `ERR_TESTER_NOT_CERTIFIED`. The window itself must be well-formed, with `scheduled_end` strictly later than `scheduled_start`; an ill-formed window yields `ERR_INVALID_TIME_RANGE`.

Two scheduling-conflict rules then apply. First, a tester may not be double-booked: the new appointment's half-open interval from `scheduled_start` up to `scheduled_end` must not overlap the interval of any other `BOOKED` appointment for the same `tester_id`. Because the intervals are half-open, back-to-back adjacency — where one appointment's start equals another's end — does not overlap and is allowed; any true overlap is rejected with `ERR_TESTER_DOUBLE_BOOKED`. Second, a premises-buffer rule spaces out visits to the same site: for any two `BOOKED` appointments on devices that share a service connection, the gap between their intervals must be at least 60 minutes. Intervals closer than that buffer — including exact adjacency, which the tester rule would otherwise permit — are rejected with `ERR_PREMISES_BUFFER_CONFLICT`. A booked appointment may be cancelled by its owning tester or by an admin, moving it from `BOOKED` to `CANCELLED` and freeing both the tester's and the premises' time windows; cancelling an appointment that is not `BOOKED` returns `ERR_APPOINTMENT_NOT_BOOKED`.

### 3.3. Submitting and Adjudicating Test Reports

After a test is performed, the `Tester` submits a **test report** referencing the `device_id` tested, their own `tester_id`, and the `test_date` on which the work was done. The report also carries the field readings: `relief_valve_differential_psid` (the relief-valve opening differential, required and meaningful only for `RP` assemblies and ignored for others), `check_valve_1_psid` (the first check-valve holding differential, always supplied), and `check_valve_2_psid` (the second check-valve holding differential, meaningful for `DC` and `DCDA` assemblies and ignored otherwise). All three readings, when present, must be at least 0. Submission requires the same two upstream guards as booking: the device must be testable (status `ACTIVE` or `NEEDS_REPAIR`, else `ERR_DEVICE_NOT_TESTABLE`) and the tester must be certified with the `test_date` falling within the inclusive window from `cert_effective_date` to `cert_expiry_date` and the tester in `ACTIVE` status (else `ERR_TESTER_NOT_CERTIFIED`). The report opens in `SUBMITTED` status.

The report's `result` — `PASS` or `FAIL` — is computed at submission from the readings and the device type, with every comparison inclusive so that a reading exactly at its threshold passes. For an `RP` device, the result is `PASS` only when the relief-valve differential is at least 2.0 psid and the first check valve holds at least 1.0 psid. For a `DC` or `DCDA` device, the result is `PASS` only when both the first and second check valves each hold at least 1.0 psid. For a `PVB` device, the result is `PASS` when the first check valve holds at least 1.0 psid. Any reading below its threshold makes the result `FAIL`.

A `UtilityAdmin` adjudicates a submitted report, and the two outcomes diverge sharply. Accepting a report moves it from `SUBMITTED` to `ACCEPTED`. When the accepted report's result is `PASS`, the device's `last_pass_date` is set to the report's `test_date`, the device's `next_test_due_date` is recomputed from that new pass baseline (the from-last-pass variant of §3.1), and the connection's posture is recomputed; furthermore, if an `ISSUED` shutoff notice with reason `OVERDUE_TEST` exists on the connection and the device is no longer overdue as a result, that notice is auto-rescinded and the connection's `open_notice_count` is decremented. When the accepted report's result is `FAIL`, the device enters a three-link cascade: the device transitions `ACTIVE → NEEDS_REPAIR`; because a device is now in repair, the connection's posture is recomputed to `NON_COMPLIANT`; and because the connection is now non-compliant, a shutoff notice with reason `FAILED_TEST` is auto-issued in `ISSUED` status and the connection's `open_notice_count` is incremented by one. This fail path also increments the connection's `version` by one. Adjudicating a report that is not in `SUBMITTED` status — whether accept or reject — is rejected with `ERR_REPORT_NOT_PENDING`.

Rejecting a submitted report instead moves it from `SUBMITTED` to `REJECTED` and requires a `rejection_reason`, which is stored on the report; a reject attempt without a `rejection_reason` fails body validation. A rejection changes no device or connection state — it neither updates due dates nor touches posture, notices, or counts.

### 3.4. Repair, Replacement, and Retirement of Devices

When a device needs attention, a `PremisesOwner` or a `UtilityAdmin` opens a **repair order** naming the `device_id`, an `order_type` of `REPAIR` or `REPLACEMENT`, a free-text `description` of the problem, and — for replacements — a `replacement_serial_number` for the new assembly (this may be omitted at creation but is required at completion). The order opens in `OPEN` status.

A `UtilityAdmin` completes an open order, which requires the order to be `OPEN` (else `ERR_REPAIR_NOT_OPEN`) and the target device to currently be in `NEEDS_REPAIR` status (else `ERR_DEVICE_NOT_REPAIRABLE`). For a `REPLACEMENT` order, a `replacement_serial_number` must be present at completion; its absence is rejected with `ERR_REPLACEMENT_SERIAL_REQUIRED`. Completion diverges on the order type:

- A `REPAIR` completion returns the device to service via the `NEEDS_REPAIR → ACTIVE` cascade: the device becomes `ACTIVE`; the connection's posture is recomputed, clearing `NON_COMPLIANT` if no other blocker remains; because no device is now in `NEEDS_REPAIR` and the connection has no overdue devices, any `ISSUED` shutoff notice whose reason is `FAILED_TEST` or `UNREPAIRED_DEVICE` is auto-rescinded and `open_notice_count` decremented; and the connection's `version` is incremented by one.
- A `REPLACEMENT` completion retires the old device via the `NEEDS_REPAIR → REPLACED` cascade and installs a fresh one: the old device becomes `REPLACED`, and a new device is created in `ACTIVE` status on the same connection, carrying the `replacement_serial_number` as its serial and copying the old device's `device_type`, `hazard_rating`, and `test_interval_months`, with its `install_date` set to `current_utc`. The connection's `protected_device_count` is deliberately unchanged: the retiring device leaves the protected set and the new device enters it, a compensating one-out-one-in invariant. The connection's posture is recomputed and the same auto-rescind of `FAILED_TEST`/`UNREPAIRED_DEVICE` notices applies as on the repair path. The new serial must itself be unique across all devices; a collision is rejected with `ERR_DUPLICATE_VALUE`.

An open order may instead be cancelled by a `UtilityAdmin` or `PremisesOwner`, moving it from `OPEN` to `CANCELLED` with no device state change; cancelling an order that is not `OPEN` returns `ERR_REPAIR_NOT_OPEN`.

Separately, a `UtilityAdmin` may retire a device outright. Removal takes a device from `ACTIVE` or `NEEDS_REPAIR` to the terminal `REMOVED` state, decrements the connection's `protected_device_count`, and recomputes posture. Removal is blocked in two ways: a device whose status is neither `ACTIVE` nor `NEEDS_REPAIR` cannot be removed (`ERR_DEVICE_NOT_REMOVABLE`), and no device may be removed while its connection's `compliance_posture` is `SHUTOFF` (`ERR_CONNECTION_SHUTOFF`). Both `REPLACED` and `REMOVED` are terminal device states.

### 3.5. Hazard Surveys and Risk Tiering

The risk profile of a premises is captured by a **hazard survey**. Either a `UtilityAdmin` or a `PremisesOwner` may create a draft survey against a `service_connection_id`, scoring three hazard dimensions each on a 0-to-40 scale: `premise_use_score`, `chemical_exposure_score`, and `auxiliary_supply_score`. Each score must be an integer no less than 0 and no greater than 40. The survey opens in `DRAFT` status and carries two computed tiers that remain blank until finalization: `assessed_risk_tier` and `effective_risk_tier`.

A `UtilityAdmin` finalizes a draft survey, which is guarded by the optimistic-concurrency check of §2.9: the request carries `expected_service_connection_version`, and finalization requires the survey to be in `DRAFT` status (else `ERR_SURVEY_NOT_DRAFT`) and the supplied version to match the connection's current `version` (else `ERR_STALE_VERSION`). Finalization moves the survey `DRAFT → FINALIZED` and computes both tiers. The `assessed_risk_tier` comes from the questionnaire alone. First a weighted score is formed by taking three-tenths of `premise_use_score`, plus four-tenths of `chemical_exposure_score`, plus three-tenths of `auxiliary_supply_score`, and rounding that sum half up to two decimal places. A base tier follows from the weighted score: `HIGH` when the weighted score is at least 70, `MODERATE` when it is at least 40 but below 70, and `LOW` otherwise. A conditional floor is then applied from individual inputs: the floor is `HIGH` if `chemical_exposure_score` is at least 35; otherwise the floor is `MODERATE` if `auxiliary_supply_score` is at least 30; otherwise the floor is `LOW`. The `assessed_risk_tier` is the higher of the base tier and the floor, ranking the tiers `LOW` below `MODERATE` below `HIGH`.

The `effective_risk_tier` raises the assessed tier by the connection's device hazard floor: if any device on the connection with status `ACTIVE` or `NEEDS_REPAIR` has a `hazard_rating` of `HIGH`, the device floor is `HIGH`, otherwise `LOW`; the effective tier is the higher of `assessed_risk_tier` and that device floor. On finalization the connection's `risk_tier` is set to this `effective_risk_tier`, any prior `FINALIZED` survey on the same connection is moved to `SUPERSEDED`, the connection's posture is recomputed, and the connection's `version` is incremented by one. The connection's effective `risk_tier` therefore always reflects the most recently finalized survey, and it is this tier that drives penalty multipliers and shutoff grace windows.

### 3.6. Shutoff Notices, Cure Windows, Enforcement, and Penalties

A **shutoff notice** warns a premises that its water service is at risk. A `UtilityAdmin` may issue one manually against a `service_connection_id` with a `reason` of `OVERDUE_TEST`, `FAILED_TEST`, or `UNREPAIRED_DEVICE`; notices are also auto-issued by the system, as when an accepted failing test raises a `FAILED_TEST` notice. On issuance the notice records its `issued_date` as `current_utc`, selects its cure window `grace_days` from the connection's `risk_tier` — 30 days for `LOW`, 14 days for `MODERATE`, and 7 days for `HIGH` — and sets its `enforcement_due_date` to the issued date plus that many days. The notice opens in `ISSUED` status; issuing it increments the connection's `open_notice_count` and recomputes posture.

An issued notice can be rescinded, enforced, or cleared automatically. Rescinding moves the notice `ISSUED → RESCINDED`, decrements `open_notice_count`, and recomputes posture, but only when the connection has cured: it must have no device in `NEEDS_REPAIR` status and an `overdue_device_count` of zero, otherwise the rescind is blocked with `ERR_NOTICE_RESCIND_BLOCKED`; rescinding a notice not in `ISSUED` status returns `ERR_NOTICE_NOT_ISSUED`. Enforcing a notice is a temporal action: it is permitted only once the logical clock has reached the deadline, that is when `current_utc` is on or after the notice's `enforcement_due_date` (else `ERR_ENFORCEMENT_NOT_DUE`), and only on a notice still in `ISSUED` status (else `ERR_NOTICE_NOT_ISSUED`). Enforcement moves the notice `ISSUED → ENFORCED`, sets the connection's `water_service_active` to false, drives its posture to `SHUTOFF`, and decrements `open_notice_count`. Once shut off, the connection can be brought back by a `UtilityAdmin` restore, which is allowed only when the connection is currently in `SHUTOFF` posture (else `ERR_NOT_SHUTOFF`) and has fully cured — an `overdue_device_count` of zero, no device in `NEEDS_REPAIR`, and an `open_notice_count` of zero. Restore sets `water_service_active` back to true and recomputes posture, which lands on `COMPLIANT` or, if a device is still inside the upcoming-due window, on `AT_RISK`.

While devices sit overdue, a monetary penalty accrues, surfaced as the connection's `total_penalty_cents` and recomputed at read time against the logical clock whenever a connection is listed or fetched. The penalty applies a risk multiplier drawn from the connection's `risk_tier`: 1.0 for `LOW`, 1.5 for `MODERATE`, and 2.0 for `HIGH`. The system considers only devices on the connection whose status is `ACTIVE` or `NEEDS_REPAIR` and whose `next_test_due_date` is strictly earlier than `current_utc`. For each such device it counts the whole days overdue by taking the floor of the elapsed time from the due date to now measured in days (always at least 1 for a device that is overdue), multiplies the base daily rate of 333 cents by the risk multiplier and by those overdue days, and rounds that per-device amount half up to whole cents. The per-device whole-cent penalties are then summed into `total_penalty_cents`. As stressed in §2.8, each device is rounded to whole cents first and only then summed — never summed and rounded once.

### 3.7. Reminders and Utility Reporting

To warn owners before a test lapses, a `UtilityAdmin` runs a reminder batch that evaluates every device against the logical clock. For each device whose status is `ACTIVE` or `NEEDS_REPAIR`, the batch creates a **reminder** whose `device_id` names the device, whose `generated_date` is `current_utc`, and whose `days_until_due` is the whole number of days from `current_utc` to the device's `next_test_due_date` at generation time — negative once the device is overdue. The reminder's `reminder_type` is `UPCOMING_DUE` when `days_until_due` is at least 0 and at most 30, and `OVERDUE` when `days_until_due` is below 0. The batch returns a summary object reporting `generated_count` (total reminders created), `upcoming_count` (those of type `UPCOMING_DUE`), and `overdue_count` (those of type `OVERDUE`).

Finally, a `UtilityAdmin` can pull an aggregate compliance report across the connection pool, optionally narrowing the pool by a `hazard_class` filter. The report recomputes each connection's posture at read time, then returns `total_connections` (the size of the pool), `compliant_count` (connections whose posture is `COMPLIANT`), `non_compliant_count` (connections whose posture is `NON_COMPLIANT` or `SHUTOFF`), and `compliance_rate`. The compliance rate is the compliant count divided by the total, multiplied by 100 and rounded half up to two decimal places; as an empty-pool boundary, when there are no connections in the pool the rate is exactly 0.00 with no division performed.

## 4. Endpoint Definitions

Operations that register a new, stand-alone resource — a service connection, device, tester, appointment, report, survey, notice, repair order, or a reminder batch — return `201 Created`. Operations that modify an existing resource, including all state-transition actions and the logical-clock control, return `200 OK`. The table below is a routing summary only; the request payloads, response side effects, and business rules for each operation are specified in §3 and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-connections` | Register a new service connection | UtilityAdmin |
| GET | `/service-connections` | List service connections (posture/penalty/counts recomputed) | UtilityAdmin, PremisesOwner |
| GET | `/service-connections/{id}` | Fetch one connection with recomputed derived fields | UtilityAdmin, PremisesOwner |
| POST | `/service-connections/{id}/restore` | Restore water service after a shutoff | UtilityAdmin |
| POST | `/devices` | Add a backflow device to a connection | UtilityAdmin |
| GET | `/devices` | List/filter devices | UtilityAdmin, PremisesOwner |
| GET | `/devices/{id}` | Fetch one device | UtilityAdmin, PremisesOwner |
| POST | `/devices/{id}/remove` | Retire a device from service | UtilityAdmin |
| POST | `/testers` | Register a certified tester | UtilityAdmin |
| GET | `/testers` | List testers | UtilityAdmin |
| GET | `/testers/{id}` | Fetch one tester | UtilityAdmin, Tester |
| POST | `/testers/{id}/suspend` | Suspend a tester's certification | UtilityAdmin |
| POST | `/testers/{id}/reinstate` | Reinstate a suspended tester | UtilityAdmin |
| POST | `/test-appointments` | Book an on-site test appointment | Tester |
| GET | `/test-appointments` | List/filter appointments | UtilityAdmin, Tester |
| GET | `/test-appointments/{id}` | Fetch one appointment | UtilityAdmin, Tester |
| POST | `/test-appointments/{id}/cancel` | Cancel a booked appointment | Tester, UtilityAdmin |
| POST | `/test-reports` | Submit a backflow test report | Tester |
| GET | `/test-reports` | List/filter test reports | UtilityAdmin, Tester |
| GET | `/test-reports/{id}` | Fetch one test report | UtilityAdmin, Tester |
| POST | `/test-reports/{id}/accept` | Accept a submitted report | UtilityAdmin |
| POST | `/test-reports/{id}/reject` | Reject a submitted report | UtilityAdmin |
| POST | `/hazard-surveys` | Create a draft hazard survey | UtilityAdmin, PremisesOwner |
| GET | `/hazard-surveys` | List/filter hazard surveys | UtilityAdmin, PremisesOwner |
| GET | `/hazard-surveys/{id}` | Fetch one hazard survey | UtilityAdmin, PremisesOwner |
| POST | `/hazard-surveys/{id}/finalize` | Finalize a draft survey (OCC-guarded) | UtilityAdmin |
| POST | `/shutoff-notices` | Manually issue a shutoff notice | UtilityAdmin |
| GET | `/shutoff-notices` | List/filter shutoff notices | UtilityAdmin, PremisesOwner |
| GET | `/shutoff-notices/{id}` | Fetch one shutoff notice | UtilityAdmin, PremisesOwner |
| POST | `/shutoff-notices/{id}/rescind` | Rescind an issued notice | UtilityAdmin |
| POST | `/shutoff-notices/{id}/enforce` | Enforce an issued notice (shuts off water) | UtilityAdmin |
| POST | `/repair-orders` | Open a repair or replacement order | PremisesOwner, UtilityAdmin |
| GET | `/repair-orders` | List/filter repair orders | UtilityAdmin, PremisesOwner |
| GET | `/repair-orders/{id}` | Fetch one repair order | UtilityAdmin, PremisesOwner |
| POST | `/repair-orders/{id}/complete` | Complete an open order | UtilityAdmin |
| POST | `/repair-orders/{id}/cancel` | Cancel an open order | UtilityAdmin, PremisesOwner |
| POST | `/reminders/generate` | Batch-generate due/overdue reminders | UtilityAdmin |
| GET | `/reminders` | List/filter reminders | UtilityAdmin, PremisesOwner |
| GET | `/reminders/{id}` | Fetch one reminder | UtilityAdmin, PremisesOwner |
| GET | `/utility-report` | Aggregate compliance report across connections | UtilityAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | UtilityAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_TIME_RANGE` | 400 |
| `ERR_CONNECTION_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_TESTER_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_SURVEY_NOT_FOUND` | 404 |
| `ERR_NOTICE_NOT_FOUND` | 404 |
| `ERR_REPAIR_ORDER_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_TESTABLE` | 409 |
| `ERR_DEVICE_NOT_REMOVABLE` | 409 |
| `ERR_REPORT_NOT_PENDING` | 409 |
| `ERR_SURVEY_NOT_DRAFT` | 409 |
| `ERR_NOTICE_NOT_ISSUED` | 409 |
| `ERR_REPAIR_NOT_OPEN` | 409 |
| `ERR_DEVICE_NOT_REPAIRABLE` | 409 |
| `ERR_APPOINTMENT_NOT_BOOKED` | 409 |
| `ERR_NOT_SHUTOFF` | 409 |
| `ERR_TESTER_NOT_CERTIFIED` | 422 |
| `ERR_CONNECTION_SHUTOFF` | 409 |
| `ERR_NOTICE_RESCIND_BLOCKED` | 409 |
| `ERR_ENFORCEMENT_NOT_DUE` | 409 |
| `ERR_TESTER_DOUBLE_BOOKED` | 409 |
| `ERR_PREMISES_BUFFER_CONFLICT` | 409 |
| `ERR_REPLACEMENT_SERIAL_REQUIRED` | 422 |
| `ERR_DUPLICATE_VALUE` | 409 |
| `ERR_STALE_VERSION` | 412 |

