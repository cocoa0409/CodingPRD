# Tank Cleaning Terminal Services API — Product Requirements Document

## 1. Introduction

Bulk liquid storage terminals live under a simple commercial pressure: a tank earns nothing while it is being cleaned, yet cleaning it badly — an incompatible product changeover, an unmanifested sludge shipment, a confined-space entry against a lapsed gas-free certificate — creates regulatory exposure that dwarfs the downtime. Operators coordinate a cast of independent parties on every job: the cleaning contractor who pumps out the heel and washes the tank, the marine chemist who certifies the atmosphere, the EHS officer who controls entry permits and waste profiles, the API 653 inspector who examines the shell, and the laboratory that clears wastewater for discharge. Each hand-off is a compliance checkpoint, and the industry norm of segregating duties (the chemist who certifies may not issue the permit; the technician who runs the lab may not authorize the discharge) turns every checkpoint into a potential audit finding.

This document specifies the Tank Cleaning & Terminal Services API, a single platform mounted under `/ops` on which terminals run that entire lifecycle as a stateful, auditable workflow: taking tanks out of service against booked windows, tracking heel and sludge removal with manifest-backed mass balances, governing gas-free certification and confined-space entry, coordinating inspections and repair cycles, verifying changeover flushes, computing the final invoice, and controlling wastewater discharge against daily plant capacity. Seven roles share the platform under strict segregation of duties; a logical clock drives certificate expiry and window overrun sweeps so that time-dependent safety rules are testable and deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the structural contracts and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly seven roles: `TerminalAdmin`, `TerminalOperator`, `ContractorSupervisor`, `MarineChemist`, `EHSOfficer`, `API653Inspector`, and `LabTechnician`. Each write endpoint admits a defined subset of these roles; a caller whose role is not admitted — or who fails an ownership check the endpoint requires — is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403). All read endpoints are open to every one of the seven roles.

Two roles are entity-backed. When `X-User-Role` is `ContractorSupervisor`, `X-User-ID` is the `id` of the acting Contractor; ownership checks on any resource that references a contractor — cleaning jobs, waste profiles, waste shipments, entry permits, and repair orders via their denormalized job — compare the resource's contractor foreign key to `X-User-ID`. When `X-User-Role` is `API653Inspector`, `X-User-ID` is the `id` of the acting Inspector, and ownership checks compare the inspection's or repair's inspector foreign key to it. For the remaining five roles — `TerminalAdmin`, `TerminalOperator`, `MarineChemist`, `EHSOfficer`, and `LabTechnician` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `issued_by_user_id` on certificates and permits, `reported_by_user_id` on inspections, `completed_by_user_id` on repair orders, or `lab_user_id` on wastewater batches) but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, and the `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered with three fractional digits; `updated_at` refreshes on every mutation of the resource. The `version` is an integer that the server increments by exactly one on every mutation, and it anchors the optimistic concurrency rules of §2.6. Safety events are the deliberate exception: a safety event is append-only, carries only `id` and `created_at`, and has neither `updated_at` nor `version`, because events are never modified after being recorded.

### 2.5. The Logical Clock and Time-Driven Sweeps

