# Vehicle Safety & Emissions Inspection API — Product Requirements Document

## 1. Introduction

State-licensed inspection stations sit at the intersection of two very different obligations: they are a service business that books lanes, runs a checklist, and collects a fee, and they are an arm of a regulator that must guarantee no vehicle receives a certificate it has not earned. This API models that dual mandate end to end. It governs the full journey of a vehicle through a station — from the moment a receptionist books a lane or opens a walk-in, through the inspector's safety checklist and OBD-II emissions test, to the pass/fail decision, the issuance (or voiding) of a certificate and sticker, and the eventual remittance of results to the jurisdiction in a state report batch.

The system is deliberately compliance-first. An inspection record is the audit hub that every downstream artifact — certificates, repair orders, waiver requests, report lines — references and depends on, and the integrity of that record gates everything. A failed emissions test opens a bounded reinspection loop and a repair-cost ledger that can make a vehicle eligible for a waiver; a reinspection that reopens an already-certified record must cascade backward and revoke the certificate and its physical sticker so the books stay honest. Because lane time and shared analyzer capacity are finite, scheduling is a temporal-overlap problem with two distinct interval disciplines, and because certificate issuance and state submission are points where two operators can disagree about what they last saw, those writes are guarded by optimistic concurrency control. The sections that follow specify the contract precisely where the API's shape is fixed, and describe the business rules in the narrative order a station actually works through them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing or malformed in either header is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `StationManager`, `Inspector`, `Receptionist`, and `StateAuditor`. A `StationManager` is the station superuser — it configures stations, lanes, and class profiles, issues and voids certificates, verifies and rejects repair orders, decides waivers, manages state report batches, and may additionally perform every operation an `Inspector` or `Receptionist` can perform. An `Inspector` performs the inspection itself: opening records, recording checklist items and OBD tests, deciding pass or fail, and opening reinspections. A `Receptionist` runs the front desk: booking appointments and walk-ins, checking vehicles in, cancelling, marking no-shows, holding and releasing analyzer windows, and intaking repair orders and waiver requests. A `StateAuditor` is the external jurisdiction reviewer who accepts or rejects submitted state report batches and otherwise has read-only access.

All four roles carry an **opaque** identity. When `X-User-Role` is `StationManager`, `Inspector`, `Receptionist`, or `StateAuditor`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`; there are no per-user ownership checks in this domain, and authorization is decided purely by role.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order. Every list response carries the pagination bookkeeping inside the `meta` object, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system share a common set of system-managed fields. Each carries an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp, recorded as an ISO 8601 UTC string with three fractional digits at the moment of creation; an `updated_at` timestamp, refreshed in the same format whenever the resource is mutated; and a `version`, an integer that begins at its initial value and increments by one on every mutation. These four fields apply to `Station`, `VehicleClassProfile`, `Lane`, `AnalyzerReservation`, `Appointment`, `InspectionRecord`, `ChecklistResult`, `EmissionsTest`, `RepairOrder`, `WaiverRequest`, `Certificate`, and `StateReportBatch`.

`StateReportLine` is the one exception. A report line is immutable once attached: it carries only an `id` and a `created_at`, and has no `updated_at` and no `version`. Any narrative below that speaks of "bumping the version" or "refreshing `updated_at`" therefore never applies to a `StateReportLine`.

### 2.5. State Propagation and Cascade Integrity

Many operations mutate more than the resource they directly target. Whenever a transition's side effects touch a second resource, the system applies every named effect, and each touched resource independently has its `updated_at` refreshed and its `version` incremented. The most consequential example is the reinspection of an already-passed vehicle, which is specified as a chain of causally linked steps in §3: the supersession of the chain-head record drives the certificate from `ACTIVE` to `VOID`, and the certificate's own void effect in turn surrenders the sticker. Each link fires because the prior link fired, not because the client asked for it directly, and every resource altered along the way advances its own `version`.

### 2.6. Nested Resource Retrieval and Reference Resolution

Endpoints that name a resource by id in their path, and operations that reference other resources by id in their body, validate those references left to right in the order they appear. The first id that does not resolve to an existing entity causes the request to be rejected with `ERR_NOT_FOUND` before any further reference or business rule is evaluated. This applies uniformly: a check-in for a missing appointment, a checklist line whose `record_id` points to nothing, or a report line whose batch id is unknown all surface as a not-found rejection at the first unresolved reference.

### 2.7. Monetary Precision and Rounding

All money in the system is expressed and stored as integer cents, and most calculations involve no rounding at all — fees, repair spend, and batch totals are computed and summed as whole-cent integers. The single place rounding occurs is the state remittance surcharge, which multiplies a service portion by a fractional rate. There, amounts are rounded using the round-half-up method to whole cents, and the rounding is applied per line before any summation, never after. The precise ordering of that rounding is specified in §3 where the surcharge is described.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource by supplying that parent's last-observed `version`. These are non-optional inputs on the operations named below; an endpoint not named here takes no version field.

Issuing a certificate is guarded against a stale inspection record. The issuance request must carry `expected_record_version`, the value of the target `InspectionRecord`'s `version` that the client last read. If that value does not equal the record's current `version` — for example because the record was reinspected and superseded after the client read its `PASSED` state, advancing its `version` — the issuance is refused with `ERR_STALE_VERSION` and HTTP 412, so the station cannot certify a result that has since been superseded.

Submitting a state report batch is guarded against a stale batch. The submit request must carry `expected_batch_version`, the value of the `StateReportBatch`'s `version` the client last read. If a line was attached or detached after that read — each such change bumps the batch's `version` and recomputes its totals — the submitter's view of `line_count` and `total_reported_fee_cents` is stale, and submission is refused with `ERR_STALE_VERSION` and HTTP 412.

### 2.9. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. Authentication comes first: a missing or malformed header yields `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted for the operation yields `ERR_FORBIDDEN`. Existence is third: any unresolved path or body reference yields `ERR_NOT_FOUND`. Request well-formedness is fourth: a missing required field, an invalid enum member, a VIN that is not exactly 17 uppercase alphanumeric characters, a `state_code` that is not exactly two uppercase letters, or a negative integer where a non-negative one is required yields `ERR_INVALID_REQUEST`. State legality is fifth: attempting a transition from a state in which it is not defined yields `ERR_INVALID_STATE`. Optimistic-concurrency staleness is sixth, applying to certificate issuance and batch submission as described in §2.8, and yields `ERR_STALE_VERSION`. Only after all of these pass does the system evaluate the operation-specific business rules described in §3. Where two business rules both apply to one operation, the operation's narrative states which is evaluated first.

