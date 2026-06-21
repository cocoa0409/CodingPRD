# Dialysis Center Scheduling API — Product Requirements Document

## 1. Introduction

Outpatient hemodialysis runs on a relentless rhythm. Most patients with end-stage renal disease must be dialyzed three times a week, on a fixed recurring pattern, in a chair that is bolted to a specific machine, during a specific shift of the day. A modest clinic juggles a finite pool of chairs and machines against dozens of standing patients, visiting "transient" guests passing through town, nephrologist treatment orders that change over time, monthly lab draws, no-show tracking that can suspend a chronically absent patient, and door-to-door medical transport. This API is the system of record that coordinates all of it.

The platform models the clinic's physical inventory (shifts, machines, stations), its clinical population (resident and transient patients), the nephrologist orders that authorize treatment, the standing reservations and individual treatment sessions that consume chair capacity, the lab and transport logistics that wrap around each session, and the billing ledger that ultimately bills each patient's coinsurance. Four operator roles divide the work: a **ClinicAdmin** runs the facility and its equipment, a **Scheduler** owns reservations and the day-to-day session board, a **Nephrologist** owns treatment orders and lab prescriptions, and a **BillingClerk** turns completed care into money. Because chairs are scarce and double-booking a dialysis station has real clinical consequences, the system treats capacity arbitration, infection-control isolation, machine disinfection turnover, and dialyzer reuse limits as first-class safety rules rather than afterthoughts.

This document specifies the complete behavioral contract: the resource model, the parallel clinical and billing state machines that govern a session, the cascade rules that ripple through reservations and ledgers when an order is revoked, the pricing and adherence calculations, and the validation order that decides which error a malformed request earns. The benchmark implementation must satisfy every rule described here.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400) before any other processing. If the headers are present but the role named in `X-User-Role` is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly four roles, spelled precisely as follows: `ClinicAdmin`, `Scheduler`, `Nephrologist`, and `BillingClerk`. Their authority is scoped by operation; §4 names the authorized role(s) for every endpoint, and the workflow narratives in §3 describe who drives each transition.

All four roles are **opaque operator identities**. When `X-User-Role` is `ClinicAdmin`, `Scheduler`, `Nephrologist`, or `BillingClerk`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity in this system. The server may log it for audit purposes, but it never compares `X-User-ID` against any resource's `id` or foreign key; there is no per-patient or per-clinic ownership check keyed off the caller's identity. Authorization is decided purely by whether the role is permitted to perform the operation. All four roles may perform every read (`GET`) operation in the system.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100; the `offset` defaults to 0 and is the count of records to skip from the front of the result. Results are always sorted by `created_at` in ascending order, so the oldest record appears first. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (a boolean that is true when records remain beyond the current page). Where a list endpoint also accepts domain filters (for example a `clinic_id` or `patient_id` filter), those filters narrow the matching set before pagination is applied.

### 2.4. Common Resource Properties and Identifiers

Every resource is assigned a server-minted `id`, which is a UUID string carrying no type prefix. Every resource also records a `created_at` timestamp at creation. All entities in this system carry the full set of common fields: in addition to `id` and `created_at`, each resource also has an `updated_at` timestamp and an integer `version`. The `version` begins at 1 when the resource is created and increments by exactly 1 on every mutation that changes the resource; the `updated_at` timestamp is refreshed to the current clock value on every such mutation. All timestamps are ISO 8601 in UTC with three fractional digits. The `time_zone` recorded on a clinic is an informational IANA label only — it does not shift any stored timestamp, which always remains UTC.

Foreign-key fields named throughout this document (such as `clinic_id`, `patient_id`, `order_id`, `station_id`, `shift_id`, `machine_id`, `standing_slot_id`, `session_id`, and `rescheduled_from_id`) hold the `id` of the referenced resource. When a resource is fetched or mutated by a path identifier, that path identifier is validated left to right: for any endpoint whose URL names a resource id, the named resource must exist or the request fails with that resource's not-found error (for example `ERR_CLINIC_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_LAB_NOT_FOUND`, or `ERR_STATEMENT_NOT_FOUND`), each at HTTP 404.

### 2.5. Clinic Scoping and Referential Integrity

Most resources belong to a clinic. For a clinic-derived child such as a nephrologist order, standing slot, treatment session, lab order, or monthly statement, the `clinic_id` is not supplied by the client — it is copied from the referenced patient at creation time. A transport trip likewise copies its `patient_id` from the session it serves. When a create payload carries foreign-key references, those references must not only exist but must resolve to entities in the **same clinic**. A body foreign key that points at a missing entity, or at an entity belonging to a different clinic, is rejected with `ERR_CROSS_CLINIC_REFERENCE` (HTTP 422). This same-clinic rule governs the creation of sessions, standing slots, stations, orders, transport trips, and lab orders.

### 2.6. Money, Counts, and Rounding

