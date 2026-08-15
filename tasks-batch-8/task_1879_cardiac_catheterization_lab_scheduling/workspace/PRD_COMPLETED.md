# Cardiac Cath Lab API — Product Requirements Document

## 1. Introduction

A cardiac catheterization laboratory is one of the most contended resources in a hospital. Elective and urgent cases are posted against a handful of procedure rooms, each with its own installed equipment; every case consumes contrast dye and ionizing radiation that must be tracked against per-patient safety ceilings; implantable devices — stents, pacemaker and ICD leads, closure devices — sit on the shelf under a mix of owned and consigned inventory; and every completed procedure owes a data submission to the national cardiovascular registries on a strict deadline. Threaded through all of this is the STEMI activation: when a heart-attack patient arrives, the lab must absorb an emergency case immediately, displacing whatever elective work stands in its way without losing track of the beds, staff, and reserved devices those displaced cases were holding.

This document specifies the API that runs that operation. It governs case posting and scheduling, STEMI bumping with its full cascade of releases, room and staff assignment under conflicting calendar constraints, device-lot reservation and implantation, intra-procedure dose recording with hard contrast limits and a latching radiation alert, recovery-bed commitment and release, appropriate-use-criteria documentation under segregation of duties, and the registry submission lifecycle from draft through acceptance or rejection-driven revision. All endpoints are mounted under `/cath-lab`. Five segregated roles share the workload, and a server-side logical clock — not wall-clock time — drives every timestamp and deadline.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request that is missing either header, or carries a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Five roles are recognized, spelled exactly as follows: `CathLabScheduler`, `InterventionalCardiologist`, `CathLabTechnologist`, `RecoveryNurseManager`, and `RegistryCoordinator`. Each operation in §4 names the roles permitted to invoke it; a request whose role is not among them is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The meaning of `X-User-ID` depends on the declared role. When `X-User-Role` is `InterventionalCardiologist`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a staff member — a case's `performing_physician_id`, an attestation's `ordering_physician_id` — compare that foreign-key field to `X-User-ID`. The same holds when `X-User-Role` is `CathLabTechnologist`: `X-User-ID` is the `id` of the acting `StaffMember`. When `X-User-Role` is `CathLabScheduler`, `RecoveryNurseManager`, or `RegistryCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items are skipped and defaults to 0. A `limit` that is not a whole number or falls outside 1 to 100, and an `offset` that is not a whole number or is negative, are rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`. Here `total_count` is the number of resources matching the request's filters before pagination is applied, and `has_more` is true exactly when `offset + limit` is below `total_count`. Filter query parameters match exactly; a filter value that matches no resource simply yields an empty page.

### 2.4. Common Resource Properties

All nine resource types in this system — cath lab rooms, staff members, cases, staff assignments, device lots, device usages, dose records, recovery beds, and registry submissions — share one set of system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments with every modification of the resource, including modifications performed automatically by reconciliation cascades. Every resource is created with `version` at 1. This field underpins the optimistic concurrency control of §2.7.

### 2.5. The Logical Clock

The server keeps a logical clock and never consults wall-clock time. At startup the clock reads exactly 2026-08-01T00:00:00Z; until a client explicitly sets it, every read of the clock returns that instant. Every timestamp the server stamps — a case's `actual_start` and `actual_end`, a submission's `submitted_at` and `decided_at` — is taken from this clock, and every date-sensitive check, including device-lot expiry and the registry submission window, is evaluated against it. A `CathLabScheduler` sets the clock through the test-driving capability at `POST /cath-lab/_clock/set_current_utc`, passing the target instant as `to_iso8601`; the response carries the new reading as `current_utc`. Because the clock may stay frozen across many writes, `created_at` and `updated_at` stamps are drawn from a monotonic tick derived from the logical clock: whenever the clock has not advanced past the previous stamp, the tick moves one millisecond beyond it, so `created_at` ordering always matches creation order even while the clock is frozen.

### 2.6. Precision, Rounding, and Time Arithmetic

Numeric precision is pinned per quantity family so that independent implementations agree bit-for-bit. Contrast volumes — the per-patient `contrast_limit_ml`, each entry's `contrast_ml`, and the case's `cumulative_contrast_ml` — are carried at one decimal place, rounded half-up. Radiation accounting rounds per record before summing: each `record_total_mgy` is the entry's fluoroscopy and cine components added together and rounded half-up to two decimal places, and only those rounded per-record totals are summed into `cumulative_radiation_mgy`; summing raw components and rounding once at the end is a forbidden alternative order (§3.6 gives the worked divergence). Registry `completeness_pct` is a percentage rounded half-up to one decimal place. Case windows are computed in whole minutes, and all datetimes are handled at second resolution. Incoming datetime strings may carry any ISO 8601 offset — or none at all, in which case they are read as UTC — and are normalized to UTC. Device stock figures — `quantity_on_hand`, `allocated_units`, `available_units`, `reorder_threshold`, and usage `quantity` — are whole units.

### 2.7. Optimistic Concurrency Control

Two writes are version-gated, and no other endpoint takes a version field.

Recording an AUC attestation (the `POST /cath-lab/cases/{id}/auc-attestation` endpoint) requires the request to carry `expected_case_version`, holding the case `version` the client last observed. An attestation legitimately overwrites the case's current AUC documentation, so a request whose `expected_case_version` no longer matches the case's current `version` — because an earlier attestation, a scheduling action, or a dose-recording side effect has advanced it in the meantime — is operating on a stale view and must be refused. The rejection carries `ERR_STALE_CASE_VERSION` and HTTP status 412.