### 2.10. Vehicle Classes and Enumerations

Vehicle class is a closed enumeration used by class profiles, appointments, and inspection records alike: a vehicle is one of `PASSENGER`, `LIGHT_TRUCK`, `HEAVY_DUTY`, or `MOTORCYCLE`. Other closed enumerations introduced in their respective workflows include appointment `kind` (`APPOINTMENT` or `WALK_IN`), checklist `outcome` (`PASS`, `FAIL`, or `NA`) and `severity` (`MINOR`, `MAJOR`, or `CRITICAL`), the emissions `protocol` (`OBD2_CAN`, `OBD2_ISO`, or `OBD2_J1850`), and the waiver `cost_basis` (`DOCUMENTED_ONLY` or `DOCUMENTED_PLUS_ESTIMATED`). The lifecycle states for each entity are enumerated in §3 alongside the workflow that drives them.

### 2.11. The Logical Clock

Several rules depend on the current time — marking an appointment a no-show, and judging whether a reinspection falls inside its fee-relief window. For deterministic operation, the system maintains a single logical current clock. An administrative test-driving capability, restricted to a `StationManager`, sets that clock to a supplied instant via the `to_iso8601` field; all time-dependent comparisons read this logical clock rather than wall time.

## 3. Business Logic & Workflows

### 3.1. Station Configuration

Everything begins with a `Station`, created by a `StationManager`. A station is defined by its legal `name`, a two-letter jurisdiction `state_code` (exactly two uppercase letters), a `certificate_serial_prefix` that is stamped onto every certificate serial the station mints, and a `repair_cost_limit_cents` — the positive jurisdiction repair-cost limit a failed-emissions vehicle's qualifying spend must reach to become waiver-eligible. A station also declares an `analyzer_count`, the number of OBD-II analyzer units it owns; this is an integer of at least 1 and defaults to 1 when omitted. At creation the system initializes the station's `next_certificate_seq` to 1; this monotonic counter supplies the next certificate serial and increments by one each time a serial is minted.

Under a station, a `StationManager` configures one `VehicleClassProfile` per class. A profile names its owning `station_id` and the `vehicle_class` it configures, sets the `base_fee_cents` (a positive base safety-inspection fee in cents) and a boolean `obd_required` flag indicating whether an OBD-II emissions test is part of that class's checklist, and declares `checklist_item_count`, the number of safety checklist items (at least 1) that must each be recorded before a pass/fail decision may be made. A profile also carries `reinspection_window_days`, the number of days after the original inspection during which the first reinspection's service fee is waived; this is an integer of at least 0 and defaults to 30. Profiles can be listed and filtered by `station_id` or by `vehicle_class`.

