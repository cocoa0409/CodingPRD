# Hospital Bed Flow API — Product Requirements Document

## 1. Introduction

Acute-care hospitals run on a finite, perishable resource: the staffed inpatient bed. Every morning a capacity coordinator faces the same arithmetic — patients arriving through the Emergency Department who have nowhere to go, patients medically ready to leave who are stuck behind a missing nursing-home placement or an overdue transport, and a housekeeping queue that can turn a clean room around in twenty minutes or sit untouched for three hours. When these signals live in separate spreadsheets, phone calls, and whiteboards, the result is ED boarding, ambulance diversion, and avoidable bed-days that no one can account for after the fact.

This document specifies the **Hospital Bed Flow API**, a single system of record for bed inventory, admission/transfer/discharge (ADT) events, environmental-services (EVS) turnover, transfer-center placement, discharge-barrier tracking, and house-wide capacity surveillance. The platform models each nursing unit and its beds as a strict ownership tree, while treating encounters, placement requests, turnover tasks, discharge barriers, and surge declarations as cross-cutting peers that reference units, beds, and encounters by identifier. Bed status follows a turnover cycle; an encounter moves through an ADT lifecycle; a placement request branches through an auto-selection fork; and a unit's operational posture is continuously re-derived from its live occupancy and any declared surge. The goal is that any operator — placement, nursing, housekeeping, transfer center, or discharge planning — reads the same numbers and acts on the same rules.

Because length-of-stay, boarding duration, EVS aging, and discharge delay all depend on the passage of time, the system keeps a single simulated clock that can be advanced under test control, and a logical operations counter that ages and expires stale placement requests. Everything downstream — long-stay flags, SLA breaches, priority scoring — is computed against that one clock so that the house's state is always internally consistent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming that user's role. If either header is missing or invalid, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. When the headers are present but the named role is not permitted to perform the requested operation under the authorization rules below, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are exactly six roles, spelled precisely as follows: `FlowAdmin`, `BedControlCoordinator`, `ChargeNurse`, `TransferCenterAgent`, `CaseManager`, and `EvsTech`. `FlowAdmin` is the house-wide operations administrator responsible for unit and bed lifecycle, surge declarations, the simulated clock, operations runs, and overrides. `BedControlCoordinator` is the central placement authority that drives ADT, placement, transfers, surge, and huddles. `ChargeNurse` owns unit-level bed status — bed creation, direct cleaning, blocking, and EVS requests. `TransferCenterAgent` registers incoming patients and drives placement requests. `CaseManager` handles discharge planning: discharge orders, discharge, and barrier management. `EvsTech` is the environmental-services technician who claims and completes turnover tasks.

All six roles are **opaque operator identifiers**: in every case, `X-User-ID` is an operator handle that is not tied to any persisted entity, and the server never compares it to any resource's `id` for ownership. The server may record the acting operator where a workflow calls for it — for example, when an `EvsTech` (or, on that user's behalf, a `FlowAdmin`) claims a turnover task, the acting `X-User-ID` is written to `assigned_tech_id` on that task — but no role's identity is checked against a stored foreign key. Authorization is therefore purely role-based: the per-endpoint authorized-role lists in Section 4 are the sole access-control surface, and there is no notion of "the user who owns this encounter."

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

Every list endpoint accepts two query parameters: `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and may be at most 100. `offset` defaults to 0 when omitted and must be 0 or greater. A `limit` outside the inclusive range of 1 through 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422). List results are ordered by `created_at` ascending unless a specific endpoint declares a different ordering (the EVS task list and certain scored lists override this, as described in their workflows). The response envelope's `meta` block carries `limit`, `offset`, `total_count`, and `has_more` for list responses, where `total_count` is the count of all matching records before the page window is applied and `has_more` is true when more records remain beyond the returned page.

### 2.4. Common Resource Properties and Identifiers

Most resources expose four common properties. The `id` is a server-minted UUID with no type prefix. `created_at` is the ISO 8601 UTC timestamp (three fractional digits) at which the resource was created. `updated_at` is the ISO 8601 UTC timestamp of the most recent mutation. `version` is an integer that begins at 1 and increments by exactly 1 on every mutation of the resource. These four apply to `Unit`, `Bed`, `Encounter`, `BedRequest`, `EvsTask`, `DischargeBarrier`, and `SurgeEvent`.

Two entities are exceptions. `CapacityHuddle` is an immutable snapshot that carries `id` and `created_at` and also exposes `version` and `updated_at` per the common pattern, but is never mutated after creation. The append-only `AdtEvent` record is the genuine exception: it carries only `id` and `created_at` — it has no `updated_at` and no `version`, because ADT events are written once and never modified.

`created_at`, `updated_at`, and the various clock-stamped fields are distinct concepts: the clock-stamped business timestamps (such as `admit_decision_at`, `admitted_at`, `discharged_at`) are driven by the simulated clock described in Section 2.9, whereas `created_at`/`updated_at` reflect record bookkeeping.

### 2.5. Nested Resource Resolution

Beds are the only nested resource: a bed lives under its owning unit, addressed through the unit-and-bed path hierarchy. When a request names both a unit and a bed, the server validates path-referenced resources left to right — first the unit, then the bed — and returns `ERR_NOT_FOUND` (HTTP 404) as soon as any referenced resource in the path does not exist. A bed whose owning unit does not exist can therefore never be reached. The same left-to-right existence rule governs every path that names a parent resource before a child (an encounter before its ADT event listing, for instance). FK references carried in a request **body** — such as `encounter_id`, `bed_id`, `unit_id`, or `preferred_unit_id` — are validated separately: if a body-referenced resource does not resolve, the request fails with `ERR_REFERENCE_NOT_FOUND` (HTTP 404), distinct from the path-level 404.

### 2.6. Validation Order and Error Precedence

When several conditions could reject a request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN`), then existence of all path-referenced resources (`ERR_NOT_FOUND`), then existence of all body-referenced foreign keys (`ERR_REFERENCE_NOT_FOUND`), then request-body well-formedness — required fields present and enum values legal (`ERR_INVALID_REQUEST`, HTTP 422). Only after these structural checks pass does the system evaluate state legality: a transition requested from a state in which it is not defined yields `ERR_INVALID_STATE` (HTTP 409). Business-rule checks specific to each workflow — isolation, telemetry, cohort, bed availability, barriers, and so on, described in Section 3 — are evaluated after the state check. Pagination-bounds validation (`ERR_INVALID_PAGINATION`) guards list endpoints. The practical consequence: a request that is both unauthorized and malformed reports the authorization failure, and a transition attempted on a resource in the wrong state reports `ERR_INVALID_STATE` rather than any later business condition.

