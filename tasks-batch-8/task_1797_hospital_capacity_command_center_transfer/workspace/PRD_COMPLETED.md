# Hospital Capacity Command Center API — Product Requirements Document

## 1. Introduction

Hospitals in a multi-facility health system routinely operate without a shared, real-time picture of staffed-bed capacity. Transfer centers call sibling facilities one by one to find accepting physicians, emergency departments board admitted patients for hours without an escalation trail, and elective schedulers book cases against census numbers that were stale before they were printed. The Hospital Capacity Command Center API consolidates this work into a single coordination service: it tracks bed availability and pending discharges as they change, runs transfer-request intake with an accepting-physician consult cycle, matches patients to beds against acuity, isolation, and service constraints, manages diversion posture with ambulance-notification semantics, times ED boarding with automatic escalation huddles, and projects capacity forward so elective scheduling can target genuinely open windows.

This document specifies the API's behavioral contract for engineering. It is written for implementers who must reproduce exact semantics: derived facility load figures and their rounding, bed-selector scoring and tie-breaking, diversion and cooling window arithmetic, consult and hold deadlines, and the cascades that keep forecasts honest when beds change hands. Every rule herein is normative. The service is mounted under the `/cc` prefix, and all time-dependent behavior is evaluated against a server-controlled logical clock so that deadlines, windows, and forecasts are deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the user's operational capacity. A request in which either header is missing, empty, or whitespace-only is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); surrounding whitespace is otherwise trimmed from both header values. The system recognizes seven role designations: `SystemAdministrator`, `BedManager`, `TransferCenterCoordinator`, `AcceptingPhysician`, `HouseSupervisor`, `CapacityPlanner`, and `Any`; an `X-User-Role` value outside these seven designations is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Each write endpoint is restricted to the roles listed in Section 4; a request whose role is not authorized for the endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). `Any` is the shared read authorization granted to every authenticated role for the read endpoints listed in Section 4; presented literally as `X-User-Role`, `Any` authenticates like any other designation and authorizes exactly those read endpoints — never a write endpoint.

Role identity semantics differ by role. When `X-User-Role` is `AcceptingPhysician`, `X-User-ID` is the `id` of the acting `Physician`, and a request whose `X-User-ID` does not resolve to a registered `Physician`'s `id` is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403) before any endpoint-specific check; ownership checks on any resource that references a `Physician` compare the resource's foreign-key field to `X-User-ID` (this is how the consult-response ownership check is enforced). When `X-User-Role` is `SystemAdministrator`, `BedManager`, `TransferCenterCoordinator`, `HouseSupervisor`, `CapacityPlanner`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `intake_coordinator_id` on a transfer request, as `declared_by_user_id` or `lifted_by_user_id` on a diversion event, or as `created_by_user_id` on a bed assignment — but it does not compare the identifier to any entity's `id`; the segregation-of-duties rules in §2.10 compare the incoming `X-User-ID` to those previously recorded operator identifiers, not to entity records.

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

Requests that match no defined route are rejected with `ERR_INVALID_REQUEST` (HTTP 404), a defined path called with an unsupported method is rejected with `ERR_INVALID_REQUEST` (HTTP 405), and an unexpected server failure surfaces as `ERR_INVALID_REQUEST` (HTTP 500); all three use the standard error envelope above.

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100, and out-of-range values are clamped to the nearest bound rather than rejected. The `offset` parameter specifies how many items to skip and defaults to 0, with negative values clamped to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with resources created at the same logical-clock instant kept in creation (registration) order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items returned is smaller than `total_count`.

### 2.4. The Logical Clock and the Housekeeping Sweep

All time-dependent behavior in the system — recorded timestamps, consult deadlines, hold expirations, diversion windows, boarding durations, forecast hour mapping, and sweep checks — reads a server-controlled logical clock, never the host's wall clock. At startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z; the server must not fall back to wall-clock time under any circumstance. A `SystemAdministrator` can advance the clock through an admin-only test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value; the capability responds with the new `current_utc`. Every deadline and window described in this document is evaluated against this logical "now".

A second `SystemAdministrator` capability runs one housekeeping sweep against the logical clock. A sweep performs four duties: it expires every `ACTIVE` bed hold whose `expires_at` has been reached or passed; it expires every `CONSULT_PENDING` transfer request whose `consult_deadline` has been reached or passed, recording the decline reason `TIMEOUT`; it expires every `ACTIVE` diversion whose `ends_at` has been reached or passed; and it runs the boarding escalation check for every boarding record still in an open placement. The sweep reports four lists of affected identifiers: `expired_hold_ids`, `expired_consult_request_ids`, `expired_diversion_ids`, and `escalated_boarding_record_ids`, each list in the creation order of the affected resources; `escalated_boarding_record_ids` contains only records for which the sweep actually called an auto-threshold huddle — a sweep that merely sets `executive_escalation` does not list the record.

### 2.5. Common Resource Properties

Every resource in the system — facilities, beds, physicians, admissions, transfer requests, bed holds, bed assignments, diversion events, boarding records, escalation huddles, and capacity forecasts — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one with every mutation of the resource. It backs the optimistic concurrency control rules in §2.9.

Any mutation described in Section 3 — including cascades triggered by the system rather than by a direct client call on that resource — refreshes `updated_at` and increments `version` on each mutated resource.

Every timestamp the API emits — not only `created_at`, `updated_at`, and the envelope's `api_request_timestamp`, but also domain timestamps such as `starts_at`, `ends_at`, `expires_at`, `consult_deadline`, `cooling_until`, `projected_free_at`, `expected_discharge_at`, `pending_discharge_at`, `confirmed_discharge_at`, `completed_at`, `lifted_at`, `started_at`, `called_at`, `resolved_at`, `generated_at`, `published_at`, `next_elective_window_start`, and the clock capability's `current_utc` — is serialized in the same form: an ISO 8601 UTC timestamp with three fractional digits and a `Z` suffix (for example, `2026-08-01T00:00:00.000Z`). Client-supplied timestamps are parsed leniently as ISO 8601, a value without an explicit UTC offset is interpreted as UTC, and an unparseable value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Derived Facility Posture and Numeric Precision

A facility is a monitored aggregate whose load picture is entirely derived. Its `diversion_status` is never set directly by a client; it is recomputed from the facility's diversion events whenever a diversion is created, lifted, or expires, and its exact derivation is given in §3.7. The bed counters `staffed_beds`, `occupied_beds`, `held_beds`, `available_beds`, and `out_of_service_beds`, the pipeline counters `boarding_waiters` and `active_inbound_transfers`, the scores `load_score_raw`, `load_score_weighted`, and `service_weighted_occupancy_pct`, the flag `diversion_recommended`, and the elective-scheduling pointer `next_elective_window_start` are all computed fields; their formulas and trigger conditions appear in §3.2 and §3.9.