A station's physical capacity is modeled by lanes. A `StationManager` adds a `Lane` by naming its `station_id` and a `lane_number` (an integer of at least 1, unique within the station), declaring whether the lane is `supports_obd`-equipped for emissions testing, and optionally setting a `turnaround_buffer_minutes` — the mandatory clean-down gap enforced after each appointment on the lane before the next one may start, an integer of at least 0 that defaults to 0. Lanes can be listed and filtered by `station_id`, and the appointments reserved on a particular lane can be listed directly from that lane.

### 3.2. Lane Scheduling and the Appointment Lifecycle

A `Receptionist` (or a `StationManager`) puts a vehicle on the calendar by creating an `Appointment`. The booking names the `lane_id` to reserve, the `vehicle_vin` (exactly 17 uppercase alphanumeric characters), the declared `vehicle_class`, the `kind` of visit (`APPOINTMENT` for a pre-booked slot or `WALK_IN` for one opened on arrival), and the reserved slot's `scheduled_start` and `scheduled_end`. A new appointment starts in `BOOKED`.

Several rules gate a booking, evaluated after the generic checks of §2.9. First, the slot must be a valid interval: `scheduled_end` must be strictly after `scheduled_start`, or the request is rejected with `ERR_INVALID_TIME_RANGE`. Second, the lane must be free for the requested slot. A lane is a single-occupant resource with a buffer: the requested slot is the half-open interval from `scheduled_start` up to but not including `scheduled_end`, and to it the system appends the lane's `turnaround_buffer_minutes` of clean-down. The booking is rejected with `ERR_LANE_TIME_CONFLICT` if this buffered span overlaps the buffered span of any appointment on the same lane that has not been released — that is, any appointment still in `BOOKED`, `CHECKED_IN`, or `CONSUMED`. The intervals are half-open, so exact adjacency at the boundary, where the new slot starts precisely at an existing appointment's end plus its buffer, does not conflict. Third, the declared `vehicle_class` must have a matching `VehicleClassProfile` at the lane's station; if no such profile exists the booking is rejected with `ERR_CLASS_PROFILE_MISSING`. When all gates pass, the slot is reserved on the lane.

An appointment in `BOOKED` can move along three paths, all driven by the `Receptionist` or `StationManager`. Checking the vehicle in advances it from `BOOKED` to `CHECKED_IN` and bumps its `version`. Cancelling it advances `BOOKED` to `CANCELLED`, releasing the reserved slot back to the lane and bumping its `version`. Marking it a no-show advances `BOOKED` to `NO_SHOW`, but only once the logical clock has reached or passed the appointment's `scheduled_end`; the no-show likewise releases the slot and bumps the `version`. `CANCELLED` and `NO_SHOW` are terminal, as is `CONSUMED`, which is reached only by the inspection workflow below. Any of these transitions attempted from a state other than `BOOKED` is rejected with `ERR_INVALID_STATE`.

### 3.3. Shared Analyzer Reservations

OBD-II testing draws on a station's shared pool of analyzer units, and that pool is a finite, concurrently shared resource — distinct from the single-occupant lane. A `Receptionist` or `StationManager` holds an analyzer window by creating an `AnalyzerReservation` against a `station_id` for a `vehicle_vin` (again exactly 17 uppercase alphanumeric characters), bounded by a `window_start` and a `window_end` that must be strictly after the start. The reservation begins with a `status` of `HELD`.

Analyzer capacity uses aggregate-overlap semantics rather than single-occupancy. A window is the half-open interval from `window_start` up to but not including `window_end`. Two windows are in conflict only when their intervals strictly overlap — that is, when their intersection has positive length; windows that merely touch at an endpoint do not overlap. When a new reservation is requested, the system counts the `HELD` reservations at the same station whose windows strictly overlap the requested one. The new reservation may be admitted only if, after admitting it, the number of mutually overlapping held windows would remain below the station's `analyzer_count`; equivalently, if admitting it would bring the count of strictly-overlapping held windows to the station's `analyzer_count` or beyond, it is rejected with `ERR_ANALYZER_CAPACITY`. A held window can be released by a `Receptionist` or `StationManager`, advancing its `status` from `HELD` to `RELEASED` and bumping its `version`; once `RELEASED` (a terminal state) the window no longer counts toward concurrency. Reservations can be listed and filtered by `station_id` and by `status`.

### 3.4. Opening and Conducting an Inspection