### 2.7. Unit Posture and the Surge Override

Every unit continuously re-derives an operational posture from its live bed inventory, and this derivation is the backbone of placement scoring and EVS prioritization. The system recognizes a unit's **staffed** beds as those whose `status` is `CLEAN`, `DIRTY`, or `OCCUPIED`; beds that are `BLOCKED` or `RETIRED` are excluded from staffed inventory. From these, `occupancy_pct` is the number of `OCCUPIED` beds divided by the number of staffed beds, multiplied by 100 and rounded half-up to two decimal places; when a unit has zero staffed beds, `occupancy_pct` is `0.00`.

The unit's **derived posture** (`derived_posture`) follows from these two counts. If the unit has no staffed beds at all, `derived_posture` is `CLOSED`. Otherwise the system compares `occupancy_pct` against two inclusive thresholds: at 95.00 percent or above, posture is `RED`; at 85.00 percent or above but below 95.00 percent, posture is `YELLOW`; below 85.00 percent, posture is `GREEN`. Separately, a unit carries a **declared surge level** (`declared_surge_level`) equal to the highest level among its currently `OPEN` surge events (ranking `YELLOW` below `RED`), or `GREEN` when no surge is open. The unit's `effective_posture` is then the more severe of `derived_posture` and `declared_surge_level`, where severity ranks `GREEN` below `YELLOW`, `YELLOW` below `RED`, and `RED` below `CLOSED`. These derived fields — `occupancy_pct`, `derived_posture`, `declared_surge_level`, and `effective_posture` — are recomputed on every bed-status change in the unit, on every surge open or stand-down, and whenever the unit is read.

### 2.8. Derived Counts and the Reconciliation Principle

A unit also maintains four count fields that must always reconcile with its beds: `total_bed_count` is the number of non-`RETIRED` beds whose `unit_id` is this unit; `staffed_bed_count` is the number of beds in `CLEAN`, `DIRTY`, or `OCCUPIED` status; `occupied_bed_count` is the number of beds in `OCCUPIED` status; and `clean_available_count` is the number of beds in `CLEAN` status. These counts begin at 0 for a newly created unit and are recomputed whenever a bed is added, removed from inventory, or changes status. Any operation that changes a bed's status or membership refreshes the affected unit's counts, then refreshes its posture fields, in that order, so the two layers never disagree.

### 2.9. The Simulated Clock and Time-Based Computation