All monetary amounts in the system are stored as **integer cents** — there are no fractional-cent values anywhere. Whenever a charge is computed from a fractional multiplier (a payer discount, a coinsurance fraction, or a shared-ride multiplier), the result is rounded to whole cents using the round-half-up convention, meaning a value whose fractional part is exactly one half rounds away from zero to the next whole cent. The precise point at which each rounding occurs is part of the calculation contracts in §3 and matters: some totals round each component before summing rather than summing then rounding. Adherence percentages are the one non-monetary computed figure; they are expressed to one decimal place, also using round-half-up.

### 2.7. Optimistic Concurrency on Patient Reservations

Two creation operations — reserving a standing slot and booking a treatment session — compete for finite chair-and-shift capacity tied to a patient, and both are guarded by optimistic concurrency control on the patient record. A request to reserve a standing chair/shift slot must include a non-optional `expected_patient_version` field carrying the `version` of the patient that the client last observed. If that value does not equal the patient's current `version`, the reservation is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412): another writer has advanced the patient's version since the client read it, so the reservation is refused as stale rather than allowed to double-book the chair. A successful standing-slot reservation increments the patient's `version` by 1, so a second create still carrying the previously observed version will be caught as stale.

The same guard applies to booking a treatment session: a session create must carry a non-optional `expected_patient_version` matching the patient's current `version`, and a mismatch is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412). A successful session booking likewise increments the patient's `version` by 1. The clinic-level transition endpoints (suspend, resume, close) accept an optional `expected_clinic_version` field; these are not version-guarded creates and are not subject to the patient OCC rule.

### 2.8. The Treatment Clock

The system maintains a logical clinic clock used to evaluate trailing time windows for no-show tracking. An admin-only test-driving capability sets this clock to a supplied instant; the request body carries the new value in a `to_iso8601` field and the response reports the new clock value as `now`. Setting the clock is consequential: it triggers a recomputation of every patient's `no_show_count_window` and `adherence_status` against the new clock value, which can both escalate a patient into a worse adherence tier and, when the clock advances past missed sessions, relax a patient back toward `GOOD_STANDING`.

### 2.9. Validation Order

When several conditions could reject one request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) presence of well-formed `X-User-ID` and `X-User-Role` headers, else `ERR_MISSING_USER_CONTEXT`; (2) the role's permission for the operation, else `ERR_FORBIDDEN_ROLE`; (3) existence of the path resource id, else the matching not-found error; (4) existence and same-clinic resolution of body foreign keys, else `ERR_CROSS_CLINIC_REFERENCE`; (5) the clinic being `OPEN` where required, else `ERR_CLINIC_SUSPENDED`; (6) the target resource being in the correct state for the requested transition, else the relevant state error such as `ERR_INVALID_STATE`, `ERR_SESSION_NOT_COMPLETED`, or `ERR_ORDER_NOT_ACTIVE`; (7) the authorizing order being active and governing the date, else `ERR_ORDER_NOT_ACTIVE`; (8) the service date falling on the shift's day pattern, else `ERR_DATE_NOT_ON_PATTERN`; (9) isolation suitability of the station, else `ERR_ISOLATION_STATION_REQUIRED`; (10) machine HDF support for HDF orders, else `ERR_MODALITY_NOT_SUPPORTED`; (11) dialyzer reuse headroom at completion, else `ERR_DIALYZER_REUSE_EXCEEDED`; (12) station-cell double-booking, else `ERR_STATION_DOUBLE_BOOKED`; (13) machine turnover-buffer overlap, else `ERR_TURNOVER_BUFFER_VIOLATION`; (14) the patient not being adherence-suspended for ad-hoc booking, else `ERR_PATIENT_SUSPENDED`; (15) the standing-slot patient being a resident, else `ERR_TRANSIENT_NO_STANDING_SLOT`; (16) request-body field-level validation, else `ERR_INVALID_REQUEST`; and (17) the optimistic-concurrency version match, else `ERR_STALE_PATIENT_VERSION`. A lower-numbered check that fails masks every higher-numbered one. Field-level body validation (priority 16) governs all `POST` and `PUT` requests; the header, role, and existence checks (priorities 1 through 3) govern every endpoint.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Clinic and Its Inventory

A `ClinicAdmin` creates a clinic by supplying its `name`, and optionally a `time_zone` (defaulting to `UTC`) and a `dialyzer_reuse_limit`. The reuse limit defaults to 12 and caps how many times a single dialyzer may be reused on a machine before mandatory retirement; it is the ceiling enforced when a hemodialysis or hemodiafiltration session is completed. A freshly created clinic opens in `status` `OPEN`. A clinic moves through `OPEN → SUSPENDED → OPEN` cyclically and can be retired permanently via `OPEN → CLOSED`, which is terminal. While a clinic sits in `SUSPENDED`, the system refuses to create new standing slots, treatment sessions, or lab orders for it, rejecting each attempt with `ERR_CLINIC_SUSPENDED`. Suspending and resuming a clinic carry no preconditions. Closing a clinic, however, is blocked while any treatment session in the clinic is still in `BOOKED` or `CHECKED_IN`, which earns `ERR_CLINIC_HAS_ACTIVE_SESSIONS`. When a clinic does close, a three-part cascade fires: first, every standing slot still in `RESERVED` transitions to `RELEASED`; second, each released slot's treatment sessions that were still `BOOKED` transition to `CANCELLED`; and third, every shift still `ACTIVE` transitions to `RETIRED`.