All time-dependent rules in the system — certificate validity, window activation, window overrun, the rolling safety-score window, and the wastewater discharge day — read a single logical UTC clock maintained by the server rather than wall-clock time. At server startup, before any clock call has been made, the logical clock reads exactly 2026-05-01T00:00:00Z. A `TerminalAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Advancing the clock performs two sweeps as part of the same operation: every gas-free certificate still `VALID` whose `expires_at` has been reached transitions to `EXPIRED` and fires the downstream cascade described in §3.6, and every service window whose `planned_end` has been reached transitions to `OVERRUN` — a `PLANNED` window unconditionally, an `ACTIVE` window only when its linked job has not yet reached `RETURNED_TO_SERVICE`.

### 2.6. Optimistic Concurrency Control

Three write endpoints guard a parent entity's `version` with an explicit optimistic-concurrency field, and no other endpoint accepts a version field at all.

Booking a service window requires the request to carry `expected_tank_version` holding the tank `version` the client last observed. If the tank's current `version` has advanced since — for example because another writer has just booked a window on the same tank, an act that legitimately extends the tank's booked calendar and itself increments the tank's `version` by one — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from extending a calendar it has not observed.

Patching a cleaning job requires `expected_job_version` matching the job's current `version`; a job whose version has advanced since the client's last read rejects the patch with `ERR_STALE_VERSION` (HTTP 412), because the client's edits were computed against a stale snapshot.

Booking an inspection requires `expected_inspector_version` matching the inspector's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). This rejection applies even when the new interval overlaps nothing on the inspector's calendar — the client's view of the calendar is stale regardless of whether the specific slot happens to be free.

### 2.7. Units, Precision, and Rounding Discipline

Monetary amounts are integer cents throughout: base fees, disposal costs, invoice totals, and per-line rates are never fractional. Volumes are whole liters and masses are whole kilograms. The contractor safety score is stored and compared at two decimal places using round-half-up, and is clamped to the band from 0.00 to 100.00 inclusive. Sludge estimates are rounded half-up to whole kilograms. Flush volumes are whole liters, with the ceiling applied exactly once at the final step of the computation. Disposal costing follows a pinned rounding order: each shipment line is rounded half-up to whole cents first, and only then are the line amounts summed into the shipment total — summing raw line products and rounding once at the end produces a different number and is not the contract. Invoice computation rounds half-up at the discount step only, per the pinned evaluation order of §3.8. The mass-balance tolerance bound is computed to two decimal places, round-half-up. Atmospheric instrument readings are compared exactly as supplied at one decimal place.

### 2.8. Scheduling Intervals and Calendar Discipline

All planned intervals in the system — service windows and inspection bookings alike — are half-open: the start instant is included, the end instant is excluded, and a request whose start is not strictly before its end is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Two calendars coexist under different tightness rules.

On a tank's window calendar, a new window is checked against every existing `PLANNED` or `ACTIVE` window of the same tank. True intersection — the new start falling before the existing end while the existing start falls before the new end — is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409). Even without intersection, a mandatory 24-hour gas-free buffer surrounds each existing window: a new window that starts or ends within 24 hours of an existing window's far edge is rejected with `ERR_WINDOW_BUFFER_VIOLATION` (HTTP 409). Touching adjacency is not exempt — because the buffer makes a zero-hour gap a violation, a new window starting exactly at an existing window's end is rejected as a buffer violation. When both rules could fire, the overlap error is reported first.

On an inspector's calendar, only true intersection matters: a new inspection overlapping an existing `SCHEDULED` or `IN_PROGRESS` inspection of the same inspector is rejected with `ERR_INSPECTOR_UNAVAILABLE` (HTTP 409), while back-to-back adjacency — the new start exactly equal to an existing end — is explicitly allowed.

### 2.9. Atmospheric Safety Envelope and Certificate Validity

A gas-free certificate may be issued only when all four instrument readings fall inside their envelope: the lower-explosive-limit reading `lel_pct` strictly below 10.0 percent, the oxygen reading `o2_pct` within the closed band from 19.5 to 23.5 percent inclusive, the hydrogen sulfide reading `h2s_ppm` at most 10.0 ppm inclusive, and the benzene reading `benzene_ppm` strictly below 1.0 ppm. A certificate request breaching any one of these is rejected with `ERR_GAS_FREE_LIMITS_EXCEEDED` (HTTP 422). A certificate's `expires_at` is set twelve hours after its `issued_at`; exactly one revalidation is permitted and adds a further six hours. A certificate anchors downstream operations only while its status is `VALID` and the logical clock is strictly before `expires_at`; at or past that instant, use-sites fail with `ERR_CERT_EXPIRED` (HTTP 409), and the clock sweep of §2.5 marks the certificate `EXPIRED`. Where an operation references a certificate that is not `VALID` at all — none exists, or the referenced one has been revoked, superseded, or expired — the rejection is `ERR_NO_VALID_GAS_FREE_CERT` (HTTP 409).

### 2.10. Segregation of Duties

Four hand-offs in the workflow are segregated, and in each case the rejection is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the same `X-User-ID` appears on both sides of the step. The EHS officer issuing an entry permit must differ from the marine chemist who issued the anchoring gas-free certificate. The terminal operator accepting an inspection report must differ from the inspector who reported it. The inspector verifying a completed repair must differ from the contractor supervisor who completed it. The terminal operator authorizing a wastewater discharge must differ from the lab technician who submitted the batch's results.

### 2.11. Validation Order and Error Semantics

Every request is evaluated against a fixed validation pipeline, and the first failing check determines the error returned. Authentication context comes first (§2.1), then role admission and entity-backed ownership, then existence — path identifiers validated left to right before body foreign-key references, a missing one yielding `ERR_NOT_FOUND` (HTTP 404) — then the optimistic-concurrency check of §2.6 where the endpoint carries one, then state-transition legality, where a target resource that is not in a state from which the requested transition is defined fails with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Only after these generic layers do endpoint-specific business rules run, in the relative orders stated beside each workflow in §3; where §3 names an order among business checks, that order is normative. Malformed payloads — a missing required field, an unknown enum value, an interval whose start is not before its end, a negative quantity, or a job whose named terminal does not own the named tank — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Terminal Configuration, Products, and Tanks

A `TerminalAdmin` begins by registering the physical landscape. Each terminal carries a display `name`, a `wastewater_daily_capacity_liters` ceiling on the effluent it may authorize and discharge per UTC day, and three tunable governance values with defaults applied when omitted: `safety_score_threshold` defaulting to 85.0, the minimum contractor safety score for qualification, evaluated inclusively; `score_variant` defaulting to `ROLLING_12MO` (the alternative being `LIFETIME`), which pins which variant of the contractor safety score this terminal evaluates; and `mass_balance_tolerance_pct` defaulting to 2.0, the tolerated solids fraction at return-to-service, also inclusive.

Products are registered next. A product grade has a unique `code`, a `family` drawn from `GASOLINE`, `DISTILLATE`, `JET`, `CRUDE`, `CHEMICAL`, and `VEGOIL`, a `viscosity_class` of `LOW`, `MEDIUM`, or `HIGH` that drives both the flush base factor and the sludge surface factor, a free-form `compatibility_group` key (conventionally values like GAS, DIST, JET, CRUDE, CHEM, VEG) on which the changeover matrix of §3.4 operates, and a `flash_point_c` flash point in Celsius.

Tanks belong to terminals. Registering a tank names its owning `terminal_id`, a terminal-unique `tank_number`, its shell `capacity_m3` in cubic meters, and the `current_product_id` of the product in service. A tank enters the world `IN_SERVICE`, and its `status` never changes through a direct write: it moves to `OUT_OF_SERVICE` only as a side effect of a cleaning job taking the tank out of service, and returns to `IN_SERVICE` when that job returns the tank to service or is cancelled. The API 653 inspector registry rounds out configuration: each inspector has a `name` and a `certification_level` of `API653`, `API650`, or `BOTH`.

### 3.2. Contractor Governance and the Safety Score

Cleaning contractors are registered by a `TerminalAdmin` with a `company_name`; a new contractor enters as an `APPLICANT` carrying a `safety_score` of 100.00. From there, an `EHSOfficer` maintains an append-only stream of safety events against the contractor — each event naming the `contractor_id`, a `kind` of `INCIDENT`, `VIOLATION`, `NEAR_MISS`, or `TRAINING_CREDIT`, a `severity_weight` that is an integer from 1 to 10 inclusive, and an `occurred_at` timestamp that drives rolling-window inclusion.

Every event write recomputes the contractor's score. The computation starts from a base of 100.00, subtracts 2.00 times the total severity weight of the contractor's `INCIDENT` events, subtracts 1.00 times the total severity weight of `VIOLATION` events, subtracts 0.25 times the total severity weight of `NEAR_MISS` events, adds 0.50 times the total severity weight of `TRAINING_CREDIT` events, and clamps the result into the band from 0.00 to 100.00 at two decimal places. Which events enter the sums depends on the evaluating terminal's `score_variant`: under `ROLLING_12MO` only events whose `occurred_at` falls at or after the instant exactly 365 days before now count — the boundary is inclusive — while under `LIFETIME` every event counts regardless of age. The same event history can therefore yield two different scores at two terminals, and each terminal's pinned variant governs evaluations made against that terminal.

Qualification is where the score bites. A `TerminalAdmin` qualifies an `APPLICANT` contractor, or reinstates a `SUSPENDED` one, by naming a `terminal_id`: the contractor's score is computed under that terminal's variant and must meet the terminal's `safety_score_threshold` — a score exactly equal to the threshold passes — failing which the request is rejected with `ERR_CONTRACTOR_NOT_QUALIFIED` (HTTP 409) and the contractor's status is unchanged. Success moves `APPLICANT` to `QUALIFIED`, or `SUSPENDED` back to `QUALIFIED` on reinstatement. Governance actions complete the lifecycle: suspension moves `QUALIFIED` to `SUSPENDED`, and barring moves a contractor from `APPLICANT`, `QUALIFIED`, or `SUSPENDED` to the terminal state `BARRED`, from which no return exists.

### 3.3. Booking Out-of-Service Windows

Before a job can be scheduled, someone must hold time on the tank. A `TerminalOperator` books a service window by naming the `tank_id` and the half-open interval from `planned_start` to `planned_end`, and by carrying `expected_tank_version` per §2.6 — a stale tank view is rejected with `ERR_STALE_VERSION` (HTTP 412). The booking itself advances the tank's `version` by exactly one, because the tank's booked calendar is part of its observable state; this is precisely why a client holding an older tank snapshot cannot book on top of a booking it never saw. Calendar conflicts are then evaluated per §2.8, overlap reported before buffer violation, and the new window lands in `PLANNED` with its `job_id` null.

Windows have their own small lifecycle. Activation — `PLANNED` to `ACTIVE` — is permitted only while the logical clock has reached `planned_start` and has not yet reached `planned_end`; outside that interval the attempt fails with `ERR_WINDOW_NOT_ACTIVE` (HTTP 409). Completion moves `ACTIVE` to `COMPLETED`, either at the operator's hand or automatically when the linked cleaning job returns to service. Cancelling is allowed only from `PLANNED`, and only while the window is unlinked or its linked job is already `CANCELLED` — a live job holding the window rejects the cancel with `ERR_WINDOW_LINKED` (HTTP 409). An `ACTIVE` window is never cancelled directly; it is cancelled by the system when its linked job is cancelled from `TANK_OOS` onward. Finally, the clock sweep of §2.5 retires stale windows: a `PLANNED` window whose `planned_end` has passed becomes `OVERRUN`, as does an `ACTIVE` window whose planned end has passed while its linked job has not reached `RETURNED_TO_SERVICE`.

### 3.4. Drafting and Scheduling a Cleaning Job

A cleaning job is drafted by a `TerminalOperator` against a specific tank and a specific product changeover. The draft names the `terminal_id`, the `tank_id`, the `contractor_id` of the cleaning contractor, the `from_product_id` being removed and the `to_product_id` the tank will hold next, the provisional `heel_volume_liters_sounding` read from the sounding tape, and the fixed `base_service_fee_cents`; an optional `lines_included` flag, defaulting to false, records whether transfer lines are flushed too. Creation refuses a tank that is not `IN_SERVICE` with `ERR_TANK_NOT_IN_SERVICE` (HTTP 409), and refuses a `terminal_id` that differs from the tank's owning terminal with `ERR_INVALID_REQUEST` (HTTP 400).

Three computations happen at draft time. First, the changeover matrix classifies the product pair into `changeover_class`, evaluated strictly in this order: if both products share the same `compatibility_group`, the class is `COMPATIBLE_DIRECT`; otherwise, if the two product families form a crude-into-jet or jet-into-crude pair in either direction, the class is `FORBIDDEN`; otherwise, if either product's `compatibility_group` is CHEM or VEG, the class is `REQUIRES_FULL_STRIP`; and in every remaining case the class is `REQUIRES_FLUSH`. Second, the provisional sludge estimate `sludge_estimate_provisional_kg` is the sounding volume multiplied by the sludge ratio of the from-product's family — 0.02 for `GASOLINE`, 0.03 for `DISTILLATE`, 0.015 for `JET`, 0.08 for `CRUDE`, 0.05 for `CHEMICAL`, 0.04 for `VEGOIL` — plus the tank's `capacity_m3` multiplied by the surface factor of the from-product's viscosity class — 0.5 for `LOW`, 1.0 for `MEDIUM`, 2.0 for `HIGH` — the whole result rounded half-up to whole kilograms; this provisional figure drives waste booking before pump-out. Third, the required `flush_volume_liters` is the tank capacity in liters — `capacity_m3` times one thousand — multiplied by the base factor of the from-product's viscosity class (0.02 for `LOW`, 0.035 for `MEDIUM`, 0.05 for `HIGH`) and by the class multiplier of the changeover class (0.5 for `COMPATIBLE_DIRECT`, 1.0 for `REQUIRES_FLUSH`, 1.8 for `REQUIRES_FULL_STRIP`); when `lines_included` is set, a further 5,000 liters is added; the raw figure is then rounded up to the next whole liter and finally confined to a floor of 2,000 liters and a ceiling of 200,000 liters. A job classified `FORBIDDEN` carries no flush volume — the field stays null — and, as scheduling will enforce, can never leave the draft stage.

While the job remains in `DRAFT`, the operator may patch its `base_service_fee_cents` or `lines_included`; the patch must carry `expected_job_version` per §2.6 and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Each accepted patch advances the job's `version` by one, and a change to `lines_included` recomputes the flush volume.

Scheduling is the first gated transition. The job must be in `DRAFT` — anything else is an invalid transition — and three business checks then run in order. The contractor's standing is examined first: the contractor must be `QUALIFIED` and must meet the terminal's `safety_score_threshold` under the terminal's pinned score variant, failing which the schedule is rejected with `ERR_CONTRACTOR_NOT_QUALIFIED`. Next, a `FORBIDDEN` changeover class is rejected with `ERR_INCOMPATIBLE_CHANGEOVER` (HTTP 422). Last, the named `window_id` must identify a `PLANNED` service window on the same tank that is not already linked to another job, failing which the rejection is `ERR_WINDOW_UNAVAILABLE` (HTTP 409). On success the job moves `DRAFT` to `SCHEDULED`, the window's `job_id` is set to the job, and the job's `version` increments by one.

When the window's time comes, taking the tank out of service moves the job `SCHEDULED` to `TANK_OOS`. The linked window must be `ACTIVE` — a window still `PLANNED` is not yet a valid basis and the attempt fails as an invalid transition — and the tank must still be `IN_SERVICE`, failing which `ERR_TANK_NOT_IN_SERVICE` fires. The side effect lands on the tank: its `status` flips to `OUT_OF_SERVICE` and its `version` advances by one.

### 3.5. Heel Removal, Waste Profiling, and Shipment Logistics

Physical work now belongs to the contractor. The owning `ContractorSupervisor` — the caller's `X-User-ID` must equal the job's `contractor_id`, failing which `ERR_FORBIDDEN_FOR_ROLE` — records the metered pump-out by supplying `metered_liters`; a negative value is rejected with `ERR_INVALID_REQUEST`. The job moves `TANK_OOS` to `HEEL_REMOVED`, the value is stored as `heel_volume_liters_metered`, and `expected_solids_kg` is computed on the final basis: exactly the same sludge formula as the provisional estimate of §3.4 — metered volume times the family sludge ratio, plus capacity times the viscosity surface factor, rounded half-up to whole kilograms — differing only in that the metered volume replaces the sounding volume. Until this point `expected_solids_kg` remains null.

Waste cannot move without an approved profile. The owning supervisor drafts a waste profile for the job with a regulatory `waste_code` (for example K051), a `hazard_class` of `NON_HAZARDOUS` or `HAZARDOUS`, and the lab characterizations `lab_flash_point_c` and `lab_tph_mg_l`; the profile starts `DRAFT`. Submission moves `DRAFT` to `SUBMITTED` — and, on the rejection cycle, `REJECTED` back to `SUBMITTED`. An `EHSOfficer` then approves or rejects. Approval enforces a one-approved-profile-per-job invariant: if any other profile of the same job is already `APPROVED`, the approval is rejected with `ERR_PROFILE_ALREADY_APPROVED` (HTTP 409). Rejection returns the profile to the supervisor for rework.

Reclassification is the dangerous lever, and it cascades. When an `EHSOfficer` reclassifies an `APPROVED` profile, the request's `hazard_class` must differ from the current one — a no-op reclassification is rejected with `ERR_INVALID_REQUEST`. The profile returns to `DRAFT` with the new hazard class, every waste shipment referencing it in `BOOKED`, `IN_TRANSIT`, or `DELIVERED` is voided (manifests invalidated by the reclassification; already-`RECONCILED` shipments survive untouched), each voided shipment triggers a recompute of its job's `shipped_solids_kg`, and if that job was sitting in `RTS_PENDING` and the mass balance of §3.8 now fails, the job automatically falls back to `FLUSH_VERIFIED`. The full chain — profile reclassified, shipments voided, job's return-to-service gate reverted — is a single atomic cascade.

Shipments are booked by the owning supervisor with a `job_id`, a `profile_id`, and a list of `lines`, each line naming a `material` of `SLUDGE`, `WASH_WATER`, or `SCALE`, an integer `kg`, and a `rate_cents_per_kg`. Booking evaluates two checks in order: first the referenced profile must be `APPROVED`, failing which `ERR_WASTE_PROFILE_NOT_APPROVED` (HTTP 409); then the profile must belong to the same job as the shipment, failing which `ERR_SHIPMENT_PROFILE_MISMATCH` (HTTP 409). The shipment's `manifested_kg` is the sum of its line kilograms, and its `disposal_cost_cents` follows the pinned rounding order of §2.7: each line's kilograms multiplied by its rate and by the hazard multiplier of the profile's class — 1.0 for `NON_HAZARDOUS`, 2.5 for `HAZARDOUS` — rounded half-up to whole cents per line, then summed.

The shipment lifecycle is a short conveyor. Dispatch moves `BOOKED` to `IN_TRANSIT`; delivery moves `IN_TRANSIT` to `DELIVERED` and recomputes the job's `shipped_solids_kg` — defined as the manifested kilograms over all of the job's shipments in `DELIVERED` or `RECONCILED`, plus the job's `residual_sludge_kg`. Reconciliation by an `EHSOfficer` moves `DELIVERED` to `RECONCILED` and recomputes the job's `waste_cost_cents`, adding this shipment's disposal cost into the total over reconciled shipments. A `TerminalOperator` may void a shipment in `BOOKED`, `IN_TRANSIT`, or `DELIVERED` as a compensating action; `DELIVERED` to `VOIDED` otherwise occurs only through the reclassification cascade above, never by direct call. Every void recomputes `shipped_solids_kg` and re-runs the return-to-service revert check.

Recording sludge removal is the gate that closes the physical cleaning phase, and it serves both the first pass (`HEEL_REMOVED` to `SLUDGE_REMOVED`) and every rework pass (`REWORK_CLEANING` to `SLUDGE_REMOVED`, the loop edge that second and later passes take). Three checks run in order after ownership: an `APPROVED` waste profile must exist for the job, failing which `ERR_WASTE_PROFILE_NOT_APPROVED`; at least one shipment of the job must stand in `DELIVERED` or `RECONCILED`, failing which `ERR_NO_DELIVERED_SHIPMENT` (HTTP 409); and the supplied `residual_sludge_kg` — the unrecoverable solids left in the tank, defaulting to 0 on the job until recorded — must not be negative, failing which `ERR_INVALID_REQUEST`. The recorded residual is stored and `shipped_solids_kg` is recomputed.

### 3.6. Gas-Free Certification and Confined-Space Entry

With sludge out, the owning supervisor requests gas-free certification, moving the job `SLUDGE_REMOVED` to `GAS_FREE_PENDING`. A `MarineChemist` then issues a certificate carrying the four readings of §2.9; any reading outside its envelope is rejected with `ERR_GAS_FREE_LIMITS_EXCEEDED` (HTTP 422). Issuance stamps `issued_at` from the logical clock, computes `expires_at` twelve hours later, records the chemist's `X-User-ID` as `issued_by_user_id`, and leaves `revalidated` false. Issuing a certificate for a job that already holds a `VALID` one supersedes the old certificate automatically — the prior certificate moves to `SUPERSEDED` — and the job itself advances `GAS_FREE_PENDING` to `GAS_FREE_CERTIFIED` without further action.

A certificate may be revalidated exactly once, by a `MarineChemist`, while it still lives: the clock is examined first, and a certificate whose `expires_at` has been reached rejects the attempt with `ERR_CERT_EXPIRED`; the one-shot flag is examined next, and a certificate already revalidated once rejects with `ERR_CERT_ALREADY_REVALIDATED` (HTTP 409). A successful revalidation extends `expires_at` by six hours and sets `revalidated`.

Revocation and expiry share one cascade, and it is the deepest in the system. When a `MarineChemist` revokes a `VALID` certificate — or the clock sweep expires one — every entry permit anchored to that certificate in `ISSUED` or `ACTIVE` moves to `SUSPENDED`. If the job then holds at least one suspended permit and no permit at all in `ISSUED` or `ACTIVE`, and the job stands in `GAS_FREE_CERTIFIED`, `ENTRY_IN_PROGRESS`, or `ENTRY_COMPLETE`, the job moves to `PAUSED`, recording in `paused_from` the status it held and in `pause_reason` the cause — `CERT_REVOKED` or `CERT_EXPIRED` for these cascades, with `MANUAL` rounding out the field's declared values. Whenever a job lands in `PAUSED`, all of its `SCHEDULED` inspections are cancelled. If instead the job held no `ISSUED` or `ACTIVE` permits at all and stood in `GAS_FREE_CERTIFIED`, it reverts to `GAS_FREE_PENDING` and must be re-certified; permits still `REQUESTED` that reference the dead certificate remain `REQUESTED` but can never issue against it.

Entry permits are the second safety artifact. The owning supervisor requests one with the `job_id`, the anchoring `cert_id`, and a `max_entrants` of at least one; the permit starts `REQUESTED` with its atmosphere dimension `CLEAR`. Permits carry two independent dimensions — a `status` lifecycle and an `atmosphere` dimension that moves in parallel without disturbing the status. Issuance is the `EHSOfficer`'s act and is evaluated after the state checks: the job must stand in `GAS_FREE_CERTIFIED`, failing which the transition is invalid; the referenced certificate must be `VALID`, failing which `ERR_NO_VALID_GAS_FREE_CERT`; the clock must still be strictly before the certificate's `expires_at`, failing which `ERR_CERT_EXPIRED`; and segregation of duties bars the officer whose `X-User-ID` matches the certificate's `issued_by_user_id`, failing which `ERR_SEGREGATION_OF_DUTIES`. Issuance records the officer as the permit's own `issued_by_user_id` and moves `REQUESTED` to `ISSUED`.

Activation belongs to the owning supervisor: the job must still be `GAS_FREE_CERTIFIED`, the anchoring certificate still valid and unexpired (`ERR_CERT_EXPIRED` otherwise), and the atmosphere dimension `CLEAR` (`ERR_ATMOSPHERE_NOT_CLEAR`, HTTP 409, otherwise) — then `ISSUED` becomes `ACTIVE`. Beginning entry is the job-level gate: moving `GAS_FREE_CERTIFIED` to `ENTRY_IN_PROGRESS` requires at least one permit of the job standing `ACTIVE` with atmosphere `CLEAR`, failing which `ERR_NO_VALID_ENTRY_PERMIT` (HTTP 409). Completing entry requires every permit of the job to stand in `CLOSED` or `VOIDED` — any permit still `REQUESTED`, `ISSUED`, `ACTIVE`, or `SUSPENDED` rejects the completion with `ERR_PERMITS_NOT_CLOSED` (HTTP 409) — and moves `ENTRY_IN_PROGRESS` to `ENTRY_COMPLETE`.

Around live entry, permits are suspended, resumed, closed, and voided. An `EHSOfficer` may suspend a permit in `ISSUED` or `ACTIVE`; when the suspended permit was the job's last one standing in `ISSUED` or `ACTIVE`, the job pauses exactly as in the certificate cascade — from `ACTIVE` mid-entry this means `paused_from` records `ENTRY_IN_PROGRESS`, from an issued-but-never-activated permit while the job is still `GAS_FREE_CERTIFIED` it records that state — and the job's `SCHEDULED` inspections are cancelled. Resuming a suspended permit requires the anchoring certificate valid and unexpired (`ERR_CERT_EXPIRED`) and the atmosphere `CLEAR` (`ERR_ATMOSPHERE_NOT_CLEAR`), moving `SUSPENDED` back to `ACTIVE`. The owning supervisor closes a permit from `ACTIVE` or `SUSPENDED` into `CLOSED`. An `EHSOfficer` may void a permit from `REQUESTED`, `ISSUED`, or `SUSPENDED` into `VOIDED`, and the system voids the same three states as part of the job-cancellation and rework cascades.

The atmosphere dimension has its own small machine. Raising an alarm — available to the owning supervisor and to an `EHSOfficer` — moves `CLEAR` to `ALARM` while the permit's status is `ISSUED`, `ACTIVE`, or `SUSPENDED`; against any other status the attempt is an invalid transition. Resolving the alarm is the `EHSOfficer`'s act and moves `ALARM` to `RETEST_REQUIRED`. The dimension returns to `CLEAR` either automatically — when the permit's certificate is revalidated, or when a superseding certificate is issued for the job and the permit's `cert_id` is updated to it — or explicitly when an `EHSOfficer` clears the atmosphere; every one of these paths requires the anchoring certificate to be `VALID`, failing which `ERR_NO_VALID_GAS_FREE_CERT`.

Pause and resume close the loop. A `TerminalOperator` resumes a `PAUSED` job into the status recorded in `paused_from`, and each of the three resume targets has its own gate. Resuming into `GAS_FREE_CERTIFIED` or into `ENTRY_COMPLETE` requires a `VALID` certificate to exist for the job, failing which `ERR_NO_VALID_GAS_FREE_CERT`. Resuming into `ENTRY_IN_PROGRESS` requires the same certificate and, additionally, an `ACTIVE` permit with `CLEAR` atmosphere — or a `SUSPENDED` permit that is first resumed — failing which `ERR_NO_VALID_ENTRY_PERMIT`. A paused job may also re-enter the gas-free pipeline from scratch: requesting gas-free from `PAUSED` is permitted only when no `VALID` certificate exists for the job, clears `paused_from` and `pause_reason`, and lands the job in `GAS_FREE_PENDING` — the recovery edge after certificate revocation or expiry.

### 3.7. Inspection, Findings, and Repair Cycles

Inspections are booked by a `TerminalOperator` against an inspector's calendar while the job stands in `ENTRY_IN_PROGRESS` or `ENTRY_COMPLETE`. The booking names the `job_id`, the `inspector_id`, and the half-open interval from `scheduled_start` to `scheduled_end`, and carries `expected_inspector_version` per §2.6 — a stale inspector view is rejected with `ERR_STALE_VERSION` (HTTP 412) even when the requested interval overlaps nothing, because the client's calendar picture is stale regardless. Calendar conflicts follow §2.8: an intersection with any `SCHEDULED` or `IN_PROGRESS` inspection of the same inspector is rejected with `ERR_INSPECTOR_UNAVAILABLE`, while adjacency is allowed. Booking advances the inspector's `version` by one and lands the inspection in `SCHEDULED`.

Starting the inspection belongs to the assigned `API653Inspector`: the caller's `X-User-ID` must equal the inspection's `inspector_id` (`ERR_FORBIDDEN_FOR_ROLE` otherwise), and the job must have reached `ENTRY_COMPLETE` — attempting to start while the job is still in entry is an invalid transition. Starting moves the inspection `SCHEDULED` to `IN_PROGRESS` and, as a cascade, moves the job `ENTRY_COMPLETE` to `INSPECTION_IN_PROGRESS`. Findings may be recorded only while the inspection is `IN_PROGRESS` and only by the assigned inspector; each finding carries the `inspection_id`, a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, a narrative `description`, and a `requires_repair` flag, and opens in `OPEN`.

Reporting closes the field work: the assigned inspector files the report, moving `IN_PROGRESS` to `REPORTED` and stamping `reported_by_user_id`. Acceptance is the terminal operator's gate and evaluates two checks in order: segregation of duties first — the acceptor's `X-User-ID` must differ from `reported_by_user_id`, failing which `ERR_SEGREGATION_OF_DUTIES` — then the critical-findings rule, which rejects acceptance with `ERR_CRITICAL_FINDINGS_OPEN` (HTTP 409) while any `CRITICAL` finding of this inspection remains `OPEN`. Acceptance here is blocked only by `OPEN` critical findings; the later flush and return-to-service gates of §3.8 are stricter and also count `REPAIR_ORDERED` ones. Acceptance moves the job `INSPECTION_IN_PROGRESS` to `INSPECTION_ACCEPTED` automatically. Rejection instead moves `REPORTED` to `REJECTED`, and the assigned inspector may amend a rejected report — `REJECTED` back to `REPORTED` — to re-file it. A `SCHEDULED` inspection may be cancelled outright by a `TerminalOperator`, and is cancelled by the system whenever its job pauses.

Findings are dispositioned in two ways. A `TerminalOperator` may accept a finding as risk, moving `OPEN` to `ACCEPTED_RISK`, but only for `MINOR` and `MAJOR` severities — a `CRITICAL` finding rejects the attempt with `ERR_FINDING_NOT_RISK_ACCEPTABLE` (HTTP 409). Alternatively, opening a repair order — by a `TerminalOperator`, naming the `finding_id` and a repair-scope `description` — moves the finding `OPEN` to `REPAIR_ORDERED` automatically and denormalizes the `job_id` onto the order from the finding's inspection. The repair itself is worked by the owning contractor supervisor, who starts it (`OPEN` to `IN_PROGRESS`) and completes it (`IN_PROGRESS` to `COMPLETED`, stamping `completed_by_user_id`). Verification belongs to the `API653Inspector` assigned to the finding's inspection: identity must match (`ERR_FORBIDDEN_FOR_ROLE`), and segregation of duties bars the verifier whose `X-User-ID` equals the order's `completed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). Verification marks the order `VERIFIED` — its terminal state — and resolves the finding from `REPAIR_ORDERED` to `RESOLVED`; rejection instead returns the order `COMPLETED` to `IN_PROGRESS` for another work pass.