All business time is read from a single server-held simulated clock expressed in UTC. The `FlowAdmin` may set this clock to a supplied instant; doing so immediately changes every live time-based computation — length-of-stay, ED boarding, EVS aging, and discharge delay — for resources read afterward. Time-derived fields fall into two categories. **Live** fields are recomputed against the current clock every time the resource is read (for example, a boarding patient's boarding hours grow as the clock advances). **Frozen** fields are captured once at a lifecycle moment and never change afterward (boarding hours freeze at placement; length-of-stay freezes at discharge). Each computation in Section 3 states which behavior applies. All durations derived from the clock are expressed in hours rounded half-up to two decimal places unless otherwise stated, and every duration-based threshold in this document is inclusive.

### 2.10. Optimistic Concurrency on Bed Confirmation

One placement step is guarded by optimistic concurrency control to prevent two coordinators from committing the same bed. When confirming an assigned placement request — the step that flips the assigned bed to `OCCUPIED` and the patient to `PLACED` — the request body must include `expected_bed_version`, which is not optional and must carry the client's last observed `version` of the assigned bed. If that value does not equal the bed's current `version`, the confirmation is rejected with `ERR_STALE_BED_VERSION` (HTTP 412). This catches the situation where another placement request was already confirmed into the same bed since the client last read it — that prior confirmation legitimately took the bed `OCCUPIED` and advanced its `version` — so the client's view is stale and the seat is gone. A successful confirmation itself increments the bed's `version` by 1. No other endpoint accepts or requires a version field.

### 2.11. Bed-Eligibility Safety Checks

Three patient-to-bed safety constraints and one availability constraint govern every operation that places a patient on a specific bed. The same four checks apply identically to exactly three operations: manually assigning a bed to a queued request, confirming an assigned request, and transferring a placed patient. In all three, a patient flagged as requiring isolation may not land on a bed that is not `isolation_capable` — a violation is rejected with `ERR_ISOLATION_REQUIRED` (HTTP 409). A patient flagged as requiring telemetry may not land on a bed that is not `telemetry_capable` — rejected with `ERR_TELEMETRY_REQUIRED` (HTTP 409). For a `SEMIPRIVATE` target bed, the bed's `sex_cohort` must be either `NONE` or equal to the patient's `sex`; a conflicting cohort is rejected with `ERR_COHORT_CONFLICT` (HTTP 409), while `PRIVATE` beds accept any cohort. And the target bed must be `CLEAN`; a bed in any other status is rejected with `ERR_BED_NOT_AVAILABLE` (HTTP 409). When several of these conditions could apply, they are evaluated in the order listed here — isolation, then telemetry, then cohort, then availability — so the returned error is deterministic; these business-safety checks all run after the state-legality check described in Section 2.6.

## 3. Business Logic & Workflows

### 3.1. Building the House: Units and Bed Inventory

A `FlowAdmin` stands up each nursing unit, supplying a `name` and a `unit_type` — one of `MEDSURG`, `TELEMETRY`, `ICU`, or `ED` — and optionally a `gmlos_days` benchmark (the geometric-mean length-of-stay target in days for that unit, defaulting to 3) that later governs long-stay flagging. A new unit begins with all four bed counts at 0, `derived_posture` and `effective_posture` both `CLOSED`, and `declared_surge_level` at `GREEN`.

Beds are added into a unit by a `FlowAdmin` or a `ChargeNurse`, who supply the owning `unit_id`, a `label` such as a room-and-bed designation, and optionally `room_type` (`PRIVATE` or `SEMIPRIVATE`, defaulting to `SEMIPRIVATE`), `isolation_capable` (whether the room supports contact or negative-pressure isolation, defaulting to false), and `telemetry_capable` (whether the bed has cardiac telemetry, defaulting to false). A freshly added bed enters life in `DIRTY` status with `sex_cohort` set to `NONE`, and the owning unit's `total_bed_count` and `staffed_bed_count` are recomputed to include it. Each bed also carries a `current_encounter_id` back-pointer (the encounter occupying it, or null when not occupied) and a `blocked_reason` that is populated only while the bed is blocked.

Beds may be browsed within a unit, and a status filter narrows that listing; the unit-and-bed list is the canonical way to look up a specific bed once auto-placement has chosen one. When a bed is read directly, the response reflects its current `status`, `sex_cohort`, and pointers.

### 3.2. The Bed Turnover Cycle

A bed cycles through cleanliness states as patients come and go. The core loop runs `CLEAN → OCCUPIED → DIRTY → CLEAN`. A `DIRTY` bed becomes `CLEAN` in one of two ways: a `ChargeNurse` or `EvsTech` may mark it clean directly, or the completion of a turnover task may drive the same transition. The direct mark-clean path is allowed only when the bed is currently `DIRTY`; it preserves the bed's `sex_cohort` (routine turnover keeps whatever cohort the room last held), and it cancels any open turnover task on that bed — any task in `REQUESTED`, `ASSIGNED`, or `IN_PROGRESS` is moved to `CANCELLED`. The completion-driven path, by contrast, is itself the turnover task finishing, so it does not cancel a task. After either path, the unit's `clean_available_count` and posture are recomputed.

A `CLEAN` bed becomes `OCCUPIED` only as a system side-effect of placing or transferring a patient into it — never by a direct call — and only when the bed is `CLEAN` and the isolation, telemetry, and cohort checks all pass. On that transition the bed's `current_encounter_id` is set to the placing encounter, its `sex_cohort` is set to that encounter's `sex`, and the unit's `occupied_bed_count`, `occupancy_pct`, and posture are recomputed. When a patient later transfers out, discharges, or is cancelled out of the bed, an `OCCUPIED` bed returns to `DIRTY`: its `current_encounter_id` is cleared, the unit's `occupied_bed_count` and posture are recomputed, and the system automatically opens a turnover task for that bed (a fresh task in `REQUESTED` status, typed `ISOLATION` if the departing patient required isolation and `ROUTINE` otherwise).

Beds can also be pulled from service. From `CLEAN` or `DIRTY`, a `ChargeNurse` or `FlowAdmin` may block a bed, which requires a `blocked_reason` (one of `MAINTENANCE`, `STAFFING`, or `INFECTION_CONTROL`); the bed moves to `BLOCKED`, leaves staffed inventory so `staffed_bed_count` decrements, and the unit's `occupancy_pct` and `effective_posture` are recomputed. Blocking a bed that was `DIRTY` also cancels any open turnover task on it. A bed cannot be blocked while `OCCUPIED`, and an attempt to do so — or a block request missing its `blocked_reason` — is rejected with `ERR_BED_OCCUPIED` (HTTP 409). Unblocking a `BLOCKED` bed returns it to `DIRTY`, clears `blocked_reason` back to null, **resets `sex_cohort` to `NONE`** (an unblock is treated as a deep room turnover that wipes the cohort designation, unlike routine cleaning which preserves it), restores it to staffed inventory, and recomputes the unit's counts and posture. Finally, a `FlowAdmin` may retire a `BLOCKED` bed, which is terminal: the bed enters `RETIRED`, permanently leaves inventory, and the unit's `total_bed_count` is recomputed downward. Each of these block, unblock, and retire transitions is defined only from the stated source state, and a request from any other state is rejected with `ERR_INVALID_STATE`.

### 3.3. Registration and the ED Boarding Clock

A patient's stay begins when a `BedControlCoordinator`, `TransferCenterAgent`, or `FlowAdmin` registers an encounter, supplying the patient's `mrn`, `sex` (`MALE` or `FEMALE`), and optionally `requires_isolation`, `requires_telemetry`, and `origin`. The `origin` is one of `ED`, `DIRECT`, or `TRANSFER_IN` and defaults to `ED`; ED patients board until placed, whereas direct and transfer-in patients place straight through. A new encounter starts in `REGISTERED`, with all computed time fields null and all counters at zero. The encounter also tracks `current_bed_id` (the bed it occupies, set and cleared by ADT side-effects), `transferred_from_bed_id` (the bed it occupied immediately before its most recent transfer), and a running `open_barrier_count`.

When a `BedControlCoordinator` or `FlowAdmin` places the admit order, a `REGISTERED` encounter advances to `ADMIT_PENDING`: `admit_decision_at` is stamped with the current clock and an admit ADT event is appended. For an ED-origin encounter, the admit order automatically advances the encounter onward to `BOARDING` in the same operation; a `BedControlCoordinator` may also move an `ADMIT_PENDING` ED encounter to `BOARDING` explicitly, which is permitted only when the encounter is `ADMIT_PENDING` and its `origin` is `ED`. From the moment an ED patient enters boarding, **boarding hours accrue from `admit_decision_at`**.

While an encounter is `BOARDING`, its `boarding_hours` is a live value: the difference between the current clock and `admit_decision_at`, expressed in hours and rounded half-up to two decimal places. Once a `BOARDING → PLACED` transition occurs, `boarding_hours` freezes to the difference between the placement event's timestamp and `admit_decision_at`. If neither situation applies, `boarding_hours` is `0.00`. A companion flag, `boarding_breached`, is true exactly when `boarding_hours` is at least 4.0 hours — the ED boarding service-level threshold — and false otherwise. These boarding fields, along with the length-of-stay and barrier fields, are recomputed whenever the encounter is read.

### 3.4. Transfer-Center Placement: Requests, Scoring, and the Auto-Place Fork

Placement is choreographed through bed requests. A `TransferCenterAgent` or `BedControlCoordinator` creates a request for a waiting patient, supplying the `encounter_id`, optionally a `preferred_unit_id` (a desired destination unit), optionally a list of `acceptable_unit_types` (allowed unit types; an empty list means any type is acceptable), and optionally a `priority` of `STAT`, `URGENT`, or `ROUTINE` (defaulting to `ROUTINE`). A new request enters `QUEUED`, and its `queued_ops_index` records the value of the global operations counter at that moment, anchoring later expiry. While queued, `assigned_bed_id` and `match_score` are null.

A queued request can be filled two ways. In the **auto-place** path, a `BedControlCoordinator` or `TransferCenterAgent` asks the server to select the best eligible bed; on success the request advances `QUEUED → ASSIGNED` with `assigned_bed_id` set to the chosen bed and `match_score` set to that bed's score, and the chosen bed is reserved — it stays `CLEAN` and is not yet `OCCUPIED` until confirmation. In the **manual assign** path, a `BedControlCoordinator` names a specific `bed_id`; the same `QUEUED → ASSIGNED` transition records that bed as `assigned_bed_id` and computes its `match_score`, provided the bed is `CLEAN` and passes the isolation, telemetry, and cohort checks.

The candidate pool and scoring are the heart of placement. A bed is **eligible** only if every one of the following holds: its `status` is `CLEAN`; the request's `acceptable_unit_types` is empty or the bed's unit `unit_type` is one of those types; the patient does not require isolation, or the bed is `isolation_capable`; the patient does not require telemetry, or the bed is `telemetry_capable`; and the bed's `room_type` is `PRIVATE`, or the bed's `sex_cohort` is either `NONE` or the patient's `sex`. Among eligible beds the server picks the one with the highest `match_score`, computed as follows. The score starts at 0. If the bed is `isolation_capable` but the patient does not require isolation, the score is reduced by 10 (an isolation-waste penalty). If the bed is `telemetry_capable` but the patient does not require telemetry, the score is reduced by 5 (a telemetry-waste penalty). A posture bonus is then added based on the bed's unit `effective_posture`: 20 for `GREEN`, 10 for `YELLOW`, and 0 for `RED` or `CLOSED`. Finally, if the request named a `preferred_unit_id` and the bed's `unit_id` equals it, 50 is added. When two eligible beds tie on the highest score, the bed with the lower unit `occupancy_pct` wins; if they still tie, the bed with the earlier `created_at` wins. The bed's `id` is never used as a tiebreaker. If the eligible pool is empty, auto-place selects nothing, leaves the request in `QUEUED`, and returns `ERR_NO_ELIGIBLE_BED` (HTTP 409).

An assigned request can be released back to the queue by a `BedControlCoordinator` or `TransferCenterAgent`: the `ASSIGNED → QUEUED` transition clears `assigned_bed_id` and `match_score` to null, releases the bed reservation, and resets `queued_ops_index` to the current operations counter so the expiry clock restarts. Either party may also cancel a request outright from `QUEUED` or `ASSIGNED`, which moves it to `CANCELLED`; cancelling an assigned request releases its bed reservation.

Queued requests do not wait forever. The operations run (described in Section 3.9) advances a logical counter and sweeps the queue: any request still `QUEUED` whose age — the current operations counter minus its `queued_ops_index` — has reached 2 or more is moved to `EXPIRED`.

### 3.5. Confirming a Placement and the Stale-Bed Guard

Confirmation is the commit step that actually seats the patient. A `BedControlCoordinator` or `TransferCenterAgent` confirms an `ASSIGNED` request, supplying `expected_bed_version`. The confirmation is permitted only when the request is `ASSIGNED`, the assigned bed is still `CLEAN`, the `expected_bed_version` equals the assigned bed's current `version`, and the encounter for this request is either `BOARDING` or an `ADMIT_PENDING` non-ED patient. On success the request advances `ASSIGNED → CONFIRMED`; the assigned bed flips to `OCCUPIED` and its `version` increments by 1; the encounter moves to `PLACED`; and a placement ADT event is appended. As described in Section 2.10, a mismatch between `expected_bed_version` and the bed's live `version` is rejected with `ERR_STALE_BED_VERSION` (HTTP 412), the precise guard against confirming a bed that another request has already taken.

The placement that confirmation drives lands differently depending on where the patient was. For a `BOARDING` ED patient, `boarding_hours` is frozen at the difference between the current clock and `admit_decision_at`, `boarding_breached` is recomputed, `current_bed_id` is set to the assigned bed, the bed goes `OCCUPIED`, and `admitted_at` is stamped with the current clock as the patient's first placement. For a direct or transfer-in patient confirmed straight from `ADMIT_PENDING`, the encounter moves `ADMIT_PENDING → PLACED` with `current_bed_id` set, the bed taken `OCCUPIED`, and `admitted_at` stamped at first placement. In both cases the placement is allowed only when the assigned bed is `CLEAN` and clears the isolation, telemetry, and cohort checks, and a placement ADT event records the move.

### 3.6. Moving and Discharging Patients

Once `PLACED`, a patient can be transferred to a different bed by a `BedControlCoordinator`, who supplies the `target_bed_id`. A transfer is a self-loop that keeps the encounter `PLACED` while swapping beds. It is allowed only when the encounter is `PLACED`, the target bed is `CLEAN` and clears the isolation, telemetry, and cohort checks, and the target bed differs from the patient's current bed; a transfer onto the same bed is rejected with `ERR_SAME_BED` (HTTP 409). The four bed-eligibility safety checks of Section 2.11 (isolation, then telemetry, then cohort, then availability) are evaluated before this same-bed check, so the same-bed condition is reached only on a target bed that has already passed the availability check (i.e. is `CLEAN`). Because a `PLACED` patient's own current bed is necessarily `OCCUPIED`, a transfer naming that current bed as the target fails the availability check first and is rejected with `ERR_BED_NOT_AVAILABLE` (HTTP 409); `ERR_SAME_BED` is therefore returned only if the target equals the current bed while that bed is itself `CLEAN`. On a valid transfer the system records `transferred_from_bed_id` as the patient's current bed, returns that old bed to `DIRTY` (auto-creating a turnover task for it), sets `current_bed_id` to the target bed and takes that target `OCCUPIED`, leaves `admitted_at` unchanged so the length-of-stay clock runs continuously across the move, and appends a transfer ADT event.

Discharge is a two-step protocol with a safety gate. A `CaseManager` or `BedControlCoordinator` first orders discharge on a `PLACED` patient, advancing `PLACED → DISCHARGE_ORDERED`, stamping `discharge_order_at` with the current clock, and appending a discharge-order ADT event. A discharge order can be rescinded — the `DISCHARGE_ORDERED → PLACED` revert clears `discharge_order_at` back to null while the patient is still in the bed. The actual discharge is permitted only from `DISCHARGE_ORDERED` and only when the encounter has zero `OPEN` discharge barriers; a discharge attempted while any barrier remains open is rejected with `ERR_OPEN_BARRIERS` (HTTP 409). A successful discharge stamps `discharged_at`, freezes `length_of_stay_hours`, returns the bed to `DIRTY` (auto-creating a turnover task), clears `current_bed_id` to null, and appends a discharge ADT event.

Encounters that have not yet been placed can be cancelled. A `BedControlCoordinator` or `FlowAdmin` may cancel an encounter that is `REGISTERED`, `ADMIT_PENDING`, or `BOARDING`, moving it to `CANCELLED` and appending a cancel ADT event. When the cancelled encounter was `ADMIT_PENDING` or `BOARDING`, any open bed request for that encounter (in `QUEUED` or `ASSIGNED`) is also moved to `CANCELLED` so no stale reservation lingers.

### 3.7. Length of Stay, Long-Stay Flagging, and Discharge Delay

Length of stay is anchored at first placement. While a patient is admitted and not yet discharged, `length_of_stay_hours` is the difference between the current clock and `admitted_at`, expressed in hours and rounded half-up to two decimal places; once the patient is `DISCHARGED` it is the difference between `discharged_at` and `admitted_at`, frozen. When `admitted_at` is still null, `length_of_stay_hours` is `0.00`. A `long_stay_flag` is raised when the patient has actually been admitted (`admitted_at` is not null) and `length_of_stay_hours` has reached the unit's long-stay threshold, computed as the placement unit's `gmlos_days` multiplied by 24 and then by 1.5; the comparison is inclusive, so a stay equal to that threshold sets the flag. The `gmlos_days` used is that of the unit owning the patient's current bed, or the last bed occupied if the patient has been discharged.

Discharge delay measures the gap between ordering discharge and actually completing it. For an encounter that is `DISCHARGE_ORDERED` or `DISCHARGED` and has a `discharge_order_at`, the discharge-delay hours equal the difference between the end point — `discharged_at` if discharged, otherwise the current clock — and `discharge_order_at`, in hours rounded half-up to two decimal places; if there is no `discharge_order_at`, the delay is `0.00`. The number of avoidable bed-days is the discharge-delay hours divided by 24 and rounded down to a whole number (floor). These figures surface the operational cost of barriers that keep a ready patient occupying a bed.

### 3.8. Discharge Barriers

Barriers are the named obstacles that keep a medically-ready patient in a bed. A `CaseManager` or `BedControlCoordinator` opens a barrier against an encounter, supplying the `encounter_id`, a `barrier_type` (one of `PLACEMENT_SNF`, `TRANSPORT`, `PHARMACY`, `FAMILY`, or `EQUIPMENT`), and an optional free-text `note`. A new barrier enters `OPEN`, stamps `opened_at`, and increments the encounter's `open_barrier_count`. A `CaseManager` or `FlowAdmin` resolves an `OPEN` barrier, advancing it `OPEN → RESOLVED`, stamping `resolved_at`, and decrementing the encounter's `open_barrier_count`. Because discharge requires `open_barrier_count` to be zero, the resolve action is what ultimately clears the path to discharge.

### 3.9. EVS Turnover Tasks and Priority Scoring

Turnover tasks are created either automatically (when a bed becomes `DIRTY` on departure, as described above) or explicitly by a `ChargeNurse`, `BedControlCoordinator`, or `EvsTech`, who name the `bed_id` and an optional `task_type` of `STAT`, `ISOLATION`, or `ROUTINE` (defaulting to `ROUTINE`). A manually created task is allowed only when the target bed is `DIRTY` at creation time — otherwise the request is rejected with `ERR_BED_NOT_DIRTY` (HTTP 409) — and a bed may carry at most one non-terminal task (in `REQUESTED`, `ASSIGNED`, or `IN_PROGRESS`); a second one is rejected with `ERR_EVS_TASK_EXISTS` (HTTP 409). A new task enters `REQUESTED`, stamps `requested_at`, and computes its initial `priority_score`.

The task then moves linearly. An `EvsTech` (or a `FlowAdmin` acting on their behalf with an optional `tech_id`) assigns the task `REQUESTED → ASSIGNED`, writing `assigned_tech_id`. The `EvsTech` starts it `ASSIGNED → IN_PROGRESS`, then completes it `IN_PROGRESS → COMPLETED`, which is permitted only when the target bed is `DIRTY`; completion drives that bed `DIRTY → CLEAN` (preserving `sex_cohort`, as routine turnover does) and recomputes the unit's `clean_available_count` and posture. A task can also be cancelled: from `REQUESTED` or `ASSIGNED` it may be cancelled by an `EvsTech`, `ChargeNurse`, or `FlowAdmin` (and the system itself cancels such tasks when their bed is blocked or retired), while an `IN_PROGRESS` task may be cancelled by a `ChargeNurse` or `FlowAdmin`.

A task's `priority_score` is recomputed on every read — both when fetching a single task and when listing tasks — against the current clock and the posture of the bed's unit. The score is the sum of three parts. The base comes from `task_type`: 100 for `STAT`, 70 for `ISOLATION`, 40 for `ROUTINE`. A surge component is added from the bed's unit `effective_posture`: 30 for `RED`, 15 for `YELLOW`, and 0 for `GREEN` or `CLOSED`. An aging component rewards waiting: the wait in minutes is the difference between the current clock and `requested_at` rounded down to whole minutes, that wait is divided by 30 and rounded down to a whole number of completed 30-minute windows, and each completed window adds 5. The three parts sum to the final integer `priority_score`. The task list endpoint orders results by `priority_score` descending and then by `requested_at` ascending, never by `id`; a `bed_id` and a `status` filter narrow the list.

### 3.10. Capacity Surveillance, Surge, and Operations Runs

House-wide situational awareness is captured by capacity huddles. A `BedControlCoordinator` or `FlowAdmin` snapshots the whole house at the current clock, and the snapshot stamps `huddle_at` and freezes a set of aggregates: `total_staffed_beds` is the sum of every unit's `staffed_bed_count`; `total_occupied_beds` is the sum of every unit's `occupied_bed_count`; `house_occupancy_pct` is the total occupied divided by total staffed, times 100, rounded half-up to two decimal places, and `0.00` when there are no staffed beds; `boarding_encounter_count` is the number of encounters in `BOARDING`; `queued_request_count` is the number of bed requests in `QUEUED`; and `red_unit_count` is the number of units whose `effective_posture` is `RED`. These numbers are computed once at huddle time and never change afterward.

Surge declarations let leadership override a unit's derived posture upward. A `BedControlCoordinator` or `FlowAdmin` declares a surge on a unit, supplying the `unit_id`, a `level` of `YELLOW` or `RED`, and an optional `reason`. The surge enters `OPEN`, stamps `opened_at`, and the unit's `declared_surge_level` and `effective_posture` are recomputed to reflect it. Standing a surge down advances it `OPEN → STOOD_DOWN`, stamps `stood_down_at`, and recomputes the unit's `declared_surge_level` and `effective_posture`, which drop back if no other surge remains open. Because the posture machinery takes the more severe of derived and declared, an open `RED` surge holds a quiet unit at `RED` regardless of its occupancy.

Finally, two administrative capabilities drive time and the queue. An operations run advances a global operations counter by 1 and then sweeps the bed-request queue for expiry, returning the new `ops_run_index` along with the list of `expired_request_ids` it just moved to `EXPIRED`; a `FlowAdmin` or `BedControlCoordinator` may trigger it. A separate test-driving capability lets a `FlowAdmin` set the simulated UTC clock to a supplied `to_iso8601` instant, returning the new `current_utc`; this is what advances length-of-stay, boarding, EVS aging, and discharge-delay computations across the system. Listing endpoints throughout the system accept the standard `limit` and `offset` and, where noted, narrow by `encounter_id`, `preferred_unit_id`, `unit_id`, `bed_id`, or `status`; the ADT event listing for an encounter exposes each event's `encounter_id`, `event_type` (`ADMIT`, `PLACE`, `TRANSFER`, `DISCHARGE_ORDER`, `DISCHARGE`, or `CANCEL`), its `from_bed_id` and `to_bed_id` snapshot pointers, and its `event_at` timestamp.

## 4. Endpoint Definitions

All endpoints share the envelope of Section 2.2. Creation endpoints return HTTP 201 with the newly created resource; reads, lists, and state-changing actions on existing resources return HTTP 200 with the affected resource (or, for operations and clock control, the documented small result object). Authentication, authorization, existence, and validation failures use the status codes of Section 5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/units` | Create a nursing unit | FlowAdmin |
| GET | `/units/{id}` | Get a unit with recomputed occupancy and posture | FlowAdmin, BedControlCoordinator, ChargeNurse, TransferCenterAgent, CaseManager, EvsTech |
| GET | `/units` | List units (paginated) | FlowAdmin, BedControlCoordinator, ChargeNurse, TransferCenterAgent, CaseManager, EvsTech |
| POST | `/units/{id}/beds` | Add a bed to a unit (starts DIRTY) | FlowAdmin, ChargeNurse |
| GET | `/units/{id}/beds/{bedId}` | Get a bed | FlowAdmin, BedControlCoordinator, ChargeNurse, TransferCenterAgent, EvsTech |
| GET | `/units/{id}/beds` | List beds in a unit (paginated, optional status filter) | FlowAdmin, BedControlCoordinator, ChargeNurse, TransferCenterAgent, EvsTech |
| POST | `/units/{id}/beds/{bedId}/mark-clean` | Mark a DIRTY bed CLEAN directly | ChargeNurse, EvsTech |
| POST | `/units/{id}/beds/{bedId}/block` | Block a CLEAN or DIRTY bed | ChargeNurse, FlowAdmin |
| POST | `/units/{id}/beds/{bedId}/unblock` | Unblock a BLOCKED bed (returns to DIRTY) | ChargeNurse, FlowAdmin |
| POST | `/units/{id}/beds/{bedId}/retire` | Retire a BLOCKED bed permanently | FlowAdmin |
| POST | `/encounters` | Register a new patient encounter | BedControlCoordinator, TransferCenterAgent, FlowAdmin |
| GET | `/encounters/{encounterId}` | Get an encounter with recomputed LOS, boarding, barrier count | FlowAdmin, BedControlCoordinator, ChargeNurse, TransferCenterAgent, CaseManager |
| GET | `/encounters` | List encounters (paginated, optional status filter) | FlowAdmin, BedControlCoordinator, ChargeNurse, TransferCenterAgent, CaseManager |
| POST | `/encounters/{encounterId}/admit-order` | Place admit order (ED auto-advances to BOARDING) | BedControlCoordinator, FlowAdmin |
| POST | `/encounters/{encounterId}/start-boarding` | Manually move ADMIT_PENDING ED encounter to BOARDING | BedControlCoordinator |
| POST | `/encounters/{encounterId}/transfer` | Transfer a PLACED patient to a different CLEAN bed | BedControlCoordinator |
| POST | `/encounters/{encounterId}/discharge-order` | Order discharge (PLACED to DISCHARGE_ORDERED) | CaseManager, BedControlCoordinator |
| POST | `/encounters/{encounterId}/rescind-discharge` | Rescind a discharge order | CaseManager, BedControlCoordinator |
| POST | `/encounters/{encounterId}/discharge` | Discharge a patient if no open barriers | CaseManager, BedControlCoordinator |
| POST | `/encounters/{encounterId}/cancel` | Cancel a not-yet-placed encounter | BedControlCoordinator, FlowAdmin |
| GET | `/encounters/{id}/adt-events` | List ADT events for an encounter | FlowAdmin, BedControlCoordinator, CaseManager |
| POST | `/bed-requests` | Create a placement request (enters QUEUED) | TransferCenterAgent, BedControlCoordinator |
| GET | `/bed-requests/{bedRequestId}` | Get a bed request | FlowAdmin, BedControlCoordinator, TransferCenterAgent |
| GET | `/bed-requests` | List bed requests (paginated) | FlowAdmin, BedControlCoordinator, TransferCenterAgent |
| POST | `/bed-requests/{bedRequestId}/auto-place` | Server selects the best eligible CLEAN bed and assigns it | BedControlCoordinator, TransferCenterAgent |
| POST | `/bed-requests/{bedRequestId}/assign` | Manually assign a specific bed to a queued request | BedControlCoordinator |
| POST | `/bed-requests/{bedRequestId}/confirm` | Confirm an assigned bed, placing the patient (OCC-guarded) | BedControlCoordinator, TransferCenterAgent |
| POST | `/bed-requests/{bedRequestId}/release` | Release an assignment back to the queue | BedControlCoordinator, TransferCenterAgent |
| POST | `/bed-requests/{bedRequestId}/cancel` | Cancel a bed request | BedControlCoordinator, TransferCenterAgent |
| POST | `/evs-tasks` | Create an EVS turnover task for a DIRTY bed | ChargeNurse, BedControlCoordinator, EvsTech |
| GET | `/evs-tasks/{evsTaskId}` | Get an EVS task with recomputed priority_score | FlowAdmin, EvsTech, ChargeNurse, BedControlCoordinator |
| GET | `/evs-tasks` | List EVS tasks ordered by priority_score DESC then requested_at ASC | FlowAdmin, EvsTech, ChargeNurse, BedControlCoordinator |
| POST | `/evs-tasks/{evsTaskId}/assign` | Assign a tech to a requested task | EvsTech, FlowAdmin |
| POST | `/evs-tasks/{evsTaskId}/start` | Start cleaning (ASSIGNED to IN_PROGRESS) | EvsTech |
| POST | `/evs-tasks/{evsTaskId}/complete` | Complete cleaning (bed DIRTY to CLEAN) | EvsTech |
| POST | `/evs-tasks/{evsTaskId}/cancel` | Cancel an EVS task | EvsTech, ChargeNurse, FlowAdmin |
| POST | `/discharge-barriers` | Open a discharge barrier on an encounter | CaseManager, BedControlCoordinator |
| GET | `/discharge-barriers/{barrierId}` | Get a discharge barrier | FlowAdmin, CaseManager, BedControlCoordinator |
| GET | `/discharge-barriers` | List discharge barriers (paginated) | FlowAdmin, CaseManager, BedControlCoordinator |
| POST | `/discharge-barriers/{barrierId}/resolve` | Resolve an open barrier (OPEN to RESOLVED) | CaseManager, FlowAdmin |
| POST | `/surge-events` | Declare a surge on a unit | BedControlCoordinator, FlowAdmin |
| GET | `/surge-events/{surgeEventId}` | Get a surge event | FlowAdmin, BedControlCoordinator |
| GET | `/surge-events` | List surge events (paginated) | FlowAdmin, BedControlCoordinator |
| POST | `/surge-events/{surgeEventId}/stand-down` | Stand down a surge (OPEN to STOOD_DOWN) | BedControlCoordinator, FlowAdmin |
| POST | `/capacity-huddles` | Snapshot house-wide capacity at the current clock | BedControlCoordinator, FlowAdmin |
| GET | `/capacity-huddles/{huddleId}` | Get a capacity huddle snapshot | FlowAdmin, BedControlCoordinator |
| GET | `/capacity-huddles` | List capacity huddles (paginated) | FlowAdmin, BedControlCoordinator |
| POST | `/ops/run` | Advance the ops run index and run the queued-request expiry sweep | FlowAdmin, BedControlCoordinator |
| POST | `/_clock/set` | Test-driving: set the server's simulated current UTC clock | FlowAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_PAGINATION | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_ISOLATION_REQUIRED | 409 |
| ERR_TELEMETRY_REQUIRED | 409 |
| ERR_COHORT_CONFLICT | 409 |
| ERR_BED_NOT_AVAILABLE | 409 |
| ERR_SAME_BED | 409 |
| ERR_OPEN_BARRIERS | 409 |
| ERR_NO_ELIGIBLE_BED | 409 |
| ERR_BED_NOT_DIRTY | 409 |
| ERR_EVS_TASK_EXISTS | 409 |
| ERR_BED_OCCUPIED | 409 |
| ERR_STALE_BED_VERSION | 412 |