Restocking a device lot (the `POST /cath-lab/device-lots/{id}/restock` endpoint) requires the request to carry `expected_lot_version`. A restock is valid from any lot state, so the version check is the only way to detect that the client's quantity basis is stale — for example after an intervening restock, or after an implant that decremented `quantity_on_hand`. A mismatch with the lot's current `version` is refused with `ERR_STALE_LOT_VERSION` and HTTP status 412.

### 2.8. Nested Paths and Resource Existence

Identifiers embedded in a request path are validated in a strict left-to-right order, and the request is rejected with the not-found error of the first identifier that fails to resolve: an unknown room yields `ERR_ROOM_NOT_FOUND`, a staff member `ERR_STAFF_NOT_FOUND`, a case `ERR_CASE_NOT_FOUND`, a device lot `ERR_LOT_NOT_FOUND`, a recovery bed `ERR_BED_NOT_FOUND`, a staff assignment `ERR_ASSIGNMENT_NOT_FOUND`, a device usage `ERR_USAGE_NOT_FOUND`, a dose record `ERR_DOSE_RECORD_NOT_FOUND`, and a registry submission `ERR_SUBMISSION_NOT_FOUND` — all HTTP 404. Foreign keys carried in request bodies receive the same treatment after the path identifiers pass: `lab_id`, `bed_id`, `staff_id`, `lot_id`, `performing_physician_id`, and `ordering_physician_id` each resolve against the corresponding resource and fail with that resource's not-found error. A foreign key whose value is not a string instead fails request-shape validation with `ERR_INVALID_REQUEST`. Existence always precedes any business rule.

### 2.9. Derived Statuses and Automatic Reconciliation

Several statuses are never set directly by clients; the server derives and maintains them. A device lot's `status` is fully derived from `available_units` against its `reorder_threshold` and is recomputed after every mutation that changes `quantity_on_hand` or `allocated_units` — lot creation, reservation, release, implantation, and restock (§3.5). A case's `radiation_alert` is derived from `cumulative_radiation_mgy` and, once raised, latches permanently: it never clears automatically, even when a later void pulls the cumulative figure back under the threshold (§3.6). When a single operation cascades into other resources — a STEMI bump releasing a bed, staff assignments, and device reservations, or a completion settling all three at once — each affected resource is reconciled independently, refreshing its own `updated_at` and incrementing its own `version`.

### 2.10. Validation Evaluation Order

