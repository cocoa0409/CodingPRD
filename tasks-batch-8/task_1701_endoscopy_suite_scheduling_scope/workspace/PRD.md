# Endoscopy Suite Scheduling & Scope Reprocessing API — Product Requirements Document

## 1. Introduction

A gastrointestinal endoscopy unit runs on three interlocking clocks: the appointment book, the anesthesia roster, and the reprocessing bench. Procedures must be booked against rooms and endoscopists with enough lead time for bowel preparation to take effect; every scope must travel a strictly ordered reprocessing pipeline — preclean, manual clean, high-level disinfection, drying — before it may touch the next patient; and when a surveillance culture returns positive, the unit must answer within minutes exactly which patients were exposed to the implicated scope since its last clean result. Whiteboards, spreadsheets, and institutional memory cannot carry that burden, and the cost of failure is measured in cancelled procedure lists, recalled patients, and regulatory findings.

This document specifies the Endoscopy Suite Scheduling & Scope Reprocessing API, the system of record for a GI endoscopy unit. It governs patient and provider registration, procedure booking with prep-lead-time and room-capacity enforcement, anesthesia coordination, intra-procedure bowel-prep assessment, scope inventory with deterministic assignment, the stepwise reprocessing cycle with documented disinfection evidence, culture surveillance with quarantine and exposure traceability, pathology specimen chain of custody, and quality measurement alongside room-utilization reporting. All resources are served under the `/endoscopy` prefix. Eight operator roles interact with the API, and every notion of "now" — step minimums, storage expiry, arrival windows, report periods — is read from a single controllable logical clock so that time-dependent behavior stays deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly eight roles, spelled precisely as follows: `UnitAdmin`, `SchedulingCoordinator`, `Endoscopist`, `AnesthesiaProvider`, `ReprocessingTechnician`, `InfectionControlNurse`, `PathologyStaff`, and `QualityOfficer`. Each endpoint restricts which roles may call it (see §4); a caller whose role is not in the endpoint's permitted set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Endoscopist`, `X-User-ID` is the `id` of the acting Provider; ownership checks on any resource that references a Provider compare the resource's `provider_id` field to `X-User-ID`. When `X-User-Role` is `AnesthesiaProvider`, `X-User-ID` is the `id` of the acting AnesthesiaProvider; ownership checks compare the assignment's `anesthesia_provider_id` field to `X-User-ID`. For the remaining six roles — `UnitAdmin`, `SchedulingCoordinator`, `ReprocessingTechnician`, `InfectionControlNurse`, `PathologyStaff`, and `QualityOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `technician_id` on a ReprocessingCycle, as `recorded_by` on a ScopeCultureTest, as `released_by` on a QuarantineCase, or as `labeled_by`, `handed_off_by`, and `received_by` on a Specimen) but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items are skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. The per-collection filters described throughout §3 compose freely with these two parameters.

### 2.4. The Logical Clock and the Meaning of "Now"

All time-dependent logic — reprocessing step minimums, scope storage expiry, check-in and no-show windows, booking lead times, report periods — reads a single logical clock rather than the host's wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`; before it has ever been set, the clock continues to report this default and never falls back to wall-clock time. A `UnitAdmin` may advance the clock through an admin-only capability that accepts a `to_iso8601` target instant and answers with the resulting `current_utc`. The target must be strictly later than the current logical reading; a target equal to or earlier than the present reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). Advancing the clock mutates no entity.

### 2.5. Common Resource Properties

Every primary resource — Patient, Provider, ProcedureType, Room, AnesthesiaProvider, Scope, ProcedureBooking, ScopeUsage, ReprocessingCycle, ScopeCultureTest, QuarantineCase, Specimen, and AnesthesiaAssignment — carries a standard set of system-managed fields:

- **`id`** (string): a server-minted UUID with no type prefix, uniquely addressing the resource.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation and never changed.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- **`version`** (integer): starts at 1 when the resource is created and increments by exactly 1 on every mutation, including mutations driven by cascades originating on other entities.

The QualityMetricReport is the sole exception: it is an immutable snapshot carrying only `id` and `created_at`. Both `updated_at` and `version` are absent from it, and nothing about a report can ever change after creation.

### 2.6. Reference Resolution and the Validation Ladder

The resource graph is flat: every resource is addressable directly under the API prefix by its `id`, and no resource nests inside another in its URL. When a path contains resource identifiers, they are validated from left to right, and the first identifier that fails to resolve produces its dedicated 404 response. References carried in request bodies — `patient_id`, `provider_id`, `procedure_type_id`, `room_id`, `booking_id`, `scope_id`, `reprocessing_cycle_id`, and `anesthesia_provider_id`, plus `new_room_id` on rescheduling — must likewise resolve before any other rule is evaluated. Each unresolved reference maps to its own error: `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`, `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`, `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`, `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`, `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`, all HTTP 404.

When a single request violates several rules, exactly one error surfaces, chosen by the following ladder — earlier rungs win over later ones:

1. **Header presence** — missing or empty `X-User-ID` or `X-User-Role`: `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — the caller's role is not permitted on the endpoint: `ERR_FORBIDDEN_ROLE`.
3. **Existence** — path and body reference resolution, as above; the 404 family.
4. **Request schema** — required fields present, types valid, enum values in range, integer ranges honored (BBPS segment scores between 0 and 3 inclusive, `container_count` at least 1, `base_duration_minutes` greater than 0, `withdrawal_time_seconds` and `adenomas_detected` at least 0, a POSITIVE culture accompanied by its organism and colony count): `ERR_INVALID_REQUEST`.
5. **Optimistic concurrency** — a stale expected version on a guarded write: `ERR_STALE_BOOKING_VERSION` or `ERR_STALE_SCOPE_VERSION`. Once the resource exists, this rung is evaluated before any business rule.
6. **Ownership and segregation of duties** — an `Endoscopist` acting on another provider's booking (`ERR_PROVIDER_OWNERSHIP_MISMATCH`), an `AnesthesiaProvider` confirming another provider's assignment (`ERR_ANESTHESIA_OWNERSHIP_MISMATCH`), or a quarantine releaser who personally performed the reculture cycle (`ERR_SEGREGATION_OF_DUTIES`).
7. **Legal from-state** — the target entity is not in a state that permits the requested transition: `ERR_BOOKING_NOT_SCHEDULED`, `ERR_BOOKING_NOT_CHECKED_IN`, `ERR_BOOKING_NOT_IN_PROGRESS`, `ERR_BOOKING_NOT_CANCELLABLE`, `ERR_PREP_NOT_CONFIRMED`, `ERR_PREP_ALREADY_ASSESSED`, `ERR_PREP_NOT_ASSESSED`, `ERR_PREP_NOT_INADEQUATE`, `ERR_SCOPE_NOT_AVAILABLE`, `ERR_SCOPE_NOT_REPROCESSABLE`, `ERR_SCOPE_NOT_RETIRABLE`, `ERR_CYCLE_STEP_OUT_OF_ORDER`, `ERR_CYCLE_NOT_ADVANCABLE`, `ERR_CULTURE_ALREADY_RESULTED`, `ERR_NO_OPEN_QUARANTINE`, `ERR_SPECIMEN_NOT_LABELED`, `ERR_SPECIMEN_NOT_IN_TRANSIT`, `ERR_SPECIMEN_NOT_RECEIVED`, `ERR_SPECIMEN_TERMINAL`, `ERR_ASSIGNMENT_STATE_INVALID`, `ERR_SCOPE_USAGE_NOT_VOIDABLE`.
8. **Compliance gates** — a suspended provider or anesthesia provider (`ERR_PROVIDER_SUSPENDED`, `ERR_ANESTHESIA_PROVIDER_SUSPENDED`), anesthesia coverage not yet confirmed when required (`ERR_ANESTHESIA_NOT_CONFIRMED`), an explicitly named scope past its storage limit (`ERR_SCOPE_STORAGE_EXPIRED`), disinfectant concentration below the floor (`ERR_HLD_CONCENTRATION_TOO_LOW`), a reprocessing step advanced before its minimum dwell time (`ERR_STEP_DURATION_TOO_SHORT`), or a specimen label or transport window exceeded (`ERR_LABEL_WINDOW_EXCEEDED`, `ERR_TRANSPORT_WINDOW_EXCEEDED`).
9. **Temporal gates** — `ERR_SCHEDULED_START_IN_PAST`, `ERR_PREP_LEAD_TIME_INSUFFICIENT`, `ERR_CHECKIN_WINDOW_CLOSED`, `ERR_NO_SHOW_WINDOW_NOT_REACHED`, `ERR_INVALID_PERIOD`, `ERR_CLOCK_REGRESSION`.
10. **Capacity and uniqueness** — `ERR_ROOM_TIME_CONFLICT`, `ERR_ROOM_DAY_CAPACITY_EXCEEDED`, `ERR_ANESTHESIA_TIME_CONFLICT`, `ERR_ROOM_NOT_IN_SERVICE`, `ERR_ANESTHESIA_TYPE_NONE`, `ERR_NO_COMPATIBLE_SCOPE`, `ERR_PATIENT_MRN_EXISTS`, `ERR_SERIAL_NUMBER_EXISTS`, `ERR_PROCEDURE_TYPE_CODE_EXISTS`.
11. **Cross-entity referential consistency** — `ERR_SCOPE_TYPE_MISMATCH`, `ERR_CULTURE_SCOPE_MISMATCH`, `ERR_CYCLE_NOT_COMPLETE`.

The ladder governs only which error surfaces first; the HTTP status attached to each error is fixed by §5 and does not change with its rung. The suspension, anesthesia-confirmation, and storage-expiry gates in rung 8, for instance, answer 409 even though their sibling concentration, step-duration, and specimen-window gates answer 422; likewise `ERR_CULTURE_SCOPE_MISMATCH` answers 400 while its rung-mates answer 409 or 422.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control. Each takes a mandatory expected-version field carrying the resource `version` the client last observed, and each rejects the write when that value no longer matches:

- `PATCH /endoscopy/bookings/{id}` requires `expected_booking_version`. If another writer has since advanced the booking's `version` — amending its notes, changing its anesthesia level, confirming prep, checking the patient in — the amendment is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412), preventing the client from overwriting a booking state it has not observed.
- `POST /endoscopy/bookings/{id}/reschedule` likewise requires `expected_booking_version`, with the same `ERR_STALE_BOOKING_VERSION` (HTTP 412) rejection on mismatch. Superseding a booking must be based on the client's latest observed state of that booking.
- `POST /endoscopy/scopes/{id}/release-quarantine` requires `expected_scope_version`. A mismatch with the scope's current `version` — for example because the reculture cycle has since completed and advanced it — is rejected with `ERR_STALE_SCOPE_VERSION` (HTTP 412).

Endpoints not named in this section do not accept a version field at all.

### 2.8. Units, Precision, and Rounding

Durations are whole minutes throughout. Scheduled durations are assembled from integer components, and measured durations truncate elapsed seconds down to whole minutes. Rates and averages reported by the quality and utilization endpoints carry exactly one decimal place, produced with round-half-up. Elapsed-time comparisons against step minimums, storage expiry instants, and arrival or transport windows are evaluated at second resolution, and minimum-threshold comparisons are inclusive: arriving exactly at a minimum satisfies it. All timestamps are ISO 8601 in UTC with three fractional digits; calendar-date fields such as `date_of_birth` use the `YYYY-MM-DD` form, and date-keyed lookups interpret the day as a UTC calendar day.

## 3. Business Logic & Workflows

### 3.1. Building the Unit Registry

Before a single procedure can be booked, the unit's reference data must exist. Patients are registered by a `SchedulingCoordinator` or a `UnitAdmin`, who supply an `mrn` (the medical record number, unique across patients — a duplicate is refused with `ERR_PATIENT_MRN_EXISTS`), a `full_name`, and a `date_of_birth` in `YYYY-MM-DD` form; the date of birth is not decoration, since it later drives every age computation the unit performs. An optional `contact_phone` may be recorded and stays null when omitted. The patient list can be narrowed with an optional `mrn` filter alongside the standard pagination parameters.

Endoscopists are created by a `UnitAdmin` with a `full_name` and a `specialty` of either `GASTROENTEROLOGY` or `COLORECTAL_SURGERY`. Each provider's `credential_status` begins as `ACTIVE`; a `UnitAdmin` may later amend a provider's `full_name` or move `credential_status` between `ACTIVE` and `SUSPENDED`, and suspension has teeth — a `SUSPENDED` provider cannot take new bookings and cannot start procedures. The provider list accepts a `credential_status` filter.

A ProcedureType describes a bookable procedure: a unique `code` such as COLONOSCOPY (duplicates refused with `ERR_PROCEDURE_TYPE_CODE_EXISTS`), a human-readable `display_name`, a `base_duration_minutes` that must be greater than zero (violations surface as `ERR_INVALID_REQUEST`), and a `prep_protocol` of `NONE`, `CLEAR_LIQUIDS`, or `SPLIT_DOSE` that dictates how far ahead such procedures may be booked. Two booleans shape downstream reporting: `colonoscopy_family` marks types whose procedures count toward withdrawal-time and cecal-intubation metrics, and `adr_relevant` marks types that may enter adenoma-detection denominators. Finally, `required_scope_type` — one of `COLONOSCOPE`, `GASTROSCOPE`, or `SIGMOIDOSCOPE` — declares which physical scope type the procedure is compatible with.

Rooms are created by a `UnitAdmin` with a display `name`, a `room_class` of `STANDARD` or `ERCP_CAPABLE` (the class drives the post-procedure turnover buffer), and a `supports_anesthesia` flag recording whether anesthesia cases may be booked in the room. A room's `status` begins as `ACTIVE`; a `UnitAdmin` may amend the `name` or move `status` between `ACTIVE` and `OUT_OF_SERVICE`, and an out-of-service room refuses new bookings and procedure starts. The room list accepts a `status` filter.

Anesthesia providers are registered by a `UnitAdmin` with just a `full_name`. Their `credential_status` likewise begins as `ACTIVE` and may be suspended or reinstated by a `UnitAdmin` — a `SUSPENDED` anesthesia provider cannot take new assignments — and each carries a computed `scheduled_minutes` total, zero at creation, that tracks their committed workload as described in §3.3. The anesthesia-provider list accepts a `credential_status` filter, and a single-anesthesia-provider read includes the live `scheduled_minutes` figure.

Scopes are registered by a `UnitAdmin` with a manufacturer `serial_number` (unique across scopes — duplicates are refused with `ERR_SERIAL_NUMBER_EXISTS`) and a `scope_type` of `COLONOSCOPE`, `GASTROSCOPE`, or `SIGMOIDOSCOPE`. A freshly registered scope is `AVAILABLE`, has a `use_count` of zero, and has never been reprocessed, so both its `storage_expires_at` and its `awaiting_reprocess_since` are null. Scope responses also expose the computed boolean `is_storage_current`, which is true when `storage_expires_at` is null or the logical now falls strictly before it. The scope list accepts `scope_type` and `status` filters.

### 3.2. Booking a Procedure: Lead Times, Windows, and Room Capacity

Booking is the exclusive province of the `SchedulingCoordinator`. The request names the principals by reference — `patient_id`, `provider_id`, `procedure_type_id`, and `room_id`, each of which must resolve to an existing record — and supplies the clinical shape of the visit: `scheduled_start` (the planned UTC start), an `indication` of `SCREENING`, `SURVEILLANCE`, or `DIAGNOSTIC`, an `anesthesia_type` of `NONE`, `MAC`, or `GENERAL`, and optional free-text `notes`.

Two temporal gates guard every new booking, and again on any change of schedule. First, `scheduled_start` must lie strictly in the future; a start at or before the current logical time is refused with `ERR_SCHEDULED_START_IN_PAST`. Second, the chosen procedure type's `prep_protocol` imposes a minimum lead time: a `SPLIT_DOSE` prep requires the start to be at least 24 hours away, `CLEAR_LIQUIDS` requires at least 8 hours, and `NONE` imposes no lead at all. A start inside the lead window is refused with `ERR_PREP_LEAD_TIME_INSUFFICIENT`.

From these inputs the system computes the booking's time window. The planned `procedure_minutes` is the procedure type's `base_duration_minutes`, plus an anesthesia add-on of 0 minutes for `NONE`, 10 for `MAC`, or 15 for `GENERAL`, plus a further 5 minutes when the patient is at least 65 years old at the scheduled start. Age here means full calendar years between the patient's `date_of_birth` and `scheduled_start` in UTC, and a patient whose birthday falls on the scheduled date counts as having already turned that age. The `scheduled_end` is then `scheduled_start` advanced by `procedure_minutes`, and the `room_block_end` adds a turnover buffer on top of `scheduled_end` — 15 minutes for a `STANDARD` room, 25 for an `ERCP_CAPABLE` one. A change of `anesthesia_type` on an existing booking recomputes all three figures from the same rule.

A room's committed calendar is then checked in two stages, overlap before capacity. For overlap, the candidate set is every other booking of the same room whose booking axis sits in `SCHEDULED`, `CHECKED_IN`, `IN_PROGRESS`, `COMPLETED`, or `ABORTED_PREP_INADEQUATE` — `CANCELLED`, `NO_SHOW`, and `RESCHEDULED` bookings have released their time and are ignored. A conflict exists exactly when the new booking's `scheduled_start` falls strictly before a candidate's `room_block_end` and the new booking's `room_block_end` falls strictly after that candidate's `scheduled_start`; because the intervals are half-open, exact adjacency — a new start landing precisely on the prior booking's `room_block_end` — is permitted. An overlapping request is refused with `ERR_ROOM_TIME_CONFLICT`. For capacity, the same candidate set restricted to the UTC calendar date of `scheduled_start` contributes its block minutes — the minutes from each booking's `scheduled_start` to its `room_block_end` — and the running total plus the new booking's own block must not exceed 480 minutes of committed room time in a day. A request that would breach the cap is refused with `ERR_ROOM_DAY_CAPACITY_EXCEEDED`.

Credential and room gates complete creation: the named provider must be `ACTIVE` (`ERR_PROVIDER_SUSPENDED` otherwise) and the room must be `ACTIVE` (`ERR_ROOM_NOT_IN_SERVICE` otherwise). A booking that passes everything is born with its booking axis in `SCHEDULED` and its prep axis in `PREP_PENDING` — two parallel status dimensions that live on the same record and evolve independently: the booking axis terminates in `COMPLETED`, `CANCELLED`, `NO_SHOW`, `RESCHEDULED`, or `ABORTED_PREP_INADEQUATE`, while the prep axis terminates in `PREP_ADEQUATE` or `PREP_INADEQUATE`. Every outcome and timing field on a fresh booking — `actual_start`, `actual_end`, `actual_duration_minutes`, `cecum_intubated`, `withdrawal_time_seconds`, `adenomas_detected`, `rescheduled_from_id`, and `cancel_reason` — begins null, `notification_flag` begins false, and the three BBPS segment fields stay null until the assessment of §3.5.

The booking list supports a broad filter set for day-to-day coordination: `patient_id`, `provider_id`, `room_id`, `procedure_type_id`, `rescheduled_from_id` (to trace a replacement chain), `status`, `prep_status`, and a `date` filter narrowing results to a UTC calendar day, in addition to pagination.

### 3.3. Coordinating Anesthesia Coverage

When a booking's `anesthesia_type` is `MAC` or `GENERAL`, coverage is arranged through an AnesthesiaAssignment created by a `SchedulingCoordinator` with a `booking_id` and an `anesthesia_provider_id`. Creation is refused outright when the booking's `anesthesia_type` is `NONE` — there is nothing to staff — with `ERR_ANESTHESIA_TYPE_NONE`, and refused with `ERR_ANESTHESIA_PROVIDER_SUSPENDED` when the named anesthesia provider is `SUSPENDED`.

Anesthesia coverage obeys a stricter overlap rule than rooms do. An assignment inherits the booking's scheduled procedure window, and a new assignment conflicts with any existing `ASSIGNED` or `CONFIRMED` assignment of the same anesthesia provider whenever the two windows share any instant — the intervals are closed, so assignments whose windows merely touch at an endpoint conflict and are refused with `ERR_ANESTHESIA_TIME_CONFLICT`. (Rooms, by contrast, permit exact adjacency.)

Each assignment stores a `minutes` field: a snapshot of the booking's `procedure_minutes` taken at creation and never recomputed, even if the booking is amended later. Those snapshots feed the `scheduled_minutes` ledger on each AnesthesiaProvider, which at any moment equals the sum of `minutes` over that provider's assignments in `ASSIGNED` or `CONFIRMED` status. Creating an assignment adds its minutes to the ledger; completion or cancellation releases them. The pair of operations on the same assignment — creation and a later cancellation or completion — therefore leaves the provider's `scheduled_minutes` exactly as it was, and amending the booking afterwards never disturbs the figure.

A new assignment is born in `ASSIGNED` with its `cancel_reason` null; from there the lifecycle runs `ASSIGNED` → `CONFIRMED` → `COMPLETED`, with `ASSIGNED` or `CONFIRMED` → `CANCELLED` as the early exit. Confirmation belongs to the assigned anesthesia provider alone: the caller's `X-User-ID` must equal the assignment's `anesthesia_provider_id` (`ERR_ANESTHESIA_OWNERSHIP_MISMATCH` otherwise), and only an `ASSIGNED` assignment can be confirmed (`ERR_ASSIGNMENT_STATE_INVALID`). An explicit cancellation may be filed by a `SchedulingCoordinator` or by the anesthesia provider, accepts an optional `reason` that is stored into `cancel_reason`, and is legal only from `ASSIGNED` or `CONFIRMED` (`ERR_ASSIGNMENT_STATE_INVALID`); it releases the assignment's minutes from the ledger.

Cascades keep the ledger honest without any explicit call. When a booking is cancelled, marked no-show, aborted, or rescheduled — or when its `anesthesia_type` is amended to `NONE` — every `ASSIGNED` or `CONFIRMED` assignment on that booking moves to `CANCELLED` and its minutes are released. When a booking completes, its `CONFIRMED` assignment moves to `COMPLETED`, again releasing minutes. The assignment list accepts `booking_id`, `anesthesia_provider_id`, and `status` filters.

### 3.4. Day of Procedure: Prep Confirmation, Check-In, and Scope Assignment

Once the patient has taken their prep, a `SchedulingCoordinator` records the attestation, moving the prep axis from `PREP_PENDING` to `PREP_CONFIRMED`. This is legal only while the booking axis remains `SCHEDULED`; otherwise the attempt is refused with `ERR_BOOKING_NOT_SCHEDULED`.

On arrival, the same role checks the patient in, moving the booking axis from `SCHEDULED` to `CHECKED_IN`. Two gates apply, evaluated state before temporal per the validation ladder — so a missing prep confirmation surfaces even when the arrival window has also closed. The prep axis must already be `PREP_CONFIRMED` (`ERR_PREP_NOT_CONFIRMED`), and the arrival must fall within the check-in window running from sixty minutes before `scheduled_start` through thirty minutes after it, inclusive at both ends; an arrival outside that window is refused with `ERR_CHECKIN_WINDOW_CLOSED`. A patient who simply never arrives is marked `NO_SHOW` by a `SchedulingCoordinator`, moving the booking axis from `SCHEDULED` to `NO_SHOW`; the axis must still be `SCHEDULED` — a booking already checked in cannot be marked no-show and the attempt is refused with `ERR_BOOKING_NOT_SCHEDULED` — and the logical time must be strictly later than thirty minutes past `scheduled_start`, with earlier attempts refused by `ERR_NO_SHOW_WINDOW_NOT_REACHED`. The no-show cascade cancels any active anesthesia assignment, releasing its minutes.

Starting the procedure belongs to the `Endoscopist` who owns the booking: the caller's `X-User-ID` must equal the booking's `provider_id` (`ERR_PROVIDER_OWNERSHIP_MISMATCH`). The booking axis must be `CHECKED_IN` (`ERR_BOOKING_NOT_CHECKED_IN`), the provider's `credential_status` must be `ACTIVE` (`ERR_PROVIDER_SUSPENDED`), the room must be in service (`ERR_ROOM_NOT_IN_SERVICE`), and whenever `anesthesia_type` is not `NONE`, a `CONFIRMED` AnesthesiaAssignment for the booking must already exist (`ERR_ANESTHESIA_NOT_CONFIRMED`).

Scope assignment happens at this same moment, in one of two ways. The endoscopist may name an explicit `scope_id`, in which case the scope must be `AVAILABLE` (`ERR_SCOPE_NOT_AVAILABLE`), must be storage-current — its `is_storage_current` true, meaning a null `storage_expires_at` or a logical now strictly before it — with `ERR_SCOPE_STORAGE_EXPIRED` the refusal, and its `scope_type` must equal the procedure type's `required_scope_type` (`ERR_SCOPE_TYPE_MISMATCH`). Alternatively, with `scope_id` omitted, a deterministic selector runs over the whole inventory: eligibility requires a matching `scope_type`, `AVAILABLE` status, and storage currency; eligible scopes are ranked by `use_count` ascending so the least-worn scope goes first, ties break toward the earliest `storage_expires_at` with never-expiring scopes (null) sorted last, and further ties fall to `created_at` ascending. An empty eligible pool refuses the start with `ERR_NO_COMPATIBLE_SCOPE`.

A successful start stamps `actual_start` to the current logical time and creates a ScopeUsage — the traceability junction carrying `booking_id`, `scope_id`, the `patient_id` denormalized from the booking, and `used_at` equal to the start instant, beginning in `ACTIVE` status with `void_reason` null and `exposure_flagged` false. The chosen scope moves to `IN_USE` and its `use_count` increments by one, keeping `use_count` equal to the number of non-`VOID` usage rows the scope has accumulated.

### 3.5. Assessment, Completion, and the End of a Booking

With the procedure underway, the endoscopist records the Boston Bowel Preparation Scale assessment: `bbps_left`, `bbps_right`, and `bbps_transverse`, each an integer from 0 to 3 (out-of-range values fail schema validation with `ERR_INVALID_REQUEST`). The act belongs to the booking's own endoscopist (`ERR_PROVIDER_OWNERSHIP_MISMATCH`), requires the booking axis at `IN_PROGRESS` (`ERR_BOOKING_NOT_IN_PROGRESS`), and is single-shot — all three segment fields must still be null, so a second assessment is refused with `ERR_PREP_ALREADY_ASSESSED`. The scores decide the prep axis outcome: the prep is `PREP_ADEQUATE` when the three segments total at least 6 and every individual segment is at least 2, and `PREP_INADEQUATE` otherwise. The scores are stored on the booking either way.

Completion, again by the owning endoscopist, requires the prep axis to have been assessed — `PREP_ADEQUATE` or `PREP_INADEQUATE` — with `ERR_PREP_NOT_ASSESSED` the refusal otherwise. The request records the quality fields: `cecum_intubated` (whether the cecum was reached), `withdrawal_time_seconds`, and `adenomas_detected`; the two counts must each be at least zero (`ERR_INVALID_REQUEST`). On completion the booking axis moves to `COMPLETED`, `actual_end` is stamped, and `actual_duration_minutes` is computed as the elapsed seconds between `actual_start` and `actual_end` truncated down to whole minutes — a measured figure that routinely differs from the forward-looking `procedure_minutes` estimate. If an `ACTIVE` ScopeUsage exists, its scope moves to `AWAITING_REPROCESS` with `awaiting_reprocess_since` stamped to the same instant, and a `CONFIRMED` anesthesia assignment moves to `COMPLETED`, releasing its minutes.

When the intra-procedure assessment reveals inadequate preparation, the endoscopist may instead abort: the prep axis must be exactly `PREP_INADEQUATE` (`ERR_PREP_NOT_INADEQUATE` otherwise), a `reason` is captured into `cancel_reason`, `actual_end` is stamped, and the booking axis settles at `ABORTED_PREP_INADEQUATE`. The same scope and anesthesia cascades apply — the scope goes to `AWAITING_REPROCESS` when an active usage exists, and an `ASSIGNED` or `CONFIRMED` assignment is cancelled with its minutes released.

A `SchedulingCoordinator` may cancel a booking whose axis is `SCHEDULED` or `CHECKED_IN`; any other state is refused with `ERR_BOOKING_NOT_CANCELLABLE`. An optional `reason` lands in `cancel_reason`, and the prep axis is deliberately left untouched — the two axes are independent — while any active anesthesia assignment is cancelled and its minutes released.

Amendment of a still-`SCHEDULED` booking is an OCC-guarded operation (per §2.7) restricted to a `SchedulingCoordinator`; any other booking state is refused with `ERR_BOOKING_NOT_SCHEDULED`. The payload may touch only `notes` and `anesthesia_type`. Changing `anesthesia_type` recomputes the whole time window — `procedure_minutes`, `scheduled_end`, and `room_block_end` — and re-runs the lead-time, room-overlap, and day-capacity validations of §3.2 against the new figure; setting `anesthesia_type` to `NONE` additionally cancels any active anesthesia assignment, releasing its minutes.

Rescheduling supersedes rather than edits. The `SchedulingCoordinator` supplies `expected_booking_version` (the OCC check of §2.7 runs before the new slot is examined, refusing stale views with `ERR_STALE_BOOKING_VERSION`), a `new_scheduled_start`, and an optional `new_room_id` — when omitted, the current room is reused; when present, it must resolve (`ERR_ROOM_NOT_FOUND`). The old booking must still be `SCHEDULED` (`ERR_BOOKING_NOT_SCHEDULED`). The proposed slot is then validated exactly as a fresh booking would be: future start, prep lead time, room overlap with turnover, and the 480-minute day capacity all re-run against the new time and room. On success the old booking's axis moves to `RESCHEDULED` and a brand-new booking is created with its `rescheduled_from_id` pointing back at the old one, its axis at `SCHEDULED`, its prep axis at `PREP_PENDING`, and version 1 — the response carries the new booking with a 201 status. The old booking's active anesthesia assignment is cancelled, releasing minutes.

Finally, a usage recorded in error can be voided by an `Endoscopist`: the usage must still be `ACTIVE` and its booking still `IN_PROGRESS`, otherwise `ERR_SCOPE_USAGE_NOT_VOIDABLE`. The supplied `reason` is stored in `void_reason`, the usage moves to `VOID`, the scope's `use_count` is decremented — creation and voiding of the same usage being a compensating pair that leaves `use_count` unchanged — and an `IN_USE` scope returns to `AVAILABLE`. Usage history is queryable with `booking_id`, `scope_id`, `patient_id`, `status`, and `exposure_flagged` filters.

### 3.6. Scope Reprocessing and Storage Limits

A scope's life is a cycle: `AVAILABLE` → `IN_USE` → `AWAITING_REPROCESS` → `REPROCESSING` → back to `AVAILABLE`, with a `QUARANTINED` branch entered from any of several points and a terminal `OUT_OF_SERVICE` for retired hardware. The transitions into `IN_USE` and out of it are driven by the booking lifecycle, as §3.4 and §3.5 describe.

Not every trip to the bench starts with a procedure. A `ReprocessingTechnician` or `UnitAdmin` may manually send an `AVAILABLE` scope to reprocessing — a scope whose hang time has lapsed or that was touch-contaminated — moving it to `AWAITING_REPROCESS` and stamping `awaiting_reprocess_since` to the current logical time. A scope in any other status is not reprocessable through this route (`ERR_SCOPE_NOT_REPROCESSABLE`).

Opening a ReprocessingCycle belongs to the `ReprocessingTechnician`. The scope must be `AWAITING_REPROCESS` or `QUARANTINED` (`ERR_SCOPE_NOT_REPROCESSABLE` otherwise); the request names the `scope_id` and may optionally attach a `booking_id`, which stays null for manual sends. The new cycle begins in `INITIATED` — with every later step timestamp and the HLD documentation fields null until their step lands — records `technician_id` from the caller, stamps `initiated_at`, and immediately computes `requires_extended_soak`: true when strictly more than 60 minutes have elapsed since the scope's `awaiting_reprocess_since` — a scope at exactly 60 minutes is not extended. Creation moves the scope to `REPROCESSING`. When the scope was `QUARANTINED`, the cycle is flagged `is_reculture` true, and the scope's open quarantine case moves from `OPEN` to `RECULTURING` with its `reculture_cycle_id` set to the new cycle.

The cycle itself is a strictly ordered step machine: `INITIATED` → `PRECLEANED` → `CLEANED` → `DISINFECTED` → `DRIED` → `COMPLETE`, with `FAILED` as the terminal rejection branch. Each advance names a `to_step`, and it must be exactly the next step — skipping or repeating a step is refused with `ERR_CYCLE_STEP_OUT_OF_ORDER`, while any advance against a terminal (`COMPLETE` or `FAILED`) cycle is refused with `ERR_CYCLE_NOT_ADVANCABLE`. Steps carry minimum dwell times, all evaluated with inclusive thresholds at second resolution:

- From `INITIATED` to `PRECLEANED`: no minimum; `precleaned_at` is stamped.
- From `PRECLEANED` to `CLEANED`: at least 20 minutes must have elapsed since `precleaned_at` when `requires_extended_soak` is true, otherwise at least 5 minutes; shortfalls are refused with `ERR_STEP_DURATION_TOO_SHORT`, and `cleaned_at` is stamped on success.
- From `CLEANED` to `DISINFECTED`: at least 600 seconds of high-level-disinfectant contact must have elapsed since `cleaned_at` (`ERR_STEP_DURATION_TOO_SHORT` otherwise). This step is also the documentation gate: the request must carry the `hld_solution_lot` and the measured `hld_concentration_ppm`. A concentration below 300 ppm is rejected with `ERR_HLD_CONCENTRATION_TOO_LOW` — and the rejection itself has teeth: the cycle falls to `FAILED` and the scope returns to `AWAITING_REPROCESS` with `awaiting_reprocess_since` reset to the present. At 300 ppm or above, the lot and concentration are stored and `disinfected_at` is stamped.
- From `DISINFECTED` to `DRIED`: at least 10 minutes since `disinfected_at` (`ERR_STEP_DURATION_TOO_SHORT`); `dried_at` is stamped.
- From `DRIED` to `COMPLETE`: no minimum; `completed_at` is stamped.

Completion is where storage limits are born. When the cycle completes, its scope returns to `AVAILABLE` — unless the scope is under quarantine, in which case it stays `QUARANTINED` while the disinfection documentation is preserved — and in either case the scope's `storage_expires_at` is set to the cycle's `dried_at` plus 72 hours. Storage currency is strict at the boundary: a scope is current while the logical now is strictly before `storage_expires_at`, a null `storage_expires_at` (a never-reprocessed scope) counts as current, and at the exact expiry instant the scope is already expired. Cycles are queryable with `scope_id`, `booking_id`, and `status` filters.

Retirement is a `UnitAdmin` decision available from `AVAILABLE`, `AWAITING_REPROCESS`, or `QUARANTINED`; a scope that is `IN_USE` or `REPROCESSING` cannot be retired (`ERR_SCOPE_NOT_RETIRABLE`). Retirement moves the scope to `OUT_OF_SERVICE`, and if a quarantine case is open on it, the case settles at `SCOPE_RETIRED` with `resolved_at` stamped.

### 3.7. Culture Surveillance, Quarantine, and Exposure Traceability

Surveillance cultures are the unit's tripwire. An `InfectionControlNurse` opens a ScopeCultureTest by naming a `scope_id` and a `reprocessing_cycle_id`; the referenced cycle must belong to that very scope (`ERR_CULTURE_SCOPE_MISMATCH` when it belongs to a different one) and must already be `COMPLETE` (`ERR_CYCLE_NOT_COMPLETE`), and the scope must not be `OUT_OF_SERVICE` (`ERR_SCOPE_NOT_AVAILABLE`). The test begins `PENDING`, with `sampled_at` stamped to the current logical time and `recorded_by` set from the caller.

Recording the result is likewise the `InfectionControlNurse`'s act and is legal only while the test is `PENDING` (`ERR_CULTURE_ALREADY_RESULTED` on a second attempt). The `result` is `NEGATIVE` or `POSITIVE`; a `POSITIVE` result must be accompanied by an `organism` name and a `cfu_count` of zero or more, and a positive without them fails schema validation with `ERR_INVALID_REQUEST`. The `result`, `organism`, `cfu_count`, and `resulted_at` are stored together.

A `POSITIVE` result fires the quarantine cascade. First, the exposure window is computed. Its end — the case's `exposure_window_end` — is the triggering culture's `sampled_at`. Its start — `exposure_window_start` — is the `sampled_at` of the latest `NEGATIVE` culture on the same scope taken strictly before the trigger; if two such cultures share a timestamp, the one created later wins, and when no earlier negative exists at all, the window start is null, meaning the exposure reach is unbounded into the past. The exposure set is then every ScopeUsage of the scope — `VOID` rows included, for traceability — whose booking's `actual_end` falls after the window start and at or before the trigger's sample time: the interval is left-exclusive and right-inclusive, so a usage ending exactly at the last negative sample is excluded while one ending exactly at the trigger is included. Every usage in the set gets `exposure_flagged` set true, and each of their bookings gets `notification_flag` set true, which is how the recall list surfaces. A QuarantineCase opens in `OPEN` status with `opened_at` stamped, the `triggering_culture_id` recorded, and the window fields populated; the scope itself moves to `QUARANTINED` from `AVAILABLE`, `AWAITING_REPROCESS`, or `REPROCESSING`. One branch deserves emphasis: if the scope has already been retired, no scope transition is possible, and the case is created directly in `SCOPE_RETIRED`.

The path back to service runs through reculture. Creating a reprocessing cycle on the quarantined scope — §3.6 — moves the case from `OPEN` to `RECULTURING` and records the cycle as `reculture_cycle_id`; when that reculture cycle completes, the scope remains `QUARANTINED`, awaiting a verdict. Retiring the scope at any point settles the case at `SCOPE_RETIRED` with `resolved_at` stamped.

Release is an `InfectionControlNurse` act with four gates, and the OCC version check of §2.7 — a required `expected_scope_version`, refused with `ERR_STALE_SCOPE_VERSION` when stale — is evaluated before the business gates. An open quarantine case must exist for the scope, `OPEN` or `RECULTURING` (`ERR_NO_OPEN_QUARANTINE`). A `NEGATIVE` culture must already exist against the case's `reculture_cycle_id` (`ERR_RECULTURE_NOT_NEGATIVE`). And segregation of duties forbids the releaser from being the technician who performed the reculture cycle: the caller's `X-User-ID` must differ from the reculture cycle's `technician_id` (`ERR_SEGREGATION_OF_DUTIES`). A release that passes everything moves the scope from `QUARANTINED` back to `AVAILABLE` and settles the case at `RELEASED` with `released_by` set from the caller and `resolved_at` stamped.

Case history is queryable with `scope_id`, `status`, `triggering_culture_id`, and `reculture_cycle_id` filters, and a computed per-case read returns exactly the ScopeUsage rows inside the exposure window under the same left-exclusive, right-inclusive rule. Culture tests are queryable with `scope_id`, `reprocessing_cycle_id`, and `status` filters.

### 3.8. Specimen Chain of Custody

Tissue moves under a chain of custody whose states run `COLLECTED` → `LABELED` → `IN_TRANSIT` → `RECEIVED_BY_LAB` → `RESULTED`, with `REJECTED_BY_LAB` as the terminal refusal branch.

Collection is performed by the booking's own `Endoscopist` (`ERR_PROVIDER_OWNERSHIP_MISMATCH`) while the booking axis is `IN_PROGRESS` (`ERR_BOOKING_NOT_IN_PROGRESS`). The request names the `booking_id`, a `specimen_type` of `POLYP`, `BIOPSY`, or `OTHER`, and a `container_count` of at least 1 (`ERR_INVALID_REQUEST`). The specimen is born `COLLECTED`, its `collected_at` stamped to the current logical time — that stamp anchors every later custody window — and its `patient_id` denormalized from the booking for traceability.

Labeling must happen fast: within fifteen minutes of `collected_at`, inclusive — a labeling attempted later is refused with `ERR_LABEL_WINDOW_EXCEEDED`. Either the `Endoscopist` or `PathologyStaff` may label; the specimen moves to `LABELED` with `labeled_at` stamped and `labeled_by` set from the caller.

Courier handoff belongs to `PathologyStaff` and is legal only from `LABELED` (`ERR_SPECIMEN_NOT_LABELED`). The request supplies the `courier_id`; the specimen moves to `IN_TRANSIT` with `handed_off_at` stamped and `handed_off_by` set from the caller.

Laboratory receipt, again `PathologyStaff`, requires `IN_TRANSIT` (`ERR_SPECIMEN_NOT_IN_TRANSIT`) and enforces the transport window: receipt must occur no later than 120 minutes after `collected_at`, inclusive — a later receipt is refused with `ERR_TRANSPORT_WINDOW_EXCEEDED`. Success stamps `received_at` and records `received_by`, settling the specimen at `RECEIVED_BY_LAB`.

Result recording by `PathologyStaff` requires `RECEIVED_BY_LAB` (`ERR_SPECIMEN_NOT_RECEIVED`); the request carries the `adenoma_confirmed` pathology flag, `resulted_at` is stamped, and the specimen settles at `RESULTED`. Rejection by `PathologyStaff` is available while the specimen is `LABELED` or `IN_TRANSIT` — after receipt or result the option is gone (`ERR_SPECIMEN_TERMINAL`) — storing the supplied `reason` into `reject_reason` and settling at `REJECTED_BY_LAB`. The specimen list accepts `booking_id`, `patient_id`, and `status` filters.

### 3.9. Quality Measurement and Utilization Reporting

A `QualityOfficer` creates a QualityMetricReport by naming a `provider_id`, a `period_start`, a `period_end`, and a `metric_variant` of `STRICT` or `EXPANDED`. The period bounds are both inclusive against bookings' `actual_end`, and `period_start` must not fall after `period_end` (`ERR_INVALID_PERIOD`). The report is computed exactly once, at creation, into an immutable snapshot — recall from §2.5 that it carries only `id` and `created_at`, with no `updated_at` and no `version`, so later bookings can never retroactively alter a published figure. The report list accepts `provider_id` and `metric_variant` filters.

The adenoma detection rate is the only variant-sensitive metric. Its candidate set is the provider's `COMPLETED` bookings whose procedure type is `adr_relevant` and whose `actual_end` falls within the period. Under the `STRICT` variant, the denominator admits only those candidates that additionally satisfy all four auditing filters: `indication` of `SCREENING`, a patient at least 45 years old at the scheduled start (the same full-calendar-years age rule as §3.2), `cecum_intubated` true, and prep axis `PREP_ADEQUATE`. Under the `EXPANDED` variant, the denominator is the whole candidate set with no further filtering — the operational denominator, which routinely yields a different rate from the same underlying data. The `adr_denominator` is the denominator's size, the `adr_numerator` counts denominator rows whose `adenomas_detected` is at least 1, and the `adenoma_detection_rate` is null when the denominator is zero, otherwise one hundred times the numerator divided by the denominator, rounded half-up to one decimal place.

The withdrawal-time average is variant-invariant. Its inclusion set is the provider's `COMPLETED` bookings whose procedure type is in the `colonoscopy_family`, with `actual_end` in the period, `cecum_intubated` true, `adenomas_detected` exactly zero, and zero Specimen rows linked through `booking_id` — a specimen in any status counts as taken and excludes the booking. The `withdrawal_time_avg_seconds` is null when the set is empty, otherwise the mean of `withdrawal_time_seconds` across the set, rounded half-up to one decimal place; `withdrawal_sample_size` reports the set's size.

Two further rates round out the report, also variant-invariant. The `cecal_intubation_rate` divides the provider's `COMPLETED`, `colonoscopy_family`, in-period bookings into those with `cecum_intubated` true, is null when that denominator is zero, and otherwise expresses the percentage with one half-up-rounded decimal. The `prep_adequacy_rate` takes the provider's bookings with `actual_end` in the period whose prep axis has been assessed — `PREP_ADEQUATE` or `PREP_INADEQUATE` — and expresses the `PREP_ADEQUATE` share the same way, null when the denominator is zero.

Room utilization is a computed read, available to a `QualityOfficer` or a `UnitAdmin`, keyed by a required `date` in `YYYY-MM-DD` form. For every Room regardless of `status`, the occupied minutes are the sum of block minutes — `scheduled_start` to `room_block_end` — over bookings whose `scheduled_start` falls on that UTC date and whose booking axis is `SCHEDULED`, `CHECKED_IN`, `IN_PROGRESS`, `COMPLETED`, or `ABORTED_PREP_INADEQUATE`; `CANCELLED`, `NO_SHOW`, and `RESCHEDULED` bookings are excluded. Each room's utilization percentage is one hundred times its occupied minutes divided by 480 open minutes, rounded half-up to one decimal place — and the rounding order is pinned: each room is rounded first, the unit figure `unit_utilization_pct` is then the average of those per-room percentages, itself rounded half-up to one decimal place. Computing the unit figure from raw summed minutes instead is a different, non-conformant algorithm. The response carries the `date`, the `open_minutes_per_room` constant (480), the `unit_utilization_pct`, and a `rooms` array with each room's occupied minutes and percentage; when no rooms exist at all, `rooms` is empty and `unit_utilization_pct` is null.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; this includes rescheduling, which returns the newly created replacement booking with 201. Operations that modify an existing resource, record a transition, or answer a computed read return `200 OK`. Request and response bodies follow the envelope of §2.2; the workflow narratives of §3 define each operation's payload and effects.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/endoscopy/_clock/set_current_utc` | Advance the logical clock (strictly increasing) | UnitAdmin |
| POST | `/endoscopy/patients` | Register a patient | SchedulingCoordinator, UnitAdmin |
| GET | `/endoscopy/patients` | List patients (paginated) | All roles |
| GET | `/endoscopy/patients/{id}` | Get one patient | All roles |
| POST | `/endoscopy/providers` | Create an endoscopist | UnitAdmin |
| GET | `/endoscopy/providers` | List providers | All roles |
| GET | `/endoscopy/providers/{id}` | Get one provider | All roles |
| PATCH | `/endoscopy/providers/{id}` | Update provider (credential suspend/reinstate) | UnitAdmin |
| POST | `/endoscopy/procedure-types` | Create a procedure type (code unique) | UnitAdmin |
| GET | `/endoscopy/procedure-types` | List procedure types | All roles |
| GET | `/endoscopy/procedure-types/{id}` | Get one procedure type | All roles |
| POST | `/endoscopy/rooms` | Create a procedure room | UnitAdmin |
| GET | `/endoscopy/rooms` | List rooms | All roles |
| GET | `/endoscopy/rooms/{id}` | Get one room | All roles |
| PATCH | `/endoscopy/rooms/{id}` | Update room (take out of service / return) | UnitAdmin |
| POST | `/endoscopy/anesthesia-providers` | Create an anesthesia provider | UnitAdmin |
| GET | `/endoscopy/anesthesia-providers` | List anesthesia providers | All roles |
| GET | `/endoscopy/anesthesia-providers/{id}` | Get one anesthesia provider (includes computed scheduled_minutes) | All roles |
| PATCH | `/endoscopy/anesthesia-providers/{id}` | Update anesthesia provider (credential suspend/reinstate) | UnitAdmin |
| POST | `/endoscopy/scopes` | Register an endoscope (serial_number unique) | UnitAdmin |
| GET | `/endoscopy/scopes` | List scopes | All roles |
| GET | `/endoscopy/scopes/{id}` | Get one scope | All roles |
| POST | `/endoscopy/scopes/{id}/send-to-reprocessing` | Manually send an AVAILABLE scope to reprocessing | ReprocessingTechnician, UnitAdmin |
| POST | `/endoscopy/scopes/{id}/retire` | Retire a scope (not while IN_USE or REPROCESSING) | UnitAdmin |
| POST | `/endoscopy/scopes/{id}/release-quarantine` | Release a quarantined scope after a negative reculture (OCC-guarded) | InfectionControlNurse |
| POST | `/endoscopy/bookings` | Book a procedure; computes the time window and validates lead time, overlap, capacity, provider and room status | SchedulingCoordinator |
| GET | `/endoscopy/bookings` | List bookings with filters (paginated) | All roles |
| GET | `/endoscopy/bookings/{id}` | Get one booking | All roles |
| PATCH | `/endoscopy/bookings/{id}` | Amend a SCHEDULED booking (notes, anesthesia_type; OCC-guarded) | SchedulingCoordinator |
| POST | `/endoscopy/bookings/{id}/confirm-prep` | Record patient attestation that prep was taken | SchedulingCoordinator |
| POST | `/endoscopy/bookings/{id}/check-in` | Check in a patient inside the arrival window; requires confirmed prep | SchedulingCoordinator |
| POST | `/endoscopy/bookings/{id}/start` | Start the procedure; assigns a scope and creates the usage record | Endoscopist |
| POST | `/endoscopy/bookings/{id}/record-prep-assessment` | Record intra-procedure BBPS scores (single-shot) | Endoscopist |
| POST | `/endoscopy/bookings/{id}/complete` | Complete the procedure; records quality fields; frees room and scope | Endoscopist |
| POST | `/endoscopy/bookings/{id}/abort` | Abort an in-progress procedure for inadequate prep | Endoscopist |
| POST | `/endoscopy/bookings/{id}/cancel` | Cancel a SCHEDULED or CHECKED_IN booking; prep axis untouched | SchedulingCoordinator |
| POST | `/endoscopy/bookings/{id}/mark-no-show` | Mark no-show after the grace window | SchedulingCoordinator |
| POST | `/endoscopy/bookings/{id}/reschedule` | Supersede this booking with a new one (OCC-guarded; returns the new booking) | SchedulingCoordinator |
| POST | `/endoscopy/anesthesia-assignments` | Assign an anesthesia provider to a booking (closed-interval overlap) | SchedulingCoordinator |
| GET | `/endoscopy/anesthesia-assignments` | List anesthesia assignments | All roles |
| GET | `/endoscopy/anesthesia-assignments/{id}` | Get one assignment | All roles |
| POST | `/endoscopy/anesthesia-assignments/{id}/confirm` | Anesthesia provider confirms own assignment | AnesthesiaProvider |
| POST | `/endoscopy/anesthesia-assignments/{id}/cancel` | Cancel an active assignment; releases scheduled minutes | SchedulingCoordinator, AnesthesiaProvider |
| GET | `/endoscopy/scope-usages` | List scope usages (scope-to-patient traceability) | All roles |
| GET | `/endoscopy/scope-usages/{id}` | Get one scope usage | All roles |
| POST | `/endoscopy/scope-usages/{id}/void` | Void a usage recorded in error (booking must still be IN_PROGRESS) | Endoscopist |
| POST | `/endoscopy/reprocessing-cycles` | Open a reprocessing cycle on an AWAITING_REPROCESS or QUARANTINED scope | ReprocessingTechnician |
| GET | `/endoscopy/reprocessing-cycles` | List reprocessing cycles | All roles |
| GET | `/endoscopy/reprocessing-cycles/{id}` | Get one reprocessing cycle | All roles |
| POST | `/endoscopy/reprocessing-cycles/{id}/steps/advance` | Advance exactly one step; enforces step minimums and the HLD concentration gate | ReprocessingTechnician |
| POST | `/endoscopy/culture-tests` | Create a surveillance culture test against a COMPLETE reprocessing cycle | InfectionControlNurse |
| GET | `/endoscopy/culture-tests` | List culture tests | All roles |
| GET | `/endoscopy/culture-tests/{id}` | Get one culture test | All roles |
| POST | `/endoscopy/culture-tests/{id}/result` | Record the culture result; POSITIVE quarantines the scope and opens a case | InfectionControlNurse |
| GET | `/endoscopy/quarantine-cases` | List quarantine cases | All roles |
| GET | `/endoscopy/quarantine-cases/{id}` | Get one quarantine case | All roles |
| GET | `/endoscopy/quarantine-cases/{id}/exposures` | Computed read: usages inside the case exposure window | All roles |
| POST | `/endoscopy/specimens` | Collect a specimen during an IN_PROGRESS booking (chain-of-custody start) | Endoscopist |
| GET | `/endoscopy/specimens` | List specimens | All roles |
| GET | `/endoscopy/specimens/{id}` | Get one specimen | All roles |
| POST | `/endoscopy/specimens/{id}/label` | Label a collected specimen within 15 minutes of collection | Endoscopist, PathologyStaff |
| POST | `/endoscopy/specimens/{id}/handoff` | Hand a labeled specimen to a courier | PathologyStaff |
| POST | `/endoscopy/specimens/{id}/receive` | Lab receives an in-transit specimen; transport window enforced | PathologyStaff |
| POST | `/endoscopy/specimens/{id}/reject` | Reject a LABELED or IN_TRANSIT specimen | PathologyStaff |
| POST | `/endoscopy/specimens/{id}/result` | Record pathology result for a received specimen | PathologyStaff |
| POST | `/endoscopy/quality-reports` | Create an immutable quality-metric snapshot for a provider and period | QualityOfficer |
| GET | `/endoscopy/quality-reports` | List quality reports | All roles |
| GET | `/endoscopy/quality-reports/{id}` | Get one quality report | All roles |
| GET | `/endoscopy/reports/room-utilization` | Computed per-room and unit utilization for a UTC date | QualityOfficer, UnitAdmin |