Rework is the cycle edge of the whole job machine. Once the inspection has been accepted, a `TerminalOperator` may order rework, but only while at least one finding on the accepted inspection stands in `OPEN` or `REPAIR_ORDERED` — with nothing reworkable outstanding, the request is rejected with `ERR_NO_REWORKABLE_FINDINGS` (HTTP 409). Ordering rework moves the job `INSPECTION_ACCEPTED` to `REWORK_CLEANING`, supersedes every `VALID` gas-free certificate of the job — the atmosphere is invalidated by the rework — and voids every permit in `REQUESTED`, `ISSUED`, or `SUSPENDED`. The job then loops back through sludge removal, gas-free certification, entry, and inspection exactly as on its first pass.

### 3.8. Flush, Mass Balance, and Return to Service

When the accepted inspection leaves nothing critical outstanding, the changeover flush begins. Moving `INSPECTION_ACCEPTED` to `FLUSH_IN_PROGRESS` — the owning supervisor's act — is barred while any `CRITICAL` finding on the accepted inspection stands in `OPEN` or `REPAIR_ORDERED`, failing which `ERR_CRITICAL_FINDINGS_OPEN`. Verification is the `EHSOfficer`'s gate: the officer supplies `actual_flush_liters`, and the flush passes when that figure is at least the job's computed `flush_volume_liters` — the boundary is inclusive, so a flush exactly equal to the requirement verifies — failing which `ERR_FLUSH_VOLUME_INSUFFICIENT` (HTTP 409). Success moves `FLUSH_IN_PROGRESS` to `FLUSH_VERIFIED`.