All percentage and score figures produced by the system use exactly one decimal place, rounded half up. Census projections are exact integers. Selector scoring uses integer arithmetic with no rounding. Numeric fields are represented in responses as JSON numbers, not strings.

### 2.7. Nested Paths and Left-to-Right Existence Validation

Creation endpoints nest child resources under their owning facility, and the API enforces strict left-to-right validation of path identifiers. The first identifier in the path that does not resolve to an existing resource produces that resource type's 404 error — `ERR_FACILITY_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`, `ERR_TRANSFER_REQUEST_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DIVERSION_NOT_FOUND`, `ERR_BOARDING_RECORD_NOT_FOUND`, `ERR_HUDDLE_NOT_FOUND`, or `ERR_FORECAST_NOT_FOUND` as appropriate. A child identifier that exists but belongs to a different facility than the path's facility is reported with the child resource's 404, not the facility's — a bed, physician, admission, or transfer request from another facility is simply "not found" in this context.

### 2.8. Validation Order Across Competing Failures

When a request would fail for several reasons at once, the checks are evaluated in a fixed global order so that the surfaced error is deterministic. Authentication context comes first: missing or empty headers are rejected before anything else, followed by role authorization. Next comes request-body well-formedness — required fields present, types correct, enum values valid — and then resource existence along the path, validated left to right per §2.7. Entity-backed ownership checks run immediately after the resource they guard is found, ahead of its state checks. State-machine eligibility checks run after existence; optimistic-concurrency version comparisons run after state checks. Domain safety rules follow, and where several apply they run in their own pinned order (isolation compatibility, then acuity capability, then service matching; physician credentialing before physician on-call status). Segregation-of-duties checks come after the safety rules, then temporal checks (deadlines and minimum durations), then window-conflict checks, and finally quota and uniqueness constraints.

### 2.9. Optimistic Concurrency Control

Two write operations require the caller to prove it is acting on a current view of the resource it is mutating, by carrying the resource's `version` as last observed by the client.

Creating a bed assignment against a transfer request requires the non-optional field `expected_transfer_request_version`, carrying the transfer request's `version` as the client last read it. If the request's current `version` has advanced since that read — for example because another writer placed or released a hold, each of which legitimately moves the request between `ACCEPTED` and `HOLD_PLACED` and advances its version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from placing a patient against a view of the request it has not observed.

Extending a bed hold requires the non-optional field `expected_bed_hold_version`, carrying the hold's `version` as last observed. Because a successful extension both pushes `expires_at` forward and advances the hold's `version`, an extension carrying a pre-extension version is operating on a stale view and is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; version-bearing inputs exist only on these two operations.

### 2.10. Segregation of Duties

Two sensitive action pairs must be performed by two different operators. A diversion event may only be lifted by a `HouseSupervisor` whose `X-User-ID` differs from the `declared_by_user_id` recorded when the diversion was declared; the same operator attempting both is rejected with `ERR_SOD_DIVERSION_DECLARE_LIFT_SAME_ACTOR` (HTTP 403). A bed assignment may only be completed by a `BedManager` whose `X-User-ID` differs from the assignment's `created_by_user_id`; a violation is rejected with `ERR_SOD_ASSIGNMENT_CREATE_COMPLETE_SAME_ACTOR` (HTTP 403).

### 2.11. Time-Window Semantics: Diversion Windows and Bed Cooling

The system uses two different interval conventions, and confusing them changes behavior at the boundary. Diversion windows are half-open: a diversion declared from `starts_at` to `ends_at` is in effect at `starts_at` itself and ceases to be in effect at `ends_at` itself. Two diversion windows therefore may be adjacent — a new window starting exactly when an existing one ends does not overlap it — and the overlap test is described in §3.7. A diversion is in effect at a given moment when that moment is at or after `starts_at` and strictly before `ends_at`.

Bed cooling, by contrast, blocks a closed span. When a hold ends or a discharge is confirmed, the bed enters a turnover buffer ending at `cooling_until`; a new hold on that bed is rejected precisely while the current time is strictly before `cooling_until`, so a hold placed exactly at the `cooling_until` instant is allowed. The full cooling rule and its interaction with hold placement appear in §3.4 and §3.6.

## 3. Business Logic & Workflows

### 3.1. Provisioning: Facilities, Beds, and the Physician Roster

A `SystemAdministrator` onboards the health system one facility at a time. Creating a facility requires a display `name` and a `region` code that groups sibling facilities for inter-hospital load balancing. A new facility starts with every computed counter at zero, `diversion_status` of `ACCEPTING`, `diversion_recommended` false, and `next_elective_window_start` null.

Beds are registered under a facility with a nursing `unit` label (conventionally something like ICU-1, M-2, or ED-1; any unit whose label begins with the letters ED is an emergency-department unit), a `label` identifying the bed within the unit, a clinical `service`, a `max_acuity` ceiling, and an `isolation_capability`. The service enumeration is `CARDIAC`, `NEURO`, `TRAUMA`, `MEDICAL`, `SURGICAL`, or `ONCOLOGY`; `MEDICAL` beds additionally act as universal overflow in the bed selector described in §3.4. The acuity enumeration, from highest capability to lowest, is `ACUITY_1_CRITICAL`, `ACUITY_2_STEPDOWN`, `ACUITY_3_MEDICAL_SURGICAL`, and `ACUITY_4_OBSERVATION`; a bed accepts patients whose acuity rank is at most the bed's rank. The isolation enumeration, in ascending containment order, is `NONE`, `CONTACT`, `DROPLET`, and `AIRBORNE`; a bed accepts patients whose isolation need ranks no higher than its capability. The optional `staffed` flag defaults to true — unstaffed beds are excluded from load denominators, occupancy figures, and the selector — and the optional `turnover_minutes` cleaning buffer defaults to 45 and, when supplied, must be a non-negative integer. A newly registered bed starts in `AVAILABLE` status, and its `facility_id` ties it permanently to the owning facility.