A clinic's shifts define the recurring daily treatment windows. Creating a shift requires the `clinic_id`, a `code` (a human-readable shift code such as MON_AM, unique within the clinic and compared case-sensitively), a `day_pattern`, a `start_minute`, and an `end_minute`; a `turnover_buffer_minutes` is optional. The `day_pattern` is either `MWF` (recurring Monday/Wednesday/Friday) or `TTHS` (recurring Tuesday/Thursday/Saturday). The `start_minute` is the inclusive minute-of-day start in the range 0 through 1439, and the `end_minute` is the exclusive minute-of-day end in the range 1 through 1440; the end must be strictly greater than the start. The `turnover_buffer_minutes` defaults to 45 and is the mandatory disinfection and turnover gap a machine needs after this shift's `end_minute` before the next shift on the same machine may begin. A shift opens `ACTIVE` and can be retired to `RETIRED`; a `RETIRED` shift accepts no new standing slots or sessions.

Machines and the chairs they drive are the scarce physical resource. A machine is created with a `clinic_id`, an `asset_tag` (unique within the clinic, case-sensitive), a `model`, and an optional `supports_hdf` flag (defaulting to false) indicating whether it can run the hemodiafiltration modality. Each machine tracks a `dialyzer_reuse_count`, which begins at 0; this counter is described in the completion and disinfection narratives below. A machine starts `AVAILABLE` and cycles `AVAILABLE → IN_MAINTENANCE → AVAILABLE`, or retires permanently via `AVAILABLE → RETIRED`. A station (the chair) is created with a `clinic_id`, a `chair_label` (unique within the clinic, case-sensitive), the `machine_id` of the machine bolted to it (which must belong to the same clinic), and an optional `isolation_capable` flag (defaulting to false) marking whether it can host patients who require infection isolation. A station starts `ACTIVE` and cycles `ACTIVE → OUT_OF_SERVICE → ACTIVE`.

### 3.2. Taking Equipment Offline Safely

Equipment cannot be pulled from service while a patient is in the chair. A `ClinicAdmin` who starts machine maintenance moves it `AVAILABLE → IN_MAINTENANCE`, but only if no treatment session in `CHECKED_IN` is currently running on a station bound to that machine; otherwise the request is rejected with `ERR_MACHINE_IN_USE`. While a machine is `IN_MAINTENANCE` it cannot host sessions. Completing maintenance moves it `IN_MAINTENANCE → AVAILABLE`; the request may carry a `disinfect` flag, and when `disinfect` is true the machine's `dialyzer_reuse_count` is reset to 0, modeling a fresh dialyzer mount after disinfection. Retiring a machine moves it `AVAILABLE → RETIRED` and is blocked, with `ERR_MACHINE_IN_USE`, while any station bound to that machine has a treatment session still in `BOOKED` or `CHECKED_IN`.

Stations follow a parallel discipline. Taking a station offline moves it `ACTIVE → OUT_OF_SERVICE`, but only when no treatment session in `BOOKED` or `CHECKED_IN` occupies that station; an occupied station is rejected with `ERR_STATION_OCCUPIED`. Bringing a station back online moves it `OUT_OF_SERVICE → ACTIVE` with no precondition. An `OUT_OF_SERVICE` station hosts no sessions, just as an `IN_MAINTENANCE` machine hosts none.

### 3.3. Patients, Payer Class, and the Patient Ledger

A `ClinicAdmin` or a `Scheduler` registers a patient with a `clinic_id`, an `mrn` (medical record number, unique within the clinic, case-sensitive), and a `full_name`. Three classifications are optional at creation. The `patient_kind` is either `RESIDENT` (the default — a standing three-times-weekly roster patient) or `TRANSIENT` (a visiting guest who may only take ad-hoc sessions and may never hold a standing slot). The `payer_class` is either `STANDARD` (the default — full charge) or `CONTRACTED` (an in-network discounted charge); this selects which variant of the session charge applies. The `requires_isolation` flag (default false) marks a patient who must be seated in an isolation-capable station, and `coinsurance_pct` (default 0.0) is the patient's coinsurance fraction between 0 and 1 inclusive, applied to the billed amount of each completed session. A newly created patient starts with `adherence_status` `GOOD_STANDING`, an `account_balance_cents` of 0, and a `no_show_count_window` of 0.

