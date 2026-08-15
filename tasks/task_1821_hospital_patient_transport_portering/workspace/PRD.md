# Hospital Patient Transport API — Product Requirements Document

## 1. Introduction

A hospital's transport department lives and dies by minutes. Porters move patients between wards, intensive care, the emergency department, operating rooms, imaging suites, and discharge lounges all day long, and every late arrival cascades into idle OR time, rebooked imaging slots, and delayed discharges. This document specifies the Hospital Patient Transport API, the system of record for that operation: a queue of transport requests prioritized by clinical urgency, a dispatch board that matches trips to certified transporters and equipment, a hygiene pipeline that takes contaminated wheelchairs and stretchers out of circulation until cleaning is verified, and a staffing model that compares planned coverage against forecast and replayed demand.

Two technical commitments shape every workflow below. First, the server runs on a logical clock that administrators control directly, so service-level measurement, offer expiry, and schedule validation are deterministic rather than wall-clock accidents. Second, dispatch is optimistic but auditable: every offer carries a travel-time estimate, every acceptance recomputes that estimate against live congestion, every stale write is rejected rather than silently applied, and every breach of the response-time service level leaves a durable, attributable record. Implementers should read §2 for the system-wide contract before reconstructing any single workflow in §3.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly five roles: `RequestingClinician`, `TransportDispatcher`, `Transporter`, `HousekeepingStaff`, and `TransportSupervisor`. A request with missing headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the endpoint, that violates a role-payload restriction, or that fails an ownership check is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity works as follows. When `X-User-Role` is `Transporter`, `X-User-ID` is the `id` of the acting Transporter record; ownership checks on any resource that references a transporter — an assigned trip, a dispatch offer, the transporter profile in the path — compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `RequestingClinician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `requested_by` on each request the clinician creates and uses it for the own-request cancellation check, but never compares it to an entity `id`. When `X-User-Role` is `TransportDispatcher`, `X-User-ID` is likewise opaque and is not persisted on any entity. When `X-User-Role` is `HousekeepingStaff`, `X-User-ID` is opaque; the server records it as `performed_by` when that staffer finishes a cleaning task. When `X-User-Role` is `TransportSupervisor`, `X-User-ID` is opaque; the server records it as `verified_by` when the supervisor verifies a cleaning task.

Role-payload restrictions, stated here in summary and in full detail alongside each workflow in §3: a `Transporter` may set only their own status and only to `ON_SHIFT` or `OFF_SHIFT`; suspension and reinstatement are `TransportSupervisor`-only; `HousekeepingStaff` may advance cleaning only to `IN_PROGRESS` or `AWAITING_VERIFICATION`; verification and rework belong to the supervisor; supersede-as-duplicate belongs to the dispatcher alone.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every modification. `version` is a system-managed integer that increments by exactly one on every mutation of the resource. One entity is deliberately lighter: a `DelayRecord` carries only `id` and `created_at` — both `updated_at` and `version` are absent, because delay records are immutable observations.

Many operations in this domain mutate several resources atomically. Completing a trip, for example, updates the request, relocates the transporter, retires the equipment asset into the cleaning pipeline, and may spawn a cleaning task and delay records in the same transaction. Whenever a cascade touches an entity, that entity's `updated_at` refreshes and its `version` increments by one, exactly as if the client had mutated it directly.

### 2.5. The Logical Clock

All timestamps written by the server, and all elapsed-time computations, read a single logical clock — never the wall clock. Before any administrator action, the logical clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A supervisor-only capability sets the clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`. Sweep evaluation, offer expiry, schedule-past validation, dwell measurement, and service-level arithmetic all consume this clock.

### 2.6. Validation Cascade and Nested Resource Retrieval

Incoming requests are screened against ten tiers of checks, evaluated strictly in this order, and the first failing tier produces the response:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the five declared roles, else `ERR_UNAUTHENTICATED`.
2. **Authorization and ownership** — the role is allowed on the endpoint, role-payload restrictions hold, and ownership checks pass, else `ERR_FORBIDDEN_ROLE`.
3. **Body schema** — required fields are present, enums are in range, and integer bounds hold (positive travel minutes, a valid adequacy window, shift end after shift start, and a `duplicate_of_id` present when the close action is SUPERSEDE), else `ERR_VALIDATION`.
4. **Existence** — path identifiers exist, validated left to right, and body-referenced identifiers (such as `transporter_id`, `duplicate_of_id`, and location or equipment foreign keys) exist, else `ERR_NOT_FOUND`.
5. **Optimistic concurrency** — the version guard described in §2.7, else `ERR_STALE_VERSION`.
6. **Entity state** — the target resource is in a status that permits the operation; requests already in a terminal state answer `ERR_ALREADY_TERMINAL`, other state violations answer the appropriate `ERR_INVALID_*_STATE` error.
7. **Business safety** — isolation capability, cleaning dwell, and segregation-of-duty rules.
8. **Business referential** — referenced entities are in a fit state (no shifts for suspended transporters, supersede targets that qualify, shift coverage at clock-in).
9. **Business temporal** — scheduled times not in the past, shift non-overlap, and patient minimum separation.
10. **Uniqueness and capacity** — duplicate active requests, duplicate travel edges, duplicate demand-curve rows, transporter eligibility, selector empty pools, and travel-edge existence.