An inspection begins when an `Inspector` (or `StationManager`) consumes a checked-in appointment. Opening a record names the `appointment_id` to consume and, on a reinspection visit, may carry an `original_record_id`. The appointment must be in `CHECKED_IN`, and no inspection record that is not `ABORTED` may already reference that `appointment_id`; otherwise the open is rejected with `ERR_INVALID_STATE`. On success the appointment advances from `CHECKED_IN` to `CONSUMED`, and a new `InspectionRecord` is created in `IN_PROGRESS`. The record copies its `station_id`, `vehicle_vin`, and `vehicle_class` from the consumed appointment and its lane's station. Its `original_record_id` is null on a first inspection; when supplied for a reinspection it points to the head of the chain. Its computed `reinspection_index` is 0 for an original inspection and is set to the chain head's index plus one for a reinspection. A fresh record carries a `safety_result` and `emissions_result` of `PENDING`, a `fee_cents` of 0, and `waiver_applied` of false.

While the record is `IN_PROGRESS`, the `Inspector` records the safety checklist one item at a time. Each `ChecklistResult` names its `record_id`, an `item_code` (a stable code such as "BRAKES" or "LIGHTS"), and an `outcome` of `PASS`, `FAIL`, or `NA`. A line may also carry a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, which defaults to `MINOR` and is meaningful only when the outcome is `FAIL`. Records can be listed and filtered by `appointment_id`, `original_record_id`, `station_id`, or `status`, and checklist results can be listed and filtered by `record_id`.

When the class profile's `obd_required` flag is true, the `Inspector` also attaches exactly one `EmissionsTest` to the record. The test names its `record_id`, the `protocol` used (`OBD2_CAN`, `OBD2_ISO`, or `OBD2_J1850`), the `dtc_count` of stored Diagnostic Trouble Codes read from the ECU (a non-negative integer), the `readiness_monitors_incomplete` count of emissions monitors not yet complete (also non-negative), and the boolean `mil_on` indicating whether the Malfunction Indicator Lamp is commanded on. An emissions test may be attached only when the record's class profile has `obd_required` true, and at most one test may exist per record; an attempt to attach a test to a non-OBD class, or to attach a second test, is rejected with `ERR_OBD_NOT_APPLICABLE`. Tests can be listed and filtered by `record_id`.

The OBD-II verdict is computed when the test is created and re-affirmed at the pass/fail decision, and stored on the test's `result` field. The verdict is a clean-ECU threshold check evaluated in this order: if `mil_on` is true the `result` is `FAIL`; otherwise if `dtc_count` is greater than zero (any stored trouble code) the `result` is `FAIL`; otherwise if `readiness_monitors_incomplete` is two or more — that is, more than the single incomplete monitor that is tolerated — the `result` is `FAIL`; otherwise the `result` is `PASS`. In short, a pass requires the lamp off, zero stored codes, and at most one incomplete readiness monitor.

### 3.5. The Pass/Fail Decision

Deciding a record is the inspector's central act, and it freezes the record as either `PASSED` or `FAILED`. The decision may be made only on a record that is `IN_PROGRESS`; attempting it on any other status is rejected with `ERR_INVALID_STATE`. Before any outcome can be computed, the inspection must be complete: the number of `ChecklistResult` rows for the record must equal the class profile's `checklist_item_count`, and when the class requires OBD exactly one `EmissionsTest` must exist. If items are missing, or the required emissions test is absent, the decision is rejected with `ERR_INSPECTION_INCOMPLETE`.

Once complete, the system computes the two component results. The `safety_result` aggregates over all `ChecklistResult` rows for the record: if any line's `outcome` is `FAIL` the `safety_result` is `FAIL`, and otherwise (every outcome being `PASS` or `NA`) it is `PASS`. The `emissions_result` is derived from the single emissions test's `result` when the class requires OBD; for a class whose `obd_required` is false, the `emissions_result` is `NOT_APPLICABLE`.

The record passes when, and only when, all of these hold together: the record was `IN_PROGRESS`, the checklist row count matched the profile's `checklist_item_count`, the safety result resolved to `PASS` (no checklist line failed), and — for an OBD-required class — exactly one emissions test exists and either its result is `PASS` or an `APPROVED` `WaiverRequest` exists for this record. When every one of these is satisfied the record transitions `IN_PROGRESS → PASSED`. If instead any of them fails — a safety failure exists, or emissions failed without an approved waiver — the record transitions `IN_PROGRESS → FAILED`. In both branches the system computes `safety_result` and `emissions_result`, freezes the fee onto `fee_cents` as described in §3.6, and increments the record's `version`. On the passing branch only, `waiver_applied` is set to true exactly when the `emissions_result` is `FAIL` and an `APPROVED` `WaiverRequest` exists for the record (the case where a waiver carried the vehicle past an emissions failure); otherwise `waiver_applied` remains false.

A `StationManager` may instead abort an in-progress record, transitioning `IN_PROGRESS → ABORTED` and bumping its `version`. `ABORTED` is terminal and certifies nothing.