## 5. Error Code Catalogue

The catalogue below fixes the HTTP status for every error identifier; §2 and §3 define the conditions under which each is raised, and §2.6 fixes which error surfaces when several rules are violated at once.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_PROVIDER_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_ANESTHESIA_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PATIENT_NOT_FOUND` | 404 Not Found |
| `ERR_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_PROCEDURE_TYPE_NOT_FOUND` | 404 Not Found |
| `ERR_ROOM_NOT_FOUND` | 404 Not Found |
| `ERR_ANESTHESIA_PROVIDER_NOT_FOUND` | 404 Not Found |
| `ERR_SCOPE_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_SCOPE_USAGE_NOT_FOUND` | 404 Not Found |
| `ERR_REPROCESSING_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_CULTURE_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_QUARANTINE_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_SPECIMEN_NOT_FOUND` | 404 Not Found |
| `ERR_QUALITY_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_BOOKING_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SCOPE_VERSION` | 412 Precondition Failed |
| `ERR_BOOKING_NOT_SCHEDULED` | 409 Conflict |
| `ERR_BOOKING_NOT_CHECKED_IN` | 409 Conflict |
| `ERR_BOOKING_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_BOOKING_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PREP_NOT_CONFIRMED` | 409 Conflict |
| `ERR_PREP_ALREADY_ASSESSED` | 409 Conflict |
| `ERR_PREP_NOT_ASSESSED` | 409 Conflict |
| `ERR_PREP_NOT_INADEQUATE` | 409 Conflict |
| `ERR_SCOPE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SCOPE_NOT_REPROCESSABLE` | 409 Conflict |
| `ERR_SCOPE_NOT_RETIRABLE` | 409 Conflict |
| `ERR_CYCLE_STEP_OUT_OF_ORDER` | 409 Conflict |
| `ERR_CYCLE_NOT_ADVANCABLE` | 409 Conflict |
| `ERR_CULTURE_ALREADY_RESULTED` | 409 Conflict |
| `ERR_NO_OPEN_QUARANTINE` | 409 Conflict |
| `ERR_SPECIMEN_NOT_LABELED` | 409 Conflict |
| `ERR_SPECIMEN_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_SPECIMEN_NOT_RECEIVED` | 409 Conflict |
| `ERR_SPECIMEN_TERMINAL` | 409 Conflict |
| `ERR_ASSIGNMENT_STATE_INVALID` | 409 Conflict |
| `ERR_SCOPE_USAGE_NOT_VOIDABLE` | 409 Conflict |
| `ERR_PROVIDER_SUSPENDED` | 409 Conflict |
| `ERR_ANESTHESIA_PROVIDER_SUSPENDED` | 409 Conflict |
| `ERR_ANESTHESIA_NOT_CONFIRMED` | 409 Conflict |
| `ERR_SCOPE_STORAGE_EXPIRED` | 409 Conflict |
| `ERR_HLD_CONCENTRATION_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_STEP_DURATION_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_LABEL_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TRANSPORT_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SCHEDULED_START_IN_PAST` | 422 Unprocessable Entity |
| `ERR_PREP_LEAD_TIME_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CHECKIN_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_NO_SHOW_WINDOW_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_INVALID_PERIOD` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |
| `ERR_ROOM_TIME_CONFLICT` | 409 Conflict |
| `ERR_ROOM_DAY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ANESTHESIA_TIME_CONFLICT` | 409 Conflict |
| `ERR_ROOM_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_ANESTHESIA_TYPE_NONE` | 409 Conflict |
| `ERR_NO_COMPATIBLE_SCOPE` | 409 Conflict |
| `ERR_PATIENT_MRN_EXISTS` | 409 Conflict |
| `ERR_SERIAL_NUMBER_EXISTS` | 409 Conflict |
| `ERR_PROCEDURE_TYPE_CODE_EXISTS` | 409 Conflict |
| `ERR_SCOPE_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CULTURE_SCOPE_MISMATCH` | 400 Bad Request |
| `ERR_CYCLE_NOT_COMPLETE` | 409 Conflict |
| `ERR_RECULTURE_NOT_NEGATIVE` | 409 Conflict |