Requesting return to service is the mass-balance gate, evaluated by a `TerminalOperator` against the job in `FLUSH_VERIFIED`. The check compares the job's `shipped_solids_kg` — manifested kilograms over shipments in `DELIVERED` or `RECONCILED`, plus the recorded `residual_sludge_kg` — against the final-basis `expected_solids_kg`: the absolute difference between the two must not exceed the expected figure multiplied by the terminal's `mass_balance_tolerance_pct` divided by one hundred, and a delta exactly equal to the tolerance passes. A breach rejects the request with `ERR_MASS_BALANCE_OUT_OF_TOLERANCE` (HTTP 409).

The same request computes the final `invoice_total_cents`, and the evaluation order is pinned because the discount tier keys off the pre-discount total. First, waste charges are taken as the job's `waste_cost_cents`, the sum of disposal costs over its `RECONCILED` shipments. Second, the flush charge is the job's `flush_volume_liters` at two cents per liter. Third, the pre-discount total is the sum of `base_service_fee_cents`, the waste charges, and the flush charge. Fourth, the tier is read off that pre-discount total: ten percent when it reaches 1,000,000 cents, five percent when it reaches 500,000 cents, and nothing below that. Fifth, the discount is `base_service_fee_cents` multiplied by the tier percentage, rounded half-up to whole cents — the only rounding step in the waterfall. Finally, the invoice total is the pre-discount total minus the discount.