### 3.6. Computing and Freezing the Fee

At the moment a record is decided — on both the passing and failing branch — its total fee is computed and frozen onto `fee_cents` in a pinned order of steps. The system first locates the `VehicleClassProfile` for the record's station and class. The base of the fee is that profile's `base_fee_cents`. To the base it adds an emissions surcharge: when the class requires OBD the surcharge is ten dollars (1000 cents), and when it does not the surcharge is zero. The base plus the emissions surcharge forms the service subtotal.

Reinspection relief can then zero that service subtotal. The first reinspection within its window is granted free service: the relief applies precisely when the record's `reinspection_index` equals 1 and the elapsed time from the chain head's `created_at` to the decision instant on the logical clock is no greater than the profile's `reinspection_window_days` converted to seconds (that is, `reinspection_window_days` multiplied by 86,400 seconds per day). When that condition holds the service subtotal is forced to zero. A flat state environmental fee of two dollars (200 cents) is always added afterward regardless of relief. The frozen `fee_cents` is therefore the service subtotal (possibly zeroed by relief) plus the flat 200-cent environmental fee. Concretely, an original inspection (`reinspection_index` of 0) or a reinspection that is outside its window or whose index is not exactly 1 pays the full service subtotal plus the 200-cent fee, while a qualifying first reinspection pays only the 200-cent environmental fee. All amounts here are whole-cent integers with no rounding.

### 3.7. Failed Emissions: Repair Orders and the Repair-Cost Ledger

A vehicle that fails its emissions test can work toward a waiver by accumulating qualifying repair spend. A `Receptionist` or `StationManager` submits a `RepairOrder` against the failed record, naming the `record_id`, the `shop_name` of the repair facility, a `documented_cost_cents` figure backed by an itemized invoice, an `estimated_cost_cents` figure backed only by a written estimate, and a boolean `emissions_related` flag indicating whether the repair targets the emissions failure. Both cost figures are non-negative integers defaulting to 0. A repair order begins in `SUBMITTED` and can be listed and filtered by `record_id` and `status`.

A `StationManager` adjudicates each order. Verifying it advances `SUBMITTED → VERIFIED`, but only when the referenced record is `FAILED` with an `emissions_result` of `FAIL`; this gate is enforced as part of the verify transition, and an order whose record does not meet it cannot be verified. Only verified, emissions-related documented spend counts toward the limit. Rejecting an order advances `SUBMITTED → REJECTED`, which excludes it from all waiver spend. Both verify and reject bump the order's `version`, and both terminal states are reached only from `SUBMITTED`; attempting either from another state is rejected with `ERR_INVALID_STATE`.

The qualifying repair spend for a record is computed two ways, governed by a chosen basis. The system first selects the eligible orders: those whose `record_id` is the record, whose `emissions_related` is true, and whose `status` is `VERIFIED`. Submitted and rejected orders never count. The documented total is the sum of `documented_cost_cents` across those eligible orders. Under the `DOCUMENTED_ONLY` basis the qualifying spend is exactly that documented total. Under the `DOCUMENTED_PLUS_ESTIMATED` basis the system additionally sums `estimated_cost_cents` across the same eligible orders and the qualifying spend is the documented total plus the estimated total — a basis that can cross the limit on the very same repair set that the documented-only basis falls short on. All sums are whole-cent integers. A vehicle is waiver-eligible under a basis precisely when its qualifying spend computed that way is greater than or equal to the station's `repair_cost_limit_cents`.

A read-only preview is available for an inspection record that reports the qualifying spend and eligibility under both bases at once. It returns `documented_only_spend_cents` and `documented_plus_estimated_spend_cents`, the station's `repair_cost_limit_cents`, and two booleans, `eligible_documented_only` and `eligible_documented_plus_estimated`, each true exactly when the corresponding spend reaches the limit.

### 3.8. Waiver Requests and Approval

When repair spend cannot be made to satisfy the emissions standard but reaches the cost limit, the vehicle's owner may seek a waiver. A `Receptionist` or `StationManager` files a `WaiverRequest` against the failed record, naming the `record_id` and the `cost_basis` being claimed — either `DOCUMENTED_ONLY` or `DOCUMENTED_PLUS_ESTIMATED`. The request begins in `REQUESTED` with a `qualifying_spend_cents` of 0, and can be listed and filtered by `record_id` and `status`.