Because the tiers are ordered, a request that would fail several checks always reports the earliest failure: a stale offer attempt surfaces `ERR_STALE_VERSION` rather than a state error, and an unknown path id surfaces `ERR_NOT_FOUND` before any business rule is consulted. For nested paths such as a request's offers or a request's delay records, the parent identifier is validated first and a missing parent answers 404 before the child is examined.

### 2.7. Optimistic Concurrency Control on Dispatch

Exactly one endpoint participates in optimistic concurrency control: the creation of a dispatch offer against a transport request. The request body must carry `expected_request_version`, a non-optional integer holding the client last observed `version` of the target request. If that value does not equal the request's current `version` — because another writer has advanced it since the client last read it — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), so a dispatcher never unknowingly builds on a superseded view of the queue. No other endpoint accepts a version field; all other mutations proceed without an OCC check.

### 2.8. Time Arithmetic, Precision, and Rounding

All durations in the system are integer minutes; fractional minutes never appear in stored fields or responses. Elapsed durations (response times, delay attribution) are floored to whole minutes. The equipment-factor multiplication inside the travel-time estimate is rounded up to the next whole minute. The downstream-impact weighting on delay records uses round-half-up to whole minutes. Where a threshold involves a fraction of a target (the at-risk watermark), the fraction is computed first and floored to a whole minute before comparison.

### 2.9. Equipment Hygiene and Segregation of Duty

Wheelchairs and stretchers are shared, regulated assets, and the API treats hygiene as a first-class state dimension rather than an afterthought. An asset that completes a trip is never immediately reusable: it enters a cleaning pipeline whose depth depends on the isolation precaution of the trip that soiled it, and it cannot dispatch again until a supervisor verifies the cleaning. Verification is segregated from performance — the person who cleaned an asset may never be the person who signs it off — and assets flagged as isolation-contaminated carry that flag until verification clears it. Supervisors may also pull an asset out of service entirely; the full lifecycle, including rework, is specified in §3.7.

## 3. Business Logic & Workflows

### 3.1. Mapping the Estate: Locations and Travel Edges

Everything in the transport network happens between **Locations**. A supervisor registers each location with a unique `code` (for example `WARD-4E`), a display `name`, a `location_type` of `WARD`, `ICU`, `ED`, `OR`, `IMAGING`, `DISCHARGE_LOUNGE`, or `OTHER`, and a free-form `zone_code` grouping label that references nothing else in the system. The `location_type` matters beyond display: it drives the delay-cascade multiplier described in §3.6, so an OR-bound delay counts double while a ward-bound delay counts plain.

Travel between locations is modelled as directed **Travel Edges**. Creating one requires `from_location_id`, `to_location_id`, a positive integer `base_minutes` (walking time for a porter with standard equipment), and a positive integer `airborne_minutes` (the replacement leg time used when a trip runs under airborne precautions and must take the longer corridor). The directed pair is unique: a second edge with the same origin and destination is rejected with `ERR_TRAVEL_EDGE_DUPLICATE`. Dispatchers and supervisors can list edges, filtering by `from_location_id` or `to_location_id`. Edges are the substrate of dispatch: when an offer is built and either leg of the journey has no edge, creation fails with `ERR_NO_TRAVEL_EDGE`, as detailed in §3.4 — with one exception, namely that a transporter already standing at the pickup location needs no deadhead edge at all.

### 3.2. The Transporter Roster: Registration, Certification, and Shift Coverage

A supervisor registers each **Transporter** with a `name` and a `home_location_id`, and optionally a `certified_equipment` list (a subset of `WHEELCHAIR`, `STRETCHER`, and `BARIATRIC_STRETCHER`, defaulting to empty), an `oxygen_certified` flag (default false, required to escort oxygen trips), and an `isolation_certified` flag (default false, required for any trip under precautions). A new transporter starts `OFF_SHIFT` with `current_location_id` initialized to their home; `current_location_id` is thereafter updated to each trip's destination on completion. The roster list supports filtering by `status`, `home_location_id`, and `current_location_id`, and each transporter's shifts and offers can be listed individually, each with an optional `status` filter.