The gate is not sticky. While a job stands in `RTS_PENDING`, any recompute of `shipped_solids_kg` — classically a waste-profile reclassification voiding a `DELIVERED` shipment — re-evaluates the balance, and if it now fails the job automatically falls back to `FLUSH_VERIFIED`. The final return-to-service call therefore re-checks both gates at call time, in order: the critical-findings rule first (`ERR_CRITICAL_FINDINGS_OPEN`), then the mass balance (`ERR_MASS_BALANCE_OUT_OF_TOLERANCE`). Success moves `RTS_PENDING` to `RETURNED_TO_SERVICE`, returns the tank to `IN_SERVICE` with its `current_product_id` set to the job's `to_product_id`, advances the tank's `version` by one, and moves the linked service window to `COMPLETED`.

Abandonment has its own rules. Cancelling a job is defined from `DRAFT`, `SCHEDULED`, `TANK_OOS`, `HEEL_REMOVED`, `SLUDGE_REMOVED`, `GAS_FREE_PENDING`, `GAS_FREE_CERTIFIED`, and `PAUSED`; from any other status the request is an invalid transition. From `DRAFT` there is nothing to unwind. From `SCHEDULED` the linked window's `job_id` is cleared back to null and the window itself stays `PLANNED`. From `TANK_OOS` the tank returns to `IN_SERVICE` with its `version` advanced by one, and the linked window is cancelled. From `HEEL_REMOVED`, `SLUDGE_REMOVED`, or `GAS_FREE_PENDING` the tank likewise returns to `IN_SERVICE` and the linked window is cancelled. From `GAS_FREE_CERTIFIED` or `PAUSED`, a job holding any `ACTIVE` entry permit cannot be cancelled at all — the attempt is rejected with `ERR_JOB_HAS_ACTIVE_PERMIT` (HTTP 409); otherwise every permit in `REQUESTED`, `ISSUED`, or `SUSPENDED` is voided, the tank returns to `IN_SERVICE`, and the linked window is cancelled.