A `StationManager` decides each request with a `decision` of either approve or deny. Approval is the gated path: it requires that the referenced record be `FAILED` with an `emissions_result` of `FAIL`, and it requires that the qualifying repair spend computed under the request's claimed `cost_basis` be greater than or equal to the station's `repair_cost_limit_cents`. If the spend is below the limit the approval is rejected with `ERR_REPAIR_LIMIT_NOT_MET`. On approval the system freezes `qualifying_spend_cents` to the computed amount and advances `REQUESTED → APPROVED`, which unblocks a later reinspection-and-decide to pass with `waiver_applied` true. Denial advances `REQUESTED → DENIED`; it likewise freezes `qualifying_spend_cents` as an audit snapshot of what was claimed. Both decisions bump the request's `version`, and both terminal states are reached only from `REQUESTED`; deciding a request not in `REQUESTED` is rejected with `ERR_INVALID_STATE`.

### 3.9. Reinspection: the Revision Loop

A failed vehicle returns for reinspection, and so, occasionally, does a passed one (for a recall or dispute). Both are driven by an `Inspector` or `StationManager` and both open a fresh record in the chain. A reinspection requires that the source record be in `FAILED` or in `PASSED` — attempting it from `IN_PROGRESS` or a terminal state is rejected with `ERR_INVALID_STATE` — that the chain not already be at its reinspection ceiling, and that a checked-in appointment be supplied for the new visit via `reinspection_appointment_id`. A chain admits at most three reinspections: a reinspection is allowed only while the source's `reinspection_index` is less than 3, and an attempt once the chain has reached that ceiling is rejected with `ERR_REINSPECTION_LIMIT`.

On a reinspection from a `FAILED` record, the failed record is marked superseded and its `version` is incremented, though it retains its `FAILED` status as chain history; a new `InspectionRecord` is created in `IN_PROGRESS` with `original_record_id` set to the head of the chain and `reinspection_index` set to one greater than the source's; and the supplied appointment is consumed, advancing it `CHECKED_IN → CONSUMED`. Because a failed record never holds an active certificate, no certificate cascade fires on this path.

On a reinspection from a `PASSED` chain-head record, the same supersession-and-creation occurs, and in addition a three-link cascade fires. First, the passed chain-head record is marked superseded and its `version` is incremented (it keeps its `PASSED` status as chain history). Second, caused by that supersession, the chain head's `ACTIVE` `Certificate` is driven through the certificate `ACTIVE → VOID` transition. Third, caused by that void, the certificate's own void effect revokes and surrenders its `sticker_number`. As on the failed path, a new `IN_PROGRESS` record is created with `original_record_id` at the chain head and `reinspection_index` one greater, the void certificate's `version` is incremented, and the supplied appointment is consumed `CHECKED_IN → CONSUMED`. A record reopened to `IN_PROGRESS` this way proceeds through the checklist, emissions, and decision workflow again.

### 3.10. Certificate Issuance, Voiding, and the Sticker

A `StationManager` issues a `Certificate` and its physical sticker for a passed record. Issuance names the `record_id` and carries `expected_record_version` for the optimistic-concurrency check of §2.8. The record must be `PASSED`; issuing against an `IN_PROGRESS`, `FAILED`, or `ABORTED` record is rejected with `ERR_RECORD_NOT_PASSED`. At most one `ACTIVE` certificate may exist per record; a second issuance against a record that already has an active certificate is rejected with `ERR_CERTIFICATE_EXISTS`. When these gates and the stale-version check pass, the system mints the certificate's `serial` by concatenating the station's `certificate_serial_prefix` with the zero-padded `next_certificate_seq`, then increments `next_certificate_seq` by one; it mints a `sticker_number`; it sets the certificate's `status` to `ACTIVE` and its `expires_on` to one year after issuance; and it increments the certified record's `version` by one, so that any later issuance attempt carrying the now-stale `expected_record_version` fails the OCC check. Certificates can be listed and filtered by `record_id` and `status`.