Bed availability between `AVAILABLE` and `OUT_OF_SERVICE` is managed by a `BedManager` through a status-setting operation accepting a `to_status` of either `AVAILABLE` or `OUT_OF_SERVICE`. The statuses `HELD` and `OCCUPIED` are system-managed through the hold and admission lifecycles and are rejected as targets of this operation with `ERR_INVALID_REQUEST`; a request whose target state is not reachable from the bed's current state (for example, marking a `HELD` bed out of service, or setting a bed to the status it already holds) is rejected with `ERR_BED_NOT_AVAILABLE`. Each successful change recomputes the facility's bed counts and load scores. Beds expose two computed timestamps: `projected_free_at`, which is null unless the occupying admission is `PENDING_DISCHARGE`, in which case it equals that admission's `expected_discharge_at` plus the bed's `turnover_minutes`; and `cooling_until`, which is null unless the bed is in post-hold or post-discharge turnover, in which case it equals the time the hold end or discharge confirmation was processed — the logical-clock time of the release call, the expiring sweep, or the confirmation — plus `turnover_minutes`.

The physician roster is also facility-scoped. Registering a physician records a `full_name`, the list of `services` the physician is credentialed to accept transfers for, and an optional roster `status` that defaults to `ON_CALL` (the alternative is `OFF_CALL`). A `HouseSupervisor` toggles a physician between `ON_CALL` and `OFF_CALL` through a status operation taking `to_status`, which accepts either target regardless of current status (re-setting the status the physician already holds succeeds); consult dispatch, described in §3.3, requires `ON_CALL`.

### 3.2. Reading Capacity: Load Scores, Counters, and Service-Weighted Occupancy

Every facility maintains a live load picture that is recomputed on every mutation touching bed occupancy, holds, boarding waiters, or the inbound transfer pipeline — admission creation and discharge confirmation, hold creation, release, expiry, and consumption, boarding record creation, placement, and departure, transfer intake, cancellation, and completion, the diversion decline cascade, and bed status changes. Consistency is immediate: each mutation's effects are visible in that same request's response.

The counters are defined precisely. `staffed_beds` counts the facility's beds flagged `staffed`, across all units including ED units. `occupied_beds` counts staffed beds in `OCCUPIED` status, `held_beds` counts staffed beds in `HELD` status, and `available_beds` counts staffed beds in `AVAILABLE` status. `out_of_service_beds` counts all beds in `OUT_OF_SERVICE` status regardless of the staffing flag. `boarding_waiters` counts the facility's boarding records whose `placement_status` is `WAITING` or `OFFERED`. `active_inbound_transfers` counts the facility's transfer requests in any non-terminal status: `INTAKE`, `CONSULT_PENDING`, `DECLINED`, `EXPIRED`, `ACCEPTED`, `HOLD_PLACED`, or `ASSIGNED`.

Two occupancy scores are maintained. The raw score, exposed as `load_score_raw` on the facility, is one hundred times the number of staffed `OCCUPIED` beds divided by `staffed_beds`, rounded half-up to one decimal place; it is the variant used for regulatory and dashboard occupancy reporting. The pressure-weighted score, exposed as `load_score_weighted`, builds a pressure numerator in which occupied beds count in full, each staffed `HELD` bed contributes one half, each boarding waiter contributes three quarters, and each inbound transfer in a non-terminal status contributes one half; the score is one hundred times that numerator divided by `staffed_beds`, again rounded half-up to one decimal place. The weighted variant drives diversion recommendation and inter-hospital load balancing, and the two variants diverge whenever any held bed, boarder, or inbound transfer exists. When a facility has no staffed beds at all, both scores are zero and `diversion_recommended` is false. The flag `diversion_recommended` turns true exactly when the weighted score reaches or exceeds 95.0 — a score of 95.0 triggers it, and anything below does not.

A third figure, `service_weighted_occupancy_pct`, summarizes per-service pressure over staffed beds outside ED units. For each service that has at least one staffed non-ED bed, the service's occupancy percentage is computed first — one hundred times its occupied staffed non-ED beds divided by its staffed non-ED beds — and that per-service figure is rounded half-up to one decimal place before any weighting. The per-service figures are then combined: each is multiplied by a fixed service weight — 0.5 for `CARDIAC`, 0.3 for `MEDICAL`, and 0.2 each for `NEURO`, `TRAUMA`, `SURGICAL`, and `ONCOLOGY` — the products are summed, the sum is divided by the sum of the participating services' weights, and the quotient is rounded half-up to one decimal place. Services with no staffed non-ED beds contribute to neither the numerator sum nor the denominator sum. The rounding order is pinned: per-service percentages are rounded first, then the weighted aggregate is rounded; the alternative aggregate-then-round order is documented and explicitly not used, because it yields different values. When no service has any staffed non-ED bed, `service_weighted_occupancy_pct` is 0.0.

A dedicated computed read on the facility returns both score variants and their components in one payload: `raw_occupancy_pct`, `pressure_weighted_pct`, `service_weighted_occupancy_pct`, `diversion_recommended`, `staffed_beds`, `occupied_beds`, `held_beds`, `boarding_waiters`, and `active_inbound_transfers`.

### 3.3. Transfer Intake and the Accepting-Physician Consult Cycle

A `TransferCenterCoordinator` opens a transfer request against a destination facility by supplying the requesting hospital's free-text `source_facility_name`, a de-identified `patient_ref`, the patient's `acuity`, `isolation_need`, and `service`, a `priority` of `EMERGENT`, `URGENT`, or `ELECTIVE`, and an optional `preferred_unit` that later serves only as a small scoring bonus in the selector. The request is created in `INTAKE` status with the coordinator's `X-User-ID` recorded as `intake_coordinator_id`, `consult_count` at zero, and no `accepting_physician_id`, `consult_deadline`, `decline_reason`, or `assigned_bed_id`; the facility's `active_inbound_transfers` and load scores are recomputed. Intake is gated by diversion posture: if the destination facility is in `DIVERT_FULL`, or is in `DIVERT_SERVICE` for a service matching the request's `service`, creation is rejected with `ERR_FACILITY_ON_DIVERSION`.

From `INTAKE` — and again from `DECLINED` or `EXPIRED`, forming the re-consult loop — the coordinator dispatches an accepting-physician consult by naming a `physician_id`. Dispatch validates in a fixed order: the physician must exist within the destination facility (`ERR_PHYSICIAN_NOT_FOUND`); the request must be in `INTAKE`, `DECLINED`, or `EXPIRED` (`ERR_TRANSFER_INVALID_STATE`); the physician must be credentialed for the request's `service`, meaning the service appears in the physician's `services` list (`ERR_PHYSICIAN_NOT_CREDENTIALED_FOR_SERVICE`); and only then is the physician's roster status checked, which must be `ON_CALL` (`ERR_PHYSICIAN_NOT_ON_CALL`). A successful dispatch moves the request to `CONSULT_PENDING`, records the physician as `accepting_physician_id`, sets `consult_deadline` to thirty minutes after the dispatch time, increments `consult_count` by one (re-consult rounds included), clears `decline_reason` to null, and increments the request's `version` by one.