The `account_balance_cents` is a running liability ledger for the patient, recorded in cents and starting at 0. It moves in well-defined steps that the relevant workflows describe: it rises by the patient's coinsurance share when a session completes, rises by the no-show fee when a session is marked missed, and rises by the trip fare when a transport trip is confirmed; it falls by the coinsurance share when a billed session is settled, falls by the trip fare when a confirmed trip is cancelled, and falls by the statement total when a monthly statement is paid. The `no_show_count_window` and `adherence_status` are derived figures maintained automatically and explained in §3.7.

### 3.4. Nephrologist Orders and Their Revision Cycle

Only an `ACTIVE` nephrologist order authorizes treatment, and a patient may hold only one active order at a time. A `Nephrologist` creates an order against a `patient_id`, with a `modality` (one of `HEMODIALYSIS`, `HEMODIAFILTRATION`, or `PERITONEAL`), an `effective_from_date` (an ISO date, `YYYY-MM-DD`), and optionally a `sessions_per_week` (the prescribed weekly frequency, an integer from 1 to 3, defaulting to 3), an `epo_units` count (prescribed EPO units per session, at least 0, defaulting to 0, and priced per whole 1000-unit block), and an `iron_ordered` flag (default false, indicating IV iron is ordered per session as a flat add-on). The order's `clinic_id` is copied from the patient. A new order is created in `DRAFT`.

Activating an order moves it `DRAFT → ACTIVE`, but is rejected with `ERR_ACTIVE_ORDER_EXISTS` if the patient already has another order in `ACTIVE`. On activation the order's `revision_no` is initialized to 1. From `ACTIVE`, the nephrologist may open a revision, moving it `ACTIVE → UNDER_REVISION`, and then commit that revision, moving it `UNDER_REVISION → ACTIVE`. Committing a revision applies any submitted changes to `modality`, `epo_units`, `iron_ordered`, and `sessions_per_week`, and increments `revision_no` by 1. This open-then-commit cycle may repeat. An order's `effective_from_date` governs which sessions it authorizes: it may authorize a session only when the session's `service_date` falls on or after the order's effective date.

Revoking an order moves it from `ACTIVE → REVOKED` (or `UNDER_REVISION → REVOKED`); `REVOKED` is terminal. Revocation triggers the system's deepest cascade, a three-hop ripple. First, every treatment session authorized by this order that is still `BOOKED` transitions to `CANCELLED`. Second, for each such cancelled session, any transport trip in `REQUESTED` or `CONFIRMED` transitions to `CANCELLED`. Third, for each of those transport trips that was in `CONFIRMED` at the moment of cancellation, its fare is reversed out of the patient's ledger — the trip's `fare_cents` is subtracted from the patient's `account_balance_cents`. The cascade out of `UNDER_REVISION → REVOKED` is identical to the one out of `ACTIVE → REVOKED`.

### 3.5. Reserving Chairs: Standing Slots and the Booking Board

A standing slot is a recurring reservation that holds one chair on one shift for one resident patient on every occurrence of the shift's day pattern. A `Scheduler` reserves a standing slot by supplying the `patient_id`, the `shift_id` of the recurring shift, the `station_id` of the recurring chair, and the `expected_patient_version` required by the concurrency guard in §2.7. The slot's `clinic_id` is copied from the patient. A standing slot is created in `RESERVED` and can only move `RESERVED → RELEASED`, which is terminal. A reservation may be created only when the clinic is `OPEN`. Several guards apply to a standing-slot reservation: the patient must be a `RESIDENT`, or the request is rejected with `ERR_TRANSIENT_NO_STANDING_SLOT`; the authorizing order must be `ACTIVE` and govern the relevant date, or `ERR_ORDER_NOT_ACTIVE`; if the patient's `requires_isolation` is true the chosen station must be `isolation_capable`, or `ERR_ISOLATION_STATION_REQUIRED`; and the reserved cell must not collide with an existing reservation or session, or `ERR_STATION_DOUBLE_BOOKED`. Releasing a standing slot transitions it to `RELEASED` and cascades: every treatment session generated from this slot that is still `BOOKED` transitions to `CANCELLED`, and for each such session any transport trip in `REQUESTED` or `CONFIRMED` is cancelled, with a `CONFIRMED` trip's fare reversed from the patient's `account_balance_cents`.

A treatment session is the atomic unit of care. A `Scheduler` books a session with the `patient_id`, the `order_id` of the authorizing order, the `station_id` and `shift_id` to occupy, a `service_date` (an ISO date on which the session occurs), and the `expected_patient_version` for the concurrency guard. Two optional references distinguish how the session arose: `standing_slot_id` is set when the session was generated from a standing slot and is null for an ad-hoc or transient booking, and `rescheduled_from_id` references another treatment session's `id` when this session supersedes a rescheduled one and is null otherwise. The session's `clinic_id` is copied from the patient. A new session is created with `clinical_status` `BOOKED` and `billing_status` `UNBILLED`. Session creation is allowed only when the clinic is `OPEN`, and the authorizing order must be `ACTIVE` with an `effective_from_date` on or before the `service_date`, else `ERR_ORDER_NOT_ACTIVE`.