### 3.9. Wastewater Treatment and Discharge Control

Wash water and rinse effluent are tracked as batches against the terminal's treatment plant. Either a `TerminalOperator` or the owning `ContractorSupervisor` collects a batch, naming the `terminal_id`, the source `job_id`, and a `volume_liters` strictly greater than zero; the batch starts `COLLECTED`. A `LabTechnician` submits the lab results `ph` and `tph_mg_l`; values outside the physically meaningful ranges — pH beyond the closed band from 0 to 14, or a negative TPH — are rejected with `ERR_INVALID_REQUEST`. Submission moves `COLLECTED` to `LAB_TESTED` and stamps the technician's `X-User-ID` as `lab_user_id`.

Authorization is the regulated step, and a `TerminalOperator` runs three checks in order. Segregation of duties comes first: the authorizer's `X-User-ID` must differ from the batch's `lab_user_id`, failing which `ERR_SEGREGATION_OF_DUTIES`. The discharge envelope comes next: pH must lie within the closed band from 6.0 to 9.0 and TPH must be at most 15.0 milligrams per liter inclusive, failing which `ERR_DISCHARGE_LIMITS_EXCEEDED` (HTTP 422). Daily capacity comes last: the batch's volume, added to the volumes of every batch of the same terminal already `AUTHORIZED` or `DISCHARGED` under the same `discharge_day`, must not exceed the terminal's `wastewater_daily_capacity_liters` — landing exactly on capacity is permitted — failing which `ERR_DISCHARGE_CAPACITY_EXCEEDED` (HTTP 409). Authorization stamps `discharge_day` with the current UTC calendar date from the logical clock, formatted YYYY-MM-DD, which is the key of the daily capacity bucket, and moves `LAB_TESTED` to `AUTHORIZED`.

From there the batch either leaves the plant or unwinds. Discharge moves `AUTHORIZED` to `DISCHARGED`, the terminal state. Voiding an authorization is the compensating action: it returns `AUTHORIZED` to `COLLECTED`, clears `discharge_day`, and releases the day's allocated liters back into the terminal's capacity. An `EHSOfficer` may instead reject a `LAB_TESTED` batch outright, moving it to `REJECTED`, and returning a rejected batch to storage moves `REJECTED` back to `COLLECTED` for another attempt.

## 4. Endpoint Definitions