The consulted physician responds through a decision operation carrying `decision` and, when declining, a `decline_reason`. Only the physician whose `id` equals the request's `accepting_physician_id` may respond — an `AcceptingPhysician` caller whose `X-User-ID` does not match is rejected with `ERR_INSUFFICIENT_PERMISSIONS` — and the response must arrive while the current time is still strictly before `consult_deadline`; a response arriving at or after the deadline is rejected with `ERR_CONSULT_WINDOW_EXPIRED`, and responding from any status other than `CONSULT_PENDING` is rejected with `ERR_TRANSFER_INVALID_STATE`. Per §2.8, the entity-backed ownership comparison runs before the state check and compares against the recorded `accepting_physician_id` whatever the request's status; a null `accepting_physician_id` — the case in every status in which no consult is outstanding, such as `INTAKE`, `DECLINED`, `EXPIRED`, or a terminal status — equals no physician's `id`, so a respond attempt made while no physician is recorded is rejected with `ERR_INSUFFICIENT_PERMISSIONS` rather than a state error. An `ACCEPT` decision moves the request to `ACCEPTED`, clears `consult_deadline`, and increments `version`. A `DECLINE` decision moves the request to `DECLINED`, records the physician-supplied `decline_reason` — one of `PHYSICIAN_DECLINED`, `NO_CAPACITY`, or `CLINICAL` — clears `accepting_physician_id` and `consult_deadline`, and increments `version`; from `DECLINED` (or `EXPIRED`) the coordinator may dispatch a fresh consult to the same or a different physician.

Two system-driven outcomes close a consult without a physician response. If a sweep observes the current time at or past `consult_deadline`, the request moves from `CONSULT_PENDING` to `EXPIRED` with `decline_reason` set to `TIMEOUT`, and `accepting_physician_id` and `consult_deadline` are cleared. And if a full diversion is declared on the destination facility while the request is in `INTAKE` or `CONSULT_PENDING`, the diversion cascade described in §3.7 moves it to `DECLINED` with `decline_reason` set to `DIVERSION`. The full set of decline reasons is therefore `DIVERSION`, `NO_CAPACITY`, `CLINICAL`, `PHYSICIAN_DECLINED`, and `TIMEOUT`, the first and last being system-assigned.

A coordinator may cancel a request from any non-terminal status — `INTAKE`, `CONSULT_PENDING`, `DECLINED`, `EXPIRED`, `ACCEPTED`, `HOLD_PLACED`, or `ASSIGNED` — moving it to the terminal `CANCELLED` status; cancelling a terminal request is rejected with `ERR_TRANSFER_INVALID_STATE`. Cancellation clears `accepting_physician_id` and `consult_deadline` and increments `version`. If the request was `HOLD_PLACED`, its `ACTIVE` hold is released as a side effect, with the same bed-cooling consequences as a manual release (§3.4); the release's fall-back to `ACCEPTED` and the cancellation itself each advance the request's `version`, so cancelling from `HOLD_PLACED` increments `version` twice. Facility load scores are recomputed.

### 3.4. Holding Beds: The Selector, Quotas, Cooling, and the Hold Lifecycle

Once a request is `ACCEPTED`, a `TransferCenterCoordinator` places a bed hold for it; attempting placement from any other status is rejected with `ERR_TRANSFER_INVALID_STATE`. The hold request carries an optional `bed_id` and an optional `ttl_minutes`, the latter, when supplied, required to be a positive integer. When `bed_id` is given, the chosen bed is validated explicitly; when it is omitted, the server runs the bed selector over the facility's beds and places the hold on the top-ranked candidate.

Eligibility is identical in both modes and has four clauses beyond basic availability: the bed must be `AVAILABLE`, flagged `staffed`, and outside ED units (its `unit` label must not begin with ED); its `max_acuity` rank must be at least the request's acuity rank, using the ranks one through four from `ACUITY_4_OBSERVATION` up to `ACUITY_1_CRITICAL`; its `isolation_capability` rank must be at least the request's `isolation_need` rank, using the ranks zero through three from `NONE` up to `AIRBORNE`; and its `service` must either equal the request's `service` or be `MEDICAL`, the universal overflow. In selector mode, ineligible beds are silently excluded from the candidate pool. In explicit mode, failures map to errors in a pinned order — after the state check that the bed is available, staffed, and non-ED (`ERR_BED_NOT_AVAILABLE`), isolation compatibility is checked first (`ERR_ISOLATION_INCOMPATIBLE`), then acuity capability (`ERR_ACUITY_EXCEEDS_BED_CAPABILITY`), then service match (`ERR_SERVICE_MISMATCH`).

The selector scores each eligible bed with integer arithmetic: one thousand points when the bed's service exactly matches the request's service; an acuity-fit component computed as four minus the number of ranks by which the bed's `max_acuity` exceeds the request's `acuity`, multiplied by one hundred points, so an exact acuity match earns four hundred points and each rank of headroom costs one hundred; ten points when the bed's isolation capability exactly equals the request's isolation need; and five points when the request names a `preferred_unit` and the bed's `unit` equals it. Candidates are ordered by score descending, with ties broken by the bed's `created_at`, earliest first — never by bed id — and beds created at the same logical-clock instant keep registration order. The candidate list may legitimately be empty: the bed-candidates read, which takes a `transfer_request_id` and applies the same eligibility, scoring, and ordering, returns an object with a `candidates` array — empty in that case — whose entries are the full bed representation plus the integer `score` the selector assigned, while hold placement with an omitted `bed_id` and an empty pool is rejected with `ERR_NO_ELIGIBLE_BED`. The bed-candidates read is not paginated; a missing `transfer_request_id` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and one that is unknown or belongs to another facility is rejected with `ERR_TRANSFER_REQUEST_NOT_FOUND` (HTTP 404).

Two facility-wide and bed-local guards sit outside eligibility. A facility may carry at most six `ACTIVE` holds at one time: with six already active the quota is full — the sixth hold succeeds and a seventh is rejected with `ERR_HOLD_QUOTA_EXCEEDED`. And the bed's cooling buffer must have cleared: after a hold ends or a discharge confirms, the bed cools until `cooling_until`, and a new hold arriving while the current time is strictly before `cooling_until` is rejected with `ERR_BED_HOLD_WINDOW_CONFLICT`; arrival exactly at `cooling_until` is permitted. These guards apply in both explicit and selector mode, after the safety checks above. In explicit mode the cooling check runs before the quota check. In selector mode the quota is evaluated before candidate selection begins, and the cooling check then applies to the single top-ranked candidate: if that candidate is still cooling, the placement is rejected with `ERR_BED_HOLD_WINDOW_CONFLICT` rather than falling through to lower-ranked candidates.