Several capacity and safety rules guard a booking. The `service_date`'s weekday must fall on the chosen shift's `day_pattern` — Monday, Wednesday, or Friday for `MWF`; Tuesday, Thursday, or Saturday for `TTHS` — or the request is rejected with `ERR_DATE_NOT_ON_PATTERN`. If the patient's `requires_isolation` is true, the chosen station must be `isolation_capable`, else `ERR_ISOLATION_STATION_REQUIRED`. If the order's `modality` is `HEMODIAFILTRATION`, the station's bound machine must have `supports_hdf` true, else `ERR_MODALITY_NOT_SUPPORTED`. No two sessions that are neither `CANCELLED` nor `MISSED` may occupy the same station, shift, and `service_date` combination — a standing slot reserves that cell for every day-pattern occurrence — and a collision is rejected with `ERR_STATION_DOUBLE_BOOKED`. Separately, two non-terminal sessions whose stations share the same machine on the same `service_date` must respect the earlier shift's turnover gap: the earlier shift's `end_minute` plus that shift's `turnover_buffer_minutes` must be less than or equal to the later shift's `start_minute`; if that disinfection gap is violated the booking is rejected with `ERR_TURNOVER_BUFFER_VIOLATION`. This turnover rule is a buffered, half-open adjacency check on the shared machine, distinct from the exact station-cell equality of the double-booking rule. Finally, booking an ad-hoc or transient session is refused with `ERR_PATIENT_SUSPENDED` when the patient's `adherence_status` is `SUSPENDED`.

### 3.6. Running a Session: Check-In, Completion, and Charges

Once booked, a session is worked through its clinical axis by a `Scheduler`. Checking in moves the session `BOOKED → CHECKED_IN`, but only when the station's bound machine is `AVAILABLE` (else `ERR_MACHINE_UNAVAILABLE`) and the station itself is `ACTIVE` (else `ERR_STATION_OFFLINE`). Completing the session moves it `CHECKED_IN → COMPLETED`, which is terminal on the clinical axis. For a `HEMODIALYSIS` or `HEMODIAFILTRATION` session, completion is permitted only when the machine's `dialyzer_reuse_count` is strictly less than the clinic's `dialyzer_reuse_limit`, because completion increments that counter and would otherwise push it to or past the cap; a completion that would breach the cap is rejected with `ERR_DIALYZER_REUSE_EXCEEDED`.

Completion is where money is first recognized. The session's `billed_amount_cents` is computed by the session charge rule. The gross charge is built from the authorizing order: a base amount selected by the order's `modality` — 28,500 cents for `HEMODIALYSIS`, 34,000 cents for `HEMODIAFILTRATION`, and 22,000 cents for `PERITONEAL` — plus an EPO add-on of 1,200 cents for each whole 1,000-unit block of the order's `epo_units` (the number of `epo_units` divided by 1,000 discarding any remainder, multiplied by 1,200 cents), plus a flat iron add-on of 4,500 cents when `iron_ordered` is true and 0 otherwise. That gross is then adjusted by the patient's `payer_class`: for a `CONTRACTED` patient the gross is multiplied by 0.82 (the in-network discount), and for a `STANDARD` patient the gross is taken at full value, multiplied by 1.00. The product is rounded once to whole cents using round-half-up to yield `billed_amount_cents`. Upon completion, the patient's coinsurance share — the `billed_amount_cents` multiplied by the patient's `coinsurance_pct`, rounded half-up to whole cents — is added to the patient's `account_balance_cents`. Also upon completion, if the order's `modality` is `HEMODIALYSIS` or `HEMODIAFILTRATION`, the machine's `dialyzer_reuse_count` is increased by 1. The session's `billing_status` is unaffected by completion and remains `UNBILLED`, because the billing axis evolves independently.

A booked session that the patient does not attend is marked missed by a `Scheduler`, moving it `BOOKED → MISSED`, which is terminal. Marking missed sets the session's `missed_fee_cents` to the flat no-show fee of 7,500 cents, adds that `missed_fee_cents` to the patient's `account_balance_cents`, recomputes the patient's `no_show_count_window` with adherence escalation as described in §3.7, and cancels any transport trip on that session that is still in `REQUESTED` or `CONFIRMED` — reversing a `CONFIRMED` trip's fare out of the ledger. A booked session may instead be cancelled outright, moving it `BOOKED → CANCELLED` (terminal); cancellation likewise cancels any `REQUESTED` or `CONFIRMED` transport trip on the session and reverses a confirmed trip's fare. A cancelled or missed session carries no charge and posts no coinsurance.

### 3.7. No-Show Tracking and Adherence Lifecycle