Clocking in moves a transporter from `OFF_SHIFT` to `ON_SHIFT` and is gated on shift coverage: a `PLANNED` staffing shift must cover the current logical instant, meaning `shift_start` is at or before now and now is strictly before `shift_end` — otherwise `ERR_NO_SHIFT_COVERAGE`. Attempting to clock in from `SUSPENDED` (or while already `ON_SHIFT`) is rejected with `ERR_INVALID_TRANSPORTER_STATE`. Clocking out, and suspension, are only permitted when the transporter holds no active assignment — no request assigned to them in `ASSIGNED`, `AT_PICKUP`, or `IN_TRANSIT` — and has no `PENDING` offer addressed to them; violations answer `ERR_INVALID_TRANSPORTER_STATE`. A transporter acting on their own record may request only `ON_SHIFT` or `OFF_SHIFT`; any attempt by a `Transporter` to set `SUSPENDED` is rejected with `ERR_FORBIDDEN_ROLE`. Suspension from `ON_SHIFT`, and reinstatement from `SUSPENDED` back to `OFF_SHIFT`, are supervisor-only actions. Every status change increments the transporter's `version`.

**Staffing Shifts** are planned by supervisors as half-open intervals: `shift_start` is inclusive, `shift_end` is exclusive, and `shift_end` must be later than `shift_start` or the creation fails schema validation with `ERR_VALIDATION`. A new shift may not overlap another `PLANNED` shift of the same transporter — half-open semantics mean back-to-back shifts that merely touch are allowed — and a genuine overlap is rejected with `ERR_SHIFT_OVERLAP`. Planning a shift for a `SUSPENDED` transporter is rejected with `ERR_TRANSPORTER_SUSPENDED`. Cancellation moves a shift from `PLANNED` to `CANCELLED` and is permitted only while the shift is `PLANNED`, otherwise `ERR_INVALID_SHIFT_STATE`; cancelled shifts are excluded from the scheduled-headcount counts in §3.8.

### 3.3. Placing a Transport Request

A `RequestingClinician` opens a **Transport Request** by supplying the `patient_ref` (an opaque patient identifier used for duplicate and separation checks), the `origin_location_id` and `destination_location_id`, a `priority` of `ROUTINE`, `URGENT`, or `STAT`, and the `required_equipment` — `PORTER_ONLY`, `WHEELCHAIR`, `STRETCHER`, or `BARIATRIC_STRETCHER`. Three optional fields refine the trip: `oxygen_required` (default false), `isolation_precaution` of `NONE`, `CONTACT`, `DROPLET`, or `AIRBORNE` (default `NONE`), and two datetimes, `scheduled_pickup_time` and `appointment_deadline`. The server stamps `requested_by` from the caller's `X-User-ID`.

A fresh request lands in `QUEUED` with `sla_posture` `ON_TRACK`; the counters `escalation_count`, `decline_count`, `release_count`, and `offer_seq_count` all start at zero; `excluded_transporter_ids` starts empty; `assigned_transporter_id`, `assigned_equipment_id`, and `duplicate_of_id` start null; the computed fields `committed_eta_minutes` and `response_minutes` remain null until dispatch and arrival respectively; and the lifecycle timestamps `at_pickup_at`, `picked_up_at`, `completed_at`, and `closed_at` are null until their events occur.

Three guards protect the queue at creation time, in the cascade order of §2.6. A `scheduled_pickup_time` or `appointment_deadline` earlier than the current logical instant is rejected with `ERR_SCHEDULE_IN_PAST`. Two non-terminal requests for the same `patient_ref` whose `scheduled_pickup_time` values fall strictly less than 75 minutes apart violate the patient minimum-separation rule and are rejected with `ERR_PATIENT_SCHEDULE_CONFLICT` — bookings exactly 75 minutes apart are acceptable. And if the same `patient_ref` already has a non-terminal request to the same `destination_location_id` — one in `QUEUED`, `ASSIGNED`, `AT_PICKUP`, or `IN_TRANSIT` — creation is rejected with `ERR_DUPLICATE_ACTIVE_REQUEST`. Clinicians, dispatchers, supervisors, and transporters may all read requests; the list filters by `status`, `priority`, `sla_posture`, `origin_location_id`, `destination_location_id`, `assigned_transporter_id`, `assigned_equipment_id`, and `duplicate_of_id`.

### 3.4. Dispatch: Offers, Eligibility, and Equipment Selection

Dispatch begins when a `TransportDispatcher` creates a **Dispatch Offer** on a `QUEUED` request. The payload optionally names a `transporter_id`; omitting it asks the server to select. The payload must also carry `expected_request_version` per §2.7 — and because the concurrency tier outranks the state tier, a stale offer attempt is rejected with `ERR_STALE_VERSION` even if the request has meanwhile left `QUEUED`; only when the version matches does the state check run, rejecting offers on non-`QUEUED` requests with `ERR_INVALID_REQUEST_STATE`.