A created hold records its `bed_id`, the `transfer_request_id` it serves, a `starts_at` equal to the logical-clock time of creation, the effective `ttl_minutes` (defaulting to 60 when omitted), an `expires_at` equal to `starts_at` plus `ttl_minutes`, an `extend_count` of zero, and `ACTIVE` status. Its creation moves the bed from `AVAILABLE` to `HELD` (clearing any `cooling_until`), moves the request from `ACCEPTED` to `HOLD_PLACED` with a version increment, and recomputes the facility's bed counts and load scores. A hold expires when the current time reaches or passes `expires_at` — expiry happens exactly at the deadline — which a sweep detects and processes.

While `ACTIVE`, a hold supports three outcomes besides placement. A coordinator may extend it: the extension request must carry `expected_bed_hold_version` per §2.9, the hold must be `ACTIVE` (`ERR_HOLD_INVALID_STATE`), and its `extend_count` must still be below two — the hard cap — so a third extension is rejected with `ERR_HOLD_EXTEND_LIMIT_EXCEEDED`. Each successful extension pushes `expires_at` forward by thirty minutes, increments `extend_count`, and increments the hold's `version`. A coordinator may instead release the hold, moving it to `RELEASED`. Or a sweep may expire it, moving it to `EXPIRED`. Release and expiry have identical downstream effects: the bed returns from `HELD` to `AVAILABLE` with `cooling_until` set to the time the release or expiry is processed plus the bed's `turnover_minutes`, the served request falls back from `HOLD_PLACED` to `ACCEPTED` with a version increment (the placement loop reopens), and facility counts and load scores are recomputed. The fourth outcome, consumption by a bed assignment, is the subject of §3.5; a consumed hold leaves the bed `HELD` pending the patient's arrival.

### 3.5. From Hold to Arrival: Assignment, Completion, and Segregation of Duties

Placement converts a hold into a commitment. A `TransferCenterCoordinator` creates a bed assignment against a `HOLD_PLACED` request by supplying the `bed_hold_id` of the hold to consume together with `expected_transfer_request_version` per §2.9; an unknown `bed_hold_id` is rejected with `ERR_HOLD_NOT_FOUND` (HTTP 404). State validation runs before the version comparison: the request must be in `HOLD_PLACED` (`ERR_TRANSFER_INVALID_STATE`), and the referenced hold must be `ACTIVE` and belong to this request (`ERR_HOLD_INVALID_STATE`); only then is `expected_transfer_request_version` compared against the request's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). A successful creation produces a bed assignment in `PLACED` status with the coordinator's `X-User-ID` recorded as `created_by_user_id` and the `bed_id` copied from the consumed hold; it moves the request from `HOLD_PLACED` to `ASSIGNED` with `assigned_bed_id` set and `version` incremented, and it moves the hold to the terminal `CONSUMED` status while the bed remains `HELD`.

When the patient physically arrives, a `BedManager` completes the assignment. The assignment must be `PLACED`; completing from any other status is rejected with `ERR_INVALID_STATE`. Segregation of duties applies per §2.10: the completing operator's `X-User-ID` must differ from the assignment's `created_by_user_id`, or the completion is rejected with `ERR_SOD_ASSIGNMENT_CREATE_COMPLETE_SAME_ACTOR`. Completion stamps `completed_at`, moves the assignment to `COMPLETED`, moves the transfer request from `ASSIGNED` to its terminal `COMPLETED` status with a version increment, moves the bed from `HELD` to `OCCUPIED`, and creates a new admission in `ADMITTED` status on that bed carrying the transfer request's `patient_ref`, `acuity`, `isolation_need`, and `service`. Facility counts and load scores are recomputed.

### 3.6. Admissions, Pending Discharges, and Bed Turnover

Independent of the transfer pipeline, a `BedManager` may direct-admit a patient into a facility by naming the target `bed_id` along with `patient_ref`, `acuity`, `isolation_need`, and `service`. The bed must belong to the same facility — a `bed_id` that is unknown or belongs to another facility is rejected with `ERR_BED_NOT_FOUND` (HTTP 404) per §2.7 — and be both `AVAILABLE` and staffed; any other availability failure is rejected with `ERR_BED_NOT_AVAILABLE`. A successful admission starts in `ADMITTED` status, moves the bed from `AVAILABLE` to `OCCUPIED`, clears any `cooling_until`, and recomputes facility counts and load scores.

Discharge is a two-milestone process. Marking an admission pending discharge requires the admission to be `ADMITTED` (`ERR_ADMISSION_INVALID_STATE`) and records two inputs — the `expected_discharge_at` timestamp and the `discharge_order_signed` flag, the latter optional and defaulting to false — while stamping `pending_discharge_at` with the current time. The occupied bed's `projected_free_at` becomes `expected_discharge_at` plus the bed's `turnover_minutes`, giving the command center forward visibility into soon-to-free beds. Confirming the discharge requires `PENDING_DISCHARGE` (`ERR_ADMISSION_INVALID_STATE`), stamps `confirmed_discharge_at`, moves the admission to the terminal `DISCHARGED` status, and frees the bed: the bed returns from `OCCUPIED` to `AVAILABLE`, its `projected_free_at` is cleared to null, and `cooling_until` is set to the confirmation time plus `turnover_minutes`, during which §3.4's cooling rule blocks new holds. If the patient ends up staying, rescinding the pending discharge requires `PENDING_DISCHARGE` and returns the admission to `ADMITTED`, clearing `pending_discharge_at`, `expected_discharge_at`, and `discharge_order_signed` (reset to false) and nulling the bed's `projected_free_at`.

Each of these three milestones is a bed-availability mutation, and all three trigger the forecast-staleness cascade described in §3.9: the facility's latest `PUBLISHED` capacity forecast is marked `stale`, and the facility's `next_elective_window_start` is nulled until a fresh publish. The signed/unsigned distinction recorded at pending-discharge time matters downstream: signed discharge orders feed the committed census variant while unsigned ones feed only the provisional variant, per §3.9.

### 3.7. Diversion Posture and Inter-Hospital Load Balancing