All endpoints are mounted under `/ops`. Creation endpoints that mint a new resource — terminals, products, tanks, contractors, safety events, cleaning jobs, service windows, waste profiles, waste shipments, gas-free certificates, entry permits, inspectors, inspections, inspection findings, repair orders, and wastewater batches — answer 201 on success; every other successful call, including all state-transition actions, patches, and reads, answers 200. Error responses carry the error identifiers catalogued in §5 within the envelope of §2.2. Request and response bodies for each operation are reconstructed from the workflow narratives of §3 rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /ops/terminals | Create a terminal (capacity, thresholds, score variant configuration) | TerminalAdmin |
| GET | /ops/terminals/{terminalId} | Get a terminal | All roles |
| GET | /ops/terminals | List terminals (paginated) | All roles |
| POST | /ops/products | Register a product grade | TerminalAdmin |
| GET | /ops/products/{productId} | Get a product | All roles |
| GET | /ops/products | List products (paginated) | All roles |
| POST | /ops/tanks | Register a tank | TerminalAdmin |
| GET | /ops/tanks/{tankId} | Get a tank | All roles |
| GET | /ops/tanks | List tanks, filterable by `terminal_id`, `current_product_id`, `status` (paginated) | All roles |
| POST | /ops/contractors | Register a contractor (enters as `APPLICANT`) | TerminalAdmin |
| GET | /ops/contractors/{contractorId} | Get a contractor | All roles |
| GET | /ops/contractors | List contractors, filterable by `status` (paginated) | All roles |
| POST | /ops/contractors/{contractorId}/qualify | Qualify a contractor against a terminal's score variant and threshold | TerminalAdmin |
| POST | /ops/contractors/{contractorId}/suspend | Suspend a contractor | TerminalAdmin |
| POST | /ops/contractors/{contractorId}/reinstate | Reinstate a suspended contractor (score re-check) | TerminalAdmin |
| POST | /ops/contractors/{contractorId}/bar | Bar a contractor (terminal state) | TerminalAdmin |
| POST | /ops/safety-events | Record a safety event (append-only); recomputes the contractor's score | EHSOfficer |
| GET | /ops/safety-events/{eventId} | Get a safety event | All roles |
| GET | /ops/safety-events | List safety events, filterable by `contractor_id` (paginated) | All roles |
| POST | /ops/cleaning-jobs | Create a cleaning job in `DRAFT`; computes changeover class, provisional sludge estimate, flush volume | TerminalOperator |
| GET | /ops/cleaning-jobs/{jobId} | Get a cleaning job | All roles |
| GET | /ops/cleaning-jobs | List cleaning jobs, filterable by `terminal_id`, `tank_id`, `contractor_id`, `from_product_id`, `to_product_id`, `window_id`, `status` (paginated) | All roles |
| PATCH | /ops/cleaning-jobs/{jobId} | Patch fee/lines flag while `DRAFT` (OCC on job version) | TerminalOperator |
| POST | /ops/cleaning-jobs/{jobId}/schedule | Schedule a job against a planned service window | TerminalOperator |
| POST | /ops/cleaning-jobs/{jobId}/take-out-of-service | Take the tank out of service to begin cleaning | TerminalOperator |
| POST | /ops/cleaning-jobs/{jobId}/record-heel-removal | Record metered heel pump-out volume | ContractorSupervisor |
| POST | /ops/cleaning-jobs/{jobId}/record-sludge-removal | Record sludge removal completion and residual solids | ContractorSupervisor |
| POST | /ops/cleaning-jobs/{jobId}/request-gas-free | Request gas-free certification | ContractorSupervisor |
| POST | /ops/cleaning-jobs/{jobId}/begin-entry | Begin manned entry (requires `ACTIVE` permit with `CLEAR` atmosphere) | ContractorSupervisor |
| POST | /ops/cleaning-jobs/{jobId}/complete-entry | Complete entry phase (all permits closed/voided) | ContractorSupervisor |
| POST | /ops/cleaning-jobs/{jobId}/order-rework | Order rework after accepted inspection (cyclic loop back) | TerminalOperator |
| POST | /ops/cleaning-jobs/{jobId}/begin-flush | Begin product-changeover flush | ContractorSupervisor |
| POST | /ops/cleaning-jobs/{jobId}/verify-flush | Verify flush volume meets the computed requirement | EHSOfficer |
| POST | /ops/cleaning-jobs/{jobId}/request-rts | Request return-to-service (mass balance gate; computes invoice) | TerminalOperator |
| POST | /ops/cleaning-jobs/{jobId}/return-to-service | Return tank to service and recertify | TerminalOperator |
| POST | /ops/cleaning-jobs/{jobId}/resume | Resume a paused job back to `paused_from` | TerminalOperator |
| POST | /ops/cleaning-jobs/{jobId}/cancel | Cancel a non-terminal job | TerminalOperator |
| POST | /ops/service-windows | Book an out-of-service window on a tank (OCC on tank version; overlap + 24h buffer rules) | TerminalOperator |
| GET | /ops/service-windows/{windowId} | Get a service window | All roles |
| GET | /ops/service-windows | List service windows, filterable by `tank_id`, `job_id`, `status` (paginated) | All roles |
| POST | /ops/service-windows/{windowId}/activate | Activate a window inside its planned interval | TerminalOperator |
| POST | /ops/service-windows/{windowId}/complete | Complete an active window | TerminalOperator |
| POST | /ops/service-windows/{windowId}/cancel | Cancel a planned window (blocked while linked to a live job) | TerminalOperator |
| POST | /ops/waste-profiles | Draft a waste profile for a job | ContractorSupervisor |
| GET | /ops/waste-profiles/{profileId} | Get a waste profile | All roles |
| GET | /ops/waste-profiles | List waste profiles, filterable by `job_id`, `status` (paginated) | All roles |
| POST | /ops/waste-profiles/{profileId}/submit | Submit a draft (or rejected) profile for EHS review | ContractorSupervisor |
| POST | /ops/waste-profiles/{profileId}/approve | Approve a submitted profile (one approved profile per job) | EHSOfficer |
| POST | /ops/waste-profiles/{profileId}/reject | Reject a submitted profile | EHSOfficer |
| POST | /ops/waste-profiles/{profileId}/reclassify | Reclassify hazard class of an approved profile; voids non-reconciled shipments and may revert the job's RTS gate | EHSOfficer |
| POST | /ops/waste-shipments | Book a waste shipment against an approved profile | ContractorSupervisor |
| GET | /ops/waste-shipments/{shipmentId} | Get a waste shipment | All roles |
| GET | /ops/waste-shipments | List waste shipments, filterable by `job_id`, `profile_id`, `status` (paginated) | All roles |
| POST | /ops/waste-shipments/{shipmentId}/dispatch | Dispatch a booked shipment | ContractorSupervisor |
| POST | /ops/waste-shipments/{shipmentId}/deliver | Mark shipment delivered at the disposal facility | ContractorSupervisor |
| POST | /ops/waste-shipments/{shipmentId}/reconcile | Reconcile a delivered shipment (EHS receipt verification) | EHSOfficer |
| POST | /ops/waste-shipments/{shipmentId}/void | Void a non-reconciled shipment (compensating action) | TerminalOperator |
| POST | /ops/gas-free-certificates | Issue a gas-free certificate for a job in `GAS_FREE_PENDING` | MarineChemist |
| GET | /ops/gas-free-certificates/{certId} | Get a gas-free certificate | All roles |
| GET | /ops/gas-free-certificates | List gas-free certificates, filterable by `job_id`, `status` (paginated) | All roles |
| POST | /ops/gas-free-certificates/{certId}/revalidate | Extend a valid certificate once by six hours | MarineChemist |
| POST | /ops/gas-free-certificates/{certId}/revoke | Revoke a certificate (cascades: permits suspend, job pauses or reverts, inspections cancel) | MarineChemist |
| POST | /ops/entry-permits | Request a confined-space entry permit | ContractorSupervisor |
| GET | /ops/entry-permits/{permitId} | Get an entry permit | All roles |
| GET | /ops/entry-permits | List entry permits, filterable by `job_id`, `cert_id`, `status` (paginated) | All roles |
| POST | /ops/entry-permits/{permitId}/issue | Issue a requested permit (segregation of duties vs cert issuer) | EHSOfficer |
| POST | /ops/entry-permits/{permitId}/activate | Activate an issued permit for entry | ContractorSupervisor |
| POST | /ops/entry-permits/{permitId}/suspend | Suspend a permit | EHSOfficer |
| POST | /ops/entry-permits/{permitId}/resume | Resume a suspended permit | EHSOfficer |
| POST | /ops/entry-permits/{permitId}/close | Close a permit after entry work ends | ContractorSupervisor |
| POST | /ops/entry-permits/{permitId}/void | Void a permit | EHSOfficer |
| POST | /ops/entry-permits/{permitId}/raise-alarm | Raise an atmospheric alarm (parallel dimension) | ContractorSupervisor, EHSOfficer |
| POST | /ops/entry-permits/{permitId}/resolve-alarm | Resolve an alarm; retest required before clearing | EHSOfficer |
| POST | /ops/entry-permits/{permitId}/clear-atmosphere | Clear the atmosphere dimension after retest | EHSOfficer |
| POST | /ops/inspectors | Register an API-certified inspector | TerminalAdmin |
| GET | /ops/inspectors/{inspectorId} | Get an inspector | All roles |
| GET | /ops/inspectors | List inspectors (paginated) | All roles |
| POST | /ops/inspections | Book an API 653 inspection on an inspector's calendar (OCC on inspector version; adjacency allowed) | TerminalOperator |
| GET | /ops/inspections/{inspectionId} | Get an inspection | All roles |
| GET | /ops/inspections | List inspections, filterable by `job_id`, `inspector_id`, `status` (paginated) | All roles |
| POST | /ops/inspections/{inspectionId}/start | Start a scheduled inspection | API653Inspector |
| POST | /ops/inspections/{inspectionId}/report | File the inspection report | API653Inspector |
| POST | /ops/inspections/{inspectionId}/accept | Accept the report (no `OPEN` `CRITICAL` findings; segregation of duties vs reporting inspector) | TerminalOperator |
| POST | /ops/inspections/{inspectionId}/reject | Reject the report | TerminalOperator |
| POST | /ops/inspections/{inspectionId}/amend | Amend a rejected report (re-report cycle) | API653Inspector |
| POST | /ops/inspections/{inspectionId}/cancel | Cancel a scheduled inspection | TerminalOperator |
| POST | /ops/inspection-findings | Record a finding on an `IN_PROGRESS` inspection | API653Inspector |
| GET | /ops/inspection-findings/{findingId} | Get a finding | All roles |
| GET | /ops/inspection-findings | List findings, filterable by `inspection_id`, `status`, `severity` (paginated) | All roles |
| POST | /ops/inspection-findings/{findingId}/accept-risk | Accept a `MINOR`/`MAJOR` finding as risk | TerminalOperator |
| POST | /ops/repair-orders | Open a repair order for a finding | TerminalOperator |
| GET | /ops/repair-orders/{repairId} | Get a repair order | All roles |
| GET | /ops/repair-orders | List repair orders, filterable by `finding_id`, `job_id`, `status` (paginated) | All roles |
| POST | /ops/repair-orders/{repairId}/start | Start repair work | ContractorSupervisor |
| POST | /ops/repair-orders/{repairId}/complete | Mark repair complete | ContractorSupervisor |
| POST | /ops/repair-orders/{repairId}/verify | Verify a completed repair (segregation of duties vs completer) | API653Inspector |
| POST | /ops/repair-orders/{repairId}/reject | Reject a completed repair (rework cycle) | API653Inspector |
| POST | /ops/wastewater-batches | Collect a wastewater batch from a job | TerminalOperator, ContractorSupervisor |
| GET | /ops/wastewater-batches/{batchId} | Get a wastewater batch | All roles |
| GET | /ops/wastewater-batches | List wastewater batches, filterable by `terminal_id`, `job_id`, `status`, `discharge_day` (paginated) | All roles |
| POST | /ops/wastewater-batches/{batchId}/submit-lab | Submit lab results (pH, TPH) | LabTechnician |
| POST | /ops/wastewater-batches/{batchId}/authorize | Authorize discharge (limits, daily capacity, segregation of duties vs lab tech) | TerminalOperator |
| POST | /ops/wastewater-batches/{batchId}/discharge | Discharge an authorized batch | TerminalOperator |
| POST | /ops/wastewater-batches/{batchId}/reject | Reject a lab-tested batch | EHSOfficer |
| POST | /ops/wastewater-batches/{batchId}/void-authorization | Void an authorization (releases daily allocation; compensating action) | TerminalOperator |
| POST | /ops/wastewater-batches/{batchId}/return-to-storage | Return a rejected batch to storage | TerminalOperator |
| POST | /ops/_clock/set_current_utc | Set the logical clock; advancing sweeps certificate expiry and window `OVERRUN` transitions | TerminalAdmin |