Eligibility is then enforced in cascade order. The isolation safety gate comes first: a trip whose `isolation_precaution` is anything other than `NONE` requires an `isolation_certified` transporter, else `ERR_ISOLATION_CAPABILITY_MISMATCH`. The remaining checks belong to the constraint tier. A manually named transporter must be `ON_SHIFT`, hold no active assignment, have no other `PENDING` offer addressed to them, and not appear in the request's `excluded_transporter_ids`; they must be `oxygen_certified` when `oxygen_required` is set; and when `required_equipment` is not `PORTER_ONLY`, that equipment type must appear in their `certified_equipment`. Any such failure rejects the offer with `ERR_TRANSPORTER_INELIGIBLE`. Travel edges must exist from the transporter's `current_location_id` to the origin and from the origin to the destination, else `ERR_NO_TRAVEL_EDGE`. Finally, when the trip needs equipment, at least one `AVAILABLE` asset of the matching type must exist, else `ERR_NO_AVAILABLE_EQUIPMENT`.

When `transporter_id` is omitted, the server auto-selects: it ranks all eligible transporters by the deadhead `base_minutes` from their current location to the request's origin, ascending, breaking ties by transporter `created_at` ascending, and an empty pool rejects the offer with `ERR_NO_ELIGIBLE_TRANSPORTER`. Equipment selection is deterministic in both manual and automatic flows: among `AVAILABLE` assets of the required type, the pick is the earliest `created_at`, breaking ties by `asset_tag` ascending; the chosen asset flips to `RESERVED` and is recorded as the request's `assigned_equipment_id`. `PORTER_ONLY` trips reserve nothing and leave `assigned_equipment_id` null.