A `HouseSupervisor` declares a diversion window on a facility by supplying a `level` of `FULL` or `SERVICE`, the window bounds `starts_at` and `ends_at`, and — exactly when the level is `SERVICE` — the affected `service`. Supplying a `service` for a `FULL` diversion, or omitting it for a `SERVICE` diversion, is rejected with `ERR_INVALID_REQUEST`, as is a window whose `ends_at` is not strictly later than its `starts_at`. The window must not overlap any other `ACTIVE` diversion of the same facility: overlap means the new window starts before the existing window ends and the existing window starts before the new window ends, evaluated under the half-open convention of §2.11, so adjacent windows that merely touch at a boundary are allowed. An overlap is rejected with `ERR_DIVERSION_WINDOW_OVERLAP`. A declared diversion starts in `ACTIVE` status with `declared_by_user_id` set to the supervisor's `X-User-ID`.

The facility's `diversion_status` is derived after every diversion create, lift, or expiry: it is `DIVERT_FULL` when any `ACTIVE` `FULL` diversion's window contains the current time; otherwise `DIVERT_SERVICE` when any `ACTIVE` `SERVICE` diversion's window contains the current time; otherwise `ACCEPTING`. Entering `DIVERT_FULL` has teeth: the cascade is evaluated at declaration time, at the moment the newly declared window moves the facility into `DIVERT_FULL` — every transfer request of the facility sitting in `INTAKE` or `CONSULT_PENDING` is moved to `DECLINED` with `decline_reason` set to `DIVERSION`, `accepting_physician_id` cleared, and `consult_deadline` cleared, after which `active_inbound_transfers` and the load scores are recomputed. `DIVERT_SERVICE` carries no such cascade; it blocks new intake for the named service per §3.3. While a facility is in either diversion posture, transfer intake (and rebalance targeting, below) is refused with `ERR_FACILITY_ON_DIVERSION`.

A diversion ends in one of two ways. A `HouseSupervisor` may lift an `ACTIVE` diversion — lifting from any other status is rejected with `ERR_DIVERSION_INVALID_STATE` — subject to two further guards evaluated in order: the lifting operator must differ from `declared_by_user_id` (`ERR_SOD_DIVERSION_DECLARE_LIFT_SAME_ACTOR`), and at least thirty minutes must have elapsed since the diversion's `created_at`, with an earlier attempt rejected as `ERR_DIVERSION_LIFT_TOO_SOON`. A successful lift stamps `lifted_at`, records `lifted_by_user_id`, moves the event to `LIFTED`, and recomputes `diversion_status`. Alternatively, a sweep observing the current time at or past `ends_at` moves the event to `EXPIRED` and recomputes `diversion_status` the same way; expiry occurs exactly at the window's end.

Load balancing redirects demand between sibling facilities in the same health system. A `TransferCenterCoordinator` may rebalance a request to a `target_facility_id` while the request is in `INTAKE`, `CONSULT_PENDING`, `DECLINED`, or `EXPIRED` — any other status is rejected with `ERR_TRANSFER_INVALID_STATE`. An unknown `target_facility_id` is rejected with `ERR_FACILITY_NOT_FOUND` (HTTP 404). The target facility must be `ACCEPTING` (`ERR_FACILITY_ON_DIVERSION`), and the pressure margin must be decisive: the source facility's `load_score_weighted` minus the target facility's `load_score_weighted` must be at least 10.0, with a margin of exactly 10.0 permitted; anything smaller is rejected with `ERR_REBALANCE_MARGIN_NOT_MET`. A successful rebalance repoints the request's `facility_id` to the target, resets the request to `INTAKE`, clears `accepting_physician_id`, `consult_deadline`, and `decline_reason`, retains `consult_count`, increments `version`, and recomputes load scores on both facilities.

### 3.8. ED Boarding, Heartbeats, and Escalation Huddles

When a patient admitted through the emergency department is waiting for an inpatient bed, a `TransferCenterCoordinator` opens a boarding record by naming the `admission_id`. The admission's bed must be in an ED unit — its bed's `unit` label beginning with ED — or creation is rejected with `ERR_ADMISSION_NOT_ED_BOARDER`; and an admission may have at most one open boarding record, where open means `placement_status` of `WAITING` or `OFFERED`, with a second attempt rejected as `ERR_BOARDING_RECORD_ALREADY_OPEN`. A new record starts with `placement_status` of `WAITING`, `escalation_status` of `NONE`, `started_at` set to the logical-clock time, `last_heartbeat_minutes` null, and `executive_escalation` false; the facility's `boarding_waiters` and load scores are recomputed.

Boarding duration is tracked in whole minutes. The record's `boarding_minutes` is the greater of two components: the heartbeat component — `last_heartbeat_minutes`, or zero until the first heartbeat — and the clock component, the whole minutes elapsed between `started_at` and now, any partial minute discarded. Coordinators report observed durations through heartbeats carrying `observed_minutes`, which must be a non-negative integer; heartbeats are monotonic, so a value lower than the last accepted heartbeat is rejected with `ERR_INVALID_REQUEST`, and heartbeat on a record whose placement has closed is rejected with `ERR_BOARDING_INVALID_STATE`. Each accepted heartbeat stores `observed_minutes` as `last_heartbeat_minutes` and recomputes `boarding_minutes`.

Escalation runs as a dimension parallel to placement. Whenever a heartbeat or a sweep evaluates the check, if the record's placement is `WAITING` or `OFFERED`, its escalation status is `NONE` or `HUDDLE_RESOLVED`, and `boarding_minutes` has reached at least 120 minutes — two hours — the system calls an escalation huddle automatically: an `EscalationHuddle` is created in `CALLED` status with `trigger_reason` of `AUTO_THRESHOLD`, and the record's `escalation_status` becomes `HUDDLE_CALLED`. A boarding time of 119 minutes does not trigger; 120 does. Separately, whenever `boarding_minutes` reaches at least 240 minutes — four hours — the record's `executive_escalation` flag is set true. A `HouseSupervisor` may also call a huddle manually at any time the record's escalation status is not already `HUDDLE_CALLED` (`ERR_HUDDLE_INVALID_STATE`) and its placement is still open (`ERR_BOARDING_INVALID_STATE`), with the placement-open check evaluated first when both fail; a manual huddle is created `CALLED` with `trigger_reason` of `MANUAL`. Each huddle records its `boarding_record_id` and a `called_at` timestamp.