Rejection checks run in a fixed priority order, so a request that would fail several checks always reports the earliest applicable one. First come the user-context headers of §2.1 (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization against §4 (`ERR_INSUFFICIENT_PERMISSIONS`), then existence of every path identifier — left to right — followed by body foreign keys (the nine not-found errors of §2.8). Fourth, on every mutating call, request shape is validated: a body that is not a valid JSON object fails outright, required fields present, types correct, enum values in domain, numeric ranges respected (`weight_kg` and `serum_creatinine` greater than zero, a reservation or restock `quantity` of at least one, stock counts and thresholds at zero or more), and the conditional requirements met — a STEMI posting carries `scheduled_start`, a contrast entry carries `contrast_ml`, a radiation entry carries `fluoroscopy_mgy` and `cine_mgy`, a rejection decision carries `rejection_reason`, and no status is set to the value it already holds. Shape failures are `ERR_INVALID_REQUEST`. Fields a request carries beyond those the operation defines are ignored. Fifth, state gates on the target and parent resources (`ERR_CASE_INVALID_STATE`, `ERR_USAGE_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_BED_INVALID_STATE`, `ERR_SUBMISSION_INVALID_STATE`, `ERR_DOSE_RECORD_ALREADY_VOIDED`). Sixth, clinical safety and compliance: the elective AUC gate, the attestation segregation of duties, the contrast ceiling, and registry completeness (`ERR_AUC_REQUIRED`, `ERR_AUC_ORDERING_CONFLICT`, `ERR_CONTRAST_LIMIT_EXCEEDED`, `ERR_SUBMISSION_INCOMPLETE`). Seventh, temporal conflicts and deadlines (`ERR_ROOM_WINDOW_CONFLICT`, `ERR_STAFF_WINDOW_CONFLICT`, `ERR_DEVICE_EXPIRED`, `ERR_SUBMISSION_WINDOW_EXPIRED`). Eighth, the state and consistency of referenced entities (`ERR_ROOM_NOT_ACTIVE`, `ERR_STAFF_INACTIVE`, `ERR_STAFF_ROLE_MISMATCH`, `ERR_NOT_PERFORMING_PHYSICIAN`, `ERR_STAFFING_INCOMPLETE`, `ERR_RESOURCE_IN_USE`, `ERR_EQUIPMENT_MISMATCH`, `ERR_DUPLICATE_SUBMISSION`). Ninth, capacity and selector fallbacks (`ERR_INSUFFICIENT_DEVICE_STOCK`, `ERR_NO_RECOVERY_BED`, `ERR_NO_STEMI_ROOM`). Tenth and last, the optimistic-concurrency version check (`ERR_STALE_CASE_VERSION`, `ERR_STALE_LOT_VERSION`), evaluated after existence and request shape and before the write is applied.

## 3. Business Logic & Workflows

### 3.1. Registering the Lab: Rooms, Staff, and Recovery Beds

Before any case can be posted, the lab's physical and human resources are registered. A `CathLabScheduler` registers each catheterization laboratory room with a human-readable `room_name` and an optional `equipment_profile` listing the equipment codes installed there. An equipment code is one of `BIPLANE_ANGIOGRAPHY`, `IVUS`, `OCT`, `FFR`, `ROTATIONAL_ATHERECTOMY`, `IABP`, or `MECHANICAL_SUPPORT`; when the profile is omitted it defaults to an empty list. New rooms come up `ACTIVE`. The scheduler can later take a room `OUT_OF_SERVICE` and return it to `ACTIVE`, but a room may only be taken out of service when no case assigned to it is currently `SCHEDULED` or `IN_PROGRESS` — otherwise the change is refused with `ERR_RESOURCE_IN_USE`. Asking for the status the room already has is not treated as a no-op; it is rejected with `ERR_INVALID_REQUEST`. The room list can be filtered by `status`.

Staff are registered with a `full_name`, a `staff_role` of `INTERVENTIONAL_CARDIOLOGIST`, `SCRUB_TECHNOLOGIST`, or `CIRCULATING_NURSE`, and an optional list of free-form `credentials` that defaults to empty. Every member carries an `is_active` flag — true unless the registration payload explicitly supplies `is_active` as false — which governs whether they may receive new case assignments. Activation and deactivation are scheduler operations on `is_active`; deactivation is refused with `ERR_RESOURCE_IN_USE` while the member still holds `ASSIGNED` assignments on cases that have not reached a terminal state. Setting `is_active` to the value the member already holds is a no-op: the member is returned unchanged and its `version` is not incremented. The staff directory can be filtered by `staff_role` or by `is_active` — the `is_active` filter accepts the strings `true` and `false`, case-insensitive — and a member's own assignment history is reachable through the member's assignment collection.

Recovery beds are registered by a `RecoveryNurseManager` with a human-readable `bed_label` and start life `AVAILABLE`. A free bed's `held_case_id`, `window_start`, and `window_end` are all null. The nurse manager can take a bed `OUT_OF_SERVICE` and bring it back to `AVAILABLE`, but only an `AVAILABLE` bed may be taken out of service — attempting it on a `RESERVED` or `OCCUPIED` bed is refused with `ERR_RESOURCE_IN_USE` — and setting the status the bed already holds is rejected with `ERR_INVALID_REQUEST`. The bed board can be filtered by `status`, or by `held_case_id` to find the bed committed to a particular case.

### 3.2. Posting a Case and the STEMI Activation Path

Posting a case captures the patient context: the `patient_mrn`, a `procedure_type` of `DIAGNOSTIC_CATHETERIZATION`, `PCI`, `STEMI_PCI`, `DEVICE_IMPLANT`, or `EP_STUDY`, a `priority` of `ELECTIVE`, `URGENT`, or `STEMI`, the `performing_physician_id`, the patient's `weight_kg`, and the `serum_creatinine`. Both clinical measurements must be greater than zero. The `equipment_needs` list — the equipment codes the case will require, drawn from the same code list as room equipment profiles — may be omitted and defaults to empty. The referenced performing physician must be a staff member whose `staff_role` is `INTERVENTIONAL_CARDIOLOGIST`; any other reference is rejected with `ERR_STAFF_ROLE_MISMATCH`. Either a `CathLabScheduler` or an `InterventionalCardiologist` may post a case. A new case begins with `cumulative_contrast_ml` and `cumulative_radiation_mgy` at zero, `radiation_alert` false, and `bump_count` at zero.

At posting time the server computes the patient's contrast ceiling and stores it as `contrast_limit_ml`. The raw allowance is five times the patient's weight in kilograms divided by the serum creatinine, and the ceiling is the lesser of that raw allowance and a hard cap of 300.0 mL, rounded half-up to one decimal place. A 60 kg patient with a creatinine of 1.5 mg/dL receives a ceiling of 200.0 mL; an 80 kg patient at 1.0 mg/dL would produce a raw allowance of 400 mL and is therefore capped at 300.0 mL.

What happens next depends entirely on `priority`. `ELECTIVE` and `URGENT` cases are created in `POSTED` status and wait for explicit scheduling (§3.3). A `STEMI` case is an activation: it bypasses the queue and is created directly in `SCHEDULED`.

A STEMI posting must carry `scheduled_start`; without it the request fails shape validation with `ERR_INVALID_REQUEST`. A `scheduled_start` supplied on an `ELECTIVE` or `URGENT` posting is validated as a datetime but otherwise ignored — the case is still created in `POSTED` with its schedule fields null. From that start the server derives the case window (below) and chooses a room through the STEMI room selector. A room is eligible only when it is `ACTIVE`, when every code in the case's `equipment_needs` appears in the room's `equipment_profile`, when no case on the room is `IN_PROGRESS`, and when no `SCHEDULED` case of `STEMI` or `URGENT` priority on the room has a buffered window that overlaps the STEMI window — overlap is judged with the buffered half-open room-window semantics of §3.3, against the STEMI window running from its `scheduled_start` through its scheduled end plus the twenty-minute turnover buffer. Among the eligible rooms the selector prefers the one where the fewest `SCHEDULED` `ELECTIVE` cases overlap the STEMI window — fewest victims first — and breaks ties by the room's `created_at` ascending, never by identifier. If no room qualifies, the activation fails outright with `ERR_NO_STEMI_ROOM` and no case is persisted.

The scheduled window of any case runs from `scheduled_start` to a computed `scheduled_end`: a base duration by procedure type — forty-five minutes for `DIAGNOSTIC_CATHETERIZATION`, ninety for `PCI`, seventy-five for `STEMI_PCI`, sixty for `DEVICE_IMPLANT`, and one hundred twenty for `EP_STUDY` — plus a setup allowance. The setup allowance is zero for a STEMI activation, the expedited branch; otherwise it is zero when the case lists no equipment, fifteen minutes when it lists one or two equipment codes, and thirty minutes when it lists three or more. On a STEMI activation the chosen room is written onto the new case as `lab_id`, along with the payload's `scheduled_start` and this computed `scheduled_end`. The activation also reserves a recovery bed through the bed selector (§3.3), moving the chosen bed `AVAILABLE` → `RESERVED` with a recovery window beginning at the STEMI case's `scheduled_end`. The room selector runs before the bed selector, and when no recovery bed is `AVAILABLE` the activation likewise fails outright with `ERR_NO_RECOVERY_BED`, again persisting no case.

Every overlapping `SCHEDULED` `ELECTIVE` case on the chosen room is then bumped. Each victim moves `SCHEDULED` → `BUMPED`, its `bump_count` rises by one, and its `lab_id`, `scheduled_start`, and `scheduled_end` are cleared to null — indeed, those three fields remain null on any case sitting in `POSTED`, `BUMPED`, or `CANCELLED`. The bump cascades further, and §3.3 through §3.5 cover each piece in detail: the victim's reserved recovery bed returns to `AVAILABLE` with `held_case_id` and both window fields cleared, every `ASSIGNED` staff assignment on the victim is `RELEASED`, and every `RESERVED` device usage is `RELEASED`, which in turn recomputes each affected lot's `allocated_units` and derived `status`.

The case list supports filtering by `status`, `priority`, `lab_id`, `performing_physician_id`, and `ordering_physician_id`, which is how the scheduler's board and the per-physician views are built.

### 3.3. Scheduling Cases and Securing Recovery Beds

A `CathLabScheduler` schedules a `POSTED` case — or reschedules a `BUMPED` one, and the two transitions share their rulebook entirely — by supplying the target `lab_id` and `scheduled_start`, with an optional `bed_id` pinning a specific recovery bed. Scheduling from any other case status is rejected with `ERR_CASE_INVALID_STATE`. In both directions the transition lands the case in `SCHEDULED` — `POSTED` → `SCHEDULED` for a first scheduling, `BUMPED` → `SCHEDULED` for a reschedule — and the cycle `SCHEDULED` → `BUMPED` → `SCHEDULED` is the normal recovery path after a STEMI activation.

For an `ELECTIVE` case, scheduling is gated on appropriate-use documentation: the case's `auc_status` must be `DOCUMENTED`, or the request is refused with `ERR_AUC_REQUIRED`. An attestation recorded before a bump survives it, so a rescheduled elective case does not need to be re-documented. `URGENT` and `STEMI` cases carry no such gate.

Two checks qualify the target room — under §2.10's fixed priority they run after the window-conflict check described in the next paragraph. The room must be `ACTIVE`; scheduling onto an `OUT_OF_SERVICE` room is rejected with `ERR_ROOM_NOT_ACTIVE`. And the case's `equipment_needs` must be a subset of the room's `equipment_profile`, failing which the request is refused with `ERR_EQUIPMENT_MISMATCH`.

The room's committed schedule then decides availability. The committed set is every case assigned to that room in `SCHEDULED` or `IN_PROGRESS`; cases in `POSTED`, `BUMPED`, `CANCELLED`, or `COMPLETED` do not block the room. Each committed case occupies a half-open interval from its `scheduled_start` through its `scheduled_end` plus a twenty-minute turnover buffer, and the incoming case occupies the same shape of interval, from its own start through its own end plus twenty minutes. A conflict exists when the incoming start is earlier than a committed case's buffered end and that committed case's start is earlier than the incoming case's buffered end; the rejection is `ERR_ROOM_WINDOW_CONFLICT`. Exact adjacency after the buffer is allowed — an incoming case starting precisely twenty minutes after a committed case's `scheduled_end` is not a conflict.

With the room cleared, the server stamps `lab_id` and `scheduled_start` from the payload and computes `scheduled_end` with the same base-plus-setup arithmetic as §3.2 — a rescheduled non-STEMI case takes the tiered branch based on its equipment count. Then a recovery bed is secured. When the payload names a `bed_id`, that bed must currently be `AVAILABLE`; otherwise the schedule fails with `ERR_BED_INVALID_STATE`. When no `bed_id` is given, the bed selector runs: only `AVAILABLE` beds are eligible — a bed holds at most one case at a time, so `RESERVED`, `OCCUPIED`, and `OUT_OF_SERVICE` beds are out — the earliest-created eligible bed wins, ties break by `bed_label` ascending, and an empty eligible set fails the whole scheduling request with `ERR_NO_RECOVERY_BED`. The secured bed moves `AVAILABLE` → `RESERVED`, records the case in `held_case_id`, and projects its recovery window with `window_start` at the case's `scheduled_end` and `window_end` ninety minutes later — the scheduled variant of the bed projection. A successful schedule or reschedule increments the case's `version` by one.

### 3.4. Staffing the Case

Once a case is `SCHEDULED`, the scheduler builds its team. Staffing is open only while the case is `SCHEDULED`; adding an assignment in any other case state is refused with `ERR_CASE_INVALID_STATE`. Each assignment names a `staff_id` and a `role_in_case` of `PRIMARY_OPERATOR`, `SCRUB`, or `CIRCULATOR`, and the role in the case must agree with the staff member's own `staff_role`: `PRIMARY_OPERATOR` requires an `INTERVENTIONAL_CARDIOLOGIST`, `SCRUB` requires a `SCRUB_TECHNOLOGIST`, and `CIRCULATOR` requires a `CIRCULATING_NURSE`. A mismatch is rejected with `ERR_STAFF_ROLE_MISMATCH`, and a member whose `is_active` flag is false is rejected with `ERR_STAFF_INACTIVE`.

A staff member cannot be in two rooms at once, and the staff-window rule is deliberately stricter than the room rule. The member's committed set is every `ASSIGNED` assignment of theirs whose case is `SCHEDULED` or `IN_PROGRESS`, each occupying the strict half-open interval from its `window_start` to its `window_end` with no turnover buffer at all. A new assignment conflicts when its start is earlier than a committed assignment's end and that committed assignment's start is earlier than the new one's end, and it is rejected with `ERR_STAFF_WINDOW_CONFLICT`. Exact adjacency — the new window starting precisely when a committed window ends — is allowed.

A created assignment records the staffed case as its `case_id`, copies its `window_start` and `window_end` from the case's `scheduled_start` and `scheduled_end` at that moment, and starts in `ASSIGNED`. The scheduler can release an assignment manually; releasing one that is not `ASSIGNED` is refused with `ERR_ASSIGNMENT_INVALID_STATE`. Assignments also release automatically when their case is bumped, cancelled, or completed. A case's team is listed through the case's assignment collection, and a staff member's commitments through the member's own assignment collection.

Staffing completeness is enforced at procedure start (§3.7): the case needs at least one `ASSIGNED` assignment with `role_in_case` `SCRUB` and at least one with `CIRCULATOR` before the cardiologist can begin.

### 3.5. Device Inventory: Lots, Reservation, and Implantation

A `CathLabTechnologist` registers each device or implant lot with its `device_type` — one of `STENT_DES`, `STENT_BMS`, `PACEMAKER_LEAD`, `ICD_LEAD`, or `CLOSURE_DEVICE` — plus the `manufacturer`, `model_number`, and `lot_number`, an `ownership` of `OWNED` or `CONSIGNMENT` (consigned stock is tracked exactly like owned stock for scheduling purposes), the physical `quantity_on_hand` (zero or more), a `reorder_threshold` (zero or more), and an `expiration_date`. The lot list can be filtered by `device_type`, `status`, or `ownership`.

Two counters govern a lot. `allocated_units` is the sum of `quantity` over that lot's device usages in `RESERVED` status — `IMPLANTED` and `RELEASED` usages do not count — and `available_units` is `quantity_on_hand` minus `allocated_units`. The lot's `status` is fully derived from those figures after every mutation that touches either counter — creation, reservation, release, implantation, restock: `DEPLETED` when nothing is available; otherwise `LOW_STOCK` when the available figure is below the `reorder_threshold`; otherwise `ACTIVE`. The boundary belongs to `ACTIVE` — availability exactly equal to the reorder threshold is healthy. Note also that a lot carries two readings: the scheduling view, `available_units`, subtracts reservations and drives both reservation validation and status derivation, while the physical view, `quantity_on_hand`, does not subtract them and is what consignment and shelf reconciliation read. The two diverge whenever any usage of the lot is `RESERVED`.

Reserving device units against a case requires the case to be `SCHEDULED` or `IN_PROGRESS` — any other case state is `ERR_CASE_INVALID_STATE` — and the payload names the `lot_id` to draw from and a `quantity` of at least one. Two further guards apply. When the current logical date falls strictly after the lot's `expiration_date`, the reservation fails with `ERR_DEVICE_EXPIRED`; on the expiration date itself the lot remains reservable. And the lot's `available_units` must cover the request — a request equal to the available figure is allowed, while anything larger is refused with `ERR_INSUFFICIENT_DEVICE_STOCK`. A successful reservation creates the usage in `RESERVED`, recorded against its case as `case_id`, raises the lot's `allocated_units` by the reserved `quantity`, and recomputes the derived status. Usages are listed per case, or per lot through the lot's usage collection.

Marking reserved units as implanted is restricted to a case `IN_PROGRESS` (anything else is `ERR_CASE_INVALID_STATE`) and to a usage still `RESERVED` (else `ERR_USAGE_INVALID_STATE`). Implantation consumes physical stock: the usage moves `RESERVED` → `IMPLANTED`, and the lot's `quantity_on_hand` and `allocated_units` both fall by the implanted `quantity`, with the derived status recomputed. Releasing a reservation — manually by the technologist, or automatically when the case is bumped, cancelled, or completed — returns the units to the available pool: the usage moves `RESERVED` → `RELEASED`, `allocated_units` falls by the released `quantity`, `quantity_on_hand` is untouched, and the status recomputes. Releasing a usage that is not `RESERVED` is likewise `ERR_USAGE_INVALID_STATE`.

Restocking adds `quantity` units to `quantity_on_hand`, increments the lot's `version` by one, and recomputes the derived status; it is valid from any lot state. Because of that latitude, the restock write is version-gated per §2.7: the request must carry `expected_lot_version` equal to the lot's current `version`, and a mismatch is refused with `ERR_STALE_LOT_VERSION`.

### 3.6. Recording Contrast and Radiation During the Procedure

While a case is `IN_PROGRESS`, a `CathLabTechnologist` records dose entries against it; adding an entry in any other case state is refused with `ERR_CASE_INVALID_STATE`. Each entry carries a `record_type` of `CONTRAST` or `RADIATION`. A contrast entry requires `contrast_ml`, zero or more; a radiation entry requires `fluoroscopy_mgy` and `cine_mgy`, each zero or more. Omitting the fields the chosen type requires — or supplying them out of place — fails shape validation with `ERR_INVALID_REQUEST`. Every entry is created `ACTIVE`, is recorded against its case as `case_id`, and each creation advances the case's `version` by one. A case's entries can be listed and filtered by `record_type` or `status`.

Contrast is guarded entry by entry against the case's `contrast_limit_ml`. The projected total — the case's current `cumulative_contrast_ml` plus the new entry's `contrast_ml` — may not exceed the ceiling: a projection strictly above the limit is rejected with `ERR_CONTRAST_LIMIT_EXCEEDED`, while a projection landing exactly on the limit is allowed. Accepted entries raise `cumulative_contrast_ml`, the running sum over the case's `ACTIVE` contrast entries.

Radiation accounting pins its rounding order. Each radiation entry first computes its own `record_total_mgy`: the `fluoroscopy_mgy` and `cine_mgy` components added together, then rounded half-up to two decimal places. The case's `cumulative_radiation_mgy` is the sum of those per-record rounded totals over its non-voided radiation entries. Rounding must happen per record, before summing; summing the raw components and rounding once at the end is forbidden, because the orders genuinely diverge — two entries each recording 1.005 mGy of fluoroscopy and no cine yield 2.02 mGy under the pinned order (1.01 plus 1.01) but 2.01 mGy under the forbidden one. A contrast entry's `record_total_mgy` is always 0. When the cumulative figure reaches 5,000.0 mGy — equality triggers — the case's `radiation_alert` flag is set true, and it latches: once raised, it never clears automatically.

Voiding is the compensating action for a bad entry. It requires the parent case `IN_PROGRESS` — otherwise `ERR_CASE_INVALID_STATE` — and the entry still `ACTIVE`; voiding an already-`VOIDED` record is refused with `ERR_DOSE_RECORD_ALREADY_VOIDED`. The entry moves `ACTIVE` → `VOIDED`, and both cumulative totals are recomputed over the remaining `ACTIVE` entries, advancing the case's `version` by one exactly as an entry creation does. Even if the recomputed radiation total drops back below 5,000.0 mGy, a latched `radiation_alert` stays set.

### 3.7. Starting, Completing, and Cancelling Cases

The performing cardiologist starts the case, and no one else can: the acting `X-User-ID` must equal the case's `performing_physician_id`, otherwise the start is refused with `ERR_NOT_PERFORMING_PHYSICIAN`. Two further gates apply — the assigned room must still be `ACTIVE` (`ERR_ROOM_NOT_ACTIVE`), and staffing must be complete, meaning at least one `ASSIGNED` assignment with `role_in_case` `SCRUB` and at least one `ASSIGNED` assignment with `CIRCULATOR` (`ERR_STAFFING_INCOMPLETE`). Starting from any status other than `SCHEDULED` is `ERR_CASE_INVALID_STATE`. A successful start moves the case `SCHEDULED` → `IN_PROGRESS`, stamps `actual_start` from the logical clock — it stays null until this moment — and increments the case `version` by one.

Completion is likewise the performing cardiologist's call, with the same identity check and the same `ERR_NOT_PERFORMING_PHYSICIAN` rejection, and is valid only from `IN_PROGRESS`. Completing moves the case to `COMPLETED`, stamps `actual_end` from the logical clock — null until now — and settles everything the case was holding. The recovery bed committed to the case moves `RESERVED` → `OCCUPIED`, and its window is recomputed from the actual finish: `window_start` becomes the case's `actual_end` and `window_end` ninety minutes after it. This is the actual variant of the bed projection, and it differs from the scheduled variant of §3.3 whenever the case finished earlier or later than its `scheduled_end`. Every still-`ASSIGNED` staff assignment of the case is `RELEASED`, and every still-`RESERVED` device usage is `RELEASED`, recomputing each affected lot's `allocated_units` and derived `status`.

A scheduler can cancel a case from `POSTED`, `SCHEDULED`, or `BUMPED`, moving it to `CANCELLED`; attempts from `IN_PROGRESS`, `COMPLETED`, or an already-`CANCELLED` case are refused with `ERR_CASE_INVALID_STATE`. Cancelling a `SCHEDULED` case unwinds its commitments exactly as a bump does: the reserved bed returns to `AVAILABLE` with `held_case_id` and both window fields cleared, its `ASSIGNED` assignments are released, and its `RESERVED` device usages are released with lot recomputation. Cancelling a `POSTED` or `BUMPED` case has no such cascade — a bumped case already surrendered its bed, staff, and device reservations at bump time.

A `RESERVED` bed frees itself automatically when its case is bumped or cancelled; an `OCCUPIED` bed is freed explicitly by a `RecoveryNurseManager` once the patient leaves recovery. Releasing a bed that is not `OCCUPIED` is refused with `ERR_BED_INVALID_STATE`; a valid release returns the bed `OCCUPIED` → `AVAILABLE` and clears `held_case_id`, `window_start`, and `window_end` to null. In every variant the committed recovery window is ninety minutes long, anchored at the case's `scheduled_end` while the bed is merely reserved and re-anchored at `actual_end` upon occupation.

### 3.8. Appropriate-Use Criteria Documentation

Appropriate-use criteria are documented against a case by an `InterventionalCardiologist` through the AUC attestation. The attestation imposes no case-state gate — it may be recorded against a case in any status. The payload carries the `ordering_physician_id`, an `auc_score` of `APPROPRIATE`, `MAY_BE_APPROPRIATE`, or `RARELY_APPROPRIATE`, and a `criterion_code` identifying the criterion applied. Recording the attestation sets the case's `auc_status` to `DOCUMENTED` — every case begins `NOT_DOCUMENTED`, with `auc_score`, `auc_criterion_code`, and `ordering_physician_id` null until then — and stores the score, the criterion code as `auc_criterion_code`, and the ordering physician on the case. A later attestation overwrites an earlier one wholesale, and each attestation increments the case `version` by one.

Segregation of duties is enforced in two directions, both under `ERR_AUC_ORDERING_CONFLICT`: the `ordering_physician_id` must differ from the case's `performing_physician_id` — no physician may attest as the ordering physician on their own case — and the acting `X-User-ID` must equal the `ordering_physician_id` being recorded.

Because an attestation legitimately overwrites prior documentation, the write is version-gated per §2.7: the payload must carry `expected_case_version` equal to the case's current `version`, and a stale value is refused with `ERR_STALE_CASE_VERSION` rather than silently overwriting documentation the caller never observed. The attestation is what unblocks elective scheduling — the `ERR_AUC_REQUIRED` gate of §3.3 — and it feeds registry completeness for elective cases (§3.9).

### 3.9. Registry Submission and the Revision Cycle

Once a case is `COMPLETED`, a `RegistryCoordinator` opens its registry submission; opening one for a case in any other state is refused with `ERR_CASE_INVALID_STATE`, and a case admits at most one submission — a second attempt is `ERR_DUPLICATE_SUBMISSION`. The submission's `registry_name` is derived from the case's `procedure_type`: `NCDR_CATHPCI` for `DIAGNOSTIC_CATHETERIZATION`, `PCI`, and `STEMI_PCI`; `NCDR_ICD` for `DEVICE_IMPLANT`; and `NCDR_EP` for `EP_STUDY`. The submission opens in `DRAFT`, recorded against its case as `case_id`, with `submitted_at`, `decided_at`, `rejection_reason`, and `correction_note` all null, and its `completeness_pct` computed immediately.

Completeness scores the case against six required elements — seven for an `ELECTIVE` case. Always required: the `patient_mrn` is present; the `performing_physician_id` is set; `actual_start` is set; `actual_end` is set; at least one `RADIATION` dose entry is `ACTIVE`; and no device usage of the case remains `RESERVED`. Elective cases additionally require `auc_status` to be `DOCUMENTED`. The `completeness_pct` is the number of satisfied elements divided by the number required, expressed as a percentage and rounded half-up to one decimal place; it is evaluated when the submission is created and refreshed again at submit time.

Submitting moves a `DRAFT` submission to `SUBMITTED` behind three gates. The submission must currently be `DRAFT`, otherwise `ERR_SUBMISSION_INVALID_STATE`. Its completeness must be exactly 100.0 — anything less, even 99.9, fails with `ERR_SUBMISSION_INCOMPLETE`. And the registry window must still be open: the deadline is thirty days after the case's `actual_end`, a current logical time falling strictly after that deadline is rejected with `ERR_SUBMISSION_WINDOW_EXPIRED`, and a submission landing exactly at the deadline is allowed. A successful submit stamps `submitted_at` from the logical clock and stores the refreshed `completeness_pct`.

The clearinghouse's decision is recorded against a `SUBMITTED` submission — any other state yields `ERR_SUBMISSION_INVALID_STATE`. An `outcome` of `ACCEPTED` stamps `decided_at` and closes the submission: `ACCEPTED` is terminal. A `rejection_reason` supplied alongside `ACCEPTED` is tolerated but not stored. An `outcome` of `REJECTED` requires a `rejection_reason` in the payload, and its absence fails with `ERR_INVALID_REQUEST`; the reason is stored and `decided_at` stamped.

A rejected submission re-enters the revision cycle. Revising carries a required `correction_note`, moves the submission `REJECTED` → `DRAFT` — again, only from `REJECTED`, else `ERR_SUBMISSION_INVALID_STATE` — stores the note, and clears `submitted_at` and `decided_at` to null, readying the submission for a fresh attempt. The loop `DRAFT` → `SUBMITTED` → `REJECTED` → `DRAFT` may repeat as often as needed. A case's submissions are listed through the case's submission collection, and any single submission can be fetched on its own.

## 4. Endpoint Definitions

Endpoints that create a new resource — registering rooms, staff, beds, and lots; posting cases; adding staff assignments, device usages, and dose entries; opening registry submissions — return `201 Created`. Endpoints that modify an existing resource or drive a state transition return `200 OK`. Recording an AUC attestation is the single exception to that shape: although it writes onto an existing case, it returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cath-lab/rooms` | Register a cath lab room | CathLabScheduler |
| GET | `/cath-lab/rooms` | List cath lab rooms | All roles |
| GET | `/cath-lab/rooms/{id}` | Get one cath lab room | All roles |
| PATCH | `/cath-lab/rooms/{id}` | Set room status (`ACTIVE` ↔ `OUT_OF_SERVICE`) | CathLabScheduler |
| POST | `/cath-lab/staff` | Register a staff member | CathLabScheduler |
| GET | `/cath-lab/staff` | List staff members | All roles |
| GET | `/cath-lab/staff/{id}` | Get one staff member | All roles |
| PATCH | `/cath-lab/staff/{id}` | Activate or deactivate a staff member | CathLabScheduler |
| GET | `/cath-lab/staff/{id}/assignments` | List a staff member's assignments | All roles |
| POST | `/cath-lab/cases` | Post a cath case; a STEMI case activates immediately | CathLabScheduler, InterventionalCardiologist |
| GET | `/cath-lab/cases` | List cath cases | All roles |
| GET | `/cath-lab/cases/{id}` | Get one cath case | All roles |
| POST | `/cath-lab/cases/{id}/schedule` | Schedule or reschedule a case onto a room | CathLabScheduler |
| POST | `/cath-lab/cases/{id}/cancel` | Cancel a non-terminal case | CathLabScheduler |
| POST | `/cath-lab/cases/{id}/start` | Begin the procedure | InterventionalCardiologist |
| POST | `/cath-lab/cases/{id}/complete` | Finish the procedure | InterventionalCardiologist |
| POST | `/cath-lab/cases/{id}/auc-attestation` | Document appropriate-use criteria (version-gated) | InterventionalCardiologist |
| POST | `/cath-lab/cases/{id}/staff-assignments` | Assign a staff member to a case | CathLabScheduler |
| GET | `/cath-lab/cases/{id}/staff-assignments` | List a case's staff assignments | All roles |
| POST | `/cath-lab/staff-assignments/{id}/release` | Release a staff assignment | CathLabScheduler |
| POST | `/cath-lab/device-lots` | Register a device/implant lot | CathLabTechnologist |
| GET | `/cath-lab/device-lots` | List device lots | All roles |
| GET | `/cath-lab/device-lots/{id}` | Get one device lot | All roles |
| POST | `/cath-lab/device-lots/{id}/restock` | Add units to a lot (version-gated) | CathLabTechnologist |
| GET | `/cath-lab/device-lots/{id}/usages` | List usages drawn from a lot | All roles |
| POST | `/cath-lab/cases/{id}/device-usages` | Reserve device units from a lot for a case | CathLabTechnologist |
| GET | `/cath-lab/cases/{id}/device-usages` | List a case's device usages | All roles |
| POST | `/cath-lab/device-usages/{id}/implant` | Mark reserved units as implanted | CathLabTechnologist |
| POST | `/cath-lab/device-usages/{id}/release` | Return reserved units to available stock | CathLabTechnologist |
| POST | `/cath-lab/cases/{id}/dose-records` | Record a contrast or radiation dose entry | CathLabTechnologist |
| GET | `/cath-lab/cases/{id}/dose-records` | List a case's dose records | All roles |
| POST | `/cath-lab/dose-records/{id}/void` | Void an active dose record | CathLabTechnologist |
| POST | `/cath-lab/recovery-beds` | Register a recovery bed | RecoveryNurseManager |
| GET | `/cath-lab/recovery-beds` | List recovery beds | All roles |
| GET | `/cath-lab/recovery-beds/{id}` | Get one recovery bed | All roles |
| PATCH | `/cath-lab/recovery-beds/{id}` | Set bed status (`AVAILABLE` ↔ `OUT_OF_SERVICE`) | RecoveryNurseManager |
| POST | `/cath-lab/recovery-beds/{id}/release` | Release an occupied bed | RecoveryNurseManager |
| POST | `/cath-lab/cases/{id}/registry-submissions` | Open a registry submission for a completed case | RegistryCoordinator |
| GET | `/cath-lab/cases/{id}/registry-submissions` | List a case's registry submissions | All roles |
| GET | `/cath-lab/registry-submissions/{id}` | Get one registry submission | All roles |
| POST | `/cath-lab/registry-submissions/{id}/submit` | Submit a draft submission to the registry | RegistryCoordinator |
| POST | `/cath-lab/registry-submissions/{id}/record-decision` | Record the clearinghouse decision | RegistryCoordinator |
| POST | `/cath-lab/registry-submissions/{id}/revise` | Return a rejected submission to draft | RegistryCoordinator |
| POST | `/cath-lab/_clock/set_current_utc` | Set the server's logical clock | CathLabScheduler |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_BED_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_USAGE_NOT_FOUND` | 404 Not Found |
| `ERR_DOSE_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_SUBMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_USAGE_INVALID_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_BED_INVALID_STATE` | 409 Conflict |
| `ERR_SUBMISSION_INVALID_STATE` | 409 Conflict |
| `ERR_SUBMISSION_INCOMPLETE` | 409 Conflict |
| `ERR_DOSE_RECORD_ALREADY_VOIDED` | 409 Conflict |
| `ERR_AUC_REQUIRED` | 422 Unprocessable Entity |
| `ERR_AUC_ORDERING_CONFLICT` | 403 Forbidden |
| `ERR_CONTRAST_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ROOM_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_STAFF_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DEVICE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SUBMISSION_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_ROOM_NOT_ACTIVE` | 409 Conflict |
| `ERR_STAFF_INACTIVE` | 409 Conflict |
| `ERR_STAFF_ROLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NOT_PERFORMING_PHYSICIAN` | 403 Forbidden |
| `ERR_STAFFING_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_RESOURCE_IN_USE` | 409 Conflict |
| `ERR_EQUIPMENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SUBMISSION` | 409 Conflict |
| `ERR_INSUFFICIENT_DEVICE_STOCK` | 409 Conflict |
| `ERR_NO_RECOVERY_BED` | 409 Conflict |
| `ERR_NO_STEMI_ROOM` | 409 Conflict |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |

Requests that fall outside the defined surface — an unknown path, a defined path called with an unsupported method, or an unexpected server failure — are answered in the same error envelope with `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), and `ERR_INTERNAL` (500) respectively.