## 5. Error Code Catalogue

The table below is a pure catalogue: the trigger condition for each error is specified in the workflow narratives of §2 and §3, not repeated here.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_GAS_FREE_LIMITS_EXCEEDED | 422 |
| ERR_NO_VALID_GAS_FREE_CERT | 409 |
| ERR_CERT_EXPIRED | 409 |
| ERR_CERT_ALREADY_REVALIDATED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_CONTRACTOR_NOT_QUALIFIED | 409 |
| ERR_INCOMPATIBLE_CHANGEOVER | 422 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_WINDOW_BUFFER_VIOLATION | 409 |
| ERR_WINDOW_NOT_ACTIVE | 409 |
| ERR_WINDOW_UNAVAILABLE | 409 |
| ERR_WINDOW_LINKED | 409 |
| ERR_TANK_NOT_IN_SERVICE | 409 |
| ERR_WASTE_PROFILE_NOT_APPROVED | 409 |
| ERR_PROFILE_ALREADY_APPROVED | 409 |
| ERR_SHIPMENT_PROFILE_MISMATCH | 409 |
| ERR_NO_DELIVERED_SHIPMENT | 409 |
| ERR_NO_VALID_ENTRY_PERMIT | 409 |
| ERR_ATMOSPHERE_NOT_CLEAR | 409 |
| ERR_PERMITS_NOT_CLOSED | 409 |
| ERR_JOB_HAS_ACTIVE_PERMIT | 409 |
| ERR_INSPECTOR_UNAVAILABLE | 409 |
| ERR_CRITICAL_FINDINGS_OPEN | 409 |
| ERR_FINDING_NOT_RISK_ACCEPTABLE | 409 |
| ERR_NO_REWORKABLE_FINDINGS | 409 |
| ERR_FLUSH_VOLUME_INSUFFICIENT | 409 |
| ERR_MASS_BALANCE_OUT_OF_TOLERANCE | 409 |
| ERR_DISCHARGE_LIMITS_EXCEEDED | 422 |
| ERR_DISCHARGE_CAPACITY_EXCEEDED | 409 |