Resolving a huddle is also a `HouseSupervisor` action, requires the huddle to be `CALLED` (`ERR_HUDDLE_INVALID_STATE`), and accepts an optional free-text `resolution` note. Resolution stamps `resolved_at`, moves the huddle to `RESOLVED`, returns the boarding record's `escalation_status` from `HUDDLE_CALLED` to `HUDDLE_RESOLVED`, and recomputes `huddle_count_24h` — the count of this record's huddles whose `called_at` falls at or after the time exactly 24 hours before now, the boundary included. When that count reaches three, `executive_escalation` is set true. Because resolution returns escalation to `HUDDLE_RESOLVED`, a record whose boarding continues can escalate again: the 120-minute check fires anew on a later heartbeat or sweep, producing another huddle in a cyclic loop.

Placement progresses on its own track. A coordinator offers an inpatient bed to a waiting boarder, moving `placement_status` from `WAITING` to `OFFERED` (offering from any other status is rejected with `ERR_BOARDING_INVALID_STATE`); placement into the bed moves it from `OFFERED` to `PLACED` (likewise guarded by `ERR_BOARDING_INVALID_STATE`); and a patient who leaves against medical advice moves from `WAITING` or `OFFERED` to `LEFT_AMA`. `PLACED` and `LEFT_AMA` are terminal. Placement and departure both remove the record from the waiter set, so `boarding_waiters` and load scores are recomputed at each.

### 3.9. Capacity Forecasts and Elective Scheduling Windows

A `CapacityPlanner` generates a capacity forecast for a facility by supplying `horizon_hours`, the number of hours to project, between 1 and 72. Generation stamps `generated_at` with the logical-clock time and computes, for every hour h from 1 through `horizon_hours`, two variants of the projected inpatient census, stored on the forecast as `variant_snapshots` — an object with a `committed` array and a `provisional` array, each holding one integer per hour. Hour h maps to the instant `generated_at` plus h hours.

Both variants share the same base: the count of `OCCUPIED` staffed beds outside ED units, the current inpatient census. From that base, each hour subtracts the pending discharges expected to complete by that hour — admissions in `PENDING_DISCHARGE` whose beds are outside ED units and whose `expected_discharge_at` falls at or before `generated_at` plus h hours, the boundary included. The committed variant subtracts only pending discharges whose `discharge_order_signed` is true. The provisional variant additionally subtracts those with unsigned orders and adds back expected ED conversions: the facility's current `boarding_waiters` multiplied by 0.8, rounded up to a whole number, the same addition in every hour. The committed variant therefore gives the stricter view used for compliance reporting, while the provisional variant is the planning view; the two diverge whenever unsigned pending discharges or boarding waiters exist.

Each forecast also carries two summary percentages. `occupancy_pct_committed` is one hundred times the mean of the committed per-hour census values over the horizon, divided by the facility's inpatient bed count — the number of staffed beds outside ED units — rounded half-up to one decimal place; `occupancy_pct_provisional` is the same computation over the provisional values. When the inpatient bed count is zero, both percentages are zero.

Forecast lifecycles enforce a single current document. A new forecast starts `PROVISIONAL` with `stale` false, and its creation supersedes every prior `PROVISIONAL` or `PUBLISHED` forecast of the same facility, moving them to the terminal `SUPERSEDED` status. Publishing — restricted to a `PROVISIONAL` forecast, with attempts otherwise rejected as `ERR_FORECAST_INVALID_STATE` — moves the forecast to `PUBLISHED`, stamps `published_at`, and recomputes the facility's `next_elective_window_start`: the earliest hour h whose provisional census is at most the inpatient bed count minus a two-bed elective buffer, expressed as `generated_at` plus h hours, or null when no hour in the horizon qualifies. When the superseded forecast was the facility's latest published one, `next_elective_window_start` is recomputed from the surviving latest `PUBLISHED` non-stale forecast, or set null when none survives; throughout this section the *latest* forecast of a given kind is the most recently created one.

Published forecasts are kept honest by staleness tracking. Whenever bed availability mutates — a pending-discharge mark, a pending-discharge rescind, or a discharge confirmation, per §3.6 — the facility's latest `PUBLISHED` forecast is marked `stale` true; `PROVISIONAL` forecasts are never marked stale. Because `next_elective_window_start` reads only non-stale published forecasts, the same mutation also nulls it, and it remains null until a fresh publish. The field is therefore null whenever the facility has no `PUBLISHED` non-stale forecast or no qualifying hour exists.

## 4. Endpoint Definitions