A certificate's `status` lives on a parallel validity dimension: it is `ACTIVE` when issued and becomes `VOID` once the underlying result is invalidated. Voiding can happen two ways. It happens automatically as the cascade of §3.9 when a passed record is reinspected. It can also be done deliberately by a `StationManager` as a compensating action. Either way, the certificate transitions `ACTIVE → VOID`, the issued `sticker_number` is revoked and considered surrendered, and the certificate's `version` is incremented. `VOID` is terminal; voiding a certificate that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`.

### 3.11. State Reporting to the Jurisdiction

Terminal inspection results are remitted to the state in batches. A `StationManager` opens a `StateReportBatch` for a `station_id` and a `period_label` (such as "2026-06"). A new batch is `OPEN` with `line_count` of 0 and `total_reported_fee_cents` of 0. Batches can be listed and filtered by `station_id` and `status`.

A `StationManager` attaches a terminal record to an open batch as a `StateReportLine`, supplying the `record_id`. A line may be attached only for a record that has reached a terminal pass/fail outcome — that is, a record in `PASSED` or `FAILED` — and a given record may appear at most once per batch; an attempt to attach a non-terminal record or to duplicate one already on the batch is rejected with `ERR_LINE_NOT_ELIGIBLE`. On attach, the line snapshots the record's overall outcome into `reported_result` (`PASS` or `FAIL`) and the record's frozen `fee_cents` into the line's own `fee_cents`; it carries the owning `batch_id` and the source `record_id`. After every attach the batch's totals are recomputed: `line_count` is set to the number of attached lines and `total_reported_fee_cents` to the sum of those lines' `fee_cents`, and the batch's `version` is incremented. Lines can be listed for a batch, listed and filtered globally by `record_id` or `batch_id`, and fetched individually.

A `StationManager` may detach a line from an open batch by naming the record. Detaching removes the line, reruns the same recomputation of `line_count` and `total_reported_fee_cents` over the remaining lines, and increments the batch's `version`.

Submitting a batch is restricted to a `StationManager`, requires the batch to be `OPEN`, requires `line_count` of at least 1 (a batch with no lines is rejected with `ERR_EMPTY_BATCH`), and carries `expected_batch_version` for the stale-batch check of §2.8. On success the batch transitions `OPEN → SUBMITTED`, its lines are frozen against further attach or detach, and its `version` is incremented. A `StateAuditor` then renders a `decision` of accept or reject on the submitted batch: acceptance advances `SUBMITTED → ACCEPTED` (terminal) and rejection advances `SUBMITTED → REJECTED`, each bumping the `version`. A rejected batch can be reopened by a `StationManager`, advancing `REJECTED → OPEN` so its lines become editable again, in a branching submit/reject cycle; the reopen bumps the `version`. Any of these transitions attempted from a state in which it is undefined is rejected with `ERR_INVALID_STATE`.

### 3.12. The State Remittance Surcharge

The jurisdiction reclaims a percentage of the service portion of each inspection fee. This surcharge can be previewed per record and is also the basis on which a batch's remittance is understood. The service portion of a single fee is the line or record's `fee_cents` less the flat 200-cent state environmental fee, floored at zero so it never goes negative. That service portion is multiplied by the state remittance rate of 7.5 percent (0.075), and the product is rounded half-up to whole cents to give that line's surcharge.

Rounding order is pinned and matters: each line's surcharge is rounded to whole cents first, and only then are the per-line surcharges summed to a batch total. Summing the raw service portions and rounding once at the end is not permitted, because on a multi-line batch the two approaches can differ by up to a cent. The per-record preview returns the `service_portion_cents` and the `state_surcharge_cents` for that single record. For a batch, the remittance total is the sum of each line's individually rounded surcharge across all of its lines.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify or transition an existing resource — including state-transition actions, the clock-set capability, and line detachment — return `200 OK`. All read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's current UTC logical clock | StationManager |
| POST | `/stations` | Create an inspection station | StationManager |
| GET | `/stations/{id}` | Fetch a station | StationManager, Inspector, Receptionist, StateAuditor |
| POST | `/vehicle-class-profiles` | Create a vehicle-class profile under a station | StationManager |
| GET | `/vehicle-class-profiles/{id}` | Fetch a vehicle-class profile | StationManager, Inspector, Receptionist |
| GET | `/vehicle-class-profiles` | List vehicle-class profiles | StationManager, Inspector, Receptionist |
| POST | `/lanes` | Create an inspection lane under a station | StationManager |
| GET | `/lanes/{id}` | Fetch a lane | StationManager, Inspector, Receptionist |
| GET | `/lanes` | List lanes | StationManager, Inspector, Receptionist |
| GET | `/lanes/{id}/appointments` | List appointments reserved on a lane | StationManager, Inspector, Receptionist |
| POST | `/analyzer-reservations` | Hold a shared OBD analyzer for a time window | Receptionist, StationManager |
| GET | `/analyzer-reservations/{id}` | Fetch an analyzer reservation | Receptionist, StationManager, Inspector |
| GET | `/analyzer-reservations` | List analyzer reservations | Receptionist, StationManager, Inspector |
| POST | `/analyzer-reservations/{id}/release` | Release a held analyzer window | Receptionist, StationManager |
| POST | `/appointments` | Book an appointment or open a walk-in slot | Receptionist, StationManager |
| GET | `/appointments/{id}` | Fetch an appointment | Receptionist, StationManager, Inspector |
| POST | `/appointments/{id}/check-in` | Mark an appointment checked in | Receptionist, StationManager |
| POST | `/appointments/{id}/cancel` | Cancel a booked appointment and release its slot | Receptionist, StationManager |
| POST | `/appointments/{id}/no-show` | Mark a booked appointment a no-show after its end time | Receptionist, StationManager |
| POST | `/inspection-records` | Open an inspection record by consuming a checked-in appointment | Inspector, StationManager |
| GET | `/inspection-records/{id}` | Fetch an inspection record | Inspector, StationManager, Receptionist, StateAuditor |
| GET | `/inspection-records` | List inspection records | Inspector, StationManager, StateAuditor |
| POST | `/inspection-records/{id}/decide` | Compute results and freeze the record as passed or failed | Inspector, StationManager |
| POST | `/inspection-records/{id}/reinspect` | Open a fresh reinspection record from a failed or passed record | Inspector, StationManager |
| POST | `/inspection-records/{id}/abort` | Abort an in-progress record | StationManager |
| GET | `/inspection-records/{id}/waiver-eligibility` | Preview qualifying repair spend and eligibility under both bases | Inspector, StationManager |
| GET | `/inspection-records/{id}/state-surcharge` | Preview the per-record state remittance surcharge | StationManager, StateAuditor |
| POST | `/checklist-results` | Record one safety checklist item outcome | Inspector, StationManager |
| GET | `/checklist-results/{id}` | Fetch a checklist result | Inspector, StationManager, StateAuditor |
| GET | `/checklist-results` | List checklist results | Inspector, StationManager, StateAuditor |
| POST | `/emissions-tests` | Attach an OBD-II test result to a record | Inspector, StationManager |
| GET | `/emissions-tests/{id}` | Fetch an emissions test | Inspector, StationManager, StateAuditor |
| GET | `/emissions-tests` | List emissions tests | Inspector, StationManager, StateAuditor |
| POST | `/repair-orders` | Submit a repair order against a failed emissions record | Receptionist, StationManager |
| GET | `/repair-orders/{id}` | Fetch a repair order | Inspector, StationManager, StateAuditor |
| GET | `/repair-orders` | List repair orders | Inspector, StationManager, StateAuditor |
| POST | `/repair-orders/{id}/verify` | Verify a submitted repair order | StationManager |
| POST | `/repair-orders/{id}/reject` | Reject a submitted repair order | StationManager |
| POST | `/waiver-requests` | Request an emissions waiver under a cost basis | Receptionist, StationManager |
| GET | `/waiver-requests/{id}` | Fetch a waiver request | Inspector, StationManager, StateAuditor |
| GET | `/waiver-requests` | List waiver requests | Inspector, StationManager, StateAuditor |
| POST | `/waiver-requests/{id}/decide` | Approve or deny a waiver request | StationManager |
| POST | `/certificates` | Issue a certificate and sticker for a passed record | StationManager |
| GET | `/certificates/{id}` | Fetch a single certificate | StationManager, Inspector, StateAuditor |
| GET | `/certificates` | List certificates | StationManager, Inspector, StateAuditor |
| POST | `/certificates/{id}/void` | Manually void an active certificate | StationManager |
| POST | `/state-report-batches` | Open a new state report batch | StationManager |
| GET | `/state-report-batches/{id}` | Fetch a state report batch | StationManager, StateAuditor |
| GET | `/state-report-batches` | List state report batches | StationManager, StateAuditor |
| POST | `/state-report-batches/{id}/lines` | Attach a terminal record to an open batch as a line | StationManager |
| GET | `/state-report-batches/{id}/lines` | List the lines attached to a batch | StationManager, StateAuditor |
| GET | `/state-report-lines/{id}` | Fetch a state report line | StationManager, StateAuditor |
| GET | `/state-report-lines` | List state report lines | StationManager, StateAuditor |
| DELETE | `/state-report-batches/{id}/lines/{record_id}` | Detach a line from an open batch | StationManager |
| POST | `/state-report-batches/{id}/submit` | Submit a non-empty batch to the state | StationManager |
| POST | `/state-report-batches/{id}/decide` | Accept or reject a submitted batch | StateAuditor |
| POST | `/state-report-batches/{id}/reopen` | Reopen a rejected batch for edits | StationManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_LANE_TIME_CONFLICT` | 409 |
| `ERR_ANALYZER_CAPACITY` | 409 |
| `ERR_CLASS_PROFILE_MISSING` | 409 |
| `ERR_OBD_NOT_APPLICABLE` | 409 |
| `ERR_INSPECTION_INCOMPLETE` | 409 |
| `ERR_RECORD_NOT_PASSED` | 409 |
| `ERR_CERTIFICATE_EXISTS` | 409 |
| `ERR_REPAIR_LIMIT_NOT_MET` | 409 |
| `ERR_REINSPECTION_LIMIT` | 409 |
| `ERR_LINE_NOT_ELIGIBLE` | 409 |
| `ERR_EMPTY_BATCH` | 409 |