Creating an offer supersedes any existing `PENDING` offer on the same request — the older offer moves to `SUPERSEDED` and its reserved asset returns to `AVAILABLE`, and notably no auto-dispatch evaluation runs on this supersession path. The new offer is born `PENDING` with `offer_seq` set to the next per-request sequence number (the request's `offer_seq_count` increments in step), and its `estimated_travel_minutes` snapshots the dispatch-variant travel estimate. The request's `version` increments.

The travel estimate itself is built from two legs. The deadhead leg is zero minutes when the transporter is already at the pickup location — no edge required — and otherwise the `base_minutes` of the edge from the transporter's current location to the origin. The loaded leg uses the edge from origin to destination: its `airborne_minutes` when the trip's isolation precaution is `AIRBORNE`, otherwise its `base_minutes`, and that figure is then multiplied by an equipment factor — 1.0 for `PORTER_ONLY`, 1.1 for `WHEELCHAIR`, 1.25 for `STRETCHER`, and 1.4 for `BARIATRIC_STRETCHER` — with the product rounded up to a whole minute. Two minutes of oxygen setup are added when `oxygen_required` is set. The dispatch estimate is the sum of deadhead, loaded, and oxygen components, and a missing edge on either required leg is what raises `ERR_NO_TRAVEL_EDGE`.

Offers do not live forever. A time-driven sweep expires any `PENDING` offer that is strictly more than 10 minutes old, moving it to `EXPIRED` — an offer exactly 10 minutes old stays `PENDING`. Expiry returns its reserved asset to `AVAILABLE` but deliberately runs no auto-dispatch evaluation, and it leaves the request itself untouched: no version bump and no exclusion entry.

Auto-dispatch evaluation is the system's habit of re-homing freed equipment. It runs when an asset returns to `AVAILABLE` through an offer decline, a request close (either action), a trip release, a cleaning verification, or a supervisor returning an asset to service — and it runs in none of the two remaining cases, namely offer expiry and manual-offer supersession. The evaluation considers `QUEUED` requests with no `PENDING` offer whose `required_equipment` matches the freed asset's type, ranks them by priority (`STAT` first, then `URGENT`, then `ROUTINE`) and then by `created_at` ascending, and takes the first candidate. For that candidate it builds the eligible transporter pool — `ON_SHIFT`, no active assignment, no `PENDING` offer addressed, absent from `excluded_transporter_ids`, certifications matching the trip's isolation, oxygen, and equipment demands, and a travel edge from the transporter's current location to the request origin — ranks it by deadhead minutes then transporter `created_at`, and creates a `PENDING` offer while reserving the freed asset. If the pool is empty, no offer is created and the asset simply stays `AVAILABLE`. `PORTER_ONLY` requests never trigger and never participate in auto-dispatch, because no asset ever frees for them.

### 3.5. Running the Trip: Acceptance, Pickup, Completion, Release

The addressed transporter answers an offer with a `decision` of `ACCEPT` or `DECLINE`. Only the transporter named by the offer may respond — an offer whose `transporter_id` does not equal the caller's `X-User-ID` is rejected with `ERR_FORBIDDEN_ROLE` — and only while the offer is `PENDING`, otherwise `ERR_INVALID_OFFER_STATE`. Both branches receive equal ceremony.

Acceptance cascades. The request must still be `QUEUED` (`ERR_INVALID_REQUEST_STATE` otherwise) and the transporter still `ON_SHIFT` (`ERR_INVALID_TRANSPORTER_STATE` otherwise). The offer becomes `ACCEPTED` with `responded_at` stamped, the request advances from `QUEUED` to `ASSIGNED` with `assigned_transporter_id` set from the offer, and the server commits an ETA: `committed_eta_minutes` is the commit-variant estimate, which takes the identical deadhead, loaded, and oxygen legs of the dispatch estimate and adds a congestion surcharge of 2 minutes for each trip currently `IN_TRANSIT`, counting at most 5 such trips. The two estimates therefore agree exactly when no other trip is in transit and diverge as the corridors fill. The request's `version` increments.

Declination reshuffles the board. The offer becomes `DECLINED` with `responded_at` stamped, the request's `decline_count` increments, and the declining transporter is appended to `excluded_transporter_ids`, removing them from all future selection for that request. The offer's reserved asset, if any, returns to `AVAILABLE`, and auto-dispatch evaluation runs for the freed asset. The request's `version` increments.

Once assigned, the trip advances through trip events posted by the assigned transporter — for every event, a caller whose `X-User-ID` differs from the request's `assigned_transporter_id` is rejected with `ERR_FORBIDDEN_ROLE`, except that a dispatcher may force a release. The `event` field selects the transition, and an optional `cause_code` may accompany completion.

`ARRIVE_PICKUP` moves the request from `ASSIGNED` to `AT_PICKUP` (any other state answers `ERR_INVALID_REQUEST_STATE`). It stamps `at_pickup_at`, computes `response_minutes` as the whole-minute floor of the span from `created_at` to `at_pickup_at`, and freezes `sla_posture` one final time: `BREACHED` when `response_minutes` exceeds the priority's target, `AT_RISK` when it reaches at least three-quarters of the target rounded down to a whole minute, otherwise `ON_TRACK`. From this moment on, sweeps never mutate the posture again. The request's `version` increments.

`PICKUP` moves the request from `AT_PICKUP` to `IN_TRANSIT`. If an asset is assigned, it must be `RESERVED` — any other asset state rejects the event with `ERR_INVALID_ASSET_STATE` — and on success `picked_up_at` is stamped and the asset moves to `IN_USE`. The request's `version` increments.

`COMPLETE` moves the request from `IN_TRANSIT` to `COMPLETED` and carries the heaviest cascade in the system. `completed_at` is stamped and `assigned_transporter_id` cleared; the transporter's `current_location_id` is updated to the trip's destination; the assigned asset, if any, moves to `AWAITING_CLEANING`, and when the trip ran under any isolation precaution its `isolation_contaminated` flag is set true. The asset's entry into `AWAITING_CLEANING` creates a `CleaningTask` in `PENDING` whose `task_type` is `DEEP` for isolation trips and `STANDARD` otherwise, linked to both the asset and the request. Completion also writes up to two delay records: when an `appointment_deadline` was set and completion fell after it, and no `APPOINTMENT_LATE` record exists yet, one is created with `delay_minutes` equal to the whole-minute floor of the overrun, `cause_code` taken from the event payload's `cause_code` or `OTHER` when none was supplied, and `recorded_via` `COMPLETION`; and when `response_minutes` exceeded the priority's target and no `SLA_BREACH` record exists yet, one is created with `delay_minutes` equal to `response_minutes` minus the target, `cause_code` `SYSTEM`, and `recorded_via` `COMPLETION`. The request's `version` increments.

`RELEASE` returns an `ASSIGNED` request to `QUEUED` and may be invoked by the assigned transporter or forced by a dispatcher. The assignment is cleared, `release_count` increments, the transporter who had been holding the trip is appended to `excluded_transporter_ids`, the assigned asset returns to `AVAILABLE` with auto-dispatch evaluation, and the request's `version` increments.

Closing a request takes an `action` of `CANCEL` or `SUPERSEDE`, with `reason` and `duplicate_of_id` as the supporting fields.

Cancellation is open to clinicians, dispatchers, and supervisors, with sharp role boundaries. From a terminal state it is rejected with `ERR_ALREADY_TERMINAL`; from `IN_TRANSIT` it is rejected with `ERR_INVALID_REQUEST_STATE`; from `QUEUED`, `ASSIGNED`, or `AT_PICKUP` it proceeds — but a `RequestingClinician` may cancel only their own requests, meaning `requested_by` must equal the caller's `X-User-ID` (otherwise `ERR_FORBIDDEN_ROLE`), and only while the request is still `QUEUED`, whereas dispatchers and supervisors may cancel any cancellable request. Side effects: any `PENDING` offer on the request moves to `SUPERSEDED` and its reserved asset returns to `AVAILABLE` with auto-dispatch evaluation; when cancelling from `ASSIGNED` or `AT_PICKUP`, the assigned asset — which was never in use — returns to `AVAILABLE` with no cleaning obligation, the transporter is freed, `assigned_transporter_id` is cleared, and auto-dispatch evaluation runs. The close stamps `closed_at`, records the payload's `reason` as `cancel_reason`, settles the request in `CANCELLED`, and increments the request's `version`.

Supersession is the dispatcher's duplicate-consolidation tool and is restricted to that role. The request must be `QUEUED` — a terminal request answers `ERR_ALREADY_TERMINAL`, any other state `ERR_INVALID_REQUEST_STATE`. The payload must include `duplicate_of_id` (its absence fails schema validation with `ERR_VALIDATION`), and the nominated original must exist (an unknown identifier answers `ERR_NOT_FOUND`), must not be the request itself, must still be `QUEUED`, and must carry the same `patient_ref`; a target that fails any of those conditions is rejected with `ERR_NOT_DUPLICATE`. On success the request records the payload's `duplicate_of_id` as its own `duplicate_of_id`, stamps `closed_at`, supersedes any `PENDING` offer with its asset returned to `AVAILABLE` plus auto-dispatch evaluation, and increments `version`. Dispatchers and supervisors can also list a request's delay records, oldest first.

### 3.6. Service Levels, Escalation Sweeps, and Delay Attribution

The response-time service level assigns each priority a target: 120 minutes for `ROUTINE`, 45 for `URGENT`, and 15 for `STAT`. While a request sits in `QUEUED` or `ASSIGNED`, its `sla_posture` is a live function of elapsed time — the whole-minute floor of the span from `created_at` to now. Elapsed time strictly greater than the target means `BREACHED`; elapsed time of at least three-quarters of the target, that fraction rounded down to a whole minute, without exceeding the target means `AT_RISK`; anything less is `ON_TRACK`. The boundary is pinned: a request whose elapsed time equals its target exactly is still `AT_RISK`, because breach demands a strict excess.

A supervisor runs the time-driven sweep, which processes its four steps in a pinned order and reports `offers_expired`, `requests_escalated`, and `sla_records_created`. First, `PENDING` offers past their time-to-live expire, oldest offer first, exactly as §3.4 specifies. Second, the sweep recomputes `sla_posture` for every `QUEUED` or `ASSIGNED` request in `created_at` ascending order, incrementing `version` on each request whose posture actually changes. Third, any `QUEUED` request whose freshly evaluated posture is `BREACHED` and whose priority is not yet `STAT` escalates one tier — `ROUTINE` to `URGENT` to `STAT` — incrementing `escalation_count`, and its posture is immediately recomputed against the new, tighter-or-looser target; because a fresh escalation compares the same elapsed time against a different target, posture may legitimately drop back to `AT_RISK` or even `ON_TRACK`, and this post-escalation recompute is the only way posture ever moves downward — it never relaxes directly. Fourth, for each request whose final posture is `BREACHED` while `QUEUED` or `ASSIGNED` and which has no `SLA_BREACH` delay record yet, the sweep creates one with `delay_minutes` equal to elapsed minus the current priority's target, `cause_code` `SYSTEM`, and `recorded_via` `SWEEP`.

Every **Delay Record** names its `transport_request_id`, a `record_kind` of `SLA_BREACH` or `APPOINTMENT_LATE`, the attributed `delay_minutes`, a weighted `impact_minutes`, a `cause_code` of `NO_TRANSPORTER`, `NO_EQUIPMENT`, `CLEANING_BACKLOG`, `PATIENT_NOT_READY`, `SYSTEM`, or `OTHER`, and a `recorded_via` of `SWEEP` or `COMPLETION`. The impact figure translates raw lateness into downstream schedule damage: `delay_minutes` multiplied by 2.0 when the destination's `location_type` is `OR`, by 1.5 for `IMAGING`, and by 1.0 for `WARD`, `ICU`, `ED`, `DISCHARGE_LOUNGE`, and `OTHER`, with the product rounded half-up to whole minutes. An OR-bound trip that runs 20 minutes late therefore records 20 attributed minutes but 40 impact minutes.

### 3.7. Cleaning, Verification, and Equipment Return to Service

Each **Cleaning Task** links an `equipment_asset_id` to the `transport_request_id` that soiled it and walks a four-state pipeline, advanced through a `to_state` payload naming the desired next state. A `HousekeepingStaff` member starts a `PENDING` task by advancing it to `IN_PROGRESS` — the task must actually be `PENDING` (else `ERR_INVALID_CLEANING_STATE`) and its asset must be waiting, in `AWAITING_CLEANING` (else `ERR_INVALID_ASSET_STATE`). Starting stamps `started_at` and moves the asset to `IN_CLEANING`. Finishing moves the task from `IN_PROGRESS` to `AWAITING_VERIFICATION`: for a `DEEP` task at least 15 minutes must have elapsed since `started_at` — exactly 15 minutes suffices — otherwise the advance is rejected with `ERR_DWELL_NOT_ELAPSED`, while `STANDARD` tasks carry no dwell requirement. Finishing stamps `finished_at` and records the finisher's `X-User-ID` as `performed_by`. An optional `note` may accompany any advance.

Verification belongs to the supervisor and enforces segregation of duty: a verifier whose `X-User-ID` equals the task's `performed_by` is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403). A successful verification stamps `verified_at`, records `verified_by`, moves the task to `VERIFIED`, and cascades to the asset — back to `AVAILABLE`, `isolation_contaminated` cleared, and auto-dispatch evaluation run for the freed asset. When the work is not good enough, the supervisor instead sends the task from `AWAITING_VERIFICATION` back to `IN_PROGRESS` as rework: `rework_count` increments, `started_at` resets to the current instant, the asset stays `IN_CLEANING`, and the dwell requirement applies afresh to the next finish. Housekeeping, dispatchers, and supervisors can list tasks and filter by `status`, `equipment_asset_id`, or `transport_request_id`.

Separately from cleaning, a supervisor governs serviceability directly. Pulling an asset `OUT_OF_SERVICE` is permitted from `AVAILABLE` or `RESERVED`; attempting it from `IN_USE`, `AWAITING_CLEANING`, or `IN_CLEANING` is rejected with `ERR_INVALID_ASSET_STATE`. Pulling a `RESERVED` asset is allowed but consequential — the trip holding that reservation will fail its pickup with `ERR_INVALID_ASSET_STATE` when the moment comes. Returning an asset to `AVAILABLE` is permitted only from `OUT_OF_SERVICE` (anything else again answers `ERR_INVALID_ASSET_STATE`), and the return runs auto-dispatch evaluation. Each service-status change carries a `service_status` payload field and increments the asset's `version`. The asset registry itself lists with `status`, `equipment_type`, and `current_location_id` filters.

### 3.8. Demand Curves and Staffing Adequacy

Supervisors teach the system expected demand one **Demand Curve** row at a time: a `day_type` of `WEEKDAY` or `WEEKEND`, an `hour_block` from 0 to 23, a `priority`, an `expected_requests` volume of zero or more, and a positive `mean_service_minutes`. The triple of `day_type`, `hour_block`, and `priority` is unique, and a colliding row is rejected with `ERR_DEMAND_CURVE_CONFLICT`.

The staffing-adequacy read is a computed projection, not a stored entity. It takes a `date`, an `hour_block`, a `window_hours` length, and a `variant` of `FORECAST` or `REPLAY`, and the window must be sane — `window_hours` at least 1 and `hour_block` plus `window_hours` at most 24, else `ERR_VALIDATION`. Under `FORECAST`, the system derives the day type from the date — Monday through Friday map to `WEEKDAY`, Saturday and Sunday to `WEEKEND` — and for each block in the window multiplies each priority's `expected_requests` by its `mean_service_minutes`, sums the three products into total expected service minutes for the block, divides by 60, and rounds up to a whole headcount. Under `REPLAY`, each block instead looks at requests completed within the trailing 24 hours whose `created_at` hour matches the block, sums their actual service minutes — `completed_at` minus `at_pickup_at` — divides by 60, and rounds up; a block with no matching completions requires zero transporters. In both variants the rounding order is pinned: the ceiling is taken per block first, and only then are the per-block integers summed — summing first and rounding once is a different, incorrect algorithm.

The scheduled side of the ledger counts distinct `transporter_id` values across `PLANNED` shifts that cover any block in the window — a shift covers a block when it starts before the block's end and ends after the block's start, half-open semantics throughout — unioned across all blocks; cancelled shifts never count. The response reports `required_transporters`, `scheduled_transporters`, and their difference as `gap`, so a negative gap names exactly how thin coverage runs.

## 4. Endpoint Definitions

All endpoints live under the API's transport surface. Operations that create a new resource — a location, edge, transporter, asset, request, offer, shift, or demand-curve row — return `201 Created`. Operations that read, modify, advance, close, respond, compute, set the clock, or run the sweep return `200 OK`. Error responses follow §2.2 and the cascade in §2.6.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/transport/locations` | Create a hospital location | TransportSupervisor |
| POST | `/transport/travel-edges` | Create a directed travel edge between locations | TransportSupervisor |
| GET | `/transport/travel-edges` | List travel edges | TransportDispatcher, TransportSupervisor |
| GET | `/transport/travel-edges/{id}` | Get one travel edge | TransportDispatcher, TransportSupervisor |
| POST | `/transport/transporters` | Register a transporter (starts `OFF_SHIFT`, located at home) | TransportSupervisor |
| GET | `/transport/transporters` | List transporters | TransportDispatcher, TransportSupervisor |
| GET | `/transport/transporters/{id}` | Get one transporter | TransportDispatcher, TransportSupervisor, Transporter |
| POST | `/transport/transporters/{id}/set-status` | Clock in or out; suspend or reinstate | Transporter, TransportSupervisor |
| GET | `/transport/transporters/{id}/shifts` | List shifts of a transporter | TransportDispatcher, TransportSupervisor, Transporter |
| GET | `/transport/transporters/{id}/offers` | List dispatch offers addressed to a transporter | TransportDispatcher, TransportSupervisor, Transporter |
| POST | `/transport/equipment-assets` | Register an equipment asset (starts `AVAILABLE`) | TransportSupervisor |
| GET | `/transport/equipment-assets` | List equipment assets | TransportDispatcher, TransportSupervisor |
| GET | `/transport/equipment-assets/{id}` | Get one equipment asset | TransportDispatcher, TransportSupervisor |
| POST | `/transport/equipment-assets/{id}/set-service-status` | Pull an asset out of service or return it | TransportSupervisor |
| POST | `/transport/requests` | Create a transport request | RequestingClinician |
| GET | `/transport/requests` | List transport requests | RequestingClinician, TransportDispatcher, TransportSupervisor, Transporter |
| GET | `/transport/requests/{id}` | Get one transport request | RequestingClinician, TransportDispatcher, TransportSupervisor, Transporter |
| POST | `/transport/requests/{id}/close` | Cancel a request or supersede it as a duplicate | RequestingClinician, TransportDispatcher, TransportSupervisor |
| POST | `/transport/requests/{id}/offers` | Create a dispatch offer for a request | TransportDispatcher |
| GET | `/transport/requests/{id}/offers` | List offers of a request, oldest first | TransportDispatcher, TransportSupervisor |
| POST | `/transport/dispatch-offers/{id}/respond` | Accept or decline a pending offer | Transporter |
| POST | `/transport/requests/{id}/trip-events` | Advance a trip (arrive, pick up, complete) or release it | Transporter, TransportDispatcher |
| GET | `/transport/requests/{id}/delay-records` | List delay records of a request, oldest first | TransportDispatcher, TransportSupervisor |
| POST | `/transport/cleaning-tasks/{id}/advance` | Advance a cleaning task (start, finish, verify, or rework) | HousekeepingStaff, TransportSupervisor |
| GET | `/transport/cleaning-tasks` | List cleaning tasks | HousekeepingStaff, TransportDispatcher, TransportSupervisor |
| GET | `/transport/cleaning-tasks/{id}` | Get one cleaning task | HousekeepingStaff, TransportDispatcher, TransportSupervisor |
| POST | `/transport/staffing-shifts` | Plan a transporter shift | TransportSupervisor |
| POST | `/transport/staffing-shifts/{id}/set-status` | Cancel a planned shift | TransportSupervisor |
| POST | `/transport/demand-curves` | Create a demand-curve row | TransportSupervisor |
| GET | `/transport/staffing/adequacy` | Required versus scheduled transporters for a window | TransportDispatcher, TransportSupervisor |
| POST | `/_clock/set_current_utc` | Set the logical clock | TransportSupervisor |
| POST | `/_sweeps/run` | Run the time-driven sweep in its pinned order | TransportSupervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST_STATE` | 409 |
| `ERR_INVALID_OFFER_STATE` | 409 |
| `ERR_INVALID_ASSET_STATE` | 409 |
| `ERR_INVALID_CLEANING_STATE` | 409 |
| `ERR_INVALID_TRANSPORTER_STATE` | 409 |
| `ERR_INVALID_SHIFT_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_ISOLATION_CAPABILITY_MISMATCH` | 422 |
| `ERR_DWELL_NOT_ELAPSED` | 422 |
| `ERR_SEGREGATION_OF_DUTY` | 403 |
| `ERR_TRANSPORTER_SUSPENDED` | 422 |
| `ERR_NOT_DUPLICATE` | 409 |
| `ERR_NO_SHIFT_COVERAGE` | 422 |
| `ERR_SCHEDULE_IN_PAST` | 422 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_PATIENT_SCHEDULE_CONFLICT` | 409 |
| `ERR_DUPLICATE_ACTIVE_REQUEST` | 409 |
| `ERR_TRAVEL_EDGE_DUPLICATE` | 409 |
| `ERR_DEMAND_CURVE_CONFLICT` | 409 |
| `ERR_TRANSPORTER_INELIGIBLE` | 422 |
| `ERR_NO_ELIGIBLE_TRANSPORTER` | 422 |
| `ERR_NO_AVAILABLE_EQUIPMENT` | 422 |
| `ERR_NO_TRAVEL_EDGE` | 422 |