Operations that create a new resource — a facility, bed, physician, admission, transfer request, bed hold, bed assignment, diversion event, boarding record, escalation huddle, or capacity forecast — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. All responses follow the envelope in §2.2, and list endpoints follow the pagination rules in §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cc/facilities` | Create a facility | SystemAdministrator |
| GET | `/cc/facilities/{id}` | Get a facility with all computed load fields | Any |
| GET | `/cc/facilities/{id}/load-score` | Computed read: both load-score variants plus components | Any |
| GET | `/cc/facilities/{id}/bed-candidates` | Ranked eligible beds for a transfer request | Any |
| POST | `/cc/facilities/{id}/diversions` | Declare a diversion window | HouseSupervisor |
| GET | `/cc/facilities/{id}/diversions` | List diversion events of a facility | Any |
| POST | `/cc/diversions/{id}/lift` | Lift an active diversion | HouseSupervisor |
| POST | `/cc/facilities/{id}/beds` | Register a bed | SystemAdministrator |
| GET | `/cc/facilities/{id}/beds` | List beds of a facility (filterable by `status` and `service`) | Any |
| GET | `/cc/beds/{id}` | Get a bed | Any |
| POST | `/cc/beds/{id}/status` | Move a bed between AVAILABLE and OUT_OF_SERVICE | BedManager |
| GET | `/cc/beds/{id}/admissions` | List admissions occupying or formerly occupying a bed | Any |
| GET | `/cc/beds/{id}/bed-holds` | List holds placed on a bed | Any |
| GET | `/cc/beds/{id}/transfer-requests` | List transfer requests assigned to a bed | Any |
| POST | `/cc/facilities/{id}/physicians` | Register a physician on the on-call roster | SystemAdministrator |
| GET | `/cc/facilities/{id}/physicians` | List physicians of a facility | Any |
| GET | `/cc/physicians/{id}` | Get a physician | Any |
| POST | `/cc/physicians/{id}/status` | Set a physician ON_CALL or OFF_CALL | HouseSupervisor |
| GET | `/cc/physicians/{id}/transfer-requests` | List transfer requests accepted by a physician | Any |
| POST | `/cc/facilities/{id}/admissions` | Direct-admit a patient into an available staffed bed | BedManager |
| GET | `/cc/facilities/{id}/admissions` | List admissions of a facility | Any |
| GET | `/cc/admissions/{id}` | Get an admission | Any |
| POST | `/cc/admissions/{id}/pending-discharge` | Mark an admission pending discharge | BedManager |
| POST | `/cc/admissions/{id}/confirm-discharge` | Confirm a discharge, freeing the bed | BedManager |
| POST | `/cc/admissions/{id}/rescind-pending-discharge` | Rescind a pending discharge | BedManager |
| GET | `/cc/admissions/{id}/boarding-records` | List boarding records of an admission | Any |
| POST | `/cc/facilities/{id}/transfer-requests` | Transfer request intake | TransferCenterCoordinator |
| GET | `/cc/facilities/{id}/transfer-requests` | List transfer requests of a facility | Any |
| GET | `/cc/transfer-requests/{id}` | Get a transfer request | Any |
| POST | `/cc/transfer-requests/{id}/consult` | Dispatch an accepting-physician consult (also re-consult) | TransferCenterCoordinator |
| POST | `/cc/transfer-requests/{id}/consult-response` | Accept or decline a consult | AcceptingPhysician |
| POST | `/cc/transfer-requests/{id}/cancel` | Cancel a non-terminal transfer request | TransferCenterCoordinator |
| POST | `/cc/transfer-requests/{id}/rebalance` | Redirect a request to a sibling facility | TransferCenterCoordinator |
| POST | `/cc/transfer-requests/{id}/bed-holds` | Place a bed hold for an accepted request | TransferCenterCoordinator |
| GET | `/cc/transfer-requests/{id}/bed-holds` | List holds of a transfer request | Any |
| GET | `/cc/bed-holds/{id}` | Get a bed hold | Any |
| POST | `/cc/bed-holds/{id}/extend` | Extend an active hold by thirty minutes | TransferCenterCoordinator |
| POST | `/cc/bed-holds/{id}/release` | Release an active hold | TransferCenterCoordinator |
| GET | `/cc/bed-holds/{id}/bed-assignments` | List assignments consuming a hold | Any |
| POST | `/cc/transfer-requests/{id}/bed-assignments` | Convert an active hold into a placement | TransferCenterCoordinator |
| GET | `/cc/transfer-requests/{id}/bed-assignments` | List assignments of a transfer request | Any |
| GET | `/cc/beds/{id}/bed-assignments` | List assignments placed on a bed | Any |
| POST | `/cc/bed-assignments/{id}/complete` | Confirm patient arrival and complete the assignment | BedManager |
| POST | `/cc/facilities/{id}/boarding-records` | Open a boarding record for an ED admission | TransferCenterCoordinator |
| GET | `/cc/facilities/{id}/boarding-records` | List boarding records of a facility (filterable by `placement_status`) | Any |
| GET | `/cc/boarding-records/{id}` | Get a boarding record | Any |
| POST | `/cc/boarding-records/{id}/heartbeat` | Report observed boarding minutes | TransferCenterCoordinator |
| POST | `/cc/boarding-records/{id}/offer` | Offer an inpatient bed to a waiting boarder | TransferCenterCoordinator |
| POST | `/cc/boarding-records/{id}/place` | Mark a boarder placed in an inpatient bed | TransferCenterCoordinator |
| POST | `/cc/boarding-records/{id}/leave-ama` | Record a patient leaving against medical advice | TransferCenterCoordinator |
| POST | `/cc/boarding-records/{id}/huddles` | Manually call an escalation huddle | HouseSupervisor |
| GET | `/cc/boarding-records/{id}/huddles` | List huddles of a boarding record | Any |
| POST | `/cc/huddles/{id}/resolve` | Resolve a called huddle | HouseSupervisor |
| POST | `/cc/facilities/{id}/capacity-forecasts` | Generate a capacity forecast (both census variants) | CapacityPlanner |
| GET | `/cc/facilities/{id}/capacity-forecasts` | List forecasts of a facility | Any |
| GET | `/cc/capacity-forecasts/{id}` | Get a forecast with variant snapshots | Any |
| POST | `/cc/capacity-forecasts/{id}/publish` | Publish a provisional forecast | CapacityPlanner |
| POST | `/cc/_clock/set_current_utc` | Set the server's logical clock | SystemAdministrator |
| POST | `/cc/_sweeps/run` | Run one housekeeping sweep | SystemAdministrator |

List endpoints accept the optional query parameters `limit` and `offset` per §2.3, plus the filters shown above; diversion, physician, admission, transfer-request, hold, assignment, huddle, and forecast lists also accept an optional `status` filter, and the bed-candidates read takes a `transfer_request_id` parameter.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_BED_NOT_FOUND` | 404 Not Found |
| `ERR_PHYSICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_ADMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DIVERSION_NOT_FOUND` | 404 Not Found |
| `ERR_BOARDING_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_HUDDLE_NOT_FOUND` | 404 Not Found |
| `ERR_FORECAST_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_INVALID_STATE` | 409 Conflict |
| `ERR_BED_NOT_AVAILABLE` | 409 Conflict |
| `ERR_ADMISSION_INVALID_STATE` | 409 Conflict |
| `ERR_ADMISSION_NOT_ED_BOARDER` | 409 Conflict |
| `ERR_BOARDING_INVALID_STATE` | 409 Conflict |
| `ERR_HUDDLE_INVALID_STATE` | 409 Conflict |
| `ERR_FORECAST_INVALID_STATE` | 409 Conflict |
| `ERR_DIVERSION_INVALID_STATE` | 409 Conflict |
| `ERR_HOLD_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ISOLATION_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_ACUITY_EXCEEDS_BED_CAPABILITY` | 422 Unprocessable Entity |
| `ERR_SERVICE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PHYSICIAN_NOT_CREDENTIALED_FOR_SERVICE` | 422 Unprocessable Entity |
| `ERR_PHYSICIAN_NOT_ON_CALL` | 409 Conflict |
| `ERR_SOD_DIVERSION_DECLARE_LIFT_SAME_ACTOR` | 403 Forbidden |
| `ERR_SOD_ASSIGNMENT_CREATE_COMPLETE_SAME_ACTOR` | 403 Forbidden |
| `ERR_CONSULT_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_DIVERSION_LIFT_TOO_SOON` | 409 Conflict |
| `ERR_DIVERSION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BED_HOLD_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_HOLD_QUOTA_EXCEEDED` | 409 Conflict |
| `ERR_BOARDING_RECORD_ALREADY_OPEN` | 409 Conflict |
| `ERR_HOLD_EXTEND_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_FACILITY_ON_DIVERSION` | 409 Conflict |
| `ERR_REBALANCE_MARGIN_NOT_MET` | 409 Conflict |
| `ERR_NO_ELIGIBLE_BED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