A patient's discipline is tracked through a 30-day trailing window. The `no_show_count_window` is the count of the patient's `MISSED` sessions whose `service_date` falls on or after the window-start date and on or before the current clinic clock date, where the window-start date is the clock date minus 30 days (an inclusive 30-day trailing window ending at the clock's current date). This count is recomputed both when a session is marked missed and whenever the clinic clock is set, because advancing the clock can carry old missed sessions out of the window.

The count drives an automatic adherence lifecycle on the `adherence_status` axis, which cycles `GOOD_STANDING → AT_RISK → SUSPENDED → GOOD_STANDING`. When the recomputed `no_show_count_window` is at least 5, the patient is `SUSPENDED`; when it is at least 3 but below 5, the patient is `AT_RISK`; and when it is below 3, the patient is `GOOD_STANDING`. These transitions are evaluated automatically on every mark-missed and on every clock change: a patient can escalate `GOOD_STANDING → AT_RISK` when the count reaches 3, escalate to `SUSPENDED` when the count reaches 5 (whether stepping up from `AT_RISK` or jumping straight from `GOOD_STANDING`), and can de-escalate `AT_RISK → GOOD_STANDING` automatically when a clock advance drops the count below 3. A `SUSPENDED` patient is blocked from creating new ad-hoc or transient sessions until reactivated. A `ClinicAdmin` may manually reactivate a suspended patient, moving `adherence_status` `SUSPENDED → GOOD_STANDING`; this manual reactivation overrides only the `adherence_status` and does **not** clear the underlying `no_show_count_window`, which remains at its computed value.

Adherence can also be read as a score. A read of a patient's adherence returns four figures: a `cumulative_score`, a `rolling_score`, the patient's current `no_show_count_window`, and the patient's current `adherence_status`. The two scores are computed over the patient's terminal sessions, considering only those whose `clinical_status` is `COMPLETED` or `MISSED` and excluding `CANCELLED` sessions from both the numerator and the denominator. The qualifying sessions are ordered by `service_date` ascending and then by `created_at` ascending. A score is 100 multiplied by the number of completed sessions in the considered set, divided by the sum of completed and missed sessions in that set, rounded half-up to one decimal place; it is null when the considered set has no completed and no missed sessions. The `cumulative_score` considers all qualifying sessions ever. The `rolling_score` considers only the most recent 8 qualifying sessions in that same ordering — so identical underlying data can yield a different cumulative and rolling percentage.

### 3.8. Transport Coordination and Fares

Door-to-door medical transport wraps around a session. A `Scheduler` requests a transport trip for a session by supplying the `session_id`, a `direction` (`INBOUND` for home-to-clinic or `OUTBOUND` for clinic-to-home), the one-way `miles` (at least 0), and three optional flags: `cross_county` (default false, a county-line zone surcharge), `wheelchair` (default false, a wheelchair-lift flat add-on), and `shared_ride` (default false, a pooled-ride multiplier discount). The trip's `patient_id` is copied from the session. A new trip is created in `REQUESTED` with its `fare_cents` computed immediately.

The fare is built in a pinned order from the trip's own fields. First, the mileage charge is tiered: the first 5 miles cost 250 cents per mile, the next 10 miles (miles beyond 5 up to 15) cost 200 cents per mile, and every mile beyond 15 costs 150 cents per mile. A base flag-drop of 800 cents is added to the mileage charge to form a subtotal. If `shared_ride` is true, that subtotal is multiplied by 0.75; otherwise it is multiplied by 1. This product — the base-plus-mileage subtotal after the shared multiplier — is rounded once to whole cents using round-half-up. Only after that rounding are the flat add-ons applied: 1,500 cents is added when `wheelchair` is true, and 500 cents is added when `cross_county` is true. The sum is the trip's `fare_cents`. The single rounding happens after the shared multiplier and before the flat add-ons.

A trip advances through its own lifecycle. Confirming a trip moves it `REQUESTED → CONFIRMED`, but only when the owning session's `clinical_status` is `BOOKED` or `CHECKED_IN`, else `ERR_SESSION_NOT_SCHEDULABLE`; confirmation adds the trip's `fare_cents` to the patient's `account_balance_cents`. Completing a trip moves it `CONFIRMED → COMPLETED` (terminal), permitted only when the owning session's `clinical_status` is `COMPLETED`, else `ERR_SESSION_NOT_COMPLETED`. A trip may be cancelled from either `REQUESTED → CANCELLED` or `CONFIRMED → CANCELLED` (terminal); cancelling a trip that was in `CONFIRMED` reverses its `fare_cents` back out of the patient's `account_balance_cents`, while cancelling a trip that was still in `REQUESTED` touches no ledger because no fare was ever posted.

### 3.9. Lab Scheduling

Monthly labs are lightweight. A `Nephrologist` or a `Scheduler` schedules a lab order with a `patient_id`, a `panel` (one of `MONTHLY_CHEM`, `CBC`, or `IRON_STUDIES`), and a `scheduled_date` (the planned draw date as an ISO date). The lab's `clinic_id` is copied from the patient, and a lab order may be created only while the clinic is `OPEN`. A lab order is created `SCHEDULED` and reaches a terminal state in one of two ways: a `Scheduler` marks it collected, moving it `SCHEDULED → COLLECTED`; or either a `Scheduler` or a `Nephrologist` cancels it, moving it `SCHEDULED → CANCELLED`.

### 3.10. Session Billing and Monthly Statements

The billing axis of a treatment session evolves independently of its clinical axis and is owned by a `BillingClerk`. The `billing_status` starts at `UNBILLED`. Billing a session moves it `UNBILLED → BILLED`, permitted only when the session's `clinical_status` is `COMPLETED`, else `ERR_SESSION_NOT_COMPLETED`. Settling a billed session moves it `BILLED → SETTLED` (terminal) and subtracts the patient's coinsurance share — the `billed_amount_cents` multiplied by the patient's `coinsurance_pct`, rounded half-up to whole cents — back out of the patient's `account_balance_cents`. Alternatively, a session that was never properly delivered can have its billing voided, moving `UNBILLED → VOID` (terminal); voiding is permitted only when the session's `clinical_status` is `CANCELLED` or `MISSED`, else `ERR_SESSION_NOT_VOIDABLE`.

At month's end a `BillingClerk` issues a monthly statement for a patient and a `period_month` (an ISO month, `YYYY-MM`). Issuing the statement runs the rollup and stamps four computed totals. The `session_count` is the number of the patient's sessions whose `clinical_status` is `COMPLETED`, whose `billing_status` is `BILLED` at run time, and whose `service_date` falls inside the `period_month`. The `coinsurance_due_cents` is the sum, over exactly those included sessions, of each session's `billed_amount_cents` multiplied by the patient's `coinsurance_pct` and rounded half-up to whole cents per session before summing — the rounding is pinned to happen per session and then sum, never sum-then-round. The `missed_fee_total_cents` is the sum of `missed_fee_cents` over the patient's sessions whose `clinical_status` is `MISSED` and whose `service_date` falls inside the `period_month`. The `total_due_cents` is the `coinsurance_due_cents` plus the `missed_fee_total_cents`. A statement's `clinic_id` is copied from the patient and the statement is created `ISSUED`. Paying a statement moves it `ISSUED → PAID` (terminal) and subtracts the `total_due_cents` from the patient's `account_balance_cents`; cancelling a statement moves it `ISSUED → CANCELLED` (terminal) with no ledger effect.

## 4. Endpoint Definitions

All endpoints are mounted under the API root. A successful resource creation returns HTTP 201 with the created resource in `data`; a successful read or state-changing action on an existing resource returns HTTP 200 with the affected resource (or the documented payload). All error responses use the envelope and codes defined above.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/clinics` | Create clinic | ClinicAdmin |
| GET | `/clinics` | List clinics | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/clinics/{clinicId}` | Get clinic | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/clinics/{clinicId}/suspend` | Suspend clinic | ClinicAdmin |
| POST | `/clinics/{clinicId}/resume` | Resume clinic | ClinicAdmin |
| POST | `/clinics/{clinicId}/close` | Close clinic | ClinicAdmin |
| POST | `/shifts` | Create shift | ClinicAdmin |
| GET | `/shifts` | List shifts (filter by clinic_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/shifts/{shiftId}` | Get shift | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/shifts/{shiftId}/retire` | Retire shift | ClinicAdmin |
| POST | `/machines` | Create machine | ClinicAdmin |
| GET | `/machines` | List machines (filter by clinic_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/machines/{machineId}` | Get machine | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/machines/{machineId}/start-maintenance` | Start machine maintenance | ClinicAdmin |
| POST | `/machines/{machineId}/complete-maintenance` | Complete maintenance | ClinicAdmin |
| POST | `/machines/{machineId}/retire` | Retire machine | ClinicAdmin |
| POST | `/stations` | Create station | ClinicAdmin |
| GET | `/stations` | List stations (filter by clinic_id, machine_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/stations/{stationId}` | Get station | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/stations/{stationId}/take-offline` | Take station out of service | ClinicAdmin |
| POST | `/stations/{stationId}/bring-online` | Bring station back online | ClinicAdmin |
| POST | `/patients` | Create patient | ClinicAdmin, Scheduler |
| GET | `/patients` | List patients (filter by clinic_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/patients/{patientId}` | Get patient | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/patients/{patientId}/adherence` | Read computed adherence (both variants) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/patients/{patientId}/reactivate` | Reactivate a SUSPENDED patient (admin override) | ClinicAdmin |
| POST | `/orders` | Create order (DRAFT) | Nephrologist |
| GET | `/orders` | List orders (filter by patient_id, clinic_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/orders/{orderId}` | Get order | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/orders/{orderId}/activate` | Activate order | Nephrologist |
| POST | `/orders/{orderId}/open-revision` | Open order revision | Nephrologist |
| POST | `/orders/{orderId}/commit-revision` | Commit order revision | Nephrologist |
| POST | `/orders/{orderId}/revoke` | Revoke order | Nephrologist |
| POST | `/standing-slots` | Reserve a standing chair/shift slot | Scheduler |
| GET | `/standing-slots` | List standing slots (filter by patient_id, clinic_id, shift_id, station_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/standing-slots/{slotId}` | Get standing slot | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/standing-slots/{slotId}/release` | Release a standing slot | Scheduler |
| POST | `/sessions` | Book a treatment session (standing or ad-hoc/transient) | Scheduler |
| GET | `/sessions` | List sessions (filter by patient_id, order_id, station_id, shift_id, standing_slot_id, rescheduled_from_id, clinic_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/sessions/{sessionId}` | Get session | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/sessions/{sessionId}/check-in` | Check in a booked session | Scheduler |
| POST | `/sessions/{sessionId}/complete` | Complete a session | Scheduler |
| POST | `/sessions/{sessionId}/mark-missed` | Mark a session missed (no-show) | Scheduler |
| POST | `/sessions/{sessionId}/cancel` | Cancel a booked session | Scheduler |
| POST | `/sessions/{sessionId}/bill` | Mark session billed | BillingClerk |
| POST | `/sessions/{sessionId}/settle` | Settle a billed session | BillingClerk |
| POST | `/sessions/{sessionId}/void-billing` | Void billing for a cancelled/missed session | BillingClerk |
| POST | `/transport-trips` | Request a transport trip for a session | Scheduler |
| GET | `/transport-trips` | List transport trips (filter by session_id, patient_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/transport-trips/{tripId}` | Get transport trip | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/transport-trips/{tripId}/confirm` | Confirm a transport trip | Scheduler |
| POST | `/transport-trips/{tripId}/complete` | Complete a transport trip | Scheduler |
| POST | `/transport-trips/{tripId}/cancel` | Cancel a transport trip | Scheduler |
| POST | `/lab-orders` | Schedule a monthly lab | Nephrologist, Scheduler |
| GET | `/lab-orders` | List lab orders (filter by patient_id, clinic_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/lab-orders/{labId}` | Get lab order | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/lab-orders/{labId}/collect` | Mark lab collected | Scheduler |
| POST | `/lab-orders/{labId}/cancel` | Cancel lab order | Scheduler, Nephrologist |
| POST | `/statements` | Issue a monthly statement | BillingClerk |
| GET | `/statements` | List statements (filter by patient_id, clinic_id) | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| GET | `/statements/{statementId}` | Get statement | ClinicAdmin, Scheduler, Nephrologist, BillingClerk |
| POST | `/statements/{statementId}/pay` | Mark statement paid | BillingClerk |
| POST | `/statements/{statementId}/cancel` | Cancel statement | BillingClerk |
| POST | `/_clock/set_current_utc` | Set the clinic system clock (test-driving) | ClinicAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_CLINIC_NOT_FOUND` | 404 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_SHIFT_NOT_FOUND` | 404 |
| `ERR_MACHINE_NOT_FOUND` | 404 |
| `ERR_STATION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_TRIP_NOT_FOUND` | 404 |
| `ERR_LAB_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CROSS_CLINIC_REFERENCE` | 422 |
| `ERR_CLINIC_SUSPENDED` | 409 |
| `ERR_CLINIC_HAS_ACTIVE_SESSIONS` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_NOT_ACTIVE` | 409 |
| `ERR_ACTIVE_ORDER_EXISTS` | 409 |
| `ERR_SESSION_NOT_COMPLETED` | 409 |
| `ERR_SESSION_NOT_VOIDABLE` | 409 |
| `ERR_SESSION_NOT_SCHEDULABLE` | 409 |
| `ERR_DATE_NOT_ON_PATTERN` | 422 |
| `ERR_ISOLATION_STATION_REQUIRED` | 422 |
| `ERR_MODALITY_NOT_SUPPORTED` | 422 |
| `ERR_DIALYZER_REUSE_EXCEEDED` | 409 |
| `ERR_STATION_DOUBLE_BOOKED` | 409 |
| `ERR_TURNOVER_BUFFER_VIOLATION` | 409 |
| `ERR_MACHINE_IN_USE` | 409 |
| `ERR_MACHINE_UNAVAILABLE` | 409 |
| `ERR_STATION_OFFLINE` | 409 |
| `ERR_STATION_OCCUPIED` | 409 |
| `ERR_PATIENT_SUSPENDED` | 409 |
| `ERR_TRANSIENT_NO_STANDING_SLOT` | 422 |
| `ERR_STALE_PATIENT_VERSION` | 412 |
